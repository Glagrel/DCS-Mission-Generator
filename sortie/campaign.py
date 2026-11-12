"""Campaign creation from a theater template (the career-start wizard backend)."""
from __future__ import annotations

import logging
import re
import uuid
from typing import List, Optional

from pydantic import BaseModel

from . import config, geo, models as M, terrain, units
from .db import Store
from .state import State, save_state
from .theater import Theater, validate

log = logging.getLogger("sortie.campaign")


class CareerOptions(BaseModel):
    theater_id: str
    side: str = "blue"
    squadron_id: str
    aircraft: Optional[str] = None      # must equal the squadron's type; kept for wizard clarity
    callsign: str = "Rookie"
    difficulty: str = "normal"
    profile: str = "auto"
    seed: int = 1
    name: Optional[str] = None


class CampaignError(ValueError):
    pass


def owned(settings: Optional[config.Settings]) -> List[str]:
    if settings and settings.owned_modules is not None:
        return list(settings.owned_modules)
    return units.flyable_modules()


def playable_squadrons(t: Theater, side: str, owned_modules: List[str]) -> List[str]:
    """Squadron ids the player may join: right side, owned + flyable + in-era airframe."""
    ok = set(owned_modules) & set(units.flyable_in_era(t.era.year, t.era.kind))
    return [s.id for s in t.squadrons if s.coalition == side and s.aircraft in ok]


def build_state(t: Theater, opt: CareerOptions, settings: Optional[config.Settings] = None) -> State:
    errs = validate(t)
    if errs:
        raise CampaignError("invalid theater: " + "; ".join(errs[:5]))
    if opt.side not in ("blue", "red"):
        raise CampaignError("side must be blue or red")
    if opt.squadron_id not in playable_squadrons(t, opt.side, owned(settings)):
        raise CampaignError(f"squadron {opt.squadron_id} is not playable (side, era or owned modules)")
    d = config.defaults(settings)
    if opt.difficulty not in d["difficulty"]:
        raise CampaignError(f"unknown difficulty {opt.difficulty}")
    meta = M.Meta(
        name=opt.name or f"{t.name} - {opt.callsign}", template_id=t.id, terrain=t.terrain,
        era_kind=t.era.kind, year=t.era.year, player_side=opt.side,
        date=f"{t.start.date}T{t.start.time}:00", turn_hours=d["turn_hours"],
        difficulty=opt.difficulty, profile=opt.profile, seed=opt.seed,
        capabilities={s: list(c.capabilities) for s, c in t.coalitions.items()},
        doctrine={s: c.doctrine for s, c in t.coalitions.items()},
        coalition_names={s: c.name for s, c in t.coalitions.items()},
        countries={s: list(c.countries) for s, c in t.coalitions.items()},
        bullseye={s: M.LatLon(lat=v[0], lon=v[1]) for s, v in t.bullseye.items()},
        weather=dict(t.start.weather), owned_modules=owned(settings),
        production={s: dict(c.production) for s, c in t.coalitions.items() if c.production})
    st = State(meta=meta)
    from . import weather as _wx
    _wx.normalize(st.meta.weather, st.rng("weather"))
    cap = d["logistics"]["airbase_fuel_cap_t"]
    ww2 = t.era.kind == "ww2"

    def fuel(tons: float) -> M.Fuel:
        return M.Fuel(avgas=tons, jet=0.0, diesel=tons / 5) if ww2 else \
            M.Fuel(jet=tons, avgas=tons / 10, diesel=tons / 5)

    for a in t.airbases:
        lat, lon = terrain.airport_latlon(t.terrain, a.dcs_name)
        st.airbases[a.id] = M.Airbase(
            id=a.id, name=a.dcs_name, dcs_name=a.dcs_name, coalition=a.coalition, lat=lat, lon=lon,
            fuel=fuel(a.fuel), fuel_cap=max(cap, a.fuel), munition_level=a.munition_level,
            supply_node=a.supply_node)
    for c in t.carriers:
        st.airbases[c.id] = M.Airbase(
            id=c.id, name=c.name, kind="carrier", coalition=c.coalition, lat=c.lat, lon=c.lon,
            fuel=fuel(c.fuel), fuel_cap=max(cap, c.fuel), naval_group=c.id)
        st.naval_groups[c.id] = M.NavalGroup(
            id=c.id, name=c.name, coalition=c.coalition, country=c.country, units=list(c.ships),
            lat=c.lat, lon=c.lon, airbase_id=c.id, role="carrier",
            track=[M.LatLon(lat=p[0], lon=p[1]) for p in c.track])
    for s in t.squadrons:
        pilots = s.pilots if s.pilots is not None else int(round(s.airframes * 1.25))
        st.squadrons[s.id] = M.Squadron(
            id=s.id, name=s.name, coalition=s.coalition, country=s.country, airbase_id=s.airbase,
            aircraft=s.aircraft, tasks=list(s.tasks), airframes=s.airframes, airframes_max=s.airframes,
            pilots=pilots, pilots_max=pilots, skill=s.skill, callsign=s.callsign or _callsign(s.name),
            is_player=(s.id == opt.squadron_id))
    for f in t.fronts:
        st.fronts[f.id] = M.Front(id=f.id, name=f.name, a=M.LatLon(lat=f.a[0], lon=f.a[1]),
                                  b=M.LatLon(lat=f.b[0], lon=f.b[1]), position=f.position,
                                  width_km=f.width_km)
    for g in t.ground_units:
        st.ground_units[g.id] = M.GroundUnit(id=g.id, name=g.name, coalition=g.coalition,
                                             country=g.country, front_id=g.front, units=dict(g.units),
                                             supply_node=g.supply_node)
    for s in t.sam_sites:
        tpl = units.sam_template(s.template)
        st.sam_sites[s.id] = M.SamSite(id=s.id, name=s.name or s.id, coalition=s.coalition,
                                       country=s.country, template=s.template, role=tpl["role"],
                                       lat=s.lat, lon=s.lon, range_km=tpl["range_km"])
    for n in t.supply_nodes:
        st.supply_nodes[n.id] = M.SupplyNode(**n.model_dump())
    for r in t.supply_routes:
        rid = f"{r.src}__{r.dst}"
        st.supply_routes[rid] = M.SupplyRoute(id=rid, **r.model_dump())
    for n in t.naval_groups:
        st.naval_groups[n.id] = M.NavalGroup(
            id=n.id, name=n.name, coalition=n.coalition, country=n.country, units=list(n.units),
            lat=n.lat, lon=n.lon, role=n.role, track=[M.LatLon(lat=p[0], lon=p[1]) for p in n.track])
    place_ground_units(st)
    ensure_plane_guards(st)
    sq = st.squadrons[opt.squadron_id]
    from .debrief.career import rank_name
    st.pilot = M.Pilot(callsign=opt.callsign, squadron_id=sq.id, aircraft=sq.aircraft,
                       rank=rank_name(st.meta.doctrine.get(opt.side, "nato"), opt.side, 0, t.era.kind))
    return st


# plane-guard helicopters, newest first: the first one in era flies from carriers without one
PLANE_GUARD_TYPES = ("SH-60B", "SH-3W")


def ensure_plane_guards(st: State) -> List[str]:
    """Every aircraft-carrying ship of a NATO coalition (CVN, LHA ...) keeps a plane-guard
    helicopter squadron aboard, even when the theater template gave it none. Runs at campaign
    creation and on every load, so campaigns made before this rule get one too.
    Returns the ids of squadrons added."""
    added: List[str] = []
    for b in st.airbases.values():
        if b.kind != "carrier" or st.meta.doctrine.get(b.coalition, "nato") != "nato":
            continue
        if any(s.airbase_id == b.id and "SAR" in s.tasks for s in st.squadrons.values()):
            continue
        ac = next((a for a in PLANE_GUARD_TYPES if units.exists(a)
                   and units.in_era(a, st.meta.year, st.meta.era_kind)), None)
        ng = st.naval_groups.get(b.naval_group or b.id)
        if ac is None or ng is None:
            continue
        sid = f"{b.id}_pg"
        st.squadrons[sid] = M.Squadron(
            id=sid, name=f"{b.name} plane guard", coalition=b.coalition, country=ng.country, airbase_id=b.id,
            aircraft=ac, tasks=["SAR"], airframes=2, airframes_max=2, pilots=3, pilots_max=3,
            callsign="Seahawk" if ac == "SH-60B" else "Angel")
        added.append(sid)
    return added


def _callsign(name: str) -> str:
    return re.sub(r"[^A-Za-z]", "", name)[:8] or "Flight"


def place_ground_units(st: State) -> None:
    """Put each formation on its own side of its front line, spread along the line."""
    for front in st.fronts.values():
        a, b = (front.a.lat, front.a.lon), (front.b.lat, front.b.lon)
        axis_km = max(1.0, geo.dist_km(a, b))
        br = geo.bearing(a, b)
        for side in ("blue", "red"):
            group = [g for g in st.ground_units.values() if g.front_id == front.id and g.coalition == side]
            back = min(0.45, 3.0 / axis_km)            # ~3 km behind the line
            pos = front.position - back if side == "blue" else front.position + back
            centre = geo.lerp(a, b, max(0.0, min(1.0, pos)))
            for i, g in enumerate(sorted(group, key=lambda x: x.id)):
                off = (i - (len(group) - 1) / 2) * (front.width_km / max(1, len(group)))
                g.lat, g.lon = geo.destination(centre, br + 90, off)


def create_campaign(store: Store, t: Theater, opt: CareerOptions,
                    settings: Optional[config.Settings] = None) -> str:
    st = build_state(t, opt, settings)
    cid = uuid.uuid4().hex[:10]
    store.create_campaign(cid, st.meta.name)
    save_state(store, cid, st)
    store.log(cid, 1, "campaign", {"msg": f"Campaign started: {st.meta.name}",
                                   "squadron": opt.squadron_id, "aircraft": st.pilot.aircraft})
    log.info("campaign created id=%s theater=%s squadron=%s", cid, t.id, opt.squadron_id)
    return cid
