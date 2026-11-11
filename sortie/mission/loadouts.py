"""Loadout selection from the DCS payload files that pydcs can parse.

Payload Lua files live in the DCS install (read-only use). Without an install (tests, CI)
no payloads are known and flights are generated with empty pylons plus a warning.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional

from dcs import task as dcstask
from dcs.payloads import PayloadDirectories

from .. import units

log = logging.getLogger("sortie.loadouts")

# SORTIE task -> pydcs MainTask classes to look for in a payload's task list, in preference order
TASK_CLASSES: Dict[str, List[type]] = {
    "CAP": [dcstask.CAP, dcstask.Intercept, dcstask.FighterSweep],
    "INTERCEPT": [dcstask.Intercept, dcstask.CAP],
    "ESCORT": [dcstask.Escort, dcstask.CAP],
    "SWEEP": [dcstask.FighterSweep, dcstask.CAP],
    "SEAD": [dcstask.SEAD],
    "DEAD": [dcstask.SEAD, dcstask.PinpointStrike, dcstask.GroundAttack],
    "STRIKE": [dcstask.GroundAttack, dcstask.PinpointStrike, dcstask.RunwayAttack],
    "CAS": [dcstask.CAS, dcstask.GroundAttack],
    "INTERDICTION": [dcstask.GroundAttack, dcstask.CAS],
    "ANTISHIP": [dcstask.AntishipStrike],
    "RECON": [dcstask.Reconnaissance],
    "TANKER": [dcstask.Refueling],
    "AWACS": [dcstask.AWACS],
    "TRANSPORT": [dcstask.Transport],
}
_configured = False


def configure(install: Optional[Path], saved_games: Optional[Path] = None) -> None:
    """Point pydcs at the detected DCS folders (its own lookup can pick the wrong registry key)."""
    global _configured
    dirs: List[Path] = []
    if install and install.is_dir():
        main = install / "MissionEditor" / "data" / "scripts" / "UnitPayloads"
        if main.is_dir():
            dirs.append(main)
        core = install / "CoreMods" / "aircraft"
        if core.is_dir():
            dirs += [p / "UnitPayloads" for p in core.iterdir() if (p / "UnitPayloads").is_dir()]
    PayloadDirectories._dcs = dirs
    mods: List[Path] = []
    user = Path("__sortie_no_user_payloads__")
    if saved_games and saved_games.is_dir():
        user = saved_games / "MissionEditor" / "UnitPayloads"
        mod_dir = saved_games / "Mods" / "Aircraft"
        if mod_dir.is_dir():
            mods = [p / "UnitPayloads" for p in mod_dir.iterdir() if (p / "UnitPayloads").is_dir()]
    PayloadDirectories._mod = mods
    PayloadDirectories._user = user
    _configured = True


def _payloads(aircraft: str) -> Dict[str, dict]:
    if not _configured:
        configure(None)
    t = units.aircraft_type(aircraft)
    if t is None:
        return {}
    try:
        return t.load_payloads() or {}
    except Exception as exc:              # a broken payload file must not stop mission generation
        log.warning("payloads for %s could not be read: %s", aircraft, exc)
        return {}


def pick(aircraft: str, task: str) -> str:
    """Name of the first payload tagged for the task ('' when none is known)."""
    payloads = _payloads(aircraft)
    for cls in TASK_CLASSES.get(task, []):
        for name in sorted(payloads):
            tasks = payloads[name].get("tasks", {})
            if cls.id in (tasks.values() if isinstance(tasks, dict) else tasks):
                return name
    return ""


def pylons(aircraft: str, name: str):
    """[(pylon number, {'clsid':..., 'settings'?})] for a payload name, or None."""
    t = units.aircraft_type(aircraft)
    if t is None or not name or not _payloads(aircraft):
        return None
    return t.loadout_by_name(name)


def describe(aircraft: str, name: str) -> List[str]:
    """Human-readable store list for the briefing (CLSIDs resolved through pydcs weapon data)."""
    from dcs import weapons_data
    out: Dict[str, int] = {}
    for _, data in pylons(aircraft, name) or []:
        w = weapons_data.weapon_ids.get(data["clsid"])
        label = w["name"] if w else data["clsid"]
        out[label] = out.get(label, 0) + 1
    return [f"{n} x {label}" for label, n in out.items()]
