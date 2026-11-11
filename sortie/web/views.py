"""Read-only views of campaign state shaped for the GUI (pure functions, unit-testable)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .. import geo, units
from ..campaign import playable_squadrons
from ..sim.readiness import squadron_status
from ..sim.supply import network_health
from ..state import State
from ..theater import Theater


def theater_card(t: Theater, owned: List[str]) -> Dict[str, Any]:
    from .. import terrain
    sides = {}
    for side, co in t.coalitions.items():
        ok = set(playable_squadrons(t, side, owned))
        sides[side] = {
            "name": co.name, "countries": co.countries, "capabilities": co.capabilities, "doctrine": co.doctrine,
            "squadrons": [{"id": s.id, "name": s.name, "aircraft": s.aircraft, "airbase": s.airbase,
                           "tasks": s.tasks, "airframes": s.airframes, "playable": s.id in ok,
                           "flyable": s.aircraft in units.flyable_modules(),
                           "owned": s.aircraft in owned} for s in t.squadrons if s.coalition == side]}
    return {"id": t.id, "name": t.name, "description": t.description, "terrain": t.terrain,
            "year": t.era.year, "era": t.era.kind, "restrictions": t.era.restrictions, "start": t.start.model_dump(),
            "sides": sides, "terrain_supported": terrain.is_supported(t.terrain),
            "terrain_fallback": terrain.is_supported(t.terrain) and terrain.is_fallback(t.terrain)}


def overview(st: State, d: Dict[str, Any]) -> Dict[str, Any]:
    sq = st.player_squadron()
    m = st.meta
    return {
        "meta": {"name": m.name, "template": m.template_id, "turn": m.turn, "date": m.date, "status": m.status,
                 "side": m.player_side, "difficulty": m.difficulty, "war_score": m.war_score, "era": m.era_kind,
                 "coalitions": m.coalition_names, "weather": m.weather, "terrain": m.terrain},
        "pilot": st.pilot.model_dump(exclude={"history"}) if st.pilot else None,
        "squadron": ({**sq.model_dump(), **squadron_status(st, sq, d),
                      "airbase": st.airbases[sq.airbase_id].name} if sq else None),
        "sortie": ({"state": st.sortie.state, "miz_path": st.sortie.miz_path} if st.sortie else None),
        "has_ato": st.ato is not None,
    }


def map_data(st: State) -> Dict[str, Any]:
    side = st.meta.player_side
    fronts = []
    for f in st.fronts.values():
        a, b = (f.a.lat, f.a.lon), (f.b.lat, f.b.lon)
        fronts.append({"id": f.id, "name": f.name, "line": geo.front_line(a, b, f.position, f.width_km),
                       "axis": [a, b], "position": f.position, "pressure": f.pressure})
    routes = []
    for r in st.supply_routes.values():
        s, e = st.supply_nodes.get(r.src), st.supply_nodes.get(r.dst)
        if s and e:
            routes.append({"id": r.id, "coalition": s.coalition, "kind": r.kind, "interdiction": r.interdiction,
                           "capacity": r.capacity, "line": [(s.lat, s.lon), (e.lat, e.lon)]})
    player_route, packages = [], []
    if st.ato:
        _, flt = st.ato.find_flight(st.ato.player_flight_id or "")
        if flt:
            player_route = [{"name": w.name, "lat": w.lat, "lon": w.lon} for w in flt.waypoints]
        for p in st.ato.packages:
            if p.coalition == side:
                packages.append({"id": p.id, "mission": p.mission, "lat": p.target.lat, "lon": p.target.lon,
                                 "name": p.target.name, "player": p.id == st.ato.player_package_id})
    return {
        "side": side, "turn": st.meta.turn,
        "bullseye": {k: {"lat": v.lat, "lon": v.lon} for k, v in st.meta.bullseye.items()},
        "airbases": [{"id": b.id, "name": b.name, "kind": b.kind, "coalition": b.coalition, "lat": b.lat,
                      "lon": b.lon, "runway": b.runway_health, "fuel": round(b.fuel.jet + b.fuel.avgas, 1),
                      "munitions": b.munition_level,
                      "squadrons": [f"{s.name} ({s.airframes} {s.aircraft})" for s in st.squadrons.values()
                                    if s.airbase_id == b.id]} for b in st.airbases.values()],
        "fronts": fronts,
        "ground": [{"id": g.id, "name": g.name, "coalition": g.coalition, "lat": g.lat, "lon": g.lon,
                    "strength": g.strength, "supply": g.supply} for g in st.ground_units.values()],
        "sams": [{"id": s.id, "name": s.name, "coalition": s.coalition, "type": s.template, "role": s.role,
                  "lat": s.lat, "lon": s.lon, "range_km": s.range_km, "health": s.health}
                 for s in st.sam_sites.values() if s.coalition == side or s.known],
        "nodes": [{"id": n.id, "name": n.name, "kind": n.kind, "coalition": n.coalition, "lat": n.lat,
                   "lon": n.lon, "health": n.health, "stock": round(n.stock, 0), "output": n.output}
                  for n in st.supply_nodes.values()],
        "routes": routes,
        "naval": [{"id": n.id, "name": n.name, "coalition": n.coalition, "lat": n.lat, "lon": n.lon,
                   "health": n.health, "role": n.role, "units": n.units} for n in st.naval_groups.values()],
        "player_route": player_route, "packages": packages,
    }


def ato_view(st: State) -> Dict[str, Any]:
    if st.ato is None:
        return {"turn": st.meta.turn, "packages": [], "player_flight_id": None}
    pk = []
    for p in sorted(st.ato.packages, key=lambda x: (x.coalition != st.meta.player_side, x.tot_s, x.id)):
        if p.coalition != st.meta.player_side:
            continue                                    # the enemy's ATO is not ours to read
        pk.append({"id": p.id, "mission": p.mission, "target": p.target.name, "tot_s": p.tot_s,
                   "score": p.score, "reason": p.reason, "freq": p.freq,
                   "player": p.id == st.ato.player_package_id,
                   "flights": [{"id": f.id, "callsign": f.callsign, "aircraft": f.aircraft, "count": f.count,
                                "task": f.task, "squadron": st.squadrons[f.squadron_id].name,
                                "player": f.is_player, "status": f.status, "loadout": f.loadout}
                               for f in p.flights]})
    return {"turn": st.ato.turn, "packages": pk, "player_flight_id": st.ato.player_flight_id,
            "support": {k: v for k, v in st.ato.support.items() if k == st.meta.player_side}}


def roster(st: State, d: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for s in sorted(st.side("squadrons", st.meta.player_side), key=lambda x: (not x.is_player, x.name)):
        b = st.airbases.get(s.airbase_id)
        out.append({**s.model_dump(), **squadron_status(st, s, d), "airbase": b.name if b else "-",
                    "owned": s.aircraft in st.meta.owned_modules,
                    "flyable": s.aircraft in units.flyable_modules()})
    return out


def logistics(st: State) -> Dict[str, Any]:
    side = st.meta.player_side
    bases = []
    for b in sorted(st.airbases.values(), key=lambda x: (x.coalition != side, x.name)):
        top = sorted(b.munitions.items(), key=lambda kv: -kv[1])[:12]
        bases.append({"id": b.id, "name": b.name, "coalition": b.coalition, "kind": b.kind,
                      "fuel": b.fuel.model_dump(), "fuel_cap": b.fuel_cap, "munition_level": b.munition_level,
                      "weapons_tracked": len(b.munitions), "weapons": [{"item": k, "count": v} for k, v in top],
                      "runway": b.runway_health, "supply_node": b.supply_node, "hit": b.hit_last_turn,
                      "aircraft": sum(s.airframes for s in st.squadrons.values() if s.airbase_id == b.id)})
    return {
        "bases": bases,
        "nodes": [n.model_dump() for n in sorted(st.supply_nodes.values(), key=lambda x: (x.coalition != side, x.kind))],
        "routes": [{**r.model_dump(), "src_name": st.supply_nodes[r.src].name, "dst_name": st.supply_nodes[r.dst].name,
                    "coalition": st.supply_nodes[r.src].coalition}
                   for r in st.supply_routes.values() if r.src in st.supply_nodes and r.dst in st.supply_nodes],
        "network": {s: round(network_health(st, s), 2) for s in ("blue", "red")},
    }


def career_view(st: State) -> Optional[Dict[str, Any]]:
    if st.pilot is None:
        return None
    p = st.pilot.model_dump()
    sq = st.player_squadron()
    p["squadron_name"] = sq.name if sq else "-"
    p["qualifications"] = sorted({h.get("aircraft") for h in st.pilot.history if h.get("aircraft")} | {st.pilot.aircraft})
    p["history"] = list(reversed(p["history"]))
    return p
