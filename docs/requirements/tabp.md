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
