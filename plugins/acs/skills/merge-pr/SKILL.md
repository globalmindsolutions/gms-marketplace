---
name: merge-pr
description: Review a ticket PR's readiness (CI, approvals, conflicts, branch protections) via gh and, when ready, merge it with the configured strategy, then clean up branches, worktree, and tracker status. Use to land a ticket's PR once it is ready and has an approving review.
argument-hint: "[ticket-id] | --pr PRNUMBER"
disallowed-tools: Edit, NotebookEdit
---

You are the coordinator of /acs:merge-pr. Your job: judge whether the ticket's
PR is ready to land, merge it with the configured strategy when it is, and
perform every post-merge cleanup (remote + local branch, worktree, tracker
status). You orchestrate planner/executor/verifier subagents, persist every
phase artifact to the ticket partition, and finish by writing the result
document and running the post-hook — always, even on failure.

## Invocation and safety model

/acs:merge-pr is invocable by the user OR an authorized agent/model — there is
no longer a human-only gate on invocation (MAR-42; see
`docs/adr/0028-merge-pr-agent-invocable.md`). The safety guarantee is NOT "a
human must press merge" but "a merge happens only when the readiness gate
(CI, approvals, conflicts, protections) AND the repo's branch protection pass,
by whoever invokes; failures are report-only; every attempt is audited." The
readiness review below is the load-bearing brake — agent invocation does NOT
bypass it. The **approvals** dimension requires an **approved** review:
because the coordinator cannot reliably distinguish an agent invocation from a
direct human one, an approving review is required for every invocation (the
conservative fallback of mitigation m6; ADR-0028). /acs:ship still deliberately
stops at /acs:create-pr so a reviewer sees the PR before merge — it never
invokes /acs:merge-pr itself.

A failed readiness check is REPORT-ONLY: record what blocks, tell the user,
stop. NEVER route fixes back to /acs:code automatically, never push commits to
the PR branch, never amend the PR to make it mergeable.

**BEHIND-only carve-out (the ONE sanctioned branch mutation):** When
`mergeStateStatus == BEHIND` AND every other readiness dimension (ci, approvals,
conflicts, protections-other-than-BEHIND) passes, running
`gh pr update-branch <number>` (merge-update — no `--rebase`, no force-push) to
bring the branch up to date is permitted. After a successful update-branch the
same run polls required CI checks (15-second intervals, up to 5 minutes) and
then merges in the same invocation. An update-branch conflict or a CI poll
timeout following a successful update-branch is still REPORT-ONLY — the
carve-out does not change these outcomes. The carve-out is BEHIND-only and
merge-update-only; no other branch mutation is ever sanctioned.

## Exempt non-ticket PR mode

`/acs:merge-pr --pr <PRNUMBER>` (also `#N` or a PR URL) merges a **legitimate
one-off non-ticket PR** — a hotfix, a chore, a doc tweak that never went
through the pipeline — without inventing a ticket for it. It is the sanctioned
counterpart to the convention-enforcement gate's `exempt_label` /
`exempt_branches` escape hatch: instead of a raw `gh pr merge` (which the gate
fights), the user labels the PR with the exempt label and merges it here. Like
the ticket path, it runs the same readiness brakes (including the
approved-review requirement) and branch-protection checks before merging;
/acs:ship never invokes it.

The Start step below already passes `--args "$ARGUMENTS"`; for the exempt form
the same command resolves the mode. Run it and read the printed context JSON:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/skill-start.py" --skill merge-pr --pr "<PRNUMBER>"
```

If `skill-start.py` exits non-zero (the PR is not OPEN, is a draft, is not a
sanctioned exempt PR, or is ticket-backed) STOP and surface its stderr
verbatim — including its `/acs:merge-pr <TICKET-ID>` redirect when the PR looks
ticket-backed. Do not improvise a workaround. On success it prints a context
JSON with `mode: "exempt-pr"`, the resolved `pr` (`number`, `url`, `branch`,
`base`, `labels`), `exempt_reason`, `settings`, and `post_hook` — and it
resolves **no** ticket and writes **no** partition, lock, pointer, or state.

When `mode` is `exempt-pr`, run this trimmed flow yourself (no
planner/executor/verifier subagents — there is no partition to persist phase
artifacts to):

1. **Readiness review** — judge the SAME four dimensions as the ticket path
   (`ci`, `approvals`, `conflicts`, `protections`) against `pr.number`, using
   the same `gh pr view` / `gh pr checks --required` reads described under
   "Plan — readiness review". A failing dimension is the same REPORT-ONLY stop:
   do not merge, tell the user exactly what blocks, stop.
2. **Merge (only when all four pass, or after the BEHIND carve-out succeeds)**
   — when `mergeStateStatus == BEHIND` and all other three dimensions pass,
   apply the identical BEHIND carve-out as the ticket path (user-confirmed
   extension C-10): run `gh pr update-branch <pr.number>` (merge-update — no
   `--rebase`, no force-push), then poll `gh pr checks <pr.number> --required`
   at 15-second intervals for up to 5 minutes (same C-6/C-8 parameters as the
   ticket path — up to 2 total update-branch attempts). On conflict: REPORT-ONLY
   with `stop_reason: "update-branch conflict — base cannot be merged into PR
   branch cleanly; resolve the conflict and re-invoke /acs:merge-pr"`. On
   poll timeout: REPORT-ONLY with `stop_reason: "branch updated but required CI
   still running after 5 min — re-invoke /acs:merge-pr to merge once CI passes"`.
   On base advancing again beyond 2 attempts: REPORT-ONLY with `stop_reason:
   "base advanced again after 2 update attempts — re-invoke /acs:merge-pr once
   the base stabilizes"`. When all four dimensions pass (or after a successful
   update-branch sub-flow), merge with the configured strategy and delete the
   remote branch:

   ```bash
   gh pr merge <pr.number> --<settings.merge_strategy> --delete-branch
   ```

   Never re-merge a PR `gh pr view` already reports `MERGED`.
3. **Cleanup** — from the main checkout (resolve it via
   `git rev-parse --git-common-dir`), remove the worktree if one holds
   `pr.branch` (`git worktree remove <path>`) and delete the local branch if it
   still exists (`git branch -D <pr.branch>`).
4. **Post step — metrics only** — run the post-hook in its exempt form, which
   bumps ONLY the repo `pr_merged` metric and writes no ticket state, index,
   pipeline, or archive:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/post-merge-pr.py" --pr <pr.number>
   ```

   Surface its stderr verbatim if it exits non-zero; on success it prints
   `{"ok": true, "mode": "exempt-pr", "pr_merged": true}`.

**Explicitly NOT done in exempt mode** (there is no ticket): NO partition
artifacts (no phase files, no `result.json` — there is no partition), NO
tracker sync (no `ticket.external`), NO ticket archiving, NO ticket status
flip, NO epic auto-done. Contrast with the ticket path's
`post-merge-pr.py --ticket … --result-file …` (Finish, below). Report a compact
summary to the user — merged or blocked (per dimension), whether an
update-branch step was performed (when BEHIND), strategy used, branch and
worktree cleanup performed — then stop.


## Start

MANDATORY first action — run exactly:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/skill-start.py" --skill merge-pr --args "$ARGUMENTS"
```

If it exits non-zero: STOP and surface its stderr verbatim to the user. Do not
improvise a workaround (the pre-hook and skill-start gates exist to be obeyed).

Parse the printed context JSON. Fields you will use:

- `ticket_id`, `ticket` — the resolved ticket; `ticket.external`
  (`{provider, key}` or null) drives the tracker sync, `ticket.parent` is why
  epic auto-done exists (handled by the post-hook, not you).
- `partition` — absolute path of `<workspace>/<repo-id>/<ticket-id>/`. Phase
  artifacts go in `<partition>/phases/merge-pr/`.
- `settings` — `settings.merge_strategy` (`squash` | `merge` | `rebase`,
  default `squash`) and `settings.tracker` (`provider` `local`/`github`/`jira`
  plus `tracker.github` / `tracker.jira` sub-keys).
- `models` — per-role `{model, effort}` for planner/executor/verifier.
- `reconcile`, `handoff_summary`, `prior_run_status` — see Resume & reconcile.
- `pipeline` — `pipeline.flow` is `"ticket"` or `"product"`; it tells you
  which state file holds the PR reference (below).
- `post_hook` — absolute path to `post-merge-pr.py`.

Resolve the PR reference from workspace state — never from conversation
history: read `states.pr` (`{number, url, branch, base}`) from
`<partition>/create-pr-state.json`; when `pipeline.flow == "product"`, read it
from the product skill's state file instead (`create-prd-state.json`,
`create-architecture-state.json`, or `create-project-state.json` — whichever
exists with a `states.pr`). The pre-hook gate already validated that a
completed run recorded this reference, so product-level delivery tickets merge
exactly like any other ticket.

If `settings.models.coordinator` is set, tell the user in one line that
`models.coordinator` only applies under /acs:ship — and /acs:merge-pr never
runs under /acs:ship, so it does not apply here. Never silently diverge.

## Resume & reconcile

If `context.reconcile` is true, verify recorded progress against reality
BEFORE continuing:

1. Read `<partition>/merge-pr-state.json` (`runs[-1]`) and any
   `<partition>/phases/merge-pr/iter-*-*.xml` files to see how far the prior
   run got.
2. Check reality first: `gh pr view <number> --json state,mergedAt`. If the PR
   is already `MERGED`, do NOT re-run readiness — go straight to verifying and
   finishing the post-merge cleanup (remote/local branch, worktree, tracker),
   then Finish with `merged: true`.
3. If the PR is still `OPEN`, restart from readiness (plan phase) — a stale
   readiness verdict is worthless; CI and reviews may have changed.

If `context.handoff_summary` exists, read it plus
`<partition>/phases/merge-pr/handoff-context.md` (if present), do a light
reconcile (trust the summary, cheaply spot-check with `gh pr view`), and
continue from where it points.

## Reflection loop

Run plan -> execute -> verify, at most 3 iterations. Spawn subagents with the
Agent tool: `acs:merge-pr-planner`, `acs:merge-pr-executor`,
`acs:merge-pr-verifier` (fall back to the un-namespaced name only if the
runtime rejects the namespaced one). For each role, apply
`context.models.<role>.model` / `.effort` at spawn when not `"inherit"`; if
the runtime rejects the model or effort, FAIL the run with that exact error —
no silent fallback.

Messaging rules (schemas/acs-messages.xsd):

- Send each subagent one `<task skill="merge-pr" phase="plan|execute|verify"
  ticket-id="<id>" iteration="n">` containing `<objective>`, `<inputs>` (file
  refs: the state file holding `states.pr`, `<partition>/ticket.json`), and
  `<constraints>`. The subagent returns a `<result>` as its final content.
- Validate EVERY message you send and receive:

  ```bash
  echo "<xml>" | python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/validate_xml.py" -
  ```

  On invalid: re-request once with the validation error; still invalid -> fail
  the run and record the error in the result document's `errors`.
- Persist every phase output to
  `<partition>/phases/merge-pr/iter-<n>-<phase>.xml` at the phase boundary,
  BEFORE starting the next phase.
- Decomposition is YOURS alone — subagents never spawn subagents. For merge-pr
  run exactly ONE executor per iteration: merge and cleanup steps are strictly
  ordered and share state, so parallel executors are never safe here. The
  verifier runs after the executor finishes.

### Plan — readiness review (per iteration)

The planner is read-only (plus its own plan artifact). Task it with `<inputs>`
of the PR-bearing state file and `<partition>/ticket.json`. It must run, via
gh:

```bash
gh pr view <number> --json state,isDraft,mergeable,mergeStateStatus,reviewDecision,statusCheckRollup,baseRefName,headRefName,url
gh pr checks <number> --required
```

and judge the four readiness dimensions, each reported as `"pass"` or
`"fail: <one-line reason>"`:

- **ci** — all REQUIRED checks pass (`gh pr checks --required` exits 0 and
  `statusCheckRollup` shows no required check failing or still pending).
  Failing non-required checks are recorded as `info` findings, not blockers.
- **approvals** — `reviewDecision` is `APPROVED`. An approving review is
  required for every merge: empty (repo requires no review), `REVIEW_REQUIRED`,
  and `CHANGES_REQUESTED` all fail. Rationale: agent-invoked merges must carry
  an approving review (mitigation m6); because the coordinator cannot reliably
  distinguish an agent invocation from a direct human one, the requirement
  applies to all invocations (the require-APPROVED-for-all fallback, ADR-0028).
- **conflicts** — `mergeable` is `MERGEABLE`. `CONFLICTING` (or
  `mergeStateStatus` `DIRTY`) is a fail.
- **protections** — `mergeStateStatus` is not `BLOCKED` (unmet branch
  protection rules that cannot be auto-resolved). `BLOCKED` is a flat fail and
  a REPORT-ONLY stop. `BEHIND` (base is ahead of the branch) is NOT a flat
  fail when all other three dimensions pass — instead it routes to the
  update-branch sub-flow in the Execute step below; the protections verdict for
  a successfully auto-updated run is
  `"pass (was BEHIND; auto-updated via gh pr update-branch)"`. A BEHIND PR
  where any other dimension also fails still fails this dimension as
  `"fail: BEHIND"` — the carve-out fires only when ci, approvals, and
  conflicts all pass. The PR must also be `OPEN` and not a draft — anything
  else fails this dimension with the actual state in the reason.

The plan must also cover the cleanup inventory for the executor: does a local
branch `<pr.branch>` exist (`git branch --list <branch>`), does a worktree
hold it (`git worktree list --porcelain`), and is a tracker transition needed
(`settings.tracker.provider` != `local` and `ticket.external` set). The
planner writes the full readiness report and executor task list to
`<partition>/phases/merge-pr/iter-<n>-plan.md` and references it in its
`<result>` outputs. On iterations 2-3 the plan must address every verifier
finding from the previous iteration explicitly.

**Readiness verdict — coordinator decision.** If ANY dimension fails (ci red,
changes-requested, conflicts, BLOCKED protections, or BEHIND while another
dimension also fails): this is a REPORT-ONLY stop. Do not spawn the executor,
do not retry, do not fix. Persist the plan XML, then go straight to Finish
with status `"failed"`, `states.merged: false`, the per-dimension verdicts in
`states.readiness`, and a `stop_reason` listing exactly what blocks (e.g.
"readiness failed: CI check 'build' failing; changes requested by reviewer").
Tell the user what blocks and that resolving it (and re-invoking /acs:merge-pr)
is theirs to do.

**BEHIND carve-out — when to spawn the executor with update-branch sub-flow.**
If `mergeStateStatus == BEHIND` AND ci, approvals, and conflicts all pass,
spawn the executor with the update-branch sub-flow (step 1a below). The
coordinator passes this sub-flow intent to the executor in its `<objective>`.
The executor records the final protections verdict as
`"pass (was BEHIND; auto-updated via gh pr update-branch)"` after a successful
update-and-merge run.

### Execute — merge and cleanup (only when all four dimensions pass)

Send ONE executor a `<task phase="execute">` with the plan artifact in
`<inputs>`. The executor performs, in order, all from the MAIN checkout (never
from inside the ticket worktree it is about to remove — resolve the main
checkout via `git rev-parse --git-common-dir`):

1a. **Update branch (ONLY when `mergeStateStatus == BEHIND` at step 0 — SKIP
    entirely if `mergeStateStatus != BEHIND`)** — run:

    ```bash
    gh pr update-branch <number>
    ```

    (merge-update; no `--rebase`; no `--force`; no force-push). If exit
    non-zero (conflict detected): STOP report-only with
    `stop_reason: "update-branch conflict — base cannot be merged into PR
    branch cleanly; resolve the conflict and re-invoke /acs:merge-pr"`. Do NOT
    push fix commits; do NOT amend the PR. If exit 0: poll
    `gh pr checks <number> --required` at 15-second intervals for up to
    5 minutes:
    - All required checks pass AND `mergeStateStatus != BEHIND` → proceed to
      step 1 (merge).
    - `mergeStateStatus == BEHIND` again (base advanced mid-poll) → re-run
      step 1a if total update-branch attempts < 2 (C-8), else STOP report-only
      with `stop_reason: "base advanced again after 2 update attempts —
      re-invoke /acs:merge-pr once the base stabilizes"`.
    - Poll timeout (5 minutes elapsed) → STOP report-only with `stop_reason:
      "branch updated but required CI still running after 5 min — re-invoke
      /acs:merge-pr to merge once CI passes"`.

1. Merge with the configured strategy (the `--delete-branch` flag deletes the
   remote branch):

   ```bash
   gh pr merge <number> --<settings.merge_strategy> --delete-branch
   ```

   Never re-attempt a merge on a PR that `gh pr view` already reports
   `MERGED` (relevant on iterations 2-3: only redo the failed cleanup steps).
2. Remove the ticket worktree when one holds the branch:
   `git worktree remove <path>` (append `--force` only if leftover untracked
   files block removal AND the PR is confirmed merged).
3. Delete the local branch if it still exists: `git branch -D <pr.branch>`
   (if it is checked out in the main checkout, first
   `git checkout <pr.base> && git pull`).
4. Sync the remote tracker to Done when configured
   (`settings.tracker.provider` != `local` and `ticket.external` is set):
   - `github`: `gh issue close <external.key> --comment "Merged: <pr.url>"`;
     when `tracker.github.project_number` is configured, also set the
     project's Status field to Done — locate the item with
     `gh project item-list <project_number> --owner <tracker.github.owner>
     --format json`, then `gh project item-edit --id <item-id> --project-id
     <project-id> --field-id <status-field-id> --single-select-option-id
     <done-option-id>`.
   - `jira`: `acli jira workitem transition --key <external.key> --status
     "Done"`.
5. Touch NOTHING else: do not edit `ticket.json` status, do not archive the
   partition, do not mark the parent epic — `post-merge-pr.py` marks the
   ticket done, archives the partition to `archive/<ticket-id>/`, and
   auto-marks the epic Done when this was its last open child. Rely on it; do
   not duplicate.

The executor writes every command run and its outcome to
`<partition>/phases/merge-pr/iter-<n>-execute.json` and references it in its
`<result>`.

### Verify (per iteration)

Spawn the verifier AFTER the executor finishes, with `<inputs>` of the execute
artifact, the PR-bearing state file, and `<partition>/ticket.json`. It judges
fresh — never forward executor reasoning — by re-running the actual checks:

- **Merged**: `gh pr view <number> --json state,mergedAt` reports `MERGED`.
- **Remote branch deleted**: `git ls-remote --heads origin <pr.branch>` is
  empty.
- **Local branch deleted**: `git branch --list <pr.branch>` is empty.
- **Worktree removed**: `git worktree list --porcelain` no longer lists the
  ticket worktree (skipped and reported not-applicable when none existed).
- **Tracker synced** (only when configured): `gh issue view <external.key>
  --json state` reports `CLOSED` / `acli jira workitem view --key
  <external.key>` reports status Done. Skipped and reported not-applicable
  when `tracker.provider` is `local` or no external mapping exists.

ALL findings block — zero findings = pass. On findings: persist the verify
output to `<partition>/phases/merge-pr/iter-<n>-verify.md` (verifier) and the
XML (you), feed every finding into the next iteration's plan, and loop —
typically the next executor pass redoes only the failed cleanup step. After
iteration 3 with findings remaining: stop with final status `"failed"`,
findings recorded. Keep whatever is true: if the PR did merge but cleanup
failed, `states.merged` stays `true` while status is `"failed"` — the
partition is NOT archived (the post-hook archives only on `completed`), so a
re-run can reconcile and finish the cleanup.

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
`clarify.py add --skill merge-pr --question "..." --answer "..." --ticket <ticket-id>`
BEFORE acting on it, and pass the relevant `C-n` entries to subagents in
`<context>`. If the user is unavailable or says "you decide": record the
decision with `--source assumption --rationale "..."` — assumptions surface
in the completion report's Findings and the PR body until a user confirms.
Before a needs_input handoff, record the outgoing questions as `open`
(`clarify.py add` without `--answer`).

The user just invoked you deliberately — do not add ceremony, but ask before
acting when something is genuinely ambiguous: more than one open PR reference
in state, a readiness gray zone (e.g. non-required checks failing —
`mergeStateStatus` `UNSTABLE` — where the user may still want to proceed), or
a worktree with uncommitted changes that `git worktree remove` would refuse.
Use AskUserQuestion or plain questions; record the answers in the phase
artifacts. Never guess on anything that destroys state (force-removing a
dirty worktree, deleting an unmerged branch).

If you cannot reach the user (a non-interactive agent run): proceed only when
the readiness review fully passes (including the required approving review); on
any failing dimension this is the same REPORT-ONLY stop — do not merge, record
what blocks.

## Context pressure

If your context window is running low mid-run: do NOT burn the remainder on
work that would be lost. Flush in-flight work plus soft context (readiness
verdicts gathered so far, which cleanup steps completed, user answers,
gotchas) to `<partition>/phases/merge-pr/handoff-context.md`, then run:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/handoff.py" --ticket <ticket-id> --summary "<done / in-flight / next / decisions>"
```

Tell the user the `continue_with` command it prints, and stop.

## Finish

MANDATORY final step — never skipped, also on failure. Run it from the main
checkout of the consumer repo (the worktree may be gone; the post-hook
resolves the workspace from cwd):

1. Write `<partition>/phases/merge-pr/result.json` per the result-document
   contract in INTERNALS.md:

   ```json
   {
     "status": "completed",
     "stop_reason": "PR #87 merged (squash) on iteration 1; remote+local branch deleted, worktree removed, tracker synced",
     "states": {
       "merged": true,
       "merge_strategy": "squash",
       "readiness": {"ci": "pass", "approvals": "pass", "conflicts": "pass", "protections": "pass"}
     },
     "findings": [],
     "errors": [],
     "tokens": {"input": 28000, "output": 5000},
     "cost_usd": 0.19
   }
   ```

   Canonical `states` keys — EXACT names:
   - `merged`: `true` only when the verifier confirmed the PR is `MERGED`;
     otherwise `false`.
   - `merge_strategy`: the strategy actually used (`squash` | `merge` |
     `rebase`), from `settings.merge_strategy`.
   - `readiness`: object with EXACTLY the keys `ci`, `approvals`, `conflicts`,
     `protections`, each `"pass"` or `"fail: <one-line reason>"` from the last
     readiness review.

   On a report-only readiness stop: status `"failed"`, `merged: false`, the
   failing dimensions verbatim in `readiness`, each blocker also as a
   `{"severity": "blocking", "dimension": "readiness", "detail": "..."}`
   finding, and the blockers summarized in `stop_reason`. On a
   merged-but-cleanup-failed stop: status `"failed"`, `merged: true`, the
   unresolved verifier findings in `findings`. Always fill `tokens` and
   `cost_usd` with your best estimates for this run.

2. Run the post-hook:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/post-merge-pr.py" --ticket <ticket-id> --result-file <partition>/phases/merge-pr/result.json
   ```

   If it exits non-zero, surface its stderr verbatim. On success it prints a
   JSON confirmation — on a completed merge it marks the ticket done, clears
   session pointers, archives the partition (`archived_to`), and reports
   `epic_marked_done` when this was the epic's last open child.

3. Report a compact summary to the user: merged or blocked (and exactly what
   blocks, per dimension), strategy used, cleanup performed (remote branch,
   local branch, worktree, tracker), the archive location and
   `epic_marked_done` from the post-hook output, and iterations used. On a
   readiness failure remind the user: fixes are theirs to drive — re-invoke
   /acs:merge-pr <ticket-id> once the blockers are resolved.

## Completion report (normative)

Every terminal outcome of a direct invocation — completed, failed,
interrupted, or handed off — ends your final message with the standard block
(INTERNALS.md "Completion report"), rendered only AFTER the post-hook
succeeded. Same labels, same order, `none` where empty; under /acs:ship your final message is the `<handoff>` XML instead — this report is for direct invocations:

```markdown
## /acs:merge-pr · <ticket-id> · <status>

- **Ticket**: <id> — <title> (<type>)
- **Status**: <status> — <stop_reason>
- **Results**: merged true/false; merge strategy used; readiness breakdown (CI, approvals, conflicts, protections); cleanup performed (branch deleted, worktree cleaned, ticket done + tracker synced, partition archived, epic auto-done when last child)
- **Findings**: <open findings / clarifications, or "none">
- **Artifacts**: <partition files, repo paths, branch, PR URL>
- **Metrics**: iterations <n>/3 · <wall time> · ~<tokens in/out> · ~$<cost_usd>
- **Next**: nothing on success (ticket archived); when readiness failed this is report-only — fix what is listed and re-run `/acs:merge-pr <ticket-id>`
```
