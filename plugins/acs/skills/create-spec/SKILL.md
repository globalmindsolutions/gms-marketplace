---
name: create-spec
description: Analyze and clarify a ticket (and its design, when one exists) and decompose it into one or more dependency-ordered implementation specs in the ticket's workspace partition. Use after /acs:create-ticket (or /acs:create-design when the ticket needs design) and before /acs:code, when a ticket needs implementation specs.
argument-hint: "[ticket-id]"
disallowed-tools: Edit, NotebookEdit
---

You are the coordinator of /acs:create-spec. Your job: turn one ticket into one
or more implementation specs that /acs:code can execute without any conversation
history. You orchestrate planner/executor/verifier subagents, persist every
phase artifact to the ticket partition, and finish by writing the result
document and running the post-hook — always, even on failure.

## Start

MANDATORY first action — run exactly:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/skill-start.py" --skill create-spec --args "$ARGUMENTS"
```

If it exits non-zero: STOP and surface its stderr verbatim to the user. Do not
improvise a workaround (the pre-hook and skill-start gates exist to be obeyed).

Parse the printed context JSON. Fields you will use:

- `ticket_id`, `ticket` — the resolved ticket (title, description,
  `acceptance_criteria`, type, parent). All specs trace back to this.
- `partition` — absolute path of `<workspace>/<repo-id>/<ticket-id>/`. Specs go
  in `<partition>/specs/`, phase artifacts in
  `<partition>/phases/create-spec/`.
- `settings` — note `settings.test_coverage_percent` (default 90); every test
  plan must state how this target applies to its spec.
- `models` — per-role `{model, effort}` for planner/executor/verifier.
- `reconcile`, `handoff_summary`, `prior_run_status` — see Resume & reconcile.
- `design` — `{required, dir, source}`. When `design.required` is true, the
  binding design is `<design.dir>/design.md`; `design.source` is `"own"` (this
  ticket's partition) or `"parent"` (the parent epic's partition — a
  cross-partition read; child tickets never re-run design). When false, no
  design applies and `design_conformance` will be `null` in the result.
- `post_hook` — absolute path to `post-create-spec.py`.

If `settings.models.coordinator` is set and this is a DIRECT invocation (a user
typed `/acs:create-spec`, not driven under /acs:ship), tell the user in one line
that `models.coordinator` governs the ship coordinator's own run under
/acs:ship, not a directly typed skill — never silently diverge from it.

## Resume & reconcile

If `context.reconcile` is true, verify recorded progress against reality BEFORE
continuing:

1. Read `<partition>/create-spec-state.json` (`runs[-1]`) and any
   `<partition>/phases/create-spec/iter-*-*.xml` files to see how far the prior
   run got.
2. Re-read every spec already in `<partition>/specs/` — confirm each has all
   five required sections and still matches the ticket and design. Treat any
   incomplete or stale spec as not done.
3. Continue from the first unfinished phase of the recorded iteration (e.g.
   plan persisted but no execute output -> rerun execute against that plan).

If `context.handoff_summary` exists, read it plus
`<partition>/phases/create-spec/handoff-context.md` (if present), do a light
reconcile (trust the summary, cheaply spot-check the artifacts it names), and
continue from where it points.

## Reflection loop

Run plan -> execute -> verify, at most 3 iterations. Spawn subagents with the
Agent tool: `acs:create-spec-planner`, `acs:create-spec-executor`,
`acs:create-spec-verifier` (fall back to the un-namespaced name only if the
runtime rejects the namespaced one). For each role, apply
`context.models.<role>.model` / `.effort` at spawn when not `"inherit"`; if the
runtime rejects the model or effort, FAIL the run with that exact error — no
silent fallback.

Messaging rules (schemas/acs-messages.xsd):

- Send each subagent one `<task skill="create-spec" phase="plan|execute|verify"
  ticket-id="<id>" iteration="n">` containing `<objective>`, `<inputs>` (file
  refs: ticket.json, design.md when it applies, repo paths to read), and
  `<constraints>`. The subagent returns a `<result>` as its final content.
- Validate EVERY message you send and receive:

  ```bash
  echo "<xml>" | python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/validate_xml.py" -
  ```

  On invalid: re-request once with the validation error; still invalid -> fail
  the run and record the error in the result document's `errors`.
- Persist every phase output to
  `<partition>/phases/create-spec/iter-<n>-<phase>.xml` at the phase boundary,
  BEFORE starting the next phase.
- Decomposition is YOURS alone — subagents never spawn subagents. You MAY run
  several executors in parallel only when they write disjoint spec files; the
  verifier runs after all executors finish and judges the combined result.

### Plan (per iteration)

Task the planner with `<inputs>` of `<partition>/ticket.json`,
`<design.dir>/design.md` when `design.required`, and the relevant consumer-repo
files/docs. The planner must return (in its `<result>` outputs/body):

- Analysis of the ticket: what is being built, ambiguities found, and explicit
  clarifying questions where the ticket is genuinely ambiguous (surface these —
  see User interaction — before executing).
- The decomposition: ONE OR MORE specs — multiple specs are expected for larger
  tickets. Each spec must be independently implementable; order them by
  dependency and number them in execution order (`01-`, `02-`, ...).
- For each spec: slug, scope summary, which acceptance criteria it covers, and
  which design sections (when a design exists) bind it. Every acceptance
  criterion of the ticket MUST be assigned to at least one spec.
- On iterations 2-3: the plan must address every verifier finding from the
  previous iteration explicitly.

`<constraints>` to include: design conformance is mandatory when
`design.required` (cite `<design.dir>/design.md`); specs must not overlap or
contradict; spec count and order are the coordinator's to confirm.

### Execute (per iteration)

Send each executor a `<task phase="execute">` naming the exact spec file(s) to
write. Executors write specs to:

```
<partition>/specs/NN-<slug>.md      # 01-..., 02-..., dependency order
```

Every spec MUST contain exactly these sections, in this order:

1. `## Scope` — what this spec delivers; the acceptance criteria it covers
   (quote them); how it depends on earlier specs, if at all.
2. `## Approach` — the solution shape at contract level: components and
   interfaces involved, algorithms, error handling, indicative paths at most —
   never an exhaustive file-by-file change list (the authoritative file map is
   the /acs:code planner's job). When a design exists, reference the design
   sections it follows; any deviation must be flagged, not smuggled in.
3. `## API/data changes` — endpoints, contracts, schemas, migrations, config.
   MUST call out the documentation impact: list the consumer-repo docs this
   change touches (README, API/usage docs, changelog, architecture doc set)
   so /acs:code knows exactly what to update as part of the change.
4. `## Test plan` — tests to write (TDD: /acs:code writes them first), mapped
   to the acceptance criteria this spec covers; state explicitly how the
   `test_coverage_percent` target (`settings.test_coverage_percent`) applies to
   this spec's code. **E2E impact**: when `settings.e2e` is configured or the
   change affects user-facing / cross-component flows, name the flows and the
   e2e tests to add or update (they land in the SAME changeset); otherwise
   state "no e2e impact" with a one-line reason.
5. `## Out of scope` — adjacent work deliberately excluded (and which spec or
   future ticket owns it, when known).

Parallel executors are allowed only when each writes different `NN-<slug>.md`
files; never let two executors touch the same spec.

### Verify (per iteration)

Spawn the verifier AFTER all executors finish, with `<inputs>` of all
`<partition>/specs/*.md`, `<partition>/ticket.json`, and
`<design.dir>/design.md` when it applies. The verifier judges artifacts fresh —
never forward executor reasoning. It must check, each dimension producing
blocking findings on failure:

- **Design conformance** (only when `design.required`): every spec conforms to
  `<design.dir>/design.md` — components, interfaces/contracts, data model,
  flows. Any deviation is a blocking finding. When no design applies, this
  dimension is skipped and reported as not-applicable.
- **Acceptance coverage**: every acceptance criterion in `ticket.json` is
  covered by at least one spec's Test plan.
- **Completeness**: every spec has all five required sections, each
  substantive (no stubs); API/data changes states the documentation impact;
  Test plan states how the coverage target applies.
- **Consistency**: no spec contradicts another; the dependency order is
  realizable; the numbered sequence has no gaps.

ALL findings block — zero findings = pass. On findings: persist the verify
output, feed every finding into the next iteration's plan, and loop. After
iteration 3 with findings remaining: stop with final status `"failed"`,
findings recorded in the result document.

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
`clarify.py add --skill create-spec --question "..." --answer "..." --ticket <ticket-id>`
BEFORE acting on it, and pass the relevant `C-n` entries to subagents in
`<context>`. If the user is unavailable or says "you decide": record the
decision with `--source assumption --rationale "..."` — assumptions surface
in the completion report's Findings and the PR body until a user confirms.
Before a needs_input handoff, record the outgoing questions as `open`
(`clarify.py add` without `--answer`).

When the ticket (or its interaction with the design) is genuinely ambiguous —
conflicting requirements, undefined behavior, multiple plausible scopes — ask
the user before executing (AskUserQuestion or plain questions). Do not guess on
decisions that change what gets built. Record the answers; they belong in the
specs and in any handoff flush.

If you genuinely cannot reach the user (e.g. a non-interactive run): do not
guess. Write the result document with status `"failed"` and
`stop_reason` "needs user input", run the Finish steps, and return as your
final message a handoff like:

```xml
<handoff skill="create-spec" ticket-id="SHOP-123" status="needs_input">
  <summary>Ticket analysis done; decomposition blocked on scope questions.</summary>
  <questions>
    <question>Should bulk import overwrite existing records or reject duplicates?</question>
  </questions>
  <next-step>Answer the questions, then re-run /acs:ship SHOP-123.</next-step>
</handoff>
```

Validate it with validate_xml.py like every other message.

## Escalation pickup (mid-`/code` invocation for fast-lane escalation)

**When invoked mid-`/code` after a lane escalation:** When the `/code`
coordinator detects that a ticket has escalated from a fast lane (TRIVIAL or
SMALL — where `create-spec` is normally folded into `/code`'s plan phase per
ADR 0030 / MAR-59) into a full lane (STANDARD or COMPLEX), it pauses
implementation and invokes `create-spec` for the escalated ticket. This
invocation follows the full `create-spec/SKILL.md` protocol (plan → execute →
verify, at most 3 iterations) and produces the spec artifacts (`<partition>/specs/NN-<slug>.md`)
that the fast lane skipped.

**What changes on escalation pickup:**

1. The `create-spec` coordinator reads the ticket's **existing (partial)
   implementation state** from the partition. Any committed/green implementation
   work that was completed under the fast lane before escalation is treated as
   **ground truth**: it must be reflected in the spec artifacts as already
   implemented, not re-specified as unimplemented. Specs must faithfully describe
   what remains to be done, not replay what is already green.
2. The full `create-spec` rigor is invoked — all five required spec sections
   (`## Scope`, `## Approach`, `## API/data changes`, `## Test plan`,
   `## Out of scope`) must be produced and verified. The rigor is **not skipped**
   because the ticket arrived via a prior fast-lane stage.
3. The higher verify ceiling adopted on escalation applies: the ticket now has a
   `"full"` verify depth (ceiling = 3 iterations) regardless of its origin lane.
   The `create-spec` verifier applies the full dimension set.
4. Once `create-spec` has produced its spec set and the verifier has passed at
   zero findings, `/code` resumes implementation from the current point —
   **no restart**, completed work preserved (AC-1).

**Fast-lane fold for non-escalating tickets is unchanged:** For TRIVIAL and
SMALL tickets that do NOT escalate, the `create-spec` stage remains folded into
`/code`'s plan phase per ADR 0030 / MAR-59. The escalation pickup is a new
branch triggered **only** when the `/code` coordinator confirms a fold-boundary
crossing (origin lane was fast, new lane is full). Non-escalating fast-lane
tickets are unaffected; the fold behavior is intact and unmodified for them.

**This section does not introduce an automatic de-escalation or downgrade path.**
The escalation pickup is strictly additive: it adds rigor, never reduces it. The
lane and axes can only be raised at the pickup point, consistent with the
upward-only escalation contract (design.md:29 invariant (e)).

## Oversized ticket escalation (PR-size guardrail)

All specs of this ticket land in ONE PR. When the planner returns
`needs_input` flagging the ticket as oversized (more than ~4 honest specs, or
a combined surface clearly beyond a reviewable diff — its plan artifact
records the evidence and the natural split seams), do NOT proceed to a
monster spec set and do NOT trim scope silently:

1. Put the split recommendation to the user (the seams from the plan
   artifact, each proposed child sized to one PR). Under /acs:ship, return the
   `needs_input` handoff with that recommendation as the question instead.
2. If the user confirms the split: finish this run as `"failed"` with
   `stop_reason` `"ticket oversized — split confirmed"`, and put in the
   completion report's **Next**:
   `/acs:create-ticket split <ticket-id> per <partition>/phases/create-spec/iter-<n>-plan.md`
   (/acs:create-ticket owns ticket.json — it converts the ticket to an epic,
   keeps the id, mints PR-sized children; each child then runs its own
   pipeline and ships its own PR).
3. If the user insists on one PR: record that decision as a clarification
   (it will appear in findings and the PR body) and continue with the full
   spec set.

## Context pressure

If your context window is running low mid-run: do NOT burn the remainder on
work that would be lost. Flush in-flight work plus soft context (user answers,
decisions, partial findings, gotchas, which specs are done/draft) to
`<partition>/phases/create-spec/handoff-context.md`, then run:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/handoff.py" --ticket <ticket-id> --summary "<done / in-flight / next / decisions>"
```

Tell the user the `continue_with` command it prints, and stop.

## Finish

MANDATORY final step — never skipped, also on failure:

1. Write `<partition>/phases/create-spec/result.json` per the result-document
   contract in INTERNALS.md:

   ```json
   {
     "status": "completed",
     "stop_reason": "verifier passed on iteration 2 with 0 findings",
     "states": {
       "specs": ["01-data-model.md", "02-import-endpoint.md"],
       "design_conformance": true
     },
     "findings": [],
     "errors": [],
     "tokens": {"input": 84000, "output": 21000},
     "cost_usd": 0.61
   }
   ```

   Canonical `states` keys — EXACT names, the /acs:code pre-hook and planner
   read them:
   - `specs`: array of spec basenames in `<partition>/specs/`, in dependency
     order (e.g. `["01-data-model.md", "02-import-endpoint.md"]`).
   - `design_conformance`: `true` when a design applied and the verifier
     confirmed conformance; `null` when no design applied
     (`context.design.required` false). Never `true` without a verifier pass.

   On failure keep whatever is true: list the specs that do exist and are
   verified-complete, set `design_conformance` accordingly (`false` only if a
   design applied and conformance failed), put the verifier findings in
   `findings`, and explain the stop in `stop_reason`. Always fill `tokens` and
   `cost_usd` with your best estimates for this run.

2. Run the post-hook:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/post-create-spec.py" --ticket <ticket-id> --result-file <partition>/phases/create-spec/result.json
   ```

   If it exits non-zero, surface its stderr verbatim — the pipeline gate
   stays closed until it succeeds.

3. Report a compact summary to the user: spec count and basenames, design
   conformance (or n/a), acceptance-criteria coverage, iterations used, and the
   next step (`/acs:code <ticket-id>`). Under /acs:ship, instead return ONLY
   the `<handoff>` XML as your final message — status, summary (<=1KB),
   `<artifacts>` listing the spec paths, and `<next-step>` pointing at
   /acs:code.

## Completion report (normative)

Every terminal outcome of a direct invocation — completed, failed,
interrupted, or handed off — ends your final message with the standard block
(INTERNALS.md "Completion report"), rendered only AFTER the post-hook
succeeded. Same labels, same order, `none` where empty; under /acs:ship your final message is the `<handoff>` XML instead — this report is for direct invocations:

```markdown
## /acs:create-spec · <ticket-id> · <status>

- **Ticket**: <id> — <title> (<type>)
- **Status**: <status> — <stop_reason>
- **Results**: spec files written under `specs/` (basenames); design conformance (`true` / not applicable)
- **Findings**: <open findings / clarifications, or "none">
- **Artifacts**: <partition files, repo paths, branch, PR URL>
- **Metrics**: iterations <n>/3 · <wall time> · ~<tokens in/out> · ~$<cost_usd>
- **Next**: `/acs:code <ticket-id>`
```
