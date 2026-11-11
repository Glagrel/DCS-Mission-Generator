"""Briefing text (plain text for the DCS briefing panel; structured dict for the GUI)."""
from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, List

from .. import geo
from ..ato import planner
from ..models_ato import Ato, Flight, Package
from ..state import State
from . import loadouts

OBJECTIVES = {
    "CAP": "Hold the CAP station and engage hostile aircraft entering the area.",
    "INTERCEPT": "Scramble and intercept inbound raids as directed.",
    "ESCORT": "Stay with the package and keep enemy fighters off it to and from the target.",
    "SWEEP": "Sweep the area ahead of friendly packages and destroy enemy fighters.",
    "SEAD": "Suppress the air-defence site so the package can reach its target.",
    "DEAD": "Destroy the air-defence site's radars and launchers.",
    "STRIKE": "Destroy the target and return to base.",
    "CAS": "Support friendly ground forces: destroy enemy armour and artillery on the front line.",
    "INTERDICTION": "Find and destroy the supply convoy on the route.",
    "ANTISHIP": "Sink or disable the enemy vessels.",
    "RECON": "Overfly the target area and return with the film.",
    "TRANSPORT": "Deliver the cargo to the destination airfield.",
}


def _hhmm(st: State, seconds: float) -> str:
    return (st.now + timedelta(seconds=seconds or 0)).strftime("%H:%M:%S")


def _freq(f: float) -> str:
    return f"{f:.3f} AM"


def build(st: State, ato: Ato, reason: str) -> Dict[str, Any]:
    """Everything the GUI/briefing needs about the player's sortie."""
    pkg, flt = ato.find_flight(ato.player_flight_id or "")
    if flt is None:
        return {"assigned": False, "reason": reason}
    side = flt.coalition
    sq = st.squadrons[flt.squadron_id]
    base = st.airbases[sq.airbase_id]
    sup = ato.support.get(side, {})
    tgt_wp = next((w for w in flt.waypoints if w.action in ("target", "orbit")), flt.waypoints[-1])
    be = st.meta.bullseye.get(side)
    bulls = None
    if be:
        d = geo.dist_km((be.lat, be.lon), (pkg.target.lat, pkg.target.lon))
        bulls = f"{geo.bearing((be.lat, be.lon), (pkg.target.lat, pkg.target.lon)):03.0f}/{d / 1.852:.0f} nm"
    return {
        "assigned": True, "reason": reason, "turn": ato.turn, "date": st.meta.date,
        "mission": flt.task, "package": {"id": pkg.id, "mission": pkg.mission, "freq": pkg.freq,
                                         "flights": [_flight_row(st, f) for f in pkg.flights]},
        "flight": {"id": flt.id, "callsign": flt.callsign, "aircraft": flt.aircraft, "count": flt.count,
                   "freq": flt.freq, "squadron": sq.name, "base": base.name,
                   "loadout": flt.loadout, "stores": loadouts.describe(flt.aircraft, flt.loadout)},
        "target": {**pkg.target.model_dump(), "bullseye": bulls},
        "tot": _hhmm(st, tgt_wp.eta_s), "tot_s": tgt_wp.eta_s,
        "objective": OBJECTIVES.get(flt.task, "Complete the tasking."),
        "waypoints": [{**w.model_dump(), "time": _hhmm(st, w.eta_s)} for w in flt.waypoints],
        "threats": planner.threats_for(st, side, flt, ato),
        "tankers": sup.get("tankers", []), "awacs": sup.get("awacs", []), "gci": sup.get("gci"),
        "escort": [f.callsign for f in pkg.flights if f.task == "ESCORT" and f.id != flt.id],
        "sead": [f.callsign for f in pkg.flights if f.task == "SEAD" and f.id != flt.id],
        "weather": st.meta.weather,
        "base_status": {"fuel_jet_t": round(base.fuel.jet, 1), "fuel_avgas_t": round(base.fuel.avgas, 1),
                        "munitions": round(base.munition_level, 2), "runway": round(base.runway_health, 2)},
    }


def _flight_row(st: State, f: Flight) -> Dict[str, Any]:
    return {"id": f.id, "callsign": f.callsign, "aircraft": f.aircraft, "count": f.count, "task": f.task,
            "freq": f.freq, "squadron": st.squadrons[f.squadron_id].name, "player": f.is_player}


def text(st: State, b: Dict[str, Any]) -> str:
    """Plain-text briefing for the DCS briefing screen."""
    if not b.get("assigned"):
        return f"No sortie assigned: {b.get('reason', '')}"
    L: List[str] = []
    f, p = b["flight"], b["package"]
    L.append(f"SORTIE - {st.meta.name}")
    L.append(f"Cycle {b['turn']}  {st.now.strftime('%d %b %Y %H:%M')} local")
    L.append("")
    L.append(f"TASKING: {b['mission']} - package {p['id']} ({p['mission']} on {b['target']['name']})")
    L.append(f"WHY YOU: {b['reason']}")
    L.append(f"OBJECTIVE: {b['objective']}")
    L.append(f"TOT: {b['tot']}" + (f"   TARGET BULLSEYE {b['target']['bullseye']}" if b['target'].get('bullseye') else ""))
    L.append("")
    L.append(f"FLIGHT: {f['callsign']}  {f['count']} x {f['aircraft']}  ({f['squadron']}, {f['base']})")
    L.append(f"RADIO: flight/package {_freq(f['freq'])}")
    if f["stores"]:
        L.append("LOADOUT: " + ", ".join(f["stores"]))
    L.append("")
    L.append("PACKAGE:")
    for r in p["flights"]:
        L.append(f"  {r['callsign']:<12} {r['count']} x {r['aircraft']:<14} {r['task']:<8} {_freq(r['freq'])}"
                 + ("  <- YOU" if r["player"] else ""))
    L.append("")
    L.append("ROUTE:")
    for i, w in enumerate(b["waypoints"]):
        L.append(f"  {i} {w['name']:<8} {w['time']}  {w['alt_m']:.0f} m  {w['speed_kmh']:.0f} km/h")
    L.append("")
    th = b["threats"]
    if th["sams"]:
        L.append("AIR DEFENCES NEAR ROUTE:")
        for s in th["sams"][:8]:
            L.append(f"  {s['type']:<10} {s['name']} - {s['dist_km']} km from route"
                     + (" (ROUTE INSIDE RING)" if s["inside"] else ""))
    else:
        L.append("AIR DEFENCES NEAR ROUTE: none known")
    if th["air"]:
        L.append("EXPECTED AIR OPPOSITION:")
        for a in th["air"][:6]:
            L.append(f"  {a['count']} x {a['aircraft']} ({a['task']}) near {a['near']}")
    L.append("")
    for t in b["tankers"]:
        L.append(f"TANKER: {t['callsign']} {t['aircraft']} {_freq(t['freq'])} TACAN {t.get('tacan', '-')}")
    for a in b["awacs"]:
        L.append(f"AWACS: {a['callsign']} {a['aircraft']} {_freq(a['freq'])}")
    if b.get("gci"):
        L.append(f"GCI: {_freq(b['gci']['freq'])}")
    w = b["weather"]
    if w:
        L.append(f"WEATHER: wind {w.get('wind_dir', 0):03d}/{w.get('wind_ms', 0)} m/s, cloud base "
                 f"{w.get('cloud_base_m', 0)} m, {w.get('temp_c', 15)} C")
    bs = b["base_status"]
    L.append(f"BASE STOCKS: munitions {bs['munitions']:.0%}, runway {bs['runway']:.0%}")
    return "\n".join(L)
