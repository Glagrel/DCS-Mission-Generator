"""Pilot career: ranks, awards, status changes after each sortie."""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .. import models as M

RANKS: Dict[str, List[str]] = {
    "nato": ["2nd Lieutenant", "1st Lieutenant", "Captain", "Major", "Lieutenant Colonel", "Colonel"],
    "soviet": ["Leytenant", "Starshiy Leytenant", "Kapitan", "Mayor", "Podpolkovnik", "Polkovnik"],
    "ww2_blue": ["Ensign", "Lieutenant (jg)", "Lieutenant", "Lieutenant Commander", "Commander", "Captain"],
    "ww2_red": ["Shoi", "Chui", "Taii", "Shosa", "Chusa", "Taisa"],
}
RANK_POINTS = [0, 40, 110, 220, 400, 650]          # career points needed for each rank
AWARDS: Dict[str, List[Tuple[str, str]]] = {
    # (award name, rule key) - rule keys are evaluated in check_awards
    "nato": [("Air Medal", "sorties10"), ("Distinguished Flying Cross", "ace"), ("Purple Heart", "wounded"),
             ("Silver Star", "kills3_sortie"), ("Air Force Cross", "points400")],
    "soviet": [("Medal For Combat Service", "sorties10"), ("Order of the Red Star", "ace"),
               ("Order of the Red Banner", "kills3_sortie"), ("Hero of the Soviet Union", "points400")],
    "ww2_blue": [("Air Medal", "sorties10"), ("Distinguished Flying Cross", "ace"), ("Purple Heart", "wounded"),
                 ("Navy Cross", "kills3_sortie"), ("Medal of Honor", "points400")],
    "ww2_red": [("Order of the Golden Kite 5th Class", "sorties10"), ("Order of the Golden Kite 4th Class", "ace"),
                ("Order of the Golden Kite 3rd Class", "points400")],
}


def _table(doctrine: str, side: str, era_kind: str) -> str:
    if era_kind == "ww2" or doctrine == "ww2":
        return f"ww2_{side}"
    return doctrine if doctrine in RANKS else "nato"


def rank_name(doctrine: str, side: str, index: int, era_kind: str = "modern") -> str:
    ranks = RANKS[_table(doctrine, side, era_kind)]
    return ranks[max(0, min(index, len(ranks) - 1))]


def sortie_points(player: Dict[str, Any], success: float) -> float:
    """Career points for one sortie: flying it, doing the job, kills, bringing the jet home."""
    pts = 4.0 + 10.0 * success
    pts += 6.0 * player.get("kills_air", 0) + 1.5 * player.get("kills_ground", 0)
    pts += 8.0 * player.get("kills_naval", 0) + 2.0 * player.get("kills_structure", 0)
    if player.get("landed"):
        pts += 3.0
    if player.get("ejected") or player.get("crashed"):
        pts -= 4.0
    return max(0.0, pts)


def update_career(pilot: M.Pilot, player: Dict[str, Any], success: float, turn: int, mission: str,
                  doctrine: str, side: str, era_kind: str, rng) -> Dict[str, Any]:
    """Apply one sortie's player stats. Returns {'promoted': rank|None, 'awards': [...], 'status': str}."""
    pilot.sorties += 1
    pilot.hours = round(pilot.hours + player.get("flight_time_s", 0.0) / 3600.0, 2)
    for k_src, k_dst in (("kills_air", "air"), ("kills_ground", "ground"), ("kills_naval", "naval"),
                         ("kills_structure", "structure")):
        pilot.kills[k_dst] = pilot.kills.get(k_dst, 0) + int(player.get(k_src, 0))
    if player.get("landed"):
        pilot.landings += 1
    status = "active"
    if player.get("dead"):
        status = "kia"
    elif player.get("ejected"):
        pilot.ejections += 1
        # over enemy ground an ejected pilot may be captured or go missing
        roll = rng.random()
        if player.get("ejected_over_enemy"):
            status = "pow" if roll < 0.35 else ("mia" if roll < 0.5 else "active")
        else:
            status = "wounded" if roll < 0.3 else "active"
    elif player.get("crashed") and not player.get("landed"):
        status = "kia" if rng.random() < 0.6 else "wounded"
    pts = sortie_points(player, success)
    pilot.points = round(pilot.points + pts, 1)
    pilot.status = status
    promoted = None
    new_index = max(i for i, need in enumerate(RANK_POINTS) if pilot.points >= need)
    if new_index > pilot.rank_index and status in ("active", "wounded"):
        pilot.rank_index = new_index
        pilot.rank = rank_name(doctrine, side, new_index, era_kind)
        promoted = pilot.rank
    awards = check_awards(pilot, player, doctrine, side, era_kind)
    pilot.awards.extend(awards)
    pilot.history.append({"turn": turn, "mission": mission, "success": round(success, 2), "points": round(pts, 1),
                          "kills_air": player.get("kills_air", 0), "kills_ground": player.get("kills_ground", 0),
                          "kills_naval": player.get("kills_naval", 0), "status": status,
                          "flight_time_s": player.get("flight_time_s", 0.0),
                          "aircraft": pilot.aircraft, "promoted": promoted, "awards": awards})
    return {"promoted": promoted, "awards": awards, "status": status, "points": pts}


def check_awards(pilot: M.Pilot, player: Dict[str, Any], doctrine: str, side: str, era_kind: str) -> List[str]:
    rules = {
        "sorties10": pilot.sorties >= 10,
        "ace": pilot.kills.get("air", 0) >= 5,
        "wounded": pilot.status == "wounded",
        "kills3_sortie": player.get("kills_air", 0) >= 3,
        "points400": pilot.points >= 400,
    }
    out = []
    for name, key in AWARDS[_table(doctrine, side, era_kind)]:
        repeatable = key in ("wounded", "kills3_sortie")
        if rules[key] and (repeatable or name not in pilot.awards):
            out.append(name)
    return out


def recover_status(pilot: M.Pilot) -> str:
    """Between turns: wounded pilots return to duty. KIA/POW/MIA end the career."""
    if pilot.status == "wounded":
        pilot.status = "active"
    return pilot.status
