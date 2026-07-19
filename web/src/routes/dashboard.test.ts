import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/svelte";
import Dashboard from "./Dashboard.svelte";
import type { Feed } from "$lib/types";

const feed: Feed = {
  events: [
    { task: "Called dentist", category: "phone", completed_at: "2026-06-09T00:00:00Z", sat_for_hours: 5, orchestrator: null },
    { task: "Ran errand", category: "errand", completed_at: "2026-06-08T00:00:00Z", sat_for_hours: 30, orchestrator: null }
  ],
  active: [
    { id: "t1", task: "Replace fan", category: "chore", sat_for_hours: 120,
      plan: { summary: "Three quotes compared.", steps: [{ text: "Call the electrician", href: "tel:+4500" }, { text: "Book a slot" }] } },
    { id: "t2", task: "Email landlord", category: "admin", sat_for_hours: 10, plan: null }
  ]
};

describe("Dashboard", () => {
  it("renders the level, open tasks, branches, and log from a feed", () => {
    const { container } = render(Dashboard, { props: { feed } });
    // hero: 2 events -> level 0 (need 4 for level 1)
    expect(screen.getByText("Getting started")).toBeInTheDocument();
    expect(container.querySelector(".stats")?.textContent).toContain("2 tasks cleared");
    // open tasks
    expect(screen.getByText("Replace fan")).toBeInTheDocument();
    expect(screen.getByText("Email landlord")).toBeInTheDocument();
    expect(screen.getByText("Call the electrician")).toBeInTheDocument();
    expect(screen.getByText(/No plan yet/i)).toBeInTheDocument();
    // a branch + a log row
    expect(screen.getByText("Diplomat")).toBeInTheDocument();
    expect(screen.getByText("Called dentist")).toBeInTheDocument();
  });

  it("does not render a javascript: href as a link (XSS guard)", () => {
    const evil = {
      events: [],
      active: [{ id: "x", task: "Evil", category: "chore", sat_for_hours: 1,
        plan: { summary: "s", steps: [{ text: "click me", href: "javascript:alert(1)" }] } }]
    };
    render(Dashboard, { props: { feed: evil as any } });
    expect(screen.getByText("click me").closest("a")).toBeNull(); // plain text, not an anchor
  });

  it("renders the patterns panel computed from events", () => {
    const { container } = render(Dashboard, { props: { feed } });
    expect(screen.getByText("Patterns")).toBeInTheDocument();
    const panel = container.querySelector(".patterns");
    expect(panel?.textContent).toContain("phone 1");
    expect(panel?.textContent).toContain("consecutive days");
  });
});

describe("Ask Sidekick", () => {
  const job = (status: string, summary: string | null = null) => ({
    id: "j1", task_id: "t2", action: "research", status, summary,
    error: null, log_tail: null, created_at: "T", started_at: null, finished_at: null
  });

  it("fires onAgent with the task id", async () => {
    const onAgent = vi.fn();
    render(Dashboard, { props: { feed, onAgent } });
    await fireEvent.click(screen.getByRole("button", { name: /ask sidekick about replace fan/i }));
    expect(onAgent).toHaveBeenCalledWith("t1");
  });

  it("shows the status chip and disables only the busy task's button", () => {
    render(Dashboard, { props: { feed, agentJobs: { t2: job("running") } as any } });
    expect(screen.getByText("running")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /ask sidekick about email landlord/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /ask sidekick about replace fan/i })).toBeEnabled();
  });

  it("shows the summary on a done job", () => {
    render(Dashboard, { props: { feed, agentJobs: { t2: job("done", "plan set") } as any } });
    expect(screen.getByText("done — plan set")).toBeInTheDocument();
  });
});

describe("Dashboard descriptions", () => {
  const withDesc: Feed = {
    events: [],
    active: [
      { id: "t1", task: "Replace fan", category: "chore", sat_for_hours: 120, plan: null,
        description: "Get three quotes from local electricians before booking anyone." }
    ]
  };

  it("renders a clamped description on a card and expands on tap", async () => {
    const { container } = render(Dashboard, { props: { feed: withDesc } });
    const desc = screen.getByLabelText("Details for Replace fan");
    expect(desc.textContent).toContain("Get three quotes");
    expect(desc.className).not.toContain("expanded");
    await fireEvent.click(desc);
    expect(container.querySelector(".desc-text.expanded, [aria-label='Details for Replace fan'].expanded")).toBeTruthy();
  });

  it("calls onDescribe with the edited text on Save and closes the editor on success", async () => {
    const onDescribe = vi.fn().mockResolvedValue(true);
    render(Dashboard, { props: { feed: withDesc, onDescribe } });
    await fireEvent.click(screen.getByLabelText("Details for Replace fan"));
    await fireEvent.click(screen.getByText("Edit"));
    const textarea = screen.getByLabelText("Edit details for Replace fan");
    await fireEvent.input(textarea, { target: { value: "Updated details here." } });
    await fireEvent.click(screen.getByText("Save"));
    expect(onDescribe).toHaveBeenCalledWith("t1", "Updated details here.");
    await waitFor(() => expect(screen.queryByLabelText("Edit details for Replace fan")).toBeNull());
  });

  it("keeps the editor open with the typed text when the save fails", async () => {
    const onDescribe = vi.fn().mockResolvedValue(false);
    render(Dashboard, { props: { feed: withDesc, onDescribe } });
    await fireEvent.click(screen.getByLabelText("Details for Replace fan"));
    await fireEvent.click(screen.getByText("Edit"));
    const textarea = screen.getByLabelText("Edit details for Replace fan");
    await fireEvent.input(textarea, { target: { value: "Updated details here." } });
    await fireEvent.click(screen.getByText("Save"));
    await waitFor(() => expect(onDescribe).toHaveBeenCalledWith("t1", "Updated details here."));
    // the editor stays open — the user's typed text was never discarded
    expect(screen.getByLabelText("Edit details for Replace fan")).toHaveValue("Updated details here.");
  });

  it("does not render a description on a done child card", () => {
    const nested: Feed = {
      events: [],
      active: [
        { id: "p", task: "Plan the party", category: "chore", sat_for_hours: 5, plan: null, status: "open" },
        { id: "c1", task: "Order the cake", category: "chore", sat_for_hours: null, plan: null,
          parent: "p", status: "done", completed_at: "2026-07-19T10:00:00Z", description: "Chocolate, three tiers." }
      ]
    };
    render(Dashboard, { props: { feed: nested } });
    expect(screen.queryByText("Chocolate, three tiers.")).toBeNull();
    expect(screen.queryByLabelText("Details for Order the cake")).toBeNull();
  });
});

describe("Dashboard nested sub-tasks", () => {
  const nested: Feed = {
    events: [],
    active: [
      { id: "p", task: "Plan the party", category: "chore", sat_for_hours: 5,
        plan: { summary: "Broken into 2 sub-tasks", steps: [{ text: "Book the venue — [[c1]]" }, { text: "Order the cake — [[c2]]" }] },
        status: "open" },
      { id: "c1", task: "Book the venue", category: "chore", sat_for_hours: 2, plan: null, parent: "p", status: "open" },
      { id: "c2", task: "Order the cake", category: "chore", sat_for_hours: null, plan: null, parent: "p", status: "done", completed_at: "2026-07-19T10:00:00Z" }
    ]
  };

  it("nests child cards inside the parent card, not as top-level cards", () => {
    const { container } = render(Dashboard, { props: { feed: nested } });
    const parentCard = screen.getByText("Plan the party").closest("article")!;
    expect(parentCard.querySelector(".children")).toBeTruthy();
    // children live inside the parent's card
    expect(parentCard.textContent).toContain("Book the venue");
    // and only the parent is a top-level card
    const section = parentCard.parentElement!;
    expect(section.querySelectorAll(":scope > article").length).toBe(1);
  });

  it("renders a done child struck-through without buttons", () => {
    render(Dashboard, { props: { feed: nested } });
    const done = screen.getByText("Order the cake").closest("article")!;
    expect(done.classList.contains("done-card")).toBe(true);
    expect(done.querySelector("button")).toBeNull();
  });

  it("counts only open tasks in the header and nudges when all children are done", () => {
    const allDone: Feed = {
      events: [],
      active: [
        { id: "p", task: "Plan the party", category: "chore", sat_for_hours: 5, plan: null, status: "open" },
        { id: "c1", task: "Book the venue", category: "chore", sat_for_hours: null, plan: null, parent: "p", status: "done", completed_at: "2026-07-19T10:00:00Z" }
      ]
    };
    render(Dashboard, { props: { feed: allDone } });
    expect(screen.getByText("1 open")).toBeInTheDocument();
    expect(screen.getByText("1/1 done — finish it?")).toBeInTheDocument();
  });
});
