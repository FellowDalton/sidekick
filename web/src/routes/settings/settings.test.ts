import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/svelte";
import { get } from "svelte/store";
import Settings from "./+page.svelte";
import { settings } from "$lib/settings";

beforeEach(() => settings.set({ token: "", apiBase: "" }));

describe("Settings", () => {
  it("writes the entered token into the settings store", async () => {
    render(Settings);
    await fireEvent.input(screen.getByLabelText(/token/i), { target: { value: "secret-123" } });
    expect(get(settings).token).toBe("secret-123");
  });

  it("prefills from the existing settings", () => {
    settings.set({ token: "abc", apiBase: "" });
    render(Settings);
    expect((screen.getByLabelText(/token/i) as HTMLInputElement).value).toBe("abc");
  });
});
