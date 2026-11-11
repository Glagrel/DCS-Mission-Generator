"""Campaign state entities (pydantic). Stored as JSON documents by sortie.db."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

BLUE, RED = "blue", "red"


def enemy_of(side: str) -> str:
    return RED if side == BLUE else BLUE


class LatLon(BaseModel):
    lat: float
    lon: float


class Meta(BaseModel):
    id: str = "meta"
    name: str
    template_id: str
    terrain: str
    era_kind: str = "modern"          # ww2 | coldwar | modern
    year: int = 2010
    player_side: str = BLUE
    date: str                          # ISO datetime of the *start* of the current turn
    turn: int = 1
    turn_hours: int = 6
    difficulty: str = "normal"
    profile: str = "auto"
    seed: int = 1
    status: str = "active"             # active | won | lost
    capabilities: Dict[str, List[str]] = Field(default_factory=dict)  # side -> list
    doctrine: Dict[str, str] = Field(default_factory=dict)            # side -> nato|soviet|ww2
    coalition_names: Dict[str, str] = Field(default_factory=dict)
    countries: Dict[str, List[str]] = Field(default_factory=dict)
    bullseye: Dict[str, LatLon] = Field(default_factory=dict)
    weather: Dict[str, Any] = Field(default_factory=dict)
    owned_modules: List[str] = Field(default_factory=list)
    war_score: float = 0.0             # -1 red winning .. +1 blue winning
    production: Dict[str, Dict[str, float]] = Field(default_factory=dict)  # side -> per-turn overrides
    features: Dict[str, Any] = Field(default_factory=dict)


class Fuel(BaseModel):
    jet: float = 0.0
    avgas: float = 0.0
    mw50: float = 0.0
    diesel: float = 0.0


class Airbase(BaseModel):
    id: str
    name: str
    dcs_name: Optional[str] = None     # pydcs airport name; None for carriers
    kind: str = "airfield"             # airfield | carrier | farp
    coalition: str
    lat: float
    lon: float
    runway_health: float = 1.0
    fuel: Fuel = Field(default_factory=Fuel)
    fuel_cap: float = 1500.0
    munitions: Dict[str, int] = Field(default_factory=dict)  # DCS item name -> count
    munition_level: float = 1.0        # generic stock 0..1 for items not yet seen
    supply_node: Optional[str] = None  # node that feeds this base
    naval_group: Optional[str] = None  # for carriers
    hit_last_turn: bool = False


class Squadron(BaseModel):
    id: str
    name: str
    coalition: str
    country: str
    airbase_id: str
    aircraft: str                      # pydcs type id
    tasks: List[str]
    airframes: int
    airframes_max: int
    pilots: int
    pilots_max: int
    skill: str = "Good"
    morale: float = 1.0
    is_player: bool = False
    callsign: str = ""
    sorties_flown: int = 0
    kills: int = 0
    losses: int = 0

    @property
    def available(self) -> int:
        return max(0, min(self.airframes, self.pilots))


class Front(BaseModel):
    id: str
    name: str
    a: LatLon                          # blue rear anchor
    b: LatLon                          # red rear anchor
    position: float = 0.5              # 0 = at a, 1 = at b; blue advances toward b
    width_km: float = 30.0
    pressure: float = 0.0              # -1 red pushing .. +1 blue pushing (last turn)
    cas_effect: Dict[str, float] = Field(default_factory=dict)  # side -> damage dealt this turn


class GroundUnit(BaseModel):
    id: str
    name: str
    coalition: str
    country: str
    front_id: str
    units: Dict[str, int]              # pydcs vehicle id -> count at full strength
    strength: float = 1.0
    supply: float = 1.0
    supply_node: Optional[str] = None
    lat: float = 0.0
    lon: float = 0.0


class SamSite(BaseModel):
    id: str
    name: str
    coalition: str
    country: str
    template: str                      # key in data/sam_templates.yaml
    role: str = "sam"                  # sam | ewr | aaa
    lat: float
    lon: float
    health: float = 1.0
    range_km: float = 0.0
    known: bool = True                 # known to the enemy (shown on their map)


class SupplyNode(BaseModel):
    id: str
    name: str
    kind: str                          # factory | port | depot | rail | bridge
    coalition: str
    country: str
    lat: float
    lon: float
    health: float = 1.0
    output: float = 0.0                # tons/turn generated (factory, port)
    stock: float = 0.0
    stock_cap: float = 2000.0
    static_type: str = "Warehouse"
    n_objects: int = 4
    received_last_turn: float = 0.0


class SupplyRoute(BaseModel):
    id: str
    src: str
    dst: str                           # node id or airbase id
    capacity: float = 200.0
    kind: str = "road"                 # road | rail | sea
    interdiction: float = 0.0          # 0..1 this turn; decays
    convoy_units: Dict[str, int] = Field(default_factory=dict)


class NavalGroup(BaseModel):
    id: str
    name: str
    coalition: str
    country: str
    units: List[str]                   # pydcs ship ids; first is the flagship
    lat: float
    lon: float
    health: float = 1.0
    airbase_id: Optional[str] = None
    track: List[LatLon] = Field(default_factory=list)
    role: str = "combat"               # combat | carrier | transport


class Pilot(BaseModel):
    id: str = "player"
    callsign: str
    rank: str = ""
    rank_index: int = 0
    hours: float = 0.0
    sorties: int = 0
    landings: int = 0
    kills: Dict[str, int] = Field(default_factory=lambda: {"air": 0, "ground": 0, "naval": 0, "structure": 0})
    awards: List[str] = Field(default_factory=list)
    status: str = "active"             # active | wounded | mia | kia | pow
    ejections: int = 0
    squadron_id: str
    aircraft: str
    points: float = 0.0
    history: List[Dict[str, Any]] = Field(default_factory=list)


KINDS: Dict[str, type] = {
    "meta": Meta, "airbase": Airbase, "squadron": Squadron, "front": Front,
    "ground_unit": GroundUnit, "sam_site": SamSite, "supply_node": SupplyNode,
    "supply_route": SupplyRoute, "naval_group": NavalGroup, "pilot": Pilot,
}
