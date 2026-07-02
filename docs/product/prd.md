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
discoverability, and consistent quality across all plugins. The catalog grows
through a documented, gated onboarding path, and every catalog plugin meets a
shared quality bar (trigger-eval baseline + namespace isolation) — see **G20**.

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
| G6 — Portability | Works on any git repo with `python3` + `gh`; zero pip installs; one `/acs:init` to onboard. First validated 2026-06-13 (acs v0.1.2, M2-0 spike): clean install + `/acs:init` in a throwaway repo, no Duplicate-hooks load failure. Each acs doc set (`prd`, `architecture`, `requirements`, `adr`, and future `standards`/`principles`/`quality`/`operations`) is independently relocatable to an external/absolute filesystem path via configuration; 100% of producer-skill runs preserve the per-backend reviewability + Git-audit guarantee (local/external-local = reviewable diff / repo PR; remote = backend-native review); 0 doc-set writes bypass the configured backend review path; measured per release. The acs pipeline is **runtime-portable**: the same gated pipeline (gating, TDD, coverage hard-fail, 12-dimension review, audit) runs on **≥ 2 supported runtimes** (Claude Code today + OpenAI Codex CLI). Gate-integrity strength is **runtime-dependent**: on Claude Code the pre-gate is non-bypassable (kernel `PreToolUse(Skill)` → exit 2); on Codex CLI — whose `PreToolUse` is documented as a guardrail rather than a complete enforcement boundary, which exposes **no skill-invocation matcher and no `SessionEnd` event**, and whose plugin hooks run only once user-trusted — gating is **best-effort by default**, with **non-bypassable enforcement available only via org-managed hooks** (`requirements.toml`). The second-runtime metric is **0 lost audit-trail artifacts** on a published end-to-end run, plus **0 gate escapes under managed-hook enforcement**, **validated within 1 release of the Codex CLI runtime capability shipping** (mirrors how G1/G2/G6 were first validated by the M2-0 spike). |
| G7 — Observability | Dashboard renders all 6 panels (throughput, pipeline funnel, cost/time per step, coverage vs target, review iterations, token burn by role) in ≤ 5 s for ≤ 50 tickets; reads only workspace artifacts; requires no network calls and no new config beyond `.acs/settings.json`. In-session status lines preserve 100% of Claude Code's default status-line fields and add acs state on top (zero default fields lost), render in < 100 ms per refresh, and never crash — any failure falls back to a valid line. *(Shipped — status-line refinement delivered in E3.4; verified live in-session.)* |
| G8 — Skill quality coverage | Structure, gating, and routing covered for 100% of the **16** skills (free, every PR; matches `s04_skill_triggers.py`'s 16-skill routing coverage); every critical-path skill has behavioral (artifact-level) eval coverage — including the dashboard skills `metrics`, `usage`, and `handoff`, which today have only trigger-level coverage (s04) and are the named gap this metric requires closing (see roadmap M3); no new skill ships without ≥ a trigger eval (CI guardrail); **0 orphaned agent files on disk — agent-file count == reachable-agent count** (currently 27 agent files vs 21 reachable; the 6 apply-work planner/verifier files are orphaned per MAR-62 and must be cleaned up or re-wired to close this metric). |
| G9 — Enforceable conventions | The configured branch/PR/commit formats are enforceable as a required merge gate on the consumer repo, blocking non-exempt violating PRs even when they bypassed `/acs:create-pr` (escape hatch: the `acs-exempt` label / release-branch allowlist). MAR-9 (PR #50, pending merge) completes the consumer side of that escape hatch: a legitimate non-ticket exempt PR lands via the sanctioned `/acs:merge-pr --pr` path (same readiness + branch/worktree cleanup as the ticket path, no ticket/partition/tracker/archive; it refuses and redirects ticket-backed PRs), and `/acs:init` Step 7e writes an idempotent `CLAUDE.md` acs-managed block that makes the pipeline the *default* for in-repo agent sessions (steering changes through `/acs:ship` rather than ad-hoc PRs). The gate itself is existence-proven by the live required-check ruleset on this repo's own `main` (ruleset 17602044, `active`; "Branch / PR / commit conventions" is a required status-check context). |
| G10 — Standards conformance & repo standardization | New design/code conforms to the principles + standards doc sets, verifier-checked: **100% of `/code` runs whose changeset touches a standards-governed area produce zero unwaived standards-conformance findings** (a violation is a blocking finding, never a silent pass), measured per release on the dogfood repo. Brownfield onboarding is additive and reviewable: **`/acs:standardize-project` lands its setup as exactly one reviewed PR that adds only docs/config/tooling and moves or renames zero existing source files** (0 source relocations; verified by the PR diff), with every target-layout structural gap emitted as a recommended follow-up ticket rather than an in-place move. |
| G11 — Tracker-first delivery / graceful degradation | A repo with **no PRD/architecture** delivers a remote-tracker-defined ticket end-to-end through the **same gates** (TDD, coverage hard-fail, 12-dimension review, audit, merge readiness) with **zero gate escapes** and **zero "missing PRD" hard-blocks** — the absent upstream artifact makes only its own trace step N/A, never blocking the run. Target: **100% of tracker-first runs (PRD absent) complete without a missing-upstream hard-block AND with 0 gate escapes**, validated on **≥ 1 real PRD-less repo within 1 release of the capability shipping**; tracker-issue acceptance criteria are carried into the spec for **100%** of such runs. |
| G12 — Org-level enforceable policy | An organization can define enforcement policy (required convention checks, security gates, standards/conventions floors) once and have it apply as a **non-overridable floor** across all its repos, with repos able to tighten but not loosen it, exemptions granted only at the org layer, and every effective rule traceable to the layer it came from. **Measurable success metric:** on a pilot org of **≥ 3 repos**, **100% of those repos enforce the org-mandated convention/security checks as required status checks with 0 repo-level self-exemptions of a mandated rule**, and a deliberately non-conforming PR in any pilot repo is **blocked from merge** — first validated within **1 release** of the org-policy capability shipping (mirrors how G1/G9 are validated by an observed live gate, e.g. ruleset 17602044, prd.md). |
| G13 — Enforceable e2e integrity | When the optional e2e merge gate is enabled on a consumer repo, **0 PRs merge with a red e2e suite** (the required e2e status check is a fail-closed merge brake, symmetric to the G9 convention gate and the G3 coverage hard-fail), AND **100% of specs whose changeset touches a user-facing / cross-component surface declare e2e impact** (the spec's Test plan states e2e impact or an explicit "no e2e impact" reason — the code-verifier blocks any declared-impact spec lacking matching e2e test diffs; no zero-findings verdict without a green e2e run). The opt-in invariant holds: a repo with `settings.e2e` unset has no e2e suite and no e2e gate. Measured per release on the dogfood repo (gate-enabled repos). Traces the Tech-lead persona. |
| G14 — Complexity-adaptive delivery efficiency | A trivial, human-supervised ticket is delivered for substantially less wall-clock time and token/cost than the full pipeline. **Metric:** median wall-clock time AND median token/cost for a TRIVIAL-lane ticket are each reduced **≥ 60%** vs the same ticket run through the full plan-execute-verify ladder, measured on the dogfood repo within **1 release** of the capability shipping. |
| G15 — Fast-lane adoption | A meaningful share of tickets flow through the TRIVIAL/SMALL fast lanes (light verify) rather than the full ladder. **Metric:** **≥ 50%** of delivered tickets use the TRIVIAL or SMALL fast lane (vs the full STANDARD/COMPLEX ladder), measured per release on the dogfood repo once the lanes ship. |
| G16 — Rigor preserved where it matters (no regression) | Reducing process volume on simple work must not lower defect-catch. The verifier gates on every lane (autonomous-first); lighter lanes reduce only the verify-iteration ceiling, never whether the verifier or the TDD/coverage gate runs. **Metric:** **0 regression** in the code verifier's defect-catch rate — the TDD/coverage gate's hard-fail behavior is 100% in force on every lane, and full verify (the 12-dimension review) stays 100% on standard/complex lanes; measured by the existing eval harness (E1) showing no drop in verifier-caught findings per release vs the pre-feature baseline. |
| G17 — First-class release-version planning & one-command release cut | **100%** of roadmap versions carry an explicit version → milestone/epic mapping (every committed milestone resolves to exactly one release version, 0 orphan milestones), **AND** a release is cut in **1 command** producing an aggregated changelog/release notes from the merged tickets in that version, a version bump, a tag, and a GitHub release with **0 manual `release: cut vX.Y.Z` steps** — first validated by cutting **1** real acs release end-to-end within **1 release** of the capability shipping (mirrors how G1/G9/G11 are first validated by an observed live run). |
| G18 — Guided architecture selection (select-not-author) | For a repo with a PRD present, `/acs:create-architecture` presents a **pre-filtered/ranked shortlist across all FOUR catalog categories** (techstack, NFR templates, architecture patterns, design patterns) such that **≥ 80%** of finalized architecture selections are **chosen or refined from the offered shortlist rather than authored from scratch**, and the top-ranked shortlist is **non-empty for 100%** of the four categories on a PRD-present run — measured per release on the dogfood repo within **1 release** of the capability shipping. |
| G19 — Failure-mode / pipeline-health observability | A tech lead can see verifier cap-hits, gate-block counts, coverage hard-fail incidents, stale locks, and abandoned/handed-off tickets over time — not just success/throughput. **Metric:** the cap-hit rate and gate-block count are visible for **100%** of tickets in the workspace, rendered in **≤ 5 s** for ≤ 50 tickets, read-only from existing workspace artifacts (no new config) — measured per release on the dogfood repo within **1 release** of the capability shipping. Extends G7's observability goal with failure-signal coverage. |
| G20 — Marketplace catalog growth & quality bar | The GMS Marketplace grows its plugin catalog through a documented, gated onboarding path while every catalog plugin meets a shared quality bar. **Metric:** a new plugin is added to the catalog through the documented path in **≤ 5 steps** (manifest entry, `marketplace.json` registration, namespace-isolation check, trigger-eval baseline, README), **AND 100%** of catalog plugins (currently 2: acs, tabp) pass the shared quality bar — a trigger eval baseline (mirrors G8's per-skill trigger-eval requirement) plus a verified namespace-isolation check (no cross-plugin prefix/token leakage, mirrors the tabp namespace rule) — measured per release. |
| G21 — Complete-configuration onboarding (init offers every user-configurable setting) | A fresh `/acs:init` actively offers every user-configurable acs setting — no user-settable capability is reachable only by hand-editing `.acs/settings.json` — and per-role model (at specific version), per-role reasoning effort, and e2e are each explicitly offered. **Measurable success metric:** on a fresh init, **100% of user-configurable `settings.schema.json` keys are reachable via the interactive `/acs:init` flow**, AND **per-role model (specific version, e.g. `claude-opus-4-8` / `claude-sonnet-5`), per-role reasoning effort, and e2e configuration are each explicitly offered** (not silently defaulted) — verified by a **fresh-init walkthrough on the dogfood repo within 1 release** of the capability shipping (mirrors how G1/G9/G11 are first validated by an observed live run). Extends **G7** (config-surface discoverability). Traces the **Solo-developer + Tech-lead personas**. |

### tabp feature — success metrics

| Metric | Measurable success metric |
|--------|---------------------------|
| T1 — Speed | Screen a 20-CV batch ≥ 70% faster than manual screening, measured within 1 month of the feature's first use. |
| T2 — Reproducibility | ≥ 95% reproducible band/recommendation on a fixed 10-CV regression set, per release. |
| T3 — Evidence & auditability | 100% of judgments cite evidence and produce a scorecard, every run — no recommendation without a traceable rationale. |
| T4 — Fairness | 0 protected/proxy criteria used AND 100% of bias-relevant JD requirements flagged, measured on a ≥ 15-pair test set, per release. |
| T5 — Adoption | ≥ 80% of new TABP role openings use screen-cvs within 3 months of the feature's first use. |
| T6 — Verifier-as-gate | 100% of screen-cvs runs present results only after a clean verifier `pass` verdict from `screen-verifier-subagent.md` (0 results shown on cap-hit at N=3 unresolved-finding remediation attempts), measured per release on the run history in `.tabp/history.json`. |
| T7 — Resumability | 100% of interrupted screen-cvs runs resumable from `.tabp/` persisted state alone (run.json, evidence-*.json, decision.json, history.json), verified by 1 real interrupted-and-resumed run per release. |

## Features (MoSCoW)

The GMS Marketplace currently delivers two plugin features — **acs** and **tabp** —
each prioritized internally via MoSCoW. Future plugins will be added as additional
feature sections here.

### Feature: acs (Autonomous Coding Skills)

**Must have** *(shipped in v0.1)*
- Claude Code plugin marketplace (this repo) with the `acs` plugin.
- 16 skills: `/init`, `/ship`, `/handoff`, `/update`, `/install-hooks`, 4
  product-level (`create-prd`, `create-architecture`, `create-project`, `metrics`),
  1 usage dashboard (`usage`), 6 workflow (`create-design`, `create-spec`,
  `create-ticket`, `code`, `create-pr`, `merge-pr`). Verified on disk: `ls
  plugins/acs/skills` = 16.
- Hook-enforced step gating (PreToolUse dispatch, exit-2 blocks, SessionEnd safety net).
- Workspace partitioned by repo/ticket, outside the consumer repo; locks, worktree parallelism.
- Reflection cycle (planner/executor/verifier) with XML messaging (XSD) and phase artifacts. The six triad-keeping skills (create-prd, create-architecture, create-project, create-design, create-spec, code) each spawn the full planner/executor/verifier triad; the three apply-work skills (create-ticket, create-pr, merge-pr) run **inline** (coordinator + at most one executor, no planner/verifier) since MAR-60. 27 agent files exist on disk (9 skills × 3 roles) but only 21 are reachable — 18 active triad agents + 3 apply-work executors; the 6 apply-work planner/verifier files are orphaned (MAR-62 tracks cleanup).
- TDD `/code` with coverage hard-fail and the 12-dimension changeset review loop (≤ 3 iterations).
- Local-first tickets: epics with child fan-out, per-repo id sequence, archive lifecycle.
- Resume at three levels (gates, `/ship` ledger, mid-skill reconcile) + deliberate handoff.
- Requirement clarification ledger; grounding rules; standard completion reports.
- `acs:metrics` dashboard skill — reads workspace artifacts (`metrics.json`, `tickets-index.json`, per-ticket `pipeline-state.json`, `code-state.json`, `create-pr-state.json`) and renders an interactive HTML dashboard inline in the Claude Code session (`show_widget`) covering: ticket throughput by status/type, pipeline funnel, cost and time per ticket broken down by pipeline step, test coverage achieved vs target, review iterations before verifier passed, and token burn by role (planner/executor/verifier). Read-only; no new file writes; no new config; single-repo scope. Traces G5, G7. *(Must have for M2 exit)*
- `acs:usage` dashboard skill — a separate, shipped delivery-metrics/AI-spend
  split from `acs:metrics`: reads workspace artifacts and renders cost, token,
  and time usage (AI spend) per ticket/run/role, distinct from `acs:metrics`'s
  delivery-KPI focus (throughput, funnel, coverage, review iterations). The two
  dashboards partition **delivery KPIs** (`acs:metrics`) from **AI-spend
  tracking** (`acs:usage`). Read-only; no new file writes; no new config;
  single-repo scope. Verified on disk: `plugins/acs/skills/usage/SKILL.md`.
  Traces G5, G7.
- Convention enforcement as a required merge gate — `/acs:init` Step 7c scaffolds a repo-side CI check (`.github/workflows/acs-conventions.yml`) backed by a stdlib-only `.acs/ci/check-conventions.py` (fail-closed; modes `pr` / `pre-push` / `commit-msg`) compiled from the configured `formats.*`, plus an `enforcement` settings block (`checks.{branch_name,pr_title,pr_description,acs_label,commit_message}`, `require_label`, `exempt_label` default `acs-exempt`, `exempt_branches`, `pr_description_sections`). Wired as a required status check on the consumer repo, it blocks non-exempt branch/title/description/label/commit-message violations even on PRs that bypassed `/acs:create-pr`; the `acs-exempt` label and a release-branch allowlist are the escape hatch. Observed live on this repo (ruleset 17602044, `active` on `main`; "Branch / PR / commit conventions" is a required context). Traces G9 (+ the Tech-lead persona). **MAR-9 (PR #50, pending merge)** extends this: the exempt PRs the gate lets through then land via a sanctioned merge path — `/acs:merge-pr --pr <n>` (also `#n` / a PR URL) runs the same four readiness dimensions and branch/worktree cleanup as the ticket path but resolves no ticket, writes no partition/state, and skips tracker sync and archiving (bumping only the repo `pr_merged` metric), refusing and redirecting when the PR is actually ticket-backed; and `/acs:init` Step 7e (opt-in, default-on) writes an idempotent, marker-delimited `CLAUDE.md` acs-managed block (rendered from `templates/CLAUDE.acs.md`) that steers in-repo Claude sessions to ship via `/acs:ship` instead of a raw `gh pr create`, making the pipeline the default rather than only the gate.
- `/acs:install-hooks` skill — the `pre-commit install` equivalent for acs (per-clone, user-invoked): installs the config-driven local git hooks (`commit-msg` + `pre-push`) that run the same `check-conventions.py` before a commit or push leaves the machine. A committed `.acs/ci/install-hooks.sh` lets teammates run it without the plugin. Traces G9 (+ the Tech-lead persona).
- **Tracker-first delivery (PRD-optional mode)** — a **configurable governance mode**
  so a team with no PRD/roadmap/architecture can deliver requirements that live only
  in a remote tracker (GitHub Projects / Jira) through the **same gated pipeline**.
  When upstream product docs are **absent**, the imported tracker issue (description +
  acceptance criteria) is the **requirement source of truth**; the conformance chain
  **degrades gracefully** — a missing upstream artifact makes only its own trace step
  **N/A**, never a hard block — while TDD, coverage hard-fail, the 12-dimension review,
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
- **Complexity-adaptive delivery** *(shipped — MAR-55 epic: MAR-56/57/58/59/60/61 merged to main)* — acs scales the amount of process/structure it
  applies to a ticket based on the ticket's **complexity** AND the level of **human
  supervision**, instead of running the full plan-execute-verify ladder on every
  ticket. **Framing principle (autonomous-first):** acs is autonomous-first — the
  in-loop quality gate on every lane is the **verifier subagent**, and the
  human-in-the-loop checkpoint is the **PR review** before merge, not an inline
  human-approval gate. What scales with complexity is the *amount of process*
  (decomposition stages and verify iteration depth), **not whether the verifier
  runs**: the verifier always runs, and the TDD/coverage gate always runs, in
  every lane. (This generalizes Claude Code's own adaptivity — Plan mode for
  complex, skipped for simple — but keeps an automated in-loop gate because acs
  must stay correct on unattended `/acs:ship` runs where no human is watching.)
  Routing is **two axes — size × stakes** — assembled into four lanes; lighter
  lanes reduce process volume but never drop a gate. Four delivery lanes:
  1. **TRIVIAL** (trivial size, not high stakes) — no standalone create-spec and
     no separate planner subagent (spec authoring is folded into `/code`'s plan
     phase); **light verify**: a single verifier pass that may iterate at most
     **once** on blocking findings (`VERIFY_ITERATION_CAP["light"] = 1`). The
     verifier still gates; there is no human-approval gate.
  2. **SMALL** (small size, not high stakes) — same fast-lane fold and **light
     verify** (1-iteration cap) as TRIVIAL.
  3. **STANDARD** (standard size, or any ticket with `needs_design`) — full
     create-spec path; **full verify** (the existing up-to-3-iteration
     plan→execute→verify loop + 12-dimension review + e2e when configured).
     Apply-work skills (create-pr, merge-pr, create-ticket) run **inline**
     (coordinator + at most one executor), never a full triad, in every lane.
  4. **COMPLEX / UNATTENDED** (large size, epic, or `/acs:ship` autonomous run) —
     **full verify** exactly as today; the persisted artifacts are the audit
     trail; preserves the rigor that is the product.

  **High-stakes floor:** `stakes = high` resolves to at least STANDARD (full
  verify) regardless of size — a defense-in-depth floor a small lane value can
  never bypass. **Mid-flight escalation** raises a ticket to a higher lane (and
  re-introduces any skipped stage) on the first higher-stakes signal, upward-only
  and automatic; de-escalation is never automatic. The lane is set once,
  user-confirmed, at create-ticket alongside `needs_design`; default is
  full/standard rigor; lighter lanes are opt-in and rigor is never silently
  dropped. Traces **G14, G15, G16**.

**Should have** *(shipped in v0.1, maturing)*
- Two-way tracker sync (GitHub Projects / Jira via `gh` / `acli`), remote import.
- **Configured e2e test layer with an optional enforceable merge gate** — the opt-in `settings.e2e` layer ships today (`command` + optional `setup`/`teardown`, `per_iteration`; unset = no e2e suite): `/acs:create-spec` test plans declare e2e impact, `/acs:code` authors/runs affected e2e tests in the same changeset, and the code-verifier runs the FULL suite (no green run, no zero-findings verdict). **New:** `/acs:init` can scaffold a repo-side e2e CI workflow + runner and wire it as a REQUIRED status check on the consumer repo (opt-in, fail-closed), so a red e2e blocks PR merge — symmetric to the G9 convention gate and the G3 coverage hard-fail, and making the today-report-only `/acs:merge-pr` CI read ENFORCEABLE via branch protection. A fresh `/acs:init` **explicitly offers** e2e configuration (candidate-detected), rather than leaving it in the silently-defaultable optional batch — the exact prompt mechanism is deferred to the implementing ticket's design/spec phase. Traces G13, G9, **G21**. *(The opt-in invariant is preserved: no `settings.e2e`, no e2e suite and no gate.)*
- `docs_only` fast-path; PR-size control with ticket splitting.
- Per-role model + effort configuration *(shipped in v0.1, maturing)* — users can pin a specific model version (e.g. `claude-sonnet-5` / `claude-opus-4-8`) and set a reasoning effort per role in `.acs/settings.json` for all FOUR roles — `planner`, `executor`, `verifier`, `coordinator` — plus per-skill overrides (`models.overrides.<skill>.<role>`); a role value is a bare model string or a `{model, effort}` object, resolved override → role → inherit. A fresh `/acs:init` actively offers every user-configurable acs setting, so no user-settable capability is reachable only by hand-editing `.acs/settings.json`; the three under-offered surfaces today are per-role model at specific-version granularity, per-role effort, and e2e (traces **G21**). **Maturing enhancements (committed):** (1) init discoverability — a fresh `/acs:init` actively PROMPTS for per-role model at SPECIFIC-VERSION granularity (offering version-pinned choices, e.g. `claude-opus-4-8` / `claude-sonnet-5`, not only coarse tiers) AND for per-role reasoning EFFORT as a first-class choice (not only a documented example), including the coordinator-scope caveat, so the choice is fully discoverable — the exact init UX is mechanism, deferred to the implementing ticket's design/spec phase; (2) up-front value validation — validate supported effort values and model ids fail-closed at config time with a helpful error, instead of failing late at subagent-spawn time (the supported-effort enum exists today only in the advisory `settings.schema.json`, not enforced by the runtime gate, and there is no model-id validation) — the supported-model-id/effort source-of-truth is mechanism, deferred to the implementing ticket's design/spec phase. Traces G7 (observability/config surface — see the "convenience config (…models…)" framing below), **G21**. See roadmap **v0.3.1** (init prompt) and M3/v0.4.0 (up-front validation + docs) for the committed delivery items.
- Status lines layer acs state onto Claude Code's defaults, never replacing them — both the prompt line and the reflection agent-panel compose with Claude Code's default rendering and add acs context on top: the **prompt** line surfaces the default's standard context (model, cwd, git branch, context-left, output style) **plus** acs pipeline state (active ticket, step glyphs, cost, lock); the **agent panel** keeps every non-acs row at its Claude Code default and enriches the recognized reflection-subagent rows with acs state (phase, role, ticket, tokens, elapsed), with room to surface more acs-relevant fields. *(Traces G7.)*
- Behavioral eval harness for skills: free contract/gate smoke (pre-commit + CI) + paid agentic evals as a pre-release gate. *(Delivered in M2, Epic E1. Traces G8.)*
- **First-class release versions + one-command release cut** — acs's release process gains two related capabilities: (a) a **cut-release capability** that aggregates the merged tickets belonging to a version into changelog/release notes, bumps the version, tags the commit, and creates the GitHub release — filling today's manual "release: cut vX.Y.Z" gap (see README "Releasing & updating"); and (b) the create-prd **roadmap models release versions as first-class planning units** distinct from milestones, with an explicit version → milestones/epics mapping (today the roadmap only *labels* milestones with versions, e.g. "M3 — v0.4.0"). This likely warrants a new producer/apply-work skill (e.g. `/acs:release` or `/acs:create-release`), but the exact **skill name/shape, the version-object schema, and the release-cut implementation are MECHANISM — deferred to the implementing epic's design phase** (mirrors the Notion/multi-runtime/org-policy deferrals above). Traces **G17**. See roadmap M3 (v0.4.0) for the committed delivery item.
- **Guided architecture selection — curated catalog, select-not-author** — `/acs:create-architecture` gains a **curated acs-shipped catalog** of common tech stacks, NFR templates, and architecture/design patterns, **pre-filtered/ranked** by what the PRD + codebase imply, so the user **selects/refines** from the most relevant options across all FOUR categories (techstack, NFRs, architecture patterns, design patterns) instead of inputting from scratch. This **enhances the existing `/acs:create-architecture` skill and adds no new doc set**. The **catalog source-of-truth and the exact selection UX are MECHANISM — deferred to the implementing epic's design phase.** Traces **G18** (+ the Tech-lead persona). See roadmap M3 (v0.4.0) for the committed delivery item.
- **Failure-mode / pipeline-health observability** — extends the existing dashboard
  surfaces (`acs:metrics`, `acs:usage`), which today are strictly success/throughput
  oriented, with a failure-signal view: verifier cap-hits, gate-block counts,
  coverage hard-fail incidents, stale locks, and abandoned/handed-off tickets — read
  from existing workspace artifacts (same read-only, no-new-config discipline as
  G7). Mechanism (standalone panel vs a new `acs:metrics` section) is deferred to
  the implementing ticket's design/spec phase. Traces **G19** (extends G7). See
  roadmap M3 (v0.4.0) for the committed delivery item.

**Could have**
- Scheduled background tracker sync; cross-machine handoff (shared workspace) — both sequenced into v0.7.0 (see roadmap M6); additional description templates.
- **Discoverability — skill index / next-step advisor** — with 16 acs skills + 2
  tabp skills there is no in-plugin "what can I do / where am I in the pipeline /
  what's the next step" surface today; `install-hooks` and `update` are
  `disable-model-invocation: true` (verified in frontmatter) so they are
  discoverable only if the user already knows them. Adds a read-only skill index /
  next-step advisor (e.g. `/acs:help`) that lists available skills and the current
  ticket's next pipeline step from workspace state. Mechanism deferred to the
  implementing ticket's design/spec phase. Distinct from the M3 onboarding-polish
  epic (which addresses `/acs:init` flows, not a skill catalog); maps to the
  Solo-developer persona. See roadmap M3 (v0.4.0) onboarding-polish epic.
- acs maintains the `quality/` and `operations/` doc sets for consumers (test strategy + release/ops runbooks) via `/acs:create-quality` and `/acs:create-operations`, plus `/acs:test` — a schedulable regression runner that triages failures and opens a ticket per regression (closed loop). *(Proposed — see [ADR 0011](../adr/0011-sdlc-doc-sets-quality-and-operations.md).)*
- **acs maintains the `principles/` and `standards/` doc sets for consumers** — engineering principles (e.g. `/acs:create-principles` → `principles/`) and coding standards/conventions (e.g. `/acs:create-standards` → `standards/`), each a product-level producer skill with its own planner/executor/verifier triad and acs-shipped templates, following the one-skill-per-set pattern of `/acs:create-architecture` and the proposed `/acs:create-quality` / `/acs:create-operations` (see [ADR 0011](../adr/0011-sdlc-doc-sets-quality-and-operations.md)). These sets sit between architecture and design in the conformance chain: **PRD → architecture → standards → design → specs → code**, each level verified against the one above it. Design and code MUST conform to the standards docs; the `/code` `code-verifier`'s technical-standards dimension and the design verifiers check conformance and block violations (no silent waivers). Traces G10 (+ the Tech-lead persona). *(Proposed — extends the chain at workflow.md and docs/README; see Constraints.)*
- **Architecture doc set gains an explicit project-structure target** — the `/acs:create-architecture` output set adds a project-structure document (the intended repo layout, derived from the C4 container/component views) as the canonical target a repo is expected to match. It is the layout `/acs:standardize-project` audits an existing repo against. Traces G10.
- **`/acs:standardize-project` — brownfield standardization (separate from `/acs:create-project`, which stays greenfield-only)** — audits an EXISTING repo against its principles + standards doc sets, the architecture project-structure target, and acs-readiness tooling (coverage/CI/pre-commit/e2e harness — scaffolding a repo-side e2e CI workflow + runner and, opt-in, wiring it as a required e2e merge-gate status check for an EXISTING repo that lacks one, the brownfield counterpart to greenfield-only `/acs:create-project`), then **additively** sets up the missing docs/config/tooling as **one reviewed PR**. It NEVER moves or renames existing source; structural gaps versus the target layout become **recommended follow-up tickets**, not in-place moves. Traces G10, G13 (+ the Tech-lead persona). *(Proposed; additive-only — see the C-2 guardrail in Constraints & assumptions.)*
- **Configurable doc-set storage location (external/local paths)** — each acs doc set's path is independently configurable and may point to an absolute/external path outside the consumer repo (not only repo-relative); generalizes the `prd_path`, `architecture_path`, `requirements_path`, `adr_path`, and future `standards_path`/`principles_path`/`quality_path`/`operations_path` keys under one doc-set storage-location config surface; producer skills resolve the configured location and preserve a reviewable diff there. This is the committed near-term deliverable. Traces extended G6.
- **Pluggable remote docs backend (Notion)** — mirrors the existing `tracker.provider` precedent (`local` filesystem default + `notion` as the first remote provider); supports BOTH modes per backend: (1) **publish/mirror** — repo stays source of truth, the docs-only PR is preserved, content synced to Notion for reading; (2) **authoritative-remote** — Notion is the system of record, no repo copy, review/audit happens in Notion. The **MECHANISM** — Notion API/auth, markdown→Notion-blocks mapping, PR-less vs sync delivery, per-mode review/audit — is **deferred to a dedicated future Notion/remote-docs epic's design phase**, mirroring how this PRD defers tabp's mechanism. Auth via external CLI/integration; no secrets in settings (mirrors the `tracker.provider` precedent and the Safety NFR). Traces extended G6. **Tentative version home: v0.6.0** (see roadmap M5 — v0.6.0), sequenced after v0.4.0; the MECHANISM deferral above is unchanged.
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
  gated pipeline (ordering/gating, TDD, coverage hard-fail, the 12-dimension review
  loop, resumable workspace state, audit trail, merge readiness) becomes runnable on
  **OpenAI Codex CLI** in addition to Claude Code, so a team standardized on Codex CLI
  can adopt acs without switching agent runtimes. acs stays authored and distributed
  as a Claude plugin; this adds a **second execution runtime for the pipeline**, not a
  second product. The **MECHANISM** — how the Claude-Code-specific mechanisms map onto
  Codex CLI (hook gating, the planner/executor/verifier reflection-subagent protocol,
  skill/agent dispatch, per-role model/effort config, self-reported cost/tokens) — is
  **deferred to a dedicated future multi-runtime epic's design phase**, mirroring how
  this PRD defers the Notion/remote-docs and org-policy mechanisms. That design MUST
  account for documented Codex-platform constraints rather than assume a 1:1 mapping:
  Codex exposes **no skill-invocation hook matcher and no `SessionEnd` event**, its
  `PreToolUse` is a **guardrail, not a complete enforcement boundary** (so pipeline
  gating is best-effort unless deployed as org-managed `requirements.toml` hooks), and
  Codex spawns subagents **only on explicit request** via a different custom-agent
  format — so the reflection cycle is a genuine runtime divergence, not a thin shim. The
  deterministic layer is already stdlib-only Python (Portability NFR), which is the
  portable substrate this builds on. Traces **extended G6** (runtime portability).
  **Lowest-priority Could-have — sequenced after the v0.4.0 epics ship, with a
  tentative version home at v0.5.0** (see roadmap M4 — v0.5.0): not started, designed,
  or ticketed until the v0.4.0 epics ship; it does not compete with the v0.4.0 epics for
  capacity. *(Proposed — the MECHANISM is deferred to the multi-runtime epic's design
  phase / an ADR, per Constraints. Reverses the prior acs "non-Claude-Code runtimes"
  Won't-have — see Reversal note (MAR-2) in Out of scope; the separate GitLab/Bitbucket
  non-GitHub-forge Won't-have is reversed independently — see the acs Could-have
  "Non-GitHub forges (GitLab/Bitbucket) support" below and the Reversal note (MAR-71) in
  Out of scope.)*
- **Non-GitHub forges (GitLab/Bitbucket) support** — the delivery pipeline (tracker
  import/sync, PR flow) targets GitLab/Bitbucket in addition to GitHub, extending the
  Two-way tracker sync Should-have (above) to the additional forges. The **MECHANISM**
  (forge API/auth mapping, MR-vs-PR semantics) is **deferred to the forge epic's design
  phase**, mirroring the Notion/multi-runtime deferrals. **Tentative version home:
  v0.7.0** (see roadmap M6 — v0.7.0). Traces the Two-way tracker sync Should-have goals
  (above) + extended **G6** (portability). *(Reverses the prior acs "non-GitHub forges"
  Won't-have — see Reversal note (MAR-71) in Out of scope.)*

**Won't have (now)** *(acs feature scope)*
- Non-Notion remote docs providers (Confluence, Google Docs, SharePoint) — Notion is the only named remote provider; general CMS / doc-graph re-architecture is out of scope; bidirectional Notion→repo editing is out of scope now (authoritative-remote means Notion is the system of record with no repo copy, not a two-way file sync).
- Automatic downgrade of a ticket's complexity/supervision tier without explicit user confirmation — tiers are always user-confirmed; the system never silently reduces rigor.
- Claude Code plugin LSP servers (`.lsp.json`), background monitors (`monitors.json`), and `bin/` PATH executables — evaluated (MAR-82) and not adopted as acs features. **LSP** is an anti-fit: it breaks the G6 zero-install/language-agnostic portability guarantee (Portability NFR) and is redundant with Claude Code's official LSP plugins. **Background monitors** are session-scoped and overlap already-planned work — the `/acs:test` closed-loop (v0.4.0) and Scheduled background tracker sync (v0.7.0) Could-haves — so they are at most a deferred mechanism of those items, not a new feature. **`bin/` PATH executables** sit below PRD altitude: an internal helper-invocation mechanism with no user-facing change that would not serve the deliberately install-free CI path (Portability NFR). Revisit only if a concrete acs need appears.

### Feature: tabp (recruiting/talent toolkit for the TABP team)

Runs in **both Claude Cowork and Claude Code**. tabp is a fuller plugin; screen-cvs is
one capability within it, targeting a project-folder-based workflow. In Claude Code the
project folder need not be a git repo (dual-runtime support driven by MAR-40, per
clarification C-1 on the MAR-36 epic).

**Must have** *(shipped — tabp upgrade, verified on disk: `plugins/tabp/README.md`)*
- **screen-cvs** — screen one CV or a batch against a job description; parse the JD
  into must-have vs nice-to-have requirements; produce evidence-based Met/Partial/Missing
  per requirement; compute a weighted 0–100 match score where missing a must-have
  requirement caps the result; assign a Strong/Moderate/Weak band with a
  Recommend/Hold/Reject recommendation; output an inline summary and a two-sheet Excel
  scorecard; apply fairness guardrails (job-relevant criteria only, decision-support
  framing); batch screening fans out one Sonnet subagent per CV with Opus synthesis;
  inputs read from the project folder, falling back to chat attachments.
  Traces T1, T2, T3, T4, T5.
- **tabp settings.json** *(shipped)* — configurable models (`screening_model`,
  `synthesis_model`) and default CV/JD folder paths (`cv_folder`, `jd_folder`);
  stored in the project folder (`tabp settings.json`, root of the project folder);
  validated via `tabp_helper.py settings-validate` against
  `plugins/tabp/schemas/settings.schema.json`; no secrets accepted (validator
  rejects a `workspace_path` key or any secret-shaped key).
- **.tabp/ workspace state** *(shipped)* — run history and a per-screening archive
  (the `.xlsx` scorecard and a JSON record per run); persisted in the project
  folder under `.tabp/runs/<run-id>/`, `evidence-<id>.json`, `decision.json`,
  `history.json`, `lock`; written atomically via `tabp_helper.py` with a spin-lock
  and schema validation against `plugins/tabp/schemas/*.schema.json`.
- **/tabp:usage skill** *(shipped)* — surfaces per-run usage metrics: cost, time,
  and tokens, reading `.tabp/history.json` and per-run `run.json` via
  `tabp_helper.py usage-read`; renders a per-run table plus an aggregate totals
  summary; labels derived cost as `cost_basis="estimate"` with a
  `pricing_snapshot_date`; read-only, no writes, no re-screening, no network
  calls. Verified on disk: `plugins/tabp/skills/usage/SKILL.md`.
- **Resumable runs** *(shipped)* — all intermediate states persisted as a
  human-reviewable audit trail in `.tabp/`; the run can be resumed from the
  persisted state.
- **Reflection/self-verification (verifier-as-gate)** *(shipped)* — an
  independent verifier subagent (`plugins/tabp/agents/screen-verifier-subagent.md`)
  runs always-on (no skip path) after synthesis, confirming all evidence is cited
  and fairness guardrails were followed; on blocking findings the coordinator
  remediates and re-verifies, capped at N=3 total verifier invocations; results
  are delivered only after a clean `pass` verdict — on cap-hit with unresolved
  findings, no results are presented and the recruiter is notified instead.

**Should have** *(genuinely unbuilt — verified: no rich-artifact rendering or
Cowork-runtime verification found on disk)*
- **Rich Claude artifact** — results rendered as a rich Claude artifact (distinct
  from the shipped inline summary + Excel scorecard) for recruiter review.
- **Recruiter sign-off UX** — the completed result presented as an explicit
  recruiter sign-off step (distinct from today's "present after clean verifier
  pass" delivery).
- **Claude Cowork-runtime verification** — confirm the shipped capabilities above
  (settings resolution, `.tabp/` writes, always-on verifier, resumability)
  actually behave identically when tabp runs inside Claude Cowork, not only
  Claude Code; the plugin is authored runtime-agnostic but this verification has
  not been performed/recorded.

**Namespace rule:** tabp operates in its own namespace and must never use `.acs/` or
`acs:` prefixes. No `acs` token appears in tabp's external surface. The canonical
tabp-namespaced forms are `.tabp/` (workspace state), `tabp settings.json`
(configuration), and `/tabp:usage` (the usage-metrics skill).

**Engineering-rigor NFR (tabp upgrade)** *(shipped — verified:
`plugins/tabp/README.md`, `plugins/tabp/agents/*`, `plugins/tabp/schemas/*`)*:
the fuller tabp workflow adopts the same proven quality patterns in tabp's own
namespace:

- **Coordinator-plus-subagents** — the Sonnet-per-CV + Opus-synthesis shape already
  present in screen-cvs continues across the fuller tabp workflow.
- **Reflection/self-verification** — the rubric's own consistency check; tabp presents
  results only after a self-verification step (the always-on verifier subagent above).
- **Structured JSON state** — tabp persists all run state in structured, human-readable
  JSON (in `.tabp/`), schema-validated against `plugins/tabp/schemas/*.schema.json`.
- **Source-grounded evidence / anti-hallucination** — screen-cvs already cites CV
  evidence per requirement; the fuller tabp workflow extends this discipline; tabp
  never invents or assumes evidence the source does not support.
- **Decision recording for human review** — the `.tabp/` audit trail and the
  present-for-review step form the decision record.

The mechanism shipped as **instruction-driven** coordinator+subagent protocol
(not hook-gated) — verified: `plugins/tabp/README.md`, `plugins/tabp/agents/*`.
Verification against Claude Cowork specifically (as opposed to Claude Code, where
the shape above is confirmed) remains outstanding — see the tabp Should-have
"Claude Cowork-runtime verification" item above.

**Remaining deferral:** the **rich Claude artifact** rendering and the
**recruiter sign-off UX** mechanisms (see the tabp Should-have items above), plus
final **Claude Cowork-runtime verification** of the shipped shape (config
resolution, hooks, self-reported cost/tokens under Cowork specifically), are
**deferred to the tabp-upgrade epic's remaining follow-on work**. This PRD states
the requirements (what) for those two items; the design (how) is determined
then.

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
- **Verifier-as-gate with lane-driven depth (autonomous-first)**: the verifier
  subagent is the **in-loop quality gate on every lane** — it always runs; the
  human-in-the-loop checkpoint is the PR review, not an inline approval. What
  scales with the lane is **verify depth**, not whether the verifier runs:
  `verify_depth(size, stakes)` returns `light` (a single verifier pass, iteration
  cap 1) for TRIVIAL/SMALL low/normal-stakes tickets and `full` (the up-to-3
  iteration loop + 12-dimension review + e2e when configured) for
  STANDARD/COMPLEX and **all** high-stakes tickets. The code TDD/coverage gate
  **always** runs in full in every lane and is never trimmed by depth selection.
  Gates fail closed — the gate is never the thing dropped; the lighter lane only
  reduces *iteration ceiling and decomposition stages*. (Composes with "Graceful
  degradation of the conformance chain" above: lane-driven depth scales
  *process volume*, the chain's gates still fail closed.)
- **Deterministic apply-tier executors**: apply-tier skills (create-ticket, create-pr,
  merge-pr) have deterministic executors with judgment front-loaded into
  clarification/gates; they do **not** need an iterating plan-execute-verify reflection
  loop. create-ticket's structural checks (schema-completeness, link bidirectionality)
  are a **script check, not an LLM verifier**.
- **Message-validation / per-send performance**: XML message validation runs
  **in-process** by default — `validate_xml.py`'s `validate_structurally()` (pure
  stdlib `xml.etree`, raised to XSD-equivalent coverage) is the fast path and spawns
  **no subprocess per send/receive**; a `validate_batch()` API validates a list in one
  in-process loop. `xmllint` is invoked **opt-in only** when `ACS_XML_AUTHORITATIVE=1`
  (and `xmllint` is on PATH and the XSD is present); its absence never blocks (MAR-61).
  Clarifications are **batched** at the coordinator level — when ≥ 2 are open they are
  presented in one grouped `AskUserQuestion`, each answer recorded as its own
  `clarify.py` entry.

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
- **acs feature — complexity tier is a confirmed flag set once at create-ticket; default is full rigor; lighter tiers are opt-in (C-7).** The complexity/supervision tier is set **once, user-confirmed, at create-ticket**, alongside the existing `needs_design` flag and following that exact precedent (a confirmed flag gating downstream skills). The **default stays full/standard rigor**; trivial/small fast lanes are **opt-in**, so rigor is **never silently dropped**. The code TDD/coverage gate and the in-loop verifier gate both run in every lane (autonomous-first); what the lighter lanes make conditional is the **verify depth** (light = single pass, iteration cap 1) and the heavyweight decomposition stages (standalone create-spec / separate planner), never whether a gate runs. (Mirrors how `needs_design` is a confirmed flag gating the design step.) Cross-reference: the Out of scope section records that automatic downgrade of a ticket's complexity/supervision tier without explicit user confirmation is out of scope. *(Assumption: this constraint follows the `needs_design` confirmed-flag precedent — verified in `ticket.json` (`"needs_design": false` field present), confirming the precedent exists and no new pattern is invented.)*
- **acs feature — release versioning is additive to the existing roadmap/release model; the cut mechanism is deferred (C-8).** Modeling release versions as first-class planning units is **additive and non-breaking**: the roadmap already labels milestones with versions (e.g. "M3 — v0.4.0") and that labeling stays valid; this amendment adds an explicit version → milestone/epic mapping and a capability to cut a release — it does not restructure the existing milestone tracks. The **release-cut mechanism** (new skill name/shape, version-object schema, changelog-aggregation source, tag/GitHub-release implementation, and its coupling to the existing `marketplace.json`/`plugin.json` version-bump + Release workflow described in the README) is **deferred to the implementing epic's design phase / an ADR**, mirroring the Notion/org-policy deferrals above. Auth stays via `gh` (no secrets in settings — consistent with the Safety NFR).
- **acs feature — guided architecture selection is select/refine over an acs-shipped catalog; it never overrides the user's decision, and the catalog source-of-truth is deferred (C-9).** The catalog **augments** `/acs:create-architecture` — it offers a pre-filtered/ranked shortlist across the four categories, and the **user still owns the final selection** (decision-support framing, consistent with the human-owns-requirement-decisions Vision). It **adds no new doc set** and does not change the architecture doc-set outputs. The **catalog source-of-truth and the selection/ranking UX are MECHANISM — deferred to the implementing epic's design phase.**

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
must invoke. Tracker-first / auto-authoring applies to the supported trackers only
(GitHub Projects / Jira via `gh` / `acli`); **this tracker-first / auto-authoring scope
stays limited to those trackers** (GitLab / Bitbucket are not additional tracker-first
sources here). This is distinct from GitLab/Bitbucket as a **general delivery-forge
target** (tracker import/sync, PR flow), which is now a **Could-have** (MAR-71) with a
tentative v0.7.0 home — see the acs Could-have "Non-GitHub forges (GitLab/Bitbucket)
support" and the Reversal note (MAR-71) above.

**Reversal note (MAR-35):** this amendment reverses the prior "tabp is skills-only"
product decision that was previously stated in this PRD and in MAR-26 design C-arch-5
(skills-only plugin shape). tabp remains a **FEATURE of the one GMS Marketplace
product** — a fuller feature, not a separate product. This does NOT re-introduce the
abandoned MAR-17 per-plugin-sub-product / separate-per-plugin-PRD approach. The tabp
feature section above replaces the skills-only framing with the fuller-plugin shape.
**Update (MAR-85):** the tabp-upgrade epic's core capabilities — `tabp settings.json`,
`.tabp/` workspace state, `/tabp:usage`, resumable runs, and the reflection/
self-verification (always-on verifier) engineering-rigor pattern — are **now shipped**
(verified on disk: `plugins/tabp/README.md`, `plugins/tabp/agents/*`,
`plugins/tabp/helpers/tabp_helper.py`, `plugins/tabp/schemas/*`); the tabp feature
section above records them as Must-have (shipped). Only the rich-Claude-artifact
rendering, the explicit recruiter-sign-off UX, and Claude Cowork-runtime verification
of the shipped shape remain unbuilt — these carry forward as tabp Should-have items
and are the scope of the tabp-upgrade epic's remaining follow-on work.

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
the Notion/remote-docs mechanisms. MAR-2 reversed **only the runtime clause**; the
GitLab/Bitbucket non-GitHub-forge Won't-have is **separately reversed by MAR-71** —
see the Reversal note (MAR-71) below.

**Reversal note (MAR-71):** this amendment reverses the prior "non-GitHub forges
(GitLab/Bitbucket)" acs Won't-have. Per MAR-71, **GitLab/Bitbucket become a Could-have**
— the delivery pipeline's tracker import/sync and PR flow extend to the additional
forges, with a **tentative version home at v0.7.0** (see roadmap M6 — v0.7.0; see the
acs Could-have "Non-GitHub forges (GitLab/Bitbucket) support" above). The **MECHANISM**
(forge API/auth mapping, MR-vs-PR semantics) is **deferred to the forge epic's design
phase**, mirroring the Notion/multi-runtime deferrals. This reversal does **not** reopen
any other Won't-have: Notion-only remote providers, ATS integrations, and the
wholesale-restructure guardrail all remain out of scope, unchanged.

Non-GitHub org-policy backends are out of scope — org enforcement targets the GitHub
org-controlled surface first (org rulesets / org-required workflows); other forges remain
Won't-have, consistent with the acs Won't-have above. Automatic org-wide migration or bulk
retrofitting of existing repos to an org policy is out of scope — applying org policy to a
repo is an opt-in/rollout action surfaced per repo, never an automatic mass rewrite (same
additive, no-wholesale-restructure discipline as C-2 above and the MAR-16..24 reset note
above). A general non-GitHub policy distribution system is out of scope.

Automatic downgrade of a ticket's complexity/supervision tier without explicit user
confirmation — tiers are always user-confirmed; the system never silently reduces rigor.
