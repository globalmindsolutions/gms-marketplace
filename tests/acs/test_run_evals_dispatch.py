"""Unit tests for the per-plugin dispatcher in evals/run_evals.py.

TDD surface: plugin-name → registry-path resolution and skills-only banner-gate
tolerance. Driven as subprocesses (mirrors tests/acs/test_run_tests.py) so
sys.path mutation in run_evals.py does not leak into the unittest process.

Run:  python3 -m unittest discover -s tests -v
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RUN_EVALS = os.path.join(REPO_ROOT, "evals", "run_evals.py")


class DispatchAcsPluginTest(unittest.TestCase):
    """--plugin acs routes to evals/acs/scenarios/SCENARIOS (5 entries)."""

    def test_plugin_acs_list_shows_five_scenarios(self):
        """--plugin acs --list must list exactly 5 scenarios without import error."""
        result = subprocess.run(
            [sys.executable, RUN_EVALS, "--plugin", "acs", "--list"],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            env={"ACS_EVAL_SOURCE": "1", **os.environ},
        )
        self.assertEqual(result.returncode, 0,
                         "run_evals.py --plugin acs --list exited non-zero: "
                         + result.stderr)
        lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
        self.assertEqual(
            len(lines), 5,
            "Expected 5 scenario lines, got %d:\n%s" % (len(lines), result.stdout),
        )

    def test_plugin_acs_list_scenario_names(self):
        """The 5 acs scenario names appear in --list output."""
        result = subprocess.run(
            [sys.executable, RUN_EVALS, "--plugin", "acs", "--list"],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            env={"ACS_EVAL_SOURCE": "1", **os.environ},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        for name in (
            "install_gate_smoke",
            "create_ticket_artifacts",
            "resume_and_verify",
            "skill_triggers",
            "session_end",
        ):
            self.assertIn(name, result.stdout,
                          "Scenario '%s' missing from --list output" % name)


class SkillsOnlyPluginTest(unittest.TestCase):
    """A plugin with SCENARIOS=[] (no Sandbox, no hooks) exits 0, 0 scenarios,
    no acs cache lookup, no hard-fail, no banner."""

    def setUp(self):
        # Drive a COPY of the eval tree from a tmp dir so the skills-only
        # fixture never touches the tracked repo evals/ (C-3).
        self.tmp = tempfile.mkdtemp(prefix="acs-eval-skillsonly-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.evals_dir = os.path.join(self.tmp, "evals")
        shutil.copytree(
            os.path.join(REPO_ROOT, "evals"),
            self.evals_dir,
            ignore=shutil.ignore_patterns("__pycache__"),
        )
        self.plugin_name = "TESTPLUGIN"
        scenarios_dir = os.path.join(self.evals_dir, self.plugin_name, "scenarios")
        os.makedirs(scenarios_dir)
        with open(os.path.join(scenarios_dir, "__init__.py"), "w") as fh:
            fh.write("SCENARIOS = []\n")
        self.run_evals = os.path.join(self.evals_dir, "run_evals.py")

    def _run_list(self):
        return subprocess.run(
            [sys.executable, self.run_evals, "--plugin", self.plugin_name, "--list"],
            capture_output=True,
            text=True,
            cwd=self.evals_dir,
            env=dict(os.environ),  # no ACS_EVAL_SOURCE; skills-only path
        )

    def test_skills_only_list_exits_zero(self):
        """Skills-only --plugin --list must exit 0 (no hard-fail)."""
        result = self._run_list()
        self.assertEqual(result.returncode, 0,
                         "skills-only --list exited non-zero.\nstderr: "
                         + result.stderr)

    def test_skills_only_list_zero_scenarios(self):
        """Skills-only --plugin --list must print 0 scenario lines."""
        result = self._run_list()
        lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
        self.assertEqual(
            len(lines), 0,
            "Expected 0 scenario lines for skills-only plugin, got %d:\n%s"
            % (len(lines), result.stdout),
        )

    def test_skills_only_no_banner(self):
        """Skills-only --plugin must not print the acs 'plugin build under test' banner."""
        result = self._run_list()
        self.assertNotIn(
            "plugin build under test",
            result.stdout + result.stderr,
            "Banner appeared for skills-only plugin (acs cache lookup must be gated)",
        )

    def test_skills_only_no_installed_scripts_dir_error(self):
        """Skills-only --plugin must not hard-fail due to missing acs install."""
        # If installed_scripts_dir() were called unconditionally, it would attempt
        # to glob the acs cache; in a clean environment with ACS_EVAL_SOURCE unset
        # it falls back to SOURCE_SCRIPTS (never hard-fails), but we verify the
        # banner text is absent (the call itself is gated) to prove the code path.
        result = self._run_list()
        # Primary check: no error exit
        self.assertEqual(result.returncode, 0, result.stderr)
        # Secondary check: no acs-specific banner
        self.assertNotIn("plugin build under test",
                         result.stdout + result.stderr)


class FlagCarryOverTest(unittest.TestCase):
    """--paid, --forge, --only, --keep, --list all parse without error."""

    def test_all_flags_parse(self):
        """Arg-parse must not error with all flags present."""
        result = subprocess.run(
            [sys.executable, RUN_EVALS,
             "--plugin", "acs",
             "--list",
             "--paid",
             "--forge",
             "--only", "install_gate_smoke",
             "--keep"],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            env={"ACS_EVAL_SOURCE": "1", **os.environ},
        )
        # --list returns before any scenario runs so we expect 0
        self.assertEqual(result.returncode, 0,
                         "Flag carry-over parse failed:\n" + result.stderr)


if __name__ == "__main__":
    unittest.main()
