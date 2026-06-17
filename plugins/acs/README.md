# acs — Autonomous Coding Skills

`acs` is a Claude Code plugin that turns a raw request into merged code
through a complete, agentic software-delivery workflow: product definition
(PRD), architecture, ticketing, design (when the change warrants it),
implementation specs, TDD implementation with an automatic review loop, pull
request, and merge. Every workflow skill runs a plan → execute → verify
reflection cycle with dedicated subagents, pre/post hooks gate each step on
the recorded state of its predecessor, and all durable state lives in a
workspace folder *outside* your repo — so runs are resumable, tickets can
ship in parallel across git worktrees, and the coordinator never depends on
conversation history between steps.

## Requirements

On the machine running Claude Code, inside the consumer repo:

| Tool | Required | Used for |
|------|----------|----------|
| `git` | Yes | Branches, worktrees, repo identity |
| `python3` 3.9+ | Yes | All hooks and helper CLIs (stdlib only — no pip installs) |
| `gh` (authenticated) | Yes | Pull requests; ticket sync when `tracker.provider` is `github` |
| `acli` (authenticated) | Only with `tracker.provider: "jira"` | Jira ticket sync |
| `xmllint` | Optional | Full XSD validation of agent messages (structural fallback otherwise) |

## Install

From the `gms-marketplace` marketplace (this repository):

```text
claude plugin marketplace add globalmindsolution/gms-marketplace
claude plugin install acs@gms-marketplace
```

Or through the UI: run `/plugin` inside a Claude Code session, add the
marketplace `globalmindsolution/gms-marketplace`, then install `acs` from it.

## Quick start

One-time setup in any repo (the workspace path must be outside the repo):

```text
cd acme-shop
/acs:init
  → scope?            project            (.acs/settings.json + gitignored .acs/settings.local.json)
  → workspace_path?   ~/acs-workspace    (must be outside the repo)
  → ticket_prefix?    SHOP               (suggested from the repo name)
  → coverage 90, merge_strategy squash, tracker local  (defaults, editable)
```

Onboard an existing product (brownfield) — baseline the PRD and the
architecture doc set, each delivered as a reviewable docs PR:

```text
/acs:create-prd            # reverse-engineers a baseline PRD from code + docs
                           # → delivery ticket SHOP-1, docs PR
/acs:merge-pr SHOP-1       # after you review the PR yourself

/acs:create-architecture   # reverse-engineers HLD (C4 1–3, data model,
                           #   deployment) + LLD key flows, all Mermaid
                           # → delivery ticket SHOP-2, docs PR
/acs:merge-pr SHOP-2
```

(Greenfield is the same, except both skills *elicit* instead of
reverse-engineer, and one extra `/acs:create-project` run scaffolds the repo
skeleton — build, test harness, coverage tooling, lint, CI, a green vertical
slice.)

Then ship features:

```text
/acs:ship Add wishlist support so customers can save products for later
```

`/acs:ship` runs `/acs:create-ticket` → `/acs:create-design` (when the
ticket needs design) → `/acs:create-spec` → `/acs:code` → `/acs:create-pr`,
asking clarifying questions along the way — and always stops before merge.
After reviewing each PR yourself:

```text
/acs:merge-pr SHOP-5       # readiness check → squash merge → delete branch →
                           #   ticket done (+ tracker sync) → partition archived
```

Every step is also invocable on its own (`/acs:create-ticket Fix flaky
checkout rounding`, then `/acs:create-spec SHOP-7`, `/acs:code SHOP-7`, …) —
the hooks enforce the order either way. The ticket id argument is optional
when context is unambiguous: explicit argument → session context → branch
name.

## The 15 skills

| Skill | Gated by | What it does |
|-------|----------|--------------|
| `/acs:init` | — (bootstrap) | Generates `.acs/settings.json` (user or project scope): workspace path, ticket prefix, coverage target, formats, tracker. Opt-in (default-on) writes a pipeline-default `CLAUDE.md` managed block so sessions ship via `/acs:ship`, not raw `gh pr create`. Re-runs update in place. |
| `/acs:ship` | Each step's own gate | Umbrella: drives create-ticket → design → spec → code → create-pr end to end, resumable from the first incomplete step. Never merges. |
| `/acs:handoff` | — (utility) | Flushes in-flight work and decisions to the ticket partition, marks the run `handed_off`, releases the lock, prints the command to continue in a fresh session. |
| `/acs:update` | — (utility, user-invoked only) | Upgrade assistant: installed-vs-latest version check, CHANGELOG delta with breaking-change callouts, marketplace refresh, post-update migration checks (settings, status-line paths). Reloading stays your action. |
| `/acs:install-hooks` | — (utility, user-invoked only) | Installs this clone's local convention hooks (`commit-msg` + `pre-push`) that enforce the configured `formats.*` before push — the `pre-commit install` equivalent for acs. Per-clone; each teammate runs it once. |
| `/acs:metrics` | — (utility) | Read-only in-session dashboard: renders six panels (throughput, pipeline funnel, cost/time per ticket, coverage vs target, review iterations, token burn by role) for the current repo from workspace state. Writes nothing. |
| `/acs:create-prd` | `/acs:init` done | Product-level: elicits (greenfield) or reverse-engineers (brownfield) the PRD doc set at `prd_path`; docs PR via its own delivery ticket. |
| `/acs:create-architecture` | PRD doc set exists | Product-level: HLD (C4 levels 1–3, data model, deployment, tech stack) + LLD (sequence-diagram flows, contracts) at `architecture_path`, all Mermaid; docs PR. |
| `/acs:create-project` | Architecture doc set exists | Product-level, greenfield-only: scaffolds layout, build, test framework + coverage tooling, lint, CI, and a minimal green vertical slice; bootstrap PR. |
| `/acs:create-ticket` | Settings exist | Turns a prompt (or an imported remote key) into a typed ticket (epic/story/task) with PRD tracing, `needs_design` flag, optional Jira/GitHub Projects sync. |
| `/acs:create-design` | `/acs:create-ticket` completed; ticket has `needs_design: true` | Weighs options with you and writes `design.md` (decision, architecture, NFRs, risks) in the ticket partition; epics' children inherit it. |
| `/acs:create-spec` | `/acs:create-ticket` completed; design completed when required | Decomposes the ticket into one or more implementation specs (scope, approach, API/data changes, test plan), conformant to the design. |
| `/acs:code` | `/acs:create-spec` completed; specs exist | TDD implementation on a ticket branch against the coverage target; updates affected docs and the architecture doc set; verifier review loop (max 3 iterations). |
| `/acs:create-pr` | `/acs:code` completed **and** its verifier passed | Pushes the ticket branch and opens the PR (configured title/description formats, `ACS` label) against the default branch. |
| `/acs:merge-pr` | PR reference recorded; **user-invoked only** | Readiness check (CI, approvals, conflicts, protections), merge per `merge_strategy`, delete branch, mark ticket done, archive the partition. Also `/acs:merge-pr --pr <n>` (or `#n` / PR URL) to land a legitimate non-ticket **`acs-exempt`** PR — same readiness + cleanup, no ticket/partition/tracker. |

## How gating works

- **Pre-hooks are deterministic.** A `PreToolUse` hook on the `Skill` tool
  (`dispatch.py pre`) routes every `acs` skill invocation to its
  `pre-<skill>.py`. Exit 2 blocks the skill before any of its instructions
  run; stderr tells you exactly what is missing and which skill to run
  first. This fires for typed slash commands and model-initiated calls
  alike, including the step skills `/acs:ship` invokes directly.
- **Post-hooks close the loop without trusting the model.** Each skill's
  coordinator must call `post-<skill>.py --result-file …` as its mandatory
  final step; that is the only thing that flips the run to `completed`.
  Skill start has already recorded an `in_progress` run entry, and every
  downstream gate checks `runs[-1].status == "completed"` — so a skipped
  post-hook leaves the gate closed, never open.
- **A `SessionEnd` safety net** (`dispatch.py session-end`) finalizes any
  run this checkout left `in_progress` as `interrupted` and releases its
  lock, so abnormal endings still write state.

## Workspace layout

Everything durable lives under `workspace_path`, partitioned per repo and
per ticket:

```text
<workspace>/<repo-id>/                  # repo-id from git remote: owner-name
  tickets-index.json  counters.json  metrics.json
  sessions/<checkout-id>.json           # per-worktree current-ticket pointer
  archive/<ticket-id>/                  # moved here by post-merge-pr
  <ticket-id>/
    .lock  ticket.json  pipeline-state.json
    design.md  specs/NN-slug.md
    phases/<skill>/iter-<n>-<phase>.xml  phases/<skill>/result.json
    <skill>-state.json ...
```

Inspect progress and spend anytime: `tickets-index.json` for status across
tickets, `metrics.json` for per-repo totals, a ticket's
`pipeline-state.json` for where it stands in the pipeline.

## Configuration

Generated by `/acs:init`; resolved per key as `settings.local.json` →
project `settings.json` → `~/.acs/settings.json`. The most-used keys:

| Key | Default | Purpose |
|-----|---------|---------|
| `workspace_path` | — (required at init) | State folder, outside the repo; lives in gitignored `settings.local.json` |
| `ticket_prefix` | — (required at init) | Per-repo ticket id prefix (`SHOP` → `SHOP-123`) |
| `test_coverage_percent` | `90` | `/acs:code` TDD coverage target (hard fail if missed) |
| `merge_strategy` | `"squash"` | `/acs:merge-pr`: `squash` \| `merge` \| `rebase` |
| `prd_path` | `"docs/product"` | PRD doc set location in the repo |
| `architecture_path` | `"docs/architecture"` | HLD/LLD doc set location in the repo |
| `adr_path` | unset | When set, `/acs:code` commits accepted decision records here |
| `models` | inherit | Per-role model + reasoning effort (`planner`/`executor`/`verifier`, per-skill overrides) |
| `tracker` | `{ "provider": "local" }` | Ticket backend: `local`, `github` (Projects v2), or `jira` |
| `formats` | built-ins | Branch/commit/PR/ticket formats (`branch_name` must embed `{ticket_id}`) |

Full reference: [docs/requirements/configuration.md](../../docs/requirements/configuration.md)
(all keys, placeholder vocabulary, description templates, tracker mapping)
and the machine-readable
[schemas/settings.schema.json](schemas/settings.schema.json).

## Troubleshooting

- **"blocked — … has not completed" (skill refuses to run).** A pre-hook
  exited 2. The stderr message names the missing predecessor — run that
  skill for the same ticket (e.g. `/acs:create-spec SHOP-123` before
  `/acs:code SHOP-123`). A "run /init first" message means no
  `settings.json` could be resolved: run `/acs:init`.
- **"another session holds the lock."** Each ticket partition has a `.lock`
  owned by one session. If the other session is live (e.g. a parallel
  worktree), finish or hand off there. If it crashed, ending that session
  normally releases the lock via the `SessionEnd` hook; after a hard kill
  the lock is stale — verify the owning process is gone, then delete
  `<workspace>/<repo>/<ticket-id>/.lock` and re-run the skill.
- **Crash or interruption mid-skill.** The run entry stays `in_progress`
  (or is finalized `interrupted`); downstream gates simply read "not
  completed". Re-run the same skill (or `/acs:ship <ticket-id>`) — the
  coordinator sees the unfinished run and *reconciles* recorded state
  against reality (e.g. re-runs tests for specs marked implemented) before
  continuing. Phase artifacts under `phases/<skill>/` mean at most the
  in-flight phase is lost.
- **Corrupt or missing state files.** Treated as *not completed* — the gate
  stays closed rather than letting a half-recorded step pass. Re-run the
  predecessor skill for that ticket to regenerate its state.
- **Long session running out of context.** Run `/acs:handoff`: it flushes
  in-flight work and decisions to the ticket partition, releases the lock,
  and prints the exact command (e.g. `/acs:code SHOP-123`) to continue in a
  fresh session.

## For contributors

The binding implementation contract — skill lifecycle, helper CLIs
(`skill-start.py`, `new-ticket.py`, `handoff.py`, `validate_xml.py`),
result-document shape, canonical `states` keys, XML messaging rules, and
subagent conventions — lives in [docs/INTERNALS.md](docs/INTERNALS.md). The
business requirements live in the repo's
[docs/](../../docs/README.md) folder.
