---
name: init
description: Initialize or update the acs configuration for the current repo — settings scope, workspace path, ticket prefix, coverage target, merge strategy, tracker, doc paths, formats, subagent models, and optional CI enforcement of PR/branch/commit conventions. Use when setting up acs on a new repo, when another acs skill fails with "run /acs:init first", when the user wants to enforce acs conventions in CI or stop the pipeline being bypassed, or when changing any acs setting.
---

You are the coordinator of `/acs:init`, the acs bootstrap skill. This is NOT a
hooked pipeline skill: no `skill-start.py`, no pre/post hooks, no subagents, no
reflection loop. You do everything yourself in this session with Bash, Read,
Write, Edit, and AskUserQuestion. Every other acs skill's pre-hook fails with
"run /acs:init first" until this skill has produced a valid configuration.

Settings live in JSON files that MUST conform to
`${CLAUDE_PLUGIN_ROOT}/schemas/settings.schema.json` — read that schema if you
are unsure about any key's exact shape. Unknown keys in existing files are
legal (forward compatibility): never drop them.

## Step 0 — Preflight

Confirm you are inside a git repo and resolve the roots:

```bash
python3 - "${CLAUDE_PLUGIN_ROOT}/hooks/scripts" <<'PY'
import os, sys
sys.path.insert(0, sys.argv[1])
import acs_lib
cwd = os.getcwd()
print("checkout_root:", acs_lib.checkout_root(cwd))
print("main_repo_root:", acs_lib.main_repo_root(cwd))
print("repo_id:", acs_lib.repo_partition_id(cwd))
PY
```

If `checkout_root` is empty, stop: tell the user `/acs:init` must run inside
the consumer repo. Use `main_repo_root` (the main checkout, even from a linked
worktree) as `<repo>` everywhere below — local settings and `.gitignore`
belong to the main checkout so linked worktrees inherit them.

## Step 0b — Toolchain preflight (install what the full workflow needs)

Before configuring anything, make sure the machine has the tools the full acs
pipeline uses, so the user does not hit a missing `gh` or `pre-commit` mid-flow.
Print the status table (`check_toolchain` is the single source of truth — git,
python3, gh, pre-commit, xmllint, acli):

```bash
python3 - "${CLAUDE_PLUGIN_ROOT}/hooks/scripts" <<'PY'
import sys; sys.path.insert(0, sys.argv[1])
import acs_lib
for r in acs_lib.check_toolchain(acs_lib.load_settings(".")[0]):
    mark = "✓" if r["present"] else ("○" if r["kind"] == "optional" else "✗")
    print("%s %-11s %-11s %s" % (mark, r["name"], r["kind"], r["version"] or r["why"]))
print("MISSING:", ", ".join(acs_lib.missing_tools(acs_lib.load_settings(".")[0])) or "none")
PY
```

What the kinds mean and how to act:

- **required** (`git`, `python3`; plus `gh` when the github tracker is chosen,
  `acli` for jira) — the pipeline cannot run without these. `git`/`python3` are
  already present (this skill is running). If a required tool is missing, install
  it before continuing.
- **recommended** (`gh`, `pre-commit`) — a major capability degrades without
  them: no `gh` means `/acs:create-pr`, `/acs:merge-pr`, labels, and branch
  protection can't run; no `pre-commit` means the shared local convention hooks
  fall back to per-clone raw hooks.
- **optional** (`xmllint`) — graceful fallback exists (structural XML validation
  instead of full XSD); never block on it.

For every **required + recommended** tool in `MISSING`, offer to install it now
(never install silently). Detect the platform and use the matching command from
each tool's `install` map — `uname -s` is `Darwin` → use the `macos` command
(prefer Homebrew: check `command -v brew`); `Linux` with `apt-get` → the
`debian` command; otherwise show the `any`/URL hint. Examples:
`brew install gh`, `brew install pre-commit` (or `pipx install pre-commit`),
`sudo apt-get install -y libxml2-utils`. Ask once (AskUserQuestion or a compact
prompt) which missing tools to install; run the chosen commands and re-run the
table to confirm. If the user declines, continue — but record the gap and repeat
the install hint in the Step 8 summary so the workflow degradation is explicit.
Authentication (`gh auth login`, `acli auth login`) is handled per-tracker in
Step 4; this step only ensures the binaries exist.

## Step 1 — Detect existing settings (all three scopes)

Read each of these files if it exists (Read tool; missing file = fresh init):

1. `~/.acs/settings.json` — user scope
2. `<repo>/.acs/settings.json` — project scope, committed
3. `<repo>/.acs/settings.local.json` — machine scope, gitignored

If any exists, this is a RE-RUN: show the user the current resolved values
(per-key merge, most specific wins: local -> project -> user) and which file
each came from, then ask which keys to change. Update the existing files in
place — touch only the keys the user changes, preserve everything else
including keys you do not recognize. For nested objects (`tracker`, `formats`,
`models`) merge at the leaf level; never replace the whole object when only one
sub-key changed. Skip the questions below for keys the user does not want to
change.

## Step 2 — Choose scope

Ask with AskUserQuestion: where should the shared (non-machine-specific)
settings live?

- **Project** (recommended for team repos): `<repo>/.acs/settings.json`,
  committed and shared with the team.
- **User**: `~/.acs/settings.json`, personal defaults across all of this
  user's repos. Note in the question text: per-repo keys like `ticket_prefix`
  and `tracker` will then apply to every repo that has no project file —
  prefer project scope unless this is a single personal repo.

Regardless of the chosen scope, the machine-specific key `workspace_path`
ALWAYS goes to `<repo>/.acs/settings.local.json` (Step 5).

## Step 3 — Required inputs

### workspace_path (no default — must ask)

Ask for the workspace folder where acs stores all ticket state. Requirements
you must enforce before accepting an answer:

- Expand `~` (`os.path.expanduser`) and require an absolute path.
- It MUST be outside the consumer repo, including every worktree. Validate:

```bash
python3 - "<candidate-path>" <<'PY'
import os, subprocess, sys
ws = os.path.realpath(os.path.expanduser(sys.argv[1]))
if not os.path.isabs(os.path.expanduser(sys.argv[1])):
    sys.exit("REJECT: workspace_path must be an absolute path")
out = subprocess.run(["git", "worktree", "list", "--porcelain"],
                     capture_output=True, text=True).stdout
roots = [l.split(" ", 1)[1] for l in out.splitlines() if l.startswith("worktree ")]
for root in roots:
    root = os.path.realpath(root)
    try:
        if os.path.commonpath([ws, root]) == root:
            sys.exit("REJECT: %s is inside checkout %s" % (ws, root))
    except ValueError:
        pass  # different drive -> outside
print("OK:", ws)
PY
```

On `REJECT`, explain why (worktrees and parallel tickets need a shared store
outside the repo) and ask again. Never write a rejected path. Store the
expanded absolute path.

### ticket_prefix (no default — must ask, with a suggestion)

Suggest a prefix derived from the repo name: take the basename of the repo
(e.g. `acme-shop`), keep letters and digits, uppercase it, and prefer the most
product-like word (`acme-shop` -> suggest `SHOP`, fall back to `ACMESHOP`).
Validate the final answer against `^[A-Z][A-Z0-9]*$`; on failure explain the
rule (uppercase identifier starting with a letter, e.g. `SHOP` -> tickets
`SHOP-1`, `SHOP-2`, …) and re-ask. There is no global default — every repo
gets its own prefix; the sequence counter lives in the workspace.

## Step 4 — Optional settings (defaults shown, user may override)

Present these as a batch (AskUserQuestion or a compact list) with their
defaults; accept the defaults silently if the user says "defaults are fine".
The one exception is **`### models`** below: on a fresh init, present the
model-selection choice explicitly (it is a first-class setup decision, not a
silently-defaulted key) — see that subsection.

- `test_coverage_percent` — default `90`. Validate: a number in `(0, 100]`;
  reject and re-ask otherwise. Hard-fail target for the `/acs:code` TDD cycle.
- `merge_strategy` — default `"squash"`. One of `squash` | `merge` | `rebase`.
- `prd_path` — default `"docs/product"` (repo-relative).
- `architecture_path` — default `"docs/architecture"` (repo-relative).
- `requirements_path` — default `"docs/requirements"` (repo-relative). The
  living requirements: the standing behavioral contract, one file per feature
  area, accumulated ticket by ticket by /acs:code — no bootstrap needed; it
  grows from the first merged ticket.
- `adr_path` — default `"docs/adr"` (repo-relative): /acs:code commits the
  accepted decision records from each ticket's design.md there. Write the key
  only when the user changes it; explicit `null` disables (designs stay
  workspace-only).
- `e2e` — default UNSET (repo has no e2e suite). Detect candidates first
  (`package.json` scripts containing `e2e`, `playwright.config.*`,
  `cypress.config.*`, Makefile targets) and suggest what you find. When the
  user configures it, collect `e2e.command` (required), optional
  `e2e.setup`/`e2e.teardown` (environment bring-up/teardown), and
  `e2e.per_iteration` (default `false` — the code-verifier then runs the
  suite only on the final, otherwise-passing iteration; e2e is slow).
  Configured e2e makes the suite part of every /acs:code verification.

### tracker — default `{"provider": "local"}`

Ask which tracker: `local` (workspace only), `github` (GitHub Projects v2), or
`jira`. Tickets are always stored local-first; github/jira adds two-way sync.

For **github**, collect `tracker.github = {"owner": "<org-or-user>",
"project_number": <n>}` and then:

1. Check the CLI: `gh --version` and `gh auth status`. If missing or
   unauthenticated, give the fix (`brew install gh`, `gh auth login`) and ask
   whether to proceed anyway (sync stays broken until fixed) or pause.
2. Verify the project: `gh project view <project_number> --owner <owner>`.
3. Offer to ensure required fields exist:
   `gh project field-list <project_number> --owner <owner> --format json` —
   the project needs a `Status` field (built into Projects v2) and a `Type`
   single-select field with options `Epic`, `Story`, `Task`. If `Type` is
   missing and the user agrees, create it:
   `gh project field-create <project_number> --owner <owner> --name "Type" --data-type "SINGLE_SELECT" --single-select-options "Epic,Story,Task"`.

For **jira**, collect `tracker.jira = {"base_url": "<url>", "project_key":
"<KEY>"}` and check the CLI: `acli --version` and `acli auth status`. If
missing or unauthenticated, give the fix (`acli auth login`) and ask whether
to proceed anyway or pause. Never store credentials in settings — `gh` and
`acli` manage their own auth.

### formats — built-in defaults

Show the defaults and ask if the user wants changes:

| Field | Default | Allowed placeholders |
|-------|---------|----------------------|
| `branch_name` | `{type}/{ticket_id}-{slug}` | `{ticket_id}` (REQUIRED), `{type}`, `{slug}`, `{external_key}` |
| `commit_message` | `{ticket_id} {summary}` | `{ticket_id}`, `{type}`, `{summary}`, `{external_key}` |
| `pr_title` | `[{ticket_id}] {title}` | `{ticket_id}`, `{type}`, `{title}`, `{summary}`, `{external_key}` |
| `pr_description_template` | `pr-default` | template name/path, no placeholders |
| `tickets.epic.title` | `[EPIC] {title}` | `{ticket_id}`, `{type}`, `{title}`, `{external_key}` |
| `tickets.story.title` | `{title}` | same as epic title |
| `tickets.task.title` | `{title}` | same as epic title |
| `tickets.<type>.description_template` | `epic-default` / `story-default` / `task-default` | template name/path |

Validate every custom inline format against its column above: an unknown
placeholder is a hard validation error — REJECT and re-ask, never pass it
through (the pre-hooks would exit 2 on it later). `branch_name` MUST embed
`{ticket_id}`. Description templates resolve by built-in name (`pr-default`,
`epic-default`, `story-default`, `task-default`), then
`<repo>/.acs/templates/<name>.md`, then absolute path — if the user names a
custom one, check the file exists.

These same formats can be enforced in CI (branch name, PR title, PR
description, commit messages) — offered in Step 7c. If the user asks during
init to "enforce conventions" or "stop the pipeline being bypassed", that is
Step 7c.

### models — choose per-role models

**On a fresh init, ALWAYS ask this** (not only on request) — model choice is a
first-class setup decision. Present the choice with AskUserQuestion, offering:

1. **Recommended (default)** — `planner: opus`, `executor: sonnet`,
   `verifier: opus`, `coordinator: opus`: strong reasoning for planning/review,
   a faster/cheaper model for the mechanical execution role. Pick this and move
   on if unsure.
2. **Inherit the session model** — set nothing; every role runs on whatever
   model the user's Claude Code session is using (cheapest to reason about, no
   per-role split).
3. **Custom** — let the user set any of the four roles individually.

On a **re-run**, show the currently-resolved per-role models (and where each
came from) and ask only whether to change them — do not force a re-pick.

Shape per role (`planner`, `executor`, `verifier`, `coordinator`): a model
string (e.g. `"sonnet"`) or
`{"model": "...", "effort": "low|medium|high|xhigh|max|inherit"}`, plus
per-skill `models.overrides.<skill>.<role>`. Any non-empty model string is
accepted (so newer model names work without a skill update); resolution is per
field: override -> role -> inherit. Write the `models` object only when the user
picks Recommended or Custom; for Inherit, omit it entirely (inherit is the
schema default). If the user sets `models.coordinator`, tell them it governs the
`/acs:ship` coordinator's own session — under `/acs:ship` each step skill is
invoked directly in that session, so there is no separate per-step agent for the
key to apply to; a directly invoked skill runs in the user's session on the
session's model.

## Step 5 — Write the files

Split the collected keys:

- `<repo>/.acs/settings.local.json` — ALWAYS gets `workspace_path` (and only
  machine-specific keys), even when the user chose user scope.
- The chosen scope file (`<repo>/.acs/settings.json` or
  `~/.acs/settings.json`) — gets everything else the user set:
  `ticket_prefix`, `test_coverage_percent`, `merge_strategy`, `prd_path`,
  `architecture_path`, `adr_path` (only if set), `tracker`, `formats`,
  `models` (only if set).

Write each file with a read-update-write merge so a re-run preserves untouched
and unknown keys (adapt the inline dict to the keys collected this run; for
nested objects update sub-keys on the existing object instead of replacing it):

```bash
python3 - "<target-file>" <<'PY'
import json, os, sys
path = os.path.expanduser(sys.argv[1])
data = {}
if os.path.exists(path):
    with open(path) as f:
        data = json.load(f)
data["ticket_prefix"] = "SHOP"          # <- only the keys collected this run
data["test_coverage_percent"] = 90
os.makedirs(os.path.dirname(path), exist_ok=True)
with open(path, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
print("wrote", path)
PY
```

Then ensure the local file is gitignored. Run this ALWAYS — on a fresh init
AND on every re-run, even when no settings keys changed: a repo first
initialized by an older acs may already have `settings.local.json` but no
ignore rule, and this is the only step that retro-fixes it. Run from `<repo>`,
the main checkout root:

```bash
if ! git check-ignore -q .acs/settings.local.json 2>/dev/null; then
  # Guarantee a trailing newline first so the entry can't glue onto the last line.
  [ -f .gitignore ] && [ -n "$(tail -c1 .gitignore 2>/dev/null)" ] && printf '\n' >> .gitignore
  printf '.acs/settings.local.json\n' >> .gitignore
  echo "gitignored .acs/settings.local.json"
else
  echo ".acs/settings.local.json already ignored"
fi
```

Use `git check-ignore` (not a literal `grep`) so an existing broader rule like
`.acs/` already counts as ignored and no duplicate line is appended.

## Step 6 — Create and probe the workspace

```bash
mkdir -p "<workspace_path>" \
  && touch "<workspace_path>/.acs-write-probe" \
  && rm "<workspace_path>/.acs-write-probe" \
  && echo "workspace OK: <workspace_path>"
```

If this fails, report the exact error (permissions, read-only volume, bad
path) and ask for a different `workspace_path`, then redo Step 3's
outside-the-repo check and rewrite `settings.local.json`.

## Step 7 — Final validation

Run the exact validation every pre-hook will run, against the merged result of
all three scopes:

```bash
python3 - "${CLAUDE_PLUGIN_ROOT}/hooks/scripts" <<'PY'
import os, sys
sys.path.insert(0, sys.argv[1])
import acs_lib
cwd = os.getcwd()
settings, found = acs_lib.load_settings(cwd)
try:
    acs_lib.validate_settings(settings, cwd)
except acs_lib.GateError as e:
    sys.exit("INVALID: %s" % e)
print("settings valid; merged from:")
for p in found:
    print("  " + p)
PY
```

On `INVALID`, fix the offending key (re-ask the user if needed), rewrite, and
re-validate. Do NOT finish with invalid settings. The written files must also
conform to `${CLAUDE_PLUGIN_ROOT}/schemas/settings.schema.json`.

## Step 7b — Optional: acs status line (opt-in, never silent)

Offer the acs status line: a one-liner under the Claude Code prompt showing
the active ticket and live pipeline progress straight from workspace state,
e.g. `Opus 4.8 · SHOP-123 task · ✓ticket ✓spec ▶code ○pr ○merge · ~$0.85`.

`statusLine` is the USER's Claude Code setting — only write it with explicit
consent, and never overwrite an existing `statusLine` (if one is set, show
the manual snippet instead and move on). On yes, ask user vs project scope
and merge into `~/.claude/settings.json` or `<repo>/.claude/settings.json`
(preserve all other keys):

```json
{
  "statusLine": {
    "type": "command",
    "command": "python3 <resolved ${CLAUDE_PLUGIN_ROOT}>/hooks/scripts/statusline.py"
  }
}
```

In the same offer, include the **subagent status line** — live agent-panel
rows for the reflection subagents while they run
(`▶ verify · code-verifier · SHOP-123 · 45k tok · 1m32s`; rows for non-acs
agents keep Claude Code's default rendering). Same consent and scope rules,
key `subagentStatusLine`:

```json
{
  "subagentStatusLine": {
    "type": "command",
    "command": "python3 <resolved ${CLAUDE_PLUGIN_ROOT}>/hooks/scripts/subagent-statusline.py"
  }
}
```

The user may take either line, both, or neither — never overwrite an existing
`statusLine`/`subagentStatusLine` key.

Resolve `${CLAUDE_PLUGIN_ROOT}` to its absolute path when writing — user
settings do not expand plugin variables. Tell the user: if a plugin update
relocates the install, re-run /acs:init to refresh the path. Test each once:
`echo '{}' | python3 <path>/statusline.py` must print a line and exit 0;
`echo '{"tasks":[]}' | python3 <path>/subagent-statusline.py` must exit 0
silently.

## Step 7c — CI convention enforcement (opt-in, never silent)

Offer to enforce the acs conventions in the consumer repo's CI so a PR that
never went through `/acs:create-pr` is still held to the same branch name, PR
title, PR description, label, and commit-message conventions before it can
merge. Skip the whole step on a plain "no".

Be honest about what this is. The CI check is **necessary but not sufficient**:
branch name and PR title are observable conventions, but the proof that work
actually went through the pipeline (the ticket, specs, TDD) lives in the
workspace OUTSIDE the repo, which CI cannot see. So this makes the conventions
**mandatory to merge** (raising the floor), and the real gate is **a required
status check on a protected default branch**. Explain that before configuring
anything.

### Precondition — conventions must be committed

The check reads `ticket_prefix` + `formats` (+ `enforcement`) from the committed
`<repo>/.acs/settings.json`; the CI runner has no acs install. If the user chose
**user scope** in Step 2, those keys are in `~/.acs/settings.json` and CI will
not see them. When enabling enforcement, write `ticket_prefix`, `formats`, and
`enforcement` to the **project** file `<repo>/.acs/settings.json` regardless of
the chosen shared scope, and tell the user. Then confirm the file and the
checker dir are not gitignored (a broad `.acs/` ignore rule would hide them):

```bash
for p in .acs/settings.json .acs/ci/check-conventions.py; do
  git check-ignore -q "$p" && echo "WARNING: $p is gitignored — add '!.acs/' or narrow the rule, or CI cannot read it"
done || true
```

### Choose the checks and exemptions

Confirm (defaults shown — accept silently if the user says "defaults are fine"),
writing them under `enforcement` in the project settings file:

- `enforcement.checks` — `branch_name`, `pr_title`, `pr_description`, `acs_label`
  default **on**; `commit_message` defaults **off** (noisy under squash-merge,
  where only the PR title reaches `main`). Turn it on only if the user wants
  every PR-branch commit subject linted.
- `enforcement.exempt_branches` — default `["release/*", "dependabot/*",
  "renovate/*"]` (fnmatch globs that skip all checks — releases and bot PRs).
- `enforcement.exempt_label` — default `acs-exempt` (a PR carrying it skips all
  checks; the deliberate escape hatch for a one-off non-ticket PR).
- `enforcement.require_label` — default `ACS` (the label `/acs:create-pr`
  applies).
- `enforcement.pr_description_sections` — default the section headings of the
  configured `pr_description_template` (for `pr-default`: `Summary`, `Ticket`,
  `Changes`, `Test plan`). Only the `pr_description` check uses these.

### Install the workflow + checker (copy, don't hand-write)

Copy the shipped templates verbatim — they are stdlib-only and self-contained.
Run from `<repo>` (the main checkout root):

```bash
mkdir -p .acs/ci .github/workflows
for f in check-conventions.py commit-msg pre-push install-hooks.sh; do
  cp "${CLAUDE_PLUGIN_ROOT}/templates/ci/$f" ".acs/ci/$f"
done
cp "${CLAUDE_PLUGIN_ROOT}/templates/ci/acs-conventions.yml" .github/workflows/acs-conventions.yml
chmod +x .acs/ci/check-conventions.py .acs/ci/commit-msg .acs/ci/pre-push .acs/ci/install-hooks.sh
```

`.acs/ci/` carries the checker, the two hook scripts, and `install-hooks.sh` so a
teammate who only cloned the repo can install the local hooks without the acs
plugin.

These are regenerated on every re-run, so changing a format later and re-running
`/acs:init` refreshes them. Stage `.acs/settings.json`, `.acs/ci/`, and
`.github/workflows/acs-conventions.yml` for the user to commit (do not commit
yourself unless asked).

### Ensure the labels exist (tracker = github, or any GitHub remote)

Best-effort; harmless if they already exist:

```bash
gh label create ACS        --description "Created/validated by the acs pipeline" 2>/dev/null || true
gh label create acs-exempt --description "Skip acs convention checks for this PR" 2>/dev/null || true
```

### Optional — local hooks: enforce conventions before push (config-driven)

Offer git hooks that enforce the conventions **locally**, before anything
reaches GitHub. They run the SAME `check-conventions.py` against the SAME
committed `formats.*` / `enforcement.*` the user just configured — so a custom
`commit_message` or `branch_name` format is honoured identically on the laptop
and in CI. PR title and PR description only exist once a PR is open, so the
local hooks check what is knowable locally:

- **`commit-msg`** (`--mode commit-msg`) — validates the commit subject against
  `formats.commit_message` the instant it is written (earliest catch).
- **`pre-push`** (`--mode pre-push`) — validates `formats.branch_name` plus
  every commit subject in the push range, the last gate before code leaves the
  machine.

Both honour the `enforcement.checks.*` toggles and the exempt label/branches,
and both are `--no-verify`-bypassable per-clone — CI is still the backstop. The
acs pipeline (`/acs:code`, `/acs:create-pr`) already generates branch, commits,
PR title, and PR body from these formats+templates, so these hooks only bite on
work done by hand outside the pipeline.

**Preferred — pre-commit framework (tracked, shared with the team).** If the
repo uses pre-commit (`.pre-commit-config.yaml` present, or the user agrees to
add it), add these entries under `repos:` and install both stages with
`pre-commit install --hook-type commit-msg --hook-type pre-push`. Tracked in the
repo, so every teammate gets them after `pre-commit install` — not per-clone
copying:

```yaml
  - repo: local
    hooks:
      - id: acs-commit-msg
        name: acs commit message convention
        entry: python3 .acs/ci/check-conventions.py --mode commit-msg --message-file
        language: system
        stages: [commit-msg]
        pass_filenames: true       # pre-commit appends the message-file path
        always_run: true
      - id: acs-pre-push
        name: acs branch + commit conventions
        entry: python3 .acs/ci/check-conventions.py --mode pre-push
        language: system
        stages: [pre-push]
        pass_filenames: false
        always_run: true
```

**Fallback — raw git hooks (per-clone).** When not using pre-commit, run the
committed installer, which copies `.acs/ci/commit-msg` + `.acs/ci/pre-push` into
this clone and refuses to clobber a non-acs hook:

```bash
sh .acs/ci/install-hooks.sh
```

Either way, hooks are **per-clone** — each teammate runs it once after cloning.
The dedicated command for that is **`/acs:install-hooks`** (or
`sh .acs/ci/install-hooks.sh` without the plugin); it ensures the `.acs/ci/`
files exist and installs the hooks, and is the thing to tell teammates to run.
Offer to run it now for this clone.

### The actual gate — branch protection (admin, one-time)

The workflow is advisory until the check is **required** and the default branch
**blocks direct pushes**. This is set once by a repo admin and then binds every
non-admin teammate — they cannot bypass it. Detect admin and act accordingly:

```bash
slug=$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null)
admin=$(gh api "repos/$slug" --jq .permissions.admin 2>/dev/null)
branch=$(gh repo view --json defaultBranchRef -q .defaultBranchRef.name 2>/dev/null)
echo "repo=$slug default=$branch admin=$admin"
```

- **`admin=true` and the user consents** — configure protection so the check is
  required and a PR is mandatory (which blocks direct pushes). The required
  status-check **context is the workflow job name** (`Branch / PR / commit
  conventions`); confirm it matches if the user customized the workflow:

  ```bash
  gh api -X PUT "repos/$slug/branches/$branch/protection" \
    -H "Accept: application/vnd.github+json" --input - <<'JSON'
  {
    "required_status_checks": { "strict": true, "contexts": ["Branch / PR / commit conventions"] },
    "enforce_admins": true,
    "required_pull_request_reviews": { "required_approving_review_count": 0 },
    "restrictions": null
  }
  JSON
  ```

  (`required_pull_request_reviews` present = a PR is mandatory, so direct pushes
  to `$branch` are blocked; `restrictions: null` keeps all collaborators able to
  open PRs.) The check first appears in the contexts list only after one workflow run, so
  if the API rejects an unknown context, tell the user to open a PR first (to
  register the check), then re-run the command. Mention GitHub **rulesets** as
  the modern alternative (repo or org level, same effect) if they prefer the UI.

- **`admin` is not `true`** — do NOT attempt the API call (it will 403). The
  committed workflow file needs no admin, so it still runs and shows a red X on
  non-conforming PRs. Print the exact command above for an admin to run once,
  and state clearly: **enforcement is advisory until a repo admin enables the
  required check + branch protection.** This is the answer to "teammates aren't
  admins" — the gate is meant to be set once by an admin and then inherited.

Record everything configured here for Steps 8 and the completion report:
checks enabled, exemptions, files written, labels, pre-push choice, and the
branch-protection outcome (configured / printed-for-admin / declined).

## Step 7d — CI tests + coverage gate (opt-in, never silent)

Offer a CI check that runs the repo's test suite and enforces the coverage
target on **every PR** — the same `test_coverage_percent` the `/code` TDD cycle
hard-fails on, now a merge gate for any PR (including ones that never went
through the pipeline). Skip the whole step on a plain "no". Same honesty as
Step 7c: this is a real gate only as a **required status check on a protected
default branch**.

### Choose the test command (detect candidates first)

acs stores no test command otherwise (`/code` discovers tooling per run), so
collect one now. Detect candidates and suggest:

```bash
ls pyproject.toml setup.cfg pytest.ini tox.ini 2>/dev/null            # python
[ -f package.json ] && grep -oE '"(test|test:unit|coverage)" *:' package.json   # node
ls go.mod Makefile 2>/dev/null                                       # go / make
```

Ask for `tests.command` — it MUST run the suite and **fail on a coverage
shortfall** (delegate to the tool; acs exports `ACS_COVERAGE` = the configured
`test_coverage_percent`):

| Stack | Example `tests.command` |
|-------|-------------------------|
| Python / pytest | `pytest --cov --cov-fail-under=$ACS_COVERAGE` |
| Node / jest | `jest --coverage` (with a `coverageThreshold` in the jest config) |
| Go | `go test ./... -coverprofile=cover.out` + a threshold check on `go tool cover -func` |

Optionally collect `tests.setup` (dependency bring-up, e.g. `pip install -e .[test]`
or `npm ci`). Write `tests` and — if not default — `test_coverage_percent` to the
**project** file `<repo>/.acs/settings.json`: the CI runner reads only the
committed project file (same precondition as Step 7c). Confirm it is not
gitignored.

### Install the workflow + runner (copy, don't hand-write)

```bash
mkdir -p .acs/ci .github/workflows
cp "${CLAUDE_PLUGIN_ROOT}/templates/ci/run-tests.py" .acs/ci/run-tests.py
cp "${CLAUDE_PLUGIN_ROOT}/templates/ci/acs-tests.yml" .github/workflows/acs-tests.yml
chmod +x .acs/ci/run-tests.py
```

Regenerated on every re-run. Stage `.acs/settings.json`, `.acs/ci/run-tests.py`,
and `.github/workflows/acs-tests.yml` for the user to commit (do not commit
yourself unless asked).

### The gate — branch protection

Same as Step 7c: advisory until required. The required status-check **context is
the job name `Tests & coverage`**. If you configured branch protection in
Step 7c, add `"Tests & coverage"` to the `contexts` array alongside the
conventions check; otherwise print the `gh api … /protection` command (from
Step 7c) with `contexts: ["Tests & coverage"]` for an admin to run once. Record
the outcome for Step 8 and the completion report.

## Step 7e — Project agent guidance: pipeline-default `CLAUDE.md` (opt-in, default-on)

Write (or refresh) an **acs-managed block** in the consumer repo's `CLAUDE.md`
so every Claude session in the repo defaults to the pipeline instead of
freelancing a raw `gh pr create` — the steer that makes acs the *automatic*
path, not merely an available one (a non-ticket PR opened ad hoc has no ticket
for `/acs:merge-pr` to resolve; this block prevents that dead end at the
source). Offer it with a default-**yes** confirmation — recommended, but never
written silently. Skip the whole step on an explicit "no".

The block is **marker-delimited and idempotent**: it lives between
`<!-- BEGIN acs-managed … -->` and `<!-- END acs-managed -->`, so re-running
`/acs:init` replaces only that span and never touches the surrounding
`CLAUDE.md` content the user owns. Render it from the plugin template
`templates/CLAUDE.acs.md` (the configured `ticket_prefix` and the enforcement
`exempt_label` fill its placeholders), then upsert it into the repo-root
`CLAUDE.md` (created if absent) via the `acs_lib` helpers. Run from `<repo>`
(the main checkout — linked worktrees share it):

```bash
python3 - "${CLAUDE_PLUGIN_ROOT}/hooks/scripts" "${CLAUDE_PLUGIN_ROOT}/templates/CLAUDE.acs.md" <<'PY'
import os, sys
sys.path.insert(0, sys.argv[1])
import acs_lib
cwd = os.getcwd()
root = acs_lib.main_repo_root(cwd) or acs_lib.checkout_root(cwd) or cwd
settings, _ = acs_lib.load_settings(cwd)
prefix = settings.get("ticket_prefix", "")
exempt = ((settings.get("enforcement") or {}).get("exempt_label")) or "acs-exempt"
with open(sys.argv[2], encoding="utf-8") as fh:
    block = acs_lib.render_managed_block(fh.read(), prefix, exempt)
path = os.path.join(root, "CLAUDE.md")
existing = ""
if os.path.exists(path):
    with open(path, encoding="utf-8") as fh:
        existing = fh.read()
with open(path, "w", encoding="utf-8") as fh:
    fh.write(acs_lib.upsert_managed_block(existing, block))
print("wrote acs-managed block to", path)
PY
```

`render_managed_block` only substitutes the two placeholders (no other content
changes); `upsert_managed_block` replaces an existing acs-managed span in place
or appends one separated by a blank line, leaving the rest byte-for-byte — so a
re-run is safe and a hand-written `CLAUDE.md` is never clobbered. Tell the user
to **commit** `CLAUDE.md` so teammates inherit the guidance. Record the outcome
(written / refreshed / declined) for Step 8 and the completion report.

## Step 8 — Summary and next steps

Print a markdown table of every resolved setting, its value, and the file it
landed in (or "default — not written" for untouched defaults), e.g.:

| Key | Value | Written to |
|-----|-------|------------|
| `workspace_path` | `/Users/jane/acs-workspace` | `<repo>/.acs/settings.local.json` |
| `ticket_prefix` | `SHOP` | `<repo>/.acs/settings.json` |
| `test_coverage_percent` | `90` | default — not written |
| `enforcement` (CI) | checks on; gate via required check | `<repo>/.acs/settings.json` + `.github/workflows/acs-conventions.yml` |
| `tests` (CI) | suite + coverage gate on PRs | `<repo>/.acs/settings.json` + `.acs/ci/run-tests.py` + `.github/workflows/acs-tests.yml` |
| `CLAUDE.md` guidance | acs-managed block (pipeline default + exempt `--pr` merge) | `<repo>/CLAUDE.md` (written / refreshed / declined) |

Then point the user at the next steps. Decide greenfield vs brownfield by
looking at the repo (`git ls-files` — an existing product codebase is
brownfield; an empty or docs-only repo is greenfield):

- **Brownfield**: run `/acs:create-prd` (reverse-engineers a baseline PRD,
  opens a docs PR), then `/acs:create-architecture` (HLD + LLD docs PR) —
  merge each PR with `/acs:merge-pr <ticket-id>` after your own review.
- **Greenfield**: same two skills (they elicit instead of reverse-engineer),
  plus `/acs:create-project` to scaffold the repo.
- After that, ship features with `/acs:ship <prompt>` or step-by-step starting
  at `/acs:create-ticket <prompt>`.

If tracker CLI checks were skipped or failed in Step 4, repeat the pending fix
command (`gh auth login` / `acli auth login`) in the summary.

Confirm the full workflow is ready: a one-line toolchain status (from Step 0b)
and the reminder that the plugin already provides every skill — bootstrap
(`/acs:init`), the pipeline (`/acs:create-prd` → `/acs:create-architecture` →
`/acs:create-project` → `/acs:create-ticket` → `/acs:create-design` →
`/acs:create-spec` → `/acs:code` → `/acs:create-pr` → `/acs:merge-pr`), the
umbrella `/acs:ship`, and utilities `/acs:handoff`, `/acs:update`,
`/acs:install-hooks`. Repeat any unmet toolchain install hint here so the gap is
explicit.

## Completion report (normative)

Every terminal outcome of a direct invocation — completed, failed,
interrupted, or handed off — ends your final message with the standard block
(INTERNALS.md "Completion report"), rendered only AFTER the post-hook
succeeded. Same labels, same order, `none` where empty; replace the Ticket line with **Scope** (no ticket at init time):

```markdown
## /acs:init · <ticket-id> · <status>

- **Ticket**: <id> — <title> (<type>)
- **Status**: <status> — <stop_reason>
- **Results**: toolchain preflight outcome (tools present / installed / still missing with the install hint); settings written, per key: value and which file (user/project `settings.json`, gitignored `settings.local.json`); workspace created/verified; tracker CLI check outcome; status line + subagent status line opt-in outcomes (configured at which scope / declined / already set); CI convention enforcement outcome (checks enabled, files written, labels, pre-push choice, branch-protection: configured / printed-for-admin / declined); `CLAUDE.md` pipeline-default guidance block (written / refreshed / declined)
- **Findings**: <open findings / clarifications, or "none">
- **Artifacts**: <partition files, repo paths, branch, PR URL>
- **Metrics**: iterations <n>/3 · <wall time> · ~<tokens in/out> · ~$<cost_usd>
- **Next**: brownfield: `/acs:create-prd` then `/acs:create-architecture`; greenfield: same plus `/acs:create-project`; then `/acs:ship <prompt>` or `/acs:create-ticket <prompt>`
```
