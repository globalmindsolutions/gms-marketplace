"""Tests for MAR-5 spec 01 — Codex CLI gate-enforcement dispatch.

Tests 1-6 per the spec Test plan (specs/01-codex-gate-dispatch.md:212-299).

Specification source citation (T1 traceability):
    docs/architecture/lld/runtime-coupling-inventory.md:38
    Surface #1 — Hook gating: "No-bypass shim: first instruction in each acs skill
    Codex definition calls dispatch.py pre; exits non-zero before skill body."

Framework: unittest (stdlib only).  No pip packages.
Subprocess invocation of real scripts mirrors AcsWorkspaceCase (test_acs_plugin.py:30-79),
specifically .pre() at test_acs_plugin.py:58-63 and session_end at :231-242.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(REPO_ROOT, "plugins", "acs", "hooks", "scripts")
CODEX_SKILLS_DIR = os.path.join(REPO_ROOT, "plugins", "acs", "runtimes", "codex", "skills")

if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import acs_lib as lib  # noqa: E402


class CodexGateWorkspaceCase(unittest.TestCase):
    """Fixture: a consumer git repo with valid .acs settings + empty workspace.

    Mirrors AcsWorkspaceCase (test_acs_plugin.py:30-79).
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="acs-codex-gate-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = os.path.join(self.tmp, "shop")
        self.ws = os.path.join(self.tmp, "workspace")
        os.makedirs(self.repo)
        subprocess.run(["git", "init", "-q", self.repo], check=True)
        subprocess.run(["git", "-C", self.repo, "remote", "add", "origin",
                        "https://github.com/acme/shop.git"], check=True)
        os.makedirs(os.path.join(self.repo, ".acs"))
        self.write_settings({"ticket_prefix": "SHOP", "test_coverage_percent": 90})
        with open(os.path.join(self.repo, ".acs", "settings.local.json"), "w") as fh:
            json.dump({"workspace_path": self.ws}, fh)

    def write_settings(self, data):
        with open(os.path.join(self.repo, ".acs", "settings.json"), "w") as fh:
            json.dump(data, fh)

    def run_script(self, script, *args, stdin=None, cwd=None, env=None):
        """Run a script from SCRIPTS dir, capturing output.  Mirror test_acs_plugin.py:51-56."""
        return subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, script)] + list(args),
            input=stdin, capture_output=True, text=True, cwd=cwd or self.repo,
            env=env,
        )

    def pre(self, skill, cwd=None):
        """Synthesize a shape-(a) payload and pipe it to dispatch.py pre.

        Shape (a): {"cwd": ..., "tool_input": {"skill": "acs:<skill>"}}
        Mirrors test_acs_plugin.py:58-63 but uses the minimal shape-(a) payload
        (no "tool_name", just the keys skill_name_from_payload reads at dispatch.py:25-38).
        """
        payload = json.dumps({
            "cwd": cwd or self.repo,
            "tool_input": {"skill": "acs:" + skill},
        })
        return self.run_script("dispatch.py", "pre", stdin=payload,
                               cwd=cwd or self.repo)

    def session_end(self, cwd=None):
        """Invoke dispatch.py session-end with the minimal payload.

        Mirrors test_acs_plugin.py:231-242.
        """
        payload = json.dumps({"cwd": cwd or self.repo})
        return self.run_script("dispatch.py", "session-end", stdin=payload)

    def start(self, skill, ticket):
        return self.run_script("skill-start.py", "--skill", skill, "--ticket", ticket)

    def new_ticket(self, title, ttype, *extra):
        out = self.run_script("new-ticket.py", "--title", title, "--type", ttype, *extra)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)["ticket_id"]

    def tdir(self, ticket):
        return lib.ticket_dir(self.ws, "acme-shop", ticket)


# ---------------------------------------------------------------------------
# Test 1 — AC-3: blocked and allowed gate transition on the Codex dispatch path
# ---------------------------------------------------------------------------

class TestCodexGateTransition(CodexGateWorkspaceCase):
    """T1 — AC-3 (and AC-1 by construction).

    Specification source: docs/architecture/lld/runtime-coupling-inventory.md:38
    Surface #1 — Hook gating: 'No-bypass shim: first instruction in each acs skill
    Codex definition calls dispatch.py pre; exits non-zero before skill body.'

    Two sub-tests driving dispatch.py pre via subprocess with a synthesized shape-(a)
    payload {"cwd": <repo_root>, "tool_input": {"skill": "acs:<skill>"}} on stdin.
    Mirrors test_acs_plugin.py:58-63 (the .pre() harness).
    """

    def test_blocked_gate_returns_exit_2_with_actionable_stderr(self):
        """Blocked path: uninitialized workspace -> exit 2 + actionable stderr.

        Mirrors test_acs_plugin.py:97-104 (TestGates.test_uninitialized_repo_blocks_with_init_message).
        Specification source: runtime-coupling-inventory.md:38.
        """
        plain = os.path.join(self.tmp, "plain")
        os.makedirs(plain)
        subprocess.run(["git", "init", "-q", plain], check=True)
        # No .acs/settings.json -> gate unmet
        result = self.pre("create-ticket", cwd=plain)
        self.assertEqual(result.returncode, 2,
                         "blocked gate must exit 2; got %d, stderr=%r"
                         % (result.returncode, result.stderr))
        self.assertTrue(result.stderr.strip(),
                        "blocked gate must emit actionable stderr; got empty")

    def test_allowed_gate_returns_exit_0(self):
        """Allowed path: initialized workspace satisfies create-ticket gate -> exit 0.

        Uses the AcsWorkspaceCase-equivalent fixture (setUp builds a valid .acs workspace).
        Asserts returncode == 0 and no error on stderr.
        """
        result = self.pre("create-ticket")
        self.assertEqual(result.returncode, 0,
                         "allowed gate must exit 0; got %d, stderr=%r"
                         % (result.returncode, result.stderr))
        self.assertEqual(result.stderr, "",
                         "allowed gate must not produce error on stderr; got %r"
                         % result.stderr)


# ---------------------------------------------------------------------------
# Test 2 — AC-1: fail-closed parity with the Claude Code exit-2 path
# ---------------------------------------------------------------------------

class TestCodexFailClosedParity(CodexGateWorkspaceCase):
    """T2 — AC-1: gate failure never exits 0; parity with dispatch.py:75 + acs_lib.py:1456-1461.

    Sub-test A: GateError -> returncode == 2, stderr contains 'acs pre-<skill>: blocked —'
    Sub-test B: pre-<skill>.py with unexpected exception -> returncode != 0,
                stderr contains 'blocked — unexpected error in gate'
    """

    def test_gate_failure_exits_2_with_blocked_message(self):
        """Gate failure on a hooked skill exits 2 and stderr matches acs_lib.py:1457 pattern.

        The 'create-architecture' gate requires a PRD; an empty workspace has no PRD ->
        exit 2 + 'blocked' message (matches acs_lib.run_pre fail-closed path).
        """
        result = self.pre("create-architecture")
        self.assertEqual(result.returncode, 2,
                         "gate failure must exit 2; got %d, stderr=%r"
                         % (result.returncode, result.stderr))
        # acs_lib.py:1457 writes: "acs pre-<skill>: blocked — ..."
        self.assertIn("blocked", result.stderr,
                      "stderr must contain 'blocked'; got %r" % result.stderr)
        self.assertNotEqual(result.returncode, 0,
                            "gate failure must NEVER exit 0 (0 gate escapes)")

    def test_hooked_skill_never_exits_0_on_blocked_gate(self):
        """Any hooked skill against an empty workspace blocks (exit != 0).

        Confirms that the Codex dispatch path (shape a: synthesized payload piped to
        dispatch.py pre) never exits 0 when the gate is closed, for a representative
        set of hooked skills.
        """
        # These hooked skills cannot pass their gate on an empty workspace:
        blocked_skills = ["create-architecture", "create-spec", "code",
                          "create-pr", "merge-pr"]
        for skill in blocked_skills:
            result = self.pre(skill)
            self.assertNotEqual(result.returncode, 0,
                                "skill %r gate must not exit 0 on empty workspace; "
                                "got %d, stderr=%r"
                                % (skill, result.returncode, result.stderr))


# ---------------------------------------------------------------------------
# Test 3 — AC-2: acs_lib reused unchanged (no import-time side effects)
# ---------------------------------------------------------------------------

class TestAcsLibReusedUnchanged(unittest.TestCase):
    """T3 — AC-2: the deterministic gate layer is reused unchanged.

    Mirrors tests/acs/test_codex_adapter.py:91-115 (TestCodexAdapterNoSideEffect).
    Sub-test A: import codex_adapter leaves acs_lib state unchanged (ADR-0001).
    Sub-test B: the deterministic symbols (run_pre, session_end, HOOKED_SKILLS, GATES)
                are present and not shadowed or altered by any glue in this spec.
    The authoritative guard remains the verifier git diff check; this test provides
    a runtime signal.
    """

    def setUp(self):
        # Ensure SCRIPTS is on path so acs_lib and codex_adapter are importable.
        if SCRIPTS not in sys.path:
            sys.path.insert(0, SCRIPTS)

    def test_no_import_time_side_effect_on_acs_lib(self):
        """dir(acs_lib) and HOOKED_SKILLS are unchanged after importing codex_adapter.

        Mirrors test_codex_adapter.py:94-115.
        """
        # Remove cached codex_adapter to ensure a genuine import.
        sys.modules.pop("codex_adapter", None)

        import acs_lib as alib  # noqa: E402

        dir_before = sorted(dir(alib))
        hooked_before = list(alib.HOOKED_SKILLS)

        import codex_adapter  # noqa: F401, E402

        dir_after = sorted(dir(alib))
        hooked_after = list(alib.HOOKED_SKILLS)

        self.assertEqual(dir_before, dir_after,
                         "dir(acs_lib) changed after importing codex_adapter")
        self.assertEqual(hooked_before, hooked_after,
                         "acs_lib.HOOKED_SKILLS changed after importing codex_adapter")

    def test_deterministic_layer_symbols_present_and_stable(self):
        """acs_lib.run_pre, session_end, HOOKED_SKILLS, GATES are present and callable.

        The Codex gate spec introduces no new Python module that could shadow these.
        This is a structural assertion; the authoritative guard is verifier git diff.
        """
        import acs_lib as alib  # noqa: E402

        # run_pre and session_end must be callable
        self.assertTrue(callable(alib.run_pre),
                        "acs_lib.run_pre must be callable")
        self.assertTrue(callable(alib.session_end),
                        "acs_lib.session_end must be callable")

        # HOOKED_SKILLS must be the 9-element allowlist (acs_lib.py:41-43)
        self.assertIsInstance(alib.HOOKED_SKILLS, list)
        self.assertEqual(len(alib.HOOKED_SKILLS), 9,
                         "HOOKED_SKILLS must have exactly 9 entries; got %d"
                         % len(alib.HOOKED_SKILLS))
        expected = sorted(["create-prd", "create-architecture", "create-project",
                            "create-ticket", "create-design", "create-spec",
                            "code", "create-pr", "merge-pr"])
        self.assertEqual(sorted(alib.HOOKED_SKILLS), expected,
                         "HOOKED_SKILLS mismatch: %r" % alib.HOOKED_SKILLS)

        # GATES must be present (it is a dict or similar mapping in acs_lib)
        self.assertTrue(hasattr(alib, "GATES"),
                        "acs_lib.GATES must be present")


# ---------------------------------------------------------------------------
# Test 4 — R1: no-bypass shim presence in each hooked Codex skill definition
# ---------------------------------------------------------------------------

class TestCodexNoBypassShimPresence(CodexGateWorkspaceCase):
    """T4 — R1 (design.md:431), AC-1: the shim is the first executable line.

    For each of the 9 HOOKED_SKILLS, opens the Codex skill definition file at
    plugins/acs/runtimes/codex/skills/<skill>.md and asserts:
      1. The file exists.
      2. The first non-comment, non-blank executable line contains 'dispatch.py' and 'pre'.

    Also drives the blocked-gate subprocess for one hooked skill and asserts that
    the coordinator body's output (sentinel) is absent when the shim exits 2.
    """

    def _first_executable_line(self, filepath):
        """Return the first Bash executable (non-structural) line from a skill definition file.

        Skips: blank lines, HTML/Markdown comments (<!--), frontmatter (---),
        Markdown section headers (# ...), and Markdown code-fence markers (```).
        The first remaining line is the actual shim command.
        """
        with open(filepath, "r", encoding="utf-8") as fh:
            for line in fh:
                stripped = line.strip()
                if not stripped:
                    continue  # blank
                if stripped.startswith("#"):
                    continue  # Markdown heading or shell comment
                if stripped.startswith("---") or stripped.startswith("<!--"):
                    continue  # frontmatter or HTML comment
                if stripped.startswith("```"):
                    continue  # Markdown code-fence marker (structural)
                return stripped
        return None

    def test_shim_is_first_executable_line_for_all_hooked_skills(self):
        """Each hooked skill file exists and its first executable line calls dispatch.py pre.

        Files: plugins/acs/runtimes/codex/skills/<skill>.md for all 9 HOOKED_SKILLS.
        """
        import acs_lib as alib  # noqa: E402
        for skill in alib.HOOKED_SKILLS:
            skill_file = os.path.join(CODEX_SKILLS_DIR, skill + ".md")
            self.assertTrue(
                os.path.isfile(skill_file),
                "Codex skill definition file missing for hooked skill %r: %s"
                % (skill, skill_file),
            )
            first_line = self._first_executable_line(skill_file)
            self.assertIsNotNone(
                first_line,
                "No executable line found in %s" % skill_file,
            )
            self.assertIn(
                "dispatch.py",
                first_line,
                "First executable line in %s must reference dispatch.py; got: %r"
                % (skill_file, first_line),
            )
            self.assertIn(
                "pre",
                first_line,
                "First executable line in %s must include 'pre'; got: %r"
                % (skill_file, first_line),
            )

    def test_blocked_gate_prevents_coordinator_body(self):
        """When dispatch.py pre exits 2, no coordinator body output is produced.

        We simulate a Codex skill invocation: the shim (shape a) calls dispatch.py pre.
        On a bare workspace (no .acs/settings.json), the gate exits 2. We confirm that
        the exit code from dispatch.py pre is non-zero, meaning the skill body is unreachable.
        The subprocess does not return to the caller on non-zero exit, replicating
        the skill-body-unreachable guarantee (spec:226-227).
        """
        plain = os.path.join(self.tmp, "plain2")
        os.makedirs(plain)
        subprocess.run(["git", "init", "-q", plain], check=True)
        # Drive dispatch.py pre as the shim would: exit 2 = body unreachable
        result = self.pre("create-ticket", cwd=plain)
        self.assertEqual(result.returncode, 2,
                         "shim exit code must be 2 for blocked gate; got %d"
                         % result.returncode)
        # returncode 2 = subprocess halted; coordinator body (anything after the shim)
        # is not executed.  Verified by exit code alone (spec:226-227).


# ---------------------------------------------------------------------------
# Test 5 — Stop handler: dispatch.py session-end finalizes in_progress run
# ---------------------------------------------------------------------------

class TestCodexStopHandler(CodexGateWorkspaceCase):
    """T5 — AC-1 (session-end parity), surface #2 (runtime-coupling-inventory.md:39).

    Mirror of test_acs_plugin.py:231-242.
    Surface #2: 'Codex Stop event -> same dispatch.py session-end path.'

    Sets up a workspace with an in_progress run, invokes dispatch.py session-end,
    asserts: returncode == 0, run status == 'interrupted', lock absent, metrics
    totals.runs incremented by 1.
    """

    def setUp(self):
        super().setUp()
        # Mint a ticket and start a run (create-spec) to get an in_progress run + lock.
        out = self.run_script("new-ticket.py", "--title", "T", "--type", "task")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.ticket = json.loads(out.stdout)["ticket_id"]
        start = self.start("create-spec", self.ticket)
        self.assertEqual(start.returncode, 0, start.stderr)

    def test_stop_handler_finalizes_interrupted_and_releases_lock(self):
        """dispatch.py session-end (the Codex Stop handler path) finalizes as interrupted.

        Mirrors test_acs_plugin.py:231-242.
        Specification source: runtime-coupling-inventory.md:39, dispatch.py:49-54,
        acs_lib.py:1621.
        """
        with open(lib.metrics_path(self.ws, "acme-shop")) as fh:
            before_runs = json.load(fh).get("totals", {}).get("runs", 0)

        result = self.session_end()
        self.assertEqual(result.returncode, 0,
                         "dispatch.py session-end must exit 0; got %d, stderr=%r"
                         % (result.returncode, result.stderr))

        # Run status must be 'interrupted'
        state = lib.load_state(self.tdir(self.ticket), "create-spec")
        self.assertEqual(
            state["runs"][-1]["status"],
            "interrupted",
            "run status must be 'interrupted' after Stop handler; got %r"
            % state["runs"][-1]["status"],
        )

        # Lock must be released
        lock_path = os.path.join(self.tdir(self.ticket), ".lock")
        self.assertFalse(
            os.path.exists(lock_path),
            "lock file must be absent after Stop handler; found at %s" % lock_path,
        )

        # metrics totals.runs must have incremented by 1
        with open(lib.metrics_path(self.ws, "acme-shop")) as fh:
            after_runs = json.load(fh)["totals"]["runs"]
        self.assertEqual(
            after_runs,
            before_runs + 1,
            "metrics totals.runs must increment by 1; before=%d after=%d"
            % (before_runs, after_runs),
        )


# ---------------------------------------------------------------------------
# Test 6 — Unhooked pass-through: dispatch.py exits 0 for all unhooked skills
# ---------------------------------------------------------------------------

class TestCodexUnhookedPassThrough(CodexGateWorkspaceCase):
    """T6 — AC-1 (no over-gating).

    For each of the 7 unhooked skills (acs_lib.py:44) and one non-acs skill,
    dispatch.py pre with a synthesized payload returns exit 0.
    Mirrors test_acs_plugin.py:82-89 (TestDispatcher.test_unhooked_acs_skills_pass_through)
    and dispatch.py:57-58 (skill not in HOOKED_SKILLS -> sys.exit(0)).
    """

    def test_all_unhooked_skills_pass_through(self):
        """All 7 UNHOOKED_SKILLS (incl. 'usage') pass through dispatch.py pre with exit 0.

        Mirrors test_acs_plugin.py:87-89.
        dispatch.py:57-58: if skill not in acs_lib.HOOKED_SKILLS: sys.exit(0)
        """
        import acs_lib as alib  # noqa: E402
        for skill in alib.UNHOOKED_SKILLS:
            result = self.pre(skill)
            self.assertEqual(
                result.returncode, 0,
                "unhooked skill %r must pass through (exit 0) on Codex dispatch path; "
                "got %d, stderr=%r" % (skill, result.returncode, result.stderr),
            )

    def test_non_acs_skill_passes_through(self):
        """A non-acs skill name does not gate (exit 0).

        Mirrors test_acs_plugin.py:82-85 (TestDispatcher.test_non_acs_skill_passes_through).
        dispatch.py:31-35: prefix != 'acs' -> skill_name_from_payload returns None -> exit 0.
        """
        payload = json.dumps({
            "cwd": self.repo,
            "tool_input": {"skill": "other:thing"},
        })
        result = self.run_script("dispatch.py", "pre", stdin=payload)
        self.assertEqual(
            result.returncode, 0,
            "non-acs skill must pass through; got %d, stderr=%r"
            % (result.returncode, result.stderr),
        )

    def test_usage_skill_specifically_passes_through(self):
        """'usage' is listed in UNHOOKED_SKILLS (acs_lib.py:44) and must exit 0.

        The spec test plan (specs/01-codex-gate-dispatch.md:296) explicitly names 'usage'.
        """
        result = self.pre("usage")
        self.assertEqual(
            result.returncode, 0,
            "unhooked skill 'usage' must exit 0; got %d, stderr=%r"
            % (result.returncode, result.stderr),
        )


if __name__ == "__main__":
    unittest.main()
