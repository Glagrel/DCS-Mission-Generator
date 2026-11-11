"""Squadron readiness and sortie costs (fuel, munitions) against airbase stocks."""
from __future__ import annotations

from typing import Any, Dict, Tuple

from .. import models as M, units
from ..state import State

COMBAT_TASKS = {"CAP", "INTERCEPT", "ESCORT", "SWEEP", "SEAD", "DEAD", "STRIKE", "CAS", "INTERDICTION", "ANTISHIP"}
MIN_RUNWAY = 0.3
MIN_MUNITIONS = 0.05


def fuel_per_aircraft(aircraft: str, d: Dict[str, Any]) -> float:
    return float(d["logistics"]["fuel_per_sortie_t"][units.role_class(aircraft)])


def base_fuel(base: M.Airbase, aircraft: str) -> float:
    return getattr(base.fuel, units.fuel_kind(aircraft))


def readiness(st: State, sq: M.Squadron, d: Dict[str, Any]) -> Tuple[int, str]:
    """(aircraft that can be launched this turn, reason when that is limited/zero)."""
    base = st.airbases.get(sq.airbase_id)
    if base is None or base.coalition != sq.coalition:
        return 0, "no friendly airbase"
    if base.kind == "carrier":
        group = st.naval_groups.get(base.naval_group or "")
        if group is None or group.health < 0.3:
            return 0, "carrier out of action"
    if base.runway_health < MIN_RUNWAY:
        return 0, "runway out of action"
    if sq.available <= 0:
        return 0, "no airframes" if sq.airframes <= 0 else "no pilots"
    by_fuel = int(base_fuel(base, sq.aircraft) // fuel_per_aircraft(sq.aircraft, d))
    if by_fuel <= 0:
        return 0, "no fuel"
    if base.munition_level < MIN_MUNITIONS and set(sq.tasks) & COMBAT_TASKS:
        return 0, "no munitions"
    n = min(sq.available, by_fuel)
    if base.runway_health < 0.7:
        n = max(1, n // 2)
    reason = ""
    if n < sq.available:
        reason = "fuel shortage" if by_fuel < sq.available else "runway damaged"
    return n, reason


def scale_munitions(base: M.Airbase, new_level: float) -> None:
    """Move the generic level and scale the tracked per-weapon counts with it."""
    new_level = max(0.0, min(1.0, new_level))
    old = base.munition_level
    if old > 0.0001:
        ratio = new_level / old
        base.munitions = {k: int(round(v * ratio)) for k, v in base.munitions.items()}
    base.munition_level = new_level


def charge_sortie(st: State, sq: M.Squadron, count: int, task: str, d: Dict[str, Any]) -> None:
    """Deduct fuel and munitions for `count` aircraft flying abstractly."""
    base = st.airbases.get(sq.airbase_id)
    if base is None:
        return
    kind = units.fuel_kind(sq.aircraft)
    setattr(base.fuel, kind, max(0.0, getattr(base.fuel, kind) - fuel_per_aircraft(sq.aircraft, d) * count))
    if task in COMBAT_TASKS:
        use = d["logistics"]["munition_level_per_sortie"] * count * (2.0 if task in ("STRIKE", "CAS", "DEAD",
                                                                                 "INTERDICTION", "ANTISHIP") else 1.0)
        scale_munitions(base, base.munition_level - use)
    sq.sorties_flown += count


def squadron_status(st: State, sq: M.Squadron, d: Dict[str, Any]) -> Dict[str, Any]:
    n, reason = readiness(st, sq, d)
    state = "grounded" if n == 0 else ("limited" if reason else "ready")
    return {"ready": n, "state": state, "reason": reason,
            "strength": round(sq.airframes / max(1, sq.airframes_max), 2)}
