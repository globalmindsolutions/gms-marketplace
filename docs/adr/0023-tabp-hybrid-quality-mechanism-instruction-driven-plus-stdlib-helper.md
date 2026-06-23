# 0023 — tabp quality-mechanism: hybrid instruction-driven orchestration plus a tabp-namespaced stdlib-Python persistence helper

**Status**: Accepted · **Date**: 2026-06-20

## Context

The tabp plugin (`plugins/tabp/`) runs in the Cowork runtime — not in Claude
Code. The D1 evidence table (`MAR-1/design.md:57-66`) shows that key Cowork
runtime capabilities are UNVERIFIED: `PreToolUse` / `SessionEnd` hook support
is unconfirmed, and `PostToolUse` does not exist in any host. The acs pattern
(ADR 0001) established a hook-gated model where a `PreToolUse` script enforces
determinism at skill dispatch time. That pattern cannot be adopted verbatim for
tabp because it depends on a confirmed hook surface.

Three options were evaluated (`design.md:210-288`):

- **Option A — pure instruction-driven:** SKILL.md coordinator writes `.tabp/`
  JSON directly. Zero external dependencies. Insufficient: cannot meet the
  determinism-where-possible NFR (`prd.md:177`) or safety NFR (`prd.md:180`).
- **Option B — hook-gated (mirroring ADR 0001):** Same structure as acs but
  using Cowork hooks. Rejected: Cowork hook support is UNVERIFIED (`design.md:57-66`).
  Building a gate layer on an unconfirmed capability is speculative engineering
  (ADR 0009).
- **Option C — hybrid (chosen):** Instruction-driven orchestration for all
  judgment and coordination; a tabp-namespaced, stdlib-only Python helper module
  (`tabp_helper.py`) for the deterministic bits (atomic writes, spin-lock,
  schema validation, run-history, usage aggregation stub). The coordinator
  invokes the helper via Bash when Cowork grants shell access (assumption C-5,
  `design.md:84-85`); degrades gracefully to instruction-driven writes if Cowork
  denies shell.

## Decision

Adopt **Option C (hybrid)** for the tabp quality mechanism. `tabp_helper.py`
owns all deterministic `.tabp/` operations (atomic writes, `O_EXCL` spin-lock,
schema validation at write time, append-only run-history, resume read-back, and
the `/tabp:usage` aggregation stub). SKILL.md and the subagent charters own all
judgment, orchestration, and the verify-before-present reflection step.

This is a **deliberate divergence from ADR 0001** (hook-gated model): tabp
does not use a `PreToolUse` hook gate because Cowork hook support is unverified.
The two-layer spirit of ADR 0001 (scripts record, prose decides) is preserved —
only the hook mechanism is absent.

The helper is:
- stdlib-only Python ≥ 3.9 (zero pip dependencies, matches ADR 0001's
  portability constraint);
- fully tabp-namespaced (no `acs:` token, no `.acs/` path, no import of
  acs_lib — constraint AC-6);
- designed to degrade to Option A behavior if Cowork denies shell (recorded in
  `.tabp/runs/<id>/run.json` as `"state_write_mode": "instructed"`).

## Consequences

- `tabp_helper.py` (`plugins/tabp/helpers/tabp_helper.py`) is the authoritative
  implementation of this decision (delivered in MAR-2).
- Deterministic state operations are unit-testable in isolation (90% coverage
  gate measured in MAR-2).
- If C-5 (unverified Cowork shell access) is later confirmed, no architecture
  change is required — the helper is already invoked via Bash.
- If Cowork gains confirmed `PreToolUse` hook support in a future release, a
  follow-up ADR can upgrade tabp from Option C to a hook-gated model (Option B).
- The absence of an auto-firing gate means enforcement is "coordinator-
  disciplined": a SKILL.md error that skips a helper call is not fail-closed.
  Mitigation: the self-verification pass re-reads `.tabp/` state before
  presenting (spec 03, MAR-2); if state is absent, verification fails.

## Amendment (MAR-40, 2026-06-22)

**Scope extended to dual-runtime (Cowork + Claude Code).** The original Accepted
decision above (hybrid instruction-driven orchestration + tabp-namespaced
stdlib-Python helper) is preserved unchanged and is only extended here. As of
MAR-40, the tabp plugin runs under both Cowork *and* Claude Code, not Cowork
only (the original Context line "runs in the Cowork runtime — not in Claude
Code" reflects the pre-MAR-40 scope and is retained as the historical record).

What changes:

- **Runtime selection.** The runtime is selected by an explicit
  `--runtime {cowork,claude-code}` flag on the coordinator-invoked
  `tabp_helper.py` subcommands, with an auto-detect fallback when the flag is
  absent. The detection decision is recorded separately in **ADR-0027**
  (dual-runtime detection).
- **Mechanism unchanged.** The hybrid mechanism itself is unchanged across both
  runtimes: instruction-driven orchestration for judgment and coordination; the
  stdlib-only helper for the deterministic `.tabp/` operations. The Option C
  rationale (Cowork hook support unverified) still holds — no `PreToolUse` gate
  is introduced for either runtime.
- **Degradation preserved.** The Bash-denied degradation path (`state_write_mode:
  "instructed"`) still applies under either runtime; only the actor that may deny
  Bash is generalized from "Cowork" to "the runtime".

This amendment extends the decision; it does not rewrite it. The
tabp-namespace constraint stated in the Decision section above (the rule that no
foreign-namespace prefix, no foreign state-path token, and no foreign-library
import appear in the helper — constraint AC-6) continues to bind all MAR-40
changes. See also ADR-0024 (state location, MAR-40 amendment) and ADR-0027
(dual-runtime detection).
