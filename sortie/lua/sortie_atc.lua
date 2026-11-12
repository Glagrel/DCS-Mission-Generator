-- SORTIE ATC / GCI layer (feature flag, default OFF; only embedded when enabled).
-- Text is always shown to the player's group. Voice is optional and goes through MOOSE MSRS
-- (SimpleRadio Standalone) when MOOSE is loaded and cfg.atc.voice ~= 'off'.
-- MOOSE calls used (verified against the vendored Moose_.lua):
--   MSRS:New(Path, Frequency, Modulation), :SetPort, :SetCoalition, :SetCulture, :SetProvider,
--   :SetGoogle(PathToCredentials), :PlayText(Text, Delay), MSRS.Provider.WINDOWS / .GOOGLE
--   :SetFrequencies(table), :SetModulations(table), :SetLabel(name)
-- MSRS starts SRS's DCS-SR-ExternalAudio.exe once per message: the controller is only in the
-- SRS client list while it is talking. That needs os and io un-sanitised on the hosting PC.
--   FLIGHTCONTROL:New(AirbaseName, Frequency, Modulation, PathToSRS, Port):Start()
SORTIE.atc = { cfg = (SORTIE.cfg and SORTIE.cfg.atc) or {}, last = {}, merged = {}, state = {}, said = {},
               spoken = {} }
local A = SORTIE.atc
local C = A.cfg
local F = C.features or {}

-- ---- formatting (mirrors sortie/atc/procedures.py) -------------------------------------
function A.fmt_bearing(deg)
  return string.format('%03d', math.floor(deg + 0.5) % 360)
end

function A.fmt_range(m)
  if C.procedure == 'soviet' then return string.format('%.0f kilometres', m / 1000) end
  return string.format('%.0f miles', m / 1852)
end

function A.fmt_altitude(m)
  if C.procedure == 'soviet' then
    return string.format('%d metres', math.max(100, math.floor(m / 100 + 0.5) * 100))
  end
  local thousands = math.floor(m * 3.28084 / 1000 + 0.5)
  if C.procedure == 'ww2' then return tostring(thousands) end
  return tostring(math.max(1, thousands)) .. ' thousand'
end

function A.aspect(target_heading, bearing_to_target)
  local diff = math.abs((target_heading - (bearing_to_target + 180) + 180) % 360 - 180)
  if diff <= 30 then return 'hot' end
  if diff <= 60 then return 'flanking' end
  if diff <= 120 then return 'beaming' end
  return 'cold'
end

function A.render(key, params)
  local tpl = C.phrases and C.phrases[key]
  if not tpl then return '' end
  return (string.gsub(tpl, '{([%w_]+)}', function(k)
    local v = params and params[k]
    if v == nil then return '{' .. k .. '}' end
    return tostring(v)
  end))
end

-- ---- geometry in DCS map coordinates (x = north, z = east) -------------------------------
function A.bearing(from, to)
  return math.deg(math.atan2(to.z - from.z, to.x - from.x)) % 360
end

function A.heading_of(unit)
  local h = 0
  pcall(function()
    local v = unit:getVelocity()
    h = math.deg(math.atan2(v.z, v.x)) % 360
  end)
  return h
end

local function bulls_point()
  if not A.bulls and C.bullseye then
    local ok, p = pcall(coord.LLtoLO, C.bullseye.lat, C.bullseye.lon, 0)
    if ok then A.bulls = p end
  end
  return A.bulls
end

-- ---- output: text always, voice when available ---------------------------------------------
-- What is shown as "045/30" or "251.500" has to be said digit by digit.
local WORDS = { ['0'] = 'zero', ['1'] = 'one', ['2'] = 'two', ['3'] = 'three', ['4'] = 'four', ['5'] = 'five',
                ['6'] = 'six', ['7'] = 'seven', ['8'] = 'eight', ['9'] = 'niner', ['.'] = 'decimal',
                L = 'left', R = 'right', C = 'center' }
local SPELL = { bearing = true, wind_dir = true, qnh = true, freq = true, runway = true, tacan = true }

function A.spell(v)
  local s = tostring(v)
  if not string.match(s, '^%d[%d%.]*%a?$') then return s end
  if string.find(s, '%.') then s = string.gsub(string.gsub(s, '0+$', ''), '%.$', '') end
  local out = {}
  for ch in string.gmatch(s, '.') do out[#out + 1] = WORDS[ch] or ch end
  return table.concat(out, ' ')
end

function A.speech(key, params)
  local p = {}
  for k, v in pairs(params or {}) do p[k] = SPELL[k] and A.spell(v) or v end
  if p.groups_spoken then p.groups = p.groups_spoken end
  local text = A.render(key, p)
  text = string.gsub(text, '/', ', ')
  text = string.gsub(text, 'BRAA', 'bra')
  return text
end

function A.say(key, params, delay)
  params = params or {}
  params.controller = params.controller or (C.controller and C.controller.callsign) or 'Control'
  local text = A.render(key, params)
  if text == '' then return nil end
  SORTIE.message(text, 15)
  if A.msrs then
    local spoken = A.speech(key, params)
    A.spoken[#A.spoken + 1] = spoken
    pcall(function() A.msrs:PlayText(spoken, delay or 0) end)
  end
  SORTIE.emit('atc', { key = key, text = text })
  A.said[#A.said + 1] = text
  return text
end

local EXE = 'DCS-SR-ExternalAudio.exe'

-- The folder holding the SRS speech tool: SRS 2.x keeps it in <SRS>\ExternalAudio.
local function find_srs(path)
  path = string.gsub(tostring(path or ''), '[\\/]+$', '')
  for _, dir in ipairs({ path, path .. '\\ExternalAudio' }) do
    local f = io.open(dir .. '\\' .. EXE, 'rb')
    if f then f:close() return dir end
  end
  return nil
end

local function voice_freqs()
  local list = {}
  for _, f in ipairs(C.voice_freqs or {}) do list[#list + 1] = f end
  if #list == 0 then list[1] = (C.controller and C.controller.freq) or 251 end
  return list
end

-- Sets A.msrs when speech can work, and A.voice = { ok, reason } either way.
function A.setup_voice()
  if C.voice == 'off' or C.voice == nil then A.voice = { ok = false, reason = 'off' } return end
  local function fail(reason)
    A.voice = { ok = false, reason = reason }
    SORTIE.log('ATC voice unavailable, text only: ' .. reason)
  end
  if not MSRS then return fail('MOOSE is not loaded in this mission') end
  if not io or not os then
    return fail('MissionScripting.lua is sanitised on the PC hosting the mission (use Desanitize in SORTIE Settings)')
  end
  local dir = find_srs(C.srs and C.srs.path)
  if not dir then
    return fail(EXE .. ' not found in ' .. tostring(C.srs and C.srs.path) .. ' (set the SRS folder in SORTIE Settings)')
  end
  local freqs = voice_freqs()
  local ok, err = pcall(function()
    local mods = {}
    for i = 1, #freqs do mods[i] = radio.modulation.AM end
    local m = MSRS:New(dir, freqs[1], radio.modulation.AM)
    if m.SetFrequencies then m:SetFrequencies(freqs) end
    if m.SetModulations then m:SetModulations(mods) end
    if m.SetLabel then
      m:SetLabel((string.gsub((C.controller and C.controller.callsign) or 'SORTIE', '[^%w_-]', '')))
    end
    m:SetPort(C.srs.port or 5002)
    m:SetCoalition(C.coalition or 2)
    m:SetCulture(C.srs.culture or 'en-US')
    if C.voice == 'google' then
      m:SetProvider(MSRS.Provider.GOOGLE)
      if C.srs.google_credentials and C.srs.google_credentials ~= '' then m:SetGoogle(C.srs.google_credentials) end
    else
      -- 'windows', and 'piper' until a Piper provider exists in MSRS (see docs/KNOWN_ISSUES.md)
      m:SetProvider(MSRS.Provider.WINDOWS)
      if C.voice == 'piper' then SORTIE.log('Piper is not an MSRS provider; using Windows TTS.') end
    end
    A.msrs = m
  end)
  if not ok then return fail('MSRS setup failed: ' .. tostring(err)) end
  A.voice = { ok = true, path = dir, freqs = freqs }
  SORTIE.log('ATC voice ready: ' .. dir .. ' on ' .. table.concat(freqs, ', ') .. ' MHz AM, port ' .. tostring(C.srs.port))
  if FLIGHTCONTROL and C.use_flightcontrol and C.home and C.home.kind == 'airfield' then
    pcall(function()
      A.flightcontrol = FLIGHTCONTROL:New(C.home.name, C.home.freq, radio.modulation.AM, dir, C.srs.port)
      A.flightcontrol:Start()
    end)
  end
end

local function freq_text(list)
  local out = {}
  for i, f in ipairs(list or {}) do out[i] = string.format('%.3f', f) end
  return table.concat(out, ' / ')
end

-- Say once, on screen, whether voice works and where to listen (or why it does not).
function A.announce_voice()
  local v = A.voice or { ok = false, reason = 'off' }
  if v.reason == 'off' then return end
  SORTIE.emit('voice', { ok = v.ok, reason = v.reason, path = v.path, freqs = v.freqs })
  if v.ok then
    SORTIE.message('SORTIE voice: ' .. tostring((C.controller and C.controller.callsign) or 'Control')
      .. ' speaks through SRS on ' .. freq_text(v.freqs) .. ' AM. F10 > SORTIE Control > Radio check to test.', 20)
  else
    SORTIE.message('SORTIE voice is OFF (text only): ' .. tostring(v.reason) .. '.', 30)
  end
end

function A.radio_check()
  local v = A.voice or {}
  local freq = (v.freqs and v.freqs[1]) or (C.controller and C.controller.freq) or 0
  local text = A.say('radio_check', { callsign = A.callsign(), freq = string.format('%.3f', freq) })
  if v.ok then
    SORTIE.message('Spoken through SRS on ' .. freq_text(v.freqs) .. ' AM. Nothing heard? Check that the SRS server '
      .. 'is running on port ' .. tostring(C.srs.port) .. ' and that your SRS client is connected to it with a '
      .. 'radio on one of those frequencies.', 20)
  elseif v.reason and v.reason ~= 'off' then
    SORTIE.message('No voice: ' .. tostring(v.reason) .. '.', 20)
  end
  return text
end

-- ---- contacts ------------------------------------------------------------------------------
local function enemy_side() return (C.coalition == 2) and coalition.side.RED or coalition.side.BLUE end

-- Hostile air groups as { name, p = position of lead, heading, alt, size }.
function A.contacts()
  local out = {}
  for _, cat in ipairs({ Group.Category.AIRPLANE, Group.Category.HELICOPTER }) do
    local ok, groups = pcall(coalition.getGroups, enemy_side(), cat)
    if ok and groups then
      for _, g in ipairs(groups) do
        local units = g:getUnits() or {}
        local u = units[1]
        if u and u:inAir() then
          local p = u:getPoint()
          out[#out + 1] = { name = g:getName(), p = p, heading = A.heading_of(u), alt = p.y, size = #units }
        end
      end
    end
  end
  return out
end

local function contact_params(from, c, callsign)
  local b = A.bearing(from, c.p)
  return { callsign = callsign, bearing = A.fmt_bearing(b), range = A.fmt_range(SORTIE.dist2d(from, c.p)),
           altitude = A.fmt_altitude(c.alt), aspect = A.aspect(c.heading, b), declare = 'hostile' }
end

function A.player()
  local g = Group.getByName(SORTIE.cfg.player_group or '')
  if not g or not g:isExist() then return nil end
  local u = (g:getUnits() or {})[1]
  if not u then return nil end
  return u, g
end

function A.callsign() return C.player_callsign or 'Flight' end

function A.picture()
  if not F.picture or not F.gci then return end
  local u = A.player()
  if not u or not u:inAir() then return end
  local ref = F.bullseye and bulls_point() or u:getPoint()
  local list = A.contacts()
  local up = u:getPoint()
  table.sort(list, function(a, b) return SORTIE.dist2d(up, a.p) < SORTIE.dist2d(up, b.p) end)
  local near = {}
  for _, c in ipairs(list) do
    if SORTIE.dist2d(up, c.p) < (C.picture_range_m or 185000) then near[#near + 1] = c end
  end
  if #near == 0 then return A.say('picture_clean', { callsign = A.callsign() }) end
  local parts, spoken = {}, {}
  for i = 1, math.min(3, #near) do
    local cp = contact_params(ref, near[i], A.callsign())
    parts[#parts + 1] = A.render('group', cp)
    spoken[#spoken + 1] = A.speech('group', cp)
  end
  return A.say('picture', { callsign = A.callsign(), n = #near, s = (#near == 1) and '' or 's',
                            groups = table.concat(parts, '. ') .. '.',
                            groups_spoken = table.concat(spoken, '. ') .. '.' })
end

function A.bogey_dope()
  local u = A.player()
  if not u then return end
  local up, best, bd = u:getPoint(), nil, nil
  for _, c in ipairs(A.contacts()) do
    local d = SORTIE.dist2d(up, c.p)
    if not bd or d < bd then best, bd = c, d end
  end
  if not best then return A.say('picture_clean', { callsign = A.callsign() }) end
  return A.say('bogey_dope', contact_params(up, best, A.callsign()))
end

function A.declare()
  if not F.declare then return end
  local u = A.player()
  if not u then return end
  local up, hdg, best, bd = u:getPoint(), A.heading_of(u), nil, nil
  for _, c in ipairs(A.contacts()) do             -- nearest contact within 30 degrees of the nose
    local off = math.abs((A.bearing(up, c.p) - hdg + 180) % 360 - 180)
    local d = SORTIE.dist2d(up, c.p)
    if off <= 30 and (not bd or d < bd) then best, bd = c, d end
  end
  local ref = bulls_point() or up
  if best then return A.say('declare_hostile', contact_params(ref, best, A.callsign())) end
  return A.say('picture_clean', { callsign = A.callsign() })
end

function A.threat_scan()
  if not F.threat or not F.gci then return end
  local u = A.player()
  if not u or not u:inAir() then return end
  local up, now = u:getPoint(), timer.getTime()
  for _, c in ipairs(A.contacts()) do
    local d = SORTIE.dist2d(up, c.p)
    local last = A.last[c.name] or -1000
    if d < 5000 then
      if now - (A.merged[c.name] or -1000) > 90 then
        A.merged[c.name] = now
        A.last[c.name] = now
        A.say('merged', { callsign = A.callsign() })
      end
    elseif d < (C.threat_range_m or 46300) and now - last > 60 then
      A.last[c.name] = now
      A.say('threat', contact_params(up, c, A.callsign()))
    end
  end
end

function A.vector(kind)
  local u = A.player()
  if not u then return end
  local up = u:getPoint()
  if kind == 'home' and C.home then
    local ok, ab = pcall(Airbase.getByName, C.home.name)
    if ok and ab then
      local hp = ab:getPoint()
      return A.say('vector_home', { callsign = A.callsign(), bearing = A.fmt_bearing(A.bearing(up, hp)),
                                    range = A.fmt_range(SORTIE.dist2d(up, hp)) })
    end
  elseif kind == 'tanker' and F.tanker and C.tankers and C.tankers[1] then
    local t = C.tankers[1]
    local g = t.group and Group.getByName(t.group)
    local tu = g and g:isExist() and (g:getUnits() or {})[1]
    if tu then
      local tp = tu:getPoint()
      return A.say('vector_tanker', { callsign = A.callsign(), tanker = t.callsign, tacan = t.tacan or '-',
                                      freq = string.format('%.3f', t.freq or 0),
                                      bearing = A.fmt_bearing(A.bearing(up, tp)),
                                      range = A.fmt_range(SORTIE.dist2d(up, tp)), altitude = A.fmt_altitude(tp.y) })
    end
  end
end

-- ---- tower calls and event-driven messages -------------------------------------------------
-- Surface wind at the home base as (direction it blows FROM in degrees, speed in m/s), read from
-- the running mission; falls back to the planned weather.
function A.wind()
  local dir, spd = C.wind_dir or 0, C.wind_speed or 0
  pcall(function()
    local p = Airbase.getByName(C.home.name):getPoint()
    local v = atmosphere.getWind({ x = p.x, y = p.y + 10, z = p.z })
    local s = math.sqrt(v.x * v.x + v.z * v.z)
    if s >= 0.5 then dir = math.deg(math.atan2(-v.z, -v.x)) % 360 end
    spd = s
  end)
  return dir, spd
end

-- Altimeter setting: inches of mercury x100 (NATO, WW2) or millimetres (Soviet).
function A.qnh()
  local mm = 760
  pcall(function() mm = tonumber(env.mission.weather.qnh) or 760 end)
  if C.procedure == 'soviet' then return string.format('%d', math.floor(mm + 0.5)) end
  return string.format('%04d', math.floor(mm / 25.4 * 100 + 0.5))
end

local function runway_name(r, hdg)
  local num, suffix = string.match(tostring(r.Name or ''), '^(%d+)(%a?)$')
  local n = tonumber(num)
  local function off(a) return math.abs((a * 10 - hdg + 180) % 360 - 180) end
  if n and off(n) <= 30 then return string.format('%02d%s', n, suffix) end
  local o = n and ((n + 17) % 36 + 1)                         -- the other end of the same strip
  if o and off(o) <= 30 then return string.format('%02d%s', o, ({ L = 'R', R = 'L' })[suffix] or suffix) end
  local c = math.floor(hdg / 10 + 0.5) % 36
  return string.format('%02d', c == 0 and 36 or c)
end

-- Runway in use at the home base: the end with the most headwind (the longest strip in calm air).
function A.runway(wind_from, wind_speed)
  local best, score
  pcall(function()
    for _, r in ipairs(Airbase.getByName(C.home.name):getRunways() or {}) do
      local h = (-math.deg(r.course)) % 360        -- DCS gives the course as a negative bearing in radians
      for i, hdg in ipairs({ h, (h + 180) % 360 }) do
        local s = math.cos(math.rad(hdg - wind_from)) * (wind_speed or 0) + (r.length or 0) / 1e5 - i / 1e3
        if not score or s > score then score, best = s, runway_name(r, hdg) end
      end
    end
  end)
  return best or C.runway or 'in use'
end

local function tower_params()
  local wdir, wspd = A.wind()
  local shown = (C.procedure == 'soviet') and wspd or wspd * 1.94384        -- m/s or knots
  return { callsign = A.callsign(), tower = (C.home and C.home.name) or 'Tower', runway = A.runway(wdir, wspd),
           wind_dir = A.fmt_bearing(wdir), wind_speed = string.format('%d', math.floor(shown + 0.5)),
           qnh = A.qnh(), controller = C.controller and C.controller.callsign,
           freq = string.format('%.3f', (C.controller and C.controller.freq) or 0) }
end

function A.on_event(event)
  local name = SORTIE.events.names[event.id]
  local u = A.player()
  if not name or not u or not event.initiator then return end
  local okn, n = pcall(event.initiator.getName, event.initiator)
  local mine = okn and n == u:getName()
  if name == 'kill' and mine then A.say('splash', {}) return end
  if not mine then return end
  if A.flightcontrol and (name == 'engine_start' or name == 'takeoff' or name == 'land') then return end
  if name == 'engine_start' and F.ground and not A.state.started then
    A.state.started = true
    A.say('startup', tower_params())
    A.say('taxi', tower_params(), 20)
  elseif name == 'takeoff' and not A.state.airborne then
    A.state.airborne = true
    if F.departure then A.say('departure', tower_params()) end
    if F.gci then A.say('checkin', { callsign = A.callsign() }, 15) end
  elseif name == 'land' then
    A.state.airborne = false
    A.say('landed', tower_params())
  elseif name == 'eject' and F.csar then
    local ref = bulls_point() or u:getPoint()
    local p = u:getPoint()
    A.say('csar', { callsign = A.callsign(), bearing = A.fmt_bearing(A.bearing(ref, p)),
                    range = A.fmt_range(SORTIE.dist2d(ref, p)) })
    SORTIE.emit('csar', { pos = SORTIE.latlon(u) })
  end
end

function A.approach_scan()
  local u = A.player()
  if not u or not u:inAir() or not A.state.airborne or not C.home or A.flightcontrol then return end
  local ok, ab = pcall(Airbase.getByName, C.home.name)
  if not ok or not ab then return end
  local d = SORTIE.dist2d(u:getPoint(), ab:getPoint())
  if d > 60000 then A.state.away = true end
  if A.state.away and d < 40000 and not A.state.inbound then
    A.state.inbound = true
    local p = tower_params()
    p.range = A.fmt_range(d)
    A.say('inbound', p)
  elseif A.state.inbound and d < 12000 and not A.state.cleared then
    A.state.cleared = true
    A.say('landing', tower_params())
  end
end

function A.menu()
  if not missionCommands then return end
  local _, g = A.player()
  if not g then return end
  local gid = g:getID()
  local root = missionCommands.addSubMenuForGroup(gid, 'SORTIE Control')
  local function add(label, fn) missionCommands.addCommandForGroup(gid, label, root, function() SORTIE.safe('atc.menu', fn) end) end
  if F.gci then
    add('Request picture', A.picture)
    add('Bogey dope', A.bogey_dope)
    if F.declare then add('Declare (contact on the nose)', A.declare) end
  end
  add('Vector to home base', function() A.vector('home') end)
  if F.tanker then add('Vector to tanker', function() A.vector('tanker') end) end
  add('Radio check', A.radio_check)
end

if C.enabled then
  SORTIE.safe('atc.voice', A.setup_voice)
  SORTIE.safe('atc.menu', A.menu)
  world.addEventHandler({ onEvent = function(_, event) SORTIE.safe('atc.event', A.on_event, event) end })
  SORTIE.every(C.picture_interval or 120, 'atc.picture', A.picture)
  SORTIE.every(15, 'atc.threat', A.threat_scan)
  SORTIE.every(20, 'atc.approach', A.approach_scan)
  timer.scheduleFunction(function() SORTIE.safe('atc.voice', A.announce_voice) end, nil, timer.getTime() + 20)
  SORTIE.log('ATC/GCI layer active: ' .. tostring(C.procedure) .. ', voice ' .. tostring(C.voice)
    .. ((A.voice and A.voice.ok) and ' (ready)' or ' (text only)'))
end
