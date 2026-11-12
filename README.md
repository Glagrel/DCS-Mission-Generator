# SORTIE

A Falcon BMS-style dynamic campaign for DCS World. A Python engine runs a persistent war
(air tasking, logistics, attrition, front lines); DCS is used to fly one sortie at a time.
You are a line pilot: **the ATO assigns your mission, you never pick it.**

> **Status.** Everything that can run without DCS is implemented and covered by an automated
> test suite (`pytest`, 186 tests). **Nothing has been flown in DCS yet.** The generated
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
`<Saved Games>\Missions\SORTIE\runtime\events.jsonl` for the live feed.

**Easiest: Settings -> "Mission script file access" -> Desanitize.** It lists every DCS install in
use (game and dedicated server), shows whether scripts are blocked, and has a *Desanitize* and a
*Re-sanitize* (restore) button. Windows asks for administrator permission when DCS is under
Program Files. If you generate a mission while an install is still blocked, a pop-up offers the
same button. The buttons run the script below.

By hand, **in an elevated PowerShell if DCS is under Program Files**:

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

Settings → *Co-op / multiplayer*:

* **Seats in your own flight (1–4):** friends fly as your wingmen in the same aircraft type.
* **Extra pilots in their own aircraft (0–12):** each gets a wingman seat in *another* friendly
  flight of the mission (same package first, then other flights that depart during the mission),
  in any aircraft from the co-op module list — so a friend with a different module flies that
  module. The AI keeps the lead of those flights, so the tasking is flown even if nobody joins.
  The ATO still decides what every flight does.
* Every human seat is a **Client** slot, cold on the ramp or deck. The generated-mission panel and
  the DCS briefing list the slots (callsign, aircraft, seat numbers, base, frequency).
* Accounting is per aircraft: a guest's aircraft comes out of that squadron's airframes, fuel and
  weapons like any other; losses and kills are credited to the flight and shown per pilot in the
  debrief. A seat nobody takes never spawns and costs nothing. The career (hours, rank, awards)
  follows the pilot in seat 1 of your flight.
* The host needs the desanitize step. Multi-crew seats (WSO/RIO/CPG) work as DCS provides them.

**Dedicated server:** tick *Also save each mission into the server's Missions\SORTIE folder* and
set the server's Saved Games folder (detected profiles such as `DCS.server1` are offered). The
mission is written to both places, and events are read from whichever instance runs the mission
(client folder, server folder or `%TEMP%\SORTIE`).

### Mission clock

The mission does not start at the beginning of the 6-hour cycle. It starts ten minutes before
your take-off time (`mission.startup_minutes`). Packages that are already home by then are fought
out before the mission is built, so their results are in it and listed under "Earlier this cycle".
Flights that took off before then are airborne where they would be; everything else is parked at
its base (or on the deck) and starts up on schedule. Nothing spawns in mid-air during the mission
and every flight flies home and lands. Whatever happens after you land is resolved at debrief.

AWACS, tankers and the carrier's plane guard / recovery tanker are already on station when the
cycle begins (they launched during the previous cycle) and stay until the last tasking of the ATO
has landed and the next cycle's aircraft has taken over, so they are in every mission from the
first second.

Packages with more than one flight get a **JOIN** waypoint in friendly territory (outside known
air-defence rings and on your side of the front). All elements are timed to be there by the
lead's push time; escorts pick the strikers up there.

Settings → *Your aircraft start*: **cold** (mission opens 10 minutes before take-off) or **hot**
with engines running (mission opens 3 minutes before take-off). It applies to every human seat.

### Kneeboard

Every aircraft type with a human seat gets kneeboard pages inside the mission (flight card with
route, times, headings, distances, coordinates, loadout; a support/threat page with tankers,
AWACS, package, air defences, weather, IFF Mode 3 and laser codes, bingo/joker, Link 16 /
SADL track numbers). Open the kneeboard in the cockpit (default `RShift+K`).

### Units

Settings → *Units*: imperial (ft, kt, nm) or metric (m, km/h, km) for the GUI briefing, the DCS
briefing text and the kneeboard.

### Loadouts

Each flight gets the best-scoring DCS payload for its task: the right weapons first, then external
fuel, self-defence heat-seekers, radar missiles and the pods the weapons need. To force your own,
save a payload in the Mission Editor named **`SORTIE <TASK>`** (for example `SORTIE SEAD`,
`SORTIE CAS`, `SORTIE CAP`) for that aircraft; it always wins.

Weapons at airbases are **unlimited in DCS by default**. Limited weapon stock
(`logistics.limit_munitions: true`) is experimental: in the first flown mission DCS removed every
store without warehouse stock, including fuel tanks, pods and AIM-9X. Fuel is limited and read
back as designed. The campaign still tracks munition levels and grounds squadrons that run dry.

### Navaids

Carriers transmit TACAN (71X, 72X, ...), ICLS (channel 1, 2, ...), Link 4 and ACLS; tankers
transmit air-to-air TACAN on the briefed Y channel. Your home base's TACAN, VOR, ILS frequencies
per runway and tower frequencies are on the briefing and the kneeboard (read from the DCS install).
Airfield ILS and TACAN are part of the map and always on; DCS activates the ILS for the runway in
use.

### Carrier operations

When a carrier is in the mission the ATO adds a plane-guard helicopter (SH-60B, about 1 nm off the
starboard side at 300 ft; kept on station by MOOSE's RESCUEHELO when MOOSE is embedded) and a
recovery tanker overhead (S-3B at 6,000 ft using DCS's Recovery Tanker task).

### Performance profiles

Light / Standard / Heavy cap how many aircraft are **airborne at the same time**, plus ground
groups, naval groups and the simulation bubble around your route. Flights at different times do
not count against each other, and your own package is never cut. Everything outside is resolved
abstractly. Auto picks
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

**Getting voice to work.** Voice needs four things, all listed with a green/amber status under
Settings → *Voice check*: the ATC layer and a voice engine switched on; the SRS install folder
(the `ExternalAudio` subfolder that holds `DCS-SR-ExternalAudio.exe` is found automatically);
an SRS server running on the PC that hosts the mission; and mission scripts desanitised there
(MOOSE has to start the SRS speech tool). *Test voice through SRS* speaks a sentence on a
frequency of your choice without starting DCS.

The controller is not a permanent SRS client. It joins the SRS server only while it speaks and
leaves again a few seconds later, so an empty client list between calls is normal. Calls go out
on the controller's frequency and on your flight's frequency (AM), so you hear them on the radio
you start with. About 20 seconds into the mission a message says which frequencies voice is on,
or why it is off; F10 → SORTIE Control → *Radio check* repeats the test at any time.

Tower calls read the runway in use (most headwind), the surface wind and the altimeter setting
from the running mission.

## Tests

```powershell
.\.venv\Scripts\python -m pytest
```

No test needs DCS or touches your DCS folders; everything runs in temp directories.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Mission was hosted on a server that is not desanitised | Nothing to do: at debrief SORTIE reads the events from the client's or server's `dcs.log`. Only the live feed needs the desanitize step. |
| "No event file yet" on Live Mission | Run `tools\install_desanitize.ps1` (again after a DCS update); check `python -m sortie doctor`. |
| Debrief says no events found | Same as above, or the mission was not this cycle's file. Events that went to `dcs.log` can be imported: `python -m sortie import-log <campaign id> <path to dcs.log>` (the id is shown in the Campaigns list). |
| Aircraft spawn with empty pylons | DCS install not found → set it in Settings. Loadouts come from DCS's own payload files. |
| No squadron offered in the wizard | No aircraft on that side is ticked under Settings → Owned modules. |
| Map is blank | Leaflet/tiles need internet; the rest of the GUI works offline. |
| Mission not listed in DCS | Check the path shown after generation; set *Mission output folder* in Settings. |
| Wrong DCS folder detected | Override both paths in Settings. |
| Port in use | `python -m sortie gui --port 8770` |

## Credits

The weather model and its weapon limits, per-flight IFF/laser codes, bingo/joker figures, the
Link 16 / SADL set-up and the AI SEAD hold-fire idea were adapted from
[SQE (Squadron Campaign Engine)](https://github.com/MarkuzJuniuz/SQE) by MarkuzJuniuz, MIT licence.
