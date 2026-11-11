"""Spherical geometry helpers on lat/lon (degrees). Distances in km."""
from __future__ import annotations

import math
from typing import Iterable, List, Sequence, Tuple

R_KM = 6371.0
Pt = Tuple[float, float]  # (lat, lon)


def dist_km(a: Pt, b: Pt) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * R_KM * math.asin(min(1.0, math.sqrt(h)))


def bearing(a: Pt, b: Pt) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    y = math.sin(lo2 - lo1) * math.cos(la2)
    x = math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(lo2 - lo1)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def destination(a: Pt, bearing_deg: float, km: float) -> Pt:
    la1, lo1, br, d = math.radians(a[0]), math.radians(a[1]), math.radians(bearing_deg), km / R_KM
    la2 = math.asin(math.sin(la1) * math.cos(d) + math.cos(la1) * math.sin(d) * math.cos(br))
    lo2 = lo1 + math.atan2(math.sin(br) * math.sin(d) * math.cos(la1),
                           math.cos(d) - math.sin(la1) * math.sin(la2))
    return math.degrees(la2), (math.degrees(lo2) + 540.0) % 360.0 - 180.0


def lerp(a: Pt, b: Pt, t: float) -> Pt:
    """Linear interpolation; fine at theater scale."""
    return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t


def point_segment_km(p: Pt, a: Pt, b: Pt) -> float:
    """Distance from p to segment a-b using a local flat projection."""
    kx = 111.32 * math.cos(math.radians(p[0]))
    ax, ay = (a[1] - p[1]) * kx, (a[0] - p[0]) * 110.57
    bx, by = (b[1] - p[1]) * kx, (b[0] - p[0]) * 110.57
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / L2))
    return math.hypot(ax + t * dx, ay + t * dy)


def point_path_km(p: Pt, path: Sequence[Pt]) -> float:
    if not path:
        return float("inf")
    if len(path) == 1:
        return dist_km(p, path[0])
    return min(point_segment_km(p, path[i], path[i + 1]) for i in range(len(path) - 1))


def path_length_km(path: Sequence[Pt]) -> float:
    return sum(dist_km(path[i], path[i + 1]) for i in range(len(path) - 1))


def front_line(a: Pt, b: Pt, position: float, width_km: float) -> List[Pt]:
    """Two end points of the front line: perpendicular to axis a->b at `position`."""
    c = lerp(a, b, position)
    br = bearing(a, b)
    return [destination(c, br - 90, width_km / 2), destination(c, br + 90, width_km / 2)]


def centroid(pts: Iterable[Pt]) -> Pt:
    pts = list(pts)
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
