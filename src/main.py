#!/usr/bin/env python3
"""gameplayer-bot: camera-based game automation via USB HID.

Captures frames from a CSI camera, runs a game-specific detection plugin,
and sends keyboard/mouse input via USB HID gadget mode.

Usage:
    python3 src/main.py                 # Run with default config
    python3 src/main.py --config PATH   # Run with custom config
    python3 src/main.py --camera csi    # Override camera type (auto/csi/usb/dummy)
    python3 src/main.py --test-hid      # Send test keystrokes (no camera)
    python3 src/main.py --calibrate     # Capture and save a frame for ROI setup
    python3 src/main.py --auto-roi      # Auto-detect Chrome Dino game area
    python3 src/main.py --guided-roi    # Detect ROI using white Notepad as guide
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


def auto_roi(cfg):
    """Auto-detect the Chrome Dino game area.

    Finds the largest uniform dark (night) or white (day) rectangle in the
    camera frame. This is far more robust than looking for the ground line,
    since the game area is always a large uniformly-colored region.

    Algorithm:
    1. Blur and compute local std deviation (uniformity map)
    2. Threshold to find uniform regions
    3. Find contours — largest rectangle = game area
    """
    import cv2
    import numpy as np
    from camera import create_camera

    print("gameplayer-bot: auto-ROI detection")
    print(f"Camera: {cfg.camera_type} {cfg.camera_width}x{cfg.camera_height}")

    cam = create_camera(cfg.camera_type, cfg.camera_width, cfg.camera_height,
                         cfg.camera_fps, cfg.camera_device)
    cam.start()
    print("Waiting for camera to stabilize...")
    time.sleep(2)
    for _ in range(10):
        frame = cam.capture()
    cam.stop()

    outdir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "tests", "sample_frames"
    )
    os.makedirs(outdir, exist_ok=True)

    frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
    cv2.imwrite(os.path.join(outdir, "auto_roi_input.png"), frame_bgr)

    gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
    h, w = gray.shape

    # Step 1: Build a "uniformity mask". The game area (dark or white bg)
    # has very low local variance compared to desktop/browser chrome.
    # Use a block-based approach: divide into 10x10 blocks, compute std.
    block = 10
    mask = np.zeros((h, w), dtype=np.uint8)
    for by in range(0, h - block, block):
        for bx in range(0, w - block, block):
            patch = gray[by:by + block, bx:bx + block]
            std = float(np.std(patch))
            mean = float(np.mean(patch))
            # Uniform AND (dark or bright) = game background
            # Exclude near-black (mean<25) to avoid monitor bezel
            if std < 15 and ((25 < mean < 120) or mean > 180):
                mask[by:by + block, bx:bx + block] = 255

    # Step 2: Open to remove small noise. NO close — we don't want to
    # merge the game area with taskbar/bezel/desktop patches.
    kernel_open = cv2.getStructuringElement(cv2.MORPH_RECT, (10, 10))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel_open)

    cv2.imwrite(os.path.join(outdir, "auto_roi_mask.png"), mask)

    # Step 3: Find contours and pick the best game-area candidate
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if not contours:
        print("ERROR: No uniform region found. Is the Chrome Dino game visible?")
        print(f"  Saved input frame: {os.path.join(outdir, 'auto_roi_input.png')}")
        print(f"  Uniformity mask: {os.path.join(outdir, 'auto_roi_mask.png')}")
        return

    # Score contours: game area should be large, wider than tall, NOT touching
    # frame edges (bezel/taskbar are at edges), and not a thin strip.
    margin = 5  # pixels from edge to consider "touching"
    best = None
    best_score = 0
    for c in contours:
        rx, ry, rw, rh = cv2.boundingRect(c)
        area = rw * rh
        aspect = rw / max(rh, 1)

        # Skip small regions
        if rw < 80 or rh < 40:
            continue
        # Skip tall/narrow (taskbar)
        if aspect < 1.0:
            continue
        # Skip regions touching frame edges (monitor bezel, taskbar)
        touches_edge = (rx <= margin or ry <= margin or
                        rx + rw >= w - margin or ry + rh >= h - margin)
        # Penalize edge-touching but don't discard (game might be near edge)
        edge_penalty = 0.3 if touches_edge else 1.0
        score = area * edge_penalty

        print(f"    region x={rx} y={ry} w={rw} h={rh}"
              f" aspect={aspect:.1f} area={area}"
              f" edge={'Y' if touches_edge else 'N'} score={score:.0f}")
        if score > best_score:
            best_score = score
            best = (rx, ry, rw, rh)

    if best is None:
        print("ERROR: No game-area region found.")
        print(f"  Saved input frame: {os.path.join(outdir, 'auto_roi_input.png')}")
        print(f"  Uniformity mask: {os.path.join(outdir, 'auto_roi_mask.png')}")
        return

    rx, ry, rw, rh = best
    print(f"  Best uniform region: x={rx} y={ry} w={rw} h={rh} area={rw * rh}")

    # Stage 2: Find the ground line within the uniform region.
    # The ground line is the most reliable anchor — a long horizontal edge.
    region_gray = gray[ry:ry + rh, rx:rx + rw]
    edges = cv2.Canny(region_gray, 50, 150)
    cv2.imwrite(os.path.join(outdir, "auto_roi_edges.png"), edges)

    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=40,
                             minLineLength=60, maxLineGap=20)

    # Find the ground line: near-horizontal, in lower portion of region,
    # with uniform game background ABOVE it (not browser chrome).
    ground_line = None
    ground_score = 0
    if lines is not None:
        for line in lines:
            lx1, ly1, lx2, ly2 = line[0]
            length = np.sqrt((lx2 - lx1) ** 2 + (ly2 - ly1) ** 2)
            angle = abs(np.degrees(np.arctan2(ly2 - ly1, lx2 - lx1)))
            if angle >= 10 or length < 50:
                continue

            mid_y = (ly1 + ly2) // 2
            y_frac = mid_y / rh  # 0=top, 1=bottom of region

            # Check band above this line for uniformity (game bg = low std)
            band_top = max(0, mid_y - 60)
            band_bot = max(0, mid_y - 10)
            if band_bot > band_top:
                band = region_gray[band_top:band_bot, :]
                band_std = float(np.std(band))
            else:
                band_std = 999

            # Score: prefer long lines, in lower half, with uniform bg above
            # Lines in top 30% get heavily penalized (browser chrome)
            pos_weight = 0.1 if y_frac < 0.3 else (0.5 + y_frac)
            uniformity_bonus = 2.0 if band_std < 25 else 1.0
            score = length * pos_weight * uniformity_bonus

            print(f"    hline: x={lx1}..{lx2} y={ly1}..{ly2}"
                  f" len={length:.0f} angle={angle:.1f}"
                  f" y_frac={y_frac:.2f} band_std={band_std:.1f}"
                  f" score={score:.0f}")

            if score > ground_score:
                ground_score = score
                ground_line = line[0]

    if ground_line is not None:
        lx1, ly1, lx2, ly2 = ground_line
        mid_y = (ly1 + ly2) // 2  # ground y within region

        # Use Hough only for y-position. Find true horizontal extent
        # by scanning the edge image along the ground line y (±3 rows).
        edge_band = np.zeros(rw, dtype=np.uint8)
        for dy in range(-3, 4):
            row_y = mid_y + dy
            if 0 <= row_y < rh:
                edge_band = np.maximum(edge_band, edges[row_y, :])

        # Find the contiguous edge run containing the Hough line,
        # bridging small gaps (≤30px) but not jumping to distant stray edges.
        hough_mid = (min(lx1, lx2) + max(lx1, lx2)) // 2
        max_gap = 30
        edge_binary = (edge_band > 0).astype(np.uint8)
        # Dilate to bridge small gaps
        kern_bridge = np.ones((1, max_gap), dtype=np.uint8)
        bridged = cv2.dilate(edge_binary.reshape(1, -1),
                             kern_bridge).flatten()

        if hough_mid < len(bridged) and bridged[hough_mid]:
            # Scan left/right from Hough midpoint within bridged region
            scan_x1 = hough_mid
            while scan_x1 > 0 and bridged[scan_x1 - 1]:
                scan_x1 -= 1
            scan_x2 = hough_mid
            while scan_x2 < rw - 1 and bridged[scan_x2 + 1]:
                scan_x2 += 1
        else:
            # Fallback to Hough endpoints
            scan_x1 = min(lx1, lx2)
            scan_x2 = max(lx1, lx2)

        # Sanity check: if detected line is too narrow compared to the
        # uniform region, it's a partial detection. Expand symmetrically
        # from the Hough midpoint to ~60% of the uniform region width.
        detected_width = scan_x2 - scan_x1
        if detected_width < rw * 0.5:
            expected_half = int(rw * 0.30)
            print(f"  WARNING: ground line too narrow ({detected_width}px"
                  f" vs region {rw}px), expanding from Hough midpoint")
            scan_x1 = max(0, hough_mid - expected_half)
            scan_x2 = min(rw, hough_mid + expected_half)

        ground_y = ry + mid_y
        ground_x1 = rx + scan_x1
        ground_x2 = rx + scan_x2
        line_width = ground_x2 - ground_x1
        print(f"  Ground line: y={ground_y} x={ground_x1}..{ground_x2}"
              f" width={line_width}")

        # ROI relative to ground line. The Chrome Dino game has fixed
        # proportions: score is ~35% of game width above ground line,
        # dino starts ~10% left of ground line start.
        # These ratios are intrinsic to the game, not camera-dependent.
        # Keep tight to exclude browser chrome above the game area.
        game_height = int(line_width * 0.40)
        pad_below = 15
        pad_left = int(line_width * 0.12)
        pad_right = int(line_width * 0.05)  # score is within ground line extent

        roi_x1 = max(0, ground_x1 - pad_left)
        roi_y1 = max(0, ground_y - game_height)
        roi_x2 = min(w, ground_x2 + pad_right)
        roi_y2 = min(h, ground_y + pad_below)
    else:
        # Fallback: use the full uniform region
        print("  WARNING: No ground line found, using full uniform region")
        roi_x1 = rx
        roi_y1 = ry
        roi_x2 = rx + rw
        roi_y2 = ry + rh

    # Draw debug image
    debug = frame_bgr.copy()
    cv2.drawContours(debug, contours, -1, (0, 255, 0), 1)
    cv2.rectangle(debug, (roi_x1, roi_y1), (roi_x2, roi_y2), (255, 0, 0), 2)
    cv2.imwrite(os.path.join(outdir, "auto_roi_debug.png"), debug)

    print(f"  ROI detected: x1={roi_x1} y1={roi_y1} x2={roi_x2} y2={roi_y2}")
    print(f"  ROI size: {roi_x2 - roi_x1}x{roi_y2 - roi_y1}")
    print(f"  Debug image: {os.path.join(outdir, 'auto_roi_debug.png')}")

    cfg.set_roi(roi_x1, roi_y1, roi_x2, roi_y2)
    print(f"  Updated configs/game.ini with new ROI")
    print(f"  Run 'sudo python3 src/main.py' to start playing")


def guided_roi(cfg):
    """Guided ROI detection using a white Notepad window as reference.

    The user places a Notepad window (white background) sized to match
    the game's baseline width. The camera detects this bright white
    rectangle and uses it to calculate the game ROI.

    Steps:
    1. User opens Notepad, resizes it to match the game's ground line width
    2. User runs: sudo python3 src/main.py --guided-roi
    3. Camera detects the white rectangle
    4. Top edge of rectangle = ground line y, width = game width
    5. ROI is calculated from game proportions
    """
    import cv2
    import numpy as np
    from camera import create_camera

    print("gameplayer-bot: guided ROI detection")
    print("Make sure a white Notepad window is visible, sized to the game baseline.")
    print(f"Camera: {cfg.camera_type} {cfg.camera_width}x{cfg.camera_height}")

    cam = create_camera(cfg.camera_type, cfg.camera_width, cfg.camera_height,
                         cfg.camera_fps, cfg.camera_device)
    cam.start()
    print("Waiting for camera to stabilize...")
    time.sleep(2)
    for _ in range(10):
        frame = cam.capture()
    cam.stop()

    outdir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "tests", "sample_frames"
    )
    os.makedirs(outdir, exist_ok=True)

    frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
    cv2.imwrite(os.path.join(outdir, "guided_roi_input.png"), frame_bgr)

    gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
    h, w = gray.shape

    # Step 1: Threshold for bright white pixels (Notepad background).
    # White paper/notepad has brightness > 200 in camera image.
    _, white_mask = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)

    # Clean up noise with morphological open/close
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    white_mask = cv2.morphologyEx(white_mask, cv2.MORPH_OPEN, kernel)
    white_mask = cv2.morphologyEx(white_mask, cv2.MORPH_CLOSE, kernel)

    cv2.imwrite(os.path.join(outdir, "guided_roi_mask.png"), white_mask)

    # Step 2: Find contours — the largest white rectangle is the Notepad
    contours, _ = cv2.findContours(white_mask, cv2.RETR_EXTERNAL,
                                    cv2.CHAIN_APPROX_SIMPLE)

    if not contours:
        print("ERROR: No white rectangle found. Is Notepad visible?")
        print(f"  Input: {os.path.join(outdir, 'guided_roi_input.png')}")
        print(f"  Mask: {os.path.join(outdir, 'guided_roi_mask.png')}")
        return

    # Find the largest rectangle-like contour
    best = None
    best_area = 0
    for c in contours:
        rx, ry, rw, rh = cv2.boundingRect(c)
        area = rw * rh
        aspect = rw / max(rh, 1)
        # Must be wider than tall, reasonably sized
        if rw < 60 or rh < 20 or aspect < 1.5:
            continue
        print(f"    white region: x={rx} y={ry} w={rw} h={rh}"
              f" aspect={aspect:.1f} area={area}")
        if area > best_area:
            best_area = area
            best = (rx, ry, rw, rh)

    if best is None:
        print("ERROR: No suitable white rectangle found.")
        print(f"  Input: {os.path.join(outdir, 'guided_roi_input.png')}")
        print(f"  Mask: {os.path.join(outdir, 'guided_roi_mask.png')}")
        return

    rx, ry, rw, rh = best
    print(f"  Notepad detected: x={rx} y={ry} w={rw} h={rh}")

    # Step 3: The Notepad's top edge = game ground line y position.
    # The Notepad's width = game baseline width.
    ground_y = ry           # top edge of Notepad = ground line
    ground_x1 = rx          # left edge
    ground_x2 = rx + rw     # right edge
    line_width = rw

    print(f"  Ground line: y={ground_y} x={ground_x1}..{ground_x2}"
          f" width={line_width}")

    # Step 4: Build ROI from game proportions (same as auto_roi).
    game_height = int(line_width * 0.40)
    pad_below = 15
    pad_left = int(line_width * 0.12)
    pad_right = int(line_width * 0.05)

    roi_x1 = max(0, ground_x1 - pad_left)
    roi_y1 = max(0, ground_y - game_height)
    roi_x2 = min(w, ground_x2 + pad_right)
    roi_y2 = min(h, ground_y + pad_below)

    # Draw debug image
    debug = frame_bgr.copy()
    # Green: detected Notepad
    cv2.rectangle(debug, (rx, ry), (rx + rw, ry + rh), (0, 255, 0), 2)
    # Blue: calculated ROI
    cv2.rectangle(debug, (roi_x1, roi_y1), (roi_x2, roi_y2), (255, 0, 0), 2)
    # Red line: ground line
    cv2.line(debug, (ground_x1, ground_y), (ground_x2, ground_y), (0, 0, 255), 2)
    cv2.imwrite(os.path.join(outdir, "guided_roi_debug.png"), debug)

    print(f"  ROI detected: x1={roi_x1} y1={roi_y1} x2={roi_x2} y2={roi_y2}")
    print(f"  ROI size: {roi_x2 - roi_x1}x{roi_y2 - roi_y1}")
    print(f"  Debug image: {os.path.join(outdir, 'guided_roi_debug.png')}")

    cfg.set_roi(roi_x1, roi_y1, roi_x2, roi_y2)
    print(f"  Updated configs/game.ini with new ROI")
    print(f"  Now close Notepad, start the game, and run: sudo python3 src/main.py")


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
                    sc = getattr(plugin, '_debug_scene_change', False)
                    mr = getattr(plugin, '_debug_motion_ratio', 0)
                    pk_lo = getattr(plugin, '_peak_lower', 0)
                    pk_up = getattr(plugin, '_peak_upper', 0)
                    pk_mr = getattr(plugin, '_peak_mr', 0)
                    pk_spd = getattr(plugin, '_peak_speed', 0)
                    spd = getattr(plugin, '_debug_speed', 0)
                    jx = getattr(plugin, '_debug_jx_pct', 0)
                    dbg = (f" lo={plugin._debug_lower:.0%}"
                           f" cy={plugin._debug_upper:.0%}"
                           f" spd={spd:.1f} pk_spd={pk_spd:.1f}"
                           f" jx={jx:.0%}"
                           f" pk_lo={pk_lo:.0%} pk_fd={pk_up:.1%}"
                           f" bg={state.get('bg_brightness', 0):.0f}"
                           f" pk_mr={pk_mr:.2f}{'!SC' if sc else ''}")
                    # Reset peaks for next interval
                    plugin._peak_lower = 0
                    plugin._peak_upper = 0
                    plugin._peak_mr = 0.0
                    plugin._peak_speed = 0.0
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
    parser.add_argument("--camera", choices=["auto", "csi", "usb", "dummy"],
                        help="Override camera type from config")
    parser.add_argument("--auto-roi", action="store_true",
                        help="Auto-detect Chrome Dino game area (ground line)")
    parser.add_argument("--guided-roi", action="store_true",
                        help="Detect ROI using a white Notepad window as guide")
    args = parser.parse_args()

    if args.test_hid:
        test_hid()
        return

    cfg = Config(args.config)
    if args.camera:
        cfg.camera_type = args.camera

    if args.auto_roi:
        auto_roi(cfg)
        return

    if args.guided_roi:
        guided_roi(cfg)
        return

    if args.calibrate:
        calibrate(cfg)
        return

    run(cfg)


if __name__ == "__main__":
    main()
