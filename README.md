# SORTIE

A Falcon BMS-style dynamic campaign for DCS World. A Python engine runs a persistent war
(air tasking, logistics, attrition, front lines); DCS is used to fly one sortie at a time.
You are a line pilot: **the ATO assigns your mission, you never pick it.**

> **Status.** Everything that can run without DCS is implemented and covered by an automated
> test suite (`pytest`, 135 tests). **Nothing has been flown in DCS yet.** The generated
> missions load back into pydcs and the Lua runs under a real Lua 5.1 interpreter against a
> mocked DCS API, but in-sim behaviour is unverified. Work through
> [docs/TEST_IN_DCS.md](docs/TEST_IN_DCS.md) and read [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md).

## How it works

```
career wizard ─► ATO for the cycle ─► your flight is assigned ─► .miz generated
     ▲                                                                │ fly it in DCS
     │                                                                ▼
 war advances (supply, production, repair, fronts) ◄── debrief: events.jsonl ─► losses, damage,
                                                       warehouses, career, rest of ATO resolved
```

| Part | Where |
|---|---|
| Campaign state (SQLite, pydantic) | `sortie/models.py`, `db.py`, `state.py` |
| Theater templates (YAML) | `data/theaters/` — Cold War 1985, Forager 1944, Persian Gulf |
| War simulator | `sortie/sim/` |
| ATO, routes, radio plan, player assignment | `sortie/ato/` |
| Mission builder (pydcs) | `sortie/mission/` |
| In-mission Lua (events, warehouses, proximity spawn, ATC) | `sortie/lua/` |
| Event watcher, after-action report | `sortie/runtime/` |
| Debrief, career, reassignment | `sortie/debrief/` |
| Web GUI (FastAPI + Leaflet) | `sortie/web/` |

Architecture details: [docs/SPEC.md](docs/SPEC.md). Decisions and assumptions:
[docs/DECISIONS.md](docs/DECISIONS.md).

## Requirements

* Windows, PowerShell, Python 3.10+ (developed on 3.14), DCS World 2.9 (2.8.8+ for warehouses)
* Internet for setup (pip packages, MOOSE, map tiles). Everything except the map works offline.
* The DCS modules/terrains you want to fly: Germany (Cold War), Marianas, Persian Gulf.

## Install

```powershell
powershell -ExecutionPolicy Bypass -File tools\setup.ps1
```

This creates `.venv`, installs the dependencies, downloads MOOSE into `vendor\moose\` and
prints what it detected. It changes nothing outside the project folder.

> The DCS mission library is the PyPI package **`pydcs`** (import name `dcs`). The PyPI
> package literally called `dcs` is an unrelated tool; the setup script removes it.

Manual equivalent:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python tools\fetch_moose.py
.\.venv\Scripts\python -m sortie doctor
```

**MOOSE offline:** download `Moose_.lua` from <https://github.com/FlightControl-Master/MOOSE/releases>
and put it at `vendor\moose\Moose_.lua`. SORTIE embeds it in every mission through a
MISSION START → DO SCRIPT FILE trigger; nothing is installed into DCS. Missions still build
without it (only the optional ATC voice needs MOOSE). `vendor\moose\SOURCE.txt` records the
URL, date and commit of the copy in use.

## Let the mission write its event file (desanitize)

DCS blocks file access from mission scripts. SORTIE needs it to write
`<Saved Games>\Missions\SORTIE\runtime\events.jsonl`. Run once, **in an elevated PowerShell if
DCS is under Program Files**:

```powershell
powershell -ExecutionPolicy Bypass -File tools\install_desanitize.ps1
```

* It backs up `<DCS>\Scripts\MissionScripting.lua` to `MissionScripting.lua.sortie-backup` and
  comments out only the `sanitizeModule('os')`, `('io')`, `('lfs')` lines.
* Preview with `-DryRun`. Undo with `-Undo`. Point it at a specific install with `-DcsPath`.
* **Every DCS update or repair restores the original file — run the script again afterwards.**
  `python -m sortie doctor` tells you whether it is currently applied.
* **Co-op:** only the machine *hosting* the mission needs it.
* Security: with these lines disabled any mission you run can read/write files. Fly missions
  you trust.

Without it the scripts still run; events go to `dcs.log` as `SORTIE_EVT` lines and warehouse
readback still works, but the live feed does not (see Troubleshooting).

## First run

```powershell
tools\run.ps1          # or: .\.venv\Scripts\python -m sortie gui
```

Your browser opens <http://127.0.0.1:8765>.

1. **Settings** — check the detected *Saved Games* and *DCS install* paths. Saved Games is
   auto-detected from `DCS.openbeta`, `DCS`, `DCS.openalpha` (the one with the newest
   `Logs\dcs.log`); the install comes from the registry and common folders. Both can be
   overridden. Tick the **modules you own** — careers, transfers and reassignments only ever
   use ticked aircraft. Pick the performance profile (auto = by installed RAM).
2. **Campaigns → New career** — theater, side, squadron/aircraft (only owned, flyable, in-era
   types are offered), callsign, difficulty, profile.
3. **ATO & Briefing** — the cycle's Air Tasking Order and *your* tasking with the reason you
   got it, route, TOT, loadout, frequencies, threats, tanker/AWACS.
4. **Generate Next Mission** — writes `SORTIE_<theater>_T<cycle>.miz` to
   `<Saved Games>\Missions\SORTIE\` and shows the full path and any warnings.
5. In DCS: *Mission → My Missions → SORTIE*, fly it. Keep the GUI on **Live Mission** to watch
   the feed.
6. End the mission in DCS, then **Live Mission → End sortie & debrief**. The war advances one
   cycle (6 h) and the next ATO is issued.

"Skip this sortie" stands you down: the whole ATO is resolved abstractly.

### Co-op

Settings → *Player slots* 2–4. Your flight then has that many **Client** slots (the rest of
the flight is AI). Host the generated mission as a multiplayer server. The career follows the
pilot in slot 1 of the flight. The host needs the desanitize step.

### Performance profiles

Light / Standard / Heavy cap concurrent AI aircraft, ground groups, naval groups and the
simulation bubble around your route; everything outside is resolved abstractly. Auto picks
Light ≤ 20 GB RAM, Standard ≤ 48 GB, Heavy above. All numbers are starting guesses in
`config\defaults.yaml` — tune them.

### Testing without DCS

```powershell
.\.venv\Scripts\python -m sortie simulate <campaign id> --outcome success   # or eject, killed (id: Campaigns list)
```

writes synthetic events for the current sortie so you can try the debrief loop.

## Configuration

* `config\settings.json` — your settings (written by the GUI).
* `config\defaults.yaml` — tunable numbers: profiles, difficulty, logistics, production,
  repair, ground war, ATC. Override individual values via `"overrides"` in settings.json.
* `data\theaters\*.yaml` — one file per theater; add a file to add a theater.
  `data\unit_eras.yaml` (introduction years) and `data\sam_templates.yaml` drive era filtering.

## Optional ATC / GCI / voice (default off)

Settings → *Enable ATC/GCI layer*. Tower, check-in, picture, bogey dope, declare, threat and
merged calls, vectors to base/tanker, CSAR notice, and an F10 "SORTIE Control" menu. NATO,
Soviet-style and WWII (simple GCI vectors only) phrase sets are chosen from the theater.
Messages always appear as text; with a voice engine selected and SimpleRadio Standalone
installed they are also spoken through MOOSE MSRS (Windows or Google TTS; Piper falls back to
Windows — see Known Issues).

## Tests

```powershell
.\.venv\Scripts\python -m pytest
```

No test needs DCS or touches your DCS folders; everything runs in temp directories.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "No event file yet" on Live Mission | Run `tools\install_desanitize.ps1` (again after a DCS update); check `python -m sortie doctor`. |
| Debrief says no events found | Same as above, or the mission was not this cycle's file. Events that went to `dcs.log` can be imported: `python -m sortie import-log <campaign id> <path to dcs.log>` (the id is shown in the Campaigns list). |
| Aircraft spawn with empty pylons | DCS install not found → set it in Settings. Loadouts come from DCS's own payload files. |
| No squadron offered in the wizard | No aircraft on that side is ticked under Settings → Owned modules. |
| Map is blank | Leaflet/tiles need internet; the rest of the GUI works offline. |
| Mission not listed in DCS | Check the path shown after generation; set *Mission output folder* in Settings. |
| Wrong DCS folder detected | Override both paths in Settings. |
| Port in use | `python -m sortie gui --port 8770` |
