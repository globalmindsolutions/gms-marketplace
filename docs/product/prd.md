# PRD — acs (Autonomous Coding Skills)

> Bootstrapped as the dogfood baseline, derived from the requirements set
> (`docs/requirements/`) and the implemented plugin. Amendments go through
> `/acs:create-prd` re-runs — each amendment is its own delivery ticket and
> docs PR.

## Vision

Every software change — from product definition to merged PR — driven through
one auditable, resumable, hook-enforced agentic pipeline, on any consumer
repository, with the human owning exactly two things: requirement decisions
and the merge button.

## Problem

Agentic coding today loses state between sessions, skips steps when the model
forgets, mixes planning with implementation in one context, and leaves no
audit trail of what was decided, built, verified, and why. Teams cannot trust
a pipeline whose ordering depends on model goodwill, and cannot resume or
parallelize work that lives in a conversation window.

## Target users & personas

| Persona | Need |
|---------|------|
| **Solo developer** | Ship features end-to-end with one command (`/acs:ship`), trust the gates instead of self-discipline, resume after any interruption. |
| **Tech lead** | Enforce a delivery process (design gates, TDD, review dimensions, PR size) uniformly across repos and teammates; inspect any ticket's full audit trail. |
| **Team on a shared repo** | Parallel tickets in worktrees without state collisions; team-shared settings; tracker sync to Jira / GitHub Projects. |

## Goals & success metrics

| Goal | Measurable success metric |
|------|---------------------------|
| G1 — Gated pipeline integrity | 0 instances of a skill running with an unmet predecessor (gate escapes); every blocked attempt produces an actionable message. First validated 2026-06-13 (acs v0.1.2, M2-0 spike): 0 gate escapes; gate advanced exactly one step at each of init → create-ticket → create-spec → code → create-pr. |
| G2 — Resumability | 100% of interrupted/handed-off tickets resumable from workspace state alone in a fresh session (no conversation history needed). First validated 2026-06-13 (acs v0.1.2, M2-0 spike): resumed from the code step in a fresh session using workspace state alone. |
| G3 — Quality via reflection | ≥ 90% of `/code` runs reach zero verifier findings within the 3-iteration cap; coverage target met or hard-failed (never silently waived). |
| G4 — Reviewable delivery | ≥ 80% of story/task PRs ≤ ~400 changed lines; every PR carries ticket trace, test plan, and findings. |
| G5 — Auditability | Every decision (clarification, assumption, finding, phase output) recoverable from the ticket partition; cost/tokens/time recorded per run, ticket, and repo. First measured 2026-06-13 (acs v0.1.2, M2-0 spike, 5 runs): ~$2.43 total, ~385k in / ~72k out tokens, ~1770 working-seconds, all recoverable from the partition. |
| G6 — Portability | Works on any git repo with `python3` + `gh`; zero pip installs; one `/acs:init` to onboard. First validated 2026-06-13 (acs v0.1.2, M2-0 spike): clean install + `/acs:init` in a throwaway repo, no Duplicate-hooks load failure. |
| G7 — Observability | Dashboard renders all 6 panels (throughput, pipeline funnel, cost/time per step, coverage vs target, review iterations, token burn by role) in ≤ 5 s for ≤ 50 tickets; reads only workspace artifacts; requires no network calls and no new config beyond `.acs/settings.json`. In-session status lines, when wired, preserve 100% of Claude Code's default status-line fields and add acs state on top (zero default fields lost), render in < 100 ms per refresh, and never crash — any failure falls back to a valid line. |
| G8 — Skill quality coverage | Structure, gating, and routing covered for 100% of skills (free, every PR); every critical-path skill has behavioral (artifact-level) eval coverage; no new skill ships without ≥ a trigger eval (CI guardrail). |
| G9 — Enforceable conventions | The configured branch/PR/commit formats are enforceable as a required merge gate on the consumer repo, blocking non-exempt violating PRs even when they bypassed `/acs:create-pr` (escape hatch: the `acs-exempt` label / release-branch allowlist). MAR-9 (PR #50, pending merge) completes the consumer side of that escape hatch: a legitimate non-ticket exempt PR lands via the sanctioned `/acs:merge-pr --pr` path (same readiness + branch/worktree cleanup as the ticket path, no ticket/partition/tracker/archive; it refuses and redirects ticket-backed PRs), and `/acs:init` Step 7e writes an idempotent `CLAUDE.md` acs-managed block that makes the pipeline the *default* for in-repo agent sessions (steering changes through `/acs:ship` rather than ad-hoc PRs). The gate itself is existence-proven by the live required-check ruleset on this repo's own `main` (ruleset 17602044, `active`; "PR title convention" is a required status-check context). |

## Features (MoSCoW)

**Must have** *(shipped in v0.1)*
- Claude Code plugin marketplace (this repo) with the `acs` plugin.
- 14 skills: `/init`, `/ship`, `/handoff`, `/update`, `/install-hooks`, 3 product-level, 6 workflow.
- Hook-enforced step gating (PreToolUse dispatch, exit-2 blocks, SessionEnd safety net).
- Workspace partitioned by repo/ticket, outside the consumer repo; locks, worktree parallelism.
- Reflection cycle (planner/executor/verifier, 27 agents) with XML messaging (XSD) and phase artifacts.
- TDD `/code` with coverage hard-fail and the 11-dimension changeset review loop (≤ 3 iterations).
- Local-first tickets: epics with child fan-out, per-repo id sequence, archive lifecycle.
- Resume at three levels (gates, `/ship` ledger, mid-skill reconcile) + deliberate handoff.
- Requirement clarification ledger; grounding rules; standard completion reports.
- `acs:metrics` dashboard skill — reads workspace artifacts (`metrics.json`, `tickets-index.json`, per-ticket `pipeline-state.json`, `code-state.json`, `create-pr-state.json`) and renders an interactive HTML dashboard inline in the Claude Code session (`show_widget`) covering: ticket throughput by status/type, pipeline funnel, cost and time per ticket broken down by pipeline step, test coverage achieved vs target, review iterations before verifier passed, and token burn by role (planner/executor/verifier). Read-only; no new file writes; no new config; single-repo scope. Traces G5, G7. *(Must have for M2 exit)*
- Convention enforcement as a required merge gate — `/acs:init` Step 7c scaffolds a repo-side CI check (`.github/workflows/acs-conventions.yml`) backed by a stdlib-only `.acs/ci/check-conventions.py` (fail-closed; modes `pr` / `pre-push` / `commit-msg`) compiled from the configured `formats.*`, plus an `enforcement` settings block (`checks.{branch_name,pr_title,pr_description,acs_label,commit_message}`, `require_label`, `exempt_label` default `acs-exempt`, `exempt_branches`, `pr_description_sections`). Wired as a required status check on the consumer repo, it blocks non-exempt branch/title/description/label/commit-message violations even on PRs that bypassed `/acs:create-pr`; the `acs-exempt` label and a release-branch allowlist are the escape hatch. Observed live on this repo (ruleset 17602044, `active` on `main`; "PR title convention" is a required context). Traces G9 (+ the Tech-lead persona). **MAR-9 (PR #50, pending merge)** extends this: the exempt PRs the gate lets through then land via a sanctioned merge path — `/acs:merge-pr --pr <n>` (also `#n` / a PR URL) runs the same four readiness dimensions and branch/worktree cleanup as the ticket path but resolves no ticket, writes no partition/state, and skips tracker sync and archiving (bumping only the repo `pr_merged` metric), refusing and redirecting when the PR is actually ticket-backed; and `/acs:init` Step 7e (opt-in, default-on) writes an idempotent, marker-delimited `CLAUDE.md` acs-managed block (rendered from `templates/CLAUDE.acs.md`) that steers in-repo Claude sessions to ship via `/acs:ship` instead of a raw `gh pr create`, making the pipeline the default rather than only the gate.
- `/acs:install-hooks` skill — the `pre-commit install` equivalent for acs (per-clone, user-invoked): installs the config-driven local git hooks (`commit-msg` + `pre-push`) that run the same `check-conventions.py` before a commit or push leaves the machine. A committed `.acs/ci/install-hooks.sh` lets teammates run it without the plugin. Traces G9 (+ the Tech-lead persona).

**Should have** *(shipped in v0.1, maturing)*
- Two-way tracker sync (GitHub Projects / Jira via `gh` / `acli`), remote import.
- Configured e2e test layer; `docs_only` fast-path; PR-size control with ticket splitting.
- Per-role model/effort configuration for the planner/executor/verifier subagents.
- Status lines layer acs state onto Claude Code's defaults, never replacing them — both the prompt line and the reflection agent-panel compose with Claude Code's default rendering and add acs context on top: the **prompt** line surfaces the default's standard context (model, cwd, git branch, context-left, output style) **plus** acs pipeline state (active ticket, step glyphs, cost, lock); the **agent panel** keeps every non-acs row at its Claude Code default and enriches the recognized reflection-subagent rows with acs state (phase, role, ticket, tokens, elapsed), with room to surface more acs-relevant fields. *(Traces G7.)*
- Behavioral eval harness for skills: free contract/gate smoke (pre-commit + CI) + paid agentic evals as a pre-release gate. *(Delivered in M2, Epic E1. Traces G8.)*

**Could have**
- Scheduled background tracker sync; cross-machine handoff (shared workspace); additional description templates.
- acs maintains the `quality/` and `operations/` doc sets for consumers (test strategy + release/ops runbooks) via `/acs:create-quality` and `/acs:create-operations`, plus `/acs:test` — a schedulable regression runner that triages failures and opens a ticket per regression (closed loop). *(Proposed — see [ADR 0011](../adr/0011-sdlc-doc-sets-quality-and-operations.md).)*

**Won't have (now)**
- Non-GitHub forges (GitLab/Bitbucket); non-Claude-Code runtimes; plugins other than `acs`.

## Product-level NFRs

- **Determinism where possible**: ordering, gating, state writes, id allocation are scripts, never prose; gates fail closed.
- **Portability**: hooks and helpers are stdlib-only Python ≥ 3.9; no network dependencies of their own. `/acs:init` Step 0b runs a toolchain preflight — it detects and offers to install the tools acs leans on (`git`, `python3`, `gh`, `pre-commit`, `xmllint`, `acli`) so onboarding fails up front with consent rather than mid-pipeline; the convention checker stays stdlib-only so no acs install is needed on the CI runner.
- **Auditability**: every state file human-readable (pretty JSON), append-only run history, archived not deleted.
- **Safety**: no secrets in settings (CLIs own auth); locks prevent cross-session corruption; stale locks reported, never stolen.
- **Cost transparency**: tokens/cost/time per run, rolled up per ticket and repo.

## Constraints & assumptions

- Claude Code plugin API (skills/agents/hooks as documented) is the only runtime.
- Delivery is git + GitHub PRs (`gh` assumed); correctness must be checkable by automated tests for the strong-fit domains (see `docs/requirements/overview.md`).
- Subagents cannot interact with the user — all user interaction happens in coordinators (drives the `needs_input` handoff design).

## Out of scope

Visual/UX-judged work without an automatable test strategy, hardware-in-the-loop
testing, model training pipelines, registry distribution beyond the GitHub URL.
