# 0011 — Full-SDLC doc sets (quality, operations) + standing test runs

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
without deciding **who produces them** would be half a feature. This ADR settles
that.

## Decision

1. **One skill per doc set — two new product-level skills.** Following acs's
   existing pattern (`/create-prd` → `product/`, `/create-architecture` →
   `architecture/`), add:
   - **`/acs:create-quality`** → `quality/` (test strategy, coverage policy)
   - **`/acs:create-operations`** → `operations/` (release process, runbooks,
     observability, incident response)

   Each is a product-level skill with its own planner/executor/verifier triad,
   gated and hooked like the other doc-set producers. We deliberately **do not**
   overload `/create-architecture` with extra sets — keeping one skill per set
   means each set is regenerated independently and each skill stays focused.

2. **Methodology-led, template-first.** Their content is largely *how you test*
   and *how you release/operate* — more reusable methodology than per-product
   prose. acs ships **templates** (a recommended testing strategy and a
   release/operations runbook set) under `plugins/acs/templates/`; the skills
   **bootstrap + lightly tailor** them to the consumer (its test framework,
   distribution, deployment) rather than generating from scratch.

3. **Inputs:** both skills read the PRD's NFRs and the `architecture/` set (tech
   stack, deployment) as upstream context — so conformance gains
   `architecture → quality` and `architecture → operations`.

4. **Config:** add optional `quality_path` (default `docs/quality`) and
   `operations_path` (default `docs/operations`) to `settings.schema.json`;
   `/acs:init` collects/defaults them like `architecture_path`. Unset means "acs
   does not maintain this set for this repo" (forward-compatible, like
   `adr_path: null`).

5. **Living parts accrete later.** Per-feature coverage already accretes in
   `requirements/` via `/code`; a coverage ledger in `quality/` and incident
   postmortems in `operations/` are deferred — bootstrap the strategy/runbooks
   first.

6. **Add `/acs:test` — standing, scheduled product verification.** Distinct from
   the per-ticket `/code` reflection-verifier and from the doc producers above,
   `/acs:test` *runs* the product's configured suites
   (unit/integration/e2e/regression), writes an auditable results artifact,
   **triages** failures into a regression summary, and **opens an acs ticket per
   regression** to drive the fix (closed loop). It is a non-ticket utility skill
   (unhooked, like `/init`/`/update`) and is the **execution counterpart** to
   `/create-quality`: that skill writes the test *strategy* (`quality/`),
   `/acs:test` runs the tests the strategy describes.
   - **Config:** generalize the existing `e2e` setting into a `suites` map
     (named commands with optional setup/teardown); `/acs:test` runs all or a
     selected subset.
   - **Cadence:** daily/regression runs come from scheduling `/acs:test` headless
     via Claude Code routines/cron — acs does **not** build its own scheduler;
     the scheduling recipe lives in `operations/`.
   - **Reporting:** results feed the planned `acs:metrics` dashboard (G7).

## Alternatives considered

- **Extend `/acs:create-architecture`** to emit all three sets — *rejected*:
  overloads one skill with distinct concerns ("how it's structured" vs. "how
  it's verified / operated") and couples regeneration of unrelated sets. (This
  was the first draft of this ADR; the one-skill-per-set rule won.)
- **A single combined skill** (`/create-ops-docs` for both new sets) —
  *rejected*: verify and release/operate are distinct lifecycle concerns; one
  skill per set keeps each focused and independently regenerable.
- **Pure agentic generation per product** — *rejected* for v1: the content is
  largely methodology; templates + light tailoring are leaner and match acs's
  existing `templates/` model.
- **Scaffold only in `/acs:create-project`** (greenfield) — *rejected* as the
  sole mechanism: brownfield onboarding also needs these sets.
- **Build a scheduler into acs** (for the daily `/acs:test` runs) — *rejected*:
  Claude Code routines/cron already schedule headless skill runs; acs stays a
  set of *schedulable* skills rather than owning a scheduler.
- **Run the suite without triage** (a bare `cron pytest`) — *rejected*: the
  model's value is turning failures into a regression summary + tickets, not
  just an exit code; a deterministic-only run needs no acs skill.

## Consequences

- Three new skills (`create-quality`, `create-operations`, `test`) — the two
  doc producers carry a planner/executor/verifier triad, `test` is a utility
  skill; the skill count goes **12 → 15**. Touches: `settings.schema.json`
  (`quality_path`/`operations_path` + a `suites` map), `/init`, the dispatcher +
  pre/post hooks (`HOOKED_SKILLS`), `templates/`, the contract tests, the plugin
  README skill table, and the architecture C4 docs.
- `/acs:test` runs unattended on a schedule (Claude Code routines/cron) and, on
  regression, invokes the create-ticket flow (like `/ship` orchestrates other
  skills); its results feed `acs:metrics`. The scheduling recipe is documented
  in `operations/`.
- A release ships only after the [quality](../operations/release-runbook.md)
  gate passes; `operations/` is the home for the release/observability runbooks.
- acs's *own* `quality/` and `operations/` docs become the reference instance of
  these templates — dogfooding the feature it ships.
- The behavioral eval harness (Epic E1) is the acs-internal realization of the
  `quality/` strategy; this ADR generalizes it into a consumer-facing capability.
