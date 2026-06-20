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
