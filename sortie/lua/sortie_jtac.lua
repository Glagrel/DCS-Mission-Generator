-- SORTIE JTACs. The 9-line comes from DCS itself (the FAC task in the mission file). With MOOSE
-- loaded and autolase on, MOOSE AUTOLASE also lets each JTAC find, smoke and lase targets by
-- itself on its briefed laser code (verified in the vendored Moose_.lua: AUTOLASE:New(RecceSet,
-- Coalition, Alias), :SetRecceLaserCode(name, code), :SetSmokeTargets(on, color),
-- :SetNotifyPilots(on)).
SORTIE.jtac = { lasers = {} }

function SORTIE.jtac.init()
  local rows = SORTIE.cfg.jtacs or {}
  if #rows == 0 then return end
  local side = (SORTIE.cfg.player_side == 1) and 'red' or 'blue'
  for _, r in ipairs(rows) do
    if r.autolase and AUTOLASE and SET_GROUP then
      local ok, err = pcall(function()
        local set = SET_GROUP:New():FilterPrefixes(r.group):FilterStart()
        local al = AUTOLASE:New(set, side, r.callsign)
        al:SetRecceLaserCode(r.group, tonumber(r.code))
        al:SetSmokeTargets(true, trigger.smokeColor.Red)
        al:SetNotifyPilots(true)
        SORTIE.jtac.lasers[#SORTIE.jtac.lasers + 1] = al
      end)
      SORTIE.emit('support', { role = 'jtac', group = r.group, by = ok and 'autolase' or 'fac',
                              err = (not ok) and tostring(err) or nil })
    else
      SORTIE.emit('support', { role = 'jtac', group = r.group, by = 'fac' })
    end
  end
end

SORTIE.safe('jtac.init', SORTIE.jtac.init)
