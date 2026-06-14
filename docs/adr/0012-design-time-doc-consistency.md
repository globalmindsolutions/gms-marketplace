# 0012 — Design-time doc-consistency: gap & staleness analysis in the design skills

**Status**: Proposed · **Date**: 2026-06-14

## Context

acs maintains a graph of doc sets — `product → architecture →
{design → spec → code → requirements}`, plus `quality` and `operations`
([ADR 0011](0011-sdlc-doc-sets-quality-and-operations.md), conformance direction
in [docs/README](../README.md)). Each set is produced by a skill. A change to any
doc can **stale** its dependents or leave **coverage gaps**, and the more sets
there are, the wider that drift surface.

The skills already check their *own immediate* conformance (specs → design,
features → goals) and are charged with "updating all affected documentation."
What's missing is detecting cross-set drift **early — while the user is doing
design work**, not after. Detached mechanisms for this were considered and
rejected (see below): they decouple detection from the design moment and add
surface.

## Decision

Make doc-consistency a **built-in step of the design-producing skills**:
`/create-prd`, `/create-architecture`, `/create-design`, `/create-spec`, and the
new `/create-quality` and `/create-operations`. Add a **shared analysis step to
their planner phase** (the same way the grounding section is shared across
agents):

1. **Read the related slice of the doc graph** — the upstream sets the skill
   derives from and the downstream sets that derive from it — using the existing
   trace links (features → goals, specs → design → architecture, …) and the
   conformance direction.
2. **Detect gaps** (missing required edges: orphan goal, uncovered feature,
   undesigned ticket, architecture component with no quality/operations
   coverage) and **staleness** (downstream that no longer conforms to the
   upstream it traces to).
3. **Surface findings + recommended adjustments to the user in-session**, through
   the existing clarification-ledger / findings mechanism, *before/while*
   producing output — e.g. "amending G3 leaves `architecture/overview` and
   `quality/strategy` stale; recommend updating sections X, Y."
4. The user decides; the skill then **updates the affected docs as part of the
   same change** and its verifier confirms the result is consistent.

No new skill, no CI check, no pre-commit hook — detection rides the design skills
the user already runs.

## Alternatives considered

- **A dedicated `/acs:doctor` command** — *rejected*: decouples detection from
  the design moment and relies on the user remembering to run it; extra surface.
- **A `docs/` pre-commit hook + CI gate** — *rejected*: catches drift only at
  commit/PR, *after* the design decision is made; cheap link-checking is narrow
  (it resolves references but misses semantic gaps); adds tooling.
- **A periodic audit** — *rejected as the primary detector*: too late by
  definition, which was the explicit concern.
- **Provenance fingerprints / manifests** (hash each upstream source to make
  staleness a pure diff) — *deferred*: useful precision, but a separate system;
  the planner can reason over the existing trace links for now, and we revisit
  if agentic detection proves unreliable.

## Consequences

- Each design skill's **planner** (and planner-agent prompt) gains the shared
  consistency-analysis step; the **executor** applies chosen adjustments; the
  **verifier** checks the affected docs end consistent. Completion-report
  findings gain a gaps/staleness section.
- Detection happens **at design time, in the same session** as the change — the
  earliest practical point — with no separate command, gate, or schedule.
- Detection power scales with **trace-link quality**; weak/missing links reduce
  it — a standing incentive to keep traces current (which the skills already
  enforce). Provenance fingerprints remain a future upgrade if needed.
- [`/acs:test`](0011-sdlc-doc-sets-quality-and-operations.md) is unaffected — it
  stays the QA/regression runner, not a doc tool.
