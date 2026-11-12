-- SORTIE carrier flight-operations support.
-- The recovery tanker uses DCS's own "Recovery Tanker" task (set in the mission file).
-- The plane-guard helicopter has no native task that keeps station on a moving ship, so when
-- MOOSE is loaded it is handed to MOOSE's RESCUEHELO (verified in the vendored Moose_.lua:
-- RESCUEHELO:New(carrierunit, helogroupname), :SetTakeoffAir(), :SetRespawnOff(), :Start()).
-- Without MOOSE the helicopter simply flies the racetrack given to it in the mission file.
SORTIE.carrier = { helos = {} }

function SORTIE.carrier.init()
  for _, entry in ipairs(SORTIE.cfg.carrier_support or {}) do
    if entry.role == 'plane_guard' and RESCUEHELO and entry.moose then
      local ok, err = pcall(function()
        local helo = RESCUEHELO:New(entry.carrier_unit, entry.group)
        helo:SetTakeoffAir()
        helo:SetRespawnOff()
        helo:Start()
        SORTIE.carrier.helos[#SORTIE.carrier.helos + 1] = helo
      end)
      if ok then
        SORTIE.emit('support', { role = 'plane_guard', group = entry.group, carrier = entry.carrier_unit, by = 'moose' })
      else
        SORTIE.log('RESCUEHELO failed (' .. tostring(err) .. '); activating the helicopter on its own route')
        pcall(function() Group.getByName(entry.group):activate() end)
      end
    elseif entry.role == 'plane_guard' then
      -- no MOOSE: make sure the group is active and let it fly its own racetrack
      pcall(function()
        local g = Group.getByName(entry.group)
        if g then g:activate() end
      end)
      SORTIE.emit('support', { role = 'plane_guard', group = entry.group, carrier = entry.carrier_unit, by = 'route' })
    end
  end
end

SORTIE.safe('carrier.init', SORTIE.carrier.init)
