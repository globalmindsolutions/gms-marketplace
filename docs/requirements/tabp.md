# tabp plugin — living requirements

This file states what the tabp plugin DOES (current behavior). It is additive
and updated in place as features ship. Source tickets: MAR-1 (epic), MAR-2 (foundation).

---

## Feature area: tabp quality-patterns foundation (MAR-2)

### .tabp/ state JSON schemas (spec 01 — MAR-2)

The tabp plugin ships five JSON Schema Draft-2020-12 contracts for every `.tabp/`
state entity written during a `screen-cvs` run. Schema files live in
`plugins/tabp/schemas/`; validating samples live in `plugins/tabp/schemas/samples/`.

#### Acceptance criteria (shipped — MAR-2 spec 01)

- **AC-1**: A documented structured JSON Schema for the `.tabp/` run record and
  append-only run history exists (`run.schema.json`, `history.schema.json`), and a
  validating sample exists for each. The `runs[-1]` invariant (last entry = current
  status) is documented in `plugins/tabp/schemas/README.md`.

- **AC-4**: A source-grounded evidence schema is defined (`evidence.schema.json`) that
  ties every judgment to cited source evidence. The `evidence` field within each
  requirement item has `minLength:1` — an empty or absent `evidence` field is
  schema-invalid. No invented evidence is permitted.

- **AC-5**: A decision-record format is defined (`decision.schema.json`) for human
  review and is written into the `.tabp/` state. The `sign_off` field is nullable via
  `oneOf` — it is `null` until the recruiter explicitly confirms in-chat.

- **AC-6**: No `acs:` prefix and no `.acs/` token appear anywhere in the tabp
  foundation surface (schemas, samples, README, tests). All `$id` URIs use the
  tabp-namespaced GitHub URI pattern. This is verified by TC-12 in
  `tests/tabp/test_tabp_schemas.py`.

#### Behavior-defining decisions and constraints

**Namespace isolation**: Every tabp schema file uses
`https://github.com/globalmindsolution/gms-marketplace/plugins/tabp/schemas/<entity>.schema.json`
as its `$id`. No `acs` identifier appears in any tabp file (`design.md:120-127`).

**Schema convention**: Five entities, one schema file each. All schemas:
- `"$schema": "https://json-schema.org/draft/2020-12/schema"` (Draft 2020-12)
- `"type": "object"` at the top level
- `"additionalProperties": true` for forward compatibility
- A `"required"` array listing all required fields

**PII-minimal rule** (`design.md:129-132`): `candidate_name` holds only a name or
anonymised label. No contact details (email, phone, address), no protected-class
attributes (age, gender, race, religion, disability), and no secrets (API keys,
passwords) appear in any `.tabp/` state file. This is a process constraint on the
write path; it is not expressible in JSON Schema and is enforced by documentation
and code review.

**Evidence sourcing (AC-4)**: The `requirements[].evidence` field in the evidence
record is required and has `minLength:1`. A screening judgment is invalid without a
non-empty evidence citation from the candidate's CV.

**`sign_off` nullability (AC-5)**: The `decision.schema.json` encodes `sign_off` as
`oneOf: [{type: null}, {type: object, required: [recruiter, confirmed_at]}]`. The
`null` variant is the initial state; the object variant is written only when the
recruiter explicitly confirms.

**Append-only history**: The `runs` array in `history.json` is append-only. No entry
is ever removed or overwritten. This invariant is enforced at runtime by
`tabp_helper.py` (spec 02), not by the schema itself (JSON Schema cannot prevent
array-entry deletion at write time).

**Lock contract**: The `.tabp/.lock` requires `pid` (integer >= 1), `hostname`, and
`created_at`. Stale locks (process gone or different host) are reported for manual
removal, never auto-stolen.

**No `settings.schema.json` in spec 01**: The tabp settings schema is owned by
MAR-3. Adding it prematurely would activate the CI settings-schema validation step
for tabp. It is excluded from this spec.

#### Contract surface (spec 01 delivery)

| File | Kind | Runtime path |
|---|---|---|
| `plugins/tabp/schemas/run.schema.json` | JSON Schema Draft 2020-12 | `<project>/.tabp/runs/<run-id>/run.json` |
| `plugins/tabp/schemas/evidence.schema.json` | JSON Schema Draft 2020-12 | `<project>/.tabp/runs/<run-id>/evidence-<candidate-id>.json` |
| `plugins/tabp/schemas/decision.schema.json` | JSON Schema Draft 2020-12 | `<project>/.tabp/runs/<run-id>/decision.json` |
| `plugins/tabp/schemas/history.schema.json` | JSON Schema Draft 2020-12 | `<project>/.tabp/history.json` |
| `plugins/tabp/schemas/lock.schema.json` | JSON Schema Draft 2020-12 | `<project>/.tabp/.lock` |
| `plugins/tabp/schemas/samples/run.sample.json` | Validating sample | — |
| `plugins/tabp/schemas/samples/evidence.sample.json` | Validating sample | — |
| `plugins/tabp/schemas/samples/decision.sample.json` | Validating sample | — |
| `plugins/tabp/schemas/samples/history.sample.json` | Validating sample | — |
| `plugins/tabp/schemas/samples/lock.sample.json` | Validating sample | — |
| `plugins/tabp/schemas/README.md` | Contract documentation | — |

Executable validation of live state files is performed by `tabp_helper.py` (spec 02,
MAR-2). The schema files here are the contract source; the helper loads them at
runtime.

---

## Feature area: tabp independent verifier (MAR-37)

Every `screen-cvs` run is re-judged by an independent verifier subagent before
results are presented to the recruiter. This behavior implements the
engineering-rigor NFR (`prd.md:141-154`) and fulfils the upgrade-path note
deferred in MAR-2 (`SKILL.md:173-177` prior to MAR-37).

### Behavioral contract

**Always-on.** The verifier runs on every `screen-cvs` run with no skip path.
There is no condition under which the verifier invocation is bypassed (AC-4,
MAR-37). The coordinator spawns the verifier in Step 5a of
`plugins/tabp/skills/screen-cvs/SKILL.md` before any results are presented.

**Artifact-only, isolated context.** The verifier subagent
(`plugins/tabp/agents/screen-verifier-subagent.md`) operates in a separate spawn
context from the coordinator. It receives only persisted artifacts — parsed JD
requirements, all `evidence-*.json` records, the synthesis result,
`references/scoring-rubric.md`, and `references/fairness-guidelines.md` — passed
inline in the task payload. The coordinator must NOT include its own reasoning,
framing, or in-progress evaluation notes. The verifier is isolated from the
coordinator's perspective (AC-1, D1, ADR-0025).

**Five-check re-judgment (AC-2).** The verifier independently re-applies:

1. Evidence citations — every judgment cites a non-empty, specific CV source.
2. Must-have gate correctness — `Missing` judgments on must-haves map to
   `must_have_gate="Missing:<list>"` and `recommendation` in `{Hold, Reject}`.
3. Score/band/recommendation rubric consistency — thresholds and recommendation
   mapping applied identically per the rubric.
4. No protected or proxy criteria — no judgment references protected
   characteristics or their proxies.
5. Cross-candidate consistency — identical rubric weighting and fairness rules
   applied to every candidate.

**Structured `pass | blocking` verdict.** The verifier returns a JSON object:

```json
{"status": "pass" | "blocking", "blocking_findings": [...]}
```

Each entry in `blocking_findings` carries `candidate_id`, `finding_type`,
`requirement`, and `detail`.

**Remediate-and-re-verify loop capped at N=3 (AC-3, D2, ADR-0025).** If the
verdict is `blocking`, the coordinator remediates the flagged issues (re-spawning
affected `screen-cv-subagent` instances for evidence/fairness findings, or
re-running the synthesis subagent for rubric/consistency findings) and re-spawns
the verifier. The loop is capped at **N=3 total verifier invocations** (including
the initial one). This guarantees termination.

**Present-only-after-clean rule (AC-3).** Results (Step 6 — inline summary and
Excel scorecard) are delivered to the recruiter ONLY after the verifier returns a
clean `pass` verdict.

**Cap-hit behavior (AC-4).** If the N=3 cap is reached with unresolved blocking
findings, the coordinator:
- Writes `decision.json` with `verification_passed: false` and the unresolved
  `blocking_findings` in `verification_notes`.
- Does NOT proceed to Step 6 result delivery.
- Notifies the recruiter of the unresolved verification issues and advises against
  scorecard use without manual review.

**Independent verdict recorded in `decision.json`.** The `verification_passed`
and `verification_notes` fields in `decision.json` record the independent verifier
verdict (not a coordinator self-attestation). On a clean `pass`,
`verification_passed: true`. On cap-hit, `verification_passed: false` with
unresolved findings in `verification_notes`. This is the semantic meaning of
those fields from MAR-37 onwards (ADR-0025, C-3).

**No state writes by the verifier.** The verifier does not invoke
`tabp_helper.py`, does not write to `.tabp/`, and does not make Bash calls. Its
only output is the verdict JSON returned to the coordinator. State persistence
(updated evidence records on remediation, the decision record) is performed by
the coordinator.

**Namespace constraint (AC-5/AC-6).** The verifier charter and all MAR-37
changes to SKILL.md, the flow doc, the README, and the ADR use the tabp namespace
exclusively — no `acs:` prefix, no `.tabp/`-adjacent foreign paths, no helper
imports from other plugins.

### Contract surface (MAR-37 delivery)

| File | Kind | Change |
|---|---|---|
| `plugins/tabp/agents/screen-verifier-subagent.md` | Subagent charter | NEW — defines the verifier's role, artifact-only input contract, five re-judgment checks, and `pass\|blocking` output contract |
| `plugins/tabp/skills/screen-cvs/SKILL.md` Step 5a | Coordinator instruction | REPLACED — coordinator self-verification retired; independent verifier spawn + remediate loop (N=3) inserted |
| `plugins/tabp/skills/screen-cvs/SKILL.md` Step 5b | Coordinator instruction | UPDATED — records independent verifier verdict (`verification_passed`), not a coordinator self-attestation |
| `plugins/tabp/schemas/decision.schema.json` | JSON Schema | UPDATED — `verification_passed` and `verification_notes` descriptions updated to reflect independent verifier step |
| `docs/adr/0025-tabp-independent-verifier-subagent.md` | ADR | NEW — records D1 (inline-artifact input), D2 (N=3 cap), always-on rule, and residual risk |

---

## Feature area: tabp hybrid cost sourcing (MAR-38)

### MAR-38 hybrid cost model for usage-read aggregation

The `usage-read` subcommand (`tabp_helper.py _cmd_usage_read`) delivers real
aggregation over `history.json` and each `run.json`, replacing the MAR-6
placeholder stub that shipped with the tabp foundation.

#### Four usage_source semantics

The `usage.usage_source` field in `run.json` now carries one of four values,
each with defined semantics:

| `usage_source` | Meaning | `cost_basis` | Token source |
|---|---|---|---|
| `"claude-code"` | Run executed under Claude Code runtime | `"estimate"` | Actuals from `~/.claude/projects/<cwd-slug>/*.jsonl` (MAR-38 auto-detect) |
| `"estimate"` | Heuristic token estimate (e.g. Cowork estimate) | `"estimate"` | Pre-written tokens in `run.json usage.tokens_in/out` |
| `"cowork"` | Cowork self-reported usage (future hook, MAR-40) | `"actual"` | Self-reported in `run.json usage.tokens_in/out/cost_usd` |
| `"unavailable"` | No usage data available | `"unavailable"` | None — omitted from aggregate totals |

Runs with `usage_source="unavailable"` appear in the `runs[]` array but are
excluded from `total_tokens_in`, `total_tokens_out`, and `total_cost_usd`.

#### settings.json `model_pricing` (no schema file)

The tabp `settings.json` file accepts an optional `model_pricing` block:

```json
{
  "model_pricing": {
    "claude-opus-4-8":   { "input_per_mtok": 15.00, "output_per_mtok": 75.00 },
    "claude-sonnet-4-6": { "input_per_mtok":  3.00, "output_per_mtok": 15.00 }
  }
}
```

Values are USD per million tokens. If absent, the built-in `_MODEL_PRICING`
snapshot (frozen at `_PRICING_SNAPSHOT_DATE`) is used as the fallback.

**No `settings.schema.json` is created for this key** (DEV-1: the tabp settings
schema is owned by MAR-3; creating it prematurely activates the CI
settings-schema validation gate at `ci.yml:197-199`). The `model_pricing`
block is a runtime-read-only contract — read by `_resolve_pricing`, passed
through `settings-read` output when present, and documented here. Malformed
or non-numeric per-model entries are silently skipped (R5 additive safety).

#### Claude Code transcript reader privacy

The transcript reader (`_read_transcript_tokens`) reads ONLY:
- `message.usage.input_tokens` (integer)
- `message.usage.output_tokens` (integer)
- `message.model` (string)

It never reads `message.content`, any prompt text, CV content, or response
body. The return value is `(total_in: int, total_out: int, model: str|None)`.
No transcript content is persisted into `.tabp/` state files.

The transcript root defaults to `~/.claude/projects` and is injectable via the
`TABP_TRANSCRIPT_ROOT` environment variable (for testing — tests never read the
real `~/.claude` path).

#### `run-finalize` new arguments (MAR-38)

The `run-finalize` subcommand accepts three new optional arguments:

- `--tokens-in <int>`: input token count to write into `run.json usage.tokens_in`
- `--tokens-out <int>`: output token count to write into `run.json usage.tokens_out`
- `--cost-basis <actual|estimate|unavailable>`: cost basis label

The `--usage-source` argument is widened from two values to four:
`cowork`, `claude-code`, `estimate`, `unavailable`.

#### cost_basis labeling invariant (R2)

Cost derived from tokens x pricing is NEVER labeled `cost_basis="actual"`.
Only `usage_source="cowork"` (Cowork self-reported, future hook) may carry
`"actual"`. All derived costs (`claude-code`, `estimate`) carry `"estimate"`.
This invariant is enforced in the aggregation loop and tested by
`test_r2_mislabel_guard_cost_basis_always_set` in `TestUsageReadAggregation`.

#### Contract surface (MAR-38 delivery)

| File | Kind | Change |
|---|---|---|
| `plugins/tabp/helpers/tabp_helper.py` | Python stdlib helper | REPLACED `_cmd_usage_read` stub with real aggregation; added `_MODEL_PRICING`, `_PRICING_SNAPSHOT_DATE`, `_resolve_pricing`, `_cwd_slug`, `_read_transcript_tokens`, `_derive_cost`; extended `_cmd_run_finalize` args; extended `_cmd_settings_read` for `model_pricing` pass-through |
| `plugins/tabp/schemas/run.schema.json` | JSON Schema Draft 2020-12 | WIDENED `usage.usage_source` enum to four values; ADDED optional `usage.cost_basis` field |
| `plugins/tabp/schemas/history.schema.json` | JSON Schema Draft 2020-12 | WIDENED `runs[].usage_source` enum to four values |
| `docs/adr/0026-tabp-hybrid-cost-sourcing.md` | ADR | NEW — records D3a (transcript-actuals) and D3b (dated snapshot pricing + settings override) |

---

## Feature area: tabp usage skill (MAR-39)

### /tabp:usage skill — Show cost, time, and token usage for screening runs

The tabp plugin ships a second skill, `/tabp:usage`, as a thin presentation layer
over the `usage-read` aggregation that MAR-38 delivered. MAR-39 adds no new
aggregation logic, no new Python production code, and no changes to the helper
or schemas.

The skill lives at `plugins/tabp/skills/usage/SKILL.md` and is auto-discovered
by the runtime (skills auto-discover from `skills/<name>/SKILL.md`; no explicit
`skills` array in `plugin.json` is required).

#### Acceptance criteria (shipped — MAR-39 spec 01)

- **AC-1**: A new `/tabp:usage` skill exists at `plugins/tabp/skills/usage/SKILL.md`
  with frontmatter (`name: usage` and a `description` that triggers on
  usage/cost/tokens/spend requests), instructing the coordinator to invoke
  `python3 plugins/tabp/helpers/tabp_helper.py usage-read --project-dir <project-folder>
  [--run-id <id>|all]` and render the result. The skill is registered via
  auto-discovery (no `skills` array in `plugin.json`).

- **AC-2**: The skill renders BOTH per-run and aggregate TOTALS for cost (USD),
  time (`duration_seconds`), and tokens (in/out), surfacing `usage_source`,
  `cost_basis`, and `pricing_snapshot_date` so a derived cost is clearly labeled
  as an estimate and never presented as an actual billed amount.

- **AC-3**: Honest degradation: when usage data is unavailable
  (`usage_source="unavailable"`, or the helper/Bash is unavailable), the skill
  renders "—" for null fields, presents the `usage_note` from the helper, and
  never fabricates cost or token figures.

- **AC-4**: Documentation: a new `docs/architecture/lld/flows/tabp-usage-read.md`
  (Mermaid sequence diagram for the read flow) is added;
  `docs/architecture/hld/c4-container.md` and `docs/architecture/hld/tech-stack.md`
  skill count updated 1→2; `plugins/tabp/README.md` documents the new skill with
  a `### usage` subsection.

- **AC-5**: Namespace clean (see AC-6 contract at `docs/requirements/tabp.md:32-35`):
  no foreign namespace prefix, no foreign state-path token, no foreign library
  import appears in the new skill or any changed tabp artifact. All files stay
  within the tabp namespace. Structural tests in
  `tests/tabp/test_tabp_usage_skill.py` assert file existence, required
  frontmatter/sections, and the namespace guard. The full suite remains green
  (90% line-coverage target vacuously satisfied — no new executable Python added).

#### Presentation-only scope

MAR-39 is presentation only. It consumes the `usage-read` aggregation
(shipped in MAR-38) without modification:

- **No changes** to `tabp_helper.py`, `contracts.md`, `plugin.json`, `data-model.md`,
  or `plugins/tabp/schemas/`.
- **No new aggregation logic** — the skill renders the JSON output of
  `tabp_helper.py usage-read` as-is.
- **No e2e test flows** required — the skill is a coordinator-only read path
  with no interactive state changes; asserted at the structural level only.

#### Cost-transparency NFR

Any cost figure where `cost_basis="estimate"` must be labeled as an estimate
and never presented as an actual charge. The `pricing_snapshot_date` must be
surfaced so the reader knows which pricing snapshot was used. This is enforced
by Step 3 (Honesty rule) in `plugins/tabp/skills/usage/SKILL.md`.

#### Honest-degradation NFR

When usage data is unavailable for a run, the skill renders "—" for null
token/cost fields and displays the `usage_note`. It fabricates nothing. When
the helper/Bash is entirely unavailable, the skill states that usage data is
not accessible and fabricates nothing.

#### Contract surface (MAR-39 delivery)

| File | Kind | Change |
|---|---|---|
| `plugins/tabp/skills/usage/SKILL.md` | Coordinator protocol (SKILL.md) | NEW — /tabp:usage skill with frontmatter, usage-read invocation, per-run + totals rendering, honesty rule, degradation path, guardrails |
| `docs/architecture/lld/flows/tabp-usage-read.md` | LLD flow doc (Mermaid sequence) | NEW — /tabp:usage read flow with step annotations |
| `docs/architecture/hld/c4-container.md` | HLD C4 container diagram | EDIT line 13: `tabp_skills` skill count 1→2 (added /tabp:usage) |
| `docs/architecture/hld/tech-stack.md` | HLD tech-stack table | EDIT line 5: skill count 1→2; removed "not yet shipped" clause |
| `plugins/tabp/README.md` | Plugin README | EDIT: added `### usage` subsection under `## Skills`; refreshed "usage stubs" → "usage aggregation" |
| `tests/tabp/test_tabp_usage_skill.py` | Structural test module (stdlib unittest) | NEW — TU-01..TU-30 asserting file presence, frontmatter, invocation markers, rendering markers, honesty/degradation, namespace guard |
