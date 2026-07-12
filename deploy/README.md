# Sidekick — Phase 4 deploy (VPS + Tailscale)

Get the phone app live: `server/` (the API) and `web/` (the PWA) running 24/7 on a small
VPS, reached privately from your iPhone over **Tailscale** (no public domain, no public
attack surface, automatic HTTPS). The GitHub repo stays the canonical vault; the host and
your Mac both sync through it.

```
iPhone (Tailscale app) ──https──► tailscale serve (auto-TLS, sidekick.<tailnet>.ts.net)
                                       └─► Caddy 127.0.0.1:8080
                                              ├─ /api/* → strip → uvicorn 127.0.0.1:8000 (systemd)
                                              └─ /*     → web/build (SPA fallback)
   Mac (Obsidian Git) ◄── git ──► GitHub (canonical) ◄── git ──► host (server pushes ledger)
```

**Why Caddy *and* Tailscale:** `tailscale serve` gives TLS + tailnet exposure, but it
won't strip the `/api` prefix or do SPA history fallback. Caddy (bound to localhost) does
both, exactly like the prod Caddyfile in `web/README.md` — just without the public-domain
TLS block, since Tailscale terminates TLS.

The files in this folder do the automatable part:
- `bootstrap.sh` — one idempotent script: system deps, venv, web build, env, systemd, Caddy.
- `sidekick.service` — the uvicorn systemd unit (single worker — the write lock is per-process).
- `Caddyfile` — the localhost same-origin router.

---

## What you do by hand vs. what's automated

| Phase | Who | What |
|---|---|---|
| A. Create the VPS | you | Hetzner CX22 (or similar), Ubuntu 24.04, your SSH key |
| B. Deploy key + clone | you (copy-paste) | give the host write access to GitHub, clone to `/srv/sidekick` |
| C. Bootstrap | `bootstrap.sh` | deps, venv, build, env+token, systemd, Caddy |
| D. Tailscale | you (3 commands) | join the tailnet, expose port 8080 with auto-TLS |
| E. iPhone | you | Tailscale app, open the URL, paste token, Add to Home Screen |
| F. Mac | you | Obsidian Git plugin → canonical remote → auto pull/commit/push |

---

## Phase A — create the VPS

Any always-on Linux box with **persistent disk** works (the host holds canonical data).
Recommended: **Hetzner CX22** (~€4/mo), **Ubuntu 24.04**. Add your SSH public key during
creation, note the public IPv4, then:

```bash
ssh root@<vps-ip>
# good hygiene: only SSH stays public; the app binds to localhost + the tailnet.
apt-get update && apt-get install -y ufw
ufw allow OpenSSH && ufw --force enable
```

You do **not** need to open a port for Tailscale — it uses NAT traversal and falls back to
its DERP relays, so it works behind a default-deny firewall. (Optional, for best-case
direct connections: `ufw allow 41641/udp`.)

## Phase B — give the host GitHub access, then clone

The host **pushes** ledger commits, so it needs a deploy key **with write access**. On the
VPS:

```bash
# service user that owns the clone and runs the API
adduser --system --group --home /home/sidekick --shell /bin/bash sidekick

# its own SSH deploy key
sudo -u sidekick ssh-keygen -t ed25519 -f /home/sidekick/.ssh/id_ed25519 -N ""
sudo -u sidekick bash -lc 'ssh-keyscan github.com >> ~/.ssh/known_hosts'
cat /home/sidekick/.ssh/id_ed25519.pub        # ← copy this line
```

Add that public key on GitHub: **repo → Settings → Deploy keys → Add deploy key**, tick
**Allow write access**. Then clone (note: the plain `git@github.com:` host, not your local
`github.com-work` SSH alias):

```bash
mkdir -p /srv && chown sidekick:sidekick /srv
sudo -u sidekick git clone git@github.com:FellowDalton/sidekick.git /srv/sidekick
```

## Phase C — bootstrap

```bash
sudo bash /srv/sidekick/deploy/bootstrap.sh
```

It installs Python/Node/Caddy/Tailscale, builds the venv and the PWA, writes
`/etc/sidekick.env` with a freshly generated `SIDEKICK_API_TOKEN` (**printed at the end —
save it**), and installs + starts the `sidekick` (uvicorn) and `caddy` services. Re-runnable.

Sanity check, all local to the box:
```bash
systemctl status sidekick caddy --no-pager
curl -s -H "Authorization: Bearer $(grep API_TOKEN /etc/sidekick.env | cut -d= -f2)" \
  http://127.0.0.1:8080/api/feed | head -c 200    # → JSON {"events":...,"active":...}
```

### Two users (token map)

For more than one person (e.g. you + a partner), replace the single `SIDEKICK_API_TOKEN`
line in `/etc/sidekick.env` with a token→identity map:

```
SIDEKICK_API_TOKENS={"<dalton-token>":{"name":"dalton","role":"full"},"<wife-token>":{"name":"wife","role":"shared"}}
```

Keep it **compact JSON on one line** — systemd's `EnvironmentFile` parsing doesn't handle
multi-line values. Generate each token with `openssl rand -hex 24`. The legacy
`SIDEKICK_API_TOKEN` (single token) still works on its own and is treated as role `full`.

Verify after editing:
```bash
sudo systemctl restart sidekick
# repeat for EACH token in the map:
curl -s -H "Authorization: Bearer <token>" https://sidekick.tail81b55b.ts.net/api/me
# → {"name":"dalton","role":"full"}  or  {"name":"wife","role":"shared"}
```
Hitting `/api/me` for every token isn't just an identity check — it's also the smoke test
for systemd's env-file JSON parsing, which has quote-handling edge cases (e.g. stray
escaping around the embedded double quotes can silently truncate the value).

## Phase D — put it on your tailnet

If you don't have Tailscale yet, make a free account at tailscale.com (the Personal plan
covers a single user / many devices at $0). One-time in the **admin console → DNS**: enable
**MagicDNS** and **HTTPS Certificates**. Then on the VPS:

```bash
tailscale up --hostname=sidekick      # opens an auth URL — sign in
tailscale serve --bg 8080             # auto-TLS, proxies the tailnet name → localhost:8080
tailscale serve status                # prints https://sidekick.<your-tailnet>.ts.net
```

## Phase E — install on your iPhone

1. App Store → install **Tailscale**, sign in with the same account (leave it connected;
   it works on Wi-Fi and cellular).
2. Safari → open `https://sidekick.<your-tailnet>.ts.net`.
3. You'll land on **Settings** — paste the API token from Phase C → the Dashboard loads.
4. Share → **Add to Home Screen**. It installs standalone and caches the last feed offline.

## Phase F — Mac side (Obsidian Git)

So edits you make in Obsidian sync with the host through GitHub:

1. Obsidian → Community plugins → install & enable **Obsidian Git**.
2. Confirm the vault's remote is the canonical GitHub repo (the host pushes there too).
3. Enable **auto pull** + **auto commit-and-push** (e.g. every 5–10 min).

`ledger.jsonl` already uses git's built-in `union` merge driver (`.gitattributes`), so the
host's and the Mac's concurrent appends merge without conflicts — nothing extra to install.

## Enable the sync timer (two-way sync)

The API publishes on every write, but only the timer brings in commits pushed
from elsewhere (the Mac, claude.ai/code, the agent). On the VPS:

    sudo cp deploy/sidekick-sync.service deploy/sidekick-sync.timer /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable --now sidekick-sync.timer

Verify:

    systemctl list-timers sidekick-sync.timer     # next run scheduled
    sudo systemctl start sidekick-sync.service    # run once now
    journalctl -u sidekick-sync.service -n 5      # expect "sync-pull: updated|unchanged"

A conflicting pull exits 1 with the vault left clean (rebase aborted); check
`journalctl -u sidekick-sync.service` if the phones stop seeing Mac-side changes.

## Web-push nudges (daily, 09:00 Copenhagen)

The VPS sends the daily nudge as a web-push notification (`server/nudge_job.py`).
One-time setup on the VPS:

    # 1. deps into the venv (pywebpush is in server/requirements.txt)
    sudo -u sidekick /srv/sidekick/.venv/bin/pip install -r /srv/sidekick/server/requirements.txt

    # 2. generate the VAPID keypair — prints two env lines, paste them into /etc/sidekick.env
    sudo -u sidekick /srv/sidekick/.venv/bin/python - <<'EOF'
    import base64
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization
    key = ec.generate_private_key(ec.SECP256R1())
    b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()
    print("SIDEKICK_VAPID_PRIVATE=" + b64(key.private_numbers().private_value.to_bytes(32, "big")))
    print("SIDEKICK_VAPID_PUBLIC=" + b64(key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)))
    EOF

Add to `/etc/sidekick.env` (one line each, values unquoted):

    SIDEKICK_VAPID_PRIVATE=...          # from the generator above
    SIDEKICK_VAPID_PUBLIC=...           # from the generator above
    SIDEKICK_VAPID_SUB=mailto:nikoflash@gmail.com
    SIDEKICK_NUDGE_MIN_SAT_HOURS=48     # optional; this is the default
    # SIDEKICK_NUDGE_CMD=pi -p          # optional model wording — leave unset until
    #                                     pi lands on the box (agent-runner sub-project);
    #                                     unset = deterministic wording, always works

Then install and verify:

    sudo systemctl restart sidekick     # the API serves the public key from the env
    sudo cp deploy/sidekick-nudge.service deploy/sidekick-nudge.timer /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable --now sidekick-nudge.timer

    systemctl list-timers sidekick-nudge.timer   # next run: 09:00 Europe/Copenhagen
    sudo -u sidekick bash -c 'set -a; . /etc/sidekick.env; cd /srv/sidekick && .venv/bin/python -m server.nudge_job --dry-run'
    sudo systemctl start sidekick-nudge.service && journalctl -u sidekick-nudge -n 3

Phone (Dalton's iPhone; the shared-role token gets no push this phase):

1. Open the **installed** (Home-Screen) Sidekick app — iOS only allows web push there,
   never in a plain Safari tab.
2. Settings → **Enable notifications** → Allow when iOS asks.
3. With a stalled task present, `sudo systemctl start sidekick-nudge.service` → the
   banner arrives on the phone.

Subscriptions live in `/srv/sidekick/.sidekick-push.json` (gitignored). The sync job
uses the same channel: three consecutive `git pull` failures send one alert.
The old Mac path (`nudge.py` + launchd + Beeper) remains the documented offline fallback.

---

## Operating notes
- **Logs:** `journalctl -u sidekick -f` (API) · `journalctl -u caddy -f` (router).
- **Rotate the token:** edit `/etc/sidekick.env`, `systemctl restart sidekick`, re-paste in the phone's Settings.
- **Update the deployment:** `sudo -u sidekick git -C /srv/sidekick pull` then re-run
  `bootstrap.sh` (rebuilds the web bundle + venv and restarts the services).
- **Nothing app-related is public:** uvicorn and Caddy bind `127.0.0.1`; only `tailscale
  serve` exposes the box, and only to your tailnet.
