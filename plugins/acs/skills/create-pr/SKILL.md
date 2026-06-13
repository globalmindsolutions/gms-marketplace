---
name: create-pr
description: Push the ticket's implementation branch and open (or update) the pull request — title and body composed entirely from workspace state, targeting the repo's default branch with the ACS label, ready for review. Use after /acs:code completes with a passing verifier, when the implementation is ready to ship for human review.
argument-hint: "[ticket-id]"
disallowed-tools: Edit, NotebookEdit
---

You are the coordinator of /acs:create-pr. Your job: ship the ticket's
implementation as a pull request. Everything in the PR — title, body, ticket
reference, change list, test plan — is composed from WORKSPACE STATE
(`ticket.json`, `specs/`, `design.md`, `code-state.json` including its review
summary), never from conversation history. You orchestrate
planner/executor/verifier subagents, persist every phase artifact to the
ticket partition, and finish by writing the result document and running the
post-hook — always, even on failure.

## Start

MANDATORY first action — run exactly:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/skill-start.py" --skill create-pr --args "$ARGUMENTS"
```

If it exits non-zero: STOP and surface its stderr verbatim to the user. Do not
improvise a workaround. (The pre-hook already gated on
`code-state.json` `runs[-1].status == "completed"` with
`states.verifier_passed == true` — if you are running, /acs:code passed.)

Parse the printed context JSON. Fields you will use:

- `ticket_id`, `ticket` — id, title, type, and `external` (the
  `{provider, key}` remote-tracker mapping, when synced).
- `partition` — absolute path of `<workspace>/<repo-id>/<ticket-id>/`. Phase
  artifacts go in `<partition>/phases/create-pr/`.
- `settings.formats` — `pr_title` (default `[{ticket_id}] {title}`; vocabulary
  `{ticket_id}` `{type}` `{title}` `{summary}` `{external_key}`) and
  `pr_description_template` (default `pr-default`).
- `settings.tracker` — `provider` is `local` (no sync), `github`, or `jira`.
- `checkout_root`, `plugin_root` — for template resolution.
- `models` — per-role `{model, effort}` for planner/executor/verifier.
- `reconcile`, `handoff_summary`, `prior_run_status` — see Resume & reconcile.
- `design` — `{required, dir, source}`; when required, `<design.dir>/design.md`
  feeds the Summary/Changes content.
- `post_hook` — absolute path to `post-create-pr.py`.

If `settings.models.coordinator` is set and this is a DIRECT invocation (not a
step spawned by /acs:ship), tell the user in one line that `models.coordinator`
only applies under /acs:ship — never silently diverge from it.

State inputs (read these; conversation history is NOT an input):

- `<partition>/ticket.json` — title, type, description, acceptance criteria,
  `external` mapping.
- `<partition>/code-state.json` — `runs[-1].states`: `branch` (the ticket
  branch /acs:code created per `formats.branch_name`), `specs_implemented`,
  `tests` `{passed, failed, coverage_percent, coverage_target}`,
  `docs_updated`, `review` `{iterations, findings_open}`.
- `<partition>/specs/*.md` — scope and API/data changes per spec.
- `<design.dir>/design.md` — the decision, when `design.required`.

## Resume & reconcile

If `context.reconcile` is true, verify recorded state against reality BEFORE
continuing:

1. Read `<partition>/create-pr-state.json` (`runs[-1]`) and any
   `<partition>/phases/create-pr/iter-*-*.xml` to see how far the prior run got.
2. Re-check reality: does the branch exist on origin
   (`git ls-remote origin <branch>`)? Does an open PR for it exist
   (`gh pr list --head <branch> --state open --json number,url,baseRefName`)?
   A PR recorded but missing remotely is not done; a PR that exists but was
   never recorded is done-but-unfinalized — verify it, then finish normally.
3. Continue from the first unfinished phase of the recorded iteration.

If `context.handoff_summary` exists, read it plus
`<partition>/phases/create-pr/handoff-context.md` (if present), do a light
reconcile (trust the summary, cheaply spot-check the PR/branch it names), and
continue from where it points.

## Reflection loop

Run plan -> execute -> verify, at most 3 iterations. Spawn subagents with the
Agent tool: `acs:create-pr-planner`, `acs:create-pr-executor`,
`acs:create-pr-verifier` (fall back to the un-namespaced name only if the
runtime rejects the namespaced one). For each role, apply
`context.models.<role>.model` / `.effort` at spawn when not `"inherit"`; if
the runtime rejects the model or effort, FAIL the run with that exact error —
no silent fallback.

Messaging rules (schemas/acs-messages.xsd):

- Send each subagent one `<task skill="create-pr" phase="plan|execute|verify"
  ticket-id="<id>" iteration="n">` containing `<objective>`, `<inputs>` (file
  refs: ticket.json, code-state.json, specs/, design.md when it applies), and
  `<constraints>`. The subagent returns a `<result>` as its final content.
- Validate EVERY message you send and receive:

  ```bash
  echo "<xml>" | python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/validate_xml.py" -
  ```

  On invalid: re-request once with the validation error; still invalid -> fail
  the run and record the error in the result document's `errors`.
- Persist every phase output to
  `<partition>/phases/create-pr/iter-<n>-<phase>.xml` at the phase boundary,
  BEFORE starting the next phase.
- Decomposition is YOURS alone — subagents never spawn subagents. For this
  skill run exactly ONE executor per iteration: there is one branch and one PR,
  so parallel executor outputs always conflict. The verifier runs after the
  executor finishes.

### Plan (per iteration)

Task the planner with `<inputs>` of the state files above. The planner is
read-only (except its own `iter-<n>-plan.md`) and must produce:

- The ticket branch resolved from `code-state.json` `states.branch`, with its
  reality check plan (exists locally? exists on origin? local tip ==
  remote tip?).
- The base: the repo's DEFAULT branch, detected via
  `gh repo view --json defaultBranchRef --jq .defaultBranchRef.name`.
- The rendered PR title per `settings.formats.pr_title` — `{summary}` is a
  one-line summary of the change derived from specs + code-state, `{external_key}`
  is `ticket.external.key` or empty.
- The resolved body template path. Resolution (INTERNALS rule): a built-in
  name (`pr-default`) -> `${CLAUDE_PLUGIN_ROOT}/templates/pr-default.md`;
  otherwise `<checkout_root>/.acs/templates/<name>.md`; otherwise an absolute
  path. Unresolvable template = blocking problem, surface it.
- The section-by-section body content plan, every claim traced to a state
  file: Summary (from specs scope + design decision), Ticket (id, title, type,
  external key), Changes (from `specs_implemented`, `docs_updated`, and the
  real diff `git diff <base>...<branch> --stat`), Test plan (from
  `tests.passed/failed/coverage_percent/coverage_target` and the specs' test
  plans), Checklist (tick exactly what code-state evidences).
- Existing-PR detection plan: `gh pr list --head <branch> --state open
  --json number,url,baseRefName,isDraft` — create vs update.
- Tracker sync plan when `settings.tracker.provider` is `github`/`jira` and
  `ticket.external` is set.
- On iterations 2-3: how each verifier finding from the previous iteration is
  addressed.

The planner writes `<partition>/phases/create-pr/iter-<n>-plan.md` and
references it in its `<result>` outputs.

### Execute (per iteration)

Send the executor a `<task phase="execute">` carrying the plan file ref. The
executor performs, in order:

1. **Branch.** Verify the ticket branch from the plan exists
   (`git rev-parse --verify <branch>` locally, or already on origin). Push it:
   `git push -u origin <branch>`. If the branch only exists on origin and is
   current, skip the push. Never commit new work — if implementation changes
   are uncommitted, that is /acs:code's job: report it as a problem instead.
2. **Body.** Fill the resolved template into
   `<partition>/phases/create-pr/pr-body.md`: replace every placeholder
   (`{ticket_id}`, `{type}`, `{title}`, `{summary}`, `{external_key}`;
   `{external_key_line}` renders as ` — tracker: <provider> <key>` when
   `ticket.external` is set, empty otherwise), replace the template's HTML
   comments with real content and DELETE the comments, and fill every section
   strictly from the state files per the plan. Checklist items are `[x]` only
   when code-state substantiates them (e.g. review loop passed when
   `review.findings_open == 0`).
3. **Label.** `gh label create ACS --description "Created by the acs pipeline" 2>/dev/null || true`
4. **Create or update.** If no open PR exists for the branch:

   ```bash
   gh pr create --base <default-branch> --head <branch> --title "<rendered pr_title>" --body-file <partition>/phases/create-pr/pr-body.md --label ACS
   ```

   No `--draft` — PRs are created ready-for-review. If an open PR already
   exists for the branch: update it instead and record it —
   `gh pr edit <number> --title "<rendered pr_title>" --body-file <body> --add-label ACS`,
   plus `gh pr edit <number> --base <default-branch>` when its base is wrong
   and `gh pr ready <number>` when it is a draft.
5. **Record.** `gh pr view <branch> --json number,url,baseRefName,headRefName,isDraft,labels`
   -> capture `{number, url, branch, base}`.
6. **Tracker sync** (only when `settings.tracker.provider` is `github` or
   `jira` AND `ticket.external.key` is set; skip for `local`, and report an
   info finding when the provider is configured but the ticket was never
   synced):
   - `github`: `gh issue comment <external.key> --body "ACS: PR #<number> opened for <ticket-id> — <url>"`
   - `jira`: `acli jira workitem comment --key <external.key> --body "ACS: PR opened for <ticket-id> — <url>"`

The executor writes `<partition>/phases/create-pr/iter-<n>-execute.json`
(commands run with outcomes, pushed SHA, PR number/url/base, sync result,
problems hit) and returns a `<result>` referencing it.

### Verify (per iteration)

Spawn the verifier AFTER the executor finishes, with `<inputs>` of
ticket.json, code-state.json, specs/, the rendered pr-body.md, and the PR
reference from the execute report. The verifier judges fresh — never forward
executor reasoning — and re-runs the actual checks:

- **PR exists and is live**: `gh pr view <number> --json
  number,url,state,baseRefName,headRefName,isDraft,labels,title,body` —
  state OPEN, `isDraft` false, head is the ticket branch.
- **Targets the default branch**: `baseRefName` equals
  `gh repo view --json defaultBranchRef --jq .defaultBranchRef.name`.
- **ACS label present** in the PR's labels.
- **Title follows formats**: independently re-render
  `settings.formats.pr_title` from ticket.json and compare to the live title.
- **Body follows the template and is filled from state**: all sections of the
  resolved template present (for `pr-default`: Summary, Ticket, Changes, Test
  plan, Checklist); no unrendered `{placeholder}` and no leftover template
  comments; Ticket section names `<ticket-id>` (and the external key when
  synced); Test plan numbers match `code-state.json` `tests` exactly; Changes
  consistent with `specs_implemented`/`docs_updated` and the real file list
  (`gh pr diff <number> --name-only`).
- **Branch is pushed and current**: `git rev-parse <branch>` equals the SHA in
  `git ls-remote origin refs/heads/<branch>`.
- **Tracker sync done** when configured and the ticket is synced: the PR URL
  appears on the remote issue (`gh issue view <key> --comments` /
  `acli jira workitem view <key>`).

The verifier writes its full report to
`<partition>/phases/create-pr/iter-<n>-verify.md` and returns `<finding>`
entries that summarize it. ALL findings block — zero findings = pass. On
findings: persist the verify output, feed every finding into the next
iteration's plan, and loop. After iteration 3 with findings remaining: stop
with final status `"failed"`, findings recorded in the result document.

## User interaction

**Clarification ledger first.** Before asking the user anything, run
`python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/clarify.py" list --ticket <ticket-id>`
and reuse any recorded answer — re-asking an answered question is a defect.
Record every Q&A — obtained interactively or relayed in a /ship brief — with
`clarify.py add --skill create-pr --question "..." --answer "..." --ticket <ticket-id>`
BEFORE acting on it, and pass the relevant `C-n` entries to subagents in
`<context>`. If the user is unavailable or says "you decide": record the
decision with `--source assumption --rationale "..."` — assumptions surface
in the completion report's Findings and the PR body until a user confirms.
Before a needs_input handoff, record the outgoing questions as `open`
(`clarify.py add` without `--answer`).

Most runs need no questions — the state files answer everything. Ask
(AskUserQuestion or plain questions) only when reality genuinely diverges from
state: the ticket branch has uncommitted or unpushed work not recorded by
/acs:code (include by re-running /acs:code, or proceed without?), the recorded
branch no longer exists, or an open PR for the branch was authored outside ACS
with a conflicting base. Do not guess.

If you are running as a spawned step under /acs:ship (you cannot reach the
user): do not guess. Write the result document with status `"failed"` and
`stop_reason` "needs user input", run the Finish steps, and return as your
final message a handoff like:

```xml
<handoff skill="create-pr" ticket-id="SHOP-123" status="needs_input">
  <summary>Branch task/SHOP-123-bulk-import has uncommitted changes not recorded in code-state.json.</summary>
  <questions>
    <question>Re-run /acs:code SHOP-123 to land the uncommitted changes, or open the PR from the last recorded commit?</question>
  </questions>
  <next-step>Answer, then re-run /acs:ship SHOP-123.</next-step>
</handoff>
```

Validate it with validate_xml.py like every other message.

## Context pressure

If your context window is running low mid-run: do NOT burn the remainder on
work that would be lost. Flush in-flight work plus soft context (rendered
title, body status, push/PR/sync progress, decisions, gotchas) to
`<partition>/phases/create-pr/handoff-context.md`, then run:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/handoff.py" --ticket <ticket-id> --summary "<done / in-flight / next / decisions>"
```

Tell the user the `continue_with` command it prints, and stop.

## Finish

MANDATORY final step — never skipped, also on failure:

1. Write `<partition>/phases/create-pr/result.json` per the result-document
   contract in INTERNALS.md:

   ```json
   {
     "status": "completed",
     "stop_reason": "verifier passed on iteration 1 with 0 findings; PR #42 ready for review",
     "states": {
       "pr": {
         "number": 42,
         "url": "https://github.com/acme/shop/pull/42",
         "branch": "task/SHOP-123-bulk-import",
         "base": "main"
       }
     },
     "findings": [],
     "errors": [],
     "tokens": {"input": 52000, "output": 9000},
     "cost_usd": 0.34
   }
   ```

   Canonical `states` key — EXACT name and shape, the /acs:merge-pr gate reads
   it: `pr` `{number, url, branch, base}` (`base` is the default branch the PR
   targets). On failure keep whatever is true: if the PR was created or
   updated but verification failed, still record the real `pr` object; if no
   PR exists, omit `pr` entirely (never a stub) — the /acs:merge-pr gate stays
   closed. Put verifier findings in `findings`, errors in `errors`, the reason
   in `stop_reason`. Always fill `tokens` and `cost_usd` with your best
   estimates for this run.

2. Run the post-hook:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/post-create-pr.py" --ticket <ticket-id> --result-file <partition>/phases/create-pr/result.json
   ```

   If it exits non-zero, surface its stderr verbatim — the pipeline gate stays
   closed until it succeeds. On success it finalizes the run, moves the ticket
   to `in_review`, and counts the PR in metrics.

3. Report a compact summary to the user: PR number + URL, branch -> base, ACS
   label confirmed, tracker sync result (or n/a), created vs updated,
   iterations used, and the next step — review the PR yourself, then run
   `/acs:merge-pr <ticket-id>` (a user action; the pipeline never triggers
   it). Under /acs:ship, instead return ONLY the `<handoff>` XML as your final
   message — status, summary (<=1KB) naming the PR number/URL, `<artifacts>`
   referencing `phases/create-pr/result.json`, and `<next-step>` pointing at
   /acs:merge-pr as the user's review-and-merge action.

## Completion report (normative)

Every terminal outcome of a direct invocation — completed, failed,
interrupted, or handed off — ends your final message with the standard block
(INTERNALS.md "Completion report"), rendered only AFTER the post-hook
succeeded. Same labels, same order, `none` where empty; under /acs:ship your final message is the `<handoff>` XML instead — this report is for direct invocations:

```markdown
## /acs:create-pr · <ticket-id> · <status>

- **Ticket**: <id> — <title> (<type>)
- **Status**: <status> — <stop_reason>
- **Results**: PR number and URL; base branch; head branch; `ACS` label applied
- **Findings**: <open findings / clarifications, or "none">
- **Artifacts**: <partition files, repo paths, branch, PR URL>
- **Metrics**: iterations <n>/3 · <wall time> · ~<tokens in/out> · ~$<cost_usd>
- **Next**: review the PR yourself, then `/acs:merge-pr <ticket-id>` — merging stays a user action
```
