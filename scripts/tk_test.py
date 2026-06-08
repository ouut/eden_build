#!/usr/bin/env python3
"""Minimal tkinter key event debugger. Tests if key events fire."""
import tkinter as tk
root = tk.Tk()
root.title("Key Test — press/release keys, watch terminal")
root.geometry("400x100")

def on_key(event):
    t = "PRESS" if event.type == "2" else "RELEASE" if event.type == "3" else f"TYPE={event.type}"
    print(f"[{t}] keycode={event.keycode} keysym={event.keysym} char={repr(event.char)}")

def on_press(event):
    print(f"[PRESS ONLY] keycode={event.keycode} keysym={event.keysym}")

def on_release(event):
    print(f"[RELEASE ONLY] keycode={event.keycode} keysym={event.keysym}")

root.bind("<KeyPress>", on_press)
root.bind("<KeyRelease>", on_release)
root.bind("<Key>", on_key)

print("Click the 'Key Test' window to focus it, then press/release keys.")
print("Watch this terminal for events.")
print("Close the window or Ctrl-C to quit.")
root.mainloop()
