#!/bin/bash
# gameplayer-bot: KEY_1 — run guided ROI calibration with LED feedback.
# Blinks the Pi green ACT LED during calibration, restores on completion.

set -e

# Derive env file path from this script's location
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
source "$SCRIPT_DIR/gameplayer-bot.env"
LED="/sys/class/leds/ACT"
LOCK="/tmp/gp-calibrate.lock"
LED_SAVE="/tmp/gp-led-trigger"

# Prevent concurrent runs
if [ -f "$LOCK" ]; then
    echo "gp-calibrate: already running"
    exit 0
fi
touch "$LOCK"

# Save the current LED trigger before we change it
if [ -f "$LED/trigger" ]; then
    # Extract the active trigger (shown in [brackets])
    sed -n 's/.*\[\(.*\)\].*/\1/p' "$LED/trigger" > "$LED_SAVE"
fi

cleanup() {
    # Restore LED to its original trigger
    if [ -f "$LED_SAVE" ]; then
        echo "$(cat "$LED_SAVE")" > "$LED/trigger" 2>/dev/null || true
        rm -f "$LED_SAVE"
    fi
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
    echo "gp-calibrate: calibration successful"
else
    echo "gp-calibrate: calibration failed"
fi

# cleanup runs via trap
