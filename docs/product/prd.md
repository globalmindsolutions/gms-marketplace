# PRD — GMS Marketplace

> Bootstrapped as the dogfood baseline, derived from the requirements set
> (`docs/requirements/`) and the implemented plugin. Amendments go through
> `/acs:create-prd` re-runs — each amendment is its own delivery ticket and
> docs PR. This PRD covers the GMS Marketplace product and its plugin features
> (acs, tabp, and future plugins); each plugin is a distinct capability delivered
> and updated through one marketplace.

## Vision

The GMS Marketplace is a curated catalog of Global Mind Solution Claude plugins,
each plugin a distinct team capability — coding delivery, talent screening, and
future capabilities — delivered and kept current through one marketplace. Teams
adopt exactly the plugins they need; the marketplace ensures versioning,
discoverability, and consistent quality across all plugins.

The **acs** feature delivers: every software change — from product definition to
merged PR — driven through one auditable, resumable, hook-enforced agentic
pipeline, on any consumer repository, with the human owning exactly two things:
requirement decisions and the merge button.

## Problem

GMS teams need a single curated source of vetted, versioned Claude plugins that
each solve a distinct team problem — coding delivery via acs, talent screening
via tabp — instead of ad-hoc one-off tools with no shared versioning, quality
bar, or discoverability.

**acs feature problem:** Agentic coding today loses state between sessions, skips steps when the model
forgets, mixes planning with implementation in one context, and leaves no
audit trail of what was decided, built, verified, and why. Teams cannot trust
a pipeline whose ordering depends on model goodwill, and cannot resume or
parallelize work that lives in a conversation window.

**tabp feature problem:** Manual CV-vs-JD screening is slow, inconsistent, and hard to audit for
fairness — hiring managers cannot reproduce scoring decisions or demonstrate
that protected characteristics played no role.

## Target users & personas

| Persona | Need |
|---------|------|
| **Solo developer** | Ship features end-to-end with one command (`/acs:ship`), trust the gates instead of self-discipline, resume after any interruption. |
| **Tech lead** | Enforce a delivery process (design gates, TDD, review dimensions, PR size) uniformly across repos and teammates; inspect any ticket's full audit trail. |
| **Team on a shared repo** | Parallel tickets in worktrees without state collisions; team-shared settings; tracker sync to Jira / GitHub Projects. |
| **TABP recruiter / hiring team** | Screen one CV or a batch against a job description in Claude Cowork, receive evidence-based and reproducible Recommend/Hold/Reject recommendations with a downloadable scorecard, and demonstrate fairness to auditors. |

## Goals & success metrics

### acs feature — goals & success metrics

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
| G9 — Enforceable conventions | The configured branch/PR/commit formats are enforceable as a required merge gate on the consumer repo, blocking non-exempt violating PRs even when they bypassed `/acs:create-pr` (escape hatch: the `acs-exempt` label / release-branch allowlist). MAR-9 (PR #50, pending merge) completes the consumer side of that escape hatch: a legitimate non-ticket exempt PR lands via the sanctioned `/acs:merge-pr --pr` path (same readiness + branch/worktree cleanup as the ticket path, no ticket/partition/tracker/archive; it refuses and redirects ticket-backed PRs), and `/acs:init` Step 7e writes an idempotent `CLAUDE.md` acs-managed block that makes the pipeline the *default* for in-repo agent sessions (steering changes through `/acs:ship` rather than ad-hoc PRs). The gate itself is existence-proven by the live required-check ruleset on this repo's own `main` (ruleset 17602044, `active`; "Branch / PR / commit conventions" is a required status-check context). |

### tabp feature — success metrics

| Metric | Measurable success metric |
|--------|---------------------------|
| T1 — Speed | Screen a 20-CV batch ≥ 70% faster than manual screening, measured within 1 month of the feature's first use. |
| T2 — Reproducibility | ≥ 95% reproducible band/recommendation on a fixed 10-CV regression set, per release. |
| T3 — Evidence & auditability | 100% of judgments cite evidence and produce a scorecard, every run — no recommendation without a traceable rationale. |
| T4 — Fairness | 0 protected/proxy criteria used AND 100% of bias-relevant JD requirements flagged, measured on a ≥ 15-pair test set, per release. |
| T5 — Adoption | ≥ 80% of new TABP role openings use screen-cvs within 3 months of the feature's first use. |

## Features (MoSCoW)

The GMS Marketplace currently delivers two plugin features — **acs** and **tabp** —
each prioritized internally via MoSCoW. Future plugins will be added as additional
feature sections here.

### Feature: acs (Autonomous Coding Skills)

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
- Convention enforcement as a required merge gate — `/acs:init` Step 7c scaffolds a repo-side CI check (`.github/workflows/acs-conventions.yml`) backed by a stdlib-only `.acs/ci/check-conventions.py` (fail-closed; modes `pr` / `pre-push` / `commit-msg`) compiled from the configured `formats.*`, plus an `enforcement` settings block (`checks.{branch_name,pr_title,pr_description,acs_label,commit_message}`, `require_label`, `exempt_label` default `acs-exempt`, `exempt_branches`, `pr_description_sections`). Wired as a required status check on the consumer repo, it blocks non-exempt branch/title/description/label/commit-message violations even on PRs that bypassed `/acs:create-pr`; the `acs-exempt` label and a release-branch allowlist are the escape hatch. Observed live on this repo (ruleset 17602044, `active` on `main`; "Branch / PR / commit conventions" is a required context). Traces G9 (+ the Tech-lead persona). **MAR-9 (PR #50, pending merge)** extends this: the exempt PRs the gate lets through then land via a sanctioned merge path — `/acs:merge-pr --pr <n>` (also `#n` / a PR URL) runs the same four readiness dimensions and branch/worktree cleanup as the ticket path but resolves no ticket, writes no partition/state, and skips tracker sync and archiving (bumping only the repo `pr_merged` metric), refusing and redirecting when the PR is actually ticket-backed; and `/acs:init` Step 7e (opt-in, default-on) writes an idempotent, marker-delimited `CLAUDE.md` acs-managed block (rendered from `templates/CLAUDE.acs.md`) that steers in-repo Claude sessions to ship via `/acs:ship` instead of a raw `gh pr create`, making the pipeline the default rather than only the gate.
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

**Won't have (now)** *(acs feature scope)*
- Non-GitHub forges (GitLab/Bitbucket); non-Claude-Code runtimes for the acs pipeline.

### Feature: tabp (recruiting/talent toolkit for the TABP team — screen-cvs)

Runs in **Claude Cowork** (not Claude Code). This feature targets Cowork skills format.

**Must have** *(urgent — next delivery)*
- **screen-cvs** — screen one CV or a batch against a job description; parse the JD
  into must-have vs nice-to-have requirements; produce evidence-based Met/Partial/Missing
  per requirement; compute a weighted 0–100 match score where missing a must-have
  requirement caps the result; assign a Strong/Moderate/Weak band with a
  Recommend/Hold/Reject recommendation; output an inline summary and a two-sheet Excel
  scorecard; apply fairness guardrails (job-relevant criteria only, decision-support
  framing); batch screening fans out one Sonnet subagent per CV with Opus synthesis;
  inputs read from the Cowork project folder, falling back to chat attachments.
  Traces T1, T2, T3, T4, T5.

**Won't have (now)** *(tabp feature scope)*
- Integrations with ATS platforms; automated hiring decisions (screen-cvs is
  decision-support only, not a hiring authority); Claude Code runtime (tabp targets
  Claude Cowork).

## Product-level NFRs

These NFRs apply across all marketplace features. Each feature realizes them through
its own mechanisms (acs via stdlib Python + hooks; tabp via Cowork skills format).

- **Determinism where possible**: ordering, gating, state writes, id allocation are scripts, never prose; gates fail closed.
- **Portability**: hooks and helpers are stdlib-only Python ≥ 3.9; no network dependencies of their own. `/acs:init` Step 0b runs a toolchain preflight — it detects and offers to install the tools acs leans on (`git`, `python3`, `gh`, `pre-commit`, `xmllint`, `acli`) so onboarding fails up front with consent rather than mid-pipeline; the convention checker stays stdlib-only so no acs install is needed on the CI runner.
- **Auditability**: every state file human-readable (pretty JSON), append-only run history, archived not deleted.
- **Safety**: no secrets in settings (CLIs own auth); locks prevent cross-session corruption; stale locks reported, never stolen.
- **Cost transparency**: tokens/cost/time per run, rolled up per ticket and repo.

## Constraints & assumptions

- **acs feature:** Claude Code plugin API (skills/agents/hooks as documented) is the runtime for the acs pipeline. Different features may target different Claude runtimes — acs targets Claude Code; tabp targets Claude Cowork.
- Delivery is git + GitHub PRs (`gh` assumed); correctness must be checkable by automated tests for the strong-fit domains (see `docs/requirements/overview.md`).
- Subagents cannot interact with the user — all user interaction happens in coordinators (drives the `needs_input` handoff design).
- **tabp feature:** screen-cvs runs in Claude Cowork; inputs are read from the Cowork project folder, falling back to chat attachments; batch screening uses one Sonnet subagent per CV with Opus synthesis; outputs include a two-sheet Excel scorecard.

## Out of scope

Visual/UX-judged work without an automatable test strategy, hardware-in-the-loop
testing, model training pipelines, registry distribution beyond the GitHub URL.

Per-plugin separate PRDs and per-plugin acs configuration are out of scope — this
single `prd.md` covers the GMS Marketplace product and all its plugin features. The
MAR-17 restructure (separate per-plugin PRDs) was abandoned. The tabp plugin
implementation (plugin.json, screen-cvs skill, marketplace.json entry, CI
version-coupling removal) is a separate follow-up ticket — this PRD defines the
feature; the build is out of scope here.
