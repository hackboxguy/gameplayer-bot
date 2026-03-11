# gameplayer-bot - Design Plan

## Overview

A Raspberry Pi with a CSI camera that watches a monitor, detects game state
using computer vision, and injects keyboard/mouse input via USB HID gadget
mode. The host PC sees only a standard USB keyboard+mouse plugging in.
No host software, no browser extension — just a camera watching a screen and
a USB cable.

This is the evolution of the ATtiny85 Chrome Dino player (V1), replacing
LDR sensors with a camera and simple CV, enabling:
- Day/night mode handling (V1's main limitation)
- Support for multiple games via swappable game plugins
- Mouse emulation for paddle/pointer-based games

## Target Hardware

### Development: Raspberry Pi 4 + USB-C Splitter

For initial development, using a Pi 4 with a USB-C power/data splitter board.
The Pi 4's USB-C port supports gadget mode (dwc2 overlay), and the splitter
allows simultaneous power injection and USB data to the host PC.

```
  Monitor
  ┌──────────────────────────────┐
  │        Game on Screen        │
  │                              │
  │   ┌──────────────────────┐   │
  │   │  Camera's FOV        │   │
  │   │  (game area)         │   │
  │   └──────────────────────┘   │
  └──────────────────────────────┘
              │ CSI ribbon
        ┌─────▼──────────┐
        │  Raspberry Pi 4│
        │                │
        │  Python + CV   │
        │  USB Gadget    │
        └───────┬────────┘
                │ USB-C (via splitter board)
                ├──► Power supply (5V/3A)
                └──► Host PC (HID data)
```

### Production: Raspberry Pi Zero 2W (Single Cable)

For the final compact build, the Pi Zero 2W's micro-USB OTG port serves
double duty (power + HID data) from a single USB cable to the host PC.
The CSI camera connects via ribbon cable — no USB port consumed.

### Bill of Materials

| Component | Est. Cost | Notes |
|---|---|---|
| Raspberry Pi Zero 2W (or Pi 4 for dev) | ~$15 / ~$55 | USB gadget mode via dwc2 |
| Raspberry Pi Camera Module (v2 or v3) | ~$25 | CSI ribbon cable |
| USB-C splitter board (Pi 4 only) | ~$5 | Power inject + data passthrough |
| Micro-USB / USB-C cable | ~$2 | Data+power to host PC |
| Camera mount / clip | ~$3 | Aim camera at monitor |
| SD card (8GB+) | ~$5 | Raspberry Pi OS Bookworm Lite |

### Power Budget (Pi Zero 2W single-cable mode)

| Component | Current Draw | Notes |
|---|---|---|
| Pi Zero 2W idle | ~120mA | Bookworm Lite, no desktop |
| Pi Zero 2W under CV load | ~300-400mA | OpenCV on small ROI |
| CSI Camera Module | ~200-250mA | Active video capture |
| **Total estimated** | **~500-650mA** | |

| USB Port Type | Available | Margin |
|---|---|---|
| USB 2.0 | 500mA | Tight — may brownout under load |
| USB 3.0 | 900mA | Comfortable margin |
| USB-C (modern PCs) | 500-1500mA | Safe |

**Recommendation**: Use a USB 3.0 or USB-C port on the host PC. If USB 2.0
is the only option, disable WiFi/Bluetooth and reduce camera resolution to
lower power draw, or use a powered USB hub.

Note: Pi 4 with the splitter board has separate power, so no power budget
concerns during development.

## OS Setup

### Raspberry Pi OS Bookworm Lite

#### Why Lite (no desktop)?
- Lower idle power (~120mA vs ~200mA+ with desktop)
- Faster boot time (~10-15s vs ~30s+)
- No GPU memory wasted on desktop compositor
- Headless operation — no monitor needed on the Pi itself

#### Image Preparation (Raspberry Pi Imager)

1. Select **Raspberry Pi OS Lite (64-bit)** — Bookworm
2. Press **Ctrl+Shift+X** to open advanced settings:
   - Hostname: `gameplayer-bot`
   - Enable SSH: yes (password authentication)
   - Username: `pi`
   - Password: `brb0x`
   - Configure WiFi: yes (for initial SSH access)
3. Flash to SD card, boot the Pi

#### First Login

```bash
ssh pi@gameplayer-bot.local
# password: brb0x
```

### Deployment

```bash
# Clone the repo
cd /home/pi
git clone https://github.com/hackboxguy/gameplayer-bot.git
cd gameplayer-bot

# Install everything (dependencies, configs, systemd units)
sudo ./setup.sh

# Or install with auto-start on boot
sudo ./setup.sh --autostart
```

## setup.sh Behavior

The setup script lives at the repo root: `/home/pi/gameplayer-bot/setup.sh`

It is **idempotent** — safe to re-run after pulling new code.

### What `sudo ./setup.sh` Does

1. **Install system dependencies**:
   ```bash
   apt install -y --no-install-recommends \
       python3-opencv python3-picamera2 python3-numpy python3-libcamera \
       triggerhappy
   ```

2. **Configure boot for USB gadget mode** (if not already done):
   - Add `dtoverlay=dwc2,dr_mode=peripheral` under the `[all]` section in
     `/boot/firmware/config.txt` (must be under `[all]`, not board-specific
     sections like `[cm4]` or `[cm5]`)
   - Add `dwc2` and `libcomposite` to `/etc/modules` (kernel module loading
     at boot — `modules-load=` in cmdline.txt does NOT work on Bookworm)

3. **Install gadget setup script**:
   - Copy `configs/setup-gadget.sh` → `/usr/local/bin/gameplayer-bot-gadget.sh`
   - Install `configs/gameplayer-bot-gadget.service` → `/etc/systemd/system/`
   - **Always enable** the gadget service (HID device must exist for the
     game player to work)

4. **Install game player service**:
   - Install `configs/gameplayer-bot.service` → `/etc/systemd/system/`
   - Service runs: `/usr/bin/python3 <repo>/src/main.py --boot --camera csi`
   - **Do NOT enable by default** (user must manually start during dev)

5. **Install hotkey support** (trigger-happy):
   - Save repo path to `/etc/gameplayer-bot.env` (sourced by scripts at runtime)
   - Make `scripts/gp-calibrate.sh`, `gp-start.sh`, `gp-stop.sh` executable
   - Generate `/etc/triggerhappy/triggers.d/gameplayer-bot.conf` from
     `configs/gameplayer-bot.triggers` template (substitutes `__REPO_DIR__`)
   - Install systemd drop-in override for triggerhappy to run as root
     (needed for LED control and HID access)
   - Enable and restart `triggerhappy.service`

6. **Print status and next steps**

### With `--autostart` Flag

Same as above, plus:
- `systemctl enable gameplayer-bot.service` (starts game player on boot)

### Hotkey Operation (3-Key USB Keyboard)

For headless operation without SSH, a 3-key USB mini keyboard can control the
bot via trigger-happy (thd):

| Key | Action | Script |
|---|---|---|
| KEY_1 | Guided ROI calibration (LED blinks) | `scripts/gp-calibrate.sh` |
| KEY_2 | Start/restart game player | `scripts/gp-start.sh` |
| KEY_3 | Stop game player + cleanup | `scripts/gp-stop.sh` |

**Typical workflow**:
1. Place white Notepad window over game baseline on host PC
2. Press KEY_1 → Pi blinks green LED during calibration
3. Remove Notepad, open Chrome Dino game
4. Press KEY_2 → Pi sends spacebar + starts playing
5. After game-over, press KEY_2 again → kills old process + restarts fresh
6. Press KEY_3 → stops everything, restores LED

Scripts source `/etc/gameplayer-bot.env` for the repo path, so the deployment
works regardless of where the repo is cloned.

### Manual Service Control

```bash
# Start game player manually
sudo systemctl start gameplayer-bot

# Stop game player
sudo systemctl stop gameplayer-bot

# Check status / logs
sudo systemctl status gameplayer-bot
journalctl -u gameplayer-bot -f

# Enable auto-start later
sudo systemctl enable gameplayer-bot

# Disable auto-start
sudo systemctl disable gameplayer-bot
```

## Software Stack

```
┌─────────────────────────────────────────────┐
│  Game Plugin (Python)                       │
│  ├── detect(frame) → game state             │  Game-specific CV logic
│  ├── decide(state) → action                 │  Game-specific decision
│  └── get_hid_report(action) → bytes         │  HID report for keystroke/mouse
├─────────────────────────────────────────────┤
│  gameplayer-bot Core (Python)               │
│  ├── Camera capture (picamera2)             │  CSI camera via libcamera
│  ├── Frame pipeline (OpenCV)                │  Crop, resize, threshold
│  ├── HID Keyboard  (/dev/hidg0)            │  USB gadget keyboard reports
│  └── HID Mouse     (/dev/hidg1)            │  USB gadget mouse reports
├─────────────────────────────────────────────┤
│  USB Gadget Layer (Linux configfs)          │
│  ├── dwc2 overlay                           │  OTG controller driver
│  ├── libcomposite module                    │  Composite gadget framework
│  ├── HID function 0 (keyboard)             │  Boot keyboard, 8-byte report
│  └── HID function 1 (mouse)                │  3-button + dx/dy + wheel
├─────────────────────────────────────────────┤
│  Raspberry Pi OS Bookworm Lite              │
│  ├── libcamera + picamera2                  │  Camera stack
│  ├── Python 3.11+ / OpenCV                  │  CV processing
│  └── systemd services                       │  gameplayer-bot-gadget + gameplayer-bot
└─────────────────────────────────────────────┘
```

## USB HID Composite Gadget

### Boot Configuration

`/boot/firmware/config.txt` — add under the `[all]` section:
```ini
[all]
dtoverlay=dwc2,dr_mode=peripheral
```

**Important**: The dtoverlay must be under `[all]`, not under board-specific
sections like `[cm4]` or `[cm5]`. The `dr_mode=peripheral` forces the USB-C
port into device/gadget mode (required for HID output to host PC).

`/etc/modules` — add these two modules:
```
dwc2
libcomposite
```

**Note**: Do NOT use `modules-load=` in `cmdline.txt` — it does not work on
Bookworm. Use `/etc/modules` instead.

### Gadget Configuration Script

`configs/setup-gadget.sh` — run at boot via systemd to create a composite
HID device (keyboard + mouse):

```bash
#!/bin/bash
# gameplayer-bot USB HID composite gadget setup
# Installed to /usr/local/bin/gameplayer-bot-gadget.sh by setup.sh

GADGET_DIR=/sys/kernel/config/usb_gadget/gameplayer-bot

# Check if already configured AND bound to UDC
if [ -d "$GADGET_DIR" ]; then
    if [ -n "$(cat "$GADGET_DIR/UDC" 2>/dev/null)" ]; then
        exit 0  # already configured and bound
    fi
    # Directory exists but not bound — clean up and reconfigure
    rm -rf "$GADGET_DIR"
fi

# Create gadget
mkdir -p $GADGET_DIR
cd $GADGET_DIR

# Device descriptor
echo 0x1d6b > idVendor   # Linux Foundation
echo 0x0104 > idProduct   # Multifunction Composite Gadget
echo 0x0100 > bcdDevice
echo 0x0200 > bcdUSB

# Device strings
mkdir -p strings/0x409
echo "gameplayer-bot-01" > strings/0x409/serialnumber
echo "gameplayer-bot"    > strings/0x409/manufacturer
echo "gameplayer-bot"    > strings/0x409/product

# --- HID Keyboard Function ---
mkdir -p functions/hid.keyboard
echo 1 > functions/hid.keyboard/protocol    # 1 = keyboard
echo 1 > functions/hid.keyboard/subclass    # 1 = boot interface
echo 8 > functions/hid.keyboard/report_length

# Standard boot keyboard report descriptor
echo -ne '\x05\x01\x09\x06\xa1\x01\x05\x07\x19\xe0\x29\xe7\x15\x00\x25\x01\x75\x01\x95\x08\x81\x02\x95\x01\x75\x08\x81\x01\x95\x05\x75\x01\x05\x08\x19\x01\x29\x05\x91\x02\x95\x01\x75\x03\x91\x01\x95\x06\x75\x08\x15\x00\x25\x65\x05\x07\x19\x00\x29\x65\x81\x00\xc0' \
    > functions/hid.keyboard/report_desc

# --- HID Mouse Function ---
mkdir -p functions/hid.mouse
echo 2 > functions/hid.mouse/protocol      # 2 = mouse
echo 1 > functions/hid.mouse/subclass      # 1 = boot interface
echo 4 > functions/hid.mouse/report_length

# Boot mouse report descriptor: 3 buttons + dx + dy (relative)
echo -ne '\x05\x01\x09\x02\xa1\x01\x09\x01\xa1\x00\x05\x09\x19\x01\x29\x03\x15\x00\x25\x01\x75\x01\x95\x03\x81\x02\x75\x05\x95\x01\x81\x01\x05\x01\x09\x30\x09\x31\x15\x81\x25\x7f\x75\x08\x95\x02\x81\x06\xc0\xc0' \
    > functions/hid.mouse/report_desc

# --- Configuration ---
mkdir -p configs/c.1/strings/0x409
echo "gameplayer-bot Config" > configs/c.1/strings/0x409/configuration
echo 250 > configs/c.1/MaxPower  # 250 x 2mA = 500mA

# Link functions to configuration
ln -s functions/hid.keyboard configs/c.1/
ln -s functions/hid.mouse    configs/c.1/

# Bind to UDC (USB Device Controller)
ls /sys/class/udc > UDC
```

### Systemd Services

`configs/gameplayer-bot-gadget.service`:
```ini
[Unit]
Description=gameplayer-bot USB HID Gadget Setup
After=sysinit.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/gameplayer-bot-gadget.sh
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
```

`configs/gameplayer-bot.service`:
```ini
[Unit]
Description=gameplayer-bot Game Player
After=gameplayer-bot-gadget.service
Requires=gameplayer-bot-gadget.service

[Service]
Type=simple
User=root
ExecStart=/usr/bin/python3 /home/pi/gameplayer-bot/src/main.py --boot --camera csi
WorkingDirectory=/home/pi/gameplayer-bot
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### HID Report Formats

**Keyboard** (`/dev/hidg0`, 8 bytes):
```
Byte 0: Modifier keys (Ctrl, Shift, Alt, GUI)
Byte 1: Reserved (0x00)
Byte 2: Key code 1
Byte 3: Key code 2
Byte 4: Key code 3
Byte 5: Key code 4
Byte 6: Key code 5
Byte 7: Key code 6
```

**Mouse** (`/dev/hidg1`, 4 bytes):
```
Byte 0: Buttons (bit0=left, bit1=right, bit2=middle)
Byte 1: X movement (-127 to +127, relative)
Byte 2: Y movement (-127 to +127, relative)
Byte 3: Wheel (unused, 0x00)
```

## Camera Capture Pipeline

### picamera2 on Bookworm

Bookworm uses libcamera (not legacy raspistill). The `picamera2` Python
library provides a clean API:

```python
from picamera2 import Picamera2

camera = Picamera2()
config = camera.create_video_configuration(
    main={"size": (640, 480), "format": "RGB888"},
    controls={"FrameRate": 60}
)
camera.configure(config)
camera.start()

while True:
    frame = camera.capture_array()  # numpy array, ~16ms at 60fps
    # ... CV processing ...
```

### Frame Pipeline

```
Full frame (640x480) → Crop to game ROI → CV processing → Action
        ~16ms (60fps)      <1ms              ~2ms          <1ms
                                                    Total: ~20ms
```

The game ROI (Region of Interest) is a small rectangle containing just the
game area. Three detection modes:
- `--guided-roi`: User places a white Notepad window sized to match the game
  baseline. Camera detects the white rectangle, uses its top edge as ground
  line and width as game width. Most reliable method.
- `--auto-roi`: Automatically finds game area via uniformity mask + ground
  line detection. Works across different camera placements.
- Manual config: Edit `configs/game.ini` [roi] section directly.

## Game Plugin Architecture

Each game is a Python module in `src/plugins/` implementing a simple interface:

```python
class GamePlugin:
    """Base class for game plugins."""

    name: str = "unnamed"
    hid_type: str = "keyboard"  # "keyboard", "mouse", or "both"

    def calibrate(self, frame):
        """One-time setup: find game area, detect theme, etc."""
        pass

    def detect(self, frame) -> dict:
        """Process frame, return game state."""
        raise NotImplementedError

    def decide(self, state) -> dict:
        """Given game state, decide what action to take."""
        raise NotImplementedError

    def get_hid_report(self, action) -> bytes:
        """Convert action to raw HID report bytes."""
        raise NotImplementedError
```

### Plugin: Chrome Dino (Implemented)

Uses **frame differencing** instead of static thresholding. This was a key
lesson learned — static thresholding on camera images is unreliable because:
- Ground line, score text, and dino body are always bright in night mode
- Camera noise and auto-exposure changes cause false triggers
- Otsu's method is unstable on unimodal (obstacle-free) frames

Frame differencing (`cv2.absdiff(current, previous)`) naturally cancels all
static elements. Only moving objects (scrolling obstacles) produce signal.

#### Detection Architecture

The plugin uses **density-based detection** (fraction of pixels with motion)
rather than raw pixel counts. This makes detection independent of ROI size.

**Speed measurement** — `cv2.phaseCorrelate` on the ground texture strip
measures horizontal scroll speed in px/frame. Uses a **one-way ratchet**:
speed only increases during a run (Chrome Dino never slows down), resets
to 0 on scene change (game-over). This prevents speed drops when obstacles
corrupt the ground strip measurement.

**Adaptive scan strips** — The jump strip position shifts further ahead at
higher speeds (27% at game start → 40% at max speed), giving more lead time
for faster obstacles. Jump strip width is constant at 6%.

**Obstacle classification** — Uses vertical centroid of motion in a wide
strip (20-45% x-range) to distinguish cactuses from pterodactyls:
- Cactuses: centroid ~81-87% (rooted to ground)
- Low pterodactyls: centroid ~55-65% (jumped, not ducked)
- Medium/high pterodactyls: centroid <50% (ducked)
- Noise: centroid varies but density <2%

**Pterodactyl early-warning** — A `_ptero_suspect` counter tracks frames
with elevated motion (>0.5%) and high centroid (<70%). While active (up to
4 frames ≈ 130ms), jump triggers are suppressed to prevent jumping into an
approaching ptero. Safe because cactus centroid is 81-87%, never below 70%.

**Adaptive cooldown** — Cooldown between actions shortens at higher speeds
(350ms at start → 100ms at max speed) to handle closely-spaced obstacles.

**Scene change detection** — Suppresses all triggers when >15% of ROI
pixels change between frames (game-over/restart transitions). Resets speed
ratchet and ptero suspect counter.

#### Key Parameters

```python
JX_BASE = 0.27       # jump strip start at minimum speed
JX_MAX = 0.40        # jump strip start at maximum speed
JX_WIDTH = 0.06      # jump strip width (constant)
DX_START = 0.20      # duck strip start (fixed, wide)
DX_END = 0.45        # duck strip end (fixed, wide)
DY_END = 0.40        # duck zone vertical limit (top 40% of ROI only)
# Speed thresholds defined at 30fps reference, auto-scaled for other fps:
SPEED_MIN_30 = 2.0   # px/frame at game start (30fps reference)
SPEED_MAX_30 = 20.0  # px/frame at high speed (30fps reference)
# At 60fps: SPEED_MIN=1.0, SPEED_MAX=10.0 (scaled by 30/fps)
COOLDOWN_MIN_MS = 100 # minimum cooldown at max speed
COOLDOWN_MAX_MS = 350 # maximum cooldown at min speed
JUMP_DENSITY = 0.08  # 8% of scan pixels must have motion
PTERO_MIN_DENSITY = 0.02  # 2% for confirmed ptero
PTERO_CENTROID = 0.50     # centroid < 50% = duck (medium/high ptero)
PTERO_EARLY_CENTROID = 0.55  # early-warning: < 55% = suspect ptero
```

#### Known Failure Modes

- **Night-to-day transition with obstacle present**: The brightness change
  triggers scene_change detection (motion_ratio > 0.15), which suppresses
  all triggers. If an obstacle is present during the transition, it gets
  missed. Transitions without obstacles work fine.
- **Very high-flying pterodactyl**: Ptero at the very top of the ROI may
  not accumulate enough density in the wide strip for confirmed detection.

### Plugin: Breakout / Pong (Paddle Game)

```python
class BreakoutPlugin(GamePlugin):
    name = "breakout"
    hid_type = "mouse"

    def detect(self, frame):
        roi = frame[y1:y2, x1:x2]
        hsv = cv2.cvtColor(roi, cv2.COLOR_RGB2HSV)

        mask = cv2.inRange(hsv, ball_lower, ball_upper)
        contours, _ = cv2.findContours(mask, ...)
        if contours:
            ball = max(contours, key=cv2.contourArea)
            M = cv2.moments(ball)
            bx = int(M["m10"] / M["m00"])
            by = int(M["m01"] / M["m00"])
            return {"ball_x": bx, "ball_y": by, "found": True}
        return {"found": False}

    def decide(self, state):
        if not state["found"]:
            return {"dx": 0}
        dx = state["ball_x"] - self.last_paddle_x
        dx = max(-127, min(127, dx))
        return {"dx": dx}

    def get_hid_report(self, action):
        return mouse_report(dx=action["dx"], dy=0)
```

## Configuration

### `configs/game.ini`

```ini
[general]
# Which game plugin to load: chrome-dino, breakout
plugin = chrome-dino

# Camera type: auto, csi, usb, dummy
camera_type = auto

# USB camera device index (only used when camera_type=usb or auto fallback)
camera_device = 0

# Camera resolution and framerate
camera_width = 640
camera_height = 480
camera_fps = 60

[roi]
# Game area coordinates in camera frame (pixels)
# Set these after mounting the camera and aiming at the monitor.
# Use: python3 src/main.py --calibrate to capture a frame and check coords.
x1 = 140
y1 = 130
x2 = 530
y2 = 210

[chrome-dino]
# Pixel sum threshold to consider an obstacle detected in a zone
# Higher values = less sensitive (fewer false jumps from camera noise)
# Scale this up if the ROI is larger (more pixels in scan zone)
trigger_threshold = 300
# Pixel sum threshold for pterodactyl detection in upper zone
# Lower than trigger_threshold because ptero motion is smaller
duck_threshold = 90
# Cooldown between actions (ms) — must be long enough to avoid
# re-jumping on the same obstacle as it scrolls through
cooldown_ms = 350

[breakout]
# Ball color range in HSV (tune for your specific game)
ball_h_min = 0
ball_h_max = 180
ball_s_min = 50
ball_s_max = 255
ball_v_min = 50
ball_v_max = 255
```

## Project Structure

```
gameplayer-bot/
├── setup.sh                          Setup script (run as sudo)
├── PLAN.md                           This file
├── README.md                         Project overview
├── LICENSE
├── configs/
│   ├── game.ini                      Game plugin + ROI + tuning config
│   ├── setup-gadget.sh               USB HID composite gadget script
│   ├── gameplayer-bot-gadget.service  systemd: create HID gadget at boot
│   ├── gameplayer-bot.service         systemd: run game player
│   └── gameplayer-bot.triggers       trigger-happy hotkey template
├── scripts/
│   ├── gp-calibrate.sh              KEY_1: guided ROI calibration (LED blinks)
│   ├── gp-start.sh                  KEY_2: start/restart game player
│   └── gp-stop.sh                   KEY_3: stop game player + cleanup
├── src/
│   ├── main.py                       Entry point (main game loop)
│   ├── camera.py                     picamera2 wrapper
│   ├── hid.py                        HID keyboard/mouse report helpers
│   ├── config.py                     Config file loader (game.ini)
│   └── plugins/
│       ├── __init__.py
│       ├── base.py                   GamePlugin base class
│       ├── chrome_dino.py            Chrome Dino: jump/duck via keyboard
│       └── breakout.py               Breakout/Pong: paddle via mouse
└── tests/
    ├── test_hid.py                   Verify HID reports
    ├── test_plugins.py               Test detection with sample frames
    └── sample_frames/                Screenshots for offline testing
```

## Development Phases

### Phase 1: USB HID Gadget Foundation — COMPLETE
- Flash Bookworm Lite (hostname: gameplayer-bot, user: pi)
- Write `setup.sh` and gadget config scripts
- Write Python HID helpers (`src/hid.py`)
- Test: Pi 4 sends spacebar presses to host PC via USB-C gadget
- Deliverable: `sudo systemctl start gameplayer-bot` sends test keystrokes
- **Result**: Working. Host PC (Ubuntu) sees keyboard + mouse via `evtest`.

### Phase 2: Camera + Chrome Dino (Keyboard Game) — COMPLETE
- Camera capture with auto-detection (`src/camera.py`)
- Manual ROI config via `configs/game.ini`
- Chrome Dino plugin: frame differencing obstacle detection
- Jump/duck via keyboard HID
- CSI camera support (ov5647) — 60fps at 640×480
- FPS-adaptive speed constants (30fps reference, auto-scaled)
- Ptero centroid thresholds tuned (duck only for cy <50%)
- Hotkey control via 3-key USB keyboard (trigger-happy)
- Auto-start game via HID spacebar
- **Result**: Scores 800–2500 with CSI camera at 60fps.
  See "Current Status" section below for details.

### Phase 3: Breakout/Pong (Mouse Game)
- Ball tracking (color or contour-based)
- Mouse HID relative movement
- Paddle control via dx deltas
- Test: Plays a browser-based Breakout/Pong game
- Deliverable: Second game proving the platform is generic

### Phase 4: Polish — IN PROGRESS
- `--autostart` tested and working (boot mode with guided-roi + retries)
- Hotkey control via 3-key USB keyboard (trigger-happy) — DONE
- 60fps CSI camera with FPS-adaptive speed scaling — DONE
- Game selection via `configs/game.ini`
- Pi Zero 2W testing (single cable mode)
- Documentation and blog post

## Latency Analysis

### Theoretical (CSI Camera at 60fps)

| Stage | Duration | Cumulative |
|---|---|---|
| Frame capture (60fps) | 16ms | 16ms |
| ROI crop + resize | <1ms | 17ms |
| CV processing (blur + diff + threshold) | 3-5ms | 20-22ms |
| Decision logic | <1ms | 21-23ms |
| HID report write | <1ms | 22-24ms |
| USB poll interval (1ms for HID) | 0-1ms | 22-25ms |
| **Total pipeline latency** | **~22-25ms** | |

### Actual (CSI Camera — ov5647 at 60fps)

| Stage | Duration | Cumulative |
|---|---|---|
| Frame capture (60fps CSI via picamera2) | 16ms | 16ms |
| ROI crop | <1ms | 17ms |
| GaussianBlur + absdiff + threshold | ~2ms | 19ms |
| Decision + HID write | <1ms | 20ms |
| **Total pipeline latency** | **~16-20ms** | |

### Actual (USB Camera — Logitech Brio at 15fps)

| Stage | Duration | Cumulative |
|---|---|---|
| Frame capture (15fps Brio via V4L2) | 67ms | 67ms |
| ROI crop | <1ms | 68ms |
| GaussianBlur + absdiff + threshold | ~2ms | 70ms |
| Decision + HID write | <1ms | 71ms |
| **Total pipeline latency** | **~67-71ms** | |

The CSI camera at 60fps (~16ms per frame) cuts pipeline latency to ~20ms,
roughly 3.5x faster than the USB camera (15fps, ~67ms). This enables scores
of 800-2500 with the Chrome Dino plugin.

For mouse-based games (Breakout/Pong), continuous tracking means individual
frame latency matters less — small dx corrections every 16ms should produce
smooth paddle movement.

## Current Status & Results (March 2026)

### Chrome Dino — Working

The bot reliably plays Chrome Dino in both day and night modes, scoring
**800–2500** with CSI camera at 60fps. Key improvements:

- **60fps CSI camera** (ov5647): 60fps at 640×480 via picamera2/libcamera.
  ~16ms frame interval for faster obstacle detection. Also tested at 30fps
  with similar variance (both score 800-2500).
- **FPS-adaptive speed constants**: Speed thresholds defined at 30fps
  reference, automatically scaled by `30/fps` for any frame rate. Changing
  `camera_fps` in `game.ini` requires no code changes.
- **Guided ROI detection** (`--guided-roi`): User places a white Notepad
  window sized to match the game baseline. Camera detects the white
  rectangle and calculates ROI from game proportions. Most reliable method.
- **Auto-ROI detection** (`--auto-roi`): Automatically finds game area via
  uniformity mask + ground line detection. Works across different camera
  placements.
- **Density-based detection**: Uses fraction of pixels with motion instead
  of raw pixel counts. ROI-size-independent — works across different ROI
  sizes without threshold retuning.
- **Speed-adaptive scan strip**: Phase correlation measures scroll speed.
  Jump strip moves further ahead at higher speeds (27% → 40%). One-way
  speed ratchet prevents drops during obstacle corruption.
- **Centroid-based ptero detection**: Vertical centroid of motion
  distinguishes floating pterodactyls (centroid <50%) from grounded
  cactuses (centroid 81-87%). Low pteros (cy 55-65%) are jumped, not
  ducked. Only medium/high pteros (cy <50%) trigger duck.
- **Ptero early-warning suppression**: Tracks frames with elevated
  floating motion (centroid <55%) to suppress premature jumps before
  ptero is confirmed.
- **Adaptive cooldown**: 350ms at slow speed → 100ms at max speed for
  closely-spaced obstacles at high speed.
- **Day/night handling**: Works across day/night transitions when no
  obstacle is present during the brightness change.
- **Scene change suppression**: Prevents false triggers during game-over
  and restart transitions (>15% of ROI pixels changed = scene change).
- **Auto-start game**: Sends spacebar via HID before game loop begins,
  eliminating manual step on host PC.
- **Hotkey control**: 3-key USB keyboard for headless operation
  (KEY_1=calibrate, KEY_2=start/restart, KEY_3=stop). KEY_2 kills any
  existing game player and starts fresh, enabling restart after game-over.
- **Optional autoloop** (`--autoloop`): Game pause/over detection with
  auto speed reset. Disabled by default as it can cap scores (~700).

Main failure modes at higher scores:
- **Night-to-day transition with obstacle**: The brightness change during
  day/night mode switch triggers scene_change suppression, missing any
  obstacle present during the transition.
- **Very high-flying pterodactyl**: Ptero near the top of ROI may not
  accumulate enough density for confirmed detection.

### Detection Algorithm Evolution

Finding the right detection approach required 6+ iterations:

1. **Simple threshold** (bg+40): Failed — ground line, dino body, score text
   are all bright in night mode → constant false triggers
2. **Baseline subtraction**: Failed — camera auto-exposure hadn't stabilized
   when baseline was captured (bg=3 at startup vs bg=51 during play)
3. **Detection column**: Failed — ground texture produced 5000+ pixel noise
   even with margins excluded
4. **Otsu's threshold**: Failed — unstable on obstacle-free frames (unimodal
   histogram → random low threshold → noise spikes)
5. **Fixed high threshold (3000)**: Inverted behavior — Otsu gave lower
   thresholds when obstacles created bimodal histogram
6. **Frame differencing** (final): Works. `cv2.absdiff(current, previous)`
   cancels all static elements. Only scrolling obstacles produce signal.

Key insight: a camera watching a screen is fundamentally different from
reading pixels directly. Camera noise, auto-exposure, and screen refresh
artifacts make static thresholding unreliable. Frame differencing elegantly
sidesteps all these issues.

### Tuning Parameters (Current)

| Parameter | Value | Why |
|---|---|---|
| Jump strip | 27–40% adaptive + 6% width | Shifts right at higher speed for more lead time |
| Duck strip | 20–45% of ROI width | Wide strip for centroid-based ptero detection |
| Ground split | 50% of ROI height | Jump scan uses lower half only |
| Duck zone limit | Top 40% (DY_END) | Avoids scrolling ground features at 40-50% |
| Diff threshold | 30 brightness levels | Filters camera noise while catching obstacles |
| Jump density | 8% of scan pixels | ROI-size-independent; works in day and night modes |
| Ptero density | 2% of strip + centroid < 50% | Only medium/high pteros ducked; low pteros jumped |
| Ptero early-warning | 0.5% density + centroid < 55% | Suppresses premature jumps for up to 4 frames |
| Cooldown | 350ms (slow) → 100ms (fast) | Adaptive; shorter at high speed for close obstacles |
| Speed range | 2–20 px/frame (30fps ref) | Auto-scaled by 30/fps; at 60fps: 1–10 px/frame |
| Scene change | 15% of ROI pixels | Suppresses triggers during game-over/restart |

### Hardware Performance

- **CSI Camera**: RPi Camera Module v1 (ov5647) — 60fps at 640×480 (~62.5fps measured)
- **USB Camera**: Logitech Brio — 15fps (backup, used for initial development)
- **Resolution**: 640×480
- **Pipeline latency (CSI)**: ~20ms total (16ms capture + ~2ms CV)
- **Pipeline latency (USB)**: ~67–71ms total (dominated by frame capture interval)
- **CV processing**: ~2ms (GaussianBlur + absdiff + threshold on ~390×80 ROI)

## What to Explore Next

### Completed

- **CSI camera support** — RPi Camera Module v1 (ov5647) achieving 60fps
  via picamera2/libcamera (~62.5fps measured). ~4x faster than USB camera
  (15fps), enabling scores of 800-2500.

- **60fps support** — Camera runs at 60fps. Speed constants and autoloop
  thresholds are FPS-adaptive (defined at 30fps reference, scaled by
  `30/fps`). Changing `camera_fps` in `game.ini` requires no code changes.

- **Guided ROI detection** — `--guided-roi` uses a white Notepad window
  as a visual reference. User sizes the Notepad to match the game baseline.
  Camera detects the bright white rectangle and uses game-proportion ratios
  to calculate the ROI. Most reliable ROI detection method.

- **Auto-ROI detection** — `--auto-roi` automatically detects the game area.
  Uses uniformity mask to find the browser dark area, then Canny + Hough
  to locate the ground line as a vertical anchor. Edge scan finds the full
  ground line extent, and fixed game-proportion ratios build the ROI.
  Robust across different camera placements (tested with 8+ positions).

- **Density-based detection** — Fraction of pixels with motion instead of
  raw pixel counts. ROI-size-independent. JUMP_DENSITY=8%, PTERO_MIN=2%.

- **Speed-adaptive scan strip** — Phase correlation on ground texture
  measures scroll speed. Jump strip shifts from 27% (slow) to 40% (fast).
  One-way speed ratchet prevents drops mid-game. Resets on game-over.

- **Centroid-based ptero detection** — Vertical centroid distinguishes
  floating pterodactyls (centroid <50%) from grounded cactuses (81-87%).
  Low pteros (cy 55-65%) are jumped; only medium/high pteros (cy <50%)
  trigger duck. Replaced zone-based upper/lower approach.

- **Ptero early-warning suppression** — Tracks frames with elevated
  floating motion (>0.5%, centroid <55%) to suppress premature jumps
  for up to 4 frames before ptero is confirmed with full density.

- **Adaptive cooldown** — 350ms at game start, 100ms at max speed.
  Handles closely-spaced obstacles at high speed.

- **Scene change detection** — Suppresses all triggers when >15% of ROI
  pixels change between frames (game-over/restart transitions).

- **Auto-start game** — Sends spacebar via HID before game loop begins,
  so the Chrome Dino game starts automatically without manual input.

- **Hotkey control** — 3-key USB keyboard for headless operation via
  trigger-happy (thd). KEY_1=calibrate ROI (LED blinks), KEY_2=start/restart
  game player, KEY_3=stop. Scripts are repo-path-independent via
  `/etc/gameplayer-bot.env`.

- **Game pause/over detection** (`--autoloop`) — Tracks near-zero scroll
  speed frames to detect game pause/over and auto-reset. Optional flag
  because false triggers can cap scores (~700).

- **USB HID gadget fixes** — Removed conflicting `dr_mode=host` overlays
  from `config.txt`. Gadget script now checks UDC binding, not just
  directory existence, and reconfigures if not properly bound.

### High Priority

1. **Night-to-day transition fix** — Scene change detection (motion_ratio
   > 0.15) suppresses all triggers during day/night brightness transitions.
   If an obstacle is present during the transition, it gets missed. Need to
   distinguish brightness-only transitions from actual game-over events.

### Medium Priority

3. **Breakout/Pong plugin** (Phase 3) — Ball tracking via color or contour
   detection. Mouse HID for paddle movement. Would prove the platform
   handles mouse-based games too.

4. **Pi Zero 2W testing** — Single-cable mode (power + HID via micro-USB).
   Need to verify power budget and CV performance on the weaker CPU.

### Low Priority

7. **Score OCR** — Read the score display to log performance and potentially
   adapt strategy based on game speed.

8. **Recording mode** — Save camera footage with detection overlays for
   debugging and demo videos.

9. **Web calibration UI** — Flask app served from the Pi for adjusting ROI
   and thresholds via a browser instead of editing `game.ini`.

## Known Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| USB 2.0 can't supply enough current (Pi Zero) | Brownout / reboot | USB 3.0 port; disable WiFi/BT; Pi 4 + splitter for dev |
| Pi 4 USB-C gadget mode quirks | HID not recognized | Verify dwc2 overlay; test with `lsusb` on host |
| Camera angle / perspective distortion | ROI misaligned | Tripod mount; careful `game.ini` ROI tuning |
| Ambient light / screen reflections | False triggers | Adaptive thresholding; hood over camera |
| picamera2 frame drop under load | Missed obstacles | Reduce resolution/fps in `game.ini` |
| Game-specific sprite changes | Plugin breaks | Keep plugins simple; threshold-based |

## Comparison: V1 (ATtiny85 + LDR) vs V2 (Pi + Camera)

| Aspect | V1 (ATtiny85) | V2 (gameplayer-bot) |
|---|---|---|
| Cost | ~$5 | ~$50 |
| Sensor | 2x LM393 LDR on monitor | CSI camera on tripod |
| Detection | Digital threshold (dark/light) | OpenCV (threshold + contour) |
| Day/night mode | Fails (workaround: DevTools) | Handled in CV (detect + adapt) |
| Games supported | Chrome Dino only | Any (plugin architecture) |
| HID output | Keyboard only | Keyboard + Mouse composite |
| Power | <100mA (USB bus powered) | ~500-650mA (needs USB 3.0+) |
| Setup | Mount sensors + tune pots | Mount camera + edit game.ini |
| Code | 2699 bytes C | Python + OpenCV |

## Future Ideas

- Web UI for calibration (Flask served from the Pi over WiFi)
- Record gameplay footage from the camera for debugging / demo videos
- Reinforcement learning plugin (train a small model to play via screen)
- Support for gamepad HID reports (joystick + buttons) for more game types
- HDMI capture via USB dongle instead of camera (eliminates perspective
  issues but adds cost and requires a USB hub)
- Power-saving measures automated in setup.sh (disable WiFi/BT/HDMI)
