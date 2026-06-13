# 0010 — Explicit-semver distribution with an update assistant

**Status**: Accepted · **Date**: 2026-06-13

## Context

With an explicit `version` in `plugin.json`, consumers receive updates only
on version bumps — pushing commits alone changes nothing for installed
copies. That is a feature (deliberate releases) and a footgun (forgotten
bumps; silent staleness).

## Decision

Keep explicit semver: release automation tags `v<version>` when
`plugin.json` bumps on main, with the matching CHANGELOG section as release
notes. Add `/acs:update`, a user-invoked-only upgrade assistant: version
comparison, CHANGELOG delta with breaking-change callouts, consented
marketplace refresh, and post-update migration checks (settings schema,
status-line absolute paths). Reloading stays the user's action.

## Consequences

Updates are deliberate and documented; the migration surface we created
(status-line paths embed the install path) is checked rather than left to
break silently; MAJOR bumps are contractually tied to breaking changes in
skills/hooks/settings/state shapes.
