# Eden Overlay C++

## 设计原则
- 不引入 Lua。逻辑全在 C++。
- 多 pad 支持（最多 8 玩家，匹配 Switch 硬件上限），UDP 包内 `pad_id` 区分目标 pad。
- UDP 接收输入，C++ 解析协议并写入 overlay 状态。
- **物理和 overlay 同时使用同一个 pad**——核心场景。玩家手持物理手柄，手机/脚本发 UDP 补充额外的轴或按钮。
- 冲突处理：
  - 按键：OR 合并（任一方按下即生效）
  - 摇杆/体感：**control_mask 控制哪些字段走 overlay**。声明由 overlay 控制的轴直接覆盖物理值（不比较时间戳）；未声明的轴保留物理值，不受 overlay 影响。staleness 是唯一的退出机制。

## 集成方式：完整文件替换（不是 diff patch）

不使用 `.patch` 文件。采用**完整文件替换**——把修改后的 Eden 源文件完整保存在仓库里，构建时直接 `cp` 覆盖。

原因：
- diff patch 依赖行号、上下文精确匹配，Eden 版本一变就挂
- 完整文件替换：只要指定 Eden 版本，文件一定正确，零失败
- 下次新版本：从新版本源码复制 → 手工/脚本改动 → 保存为 `patches_vX.X.X/files/`

## 目录结构
```
overlay_cpp/                              # 本仓库
├── CLAUDE.md
├── overlay/                              # 新增文件 — 直接复制到 Eden
│   ├── overlay_state.h                   # OverlayState 结构体 + 常量
│   ├── overlay_udp.h                     # InitOverlayUdp / ApplyOverlay 声明
│   └── overlay_udp.cpp                   # UDP socket + 协议解析 + merge
├── patches_v0.2.1/                       # v0.2.1 的修改文件
│   ├── files/                            # 完整修改后的 Eden 源文件，直接 cp 覆盖
│   │   ├── settings.h                    #   + overlay_enabled + overlay_port
│   │   ├── emulated_controller.h         #   + #include "overlay_udp.h"
│   │   ├── emulated_controller.cpp       #   + ApplyOverlay() 调用
│   │   ├── CMakeLists_hid_core.txt       #   + overlay 源文件到构建
│   │   ├── configure_input_advanced.ui   #   + checkbox + port spinbox
│   │   └── configure_input_advanced.cpp  #   + port 测试 + 读写逻辑
│   └── apply_changes.sh                  # 记录修改过程的 sed 脚本（可重复）
├── scripts/
│   ├── apply_overlay.sh                  # 一键集成：cp overlay 文件 + cp files/
│   └── over_sender.py                    # OVER 协议测试发送工具
└── tests/
    ├── test_packet.py                     # 54 tests — 协议包格式
    ├── test_merge.py                      # 28 tests — 合并逻辑模拟
    └── test_integration.py                # 31 tests — 真实 UDP 收发

CI 构建时的文件操作（build.yml Apply Overlay 步骤）：
  1. cp overlay/overlay_state.h         → eden/src/hid_core/frontend/
  2. cp overlay/overlay_udp.h           → eden/src/hid_core/frontend/
  3. cp overlay/overlay_udp.cpp         → eden/src/hid_core/frontend/
  4. cp files/settings.h                → eden/src/common/           (替换)
  5. cp files/emulated_controller.h     → eden/src/hid_core/frontend/(替换)
  6. cp files/emulated_controller.cpp   → eden/src/hid_core/frontend/(替换)
  7. cp files/CMakeLists_hid_core.txt   → eden/src/hid_core/CMakeLists.txt(替换)
  8. cp files/configure_input_advanced.ui   → eden/src/yuzu/configuration/(替换)
  9. cp files/configure_input_advanced.cpp  → eden/src/yuzu/configuration/(替换)

共 9 个 cp，3 个新文件 + 6 个替换文件。无 diff，无 patch，无行号依赖。
```

## 典型使用场景

玩家手持物理 Joy-Con，左手推摇杆控制移动，同时手机 app 发 UDP 补充右手摇杆（瞄准/视角）：

```
物理：  left_stick=(0, 0.8)   right_stick=(0, 0)     buttons=A
UDP：   left_stick=(0, 0)     right_stick=(0.5, 0)   buttons=0
                             │
               control_mask: left=0 (不控制), right=1 (控制), buttons=1
                             │
merge 结果： left_stick=(0, 0.8)  ← 物理胜出（control_mask bit 未置位）
            right_stick=(0.5, 0)  ← overlay 胜出（control_mask bit 置位）
            buttons=A             ← OR 合并（overlay 无按键，不破坏物理 A）
```

手机只需要发送它关心的字段，其余字段物理输入不受影响。

## 设计决策（10 个关键问题的最终答案）

### 1. button_mask 类型：u64
协议用 u64，匹配 Eden 的 `NpadButtonState.raw`（也是 u64）。bit 0-31 覆盖标准按键，bit 32-34 覆盖 N64 LagonC 按键。不为了省 4 字节留功能缺口。

### 2. OverlayState 位置：全局数组，controller 不持有
```cpp
// overlay_udp.cpp — 模块级全局变量
static std::array<OverlayState, 8> overlay_states;
```
EmulatedController 不持有 OverlayState。ApplyOverlay() 引用全局数组，按自己的 `npad_id_type`（Player1=0..Player8=7）索引。ControllerStatus 不加成员变量。patch 量最小。

### 3. 物理/overlay 时间戳比较：不做
不记录物理摇杆 last_write 时间戳。overlay active 时，control_mask 声明控制的轴直接覆盖物理值——不需要比较时间戳。staleness 是唯一的退出机制：overlay 停止发包 → 超时 → `active=false` → 物理全权接管。

### 4. 摇杆方向键位：ApplyOverlay 里同步设置
写入 `analog_stick_state` 后，用阈值（0.5，和 Eden `StickStatus` 一致）计算方向 bit，写入 `npad_button_state.stick_l_left/right/up/down` 和 `stick_r_*`。保证依赖摇杆方向键的游戏正常工作。

### 5. 体感写入路径：直接写 `ControllerStatus.motion_state`
不绕 MotionInput。overlay 数据是最终值，直接写 struct：
```cpp
controller.motion_state[0].gyro = {left_gyro_x,  left_gyro_y,  left_gyro_z};
controller.motion_state[0].accel = {left_accel_x, left_accel_y, left_accel_z};
controller.motion_state[1].gyro = {right_gyro_x, right_gyro_y, right_gyro_z};
controller.motion_state[1].accel = {right_accel_x, right_accel_y, right_accel_z};
```
index 0=左手, 1=右手。

### 6. 线程安全：单线程 poll，不创建线程
UDP socket 设为非阻塞（`O_NONBLOCK`）。ApplyOverlay() 在 StatusUpdate 末尾调用，内部 `recvfrom` 循环 consume 当前缓冲区的所有包。全程在主线程，无锁，无竞争。

### 7. UDP socket 生命周期：模块级静态，InitOverlayUdp 创建
```cpp
// overlay_udp.cpp
static int overlay_socket = -1;   // -1 = 未初始化/disabled

void InitOverlayUdp(u16 port) {
    overlay_socket = socket(AF_INET, SOCK_DGRAM | SOCK_NONBLOCK);
    bind(0.0.0.0:port);
}
void ApplyOverlay(NpadIdType npad_id, ControllerStatus& c) {
    if (overlay_socket < 0) return;
    // drain packets for this pad...
}
```
模拟器启动时调用 `InitOverlayUdp`。不需要 Stop 函数——进程退出时 OS 回收 socket。overlay 关闭时 close socket 并置 -1。

### 8. 本地集成：`scripts/apply_overlay.sh`
```bash
# 9 个 cp 操作，覆盖本地 eden_build：
#   3 个新文件：overlay_state.h, overlay_udp.h, overlay_udp.cpp → hid_core/frontend/
#   6 个替换文件：patches_v0.2.1/files/* → Eden 源码对应位置
./scripts/apply_overlay.sh /path/to/eden_build
```

### 9. 端口占用：UI 中实时检测 + 显示失败
用户勾选 "Enable overlay input" 并点击 Apply 时，configure_input_advanced.cpp 尝试短暂 bind 测试端口。如果失败：
- 弹出 QMessageBox::warning："Overlay port XXXX is already in use. Please choose a different port."
- **自动取消勾选** `enable_overlay`，UI 回到 disabled 状态
- **不保存** `enable_overlay=true`

实现：ApplyConfiguration 内，在保存 `enable_overlay` 之前，先检查该值是否从 false 变为 true（或持续为 true）。如果是，创建一个临时 socket 尝试 bind。成功则关闭临时 socket 并保存设置。失败则弹窗 + 回退 checkbox。

```cpp
// configure_input_advanced.cpp ApplyConfiguration() 中 overlay 部分的逻辑
const bool overlay_was_enabled = Settings::values.enable_overlay.GetValue();
const bool overlay_will_enable = ui->enable_overlay->isChecked();
const u16 port = static_cast<u16>(ui->overlay_port->value());

if (overlay_will_enable && !overlay_was_enabled) {
    // 测试端口是否可用
    int test_sock = socket(AF_INET, SOCK_DGRAM);
    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(port);
    addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    if (bind(test_sock, (sockaddr*)&addr, sizeof(addr)) < 0) {
        QMessageBox::warning(this, "Overlay Port In Use",
            QString("Port %1 is already in use. Please choose a different port.").arg(port));
        ui->enable_overlay->setChecked(false);
        close(test_sock);
        return;  // 不保存 enable_overlay=true
    }
    close(test_sock);
}
Settings::values.enable_overlay = ui->enable_overlay->isChecked();
Settings::values.overlay_port = port;
```

说明：用 `INADDR_LOOPBACK`（127.0.0.1）做测试 bind 而非 `INADDR_ANY`（0.0.0.0），避免和实际监听冲突。两者端口占用检测效果等同。测试后立刻关闭，真正的 bind 在模拟器启动时由 `InitOverlayUdp` 执行。

备选方案（如果不想在 UI 层写 socket 代码）：defer 到模拟器启动时检测，bind 失败通过系统托盘通知或日志。但用户体验差——用户发现勾选了但没生效，不知道原因。**采用 UI 层实时检测**。

### 10. pad_id 越界：接收时 clamp + 丢弃
```cpp
if (pad_id > 7) return;  // Other=0x10, Handheld=0x20 不是有效 overlay 目标
```
`NpadIdType` Player1-8 = 0-7，连续映射。Other(0x10) 和 Handheld(0x20) 不是有效的 overlay 目标，静默丢弃。

## OverlayState
```cpp
struct OverlayState {
    u32 control_mask{0};       // sender 声明控制的字段
    u64 button_mask{0};        // NpadButton 位图，匹配 Eden u64 NpadButtonState.raw
    f32 left_x{0}, left_y{0};
    f32 right_x{0}, right_y{0};
    f32 left_gyro_x{0}, left_gyro_y{0}, left_gyro_z{0};
    f32 left_accel_x{0}, left_accel_y{0}, left_accel_z{0};
    f32 right_gyro_x{0}, right_gyro_y{0}, right_gyro_z{0};
    f32 right_accel_x{0}, right_accel_y{0}, right_accel_z{0};
    u64 last_update{0};        // steady_clock，收到最后一个包的时刻
    bool active{false};        // false = stale，跳过
};
// 模块级全局数组（overlay_udp.cpp），不是 EmulatedController 成员
// extern std::array<OverlayState, 8> overlay_states;
```

## UDP 协议（84-byte，little-endian）

```
Offset  Type    Field
────────────────────────────────────────────────────────
[0]     char[4] magic "OVER"
[4]     u8      pad_id             目标 pad 编号，0-7
[5]     u8[3]   _reserved          padding
[8]     u32     control_mask       控制位图
[12]    u64     button_mask        按键位图（NpadButton 位布局，64-bit）
[20]    f32     left_x             左摇杆 X，-1.0 ~ 1.0
[24]    f32     left_y
[28]    f32     right_x
[32]    f32     right_y
[36]    f32     left_gyro_x
[40]    f32     left_gyro_y
[44]    f32     left_gyro_z
[48]    f32     left_accel_x
[52]    f32     left_accel_y
[56]    f32     left_accel_z
[60]    f32     right_gyro_x
[64]    f32     right_gyro_y
[68]    f32     right_gyro_z
[72]    f32     right_accel_x
[76]    f32     right_accel_y
[80]    f32     right_accel_z
────────────────────────────────────────────────────────
        Total: 84 bytes
```

### Python 发送
```python
# <4sB3xIQ16f  = 4 + 1 + 3 + 4 + 8 + 16*4 = 84
ctrl = (1 << 0) | (1 << 3)  # buttons + right_x
struct.pack('<4sB3xIQ16f', b'OVER', pad_id, ctrl, buttons,
    lx, ly, rx, ry,
    lgx, lgy, lgz, lax, lay, laz,
    rgx, rgy, rgz, rax, ray, raz)
```

### control_mask 位布局

```
bit 0:  button_mask    ← overlay 按键 OR 到物理按键
bit 1:  left_x         ← overlay 控制此轴
bit 2:  left_y
bit 3:  right_x
bit 4:  right_y
bit 5:  left_gyro      ← overlay 控制左手陀螺 (xyz 整组)
bit 6:  left_accel     ← overlay 控制左手加速度 (xyz 整组)
bit 7:  right_gyro     ← overlay 控制右手陀螺 (xyz 整组)
bit 8:  right_accel    ← overlay 控制右手加速度 (xyz 整组)
bits 9-31: reserved (must be 0)
```

## Merge 规则

每个 pad 独立 merge。ApplyOverlay() 被 StatusUpdate 调用，传入自己的 `npad_id` 和 `ControllerStatus`。

### 先检查 staleness
```
if (!overlay_states[pad].active) return;  // 无 overlay 数据，物理直接生效
if (now - overlay_states[pad].last_update > 100ms):
    overlay_states[pad].active = false;
    return;  // 超时，移除 overlay，物理全权接管
```

### 按键：clear-then-set（不是纯 OR）

**为什么纯 OR 有根本缺陷？**

Eden 的物理手柄每帧通过 `Assign(1)` / `Assign(0)` 逐位设置按键状态。按钮 A 按下时 `Assign(1)`，松开时 `Assign(0)`——清零是显式的。

但 overlay 的 OR 合并**只能加不能减**：

```
帧1: phys=0, overlay 设 A → raw = 0 | A = A  ✅
帧2: phys=0, overlay 松 A → raw = A | 0 = A  ❌ 松不开！
```

`1 | 0 = 1`，OR 永远无法把 1 变回 0。摇杆没这个问题，因为摇杆是直接写值：`stick.x = 0` 就是归中。

**修复：clear-then-set**

不直接 OR。跟踪上一帧 overlay 设了哪些位（`button_mask_prev`），先清掉再设新的：

```cpp
// 不是 raw |= new
// 而是 raw = (raw & ~prev) | new
u64 raw = phys;
raw &= ~state.button_mask_prev;   // 清掉上一帧 overlay 的贡献
raw |= state.button_mask;          // 加上这一帧 overlay 的贡献
state.button_mask_prev = state.button_mask;  // 记住，下帧清
```

帧1 按 A：`raw = (0 & ~0) | A = A`，prev 记 A
帧2 松 A：`raw = (0 & ~A) | 0 = 0`，prev 记 0 ✅

**新包到达时保留 prev**

UDP 包到达时 `ParsePacket` 创建全新的 `OverlayState`，`button_mask_prev` 被清零。必须在赋值前保留：

```cpp
state.button_mask_prev = overlay_states[pad_id].button_mask_prev;
overlay_states[pad_id] = state;
```

否则新包一到，prev 丢失，下一帧又清不掉了。

### 摇杆：control_mask bits 1-4 直写 + 方向键位同步
```
if (control_mask & LEFT_X):
    analog_stick_state.left.x  = to_stick_s32(overlay.left_x);
    stick_l_right = (overlay.left_x > 0.5);
    stick_l_left  = (overlay.left_x < -0.5);
// control_mask bit 未置位的轴不碰，物理保留
```
每个轴独立判断。left_x、left_y、right_x、right_y 各由一个 bit 控制。

### 体感：control_mask bits 5-8 组写入
```
if (control_mask & LEFT_GYRO):
    motion_state[0].gyro = overlay.left_gyro;
```
3 轴一起覆盖。

### 阈值 0.01
只在 f32→s32 转换层生效：
```
s32 to_stick_s32(f32 v) {
    if (|v| < 0.01) return 0;
    return s32(v * 32767);
}
```

## Staleness 处理

- **超时值**：100ms（约 6 帧 @60Hz）
- **超时行为**：`active = false`，不再参与 merge
- **实现位置**：`ApplyOverlay()` 开头
- **效果**：staleness 触发时，手机辅助消失，物理手柄全权接管。角色不会卡住

## UDP 接收策略

- 单线程，非阻塞 socket（`SOCK_NONBLOCK`）
- StatusUpdate → ApplyOverlay → `while (recvfrom() > 0)` drain 所有包
- 每个 pad 只保留最后一个包的数据（后来的覆盖前面的）
- 积压的旧包直接丢弃

## Eden 集成：4 个文件的改动

### 文件 1：`common/settings.h` — 加 2 个 setting

在 `Values` struct 的 Controls 区域（约 L715，`enable_udp_controller` 附近）添加：

```cpp
// Overlay
Setting<bool> enable_overlay{linkage, false, "enable_overlay", Category::Overlay};
Setting<u16> overlay_port{linkage, 26760, "overlay_port", Category::Overlay,
                          Specialization::Default, true, true};
```

注意和现有 DSU 设置区分：`enable_udp_controller` + `udp_input_servers` 是 DSU 协议（出站连接外部手柄），与 OVER overlay 无关。

### 文件 2：`configure_input_advanced.ui` — 加 checkbox + spinbox

在 "Other" QGroupBox 的 `OtherGridLayout` 末尾追加：

```xml
<item row="9" column="0">
 <widget class="QCheckBox" name="enable_overlay">
  <property name="text"><string>Enable overlay input (UDP)</string></property>
  <property name="toolTip"><string>Receive external stick/button/motion data via UDP OVER protocol.
Buttons are OR-merged; sticks and motion are overwritten for axes declared in control_mask.</string></property>
 </widget>
</item>
<item row="9" column="2">
 <widget class="QSpinBox" name="overlay_port">
  <property name="minimum"><number>1024</number></property>
  <property name="maximum"><number>65535</number></property>
  <property name="value"><number>26760</number></property>
  <property name="toolTip"><string>UDP port for overlay input (1024-65535)</string></property>
 </widget>
</item>
```

### 文件 3：`configure_input_advanced.cpp` — 读写 + 端口检测

**头文件新增**：
```cpp
#include <QMessageBox>
#include <sys/socket.h>
#include <netinet/in.h>
#include <unistd.h>
```

**LoadConfiguration()** 末尾追加（约 L183 后）：
```cpp
ui->enable_overlay->setChecked(Settings::values.enable_overlay.GetValue());
ui->overlay_port->setValue(Settings::values.overlay_port.GetValue());
```

**ApplyConfiguration()** 末尾追加（约 L148 后）：
```cpp
const bool overlay_was_enabled = Settings::values.enable_overlay.GetValue();
const bool overlay_will_enable = ui->enable_overlay->isChecked();
const u16 port = static_cast<u16>(ui->overlay_port->value());

if (overlay_will_enable && !overlay_was_enabled) {
    int test_sock = socket(AF_INET, SOCK_DGRAM);
    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(port);
    addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    if (bind(test_sock, (sockaddr*)&addr, sizeof(addr)) < 0) {
        QMessageBox::warning(this, "Overlay Port In Use",
            QString("Port %1 is already in use.\nPlease choose a different port.").arg(port));
        ui->enable_overlay->setChecked(false);
        close(test_sock);
        // 继续执行，但不保存 enable_overlay=true
    } else {
        close(test_sock);
        Settings::values.enable_overlay = true;
    }
} else {
    Settings::values.enable_overlay = overlay_will_enable;
}
Settings::values.overlay_port = port;
```

### 文件 4：`emulated_controller.cpp` — ApplyOverlay 调用

- **`.h` patch**: 加入 `#include "overlay_udp.h"`（在现有 include 区域末尾）
- **`.cpp` patch**: `StatusUpdate()` 函数体末尾（`}` 之前）加 `ApplyOverlay(npad_id_type, controller);`

---

## 新版本适配流程

当 Eden 发布新版本（如 v0.3.0）时：

```bash
# 1. 获取新版源码
git clone --branch v0.3.0 https://git.eden-emu.dev/eden-emu/eden.git eden_v0.3.0

# 2. 创建新 patches 目录
mkdir -p patches_v0.3.0/files

# 3. 从新版源码复制 6 个文件到 files/
cp eden_v0.3.0/src/common/settings.h                              patches_v0.3.0/files/
cp eden_v0.3.0/src/hid_core/frontend/emulated_controller.h        patches_v0.3.0/files/
cp eden_v0.3.0/src/hid_core/frontend/emulated_controller.cpp      patches_v0.3.0/files/
cp eden_v0.3.0/src/hid_core/CMakeLists.txt                         patches_v0.3.0/files/CMakeLists_hid_core.txt
cp eden_v0.3.0/src/yuzu/configuration/configure_input_advanced.ui patches_v0.3.0/files/
cp eden_v0.3.0/src/yuzu/configuration/configure_input_advanced.cpp patches_v0.3.0/files/

# 4. 参照 patches_v0.2.1/apply_changes.sh，手工在新版文件上做修改
# 5. 验证修改正确
grep 'ApplyOverlay' patches_v0.3.0/files/emulated_controller.cpp
grep 'overlay_enabled' patches_v0.3.0/files/settings.h

# 6. 创建 overlay_cpp_v0.3.0.yml workflow，patches-dir 指向 patches_v0.3.0
```
,   