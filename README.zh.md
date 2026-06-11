# Eden Overlay C++

纯 C++ 实现的外部输入叠加层。通过 UDP 接收 OVER 协议数据包，与物理手柄输入实时合并，驱动 Eden Switch 模拟器的任意玩家。

**核心场景**：玩家手持物理 Joy-Con，手机/脚本同时发 UDP 补充额外的摇杆/按键/体感。物理和 overlay 输入无缝混合，按轴独立控制。

## 协议

```
84-byte UDP 包, little-endian
┌──────┬──────┬──────────┬──────────────┬──────────────┬──────────────┬──────────────────────────┐
│ OVER │ pad  │ reserved │ control_mask │ button_mask  │ left_x left_y│ left/right gyro + accel │
│ 4B   │ 1B   │ 3B       │ u32          │ u64          │ right_x ry   │ 12×f32 = 48B            │
└──────┴──────┴──────────┴──────────────┴──────────────┴──────────────┴──────────────────────────┘
```

`control_mask` 声明 overlay 控制哪些字段（bit 0=按键, 1-4=4个摇杆轴, 5-8=体感组）。置位的字段 overlay 生效，未置位的字段物理输入保留。

详见 [CLAUDE.md](CLAUDE.md)。

## 目录结构

```
overlay_cpp/
├── overlay/                    # 新增文件 — 复制到 Eden
│   ├── overlay_state.h         #   OverlayState 结构体 + 常量
│   ├── overlay_udp.h           #   InitOverlayUdp / ApplyOverlay 声明
│   └── overlay_udp.cpp         #   UDP socket + 协议解析 + merge 实现
├── patches_v0.2.1/             # Eden v0.2.1 的修改文件（完整替换）
│   ├── files/                  #   6 个修改后的 Eden 源文件（直接 cp）
│   └── apply_changes.sh        #   修改步骤参考（sed 脚本）
├── scripts/
│   ├── over_console.py         #   键盘 → OVER 协议的交互控制台（tkinter）
│   ├── over_sender.py          #   OVER 协议包构建/发送库
│   ├── over_test.py            #   自动诊断脚本（6 个测试包）
│   └── apply_overlay.sh        #   一键集成脚本（cp 文件到 eden_build）
├── tests/                      #   Python 测试套件（113 tests）
└── CLAUDE.md                   #   完整设计文档
```

## 快速开始

### 1. 下载构建产物

从 GitHub Actions → **Overlay C++ v0.2.1** workflow 下载对应平台的构建产物。

### 2. 启用 Overlay

- Eden → Settings → Input → Advanced → Other
- 勾选 **"Enable overlay input (UDP)"**
- 端口默认 26760
- 点击 Apply
- 启动游戏

### 3. 发送输入

**交互控制台（键盘模拟）：**

```bash
python3 scripts/over_console.py                  # pad 0, 本地
python3 scripts/over_console.py -p 1              # pad 1
python3 scripts/over_console.py --host 10.0.0.5   # 远程
```

| 按键 | 功能 |
|------|------|
| WASD | 左摇杆 |
| IJKL | 右摇杆 |
| U/J | A / B |
| Y/H | X / Y |
| R/T | L / R |
| Q/E | ZL / ZR |
| 1/2 | L3 / R3 |
| -/= | MINUS / PLUS |
| 方向键 | D-Pad |
| Shift | 半推摇杆 |
| Tab | 切换 pad (0-7) |
| Esc | 退出 |

**诊断脚本（无需键盘）：**

```bash
python3 scripts/over_test.py                    # 自动发 6 个测试包
python3 scripts/over_test.py 192.168.1.5 26760  # 指定 IP 和端口
```

**作为 Python 库：**

```python
from scripts.over_sender import OverSender

s = OverSender(pad_id=0, host="127.0.0.1", port=26760)
s.buttons(A=True, B=True)          # 按键
s.stick("left", 0.5, 0)            # 左摇杆半推向右
s.stick("right", 0, 0.8)           # 右摇杆向上
s.motion("left", gyro=(0.1,0,0))   # 左手陀螺
s.send()                            # 发送 84-byte 包
```

## 本地集成（开发者）

将 overlay 集成到本地 Eden 代码树：

```bash
./scripts/apply_overlay.sh /path/to/eden_build
```

做 9 个文件操作：3 个新文件（overlay/*.h *.cpp）+ 6 个文件替换（patches_v0.2.1/files/）。

## CI 构建

3 个独立的 workflow，各管各的分支：

| Workflow | 分支 | 说明 |
|----------|------|------|
| **DSU Build** | `master` | Eden + DSU 协议 patch |
| **Overlay Build** | `overlay` | Eden + Lua overlay |
| **Overlay C++ v0.2.1** | `overlay_cpp` | Eden v0.2.1 + C++ overlay |

每个 workflow 手动触发，从 Actions 页面下载构建产物。不做自动 release。

## 新版本适配

Eden 发布新版本（如 v0.3.0）时：

```bash
# 1. 获取新版源码
git clone --branch v0.3.0 https://git.eden-emu.dev/eden-emu/eden.git

# 2. 创建对应目录
mkdir -p patches_v0.3.0/files

# 3. 复制需要修改的 6 个源文件
cp eden/src/common/settings.h                         patches_v0.3.0/files/
cp eden/src/hid_core/frontend/emulated_controller.h   patches_v0.3.0/files/
cp eden/src/hid_core/frontend/emulated_controller.cpp patches_v0.3.0/files/
cp eden/src/hid_core/CMakeLists.txt                   patches_v0.3.0/files/CMakeLists_hid_core.txt
cp eden/src/yuzu/configuration/configure_input_advanced.ui  patches_v0.3.0/files/
cp eden/src/yuzu/configuration/configure_input_advanced.cpp patches_v0.3.0/files/

# 4. 参照 patches_v0.2.1/apply_changes.sh 手工修改
# 5. 创建 overlay_cpp_v0.3.0.yml workflow
```

## 设计决策

| # | 问题 | 答案 |
|---|------|------|
| 1 | button_mask 类型 | u64（匹配 Eden NpadButtonState.raw） |
| 2 | OverlayState 位置 | 全局数组，不挂在 controller 上 |
| 3 | 物理/overlay 时间戳 | 不做——overlay active 时直写，staleness 退出 |
| 4 | 摇杆方向键位 | ApplyOverlay 同步设置阈值 0.5 |
| 5 | 体感写入 | 直接写 ControllerStatus.motion_state |
| 6 | 线程安全 | 单线程，非阻塞 recvfrom |
| 7 | socket 生命周期 | 模块静态变量，InitOverlayUdp 懒初始化 |
| 8 | 集成方式 | 完整文件替换，不用 diff patch |
| 9 | 端口占用检测 | UI Apply 时测试 bind，失败弹窗 |
| 10 | pad_id 越界 | clamp 0-7 |

详见 [CLAUDE.md](CLAUDE.md)。

## 许可

GPLv3。基于 [Eden Emulator](https://git.eden-emu.dev/eden-emu/eden)。
