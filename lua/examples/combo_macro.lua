-- combo_macro.lua - Eden Overlay example
-- Hold L + flick left stick to trigger direction-based combos.

local PID = 1
local combo_DOWN  = { "A", "B" }
local combo_UP    = { "X", "Y" }
local combo_RIGHT = { "A", "X" }
local step_ms = 80

local function play_combo(seq)
    for _, btn in ipairs(seq) do
        press(btn)
        wait(step_ms)
        release(btn)
        wait(step_ms)
    end
end

while true do
    if player:held(PID, "L") then
        local lx, ly = player:axis(PID, "left")

        if     ly > 0.7 then play_combo(combo_UP)
        elseif ly < -0.7 then play_combo(combo_DOWN)
        elseif lx > 0.7 then play_combo(combo_RIGHT)
        end
    end
    wait(16)
end
