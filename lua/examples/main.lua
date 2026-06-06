-- main.lua - Eden Overlay entry point
-- The only file loaded by C++. Spawn sub-scripts and create handles.

local PID = 1  -- player 1

-- ============================================================
-- player.new_script(id, path) — auto slot, coroutine
-- player.new_script(id, path, slot) — fixed slot
-- ============================================================

player.new_script(PID, "overlay_scripts/turbo.lua")
player.new_script(PID, "overlay_scripts/auto_potion.lua")
player.new_script(PID, "overlay_scripts/combo_macro.lua")
player.new_script(PID, "overlay_scripts/motion_aim.lua")

-- Fixed slot for UDP remote (stable slot number)
player.new_script(PID, "overlay_scripts/udp_remote.lua", 7)

-- ============================================================
-- player.new(id) — manual handle, auto slot
-- player.new(id, slot) — manual handle, fixed slot
-- Handle methods: press, release, move, motion, wait, kill
-- ============================================================

-- Permanent RStick press (game-specific: keep camera locked)
local toggle = player.new(PID)
toggle:press("RStick")

-- Permanent DUp on fixed slot 6
local dpad = player.new(PID, 6)
dpad:press("DUp")

-- ============================================================
-- game.name() — current game display name
-- game.id() — current program ID (see per_game.lua for details)
-- ============================================================

local name = game.name()
if name and name:find("Zelda") then
    player.new_script(PID, "overlay_scripts/per_game.lua", 3)
end

-- Main sleeps forever
while true do wait(99999999) end
