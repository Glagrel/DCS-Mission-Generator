"""Theater template schema, loader and validation (data/theaters/*.yaml)."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml
from pydantic import BaseModel, Field, field_validator

from . import paths, terrain, units
from .models_ato import MISSION_TYPES

THEATER_DIR = paths.PROJECT_ROOT / "data" / "theaters"
CAPABILITIES = ("AWACS", "TANKER", "GCI", "CARRIER", "SEAD", "PGM", "HELO", "RADAR_SAM", "NIGHT")
LL = Tuple[float, float]


class Era(BaseModel):
    year: int
    kind: str                         # ww2 | coldwar | modern
    restrictions: List[str] = Field(default_factory=list)

    @field_validator("kind")
    @classmethod
    def _kind(cls, v):
        if v not in ("ww2", "coldwar", "modern"):
            raise ValueError("era.kind must be ww2|coldwar|modern")
        return v


class Start(BaseModel):
    date: str                         # YYYY-MM-DD
    time: str = "06:00"
    weather: Dict[str, Any] = Field(default_factory=dict)


class CoalitionT(BaseModel):
    name: str
    countries: List[str]
    capabilities: List[str] = Field(default_factory=list)
    doctrine: str = "nato"            # nato | soviet | ww2
    production: Dict[str, float] = Field(default_factory=dict)  # airframes/pilots per turn override

    @field_validator("capabilities")
    @classmethod
    def _caps(cls, v):
        bad = [c for c in v if c not in CAPABILITIES]
        if bad:
            raise ValueError(f"unknown capabilities {bad}")
        return v


class AirbaseT(BaseModel):
    id: str
    dcs_name: str
    coalition: str
    fuel: float = 800.0
    munition_level: float = 1.0
    supply_node: Optional[str] = None


class CarrierT(BaseModel):
    id: str
    name: str
    coalition: str
    country: str
    ships: List[str]
    lat: float
    lon: float
    track: List[LL] = Field(default_factory=list)
    fuel: float = 600.0


class SquadronT(BaseModel):
    id: str
    name: str
    coalition: str
    country: str
    airbase: str
    aircraft: str
    tasks: List[str]
    airframes: int = 12
    pilots: Optional[int] = None
    skill: str = "Good"
    callsign: str = ""

    @field_validator("tasks")
    @classmethod
    def _tasks(cls, v):
        bad = [t for t in v if t not in MISSION_TYPES]
        if bad:
            raise ValueError(f"unknown mission types {bad}")
        return v


class FrontT(BaseModel):
    id: str
    name: str
    a: LL
    b: LL
    position: float = 0.5
    width_km: float = 30.0


class GroundT(BaseModel):
    id: str
    name: str
    coalition: str
    country: str
    front: str
    units: Dict[str, int]
    supply_node: Optional[str] = None


class SamT(BaseModel):
    id: str
    name: str = ""
    coalition: str
    country: str
    template: str
    lat: float
    lon: float


class NodeT(BaseModel):
    id: str
    name: str
    kind: str
    coalition: str
    country: str
    lat: float
    lon: float
    output: float = 0.0
    stock: float = 500.0
    static_type: str = "Warehouse"
    n_objects: int = 4

    @field_validator("kind")
    @classmethod
    def _kind(cls, v):
        if v not in ("factory", "port", "depot", "rail", "bridge"):
            raise ValueError("node kind must be factory|port|depot|rail|bridge")
        return v


class RouteT(BaseModel):
    src: str
    dst: str
    capacity: float = 200.0
    kind: str = "road"
    convoy_units: Dict[str, int] = Field(default_factory=dict)


class NavalT(BaseModel):
    id: str
    name: str
    coalition: str
    country: str
    units: List[str]
    lat: float
    lon: float
    track: List[LL] = Field(default_factory=list)
    role: str = "combat"


class Theater(BaseModel):
    id: str
    name: str
    description: str = ""
    terrain: str
    era: Era
    start: Start
    coalitions: Dict[str, CoalitionT]
    bullseye: Dict[str, LL] = Field(default_factory=dict)
    airbases: List[AirbaseT]
    carriers: List[CarrierT] = Field(default_factory=list)
    squadrons: List[SquadronT]
    fronts: List[FrontT] = Field(default_factory=list)
    ground_units: List[GroundT] = Field(default_factory=list)
    sam_sites: List[SamT] = Field(default_factory=list)
    supply_nodes: List[NodeT] = Field(default_factory=list)
    supply_routes: List[RouteT] = Field(default_factory=list)
    naval_groups: List[NavalT] = Field(default_factory=list)

    def side_of_country(self, country: str) -> Optional[str]:
        for side, c in self.coalitions.items():
            if country in c.countries:
                return side
        return None


def load_file(path: Path) -> Theater:
    with open(path, encoding="utf-8") as f:
        t = Theater(**yaml.safe_load(f))
    from . import mods
    mods.extend_theater(t)           # squadrons flying mod aircraft, while those mods are on
    return t


def list_theaters(directory: Path = THEATER_DIR) -> List[Theater]:
    return [load_file(p) for p in sorted(directory.glob("*.yaml"))]


def load(theater_id: str, directory: Path = THEATER_DIR) -> Theater:
    for t in list_theaters(directory):
        if t.id == theater_id:
            return t
    raise KeyError(f"theater '{theater_id}' not found in {directory}")


def validate(t: Theater) -> List[str]:
    """Cross-reference checks. Returns a list of problems (empty = valid)."""
    from dcs import countries as C
    errs: List[str] = []
    if set(t.coalitions) != {"blue", "red"}:
        errs.append("coalitions must be exactly blue and red")
    known_countries = {c.name for c in C.country_dict.values()}
    for side, co in t.coalitions.items():
        errs += [f"{side}: unknown country {c}" for c in co.countries if c not in known_countries]
    if not terrain.is_supported(t.terrain):
        errs.append(f"terrain {t.terrain} unsupported")
        names = set()
    else:
        names = set(terrain.airport_names(t.terrain))
    base_ids = {a.id for a in t.airbases} | {c.id for c in t.carriers}
    node_ids = {n.id for n in t.supply_nodes}
    front_ids = {f.id for f in t.fronts}
    y, k = t.era.year, t.era.kind

    def era(type_id: str, where: str) -> None:
        if not units.exists(type_id):
            errs.append(f"{where}: unknown pydcs type '{type_id}'")
        elif not units.in_era(type_id, y, k):
            errs.append(f"{where}: '{type_id}' ({units.year_of(type_id)}) not allowed in {k} {y}")

    def country(c: str, side: str, where: str) -> None:
        if t.side_of_country(c) != side:
            errs.append(f"{where}: country {c} is not in coalition {side}")

    for a in t.airbases:
        if names and a.dcs_name not in names:
            errs.append(f"airbase {a.id}: no airport '{a.dcs_name}' on {t.terrain}")
        if a.supply_node and a.supply_node not in node_ids:
            errs.append(f"airbase {a.id}: unknown supply node {a.supply_node}")
    for c in t.carriers:
        country(c.country, c.coalition, f"carrier {c.id}")
        for s in c.ships:
            era(s, f"carrier {c.id}")
    for s in t.squadrons:
        if s.airbase not in base_ids:
            errs.append(f"squadron {s.id}: unknown airbase {s.airbase}")
        country(s.country, s.coalition, f"squadron {s.id}")
        era(s.aircraft, f"squadron {s.id}")
        can = units.capable_missions(s.aircraft)
        errs += [f"squadron {s.id}: {s.aircraft} cannot fly {m}" for m in s.tasks if m not in can]
        caps = t.coalitions[s.coalition].capabilities if s.coalition in t.coalitions else []
        for m in ("AWACS", "TANKER"):
            if m in s.tasks and m not in caps:
                errs.append(f"squadron {s.id}: task {m} but coalition lacks capability")
    for g in t.ground_units:
        if g.front not in front_ids:
            errs.append(f"ground {g.id}: unknown front {g.front}")
        country(g.country, g.coalition, f"ground {g.id}")
        for u in g.units:
            era(u, f"ground {g.id}")
    for s in t.sam_sites:
        tpl = units.sam_template(s.template)
        country(s.country, s.coalition, f"sam {s.id}")
        if tpl is None:
            errs.append(f"sam {s.id}: unknown template {s.template}")
            continue
        if tpl["year"] > y or (k == "ww2" and tpl["year"] > 1945):
            errs.append(f"sam {s.id}: template {s.template} ({tpl['year']}) not allowed in {k} {y}")
        errs += [f"sam template {s.template}: unknown vehicle {u}" for u in tpl["units"]
                 if not units.vehicle_type(u)]
    for n in t.supply_nodes:
        country(n.country, n.coalition, f"node {n.id}")
    for r in t.supply_routes:
        for end in (r.src, r.dst):
            if end not in node_ids and end not in base_ids:
                errs.append(f"route {r.src}->{r.dst}: unknown endpoint {end}")
        for u in r.convoy_units:
            era(u, f"route {r.src}->{r.dst}")
    for n in t.naval_groups:
        country(n.country, n.coalition, f"naval {n.id}")
        for u in n.units:
            era(u, f"naval {n.id}")
    ids = [x.id for coll in (t.airbases, t.carriers, t.squadrons, t.fronts, t.ground_units, t.sam_sites,
                             t.supply_nodes, t.naval_groups) for x in coll]
    errs += [f"duplicate id {i}" for i in sorted({i for i in ids if ids.count(i) > 1})]
    return errs
