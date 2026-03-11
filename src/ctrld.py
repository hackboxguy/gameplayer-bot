#!/usr/bin/env python3
"""dino-player-ctrld: headless controller daemon for Pi Zero 2W.

Orchestrates the gameplayer-bot lifecycle without SSH or USB keyboard:
  1. Wait for white Notepad window to appear (camera)
  2. Run guided ROI calibration (LED blinks)
  3. Wait for Notepad to be removed
  4. Start main.py game loop
  5. Monitor /tmp/gp-state for game_over
  6. On game_over: kill main.py, check for Notepad
     - Notepad present → re-calibrate (step 2)
     - No Notepad → restart game (step 4)

Usage:
    sudo python3 src/ctrld.py --camera csi
    sudo python3 src/ctrld.py --camera csi --boot-delay 15
"""

import argparse
import os
import signal
import subprocess
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from camera import create_camera
from config import Config

STATE_FILE = "/tmp/gp-state"
LED_PATH = "/sys/class/leds/ACT"
LED_SAVE = "/tmp/gp-led-trigger"

# How often to poll for state changes (seconds)
POLL_INTERVAL = 1.0
# How often to capture a frame for Notepad detection (seconds)
CAPTURE_INTERVAL = 2.0


def log(msg):
    print(f"ctrld: {msg}", flush=True)


def save_led_trigger():
    """Save the current LED trigger before changing it."""
    trigger_path = os.path.join(LED_PATH, "trigger")
    try:
        with open(trigger_path, "r") as f:
            content = f.read()
        # Active trigger is shown in [brackets]
        import re
        m = re.search(r'\[(\S+)\]', content)
        if m:
            with open(LED_SAVE, "w") as f:
                f.write(m.group(1))
    except OSError:
        pass


def restore_led_trigger():
    """Restore the LED to its original trigger."""
    try:
        if os.path.exists(LED_SAVE):
            with open(LED_SAVE, "r") as f:
                trigger = f.read().strip()
            with open(os.path.join(LED_PATH, "trigger"), "w") as f:
                f.write(trigger)
            os.remove(LED_SAVE)
        else:
            with open(os.path.join(LED_PATH, "trigger"), "w") as f:
                f.write("mmc0")
    except OSError:
        pass


def set_led_blink():
    """Set the ACT LED to fast blink (calibrating)."""
    try:
        with open(os.path.join(LED_PATH, "trigger"), "w") as f:
            f.write("timer")
        with open(os.path.join(LED_PATH, "delay_on"), "w") as f:
            f.write("100")
        with open(os.path.join(LED_PATH, "delay_off"), "w") as f:
            f.write("100")
    except OSError:
        pass


def detect_notepad(cam):
    """Capture a frame and check for a white Notepad rectangle.

    Uses the same logic as guided_roi() in main.py: threshold for bright
    white pixels, find contours, look for a wide rectangle.

    Returns:
        True if a Notepad-like white rectangle is detected.
    """
    frame = cam.capture()
    gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)

    # Threshold for bright white (Notepad background > 200)
    _, white_mask = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)

    # Clean up noise
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    white_mask = cv2.morphologyEx(white_mask, cv2.MORPH_OPEN, kernel)
    white_mask = cv2.morphologyEx(white_mask, cv2.MORPH_CLOSE, kernel)

    # Find contours
    contours, _ = cv2.findContours(white_mask, cv2.RETR_EXTERNAL,
                                    cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return False

    # Look for a wide white rectangle (same criteria as guided_roi)
    for c in contours:
        rx, ry, rw, rh = cv2.boundingRect(c)
        aspect = rw / max(rh, 1)
        if rw >= 60 and rh >= 20 and aspect >= 1.5:
            return True

    return False


def read_state():
    """Read the game state from /tmp/gp-state."""
    try:
        with open(STATE_FILE, "r") as f:
            return f.read().strip()
    except (OSError, FileNotFoundError):
        return ""


def run_guided_roi(cfg, camera_override):
    """Run main.py --guided-roi as a subprocess. Returns True on success."""
    repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cmd = [sys.executable, os.path.join(repo_dir, "src", "main.py"),
           "--guided-roi"]
    if camera_override:
        cmd += ["--camera", camera_override]
    log(f"running: {' '.join(cmd)}")
    result = subprocess.run(cmd)
    return result.returncode == 0


def start_game(cfg, camera_override):
    """Start main.py game loop as a subprocess. Returns the Popen object."""
    repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cmd = [sys.executable, os.path.join(repo_dir, "src", "main.py"),
           "--autoloop"]
    if camera_override:
        cmd += ["--camera", camera_override]
    log(f"starting game: {' '.join(cmd)}")
    proc = subprocess.Popen(cmd)
    return proc


def stop_game(proc):
    """Stop the main.py game process."""
    if proc is None:
        return
    if proc.poll() is None:
        log("stopping game process...")
        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    log(f"game process exited (code={proc.returncode})")


def main():
    parser = argparse.ArgumentParser(description="dino-player-ctrld")
    parser.add_argument("--config", default=None,
                        help="Path to game.ini config file")
    parser.add_argument("--camera", choices=["auto", "csi", "usb"],
                        default=None, help="Override camera type")
    parser.add_argument("--boot-delay", type=int, default=10,
                        help="Seconds to wait at startup (default: 10)")
    args = parser.parse_args()

    cfg = Config(args.config)
    camera_type = args.camera or cfg.camera_type

    log("starting dino-player-ctrld")
    log(f"camera={camera_type} boot-delay={args.boot_delay}s")

    if args.boot_delay > 0:
        log(f"waiting {args.boot_delay}s for system to stabilize...")
        time.sleep(args.boot_delay)

    game_proc = None

    try:
        while True:
            # --- PHASE 1: Wait for Notepad ---
            log("waiting for Notepad window...")
            cam = create_camera(camera_type, cfg.camera_width,
                                cfg.camera_height, cfg.camera_fps,
                                cfg.camera_device)
            cam.start()
            time.sleep(2)  # let camera auto-expose

            # Flush a few frames for exposure
            for _ in range(5):
                cam.capture()

            while not detect_notepad(cam):
                time.sleep(CAPTURE_INTERVAL)

            cam.stop()
            log("Notepad detected!")

            # --- PHASE 2: Calibrate ROI ---
            save_led_trigger()
            set_led_blink()
            log("starting ROI calibration...")

            success = run_guided_roi(cfg, args.camera)
            restore_led_trigger()

            if not success:
                log("calibration failed, retrying in 10s...")
                time.sleep(10)
                continue

            log("calibration successful")

            # Reload config to get the updated ROI
            cfg = Config(args.config)
            if args.camera:
                cfg.camera_type = args.camera

            # --- PHASE 3: Wait for Notepad removal ---
            log("waiting for Notepad to be removed...")
            cam = create_camera(camera_type, cfg.camera_width,
                                cfg.camera_height, cfg.camera_fps,
                                cfg.camera_device)
            cam.start()
            time.sleep(2)

            for _ in range(5):
                cam.capture()

            while detect_notepad(cam):
                time.sleep(CAPTURE_INTERVAL)

            cam.stop()
            log("Notepad removed!")
            time.sleep(1)  # brief pause before starting game

            # --- PHASE 4+5: Play and restart loop ---
            # Keep restarting the game until Notepad reappears.
            while True:
                game_proc = start_game(cfg, args.camera)
                time.sleep(3)  # wait for game to initialize

                # Monitor for game_over
                log("monitoring game state...")
                while True:
                    if game_proc.poll() is not None:
                        log(f"game process exited (code={game_proc.returncode})")
                        break
                    state = read_state()
                    if state == "game_over":
                        log("game over detected!")
                        break
                    time.sleep(POLL_INTERVAL)

                stop_game(game_proc)
                game_proc = None
                time.sleep(1)

                # Check if Notepad is back (user wants to stop/re-calibrate)
                cam = create_camera(camera_type, cfg.camera_width,
                                    cfg.camera_height, cfg.camera_fps,
                                    cfg.camera_device)
                cam.start()
                time.sleep(2)
                for _ in range(5):
                    cam.capture()

                notepad_back = detect_notepad(cam)
                cam.stop()

                if notepad_back:
                    log("Notepad detected — will re-calibrate")
                    break  # break inner loop, outer loop goes to phase 1

                log("no Notepad — restarting game in 2s...")
                time.sleep(2)

    except KeyboardInterrupt:
        log("shutting down...")
    finally:
        if game_proc is not None:
            stop_game(game_proc)
        restore_led_trigger()
        log("stopped")


if __name__ == "__main__":
    main()
