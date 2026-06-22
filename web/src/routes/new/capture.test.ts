import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/svelte";

vi.mock("$app/navigation", () => ({ goto: vi.fn() }));
vi.mock("$lib/api", () => ({ createTask: vi.fn(async () => ({ id: "new1" })), ApiError: class extends Error {} }));

import Capture from "./+page.svelte";
import { createTask } from "$lib/api";
import { goto } from "$app/navigation";

beforeEach(() => { vi.clearAllMocks(); });

describe("Capture", () => {
  it("creates a task and navigates home", async () => {
    render(Capture);
    await fireEvent.input(screen.getByLabelText(/title/i), { target: { value: "Book MOT" } });
    await fireEvent.change(screen.getByLabelText(/category/i), { target: { value: "errand" } });
    await fireEvent.click(screen.getByRole("button", { name: /capture/i }));
    await waitFor(() => expect(createTask).toHaveBeenCalledWith("Book MOT", "errand"));
    await waitFor(() => expect(goto).toHaveBeenCalledWith("/"));
  });

  it("does not submit an empty title", async () => {
    render(Capture);
    await fireEvent.click(screen.getByRole("button", { name: /capture/i }));
    expect(createTask).not.toHaveBeenCalled();
  });
});
