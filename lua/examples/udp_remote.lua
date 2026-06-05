-- udp_remote.lua - Eden Overlay example
-- Receives UDP input packets via built-in udp_bind/udp_poll (no external deps).
-- Packet format (24 bytes, little-endian):
--   [0]     magic  "OVER" (4 bytes)
--   [4]     button_mask  u32 (NpadButton bits)
--   [8]     left_x       f32
--   [12]    left_y       f32
--   [16]    right_x      f32
--   [20]    right_y      f32
--
-- Test sender (Python):
--   import socket, struct
--   s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
--   s.sendto(struct.pack('<4sIffff', b'OVER', 0x0001, -1.0, 0.0, 0.0, 0.0),
--            ('127.0.0.1', 26760))

local PORT = 26760

-- Bitwise helper: Lua 5.3+ has &, LuaJIT needs bit library
local band = load("return function(a,b) return a & b end")()
if not band then
    local bit = require("bit")
    band = bit.band
end

-- Little-endian unpack helpers
local function le_u32(s, i)
    return s:byte(i) + s:byte(i+1)*256 + s:byte(i+2)*65536 + s:byte(i+3)*16777216
end

local function le_f32(s, i)
    local b = le_u32(s, i)
    if b == 0 then return 0.0 end
    local sign = (b >> 31) & 1
    local exp  = (b >> 23) & 0xFF
    if exp == 0xFF then return 0.0 end   -- inf/nan → 0
    local mant = b & 0x7FFFFF
    return (1 - 2*sign) * (1.0 + mant / 0x800000) * 2.0^(exp - 127)
end

-- Button bit → name (NpadButton)
local BTNS = {
    {0x0001, "A"},      {0x0002, "B"},      {0x0004, "X"},
    {0x0008, "Y"},      {0x0010, "LStick"}, {0x0020, "RStick"},
    {0x0040, "L"},      {0x0080, "R"},      {0x0100, "ZL"},
    {0x0200, "ZR"},     {0x0400, "Plus"},   {0x0800, "Minus"},
    {0x1000, "DLeft"},  {0x2000, "DUp"},    {0x4000, "DRight"},
    {0x8000, "DDown"},
}

assert(udp_bind(PORT), "udp_bind failed")

while true do
    -- Drain queue, keep newest
    local last
    while true do
        local d = udp_poll()
        if not d then break end
        last = d
    end

    if last and #last >= 24 then
        local m = last:sub(1, 4)
        if m == "OVER" then
            local btn = le_u32(last, 5)
            local lx  = le_f32(last, 9)
            local ly  = le_f32(last, 13)
            local rx  = le_f32(last, 17)
            local ry  = le_f32(last, 21)

            for _, tb in ipairs(BTNS) do
                if band(btn, tb[1]) ~= 0 then
                    press(tb[2])
                else
                    release(tb[2])
                end
            end
            set_stick("left",  lx, ly)
            set_stick("right", rx, ry)
        end
    end

    sleep(16)
end
