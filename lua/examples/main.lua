-- main.lua - Eden Overlay entry point
-- The only file loaded by C++. Spawn sub-scripts — each in its own slot.

local PID = 1  -- player 1

-- Auto slot (any free slot)
player.new_script(PID, "overlay_scripts/turbo.lua")

-- Explicit slot — useful for scripts that need a stable slot number
player.new_script(PID, "overlay_scripts/udp_remote.lua", 7)

-- Per-game: spawn game-specific helpers
local name = game.name()
if name and name:find("Zelda") then
    player.new_script(PID, "overlay_scripts/zelda.lua", 3)
end

-- Main sleeps forever
while true do wait(99999999) end
