# 0024 — tabp state in the Cowork project folder

**Status**: Accepted · **Date**: 2026-06-20

## Context

ADR 0003 (`docs/adr/0003-file-based-state-outside-repo.md`) mandates that acs
plugin state lives in a workspace directory **outside the consumer repo** to
avoid git-worktree collision problems: when two worktrees of the same repo are
active simultaneously, per-worktree state must not be confused with per-repo
state. The rule was designed for acs's Claude Code runtime where worktrees are
common.

The tabp plugin (`plugins/tabp/`) has a different runtime context (Cowork) and
a different usage model:

- tabp has no git-worktree collision problem: it operates on Cowork project
  folders, not git worktrees. Cowork project folders are not git repos in the
  acs sense (`design.md:301-308`).
- The PRD mandates explicitly that `tabp settings.json` and the `.tabp/` run
  state are stored **in the Cowork project folder** (`prd.md:127-129`;
  `roadmap.md:238-241`). This is the natural workspace for a Cowork session.
- The inputs to each screening run (CV files, the JD) are already read from the
  project folder (`prd.md:124, 188`). Co-locating state with inputs is
  consistent with the Cowork workflow.
- The Cowork project-folder model provides isolation through a different
  mechanism: each Cowork project is a separate folder with its own `.tabp/`
  tree; simultaneous runs on different projects are naturally isolated without
  requiring an out-of-repo workspace path.

Two options were evaluated (`design.md:293-330`):

- **Option A — in the Cowork project folder (`<project>/.tabp/`):** PRD-
  mandated. Natural. No worktree issue. Chosen.
- **Option B — outside the project folder (mirroring ADR 0003):** An explicit
  workspace path would be configured in `tabp settings.json`. Unnecessary
  complexity; departs from PRD; no worktree collision to prevent.

## Decision

Store all tabp `.tabp/` run state and `tabp settings.json` in the **Cowork
project folder** at `<project>/.tabp/` and `<project>/tabp settings.json`
respectively.

This is a **deliberate divergence from ADR 0003** (state-outside-repo rule):
the rule does not apply to tabp because the underlying collision problem
(git-worktree ambiguity) does not exist in the Cowork project-folder model.
The PRD mandate (`prd.md:127-129`) is the primary driver.

The `--project-dir` argument to every `tabp_helper.py` subcommand is the
Cowork project folder path; the helper computes `<project-dir>/.tabp/` as the
state root. No out-of-repo workspace path is needed or configured.

## Consequences

- All `.tabp/` state is co-located with the screening inputs (CVs, JD) in the
  Cowork project folder — consistent with the Cowork workflow and PRD.
- `tabp_helper.py` derives the state root from `--project-dir` (supplied by the
  coordinator from the Cowork session context); no settings resolution chain is
  needed for the state path.
- Simultaneous runs on different Cowork projects are naturally isolated (each
  project has its own `.tabp/`). Simultaneous runs on the SAME project are
  guarded by the `O_EXCL` spin-lock (ADR 0023 / `tabp_helper.py`).
- This decision does not affect acs plugin state, which continues to follow
  ADR 0003 (outside-repo workspace).
- If a future use case introduces tabp runs across multiple concurrent worktrees
  of the same git repo (unlikely given Cowork's single-project model), this
  decision must be revisited and a new ADR created.
