import type { LedgerEvent } from "./types";

/* Client-side mirror of sidekick.py compute_stats(): the PWA gets raw events from
   /feed (no stats key — that key only exists in the generated sidekick-data.js), so
   it derives the same aggregates itself, like everything else in $lib/game.ts.
   All calendar math is UTC — completed_at is stored as UTC ISO; a late evening in
   Copenhagen (UTC+1/+2) can bin to an earlier UTC hour / previous UTC day. Labeled
   "UTC" in the UI. KEEP DEFINITIONS IN LOCKSTEP with sidekick.py compute_stats. */

export interface Stats {
  total: number;
  byCategory: [string, number][];   // count desc, then name asc
  medianSatHours: number | null;
  byWeekday: number[];              // Mon..Sun, UTC (Python weekday() order)
  byHour: number[];                 // 00..23, UTC
  streakDays: number;
}

const DAY = 86400000;
const utcDay = (t: number) => Math.floor(t / DAY);

export function computeStats(events: LedgerEvent[], now: number = Date.now()): Stats {
  const byCat = new Map<string, number>();
  const sat: number[] = [];
  const byWeekday = new Array(7).fill(0);
  const byHour = new Array(24).fill(0);
  const days = new Set<number>();
  for (const e of events) {
    const cat = e.category || "uncategorized";
    byCat.set(cat, (byCat.get(cat) || 0) + 1);
    if (typeof e.sat_for_hours === "number") sat.push(e.sat_for_hours);
    const t = Date.parse(e.completed_at ?? "");
    if (!Number.isNaN(t)) {
      const d = new Date(t);
      byWeekday[(d.getUTCDay() + 6) % 7] += 1;   // JS Sunday-first -> Monday-first
      byHour[d.getUTCHours()] += 1;
      days.add(utcDay(t));
    }
  }
  // current streak: consecutive UTC days counted back from today, or from
  // yesterday when today is still empty (grace until the day is over).
  let streak = 0;
  let day = utcDay(now);
  if (!days.has(day)) day -= 1;
  while (days.has(day)) { streak += 1; day -= 1; }
  let median: number | null = null;
  if (sat.length) {
    const s = [...sat].sort((a, b) => a - b);
    const mid = s.length >> 1;
    median = s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
  }
  return {
    total: events.length,
    byCategory: [...byCat.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])),
    medianSatHours: median,
    byWeekday, byHour, streakDays: streak
  };
}

export const WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
