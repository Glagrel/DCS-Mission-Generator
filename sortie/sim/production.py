"""Replacement airframes/pilots and repair of runways, nodes and air defences."""
from __future__ import annotations

from typing import Any, Dict, List

from .. import models as M
from ..state import State
from .supply import network_health


def _rate(st: State, side: str, key: str, d: Dict[str, Any], theater_prod: Dict[str, Dict[str, float]]) -> float:
    base = theater_prod.get(side, {}).get(key, d["production"][f"{key}_per_turn"])
    return base * network_health(st, side)


def replacements(st: State, d: Dict[str, Any], theater_prod: Dict[str, Dict[str, float]] | None = None,
                 ) -> Dict[str, Any]:
    """Hand out new airframes and pilots. Priority = relative deficit, player squadron first on ties."""
    theater_prod = theater_prod or {}
    report: Dict[str, Any] = {"airframes": {}, "pilots": {}}
    rng = st.rng("production")
    for side in ("blue", "red"):
        squadrons = [s for s in st.squadrons.values() if s.coalition == side
                     and st.airbases.get(s.airbase_id) is not None
                     and st.airbases[s.airbase_id].coalition == side]
        for key, have, cap in (("airframes", "airframes", "airframes_max"), ("pilots", "pilots", "pilots_max")):
            rate = _rate(st, side, key, d, theater_prod)
            n = int(rate) + (1 if rng.random() < rate - int(rate) else 0)
            for _ in range(n):
                short = [s for s in squadrons if getattr(s, have) < getattr(s, cap)]
                if not short:
                    break
                s = max(short, key=lambda q: (1 - getattr(q, have) / max(1, getattr(q, cap)), q.is_player, q.id))
                setattr(s, have, getattr(s, have) + 1)
                report[key][s.id] = report[key].get(s.id, 0) + 1
    return report


def repairs(st: State, d: Dict[str, Any]) -> Dict[str, List[str]]:
    rp = d["repair"]
    done: Dict[str, List[str]] = {"runways": [], "nodes": [], "sams": []}
    for b in st.airbases.values():
        b.hit_last_turn = False
        if b.runway_health < 1.0:
            b.runway_health = min(1.0, b.runway_health + rp["runway_per_turn"])
            done["runways"].append(b.id)
    for n in st.supply_nodes.values():
        if n.health < 1.0:
            n.health = min(1.0, n.health + rp["node_per_turn"] * (0.5 if n.health < 0.1 else 1.0))
            done["nodes"].append(n.id)
    for s in st.sam_sites.values():
        if s.health < 1.0:
            # a site that was wiped out is rebuilt slowly from reserves
            s.health = min(1.0, s.health + rp["sam_per_turn"] * (0.5 if s.health < 0.1 else 1.0)
                           * max(0.3, network_health(st, s.coalition)))
            done["sams"].append(s.id)
    for g in st.ground_units.values():
        if g.strength < 1.0 and g.supply > 0.6:
            g.strength = min(1.0, g.strength + 0.03)
    for n in st.naval_groups.values():
        if 0 < n.health < 1.0:
            n.health = min(1.0, n.health + 0.05)
    return done
