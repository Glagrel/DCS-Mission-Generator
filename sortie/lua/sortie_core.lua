-- SORTIE core: event file writer, safe-call wrapper, helpers. Loaded after sortie_config.lua
-- and sortie_json.lua. Needs a desanitised MissionScripting.lua (io, lfs) to write the event
-- file; without it every event goes to dcs.log as "SORTIE_EVT {json}" instead.
SORTIE = SORTIE or {}
SORTIE.cfg = SORTIE.cfg or {}
SORTIE.seq = 0
SORTIE.file = nil
SORTIE.mode = 'log'      -- 'file' when io/lfs are available
SORTIE.run = tostring((os and os.time and os.time()) or math.random(100000, 999999))

function SORTIE.log(msg)
  env.info('SORTIE: ' .. tostring(msg))
end

-- Run fn(...) and never let an error escape into the mission.
function SORTIE.safe(name, fn, ...)
  local ok, err = pcall(fn, ...)
  if not ok then env.error('SORTIE error in ' .. tostring(name) .. ': ' .. tostring(err)) end
  return ok, err
end

function SORTIE.open()
  if not (io and lfs and lfs.writedir) then
    SORTIE.log('io/lfs not available (MissionScripting.lua is sanitised). Events go to dcs.log only.')
    return false
  end
  local dir = lfs.writedir() .. (SORTIE.cfg.runtime_subdir or 'Missions\\SORTIE\\runtime\\')
  -- create each level; lfs.mkdir fails harmlessly when the folder exists
  local path = ''
  for part in string.gmatch(dir, '[^\\/]+[\\/]?') do
    path = path .. part
    if not string.find(part, ':') then pcall(lfs.mkdir, path) end
  end
  local f, err = io.open(dir .. (SORTIE.cfg.events_file or 'events.jsonl'), 'w')
  if not f then
    SORTIE.log('cannot open event file: ' .. tostring(err))
    return false
  end
  SORTIE.file, SORTIE.mode = f, 'file'
  SORTIE.log('writing events to ' .. dir .. (SORTIE.cfg.events_file or 'events.jsonl'))
  return true
end

-- Write one event as one JSON line and flush immediately.
function SORTIE.emit(ev, data)
  data = data or {}
  SORTIE.seq = SORTIE.seq + 1
  data.ev = ev
  data.t = timer.getTime()
  data.id = tostring(SORTIE.cfg.sortie or 'x') .. '-' .. SORTIE.run .. '-' .. SORTIE.seq
  local ok, line = pcall(SORTIE.json.encode, data)
  if not ok then
    env.error('SORTIE json error: ' .. tostring(line))
    return
  end
  if SORTIE.file then
    local wok = pcall(function()
      SORTIE.file:write(line, '\n')
      SORTIE.file:flush()
    end)
    if not wok then SORTIE.file = nil; SORTIE.mode = 'log' end
  end
  if not SORTIE.file then env.info('SORTIE_EVT ' .. line) end
end

function SORTIE.close()
  if SORTIE.file then pcall(function() SORTIE.file:close() end); SORTIE.file = nil end
end

-- Describe a unit/static/weapon object for an event. Never throws.
function SORTIE.ref(obj)
  if not obj then return nil end
  local r = {}
  pcall(function() r.n = obj:getName() end)
  pcall(function() r.ty = obj:getTypeName() end)
  pcall(function() r.c = obj:getCoalition() end)
  pcall(function() r.cat = obj:getCategory() end)
  pcall(function()
    local g = obj.getGroup and obj:getGroup()
    if g then r.g = g:getName() end
  end)
  pcall(function()
    local p = obj.getPlayerName and obj:getPlayerName()
    if p then r.p = p end
  end)
  return r
end

function SORTIE.latlon(obj)
  local out
  pcall(function()
    local p = obj:getPoint()
    local lat, lon, alt = coord.LOtoLL(p)
    out = { lat = lat, lon = lon, alt = p.y }
  end)
  return out
end

function SORTIE.dist2d(a, b)
  local dx, dz = a.x - b.x, a.z - b.z
  return math.sqrt(dx * dx + dz * dz)
end

-- All human-controlled units currently alive, both coalitions.
function SORTIE.players()
  local out = {}
  for _, side in ipairs({ coalition.side.RED, coalition.side.BLUE }) do
    local ok, list = pcall(coalition.getPlayers, side)
    if ok and list then
      for _, u in ipairs(list) do out[#out + 1] = u end
    end
  end
  return out
end

-- Text to the player's group (falls back to the whole coalition).
function SORTIE.message(text, seconds)
  local shown = false
  pcall(function()
    local g = Group.getByName(SORTIE.cfg.player_group or '')
    if g and g:isExist() then
      trigger.action.outTextForGroup(g:getID(), text, seconds or 12)
      shown = true
    end
  end)
  if not shown then
    pcall(trigger.action.outTextForCoalition, SORTIE.cfg.player_side or 2, text, seconds or 12)
  end
end

-- Repeat fn every `interval` seconds, shielded by pcall.
function SORTIE.every(interval, name, fn)
  timer.scheduleFunction(function(_, time)
    SORTIE.safe(name, fn)
    return time + interval
  end, nil, timer.getTime() + interval)
end

SORTIE.safe('open', SORTIE.open)
SORTIE.emit('mission_start', {
  campaign = SORTIE.cfg.campaign, turn = SORTIE.cfg.turn, sortie = SORTIE.cfg.sortie,
  run = SORTIE.run, mode = SORTIE.mode, version = SORTIE.cfg.version,
})
