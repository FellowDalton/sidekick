#!/usr/bin/env bash
# Sidekick host bootstrap — run as root on a fresh Ubuntu/Debian VPS, AFTER the repo has
# been cloned to /srv/sidekick by the `sidekick` service user (see deploy/README.md, phase D).
#
# Idempotent: safe to re-run. It installs system deps, builds the venv + the web bundle,
# writes /etc/sidekick.env (generating a token once), and installs+starts the systemd
# service and the localhost Caddy router. It does NOT run `tailscale up`/`serve` — those
# are account-bound and interactive; the printed summary tells you the exact commands.
#
# Usage:
#   sudo bash /srv/sidekick/deploy/bootstrap.sh
# Optional: SIDEKICK_TOKEN=<token> to pin the API token instead of generating one.
set -euo pipefail

SERVICE_USER=sidekick
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE=/etc/sidekick.env

log() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }

[ "$(id -u)" -eq 0 ] || { echo "Run as root (sudo bash $0)"; exit 1; }
[ "$REPO" = /srv/sidekick ] || echo "Note: repo is at $REPO (expected /srv/sidekick) — continuing."

# --- service user -----------------------------------------------------------------------
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
	log "Creating service user '$SERVICE_USER'"
	adduser --system --group --home "/home/$SERVICE_USER" --shell /bin/bash "$SERVICE_USER"
fi
chown -R "$SERVICE_USER:$SERVICE_USER" "$REPO"

# --- system packages --------------------------------------------------------------------
log "Installing base packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y git python3-venv python3-pip curl ca-certificates gnupg apt-transport-https

if ! command -v node >/dev/null 2>&1 || [ "$(node -p 'process.versions.node.split(".")[0]')" -lt 20 ]; then
	log "Installing Node.js 20 (NodeSource)"
	curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
	apt-get install -y nodejs
fi

if ! command -v caddy >/dev/null 2>&1; then
	log "Installing Caddy (official repo)"
	curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
		| gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
	curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
		> /etc/apt/sources.list.d/caddy-stable.list
	apt-get update -y
	apt-get install -y caddy
fi

if ! command -v tailscale >/dev/null 2>&1; then
	log "Installing Tailscale"
	curl -fsSL https://tailscale.com/install.sh | sh
fi

# --- python venv ------------------------------------------------------------------------
log "Building Python venv + installing engine/server deps"
[ -d "$REPO/.venv" ] || sudo -u "$SERVICE_USER" python3 -m venv "$REPO/.venv"
sudo -u "$SERVICE_USER" "$REPO/.venv/bin/pip" install --upgrade pip
sudo -u "$SERVICE_USER" "$REPO/.venv/bin/pip" install -r "$REPO/server/requirements.txt" pyyaml

# --- web build --------------------------------------------------------------------------
log "Building the PWA (web/build)"
if [ -f "$REPO/web/package-lock.json" ]; then
	sudo -u "$SERVICE_USER" bash -lc "cd '$REPO/web' && npm ci && npm run build"
else
	sudo -u "$SERVICE_USER" bash -lc "cd '$REPO/web' && npm install && npm run build"
fi

# --- git commit identity (for the host's ledger pushes) ---------------------------------
if [ -z "$(sudo -u "$SERVICE_USER" git -C "$REPO" config user.email || true)" ]; then
	log "Setting git commit identity for the host clone"
	sudo -u "$SERVICE_USER" git -C "$REPO" config user.email "host@sidekick"
	sudo -u "$SERVICE_USER" git -C "$REPO" config user.name  "Sidekick Host"
fi

# --- environment file -------------------------------------------------------------------
if [ ! -f "$ENV_FILE" ]; then
	TOKEN="${SIDEKICK_TOKEN:-$(openssl rand -hex 24)}"
	log "Writing $ENV_FILE (new API token generated)"
	cat > "$ENV_FILE" <<EOF
SIDEKICK_VAULT=$REPO
SIDEKICK_API_TOKEN=$TOKEN
SIDEKICK_GIT_PUSH=1
SIDEKICK_GIT_REMOTE=origin
EOF
	chmod 600 "$ENV_FILE"
else
	log "$ENV_FILE already exists — leaving it (and its token) untouched"
fi

# --- systemd service --------------------------------------------------------------------
log "Installing + starting the uvicorn systemd service"
install -m 644 "$REPO/deploy/sidekick.service" /etc/systemd/system/sidekick.service
systemctl daemon-reload
systemctl enable --now sidekick.service

# --- caddy router -----------------------------------------------------------------------
log "Installing the localhost Caddy router"
install -m 644 "$REPO/deploy/Caddyfile" /etc/caddy/Caddyfile
systemctl reload caddy 2>/dev/null || systemctl restart caddy

# --- summary ----------------------------------------------------------------------------
TOKEN_NOW="$(grep -E '^SIDEKICK_API_TOKEN=' "$ENV_FILE" | cut -d= -f2-)"
cat <<EOF

$(log "Bootstrap complete")
  • uvicorn:  systemctl status sidekick   (127.0.0.1:8000)
  • caddy:    systemctl status caddy      (127.0.0.1:8080)
  • API token (paste into the phone's Settings later):
        $TOKEN_NOW

Next — put this host on your tailnet and expose it (run as root):
  1. tailscale up --hostname=sidekick
  2. tailscale serve --bg 8080
  3. tailscale serve status        # prints the https://sidekick.<tailnet>.ts.net URL
  (One-time: in the Tailscale admin console enable MagicDNS + HTTPS Certificates.)

Then open that URL on your iPhone (Tailscale app installed + signed in),
paste the token in Settings, and Add to Home Screen. See deploy/README.md.
EOF
