# 0005 — XML subagent messaging validated by XSD

**Status**: Accepted · **Date**: 2026-06-12

## Context

Coordinator ↔ subagent traffic must be machine-checkable; malformed messages
should fail fast, not silently degrade the pipeline.

## Decision

Three message shapes (`task`, `result`, `handoff`) defined in
`acs-messages.xsd`; every message validated on send and receive
(`validate_xml.py`: xmllint when present, stdlib structural fallback —
hooks stay stdlib-only). Results carry file references, never artifact
bodies; a subagent's final message is the `<result>` element alone.

## Consequences

One re-request then hard failure on invalid messages; compact handoffs keep
/ship's context clearable; the XSD is the normative schema even where only
the structural fallback runs.
