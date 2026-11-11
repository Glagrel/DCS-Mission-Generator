"""Terrain abstraction over pydcs. New terrains only need an entry in TERRAINS."""
from __future__ import annotations

from functools import lru_cache
from typing import Dict, List, Optional, Tuple

import dcs.terrain as T
from dcs import mapping

# template terrain key -> (pydcs class name, fallback class name or None)
TERRAINS: Dict[str, Tuple[str, Optional[str]]] = {
    "GermanyCW": ("Germany", None),
    "PersianGulf": ("PersianGulf", None),
    "MarianaIslands": ("MarianaIslands", None),
    # Not in pydcs 1.0.0. Falls back to the modern Marianas map (DECISIONS 2).
    "MarianaIslandsWWII": ("MarianaIslandsWWII", "MarianaIslands"),
    "Caucasus": ("Caucasus", None), "Syria": ("Syria", None), "Nevada": ("Nevada", None),
    "Normandy": ("Normandy", None), "TheChannel": ("TheChannel", None), "Sinai": ("Sinai", None),
    "Kola": ("Kola", None), "Afghanistan": ("Afghanistan", None), "Falklands": ("Falklands", None),
}


class TerrainUnsupported(RuntimeError):
    pass


def resolve(key: str) -> Tuple[str, bool]:
    """Return (pydcs class name, is_fallback). Raises if nothing usable."""
    if key not in TERRAINS:
        raise TerrainUnsupported(f"unknown terrain '{key}'")
    primary, fallback = TERRAINS[key]
    if hasattr(T, primary):
        return primary, False
    if fallback and hasattr(T, fallback):
        return fallback, True
    raise TerrainUnsupported(f"terrain '{key}' is not supported by the installed pydcs")


def is_supported(key: str) -> bool:
    try:
        resolve(key)
        return True
    except TerrainUnsupported:
        return False


def is_fallback(key: str) -> bool:
    return resolve(key)[1]


def new_terrain(key: str):
    """A fresh pydcs terrain instance (airports carry mutable state, so never share)."""
    return getattr(T, resolve(key)[0])()


@lru_cache(maxsize=8)
def _airports(key: str) -> Dict[str, Tuple[float, float, int]]:
    t = new_terrain(key)
    out = {}
    for name, ap in t.airports.items():
        ll = ap.position.latlng()
        out[name] = (ll.lat, ll.lng, len(ap.parking_slots))
    return out


def airport_names(key: str) -> List[str]:
    return list(_airports(key))


def airport_latlon(key: str, name: str) -> Tuple[float, float]:
    lat, lon, _ = _airports(key)[name]
    return lat, lon


def airport_parking(key: str, name: str) -> int:
    return _airports(key)[name][2]


def to_point(terrain, lat: float, lon: float) -> mapping.Point:
    return mapping.Point.from_latlng(mapping.LatLng(lat, lon), terrain)


def to_latlon(point: mapping.Point) -> Tuple[float, float]:
    ll = point.latlng()
    return ll.lat, ll.lng
