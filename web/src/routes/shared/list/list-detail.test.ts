import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/svelte";
import type { Feed } from "$lib/types";

vi.mock("$app/state", () => ({ page: { params: { id: "groceries" } } }));
vi.mock("$app/navigation", () => ({ goto: vi.fn() }));
vi.mock("$lib/settings", () => ({ hasToken: () => true }));
vi.mock("$lib/api", () => ({
  getFeed: vi.fn(),
  createTask: vi.fn(async () => ({ id: "new1" })),
  completeTask: vi.fn(async () => ({
    id: "new", status: "done", completed_at: "T", sat_for_hours: 1, already_done: false
  })),
  startAgentJob: vi.fn(),
  getAgentJob: vi.fn(),
  ApiError: class extends Error {
    status: number;
    constructor(status: number, msg: string) { super(msg); this.status = status; }
  }
}));

import Page from "./[id]/+page.svelte";
import { getFeed, createTask, completeTask, startAgentJob, getAgentJob } from "$lib/api";
import { goto } from "$app/navigation";

afterEach(() => vi.useRealTimers());

beforeEach(() => {
  vi.clearAllMocks();
});

describe("list detail view", () => {
  const feed = {
    events: [],
    lists: [{ id: "groceries", name: "Groceries", created: "2026-07-19T00:00:00Z" }],
    active: [
      { id: "p", task: "Plan the party", category: "chore", sat_for_hours: 5, plan: null, shared: true, status: "open", list: "groceries" },
      { id: "c1", task: "Book the venue", category: "chore", sat_for_hours: 2, plan: null, shared: true, parent: "p", status: "open" },
      { id: "c2", task: "Order the cake", category: "chore", sat_for_hours: null, plan: null, shared: true, parent: "p", status: "done", completed_at: "2026-07-19T10:00:00Z" },
      { id: "other", task: "Not in this list", category: "chore", sat_for_hours: 1, plan: null, shared: true, status: "open" }
    ]
  };

  it("shows only this list's roots, with children nested inside", async () => {
    vi.mocked(getFeed).mockResolvedValue(feed as any);
    render(Page);
    const parentRow = (await screen.findByText("Plan the party")).closest("li")!;
    expect(parentRow.textContent).toContain("Book the venue");
    expect(screen.queryByText("Not in this list")).toBeNull();   // that's a To-dos root
    const list = parentRow.closest("ul")!;
    expect(list.querySelectorAll(":scope > li").length).toBe(1);
  });

  it("renders a done child checked, disabled and struck through", async () => {
    vi.mocked(getFeed).mockResolvedValue(feed as any);
    render(Page);
    await screen.findByText("Plan the party");
    const box = screen.getByLabelText("Order the cake — done") as HTMLInputElement;
    expect(box.checked).toBe(true);
    expect(box.disabled).toBe(true);
  });

  it("shows the finish nudge when all children are done", async () => {
    vi.mocked(getFeed).mockResolvedValue({
      ...feed,
      active: [feed.active[0], feed.active[2]]     // parent + done child only
    } as any);
    render(Page);
    expect(await screen.findByText("1/1 done — finish it?")).toBeInTheDocument();
  });

  it("still offers Break it down on a nested open child", async () => {
    vi.mocked(getFeed).mockResolvedValue(feed as any);
    render(Page);
    await screen.findByText("Plan the party");
    expect(screen.getByLabelText("Break down Book the venue")).toBeInTheDocument();
  });

  it("adds a task into this list", async () => {
    vi.mocked(getFeed).mockResolvedValue(feed as any);
    vi.mocked(createTask).mockResolvedValue({ id: "n" } as any);
    render(Page);
    await screen.findByText("Plan the party");
    await fireEvent.input(screen.getByLabelText("New task"), { target: { value: "Buy candles" } });
    await fireEvent.submit(screen.getByLabelText("New task").closest("form")!);
    expect(createTask).toHaveBeenCalledWith("Buy candles", "chore", true, "groceries");
  });

  it("shows list-not-found for an unknown id", async () => {
    vi.mocked(getFeed).mockResolvedValue({ events: [], lists: [], active: [] } as any);
    render(Page);   // param mock still says "groceries", which now doesn't exist
    expect(await screen.findByText(/list not found/i)).toBeInTheDocument();
  });
});
