"""Unit tests for the per-plugin dispatcher in evals/run_evals.py.

TDD surface: plugin-name → per-plugin-runner dispatch (subprocess delegation),
flag forwarding to evals/<plugin>/run_evals.py, non-zero exit propagation, and
skills-only banner-gate tolerance. Driven as subprocesses (mirrors
tests/acs/test_run_tests.py) so sys.path mutation in run_evals.py does not leak
into the unittest process.

Run:  python3 -m unittest discover -s tests -v
"""

import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RUN_EVALS = os.path.join(REPO_ROOT, "evals", "run_evals.py")


class DispatchAcsPluginTest(unittest.TestCase):
    """--plugin acs routes to evals/acs/run_evals.py which lists 7 scenarios."""

    def test_plugin_acs_list_shows_six_scenarios(self):
        """--plugin acs --list must list exactly 7 scenarios without import error."""
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
            len(lines), 7,
            "Expected 7 scenario lines, got %d:\n%s" % (len(lines), result.stdout),
        )

    def test_plugin_acs_list_scenario_names(self):
        """The 7 acs scenario names appear in --list output."""
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
            "update_migration",
            "fanout_tracker_sync",
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
        plugin_dir = os.path.join(self.evals_dir, self.plugin_name)
        scenarios_dir = os.path.join(plugin_dir, "scenarios")
        os.makedirs(scenarios_dir)
        with open(os.path.join(scenarios_dir, "__init__.py"), "w") as fh:
            fh.write("SCENARIOS = []\n")
        # Fabricate a minimal per-plugin runner for TESTPLUGIN.
        # The thin dispatcher resolves evals/TESTPLUGIN/run_evals.py and
        # delegates to it — without this file the dispatcher exits 1 (missing
        # runner), which would fail the skills-only tolerance tests.
        # This runner:
        #   - inserts its own dir on sys.path so `import scenarios` resolves
        #   - accepts --list and all forwarded flags without argparse error
        #   - prints 0 scenario lines and exits 0
        #   - does NOT import harness / installed_scripts_dir
        #   - does NOT print "plugin build under test"
        runner_code = textwrap.dedent("""\
            import argparse
            import importlib
            import os
            import sys

            _dir = os.path.dirname(os.path.abspath(__file__))
            sys.path.insert(0, _dir)

            def main():
                ap = argparse.ArgumentParser()
                ap.add_argument("--plugin", default="TESTPLUGIN")
                ap.add_argument("--paid", action="store_true")
                ap.add_argument("--forge", action="store_true")
                ap.add_argument("--only", action="append", metavar="NAME")
                ap.add_argument("--keep", action="store_true")
                ap.add_argument("--list", action="store_true")
                args = ap.parse_args()

                if "scenarios" in sys.modules:
                    del sys.modules["scenarios"]
                scenarios_mod = importlib.import_module("scenarios")
                scenarios = getattr(scenarios_mod, "SCENARIOS", [])

                if args.list:
                    for mod in scenarios:
                        m = mod.META
                        print("%-28s %-6s %-4s  %s" % (
                            m["name"], m["tier"], m["goal"], m["summary"]))
                    return 0

                failed = []
                for mod in scenarios:
                    try:
                        check = mod.run()
                    except Exception as exc:
                        failed.append(mod.META["name"])
                        continue
                    if not check.passed:
                        failed.append(mod.META["name"])

                if not scenarios:
                    print("no scenarios selected (free tier is default; use --paid).")
                    return 0

                print("-" * 60)
                print("scenarios: %d run, %d failed" % (len(scenarios), len(failed)))
                if failed:
                    return 1
                print("all passed.")
                return 0

            if __name__ == "__main__":
                sys.exit(main())
        """)
        with open(os.path.join(plugin_dir, "run_evals.py"), "w") as fh:
            fh.write(runner_code)
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


class ExitCodePropagationTest(unittest.TestCase):
    """Non-zero exit from a per-plugin runner is preserved through the dispatcher (AC-3)."""

    def setUp(self):
        # Create a tmp evals tree with a FAILPLUGIN whose runner always exits 1.
        self.tmp = tempfile.mkdtemp(prefix="acs-eval-exitprop-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.evals_dir = os.path.join(self.tmp, "evals")
        shutil.copytree(
            os.path.join(REPO_ROOT, "evals"),
            self.evals_dir,
            ignore=shutil.ignore_patterns("__pycache__"),
        )
        self.plugin_name = "FAILPLUGIN"
        plugin_dir = os.path.join(self.evals_dir, self.plugin_name)
        os.makedirs(plugin_dir)
        # A minimal runner that unconditionally exits 1.
        runner_code = textwrap.dedent("""\
            import sys
            if __name__ == "__main__":
                sys.exit(1)
        """)
        with open(os.path.join(plugin_dir, "run_evals.py"), "w") as fh:
            fh.write(runner_code)
        self.run_evals = os.path.join(self.evals_dir, "run_evals.py")

    def test_nonzero_exit_propagates(self):
        """A failing per-plugin runner must produce a non-zero exit through the dispatcher."""
        result = subprocess.run(
            [sys.executable, self.run_evals, "--plugin", self.plugin_name],
            capture_output=True,
            text=True,
            cwd=self.evals_dir,
            env=dict(os.environ),
        )
        self.assertNotEqual(
            result.returncode, 0,
            "Dispatcher swallowed non-zero exit from FAILPLUGIN runner "
            "(returncode was 0, expected != 0)",
        )

    def test_missing_plugin_exits_nonzero(self):
        """A missing per-plugin runner must produce a non-zero exit and a clear stderr message."""
        result = subprocess.run(
            [sys.executable, RUN_EVALS, "--plugin", "nosuchplugin"],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            env=dict(os.environ),
        )
        self.assertNotEqual(result.returncode, 0,
                            "Dispatcher exited 0 for a missing plugin (expected != 0)")
        self.assertIn("nosuchplugin", result.stderr,
                      "Expected plugin name in stderr error message")


if __name__ == "__main__":
    unittest.main()
