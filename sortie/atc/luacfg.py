"""ATC/GCI layer configuration handed to sortie_atc.lua (feature flag, default OFF)."""
from __future__ import annotations

from typing import Any, Dict

from .. import config
from ..voice import audio_dir
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
    ctrl_freq = (awacs or sup.get("gci") or {}).get("freq", flt.freq if flt else 0)
    # Speak on the controller's frequency and on every frequency a human seat starts tuned to,
    # so calls are heard without retuning (SRS plays one transmission once per listener).
    human = [f.freq for _, f in ato.flights() if f.id in _human_flights(manifest, ato)]
    voice_freqs = list(dict.fromkeys(round(float(x), 3) for x in [ctrl_freq, flt.freq if flt else 0, *human] if x))
    return {
        "enabled": True, "procedure": proc, "voice": voice, "features": features,
        "phrases": procedures.PHRASES[proc],
        "srs": {"path": str(audio_dir(settings.srs_path)), "port": settings.srs_port, "piper_voice": settings.piper_voice,
                "google_credentials": settings.google_credentials,
                "culture": "en-US" if proc != "soviet" else "en-GB"},
        "coalition": 2 if side == "blue" else 1,
        "bullseye": {"lat": be.lat, "lon": be.lon} if be else None,
        "home": {"name": base.dcs_name or base.name, "kind": base.kind, "freq": flt.freq} if base else None,
        "controller": {
            "callsign": (awacs or {}).get("callsign") or procedures.gci_callsign(proc),
            "freq": ctrl_freq,
            "awacs_group": _group(manifest, (awacs or {}).get("flight_id")),
        },
        "tankers": [{"callsign": t["callsign"], "freq": t["freq"], "tacan": t.get("tacan"),
                     "group": _group(manifest, t.get("flight_id"))} for t in tankers],
        "picture_interval": 120, "threat_range_m": procedures.THREAT_RANGE_M[proc],
        "picture_range_m": 185000, "player_callsign": flt.callsign if flt else "Flight",
        "wind_dir": int(st.meta.weather.get("wind_dir", 0)), "wind_speed": int(st.meta.weather.get("wind_ms", 0)),
        "voice_freqs": voice_freqs,
        "use_flightcontrol": bool(config.defaults(settings)["atc"].get("use_flightcontrol", False)),
        "units": "metric" if proc == "soviet" else "imperial",
    }


def _human_flights(manifest: Dict[str, Any], ato: Ato) -> set:
    """Flight ids with a human seat: the player's flight plus flights holding co-op seats."""
    out = {ato.player_flight_id} if ato.player_flight_id else set()
    for v in manifest.values():
        if v.get("kind") == "flight" and v.get("clients"):
            out.add(v.get("id"))
    return out


def _group(manifest: Dict[str, Any], flight_id) -> Any:
    for name, v in manifest.items():
        if v.get("kind") == "flight" and v.get("id") == flight_id:
            return name
    return None
