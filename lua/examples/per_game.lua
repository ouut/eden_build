-- per_game.lua - Eden Overlay example
-- Different behavior per game using game.name() / game.id().

local PID = 1
local ZELDA_BOTW = 0x01007EF00011E000

while true do
    local name = game.name()
    local id = game.id()

    if name and name:find("Zelda") then
        -- BotW: hold ZL → rapid A for flurry rush
        if player:held(PID, "ZL") then
            press("A")
            wait(50)
            release("A")
            wait(50)
        end
    end

    -- Exact title ID match
    if id == ZELDA_BOTW then
        -- BotW-specific logic here
    end

    wait(16)
end
