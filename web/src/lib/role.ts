import { writable } from "svelte/store";
import { browser } from "$app/environment";
import { getMe, type Identity } from "./api";

const KEY = "sidekick.identity";

function load(): Identity | null {
  if (!browser) return null;
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) {
      const v = JSON.parse(raw);
      if (v && v.name && (v.role === "full" || v.role === "shared")) {
        return { name: v.name, role: v.role };
      }
    }
  } catch { /* ignore */ }
  return null;
}

/** The token's identity as the server sees it (GET /me). null = unknown / no token.
 *  This store only steers the UI — the API enforces roles server-side. */
export const identity = writable<Identity | null>(load());

if (browser) {
  identity.subscribe(v => {
    try {
      if (v) localStorage.setItem(KEY, JSON.stringify(v));
      else localStorage.removeItem(KEY);
    } catch { /* ignore */ }
  });
}

let lastToken: string | null = null;
let generation = 0;

/** Forget the cached identity (token cleared; tests). */
export function resetIdentity() {
  generation++;
  lastToken = null;
  identity.set(null);
}

/** Resolve the token's role via GET /me. No-op for a repeat token; on failure the
 *  identity is cleared and the next call retries. */
export async function loadIdentity(token: string): Promise<void> {
  const t = token.trim();
  if (!t) { resetIdentity(); return; }
  if (t === lastToken) return;
  lastToken = t;
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
