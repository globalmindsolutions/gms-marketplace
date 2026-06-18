---
name: usage
description: Render a read-only, in-session dashboard of acs tool usage and spend for the current repo — usage summary, cost and working time per ticket by pipeline step, the four per-ticket and per-PR averages (avg cost, avg tokens, avg working time, avg duration per PR), and token burn by role (planner / executor / verifier) — all derived from existing workspace state. Use when asked to see, audit, or report this repo's AI spend, token consumption, working time, cost per ticket, or averages, not delivery throughput or pipeline coverage.
---

You are the coordinator of `/acs:usage`, the acs tool-usage and spend dashboard.
This is NOT a hooked pipeline skill: no skill-start, no pre/post hooks, no
subagents, no reflection loop. You do everything yourself with Bash and
`show_widget`.

Scope honesty up front: this skill is **read-only**. It aggregates usage
metrics that already exist in the workspace and renders them inline — it writes
no file, makes no network call, runs no `gh`/HTTP, and reads no config key
beyond the `.acs/settings.json` the helper already consumes. The only side
effect is the inline render in this session. Both the aggregation and the render
are deterministic stdlib helpers — the aggregator
(`hooks/scripts/metrics_aggregate.py`) emits the panel JSON and the renderer
(`hooks/scripts/metrics_render.py`) turns that JSON into the dashboard. Your job
is to **route** the data through them, not to compose the layout yourself.

`show_widget` is a main-session-only tool — it is not available to subagents,
which is precisely why this skill renders inline itself and delegates nothing.

## Step 1 — Run the aggregation helper

Run the helper via Bash. It takes no required arguments — it resolves the live
repo and workspace itself (via `acs_lib.build_context()`):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/metrics_aggregate.py"
```

The helper exits `0` even on an empty or partial workspace — degradation is
in-band (`meta.degraded`), never an error code. Its stdout is one JSON object:

```json
{
  "panels": {
    "1": …, "2": …, "3": …, "4": …, "5": …, "6": …, "7": …,
    "delivery_summary": …, "issues": …, "progress": …, "deadline": …,
    "usage_summary": …
  },
  "meta": { "generated_at": …, "repo_id": …, "ticket_count": …, "degraded": [ … ] }
}
```

**Every panel key is ALWAYS present** (the helper's invariant): degradation is a
`"no data"` marker inside a panel, never a missing key. ALL panel keys are
always emitted — the usage view uses the subset relevant to usage. If the helper
exits non-zero (an unexpected internal error), report that the dashboard could
not be generated and stop — do not fabricate panels.

## Step 2 — Render the usage view via the deterministic renderer

Do **not** compose the layout yourself. **Route** the aggregate JSON into the
deterministic renderer — `pip`-free, stdlib-only, byte-identical output for the
same input — and present what it emits. Both surfaces invoke the renderer with
`--view usage` explicitly. Pick the surface for your session:

- **Claude Code terminal (default):** pipe the aggregate JSON into the renderer
  with `--view usage` and print the deterministic terminal/Unicode dashboard
  inline:

  ```bash
  python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/metrics_aggregate.py" \
    | python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/metrics_render.py" --view usage
  ```

- **Claude Desktop / claude.ai:** run the same pipe with `--view usage --html`
  and pass the emitted, self-contained HTML string to `show_widget` **verbatim**
  (it is one document, inline CSS, no external fetch):

  ```bash
  python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/metrics_aggregate.py" \
    | python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/metrics_render.py" --view usage --html
  ```

The usage view renders exactly three panels:

1. **Usage summary** — total and average cost, token consumption, run count, and
   working time across all tickets in the workspace.
3. **Cost and time per ticket by pipeline step** — per-ticket rows broken down by
   pipeline step (working time and spend), with the four per-ticket / per-PR
   averages: avg cost, avg tokens, avg working time, avg duration per PR.
6. **Token burn by role** — input/output tokens and cost bucketed into the three
   roles planner / executor / verifier.

PM-only panels (delivery summary, throughput, pipeline funnel, ISSUES, PROGRESS,
DEADLINE, coverage achieved vs target, review iterations, lead/cycle time) are
NOT included in the usage view.

The renderer surfaces the `meta.degraded` entries as an explicit summary section
on both surfaces (which ticket/panel fell back to "no data" and why), so the
render is auditable — a reader can see what was missing rather than mistaking a
gap for a zero. Because every panel key is always present, an empty or partial
workspace shows the affected frame as "no data" rather than omitting it. Present
the renderer's output as-is; do not re-compose or re-format the panels.

## Completion report (normative)

End your final message with the standard completion block; replace the Ticket
line with **Scope** (this skill is repo-wide, not tied to one ticket):

```markdown
## /acs:usage · <status>

- **Scope**: usage dashboard for <repo_id> (<ticket_count> tickets, generated <generated_at>)
- **Status**: <status> — <one line>
- **Results**: usage view rendered inline (terminal default; --view usage --html → show_widget on Desktop)
- **Findings**: <degraded panels/tickets and why, or "none — all panels had data">
- **Artifacts**: none (this skill writes nothing)
- **Metrics**: n/a
- **Next**: <e.g. re-run after the next ticket completes, or compare spend across PRs>
```
