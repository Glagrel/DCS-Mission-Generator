-- Minimal fake of the DCS mission scripting environment for running SORTIE's Lua under
-- plain Lua 5.1 (via lupa) in pytest. Only what the SORTIE scripts call is implemented.
MOCK = { time = 0, scheduled = {}, handlers = {}, groups = {}, airbases = {}, players = {},
         texts = {}, log = {}, errors = {}, dir = MOCK_DIR or '' }

env = {
  info = function(s) MOCK.log[#MOCK.log + 1] = s end,
  error = function(s) MOCK.errors[#MOCK.errors + 1] = s end,
  warning = function(s) MOCK.log[#MOCK.log + 1] = s end,
}
timer = {
  getTime = function() return MOCK.time end,
  scheduleFunction = function(fn, arg, t) MOCK.scheduled[#MOCK.scheduled + 1] = { fn = fn, arg = arg, t = t } end,
}
world = {
  event = { S_EVENT_SHOT = 1, S_EVENT_HIT = 2, S_EVENT_TAKEOFF = 3, S_EVENT_LAND = 4, S_EVENT_CRASH = 5,
            S_EVENT_EJECTION = 6, S_EVENT_REFUELING = 7, S_EVENT_DEAD = 8, S_EVENT_PILOT_DEAD = 9,
            S_EVENT_BASE_CAPTURED = 10, S_EVENT_MISSION_START = 11, S_EVENT_MISSION_END = 12,
            S_EVENT_BIRTH = 15, S_EVENT_ENGINE_STARTUP = 18, S_EVENT_PLAYER_ENTER_UNIT = 20,
            S_EVENT_PLAYER_LEAVE_UNIT = 21, S_EVENT_KILL = 28, S_EVENT_UNIT_LOST = 30,
            S_EVENT_LANDING_AFTER_EJECTION = 31 },
  addEventHandler = function(h) MOCK.handlers[#MOCK.handlers + 1] = h end,
}
coalition = {
  side = { NEUTRAL = 0, RED = 1, BLUE = 2 },
  getGroups = function(side, cat)
    local out = {}
    for _, g in pairs(MOCK.groups) do
      if g.side == side and (cat == nil or g.cat == cat) and g.exists and g.active then out[#out + 1] = g end
    end
    return out
  end,
  getPlayers = function(side)
    local out = {}
    for _, u in ipairs(MOCK.players) do if u.c == side then out[#out + 1] = u end end
    return out
  end,
}
Group = { Category = { AIRPLANE = 0, HELICOPTER = 1, GROUND = 2, SHIP = 3 },
          getByName = function(n) return MOCK.groups[n] end }
Object = { Category = { UNIT = 1, WEAPON = 2, STATIC = 3, BASE = 4, SCENERY = 5 } }
MOCK.statics = {}
coalition.addStaticObject = function(country, t) MOCK.statics[#MOCK.statics + 1] = t; return t end
Unit = { getByName = function(n)
  for _, g in pairs(MOCK.groups) do
    for _, u in ipairs(g.units) do if u.name == n and g.exists then return u end end
  end
  return nil
end }
Airbase = { getByName = function(n) return MOCK.airbases[n] end }
trigger = { action = {
  outTextForGroup = function(id, text, secs) MOCK.texts[#MOCK.texts + 1] = { group = id, text = text } end,
  outTextForCoalition = function(side, text, secs) MOCK.texts[#MOCK.texts + 1] = { side = side, text = text } end,
  outText = function(text, secs) MOCK.texts[#MOCK.texts + 1] = { text = text } end,
} }
coord = {
  LOtoLL = function(p) return p.x / 111000, p.z / 111000, p.y end,
  LLtoLO = function(lat, lon, alt) return { x = lat * 111000, y = alt or 0, z = lon * 111000 } end,
}
radio = { modulation = { AM = 0, FM = 1 } }
MOCK.menu = {}
missionCommands = {
  addSubMenuForGroup = function(gid, name) return { name } end,
  addCommandForGroup = function(gid, name, path, fn) MOCK.menu[name] = fn end,
}
if MOCK_SANITIZED then
  io, lfs, os = nil, nil, nil
else
  lfs = { writedir = function() return MOCK.dir end, mkdir = function(p) return nil, 'exists' end }
end

function MOCK.unit(t)
  local u = { name = t.name, ty = t.type or 'F-15C', c = t.coalition or 2, player = t.player,
              x = t.x or 0, z = t.z or 0, alt = t.alt or 0, air = t.air or false, ammo = t.ammo or {},
              cat = t.cat or Object.Category.UNIT, group = nil }
  function u:getName() return self.name end
  function u:getTypeName() return self.ty end
  function u:getCoalition() return self.c end
  function u:getCategory() return self.cat end
  function u:getGroup() return self.group end
  function u:getPlayerName() return self.player end
  function u:getPoint() return { x = self.x, y = self.alt, z = self.z } end
  function u:inAir() return self.air end
  function u:getVelocity() return { x = t.vx or 0, y = 0, z = t.vz or 0 } end
  function u:getFuel() return 0.8 end
  function u:isExist() return true end
  function u:getID() return t.id or 99 end
  function u:getCountry() return t.country or 2 end
  -- heading 0 = facing +x (north); +z is to the right (starboard)
  function u:getPosition()
    local h = t.heading or 0
    return { p = { x = self.x, y = self.alt, z = self.z }, x = { x = math.cos(h), y = 0, z = math.sin(h) },
             y = { x = 0, y = 1, z = 0 }, z = { x = -math.sin(h), y = 0, z = math.cos(h) } }
  end
  function u:getLife() return 100 end
  function u:getAmmo()
    local out = {}
    for name, n in pairs(self.ammo) do out[#out + 1] = { count = n, desc = { typeName = name } } end
    return out
  end
  if t.player then MOCK.players[#MOCK.players + 1] = u end
  return u
end

function MOCK.group(t)
  local g = { name = t.name, side = t.side or 2, cat = t.cat or Group.Category.AIRPLANE, units = t.units or {},
              exists = true, active = not t.late, id = t.id or 1 }
  for _, u in ipairs(g.units) do u.group = g end
  function g:getName() return self.name end
  function g:getID() return self.id end
  function g:isExist() return self.exists end
  function g:getUnits() return self.units end
  function g:getSize() return #self.units end
  function g:activate() self.active = true end
  function g:destroy() self.exists = false end
  MOCK.groups[g.name] = g
  return g
end

function MOCK.airbase(name, weapons, liquids, unlimited)
  local wh = { weapon = weapons or {}, liquids = liquids or { [0] = 1000, [1] = 100, [2] = 0, [3] = 50 },
               aircraft = {}, sets = 0 }
  function wh:getInventory()
    if unlimited then return { weapon = {}, liquids = {}, aircraft = {} } end
    local w = {}
    for k, v in pairs(self.weapon) do w[k] = v end
    return { weapon = w, liquids = self.liquids, aircraft = self.aircraft }
  end
  function wh:setItem(item, n) self.weapon[item] = n; self.sets = self.sets + 1 end
  function wh:getItemCount(item) return self.weapon[item] or 0 end
  function wh:getLiquidAmount(i) return self.liquids[i] end
  local ab = { name = name, wh = wh, c = 2 }
  function ab:getWarehouse() return self.wh end
  function ab:getName() return self.name end
  function ab:getCoalition() return self.c end
  function ab:getPoint() return { x = self.x or 0, y = 0, z = self.z or 0 } end
  function ab:getParking(available)
    local out = {}
    for _, s in ipairs(self.spots or {}) do
      if not available or not s.TO_AC then out[#out + 1] = s end
    end
    return out
  end
  MOCK.airbases[name] = ab
  return ab
end

-- Advance mission time, running scheduled functions like DCS does (fn returns next time or nil).
function MOCK.advance(dt)
  local target = MOCK.time + dt
  while true do
    local nxt = nil
    for i, s in ipairs(MOCK.scheduled) do
      if s.t <= target and (nxt == nil or s.t < MOCK.scheduled[nxt].t) then nxt = i end
    end
    if not nxt then break end
    local s = table.remove(MOCK.scheduled, nxt)
    MOCK.time = math.max(MOCK.time, s.t)
    local again = s.fn(s.arg, MOCK.time)
    if again then MOCK.scheduled[#MOCK.scheduled + 1] = { fn = s.fn, arg = s.arg, t = again } end
  end
  MOCK.time = target
end

function MOCK.fire(event)
  for _, h in ipairs(MOCK.handlers) do h:onEvent(event) end
end
