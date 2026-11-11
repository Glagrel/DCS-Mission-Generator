"""Supply network: production at sources, flow along routes, delivery to bases and troops."""
from __future__ import annotations

from typing import Any, Dict, List

from .. import models as M
from ..state import State
from .readiness import scale_munitions

LOCAL_DELIVERY_CAP = 250.0     # tons/turn a node can push to one airbase
GROUND_UNIT_NEED = 20.0        # tons/turn per formation


def _route_flow(st: State, r: M.SupplyRoute) -> float:
    src, dst = st.supply_nodes.get(r.src), st.supply_nodes.get(r.dst)
    if src is None or dst is None or src.coalition != dst.coalition:
        return 0.0
    # a wrecked end point throttles the route; a destroyed one (bridge, rail yard) cuts it
    health = min(src.health, dst.health)
    if health < 0.1:
        return 0.0
    cap = r.capacity * health * (1.0 - r.interdiction)
    return max(0.0, min(cap, src.stock, dst.stock_cap - dst.stock))


def run_supply(st: State, d: Dict[str, Any]) -> Dict[str, Any]:
    lg = d["logistics"]
    report: Dict[str, Any] = {"produced": {}, "moved": {}, "delivered": {}, "starved": []}
    for n in st.supply_nodes.values():
        n.received_last_turn = 0.0
        if n.output > 0 and n.health >= 0.1:
            made = n.output * n.health
            n.stock = min(n.stock_cap, n.stock + made)
            report["produced"][n.id] = round(made, 1)
    # two passes let supplies cross two hops per turn at most
    for _ in range(2):
        for r in sorted(st.supply_routes.values(), key=lambda x: x.id):
            flow = _route_flow(st, r)
            if flow <= 0:
                continue
            st.supply_nodes[r.src].stock -= flow
            dst = st.supply_nodes[r.dst]
            dst.stock += flow
            dst.received_last_turn += flow
            report["moved"][r.id] = round(report["moved"].get(r.id, 0.0) + flow, 1)
    _deliver_airbases(st, lg, report)
    _deliver_ground(st, report)
    for r in st.supply_routes.values():          # interdiction wears off as convoys re-route
        r.interdiction = round(r.interdiction * 0.5, 3) if r.interdiction > 0.02 else 0.0
    return report


def _deliver_airbases(st: State, lg: Dict[str, Any], report: Dict[str, Any]) -> None:
    by_node: Dict[str, List[M.Airbase]] = {}
    for b in st.airbases.values():
        node = st.supply_nodes.get(b.supply_node or "")
        if b.kind == "carrier" and node is None:
            _unrep(st, b, lg, report)
            continue
        if node is None or node.coalition != b.coalition or node.health < 0.1:
            report["starved"].append(b.id)
            continue
        by_node.setdefault(node.id, []).append(b)
    share, per_level = lg["resupply_fuel_share"], lg["tons_per_munition_level"]
    for node_id, bases in by_node.items():
        node = st.supply_nodes[node_id]
        budget = min(node.stock, LOCAL_DELIVERY_CAP * len(bases) * node.health) / len(bases)
        for b in bases:
            kind = "avgas" if st.meta.era_kind == "ww2" else "jet"
            fuel_need = max(0.0, b.fuel_cap - getattr(b.fuel, kind))
            mun_need = max(0.0, 1.0 - b.munition_level) * per_level
            fuel_t = min(fuel_need, budget * share)
            mun_t = min(mun_need, budget - fuel_t)
            fuel_t = min(fuel_need, budget - mun_t)            # use what munitions did not need
            setattr(b.fuel, kind, getattr(b.fuel, kind) + fuel_t)
            scale_munitions(b, b.munition_level + mun_t / per_level)
            node.stock -= fuel_t + mun_t
            if fuel_t + mun_t > 0:
                report["delivered"][b.id] = {"fuel": round(fuel_t, 1), "munitions": round(mun_t, 1)}


def _unrep(st: State, b: M.Airbase, lg: Dict[str, Any], report: Dict[str, Any]) -> None:
    """Carriers are replenished at sea from outside the theater while the group is afloat."""
    group = st.naval_groups.get(b.naval_group or "")
    if group is None or group.health < 0.3:
        report["starved"].append(b.id)
        return
    kind = "avgas" if st.meta.era_kind == "ww2" else "jet"
    fuel_t = min(b.fuel_cap - getattr(b.fuel, kind), b.fuel_cap * 0.12)
    setattr(b.fuel, kind, getattr(b.fuel, kind) + max(0.0, fuel_t))
    scale_munitions(b, b.munition_level + 0.1)
    report["delivered"][b.id] = {"fuel": round(max(0.0, fuel_t), 1), "munitions": 0.1 * lg["tons_per_munition_level"]}


def _deliver_ground(st: State, report: Dict[str, Any]) -> None:
    for g in st.ground_units.values():
        node = st.supply_nodes.get(g.supply_node or "")
        ok = node is not None and node.coalition == g.coalition and node.health >= 0.2 \
            and node.stock >= GROUND_UNIT_NEED
        if ok:
            node.stock -= GROUND_UNIT_NEED
            g.supply = min(1.0, g.supply + 0.25)
        else:
            g.supply = max(0.2, g.supply - 0.2)
            report["starved"].append(g.id)


def network_health(st: State, coalition: str) -> float:
    """0..1 summary of a side's supply net: producer health weighted by output."""
    prod = [n for n in st.supply_nodes.values() if n.coalition == coalition and n.output > 0]
    total = sum(n.output for n in prod)
    return sum(n.output * n.health for n in prod) / total if total else 0.0
