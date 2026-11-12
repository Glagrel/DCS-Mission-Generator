"""Flight groups for the mission: human slots (single player or co-op) and AI.

Nothing pops into existence mid-mission: a flight is either already airborne when the
mission starts (it took off before T0) or parked at its base and takes off on schedule.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from dcs import action, condition, task, triggers
from dcs.mission import StartType
from dcs.point import PointAction
from dcs.terrain.terrain import NoParkingSlotError
from dcs.unit import Skill

from .. import geo, navaids, terrain, units, weather
from ..models_ato import Ato, Flight, Package
from ..state import State
from . import clock, codes, loadouts, slots
from .budget import Selection, gname
from .forces import Manifest

log = logging.getLogger("sortie.mission")
SKILLS = {"Average": Skill.Average, "Good": Skill.Good, "High": Skill.High, "Excellent": Skill.Excellent}
RECOVERY_TANKER_ALT_M, RECOVERY_TANKER_SPEED_MS = 1829.0, 141.0     # 6,000 ft, 274 kt (MOOSE defaults)
PLANE_GUARD_ALT_M, PLANE_GUARD_OFFSET_M = 90.0, 1852.0              # 300 ft, 1 nm to starboard


def main_task(aircraft: str, sortie_task: str):
    """First pydcs MainTask for the SORTIE task that the airframe supports (else its default)."""
    t = units.aircraft_type(aircraft)
    for cls in loadouts.TASK_CLASSES.get(sortie_task, []):
        if cls in t.tasks:
            return cls
    return t.task_default or (t.tasks[0] if t.tasks else task.Nothing)


class FlightBuilder:
    def __init__(self, m, st: State, ato: Ato, sel: Selection, man: Manifest, ships: Dict[str, Any],
                 seats: Dict[str, List[int]], multiplayer: bool, skills: Dict[str, str], warnings: List[str],
                 t0: float, d: Dict[str, Any], hot: bool = False) -> None:
        self.m, self.st, self.ato, self.sel, self.man = m, st, ato, sel, man
        self.ships, self.seats, self.multiplayer = ships, seats, multiplayer
        self.skills, self.warnings, self.t0, self.d, self.hot = skills, warnings, t0, d, hot
        self.groups: Dict[str, Any] = {}          # flight id -> pydcs group
        self.carrier_support: List[Dict[str, Any]] = []
        self.parked: Dict[str, List[Any]] = {}    # base id -> [(take-off time, group)] for stand re-use
        self.stn: Dict[str, str] = {}             # flight id -> lead's Link 16 / SADL track number
        self.weapon_notes: Dict[str, List[str]] = {}   # flight id -> weather weapon swaps
        from datetime import timedelta
        import random
        self.wx = weather.at(weather.normalize(dict(st.meta.weather), random.Random("wx")),
                             st.now + timedelta(seconds=t0)) if st.meta.weather else {}

    # -- public --------------------------------------------------------------------------
    def build_all(self) -> None:
        for fid in self.sel.flights:
            pkg, f = self.ato.find_flight(fid)
            self.groups[fid] = self._build(pkg, f)
        for fid in self.sel.flights:              # second pass: tasks that reference other groups
            pkg, f = self.ato.find_flight(fid)
            if not f.is_player:
                self._tasks(pkg, f, self.groups[fid])
        try:
            self.stn = codes.setup_datalinks(self.ato, self.groups)
        except Exception as exc:                  # never let datalinks stop a mission build
            log.warning("datalink set-up failed: %s", exc)
            self.warnings.append(f"Datalinks were not set up: {exc}")

    def _carrier_of(self, pkg: Package):
        """Ship group when the package target is a carrier that is in the mission."""
        if pkg.target.kind != "airbase":
            return None
        base = self.st.airbases.get(pkg.target.id)
        return self.ships.get(base.naval_group) if base and base.kind == "carrier" else None

    # -- creation ------------------------------------------------------------------------
    def _build(self, pkg: Package, f: Flight):
        m, st, t0 = self.m, self.st, self.t0
        sq = st.squadrons[f.squadron_id]
        base = st.airbases[sq.airbase_id]
        actype = units.aircraft_type(f.aircraft)
        country = m.country(sq.country)
        mt = main_task(f.aircraft, f.task)
        name = gname("flt", f.id)
        humans = self.seats.get(f.id, [])
        ph = clock.GROUND if (f.is_player or humans) else clock.phase(f, t0)
        group, first, delay = None, 1, 0.0
        boat = self._carrier_of(pkg)
        if ph == clock.GROUND:
            start = StartType.Cold if (humans and not self.hot) else StartType.Warm
            delay = 0.0 if humans else clock.start_delay(f, t0, self.d)

            def make(how=None):
                how = how or start
                if base.kind == "carrier" and base.naval_group in self.ships:
                    return m.flight_group_from_unit(country, name, actype, self.ships[base.naval_group],
                                                    maintask=mt, start_type=how, group_size=f.count)
                if base.dcs_name:
                    return m.flight_group_from_airport(country, name, actype, m.terrain.airports[base.dcs_name],
                                                       maintask=mt, start_type=how, group_size=f.count)
                return None

            reused = False
            try:
                group = make()
            except (NoParkingSlotError, RuntimeError, IndexError) as exc:
                # ramp is full: take over the stands of a flight that has left before we start up
                if self._free_stands(base.id, delay):
                    try:
                        group, reused = make(), True
                    except (NoParkingSlotError, RuntimeError, IndexError):
                        group = None
                if group is None and not humans:
                    # still no stand: line up on the runway at take-off time and go
                    try:
                        group, reused = make(StartType.Runway), True
                        delay = clock.rel(f.waypoints[0].eta_s, t0)
                    except Exception:
                        group = None
                if group is None:
                    self.warnings.append(f"{f.callsign}: no free parking at {base.name}; this flight enters "
                                         f"airborne over its base at take-off time ({exc})")
            if group is not None:
                self.parked.setdefault(base.id, []).append((clock.rel(f.waypoints[0].eta_s, t0), group))
                if reused:
                    self._activate_at(group, delay)        # appears on its stand once the stand is free
                elif delay > 30:
                    self._start_at(group, delay)           # parked and cold until its own start-up time
        if group is None:
            if ph == clock.GROUND:                         # parking fallback: appear over the base on time
                pos, alt, spd = (base.lat, base.lon), 1500.0, f.waypoints[1].speed_kmh or 500.0
                state = None
            else:
                state = clock.air_state(f, t0)
                pos, alt, spd, first = (state.lat, state.lon), state.alt_m, state.speed_kmh, state.next_index
                if boat is not None and f.task in ("SAR", "TANKER"):
                    pos, alt = self._station_by_boat(boat, f.task)
            group = m.flight_group_inflight(country, name, actype, terrain.to_point(m.terrain, *pos),
                                            int(max(alt, 60)), int(spd or 500), maintask=mt, group_size=f.count)
            if ph == clock.GROUND:
                group.start_time = int(clock.rel(f.waypoints[0].eta_s, t0))
            elif state is not None and state.on_station:
                group.points[0].sortie_action = "orbit"
                group.points[0].sortie_hold = state.hold_s
        self._crew(f, sq, group, humans)
        self._payload(f, group)
        if self.st.meta.era_kind != "ww2":
            codes.set_laser(group, codes.laser(self.ato, f))
        group.set_frequency(f.freq)
        for wp in f.waypoints[first:-1]:
            mp = group.add_waypoint(terrain.to_point(m.terrain, wp.lat, wp.lon), int(max(wp.alt_m, 60)),
                                    int(wp.speed_kmh or 500), wp.name)
            mp.ETA = int(clock.rel(wp.eta_s, t0))
            mp.sortie_action, mp.sortie_hold = wp.action, wp.hold_s
        self._land(group, base)
        f.callsign = self._dcs_callsign(group) or f.callsign
        airborne = group.points[0].type == "Turning Point"
        self.man.add(name, "flight", f.id, len(group.units), player=f.is_player, task=f.task,
                     squadron=sq.id, coalition=f.coalition, aircraft=f.aircraft, callsign=f.callsign,
                     airborne_start=airborne, phase=ph, start_delay_s=round(delay),
                     shared_stand=bool(getattr(group, "late_activation", False)),
                     end_s=clock.rel(f.waypoints[-1].eta_s, t0),
                     clients=[group.units[i].name for i in humans], base=base.id)
        return group

    def _free_stands(self, base_id: str, start_s: float) -> bool:
        """Release the parking of groups that take off at least 5 minutes before `start_s`."""
        freed = False
        for dep, og in self.parked.get(base_id, []):
            if dep + 300 < start_s and not getattr(og, "sortie_freed", False):
                try:
                    freed = bool(self.m.clear_parking_slots(og)) or freed
                    og.sortie_freed = True
                except Exception as exc:
                    log.debug("could not free stands of %s: %s", og.name, exc)
        return freed

    def _start_at(self, group, seconds: float) -> None:
        """Uncontrolled (parked, engines off) until a one-shot trigger pushes the Start command."""
        group.add_trigger_action(task.StartCommand())
        group.uncontrolled = True
        trig = triggers.TriggerOnce(comment=f"{group.name} start-up")
        trig.add_condition(condition.TimeAfter(int(seconds)))
        trig.add_action(action.AITaskPush(group.id, len(group.tasks)))
        self.m.triggerrules.triggers.append(trig)

    def _activate_at(self, group, seconds: float) -> None:
        """Late-activated on its stand at `seconds` (used when a stand is shared in sequence)."""
        group.late_activation = True
        trig = triggers.TriggerOnce(comment=f"{group.name} activate")
        trig.add_condition(condition.TimeAfter(int(max(1, seconds))))
        trig.add_action(action.ActivateGroup(group.id))
        self.m.triggerrules.triggers.append(trig)

    def _station_by_boat(self, boat, sortie_task: str):
        lat, lon = terrain.to_latlon(boat.position)
        hdg = boat.units[0].heading
        if sortie_task == "SAR":                           # plane guard: close aboard, starboard side
            lat, lon = geo.destination((lat, lon), hdg + 90, PLANE_GUARD_OFFSET_M / 1000.0)
            return (lat, lon), PLANE_GUARD_ALT_M
        lat, lon = geo.destination((lat, lon), hdg + 180, 5.0)   # recovery tanker: overhead, astern
        return (lat, lon), RECOVERY_TANKER_ALT_M

    def _crew(self, f: Flight, sq, group, humans: List[int]) -> None:
        skill = SKILLS.get(self.skills["friendly" if f.coalition == self.st.meta.player_side else "enemy"],
                           SKILLS.get(sq.skill, Skill.Good))
        for u in group.units:
            u.skill = skill
        for i in humans:
            if self.multiplayer:
                group.units[i].set_client()         # co-op: every human seat is a Client slot
            else:
                group.units[i].set_player()         # single player: the one "Player" slot

    def _payload(self, f: Flight, group) -> None:
        # choose again at build time: payload files or the selection rules may have changed
        # since the ATO was planned
        f.loadout = loadouts.pick(f.aircraft, f.task) or f.loadout
        pyl = loadouts.pylons(f.aircraft, f.loadout)
        if not pyl:
            if self.seats.get(f.id):
                self.warnings.append(f"No stock loadout found for {f.aircraft}/{f.task}: aircraft spawn clean; "
                                     "re-arm on the ramp.")
            return
        if self.wx:
            pyl, notes, keep, dead = weather.adapt(units.aircraft_type(f.aircraft), list(pyl), self.wx)
            if notes:
                self.weapon_notes[f.id] = notes
                if f.is_player or self.seats.get(f.id):
                    self.warnings.append(f"{f.callsign}: weather swap {', '.join(notes)} "
                                         f"({weather.describe(self.wx)})")
            need = weather.NEEDS.get(f.task)
            if need and dead and not (keep & need) and (f.is_player or self.seats.get(f.id)):
                self.warnings.append(f"{f.callsign}: the weather rules out your {'/'.join(sorted(dead)).lower()} "
                                     f"weapons and no GPS weapon fits ({weather.describe(self.wx)}).")
        for u in group.units:
            u.pylons.clear()                    # pydcs pre-fills a default loadout: start clean
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

    def _orbit(self, p, pattern=None) -> None:
        orbit = task.OrbitAction(int(p.alt), int(p.speed * 3.6), pattern or task.OrbitAction.OrbitPattern.RaceTrack)
        hold = float(getattr(p, "sortie_hold", 0.0) or 0.0)
        if hold > 0:
            ctl = task.ControlledTask(orbit)
            ctl.stop_after_duration(int(hold))     # then continue the route and land
            p.tasks.append(ctl)
        else:
            p.tasks.append(orbit)

    def _tanker_beacon(self, f: Flight, group) -> None:
        """Air-to-air TACAN for a tanker, on the channel the briefing lists."""
        entry = next((t for t in self.ato.support.get(f.coalition, {}).get("tankers", [])
                      if t.get("flight_id") == f.id), None)
        chan, band = navaids.tanker_channel((entry or {}).get("tacan"))
        if chan is None:
            return
        ident = "".join(c for c in f.callsign.upper() if c.isalpha())[:3] or "TKR"
        group.points[0].tasks.append(task.ActivateBeaconCommand(chan, band, ident, unit_id=group.units[0].id,
                                                                aa=True))
        self.man[group.name]["tacan"] = f"{chan}{band} {ident}"

    def _tasks(self, pkg: Package, f: Flight, group) -> None:
        if f.task not in ("TANKER", "AWACS", "SAR", "TRANSPORT"):
            group.points[0].tasks.append(task.OptRTBOnBingoFuel(True))      # AI goes home on bingo
        if f.task in ("SEAD", "DEAD"):
            # hold fire until the IP so the SEAD flight does not chase fighters into SAM cover
            group.points[0].tasks.append(task.OptROE(task.OptROE.Values.ReturnFire))
        if f.task == "TANKER":
            self._tanker_beacon(f, group)
        tgt = terrain.to_point(self.m.terrain, pkg.target.lat, pkg.target.lon)
        marks = {getattr(p, "sortie_action", ""): p for p in group.points}
        boat = self._carrier_of(pkg)
        if boat is not None and f.task == "TANKER":
            group.points[0].tasks.append(task.RecoveryTanker(boat.id, RECOVERY_TANKER_SPEED_MS,
                                                             RECOVERY_TANKER_ALT_M, None))
            self.man[group.name]["role"] = "recovery_tanker"
        elif boat is not None and f.task == "SAR":
            # MOOSE's RESCUEHELO keeps station on the moving ship (wired in sortie_carrier.lua);
            # without MOOSE the helicopter flies this racetrack beside the ship's starting position
            if "orbit" in marks:
                self._orbit(marks["orbit"], task.OrbitAction.OrbitPattern.Circle)
            self.man[group.name]["role"] = "plane_guard"
            self.carrier_support.append({"role": "plane_guard", "group": group.name,
                                         "carrier_unit": boat.units[0].name})
        elif f.task in ("CAP", "INTERCEPT", "AWACS", "TANKER", "SAR") and "orbit" in marks:
            self._orbit(marks["orbit"])
        elif f.task == "ESCORT":
            lead = self.groups.get(pkg.flights[0].id)
            if lead is not None and lead is not group:
                # replace pydcs's generic auto-escort with one bound to our package lead
                group.points[0].tasks = [t for t in group.points[0].tasks
                                         if not isinstance(t, task.EscortTaskAction)]
                # escorts pick the package up at the JOIN point when there is one
                (marks.get("join") or group.points[0]).tasks.append(task.EscortTaskAction(
                    group_id=lead.id, engagement_max_dist=60000, lastwpt=max(2, len(lead.points) - 1),
                    targets=[task.Targets.All.Air.Planes.Fighters, task.Targets.All.Air.Planes.MultiroleFighters],
                    position={"x": -300, "y": 600, "z": -300}))
        elif f.task in ("SEAD", "DEAD", "CAS", "INTERDICTION", "ANTISHIP", "STRIKE"):
            at = marks.get("ip") or group.points[-2]
            if f.task in ("SEAD", "DEAD"):
                at.tasks.append(task.OptROE(task.OptROE.Values.OpenFire))
            ids = self._target_groups(pkg)
            if ids:
                for gid in ids[:3]:
                    at.tasks.append(task.AttackGroup(gid, group_attack=True))
            elif pkg.target.kind == "airbase" and self.st.airbases[pkg.target.id].dcs_name:
                ap = self.m.terrain.airports[self.st.airbases[pkg.target.id].dcs_name]
                at.tasks.append(task.BombingRunway(ap.id, group_attack=True))
            else:
                at.tasks.append(task.Bombing(tgt, attack_qty=2, group_attack=True))
