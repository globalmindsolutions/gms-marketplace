"""Unit tests for the tests+coverage CI runner /acs:init ships into consumer repos.

run-tests.py (plugins/acs/templates/ci/run-tests.py) runs in the consumer's CI
with ZERO acs dependencies — stdlib only. It reads `tests.command` from the
committed `.acs/settings.json`, exports `ACS_COVERAGE` (= test_coverage_percent),
runs optional `setup` then the command, and exits with the command's status.
These tests drive it as a subprocess in throwaway repos.

Run:  python3 -m unittest discover -s tests -v
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RUNNER = os.path.join(REPO_ROOT, "plugins", "acs", "templates", "ci", "run-tests.py")


class RunTestsCase(unittest.TestCase):
    def run_in(self, settings=None):
        tmp = tempfile.mkdtemp(prefix="acs-runtests-")
        self.addCleanup(shutil.rmtree, tmp, True)
        if settings is not None:
            os.makedirs(os.path.join(tmp, ".acs"))
            with open(os.path.join(tmp, ".acs", "settings.json"), "w") as fh:
                json.dump(settings, fh)
        return subprocess.run([sys.executable, RUNNER], cwd=tmp,
                              capture_output=True, text=True)

    def test_passes_and_exports_coverage(self):
        out = self.run_in({"test_coverage_percent": 85,
                           "tests": {"command": 'test "$ACS_COVERAGE" = 85'}})
        self.assertEqual(out.returncode, 0, out.stderr)

    def test_default_coverage_when_unset(self):
        out = self.run_in({"tests": {"command": 'test "$ACS_COVERAGE" = 90'}})
        self.assertEqual(out.returncode, 0, out.stderr)

    def test_command_failure_fails(self):
        out = self.run_in({"tests": {"command": "exit 3"}})
        self.assertEqual(out.returncode, 1)
        self.assertIn("failed", out.stderr)

    def test_missing_command_errors(self):
        out = self.run_in({"test_coverage_percent": 90})
        self.assertEqual(out.returncode, 1)
        self.assertIn("tests.command", out.stderr)

    def test_missing_settings_errors(self):
        out = self.run_in(None)
        self.assertEqual(out.returncode, 1)
        self.assertIn("settings.json", out.stderr)

    def test_setup_runs_before_command(self):
        out = self.run_in({"tests": {"setup": "echo ok > marker",
                                     "command": "test -f marker"}})
        self.assertEqual(out.returncode, 0, out.stderr)

    def test_setup_failure_fails(self):
        out = self.run_in({"tests": {"setup": "exit 4", "command": "true"}})
        self.assertEqual(out.returncode, 1)
        self.assertIn("setup failed", out.stderr)


if __name__ == "__main__":
    unittest.main()
