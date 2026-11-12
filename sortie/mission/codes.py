"""Per-flight codes and planning figures: IFF Mode 3, laser code, bingo/joker fuel, and the
Link 16 / SADL datalink set-up (team members, donors, track numbers).

Ideas adapted from SQE (github.com/MarkuzJuniuz/SQE, MIT). The datalink dict layout follows the
dcs-retribution pydcs fork (dcs/datalinks), which writes what the DCS Mission Editor writes.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from .. import geo, units
from ..models_ato import Ato, Flight

log = logging.getLogger("sortie.mission")
LASER_CODES = ["1688", "1687", "1686", "1685", "1684", "1683", "1682", "1681"]
KG_TO_LB = 2.20462


def _index(ato: Ato, flt: Flight) -> Tuple[int, int]:
    """(package number, flight number within the package), both 0-based."""
    for pi, p in enumerate(ato.packages):
        for fi, f in enumerate(p.flights):
            if f.id == flt.id:
                return pi, fi
    return 0, 0


def mode3(ato: Ato, flt: Flight) -> str:
    """Four octal digits, unique per flight within a package and different between packages."""
    pi, fi = _index(ato, flt)
    return f"{4 + (pi // 64) % 4}{(pi // 8) % 8}{pi % 8}{fi % 8}"


def laser(ato: Ato, flt: Flight) -> str:
    _, fi = _index(ato, flt)
    return LASER_CODES[fi % len(LASER_CODES)]


def set_laser(group, code: str) -> None:
    """Write the laser code into aircraft that take it as a unit property (e.g. AV-8B)."""
    for u in group.units:
        props = getattr(u.unit_type, "properties", {}) or {}
        if "LaserCode100" in props:
            try:
                u.set_property("LaserCode100", int(code[1]))
                u.set_property("LaserCode10", int(code[2]))
                u.set_property("LaserCode1", int(code[3]))
            except Exception as exc:
                log.debug("laser code not set on %s: %s", u.name, exc)


def fuel_plan(flt: Flight, home: Tuple[float, float]) -> Optional[Dict[str, float]]:
    """Planning bingo/joker in kg: a 12% landing reserve plus the fuel to fly home from the farthest point
    of the route (generic burn: a full internal load lasts about 1,600 km at cruise), joker 12% above."""
    t = units.aircraft_type(flt.aircraft)
    full = float(getattr(t, "fuel_max", 0) or 0)
    if full <= 0 or not flt.waypoints:
        return None
    far = max(geo.dist_km(home, (w.lat, w.lon)) for w in flt.waypoints)
    bingo = 0.12 * full + far * full / 1600.0
    bingo = min(max(bingo, 0.15 * full), 0.55 * full)
    return {"bingo_kg": round(bingo, -1), "joker_kg": round(bingo + 0.12 * full, -1), "internal_kg": full}


def fuel_text(kg: float, system: str) -> str:
    return f"{kg:,.0f} kg" if system == "metric" else f"{round(kg * KG_TO_LB, -2):,.0f} lb"


# -- datalinks -------------------------------------------------------------------------------------------
# aircraft id -> (link, max members, max donors, settings, members carry TDOA)
_LINKS = {
    "FA-18C_hornet": ("Link16", 4, 8, {"FF1_Channel": 2, "FF2_Channel": 3, "transmitPower": 0, "AIC_Channel": 1,
                                       "VOCA_Channel": 4, "VOCB_Channel": 5}, False),
    "F-16C_50": ("Link16", 8, 4, {"flightLead": False, "transmitPower": 3, "specialChannel": 1, "fighterChannel": 1,
                                  "missionChannel": 1}, True),
    "A-10C_2": ("SADL", 4, 12, {"flightLead": False, "AirKey": 10, "GatewayKey": 8}, False),
}


def link_of(aircraft: str) -> Optional[str]:
    spec = _LINKS.get(aircraft)
    return spec[0] if spec else None


def setup_datalinks(ato: Ato, groups: Dict[str, Any]) -> Dict[str, str]:
    """Wire the datalink of every capable flight: its own aircraft are team members, the leads of the
    other flights of the same package on the same link are donors. Returns flight id -> lead's track number."""
    counter: Dict[str, int] = {}
    stn: Dict[str, str] = {}
    for pkg in ato.packages:
        flights = [f for f in pkg.flights if f.id in groups and f.aircraft in _LINKS]
        for f in flights:
            link, max_m, max_d, settings, tdoa = _LINKS[f.aircraft]
            g = groups[f.id]
            donors = [groups[o.id].units[0].id for o in flights
                      if o.id != f.id and _LINKS[o.aircraft][0] == link][:max_d]
            for i, u in enumerate(g.units):
                members = [m.id for m in g.units][:max_m]
                net = {"teamMembers": {k: ({"missionUnitId": uid, "TDOA": True} if tdoa else {"missionUnitId": uid})
                                       for k, uid in enumerate(members, 1)},
                       "donors": {k: {"missionUnitId": uid} for k, uid in enumerate(donors, 1)}}
                s = dict(settings)
                if "flightLead" in s:
                    s["flightLead"] = i == 0
                u.datalinks = {link: {"settings": s, "network": net}}
                counter[link] = counter.get(link, 0) + 1
                code = f"{counter[link]:05o}" if link == "Link16" else f"{counter[link]:04o}"
                try:
                    u.set_property("STN_L16" if link == "Link16" else "SADL_TN", code)
                    raw = (u.callsign_dict or {}).get("name", "") if isinstance(u.callsign_dict, dict) else ""
                    if len(raw) > 2:
                        u.set_property("VoiceCallsignLabel", (raw[0] + raw[:-2][-1]).upper())
                        u.set_property("VoiceCallsignNumber", raw[-2:])
                except Exception as exc:
                    log.debug("datalink properties not set on %s: %s", u.name, exc)
                if i == 0:
                    stn[f.id] = code
    return stn


def whois(ato: Ato, flt: Flight, stn: Dict[str, str]) -> List[Dict[str, str]]:
    """Package who's-who rows for the kneeboard."""
    pkg, _ = ato.find_flight(flt.id)
    return [{"callsign": f.callsign, "aircraft": f.aircraft, "task": f.task, "m3": mode3(ato, f),
             "stn": stn.get(f.id, "-"), "you": f.id == flt.id} for f in (pkg.flights if pkg else [])]
