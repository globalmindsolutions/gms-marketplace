# 0004 — Reflection trio; verifier anchors on gated contracts

**Status**: Accepted · **Date**: 2026-06-12, sharpened 2026-06-13

## Context

A model reviewing its own output rubber-stamps. A verifier judging against
the same-iteration plan certifies plan-conformant-but-wrong work.

## Decision

Each hooked skill runs plan → execute → verify with three separate agent
contexts. The verifier anchors on the **gated upstream contracts** (specs,
ticket, design) — never the same-iteration plan (it consumes only the plan's
verifier-checklist section, a floor never a ceiling) and never executor
narratives; it re-runs every cheap check itself. All findings block;
remediation loops are capped at 3 iterations. Every phase writes its own
artifact (`iter-<n>-plan.md` / `-execute.json` / `-verify.md`).

## Consequences

A wrong plan is caught (code judged against specs fails; the next plan must
remediate); resumption can lose at most the in-flight phase; native plan
mode is unused — planners are headless subagents (ADR context: user approval
has no meaning there).
