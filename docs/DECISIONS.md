# SORTIE — Decisions and flags

Entries are numbered; **FLAG** marks things that need in-sim verification or later tuning.

1. **pydcs package name.** `pip install -U dcs` installs an unrelated Rackspace package
   ("Dynamic Chef Solo", v0.1.1). The DCS mission library is published as **`pydcs`**
   (import name `dcs`). Setup installs `pydcs` (1.0.0 at time of writing) and removes `dcs`.
2. **Terrains in pydcs 1.0.0:** afghanistan, caucasus, falklands, germany (GermanyCW),
   kola, marianaislands, nevada, normandy, persiangulf, sinai, syria, thechannel.
   **The Marianas WWII map is missing.** Operation Forager is built on the modern
   `MarianaIslands` terrain (same islands, same coordinates; modern airfields/buildings
   visible). **FLAG** — when pydcs adds `MarianaIslandsWWII`, change `terrain:` in
   `data/theaters/forager_1944.yaml`.
3. **No Japanese aircraft or warships exist in DCS/pydcs.** Japan flies stand-ins under the
   `Japan` country: Bf-109K-4 (fighter), FW-190A8 (fighter-bomber), Ju-88A4 (bomber).
   Japanese shipping uses generic cargo ships. Japanese ground units use the real WWII
   Asset Pack types pydcs lists (Type 89 I-Go, Type 98 Ke-Ni, Type 88 75 mm AA, …). **FLAG**
4. **State storage:** pydantic documents stored as JSON rows in SQLite (one table of
   entities keyed by campaign/kind/id plus a history table) rather than a fully normalised
   schema. Simple, migration-free, and still queryable with SQLite JSON functions.
5. **Warehouse weapons.** pydcs has no `wsType` table, which the `.miz` `warehouses` file
   needs for per-weapon rows. So: the .miz carries coalition, limited-flags, fuel (tons)
   and aircraft counts per airbase; **per-weapon stock is applied at mission start by Lua**
   through the documented `Warehouse.setItem(itemName, count)` API from a table generated
   from campaign state, and read back with `getInventory()` / `getLiquidAmount()`.
   Weapon item names the campaign has never seen are discovered at runtime (`Unit.getAmmo`
   on birth, inventory dump) and given the base's `munition_level × default_stock`; they are
   reported back so the campaign tracks them from then on. `data/weapon_seed.yaml` holds a
   small best-effort seed list of item names. **FLAG** — verify in DCS.
6. **Aircraft warehouse format** assumed `aircrafts = {planes={[type]={initialAmount=n}},
   helicopters={…}}`. **FLAG**
7. **Turn = one ATO cycle** of 6 campaign hours by default; one player sortie per turn.
8. **Group naming contract** `S|kind|entity|n` links DCS objects back to campaign entities.
9. **Era data.** pydcs has no in-service years. `data/unit_eras.yaml` lists introduction
   years for the types used; unknown types are treated as "modern" (2000) so they are
   excluded from older eras by default.
10. **Owned modules default** = every pydcs `flyable` aircraft/helicopter, filtered by era in
    the wizard.
11. **DCS path detection:** Saved Games = candidate folder with newest `Logs\dcs.log`;
    install = registry `HKCU\Software\Eagle Dynamics\*` `Path` values validated by
    `bin\DCS.exe`/`bin-mt\DCS.exe`, then common paths on all drives; overridable in settings.
12. **MOOSE** is downloaded by `tools/fetch_moose.py` from the official
    `FlightControl-Master/MOOSE_INCLUDE` repo (`Moose_Include_Static/Moose_.lua`) into
    `vendor/moose/`. Offline: place `Moose_.lua` there by hand. Missions still build without
    it (SORTIE's own Lua does not depend on MOOSE; only the ATC layer does).
13. **Revised brief (project boundaries).** The coding agent never writes outside the project
    folder and never runs the integration scripts. The *application*, when the user clicks
    "Generate next mission", writes the `.miz` and runtime folder under
    `<SavedGames>\Missions\SORTIE\` (that is the product's function and is configurable via
    `output_dir`). All tests use temp directories.
14. **Schema migrations:** ordered `MIGRATIONS` list in `sortie/db.py`, version in
    `PRAGMA user_version`. Entity documents are pydantic models with defaults, so adding
    fields needs no migration.
15. **Gulf template:** the fictional "Farsian Republic" uses the DCS country `Iran`.
    Cold War template uses Tornado GR4 as the RAF Tornado GR1 stand-in and F-4E for the
    Luftwaffe F-4F (pydcs has neither).
16. **Fronts are an axis** (blue rear anchor → red rear anchor) with a position 0..1; ground
    formations are placed ~3 km either side of the line at mission-build time. Simple, but it
    gives front movement, CAS targets and base capture (an airbase overrun by the line flips).
17. **Loadouts** come from DCS's own `UnitPayloads` Lua files, parsed by pydcs. pydcs's
    built-in install lookup reads the "DCS World" registry key first, which on this machine
    points at the Saved Games folder, so SORTIE sets `PayloadDirectories` explicitly from its
    own detection. With no DCS install (tests) flights are built with empty pylons and the
    builder emits a warning. The player can always re-arm on the ramp.
18. **ATO balance:** each additional package of the same mission type costs 7 priority points
    (`planner.DIMINISH`) so one need category cannot monopolise the cycle. Max 14 packages
    per side per cycle. Both are tuning guesses.
19. **ATC layer design.** SORTIE's own Lua produces all controller text from native DCS API
    data so that text never depends on voice, SRS or MOOSE. MOOSE is used for speech only
    (MSRS) and optionally for the home tower (FLIGHTCONTROL, `atc.use_flightcontrol`, voice
    only because FLIGHTCONTROL speaks exclusively through SRS).
20. **MOOSE classes evaluated but not wired:** `AWACS:New(Name, AirWing, ...)` needs a MOOSE
    AIRWING/OPS stack that would fight with the flights pydcs already placed; `AIRBOSS`
    needs its sound-file pack and a recovery-tanker template; `CSAR:New(Coalition, Template,
    Alias)` needs late-activated helicopter templates; `AI_A2A_DISPATCHER` would re-task the
    ATO's flights. They are left out deliberately; CSAR is a radio notice plus the campaign's
    pilot-recovery roll. **FLAG** revisit after the basic layer is proven in DCS.
21. **Piper voice:** MSRS has no Piper provider (providers are win/gcloud/azure/aws). The
    setting is stored and passed through, but the mission falls back to Windows TTS and logs
    it. **FLAG / partial.**
22. **GCI detection is abstracted:** the controller "sees" every airborne hostile within
    185 km of the player rather than modelling radar coverage. Bearings are true, not magnetic.
23. **Limited aircraft in warehouses is off by default** (`logistics.limit_aircraft`): the
    .miz aircraft rows need `wsType` data pydcs lacks, and a wrong table could block the
    player's slot. Airframe attrition is enforced by the campaign instead (flight sizes).
24. **Mission clock (fast-forward).** The .miz starts `mission.startup_minutes` (10) before the
    player's take-off time instead of at the start of the cycle. Packages wholly finished by
    then are resolved abstractly *before* the build (`Service._resolve_before_launch`), the rest
    after debrief. Inspired by DCS Retribution's start-at-player-start-up option.
25. **No mid-air spawns.** At mission start a flight is either already airborne (it took off
    earlier; placed by interpolation along its route) or parked. Parked AI is `uncontrolled`
    until a one-shot trigger pushes its Start command. If a ramp is full, a later flight takes
    over the stands of one that left >5 min earlier (late-activated on the stand); failing that
    it lines up on the runway at take-off time; only then does it enter airborne over its base,
    with a warning. Aircraft are only removed after landing and parking.
26. **The aircraft limit is concurrency**, not a total: `budget._peak` checks aircraft airborne
    at the same time. The player's package is exempt.
27. **Carrier support.** Doctrine used: plane-guard helicopter in the starboard delta about 1 nm
    abeam at 300 ft (figures from US Army FM 1-564 ch. 5 on shipboard helicopter patterns);
    recovery tanker overhead at 6,000 ft / 274 kt (MOOSE RECOVERYTANKER defaults; community
    sources for the 6K stack altitude, not NATOPS). Tanker = DCS native `RecoveryTanker` task;
    helicopter = MOOSE `RESCUEHELO:New(carrierunit, helogroupname)` when MOOSE is embedded
    (it respawns the group under a new name, so its losses are not tracked), else a fixed
    racetrack beside the ship's start position. New mission type `SAR`; SH-60B squadrons added
    to the Gulf template. **FLAG** verify in DCS.
28. **Co-op guests** sit in the *last* aircraft of other friendly flights (AI keeps the lead).
    Their flights start cold on the ground and are not delayed, so the AI lead may leave before
    a human is ready. Unused Client seats are detected from the absence of any event for the
    unit and are not charged. **FLAG**
29. **Event file location** now follows Retribution's pattern: absolute folders passed in by the
    app (needs only `io`), then `lfs.writedir()`, then `%TEMP%`; the first writable one wins and
    an on-screen notice says whether the campaign link works. Python watches all candidates.
30. **Kneeboards** are PNGs rendered with Pillow and appended to the saved archive under
    `KNEEBOARD/<aircraft type>/IMAGES/` (pydcs's own helper writes a doubled slash in the
    archive path, so it is not used). **FLAG** verify they show in the cockpit.
31. **Support continuity.** AWACS/tanker/SAR flights are planned with their station time
    starting at cycle second 0 (negative take-off time = launched last cycle) and ending at
    max(last landing of the side's ATO + 15 min, end of cycle). Each cycle's aircraft therefore
    relieves the previous one on station at the cycle boundary. One airframe covers the whole
    cycle; real relief/refuelling cycles within a cycle are not modelled and DCS AI may leave
    early on fuel. **FLAG**
32. **Saved plans carry a planner version** (`Ato.version`, `planner.PLAN_VERSION`). An unflown
    plan from an older version is re-planned automatically, so fixes reach campaigns in progress.
33. **JOIN point:** first of 60/45/30/15 % along the lead's leg to INGRESS that is outside known
    enemy SAM/AAA rings (+5 km) and at least 10 km on the friendly side of any front. Flights
    that would arrive late leave earlier; the AI is not made to hold there (escorts simply attach
    to the lead from the JOIN point on).
34. **Hot start** (`player_start: hot`) applies to all human seats; the mission then opens
    `mission.hot_startup_minutes` (3) before take-off instead of 10.
35. **Loadout selection** (after DCS Liberation's "Liberation <task>" convention): a payload named
    `SORTIE <TASK>` wins; otherwise payloads are scored (`loadouts.score`) instead of taking the
    first tagged one. Units' default pylons are cleared before a payload is applied.
36. **Limited weapons default OFF** (`logistics.limit_munitions`). Evidence from the first flown
    mission (server dcs.log): with limited munitions and no weapon rows in the .miz the warehouse
    is empty; `getInventory()` lists nothing; aircraft are spawned without any store that has no
    stock (the Hornet lost its AIM-9X and centreline tank; HARM/AMRAAM survived only because the
    script had stocked those names); `Unit.getAmmo()` type names are not always warehouse names
    ("AIM_9X"). Liberation uses unlimited warehouses. Experimental mode now also stocks everything
    from `Warehouse.getResourceMap()` (shape unknown, probed and reported in a `warehouse_debug`
    event) and tries category prefixes for bare names. **FLAG**
37. **Fuel in warehouses is confirmed working**: `InitFuel` is tonnes (1500 -> 1,500,000 kg read
    back) and AI refuelling reduced stock at Al Dhafra.
38. **Navaids:** carrier TACAN 71X+, ICLS 1+, Link 4 336+ MHz, ACLS; tanker TACAN Y band via
    `ActivateBeaconCommand`. Airfield TACAN/VOR/ILS/tower data is parsed from
    `<DCS>\Mods\terrains\<terrain>\beacons.lua` (pydcs only has beacon ids).
39. **Debrief reads dcs.log** (client and server) when no event file exists for the sortie.
40. **Desanitize from the GUI** (user request). `sortie/sanitize.py` runs the same
    `tools/install_desanitize.ps1`, only when the button is pressed, only for installs SORTIE
    detected itself (settings/registry install, plus the install each Saved Games profile's
    dcs.log says it was started with, which is how the dedicated server's install is found).
    If the write is refused it is retried elevated through the normal UAC prompt. The elevated
    branch cannot be covered by automated tests. **FLAG**
41. **Recovery tanker altitude** follows the stack, not the refuelling track: 6,000 ft / 274 kt
    overhead the carrier in the ATO, briefing and DCS task alike (was FL220 in the route).
42. **Plane guard on every NATO carrier/LHA** (user request): `campaign.ensure_plane_guards` adds a
    2-airframe SH-60B (SH-3W before 1984) squadron to a ship without one, at career start and on
    load; carrier support of any friendly ship is top priority in the performance budget.
43. **Deck dressing**: DCS Liberation only spawns idle aircraft at airfields (never on ships,
    `aircraftgenerator.spawn_unused_aircraft` skips non-`Airfield` control points). SORTIE does put
    statics on decks, but at run time from the ship's parking table (only free spots, starboard,
    clear of the bow catapults' run on a CVN, never out of a reserve of every aircraft using that
    deck + 4). **FLAG** (not yet seen in DCS)
44. **Mod aircraft** are registered with pydcs only while installed AND switched on
    (`sortie/mods.py`); types copy numbers from the mods' own Lua; payloads are read with lupa.
    Super Hornets subclass pydcs's F/A-18C for radios/properties but hide its `PylonN` store lists,
    so nothing can hang a base-game Hornet store on a Super Hornet station.
45. **Community scripts** (`sortie/addons.py`): files live in `vendor/addons` (gitignored,
    `tools/fetch_addons.py`). Splash Damage settings are parsed from the script's own option
    table and written into the embedded copy right after that table. Skynet and Hound are set up
    by `sortie_addons.lua` from the manifest. Growler AEA (loads a few seconds in, as its author asks)
    is shelved until the script can be downloaded.
46. **JTAC**: base-DCS FAC task (9-line) on a hidden, immortal HMMWV; MOOSE AUTOLASE optional.
