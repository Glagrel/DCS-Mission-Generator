-- SORTIE: minimal JSON encoder (Lua 5.1, no external libraries).
-- Encodes nil/boolean/number/string/table. Tables with keys 1..n become arrays, everything
-- else becomes an object with string keys. NaN/inf become null. Cycles are cut at depth 12.
SORTIE = SORTIE or {}
SORTIE.json = {}

local escapes = { ['"'] = '\\"', ['\\'] = '\\\\', ['\b'] = '\\b', ['\f'] = '\\f',
                  ['\n'] = '\\n', ['\r'] = '\\r', ['\t'] = '\\t' }

local function esc_char(c)
  return escapes[c] or string.format('\\u%04x', string.byte(c))
end

local function enc_string(s)
  return '"' .. string.gsub(s, '[%c"\\]', esc_char) .. '"'
end

local function is_array(t)
  local n = 0
  for k, _ in pairs(t) do
    if type(k) ~= 'number' or k <= 0 or math.floor(k) ~= k then return false end
    n = n + 1
  end
  return n > 0 and n == #t
end

local function encode(v, depth)
  local tv = type(v)
  if v == nil then return 'null' end
  if tv == 'boolean' then return v and 'true' or 'false' end
  if tv == 'number' then
    if v ~= v or v == math.huge or v == -math.huge then return 'null' end
    if math.floor(v) == v and math.abs(v) < 1e15 then return string.format('%d', v) end
    return string.format('%.6g', v)
  end
  if tv == 'string' then return enc_string(v) end
  if tv == 'table' then
    if depth > 12 then return 'null' end
    local out = {}
    if is_array(v) then
      for i = 1, #v do out[#out + 1] = encode(v[i], depth + 1) end
      return '[' .. table.concat(out, ',') .. ']'
    end
    local keys = {}
    for k, _ in pairs(v) do keys[#keys + 1] = k end
    table.sort(keys, function(a, b) return tostring(a) < tostring(b) end)
    for _, k in ipairs(keys) do
      local val = v[k]
      local tval = type(val)
      if tval ~= 'function' and tval ~= 'userdata' and tval ~= 'thread' then
        out[#out + 1] = enc_string(tostring(k)) .. ':' .. encode(val, depth + 1)
      end
    end
    return '{' .. table.concat(out, ',') .. '}'
  end
  return 'null'   -- functions, userdata, threads
end

function SORTIE.json.encode(v)
  return encode(v, 0)
end
