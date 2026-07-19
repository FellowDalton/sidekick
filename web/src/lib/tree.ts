// Pure tree-builder for nested sub-tasks (spec 2026-07-19). Shared by the
// dashboard and the shared list; rendering stays per-route.
import type { ActiveTask } from "./types";

export interface TreeNode { task: ActiveTask; children: TreeNode[]; }

export function buildTree(tasks: ActiveTask[]): TreeNode[] {
  const byId = new Map(tasks.map(t => [t.id, t]));
  const parentOf = (t: ActiveTask): string | null =>
    t.parent && byId.has(t.parent) ? t.parent : null;
  // cycle guard: bad data degrades to top-level cards, never infinite recursion
  const cyclic = (t: ActiveTask): boolean => {
    const seen = new Set([t.id]);
    for (let p = parentOf(t); p; p = parentOf(byId.get(p)!)) {
      if (seen.has(p)) return true;
      seen.add(p);
    }
    return false;
  };
  const nodes = new Map(tasks.map(t => [t.id, { task: t, children: [] as TreeNode[] }]));
  const roots: TreeNode[] = [];
  for (const t of tasks) {
    const p = cyclic(t) ? null : parentOf(t);
    if (p) nodes.get(p)!.children.push(nodes.get(t.id)!);
    else roots.push(nodes.get(t.id)!);
  }
  return roots;
}

export function doneCount(n: TreeNode): { done: number; total: number } {
  return {
    done: n.children.filter(c => c.task.status === "done").length,
    total: n.children.length,
  };
}

export function showNudge(n: TreeNode): boolean {
  const { done, total } = doneCount(n);
  return n.task.status !== "done" && total > 0 && done === total;
}
