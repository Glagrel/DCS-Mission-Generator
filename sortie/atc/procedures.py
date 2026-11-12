"""Radio procedure sets and message generation for the ATC/GCI layer.

The same phrase templates are shipped to Lua (in the mission config) and used here for
tests/fixtures, so what is tested in Python is what the mission says.
Placeholders use {name} and are filled by `render` (Python) / SORTIE.atc.render (Lua).
"""
from __future__ import annotations

import math
from typing import Any, Dict, List

PROCEDURES = ("nato", "soviet", "ww2")
THREAT_RANGE_M = {"nato": 46300, "soviet": 40000, "ww2": 30000}   # 25 nm / 40 km / 30 km

PHRASES: Dict[str, Dict[str, str]] = {
    "nato": {
        "checkin": "{callsign}, {controller}, radar contact. Bullseye is set. Picture to follow.",
        "picture_clean": "{callsign}, {controller}, picture clean.",
        "picture": "{callsign}, {controller}, picture: {n} group{s}. {groups}",
        "group": "Group bullseye {bearing}/{range}, {altitude}, {aspect}, {declare}",
        "bogey_dope": "{callsign}, {controller}, group BRAA {bearing}/{range}, {altitude}, {aspect}, {declare}.",
        "declare_hostile": "{callsign}, {controller}, group bullseye {bearing}/{range} hostile.",
        "declare_friendly": "{callsign}, {controller}, group bullseye {bearing}/{range} friendly.",
        "threat": "{callsign}, {controller}, threat BRAA {bearing}/{range}, {altitude}, {aspect}!",
        "merged": "{callsign}, {controller}, merged.",
        "vector_home": "{callsign}, {controller}, vector home base {bearing} for {range}.",
        "vector_tanker": "{callsign}, {controller}, {tanker} bears {bearing} for {range}, {altitude}, button {freq}, TACAN {tacan}.",
        "startup": "{callsign}, {tower} Ground, start-up approved. Wind {wind_dir} at {wind_speed}, altimeter {qnh}.",
        "taxi": "{callsign}, {tower} Ground, taxi to runway {runway}, hold short.",
        "takeoff": "{callsign}, {tower} Tower, wind {wind_dir} at {wind_speed}, runway {runway}, cleared for take-off.",
        "departure": "{callsign}, {tower} Departure, radar contact, climb on course. Contact {controller} on {freq}.",
        "inbound": "{callsign}, {tower} Approach, radar contact {range} out. Expect runway {runway}, altimeter {qnh}.",
        "landing": "{callsign}, {tower} Tower, wind {wind_dir} at {wind_speed}, runway {runway}, cleared to land.",
        "landed": "{callsign}, {tower} Tower, welcome home. Taxi to parking.",
        "csar": "{callsign}, {controller}, copy ejection. Rescue forces are being scrambled to bullseye {bearing}/{range}.",
        "splash": "{controller} copies splash one.",
        "radio_check": "{callsign}, {controller}, radio check, loud and clear on {freq}.",
    },
    "soviet": {
        "checkin": "{callsign}, I am {controller}. I see you. Stand by for target information.",
        "picture_clean": "{callsign}, {controller}. Airspace is clear.",
        "picture": "{callsign}, {controller}. {n} target{s}. {groups}",
        "group": "Target azimuth {bearing}, range {range}, height {altitude}, {aspect}",
        "bogey_dope": "{callsign}, {controller}. Target: course {bearing}, range {range}, height {altitude}, {aspect}.",
        "declare_hostile": "{callsign}, {controller}. Target azimuth {bearing}, range {range} is hostile. Attack.",
        "declare_friendly": "{callsign}, {controller}. Azimuth {bearing}, range {range} is ours. Do not attack.",
        "threat": "{callsign}, {controller}. Attention! Enemy azimuth {bearing}, range {range}, height {altitude}!",
        "merged": "{callsign}, {controller}. Targets merged with you.",
        "vector_home": "{callsign}, {controller}. Course to base {bearing}, distance {range}.",
        "vector_tanker": "{callsign}, {controller}. Tanker {tanker} course {bearing}, distance {range}, height {altitude}.",
        "startup": "{callsign}, {tower}. Start-up permitted. Wind {wind_dir} degrees, {wind_speed}. Pressure {qnh}.",
        "taxi": "{callsign}, {tower}. Taxi to the holding point, runway {runway}.",
        "takeoff": "{callsign}, {tower}. Runway {runway}, take-off permitted.",
        "departure": "{callsign}, {tower}. Climb on course. Go to channel {freq}, {controller}.",
        "inbound": "{callsign}, {tower}. I see you, distance {range}. Landing course {runway}, pressure {qnh}.",
        "landing": "{callsign}, {tower}. Runway {runway}, landing permitted.",
        "landed": "{callsign}, {tower}. Landing recorded. Taxi to the stand.",
        "csar": "{callsign}, {controller}. Ejection observed. Search and rescue is tasked, azimuth {bearing}, range {range}.",
        "splash": "{controller}. Target destroyed, confirmed.",
        "radio_check": "{callsign}, {controller}. I hear you well on {freq}.",
    },
    "ww2": {
        "checkin": "{callsign}, this is {controller}. Receiving you. Stand by for vectors.",
        "picture_clean": "{callsign}, {controller}. No bogeys on the board.",
        "picture": "{callsign}, {controller}. {n} plot{s}. {groups}",
        "group": "Bogeys bearing {bearing}, {range}, angels {altitude}",
        "bogey_dope": "{callsign}, {controller}. Vector {bearing}, bogeys {range}, angels {altitude}. Buster.",
        "declare_hostile": "{callsign}, {controller}. Plot bearing {bearing}, {range} is a bandit.",
        "declare_friendly": "{callsign}, {controller}. Plot bearing {bearing}, {range} is friendly.",
        "threat": "{callsign}, {controller}. Bandits close! Bearing {bearing}, {range}, angels {altitude}.",
        "merged": "{callsign}, {controller}. Plots have merged. Good hunting.",
        "vector_home": "{callsign}, {controller}. Steer {bearing} for base, {range}.",
        "startup": "{callsign}, {tower}. Clear to start engines.",
        "taxi": "{callsign}, {tower}. Clear to taxi.",
        "takeoff": "{callsign}, {tower}. Wind {wind_dir} degrees {wind_speed}. Clear for take-off.",
        "inbound": "{callsign}, {tower}. Field is clear, join the circuit.",
        "landing": "{callsign}, {tower}. Clear to land.",
        "landed": "{callsign}, {tower}. Pancake logged.",
        "splash": "{controller}. Splash confirmed.",
        "radio_check": "{callsign}, {controller}. Receiving you strength five on {freq}.",
    },
}
GCI_CALLSIGNS = {"nato": "Overlord", "soviet": "Kupol", "ww2": "Base"}


def procedure_set(doctrine: str, era_kind: str) -> str:
    if era_kind == "ww2" or doctrine == "ww2":
        return "ww2"
    return "soviet" if doctrine == "soviet" else "nato"


def gci_callsign(proc: str) -> str:
    return GCI_CALLSIGNS[proc]


def features(proc: str, capabilities: List[str]) -> Dict[str, bool]:
    """Which services exist. WW2 gets only simple GCI vectors and basic tower calls."""
    modern = proc != "ww2"
    return {
        "tower": True, "ground": True, "approach": modern, "departure": modern,
        "gci": "GCI" in capabilities or "AWACS" in capabilities,
        "awacs": modern and "AWACS" in capabilities,
        "picture": True, "declare": modern, "threat": True, "bullseye": modern,
        "tanker": modern and "TANKER" in capabilities, "csar": modern,
        "airboss": modern and "CARRIER" in capabilities,
    }


def aspect(target_heading: float, bearing_to_target: float) -> str:
    """hot / flank / beam / drag from the angle between the target's heading and the line to us."""
    diff = abs((target_heading - (bearing_to_target + 180.0) + 180.0) % 360.0 - 180.0)
    if diff <= 30:
        return "hot"
    if diff <= 60:
        return "flanking"
    return "beaming" if diff <= 120 else "cold"


def fmt_range(metres: float, proc: str) -> str:
    return f"{metres / 1000.0:.0f} kilometres" if proc == "soviet" else f"{metres / 1852.0:.0f} miles"


def fmt_altitude(metres: float, proc: str) -> str:
    if proc == "soviet":
        return f"{max(100, int(round(metres / 100.0)) * 100)} metres"
    thousands = int(round(metres * 3.28084 / 1000.0))
    return f"{thousands}" if proc == "ww2" else f"{max(1, thousands)} thousand"


def fmt_bearing(deg: float) -> str:
    return f"{int(round(deg)) % 360:03d}"


def render(proc: str, key: str, **kw: Any) -> str:
    """Fill a phrase. Unknown keys for a procedure set return '' (e.g. tanker calls in WW2)."""
    tpl = PHRASES[proc].get(key)
    if tpl is None:
        return ""

    class _Safe(dict):
        def __missing__(self, k):
            return "{" + k + "}"

    return tpl.format_map(_Safe(kw))


def contact_call(proc: str, key: str, callsign: str, controller: str, bearing: float, range_m: float,
                 alt_m: float, target_heading: float = 0.0, hostile: bool = True) -> str:
    return render(proc, key, callsign=callsign, controller=controller, bearing=fmt_bearing(bearing),
                  range=fmt_range(range_m, proc), altitude=fmt_altitude(alt_m, proc),
                  aspect=aspect(target_heading, bearing), declare="hostile" if hostile else "bogey")


def picture_call(proc: str, callsign: str, controller: str, groups: List[Dict[str, float]]) -> str:
    """groups: [{'bearing','range_m','alt_m','heading'}] relative to bullseye (or to the player in ww2)."""
    if not groups:
        return render(proc, "picture_clean", callsign=callsign, controller=controller)
    parts = [render(proc, "group", bearing=fmt_bearing(g["bearing"]), range=fmt_range(g["range_m"], proc),
                    altitude=fmt_altitude(g["alt_m"], proc), aspect=aspect(g.get("heading", 0.0), g["bearing"]),
                    declare="hostile") for g in groups[:3]]
    return render(proc, "picture", callsign=callsign, controller=controller, n=len(groups),
                  s="" if len(groups) == 1 else "s", groups=". ".join(parts) + ".")


def bearing_range(lat1: float, lon1: float, lat2: float, lon2: float):
    from .. import geo
    return geo.bearing((lat1, lon1), (lat2, lon2)), geo.dist_km((lat1, lon1), (lat2, lon2)) * 1000.0
