import { describe, it, expect } from "vitest";
import { buildTree, doneCount, showNudge, type TreeNode } from "./tree";
import type { ActiveTask } from "./types";

const t = (id: string, over: Partial<ActiveTask> = {}): ActiveTask =>
  ({ id, task: id, category: "chore", sat_for_hours: 1, plan: null, status: "open", ...over });

describe("buildTree", () => {
  it("nests children under parents, recursively, preserving order", () => {
    const tree = buildTree([t("a"), t("b", { parent: "a" }), t("c", { parent: "b" }), t("d")]);
    expect(tree.map(n => n.task.id)).toEqual(["a", "d"]);
    expect(tree[0].children.map(n => n.task.id)).toEqual(["b"]);
    expect(tree[0].children[0].children.map(n => n.task.id)).toEqual(["c"]);
  });

  it("promotes orphans (parent not in the visible set) to top level", () => {
    const tree = buildTree([t("b", { parent: "gone" })]);
    expect(tree.map(n => n.task.id)).toEqual(["b"]);
  });

  it("breaks parent cycles instead of recursing forever", () => {
    const tree = buildTree([t("a", { parent: "b" }), t("b", { parent: "a" })]);
    expect(tree.map(n => n.task.id).sort()).toEqual(["a", "b"]);
    expect(tree.every(n => n.children.length === 0)).toBe(true);
  });

  it("keeps done children nested under their open parent", () => {
    const tree = buildTree([t("a"), t("b", { parent: "a", status: "done" })]);
    expect(tree[0].children[0].task.status).toBe("done");
  });
});

describe("doneCount / showNudge", () => {
  const forest = buildTree([
    t("p"),
    t("c1", { parent: "p", status: "done" }),
    t("c2", { parent: "p", status: "done" }),
    t("g", { parent: "c2" }),   // grandchild must NOT count toward p's nudge
  ]);
  const p = forest[0];

  it("counts direct children only", () => {
    expect(doneCount(p)).toEqual({ done: 2, total: 2 });
  });

  it("nudges an open parent whose direct children are all done", () => {
    expect(showNudge(p)).toBe(true);
  });

  it("never nudges leaves or parents with open children", () => {
    const open = buildTree([t("p"), t("c", { parent: "p" })]);
    expect(showNudge(open[0])).toBe(false);
    expect(showNudge(buildTree([t("solo")])[0])).toBe(false);
  });
});
