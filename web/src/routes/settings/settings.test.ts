import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/svelte";
import { get } from "svelte/store";
import Settings from "./+page.svelte";
import { settings } from "$lib/settings";
import { enablePush } from "$lib/push";

vi.mock("$lib/push", () => ({
  enablePush: vi.fn(async () => "enabled" as const)
}));

beforeEach(() => {
  settings.set({ token: "", apiBase: "" });
  vi.mocked(enablePush).mockClear();
  vi.mocked(enablePush).mockResolvedValue("enabled");
});

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

describe("Settings — notifications", () => {
  it("runs the enable-push flow from the button (the user gesture)", async () => {
    render(Settings);
    await fireEvent.click(screen.getByRole("button", { name: /enable notifications/i }));
    expect(enablePush).toHaveBeenCalledOnce();
    expect(await screen.findByText(/notifications enabled/i)).toBeInTheDocument();
  });

  it("explains a denied permission", async () => {
    vi.mocked(enablePush).mockResolvedValue("denied");
    render(Settings);
    await fireEvent.click(screen.getByRole("button", { name: /enable notifications/i }));
    expect(await screen.findByText(/permission denied/i)).toBeInTheDocument();
  });

  it("explains unsupported browsers (iOS Safari outside the installed app)", async () => {
    vi.mocked(enablePush).mockResolvedValue("unsupported");
    render(Settings);
    await fireEvent.click(screen.getByRole("button", { name: /enable notifications/i }));
    expect(await screen.findByText(/home screen/i)).toBeInTheDocument();
  });
});
