"""Mission clock. ATO times are seconds after the start of the cycle; the DCS mission starts
at T0 = just before the player's flight has to start engines, so nobody sits waiting.

Relative to T0 every other flight is in one of three phases:
  done     - landed before T0: never in the mission (resolved abstractly before generation)
  airborne - took off before T0: placed in the air where it would be at T0
  ground   - takes off later: parked at its base, starts up shortly before its take-off time
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel

from .. import geo
from ..models_ato import Ato, Flight, Waypoint

DONE, AIRBORNE, GROUND = "done", "airborne", "ground"


def mission_t0(ato: Ato, d: Dict[str, Any]) -> float:
    """Cycle time at which the DCS mission starts."""
    _, flt = ato.find_flight(ato.player_flight_id or "")
    if flt is None or not flt.waypoints:
        return 0.0
    startup = float(d.get("mission", {}).get("startup_minutes", 10)) * 60.0
    return max(0.0, (flt.waypoints[0].eta_s or 0.0) - startup)


def window(f: Flight) -> Tuple[float, float]:
    """(take-off, landing) in cycle seconds."""
    if not f.waypoints:
        return 0.0, 0.0
    return f.waypoints[0].eta_s or 0.0, f.waypoints[-1].eta_s or 0.0


def phase(f: Flight, t0: float) -> str:
    dep, end = window(f)
    if end <= t0:
        return DONE
    return AIRBORNE if dep < t0 else GROUND


class AirState(BaseModel):
    lat: float
    lon: float
    alt_m: float
    speed_kmh: float
    next_index: int               # first waypoint of the flight still ahead
    on_station: bool = False      # holding its orbit at T0
    hold_s: float = 0.0           # station time still to serve


def station_end(f: Flight) -> Optional[float]:
    """Cycle time an orbiting flight leaves its station (None for non-orbit flights)."""
    idx = [i for i, w in enumerate(f.waypoints) if w.name.startswith("STN")]
    if not idx or idx[-1] + 1 >= len(f.waypoints):
        return None
    last, nxt = f.waypoints[idx[-1]], f.waypoints[idx[-1] + 1]
    spd = nxt.speed_kmh or last.speed_kmh or 600.0
    home = geo.dist_km((last.lat, last.lon), (nxt.lat, nxt.lon)) / spd * 3600.0
    return (nxt.eta_s or 0.0) - home


def air_state(f: Flight, t0: float) -> AirState:
    """Where an already-airborne flight is at T0 (interpolated along its route)."""
    wps: List[Waypoint] = f.waypoints
    stn = [i for i, w in enumerate(wps) if w.name.startswith("STN")]
    end = station_end(f)
    if stn and end is not None and (wps[stn[0]].eta_s or 0.0) <= t0 < end:
        w = wps[stn[0]]
        return AirState(lat=w.lat, lon=w.lon, alt_m=w.alt_m, speed_kmh=w.speed_kmh, next_index=stn[0] + 1,
                        on_station=True, hold_s=end - t0)
    for i in range(len(wps) - 1):
        a, b = wps[i], wps[i + 1]
        ta, tb = a.eta_s or 0.0, b.eta_s or 0.0
        if stn and i == stn[-1] and end is not None:
            ta = end                           # the leg home starts when the station time is over
        if ta <= t0 < tb:
            frac = (t0 - ta) / (tb - ta) if tb > ta else 0.0
            lat, lon = geo.lerp((a.lat, a.lon), (b.lat, b.lon), frac)
            cruise = max(a.alt_m, b.alt_m) if (i == 0 or b.action == "land") else a.alt_m + (b.alt_m - a.alt_m) * frac
            if i == 0:                         # climbing out
                cruise = max(600.0, b.alt_m * min(1.0, frac * 3))
            elif b.action == "land":           # descending home
                cruise = max(900.0, a.alt_m * (1.0 - frac * 0.8))
            return AirState(lat=lat, lon=lon, alt_m=cruise, speed_kmh=b.speed_kmh or a.speed_kmh or 600.0,
                            next_index=i + 1)
    w = wps[-2] if len(wps) > 1 else wps[0]
    return AirState(lat=w.lat, lon=w.lon, alt_m=max(900.0, w.alt_m), speed_kmh=w.speed_kmh or 600.0,
                    next_index=len(wps) - 1)


def start_delay(f: Flight, t0: float, d: Dict[str, Any]) -> float:
    """Mission seconds a parked AI flight waits before starting engines."""
    taxi = float(d.get("mission", {}).get("taxi_minutes", 5)) * 60.0
    return max(0.0, window(f)[0] - t0 - taxi)


def rel(t: Optional[float], t0: float) -> float:
    return max(0.0, (t or 0.0) - t0)
