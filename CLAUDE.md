
# Eden Overlay

## Design rules
- Discuss first, don't implement until user confirms.
- Minimal C++ changes, maximum Lua flexibility.
- One entry Lua script. Global engine table routes player_id to the correct controller.
- Each `player.new(...)` allocates one overlay slot on the target player's controller.

## Architecture
```
C++ side (once):
  Global registry: engines = {engine0 → controller[0], engine1 → controller[1], ...}
  Lua can reach any player by id.

Lua side:
  main.lua loaded once, then:
    p = player.new(1)        → routes to engine0, writes to controller[0] slot
    p = player.new(2)        → routes to engine1, writes to controller[1] slot
```

## Lua API (target design, not yet implemented)

### Create input source
```lua
p = player.new(player_id)                       -- manual, auto slot
p = player.new(player_id, slot)                 -- manual, fixed slot
u = player.new_udp(player_id, port)             -- UDP source, auto slot
u = player.new_udp(player_id, port, slot)       -- UDP source, fixed slot
s = player.new_script(player_id, "x.lua")       -- file, auto slot, own coroutine
s = player.new_script(player_id, "x.lua", slot) -- file, fixed slot
```

### Write (handle methods, own slot only)
```lua
p:press("A")                                        -- hold button
p:release("A")                                      -- release button
p:move("left", x, y)                                -- stick, x,y in [-1,1]
p:motion("left", gx, gy, gz, ax, ay, az)            -- gyro + accel, left joycon
p:motion("right", gx, gy, gz, ax, ay, az)           -- gyro + accel, right joycon
p:wait(ms)                                          -- pause this coroutine
p:kill()                                            -- release slot, stop source
```

All writes are last-write-wins by timestamp when multiple slots write the same field.

### Read (final merged controller state)
```lua
player:held(player_id, "A")   → bool                -- button pressed?
player:axis(player_id, "left") → x, y               -- stick position [-1,1]
player:motion(player_id, "left")  → gx,gy,gz,ax,ay,az
player:motion(player_id, "right") → gx,gy,gz,ax,ay,az
```

### Context
```lua
game:id()         → u64                          -- title ID
game:name()       → string                       -- game display name
wait(ms)          -- global pause
```

### Button names
A, B, X, Y, L, R, ZL, ZR, Plus, Minus,
DUp, DDown, DLeft, DRight, LStick, RStick,
SLLeft, SLRight, SRLeft, SRRight

### Concepts
- `player` = module, factory + read. `player.new(id)` creates a handle routed to that player.
- `p/u/s` = handle, writes to one slot on one player. `press("A")` writes to handle's slot.
- `player:held(id, btn)` / `player:axis(id, stick)` reads merged state of the specified player.
- `game` = globals, current game info.
- `wait` = global, coroutine sleep.
- player_id always explicit. No implicit "current player".

## Current state (already committed)
Old API still in code: press, release, get_button, set_stick, sleep, get_stick,
udp_bind, udp_poll, get_title_id, get_game_name, spawn, ScanAndLoad.
Needs migration to new API above.
