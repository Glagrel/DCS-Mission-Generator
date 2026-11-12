"""ATO and sortie-result models."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

MISSION_TYPES = ("CAP", "INTERCEPT", "ESCORT", "SWEEP", "SEAD", "DEAD", "STRIKE", "CAS", "INTERDICTION",
                 "ANTISHIP", "RECON", "TANKER", "AWACS", "TRANSPORT", "SAR")
A2A = ("CAP", "ESCORT", "SWEEP")
A2G = ("SEAD", "DEAD", "STRIKE", "CAS", "INTERDICTION", "ANTISHIP")
SUPPORT = ("TANKER", "AWACS", "TRANSPORT", "RECON", "SAR")


class Target(BaseModel):
    kind: str                # airbase | sam_site | supply_node | supply_route | front | naval_group | zone
    id: str
    name: str
    lat: float
    lon: float


class Waypoint(BaseModel):
    name: str
    lat: float
    lon: float
    alt_m: float
    speed_kmh: float
    action: str = "fly"      # takeoff | fly | hold | ip | target | orbit | land
    eta_s: Optional[float] = None   # seconds after the start of the cycle
    hold_s: float = 0.0             # time on station (orbit waypoints)


class Flight(BaseModel):
    id: str
    squadron_id: str
    coalition: str
    aircraft: str
    count: int
    task: str                # one of MISSION_TYPES
    callsign: str = ""
    freq: float = 0.0
    is_player: bool = False
    waypoints: List[Waypoint] = Field(default_factory=list)
    loadout: str = ""
    status: str = "planned"  # planned | simulated | resolved | cancelled
    result: Dict[str, Any] = Field(default_factory=dict)


class Package(BaseModel):
    id: str
    coalition: str
    mission: str
    target: Target
    tot_s: float = 0.0       # time on target, seconds after turn start
    score: float = 0.0
    reason: str = ""
    flights: List[Flight] = Field(default_factory=list)
    freq: float = 0.0


class Ato(BaseModel):
    id: str                  # "ato-<turn>"
    turn: int
    packages: List[Package] = Field(default_factory=list)
    player_flight_id: Optional[str] = None
    player_package_id: Optional[str] = None
    support: Dict[str, Any] = Field(default_factory=dict)  # tanker/awacs info per side

    def flights(self):
        for p in self.packages:
            for f in p.flights:
                yield p, f

    def find_flight(self, flight_id: str):
        for p, f in self.flights():
            if f.id == flight_id:
                return p, f
        return None, None


class FlightResult(BaseModel):
    flight_id: str
    lost: int = 0
    pilots_lost: int = 0
    kills_air: int = 0
    kills_ground: int = 0
    kills_naval: int = 0
    kills_structure: int = 0
    success: float = 0.0     # 0..1
    simulated: bool = False  # True = flown in DCS


class SortieResult(BaseModel):
    id: str                  # "sortie-<turn>"
    turn: int
    state: str = "planned"   # planned | built | flown | skipped
    miz_path: Optional[str] = None
    flight_time_s: float = 0.0
    player: Dict[str, Any] = Field(default_factory=dict)
    flights: Dict[str, FlightResult] = Field(default_factory=dict)
    entity_damage: Dict[str, float] = Field(default_factory=dict)   # "kind:id" -> fraction destroyed
    entity_units_lost: Dict[str, int] = Field(default_factory=dict)
    warehouses: Dict[str, Any] = Field(default_factory=dict)        # airbase id -> readback
    timeline: List[Dict[str, Any]] = Field(default_factory=list)
    summary: Dict[str, Any] = Field(default_factory=dict)
    mission_success: Optional[bool] = None
