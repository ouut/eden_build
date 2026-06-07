# Eden Overlay C++

## 设计原则
- 不引入 Lua。逻辑全在 C++。
- 单 slot，单层——只有一个 overlay 输入源。
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

## OverlayState（唯一一份，非数组）
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
```

## UDP 协议（72-byte，little-endian）

单一固定格式。发送端永远发 72 字节，接收端读到少于 72 字节则丢弃。

```
Offset  Type    Field
────────────────────────────────────────────────
[0]     char[4] magic "OVER"
[4]     u32     button_mask        按键位图
[8]     f32     left_x             左摇杆 X，-1.0 ~ 1.0
[12]    f32     left_y             左摇杆 Y
[16]    f32     right_x            右摇杆 X
[20]    f32     right_y            右摇杆 Y
[24]    f32     left_gyro_x        左手陀螺 X，rad/s
[28]    f32     left_gyro_y
[32]    f32     left_gyro_z
[36]    f32     left_accel_x       左手加速度 X，G
[40]    f32     left_accel_y
[44]    f32     left_accel_z
[48]    f32     right_gyro_x       右手陀螺 X，rad/s
[52]    f32     right_gyro_y
[56]    f32     right_gyro_z
[60]    f32     right_accel_x      右手加速度 X，G
[64]    f32     right_accel_y
[68]    f32     right_accel_z
────────────────────────────────────────────────
        Total: 72 bytes
```

Python 发送示例：
```python
struct.pack('<4sI20f', b'OVER', buttons,
    lx, ly, rx, ry,
    lgx, lgy, lgz, lax, lay, laz,
    rgx, rgy, rgz, rax, ray, raz)
```

### 设计理由
- **固定长度** — 不需要 length 字段，收多收少直接判断
- **无标志位** — magic 即格式标识，不引入版本号/可选字段
- **零就是零** — 不存在「这个字段没发货」，所有字段始终存在
- **跨语言** — C struct / Python struct.pack / Java ByteBuffer 都能一行构造

## 摇杆值域与 Eden 的对应关系

Eden 内部：
- `StickStatus.x.value` / `y.value` — **f32，范围 -1.0 ~ 1.0**
- `AnalogStickState` — `{s32 x, s32 y}`，写入时做：`s32(value * 32767)`（`HID_JOYSTICK_MAX = 0x7FFF`）

Overlay 协议直接使用 f32（-1.0 ~ 1.0），ApplyOverlay() 里乘以 32767 写到 `analog_stick_state`。

## Merge 规则（最终版）

### 按键：OR 合并
```
npad_button_state.raw |= overlay_state.button_mask
```
每帧 `npad_button_state` 从硬件重新读取，OR 是无状态的——overlay 清零后下一帧自动恢复纯物理输入，无残留。

### 摇杆/体感：pure last-write-wins
```
if (overlay_last_write > prev_last_write) {
    // 覆盖，含零值——归中是有意义的操作
    apply_overlay_value();
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

### 场景
Overlay 发送端通过 UDP 发包。UDP 无连接、无心跳、无对端存活检测。如果：
- 网络断开（Wi-Fi 中断、网线松脱）
- 发送端 app 崩溃或退出
- 发送端机器 sleep

模拟器收不到新包，但不知道对端已死。上一次收到的摇杆/按键值会永久残留——摇杆卡住、按钮常按。

物理 Joy-Con 不存在此问题：蓝牙有心跳，HID 层在连接断开时立刻感知并清理状态。

### 方案
- **超时值**：100ms（约 6 帧 @60Hz，局域网内足够宽松）
- **超时行为**：全清零 —— `active = false`，清空所有 button_mask 和 stick/motion 值
- **实现位置**：`ApplyOverlay()` 函数开头，每次 StatusUpdate 调用时检查

```
每帧 ApplyOverlay():
    now = steady_clock::now()
    if (now - overlay_state.last_update > 100ms) {
        overlay_state.active = false;
        overlay_state.button_mask = 0;
        // sticks, motion 全部归零
        return;  // 跳过 overlay，本帧纯物理输入
    }
```

### 注意
清零后 `active = false`，merge 层检查此标志：
- `active == false` → 完全跳过 overlay，不比较时间戳
- 避免「用归零覆盖物理输入」——清零是移除 overlay，不是用零值写入

## UDP 接收策略

- `StatusUpdate()` 调用频率 ≈ 60Hz
- 每帧之间可能积压多个 UDP 包
- **循环 recvfrom 直到缓冲区空，只消费最后一个包**
- 前面积压的包直接丢弃，不处理

原因：用一个过时包更新状态后立刻被下一个包覆盖，徒增 CPU 开销。

## EmulatedController patch（最小改动）
- `.h`: 加 `#include`、`OverlayState` 成员、`ApplyOverlay()` 声明、`StartOverlayUdp()` 声明
- `.cpp`: `StatusUpdate()` 末尾加 `ApplyOverlay()` 调用、`ApplyOverlay()` 实现、`StartOverlayUdp()` 实现

## apply_overlay.sh
- 复制 overlay 源文件到 `hid_core/frontend/`
- 打 controller patch（不需要 CPM/Lua/CMake 改动）
