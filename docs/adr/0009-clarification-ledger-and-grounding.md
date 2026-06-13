# 0009 — Clarification ledger + grounding rules

**Status**: Accepted · **Date**: 2026-06-13

## Context

Requirement Q&A was scattered across specs, findings, and handoff notes —
skills re-asked answered questions, and silent model assumptions were
indistinguishable from user decisions.

## Decision

One append-only ledger per ticket (`clarifications.json`, via `clarify.py`)
with four rules: research first (never ask what repo/docs/ledger answer);
ask once at the cheapest phase (re-asking is a defect); record every answer
before acting on it; assumptions are visible debt (recorded with rationale,
surfaced in reports and the PR until user-confirmed). Paired with grounding
rules in every agent: every claim cites the file/section or quoted command
output it rests on; verifiers treat ungrounded work as blocking findings.

## Consequences

Clarifications survive sessions, handoffs, and /ship re-spawns; hallucinated
"facts" are findable (no citation) and blocked; behavior-defining answers
flow into the living requirements (ADR 0007).
