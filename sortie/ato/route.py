"""Waypoint generation for a flight (lat/lon; the mission builder projects to DCS x/y)."""
from __future__ import annotations

from typing import List, Tuple

from .. import geo, models as M, units
from ..models_ato import Target, Waypoint
from ..state import State

ORBIT_TASKS = ("CAP", "INTERCEPT", "AWACS", "TANKER")
ALT_M = {"CAP": 7500, "INTERCEPT": 7000, "ESCORT": 7000, "SWEEP": 7500, "SEAD": 6500, "DEAD": 6000,
         "STRIKE": 6000, "CAS": 3500, "INTERDICTION": 4500, "ANTISHIP": 5000, "RECON": 8000,
         "TANKER": 6700, "AWACS": 9000, "TRANSPORT": 5000}
SPEED = {"fighter": 850, "attacker": 750, "bomber": 780, "support": 720, "helo": 200, "ww2": 420}


def profile(aircraft: str, task: str, era_kind: str) -> Tuple[float, float]:
    """(altitude m, speed km/h) for an airframe on a task."""
    cls = units.role_class(aircraft)
    speed = SPEED[cls]
    alt = ALT_M.get(task, 6000)
    if cls == "helo":
        alt = 150
    elif era_kind == "ww2":
        alt = {"CAS": 1500, "STRIKE": 3500, "ANTISHIP": 1500, "INTERDICTION": 2000}.get(task, 4000)
        speed = 380 if cls == "bomber" else SPEED["ww2"]
    elif cls == "attacker" and task in ("CAS", "INTERDICTION"):
        alt = 3000
    t = units.aircraft_type(aircraft)
    if t is not None and t.max_speed:
        speed = min(speed, 0.85 * t.max_speed)
    return float(alt), float(speed)


def _threat(st: State, side: str, path: List[geo.Pt], ignore: str = "") -> float:
    total = 0.0
    for s in st.sam_sites.values():
        if s.coalition == side or s.role == "ewr" or s.health < 0.15 or s.id == ignore or not s.known:
            continue
        d = geo.point_path_km((s.lat, s.lon), path)
        if d < s.range_km:
            total += s.health * (1 - d / s.range_km + 0.2)
    return total


def build_route(st: State, side: str, home: M.Airbase, target: Target, aircraft: str, task: str,
                tot_s: float) -> List[Waypoint]:
    alt, speed = profile(aircraft, task, st.meta.era_kind)
    h, t = (home.lat, home.lon), (target.lat, target.lon)
    dist = geo.dist_km(h, t)
    br = geo.bearing(h, t)
    wps: List[Waypoint] = [Waypoint(name="DEP", lat=h[0], lon=h[1], alt_m=0, speed_kmh=0, action="takeoff")]
    if task in ORBIT_TASKS:
        # racetrack across the axis home->station so the orbit faces the threat
        leg = 25.0 if task in ("CAP", "INTERCEPT") else 40.0
        p1, p2 = geo.destination(t, br + 90, leg / 2), geo.destination(t, br - 90, leg / 2)
        wps += [Waypoint(name="STN-A", lat=p1[0], lon=p1[1], alt_m=alt, speed_kmh=speed, action="orbit"),
                Waypoint(name="STN-B", lat=p2[0], lon=p2[1], alt_m=alt, speed_kmh=speed, action="fly")]
    elif task == "TRANSPORT":
        wps.append(Waypoint(name="DEST", lat=t[0], lon=t[1], alt_m=alt, speed_kmh=speed, action="land"))
        _eta(wps, tot_s, anchor="DEST")
        return wps
    else:
        ip_km = min(30.0, dist * 0.3)
        ignore = target.id if target.kind == "sam_site" else ""
        best, best_cost = None, 1e9
        for off in (0, 20, -20, 40, -40):                 # try ingress headings around the direct line
            ip = geo.destination(t, br + 180 + off, ip_km)
            ing = geo.lerp(h, ip, 0.55)
            if off:
                ing = geo.destination(ing, br + (90 if off > 0 else -90), dist * 0.12)
            cost = _threat(st, side, [h, ing, ip], ignore) + abs(off) * 0.004
            if cost < best_cost:
                best, best_cost = (ing, ip), cost
        ing, ip = best
        egress = geo.destination(t, br + 180 - 50, min(35.0, dist * 0.35))
        tgt_alt = alt if task not in ("CAS", "INTERDICTION", "ANTISHIP") else min(alt, 3000)
        wps += [Waypoint(name="INGRESS", lat=ing[0], lon=ing[1], alt_m=alt, speed_kmh=speed),
                Waypoint(name="IP", lat=ip[0], lon=ip[1], alt_m=alt, speed_kmh=speed, action="ip"),
                Waypoint(name="TGT", lat=t[0], lon=t[1], alt_m=tgt_alt, speed_kmh=speed, action="target"),
                Waypoint(name="EGRESS", lat=egress[0], lon=egress[1], alt_m=alt, speed_kmh=speed)]
    wps.append(Waypoint(name="RTB", lat=h[0], lon=h[1], alt_m=0, speed_kmh=0, action="land"))
    _eta(wps, tot_s, anchor="STN-A" if task in ORBIT_TASKS else "TGT")
    return wps


def _eta(wps: List[Waypoint], tot_s: float, anchor: str) -> None:
    """Fill eta_s so the anchor waypoint is reached at tot_s (never departing before t=0)."""
    t, times = 0.0, [0.0]
    for i in range(1, len(wps)):
        spd = wps[i].speed_kmh or wps[i - 1].speed_kmh or 600.0
        t += geo.dist_km((wps[i - 1].lat, wps[i - 1].lon), (wps[i].lat, wps[i].lon)) / spd * 3600.0
        times.append(t)
    idx = next((i for i, w in enumerate(wps) if w.name == anchor), len(wps) - 1)
    shift = max(0.0, tot_s - times[idx])
    for w, ts in zip(wps, times):
        w.eta_s = round(ts + shift, 0)


def route_length_km(wps: List[Waypoint]) -> float:
    return geo.path_length_km([(w.lat, w.lon) for w in wps])


def flight_time_s(wps: List[Waypoint]) -> float:
    return (wps[-1].eta_s or 0.0) - (wps[0].eta_s or 0.0) if wps else 0.0
