---
name: usage
description: >
  Show usage, cost, time, and token counts for tabp CV-screening runs.
  Use when the user asks about usage, cost, spend, how much did screening cost,
  token usage, screening cost breakdown, time spent screening, or wants to see
  per-run or total usage figures.
---

# Show usage, cost, time, and token statistics for screening runs

Read aggregated cost, time, and token data from the `.tabp/` run history and
present a clear per-run breakdown plus aggregate totals. Works for a single run
or all runs in a project.

This skill is read-only. It performs no writes, no re-screening, and no network
calls.

## When to use

Use when the user wants to: see how much CV screening cost, review token usage
across runs, check time spent screening, understand cost per run, get a spend
summary, or audit usage figures for a project.

## Step 0 — Invoke usage-read

Run the helper to collect usage data:

```
python3 plugins/tabp/helpers/tabp_helper.py usage-read \
  --project-dir <project-folder> \
  [--run-id <run-id>|all]
```

- When `--run-id` is omitted, all runs in the project are returned.
- `<project-folder>` is the recruiter's Cowork project folder (the folder that
  contains the `.tabp/` state directory).
- Capture the JSON output (printed to stdout) for rendering in Step 1.

## Step 1 — Parse the JSON response

The helper returns a single JSON object. Key top-level fields:

- `total_runs` — total number of processed runs
- `completed_runs` — count of runs with status=completed
- `failed_runs` — count of runs with status=failed or interrupted
- `total_candidates_screened` — sum of candidates across all runs
- `total_duration_seconds` — total wall time including unavailable runs
- `total_tokens_in` — sum of input tokens (unavailable runs excluded)
- `total_tokens_out` — sum of output tokens (unavailable runs excluded)
- `total_cost_usd` — sum of cost in USD (unavailable runs excluded)
- `cost_basis` — aggregate basis: `"actual"` / `"estimate"` / `"unavailable"`
- `pricing_snapshot_date` — date of the pricing snapshot used for estimates
- `usage_note` — human-readable note about estimate accuracy and exclusions
- `runs[]` — array of per-run entries (see Step 2)

Each entry in `runs[]` carries:
- `run_id` — unique run identifier
- `started_at` — ISO-8601 start timestamp
- `status` — `completed` / `failed` / `interrupted`
- `candidates_screened` — number of CVs evaluated in this run
- `duration_seconds` — wall time for this run
- `usage_source` — `"claude-code"` / `"cowork"` / `"estimate"` / `"unavailable"`
- `tokens_in` — input tokens (null when unavailable)
- `tokens_out` — output tokens (null when unavailable)
- `cost_usd` — cost in USD (null when unavailable)
- `cost_basis` — per-run cost basis
- `usage_note` — per-run human-readable note

## Step 2 — Render per-run table and totals

Present a Markdown table with one row per run in `runs[]`:

| Run ID | Date | Status | Candidates | Duration (s) | Tokens in | Tokens out | Cost (USD) | Basis | Source |
|--------|------|--------|------------|--------------|-----------|------------|------------|-------|--------|
| `run_id` | `started_at` (date) | `status` | `candidates_screened` | `duration_seconds` | `tokens_in` or "—" | `tokens_out` or "—" | `cost_usd` or "—" | `cost_basis` | `usage_source` |

Render "—" for `tokens_in`, `tokens_out`, and `cost_usd` when they are null
(this happens for runs where `usage_source="unavailable"`).

After the per-run table, render a **Totals** summary block using the top-level
aggregate fields:

```
Totals
  Runs:                <total_runs> total (<completed_runs> completed, <failed_runs> failed)
  Candidates screened: <total_candidates_screened>
  Total duration:      <total_duration_seconds> s
  Total tokens in:     <total_tokens_in>
  Total tokens out:    <total_tokens_out>
  Total cost (USD):    <total_cost_usd>
  Cost basis:          <cost_basis>
  Pricing snapshot:    <pricing_snapshot_date>
```

Always display the top-level `usage_note` verbatim below the totals block.

## Step 3 — Honesty rule

Any cost figure where `cost_basis` is `"estimate"` must be labeled as an
estimate — never presented as an actual charge. The coordinator must not
rephrase or omit this label when rendering results.

- `cost_basis="estimate"` figures derive from token counts multiplied by a
  pricing snapshot; they are not actual billed amounts.
- `cost_basis="actual"` figures (Cowork self-reported, future path) may be
  labeled as actual only when the source explicitly says so.
- The `pricing_snapshot_date` tells the reader which pricing snapshot the
  estimate is based on; always surface it in the summary.

## Degradation path

When usage data is unavailable for a run:

- The helper returns `usage_source="unavailable"` for that run.
- `tokens_in`, `tokens_out`, and `cost_usd` are `null`; `cost_basis` is
  `"unavailable"`.
- Render "—" for those cells and display the run's `usage_note` to explain
  why data is unavailable.
- Never fabricate or estimate cost or token figures for unavailable runs.
  The coordinator fabricates nothing for runs it cannot read.

When the helper or Bash is unavailable entirely (the `usage-read` call cannot
execute):

- Present the `usage_note` from the helper if it was returned, or state that
  usage data is not accessible in this context.
- Do not invent cost or token figures.
- Fabricate nothing.

## Guardrails & limits

- Cost figures are read-only derived estimates unless labeled `cost_basis="actual"`.
- This skill performs **no writes**, **no re-screening**, and **no network calls**.
- Never present an estimate as an actual charge.
- Never fabricate usage figures when data is unavailable.
- All data comes from the `.tabp/` run history and the Claude Code transcript;
  no external service is contacted.
