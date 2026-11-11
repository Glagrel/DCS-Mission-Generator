"""Apply an analysed mission (runtime.aar) to the campaign: losses, damage, stocks, career."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .. import geo, models as M
from ..mission import warehouses
from ..models_ato import A2A, Ato, FlightResult, SortieResult
from ..runtime import aar
from ..sim import airwar
from ..sim.readiness import charge_sortie
from ..state import State
from . import career

log = logging.getLogger("sortie.debrief")
STRIKE_TASKS = ("STRIKE", "DEAD", "SEAD", "INTERDICTION", "ANTISHIP", "CAS")


def _target_damage(facts: Dict[str, Any], st: State, pkg) -> float:
    """Fraction of the package target destroyed in DCS (0..1)."""
    t = pkg.target
    if t.kind == "front":
        ents = [v for k, v in facts["entities"].items() if k.startswith("ground_unit:")
                and st.ground_units.get(k.split(":", 1)[1]) is not None
                and st.ground_units[k.split(":", 1)[1]].front_id == t.id
                and st.ground_units[k.split(":", 1)[1]].coalition != pkg.coalition]
    else:
        ents = [facts["entities"].get(f"{t.kind}:{t.id}")] if f"{t.kind}:{t.id}" in facts["entities"] else []
    spawned = sum(e["spawned"] for e in ents)
    return sum(e["lost"] for e in ents) / spawned if spawned else 0.0


def flight_success(st: State, ato: Ato, pkg, flt, f: Dict[str, Any], facts: Dict[str, Any]) -> float:
    alive = max(0, flt.count - f["lost"])
    survival = alive / flt.count if flt.count else 0.0
    if flt.task in A2A or flt.task == "INTERCEPT":
        if flt.task == "ESCORT":
            lead = facts["flights"].get(pkg.flights[0].id, {"lost": 0})
            protected = 1.0 - min(1.0, lead["lost"] / max(1, pkg.flights[0].count))
            return round(0.5 * survival + 0.5 * protected, 2)
        return round(min(1.0, 0.6 * survival + 0.2 * f["kills_air"] + (0.2 if f["took_off"] or alive else 0)), 2)
    if flt.task in STRIKE_TASKS:
        dmg = _target_damage(facts, st, pkg)
        own = f["kills_ground"] + f["kills_structure"] + f["kills_naval"]
        if pkg.target.kind == "airbase":            # runway hits are not reported by DCS events
            return round(min(1.0, 0.25 * f["shots"]) * (0.5 + 0.5 * survival), 2)
        return round(min(1.0, max(dmg / 0.3, own / 3.0)), 2)
    return round(survival if f["took_off"] or f["landed"] or alive else 0.0, 2)


def ingest(st: State, ato: Ato, sortie: SortieResult, events: List[Dict[str, Any]],
           d: Dict[str, Any]) -> SortieResult:
    """Mutates `st` and `ato` from one mission run's events. Returns the filled SortieResult."""
    manifest = sortie.summary.get("manifest", {})
    player_group = sortie.summary.get("player_group", "")
    facts = aar.analyze(events, manifest, player_group)
    rng = st.rng("debrief")
    side = st.meta.player_side
    consequences: List[str] = []

    # --- flights flown in DCS --------------------------------------------------------------
    readback_bases = set(facts["warehouses"])
    for name, v in manifest.items():
        if v.get("kind") != "flight":
            continue
        pkg, flt = ato.find_flight(v["id"])
        if flt is None:
            continue
        f = facts["flights"][flt.id]
        res = FlightResult(flight_id=flt.id, lost=min(flt.count, f["lost"]),
                           pilots_lost=min(flt.count, f["pilots_lost"]), kills_air=f["kills_air"],
                           kills_ground=f["kills_ground"], kills_naval=f["kills_naval"],
                           kills_structure=f["kills_structure"], simulated=True)
        res.success = flight_success(st, ato, pkg, flt, f, facts)
        sq = st.squadrons.get(flt.squadron_id)
        if sq:
            sq.airframes = max(0, sq.airframes - res.lost)
            pilots = res.pilots_lost - (1 if flt.is_player and facts["player"]["dead"] else 0)
            sq.pilots = max(0, sq.pilots - max(0, pilots))
            sq.losses += res.lost
            sq.kills += res.kills_air
            if v.get("airborne_start") or sq.airbase_id not in readback_bases:
                charge_sortie(st, sq, flt.count, flt.task, d)      # nothing drawn from a DCS warehouse
            else:
                sq.sorties_flown += flt.count
        # effects DCS events cannot report: runway damage and CAS pressure on the front
        if flt.task in STRIKE_TASKS and pkg.target.kind in ("airbase", "front") and res.success > 0:
            power = (flt.count - res.lost) * res.success
            airwar.apply_strike(st, pkg, flt, power, FlightResult(flight_id="x"), rng)
        flt.status, flt.result = "simulated", res.model_dump()
        sortie.flights[flt.id] = res

    # --- destroyed objects -------------------------------------------------------------------
    for key, e in facts["entities"].items():
        if e["spawned"] <= 0 or e["lost"] <= 0:
            continue
        frac = min(1.0, e["lost"] / e["spawned"])
        kind, eid = key.split(":", 1)
        sortie.entity_damage[key] = round(frac, 3)
        sortie.entity_units_lost[key] = e["lost"]
        if kind == "sam_site" and eid in st.sam_sites:
            s = st.sam_sites[eid]
            s.health = round(s.health * (1 - frac), 3)
            consequences.append(f"{s.name}: {frac:.0%} destroyed")
        elif kind == "ground_unit" and eid in st.ground_units:
            g = st.ground_units[eid]
            g.strength = round(max(0.05, g.strength * (1 - 0.8 * frac)), 3)
            consequences.append(f"{g.name}: lost {e['lost']} vehicles")
        elif kind == "supply_node" and eid in st.supply_nodes:
            n = st.supply_nodes[eid]
            n.health = round(max(0.0, n.health - e["lost"] / max(1, n.n_objects)), 3)
            n.stock = round(n.stock * (1 - 0.5 * frac), 1)
            consequences.append(f"{n.name}: {e['lost']} of {n.n_objects} structures destroyed")
        elif kind == "supply_route" and eid in st.supply_routes:
            r = st.supply_routes[eid]
            r.interdiction = round(min(1.0, r.interdiction + frac), 3)
            consequences.append(f"Convoy route {eid.replace('__', ' -> ')}: {frac:.0%} interdicted")
        elif kind == "naval_group" and eid in st.naval_groups:
            n = st.naval_groups[eid]
            n.health = round(n.health * (1 - frac), 3)
            consequences.append(f"{n.name}: {e['lost']} ships lost")

    # --- airbases: capture events and warehouse readback ---------------------------------------
    for c in facts["captured"]:
        for b in st.airbases.values():
            if b.dcs_name == c["place"] and c["coalition"] in ("blue", "red") and b.coalition != c["coalition"]:
                b.coalition = c["coalition"]
                consequences.append(f"{b.name} captured by {st.meta.coalition_names.get(b.coalition, b.coalition)}")
    notes = warehouses.apply_readback(st, facts["warehouses"], d["logistics"])
    sortie.warehouses = facts["warehouses"]

    # --- the player ----------------------------------------------------------------------------
    p = dict(facts["player"])
    pkg, flt = ato.find_flight(ato.player_flight_id or "")
    success = sortie.flights[flt.id].success if flt and flt.id in sortie.flights else 0.0
    flew = p["took_off"] or p["entered"] or p["flight_time_s"] > 0
    if p.get("pos") and (p["ejected"] or p["crashed"]):
        p["ejected_over_enemy"] = _over_enemy(st, side, p["pos"])
    career_update: Dict[str, Any] = {"promoted": None, "awards": [], "status": st.pilot.status if st.pilot else ""}
    if st.pilot and flew:
        if not p["took_off"]:
            success = 0.0
        career_update = career.update_career(st.pilot, p, success, st.meta.turn, flt.task if flt else "?",
                                             st.meta.doctrine.get(side, "nato"), side, st.meta.era_kind, rng)
    sortie.state = "flown" if flew else "skipped"
    sortie.flight_time_s = p["flight_time_s"]
    sortie.player = {**p, "success": success, **{f"career_{k}": v for k, v in career_update.items()}}
    sortie.mission_success = success >= 0.5 if flew else None
    sortie.timeline = facts["timeline"][-400:]
    blue = sum(r.lost for fid, r in sortie.flights.items() if ato.find_flight(fid)[1].coalition == "blue")
    red = sum(r.lost for fid, r in sortie.flights.items() if ato.find_flight(fid)[1].coalition == "red")
    sortie.summary.update({
        "duration_s": facts["duration_s"], "ended": facts["ended"], "aircraft_lost": {"blue": blue, "red": red},
        "consequences": consequences, "warehouse_notes": notes, "events": len(events),
        "task": flt.task if flt else None, "target": pkg.target.name if pkg else None,
    })
    log.info("sortie ingested", extra={"turn": st.meta.turn, "events": len(events), "success": success})
    return sortie


def _over_enemy(st: State, side: str, pos: Dict[str, Any]) -> bool:
    """Enemy territory = beyond the nearest front line, else nearest airbase belongs to the enemy."""
    from ..sim.ground import axis_param
    here = (pos.get("lat", 0.0), pos.get("lon", 0.0))
    for f in st.fronts.values():
        t, off = axis_param(f, here[0], here[1])
        if off < f.width_km * 3 and -0.5 <= t <= 1.5:
            return t > f.position if side == "blue" else t < f.position
    bases = sorted(st.airbases.values(), key=lambda b: geo.dist_km((b.lat, b.lon), here))
    return bool(bases) and bases[0].coalition != side
