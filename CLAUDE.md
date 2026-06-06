
# Eden Overlay

## Design rules
- Discuss first, don't implement until user confirms.
- Minimal C++ changes, maximum Lua flexibility.
- Each Lua script = one overlay slot. One OverlayEngine per EmulatedController (player).

## Lua API (target design, not yet implemented)

### Create input source
```lua
p = player.new()                    -- manual, auto slot
p = player.new(slot)                -- manual, fixed slot
u = player.new_udp(port)            -- UDP source, auto slot
u = player.new_udp(port, slot)      -- UDP source, fixed slot
s = player.new_script("x.lua")      -- file script, auto slot, own coroutine
s = player.new_script("x.lua", slot)
```

### Write (handle methods, own slot only)
```lua
p:press("A")                        -- hold button
p:release("A")                      -- release button
p:move("left", x, y)                -- stick, x,y in [-1,1]
p:wait(ms)                          -- pause coroutine
p:kill()                            -- release slot, stop source
```

### Read (player module, final merged controller state)
```lua
player:id()       → int             -- 1, 2, ...
player:held("A")  → bool            -- button pressed?
player:axis("left") → x, y          -- stick position [-1,1]
```

### Context
```lua
game:id()         → u64             -- title ID
game:name()       → string          -- game display name
wait(ms)          -- global pause
```

### Button names
A, B, X, Y, L, R, ZL, ZR, Plus, Minus,
DUp, DDown, DLeft, DRight, LStick, RStick,
SLLeft, SLRight, SRLeft, SRRight

### Concepts
- `player` = module (static read + factory), read-only merged state
- `p/u/s` = handle (instance write), owns one slot
- `game` = globals, current game info
- `wait` = global, coroutine sleep
- No cross-player API. File placement (p1_main.lua / p2_main.lua) decides which engine loads it.

## Current state (already committed)
Old API still in code: press, release, get_button, set_stick, sleep, get_stick,
udp_bind, udp_poll, get_title_id, get_game_name, spawn, ScanAndLoad.
Needs migration to new API above.
