// Client half of web push (spec sub-project 4). On iOS ALL of these must hold:
// the PWA is installed (Home Screen), the call happens inside a user gesture,
// and the user grants Notification permission. The VAPID public key comes from
// the server (GET /api/push/vapid-public-key) so it is never hardcoded here.
import { getVapidPublicKey, subscribePush } from "./api";

export type EnableResult = "enabled" | "denied" | "unsupported";

export function pushSupported(): boolean {
  return typeof Notification !== "undefined"
    && "serviceWorker" in navigator
    && "PushManager" in window;
}

function urlBase64ToUint8Array(base64: string): Uint8Array {
  const padding = "=".repeat((4 - (base64.length % 4)) % 4);
  const b64 = (base64 + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(b64);
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

const STEP_TIMEOUT_MS = 10_000;

/** Reject after STEP_TIMEOUT_MS with the step's name, so a stalled browser API
 *  surfaces as an actionable error instead of an eternal "Enabling…" spinner. */
function withTimeout<T>(p: Promise<T>, step: string): Promise<T> {
  return new Promise((resolve, reject) => {
    const t = setTimeout(() => reject(new Error(`stalled at: ${step} — close and reopen the app, then retry`)), STEP_TIMEOUT_MS);
    p.then(v => { clearTimeout(t); resolve(v); }, e => { clearTimeout(t); reject(e); });
  });
}

/** Must be called from a user gesture (the Settings button click). */
export async function enablePush(): Promise<EnableResult> {
  if (!pushSupported()) return "unsupported";
  const permission = await Notification.requestPermission();
  if (permission !== "granted") return "denied";
  const reg = await withTimeout(navigator.serviceWorker.ready, "service worker");
  // a previous attempt may have subscribed but died before reaching the server —
  // reuse that subscription and just re-send it (calling subscribe() again over
  // an existing subscription is also where iOS likes to hang)
  let sub = await withTimeout(reg.pushManager.getSubscription(), "subscription check");
  if (!sub) {
    const key = await getVapidPublicKey();
    sub = await withTimeout(reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(key)
    }), "push subscription");
  }
  await subscribePush(sub.toJSON());
  return "enabled";
}
