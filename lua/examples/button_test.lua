-- button_test.lua - Eden Overlay example
-- Presses every supported button in sequence. Useful for testing.
-- API: press, release, wait (coroutine globals)

local BUTTONS = {
    "A", "B", "X", "Y",
    "L", "R", "ZL", "ZR",
    "Plus", "Minus",
    "DUp", "DDown", "DLeft", "DRight",
    "LStick", "RStick",
    "SLLeft", "SLRight", "SRLeft", "SRRight",
}

local HOLD_MS = 200
local GAP_MS  = 100

while true do
    for _, btn in ipairs(BUTTONS) do
        press(btn)
        wait(HOLD_MS)
        release(btn)
        wait(GAP_MS)
    end
    wait(2000)  -- pause between cycles
end
