# Observability — the `/acs:metrics` dashboard

How to read the in-session `/acs:metrics` dashboard: a **read-only, single-repo**
view of throughput, cost, coverage, and review effort for the current repo,
aggregated from workspace artifacts alone. It realizes PRD goal **G7
(observability)** and feeds **G5 (auditability)** — every fallback is recorded,
nothing is silently dropped.

## Scope and guarantees

- **Read-only.** The dashboard reads workspace artifacts and writes nothing,
  anywhere — no new state, no files, no schema fields. It runs in-session; there
  is no network call.
- **Single repo.** It aggregates only the current repo's workspace partition
  (active tickets plus `archive/`). Multi-repo aggregation is out of scope.
- **No new config.** It consumes the existing `.acs/settings.json` only (to
  resolve `workspace_path`) and introduces **no new config keys**. Nothing about
  the dashboard needs configuring.
- **Always seven panels.** Every panel key is always present. Missing or partial
  state renders as a **"no data"** marker for that panel — never a missing panel,
  never a crash (see [Degradation](#degradation-and-the-meta-block) below).

## How to run

Run `/acs:metrics` in a Claude Code session for the repo you want to inspect.
The skill **routes** the data through two deterministic stdlib helpers — it does
not compose the layout itself: the read-only aggregation helper
(`metrics_aggregate.py`) emits the panel JSON, and the renderer
(`metrics_render.py`) turns that JSON into the dashboard. See
[Rendering surfaces](#rendering-surfaces) below for the terminal-vs-HTML split.

## Rendering surfaces

Rendering is **deterministic and read-only**: `metrics_render.py` is a pure
function of the aggregate JSON — identical input produces byte-identical output,
it reads no clock (`meta.generated_at` is rendered exactly as the aggregator
stamped it), and it writes nothing. It is stdlib-only (no pip) and never imports
`show_widget`. The same seven panels render on two surfaces:

- **Terminal (Claude Code CLI — default).** A deterministic Unicode block-bar
  dashboard printed inline. This is the default surface; ANSI color is off so the
  output is reproducible.

  ```bash
  python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/metrics_aggregate.py" \
    | python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/metrics_render.py"
  ```

- **HTML (Claude Desktop / claude.ai).** With `--html`, the renderer emits one
  self-contained HTML string — inline CSS only, **no external fetch** (no
  `http(s)` URL, `<link>`, `<script src>`, or web font) — which the skill hands
  to `show_widget` verbatim. The inline style is **theme-adaptive** (a
  `prefers-color-scheme: dark` block keeps it readable in both light and dark)
  and carries deterministic CSS **bar visuals** on panels 1, 2, and 6.

  ```bash
  python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/metrics_aggregate.py" \
    | python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/metrics_render.py" --html
  ```

Run standalone with no piped input, `metrics_render.py` self-invokes the
aggregator (resolving the live repo via `acs_lib.build_context()`), so the
single-command form works too. Either surface draws all seven panel frames — an
empty or partial workspace renders the affected frame as "no data" rather than
omitting it. The deterministic terminal renderer **supersedes** the former
model-improvised Markdown fallback: rendering no longer depends on the model
composing the layout.

## The seven panels

Each panel is derived from existing workspace artifacts (no schema extension was
added to back any of them). The sources below are the panel contract — what each
panel means and where its numbers come from.

### 1 — Throughput by status / type

Counts of tickets per status and per type. Primary source is the repo-level
`metrics.json` (`tickets.by_status` / `tickets.by_type`). When `metrics.json` is
absent, the counts are recomputed from each ticket's `status` / `type` in
`tickets-index.json`.

### 2 — Pipeline funnel

How far tickets progress through the pipeline. For each ticket, the per-skill
step status comes from `pipeline-state.json` (`steps.<skill>.status`), counted in
`HOOKED_SKILLS` order — a ticket is counted at a step when that step is
`completed`. The PR terminus comes from the repo-level `metrics.json.prs`
(`created` / `merged`).

**Distinct-PR counting (deliberate semantics).** `prs.created` reflects the number
of **distinct PRs** created, not the number of completed `create-pr` skill runs.
A single PR that triggers `create-pr` multiple times (re-runs on updates, forced CI
re-entries) is counted once.  The distinct set is backed by the auditable
`prs.created_pr_numbers` field — a sorted, de-duped list of the positive PR numbers
recorded via `create-pr` completions.  `prs.created = len(prs.created_pr_numbers)`
at all times; the two fields are kept consistent by a single write point in
`update_metrics`.  Pre-fix history where no PR number was retained in partition state
is unrecoverable and accepted (see ADR 0018).

### 3 — Cost + time per ticket by step

Per-ticket cost and elapsed time, broken down by pipeline step. Time comes from
each step's start/end in `pipeline-state.json` (`steps.<skill>` → seconds); the
per-ticket roll-up is `pipeline-state.json.totals`, cross-checked against the
repo-level `metrics.json.totals`.

The panel also appends **four averages** as summary rows after the repo total:
**avg working time per ticket** and **per merged PR**, and **avg cost per ticket**
and **per merged PR**. The two working-time averages are humanized durations
(`d`/`h`/`m`/`s`); the two cost averages are plain USD. Each average is
`total ÷ denominator` — repo-level `metrics.json.totals.working_seconds` /
`cost_usd` over the ticket count or the merged-PR count (`metrics.json.prs.merged`).
A **zero denominator** (no tickets, or no merged PR) renders **"no data"** for that
average rather than dividing by zero. These working-time averages are the
**working-seconds** the pipeline recorded — distinct from the wall-clock lead/cycle
times in Panel 7 below.

### 4 — Coverage achieved vs target

Per-ticket test coverage. Achieved coverage is
`code-state.json.states.tests.coverage_percent`; the bar is
`states.tests.coverage_target` (a number, or an `"n/a …"` string for docs-only
work); `states.verifier_passed` is the pass flag. When coverage is `null` or an
`"n/a"` string, the panel shows **"no data"** for that ticket — it does not crash
or attempt arithmetic.

### 5 — Review iterations before the verifier passed

How many `/acs:code` review iterations a ticket needed before its verifier
passed. The authoritative source is
`code-state.json.states.review.iterations`; when that field is absent, the value
falls back to the maximum `iteration` among the ticket's
`phases/code/iter-N-verify.xml` files.

### 6 — Token burn by role

Token and cost spend bucketed into three roles — **planner**, **executor**,
**verifier**. For each ticket, the spend is summed from the `<metrics
tokens-input … tokens-output … cost-usd …>` element across the ticket's
`phases/<skill>/iter-N-<phase>.xml` files, bucketed by the file's `phase`
attribute: `plan → planner`, `execute → executor`, `verify → verifier`.

There is **no `role` attribute** — the role IS the phase. Phases that are not one
of these three (notably the `coordinate` phase) are **not** counted in any role
bucket. Tickets with no metric-bearing phase XML contribute `0`.

### 7 — Lead + cycle time per ticket

Per-ticket **delivery-flow** times, plus the **average lead** and **average
cycle** across the tickets that have a value. Definitions:

- **Lead time** = `ticket.json.created_at` → the `merge-pr` step's `ended_at` in
  `pipeline-state.json` — from when the ticket was created to when its PR merged.
- **Cycle time** = the `code` step's `started_at` → the `merge-pr` step's
  `ended_at` — from when coding began to when the PR merged.

**Wall-clock, not working time.** Lead and cycle are **wall-clock elapsed**
(`ended − started`) durations, *not* the `working_seconds` that Panels 3 and 6
use: they include idle/overnight gaps. The end anchor is **`merge-pr`** (when the
PR actually merged), **not** `create-pr`. Both are rendered as humanized
durations (`d`/`h`/`m`/`s`). The two **averages** are taken only over the tickets
that have a numeric value — a ticket with `"no data"` lead or cycle does not drag
the average.

**No-data / degraded behavior.** A ticket with **no merged PR** (no
`merge-pr.ended_at`) renders **"no data"** for both lead and cycle; a merged
ticket **with no code step** renders **"no data"** for cycle while lead still
computes; a ticket with **no `created_at`** renders **"no data"** for lead. Every
such case appends a `meta.degraded` entry (`panel: 7`) — consistent with the
degradation contract below. The "no data" cell is always present, never an
omitted row.

**Re-cycle / overlapping-span contract.** When a ticket is re-cycled (i.e. its
`code.started_at` falls *after* its `merge-pr.ended_at` due to an overlapping or
out-of-order step span), `aggregate()` never raises. The inverted cycle interval
renders as `"no data"` for `cycle_seconds`; a `meta.degraded` entry is appended
with `panel: 7`; one row per ticket is always returned; nothing is written to disk.
The same overlap-safe guarantee applies to lead-time inversions
(`merge-pr.ended_at` before `ticket.json.created_at`). Both cases are handled by
the `_elapsed_seconds` guard in `metrics_aggregate.py` which returns `None` on any
inverted interval (`not (end >= start)`), never raises, and is never rewritten
around this guard — a guarantee, not a rewrite.

**Per-ticket re-work count (`rework_count`).** Each Panel-7 row carries an
additive integer field `rework_count` (>= 0) equal to the count of **distinct
positive PR numbers** recoverable from `create-pr-state.json` in that ticket's
resolved partition (active or `archive/`). It counts how many different PRs were
associated with this ticket — a value > 1 indicates re-work (the ticket drove more
than one PR, e.g. after a reverted merge). The field is `0` when the state file is
absent, malformed, or carries no positive PR number. `rework_count` appears next to
`lead_seconds` and `cycle_seconds` in the per-ticket row dict; it is **not**
averaged at the panel level (it is a count, not a duration). The aggregator is
read-only: computing `rework_count` reads one file per ticket, writes nothing.

## Degradation and the `meta` block

Alongside the seven panels the dashboard carries a `meta` block:

```
meta = { generated_at, repo_id, ticket_count, degraded: [ { ticket_id, panel, reason } ] }
```

The operability contract is explicit and auditable:

- **Every panel key is always present.** A panel with no usable source renders a
  **"no data"** marker — never a missing key, never an exception.
- **Every fallback is recorded.** Whenever a panel falls back to "no data" (or to
  a recompute path), an entry is appended to `meta.degraded` naming the
  `ticket_id`, the `panel`, and the `reason`. This is what makes the dashboard
  auditable (G5): you can always see *which* panels degraded and *why*.
- **An empty workspace is valid.** With no tickets, the dashboard renders a valid
  seven-panel "no data" dashboard with `ticket_count == 0` — it does not error.

## Performance budget

The dashboard aggregates and renders all seven panels in **≤ 5 s for ≤ 50
tickets** (the binding G7 NFR). This is the operator's expectation when running
`/acs:metrics` against a busy repo.
