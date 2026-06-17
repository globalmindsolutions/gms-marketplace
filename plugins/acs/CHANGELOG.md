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

### Added

- **Pipeline-default `CLAUDE.md` guidance + exempt non-ticket merge path (MAR-9).**
  Two changes that make the acs pipeline the *automatic* path in an installed
  repo and close the non-ticket dead end. (1) `/acs:init` gains an opt-in
  (default-on) step that writes an idempotent, marker-delimited **acs-managed
  block** into the repo's `CLAUDE.md` (from the new `templates/CLAUDE.acs.md`),
  steering every Claude session to ship via `/acs:ship` instead of a raw
  `gh pr create` — re-runs replace only the block, never the surrounding
  content. (2) `/acs:merge-pr --pr <n>` (also `#n` or a PR URL) lands a
  legitimate one-off **exempt** PR: it runs the same four readiness checks and
  branch/worktree cleanup as the ticket path but resolves no ticket, writes no
  partition/state, and skips tracker sync and archiving (bumping only the repo
  `pr_merged` metric). `skill-start.py --pr` validates the PR carries the
  configured `exempt_label` (or an `exempt_branches` head) and refuses +
  redirects to `/acs:merge-pr <ticket-id>` when the PR looks ticket-backed. The
  existing ticket-backed merge flow and every other gate are unchanged.
- **`/acs:metrics` — read-only delivery dashboard (MAR-5).** A new
  model-invocable utility skill that renders six panels for the current repo —
  throughput by status/type, pipeline funnel, cost and time per ticket by step,
  coverage achieved vs target, review iterations before the verifier passed, and
  token burn by role (planner/executor/verifier). Backed by the stdlib-only
  `metrics_aggregate.py` helper, which aggregates the panels from existing
  workspace artifacts and emits one JSON object (every panel key always present;
  degradation is an in-band "no data" marker, never a missing key). The skill is
  read-only: it writes no file, makes no network call, and adds no config key.
- **Deterministic cross-surface metrics renderer (MAR-5).** Rendering is now a
  deterministic stdlib helper `metrics_render.py` that consumes the aggregate
  JSON and emits the same six panels on two surfaces: a Unicode block-bar
  **terminal** dashboard for the Claude Code CLI (default) and a self-contained
  **HTML** component (`--html`, inline CSS, no external fetch) handed to
  `show_widget` verbatim on Claude Desktop / claude.ai. The skill now **routes**
  (aggregate → render) instead of model-composing the layout, and the
  deterministic terminal renderer **supersedes** the former model-improvised
  Markdown-table fallback. `metrics_render.py` is stdlib-only, never imports
  `show_widget`, is read-only, and is deterministic (identical JSON in →
  byte-identical output; no clock read in render) — unit-tested to the same 90%
  coverage bar as the aggregator.

## [0.2.0] - 2026-06-14

### Added

- **`/acs:init` toolchain preflight (Step 0b).** Init now checks every external
  tool the full workflow needs up front and offers to install the missing ones
  (consent-gated, platform-aware) instead of failing mid-pipeline on a missing
  `gh` or `pre-commit`. Backed by `acs_lib.check_toolchain()` — the single
  source of truth listing `git`, `python3`, `gh`, `pre-commit`, `xmllint`,
  `acli` with kind (required | recommended | optional, bumped by tracker
  provider) and per-platform install commands — plus `acs_lib.missing_tools()`.
  The Step 8 summary now also confirms the full skill set is ready.

- **CI enforcement of acs conventions (opt-in via `/acs:init`).** A new Step 7c
  offers to scaffold repo-side enforcement so a PR that never went through
  `/acs:create-pr` is still held to the same conventions before it can merge.
  It installs:
  - `.github/workflows/acs-conventions.yml` — a `pull_request` check (re-runs on
    title/body edits and label changes) that validates **branch name**, **PR
    title**, **PR description sections**, the **`ACS` label**, and (opt-in)
    **commit-message** format.
  - `.acs/ci/check-conventions.py` — a self-contained, stdlib-only checker that
    compiles the committed `formats.*` strings into regexes (the same vocabulary
    the pipeline renders from) and reads `ticket_prefix` + `formats` from the
    committed `.acs/settings.json`; **no acs install is needed on the runner**.
    It is FAIL-CLOSED (no committed conventions → error + "run /acs:init") and
    runs in `--mode pr` (CI), `--mode pre-push`, or `--mode commit-msg` (local
    hooks) — the same checker and the same configured formats everywhere.
  - Optional **local git hooks** that enforce conventions *before* push, against
    the SAME configured `formats.*`/`enforcement.*`: `commit-msg` validates the
    commit subject against `formats.commit_message` as it is written, and
    `pre-push` validates `formats.branch_name` + the push range's commit
    subjects. Installed via the pre-commit framework (tracked, shared across the
    team) or as raw `.git/hooks/*` (per-clone). PR title/description stay CI-only
    (they don't exist until a PR is open).
  - New **`enforcement`** settings block (`schemas/settings.schema.json`):
    `checks.*` toggles, `exempt_branches` globs, `exempt_label`, `require_label`,
    and `pr_description_sections`.
- **New skill `/acs:install-hooks`** — the `pre-commit install` equivalent for
  acs: installs this clone's local `commit-msg` + `pre-push` hooks (per-clone,
  user-invoked). It ensures the `.acs/ci/` files exist (copying them from the
  plugin if needed), then installs via the pre-commit framework when the repo
  uses it or via raw git hooks otherwise. A committed `.acs/ci/install-hooks.sh`
  lets a teammate who only cloned the repo run it (`sh .acs/ci/install-hooks.sh`)
  without the acs plugin. `/acs:init` Step 7c now copies the hook scripts +
  installer into `.acs/ci/` and points at this command.
- **No-bypass gate guidance.** Because branch/title are cosmetic and the proof
  of pipeline use lives in the workspace outside the repo, the check is *mandatory
  to merge* but the real gate is a **required status check on a protected default
  branch**. Step 7c detects repo-admin (`gh api .permissions.admin`) and either
  configures branch protection via `gh api` or prints the one-time admin command,
  with a configurable **`acs-exempt` label + branch allowlist** escape hatch for
  releases and bot PRs.

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

[Unreleased]: https://github.com/globalmindsolution/gms-marketplace/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/globalmindsolution/gms-marketplace/compare/v0.1.6...v0.2.0
[0.1.6]: https://github.com/globalmindsolution/gms-marketplace/compare/v0.1.5...v0.1.6
[0.1.5]: https://github.com/globalmindsolution/gms-marketplace/compare/v0.1.3...v0.1.5
[0.1.3]: https://github.com/globalmindsolution/gms-marketplace/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/globalmindsolution/gms-marketplace/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/globalmindsolution/gms-marketplace/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/globalmindsolution/gms-marketplace/releases/tag/v0.1.0
