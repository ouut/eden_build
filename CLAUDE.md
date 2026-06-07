# Eden Overlay C++

## 设计原则
- 不引入 Lua。逻辑全在 C++。
- 多 pad 支持（最多 8 玩家，匹配 Switch 硬件上限），UDP 包内 `pad_id` 区分目标 pad。
- UDP 接收输入，C++ 解析协议并写入 overlay 状态。
- **物理和 overlay 同时使用同一个 pad**——核心场景。玩家手持物理手柄，手机/脚本发 UDP 补充额外的轴或按钮。
- 冲突处理：
  - 按键：OR 合并（任一方按下即生效）
  - 摇杆/体感：**control_mask 控制哪些字段走 overlay**。声明由 overlay 控制的轴走 last-write-wins；未声明的轴保留物理值，不受 overlay 影响。

## 为什么需要打 patch（不能只往文件末尾追加）
- `OverlayState overlay_state` 成员必须在 `EmulatedController` class 体内（`};` 之前）
- `ApplyOverlay()` 调用必须插入 `StatusUpdate()` 函数体末尾
- 两者都在文件中部，追加到文件末尾无效

## 目录结构
```
overlay/
├── overlay_state.h          # OverlayState 结构体
├── overlay_udp.h            # UDP 监听 + 协议解析
├── overlay_udp.cpp
└── patches/
    ├── emulated_controller.h.patch
    └── emulated_controller.cpp.patch
scripts/
├── apply_overlay.sh
└── over_sender.py           # OVER 协议测试发送工具
docs/
└── ARCHITECTURE.md
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

## OverlayState（数组，每 pad 一份，最多 8）
```cpp
struct OverlayState {
    // Control — sender declares which fields it controls
    u32 control_mask{0};

    // Buttons
    u32 button_mask{0};

    // Analog sticks — f32, -1.0 ~ 1.0 (匹配 Eden StickStatus.value)
    f32 left_x{0}, left_y{0};
    f32 right_x{0}, right_y{0};

    // Left motion (6 fields)
    f32 left_gyro_x{0}, left_gyro_y{0}, left_gyro_z{0};   // rad/s
    f32 left_accel_x{0}, left_accel_y{0}, left_accel_z{0}; // G

    // Right motion (6 fields)
    f32 right_gyro_x{0}, right_gyro_y{0}, right_gyro_z{0};   // rad/s
    f32 right_accel_x{0}, right_accel_y{0}, right_accel_z{0}; // G

    // Metadata
    u64 last_update{0};    // local steady_clock timestamp of last received packet
    bool active{false};    // false when stale (no packet received within timeout)
};

// 每个 EmulatedController 持有一份
std::array<OverlayState, 8> overlay_states;
```

## UDP 协议（80-byte，little-endian）

单一固定格式。每包对应一个 pad，`pad_id` 区分目标。发送端永远发 80 字节，接收端读到少于 80 字节则丢弃。

```
Offset  Type    Field
────────────────────────────────────────────────────────
[0]     char[4] magic "OVER"
[4]     u8      pad_id             目标 pad 编号，0-7
[5]     u8[3]   _reserved          padding，保证对齐
[8]     u32     control_mask       控制位图（见下文）
[12]    u32     button_mask        按键位图（NpadButton 位布局）
[16]    f32     left_x             左摇杆 X，-1.0 ~ 1.0
[20]    f32     left_y             左摇杆 Y
[24]    f32     right_x            右摇杆 X
[28]    f32     right_y            右摇杆 Y
[32]    f32     left_gyro_x        左手陀螺 X，rad/s
[36]    f32     left_gyro_y
[40]    f32     left_gyro_z
[44]    f32     left_accel_x       左手加速度 X，G
[48]    f32     left_accel_y
[52]    f32     left_accel_z
[56]    f32     right_gyro_x       右手陀螺 X，rad/s
[60]    f32     right_gyro_y
[64]    f32     right_gyro_z
[68]    f32     right_accel_x      右手加速度 X，G
[72]    f32     right_accel_y
[76]    f32     right_accel_z
────────────────────────────────────────────────────────
        Total: 80 bytes
```

### control_mask 位布局

每个 bit：1 = overlay 控制此字段，merge 时 overlay 值生效；0 = 不控制，保留物理值。

```
bit 0:  button_mask    ← 1 时 OR overlay 按键位图到物理按键
bit 1:  left_x         ← 1 时 overlay 左摇杆 X 轴覆盖物理
bit 2:  left_y
bit 3:  right_x
bit 4:  right_y
bit 5:  left_gyro      ← 1 时 overlay 左手陀螺 (xyz) 覆盖物理
bit 6:  left_accel     ← 1 时 overlay 左手加速度 (xyz) 覆盖物理
bit 7:  right_gyro     ← 1 时 overlay 右手陀螺 (xyz) 覆盖物理
bit 8:  right_accel    ← 1 时 overlay 右手加速度 (xyz) 覆盖物理
bits 9-31: reserved (must be 0)
```

设计要点：
- **摇杆分轴独立控制**：手机只想控制右摇杆 X 轴（水平视角），设置 bit 3=1，left_x/left_y/right_y 不受影响
- **体感按传感器分组**：陀螺 3 轴一起控制，加速度 3 轴一起控制。手机传感器天然产生完整 3 轴数据，不存在只发 X 轴不发 Y 轴的情况
- **按键整体控制**：一个 bit 控制是否 OR overlay 按键。sender 不想影响物理按键时置 0，overlay button_mask 被忽略

### Python 发送示例
```python
ctrl = (1 << 0) | (1 << 3)  # 控制 buttons + right_x
struct.pack('<4sB3xII16f', b'OVER', pad_id, ctrl, buttons,
    lx, ly, rx, ry,
    lgx, lgy, lgz, lax, lay, laz,
    rgx, rgy, rgz, rax, ray, raz)
```

### 设计理由
- **固定长度** — 不需要 length 字段，收多收少直接判断
- **control_mask 在头部** — 解析后立刻知道哪些字段需要 merge，不需要解析全包体
- **每包一个 pad** — 不同 pad 的数据独立发送、独立 stale、独立 merge
- **零就是零** — 不存在「这个字段没发货」，所有字段始终存在。但 control_mask 决定哪些生效
- **跨语言** — 一行 struct.pack 构造

## 摇杆值域与 Eden 的对应关系

Eden 内部：
- `StickStatus.x.value` / `y.value` — **f32，范围 -1.0 ~ 1.0**
- `AnalogStickState` — `{s32 x, s32 y}`，写入时做：`s32(value * 32767)`（`HID_JOYSTICK_MAX = 0x7FFF`）

Overlay 协议直接使用 f32（-1.0 ~ 1.0），ApplyOverlay() 里乘以 32767 写到 `analog_stick_state`。

## Merge 规则

每个 pad 独立 merge。ApplyOverlay() 对每个活跃的 pad：

### 先检查 staleness
```
if (now - overlay_states[pad_id].last_update > 100ms):
    overlay_states[pad_id].active = false
    // 该 pad 全部清零，跳过 overlay
    continue
```

### 按键：OR 合并（受 control_mask bit 0 控制）
```
if (control_mask & BUTTON_BIT):
    npad_button_state.raw |= overlay.button_mask
// bit 未置位 → 不 OR，物理按键原样保留
```

### 摇杆轴：last-write-wins（受 control_mask bits 1-4 各自控制）
```
if (control_mask & LEFT_X)  && overlay_last_update > phys_last_write:
    analog_stick_state.left.x = to_stick_s32(overlay.left_x)
// bit 未置位 → 该轴不覆盖，物理值保留
```
每个轴独立判断。control_mask bit 1 只影响 left_x，不影响 left_y 等。

### 体感：last-write-wins（受 control_mask bits 5-8 按传感器组控制）
```
if (control_mask & LEFT_GYRO) && overlay_last_update > phys_last_write:
    gyro_left = overlay.left_gyro
```
同组 3 轴一起覆盖。

### 阈值 0.01
阈值存在于**值转换层**，不在 merge 决策层：
```
s32 to_stick_s32(f32 v) {
    if (|v| < 0.01) return 0;   // 过滤浮点噪声
    return s32(v * 32767);
}
```
作用：防止 0.001 之类浮点误差在 s32 输出中产生非零值。

### control_mask 未置位的字段
完全不参与 merge。overlay 包里对应字段的值被忽略，物理输入保留。sender 可以安全地填 0。

## Staleness 处理

每个 pad 独立计时、独立超时。

### 场景
Overlay 发送端通过 UDP 发包。UDP 无连接、无心跳、无对端存活检测。如果：
- 网络断开（Wi-Fi 中断、网线松脱）
- 发送端 app 崩溃或退出
- 发送端机器 sleep

模拟器收不到新包，但不知道对端已死。上一次 overlay 控制的摇杆/按键值会永久残留。

物理 Joy-Con 不存在此问题：蓝牙有心跳，HID 层在连接断开时立刻感知并清理状态。

### 方案
- **超时值**：100ms（约 6 帧 @60Hz，局域网内足够宽松）
- **超时行为**：`active = false`，清空该 pad 所有 overlay 字段（包括 control_mask）
- **实现位置**：`ApplyOverlay()` 函数开头，每次 StatusUpdate 调用时对每个 pad 检查

```
每帧 ApplyOverlay():
    for pad_id in 0..7:
        if (now - overlay_states[pad_id].last_update > 100ms):
            overlay_states[pad_id].active = false
            overlay_states[pad_id].control_mask = 0
            overlay_states[pad_id].button_mask = 0
            // sticks, motion 全部归零
            continue  // 跳过此 pad，全部物理输入
        // active == true，按 control_mask 逐字段 merge
```

### 注意
- `active == false` → 完全跳过 overlay，物理输入原样生效
- 清零后 `control_mask = 0` → 即使时间戳残留也不会错误覆盖
- 正确行为：staleness 触发时，玩家突然感觉「手机辅助消失」，物理手柄全权接管。平滑过渡，角色不会卡住

## UDP 接收策略

- `StatusUpdate()` 调用频率 ≈ 60Hz
- 每帧之间可能积压多个 UDP 包
- **循环 recvfrom 直到缓冲区空，对每个 pad 只消费最后一个包**
- 前面积压的包直接丢弃，不处理
- 每个包只更新对应 pad 的 `overlay_states[pad_id]`

原因：用一个过时包更新状态后立刻被下一个包覆盖，徒增 CPU 开销。

## EmulatedController patch（最小改动）
- `.h`: 加 `#include`、`std::array<OverlayState, 8> overlay_states` 成员、`ApplyOverlay()` 声明、`StartOverlayUdp()` 声明
- `.cpp`: `StatusUpdate()` 末尾加 `ApplyOverlay()` 调用、`ApplyOverlay()` 实现、`StartOverlayUdp()` 实现

## Eden 集成：UI 设置与 HID Core 对接

### 概述

在 Eden 模拟器的 Qt 设置界面添加两个控件：
- **开关**：启用/禁用 overlay UDP 监听
- **端口**：UDP 监听端口（默认 26760）

这两个设置需要贯穿三个层：Settings 定义 → Qt UI → HID Core 消费。

### 新增 Settings（`common/settings.h`）

文件：`eden/src/common/settings.h`，在 `Values` struct 的 Controls 区域（约第 715 行，现有 `enable_udp_controller` 附近）添加：

```cpp
// Overlay
Setting<bool> enable_overlay{linkage, false, "enable_overlay", Category::Overlay};
Setting<u16> overlay_port{linkage, 26760, "overlay_port", Category::Overlay,
                          Specialization::Default, true, true};
```

说明：
- `enable_overlay` — bool，默认 `false`。非 `SwitchableSetting`，因为 overlay 不需要 per-game override
- `overlay_port` — u16，默认 `26760`。`Specialization::Default` 表示普通数值输入
- 两者都属于 `Category::Overlay`（枚举已存在但之前未被使用）
- 不需要 `SwitchableSetting` 因为 overlay 是全局开关，不是 per-game 配置

**注意**：不要和现有的两个设置混淆（它们用于 DSU/Cemuhook 协议，与 OVER overlay 完全无关）：
```cpp
// 第 715-718 行 — 这些是 DSU 协议的，不是 overlay
Setting<std::string> udp_input_servers{...};    // DSU 服务器地址
Setting<bool> enable_udp_controller{...};       // DSU 控制器开关
```

### 新增 UI 控件（Qt 配置页）

#### 位置选择

现有 `configure_input_advanced.ui` 中，"Other" QGroupBox 包含多个 checkbox（`emulate_analog_keyboard`、`enable_raw_input`、`enable_udp_controller` 等），以 `QGridLayout` 排列。

**方案**：在 "Other" GroupBox 的 grid 末尾追加新行，放 overlay 开关和端口输入框。

#### .ui 文件改动（`yuzu/configuration/configure_input_advanced.ui`）

文件：`eden/src/yuzu/configuration/configure_input_advanced.ui`

在 `OtherGridLayout` 的最后一个 `<item>` 之后（约第 2770 行附近），`</layout>` 关闭前，追加：

```xml
<!-- Overlay: enable toggle + port -->
<item row="9" column="0">
 <widget class="QCheckBox" name="enable_overlay">
  <property name="minimumSize">
   <size>
    <width>0</width>
    <height>23</height>
   </size>
  </property>
  <property name="text">
   <string>Enable overlay input (UDP)</string>
  </property>
  <property name="toolTip">
   <string>Receive external input via UDP OVER protocol on the configured port.
Buttons are OR-merged, sticks last-write-wins with control_mask.</string>
  </property>
 </widget>
</item>
<item row="9" column="2">
 <widget class="QSpinBox" name="overlay_port">
  <property name="minimum">
   <number>1024</number>
  </property>
  <property name="maximum">
   <number>65535</number>
  </property>
  <property name="value">
   <number>26760</number>
  </property>
  <property name="toolTip">
   <string>UDP port for overlay input (1024-65535)</string>
  </property>
 </widget>
</item>
```

说明：
- `row="9"` — 当前 OtherGridLayout 最大 row 是 8，使用 row 9 避免冲突
- checkbox 在 column 0，端口 spinbox 在 column 2（column 1 留空，保持间距）
- `enable_overlay` — QCheckBox，默认未勾选
- `overlay_port` — QSpinBox，范围 1024-65535，默认 26760

#### .cpp 文件改动（`yuzu/configuration/configure_input_advanced.cpp`）

文件：`eden/src/yuzu/configuration/configure_input_advanced.cpp`

**ApplyConfiguration()** 末尾追加（约第 148 行之后）：

```cpp
Settings::values.enable_overlay = ui->enable_overlay->isChecked();
Settings::values.overlay_port = static_cast<u16>(ui->overlay_port->value());
```

**LoadConfiguration()** 末尾追加（约第 183 行之后）：

```cpp
ui->enable_overlay->setChecked(Settings::values.enable_overlay.GetValue());
ui->overlay_port->setValue(Settings::values.overlay_port.GetValue());
```

### Settings 消费：HID Core 启动/停止 UDP 监听

设置定义好了、UI 也能读写，但还需要在 HID 层实际使用它们。

#### 消费点：`EmulatedController` 或 `HIDCore`

有几种方案：

**方案 A：在 `StartOverlayUdp()` 中读取**（推荐，最简单）

`StartOverlayUdp()` 在 `EmulatedController` 构造函数或初始化时调用，读取 settings 决定行为：

```cpp
void EmulatedController::StartOverlayUdp() {
    if (!Settings::values.enable_overlay) {
        return;  // overlay 关闭，不启动 UDP 监听
    }
    u16 port = Settings::values.overlay_port;
    // bind UDP socket on 0.0.0.0:port
    // spawn receive thread or register to poll in StatusUpdate()
}
```

`StartOverlayUdp()` 调用时机：
- 模拟器启动时（`EmulatedController` 构造）
- 用户在 UI 修改设置后点击 Apply → 重启模拟器时生效

**方案 B：热切换（监听 settings 变化，立即启动/停止）**

`ApplyConfiguration()` 保存设置后发信号，HID 层接收信号，动态 bind/unbind UDP socket。更复杂但用户体验更好。

**当前采用方案 A**。overlay 开关变更需要重启模拟器才生效（和大部分 Controls 设置一致）。

#### 设置保存和加载

Eden 的 settings 系统自动处理持久化。`Setting<bool>` 和 `Setting<u16>` 通过 `linkage` 自动读写 `qt-config.ini`：

```ini
[Controls]
enable_overlay=true
overlay_port=26760
```

不需要额外写序列化代码。

### 完整文件清单

| 文件 | 操作 | 行数（参考） | 说明 |
|---|---|---|---|
| `eden/src/common/settings.h` | 插入 2 行 | L715 附近 | 加 `enable_overlay` + `overlay_port` |
| `eden/src/yuzu/configuration/configure_input_advanced.ui` | 追加 ~30 行 | OtherGridLayout 末尾 | 加 checkbox + spinbox |
| `eden/src/yuzu/configuration/configure_input_advanced.cpp` | 追加 2+2 行 | ApplyConfiguration / LoadConfiguration 末尾 | 读写 UI 控件到 settings |
| `eden/src/hid_core/frontend/emulated_controller.cpp` | 追加 ~20 行 | StartOverlayUdp() 实现 | 读取 settings 决定是否监听 |

### 与现有 DSU UDP Controller 的区分

Eden 已有 `enable_udp_controller`（DSU/Cemuhook 协议），配置页上它的 label 是 "Enable UDP controllers (not needed for motion)"。这是**另一个功能**——把外部的真实手柄（通过 DSU 协议）映射到 Eden 的虚拟控制器。

我们的 overlay 是**完全不同的东西**——接收 OVER 协议的 80-byte 数据包，与物理输入混合 merge。两个开关独立工作，端口也独立配置。

DSU 相关设置（**不碰它**）：
```cpp
Setting<std::string> udp_input_servers;    // DSU 服务器地址，如 "192.168.1.5:26760"（出站连接）
Setting<bool> enable_udp_controller;       // 启用 DSU 客户端（连接外部手柄）
```

Overlay 新增设置：
```cpp
Setting<bool> enable_overlay;    // 启用 overlay UDP 监听（入站监听，接收 OVER 协议包）
Setting<u16> overlay_port;       // 监听端口（默认 26760）
```

两者不冲突——DSU 是出站客户端（连接外部手柄到 Eden），overlay 是入站服务器（外部 app 发数据给 Eden）。端口可以相同是因为 DSU 客户端用的是远程地址，overlay 监听的是本地端口。

## apply_overlay.sh
- 复制 overlay 源文件到 `hid_core/frontend/`
- 打 controller patch（不需要 CPM/Lua/CMake 改动）
