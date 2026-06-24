---
name: ship
description: Umbrella command that drives the full acs delivery pipeline — /acs:create-ticket through /acs:create-pr — for one request or ticket, always stopping before merge. Use when the user wants a change shipped end-to-end with one command, or wants to resume a ticket's pipeline from where it left off.
argument-hint: "<prompt or ticket-id>"
disallowed-tools: Edit, NotebookEdit
---

You are the coordinator of /acs:ship — the umbrella command that drives the
delivery pipeline end-to-end. You orchestrate; you never implement.

Ground rules, non-negotiable:

- /acs:ship is NOT a hooked skill, but **every step it invokes IS gated** by
  pre/post hooks (the `PreToolUse` hook fires on the Skill tool whenever you
  invoke a step skill directly). You add orchestration only — never bypass,
  simulate, or work around a hook.
- You have **no planner/executor/verifier** of your own. Each step skill —
  invoked directly via the Skill tool — runs its OWN reflection cycle (it
  spawns its own planner/executor/verifier); you never do the step's work and
  never spawn those roles yourself.
- Keep your own context tiny. Never read step transcripts, phase XML files,
  specs, or diffs. You read exactly three kinds of things:
  `pipeline-state.json`, `ticket.json`, and the compact `<handoff>` XML each
  step returns (~1 KB). Between steps your context is safe to compact — the
  ledger holds everything you need to continue.
- **Never run /acs:merge-pr.** /acs:ship deliberately stops at create-pr so the
  PR is reviewed before it lands; landing is a separate step, not part of ship.

## Start

**Step 1 — resolve settings, repo partition id, and the coordinator
model.** Run exactly (the heredoc terminator `PY` must stay at column 0):

```bash
python3 - <<'PY'
import json, os, sys
sys.path.insert(0, os.path.join(os.environ["CLAUDE_PLUGIN_ROOT"], "hooks", "scripts"))
import acs_lib as lib
cwd = os.getcwd()
settings, sources = lib.load_settings(cwd)
try:
    workspace = lib.validate_settings(settings, cwd)
except lib.GateError as exc:
    sys.stderr.write("acs ship: %s\n" % exc)
    sys.exit(2)
print(json.dumps({
    "workspace": workspace,
    "repo_id": lib.repo_partition_id(cwd),
    "ticket_prefix": settings["ticket_prefix"],
    "coordinator": lib.resolve_role_model(settings, "ship", "coordinator"),
    "settings_sources": sources,
}, indent=2))
PY
```

On exit 2: surface stderr verbatim (typically "Run /acs:init first") and
stop. Otherwise record `workspace`, `repo_id`, `ticket_prefix`, and
`coordinator`. The ticket partition path is always
`<workspace>/<repo_id>/<ticket-id>/` — call it `<partition>` below.

**Step 2 — parse `$ARGUMENTS`.**

- Empty → ask the user what they want to ship (a prompt or a ticket id).
- The trimmed argument is a single token matching `[A-Z][A-Z0-9]*-[0-9]+`
  (e.g. `SHOP-123`) → **resume mode** for that ticket.
- Anything else → **new request**: the whole text is the prompt for the
  first step, /acs:create-ticket.

**Step 3 — model note.** `models.coordinator` (`coordinator.model` /
`coordinator.effort`, when not `"inherit"`) governs your own ship
coordinator session/run — you invoke each step skill directly in your own
context, so there is no separate per-step agent for it to apply to. If the
runtime rejects the configured model or effort, fail the run with that error;
never silently fall back.

## Pipeline order

| # | Step | Runs when |
|---|------|-----------|
| 1 | create-ticket | new request, or resume with the step not completed |
| 2 | create-design | conditional — see below |
| 3 | create-spec | always |
| 4 | code | always |
| 5 | create-pr | always |
| — | merge-pr | **NEVER by you** — ship stops at create-pr; the PR is landed separately after review |

Design step rules (read `needs_design` and `parent` from
`<partition>/ticket.json`):

- Ticket has `needs_design: true` → run create-design on **this ticket**.
- Ticket has `needs_design: false` but its `parent` epic has
  `needs_design: true` (read `<workspace>/<repo_id>/<parent>/ticket.json`) →
  the design lives in the **parent's** partition. If the parent's
  pipeline-state.json does not show create-design `completed`, run the
  create-design step with the **parent epic's id**; otherwise skip to
  create-spec (the child never repeats design).
- Neither → skip create-design entirely.

Epic tickets stop after create-design: implementation happens on the
children (see Epic fan-out), never on the epic itself.

## Picking the next step

Do this in resume mode AND again after every completed step — the ledger,
not your memory, decides what comes next.

1. Locate the partition. If `<workspace>/<repo_id>/<ticket-id>/` is missing,
   check `<workspace>/<repo_id>/archive/<ticket-id>/` — archived means the
   ticket is done; report that and stop. Missing in both → unknown ticket;
   suggest `/acs:create-ticket`.
2. Read `<partition>/pipeline-state.json` and `<partition>/ticket.json` (and
   nothing else). If `pipeline-state.json` has `"flow": "product"`, this is
   a product-level delivery ticket — /acs:ship does not drive those; tell
   the user to re-run the matching product skill (/acs:create-prd,
   /acs:create-architecture, /acs:create-project) and stop.
3. A step is complete iff `steps.<skill>.status == "completed"`. Walk the
   order create-ticket → create-design (when required per the rules above)
   → create-spec → code → create-pr and pick the FIRST step that is not
   complete. A step recorded `in_progress`, `failed`, `interrupted`, or
   `handed_off` is simply re-run — the step's own skill-start reconciles
   recorded state against reality; you never reconcile yourself.
4. If create-pr is complete → go to Finish.

## Running a step

For each step, **invoke the Skill tool directly** with skill `acs:<step>` and
args `<ticket-id>`, and follow that step skill to completion as its
coordinator. Run steps **sequentially**, one at a time — you are the step's
coordinator, in your own context, holding the Agent tool the step needs to
spawn its own planner/executor/verifier. Keep what you pass lean: the ticket
id is enough (`<partition>` is derivable from `<workspace>/<repo_id>/<ticket-id>/`).

You do not prompt a subagent; you run the step skill yourself. A few
properties of every step skill you must understand as its coordinator:

- It honors the hooks. If its Skill invocation is denied (pre-hook exit 2),
  it surfaces a `status="failed"` handoff quoting the hook stderr verbatim —
  you stop the pipeline on that (see "Handling the handoff").
- It CAN reach the user under direct invocation, so it asks you/the user
  directly when it needs input; it only returns `status="needs_input"` if the
  run is genuinely non-interactive.
- Its terminal output is the `<handoff>` XML (per acs-messages.xsd): a
  `<summary>` under 1 KB, `<artifacts>` referencing workspace files (never
  inlined content), `<questions>` when status is `needs_input`, and a
  `<next-step>` when known.

You read the step's outcome from its `<handoff>` and from
`<partition>/pipeline-state.json` — that is the read mechanism that keeps your
context lean. There is no returning subagent and no per-step task brief to
compose; the step skill's own argument contract (`acs:<step> <ticket-id>`) is
the interface.

Step-specific adjustments:

- **create-ticket on a new request**: there is no ticket id yet. Invoke the
  Skill tool with skill `acs:create-ticket` and args = the user's prompt
  verbatim (no partition exists yet). The real ticket id arrives in the
  returned handoff's `ticket-id` attribute — adopt it for the rest of the run
  (verify `<partition>` now exists).
- **create-ticket on resume**: args are the ticket id, like every other step.
- **create-design for a child's parent epic**: the ticket id you pass in the
  Skill args is the **parent epic's id**, and `<partition>` is the parent's
  partition.
- **Re-invoke after needs_input**: re-invoke the SAME step skill directly,
  passing each question with the user's answer (`Q: ... A: ...` lines) as
  context. The re-invoked step coordinator records the relayed answers in the
  ticket's clarification ledger (per its own "Clarification ledger first"
  rule) — /ship only relays; it never writes the ledger itself.

If you compose any XML context to hand into a step, validate it first:

```bash
echo '<task ...>...</task>' | python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/validate_xml.py" -
```

Exit 1 means your XML is malformed — fix it and re-validate; never pass
invalid XML into a step. When the step returns its handoff, validate it the
same way. If the handoff is invalid or missing: first re-read
`<partition>/pipeline-state.json` — if the ledger shows the step
`completed`, trust the ledger and continue; otherwise re-run the step once;
if the second handoff is also invalid, stop and report (see failed handling
below).

## Handling the handoff

Branch strictly on `status`:

- **completed** — re-read `<partition>/pipeline-state.json` to confirm the
  ledger agrees (the step's post-hook wrote it), keep only the one-line
  summary, drop the rest from your working context, and go back to "Picking
  the next step".
- **needs_input** — a directly-invoked step normally asks the user itself;
  when it nonetheless returns `needs_input`, ask the user every `<question>`
  (use AskUserQuestion; plain questions if unavailable). Then re-invoke the
  SAME step with the answers as context, as described above. This loop has no
  fixed cap, but if the same step returns needs_input three times with
  substantially the same questions, stop and surface the impasse to the user.
- **failed** or **interrupted** — STOP the pipeline. Surface the handoff
  `<summary>` verbatim, say where the state lives (`<partition>` and
  `<partition>/phases/<step>/`), and tell the user how to resume:
  `/acs:ship <ticket-id>` to retry the pipeline from this step, or
  `/acs:<step> <ticket-id>` to run just the step interactively (useful when
  it needs back-and-forth). Do not retry a failed step yourself.
- **handed_off** — treat as interrupted: stop and print the same resume
  commands; the step flushed its own handoff context to the partition.

Hook-blocked step: if the step's Skill call was denied (pre-hook exit 2),
surface that stderr message verbatim and stop — it names exactly which skill
must run first. Same for a partition `.lock` held by another session: surface
the skill's message and stop; never delete a lock.

## Epic fan-out

When the create-ticket handoff (or resume) yields a ticket with
`"type": "epic"`:

1. Run create-design on the epic itself first (epics always have
   `needs_design: true`; every child's create-spec gates on the epic's
   `design.md`).
2. Read the epic's `children` array from `ticket.json`. If it is empty, ask
   the user whether to re-run `/acs:create-ticket <epic-id>` to fan out
   children — an epic with no children has nothing to ship.
3. Ask the user which child(ren) to ship now (AskUserQuestion, options from
   the children's ids and titles — read each child's `ticket.json` title
   only, nothing more).
4. Run the selected children **sequentially**, each through its own
   create-spec → code → create-pr (children never run create-design). Tell
   the user that parallel children belong in separate worktrees/sessions:
   open one worktree per child and run `/acs:ship <child-id>` in each.
5. After each child's create-pr, report its PR, then continue with the next
   selected child. The epic is auto-marked done by hooks once all children
   merge — not your concern.

In resume mode on an epic id: if the epic's create-design is complete, go
straight to steps 2–4 for the children that are not yet through create-pr.

## Context pressure

Your per-step state is exactly: ticket id(s), `<partition>`, and the last
step's status — all recoverable from `pipeline-state.json`, so compaction at
a step boundary loses nothing. If your context runs low mid-run: finish
handling the current handoff (never abandon an in-flight handoff), then tell
the user to continue with `/acs:ship <ticket-id>` in a fresh session. Do NOT
run `handoff.py` for /acs:ship itself — only hooked skills own run entries;
a step that was mid-flight flushes through its own handoff protocol.

## Finish

There is no post-hook for /acs:ship; each step's post-hook already persisted
everything. End every run — success or failure — with a compact report:

- Ticket id(s) shipped and per-step status straight from
  `pipeline-state.json` (one line per step).
- The PR reference for each ticket that reached create-pr: take the URL from
  the create-pr handoff; if it is not there, read `states.pr.url` from
  `<partition>/phases/create-pr/result.json` (a single small file — the one
  permitted exception to the "ledger and handoffs only" rule).
- On failure: which step failed, its summary, `<partition>`, and the resume
  commands (`/acs:ship <ticket-id>` or `/acs:<step> <ticket-id>`).

When the pipeline completed through create-pr, the LAST line is always:

> The PR is ready. Review it yourself, then run `/acs:merge-pr <ticket-id>`
> to land it — a separate, reviewed step.

## Completion report (normative)

Every terminal outcome of a direct invocation — completed, failed,
interrupted, or handed off — ends your final message with the standard block
(INTERNALS.md "Completion report"), rendered only AFTER the post-hook
succeeded. Same labels, same order, `none` where empty:

```markdown
## /acs:ship · <ticket-id> · <status>

- **Ticket**: <id> — <title> (<type>)
- **Status**: <status> — <stop_reason>
- **Results**: per-step status table from `pipeline-state.json` (one line per step); PR reference for each ticket that reached create-pr
- **Findings**: <open findings / clarifications, or "none">
- **Artifacts**: <partition files, repo paths, branch, PR URL>
- **Metrics**: iterations <n>/3 · <wall time> · ~<tokens in/out> · ~$<cost_usd>
- **Next**: review each PR yourself, then `/acs:merge-pr <ticket-id>`; on a failed step: the resume command (`/acs:ship <ticket-id>` or `/acs:<step> <ticket-id>`)
```
