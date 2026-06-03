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

`dsu_test.py` 是一个 DSU 协议测试服务器，用于验证模拟器是否正确接收按键、摇杆和体感输入。

```bash
python3 dsu_test.py                        # 自动循环所有按键
python3 dsu_test.py --button A             # 按住 A
python3 dsu_test.py --button A,B,L         # 同时按住 A + B + L
python3 dsu_test.py --button DUp           # 按十字键上
python3 dsu_test.py --stick-left 255 128   # 左摇杆推到最右
python3 dsu_test.py --list                 # 列出所有按键名
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
 DSU Server (dsu_test.py / 手机 App)         Eden 模拟器                    游戏
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
