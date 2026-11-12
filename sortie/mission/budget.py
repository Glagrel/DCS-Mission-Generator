"""Decide what is simulated in DCS: everything near the player's route, inside the
performance profile's limits. The rest of the war is resolved abstractly."""
from __future__ import annotations

from typing import Any, Dict, List, Set, Tuple

from pydantic import BaseModel, Field

from .. import geo
from ..models_ato import Ato, Flight
from . import clock
from ..state import State

SEP = "|"


def gname(kind: str, entity_id: str, n: int = 1) -> str:
    """DCS group/unit name for a campaign entity: S|kind|entity|n."""
    return f"S{SEP}{kind}{SEP}{entity_id}{SEP}{n}"


def parse_name(name: str):
    """(kind, entity id, n) or None for names SORTIE did not create."""
    parts = str(name or "").split(SEP)
    if len(parts) < 4 or parts[0] != "S":
        return None
    try:
        return parts[1], parts[2], int(parts[3].split(" ")[0].split("-")[0])
    except ValueError:
        return parts[1], parts[2], 0


class Selection(BaseModel):
    flights: List[str] = Field(default_factory=list)          # flight ids, player flight first
    ground_units: List[str] = Field(default_factory=list)
    sam_sites: List[str] = Field(default_factory=list)
    supply_nodes: List[str] = Field(default_factory=list)
    routes: List[str] = Field(default_factory=list)           # convoys
    naval_groups: List[str] = Field(default_factory=list)
    late: List[str] = Field(default_factory=list)             # "kind:id" activated by proximity
    aircraft: int = 0                                         # peak airborne at the same time
    total_aircraft: int = 0                                   # all aircraft that appear in the mission
    dropped: Dict[str, int] = Field(default_factory=dict)     # what the limits cut
    bubble_km: float = 0.0


def _flight_dist(f: Flight, path: List[geo.Pt]) -> float:
    pts = [(w.lat, w.lon) for w in f.waypoints[1:-1]] or [(w.lat, w.lon) for w in f.waypoints]
    return min(geo.point_path_km(p, path) for p in pts)


def _peak(intervals: List[Tuple[float, float, int]], a: float, b: float) -> int:
    """Most aircraft airborne at any moment inside [a, b] among `intervals`."""
    peak = 0
    for t in [a] + [s for s, _, _ in intervals if a < s < b]:
        peak = max(peak, sum(n for s, e, n in intervals if s <= t < e))
    return peak


def select(st: State, ato: Ato, limits: Dict[str, Any], t0: float = 0.0) -> Selection:
    """`t0` = cycle time the mission starts (see mission.clock). The aircraft limit caps how
    many are in the air AT THE SAME TIME, not how many flights the mission may contain."""
    pkg, player = ato.find_flight(ato.player_flight_id or "")
    if player is None:
        raise ValueError("ATO has no player flight; nothing to build")
    path = [(w.lat, w.lon) for w in player.waypoints]
    bubble, spawn_km = float(limits["bubble_km"]), float(limits["spawn_km"])
    t1 = clock.window(player)[1] + 600.0
    sel = Selection(bubble_km=bubble)
    side = player.coalition

    def active(f: Flight) -> Tuple[float, float, int]:
        dep, end = clock.window(f)
        return max(dep, t0), end, f.count

    # --- flights -----------------------------------------------------------------------
    # the player's package always flies; the limit never removes it
    sel.flights = [player.id] + [f.id for f in pkg.flights if f.id != player.id
                                 and clock.phase(f, t0) != clock.DONE]
    busy: List[Tuple[float, float, int]] = [active(ato.find_flight(fid)[1]) for fid in sel.flights]
    home_carriers = {b.id for b in st.airbases.values() if b.kind == "carrier" and any(
        st.squadrons[ato.find_flight(fid)[1].squadron_id].airbase_id == b.id for fid in sel.flights)}
    cands: List[Tuple[float, Flight]] = []
    for p, f in ato.flights():
        if p.id == pkg.id or f.status != "planned":
            continue
        dep, end = clock.window(f)
        if end <= t0 or dep > t1:                      # landed before we start / leaves after we are home
            continue
        dist = _flight_dist(f, path)
        support = f.task in ("AWACS", "TANKER", "SAR") and f.coalition == side
        boat = support and p.target.kind == "airbase" and p.target.id in home_carriers
        if dist <= bubble or support:
            cands.append((-2.0 if boat else -1.0 if support else dist, f))
    for dist, f in sorted(cands, key=lambda x: (x[0], x[1].id)):
        a, b, n = active(f)
        if _peak(busy, a, b) + n > limits["max_air"]:
            sel.dropped["flights"] = sel.dropped.get("flights", 0) + 1
            continue
        sel.flights.append(f.id)
        busy.append((a, b, n))
    sel.aircraft = _peak(busy, t0, max(e for _, e, _ in busy)) if busy else 0
    sel.total_aircraft = sum(n for _, _, n in busy)

    # --- ground objects ----------------------------------------------------------------
    must: Set[str] = set()
    for fid in sel.flights:
        p, _ = ato.find_flight(fid)
        must.add(f"{p.target.kind}:{p.target.id}")
    ground: List[Tuple[float, str, str]] = []
    for g in st.ground_units.values():
        d = geo.point_path_km((g.lat, g.lon), path)
        if d <= bubble or f"front:{g.front_id}" in must:
            ground.append((-1.0 if f"front:{g.front_id}" in must else d, "ground_unit", g.id))
    for s in st.sam_sites.values():
        if s.health < 0.1:
            continue
        d = geo.point_path_km((s.lat, s.lon), path)
        key = f"sam_site:{s.id}"
        if d <= max(bubble, s.range_km) or key in must:
            ground.append((-1.0 if key in must else max(0.0, d - s.range_km), "sam_site", s.id))
    for n in st.supply_nodes.values():
        d = geo.point_path_km((n.lat, n.lon), path)
        key = f"supply_node:{n.id}"
        if d <= bubble or key in must:
            ground.append((-1.0 if key in must else d, "supply_node", n.id))
    for r in st.supply_routes.values():
        src, dst = st.supply_nodes.get(r.src), st.supply_nodes.get(r.dst)
        if not src or not dst or not r.convoy_units or src.coalition != dst.coalition:
            continue
        mid = geo.lerp((src.lat, src.lon), (dst.lat, dst.lon), 0.5)
        d = geo.point_path_km(mid, path)
        key = f"supply_route:{r.id}"
        if d <= bubble or key in must:
            ground.append((-1.0 if key in must else d, "supply_route", r.id))
    ground.sort(key=lambda x: (x[0], x[2]))
    for d, kind, eid in ground[: int(limits["max_ground_groups"])]:
        {"ground_unit": sel.ground_units, "sam_site": sel.sam_sites, "supply_node": sel.supply_nodes,
         "supply_route": sel.routes}[kind].append(eid)
        if d > spawn_km and kind in ("ground_unit", "supply_route"):
            sel.late.append(f"{kind}:{eid}")
    if len(ground) > limits["max_ground_groups"]:
        sel.dropped["ground"] = len(ground) - int(limits["max_ground_groups"])

    # --- naval ---------------------------------------------------------------------------
    carriers = {st.airbases[st.squadrons[ato.find_flight(fid)[1].squadron_id].airbase_id].naval_group
                for fid in sel.flights if ato.find_flight(fid)[1].squadron_id in st.squadrons}
    naval: List[Tuple[float, str]] = []
    for n in st.naval_groups.values():
        if n.health < 0.1:
            continue
        d = geo.point_path_km((n.lat, n.lon), path)
        needed = n.id in carriers or f"naval_group:{n.id}" in must
        if d <= bubble or needed:
            naval.append((-1.0 if needed else d, n.id))
    naval.sort()
    keep = [n for d, n in naval if d < 0] + [n for d, n in naval if d >= 0]
    sel.naval_groups = keep[: max(int(limits["max_naval_groups"]), sum(1 for d, _ in naval if d < 0))]
    if len(keep) > len(sel.naval_groups):
        sel.dropped["naval"] = len(keep) - len(sel.naval_groups)
    return sel
