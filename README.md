# Eden DSU Build

基于 [Eden-CI/Workflow](https://github.com/Eden-CI/Workflow) 的 CI 构建仓库，增加 DSU（Cemuhook）协议完整手柄支持。

## DSU 协议支持

在官方构建流程中增加一个 patch 步骤：将 `enable_udp_controller` 默认值从 `false` 改为 `true`。

改动位于 `.github/workflows/build.yml` 的 clone job，在拉取 Eden 源码后、构建前执行：

```
git clone Eden → sed 改 settings.h → 全平台构建
```

## 构建

手动触发：

1. 进入 [Actions](../../actions) 页面
2. 选择 **"DSU Build"**
3. 点击 **Run workflow**
4. 等待三平台（macOS / Windows / Linux）构建完成
5. 构建产物自动发布到 [Releases](../../releases) 页面

## DSU 使用方式

1. 在手机安装 DSU Server（支持 Cemuhook 协议，UDP 26760 端口）
2. 模拟器控制器设置中选择 "UDP Controller" 作为输入设备
3. 填入 DSU Server IP 和端口（默认 26760）
4. 按键、摇杆、体感同时生效

## 测试脚本

### dsu_server.py（推荐）

可扩展的 DSU 服务器，提供简洁的 Python API，方便写自定义逻辑（如体感→按键转换）。

**命令行使用：**

```bash
python3 dsu_server.py                        # 交互键盘模式，单手柄
python3 dsu_server.py --pads 4               # 4 人手柄
python3 dsu_server.py --port 26760           # 指定端口
python3 dsu_server.py --no-keyboard          # 仅 DSU 服务，无键盘输入
```

**键盘映射（无需回车）：**

| 按键 | 功能 | | 按键 | 功能 |
|------|------|-|------|------|
| `j` `k` `u` `i` | A B X Y | | `q` `e` | L R |
| `z` `c` | ZL ZR | | `v` `b` | L3 R3 |
| `w` `a` `s` `d` | 方向键 | | `↑` `↓` `←` `→` | 方向键 |
| `m` | Minus (-) | | `p` | Plus (+) |
| `h` | Home | | `Space` | 松开所有 |
| `Tab` | 切换手柄 | | `:` | 输入文本命令 |
| `Esc` | 退出 | | `?` | 显示帮助 |

`: ` 文本命令：`A` `B` `ZL` `stick left 200 128` `state` `pad 1 A` `release`

**扩展 API：**

```python
from dsu_server import DsuServer

server = DsuServer(port=26760, num_pads=1, keyboard=False)

# 按钮
server.press("A")              # 按住 A（替换之前的按键）
server.press("A", "B")         # 按住 A + B
server.release()               # 松开所有按键
server.release(pad=0)          # 松开指定手柄

# 摇杆（0-255, 128=居中）
server.stick("left", 200, 128)
server.stick("right", 64, 192)

# 体感（3 元组）
server.motion(gyro=(0.1, 0.0, 0.0), accel=(0.0, 0.0, 1.0))

# 触摸
server.touch(500, 300, pressed=True)

server.start()   # 启动，阻塞
```

**自定义逻辑示例（体感→按键）：**

```python
from dsu_server import DsuServer
import time, threading

server = DsuServer(port=26760, keyboard=False)

# 在后台线程中读取传感器，转换为按键
def motion_to_button():
    while True:
        gyro = read_gyro()  # 你的传感器代码
        if gyro[0] > 0.5:
            server.press("RIGHT")
        elif gyro[0] < -0.5:
            server.press("LEFT")
        else:
            server.release()
        time.sleep(0.01)

threading.Thread(target=motion_to_button, daemon=True).start()
server.start()  # 主线程跑 DSU 事件循环
```

启动后在模拟器中选 "UDP Controller" 作为输入设备即可测试。

## 按键映射

DSU 协议使用 16 位掩码（`digital_button`）传输按键状态，每个 bit 对应一个按钮：

```
Bit 0: Share     Bit 1: L3         Bit 2: R3        Bit 3: Options
Bit 4: DUp       Bit 5: DRight     Bit 6: DDown      Bit 7: DLeft
Bit 8: L2        Bit 9: R2         Bit 10: L1        Bit 11: R1
Bit 12: Triangle Bit 13: Circle    Bit 14: Cross     Bit 15: Square
```

Eden 收到包后在 `OnPadData()` 中按这个顺序逐位读取，再通过 `GetButtonMappingForDevice()` 映射到 Switch 按键：

| DSU 名称 | Switch 按键 | 游戏中效果 |
|---------|-----------|----------|
| Circle | A | 确认 / 跳跃 |
| Cross | B | 取消 / 返回 |
| Triangle | X | 攻击 |
| Square | Y | 重击 |
| Options | Plus (+) | 菜单 |
| Share | Minus (-) | 地图 |
| DUp / DDown / DLeft / DRight | 十字键 | 方向 |
| L1 | L | 左肩键 |
| R1 | R | 右肩键 |
| L2 | ZL | 左扳机 |
| R2 | ZR | 右扳机 |
| L3 | Left Stick Press | 左摇杆按下 |
| R3 | Right Stick Press | 右摇杆按下 |

## 数据流

```
 DSU Server (dsu_server.py / 手机 App)      Eden 模拟器                    游戏
 ───────────────────────────────────         ───────────                    ────
 digital_button = 1 << 13  (Circle)         OnPadData()
 pack PadData ───── UDP ────────────────→   解析 bit 13 → PadButton::Circle
                                                          ↓
                                             GetButtonMappingForDevice()
                                             Circle → A ──────────────────→  A 按下
```

## 协议参考

- [cemuhook-protocol](https://github.com/v1993/cemuhook-protocol)

## 许可

GPLv3。基于 [Eden-CI/Workflow](https://github.com/Eden-CI/Workflow)。
