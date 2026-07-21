#!/usr/bin/env bash
# Install the Sidekick nudge as a launchd agent that fires daily.
# Usage:  ./install-nudge.sh [hour] [minute]   (default 9 0)
set -euo pipefail

VAULT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$(command -v python3 || true)"
[ -z "$PYTHON" ] && { echo "python3 not found on PATH"; exit 1; }
"$PYTHON" -c "import yaml" 2>/dev/null || \
  echo "WARN: pyyaml not installed for $PYTHON — run: $PYTHON -m pip install pyyaml"
command -v claude >/dev/null 2>&1 || \
  echo "WARN: 'claude' not on PATH — nudge will use the deterministic fallback until claude is reachable (or set claude_cmd in nudge.config.json)"

HOUR="${1:-9}"; MIN="${2:-0}"
LABEL="com.sidekick.nudge"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
mkdir -p "$HOME/Library/LaunchAgents"

cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON</string>
    <string>$VAULT/nudge.py</string>
    <string>run</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>$HOUR</integer><key>Minute</key><integer>$MIN</integer></dict>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>$PATH</string>
    <key>HOME</key><string>$HOME</string>
  </dict>
  <key>WorkingDirectory</key><string>$VAULT</string>
  <key>StandardOutPath</key><string>$VAULT/nudge.out.log</string>
  <key>StandardErrorPath</key><string>$VAULT/nudge.err.log</string>
  <key>RunAtLoad</key><false/>
</dict>
</plist>
PLIST

# (re)load. launchctl load/unload works on current macOS; if it errors on your
# version, use: launchctl bootout gui/$UID "$PLIST"; launchctl bootstrap gui/$UID "$PLIST"
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

printf 'Installed %s — fires daily at %02d:%02d\n' "$LABEL" "$HOUR" "$MIN"
echo "Plist:   $PLIST"
echo "Test it: $PYTHON $VAULT/nudge.py run --dry-run     (decides + prints, sends nothing)"
echo "Logs:    $VAULT/nudge.log"
