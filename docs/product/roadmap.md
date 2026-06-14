# Roadmap — acs

> Milestones map to intended epics; each epic fans out into child tickets that
> ship through the pipeline. Maintained alongside the PRD via `/acs:create-prd`.

## M1 — Foundation (v0.1.x) — *implemented*

Epic-level scope (retrofit; built before dogfooding began):

- Marketplace + plugin skeleton (manifests, CI, release automation).
- Deterministic layer: hooks, gates, workspace/state, locks, metrics, helper CLIs.
- 12 skills + 27 agents with the reflection protocol, XML/XSD messaging, phase artifacts.
- Quality systems: grounding rules, clarification ledger, completion reports,
  size control, `docs_only`, e2e layer, living-architecture enforcement.
- Test suites: deterministic-layer integration tests + prose contract tests; CI green.

## M2 — Hardening (v0.2)

Sequenced, not flat: M1 proved only the deterministic layer (hooks, schemas,
Python units). The agentic behavior of the 12 skills is still unverified in a
real consumer repo, which orders the work below — validate by hand, then
systematize as evals, then dogfood. Tracker-sync runs as an independent,
lower-priority track. Goal references (G1–G6) point at
[`prd.md`](prd.md#goals--success-metrics).

### M2-0 — Validation spike *(prerequisite, ~1 session)*

Traces G1, G2, G6. Install published v0.1.1 into a throwaway consumer repo; run
`/acs:init` → `/acs:create-ticket` → `/acs:ship` on a trivial change. Assert
that workspace partitions, hook gates (exit-2 blocks), and the PR flow match
the docs. Step-by-step runbook with per-step assertions:
[m2-0-validation-spike.md](m2-0-validation-spike.md).

> v0.1.1 was the first fast-follow: v0.1.0 failed to load on install
> (duplicate hooks reference), so v0.1.1 is the build the spike targets.

- **Done when:** a clean end-to-end run, or a logged defect list cut as a
  fast-follow **v0.1.2**. Gates the dogfood epic (E3).
- **Status (2026-06-13):** ✅ **green** — clean end-to-end run against v0.1.2
  (G1/G2/G6 observed, ~$2.43 measured for G5; one doc-only nit, no product
  defects). See the run record in
  [m2-0-validation-spike.md](m2-0-validation-spike.md#run-record).

### Epic E1 — Behavioral eval harness *(M2 backbone)*

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

### Epic E2 — Tracker-sync depth *(parallel, lower priority)*

Traces the "team on a shared repo" persona. Independent of E1/E3 — slot in once
dogfooding is rolling.

- Conflict-resolution UX, bulk import, epic-link fidelity on Jira / GitHub
  Projects.

### Epic E3 — Dogfood acs on acs

Traces all goals (proof by usage). Starts once M2-0 is green and E1 provides a
safety net.

- **E3.1** — First dogfood act: allocate real ticket ids for this M2 plan via
  `/acs:create-ticket` (the plan defines the epics; acs assigns the ids).
- **E3.2** — Every change to this repo ships via `/acs:ship`; PRD/architecture
  amendments via skill re-runs.
- **E3.3** — `acs:metrics` skill delivery: implement the dashboard skill reading workspace artifacts; render the six panels (throughput, funnel, cost/time per step, coverage vs target, review iterations, token burn by role); ship as a new skill in the `acs` plugin. Traces G5, G7.
- **E3.4** — Status-line refinement (dogfood-driven): both the prompt line and the reflection agent-panel compose with Claude Code's default status line and add acs state on top (default context + acs pipeline/subagent state) instead of replacing it; ships as a maturing refinement to the v0.1 Should-have status-line feature. Traces G7.

### Epic E4 — `acs:metrics` dashboard *(gates on E1)*

Traces G5, G7. Starts once E1 (eval harness) is green — behavioral evals for
the `acs:metrics` skill land in E1 before the skill ships.

- **E4.1** — Skill skeleton + data-source wiring (`metrics.json`, `tickets-index.json`, `pipeline-state.json`, `code-state.json`, `create-pr-state.json`).
- **E4.2** — Six dashboard panels implemented and rendered via `show_widget` inline in the Claude Code session.
- **E4.3** — Edge cases: empty workspace, tickets with missing state files, performance target (≤ 5 s for ≤ 50 tickets).
- **E4.4** — Documentation: skill description, usage example in plugin README and `docs/`.

### Sequence & exit

```
M2-0 spike ─▶ (v0.1.2 if needed) ─▶ E1 harness ─▶ E3 dogfood ─▶ E4 acs:metrics ─▶ M2 exit
                                                  └──────────────▶ E2 tracker-sync (parallel)
```

**M2 exits → v0.2.0 when:** the eval harness is green nightly, ≥ 1 real acs
change has shipped via `/acs:ship`, PRD metrics G1–G5 and G7 are measured on real
runs, and the `acs:metrics` dashboard skill ships and passes evals.

## M3 — GA (v1.0)

- **Epic: onboarding polish** — `/acs:init` guided flows, repo-detection
  heuristics, template gallery for descriptions.
- **Epic: documentation site** — rendered architecture doc set + usage
  walkthroughs.
- Semver stability promise for state-file schemas (migration notes per minor).

## Later / icebox

Scheduled background sync routines; cross-machine handoff via shared
workspace; GitLab/Bitbucket forges; additional marketplace plugins.
