import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/svelte";
import type { Feed } from "$lib/types";

vi.mock("$app/navigation", () => ({ goto: vi.fn() }));
vi.mock("$lib/settings", () => ({ hasToken: () => true }));
vi.mock("$lib/api", () => ({
  getFeed: vi.fn(),
  completeTask: vi.fn(),
  startAgentJob: vi.fn(),
  getAgentJob: vi.fn(),
  ApiError: class extends Error {
    status: number;
    constructor(status: number, msg: string) { super(msg); this.status = status; }
  }
}));

import Page from "./+page.svelte";
import { getFeed, startAgentJob, getAgentJob } from "$lib/api";

const feed: Feed = {
  events: [],
  active: [{ id: "t1", task: "Replace fan", category: "chore", sat_for_hours: 12, plan: null }]
};

const job = (status: string, summary: string | null = null) => ({
  id: "j1", task_id: "t1", action: "research", status, summary,
  error: null, log_tail: null, created_at: "T", started_at: null, finished_at: null
});

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getFeed).mockResolvedValue(feed);
});
afterEach(() => vi.useRealTimers());

describe("Ask Sidekick (dashboard route)", () => {
  it("starts a research job and polls it to done every 5s", async () => {
    vi.mocked(startAgentJob).mockResolvedValue(job("queued") as any);
    vi.mocked(getAgentJob)
      .mockResolvedValueOnce(job("running") as any)
      .mockResolvedValueOnce(job("done", "plan set: buy the fan") as any);

    render(Page);
    await waitFor(() => expect(screen.getByText("Replace fan")).toBeInTheDocument());

    vi.useFakeTimers();
    await fireEvent.click(screen.getByRole("button", { name: /ask sidekick about replace fan/i }));
    await vi.advanceTimersByTimeAsync(0);               // let the POST resolve
    expect(startAgentJob).toHaveBeenCalledWith("t1", "research");

    await vi.advanceTimersByTimeAsync(5000);            // poll 1 → running
    expect(getAgentJob).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(5000);            // poll 2 → done + feed reload
    expect(getAgentJob).toHaveBeenCalledTimes(2);
    expect(getFeed).toHaveBeenCalledTimes(2);           // mount + reload on done
    vi.useRealTimers();
    await waitFor(() => expect(screen.getByText(/done — plan set: buy the fan/i)).toBeInTheDocument());
  });

  it("surfaces an error when the job cannot start", async () => {
    vi.mocked(startAgentJob).mockRejectedValue(new Error("agent runner not configured"));
    render(Page);
    await waitFor(() => expect(screen.getByText("Replace fan")).toBeInTheDocument());
    await fireEvent.click(screen.getByRole("button", { name: /ask sidekick/i }));
    await waitFor(() => expect(screen.getByText(/agent runner not configured/i)).toBeInTheDocument());
  });
});
