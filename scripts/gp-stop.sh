#!/bin/bash
# gameplayer-bot: KEY_3 — stop the game player and any calibration.

# Kill any running game player or calibration
if pkill -f "python3.*main\.py" 2>/dev/null; then
    echo "gp-stop: game player stopped"
else
    echo "gp-stop: no game player running"
fi

# Clean up calibration lock if orphaned
rm -f /tmp/gp-calibrate.lock

# Restore LED to SD card activity
LED="/sys/class/leds/ACT"
echo mmc0 > "$LED/trigger" 2>/dev/null || true
