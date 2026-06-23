# 0027 — merge-pr is agent/model-invocable; readiness gate + branch protection are the merge brakes

**Status**: Accepted · **Date**: 2026-06-23

## Context

`/acs:merge-pr` was deliberately user-action-only: its frontmatter set
`disable-model-invocation: true`, a "User action only" section forbade
spawned/agent invocation, and `/acs:ship` asserted it stops before merge. This
realised the PRD Vision guardrail that "the human owns ... the merge button"
(`docs/product/prd.md`). MAR-42 reverses that guardrail — the PRD Vision was
amended in MAR-45 to authorise it — so an agent/model can drive a merge
end-to-end.

## Decision

Make `/acs:merge-pr` agent/model-invocable (FULL): remove
`disable-model-invocation` outright. Alternatives weighed and rejected:
confirmation-gated (an agent-answerable prompt is not a real gate), ship-opt-in
behind a settings key (a static frontmatter flag cannot be toggled per-run, and
no source-aware hook exists), and reject/keep-human-only (does not satisfy the
request).

The safety guarantee shifts from "a human must press merge" to "a merge happens
only when the readiness gate (CI, approvals, conflicts, protections) AND the
repo's branch protection pass, by whoever invokes; failures are report-only;
every attempt is audited." Mandatory mitigations: the readiness gate is
unchanged and not bypassed (m1); the repo's branch protection is the second
independent brake (m2); report-only on failure (m3); the run record is the
audit trail (m4); and **agent-invoked merges require an APPROVED review** (m6).

Because the merge-pr coordinator cannot reliably distinguish an agent
invocation from a direct human one (skill-start's context carries no
invocation-source field; no hook distinguishes the two), m6 is implemented as
the conservative **require-APPROVED-for-all** fallback: the approvals readiness
dimension requires `reviewDecision == APPROVED` for every invocation. There is
no settings kill-switch (unconditional).

## Consequences

- `/acs:merge-pr` (ticket and exempt `--pr` paths) can be invoked by an agent.
- Every merge now requires an approving review, even on repos whose own branch
  protection requires none — a deliberate behaviour change.
- `/acs:ship` still stops at `/acs:create-pr` (review separation); it does not
  chain into merge (a separate future decision).
- Reversible: re-add `disable-model-invocation: true` to the frontmatter. If a
  reliable invocation-source signal is added later, m6 can be narrowed to
  agent invocations only.
