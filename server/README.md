# Sidekick host API (phone app — Phase 1)

The always-on backbone of the phone app: a thin FastAPI wrapper over `sidekick.py`.
The engine stays the **sole, append-only writer of `ledger.jsonl`**; this service only
routes requests, enforces auth + idempotency, and publishes each change to git. The
vault (markdown + ledger) remains the source of truth; this host holds the canonical
working clone and the Mac syncs via the Obsidian Git plugin (Phase 4).

## Endpoints
All require `Authorization: Bearer <token>`. Mutations accept an `Idempotency-Key` header.

| Method | Path | Body | Result |
|---|---|---|---|
| GET  | `/feed` | — | `{ "events": [...], "active": [...] }` |
| POST | `/tasks` | `{ "title", "category" }` (`phone\|admin\|errand\|chore`) | `201` task entry |
| POST | `/tasks/{id}/complete` | `{ "completed_at"? }` (ISO) | `200` result |

Errors render as `{ "error": "<message>" }` (`401` no/bad token, `400` bad input,
`404` unknown task, `409`/`5xx` git/host trouble).

## Configuration (environment)
- `SIDEKICK_VAULT` (required) — path to the vault working clone on this host.
- `SIDEKICK_API_TOKEN` (required) — the bearer token the phone sends.
- `SIDEKICK_GIT_PUSH` (default `1`) — set `0` to commit locally without pushing (dev).
- `SIDEKICK_GIT_REMOTE` (default `origin`) — the canonical remote to publish to.

## Run locally
```bash
pip install -r server/requirements.txt
export SIDEKICK_VAULT=/path/to/vault
export SIDEKICK_API_TOKEN=$(openssl rand -hex 24)
# single worker: the write lock is per-process
uvicorn "server.app:create_app" --factory --host 127.0.0.1 --port 8000 --workers 1
```

## Deploy on a VPS (e.g. Hetzner)
The host stores **canonical data**, so it needs **persistent storage** (a VPS disk, or
a free tier with a real persistent volume — not ephemeral).

1. Clone the vault repo and set a commit identity (the engine commits as this user):
   ```bash
   git clone <canonical-remote-url> /srv/sidekick-vault
   git -C /srv/sidekick-vault config user.email "host@sidekick"
   git -C /srv/sidekick-vault config user.name  "Sidekick Host"
   ```
2. Install deps into a venv; set `SIDEKICK_VAULT=/srv/sidekick-vault` and a strong
   `SIDEKICK_API_TOKEN`.
3. Run uvicorn (single worker) under a process manager. Example `systemd` unit
   (`/etc/systemd/system/sidekick.service`):
   ```ini
   [Service]
   Environment=SIDEKICK_VAULT=/srv/sidekick-vault
   Environment=SIDEKICK_API_TOKEN=<your-token>
   WorkingDirectory=/srv/sidekick
   ExecStart=/srv/sidekick/.venv/bin/uvicorn server.app:create_app --factory --host 127.0.0.1 --port 8000 --workers 1
   Restart=always
   [Install]
   WantedBy=multi-user.target
   ```
4. Terminate TLS with a reverse proxy. Example `Caddyfile` (auto Let's Encrypt):
   ```
   sidekick.example.com {
       reverse_proxy 127.0.0.1:8000
   }
   ```
   The bearer token must only ever travel over HTTPS.

## Mac side (Phase 4, summary)
Install the **Obsidian Git** plugin in the vault, point it at the same canonical remote,
and enable auto pull + auto commit/push. `ledger.jsonl` uses a `union` merge driver
(`.gitattributes`) so the host's and the Mac's appends never conflict.

## Tests
```bash
pip install -r server/requirements.txt -r server/requirements-dev.txt
pytest server/tests -v
```
