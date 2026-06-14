---
name: install-hooks
description: Install this clone's local acs convention hooks (commit-msg + pre-push) that enforce the branch and commit formats you configured at /acs:init, before anything is pushed — the `pre-commit install` equivalent for acs. Use after cloning a repo that has acs enforcement set up, or whenever you want local enforcement of the configured conventions before pushing a PR.
disable-model-invocation: true
---

You are the coordinator of `/acs:install-hooks`. This is NOT a hooked pipeline
skill: no `skill-start.py`, no pre/post hooks, no subagents, no reflection loop.
You do everything yourself in this session with Bash, Read, Edit, and Write.

The job: install this clone's local git hooks so the conventions the user
configured at `/acs:init` (`formats.branch_name`, `formats.commit_message`) are
enforced **before push** — `commit-msg` validates the commit subject as it is
written, `pre-push` validates the branch name and the push range's commit
subjects. Both run the same `.acs/ci/check-conventions.py` against the same
committed `.acs/settings.json` as CI, so laptop and runner never drift. PR title
and description can only be checked once a PR exists, so those stay CI-only.

Git hooks are **per-clone** — that is why this is a command each teammate runs
once after cloning, exactly like `pre-commit install`. The hooks are
`--no-verify`-bypassable; CI is the real backstop.

## Step 0 — Preflight

Resolve the repo roots (operate on the main checkout so linked worktrees share
the hooks via the common git dir):

```bash
python3 - "${CLAUDE_PLUGIN_ROOT}/hooks/scripts" <<'PY'
import os, sys
sys.path.insert(0, sys.argv[1])
import acs_lib
cwd = os.getcwd()
print("checkout_root:", acs_lib.checkout_root(cwd))
print("main_repo_root:", acs_lib.main_repo_root(cwd))
PY
```

If `checkout_root` is empty, stop: `/acs:install-hooks` must run inside the
consumer repo. Use `main_repo_root` as `<repo>` below.

## Step 1 — Require configured conventions

The hooks are useless (and fail closed) without committed conventions. Verify
`<repo>/.acs/settings.json` resolves with `ticket_prefix` + `formats`:

```bash
python3 - "${CLAUDE_PLUGIN_ROOT}/hooks/scripts" "<repo>" <<'PY'
import os, sys
sys.path.insert(0, sys.argv[1])
import acs_lib
settings, _ = acs_lib.load_settings(sys.argv[2])
ok = bool(settings.get("ticket_prefix")) and isinstance(settings.get("formats"), dict)
print("CONVENTIONS_OK" if ok else "MISSING")
PY
```

On `MISSING`, stop and tell the user to run `/acs:init` first (it writes the
committed conventions the hooks read). Do not install hooks that would only
block every commit with "run /acs:init".

## Step 2 — Ensure the local-enforcement files are present

The hooks and installer live in `<repo>/.acs/ci/`. Copy any that are missing
from the plugin templates (this bootstraps a repo where `/acs:init`'s CI step
was never run), and make the scripts executable. Run from `<repo>`:

```bash
mkdir -p .acs/ci
for f in check-conventions.py commit-msg pre-push install-hooks.sh; do
  [ -f ".acs/ci/$f" ] || cp "${CLAUDE_PLUGIN_ROOT}/templates/ci/$f" ".acs/ci/$f"
done
chmod +x .acs/ci/check-conventions.py .acs/ci/commit-msg .acs/ci/pre-push .acs/ci/install-hooks.sh
```

If you copied any file, tell the user to **commit** `.acs/ci/` so teammates get
it (do not commit yourself unless asked). Confirm `.acs/` is not gitignored
(`git check-ignore -q .acs/ci/check-conventions.py` returning a hit means a
broad rule hides it — warn the user).

## Step 3 — Install the hooks

Two paths; pick by what the repo already uses:

- **Repo uses the pre-commit framework** (`.pre-commit-config.yaml` present and
  the user wants shared, tracked hooks): ensure the two acs entries exist under
  `repos:` (insert this managed block with Edit if `id: acs-commit-msg` is not
  already present — never duplicate it, never disturb other entries), then run
  the framework installer:

  ```yaml
    - repo: local
      hooks:
        - id: acs-commit-msg
          name: acs commit message convention
          entry: python3 .acs/ci/check-conventions.py --mode commit-msg --message-file
          language: system
          stages: [commit-msg]
          pass_filenames: true
          always_run: true
        - id: acs-pre-push
          name: acs branch + commit conventions
          entry: python3 .acs/ci/check-conventions.py --mode pre-push
          language: system
          stages: [pre-push]
          pass_filenames: false
          always_run: true
  ```

  ```bash
  pre-commit install --hook-type commit-msg --hook-type pre-push
  ```

  Adding the entries edits a tracked file — remind the user to commit
  `.pre-commit-config.yaml`.

- **Otherwise (raw git hooks)** — run the committed installer, which copies
  `.acs/ci/commit-msg` and `.acs/ci/pre-push` into this clone's hooks dir and
  refuses to clobber a non-acs hook:

  ```bash
  sh .acs/ci/install-hooks.sh
  ```

The installer also auto-delegates to `pre-commit install` when the config
already declares the acs entries, so re-running it is always safe.

## Step 4 — Verify

Confirm the hooks are in place and actually fire:

```bash
ls -l "$(git rev-parse --git-path hooks)/commit-msg" "$(git rev-parse --git-path hooks)/pre-push" 2>/dev/null
printf 'nope not a valid subject\n' | python3 .acs/ci/check-conventions.py --mode commit-msg --message-file /dev/stdin; echo "rc=$? (non-zero only if commit_message check is enabled)"
```

A clean (`rc=0`) result here just means the `commit_message` check is off in
settings (default) — the `pre-push` branch-name check still applies. Do not
treat `rc=0` as a failure.

## Step 5 — Hand-off note

Tell the user, concisely:

- Each teammate runs `/acs:install-hooks` (or `sh .acs/ci/install-hooks.sh`)
  once per clone — hooks are per-clone, like `pre-commit install`.
- The hooks enforce the configured `formats.*`; change them with `/acs:init`.
- They are `--no-verify`-bypassable, so the required CI check (if configured) is
  the real gate.
- Commit any newly created `.acs/ci/*` (and `.pre-commit-config.yaml` if edited).

## Completion report (normative)

Every terminal outcome of a direct invocation — completed, failed, or
interrupted — ends your final message with the standard block (INTERNALS.md
"Completion report"). Same labels, same order, `none` where empty; replace the
Ticket line with **Scope** (no ticket):

```markdown
## /acs:install-hooks · <scope> · <status>

- **Scope**: local hooks for <repo>
- **Status**: <status> — <stop_reason>
- **Results**: install path (pre-commit framework / raw git hooks); hooks installed (commit-msg, pre-push) or skipped (with reason); files copied into `.acs/ci/` (and whether they still need committing); verification outcome
- **Findings**: <missing conventions / pre-existing non-acs hooks / clarifications, or "none">
- **Artifacts**: `.acs/ci/` files, this clone's `.git/hooks/*`, edited `.pre-commit-config.yaml`
- **Metrics**: <wall time> · ~<tokens in/out> · ~$<cost_usd>
- **Next**: have teammates run `/acs:install-hooks` per clone; configure the required CI check via `/acs:init` for a true gate
```
