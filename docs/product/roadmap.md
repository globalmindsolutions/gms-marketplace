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
- Semver stability promise for state-file schemas (migration notes per minor).

## tabp plugin track

### T-M1 — screen-cvs *(URGENT — next milestone)*

Maps to PRD: [`prd.md`](prd.md#features-moscow)
tabp Must-have screen-cvs feature and metrics T1–T5.

Deliver the screen-cvs capability in Claude Cowork:

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
- **Input handling** — reads CVs and JD from the Cowork project folder; falls back to
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
  in the Cowork project folder.
- **.tabp/ workspace state** — run history and a per-screening archive (the `.xlsx`
  scorecard and a JSON record per run); persisted in the Cowork project folder.
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
what the Cowork runtime actually supports (config resolution, hooks, artifacts,
self-reported cost/tokens) are deferred to this epic's design phase.

**Implementation note:** the tabp-upgrade design and build are a separate future epic —
this milestone defines what to deliver; the design and implementation tickets carry
the build work.

## Later / icebox

Scheduled background sync routines; cross-machine handoff via shared
workspace; GitLab/Bitbucket forges; additional marketplace plugins.
