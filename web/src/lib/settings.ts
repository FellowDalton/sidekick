import { writable, get } from "svelte/store";
import { browser } from "$app/environment";

export interface Settings { token: string; apiBase: string; }
const KEY = "sidekick.settings";
const EMPTY: Settings = { token: "", apiBase: "" };

function load(): Settings {
  if (!browser) return EMPTY;
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) { const v = JSON.parse(raw); return { token: v.token || "", apiBase: v.apiBase || "" }; }
  } catch { /* ignore */ }
  return EMPTY;
}

export const settings = writable<Settings>(load());

if (browser) {
  settings.subscribe(v => {
    try { localStorage.setItem(KEY, JSON.stringify(v)); } catch { /* ignore */ }
  });
}

export const hasToken = () => get(settings).token.trim().length > 0;
