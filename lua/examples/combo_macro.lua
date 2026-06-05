-- combo_macro.lua - Eden Overlay example
-- Hold L + flick left stick → direction-triggered combos.
-- Demonstrates get_stick() to read the final merged stick state.

local combo_DOWN   = { "A", "B" }        -- down  → A→B
local combo_UP     = { "X", "Y" }        -- up    → X→Y
local combo_RIGHT  = { "A", "X" }        -- right → A→X
local step_ms = 80   -- ms per button

-- Which combo is active (nil = none)
local active = nil

local function play_combo(seq)
    for _, btn in ipairs(seq) do
        press(btn)
        sleep(step_ms)
        release(btn)
        sleep(step_ms)
    end
end

while true do
    if get_button("L") and not active then
        local lx, ly = get_stick("left")

        if     ly > 0.7 then active = combo_UP
        elseif ly < -0.7 then active = combo_DOWN
        elseif lx > 0.7 then active = combo_RIGHT
        end

        if active then
            play_combo(active)
            active = nil
            sleep(300)  -- cooldown
        end
    end

    sleep(16)
end
