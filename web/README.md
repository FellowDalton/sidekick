# Sidekick web (phone app — Phase 2)

A mobile-first, installable SvelteKit PWA that reads the dashboard from the Phase 1
host API and lets you complete and capture tasks. It calls the API **same-origin via
a proxy** (Vite in dev, Caddy in prod), so there's no CORS and the backend is untouched.
The level/branch/log "game brain" is computed in the browser from the raw feed.

Role `shared` tokens land on **/shared** — a plain add-box + checkbox list — and are
redirected away from everything else (Settings stays reachable for token entry); role
`full` gets the whole app plus a Shared tab. The server enforces the roles; the UI
only mirrors them.

## Develop
```bash
# 1) run the Phase 1 host API (from the repo root)
SIDEKICK_VAULT=/path/to/vault SIDEKICK_API_TOKEN=dev-token \
  python3 -m uvicorn server.app:create_app --factory --port 8000 --workers 1
# 2) run the web app (from web/)
npm install
npm run dev
```
Open the Vite URL it prints. Vite proxies `/api/*` → `http://127.0.0.1:8000`. On first
load you'll land on **Settings** — paste `dev-token` — then the Dashboard loads.

## Test
```bash
npm test                       # Vitest unit + component
npx playwright install chromium && npm run e2e   # Playwright end-to-end
```

## Build & deploy (prod)
```bash
npm run build                  # static output in web/build/
```
Serve `web/build` and proxy `/api` to the host API with the same web server. Example
`Caddyfile` (one origin → no CORS, installable PWA):
```
sidekick.example.com {
    handle /api/* {
        uri strip_prefix /api
        reverse_proxy 127.0.0.1:8000
    }
    handle {
        root * /srv/sidekick/web/build
        try_files {path} /index.html
        file_server
    }
}
```

## Install on iPhone
Open the site in Safari → Share → **Add to Home Screen**. The app installs with its own
icon and opens standalone; it caches the shell + last feed so it opens offline (writes
still need a connection in this version).
