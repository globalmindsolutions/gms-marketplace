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
- **Always six panels.** Every panel key is always present. Missing or partial
  state renders as a **"no data"** marker for that panel — never a missing panel,
  never a crash (see [Degradation](#degradation-and-the-meta-block) below).

## How to run

Run `/acs:metrics` in a Claude Code session for the repo you want to inspect.
The skill runs the read-only aggregation helper and renders the six panels
inline as a single dashboard (one `show_widget` call). If `show_widget` is
unavailable, the same six panels render as a Markdown table — no data is lost,
only the presentation changes.

## The six panels

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

### 3 — Cost + time per ticket by step

Per-ticket cost and elapsed time, broken down by pipeline step. Time comes from
each step's start/end in `pipeline-state.json` (`steps.<skill>` → seconds); the
per-ticket roll-up is `pipeline-state.json.totals`, cross-checked against the
repo-level `metrics.json.totals`.

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

## Degradation and the `meta` block

Alongside the six panels the dashboard carries a `meta` block:

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
  six-panel "no data" dashboard with `ticket_count == 0` — it does not error.

## Performance budget

The dashboard aggregates and renders all six panels in **≤ 5 s for ≤ 50
tickets** (the binding G7 NFR). This is the operator's expectation when running
`/acs:metrics` against a busy repo.
