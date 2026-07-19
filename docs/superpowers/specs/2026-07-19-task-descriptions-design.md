# Task descriptions — design

2026-07-19. Approved: multiline descriptions on tasks — add at capture, view on tasks,
edit later, on all surfaces.

## What this is

Tasks get an optional free-text, multiline **description**. It is entered via an
"add details" textarea on the app's capture form, shown (clamped, expandable) on
dashboard cards and list rows, and editable in place after capture.

## Where it lives — `description:` frontmatter, NOT the body

The task file's markdown body stays the orchestrator's free space (research prose;
app-invisible). The description is a structured `description:` frontmatter field:
code-written, no collision with agent prose, visible to the agent when it reads the
task file, and shown in Obsidian as a property. Plain text with line breaks — no
markdown rendering in the app.

## Engine (`sidekick.py`)

- `create_task(..., description=None)` — strips; empty → omitted (field never written
  as empty/null). CLI: `new … --description "<text>"`.
- `set_description(task_id, text)` — writes/replaces `description:`; empty/whitespace
  text REMOVES the field. `ValueError` if the task file is missing or `status` ≠ open.
  CLI: `set-description <id> [--file f]` (arg via `--file` or stdin, like `set-plan`).
- Feed: active items gain `"description": fm.get("description")` (open items; done
  children too — harmless passthrough, not rendered).

## API (`server/app.py`)

- `POST /tasks` accepts optional `description` (string; stripped; empty → omitted;
  > 4000 chars → 400) and forwards it.
- `POST /tasks/{task_id}/description` `{description}` — same shape as `complete`:
  shared role gets 404 for personal tasks (indistinguishable from missing), 404 for
  unknown ids, 409 for non-open tasks, 400 for non-string or > 4000 chars; empty
  string clears the description; idempotency-key aware; vault lock; regenerate;
  git commit `api: describe <id>`; returns the updated active entry.

## Web

- Types/api: `ActiveTask.description?: string | null`; `createTask(title, category,
  shared, list?, description?)`; `setTaskDescription(id, text)`.
- **Capture** (list detail add box — the app's only capture form): a small
  "+ details" toggle under the title input expands an auto-growing `<textarea>`
  (collapsed by default; quick capture unchanged). Submitting sends the description
  when non-empty and clears both fields.
- **Display:** tasks with a description show it under the title, clamped to 2 lines
  (CSS line-clamp), tap to expand. Applied on dashboard cards and list-detail rows.
  Done children don't render descriptions.
- **Edit:** in the expanded state an "Edit" affordance swaps the text for a textarea
  + Save/Cancel; Save calls `setTaskDescription`, optimistically updates, reloads to
  reconcile; errors surface like other row errors. Editing is available to both
  roles on tasks they can see (server enforces the shared-role rules).
- Whitespace-only edits clear the description (field disappears).

## Out of scope

- Markdown rendering; descriptions in nudges, previews on the list GRID cards, the
  static dashboard/Chrome extension (view stays title+plan), and the ledger (the
  completion event is unchanged).
- Editing task TITLES (separate feature if ever wanted).

## Testing

- Engine: create with/without description, strip/empty-omit, set/replace/clear,
  missing/done task errors, feed passthrough.
- Server: create with description; describe happy path, clear, 404 personal-as-shared,
  404 unknown, 409 done, 400 oversize/non-string.
- Web: api call shapes; add-box toggle + submit with details; clamp/expand; edit save
  + optimistic update + rollback on failure; done rows don't render descriptions.
