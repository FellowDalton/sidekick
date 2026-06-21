import { describe, it, expect } from "vitest";
import { progress, dur, ago, hero, branchVMs, recentLog } from "./game";
import type { Feed } from "./types";

const ev = (over: Partial<import("./types").LedgerEvent> = {}) => ({
  task: "T", category: "chore", completed_at: "2026-06-10T00:00:00Z",
  sat_for_hours: 50, orchestrator: null, ...over
});

describe("progress (level curve)", () => {
  it("levels up with linearly rising cost", () => {
    // base 4, step 2: lvl1 costs 4, lvl2 costs 6, lvl3 costs 8...
    expect(progress(0, 4, 2).level).toBe(0);
    expect(progress(4, 4, 2).level).toBe(1);
    expect(progress(9, 4, 2).level).toBe(1);  // 4 used, need 6 more for lvl2
    expect(progress(10, 4, 2).level).toBe(2); // 4+6=10
    const p = progress(5, 4, 2);
    expect(p.into).toBe(1); expect(p.span).toBe(6); expect(p.toNext).toBe(5);
  });
});

describe("dur", () => {
  it("formats hours/days and null", () => {
    expect(dur(null)).toBe("—");
    expect(dur(5)).toBe("5h");
    expect(dur(48)).toBe("2d");
  });
});

describe("ago", () => {
  it("uses an injectable now", () => {
    const now = Date.parse("2026-06-10T05:00:00Z");
    expect(ago("2026-06-10T04:30:00Z", now)).toBe("just now");
    expect(ago("2026-06-10T02:00:00Z", now)).toBe("3h ago");
    expect(ago("2026-06-08T05:00:00Z", now)).toBe("2d ago");
  });
});

describe("hero", () => {
  it("derives overall level from event count (base 4, step 2)", () => {
    const feed: Feed = { events: Array.from({ length: 10 }, () => ev()), active: [] };
    const h = hero(feed);
    expect(h.total).toBe(10);
    expect(h.level).toBe(2);          // 4 + 6 = 10
    expect(h.word).toBe("Warmed up"); // LEVEL_WORDS[2]
  });
});

describe("branchVMs", () => {
  it("lights branches by predicate and counts", () => {
    const feed: Feed = {
      events: [
        ev({ category: "phone" }), ev({ category: "admin" }),  // diplomat x2
        ev({ category: "errand" }),                            // pathfinder x1
        ev({ orchestrator: "did research", category: "chore" }), // loremaster + hearthkeeper
        ev({ sat_for_hours: 1, category: "chore" })            // swift + hearthkeeper
      ],
      active: []
    };
    const vms = Object.fromEntries(branchVMs(feed).map(b => [b.key, b]));
    expect(vms.diplomat.count).toBe(2);
    expect(vms.diplomat.lit).toBe(true);
    expect(vms.pathfinder.count).toBe(1);
    expect(vms.loremaster.count).toBe(1);
    expect(vms.swift.count).toBe(1);
    expect(vms.hearthkeeper.count).toBe(2);
  });
  it("marks zero-count branches unlit with an invite", () => {
    const vms = Object.fromEntries(branchVMs({ events: [], active: [] }).map(b => [b.key, b]));
    expect(vms.swift.lit).toBe(false);
    expect(vms.swift.invite).toMatch(/couple of hours/i);
  });
});

describe("recentLog", () => {
  it("returns newest first, capped, with branch chips", () => {
    const feed: Feed = {
      events: [
        ev({ task: "old", completed_at: "2026-06-01T00:00:00Z", category: "phone" }),
        ev({ task: "new", completed_at: "2026-06-09T00:00:00Z", category: "errand" })
      ],
      active: []
    };
    const log = recentLog(feed, 7);
    expect(log[0].task).toBe("new");
    expect(log[0].chips.map(c => c.name)).toContain("Pathfinder");
    expect(log.length).toBe(2);
  });
});
