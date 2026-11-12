"""Which static aircraft to park on each carrier / LHA deck, and how many spots to leave free.

The placing itself happens in the mission (sortie_deck.lua), from the ship's live parking
table, because only DCS knows which deck spots exist and which ones are taken. This side
decides *what* to park (the squadrons' airframes that are not flying this mission, so the
deck shows the air wing that has already recovered or is waiting to launch) and the
`reserve`: every aircraft that spawns on or recovers to that deck during the mission, plus a
margin. The Lua never fills a spot out of the reserve, so the AI always has a spot to spawn
on and a spot to taxi to after landing.
"""
from __future__ import annotations

from typing import Any, Dict, List

from .. import mods, units
from ..models_ato import Ato
from ..state import State
from .budget import Selection

CVN_TYPES = {"CVN_71", "CVN_72", "CVN_73", "CVN_75", "Stennis", "VINSON", "Forrestal"}
LHA_TYPES = {"LHA_Tarawa", "hms_invincible"}
MARGIN = 4               # spots kept free on top of the aircraft that use the deck this mission
LHA_CAP = 4              # a small deck: never more than this many statics


def ship_kind(type_id: str):
    if type_id in CVN_TYPES:
        return "cvn"
    if type_id in LHA_TYPES:
        return "lha"
    return None


def plan(st: State, ato: Ato, sel: Selection, ships: Dict[str, Any], fb, settings) -> List[Dict[str, Any]]:
    out = []
    flying: Dict[str, int] = {}                       # squadron -> aircraft in this mission
    for fid in sel.flights:
        _, f = ato.find_flight(fid)
        flying[f.squadron_id] = flying.get(f.squadron_id, 0) + f.count
    for nid, sg in ships.items():
        n = st.naval_groups[nid]
        base = st.airbases.get(n.airbase_id or "")
        kind = ship_kind(n.units[0]) if n.units else None
        if base is None or kind is None or st.meta.doctrine.get(base.coalition, "nato") != "nato":
            continue
        squads = [s for s in st.squadrons.values() if s.airbase_id == base.id]
        users = sum(flying.get(s.id, 0) for s in squads)
        pool: List[List[str]] = []
        for s in sorted(squads, key=lambda s: s.id):
            ac, _, _ = mods.flown_type(s.aircraft, "SAR" if "SAR" in s.tasks else "")
            if units.aircraft_type(ac) is None:
                continue
            idle = max(0, min(s.airframes, s.pilots) - flying.get(s.id, 0))
            pool.append([ac] * min(idle, 6))
        types: List[str] = []
        while any(pool):                              # round robin: a mixed deck, not one type
            for lst in pool:
                if lst:
                    types.append(lst.pop())
        cap = int(settings.deck_statics_max)
        if kind == "lha":
            cap = min(cap, LHA_CAP)
        types = types[:max(0, cap)]
        if not types:
            continue
        out.append({"carrier_unit": sg.units[0].name, "kind": kind, "types": types, "max": len(types),
                    "reserve": users + MARGIN})
    return out
