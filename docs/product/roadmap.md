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

- **Epic: behavioral eval harness** — headless `claude -p` scenario suite in a
  sandbox consumer repo asserting on workspace artifacts; description-trigger
  evals for all 12 skills; nightly CI job.
- **Epic: tracker-sync depth** — conflict-resolution UX, bulk import, epic
  link fidelity on Jira/GitHub Projects.
- **Epic: dogfood acs on acs** — every change to this repo ships via
  `/acs:ship`; PRD/architecture amendments via re-runs; metrics published.

## M3 — GA (v1.0)

- **Epic: onboarding polish** — `/acs:init` guided flows, repo-detection
  heuristics, template gallery for descriptions.
- **Epic: documentation site** — rendered architecture doc set + usage
  walkthroughs.
- Semver stability promise for state-file schemas (migration notes per minor).

## Later / icebox

Scheduled background sync routines; cross-machine handoff via shared
workspace; GitLab/Bitbucket forges; additional marketplace plugins.
