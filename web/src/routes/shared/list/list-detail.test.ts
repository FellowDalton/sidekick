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
  setTaskDescription: vi.fn(),
  startAgentJob: vi.fn(),
  getAgentJob: vi.fn(),
  ApiError: class extends Error {
    status: number;
    constructor(status: number, msg: string) { super(msg); this.status = status; }
  }
}));

import Page from "./[id]/+page.svelte";
import { getFeed, createTask, completeTask, setTaskDescription, startAgentJob, getAgentJob, ApiError } from "$lib/api";
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

  it("renders breakdown children in creation order, not newest-first", async () => {
    // feed order is creation order: c1 (step 1) before c2 (step 2) — the tree
    // must preserve that under the parent even though roots sort newest-first
    vi.mocked(getFeed).mockResolvedValue({
      events: [],
      lists: [{ id: "groceries", name: "Groceries", created: "2026-07-19T00:00:00Z" }],
      active: [
        { id: "p", task: "Plan the party", category: "chore", sat_for_hours: 5, plan: null, shared: true, status: "open", list: "groceries" },
        { id: "c1", task: "Step one", category: "chore", sat_for_hours: 2, plan: null, shared: true, parent: "p", status: "open" },
        { id: "c2", task: "Step two", category: "chore", sat_for_hours: 1, plan: null, shared: true, parent: "p", status: "open" }
      ]
    } as any);
    render(Page);
    const parentRow = (await screen.findByText("Plan the party")).closest("li")!;
    const children = parentRow.querySelectorAll(".children > li");
    expect(children.length).toBe(2);
    expect(children[0].textContent).toContain("Step one");
    expect(children[1].textContent).toContain("Step two");
  });

  it("shows list-not-found for an unknown id", async () => {
    vi.mocked(getFeed).mockResolvedValue({ events: [], lists: [], active: [] } as any);
    render(Page);   // param mock still says "groceries", which now doesn't exist
    expect(await screen.findByText(/list not found/i)).toBeInTheDocument();
  });
});

describe("list detail — task descriptions", () => {
  const feed = {
    events: [],
    lists: [{ id: "groceries", name: "Groceries", created: "2026-07-19T00:00:00Z" }],
    active: [
      { id: "p", task: "Plan the party", category: "chore", sat_for_hours: 5, plan: null, shared: true, status: "open", list: "groceries" },
      { id: "c2", task: "Order the cake", category: "chore", sat_for_hours: null, plan: null, shared: true, parent: "p", status: "done", completed_at: "2026-07-19T10:00:00Z" }
    ]
  };

  it("adds a task with details from the expanded textarea", async () => {
    vi.mocked(getFeed).mockResolvedValue(feed as any);
    vi.mocked(createTask).mockResolvedValue({ id: "n" } as any);
    render(Page);
    await screen.findByText("Plan the party");

    await fireEvent.click(screen.getByRole("button", { name: "+ details" }));
    await fireEvent.input(screen.getByLabelText("Details"), { target: { value: "  the details  " } });
    await fireEvent.input(screen.getByLabelText("New task"), { target: { value: "Buy candles" } });
    await fireEvent.submit(screen.getByLabelText("New task").closest("form")!);

    expect(createTask).toHaveBeenCalledWith("Buy candles", "chore", true, "groceries", "the details");
    await waitFor(() => expect(screen.queryByLabelText("Details")).toBeNull());   // collapsed after submit
  });

  it("shows a clamped description that expands on tap", async () => {
    vi.mocked(getFeed).mockResolvedValue({
      ...feed,
      active: [{ ...feed.active[0], description: "Some long details about the party plan." }]
    } as any);
    render(Page);
    await screen.findByText("Plan the party");

    const desc = screen.getByLabelText("Details for Plan the party");
    expect(desc.textContent).toContain("Some long details about the party plan.");
    expect(desc.className).not.toContain("expanded");

    await fireEvent.click(desc);
    expect(screen.getByLabelText("Details for Plan the party").className).toContain("expanded");
  });

  it("edits a description and saves optimistically", async () => {
    vi.mocked(getFeed).mockResolvedValue({
      ...feed,
      active: [{ ...feed.active[0], description: "Old details" }]
    } as any);
    let resolveSave!: (v: unknown) => void;
    const savePromise = new Promise((res) => { resolveSave = res; });
    vi.mocked(setTaskDescription).mockReturnValue(savePromise as any);

    render(Page);
    await screen.findByText("Plan the party");

    await fireEvent.click(screen.getByLabelText("Details for Plan the party"));
    await fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    const textarea = screen.getByLabelText("Edit details for Plan the party");
    await fireEvent.input(textarea, { target: { value: "New details" } });
    await fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(setTaskDescription).toHaveBeenCalledWith("p", "New details");
    expect(screen.getByLabelText("Details for Plan the party").textContent).toContain("New details");
    expect(getFeed).toHaveBeenCalledTimes(1);   // no reconcile yet

    resolveSave({ id: "p" });
    await waitFor(() => expect(getFeed).toHaveBeenCalledTimes(2));   // reconcile after save resolves
  });

  it("keeps the editor open with the typed text when the save fails", async () => {
    vi.mocked(getFeed).mockResolvedValue({
      ...feed,
      active: [{ ...feed.active[0], description: "Old details" }]
    } as any);
    vi.mocked(setTaskDescription).mockRejectedValue(new Error("couldn't reach the host"));

    render(Page);
    await screen.findByText("Plan the party");

    await fireEvent.click(screen.getByLabelText("Details for Plan the party"));
    await fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    const textarea = screen.getByLabelText("Edit details for Plan the party") as HTMLTextAreaElement;
    await fireEvent.input(textarea, { target: { value: "New details" } });
    await fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(screen.getByText("couldn't reach the host")).toBeInTheDocument());
    // the editor stays open — the user's typed text was never discarded
    expect(screen.getByLabelText("Edit details for Plan the party")).toHaveValue("New details");
    expect(screen.queryByLabelText("Details for Plan the party")).toBeNull();
  });

  it("does not render a description on a done row", async () => {
    vi.mocked(getFeed).mockResolvedValue({
      ...feed,
      active: [feed.active[0], { ...feed.active[1], description: "Cake details" }]
    } as any);
    render(Page);
    await screen.findByText("Plan the party");

    expect(screen.queryByLabelText("Details for Order the cake")).toBeNull();
  });
});

// Behaviors carried over (and adapted) from the old flat shared page's
// shared.test.ts (git show 70cb84c:web/src/routes/shared/shared.test.ts),
// which the detail view replaced. Route param mock is fixed to "groceries",
// so every fixture root below lives in that list.
describe("list detail — optimistic complete, rollback, breakdown polling", () => {
  const feed: Feed = {
    events: [],
    lists: [{ id: "groceries", name: "Groceries", created: "2026-07-19T00:00:00Z" }],
    active: [
      { id: "new", task: "New shared", category: "chore", sat_for_hours: 5, plan: null, from: "wife", shared: true, status: "open", list: "groceries" }
    ] as any
  };

  it("ticking a checkbox flips the row in place, then reconciles the feed", async () => {
    let resolveComplete!: (v: unknown) => void;
    const completePromise = new Promise((res) => { resolveComplete = res; });
    vi.mocked(getFeed).mockResolvedValue(feed);
    vi.mocked(completeTask).mockReturnValue(completePromise as any);

    render(Page);
    await screen.findByText("New shared");

    await fireEvent.click(screen.getByLabelText("Complete New shared"));
    await waitFor(() => expect(completeTask).toHaveBeenCalledWith("new", expect.any(String)));

    // in-place optimistic flip — happens before completeTask (and reload) resolve
    const box = screen.getByLabelText("New shared — done") as HTMLInputElement;
    expect(box.checked).toBe(true);
    expect(box.disabled).toBe(true);
    expect(getFeed).toHaveBeenCalledTimes(1);   // no reconcile yet

    resolveComplete({ id: "new", status: "done", completed_at: "T", sat_for_hours: 1, already_done: false });
    await waitFor(() => expect(getFeed).toHaveBeenCalledTimes(2));   // reconcile after complete resolves
  });

  it("rolls back the optimistic flip and shows an error when complete fails", async () => {
    vi.mocked(getFeed).mockResolvedValue(feed);
    vi.mocked(completeTask).mockRejectedValue(new Error("couldn't reach the host"));

    render(Page);
    await screen.findByText("New shared");

    await fireEvent.click(screen.getByLabelText("Complete New shared"));
    await waitFor(() => expect(screen.getByText("couldn't reach the host")).toBeInTheDocument());

    const box = screen.getByLabelText("Complete New shared") as HTMLInputElement;
    expect(box.checked).toBe(false);
    expect(box.disabled).toBe(false);
  });

  it("break it down starts a job and, once the poll reports done, shows the done chip", async () => {
    vi.mocked(getFeed).mockResolvedValue(feed);
    vi.mocked(startAgentJob).mockResolvedValue({
      id: "j1", task_id: "new", action: "breakdown", status: "queued",
      summary: null, error: null, log_tail: null,
      created_at: "T", started_at: null, finished_at: null
    } as any);
    vi.mocked(getAgentJob).mockResolvedValue({
      id: "j1", task_id: "new", action: "breakdown", status: "done",
      summary: "3 sub-tasks created", error: null, log_tail: null,
      created_at: "T", started_at: "T", finished_at: "T"
    } as any);

    render(Page);
    await screen.findByText("New shared");

    vi.useFakeTimers();
    await fireEvent.click(screen.getByLabelText("Break down New shared"));
    await vi.advanceTimersByTimeAsync(0);
    expect(startAgentJob).toHaveBeenCalledWith("new", "breakdown");

    await vi.advanceTimersByTimeAsync(5000);   // poll 1 → done
    vi.useRealTimers();
    await waitFor(() =>
      expect(screen.getByText("done — sub-tasks arrive in a few minutes")).toBeInTheDocument());
  });

  it("marks the chip failed (job lost) when the poll can't find the job", async () => {
    vi.mocked(getFeed).mockResolvedValue(feed);
    vi.mocked(startAgentJob).mockResolvedValue({
      id: "j1", task_id: "new", action: "breakdown", status: "queued",
      summary: null, error: null, log_tail: null,
      created_at: "T", started_at: null, finished_at: null
    } as any);
    vi.mocked(getAgentJob).mockRejectedValue(new ApiError(404, "not found"));

    render(Page);
    await screen.findByText("New shared");

    vi.useFakeTimers();
    await fireEvent.click(screen.getByLabelText("Break down New shared"));
    await vi.advanceTimersByTimeAsync(0);
    expect(startAgentJob).toHaveBeenCalledWith("new", "breakdown");

    await vi.advanceTimersByTimeAsync(5000);   // poll 1 → 404, marked job lost
    vi.useRealTimers();
    await waitFor(() => expect(screen.getByText("failed (job lost)")).toBeInTheDocument());
  });

  // The old shared.test.ts also asserted the flat page's list omitted non-shared
  // tasks — here that's "which list a shared task belongs to", covered above by
  // "shows only this list's roots" in the main describe block. A true "todos"-route
  // variant would need the "$app/state" route-param mock (fixed to "groceries" at
  // module-mock hoist time) to resolve to "todos" for one test only. vi.doMock +
  // vi.resetModules + a dynamic re-import of the page/api modules can do this in
  // Vitest, but it reinitializes the whole module graph for that test and risks
  // bleeding into the statically-imported `Page`/`getFeed` bindings used by every
  // other test in this file — not worth the fragility for one extra case, and the
  // component isn't being restructured just to make this easier to test.
  // Untestable with the current module-level route-param mock; the "todos" root-
  // scoping behavior is exercised indirectly by "shows only this list's roots,
  // with children nested inside" above (a "groceries" task is included, a
  // list-less/other task is excluded).
});
