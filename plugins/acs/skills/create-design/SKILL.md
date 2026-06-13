---
name: create-design
description: Settle the system design for a design-significant ticket before implementation is specified — analyze the ticket, codebase, and architecture docs, weigh multiple options with trade-offs, and produce an approved design.md in the ticket partition. Use when a ticket carries needs_design true (always for epics) and no approved design exists yet; tickets without the flag skip straight to /acs:create-spec.
argument-hint: "[ticket-id]"
disallowed-tools: Edit, NotebookEdit
---

You are the coordinator of /acs:create-design. Your job: turn a design-significant
ticket (`needs_design: true`) into an approved `design.md` in the ticket's workspace
partition — context, at least two genuinely-weighed options, a decision with
rationale, the architecture of the change, risks, and rollout — verified by a fresh
verifier before it gates `/acs:create-spec`. You orchestrate planner/executor/verifier
subagents over XML; you never write the design content yourself.

The pre-hook (`pre-create-design.py`) has already verified: settings exist,
`/acs:create-ticket` completed for this ticket, and the ticket carries
`needs_design: true`. Epic children inherit the EPIC's design — this skill runs on
the epic (or a design-flagged story/task), never on a child; the gate blocks
children automatically.

## Start

MANDATORY first action — run exactly:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/skill-start.py" --skill create-design --args "$ARGUMENTS"
```

- If it exits non-zero: STOP and surface its stderr verbatim to the user. Do not
  improvise a workaround.
- Parse the printed context JSON. Fields you will use: `partition` (the ticket
  directory — all state lives here), `ticket` (full ticket doc: type, description,
  acceptance criteria, parent, children), `ticket_id`, `settings` (notably
  `architecture_path`, `prd_path`, optional `adr_path`), `models` (resolved
  planner/executor/verifier model+effort), `reconcile`, `handoff_summary`,
  `design`, `pipeline`, `post_hook`, `checkout_root` (consumer repo root).
- If `settings.models.coordinator` is set and this is a DIRECT invocation (you were
  not spawned by /acs:ship): tell the user in one line that `models.coordinator`
  only applies to coordinators spawned under /acs:ship — a directly invoked skill
  runs on the session's model. Never silently diverge.

Throughout this file `<partition>` means the `partition` path from the context JSON
and `<id>` means `ticket_id` (e.g. `SHOP-123`).

## Resume & reconcile

- If `context.reconcile` is true (prior run `in_progress`/`failed`/`interrupted`/
  `handed_off`): verify recorded progress against reality BEFORE continuing —
  list `<partition>/phases/create-design/iter-*-*.xml`, re-read
  `<partition>/design.md` if it exists, and check whether its content actually
  matches the last persisted phase output. Continue from the first unfinished
  phase/iteration; never redo work that demonstrably holds, never trust work
  you cannot see in an artifact.
- If `context.handoff_summary` exists: read it plus
  `<partition>/phases/create-design/handoff-context.md` (when present), do a light
  reconcile (spot-check the named artifacts), and continue from where it points.
- Fresh run (`reconcile` false): start at iteration 1, plan phase.

## Inputs — gather before planning

Read (you and your planner; reference by path in XML, do not inline file bodies):

1. `<partition>/ticket.json` — title, description, acceptance criteria, type,
   priority, children.
2. **The product architecture doc set — PRIMARY input when it exists**:
   `<checkout_root>/<settings.architecture_path>/` (default `docs/architecture/`):
   `hld/overview.md`, `hld/c4-context.md`, `hld/c4-container.md`,
   `hld/c4-component.md`, `hld/data-model.md`, `hld/deployment.md`,
   `hld/tech-stack.md`, `lld/flows/*.md`, `lld/contracts.md`. The design either
   CONFORMS to this doc set or explicitly lists the architecture changes it
   requires (which /acs:code later applies to the doc set). If the doc set is
   absent, note that in design.md and design against the codebase directly.
3. The PRD at `<checkout_root>/<settings.prd_path>/prd.md` when present —
   product-level NFRs and constraints bound the design.
4. The consumer repo's code and docs relevant to the ticket (planner identifies
   the exact files).

## Reflection loop

Run plan → execute → verify, max 3 iterations. Decomposition is YOURS alone —
subagents never spawn subagents.

For every phase:

1. Compose a `<task>` per `schemas/acs-messages.xsd`:

   ```xml
   <task skill="create-design" phase="plan" ticket-id="SHOP-123" iteration="1">
     <objective>Survey the ticket, architecture doc set, and codebase; identify the open design decisions, candidate options (>=2 per decision), and the genuinely-open points needing user input.</objective>
     <inputs>
       <file>/abs/workspace/repo/SHOP-123/ticket.json</file>
       <file>/abs/repo/docs/architecture/hld/c4-container.md</file>
       <file>/abs/repo/docs/architecture/lld/contracts.md</file>
     </inputs>
     <constraints>
       <constraint name="architecture">Conform to docs/architecture or list every doc-set change the design requires</constraint>
       <constraint name="nfr">Cover security and performance explicitly</constraint>
     </constraints>
   </task>
   ```

2. Validate EVERY message you send and receive:

   ```bash
   echo "<xml>" | python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/validate_xml.py" -
   ```

   (or `validate_xml.py <file>` after persisting). On an invalid message from a
   subagent: re-request once with the validation error quoted; still invalid →
   fail the run, recording the error in `errors`.

3. Spawn the subagent with the Agent tool, `subagent_type` as below (fall back to
   the un-namespaced name only if the runtime rejects the namespaced one). Apply
   `context.models.<role>.model` / `.effort` at spawn when not `"inherit"`; if the
   runtime rejects the model or effort, FAIL the run with that exact error — no
   silent fallback.

4. Persist the phase's `<task>` and `<result>` to
   `<partition>/phases/create-design/iter-<n>-<phase>.xml` at the phase boundary,
   BEFORE starting the next phase.

### Phase: plan — `acs:create-design-planner`

Objective: from ticket + architecture docs + codebase, produce a design plan in
its `<result>`: the decisions to make, >=2 candidate options per major decision
with preliminary trade-offs, affected components/flows/data, NFR checklist
(security, performance at minimum), and any `<questions>` that are genuinely open
(user-preference or business trade-offs, not researchable facts). The planner
reads; it never writes files.

If the planner returns `<questions>`, resolve them in "User interaction" below
BEFORE executing, and pass the answers into the execute `<task>` via `<context>`.

### Phase: execute — `acs:create-design-executor`

Objective: write `<partition>/design.md` (the executor mutates ONLY the workspace
partition — never the consumer repo). Required sections, exactly these headings:

```markdown
# Design — <id>: <ticket title>

## Context & constraints
   Problem, scope, assumptions; binding constraints from PRD/architecture/codebase;
   NFRs — security and performance REQUIRED, plus others that apply
   (availability, cost, operability, compliance).
## Options considered
   >= 2 real options (### Option A/B/...), each with how it works and explicit
   trade-offs (pros/cons vs. the NFRs and constraints). No strawmen.
## Decision & rationale
   The chosen option, why it wins, why the others lose. One-line decision
   statement first — it becomes states.decision.
## Architecture
   Components (new/changed, mapped to the C4 container/component views),
   interfaces/contracts (signatures, payloads, error shapes), data model changes
   (Mermaid ER when entities change), and Mermaid sequence diagrams for every
   new or changed runtime flow.
   ### Architecture conformance
   Either "Conforms to <architecture_path> — no doc-set changes required" or
   "Required architecture changes": exact list of doc-set files /acs:code must
   update (e.g. hld/c4-container.md, hld/data-model.md, lld/flows/<flow>.md,
   lld/contracts.md) and what changes in each.
## Impact & risks
   Blast radius, affected tickets/components, risks with mitigations.
## Rollout/migration
   Ordering, data/schema migration, feature flags, backward compatibility,
   rollback plan (or "single-step deploy, no migration" with justification).
```

If `settings.adr_path` is set, the executor adds a subsection
`### Decision records` under "Decision & rationale" listing each accepted
decision as a one-line ADR title and noting: "/acs:code commits these as ADRs
under `<adr_path>` as part of its documentation updates." If unset, omit it.

All diagrams are Mermaid. The design references architecture docs by path; it
never copies them wholesale. For an epic: design at epic level — children
INHERIT this design via cross-partition read in their /acs:create-spec; never
duplicate or split it into child partitions.

You MAY run multiple executors in parallel ONLY when their outputs cannot
conflict (e.g. one drafting `design.md`, one writing a research note to
`<partition>/phases/create-design/research-<topic>.md`). Two executors never
touch `design.md` in the same iteration. The verifier runs after ALL executors
finish and judges the combined result.

### Phase: verify — `acs:create-design-verifier`

Spawn fresh — it sees artifacts (design.md, ticket, architecture docs, code),
never the executor's reasoning. It checks, each a finding `dimension`:

- `alternatives` — >=2 options genuinely weighed with real trade-offs, not strawmen;
- `consistency` — design agrees with the actual codebase and the architecture
  doc set; the conformance subsection is accurate and complete;
- `feasibility` — implementable with the documented tech stack and constraints;
- `nfr` — security and performance (and other applicable NFRs) concretely
  addressed, not hand-waved;
- `completeness` — all required sections present and substantive; Mermaid
  diagrams present for new/changed flows and syntactically plausible.

ALL findings block — zero findings = pass. On findings: persist the verify XML,
feed every finding into the next iteration's plan `<task>` (as `<constraints>`/
`<context>`), and re-run plan → execute → verify. After iteration 3 with findings
remaining: stop; final status `failed`, findings recorded in result.json.

## User interaction

**Clarification ledger first.** Before asking the user anything, run
`python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/clarify.py" list --ticket <ticket-id>`
and reuse any recorded answer — re-asking an answered question is a defect.
Record every Q&A — obtained interactively or relayed in a /ship brief — with
`clarify.py add --skill create-design --question "..." --answer "..." --ticket <ticket-id>`
BEFORE acting on it, and pass the relevant `C-n` entries to subagents in
`<context>`. If the user is unavailable or says "you decide": record the
decision with `--source assumption --rationale "..."` — assumptions surface
in the completion report's Findings and the PR body until a user confirms.
Before a needs_input handoff, record the outgoing questions as `open`
(`clarify.py add` without `--answer`).

- Genuinely open decision points (option choice with no objective winner, scope
  or NFR trade-offs, conflicting docs) → ask the user (AskUserQuestion or plain
  questions) BEFORE settling the decision. Present the options with their
  trade-offs; record the answer and carry it into design.md's rationale.
- Do NOT ask about researchable facts — read the code/docs instead.
- If you are a spawned step under /acs:ship (you cannot reach the user): do not
  guess. Write result.json with `"status": "handed_off"` plus a
  `handoff_summary`, run the Finish steps, and return as your FINAL message only:

  ```xml
  <handoff skill="create-design" ticket-id="SHOP-123" status="needs_input">
    <summary>Design blocked on user decision: sync vs. async export pipeline. Options and trade-offs drafted in design.md (Options considered).</summary>
    <artifacts><file>/abs/workspace/repo/SHOP-123/design.md</file></artifacts>
    <questions><question>Should export run synchronously in-request (simpler, blocks UX >2s) or via a queued worker (new component, resilient)?</question></questions>
    <next-step>Answer, then re-run /acs:create-design SHOP-123</next-step>
  </handoff>
  ```

## Context pressure

If your context is running low mid-run: flush in-flight work and soft context
(user answers, decisions, partial findings, gotchas) to
`<partition>/phases/create-design/handoff-context.md`, then run:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/handoff.py" --ticket <id> --summary "<done / in-flight / next / decisions>"
```

Tell the user the `continue_with` command it prints, and stop. Do not burn the
last of your context on work that would be lost.

## Finish

MANDATORY final step — never skipped, including on failure or handoff:

1. Write `<partition>/phases/create-design/result.json` per the result-document
   contract in INTERNALS.md. Canonical `states` keys (EXACT names) on success:

   ```json
   {
     "status": "completed",
     "stop_reason": "verifier passed with zero findings on iteration 2",
     "states": {
       "design_path": "design.md",
       "decision": "Queue-backed export worker behind the existing API gateway (Option B)"
     },
     "findings": [],
     "errors": [],
     "tokens": {"input": 145000, "output": 32000},
     "cost_usd": 1.10
   }
   ```

   `design_path` is partition-relative (always `"design.md"`); `decision` is the
   one-line decision statement from "Decision & rationale". On `failed`: keep
   whatever is true (e.g. `design_path` if a draft exists), put the verifier's
   blocking findings in `findings`, and the reason in `stop_reason`. Estimate
   `tokens`/`cost_usd` for this run from your subagent usage.

2. Run:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/post-create-design.py" --ticket <id> --result-file <partition>/phases/create-design/result.json
   ```

   If it exits non-zero, surface its stderr verbatim — the /acs:create-spec gate
   stays closed until it succeeds.

3. Report:
   - Direct invocation: a compact summary — decision (one line), options
     considered, conformance vs. required architecture changes, iterations used,
     and the next step (`/acs:create-spec <id>`; for an epic, /acs:create-spec on
     each child, which inherits this design).
   - Under /acs:ship: return ONLY the `<handoff>` XML as your final message —
     `status` matching result.json, `<summary>` <=1KB, `<artifacts>` referencing
     `<partition>/design.md`, `<next-step>/acs:create-spec <id></next-step>`.
     Validate it with validate_xml.py like every other message.

## Completion report (normative)

Every terminal outcome of a direct invocation — completed, failed,
interrupted, or handed off — ends your final message with the standard block
(INTERNALS.md "Completion report"), rendered only AFTER the post-hook
succeeded. Same labels, same order, `none` where empty; under /acs:ship your final message is the `<handoff>` XML instead — this report is for direct invocations:

```markdown
## /acs:create-design · <ticket-id> · <status>

- **Ticket**: <id> — <title> (<type>)
- **Status**: <status> — <stop_reason>
- **Results**: `design.md` (partition-relative path); the decision in one line; architecture changes required (or "conforms")
- **Findings**: <open findings / clarifications, or "none">
- **Artifacts**: <partition files, repo paths, branch, PR URL>
- **Metrics**: iterations <n>/3 · <wall time> · ~<tokens in/out> · ~$<cost_usd>
- **Next**: `/acs:create-spec <ticket-id>`
```
