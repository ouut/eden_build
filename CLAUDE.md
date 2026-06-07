# Eden Overlay C++

## 设计原则
- 不引入 Lua。逻辑全在 C++。
- 多 pad 支持（最多 8 玩家，匹配 Switch 硬件上限），UDP 包内 `pad_id` 区分目标 pad。
- UDP 接收输入，C++ 解析协议并写入 overlay 状态。
- 和物理输入的冲突处理：
  - 按键：OR 合并（任一方按下即生效）
  - 摇杆/体感：pure last-write-wins，由时间戳仲裁，零值也会覆盖

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
└── apply_overlay.sh
docs/
└── ARCHITECTURE.md
```

## OverlayState（数组，每 pad 一份，最多 8）
```cpp
struct OverlayState {
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

## UDP 协议（76-byte，little-endian）

单一固定格式。每包对应一个 pad，`pad_id` 区分目标。发送端永远发 76 字节，接收端读到少于 76 字节则丢弃。

```
Offset  Type    Field
────────────────────────────────────────────────
[0]     char[4] magic "OVER"
[4]     u8      pad_id             目标 pad 编号，0-7
[5]     u8[3]   _reserved          padding，保证对齐
[8]     u32     button_mask        按键位图
[12]    f32     left_x             左摇杆 X，-1.0 ~ 1.0
[16]    f32     left_y             左摇杆 Y
[20]    f32     right_x            右摇杆 X
[24]    f32     right_y            右摇杆 Y
[28]    f32     left_gyro_x        左手陀螺 X，rad/s
[32]    f32     left_gyro_y
[36]    f32     left_gyro_z
[40]    f32     left_accel_x       左手加速度 X，G
[44]    f32     left_accel_y
[48]    f32     left_accel_z
[52]    f32     right_gyro_x       右手陀螺 X，rad/s
[56]    f32     right_gyro_y
[60]    f32     right_gyro_z
[64]    f32     right_accel_x      右手加速度 X，G
[68]    f32     right_accel_y
[72]    f32     right_accel_z
────────────────────────────────────────────────
        Total: 76 bytes
```

Python 发送示例：
```python
struct.pack('<4sB3xI20f', b'OVER', pad_id, buttons,
    lx, ly, rx, ry,
    lgx, lgy, lgz, lax, lay, laz,
    rgx, rgy, rgz, rax, ray, raz)
```

### 设计理由
- **pad_id 在头部** — 收包后立刻知道目标 pad，不需要先解析全包体
- **固定长度** — 不需要 length 字段，收多收少直接判断
- **无标志位** — magic 即格式标识，不引入版本号/可选字段
- **每包一个 pad** — 不同 pad 的数据独立发送、独立 stale、独立 merge
- **零就是零** — 不存在「这个字段没发货」，所有字段始终存在
- **跨语言** — C struct / Python struct.pack / Java ByteBuffer 都能一行构造

## 摇杆值域与 Eden 的对应关系

Eden 内部：
- `StickStatus.x.value` / `y.value` — **f32，范围 -1.0 ~ 1.0**
- `AnalogStickState` — `{s32 x, s32 y}`，写入时做：`s32(value * 32767)`（`HID_JOYSTICK_MAX = 0x7FFF`）

Overlay 协议直接使用 f32（-1.0 ~ 1.0），ApplyOverlay() 里乘以 32767 写到 `analog_stick_state`。

## 部分覆盖问题（Open Issue）

### 场景：同一 pad，物理和 overlay 同时操作不同轴

用户用 pad 0 玩塞尔达：

- **左手**：持物理 Joy-Con，推左摇杆往前走 → `left_y = 0.8`
- **右手**：持手机，滑动右摇杆转视角 → 手机 app 发 UDP 到 pad 0

手机 app 构造的 UDP 包必须填充全部字段。它不关心左摇杆，所以填 0：

```
pad_id=0, left=(0,0), right=(0.5,0), buttons=0, motion...=0
```

帧序列：

```
帧1  StatusUpdate:
      物理输入: left=(0, 0.8), right=(0, 0)
      无 UDP 包，overlay active=false → 跳过
      → 角色往前走 ✅

帧2  收到 UDP 包:
      overlay_states[0]: left=(0, 0), right=(0.5, 0), last_update=t2
      
帧3  StatusUpdate:
      物理输入: left=(0, 0.8), right=(0, 0), last_write=t1
      overlay:  left=(0, 0), right=(0.5, 0), last_update=t2
      t2 > t1 → overlay 覆盖
      → 左摇杆归零，角色停下 ❌
      → 右摇杆向右，视角转动 ✅
```

**结果：角色本来在往前走，手机每发一帧 UDP，角色就被钉在原地。** 用户左手一直推摇杆，但 overlay 把左摇杆清零了。

### 为什么按键不会这样

按键 OR 合并：`button_mask | 0 = button_mask`。overlay 填 0 不会破坏物理按键。

摇杆 last-write-wins：`0` 就是归中，是一等公民的值。overlay 填 0 和「明确要求归中」无法区分。

### 根本矛盾

固定格式的全量包要求 sender 对每个字段表态。但 sender 只想控制其中一部分，没想控制的字段被迫填 0，而这个 0 会破坏物理输入。

### 方案 B：control_mask

包体增加 4 字节 control_mask，每个 bit 对应一个可控单元：

```
bit 0:  left_x       bit 1:  left_y
bit 2:  right_x      bit 3:  right_y
bit 4:  left_gyro    bit 5:  left_accel
bit 6:  right_gyro   bit 7:  right_accel
bit 8:  button_mask
```

merge 时，control_mask 中为 1 的字段走 last-write-wins；为 0 的字段不覆盖，保留物理值。

包体变为 80 字节（76 + 4）。**代价**：协议复杂度上升，sender 必须能计算 control_mask。

### 当前态度

先不做。可能的使用模式不是「同一 pad 物理和 overlay 混用」，而是「pad 0 全物理，pad 1-7 纯 overlay」。暂不接受这部分复杂度。

## Merge 规则（最终版）

每个 pad 独立 merge。ApplyOverlay() 根据收到的 `pad_id` 只操作 `overlay_states[pad_id]` 和对应 pad 的 `npad_button_state`。

### 按键：OR 合并
```
npad_button_state[pad_id].raw |= overlay_states[pad_id].button_mask
```
每帧 `npad_button_state` 从硬件重新读取，OR 是无状态的——overlay 清零后下一帧自动恢复纯物理输入，无残留。

### 摇杆/体感：pure last-write-wins
```
if (overlay_states[pad_id].last_update > prev_last_write[pad_id]) {
    // 覆盖，含零值——归中是有意义的操作
    apply_overlay_stick_and_motion(pad_id);
}
```
**不检查 non_zero**。归中（值=0）和推杆（值≠0）一样是需要生效的状态变更。

### 阈值 0.01
阈值存在于**值转换层**，不在 merge 决策层：
```
s32 to_stick_s32(f32 v) {
    if (|v| < 0.01) return 0;   // 过滤浮点噪声
    return s32(v * 32767);
}
```
作用：防止 0.001 之类浮点误差在 s32 输出中产生非零值。

### 为什么不需要 non_zero
Eden 自己的 `SetStick` 跳过了非 TAS 源的零值更新——这能工作是因为物理摇杆持续采样，总有写入发生。Overlay 是单一外部源：如果零值被 gate 掉，摇杆松手操作永远不生效，stick 会卡在最后一次非零值。

## Staleness 处理

每个 pad 独立计时、独立超时。

### 场景
Overlay 发送端通过 UDP 发包。UDP 无连接、无心跳、无对端存活检测。如果：
- 网络断开（Wi-Fi 中断、网线松脱）
- 发送端 app 崩溃或退出
- 发送端机器 sleep

模拟器收不到新包，但不知道对端已死。上一次收到的摇杆/按键值会永久残留——摇杆卡住、按钮常按。

物理 Joy-Con 不存在此问题：蓝牙有心跳，HID 层在连接断开时立刻感知并清理状态。

### 方案
- **超时值**：100ms（约 6 帧 @60Hz，局域网内足够宽松）
- **超时行为**：全清零 —— `active = false`，清空该 pad 的 button_mask 和 stick/motion 值
- **实现位置**：`ApplyOverlay()` 函数开头，每次 StatusUpdate 调用时对每个 pad 检查

```
每帧 ApplyOverlay():
    for pad_id in 0..7:
        now = steady_clock::now()
        if (now - overlay_states[pad_id].last_update > 100ms) {
            overlay_states[pad_id].active = false;
            overlay_states[pad_id].button_mask = 0;
            // sticks, motion 全部归零
            continue;  // 跳过此 pad
        }
        // 否则应用 overlay_states[pad_id]
```

### 注意
清零后 `active = false`，merge 层检查此标志：
- `active == false` → 完全跳过 overlay，不比较时间戳
- 避免「用归零覆盖物理输入」——清零是移除 overlay，不是用零值写入

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
