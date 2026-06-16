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
| [0011](0011-sdlc-doc-sets-quality-and-operations.md) | Full-SDLC doc sets (quality, operations) + standing test runs | Proposed |
| [0012](0012-design-time-doc-consistency.md) | Design-time doc-consistency gap & staleness analysis | Proposed |
| [0013](0013-metrics-derives-panels-from-artifacts.md) | acs:metrics derives panels 4-6 from phase artifacts, not a schema extension | Accepted |
| [0014](0014-metrics-helper-emits-json-skill-renders.md) | metrics helper emits aggregate JSON; the skill renders show_widget | Accepted |
| [0015](0015-metrics-single-show-widget-call.md) | acs:metrics renders all six panels in a single show_widget call | Accepted |
| [0016](0016-metrics-bounded-single-pass-walk.md) | metrics aggregation uses a bounded single-pass walk with regex extraction | Accepted |
| [0017](0017-metrics-deterministic-cross-surface-rendering.md) | acs:metrics renders deterministically across surfaces via metrics_render.py | Accepted |

Format: status, date, context, decision, consequences (MADR-flavored, kept
short). New ADRs are appended by the pipeline with the next sequence number.
