import type { Feed, LedgerEvent, Category } from "./types";

export interface Branch {
  key: string; name: string; hue: string;
  test: (e: LedgerEvent) => boolean; invite: string;
}

export const BRANCHES: Branch[] = [
  { key: "diplomat",     name: "Diplomat",     hue: "var(--h-diplomat)",     test: e => e.category === "phone" || e.category === "admin", invite: "Untapped — clear a call or an admin task." },
  { key: "pathfinder",   name: "Pathfinder",   hue: "var(--h-pathfinder)",   test: e => e.category === "errand",                          invite: "Untapped — run an errand." },
  { key: "hearthkeeper", name: "Hearthkeeper", hue: "var(--h-hearthkeeper)", test: e => e.category === "chore",                           invite: "Untapped — knock out a chore." },
  { key: "loremaster",   name: "Loremaster",   hue: "var(--h-loremaster)",   test: e => !!e.orchestrator,                                 invite: "Untapped — let the orchestrator take one on." },
  { key: "swift",        name: "Swift",        hue: "var(--h-swift)",        test: e => e.sat_for_hours != null && e.sat_for_hours <= 2,  invite: "Untapped — clear one within a couple of hours." }
];

export const CAT_HUE: Record<string, string> = {
  phone: "var(--h-diplomat)", admin: "var(--h-diplomat)",
  errand: "var(--h-pathfinder)", chore: "var(--h-hearthkeeper)"
};

const OVERALL_CURVE = { base: 4, step: 2 };
const BRANCH_CURVE = { base: 2, step: 1 };
const LEVEL_WORDS = ["Getting started","Finding the rhythm","Warmed up","In the swing","Hitting stride","On a roll","Dialled in","Unstoppable"];

export interface Progress { level: number; into: number; span: number; toNext: number; pct: number; }
export function progress(count: number, base: number, step: number): Progress {
  let lvl = 0, used = 0, cost = base;
  while (used + cost <= count) { used += cost; lvl++; cost = base + step * lvl; }
  const into = count - used, span = cost;
  return { level: lvl, into, span, toNext: span - into, pct: span ? into / span : 0 };
}

export const catHue = (c: string) => CAT_HUE[c] || "var(--line)";
export const fmtDate = (iso: string) => new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
export const dur = (h: number | null) => h == null ? "—" : (h < 24 ? Math.round(h) + "h" : Math.round(h / 24) + "d");
export function ago(iso: string, now: number = Date.now()): string {
  const h = (now - new Date(iso).getTime()) / 36e5;
  if (h < 1) return "just now";
  if (h < 24) return Math.round(h) + "h ago";
  return Math.round(h / 24) + "d ago";
}

export interface Hero { level: number; word: string; total: number; toNext: number; pct: number; }
export function hero(feed: Feed): Hero {
  const total = feed.events.length;
  const p = progress(total, OVERALL_CURVE.base, OVERALL_CURVE.step);
  return { level: p.level, word: LEVEL_WORDS[Math.min(p.level, LEVEL_WORDS.length - 1)], total, toNext: p.toNext, pct: p.pct };
}

export interface BranchVM {
  key: string; name: string; hue: string; invite: string;
  lit: boolean; level: number; into: number; span: number; pct: number; count: number;
}
export function branchVMs(feed: Feed): BranchVM[] {
  return BRANCHES.map(b => {
    const count = feed.events.filter(b.test).length;
    const p = progress(count, BRANCH_CURVE.base, BRANCH_CURVE.step);
    return { key: b.key, name: b.name, hue: b.hue, invite: b.invite,
      lit: count > 0, level: p.level, into: p.into, span: p.span, pct: p.pct, count };
  });
}

export interface LogRow { task: string; chips: { name: string; hue: string }[]; when: string; }
export function recentLog(feed: Feed, limit = 7, now: number = Date.now()): LogRow[] {
  return [...feed.events]
    .sort((a, b) => new Date(b.completed_at).getTime() - new Date(a.completed_at).getTime())
    .slice(0, limit)
    .map(e => ({
      task: e.task,
      chips: BRANCHES.filter(b => b.test(e)).map(b => ({ name: b.name, hue: b.hue })),
      when: ago(e.completed_at, now)
    }));
}

export type { Category };
