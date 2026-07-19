# Nested sub-tasks — design

2026-07-19. Approved approach: **B — authoritative `parent:` frontmatter field** (over client-side
`[[wikilink]]` parsing, rejected as model-written prose masquerading as structure).

## What this is

When a task is broken down (agent runner "Break it down", or by hand), its sub-tasks are real task
files. Today both the dashboard view and the shared list render every task as a flat card and the
parent/child relationship is invisible. This change renders **parents as cards with their sub-tasks
nested beneath them, recursively, in both views**. Sub-tasks are full cards: they can be completed,
and they can themselves be broken down (recursion is already possible at the data level; the UI just
never showed it).

Decisions made with Dalton:
- **Nested tree**, children do not repeat as top-level rows.
- Applies to **both** the dashboard view and the shared list (one shared component).
- Parent is **not** auto-completed when all children are done — the parent card shows a
  "N/N done — finish it?" nudge and completion stays a manual, explicit XP event.

## Data model

- Child task frontmatter gains `parent: <task-id>` (the filename-id of the parent).
- `sidekick.py new` gains `--parent <id>`: validates the parent task file exists and is open,
  writes the field. Deterministic; no model reasoning.
- The breakdown prompt (`server/agent_prompts.py`) adds `--parent {task_id}` to the
  `sidekick.py new` command it instructs the agent to run. The parent's short plan
  (`"Broken into N sub-tasks"` + `[[child]]` steps) is unchanged — it stays as the human-readable
  summary; the `parent:` field is the machine truth.
- Feeds pass `parent` through: `sidekick.py regenerate` (→ `sidekick-data.js`) and the server
  `/api/feed` active-task payload.

### Completed children stay visible under an open parent

Completed tasks normally leave the active feed. Exception: a **done** task whose `parent` is still
an **open, visible** task is included in the feed (minimal fields: id, title, parent, status,
completed_at). The tree renders it as a checked row under its parent. This is what makes the
"N/N done" nudge computable client-side, and it gives the satisfying strikethrough view until the
parent itself is completed — at which point the whole subtree leaves the active view for good.
No ledger changes: XP/events are untouched; this is purely feed/rendering.

## Tree building (shared component)

One Svelte component (e.g. `web/src/lib/TaskTree.svelte`) used by `routes/+page.svelte`
(dashboard view) and `routes/shared/+page.svelte`.

Rules, applied to whatever task set the caller already has (role filtering unchanged):
- A task renders at **top level** if it has no `parent`, or its parent is not in the visible set
  (parent completed, parent personal while viewer only sees shared, parent deleted).
- Otherwise it nests under its parent; arbitrary depth.
- Cycle guard: while walking ancestors, a repeated id breaks the chain — that task renders at top
  level. (Bad data should degrade to today's flat view, never recurse forever.)
- Sibling order: feed order (creation date), same as today.

## Cards

Every node is the full task card, at any depth:
- title, category, age — as today;
- plan summary; non-breakdown plans (research) keep today's numbered-steps rendering;
- **Break it down** button (this is what makes recursion usable), with the existing job chip/polling;
- complete button (existing `POST /tasks/{id}/complete` flow);
- parent whose visible children are all done: nudge text "N/N done — finish it?" beside its
  complete button. N counts direct children only.
- Completed children render checked, struck through, no buttons.

## Roles & permissions

No server permission changes. The shared role already sees only shared tasks and breakdown inherits
`shared`, so each viewer's tree is composed purely from tasks they can already see. The
completed-children feed exception respects the same visibility filter.

## Error handling

- `sidekick.py new --parent` with a missing/done parent: hard error, task not created.
- Orphaned `parent` value at render time: degrade to top-level card (never hide a task).
- Agent runner failure mid-breakdown: unchanged — existing baseline-reset handles it.

## Testing

- `sidekick.py`: `--parent` happy path, missing parent, done parent; `regenerate` includes
  `parent` and the done-child-with-open-parent exception.
- Server: `/api/feed` exposes `parent` and the done-children exception under both roles.
- Web: tree-builder unit tests (orphans, depth ≥ 3, cycle guard, mixed shared/personal parents,
  done children, nudge counting); component tests for both routes.

## Out of scope

- Auto-completing parents (rejected by design).
- Push notifications for the shared role (existing phase limitation).
- Any depth limit or breakdown-count changes (prompt already bounds 2–5 children per breakdown).
- Migration: none needed — the vault was wiped 2026-07-19; no legacy tasks exist.
