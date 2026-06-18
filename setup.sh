#!/usr/bin/env bash
# setup.sh — bring Sidekick up from zero. Idempotent and skippable; never writes the ledger.
set -euo pipefail
DIR="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cd "$DIR"

say() { printf '\n\033[1m%s\033[0m\n' "$1"; }
ask() { # ask "prompt" -> echoes the reply (empty allowed)
  local reply; read -r -p "$1 " reply || true; printf '%s' "$reply"; }

say "1/5  Checking Python + pyyaml"
command -v python3 >/dev/null || { echo "python3 not found — install it first."; exit 1; }
if python3 -c "import yaml" 2>/dev/null; then
  echo "  pyyaml: OK"
else
  echo "  pyyaml missing."
  if [ "$(ask 'Install pyyaml with pip3 now? [y/N]')" = "y" ]; then
    pip3 install pyyaml
  else
    echo "  Skipped — the CLI and nudge need pyyaml to run."
  fi
fi

say "2/5  Building the feed"
python3 "$DIR/sidekick.py" regenerate

say "3/5  Nudge config"
if [ -f "$DIR/nudge.config.json" ]; then
  echo "  nudge.config.json already exists — leaving it."
else
  cp "$DIR/nudge.config.example.json" "$DIR/nudge.config.json"
  echo "  Created nudge.config.json from the example."
  token="$(ask 'Paste your Beeper token (blank to skip):')"
  if [ -n "$token" ]; then
    python3 - "$DIR/nudge.config.json" "$token" <<'PY'
import json, sys
p, token = sys.argv[1], sys.argv[2]
cfg = json.load(open(p)); cfg["access_token"] = token
json.dump(cfg, open(p, "w"), indent=2); print("  Token saved.")
PY
    q="$(ask 'Your name to find your self-chat (blank to skip):')"
    [ -n "$q" ] && python3 "$DIR/nudge.py" find-chat "$q" || true
    echo "  Paste the chat id into nudge.config.json (\"chat_id\")."
  fi
fi

say "4/5  Schedule the daily nudge"
if [ "$(ask 'Install the launchd agent now (daily 09:00)? [y/N]')" = "y" ]; then
  "$DIR/install-nudge.sh" 9 0
else
  echo "  Skipped — run 'sidekick nudge-install 9 0' later."
fi

say "5/5  Chrome new tab"
cat <<EOF
  Load the new-tab dashboard:
    1. Open chrome://extensions
    2. Enable Developer mode (top-right)
    3. Load unpacked -> select:
         $DIR/chrome-extension
    4. Open a new tab. It refreshes whenever 'sidekick regenerate' runs.

Done. Day-to-day: use the 'sidekick' command (run 'sidekick help').
EOF
