# 0020 — Deadlines sourced from a `due_date` ticket field (not the GitHub tracker, not deferred)

**Status**: Accepted · **Date**: 2026-06-18

## Context

The PM DEADLINE panel in `/acs:metrics` shipped as a "not set" degraded frame
in MAR-14 (Child 2 of MAR-8): the panel key was always present (B1) but
contained no real due-date data because no date field existed on `ticket.json`.

Three options for the deadline source were evaluated (design `MAR-8/design.md`
lines 244-280):

- **D(a) — add `due_date` to `ticket.json`, set at `/acs:create-ticket`.**
  Keeps the dashboard fully local and deterministic: no network, no `gh` call,
  render input is fixed at aggregation time.
- **D(b) — source dates from the GitHub tracker at render time.**  Read
  project-iteration or milestone dates via `gh` during each `/acs:metrics`
  invocation.  Rejected: a `gh` network read breaks the "no network call" scope
  guarantee for `/acs:metrics` (`docs/operations/observability.md` Scope
  section) and makes the render non-deterministic (results depend on external
  state at render time).
- **D(c) — defer deadlines indefinitely.**  Ship ISSUES + PROGRESS but keep
  the DEADLINE panel as the degraded "not set" frame permanently.  Rejected:
  leaves the eighth acceptance criterion (PM lens) incomplete.

User confirmed option D(a) — clarification ledger C-9 in `MAR-8/design.md`.

Four further clarifications were resolved for MAR-15 (Child 3):

- **C-1** — `now`-injection for determinism: `aggregate(workspace, repo_id,
  now=None)` uses one `_now_str` for BOTH `meta.generated_at` and the
  deadline comparison; tests pin `now` for byte-identical output; the renderer
  reads no clock.
- **C-2** — panel shape: per-ticket table rows of (`id`, `due_date`,
  on-track/overdue status) plus a roll-up, matching the ISSUES/PROGRESS
  per-ticket style.
- **C-3** — index propagation: `update_index` propagates `due_date` into
  `tickets-index.json` so non-dashboard consumers can read it; the aggregator
  reads `due_date` directly from the `ticket.json` it already opens per ticket.
- **C-4** — ADR authorship: `MAR-8/design.md` lines 386-394 assigns an ADR for
  Decision D to `/acs:code`; MAR-13 authored ADR 0018 (Decision A) and MAR-14
  authored ADR 0019 (Decision C) under the same pattern; MAR-15 authors this
  record.

## Decision

Adopt **D(a)** — a `due_date` field on `ticket.json`, set at create-ticket,
derived read-only by the aggregator.

- **`ticket.schema.json`** gains an optional `due_date` property: a `oneOf`
  of a string matching `/^\d{4}-\d{2}-\d{2}$/` (ISO-8601 date) or `null`,
  with `default: null`.  The field is NOT in `required`; `additionalProperties:
  true` is unchanged.  Existing tickets without `due_date` remain valid.
- **`acs_lib.new_ticket_doc`** adds `"due_date": kw.get("due_date")`;
  **`acs_lib.update_index`** adds `"due_date": ticket.get("due_date")` to the
  fixed projection so `tickets-index.json` carries the field (C-3).
- **`new-ticket.py`** gains a `--due-date` optional argument; a `re.fullmatch`
  guard validates `\d{4}-\d{2}-\d{2}` after `parse_args()` and calls
  `sys.exit(2)` on malformed input — matching the `--external` validation
  pattern already in the file.
- **`metrics_aggregate.aggregate`** is extended to `aggregate(workspace,
  repo_id, now=None)` with a single `_now_str` computed once from `now` (if
  given) or `acs_lib.now_iso()`.  `_now_str` is used for BOTH
  `meta["generated_at"]` and the deadline comparison, satisfying C-1.  A
  module-private `_parse_due_date(value)` parses `YYYY-MM-DD` strings and
  returns `None` on anything else; it is a sibling, NOT a widening of
  `acs_lib.parse_iso`, which must continue to accept only full ISO timestamps
  for the panel-7 lead/cycle callers.
- **`_deadline_panel`** is replaced with a live derivation: for each ticket
  with a parseable `due_date`, *overdue* when `due_date < now_date` and the
  ticket is not done; *on-track* otherwise.  The panel shape is a dict with a
  `"rows"` list (C-2) plus a roll-up count.  When no ticket has a parseable
  `due_date`, the panel degrades to the "not set" state with a `meta.degraded`
  entry (B1); an empty workspace keeps `deadline == "no data"` (B1).
- **`metrics_render`** (`_term_render_deadline`, `_html_render_deadline`)
  is extended to render the rows + roll-up table shape when the panel carries
  a `"rows"` key, while retaining the degraded "not set" and "no data"
  branches.  Every new cell routes through `_esc` (XSS safety).
- **The only write is `due_date` at `/acs:create-ticket`.**  The aggregator
  and renderer are read-only.  No network call; no new config key.

This decision is recorded in `MAR-8/design.md` lines 244-280 and 341-351, and
implemented in MAR-15 (specs 01, 02, 03).

## Consequences

- **Live deadline signal in `/acs:metrics`.**  Each ticket with a `due_date`
  contributes a row to the DEADLINE panel showing its on-track/overdue status.
  A roll-up gives the overall workspace health at a glance.  The MAR-14 "not
  set" interim frame is superseded.
- **Additive, back-compatible field.**  Existing tickets without `due_date`
  are valid; the panel degrades gracefully to "not set" (B1) when no ticket
  has a parseable value.  No migration is required; `additionalProperties:
  true` in `ticket.schema.json` was already present.
- **Determinism invariant preserved.**  One `_now_str` anchors both the
  `meta.generated_at` timestamp and the deadline comparison; the renderer
  reads no clock.  Tests pin `now` via the injected parameter for
  byte-identical assertions.
- **No new runtime dependency.**  The change is stdlib-only; no `gh` call;
  no new config key.  The "read-only dashboard path" guarantee holds: the
  only write in the entire feature is `due_date` at create-ticket.
- **`acs_lib.parse_iso` is unchanged.**  The panel-7 lead/cycle callers
  depend on its datetime-only behavior returning `None` on a bare date.  The
  new `_parse_due_date` is a module-private sibling in `metrics_aggregate.py`.
- **Index propagation (C-3).**  `tickets-index.json` carries `due_date`
  from the moment a ticket is created with a value, making the field available
  to non-dashboard consumers without re-reading `ticket.json`.
