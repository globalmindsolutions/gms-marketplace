# 0007 — Living architecture & requirements by induction

**Status**: Accepted · **Date**: 2026-06-13

## Context

Standing docs rot when updating them is a separate activity; per-ticket
specs are archived change-deltas, so no file states the product's current
behavior.

## Decision

Two doc sets stay current by induction, not by chore: the **architecture**
set (`architecture_path`) and the **living requirements**
(`requirements_path`, one file per feature area). Base case: bootstrapped
verified against PRD and codebase (architecture) / grown from ticket #1
(requirements). Inductive step: every changeset carries its doc delta, and
the code-verifier makes a positive, evidenced impact determination — impact
without a matching doc change in the same diff is a blocking finding.
Out-of-band drift is repaired boy-scout style (area-scoped) by the design
and code planners; widespread drift triggers a /create-architecture re-run.

## Consequences

After every merge the docs match the code; behavior-defining clarifications
graduate from the workspace ledger into the durable contract; doc updates
are reviewable parts of each PR rather than batch rewrites.
