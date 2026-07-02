# Design: "Think Before Coding" — simpler-approach push-back flag

**Status:** Approved (brainstorm)
**Date:** 2026-07-02
**Base:** `origin/main` @ 503075a (contains the merged MAR-2 restraint layer, PR #149)
**Sibling work:** MAR-2 — "Simplicity First + Surgical Changes restraint layer" (PR #149, merged)

## Problem

Andrej Karpathy's four LLM-coding anti-patterns map onto acs as follows:

| Karpathy principle | Status in acs |
|---|---|
| #1 Think Before Coding | **~70% present** — clarification ledger + "assumptions are findings, never silent guesses" cover the *ambiguity* half; the *"a simpler approach exists — surface it / push back"* half is missing. |
| #2 Simplicity First | Shipped (MAR-2). |
| #3 Surgical Changes | Shipped (MAR-2). |
| #4 Goal-Driven Execution | **Already fully covered** — strict TDD (write failing tests first, loop to green) + acceptance-criteria (verifier dim #5 Features) + the reflection loop *are* "transform the task into a verifiable goal and loop until met." |

The only genuine behavioral gap is the second half of #1: when an executor or
planner sees a **materially simpler approach** that satisfies the same
acceptance criteria with materially less code/complexity than the spec
prescribes, acs today has no channel to surface it. The agent either silently
follows the spec (losing the insight) or would have to silently deviate (which
violates acs's core rule that agents anchor to gated upstream contracts).

## Non-goals

- **No `#4 Goal-Driven Execution` text.** It would restate TDD + acceptance
  criteria — pure duplication, and adding it would itself violate the
  Simplicity principle MAR-2 just shipped.
- **No changes to the clarification ledger.** The ambiguity half of #1 already
  works (`clarify.py`, "do not guess on decisions that change behavior").
- **No new verifier dimension.** The count stays at 12.
- **No autonomous spec rewriting.** The pipeline never acts on the flag itself.

## Solution — flag, don't deviate

When the **executor** (while implementing a spec) or the **planner** (at plan
time) sees a materially simpler approach that would satisfy the same acceptance
criteria with materially less code/complexity than the spec prescribes:

1. **Still implement the spec as written.** The spec remains the gated
   contract; there is no silent deviation.
2. **Record the simpler alternative in the execute-report `problems` field**
   (planner: in the plan) as a one-line "simpler-approach" note: what the spec
   does, the simpler path, and why it is *materially* simpler.
3. **The coordinator surfaces it** in the result document / PR body — the same
   channel already used for flagged intent divergences and mentioned dead code.
4. **A human / spec owner decides** whether to amend the spec.

This is deliberately the same shape as two rules acs already has:
- MAR-2 dead-code rule: "mention it in `problems`, don't delete it."
- Product-doc intent-divergence rule: "flag, never rewrite."

It reuses existing plumbing — no new report field, no new gate, no new
interactive interruption.

### Why "materially" simpler

The threshold is deliberately high so the flag does not fire on every
micro-preference or stylistic choice. It is for approaches that a senior
engineer would call *materially* less code/complexity for the same acceptance
criteria — not "I'd have named this differently."

## Where it is wired (mirrors the MAR-2 five-layer pattern)

| Layer | Change |
|---|---|
| `plugins/acs/agents/code-executor.md` (Charter, step 4 authoring block) | New short **"Think Before Coding — flag a simpler path"** rule next to Simplicity First / Surgical Changes. Defines the `problems`-field note and the "implement the spec anyway" rule. |
| `plugins/acs/agents/code-planner.md` | One line: the planner may flag a materially simpler approach in the plan at plan time (earliest signal), same flag-don't-deviate rule. |
| `plugins/acs/agents/code-verifier.md` | **No new numbered dimension.** Add one clause to existing dim #12 (Simplicity & scope): the verifier does **not** block for the executor *failing to find* a simpler path (do not punish the executor for the spec's complexity); a silently-taken deviation from the spec is already caught by anchoring (dim #5 Features / spec conformance). |
| `plugins/acs/skills/code/SKILL.md` | Restate the executor rule in the authoring section and note the `problems`-surfacing in the coordinator result/PR flow. |
| `docs/requirements/skills.md` + `docs/requirements/reflection.md` | Add the flag to the requirements source of truth (one clause each). |
| `tests/acs/test_skill_contracts.py` | Contract test asserting the simpler-approach-flag text is present in the executor charter + SKILL.md; assert the verifier dimension count stays **12** (regression guard against accidental dimension bloat). |
| `plugins/acs/CHANGELOG.md` | One entry under the acs plugin changelog. |

## Testing & success criteria

Karpathy-style verifiable criteria — the change is done when ALL hold:

1. The full `tests/acs/` suite passes.
2. `grep` confirms the simpler-approach-flag rule text in `code-executor.md`,
   `code-planner.md`, and `skills/code/SKILL.md`.
3. The `code-verifier.md` numbered-dimension count is unchanged at **12**
   (asserted by the contract test).
4. `plugins/acs/CHANGELOG.md` has a matching entry.

## Rollout

Design doc first (this file), committed. Ship path (new MAR-N ticket via
`/acs:ship`, or `/acs:code <ticket>`) decided after this doc is reviewed —
per the CLAUDE.md pipeline rules, the change ships through acs, not a hand-made
PR.
