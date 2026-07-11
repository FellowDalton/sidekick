import { describe, it, expect, vi, beforeEach } from "vitest";
import { get } from "svelte/store";

vi.mock("./api", () => ({ getMe: vi.fn() }));

import { identity, loadIdentity, resetIdentity } from "./role";
import { getMe } from "./api";

beforeEach(() => {
  vi.clearAllMocks();
  resetIdentity();
});

describe("identity store", () => {
  it("fetches /me and stores the identity", async () => {
    vi.mocked(getMe).mockResolvedValue({ name: "wife", role: "shared" });
    await loadIdentity("tok-1");
    expect(get(identity)).toEqual({ name: "wife", role: "shared" });
  });

  it("does not re-fetch for the same token", async () => {
    vi.mocked(getMe).mockResolvedValue({ name: "dalton", role: "full" });
    await loadIdentity("tok-1");
    await loadIdentity("tok-1");
    expect(getMe).toHaveBeenCalledTimes(1);
  });

  it("clears the identity when the token is empty", async () => {
    vi.mocked(getMe).mockResolvedValue({ name: "dalton", role: "full" });
    await loadIdentity("tok-1");
    await loadIdentity("");
    expect(get(identity)).toBeNull();
    expect(getMe).toHaveBeenCalledTimes(1);
  });

  it("nulls the identity on failure and retries on the next call", async () => {
    vi.mocked(getMe).mockRejectedValueOnce(new Error("down"));
    await loadIdentity("tok-1");
    expect(get(identity)).toBeNull();
    vi.mocked(getMe).mockResolvedValue({ name: "dalton", role: "full" });
    await loadIdentity("tok-1");
    expect(get(identity)).toEqual({ name: "dalton", role: "full" });
  });
});
