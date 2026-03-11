#!/bin/bash
# gameplayer-bot: KEY_2 — start (or restart) the game player.
# Waits for any running calibration to finish first.
# If already running, kills the old process and starts fresh.

source /etc/gameplayer-bot.env
LOCK="/tmp/gp-calibrate.lock"

# If calibration is running, wait for it (max 30s)
if [ -f "$LOCK" ]; then
    echo "gp-start: waiting for calibration to finish..."
    for i in $(seq 1 30); do
        [ ! -f "$LOCK" ] && break
        sleep 1
    done
    if [ -f "$LOCK" ]; then
        echo "gp-start: calibration still running after 30s, aborting"
        exit 1
    fi
fi

# Kill any existing game player (allows restart after game-over)
if pkill -f "python3.*main\.py.*--camera" 2>/dev/null; then
    echo "gp-start: stopped previous game player"
    sleep 0.5
fi

echo "gp-start: starting game player..."
nohup python3 "$REPO_DIR/src/main.py" --camera csi \
    >> /tmp/gameplayer-bot.log 2>&1 &

echo "gp-start: game player started (pid=$!)"
echo "gp-start: log at /tmp/gameplayer-bot.log"
