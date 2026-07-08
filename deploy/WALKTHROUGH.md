# Sidekick deploy — step-by-step walkthrough

A single top-to-bottom checklist to get the phone app live on your Hetzner **CX23** box,
reached from your iPhone over **Tailscale**. Do the steps in order. Lines in code blocks are
copy-paste; steps marked **(browser)** happen in a web UI.

Fill in as you go:
- `SERVER_IP` = your VPS public IPv4 = `138.199.166.196`
- API token (generated in Phase C) = ``
- Tailnet URL (shown in Phase D) = `https://sidekick.tail81b55b.ts.net  (tailnet only) → 127.0.0.1:8080`

Order matters, and note: **Tailscale is the *last* step, not the first.** You SSH in over the
public IP, set everything up, and only expose it to your phone at the end.

---

## Phase 0 — accounts (can do anytime before Phase D/E)
- [x] A free **Tailscale** account (tailscale.com) — sign in with Google/GitHub/etc.
- [x] In the Tailscale **admin console → DNS**: enable **MagicDNS** and **HTTPS Certificates** (one-time).
- [x] **Tailscale** app installed on your **iPhone** (App Store), signed into the same account.

## Phase A — the VPS  ✅ (done)
Server created: Hetzner **CX23**, Ubuntu 24.04, your SSH key attached, firewall allowing
**inbound TCP 22 (SSH)**. Nothing else to do here.

## Phase 1 — SSH in

**1a. Find your server's IP.** Hetzner Cloud console → your project → click the `sidekick`
server. The **Public IPv4** is shown at the top (e.g. `203.0.113.45`). Copy it — that's
`SERVER_IP`. Write it in the box at the top of this file.

**1b. Open a terminal on your Mac.** Spotlight (⌘-Space) → type `Terminal` → Enter.

**1c. Connect** (replace with your real IP):
```bash
ssh root@SERVER_IP
```

**1d. First-connect prompt.** The very first time you'll see:
```
The authenticity of host '203.0.113.45' can't be established.
ED25519 key fingerprint is SHA256:...
Are you sure you want to continue connecting (yes/no/[fingerprint])?
```
Type **`yes`** and press Enter. (This just records the server's identity in
`~/.ssh/known_hosts`; you won't be asked again.)

**1e. You're in** when the prompt changes to something like:
```
root@sidekick:~#
```
No password is asked — login uses the SSH key you attached when creating the server.
**Everything from here (Phase B onward) is typed at this `root@sidekick:~#` prompt**, unless a
step says "(browser)".

<details><summary>If it doesn't connect</summary>

- **`Permission denied (publickey)`** → your local SSH key isn't the one attached to the
  server. Try naming the key explicitly: `ssh -i ~/.ssh/id_ed25519 root@SERVER_IP` (swap in
  your key's filename — `ls ~/.ssh/*.pub` lists them). If none match, add your public key to
  the server via the Hetzner console (server → **Rescue/Console** or re-add under SSH Keys).
- **`Connection timed out`** → double-check the IP, and that the firewall allows **inbound
  TCP 22**. You can also use Hetzner's browser **Console** (server page → `>_ Console`) to get
  a root shell without SSH.
- **`Connection refused`** → the box may still be booting; wait ~30s and retry.
</details>

## Phase B — give the host GitHub access, then clone
```bash
# 1. service user that owns the clone + runs the API
adduser --system --group --home /home/sidekick --shell /bin/bash sidekick

# 2. its SSH deploy key + trust GitHub's host key
sudo -u sidekick ssh-keygen -t ed25519 -f /home/sidekick/.ssh/id_ed25519 -N ""
sudo -u sidekick bash -lc 'ssh-keyscan github.com >> ~/.ssh/known_hosts'

# 3. print the PUBLIC key — copy the whole line
cat /home/sidekick/.ssh/id_ed25519.pub
```
- [ ] **(browser)** github.com/FellowDalton/sidekick → **Settings → Deploy keys → Add deploy key**.
      Title `sidekick-host`, paste the key line, **tick "Allow write access"**, save.

```bash
# 4. clone the vault (this repo == the vault) to /srv/sidekick
mkdir -p /srv && chown sidekick:sidekick /srv
sudo -u sidekick git clone git@github.com:FellowDalton/sidekick.git /srv/sidekick
```

## Phase C — bootstrap (one command)
```bash
sudo bash /srv/sidekick/deploy/bootstrap.sh
```
Installs Python/Node 22/Caddy/Tailscale, builds the venv + the PWA, writes
`/etc/sidekick.env` with a generated **API token**, and starts the `sidekick` (uvicorn) and
`caddy` services. **Copy the API token it prints at the end** into the box at the top of this file.

Sanity check (all local to the box):
```bash
systemctl status sidekick caddy --no-pager
curl -s -H "Authorization: Bearer $(grep API_TOKEN /etc/sidekick.env | cut -d= -f2)" \
  http://127.0.0.1:8080/api/feed | head -c 200      # → JSON starting {"events":...
```

## Phase D — put it on Tailscale (expose to your phone)
```bash
tailscale up --hostname=sidekick     # opens an auth URL — open it, sign in
tailscale serve --bg 8080            # auto-TLS; proxies the tailnet name → localhost:8080
tailscale serve status               # prints https://sidekick.<your-tailnet>.ts.net
```
- [ ] Copy that `https://sidekick.….ts.net` URL into the box at the top of this file.

## Phase E — install on your iPhone
- [ ] Tailscale app is connected (from Phase 0).
- [ ] **(browser, Safari)** open your `https://sidekick.….ts.net` URL.
- [ ] You'll land on **Settings** → paste the **API token** → the Dashboard loads.
- [ ] Safari **Share → Add to Home Screen** — installs standalone, caches last feed offline.

## Phase F — Mac side (Obsidian Git)
So your Obsidian edits sync with the host through GitHub:
- [ ] Obsidian → Community plugins → install & enable **Obsidian Git**.
- [ ] Confirm the vault's remote is the canonical GitHub repo (the host pushes there too).
- [ ] Enable **auto pull** + **auto commit-and-push** (e.g. every 5–10 min).

`ledger.jsonl` already uses git's built-in `union` merge driver (`.gitattributes`), so the
host's and Mac's concurrent appends merge without conflicts — nothing extra to install.

---

## Done — day-to-day
- Open the home-screen app → complete/capture tasks; the host writes the ledger and pushes to GitHub.
- **Logs:** `journalctl -u sidekick -f` (API) · `journalctl -u caddy -f` (router).
- **Update the deployment:** `sudo -u sidekick git -C /srv/sidekick pull` then re-run `bootstrap.sh`.
- **Rotate the token:** edit `/etc/sidekick.env`, `systemctl restart sidekick`, re-paste in the phone's Settings.

## If something breaks
- `bootstrap.sh` fails on an apt repo (Node/Caddy) → re-run it; transient mirror hiccups are common.
- Web build OOM (unlikely on 4 GB) → tell me; we add a swap file.
- `tailscale serve` shows no cert → confirm MagicDNS + HTTPS Certificates are on in the admin console, then re-run.
- Phone can't reach the URL → confirm the iPhone's Tailscale app is **connected** (toggle on).
