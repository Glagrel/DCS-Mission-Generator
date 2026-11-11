"""ATC/GCI layer configuration handed to sortie_atc.lua (feature flag, default OFF)."""
from __future__ import annotations

from typing import Any, Dict

from .. import config
from ..models_ato import Ato
from ..state import State
from . import procedures


def build(st: State, ato: Ato, settings: config.Settings, manifest: Dict[str, Any]) -> Dict[str, Any]:
    if not settings.atc_enabled:
        return {"enabled": False}
    side = st.meta.player_side
    proc = procedures.procedure_set(st.meta.doctrine.get(side, "nato"), st.meta.era_kind)
    pkg, flt = ato.find_flight(ato.player_flight_id or "")
    sup = ato.support.get(side, {})
    be = st.meta.bullseye.get(side)
    base = st.airbases[st.squadrons[flt.squadron_id].airbase_id] if flt else None
    voice = settings.voice if settings.voice in config.VOICE_ENGINES else "off"
    features = procedures.features(proc, st.meta.capabilities.get(side, []))
    awacs = (sup.get("awacs") or [None])[0]
    tankers = sup.get("tankers") or []
    return {
        "enabled": True, "procedure": proc, "voice": voice, "features": features,
        "phrases": procedures.PHRASES[proc],
        "srs": {"path": settings.srs_path, "port": settings.srs_port, "piper_voice": settings.piper_voice,
                "google_credentials": settings.google_credentials,
                "culture": "en-US" if proc != "soviet" else "en-GB"},
        "coalition": 2 if side == "blue" else 1,
        "bullseye": {"lat": be.lat, "lon": be.lon} if be else None,
        "home": {"name": base.dcs_name or base.name, "kind": base.kind, "freq": flt.freq} if base else None,
        "controller": {
            "callsign": (awacs or {}).get("callsign") or procedures.gci_callsign(proc),
            "freq": (awacs or sup.get("gci") or {}).get("freq", flt.freq if flt else 0),
            "awacs_group": _group(manifest, (awacs or {}).get("flight_id")),
        },
        "tankers": [{"callsign": t["callsign"], "freq": t["freq"], "tacan": t.get("tacan"),
                     "group": _group(manifest, t.get("flight_id"))} for t in tankers],
        "picture_interval": 120, "threat_range_m": procedures.THREAT_RANGE_M[proc],
        "units": "metric" if proc == "soviet" else "imperial",
    }


def _group(manifest: Dict[str, Any], flight_id) -> Any:
    for name, v in manifest.items():
        if v.get("kind") == "flight" and v.get("id") == flight_id:
            return name
    return None
