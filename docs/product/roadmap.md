# Roadmap — GMS Marketplace

> Milestones map to intended epics; each epic fans out into child tickets that
> ship through the pipeline. Maintained alongside the PRD via `/acs:create-prd`.

Each plugin has its own milestone track. M1/M2/M3 below are the **acs plugin**
track (v0.2.0 shipped; v0.3.0 in progress). The **tabp plugin** track follows
with T-M1 as the urgent next milestone. Future plugins add their own track here
without restructuring the existing tracks.

## acs plugin track

### M1 — Foundation (v0.1.x) — *implemented*

Epic-level scope (retrofit; built before dogfooding began):

- Marketplace + plugin skeleton (manifests, CI, release automation).
- Deterministic layer: hooks, gates, workspace/state, locks, metrics, helper CLIs.
- 14 skills + 27 agents with the reflection protocol, XML/XSD messaging, phase artifacts.
- Quality systems: grounding rules, clarification ledger, completion reports,
  size control, `docs_only`, e2e layer, living-architecture enforcement.
- Test suites: deterministic-layer integration tests + prose contract tests; CI green.

### M2 — Hardening (v0.2)

Sequenced, not flat: M1 proved only the deterministic layer (hooks, schemas,
Python units). The agentic behavior of the 12 skills is still unverified in a
real consumer repo, which orders the work below — validate by hand, then
systematize as evals, then dogfood. Tracker-sync runs as an independent,
lower-priority track. Goal references (G1–G6) point at
[`prd.md`](prd.md#goals--success-metrics).

#### M2-0 — Validation spike *(prerequisite, ~1 session)*

Traces G1, G2, G6. Install published v0.1.1 into a throwaway consumer repo; run
`/acs:init` → `/acs:create-ticket` → `/acs:ship` on a trivial change. Assert
that workspace partitions, hook gates (exit-2 blocks), and the PR flow match
the docs. Step-by-step runbook with per-step assertions:
[m2-0-validation-spike.md](spikes/m2-0-validation-spike.md).

> v0.1.1 was the first fast-follow: v0.1.0 failed to load on install
> (duplicate hooks reference), so v0.1.1 is the build the spike targets.

- **Done when:** a clean end-to-end run, or a logged defect list cut as a
  fast-follow **v0.1.2**. Gates the dogfood epic (E3).
- **Status (2026-06-13):** ✅ **green** — clean end-to-end run against v0.1.2
  (G1/G2/G6 observed, ~$2.43 measured for G5; one doc-only nit, no product
  defects). See the run record in
  [m2-0-validation-spike.md](spikes/m2-0-validation-spike.md#run-record).

#### Epic E1 — Behavioral eval harness *(M2 backbone)*

Traces G1, G3, G4, G5. The regression net that makes dogfooding and every
future change safe; built on what M2-0 learns by hand.

All four sub-epics are implemented in [`evals/`](../../evals/README.md): a tiered
runner (free deterministic checks + paid `claude -p`), a `Sandbox`/`Check`
harness asserting on workspace artifacts, and 6 scenarios covering G1–G4 plus
cleanup. Validated green against installed v0.1.2.

- **E1.1 (done)** — `claude -p` scenario runner + sandbox + artifact assertions;
  seed scenarios `install_gate_smoke` (free, G1) and `create_ticket_artifacts`
  (paid, G1).
- **E1.2 (done)** — `skill_triggers` (paid): one un-named request per skill
  routes to the right skill; all 12 green.
- **E1.3 (done)** — `resume_and_verify` (paid) covers G2 (resume-from-state),
  G3 (verifier-clean within the cap), and G4 (PR ≤ ~400 lines, as the seed
  diff); `session_end_safety_net` (free) covers the SessionEnd cleanup.
- **E1.4 (done)** — the **free** tier is wired into
  [`.pre-commit-config.yaml`](../../.pre-commit-config.yaml) as the
  `acs-free-evals` hook (gate + SessionEnd smoke, `$0`, no `claude`), running on
  every commit that touches the plugin or harness — locally and in the
  *Pre-commit hooks* CI job (`ACS_EVAL_SOURCE=1`, so it tests the committed
  source). The **paid** tier is a local, on-demand developer action; there is no
  dedicated eval CI workflow. (A 2026-06-14 CI dispatch had confirmed the full
  paid path runs green in CI before paid was moved local-only.)

#### Epic E2 — Tracker-sync depth *(parallel, lower priority)*

Traces the "team on a shared repo" persona. Independent of E1/E3 — slot in once
dogfooding is rolling.

- Conflict-resolution UX, bulk import, epic-link fidelity on Jira / GitHub
  Projects.

#### Epic E6 — Tracker-first delivery (PRD-optional mode) *(Must-have — urgent; builds on E2)*

Traces **G11** (+ the Team-with-a-tracker-only-PO persona) and the acs Must-have
**Tracker-first delivery (PRD-optional mode)** feature
([`prd.md`](prd.md#features-moscow)). Builds on E2's import/sync depth: a team with
**no PRD/roadmap/architecture** delivers a remote-tracker-defined ticket through the
**same gated pipeline**.

- **E6.1 — Configurable governance mode.** A setting that turns on tracker-first /
  PRD-optional delivery; when upstream docs are absent the imported tracker issue
  (description + acceptance criteria) is the requirement source of truth. *(Config key
  name + explicit-opt-in vs auto-detect resolved in this epic's design phase.)*
- **E6.2 — Graceful conformance-chain degradation.** A missing upstream artifact
  (PRD/architecture) makes only its own trace step N/A — never a hard block — while
  gates (TDD, coverage, review, audit, merge readiness) stay unchanged.
- **E6.3 — Divergence behavior (C-3).** No PRD ⇒ tracing N/A, tracker governs,
  nothing flagged; PRD present ⇒ keep today's behavior (trace, flag divergence, user
  decides).
- **E6.4 — Validation.** Prove a PRD-less repo delivers a tracker-defined ticket
  end-to-end with 0 gate escapes and 0 missing-upstream hard-blocks (G11 metric).

Opt-in reverse-bootstrap (seeding a baseline `prd.md`/architecture from imported
tickets + codebase) is a Could-have growth path; it is not part of this milestone and
has no separate milestone — tracker-first delivery works without it.

**Deferral:** the MECHANISM (config key, opt-in vs auto-detect, design-step
optionality) is determined in this epic's design phase; this milestone states what
to deliver. E6 builds on E2.

#### Epic E5 — Convention enforcement & onboarding/repo hardening *(shipped in v0.2.0)*

Traces G9 (+ the Tech-lead persona). The v0.2.0 release that this roadmap entry
records — what actually shipped under the M2 hardening banner. Delivers the PRD
Must-have convention-enforcement, `/acs:install-hooks`, and Step 0b preflight
features.

- **E5.1 — Step 7c repo-side CI convention check.** `/acs:init` Step 7c scaffolds
  `.github/workflows/acs-conventions.yml` backed by a stdlib-only
  `.acs/ci/check-conventions.py` (fail-closed; modes `pr` / `pre-push` /
  `commit-msg`), config-driven local git hooks (`commit-msg` + `pre-push`), and a
  new `enforcement` settings block
  (`checks.{branch_name,pr_title,pr_description,acs_label,commit_message}`,
  `require_label`, `exempt_label` default `acs-exempt`, `exempt_branches`,
  `pr_description_sections`). Observed live on this repo: ruleset 17602044 is
  `active` on `main` with "Branch / PR / commit conventions" among the required status-check
  contexts (`gh api repos/:owner/:repo/rulesets/17602044`).
- **E5.2 — `/acs:install-hooks` skill** + committed `.acs/ci/install-hooks.sh`.
  The per-clone `pre-commit install` equivalent for acs; the committed script
  lets teammates install the local hooks without the plugin.
- **E5.3 — `/acs:init` Step 0b toolchain preflight.** Detects and offers to
  install `git`, `python3`, `gh`, `pre-commit`, `xmllint`, `acli` with
  per-platform install commands, so onboarding fails up front with consent.
- **E5.4 — Repo hardening.** This repo is public under the MIT `LICENSE`; a branch
  ruleset on `main` requires a PR with squash-only merges, linear history,
  non-fast-forward protection, and the required status checks (Branch / PR / commit
  conventions, secret scan, pre-commit hooks, tests); secret scanning + push
  protection are enabled; Dependabot runs alerts, security updates, and version
  updates. The default `GITHUB_TOKEN` workflow permission is **read**, and
  Actions are restricted to a selected allowlist (`allowed_actions=selected`,
  `github_owned_allowed=true`, `verified_allowed=true`,
  `patterns_allowed=["pre-commit/action@*"]`) — confirmed live via
  `gh api repos/:owner/:repo/actions/permissions` and
  `.../actions/permissions/workflow`; re-confirmable the same way.
- **E5.5 — Escape-hatch merge path + pipeline-as-default guidance (MAR-9, PR #50 — pending merge).**
  Completes the consumer side of the G9 escape hatch and makes the pipeline the default
  rather than only the gate. `/acs:merge-pr --pr <n>` (also `#n` / a PR URL) lands a
  legitimate non-ticket `acs-exempt` PR — same four readiness dimensions and
  branch/worktree cleanup as the ticket path, but resolving no ticket, writing no
  partition/state, and skipping tracker sync and archiving (bumping only the repo
  `pr_merged` metric); it refuses and redirects when the PR is actually ticket-backed.
  `/acs:init` Step 7e (opt-in, default-on) writes an idempotent, marker-delimited
  `CLAUDE.md` acs-managed block (from `templates/CLAUDE.acs.md`) steering in-repo
  Claude sessions to `/acs:ship` rather than a raw `gh pr create`. Pending merge in
  PR #50; targeted for a v0.2.x release.

#### Epic E3 — Dogfood acs on acs

Traces all goals (proof by usage). Starts once M2-0 is green and E1 provides a
safety net.

- **E3.1** — First dogfood act: allocate real ticket ids for this M2 plan via
  `/acs:create-ticket` (the plan defines the epics; acs assigns the ids).
- **E3.2** — Every change to this repo ships via `/acs:ship`; PRD/architecture
  amendments via skill re-runs.
- **E3.3** — `acs:metrics` skill delivery: implement the dashboard skill reading workspace artifacts; render the six panels (throughput, funnel, cost/time per step, coverage vs target, review iterations, token burn by role); ship as a new skill in the `acs` plugin. Traces G5, G7.
- **E3.4** — Status-line refinement (dogfood-driven): both the prompt line and the reflection agent-panel compose with Claude Code's default status line and add acs state on top (default context + acs pipeline/subagent state) instead of replacing it; ships as a maturing refinement to the v0.1 Should-have status-line feature. Traces G7.

#### Epic E4 — `acs:metrics` dashboard *(gates on E1)*

Traces G5, G7. Starts once E1 (eval harness) is green — behavioral evals for
the `acs:metrics` skill land in E1 before the skill ships.

- **E4.1** — Skill skeleton + data-source wiring (`metrics.json`, `tickets-index.json`, `pipeline-state.json`, `code-state.json`, `create-pr-state.json`).
- **E4.2** — Six dashboard panels implemented and rendered via `show_widget` inline in the Claude Code session.
- **E4.3** — Edge cases: empty workspace, tickets with missing state files, performance target (≤ 5 s for ≤ 50 tickets).
- **E4.4** — Documentation: skill description, usage example in plugin README and `docs/`.

#### Sequence & exit

```
M2-0 spike ─▶ (v0.1.2 if needed) ─▶ E1 harness ─▶ E5 enforcement + hardening ─▶ v0.2.0
                                       │                                          └▶ E2 tracker-sync (parallel)
                                       └▶ E3 dogfood ─▶ E4 acs:metrics ─▶ v0.3.0
```

**M2 exits → v0.2.0 when:** the eval harness is green (E1), the convention-
enforcement + `/acs:install-hooks` + Step 0b preflight features ship (E5), and
the repo is hardened (public/MIT, branch ruleset with required checks, secret
scanning + push protection, Dependabot, read-only `GITHUB_TOKEN` + Actions
allowlist). *(Shipped.)*

**Exits → v0.3.0 when:** ≥ 1 real acs change has shipped via `/acs:ship` (E3
dogfood), PRD metrics G1–G5 and G7 are measured on real runs, and the
`acs:metrics` dashboard skill ships and passes evals (E4).

### M3 — GA (v1.0)

- **Epic: onboarding polish** — `/acs:init` guided flows, repo-detection
  heuristics, template gallery for descriptions.
- **Epic: documentation site** — rendered architecture doc set + usage
  walkthroughs.
- **Epic: full-SDLC verify & operate** — acs maintains the `quality/` and
  `operations/` doc sets for consumers via `/acs:create-quality` and
  `/acs:create-operations` (test strategy + release/ops runbooks, from
  templates), and adds **`/acs:test`** — a standing, schedulable skill that runs
  the product's suites, triages regressions, and opens a ticket per failure
  (closed loop). `settings.schema.json` gains `quality_path`/`operations_path`
  and a `suites` map; `/acs:init` defaults them. Skill count 14 → 17. Traces
  **G8**. Design: [ADR 0011](../adr/0011-sdlc-doc-sets-quality-and-operations.md).
  All design skills also gain a shared **design-time consistency step** — detect
  doc gaps/staleness across the graph and recommend adjustments in-session, no
  separate tooling ([ADR 0012](../adr/0012-design-time-doc-consistency.md)).
- **Epic: principles & standards doc layer + brownfield standardization** — acs
  maintains two more living doc sets for consumers: **principles/** (engineering
  principles, e.g. `/acs:create-principles`) and **standards/** (coding
  standards/conventions, e.g. `/acs:create-standards`), each a product-level
  producer with templates and a planner/executor/verifier triad, following ADR
  0011's one-skill-per-set pattern. The sets extend the conformance chain to
  **PRD → architecture → standards → design → specs → code** — design and code
  verifiers check conformance (no silent waivers). `/acs:create-architecture`'s
  output set gains a **project-structure target** document (intended repo layout
  from the C4 views). A new brownfield skill **`/acs:standardize-project`**
  (separate from greenfield-only `/acs:create-project`) audits an existing repo
  against its standards docs, that project-structure target, and acs-readiness
  tooling, then **additively** sets up the missing docs/config/tooling as one
  reviewed PR — **never moving or renaming existing source**; structural gaps
  become recommended follow-up tickets (additive-only guardrail, C-2). Maps to
  PRD G10 and the acs Could-have features. `settings.schema.json` gains
  `principles_path`/`standards_path`; `/acs:init` defaults them. Skill count grows
  accordingly. Traces **G10** (+ the Tech-lead persona).
- **Epic: enforceable e2e integrity (opt-in merge gate + brownfield e2e scaffolding)** — extends the already-shipped opt-in e2e layer (M1) with enforcement and brownfield onboarding. Three deliverables:
  - **E2E-1 — Optional required e2e merge gate.** `/acs:init` scaffolds a repo-side e2e CI workflow + runner from `settings.e2e` and, opt-in, wires it as a REQUIRED status check on the protected default branch — a red e2e becomes a fail-closed merge brake (symmetric to E5's convention gate and the coverage hard-fail), making `/acs:merge-pr`'s report-only CI read enforceable via branch protection. Maps to PRD acs Should-have (e2e bullet). Traces **G13**, **G9**.
  - **E2E-2 — Brownfield e2e scaffolding via `/acs:standardize-project`.** The greenfield-only `/acs:create-project` e2e scaffolding gains a brownfield counterpart: `/acs:standardize-project` additively scaffolds the e2e CI workflow + runner for an EXISTING repo that lacks one, as part of its one reviewed PR — never moving or renaming source (C-2). Maps to PRD acs Could-have (`/acs:standardize-project`). Traces **G13**, **G10**.
  - **E2E-3 — Measured e2e integrity (G13).** Validate the metric on the dogfood repo: 0 PRs merged with a red e2e suite (gate enabled) and 100% of user-facing-surface specs declare e2e impact, per release. Maps to PRD **G13**.
  The opt-in invariant holds throughout: `settings.e2e` unset = no e2e suite, no gate.
- **Epic: configurable doc-set storage location** — each acs doc set
  (`prd`, `architecture`, `requirements`, `adr`, and future `standards`/`principles`/
  `quality`/`operations`) is independently relocatable to an external/absolute
  filesystem path outside the consumer repo via configuration; one doc-set
  storage-location config surface generalizes the existing `*_path` keys; producer
  skills resolve the configured location and preserve a reviewable diff there. Same
  family as the `principles_path`/`standards_path`/`quality_path`/`operations_path`
  path-config work above. Maps to PRD extended G6 and the acs Could-have
  configurable-doc-set-storage-location feature.
- **Epic: org-level enforcement policy (org & department layers)** — acs gains an ordered
  **policy-source chain** above today's user + team(project) layers. An organization (and
  optionally a department/sub-group) defines **shared defaults** (overridable convenience
  config, resolved most-specific-wins by extending the existing cascade) and **enforcement
  mandates** (non-overridable floors — required convention/security/standards checks; repo
  may tighten not loosen; no repo self-exemption; org-granted, audited exemptions; rule
  provenance). The enforceable part comes from an org-controlled source the repo cannot
  edit (e.g. GitHub org rulesets / org-required workflows / a versioned policy pack) and/or
  inverted floor precedence — never a developer-home file. Additive and non-breaking
  (no org source ⇒ today's behavior). Connects to the standards layer (org policy can
  mandate G10 conformance as a floor once it ships). Maps to PRD **G12** and the new acs
  Could-have feature. The MECHANISM is settled in this epic's **design phase / an ADR**,
  consistent with how the tabp-upgrade and standards epics defer mechanism. Traces **G12**
  (+ the Org/Platform-admin persona).
- **Epic: complexity-adaptive delivery** — acs scales process to ticket complexity ×
  human supervision (three tiers: trivial / standard / complex-unattended). Maps to PRD
  **G14, G15, G16** and the acs Must-have **Complexity-adaptive delivery** feature
  ([`prd.md`](prd.md#features-moscow)). Parallel to the other M3 epics above; independent
  of the doc-set and standards work (touches pipeline process-volume, not the doc-set
  surface). Child workstreams (sequenced):
  1. **Trivial fast-lane** — fuse create-spec into code, human-approval gate, skip the
     verifier subagent for trivial-tier supervised tickets.
  2. **Conditional verification model** — make the independent-verifier subagent role
     conditional on stakes + supervision; the code TDD/coverage gate always stays
     regardless of tier.
  3. **Apply-tier inlining** — sequence **merge-pr first** (its existing exempt-PR mode,
     E5.5 / MAR-9, already runs the inline coordinator+executor shape as a working
     template), then **create-pr**, then **create-ticket**.
  4. **In-process / batched XML validation + clarify batching** — replace per-send/receive
     `validate_xml.py` subprocess spawns with in-process/batched validation; batch
     `clarify.py` record-before-act calls.
  5. **create-ticket complexity-tier flag** — set the user-confirmed tier at ticket
     creation, alongside `needs_design` (C-7 precedent).
- Semver stability promise for state-file schemas (migration notes per minor).

## tabp plugin track

### T-M1 — screen-cvs *(URGENT — next milestone)*

Maps to PRD: [`prd.md`](prd.md#features-moscow)
tabp Must-have screen-cvs feature and metrics T1–T5.

Deliver the screen-cvs capability in Claude Cowork or Claude Code:

- **JD parsing** — parse a job description into must-have vs nice-to-have requirements.
- **Evidence-based scoring** — per requirement: Met/Partial/Missing determination with
  explicit CV evidence cited for each judgment.
- **Weighted match score** — 0–100 overall score; missing a must-have requirement caps
  the result regardless of nice-to-have scores.
- **Band + recommendation** — Strong/Moderate/Weak band with a Recommend/Hold/Reject
  recommendation per CV.
- **Output artifacts** — inline summary per CV + two-sheet Excel scorecard (one sheet
  per-requirement breakdown, one sheet ranked summary for batch runs).
- **Fairness guardrails** — job-relevant criteria only; decision-support framing
  (tool assists, does not decide); bias-relevant JD flags surfaced.
- **Batch fan-out** — one Sonnet subagent per CV with Opus synthesis for the final
  ranked summary.
- **Input handling** — reads CVs and JD from the project folder; falls back to
  chat attachments.

**Success exit (release gate + ongoing adoption):**

| Metric | Gate type | Target |
|--------|-----------|--------|
| T1 — Speed | Adoption (1 month) | 20-CV batch ≥ 70% faster than manual |
| T2 — Reproducibility | Release gate (per release) | ≥ 95% on fixed 10-CV set |
| T3 — Evidence/auditability | Release gate (every run) | 100% judgments cite evidence + scorecard |
| T4 — Fairness | Release gate (per release) | 0 protected/proxy criteria; 100% bias-relevant flags on ≥ 15-pair set |
| T5 — Adoption | Ongoing (3 months) | ≥ 80% of new TABP role openings use screen-cvs |

**Implementation note:** the tabp plugin build (plugin.json, screen-cvs skill,
`marketplace.json` entry, CI version-coupling removal) is a **separate follow-up
ticket** — this roadmap entry defines what to deliver and how to measure success;
the implementation ticket carries the build work.

### T-M2 — tabp upgrade *(future — pending tabp-upgrade epic)*

Maps to PRD: [`prd.md`](prd.md#features-moscow)
tabp re-scoped Must-have capabilities and the engineering-rigor NFR (MAR-35 amendment).

Deliver the fuller tabp plugin capabilities in tabp's own namespace:

- **tabp settings.json** — configurable models and default CV/JD folder paths; stored
  in the project folder.
- **.tabp/ workspace state** — run history and a per-screening archive (the `.xlsx`
  scorecard and a JSON record per run); persisted in the project folder.
- **/tabp:usage skill** — per-run usage metrics: cost, time, and tokens.
- **Resumable runs** — all intermediate states persisted as a human-reviewable audit
  trail; the run can be resumed from the persisted state.
- **Rich Claude artifact** — results rendered as a rich Claude artifact for recruiter
  review.
- **Recruiter review** — completed result presented for recruiter sign-off.

**Engineering-rigor NFR:** the tabp upgrade adopts proven quality patterns in tabp's
own namespace: coordinator-plus-subagents (the Sonnet-per-CV + Opus-synthesis shape),
reflection/self-verification before presenting results, structured JSON state,
source-grounded evidence (anti-hallucination), and decision recording for human review.
No `acs` naming or `acs:` prefixes in tabp's surface.

**Deferral:** the MECHANISM (instruction-driven vs hook-gated) and verification of
what both runtimes (Claude Cowork and Claude Code) actually support (config resolution,
hooks, artifacts, self-reported cost/tokens) are deferred to this epic's design phase.

**Implementation note:** the tabp-upgrade design and build are a separate future epic —
this milestone defines what to deliver; the design and implementation tickets carry
the build work.

### acs M-future — Notion/remote-docs backend *(future — pending Notion/remote-docs epic)*

Maps to PRD extended G6 and the acs Could-have pluggable-remote-docs-backend feature.

Deliver a pluggable docs backend for acs, mirroring the `tracker.provider` precedent:

- **`local` backend (filesystem, default)** — current behavior, unchanged; supports
  external/absolute paths (delivered in M3 above).
- **`notion` backend (first remote provider)** — Notion as the system of record or
  sync target; two configurable modes per backend:
  - **Publish/mirror** — repo stays source of truth, the docs-only PR is preserved,
    content synced to Notion for reading.
  - **Authoritative-remote** — Notion is the system of record, no repo copy,
    review/audit happens in Notion.
- Auth via external CLI/integration; **no secrets in settings** (consistent with the
  `tracker.provider` precedent and the Safety NFR).

**Deferral:** the MECHANISM — Notion API/auth, markdown→Notion-blocks mapping, PR-less
vs sync delivery, per-mode review/audit implementation — is deferred to this epic's
dedicated design phase. This epic requires its own `/acs:create-design` run before
implementation begins. Non-Notion remote providers (Confluence, Google Docs, SharePoint)
are Won't-have now; they may be considered as future extensions after this epic ships.

**Implementation note:** this is a future epic pending design — this milestone entry
defines what to deliver and its scope boundary; the design and implementation tickets
carry the build work.

### acs M-future — Multi-runtime support (OpenAI Codex CLI) *(future — pending multi-runtime epic)*

Maps to PRD extended G6 (runtime portability) and the acs Could-have **Multi-runtime
support — OpenAI Codex CLI** feature ([`prd.md`](prd.md#features-moscow)). Reverses the
prior acs "non-Claude-Code runtimes" Won't-have (Reversal note MAR-2).

Make the acs gated pipeline runnable on **OpenAI Codex CLI** in addition to Claude Code:

- **Runtime abstraction.** Identify which pipeline mechanisms are Claude-Code-specific
  (PreToolUse/SessionEnd hook gating, the planner/executor/verifier reflection-subagent
  protocol, skill/agent dispatch, per-role model/effort config, self-reported
  cost/tokens) vs runtime-agnostic (the stdlib-only deterministic layer: gating, state,
  ids, metrics, convention checks).
- **Codex CLI runtime adapter.** Map each Claude-Code-specific mechanism onto Codex
  CLI's equivalents (or a portable shim), preserving the **same gates** — 0 gate
  escapes, full audit trail — on the second runtime.
- **Validation (extended G6).** Publish an end-to-end run of the acs pipeline on Codex
  CLI with 0 gate escapes and 0 lost audit-trail artifacts, within 1 release of the
  capability shipping (the G6 runtime-portability metric).

**Deferral:** the MECHANISM (the hook-gating / subagent-protocol / dispatch mapping and
which gates are native vs shimmed on Codex CLI) is deferred to this epic's dedicated
design phase / an ADR; this epic requires its own `/acs:create-design` run before
implementation. Mirrors the Notion/remote-docs and tabp-upgrade deferrals.

**Implementation note:** this is a future epic pending design — this entry defines what
to deliver and its scope boundary; the design and implementation tickets carry the build.

## Later / icebox

Scheduled background sync routines; cross-machine handoff via shared
workspace; GitLab/Bitbucket forges; additional marketplace plugins.
