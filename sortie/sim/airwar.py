"""Abstract (probabilistic) resolution of ATO flights that are not flown in DCS."""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Set

from .. import geo, models as M, units
from ..models_ato import A2A, Ato, Flight, FlightResult, Package
from ..state import State
from .readiness import charge_sortie

SKILL = {"Average": 0.8, "Good": 1.0, "High": 1.15, "Excellent": 1.3}
PILOT_LOSS_SHARE = 0.6
STRIKERS = ("STRIKE", "CAS", "INTERDICTION", "ANTISHIP", "SEAD", "DEAD")


def _strength(st: State, flights: Iterable[Flight], air: bool) -> float:
    total = 0.0
    for f in flights:
        sq = st.squadrons.get(f.squadron_id)
        rating = units.air_rating(f.aircraft) if air else units.strike_rating(f.aircraft)
        total += f.count * rating * SKILL.get(sq.skill if sq else "Good", 1.0)
    return total


def _path(f: Flight, pkg: Package) -> List[geo.Pt]:
    pts = [(w.lat, w.lon) for w in f.waypoints]
    return pts or [(pkg.target.lat, pkg.target.lon)]


def sam_threat(st: State, side: str, path: List[geo.Pt]) -> float:
    """Sum of enemy SAM/AAA engagement weight along a path (0 = clean)."""
    threat = 0.0
    for s in st.sam_sites.values():
        if s.coalition == side or s.role == "ewr" or s.health < 0.15:
            continue
        if geo.point_path_km((s.lat, s.lon), path) <= s.range_km:
            threat += s.health * (1.0 if s.role == "sam" else 0.5)
    return threat


def _take_losses(st: State, f: Flight, res: FlightResult, n: int, rng) -> None:
    n = max(0, min(n, f.count - res.lost))
    if n == 0:
        return
    sq = st.squadrons.get(f.squadron_id)
    res.lost += n
    pilots = sum(1 for _ in range(n) if rng.random() < PILOT_LOSS_SHARE)
    res.pilots_lost += pilots
    if sq:
        sq.airframes = max(0, sq.airframes - n)
        sq.pilots = max(0, sq.pilots - pilots)
        sq.losses += n


def _binom(rng, n: int, p: float) -> int:
    p = max(0.0, min(1.0, p))
    return sum(1 for _ in range(n) if rng.random() < p)


def resolve_package(st: State, ato: Ato, pkg: Package, d: Dict[str, Any], rng,
                    skip: Set[str]) -> List[FlightResult]:
    """Resolve all flights of a package except those in `skip` (flown in DCS)."""
    flights = [f for f in pkg.flights if f.id not in skip and f.status == "planned"]
    if not flights:
        return []
    bias = d["difficulty"][st.meta.difficulty]["loss_bias"]
    results = {f.id: FlightResult(flight_id=f.id) for f in flights}
    side, enemy = pkg.coalition, M.enemy_of(pkg.coalition)
    tgt = (pkg.target.lat, pkg.target.lon)
    for f in flights:
        sq = st.squadrons.get(f.squadron_id)
        if sq:
            charge_sortie(st, sq, f.count, f.task, d)
    # --- air opposition: enemy CAP/intercept packages stationed near the target ----------
    opp = [f for p in ato.packages if p.coalition == enemy and p.mission in ("CAP", "INTERCEPT", "SWEEP")
           and geo.dist_km((p.target.lat, p.target.lon), tgt) < 120 for f in p.flights if f.status != "cancelled"]
    fighters = [f for f in flights if f.task in A2A or f.task == "INTERCEPT"]
    others = [f for f in flights if f not in fighters]
    if opp and pkg.mission not in ("TANKER", "AWACS"):
        mine = _strength(st, fighters, True) + 0.3 * _strength(st, others, True)
        theirs = _strength(st, opp, True) * (0.5 if pkg.mission in ("CAP", "INTERCEPT") else 0.7)
        edge = mine / (mine + theirs) if mine + theirs > 0 else 0.5
        loss_bias = bias if side == st.meta.player_side else 1.0 / bias
        for f in flights:
            exposed = 0.10 if f in fighters else (0.07 if fighters else 0.16)
            _take_losses(st, f, results[f.id], _binom(rng, f.count, exposed * (1 - edge) * 2 * loss_bias), rng)
        kills = _binom(rng, sum(f.count for f in fighters) or 1, 0.12 * edge * 2)
        for f in fighters[:1]:
            results[f.id].kills_air += kills
        _spread_enemy_air_losses(st, opp, kills, rng)
    # --- ground-based air defence ----------------------------------------------------------
    sead = any(f.task in ("SEAD", "DEAD") for f in pkg.flights)
    for f in flights:
        if pkg.mission in ("CAP", "INTERCEPT", "TANKER", "AWACS", "TRANSPORT"):
            continue
        threat = sam_threat(st, side, _path(f, pkg))
        if threat > 0:
            p = min(0.25, 0.035 * threat) * (0.5 if sead else 1.0)
            _take_losses(st, f, results[f.id], _binom(rng, f.count, p), rng)
    # --- effect on target ----------------------------------------------------------------------
    for f in flights:
        res = results[f.id]
        alive = f.count - res.lost
        if f.task in STRIKERS and alive > 0:
            power = alive * units.strike_rating(f.aircraft) * rng.uniform(0.5, 1.2)
            res.success = min(1.0, apply_strike(st, pkg, f, power, res, rng))
        elif f.task in ("CAP", "ESCORT", "SWEEP", "INTERCEPT"):
            res.success = 1.0 if alive == f.count else alive / f.count
        else:
            res.success = 1.0 if alive > 0 else 0.0
        f.status = "resolved"
        f.result = res.model_dump()
        sq = st.squadrons.get(f.squadron_id)
        if sq:
            sq.kills += res.kills_air
    return list(results.values())


def _spread_enemy_air_losses(st: State, opp: List[Flight], kills: int, rng) -> None:
    for _ in range(kills):
        live = [f for f in opp if st.squadrons.get(f.squadron_id) and st.squadrons[f.squadron_id].airframes > 0]
        if not live:
            return
        sq = st.squadrons[rng.choice(live).squadron_id]
        sq.airframes -= 1
        sq.losses += 1
        if rng.random() < PILOT_LOSS_SHARE:
            sq.pilots = max(0, sq.pilots - 1)


def apply_strike(st: State, pkg: Package, f: Flight, power: float, res: FlightResult, rng) -> float:
    """Apply abstract damage to the package target. Returns success 0..1."""
    t = pkg.target
    side = pkg.coalition
    if t.kind == "sam_site" and t.id in st.sam_sites:
        s = st.sam_sites[t.id]
        dmg = min(s.health, 0.09 * power)
        s.health = round(s.health - dmg, 3)
        res.kills_ground += int(round(dmg * 6))
        return dmg / 0.35
    if t.kind == "supply_node" and t.id in st.supply_nodes:
        n = st.supply_nodes[t.id]
        dmg = min(n.health, 0.06 * power)
        n.health = round(n.health - dmg, 3)
        n.stock *= 1 - dmg * 0.5
        res.kills_structure += int(round(dmg * n.n_objects))
        return dmg / 0.3
    if t.kind == "supply_route" and t.id in st.supply_routes:
        r = st.supply_routes[t.id]
        add = min(1.0 - r.interdiction, 0.07 * power)
        r.interdiction = round(r.interdiction + add, 3)
        res.kills_ground += int(round(add * 8))
        return add / 0.3
    if t.kind == "airbase" and t.id in st.airbases:
        b = st.airbases[t.id]
        dmg = min(b.runway_health, 0.05 * power)
        b.runway_health = round(b.runway_health - dmg, 3)
        b.hit_last_turn = True
        for sq in st.squadrons.values():        # aircraft caught on the ground
            if sq.airbase_id == b.id and sq.airframes > 0 and rng.random() < 0.15 * power / 4:
                sq.airframes -= 1
                sq.losses += 1
                res.kills_ground += 1
        return dmg / 0.3
    if t.kind == "front" and t.id in st.fronts:
        fr = st.fronts[t.id]
        eff = 0.04 * power
        fr.cas_effect[side] = round(fr.cas_effect.get(side, 0.0) + eff, 3)
        enemy_units = [g for g in st.ground_units.values() if g.front_id == fr.id and g.coalition != side]
        for g in enemy_units:
            g.strength = max(0.05, round(g.strength - eff / max(1, len(enemy_units)), 3))
        res.kills_ground += int(round(eff * 20))
        return eff / 0.2
    if t.kind == "naval_group" and t.id in st.naval_groups:
        n = st.naval_groups[t.id]
        dmg = min(n.health, 0.06 * power)
        n.health = round(n.health - dmg, 3)
        res.kills_naval += int(round(dmg * len(n.units)))
        return dmg / 0.3
    return 0.0


def resolve_ato(st: State, ato: Optional[Ato], d: Dict[str, Any],
                skip_flights: Iterable[str] = ()) -> Dict[str, Any]:
    """Resolve every still-planned flight. Returns a per-side summary."""
    summary: Dict[str, Any] = {s: {"sorties": 0, "lost": 0, "kills_air": 0, "kills_ground": 0,
                                   "kills_structure": 0, "kills_naval": 0} for s in ("blue", "red")}
    if ato is None:
        return summary
    skip = set(skip_flights)
    rng = st.rng("airwar")
    for pkg in sorted(ato.packages, key=lambda p: (p.tot_s, p.id)):
        counts = {f.id: f.count for f in pkg.flights}
        for res in resolve_package(st, ato, pkg, d, rng, skip):
            s = summary[pkg.coalition]
            s["sorties"] += counts[res.flight_id]
            s["lost"] += res.lost
            for k in ("kills_air", "kills_ground", "kills_structure", "kills_naval"):
                s[k] += getattr(res, k)
    return summary
