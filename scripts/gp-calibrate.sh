#!/bin/bash
# gameplayer-bot: KEY_1 — run guided ROI calibration with LED feedback.
# Blinks the Pi4 green ACT LED during calibration, restores on completion.

set -e

source /etc/gameplayer-bot.env
LED="/sys/class/leds/ACT"
LOCK="/tmp/gp-calibrate.lock"
CALIBRATED="/tmp/gp-calibrated"

# Prevent concurrent runs
if [ -f "$LOCK" ]; then
    echo "gp-calibrate: already running"
    exit 0
fi
touch "$LOCK"

cleanup() {
    # Restore LED to SD card activity
    echo mmc0 > "$LED/trigger" 2>/dev/null || true
    rm -f "$LOCK"
}
trap cleanup EXIT

# Stop any running game player first
pkill -f "python3.*main\.py.*--camera" 2>/dev/null || true
sleep 0.5

# Start LED blinking
echo timer > "$LED/trigger"
echo 100 > "$LED/delay_on"
echo 100 > "$LED/delay_off"

echo "gp-calibrate: starting guided ROI calibration..."

# Run guided-roi
if python3 "$REPO_DIR/src/main.py" --guided-roi --camera csi; then
    touch "$CALIBRATED"
    echo "gp-calibrate: calibration successful"
else
    echo "gp-calibrate: calibration failed"
fi

# cleanup runs via trap
