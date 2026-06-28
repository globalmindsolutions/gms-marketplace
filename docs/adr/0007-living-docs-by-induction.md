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

## Amendment — MAR-65

**Date**: 2026-06-28 · **Status**: Accepted (extended)

### Extended scope

The induction loop is extended to include FACTUAL claims in
`docs/product/prd.md` and `docs/product/roadmap.md`. Factual content is
reconciled by the executor as part of the change (same diff), not as a
follow-up. The code-planner assesses factual impact during planning; the
executor reconciles stale factual claims; the code-verifier enforces this as
part of its Documentation-consistency dimension (see enforcement note below).

**Factual — sync autonomously as part of the change:**
- agent/subagent counts
- feature/epic shipped-vs-planned status
- component topology
- version numbers
- file path references

### Boundary definition (factual vs intent)

Intent content — goals, NFR (non-functional requirement) targets, scope
statements, vision, and requirements rationale — remains exclusively
`/acs:create-prd`-owned. `/acs:code` may flag an intent divergence (in the
result document and PR body) but NEVER rewrites intent content. This boundary
is the normative contract encoded in `plugins/acs/skills/code/SKILL.md`
Execute step 4 and the code-executor agent.

### Divergence rationale

The original ADR-0007 scope (architecture + requirements only) treated PRD
intent as `/acs:create-prd`-owned, which is correct and unchanged. This
amendment extends the loop only to *factual* product-doc content because such
content drifts silently across code changes (demonstrated concretely: commit
`44ec46e` reconciled post-MAR-55 drift in `prd.md` out-of-band). The
extension is bounded by the factual/intent boundary above: intent ownership
does not change. No separate `/acs:create-prd` run is needed because this
change extends pipeline mechanics, not the PRD's goals or requirements.

### Enforcement note

The code-verifier's Documentation-consistency dimension (dimension 11) is
extended to make stale prd.md/roadmap.md factual claims a blocking finding.
An intent contradiction found by the changeset produces an explicit flagged
divergence (not a blocking finding). No factual impact → no-op. This makes
the inductive step enforceable for the prd/roadmap doc set.
