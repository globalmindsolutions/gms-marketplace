# 0018 — Distinct-PR counting via a recorded `created_pr_numbers` set

**Status**: Accepted · **Date**: 2026-06-17

## Context

`metrics.json.prs.created` was incremented on every completed `create-pr` run.
Because `/acs:create-pr` re-runs on each PR update (new commits, review fixes,
forced CI re-runs), a single PR can trigger multiple completions. In practice
MAR-5/PR#44 produced 3 completions for one PR — inflating `prs.created` to 14
against the actual 4 distinct PRs (numbers 43, 44, 46, 50) in the workspace.

The over-count violates the intent of the "PRs created" metric: the number
should reflect distinct PRs, not pipeline re-entries.

Two recovery strategies were considered:

- **A1 (chosen)**: at write time, record `states.pr.number` in a sorted
  de-duped `created_pr_numbers` list; `created = len(created_pr_numbers)`.
  Back-compatible; idempotent on re-run of the same skill invocation; an
  idempotent backfill heals existing history from the retained PR numbers in
  partition state files.
- **A2 (rejected)**: re-scan all skill-run records from every partition on
  every write. Prohibitively expensive and still fails for archived partitions
  that were cleaned up before the PR number was retained in state.

## Decision

Adopt **A1** — write-time set membership in `metrics.json`.

`update_metrics` gains a trailing optional parameter `pr_number=None`. When
`pr_created` is `True` and `pr_number` is a positive integer not already in
`prs.created_pr_numbers`, the number is appended (kept sorted, de-duped) and
`prs.created` is set to `len(created_pr_numbers)`. All other call-paths
(`pr_created=False`, `pr_number=None`, `pr_number <= 0`, duplicate number)
leave both fields unchanged — idempotent by design.

The `run_post` caller additionally extracts `states.pr.number` from the result
payload and passes it as `pr_number`. The `SessionEnd` and exempt-`--pr`
callers pass no `pr_number` and are unaffected.

An idempotent one-time backfill (`backfill_distinct_pr_count`) recomputes
`created_pr_numbers` from the distinct positive `states.pr.number` values
across all active and `archive/` ticket partitions and sets
`created = len(...)`. Re-running the backfill with unchanged partition state
produces the identical result.

This decision is recorded in `MAR-8/design.md` lines 307-322 and 677-681, and
implemented in `plugins/acs/hooks/scripts/acs_lib.py` (MAR-13 spec 01).

## Consequences

- **Deliberate semantics shift.** `prs.created` changes from "number of
  completed `create-pr` runs" to "number of distinct PRs created". The old
  meaning over-counted; the new meaning is the intended one. Readers of the
  dashboard Panel 2 (pipeline funnel) see the corrected count.
- **Backfill heals to the recoverable distinct set.** The backfill scans
  `create-pr-state.json` in each partition. Pre-fix history where no PR number
  was retained in state is **unrecoverable and accepted** — this is not a
  defect. In this workspace the recoverable set is {43, 44, 46, 50} (4 PRs),
  healing the inflated count of 14.
- **Additive field, no schema break.** `created_pr_numbers` is an additional
  property on the `prs` object, which already carries `additionalProperties:
  true` in `metrics.schema.json`. Readers that do not know the field ignore it.
- **No aggregator or renderer change in this spec.** `metrics_aggregate.py`
  and `metrics_render.py` continue to read `prs.created` as before; the field
  now reflects distinct PRs rather than run completions, which is the corrected
  value those components already intend to display.
- **Stdlib-only, read-only invariants preserved.** The change is confined to
  the `pr_created` increment path; no network call, no new dependency, and the
  dashboard read path is unmodified.
