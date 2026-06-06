-- motion_aim.lua - Eden Overlay example
-- Compensate camera movement by writing counter-motion.
-- API: player:motion (read), motion + move (write)

local PID = 1
local DEADZONE = 0.05

local function dead(v)
    return (v > DEADZONE or v < -DEADZONE) and v or 0.0
end

while true do
    -- player:motion(id, "left") → gx, gy, gz, ax, ay, az
    local gx, gy, gz, ax, ay, az = player:motion(PID, "left")

    -- Invert gyro to stabilize camera
    motion("left", -dead(gx), -dead(gy), -dead(gz),
                    -dead(ax), -dead(ay), -dead(az))

    -- player:motion(id, "right") → gx, gy, gz, ax, ay, az
    local rgx, rgy, rgz, rax, ray, raz = player:motion(PID, "right")
    motion("right", -dead(rgx), -dead(rgy), -dead(rgz),
                     -dead(rax), -dead(ray), -dead(raz))

    -- Also nudge left stick based on right joycon tilt
    move("left", -rgx, -rgy)

    wait(8)  -- ~120Hz poll
end
