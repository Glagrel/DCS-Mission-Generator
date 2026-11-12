"""MissionScripting.lua status and the desanitize / restore action behind the GUI buttons.

Nothing here runs on its own: `apply` is only called when the user presses the button. It runs
tools/install_desanitize.ps1 (backup, comment out the os/io/lfs lines, or restore), first as
the current user and, if Windows refuses the write (DCS under Program Files), again elevated,
which shows the normal Windows UAC prompt.
"""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import config, paths

log = logging.getLogger("sortie.sanitize")
SCRIPT = paths.PROJECT_ROOT / "tools" / "install_desanitize.ps1"
MODULES = ("os", "io", "lfs")
NEEDED = ("io", "lfs")                 # what SORTIE needs to write its event file
_LINE = re.compile(r"^\s*sanitizeModule\(\s*['\"](\w+)['\"]\s*\)")
_CMD = re.compile(r'Command line:\s*"([^"]+?)[\\/]bin(?:-mt)?[\\/]DCS(?:_server)?\.exe"', re.I)


def status(install: Path) -> Dict[str, Any]:
    """{'path', 'exists', 'state': desanitized|sanitized|missing, 'blocked': [...], 'backup': bool}."""
    install = Path(install)
    target = install / "Scripts" / "MissionScripting.lua"
    out: Dict[str, Any] = {"path": str(install), "file": str(target), "exists": target.is_file(),
                           "state": "missing", "blocked": [], "backup": False}
    if not target.is_file():
        return out
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        out["error"] = str(exc)
        return out
    blocked = []
    for line in text.splitlines():
        m = _LINE.match(line)                    # commented-out lines do not match (they start with --)
        if m and m.group(1) in MODULES:
            blocked.append(m.group(1))
    out["blocked"] = blocked
    out["state"] = "sanitized" if set(blocked) & set(NEEDED) else "desanitized"
    out["backup"] = Path(str(target) + ".sortie-backup").is_file()
    return out


def install_from_log(log_file: Path) -> Optional[Path]:
    """The DCS install a Saved Games profile was last started with (from its dcs.log)."""
    try:
        with open(log_file, encoding="utf-8", errors="replace") as f:
            head = f.read(20000)
    except OSError:
        return None
    m = _CMD.search(head)
    return Path(m.group(1)) if m else None


def installs(settings: config.Settings) -> List[Dict[str, Any]]:
    """Every DCS install that matters, with what it is used for and its sanitize status."""
    found: Dict[str, Dict[str, Any]] = {}

    def add(path: Optional[Path], use: str) -> None:
        if path is None:
            return
        try:
            if not paths.is_dcs_install(path):
                return
        except OSError:
            return
        key = str(path).rstrip("\\/").lower()
        entry = found.setdefault(key, {"path": str(path), "uses": []})
        if use not in entry["uses"]:
            entry["uses"].append(use)

    add(config.resolved_install(settings), "game")
    for logf in config.dcs_log_candidates(settings):
        profile = logf.parent.parent.name
        use = "dedicated server (" + profile + ")" if "server" in profile.lower() or "dedicated" in profile.lower() \
            else "game (" + profile + ")"
        add(install_from_log(logf), use)
    return [{**e, **status(Path(e["path"]))} for e in found.values()]


def needs_attention(settings: config.Settings) -> List[Dict[str, Any]]:
    return [i for i in installs(settings) if i["state"] == "sanitized"]


def _powershell() -> Optional[str]:
    return shutil.which("powershell") or shutil.which("pwsh")


def apply(install: Path, undo: bool = False, allow_elevation: bool = True) -> Dict[str, Any]:
    """Run the desanitize script for one install. Returns {'ok', 'state', 'output', 'elevated'}."""
    exe = _powershell()
    if not exe:
        return {"ok": False, "output": "PowerShell was not found.", "elevated": False, **status(install)}
    args = ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT), "-DcsPath", str(install)]
    if undo:
        args.append("-Undo")
    want = "sanitized" if undo else "desanitized"
    proc = subprocess.run([exe, *args], capture_output=True, text=True, timeout=120)
    output = (proc.stdout or "") + (proc.stderr or "")
    st = status(install)
    elevated = False
    if st["state"] != want and allow_elevation and "cannot" in output.lower():
        # Windows refused the write (DCS under Program Files): ask for administrator rights.
        elevated = True
        quoted = " ".join(f'"{a}"' if " " in a else a for a in args)
        try:
            subprocess.run([exe, "-NoProfile", "-Command",
                            f"Start-Process -FilePath '{exe}' -Verb RunAs -Wait -WindowStyle Hidden "
                            f"-ArgumentList '{quoted.replace(chr(39), chr(39) * 2)}'"],
                           capture_output=True, text=True, timeout=180)
        except subprocess.TimeoutExpired:
            output += "\nThe administrator prompt was not answered in time."
        st = status(install)
        if st["state"] != want:
            output += "\nThe change was not applied (was the Windows administrator prompt declined?)."
    ok = st["state"] == want
    log.info("desanitize %s on %s: %s", "undo" if undo else "apply", install, "ok" if ok else "failed")
    return {"ok": ok, "output": output.strip(), "elevated": elevated, **st}
