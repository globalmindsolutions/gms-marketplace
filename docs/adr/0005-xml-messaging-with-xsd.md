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

## Implementation note (MAR-61)

As of MAR-61, the engine default was inverted: the in-process stdlib structural
validator (`validate_structurally` in `validate_xml.py`) is now the **default
fast path** for every message.  `xmllint` is now **opt-in** via the
`ACS_XML_AUTHORITATIVE=1` environment variable (PATH-guarded; absent xmllint
never blocks a verdict).  The structural validator was audited against every
rule in `acs-messages.xsd` and confirmed XSD-equivalent; the AC-2 parity corpus
(`tests/acs/test_acs_plugin.py:TestValidators`) is the binding proof.  The
Decision and Consequences sections above remain unchanged — the XSD is still the
normative authority; only the runtime engine changed.
