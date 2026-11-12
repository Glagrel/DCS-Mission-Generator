"""Download the optional community mission scripts SORTIE can embed into vendor/addons/.

    python tools/fetch_addons.py            # everything
    python tools/fetch_addons.py splash     # just one (splash | skynet | mist | hound)

Writes vendor/addons/SOURCE.txt with where and when each file was fetched. Nothing is
installed into DCS: missions embed the files themselves, and only when the add-on is
switched on in Settings.

The Growler AEA (EA-18G jamming) script is a DCS forum attachment, not on GitHub: download
"Growler AEA Script.lua" from
https://forum.dcs.world/topic/385186-ea-18g-style-electronic-warfare-script-v2/ and save it
as vendor/addons/Growler_AEA.lua.
"""
from __future__ import annotations

import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DEST = Path(__file__).resolve().parent.parent / "vendor" / "addons"
GH = "https://raw.githubusercontent.com"
# key: (local file name, [urls to try], text that must appear near the top, minimum size)
FILES = {
    "splash": ("Splash_Damage.lua",
               [f"{GH}/stephenpostlethwaite/DCSSplashDamageScript/master/Splash_Damage_3.4.7_Standard.lua",
                f"{GH}/stephenpostlethwaite/DCSSplashDamageScript/master/Splash_Damage_main.lua"],
               "splash_damage_options", 100_000),
    "mist": ("mist.lua", [f"{GH}/walder/Skynet-IADS/master/demo-missions/mist_4_5_107.lua"], "mist", 200_000),
    "skynet": ("skynet-iads-compiled.lua",
               [f"{GH}/walder/Skynet-IADS/master/demo-missions/skynet-iads-compiled.lua"], "Skynet", 50_000),
    "hound": ("HoundElint.lua", [f"{GH}/uriba107/dcs-hound/main/include/HoundElint.lua"], "HOUND", 200_000),
}


def fetch_one(key: str, dest: Path = DEST) -> str:
    name, urls, marker, min_size = FILES[key]
    last = None
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "sortie-setup"})
            with urllib.request.urlopen(req, timeout=120) as r:
                data = r.read()
            if len(data) < min_size or marker.encode() not in data[:400_000]:
                raise RuntimeError(f"download does not look like {name}")
            dest.mkdir(parents=True, exist_ok=True)
            (dest / name).write_bytes(data)
            print(f"{key}: saved {dest / name} ({len(data) / 1e3:.0f} kB)")
            return f"{name}\tsource: {url}\tretrieved: {datetime.now(timezone.utc).isoformat()}\tbytes: {len(data)}"
        except Exception as exc:
            last = exc
    raise RuntimeError(f"{key}: could not download ({last})")


def fetch(keys=None, dest: Path = DEST) -> None:
    keys = keys or list(FILES)
    src = dest / "SOURCE.txt"
    lines = {ln.split("\t", 1)[0]: ln for ln in src.read_text(encoding="utf-8").splitlines()} if src.is_file() else {}
    failed = []
    for k in keys:
        try:
            line = fetch_one(k, dest)
            lines[line.split("\t", 1)[0]] = line
        except Exception as exc:
            failed.append(str(exc))
    dest.mkdir(parents=True, exist_ok=True)
    src.write_text("\n".join(lines.values()) + "\n", encoding="utf-8")
    if failed:
        raise SystemExit("\n".join(failed))


if __name__ == "__main__":
    fetch(sys.argv[1:] or None)
