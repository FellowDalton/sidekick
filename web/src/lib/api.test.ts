import { describe, it, expect, vi, beforeEach } from "vitest";
import { getFeed, getMe, createTask, completeTask, getVapidPublicKey, subscribePush, startAgentJob, getAgentJob, createList, deleteList, setTaskDescription, ApiError } from "./api";
import { settings } from "./settings";

function mockFetch(status: number, body: unknown) {
  return vi.fn(async () => new Response(JSON.stringify(body), {
    status, headers: { "Content-Type": "application/json" }
  }));
}

beforeEach(() => {
  settings.set({ token: "t0ken", apiBase: "" });
});

describe("getFeed", () => {
  it("calls /api/feed with the bearer token and returns the feed", async () => {
    const f = mockFetch(200, { events: [], active: [] });
    vi.stubGlobal("fetch", f);
    const feed = await getFeed();
    expect(feed).toEqual({ events: [], active: [] });
    const [url, opts] = f.mock.calls[0];
    expect(url).toBe("/api/feed");
    expect(opts.headers["Authorization"]).toBe("Bearer t0ken");
  });

  it("throws ApiError(401) on unauthorized", async () => {
    vi.stubGlobal("fetch", mockFetch(401, { error: "unauthorized" }));
    await expect(getFeed()).rejects.toMatchObject({ status: 401 });
  });
});

describe("createTask", () => {
  it("POSTs title+category with an Idempotency-Key", async () => {
    const f = mockFetch(201, { id: "x", task: "Buy milk", category: "errand", sat_for_hours: 0, plan: null });
    vi.stubGlobal("fetch", f);
    const res = await createTask("Buy milk", "errand");
    expect(res.id).toBe("x");
    const [url, opts] = f.mock.calls[0];
    expect(url).toBe("/api/tasks");
    expect(opts.method).toBe("POST");
    expect(JSON.parse(opts.body)).toEqual({ title: "Buy milk", category: "errand" });
    expect(typeof opts.headers["Idempotency-Key"]).toBe("string");
    expect(opts.headers["Idempotency-Key"].length).toBeGreaterThan(0);
  });

  it("surfaces the API error message on 400", async () => {
    vi.stubGlobal("fetch", mockFetch(400, { error: "category must be one of [...]" }));
    await expect(createTask("x", "bad" as any)).rejects.toMatchObject({ status: 400 });
  });
});

describe("completeTask", () => {
  it("POSTs completed_at to the complete endpoint", async () => {
    const f = mockFetch(200, { id: "x", status: "done", completed_at: "T", sat_for_hours: 1, already_done: false });
    vi.stubGlobal("fetch", f);
    const res = await completeTask("x", "2026-06-20T10:00:00Z");
    expect(res.status).toBe("done");
    const [url, opts] = f.mock.calls[0];
    expect(url).toBe("/api/tasks/x/complete");
    expect(JSON.parse(opts.body)).toEqual({ completed_at: "2026-06-20T10:00:00Z" });
  });
});

describe("getMe", () => {
  it("calls /api/me with the bearer token and returns the identity", async () => {
    const f = mockFetch(200, { name: "wife", role: "shared" });
    vi.stubGlobal("fetch", f);
    const me = await getMe();
    expect(me).toEqual({ name: "wife", role: "shared" });
    const [url, opts] = f.mock.calls[0];
    expect(url).toBe("/api/me");
    expect(opts.headers["Authorization"]).toBe("Bearer t0ken");
  });

  it("throws ApiError(401) on an unknown token", async () => {
    vi.stubGlobal("fetch", mockFetch(401, { error: "unauthorized" }));
    await expect(getMe()).rejects.toMatchObject({ status: 401 });
  });
});

describe("createTask (shared)", () => {
  it("includes shared: true in the body when asked", async () => {
    const f = mockFetch(201, {
      id: "s1", task: "Buy milk", category: "chore", sat_for_hours: 0,
      plan: null, from: "wife", shared: true
    });
    vi.stubGlobal("fetch", f);
    await createTask("Buy milk", "chore", true);
    const [, opts] = f.mock.calls[0];
    expect(JSON.parse(opts.body)).toEqual({ title: "Buy milk", category: "chore", shared: true });
  });

  it("omits shared from the body by default (backward compatible)", async () => {
    const f = mockFetch(201, { id: "x", task: "Buy milk", category: "errand", sat_for_hours: 0, plan: null });
    vi.stubGlobal("fetch", f);
    await createTask("Buy milk", "errand");
    const [, opts] = f.mock.calls[0];
    expect(JSON.parse(opts.body)).toEqual({ title: "Buy milk", category: "errand" });
  });
});

describe("push api", () => {
  it("GETs the VAPID public key with the bearer token", async () => {
    const f = mockFetch(200, { key: "BPubKey" });
    vi.stubGlobal("fetch", f);
    expect(await getVapidPublicKey()).toBe("BPubKey");
    const [url, opts] = f.mock.calls[0];
    expect(url).toBe("/api/push/vapid-public-key");
    expect(opts.headers["Authorization"]).toBe("Bearer t0ken");
  });

  it("POSTs the subscription JSON to /api/push/subscribe", async () => {
    const f = mockFetch(200, { ok: true, subscriptions: 1 });
    vi.stubGlobal("fetch", f);
    const sub = { endpoint: "https://push.example/e", keys: { p256dh: "p", auth: "a" } };
    await subscribePush(sub as PushSubscriptionJSON);
    const [url, opts] = f.mock.calls[0];
    expect(url).toBe("/api/push/subscribe");
    expect(opts.method).toBe("POST");
    expect(JSON.parse(opts.body)).toEqual(sub);
  });

  it("surfaces 503 when push is not configured on the host", async () => {
    vi.stubGlobal("fetch", mockFetch(503, { error: "web push not configured" }));
    await expect(getVapidPublicKey()).rejects.toMatchObject({ status: 503 });
  });
});

describe("agent api", () => {
  const job = {
    id: "j1", task_id: "t1", action: "research", status: "queued",
    summary: null, error: null, log_tail: null,
    created_at: "T", started_at: null, finished_at: null
  };

  it("POSTs the action to /agent with an Idempotency-Key", async () => {
    const f = mockFetch(202, job);
    vi.stubGlobal("fetch", f);
    const res = await startAgentJob("t1", "research");
    expect(res.status).toBe("queued");
    const [url, opts] = f.mock.calls[0];
    expect(url).toBe("/api/tasks/t1/agent");
    expect(opts.method).toBe("POST");
    expect(JSON.parse(opts.body)).toEqual({ action: "research" });
    expect(typeof opts.headers["Idempotency-Key"]).toBe("string");
    expect(opts.headers["Idempotency-Key"].length).toBeGreaterThan(0);
  });

  it("GETs a job by id with the bearer token", async () => {
    const f = mockFetch(200, { ...job, status: "done", summary: "plan set" });
    vi.stubGlobal("fetch", f);
    const res = await getAgentJob("j1");
    expect(res.summary).toBe("plan set");
    const [url, opts] = f.mock.calls[0];
    expect(url).toBe("/api/agent/jobs/j1");
    expect(opts.headers["Authorization"]).toBe("Bearer t0ken");
  });

  it("surfaces 403 when the role may not run the action", async () => {
    vi.stubGlobal("fetch", mockFetch(403, { error: "forbidden" }));
    await expect(startAgentJob("t1", "research")).rejects.toMatchObject({ status: 403 });
  });
});

describe("named lists api", () => {
  it("createList POSTs the name to /api/lists", async () => {
    const f = mockFetch(201, { id: "groceries", name: "Groceries", created: "2026-07-19T00:00:00Z" });
    vi.stubGlobal("fetch", f);
    const entry = await createList("Groceries");
    expect(entry.id).toBe("groceries");
    const [url, opts] = f.mock.calls[0];
    expect(url).toContain("/api/lists");
    expect(JSON.parse(opts.body)).toEqual({ name: "Groceries" });
    expect(typeof opts.headers["Idempotency-Key"]).toBe("string");
    expect(opts.headers["Idempotency-Key"].length).toBeGreaterThan(0);
  });

  it("deleteList DELETEs /api/lists/{id}", async () => {
    const f = mockFetch(200, { ok: true });
    vi.stubGlobal("fetch", f);
    await deleteList("groceries");
    const [url, opts] = f.mock.calls[0];
    expect(url).toContain("/api/lists/groceries");
    expect(opts.method).toBe("DELETE");
  });

  it("createTask includes list only when given", async () => {
    const f = mockFetch(201, { id: "t", task: "Buy milk" });
    vi.stubGlobal("fetch", f);
    await createTask("Buy milk", "errand", true, "groceries");
    const [, opts] = f.mock.calls[0];
    expect(JSON.parse(opts.body)).toEqual(
      { title: "Buy milk", category: "errand", shared: true, list: "groceries" });
  });
});

describe("task description api", () => {
  it("createTask includes description only when given", async () => {
    const f = mockFetch(201, { id: "t", task: "Buy milk" });
    vi.stubGlobal("fetch", f);
    await createTask("Buy milk", "chore", true, undefined, "details");
    const [, opts] = f.mock.calls[0];
    expect(JSON.parse(opts.body)).toEqual(
      { title: "Buy milk", category: "chore", shared: true, description: "details" });
  });

  it("createTask omits description from the body by default (backward compatible)", async () => {
    const f = mockFetch(201, { id: "x", task: "Buy milk", category: "errand", sat_for_hours: 0, plan: null });
    vi.stubGlobal("fetch", f);
    await createTask("Buy milk", "errand");
    const [, opts] = f.mock.calls[0];
    expect(JSON.parse(opts.body)).toEqual({ title: "Buy milk", category: "errand" });
  });

  it("setTaskDescription POSTs to /api/tasks/{id}/description with an Idempotency-Key", async () => {
    const f = mockFetch(200, { id: "t1", task: "Buy milk", category: "errand", sat_for_hours: 0, plan: null, description: "x" });
    vi.stubGlobal("fetch", f);
    const res = await setTaskDescription("t1", "x");
    expect(res.description).toBe("x");
    const [url, opts] = f.mock.calls[0];
    expect(url).toContain("/api/tasks/t1/description");
    expect(opts.method).toBe("POST");
    expect(JSON.parse(opts.body)).toEqual({ description: "x" });
    expect(typeof opts.headers["Idempotency-Key"]).toBe("string");
    expect(opts.headers["Idempotency-Key"].length).toBeGreaterThan(0);
  });
});
