"""Ground war: front movement, attrition, capture of bases/nodes overrun by the line."""
from __future__ import annotations

import math
from typing import Any, Dict, List

from .. import geo, models as M
from ..campaign import place_ground_units
from ..state import State


def side_strength(st: State, front_id: str, side: str) -> float:
    return sum(sum(g.units.values()) * g.strength * (0.4 + 0.6 * g.supply)
               for g in st.ground_units.values() if g.front_id == front_id and g.coalition == side)


def axis_param(front: M.Front, lat: float, lon: float) -> tuple[float, float]:
    """(t along the a->b axis, distance from the axis in km) for a point."""
    a, b = (front.a.lat, front.a.lon), (front.b.lat, front.b.lon)
    L = max(1.0, geo.dist_km(a, b))
    d = geo.dist_km(a, (lat, lon))
    ang = math.radians(geo.bearing(a, (lat, lon)) - geo.bearing(a, b))
    return d * math.cos(ang) / L, abs(d * math.sin(ang))


def run_ground(st: State, d: Dict[str, Any]) -> Dict[str, Any]:
    g = d["ground"]
    rng = st.rng("ground")
    report: Dict[str, Any] = {"fronts": {}, "captured": []}
    for f in st.fronts.values():
        b, r = side_strength(st, f.id, "blue"), side_strength(st, f.id, "red")
        air = f.cas_effect.get("blue", 0.0) - f.cas_effect.get("red", 0.0)
        balance = (b - r) / (b + r) if b + r > 0 else 0.0
        push = max(-1.0, min(1.0, balance * 1.5 + air * 2.0 + rng.uniform(-0.15, 0.15)))
        old = f.position
        f.position = round(max(0.02, min(0.98, f.position + g["front_step"] * push)), 4)
        f.pressure = round(push, 3)
        f.cas_effect = {}
        for u in st.ground_units.values():
            if u.front_id != f.id:
                continue
            enemy = r if u.coalition == "blue" else b
            own = b if u.coalition == "blue" else r
            ratio = enemy / own if own > 0 else 2.0
            u.strength = round(max(0.05, u.strength - g["attrition"] * min(2.0, ratio) * rng.uniform(0.5, 1.2)), 3)
        report["fronts"][f.id] = {"from": old, "to": f.position, "pressure": f.pressure,
                                  "blue": round(b, 1), "red": round(r, 1)}
        report["captured"] += _captures(st, f)
    place_ground_units(st)
    _war_score(st)
    return report


def _captures(st: State, f: M.Front) -> List[str]:
    """Anything within the front's corridor that is now behind enemy lines changes hands."""
    out: List[str] = []
    corridor = f.width_km * 1.5
    margin = 0.02

    def overrun(coalition: str, lat: float, lon: float) -> bool:
        t, off = axis_param(f, lat, lon)
        if off > corridor or not -0.2 <= t <= 1.2:
            return False
        # blue holds the a-side (t < position), red the b-side
        return t > f.position + margin if coalition == "blue" else t < f.position - margin

    for b in st.airbases.values():
        if b.kind == "airfield" and overrun(b.coalition, b.lat, b.lon):
            b.coalition = M.enemy_of(b.coalition)
            b.runway_health = min(b.runway_health, 0.4)
            b.fuel = M.Fuel(jet=b.fuel.jet * 0.2, avgas=b.fuel.avgas * 0.2, diesel=b.fuel.diesel * 0.2)
            b.munitions, b.munition_level, b.supply_node = {}, 0.1, _nearest_node(st, b)
            _evacuate(st, b)
            out.append(f"airbase:{b.id}")
    for n in st.supply_nodes.values():
        if overrun(n.coalition, n.lat, n.lon):
            n.coalition = M.enemy_of(n.coalition)
            n.health, n.stock = min(n.health, 0.3), n.stock * 0.3
            out.append(f"supply_node:{n.id}")
    for s in st.sam_sites.values():
        if s.health > 0 and overrun(s.coalition, s.lat, s.lon):
            s.health = 0.0
            out.append(f"sam_site:{s.id}")
    return out


def _nearest_node(st: State, b: M.Airbase):
    nodes = [n for n in st.supply_nodes.values() if n.coalition == b.coalition]
    return min(nodes, key=lambda n: geo.dist_km((n.lat, n.lon), (b.lat, b.lon))).id if nodes else None


def _evacuate(st: State, base: M.Airbase) -> None:
    """Squadrons at a captured base fall back to the nearest friendly airfield, losing aircraft."""
    for sq in st.squadrons.values():
        if sq.airbase_id != base.id:
            continue
        homes = [b for b in st.airbases.values() if b.coalition == sq.coalition and b.kind == "airfield"]
        sq.airframes = int(sq.airframes * 0.7)
        if homes:
            sq.airbase_id = min(homes, key=lambda b: geo.dist_km((b.lat, b.lon), (base.lat, base.lon))).id
        else:
            sq.airframes = 0


def _war_score(st: State) -> None:
    if not st.fronts:
        return
    avg = sum(f.position for f in st.fronts.values()) / len(st.fronts)
    st.meta.war_score = round((avg - 0.5) * 2, 3)
    if all(f.position >= 0.97 for f in st.fronts.values()):
        st.meta.status = "won" if st.meta.player_side == "blue" else "lost"
    elif all(f.position <= 0.03 for f in st.fronts.values()):
        st.meta.status = "lost" if st.meta.player_side == "blue" else "won"
