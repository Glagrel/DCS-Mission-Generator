"""Briefing text (plain text for the DCS briefing panel; structured dict for the GUI)."""
from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, List, Optional

from .. import geo, measure
from ..ato import planner
from ..models_ato import Ato, Flight
from ..state import State
from . import codes, loadouts

JOIN_NOTE = "JOIN is the package rendezvous in friendly territory: link up there and push at the JOIN time."

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


def flight_card(st: State, ato: Ato, flt: Flight, t0: float, units: str) -> Dict[str, Any]:
    """Route and radio data for one flight (used for the player and for co-op guests)."""
    pkg, _ = ato.find_flight(flt.id)
    sq = st.squadrons[flt.squadron_id]
    base = st.airbases[sq.airbase_id]
    wps = []
    for i, w in enumerate(flt.waypoints):
        leg = geo.dist_km((flt.waypoints[i - 1].lat, flt.waypoints[i - 1].lon), (w.lat, w.lon)) if i else 0.0
        hdg = geo.bearing((flt.waypoints[i - 1].lat, flt.waypoints[i - 1].lon), (w.lat, w.lon)) if i else 0.0
        wps.append({**w.model_dump(), "time": _hhmm(st, w.eta_s), "mission_s": max(0.0, (w.eta_s or 0) - t0),
                    "alt": measure.alt(w.alt_m, units), "speed": measure.speed(w.speed_kmh, units),
                    "leg": measure.dist(leg, units) if i else "-", "hdg": f"{hdg:03.0f}" if i else "-"})
    tgt_wp = next((w for w in flt.waypoints if w.action in ("target", "orbit")), flt.waypoints[-1])
    fuel = codes.fuel_plan(flt, (base.lat, base.lon))
    modern = st.meta.era_kind != "ww2"
    return {"id": flt.id, "callsign": flt.callsign, "aircraft": flt.aircraft, "count": flt.count,
            "task": flt.task, "freq": flt.freq, "squadron": sq.name, "base": base.name,
            "loadout": flt.loadout, "stores": loadouts.describe(flt.aircraft, flt.loadout),
            "package": pkg.id, "target": pkg.target.name, "tot": _hhmm(st, tgt_wp.eta_s),
            "takeoff": _hhmm(st, flt.waypoints[0].eta_s), "waypoints": wps,
            "objective": OBJECTIVES.get(flt.task, "Complete the tasking."),
            "mode3": codes.mode3(ato, flt) if modern else "", "laser": codes.laser(ato, flt) if modern else "",
            "link": codes.link_of(flt.aircraft) or "",
            "bingo": codes.fuel_text(fuel["bingo_kg"], measure.norm(units)) if fuel else "",
            "joker": codes.fuel_text(fuel["joker_kg"], measure.norm(units)) if fuel else "",
            "target_ddm": " ".join(measure.ddm(pkg.target.lat, pkg.target.lon))}


def nav_text(nav: Dict[str, Any]) -> List[str]:
    """Lines describing a base's navaids."""
    if not nav:
        return []
    out = []
    if nav.get("tacan"):
        out.append(f"TACAN {nav['tacan']}")
    if nav.get("icls"):
        out.append(f"ICLS channel {nav['icls']}")
    if nav.get("link4"):
        out.append(f"Link 4 / ACLS {nav['link4']}.000")
    if nav.get("vor"):
        out.append(f"VOR {nav['vor']}")
    for i in nav.get("ils", []):
        out.append(f"ILS RWY {i['runway']} {i['freq']:.2f} {i['ident']}")
    atc = nav.get("atc") or {}
    if atc.get("uhf"):
        out.append(f"Tower {atc['uhf']:.3f} / {atc.get('vhf', 0):.3f}")
    return out


def build(st: State, ato: Ato, reason: str, t0: float = 0.0, units: str = "imperial",
          slots: Optional[List[Dict[str, Any]]] = None, nav: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Everything the GUI/briefing needs about the player's sortie."""
    pkg, flt = ato.find_flight(ato.player_flight_id or "")
    if flt is None:
        return {"assigned": False, "reason": reason}
    side = flt.coalition
    base = st.airbases[st.squadrons[flt.squadron_id].airbase_id]
    sup = ato.support.get(side, {})
    card = flight_card(st, ato, flt, t0, units)
    be = st.meta.bullseye.get(side)
    bulls = None
    if be:
        d = geo.dist_km((be.lat, be.lon), (pkg.target.lat, pkg.target.lon))
        bulls = f"{geo.bearing((be.lat, be.lon), (pkg.target.lat, pkg.target.lon)):03.0f}/{measure.dist(d, units)}"
    from .. import weather as _wx
    import random as _r
    w = _wx.at(_wx.normalize(dict(st.meta.weather), _r.Random("wx")), st.now + timedelta(seconds=t0)) if st.meta.weather else {}
    tankers = [{**t, "alt": measure.alt(t.get("alt_m", 0), units)} for t in sup.get("tankers", [])]
    return {
        "assigned": True, "reason": reason, "turn": ato.turn, "date": st.meta.date, "units": measure.norm(units),
        "mission": flt.task, "package": {"id": pkg.id, "mission": pkg.mission, "freq": pkg.freq,
                                         "flights": [_flight_row(st, f, ato) for f in pkg.flights]},
        "flight": {k: card[k] for k in ("id", "callsign", "aircraft", "count", "freq", "squadron", "base",
                                        "loadout", "stores", "mode3", "laser", "bingo", "joker", "link")},
        "target_ddm": card["target_ddm"], "stn": {}, "weapon_notes": {},
        "target": {**pkg.target.model_dump(), "bullseye": bulls},
        "tot": card["tot"], "takeoff": card["takeoff"], "objective": card["objective"],
        "mission_start": _hhmm(st, t0), "t0_s": t0,
        "waypoints": card["waypoints"],
        "threats": _threats(st, ato, flt, units),
        "tankers": tankers, "awacs": sup.get("awacs", []), "gci": sup.get("gci"),
        "escort": [f.callsign for f in pkg.flights if f.task == "ESCORT" and f.id != flt.id],
        "sead": [f.callsign for f in pkg.flights if f.task == "SEAD" and f.id != flt.id],
        "weather": w, "weather_text": _weather(w, units), "slots": slots or [],
        "pre_mission": ato.support.get("pre_mission", []),
        "nav": nav or {}, "nav_lines": nav_text(nav or {}),
        "join": next(({"time": w["time"], "lat": w["lat"], "lon": w["lon"]} for w in card["waypoints"]
                      if w["name"] == "JOIN"), None),
        "base_status": {"fuel_jet_t": round(base.fuel.jet, 1), "fuel_avgas_t": round(base.fuel.avgas, 1),
                        "munitions": round(base.munition_level, 2), "runway": round(base.runway_health, 2)},
    }


def _threats(st: State, ato: Ato, flt: Flight, units: str) -> Dict[str, Any]:
    th = planner.threats_for(st, flt.coalition, flt, ato)
    for s in th["sams"]:
        s["range"] = measure.dist(s["range_km"], units)
        s["dist"] = measure.dist(s["dist_km"], units)
    return th


def _weather(w: Dict[str, Any], units: str) -> str:
    if not w:
        return ""
    from .. import weather
    return weather.describe(w, units) + "  [" + weather.metar(w) + "]"


def _flight_row(st: State, f: Flight, ato: Optional[Ato] = None) -> Dict[str, Any]:
    ato = ato or st.ato
    return {"id": f.id, "callsign": f.callsign, "aircraft": f.aircraft, "count": f.count, "task": f.task,
            "freq": f.freq, "squadron": st.squadrons[f.squadron_id].name, "player": f.is_player,
            "mode3": codes.mode3(ato, f) if ato and st.meta.era_kind != "ww2" else ""}


def text(st: State, b: Dict[str, Any]) -> str:
    """Plain-text briefing for the DCS briefing screen."""
    if not b.get("assigned"):
        return f"No sortie assigned: {b.get('reason', '')}"
    L: List[str] = []
    f, p = b["flight"], b["package"]
    L.append(f"SORTIE - {st.meta.name}")
    L.append(f"Cycle {b['turn']}  mission starts {b['mission_start']} local")
    L.append("")
    L.append(f"TASKING: {b['mission']} - package {p['id']} ({p['mission']} on {b['target']['name']})")
    L.append(f"WHY YOU: {b['reason']}")
    L.append(f"OBJECTIVE: {b['objective']}")
    L.append(f"TAKE-OFF: {b['takeoff']}   TOT: {b['tot']}"
             + (f"   TARGET BULLSEYE {b['target']['bullseye']}" if b['target'].get('bullseye') else ""))
    L.append("")
    L.append(f"FLIGHT: {f['callsign']}  {f['count']} x {f['aircraft']}  ({f['squadron']}, {f['base']})")
    L.append(f"RADIO: flight/package {_freq(f['freq'])}")
    if f.get("mode3"):
        L.append(f"IFF MODE 3: {f['mode3']}   LASER CODE: {f['laser']}")
    if f.get("bingo"):
        L.append(f"BINGO {f['bingo']}   JOKER {f['joker']}  (planning figures)")
    L.append(f"TARGET: {b['target']['name']}  {b.get('target_ddm', '')}")
    for note in b.get("weapon_notes", {}).get(f["id"], []):
        L.append(f"WEATHER WEAPON SWAP: {note}")
    if f["stores"]:
        L.append("LOADOUT: " + ", ".join(f["stores"]))
    L.append("")
    L.append("PACKAGE:")
    for r in p["flights"]:
        L.append(f"  {r['callsign']:<12} {r['count']} x {r['aircraft']:<14} {r['task']:<8} {_freq(r['freq'])}"
                 + (f"  M3 {r['mode3']}" if r.get("mode3") else "")
                 + (f"  STN {b['stn'][r['id']]}" if b.get("stn", {}).get(r["id"]) else "")
                 + ("  <- YOU" if r["player"] else ""))
    if f.get("link") and any(b.get("stn", {}).values()):
        L.append(f"  {f['link']}: your flight are team members; other {f['link']} flights of the package are donors.")
    if len(b["slots"]) > 1 or any(s["seats"] > 1 for s in b["slots"]):
        L.append("")
        L.append("CO-OP SLOTS:")
        for s in b["slots"]:
            L.append(f"  {s['callsign']:<12} {s['aircraft']:<14} {s['task']:<8} {s['seats']} seat(s) at {s['base']}"
                     f"  {_freq(s['freq'])}" + ("  (career pilot)" if s["career"] else ""))
    L.append("")
    L.append("ROUTE:")
    for i, w in enumerate(b["waypoints"]):
        L.append(f"  {i} {w['name']:<8} {w['time']}  {w['alt']:>9}  {w['speed']:>8}  hdg {w['hdg']}  {w['leg']}")
    if b.get("join"):
        L.append("  " + JOIN_NOTE + f" Push {b['join']['time']}.")
    L.append("")
    th = b["threats"]
    if th["sams"]:
        L.append("AIR DEFENCES NEAR ROUTE:")
        for s in th["sams"][:8]:
            L.append(f"  {s['type']:<10} {s['name']} - {s['dist']} from route, range {s['range']}"
                     + (" (ROUTE INSIDE RING)" if s["inside"] else ""))
    else:
        L.append("AIR DEFENCES NEAR ROUTE: none known")
    if th["air"]:
        L.append("EXPECTED AIR OPPOSITION:")
        for a in th["air"][:6]:
            L.append(f"  {a['count']} x {a['aircraft']} ({a['task']}) near {a['near']}")
    L.append("")
    for t in b["tankers"]:
        L.append(f"TANKER: {t['callsign']} {t['aircraft']} {_freq(t['freq'])} TACAN {t.get('tacan', '-')} {t['alt']}"
                 + (" (recovery tanker, overhead the carrier)" if t.get("recovery") else ""))
    for a in b["awacs"]:
        L.append(f"AWACS: {a['callsign']} {a['aircraft']} {_freq(a['freq'])}")
    if b.get("gci"):
        L.append(f"GCI: {_freq(b['gci']['freq'])}")
    if b.get("nav_lines"):
        L.append(f"HOME {b['nav'].get('name', '')}: " + "; ".join(b["nav_lines"]))
    if b["weather_text"]:
        L.append("WEATHER: " + b["weather_text"])
    bs = b["base_status"]
    L.append(f"BASE STOCKS: munitions {bs['munitions']:.0%}, runway {bs['runway']:.0%}")
    if b["pre_mission"]:
        L.append("")
        L.append("EARLIER THIS CYCLE:")
        L += [f"  {line}" for line in b["pre_mission"][:8]]
    return "\n".join(L)
