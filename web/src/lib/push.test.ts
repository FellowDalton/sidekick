import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { enablePush, pushSupported } from "./push";
import { settings } from "./settings";

const SUB_JSON = { endpoint: "https://push.example/e", keys: { p256dh: "p", auth: "a" } };

const subscribe = vi.fn(async (_opts?: PushSubscriptionOptionsInit) => ({ toJSON: () => SUB_JSON }));

function mockApiFetch() {
  return vi.fn(async (url: string) => {
    if (url === "/api/push/vapid-public-key")
      return new Response(JSON.stringify({ key: "BFakeServerKey" }), {
        status: 200, headers: { "Content-Type": "application/json" }
      });
    if (url === "/api/push/subscribe")
      return new Response(JSON.stringify({ ok: true, subscriptions: 1 }), {
        status: 200, headers: { "Content-Type": "application/json" }
      });
    throw new Error(`unexpected fetch: ${url}`);
  });
}

function stubPushEnv(permission: NotificationPermission = "granted",
                     existingSub: { toJSON: () => object } | null = null,
                     ready?: Promise<unknown>) {
  vi.stubGlobal("Notification", { requestPermission: vi.fn(async () => permission) });
  vi.stubGlobal("PushManager", function () { /* presence check only */ });
  Object.defineProperty(navigator, "serviceWorker", {
    configurable: true,
    value: {
      ready: ready ?? Promise.resolve({
        pushManager: { subscribe, getSubscription: vi.fn(async () => existingSub) }
      })
    }
  });
}

beforeEach(() => {
  settings.set({ token: "t0ken", apiBase: "" });
  subscribe.mockClear();
});

afterEach(() => {
  vi.unstubAllGlobals();
  delete (navigator as any).serviceWorker;   // keep pushSupported() honest again
});

describe("enablePush", () => {
  it("permission → subscribe with the server's VAPID key → POST /api/push/subscribe", async () => {
    stubPushEnv();
    const f = mockApiFetch();
    vi.stubGlobal("fetch", f);
    expect(await enablePush()).toBe("enabled");
    const opts = subscribe.mock.calls[0][0]!;
    expect(opts.userVisibleOnly).toBe(true);
    expect(opts.applicationServerKey).toBeInstanceOf(Uint8Array);
    const post = f.mock.calls.find(([u]) => u === "/api/push/subscribe");
    expect(post).toBeDefined();
  });

  it("returns 'denied' without subscribing or touching the network", async () => {
    stubPushEnv("denied");
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("no network expected"); }));
    expect(await enablePush()).toBe("denied");
    expect(subscribe).not.toHaveBeenCalled();
  });

  it("returns 'unsupported' when the push APIs are missing (plain jsdom)", async () => {
    expect(pushSupported()).toBe(false);
    expect(await enablePush()).toBe("unsupported");
  });

  it("reuses an existing subscription instead of subscribing again", async () => {
    // a previous attempt may have subscribed but died before reaching the
    // server — the retry must just re-POST it, not call subscribe() again
    stubPushEnv("granted", { toJSON: () => SUB_JSON });
    const f = mockApiFetch();
    vi.stubGlobal("fetch", f);
    expect(await enablePush()).toBe("enabled");
    expect(subscribe).not.toHaveBeenCalled();
    expect(f.mock.calls.find(([u]) => u === "/api/push/subscribe")).toBeDefined();
  });

  it("rejects with a step-labelled error instead of hanging forever", async () => {
    vi.useFakeTimers();
    try {
      stubPushEnv("granted", null, new Promise(() => {}));   // SW never readies
      vi.stubGlobal("fetch", mockApiFetch());
      const p = enablePush();
      const guard = expect(p).rejects.toThrow(/service worker/);
      await vi.advanceTimersByTimeAsync(10000);
      await guard;
    } finally {
      vi.useRealTimers();
    }
  });
});
