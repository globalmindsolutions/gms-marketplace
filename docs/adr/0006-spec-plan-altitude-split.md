# 0006 — Standing spec/plan altitude split (keep /create-spec)

**Status**: Accepted · **Date**: 2026-06-13 (rejected merging /create-spec into the code planner)

## Context

Specs and code plans overlap superficially (both analyze the ticket and the
repo), prompting a proposal to remove `/create-spec`.

## Decision

Keep both, at fixed altitudes: specs own the WHAT — contracts, API/data
changes, acceptance-level test plan, scope boundary (indicative paths at
most); the code plan owns the HOW — the authoritative file map, executor
decomposition, concrete failing tests. The spec set is the loop's **fixed
point** (authored interactively, gated, stable across iterations); the plan
is the **variable** (rewritten each remediation iteration, headless).

## Consequences

The review loop has an immovable yardstick (no moving goalposts); user
clarification happens where it is cheap (before implementation); duplicated
file-mapping was removed from specs; an exhaustive file list in a spec's
Approach is itself a verifier finding.
