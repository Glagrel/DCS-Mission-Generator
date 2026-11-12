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
