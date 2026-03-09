"""Chrome Dino game plugin for gameplayer-bot.

Uses frame differencing to detect moving obstacles. Static elements (ground
line, score, dino body) cancel out between consecutive frames, so only
approaching obstacles are detected.

The ROI should frame the game area. The plugin scans the right portion
(ahead of the dino) for motion.

Actions:
- Jump (spacebar): lower zone motion detected (cactus or low bird)
- Duck (down arrow): upper zone only has motion (medium/high bird)
"""

import os
import cv2
import numpy as np

from plugins.base import GamePlugin
from hid import keyboard_report, KEY_SPACE, KEY_DOWN, KEY_NONE

DEBUG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "tests", "sample_frames"
)


class ChromeDinoPlugin(GamePlugin):
    name = "chrome-dino"
    hid_type = "keyboard"

    def __init__(self):
        self._trigger_threshold = 500
        self._cooldown_ms = 300
        self._last_action_time = 0
        self._last_action = "none"
        self._key_held = False
        self._prev_gray = None
        self._frame_count = 0

    def setup(self, config):
        self._trigger_threshold = config.getint(
            "chrome-dino", "trigger_threshold", fallback=500
        )
        self._cooldown_ms = config.getint(
            "chrome-dino", "cooldown_ms", fallback=300
        )

    def calibrate(self, frame):
        os.makedirs(DEBUG_DIR, exist_ok=True)
        cv2.imwrite(
            os.path.join(DEBUG_DIR, "debug_full.png"),
            cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        )
        print(f"  Debug images saved to {DEBUG_DIR}")

    def _save_debug(self, gray, diff, scan_area):
        """Save debug images."""
        os.makedirs(DEBUG_DIR, exist_ok=True)
        cv2.imwrite(os.path.join(DEBUG_DIR, "debug_roi_gray.png"), gray)
        cv2.imwrite(os.path.join(DEBUG_DIR, "debug_diff.png"), diff)
        cv2.imwrite(os.path.join(DEBUG_DIR, "debug_scan_area.png"), scan_area)

    def detect(self, frame):
        gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
        h, w = gray.shape

        # Blur to reduce camera noise
        gray = cv2.GaussianBlur(gray, (5, 5), 0)

        # Day/night detection from top-left corner
        bg_brightness = float(np.mean(gray[:15, :15]))
        is_night = bg_brightness < 128

        # Frame differencing: absolute difference between current and previous
        if self._prev_gray is None:
            self._prev_gray = gray.copy()
            return {
                "lower": False, "upper": False,
                "is_night": is_night, "bg_brightness": bg_brightness,
            }

        diff = cv2.absdiff(gray, self._prev_gray)
        self._prev_gray = gray.copy()

        # Threshold the difference to find significant motion
        # Pixels that changed by more than 30 brightness levels = motion
        _, motion = cv2.threshold(diff, 30, 255, cv2.THRESH_BINARY)

        # Scan area: narrow strip ahead of dino
        x_start = int(w * 0.40)
        x_end = int(w * 0.55)
        y_mid = h // 2

        scan = motion[:, x_start:x_end]
        upper_zone = motion[:y_mid, x_start:x_end]
        lower_zone = motion[y_mid:, x_start:x_end]

        lower_sum = int(np.sum(lower_zone > 0))
        upper_sum = int(np.sum(upper_zone > 0))
        lower_triggered = lower_sum > self._trigger_threshold
        # Upper zone: stars/moon give ~75 max with narrow strip
        # Pterodactyl should give more — use same threshold as lower
        upper_triggered = upper_sum > self._trigger_threshold

        # Save debug images after camera stabilizes
        self._frame_count += 1
        if self._frame_count == 30:
            self._save_debug(gray, diff, scan)
            print(f"  Scan: x[{x_start}:{x_end}] y_mid={y_mid}"
                  f" diff_thresh=30")

        # Debug stats
        self._debug_lower = lower_sum
        self._debug_upper = upper_sum
        self._debug_thresh = 30

        return {
            "lower": lower_triggered,
            "upper": upper_triggered,
            "is_night": is_night,
            "bg_brightness": bg_brightness,
        }

    def decide(self, state):
        import time
        now_ms = time.time() * 1000

        # Cooldown: don't act too frequently
        if now_ms - self._last_action_time < self._cooldown_ms:
            if not state["lower"] and not state["upper"] and self._key_held:
                self._key_held = False
                return {"action": "release"}
            return {"action": "none"}

        # Time since last jump — used to suppress false upper-zone triggers
        # from the dino's own jump animation (~600ms arc)
        time_since_jump = now_ms - self._last_action_time

        if state["lower"]:
            # Lower zone: cactus or low bird -> jump
            self._last_action_time = now_ms
            self._last_action = "jump"
            self._key_held = True
            return {"action": "jump"}
        elif state["upper"] and time_since_jump > 800:
            # Upper zone only, and dino hasn't jumped recently (not in mid-air)
            # This catches mid/high-level pterodactyls.
            # The 800ms guard avoids false triggers from dino's jump motion.
            self._last_action_time = now_ms
            self._last_action = "duck"
            self._key_held = True
            return {"action": "duck"}
        else:
            # No obstacle: release any held key
            if self._key_held:
                self._key_held = False
                return {"action": "release"}
            return {"action": "none"}

    def get_hid_report(self, action):
        act = action["action"]
        if act == "jump":
            return keyboard_report(key=KEY_SPACE)
        elif act == "duck":
            return keyboard_report(key=KEY_DOWN)
        else:
            return keyboard_report(key=KEY_NONE)
