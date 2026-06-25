# 0033 — Treat stakes as a first-class independent axis with configurable path-glob detection

**Status**: Accepted · **Date**: 2026-06-25

## Context

Stakes (the risk level of a change) is currently implicit — it is not tracked in `ticket.json`
and has no machine-readable representation. Engineers informally raise rigor for high-risk
changes, but the pipeline cannot enforce or measure this. The decision is: how do we make
stakes first-class in a way that is (a) deterministic and unit-testable, (b) user-controlled
rather than silently decided by a tool, and (c) configurable without requiring a code change?

## Decision

**Treat `stakes` as a first-class independent axis in `ticket.json` alongside `size`.**

Key design choices:

1. **Explicit axis, not implicit risk score.** `stakes` is a user-confirmed enum
   (`low` | `normal` | `high`) stored in `ticket.json`. It is not derived from a risk
   model; the user has the final word.

2. **Path-glob detection RECOMMENDS, never decides.** A pure deterministic helper
   `recommend_stakes(paths, settings)` matches changed/surveyed paths against the
   `high_stakes_paths` glob list from settings. A match yields a RECOMMENDATION of
   `stakes=high`; no match yields `stakes=normal`. The recommendation is presented to
   the user with the matched paths as rationale. The user can accept or override in either
   direction. The function never writes `stakes` to any file.

3. **Configurable seed list, user-overridable.** The default seed list covers five
   high-stakes surfaces: `auth/**`, `payments/**`, `migrations/**`, `public-api/**`,
   `security/**`. Organizations can replace the seed by setting `high_stakes_paths` in
   `.acs/settings.json`. An absent key resolves to the seed default via `DEFAULT_SETTINGS`.
   The seed is a starting point, not a hard-coded rule.

4. **No silent floor-down invariant.** Once a user confirms `stakes=high`, a subsequent
   `recommend_stakes` call returning `normal` must NOT silently lower the stakes. The
   SKILL.md prose enforces this: de-escalation requires explicit user confirmation.

## Alternatives considered

- **Risk score from commit history / LOC / dependency analysis:** non-deterministic; adds
  an ML or heuristic dependency; not unit-testable; varies by repo tooling.
- **Stakes inferred from lane alone:** loses the axis granularity — a `large` ticket and
  a `trivial` ticket with `stakes=high` both land in STANDARD or COMPLEX, but for different
  reasons; tracking stakes independently allows the metrics layer to slice by risk.
- **Org-level only (not per-repo):** too coarse; different repos have different high-stakes
  surfaces. Configurable per-repo glob list gives teams control without a global policy change.
- **Silent auto-set (no user confirm):** violates the "recommend don't decide" invariant;
  the user is the accountable party for classifying their own ticket.

## Consequences

- `settings.schema.json` gains an optional `high_stakes_paths` array-of-strings property.
- `DEFAULT_SETTINGS` in `acs_lib.py` has the seed list as the fallback value.
- `recommend_stakes(paths, settings)` is a pure, stdlib-only, unit-testable function
  (no side effects, no imports beyond `fnmatch` which is already used in the module).
- The create-ticket SKILL.md planner runs path-glob matching and presents the recommendation
  with rationale; the user confirms or overrides.
- The `stakes` value flows into `derive_lane` (D1) where `stakes=high` floors the lane to
  STANDARD-or-above, ensuring high-stakes work always gets full-verify rigor.
- Metrics: `stakes` is in `ticket.json` and mirrored in the index, enabling future dashboards
  to correlate stakes with defect rates or rework cost (G16 catch-rate measurement).
