import { describe, it, expect, vi, beforeEach } from "vitest";
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
  startAgentJob: vi.fn(),
  getAgentJob: vi.fn(),
  ApiError: class extends Error {
    status: number;
    constructor(status: number, msg: string) { super(msg); this.status = status; }
  }
}));

import SharedPage from "./+page.svelte";
import { getFeed, createTask, completeTask, startAgentJob } from "$lib/api";

const feed: Feed = {
  events: [],
  active: [
    { id: "old", task: "Old shared", category: "chore", sat_for_hours: 50, plan: null, from: "dalton", shared: true },
    { id: "personal", task: "Personal thing", category: "admin", sat_for_hours: 10, plan: null, from: "dalton", shared: false },
    { id: "new", task: "New shared", category: "chore", sat_for_hours: 5, plan: null, from: "wife", shared: true }
  ]
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getFeed).mockResolvedValue(feed);
});

describe("Shared list", () => {
  it("shows only shared tasks, newest first", async () => {
    render(SharedPage);
    await waitFor(() => expect(screen.getByText("New shared")).toBeInTheDocument());
    expect(screen.queryByText("Personal thing")).toBeNull();
    const items = screen.getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("New shared");
    expect(items[1]).toHaveTextContent("Old shared");
  });

  it("adds a task from the box as a shared chore and reloads", async () => {
    render(SharedPage);
    await waitFor(() => expect(getFeed).toHaveBeenCalled());
    await fireEvent.input(screen.getByLabelText(/new shared task/i), { target: { value: "Buy milk" } });
    await fireEvent.click(screen.getByRole("button", { name: /add/i }));
    await waitFor(() => expect(createTask).toHaveBeenCalledWith("Buy milk", "chore", true));
    await waitFor(() => expect(getFeed).toHaveBeenCalledTimes(2));
  });

  it("ticking a checkbox completes the task and removes it", async () => {
    const feedAfterComplete: Feed = {
      events: [],
      active: [
        { id: "old", task: "Old shared", category: "chore", sat_for_hours: 50, plan: null, from: "dalton", shared: true },
        { id: "personal", task: "Personal thing", category: "admin", sat_for_hours: 10, plan: null, from: "dalton", shared: false }
      ]
    };

    // On first call (mount), return original feed; on second call (after tick), return feed without the completed item
    vi.mocked(getFeed).mockResolvedValueOnce(feed).mockResolvedValueOnce(feedAfterComplete);

    render(SharedPage);
    await waitFor(() => expect(screen.getByText("New shared")).toBeInTheDocument());

    await fireEvent.click(screen.getByRole("checkbox", { name: /complete new shared/i }));
    await waitFor(() => expect(completeTask).toHaveBeenCalledWith("new", expect.any(String)));
    expect(screen.queryByText("New shared")).toBeNull();
  });

  it("after a successful tick, reconciles feed (fetches new items from other person)", async () => {
    const feedAfterComplete: Feed = {
      events: [],
      active: [
        { id: "old", task: "Old shared", category: "chore", sat_for_hours: 50, plan: null, from: "dalton", shared: true },
        { id: "personal", task: "Personal thing", category: "admin", sat_for_hours: 10, plan: null, from: "dalton", shared: false },
        { id: "wife-added", task: "Wife just added this", category: "chore", sat_for_hours: 2, plan: null, from: "wife", shared: true }
      ]
    };

    // On first call (mount), return original feed; on second call (after tick), return feed with new item from other person
    vi.mocked(getFeed).mockResolvedValueOnce(feed).mockResolvedValueOnce(feedAfterComplete);

    render(SharedPage);
    await waitFor(() => expect(screen.getByText("New shared")).toBeInTheDocument());
    expect(screen.queryByText("Wife just added this")).toBeNull();

    await fireEvent.click(screen.getByRole("checkbox", { name: /complete new shared/i }));
    await waitFor(() => expect(getFeed).toHaveBeenCalledTimes(2));
    expect(screen.queryByText("New shared")).toBeNull();
    expect(screen.getByText("Wife just added this")).toBeInTheDocument();
  });

  it("break it down starts a breakdown job and shows the chip", async () => {
    vi.mocked(startAgentJob).mockResolvedValue({
      id: "j1", task_id: "new", action: "breakdown", status: "queued",
      summary: null, error: null, log_tail: null,
      created_at: "T", started_at: null, finished_at: null
    } as any);
    render(SharedPage);
    await waitFor(() => expect(screen.getByText("New shared")).toBeInTheDocument());
    await fireEvent.click(screen.getByRole("button", { name: /break down new shared/i }));
    await waitFor(() => expect(startAgentJob).toHaveBeenCalledWith("new", "breakdown"));
    expect(screen.getByText("queued")).toBeInTheDocument();
  });
});
