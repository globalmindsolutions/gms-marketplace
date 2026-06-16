# 0014 — metrics helper emits aggregate JSON; the skill renders show_widget

**Status**: Accepted · **Date**: 2026-06-16

## Context

MAR-5's `/acs:metrics` needs to turn workspace artifacts into a rendered
six-panel dashboard. Two contracts were weighed (design Decision A): the helper
could emit a structured aggregate JSON that the coordinator renders, or the
helper could emit `show_widget` markup directly. The ticket demands the panel
aggregation be unit-testable field-by-field, and `show_widget` is a
main-session-only tool not available to the deterministic helper layer. See
`MAR-5/design.md` Decision A.

## Decision

`plugins/acs/hooks/scripts/metrics_aggregate.py` is a **pure, stdlib-only helper
that prints one aggregate JSON object** `{ panels, meta }` to stdout, with zero
`show_widget` dependency. The `/acs:metrics` skill (`SKILL.md`) parses that JSON
and **composes the `show_widget` render** itself. This mirrors the house
CLI→JSON helper contract every other deterministic helper follows
(`docs/architecture/lld/contracts.md:16-26`).

## Consequences

- Each panel is unit-assertable in `tests/test_metrics_aggregate.py` against
  synthesized workspaces, with no widget coupling in the gate/helper layer.
- The render step lives in skill prose and is exercised at the agentic-e2e /
  paid-eval tier (the s04 trigger eval), not in the deterministic contract suite
  — an accepted trade for keeping the aggregation pure and testable.
- The helper stays usable as a plain CLI (`python3 metrics_aggregate.py` →
  JSON), consistent with the existing helper table.
