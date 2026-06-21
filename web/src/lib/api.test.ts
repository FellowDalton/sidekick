import { describe, it, expect, vi, beforeEach } from "vitest";
import { getFeed, createTask, completeTask, ApiError } from "./api";
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
