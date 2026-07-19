# Named lists on the shared page — design

2026-07-19. Companion to `2026-07-19-nested-subtasks-design.md` (built after it; the list
detail view is where that spec's shared-page tree rendering lands).

## What this is

The shared page becomes a Google Keep-style grid of named list cards (name, preview of the
first few open tasks, open count); tapping a card opens that list's detail view, which holds
everything the shared page does today plus the nested sub-task tree: add box, checkboxes,
"Break it down", finish nudge.

Decisions made with Dalton:
- **Grid + one default list**: every task belongs to exactly one list; tasks without a
  `list` field belong to the built-in default list **"To-dos"** (id `todos`). Nothing
  migrates — today's tasks are simply in To-dos.
- **Keep-style lifecycle**: lists persist independently of their tasks, in a code-written
  registry. An emptied grocery list stays on the grid.
- Lists are a **shared-page concept only**; the dashboard keeps its single game view.

## Data model

- `lists.json` in the vault root, **code-written via sidekick.py** (like the ledger: never
  hand-edit), synced through git like everything else:
  `{"lists": [{"id": "groceries", "name": "Groceries", "created": "<ISO>"}]}`
- The default list (`todos`, "To-dos") is implicit — never stored in the registry, cannot
  be deleted, always first on the grid.
- Task frontmatter gains `list: <list-id>` (top-level tasks only). **Sub-tasks never carry
  `list`** — a child renders under its parent wherever the parent lives. The UI builds the
  full tree first, then selects roots by list; children follow their root automatically.
  Corner case (accepted): if a parent completes while a child stays open, the promoted
  child has no `list` and lands in To-dos.

## Engine (`sidekick.py`)

- `read_lists()` → registry entries; `list_new(name)` → id = `slug(name)`, rejects the
  reserved id `todos` and collisions; `list_delete(list_id)` → refuses while any **open**
  task references it. CLI: `list-new "<name>"`, `list-delete <id>` (both regenerate).
- `create_task(..., list_=None)`: when given, the id must exist in the registry (else
  `SystemExit`); writes `list:` frontmatter. CLI: `new ... --list <id>`.
- Feed: the payload gains `"lists": read_lists()`; every active item gains
  `"list": fm.get("list")`.

## API (`server/app.py`)

- `POST /lists {name}` — both roles; name required, 1–60 chars; 409 on id collision;
  idempotency + vault lock + git commit like other writes; 201 → the registry entry.
- `DELETE /lists/{list_id}` — both roles; 404 unknown; 409 while the list has open tasks;
  the default list 404s (it does not exist as a resource).
- `POST /tasks` accepts optional `"list"` — 400 if not in the registry; forwarded to
  `create_task`.
- `/feed` includes `"lists"` for both roles.

## Web

- **Grid** (`/shared` rewritten): two-column card grid. Cards = To-dos first, then registry
  order. Each card: list name, up to 5 open root-task titles with ☐ glyphs, "+N more"
  overflow line, open count. Tap → `/shared/list/<id>`. "+ New list" affordance (inline
  name input → `POST /lists`). An empty non-default list shows a small delete affordance.
- **Detail view** (`/shared/list/[id]`, new route): the nested sub-task tree (per the
  nested-subtasks spec — done children checked/struck, recursion via Break it down, finish
  nudge), an add box that creates tasks in this list, optimistic complete, agent-job
  polling. Back link to the grid.
- Roles: unchanged server-side. The grid/detail views filter `t.shared` client-side exactly
  as the shared page does today; role `shared` still gets a pre-filtered feed.

## Error handling

- Unknown list id in the detail route: show "list not found" + back link (a deleted-on-
  another-phone list can 404 gracefully).
- `list_delete` racing a task create: both run under the vault lock server-side.

## Testing

- Engine: registry round-trip, slug/collision/reserved-id, delete-with-open-tasks refusal,
  `--list` validation, feed exposure.
- Server: POST/DELETE /lists happy + error paths, POST /tasks with list, /feed lists under
  both roles.
- Web: grid grouping (default list, registry order, preview overflow), new-list flow,
  detail-view scoping (only this list's roots + their descendants), add-in-list, plus the
  tree tests inherited from the nested-subtasks plan's shared-page task.

## Out of scope

- Renaming lists (add when someone actually wants it).
- List ordering/pinning, colors, personal (non-shared) lists, per-list push notifications.
- Any ledger/XP change — completing a task in any list is the same event as today.
