# 0017 — acs:metrics renders deterministically across surfaces via metrics_render.py

**Status**: Accepted · **Date**: 2026-06-16

## Context

The `/acs:metrics` dashboard renders six panels from the aggregate JSON that
`metrics_aggregate.py` emits. Two questions about *how* the layout is produced
were left open by the original design: the model could compose the layout in
prose inside the SKILL (the path ADR 0014/0015 assumed), and — because
`show_widget` is a main-session-only tool whose availability was an unverified
assumption — the design carried a **Markdown-table fallback** for the case where
`show_widget` is unavailable (ledger C-4, `MAR-5/design.md` Risk R5). A
model-composed layout is not unit-testable and is not reproducible run-to-run;
the fallback added a second, parallel render path the model had to improvise.
AC-8 (`ticket.json:14`) asks instead for a deterministic, cross-surface render
that the skill *routes* to. See `MAR-5/specs/04-metrics-render.md` and
`MAR-5/design.md` Decision A/B and Risk R5.

## Decision

Rendering moves out of prose into a deterministic stdlib module
`plugins/acs/hooks/scripts/metrics_render.py` that consumes the aggregate JSON
and emits the same six panels on **two surfaces**:

- a Unicode block-bar **terminal** dashboard for the Claude Code CLI (the
  default surface), and
- a self-contained **HTML** component (`--html`) — inline CSS only, no external
  fetch — handed to `show_widget` **verbatim** on Claude Desktop / claude.ai.

The skill **routes** (`metrics_aggregate.py | metrics_render.py`) instead of
model-composing the layout. The renderer is pure: `render_terminal(data)` and
`render_html(data)` are functions of the JSON alone — identical input yields
byte-identical output, no clock is read (`meta.generated_at` is rendered as
given), and nothing is written. It is stdlib-only and never imports
`show_widget`.

This decision **supersedes the C-4 Markdown-table fallback**
([0015](0015-metrics-single-show-widget-call.md) noted the single-`show_widget`
render path): the deterministic terminal renderer is now the CLI default rather
than a fallback, and the `--html` output is the `show_widget` payload, so AC-3
(panels render inline via `show_widget`) stays satisfied on the Desktop surface
without a separate model-improvised path. The aggregate-JSON contract
([0013](0013-metrics-derives-panels-from-artifacts.md),
[0014](0014-metrics-helper-emits-json-skill-renders.md)) is unchanged — no
field added, no key renamed, no schema change.

## Consequences

- Rendering is **deterministic and unit-tested** (golden-file): the layout logic
  is a stdlib module covered to the same 90% bar as the aggregator, not
  unreproducible prose.
- One render path, two surfaces — the terminal default removes the second,
  model-improvised Markdown fallback; there is no longer a parallel path to keep
  in parity.
- The HTML surface stays the literal `show_widget` payload (self-contained,
  inline CSS, no external fetch), so AC-3 remains satisfied on Desktop /
  claude.ai while the CLI gets a deterministic terminal render.
- Read-only and stdlib-only are preserved: the renderer writes nothing, makes no
  network call, adds no config key, and never imports `show_widget`.
