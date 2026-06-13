# Changelog

All notable changes to the `acs` plugin are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Releases are automated: bump `version` in
`plugins/acs/.claude-plugin/plugin.json`, add a matching section here, and
merge to `main` — the Release workflow tags `v<version>` and publishes a
GitHub release using that section as the notes.

## [Unreleased]

## [0.1.1] - 2026-06-13

### Fixed

- Plugin failed to load on install with "Duplicate hooks file detected"
  because `plugin.json` declared `"hooks": "./hooks/hooks.json"` — a file
  Claude Code already auto-loads by convention. Removed the redundant
  manifest key so the plugin loads cleanly on a fresh install (GMS-5).

## [0.1.0] - 2026-06-12

Initial release.

### Added

- Claude Code plugin marketplace manifest (`.claude-plugin/marketplace.json`)
  listing the `acs` plugin; install with
  `claude plugin marketplace add <github-url>`.
- 12 skills: `/acs:init`, `/acs:ship`, `/acs:handoff`, `/acs:create-prd`,
  `/acs:create-architecture`, `/acs:create-project`, `/acs:create-ticket`,
  `/acs:create-design`, `/acs:create-spec`, `/acs:code`, `/acs:create-pr`,
  `/acs:merge-pr`.
- 27 subagents: planner/executor/verifier triples for each of the 9 workflow
  and product-level skills, driving the plan -> execute -> verify reflection
  cycle (max 3 iterations).
- Hook-gated pipeline: a `PreToolUse` dispatcher plus pre/post hooks per
  hooked skill — each skill refuses to run (exit 2) until its predecessor's
  run completed, post-hooks finalize run state and release locks, and a
  `SessionEnd` safety net marks interrupted runs.
- Workspace state outside the consumer repo: per-ticket partitions
  (`ticket.json`, `pipeline-state.json`, `design.md`, `specs/`, phase
  artifacts, result documents) plus repo-level `tickets-index.json`,
  `counters.json`, `metrics.json`, per-checkout session pointers, and
  `archive/` for merged tickets.
- Helper CLIs: `skill-start.py`, `new-ticket.py`, `handoff.py`,
  `validate_xml.py` (under `hooks/scripts/`).
- JSON Schemas for every workspace document
  (`plugins/acs/schemas/*.schema.json`).
- XSD-defined XML messaging (`plugins/acs/schemas/acs-messages.xsd`):
  `task`, `result`, and `handoff` messages between coordinator and subagents.
- Description templates (`plugins/acs/templates/`): `epic-default.md`,
  `story-default.md`, `task-default.md`, `pr-default.md`.
- Unit test suite (`tests/`) and CI: tests on Python 3.9 and 3.12, JSON and
  JSON Schema validation, XSD validation, hook-script byte-compilation, and
  skill/agent frontmatter checks.
- Automated release workflow: tags `v<version>` and publishes a GitHub
  release from the matching changelog section when the plugin manifest
  version changes on `main`.

[Unreleased]: https://github.com/globalmindsolutions/gms-marketplace/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/globalmindsolutions/gms-marketplace/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/globalmindsolutions/gms-marketplace/releases/tag/v0.1.0
