-- auto_potion.lua - Eden Overlay example
-- Automatically presses X (use item) every 5 seconds.

local PRESS_DURATION = 50   -- ms to hold button
local INTERVAL       = 5000 -- ms between uses

while true do
    wait(INTERVAL)
    press("X")
    wait(PRESS_DURATION)
    release("X")
end
