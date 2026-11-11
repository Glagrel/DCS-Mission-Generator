"""Flight groups for the mission: the player's flight (SP or co-op client slots) and AI."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from dcs import task
from dcs.mission import StartType
from dcs.terrain.terrain import NoParkingSlotError
from dcs.unit import Skill

from .. import terrain, units
from ..models_ato import Ato, Flight, Package
from ..state import State
from . import loadouts
from .budget import Selection, gname
from .forces import Manifest

log = logging.getLogger("sortie.mission")
SKILLS = {"Average": Skill.Average, "Good": Skill.Good, "High": Skill.High, "Excellent": Skill.Excellent}


def main_task(aircraft: str, sortie_task: str):
    """First pydcs MainTask for the SORTIE task that the airframe supports (else its default)."""
    t = units.aircraft_type(aircraft)
    for cls in loadouts.TASK_CLASSES.get(sortie_task, []):
        if cls in t.tasks:
            return cls
    return t.task_default or (t.tasks[0] if t.tasks else task.Nothing)


class FlightBuilder:
    def __init__(self, m, st: State, ato: Ato, sel: Selection, man: Manifest, ships: Dict[str, Any],
                 coop_slots: int, skills: Dict[str, str], warnings: List[str]) -> None:
        self.m, self.st, self.ato, self.sel, self.man = m, st, ato, sel, man
        self.ships, self.coop_slots, self.skills, self.warnings = ships, max(1, coop_slots), skills, warnings
        self.groups: Dict[str, Any] = {}          # flight id -> pydcs group

    # -- public --------------------------------------------------------------------------
    def build_all(self) -> None:
        player_pkg, _ = self.ato.find_flight(self.ato.player_flight_id)
        for fid in self.sel.flights:
            pkg, f = self.ato.find_flight(fid)
            on_ground = pkg.id == player_pkg.id or f.is_player
            self.groups[fid] = self._build(pkg, f, on_ground)
        for fid in self.sel.flights:              # second pass: tasks that reference other groups
            pkg, f = self.ato.find_flight(fid)
            if not f.is_player:
                self._tasks(pkg, f, self.groups[fid])

    # -- creation ------------------------------------------------------------------------
    def _build(self, pkg: Package, f: Flight, on_ground: bool):
        m, st = self.m, self.st
        sq = st.squadrons[f.squadron_id]
        base = st.airbases[sq.airbase_id]
        actype = units.aircraft_type(f.aircraft)
        country = m.country(sq.country)
        mt = main_task(f.aircraft, f.task)
        name = gname("flt", f.id)
        start = StartType.Cold if f.is_player else StartType.Warm
        group = None
        if on_ground:
            try:
                if base.kind == "carrier" and base.naval_group in self.ships:
                    group = m.flight_group_from_unit(country, name, actype, self.ships[base.naval_group],
                                                     maintask=mt, start_type=start, group_size=f.count)
                elif base.dcs_name:
                    group = m.flight_group_from_airport(country, name, actype, m.terrain.airports[base.dcs_name],
                                                        maintask=mt, start_type=start, group_size=f.count)
            except (NoParkingSlotError, RuntimeError, IndexError) as exc:
                self.warnings.append(f"{f.callsign}: no parking at {base.name} ({exc}); starting airborne")
                group = None
        if group is None:
            wp = f.waypoints[1] if len(f.waypoints) > 1 else f.waypoints[0]
            origin = (base.lat, base.lon) if on_ground else (wp.lat, wp.lon)
            alt = max(600.0, wp.alt_m if not on_ground else min(wp.alt_m, 2500.0))
            group = m.flight_group_inflight(country, name, actype, terrain.to_point(m.terrain, *origin),
                                            int(alt), int(wp.speed_kmh or 500), maintask=mt, group_size=f.count)
            if not on_ground:
                group.start_time = int(max(0.0, (wp.eta_s or 0.0) - 60.0))
        self._crew(f, sq, group)
        self._payload(f, group)
        group.set_frequency(f.freq)
        first = 1 if on_ground else 2          # airborne flights spawn at their second waypoint
        if not on_ground and len(f.waypoints) > 1:
            group.points[0].sortie_action = f.waypoints[1].action
        for wp in f.waypoints[first:-1]:
            mp = group.add_waypoint(terrain.to_point(m.terrain, wp.lat, wp.lon), int(max(wp.alt_m, 100)),
                                    int(wp.speed_kmh or 500), wp.name)
            mp.sortie_action = wp.action        # private marker used by _tasks
        self._land(group, base)
        f.callsign = self._dcs_callsign(group) or f.callsign
        self.man.add(name, "flight", f.id, len(group.units), player=f.is_player, task=f.task,
                     squadron=sq.id, coalition=f.coalition, aircraft=f.aircraft, callsign=f.callsign,
                     airborne_start=group.points[0].type == "Turning Point",
                     end_s=f.waypoints[-1].eta_s or 0.0)
        return group

    def _crew(self, f: Flight, sq, group) -> None:
        skill = SKILLS.get(self.skills["friendly" if f.coalition == self.st.meta.player_side else "enemy"],
                           SKILLS.get(sq.skill, Skill.Good))
        for u in group.units:
            u.skill = skill
        if not f.is_player:
            return
        if self.coop_slots <= 1:
            group.units[0].set_player()             # single player: one "Player" slot, AI wingmen
        else:
            for u in group.units[: self.coop_slots]:
                u.set_client()                      # co-op: multi-client slots, remaining seats AI

    def _payload(self, f: Flight, group) -> None:
        if not f.loadout:                       # ATO was planned before payloads were known
            f.loadout = loadouts.pick(f.aircraft, f.task)
        pyl = loadouts.pylons(f.aircraft, f.loadout)
        if not pyl:
            if f.is_player:
                self.warnings.append(f"No stock loadout found for {f.aircraft}/{f.task}: aircraft spawn clean; "
                                     "re-arm on the ramp.")
            return
        for u in group.units:
            for p in pyl:
                try:
                    u.load_pylon(p)
                except Exception as exc:
                    log.debug("pylon %s rejected on %s: %s", p, f.aircraft, exc)

    def _land(self, group, base) -> None:
        if base.kind == "carrier" and base.naval_group in self.ships:
            ship = self.ships[base.naval_group]
            mp = group.add_waypoint(ship.position, 600, 400, "RTB")
            mp.type, mp.link_unit, mp.helipad_id = "Land", ship.units[0].id, ship.units[0].id
            from dcs.point import PointAction
            mp.action = PointAction.Landing
        elif base.dcs_name:
            group.land_at(self.m.terrain.airports[base.dcs_name])

    @staticmethod
    def _dcs_callsign(group) -> Optional[str]:
        u = group.units[0]
        try:
            if u.callsign_is_western():
                raw = u.callsign_dict.get("name", "")
                return f"{raw[:-2]} {raw[-2]}-{raw[-1]}" if len(raw) > 2 else None
            return str(u.callsign) if u.callsign else None
        except Exception:
            return None

    # -- AI tasking -----------------------------------------------------------------------
    def _target_groups(self, pkg: Package) -> List[int]:
        kind_map = {"sam_site": "sam", "ground_unit": "gnd", "naval_group": "nav", "supply_route": "cvy"}
        ids = []
        want = [(pkg.target.kind, pkg.target.id)]
        if pkg.target.kind == "front":            # CAS: the enemy formations on that front
            want = [("ground_unit", g.id) for g in self.st.ground_units.values()
                    if g.front_id == pkg.target.id and g.coalition != pkg.coalition]
        for kind, eid in want:
            g = self.m.find_group(gname(kind_map.get(kind, "x"), eid))
            if g is not None:
                ids.append(g.id)
        return ids

    def _tasks(self, pkg: Package, f: Flight, group) -> None:
        tgt = terrain.to_point(self.m.terrain, pkg.target.lat, pkg.target.lon)
        marks = {getattr(p, "sortie_action", ""): p for p in group.points}
        if f.task in ("CAP", "INTERCEPT", "AWACS", "TANKER") and "orbit" in marks:
            p = marks["orbit"]
            p.tasks.append(task.OrbitAction(int(p.alt), int(p.speed * 3.6), task.OrbitAction.OrbitPattern.RaceTrack))
        elif f.task == "ESCORT":
            lead = self.groups.get(pkg.flights[0].id)
            if lead is not None and lead is not group:
                # replace pydcs's generic auto-escort with one bound to our package lead
                group.points[0].tasks = [t for t in group.points[0].tasks
                                         if not isinstance(t, task.EscortTaskAction)]
                group.points[0].tasks.append(task.EscortTaskAction(
                    group_id=lead.id, engagement_max_dist=60000, lastwpt=max(2, len(lead.points) - 1),
                    targets=[task.Targets.All.Air.Planes.Fighters, task.Targets.All.Air.Planes.MultiroleFighters],
                    position={"x": -300, "y": 600, "z": -300}))
        elif f.task in ("SEAD", "DEAD", "CAS", "INTERDICTION", "ANTISHIP", "STRIKE"):
            at = marks.get("ip") or group.points[-2]
            ids = self._target_groups(pkg)
            if ids:
                for gid in ids[:3]:
                    at.tasks.append(task.AttackGroup(gid, group_attack=True))
            elif pkg.target.kind == "airbase" and self.st.airbases[pkg.target.id].dcs_name:
                ap = self.m.terrain.airports[self.st.airbases[pkg.target.id].dcs_name]
                at.tasks.append(task.BombingRunway(ap.id, group_attack=True))
            else:
                at.tasks.append(task.Bombing(tgt, attack_qty=2, group_attack=True))
