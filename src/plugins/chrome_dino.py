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

    # Speed-adaptive scan strip parameters.
    # At min speed (game start), jump strip at 27%. At max speed, at 37%.
    JX_BASE = 0.27       # jump strip start at minimum speed
    JX_MAX = 0.40        # jump strip start at maximum speed
    JX_WIDTH = 0.06      # jump strip width (constant)
    DX_START = 0.20      # duck strip start (fixed, wide)
    DX_END = 0.45        # duck strip end (fixed, wide)
    DY_END = 0.40        # duck zone vertical limit (top 40% of ROI only)
    SPEED_MIN = 2.0      # px/frame at game start
    SPEED_MAX = 20.0     # px/frame at high speed (~600+ score)
    # Adaptive cooldown: shorter at higher speeds for closely-spaced obstacles
    COOLDOWN_MIN_MS = 100  # minimum cooldown at max speed
    COOLDOWN_MAX_MS = 350  # maximum cooldown at min speed

    def __init__(self):
        self._trigger_threshold = 500
        self._duck_threshold = 90
        self._cooldown_ms = 300
        self._last_action_time = 0
        self._last_action = "none"
        self._key_held = False
        self._prev_gray = None
        self._prev_ground = None  # for phase correlation speed measurement
        self._speed = 0.0         # smoothed scroll speed (px/frame)
        self._frame_count = 0
        self._peak_lower = 0
        self._peak_upper = 0
        self._peak_mr = 0.0
        self._peak_ignore = 0
        self._peak_speed = 0.0
        self._ptero_suspect = 0   # frames of early ptero warning
        self._zero_speed_frames = 0  # consecutive frames with near-zero scroll
        self._game_paused = False    # True when game is paused/game-over

    def setup(self, config):
        self._trigger_threshold = config.getint(
            "chrome-dino", "trigger_threshold", fallback=500
        )
        self._duck_threshold = config.getint(
            "chrome-dino", "duck_threshold", fallback=90
        )
        self._cooldown_ms = config.getint(
            "chrome-dino", "cooldown_ms", fallback=300
        )
        self._autoloop = getattr(config, 'autoloop', False)

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

        # Measure scroll speed via phase correlation on ground texture.
        # Use a horizontal strip near the ground line (bottom 20% of ROI,
        # avoiding the very bottom which may be below the game area).
        ground_strip = gray[int(h * 0.75):int(h * 0.95), :]
        if self._prev_ground is not None:
            curr_f = ground_strip.astype(np.float64)
            prev_f = self._prev_ground.astype(np.float64)
            shift, _ = cv2.phaseCorrelate(prev_f, curr_f)
            raw_speed = abs(shift[0])  # horizontal pixels/frame
            # Clamp outliers (scene changes, game over can give huge shifts)
            raw_speed = min(raw_speed, 20.0)
            # One-way ratchet: Chrome Dino speed never decreases during a run.
            # Only update if new measurement is higher (with gentle EMA to
            # smooth noise). Resets only on game pause/over detection.
            if raw_speed > self._speed:
                self._speed = 0.7 * self._speed + 0.3 * raw_speed
            # else: keep current speed — it never drops mid-game

            # Game pause/over detection (--autoloop only): track consecutive
            # near-zero speed frames. Only activate after speed ratchet proves
            # a game was running (speed >= SPEED_MIN).
            if self._autoloop:
                ZERO_SPEED_THRESH = 0.3   # px/frame — below this = no scroll
                PAUSE_FRAMES = 60         # ~2s at 30fps
                if self._speed >= self.SPEED_MIN and raw_speed < ZERO_SPEED_THRESH:
                    self._zero_speed_frames += 1
                    if self._zero_speed_frames >= PAUSE_FRAMES and not self._game_paused:
                        self._game_paused = True
                        self._speed = 0.0
                        self._ptero_suspect = 0
                        print("  >> GAME PAUSED/OVER detected — speed reset")
                else:
                    if self._game_paused:
                        self._game_paused = False
                        print("  >> GAME RESUMED — starting fresh")
                    self._zero_speed_frames = 0
        self._prev_ground = ground_strip.copy()

        # Threshold the difference to find significant motion
        # Pixels that changed by more than 30 brightness levels = motion
        _, motion = cv2.threshold(diff, 30, 255, cv2.THRESH_BINARY)

        # Adaptive scan strips: jump strip moves further ahead at higher speed.
        # Map speed [SPEED_MIN..SPEED_MAX] → jx_start [JX_BASE..JX_MAX]
        speed_frac = max(0.0, min(1.0,
            (self._speed - self.SPEED_MIN) / (self.SPEED_MAX - self.SPEED_MIN)
        ))
        jx_pct = self.JX_BASE + speed_frac * (self.JX_MAX - self.JX_BASE)
        jx_start = int(w * jx_pct)
        jx_end = int(w * (jx_pct + self.JX_WIDTH))
        dx_start = int(w * self.DX_START)
        dx_end = int(w * self.DX_END)
        dy_end = int(h * self.DY_END)   # duck zone top portion only
        y_ground = int(h * 0.50)

        # Check for scene-wide change (game over, restart, etc.)
        total_motion = int(np.sum(motion > 0))
        total_pixels = h * w
        motion_ratio = total_motion / total_pixels
        scene_change = motion_ratio > 0.15

        # Jump scan: lower portion of jump strip (cactus territory)
        scan = motion[y_ground:, jx_start:jx_end]
        scan_sum = int(np.sum(scan > 0))
        scan_pixels = max(scan.size, 1)
        scan_density = scan_sum / scan_pixels

        # Full-height jump strip for centroid-based ptero detection.
        # Use wider strip (duck x-range) for better ptero coverage.
        full_strip = motion[:, dx_start:dx_end]
        full_sum = int(np.sum(full_strip > 0))
        full_pixels = max(full_strip.size, 1)
        full_density = full_sum / full_pixels

        # Vertical centroid of motion in the full strip (0.0=top, 1.0=bottom).
        # Cactuses: centroid near bottom (~0.8-0.95, rooted to ground).
        # Pteros: centroid higher up (~0.4-0.7, floating).
        centroid_y = 1.0  # default: bottom (no motion)
        if full_sum > 0:
            y_coords = np.where(full_strip > 0)[0]
            centroid_y = float(np.mean(y_coords)) / h

        # Density thresholds
        JUMP_DENSITY = 0.08
        # Ptero confirmed: >2% density AND centroid above 50%.
        # Low pteros (cy 55-65%) must be jumped, not ducked — only duck
        # for medium/high pteros clearly above body height (cy < 50%).
        PTERO_MIN_DENSITY = 0.02
        PTERO_CENTROID = 0.50
        # Ptero early-warning: lower thresholds to suppress premature jumps.
        # Catches ptero leading edges before full body enters duck strip.
        PTERO_EARLY_DENSITY = 0.005  # 0.5% — above noise floor
        PTERO_EARLY_CENTROID = 0.55  # below low-ptero range (55-65%)

        # Suppress triggers during scene changes or game paused/over.
        if scene_change or self._game_paused:
            if scene_change:
                self._ptero_suspect = 0
                # Without --autoloop, reset speed on scene change (original behavior).
                # With --autoloop, pause detection handles the reset instead.
                if not self._autoloop:
                    self._speed = 0.0
            duck_triggered = False
            jump_triggered = False
        else:
            jump_triggered = scan_density > JUMP_DENSITY
            duck_triggered = False

            # Ptero early-warning: track frames with high centroid motion.
            # When the wide strip shows elevated motion (>0.5%) with centroid
            # above ground (<70%), something is floating — likely a ptero.
            if full_density > PTERO_EARLY_DENSITY and centroid_y < PTERO_EARLY_CENTROID:
                self._ptero_suspect = min(self._ptero_suspect + 1, 4)
            else:
                if self._ptero_suspect > 0:
                    self._ptero_suspect -= 1

            # Suppress jump while ptero is suspected (max 4 frames ≈ 130ms).
            # Safe because cactus centroid is 81-87%, never below 70%.
            if jump_triggered and self._ptero_suspect > 0:
                jump_triggered = False

            # Ptero confirmed: significant density with high centroid → duck
            if full_density > PTERO_MIN_DENSITY and centroid_y < PTERO_CENTROID:
                duck_triggered = True
                jump_triggered = False
                self._ptero_suspect = 0  # confirmed, reset

        # Save debug images after camera stabilizes
        self._frame_count += 1
        if self._frame_count == 30:
            self._save_debug(gray, diff, scan)
            print(f"  Jump: x[{jx_start}:{jx_end}] Duck: x[{dx_start}:{dx_end}]"
                  f" y_ground={y_ground} spd={self._speed:.1f}"
                  f" jx={jx_pct:.0%} diff_thresh=30")

        # Peak tracking (reset each 5-sec interval from main loop)
        self._peak_lower = max(self._peak_lower, scan_density)
        self._peak_upper = max(self._peak_upper, full_density)
        self._peak_mr = max(self._peak_mr, motion_ratio)
        self._peak_ignore = 0
        self._peak_speed = max(self._peak_speed, self._speed)

        # Debug stats
        self._debug_lower = scan_density
        self._debug_upper = centroid_y
        self._debug_ignore = full_density
        self._debug_thresh = 30
        self._debug_scene_change = scene_change
        self._debug_motion_ratio = motion_ratio
        self._debug_speed = self._speed
        self._debug_jx_pct = jx_pct

        return {
            "jump": jump_triggered,
            "duck": duck_triggered,
            "is_night": is_night,
            "bg_brightness": bg_brightness,
            "game_paused": self._game_paused,
        }

    def decide(self, state):
        import time
        now_ms = time.time() * 1000

        # Adaptive cooldown: shorter at higher speeds for close obstacles
        speed_frac = max(0.0, min(1.0,
            (self._speed - self.SPEED_MIN) / (self.SPEED_MAX - self.SPEED_MIN)
        ))
        cooldown = self.COOLDOWN_MAX_MS - speed_frac * (
            self.COOLDOWN_MAX_MS - self.COOLDOWN_MIN_MS
        )

        # Cooldown: don't act too frequently
        if now_ms - self._last_action_time < cooldown:
            if not state["jump"] and not state["duck"] and self._key_held:
                self._key_held = False
                return {"action": "release"}
            return {"action": "none"}

        # Duck takes priority over jump: medium pterodactyl at face level
        # must be ducked, not jumped into.
        if state["duck"]:
            print(f"  >> DUCK jmp={self._debug_lower:.0%} cy={self._debug_upper:.0%}"
                  f" fd={self._debug_ignore:.1%} ps={self._ptero_suspect}"
                  f" spd={self._debug_speed:.1f} jx={self._debug_jx_pct:.0%}"
                  f" mr={self._debug_motion_ratio:.2f}")
            self._last_action_time = now_ms
            self._last_action = "duck"
            self._key_held = True
            return {"action": "duck"}
        elif state["jump"]:
            # Jump zone: cactus or low pterodactyl
            print(f"  >> JUMP jmp={self._debug_lower:.0%} cy={self._debug_upper:.0%}"
                  f" fd={self._debug_ignore:.1%} ps={self._ptero_suspect}"
                  f" spd={self._debug_speed:.1f} jx={self._debug_jx_pct:.0%}"
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
