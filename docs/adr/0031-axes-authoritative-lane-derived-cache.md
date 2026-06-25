# 0031 — Store size + stakes as authoritative axes; lane is a derived cache, recomputable by the routing function

**Status**: Accepted · **Date**: 2026-06-25

## Context

In a multi-axis classification system there are two approaches to storing the derived
classification result: (a) treat the derived value (`lane`) as authoritative and store
it, allowing the axes to be reconstructed — or (b) treat the axes as authoritative and
treat the derived result as a cache that can always be recomputed. The choice affects
cache coherence, escalation correctness, and verifier re-check ability.

## Decision

**`size` and `stakes` are the authoritative axes. `lane` is a derived cache computed by
`derive_lane(size, stakes, needs_design, ticket_type)` and is always recomputable.**

Concretely:
- `new_ticket_doc` and the create-ticket executor ALWAYS call `derive_lane` to compute
  `lane`; they never accept a `lane` value verbatim from user input or carry it forward
  from a planner recommendation.
- When escalation occurs (MAR-57/Child 2), `flip_lane` updates the axes AND recomputes
  the lane — it does not mutate `lane` directly without updating the axes.
- The `code-verifier` and `create-ticket-verifier` re-check consistency via
  `lane == derive_lane(size, stakes, needs_design, type)` — if they disagree, the lane
  is stale and the ticket is blocked.

## Alternatives considered

- **Lane authoritative, axes reconstructed:** fragile under escalation; once the lane is
  bumped, there is no ground truth about which axis caused the bump; the verifier cannot
  distinguish a legitimate COMPLEX lane from a mistakenly written one.
- **Both authoritative (no cache):** would require re-running `derive_lane` in every gate
  function that reads the lane, adding complexity. Caching with a consistency guarantee
  (this decision) gives both the performance of a stored value and the correctness of
  a recomputable one.

## Consequences

- A lane that disagrees with its axes is detectable and blockable by the verifier.
- Mid-flight escalation (MAR-57) is safe: the escalation helper updates axes first, then
  recomputes lane, keeping the cache coherent.
- Legacy tickets without `size`/`stakes` resolve to the conservative defaults at every
  `derive_lane` call — no migration required.
- The `lane` field in `pipeline-state.json` and `tickets-index.json` (D7) is written
  directly rather than recomputed on read, for metrics efficiency; these downstream copies
  are acceptable eventually-consistent mirrors (written on every `update_pipeline` and
  `update_index` call).
