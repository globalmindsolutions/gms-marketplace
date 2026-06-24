# 0025 — tabp independent verifier: inline-artifact input contract and bounded remediate-and-re-verify loop

**Status**: Accepted · **Date**: 2026-06-21

## Context

MAR-2 (spec 03) shipped a coordinator self-verification pass as the AC-3 gate in
`plugins/tabp/skills/screen-cvs/SKILL.md:134-177`. This was an explicit interim
measure: the upgrade-path note at `SKILL.md:173-177` deferred an independent
subagent verifier to a future iteration ("assumption C-7").

MAR-36/MAR-37 fulfil that deferral. The engineering-rigor NFR (`prd.md:141-154`)
requires genuine independent reflection — not a coordinator self-check in which
the same context that produced the screening judgments also validates them. The
verifier must operate in a separate spawn context and see only persisted
artifacts, not the coordinator's working memory.

ADR-0023 (`docs/adr/0023-*.md`) established the tabp quality mechanism:
instruction-driven orchestration for judgment, `tabp_helper.py` for deterministic
persistence. It explicitly prohibits a `PreToolUse` hook gate (Cowork hook support
is UNVERIFIED) and instead relies on coordinator-disciplined ordering. The
independent verifier must therefore be a coordinator-spawned subagent — never a
hook gate — per ADR-0023's constraint.

Two sub-decisions were required to implement the verifier (see `MAR-36/design.md`):

**D1 — how to pass artifacts to the verifier**

- **Option A (inline):** the coordinator passes the six required artifacts
  (`run_id`, `jd_requirements`, `evidence_records`, `synthesis_result`,
  `scoring_rubric`, `fairness_guidelines`) inline in the XML `<task>` body.
  Mirrors how `synthesis-subagent.md:20-27` receives `evidence_records`. Zero
  new infrastructure; no unverified Cowork capability assumed; works identically
  in Cowork and Claude Code.
- **Option B (path-based):** the coordinator passes only `run_id`; the verifier
  reads artifacts from `.tabp/runs/<run_id>/` by constructing filesystem paths.
  Requires the verifier to have Bash/filesystem read access — exactly the
  unverified Cowork capability ADR-0023 says to avoid. Also requires the
  synthesis result to be persisted to disk before the verifier can read it (a
  new write step with no existing schema target).

Decision: **Option A**. Inline-artifact input is the proven pattern, fits
ADR-0023's instruction-driven constraint, and makes no unverified-capability
assumption (`design.md:81-97`).

**D2 — how to bound the remediate-and-re-verify loop**

An unbounded loop would allow a screening run to stall indefinitely on
persistent blocking findings. A fixed N guarantees termination and records
failure visibly.

The cap is **N=3 total verifier invocations** (including the initial one). This
aligns with the acs reflection-cap precedent (ADR-0004 uses a bounded single-pass
walk). On cap-hit, the coordinator writes `verification_passed=false` and the
unresolved `blocking_findings` in `verification_notes`, then notifies the
recruiter without proceeding to Step 6 result delivery.

## Decision

1. **D1 — Inline-artifact input contract (Option A).** The coordinator passes the
   six required artifacts inline in the verifier's XML `<task>` body. The
   coordinator must NOT include its own reasoning, framing, or in-progress
   evaluation notes. The verifier is isolated from the coordinator's perspective.
   This is documented in the charter at
   `plugins/tabp/agents/screen-verifier-subagent.md`.

2. **D2 — Bounded remediate-and-re-verify loop capped at N=3.** If the verifier
   returns a `blocking` verdict, the coordinator remediates the flagged issues
   (re-spawning affected screening subagents or re-running synthesis) and
   re-verifies. The loop is capped at N=3 total verifier invocations. On cap-hit
   with unresolved findings, `decision.json` records `verification_passed=false`
   and the blocking findings in `verification_notes`. Results (Step 6) are not
   delivered.

3. **Always-on rule.** The verifier runs on every `screen-cvs` run with no skip
   path. There is no condition under which the verifier invocation is bypassed.
   This is documented in `plugins/tabp/skills/screen-cvs/SKILL.md` Step 5a.

4. **Semantic change to `decision.json`.** The `verification_passed` and
   `verification_notes` fields in `decision.json` now record the independent
   verifier verdict, not a coordinator self-attestation. The
   `decision.schema.json` descriptions have been updated accordingly (C-3).

## Consequences

- The coordinator-self-verification pass (`SKILL.md:134-177`) is retired and
  replaced by the independent verifier subagent spawn in Step 5a.
- Results are presented (Step 6) **only** after the verifier returns a clean
  `pass`. The AC-3 gate is enforced by the SKILL.md step ordering and structural
  tests in `tests/tabp/test_tabp_scaffolding.py`.
- **Residual risk (R3):** verifier independence is convention-enforced, not
  gate-enforced. ADR-0023 forbids a `PreToolUse` hook gate (Cowork hook support
  is UNVERIFIED), so the SKILL.md step ordering is the enforcement mechanism.
  A SKILL.md error that spawns the verifier with coordinator reasoning in the
  payload would undermine independence without being caught automatically
  (`design.md:535`). Mitigation: the charter explicitly prohibits coordinator
  reasoning in the payload; structural tests assert the step ordering; the
  verifier operates in a separate spawn context.
- If Cowork gains confirmed `PreToolUse` hook support in a future release, a
  follow-up ADR may upgrade to a hook-gated independence guarantee. Until then,
  this convention-only approach is the appropriate balance of independence and
  verified-capability use.
- The N=3 cap and `verification_passed=false` path are auditable in the
  `.tabp/runs/<run-id>/decision.json` record for every run.
