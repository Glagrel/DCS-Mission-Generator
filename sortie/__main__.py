"""Command line entry point:  python -m sortie <gui|doctor|simulate>"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import webbrowser

from . import config, logs, paths, terrain


def doctor() -> int:
    """Print what SORTIE detected. Read-only."""
    s = config.load_settings()
    sg, inst = config.resolved_saved_games(s), config.resolved_install(s)
    from .mission import scripts
    ram = config.total_ram_gb()
    rows = [
        ("Saved Games", sg or "NOT FOUND (set it in Settings)"),
        ("DCS install", inst or "NOT FOUND (set it in Settings; loadouts need it)"),
        ("Mission output", config.resolved_output_dir(s)),
        ("Event file", config.resolved_runtime_dir(s) / "events.jsonl"),
        ("RAM / profile", f"{ram:.1f} GB -> {config.resolve_profile(s)}"),
        ("MOOSE", scripts.MOOSE_FILE if scripts.MOOSE_FILE.is_file()
         else f"missing - run tools\\fetch_moose.py or place Moose_.lua at {scripts.MOOSE_FILE}"),
        ("Terrains", ", ".join(k + ("" if not terrain.is_fallback(k) else " (fallback)")
                               for k in terrain.TERRAINS if terrain.is_supported(k))),
    ]
    if inst:
        ms = inst / "Scripts" / "MissionScripting.lua"
        state = "not found"
        if ms.is_file():
            text = ms.read_text(encoding="utf-8", errors="replace")
            live = [ln for ln in text.splitlines()
                    if "sanitizeModule(" in ln and not ln.strip().startswith("--") and "function" not in ln]
            names = [n for n in ("os", "io", "lfs") if any(f"'{n}'" in ln or f'"{n}"' in ln for ln in live)]
            state = "desanitised (io/lfs available)" if not {"io", "lfs"} & set(names) else \
                "SANITISED - run tools\\install_desanitize.ps1 (events will only reach dcs.log)"
        rows.append(("MissionScripting", state))
    for k, v in rows:
        print(f"{k:<17} {v}")
    return 0


def gui(host: str, port: int, open_browser: bool) -> int:
    import uvicorn
    from .web.app import create_app
    logs.setup("INFO", paths.PROJECT_ROOT / "campaigns" / "sortie.log.jsonl")
    url = f"http://{host}:{port}"
    if open_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    print(f"SORTIE GUI on {url}  (Ctrl+C to stop)")
    uvicorn.run(create_app(), host=host, port=port, log_level="warning")
    return 0


def simulate(campaign_id: str, outcome: str) -> int:
    """Write synthetic events for the current sortie to the runtime event file (no DCS needed)."""
    from .db import Store
    from .runtime import simulate as sim
    from .service import Service
    s = config.load_settings()
    svc = Service(Store(s.db_path), s)
    st = svc.state(campaign_id)
    if not st.sortie or not st.sortie.summary.get("sortie_id"):
        print("Generate a mission for this campaign first.")
        return 1
    man = sim.manifest_with_sides(st.sortie.summary["manifest"], st)
    events = sim.simulate(man, st.sortie.summary["sortie_id"], st.sortie.summary["player_group"],
                          st.meta.turn, outcome=outcome)
    path = svc.events_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    print(f"{len(events)} synthetic events written to {path}")
    return 0


def import_log(campaign_id: str, path: str) -> int:
    """Load events for the current sortie from an events.jsonl copy or a dcs.log (SORTIE_EVT lines)."""
    from pathlib import Path
    from .db import Store
    from .service import Service
    s = config.load_settings()
    svc = Service(Store(s.db_path), s)
    n = svc.import_events(campaign_id, Path(path))
    print(f"{n} new events imported. Now use 'End sortie & debrief' in the GUI.")
    return 0 if n else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="sortie", description="SORTIE dynamic campaign for DCS World")
    sub = ap.add_subparsers(dest="cmd")
    g = sub.add_parser("gui", help="start the web GUI")
    g.add_argument("--host", default="127.0.0.1")
    g.add_argument("--port", type=int, default=8765)
    g.add_argument("--no-browser", action="store_true")
    sub.add_parser("doctor", help="show detected paths and setup problems")
    sm = sub.add_parser("simulate", help="write synthetic mission events for testing without DCS")
    sm.add_argument("campaign_id")
    sm.add_argument("--outcome", default="success", choices=["success", "fail", "eject", "killed", "no_takeoff"])
    il = sub.add_parser("import-log", help="import mission events from dcs.log or an events.jsonl copy")
    il.add_argument("campaign_id")
    il.add_argument("path")
    a = ap.parse_args(argv)
    if a.cmd == "import-log":
        return import_log(a.campaign_id, a.path)
    if a.cmd == "doctor":
        return doctor()
    if a.cmd == "simulate":
        return simulate(a.campaign_id, a.outcome)
    if a.cmd in (None, "gui"):
        return gui(getattr(a, "host", "127.0.0.1"), getattr(a, "port", 8765), not getattr(a, "no_browser", False))
    return 2


if __name__ == "__main__":
    sys.exit(main())
