import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/svelte";
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
});
