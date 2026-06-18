# 0019 — Split `/acs:metrics` into two narrowly-scoped skills: PM delivery and tool usage

**Status**: Accepted · **Date**: 2026-06-18

## Context

The original `/acs:metrics` skill rendered a single seven-panel dashboard that
mixed two distinct kinds of signal:

- **PM / delivery signal** (throughput, pipeline funnel, coverage, review
  iterations, lead/cycle time) — consumed by product managers and team leads
  asking "how far along is this project?"
- **acs spend / usage signal** (cost per ticket by pipeline step, token burn by
  role) — consumed by practitioners and cost-conscious teams asking "how much
  did the AI work cost?"

These two audiences have non-overlapping trigger requests, non-overlapping
panels, and non-overlapping follow-up actions. Routing both through the same
skill description caused ambiguity in `evals/acs/scenarios/s04_skill_triggers.py`:
a request about "AI spend" could legitimately route to `/acs:metrics` because
the old description mentioned "cost/time per ticket" alongside "throughput" and
"coverage" (design `MAR-8/design.md:45-49`).

The panel allocation (design `MAR-8/design.md:359-383`) makes the split
definitive: panels 1, 2, 4, 5, 7, delivery_summary, issues, progress, deadline
are PM-only; panels 3, 6, usage_summary are usage-only; no panel belongs to
both views.

## Options considered

**C1 (chosen) — Two explicit skill entrypoints over one shared aggregator:**
`/acs:metrics` (PM view) and `/acs:usage` (usage view) both call the same
`metrics_aggregate.py` superset aggregator and the same `metrics_render.py`
renderer, but pass `--view pm` and `--view usage` respectively. Each skill has
a narrowly-scoped description that makes routing unambiguous. The aggregator
always emits all panel keys; each renderer view selects its subset. The split is
enforced at the skill-description layer — the data pipeline remains shared and
single-pass.

**C2 (rejected) — One renderer with a runtime panel filter selected by the
user's request:** the coordinator would inspect the request and pass a filter
flag to the renderer. This retains one skill but creates a cross-view leak risk:
the coordinator's interpretation of "PM vs usage" is not deterministic, and
incorrect filtering produces a partially wrong dashboard without failing loudly.
A structural split (two separate skill descriptions) pushes the routing decision
to the model-trigger layer where the eval suite can assert on it.

**C3 (rejected) — Duplicate the renderer into two independent scripts:** full
separation of `metrics_render_pm.py` and `metrics_render_usage.py`. This
eliminates any coupling between views but produces shared-logic drift: every
future change to the rendering helpers (formatting, HTML layout, `_esc`, money
formatting) must be made in both files. A single shared renderer with a
`--view` dispatch is strictly better.

## Decision

Adopt **C1**: split at the skill-description layer; keep the aggregator and
renderer shared.

- `plugins/acs/skills/metrics/SKILL.md` is re-scoped to the PM delivery view
  (description anchored in delivery / throughput / funnel / coverage / lead-cycle).
  It invokes `metrics_render.py --view pm` explicitly on both surfaces.
- `plugins/acs/skills/usage/SKILL.md` is a new unhooked skill (same structural
  shape as metrics) anchored in cost / spend / token-burn / averages. It invokes
  `metrics_render.py --view usage` explicitly on both surfaces.
- `metrics_aggregate.py` emits a superset of all panel keys; neither skill
  changes the aggregator.
- `metrics_render.py` dispatches on `--view {pm,usage,all}` (added in spec 02);
  `--view all` preserves the pre-existing full seven-panel output for back-compat.

The 5-point registry change (acs_lib.UNHOOKED_SKILLS, test_skill_contracts.ALL_SKILLS,
s04_skill_triggers.CASES, plugins/acs/README.md, c4-container.md) is atomic in
one PR; a one-sided edit fails CI via `test_all_skills_exist_no_strays`.

## Consequences

- **Two focused skill descriptions** make the `s04` routing eval deterministic:
  a request about AI spend fires `/acs:usage`; a request about delivery
  throughput fires `/acs:metrics`. No routing ambiguity.
- **Independently checkable B1 invariants:** each view's panel isolation is
  asserted in the test suite (`TestPMViewPanelIsolation`, `TestUsageViewB1`);
  a future edit that leaks a PM panel into the usage view or vice versa fails CI.
- **More golden tests** (one per view per surface), but they are view-scoped and
  do not cross-contaminate.
- **Skill count increases from 15 to 16.** All skill-count references are updated
  atomically in the same PR.
- **The 5-point registry is the atomicity invariant** (Risk R3, design
  `MAR-8/design.md:655-657`): `acs_lib.UNHOOKED_SKILLS`, `test_skill_contracts.ALL_SKILLS`,
  `s04_skill_triggers.CASES`, the README table, and the C4 container count must
  always agree; the contract test enforces this on every CI run.
- **No user-visible behavior change for existing users** who invoke `/acs:metrics`:
  the skill continues to render a delivery dashboard; the PM view's nine panels
  are a superset of the information most users expect from a delivery dashboard.
  Users who want the spend/token breakdown now invoke `/acs:usage` instead.
