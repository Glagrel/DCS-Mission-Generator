"""Next-assignment logic: the war may move the player to another squadron/aircraft, but only
onto airframes that are owned modules, flyable and in era."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .. import models as M, units
from ..sim.readiness import readiness
from ..state import State

GROUNDED_TURNS_BEFORE_TRANSFER = 2
REINFORCE_EVERY = 5


def eligible_squadrons(st: State, exclude: Optional[str] = None) -> List[M.Squadron]:
    side = st.meta.player_side
    ok = set(st.meta.owned_modules) & set(units.flyable_in_era(st.meta.year, st.meta.era_kind))
    return [s for s in st.side("squadrons", side)
            if s.aircraft in ok and s.id != exclude and s.airframes > 0
            and st.airbases.get(s.airbase_id) is not None and st.airbases[s.airbase_id].coalition == side]


def _transfer(st: State, target: M.Squadron, reason: str) -> Dict[str, Any]:
    old = st.player_squadron()
    if old:
        old.is_player = False
    target.is_player = True
    st.pilot.squadron_id, st.pilot.aircraft = target.id, target.aircraft
    rec = {"turn": st.meta.turn, "from": old.name if old else None, "to": target.name,
           "aircraft": target.aircraft, "reason": reason}
    st.pilot.history.append({"turn": st.meta.turn, "mission": "TRANSFER", "transfer": rec})
    st.meta.features["grounded_turns"] = 0
    return rec


def consider(st: State, d: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Called once per turn after the war has advanced. Returns a transfer record or None."""
    if st.pilot is None or st.pilot.status in ("kia", "pow", "mia"):
        return None
    sq = st.player_squadron()
    side = st.meta.player_side
    n, why = readiness(st, sq, d) if sq else (0, "squadron disbanded")
    grounded = int(st.meta.features.get("grounded_turns", 0))
    grounded = grounded + 1 if n == 0 else 0
    st.meta.features["grounded_turns"] = grounded
    options = eligible_squadrons(st, exclude=sq.id if sq else None)

    def best() -> Optional[M.Squadron]:
        ready = [(readiness(st, s, d)[0], s) for s in options]
        ready = [(r, s) for r, s in ready if r > 0]
        # prefer the same airframe, then the squadron that most needs pilots
        return max(ready, key=lambda x: (x[1].aircraft == st.pilot.aircraft,
                                         1 - x[1].pilots / max(1, x[1].pilots_max), x[0], x[1].id))[1] if ready else None

    if sq is None or sq.airframes <= 0:
        t = best()
        return _transfer(st, t, f"{sq.name if sq else 'Your squadron'} has no aircraft left") if t else None
    if sq.aircraft not in st.meta.owned_modules:
        t = best()
        return _transfer(st, t, f"{sq.aircraft} is no longer among your owned modules") if t else None
    if grounded >= GROUNDED_TURNS_BEFORE_TRANSFER:
        t = best()
        return _transfer(st, t, f"{sq.name} grounded for {grounded} cycles ({why})") if t else None
    if st.meta.turn % REINFORCE_EVERY == 0 and sq.pilots / max(1, sq.pilots_max) > 0.8:
        short = [s for s in options if s.pilots / max(1, s.pilots_max) < 0.5 and readiness(st, s, d)[0] > 0]
        if short:
            t = min(short, key=lambda s: (s.pilots / max(1, s.pilots_max), s.id))
            return _transfer(st, t, f"{t.name} is short of pilots ({t.pilots}/{t.pilots_max}); "
                                    f"experienced pilots are being transferred in")
    return None
