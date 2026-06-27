---
name: create-prd
description: Define or amend the product PRD — vision, problem, personas, goals with measurable success metrics, prioritized features, NFRs, constraints — plus a roadmap, shipped as a docs-only PR on its own delivery ticket. Use when starting a product, onboarding acs onto an existing codebase, or when scope changes require a PRD amendment.
argument-hint: "[product notes | delivery-ticket-id to resume]"
disallowed-tools: Edit, NotebookEdit
---

You are the coordinator of /acs:create-prd. You produce or amend the PRD doc set
(`prd.md` + `roadmap.md`) in the consumer repo at `settings.prd_path` (default
`docs/product/`), under a fresh **delivery ticket**, and you ship it yourself as a
docs-only PR — `/acs:code` and `/acs:create-pr` are NOT involved. You orchestrate
planner/executor/verifier subagents; you never write the PRD content yourself.

## Start

MANDATORY first action. Pick the form by inspecting `$ARGUMENTS`:

- `$ARGUMENTS` contains a ticket id matching the repo prefix (e.g. `SHOP-1` — you are
  resuming an interrupted or handed-off delivery ticket):

  ```bash
  python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/skill-start.py" --skill create-prd --ticket <ticket-id>
  ```

- Otherwise (fresh PRD or amendment — every run gets a NEW delivery ticket):

  Before calling `skill-start.py --allocate`, detect whether this is an **amend** run
  by checking if `prd.md` already exists at the resolved `settings.prd_path` (default
  `docs/product/`). This mirrors the planner's amend definition (see Plan below).

  - **Amend mode with a usable `$ARGUMENTS` request**: pass a `--title` flag:

    ```bash
    python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/skill-start.py" \
      --skill create-prd --allocate \
      --title "Amend PRD: <≤~10-word summary of what changed>"
    ```

    A usable `$ARGUMENTS` request (clarification C-2): after stripping any leading
    delivery-ticket id (a token matching the repo prefix pattern, e.g. `MAR-51`),
    `$ARGUMENTS` contains free text describing what the amendment changes from which a
    short (about 10 words or fewer) summary can be formed. An `$ARGUMENTS` value that
    is empty, whitespace-only, or consists only of a ticket id is NOT usable — pass no
    `--title` and the built-in fallback applies. This is coordinator judgment, not
    parsing machinery; keep the free text of `$ARGUMENTS` as planner input (see below).

    The `--title` value MUST be prefixed `"Amend PRD: "` and MUST name what the
    amendment changes in at most ~10 words total (prefix included), derived from the
    free text of `$ARGUMENTS`. Example:
    `--title "Amend PRD: add org-level enforcement policy"`

  - **All other cases** (greenfield/brownfield — no `prd.md` at `prd_path` — or an
    amendment where `$ARGUMENTS` carries no usable request): pass no `--title`:

    ```bash
    python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/skill-start.py" --skill create-prd --allocate
    ```

  `--allocate` creates the delivery ticket (type `task`, built-in title
  `"Product definition (PRD)"` unless overridden by `--title`), its workspace
  partition, the `.lock`, the session pointer, and the `in_progress` run entry.

If skill-start exits non-zero: STOP and surface its stderr verbatim.

Parse the printed context JSON. Key fields: `partition`, `ticket_id`, `ticket`,
`settings` (`prd_path`, `formats`, `ticket_prefix`), `models` (per-role model/effort),
`reconcile`, `handoff_summary`, `design`, `pipeline`, `post_hook`.

If `settings.models.coordinator` is set, surface a one-line notice that it governs the
/acs:ship coordinator's own session — under /acs:ship this skill is invoked directly
in that session (no separate per-step agent for the key to apply to), and a directly
typed invocation runs in the user's session on the session's model. Never silently diverge.

Keep the free text of `$ARGUMENTS` (product notes, amendment request): it is planner
input.

## Resume & reconcile

If `context.reconcile` is true, verify recorded progress against reality BEFORE
continuing:

1. Re-read `<partition>/phases/create-prd/iter-*-*.xml` and
   `<partition>/create-prd-state.json` to see which phases completed.
2. Re-read `<repo>/<settings.prd_path>/prd.md` and `roadmap.md` — does their content
   match what the recorded executor results claim?
3. Check delivery progress: does the delivery branch exist
   (`git branch --list "<branch>"` / `git ls-remote --heads origin "<branch>"`)? Was a
   PR already opened (`gh pr list --head "<branch>" --json number,url`)?
4. Continue from the first unfinished phase. If verified docs already pass and the PR
   is open, skip straight to Finish with the recorded references.

If `context.handoff_summary` exists, read it (and
`<partition>/phases/create-prd/handoff-context.md` if present), do a light reconcile
of the same checks, and continue from where it points.

## Reflection loop

Plan -> execute -> verify, max 3 iterations. Spawn subagents with the Agent tool:
`subagent_type` `acs:create-prd-planner` / `acs:create-prd-executor` /
`acs:create-prd-verifier` (fall back to the un-namespaced name if the runtime rejects
the namespaced one). Apply `context.models.<role>.model` / `.effort` at spawn when not
`"inherit"`; if the runtime rejects the model/effort, FAIL the run with that error —
no silent fallback.

All messages follow `schemas/acs-messages.xsd`. Validate EVERY message you send and
receive:

```bash
echo "<task ...>...</task>" | python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/validate_xml.py" -
```

On an invalid message, re-request it once; if still invalid, fail the run with the
validation error recorded in `errors`. Persist every phase output to
`<partition>/phases/create-prd/iter-<n>-<phase>.xml` at the phase boundary BEFORE
starting the next phase. Decomposition is YOURS alone — subagents never spawn
subagents.

### Plan

The planner's first job is mode classification:

- **amend** — `<repo>/<settings.prd_path>/prd.md` already exists. Plan a surgical
  amendment: which sections change, which are preserved byte-for-byte.
- **brownfield** — no `prd.md`, but the repo contains real code. Plan to
  reverse-engineer a baseline PRD from the codebase and existing docs, listing the
  open points that need user confirmation.
- **greenfield** — empty/near-empty repo. Plan the elicitation: what to ask the user
  for vision, problem, personas, goals (+ measurable success metrics), prioritized
  features (MoSCoW), product NFRs, constraints, out-of-scope.

Example task (fill real values; `<context>` carries `$ARGUMENTS` and, on iteration
2+, the verifier findings to fix):

```xml
<task skill="create-prd" phase="plan" ticket-id="SHOP-1" iteration="1">
  <objective>Classify mode (greenfield/brownfield/amend); produce the prd.md and roadmap.md outline, the elicitation or reverse-engineering plan, and the open questions for the user.</objective>
  <inputs>
    <file>/abs/workspace/acme-shop/SHOP-1/ticket.json</file>
    <file>/abs/repo/docs/product/prd.md</file>
    <file>/abs/repo/README.md</file>
  </inputs>
  <constraints>
    <constraint name="prd_path">docs/product</constraint>
    <constraint name="required_sections">Vision; Problem statement; Target users &amp; personas; Goals &amp; success metrics; Features (prioritized); Non-functional requirements; Constraints &amp; assumptions; Out of scope</constraint>
    <constraint name="amend_rule">amendments preserve untouched sections exactly</constraint>
  </constraints>
  <context>User notes from $ARGUMENTS; prior findings on iteration 2+.</context>
</task>
```

The planner returns a `<result>` with the outline in `<outputs>`-referenced files or
inline context, and open points in `<questions>`. Resolve those questions with the
user (see User interaction) BEFORE spawning the executor, and pass the answers in the
executor task's `<context>`.

### Execute

Prepare the delivery branch before the first execute (deterministic plumbing — you do
it, not the executor):

```bash
DEFAULT_BRANCH=$(gh repo view --json defaultBranchRef -q .defaultBranchRef.name)
git fetch origin "$DEFAULT_BRANCH" && git checkout -b "<branch>" "origin/$DEFAULT_BRANCH"
```

`<branch>` renders `settings.formats.branch_name` (default
`{type}/{ticket_id}-{slug}`) with `ticket_id` = delivery ticket id, `type` = `task`,
`slug` = slugified ticket title — e.g. `task/MAR-51-amend-prd-add-org-enforcement-policy`. On a
fresh repo with no remote default branch yet, `git checkout -b "<branch>"` from the
current HEAD instead. If checkout fails (conflicting local changes), surface the git
error and ask the user. Iterations 2-3 stay on the branch.

Spawn the executor (`phase="execute"`) with the approved outline, the user's answers,
and the mode. The executor — the only role that mutates the repo — writes:

- `<settings.prd_path>/prd.md` with EXACTLY these sections: **Vision**,
  **Problem statement**, **Target users & personas**, **Goals & success metrics**,
  **Features (prioritized)** (MoSCoW: Must/Should/Could/Won't, each feature traced to
  the goal(s) it serves), **Non-functional requirements**,
  **Constraints & assumptions**, **Out of scope**.
- `<settings.prd_path>/roadmap.md` — milestones/phases mapped to intended epics, each
  milestone listing the PRD features it delivers.
- In amend mode: edit `prd.md` in place, preserving untouched sections exactly
  (verify with `git diff -- <settings.prd_path>`); update `roadmap.md` only where the
  amendment changes it.

Typically ONE executor — `prd.md` and `roadmap.md` are tightly coupled. You MAY run
two executors in parallel only when their outputs cannot conflict (e.g. iteration-2
fixes confined to disjoint files); the verifier always runs after all executors
finish and judges the combined result.

### Verify

Spawn the verifier (`phase="verify"`) with ONLY artifact references (the two files,
the ticket, the git diff) — never the executor's reasoning. It re-reads everything
fresh and checks, all findings blocking:

- all eight required `prd.md` sections present and non-empty, plus `roadmap.md`;
- every feature traces to at least one goal; no orphan features, no goal without a
  feature or an explicit deferral;
- every goal has at least one **measurable** success metric (value + unit +
  timeframe; "improve UX" fails);
- nothing in features, NFRs, or roadmap contradicts the stated constraints or the
  out-of-scope list;
- roadmap milestones map to intended epics and cover all Must-have features;
- amend mode: `git diff` shows only the intended sections changed.

Zero findings = pass -> Deliver. Findings -> persist the verify XML, feed the
findings into the next plan/execute iteration. After iteration 3 with findings
remaining: STOP — final status `failed`, findings recorded; go to Finish (no PR is
opened).

## Deliver the docs-only PR

Only after the verifier passes:

```bash
git add "<settings.prd_path>/prd.md" "<settings.prd_path>/roadmap.md"
git commit -m "<rendered formats.commit_message>"      # default {ticket_id} {summary}, e.g. "SHOP-1 Add product requirements document and roadmap"
git push -u origin "<branch>"
gh label create ACS 2>/dev/null || true                # create the label if missing
gh pr create --base "$DEFAULT_BRANCH" --head "<branch>" \
  --title "<rendered formats.pr_title>" \
  --body-file "<partition>/phases/create-prd/pr-body.md" \
  --label ACS
gh pr view "<branch>" --json number,url
```

- PR title renders `settings.formats.pr_title` (default `[{ticket_id}] {title}`),
  e.g. `[MAR-51] Amend PRD: add org-level enforcement policy`.
- PR body: resolve `settings.formats.pr_description_template` (default
  `pr-default` -> `${CLAUDE_PLUGIN_ROOT}/templates/pr-default.md`; a custom name ->
  `<repo>/.acs/templates/<name>.md`; else an absolute path). Fill `{ticket_id}`,
  `{type}`, `{title}`, `{summary}`, `{external_key}` from `ticket.json` and this
  run's state — never from conversation memory. Changes = the PRD files added or
  amended; Test plan = the verifier dimensions checked; mark TDD/coverage checklist
  items `N/A (docs-only PR)`. Write the filled body to
  `<partition>/phases/create-prd/pr-body.md` before `gh pr create`.
- Record the PR number, URL, and branch for the result document.

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
`clarify.py add --skill create-prd --question "..." --answer "..." --ticket <ticket-id>`
BEFORE acting on it, and pass the relevant `C-n` entries to subagents in
`<context>`. If the user is unavailable or says "you decide": record the
decision with `--source assumption --rationale "..."` — assumptions surface
in the completion report's Findings and the PR body until a user confirms.
Before a needs_input handoff, record the outgoing questions as `open`
(`clarify.py add` without `--answer`).

- **Greenfield**: elicit the definition from the user — vision, problem, personas,
  goals with measurable success metrics, prioritized features (MoSCoW), product NFRs,
  constraints, out-of-scope. Batch questions (AskUserQuestion or plain questions);
  when `$ARGUMENTS` already carries notes, propose drafts to confirm instead of
  interrogating from zero.
- **Brownfield**: present the reverse-engineered baseline and ask ONLY the open
  points the planner flagged.
- **Amend**: confirm exactly which sections change and why before executing.
- Ask only when genuinely ambiguous; never invent product facts. If you
  genuinely cannot reach the user (e.g. a non-interactive run), return a
  `<handoff skill="create-prd" ticket-id="<id>" status="needs_input">` with
  `<questions>` instead of guessing.

## Context pressure

If your context is running low mid-run: flush in-flight work and soft context (user
answers, decisions, partial findings, gotchas) to
`<partition>/phases/create-prd/handoff-context.md`, then run

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/handoff.py" --ticket <ticket-id> --summary "<done / in-flight / next / decisions>"
```

and tell the user the printed `continue_with` command. Never burn the last of the
context on work that would be lost.

## Finish

MANDATORY final step — never skipped, also on failure.

1. Write `<partition>/phases/create-prd/result.json` per the result-document contract
   (INTERNALS.md), with the canonical `states` keys for create-prd — `prd` and `pr`,
   exact names:

   ```json
   {
     "status": "completed",
     "stop_reason": "PRD created and docs-only PR opened",
     "states": {
       "prd": {"path": "docs/product", "files": ["docs/product/prd.md", "docs/product/roadmap.md"]},
       "pr": {"number": 12, "url": "https://github.com/acme/shop/pull/12", "branch": "task/MAR-51-amend-prd-add-org-enforcement-policy"}
     },
     "findings": [],
     "errors": [],
     "tokens": {"input": 84000, "output": 21000},
     "cost_usd": 0.61
   }
   ```

   Estimate `tokens`/`cost_usd` for this run (all subagents + coordinator). On
   failure keep whatever is true: status `failed`, remaining verifier findings in
   `findings`, `states.prd` if the files were written, NO `states.pr` if no PR was
   opened, and the reason in `stop_reason`.

2. Run the post-hook:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/post-create-prd.py" --ticket <ticket-id> --result-file "<partition>/phases/create-prd/result.json"
   ```

   It finalizes the run entry, updates `pipeline-state.json` / `tickets-index.json` /
   `metrics.json`, flips the delivery ticket to `in_review` (PR recorded), and
   releases the `.lock`.

3. Report a compact summary to the user: delivery ticket id, mode
   (greenfield/brownfield/amend), files written, PR URL — and tell them to review the
   PR themselves, then run `/acs:merge-pr <delivery-ticket-id>` to land it.
   `/acs:create-architecture` is unblocked once the PRD exists. Under /acs:ship,
   return ONLY the `<handoff>` XML as your final message: status, summary <=1KB,
   artifact refs, next-step.

## Completion report (normative)

Every terminal outcome of a direct invocation — completed, failed,
interrupted, or handed off — ends your final message with the standard block
(INTERNALS.md "Completion report"), rendered only AFTER the post-hook
succeeded. Same labels, same order, `none` where empty; under /acs:ship your final message is the `<handoff>` XML instead — this report is for direct invocations:

```markdown
## /acs:create-prd · <ticket-id> · <status>

- **Ticket**: <id> — <title> (<type>)
- **Status**: <status> — <stop_reason>
- **Results**: PRD files written/amended at `prd_path` (`prd.md`, `roadmap.md`); delivery ticket id; PR number/URL
- **Findings**: <open findings / clarifications, or "none">
- **Artifacts**: <partition files, repo paths, branch, PR URL>
- **Metrics**: iterations <n>/3 · <wall time> · ~<tokens in/out> · ~$<cost_usd>
- **Next**: `/acs:merge-pr <ticket-id>` after reviewing the docs PR; then `/acs:create-architecture`
```
