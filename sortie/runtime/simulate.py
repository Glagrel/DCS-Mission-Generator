"""Synthetic mission events in the exact format the Lua writes. Used by the tests, the
end-to-end check and `python -m sortie simulate` to exercise the debrief loop without DCS."""
from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any, Dict, List, Optional

SIDE_NUM = {"blue": 2, "red": 1}
PREFIX = {"sam_site": "sam", "ground_unit": "gnd", "supply_route": "cvy", "naval_group": "nav"}


class EventWriter:
    def __init__(self, sortie_id: str, run: str = "1000") -> None:
        self.sortie_id, self.run, self.seq, self.events = sortie_id, run, 0, []

    def emit(self, ev: str, t: float, **data: Any) -> Dict[str, Any]:
        self.seq += 1
        e = {"ev": ev, "t": t, "id": f"{self.sortie_id}-{self.run}-{self.seq}", **data}
        self.events.append(e)
        return e

    def write(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for e in self.events:
                f.write(json.dumps(e) + "\n")
        return path


def unit_ref(group: str, entry: Dict[str, Any], n: int = 1, player: Optional[str] = None) -> Dict[str, Any]:
    kind = entry["kind"]
    if kind == "flight":
        name, ty = f"{group} Pilot #{n}", entry.get("aircraft", "?")
        c = SIDE_NUM.get(entry.get("coalition"), 0)
    elif kind == "supply_node":
        name, ty, c = group, "Warehouse", entry.get("c", 0)
    else:
        name, ty, c = f"{group} #{n}", kind, entry.get("c", 0)
    ref = {"n": name, "g": group, "ty": ty, "c": c, "cat": 3 if kind == "supply_node" else 1}
    if player:
        ref["p"] = player
    return ref


def simulate(manifest: Dict[str, Any], sortie_id: str, player_group: str, turn: int = 1, seed: int = 1,
             outcome: str = "success", warehouses: Optional[Dict[str, Any]] = None,
             player_name: str = "Rook") -> List[Dict[str, Any]]:
    """outcome: success | fail | eject | killed | no_takeoff."""
    rng = random.Random(seed)
    w = EventWriter(sortie_id)
    me = manifest[player_group]
    my_side = me.get("coalition", "blue")
    pl = unit_ref(player_group, me, 1, player_name)
    w.emit("mission_start", 0, campaign="sim", turn=turn, sortie=sortie_id, run=w.run, mode="file", version=1)
    for base, wh in (warehouses or {}).items():
        w.emit("warehouse", 1, phase="start", base=base, liquids_start=wh["start"], liquids=wh["start"],
               weapons=wh.get("weapons_start", {}))
    w.emit("player_enter", 5, i=pl)
    if outcome == "no_takeoff":
        w.emit("mission_end", 120)
        return w.events
    w.emit("takeoff", 420, i=pl, place="home")
    for n in range(2, me.get("units", 1) + 1):
        w.emit("takeoff", 430 + n * 5, i=unit_ref(player_group, me, n), place="home")
    enemy_flights = [(g, v) for g, v in manifest.items() if v["kind"] == "flight"
                     and v.get("coalition") != my_side]
    enemy_ground = [(g, v) for g, v in manifest.items() if v["kind"] in PREFIX and not v.get("late")]
    statics = [(g, v) for g, v in manifest.items() if v["kind"] == "supply_node" and not v.get("dead")]
    t = 1500.0
    if outcome in ("success", "eject"):
        task = me.get("task", "")
        if task in ("CAP", "ESCORT", "SWEEP", "INTERCEPT") and enemy_flights:
            g, v = enemy_flights[0]
            for n in range(1, min(2, v["units"]) + 1):
                tg = unit_ref(g, v, n)
                w.emit("shot", t, i=pl, w="AIM-120C")
                w.emit("kill", t + 20, i=pl, tg=tg, w="AIM-120C")
                w.emit("crash", t + 40, i=tg, pos={"lat": 26.0, "lon": 56.0, "alt": 0})
                w.emit("pilot_dead", t + 41, i=tg)
                t += 90
        else:
            hit = 0
            for g, v in enemy_ground + statics:
                if v.get("c") == SIDE_NUM[my_side] or hit >= 4:
                    continue
                for n in range(1, min(3, v["units"]) + 1):
                    tg = unit_ref(g, v, n)
                    w.emit("shot", t, i=pl, w="AGM-65D")
                    w.emit("hit", t + 8, i=pl, tg=tg, w="AGM-65D")
                    w.emit("kill", t + 9, i=pl, tg=tg, w="AGM-65D")
                    w.emit("dead", t + 10, i=tg)
                    t += 40
                    hit += 1
    # some AI-vs-AI attrition so squadron losses appear on both sides
    for g, v in enemy_flights[1:3]:
        if rng.random() < 0.6:
            tg = unit_ref(g, v, 1)
            w.emit("crash", t + 50, i=tg)
            w.emit("eject", t + 49, i=tg, pos={"lat": 26.1, "lon": 56.1, "alt": 3000})
    t += 400
    w.emit("snapshot", t, counts={"blue": {"air": 10, "ground": 12}, "red": {"air": 8, "ground": 20}},
           players=[{**pl, "pos": {"lat": 25.5, "lon": 55.5, "alt": 5000}, "air": True}])
    if outcome == "eject":
        w.emit("hit", t + 30, i={"n": "enemy", "c": SIDE_NUM["red" if my_side == "blue" else "blue"]}, tg=pl)
        w.emit("eject", t + 40, i=pl, pos={"lat": 26.0, "lon": 56.2, "alt": 4000})
        w.emit("crash", t + 60, i=pl, pos={"lat": 26.0, "lon": 56.2, "alt": 0})
    elif outcome == "killed":
        w.emit("crash", t + 60, i=pl, pos={"lat": 26.0, "lon": 56.2, "alt": 0})
        w.emit("pilot_dead", t + 61, i=pl)
    else:
        w.emit("land", t + 1500, i=pl, place="home")
    for base, wh in (warehouses or {}).items():
        w.emit("warehouse", t + 1600, phase="end", base=base, liquids_start=wh["start"], liquids=wh["end"],
               weapons=wh.get("weapons", {}))
    w.emit("mission_end", t + 1700)
    return w.events


def manifest_with_sides(manifest: Dict[str, Any], st) -> Dict[str, Any]:
    """Add the coalition number ('c') to ground/static manifest rows from campaign state."""
    out = {}
    for g, v in manifest.items():
        v = dict(v)
        ent = st.entity(v["kind"], v["id"]) if v["kind"] != "flight" else None
        if ent is not None and getattr(ent, "coalition", None):
            v["c"] = SIDE_NUM[ent.coalition]
        elif v["kind"] == "supply_route":
            src = st.supply_nodes.get(st.supply_routes[v["id"]].src)
            v["c"] = SIDE_NUM[src.coalition] if src else 0
        out[g] = v
    return out
