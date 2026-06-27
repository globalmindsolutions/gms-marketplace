# 0035 — Codex gate enforcement: no-bypass wrapper shim calling `dispatch.py pre` at the command boundary

**Status**: Accepted · **Date**: 2026-06-27

## Context

MAR-5 adds Codex CLI as a second execution runtime for acs (MAR-3 epic).
The `PreToolUse(Skill)` hook binding (ADR-0002) is specific to Claude Code:
it fires before any coordinator instruction runs and exits-2 blocks (`hooks.json:3-14`,
`dispatch.py:64-75`). This is the only fail-closed enforcement point for G1 gate integrity.

Codex CLI's hook surface (PreToolUse) is not verified to intercept skill-invocation paths
universally — a silent gate escape is possible if Option A is used (`design.md:57-63`).
Option C (in-coordinator self-check) relies on model goodwill and violates ADR-0001
(`design.md:75-79`).

Three options were considered:

- **Option A** — Native Codex `PreToolUse`/`Stop` hook binding: rejected because Codex's
  hook coverage is explicitly not universal; unverified whether `/acs:*` skill invocation
  fires `PreToolUse` on the Skill tool. Risk: silent gate escape (blast radius: G1).
- **Option B** — No-bypass wrapper shim (CHOSEN — C-3, `design.md:65-73`): a Bash shim is
  the mandatory first instruction of each acs skill's Codex entry point; it calls the same
  `dispatch.py pre` as the Claude Code path; exit 2 before the coordinator prose runs.
- **Option C** — In-coordinator self-check: violates ADR-0001 (relies on model goodwill to
  self-gate). Rejected.

## Decision

Use **D1 Option B**: a no-bypass Bash shim in each of the 9 hooked skill's Codex skill
definition file (`plugins/acs/runtimes/codex/skills/<skill>.md`) that:

1. Synthesizes a shape-(a) Claude-Code-shaped stdin payload:
   `{"cwd": "$PWD", "tool_input": {"skill": "acs:<skill>"}}`.
2. Pipes it to `dispatch.py pre` via subprocess, reusing `skill_name_from_payload`
   (`dispatch.py:25-38`) and the full `HOOKED_SKILLS` gate path (`acs_lib.py:1443-1462`)
   **unchanged** (AC-2, ADR-0001).
3. The shim is the FIRST non-blank, non-comment executable line — no branch skips it.
   Exit 2 propagates via `dispatch.py:75` (`sys.exit(proc.returncode)`), halting execution
   before the coordinator body runs.

The Codex `Stop` event is wired to `dispatch.py session-end` (same path as the Claude Code
`SessionEnd` hook, `hooks.json:16-26`), finalizing `interrupted` runs and releasing locks
(`dispatch.py:49-54`, `acs_lib.session_end` at `acs_lib.py:1621`).

**Zero change** to `dispatch.py`, `acs_lib.py`, `hooks.json`, or any `pre-<skill>.py`
is required. This extends ADR-0002's fail-closed enforcement to the Codex CLI runtime.

## Consequences

- Enforcement is at the skill-entry wrapper, not a kernel event. A Codex skill definition
  that omits the shim would bypass it — the no-bypass guarantee rests on the authoring
  contract enforced by Test 4 (`tests/acs/test_codex_gate_dispatch.py`).
- The deterministic stdlib layer (`acs_lib.py` gating, `dispatch.py` routing) is reused
  byte-for-byte unchanged across both runtimes (AC-2, ADR-0001 invariant).
- Adding a third runtime requires only new shim files at the same pattern — no change to the
  deterministic layer.
- `plugins/acs/runtimes/codex/README.md` documents the Stop-handler wiring note.
