# Eden Overlay + DSU Build

Eden Switch emulator 的 CI 构建仓库，包含两项扩展：

| 功能 | 说明 |
|------|------|
| **DSU 协议** | 完整手柄支持（按钮 + 摇杆 + 体感），通过 Cemuhook UDP 协议 |
| **Eden Overlay** | Lua 驱动的多输入源合并，类似 reWASD |

## Eden Overlay — 快速开始

```
eden
overlay_scripts/          ← 把 .lua 脚本放在这里，自动加载
├── turbo_attack.lua
├── auto_potion.lua
└── udp_remote.lua
```

每个 `.lua` 一个 slot，独立运行，帧末 OR 合并。

### Lua API

| 函数 | 说明 |
|------|------|
| `press("A")` / `release("A")` | 写入当前 slot 的按钮 |
| `get_button("A")` → bool | 读最终合并后的按钮状态 |
| `get_stick("left")` → x, y | 读最终合并后的摇杆 [-1, 1] |
| `set_stick("left", x, y)` | 写入当前 slot 的摇杆 |
| `sleep(ms)` | 暂停协程 |
| `udp_bind(port)` | 开启 UDP 监听 |
| `udp_poll()` → data or nil | 取最新收到的包 |
| `get_title_id()` → u64 | 当前游戏 ID |
| `get_game_name()` → str | 当前游戏名 |

### 按游戏不同脚本

```lua
if get_game_name():find("Zelda") then
    -- 塞尔达专属操作
end
```

### 构建集成

```
./scripts/apply_overlay.sh /path/to/eden/source
```

详细设计见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

## DSU 协议支持

- 使用原始的 `cemuhook` UDP 协议
- 支持按钮、左右摇杆、体感数据
- 提供 `dsu_server.py` 和 `keyboard_config.json` 用于键盘转 DSU

## 示例脚本

| 脚本 | 功能 |
|------|------|
| `turbo_attack.lua` | 按住 L 时连续按 A |
| `auto_potion.lua` | 每 5 秒自动喝药 |
| `combo_macro.lua` | 摇杆方向触发不同 combo |
| `udp_remote.lua` | 通过 UDP 接收远程输入 |
| `per_game.lua` | 不同游戏走不同逻辑 |

## License

GPL-3.0-or-later
