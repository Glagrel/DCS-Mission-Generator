"""ATO generation: allocate squadrons to the highest-scoring needs of each side."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .. import geo, models as M, units
from ..mission import loadouts
from ..models_ato import Ato, Flight, Package
from ..sim.readiness import readiness
from ..state import State
from . import route
from .needs import Need, air_strength, score_needs
from .radio import RadioPlan, callsign, clamp_to_aircraft, tacan_channel

log = logging.getLogger("sortie.ato")
MAX_PACKAGES_PER_SIDE = 14
DIMINISH = 7.0
FIRST_TOT_S, TOT_STEP_S = 2400.0, 420.0
STRIKE_LIKE = ("STRIKE", "DEAD", "INTERDICTION", "ANTISHIP", "CAS", "SEAD", "RECON")


class Pool:
    """Aircraft still unallocated this cycle, per squadron."""

    def __init__(self, st: State, side: str, d: Dict[str, Any]) -> None:
        self.st, self.left, self.flights = st, {}, {}
        for s in st.side("squadrons", side):
            self.left[s.id] = readiness(st, s, d)[0]
            self.flights[s.id] = 0

    def candidates(self, mission: str, target, size: int) -> List[M.Squadron]:
        out = []
        for sid, n in self.left.items():
            s = self.st.squadrons[sid]
            if n < min(size, 2 if size > 1 else 1) or mission not in s.tasks:
                continue
            base = self.st.airbases[s.airbase_id]
            dist = geo.dist_km((base.lat, base.lon), (target.lat, target.lon))
            if dist > units.combat_radius_km(s.aircraft):
                continue
            rating = units.air_rating(s.aircraft) if mission in ("CAP", "ESCORT", "SWEEP", "INTERCEPT") \
                else units.strike_rating(s.aircraft)
            # prefer capable airframes, close bases and squadrons that have flown least this cycle
            out.append((rating * 10 - dist / 100.0 - self.flights[sid] * 2 + (0.5 if s.is_player else 0), s))
        return [s for _, s in sorted(out, key=lambda x: (-x[0], x[1].id))]

    def take(self, s: M.Squadron, size: int) -> int:
        n = min(size, self.left[s.id])
        self.left[s.id] -= n
        self.flights[s.id] += 1
        return n


def _flight(st: State, pkg: Package, s: M.Squadron, n: int, task: str, radio: RadioPlan,
            seq: Dict[str, int]) -> Flight:
    side = s.coalition
    seq[s.id] = seq.get(s.id, 0) + 1
    home = st.airbases[s.airbase_id]
    doctrine = st.meta.doctrine.get(side, "nato")
    f = Flight(id=f"{pkg.id}-{len(pkg.flights) + 1}", squadron_id=s.id, coalition=side, aircraft=s.aircraft,
               count=n, task=task, callsign=callsign(s.callsign, seq[s.id], doctrine),
               freq=clamp_to_aircraft(pkg.freq, s.aircraft), loadout=loadouts.pick(s.aircraft, task))
    tot = pkg.tot_s - (90 if task in ("ESCORT", "SEAD") and pkg.mission != task else 0)
    f.waypoints = route.build_route(st, side, home, pkg.target, s.aircraft, task, tot)
    return f


def _target_under_sam(st: State, side: str, need: Need) -> bool:
    return any(s.coalition != side and s.role == "sam" and s.health > 0.3 and s.id != need.target.id
               and geo.dist_km((s.lat, s.lon), (need.target.lat, need.target.lon)) < s.range_km
               for s in st.sam_sites.values())


def plan_side(st: State, side: str, d: Dict[str, Any], turn: int) -> List[Package]:
    needs = score_needs(st, side, d)
    pool = Pool(st, side, d)
    radio = RadioPlan(st.meta.doctrine.get(side, "nato"), st.meta.era_kind, side)
    enemy_air = air_strength(st, M.enemy_of(side)) > 0
    packages: List[Package] = []
    seq: Dict[str, int] = {}
    remaining, per_mission = list(needs), {}
    while remaining and len(packages) < MAX_PACKAGES_PER_SIDE:
        # diminishing returns: each package already flying a mission type makes another
        # of the same type less attractive, so the ATO stays balanced
        need = max(remaining, key=lambda n: n.score - DIMINISH * per_mission.get(n.mission, 0))
        remaining.remove(need)
        cands = pool.candidates(need.mission, need.target, need.size)
        if not cands:
            continue
        n_pk = len(packages) + 1
        pkg = Package(id=f"{side[0].upper()}{turn}-{n_pk:02d}", coalition=side, mission=need.mission,
                      target=need.target, score=round(need.score, 1), reason=need.reason,
                      tot_s=FIRST_TOT_S + (n_pk - 1) * TOT_STEP_S, freq=radio.next())
        if need.mission in ("AWACS", "TANKER"):
            pkg.tot_s = 600.0                       # support is on station early
        lead = cands[0]
        pkg.flights.append(_flight(st, pkg, lead, pool.take(lead, need.size), need.mission, radio, seq))
        if need.mission in STRIKE_LIKE:
            if need.mission not in ("SEAD",) and st.has_cap(side, "SEAD") and _target_under_sam(st, side, need):
                sup = pool.candidates("SEAD", need.target, 2)
                if sup:
                    pkg.flights.append(_flight(st, pkg, sup[0], pool.take(sup[0], 2), "SEAD", radio, seq))
            if enemy_air and need.score >= 35:
                esc = pool.candidates("ESCORT", need.target, 2)
                if esc:
                    pkg.flights.append(_flight(st, pkg, esc[0], pool.take(esc[0], 2), "ESCORT", radio, seq))
        packages.append(pkg)
        per_mission[need.mission] = per_mission.get(need.mission, 0) + 1
    return packages


def support_info(st: State, packages: List[Package]) -> Dict[str, Any]:
    """Tanker/AWACS/GCI details per side for briefings."""
    info: Dict[str, Any] = {"blue": {}, "red": {}}
    for side in ("blue", "red"):
        tankers, awacs = [], []
        for p in (p for p in packages if p.coalition == side):
            for f in p.flights:
                entry = {"callsign": f.callsign, "freq": f.freq, "aircraft": f.aircraft,
                         "lat": p.target.lat, "lon": p.target.lon,
                         "alt_m": f.waypoints[1].alt_m if len(f.waypoints) > 1 else 0, "flight_id": f.id}
                if f.task == "TANKER":
                    entry["tacan"] = tacan_channel(len(tankers))
                    tankers.append(entry)
                elif f.task == "AWACS":
                    awacs.append(entry)
        gci = None
        if not awacs and st.has_cap(side, "GCI") and any(
                s.role == "ewr" and s.health > 0.3 for s in st.side("sam_sites", side)):
            gci = {"callsign": "GCI", "freq": RadioPlan(st.meta.doctrine.get(side, "nato"),
                                                        st.meta.era_kind, side).guard}
        info[side] = {"tankers": tankers, "awacs": awacs, "gci": gci}
    return info


def generate_ato(st: State, d: Dict[str, Any]) -> Ato:
    turn = st.meta.turn
    packages = plan_side(st, "blue", d, turn) + plan_side(st, "red", d, turn)
    ato = Ato(id=f"ato-{turn}", turn=turn, packages=packages, support=support_info(st, packages))
    log.info("ATO %s: %d packages", turn, len(packages), extra={"turn": turn})
    return ato


def threats_for(st: State, side: str, flight: Flight, ato: Optional[Ato] = None) -> Dict[str, Any]:
    """Threat summary along a flight's route for the briefing."""
    path = [(w.lat, w.lon) for w in flight.waypoints]
    sams = []
    for s in st.sam_sites.values():
        if s.coalition == side or s.role == "ewr" or s.health < 0.15 or not s.known:
            continue
        dkm = geo.point_path_km((s.lat, s.lon), path)
        if dkm < s.range_km + 20:
            sams.append({"id": s.id, "name": s.name, "type": s.template, "range_km": s.range_km,
                         "dist_km": round(dkm, 1), "lat": s.lat, "lon": s.lon, "inside": dkm < s.range_km})
    air = []
    for p in (ato.packages if ato else []):
        if p.coalition == side or p.mission not in ("CAP", "INTERCEPT", "SWEEP", "ESCORT"):
            continue
        if geo.point_path_km((p.target.lat, p.target.lon), path) < 150:
            air += [{"aircraft": f.aircraft, "count": f.count, "task": f.task, "near": p.target.name}
                    for f in p.flights]
    return {"sams": sorted(sams, key=lambda x: x["dist_km"]), "air": air}
