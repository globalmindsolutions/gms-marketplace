# 0003 — File-based state in a workspace outside the repo

**Status**: Accepted · **Date**: 2026-06-12

## Context

State in conversation memory dies with the session; state inside the repo
collides across git worktrees and pollutes diffs.

## Decision

All pipeline state lives in `<workspace>/<repo-id>/<ticket-id>/` outside
the consumer repo (`workspace_path`, machine-local). The append-only `runs`
array is the single source of truth (`runs[-1]` = current status; durations
computed, never stored); repo identity derives from the git remote so all
worktrees share one partition; per-checkout pointer files and re-entrant
locks make parallel worktree sessions safe.

## Consequences

Any skill can run in a fresh session and resume from disk alone; the
workspace doubles as a human-readable audit trail; cross-machine handoff is
out of scope (workspace is machine-local) — a deliberate limitation.
