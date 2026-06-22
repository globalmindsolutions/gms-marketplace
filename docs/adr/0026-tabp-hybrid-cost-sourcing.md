# 0026 — tabp hybrid cost sourcing: transcript-actuals plus settings-configurable dated-snapshot pricing

**Status**: Accepted · **Date**: 2026-06-22

## Context

MAR-2 (spec 02 helper foundation) shipped `usage-read` as a stub returning
placeholder zeros. The stub's docstring referenced `"MAR-6"` as the ticket that
would deliver real aggregation, but MAR-6 was never opened — the work was
deferred until the tabp plugin had real usage data to aggregate.

MAR-38 fulfils that deferral. The ticket inherits two design decisions from
`MAR-36/design.md:123-165` that together define how token counts and costs are
sourced for a `screen-cvs` run:

**D3a — transcript-actuals source (Claude Code path)**

Cost data for runs executed under Claude Code is derived from the JSONL
transcript files in `~/.claude/projects/<cwd-slug>/`. These files contain
`message.usage.input_tokens` and `message.usage.output_tokens` fields that
record actual token counts per message. The aggregation reader reads ONLY those
two integer fields and `message.model` — it never reads `message.content`,
prompt text, CV content, or any response body. Token counts are "actuals" in the
sense that they were measured by the runtime; but cost is still derived (tokens x
pricing), not self-reported.

Two R1-level fuzziness risks apply (`design.md:531`):
1. The cwd-slug correlation is best-effort — a project directory that contains
   multiple session files spanning multiple runs cannot be split per run
   precisely. Token totals are conservative estimates.
2. The transcript-to-run time-window filtering is not yet implemented (deferred
   to MAR-40); all transcript tokens for the project are summed.

These risks are addressed by labeling the cost `cost_basis="estimate"` even
when token counts come from the transcript (not `"actual"`). The distinction
between "I measured the tokens" and "I self-reported the cost" is preserved.

**D3b — settings-configurable dated-snapshot pricing**

Cost = tokens x price. The price per million tokens must come from somewhere.
Two sub-options were evaluated:

- **Option P1 (hard-coded constant):** a single float price in the source.
  Simple but stale: Anthropic changes prices periodically.
- **Option P2 (settings-configurable dated snapshot):** a built-in
  `_MODEL_PRICING` dict frozen at a known `_PRICING_SNAPSHOT_DATE`, overridable
  per model via `settings.json` `model_pricing`. Callers see the snapshot date
  in every `usage-read` response.

Decision: **Option P2**. The snapshot date makes the cost figure auditable
("this estimate used the 2025-08-01 Anthropic price list") and the settings
override lets project owners correct stale prices without code changes. The
`model_pricing` key is a runtime-read-only contract — no `settings.schema.json`
is created because that file is owned by MAR-3 and its creation would activate
the CI settings-schema validation gate at `.github/workflows/ci.yml:197-199`
(DEV-1 boundary).

**R2 — estimate-never-actual guard**

A critical correctness requirement (`design.md:533`): cost derived from tokens x
pricing must NEVER be labeled `cost_basis="actual"`. Only Cowork self-reported
cost (the `usage_source="cowork"` path, a forward hook) may carry `"actual"`.
This invariant is enforced at two levels:
1. The aggregation loop in `_cmd_usage_read` hard-codes `cost_basis="estimate"`
   for the `claude-code` and `estimate` dispatch arms regardless of the value
   stored in `run.json`.
2. The schema and tests assert no non-cowork run carries `cost_basis="actual"`.

## Decision

1. **D3a — transcript-actuals source.** For runs with `usage_source="claude-code"`,
   `_cmd_usage_read` reads `input_tokens`/`output_tokens` from JSONL files in
   `~/.claude/projects/<cwd-slug>/` via `_read_transcript_tokens`. The transcript
   root is injectable (parameter default `os.path.expanduser("~/.claude/projects")`,
   overridable via `TABP_TRANSCRIPT_ROOT` env var in tests). The reader returns
   `(total_in, total_out, last_model)` — only integers and a model name. No
   transcript text is persisted into `.tabp/`. Cost is derived via `_derive_cost`;
   label is always `cost_basis="estimate"`.

2. **D3b — settings-configurable dated-snapshot pricing.** Module-level
   `_MODEL_PRICING` (dict, model → `{input_per_mtok, output_per_mtok}`) and
   `_PRICING_SNAPSHOT_DATE` (string `YYYY-MM-DD`) are the built-in fallback.
   `_resolve_pricing(settings)` layers `settings.model_pricing` over a copy of
   `_MODEL_PRICING`, silently skipping malformed or non-numeric entries (R5
   additive safety). The snapshot date is always surfaced in `usage-read` output
   as `pricing_snapshot_date`. No `settings.schema.json` is created (DEV-1).

3. **R2 — estimate-never-actual invariant.** `cost_basis="actual"` is reserved
   for `usage_source="cowork"` only. All other sources (`claude-code`,
   `estimate`, `unavailable`) produce `cost_basis="estimate"` or
   `cost_basis="unavailable"`. This is enforced in the aggregation loop and
   tested by the R2 mislabel guard tests in `TestUsageReadAggregation`.

4. **Unavailable omission from totals.** Runs with `usage_source="unavailable"`
   appear in the `runs[]` array for auditability but are omitted from
   `total_tokens_in`, `total_tokens_out`, and `total_cost_usd`. This prevents
   zero-padding that would make averages misleading.

5. **Read-only invariant.** `_cmd_usage_read` makes no `_write_json` calls, no
   history mutations, and no transcript writes. Verified by test
   `test_read_only_no_tabp_files_changed` in `TestUsageReadAggregation`.

## Consequences

- Every `usage-read` response carries `cost_basis` (aggregate) and
  `cost_basis` per run — callers always know the reliability of the cost figure.
- `pricing_snapshot_date` in every response makes the cost auditable: a future
  price change does not silently update historical figures.
- **Residual risk R1 (transcript-to-run correlation fuzziness):** the
  cwd-slug transcript scan is best-effort; the conservative `cost_basis="estimate"`
  label acknowledges this. MAR-40 may improve correlation via time-window
  filtering once the `--runtime` flag and run timestamps are wired through.
- **Residual risk R2 (mislabel prevention):** the `"actual"` label is currently
  unreachable in practice (Cowork does not yet expose self-reported token data;
  `design.md:30-31`). The code path is a forward hook tested by the cowork arm
  in the mixed-run test.
- The `model_pricing` settings surface is undocumented by a schema (DEV-1).
  Users who misconfigure it get silently-ignored entries (R5 additive safety),
  not a startup failure. If MAR-3 later adds `settings.schema.json`, the
  `model_pricing` key can be added to it additivley at that time.
- The `_read_transcript_tokens` / `_derive_cost` / `_resolve_pricing` functions
  are stdlib-only and have no pip dependencies. No new module imports beyond
  `glob` (stdlib) are introduced.
