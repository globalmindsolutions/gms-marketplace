# ACS — Business Requirements

This folder holds the business requirements for turning this repository into a
**Claude Code plugins marketplace** whose first plugin is **`acs`** — a
multi-step, agentic software-delivery workflow.

> **Status: DRAFT — requirements gathering.** These documents capture
> requirements only. No implementation has started. Requirements will continue
> to be added and refined before implementation begins.

## Documents

| Doc | Topic |
|-----|-------|
| [01-overview.md](01-overview.md) | Vision, goals, marketplace structure, core principles |
| [02-workflow.md](02-workflow.md) | The end-to-end 6-step workflow and step gating |
| [03-skills.md](03-skills.md) | Per-skill requirements (`/init`, `/ship`, `/handoff`, `/create-prd`, `/create-architecture`, `/create-project`, `/create-ticket`, `/create-design`, `/create-spec`, `/code`, `/create-pr`, `/merge-pr`) |
| [04-architecture.md](04-architecture.md) | Coordinator–subagents pattern, Reflection (plan–execute–verify), dynamic decomposition, XML communication |
| [05-hooks.md](05-hooks.md) | Pre/post hooks per skill: gating, exit codes, state writing |
| [06-configuration.md](06-configuration.md) | `/init` skill, `settings.json` scopes and keys |
| [07-workspace-and-state.md](07-workspace-and-state.md) | Workspace folder, `<ticket-id>` partitioning, state files, worktree support |
| [08-usage.md](08-usage.md) | Usage walkthroughs: setup, brownfield/greenfield bootstrap, `/ship` vs step-by-step, parallel worktrees, handoff, PRD amendments |

## Decision log

Resolved questions, newest first. Details live in the linked docs.

| Date | Decision |
|------|----------|
| 2026-06-12 | Remote ticket import: `/create-ticket <remote-key>` (e.g. a Jira key) pulls the issue from the configured tracker into a local ticket (fresh local id + external mapping, normal analysis applies) so PM-created tickets can be shipped. See [03-skills.md](03-skills.md), [08-usage.md](08-usage.md). |
| 2026-06-12 | **Every change is a ticket** — including product-level work: each `/create-prd` / `/create-architecture` / `/create-project` run creates its own **delivery ticket** (type task) with a normal id, partition, tracker sync, and archive lifecycle; state files live in the partition; no repo-level state or locks; `/merge-pr` works as for any ticket. Supersedes the reserved-delivery-id scheme below. See [03-skills.md](03-skills.md). |
| 2026-06-12 | `ticket_prefix` is **required at `/init`, per repo** (suggested from the repo name) — no global `ACS` default; different consumer repos get different prefixes. Doc examples now use `SHOP-…`. The `ACS` PR label stays (it marks the tool, not the project). See [06-configuration.md](06-configuration.md). |
| 2026-06-12 | *(superseded — replaced by real delivery tickets, see above)* Product-level deliveries via reserved delivery ids (`<prefix>-PRD`/`-ARCH`/`-PROJECT`) with repo-level state and locks. Still valid from this decision: `/code` creates the ticket branch, `/create-pr` pushes it and opens the PR; `{external_key}` carries the Jira/GitHub id in formats when synced. |
| 2026-06-12 | PRD layer added: new product-level `/create-prd` skill produces the product definition at `prd_path` (`prd.md`: vision, problem, personas, goals with measurable success metrics, prioritized features, product NFRs, constraints, out-of-scope; `roadmap.md`: milestones → epics). Elicited for greenfield, reverse-engineered as a baseline for existing products; re-runs amend in place. `/create-architecture` now **requires** and is verified against the PRD; `/create-ticket` traces tickets to PRD features and flags divergence (amendment via `/create-prd`, user-confirmed). Conformance chain: **PRD → architecture → design → specs → code**. See [03-skills.md](03-skills.md). |
| 2026-06-12 | The umbrella command `/acs` is **renamed to `/ship`** (says what it does; avoids colliding with the plugin name). Older log rows keep the historical name. |
| 2026-06-12 | Greenfield support: new product-level `/create-project` skill scaffolds the repo skeleton from the approved architecture (layout, build, **test framework + coverage tooling**, lint, CI, minimal green vertical slice) — greenfield-only, runs after `/create-architecture`; its verifier must see build/lint/tests pass. Fresh-product flow: `/init` → `/create-architecture` → `/create-project` → MVP epic → `/ship` children. See [02-workflow.md](02-workflow.md), [03-skills.md](03-skills.md). |
| 2026-06-12 | `acs` = **Autonomous Coding Skills**. Distribution: GitHub URL only. Versioning: semver + CHANGELOG.md + automated releases. See [01-overview.md](01-overview.md). |
| 2026-06-12 | **All** verifier findings block in the `/code` review loop — remediation runs until zero findings (cap 3). See [02-workflow.md](02-workflow.md). |
| 2026-06-12 | Ticket ids: configurable prefix + per-repo sequence (`counters.json`). Schema: title, type, description, acceptance criteria, priority, parent epic, children, status, external mapping, assignee, story points — parent/child links in both directions. See [03-skills.md](03-skills.md). |
| 2026-06-12 | Sync conflicts: ask the user. Specs: markdown with required sections (scope, approach, API/data changes, test plan, out-of-scope). See [03-skills.md](03-skills.md). |
| 2026-06-12 | Coverage target missed → hard fail, recorded in `code-state.json`. See [03-skills.md](03-skills.md). |
| 2026-06-12 | PRs target the default branch and carry the `ACS` label; `merge_strategy` configurable (default squash); post-merge: delete branch, clean worktree, mark ticket done + archive partition. See [03-skills.md](03-skills.md). |
| 2026-06-12 | XML messages validated against a formal schema (XSD); decomposition is coordinator-only; parallel executors allowed within a skill. See [04-architecture.md](04-architecture.md). |
| 2026-06-12 | Hooks: ticket id via per-checkout pointer file (`sessions/<checkout-id>.json`), branch name fallback; stdlib-only Python 3; abnormal endings still write state; event binding deferred to implementation. See [05-hooks.md](05-hooks.md). |
| 2026-06-12 | Config: per-key precedence `settings.local.json` → project `settings.json` → user; machine-specific keys (e.g. `workspace_path`) live in gitignored `settings.local.json`; `/init` re-runs update in place. Placeholder vocabulary, description-template set, and tracker mappings defined in [06-configuration.md](06-configuration.md). |
| 2026-06-12 | State: current state + append-only `runs` array; per-ticket `.lock` for parallel worktree sessions; done partitions archived; repo-level `tickets-index.json`, `counters.json`, `sessions/`, `metrics.json`; JSON Schemas shipped with the plugin. See [07-workspace-and-state.md](07-workspace-and-state.md). |
| 2026-06-12 | `/acs` context handoff: each skill runs in a fresh subagent context, returns a compact XML handoff; `pipeline-state.json` step ledger lets `/acs` clear/compact context at step boundaries. See [02-workflow.md](02-workflow.md). |
| 2026-06-12 | Metrics recorded per run (time, tokens, cost), rolled up per ticket (`pipeline-state.json`) and per repo (`metrics.json`: ticket/PR counts + totals). See [07-workspace-and-state.md](07-workspace-and-state.md). |
| 2026-06-12 | Target domains documented: strong fit = automatically testable, git/GitHub-delivered, code/text artifacts (backends, libraries, CLIs, web apps, data pipelines); caveats and out-of-scope listed, incl. `gh`/GitHub being assumed for PRs (other forges = future enhancement). See [01-overview.md](01-overview.md). |
| 2026-06-12 | Architecture doc set structured as **full system design**: HLD = C4 model levels 1–3 (`hld/c4-context/-container/-component.md`) + overview, data model, deployment, tech stack; LLD = per-flow **sequence diagrams** (`lld/flows/`) + interface contracts; C4 level 4 out of scope. Ticket designs carry sequence diagrams for new/changed flows; `/code` merges them into the LLD; the architecture verifier checks HLD↔LLD agreement. See [03-skills.md](03-skills.md). |
| 2026-06-12 | Product-level architecture: ticket-independent `/create-architecture` skill bootstraps a living architecture doc set (overview, components, data model, deployment, tech stack — all diagrams **Mermaid**) at `architecture_path` in the consumer repo; reverse-engineered for existing codebases, elicited for greenfield; delivered as a docs-only PR. `/create-design` designs against it; `/code` keeps it current. Conformance chain: **architecture → design → specs → code**. See [02-workflow.md](02-workflow.md), [03-skills.md](03-skills.md). |
| 2026-06-12 | Design phase added: conditional `/create-design` between `/create-ticket` and `/create-spec` — epics always, stories/tasks via a `needs_design` flag set during ticket analysis. Produces `design.md` (options & trade-offs, decision & rationale, architecture, risks, rollout) under the full Reflection cycle; specs must conform to it; epic children inherit it (cross-partition read); optional `adr_path` commits decision records into the repo via `/code`. See [02-workflow.md](02-workflow.md), [03-skills.md](03-skills.md). |
| 2026-06-12 | Docs updates are part of `/code`: affected consumer-repo documentation (README, API/usage docs, comments, changelog per repo convention) is updated with the change; **documentation** added to the verifier's review dimensions; specs flag docs impact in the API/data changes section. See [03-skills.md](03-skills.md). |
| 2026-06-12 | Reasoning **effort** configurable alongside models: a role accepts a model string or `{model, effort}` object; model and effort resolve independently (per-skill override → role default → inherit); unsupported effort fails at spawn. See [06-configuration.md](06-configuration.md). |
| 2026-06-12 | Coordinator model is configurable but enforceable only for `/acs`-spawned coordinators; direct invocations run on the session model, and the skill surfaces a notice if `models.coordinator` is set and differs (no silent divergence). See [06-configuration.md](06-configuration.md). |
| 2026-06-12 | Per-role subagent models configurable in `settings.json`: `models.planner/executor/verifier` (+ `models.coordinator` for `/acs`-spawned coordinators), per-skill overrides, `inherit` default, no silent fallback on unknown ids. See [06-configuration.md](06-configuration.md). |
| 2026-06-12 | Session handoff: a long session hands a ticket to a fresh one via a graceful flush — soft context persisted, run entry finalized as `handed_off` with a summary, lock released; triggered by the new `/handoff` utility skill or proactively by coordinators on context pressure. See [02-workflow.md](02-workflow.md). |
| 2026-06-12 | Resume designed in at three levels: between steps (ledger + gates), within `/acs` (first incomplete step), and mid-skill (`in_progress` run entry written at skill start, phase-boundary persistence, reconcile mode on re-run; `.lock` re-entrant per checkout). See [02-workflow.md](02-workflow.md). |
| 2026-06-12 | State files normalized — no duplicated fields: status/stop reason live only on `runs` entries (last entry = current state, pre-hooks gate on `runs[-1].status`); durations computed from timestamps; `skill`/`ticket_id` kept in-file deliberately for self-description after archiving. See [07-workspace-and-state.md](07-workspace-and-state.md). |
| 2026-06-12 | **`/review-code` is removed.** The `code-verifier` performs the changeset-level review inside `/code`; the review/remediation loop is internal to `/code`. Supersedes the three earlier review decisions below. See [03-skills.md](03-skills.md). |
| 2026-06-12 | `/acs` umbrella command added: runs `/create-ticket` → `/create-spec` → `/code` → `/create-pr` end-to-end, stopping before the user-invoked `/merge-pr`. *(Amended by the design-phase decision above: `/create-design` now runs conditionally between `/create-ticket` and `/create-spec`.)* See [02-workflow.md](02-workflow.md). |
| 2026-06-12 | Epic status lifecycle: **In Progress** when work starts on any child, **Done** when all children are merged. See [02-workflow.md](02-workflow.md). |
| 2026-06-12 | Tracker pulls are **on-demand** for now; scheduled sync routines are a later enhancement. See [03-skills.md](03-skills.md). |
| 2026-06-12 | Reflection/remediation iteration cap confirmed: **3**. See [04-architecture.md](04-architecture.md). |
| 2026-06-12 | `/merge-pr` readiness failure is **report-only** — it never routes fixes back to `/code` automatically. See [03-skills.md](03-skills.md). |
| 2026-06-12 | *(superseded)* The review → code feedback loop is automatic: blocking findings re-enter `/code` until the review passes — the loop is now internal to `/code`. |
| 2026-06-12 | `/merge-pr` is a **user action**: invoked explicitly after the user has reviewed the PR themselves; the pipeline never triggers it. See [03-skills.md](03-skills.md). |
| 2026-06-12 | Epics auto-complete when all child tickets are merged. See [02-workflow.md](02-workflow.md). |
| 2026-06-12 | Tracker sync is **two-way**; `ticket.json` holds the local-id ↔ remote-key mapping (e.g. Jira key); access via the `gh` CLI (GitHub) and `acli` (Jira). See [06-configuration.md](06-configuration.md). |
| 2026-06-12 | `<repo>` partition identity derives from the git remote, so all worktrees of a repo share one partition. See [07-workspace-and-state.md](07-workspace-and-state.md). |
| 2026-06-12 | Branch name format is configurable (`formats.branch_name`, must embed the ticket id); long descriptions (PR, tickets) use **pre-defined templates**. See [06-configuration.md](06-configuration.md). |
| 2026-06-12 | *(superseded)* No duplicated review work: `/review-code` consumes `code-state.json` as trusted input instead of re-running the `code-verifier`'s checks. |
| 2026-06-12 | *(superseded)* `/review-code` stays a separate skill: the `code-verifier` checks spec/TDD conformance (micro), `/review-code` reviews the whole changeset (macro). |
| 2026-06-12 | Epics fan out: `/create-ticket` suggests creating child story/task tickets; each child runs its own pipeline. See [02-workflow.md](02-workflow.md). |
| 2026-06-12 | Tickets are **local-first**; optional sync to a GitHub Project or Jira board, driven by `settings.json`. See [03-skills.md](03-skills.md), [06-configuration.md](06-configuration.md). |
| 2026-06-12 | Workspace is partitioned by repo, then ticket: `<workspace>/<repo>/<ticket-id>/`. See [07-workspace-and-state.md](07-workspace-and-state.md). |
| 2026-06-12 | Ticket id for skills after `/create-ticket`: explicit argument, else detected from session context or branch name. See [02-workflow.md](02-workflow.md). |
| 2026-06-12 | PR title/description, commit message, and per-ticket-type ticket formats are configurable in `settings.json`. See [06-configuration.md](06-configuration.md). |

## Conventions used in these docs

- **MUST / MUST NOT** — a hard requirement.
- **SHOULD** — a strong default; deviation needs a reason.
- **MAY** — optional / nice to have.
- **[OPEN]** — an open question to be resolved before implementation.
- **[ASSUMPTION]** — a proposed interpretation not yet confirmed by the
  product owner; treat as provisional.

## Glossary

| Term | Meaning |
|------|---------|
| **Marketplace** | This repository, published as a Claude Code plugin marketplace. |
| **`acs` plugin** | The first plugin in the marketplace; implements the delivery workflow. |
| **Consumer repo** | Any user repository where the `acs` plugin is installed and used. |
| **Workspace** | A folder *outside* the consumer repo where all skills and hooks read/write state, partitioned per repo and ticket. |
| **Coordinator** | The main agent that orchestrates a skill's subagents. |
| **Subagent** | A planner, executor, or verifier agent spawned by the coordinator for one step of a skill. |
| **Skill state file** | A JSON file (e.g. `code-state.json`) written into the workspace recording a skill's outcome, with an append-only `runs` history. |
| **Pipeline ledger** | `pipeline-state.json` — a compact per-ticket step ledger (status, timestamps, handoff summaries) used by `/ship` and pre-hooks. |
