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
        self._peak_lower = 0
        self._peak_upper = 0
        self._peak_mr = 0.0

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

        # Day/night detection from center-left of ROI (guaranteed game area)
        sample_y = h // 3
        bg_brightness = float(np.mean(gray[sample_y:sample_y + 15, 10:25]))
        is_night = bg_brightness < 128

        # Frame differencing: absolute difference between current and previous
        if self._prev_gray is None:
            self._prev_gray = gray.copy()
            return {
                "jump": False, "duck": False,
                "is_night": is_night, "bg_brightness": bg_brightness,
            }

        diff = cv2.absdiff(gray, self._prev_gray)
        self._prev_gray = gray.copy()

        # Threshold the difference to find significant motion
        # Pixels that changed by more than 30 brightness levels = motion
        _, motion = cv2.threshold(diff, 30, 255, cv2.THRESH_BINARY)

        # Scan area: strip ahead of dino.
        # Dino at ~10-15%. Scan 28-38% = tighter to avoid early trigger
        # on wide obstacles (4-cactus clusters) at low speed.
        # Three vertical zones:
        #   0-35%:  ignore (stars, moon, high pterodactyl = safe to run)
        #   35-55%: duck zone (medium pterodactyl at face level)
        #   55-100%: jump zone (cactus, low pterodactyl at ground level)
        x_start = int(w * 0.28)
        x_end = int(w * 0.38)
        y_ignore = int(h * 0.35)  # above this: stars/moon/high ptero
        y_duck_end = int(h * 0.55)  # duck zone: 35-55%

        # Check for scene-wide change (game over, restart, etc.)
        total_motion = int(np.sum(motion > 0))
        total_pixels = h * w
        motion_ratio = total_motion / total_pixels
        scene_change = motion_ratio > 0.15

        scan = motion[y_ignore:, x_start:x_end]
        duck_zone = motion[y_ignore:y_duck_end, x_start:x_end]
        jump_zone = motion[y_duck_end:, x_start:x_end]

        duck_sum = int(np.sum(duck_zone > 0))
        jump_sum = int(np.sum(jump_zone > 0))

        # Suppress triggers during scene changes (game over/restart)
        if scene_change:
            duck_triggered = False
            jump_triggered = False
        else:
            duck_triggered = duck_sum > self._trigger_threshold
            jump_triggered = jump_sum > self._trigger_threshold

        # Save debug images after camera stabilizes
        self._frame_count += 1
        if self._frame_count == 30:
            self._save_debug(gray, diff, scan)
            print(f"  Scan: x[{x_start}:{x_end}] y_ign={y_ignore}"
                  f" y_duck_end={y_duck_end} diff_thresh=30")

        # Peak tracking (reset each 5-sec interval from main loop)
        self._peak_lower = max(self._peak_lower, jump_sum)
        self._peak_upper = max(self._peak_upper, duck_sum)
        self._peak_mr = max(self._peak_mr, motion_ratio)

        # Debug stats
        self._debug_lower = jump_sum
        self._debug_upper = duck_sum
        self._debug_thresh = 30
        self._debug_scene_change = scene_change
        self._debug_motion_ratio = motion_ratio

        return {
            "jump": jump_triggered,
            "duck": duck_triggered,
            "is_night": is_night,
            "bg_brightness": bg_brightness,
        }

    def decide(self, state):
        import time
        now_ms = time.time() * 1000

        # Cooldown: don't act too frequently
        if now_ms - self._last_action_time < self._cooldown_ms:
            if not state["jump"] and not state["duck"] and self._key_held:
                self._key_held = False
                return {"action": "release"}
            return {"action": "none"}

        # Duck takes priority over jump: medium pterodactyl at face level
        # must be ducked, not jumped into.
        if state["duck"]:
            print(f"  >> DUCK jmp={self._debug_lower} dck={self._debug_upper}"
                  f" mr={self._debug_motion_ratio:.2f}")
            self._last_action_time = now_ms
            self._last_action = "duck"
            self._key_held = True
            return {"action": "duck"}
        elif state["jump"]:
            # Jump zone: cactus or low pterodactyl
            print(f"  >> JUMP jmp={self._debug_lower} dck={self._debug_upper}"
                  f" mr={self._debug_motion_ratio:.2f}")
            self._last_action_time = now_ms
            self._last_action = "jump"
            self._key_held = True
            return {"action": "jump"}
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
