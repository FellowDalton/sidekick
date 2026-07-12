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

/** Must be called from a user gesture (the Settings button click). */
export async function enablePush(): Promise<EnableResult> {
  if (!pushSupported()) return "unsupported";
  const permission = await Notification.requestPermission();
  if (permission !== "granted") return "denied";
  const key = await getVapidPublicKey();
  const reg = await navigator.serviceWorker.ready;
  const sub = await reg.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: urlBase64ToUint8Array(key)
  });
  await subscribePush(sub.toJSON());
  return "enabled";
}
