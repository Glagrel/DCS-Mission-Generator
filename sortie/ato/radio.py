"""Radio plan: frequencies per era/doctrine and callsigns."""
from __future__ import annotations

from typing import Dict

from .. import units

# (first MHz, step MHz, last MHz) per doctrine. AM throughout.
BANDS: Dict[str, tuple] = {
    "nato": (251.0, 0.25, 399.0),      # UHF
    "soviet": (124.0, 0.25, 149.0),    # VHF (R-832/R-862 class sets)
    "ww2": (124.0, 0.5, 155.5),        # SCR-522 class VHF sets
}
GUARD = {"nato": 243.0, "soviet": 121.5, "ww2": 121.5}


def band_for(doctrine: str, era_kind: str) -> str:
    return "ww2" if era_kind == "ww2" else (doctrine if doctrine in BANDS else "nato")


def clamp_to_aircraft(freq: float, aircraft: str) -> float:
    """Keep the frequency if we cannot tell; pydcs exposes only the default radio frequency."""
    t = units.aircraft_type(aircraft)
    default = getattr(t, "radio_frequency", None) if t else None
    if not default:
        return freq
    # an airframe whose default is VHF (<200) cannot be assumed to tune UHF and vice versa
    return freq if (default < 200) == (freq < 200) else float(default)


class RadioPlan:
    """Hands out frequencies deterministically; side offsets keep the two sides apart."""

    def __init__(self, doctrine: str, era_kind: str, side: str) -> None:
        self.band = band_for(doctrine, era_kind)
        self.first, self.step, self.last = BANDS[self.band]
        self.n = 0 if side == "blue" else 40
        self.guard = GUARD[self.band]

    def next(self) -> float:
        f = self.first + self.n * self.step
        self.n += 1
        if f > self.last:
            self.n, f = 0, self.first
        return round(f, 3)


def callsign(base: str, flight_no: int, doctrine: str) -> str:
    """NATO: 'Viper 1'; Soviet-style: three-digit numbers ('201' -> '211', '221', ...)."""
    if doctrine == "soviet" and base.isdigit():
        return str(int(base) + 10 * (flight_no - 1))
    return f"{base} {flight_no}"


def tacan_channel(index: int) -> str:
    return f"{31 + index * 2}Y"
