# Architecture Decision Records

Decision records for the **acs plugin itself** (dogfooding `adr_path`). On
consumer repos this folder is maintained by `/acs:code`, which commits each
ticket design's accepted decisions; these first ten are retrofitted from the
[decision log](../README.md#decision-log) — the log remains the complete,
dated history, while ADRs carry the load-bearing architecture choices with
context and consequences.

| # | Decision | Status |
|---|----------|--------|
| [0001](0001-two-layer-architecture.md) | Deterministic scripts vs. judgment prose | Accepted |
| [0002](0002-hook-event-binding.md) | Hook event binding on PreToolUse(Skill) | Accepted |
| [0003](0003-file-based-state-outside-repo.md) | File-based state in a workspace outside the repo | Accepted |
| [0004](0004-reflection-with-independent-verifier.md) | Reflection trio; verifier anchors on gated contracts | Accepted |
| [0005](0005-xml-messaging-with-xsd.md) | XML subagent messaging validated by XSD | Accepted |
| [0006](0006-spec-plan-altitude-split.md) | Standing spec/plan altitude split (keep /create-spec) | Accepted |
| [0007](0007-living-docs-by-induction.md) | Living architecture & requirements by induction | Accepted |
| [0008](0008-conditional-steps-as-ticket-data.md) | Conditional steps are ticket data, never invocation options | Accepted |
| [0009](0009-clarification-ledger-and-grounding.md) | Clarification ledger + grounding rules | Accepted |
| [0010](0010-explicit-semver-distribution.md) | Explicit-semver distribution with an update assistant | Accepted |

Format: status, date, context, decision, consequences (MADR-flavored, kept
short). New ADRs are appended by the pipeline with the next sequence number.
