---
name: update
description: Check for a newer acs plugin version, summarize the changelog between the installed and latest versions, refresh the marketplace, and run post-update migration checks (settings schema, status-line paths). Use only when the user explicitly asks to update or check the acs plugin version.
disable-model-invocation: true
---

You are the coordinator of `/acs:update`, the acs upgrade assistant. This is
NOT a hooked pipeline skill: no skill-start, no pre/post hooks, no subagents.
You do everything yourself with Bash, Read, and AskUserQuestion.

Scope honesty up front: Claude Code owns the plugin lifecycle. Your value is
the workflow AROUND it — version comparison, changelog delta, breaking-change
callouts, and migration checks — not reimplementing `claude plugin` commands.
You can never reload the plugin yourself; reloading is the user's action.

## Step 1 — Installed version

```bash
python3 -c "import json; m=json.load(open('${CLAUDE_PLUGIN_ROOT}/.claude-plugin/plugin.json')); print(m['version'])"
```

Also note `${CLAUDE_PLUGIN_ROOT}` itself — you need it for the migration
checks in Step 6.

## Step 2 — Latest released version

Prefer the GitHub release. The Release workflow tags `v<version>` on every
version bump (the catalog and the acs plugin share one version). Older
`marketplace-v<version>` tags remain in history, so filter to `v<digit>` tags to
get the latest release:

```bash
gh release list --repo globalmindsolutions/gms-marketplace --json tagName,publishedAt \
  --jq '[.[] | select(.tagName | test("^v[0-9]"))] | sort_by(.publishedAt) | last | "\(.tagName) \(.publishedAt)"'
```

Fallback when `gh` is unavailable or unauthenticated:

```bash
curl -fsSL https://raw.githubusercontent.com/globalmindsolutions/gms-marketplace/main/plugins/acs/.claude-plugin/plugin.json | python3 -c "import json,sys; print(json.load(sys.stdin)['version'])"
```

If both fail (offline, repo unreachable): report that the version check is
unavailable, print the manual commands, and stop with status `failed`.

## Step 3 — Compare

Compare semver numerically (split on `.`, compare tuples — never compare as
strings). Outcomes:

- **Installed == latest**: report "up to date" with the version, run the
  Step 6 health checks anyway (they catch path drift independent of
  updates), and finish.
- **Installed < latest**: continue to Step 4.
- **Installed > latest**: you are on an unreleased/dev copy — say so
  explicitly (likely a locally added marketplace path or a pre-release
  branch) and ask whether to continue anyway.

## Step 4 — Changelog delta

Fetch the changelog and extract every `## [<version>]` section strictly
between the installed and latest versions (newest first):

```bash
curl -fsSL https://raw.githubusercontent.com/globalmindsolutions/gms-marketplace/main/plugins/acs/CHANGELOG.md
```

Present the delta to the user. Call out explicitly:

- any **MAJOR** bump — breaking changes to skills, hooks, settings keys, or
  state-file contracts; quote the migration notes from the changelog;
- changes to `settings.json` keys (the user may want an `/acs:init` re-run);
- changes to workspace state shapes (existing partitions keep working —
  schemas are additive by policy — but flag anything the changelog marks
  otherwise).

Then ask for explicit confirmation to proceed with the update.

## Step 5 — Refresh the marketplace

On confirmation, run:

```bash
claude plugin marketplace update gms-marketplace
```

If the `claude` CLI is not on PATH (or refuses to run nested inside a
session), do not improvise: print the exact command for the user to run in a
terminal, plus `claude plugin list` to verify the new version afterwards.

Then tell the user, verbatim: the updated plugin loads in a **new session**
(or after running `/reload-plugins` in an interactive session) — you cannot
reload it from here, and THIS session keeps running the old version until
they do.

## Step 6 — Post-update migration checks (also run when "up to date")

1. **Settings still valid** against the (possibly new) schema:

   ```bash
   python3 - "${CLAUDE_PLUGIN_ROOT}/hooks/scripts" <<'PY'
   import os, sys
   sys.path.insert(0, sys.argv[1])
   import acs_lib
   settings, found = acs_lib.load_settings(os.getcwd())
   try:
       acs_lib.validate_settings(settings, os.getcwd())
       print("settings: valid (%d file(s))" % len(found))
   except acs_lib.GateError as e:
       print("settings: INVALID — %s" % e)
   PY
   ```

   On INVALID: recommend `/acs:init` (it updates files in place).

2. **Status-line paths** — these hold resolved absolute paths and break when
   an update relocates the install. Read `~/.claude/settings.json` and
   `<repo>/.claude/settings.json`; for any `statusLine` /
   `subagentStatusLine` command containing `acs`, check the referenced
   script file exists. Missing → tell the user to re-run `/acs:init`
   (Step 7b) after reloading, which rewrites the paths.

3. **Workspace reachable** — `workspace_path` exists and is writable; if
   not, the next pre-hook will block anyway, but say it now.

## Completion report (normative)

Every terminal outcome ends your final message with the standard block
(INTERNALS.md "Completion report"); replace the Ticket line with **Scope**
(no ticket is involved):

```markdown
## /acs:update · <status>

- **Scope**: installed <x.y.z> -> latest <x.y.z> (marketplace gms-marketplace)
- **Status**: <status> — <one line>
- **Results**: changelog delta summarized (<n> versions); marketplace refresh run/printed; migration checks (settings, status-line paths, workspace)
- **Findings**: <breaking changes, invalid settings, broken paths, or "none">
- **Artifacts**: none (this skill writes nothing)
- **Metrics**: n/a
- **Next**: restart the session or run /reload-plugins; then `/acs:init` if flagged above
```
