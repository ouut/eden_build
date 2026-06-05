-- turbo_attack.lua - Eden Overlay example
-- Rapidly presses A while the user holds L (turbo fire).

local ACTIVE   = 50  -- ms A is pressed
local INACTIVE = 50  -- ms A is released

while true do
    if get_button("L") then
        press("A")
        sleep(ACTIVE)
        release("A")
        sleep(INACTIVE)
    else
        sleep(16)  -- ~60fps poll
    end
end
