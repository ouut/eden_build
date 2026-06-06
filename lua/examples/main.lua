-- main.lua - Eden Overlay entry point
-- The only file loaded by C++. Spawn sub-scripts — each in its own slot.

-- Auto slot (any free slot)
spawn("overlay_scripts/turbo.lua")

-- Explicit slot — useful for scripts that need a stable slot number
-- (e.g. UDP remote always gets slot 7)
spawn("overlay_scripts/udp_remote.lua", 7)

-- Per-game: spawn game-specific helpers
local name = get_game_name()
if name and name:find("Zelda") then
    spawn("overlay_scripts/zelda.lua", 3)
end

-- Main sleeps forever
while true do sleep(99999999) end
