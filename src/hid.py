"""HID keyboard and mouse report helpers for USB gadget mode.

Writes raw HID reports to /dev/hidg0 (keyboard) and /dev/hidg1 (mouse).
These device files are created by the gameplayer-bot-gadget.service.
"""

import struct

KEYBOARD_DEV = "/dev/hidg0"
MOUSE_DEV = "/dev/hidg1"

# USB HID keyboard key codes
KEY_NONE = 0x00
KEY_SPACE = 0x2C
KEY_DOWN = 0x51
KEY_UP = 0x52
KEY_LEFT = 0x50
KEY_RIGHT = 0x4F
KEY_ENTER = 0x28
KEY_ESC = 0x29

# Modifier bits
MOD_NONE = 0x00
MOD_LCTRL = 0x01
MOD_LSHIFT = 0x02
MOD_LALT = 0x04


def keyboard_report(key=KEY_NONE, modifier=MOD_NONE):
    """Build an 8-byte boot keyboard HID report.

    Args:
        key: USB HID key code (0x00 = no key / release).
        modifier: Modifier byte (Ctrl, Shift, Alt, GUI).

    Returns:
        8 bytes: [modifier, 0x00, key, 0, 0, 0, 0, 0]
    """
    return struct.pack("BBBBBBBB", modifier, 0, key, 0, 0, 0, 0, 0)


def mouse_report(buttons=0, dx=0, dy=0):
    """Build a 4-byte boot mouse HID report.

    Args:
        buttons: Button bits (bit0=left, bit1=right, bit2=middle).
        dx: X movement (-127 to +127, relative).
        dy: Y movement (-127 to +127, relative).

    Returns:
        4 bytes: [buttons, dx, dy, 0]
    """
    dx = max(-127, min(127, int(dx)))
    dy = max(-127, min(127, int(dy)))
    return struct.pack("Bbbb", buttons, dx, dy, 0)


def send_keyboard(key=KEY_NONE, modifier=MOD_NONE):
    """Send a keyboard report (press or release)."""
    report = keyboard_report(key, modifier)
    with open(KEYBOARD_DEV, "wb") as f:
        f.write(report)


def send_keyboard_release():
    """Send a keyboard release report (all keys up)."""
    send_keyboard(KEY_NONE)


def send_mouse(buttons=0, dx=0, dy=0):
    """Send a mouse report."""
    report = mouse_report(buttons, dx, dy)
    with open(MOUSE_DEV, "wb") as f:
        f.write(report)


def send_key_tap(key, modifier=MOD_NONE, hold_ms=80):
    """Send a key press followed by release after hold_ms.

    Args:
        key: USB HID key code.
        modifier: Modifier byte.
        hold_ms: How long to hold the key (milliseconds).
    """
    import time
    send_keyboard(key, modifier)
    time.sleep(hold_ms / 1000.0)
    send_keyboard_release()
