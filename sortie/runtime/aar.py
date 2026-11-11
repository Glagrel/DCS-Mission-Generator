"""After-action analysis: fold raw mission events into per-flight/per-entity facts and a
human-readable timeline. Pure functions over event dicts (see SPEC section 8)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from ..mission.budget import parse_name

LOSS_EVENTS = ("dead", "crash", "lost", "pilot_dead")
GROUND_KINDS = {"gnd": "ground_unit", "sam": "sam_site", "cvy": "supply_route", "nav": "naval_group",
                "sup": "supply_node"}
KILL_CLASS = {"flt": "air", "gnd": "ground", "sam": "ground", "cvy": "ground", "nav": "naval", "sup": "structure"}
SIDE = {1: "red", 2: "blue"}


def _n(ref: Optional[Dict[str, Any]]) -> str:
    return (ref or {}).get("n") or ""


def _label(ref: Optional[Dict[str, Any]]) -> str:
    if not ref:
        return "unknown"
    who = ref.get("p") or ref.get("ty") or ref.get("n") or "unknown"
    return f"{who} ({SIDE.get(ref.get('c'), '?')})"


def _clock(t: float) -> str:
    t = int(t or 0)
    return f"{t // 3600:02d}:{t % 3600 // 60:02d}:{t % 60:02d}"


def timeline_entry(e: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """One feed line for an event, or None for events that are not shown (snapshots, etc.)."""
    ev, i, tg = e.get("ev"), e.get("i"), e.get("tg")
    if e.get("despawned"):
        return None
    text = {
        "mission_start": lambda: f"Mission started (cycle {e.get('turn')})",
        "mission_end": lambda: "Mission ended",
        "takeoff": lambda: f"{_label(i)} took off" + (f" from {e['place']}" if e.get("place") else ""),
        "land": lambda: f"{_label(i)} landed" + (f" at {e['place']}" if e.get("place") else ""),
        "kill": lambda: f"{_label(i)} destroyed {_label(tg)}" + (f" with {e['w']}" if e.get("w") else ""),
        "crash": lambda: f"{_label(i)} crashed",
        "eject": lambda: f"{_label(i)}: pilot ejected",
        "pilot_dead": lambda: f"{_label(i)}: pilot killed",
        "base_captured": lambda: f"{e.get('place', 'Airbase')} captured by {SIDE.get(e.get('c'), '?')}",
        "player_enter": lambda: f"{(i or {}).get('p', 'Player')} entered {(i or {}).get('ty', 'aircraft')}",
        "player_leave": lambda: f"{(i or {}).get('p', 'Player')} left the aircraft",
        "refuel": lambda: f"{_label(i)} refuelling",
        "spawn": lambda: f"Ground forces activated near player ({e.get('entity')})",
        "atc": lambda: e.get("text", ""),
    }.get(ev)
    if text is None:
        if ev == "dead" and i and parse_name(_n(i)) and parse_name(_n(i))[0] != "flt":
            return {"t": e.get("t", 0), "clock": _clock(e.get("t", 0)), "ev": ev, "side": SIDE.get(i.get("c")),
                    "text": f"{_label(i)} destroyed"}
        return None
    return {"t": e.get("t", 0), "clock": _clock(e.get("t", 0)), "ev": ev,
            "side": SIDE.get((i or {}).get("c")), "player": bool((i or {}).get("p")), "text": text()}


def analyze(events: List[Dict[str, Any]], manifest: Dict[str, Any], player_group: str) -> Dict[str, Any]:
    """Facts for one mission run.

    Returns {flights: {flight id: {lost, pilots_lost, ejected, kills_*, shots}},
             entities: {"kind:id": {lost, spawned}}, player: {...}, warehouses: {base id: {...}},
             captured: [{place, coalition}], timeline: [...], duration_s, ended}.
    """
    despawned: Set[str] = set()
    for e in events:
        if e.get("ev") == "despawn":
            despawned.update(e.get("units") or [])
    flights: Dict[str, Dict[str, Any]] = {}
    for name, v in manifest.items():
        if v.get("kind") == "flight":
            flights[v["id"]] = {"lost": 0, "pilots_lost": 0, "ejected": 0, "kills_air": 0, "kills_ground": 0,
                                "kills_naval": 0, "kills_structure": 0, "shots": 0, "took_off": 0, "landed": 0}
    entities: Dict[str, Dict[str, int]] = {}
    for name, v in manifest.items():
        if v.get("kind") in GROUND_KINDS.values():
            key = f"{v['kind']}:{v['id']}"
            ent = entities.setdefault(key, {"lost": 0, "spawned": 0})
            if not v.get("dead"):
                ent["spawned"] += int(v.get("units", 1))
    lead = f"{player_group} Pilot #1"
    player: Dict[str, Any] = {"unit": lead, "kills_air": 0, "kills_ground": 0, "kills_naval": 0,
                              "kills_structure": 0, "landed": False, "ejected": False, "dead": False,
                              "crashed": False, "took_off": False, "flight_time_s": 0.0, "name": None,
                              "pos": None, "landed_at": None, "entered": False}
    lost_units: Set[str] = set()
    ejected: Set[str] = set()
    dead_pilots: Set[str] = set()
    killed: Set[str] = set()                    # targets already credited through a kill event
    last_hit: Dict[str, Dict[str, Any]] = {}
    warehouses: Dict[str, Any] = {}
    captured: List[Dict[str, Any]] = []
    timeline: List[Dict[str, Any]] = []
    t_off: Optional[float] = None
    t_last = 0.0

    def credit(initiator: Optional[Dict[str, Any]], target_name: str) -> None:
        parsed_t = parse_name(target_name)
        parsed_i = parse_name(_n(initiator))
        if not parsed_t or target_name in killed:
            return
        killed.add(target_name)
        cls = KILL_CLASS.get(parsed_t[0])
        if not cls or not parsed_i or parsed_i[0] != "flt":
            return
        if parsed_i[1] in flights:
            flights[parsed_i[1]][f"kills_{cls}"] += 1
        if _n(initiator) == lead:
            player[f"kills_{cls}"] += 1

    for e in events:
        ev, i, tg = e.get("ev"), e.get("i"), e.get("tg")
        t_last = max(t_last, float(e.get("t", 0) or 0))
        name = _n(i)
        parsed = parse_name(name)
        entry = timeline_entry(e)
        if entry:
            timeline.append(entry)
        if ev == "warehouse" and e.get("base"):
            warehouses[e["base"]] = {"liquids_start": e.get("liquids_start") or {},
                                     "liquids_end": e.get("liquids") or {}, "weapons": e.get("weapons") or {},
                                     "phase": e.get("phase")}
        elif ev == "base_captured":
            captured.append({"place": e.get("place"), "coalition": SIDE.get(e.get("c"))})
        elif ev == "hit" and tg and i:
            last_hit[_n(tg)] = i
        elif ev == "kill" and tg:
            credit(i, _n(tg))
        elif ev == "shot" and parsed and parsed[0] == "flt" and parsed[1] in flights:
            flights[parsed[1]]["shots"] += 1
        elif ev == "eject" and name:
            ejected.add(name)
        elif ev in ("takeoff", "land") and parsed and parsed[0] == "flt" and parsed[1] in flights:
            flights[parsed[1]]["took_off" if ev == "takeoff" else "landed"] += 1
        if ev in LOSS_EVENTS and name and not e.get("despawned") and name not in despawned:
            if ev == "pilot_dead":
                dead_pilots.add(name)
            if name not in lost_units and parsed:
                lost_units.add(name)
                if parsed[0] == "flt" and parsed[1] in flights:
                    flights[parsed[1]]["lost"] += 1
                elif parsed[0] in GROUND_KINDS:
                    key = f"{GROUND_KINDS[parsed[0]]}:{parsed[1]}"
                    if key in entities:
                        entities[key]["lost"] += 1
                if name in last_hit:             # no kill event seen: credit the last unit that hit it
                    credit(last_hit[name], name)
        # --- the career pilot (lead seat of the player group) ---------------------------------
        if name == lead:
            if (i or {}).get("p"):
                player["name"] = i["p"]
            if ev in ("player_enter", "birth", "engine_start"):
                player["entered"] = True
            if ev == "takeoff":
                player["took_off"], player["landed"] = True, False
                t_off = t_off if t_off is not None else float(e.get("t", 0))
            elif ev == "land":
                player["landed"], player["landed_at"] = True, e.get("place")
                if t_off is not None:
                    player["flight_time_s"] += float(e.get("t", 0)) - t_off
                    t_off = None
            elif ev == "eject":
                player["ejected"], player["pos"] = True, e.get("pos")
            elif ev == "pilot_dead":
                player["dead"] = True
            elif ev == "crash":
                player["crashed"], player["pos"] = True, e.get("pos") or player["pos"]
                player["landed"] = False
    if t_off is not None:                        # still airborne when the log ended
        player["flight_time_s"] += max(0.0, t_last - t_off)
    for name in lost_units:
        parsed = parse_name(name)
        if parsed and parsed[0] == "flt" and parsed[1] in flights:
            f = flights[parsed[1]]
            if name in ejected and name not in dead_pilots:
                f["ejected"] += 1
            else:
                f["pilots_lost"] += 1
    if player["ejected"] or player["crashed"]:
        player["landed"] = False
    return {"flights": flights, "entities": entities, "player": player, "warehouses": warehouses,
            "captured": captured, "timeline": timeline, "duration_s": t_last,
            "ended": any(e.get("ev") == "mission_end" for e in events),
            "started": any(e.get("ev") == "mission_start" for e in events)}
