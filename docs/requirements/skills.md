# Skill Requirements

Fifteen skills in total: the bootstrap skill (`/init`), the umbrella command
(`/ship`), the utility skills — the session-handoff helper (`/handoff`), the
update assistant (`/update`), the local-hooks installer (`/install-hooks`), and
the read-only metrics dashboard (`/metrics`) — the product-level
`/create-prd`, `/create-architecture`, and `/create-project`, and six
workflow skills (one of them, `/create-design`, conditional).
Every **workflow** skill MUST:

- run the Reflection cycle (plan → execute → verify) with its own
  `<skill>-planner`, `<skill>-executor`, `<skill>-verifier` subagents
  ([reflection.md](reflection.md));
- be gated by a pre-hook and persisted by a post-hook
  ([hooks.md](hooks.md));
- read and write **only** inside `<workspace>/<repo>/<ticket-id>/` for state
  (the consumer repo is touched only where the skill's job requires it,
  e.g. `/code` edits source files);
- read configuration from the `.acs` `settings.json`
  ([configuration.md](configuration.md)), and spawn its
  planner/executor/verifier on the models and effort levels configured there
  ([configuration.md](configuration.md#subagent-models));
- (except `/create-ticket`) resolve the target `<ticket-id>` before doing
  anything — explicit argument, else session context, else branch name
  ([workflow.md](workflow.md#ticket-context));
- record every requirement Q&A in the per-ticket **clarification ledger**
  (`clarifications.json`): research first, ask once at the cheapest phase
  (re-asking an answered question is a defect), record answers before acting
  on them, and record unanswerable decisions as visible **assumptions** with
  rationale ([workspace-and-state.md](workspace-and-state.md));
- end every direct invocation with the **standard completion report**
  (Ticket / Status / Results / Findings / Artifacts / Metrics / Next), rendered
  only after the post-hook succeeded; under `/ship` the compact XML handoff
  replaces it.

---

## `/init` (bootstrap)

Purpose: make the `acs` plugin work on any consumer repo by generating its
configuration.

- MUST generate a `settings.json` in **user scope** (`~/.acs/settings.json`)
  or **project scope** (`<repo>/.acs/settings.json`); the user chooses the
  scope at init time.
- MUST prompt the user for `workspace_path` — there is no default; this is
  required input at init time.
- MUST prompt for **`ticket_prefix`**, suggesting one derived from the
  repo/product name (e.g. `SHOP`) — ticket ids are per-repo; there is no
  global default prefix.
- MUST require/validate that `workspace_path` is **outside the consumer
  repo**, so git worktrees and parallel tasks are supported.
- MUST set `test_coverage_percent` with a default of **90** (user may
  override).
- SHOULD create the workspace folder if it does not exist, and verify it is
  writable.
- `/init` is not part of the gated pipeline (no planner/executor/verifier
  subagents); it is a simple setup skill.
- All other skills' pre-hooks fail fast (exit 2) with a "run /init first"
  message when no `settings.json` can be found.
- Re-running `/init` on an initialized repo/user scope **updates the
  existing settings in place** (preserving keys it does not touch).

## `/ship` (umbrella)

Purpose: drive the whole pipeline from one command.

- `/ship <prompt>` MUST run the workflow skills in order —
  `/create-ticket` → `/create-design` (when the ticket needs design) →
  `/create-spec` → `/code` → `/create-pr` — and stop before `/merge-pr`,
  which stays a user action
  ([workflow.md](workflow.md#umbrella-command-ship)).
- MUST NOT bypass any pre/post hook; it adds orchestration only.
- SHOULD be resumable: re-running it for a ticket continues from the first
  incomplete step recorded in workspace state.
- No planner/executor/verifier of its own; each step skill is **invoked
  directly by the ship coordinator in its own context** and runs its own
  reflection cycle, returning only a compact XML handoff — `/ship` tracks the
  pipeline through `pipeline-state.json` so its context can be cleared between
  steps ([workflow.md](workflow.md#context-handoff-between-steps)).

## `/handoff` (utility)

Purpose: deliberately hand the current ticket/skill off to a fresh session
when the current one grows long
([workflow.md](workflow.md#session-handoff)).

- Flushes all in-flight work and soft context (user clarifications,
  decisions, partial findings, gotchas) to the ticket partition, finalizes
  the current run entry with status `handed_off` plus a handoff summary, and
  releases the `.lock`.
- Prints the exact command to continue in a new session (e.g.
  `/code SHOP-123`).
- Not part of the gated pipeline; no planner/executor/verifier subagents.
- Workflow coordinators SHOULD trigger the same flush proactively on context
  pressure, without waiting for the user to invoke `/handoff`.

## `/update` (utility)

Purpose: assist the plugin upgrade — Claude Code owns the plugin lifecycle;
this skill owns the workflow around it.

- **User-invoked only** (`disable-model-invocation`): updating changes the
  running environment.
- Compares the installed version (`plugin.json` at the install root) with the
  latest release; summarizes the CHANGELOG delta between them and calls out
  breaking changes (MAJOR bumps, settings-key changes, state-shape notes).
- With user consent, refreshes the marketplace
  (`claude plugin marketplace update gms-marketplace`) — updates reach consumers only
  when the plugin's `version` bumps (semver; automated release tagging).
- Runs post-update migration checks: settings valid against the new schema,
  status-line paths still resolve (they hold absolute install paths —
  re-run `/init` Step 7b when the install moved), workspace reachable.
- Reloading is the user's action (`/reload-plugins` or a new session); the
  skill states this explicitly — the current session keeps the old version.
- Not part of the gated pipeline; no planner/executor/verifier subagents.

## `/metrics` (utility)

Purpose: render a **read-only** in-session dashboard of this repo's delivery
metrics, derived entirely from existing workspace state — no network, no new
config key, nothing written.

- **Model-invocable** (unlike `/update` and `/install-hooks`, it does not set
  `disable-model-invocation`): a natural-language request to see this repo's
  throughput, spend, coverage, or review effort routes here.
- Runs the stdlib helper `metrics_aggregate.py`, which emits one aggregate JSON
  of **six panels** — throughput by status/type, pipeline funnel, cost and time
  per ticket by step, coverage achieved vs target, review iterations before the
  verifier passed, and token burn by role (planner/executor/verifier).
- The coordinator **routes** the aggregate JSON through the deterministic stdlib
  renderer `metrics_render.py` rather than composing the layout itself: the
  **terminal** Unicode dashboard is the Claude Code CLI default, and `--html`
  emits a self-contained HTML string handed to `show_widget` on Claude
  Desktop / claude.ai. Rendering is deterministic and read-only; every panel key
  is always present (a panel with no data renders as "no data", not a missing
  frame). The deterministic terminal renderer **supersedes** the former
  Markdown-table fallback.
- **Reads only** — writes no file, makes no network/`gh` call, and consumes no
  config key beyond the `.acs/settings.json` the helper already reads.
- Not part of the gated pipeline; no planner/executor/verifier subagents.

## Product-level delivery (tickets)

**Every change is tracked as a ticket — including product-level work.**
Tickets are the project-management record, so the three product-level
skills, while not running the ticket pipeline, MUST each create their own
**delivery ticket** per run:

- The skill creates the ticket first (type **task**, e.g.
  `SHOP-1 — Product definition (PRD)`): a normal id from the per-repo
  counter, a normal workspace partition, tracker sync when configured (so
  PRD/architecture/scaffold work is visible in Jira / GitHub Projects), and
  the standard archive lifecycle. Re-running a product-level skill (e.g. a
  PRD amendment) creates a **new ticket** for that change.
- All formats apply with the real ticket id: the skill creates the branch
  (`formats.branch_name`), commits (`formats.commit_message`), and opens
  the PR (PR formats, `ACS` label) itself — `/create-design`,
  `/create-spec`, and `/code` are not involved.
- The skill's state file (`create-prd-state.json`, …) lives in the delivery
  ticket's partition like any other skill state, records the PR reference,
  and `pipeline-state.json` marks the flow as product-level. Locking,
  resume, handoff, and metrics work exactly as for any other ticket.
- `/merge-pr` works as for any other ticket: readiness check, merge, mark
  done (and sync), archive the partition.

## `/create-prd` (product-level)

Purpose: define the product — the **PRD** is the root document everything
else is verified against.

- Product-level and ticket-independent. Runs before `/create-architecture`
  (whose pre-hook requires the PRD). Re-running **amends the PRD in
  place**, preserving sections it does not touch.
- For a **greenfield** product: elicits the definition from the user. For
  an **existing** product: reverse-engineers a baseline PRD from the
  codebase and docs, confirming open points with the user.
- Produces the PRD doc set in the consumer repo at `prd_path` (default
  `docs/product/` — [configuration.md](configuration.md)):
  - `prd.md` — vision, problem statement, target users & personas, goals
    with **measurable success metrics**, prioritized features (e.g.
    MoSCoW), product-level NFRs, constraints & assumptions, out-of-scope;
  - `roadmap.md` — milestones/phases mapped to intended epics.
- Reflection cycle: `create-prd-planner`, `create-prd-executor`,
  `create-prd-verifier`. The verifier checks: all required sections
  present, features trace to goals, success metrics are measurable, and
  nothing contradicts the stated constraints.
- State lives in the delivery ticket's partition
  (`create-prd-state.json`).
- Delivery: docs-only PR via the
  [product-level delivery rules](#product-level-delivery-tickets) — each
  run creates its own delivery ticket.
- Downstream: `/create-architecture` is verified against the PRD, and
  `/create-ticket` traces tickets to PRD features and flags divergence
  ([workflow.md](workflow.md#product-level-architecture)).

## `/create-architecture` (product-level)

Purpose: bootstrap and regenerate the **product architecture doc set** — the
living system documentation the whole pipeline designs and verifies against.

- Product-level and **ticket-independent**: not part of the per-ticket
  pipeline. Run once when starting a product (or onboarding `acs` onto an
  existing repo); re-run to regenerate after major shifts.
- MUST take the **PRD** (`prd_path`) as its primary input — its pre-hook
  requires the PRD to exist (run `/create-prd` first; it also baselines
  existing products). For an **existing codebase** it additionally
  reverse-engineers the current architecture from the code and docs,
  confirming open points with the user; for a **greenfield** product it
  designs the system to satisfy the PRD.
- Produces the doc set in the **consumer repo** at `architecture_path`
  (default `docs/architecture/` — [configuration.md](configuration.md)),
  split into **high-level design (HLD)** and **low-level design (LLD)**:
  - `hld/overview.md` — system context, goals, quality attributes,
    constraints;
  - `hld/c4-context.md`, `hld/c4-container.md`, `hld/c4-component.md` — the
    **C4 model, levels 1–3**; C4 level 4 (code) is deliberately out of
    scope — the code and its API docs serve that level;
  - `hld/data-model.md` — entities and relationships (ER diagrams);
  - `hld/deployment.md` — runtime and infrastructure topology;
  - `hld/tech-stack.md` — languages, frameworks, conventions;
  - `lld/flows/<flow>.md` — **sequence diagrams** for the key runtime
    flows, one file per flow — bootstrapped for the main flows (selected by
    the planner, confirmed with the user) and grown ticket by ticket;
  - `lld/contracts.md` — interface/API contracts between components.
- All diagrams are **Mermaid** (C4, ER, sequence, and state diagrams as
  code: diffable, reviewable, rendered by GitHub, maintainable by agents).
- Runs the full Reflection cycle — `create-architecture-planner`,
  `create-architecture-executor`, `create-architecture-verifier`. The
  verifier checks: the design **satisfies the PRD** (goals, product-level
  NFRs, constraints); the docs match the actual codebase; they are
  internally consistent; diagrams agree with the prose; and **HLD and LLD
  agree with each other** (every participant in a sequence diagram exists
  in the C4 views).
- State lives in the delivery ticket's partition
  (`create-architecture-state.json`)
  ([workspace-and-state.md](workspace-and-state.md)).
- Delivery: docs-only PR via the
  [product-level delivery rules](#product-level-delivery-tickets) — each
  run creates its own delivery ticket; the TDD pipeline does not apply to a
  docs-only change.
- Maintenance afterwards belongs to the pipeline: `/create-design` designs
  against the doc set, and `/code` updates it whenever a change alters the
  architecture ([workflow.md](workflow.md#product-level-architecture)).

## `/create-project` (product-level)

Purpose: scaffold a fresh product's repo skeleton from the approved
architecture, so the ticket pipeline works from the very first ticket.

- Product-level, ticket-independent, and **greenfield-only** — existing
  codebases never need it. Runs once, after `/create-architecture`: its
  pre-hook requires the architecture doc set to exist (the tech stack and
  structure must be settled before scaffolding).
- Scaffolds, per `hld/tech-stack.md` and the HLD structure:
  - directory layout matching the container/component views;
  - package/build configuration;
  - the **test framework and coverage tooling**, wired to measure
    `test_coverage_percent` — the `/code` TDD gates depend on this existing
    from ticket #1;
  - an **e2e harness** (plus one smoke e2e test and CI wiring, and a proposed
    `e2e` settings block) when the architecture has a user-facing or
    cross-component surface;
  - linter/formatter and pre-commit configuration;
  - a CI workflow running build, lint, tests, and coverage;
  - `.gitignore`, README skeleton, and a **minimal green vertical slice**
    (entrypoint + smoke test) proving the harness works.
- Reflection cycle: `create-project-planner`, `create-project-executor`,
  `create-project-verifier` — the verifier MUST actually run build, lint,
  and tests and see them pass; a scaffold that doesn't run green fails
  verification.
- State lives in the delivery ticket's partition
  (`create-project-state.json`)
  ([workspace-and-state.md](workspace-and-state.md)).
- Delivery: bootstrap PR via the
  [product-level delivery rules](#product-level-delivery-tickets) — its own
  delivery ticket. The scaffolded CI workflow runs on this very PR —
  proving the harness green in CI, not just locally.

## 1. `/create-ticket`

Purpose: turn a raw user prompt into a well-formed ticket.

- MUST analyze and clarify requirements from three sources: the **user
  prompt**, the **codebase**, and existing **docs**.
- MUST consult the **PRD** when present: tickets SHOULD trace to PRD
  features/goals, and epics SHOULD derive from the roadmap. MUST also read
  the touched areas' **living requirements** files (`requirements_path`) as
  the current behavior and flag any contradiction the request implies
  (deliberate behavior change vs. mistake). When a requested
  capability goes beyond the PRD, `/create-ticket` MUST flag the divergence
  and propose a PRD amendment (a `/create-prd` re-run, user-confirmed)
  before proceeding.
- MUST interact with the user to resolve ambiguities before finalizing
  (clarifying questions).
- MUST create a ticket with a type of **epic**, **story**, or **task**.
- When the ticket type is **epic**, MUST suggest creating child
  **story**/**task** tickets; each child gets its own `<ticket-id>` and runs
  its own pipeline. The epic's status is auto-managed: **In Progress** when
  work starts on any child, **Done** when all children are merged
  (see [workflow.md](workflow.md#epic-fan-out)).
- Ticket title and description MUST follow the per-type ticket formats
  configured in `settings.json` — epic, story, and task each have their own
  title/description format ([configuration.md](configuration.md)).
- Tickets are **local-first**: the ticket JSON in the workspace is the local
  source of truth. Optionally, based on the `tracker` config in
  `settings.json`, the ticket syncs **two-way** with a **GitHub Project** or
  **Jira board**:
  - `ticket.json` MUST hold a mapping field linking the local ACS id to the
    remote key (e.g. Jira `PROJ-456`); the local `<ticket-id>` always names
    the workspace partition.
  - Tracker access goes through the official CLIs — **`gh`** for GitHub and
    **`acli`** for Jira — which handle authentication themselves.
- MUST persist the ticket (and its `<ticket-id>`) into the workspace; the
  `<ticket-id>` names the workspace partition for the whole pipeline.
- Subagents: `create-ticket-planner`, `create-ticket-executor`,
  `create-ticket-verifier`.
- Ticket ids use the **per-repo prefix + sequence** (e.g. `SHOP-123`); the
  per-repo counter lives in `<workspace>/<repo>/counters.json`.
- MAY **import an existing remote ticket**: `/create-ticket <remote-key>`
  (e.g. `PROJ-456`) pulls the issue from the configured tracker, creates the
  local ticket with a fresh local id and the external mapping, and then runs
  the normal analysis/clarification on the imported description (incl.
  setting `needs_design`). From there the ticket ships like any local one.
- Two-way sync runs **on demand** (triggered explicitly by the user or a
  skill); scheduled background sync routines are a later enhancement.
- Sync conflicts (both the local and the remote ticket changed) are resolved
  by **asking the user** which side wins.
- Ticket schema — required fields: **title, type, description, acceptance
  criteria, priority, parent epic, children, status, external mapping,
  assignee, story points, needs-design flag, docs-only flag**. Parent/child links are stored
  in **both directions** (epic lists `children`; each child stores `parent`).
- MUST set **`needs_design`** during analysis: always `true` for epics; for
  stories/tasks the planner recommends a value and the user confirms it
  ([workflow.md](workflow.md)).
- MUST set **`docs_only`** during analysis (planner-recommended, user-confirmed,
  default `false`): `true` only when the change touches no executable code or
  tests. The flag relaxes `/code`'s tests-first and coverage hard-fail — the
  full suite still runs once and must stay green, and a diff line touching
  executable code under the flag is a blocking verifier finding.
- MUST size stories/tasks to **one reviewable PR** (rule of thumb ~<=400
  changed lines, one concern, grounded in a codebase survey); above the bar the
  planner recommends an epic with children cut at PR-sized, independently
  shippable seams.
- MAY **split an existing oversized ticket** (`/create-ticket split <id> ...`,
  typically from `/create-spec`'s escalation): the ticket becomes an epic
  **keeping its id**, description, and PRD trace; children are minted at the
  recorded seams; downstream work already present requires user confirmation
  first.

## 2. `/create-design` *(conditional)*

Purpose: settle the system design before implementation is specified — for
tickets where the change is architecturally significant.

- Runs only when the ticket carries **`needs_design: true`** (always set for
  epics; set for stories/tasks during `/create-ticket` analysis with user
  confirmation). All other tickets skip straight to `/create-spec`.
- MUST analyze the ticket, the codebase, and existing docs; MUST evaluate
  **multiple options with trade-offs** and interact with the user on the
  genuinely open decision points before settling.
- MUST take the product architecture doc set (`architecture_path`) as
  primary input when it exists: the design either **conforms to the
  documented architecture** or explicitly lists the architecture changes it
  requires — which `/code` then applies to the doc set as part of the
  change.
- Produces **`design.md`** in the ticket partition, with required sections:
  **context & constraints (incl. NFRs such as security and performance),
  options considered, decision & rationale, architecture (components,
  interfaces/contracts, data model, and Mermaid sequence diagrams for new or
  changed flows), impact & risks, rollout/migration**.
- Child tickets of an epic do NOT repeat design: their `/create-spec` reads
  the **parent epic's** `design.md` (cross-partition read,
  [workspace-and-state.md](workspace-and-state.md)).
- The `create-design-verifier` checks: alternatives genuinely weighed,
  consistency with the existing codebase and docs, feasibility, NFR
  coverage — all findings block, same 3-iteration reflection cap.
- Subagents: `create-design-planner`, `create-design-executor`,
  `create-design-verifier`.
- When `adr_path` is configured ([configuration.md](configuration.md)),
  the design's accepted decision records are committed into the consumer
  repo by `/code` as part of its documentation updates.

## 3. `/create-spec`

Purpose: turn a ticket into implementation specs.

- MUST analyze and clarify the ticket (asking the user where ambiguous).
- MUST produce **one or more** implementation specs ("different
  implementation specs") — decomposition into multiple specs is expected for
  larger tickets.
- MUST write specs into `<workspace>/<repo>/<ticket-id>/` so `/code` can consume
  them without conversation history.
- Subagents: `create-spec-planner`, `create-spec-executor`,
  `create-spec-verifier`.
- Spec format: **markdown** with required sections — **scope, approach,
  API/data changes, test plan, out-of-scope**. The **approach** section stays
  at contract level (components, interfaces, algorithms, error handling;
  indicative paths at most) — the authoritative file map belongs to `/code`'s
  planner. The **test plan** MUST state the **e2e impact** when `e2e` is
  configured or the change affects user-facing flows (the tests land in the
  same changeset), else "no e2e impact" with a reason.
- MUST escalate an **oversized ticket** instead of producing a monster spec
  set: when an honest decomposition exceeds ~4 specs (or the surface clearly
  exceeds a reviewable diff), stop, record the split seams, and route to
  `/create-ticket split <id>` (user-confirmed); the user MAY explicitly accept
  one large PR, recorded as a clarification.
- The **API/data changes** section SHOULD call out the documentation impact
  (which consumer-repo docs the change touches), so `/code` knows what to
  update.
- When a design exists (the ticket's own or its parent epic's), specs MUST
  **conform to it**, and the `create-spec-verifier` MUST check that
  conformance.

## 4. `/code`

Purpose: implement the specs in the consumer repo using TDD.

- MUST analyze and clarify the implementation specs before coding.
- MUST implement features, bug fixes, and tasks using the **TDD pattern**:
  write tests first, then implementation, iterating until green.
- MUST generate unit tests and run them targeting the configured
  `test_coverage_percent` (default 90) from `settings.json`.
- MUST update the consumer repo's **documentation affected by the change**
  as part of the implementation: README, API/usage docs, code comments, the
  changelog where the repo keeps one — and the **product architecture doc
  set** (`architecture_path`) whenever the change adds or removes
  components, or alters the data model, integrations, or deployment: HLD
  (C4 views, data model, deployment) updated accordingly, and the ticket
  design's new/changed **sequence diagrams merged into `lld/flows/`** —
  following the repo's existing conventions. MUST also merge the ticket's
  acceptance criteria and behavior-defining clarifications into the touched
  feature area's file under `requirements_path` (the living requirements —
  [workflow.md](workflow.md#living-requirements)). Docs work is part
  of the change, not a follow-up.
- Commit messages MUST follow the commit message format configured in
  `settings.json` ([configuration.md](configuration.md)).
- The `code-verifier` MUST review the changeset — **business logic**,
  **features** (does it satisfy the ticket/specs), **quality**, **technical
  standards**, **architecture**, **system design**, **security**, and
  **documentation** (affected docs updated and consistent with the code) —
  in addition to spec conformance, tests, and coverage. The architecture /
  system-design review judges the changeset against the approved `design.md`
  when one exists (the ticket's own or its parent epic's). Blocking findings
  trigger automatic remediation iterations (max 3); findings and stop
  reasons land in `code-state.json`
  ([workflow.md](workflow.md#review-feedback-loop)).
- MUST record progress, findings, errors, and stop reasons so an interrupted
  run can resume; final state lands in `code-state.json` via the post-hook.
- On start, if the previous run is `in_progress`/`interrupted`/`failed`,
  `/code` MUST **reconcile** before continuing: verify recorded progress
  against reality (e.g. re-run tests for specs marked implemented) and
  resume from the first unfinished spec/phase
  ([workflow.md](workflow.md#resuming-a-ticket)).
- Pre-hook (`pre-code.py`) MUST verify specs exist and `/create-spec`
  completed; otherwise exit 2 to stop the skill.
- Subagents: `code-planner`, `code-executor`, `code-verifier`.
- When the coverage target cannot be reached, `/code` MUST **hard fail**:
  stop, record the achieved coverage and reason in `code-state.json`, and
  leave the `/create-pr` gate closed.
- On a **`docs_only`** ticket the TDD steps relax (no new tests, no coverage
  measurement) but the guarantees do not: the full suite still runs once and
  must stay green, and executable-code diffs under the flag are blocking
  findings.
- When **`e2e`** is configured ([configuration.md](configuration.md)):
  executors author the e2e tests their specs declared (same changeset) and run
  the affected subset; the `code-verifier` runs the **full e2e suite** (setup
  -> command -> teardown, always) — no zero-findings verdict without a green
  run (`per_iteration: false` only defers it past iterations that already have
  other blocking findings).
- `/code` works on a dedicated git branch (and optionally a worktree) per
  ticket; the branch name follows `formats.branch_name` from `settings.json`
  and embeds the `<ticket-id>` so later skills and hooks can resolve ticket
  context from it.

## 5. `/create-pr`

Purpose: ship the implementation as a pull request.

- MUST create a PR containing the new changes for the implementation. The
  ticket's branch already exists — created by `/code` per
  `formats.branch_name` — so `/create-pr` pushes it and opens the PR.
- SHOULD compose the PR title/description from workspace state (ticket,
  specs, `code-state.json` summary incl. review findings) rather than
  conversation history.
- MUST record the PR reference (number/URL) in the workspace state.
- Subagents: `create-pr-planner`, `create-pr-executor`, `create-pr-verifier`.
- PR title and PR description MUST follow the formats configured in
  `settings.json` ([configuration.md](configuration.md)).
- The PR targets the repo's **default branch** and MUST carry the **`ACS`**
  label.
- **[ASSUMPTION]** PRs are created ready-for-review (not draft); reviewers
  are left to repo conventions.

## 6. `/merge-pr`

Purpose: land the change.

- `/merge-pr` is a **user action**: it MUST only run when the user explicitly
  invokes it, after they have reviewed the PR themselves. The pipeline never
  triggers it automatically.
- MUST review PR readiness — **[ASSUMPTION]** at minimum: CI status, review
  approvals, merge conflicts, branch protection requirements.
- Product-level delivery tickets (PRD, architecture, scaffold) merge like
  any other ticket — the PR reference is read from the skill's state file in
  the ticket partition
  ([Product-level delivery](#product-level-delivery-tickets)).
- MUST merge the PR **if possible**; if not possible, it MUST record the stop
  reason in the workspace state and report what is blocking. A failed
  readiness check is **report-only**: `/merge-pr` never routes fixes back to
  `/code` automatically.
- When the merged ticket is the last open child of an epic, the epic MUST be
  auto-marked done ([workflow.md](workflow.md#epic-fan-out)) —
  performed by the `post-merge-pr` hook.
- Subagents: `merge-pr-planner`, `merge-pr-executor`, `merge-pr-verifier`.
- Merge strategy is configurable via `merge_strategy` in `settings.json`
  (`squash` | `merge` | `rebase`), default **`squash`**.
- Post-merge actions (all required): **delete the branch**, **clean up the
  worktree** (if one was used), and **mark the ticket done** — in workspace
  state, in the remote tracker (if synced), and by archiving the ticket
  partition ([workspace-and-state.md](workspace-and-state.md)).
