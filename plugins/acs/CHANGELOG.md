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

- **Two-skill metrics split: `/acs:metrics` (PM view) + `/acs:usage` (usage view) (MAR-14).**
  The former single-view `/acs:metrics` skill is split into two narrowly-scoped
  utility skills over one shared stdlib aggregator:

  - **`/acs:usage`** is a new model-invocable utility skill (skill count 15 → 16,
    unhooked) that renders the **usage view**: usage summary (total cost, total
    working time, total runs, plus four averages — avg working time per ticket and
    per merged PR, avg cost per ticket and per merged PR), cost + time per ticket
    by pipeline step with the four averages (Panel 3), and token burn by role
    (Panel 6). Backed by `metrics_aggregate.py` (shared superset) then
    `metrics_render.py --view usage`. Read-only; no network call; no config key.

  - **`/acs:metrics`** is re-scoped to the **PM view**: delivery summary (headline
    KPIs — tickets done/total, PRs merged, avg lead/cycle, coverage pass rate),
    throughput by status/type (Panel 1), pipeline funnel + distinct PRs (Panel 2),
    ISSUES (id/title/status/type/GitHub key), PROGRESS (per-epic done/total +
    burn-up visual), DEADLINE ("not set" degraded frame — deadline tracking requires
    a `due_date` ticket field, wired in Child 3 / MAR-15), coverage achieved vs
    target (Panel 4), review iterations before the verifier passed (Panel 5), and
    lead + cycle time per ticket (Panel 7). Invokes `metrics_render.py --view pm`.

  **Shared mechanism.** `metrics_aggregate.py` emits one superset JSON carrying all
  panel keys for both views (the PM union usage full set; no panel appears in both
  views). `metrics_render.py` gains four new view entrypoints —
  `render_pm_terminal`, `render_pm_html`, `render_usage_terminal`,
  `render_usage_html` — selected by the new `--view {pm,usage}` CLI flag (bare
  `metrics_render.py` with no `--view` defaults to the PM view; both skills invoke
  the renderer with the flag explicitly). The existing `render_terminal` /
  `render_html` entrypoints and `--view all` remain for back-compat.

  **DEADLINE panel** ships as a "not set" B1-compliant degraded frame in this
  release (the panel key is always present; it renders "not set" without error).
  Child 3 / MAR-15 wires real due-date data via a `due_date` field on the ticket.

- **Ticket `due_date` field + live DEADLINE panel (MAR-15).** The DEADLINE panel
  in `/acs:metrics` (PM view) now derives and displays real on-track/overdue
  status from each ticket's `due_date`:

  - **`due_date` on `ticket.json`** is a new optional ISO-8601 date field
    (`YYYY-MM-DD` or null; additive, back-compatible — existing tickets with no
    `due_date` are valid and the panel degrades gracefully to "not set").
    `/acs:create-ticket` elicits and sets `due_date`; the `--due-date` option on
    `new-ticket.py` accepts and validates the value (malformed input is rejected
    with a non-zero exit).
  - **DEADLINE panel — live derivation.** `metrics_aggregate.py` reads each
    ticket's `due_date` (from the `ticket.json` already opened per ticket) and
    derives: *overdue* when `due_date < now` and the ticket is not done;
    *on-track* otherwise.  The panel shows one row per ticket with a `due_date`,
    plus a roll-up summary.  A workspace with no parseable `due_date` on any
    ticket degrades to the "not set" state (B1 — the panel key is always
    present; no crash).  An empty workspace keeps `deadline == "no data"`.
  - **Read-only.** Aggregator and renderer write nothing; the only new write is
    `due_date` at create-ticket.  No network call; no new config key.
    Deterministic: the reference "now" is the same instant stamped into
    `meta.generated_at` (pinnable in tests); the renderer reads no clock.

  This supersedes the MAR-14 interim "not set" degraded frame.

- **Distinct-PR counting via `created_pr_numbers` + idempotent backfill (MAR-13 spec 01).**
  `prs.created` in `metrics.json` now counts **distinct PRs** rather than completed
  `create-pr` run invocations — a single PR re-triggered multiple times no longer
  inflates the metric.  `update_metrics` gains an optional `pr_number` parameter;
  when `pr_created` is truthy and `pr_number` is a positive integer not already
  recorded, it is appended to a sorted de-duped `prs.created_pr_numbers` list and
  `prs.created` is set to `len(created_pr_numbers)` (idempotent: re-runs with the
  same number are a no-op).  A one-time idempotent `backfill_distinct_pr_count`
  helper heals already-inflated history by recomputing `created_pr_numbers` from
  the distinct positive `states.pr.number` values across all active and `archive/`
  partitions; re-running it is safe and produces the same result.  The
  `created_pr_numbers` field is additive on the `prs` object (no schema break); all
  other metric paths (`tokens`, `cost_usd`, `prs.merged`, ticket counts) are
  unchanged.  No new runtime dependency; no network call.
- **Lead/cycle re-cycle hardening + per-ticket re-work count (MAR-13 spec 02).**
  Panel 7 (`metrics_aggregate.py`) now carries an explicit overlap-safe guarantee:
  `aggregate()` never raises when a ticket's `code.started_at` falls after its
  `merge-pr.ended_at` (a re-cycled or overlapping step span) — the affected
  `cycle_seconds` value renders as `"no data"` and a `meta.degraded` entry (panel 7)
  is appended; one row per ticket is always returned; nothing is written.  This
  guarantee is documented in the `_elapsed_seconds` and `_panel7_row` docstrings and
  is now covered by a dedicated cycle-inversion test
  (`test_cycle_inversion_yields_no_data`).  In addition, each Panel-7 per-ticket row
  gains a new additive `rework_count` integer field (>= 0) equal to the count of
  distinct positive PR numbers recoverable from that ticket's `create-pr-state.json`
  in the resolved partition; 0 when the file is absent, malformed, or carries no
  positive PR number.  `rework_count` is read-only (zero writes), stdlib-only, and
  is not averaged at the panel level — it is per-ticket metadata next to
  `lead_seconds` / `cycle_seconds`.  No schema break; no new config key; no network
  call.
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
  model-invocable utility skill that renders dashboard panels for the current repo —
  throughput by status/type, pipeline funnel, cost and time per ticket by step,
  coverage achieved vs target, review iterations before the verifier passed, and
  token burn by role (planner/executor/verifier). Backed by the stdlib-only
  `metrics_aggregate.py` helper, which aggregates the panels from existing
  workspace artifacts and emits one JSON object (every panel key always present;
  degradation is an in-band "no data" marker, never a missing key). The skill is
  read-only: it writes no file, makes no network call, and adds no config key.
- **Deterministic cross-surface metrics renderer (MAR-5).** Rendering is now a
  deterministic stdlib helper `metrics_render.py` that consumes the aggregate
  JSON and emits the dashboard panels on two surfaces: a Unicode block-bar
  **terminal** dashboard for the Claude Code CLI (default) and a self-contained
  **HTML** component (`--html`, inline CSS, no external fetch) handed to
  `show_widget` verbatim on Claude Desktop / claude.ai. The skill now **routes**
  (aggregate → render) instead of model-composing the layout, and the
  deterministic terminal renderer **supersedes** the former model-improvised
  Markdown-table fallback. `metrics_render.py` is stdlib-only, never imports
  `show_widget`, is read-only, and is deterministic (identical JSON in →
  byte-identical output; no clock read in render) — unit-tested to the same 90%
  coverage bar as the aggregator.
- **`/acs:metrics` delivery-flow metrics (MAR-7).** The dashboard now surfaces
  delivery-flow timing on both render surfaces: **Panel 3** gains four **averages**
  summary rows — avg working time and avg cost, each per ticket and per merged PR
  (a zero denominator renders "no data") — and a **new Panel 7 — Lead + cycle time
  per ticket** shows per-ticket **lead** (`ticket.json.created_at` → `merge-pr`
  end) and **cycle** (`code` start → `merge-pr` end) wall-clock times plus their
  averages, with humanized `d`/`h`/`m`/`s` durations. Aggregated additively in
  `metrics_aggregate.py` and rendered in `metrics_render.py` (terminal + HTML),
  read-only and deterministic, with every "no data" value rendering a present "no
  data" cell — no schema, config, or network change.

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
