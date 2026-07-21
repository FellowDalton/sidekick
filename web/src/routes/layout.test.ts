import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/svelte";
import { createRawSnippet } from "svelte";

vi.mock("$app/stores", async () => {
  const { writable } = await import("svelte/store");
  return { page: writable({ url: new URL("http://localhost/") }) };
});
vi.mock("$app/navigation", () => ({ goto: vi.fn() }));
vi.mock("$lib/role", async () => {
  const { writable } = await import("svelte/store");
  return { identity: writable(null), loadIdentity: vi.fn() };
});

import Layout from "./+layout.svelte";
import { page } from "$app/stores";
import { goto } from "$app/navigation";
import { identity } from "$lib/role";

const setPage = (path: string) =>
  (page as any).set({ url: new URL(`http://localhost${path}`) });

function renderLayout() {
  const children = createRawSnippet(() => ({ render: () => "<main>content</main>" }));
  return render(Layout, { props: { children } });
}

beforeEach(() => {
  vi.mocked(goto).mockClear();
  identity.set(null);
  setPage("/");
});

describe("role-aware layout", () => {
  it("shows the full nav plus a Shared link for role full", () => {
    identity.set({ name: "dalton", role: "full" });
    renderLayout();
    expect(screen.getByRole("link", { name: "Dashboard" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "New" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Shared" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Settings" })).toBeInTheDocument();
  });

  it("shows only Shared + Settings for role shared", () => {
    identity.set({ name: "wife", role: "shared" });
    setPage("/shared");
    renderLayout();
    expect(screen.queryByRole("link", { name: "Dashboard" })).toBeNull();
    expect(screen.queryByRole("link", { name: "New" })).toBeNull();
    expect(screen.getByRole("link", { name: "Shared" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Settings" })).toBeInTheDocument();
  });

  it("redirects role shared away from every other route", async () => {
    identity.set({ name: "wife", role: "shared" });
    setPage("/");
    renderLayout();
    await waitFor(() => expect(goto).toHaveBeenCalledWith("/shared"));
  });

  it("leaves role shared alone on /settings", async () => {
    identity.set({ name: "wife", role: "shared" });
    setPage("/settings");
    renderLayout();
    await new Promise((r) => setTimeout(r, 0));   // let effects flush
    expect(goto).not.toHaveBeenCalled();
  });

  it("leaves role shared alone on a list detail page", async () => {
    identity.set({ name: "wife", role: "shared" });
    setPage("/shared/list/groceries");
    renderLayout();
    await new Promise((r) => setTimeout(r, 0));   // let effects flush
    expect(goto).not.toHaveBeenCalled();
  });

  it("registers the service worker on mount when the API exists", async () => {
    const register = vi.fn(async () => ({}));
    Object.defineProperty(navigator, "serviceWorker", {
      configurable: true, value: { register }
    });
    renderLayout();
    await waitFor(() => expect(register).toHaveBeenCalledWith("/sw.js"));
    delete (navigator as any).serviceWorker;
  });

  it("shows only Settings while the role is still unresolved", () => {
    // identity is null (beforeEach): an unknown role must not surface the
    // dashboard nav — role shared would see it flash before /me resolves
    renderLayout();
    expect(screen.queryByRole("link", { name: "Dashboard" })).toBeNull();
    expect(screen.queryByRole("link", { name: "New" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Shared" })).toBeNull();
    expect(screen.getByRole("link", { name: "Settings" })).toBeInTheDocument();
  });
});
