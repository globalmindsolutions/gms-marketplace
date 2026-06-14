# Changelog

All notable changes to the `acs` plugin are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Releases are automated: bump `version` in BOTH
`.claude-plugin/marketplace.json` and `plugins/acs/.claude-plugin/plugin.json`
to the same value, point the acs `source.ref` in `marketplace.json` at
`v<version>`, add a matching section here, and merge to `main` — the Release
workflow tags `v<version>` and publishes a GitHub release using that section as
the notes.

## [Unreleased]

## [0.1.6] - 2026-06-14

### Fixed

- `/acs:init` now reliably gitignores `<repo>/.acs/settings.local.json`. The
  Step 5 ignore step is rewritten to run on **every** init (fresh and re-run,
  even when no keys changed), so a repo first initialized by an older acs that
  has the file but no ignore rule gets retro-fixed. It uses `git check-ignore`
  instead of an exact-line `grep` (a broader existing rule like `.acs/` now
  counts as ignored, so no duplicate line is appended) and guarantees a
  trailing newline before appending so the entry can't glue onto the last line
  of an existing `.gitignore`.

## [0.1.5] - 2026-06-14

### Changed

- Unified release versioning: the marketplace catalog and the `acs` plugin now
  share **one version** and a single `v<version>` release tag. The separate
  `marketplace-v<version>` tag scheme and its workflow are retired. Cutting a
  release now bumps `version` in both `.claude-plugin/marketplace.json` and
  `plugins/acs/.claude-plugin/plugin.json` to the same value and points the acs
  `git-subdir` `source.ref` at the new `v<version>` tag; CI enforces that the
  two versions match. Existing `marketplace-v*` tags remain valid in history.

## [0.1.3] - 2026-06-13

### Changed

- **Breaking**: marketplace `name` renamed from `gms-plugins` to `gms-marketplace`.
  Existing consumers must migrate:
  1. Rename the key in `extraKnownMarketplaces` (managed settings or
     `~/.claude/settings.json`) from `"gms-plugins"` to `"gms-marketplace"`.
  2. Re-run `claude plugin install acs@gms-marketplace` (the old
     `acs@gms-plugins` reference no longer resolves).

## [0.1.2] - 2026-06-13

### Fixed

- Plugin failed to install on current Claude Code (manifest validation:
  `Unrecognized key: "displayName"`), leaving `acs@gms-marketplace` uninstallable
  even after the v0.1.1 hooks fix. Removed the unsupported `displayName` key
  from `plugin.json`; the marketplace lists the plugin by `name` +
  `description`. Caught by the M2-0 validation spike
  ([docs/product/m2-0-validation-spike.md](../../docs/product/spikes/m2-0-validation-spike.md)).

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

[Unreleased]: https://github.com/globalmindsolutions/gms-marketplace/compare/v0.1.3...HEAD
[0.1.3]: https://github.com/globalmindsolutions/gms-marketplace/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/globalmindsolutions/gms-marketplace/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/globalmindsolutions/gms-marketplace/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/globalmindsolutions/gms-marketplace/releases/tag/v0.1.0
