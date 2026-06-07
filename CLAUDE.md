# Eden Overlay C++

## 设计原则
- 不引入 Lua。逻辑全在 C++。
- 单 slot，单层——只有一个 overlay 输入源。
- UDP 接收输入，C++ 解析协议并写入 overlay 状态。
- 和物理输入的冲突处理：
  - 按键：OR 合并（任一方按下即生效）
  - 摇杆/体感：last-write-wins，由时间戳仲裁

## 为什么需要打 patch（不能只往文件末尾追加）
- `OverlayState overlay_state` 成员必须在 `EmulatedController` class 体内（`};` 之前）
- `ApplyOverlay()` 调用必须插入 `StatusUpdate()` 函数体末尾
- 两者都在文件中部，追加到文件末尾无效

## 目录结构
```
overlay/
├── overlay_state.h          # OverlayState 结构体
├── overlay_udp.h            # UDP 监听 + 24-byte 协议解析
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
    u32 button_mask{0};
    f32 left_x{0}, left_y{0};
    f32 right_x{0}, right_y{0};
    f32 left_gyro_x{0}, ..., left_accel_z{0};   // 12 个 motion 字段
    f32 right_gyro_x{0}, ..., right_accel_z{0};
    u64 last_update{0};
    bool active{false};
};
```

## UDP 协议（24-byte，little-endian）
沿用 overlay 分支的 OVER 协议：
```
[0]  magic "OVER" (4 bytes)
[4]  button_mask  u32
[8]  left_x       f32
[12] left_y       f32
[16] right_x      f32
[20] right_y      f32
```

## EmulatedController patch（最小改动）
- `.h`: 加 `#include`、`OverlayState` 成员、`ApplyOverlay()` 声明、`StartOverlayUdp()` 声明
- `.cpp`: `StatusUpdate()` 末尾加 `ApplyOverlay()` 调用、`ApplyOverlay()` 实现、`StartOverlayUdp()` 实现

## Merge 规则
- 按键：`npad_button_state.raw |= overlay_state.button_mask`
- 摇杆/体感：`last_write > prev_last_write && non_zero → 覆盖`
- staleness: 单独讨论（当前暂不处理）

## apply_overlay.sh
- 复制 overlay 源文件到 `hid_core/frontend/`
- 打 controller patch（不需要 CPM/Lua/CMake 改动）
