# 0027 — tabp dual-runtime detection: explicit `--runtime` flag with auto-detect fallback

**Status**: Accepted · **Date**: 2026-06-22

## Context

As of MAR-40, the tabp plugin (`plugins/tabp/`) runs under both the Claude
Cowork runtime and the Claude Code runtime (parent epic MAR-36). ADR-0023 (MAR-40
amendment) extends the hybrid quality mechanism to dual-runtime, and ADR-0024
(MAR-40 amendment) extends the state-location convention to the Claude Code
cwd-as-project-dir case. What those amendments deliberately leave to a separate
record is *how the helper decides which runtime it is in* and *how the project
directory is resolved on Claude Code*.

A runtime-selection mechanism must be deterministic and testable to meet the
determinism NFR (`prd.md:177`). Two options were evaluated (`MAR-36/design.md`
D4, `:169-189`):

- **Option A — explicit `--runtime {cowork,claude-code}` flag with auto-detect
  fallback.** The coordinator passes `--runtime` when it knows the runtime; when
  the flag is absent the helper auto-detects from an environment signal. The
  flag is exercised directly in unit tests by passing it explicitly, so behavior
  is deterministic and testable in isolation.
- **Option B — pure auto-detect inside the helper.** No coordinator input; the
  helper always infers the runtime from environment signals. Rejected: heuristic
  and brittle, hard to test deterministically, and prone to silent misfire when
  both signals are present or absent.

## Decision

Adopt **Option A**: dual-runtime detection via an explicit
`--runtime {cowork,claude-code}` flag on the coordinator-invoked
`tabp_helper.py` subcommands, with an auto-detect fallback when the flag is
absent.

- **Explicit flag (primary path).** Each coordinator-invoked subcommand accepts
  an optional `--runtime {cowork,claude-code}` argument. In Claude Code the
  coordinator passes `--runtime claude-code` and `--project-dir <session-cwd>`;
  in Cowork it passes `--runtime cowork` (or omits the flag). An invalid value is
  rejected by argparse choices (non-zero exit).
- **Auto-detect fallback.** When `--runtime` is absent, the helper resolves the
  runtime from the presence of the per-session transcript directory
  (`~/.claude/projects/<cwd-slug>/`): present → `claude-code`, absent →
  `cowork`. The transcript root is injectable for testing, so tests never read
  the real home-directory path.
- **cwd-as-project-dir convention (Claude Code).** The coordinator passes the
  session's current working directory as `--project-dir`. The helper derives the
  `<project-dir>/.tabp/` state root from `--project-dir` with no git dependency
  (`_tabp_dir_from_project`), so the project folder need not be a git repo. This
  is the convention recorded in ADR-0024's MAR-40 amendment.

## Consequences

- **Deterministic and unit-testable.** The flag is exercised directly in tests
  (explicit `--runtime claude-code` / `--runtime cowork`), and both auto-detect
  branches and the argparse rejection path are unit-tested via the injectable
  transcript root. This meets the determinism NFR (`prd.md:177`).
- **Back-compatible.** When the flag is absent and no transcript directory is
  present, auto-detect resolves to `cowork`, preserving the prior Cowork-only
  behavior. No `run.json`/`history.json` schema field is added.
- **Override for `usage-read`.** The resolved runtime gates whether the
  `usage-read` subcommand reads Claude Code transcript token actuals
  (`claude-code` reads them when available; `cowork` suppresses the transcript
  read and falls back to per-run `run.json` tokens).
- **Cross-references.** This record complements ADR-0023 (MAR-40 amendment —
  dual-runtime scope of the hybrid mechanism) and ADR-0024 (MAR-40 amendment —
  cwd-as-project-dir state-location convention).
- **Namespace constraint.** Like every tabp artifact, the helper code and this
  record stay within the tabp namespace: no foreign-namespace prefix, no foreign
  state-path token, and no foreign-library import (epic AC-6 / MAR-40 AC-9).
