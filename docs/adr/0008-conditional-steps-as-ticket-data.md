# 0008 — Conditional steps are ticket data, never invocation options

**Status**: Accepted · **Date**: 2026-06-13

## Context

Not every task needs every step (design, TDD), but letting callers skip
steps at invocation time would gut the gating model.

## Decision

Skips are **declared, user-confirmed flags on the ticket**, set during
/create-ticket analysis and read by deterministic gates: `needs_design`
(gates /create-design from both sides), `docs_only` (relaxes tests-first and
the coverage hard-fail; the suite still runs once; executable-code diffs
under the flag are blocking findings), epic children (mint-time completed
create-ticket state), `flow: product` (delivery tickets skip the six-step
pipeline). The spine — ticket → spec → code → PR → merge — is unconditional.

## Consequences

Every skip is visible in `ticket.json` and enforced symmetrically (the
skipped step is blocked, not just optional); a wrong flag is caught by the
verifier rather than silently honored; new conditional steps must follow
the same flag + gate pattern.
