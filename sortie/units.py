"""pydcs unit-type lookup, era filtering and coarse capability ratings."""
from __future__ import annotations

from functools import lru_cache
from typing import Any, Dict, List, Optional

import yaml
from dcs import helicopters, planes, ships, vehicles

from . import paths

DEFAULT_YEAR = 2000
# SORTIE mission type -> pydcs task name(s) that qualify an airframe for it
TASK_MAP: Dict[str, List[str]] = {
    "CAP": ["CAP", "Intercept", "Fighter Sweep"],
    "INTERCEPT": ["Intercept", "CAP"],
    "ESCORT": ["Escort", "CAP"],
    "SWEEP": ["Fighter Sweep", "CAP"],
    "SEAD": ["SEAD"],
    "DEAD": ["SEAD", "Pinpoint Strike", "Ground Attack"],
    "STRIKE": ["Ground Attack", "Pinpoint Strike", "Runway Attack"],
    "CAS": ["CAS"],
    "INTERDICTION": ["Ground Attack", "CAS"],
    "ANTISHIP": ["Antiship Strike"],
    "RECON": ["Reconnaissance"],
    "TANKER": ["Refueling"],
    "AWACS": ["AWACS"],
    "TRANSPORT": ["Transport"],
    "SAR": ["Transport"],            # plane guard / rescue helicopters
}


@lru_cache(maxsize=1)
def _eras() -> Dict[str, Dict[str, int]]:
    with open(paths.PROJECT_ROOT / "data" / "unit_eras.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


@lru_cache(maxsize=1)
def sam_templates() -> Dict[str, Dict[str, Any]]:
    with open(paths.PROJECT_ROOT / "data" / "sam_templates.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def aircraft_type(type_id: str):
    return planes.plane_map.get(type_id) or helicopters.helicopter_map.get(type_id)


def vehicle_type(type_id: str):
    return vehicles.vehicle_map.get(type_id)


def ship_type(type_id: str):
    return ships.ship_map.get(type_id)


def exists(type_id: str) -> bool:
    return bool(aircraft_type(type_id) or vehicle_type(type_id) or ship_type(type_id))


def is_helicopter(type_id: str) -> bool:
    return type_id in helicopters.helicopter_map


def year_of(type_id: str) -> int:
    e = _eras()
    for cat in ("aircraft", "helicopters", "ships", "vehicles"):
        if type_id in e.get(cat, {}):
            return e[cat][type_id]
    for tpl in sam_templates().values():
        if type_id in tpl["units"]:
            return tpl["year"]
    return DEFAULT_YEAR


def in_era(type_id: str, year: int, era_kind: str = "modern") -> bool:
    """True if the type may appear in a template of this year/era kind."""
    y = year_of(type_id)
    if y > year:
        return False
    if era_kind == "ww2":
        return y <= 1945
    return y > 1945 or type_id == "C-47" or bool(ship_type(type_id))


def flyable_modules() -> List[str]:
    out = [k for k, v in planes.plane_map.items() if v.flyable]
    out += [k for k, v in helicopters.helicopter_map.items() if v.flyable]
    return sorted(out)


def flyable_in_era(year: int, era_kind: str) -> List[str]:
    return [t for t in flyable_modules() if in_era(t, year, era_kind)]


def pydcs_tasks(type_id: str) -> List[str]:
    t = aircraft_type(type_id)
    return [x.name for x in t.tasks] if t else []


def capable_missions(type_id: str) -> List[str]:
    """SORTIE mission types an airframe can fly according to pydcs task lists."""
    have = set(pydcs_tasks(type_id))
    return [m for m, names in TASK_MAP.items() if have.intersection(names)]


def role_class(type_id: str) -> str:
    """Coarse class used for fuel use and abstract combat."""
    t = aircraft_type(type_id)
    if t is None:
        return "fighter"
    if is_helicopter(type_id):
        return "helo"
    tasks = set(pydcs_tasks(type_id))
    if tasks & {"AWACS", "Refueling", "Transport"} and not tasks & {"CAP", "CAS", "Ground Attack"}:
        return "support"
    if year_of(type_id) <= 1945:
        return "bomber" if t.fuel_max > 2500 else "ww2"
    if t.fuel_max > 20000:
        return "bomber"
    return "fighter" if "CAP" in tasks else "attacker"


def fuel_kind(type_id: str) -> str:
    """Which airbase liquid the type burns."""
    return "avgas" if year_of(type_id) <= 1945 else "jet"


def air_rating(type_id: str) -> float:
    """Abstract air-to-air quality (~0.25..2.0) derived from era, speed and role."""
    t = aircraft_type(type_id)
    if t is None or "CAP" not in pydcs_tasks(type_id):
        return 0.25
    y = year_of(type_id)
    base = 0.6 + max(0, min(y, 2010) - 1940) / 70.0          # 0.6 (1940) .. 1.6 (2010)
    speed = min(1.25, max(0.8, (t.max_speed or 800) / 2000.0 + 0.3)) if y > 1945 else 1.0
    return round(base * speed, 3)


def strike_rating(type_id: str) -> float:
    t = aircraft_type(type_id)
    if t is None:
        return 0.3
    tasks = set(pydcs_tasks(type_id))
    if not tasks & {"Ground Attack", "CAS", "Pinpoint Strike", "SEAD", "Antiship Strike", "Runway Attack"}:
        return 0.1
    y = year_of(type_id)
    r = 0.6 + max(0, min(y, 2010) - 1940) / 100.0
    if "Pinpoint Strike" in tasks:
        r += 0.2
    if role_class(type_id) == "bomber":
        r += 0.4
    return round(r, 3)


def combat_radius_km(type_id: str) -> float:
    """Rough combat radius used by the planner (not a performance model)."""
    return {"ww2": 450.0, "helo": 150.0, "bomber": 1500.0, "support": 1500.0,
            "attacker": 550.0, "fighter": 650.0}[role_class(type_id)]


def sam_template(name: str) -> Optional[Dict[str, Any]]:
    return sam_templates().get(name)
