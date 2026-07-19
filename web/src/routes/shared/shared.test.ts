import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/svelte";
import type { Feed } from "$lib/types";

vi.mock("$app/navigation", () => ({ goto: vi.fn() }));
vi.mock("$lib/settings", () => ({ hasToken: () => true }));
vi.mock("$lib/api", () => ({
  getFeed: vi.fn(),
  createTask: vi.fn(async () => ({ id: "new1" })),
  completeTask: vi.fn(async () => ({
    id: "new", status: "done", completed_at: "T", sat_for_hours: 1, already_done: false
  })),
  createList: vi.fn(),
  deleteList: vi.fn(),
  startAgentJob: vi.fn(),
  getAgentJob: vi.fn(),
  ApiError: class extends Error {
    status: number;
    constructor(status: number, msg: string) { super(msg); this.status = status; }
  }
}));

import Page from "./+page.svelte";
import { getFeed, createList, deleteList } from "$lib/api";
import { goto } from "$app/navigation";

afterEach(() => vi.useRealTimers());

beforeEach(() => {
  vi.clearAllMocks();
});

describe("shared page — list grid", () => {
  const gridFeed = {
    events: [],
    lists: [{ id: "groceries", name: "Groceries", created: "2026-07-19T00:00:00Z" },
            { id: "packing", name: "Packing", created: "2026-07-19T00:00:00Z" }],
    active: [
      { id: "t1", task: "Buy milk", category: "errand", sat_for_hours: 1, plan: null, shared: true, status: "open", list: "groceries" },
      { id: "t2", task: "Call plumber", category: "phone", sat_for_hours: 2, plan: null, shared: true, status: "open" },
      { id: "t2c", task: "Find number", category: "phone", sat_for_hours: 1, plan: null, shared: true, status: "open", parent: "t2" }
    ]
  };

  it("renders To-dos first, then registry lists, with open root counts", async () => {
    vi.mocked(getFeed).mockResolvedValue(gridFeed as any);
    render(Page);
    const cards = await screen.findAllByRole("link", { name: /open list/i });
    expect(cards.map(c => c.getAttribute("href"))).toEqual(
      ["/shared/list/todos", "/shared/list/groceries", "/shared/list/packing"]);
  });

  it("previews root tasks only — children never appear on a card", async () => {
    vi.mocked(getFeed).mockResolvedValue(gridFeed as any);
    render(Page);
    await screen.findByText("Call plumber");        // t2 is a To-dos root
    expect(screen.queryByText("Find number")).toBeNull();   // child of t2, hidden on grid
  });

  it("shows +N more when a list has more than 5 open roots", async () => {
    const many = Array.from({ length: 7 }, (_, i) => (
      { id: `g${i}`, task: `Item ${i}`, category: "errand", sat_for_hours: 1,
        plan: null, shared: true, status: "open", list: "groceries" }));
    vi.mocked(getFeed).mockResolvedValue({ ...gridFeed, active: many } as any);
    render(Page);
    expect(await screen.findByText("+2 more")).toBeInTheDocument();
  });

  it("creates a list and navigates into it", async () => {
    vi.mocked(getFeed).mockResolvedValue({ events: [], lists: [], active: [] } as any);
    vi.mocked(createList).mockResolvedValue(
      { id: "ferie", name: "Ferie", created: "2026-07-19T00:00:00Z" } as any);
    render(Page);
    await fireEvent.click(await screen.findByRole("button", { name: /new list/i }));
    await fireEvent.input(screen.getByLabelText("List name"), { target: { value: "Ferie" } });
    await fireEvent.submit(screen.getByLabelText("List name").closest("form")!);
    expect(createList).toHaveBeenCalledWith("Ferie");
    expect(goto).toHaveBeenCalledWith("/shared/list/ferie");
  });

  it("offers Delete only on an empty non-default list", async () => {
    vi.mocked(getFeed).mockResolvedValue({
      events: [],
      lists: [{ id: "old", name: "Old", created: "2026-07-19T00:00:00Z" }],
      active: []
    } as any);
    render(Page);
    expect(await screen.findByRole("button", { name: "Delete Old" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete To-dos" })).toBeNull();
  });
});
