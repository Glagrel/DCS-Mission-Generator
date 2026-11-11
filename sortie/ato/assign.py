"""Player assignment. The player never chooses: the ATO tasks their squadron and one of
that squadron's flights becomes the player's."""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from .. import models as M
from ..models_ato import Ato, Flight, Package
from ..sim.readiness import readiness
from ..state import State
from . import route
from .needs import score_needs
from .radio import RadioPlan, callsign
from ..mission import loadouts


class Assignment(Dict[str, Any]):
    pass


def assign_player(st: State, ato: Ato, d: Dict[str, Any], coop_slots: int = 1) -> Assignment:
    """Mark the player's flight in `ato`. Returns {'flight_id', 'package_id', 'reason'} or
    {'flight_id': None, 'reason': why the player is standing down}."""
    sq = st.player_squadron()
    if sq is None or st.pilot is None:
        return Assignment(flight_id=None, package_id=None, reason="no player pilot")
    if st.pilot.status not in ("active",):
        return Assignment(flight_id=None, package_id=None, reason=f"pilot status is {st.pilot.status}")
    if sq.aircraft not in st.meta.owned_modules:
        return Assignment(flight_id=None, package_id=None,
                          reason=f"{sq.aircraft} is not among your owned modules; awaiting reassignment")
    mine = [(p, f) for p, f in ato.flights() if f.squadron_id == sq.id and f.status == "planned"]
    if not mine:
        made = _force_tasking(st, ato, sq, d)
        if made is None:
            n, why = readiness(st, sq, d)
            return Assignment(flight_id=None, package_id=None,
                              reason=f"{sq.name} is standing down this cycle ({why or 'no suitable tasking'})")
        mine = [made]
    # the flight in the highest-priority package; lead flights before attached escorts
    pkg, flt = max(mine, key=lambda pf: (pf[0].score, pf[1].id.endswith("-1"), pf[1].id))
    flt.is_player = True
    flt.count = max(flt.count, min(4, coop_slots))
    ato.player_flight_id, ato.player_package_id = flt.id, pkg.id
    role = "lead flight" if pkg.flights[0].id == flt.id else f"{flt.task.lower()} support"
    reason = (f"{sq.name} was tasked with {flt.task} as {role} of package {pkg.id} "
              f"({pkg.mission} on {pkg.target.name}). Priority {pkg.score:.0f}: {pkg.reason}.")
    return Assignment(flight_id=flt.id, package_id=pkg.id, reason=reason)


def _force_tasking(st: State, ato: Ato, sq: M.Squadron, d: Dict[str, Any]) -> Optional[Tuple[Package, Flight]]:
    """The squadron got nothing in the main allocation (out-ranged or out-prioritised):
    give it the best need it can fly, if it can fly at all."""
    n, _ = readiness(st, sq, d)
    if n <= 0:
        return None
    for need in score_needs(st, sq.coalition, d):
        if need.mission not in sq.tasks or need.mission in ("AWACS", "TANKER"):
            continue
        pid = f"{sq.coalition[0].upper()}{ato.turn}-{len(ato.packages) + 1:02d}"
        radio = RadioPlan(st.meta.doctrine.get(sq.coalition, "nato"), st.meta.era_kind, sq.coalition)
        radio.n += len(ato.packages)
        pkg = Package(id=pid, coalition=sq.coalition, mission=need.mission, target=need.target,
                      score=round(need.score, 1), reason=need.reason, tot_s=2400.0, freq=radio.next())
        flt = Flight(id=f"{pid}-1", squadron_id=sq.id, coalition=sq.coalition, aircraft=sq.aircraft,
                     count=min(n, need.size), task=need.mission, freq=pkg.freq,
                     callsign=callsign(sq.callsign, 9, st.meta.doctrine.get(sq.coalition, "nato")),
                     loadout=loadouts.pick(sq.aircraft, need.mission))
        flt.waypoints = route.build_route(st, sq.coalition, st.airbases[sq.airbase_id], need.target,
                                          sq.aircraft, need.mission, pkg.tot_s)
        pkg.flights.append(flt)
        ato.packages.append(pkg)
        return pkg, flt
    return None
