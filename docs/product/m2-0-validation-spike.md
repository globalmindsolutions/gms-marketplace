# M2-0 — Validation Spike Runbook

> Prerequisite for M2 (see [roadmap.md](roadmap.md#m2-0--validation-spike-prerequisite-1-session)).
> Run the published `acs` plugin end to end in a throwaway consumer repo and
> assert that real behavior matches the docs. **Done when:** a clean
> end-to-end run, or a logged defect list cut as a fast-follow **v0.1.2**
> (gates the dogfood epic E3, and seeds the E1 eval harness — E1 systematizes
> by machine what this spike checks by hand).

**Target build:** `acs` **v0.1.1** (`acs@gms-marketplace`). v0.1.0 is not
installable end to end — it fails to load with *"Duplicate hooks file
detected"*; v0.1.1 ([#7](https://github.com/globalmindsolutions/gms-marketplace/pull/7))
is the first build this spike can run against.

**Goals traced** (from [prd.md](prd.md#goals--success-metrics)): **G1** zero
gate escapes, **G2** resume from state only, **G6** clean install/onboarding.

## Prerequisites

- `git`, `python3` ≥ 3.9 (stdlib only — acs installs no Python packages).
- `gh` authenticated (`gh auth status`) — needed for `/acs:create-pr` and
  `/acs:merge-pr`.
- A scratch directory **outside** any existing repo for the workspace.

## How to run it

Steps **1, 3, 4, 5 are skill invocations** — they use `AskUserQuestion` and
spawn subagents, so they run in an **interactive Claude Code session opened
inside the scratch repo with acs installed**. Steps **0 and 2** and every
`ASSERT` are deterministic file/exit-code checks that can be driven from a
shell. Keep the scratch repo and the workspace dir around until the spike is
signed off, so the assertions can be re-inspected.

---

## Step 0 — Scratch repo + install

```bash
mkdir -p /tmp/acs-spike && cd /tmp/acs-spike
git init -q
# a minimal but real codebase so the brownfield path has something to read
printf 'def health():\n    return "ok"\n' > app.py
git add -A && git commit -qm "seed"

claude plugin marketplace add globalmindsolutions/gms-marketplace
claude plugin install acs@gms-marketplace
```

- ✅ **ASSERT (v0.1.1 regression):** install completes and the plugin loads
  with **no** `Hook load failed: Duplicate hooks file detected`. This is the
  exact failure v0.1.1 fixed. If it reappears, **stop** — the spike is blocked
  and v0.1.0→v0.1.1 did not take; log it and cut v0.1.2.
- ✅ `/acs:*` skills are listed/offered in a session opened in this repo.

## Step 1 — `/acs:init`

In a fresh session inside `/tmp/acs-spike`:

```text
/acs:init
  → scope            project
  → workspace_path   ~/acs-workspace        (must be outside the repo)
  → ticket_prefix    SPIKE
  → defaults otherwise (coverage 90, merge_strategy squash, tracker local)
```

- ✅ `<repo>/.acs/settings.json` written (project scope) with `ticket_prefix`
  and any non-default keys.
- ✅ `<repo>/.acs/settings.local.json` written, holds `workspace_path`, and the
  line `.acs/settings.local.json` is present in `<repo>/.gitignore`.
- ✅ `~/acs-workspace/` exists (created and write-probed).
- ✅ Final validation passes (init refuses to finish on invalid settings).

Validates: [init/SKILL.md](../../plugins/acs/skills/init/SKILL.md) steps 5–7,
G6.

## Step 2 — Gate proof (exit-2 blocks) — the G1 core

Before creating any ticket, try to jump the pipeline:

```text
/acs:code SPIKE-1
```

- ✅ The `PreToolUse` dispatcher exits 2 and **blocks the skill before any of
  its instructions run**; stderr names the missing predecessor, e.g.
  `no workspace partition for SPIKE-1 (expected …) — run /acs:create-ticket first.`
- ✅ With settings removed/absent, any skill reports
  `… Run /acs:init first.` instead.

Validates: [README.md "How gating works"](../../plugins/acs/README.md#how-gating-works),
gate messages in
[acs_lib.py](../../plugins/acs/hooks/scripts/acs_lib.py) (`GateError`), G1.

## Step 3 — `/acs:create-ticket`

```text
/acs:create-ticket Add a /health endpoint that returns "ok"
```

- ✅ Repo partition `<workspace>/<repo-id>/` now contains
  `tickets-index.json`, `counters.json`, `metrics.json`.
- ✅ Ticket partition `<repo-id>/SPIKE-1/` contains `ticket.json`,
  `pipeline-state.json`, and a `.lock`.
- ✅ The allocated id uses the configured prefix (`SPIKE-1`); `ticket.json`
  records its `type` (epic/story/task) and `needs_design`.
- ✅ Re-running `/acs:code SPIKE-1` now fails a *different* gate (e.g.
  `no specs found … run /acs:create-spec SPIKE-1 first.`) — the gate moved
  forward by exactly one step.

Validates: [README.md "Workspace layout"](../../plugins/acs/README.md#workspace-layout),
ticket schema, G1.

## Step 4 — `/acs:ship SPIKE-1`

```text
/acs:ship SPIKE-1
```

- ✅ Drives create-ticket → (create-design when `needs_design`) → create-spec
  → code → create-pr, and **stops before merge** (never merges for you).
- ✅ `pipeline-state.json` advances step by step; each step's `post-<skill>.py`
  flips its run to `completed` (a skipped post-hook leaves the gate closed).
- ✅ A PR is opened against the default branch, title `[SPIKE-1] …`, branch
  matching `{type}/SPIKE-1-{slug}`, carrying the `ACS` label.
- ✅ **Resume check (G2):** interrupt mid-pipeline (end the session), then
  re-run `/acs:ship SPIKE-1` in a fresh session — it resumes from the first
  incomplete step using workspace state only, with no reliance on prior
  conversation.

Validates: [usage.md "umbrella mode"](../requirements/usage.md#ship-a-feature--umbrella-mode),
[README.md skills table](../../plugins/acs/README.md#the-12-skills), G1, G2.

## Step 5 — `/acs:merge-pr SPIKE-1`

After a human glance at the PR:

```text
/acs:merge-pr SPIKE-1
```

- ✅ Readiness check (CI/approvals/conflicts/protections) → squash merge →
  branch deleted → ticket marked `done` → partition moved to
  `<repo-id>/archive/SPIKE-1/`.
- ✅ `tickets-index.json` shows `SPIKE-1` as done; `metrics.json` reflects the
  run's tokens/cost.

Validates: [usage.md merge flow](../requirements/usage.md#ship-a-feature--umbrella-mode),
[README.md skills table](../../plugins/acs/README.md#the-12-skills).

## Outcome

Record one of two outcomes against this runbook:

- **Clean run** — every `ASSERT` passed. M2-0 is green; unblocks **E3
  (dogfood)** and gives **E1** its hand-checked baseline. Note the measured
  G1/G2/G6 observations for the PRD metrics table.
- **Defect list** — one or more `ASSERT`s failed. Log each below, cut the
  fixes as **v0.1.2** (bump `plugin.json` + `marketplace.json` + CHANGELOG,
  same release flow as v0.1.1), and re-run the spike against v0.1.2.

### Defect log

| # | Step | Expected (per docs) | Observed | Severity | Fix / ticket |
|---|------|---------------------|----------|----------|--------------|
|   |      |                     |          |          |              |

## Cleanup

```bash
claude plugin uninstall acs@gms-marketplace
rm -rf /tmp/acs-spike ~/acs-workspace
```
