"""End-of-turn pipeline: resolve the rest of the ATO, fight the ground war, move supplies,
produce and repair, then advance the clock."""
from __future__ import annotations

import logging
from typing import Any, Dict, Iterable

from ..debrief.career import recover_status
from ..state import State
from . import airwar, ground, production, supply

log = logging.getLogger("sortie.sim")


def end_turn(st: State, d: Dict[str, Any], flown_in_dcs: Iterable[str] = ()) -> Dict[str, Any]:
    """Mutates `st`. `flown_in_dcs` = flight ids already resolved from DCS events."""
    turn = st.meta.turn
    report: Dict[str, Any] = {"turn": turn, "date": st.meta.date}
    report["air"] = airwar.resolve_ato(st, st.ato, d, flown_in_dcs)
    report["ground"] = ground.run_ground(st, d)
    report["supply"] = supply.run_supply(st, d)
    report["replacements"] = production.replacements(st, d, st.meta.production)
    report["repairs"] = production.repairs(st, d)
    _drift_weather(st)
    _move_naval(st)
    if st.pilot:
        recover_status(st.pilot)
    st.advance_clock()
    st.ato, st.sortie = None, None
    report["war_score"] = st.meta.war_score
    report["status"] = st.meta.status
    log.info("turn %s resolved", turn, extra={"turn": turn, "war_score": st.meta.war_score})
    return report


def _drift_weather(st: State) -> None:
    """Small random walk so consecutive sorties do not fly in identical weather."""
    w, rng = st.meta.weather, st.rng("weather")
    if not w:
        return
    w["wind_dir"] = int((w.get("wind_dir", 0) + rng.randint(-30, 30)) % 360)
    w["wind_ms"] = max(0, min(15, w.get("wind_ms", 3) + rng.randint(-2, 2)))
    w["cloud_density"] = max(0, min(9, w.get("cloud_density", 3) + rng.randint(-2, 2)))
    w["cloud_base_m"] = max(300, min(5000, w.get("cloud_base_m", 2000) + rng.randint(-400, 400)))


def _move_naval(st: State) -> None:
    """Groups with a track shuttle between its end points; carriers drag their airbase along."""
    for n in st.naval_groups.values():
        if n.health <= 0 or len(n.track) < 2:
            continue
        here = min(range(len(n.track)), key=lambda i: abs(n.track[i].lat - n.lat) + abs(n.track[i].lon - n.lon))
        nxt = n.track[(here + 1) % len(n.track)]
        n.lat, n.lon = nxt.lat, nxt.lon
        if n.airbase_id and n.airbase_id in st.airbases:
            st.airbases[n.airbase_id].lat, st.airbases[n.airbase_id].lon = n.lat, n.lon
