# Nested Sub-tasks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render broken-down tasks as a parent card with its sub-tasks nested beneath it (recursively) in both the dashboard view and the shared list, driven by an authoritative `parent:` frontmatter field.

**Architecture:** `sidekick.py new` grows `--parent <id>` which writes `parent:` into child frontmatter; the feed exposes `parent`/`status` and includes completed children while their parent is still open; a pure TypeScript tree-builder (`web/src/lib/tree.ts`) turns the flat active list into a forest; each route renders it with a recursive Svelte 5 snippet keeping its own card/row styling. No server permission changes; no ledger changes.

**Tech Stack:** Python 3 + pyyaml (engine), FastAPI + pytest (server), SvelteKit / Svelte 5 runes + vitest + @testing-library/svelte (web).

**Spec:** `docs/superpowers/specs/2026-07-19-nested-subtasks-design.md`

## Global Constraints

- `sidekick.py` stays DETERMINISTIC — no model logic; pyyaml is its only dependency.
- `ledger.jsonl` is written ONLY by `complete()`. This feature never touches ledger writes, XP, or stats.
- Run server tests with `python3 -m pytest server/tests -q` from the repo root; web tests with `npm test` inside `web/`.
- Svelte components use Svelte 5 runes (`$props`, `$derived`, `$state`) and snippets — match the existing files.
- Feed field names: the active payload uses `parent` (string id), `status` (`"open"`/`"done"`), `completed_at` (ISO string, done items only). Frontmatter uses `parent:`; the completion stamp lives in frontmatter as `completed` (existing) but is exposed in the feed as `completed_at`.
- Nudge copy, exactly: `N/N done — finish it?` (e.g. `3/3 done — finish it?`).
- The vault was wiped 2026-07-19 — there is NO legacy data; do not write migration code.

---

### Task 1: Engine — `--parent` on task creation

**Files:**
- Modify: `sidekick.py` (`create_task` ~line 111, CLI `new` parser ~line 371, `new` dispatch ~line 386)
- Test: `server/tests/test_engine_parent.py` (create)

**Interfaces:**
- Produces: `create_task(title, category, *, from_=None, shared=False, parent=None)` — when `parent` is given, validates the parent task file exists and is `status: open`, else raises `SystemExit`; writes `parent: <id>` into the child's frontmatter. CLI: `python3 sidekick.py new "<title>" --category <c> --parent <id>`.

- [ ] **Step 1: Write the failing tests**

Create `server/tests/test_engine_parent.py`:

```python
"""Engine: parent/child task linkage (nested sub-tasks spec, 2026-07-19)."""
import pytest
import sidekick


@pytest.fixture
def vault(tmp_path):
    v = tmp_path / "vault"
    (v / "tasks").mkdir(parents=True)
    (v / "ledger.jsonl").write_text("", encoding="utf-8")
    sidekick.configure(str(v))
    return v


def test_new_with_parent_writes_parent_frontmatter(vault):
    parent_id = sidekick.create_task("Plan the party", "chore")
    child_id = sidekick.create_task("Book the venue", "chore", parent=parent_id)
    fm, _ = sidekick.read_note(sidekick.task_path(child_id))
    assert fm["parent"] == parent_id


def test_new_without_parent_writes_no_parent_field(vault):
    tid = sidekick.create_task("Solo task", "chore")
    fm, _ = sidekick.read_note(sidekick.task_path(tid))
    assert "parent" not in fm


def test_new_with_missing_parent_fails(vault):
    with pytest.raises(SystemExit):
        sidekick.create_task("Orphan", "chore", parent="20990101-nope")


def test_new_with_done_parent_fails(vault):
    parent_id = sidekick.create_task("Old task", "chore")
    sidekick.complete(parent_id)
    with pytest.raises(SystemExit):
        sidekick.create_task("Too late", "chore", parent=parent_id)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest server/tests/test_engine_parent.py -q`
Expected: 4 failures — `TypeError: create_task() got an unexpected keyword argument 'parent'`.

- [ ] **Step 3: Implement**

In `sidekick.py`, change `create_task`'s signature and body (the docstring line about shared-list fields stays):

```python
def create_task(title, category, *, from_=None, shared=False, parent=None):
    """Create an open task. `from_` (dalton|wife|sidekick) and `shared` are the
    shared-list frontmatter fields (spec sub-project 2) — written only when set,
    so a plain create produces the same file as before. `parent` (a task id) links
    a sub-task to its parent (nested sub-tasks spec) — the parent must exist and
    be open."""
    if parent is not None:
        try:
            pfm, _ = read_note(task_path(parent))
        except FileNotFoundError:
            sys.exit(f"parent task {parent} not found")
        if pfm.get("status", "open") != "open":
            sys.exit(f"parent task {parent} is not open")
    os.makedirs(TASKS, exist_ok=True)
    task_id = dt.datetime.now().strftime("%Y%m%d") + "-" + slug(title)
    n, base = 2, task_id
    while os.path.exists(task_path(task_id)):
        task_id = f"{base}-{n}"; n += 1
    fm = {"category": category, "created": now_iso(), "status": "open"}
    if from_:
        fm["from"] = from_
    if shared:
        fm["shared"] = True
    if parent:
        fm["parent"] = parent
    write_note(task_path(task_id), fm, f"# {title}\n")
    print(f"created {task_id}")
    return task_id
```

In `main()`, add the flag to the `new` parser (next to `--shared`):

```python
    pn.add_argument("--parent", default=None,
                    help="parent task id — links this as a sub-task (parent must be open)")
```

and thread it through the dispatch:

```python
    elif a.cmd == "new":
        create_task(a.title, a.category, from_=a.from_, shared=a.shared, parent=a.parent); regenerate()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest server/tests/test_engine_parent.py -q`
Expected: 4 passed. Then the whole suite: `python3 -m pytest server/tests -q` — everything passes.

- [ ] **Step 5: Commit**

```bash
git add sidekick.py server/tests/test_engine_parent.py
git commit -m "engine: sidekick.py new --parent — validated parent link in child frontmatter"
```

---

### Task 2: Engine feed — expose `parent`/`status`, keep done children under an open parent

**Files:**
- Modify: `sidekick.py` (`read_active`, ~lines 179–201)
- Test: `server/tests/test_engine_parent.py` (extend), `server/tests/test_api_feed.py` (extend)

**Interfaces:**
- Consumes: `create_task(..., parent=...)` from Task 1.
- Produces: every open item in the feed's `active` list gains `"parent": <id or None>` and `"status": "open"`. Additionally, a **done** task whose `parent` is an **open** task is included as `{"id", "task", "category", "sat_for_hours": None, "plan": None, "from", "shared", "parent", "status": "done", "completed_at"}`. The server `/feed` shared-role filter (`a["shared"]`) needs no change — done children carry their `shared` flag.

- [ ] **Step 1: Write the failing tests**

Append to `server/tests/test_engine_parent.py`:

```python
def test_read_active_exposes_parent_and_status(vault):
    parent_id = sidekick.create_task("Plan the party", "chore")
    child_id = sidekick.create_task("Book the venue", "chore", parent=parent_id)
    by_id = {a["id"]: a for a in sidekick.read_active()}
    assert by_id[parent_id]["parent"] is None
    assert by_id[parent_id]["status"] == "open"
    assert by_id[child_id]["parent"] == parent_id
    assert by_id[child_id]["status"] == "open"


def test_done_child_stays_in_feed_while_parent_open(vault):
    parent_id = sidekick.create_task("Plan the party", "chore")
    child_id = sidekick.create_task("Book the venue", "chore", parent=parent_id, shared=True)
    sidekick.complete(child_id)
    by_id = {a["id"]: a for a in sidekick.read_active()}
    assert child_id in by_id
    assert by_id[child_id]["status"] == "done"
    assert by_id[child_id]["parent"] == parent_id
    assert by_id[child_id]["shared"] is True          # role filtering still works
    assert by_id[child_id]["completed_at"]            # ISO stamp present
    assert by_id[child_id]["plan"] is None


def test_done_child_leaves_feed_once_parent_done(vault):
    parent_id = sidekick.create_task("Plan the party", "chore")
    child_id = sidekick.create_task("Book the venue", "chore", parent=parent_id)
    sidekick.complete(child_id)
    sidekick.complete(parent_id)
    assert sidekick.read_active() == []


def test_done_task_without_parent_stays_out_of_feed(vault):
    tid = sidekick.create_task("Solo task", "chore")
    sidekick.complete(tid)
    assert sidekick.read_active() == []
```

Append to `server/tests/test_api_feed.py`:

```python
def test_feed_shared_role_sees_done_shared_child(client, app_config):
    """A completed shared sub-task stays visible to both roles while its parent is open."""
    from server.config import Config
    sidekick.configure(app_config.vault)
    parent_id = sidekick.create_task("Plan the party", "chore", shared=True)
    child_id = sidekick.create_task("Book the venue", "chore", parent=parent_id, shared=True)
    sidekick.complete(child_id)
    r = client.get("/feed", headers=AUTH)
    assert r.status_code == 200
    by_id = {a["id"]: a for a in r.json()["active"]}
    assert by_id[child_id]["status"] == "done"
    assert by_id[child_id]["parent"] == parent_id
```

(The default test client uses the single full-role token; the shared-role path goes through the same `a["shared"]` filter, which `test_api_roles.py` already covers — this test pins that done children flow through `/feed` at all.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest server/tests/test_engine_parent.py server/tests/test_api_feed.py -q`
Expected: the four new engine tests fail with `KeyError: 'parent'` / `'status'`; the feed test fails likewise.

- [ ] **Step 3: Implement**

Replace `read_active` in `sidekick.py`:

```python
def read_active():
    """Open tasks, plus completed sub-tasks whose parent is still open (they render
    as checked rows under the parent until the parent itself completes — nested
    sub-tasks spec). Completed top-level tasks never appear."""
    active = []
    if not os.path.isdir(TASKS):
        return active
    notes = []
    for name in sorted(os.listdir(TASKS)):
        if not name.endswith(".md"):
            continue
        fm, body = read_note(os.path.join(TASKS, name))
        notes.append((name[:-3], fm, body))
    open_ids = {tid for tid, fm, _ in notes if fm.get("status", "open") == "open"}
    for tid, fm, body in notes:
        title = next((l[2:].strip() for l in body.splitlines() if l.startswith("# ")), tid)
        status = fm.get("status", "open")
        if status == "open":
            active.append({
                "id": tid,
                "task": title,
                "category": fm.get("category"),
                "sat_for_hours": hours_since(fm.get("created")),
                "plan": fm.get("plan"),
                "from": fm.get("from"),
                "shared": bool(fm.get("shared")),
                "parent": fm.get("parent"),
                "status": "open",
            })
        elif status == "done" and fm.get("parent") in open_ids:
            active.append({
                "id": tid,
                "task": title,
                "category": fm.get("category"),
                "sat_for_hours": None,
                "plan": None,
                "from": fm.get("from"),
                "shared": bool(fm.get("shared")),
                "parent": fm.get("parent"),
                "status": "done",
                "completed_at": fm.get("completed"),
            })
    # longest-sitting first — the most-stalled task surfaces at the top
    active.sort(key=lambda a: (a["sat_for_hours"] is not None, a["sat_for_hours"] or 0), reverse=True)
    return active
```

No `server/app.py` change: the shared-role filter already selects on `a["shared"]`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest server/tests -q`
Expected: full suite passes (159+).

- [ ] **Step 5: Commit**

```bash
git add sidekick.py server/tests/test_engine_parent.py server/tests/test_api_feed.py
git commit -m "engine: feed exposes parent/status; done sub-tasks stay under an open parent"
```

---

### Task 3: Breakdown prompt links children via `--parent`

**Files:**
- Modify: `server/agent_prompts.py` (~line 87, the `sidekick.py new` command in the breakdown instructions)
- Test: `server/tests/test_agent_prompts.py` (extend)

**Interfaces:**
- Consumes: the `--parent` CLI flag from Task 1.
- Produces: breakdown prompts instruct `python3 sidekick.py new "<sub-task title>" --category {category} --from sidekick{shared_flag} --parent {task_id}`.

- [ ] **Step 1: Write the failing test**

Append to `server/tests/test_agent_prompts.py` (match the module's existing prompt-builder call style — it builds a breakdown prompt from task fields; reuse the same helper/fixture the neighboring tests use):

```python
def test_breakdown_prompt_links_children_with_parent_flag():
    from server.agent_prompts import breakdown_prompt
    p = breakdown_prompt(task_id="20260719-plan-the-party", title="Plan the party",
                         category="chore", shared=True)
    assert "--parent 20260719-plan-the-party" in p
```

(If the module's builder has a different name/signature, mirror how the existing tests in the file call it — the assertion is the point.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest server/tests/test_agent_prompts.py -q`
Expected: the new test fails — `--parent` not in the prompt.

- [ ] **Step 3: Implement**

In `server/agent_prompts.py`, change the instruction line (currently step 3 of the breakdown prompt):

```python
   python3 sidekick.py new "<sub-task title>" --category {category} --from sidekick{shared_flag} --parent {task_id}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest server/tests/test_agent_prompts.py -q` then `python3 -m pytest server/tests -q`
Expected: all pass. (If an existing prompt-snapshot assertion pins the old command line, update that expectation in the same commit — the new flag is the intended change.)

- [ ] **Step 5: Commit**

```bash
git add server/agent_prompts.py server/tests/test_agent_prompts.py
git commit -m "agent: breakdown prompt links sub-tasks to their parent via --parent"
```

---

### Task 4: Web — types + pure tree builder

**Files:**
- Modify: `web/src/lib/types.ts`
- Create: `web/src/lib/tree.ts`
- Test: `web/src/lib/tree.test.ts`

**Interfaces:**
- Consumes: feed shape from Task 2 (`parent`, `status`, `completed_at` on `ActiveTask`).
- Produces (used by Tasks 5–6):
  - `interface TreeNode { task: ActiveTask; children: TreeNode[]; }`
  - `buildTree(tasks: ActiveTask[]): TreeNode[]` — roots in input order; a task roots when it has no parent, its parent isn't in the set, or its ancestry is cyclic.
  - `doneCount(n: TreeNode): { done: number; total: number }` — DIRECT children only.
  - `showNudge(n: TreeNode): boolean` — open parent, ≥1 child, all direct children done.

- [ ] **Step 1: Extend the types**

In `web/src/lib/types.ts`, extend `ActiveTask`:

```ts
export interface ActiveTask {
  id: string;
  task: string;
  category: Category | string;
  sat_for_hours: number | null;
  plan: Plan | null;
  from?: string | null;   // who created it — server-assigned from the token identity
  shared?: boolean;       // membership in the shared list
  parent?: string | null; // sub-task linkage — id of the parent task
  status?: "open" | "done"; // "done" = completed child still shown under its open parent
  completed_at?: string | null; // set on done children only
}
```

- [ ] **Step 2: Write the failing tests**

Create `web/src/lib/tree.test.ts`:

```ts
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd web && npx vitest run src/lib/tree.test.ts`
Expected: FAIL — `./tree` module not found.

- [ ] **Step 4: Implement**

Create `web/src/lib/tree.ts`:

```ts
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd web && npx vitest run src/lib/tree.test.ts`
Expected: 7 passed. Then `npm test` — full suite green.

- [ ] **Step 6: Commit**

```bash
git add web/src/lib/types.ts web/src/lib/tree.ts web/src/lib/tree.test.ts
git commit -m "web: task tree builder — parent nesting, cycle guard, done-count nudge"
```

---

### Task 5: Dashboard renders the tree

**Files:**
- Modify: `web/src/routes/Dashboard.svelte` (the "In front of you" section, lines ~50–88; count line 50)
- Test: `web/src/routes/dashboard.test.ts` (extend)

**Interfaces:**
- Consumes: `buildTree`, `doneCount`, `showNudge`, `TreeNode` from Task 4.
- Produces: no new exports — visual behavior only. Done children render checked/struck with NO buttons; nudge text `N/N done — finish it?` appears on qualifying parents; the "N open" count excludes done children.

- [ ] **Step 1: Write the failing tests**

Append to `web/src/routes/dashboard.test.ts`:

```ts
describe("Dashboard nested sub-tasks", () => {
  const nested: Feed = {
    events: [],
    active: [
      { id: "p", task: "Plan the party", category: "chore", sat_for_hours: 5,
        plan: { summary: "Broken into 2 sub-tasks", steps: [{ text: "Book the venue — [[c1]]" }, { text: "Order the cake — [[c2]]" }] },
        status: "open" },
      { id: "c1", task: "Book the venue", category: "chore", sat_for_hours: 2, plan: null, parent: "p", status: "open" },
      { id: "c2", task: "Order the cake", category: "chore", sat_for_hours: null, plan: null, parent: "p", status: "done", completed_at: "2026-07-19T10:00:00Z" }
    ]
  };

  it("nests child cards inside the parent card, not as top-level cards", () => {
    const { container } = render(Dashboard, { props: { feed: nested } });
    const parentCard = screen.getByText("Plan the party").closest("article")!;
    expect(parentCard.querySelector(".children")).toBeTruthy();
    // children live inside the parent's card
    expect(parentCard.textContent).toContain("Book the venue");
    // and only the parent is a top-level card
    const section = parentCard.parentElement!;
    expect(section.querySelectorAll(":scope > article").length).toBe(1);
  });

  it("renders a done child struck-through without buttons", () => {
    render(Dashboard, { props: { feed: nested } });
    const done = screen.getByText("Order the cake").closest("article")!;
    expect(done.classList.contains("done-card")).toBe(true);
    expect(done.querySelector("button")).toBeNull();
  });

  it("counts only open tasks in the header and nudges when all children are done", () => {
    const allDone: Feed = {
      events: [],
      active: [
        { id: "p", task: "Plan the party", category: "chore", sat_for_hours: 5, plan: null, status: "open" },
        { id: "c1", task: "Book the venue", category: "chore", sat_for_hours: null, plan: null, parent: "p", status: "done", completed_at: "2026-07-19T10:00:00Z" }
      ]
    };
    render(Dashboard, { props: { feed: allDone } });
    expect(screen.getByText("1 open")).toBeInTheDocument();
    expect(screen.getByText("1/1 done — finish it?")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd web && npx vitest run src/routes/dashboard.test.ts`
Expected: the three new tests fail (children render as separate top-level cards; no `.done-card`; no nudge text).

- [ ] **Step 3: Implement**

In `Dashboard.svelte`:

1. Extend the imports and derived state in the `<script>` block:

```ts
  import { buildTree, doneCount, showNudge, type TreeNode } from "$lib/tree";

  const tree = $derived(buildTree(feed.active));
  const openCount = $derived(feed.active.filter(t => t.status !== "done").length);
```

2. Change the count line (50) to use `openCount`:

```svelte
<div class="head"><h2>In front of you</h2><span class="count">{openCount} open</span><span class="rule"></span></div>
```

3. Replace the `{#each feed.active as t (t.id)} … {/each}` card block with a recursive snippet. The card body is the EXISTING markup with `t` → `node.task`; done children get a reduced card; children render inside the article:

```svelte
<section class="section">
  {#snippet taskNode(node: TreeNode)}
    {@const t = node.task}
    <article class="task-card" class:noplan={!t.plan} class:done-card={t.status === "done"}>
      <div class="tc-head">
        <h3 class="tc-name">{t.task}</h3>
        <span class="tc-meta">
          <span class="cat" style="--cl:{catHue(t.category)}">{t.category}</span>
          {#if t.status !== "done"}<span class="sat">{dur(t.sat_for_hours)}</span>{/if}
        </span>
      </div>
      {#if t.status === "done"}
        <div class="muted done-note">✓ done</div>
      {:else}
        {#if t.plan}
          <div class="plan-sum"><span class="prep">Prepared</span>{t.plan.summary}</div>
          <ol class="steps">
            {#each t.plan.steps as s, i}
              {@const href = safeHref(s.href)}
              <li class:next={i === 0}>
                {#if href}<a {href} target={href.startsWith("tel:") ? undefined : "_blank"} rel="noopener">{s.text}</a>{:else}{s.text}{/if}
              </li>
            {/each}
          </ol>
        {:else if node.children.length === 0}
          <div class="noplan-msg muted">No plan yet — ask the orchestrator to clear the first step.</div>
        {/if}
        {#if showNudge(node)}
          <span class="nudge">{doneCount(node).done}/{doneCount(node).total} done — finish it?</span>
        {/if}
        <button class="btn btn-done" aria-label="Done" aria-busy={pending.has(t.id)} disabled={pending.has(t.id)} onclick={() => onComplete(t.id)}>
          {pending.has(t.id) ? "Completing…" : "Done"}
        </button>
        <div class="tc-agent">
          <button class="btn" disabled={isAgentBusy(t.id)} onclick={() => onAgent(t.id)}
                  aria-label={"Ask Sidekick about " + t.task}>
            {isAgentBusy(t.id) ? "Sidekick working…" : "Ask Sidekick"}
          </button>
          {#if agentJobs[t.id]}
            <span class="chip chip-{agentJobs[t.id].status}">{chipText(agentJobs[t.id])}</span>
          {/if}
        </div>
      {/if}
      {#if node.children.length}
        <div class="children">
          {#each node.children as c (c.task.id)}{@render taskNode(c)}{/each}
        </div>
      {/if}
    </article>
  {/snippet}
  {#each tree as n (n.task.id)}{@render taskNode(n)}{/each}
</section>
```

4. Add to the `<style>` block:

```css
  .children { margin-top: 10px; padding-left: 14px; border-left: 2px solid rgba(128, 128, 128, 0.25); }
  .done-card .tc-name { text-decoration: line-through; opacity: 0.55; }
  .done-note { font-size: 13px; }
  .nudge { display: inline-block; font-size: 13px; margin: 6px 0; padding: 2px 10px;
           border-radius: 999px; border: 1px solid rgba(120, 200, 120, 0.5); }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd web && npx vitest run src/routes/dashboard.test.ts`
Expected: all pass, including the two pre-existing tests (flat feeds have no `parent`, so `buildTree` roots everything — unchanged rendering).

- [ ] **Step 5: Commit**

```bash
git add web/src/routes/Dashboard.svelte web/src/routes/dashboard.test.ts
git commit -m "web: dashboard renders nested sub-task tree with done rows and finish nudge"
```

---

### Task 6: Shared list renders the tree

**Files:**
- Modify: `web/src/routes/shared/+page.svelte`
- Test: `web/src/routes/shared/shared.test.ts` (extend)

**Interfaces:**
- Consumes: `buildTree`, `doneCount`, `showNudge`, `TreeNode` from Task 4.
- Produces: visual behavior only. Every open node keeps its checkbox + "Break it down" button (recursion stays available at any depth). Done children render checked+disabled and struck-through. Optimistic completion flips the row to done in place (no removal); `load()` reconciles.

- [ ] **Step 1: Write the failing tests**

Append to `web/src/routes/shared/shared.test.ts`, reusing the file's existing mocking pattern for `$lib/api` (`getFeed` etc. are already `vi.mock`ed there — follow the same setup for these cases):

```ts
describe("shared list nested sub-tasks", () => {
  const nestedFeed = {
    events: [],
    active: [
      { id: "p", task: "Plan the party", category: "chore", sat_for_hours: 5, plan: null, shared: true, status: "open" },
      { id: "c1", task: "Book the venue", category: "chore", sat_for_hours: 2, plan: null, shared: true, parent: "p", status: "open" },
      { id: "c2", task: "Order the cake", category: "chore", sat_for_hours: null, plan: null, shared: true, parent: "p", status: "done", completed_at: "2026-07-19T10:00:00Z" }
    ]
  };

  it("nests children inside the parent row instead of listing them flat", async () => {
    vi.mocked(getFeed).mockResolvedValue(nestedFeed as any);
    render(Page);
    const parentRow = (await screen.findByText("Plan the party")).closest("li")!;
    expect(parentRow.textContent).toContain("Book the venue");
    const list = parentRow.closest("ul")!;
    expect(list.querySelectorAll(":scope > li").length).toBe(1);
  });

  it("renders a done child checked, disabled and struck through", async () => {
    vi.mocked(getFeed).mockResolvedValue(nestedFeed as any);
    render(Page);
    await screen.findByText("Plan the party");
    const box = screen.getByLabelText("Order the cake — done") as HTMLInputElement;
    expect(box.checked).toBe(true);
    expect(box.disabled).toBe(true);
  });

  it("shows the finish nudge when all children are done", async () => {
    vi.mocked(getFeed).mockResolvedValue({
      events: [],
      active: [
        { id: "p", task: "Plan the party", category: "chore", sat_for_hours: 5, plan: null, shared: true, status: "open" },
        { id: "c2", task: "Order the cake", category: "chore", sat_for_hours: null, plan: null, shared: true, parent: "p", status: "done", completed_at: "2026-07-19T10:00:00Z" }
      ]
    } as any);
    render(Page);
    expect(await screen.findByText("1/1 done — finish it?")).toBeInTheDocument();
  });

  it("still offers Break it down on a nested open child", async () => {
    vi.mocked(getFeed).mockResolvedValue(nestedFeed as any);
    render(Page);
    await screen.findByText("Plan the party");
    expect(screen.getByLabelText("Break down Book the venue")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd web && npx vitest run src/routes/shared/shared.test.ts`
Expected: new tests fail (flat list, no done rows, no nudge).

- [ ] **Step 3: Implement**

In `web/src/routes/shared/+page.svelte`:

1. Script changes:

```ts
  import { buildTree, doneCount, showNudge, type TreeNode } from "$lib/tree";

  // keep done children (they render checked under their parent); sort applies to roots
  async function load() {
    error = "";
    try {
      const feed = await getFeed();
      // role `shared` gets a pre-filtered feed; for role `full` this filter does the same job
      tasks = newestFirst(feed.active.filter(t => t.shared));
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) { goto("/settings"); return; }
      error = e instanceof Error ? e.message : "couldn't reach the host";
    }
  }

  const tree = $derived(tasks ? buildTree(tasks) : []);
```

2. `tick()` — flip in place instead of removing (reload reconciles; a completed top-level task disappears on reload because the feed drops it):

```ts
  async function tick(id: string) {
    if (!tasks || pending.has(id)) return;
    const prev = tasks;
    if (!prev.some(t => t.id === id)) return;
    pending = new Set(pending).add(id);
    tasks = prev.map(t => t.id === id ? { ...t, status: "done" as const } : t);  // optimistic
    try {
      await completeTask(id, new Date().toISOString());
      await load();                                       // reconcile: fetch new items from other user
    } catch (e) {
      tasks = prev;                                       // roll back
      error = e instanceof Error ? e.message : "couldn't complete — try again";
    } finally {
      const next = new Set(pending); next.delete(id); pending = next;
    }
  }
```

3. Replace the `{#if tasks}` list markup with a recursive snippet (empty state counts roots):

```svelte
{#if tasks}
  {#if tree.length === 0}
    <p class="muted">Nothing on the list.</p>
  {:else}
    {#snippet row(node: TreeNode)}
      {@const t = node.task}
      <li class:done-row={t.status === "done"}>
        <label>
          {#if t.status === "done"}
            <input type="checkbox" checked disabled aria-label={t.task + " — done"} />
            <span class="struck">{t.task}</span>
          {:else}
            <input type="checkbox" disabled={pending.has(t.id)}
                   onchange={() => tick(t.id)} aria-label={"Complete " + t.task} />
            <span>{t.task}</span>
            {#if showNudge(node)}
              <span class="chip nudge">{doneCount(node).done}/{doneCount(node).total} done — finish it?</span>
            {/if}
          {/if}
        </label>
        {#if t.status !== "done"}
          <div class="row-agent">
            <button class="btn btn-mini" disabled={!!agentJobs[t.id] && jobActive(agentJobs[t.id])}
                    onclick={() => breakItDown(t.id)} aria-label={"Break down " + t.task}>
              {!!agentJobs[t.id] && jobActive(agentJobs[t.id]) ? "Working…" : "Break it down"}
            </button>
            {#if agentJobs[t.id]}
              <span class="chip chip-{agentJobs[t.id].status}">{chipText(agentJobs[t.id])}</span>
            {/if}
          </div>
        {/if}
        {#if node.children.length}
          <ul class="list children">
            {#each node.children as c (c.task.id)}{@render row(c)}{/each}
          </ul>
        {/if}
      </li>
    {/snippet}
    <ul class="list">
      {#each tree as n (n.task.id)}{@render row(n)}{/each}
    </ul>
  {/if}
{:else if !error}
  <p class="muted">Loading…</p>
{/if}
```

4. Style additions:

```css
  .children { margin: 8px 0 0 22px; border-left: 2px solid rgba(128, 128, 128, 0.25); padding-left: 12px; }
  .children li:last-child { border-bottom: none; }
  .struck { text-decoration: line-through; opacity: 0.55; }
  .nudge { border-color: rgba(120, 200, 120, 0.5); }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd web && npm test`
Expected: full web suite green, including the pre-existing shared tests (flat feeds without `parent` render exactly as before; `tick`'s pre-existing test expectations about optimistic behavior may reference row REMOVAL — if one does, update it to expect the in-place done flip, which is the intended new behavior).

- [ ] **Step 5: Commit**

```bash
git add web/src/routes/shared/+page.svelte web/src/routes/shared/shared.test.ts
git commit -m "web: shared list renders nested sub-task tree — done rows stay checked, finish nudge"
```

---

### Task 7: Full verification + push

**Files:** none new.

- [ ] **Step 1: Run both suites**

```bash
python3 -m pytest server/tests -q
cd web && npm test && cd ..
```

Expected: everything green.

- [ ] **Step 2: Manual smoke (optional but cheap)**

```bash
python3 sidekick.py new "Plan the party" --category chore
python3 sidekick.py new "Book the venue" --category chore --parent <printed-parent-id>
python3 sidekick.py complete <printed-child-id>
python3 sidekick.py regenerate
```

Open `sidekick-data.js`: the child appears with `"status": "done"` and `"parent"`. Then delete the two test tasks' files, truncate the test lines... **NO — do not touch `ledger.jsonl`.** Skip the completion smoke on a real vault; run it in a throwaway dir with `SIDEKICK_VAULT=/tmp/smoke-vault` instead (create `tasks/` and an empty `ledger.jsonl` first).

- [ ] **Step 3: Commit anything outstanding and push**

```bash
git push
```

Deploy note: the VPS picks up code via `git -C /srv/sidekick pull` + `bash /srv/sidekick/deploy/bootstrap.sh` (rebuilds the web bundle). The agent clone at `/home/sidekick/agent/sidekick` needs a `git pull` too before the next breakdown job so its `sidekick.py` knows `--parent`.

## Self-review notes

- Spec coverage: `--parent` (T1), feed exposure + done-children exception (T2), breakdown prompt (T3), tree builder incl. cycle guard/orphans (T4), both views + nudge + done rendering (T5, T6), roles untouched (T2 test), no migration (global constraints). Auto-complete explicitly absent — matches spec.
- The spec's "one Svelte component" became one shared pure builder (`tree.ts`) + per-route recursive snippets: the two views' row/card markup share nothing today, and forcing one component would need slot plumbing with no reuse payoff. Deviation noted for the reviewer; the tree LOGIC (the part with rules) is single-sourced and unit-tested.
- Type consistency checked: `TreeNode`/`buildTree`/`doneCount`/`showNudge` names and signatures match across T4–T6; feed field names (`parent`/`status`/`completed_at`) match T2's engine output.
