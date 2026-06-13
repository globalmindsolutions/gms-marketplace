---
name: init
description: Initialize or update the acs configuration for the current repo — settings scope, workspace path, ticket prefix, coverage target, merge strategy, tracker, doc paths, formats, and subagent models. Use when setting up acs on a new repo, when another acs skill fails with "run /acs:init first", or when the user wants to change any acs setting.
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

### models — optional, default inherit

Ask only if the user wants per-role model control. Shape per role
(`planner`, `executor`, `verifier`, `coordinator`): a model string (e.g.
`"sonnet"`) or `{"model": "...", "effort": "low|medium|high|xhigh|max|inherit"}`,
plus per-skill `models.overrides.<skill>.<role>`. Resolution is per field:
override -> role -> inherit. If the user sets `models.coordinator`, tell them
it only takes effect for coordinators spawned under `/acs:ship`; direct skill
invocations run in the user's session on the session's model.

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

Then ensure the local file is gitignored — append the exact line if missing
(run from `<repo>`, the main checkout root):

```bash
grep -qxF '.acs/settings.local.json' .gitignore 2>/dev/null \
  || printf '.acs/settings.local.json\n' >> .gitignore
```

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

## Step 8 — Summary and next steps

Print a markdown table of every resolved setting, its value, and the file it
landed in (or "default — not written" for untouched defaults), e.g.:

| Key | Value | Written to |
|-----|-------|------------|
| `workspace_path` | `/Users/jane/acs-workspace` | `<repo>/.acs/settings.local.json` |
| `ticket_prefix` | `SHOP` | `<repo>/.acs/settings.json` |
| `test_coverage_percent` | `90` | default — not written |

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

## Completion report (normative)

Every terminal outcome of a direct invocation — completed, failed,
interrupted, or handed off — ends your final message with the standard block
(INTERNALS.md "Completion report"), rendered only AFTER the post-hook
succeeded. Same labels, same order, `none` where empty; replace the Ticket line with **Scope** (no ticket at init time):

```markdown
## /acs:init · <ticket-id> · <status>

- **Ticket**: <id> — <title> (<type>)
- **Status**: <status> — <stop_reason>
- **Results**: settings written, per key: value and which file (user/project `settings.json`, gitignored `settings.local.json`); workspace created/verified; tracker CLI check outcome; status line + subagent status line opt-in outcomes (configured at which scope / declined / already set)
- **Findings**: <open findings / clarifications, or "none">
- **Artifacts**: <partition files, repo paths, branch, PR URL>
- **Metrics**: iterations <n>/3 · <wall time> · ~<tokens in/out> · ~$<cost_usd>
- **Next**: brownfield: `/acs:create-prd` then `/acs:create-architecture`; greenfield: same plus `/acs:create-project`; then `/acs:ship <prompt>` or `/acs:create-ticket <prompt>`
```
