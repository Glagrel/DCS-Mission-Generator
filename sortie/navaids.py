"""Navigation aids: airfield TACAN/VOR/ILS read from the DCS install's terrain beacon files,
and the TACAN / ICLS / Link 4 plan for carriers and tankers.

Airfield beacons are part of the map and are always transmitting; carriers and tankers only
transmit when the mission tells them to, which the mission builder does from this plan.
"""
from __future__ import annotations

import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("sortie.navaids")
# template terrain key -> folder under <DCS>\Mods\terrains
TERRAIN_DIRS = {"GermanyCW": "GermanyColdWar", "PersianGulf": "PersianGulf", "MarianaIslands": "MarianaIslands",
                "MarianaIslandsWWII": "MarianaIslandsWWII", "Caucasus": "Caucasus", "Syria": "Syria",
                "Nevada": "Nevada", "Normandy": "Normandy", "TheChannel": "TheChannel", "Sinai": "Sinai",
                "Kola": "Kola", "Afghanistan": "Afghanistan", "Falklands": "Falklands"}
FALLBACK_DIRS = {"MarianaIslandsWWII": "MarianaIslands"}
CARRIER_TACAN_FIRST, CARRIER_ICLS_FIRST, CARRIER_LINK4_FIRST = 71, 1, 336
_BLOCK = re.compile(r"\{[^{}]*?beaconId\s*=\s*'([^']+)'(.*?)\n\t\};", re.S)


def _field(body: str, name: str) -> Optional[str]:
    m = re.search(rf"\b{name}\s*=\s*([^;\n]+);", body)
    return m.group(1).strip().strip("'\"") if m else None


def parse_beacons(text: str) -> Dict[str, Dict[str, Any]]:
    """beaconId -> {type, callsign, frequency_hz, channel, name} from a terrain beacons.lua."""
    out: Dict[str, Dict[str, Any]] = {}
    for m in _BLOCK.finditer(text):
        body = m.group(2)
        try:
            freq = float(_field(body, "frequency") or 0)
        except ValueError:
            freq = 0.0
        chan = _field(body, "channel")
        name = re.search(r"display_name\s*=\s*_\('([^']*)'\)", m.group(0))
        out[m.group(1)] = {"type": (_field(body, "type") or "").replace("BEACON_TYPE_", ""),
                           "callsign": _field(body, "callsign") or "", "frequency_hz": freq,
                           "channel": int(chan) if chan and chan.lstrip("-").isdigit() else None,
                           "name": name.group(1) if name else ""}
    return out


@lru_cache(maxsize=16)
def terrain_beacons(install: Optional[str], terrain_key: str) -> Dict[str, Dict[str, Any]]:
    if not install:
        return {}
    for folder in (TERRAIN_DIRS.get(terrain_key), FALLBACK_DIRS.get(terrain_key)):
        if not folder:
            continue
        f = Path(install) / "Mods" / "terrains" / folder / "beacons.lua"
        if f.is_file():
            try:
                return parse_beacons(f.read_text(encoding="utf-8", errors="replace"))
            except OSError as exc:
                log.warning("cannot read %s: %s", f, exc)
    return {}


def airfield_nav(install: Optional[Path], terrain_key: str, airport) -> Dict[str, Any]:
    """TACAN/VOR/ILS and tower frequencies for a pydcs Airport (empty parts when unknown)."""
    beacons = terrain_beacons(str(install) if install else None, terrain_key)
    nav: Dict[str, Any] = {"name": airport.name, "tacan": None, "vor": None, "ils": [], "atc": {}}
    radio = getattr(airport, "atc_radio", None)
    if radio is not None:
        nav["atc"] = {"uhf": round(radio.uhf_hz / 1e6, 3), "vhf": round(radio.vhf_high_hz / 1e6, 3)}
    for b in getattr(airport, "beacons", []) or []:
        info = beacons.get(getattr(b, "id", ""))
        if not info:
            continue
        if info["type"] in ("TACAN", "VORTAC") and info["channel"]:
            nav["tacan"] = f"{info['channel']}X {info['callsign']}"
        if info["type"] in ("VOR", "VOR_DME", "VORTAC") and info["frequency_hz"]:
            nav["vor"] = f"{info['frequency_hz'] / 1e6:.2f} {info['callsign']}"
    for rw in getattr(airport, "runways", []) or []:
        for end in (rw.main, rw.opposite):
            for b in end.beacons:
                info = beacons.get(b.id)
                if info and info["type"] == "ILS_LOCALIZER" and info["frequency_hz"]:
                    nav["ils"].append({"runway": end.name, "freq": round(info["frequency_hz"] / 1e6, 2),
                                       "ident": info["callsign"]})
    nav["ils"].sort(key=lambda x: x["runway"])
    return nav


def _ident(name: str, fallback: str) -> str:
    letters = re.sub(r"[^A-Z]", "", name.upper().replace("USS", ""))
    return (letters[:3] or fallback).ljust(3, "X")


def carrier_plan(st) -> Dict[str, Dict[str, Any]]:
    """naval group id -> {tacan channel/band/ident, icls channel, link4 MHz} for every carrier.
    Deterministic (sorted by id) so the briefing and the mission always agree."""
    out: Dict[str, Dict[str, Any]] = {}
    modern = st.meta.era_kind != "ww2"
    carriers = sorted((n for n in st.naval_groups.values() if n.role == "carrier"), key=lambda n: n.id)
    for i, n in enumerate(carriers):
        if not modern:
            continue                                    # no TACAN/ICLS in 1944
        chan = CARRIER_TACAN_FIRST + i
        out[n.id] = {"name": n.name, "airbase_id": n.airbase_id, "tacan_channel": chan, "tacan_band": "X",
                     "tacan": f"{chan}X", "ident": _ident(n.name, f"CV{i + 1}"),
                     "icls": CARRIER_ICLS_FIRST + i, "link4": CARRIER_LINK4_FIRST + i}
    return out


def tanker_channel(tacan: Optional[str]):
    """'31Y' -> (31, 'Y')."""
    m = re.match(r"^(\d+)([XY])$", tacan or "")
    return (int(m.group(1)), m.group(2)) if m else (None, None)


def home_nav(st, base, install: Optional[Path], terrain_obj=None) -> Dict[str, Any]:
    """Navigation data for the briefing/kneeboard of a flight based at `base`."""
    if base.kind == "carrier":
        plan = carrier_plan(st).get(base.naval_group or "")
        if not plan:
            return {"name": base.name, "kind": "carrier"}
        return {"name": base.name, "kind": "carrier", "tacan": f"{plan['tacan']} {plan['ident']}",
                "icls": plan["icls"], "link4": plan["link4"], "ils": [], "atc": {}}
    if terrain_obj is None or not base.dcs_name or base.dcs_name not in terrain_obj.airports:
        return {"name": base.name, "kind": "airfield", "ils": [], "atc": {}}
    nav = airfield_nav(install, st.meta.terrain, terrain_obj.airports[base.dcs_name])
    nav["kind"] = "airfield"
    return nav
