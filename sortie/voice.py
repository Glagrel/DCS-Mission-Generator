"""SRS voice: where the SRS speech tool lives, whether voice can work, and a test transmission.

In the mission, MOOSE MSRS starts SRS's `DCS-SR-ExternalAudio.exe` once per message. That
program joins the SRS server as a client, speaks, and leaves again - so the controller only
shows up in the SRS client list while it is talking. `check` looks at every link of that chain
from outside DCS; `speak` runs the same program the same way so the chain can be heard working
without flying a mission.
"""
from __future__ import annotations

import logging
import re
import socket
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import config, sanitize
from .mission import scripts

log = logging.getLogger("sortie.voice")
EXE = "DCS-SR-ExternalAudio.exe"
SUBDIRS = ("", "ExternalAudio")          # SRS 1.x keeps the tool in the root, SRS 2.x in ExternalAudio
MSRS_NEEDS = ("os", "io")                # modules MSRS needs un-sanitised to start the tool
TEST_TEXT = "SORTIE radio check. If you can hear this, voice is working."


def audio_dir(srs_path: str) -> Path:
    """The folder that holds the SRS speech tool: the given folder or its ExternalAudio subfolder.
    Falls back to the folder as given when the tool is in neither (another PC hosts the mission)."""
    root = Path(str(srs_path).strip().strip('"').rstrip("\\/") or ".")
    for sub in SUBDIRS:
        try:
            if (root / sub / EXE).is_file():
                return root / sub
        except OSError:
            break
    return root


def exe_path(settings: config.Settings) -> Optional[Path]:
    exe = audio_dir(settings.srs_path) / EXE
    return exe if exe.is_file() else None


def server_listening(port: int, host: str = "127.0.0.1", timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except (OSError, ValueError):
        return False


def check(settings: config.Settings) -> Dict[str, Any]:
    """Every link voice needs, as rows for the GUI, plus the problems that will keep it silent."""
    wanted = bool(settings.atc_enabled and settings.voice in config.VOICE_ENGINES and settings.voice != "off")
    exe = exe_path(settings)
    up = server_listening(settings.srs_port)
    blocked = [(i["path"], [m for m in i.get("blocked", []) if m in MSRS_NEEDS])
               for i in sanitize.installs(settings) if i.get("exists")]
    blocked = [(p, b) for p, b in blocked if b]
    google_ok = settings.voice != "google" or Path(settings.google_credentials or "?").is_file()
    problems: List[str] = []
    if not exe:
        problems.append(f"SRS speech tool {EXE} was not found in {settings.srs_path} (or its ExternalAudio "
                        "folder). Set the SRS install folder in Settings.")
    if not scripts.MOOSE_FILE.is_file():
        problems.append("MOOSE is missing (run tools\\fetch_moose.py): the mission cannot speak without it.")
    for path, mods in blocked:
        problems.append(f"Mission scripts are sanitised in {path} ({', '.join(mods)} blocked): MOOSE cannot start "
                        "the SRS speech tool. Use Desanitize in Settings.")
    if not google_ok:
        problems.append("Google voice is selected but the credentials JSON file was not found.")
    notes = [] if up else [f"No SRS server is listening on port {settings.srs_port} on this PC right now. "
                           "Start the SRS server before the mission (voice needs it; text still works)."]
    if settings.voice == "piper":
        notes.append("Piper is not supported by MOOSE; the Windows voice is used instead.")
    return {
        "wanted": wanted, "engine": settings.voice, "atc_enabled": settings.atc_enabled,
        "exe": str(exe) if exe else None, "audio_dir": str(audio_dir(settings.srs_path)),
        "port": settings.srs_port, "server_up": up, "moose": scripts.MOOSE_FILE.is_file(),
        "blocked": [{"path": p, "modules": b} for p, b in blocked],
        "problems": problems, "notes": notes, "ready": not problems,
    }


def warnings_for_mission(settings: config.Settings) -> List[str]:
    """What to tell the pilot after generating a mission that asks for voice."""
    c = check(settings)
    if not c["wanted"]:
        return []
    return ["Voice: " + p for p in c["problems"]] + ["Voice: " + n for n in c["notes"] if "SRS server" in n]


def command(settings: config.Settings, text: str, freqs: List[float], coalition: int = 2,
            label: str = "SORTIE") -> List[str]:
    """The SRS speech tool command line, with the same switches MOOSE MSRS uses in the mission."""
    exe = exe_path(settings)
    if exe is None:
        raise FileNotFoundError(f"{EXE} not found in {settings.srs_path}")
    cmd = [str(exe), "-f", ",".join(f"{f:g}" for f in freqs), "-m", ",".join("AM" for _ in freqs),
           "-c", str(int(coalition)), "-p", str(int(settings.srs_port)),
           "-n", re.sub(r"[^A-Za-z0-9_-]", "", label) or "SORTIE", "-v", "1.0", "-l", "en-US",
           "--text=" + text]
    if settings.voice == "google" and settings.google_credentials:
        cmd += ["-G", settings.google_credentials]
    return cmd


def speak(settings: config.Settings, text: str = TEST_TEXT, freqs: Optional[List[float]] = None,
          coalition: int = 2, timeout: float = 60.0) -> Dict[str, Any]:
    """Say `text` on the SRS server of this PC. Returns {'ok', 'message', 'output'}."""
    freqs = freqs or [251.0]
    text = " ".join(str(text).replace('"', "'").split())[:300] or TEST_TEXT
    if exe_path(settings) is None:
        return {"ok": False, "message": f"{EXE} was not found in {settings.srs_path}.", "output": ""}
    if not server_listening(settings.srs_port):
        return {"ok": False, "output": "",
                "message": f"No SRS server is listening on port {settings.srs_port} on this PC. Start the SRS "
                           "server (SRS-Server.exe), connect your SRS client to 127.0.0.1 and try again."}
    cmd = command(settings, text, freqs, coalition)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=str(Path(cmd[0]).parent),
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        return {"ok": False, "message": "The SRS speech tool did not finish in time.", "output": ""}
    except OSError as exc:
        return {"ok": False, "message": f"Could not start the SRS speech tool: {exc}", "output": ""}
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    sent = "Finished Sending Audio" in out
    ok = sent or (proc.returncode == 0 and "rror" not in out)
    log.info("voice test on %s: %s", freqs, "sent" if ok else "failed")
    side = {1: "red", 2: "blue"}.get(int(coalition), "spectator")
    shown = ", ".join(f"{f:.3f}" for f in freqs)
    return {"ok": ok, "output": "\n".join(out.splitlines()[-12:]),
            "message": (f"Spoken on {shown} MHz AM ({side}). You hear it only if your SRS client is connected to "
                        "this server with a radio tuned to that frequency.") if ok
            else "The SRS speech tool reported a problem (details below)."}
