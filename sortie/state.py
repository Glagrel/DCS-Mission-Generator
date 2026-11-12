"""In-memory campaign state: load everything, mutate, save everything."""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from . import models as M
from .db import Store
from .models_ato import Ato, SortieResult

_COLLECTIONS = {
    "airbases": ("airbase", M.Airbase), "squadrons": ("squadron", M.Squadron),
    "fronts": ("front", M.Front), "ground_units": ("ground_unit", M.GroundUnit),
    "sam_sites": ("sam_site", M.SamSite), "supply_nodes": ("supply_node", M.SupplyNode),
    "supply_routes": ("supply_route", M.SupplyRoute), "naval_groups": ("naval_group", M.NavalGroup),
}


@dataclass
class State:
    meta: M.Meta
    pilot: Optional[M.Pilot] = None
    airbases: Dict[str, M.Airbase] = field(default_factory=dict)
    squadrons: Dict[str, M.Squadron] = field(default_factory=dict)
    fronts: Dict[str, M.Front] = field(default_factory=dict)
    ground_units: Dict[str, M.GroundUnit] = field(default_factory=dict)
    sam_sites: Dict[str, M.SamSite] = field(default_factory=dict)
    supply_nodes: Dict[str, M.SupplyNode] = field(default_factory=dict)
    supply_routes: Dict[str, M.SupplyRoute] = field(default_factory=dict)
    naval_groups: Dict[str, M.NavalGroup] = field(default_factory=dict)
    ato: Optional[Ato] = None
    sortie: Optional[SortieResult] = None

    # -- helpers -----------------------------------------------------------
    def rng(self, salt: str = "") -> random.Random:
        return random.Random(f"{self.meta.seed}:{self.meta.turn}:{salt}")

    @property
    def now(self) -> datetime:
        return datetime.fromisoformat(self.meta.date)

    def advance_clock(self) -> None:
        self.meta.date = (self.now + timedelta(hours=self.meta.turn_hours)).isoformat()
        self.meta.turn += 1

    def side(self, coll: str, coalition: str) -> List:
        return [x for x in getattr(self, coll).values() if x.coalition == coalition]

    def has_cap(self, coalition: str, capability: str) -> bool:
        return capability in self.meta.capabilities.get(coalition, [])

    def player_squadron(self) -> Optional[M.Squadron]:
        return self.squadrons.get(self.pilot.squadron_id) if self.pilot else None

    def entity(self, kind: str, eid: str):
        for attr, (k, _) in _COLLECTIONS.items():
            if k == kind:
                return getattr(self, attr).get(eid)
        return None


def load_state(store: Store, cid: str) -> State:
    meta = store.get(cid, "meta", "meta", M.Meta)
    if meta is None:
        raise KeyError(f"campaign {cid} not found")
    st = State(meta=meta, pilot=store.get(cid, "pilot", "player", M.Pilot))
    for attr, (kind, model) in _COLLECTIONS.items():
        setattr(st, attr, {o.id: o for o in store.all(cid, kind, model)})
    st.ato = store.get(cid, "ato", f"ato-{meta.turn}", Ato)
    st.sortie = store.get(cid, "sortie", f"sortie-{meta.turn}", SortieResult)
    from .campaign import ensure_plane_guards
    ensure_plane_guards(st)          # campaigns saved before every carrier had a plane guard
    return st


def save_state(store: Store, cid: str, st: State) -> None:
    with store.tx():
        store.put(cid, "meta", st.meta, commit=False)
        if st.pilot:
            store.put(cid, "pilot", st.pilot, commit=False)
        for attr, (kind, _) in _COLLECTIONS.items():
            for obj in getattr(st, attr).values():
                store.put(cid, kind, obj, commit=False)
        if st.ato:
            store.put(cid, "ato", st.ato, commit=False)
        if st.sortie:
            store.put(cid, "sortie", st.sortie, commit=False)
    store.touch(cid)
