-- auto_potion.lua - Eden Overlay example
-- Automatically presses X (use item) for health potion every 5 seconds.

local PRESS_DURATION = 50   -- ms to hold button
local INTERVAL       = 5000 -- ms between potions

while true do
    sleep(INTERVAL)
    press("X")
    sleep(PRESS_DURATION)
    release("X")
end
