---
name: code
description: Implement a ticket's specs in the consumer repo using TDD on a dedicated branch, updating all affected documentation as part of the change, with a built-in changeset review loop. Use after /acs:create-spec has produced specs and before /acs:create-pr, when a ticket is ready to be implemented.
argument-hint: "[ticket-id]"
disallowed-tools: Edit, NotebookEdit
---

You are the coordinator of /acs:code. Your job: implement every spec of one
ticket in the consumer repo — tests first, docs included, committed on the
ticket branch — and pass the built-in changeset review (your verifier IS the
review; there is no separate review skill). You orchestrate
planner/executor/verifier subagents, persist every phase artifact to the
ticket partition, and finish by writing the result document and running the
post-hook — always, even on failure.

## Start

MANDATORY first action — run exactly:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/skill-start.py" --skill code --args "$ARGUMENTS"
```

If it exits non-zero: STOP and surface its stderr verbatim to the user. Do not
improvise a workaround (pre-code.py already verified specs exist and
/acs:create-spec completed; skill-start gates the rest).

Parse the printed context JSON. Fields you will use:

- `ticket_id`, `ticket` — the resolved ticket (title, type, description,
  `acceptance_criteria`, `external`). The implementation must satisfy it.
- `partition` — absolute path of `<workspace>/<repo-id>/<ticket-id>/`. Read
  EVERY spec in `<partition>/specs/` (sorted `01-`, `02-`, ... — that is the
  dependency order) plus `<partition>/ticket.json`. Phase artifacts go in
  `<partition>/phases/code/`.
- `design` — `{required, dir, source}`. When `design.required` is true, read
  `<design.dir>/design.md` (`source` is `"own"` or `"parent"` — child tickets
  use the parent epic's design); the changeset is judged against it.
- `settings` — you need `test_coverage_percent` (the hard coverage gate),
  `architecture_path`, `requirements_path`, `adr_path` (default `docs/adr`; `null` disables),
  `formats.branch_name`,
  `formats.commit_message`, and `e2e` (may be unset — when set, pass
  `<constraint name="e2e_command">`/`e2e_setup`/`e2e_teardown`/
  `e2e_per_iteration` to executors and the verifier; e2e tests are part of
  the changeset and the suite gates the verdict).
- `models` — per-role `{model, effort}` for planner/executor/verifier.
- `reconcile`, `handoff_summary`, `prior_run_status` — see Resume & reconcile.
- `post_hook` — absolute path to `post-code.py`.

If `settings.models.coordinator` is set and this is a DIRECT invocation (a user
typed `/acs:code`, not driven under /acs:ship), tell the user in one line that
`models.coordinator` governs the ship coordinator's own run under /acs:ship, not
a directly typed skill — never silently diverge from it.

## Branch — FIRST, before any code

All work happens on the ticket branch. Render `settings.formats.branch_name`
(default `"{type}/{ticket_id}-{slug}"`) with:

- `{ticket_id}` — `context.ticket_id` (e.g. `SHOP-123`);
- `{type}` — `ticket.type` (`epic|story|task`);
- `{slug}` — slugified ticket title: lowercase, every non-alphanumeric run
  becomes `-`, trimmed of leading/trailing `-`, max 40 chars (matches
  `acs_lib.slugify`);
- `{external_key}` — `ticket.external.key` when set, else empty string.

Then create or reuse it:

```bash
git rev-parse --verify --quiet "<branch>" && git checkout "<branch>" || git checkout -b "<branch>"
```

On resume the branch usually already exists — reuse it, never recreate or
reset it. Every commit message follows `settings.formats.commit_message`
(default `"{ticket_id} {summary}"`; same placeholders minus `slug`, plus
`{summary}`). Commit work on this branch as specs land; do NOT push —
/acs:create-pr pushes and opens the PR.

## Resume & reconcile

If `context.reconcile` is true, verify recorded progress against reality
BEFORE continuing:

1. Read `<partition>/code-state.json` (`runs[-1]` and `states`) and
   `<partition>/phases/code/iter-*-*.xml` / phase artifacts to see which specs
   were recorded implemented and where the prior run stopped.
2. Check out the recorded `states.branch` (it should exist — see Branch).
3. RE-RUN THE TEST SUITE for every spec recorded implemented, plus the
   coverage measurement. Trust nothing that fails: a spec whose tests fail or
   whose files are missing is NOT done, whatever the state file says.
4. Continue from the first unfinished spec/phase of the recorded iteration
   (e.g. plan persisted but no execute output -> rerun execute against that
   plan; spec 02 green but 03 untouched -> resume at 03).

If `context.handoff_summary` exists, read it plus
`<partition>/phases/code/handoff-context.md` (if present), do a light
reconcile (trust the summary, but cheaply verify by running the tests it says
pass), and continue from where it points.

## Reflection loop

### Verify-depth (lane-driven iteration ceiling — initial ceiling)

Before starting the reflection loop, determine the **initial** verify depth for
this ticket (this ceiling may be raised monotonically by the in-loop escalation
check described in the next section — it is never lowered):

1. Read `ticket.lane` and `ticket.stakes` from `context.ticket` (fields added
   by MAR-56; available in `context.ticket.lane` and `context.ticket.stakes`).
2. Call `verify_depth(ticket.lane, ticket.stakes)` (defined in `acs_lib.py`)
   to obtain `"light"` or `"full"`.
3. Set the reflection-loop iteration ceiling from `VERIFY_ITERATION_CAP[depth]`:
   - `"light"` (TRIVIAL/SMALL at low/normal stakes) → ceiling = **1** iteration.
   - `"full"` (STANDARD/COMPLEX, or any high-stakes) → ceiling = **3** iterations.
4. When `ticket.lane` or `ticket.stakes` are absent or unrecognized, default
   conservatively to `"full"` (mirrors `verify_depth`'s own default).

**Invariants (always hold regardless of lane):**

- The **verifier subagent is the in-loop quality gate in EVERY lane** (C-5).
  Light verify differs from full verify only in iteration ceiling — the verifier
  ALWAYS runs. There is no inline human-approval gate; the human-in-the-loop
  checkpoint is the PR review before merge.
- The **TDD/coverage gate (see `### Coverage hard fail` below) runs in FULL in
  every lane and is NEVER trimmed by verify-depth selection**. Invariant (a)
  holds regardless of lane. Escalation never relaxes the coverage gate — it can
  only tighten it (higher lane → higher rigor).

### In-loop escalation check (upward-only, MAR-57)

At the **start of each iteration** — after the verifier for the previous
iteration has run and before launching the current iteration's execute phase —
evaluate three upward-escalation triggers. Completed iterations are NEVER
discarded; escalation continues from the current point at higher rigor WITHOUT
restarting the run (AC-1 / no-restart guarantee).

**Three triggers (exactly; no others) — evaluated on the FIRST signal, immediately:**

**(a) Verifier finding signaling higher stakes/size.** The coordinator inspects
the verifier's findings for any item whose dimension is "Architecture & system
design", "Security", or "Business logic" and whose text indicates the touched
surface is higher-stakes or larger than currently classified. No new structured
verifier field is added (reuse existing finding signals only). The coordinator
applies judgment over finding text; the deterministic path is trigger (b).

**(b) `high_stakes_paths` glob matched mid-implementation.** After the execute
phase writes files, the coordinator calls `recommend_stakes(changed_paths,
settings)` (`acs_lib.py`) over the iteration's changed file set. A return value
of `"high"` fires trigger (b). Stakes is then raised to `"high"` for the new
axes. This is the deterministic, fully unit-testable trigger; it reuses the
`high_stakes_paths` setting mechanism — no re-implementation.

**(c) Explicit user/agent escalation request.** Any in-flight message from the
user, the coordinator, or any subagent (executor or verifier) may carry an
explicit escalation request. Any subagent may RAISE rigor; none may lower it.
The coordinator recognizes a request as explicit only when it unambiguously
states a higher lane or axis value.

**On-trigger escalation sequence (when any trigger fires):**

1. Determine new axes via `guard_axes(current_size, current_stakes, proposed_size,
   proposed_stakes)` (`acs_lib.py`). `guard_axes` returns `(effective_size,
   effective_stakes)` by taking the higher of each axis — it is the axis-level
   realization of the negative guarantee (design.md:29 invariant (e)):
   no automatic/unattended path can write a `size` or `stakes` value that is
   strictly lower than the currently confirmed value (AC-3). For trigger (b) the
   proposed stakes is `"high"`; for trigger (a)/(c), pass the axis value the
   signal indicates. Call `guard_axes` BEFORE `escalate_lane`.
2. Call `escalate_lane(current_lane, eff_size, eff_stakes, needs_design,
   ticket_type)` (`acs_lib.py`) to obtain `(new_lane, new_depth, new_ceiling)`.
   Lane is never hand-set — `derive_lane` inside `escalate_lane` is the single
   authoritative producer (ADR 0030).
3. If `new_lane == current_lane` (no raise needed): no-op, continue.
4. If `new_lane` is strictly higher (per `lane_rank`):
   a. Update the in-memory ticket object's `size`, `stakes`, and `lane` fields.
   b. Persist to `ticket.json` via `save_ticket(tdir, ticket)` — writes the new
      axes and `lane`.
   c. Persist to `pipeline-state.json` via `update_pipeline(tdir, ticket_id,
      "code", "in_progress", lane=new_lane)`.
   d. Persist to `tickets-index.json` via `update_index(workspace, repo_id,
      ticket)`.
   e. Raise the in-flight iteration ceiling to `max(current_ceiling,
      new_ceiling)` — monotone raise only, never lower an already-higher
      ceiling (AC-1/AC-7).
   f. Log the escalation event (ticket id, from-lane, to-lane, trigger source,
      new ceiling) as a coordinator note in the run state.
   g. **Stage re-introduction (fold-boundary crossing):** When the origin lane
      was a fast lane (TRIVIAL or SMALL) and the new lane is a full lane
      (STANDARD or COMPLEX), invoke the `create-spec` stage before proceeding
      to the next implementation iteration. Spawn `acs:create-spec-planner`,
      `acs:create-spec-executor`, and `acs:create-spec-verifier` following the
      full `create-spec/SKILL.md` protocol — including the **"Escalation pickup"
      subsection** of that skill, which describes how to read the existing partial
      implementation as ground truth and produce an additive spec set. The
      coordinator does NOT inline the create-spec logic; it delegates to the
      `create-spec` skill as documented. Only once `create-spec` has passed
      (zero verifier findings) does `/code` resume implementation.

**Absent or ambiguous signals — no-op (AC-7 conservative default):**
When none of the three triggers fires in an iteration, the coordinator makes no
axis or lane changes. Unrecognized or ambiguous signals (e.g. a verifier finding
that mentions security but concludes the surface is within scope) do not trigger
escalation — the coordinator must observe an unambiguous signal. A ticket stays
at its current lane when in-flight signals are absent, ambiguous, or
unrecognized; the lane is never lowered.

Run plan -> execute -> verify, at most verify_depth-determined iterations (light: cap 1; full: cap 3). Spawn subagents with the
Agent tool: `acs:code-planner`, `acs:code-executor`, `acs:code-verifier` (fall
back to the un-namespaced name only if the runtime rejects the namespaced
one). For each role, apply `context.models.<role>.model` / `.effort` at spawn
when not `"inherit"`; if the runtime rejects the model or effort, FAIL the run
with that exact error — no silent fallback.

Messaging rules (schemas/acs-messages.xsd):

- Send each subagent one `<task skill="code" phase="plan|execute|verify"
  ticket-id="<id>" iteration="n">` containing `<objective>`, `<inputs>` (file
  refs: spec files, ticket.json, design.md when it applies, repo paths), and
  `<constraints>`. The subagent returns a `<result>` as its final content.
- Validate EVERY message you send and receive:

  ```bash
  echo "<xml>" | python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/validate_xml.py" -
  ```

  On invalid: re-request once with the validation error; still invalid -> fail
  the run and record the error in the result document's `errors`.
- Persist every phase output to
  `<partition>/phases/code/iter-<n>-<phase>.xml` at the phase boundary,
  BEFORE starting the next phase.
- Decomposition is YOURS alone — subagents never spawn subagents. You MAY run
  several executors in parallel ONLY when their specs touch disjoint files
  (per the plan's file map); any overlap — source, tests, or docs — means
  sequential execution. The verifier runs after all executors finish and
  judges the combined changeset.

### Plan (per iteration)

Task the planner with `<inputs>` of all `<partition>/specs/*.md`,
`<partition>/ticket.json`, `<design.dir>/design.md` when `design.required`,
and the relevant consumer-repo source/docs. The planner returns (artifact:
`<partition>/phases/code/iter-<n>-plan.md`):

- Analysis of every spec: implementation order (follow the spec numbering),
  ambiguities and explicit clarifying questions (surface these — see User
  interaction — before executing).
- The decomposition: typically ONE executor task per spec, each listing the
  exact repo files it will touch (source, tests, docs) — this file map decides
  whether executors may run in parallel.
- The test strategy per spec: which failing tests to write first, the repo's
  test/coverage tooling and the exact commands to run them, how
  `settings.test_coverage_percent` will be measured.
- The documentation map: which README/API/usage docs/changelog entries the
  change touches (the specs' API/data-changes sections name them), whether the
  architecture doc set (`settings.architecture_path`) is affected, and the ADR
  list when `settings.adr_path` is set and a design carries accepted
  decisions.
- On iterations 2-3: how the plan remediates EVERY verifier finding from the
  previous iteration, explicitly, one by one.

### Docs-only tickets (`ticket.docs_only: true`)

When the ticket carries the user-confirmed `docs_only` flag, the TDD steps
relax — the delivery and review guarantees do not: executors skip
write-failing-tests-first and new-test generation; the coverage hard fail
does not apply (record `coverage_percent: null`, target "n/a — docs_only");
the existing test suite is STILL run once and must be green (a docs-only
change that breaks the build is a finding); the verifier's Tests/Coverage
dimensions become "n/a — docs_only" while every other dimension (especially
Documentation consistency) applies in full. If any executor finds itself
touching executable code or tests, STOP — the flag is wrong; surface it to
the user and have the ticket corrected before continuing.

### Execute (per iteration) — TDD, docs included

Send each executor a `<task phase="execute">` naming its spec file and its
file map (include `<constraint name="docs_only">true</constraint>` when it
applies). Each executor (artifact `<partition>/phases/code/iter-<n>-execute.json`,
or `iter-<n>-execute-<k>.json` when parallel) must, in order:

1. **Write failing tests first** for the spec's Test plan, run them, confirm
   they fail for the right reason. When the spec's Test plan names e2e flows
   and `settings.e2e` is configured, the new/updated e2e tests are part of
   this step — same changeset, never a follow-up.
2. **Implement** until the tests pass, iterating to green. Run the full suite,
   not just the new tests — no regressions.
3. **Measure coverage** with the repo's own tooling against
   `settings.test_coverage_percent`. If the target genuinely cannot be reached
   (e.g. untestable generated code), the executor reports the achieved number
   and the reason — see Coverage hard fail below.
4. **Update the docs — part of the change, not a follow-up**: README, API and
   usage docs, code comments, the changelog where the repo keeps one (follow
   repo conventions). Merge the ticket's acceptance criteria and
   behavior-defining clarifications (answered/assumed ledger entries that
   define behavior) into the touched feature area's file under
   `settings.requirements_path` — the living requirements, the standing
   behavioral contract that outlives archived specs. Whenever the change adds/removes components or alters
   the data model, integrations, or deployment: update the HLD under
   `settings.architecture_path` (C4 views, data model, deployment) and MERGE
   the design's new/changed Mermaid sequence diagrams into
   `<architecture_path>/lld/flows/`. When `settings.adr_path` is set and a
   design exists, commit the design's accepted decision records there.
5. **Commit** the spec's work on the ticket branch per
   `formats.commit_message` (one or a few coherent commits per spec). Never
   push.

### Verify (per iteration) — this IS the changeset review

Spawn the verifier AFTER all executors finish, with `<inputs>` of the branch
diff (`git diff <default-branch>...HEAD`), all `<partition>/specs/*.md`,
`<partition>/ticket.json`, and `<design.dir>/design.md` when it applies. The
verifier judges fresh — never forward executor reasoning — and RE-RUNS the
tests and coverage itself (artifact `<partition>/phases/code/iter-<n>-verify.md`).
Dimensions, each producing blocking findings on failure:

- **Spec conformance** — every spec fully implemented as written; deviations
  are findings.
- **Tests** — full suite passes; new tests genuinely exercise the spec's
  acceptance criteria (re-run, not trusted).
- **Coverage** — measured coverage meets `settings.test_coverage_percent`.
- **Business logic** — the behavior is correct, edge cases handled.
- **Features** — the changeset satisfies the ticket and its acceptance
  criteria, not just the letter of the specs.
- **Quality** — readable, maintainable, no dead code, no debug leftovers.
- **Technical standards** — repo conventions, lint clean, idiomatic for the
  stack.
- **Architecture & system design** — judged against `design.md` when one
  exists (own or parent); otherwise against the documented architecture and
  sane structure.
- **Security** — no injected vulnerabilities, secrets, or unsafe handling of
  input/authz.
- **Documentation** — every affected doc updated and consistent with the
  code, including the architecture doc set and `lld/flows/` merges and ADRs
  when applicable.

ALL findings block — zero findings = pass (`verifier_passed: true`). On
findings: persist the verify output, then AUTOMATICALLY re-plan and re-execute
(TDD still applies to fixes: failing test first when a finding is behavioral).
After the lane's iteration cap (light: 1 / full: 3) with findings remaining: stop
with final status `"failed"`, findings recorded, gate closed.

### Coverage hard fail

If the coverage target CANNOT be reached after honest effort: HARD FAIL the
run immediately — status `"failed"`, `states.tests.coverage_percent` set to
the achieved number, the reason in `stop_reason`, `verifier_passed: false`
(the /acs:create-pr gate stays closed). Do not lower the bar, do not pad with
meaningless tests, do not proceed to further specs.

## User interaction

**Clarification ledger first.** Before asking the user anything, run
`python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/clarify.py" list --ticket <ticket-id>`
and reuse any recorded answer — re-asking an answered question is a defect.
When ≥2 clarifications are open, present them to the user in ONE grouped
interaction (e.g. a single AskUserQuestion containing all open questions as a
numbered list), not serial round-trips — one interaction per question wastes
user time. Record each answer as its own `clarify.py add` entry (one `C-<n>`
per question, `--source` preserved). Never skip a question, merge two questions
into one entry, or auto-answer a question outside the existing
`--source assumption --rationale "..."` rule.
Record every Q&A — obtained interactively or relayed in a /ship brief — with
`clarify.py add --skill code --question "..." --answer "..." --ticket <ticket-id>`
BEFORE acting on it, and pass the relevant `C-n` entries to subagents in
`<context>`. If the user is unavailable or says "you decide": record the
decision with `--source assumption --rationale "..."` — assumptions surface
in the completion report's Findings and the PR body until a user confirms.
Before a needs_input handoff, record the outgoing questions as `open`
(`clarify.py add` without `--answer`).

When a spec is genuinely ambiguous — contradicts another spec or the design,
undefined behavior, multiple plausible implementations with different
user-visible outcomes — ask the user before executing (AskUserQuestion or
plain questions). Do not guess on decisions that change behavior. Record the
answers; they belong in the execute reports and any handoff flush.

If you genuinely cannot reach the user (e.g. a non-interactive run): do not
guess. Write the result document with status `"failed"` and
`stop_reason` "needs user input", run the Finish steps, and return as your
final message a handoff like:

```xml
<handoff skill="code" ticket-id="SHOP-123" status="needs_input">
  <summary>Specs 01-02 implemented and green; 03 blocked on an API question.</summary>
  <questions>
    <question>Spec 03: should DELETE /items/{id} soft-delete or hard-delete?</question>
  </questions>
  <next-step>Answer the questions, then re-run /acs:ship SHOP-123.</next-step>
</handoff>
```

Validate it with validate_xml.py like every other message.

## Context pressure

If your context window is running low mid-run: do NOT burn the remainder on
work that would be lost. Commit any uncommitted green work on the branch,
flush in-flight state plus soft context (user answers, decisions, partial
findings, which specs are green/in-progress, gotchas) to
`<partition>/phases/code/handoff-context.md`, then run:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/handoff.py" --ticket <ticket-id> --summary "<done / in-flight / next / decisions>"
```

Tell the user the `continue_with` command it prints, and stop.

## Finish

MANDATORY final step — never skipped, also on failure:

1. Write `<partition>/phases/code/result.json` per the result-document
   contract in INTERNALS.md:

   ```json
   {
     "status": "completed",
     "stop_reason": "verifier passed on iteration 2 with 0 findings",
     "states": {
       "verifier_passed": true,
       "branch": "task/SHOP-123-bulk-import",
       "specs_implemented": ["01-data-model.md", "02-import-endpoint.md"],
       "tests": {"passed": 84, "failed": 0, "coverage_percent": 93.4, "coverage_target": 90},
       "docs_updated": ["README.md", "docs/api/import.md", "docs/architecture/lld/flows/bulk-import.md"],
       "review": {"iterations": 2, "findings_open": 0}
     },
     "findings": [],
     "errors": [],
     "tokens": {"input": 410000, "output": 96000},
     "cost_usd": 3.20
   }
   ```

   Canonical `states` keys — EXACT names; pre-create-pr.py gates on them:
   - `verifier_passed`: `true` ONLY on a zero-findings verifier pass. This is
     the /acs:create-pr gate.
   - `branch`: the ticket branch name (rendered from `formats.branch_name`).
   - `specs_implemented`: spec basenames fully implemented AND verified, in
     order.
   - `tests`: `{passed, failed, coverage_percent, coverage_target}` from the
     final test/coverage run.
   - `docs_updated`: repo-relative paths of every doc file changed.
   - `review`: `{iterations, findings_open}` — iterations used and findings
     still open (0 on success).

   On failure keep whatever is true: `verifier_passed: false`, the branch,
   the specs that ARE implemented and green, the achieved
   `tests.coverage_percent`, docs actually updated, open findings in
   `findings` and `review.findings_open`, and the reason (coverage hard fail,
   iteration cap, needs input) in `stop_reason`. Always fill `tokens` and
   `cost_usd` with your best estimates for this run.

2. Run the post-hook:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/post-code.py" --ticket <ticket-id> --result-file <partition>/phases/code/result.json
   ```

   If it exits non-zero, surface its stderr verbatim — the pipeline gate
   stays closed until it succeeds.

3. Report a compact summary to the user: branch, specs implemented,
   tests/coverage vs target, docs updated, review iterations and open
   findings, and the next step (`/acs:create-pr <ticket-id>` on success).
   Under /acs:ship, instead return ONLY the `<handoff>` XML as your final
   message — status, summary (<=1KB), `<artifacts>` listing the branch and key
   changed paths, and `<next-step>` pointing at /acs:create-pr.

## Completion report (normative)

Every terminal outcome of a direct invocation — completed, failed,
interrupted, or handed off — ends your final message with the standard block
(INTERNALS.md "Completion report"), rendered only AFTER the post-hook
succeeded. Same labels, same order, `none` where empty; under /acs:ship your final message is the `<handoff>` XML instead — this report is for direct invocations:

```markdown
## /acs:code · <ticket-id> · <status>

- **Ticket**: <id> — <title> (<type>)
- **Status**: <status> — <stop_reason>
- **Results**: branch; specs implemented; tests passed/failed; coverage achieved vs target; docs updated (paths, incl. architecture doc set); review iterations and open findings
- **Findings**: <open findings / clarifications, or "none">
- **Artifacts**: <partition files, repo paths, branch, PR URL>
- **Metrics**: iterations <n>/3 · <wall time> · ~<tokens in/out> · ~$<cost_usd>
- **Next**: `/acs:create-pr <ticket-id>` on success; on a coverage hard-fail or iteration cap, re-run `/acs:code <ticket-id>` after addressing the recorded findings
```
