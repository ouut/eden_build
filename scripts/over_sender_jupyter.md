# OverSender Jupyter 使用指南

## 导入

```python
import sys
sys.path.insert(0, '/Users/cc/projects/switch/overlay_cpp')
from scripts.over_sender import OverSender

sender = OverSender(pad_id=0)          # 默认 127.0.0.1:26760
sender = OverSender(host="192.168.1.100", port=26760, pad_id=0)  # 远程
```

## 核心规则

**`buttons()` / `stick()` / `motion()` 只改本地状态，必须 `.send()` 才发 UDP 包。**

```python
sender.buttons(A=True)          # ❌ 没发包，白写
sender.buttons(A=True).send()   # ✅
```

`tap()` 和 `stick_tap()` 内部替你调了 `send()`，不需要额外加。

---

## 按键

### tap — 按了自动松（推荐用于交互）

```python
sender.tap("A")                              # 单键
sender.tap("A", "B")                         # 组合
sender.tap("ZL", "B", duration=0.1)          # 按住 100ms
```

### 手动 press-hold-release

```python
sender.buttons(A=True).send()                # 按下
time.sleep(1)
sender.clear_buttons().send()                # 松开
```

按住期间可以连续发 hold 包：

```python
sender.buttons(A=True).send()                # 按下
for _ in range(60):                          # 持续 1 秒 @60Hz
    sender.send()
    time.sleep(1/60)
sender.clear_buttons().send()                # 松开
```

### 合法按键名

```
A, B, X, Y          — 面部键
L, R, ZL, ZR         — 肩键
PLUS, MINUS          — +/-（也可用 "+", "-"）
UP, DOWN, LEFT, RIGHT — 十字键
STICK_L, STICK_R     — 摇杆按下
LEFT_SL, LEFT_SR, RIGHT_SL, RIGHT_SR — SL/SR 键
```

### 非法按键

`W`、`SPACE`、键盘字母都不行。这是 Switch 手柄协议，只认上面的 Switch 按键。

---

## 摇杆

### stick — 推摇杆

```python
sender.stick("left", 1.0, 0).send()          # 左摇杆推到最右
sender.stick("left", 0.5, -0.8).send()       # 左摇杆 X=0.5, Y=-0.8
sender.stick("right", 0, -1.0).send()        # 右摇杆推到最下
sender.stick("left", 0, 0).send()            # 归中
```

`x` 正=右, `y` 正=上（值域 -1.0 ~ 1.0）。

### stick_tap — flick 一下

```python
sender.stick_tap("left", 1.0, 0)             # 向右 flick
sender.stick_tap("right", 0, -1.0, duration=0.1)  # 向下 flick，100ms
```

### 左右同时

```python
sender.stick("left", 0.8, 0).stick("right", 0, -0.5).send()
```

### 和按键组合

```python
sender.buttons(B=True).stick("left", -0.8, 0).send()
```

---

## 体感

```python
sender.motion("left", gyro=(0.1, 0, 0)).send()     # 左手陀螺 X 轴旋转
sender.motion("right", accel=(0, 0, 1.5)).send()   # 右手加速度
sender.motion("left", gyro=(0, 0.1, 0), accel=(0, 0, 1)).send()  # 同时
```

`gyro` 单位 rad/s（角速度），`accel` 单位 G（1.0 = 重力加速度）。

---

## control_mask 手动控制

一般不需要手动设，helpers 会自动置位。需要精细控制时：

```python
sender.control(buttons=True, left_x=True) \
      .stick("left", 0.5, 0) \
      .send()
# 只接管 buttons + left_x，其他轴保留物理值
```

---

## 常见错误

| 错误 | 原因 | 正确写法 |
|---|---|---|
| `tap("W")` 报错 | `W` 不是 Switch 按键 | 用 `UP`, `Y` 等合法键名 |
| 手动 press/release 没生效 | 没调 `.send()` | 加 `.send()` |
| `buttons(A=False)` 没松开 | 只改本地状态，没发包 | `clear_buttons().send()` |
| stick 值没生效 | 忘了 `.send()` | 加 `.send()` |
