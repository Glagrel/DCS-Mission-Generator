-- SORTIE carrier deck dressing: parked static aircraft on CVN and LHA decks.
--
-- DCS Liberation does not do this on ships at all (it only parks idle aircraft at airfields),
-- because statics on the wrong deck spots stop the deck crew and the AI: aircraft that cannot
-- find a spot will not spawn, and a static on a spot in a catapult's path blocks that catapult.
-- SORTIE does it at run time from the ship's own parking table instead of guessing positions:
--   * Airbase:getParking(true) lists the deck spots that are still FREE after the mission's
--     aircraft have spawned, with their positions.
--   * `reserve` spots (sent by SORTIE: every aircraft that will spawn on or recover to this deck
--     during the mission, plus a margin) are always left empty, so the AI never runs out.
--   * On a CVN only spots well to starboard of the centreline are used (the bow catapults and
--     the angled landing deck are on and to port of it), aft of the bow catapults' run;
--     on an LHA only spots right of the centreline, away from the landing spots along the port side.
--   * Each static is linked to the ship (linkUnit / linkOffset), so it moves with the deck.
SORTIE.deck = { placed = {} }

local function local_offset(ship, pos)
  local p = ship:getPosition()
  local dx, dz = pos.x - p.p.x, pos.z - p.p.z
  local along = dx * p.x.x + dz * p.x.z          -- + forward
  local across = dx * p.z.x + dz * p.z.z         -- + starboard
  local heading = math.atan2(p.x.z, p.x.x)
  return along, across, heading
end

-- Which free spots may hold a static, best first.
function SORTIE.deck.candidates(ship, spots, kind)
  local out = {}
  for _, s in ipairs(spots or {}) do
    local pos = s.vTerminalPos
    if pos then
      local along, across = local_offset(ship, pos)
      local ok
      if kind == 'lha' then
        ok = across > 4
      else
        ok = across > 12 and along < 60            -- starboard side, aft of the bow catapults' run
      end
      if ok then out[#out + 1] = { spot = s, along = along, across = across, pos = pos } end
    end
  end
  table.sort(out, function(a, b) return a.across > b.across end)   -- the deck edge first
  return out
end

function SORTIE.deck.dress(entry)
  local ship = Unit.getByName(entry.carrier_unit)
  if not ship or not ship:isExist() then return end
  local ab = Airbase.getByName(entry.carrier_unit)
  if not ab then return end
  local ok, free = pcall(function() return ab:getParking(true) end)
  if not ok or not free then return end
  local room = #free - (entry.reserve or 0)
  local n = math.min(entry.max or 0, room, #(entry.types or {}))
  if n <= 0 then
    SORTIE.emit('deck', { carrier = entry.carrier_unit, placed = 0, free = #free, reserve = entry.reserve })
    return
  end
  local cands = SORTIE.deck.candidates(ship, free, entry.kind)
  local _, _, heading = local_offset(ship, ship:getPoint())
  local country = ship:getCountry()
  local placed = 0
  for i = 1, math.min(n, #cands) do
    local c = cands[i]
    local name = string.format('S|deck|%s|%d', entry.carrier_unit, i)
    local rel = (c.across > 0) and -math.pi / 2 or math.pi / 2     -- nose inboard, tail over the edge
    local okAdd = pcall(function()
      coalition.addStaticObject(country, {
        type = entry.types[i], name = name, category = 'Planes',
        x = c.pos.x, y = c.pos.z, heading = heading + rel,
        linkUnit = ship:getID(), linkOffset = true,
        offsets = { x = c.along, y = c.across, angle = rel },
        livery_id = (entry.liveries or {})[entry.types[i]],
      })
    end)
    if okAdd then
      placed = placed + 1
      SORTIE.deck.placed[#SORTIE.deck.placed + 1] = name
    end
  end
  SORTIE.emit('deck', { carrier = entry.carrier_unit, placed = placed, free = #free, reserve = entry.reserve })
end

function SORTIE.deck.init()
  local decks = SORTIE.cfg.deck or {}
  if #decks == 0 then return end
  -- a moment after start, once every group that spawns at mission start is on its spot
  timer.scheduleFunction(function()
    for _, entry in ipairs(decks) do SORTIE.safe('deck.dress', SORTIE.deck.dress, entry) end
    return nil
  end, nil, timer.getTime() + 2)
end

SORTIE.safe('deck.init', SORTIE.deck.init)
