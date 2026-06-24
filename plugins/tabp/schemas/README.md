# tabp plugin — JSON Schema contracts

This directory contains the machine-checkable JSON Schema Draft-2020-12 contracts
for every `.tabp/` state entity, committed validating samples, and this README.

All `$id` URIs and all field names use tabp-namespaced paths.
No `acs` prefix and no `dot-acs-slash` token appear in any schema file, sample, or this
README (HARD namespace constraint, design.md:120-127, AC-6).

---

## Entity table

| Entity | Runtime path | Schema file | Description |
|---|---|---|---|
| Run record | `<project>/.tabp/runs/<run-id>/run.json` | `run.schema.json` | Per-run execution record: status, usage, metadata |
| Evidence record | `<project>/.tabp/runs/<run-id>/evidence-<candidate-id>.json` | `evidence.schema.json` | Per-candidate judgments with cited CV evidence |
| Decision record | `<project>/.tabp/runs/<run-id>/decision.json` | `decision.schema.json` | Human review sign-off record |
| Run history | `<project>/.tabp/history.json` | `history.schema.json` | Append-only array of run summaries |
| Lock | `<project>/.tabp/.lock` | `lock.schema.json` | Project-folder lock held during an active run |
| Settings | `<project>/tabp settings.json` | `settings.schema.json` | Optional recruiter configuration: model selection, CV/JD folder paths, state write mode. All fields optional with documented defaults. |

Validating samples for each entity live under `samples/`.

---

## Invariants

Enforced at runtime by `tabp_helper.py` (see `plugins/tabp/helpers/tabp_helper.py`, spec 02).
The schema files define the structural contract; the helper implements the runtime enforcement.

1. **`runs[-1]` is current status**: The last entry in `history.json`'s `runs` array is the
   current status of the most recent run. Nothing is mirrored at the top level.

2. **`in_progress` means resumable**: `status = "in_progress"` in the run record means the
   run directory `<project>/.tabp/runs/<run-id>/` exists and the run can be resumed.

3. **Evidence and decision records are append/update only within an `in_progress` run**:
   Evidence records (`evidence-<candidate-id>.json`) and the decision record (`decision.json`)
   are written only while the run status is `in_progress`.

4. **Lock held while `in_progress`; stale locks are reported, not stolen**: The `.tabp/.lock`
   file is held for the duration of a run. If a stale lock is found (process gone or different
   host), `tabp_helper.py` reports it for manual removal rather than overwriting it.

5. **No entry is ever deleted; archives are never purged**: No entry in `history.json` or any
   per-run file is removed. The append-only invariant cannot be expressed in JSON Schema — it
   is enforced entirely at the write path by `tabp_helper.py`.

---

## PII-minimal rule

Source: `design.md:129-132`. Records keep personal data minimal:

- `candidate_name` holds only the candidate's name or an anonymised label (e.g. `"Candidate A"`).
- **No contact details** (email, phone, address) in any state file.
- **No protected-class attributes** (age, gender, race, religion, disability status, etc.).
- **No secrets** (passwords, API keys, personal identification numbers) in state files.

This is a process constraint on the writing side (the helper and the skill coordinator).
It is documented here for auditability; JSON Schema cannot enforce it structurally.

---

## Namespace note

All `$id` URIs follow the pattern:

```
https://github.com/globalmindsolution/gms-marketplace/plugins/tabp/schemas/<entity>.schema.json
```

The tabp plugin uses tabp-namespaced identifiers throughout. No identifiers or file names
in this directory use the `acs` plugin namespace.

---

## Executable validation

Runtime validation of state files is performed by `tabp_helper.py validate`
(see `plugins/tabp/helpers/tabp_helper.py`, spec 02). The schema files in this directory
are the contract source; the helper loads them and runs the stdlib-based validator against
live state records. Samples in `samples/` are designed to pass the spec-02 validator when
it is applied.

### Settings validation

`settings.schema.json` covers `<project>/tabp settings.json` — the
recruiter-facing configuration file. This is distinct from the five `.tabp/`
state entity schemas above.

Validation is performed by a separate subcommand:
```
python3 plugins/tabp/helpers/tabp_helper.py settings-validate --project-dir <path>
```
This is NOT the same as `tabp_helper.py validate` (which covers the five
`.tabp/` state entities: run, evidence, decision, history, lock).

All five fields in `settings.schema.json` are optional; an absent
`tabp settings.json` file is valid and the helper falls back to documented
defaults. The schema enforces `additionalProperties: false` to block
unrecognised keys (including forbidden keys such as `workspace_path`).
