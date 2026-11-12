"""Human seats in the mission.

* The career pilot always has seat 1 of the assigned flight.
* `coop_slots` (1-4): how many seats of that flight are human.
* `coop_extra_slots`: additional pilots who fly *their own aircraft* in other friendly
  flights of the mission. Each gets a wingman seat (the AI keeps the lead, so the flight still
  does its job if nobody joins). Only aircraft types listed in `coop_modules` (default: every
  flyable type) are offered, and only flights that start on the ground.

A Client seat that nobody occupies simply does not spawn in DCS; the debrief detects unused
seats and does not charge an airframe, fuel or weapons for them.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .. import units
from ..models_ato import Ato
from ..state import State
from . import clock

NOT_FOR_GUESTS = ("AWACS", "TANKER", "SAR")


def is_multiplayer(coop_slots: int, extra: int) -> bool:
    return coop_slots > 1 or extra > 0


def allocate(st: State, ato: Ato, flight_ids: List[str], coop_slots: int, extra: int,
             modules: Optional[List[str]], t0: float) -> Dict[str, List[int]]:
    """{flight id: [unit indexes that are human seats]}."""
    pkg, player = ato.find_flight(ato.player_flight_id or "")
    seats: Dict[str, List[int]] = {}
    if player is None:
        return seats
    seats[player.id] = list(range(min(max(1, coop_slots), player.count)))
    if extra <= 0:
        return seats
    allowed = set(modules) if modules is not None else set(units.flyable_modules())
    allowed &= set(units.flyable_modules())
    in_pkg = {f.id for f in pkg.flights}
    cands = []
    for fid in flight_ids:
        _, f = ato.find_flight(fid)
        if f is None or f.id == player.id or f.coalition != player.coalition:
            continue
        if f.aircraft not in allowed or f.task in NOT_FOR_GUESTS or f.count < 2:
            continue
        if clock.phase(f, t0) != clock.GROUND and f.id not in in_pkg:
            continue                                   # already airborne at mission start
        cands.append(f)
    # same package first, then flights leaving soonest
    cands.sort(key=lambda f: (f.id not in in_pkg, clock.window(f)[0], f.id))
    left = extra
    taken: Dict[str, int] = {}
    while left > 0:
        progressed = False
        for f in cands:
            if left <= 0:
                break
            n = taken.get(f.id, 0)
            if n < f.count - 1:                        # seat 1 stays with the AI flight lead
                taken[f.id] = n + 1
                left -= 1
                progressed = True
        if not progressed:
            break
    for fid, n in taken.items():
        count = ato.find_flight(fid)[1].count
        seats[fid] = list(range(count - n, count))     # the last aircraft of the flight
    return seats


def summary(st: State, ato: Ato, seats: Dict[str, List[int]], manifest: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Slot list for the briefing/GUI."""
    out = []
    by_id = {v["id"]: (name, v) for name, v in manifest.items() if v.get("kind") == "flight"}
    for fid, idx in seats.items():
        pkg, f = ato.find_flight(fid)
        if f is None or not idx:
            continue
        sq = st.squadrons[f.squadron_id]
        out.append({"flight_id": fid, "callsign": f.callsign, "aircraft": f.aircraft, "task": f.task,
                    "seats": len(idx), "positions": [i + 1 for i in idx], "freq": f.freq,
                    "base": st.airbases[sq.airbase_id].name, "squadron": sq.name, "package": pkg.id,
                    "career": f.is_player, "group": by_id.get(fid, ("", {}))[0]})
    out.sort(key=lambda r: (not r["career"], r["callsign"]))
    return out


def unowned_extra(extra: int, seats: Dict[str, List[int]], player_flight: str) -> int:
    """How many requested guest seats could not be placed."""
    placed = sum(len(v) for k, v in seats.items() if k != player_flight)
    return max(0, extra - placed)
