# 0001 — Deterministic scripts vs. judgment prose

**Status**: Accepted · **Date**: 2026-06-12

## Context

An agentic pipeline whose ordering, state, and bookkeeping depend on model
behavior cannot be trusted: models forget steps, improvise scope, and cannot
guarantee idempotent writes. Yet analysis, authoring, and review genuinely
require judgment.

## Decision

Split every responsibility into exactly one of two layers. Everything
deterministic — gating, id allocation, locking, state writes, validation,
metrics — is stdlib-Python scripts (`hooks/scripts/`). Everything
judgment-shaped — analysis, design, specs, code, review — is prompts (skills,
agents). The prose layer must leave deterministic footprints (state files,
phase artifacts) that the script layer gates on; no prose can unlock a gate.

## Consequences

The deterministic layer is fully unit-testable without a model (39-test
suite); prose failures are fail-safe (a skipped post-hook leaves the next
gate closed); the cost is a strict discipline — "carefully update the JSON"
in a SKILL.md is a bug, fixed by adding a helper script.
