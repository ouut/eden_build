# Eden Overlay

Eden Switch 模拟器的多输入源叠加系统，Lua 驱动，类似 reWASD。

## 快速开始

```
eden
overlay_scripts/          ← 放 .lua 脚本
├── main.lua              ← 入口
├── turbo.lua
├── udp_remote.lua
└── ...
```

运行：
```bash
./scripts/apply_overlay.sh /path/to/eden/source
# 然后正常构建 Eden
```

## Lua API

### 创建输入源（player module）

```lua
h = player.new(id)              -- 手动句柄，自动分配 slot
h = player.new(id, slot)        -- 手动句柄，指定 slot
u = player.new_udp(id, port)    -- UDP 接收，自动 slot
u = player.new_udp(id, port, slot)
s = player.new_script(id, path)       -- Lua 脚本，自动 slot
s = player.new_script(id, path, slot) -- Lua 脚本，指定 slot
```

### 写入（句柄方法）

```lua
h:press("A")                                -- 按下按钮
h:release("A")                              -- 释放按钮
h:move("left", x, y)                        -- 摇杆 [-1, 1]
h:move("right", x, y)
h:motion("left", gx,gy,gz, ax,ay,az)        -- 体感（左 JoyCon）
h:motion("right", gx,gy,gz, ax,ay,az)       -- 体感（右 JoyCon）
h:wait(ms)                                  -- 暂停协程
u:recv()          → string or nil            -- 读取 UDP 包 (new_udp only)
h:kill()                                    -- 释放 slot，停止输入
```

多 slot 同时写入时：按钮 OR 合并，摇杆和体感按时间戳 last-write-wins。

### 读取（player module，查看合并后的手柄状态）

```lua
player:held(id, "A")          → bool              -- 按钮是否按下
player:axis(id, "left")       → x, y              -- 摇杆 [-1, 1]
player:axis(id, "right")      → x, y
player:motion(id, "left")     → gx,gy,gz,ax,ay,az -- 体感数据
player:motion(id, "right")    → gx,gy,gz,ax,ay,az
```

### 上下文

```lua
game:id()           → u64     -- 当前游戏 ID
game:name()         → string  -- 当前游戏名
wait(ms)            -- 协程暂停
```

### 按钮名称

`A` `B` `X` `Y` `L` `R` `ZL` `ZR` `Plus` `Minus`
`DUp` `DDown` `DLeft` `DRight` `LStick` `RStick`
`SLLeft` `SLRight` `SRLeft` `SRRight`

### 脚本协程环境

`player.new_script` 加载的脚本自动获得以下全局函数，绑定到自己的 slot：

```lua
press(btn)            release(btn)
move(which, x, y)     motion(which, gx,gy,gz,ax,ay,az)
wait(ms)
```

无需句柄，直接调用即可。

## 示例脚本

| 脚本 | 功能 | 涉及 API |
|------|------|----------|
| `main.lua` | 入口，spawn 子脚本 | `player.new`, `player.new_script`, `game.name`, `h:press`, `h:kill`, `wait` |
| `turbo.lua` | 按住 L 时连按 A | `player:held`, `press`, `release`, `wait` |
| `auto_potion.lua` | 每 5 秒自动按 X | `press`, `release`, `wait` |
| `combo_macro.lua` | 摇杆方向触发 combo | `player:held`, `player:axis`, `press`, `release`, `wait` |
| `motion_aim.lua` | 体感反补偿 + 摇杆微调 | `player:motion`, `motion`, `move`, `wait` |
| `per_game.lua` | 不同游戏不同逻辑 | `game:id`, `game:name`, `player:held` |
| `udp_remote.lua` | UDP 远程输入 (24-byte 协议) | `player.new_udp`, `h:recv`, `move`, `press`, `release`, `wait` |
| `button_test.lua` | 逐个测试全部 20 个按钮 | `press`, `release`, `wait` |

## 构建集成

```bash
./scripts/apply_overlay.sh /path/to/eden/source
```

补丁会：
1. 复制 overlay 源文件到 `hid_core/frontend/`
2. 修改 `EmulatedController` 添加 slot 系统和 `ApplyOverlay()`
3. 添加 Lua 依赖（CPM, v5.4.7）并链接到 hid_core

详细设计见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。
