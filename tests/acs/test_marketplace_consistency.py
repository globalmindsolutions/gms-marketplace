"""Regression tests for the 'Validate marketplace/plugin version consistency' step in ci.yml.

Mechanism: EXTRACT-AND-RUN (C-2 option A).
  In setUpClass, the ci.yml heredoc body for the consistency-validator step is
  extracted by locating the 'Validate marketplace/plugin version consistency' step,
  slicing the lines between the opening <<'EOF' marker and the matching EOF, and
  DEDENTING them.  The dedented body is written to a temp validator.py.

  Each test case builds a synthetic repo in a tempdir (.claude-plugin/marketplace.json
  plus, when needed, <path>/.claude-plugin/plugin.json) and runs:
    subprocess.run([sys.executable, validator_py], cwd=fixture, ...)
  asserting returncode + stderr/stdout substrings.

  Mandatory robustness guard: setUpClass asserts that the extracted body is
  non-empty AND contains the sentinel string 'git-subdir' (true after Edit 1
  lands).  If extraction drifts or Edit 1 is not yet applied, the guard fails
  loudly — this converts silent false-green into a visible red.

Coverage note: MAR-29 touches zero files under plugins/acs/ (only ci.yml and
this test file), so the 90% coverage gate against plugins/acs/ production code
is unaffected.

TDD: T2 and T4 are RED against the pre-Edit-1 ci.yml body (git-subdir entries
are silently skipped → name/version mismatches produce rc==0 instead of rc==1).
They turn GREEN after Edit 1 replaces the skip with a three-way branch.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CI_YML = os.path.join(REPO_ROOT, ".github", "workflows", "ci.yml")


def _extract_validator_body():
    """Locate the 'Validate marketplace/plugin version consistency' step in ci.yml,
    slice the heredoc body between <<'EOF' and the matching EOF, and DEDENT it.
    Returns the dedented body as a string.
    """
    with open(CI_YML, encoding="utf-8") as fh:
        lines = fh.readlines()

    step_name = "Validate marketplace/plugin version consistency"
    step_start = None
    for i, line in enumerate(lines):
        if step_name in line and "- name:" in line:
            step_start = i
            break

    if step_start is None:
        return ""

    # Find the <<'EOF' after the step name
    heredoc_start = None
    for i in range(step_start, min(step_start + 5, len(lines))):
        if "<<'EOF'" in lines[i]:
            heredoc_start = i
            break

    if heredoc_start is None:
        return ""

    # Slice lines from the line AFTER <<'EOF' up to (but not including) the EOF closer
    # The EOF closer is a line that is exactly spaces + "EOF\n" (no other content)
    body_lines = []
    for i in range(heredoc_start + 1, len(lines)):
        stripped = lines[i].rstrip("\n")
        # The heredoc EOF closer in ci.yml is "          EOF" (10 spaces + EOF)
        if stripped.strip() == "EOF" and stripped == " " * 10 + "EOF":
            break
        body_lines.append(lines[i])

    if not body_lines:
        return ""

    return textwrap.dedent("".join(body_lines))


class MarketplaceConsistencyTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        """Extract the validator body once; write to a shared temp file."""
        cls._tmpdir = tempfile.mkdtemp(prefix="acs-mktconsistency-")
        cls.validator_py = os.path.join(cls._tmpdir, "validator.py")

        body = _extract_validator_body()

        # Mandatory robustness guard: fail loudly if extraction drifted or Edit 1 not applied.
        if not body:
            raise AssertionError(
                "Extracted validator body from ci.yml is empty. "
                "Check that 'Validate marketplace/plugin version consistency' step "
                "with a <<'EOF' heredoc exists in .github/workflows/ci.yml."
            )
        if "git-subdir" not in body:
            raise AssertionError(
                "Extracted validator body does NOT contain the sentinel string 'git-subdir'. "
                "Edit 1 (three-way branch for git-subdir) must be applied to ci.yml before "
                "these tests will pass. This guard prevents silent false-green."
            )

        with open(cls.validator_py, "w", encoding="utf-8") as fh:
            fh.write(body)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmpdir, ignore_errors=True)

    # ------------------------------------------------------------------
    # Helper: build a synthetic fixture repo in a tempdir
    # ------------------------------------------------------------------

    def _make_fixture(self, entry, plugin_path=None, plugin_json=None, plugin_root=None):
        """Create a synthetic repo dir with .claude-plugin/marketplace.json.

        If plugin_path is given, also writes plugin_path/.claude-plugin/plugin.json.
        Returns the path to the fixture directory (cleaned up via addCleanup).
        """
        tmp = tempfile.mkdtemp(prefix="acs-mktfixture-")
        self.addCleanup(shutil.rmtree, tmp, True)

        metadata = {}
        if plugin_root is not None:
            metadata["pluginRoot"] = plugin_root

        mkt = {
            "name": "test-marketplace",
            "version": "1.0.0",
            "metadata": metadata,
            "plugins": [entry],
        }

        os.makedirs(os.path.join(tmp, ".claude-plugin"))
        with open(os.path.join(tmp, ".claude-plugin", "marketplace.json"), "w") as fh:
            json.dump(mkt, fh)

        if plugin_path is not None and plugin_json is not None:
            pj_dir = os.path.join(tmp, plugin_path, ".claude-plugin")
            os.makedirs(pj_dir, exist_ok=True)
            with open(os.path.join(pj_dir, "plugin.json"), "w") as fh:
                json.dump(plugin_json, fh)

        return tmp

    def _run(self, fixture_dir):
        return subprocess.run(
            [sys.executable, self.validator_py],
            cwd=fixture_dir,
            capture_output=True,
            text=True,
        )

    # ------------------------------------------------------------------
    # T1: git-subdir name match passes (AC-2)
    # ------------------------------------------------------------------

    def test_git_subdir_name_match_passes(self):
        """T1: git-subdir entry with matching plugin.json name → rc==0, no error."""
        entry = {
            "name": "myplugin",
            "source": {"source": "git-subdir", "url": "https://example.com/repo.git",
                       "path": "plugins/myplugin", "ref": "main"},
        }
        fixture = self._make_fixture(
            entry,
            plugin_path="plugins/myplugin",
            plugin_json={"name": "myplugin", "version": "1.0.0"},
        )
        out = self._run(fixture)
        self.assertEqual(out.returncode, 0, f"Expected rc==0. stderr={out.stderr!r}")
        self.assertIn("OK", out.stdout)

    # ------------------------------------------------------------------
    # T2: git-subdir name mismatch errors (AC-2) — RED pre-Edit-1
    # ------------------------------------------------------------------

    def test_git_subdir_name_mismatch_errors(self):
        """T2: git-subdir entry with mismatching plugin.json name → rc==1, stderr has mismatch.

        RED before Edit 1 (current ci.yml skips git-subdir → no error → rc==0 ≠ 1).
        GREEN after Edit 1 (three-way branch validates name).
        """
        entry = {
            "name": "myplugin",
            "source": {"source": "git-subdir", "url": "https://example.com/repo.git",
                       "path": "plugins/myplugin", "ref": "main"},
        }
        fixture = self._make_fixture(
            entry,
            plugin_path="plugins/myplugin",
            plugin_json={"name": "WRONG_NAME", "version": "1.0.0"},
        )
        out = self._run(fixture)
        self.assertEqual(out.returncode, 1, f"Expected rc==1. stderr={out.stderr!r} stdout={out.stdout!r}")
        self.assertIn("WRONG_NAME", out.stderr, f"Expected name mismatch in stderr. stderr={out.stderr!r}")

    # ------------------------------------------------------------------
    # T3: git-subdir version match passes (AC-3)
    # ------------------------------------------------------------------

    def test_git_subdir_version_match_passes(self):
        """T3: git-subdir entry declaring matching version → rc==0, no error."""
        entry = {
            "name": "myplugin",
            "version": "1.2.3",
            "source": {"source": "git-subdir", "url": "https://example.com/repo.git",
                       "path": "plugins/myplugin", "ref": "v1.2.3"},
        }
        fixture = self._make_fixture(
            entry,
            plugin_path="plugins/myplugin",
            plugin_json={"name": "myplugin", "version": "1.2.3"},
        )
        out = self._run(fixture)
        self.assertEqual(out.returncode, 0, f"Expected rc==0. stderr={out.stderr!r}")

    # ------------------------------------------------------------------
    # T4: git-subdir version mismatch errors (AC-3) — RED pre-Edit-1
    # ------------------------------------------------------------------

    def test_git_subdir_version_mismatch_errors(self):
        """T4: git-subdir entry declaring mismatching version → rc==1, stderr version error.

        RED before Edit 1 (git-subdir skipped → no version check → rc==0 ≠ 1).
        GREEN after Edit 1 (three-way branch validates version).
        """
        entry = {
            "name": "myplugin",
            "version": "1.0.0",
            "source": {"source": "git-subdir", "url": "https://example.com/repo.git",
                       "path": "plugins/myplugin", "ref": "v1.0.0"},
        }
        fixture = self._make_fixture(
            entry,
            plugin_path="plugins/myplugin",
            plugin_json={"name": "myplugin", "version": "9.9.9"},
        )
        out = self._run(fixture)
        self.assertEqual(out.returncode, 1, f"Expected rc==1. stderr={out.stderr!r} stdout={out.stdout!r}")
        self.assertIn("9.9.9", out.stderr, f"Expected version mismatch in stderr. stderr={out.stderr!r}")

    # ------------------------------------------------------------------
    # T5: git-subdir no entry-version skips version branch but enforces name (AC-3)
    # ------------------------------------------------------------------

    def test_git_subdir_no_entry_version_skips_version_branch(self):
        """T5: git-subdir entry with NO version key + plugin.json with version → rc==0,
        no version error; name check still fires (passes when names match).
        """
        entry = {
            "name": "myplugin",
            # No "version" key
            "source": {"source": "git-subdir", "url": "https://example.com/repo.git",
                       "path": "plugins/myplugin", "ref": "main"},
        }
        fixture = self._make_fixture(
            entry,
            plugin_path="plugins/myplugin",
            plugin_json={"name": "myplugin", "version": "0.5.0"},
        )
        out = self._run(fixture)
        self.assertEqual(out.returncode, 0, f"Expected rc==0. stderr={out.stderr!r}")
        # Confirm no version error
        self.assertNotIn("version", out.stderr.lower(),
                         f"Expected no version error. stderr={out.stderr!r}")

    # ------------------------------------------------------------------
    # T6: Non-git-subdir object sources skipped (AC-4)
    # ------------------------------------------------------------------

    def test_github_object_source_skipped(self):
        """T6_github: Entry with source.source=='github' and no local manifest → rc==0."""
        entry = {
            "name": "remoteplugin",
            "source": {"source": "github", "repo": "acme/plugin", "ref": "main"},
        }
        fixture = self._make_fixture(entry)
        out = self._run(fixture)
        self.assertEqual(out.returncode, 0, f"Expected rc==0. stderr={out.stderr!r}")
        # No missing-manifest error
        self.assertNotIn("plugin.json", out.stderr,
                         f"Expected no manifest error. stderr={out.stderr!r}")

    def test_url_object_source_skipped(self):
        """T6_url: Entry with source.source=='url' → rc==0, no local-manifest error."""
        entry = {
            "name": "urlplugin",
            "source": {"source": "url", "url": "https://example.com/plugin.tar.gz"},
        }
        fixture = self._make_fixture(entry)
        out = self._run(fixture)
        self.assertEqual(out.returncode, 0, f"Expected rc==0. stderr={out.stderr!r}")

    def test_npm_object_source_skipped(self):
        """T6_npm: Entry with source.source=='npm' → rc==0, no local-manifest error."""
        entry = {
            "name": "npmplugin",
            "source": {"source": "npm", "package": "@acme/plugin"},
        }
        fixture = self._make_fixture(entry)
        out = self._run(fixture)
        self.assertEqual(out.returncode, 0, f"Expected rc==0. stderr={out.stderr!r}")

    # ------------------------------------------------------------------
    # T7: String-path source unchanged (AC-5 regression guard)
    # ------------------------------------------------------------------

    def test_string_path_source_unchanged(self):
        """T7_string: String-path entry with matching name+version → rc==0 (AC-5)."""
        entry = {
            "name": "localplugin",
            "version": "2.0.0",
            "source": "plugins/localplugin",
        }
        fixture = self._make_fixture(
            entry,
            plugin_path="plugins/localplugin",
            plugin_json={"name": "localplugin", "version": "2.0.0"},
        )
        out = self._run(fixture)
        self.assertEqual(out.returncode, 0, f"Expected rc==0. stderr={out.stderr!r}")

    def test_string_path_name_mismatch_errors(self):
        """T7_string_mismatch: String-path entry with mismatching name → rc==1 (AC-5)."""
        entry = {
            "name": "localplugin",
            "source": "plugins/localplugin",
        }
        fixture = self._make_fixture(
            entry,
            plugin_path="plugins/localplugin",
            plugin_json={"name": "DIFFERENT_NAME", "version": "1.0.0"},
        )
        out = self._run(fixture)
        self.assertEqual(out.returncode, 1, f"Expected rc==1. stderr={out.stderr!r}")
        self.assertIn("DIFFERENT_NAME", out.stderr,
                      f"Expected name mismatch in stderr. stderr={out.stderr!r}")

    # ------------------------------------------------------------------
    # T8: Live acs smoke — real marketplace.json + real plugin.json (AC-2, AC-6)
    # ------------------------------------------------------------------

    def test_live_acs_entry_name_matches(self):
        """T8: Read the real marketplace.json and plugins/acs/.claude-plugin/plugin.json.
        Assert the acs entry's name matches the plugin.json name.
        This is the smoke test against the live repo state (AC-2, AC-6).
        """
        mkt_path = os.path.join(REPO_ROOT, ".claude-plugin", "marketplace.json")
        pj_path = os.path.join(REPO_ROOT, "plugins", "acs", ".claude-plugin", "plugin.json")

        with open(mkt_path, encoding="utf-8") as fh:
            mkt = json.load(fh)
        with open(pj_path, encoding="utf-8") as fh:
            pj = json.load(fh)

        # Find the acs entry
        acs_entry = None
        for entry in mkt.get("plugins", []):
            if entry.get("name") == "acs":
                acs_entry = entry
                break

        self.assertIsNotNone(acs_entry, "No 'acs' entry found in .claude-plugin/marketplace.json")
        entry_name = acs_entry.get("name")
        pj_name = pj.get("name")
        self.assertEqual(
            entry_name, pj_name,
            f"acs entry name '{entry_name}' != plugin.json name '{pj_name}'"
        )
        self.assertEqual(pj_name, "acs",
                         f"Expected plugin.json name to be 'acs', got '{pj_name}'")


if __name__ == "__main__":
    unittest.main()
