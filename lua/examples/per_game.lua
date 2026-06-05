-- per_game.lua - Eden Overlay example
-- Different behavior per game using get_title_id() / get_game_name().
-- Put all game-specific logic in one file, or split into separate files.

local ZELDA_BOTW = 0x01007EF00011E000   -- Breath of the Wild
local SMASH     = 0x01006A800016E000   -- Super Smash Bros. Ultimate

local function in_game(name)
    local n = get_game_name()
    return n and n:find(name)
end

while true do
    -- Option A: match by name (human-readable, easier)
    if in_game("Zelda") then
        -- BotW: hold ZL + A for flurry rush timing
        if get_button("ZL") then
            press("A")
            sleep(50)
            release("A")
            sleep(50)
        end
    elseif in_game("Smash") then
        -- Smash: auto short-hop (B → release quickly)
        if get_button("L") then
            press("B")
            sleep(30)
            release("B")
            sleep(100)
        end
    end

    -- Option B: match by exact title ID
    local id = get_title_id()
    if id == ZELDA_BOTW then
        -- BotW-specific logic
    end

    sleep(16)
end
