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
    _reset_cache()
    _configured = True


def _reset_cache() -> None:
    """Forget payloads parsed with a previous directory configuration."""
    from dcs import helicopters, planes
    from dcs.unittype import FlyingType
    FlyingType._payload_cache = None
    for t in list(planes.plane_map.values()) + list(helicopters.helicopter_map.values()):
        t.payloads = None


def configure_from_settings(settings) -> None:
    from .. import config, mods
    mods.register(settings)                # mod aircraft switched on in Settings become pydcs types
    configure(config.resolved_install(settings), config.resolved_saved_games(settings))


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


# What a good loadout for each task carries (matched against weapon display names, lower case).
PRIMARY: Dict[str, List[str]] = {
    "SEAD": ["agm-88", "harm", "kh-58", "kh-25mp", "kh-31p", "ld-10", "agm-45", "shrike", "alarm", "martel"],
    "DEAD": ["agm-88", "harm", "agm-65", "maverick", "gbu", "jdam", "agm-154", "jsow", "kh-58", "kh-25", "kh-29",
             "cbu", "kab", "ld-10"],
    "STRIKE": ["gbu", "jdam", "mk-84", "mk-83", "mk-82", "agm-154", "jsow", "agm-84e", "agm-84h", "slam", "kab",
               "fab", "betab", "bomb", "cbu", "blu", "kh-29", "kh-59", "storm", "apache", "durandal"],
    "CAS": ["agm-65", "maverick", "gbu-12", "gbu-38", "gbu", "cbu", "mk-20", "rockeye", "mk-82", "hydra", "rocket",
            "s-8", "s-13", "zuni", "kh-25", "kh-29", "vikhr", "ataka", "hellfire", "agm-114", "tow", "fab", "rbk"],
    "INTERDICTION": ["agm-65", "maverick", "cbu", "mk-20", "rockeye", "gbu", "mk-82", "mk-83", "rocket", "kh-25",
                     "kh-29", "fab", "rbk", "hydra"],
    "ANTISHIP": ["agm-84", "harpoon", "kh-35", "kh-31a", "kh-41", "c-802", "exocet", "rb-04", "rb 15", "rb-15",
                 "sea eagle", "kormoran", "penguin", "torpedo", "ah-1", "agm-119"],
    "RECON": ["recon", "camera", "tarps", "litening", "atflir", "targeting", "pod"],
}
IR_AAM = ["aim-9", "sidewinder", "r-73", "r-60", "magic", "python", "pl-5", "pl-8", "asraam", "iris", "r.550"]
RADAR_AAM = ["aim-120", "amraam", "aim-7", "sparrow", "aim-54", "phoenix", "r-27", "r-77", "sd-10", "super 530",
             "mica", "skyflash", "r-24", "r-33", "r-40"]
MODERN_AAM = ["aim-9x", "aim-120", "r-73", "r-77", "sd-10", "mica", "pl-8", "aim-54c"]
FUEL = ["fuel tank", "fuel", "drop tank", "ptb", "gal", "tank"]
POD = ["targeting", "litening", "atflir", "lantirn", "sniper", "tgp", "flir", "pave"]
HTS = ["hts", "harm targeting"]
ECM = ["ecm", "jammer", "alq", "sorbtsiya", "spj"]
A2A_TASKS = ("CAP", "INTERCEPT", "ESCORT", "SWEEP")
USER_PREFIX = "SORTIE "       # a payload named "SORTIE SEAD" etc. made in the Mission Editor always wins


def _stores(payload: dict) -> List[str]:
    pyl = payload.get("pylons", {})
    return [units.weapon_label(p.get("CLSID", "")).lower() for p in (pyl.values() if isinstance(pyl, dict) else pyl)]


def _has(store: str, words: List[str]) -> bool:
    return any(w in store for w in words)


def _mult(store: str) -> int:
    """'BRU-33 with 2 x Mk-82' carries two."""
    import re
    m = re.search(r"(\d+)\s*[x*]\s", store)
    return max(1, min(6, int(m.group(1)))) if m else 1


def score(payload: dict, task: str) -> float:
    """How well a payload suits a task. Rewards the right weapons, external fuel, self-defence
    missiles and the pods the weapons need; an empty payload scores nothing."""
    stores = _stores(payload)
    if not stores:
        return -100.0
    is_fuel = [(_has(s, FUEL) and not _has(s, IR_AAM + RADAR_AAM)) for s in stores]
    tanks = sum(is_fuel)
    ir = sum(_mult(s) for s in stores if _has(s, IR_AAM))
    radar = sum(_mult(s) for s in stores if _has(s, RADAR_AAM))
    modern = sum(1 for s in stores if _has(s, MODERN_AAM))
    pod = any(_has(s, POD) for s in stores)
    pts = 0.0
    if task in A2A_TASKS:
        pts += 2.0 * min(radar, 6) + 1.5 * min(ir, 4) + 0.5 * modern
        pts += 2.0 * min(tanks, 3 if task in ("CAP", "ESCORT") else 2)
        pts -= 4.0 * sum(1 for s in stores if _has(s, sum(PRIMARY.values(), [])) and not _has(s, IR_AAM + RADAR_AAM))
    elif task in PRIMARY:
        main = sum(_mult(s) for s, f in zip(stores, is_fuel) if not f and _has(s, PRIMARY[task]))
        if main == 0:
            return -50.0                         # tagged for the task but carries nothing for it
        pts += 3.0 * min(main, 6)
        pts += 4.0 if ir >= 1 else 0.0           # always bring self-defence heaters
        pts += 1.0 if ir >= 2 else 0.0
        pts += 1.5 * min(radar, 2)
        pts += 0.5 * min(modern, 2)
        pts += 3.0 if tanks >= 1 else 0.0        # and gas
        pts += 1.0 if tanks >= 2 else 0.0
        if task in ("STRIKE", "DEAD", "CAS", "INTERDICTION") and any(_has(s, ["gbu-1", "gbu-2", "paveway", "agm-65", "kab-500l", "kab-1500l"]) for s in stores):
            pts += 2.5 if pod else -1.0          # laser weapons want a targeting pod
        if task == "SEAD" and any(_has(s, HTS) for s in stores):
            pts += 2.0
        if any(_has(s, ECM) for s in stores):
            pts += 1.0
    else:
        pts += 2.0 * min(tanks, 3)               # tankers, AWACS, transports: just fuel
    return pts


def _tagged(payload: dict, cls) -> bool:
    tasks = payload.get("tasks", {})
    return cls.id in (tasks.values() if isinstance(tasks, dict) else tasks)


def pick(aircraft: str, task: str) -> str:
    """Best payload for the task ('' when none is known).

    1. A payload you saved in the Mission Editor named "SORTIE <TASK>" (e.g. "SORTIE SEAD").
    2. Otherwise the best-scoring payload DCS tags for the task (see `score`).
    3. Otherwise the best-scoring payload of any tag that carries weapons for the task."""
    payloads = _payloads(aircraft)
    if not payloads:
        return ""
    wanted = (USER_PREFIX + task).lower()
    for name in sorted(payloads):
        if name.lower() == wanted and _stores(payloads[name]):
            return name
    best_name, best = "", 0.0
    for rank, cls in enumerate(TASK_CLASSES.get(task, [])):
        for name in sorted(payloads):
            if _tagged(payloads[name], cls):
                s = score(payloads[name], task) - rank * 1.5      # prefer the task's own tag
                if s > best:
                    best_name, best = name, s
    if best_name:
        return best_name
    for name in sorted(payloads):                                  # nothing tagged: anything suitable
        s = score(payloads[name], task)
        if s > best:
            best_name, best = name, s
    return best_name


def pylons(aircraft: str, name: str):
    """[(pylon number, {'clsid':..., 'settings'?})] for a payload name, or None."""
    t = units.aircraft_type(aircraft)
    if t is None or not name or not _payloads(aircraft):
        return None
    return t.loadout_by_name(name)


def describe(aircraft: str, name: str) -> List[str]:
    """Human-readable store list for the briefing (CLSIDs resolved through pydcs weapon data)."""
    out: Dict[str, int] = {}
    for _, data in pylons(aircraft, name) or []:
        n, label = units.weapon_display(data["clsid"])
        if label.strip("<>").lower() == "clean":
            continue
        out[label] = out.get(label, 0) + n
    return [f"{n} x {label}" for label, n in out.items()]
