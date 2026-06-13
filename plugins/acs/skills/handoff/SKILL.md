---
name: handoff
description: Deliberately hand the current ticket off to a fresh session — flush in-flight soft context to the ticket partition, finalize the run as handed_off, release the lock, and print the exact command to continue. Use when the session has grown long, the user wants to stop and resume later, or the user says "hand off" / "continue this in a new session".
argument-hint: "[ticket-id]"
---

You are the coordinator of `/acs:handoff` — the session-handoff utility skill.

This skill is NOT part of the gated pipeline: no pre/post hooks fire for it, you
spawn NO subagents, and you do NOT run `skill-start.py` (it would acquire the
lock and append a new run — the opposite of what a handoff does). You touch the
consumer repo read-only; the only file you write is `handoff-context.md` inside
the ticket partition. All state mutation (run finalization, pipeline ledger,
lock release) is done by `handoff.py` — never edit `<skill>-state.json`,
`pipeline-state.json`, or `.lock` by hand.

A handoff is a *planned* resume, so it beats crash recovery: it captures the
soft context that phase boundaries have not persisted yet, then releases the
partition lock so ANY session — not only this checkout — can take over.

## Step 1 — Resolve the ticket

Resolve `<ticket-id>` in this order; first hit wins:

1. **Explicit argument** — `$ARGUMENTS` contains a ticket id (e.g. `SHOP-123`).
2. **Session context** — the ticket id appears in this conversation (a skill
   you were coordinating, a ticket just created or discussed).
3. **Pointer file** — `<workspace>/<repo-id>/sessions/<checkout-id>.json`,
   field `ticket_id` (see "Locating the workspace" below).
4. **Branch name** — `git rev-parse --abbrev-ref HEAD`, match
   `<ticket_prefix>-<number>` (e.g. `SHOP-123` in `feature/SHOP-123-cart`).

If none resolves, STOP and ask the user which ticket to hand off (suggest
`/acs:handoff SHOP-123` with an explicit id). Never guess.

### Locating the workspace

You need the partition path before flushing. Resolve it like the hooks do:

- **Settings** (per-key merge, most specific wins): read
  `<main-checkout>/.acs/settings.local.json`, then
  `<main-checkout>/.acs/settings.json`, then `~/.acs/settings.json`; take the
  first `workspace_path` (expand `~`) and `ticket_prefix` found. In a linked
  worktree also check the worktree's own `.acs/` files. No `workspace_path`
  anywhere means acs is not initialized — stop and tell the user to run
  `/acs:init` first.
- **repo-id**: from `git config --get remote.origin.url` take the last two
  path segments as `owner-name` (strip scheme, `user@`, trailing `.git`;
  replace `:` with `/`; sanitize any character outside `[A-Za-z0-9._-]` to
  `-`). Fallback: the main repo directory's basename, sanitized the same way.
- **checkout-id** (only needed for the pointer-file lookup):

```bash
python3 -c 'import hashlib,os,re,subprocess;r=subprocess.check_output(["git","rev-parse","--show-toplevel"],text=True).strip();print(re.sub(r"[^A-Za-z0-9._-]+","-",os.path.basename(r))+"-"+hashlib.sha1(os.path.abspath(r).encode()).hexdigest()[:8])'
```

The partition is `<workspace>/<repo-id>/<ticket-id>/`. If it does not exist
but `<workspace>/<repo-id>/archive/<ticket-id>/` does, the ticket is already
merged and archived — report that there is nothing to hand off and stop.

## Step 2 — Identify the in-flight skill

Find which hooked skill (if any) has a run in progress:

1. **Session context** — you usually know which skill this session was
   coordinating.
2. **Pointer file** — the `skill` field of
   `<workspace>/<repo-id>/sessions/<checkout-id>.json`.
3. **Scan** — check `<partition>/<skill>-state.json` for
   `runs[-1].status == "in_progress"`, in this order: `create-prd`,
   `create-architecture`, `create-project`, `create-ticket`, `create-design`,
   `create-spec`, `code`, `create-pr`, `merge-pr` (the same order
   `handoff.py` uses, so your flush lands where its finalization points).

If no skill is in flight, skip Step 3 (there is no in-flight phase to flush —
completed steps are already fully recorded in the workspace) and go straight
to Step 4.

## Step 3 — Flush soft context

Write `<partition>/phases/<current-skill>/handoff-context.md` (create the
directory if needed). Capture ONLY what the phase XMLs and state files have
NOT already persisted — the soft context that dies with this session:

- **user clarifications & decisions** made in conversation (and their why);
- **partial findings** of the in-flight phase (what the current
  plan/execute/verify pass has learned but not yet written out);
- **discovered gotchas** (flaky tests, surprising couplings, env quirks,
  approaches already tried and rejected);
- **next actions**, concrete and ordered.

Skeleton (keep it to a page or two; reference existing artifacts by path
instead of duplicating them):

```markdown
# Handoff context — SHOP-123 / code (iteration 2, execute in flight)

Written by /acs:handoff on 2026-06-12T09:30:00Z.

## Done (verified)
- specs/01-cart-model.md implemented; tests green (phases/code/iter-1-verify.xml)

## In flight
- specs/02-cart-api.md: tests written, handler half-implemented (src/cart/api.py)

## Next actions
1. Finish the PATCH handler in src/cart/api.py; re-run pytest tests/cart/
2. Coverage check against test_coverage_percent (90)

## User clarifications & decisions
- User chose cursor-based pagination over offset (perf on large carts)

## Partial findings (current phase)
- Existing serializer drops null quantities — workaround in tests, fix pending

## Gotchas
- tests/cart/test_api.py::test_empty is flaky under -n auto; run serially
```

## Step 4 — Record the handoff

Run the helper (this finalizes `runs[-1]` as `handed_off` with your summary,
updates `pipeline-state.json`, and releases the `.lock`):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/handoff.py" --ticket SHOP-123 \
  --summary "done: spec 01 implemented, tests green; in flight: spec 02 executor, handler partial; next: finish PATCH handler, coverage check; decisions: cursor pagination — detail in phases/code/handoff-context.md"
```

Summary rules: one compact line, well under 1 KB, covering the four parts —
**done / in flight / next / decisions** — and pointing at
`handoff-context.md` for detail. For a longer summary write it to a temp file
and pass `--summary-file <path>` instead; the deep detail still belongs in
`handoff-context.md`, not the summary. A summary is required even when
nothing is in flight.

On success it prints JSON:

```json
{
  "ok": true,
  "ticket_id": "SHOP-123",
  "skill": "code",
  "lock_released": true,
  "continue_with": "/acs:code SHOP-123"
}
```

If it exits non-zero, surface its stderr verbatim and stop. Known cases:

- `workspace_path is not configured` — tell the user to run `/acs:init`.
- `no current ticket for this checkout (nothing to hand off)` — ask the user
  for the ticket id and re-run `/acs:handoff SHOP-123`.
- `no active partition for <id>` — the ticket never started or is archived
  (done); nothing to hand off.

## Step 5 — Report

Tell the user, compactly:

1. **How to continue** — print the `continue_with` value VERBATIM as the
   command to run in the fresh session (e.g. `/acs:code SHOP-123`). The next
   coordinator will see `runs[-1].status == "handed_off"`, read the summary
   and `handoff-context.md`, run a light reconcile (recorded state trusted
   but cheaply verified, e.g. by re-running tests), and continue.
2. **What was flushed** — the path
   `<partition>/phases/<skill>/handoff-context.md` plus a one-line bullet per
   section actually captured (decisions, partial findings, gotchas, next
   actions).
3. **Lock released** — any session or worktree on this machine can now take
   the ticket over, not just this checkout.
4. **Scope** — the handoff targets a new session on the **same machine and
   workspace** (`workspace_path` is machine-local); cross-machine handoff is
   out of scope.

If `handoff.py` reported `"skill": null`, say explicitly that **nothing was
in progress — there is nothing to hand off**: every completed step is already
recorded in the workspace, no flush file was written, and the lock (if any)
was released. Still print the `continue_with` command verbatim (it will be
`/acs:ship SHOP-123`) so the user knows exactly how to pick the ticket up.

## Completion report (normative)

Every terminal outcome of a direct invocation — completed, failed,
interrupted, or handed off — ends your final message with the standard block
(INTERNALS.md "Completion report"), rendered only AFTER the post-hook
succeeded. Same labels, same order, `none` where empty:

```markdown
## /acs:handoff · <ticket-id> · <status>

- **Ticket**: <id> — <title> (<type>)
- **Status**: <status> — <stop_reason>
- **Results**: what was flushed to the partition (soft context, decisions, partial findings); run entry finalized `handed_off`; lock released
- **Findings**: <open findings / clarifications, or "none">
- **Artifacts**: <partition files, repo paths, branch, PR URL>
- **Metrics**: iterations <n>/3 · <wall time> · ~<tokens in/out> · ~$<cost_usd>
- **Next**: the exact `continue_with` command printed by `handoff.py`, e.g. `/acs:code SHOP-123` in a fresh session
```
