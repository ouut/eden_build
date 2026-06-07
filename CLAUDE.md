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

## apply_overlay.sh
- 复制 overlay 源文件到 `hid_core/frontend/`
- 打 controller patch（不需要 CPM/Lua/CMake 改动）
