---
name: create-project
description: Scaffold a greenfield product's repository skeleton from the approved architecture doc set — directory layout, build config, test framework with coverage tooling, linter/formatter, pre-commit, CI, and a minimal green vertical slice. Use exactly once on a fresh product repo after /acs:create-architecture and before the first ticket; never on an existing codebase.
argument-hint: "(no arguments)"
disallowed-tools: Edit, NotebookEdit
---

# /acs:create-project — coordinator instructions

You are the coordinator of /acs:create-project. You scaffold a fresh product's repo
skeleton from the approved architecture so the ticket pipeline — especially the
/acs:code TDD gates — works from ticket #1. You orchestrate; subagents do the work.
This is a product-level skill with its own delivery ticket, branch, and PR; the
scaffolded CI workflow runs on that very PR. Greenfield only: existing codebases
never need this skill.

## Start

MANDATORY first action — run before anything else:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/skill-start.py" --skill create-project --allocate
```

`--allocate` creates the delivery ticket (type `task`, title "Project scaffold",
e.g. `SHOP-3`), its workspace partition, the `.lock`, and an `in_progress` run
entry. Parse the printed context JSON; the fields you will use:

- `ticket_id`, `ticket`, `partition` — the delivery ticket and its workspace partition
- `checkout_root` — the consumer repo root (the only tree executors mutate)
- `settings` — `test_coverage_percent`, `architecture_path`, `prd_path`, `formats`, `tracker`
- `models` — per-role `{model, effort}` resolved from settings
- `reconcile`, `handoff_summary`, `prior_run_status`, `pipeline`
- `post_hook` — absolute path of `post-create-project.py`

If skill-start exits non-zero: stop and surface its stderr verbatim — do not improvise.

If `settings.models.coordinator` is set, surface a one-line notice that it governs the
/acs:ship coordinator's own session — under /acs:ship this skill is invoked directly
in that session (no separate per-step agent for the key to apply to), and a directly
typed invocation runs in the user's session on the session's model — then continue on
the current model. Never silently diverge.

Apply `context.models.<role>.model` / `.effort` when spawning each subagent, unless
the value is `"inherit"`. If the runtime rejects the model id or effort, FAIL the run
with that exact error — no silent fallback.

## Resume & reconcile

`--allocate` always creates a fresh ticket, so `context.reconcile` is normally false.
Three cases:

- **Prior unfinished scaffold run.** Check `<workspace>/<repo_id>/tickets-index.json`
  for an earlier "Project scaffold" ticket that is not `done`. If one exists, resume
  it instead of scaffolding twice: (1) close the just-allocated ticket — write its
  `result.json` (see Finish) with `status: "failed"`, `stop_reason: "duplicate
  allocation; resumed <PRIOR-ID>"`, and run the post-hook for it; (2) re-run
  skill-start with `--ticket <PRIOR-ID>` (no `--allocate`) and continue with that
  context — it will report `reconcile: true`.
- **`context.reconcile` is true** (resumed ticket): verify recorded progress against
  reality BEFORE continuing — re-read `<partition>/phases/create-project/` artifacts,
  inspect `git -C <checkout_root> status` and `git log` on the scaffold branch, and
  re-run any build/lint/test command recorded as passing. Trust nothing you cannot
  re-verify; continue from the first unfinished phase.
- **`context.handoff_summary` exists**: read it, plus
  `<partition>/phases/create-project/handoff-context.md` if present, do a light
  reconcile (spot-check its claims against the repo and partition), and continue
  from where it points.

## Greenfield gate

The pre-hook already verified the architecture doc set exists
(`<architecture_path>/hld/tech-stack.md`). YOU verify the repo is actually
greenfield before any planning:

```bash
git -C <checkout_root> ls-files | grep -vE '^(docs/|\.acs/|\.claude/|\.gitignore$|README[^/]*$|LICENSE[^/]*$|CLAUDE\.md$)'
```

Any output (source trees, package manifests, lockfiles, CI workflows) means
substantive sources already exist. When resuming a prior scaffold ticket, run the
scan against the default branch instead (`git -C <checkout_root> ls-tree -r
--name-only origin/HEAD`) so the unfinished scaffold's own files do not trip it.

If substantive sources exist, REFUSE politely:

1. Tell the user /acs:create-project is greenfield-only and is never needed again
   once a codebase exists — point them at the pipeline instead: `/acs:create-ticket`
   then `/acs:ship` per change (and `/acs:create-architecture` re-runs keep the doc
   set current on an existing codebase).
2. Skip the reflection loop and go straight to Finish with `status: "failed"`,
   `stop_reason: "greenfield-only: repository already contains substantive sources"`,
   all `states.scaffold` booleans `false`, and one blocking finding
   (`dimension: "greenfield"`) listing the files found.

## Reflection loop

Plan -> execute -> verify, at most 3 iterations. Decomposition is YOURS alone —
subagents never spawn subagents. Before the loop:
`mkdir -p <partition>/phases/create-project`.

Messaging rules for every phase:

- Communicate per `schemas/acs-messages.xsd`: you send a `<task>`, the subagent
  returns a `<result>` as the final content of its reply.
- Validate EVERY message, sent and received:

```bash
echo "<task ...>...</task>" | python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/validate_xml.py" -
```

- Invalid message from a subagent: re-request once; still invalid -> fail the run,
  recording the validation error in result.json `errors`.
- Persist every phase output to `<partition>/phases/create-project/iter-<n>-<phase>.xml`
  at the phase boundary, BEFORE starting the next phase (parallel executors: suffix
  `iter-<n>-execute-a.xml`, `-b.xml`, ...).
- Spawn with the Agent tool, `subagent_type` `acs:create-project-planner` /
  `acs:create-project-executor` / `acs:create-project-verifier`; fall back to the
  un-namespaced name only if the runtime rejects the namespaced one.

### Plan

Spawn the planner. Resolve doc paths from `settings.architecture_path` and
`settings.prd_path` (defaults shown); put `settings.test_coverage_percent` in the
constraints. Example (iteration 1, repo-relative input paths):

```xml
<task skill="create-project" phase="plan" ticket-id="SHOP-3" iteration="1">
  <objective>Produce a complete scaffold plan for this greenfield repo per the architecture doc set; write it to the workspace partition as phases/create-project/scaffold-plan.md and list it in outputs.</objective>
  <inputs>
    <file>docs/architecture/hld/tech-stack.md</file>
    <file>docs/architecture/hld/c4-container.md</file>
    <file>docs/architecture/hld/c4-component.md</file>
    <file>docs/architecture/hld/overview.md</file>
    <file>docs/architecture/hld/deployment.md</file>
    <file>docs/product/prd.md</file>
  </inputs>
  <constraints>
    <constraint name="coverage-threshold">90</constraint>
    <constraint name="writes">workspace partition only; the repo is not touched in this phase</constraint>
    <constraint name="decisions">pin every choice; flag anything tech-stack.md leaves open as a question, do not guess</constraint>
  </constraints>
</task>
```

The plan MUST pin, concretely, with nothing left open:

- directory layout mirroring the C4 container/component views;
- package/build configuration files and the package manager;
- an e2e harness (e.g. Playwright for a web UI, an API-level suite for
  services) WHEN the architecture has a user-facing or cross-component
  surface — wired into CI plus one smoke e2e test in the vertical slice, and
  the matching `e2e` settings block proposed to the user (`command`, setup/
  teardown) for `.acs/settings.json`;
- the test framework AND coverage tooling, configured to fail below
  `settings.test_coverage_percent`;
- linter/formatter and pre-commit configuration;
- a CI workflow (e.g. `.github/workflows/ci.yml`) running build, lint, tests, and
  coverage;
- `.gitignore` and a README skeleton;
- the minimal GREEN vertical slice: one real entrypoint plus one smoke test that
  exercises it;
- the EXACT verification commands (install, build, lint, test-with-coverage) — the
  contract for both the verifier and the CI workflow.

On iterations 2–3, include the verifier's findings verbatim in `<context>` and
instruct the planner to produce a remediation plan covering only those findings.
Persist the planner's `<result>` to `iter-<n>-plan.xml` before executing.

### Execute

Iteration 1 only — create the delivery branch before any executor runs (you do all
git operations; executors never commit). Branch name per `settings.formats.branch_name`
(default `{type}/{ticket_id}-{slug}`) with `type=task`, the real ticket id, and the
slug of the ticket title:

```bash
git -C <checkout_root> checkout -b task/SHOP-3-project-scaffold
```

Spawn executor(s) with `<task skill="create-project" phase="execute" ticket-id="..."
iteration="n">`: `<inputs>` reference the scaffold plan (and on iterations 2–3 the
findings being remediated); `<constraints>` pin the exact file set each executor
owns. Executors mutate ONLY `<checkout_root>`. You MAY run several executors in
parallel when their file sets cannot conflict — e.g. one owns build/test/lint/
pre-commit config plus the CI workflow, another owns the directory layout, vertical
slice, README, and `.gitignore`. The verifier runs only after ALL executors finish
and judges the combined result. Persist executor `<result>`s to
`iter-<n>-execute*.xml`.

### Verify

Spawn the verifier with `<task skill="create-project" phase="verify" ...>` whose
inputs are artifacts only — the scaffold plan and the repo tree, never executor
reasoning; it judges fresh. The verifier MUST actually run, from `<checkout_root>`,
the exact commands the plan pinned, and see them pass:

1. dependency install — exit 0;
2. build — exit 0;
3. lint — exit 0;
4. tests with coverage — every test passes (the smoke test proves the vertical
   slice), the coverage tool reports a percentage, AND its config fails the run
   below `settings.test_coverage_percent`.

Plus static checks: layout matches the container/component views; the CI workflow
runs those same commands; `.gitignore` and README exist; the pre-commit config
installs and its hooks pass on the tree.

A scaffold that does not run green FAILS verification — every failing command is a
blocking finding. ALL findings block: zero findings = pass. On findings, persist
`iter-<n>-verify.xml`, then feed the findings into the next plan/execute iteration.
After iteration 3 with findings remaining: stop and go to Finish with
`status: "failed"` and the findings recorded.

## Delivery — commit, PR, CI proof

Only after a verify pass (zero findings):

1. Commit on the scaffold branch, message per `settings.formats.commit_message`
   (default `{ticket_id} {summary}`), and push:

```bash
git -C <checkout_root> add -A
git -C <checkout_root> commit -m "SHOP-3 Scaffold project skeleton per architecture doc set"
git -C <checkout_root> push -u origin task/SHOP-3-project-scaffold
```

2. Render the PR body from `settings.formats.pr_description_template`: built-in name
   `pr-default` -> `${CLAUDE_PLUGIN_ROOT}/templates/pr-default.md`; otherwise
   `<checkout_root>/.acs/templates/<name>.md`; otherwise an absolute path. Fill every
   placeholder from workspace state (ticket.json, scaffold plan, verifier results) —
   never from conversation memory. Write it to
   `<partition>/phases/create-project/pr-body.md`.

3. Open the PR with the `ACS` label (create the label first; ignore "already exists"),
   title per `settings.formats.pr_title` (default `[{ticket_id}] {title}`) —
   rendered via the helper, NOT LLM prose composition, capturing its stdout
   as `<rendered title>`:

```bash
gh label create ACS --color 5319E7 --description "Created by the acs pipeline" 2>/dev/null || true
python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/pr-conventions.py" render-title \
  --template "<settings.formats.pr_title>" --ticket-id <ticket_id> --type task \
  --title "Project scaffold" --summary "<summary>" --external-key "<ticket.external.key or empty>" \
  --provider "<ticket.external.provider or empty>"
```

   **Pre-open self-check** — before `gh pr create`, self-check the rendered
   title and filled body with the helper's `check` subcommand (a
   deterministic CLI call, never a spawned subagent):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/pr-conventions.py" check \
  --title "<rendered title>" --body-file <partition>/phases/create-project/pr-body.md \
  --require-label ACS --pr-title-format "<settings.formats.pr_title>" \
  --sections "<settings.enforcement.pr_description_sections, comma-joined>" \
  --ticket-prefix <settings.ticket_prefix>
```

   On pass, proceed to `gh pr create` unchanged. On failure, this check
   blocks/retries: apply a bounded local re-render/re-check (up to 2
   attempts) rather than opening a non-conforming PR; if still failing after
   the bounded retries, STOP — do not call `gh pr create` — surface the
   blocking finding with the failing heading(s)/detail(s) in the result
   document.

```bash
gh pr create --title "<rendered title>" --body-file <partition>/phases/create-project/pr-body.md --label ACS
gh pr view --json number,url,headRefName
```

   Record `number`, `url`, and the branch for `states.pr`.

4. CI proof — the scaffolded workflow runs on this very PR; green locally is not
   enough:

```bash
gh pr checks <number> --watch
```

   If CI fails: each failing check is a blocking finding. If the 3-iteration budget
   is not exhausted, run another plan -> execute -> verify iteration to remediate,
   push to the same branch, and re-watch. Budget exhausted or still red: Finish with
   `status: "failed"`, findings recorded, and report the open PR.

Merging stays a user action: after their review the user runs
`/acs:merge-pr <ticket-id>`. Never invoke it yourself.

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
`clarify.py add --skill create-project --question "..." --answer "..." --ticket <ticket-id>`
BEFORE acting on it, and pass the relevant `C-n` entries to subagents in
`<context>`. If the user is unavailable or says "you decide": record the
decision with `--source assumption --rationale "..."` — assumptions surface
in the completion report's Findings and the PR body until a user confirms.
Before a needs_input handoff, record the outgoing questions as `open`
(`clarify.py add` without `--answer`).

Ask the user when genuinely ambiguous — e.g. `hld/tech-stack.md` names a language but
not the test framework, package manager, or CI provider; or the repo has no `origin`
remote to push to. Use AskUserQuestion (or plain questions) with concrete options and
fold the answers into the planner's `<context>`. Do not re-ask anything the
architecture doc set already pins.

If you genuinely cannot reach the user (e.g. a non-interactive run): do NOT
guess. Run Finish with `status: "handed_off"` and the open questions in
`handoff_summary`, and return a `<handoff skill="create-project" ticket-id="..."
status="needs_input">` carrying the `<questions>` as your final message.

## Context pressure

If your context runs low mid-run: flush in-flight work and soft context (user
answers, decisions, partial findings, gotchas, current iteration/phase) to
`<partition>/phases/create-project/handoff-context.md`, then:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/handoff.py" --ticket <ticket-id> --summary "done: <...>; in flight: <...>; next: <...>; decisions: <...>"
```

Tell the user the `continue_with` command it prints, then stop. handoff.py has
already finalized the run as `handed_off` and released the lock — do NOT also run
the post-hook in this path.

## Finish

MANDATORY final step — never skipped, also on failure and on the greenfield refusal
(only the Context-pressure path above replaces it):

1. Write `<partition>/phases/create-project/result.json`:

```json
{
  "status": "completed",
  "stop_reason": "scaffold verified green locally and on the PR CI run",
  "states": {
    "scaffold": {"build": true, "lint": true, "tests": true, "coverage_tooling": true},
    "pr": {"number": 7, "url": "https://github.com/acme/shop/pull/7", "branch": "task/SHOP-3-project-scaffold"}
  },
  "findings": [],
  "errors": [],
  "tokens": {"input": 184000, "output": 32000},
  "cost_usd": 1.85
}
```

   - `status`: `completed | failed | interrupted | handed_off`.
   - `states.scaffold` keys are EXACTLY `build`, `lint`, `tests`, `coverage_tooling`
     — booleans reflecting what the VERIFIER (or the PR's CI) saw pass, not what an
     executor claims. On failure keep whatever is true, e.g. build and lint green
     but tests red -> `{"build": true, "lint": true, "tests": false,
     "coverage_tooling": false}`.
   - `states.pr` (`number`, `url`, `branch`) only when a PR was opened.
   - `findings`: every open finding as
     `{"severity": "blocking|info", "dimension": "...", "detail": "..."}`.
   - `tokens` / `cost_usd`: your estimates for this entire run, subagents included.
   - `handoff_summary`: only when `status` is `handed_off`.

2. Run the post-hook:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/post-create-project.py" --ticket <ticket-id> --result-file <partition>/phases/create-project/result.json
```

   It finalizes the run entry, updates pipeline-state/index/metrics, marks the
   delivery ticket `in_review` when a PR exists, and releases the lock.

3. Report a compact summary: ticket id, PR url, the four scaffold booleans, the
   wired commands (build / lint / test / coverage plus the threshold), and the next
   steps — review then `/acs:merge-pr <ticket-id>`, then `/acs:create-ticket` for
   the first real ticket (typically the MVP epic from the PRD roadmap). If you
   genuinely cannot reach the user (a non-interactive run): your final message is ONLY the `<handoff>` XML —
   status, summary under 1 KB, artifact refs (result.json, scaffold plan, PR url),
   and `<next-step>`.

## Completion report (normative)

Every terminal outcome of a direct invocation — completed, failed,
interrupted, or handed off — ends your final message with the standard block
(INTERNALS.md "Completion report"), rendered only AFTER the post-hook
succeeded. Same labels, same order, `none` where empty; under /acs:ship your final message is the `<handoff>` XML instead — this report is for direct invocations:

```markdown
## /acs:create-project · <ticket-id> · <status>

- **Ticket**: <id> — <title> (<type>)
- **Status**: <status> — <stop_reason>
- **Results**: scaffold summary — layout, build, test framework + coverage tooling, lint, CI, green vertical slice (build/lint/tests verified passing); delivery ticket id; PR number/URL
- **Findings**: <open findings / clarifications, or "none">
- **Artifacts**: <partition files, repo paths, branch, PR URL>
- **Metrics**: iterations <n>/3 · <wall time> · ~<tokens in/out> · ~$<cost_usd>
- **Next**: `/acs:merge-pr <ticket-id>` after reviewing the bootstrap PR (CI runs on it); then `/acs:create-ticket` for the MVP epic
```
