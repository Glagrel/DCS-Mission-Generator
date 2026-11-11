"""Download the latest static MOOSE include into vendor/moose/Moose_.lua."""
from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

URLS = [
    "https://raw.githubusercontent.com/FlightControl-Master/MOOSE_INCLUDE/master/Moose_Include_Static/Moose_.lua",
    "https://raw.githubusercontent.com/FlightControl-Master/MOOSE_INCLUDE/develop/Moose_Include_Static/Moose_.lua",
]
DEST = Path(__file__).resolve().parent.parent / "vendor" / "moose" / "Moose_.lua"


def fetch(dest: Path = DEST) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    last = None
    for url in URLS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "sortie-setup"})
            with urllib.request.urlopen(req, timeout=120) as r:
                data = r.read()
            if len(data) < 500_000 or b"MOOSE" not in data[:20000]:
                raise RuntimeError("download does not look like Moose_.lua")
            dest.write_bytes(data)
            print(f"MOOSE saved to {dest} ({len(data) / 1e6:.1f} MB)")
            return dest
        except Exception as exc:  # try next mirror
            last = exc
    raise SystemExit(
        f"Could not download MOOSE ({last}).\n"
        f"Offline install: download Moose_.lua from https://github.com/FlightControl-Master/MOOSE/releases\n"
        f"and place it at: {dest}")


if __name__ == "__main__":
    fetch()
    sys.exit(0)
