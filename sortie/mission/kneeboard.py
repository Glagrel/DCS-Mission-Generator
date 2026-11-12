"""In-game kneeboard pages. DCS shows every image found in the mission archive under
KNEEBOARD/<aircraft type>/IMAGES/ on that aircraft's kneeboard, so each aircraft type with a
human seat gets a flight card per flight plus a shared support/threat page."""
from __future__ import annotations

import io
import logging
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .. import measure
from ..models_ato import Ato
from ..state import State
from . import briefing

log = logging.getLogger("sortie.kneeboard")
W, H, MARGIN = 768, 1024, 28
BG, INK, DIM, ACCENT, RULE = (250, 248, 240), (20, 22, 26), (90, 96, 104), (150, 40, 30), (180, 176, 164)
FONTS = ("consola.ttf", "cour.ttf", "DejaVuSansMono.ttf", "LiberationMono-Regular.ttf")
BOLD = ("consolab.ttf", "courbd.ttf", "DejaVuSansMono-Bold.ttf", "LiberationMono-Bold.ttf")


def _font(names: Tuple[str, ...], size: int):
    from PIL import ImageFont
    for n in names:
        try:
            return ImageFont.truetype(n, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size)
    except TypeError:                     # very old Pillow
        return ImageFont.load_default()


class Page:
    def __init__(self, title: str, subtitle: str = "") -> None:
        from PIL import Image, ImageDraw
        self.img = Image.new("RGB", (W, H), BG)
        self.d = ImageDraw.Draw(self.img)
        self.f, self.fb, self.fh = _font(FONTS, 19), _font(BOLD, 19), _font(BOLD, 28)
        self.fs = _font(FONTS, 16)
        self.y = MARGIN
        self.d.text((MARGIN, self.y), title, font=self.fh, fill=INK)
        self.y += 36
        if subtitle:
            self.d.text((MARGIN, self.y), subtitle, font=self.fs, fill=DIM)
            self.y += 22
        self.rule()

    def rule(self) -> None:
        self.d.line([(MARGIN, self.y + 2), (W - MARGIN, self.y + 2)], fill=RULE, width=2)
        self.y += 10

    def heading(self, text: str) -> None:
        self.y += 6
        self.d.text((MARGIN, self.y), text.upper(), font=self.fb, fill=ACCENT)
        self.y += 26

    def line(self, text: str, bold: bool = False, small: bool = False) -> None:
        if self.y > H - MARGIN - 22:
            return
        font = self.fs if small else (self.fb if bold else self.f)
        text = self._fit(text, font)
        self.d.text((MARGIN, self.y), text, font=font, fill=INK)
        self.y += 20 if small else 24

    def kv(self, key: str, value: str) -> None:
        if self.y > H - MARGIN - 22:
            return
        self.d.text((MARGIN, self.y), key, font=self.f, fill=DIM)
        self.d.text((MARGIN + 150, self.y), self._fit(value, self.fb, W - 2 * MARGIN - 150), font=self.fb, fill=INK)
        self.y += 24

    def table(self, cols: List[Tuple[str, int]], rows: List[List[str]], small: bool = False) -> None:
        font = self.fs if small else self.f
        x = MARGIN
        for name, width in cols:
            self.d.text((x, self.y), name, font=self.fs, fill=DIM)
            x += width
        self.y += 20
        for r in rows:
            if self.y > H - MARGIN - 22:
                break
            x = MARGIN
            for (name, width), cell in zip(cols, r):
                self.d.text((x, self.y), self._fit(str(cell), font, width - 6), font=font, fill=INK)
                x += width
            self.y += 21 if small else 24

    def _fit(self, text: str, font, width: int = W - 2 * MARGIN) -> str:
        while len(text) > 3 and self.d.textlength(text, font=font) > width:
            text = text[:-2]
        return text

    def png(self) -> bytes:
        buf = io.BytesIO()
        self.img.save(buf, "PNG", optimize=True)
        return buf.getvalue()


def _freq(f: float) -> str:
    return f"{f:.3f}"


def flight_page(st: State, card: Dict[str, Any], brief: Dict[str, Any], seats: Dict[str, Any]) -> bytes:
    p = Page(f"{card['callsign']}  {card['task']}",
             f"SORTIE cycle {brief['turn']} | {card['count']} x {card['aircraft']} | {card['squadron']} | {card['base']}")
    p.kv("Package", f"{card['package']}  target {card['target']}")
    p.kv("Take-off", card["takeoff"])
    p.kv("TOT", card["tot"])
    p.kv("Radio", _freq(card["freq"]) + " AM")
    if card.get("mode3"):
        p.kv("IFF M3 / Laser", f"{card['mode3']}  /  {card['laser']}")
    if card.get("bingo"):
        p.kv("Bingo / Joker", f"{card['bingo']}  /  {card['joker']}")
    stn = brief.get("stn", {}).get(card["id"])
    if stn:
        p.kv(card.get("link") or "Datalink", f"lead STN {stn}")
    p.kv("Target", card.get("target_ddm", ""))
    for note in brief.get("weapon_notes", {}).get(card["id"], [])[:3]:
        p.line("Weather swap: " + note, small=True)
    if seats:
        p.kv("Your seats", "aircraft " + ", ".join(str(n) for n in seats.get("positions", [])))
    p.line(card["objective"], small=True)
    p.heading("Route")
    rows = [[str(i), w["name"], w["time"][:5], w["hdg"], w["leg"], w["alt"], w["speed"]]
            for i, w in enumerate(card["waypoints"])]
    p.table([("#", 34), ("WPT", 110), ("TIME", 80), ("HDG", 64), ("LEG", 96), ("ALT", 150), ("SPD", 120)], rows)
    p.heading("Coordinates")
    p.table([("#", 34), ("WPT", 130), ("LAT", 200), ("LON", 210)],
            [[str(i), w["name"], *measure.ddm(w["lat"], w["lon"])] for i, w in enumerate(card["waypoints"])],
            small=True)
    if card["stores"]:
        p.heading("Loadout")
        for s in card["stores"][:8]:
            p.line(s, small=True)
    return p.png()


def support_page(st: State, brief: Dict[str, Any], units: str) -> bytes:
    p = Page("SUPPORT / THREATS", f"SORTIE cycle {brief['turn']} | mission starts {brief['mission_start']}")
    p.heading("Package " + brief["package"]["id"])
    p.table([("CALLSIGN", 170), ("TYPE", 170), ("TASK", 100), ("FREQ", 100), ("M3", 70), ("STN", 80)],
            [[r["callsign"], f"{r['count']} x {r['aircraft']}", r["task"], _freq(r["freq"]), r.get("mode3") or "-",
              brief.get("stn", {}).get(r["id"], "-")]
             for r in brief["package"]["flights"]], small=True)
    p.heading("Support")
    rows = [[("RCVY TKR" if t.get("recovery") else "TANKER"), t["callsign"], _freq(t["freq"]),
             t.get("tacan", "-") or "-", t["alt"]] for t in brief["tankers"]]
    rows += [["AWACS", a["callsign"], _freq(a["freq"]), "-", "-"] for a in brief["awacs"]]
    if brief.get("gci"):
        rows.append(["GCI", brief["gci"].get("callsign", "GCI"), _freq(brief["gci"]["freq"]), "-", "-"])
    rows += [["JTAC", j["callsign"], f"{j['freq']:.3f} AM", "-", f"LASER {j['code']}"] for j in brief.get("jtacs") or []]
    if rows:
        p.table([("ROLE", 120), ("CALLSIGN", 190), ("FREQ", 110), ("TACAN", 90), ("ALT", 150)], rows, small=True)
    else:
        p.line("None this cycle.", small=True)
    if brief["target"].get("bullseye"):
        p.kv("Tgt bullseye", brief["target"]["bullseye"])
    if brief.get("nav_lines"):
        p.heading("Home: " + str(brief["nav"].get("name", "")))
        for line in brief["nav_lines"][:8]:
            p.line(line, small=True)
    p.heading("Air defences near route")
    sams = brief["threats"]["sams"]
    if sams:
        p.table([("TYPE", 110), ("SITE", 300), ("RANGE", 110), ("FROM ROUTE", 170)],
                [[s["type"], s["name"], s["range"], s["dist"] + (" IN" if s["inside"] else "")] for s in sams[:9]],
                small=True)
    else:
        p.line("None known.", small=True)
    air = brief["threats"]["air"]
    p.heading("Expected air opposition")
    if air:
        for a in air[:5]:
            p.line(f"{a['count']} x {a['aircraft']} ({a['task']}) near {a['near']}", small=True)
    else:
        p.line("None expected.", small=True)
    if brief["weather_text"]:
        p.heading("Weather")
        p.line(brief["weather_text"], small=True)
    return p.png()


def pages(st: State, ato: Ato, brief: Dict[str, Any], slot_list: List[Dict[str, Any]], t0: float,
          units: str) -> List[Tuple[str, bytes]]:
    """[(archive path, png bytes)] for every aircraft type that has a human seat."""
    out: List[Tuple[str, bytes]] = []
    by_type: Dict[str, List[Dict[str, Any]]] = {}
    for s in slot_list:
        by_type.setdefault(s["aircraft"], []).append(s)
    shared = support_page(st, brief, units)
    for actype, rows in by_type.items():
        folder = f"KNEEBOARD/{actype}/IMAGES"
        for n, s in enumerate(rows, start=1):
            _, flt = ato.find_flight(s["flight_id"])
            card = briefing.flight_card(st, ato, flt, t0, units)
            out.append((f"{folder}/SORTIE_{n:02d}_flight.png", flight_page(st, card, brief, s)))
        out.append((f"{folder}/SORTIE_90_support.png", shared))
    return out


def attach(m, st: State, ato: Ato, brief: Dict[str, Any], slot_list: List[Dict[str, Any]], t0: float,
           units: str, warnings: List[str]) -> None:
    """Render the pages and remember them on the mission object; `write` adds them after save."""
    try:
        m.sortie_kneeboard = pages(st, ato, brief, slot_list, t0, measure.norm(units))
    except Exception as exc:               # a missing font/Pillow must not stop mission generation
        m.sortie_kneeboard = []
        warnings.append(f"Kneeboard pages could not be generated: {exc}")
        log.warning("kneeboard failed: %s", exc)


def write(m, path: Path) -> List[str]:
    """Append the rendered pages to the saved .miz. Returns the archive paths written."""
    items = getattr(m, "sortie_kneeboard", [])
    if not items:
        return []
    with zipfile.ZipFile(path, "a", compression=zipfile.ZIP_DEFLATED) as z:
        for arc, data in items:
            z.writestr(arc, data)
    return [arc for arc, _ in items]
