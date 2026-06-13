# HLD — Overview

> Living architecture doc set for the **acs plugin itself** (dogfooding:
> this repo is a consumer repo of its own product). Bootstrapped from the
> implemented system; kept current by the pipeline per the living-architecture
> rules in `docs/requirements/workflow.md`. All diagrams are Mermaid.

## System context

acs is a Claude Code plugin distributed from this repository (a plugin
marketplace). Installed into a user's Claude Code, it drives an agentic
software-delivery workflow on any **consumer repository**, persisting all
pipeline state into a **workspace folder outside that repo**.

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
