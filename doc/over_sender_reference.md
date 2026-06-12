###  Quick reference — all basic functions


```python
# buttons
{
    "a": "A", "b": "B", "x": "X", "y": "Y",
    "l": "L", "r": "R", "zl": "ZL", "zr": "ZR",
    "plus": "PLUS", "minus": "MINUS", "+": "PLUS", "-": "MINUS",
    "up": "UP", "down": "DOWN", "left": "LEFT", "right": "RIGHT",
}

# sticks
['left','right']

from scripts.over_sender import OverSender

sender = OverSender(pad_id=0)          # defaults: 127.0.0.1:26760, pad 0

# Buttons
sender.buttons(A=True, B=True)         # press A and B (auto-sets control_mask bit 0)
sender.clear_buttons()                 # release all buttons

# Sticks — side="left" or "right", x/y in [-1.0, 1.0]
sender.stick("left",  x=0.5, y=0)      # left stick half-right
sender.stick("right", x=0,   y=-1.0)   # right stick all the way down

# Motion — source="left" or "right"
sender.motion("left", gyro=(0, 0.1, 0))            # left gyro Y=0.1 rad/s
sender.motion("right", accel=(0, 0, 1.0))          # right accel Z=1.0 G

# Send
sender.send()                           # send one packet

# Shortcuts
sender.tap("A")                         # press A → sleep 50ms → release (2 packets)
sender.stick_tap("left", 1.0, 0)        # flick left stick right, then return to center

# Chaining
sender.stick("left", 1.0, 0).buttons(A=True).send()
```