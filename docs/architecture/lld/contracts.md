# LLD — Interface contracts

The binding shapes live in machine-validated files; this page is the index.
Canonical detail: `plugins/acs/docs/INTERNALS.md`.

## Coordinator ↔ subagent (XML, `plugins/acs/schemas/acs-messages.xsd`)

| Message | Direction | Key content |
|---------|-----------|-------------|
| `<task skill phase ticket-id iteration>` | coordinator → subagent | objective, `<inputs>` file refs, `<constraints>`, `<context>` (clarifications, prior findings) |
| `<result … status>` | subagent → coordinator (final message, nothing after) | `<outputs>` file refs (incl. the phase artifact), `<findings>`, `<errors>`, `<questions>`, `<metrics>` |
| `<handoff … status>` | step coordinator → /ship | ≤ ~1 KB summary, artifact refs, `<next-step>`, `<questions>` on `needs_input` |

Validation: `validate_xml.py` on every send/receive; one re-request, then fail.

## Coordinator ↔ deterministic layer (CLI)

| Helper | Contract |
|--------|----------|
| `skill-start.py --skill S [--ticket\|--args\|--allocate]` | stdout: context JSON (settings, partition, ticket, models, reconcile/handoff, post_hook path); registers `in_progress` run, lock, pointer |
| `post-<skill>.py --ticket T --result-file F` (or stdin JSON) | input: the **result document** `{status, stop_reason, states, findings, errors, tokens, cost_usd[, handoff_summary]}`; finalizes run + ledger + index + metrics, releases lock |
| `new-ticket.py --title --type [--parent --needs-design --docs-only …]` | mints id + partition + mint-time create-ticket state; epic backlinks |
| `clarify.py add\|answer\|list` | the Q&A ledger (`clarifications.json`); assumptions need `--rationale` |
| `handoff.py --summary` | finalizes `handed_off`, releases lock, prints `continue_with` |

Exit codes: 0 ok; 2 blocked/invalid with actionable stderr.

## Hook events (Claude Code)

`PreToolUse(Skill)` → `dispatch.py pre` → `pre-<skill>.py` (exit 2 blocks);
`SessionEnd` → `dispatch.py session-end` (finalize `interrupted`, release lock).

## Inter-step contract (state files)

The next skill reads only canonical `states` keys — e.g. `/create-pr` gate:
`code-state.states.verifier_passed == true`; `/merge-pr` gate: a `states.pr`
reference in `create-pr-state` (or the product skill's state). Full table:
INTERNALS.md "Canonical states keys per skill". Schemas:
`plugins/acs/schemas/*.schema.json`.

## Settings (consumer repo)

`.acs/settings.json` (+ gitignored `settings.local.json`, user-scope file);
per-key merge local → project → user; validated by every pre-hook
(`settings.schema.json`): `workspace_path`, `ticket_prefix`,
`test_coverage_percent`, `merge_strategy`, `prd_path`, `architecture_path`,
`adr_path?`, `e2e?`, `models`, `tracker`, `formats`.
