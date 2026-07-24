# Sidekick → family planner — vision (captured 2026-07-24, Dalton on holiday)

Sidekick evolves incrementally into the family's planning brain. Not a rewrite — a
direction for the existing loop (friction → conversation → spec → plan → ship).

## Architecture principle: the Mac is the hands, the VPS is the brain

**Local morning chores.** The Mac already self-wakes at 08:55 (pmset) for the nudge.
That slot generalizes into a local jobs runner (launchd): jobs that need Dalton's
credentials or hardware run ON the Mac, and only their distilled results are written
to the vault and pushed. The VPS never holds bank tokens or school logins.

- **Bank**: call the bank's API locally; only account balances (and later
  envelope/category numbers) enter the vault for planning. Live PSD2 access is
  earned later — CSV import or balances-only first.
- **Viggo** (kids' school communication app Dalton struggles to check): a local job
  logs in morning + evening, reads new messages, and the agent judges "does this
  need a parent?" → creates a task on the shared list with context. School data
  never leaves the Mac except as the task text itself.

## Modules, in rough order

1. **Recurring/scheduled tasks + due dates** — the missing primitive. Unlocks the
   yearly chore plan, seasonal kid-shopping reminders, calendar feeds.
2. **Chore-year import** — the family's existing Excel (Google Sheet, access pending
   — Dalton to flip link-sharing or export) becomes recurring tasks.
3. **ICS calendar feed** — one-way publish so Marie sees Sidekick tasks/dates in
   Google Calendar (her preferred surface). No OAuth; a subscription URL.
4. **Viggo morning/evening check** (local job, above).
5. **Economy / Pengero** — digitize the paper Pengero book the family already uses
   (envelope-style: amounts set aside per life area). Dalton photographs the book
   after the holiday; design starts from the ritual that makes it work, not from
   bank data. Bank balances (local job) feed it later.
6. **Dashboard growth** — new skill branches per module (economy, school) so the
   game layer reflects the whole household, not just chores.

## Surfaces (who sees what)

- Dalton: Sidekick itself (dashboard + lists) + push/iMessage nudges.
- Marie: Google Calendar (via ICS) + the shared lists + push (when enabled for
  shared role). She should never need a new tool.
- The agent: does legwork (research, breakdown, Viggo triage, imports).

## Chore-year workbook (read 2026-07-24 — link now shared)

Google Sheet "ÅRSHJUL - DALTONS", four tabs; this IS the recurrence model's shape:
- **Årshjul** (~90 rows): Måned | Kategori | Opgave | Status | Noter — month-granular
  yearly tasks (insurance review in January, winter-clothes check, holiday planning…).
- **Tilbagevendende Opgaver**: quarterly jobs with Q1–Q4 checkboxes (descale coffee
  machine, dishwasher, shower lime…).
- **Ugentlige opgaver**: daily/weekly routines with Kategori + **Ansvarlig** (owner —
  blank today; import can leave unassigned).
- **Noter og Tips**: their planning strategy in prose (quarterly weekend session,
  family-calendar reminders, coordinate with partner).
→ Recurrence primitive must express: yearly-by-month, quarterly, weekly, daily;
  category; optional owner. Danish task titles — keep unicode slugs (already fixed).

## Open inputs
- [ ] Pengero photos (after holiday) + a kitchen-table description of the ritual.
- [ ] Which bank, and whether it offers a personal API / PSD2 route worth the
      weight vs CSV export.
- [ ] Viggo: confirm web login works (no 2FA-per-login), decide credential storage
      on the Mac (Keychain).
