---
name: metrics
description: Render a read-only, in-session dashboard of project-management delivery metrics for the current repo — delivery summary (headline KPIs), ticket throughput by status/type, pipeline funnel with distinct PRs created/merged, ISSUES (per-ticket id, title, status, type, GitHub key), PROGRESS (done vs total, per-epic child progress), DEADLINE (not set — real on-track/overdue data arrives in Child 3 / MAR-15), coverage achieved vs target, review iterations before pass, and lead/cycle time — all derived from existing workspace state. Use when asked to see, audit, or report this repo's delivery throughput, pipeline funnel, ticket progress, schedule, coverage, review effort, or lead/cycle time, not AI spend or token consumption.
---

You are the coordinator of `/acs:metrics`, the acs PM delivery dashboard. This
is NOT a hooked pipeline skill: no skill-start, no pre/post hooks, no subagents,
no reflection loop. You do everything yourself with Bash and `show_widget`.

Scope honesty up front: this skill is **read-only**. It aggregates delivery
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
always emitted — the PM view uses the subset relevant to delivery. If the helper
exits non-zero (an unexpected internal error), report that the dashboard could
not be generated and stop — do not fabricate panels.

## Step 2 — Render the PM delivery view via the deterministic renderer

Do **not** compose the layout yourself. **Route** the aggregate JSON into the
deterministic renderer — `pip`-free, stdlib-only, byte-identical output for the
same input — and present what it emits. Both surfaces invoke the renderer with
`--view pm` explicitly. Pick the surface for your session:

- **Claude Code terminal (default):** pipe the aggregate JSON into the renderer
  with `--view pm` and print the deterministic terminal/Unicode dashboard inline:

  ```bash
  python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/metrics_aggregate.py" \
    | python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/metrics_render.py" --view pm
  ```

- **Claude Desktop / claude.ai:** run the same pipe with `--view pm --html` and
  pass the emitted, self-contained HTML string to `show_widget` **verbatim** (it
  is one document, inline CSS, no external fetch):

  ```bash
  python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/metrics_aggregate.py" \
    | python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/metrics_render.py" --view pm --html
  ```

The PM delivery view renders exactly nine panels:

- **Delivery summary** — headline KPIs: tickets done/total, PRs merged, avg lead
  time, avg cycle time, coverage pass rate.
1. **Throughput** — ticket counts by status and by type.
2. **Pipeline funnel** — how many tickets reached each pipeline step, with
   distinct PRs created/merged as the terminus.
4. **Coverage achieved vs target** — per ticket; a `null`/`"n/a"` coverage
   renders as "no data" for that ticket, never a crash or a fabricated number.
5. **Review iterations before the verifier passed** — per-ticket integer.
7. **Lead/cycle time** — lead time (ticket open → merge) and cycle time (code
   start → merge) per ticket.
- **ISSUES** — per-ticket table: id, title, status, type, and GitHub key.
- **PROGRESS** — done vs total counts; per-epic child progress breakdown.
- **DEADLINE** — not set frame; deadline tracking requires a `due_date` field on the ticket, wired in Child 3 / MAR-15.

Usage-only panels (usage summary, cost and time per ticket by step (3), token
burn by role (6)) are NOT included in the PM delivery view.

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
## /acs:metrics · <status>

- **Scope**: delivery dashboard for <repo_id> (<ticket_count> tickets, generated <generated_at>)
- **Status**: <status> — <one line>
- **Results**: PM delivery view rendered inline via the deterministic renderer (terminal in the CLI; --view pm --html → show_widget on Desktop)
- **Findings**: <degraded panels/tickets and why, or "none — all panels had data">
- **Artifacts**: none (this skill writes nothing)
- **Metrics**: n/a
- **Next**: <e.g. re-run after the next ticket completes, or drill into a flagged ticket>
```
