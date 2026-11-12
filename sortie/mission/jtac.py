"""Ground JTACs for close air support.

Base DCS does the 9-line: a ground vehicle with the FAC task appears in your radio menu
(F10/F5 -> JTAC), checks you in, talks you onto targets and lases on request. SORTIE puts one
a few km on the friendly side of each CAS / interdiction target your coalition is working this
cycle, on its own VHF AM frequency with its own laser code (both in the briefing and
kneeboard). The vehicle is hidden from AI and immortal, as is usual for scripted JTACs, so
it does not die in the first minute and take the 9-line with it.

With MOOSE loaded and "autolase" on, MOOSE's AUTOLASE also makes the JTAC find, smoke and
lase targets by itself on that code (F10 -> AUTOLASE for status and smoke).
"""
from __future__ import annotations

from typing import Any, Dict, List

from dcs import task

from .. import geo, terrain, units
from ..models_ato import Ato
from ..state import State
from .budget import Selection, gname

JTAC_MISSIONS = ("CAS", "INTERDICTION")
CALLNAMES = {1: "Axeman", 2: "Darknight", 3: "Warrior", 4: "Pointer", 5: "Eyeball", 6: "Moonbeam",
             7: "Whiplash", 8: "Finger", 9: "Pinpoint", 10: "Ferret"}
LASER = ["1688", "1686", "1678", "1668"]
FREQS = [133.0, 133.5, 134.0, 134.5]           # MHz AM: VHF, inside every western CAS jet's radios
MAX_JTACS = 3
STANDOFF_KM = 3.0


def _vehicle(side: str, year: int):
    for t in (["Hummer", "M1043 HMMWV Armament", "M 818"] if side == "blue" else ["UAZ-469", "BTR-80"]):
        if units.vehicle_type(t) is not None and units.year_of(t) <= max(year, 1980):
            return t
    return None


def add_jtacs(m, st: State, ato: Ato, sel: Selection, man, autolase: bool) -> List[Dict[str, Any]]:
    """Place the JTACs. Returns their briefing rows (also the Lua config for AUTOLASE)."""
    if st.meta.era_kind == "ww2":
        return []
    side = st.meta.player_side
    rows: List[Dict[str, Any]] = []
    seen = set()
    for fid in sel.flights:
        pkg, _ = ato.find_flight(fid)
        if pkg.coalition != side or pkg.mission not in JTAC_MISSIONS or pkg.id in seen:
            continue
        if pkg.target.kind not in ("front", "ground_unit", "supply_route"):
            continue
        seen.add(pkg.id)
        vt = _vehicle(side, st.meta.year)
        if vt is None or len(rows) >= MAX_JTACS:
            break
        i = len(rows)
        tgt = (pkg.target.lat, pkg.target.lon)
        own = _own_side_point(st, pkg, side)
        lat, lon = geo.destination(tgt, geo.bearing(tgt, own), STANDOFF_KM) if own else tgt
        name = gname("jtac", pkg.id)
        cs_num = (i % len(CALLNAMES)) + 1
        callsign = f"{CALLNAMES[cs_num]} 1-1"
        vg = m.vehicle_group(m.country(st.meta.countries[side][0]), name, units.vehicle_type(vt),
                             terrain.to_point(m.terrain, lat, lon), heading=geo.bearing((lat, lon), tgt), group_size=1)
        p0 = vg.points[0]
        p0.tasks.append(task.SetInvisibleCommand(True))
        p0.tasks.append(task.SetImmortalCommand(True))
        p0.tasks.append(task.FAC(callsign=cs_num, designation=task.Designation.Auto, frequency=FREQS[i],
                                 modulation=task.Modulation.AM, number=1))
        man.add(name, "jtac", pkg.id, 1, coalition=side, lat=lat, lon=lon)
        rows.append({"group": name, "callsign": callsign, "freq": FREQS[i], "code": LASER[i],
                     "package": pkg.id, "target": pkg.target.name, "lat": round(lat, 5), "lon": round(lon, 5),
                     "vehicle": vt, "autolase": autolase})
    return rows


def _own_side_point(st: State, pkg, side: str):
    """A point on our side of the target: our end of its front, else our nearest airbase."""
    front = st.fronts.get(pkg.target.id) if pkg.target.kind == "front" else None
    if front is None and pkg.target.kind == "ground_unit":
        g = st.ground_units.get(pkg.target.id)
        front = st.fronts.get(g.front_id) if g else None
    if front is not None:
        a = front.a if side == "blue" else front.b
        return a.lat, a.lon
    bases = [b for b in st.airbases.values() if b.coalition == side]
    if not bases:
        return None
    b = min(bases, key=lambda b: geo.dist_km((b.lat, b.lon), (pkg.target.lat, pkg.target.lon)))
    return b.lat, b.lon


def briefing_lines(rows: List[Dict[str, Any]]) -> List[str]:
    return [f"JTAC: {r['callsign']} {r['freq']:.3f} AM, laser {r['code']}, working {r['target']}"
            + (" (autolase: smokes and lases on its own)" if r.get("autolase") else "") for r in rows]
