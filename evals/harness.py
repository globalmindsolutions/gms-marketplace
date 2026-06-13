"""Behavioral eval harness for the acs plugin (M2 epic E1.1).

Where `tests/` exercises the *deterministic* layer (hooks, gates, state) by
driving the Python scripts directly and runs in PR CI without `claude`, this
harness exercises the *agentic* layer: it runs real `claude -p` sessions that
invoke acs skills end to end and asserts on the **workspace artifacts** they
produce (the JSON state the pipeline itself trusts) — never on prose output.

It is deliberately NOT under `tests/`: PR CI runs `python3 -m unittest
discover -s tests`, and these scenarios cost money, need network + an
authenticated `claude` CLI, and are non-deterministic. They belong to the
nightly job (E1.4), not the PR gate.

Two tiers of scenario, by cost:

  * **free**  — no `claude`. Drives the *installed* dispatch hook through
    pipeline states and asserts exit codes/messages. Catches packaging drift
    in the shipped build (the unittest suite only sees the source tree).
  * **paid**  — spawns `claude -p`. Asserts on the artifacts the agents write.

Run:  python3 evals/run_evals.py            # free tier only (default)
      python3 evals/run_evals.py --paid     # include claude-driven scenarios
      python3 evals/run_evals.py --list
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE_SCRIPTS = os.path.join(REPO_ROOT, "plugins", "acs", "hooks", "scripts")


# --------------------------------------------------------------------------- #
# Locating the plugin under test
# --------------------------------------------------------------------------- #

def installed_scripts_dir():
    """Resolve the hook-scripts dir of the *installed* acs build, newest version.

    Falls back to the in-repo source tree when no install is present, so the
    free tier still runs in a checkout that never installed the plugin. The
    chosen path is what every gate check executes, so an eval against the
    installed build is faithful to what consumers actually load.
    """
    cache = os.path.expanduser("~/.claude/plugins/cache/gms-plugins/acs")
    if os.path.isdir(cache):
        versions = [v for v in os.listdir(cache)
                    if os.path.isdir(os.path.join(cache, v, "hooks", "scripts"))]
        if versions:
            newest = max(versions, key=_version_key)
            return os.path.join(cache, newest, "hooks", "scripts"), newest
    return SOURCE_SCRIPTS, "source"


def _version_key(v):
    parts = []
    for chunk in v.split("."):
        parts.append(int(chunk) if chunk.isdigit() else -1)
    return parts


# --------------------------------------------------------------------------- #
# Sandbox: a throwaway consumer repo + workspace + valid .acs settings
# --------------------------------------------------------------------------- #

class Sandbox:
    """A throwaway consumer repo + outside-the-repo workspace.

    Use as a context manager so the temp dirs are always cleaned up::

        with Sandbox(prefix="TKT", slug="shop") as sb:
            sb.gate("create-ticket")          # free gate check
            sb.run_skill("/acs:create-ticket Add X")   # paid

    By default the settings are pre-seeded (the skill-under-test is isolated
    from `/acs:init`). Pass ``init=False`` to start uninitialized — e.g. to
    eval `/acs:init` itself, or assert the "run /acs:init first" gate.
    """

    def __init__(self, prefix="EVAL", slug="sandbox", init=True, keep=False,
                 coverage=90, tracker="local"):
        self.prefix = prefix
        self.slug = slug
        self._init = init
        self.keep = keep or os.environ.get("ACS_EVAL_KEEP") == "1"
        self.coverage = coverage
        self.tracker = tracker
        self.scripts, self.build = installed_scripts_dir()

    def __enter__(self):
        self.tmp = tempfile.mkdtemp(prefix="acs-eval-")
        self.repo = os.path.join(self.tmp, self.slug)
        self.ws = os.path.join(self.tmp, "workspace")
        os.makedirs(self.repo)
        os.makedirs(self.ws)
        self._git("init", "-q")
        # A stable remote makes the workspace repo-id deterministic.
        self._git("remote", "add", "origin",
                  "https://github.com/example/%s.git" % self.slug)
        self._git("config", "user.email", "eval@example.com")
        self._git("config", "user.name", "eval")
        with open(os.path.join(self.repo, "app.py"), "w") as fh:
            fh.write('def health():\n    return "ok"\n')
        self._git("add", "-A")
        self._git("commit", "-qm", "seed")
        if self._init:
            self._seed_settings()
        return self

    def __exit__(self, *exc):
        if not self.keep:
            shutil.rmtree(self.tmp, ignore_errors=True)
        else:
            sys.stderr.write("[harness] kept sandbox: %s\n" % self.tmp)
        return False

    # -- setup helpers ----------------------------------------------------- #

    def _git(self, *args):
        subprocess.run(["git", "-C", self.repo, *args], check=True,
                       capture_output=True)

    def _seed_settings(self):
        os.makedirs(os.path.join(self.repo, ".acs"))
        self._write(".acs/settings.json", {
            "ticket_prefix": self.prefix,
            "test_coverage_percent": self.coverage,
            "merge_strategy": "squash",
            "tracker": {"provider": self.tracker},
        })
        self._write(".acs/settings.local.json", {"workspace_path": self.ws})
        with open(os.path.join(self.repo, ".gitignore"), "a") as fh:
            fh.write(".acs/settings.local.json\n")

    def _write(self, rel, data):
        path = os.path.join(self.repo, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")

    # -- deterministic seeding via the installed helper CLIs -------------- #
    #
    # These let a scenario fast-forward the pipeline to a known state without
    # spending `claude` — e.g. seed "ready for /acs:code" so a single paid
    # session can be asserted on. Same scripts the skills themselves invoke.

    def run_script(self, script, *args, stdin=None):
        return subprocess.run(
            [sys.executable, os.path.join(self.scripts, script)] + list(args),
            input=stdin, capture_output=True, text=True, cwd=self.repo)

    def mint_ticket(self, title, ttype="task", needs_design=False, parent=None):
        extra = ["--needs-design", "true" if needs_design else "false"]
        if parent:
            extra += ["--parent", parent]
        out = self.run_script("new-ticket.py", "--title", title, "--type", ttype,
                              *extra)
        if out.returncode != 0:
            raise AssertionError("new-ticket failed: %s" % out.stderr)
        return json.loads(out.stdout)["ticket_id"]

    def start_run(self, skill, ticket):
        out = self.run_script("skill-start.py", "--skill", skill, "--ticket", ticket)
        if out.returncode != 0:
            raise AssertionError("skill-start %s failed: %s" % (skill, out.stderr))
        return out

    def complete_run(self, skill, ticket, result=None):
        out = self.run_script("post-%s.py" % skill, "--ticket", ticket,
                              stdin=json.dumps(result or {"status": "completed"}))
        if out.returncode != 0:
            raise AssertionError("post-%s failed: %s" % (skill, out.stderr))
        return out

    def write_repo_file(self, rel, content):
        path = os.path.join(self.repo, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(content)

    # -- free tier: the real installed gate ------------------------------- #

    def gate(self, skill, args=""):
        """Run the installed PreToolUse dispatcher for `/acs:<skill>`.

        Returns (exit_code, stderr). exit 2 == blocked; the message explains
        what must run first. This is the exact path Claude Code takes when the
        Skill tool is about to launch an acs skill — no `claude` needed.
        """
        payload = json.dumps({
            "cwd": self.repo,
            "tool_name": "Skill",
            "tool_input": {"skill": "acs:" + skill, "args": args},
        })
        proc = subprocess.run(
            [sys.executable, os.path.join(self.scripts, "dispatch.py"), "pre"],
            input=payload, capture_output=True, text=True, cwd=self.repo,
        )
        return proc.returncode, (proc.stderr or "").strip()

    # -- paid tier: a real claude session --------------------------------- #

    def run_skill(self, prompt, allowed_tools=("Bash", "Read", "Write", "Edit",
                                               "Glob", "Grep", "Task",
                                               "TodoWrite", "Skill"),
                  timeout=900):
        """Drive a headless `claude -p` session in the sandbox repo.

        Returns a dict: {ok, is_error, result, cost_usd, num_turns, raw}.
        Uses `--output-format json` for a single parseable envelope. The
        caller asserts on workspace artifacts afterwards, not on `result`.
        """
        cmd = [
            "claude", "-p", prompt,
            "--output-format", "json",
            "--permission-mode", "acceptEdits",
            "--allowedTools", " ".join(allowed_tools),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              cwd=self.repo, timeout=timeout)
        out = {"ok": proc.returncode == 0, "is_error": None, "result": "",
               "cost_usd": None, "num_turns": None, "raw": proc.stdout,
               "stderr": proc.stderr, "returncode": proc.returncode}
        try:
            env = json.loads(proc.stdout)
            out["is_error"] = env.get("is_error")
            out["result"] = env.get("result", "")
            out["cost_usd"] = env.get("total_cost_usd")
            out["num_turns"] = env.get("num_turns")
            out["ok"] = proc.returncode == 0 and not env.get("is_error")
        except (json.JSONDecodeError, TypeError):
            out["ok"] = False
        return out

    # -- artifact assertions ---------------------------------------------- #

    def partition_root(self):
        """The single <workspace>/<repo-id>/ dir created by the pipeline."""
        subdirs = [d for d in os.listdir(self.ws)
                   if os.path.isdir(os.path.join(self.ws, d))]
        if len(subdirs) != 1:
            raise AssertionError(
                "expected exactly one repo partition under %s, found %r"
                % (self.ws, subdirs))
        return os.path.join(self.ws, subdirs[0])

    def repo_json(self, name):
        """Load a repo-level workspace JSON (tickets-index/counters/metrics)."""
        return self._load(os.path.join(self.partition_root(), name))

    def ticket_json(self, ticket, name):
        """Load a ticket-partition JSON (ticket.json/pipeline-state.json/…)."""
        return self._load(os.path.join(self.partition_root(), ticket, name))

    def ticket_path(self, ticket, *rel):
        return os.path.join(self.partition_root(), ticket, *rel)

    def _load(self, path):
        if not os.path.isfile(path):
            raise AssertionError("expected artifact missing: %s" % path)
        with open(path) as fh:
            return json.load(fh)


# --------------------------------------------------------------------------- #
# Scenario result + assertion helpers
# --------------------------------------------------------------------------- #

class Check:
    """Collects named assertions for one scenario into a pass/fail report."""

    def __init__(self, name):
        self.name = name
        self.results = []   # (label, ok, detail)

    def ok(self, label, condition, detail=""):
        self.results.append((label, bool(condition), detail))
        return bool(condition)

    def eq(self, label, got, want):
        return self.ok(label, got == want, "got=%r want=%r" % (got, want))

    @property
    def passed(self):
        return all(ok for _, ok, _ in self.results)

    def lines(self):
        for label, ok, detail in self.results:
            mark = "PASS" if ok else "FAIL"
            tail = "" if ok else ("  (%s)" % detail if detail else "")
            yield "    [%s] %s%s" % (mark, label, tail)
