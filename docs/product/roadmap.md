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

- **E1.1** — Headless `claude -p` scenario runner in a sandbox repo, asserting
  on workspace artifacts rather than prose output. *Scaffolded:*
  [`evals/`](../../evals/README.md) — tiered runner (free gate checks + paid
  `claude -p`), `Sandbox`/`Check` harness, 2 seed scenarios (both G1, green).
  Remaining: more scenarios (E1.3) and the nightly job (E1.4).
- **E1.2** — Description-trigger evals for all 12 skills (the right skill fires
  for a given request).
- **E1.3** — Per-goal assertion scenarios: zero gate escapes (G1),
  resume-from-state-only (G2), zero verifier findings within the 3-iteration
  cap (G3), PR ≤ ~400 changed lines (G4).
- **E1.4** — Nightly CI job with variance/flake handling.

### Epic E3 — Dogfood acs on acs

Traces all goals (proof by usage). Starts once M2-0 is green and E1 provides a
safety net.

- **E3.1** — First dogfood act: allocate real ticket ids for this M2 plan via
  `/acs:create-ticket` (the plan defines the epics; acs assigns the ids).
- **E3.2** — Every change to this repo ships via `/acs:ship`; PRD/architecture
  amendments via skill re-runs.
- **E3.3** — Publish per-ticket metrics roll-ups (G5 cost transparency in
  practice).

### Epic E2 — Tracker-sync depth *(parallel, lower priority)*

Traces the "team on a shared repo" persona. Independent of E1/E3 — slot in once
dogfooding is rolling.

- Conflict-resolution UX, bulk import, epic-link fidelity on Jira / GitHub
  Projects.

### Sequence & exit

```
M2-0 spike ─▶ (v0.1.1 if needed) ─▶ E1 harness ─▶ E3 dogfood ─▶ M2 exit
                                        └─────────▶ E2 tracker-sync (parallel)
```

**M2 exits → v0.2.0 when:** the eval harness is green nightly, ≥ 1 real acs
change has shipped via `/acs:ship`, and PRD metrics G1–G5 are measured on real
runs.

## M3 — GA (v1.0)

- **Epic: onboarding polish** — `/acs:init` guided flows, repo-detection
  heuristics, template gallery for descriptions.
- **Epic: documentation site** — rendered architecture doc set + usage
  walkthroughs.
- Semver stability promise for state-file schemas (migration notes per minor).

## Later / icebox

Scheduled background sync routines; cross-machine handoff via shared
workspace; GitLab/Bitbucket forges; additional marketplace plugins.
