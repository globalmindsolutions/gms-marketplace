# HLD — Overview

> Living architecture doc set for the **GMS Marketplace** — a curated plugin
> catalog hosting heterogeneous plugins for Claude Code and Cowork (dogfooding:
> this repo is itself a consumer of acs, one of the marketplace plugins).
> Bootstrapped from the implemented system; kept current by the pipeline per
> the living-architecture rules in `docs/requirements/workflow.md`. All
> diagrams are Mermaid.

## System context

The GMS Marketplace is a curated plugin catalog that hosts heterogeneous
plugins distributed from this repository. Plugins differ in shape:

- **acs** (full-shape: `.acs/`, schemas, hooks, agents, skills) — targets
  **Claude Code**; drives an agentic software-delivery workflow on any
  **consumer repository**, persisting all pipeline state into a **workspace
  folder outside that repo**.
- **tabp** (fuller shape: `skills/` + `helpers/` + `schemas/` + `agents/` + `.tabp/` state) — targets
  **Cowork**; provides a screen-CVs recruiting workflow where a coordinator
  fans out Sonnet-per-CV subagents and an Opus synthesis subagent, persisting
  all run state in the project folder's `.tabp/` directory.

## Quality attributes (drive the design)

| Attribute | Architectural answer |
|-----------|----------------------|
| Enforceable ordering | Deterministic gate scripts on the `PreToolUse(Skill)` event; exit 2 blocks; gates fail closed. |
| Resumability | File-based state only: append-only run history, phase artifacts, pipeline ledger; no conversation memory between steps. |
| Verification independence | Separate planner/executor/verifier contexts; verifiers anchor on gated upstream contracts, re-run all cheap checks. |
| Parallelism | Workspace partitioned by repo → ticket; per-checkout pointers; re-entrant per-checkout locks; worktree-per-ticket. |
| Portability | stdlib-only Python ≥ 3.9 hooks; markdown skills/agents; no pip installs on consumer machines. |
| Auditability | Pretty-printed JSON everywhere; archives never deleted; clarification ledger; per-run metrics. |

## Key architectural decisions

1. **Two-layer split**: everything deterministic (gating, ids, locks, state
   writes, validation) lives in Python scripts; everything judgment-shaped
   (analysis, authoring, review) lives in prompts (skills/agents). The prose
   layer is forced to leave deterministic footprints the script layer gates on.
2. **The ticket partition is the only inter-step channel** — coordinators are
   stateless between steps; `/ship`'s context can be cleared at any boundary.
3. **Conformance chain** PRD → architecture → design → specs → code, each
   level verified against the one above by a fresh context.
4. **Fail-safe prose**: a skill that forgets its post-hook leaves
   `runs[-1] = in_progress` — the next gate reads "not completed"; nothing
   unlocks by omission.

## Document map

- `c4-context.md`, `c4-container.md`, `c4-component.md` — C4 levels 1–3.
- `data-model.md` — workspace state entities (ER).
- `deployment.md` — distribution & runtime topology.
- `tech-stack.md` — languages, formats, conventions.
- `../lld/flows/*.md` — sequence diagrams for the key runtime flows.
- `../lld/contracts.md` — interface contracts between components.
