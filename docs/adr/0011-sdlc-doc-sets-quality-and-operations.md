# 0011 — Full-SDLC doc sets: acs maintains quality and operations docs

**Status**: Proposed · **Date**: 2026-06-14

## Context

acs maintains a set of living docs for every consumer repo, each produced by a
skill: `product/` (`/create-prd`), `architecture/` (`/create-architecture`),
`adr/` + `requirements/` (`/create-design`, `/code`). The doc taxonomy was
extended to cover the **whole lifecycle** — adding `quality/` (verify) and
`operations/` (release & operate) — so the sets now span
define → specify → design → decide → verify → release & operate.

But those two new sets have **no producing skill**: today they exist only as
acs's *own* hand-written docs (the testing strategy, the release runbook). Every
other doc-set path in [`settings.schema.json`](../../plugins/acs/schemas/settings.schema.json)
corresponds to a skill that writes it; adding `quality_path`/`operations_path`
without deciding **who produces them** would be half a feature and inconsistent
with acs's model. This ADR settles that.

## Decision

1. **Treat `quality/` and `operations/` as methodology-led sets.** Their content
   is largely *how you test* and *how you release/operate* — more reusable
   methodology than per-product prose like a PRD. acs ships **templates** (a
   recommended testing strategy and a release/operations runbook set) under
   `plugins/acs/templates/`, and **bootstraps + lightly tailors** them to the
   consumer rather than generating from scratch.

2. **Producer: extend `/acs:create-architecture`.** It already consumes exactly
   the inputs these sets derive from — the PRD's NFRs, the codebase's tech stack,
   and the deployment view it already emits. Its charter widens from "how the
   system is *structured*" to "how the system is **built, verified, and
   operated**," emitting `quality/` and `operations/` as part of the same
   bootstrap/regenerate it already performs for `architecture/`. No new skill.

3. **Config:** add optional `quality_path` (default `docs/quality`) and
   `operations_path` (default `docs/operations`) to `settings.schema.json`;
   `/acs:init` collects/defaults them exactly like `architecture_path`.

4. **Living parts accrete later.** Per-feature test coverage already accretes in
   `requirements/` via `/code`; a coverage ledger in `quality/` and incident
   postmortems in `operations/` are deferred — bootstrap the strategy/runbooks
   first.

## Alternatives considered

- **New dedicated skills** (`/acs:create-quality`, `/acs:create-ops`) — rejected:
  more skill surface for content that derives from the same inputs
  `/create-architecture` already reads.
- **Pure agentic generation per product** — rejected for v1: the content is
  largely methodology; templates + light tailoring are leaner and more
  consistent with acs's existing `templates/` approach.
- **Scaffold only in `/acs:create-project`** (greenfield) — rejected as the sole
  mechanism: brownfield onboarding (the common path) also needs these sets, and
  `/create-architecture` runs for both greenfield and brownfield.

## Consequences

- `/acs:create-architecture`'s scope and verifier widen; its specs and
  living-architecture enforcement must cover the two new sets.
- Conformance gains two levels: `architecture → quality` (how it's verified) and
  `… → operations` (how it's shipped/run); a release ships only after the
  quality gate passes (see [release runbook](../operations/release-runbook.md)).
- `settings.schema.json` gains two optional paths; unset means "acs does not
  maintain this set for this repo" (forward-compatible, like `adr_path: null`).
- acs's *own* `quality/` and `operations/` docs become the reference instance of
  these templates — dogfooding the feature it ships.
- The behavioral eval harness (Epic E1) is the acs-internal realization of the
  `quality/` strategy; this ADR generalizes it into a consumer-facing capability.
