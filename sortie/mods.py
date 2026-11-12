"""Community aircraft mods (A-4E-C, AH-6J/MH-6J, CJS Super Hornets, UH-60L).

pydcs knows only Eagle Dynamics' own aircraft, so each mod type is registered with pydcs here
when the mod is installed in <Saved Games>/Mods/aircraft AND switched on in Settings. The
types copy the numbers from the installed mod's own Lua (fuel, speed, tasks); the CJS Super
Hornets derive from pydcs's F/A-18C so they keep its radios, datalink and properties.

Loadouts. The mods' payload files are read with a real Lua interpreter (lupa), because they
are not in the plain table format pydcs parses: the CJS Super Hornet files use `local`
station constants (`[WTL] = {...}`) and name the unit with ["name"] instead of ["unitType"].
The Super Hornet is the odd one: it does not carry base-game Hornet store ids. Every store
is a per-station wrapper id that exists only in the mod (e.g.
"{SUPERHORNET_PYLON_02_OB_MK_1X_GBU-12}" is "a GBU-12 on station 2 on an SUU-80/BRU-32"),
and a base-game id such as "{GBU-12}" on a Super Hornet station is simply not valid there.
So SORTIE never builds Super Hornet loadouts itself: it only uses whole payloads from the
mod's UnitPayloads file (or ones you save in the Mission Editor as "SORTIE <TASK>"), and a
weather swap may only pick a store the mod's own payloads already hang on that same station.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dcs import helicopters, planes, task as dcstask

log = logging.getLogger("sortie.mods")


@dataclass
class TypeSpec:
    id: str
    helicopter: bool
    year: int
    fuel_max: float
    max_speed: float                      # km/h
    tasks: List[type]
    fallback: str                         # base-game type flown instead when the mod is off
    base: Any = None                      # pydcs class to inherit (radios, properties)
    category: str = "Air"
    radio_frequency: float = 251
    livery_name: Optional[str] = None


@dataclass
class ModSpec:
    key: str
    name: str
    folder_hint: str                      # case-insensitive substring of the mod's folder name
    types: List[TypeSpec]
    note: str = ""
    # SORTIE task -> {base type: mod type}: flights of that task in the base type fly the mod type
    replaces: Dict[str, Dict[str, str]] = field(default_factory=dict)
    livery: Dict[str, str] = field(default_factory=dict)   # task -> livery folder for replaced flights


T = dcstask
MODS: Dict[str, ModSpec] = {m.key: m for m in [
    ModSpec("a4ec", "A-4E-C Skyhawk", "a-4e-c", [
        TypeSpec("A-4E-C", False, 1962, 2467, 1083,
                 [T.CAS, T.GroundAttack, T.CAP, T.Escort, T.AntishipStrike, T.SEAD], "F-5E-3",
                 category="Attack", radio_frequency=251, livery_name="A-4E-C")],
             note="Community A-4E-C. Gets VA/VMA squadrons in the Cold War theater."),
    ModSpec("ah6j", "AH-6J / MH-6J Little Bird", "ah-6j", [
        TypeSpec("AH-6J", True, 1983, 181, 280, [T.CAS, T.Reconnaissance, T.Transport], "OH58D",
                 livery_name="AH-6J"),
        TypeSpec("MH-6J", True, 1983, 181, 280, [T.Transport], "UH-1H", livery_name="MH-6J")],
             note="Little Birds of the 160th SOAR for CAS in the Gulf theater."),
    ModSpec("superhornet", "CJS Super Hornets (F/A-18E/F, EA-18G)", "super hornet", [
        TypeSpec("FA-18E", False, 1999, 4900, 2120,
                 [T.CAP, T.Escort, T.Intercept, T.FighterSweep, T.CAS, T.GroundAttack, T.PinpointStrike,
                  T.SEAD, T.AntishipStrike, T.Reconnaissance], "FA-18C_hornet", base=planes.FA_18C_hornet),
        TypeSpec("FA-18F", False, 1999, 4482, 2120,
                 [T.CAP, T.Escort, T.Intercept, T.FighterSweep, T.CAS, T.GroundAttack, T.PinpointStrike,
                  T.SEAD, T.AntishipStrike, T.Reconnaissance], "FA-18C_hornet", base=planes.FA_18C_hornet),
        TypeSpec("EA-18G", False, 2009, 4900, 2120, [T.SEAD, T.Escort, T.CAP], "FA-18C_hornet",
                 base=planes.FA_18C_hornet)],
             note="Needs the F/A-18C module. Loadouts come only from the mod's own payloads."),
    ModSpec("uh60l", "UH-60L Black Hawk", "uh60l", [
        TypeSpec("UH-60L", True, 1989, 1362, 296, [T.Transport, T.Reconnaissance], "UH-60A",
                 radio_frequency=116, livery_name="UH-60L")],
             note="Flies plane guard off every carrier instead of the SH-60B, in US Navy grey.",
             replaces={"SAR": {"SH-60B": "UH-60L"}}, livery={"SAR": "US Navy Grey"}),
]}
MOD_OF_TYPE: Dict[str, str] = {t.id: m.key for m in MODS.values() for t in m.types}
SPEC_OF_TYPE: Dict[str, TypeSpec] = {t.id: t for m in MODS.values() for t in m.types}
_registered: Dict[str, Any] = {}           # type id -> pydcs class currently in the maps
_folders: Dict[str, Path] = {}            # mod key -> installed folder


# -- detection ------------------------------------------------------------------------------
def mods_dir(saved_games: Optional[Path]) -> Optional[Path]:
    if not saved_games:
        return None
    d = saved_games / "Mods" / "aircraft"
    return d if d.is_dir() else None


def find_installed(saved_games: Optional[Path]) -> Dict[str, Path]:
    """{mod key: folder} for the supported mods found in Saved Games."""
    out: Dict[str, Path] = {}
    d = mods_dir(saved_games)
    if d is None:
        return out
    folders = [p for p in d.iterdir() if p.is_dir()]
    for m in MODS.values():
        first = m.types[0].id
        hit = next((p for p in folders if (p / "UnitPayloads" / f"{first}.lua").is_file()), None) or \
            next((p for p in folders if m.folder_hint in p.name.lower()), None)
        if hit is not None:
            out[m.key] = hit
    return out


def status(settings) -> List[Dict[str, Any]]:
    """For the Settings page: every supported mod, whether it is installed and switched on."""
    from . import config
    found = find_installed(config.resolved_saved_games(settings))
    on = settings.mods or {}
    return [{"key": m.key, "name": m.name, "installed": m.key in found,
             "folder": str(found[m.key]) if m.key in found else None, "enabled": bool(on.get(m.key)),
             "active": m.key in found and bool(on.get(m.key)), "note": m.note,
             "types": [t.id for t in m.types]} for m in MODS.values()]


def enabled(settings) -> Dict[str, Path]:
    """Mods that are installed and switched on."""
    from . import config
    found = find_installed(config.resolved_saved_games(settings))
    on = (settings.mods or {}) if settings else {}
    return {k: p for k, p in found.items() if on.get(k)}


def is_active(type_id: str) -> bool:
    return type_id in _registered


# -- registration -----------------------------------------------------------------------------
def _make_class(spec: TypeSpec, folder: Path):
    base = spec.base or (helicopters.HelicopterType if spec.helicopter else planes.PlaneType)
    attrs = {
        "id": spec.id, "flyable": True, "fuel_max": spec.fuel_max, "max_speed": spec.max_speed,
        "tasks": list(spec.tasks), "task_default": spec.tasks[0], "category": spec.category,
        "radio_frequency": spec.radio_frequency, "livery_name": spec.livery_name or spec.id,
        "payloads": None, "pylons": set(range(1, 21)), "sortie_mod_folder": str(folder),
        "sortie_station_clsids": None,
    }
    # The Super Hornets inherit pydcs's F/A-18C for its radios and properties, but NOT its
    # Pylon1..PylonN store lists: base-game Hornet store ids are not valid on Super Hornet
    # stations, and anything that looks a store up by station must see that there is none.
    for n in range(1, 21):
        attrs[f"Pylon{n}"] = None
    cls = type("Mod_" + re.sub(r"\W", "_", spec.id), (base,), attrs)

    @classmethod
    def load_payloads(c):
        if c.payloads is None:
            c.payloads = read_payloads(c.id, Path(c.sortie_mod_folder))
            st: Dict[int, List[str]] = {}
            for p in c.payloads.values():
                for pyl in p["pylons"].values():
                    lst = st.setdefault(int(pyl["num"]), [])
                    if pyl["CLSID"] not in lst:
                        lst.append(pyl["CLSID"])
            c.sortie_station_clsids = st
        return c.payloads

    cls.load_payloads = load_payloads
    return cls


def register(settings) -> List[str]:
    """Make pydcs know exactly the mods that are installed and switched on. Idempotent: mods
    switched off since the last call are removed again. Returns the registered type ids."""
    want = enabled(settings) if settings is not None else {}
    keep = {t.id for k in want for t in MODS[k].types}
    for tid in list(_registered):
        if tid not in keep:
            planes.plane_map.pop(tid, None)
            helicopters.helicopter_map.pop(tid, None)
            del _registered[tid]
    for key, folder in want.items():
        _folders[key] = folder
        for spec in MODS[key].types:
            if spec.id in _registered:
                continue
            cls = _make_class(spec, folder)
            (helicopters.helicopter_map if spec.helicopter else planes.plane_map)[spec.id] = cls
            _registered[spec.id] = cls
    return sorted(_registered)


# -- payloads -----------------------------------------------------------------------------------
def _lua_to_py(v):
    """lupa table -> dict (keys kept as they come: numbers stay numbers)."""
    if hasattr(v, "items"):
        return {k: _lua_to_py(x) for k, x in v.items()}
    return v


def _read_lua_payload_file(path: Path) -> Optional[Dict[str, Any]]:
    try:
        from lupa import lua51
    except ImportError:                    # pragma: no cover - lupa is a requirement
        log.warning("lupa missing: cannot read mod payloads %s", path)
        return None
    lua = lua51.LuaRuntime(unpack_returned_tuples=True)
    g = lua.globals()
    for k, v in dcstask.MainTask.map.items():   # some files tag payloads with task names
        g[v.internal_name] = v.id
    lua.execute("_ = function(s) return s end")
    try:
        res = lua.execute(path.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:
        log.warning("mod payload file %s could not be read: %s", path, exc)
        return None
    if res is None:
        res = g.unitPayloads
    return _lua_to_py(res) if res is not None else None


def read_payloads(type_id: str, folder: Path) -> Dict[str, Dict[str, Any]]:
    """{payload name: {'name','pylons': {i: {'CLSID','num'}}, 'tasks': {...}}} from the mod's
    UnitPayloads file, then the user's Mission Editor payloads for the type (those win)."""
    out: Dict[str, Dict[str, Any]] = {}
    files = [folder / "UnitPayloads" / f"{type_id}.lua"]
    from dcs.payloads import PayloadDirectories
    user = getattr(PayloadDirectories, "_user", None)
    if user is not None:
        files.append(Path(user) / f"{type_id}.lua")
    for f in files:
        if not f.is_file():
            continue
        data = _read_lua_payload_file(f)
        if not data:
            continue
        if (data.get("unitType") or data.get("name")) != type_id:
            continue
        for p in (data.get("payloads") or {}).values():
            if not isinstance(p, dict) or not p.get("name"):
                continue
            pylons = {}
            for key, pyl in (p.get("pylons") or {}).items():
                if isinstance(pyl, dict) and pyl.get("CLSID"):
                    num = int(pyl.get("num") or key)
                    pylons[num] = {"CLSID": pyl["CLSID"], "num": num,
                                   **({"settings": pyl["settings"]} if pyl.get("settings") else {})}
            out[p["name"]] = {"name": p["name"], "pylons": pylons, "tasks": p.get("tasks") or {}}
    return out


def station_clsids(actype, pylon: int) -> List[str]:
    """Store ids the mod's own payloads put on this station (weather swaps pick only from these)."""
    if getattr(actype, "sortie_mod_folder", None) is None:
        return []
    actype.load_payloads()
    return list((actype.sortie_station_clsids or {}).get(int(pylon), []))


# -- campaign / mission integration ----------------------------------------------------------------
def fallback(type_id: str) -> Optional[str]:
    s = SPEC_OF_TYPE.get(type_id)
    return s.fallback if s else None


def flown_type(type_id: str, task: str, settings=None) -> Tuple[str, Optional[str], Optional[str]]:
    """(type to put in the mission, livery or None, note or None) for a campaign aircraft.

    A mod type whose mod is off flies its base-game fallback; a base type that an active mod
    replaces for this task (UH-60L for SH-60B plane guard) flies the mod type."""
    if type_id in SPEC_OF_TYPE and not is_active(type_id):
        fb = fallback(type_id)
        return fb, None, f"{type_id} mod is off or not installed: flown as {fb}"
    for key in list(_folders):
        m = MODS[key]
        rep = m.replaces.get(task, {}).get(type_id)
        if rep and is_active(rep):
            return rep, m.livery.get(task), None
    return type_id, None, None


# Squadrons added to the theater templates while a mod is on (so they can be picked at career
# start and appear in new campaigns). Same fields as a theater squadron, plus the mod key.
MOD_SQUADRONS: Dict[str, List[Dict[str, Any]]] = {
    "gulf_crisis": [
        {"id": "vfa143", "name": "VFA-143", "coalition": "blue", "country": "USA", "airbase": "cvn73",
         "aircraft": "FA-18E", "mod": "superhornet", "tasks": ["CAP", "STRIKE", "SEAD", "ESCORT", "CAS", "ANTISHIP"],
         "airframes": 12, "callsign": "Dog"},
        {"id": "vfa102", "name": "VFA-102", "coalition": "blue", "country": "USA", "airbase": "cvn73",
         "aircraft": "FA-18F", "mod": "superhornet", "tasks": ["STRIKE", "CAS", "ESCORT", "CAP", "INTERDICTION"],
         "airframes": 10, "callsign": "Diamondback"},
        {"id": "vaq141", "name": "VAQ-141", "coalition": "blue", "country": "USA", "airbase": "cvn73",
         "aircraft": "EA-18G", "mod": "superhornet", "tasks": ["SEAD", "ESCORT"], "airframes": 5,
         "callsign": "Shadow"},
        {"id": "160soar", "name": "1-160th SOAR", "coalition": "blue", "country": "USA", "airbase": "rak",
         "aircraft": "AH-6J", "mod": "ah6j", "tasks": ["CAS"], "airframes": 6, "callsign": "Star"},
    ],
    "coldwar_1985": [
        {"id": "vma131", "name": "VMA-131", "coalition": "blue", "country": "USA", "airbase": "nordholz",
         "aircraft": "A-4E-C", "mod": "a4ec", "tasks": ["CAS", "INTERDICTION", "STRIKE"], "airframes": 12,
         "callsign": "Diamond"},
    ],
}


def extend_theater(theater) -> None:
    """Add the template's mod squadrons for every mod pydcs currently knows (installed + on)."""
    from .theater import SquadronT
    have = {s.id for s in theater.squadrons}
    for row in MOD_SQUADRONS.get(theater.id, []):
        if row["id"] in have or not is_active(row["aircraft"]):
            continue
        theater.squadrons.append(SquadronT(**{k: v for k, v in row.items() if k != "mod"}))


def era_years() -> Dict[str, int]:
    return {t.id: t.year for m in MODS.values() for t in m.types}
