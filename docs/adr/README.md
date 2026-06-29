# Architecture Decision Records

Decision records for the **GMS Marketplace** (including acs and its plugins, dogfooding `adr_path`). On
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
| [0007](0007-living-docs-by-induction.md) | Living architecture, requirements & factual product docs by induction | Accepted |
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
| [0018](0018-distinct-pr-counting-via-created-pr-numbers.md) | Distinct-PR counting via a recorded `created_pr_numbers` set | Accepted |
| [0019](0019-split-acs-metrics-into-pm-and-usage-skills.md) | Split `/acs:metrics` into two narrowly-scoped skills: PM delivery and tool usage | Accepted |
| [0020](0020-ticket-due-date-and-deadline-panel.md) | Deadlines sourced from a `due_date` ticket field (not the GitHub tracker, not deferred) | Accepted |
| [0021](0021-heterogeneous-plugin-contract-via-directory-convention-shapes.md) | Heterogeneous plugin contract via directory-convention shapes | Accepted |
| [0022](0022-behavioral-evals-local-only-ci-runs-no-llm-calls.md) | Behavioral evals are local-only; CI runs no LLM calls | Accepted |
| [0023](0023-tabp-hybrid-quality-mechanism-instruction-driven-plus-stdlib-helper.md) | tabp quality-mechanism: hybrid instruction-driven orchestration plus tabp-namespaced stdlib-Python helper (deliberate divergence from ADR 0001 hook-gated model) | Accepted |
| [0024](0024-tabp-state-in-cowork-project-folder.md) | tabp state in the Cowork project folder (deliberate divergence from ADR 0003 outside-repo rule) | Accepted |
| [0025](0025-tabp-independent-verifier-subagent.md) | tabp independent verifier: inline-artifact input contract and bounded (N=3) remediate-and-re-verify loop | Accepted |
| [0026](0026-tabp-hybrid-cost-sourcing.md) | tabp hybrid cost sourcing: transcript-actuals plus settings-configurable dated-snapshot pricing | Accepted |
| [0027](0027-tabp-dual-runtime-detection.md) | tabp dual-runtime detection: explicit `--runtime` flag with auto-detect fallback (cwd-as-project-dir on Claude Code) | Accepted |
| [0028](0028-merge-pr-agent-invocable.md) | merge-pr is agent/model-invocable; readiness gate + m6 require-APPROVED-for-all | Accepted |
| [0029](0029-merge-pr-auto-update-behind-branch.md) | merge-pr auto-updates a BEHIND branch then merges in the same run | Accepted |

Format: status, date, context, decision, consequences (MADR-flavored, kept
short). New ADRs are appended by the pipeline with the next sequence number.
