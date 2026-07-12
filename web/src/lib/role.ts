import { writable, get } from "svelte/store";
import { browser } from "$app/environment";
import { getMe, type Identity } from "./api";
import { settings } from "./settings";

const KEY = "sidekick.identity";

const currentToken = browser ? get(settings).token.trim() : "";

/** Cached identity is only trustworthy if it was produced by the token
 *  currently in settings — otherwise it's a stale role from an old token
 *  and must not seed the store (it would drive routing before getMe resolves). */
function load(): Identity | null {
  if (!browser) return null;
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) {
      const v = JSON.parse(raw);
      if (v && v.name && (v.role === "full" || v.role === "shared") && v.token === currentToken) {
        return { name: v.name, role: v.role };
      }
      localStorage.removeItem(KEY);
    }
  } catch { /* ignore */ }
  return null;
}

const initialIdentity = load();

/** The token's identity as the server sees it (GET /me). null = unknown / no token.
 *  This store only steers the UI — the API enforces roles server-side. */
export const identity = writable<Identity | null>(initialIdentity);

// The cache was already verified against currentToken above, so if it seeded
// the store, currentToken is also the token that produced it.
let lastToken: string | null = initialIdentity ? currentToken : null;

if (browser) {
  identity.subscribe(v => {
    try {
      if (v) localStorage.setItem(KEY, JSON.stringify({ token: lastToken ?? "", name: v.name, role: v.role }));
      else localStorage.removeItem(KEY);
    } catch { /* ignore */ }
  });
}

let generation = 0;

/** Forget the cached identity (token cleared; tests). */
export function resetIdentity() {
  generation++;
  lastToken = null;
  identity.set(null);
  // A cleared token must not leave a previous role's feed cached for whatever
  // token loads next (jsdom/SSR have no `caches`, hence the guard).
  if (typeof caches !== "undefined") void caches.delete("sidekick-feed");
}

/** Resolve the token's role via GET /me. No-op for a repeat token; on failure the
 *  identity is cleared and the next call retries. */
export async function loadIdentity(token: string): Promise<void> {
  const t = token.trim();
  if (!t) { resetIdentity(); return; }
  if (t === lastToken) return;
  lastToken = t;
  // A genuinely new token starts loading — a stale role from the previous
  // token must never drive routing while this one resolves. Also drop any
  // cached /api/feed response: it may hold the previous token's role's data
  // (the SW cache is keyed by URL only, not by Authorization header), and
  // serving it to a different-role session offline would leak it.
  identity.set(null);
  if (typeof caches !== "undefined") void caches.delete("sidekick-feed");
  generation++;
  const currentGeneration = generation;
  try {
    const result = await getMe();
    if (currentGeneration === generation) {
      identity.set(result);
    }
  } catch {
    if (currentGeneration === generation) {
      lastToken = null;
      identity.set(null);
    }
  }
}
