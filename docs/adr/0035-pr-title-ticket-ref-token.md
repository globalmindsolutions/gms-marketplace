# 0035 — Introduce a `pr_title`-only `{ticket_ref}` alternation token instead of overloading `{ticket_id}`

**Status**: Accepted · **Date**: 2026-07-01

## Context

`create-pr` renders `pr_title` from a single static template
(`settings.formats.pr_title`, default `[{ticket_id}] {title}`,
`.acs/settings.json:49`) regardless of whether the ticket is synced to a
remote tracker. MAR-75 (PR #160, merged) deliberately kept the title on the
local acs id and pushed tracker linkage into the PR body only (`Closes
#{external_key}`). MAR-80 is a scoped reversal of that one decision for the
title only: when a ticket is synced, the title should carry the tracker's own
native reference (`[#<issue-number>]` for GitHub, `[<JIRA-KEY>]` for Jira)
instead of the local id, because the local acs id is not yet consistent
across team members (the acs workspace isn't shared).

CI enforcement (`acs-conventions.yml` → `check-conventions.py --mode pr`) runs
on a runner with no acs install, no workspace, no `ticket.json` — its only
inputs are the committed `.acs/settings.json` formats and the `pull_request`
event payload. CI cannot know whether a given PR's ticket was synced; any
enforced format must therefore accept every legitimate shape from the title
string alone, with no per-PR sync signal (design.md "Binding constraint — CI
is stateless w.r.t. the ticket").

## Decision

Introduce one new format token, `{ticket_ref}`, valid only in `pr_title`.
`format_to_regex` (`check-conventions.py`) expands it to an anchored
alternation accepting all three legitimate bracket-content shapes: the local
id (`PREFIX-\d+`), the GitHub shape (`#\d+`), and the Jira shape
(`[A-Z][A-Z0-9]*-\d+`). The default `pr_title` becomes `[{ticket_ref}]
{title}`. The producer renders one concrete value per PR; CI matches the
alternation without needing to know which branch applied. `{ticket_id}`'s own
expansion (used unconditionally by `branch_name` and `commit_message`) is
untouched — it always means the strict `PREFIX-\d+` shape, everywhere.

## Alternatives considered

- **Broaden the existing `{ticket_id}` expansion in `pr_title` context only**
  (pass the format key into `format_to_regex` so `{ticket_id}` expands
  differently depending on which format string it appears in). Rejected:
  makes `{ticket_id}` mean two different things depending on caller context —
  a hidden, key-dependent behavior in a function whose current contract is
  "one token, one shape." `test_conventions_check.py`'s `FormatToRegexTests`
  pin `{ticket_id}` → strict `PREFIX-\d+` unconditionally; branching on the
  caller's format key risks breaking that pinned contract.
- **Two separate settings keys** (`pr_title` id-based + `pr_title_synced`
  tracker-based). Rejected: CI still can't tell which key SHOULD apply for a
  given PR (no ticket signal reaches it), so it degenerates to "accept
  either" — exactly this decision's alternation, but spread across two
  config keys, two regex compiles, and doubled `init/SKILL.md` prose. More
  configuration surface for no added safety.

## Consequences

- `{ticket_ref}` is additive to the format-token vocabulary: `init/SKILL.md`'s
  formats table, `settings.schema.json`'s `formats.pr_title` default and
  description, and `check-conventions.py`'s `_example()` all document/handle
  the new token.
- The scope-fence (`branch_name`/`commit_message` stay id-based) holds
  structurally, not by convention: the new token literally does not appear in
  those two formats' templates, so there is no code path by which they could
  pick up the alternation.
- The Jira branch (`[A-Z][A-Z0-9]*-\d+`) lexically overlaps the acs id branch
  (`PREFIX-\d+`) — acceptable because the regex is a gate (accept-if-
  conforms), not a classifier; CI never needs to tell which branch matched,
  only that the title conforms to at least one legitimate shape.
- `pr_title` is the only format scoped to carry `{ticket_ref}`; no other
  format field is extended by this decision.
