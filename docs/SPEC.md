# SORTIE — Specification

SORTIE is a Falcon BMS-style dynamic campaign for DCS World. A Python engine owns the
war; DCS is used only to fly one sortie at a time. The player is a line pilot: the ATO
assigns the mission, never the player.

## 1. Loop

```
new campaign (wizard) ─► [ATO cycle N] ─► build .miz ─► player flies in DCS
        ▲                                                     │ events.jsonl
        │                                                     ▼
  advance war (supply, production, repair, fronts) ◄─ ingest AAR + abstract-resolve rest of ATO
```

One **turn** = one ATO cycle (`turn_hours`, default 6 h of campaign time). The player
flies at most one sortie per turn. "Skip sortie" resolves the player's flight abstractly.

## 2. Layout

```
sortie/            Python package
  config.py        settings.json, path detection, performance profiles
  paths.py         DCS Saved Games / install auto-detection
  models.py        pydantic state models        models_ato.py   ATO models
  db.py            SQLite document store        campaign.py     Campaign facade + creation
  theater.py       template schema + loader     units.py        pydcs type lookup, era filter
  geo.py           lat/lon maths (haversine, bearings, interpolation)
  sim/             supply.py production.py airwar.py ground.py turn.py
  ato/             needs.py planner.py assign.py route.py radio.py
  mission/         builder.py flights.py forces.py warehouses.py briefing.py scripts.py budget.py
  runtime/         watcher.py aar.py
  debrief/         ingest.py career.py reassign.py
  atc/             procedures.py luacfg.py
  web/             app.py api_*.py static/ (index.html, js, css; Leaflet)
  lua/             sortie_json.lua sortie_core.lua sortie_events.lua sortie_warehouse.lua
                   sortie_spawn.lua sortie_atc.lua
data/theaters/     one YAML per template
data/              unit_eras.yaml, sam_templates.yaml, weapon_seed.yaml, ranks.yaml
config/            settings.json (user, git-ignored), defaults.yaml (tunable numbers)
tools/             setup.ps1 run.ps1 install_desanitize.ps1 fetch_moose.py
vendor/moose/      Moose_.lua (downloaded by setup, git-ignored)
tests/             pytest
docs/              SPEC PLAN PROGRESS DECISIONS TEST_IN_DCS KNOWN_ISSUES
```

Rules: files ≤ ~400 lines, one responsibility each. Nothing outside the project folder is
written except the explicit outputs `<SavedGames>\Missions\SORTIE\*.miz` and the runtime
folder beneath it (both are the product's purpose). `MissionScripting.lua` is only touched
by the user-run `tools/install_desanitize.ps1`.

## 3. Data model (sortie/models.py)

All entities are pydantic models stored as JSON documents in SQLite
(`entities(campaign_id, kind, id, data)`), plus append-only `history` rows.

| kind | key fields |
|---|---|
| `meta` (single) | name, template_id, player_side, date (ISO datetime), turn, turn_hours, difficulty, profile, seed, status, features |
| `airbase` | id, dcs_name, kind (airfield/carrier/farp), coalition, lat, lon, runway_health 0..1, fuel{jet,avgas,mw50,diesel} tons, fuel_cap, munitions{dcs item name: count}, munition_level 0..1, supply_node |
| `squadron` | id, name, coalition, country, airbase_id, aircraft (pydcs id), tasks[], airframes, airframes_max, pilots, pilots_max, skill, morale, grounded, is_player |
| `front` | id, name, a{lat,lon} (blue rear anchor), b{lat,lon} (red rear anchor), position 0..1 (0=at a, 1=at b; blue advances toward b), blue_strength, red_strength, pressure -1..1 |
| `ground_unit` | id, coalition, country, front_id, template (unit list), strength 0..1, lat, lon |
| `sam_site` | id, coalition, country, template (key in sam_templates.yaml), lat, lon, health, role (sam/ewr/aaa), range_km |
| `supply_node` | id, kind (factory/port/depot/rail/bridge), coalition, country, lat, lon, health, output (t/turn, factories+ports), stock, static_type, n_objects |
| `supply_route` | id, src, dst, capacity (t/turn), kind (road/rail/sea), interdiction 0..1 |
| `naval_group` | id, coalition, country, units[], lat, lon, health, airbase_id (carrier), track[] |
| `pilot` (player) | callsign, rank, hours, sorties, kills{air,ground,naval,structure}, awards[], status, squadron_id, aircraft, history[] |
| `ato` | turn, packages[] (see models_ato.py) |
| `sortie` | turn, miz_path, state (planned/built/flown/skipped), result |

ATO: `Package{id, coalition, mission, target{kind,id,lat,lon,name}, tot, flights[]}`;
`Flight{id, squadron_id, aircraft, count, task, callsign, freq, is_player, waypoints[], loadout, status, result}`.
Mission types: CAP, ESCORT, SWEEP, SEAD, DEAD, STRIKE, CAS, INTERDICTION, ANTISHIP, RECON,
TANKER, AWACS, TRANSPORT — filtered by template `capabilities` and era.

## 4. Theater templates (data/theaters/*.yaml)

Validated by `sortie/theater.py` (pydantic). Top-level keys: `id, name, terrain, era{year,
kind: ww2|coldwar|modern}, start{date, time, weather}, coalitions{blue,red: {name, countries[],
capabilities[], doctrine: nato|soviet|ww2}}, airbases[], carriers[], squadrons[], fronts[],
ground_units[], sam_sites[], supply_nodes[], supply_routes[], bullseye, player_options`.
Every pydcs type id in a template is checked against pydcs and against `data/unit_eras.yaml`
(introduction year ≤ template year) by a test.

## 5. Simulation (sortie/sim)

Per turn, in order: `supply` (factories/ports produce → flow along routes limited by
capacity × health × (1-interdiction) → depots → airbases get fuel tons and munition level),
`production` (airframe/pilot replacements by priority = need × supply), `repair` (runways,
SAMs, nodes), `airwar` (abstract resolution of every non-flown ATO flight: probabilistic
exchange using aircraft ratings, SAM threat on route, target damage), `ground` (front
movement from strength ratio + CAS/interdiction effects + supply). All randomness comes
from a `random.Random` seeded from `meta.seed + turn` → deterministic tests.

## 6. ATO (sortie/ato)

`needs.py` scores candidate tasks per coalition from state: SEAD/DEAD (enemy SAM coverage
over own targets/fronts), CAP/ESCORT (air-superiority ratio, bases hit last turn), STRIKE
(supply nodes, airbases), CAS (front pressure), INTERDICTION (routes feeding a pressured
front), ANTISHIP, RECON, support (TANKER/AWACS if capable). `planner.py` allocates squadrons
(capable task, range, airframes, fuel, munitions) to the highest scores → packages with TOTs.
`assign.py` picks the player's flight: the best-scoring flight flown by the player's squadron
(creating one if the squadron got nothing). `route.py` builds waypoints (hold → ingress → IP →
target → egress → home) avoiding known SAM rings where cheap. `radio.py` allocates
frequencies per era band.

## 7. Mission builder (sortie/mission)

pydcs `Mission` on the template terrain. Contains: the player's package (player flight as
`Client` slots — size from co-op setting; SP = slot 1 `Player`), all flights/ground/naval/SAM/
supply objects inside the **budget bubble** (distance from the player's route ≤ profile
`bubble_km`, capped by profile counts, nearest-first), warehouses from state, briefing text,
radio plan, and embedded Lua: `Moose_.lua` then SORTIE scripts via MISSION START → DO SCRIPT
FILE. A generated `sortie_config.lua` carries campaign ids, object→entity name map,
warehouse table, profile limits, and ATC config.

Naming contract (Lua ↔ Python): every generated group is named `S|<kind>|<entity id>|<n>`
(`kind` ∈ flt, gnd, sam, nav, sup, stc). Events carry DCS names; Python maps back by parsing.

## 8. Runtime protocol (events.jsonl)

Path: `<SavedGames>\Missions\SORTIE\runtime\events.jsonl` (one JSON object per line, flushed
per write). Fields: `t` (mission seconds), `ev`, plus event specifics. Types: `mission_start
{campaign, turn, sortie}`, `birth, takeoff, land, shot, hit, kill, crash, eject, pilot_dead,
dead, lost, base_captured, player_enter, player_leave, engine_start, refuel`, `snapshot
{air{blue,red}, ground{…}, player[]}`, `warehouse {base, liquids{0..3}, weapons{}, aircraft{}}`,
`spawn/despawn` (proximity manager), `atc`, `mission_end`. Unit refs:
`{n: unit name, g: group name, ty: type, c: coalition(1 red, 2 blue), p: player name|nil}`.
Without desanitized `io`/`lfs` the scripts fall back to `env.info("SORTIE_EVT {json}")` lines
and the watcher can parse `dcs.log` instead.

## 9. Debrief (sortie/debrief)

`ingest.py` folds events into a `SortieResult` (per-flight losses, kills by type, targets
destroyed, warehouse readback, player stats, flight time) and applies it: airframes/pilots,
SAM/site/node health, ground strength, base stocks. Flights of the ATO that were not
simulated in DCS are resolved by `sim.airwar`. `career.py` updates hours/kills/awards/rank/
status. `reassign.py` may move the player to another squadron/aircraft among owned modules.

## 10. Web GUI (sortie/web)

FastAPI JSON API + static single-page app (vanilla JS + Leaflet from CDN with a no-map
fallback). Pages: Wizard, Map, ATO/Briefing, Roster/Career, Logistics, Live feed (SSE),
Debrief, Settings. `POST /api/mission/generate` writes the .miz and returns its path.

## 11. Performance profiles

`config/defaults.yaml` → `profiles: light|standard|heavy` with `max_air, max_ground_groups,
max_naval_groups, bubble_km, despawn_km, spawn_km`. Auto-selected by RAM (≤16 GB light,
≤48 GB standard, else heavy); manual override in settings.

## 12. ATC/GCI layer (feature flag `atc.enabled`, default off)

`sortie/atc` emits a Lua config consumed by `sortie_atc.lua`, which wires MOOSE classes when
present (FLIGHTCONTROL, AWACS, AIRBOSS, CSAR, MSRS) and otherwise SORTIE's own lightweight
text GCI. Voice engine: off|windows|piper|google via MSRS; text fallback always available.
Procedure sets: nato, soviet, ww2 (simple GCI calls only).
