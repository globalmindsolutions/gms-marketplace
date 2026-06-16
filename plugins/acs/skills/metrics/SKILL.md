---
name: metrics
description: Render a read-only, in-session dashboard of delivery metrics for the current repo — six panels (throughput by status/type, pipeline funnel, cost and time per ticket by step, coverage achieved vs target, review iterations before pass, and token burn by role) derived from existing workspace state. Use when asked to see, audit, or report this repo's delivery throughput, funnel, spend, coverage, review effort, or token usage without leaving the session.
---

You are the coordinator of `/acs:metrics`, the acs delivery dashboard. This is
NOT a hooked pipeline skill: no skill-start, no pre/post hooks, no subagents, no
reflection loop. You do everything yourself with Bash and `show_widget`.

Scope honesty up front: this skill is **read-only**. It aggregates metrics that
already exist in the workspace and renders them inline — it writes no file,
makes no network call, runs no `gh`/HTTP, and reads no config key beyond the
`.acs/settings.json` the helper already consumes. The only side effect is the
inline render in this session. Both the aggregation and the render are
deterministic stdlib helpers — the aggregator
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
  "panels": { "1": …, "2": …, "3": …, "4": …, "5": …, "6": … },
  "meta": { "generated_at": …, "repo_id": …, "ticket_count": …, "degraded": [ … ] }
}
```

**Every panel key `"1"`–`"6"` is ALWAYS present** (the helper's invariant):
degradation is a `"no data"` marker inside a panel, never a missing key. So the
renderer always draws all six frames. If either helper exits non-zero (an
unexpected internal error), report that the dashboard could not be generated and
stop — do not fabricate panels.

## Step 2 — Render the six panels via the deterministic renderer

Do **not** compose the layout yourself. **Route** the aggregate JSON into the
deterministic renderer — `pip`-free, stdlib-only, byte-identical output for the
same input — and present what it emits. Pick the surface for your session:

- **Claude Code terminal (default):** pipe the aggregate JSON into the renderer
  and print the deterministic terminal/Unicode dashboard inline:

  ```bash
  python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/metrics_aggregate.py" \
    | python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/metrics_render.py"
  ```

- **Claude Desktop / claude.ai:** run the same pipe with `--html` and pass the
  emitted, self-contained HTML string to `show_widget` **verbatim** (it is one
  document, inline CSS, no external fetch):

  ```bash
  python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/metrics_aggregate.py" \
    | python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/metrics_render.py" --html
  ```

The renderer (run standalone with no piped input) self-invokes the aggregator,
so `metrics_render.py` alone also works; the explicit pipe is shown so the data
path is obvious.

Both surfaces draw the same six panels, in order:

1. **Throughput** — ticket counts by status and by type.
2. **Pipeline funnel** — how many tickets reached each pipeline step, with the
   PR/merge counts as the terminus.
3. **Cost + time per ticket by step** — per-ticket rows broken down by pipeline
   step (working time and spend), with the repo total.
4. **Coverage achieved vs target** — per ticket; a `null`/`"n/a"` coverage
   renders as "no data" for that ticket, never a crash or a fabricated number.
5. **Review iterations before the verifier passed** — per-ticket integer.
6. **Token burn by role** — input/output tokens and cost bucketed into the three
   roles planner / executor / verifier.

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
- **Results**: six panels rendered inline via the deterministic renderer (terminal in the CLI; `--html` → show_widget on Desktop)
- **Findings**: <degraded panels/tickets and why, or "none — all panels had data">
- **Artifacts**: none (this skill writes nothing)
- **Metrics**: n/a
- **Next**: <e.g. re-run after the next ticket completes, or drill into a flagged ticket>
```
