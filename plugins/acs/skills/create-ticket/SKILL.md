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
sync, and — for epics — child story/task tickets. You perform the create-ticket work
directly (deterministic inline flow), optionally delegating to **at most one executor**
subagent (`acs:create-ticket-executor`). You NEVER spawn a planner or a verifier
subagent in any lane. Decomposition is YOURS alone (subagents never spawn subagents).

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
- The coordinator (or executor) analyzes the split inline: the ticket becomes
  an **epic keeping its id**, description, priority, and PRD trace;
  `needs_design` becomes `true` (epics always — an existing approved design in
  the partition counts as that design); children are cut at the analysis' seams,
  each sized to ONE reviewable PR and independently shippable.
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

## Inline apply flow

This inline flow applies regardless of lane (TRIVIAL, SMALL, STANDARD, COMPLEX, and
absent/unknown). No lane re-introduces a planner or a verifier for /acs:create-ticket.
create-ticket carries no in-skill verifier subagent because this is **deterministic
minting** — schema completeness is enforced by the schema, and the user-confirmation
gate (step 2 below) is the quality checkpoint. The in-loop verifier gate (MAR-55
invariant (d)) belongs to the upstream code/spec lanes; there is no upstream
code-verifier for create-ticket — the correctness mechanism here is the schema plus the
user-confirmation gate.

If you delegate to an executor, spawn **at most one** `acs:create-ticket-executor`
subagent. Apply `context.models.coordinator.model` / `.effort` for coordinator work
and `context.models.executor.model` / `.effort` for the executor when not `"inherit"`;
if the runtime rejects the model or effort, FAIL the run with that exact error — no
silent fallback. Validate all XML messages:

```bash
echo "<xml...>" | python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/validate_xml.py" -
```

On invalid: re-request the message once with the validation error; still
invalid → fail the run and record the error in the result document's `errors`.

Persist each phase output to `<partition>/phases/create-ticket/iter-<n>-<phase>.xml`
at the phase boundary, BEFORE starting the next phase.

### Step 1 — Analyze and recommend fields

The coordinator (or its single optional executor) reads the raw request (or imported
remote issue), the codebase, the PRD, and the roadmap. Produce a complete proposal:

- `type` (epic / story / task), `title`, `description` outline, `acceptance_criteria`
  (array of testable strings), `priority`, `story_points`
- `needs_design` recommendation + one-line rationale (epics are always
  `needs_design: true`; for story/task recommend and rationale)
- `prd_trace`: the PRD feature/goal this ticket traces to (epics to a roadmap
  milestone), or a divergence flag when the request goes beyond the PRD
- `size` (trivial/small/standard/large) + one-line rationale
- `stakes` (low/normal/high) + one-line rationale; run path-glob match against
  `high_stakes_paths` (settings; default seed: `auth/**`, `payments/**`,
  `migrations/**`, `public-api/**`, `security/**`) — any match RECOMMENDS
  stakes=high; include matched paths in the rationale when high
- `lane` derived via `derive_lane(size, stakes, needs_design, type)` — for display
- For epics: proposed child story/task breakdown with title, type, points, and
  `needs_design` per child

No separate planner subagent is spawned. The coordinator performs this analysis
inline.

### Step 2 — User-confirmation gate (human-in-the-loop checkpoint)

**This step is a deliberate design requirement (MAR-55 invariant (c)) — it is NOT a
verifier and it is NOT skipped in any lane.** The coordinator presents the proposal
and blocks until the user confirms or overrides:

1. Resolve every genuine ambiguity with the user before finalizing.
2. **PRD divergence**: if the proposal goes beyond the PRD, present the divergence,
   propose a follow-up `/acs:create-prd` re-run, and obtain explicit user
   confirmation to proceed (or stop at the user's choice). Record the confirmed
   divergence one-liner.
3. **Type and needs_design**: epics are always `needs_design: true` (state it, do
   not ask). For story/task, present the recommendation and obtain USER CONFIRMATION
   of the final `needs_design` value. Same for `docs_only` when recommended `true`
   (it relaxes /acs:code's TDD/coverage gates — never set it without explicit user
   confirmation; when `false`, don't ask).
4. **Size and stakes**: present recommended values with a one-line rationale
   (include matched paths when stakes=high). Obtain USER CONFIRMATION or override
   for each. Derive `lane` from the confirmed values via
   `derive_lane(size, stakes, needs_design, type)` and display it so the user sees
   the pipeline lane. Stakes MAY be raised freely; de-escalation requires explicit
   user confirmation — never silently lower a user-confirmed value (invariant (c)).
5. **Due date**: ask the user for an optional due date ("YYYY-MM-DD, or leave
   blank").
6. **Epic only**: present the proposed child breakdown and obtain user confirmation
   or edits before any child is minted.

If you genuinely cannot reach the user (e.g. a non-interactive run), return
`<handoff skill="create-ticket" ticket-id="<id>" status="needs_input">` with the
open `<questions>` instead of guessing — see Finish.

### Step 3 — Rewrite ticket.json

Rewrite `<partition>/ticket.json` PRESERVING `id`, `status`, and `created_at`, and
setting all fields required by `schemas/ticket.schema.json`:

- `title`, `type`, `description`, `acceptance_criteria` (array of testable strings),
  `priority` (`critical|high|medium|low`), `parent` (null — this skill creates
  roots), `children` (filled by step 4, else `[]`), `status`, `external` (the
  import mapping, the sync result from step 5, or null), `assignee` (or null),
  `story_points` (or null), `needs_design`, `docs_only` (confirmed value, default
  false), `due_date` (ISO-8601 date string or null); refresh `updated_at`
  (ISO-8601 UTC).
- `size` (trivial|small|standard|large, default standard), `stakes`
  (low|normal|high, default normal), and `lane` — the `lane` field MUST be
  computed by `derive_lane(size, stakes, needs_design, ticket_type)` from the
  confirmed axes — NEVER copy lane verbatim from user input; always recompute to
  ensure cache consistency (invariant D5).

Render the title from `settings.formats.tickets.<type>.title` with placeholders
`{ticket_id}`, `{type}`, `{title}`, `{external_key}` (empty string when unsynced).
Build the description from the type's `description_template` (defaults:
`epic-default`, `story-default`, `task-default`). Resolution: a built-in name maps
to `${CLAUDE_PLUGIN_ROOT}/templates/<name>.md`; otherwise
`<repo>/.acs/templates/<name>.md`; otherwise an absolute path. Fill every section,
drop the HTML comments.

Every description template carries an `acs-ticket: {ticket_id}` line in its
`## Notes` section (epic-default's own `## Notes`, mirroring task/story) — the
rendered text is byte-identical across all three built-in templates, so the
acs ticket id is visibly recorded in the ticket's own body regardless of type
(AC-1). This line renders unconditionally as part of every description fill —
it is NOT itself conditional on tracker sync; what IS conditional is whether
that description ever reaches GitHub (Step 5 below, where the `local` provider
skips sync entirely — no regression for unsynced tickets, AC-4).

### Step 4 — Epic fan-out via new-ticket.py

For epics: for each user-confirmed child, run:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/new-ticket.py" --title "Wishlist API" --type story --parent SHOP-123 --description "..." --priority medium --needs-design false --story-points 3
```

Do NOT pass `--size` or `--stakes` when minting child tickets in the fan-out.
This ensures children mint with conservative defaults (size=standard, stakes=normal,
lane=STANDARD) and will each be confirmed individually when their own
`/acs:create-ticket` runs. Conservative defaults never silently assign a fast lane to
unconfirmed work.

This mints the child id, writes BOTH link directions (child `parent`, epic
`children`), and records a completed create-ticket run for the child — children do
NOT rerun /acs:create-ticket; their pipeline starts at /acs:create-spec, which reads
the parent epic's `design.md`. Capture each printed `ticket_id`.

### Step 5 — Tracker sync

Only when `settings.tracker.provider` is `github` or `jira` (skip entirely for
`local`). Sync is on-demand — this creation run pushes the new ticket(s) out; no
background sync. For `local` (unsynced) tickets, none of this step's github
field-fill behavior fires — no issue is created, so the `acs-ticket:` body line
in the local `ticket.json` description is harmless, already-existing template
content, not new GitHub-facing behavior; this is expected and not a regression
(AC-4).

- Imported tickets: keep `external` as pulled, do NOT create a remote duplicate.
  If local analysis changed title/description AND the remote also changed since the
  pull, report the conflict in the result — ask the user which side wins, then
  re-dispatch.
- **Tickets to sync** = `[root ticket, unless it is an import] + [every child
  minted in Step 4]`, EXCLUDING any product-flow delivery title
  (`PRODUCT_TICKET_TITLES`: "Product definition (PRD)", "Product architecture
  doc set") — never sync a product-flow ticket (AC-4). **For each ticket to
  sync**, run the `gh issue create` sequence below once per ticket — a failed
  `gh`/`acli` call for any one ticket is never silently swallowed: it produces
  a finding naming that ticket's id + error, surfaced in `findings` and the
  `<handoff>`, and does not abort the batch (the loop continues to other
  tickets; that ticket's `external` stays null). The Finish report lists which
  tickets synced (with their key) and which failed (with the error) so the
  failed ones can be retried individually.
- `github` (`tracker.github.owner`, `tracker.github.project_number`):
  `gh issue create --title "<rendered title>" --body-file <body.md>` → issue
  number + URL; `gh project item-add <project_number> --owner <owner> --url
  <issue-url> --format json` → item id; then set the `Type` single-select field
  to `Epic`/`Story`/`Task` and `Status` to the board's in-progress column via
  `gh project field-list <project_number> --owner <owner> --format json` +
  `gh project item-edit --project-id <pid> --id <item-id> --field-id <fid>
  --single-select-option-id <oid>`. Store `external = {"provider": "github",
  "key": "<issue number>"}`.

  After `gh issue create` and `gh project item-add` succeed, complete this
  ordered field-fill checklist (AC-6 — fill every field the target repo's
  Project schema actually supports for the synced issue, not just add it to
  the project):

  a. **Labels.** Ensure and apply the `ACS` label (mirrors the label
     `/acs:create-pr` already applies) and the type label (`epic` / `story` /
     `task` matching `ticket.type`), creating either label first if
     `gh label list` does not show it
     (`gh label create <name> --description "..." 2>/dev/null || true`, the
     same idempotent pattern `/acs:create-pr` already uses), then
     `gh issue edit <number> --add-label ACS,<type-label>`.
  b. **Assignee.** When `ticket.assignee` is a non-null value, run
     `gh issue edit <number> --add-assignee <assignee>`; when null, skip —
     this is not a gap to surface (a null assignee is expected data, not
     missing data).
  c. **Milestone.** When the repo defines at least one milestone
     (`gh api repos/<owner>/<repo>/milestones --jq length` > 0, or the
     ticket/settings names one explicitly), set it via
     `gh issue edit <number> --milestone <name>`; when the repo defines none,
     skip silently — this is the "when the repo uses one" condition AC-6
     itself names, not an omission to surface.
  d. **Project fields.** Reuse the `gh project field-list` call above (it
     already sets `Type` and `Status`) and extend its result-handling: for
     every field the JSON lists that this ticket has a natural value for, call
     `gh project item-edit` to set it. For every field the JSON does NOT list
     that AC-6 expects (e.g. no `Type` field on this repo's Project), add an
     `info`-severity finding to the run's findings list stating exactly which
     field was skipped and why ("Project schema has no `<Field>` field;
     skipped — add it via `gh project field-create` if wanted") — a
     schema-undefined field is explicitly surfaced, never silently ignored.
- `jira` (`tracker.jira.base_url`, `tracker.jira.project_key`): for each
  `ticket_to_sync` in the set defined above, run the sequence below, once per
  ticket. `acli jira workitem create --project <project_key> --type "Epic"
  --summary "<rendered title>" --description "<description>"` (types map
  epic→Epic, story→Story, task→Task; children pass the epic's remote key as
  parent link). Store `external = {"provider": "jira", "key": "<KEY-n>"}`. A
  failed `acli` call for any one ticket follows the same per-ticket
  failure-handling rule stated above (surfaced, never silent, does not abort
  the batch, that ticket's `external` stays null).
- Write `external` into each synced ticket's own `ticket.json` — root and
  every child — via `python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/record-external.py"
  --ticket <ticket-id> --provider <provider> --key <key>` once per successfully
  synced ticket.

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
     "stop_reason": "ticket created; 2 children minted",
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
   (e.g. minted children) and record blocking findings under `findings` with
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
