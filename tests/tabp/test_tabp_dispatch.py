"""Dispatch and gating tests for the evals/tabp behavioral eval subtree.

Tests the routing of ``python3 evals/run_evals.py --plugin tabp`` to
``evals/tabp/run_evals.py``, the tier gate (default no --paid = no model call),
the --list output, the acs regression (5 scenarios still listed), the
import-clean constraint (no module-scope openpyxl), the fixture presence and
synthetic-data assertions, and the pre-commit exclusion.

Run:  python3 -m unittest discover -s tests -v
      python3 -m unittest tests.tabp.test_tabp_dispatch -v
"""

import os
import re
import subprocess
import sys
import unittest

# REPO_ROOT: dirname x3 from tests/tabp/test_tabp_dispatch.py
# tests/tabp/test_tabp_dispatch.py -> tests/tabp/ -> tests/ -> repo root
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RUN_EVALS = os.path.join(REPO_ROOT, "evals", "run_evals.py")
FIXTURES_DIR = os.path.join(REPO_ROOT, "evals", "tabp", "fixtures")

_ENV = {"ACS_EVAL_SOURCE": "1", **os.environ}


def _run(*args, env=None):
    """Run a command as a subprocess and return the CompletedProcess."""
    return subprocess.run(
        list(args),
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env=env if env is not None else _ENV,
    )


class TabpDispatchTest(unittest.TestCase):
    """Deterministic routing + gate + fixture + pre-commit exclusion assertions.

    All subprocess calls use cwd=REPO_ROOT and env={"ACS_EVAL_SOURCE": "1",
    **os.environ}, mirroring tests/acs/test_run_evals_dispatch.py line 34.
    No model call is made; these tests are free-tier CI-safe.
    """

    # ------------------------------------------------------------------
    # AC7 — routing
    # ------------------------------------------------------------------

    def test_plugin_tabp_list_exits_zero(self):
        """python3 evals/run_evals.py --plugin tabp --list must exit 0."""
        result = _run(sys.executable, RUN_EVALS, "--plugin", "tabp", "--list")
        self.assertEqual(
            result.returncode, 0,
            "run_evals.py --plugin tabp --list exited non-zero.\nstderr: "
            + result.stderr,
        )

    def test_plugin_tabp_list_one_scenario(self):
        """--plugin tabp --list must print exactly 1 non-empty line."""
        result = _run(sys.executable, RUN_EVALS, "--plugin", "tabp", "--list")
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
        self.assertEqual(
            len(lines), 1,
            "Expected exactly 1 scenario line for --plugin tabp --list, "
            "got %d:\n%s" % (len(lines), result.stdout),
        )

    def test_plugin_tabp_list_scenario_name(self):
        """'screen_cvs_eval' must appear in --plugin tabp --list stdout."""
        result = _run(sys.executable, RUN_EVALS, "--plugin", "tabp", "--list")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "screen_cvs_eval",
            result.stdout,
            "screen_cvs_eval missing from --plugin tabp --list output:\n"
            + result.stdout,
        )

    # ------------------------------------------------------------------
    # AC7 — acs unaffected regression
    # ------------------------------------------------------------------

    def test_plugin_acs_unaffected_six_scenarios(self):
        """--plugin acs --list must still exit 0 and list exactly 7 scenarios."""
        result = _run(sys.executable, RUN_EVALS, "--plugin", "acs", "--list")
        self.assertEqual(
            result.returncode, 0,
            "run_evals.py --plugin acs --list exited non-zero after tabp addition.\n"
            "stderr: " + result.stderr,
        )
        lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
        self.assertEqual(
            len(lines), 7,
            "Expected 7 acs scenario lines, got %d:\n%s" % (len(lines), result.stdout),
        )

    # ------------------------------------------------------------------
    # AC6, AC8 — import clean (no module-scope openpyxl)
    # ------------------------------------------------------------------

    def test_tabp_import_clean(self):
        """Importing evals.tabp.scenarios.screen_cvs_eval must not raise.

        Proves no module-scope openpyxl / Cowork import exists (openpyxl is
        absent in this stdlib-only repo; a module-scope import would raise
        ModuleNotFoundError immediately).

        The subprocess runs with cwd=REPO_ROOT so sys.path.insert(0, os.getcwd())
        resolves the repo root, making ``evals.tabp`` importable as a package.
        """
        # Use os.getcwd() inside the -c script — __file__ is undefined in -c mode.
        result = _run(
            sys.executable,
            "-c",
            (
                "import sys, os; sys.path.insert(0, os.getcwd()); "
                "import evals.tabp; "
                "import evals.tabp.scenarios; "
                "import evals.tabp.scenarios.screen_cvs_eval"
            ),
        )
        self.assertEqual(
            result.returncode, 0,
            "Importing evals.tabp modules raised an error — likely a module-scope "
            "openpyxl or missing-module import.\nstdout: %s\nstderr: %s"
            % (result.stdout, result.stderr),
        )

    # ------------------------------------------------------------------
    # AC6, AC8 — default run (no --paid) makes no model call
    # ------------------------------------------------------------------

    def test_tabp_default_no_model_call(self):
        """python3 evals/run_evals.py --plugin tabp (no --paid) must exit 0.

        The default free-tier run must not invoke any model and must print the
        'no scenarios selected' message (the paid gate applies to screen_cvs_eval
        whose tier is 'paid').
        """
        result = _run(sys.executable, RUN_EVALS, "--plugin", "tabp")
        self.assertEqual(
            result.returncode, 0,
            "--plugin tabp (no --paid) exited non-zero.\nstderr: " + result.stderr,
        )
        # Must NOT contain any marker of a model being called.
        no_model_markers = ["claude", "invoking", "calling model", "model call"]
        combined = (result.stdout + result.stderr).lower()
        for marker in no_model_markers:
            self.assertNotIn(
                marker,
                combined,
                "Model-call marker %r appeared in output of default (no --paid) run:\n"
                "stdout: %s\nstderr: %s" % (marker, result.stdout, result.stderr),
            )
        # Must contain the no-scenarios-selected message
        self.assertIn(
            "no scenarios selected",
            result.stdout,
            "Expected 'no scenarios selected' message in default run stdout.\n"
            "stdout: " + result.stdout,
        )

    # ------------------------------------------------------------------
    # AC6, AC8 — fixtures exist
    # ------------------------------------------------------------------

    def test_tabp_fixtures_exist(self):
        """Both synthetic fixture files must exist under evals/tabp/fixtures/."""
        cv_path = os.path.join(FIXTURES_DIR, "cv_synthetic.md")
        jd_path = os.path.join(FIXTURES_DIR, "jd_synthetic.md")
        self.assertTrue(
            os.path.isfile(cv_path),
            "CV fixture missing: " + cv_path,
        )
        self.assertTrue(
            os.path.isfile(jd_path),
            "JD fixture missing: " + jd_path,
        )

    def test_tabp_fixtures_no_real_email(self):
        """Fixture files must contain no real-looking email addresses (AC8 / NFR security).

        Checks for @gmail.com, @yahoo.com, @hotmail.com and generic real-domain
        email patterns to ensure no real candidate PII is present.
        """
        cv_path = os.path.join(FIXTURES_DIR, "cv_synthetic.md")
        jd_path = os.path.join(FIXTURES_DIR, "jd_synthetic.md")

        # Patterns that would indicate real PII
        real_email_patterns = [
            r"@gmail\.com",
            r"@yahoo\.com",
            r"@hotmail\.com",
            r"@outlook\.com",
            r"@icloud\.com",
            # Generic real-looking personal email: word@word.tld where tld is a
            # common 2-3 letter extension (not .example or .test)
            r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.(com|net|org|io|co)\b",
        ]
        # Allowlisted synthetic/placeholder patterns that are NOT PII
        allowlisted = re.compile(
            r"@example\.(com|org|net|test)|@synthetic\.|@fictional\.|@tabp\.",
            re.IGNORECASE,
        )

        for path in (cv_path, jd_path):
            if not os.path.isfile(path):
                self.skipTest("Fixture %s not found; skipping email check." % path)
            with open(path) as fh:
                content = fh.read()
            for pattern in real_email_patterns:
                for match in re.finditer(pattern, content, re.IGNORECASE):
                    matched_text = match.group(0)
                    if allowlisted.search(matched_text):
                        continue
                    self.fail(
                        "Real-looking email %r found in %s — fixtures must use "
                        "synthetic data only (AC8)." % (matched_text, path)
                    )

    # ------------------------------------------------------------------
    # AC8 — pre-commit does not invoke tabp runner
    # ------------------------------------------------------------------

    def test_precommit_does_not_invoke_tabp(self):
        """No line in .pre-commit-config.yaml must contain both 'run_evals' and 'tabp'.

        The existing acs-free-evals entry pins --plugin acs; the tabp eval is
        excluded from the pre-commit free-eval smoke by design (AC8).
        """
        precommit_path = os.path.join(REPO_ROOT, ".pre-commit-config.yaml")
        self.assertTrue(
            os.path.isfile(precommit_path),
            ".pre-commit-config.yaml not found at " + precommit_path,
        )
        with open(precommit_path) as fh:
            lines = fh.readlines()
        for i, line in enumerate(lines, 1):
            if "run_evals" in line and "tabp" in line:
                self.fail(
                    ".pre-commit-config.yaml line %d contains both 'run_evals' "
                    "and 'tabp', meaning the tabp runner would be invoked by "
                    "pre-commit (violates AC8):\n  %s" % (i, line.rstrip())
                )


if __name__ == "__main__":
    unittest.main()
