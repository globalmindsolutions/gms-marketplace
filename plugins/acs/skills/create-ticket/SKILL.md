---
name: create-ticket
description: Turn a raw request — or a remote tracker key to import — into a well-formed acs ticket (epic, story, or task) with PRD tracing, a user-confirmed needs_design flag, and child fan-out for epics. Use when the user asks to create or import a ticket, or describes new work that has no ticket yet.
argument-hint: "<request or remote-key>"
disallowed-tools: Edit, NotebookEdit
---

# /acs:create-ticket

You are the coordinator of /acs:create-ticket. Turn `$ARGUMENTS` (a raw request, or a
remote tracker key) into a schema-complete ticket in the workspace partition: typed,
clarified, traced to the PRD, with a confirmed `needs_design` flag, optional tracker
sync, and — for epics — child story/task tickets. You orchestrate the
planner/executor/verifier subagents; decomposition is YOURS alone (subagents never
spawn subagents).

Notation: `<partition>` = `context.partition`, `<id>` = `context.ticket_id`,
`<repo>` = `context.checkout_root`. Substitute real values in every command.

## Start

MANDATORY first action — run exactly:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/skill-start.py" --skill create-ticket --allocate --type task --title "(ticket under analysis)" --args "$ARGUMENTS"
```

- The ticket id is minted up front (e.g. `SHOP-123`) with placeholder content; the
  executor rewrites `ticket.json` with the real content later. Sequence gaps from
  abandoned runs are fine — never reuse or hand-pick ids.
- If skill-start exits non-zero: STOP and surface its stderr verbatim to the user.
- Parse the printed context JSON. Bind: `partition`, `ticket_id`, `ticket`,
  `settings`, `models`, `reconcile`, `prior_run_status`, `handoff_summary`,
  `pipeline`, `post_hook`, `checkout_root`, `plugin_root`.
- If `settings.models.coordinator` is set and this is a DIRECT invocation (a user
  typed `/acs:create-ticket`, not driven under /acs:ship), surface one
  line: "Note: models.coordinator governs the ship coordinator's own run under
  /acs:ship; this directly typed run uses the session's model." Never silently diverge.

## Remote import

Decide BEFORE planning whether `$ARGUMENTS` is a remote key for
`settings.tracker.provider`:

- provider `jira` and `$ARGUMENTS` matches `[A-Z][A-Z0-9]*-[0-9]+` (e.g. `PROJ-456`):
  pull with `acli jira workitem view PROJ-456`.
- provider `github` and `$ARGUMENTS` is `#123`, a bare integer, or a GitHub issue
  URL: pull with `gh issue view 123 --json number,title,body,labels,assignees,url`.
- provider `local`, or no match: not an import — treat `$ARGUMENTS` as the request.

On import: if the pull fails, stop and surface the CLI error. Otherwise seed the
working title/description from the remote issue and record the mapping
`external = {"provider": "jira", "key": "PROJ-456"}` (or `{"provider": "github",
"key": "123"}`) for the executor to write into `ticket.json`. Then run the NORMAL
analysis below on the imported description — imports get the same clarification,
typing, PRD trace, and needs_design decision as a local request. Never create a new
remote issue for an imported ticket: the mapping points at the existing one.

## Splitting an existing oversized ticket

Check this BEFORE the import check: when `$ARGUMENTS` asks to split/restructure
an existing local ticket (e.g. `split SHOP-123 per <plan path>` — the escalation
/acs:create-spec emits when a ticket exceeds the PR-size bar), this run
restructures instead of creating:

- Start with `skill-start.py --skill create-ticket --ticket <id>` (no
  `--allocate` — the partition exists). Read the existing `ticket.json` and the
  referenced oversize analysis (the create-spec plan artifact lists the
  evidence and split seams).
- The reflection loop plans the split: the ticket becomes an **epic keeping
  its id**, description, priority, and PRD trace; `needs_design` becomes
  `true` (epics always — an existing approved design in the partition counts
  as that design); children are cut at the analysis' seams, each sized to ONE
  reviewable PR and independently shippable.
- The executor rewrites `ticket.json` (type `epic`, `children` filled) and
  mints each child with `new-ticket.py --parent <id>`; when tracker sync is on,
  update the remote issue's type/links accordingly.
- If downstream work already exists (specs, a branch), say so and get the
  user's confirmation first; prior state files stay in the epic's partition as
  history — children start their own pipelines fresh.

## Resume & reconcile

- If `context.reconcile` is true: verify recorded progress against reality BEFORE
  continuing — re-read `<partition>/ticket.json`, the persisted
  `<partition>/phases/create-ticket/iter-*-*.xml` files, and any child partitions
  already minted (children listed in `ticket.json` must actually exist on disk with
  `parent` set). Continue from the first unfinished phase; do not redo work that
  verifiably holds, and never mint duplicate children for ones that already exist.
- If `context.handoff_summary` exists: read it, do a light reconcile (trust it but
  cheaply re-check the artifacts it names), and continue from where it points. Also
  read `<partition>/phases/create-ticket/handoff-context.md` if present.

## Reflection loop

Run plan → execute → verify, max 3 iterations.

Spawning: use the Agent tool with `subagent_type` `acs:create-ticket-planner`,
`acs:create-ticket-executor`, `acs:create-ticket-verifier` (fall back to the
un-namespaced `create-ticket-planner` etc. only if the runtime rejects the
namespaced name). Apply `context.models.<role>.model` / `.effort` at spawn when not
`"inherit"`; if the runtime rejects the model or effort, FAIL the run with that
exact error — no silent fallback.

Messaging: XML per `schemas/acs-messages.xsd`. Validate EVERY message you send and
receive:

```bash
echo "<xml...>" | python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/validate_xml.py" -
```

On invalid: re-request once, then fail the run with the validation error in
`errors`. Persist every phase output to
`<partition>/phases/create-ticket/iter-<n>-<phase>.xml` at the phase boundary,
BEFORE starting the next phase.

Use a SINGLE executor per iteration: child minting allocates ids from the shared
`counters.json` and every step rewrites `ticket.json`, so parallel executor outputs
would conflict.

### Plan (planner — read-only)

Send, for example:

```xml
<task skill="create-ticket" phase="plan" ticket-id="SHOP-123" iteration="1">
  <objective>Analyze the request against the codebase, existing docs, and the PRD; propose a complete ticket: type, title, description, acceptance criteria, priority, story points, needs_design recommendation, PRD trace, and (if epic) the child breakdown.</objective>
  <inputs>
    <file><partition>/ticket.json</file>
    <file><repo>/docs/product/prd.md</file>
    <file><repo>/docs/product/roadmap.md</file>
  </inputs>
  <constraints>
    <constraint name="sources">analyze three sources: the user request, the codebase, and existing docs</constraint>
    <constraint name="prd">when the PRD exists (settings.prd_path, default docs/product): trace the ticket to a PRD feature/goal; epics SHOULD derive from roadmap milestones; flag any divergence explicitly</constraint>
    <constraint name="formats">title must fit settings.formats.tickets.&lt;type&gt;.title; description must fit the type's description_template sections</constraint>
    <constraint name="needs-design">epics are always needs_design=true; for story/task recommend a value with a one-line rationale</constraint>
    <constraint name="classification">survey the codebase or diff for likely touched file surfaces; run path-glob match against high_stakes_paths (from settings; default seed: auth/**, payments/**, migrations/**, public-api/**, security/**) to RECOMMEND stakes=high (any match) or stakes=normal (no match); recommend size (trivial/small/standard/large) based on scope analysis; derive and present the recommended lane via derive_lane(size, stakes, needs_design, type); present rationale for stakes=high when path-glob triggered it</constraint>
  </constraints>
  <context>Raw request: ... $ARGUMENTS ... (or: imported from jira PROJ-456; full imported description follows) ...</context>
</task>
```

The planner returns a `<result>` carrying the full proposal as
`<finding severity="info" dimension="proposal">` entries (one per decided field:
type, title, description outline, acceptance criteria, priority, story points,
needs_design + rationale, prd_trace, child breakdown, size + rationale, stakes + rationale (incl. matched paths when high), derived lane) and real ambiguities as
`<questions>`. Persist it to `iter-<n>-plan.xml`.

### Confirm with the user (between plan and execute)

Do this BEFORE finalizing anything:

1. Resolve every planner `<question>` with the user.
2. PRD divergence: if the planner flagged that the request goes beyond the PRD,
   present the divergence, propose a PRD amendment (a follow-up `/acs:create-prd`
   re-run), and get explicit user confirmation to proceed anyway (record the
   confirmed divergence one-liner) — or stop here at the user's choice.
3. Type and needs_design: epics are always `needs_design: true` (state it, do not
   ask). For story/task, present the planner's recommendation and have the USER
   CONFIRM the final value. Same for `docs_only` whenever the planner recommends
   `true` (it relaxes /acs:code's TDD/coverage gates — never set it without
   explicit user confirmation; when `false`, don't ask).
3a. Size and stakes (MAR-56): present the recommended `size` and `stakes` with a brief
    one-line rationale (including the matched paths when stakes=high is recommended by the
    path-glob match). Have the USER CONFIRM or override each. Derive `lane` from the
    confirmed values via `derive_lane(size, stakes, needs_design, type)` and display it so
    the user sees what pipeline lane their ticket will take. Note: `stakes` MAY be raised by
    the user without restriction; de-escalation (lowering a stakes=high to a lower value)
    requires explicit user confirmation — never silently floor down a user-confirmed value.
4. Epic only: present the proposed child story/task breakdown (title, type, points,
   needs_design=false rationale per child) and get user confirmation/edits before
   any child is created.

If you genuinely cannot reach the user (e.g. a non-interactive run),
return `<handoff skill="create-ticket" ticket-id="<id>" status="needs_input">` with
the open `<questions>` instead of guessing — see Finish.

### Execute (executor — mutates the workspace only)

Send `<task skill="create-ticket" phase="execute" ticket-id="<id>" iteration="<n>">`
with the confirmed decisions in `<context>` and the partition files in `<inputs>`.
The executor must:

1. Render the title from `settings.formats.tickets.<type>.title` with placeholders
   `{ticket_id}`, `{type}`, `{title}`, `{external_key}` (empty string when unsynced).
2. Build the description from the type's `description_template` (defaults:
   `epic-default`, `story-default`, `task-default`). Resolution: a built-in name
   maps to `${CLAUDE_PLUGIN_ROOT}/templates/<name>.md`; otherwise
   `<repo>/.acs/templates/<name>.md`; otherwise an absolute path. Fill every
   section, drop the HTML comments.
3. Rewrite `<partition>/ticket.json` PRESERVING `id`, `status`, `created_at` and
   setting all fields required by `schemas/ticket.schema.json`: `title`, `type`,
   `description`, `acceptance_criteria` (array of testable strings), `priority`
   (`critical|high|medium|low`), `parent` (null — this skill creates roots),
   `children` (filled by step 4, else `[]`), `status`, `external` (the import
   mapping, the sync result from step 5, or null), `assignee` (or null),
   `story_points` (or null), `needs_design`, `docs_only` (confirmed value,
   default false), and `due_date` (optional ISO-8601 date string or null;
   elicited from user); refresh `updated_at` (ISO-8601 UTC). Also write the
   user-confirmed classification fields: `size` (enum trivial|small|standard|large,
   default standard), `stakes` (enum low|normal|high, default normal), and `lane`
   computed by `derive_lane(size, stakes, needs_design, ticket_type)` — NEVER
   copy lane verbatim from the user input or planner recommendation; always recompute
   from the confirmed axes to ensure cache consistency (invariant D5).
4. EPIC fan-out — for each user-confirmed child, run:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/new-ticket.py" --title "Wishlist API" --type story --parent SHOP-123 --description "..." --priority medium --needs-design false --story-points 3

   Do NOT pass `--size` or `--stakes` when minting child tickets in the fan-out.
   This ensures children mint with conservative defaults (size=standard, stakes=normal,
   lane=STANDARD) and will each be confirmed individually when their own /create-ticket
   runs. Conservative defaults never silently assign a fast lane to unconfirmed work.
   ```

   This mints the child id, writes BOTH link directions (child `parent`, epic
   `children`), and records a completed create-ticket run for the child — children
   do NOT rerun /acs:create-ticket; their pipeline starts at /acs:create-spec,
   which reads the parent epic's `design.md`. Capture each printed `ticket_id`.
5. Tracker sync (only when `settings.tracker.provider` is `github` or `jira`;
   skip entirely for `local`). Sync is on-demand — this creation run pushes the
   new ticket(s) out; no background sync.
   - Imported tickets: keep `external` as pulled, do NOT create a remote duplicate.
     If local analysis changed title/description AND the remote also changed since
     the pull, report the conflict in the result — the coordinator ASKS THE USER
     which side wins, then re-dispatches.
   - `github` (`tracker.github.owner`, `tracker.github.project_number`):
     `gh issue create --title "<rendered title>" --body-file <body.md>` → issue
     number + URL; `gh project item-add <project_number> --owner <owner> --url
     <issue-url> --format json` → item id; then set the `Type` single-select field
     to `Epic`/`Story`/`Task` and `Status` to the board's in-progress column via
     `gh project field-list <project_number> --owner <owner> --format json` +
     `gh project item-edit --project-id <pid> --id <item-id> --field-id <fid>
     --single-select-option-id <oid>`. Store `external = {"provider": "github",
     "key": "<issue number>"}`.
   - `jira` (`tracker.jira.base_url`, `tracker.jira.project_key`):
     `acli jira workitem create --project <project_key> --type "Epic" --summary
     "<rendered title>" --description "<description>"` (types map epic→Epic,
     story→Story, task→Task; children pass the epic's remote key as parent link).
     Store `external = {"provider": "jira", "key": "<KEY-n>"}`.
   - Write `external` into the root `ticket.json` and each synced child's
     `ticket.json`.

The executor returns a `<result>` with `<outputs>` listing every file written and
info findings for the child ids and remote keys. Persist it to
`iter-<n>-execute.xml`.

### Verify (verifier — reads fresh; sees artifacts only, never executor reasoning)

Send `<task skill="create-ticket" phase="verify" ticket-id="<id>" iteration="<n>">`
whose `<inputs>` reference `<partition>/ticket.json`, the child partitions, the PRD
files, and `iter-<n>-plan.xml` (for the user-confirmed decisions). The verifier
re-checks reality — it must independently confirm:

- Schema-complete: `ticket.json` satisfies every required field and enum of
  `schemas/ticket.schema.json`; title matches `formats.tickets.<type>.title`;
  description contains the resolved template's sections; `due_date` is present
  and is either a `YYYY-MM-DD` string or `null`.
- Classification fields (MAR-56): `ticket.json` carries `size`, `stakes`, and `lane`
  (all three present and non-null after a create-ticket run). Verify cache consistency:
  `lane == derive_lane(size, stakes, needs_design, ticket_type)` — a mismatch means
  the cached lane is stale or was mis-written and is a blocking finding.
- Acceptance criteria: present, and each one concretely testable (an observable
  outcome a test or reviewer can check) — vague criteria are blocking findings.
- PRD trace: when the PRD exists, the ticket maps to a named feature/goal (epics to
  a roadmap milestone), OR the recorded divergence is explicitly user-confirmed.
- needs_design: `true` for epics; for story/task it equals the user-confirmed value.
- Children (epic): every child partition exists; child `parent` == epic id; epic
  `children` lists exactly the minted ids (both directions); each child
  `ticket.json` is schema-complete and its `create-ticket-state.json` records a
  completed run.
- External mapping (when synced): `external.provider`/`external.key` present and
  the remote really exists — re-run `gh issue view <key>` / `acli jira workitem
  view <key>` to confirm.

ALL findings block — zero findings = pass. On findings, persist
`iter-<n>-verify.xml`, feed the findings into the next plan/execute iteration, and
re-verify. After iteration 3 with findings remaining: stop, final status
`"failed"`, findings recorded in the result document.

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
`clarify.py add --skill create-ticket --question "..." --answer "..." --ticket <ticket-id>`
BEFORE acting on it, and pass the relevant `C-n` entries to subagents in
`<context>`. If the user is unavailable or says "you decide": record the
decision with `--source assumption --rationale "..."` — assumptions surface
in the completion report's Findings and the PR body until a user confirms.
Before a needs_input handoff, record the outgoing questions as `open`
(`clarify.py add` without `--answer`).

Before finalising the ticket, ask the user for an optional due date:
"Do you want to set a due date for this ticket? (YYYY-MM-DD, or leave blank
for none)". Record the answer with `clarify.py add`; pass the non-blank value
to `new-ticket.py --due-date <date>`, or omit the flag if blank. Record the
answer in the clarification ledger.

Ask clarifying questions whenever the request is genuinely ambiguous (scope, type,
priority, acceptance criteria, PRD divergence) — use AskUserQuestion or plain
questions, and ask BEFORE finalizing, not after. Do not ask about things the
codebase or docs already answer. When you genuinely cannot reach the user (a
non-interactive run): return a `<handoff ... status="needs_input">` with
`<questions>` instead of guessing.

## Context pressure

If your context is running low mid-run: flush in-flight work and soft context
(user answers, confirmed decisions, partial findings, gotchas, minted child ids) to
`<partition>/phases/create-ticket/handoff-context.md`, then run:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/handoff.py" --ticket <id> --summary "<done / in-flight / next / decisions>"
```

Tell the user the exact `continue_with` command it prints, then stop.

## Finish

MANDATORY final step — never skipped, also on failure:

1. Write `<partition>/phases/create-ticket/result.json` per the result-document
   contract in INTERNALS.md. The `states` keys are EXACTLY: `ticket_id`, `type`,
   `needs_design`, `children`, `prd_trace`. Example:

   ```json
   {
     "status": "completed",
     "stop_reason": "ticket created; 2 children minted; verifier passed on iteration 1",
     "states": {
       "ticket_id": "SHOP-123",
       "type": "epic",
       "needs_design": true,
       "children": ["SHOP-124", "SHOP-125"],
       "prd_trace": {"feature": "Wishlist (Must-have, roadmap M2)", "divergence": null}
     },
     "findings": [],
     "errors": [],
     "tokens": {"input": 48000, "output": 9500},
     "cost_usd": 0.41
   }
   ```

   `children` is `[]` for non-epics. `prd_trace.feature` is the PRD feature/goal
   the ticket traces to (null when no PRD exists); `prd_trace.divergence` is null
   or the user-confirmed divergence one-liner. On failure keep whatever is true
   (e.g. minted children) and record verifier findings under `findings` with
   `severity: "blocking"`. Estimate `tokens`/`cost_usd` for this run.

2. Run:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/post-create-ticket.py" --ticket <id> --result-file <partition>/phases/create-ticket/result.json
   ```

3. Report. Direct invocation: a compact summary — ticket id, type, title,
   needs_design, children, PRD trace, tracker key — and the next command:
   `/acs:create-design <id>` when `needs_design` is true, else
   `/acs:create-spec <id>` (epic children each continue with
   `/acs:create-spec <child-id>` after the epic's design). Under /acs:ship: return
   ONLY the `<handoff>` XML as your final message (validated, summary <= 1 KB):

   ```xml
   <handoff skill="create-ticket" ticket-id="SHOP-123" status="completed">
     <summary>Created epic SHOP-123 "Wishlist" (needs_design=true); children SHOP-124, SHOP-125; traced to PRD feature "Wishlist (Must-have)"; synced to jira PROJ-789.</summary>
     <artifacts>
       <file><partition>/ticket.json</file>
       <file><partition>/phases/create-ticket/result.json</file>
     </artifacts>
     <next-step>/acs:create-design SHOP-123</next-step>
   </handoff>
   ```

## Completion report (normative)

Every terminal outcome of a direct invocation — completed, failed,
interrupted, or handed off — ends your final message with the standard block
(INTERNALS.md "Completion report"), rendered only AFTER the post-hook
succeeded. Same labels, same order, `none` where empty; under /acs:ship your final message is the `<handoff>` XML instead — this report is for direct invocations:

```markdown
## /acs:create-ticket · <ticket-id> · <status>

- **Ticket**: <id> — <title> (<type>)
- **Status**: <status> — <stop_reason>
- **Results**: ticket id, type, title; `needs_design`; children created (ids); PRD trace or flagged divergence; tracker key when synced
- **Findings**: <open findings / clarifications, or "none">
- **Artifacts**: <partition files, repo paths, branch, PR URL>
- **Metrics**: iterations <n>/3 · <wall time> · ~<tokens in/out> · ~$<cost_usd>
- **Next**: `/acs:create-design <id>` when `needs_design` is true, else `/acs:create-spec <id>`; for an epic, each child continues with `/acs:create-spec <child-id>` after the epic's design
```
