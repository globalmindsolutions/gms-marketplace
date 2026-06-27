"""Tests for codex_adapter.py — the thin --runtime flag scaffold (MAR-4 Spec 02).

Five test cases covering:
  T1  explicit --runtime codex   -> "codex"
  T2  explicit --runtime claude-code -> "claude-code"
  T3  absent --runtime            -> "claude-code" (ADR-0027 back-compat)
  T4  invalid --runtime value     -> argparse SystemExit code 2, stderr "invalid choice"
  T5  importing codex_adapter     -> no change to acs_lib state (ADR-0001 invariant)

Run: python3 -m unittest discover -s tests -v
"""

import os
import subprocess
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(REPO_ROOT, "plugins", "acs", "hooks", "scripts")

# Insert SCRIPTS so we can import codex_adapter and acs_lib directly.
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)


class TestCodexAdapterResolveRuntime(unittest.TestCase):
    """T1, T2, T3, T4: resolve_runtime() public API and CLI contract."""

    def setUp(self):
        # Import fresh each test; codex_adapter must not be cached from a previous
        # import in a different test class's setUp (T5 imports it under trace).
        import codex_adapter  # noqa: F401 — imported for side-effect check
        self.adapter = sys.modules["codex_adapter"]

    # T1 — explicit codex
    def test_explicit_codex_runtime(self):
        """resolve_runtime(["--runtime","codex"]) returns "codex"; CLI exits 0 with "codex\n"."""
        result = self.adapter.resolve_runtime(["--runtime", "codex"])
        self.assertEqual(result, "codex")

        cli = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "codex_adapter.py"), "--runtime", "codex"],
            capture_output=True, text=True,
        )
        self.assertEqual(cli.returncode, 0)
        self.assertEqual(cli.stdout, "codex\n")

    # T2 — explicit claude-code
    def test_explicit_claude_code_runtime(self):
        """resolve_runtime(["--runtime","claude-code"]) returns "claude-code"; CLI exits 0."""
        result = self.adapter.resolve_runtime(["--runtime", "claude-code"])
        self.assertEqual(result, "claude-code")

        cli = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "codex_adapter.py"), "--runtime", "claude-code"],
            capture_output=True, text=True,
        )
        self.assertEqual(cli.returncode, 0)
        self.assertEqual(cli.stdout, "claude-code\n")

    # T3 — absent --runtime defaults to claude-code (ADR-0027 back-compat)
    def test_absent_runtime_defaults_to_claude_code(self):
        """resolve_runtime([]) returns "claude-code"; CLI (no args) exits 0 with "claude-code\\n"."""
        result = self.adapter.resolve_runtime([])
        self.assertEqual(result, "claude-code")

        cli = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "codex_adapter.py")],
            capture_output=True, text=True,
        )
        self.assertEqual(cli.returncode, 0)
        self.assertEqual(cli.stdout, "claude-code\n")

    # T4 — invalid value -> SystemExit code 2, stderr "invalid choice"
    def test_invalid_runtime_value_exits_nonzero(self):
        """resolve_runtime(["--runtime","bogus"]) raises SystemExit non-zero; CLI exits 2."""
        # Function call must raise SystemExit with non-zero code.
        with self.assertRaises(SystemExit) as cm:
            self.adapter.resolve_runtime(["--runtime", "bogus"])
        self.assertNotEqual(cm.exception.code, 0)

        # CLI must exit 2 and write "invalid choice" to stderr.
        cli = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "codex_adapter.py"), "--runtime", "bogus"],
            capture_output=True, text=True,
        )
        self.assertEqual(cli.returncode, 2)
        self.assertIn("invalid choice", cli.stderr)


class TestCodexAdapterNoSideEffect(unittest.TestCase):
    """T5: importing codex_adapter leaves acs_lib state entirely untouched (ADR-0001)."""

    def test_no_import_time_side_effect_on_acs_lib(self):
        """dir(acs_lib) and acs_lib.HOOKED_SKILLS are unchanged after importing codex_adapter."""
        # Remove any cached codex_adapter so the import is genuine.
        sys.modules.pop("codex_adapter", None)

        import acs_lib as lib  # noqa: E402

        # Record state before.
        dir_before = sorted(dir(lib))
        hooked_before = list(lib.HOOKED_SKILLS)

        # Import codex_adapter — the ADR-0001 invariant requires zero side effects on lib.
        import codex_adapter  # noqa: F401

        # Assert state is unchanged.
        dir_after = sorted(dir(lib))
        hooked_after = list(lib.HOOKED_SKILLS)

        self.assertEqual(dir_before, dir_after,
                         "dir(acs_lib) changed after importing codex_adapter")
        self.assertEqual(hooked_before, hooked_after,
                         "acs_lib.HOOKED_SKILLS changed after importing codex_adapter")


if __name__ == "__main__":
    unittest.main()
