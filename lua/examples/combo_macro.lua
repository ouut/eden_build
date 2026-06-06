-- combo_macro.lua - Eden Overlay example
-- Hold L + flick stick to trigger direction-based combos.
-- API: player:held, player:axis (left + right), press, release, wait

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
        -- player:axis(id, "left") → x, y in [-1, 1]
        local lx, ly = player:axis(PID, "left")

        if     ly > 0.7 then play_combo(combo_UP)
        elseif ly < -0.7 then play_combo(combo_DOWN)
        elseif lx > 0.7 then play_combo(combo_RIGHT)
        end

        -- player:axis(id, "right") → x, y
        local rx, ry = player:axis(PID, "right")
        if rx > 0.7 then
            press("ZR")
            wait(step_ms)
            release("ZR")
        end
    end
    wait(16)
end
