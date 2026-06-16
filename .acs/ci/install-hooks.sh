#!/bin/sh
# acs install-hooks — install THIS clone's local convention-enforcement git
# hooks (commit-msg + pre-push). The `pre-commit install` equivalent for acs:
# each teammate runs it once per clone. Idempotent and dependency-free.
#
# Committed into the consumer repo at .acs/ci/install-hooks.sh by /acs:init, so
# a teammate who has only cloned the repo (no acs plugin) can still run:
#     sh .acs/ci/install-hooks.sh
# or invoke the skill `/acs:install-hooks`, which wraps this.
#
# The hooks call .acs/ci/check-conventions.py, which reads the conventions you
# configured at /acs:init from .acs/settings.json. Bypassable with
# `git commit --no-verify` / `git push --no-verify`; CI is the backstop.
set -eu

root=$(git rev-parse --show-toplevel 2>/dev/null) || { echo "error: not inside a git repository" >&2; exit 1; }
cd "$root"

checker=".acs/ci/check-conventions.py"
if [ ! -f "$checker" ]; then
  echo "error: $checker not found — run /acs:init (CI enforcement, Step 7c) or /acs:install-hooks first." >&2
  exit 1
fi

# If the repo already wires the acs hooks through the pre-commit framework,
# delegate to it (tracked + shared) instead of writing raw hooks.
if [ -f .pre-commit-config.yaml ] && grep -q 'id: acs-commit-msg' .pre-commit-config.yaml 2>/dev/null; then
  if command -v pre-commit >/dev/null 2>&1; then
    pre-commit install --hook-type commit-msg --hook-type pre-push
    echo "acs hooks installed via the pre-commit framework (commit-msg + pre-push)."
    exit 0
  fi
  echo "note: .pre-commit-config.yaml declares the acs hooks but 'pre-commit' is not installed." >&2
  echo "      install it (pipx install pre-commit) and re-run, or continue with raw hooks below." >&2
fi

hooks_dir=$(git rev-parse --git-path hooks)
mkdir -p "$hooks_dir"
installed=0
for h in commit-msg pre-push; do
  target="$hooks_dir/$h"
  src=".acs/ci/$h"
  if [ ! -f "$src" ]; then
    echo "warning: $src missing — skipping $h (re-run /acs:install-hooks to restore it)" >&2
    continue
  fi
  # Never clobber a non-acs hook the user maintains (e.g. one pre-commit owns).
  if [ -e "$target" ] && ! grep -q 'check-conventions.py' "$target" 2>/dev/null; then
    echo "warning: $target already exists and is not an acs hook — left untouched." >&2
    echo "         Merge '$src' into it by hand, or use the pre-commit entries instead." >&2
    continue
  fi
  cp "$src" "$target"
  chmod +x "$target"
  echo "installed $target"
  installed=$((installed + 1))
done

if [ "$installed" -gt 0 ]; then
  echo "acs local hooks ready. They enforce the formats from .acs/settings.json before push."
else
  echo "no hooks installed — see the warnings above." >&2
fi
