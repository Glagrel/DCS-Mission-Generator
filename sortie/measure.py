"""Unit display: the campaign stores metric values; briefings, kneeboards and the GUI show
either metric or imperial (aviation) units according to the `units` setting."""
from __future__ import annotations

SYSTEMS = ("imperial", "metric")


def norm(system: str) -> str:
    return system if system in SYSTEMS else "imperial"


def alt(m: float, system: str) -> str:
    if norm(system) == "metric":
        return f"{round(m / 10.0) * 10:,.0f} m".replace(",", " ")
    return f"{round(m * 3.28084 / 100.0) * 100:,.0f} ft"


def speed(kmh: float, system: str) -> str:
    return f"{kmh:.0f} km/h" if norm(system) == "metric" else f"{kmh / 1.852:.0f} kt"


def dist(km: float, system: str) -> str:
    return f"{km:.0f} km" if norm(system) == "metric" else f"{km / 1.852:.0f} nm"


def wind(direction: float, ms: float, system: str) -> str:
    return f"{int(direction) % 360:03d}/{ms:.0f} m/s" if norm(system) == "metric" \
        else f"{int(direction) % 360:03d}/{ms * 1.94384:.0f} kt"


def temp(c: float, system: str) -> str:
    return f"{c:.0f} C" if norm(system) == "metric" else f"{c * 9 / 5 + 32:.0f} F"


def ddm(lat: float, lon: float) -> tuple:
    """Degrees and decimal minutes, the format most DCS navigation systems take."""
    def one(v: float, pos: str, neg: str, width: int) -> str:
        hemi = pos if v >= 0 else neg
        v = abs(v)
        deg = int(v)
        return f"{hemi}{deg:0{width}d} {(v - deg) * 60:06.3f}"
    return one(lat, "N", "S", 2), one(lon, "E", "W", 3)


def labels(system: str) -> dict:
    """Unit labels and conversion factors for the GUI (value_in_unit = metric_value * factor)."""
    if norm(system) == "metric":
        return {"system": "metric", "alt": "m", "alt_f": 1.0, "speed": "km/h", "speed_f": 1.0,
                "dist": "km", "dist_f": 1.0, "wind": "m/s", "wind_f": 1.0}
    return {"system": "imperial", "alt": "ft", "alt_f": 3.28084, "speed": "kt", "speed_f": 1 / 1.852,
            "dist": "nm", "dist_f": 1 / 1.852, "wind": "kt", "wind_f": 1.94384}
