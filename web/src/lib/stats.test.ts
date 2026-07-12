import { describe, it, expect } from "vitest";
import { computeStats } from "./stats";
import type { LedgerEvent } from "./types";

const ev = (over: Partial<LedgerEvent> = {}): LedgerEvent => ({
  task: "T", category: "chore", completed_at: "2026-06-10T21:30:00Z",
  sat_for_hours: 50, orchestrator: null, ...over
});

describe("computeStats", () => {
  it("counts categories, treating null as uncategorized", () => {
    const s = computeStats([ev(), ev({ category: "phone" }), ev({ category: null })]);
    expect(Object.fromEntries(s.byCategory)).toEqual({ chore: 1, phone: 1, uncategorized: 1 });
    expect(s.total).toBe(3);
  });

  it("orders byCategory by count desc, then name", () => {
    const s = computeStats([ev({ category: "phone" }), ev({ category: "phone" }), ev()]);
    expect(s.byCategory[0]).toEqual(["phone", 2]);
  });

  it("takes the median of sat_for_hours, ignoring nulls, averaging even counts", () => {
    expect(computeStats([ev({ sat_for_hours: 1 }), ev({ sat_for_hours: 100 }),
      ev({ sat_for_hours: 3 }), ev({ sat_for_hours: null })]).medianSatHours).toBe(3);
    expect(computeStats([1, 2, 3, 4].map(h => ev({ sat_for_hours: h }))).medianSatHours).toBe(2.5);
    expect(computeStats([ev({ sat_for_hours: null })]).medianSatHours).toBeNull();
  });

  it("bins weekday (Mon-first, like Python) and hour in UTC", () => {
    // 2026-06-10T21:30Z is a Wednesday
    const s = computeStats([ev()]);
    expect(s.byWeekday).toEqual([0, 0, 1, 0, 0, 0, 0]);
    expect(s.byHour[21]).toBe(1);
    expect(s.byHour.reduce((a, b) => a + b)).toBe(1);
  });

  it("computes the streak with injectable now; empty today doesn't break it", () => {
    const now = Date.parse("2026-06-10T12:00:00Z");
    const on = (d: string) => ev({ completed_at: `${d}T10:00:00Z` });
    expect(computeStats([on("2026-06-10"), on("2026-06-09"), on("2026-06-08")], now).streakDays).toBe(3);
    expect(computeStats([on("2026-06-09"), on("2026-06-08")], now).streakDays).toBe(2);
    expect(computeStats([on("2026-06-10"), on("2026-06-08")], now).streakDays).toBe(1);
    expect(computeStats([on("2026-06-01")], now).streakDays).toBe(0);
  });

  it("tolerates pre-learning-layer events without crashing", () => {
    const legacy = { task: "old", category: null, completed_at: "not-a-date",
                     sat_for_hours: null } as LedgerEvent;
    const s = computeStats([legacy]);
    expect(s.total).toBe(1);
    expect(s.byWeekday.reduce((a, b) => a + b)).toBe(0);
    expect(s.streakDays).toBe(0);
  });
});
