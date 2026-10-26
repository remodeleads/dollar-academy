#!/bin/bash
# Install/reload the background LaunchAgent that runs the watcher 24/7.
set -euo pipefail
BASE="$(cd "$(dirname "$0")" && pwd)"
LABEL="com.dollaracademy.dasales"
DEST="$HOME/Library/LaunchAgents/$LABEL.plist"

sed -e "s#__BASE__#$BASE#g" -e "s#__HOME__#$HOME#g" \
    "$BASE/$LABEL.plist" > "$DEST"

# reload cleanly (ignore error if not already loaded)
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$DEST"
launchctl enable "gui/$(id -u)/$LABEL"

echo "✅ Loaded $LABEL"
echo "   logs:   tail -f \"$BASE/logs/pipeline.log\""
echo "   stop:   launchctl bootout gui/$(id -u)/$LABEL"
