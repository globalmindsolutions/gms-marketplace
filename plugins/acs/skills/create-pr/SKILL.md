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
summary), never from conversation history. You perform the apply-work inline
(or delegate to at most one executor subagent), persist every phase artifact to
the ticket partition, and finish by writing the result document and running the
post-hook — always, even on failure. You never spawn a planner or verifier
subagent for this skill.

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
- `models` — per-role `{model, effort}` for the executor (the only subagent
  role used by this skill; planner and verifier are not spawned).
- `reconcile`, `handoff_summary`, `prior_run_status` — see Resume & reconcile.
- `design` — `{required, dir, source}`; when required, `<design.dir>/design.md`
  feeds the Summary/Changes content.
- `post_hook` — absolute path to `post-create-pr.py`.

If `settings.models.coordinator` is set and this is a DIRECT invocation (a user
typed `/acs:create-pr`, not driven under /acs:ship), tell the user in one line
that `models.coordinator` governs the ship coordinator's own run under
/acs:ship, not a directly typed skill — never silently diverge from it.

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

## Inline apply flow

No planner-executor-verifier triad. No planner or verifier subagents are
spawned for this skill. This inline flow holds in every lane (TRIVIAL / SMALL
/ STANDARD / COMPLEX / absent) — the lane never re-introduces a planner or
verifier for create-pr.

**Verifier-gated upstream (AC-5).** Correctness was already gated by the
upstream code-verifier (/acs:code's verifier subagent, which must pass before
/acs:create-pr is invoked — the pre-hook enforces this via
`code-state.json` `states.verifier_passed == true`). The human checkpoint is
the PR review. /acs:create-pr carries no in-skill verifier; invariant (d)
lives in the upstream code/spec lanes, not in apply-work.

The coordinator performs the following numbered steps directly, or delegates
the entire numbered flow to at most one `acs:create-pr-executor` subagent when
run complexity warrants it. When delegating, send one `<task>` message
(validated with validate_xml.py against schemas/acs-messages.xsd); the
executor returns one `<result>` with the phase artifact reference. The
coordinator never delegates to a planner or verifier. If the runtime rejects a
model or effort setting from `context.models.executor`, FAIL the run with that
exact error — no silent fallback.

1. **Branch.** Verify the ticket branch from `code-state.json` `states.branch`
   exists locally (`git rev-parse --verify <branch>`) or on origin
   (`git ls-remote origin <branch>`). Push it:
   `git push -u origin <branch>`. If the branch only exists on origin and is
   already current, skip the push. Never commit new work — if uncommitted
   implementation changes exist, that is /acs:code's job: surface it as a
   problem and stop.

2. **Body.** Resolve the body template: a built-in name (`pr-default`) maps to
   `${CLAUDE_PLUGIN_ROOT}/templates/pr-default.md`; otherwise
   `<checkout_root>/.acs/templates/<name>.md`; otherwise an absolute path.
   Unresolvable template = blocking problem, surface it. Fill the resolved
   template into `<partition>/phases/create-pr/pr-body.md`: replace every
   placeholder (`{ticket_id}`, `{type}`, `{title}`, `{summary}`,
   `{external_key}`; `{external_key_line}` renders as
   ` — tracker: <provider> <key>` when `ticket.external` is set, empty
   otherwise), replace HTML comments with real content and DELETE the comments,
   fill every section strictly from the state files (`ticket.json`,
   `code-state.json`, `specs/*.md`, `design.md` when required). The base
   branch is the repo's default, detected via
   `gh repo view --json defaultBranchRef --jq .defaultBranchRef.name`.
   Render the PR title via the helper — NOT LLM prose composition — capturing
   its stdout as `<rendered title>`:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/pr-conventions.py" render-title \
     --template "<settings.formats.pr_title>" --ticket-id <ticket_id> --type <ticket.type> \
     --title "<title-value>" --summary "<summary>" --external-key "<ticket.external.key or empty>"
   ```

   `<title-value>` and `<summary>` are derived exactly as before (from
   `ticket.json` / `code-state.json` / specs), only the render mechanism
   changes. This is the exact value passed **verbatim** to `gh pr create
   --title` / `gh pr edit --title` in step 5 — no further transformation.
   Body: Summary (from specs scope + design decision), Ticket (id, title,
   type, external key), Changes (from `specs_implemented`, `docs_updated`,
   and `git diff <base>...<branch> --stat`), Test plan (from
   `tests.passed/failed/coverage_percent/coverage_target` and the specs' test
   plans), Checklist (tick exactly what code-state evidences — e.g. `[x]`
   only when `review.findings_open == 0`).

3. **Label.** `gh label create ACS --description "Created by the acs pipeline" 2>/dev/null || true`

4. **Pre-open self-check.** Before either branch of step 5 runs `gh pr
   create`/`gh pr edit`, self-check the rendered title and filled body
   against the configured conventions with the helper's `check` subcommand —
   a deterministic CLI call, never a spawned subagent and never a
   plan/execute/verify triad — no new subagent role is introduced by this
   step:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/pr-conventions.py" check \
     --title "<rendered title>" --body-file <partition>/phases/create-pr/pr-body.md \
     --require-label ACS --pr-title-format "<settings.formats.pr_title>" \
     --sections "<settings.enforcement.pr_description_sections, comma-joined>" \
     --ticket-prefix <settings.ticket_prefix>
   ```

   - **On pass** (exit 0 / `passed: true`): proceed to step 5 unchanged.
   - **On failure** (exit 1 / `passed: false`): this reports structured
     findings from a deterministic call. Perform a bounded local retry: if
     the failing heading is `pr_title`, re-run `render-title`; if it is
     `pr_description`, `unrendered_placeholder`, or
     `leftover_template_comment`, re-fill the specific missing section or
     delete the surviving placeholder/HTML comment in `pr-body.md`, then
     re-run `check`. Cap the retry at a small bounded number of attempts
     (up to 2 re-renders) — this is a tight fix-and-recheck loop around one
     deterministic call, NOT a new plan/execute/verify iteration. If `check`
     still fails after the bounded retries, STOP: do NOT call `gh pr
     create`/`gh pr edit`; surface a blocking problem naming the exact
     failing heading(s)/detail(s) from the helper's `errors`, write it into
     the phase artifact, and follow the Finish failure path — `states.pr` is
     omitted if no PR exists yet, or kept as the last-known-good object if
     updating an existing PR that could not be re-validated. Never open or
     leave in place a PR known to be non-conforming as a result of this run.
   - Apply this identical self-check on BOTH the create path and the edit
     path below — one `check` call before whichever `gh pr` command ends up
     running.

5. **Create or update PR.** Detect existing open PR:
   `gh pr list --head <branch> --state open --json number,url,baseRefName,isDraft`.
   If no open PR exists for the branch:

   ```bash
   gh pr create --base <default-branch> --head <branch> --title "<rendered title>" --body-file <partition>/phases/create-pr/pr-body.md --label ACS
   ```

   No `--draft` — PRs are created ready-for-review. If an open PR already
   exists for the branch: update it instead —
   `gh pr edit <number> --title "<rendered title>" --body-file <body> --add-label ACS`,
   plus `gh pr edit <number> --base <default-branch>` when its base is wrong
   and `gh pr ready <number>` when it is a draft.

6. **Record.** `gh pr view <branch> --json number,url,baseRefName,headRefName,isDraft,labels`
   → capture `{number, url, branch, base}` for `states.pr`.

7. **Tracker sync.** When `settings.tracker.provider` is `github` or `jira`
   AND `ticket.external.key` is set, comment on the remote issue with the PR
   URL:
   - `github`: `gh issue comment <external.key> --body "ACS: PR #<number> opened for <ticket-id> — <url>"`
   - `jira`: `acli jira workitem comment --key <external.key> --body "ACS: PR opened for <ticket-id> — <url>"`
   Skip for `local`; report an info finding when the provider is configured but
   the ticket was never synced.

Write a phase artifact `<partition>/phases/create-pr/iter-1-execute.json`
(commands run with outcomes, pushed SHA, PR number/url/base, sync result,
problems hit, the pre-open self-check's pass/fail result and, on retry, how
many attempts were used). Validate any `<task>`/`<result>` XML with
validate_xml.py.

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

If you genuinely cannot reach the user (e.g. a non-interactive run): do not
guess. Write the result document with status `"failed"` and
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

Validate it with validate_xml.py like every other message. On invalid:
re-request the message once with the validation error; still invalid → fail the
run and record the error in the result document's `errors`.

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
- **Next**: review the PR, then `/acs:merge-pr <ticket-id>` — a separate, reviewed step
```
