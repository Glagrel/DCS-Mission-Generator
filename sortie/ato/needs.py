"""Transparent scoring of what each side's air force should do this cycle.

Every Need carries a `reason` string so the player can see why the ATO tasked them.
"""
from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel

from .. import geo, models as M, units
from ..models_ato import Target
from ..state import State
from ..sim.ground import side_strength


class Need(BaseModel):
    mission: str
    target: Target
    score: float
    reason: str
    size: int = 4


def air_strength(st: State, side: str) -> float:
    return sum(s.available * units.air_rating(s.aircraft) for s in st.side("squadrons", side)
               if "CAP" in units.capable_missions(s.aircraft))


def air_superiority(st: State, side: str) -> float:
    """0..1 share of fighter strength held by `side` (0.5 = parity)."""
    mine, theirs = air_strength(st, side), air_strength(st, M.enemy_of(side))
    return mine / (mine + theirs) if mine + theirs > 0 else 0.5


def front_points(st: State, f: M.Front, side: str, back_km: float = 0.0) -> geo.Pt:
    """Centre of the front line, optionally pulled `back_km` into `side`'s own territory."""
    a, b = (f.a.lat, f.a.lon), (f.b.lat, f.b.lon)
    c = geo.lerp(a, b, f.position)
    if back_km:
        home = a if side == "blue" else b
        c = geo.destination(c, geo.bearing(c, home), back_km)
    return c


def _front_target(st: State, f: M.Front, side: str, back_km: float = 0.0, suffix: str = "") -> Target:
    lat, lon = front_points(st, f, side, back_km)
    return Target(kind="front", id=f.id, name=f.name + suffix, lat=lat, lon=lon)


def _pressure_on(side: str, f: M.Front) -> float:
    """Positive when the enemy is pushing `side` back on this front."""
    return -f.pressure if side == "blue" else f.pressure


def score_needs(st: State, side: str, d: Dict[str, Any]) -> List[Need]:
    enemy = M.enemy_of(side)
    needs: List[Need] = []
    sup = air_superiority(st, side)
    lost_air = max(0.0, 0.5 - sup) * 2            # 0 at parity .. 1 when we have nothing
    fronts = list(st.fronts.values())
    my_points = [front_points(st, f, side) for f in fronts] + \
                [(b.lat, b.lon) for b in st.side("airbases", side)]

    # --- air superiority ---------------------------------------------------------------
    for f in fronts:
        needs.append(Need(mission="CAP", target=_front_target(st, f, side, 30, " CAP station"),
                          score=45 + 35 * lost_air + 10 * max(0, _pressure_on(side, f)),
                          reason=f"Air cover over {f.name} (air superiority {sup:.0%})"))
        if sup > 0.55:
            needs.append(Need(mission="SWEEP", target=_front_target(st, f, enemy, 25, " sweep area"),
                              score=30 + 20 * (sup - 0.5), reason=f"Exploit air superiority beyond {f.name}"))
    for b in st.side("airbases", side):
        if b.hit_last_turn:
            t = Target(kind="airbase", id=b.id, name=b.name, lat=b.lat, lon=b.lon)
            needs.append(Need(mission="CAP", target=t, score=72, reason=f"{b.name} was attacked last cycle"))
            if st.has_cap(side, "GCI"):
                needs.append(Need(mission="INTERCEPT", target=t, score=64, size=2,
                                  reason=f"Alert interceptors for {b.name} after last cycle's raid"))
        elif b.kind == "carrier":
            t = Target(kind="airbase", id=b.id, name=b.name, lat=b.lat, lon=b.lon)
            needs.append(Need(mission="CAP", target=t, score=44, size=2, reason=f"Fleet defence for {b.name}"))

    # --- enemy air defences --------------------------------------------------------------
    for s in st.side("sam_sites", enemy):
        if s.role != "sam" or s.health < 0.15 or not s.known:
            continue
        covered = sum(1 for p in my_points if geo.dist_km(p, (s.lat, s.lon)) < s.range_km + 30)
        near_front = any(geo.dist_km(front_points(st, f, side), (s.lat, s.lon)) < s.range_km + 15 for f in fronts)
        score = 34 + 9 * min(4, covered) + (18 if near_front else 0) + 8 * s.health
        mission = "SEAD" if st.has_cap(side, "SEAD") and s.range_km >= 10 else "DEAD"
        why = f"{s.name} ({s.template}, {s.range_km:.0f} km) threatens " + \
              ("the front line" if near_front else f"{covered} friendly positions" if covered else "strike routes")
        needs.append(Need(mission=mission, score=score, reason=why,
                          target=Target(kind="sam_site", id=s.id, name=s.name, lat=s.lat, lon=s.lon)))

    # --- supply network / infrastructure -------------------------------------------------
    total_out = sum(n.output for n in st.side("supply_nodes", enemy)) or 1.0
    feeding = {g.supply_node for g in st.side("ground_units", enemy)} | \
              {b.supply_node for b in st.side("airbases", enemy)}
    for n in st.side("supply_nodes", enemy):
        if n.health < 0.2:
            continue
        score = 28 + 30 * (n.output / total_out) + (12 if n.id in feeding else 0) + 8 * n.health
        needs.append(Need(mission="STRIKE", score=score,
                          reason=f"{n.name} ({n.kind}) sustains the enemy war effort",
                          target=Target(kind="supply_node", id=n.id, name=n.name, lat=n.lat, lon=n.lon)))
    for r in st.supply_routes.values():
        src, dst = st.supply_nodes.get(r.src), st.supply_nodes.get(r.dst)
        if not src or not dst or src.coalition != enemy or r.kind == "sea" or not r.convoy_units:
            continue
        mid = geo.lerp((src.lat, src.lon), (dst.lat, dst.lon), 0.5)
        hot = max([_pressure_on(side, f) for f in fronts] + [0.0])
        needs.append(Need(mission="INTERDICTION", score=30 + 18 * hot + 10 * (1 - r.interdiction),
                          reason=f"Cut the convoy route {src.name} → {dst.name}",
                          target=Target(kind="supply_route", id=r.id, name=f"{src.name} → {dst.name}",
                                        lat=mid[0], lon=mid[1])))
    for b in st.side("airbases", enemy):
        if b.kind != "airfield" or b.runway_health < 0.4:
            continue
        based = sum(s.available for s in st.squadrons.values() if s.airbase_id == b.id)
        needs.append(Need(mission="STRIKE", score=26 + 28 * lost_air + min(14, based * 0.5),
                          reason=f"Offensive counter-air against {b.name} ({based} aircraft based)",
                          target=Target(kind="airbase", id=b.id, name=b.name, lat=b.lat, lon=b.lon)))

    # --- ground war ----------------------------------------------------------------------------
    for f in fronts:
        mine, theirs = side_strength(st, f.id, side), side_strength(st, f.id, enemy)
        outnumbered = max(0.0, (theirs - mine) / (theirs + mine)) if theirs + mine else 0.0
        press = max(0.0, _pressure_on(side, f))
        needs.append(Need(mission="CAS", target=_front_target(st, f, enemy, 3, " enemy positions"),
                          score=40 + 30 * press + 25 * outnumbered,
                          reason=f"{f.name}: ground forces " + ("under pressure" if press > 0.2 else "need support")))

    # --- maritime ---------------------------------------------------------------------------------
    for n in st.side("naval_groups", enemy):
        if n.health < 0.2:
            continue
        near = min([geo.dist_km(p, (n.lat, n.lon)) for p in my_points] or [999])
        score = 32 + (22 if near < 150 else 0) + (10 if n.role in ("transport", "carrier") else 0)
        needs.append(Need(mission="ANTISHIP", score=score, reason=f"{n.name} operating {near:.0f} km from friendly forces",
                          target=Target(kind="naval_group", id=n.id, name=n.name, lat=n.lat, lon=n.lon)))

    # --- reconnaissance -------------------------------------------------------------------------
    hidden = [s for s in st.side("sam_sites", enemy) if not s.known]
    if hidden:
        s = hidden[0]
        needs.append(Need(mission="RECON", size=2, score=38, reason="Unlocated enemy air defences reported",
                          target=Target(kind="sam_site", id=s.id, name="suspected SAM area", lat=s.lat, lon=s.lon)))
    elif st.side("supply_nodes", enemy):
        n = max(st.side("supply_nodes", enemy), key=lambda x: x.stock)
        needs.append(Need(mission="RECON", size=2, score=22, reason=f"Battle damage assessment of {n.name}",
                          target=Target(kind="supply_node", id=n.id, name=n.name, lat=n.lat, lon=n.lon)))

    # --- support ----------------------------------------------------------------------------------
    if fronts:
        f = max(fronts, key=lambda x: abs(x.pressure))
        if st.has_cap(side, "AWACS"):
            needs.append(Need(mission="AWACS", size=1, score=90, reason="Airborne early warning for the cycle",
                              target=_front_target(st, f, side, 130, " AWACS orbit")))
        if st.has_cap(side, "TANKER"):
            needs.append(Need(mission="TANKER", size=1, score=85, reason="Air refuelling track for the cycle",
                              target=_front_target(st, f, side, 95, " tanker track")))
    low = [b for b in st.side("airbases", side) if b.kind == "airfield" and b.munition_level < 0.5]
    if low:
        b = min(low, key=lambda x: x.munition_level)
        needs.append(Need(mission="TRANSPORT", size=1, score=24, reason=f"{b.name} is short of munitions",
                          target=Target(kind="airbase", id=b.id, name=b.name, lat=b.lat, lon=b.lon)))
    needs.sort(key=lambda n: (-n.score, n.mission, n.target.id))
    return needs
