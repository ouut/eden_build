-- combo_macro.lua - Eden Overlay example
-- Press DDown + RStick to trigger a combo: A → B → X → Y with precise timing.

local combo = { "A", "B", "X", "Y" }
local step_ms = 80  -- ms per button in the combo

while true do
    local down = get_button("DDown")
    local rs   = get_button("RStick")
    if down and rs then
        for _, btn in ipairs(combo) do
            press(btn)
            sleep(step_ms)
            release(btn)
            sleep(step_ms)
        end
        -- Cooldown to prevent re-triggering
        sleep(500)
    else
        sleep(16)
    end
end
