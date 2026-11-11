"""Ground, air-defence, supply and naval objects for the mission (pydcs)."""
from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional

from dcs import statics, task
from dcs.point import PointAction

from .. import geo, models as M, terrain, units
from ..state import State
from .budget import Selection, gname

log = logging.getLogger("sortie.mission")
MAX_VEHICLES_PER_FORMATION = 12


class Manifest(dict):
    """group name -> {'kind','id','units': n spawned, 'represents': campaign count}."""

    def add(self, name: str, kind: str, eid: str, n: int, **extra: Any) -> None:
        self[name] = {"kind": kind, "id": eid, "units": n, **extra}


def static_type(name: str):
    for cat in (statics.Warehouse, statics.Fortification, statics.GroundObject, statics.Cargo):
        t = getattr(cat, name, None)
        if t is not None:
            return t
    return statics.Warehouse.Warehouse


def _vehicle_group(m, country, name: str, kinds: Dict[str, int], centre, heading: float, spacing: float,
                   ring: bool = False):
    """One DCS group with mixed vehicle types laid out in a grid (or ring for SAM sites)."""
    flat: List[str] = [k for k, n in kinds.items() for _ in range(n)]
    vg = m.vehicle_group(country, name, units.vehicle_type(flat[0]), centre, heading=heading, group_size=1)
    vg.units[0].name = f"{name} #1"
    cols = max(1, int(math.ceil(math.sqrt(len(flat)))))
    for i, kind in enumerate(flat[1:], start=1):
        u = m.vehicle(f"{name} #{i + 1}", units.vehicle_type(kind))
        if ring:
            u.position = centre.point_from_heading(360.0 * i / max(1, len(flat) - 1), spacing)
        else:
            u.position = centre.point_from_heading(heading + 90, (i % cols) * spacing) \
                               .point_from_heading(heading + 180, (i // cols) * spacing)
        u.heading = heading
        vg.add_unit(u)
    return vg


def scaled_units(kinds: Dict[str, int], strength: float, cap: int = MAX_VEHICLES_PER_FORMATION) -> Dict[str, int]:
    """Scale a formation by strength and cap its size, keeping at least one of the first type."""
    total = sum(kinds.values())
    factor = strength * min(1.0, cap / total) if total else 0.0
    out = {k: int(round(n * factor)) for k, n in kinds.items()}
    out = {k: n for k, n in out.items() if n > 0}
    return out or {next(iter(kinds)): 1}


def add_ground_units(m, st: State, sel: Selection, man: Manifest) -> None:
    for gid in sel.ground_units:
        g = st.ground_units[gid]
        front = st.fronts[g.front_id]
        enemy_anchor = front.b if g.coalition == "blue" else front.a
        heading = geo.bearing((g.lat, g.lon), (enemy_anchor.lat, enemy_anchor.lon))
        kinds = scaled_units(g.units, g.strength)
        name = gname("gnd", g.id)
        vg = _vehicle_group(m, m.country(g.country), name, kinds, terrain.to_point(m.terrain, g.lat, g.lon),
                            heading, 45.0)
        vg.late_activation = f"ground_unit:{gid}" in sel.late
        man.add(name, "ground_unit", g.id, len(vg.units), represents=sum(g.units.values()),
                late=vg.late_activation, lat=g.lat, lon=g.lon)


def add_sam_sites(m, st: State, sel: Selection, man: Manifest) -> None:
    for sid in sel.sam_sites:
        s = st.sam_sites[sid]
        tpl = units.sam_template(s.template)
        kinds = dict(tpl["units"])
        if s.health < 0.99:                     # damaged sites come back with fewer launchers
            first = next(iter(kinds))
            kinds = {k: (n if k == first or n == 1 else max(1, int(round(n * s.health)))) for k, n in kinds.items()}
        name = gname("sam", s.id)
        vg = _vehicle_group(m, m.country(s.country), name, kinds, terrain.to_point(m.terrain, s.lat, s.lon),
                            0.0, 90.0 if s.role == "sam" else 40.0, ring=True)
        vg.points[0].tasks.append(task.OptAlarmState(2))      # 2 = red: radars on, ready to fire
        man.add(name, "sam_site", s.id, len(vg.units), represents=sum(tpl["units"].values()),
                role=s.role, lat=s.lat, lon=s.lon)


def add_supply_nodes(m, st: State, sel: Selection, man: Manifest) -> None:
    """Each node is a cluster of destructible statics; damaged nodes spawn with dead objects."""
    for nid in sel.supply_nodes:
        n = st.supply_nodes[nid]
        centre = terrain.to_point(m.terrain, n.lat, n.lon)
        stype = static_type(n.static_type)
        alive = max(0, min(n.n_objects, int(math.ceil(n.n_objects * n.health - 1e-6))))
        cols = max(1, int(math.ceil(math.sqrt(n.n_objects))))
        for i in range(n.n_objects):
            pos = centre.point_from_heading(90, (i % cols) * 70.0).point_from_heading(180, (i // cols) * 70.0)
            name = gname("sup", n.id, i + 1)
            sg = m.static_group(m.country(n.country), name, stype, pos, heading=0, dead=i >= alive)
            sg.units[0].name = name
            man.add(name, "supply_node", n.id, 1, represents=n.n_objects, dead=i >= alive, lat=n.lat, lon=n.lon)


def add_convoys(m, st: State, sel: Selection, man: Manifest) -> None:
    for rid in sel.routes:
        r = st.supply_routes[rid]
        src, dst = st.supply_nodes[r.src], st.supply_nodes[r.dst]
        frac = 0.35 + 0.3 * (1.0 - r.interdiction)          # interdicted convoys are still near the source
        lat, lon = geo.lerp((src.lat, src.lon), (dst.lat, dst.lon), min(0.6, frac))
        kinds = scaled_units(r.convoy_units, max(0.3, 1.0 - r.interdiction), cap=8)
        name = gname("cvy", r.id)
        heading = geo.bearing((lat, lon), (dst.lat, dst.lon))
        vg = _vehicle_group(m, m.country(src.country), name, kinds, terrain.to_point(m.terrain, lat, lon),
                            heading, 25.0)
        vg.points[0].action = PointAction.OnRoad
        vg.add_waypoint(terrain.to_point(m.terrain, dst.lat, dst.lon), PointAction.OnRoad, 45)
        vg.late_activation = f"supply_route:{rid}" in sel.late
        man.add(name, "supply_route", r.id, len(vg.units), represents=sum(r.convoy_units.values()),
                late=vg.late_activation, lat=lat, lon=lon)


def add_naval(m, st: State, sel: Selection, man: Manifest) -> Dict[str, Any]:
    """Returns {naval group id: pydcs ShipGroup} so carrier flights can be attached."""
    out: Dict[str, Any] = {}
    for nid in sel.naval_groups:
        n = st.naval_groups[nid]
        afloat = max(1, int(math.ceil(len(n.units) * n.health)))
        kinds = n.units[:afloat]
        name = gname("nav", n.id)
        pos = terrain.to_point(m.terrain, n.lat, n.lon)
        nxt = next((p for p in n.track if abs(p.lat - n.lat) + abs(p.lon - n.lon) > 0.01), None)
        heading = geo.bearing((n.lat, n.lon), (nxt.lat, nxt.lon)) if nxt else 0.0
        sg = m.ship_group(m.country(n.country), name, units.ship_type(kinds[0]), pos, heading=heading, group_size=1)
        sg.units[0].name = f"{name} #1"
        for i, kind in enumerate(kinds[1:], start=1):
            u = m.ship(f"{name} #{i + 1}", units.ship_type(kind))
            u.position = pos.point_from_heading(heading + 120 + 60 * (i % 2), 1800.0 * ((i + 1) // 2))
            u.heading = heading
            sg.add_unit(u)
        if nxt:
            sg.add_waypoint(terrain.to_point(m.terrain, nxt.lat, nxt.lon), 30 if n.role == "carrier" else 20)
        out[nid] = sg
        man.add(name, "naval_group", n.id, len(sg.units), represents=len(n.units), lat=n.lat, lon=n.lon,
                carrier_unit=sg.units[0].name if n.role == "carrier" else None)
    return out
