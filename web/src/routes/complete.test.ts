import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/svelte";
import Dashboard from "./Dashboard.svelte";
import type { Feed } from "$lib/types";

const feed: Feed = {
  events: [],
  active: [{ id: "t1", task: "Pay rent", category: "admin", sat_for_hours: 10, plan: null }]
};

describe("Complete button", () => {
  it("calls onComplete with the task id when Done is clicked", async () => {
    const onComplete = vi.fn();
    render(Dashboard, { props: { feed, onComplete } });
    await fireEvent.click(screen.getByRole("button", { name: /done/i }));
    await waitFor(() => expect(onComplete).toHaveBeenCalledWith("t1"));
  });

  it("disables the button when the task id is pending", () => {
    render(Dashboard, { props: { feed, pending: new Set(["t1"]) } });
    expect(screen.getByRole("button", { name: /done/i })).toBeDisabled();
  });
});
