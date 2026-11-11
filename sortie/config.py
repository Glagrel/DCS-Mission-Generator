"""User settings (config/settings.json) merged over tunable defaults (config/defaults.yaml)."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field

from . import paths

DEFAULTS_FILE = paths.PROJECT_ROOT / "config" / "defaults.yaml"
SETTINGS_FILE = paths.PROJECT_ROOT / "config" / "settings.json"
PROFILE_NAMES = ("light", "standard", "heavy")
VOICE_ENGINES = ("off", "windows", "piper", "google")


class Settings(BaseModel):
    saved_games: Optional[str] = None        # None = auto-detect
    dcs_install: Optional[str] = None        # None = auto-detect
    output_dir: Optional[str] = None         # None = <SavedGames>/Missions/SORTIE
    db_path: str = str(paths.PROJECT_ROOT / "campaigns" / "sortie.db")
    owned_modules: Optional[List[str]] = None  # None = all flyable
    profile: str = "auto"                    # auto | light | standard | heavy
    coop_slots: int = 1
    atc_enabled: bool = False
    voice: str = "off"
    srs_path: str = r"C:\Program Files\DCS-SimpleRadio-Standalone"
    srs_port: int = 5002
    piper_voice: str = ""
    google_credentials: str = ""
    overrides: Dict[str, Any] = Field(default_factory=dict)  # deep-merged over defaults.yaml


@lru_cache(maxsize=1)
def _raw_defaults() -> Dict[str, Any]:
    with open(DEFAULTS_FILE, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _deep_merge(base: Dict[str, Any], over: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for k, v in over.items():
        out[k] = _deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load_settings(path: Path = SETTINGS_FILE) -> Settings:
    if path.is_file():
        return Settings(**json.loads(path.read_text(encoding="utf-8")))
    return Settings()


def save_settings(s: Settings, path: Path = SETTINGS_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(s.model_dump(), indent=2), encoding="utf-8")


def defaults(settings: Optional[Settings] = None) -> Dict[str, Any]:
    """Tunable numbers with the user's overrides applied."""
    d = _raw_defaults()
    return _deep_merge(d, settings.overrides) if settings and settings.overrides else d


def total_ram_gb() -> float:
    try:
        import psutil
        return psutil.virtual_memory().total / 2 ** 30
    except Exception:
        return 16.0


def profile_for_ram(ram_gb: float, d: Optional[Dict[str, Any]] = None) -> str:
    th = (d or _raw_defaults())["ram_thresholds_gb"]
    if ram_gb <= th["light_max"]:
        return "light"
    return "standard" if ram_gb <= th["standard_max"] else "heavy"


def resolve_profile(settings: Settings, ram_gb: Optional[float] = None) -> str:
    if settings.profile in PROFILE_NAMES:
        return settings.profile
    return profile_for_ram(total_ram_gb() if ram_gb is None else ram_gb, defaults(settings))


def profile_limits(name: str, settings: Optional[Settings] = None) -> Dict[str, Any]:
    return dict(defaults(settings)["profiles"][name])


def resolved_saved_games(settings: Settings) -> Optional[Path]:
    return Path(settings.saved_games) if settings.saved_games else paths.detect_saved_games()


def resolved_install(settings: Settings) -> Optional[Path]:
    return Path(settings.dcs_install) if settings.dcs_install else paths.detect_install()


def resolved_output_dir(settings: Settings) -> Path:
    if settings.output_dir:
        return Path(settings.output_dir)
    sg = resolved_saved_games(settings)
    return paths.missions_dir(sg) if sg else paths.PROJECT_ROOT / "out"


def resolved_runtime_dir(settings: Settings) -> Path:
    sg = resolved_saved_games(settings)
    return paths.runtime_dir(sg) if sg else paths.PROJECT_ROOT / "out" / "runtime"
