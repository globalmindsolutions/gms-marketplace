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
pipeline, on any consumer repository, with the human owning **requirement
decisions**. Merge is **gated, not ungoverned**: `/acs:merge-pr` is invocable by the
user *or* an authorized agent/model, and a merge happens only when the readiness gate
(CI, approvals, conflicts, protections) **and** the repo's branch protection pass, by
whoever invokes — failures are report-only and every attempt is audited;
agent-invoked merges additionally require an **approved** review. `/acs:ship` still
deliberately stops at create-pr so a reviewer sees the PR before merge. acs **meets
teams where they are**: when a team has no PRD/roadmap/architecture and its PO works
only in a remote tracker, the pipeline runs **tracker-first** — the tracker issue
(description + acceptance criteria) governs as the requirement source of truth and the
**same gates** (TDD, coverage, review, audit, merge readiness) still apply; no PRD is
required to deliver, and none is ever auto-authored without opt-in.

## Problem

GMS teams need a single curated source of vetted, versioned Claude plugins that
each solve a distinct team problem — coding delivery via acs, talent screening
via tabp — instead of ad-hoc one-off tools with no shared versioning, quality
bar, or discoverability.

**acs feature problem:** Agentic coding today loses state between sessions, skips steps when the model
forgets, mixes planning with implementation in one context, and leaves no
audit trail of what was decided, built, verified, and why. Teams cannot trust
a pipeline whose ordering depends on model goodwill, and cannot resume or
parallelize work that lives in a conversation window. Many teams, moreover,
never produce a PRD/roadmap/architecture at all — their PO authors requirements
only in a remote tracker (e.g. Jira) and may not know how to create the upstream
docs. A pipeline that **requires** a PRD to start locks those teams out; they
need to deliver tracker-defined work through the same gates without first
authoring product docs they do not have.

Today the pipeline runs the full plan-execute-verify ladder (create-ticket →
[create-design] → create-spec → code → create-pr → merge-pr) on **every** ticket
regardless of size. An over-engineering audit found that a trivial one-line ticket
pays ~5 coordinators + ~15 subagent spawns (~20 fresh model contexts), so simple,
supervised changes cost disproportionate wall-clock time and token/cost. The rigor
that is the product is right for unattended and complex work, but is double-paid on
interactive simple work where a human is already the reviewer. Rigor is scaled today
by design-significance (the `needs_design` flag) but never by implementation size or
supervision level.

**tabp feature problem:** Manual CV-vs-JD screening is slow, inconsistent, and hard to audit for
fairness — hiring managers cannot reproduce scoring decisions or demonstrate
that protected characteristics played no role.

## Target users & personas

| Persona | Need |
|---------|------|
| **Solo developer** | Ship features end-to-end with one command (`/acs:ship`), trust the gates instead of self-discipline, resume after any interruption. |
| **Tech lead** | Enforce a delivery process (design gates, TDD, review dimensions, PR size) uniformly across repos and teammates; inspect any ticket's full audit trail. |
| **Team on a shared repo** | Parallel tickets in worktrees without state collisions; team-shared settings; tracker sync to Jira / GitHub Projects. |
| **Team with a tracker-only PO** | Deliver requirements that live only in a remote tracker (Jira), with no PRD/roadmap/architecture and no need to author one — the tracker issue governs, and the full gated pipeline (TDD, coverage, review, audit) still applies. |
| **TABP recruiter / hiring team** | Screen one CV or a batch against a job description in Claude Cowork or Claude Code, receive evidence-based and reproducible Recommend/Hold/Reject recommendations with a downloadable scorecard, and demonstrate fairness to auditors. |
| **Org / Platform admin (Security/Compliance owner)** | Apply organization-wide enforcement policy — required convention checks, security gates, standards/conventions floors — across *all* of the org's repos from one place; guarantee repos cannot silently loosen or self-exempt from a mandate; see which layer each effective rule came from and who can change it (provenance/audit). |

## Goals & success metrics

### acs feature — goals & success metrics

| Goal | Measurable success metric |
|------|---------------------------|
| G1 — Gated pipeline integrity | 0 instances of a skill running with an unmet predecessor (gate escapes); every blocked attempt produces an actionable message. First validated 2026-06-13 (acs v0.1.2, M2-0 spike): 0 gate escapes; gate advanced exactly one step at each of init → create-ticket → create-spec → code → create-pr. |
| G2 — Resumability | 100% of interrupted/handed-off tickets resumable from workspace state alone in a fresh session (no conversation history needed). First validated 2026-06-13 (acs v0.1.2, M2-0 spike): resumed from the code step in a fresh session using workspace state alone. |
| G3 — Quality via reflection | ≥ 90% of `/code` runs reach zero verifier findings within the 3-iteration cap; coverage target met or hard-failed (never silently waived). |
| G4 — Reviewable delivery | ≥ 80% of story/task PRs ≤ ~400 changed lines; every PR carries ticket trace, test plan, and findings. |
| G5 — Auditability | Every decision (clarification, assumption, finding, phase output) recoverable from the ticket partition; cost/tokens/time recorded per run, ticket, and repo. First measured 2026-06-13 (acs v0.1.2, M2-0 spike, 5 runs): ~$2.43 total, ~385k in / ~72k out tokens, ~1770 working-seconds, all recoverable from the partition. |
| G6 — Portability | Works on any git repo with `python3` + `gh`; zero pip installs; one `/acs:init` to onboard. First validated 2026-06-13 (acs v0.1.2, M2-0 spike): clean install + `/acs:init` in a throwaway repo, no Duplicate-hooks load failure. Each acs doc set (`prd`, `architecture`, `requirements`, `adr`, and future `standards`/`principles`/`quality`/`operations`) is independently relocatable to an external/absolute filesystem path via configuration; 100% of producer-skill runs preserve the per-backend reviewability + Git-audit guarantee (local/external-local = reviewable diff / repo PR; remote = backend-native review); 0 doc-set writes bypass the configured backend review path; measured per release. The acs pipeline is **runtime-portable**: the same gated pipeline (gating, TDD, coverage hard-fail, 11-dimension review, audit) runs on **≥ 2 supported runtimes** (Claude Code today + OpenAI Codex CLI), with **0 gate escapes and 0 lost audit-trail artifacts** on a published end-to-end run on the second runtime, **validated within 1 release of the Codex CLI runtime capability shipping** (mirrors how G1/G2/G6 were first validated by the M2-0 spike). |
| G7 — Observability | Dashboard renders all 6 panels (throughput, pipeline funnel, cost/time per step, coverage vs target, review iterations, token burn by role) in ≤ 5 s for ≤ 50 tickets; reads only workspace artifacts; requires no network calls and no new config beyond `.acs/settings.json`. In-session status lines, when wired, preserve 100% of Claude Code's default status-line fields and add acs state on top (zero default fields lost), render in < 100 ms per refresh, and never crash — any failure falls back to a valid line. |
| G8 — Skill quality coverage | Structure, gating, and routing covered for 100% of skills (free, every PR); every critical-path skill has behavioral (artifact-level) eval coverage; no new skill ships without ≥ a trigger eval (CI guardrail). |
| G9 — Enforceable conventions | The configured branch/PR/commit formats are enforceable as a required merge gate on the consumer repo, blocking non-exempt violating PRs even when they bypassed `/acs:create-pr` (escape hatch: the `acs-exempt` label / release-branch allowlist). MAR-9 (PR #50, pending merge) completes the consumer side of that escape hatch: a legitimate non-ticket exempt PR lands via the sanctioned `/acs:merge-pr --pr` path (same readiness + branch/worktree cleanup as the ticket path, no ticket/partition/tracker/archive; it refuses and redirects ticket-backed PRs), and `/acs:init` Step 7e writes an idempotent `CLAUDE.md` acs-managed block that makes the pipeline the *default* for in-repo agent sessions (steering changes through `/acs:ship` rather than ad-hoc PRs). The gate itself is existence-proven by the live required-check ruleset on this repo's own `main` (ruleset 17602044, `active`; "Branch / PR / commit conventions" is a required status-check context). |
| G10 — Standards conformance & repo standardization | New design/code conforms to the principles + standards doc sets, verifier-checked: **100% of `/code` runs whose changeset touches a standards-governed area produce zero unwaived standards-conformance findings** (a violation is a blocking finding, never a silent pass), measured per release on the dogfood repo. Brownfield onboarding is additive and reviewable: **`/acs:standardize-project` lands its setup as exactly one reviewed PR that adds only docs/config/tooling and moves or renames zero existing source files** (0 source relocations; verified by the PR diff), with every target-layout structural gap emitted as a recommended follow-up ticket rather than an in-place move. |
| G11 — Tracker-first delivery / graceful degradation | A repo with **no PRD/architecture** delivers a remote-tracker-defined ticket end-to-end through the **same gates** (TDD, coverage hard-fail, 11-dimension review, audit, merge readiness) with **zero gate escapes** and **zero "missing PRD" hard-blocks** — the absent upstream artifact makes only its own trace step N/A, never blocking the run. Target: **100% of tracker-first runs (PRD absent) complete without a missing-upstream hard-block AND with 0 gate escapes**, validated on **≥ 1 real PRD-less repo within 1 release of the capability shipping**; tracker-issue acceptance criteria are carried into the spec for **100%** of such runs. |
| G12 — Org-level enforceable policy | An organization can define enforcement policy (required convention checks, security gates, standards/conventions floors) once and have it apply as a **non-overridable floor** across all its repos, with repos able to tighten but not loosen it, exemptions granted only at the org layer, and every effective rule traceable to the layer it came from. **Measurable success metric:** on a pilot org of **≥ 3 repos**, **100% of those repos enforce the org-mandated convention/security checks as required status checks with 0 repo-level self-exemptions of a mandated rule**, and a deliberately non-conforming PR in any pilot repo is **blocked from merge** — first validated within **1 release** of the org-policy capability shipping (mirrors how G1/G9 are validated by an observed live gate, e.g. ruleset 17602044, prd.md). |
| G13 — Enforceable e2e integrity | When the optional e2e merge gate is enabled on a consumer repo, **0 PRs merge with a red e2e suite** (the required e2e status check is a fail-closed merge brake, symmetric to the G9 convention gate and the G3 coverage hard-fail), AND **100% of specs whose changeset touches a user-facing / cross-component surface declare e2e impact** (the spec's Test plan states e2e impact or an explicit "no e2e impact" reason — the code-verifier blocks any declared-impact spec lacking matching e2e test diffs; no zero-findings verdict without a green e2e run). The opt-in invariant holds: a repo with `settings.e2e` unset has no e2e suite and no e2e gate. Measured per release on the dogfood repo (gate-enabled repos). Traces the Tech-lead persona. |
| G14 — Complexity-adaptive delivery efficiency | A trivial, human-supervised ticket is delivered for substantially less wall-clock time and token/cost than the full pipeline. **Metric:** median wall-clock time AND median token/cost for a trivial-tier ticket are each reduced **≥ 60%** vs the same ticket run through the full plan-execute-verify ladder, measured on the dogfood repo within **1 release** of the capability shipping. |
| G15 — Fast-lane adoption | A meaningful share of tickets flow through the trivial/standard fast lanes rather than the full ladder. **Metric:** **≥ 50%** of delivered tickets use the trivial- or standard-tier fast lane (vs the full complex/unattended ladder), measured per release on the dogfood repo once the tiers ship. |
| G16 — Rigor preserved where it matters (no regression) | Reducing process on simple/supervised work must not lower defect-catch on the work that keeps the verifier. **Metric:** **0 regression** in the code verifier's defect-catch rate — the TDD/coverage gate's hard-fail behavior and the 11-dimension review on standard/complex tiers stay 100% in force; measured by the existing eval harness (E1) showing no drop in verifier-caught findings per release vs the pre-feature baseline. |

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
- **Tracker-first delivery (PRD-optional mode)** — a **configurable governance mode**
  so a team with no PRD/roadmap/architecture can deliver requirements that live only
  in a remote tracker (GitHub Projects / Jira) through the **same gated pipeline**.
  When upstream product docs are **absent**, the imported tracker issue (description +
  acceptance criteria) is the **requirement source of truth**; the conformance chain
  **degrades gracefully** — a missing upstream artifact makes only its own trace step
  **N/A**, never a hard block — while TDD, coverage hard-fail, the 11-dimension review,
  audit trail, and merge readiness are **unchanged**. Builds on the existing
  `/acs:create-ticket <remote-key>` import + two-way tracker sync (Should-have, above;
  `gh`/`acli`). **Divergence (C-3):** with **no PRD present**, tracing is N/A and the
  tracker ticket governs (nothing to flag); with a **PRD present**, today's behavior
  is kept — trace, flag divergence, user decides. This is **graceful degradation of
  the existing pipeline, not a parallel workflow**, and acs **never auto-authors a PRD
  without opt-in** (see Constraints). Traces **G11** (+ the Team-with-a-tracker-only-PO
  persona). *(Must have — urgent; see roadmap E6.)* The mechanism (config key name,
  explicit opt-in vs auto-detect, design-step optionality) is **deferred to the
  tracker-first epic's design phase** — this PRD states the requirement (what).
- **Complexity-adaptive delivery** — acs scales the amount of process/structure it
  applies to a ticket based on the ticket's **complexity** AND the level of **human
  supervision**, instead of running the full plan-execute-verify ladder on every
  ticket. **Framing principle:** adopt the host tool (Claude Code)'s own adaptivity
  rather than re-implement a heavier always-on version — Claude Code uses Plan mode
  for complex tasks (skipped for simple) with human approval as the verification gate,
  plus on-demand verification (`/verify`, `/code-review`, tests in-loop), never a
  mandatory independent verifier on every task; acs's automated verifier is a
  **stand-in for the absent human reviewer in unattended runs**, so applying it to
  every interactive simple ticket double-pays. Three delivery tiers:
  1. **TRIVIAL** (small change, human supervising interactively) — single agent loop
     draft → edit → human approves; no standalone create-spec, no separate planner
     subagent, no automated verifier subagent.
  2. **STANDARD** (normal story) — create-spec fused into code (collapse the
     create-spec/code-planner double-planning); exactly **ONE** independent verify
     pass retained on code (the load-bearing TDD/coverage gate); apply-tier skills
     (create-pr, merge-pr, create-ticket) run inline (coordinator + single executor),
     not a full triad.
  3. **COMPLEX / UNATTENDED** (epic, design-significant, or `/acs:ship` autonomous
     run) — the full ladder exactly as today; the independent verifier legitimately
     substitutes for the absent human and the persisted artifacts are the audit trail;
     preserves the rigor that is the product.

  The tier is set once, user-confirmed, at create-ticket, alongside the existing
  `needs_design` flag and following that precedent; default is full/standard rigor;
  lighter tiers are opt-in. Traces **G14, G15, G16**.

**Should have** *(shipped in v0.1, maturing)*
- Two-way tracker sync (GitHub Projects / Jira via `gh` / `acli`), remote import.
- **Configured e2e test layer with an optional enforceable merge gate** — the opt-in `settings.e2e` layer ships today (`command` + optional `setup`/`teardown`, `per_iteration`; unset = no e2e suite): `/acs:create-spec` test plans declare e2e impact, `/acs:code` authors/runs affected e2e tests in the same changeset, and the code-verifier runs the FULL suite (no green run, no zero-findings verdict). **New:** `/acs:init` can scaffold a repo-side e2e CI workflow + runner and wire it as a REQUIRED status check on the consumer repo (opt-in, fail-closed), so a red e2e blocks PR merge — symmetric to the G9 convention gate and the G3 coverage hard-fail, and making the today-report-only `/acs:merge-pr` CI read ENFORCEABLE via branch protection. Traces G13, G9. *(The opt-in invariant is preserved: no `settings.e2e`, no e2e suite and no gate.)*
- `docs_only` fast-path; PR-size control with ticket splitting.
- Per-role model/effort configuration for the planner/executor/verifier subagents.
- Status lines layer acs state onto Claude Code's defaults, never replacing them — both the prompt line and the reflection agent-panel compose with Claude Code's default rendering and add acs context on top: the **prompt** line surfaces the default's standard context (model, cwd, git branch, context-left, output style) **plus** acs pipeline state (active ticket, step glyphs, cost, lock); the **agent panel** keeps every non-acs row at its Claude Code default and enriches the recognized reflection-subagent rows with acs state (phase, role, ticket, tokens, elapsed), with room to surface more acs-relevant fields. *(Traces G7.)*
- Behavioral eval harness for skills: free contract/gate smoke (pre-commit + CI) + paid agentic evals as a pre-release gate. *(Delivered in M2, Epic E1. Traces G8.)*

**Could have**
- Scheduled background tracker sync; cross-machine handoff (shared workspace); additional description templates.
- acs maintains the `quality/` and `operations/` doc sets for consumers (test strategy + release/ops runbooks) via `/acs:create-quality` and `/acs:create-operations`, plus `/acs:test` — a schedulable regression runner that triages failures and opens a ticket per regression (closed loop). *(Proposed — see [ADR 0011](../adr/0011-sdlc-doc-sets-quality-and-operations.md).)*
- **acs maintains the `principles/` and `standards/` doc sets for consumers** — engineering principles (e.g. `/acs:create-principles` → `principles/`) and coding standards/conventions (e.g. `/acs:create-standards` → `standards/`), each a product-level producer skill with its own planner/executor/verifier triad and acs-shipped templates, following the one-skill-per-set pattern of `/acs:create-architecture` and the proposed `/acs:create-quality` / `/acs:create-operations` (see [ADR 0011](../adr/0011-sdlc-doc-sets-quality-and-operations.md)). These sets sit between architecture and design in the conformance chain: **PRD → architecture → standards → design → specs → code**, each level verified against the one above it. Design and code MUST conform to the standards docs; the `/code` `code-verifier`'s technical-standards dimension and the design verifiers check conformance and block violations (no silent waivers). Traces G10 (+ the Tech-lead persona). *(Proposed — extends the chain at workflow.md and docs/README; see Constraints.)*
- **Architecture doc set gains an explicit project-structure target** — the `/acs:create-architecture` output set adds a project-structure document (the intended repo layout, derived from the C4 container/component views) as the canonical target a repo is expected to match. It is the layout `/acs:standardize-project` audits an existing repo against. Traces G10.
- **`/acs:standardize-project` — brownfield standardization (separate from `/acs:create-project`, which stays greenfield-only)** — audits an EXISTING repo against its principles + standards doc sets, the architecture project-structure target, and acs-readiness tooling (coverage/CI/pre-commit/e2e harness — scaffolding a repo-side e2e CI workflow + runner and, opt-in, wiring it as a required e2e merge-gate status check for an EXISTING repo that lacks one, the brownfield counterpart to greenfield-only `/acs:create-project`), then **additively** sets up the missing docs/config/tooling as **one reviewed PR**. It NEVER moves or renames existing source; structural gaps versus the target layout become **recommended follow-up tickets**, not in-place moves. Traces G10, G13 (+ the Tech-lead persona). *(Proposed; additive-only — see the C-2 guardrail in Constraints & assumptions.)*
- **Configurable doc-set storage location (external/local paths)** — each acs doc set's path is independently configurable and may point to an absolute/external path outside the consumer repo (not only repo-relative); generalizes the `prd_path`, `architecture_path`, `requirements_path`, `adr_path`, and future `standards_path`/`principles_path`/`quality_path`/`operations_path` keys under one doc-set storage-location config surface; producer skills resolve the configured location and preserve a reviewable diff there. This is the committed near-term deliverable. Traces extended G6.
- **Pluggable remote docs backend (Notion)** — mirrors the existing `tracker.provider` precedent (`local` filesystem default + `notion` as the first remote provider); supports BOTH modes per backend: (1) **publish/mirror** — repo stays source of truth, the docs-only PR is preserved, content synced to Notion for reading; (2) **authoritative-remote** — Notion is the system of record, no repo copy, review/audit happens in Notion. The **MECHANISM** — Notion API/auth, markdown→Notion-blocks mapping, PR-less vs sync delivery, per-mode review/audit — is **deferred to a dedicated future Notion/remote-docs epic's design phase**, mirroring how this PRD defers tabp's mechanism. Auth via external CLI/integration; no secrets in settings (mirrors the `tracker.provider` precedent and the Safety NFR). Traces extended G6.
- **Opt-in reverse-bootstrap from tracker + codebase** — an **opt-in** growth path
  that seeds a baseline `prd.md`/architecture by reverse-engineering from imported
  tracker issues plus the existing codebase, giving a tracker-only team a starting
  product-doc set **only when they ask for it**. Never automatic; tracker-first
  delivery works **without** it. Traces **G11**. *(Proposed; opt-in only — see the
  C-5 guardrail in Constraints & assumptions.)*
- **Org-level enforcement policy (organization & department layers).** acs gains an
  ordered **policy-source chain** above today's user + team(project) layers so an
  organization (and, optionally, a department/sub-group) can define both **shared
  defaults** (overridable convenience config — doc paths, models, tracker, formats:
  resolved most-specific-wins, extending the existing cascade) and **enforcement
  mandates** (non-overridable floors — required convention/security/standards checks:
  a repo may tighten but never loosen, may not self-exempt, and exemptions are granted
  only at the org layer, time-boxed and audited). Because a CI gate sees only the
  checked-out repo and the cascade is most-specific-wins, the enforceable part **cannot
  live in a developer-home or repo-editable file** — it must come from an org-controlled,
  non-overridable source and/or inverted floor precedence, and every effective rule
  exposes its **provenance** (which layer, who may change it). Adding the layers is
  **additive and non-breaking**: with no org source configured, resolution is identical
  to today. Connects to G10 (when the standards doc layer ships, org policy can mandate
  conformance as a floor). Traces **G12** (+ the new Org/Platform-admin persona).
  *(Proposed — the MECHANISM (cascade extension vs GitHub org rulesets / org-required
  workflows vs a versioned policy pack the repo cannot edit; the non-overridable mandate
  encoding) is deferred to a future design epic / ADR, per Constraints.)*

- **Multi-runtime support — OpenAI Codex CLI as an acs pipeline runtime** — the acs
  gated pipeline (ordering/gating, TDD, coverage hard-fail, the 11-dimension review
  loop, resumable workspace state, audit trail, merge readiness) becomes runnable on
  **OpenAI Codex CLI** in addition to Claude Code, so a team standardized on Codex CLI
  can adopt acs without switching agent runtimes. acs stays authored and distributed
  as a Claude plugin; this adds a **second execution runtime for the pipeline**, not a
  second product. The **MECHANISM** — how the Claude-Code-specific mechanisms map onto
  Codex CLI (the PreToolUse/SessionEnd hook gating, the planner/executor/verifier
  reflection-subagent protocol, skill/agent dispatch, per-role model/effort config,
  self-reported cost/tokens) and which gates are enforced natively vs via a portable
  shim — is **deferred to a dedicated future multi-runtime epic's design phase**,
  mirroring how this PRD defers the Notion/remote-docs and org-policy mechanisms. The
  deterministic layer is already stdlib-only Python (Portability NFR), which is the
  portable substrate this builds on. Traces **extended G6** (runtime portability).
  *(Proposed — the MECHANISM is deferred to the multi-runtime epic's design phase /
  an ADR, per Constraints. Reverses the prior acs Won't-have — see Reversal note
  (MAR-2) in Out of scope.)*

**Won't have (now)** *(acs feature scope)*
- Non-GitHub forges (GitLab/Bitbucket). *(The former "non-Claude-Code runtimes for the acs pipeline" Won't-have is **reversed by MAR-2** — OpenAI Codex CLI is now a supported pipeline runtime; see the acs Could-have **Multi-runtime support (OpenAI Codex CLI)** feature and the Reversal note (MAR-2) in Out of scope.)*
- Non-Notion remote docs providers (Confluence, Google Docs, SharePoint) — Notion is the only named remote provider; general CMS / doc-graph re-architecture is out of scope; bidirectional Notion→repo editing is out of scope now (authoritative-remote means Notion is the system of record with no repo copy, not a two-way file sync).
- Automatic downgrade of a ticket's complexity/supervision tier without explicit user confirmation — tiers are always user-confirmed; the system never silently reduces rigor.

### Feature: tabp (recruiting/talent toolkit for the TABP team)

Runs in **both Claude Cowork and Claude Code**. tabp is a fuller plugin; screen-cvs is
one capability within it, targeting a project-folder-based workflow. In Claude Code the
project folder need not be a git repo (dual-runtime support driven by MAR-40, per
clarification C-1 on the MAR-36 epic).

**Must have** *(urgent — next delivery)*
- **screen-cvs** — screen one CV or a batch against a job description; parse the JD
  into must-have vs nice-to-have requirements; produce evidence-based Met/Partial/Missing
  per requirement; compute a weighted 0–100 match score where missing a must-have
  requirement caps the result; assign a Strong/Moderate/Weak band with a
  Recommend/Hold/Reject recommendation; output an inline summary and a two-sheet Excel
  scorecard; apply fairness guardrails (job-relevant criteria only, decision-support
  framing); batch screening fans out one Sonnet subagent per CV with Opus synthesis;
  inputs read from the project folder, falling back to chat attachments.
  Traces T1, T2, T3, T4, T5.
- **tabp settings.json** — configurable models and default CV/JD folder paths; stored
  in the project folder.
- **.tabp/ workspace state** — run history and a per-screening archive (the `.xlsx`
  scorecard and a JSON record per run); persisted in the project folder.
- **/tabp:usage skill** — surfaces per-run usage metrics: cost, time, and tokens.
- **Resumable runs** — all intermediate states persisted as a human-reviewable audit
  trail; the run can be resumed from the persisted state.
- **Rich Claude artifact** — results rendered as a rich Claude artifact for recruiter
  review; the completed result is presented for recruiter sign-off.

**Namespace rule:** tabp operates in its own namespace and must never use `.acs/` or
`acs:` prefixes. No `acs` token appears in tabp's external surface. The canonical
tabp-namespaced forms are `.tabp/` (workspace state), `tabp settings.json`
(configuration), and `/tabp:usage` (the usage-metrics skill).

**Engineering-rigor NFR (tabp upgrade):** the fuller tabp workflow adopts the same
proven quality patterns in tabp's own namespace:

- **Coordinator-plus-subagents** — the Sonnet-per-CV + Opus-synthesis shape already
  present in screen-cvs continues across the fuller tabp workflow.
- **Reflection/self-verification** — the rubric's own consistency check; tabp presents
  results only after a self-verification step.
- **Structured JSON state** — tabp persists all run state in structured, human-readable
  JSON (in `.tabp/`).
- **Source-grounded evidence / anti-hallucination** — screen-cvs already cites CV
  evidence per requirement; the fuller tabp workflow extends this discipline; tabp
  never invents or assumes evidence the source does not support.
- **Decision recording for human review** — the `.tabp/` audit trail and the
  present-for-review step form the decision record.

The specific mechanisms — message format, the exact reflection loop, hook-gating —
are deferred to the tabp-upgrade epic design phase and verified against what both
runtimes (Claude Cowork and Claude Code) actually support.

**Deferral:** the MECHANISM for the above capabilities — whether instruction-driven,
hook-gated, or another approach — and the verification of what both runtimes (Claude
Cowork and Claude Code) actually support (config resolution, hooks, rich artifacts,
self-reported cost/tokens) are **deferred to the tabp-upgrade epic's design phase**.
This PRD states the requirements (what); the design (how) is determined in the
tabp-upgrade epic.

**Won't have (now)** *(tabp feature scope)*
- Integrations with ATS platforms; automated hiring decisions (tabp is
  decision-support only, not a hiring authority).

## Product-level NFRs

These NFRs apply across all marketplace features. Each feature realizes them through
its own mechanisms (acs via stdlib Python + hooks; tabp via its own plugin patterns).

- **Determinism where possible**: ordering, gating, state writes, id allocation are scripts, never prose; gates fail closed.
- **Portability**: hooks and helpers are stdlib-only Python ≥ 3.9; no network dependencies of their own. `/acs:init` Step 0b runs a toolchain preflight — it detects and offers to install the tools acs leans on (`git`, `python3`, `gh`, `pre-commit`, `xmllint`, `acli`) so onboarding fails up front with consent rather than mid-pipeline; the convention checker stays stdlib-only so no acs install is needed on the CI runner. Runtime coupling is **isolated**: the deterministic layer (gating, state, id allocation, metrics, convention checks) stays runtime-agnostic stdlib-only Python so the acs pipeline can target a second agent runtime (e.g. OpenAI Codex CLI) without rewriting that core; runtime-specific glue (hook dispatch, subagent protocol) is the only part that varies per runtime (mechanism deferred to the multi-runtime epic).
- **Auditability**: every state file human-readable (pretty JSON), append-only run history, archived not deleted.
- **Safety**: no secrets in settings (CLIs own auth); locks prevent cross-session corruption; stale locks reported, never stolen.
- **Cost transparency**: tokens/cost/time per run, rolled up per ticket and repo.
- **Graceful degradation of the conformance chain**: the chain is **PRD (when present)
  → architecture (when present) → standards → design → specs → code**; each present
  level is verified against the present level above it, and a **missing upstream
  artifact makes only its own trace step N/A — never a hard block**. The pipeline's
  gates (ordering, TDD, coverage, review, audit, merge readiness) **fail closed
  regardless** of how many upstream docs exist.
- **Conditional verification (stakes + supervision, not universal)**: the code
  TDD/coverage gate **always** stays regardless of tier; what becomes conditional is
  the **separate independent verifier subagent role** on deterministic / low-stakes /
  supervised work. Gates fail closed — the gate is never the thing dropped; the
  redundant independent reviewer on supervised work is. (Composes with "Graceful
  degradation of the conformance chain" above: conditional verification scales
  *process volume*, the chain's gates still fail closed.)
- **Deterministic apply-tier executors**: apply-tier skills (create-ticket, create-pr,
  merge-pr) have deterministic executors with judgment front-loaded into
  clarification/gates; they do **not** need an iterating plan-execute-verify reflection
  loop. create-ticket's structural checks (schema-completeness, link bidirectionality)
  are a **script check, not an LLM verifier**.
- **Message-validation / per-send performance**: in-process / batched XML message
  validation instead of a `validate_xml.py` subprocess on every send AND receive (a
  simple ticket currently fires ~24–30 subprocess spawns); batch `clarify.py`
  record-before-act calls.

## Constraints & assumptions

- **acs feature (runtime, revised MAR-2):** Claude Code is the **primary / today-shipping** runtime for the acs pipeline (Claude Code plugin API — skills/agents/hooks as documented). acs is **no longer Claude-Code-only**: **OpenAI Codex CLI is a supported pipeline runtime** (Could-have; see Features), so the pipeline targets **≥ 1 of an open set of agent runtimes** rather than Claude Code exclusively. The deterministic layer stays runtime-agnostic stdlib-only Python (Portability NFR); the runtime-specific MECHANISM (hook gating, reflection-subagent protocol, skill/agent dispatch on Codex CLI) is **deferred to the multi-runtime epic's design phase**. Different features may still target different runtimes — tabp targets both Claude Cowork and Claude Code.
- Delivery is git + GitHub PRs (`gh` assumed); correctness must be checkable by automated tests for the strong-fit domains (see `docs/requirements/overview.md`).
- Subagents cannot interact with the user — all user interaction happens in coordinators (drives the `needs_input` handoff design).
- **acs feature — brownfield standardization is additive-only (C-2).** `/acs:standardize-project` operates on an existing repo by ADDITION only: it adds principles/standards docs, config, and missing readiness tooling (coverage/CI/pre-commit/e2e — including scaffolding a repo-side e2e CI workflow/runner and opt-in wiring of a required e2e merge-gate status check), and it MUST NOT move, rename, delete, or rewrite existing source files. **The e2e layer stays OPT-IN: a repo with `settings.e2e` unset has no e2e suite and no e2e merge gate; the gate is configured only on explicit opt-in.** Structural gaps versus the architecture project-structure target are surfaced as recommended follow-up tickets for the user to decide on — never executed as an automatic restructure. This guardrail is deliberate: a wholesale-restructure mandate is explicitly out of scope (it is the over-engineering this product reset once before — see Out of scope). The greenfield/brownfield split is fixed: `/acs:create-project` is greenfield-only and refuses on any repo with substantive sources; brownfield onboarding is `/acs:standardize-project`'s job (C-1).
- **tabp feature:** tabp runs in both Claude Cowork and Claude Code as a fuller plugin; inputs are
  read from the project folder (in Claude Code the folder need not be a git repo; dual-runtime
  driven by MAR-40), falling back to chat attachments; the screen-cvs capability
  uses one Sonnet subagent per CV with Opus synthesis; outputs include a two-sheet Excel
  scorecard and a per-run `.tabp/` archive. tabp is not skills-only — the fuller feature
  shape is defined in the tabp feature section above.
- **acs feature — doc-set storage & docs backend (MAR-48).** Doc producer skills today read/write `*_path` keys and deliver **docs-only PRs to the repo** — that is how review + Git-auditability work. Configurable external-local paths and remote backends change that delivery/audit model. **Requirement:** reviewability + auditability are preserved per configured backend — *mirror/publish* and *external-local* keep a reviewable diff / repo PR (repo stays source of truth); *authoritative-remote* uses backend-native review/audit (Notion is the system of record). **Deferral:** the MECHANISM (Notion API/auth, markdown→blocks mapping, PR-less vs sync delivery, per-mode review/audit) is deferred to the future Notion/remote-docs epic's design phase, mirroring how this PRD already defers tabp's mechanism. Auth via external CLI/integration; **no secrets in settings** (consistent with the `tracker.provider` precedent and the Safety NFR). The local filesystem backend with external/absolute paths is the near-term committed deliverable; the Notion/remote backend is future + deferred.
- **acs feature — tracker-first is graceful degradation, not a parallel pipeline (C-5).**
  Tracker-first / PRD-optional mode reuses the **one existing gated pipeline** (same
  gates, TDD, coverage, review, audit, merge readiness); it is **not** a second
  workflow. acs **never auto-authors a PRD/roadmap/architecture** — reverse-bootstrap
  is **opt-in** (Could-have) and off by default. The conformance chain degrades
  gracefully: **PRD (when present) → architecture (when present) → standards → design
  → specs → code**; a missing upstream artifact makes its trace step N/A, never a hard
  block. This guardrail is deliberate — a parallel "tracker pipeline" or
  auto-PRD-generation would repeat the abandoned MAR-16..24 over-engineering (see Out
  of scope).
- **acs feature — org enforcement uses an org-controlled, non-overridable source; layers are additive (C-6).** Org-level *defaults* extend today's most-specific-wins cascade (a new org source resolved below user, fully overridable). Org-level *mandates* are the opposite: because a CI gate sees only the checked-out repo (the convention checker reads the committed project `.acs/settings.json`, not a developer home dir) and the cascade is most-specific-wins (a repo layer would silently override an org layer), an enforceable org mandate MUST come from an org-controlled source the repo cannot edit and/or use inverted **floor** precedence (repo may tighten, never loosen), with exemptions granted only at the org layer (a repo cannot self-exempt from a mandate) and every effective rule carrying provenance (which layer it came from). Introducing org/department layers is **additive and non-breaking**: with no org source configured, resolution is identical to today's user + team(project) behavior. The MECHANISM (cascade extension vs GitHub org rulesets / org-required workflows vs a versioned policy pack) is deferred to a future design epic / ADR (this PRD states the WHAT).
- **acs feature — complexity tier is a confirmed flag set once at create-ticket; default is full rigor; lighter tiers are opt-in (C-7).** The complexity/supervision tier is set **once, user-confirmed, at create-ticket**, alongside the existing `needs_design` flag and following that exact precedent (a confirmed flag gating downstream skills). The **default stays full/standard rigor**; trivial/standard fast lanes are **opt-in**, so rigor is **never silently dropped**. The code TDD/coverage gate is non-negotiable in every tier; only the redundant independent-verifier role on supervised/low-stakes work is conditional. (Mirrors how `needs_design` is a confirmed flag gating the design step.) Cross-reference: the Out of scope section records that automatic downgrade of a ticket's complexity/supervision tier without explicit user confirmation is out of scope. *(Assumption: this constraint follows the `needs_design` confirmed-flag precedent — verified in `ticket.json` (`"needs_design": false` field present), confirming the precedent exists and no new pattern is invented.)*

## Out of scope

Visual/UX-judged work without an automatable test strategy, hardware-in-the-loop
testing, model training pipelines, registry distribution beyond the GitHub URL.

Per-plugin separate PRDs and per-plugin acs configuration are out of scope — this
single `prd.md` covers the GMS Marketplace product and all its plugin features. The
MAR-17 restructure (separate per-plugin PRDs) was abandoned. The tabp plugin
implementation (plugin.json, screen-cvs skill, marketplace.json entry, CI
version-coupling removal) is a separate follow-up ticket — this PRD defines the
feature; the build is out of scope here.

Automatic wholesale repository restructuring is out of scope. Brownfield
standardization (`/acs:standardize-project`) is additive-only by constraint
(C-2 above): it never moves or renames existing source. Re-laying-out an
existing codebase to match the architecture project-structure target is a
human-decided follow-up, surfaced as recommended tickets — not something acs
performs automatically. This guardrail exists to avoid repeating the abandoned
MAR-16..24 over-engineering reset.

A general CMS / document-management product or a doc-graph re-architecture is out of
scope — this is a bounded config + pluggable-backend capability only. Remote docs
providers other than Notion (Confluence, Google Docs, SharePoint, etc.) are out of
scope now — Notion is the only named remote provider; others are Won't-have (mirrors
the acs Features Won't-have). Bidirectional Notion→repo editing (treating Notion edits
as the inbound source that rewrites repo files) is out of scope now; the
authoritative-remote mode means Notion is the system of record with no repo copy, not
a two-way file sync.

**Auto-authoring product docs from a tracker is out of scope.** Tracker-first mode
never generates a `prd.md`/roadmap/architecture automatically; reverse-bootstrap
(seeding those from imported tickets + codebase) is an **opt-in Could-have** the user
must invoke. Tracker-first applies to the supported trackers only (GitHub Projects /
Jira via `gh` / `acli`); **non-GitHub/Jira forges remain out of scope** (GitLab /
Bitbucket, per the acs Won't-have).

**Reversal note (MAR-35):** this amendment reverses the prior "tabp is skills-only"
product decision that was previously stated in this PRD and in MAR-26 design C-arch-5
(skills-only plugin shape). tabp remains a **FEATURE of the one GMS Marketplace
product** — a fuller feature, not a separate product. This does NOT re-introduce the
abandoned MAR-17 per-plugin-sub-product / separate-per-plugin-PRD approach. The tabp
feature section above replaces the skills-only framing with the fuller-plugin shape.
The tabp-upgrade epic (a separate future ticket) owns the design and build of the new
capabilities; the MECHANISM and Cowork-runtime verification are deferred to that
epic's design phase.

**Reversal note (MAR-42):** this amendment reverses the prior Vision guardrail that the
human owns "the merge button" — i.e. that `/acs:merge-pr` is invocable only by a human. Per
MAR-42 (design approved; **ADR-0028** — "merge-pr is agent/model-invocable; readiness gate +
branch protection are the merge brakes"), `/acs:merge-pr` is now agent/model-invocable. The
human still owns **requirement decisions**. The safety guarantee shifts from "a human must
press merge" to "merge happens only when the readiness gate (CI/approvals/conflicts/
protections) and the repo's branch protection pass, by whoever invokes; failures are
report-only; every attempt is audited," with agent-invoked merges additionally requiring an
approved review (m6). `/acs:ship` still deliberately stops at create-pr (review separation, not
a merge prohibition). This is a product-level Vision change only; the detailed `/acs:merge-pr`
behavior lives in `docs/requirements/skills.md` and the skill prose and is delivered by MAR-42.

**Reversal note (MAR-2):** this amendment reverses the prior "non-Claude-Code runtimes
for the acs pipeline" product decision previously stated as an acs Won't-have. Per
MAR-2 (user-approved, C-1), **OpenAI Codex CLI is now a supported acs pipeline
runtime**. acs remains authored and distributed as a Claude plugin and the **one GMS
Marketplace product** — this adds a **second execution runtime for the pipeline**, not
a second product and not a per-runtime fork of the pipeline. Claude Code stays the
primary/today-shipping runtime; Codex CLI is a Could-have whose **MECHANISM** (mapping
the PreToolUse/SessionEnd hook gating, the planner/executor/verifier reflection-subagent
protocol, and skill/agent dispatch onto Codex CLI) is **deferred to a dedicated future
multi-runtime epic's design phase / an ADR** — exactly as this PRD defers tabp's and
the Notion/remote-docs mechanisms. The GitLab/Bitbucket non-GitHub-forge Won't-have is
**unaffected** — only the runtime clause is reversed.

Non-GitHub org-policy backends are out of scope — org enforcement targets the GitHub
org-controlled surface first (org rulesets / org-required workflows); other forges remain
Won't-have, consistent with the acs Won't-have above. Automatic org-wide migration or bulk
retrofitting of existing repos to an org policy is out of scope — applying org policy to a
repo is an opt-in/rollout action surfaced per repo, never an automatic mass rewrite (same
additive, no-wholesale-restructure discipline as C-2 above and the MAR-16..24 reset note
above). A general non-GitHub policy distribution system is out of scope.

Automatic downgrade of a ticket's complexity/supervision tier without explicit user
confirmation — tiers are always user-confirmed; the system never silently reduces rigor.
