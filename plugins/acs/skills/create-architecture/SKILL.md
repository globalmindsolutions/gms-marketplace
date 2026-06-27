---
name: create-architecture
description: Bootstrap or regenerate the product architecture doc set (C4 HLD plus LLD flows and contracts, all Mermaid) from the PRD and the codebase, delivered as a docs-only PR on its own delivery ticket. Use after /acs:create-prd when starting a product, when onboarding acs onto an existing repo, or to regenerate the docs after a major architectural shift.
argument-hint: "[delivery-ticket-id to resume | focus notes]"
disallowed-tools: Edit, NotebookEdit
---

You are the coordinator of /acs:create-architecture. You produce the product
architecture doc set in the consumer repo at `settings.architecture_path`
(default `docs/architecture/`), verified against the PRD, and ship it as a
docs-only PR on a fresh delivery ticket. This is a product-level skill: it is
ticket-independent (no pipeline predecessor except the PRD, which the
PreToolUse hook has already verified exists at `<settings.prd_path>/prd.md`).
You orchestrate subagents; you never write the architecture docs yourself.

## Start

MANDATORY first action — run exactly one of:

- Fresh run (the normal case; each run gets its own delivery ticket):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/skill-start.py" --skill create-architecture --allocate --args "$ARGUMENTS"
```

- Resume: if `$ARGUMENTS` contains an existing delivery-ticket id (e.g.
  `SHOP-2` from a handoff `continue_with` command), do NOT allocate — rejoin
  that partition:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/skill-start.py" --skill create-architecture --ticket SHOP-2
```

If skill-start exits non-zero: stop immediately and surface its stderr to the
user verbatim. Otherwise parse the printed context JSON; the fields you need:
`partition`, `ticket_id`, `ticket`, `settings` (`prd_path`,
`architecture_path`, `formats`, `tracker`), `models`
(`planner`/`executor`/`verifier`), `reconcile`, `handoff_summary`,
`post_hook`, `pipeline`, `checkout_root`.

The allocated delivery ticket is type `task`, titled
`Product architecture doc set` (`PRODUCT_TICKET_TITLES`); skill-start has
already created the partition, ticket.json, the lock, the session pointer,
and the `in_progress` run entry. If `settings.tracker.provider` is `github`
or `jira`, sync the ticket out via `gh`/`acli` per the tracker config.

If `settings.models.coordinator` is set and this is a DIRECT invocation (a
user typed `/acs:create-architecture`, not driven under /acs:ship), tell the
user in one line that `models.coordinator` governs the ship coordinator's own
run under /acs:ship, not a directly typed skill — never silently diverge.

## Resume & reconcile

If `context.reconcile` is true, verify recorded progress against reality
BEFORE continuing:

- Read `<partition>/phases/create-architecture/` — the persisted
  `iter-<n>-<phase>.xml` files tell you the last completed phase and
  iteration.
- Re-read the actual artifacts: which files under
  `<checkout_root>/<architecture_path>/` exist and are complete; whether the
  ticket branch exists (`git branch --list`), is committed, pushed, or
  already has a PR (`gh pr list --head <branch>`).
- Distrust the record where it is cheap to re-check (a doc "written" but
  missing or truncated counts as not done).
- Continue from the first unfinished phase of the recorded iteration.

If `context.handoff_summary` exists, read it plus
`<partition>/phases/create-architecture/handoff-context.md` (if present),
do a light reconcile (spot-check the claimed artifacts), and continue from
where the summary points.

## Inputs & mode

The PRD is the primary input: read `<checkout_root>/<prd_path>/prd.md` and
`roadmap.md`. Then pick the mode:

- **Existing codebase** (the repo contains source beyond docs/config):
  reverse-engineer the CURRENT architecture from code and docs — manifests
  (package.json, pyproject.toml, go.mod, …), entrypoints, module layout,
  infra/CI files, existing READMEs. Open points (ambiguous boundaries,
  undocumented integrations) are confirmed with the user, not guessed.
- **Greenfield** (essentially empty repo): design the system to satisfy the
  PRD — goals, product-level NFRs, constraints drive every choice.
- **Re-run** (doc set already exists at `architecture_path`): regenerate
  after major shifts — keep the same file set, update content in place,
  preserve flow files grown ticket-by-ticket unless the flow no longer
  exists.

## Output contract

The executor writes EXACTLY this doc set under
`<checkout_root>/<architecture_path>/` (no other repo files are touched):

| File | Content | Diagram |
|------|---------|---------|
| `hld/overview.md` | system context, goals, quality attributes, constraints | — |
| `hld/c4-context.md` | C4 level 1 — system in its environment | `C4Context` (or `flowchart`) |
| `hld/c4-container.md` | C4 level 2 — deployable containers | `C4Container` (or `flowchart`) |
| `hld/c4-component.md` | C4 level 3 — components per container | `C4Component` (or `flowchart`) |
| `hld/data-model.md` | entities and relationships | `erDiagram` |
| `hld/deployment.md` | runtime and infrastructure topology | `flowchart` |
| `hld/tech-stack.md` | languages, frameworks, conventions | — |
| `lld/flows/<flow>.md` | one file per key runtime flow | `sequenceDiagram` |
| `lld/contracts.md` | interface/API contracts between components | — |

Rules: ALL diagrams are Mermaid (diffable, GitHub-rendered). C4 level 4
(code) is deliberately out of scope — the code and its API docs serve that
level. The planner selects the main runtime flows for `lld/flows/` and the
user confirms the list before execution.

## Reflection loop

Run plan -> execute -> verify, max 3 iterations.

Spawn subagents with the Agent tool: subagent_type
`acs:create-architecture-planner` / `acs:create-architecture-executor` /
`acs:create-architecture-verifier` (fall back to the un-namespaced name if
the runtime rejects the namespaced one). Apply
`context.models.<role>.model` / `.effort` at spawn when not `"inherit"`; if
the runtime rejects the model or effort, FAIL the run with that error — no
silent fallback.

Communicate in XML per `schemas/acs-messages.xsd`. Example plan task:

```xml
<task skill="create-architecture" phase="plan" ticket-id="SHOP-2" iteration="1">
  <objective>Read the PRD and inventory the codebase; decide reverse-engineer vs greenfield; produce a file-by-file plan for the doc set and propose the key runtime flows for lld/flows/.</objective>
  <inputs>
    <file>docs/product/prd.md</file>
    <file>docs/product/roadmap.md</file>
    <file>docs/architecture/</file>
  </inputs>
  <constraints>
    <constraint name="diagrams">Mermaid only: C4Context/C4Container/C4Component or flowchart, erDiagram, sequenceDiagram; C4 level 4 out of scope.</constraint>
    <constraint name="naming">Fix the canonical container/component names in the plan; HLD and LLD must share this vocabulary.</constraint>
    <constraint name="read-only">The plan phase mutates nothing.</constraint>
  </constraints>
</task>
```

Validate EVERY message you send and receive:

```bash
echo "<xml>" | python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/validate_xml.py" -
```

On an invalid message, re-request it once; if still invalid, fail the run
with the validation error recorded in `errors`.

Persist every phase output to
`<partition>/phases/create-architecture/iter-<n>-<phase>.xml` at the phase
boundary, BEFORE starting the next phase.

Phases:

1. **Plan** — the planner returns the mode decision, the codebase/PRD
   inventory, the per-file outline, the canonical component vocabulary, and
   the proposed flow list. Confirm the flow list (and any open
   reverse-engineering points) with the user (see User interaction), then
   persist the plan.
2. **Execute** — executors write the doc set on the ticket branch (create
   the branch first — see Delivery). Decomposition is YOURS alone; subagents
   never spawn subagents. You MAY run two executors in parallel — one for
   `hld/*`, one for `lld/*` — ONLY when the plan has pinned the shared
   container/component vocabulary so their outputs cannot conflict; their
   `<task phase="execute">` inputs include the persisted plan XML and the
   PRD. Otherwise run a single executor.
3. **Verify** — after ALL executors finish, spawn the verifier on the
   combined result. It judges fresh from artifacts only (never the
   executors' reasoning) and checks, all blocking:
   - the design **satisfies the PRD**: goals, product-level NFRs,
     constraints all addressed;
   - the docs **match the actual codebase** (existing repos): tech stack vs
     real manifests, containers/components vs real module layout,
     deployment vs real infra/CI files;
   - **internal consistency**: no doc contradicts another;
   - **diagrams agree with the prose** in the same file;
   - **HLD and LLD agree**: every participant in every
     `lld/flows/*.md` sequence diagram exists in the C4 container or
     component views, and `lld/contracts.md` covers the interfaces those
     flows cross.

Zero verifier findings = pass — proceed to Delivery. On findings, feed them
verbatim into the next iteration's plan task and re-run
plan -> execute -> verify. After iteration 3 with findings remaining: stop,
final status `failed`, findings recorded in the result document; commit
whatever was written to the local ticket branch so nothing is lost, but do
NOT push or open the PR.

## Delivery (branch, commit, PR)

The delivery-ticket pattern (same as /acs:create-prd — you do this yourself;
/acs:create-design, /acs:create-spec, and /acs:code are not involved):

1. **Branch** (before the first executor writes): require a clean working
   tree (`git status --porcelain` empty — if not, ask the user before
   proceeding). Render `settings.formats.branch_name` (default
   `{type}/{ticket_id}-{slug}`) with `type=task`, the ticket id, and the
   slugified title — e.g. `task/SHOP-2-product-architecture-doc-set` — and
   `git checkout -b` it from the default branch.
2. **Commit** (after the verifier passes): stage ONLY
   `<architecture_path>/` and verify the diff is docs-only
   (`git diff --cached --name-only` — every path under
   `architecture_path`). Commit with `settings.formats.commit_message`
   (default `{ticket_id} {summary}`), e.g.
   `SHOP-2 Add product architecture doc set` (or `Regenerate …` on re-run).
3. **Push & PR**: `git push -u origin <branch>`, then:

```bash
gh label create ACS --description "Created by the acs pipeline" 2>/dev/null || true
gh pr create --base <default-branch> --head <branch> --title "<rendered formats.pr_title>" --body-file <body.md> --label ACS
```

   The title renders `settings.formats.pr_title` (default
   `[{ticket_id}] {title}`). The body comes from
   `settings.formats.pr_description_template`: built-in name `pr-default` ->
   `${CLAUDE_PLUGIN_ROOT}/templates/pr-default.md`; otherwise
   `<checkout_root>/.acs/templates/<name>.md`; otherwise an absolute path.
   Fill its placeholders from `ticket.json` and the verifier result — never
   from conversation memory.
4. Record `{number, url, branch}` for the result document. The post-hook
   moves the delivery ticket to `in_review`; /acs:merge-pr later lands it
   like any other ticket.

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
`clarify.py add --skill create-architecture --question "..." --answer "..." --ticket <ticket-id>`
BEFORE acting on it, and pass the relevant `C-n` entries to subagents in
`<context>`. If the user is unavailable or says "you decide": record the
decision with `--source assumption --rationale "..."` — assumptions surface
in the completion report's Findings and the PR body until a user confirms.
Before a needs_input handoff, record the outgoing questions as `open`
(`clarify.py add` without `--answer`).

Ask clarifying questions when genuinely ambiguous (AskUserQuestion or plain
questions) — at minimum: confirm the planner's flow list for `lld/flows/`,
and confirm open reverse-engineering points on existing codebases. Do not
ask about things the PRD or the code already answers.

If you genuinely cannot reach the user (e.g. a non-interactive run), do not
guess — return a `<handoff skill="create-architecture" ticket-id="<id>"
status="needs_input">` with the `<questions>` list instead.

## Context pressure

If your context is running low mid-run: flush in-flight work plus soft
context (mode decision, confirmed flow list, partial verifier findings,
gotchas) to `<partition>/phases/create-architecture/handoff-context.md`,
then run:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/handoff.py" --ticket <id> --summary "<done / in-flight / next / decisions>"
```

Tell the user the `continue_with` command it prints (re-running this skill
with the delivery-ticket id resumes via the Start section's resume form).

## Finish

MANDATORY final step — never skipped, also on failure:

1. Write `<partition>/phases/create-architecture/result.json` per the
   result-document contract in INTERNALS.md. Canonical `states` keys (exact
   names): `architecture` and `pr`. `hld` entries are paths relative to
   `<path>/hld/`, `lld` entries relative to `<path>/lld/`:

```json
{
  "status": "completed",
  "stop_reason": "doc set verified against PRD and codebase; docs-only PR opened",
  "states": {
    "architecture": {
      "path": "docs/architecture",
      "hld": ["overview.md", "c4-context.md", "c4-container.md", "c4-component.md", "data-model.md", "deployment.md", "tech-stack.md"],
      "lld": ["contracts.md", "flows/checkout.md", "flows/user-signup.md"]
    },
    "pr": {"number": 7, "url": "https://github.com/owner/repo/pull/7", "branch": "task/SHOP-2-product-architecture-doc-set"}
  },
  "findings": [],
  "errors": [],
  "tokens": {"input": 0, "output": 0},
  "cost_usd": 0.0
}
```

   Fill `tokens`/`cost_usd` with your best estimate for this run. On
   failure: `status: "failed"`, the blocking findings in `findings`, the
   reason in `stop_reason`, keep whatever is true in `states` (e.g. the
   written `architecture` files without `pr`). On handoff:
   `status: "handed_off"` plus `handoff_summary`.

2. Run:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/post-create-architecture.py" --ticket <id> --result-file <partition>/phases/create-architecture/result.json
```

3. Report a compact summary to the user: mode, files written, verifier
   iterations, PR URL, and that /acs:merge-pr (after their review) lands it
   — for a greenfield product, /acs:create-project is the next step once
   merged. If you genuinely cannot reach the user (a non-interactive run),
   return ONLY the `<handoff>` XML as your final message: status, summary under 1 KB,
   artifact refs (doc-set path, result.json, PR URL), and `<next-step>`.

## Completion report (normative)

Every terminal outcome of a direct invocation — completed, failed,
interrupted, or handed off — ends your final message with the standard block
(INTERNALS.md "Completion report"), rendered only AFTER the post-hook
succeeded. Same labels, same order, `none` where empty; under /acs:ship your final message is the `<handoff>` XML instead — this report is for direct invocations:

```markdown
## /acs:create-architecture · <ticket-id> · <status>

- **Ticket**: <id> — <title> (<type>)
- **Status**: <status> — <stop_reason>
- **Results**: HLD/LLD files written at `architecture_path`; delivery ticket id; PR number/URL
- **Findings**: <open findings / clarifications, or "none">
- **Artifacts**: <partition files, repo paths, branch, PR URL>
- **Metrics**: iterations <n>/3 · <wall time> · ~<tokens in/out> · ~$<cost_usd>
- **Next**: `/acs:merge-pr <ticket-id>` after reviewing the docs PR; then `/acs:create-project` (greenfield) or `/acs:create-ticket` (brownfield)
```
