-- main.lua - Eden Overlay entry point
-- The ONLY file loaded by C++ (LoadScript("main.lua")).
-- Spawn sub-scripts — each gets its own coroutine + slot.

spawn("overlay_scripts/turbo.lua")
spawn("overlay_scripts/auto_potion.lua")
spawn("overlay_scripts/combo.lua")
spawn("overlay_scripts/udp_remote.lua")

-- Per-game spawning
local name = get_game_name()
if name and name:find("Zelda") then
    spawn("overlay_scripts/zelda_combos.lua")
elseif name and name:find("Smash") then
    spawn("overlay_scripts/smash_tech.lua")
end

-- Main sleeps forever. Sub-scripts run independently.
while true do
    sleep(99999999)
end
