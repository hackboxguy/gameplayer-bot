#!/usr/bin/env python3
"""gameplayer-bot: camera-based game automation via USB HID.

Captures frames from a CSI camera, runs a game-specific detection plugin,
and sends keyboard/mouse input via USB HID gadget mode.

Usage:
    python3 src/main.py                 # Run with default config
    python3 src/main.py --config PATH   # Run with custom config
    python3 src/main.py --test-hid      # Send test keystrokes (no camera)
    python3 src/main.py --calibrate     # Capture and save a frame for ROI setup
"""

import argparse
import os
import sys
import time

# Add src/ to path so plugins can be imported
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import Config
import hid


def load_plugin(name):
    """Load a game plugin by name."""
    if name == "chrome-dino":
        from plugins.chrome_dino import ChromeDinoPlugin
        return ChromeDinoPlugin()
    elif name == "breakout":
        from plugins.breakout import BreakoutPlugin
        return BreakoutPlugin()
    else:
        print(f"Unknown plugin: {name}")
        sys.exit(1)


def test_hid():
    """Send test keystrokes to verify HID gadget is working."""
    print("gameplayer-bot: HID test mode")
    print("Sending 5 spacebar presses (one per second)...")
    print("Open a text editor on the host PC to see the output.")
    time.sleep(2)

    for i in range(5):
        print(f"  Press {i+1}/5: SPACE")
        hid.send_key_tap(hid.KEY_SPACE, hold_ms=80)
        time.sleep(1)

    print("Sending mouse movement: 50px right, 50px down...")
    for _ in range(50):
        hid.send_mouse(dx=1, dy=1)
        time.sleep(0.01)

    print("HID test complete.")


def calibrate(cfg):
    """Capture a single frame and save it for ROI calibration."""
    from camera import create_camera

    print("gameplayer-bot: calibration mode")
    print(f"Camera: {cfg.camera_type} {cfg.camera_width}x{cfg.camera_height} @ {cfg.camera_fps}fps")

    cam = create_camera(cfg.camera_type, cfg.camera_width, cfg.camera_height,
                         cfg.camera_fps, cfg.camera_device)
    cam.start()
    time.sleep(1)  # let camera auto-expose

    frame = cam.capture()
    cam.stop()

    outdir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "tests", "sample_frames"
    )
    os.makedirs(outdir, exist_ok=True)
    outpath = os.path.join(outdir, "calibration.png")

    import cv2
    # picamera2 gives RGB, OpenCV expects BGR for imwrite
    cv2.imwrite(outpath, cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
    print(f"Saved calibration frame: {outpath}")
    print(f"Frame size: {frame.shape[1]}x{frame.shape[0]}")
    print(f"Current ROI: {cfg.roi}")
    print("Edit configs/game.ini [roi] section to set the game area coordinates.")


def run(cfg):
    """Main game loop."""
    from camera import create_camera

    plugin_name = cfg.plugin_name
    print(f"gameplayer-bot: starting with plugin '{plugin_name}'")
    print(f"Camera: {cfg.camera_type} {cfg.camera_width}x{cfg.camera_height} @ {cfg.camera_fps}fps")
    print(f"ROI: {cfg.roi}")

    # Load plugin
    plugin = load_plugin(plugin_name)
    plugin.setup(cfg)

    # Select HID device path
    if plugin.hid_type == "mouse":
        hid_dev = hid.MOUSE_DEV
    else:
        hid_dev = hid.KEYBOARD_DEV

    # Verify HID device exists
    if not os.path.exists(hid_dev):
        print(f"ERROR: {hid_dev} not found.")
        print("Is the gameplayer-bot-gadget service running?")
        print("  sudo systemctl start gameplayer-bot-gadget")
        sys.exit(1)

    # Start camera
    cam = create_camera(cfg.camera_type, cfg.camera_width, cfg.camera_height,
                         cfg.camera_fps, cfg.camera_device)
    cam.start()
    time.sleep(1)  # let camera auto-expose

    # Calibrate with first frame
    frame = cam.capture()
    plugin.calibrate(frame)

    x1, y1, x2, y2 = cfg.roi
    print("gameplayer-bot: running (Ctrl+C to stop)")

    frame_count = 0
    start_time = time.time()

    try:
        while True:
            frame = cam.capture()

            # Crop to ROI
            roi = frame[y1:y2, x1:x2]

            # Plugin pipeline: detect -> decide -> act
            state = plugin.detect(roi)
            action = plugin.decide(state)
            report = plugin.get_hid_report(action)

            # Send HID report
            with open(hid_dev, "wb") as f:
                f.write(report)

            frame_count += 1

            # Print stats every 5 seconds
            elapsed = time.time() - start_time
            if elapsed >= 5.0:
                fps = frame_count / elapsed
                dbg = ""
                if hasattr(plugin, '_debug_lower'):
                    dbg = (f" lo={plugin._debug_lower}"
                           f" up={plugin._debug_upper}"
                           f" thr={plugin._debug_thresh}"
                           f" bg={state.get('bg_brightness', 0):.0f}")
                print(f"  fps={fps:.1f} action={action.get('action', '?')}"
                      f" night={state.get('is_night', '?')}{dbg}")
                frame_count = 0
                start_time = time.time()

    except KeyboardInterrupt:
        print("\ngameplayer-bot: stopped")
    finally:
        # Release all keys/buttons
        try:
            hid.send_keyboard_release()
        except (OSError, IOError):
            pass
        cam.stop()


def main():
    parser = argparse.ArgumentParser(description="gameplayer-bot")
    parser.add_argument("--config", default=None,
                        help="Path to game.ini config file")
    parser.add_argument("--test-hid", action="store_true",
                        help="Send test keystrokes (no camera needed)")
    parser.add_argument("--calibrate", action="store_true",
                        help="Capture a frame for ROI calibration")
    args = parser.parse_args()

    if args.test_hid:
        test_hid()
        return

    cfg = Config(args.config)

    if args.calibrate:
        calibrate(cfg)
        return

    run(cfg)


if __name__ == "__main__":
    main()
