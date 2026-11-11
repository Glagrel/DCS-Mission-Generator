"""Airbase warehouses: campaign stocks -> .miz, plus the table the Lua side applies/reads.

Verified facts (Hoggit wiki, DCS 2.8.8+): the .miz `warehouses` file holds per-airport
coalition, unlimited flags and `InitFuel` per liquid; `Airbase.getWarehouse()` returns a
Warehouse with setItem(itemName, count), getInventory() -> {weapon, liquids, aircraft}
(empty tables for unlimited categories) and getLiquidAmount(0=jet,1=avgas,2=MW50,3=diesel).
Per-weapon rows in the .miz need wsType codes pydcs does not have, so weapon stock is set by
Lua at mission start (see DECISIONS 5).
"""
from __future__ import annotations

from typing import Any, Dict, List

from .. import models as M, units
from ..state import State

SIDE = {"blue": "BLUE", "red": "RED"}
LIQUIDS = {"jet": 0, "avgas": 1, "mw50": 2, "diesel": 3}


def apply_to_mission(m, st: State, logistics: Dict[str, Any]) -> None:
    """Set coalition, limited flags and fuel for every terrain airport."""
    by_name = {b.dcs_name: b for b in st.airbases.values() if b.dcs_name}
    for name, ap in m.terrain.airports.items():
        base = by_name.get(name)
        if base is None:
            ap.set_neutral()
            continue
        ap.set_blue() if base.coalition == "blue" else ap.set_red()
        _fill(ap, base, logistics)


def _fill(wh, base: M.Airbase, logistics: Dict[str, Any]) -> None:
    wh.unlimited_fuel = not logistics.get("limit_fuel", True)
    wh.unlimited_munitions = not logistics.get("limit_munitions", True)
    wh.unlimited_aircrafts = not logistics.get("limit_aircraft", False)
    wh.jet_init = round(base.fuel.jet, 1)
    wh.gasoline_init = round(base.fuel.avgas, 1)
    wh.methanol_mixture_init = round(base.fuel.mw50, 1)
    wh.diesel_init = round(base.fuel.diesel, 1)


def carrier_warehouse(base: M.Airbase, logistics: Dict[str, Any]) -> Dict[str, Any]:
    """Warehouse dict for a carrier unit (pydcs keeps these in mission.warehouses.warehouses)."""
    from dcs.terrain.terrain import Warehouse
    wh = Warehouse()
    wh.coalition = SIDE[base.coalition]
    _fill(wh, base, logistics)
    return wh.dict()


def lua_table(st: State, logistics: Dict[str, Any], carrier_units: Dict[str, str]) -> Dict[str, Any]:
    """Per-airbase data for sortie_warehouse.lua, keyed by the DCS airbase name.

    For carriers the key is the carrier unit name (Airbase.getByName works on ship units).
    """
    default_stock = int(logistics["default_weapon_stock"])
    out: Dict[str, Any] = {}
    for b in st.airbases.values():
        key = b.dcs_name or carrier_units.get(b.naval_group or "")
        if not key:
            continue
        aircraft: Dict[str, int] = {}
        for s in st.squadrons.values():
            if s.airbase_id == b.id:
                aircraft[s.aircraft] = aircraft.get(s.aircraft, 0) + s.airframes
        out[key] = {
            "id": b.id,
            "coalition": 2 if b.coalition == "blue" else 1,
            "weapons": {k: int(v) for k, v in b.munitions.items()},
            "default_stock": int(round(default_stock * b.munition_level)),
            "aircraft": aircraft,
            "limit_munitions": bool(logistics.get("limit_munitions", True)),
            "limit_aircraft": bool(logistics.get("limit_aircraft", False)),
        }
    return out


def apply_readback(st: State, readback: Dict[str, Any], logistics: Dict[str, Any]) -> List[str]:
    """Fold end-of-mission warehouse reports into campaign state.

    `readback[airbase id] = {"liquids_start": {"0": x..}, "liquids_end": {...},
                             "weapons": {item: count}}`.
    Fuel uses the end/start *ratio* so no assumption about DCS's internal unit is needed.
    """
    notes: List[str] = []
    default_stock = max(1, int(logistics["default_weapon_stock"]))
    for base_id, rb in readback.items():
        b = st.airbases.get(base_id)
        if b is None:
            continue
        start, end = rb.get("liquids_start") or {}, rb.get("liquids_end") or {}
        for attr, idx in LIQUIDS.items():
            s, e = start.get(str(idx)), end.get(str(idx))
            if s and e is not None and s > 0:
                ratio = max(0.0, min(1.0, float(e) / float(s)))
                setattr(b.fuel, attr, round(getattr(b.fuel, attr) * ratio, 2))
        weapons = rb.get("weapons")
        if isinstance(weapons, dict) and weapons:
            b.munitions = {str(k): int(v) for k, v in weapons.items() if isinstance(v, (int, float))}
            level = sum(min(default_stock, v) for v in b.munitions.values()) / (default_stock * len(b.munitions))
            b.munition_level = round(max(0.0, min(1.0, level)), 3)
            notes.append(f"{b.name}: {len(b.munitions)} weapon types tracked, level {b.munition_level:.0%}")
    return notes
