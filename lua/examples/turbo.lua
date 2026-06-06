-- turbo.lua - Eden Overlay example
-- Rapidly presses A while the user holds L (turbo fire).
-- API: player:held, press, release, wait

local PID = 1
local ACTIVE   = 50  -- ms A is pressed
local INACTIVE = 50  -- ms A is released

while true do
    if player:held(PID, "L") then
        press("A")
        wait(ACTIVE)
        release("A")
        wait(INACTIVE)
    else
        wait(16)
    end
end
