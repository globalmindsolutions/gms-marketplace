# LLD — Interface contracts

The binding shapes live in machine-validated files; this page is the index.
Canonical detail: `plugins/acs/docs/INTERNALS.md`.

## Coordinator ↔ subagent (XML, `plugins/acs/schemas/acs-messages.xsd`)

| Message | Direction | Key content |
|---------|-----------|-------------|
| `<task skill phase ticket-id iteration>` | coordinator → subagent | objective, `<inputs>` file refs, `<constraints>`, `<context>` (clarifications, prior findings) |
| `<result … status>` | subagent → coordinator (final message, nothing after) | `<outputs>` file refs (incl. the phase artifact), `<findings>`, `<errors>`, `<questions>`, `<metrics>` |
| `<handoff … status>` | step coordinator → /ship | ≤ ~1 KB summary, artifact refs, `<next-step>`, `<questions>` on `needs_input` |

Validation: `validate_xml.py` on every send/receive; one re-request, then fail.

## Coordinator ↔ deterministic layer (CLI)

| Helper | Contract |
|--------|----------|
| `skill-start.py --skill S [--ticket\|--args\|--allocate]` | stdout: context JSON (settings, partition, ticket, models, reconcile/handoff, post_hook path); registers `in_progress` run, lock, pointer |
| `post-<skill>.py --ticket T --result-file F` (or stdin JSON) | input: the **result document** `{status, stop_reason, states, findings, errors, tokens, cost_usd[, handoff_summary]}`; finalizes run + ledger + index + metrics, releases lock |
| `new-ticket.py --title --type [--parent --needs-design --docs-only …]` | mints id + partition + mint-time create-ticket state; epic backlinks |
| `clarify.py add\|answer\|list` | the Q&A ledger (`clarifications.json`); assumptions need `--rationale` |
| `handoff.py --summary` | finalizes `handed_off`, releases lock, prints `continue_with` |

Exit codes: 0 ok; 2 blocked/invalid with actionable stderr.

## Hook events (Claude Code)

`PreToolUse(Skill)` → `dispatch.py pre` → `pre-<skill>.py` (exit 2 blocks);
`SessionEnd` → `dispatch.py session-end` (finalize `interrupted`, release lock).

## Inter-step contract (state files)

The next skill reads only canonical `states` keys — e.g. `/create-pr` gate:
`code-state.states.verifier_passed == true`; `/merge-pr` gate: a `states.pr`
reference in `create-pr-state` (or the product skill's state). Full table:
INTERNALS.md "Canonical states keys per skill". Schemas:
`plugins/acs/schemas/*.schema.json`.

## Settings (consumer repo)

`.acs/settings.json` (+ gitignored `settings.local.json`, user-scope file);
per-key merge local → project → user; validated by every pre-hook
(`settings.schema.json`): `workspace_path`, `ticket_prefix`,
`test_coverage_percent`, `merge_strategy`, `prd_path`, `architecture_path`,
`adr_path?`, `e2e?`, `models`, `tracker`, `formats`.

---

## tabp plugin contracts

Source: `MAR-2/specs/01-tabp-state-json-schemas.md`. Schemas live in
`plugins/tabp/schemas/`. Validated at runtime by `tabp_helper.py` (spec 02).
All `$id` URIs use tabp-namespaced GitHub paths; no acs identifiers.

### tabp settings.json

_Forward reference — owned by MAR-3._ `tabp_helper.py settings-read` reads
a `tabp settings.json` file from the Cowork project folder at skill start and
applies defaults for missing keys. Schema: `plugins/tabp/schemas/settings.schema.json`
(MAR-3). Key fields: `screening_model`, `synthesis_model`, `cv_folder`,
`jd_folder`, `state_write_mode` (`"helper"` or `"instructed"`).

**MAR-38 — `model_pricing` (runtime-read-only, no schema file):** an optional
`model_pricing` block may appear in `settings.json` to override the built-in
pricing snapshot on a per-model basis. No `settings.schema.json` is created for
this key (DEV-1: MAR-3-owned schema boundary; would activate `ci.yml:197-199`).
Format:
```json
{
  "model_pricing": {
    "claude-opus-4-8":   { "input_per_mtok": 15.00, "output_per_mtok": 75.00 },
    "claude-sonnet-4-6": { "input_per_mtok":  3.00, "output_per_mtok": 15.00 }
  }
}
```
Values are USD per million tokens (numbers). No credentials or API keys.
If absent, the built-in `_MODEL_PRICING` snapshot (dated `_PRICING_SNAPSHOT_DATE`)
is used. Surfaced via `settings-read` output when present (`_cmd_settings_read`,
MAR-38). Validated/sanitised at usage-read time by `_resolve_pricing`.

### `.tabp/` state record schemas

All state files are written to `<project>/.tabp/` in the Cowork project folder.
PII-minimal rule: `candidate_name` holds only a name or anonymised label — no
contact details, no protected-class attributes, no secrets.

#### Run record — `run.json`

Path: `<project>/.tabp/runs/<run-id>/run.json`
Schema: `plugins/tabp/schemas/run.schema.json`

| Field | Type | Description |
|---|---|---|
| `run_id` | string | Unique run ID, format `run-<ISO8601>`. E.g. `run-20260620T091530Z`. |
| `skill` | string | Skill name. Always `"screen-cvs"` for the current skill. |
| `started_at` | date-time | ISO-8601 datetime the run started. |
| `ended_at` | date-time or null | ISO-8601 datetime the run ended. Null while `in_progress`. |
| `status` | enum | `"in_progress"`, `"completed"`, `"failed"`, `"interrupted"`. |
| `stop_reason` | string or null | Reason run stopped early. Null unless `failed` or `interrupted`. |
| `state_write_mode` | enum | `"helper"` (tabp_helper.py subcommands) or `"instructed"` (degraded mode). |
| `usage.usage_source` | enum | `"cowork"` (self-reported, cost_basis=actual), `"claude-code"` (transcript tokens, cost_basis=estimate), `"estimate"` (heuristic, cost_basis=estimate), `"unavailable"` (no data). |
| `usage.tokens_in` | integer or null | Input token count. Null when `usage_source = "unavailable"`. |
| `usage.tokens_out` | integer or null | Output token count. Null when `usage_source = "unavailable"`. |
| `usage.cost_usd` | number or null | Cost in USD. Null when `usage_source = "unavailable"`. |
| `usage.cost_basis` | enum (optional) | `"actual"` (self-reported by runtime), `"estimate"` (derived from tokens x pricing), `"unavailable"` (no cost data). Absent on legacy records — treated as `"unavailable"`. |
| `usage.duration_seconds` | number or null | Wall-clock duration in seconds. |
| `candidates_screened` | integer | Number of candidates screened. |
| `jd_slug` | string | Job description slug. E.g. `"backend-engineer"`. |
| `scorecard_file` | string (optional) | Filename of the Excel scorecard produced. |

#### Evidence record — `evidence-<candidate-id>.json`

Path: `<project>/.tabp/runs/<run-id>/evidence-<candidate-id>.json`
Schema: `plugins/tabp/schemas/evidence.schema.json`

| Field | Type | Description |
|---|---|---|
| `run_id` | string | Parent run identifier. |
| `candidate_id` | string | Unique candidate ID within the run. |
| `candidate_name` | string | Name or anonymised label only (PII-minimal rule). |
| `requirements` | array | Per-requirement judgments. Each item: `requirement`, `category`, `judgment`, `evidence` (minLength:1 — AC-4). |
| `score` | number | Composite score 0..100. |
| `band` | enum | `"Strong"`, `"Moderate"`, `"Weak"`. |
| `recommendation` | enum | `"Recommend"`, `"Hold"`, `"Reject"`. |
| `must_have_gate` | string | Pattern `^(OK\|Missing:.+)$`. `"OK"` or `"Missing:<list>"`. |
| `fairness_check_passed` | boolean | Whether the fairness guardrail check passed. |
| `bias_flags` | array (optional) | List of bias flag strings. Empty when none detected. |

AC-4 constraint: every `requirements[].evidence` must be a non-empty string (minLength:1).
No invented evidence is permitted; all judgments must cite CV source.

#### Decision record — `decision.json`

Path: `<project>/.tabp/runs/<run-id>/decision.json`
Schema: `plugins/tabp/schemas/decision.schema.json`

| Field | Type | Description |
|---|---|---|
| `run_id` | string | Parent run identifier. |
| `verification_passed` | boolean | Whether the self-verification step passed (AC-3). |
| `verification_notes` | string (optional) | Notes from the self-verification step. |
| `presented_at` | date-time | ISO-8601 datetime when results were presented. |
| `sign_off` | object or null | Null until recruiter confirms in-chat. Object has: `recruiter` (string), `confirmed_at` (date-time), `notes` (string, optional). |

#### Append-only run history — `history.json`

Path: `<project>/.tabp/history.json`
Schema: `plugins/tabp/schemas/history.schema.json`

| Field | Type | Description |
|---|---|---|
| `runs` | array | Append-only array of run summary objects. `runs[-1]` is the most recent run. |
| `runs[].run_id` | string | Run identifier. |
| `runs[].skill` | string | Skill name. |
| `runs[].started_at` | date-time | Run start time. |
| `runs[].status` | enum | `"in_progress"`, `"completed"`, `"failed"`, `"interrupted"`. |
| `runs[].ended_at` | date-time or null (optional) | Run end time. |
| `runs[].candidates_screened` | integer (optional) | Number of candidates screened. |
| `runs[].jd_slug` | string (optional) | Job description slug. |
| `runs[].duration_seconds` | number or null (optional) | Wall-clock duration. |
| `runs[].usage_source` | enum (optional) | `"cowork"`, `"claude-code"`, `"estimate"`, or `"unavailable"`. |

The append-only invariant (no deletion) is enforced at runtime by `tabp_helper.py`.

#### Lock — `.lock`

Path: `<project>/.tabp/.lock`
Schema: `plugins/tabp/schemas/lock.schema.json`

| Field | Type | Description |
|---|---|---|
| `pid` | integer (>= 1) | PID of the process holding the lock. |
| `hostname` | string | Hostname of the machine holding the lock. |
| `created_at` | date-time | ISO-8601 datetime the lock was acquired. |

Stale locks (process gone or different host) are reported for manual removal,
never auto-stolen. Released when the run transitions out of `in_progress`.

### `/tabp:usage` read contract output shape

_Implemented in MAR-38. Replaces the MAR-6 placeholder stub._

`tabp_helper.py usage-read --project-dir <path> [--run-id <id>|all]` aggregates
from `history.json` + per-run `run.json` records and prints to stdout:

```json
{
  "total_runs": 12,
  "completed_runs": 11,
  "failed_runs": 1,
  "total_candidates_screened": 47,
  "total_duration_seconds": 19205,
  "total_tokens_in": 284000,
  "total_tokens_out": 52000,
  "total_cost_usd": 4.12,
  "cost_basis": "estimate",
  "pricing_snapshot_date": "2025-08-01",
  "usage_note": "Cost is a derived estimate (tokens x pricing table snapshot 2025-08-01). Token counts are actuals from Claude Code transcript where available; estimate otherwise. Unavailable runs excluded from totals.",
  "runs": [
    {
      "run_id": "run-20260620T091530Z",
      "started_at": "2026-06-20T09:15:30Z",
      "status": "completed",
      "candidates_screened": 5,
      "duration_seconds": 1902,
      "usage_source": "claude-code",
      "tokens_in": 28000,
      "tokens_out": 5200,
      "cost_usd": 0.41,
      "cost_basis": "estimate",
      "usage_note": "Tokens: actuals from Claude Code transcript. Cost: derived estimate."
    }
  ]
}
```

When `usage_source = "unavailable"`: `tokens_in`, `tokens_out`, `cost_usd` are
`null`; `cost_basis` is `"unavailable"`; the run is included in `runs[]` but
excluded from token/cost totals.

When `usage_source = "cowork"`: `cost_basis = "actual"` (self-reported by
Cowork runtime — forward hook, MAR-40).

`pricing_snapshot_date` is always present (`_PRICING_SNAPSHOT_DATE` constant).
`cost_basis` is the aggregate: `"actual"` if any non-unavailable run has actual,
else `"estimate"`, else `"unavailable"`.

Read-only: no writes, no network calls, no re-screening. No transcript text is
persisted into `.tabp/` state files.
