"""Auto-detection of DCS Saved Games and install folders (read-only probing)."""
from __future__ import annotations

import os
import string
from pathlib import Path
from typing import Iterable, Optional

SAVED_GAMES_CANDIDATES = ("DCS.openbeta", "DCS", "DCS.openalpha")
INSTALL_SUFFIXES = (
    r"Program Files\Eagle Dynamics\DCS World",
    r"Program Files\Eagle Dynamics\DCS World OpenBeta",
    r"Eagle Dynamics\DCS World",
    r"Eagle Dynamics\DCS World OpenBeta",
    r"DCS World",
    r"DCS World OpenBeta",
    r"Program Files (x86)\Steam\steamapps\common\DCSWorld",
    r"SteamLibrary\steamapps\common\DCSWorld",
    r"Steam\steamapps\common\DCSWorld",
)
REGISTRY_KEYS = (
    r"Software\Eagle Dynamics\DCS World",
    r"Software\Eagle Dynamics\DCS World OpenBeta",
    r"Software\Eagle Dynamics\DCS World OpenAlpha",
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def saved_games_root() -> Path:
    return Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Saved Games"


def detect_saved_games(root: Optional[Path] = None) -> Optional[Path]:
    """Pick the candidate folder with the newest Logs/dcs.log; else first existing."""
    root = root or saved_games_root()
    best, best_mtime, first = None, -1.0, None
    for name in SAVED_GAMES_CANDIDATES:
        folder = root / name
        if not folder.is_dir():
            continue
        first = first or folder
        log = folder / "Logs" / "dcs.log"
        if log.is_file() and log.stat().st_mtime > best_mtime:
            best, best_mtime = folder, log.stat().st_mtime
    return best or first


def is_dcs_install(path: Path) -> bool:
    return any((path / b / "DCS.exe").is_file() for b in ("bin", "bin-mt"))


def _registry_paths() -> Iterable[Path]:
    try:
        import winreg
    except ImportError:  # non-Windows (tests)
        return
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for key in REGISTRY_KEYS:
            try:
                with winreg.OpenKey(hive, key) as k:
                    value, _ = winreg.QueryValueEx(k, "Path")
                    yield Path(value)
            except OSError:
                continue


def _drive_roots() -> Iterable[Path]:
    for letter in string.ascii_uppercase:
        root = Path(f"{letter}:\\")
        try:
            if root.exists():
                yield root
        except OSError:
            continue


def detect_install(extra: Iterable[Path] = (), roots: Optional[Iterable[Path]] = None,
                   use_registry: bool = True) -> Optional[Path]:
    """Registry first, then common paths on every drive. Validated by DCS.exe."""
    candidates = list(extra)
    if use_registry:
        candidates += list(_registry_paths())
    for root in (roots if roots is not None else _drive_roots()):
        candidates += [root / s for s in INSTALL_SUFFIXES]
    for c in candidates:
        try:
            if is_dcs_install(c):
                return c
        except OSError:
            continue
    return None


def missions_dir(saved_games: Path) -> Path:
    return saved_games / "Missions" / "SORTIE"


def runtime_dir(saved_games: Path) -> Path:
    return missions_dir(saved_games) / "runtime"


def events_file(saved_games: Path) -> Path:
    return runtime_dir(saved_games) / "events.jsonl"
