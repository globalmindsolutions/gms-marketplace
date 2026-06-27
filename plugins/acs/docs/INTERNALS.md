# acs plugin internals — the implementation contract

This document is the binding contract between the plugin's moving parts: skills
(SKILL.md), subagents (agents/), hooks (hooks/), schemas, and templates. The
business requirements live in the repo's `docs/` folder; this file records how
they map onto the Claude Code plugin API and the exact conventions every
component follows.

## Component map

| Piece | Where | Count |
|-------|-------|-------|
| Marketplace manifest | `.claude-plugin/marketplace.json` (repo root) | 1 |
| Plugin manifest | `plugins/acs/.claude-plugin/plugin.json` | 1 |
| Skills | `plugins/acs/skills/<name>/SKILL.md` | 13 |
| Subagents | `plugins/acs/agents/<skill>-<role>.md` | 27 (9 skills x planner/executor/verifier) |
| Hooks | `plugins/acs/hooks/hooks.json` + `hooks/scripts/` | dispatcher + 9 pre + 9 post |
| Helper CLIs | `hooks/scripts/{skill-start,new-ticket,handoff,validate_xml}.py` | 4 |
| Status lines (opt-in) | `hooks/scripts/statusline.py` (prompt line: ticket + pipeline glyphs + cost) and `hooks/scripts/subagent-statusline.py` (agent-panel rows for reflection subagents) — offered by /init Step 7b; `statusLine`/`subagentStatusLine` stay user-owned settings, never forced. A plugin-root `settings.json` default was deliberately NOT shipped: `${CLAUDE_PLUGIN_ROOT}` expansion there is unverified, and a silently broken default is worse than an explicit opt-in. | 2 |
| JSON Schemas | `plugins/acs/schemas/*.schema.json` | 8 |
| XML schema | `plugins/acs/schemas/acs-messages.xsd` | 1 |
| Description templates | `plugins/acs/templates/*.md` | 4 |

Skills are invoked namespaced: `/acs:init`, `/acs:ship`, `/acs:create-ticket`, …
(The requirements docs write `/init`, `/ship`, … — same skills, plugin-namespaced
by Claude Code.)

## Hook event binding (resolves the open question in docs/requirements/hooks.md)

Claude Code has no "skill completed" hook event, so the pre/post contract maps
onto the plugin hooks API like this:

1. **Pre-hooks — deterministic, enforced.** `hooks.json` registers a
   `PreToolUse` hook matching the `Skill` tool. `dispatch.py pre` extracts the
   skill name from the tool input (handling the `acs:` namespace), no-ops
   (exit 0) for anything that is not one of the nine hooked skills, and
   otherwise runs the named `pre-<skill>.py` with the same stdin payload.
   Exit 2 blocks the skill before any of its instructions run; stderr tells the
   user which skill to run first. This fires for user-typed slash commands and
   model-initiated Skill calls alike — including the step skills `/ship` invokes
   directly.
2. **Post-hooks — coordinator-invoked, gate-backed.** `post-<skill>.py` is the
   skill's mandatory final step (each SKILL.md ends with it). It must be a
   script the coordinator calls because its inputs — final status, stop reason,
   findings, token/cost usage — exist only in the coordinator's context. The
   pipeline does not depend on the model's goodwill: skill-start has already
   appended an `in_progress` run entry, and every downstream pre-hook gates on
   `runs[-1].status == "completed"`, so a skipped post-hook leaves the gate
   closed, never open.
3. **SessionEnd safety net.** `dispatch.py session-end` finalizes any run this
   checkout left `in_progress` as `interrupted` (and releases the lock), so
   abnormal endings still write state. A hard kill that skips even SessionEnd
   still leaves `in_progress` + a stale lock — downstream gates read "not
   completed" and the next run reconciles.

## Skill lifecycle (every hooked skill)

Every workflow and product-level SKILL.md follows this exact lifecycle:

```
(PreToolUse fired pre-<skill>.py — already passed or we wouldn't be running)
1. skill-start.py  --skill <skill> [--ticket|--args|--allocate ...]   # FIRST action
     -> context JSON: settings, partition, ticket, reconcile/handoff info,
        per-role models, design source, post_hook path
2. if context.reconcile: reconcile recorded state against reality before continuing
   if context.handoff_summary: read it, light-verify, continue from where it points
3. Reflection loop (max 3 iterations):
     plan    -> spawn <skill>-planner   (XML <task phase="plan">,   returns <result>)
     execute -> spawn <skill>-executor(s) (XML <task phase="execute">; parallel executors
                allowed when outputs cannot conflict; decomposition is coordinator-only)
     verify  -> spawn <skill>-verifier  (XML <task phase="verify">,  returns <result> with findings)
     - every subagent WRITES ITS OWN PHASE ARTIFACT (see below) and references it
       in <outputs>; the XML stays compact
     - the coordinator persists EVERY raw XML message to
       <partition>/phases/<skill>/iter-<n>-<phase>.xml at the phase boundary,
       before starting the next phase
     - validate every XML message:  validate_xml.py <file>   (or pipe with `-`)
       For Python callers that need to validate multiple messages without a
       subprocess per message, use the batch API:
           from validate_xml import validate_batch, batch_overall_ok
           results = validate_batch([msg1, msg2, ...])   # list of (ok, errors) tuples
           if not batch_overall_ok(results): ...         # False if any member invalid
       validate_batch() calls the in-process validate_structurally() engine in a
       plain loop — zero subprocess, zero third-party dependency.
     - verifier findings == 0 -> done; findings > 0 -> feed findings into next iteration
     - iteration 3 still failing -> stop; final status "failed", findings recorded
4. Write the result document <partition>/phases/<skill>/result.json
5. python3 <post_hook> --result-file <result.json>                    # MANDATORY final step
```

### Phase artifacts (written by the subagents themselves)

Subagents persist their full work products into the partition — the XML result
carries references, never the bodies (docs/requirements/reflection.md: subagents write their states,
findings, error details, and stop reasons into workspace files):

| Phase | Artifact (under `<partition>/phases/<skill>/`) | Written by | Contents |
|-------|------------------------------------------------|------------|----------|
| plan | `iter-<n>-plan.md` | planner | the complete plan: analysis, task breakdown (executor tasks + inputs), files/areas touched, risks, what the verifier must check |
| execute | `iter-<n>-execute.json` (parallel executors: `iter-<n>-execute-<k>.json`) | executor | artifacts produced, repo files changed, commands/tests run with outcomes, problems hit, clarifications used |
| verify | `iter-<n>-verify.md` | verifier | the full verification report: every check performed with its evidence, every finding in detail (the XML `<finding>` entries summarize this file) |

**Every statement in a phase artifact must be grounded**: decisions and
analysis cite the file (path + line/section) they are based on; claims about
behavior quote the command run and its relevant output; anything unverifiable
is marked as an assumption for the coordinator to resolve. Each agent body
carries the binding "Grounding (anti-hallucination)" section; ungrounded
plans/reports are a verification finding.

The coordinator's `iter-<n>-<phase>.xml` snapshots plus these artifacts are
what reconcile mode reads on resume — a crash can lose at most the in-flight
phase. Phase persistence + the `in_progress` run entry give the three resume
levels: between steps (gates), within /ship (ledger), and mid-skill
(reconcile mode).

### Why not Claude Code's native plan mode

The reflection plan phase deliberately does NOT use plan mode
(`EnterPlanMode`/`ExitPlanMode`): plan mode's contract is *interactive user
approval*, but planners run as spawned subagents (no user to approve; under
`/ship` the whole step is headless — that is what the `needs_input` handoff is
for), plugin agents cannot set `permissionMode`, and resumability comes from
the phase artifacts + gates, not from plan-mode state. The planner's
read-only discipline is enforced by its tool allowlist and charter instead
(Write is permitted solely for its own `phases/<skill>/` artifacts). A user
may still wrap a *direct* skill invocation in plan mode for pre-approval —
that is orthogonal to the pipeline and changes nothing in this contract.

### Completion report (user-facing, every skill, every terminal status)

On a **direct invocation**, the coordinator's final message always ends with
this exact block — same labels, same order, rendered AFTER the post-hook has
succeeded (so what the user reads is what was persisted). Labels never
disappear: an empty one reads `none`. Under `/acs:ship` the step's final
message is the `<handoff>` XML instead; `/ship` itself renders this report at
pipeline end.

```markdown
## /acs:<skill> · <ticket-id> · <status>

- **Ticket**: <id> — <title> (<type>)
- **Status**: <completed|failed|interrupted|handed_off> — <stop_reason>
- **Results**: <the skill's canonical states keys, as short bullets>
- **Findings**: <open findings / clarifications obtained, or "none">
- **Artifacts**: <what was written where: partition files, repo paths, branch, PR URL>
- **Metrics**: iterations <n>/3 · <wall time> · ~<tokens in/out> · ~$<cost_usd>
- **Next**: <exact command(s), e.g. `/acs:create-pr SHOP-123`, or what unblocks>
```

Three sanctioned substitutions: `/acs:init` and `/acs:update` (no ticket)
replace the Ticket line with **Scope**, and `/acs:handoff` puts the
`continue_with` command in **Next**. Per-skill Results/Next content is fixed
in each SKILL.md's "Completion report" section.

### The result document (input to post-<skill>.py)

```json
{
  "status": "completed | failed | interrupted | handed_off",
  "stop_reason": "one line: why the run ended",
  "states":   { "<skill-specific result data for the next skill>": "..." },
  "findings": [ {"severity": "blocking|info", "dimension": "...", "detail": "..."} ],
  "errors":   [ "..." ],
  "tokens":   {"input": 0, "output": 0},
  "cost_usd": 0.0,
  "handoff_summary": "only when status=handed_off"
}
```

`post-<skill>.py` finalizes `runs[-1]`, merges `states` (replaces `findings` /
`errors` when present), updates `pipeline-state.json`, `tickets-index.json`,
`metrics.json`, releases the `.lock`, and performs per-skill extras
(create-pr → ticket `in_review` + prs.created; merge-pr → ticket `done`,
epic auto-done check, partition archived to `archive/<ticket-id>/`).

### Canonical `states` keys per skill

The next skill reads these — keep the names exact:

| Skill | Required `states` keys on success |
|-------|-----------------------------------|
| create-prd | `prd` `{path, files:[...]}`, `pr` `{number, url, branch}` |
| create-architecture | `architecture` `{path, hld:[...], lld:[...]}`, `pr` `{...}` |
| create-project | `scaffold` `{build, lint, tests, coverage_tooling: true/false}`, `pr` `{...}` |
| create-ticket | `ticket_id`, `type`, `needs_design`, `children: [ids]`, `prd_trace` `{feature, divergence}` |
| create-design | `design_path` (partition-relative `design.md`), `decision` (one line) |
| create-spec | `specs: ["01-…", …]` (basenames in `specs/`), `design_conformance: true/null` |
| code | `verifier_passed: true/false` (the /create-pr gate), `branch`, `specs_implemented: [...]`, `tests` `{passed, failed, coverage_percent, coverage_target}`, `docs_updated: [paths]`, `review` `{iterations, findings_open}` |
| create-pr | `pr` `{number, url, branch, base}` (the /merge-pr gate) |
| merge-pr | `merged: true/false`, `merge_strategy`, `readiness` `{ci, approvals, conflicts, protections}` |

On failure, keep whatever is true (e.g. `/code` coverage hard-fail records
`verifier_passed: false`, achieved coverage, and the reason in `stop_reason`).

The exempt non-ticket merge path (`/acs:merge-pr --pr <n>`) has **no** result
document and writes **none** of the merge-pr ticket states above — there is no
partition. It bumps only the repo-level `pr_merged` metric via
`post-merge-pr.py --pr <n>` and touches no ticket index, pipeline, or archive.

## XML messaging

All coordinator <-> subagent communication uses the three message shapes in
`schemas/acs-messages.xsd` (`task`, `result`, `handoff`). Rules:

- The coordinator validates every message it sends and receives
  (`validate_xml.py`); a malformed message is re-requested once, then the run
  fails with the validation error in `errors`.
- Subagents receive the `<task>` inside their prompt and must return the
  `<result>` as the final content of their reply — nothing after it.
- `<handoff>` is only for step-coordinator -> /ship returns: compact (~1 KB),
  references workspace files instead of inlining detail.
- Subagents never spawn sub-subagents; parallel executors are the
  coordinator's call; the verifier runs after all executors complete.

## Subagents

27 agents named `<skill>-<role>` in `plugins/acs/agents/`. Conventions:

- Frontmatter: `name`, `description` (when the coordinator spawns it), and
  `model: inherit` — the *actual* model/effort comes from `settings.json`
  (`models.<role>`, `models.overrides.<skill>.<role>`), resolved by
  skill-start into `context.models` and applied by the coordinator at spawn
  time. An unknown model id or unsupported effort fails at spawn — surface the
  error, never silently fall back.
- Planners and verifiers are read-only with ONE exception: each writes its
  own phase artifact under `<partition>/phases/<skill>/` (plan file /
  verification report — see Phase artifacts above). Only executors mutate
  real targets (the repo for /code and the product-level skills, the
  workspace artifacts — specs, design.md — for the rest), and they record
  what they changed in their execute report. The verifier must judge fresh —
  it never sees the executor's reasoning, only artifacts.
- Verifiers re-run the actual checks (tests, coverage, builds, doc diffs) —
  trust nothing recorded that they can cheaply re-verify.

## Workspace layout (normative example)

```
<workspace>/<repo-id>/                  # repo-id from git remote: owner-name
  tickets-index.json  counters.json  metrics.json
  sessions/<checkout-id>.json           # per-worktree current-ticket pointer
  archive/<ticket-id>/                  # moved here by post-merge-pr
  <ticket-id>/
    .lock  ticket.json  pipeline-state.json
    design.md  specs/NN-slug.md
    phases/<skill>/iter-<n>-<phase>.xml  phases/<skill>/result.json
    <skill>-state.json ...
```

## Conditional steps — skipping is data, never improvisation

The hook chain is not a hardcoded sequence: every pre-hook gate is a
*condition over recorded state*, so which steps run for a ticket is
controlled by **flags set during /create-ticket analysis (planner-recommended,
user-confirmed) and read by deterministic gates** — never by asking a model
to skip politely, and never by invocation-time options that would bypass the
audit trail. Current conditional controls:

| Control | Set where | Effect |
|---------|-----------|--------|
| `needs_design` | ticket analysis (epics always true) | `false`: pre-create-design BLOCKS the step; pre-create-spec stops requiring a completed design. The skip is enforced in both directions. |
| `docs_only` | ticket analysis, user-confirmed | `true`: /code drops tests-first and the coverage hard fail (`coverage: n/a — docs_only`); the full suite still runs once and must be green; the verifier's Tests/Coverage dimensions become n/a, all others apply. A diff line touching executable code under this flag is a blocking finding. |
| epic children | minted by `new-ticket.py` | a completed `create-ticket` run is recorded at mint time — children start at /create-design (epic's) or /create-spec without a fake step. |
| `flow: product` | product-level skills | the delivery ticket skips the six-step pipeline; /merge-pr's gate accepts the PR reference from the product skill's state file. |

The spine — ticket → spec → code → PR → merge — is deliberately
unconditional: each step is a distinct guarantee (tracked record, verifiable
contract, reviewed implementation, delivery, human gate), and each scales
down with task size. A new conditional step must follow the same pattern:
a ticket-level flag, user confirmation at analysis time, and gate logic in
`acs_lib.py` enforcing both the skip and the non-skip.

## Testing layers — unit always, e2e by configuration, CI at the gate

There is deliberately NO separate testing skill: tests belong to the same
changeset as the change (like docs), and *executing* suites is verification,
which the code-verifier owns. Three layers:

| Layer | Authored | Executed & gated |
|-------|----------|------------------|
| Unit + coverage | /code executors, tests-first (TDD) per the spec's Test plan | Executors iterate to green; the verifier RE-RUNS the suite and RE-MEASURES coverage vs `test_coverage_percent` — hard fail below target (`docs_only` relaxes only this layer's authoring, never the suite-must-stay-green rule) |
| E2E (`settings.e2e`: command + optional setup/teardown) | /code executors, when the spec's Test plan declares e2e impact — same changeset, never a follow-up; /create-project scaffolds the harness for greenfield repos with a user-facing surface; /init detects and offers the config | Executors run the AFFECTED e2e tests; the verifier runs the FULL suite (setup → command → teardown always) — a red suite blocks, and with `per_iteration: false` (default, e2e is slow) the run may be skipped only on iterations that already have other blocking findings: **no zero-findings verdict without a green e2e run** |
| CI (scaffolded by /create-project; runs unit + e2e on the PR) | — | /merge-pr readiness reads CI status — report-only, never auto-fixed |

The chain of declarations keeps e2e honest: the spec's Test plan states the
e2e impact (or "no e2e impact" with a reason) → the code plan maps it into
executor tasks → the verifier demands matching e2e test diffs from any spec
that declared impact. A repo without `settings.e2e` skips the layer entirely;
adding it later is one /acs:init re-run.

## Requirement clarification — controlled, recorded, never repeated

Clarification is governed by one ledger and four rules. The ledger:
`<partition>/clarifications.json` (schema shipped; append-only via
`hooks/scripts/clarify.py` — add / answer / list). Every Q&A of the ticket
lives there with id (`C-n`), asking skill, status
(`open | answered | assumed | withdrawn`), source (`user | assumption`), and
rationale for assumptions.

1. **Research first.** A planner/executor never asks what the repo, docs,
   PRD, design, or ledger can answer — researchable facts are researched and
   cited (grounding rules); only genuinely open decisions (user preference or
   business trade-off that changes what gets built) become questions.
2. **Ask once, at the cheapest phase.** Before asking the user ANYTHING, the
   coordinator runs `clarify.py list` and reuses recorded answers — re-asking
   an answered question is a defect. Each skill asks only what ITS phase
   needs settled (ticket scope at /create-ticket, design trade-offs at
   /create-design, spec-level behavior at /create-spec, execution blockers at
   /code), batched, not dribbled.
3. **Record everything.** Every answer received — interactively or via a
   /ship relay when re-invoking a step — is recorded with `clarify.py add/answer`
   BEFORE acting on it; coordinators feed the ledger into subagent `<context>`,
   and executors cite the `C-n` ids they relied on (`clarifications_used`).
4. **Assumptions are visible debt.** When no user is available (or the user
   says "you decide"), the decision is recorded as `assumed` with a
   rationale; assumptions surface in the completion report's Findings line
   and the PR body until a user confirms (flips to `answered`) or overrides
   them. A silent default is a verifier finding.

Under /ship: a step that cannot proceed records its questions as `open`,
returns the `needs_input` handoff; /ship relays the user's answers when it
re-invokes the step directly, and the step coordinator records them before
resuming.
(Product-level elicitation — e.g. /create-prd's product definition — lands
in its real artifact, the PRD itself; the ledger is for ambiguity
resolution, not for primary content capture.)

## Living architecture — day-by-day currency by induction

The architecture doc set (`architecture_path`) stays current through an
induction invariant, not a periodic chore:

- **Base case** — /create-architecture bootstraps the doc set verified
  against both the PRD and the actual codebase.
- **Inductive step** — every ticket carries its own architecture delta in
  the SAME changeset: /create-design conforms or lists required doc changes;
  the code plan's documentation map names the HLD files and `lld/flows/`
  diagrams to update; the code-verifier derives the architectural impact
  from the diff itself (a positive, evidenced conclusion — never a default)
  and blocks the PR when impact exists without matching doc changes.
- **Drift repair (boy-scout)** — commits that bypass the pipeline can still
  desynchronize docs. Both the design planner and the code planner compare
  the touched area's docs against current code and schedule stale sections
  for repair as part of the ticket; widespread drift triggers a recommended
  /create-architecture re-run (the full reconcile, shipped as its own
  delivery ticket + docs PR).

Net effect: after every merge the doc set matches the code — "update the
architecture" is not a separate activity but a blocking dimension of every
change that has architectural impact.

The same induction maintains the **living requirements**
(`requirements_path`, default `docs/requirements/`, one file per feature
area): per-ticket specs are archived change-deltas, so the CURRENT
behavioral contract accumulates here instead — /code's documentation step
merges the merged ticket's acceptance criteria and behavior-defining
clarifications (answered/assumed ledger entries) into the touched area's
file; /create-ticket and /create-spec read it as standing behavior and flag
contradictions; the code-verifier blocks a user-observable behavior change
whose requirements file was not updated. Phrasing rule: the file states what
the product DOES now — current behavior, not change history.

## Size control: tickets, specs, PRs

The PR is the unit of review, and **the ticket is the PR boundary** — every
spec of a ticket lands on one branch in one PR. Size is therefore controlled
at two levers, with an escalation between them:

1. **Ticket sizing (controls PR size).** `/create-ticket`'s planner applies a
   PR-size rubric to the type decision: a story/task should yield one
   reviewable PR — rule of thumb ~≤400 changed lines, one concern, ≤~7
   acceptance criteria, grounded in the codebase survey. Above the bar →
   epic with children cut at PR-sized, independently shippable seams.
2. **Spec sizing (controls execution units).** Each spec is one coherent
   slice sized for a single /code executor pass; the spec count is a size
   *signal*, never a release valve.
3. **Escalation.** When `/create-spec`'s planner finds the honest
   decomposition exceeds ~4 specs (or the surface clearly exceeds a
   reviewable diff), it stops and recommends a split; the coordinator
   confirms with the user and routes to
   `/acs:create-ticket split <id> per <plan artifact>` — the ticket becomes
   an epic keeping its id, children ship as separate PRs. The user may
   explicitly accept one large PR; that decision is recorded as a
   clarification and surfaces in the PR body.

The numbers are deliberate rules of thumb for the planners' judgment, not
hard limits enforced by hooks — splitting at a bad seam (e.g. a child that
cannot build alone) is worse than a slightly large PR; feature flags are the
sanctioned way to keep children shippable when a slice alone would break.

## Settings, formats, templates

- Resolution: `settings.local.json` -> project `settings.json` -> user
  `~/.acs/settings.json`, deep-merged per key (defaults in `acs_lib.py`).
  A linked worktree without its own gitignored `settings.local.json` inherits
  the main checkout's.
- Inline formats are validated by every pre-hook (unknown placeholder = exit 2;
  `branch_name` must embed `{ticket_id}`).
- Long descriptions come from templates: built-in name -> `templates/`;
  otherwise `<repo>/.acs/templates/<name>.md`; otherwise absolute path.
- `enforcement` (opt-in, /init Step 7c): repo-side CI that holds *every* PR to
  the same conventions, so the pipeline can't be silently bypassed. /init copies
  `templates/ci/check-conventions.py` -> `<repo>/.acs/ci/` and
  `templates/ci/acs-conventions.yml` -> `<repo>/.github/workflows/`. The checker
  is intentionally **standalone (stdlib only, no `acs_lib` import)** because it
  runs on a CI runner with no acs install — it re-derives the conventions by
  compiling the committed `formats.*` strings to regexes ({ticket_id} ->
  `PREFIX-\d+`, {type} -> `epic|story|task`, {slug} -> lower-kebab, free text ->
  `.+`), reading `ticket_prefix` + `formats` from the committed project
  `settings.json`. It is fail-closed and tested by `tests/test_conventions_check.py`.
  The CI check is necessary-but-not-sufficient (workspace proof lives off-repo),
  so the real gate is a required status check on a protected default branch;
  `exempt_branches`/`exempt_label` are the escape hatch for non-ticket PRs.
  The sanctioned way to LAND such a PR is `/acs:merge-pr --pr <n>` (also `#n` or
  a PR URL): a non-ticket mode that runs the same four readiness dimensions and
  branch/worktree cleanup as the ticket path but resolves no ticket, writes no
  partition/state, and skips tracker sync and archiving — `skill-start.py --pr`
  validates the PR carries the `exempt_label` (or an `exempt_branches` head) and
  refuses + redirects to `/acs:merge-pr <ticket-id>` when the PR looks
  ticket-backed. `/acs:init` Step 7e renders the `templates/CLAUDE.acs.md`
  managed block into the repo's `CLAUDE.md` (idempotent, marker-delimited) to
  steer everyday changes onto `/acs:ship` so the pipeline is the default, not
  just the available, path.
  The same checker runs three modes off one config: `--mode pr` (CI: branch,
  commit, pr_title, acs_label, pr_description), `--mode pre-push` (local hook:
  branch + commit subjects of the push range), `--mode commit-msg` (local hook:
  the commit subject as written). Each mode's checks are `MODE_CHECKS[mode]`
  intersected with the `enforcement.checks.*` toggles, so local hooks and CI
  enforce identical, user-configured `formats.*` — laptop and runner never drift.
  Local hooks install via the pre-commit framework (tracked/shared) or raw
  `.git/hooks/*` (per-clone), both `--no-verify`-bypassable. The per-clone
  install is the unhooked, user-invoked skill `/acs:install-hooks` (wrapping the
  committed `.acs/ci/install-hooks.sh`, which a teammate can run without the
  plugin) — the `pre-commit install` equivalent for acs.

## Consumer-repo prerequisites

`git`, `python3` (3.9+, stdlib only), `gh` (PRs; also tracker sync when
`tracker.provider=github`), `pre-commit` (recommended — shared local convention
hooks), `acli` (only when `tracker.provider=jira`), `xmllint` (optional —
authoritative XSD validation via `ACS_XML_AUTHORITATIVE=1`; the default fast
path is the in-process stdlib validator which is XSD-equivalent and requires no
external tool). `acs_lib.check_toolchain()` is
the single source of truth for this list (kind = required | recommended |
optional, with per-platform install commands); `/init` Step 0b reports it and
offers to install the missing required/recommended tools before configuring
anything, so the full workflow is ready rather than failing mid-pipeline.
