# 0015 — acs:metrics renders all six panels in a single show_widget call

**Status**: Accepted · **Date**: 2026-06-16

## Context

The `/acs:metrics` dashboard presents six panels. They could be rendered as one
`show_widget` call (a single dashboard document) or as six separate calls, one
per panel (design Decision B). The ticket asks for "a dashboard" with an atomic
empty-state — a valid six-panel view even when there is no data. See
`MAR-5/design.md` Decision B.

## Decision

The skill renders **all six panels in a single `show_widget` call**, backed by an
**always-present panel contract**: the helper's JSON carries every panel key
`"1".."6"` on every run, and degradation is expressed as a `"no data"` marker
inside a panel (plus a `meta.degraded` entry), never as a missing key. The widget
therefore always draws six frames, including the empty-workspace case.

## Consequences

- A single coherent dashboard with one render, one ticket scan, and an atomic
  empty-state; the panels never disagree about which six exist.
- The "a malformed panel breaks the whole widget" risk is neutralized by the
  always-present contract — the widget never sees an absent panel.
- An empty workspace renders a valid six-panel "no data" dashboard rather than an
  error or a partial view.
