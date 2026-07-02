# 0036 — Compute `ticket_ref` inside `build_title` via a `provider` parameter and a `--provider` CLI flag, one uniform template for every caller

**Status**: Accepted · **Date**: 2026-07-01

## Context

Once `{ticket_ref}` (ADR 0035) must be a genuine render-substitution key —
not just a CI regex-expansion branch — the remaining question is where that
value gets computed and how each of the four callers of `render-title`
(`create-pr`, `create-prd`, `create-architecture`, `create-project`) supplies
it.

A prior design iteration proposed having the coordinator pick a
per-provider template string in `create-pr/SKILL.md` prose (github →
`[#{external_key}] {title}`, jira → `[{external_key}] {title}`, else →
a `{ticket_id}`-literal fallback), leaving `build_title`
(`pr-conventions.py`) unchanged. That iteration's verifier proved the
premise false: `build_title`'s substitution mapping never contained a
`ticket_ref` key, so any template using `{ticket_ref}` rendered empty
brackets in every case, including the local/unsynced case that AC-3
requires to stay `[<ticket_id>] <title>`. Reproduced empirically against the
real `build_title` + `render_format`: `[{ticket_ref}] {title}` rendered
`"[] Render PR title"` for local, github, and jira inputs alike, before the
fix below.

## Decision

`build_title` gains a `provider` parameter (default `""`, additive and
behavior-preserving) and calls a new module-level `compute_ticket_ref
(provider, ticket_id, external_key)` helper, injecting its result into the
substitution mapping under the key `ticket_ref`:

```python
def compute_ticket_ref(provider, ticket_id, external_key):
    if provider == "github" and external_key:
        return "#%s" % external_key
    if provider == "jira" and external_key:
        return external_key
    return ticket_id or ""
```

`render-title`'s CLI gains a `--provider` flag (default `""`) threaded
straight through to `build_title`. Every caller — `create-pr` for any sync
state, plus the three product skills (`create-prd`, `create-architecture`,
`create-project`) — passes the SAME literal template `[{ticket_ref}]
{title}` (via its own committed `settings.formats.pr_title`) and supplies
its own `--ticket-id`/`--external-key`/`--provider`; `build_title` computes
`ticket_ref` identically for all four callers. `build_title` still calls
`render_format` exactly once per invocation — the existing mapping-builder
pattern is preserved unchanged.

## Alternatives considered

- **Coordinator picks a per-provider template string; render helper stays
  unchanged** (the rejected prior-iteration option). Fatal: the local/
  unsynced branch still renders empty brackets unless it falls back to a
  `{ticket_id}`-literal template, making three separate template strings the
  coordinator must hand-author and keep in lockstep with the CI alternation
  (ADR 0035) — exactly the drift risk the design's consistency/CI-safety NFR
  argues against. It also does nothing for the three product skills, each of
  which would need the same three-way branch duplicated in its own SKILL.md
  prose. Rejected: leaves the local case broken and duplicates
  provider-branching logic four times instead of once.

## Consequences

- `pr-conventions.py` is a real code change (new function, new parameter, new
  CLI flag) to shared helper code used by four skills — not documentation
  only.
- `provider` defaults to `""`, so `compute_ticket_ref("", ticket_id,
  external_key)` returns `ticket_id` — byte-identical output to
  pre-MAR-80 behavior for any caller that doesn't pass the new flag. All
  four `render-title` call sites (`create-pr/SKILL.md`,
  `create-prd/SKILL.md`, `create-architecture/SKILL.md`,
  `create-project/SKILL.md`) gain `--provider "<ticket.external.provider or
  empty>"` as a one-token addition to an existing command line.
- The `#`-prefix policy for GitHub and the verbatim-key policy for Jira live
  in exactly one Python function (`compute_ticket_ref`), not duplicated
  across four SKILL.md prose blocks — eliminating the drift risk the
  rejected alternative would have introduced.
- `test_render_title_uses_acs_lib_render_format`'s
  `spy.assert_called_once()` continues to hold because `build_title` still
  calls `render_format` exactly once; only the mapping's contents grow by
  one computed key.
