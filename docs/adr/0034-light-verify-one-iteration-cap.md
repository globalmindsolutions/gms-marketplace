# 0034 — Light verify = single verifier pass with one-iteration cap; full verify unchanged; TDD/coverage gate immutable in every lane

**Status**: Accepted · **Date**: 2026-06-25

## Context

The acs reflection loop currently runs up to 3 iterations for every ticket
regardless of size or risk. For TRIVIAL/SMALL low-stakes changes this wastes
roughly 12–20 coordinator context windows with no quality gain — the verify loop
iterates 3 times on a one-line change carrying zero functional risk (design.md:6-14,
MAR-55 problem statement).

The MAR-56 classification system (ADRs 0030–0033) provides a machine-readable
`lane` field (`TRIVIAL` / `SMALL` / `STANDARD` / `COMPLEX`) derived from
`size × stakes` axes. MAR-58 builds on this to make the reflection-loop depth
proportional to the ticket's lane, while holding the TDD/coverage safety net
and the verifier-as-gate invariant absolutely constant across all lanes.

## Decision

Implement D4 (C-9, design.md:59-63, 255-276): **lane-driven verify depth**.

1. **`verify_depth(lane, stakes) -> "light" | "full"`** (pure function in
   `acs_lib.py`): returns `"light"` for TRIVIAL/SMALL tickets at low/normal
   stakes; returns `"full"` for STANDARD/COMPLEX tickets or any high-stakes
   ticket. Stakes = `"high"` is checked first (floor cannot be bypassed by lane
   value — defense-in-depth). Absent/unknown lane defaults conservatively to
   `"full"`.

2. **`VERIFY_ITERATION_CAP = {"light": 1, "full": 3}`** (constant in
   `acs_lib.py`): encodes the cap as a tested code fact.

3. **Light verify** = single verifier pass that may iterate **at most once** on
   blocking findings (iteration cap 1, not 3). Applies to TRIVIAL/SMALL tickets
   at low/normal stakes.

4. **Full verify** = the existing up-to-3-iteration plan→execute→verify loop
   + full 11-dimension review + e2e when configured. Applies to STANDARD/COMPLEX
   tickets and ALL high-stakes tickets. This behavior is **unchanged**.

5. **Two invariants hold in every lane**, unconditionally:
   - The **verifier subagent is the in-loop quality gate in every lane** (C-5).
     Light verify reduces the iteration ceiling only; the verifier always runs.
     There is no inline human-approval gate; the PR review is the
     human-in-the-loop checkpoint.
   - The **TDD/coverage gate runs in full in every lane** and is never trimmed
     by verify-depth selection (invariant a, MAR-55). It is not a verify
     dimension that light mode drops.

## Alternatives considered

- **Always 3 iterations regardless of lane:** the status quo; wastes context
  windows on TRIVIAL changes; the MAR-55 epic exists precisely to address this.
- **Zero iterations for TRIVIAL (skip verifier entirely):** violates invariant d
  (autonomous-first gating) and invariant a (TDD/coverage always). Rejected at
  C-9 confirmed user decision.
- **Human gate replaces verifier in light lane:** violates C-5 (no inline human
  gate); increases latency rather than reducing it. Rejected.
- **Cap 2 for light (not 1):** no quality advantage over 1 for TRIVIAL/SMALL;
  the single-pass cap was confirmed as the right calibration at C-9.

## Consequences

- `verify_depth(lane, stakes)` and `VERIFY_ITERATION_CAP` are additive to
  `acs_lib.py`; no schema changes, no state-file shape changes.
- The `/acs:code` coordinator reads `ticket.lane`/`ticket.stakes`, calls
  `verify_depth`, and sets the loop ceiling = `VERIFY_ITERATION_CAP[depth]`
  before starting the reflection loop.
- TRIVIAL/SMALL low-stakes tickets reduce verify overhead from up to 3 iterations
  to 1 (estimated reduction: several context windows per run, consistent with
  G14 target in design.md:82-88).
- High-stakes tickets always use full verify regardless of size (stakes floor;
  no regression on high-risk changes).
- The TDD/coverage safety net is immutable; coverage hard-fail applies in every
  lane.
- `docs/requirements/reflection.md` updated to reflect the lane-driven ceiling
  as the new standing behavioral contract.
- `docs/architecture/lld/flows/hook-gated-skill-run.md` updated with prose
  annotation describing the lane-driven depth.
