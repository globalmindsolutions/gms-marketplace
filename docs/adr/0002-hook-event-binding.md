# 0002 — Hook event binding on PreToolUse(Skill)

**Status**: Accepted · **Date**: 2026-06-12 (closed the requirements' only [OPEN] question)

## Context

Claude Code has no "skill completed" hook event, but the pipeline needs
enforced pre-gating and reliable post-persistence (docs/requirements/hooks.md).

## Decision

Pre-hooks bind to `PreToolUse` matching the `Skill` tool: a dispatcher
routes by skill name to the named `pre-<skill>.py`; exit 2 blocks the skill
before any instruction runs. Post-hooks are coordinator-invoked scripts
(their inputs — status, findings, tokens — exist only in the coordinator's
context), backed by the gates: `skill-start.py` registers an `in_progress`
run first, and every downstream gate requires `runs[-1] == "completed"`. A
`SessionEnd` hook finalizes abnormal endings as `interrupted`.

## Consequences

Gating is enforced for user-typed and model-initiated invocations alike
(including /ship's direct step invocations); a skipped post-hook can close but never
open the pipeline; a hard kill leaves `in_progress` + a stale lock, which
the next run reconciles.
