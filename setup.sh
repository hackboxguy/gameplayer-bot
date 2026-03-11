#!/bin/bash
# gameplayer-bot setup script
#
# Installs dependencies, configures USB HID gadget, and installs systemd services.
# Run from the repo root: sudo ./setup.sh [--autostart]
#
# Without --autostart: gadget service enabled (creates /dev/hidg0 + /dev/hidg1),
#   but game player must be started manually: sudo systemctl start gameplayer-bot
#
# With --autostart: game player also starts automatically on boot.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
AUTOSTART=0

for arg in "$@"; do
    case "$arg" in
        --autostart) AUTOSTART=1 ;;
        *) echo "Unknown option: $arg"; echo "Usage: sudo ./setup.sh [--autostart]"; exit 1 ;;
    esac
done

# Must run as root
if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: This script must be run as root (sudo ./setup.sh)"
    exit 1
fi

echo "=== gameplayer-bot setup ==="
echo "Repo: $SCRIPT_DIR"
echo ""

# ---- 1. Install system dependencies ----
echo "[1/5] Installing system dependencies..."
apt-get update -qq
apt-get install -y --no-install-recommends \
    python3-opencv \
    python3-picamera2 \
    python3-numpy \
    python3-libcamera \
    triggerhappy
echo "  Done."

# ---- 2. Configure boot for USB gadget mode ----
echo "[2/5] Configuring USB gadget mode..."

CONFIG_TXT="/boot/firmware/config.txt"
MODULES_FILE="/etc/modules"

# Ensure dtoverlay=dwc2,dr_mode=peripheral is in [all] section.
# Remove any existing dwc2 host-mode overlays (e.g. dr_mode=host under [cm5])
# that conflict with gadget/peripheral mode.
sed -i '/^dtoverlay=dwc2,dr_mode=host/d' "$CONFIG_TXT"

# Check if peripheral-mode overlay already present anywhere
if ! grep -q "^dtoverlay=dwc2,dr_mode=peripheral" "$CONFIG_TXT" 2>/dev/null; then
    # Insert after [all] section header (create it if missing)
    if grep -q "^\[all\]" "$CONFIG_TXT"; then
        sed -i '/^\[all\]/a dtoverlay=dwc2,dr_mode=peripheral' "$CONFIG_TXT"
    else
        echo -e "\n[all]\ndtoverlay=dwc2,dr_mode=peripheral" >> "$CONFIG_TXT"
    fi
    echo "  Added dtoverlay=dwc2,dr_mode=peripheral to $CONFIG_TXT [all] section"
else
    echo "  dtoverlay=dwc2,dr_mode=peripheral already in $CONFIG_TXT"
fi

# Add dwc2 and libcomposite to /etc/modules (loaded at boot)
if ! grep -q "^dwc2" "$MODULES_FILE" 2>/dev/null; then
    echo "dwc2" >> "$MODULES_FILE"
    echo "  Added dwc2 to $MODULES_FILE"
else
    echo "  dwc2 already in $MODULES_FILE"
fi
if ! grep -q "^libcomposite" "$MODULES_FILE" 2>/dev/null; then
    echo "libcomposite" >> "$MODULES_FILE"
    echo "  Added libcomposite to $MODULES_FILE"
else
    echo "  libcomposite already in $MODULES_FILE"
fi

echo "  Done."

# ---- 3. Install gadget setup script and services ----
echo "[3/5] Installing services..."

# Gadget setup script
cp "$SCRIPT_DIR/configs/setup-gadget.sh" /usr/local/bin/gameplayer-bot-gadget.sh
chmod +x /usr/local/bin/gameplayer-bot-gadget.sh
echo "  Installed /usr/local/bin/gameplayer-bot-gadget.sh"

# Gadget systemd service (always enabled — HID device must exist)
cp "$SCRIPT_DIR/configs/gameplayer-bot-gadget.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable gameplayer-bot-gadget.service
echo "  Enabled gameplayer-bot-gadget.service"

# Game player systemd service
cp "$SCRIPT_DIR/configs/gameplayer-bot.service" /etc/systemd/system/
systemctl daemon-reload

if [ "$AUTOSTART" -eq 1 ]; then
    systemctl enable gameplayer-bot.service
    echo "  Enabled gameplayer-bot.service (auto-start on boot)"
else
    # Ensure it's not enabled if re-running without --autostart
    systemctl disable gameplayer-bot.service 2>/dev/null || true
    echo "  Installed gameplayer-bot.service (manual start only)"
fi

echo "  Done."

# ---- 4. Install hotkey support (trigger-happy) ----
echo "[4/5] Installing hotkey support..."

# Save repo path for scripts to source at runtime
echo "REPO_DIR=\"$SCRIPT_DIR\"" > /etc/gameplayer-bot.env
echo "  Created /etc/gameplayer-bot.env (REPO_DIR=$SCRIPT_DIR)"

# Make scripts executable
chmod +x "$SCRIPT_DIR/scripts/gp-calibrate.sh"
chmod +x "$SCRIPT_DIR/scripts/gp-start.sh"
chmod +x "$SCRIPT_DIR/scripts/gp-stop.sh"

# Generate triggers config with actual repo path
sed "s|__REPO_DIR__|$SCRIPT_DIR|g" \
    "$SCRIPT_DIR/configs/gameplayer-bot.triggers" \
    > /etc/triggerhappy/triggers.d/gameplayer-bot.conf
echo "  Installed trigger-happy config"

# Ensure triggerhappy runs as root (needed for LED control and HID access)
if [ -f /etc/default/triggerhappy ]; then
    sed -i 's/^DAEMON_OPTS=.*/DAEMON_OPTS="--daemon --triggers \/etc\/triggerhappy\/triggers.d\/ --user root"/' \
        /etc/default/triggerhappy
fi

systemctl enable triggerhappy.service
systemctl restart triggerhappy.service 2>/dev/null || true
echo "  Enabled triggerhappy.service"

echo "  Done."

# ---- 5. Summary ----
echo ""
echo "[5/5] Setup complete!"
echo ""
echo "  REBOOT REQUIRED for USB gadget mode to take effect."
echo ""
echo "  After reboot:"
echo "    sudo systemctl status gameplayer-bot-gadget  # check HID gadget"
echo "    ls -la /dev/hidg*                            # verify HID devices"
echo ""
echo "  Test HID output (no camera needed):"
echo "    sudo python3 $SCRIPT_DIR/src/main.py --test-hid"
echo ""
echo "  Manual operation:"
echo "    sudo python3 $SCRIPT_DIR/src/main.py --guided-roi --camera csi"
echo "    sudo python3 $SCRIPT_DIR/src/main.py --camera csi"
echo ""
echo "  View logs:"
echo "    journalctl -u gameplayer-bot -f"
echo ""
echo "  Hotkeys (3-key USB keyboard):"
echo "    KEY_1: Calibrate ROI (LED blinks during calibration)"
echo "    KEY_2: Start game player"
echo "    KEY_3: Stop game player"
echo ""
if [ "$AUTOSTART" -eq 1 ]; then
    echo "  AUTO-START ENABLED (--boot mode with CSI camera)"
    echo ""
    echo "  Boot workflow:"
    echo "    1. Open Chrome Dino game on host PC"
    echo "    2. Place a white Notepad window over the game baseline"
    echo "    3. Power on the Pi (camera facing the screen)"
    echo "    4. Wait ~30s for Pi to boot and detect the Notepad (ROI calibration)"
    echo "    5. Remove the Notepad window"
    echo "    6. Press spacebar on host PC to start the game"
    echo "    7. Pi plays automatically. Press spacebar to restart after game-over."
    echo ""
    echo "  To disable auto-start:"
    echo "    sudo systemctl disable gameplayer-bot"
else
    echo "  Start game player manually:"
    echo "    sudo systemctl start gameplayer-bot"
    echo ""
    echo "  To enable auto-start (boot mode):"
    echo "    sudo systemctl enable gameplayer-bot"
fi
