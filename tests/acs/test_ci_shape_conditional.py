"""Regression tests for the generalized per-plugin shape-conditional CI steps.

Mechanism: EXTRACT-AND-RUN (mirrors test_marketplace_consistency.py pattern).

  setUpClass extracts each generalized static-check step from ci.yml:
    - Python-heredoc steps (JSON-Schema, settings, frontmatter): slice the body
      between <<'EOF' and the 10-space EOF closer, dedent, write a temp
      validator_<name>.py, run via subprocess.run([sys.executable, ...], cwd=fixture).
    - Shell run-block steps (XSD, hooks): extract the run: | block body, dedent,
      write a temp validate_<name>.sh, run via subprocess.run(["bash", script],
      cwd=fixture).

  Mandatory robustness guards: each extraction asserts the body is non-empty AND
  the plugins/acs/ hardcode is absent AND a loop variable/sentinel is present.
  These guards are RED against the un-generalized ci.yml.

  Synthetic fixtures are tmpdir-only (no committed plugin).

Coverage note: MAR-30 touches zero files under plugins/acs/ (only ci.yml,
.pre-commit-config.yaml, and this test file), so the 90% coverage gate against
plugins/acs/ production code is unaffected.

TDD: Tests are written BEFORE the ci.yml edits. The setUpClass guards and the
skills-only (skn) fixture tests are RED against the un-generalized ci.yml and
turn GREEN after each step is generalized.
"""

import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CI_YML = os.path.join(REPO_ROOT, ".github", "workflows", "ci.yml")
PRECOMMIT_YAML = os.path.join(REPO_ROOT, ".pre-commit-config.yaml")


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------

def _read_ci_lines():
    with open(CI_YML, encoding="utf-8") as fh:
        return fh.readlines()


def _find_step_start(lines, step_name):
    """Return the line index of the '- name: <step_name>' line, or None."""
    for i, line in enumerate(lines):
        if "- name:" in line and step_name in line:
            return i
    return None


def _extract_heredoc_body(lines, step_name):
    """Locate <step_name> in ci.yml, slice the heredoc between <<'EOF' and the
    10-space EOF closer, dedent, and return as a string. Returns '' on failure.
    """
    step_start = _find_step_start(lines, step_name)
    if step_start is None:
        return ""

    # Find <<'EOF' within the next ~5 lines
    heredoc_start = None
    for i in range(step_start, min(step_start + 5, len(lines))):
        if "<<'EOF'" in lines[i]:
            heredoc_start = i
            break
    if heredoc_start is None:
        return ""

    # Slice from the line AFTER <<'EOF' up to (not including) the 10-space EOF closer
    body_lines = []
    for i in range(heredoc_start + 1, len(lines)):
        stripped = lines[i].rstrip("\n")
        if stripped.strip() == "EOF" and stripped == " " * 10 + "EOF":
            break
        body_lines.append(lines[i])

    if not body_lines:
        return ""
    return textwrap.dedent("".join(body_lines))


def _extract_run_block_body(lines, step_name):
    """Locate <step_name> in ci.yml, find the 'run: |' line in its block, and
    extract all indented lines that follow it (the shell block body). Returns
    dedented body as a string, or '' on failure.
    """
    step_start = _find_step_start(lines, step_name)
    if step_start is None:
        return ""

    # Find the 'run: |' line within the next ~10 lines after the step
    run_line_idx = None
    for i in range(step_start, min(step_start + 10, len(lines))):
        stripped = lines[i].strip()
        if stripped == "run: |":
            run_line_idx = i
            break
        # Also handle 'run: |' as part of a single-line (for pre-generalization state)
        if stripped.startswith("run:") and not stripped.startswith("run: |"):
            # Single-line run: (pre-generalization) - return the command itself
            cmd = stripped[len("run:"):].strip()
            return cmd + "\n"

    if run_line_idx is None:
        return ""

    # Determine indentation of the run: | line to know when the block ends
    run_indent = len(lines[run_line_idx]) - len(lines[run_line_idx].lstrip())
    # Block body lines are MORE indented than run_indent + typical step indent
    body_lines = []
    for i in range(run_line_idx + 1, len(lines)):
        line = lines[i]
        if line.strip() == "":
            # blank lines within a block - stop if next non-blank is less-indented
            body_lines.append(line)
            continue
        curr_indent = len(line) - len(line.lstrip())
        if curr_indent <= run_indent:
            break
        body_lines.append(line)

    # Strip trailing blank lines
    while body_lines and body_lines[-1].strip() == "":
        body_lines.pop()

    if not body_lines:
        return ""
    return textwrap.dedent("".join(body_lines))


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

def _make_marketplace_json(plugin_entries, plugin_root=None):
    """Return a dict suitable for marketplace.json."""
    metadata = {}
    if plugin_root:
        metadata["pluginRoot"] = plugin_root
    return {
        "name": "test-marketplace",
        "version": "1.0.0",
        "metadata": metadata,
        "plugins": plugin_entries,
    }


def _write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


def _make_full_shape_fixture(tmp, name="full"):
    """Create a full-shape plugin fixture in tmp/plugins/<name>/.
    Returns the plugin dir path.
    """
    p = os.path.join(tmp, "plugins", name)
    # plugin.json
    _write_file(
        os.path.join(p, ".claude-plugin", "plugin.json"),
        json.dumps({"name": name, "version": "0.1.0"}),
    )
    # schemas
    _write_file(
        os.path.join(p, "schemas", f"{name}.schema.json"),
        json.dumps({"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object"}),
    )
    _write_file(
        os.path.join(p, "schemas", "settings.schema.json"),
        json.dumps({"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object"}),
    )
    # XSD (minimal valid)
    _write_file(
        os.path.join(p, "schemas", f"{name}-messages.xsd"),
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">\n'
        '  <xs:element name="root" type="xs:string"/>\n'
        '</xs:schema>\n',
    )
    # hooks
    _write_file(
        os.path.join(p, "hooks", "scripts", "hook.py"),
        "# compilable hook\ndef run():\n    pass\n",
    )
    # skills
    _write_file(
        os.path.join(p, "skills", "s", "SKILL.md"),
        "---\nname: test-skill\ndescription: A test skill.\n---\n\n# Test skill\n",
    )
    # agents
    _write_file(
        os.path.join(p, "agents", "a.md"),
        "---\nname: test-agent\ndescription: A test agent.\n---\n\n# Test agent\n",
    )
    return p


def _make_skills_only_fixture(tmp, name="skn"):
    """Create a skills-only plugin fixture in tmp/plugins/<name>/.
    Returns the plugin dir path.
    """
    p = os.path.join(tmp, "plugins", name)
    _write_file(
        os.path.join(p, ".claude-plugin", "plugin.json"),
        json.dumps({"name": name, "version": "0.1.0"}),
    )
    _write_file(
        os.path.join(p, "skills", "s", "SKILL.md"),
        "---\nname: skn-skill\ndescription: A skills-only skill.\n---\n\n# SKN skill\n",
    )
    return p


def _write_marketplace(tmp, plugin_entries):
    mkt = _make_marketplace_json(plugin_entries)
    _write_file(
        os.path.join(tmp, ".claude-plugin", "marketplace.json"),
        json.dumps(mkt),
    )


# ---------------------------------------------------------------------------
# Base test class with extraction and shared fixtures
# ---------------------------------------------------------------------------

class _CIShapeBase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.mkdtemp(prefix="acs-cishape-")
        cls.lines = _read_ci_lines()

        # -------------------------------------------------------------------
        # Extract each generalized step
        # -------------------------------------------------------------------
        cls.schema_body = _extract_heredoc_body(
            cls.lines, "Validate JSON Schema documents (structural)"
        )
        cls.settings_body = _extract_heredoc_body(
            cls.lines, "Validate committed per-plugin settings.json against the schema"
        )
        cls.fm_body = _extract_heredoc_body(
            cls.lines, "Check skill/agent frontmatter"
        )
        cls.xsd_body = _extract_run_block_body(
            cls.lines, "Validate XSD"
        )
        cls.hooks_body = _extract_run_block_body(
            cls.lines, "Byte-compile hook scripts"
        )

        # Write scripts
        cls.schema_py = os.path.join(cls._tmpdir, "validator_schema.py")
        cls.settings_py = os.path.join(cls._tmpdir, "validator_settings.py")
        cls.fm_py = os.path.join(cls._tmpdir, "validator_fm.py")
        cls.xsd_sh = os.path.join(cls._tmpdir, "validate_xsd.sh")
        cls.hooks_sh = os.path.join(cls._tmpdir, "validate_hooks.sh")

        for path, body in [
            (cls.schema_py, cls.schema_body),
            (cls.settings_py, cls.settings_body),
            (cls.fm_py, cls.fm_body),
            (cls.xsd_sh, cls.xsd_body),
            (cls.hooks_sh, cls.hooks_body),
        ]:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(body)

        # -------------------------------------------------------------------
        # Robustness guards: assert generalization has been applied
        # -------------------------------------------------------------------
        cls._assert_generalized()

    @classmethod
    def _assert_generalized(cls):
        """Fail loudly if any generalized step still contains a plugins/acs/ hardcode
        or lacks a loop sentinel. These guards are RED before the ci.yml edits land.
        """
        # Step 1 (JSON parse): find the run: line for that step
        step1_idx = _find_step_start(cls.lines, "Validate all JSON files parse")
        if step1_idx is not None:
            # Look for the 'find' command in the next ~15 lines
            step1_run_text = "".join(cls.lines[step1_idx:step1_idx + 15])
            assert "find .claude-plugin plugins" in step1_run_text, (
                "Step 1 (JSON-parse) run block must contain 'find .claude-plugin plugins' "
                "(without '/acs') after generalization. Guard: generalization not yet applied."
            )
            assert "plugins/acs" not in step1_run_text or "plugins/acs/" not in step1_run_text.replace(
                "find .claude-plugin plugins", ""
            ), (
                "Step 1 (JSON-parse) run block must NOT contain 'plugins/acs/' after "
                "generalization. Guard: hardcode still present."
            )
            # More precise check: the find command should not specifically enumerate plugins/acs
            find_lines = [l for l in cls.lines[step1_idx:step1_idx + 15] if "find " in l]
            if find_lines:
                assert "plugins/acs" not in find_lines[0] or (
                    "plugins " in find_lines[0] and "plugins/acs " not in find_lines[0]
                ), (
                    f"Step 1 find command still has hardcoded 'plugins/acs': {find_lines[0].strip()}"
                )

        # Step 2 (JSON Schema structural): body must not hardcode plugins/acs/schemas
        assert cls.schema_body, (
            "Extracted schema step body is empty. Check 'Validate JSON Schema documents "
            "(structural)' step heredoc in ci.yml."
        )
        assert "plugins/acs/schemas" not in cls.schema_body, (
            "Schema step body still hardcodes 'plugins/acs/schemas'. "
            "Generalization (per-plugin loop) must be applied first."
        )
        assert "plugin_dir" in cls.schema_body or "marketplace.json" in cls.schema_body, (
            "Schema step body must contain a loop variable (plugin_dir) or marketplace.json "
            "enumeration after generalization."
        )

        # Step 3 (settings): body must not hardcode plugins/acs
        assert cls.settings_body, (
            "Extracted settings step body is empty."
        )
        assert "plugins/acs" not in cls.settings_body, (
            "Settings step body still hardcodes 'plugins/acs'. "
            "Generalization must be applied first."
        )
        assert "plugin_dir" in cls.settings_body or "marketplace.json" in cls.settings_body, (
            "Settings step body must contain a loop variable after generalization."
        )

        # Step 4 (XSD): body must not hardcode plugins/acs/schemas/acs-messages.xsd
        assert cls.xsd_body, (
            "Extracted XSD step body is empty."
        )
        assert "plugins/acs/schemas/acs-messages.xsd" not in cls.xsd_body, (
            "XSD step body still hardcodes 'plugins/acs/schemas/acs-messages.xsd'. "
            "Generalization must be applied first."
        )
        # After generalization it should be a shell loop (for/while) or contain marketplace
        assert (
            "for " in cls.xsd_body
            or "while " in cls.xsd_body
            or "marketplace.json" in cls.xsd_body
        ), (
            "XSD step body must contain a loop construct after generalization."
        )

        # Step 5 (hooks): body must not hardcode plugins/acs/hooks
        assert cls.hooks_body, (
            "Extracted hooks step body is empty."
        )
        assert "plugins/acs/hooks/scripts" not in cls.hooks_body, (
            "Hooks step body still hardcodes 'plugins/acs/hooks/scripts'. "
            "Generalization must be applied first."
        )
        assert (
            "for " in cls.hooks_body
            or "while " in cls.hooks_body
            or "marketplace.json" in cls.hooks_body
        ), (
            "Hooks step body must contain a loop construct after generalization."
        )

        # Step 6 (frontmatter): body must not hardcode plugins/acs/skills or plugins/acs/agents
        assert cls.fm_body, (
            "Extracted frontmatter step body is empty."
        )
        assert "plugins/acs/skills" not in cls.fm_body, (
            "Frontmatter step body still hardcodes 'plugins/acs/skills'. "
            "Generalization must be applied first."
        )
        assert "plugins/acs/agents" not in cls.fm_body, (
            "Frontmatter step body still hardcodes 'plugins/acs/agents'. "
            "Generalization must be applied first."
        )
        assert "plugin_dir" in cls.fm_body or "marketplace.json" in cls.fm_body, (
            "Frontmatter step body must contain a loop variable after generalization."
        )

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmpdir, ignore_errors=True)

    # ------------------------------------------------------------------
    # Run helpers
    # ------------------------------------------------------------------

    def _run_py(self, script_path, fixture_dir, extra_env=None):
        env = os.environ.copy()
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            [sys.executable, script_path],
            cwd=fixture_dir,
            capture_output=True,
            text=True,
            env=env,
        )

    def _run_sh(self, script_path, fixture_dir):
        return subprocess.run(
            ["bash", script_path],
            cwd=fixture_dir,
            capture_output=True,
            text=True,
        )

    # ------------------------------------------------------------------
    # Fixture builder helpers
    # ------------------------------------------------------------------

    def _tmp_fixture(self):
        tmp = tempfile.mkdtemp(prefix="acs-cisfixture-")
        self.addCleanup(shutil.rmtree, tmp, True)
        return tmp


# ---------------------------------------------------------------------------
# T-JSON-parse: JSON parse step uses widened find (AC-1, AC-4)
# ---------------------------------------------------------------------------

class TestJSONParse(unittest.TestCase):

    def test_json_parse_step_uses_plugins_not_plugins_acs(self):
        """T-JSON-parse: Step 1 'find' must cover 'plugins' not 'plugins/acs' specifically."""
        lines = _read_ci_lines()
        step_idx = _find_step_start(lines, "Validate all JSON files parse")
        self.assertIsNotNone(step_idx, "Step 'Validate all JSON files parse' not found in ci.yml")
        # Get the run block (next ~15 lines)
        block = "".join(lines[step_idx:step_idx + 15])
        # Must contain 'find .claude-plugin plugins' (widened, no /acs suffix)
        self.assertIn(
            "find .claude-plugin plugins",
            block,
            "JSON-parse step must use 'find .claude-plugin plugins' (widened) after generalization"
        )
        # Must NOT have 'plugins/acs' as a distinct find target
        # (after widening, 'plugins' covers all plugins including acs)
        find_lines = [l.strip() for l in lines[step_idx:step_idx + 15] if "find " in l and ".claude-plugin" in l]
        if find_lines:
            self.assertNotIn(
                "plugins/acs",
                find_lines[0],
                f"JSON-parse find command must not hardcode plugins/acs: {find_lines[0]}"
            )


# ---------------------------------------------------------------------------
# Schema step tests (Python heredoc)
# ---------------------------------------------------------------------------

class TestSchemaStep(_CIShapeBase):

    def _make_full_fixture(self):
        tmp = self._tmp_fixture()
        _make_full_shape_fixture(tmp, "full")
        _write_marketplace(tmp, [{"name": "full", "source": "plugins/full"}])
        return tmp

    def _make_skn_fixture(self):
        tmp = self._tmp_fixture()
        _make_skills_only_fixture(tmp, "skn")
        _write_marketplace(tmp, [{"name": "skn", "source": "plugins/skn"}])
        return tmp

    def test_schema_full_shape_passes(self):
        """T-SCHEMA-full: Full-shape plugin has schemas -> structural check runs and passes (rc==0)."""
        fixture = self._make_full_fixture()
        result = self._run_py(self.schema_py, fixture)
        self.assertEqual(result.returncode, 0,
                         f"Expected rc==0 for full-shape schema check. "
                         f"stderr={result.stderr!r} stdout={result.stdout!r}")

    def test_schema_skills_only_skips(self):
        """T-SCHEMA-skip: Skills-only plugin has no schemas -> check skips (rc==0, AC-3)."""
        fixture = self._make_skn_fixture()
        result = self._run_py(self.schema_py, fixture)
        self.assertEqual(result.returncode, 0,
                         f"Expected rc==0 for skills-only (schema skip). "
                         f"stderr={result.stderr!r} stdout={result.stdout!r}")

    def test_schema_negative_missing_dollar_schema_key(self):
        """T-SCHEMA-neg: Schema missing '$schema' key -> check fails (rc==1, R-A)."""
        tmp = self._tmp_fixture()
        p = os.path.join(tmp, "plugins", "bad")
        _write_file(
            os.path.join(p, ".claude-plugin", "plugin.json"),
            json.dumps({"name": "bad", "version": "0.1.0"}),
        )
        # Schema is valid JSON but missing '$schema' key
        _write_file(
            os.path.join(p, "schemas", "bad.schema.json"),
            json.dumps({"type": "object"}),  # missing $schema
        )
        _write_marketplace(tmp, [{"name": "bad", "source": "plugins/bad"}])
        result = self._run_py(self.schema_py, tmp)
        self.assertEqual(result.returncode, 1,
                         f"Expected rc==1 for malformed schema (missing $schema). "
                         f"stderr={result.stderr!r}")


# ---------------------------------------------------------------------------
# Settings step tests (Python heredoc)
# ---------------------------------------------------------------------------

class TestSettingsStep(_CIShapeBase):

    def _make_full_fixture_no_acs_settings(self):
        """Full-shape plugin but no .acs/settings.json in fixture -> settings-skip guard fires."""
        tmp = self._tmp_fixture()
        _make_full_shape_fixture(tmp, "full")
        _write_marketplace(tmp, [{"name": "full", "source": "plugins/full"}])
        # Do NOT create .acs/settings.json -> the existing skip guard fires
        return tmp

    def _make_skn_fixture(self):
        tmp = self._tmp_fixture()
        _make_skills_only_fixture(tmp, "skn")
        _write_marketplace(tmp, [{"name": "skn", "source": "plugins/skn"}])
        return tmp

    def test_settings_full_shape_no_acs_settings_json(self):
        """T-SETTINGS-full: Full-shape plugin has settings.schema.json; no .acs/settings.json
        -> existing target-skip guard fires, still rc==0. (AC-2, AC-4)
        """
        fixture = self._make_full_fixture_no_acs_settings()
        result = self._run_py(self.settings_py, fixture)
        self.assertEqual(result.returncode, 0,
                         f"Expected rc==0 (no .acs/settings.json -> skip guard). "
                         f"stderr={result.stderr!r} stdout={result.stdout!r}")

    def test_settings_skills_only_skips(self):
        """T-SETTINGS-skip: Skills-only plugin has no settings.schema.json -> check skips (rc==0, AC-3)."""
        fixture = self._make_skn_fixture()
        result = self._run_py(self.settings_py, fixture)
        self.assertEqual(result.returncode, 0,
                         f"Expected rc==0 for skills-only (settings skip). "
                         f"stderr={result.stderr!r} stdout={result.stdout!r}")



    def test_settings_each_plugin_validates_its_own_target(self):
        """T-SETTINGS-per-plugin: A second plugin with settings.schema.json
        (additionalProperties:false) and no .<name>/settings.json must NOT cause
        the step to validate .acs/settings.json against that plugin's schema.
        The step must derive the target from the plugin name: .<plugin_name>/settings.json,
        and skip it when absent. Overall rc must be 0.

        Scenario: two plugins —
          - "acs" has settings.schema.json (open schema) AND .acs/settings.json
          - "tabp" has settings.schema.json (additionalProperties:false) but NO
            .tabp/settings.json

        The step must validate .acs/settings.json against acs's schema (pass),
        skip tabp's target (absent), and exit 0. It must NOT apply tabp's
        additionalProperties:false schema to .acs/settings.json.
        """
        import json as _json
        tmp = self._tmp_fixture()

        # Plugin "acs": open settings schema + .acs/settings.json with extra props
        acs_dir = os.path.join(tmp, "plugins", "acs")
        _write_file(
            os.path.join(acs_dir, ".claude-plugin", "plugin.json"),
            _json.dumps({"name": "acs", "version": "0.1.0"}),
        )
        # Open schema (no additionalProperties:false) so .acs/settings.json passes
        _write_file(
            os.path.join(acs_dir, "schemas", "settings.schema.json"),
            _json.dumps({
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
            }),
        )
        # .acs/settings.json with extra properties that would fail additionalProperties:false
        _write_file(
            os.path.join(tmp, ".acs", "settings.json"),
            _json.dumps({
                "workspace_path": "/some/path",
                "ticket_prefix": "MAR",
                "extra_field": "extra_value",
            }),
        )

        # Plugin "tabp": strict schema (additionalProperties:false) but NO .tabp/settings.json
        tabp_dir = os.path.join(tmp, "plugins", "tabp")
        _write_file(
            os.path.join(tabp_dir, ".claude-plugin", "plugin.json"),
            _json.dumps({"name": "tabp", "version": "0.1.0"}),
        )
        _write_file(
            os.path.join(tabp_dir, "schemas", "settings.schema.json"),
            _json.dumps({
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "properties": {
                    "screening_model": {"type": "string"},
                },
                "additionalProperties": False,
            }),
        )
        # NO .tabp/settings.json created -> step must skip it

        _write_marketplace(tmp, [
            {"name": "acs", "source": "plugins/acs"},
            {"name": "tabp", "source": "plugins/tabp"},
        ])

        result = self._run_py(self.settings_py, tmp)
        self.assertEqual(
            result.returncode, 0,
            f"T-SETTINGS-per-plugin: Expected rc==0 when each plugin validates only "
            f"its own .<name>/settings.json target. "
            f"If rc!=0, the step is applying a non-owning plugin schema to the wrong target. "
            f"stderr={result.stderr!r} stdout={result.stdout!r}"
        )

# ---------------------------------------------------------------------------
# XSD step tests (shell run block)
# ---------------------------------------------------------------------------

class TestXSDStep(_CIShapeBase):

    def _make_full_fixture(self):
        tmp = self._tmp_fixture()
        _make_full_shape_fixture(tmp, "full")
        _write_marketplace(tmp, [{"name": "full", "source": "plugins/full"}])
        return tmp

    def _make_skn_fixture(self):
        tmp = self._tmp_fixture()
        _make_skills_only_fixture(tmp, "skn")
        _write_marketplace(tmp, [{"name": "skn", "source": "plugins/skn"}])
        return tmp

    def test_xsd_full_shape_passes(self):
        """T-XSD-full: Full-shape plugin has .xsd -> xmllint runs and passes (rc==0, AC-2, AC-4)."""
        fixture = self._make_full_fixture()
        result = self._run_sh(self.xsd_sh, fixture)
        self.assertEqual(result.returncode, 0,
                         f"Expected rc==0 for full-shape XSD check. "
                         f"stderr={result.stderr!r} stdout={result.stdout!r}")

    def test_xsd_skills_only_skips(self):
        """T-XSD-skip: Skills-only plugin has no .xsd -> check skips, no xmllint error (rc==0, AC-3, R-D)."""
        fixture = self._make_skn_fixture()
        result = self._run_sh(self.xsd_sh, fixture)
        self.assertEqual(result.returncode, 0,
                         f"Expected rc==0 for skills-only (XSD skip). "
                         f"stderr={result.stderr!r} stdout={result.stdout!r}")


# ---------------------------------------------------------------------------
# Hooks step tests (shell run block)
# ---------------------------------------------------------------------------

class TestHooksStep(_CIShapeBase):

    def _make_full_fixture(self):
        tmp = self._tmp_fixture()
        _make_full_shape_fixture(tmp, "full")
        _write_marketplace(tmp, [{"name": "full", "source": "plugins/full"}])
        return tmp

    def _make_skn_fixture(self):
        tmp = self._tmp_fixture()
        _make_skills_only_fixture(tmp, "skn")
        _write_marketplace(tmp, [{"name": "skn", "source": "plugins/skn"}])
        return tmp

    def test_hooks_full_shape_passes(self):
        """T-HOOKS-full: Full-shape has hooks/scripts/*.py -> py_compile runs and passes (rc==0, AC-2, AC-4)."""
        fixture = self._make_full_fixture()
        result = self._run_sh(self.hooks_sh, fixture)
        self.assertEqual(result.returncode, 0,
                         f"Expected rc==0 for full-shape hooks check. "
                         f"stderr={result.stderr!r} stdout={result.stdout!r}")

    def test_hooks_skills_only_skips(self):
        """T-HOOKS-skip: Skills-only has no hooks/ -> check skips (rc==0, AC-3, R-D)."""
        fixture = self._make_skn_fixture()
        result = self._run_sh(self.hooks_sh, fixture)
        self.assertEqual(result.returncode, 0,
                         f"Expected rc==0 for skills-only (hooks skip). "
                         f"stderr={result.stderr!r} stdout={result.stdout!r}")

    def test_hooks_negative_syntax_error(self):
        """T-HOOKS-neg: Syntax-broken hook.py -> py_compile fails (rc==1, R-A)."""
        tmp = self._tmp_fixture()
        p = os.path.join(tmp, "plugins", "badhook")
        _write_file(
            os.path.join(p, ".claude-plugin", "plugin.json"),
            json.dumps({"name": "badhook", "version": "0.1.0"}),
        )
        # Intentional syntax error
        _write_file(
            os.path.join(p, "hooks", "scripts", "broken.py"),
            "def foo(\n    # missing closing paren and body\n",
        )
        _write_marketplace(tmp, [{"name": "badhook", "source": "plugins/badhook"}])
        result = self._run_sh(self.hooks_sh, tmp)
        self.assertEqual(result.returncode, 1,
                         f"Expected rc==1 for broken hook.py. "
                         f"stderr={result.stderr!r} stdout={result.stdout!r}")


# ---------------------------------------------------------------------------
# Frontmatter step tests (Python heredoc)
# ---------------------------------------------------------------------------

class TestFrontmatterStep(_CIShapeBase):

    def _make_full_fixture(self):
        tmp = self._tmp_fixture()
        _make_full_shape_fixture(tmp, "full")
        _write_marketplace(tmp, [{"name": "full", "source": "plugins/full"}])
        return tmp

    def _make_skn_fixture(self):
        tmp = self._tmp_fixture()
        _make_skills_only_fixture(tmp, "skn")
        _write_marketplace(tmp, [{"name": "skn", "source": "plugins/skn"}])
        return tmp

    def test_frontmatter_full_shape_passes(self):
        """T-FM-full: Full-shape has skills + agents -> frontmatter check runs and passes (rc==0, AC-2, AC-4)."""
        fixture = self._make_full_fixture()
        result = self._run_py(self.fm_py, fixture)
        self.assertEqual(result.returncode, 0,
                         f"Expected rc==0 for full-shape frontmatter check. "
                         f"stderr={result.stderr!r} stdout={result.stdout!r}")

    def test_frontmatter_skills_only_passes(self):
        """T-FM-skillsonly: Skills-only has skills, no agents -> frontmatter check runs and passes
        (rc==0, AC-3 proof: ONLY frontmatter fires, green).
        """
        fixture = self._make_skn_fixture()
        result = self._run_py(self.fm_py, fixture)
        self.assertEqual(result.returncode, 0,
                         f"Expected rc==0 for skills-only frontmatter check. "
                         f"stderr={result.stderr!r} stdout={result.stdout!r}")

    def test_frontmatter_negative_missing_description(self):
        """T-FM-neg: Frontmatter missing 'description:' key -> check fails (rc==1, R-A)."""
        tmp = self._tmp_fixture()
        p = os.path.join(tmp, "plugins", "badfm")
        _write_file(
            os.path.join(p, ".claude-plugin", "plugin.json"),
            json.dumps({"name": "badfm", "version": "0.1.0"}),
        )
        # SKILL.md missing 'description' key in frontmatter
        _write_file(
            os.path.join(p, "skills", "s", "SKILL.md"),
            "---\nname: bad-skill\n---\n\n# Bad skill\n",
        )
        _write_marketplace(tmp, [{"name": "badfm", "source": "plugins/badfm"}])
        result = self._run_py(self.fm_py, tmp)
        self.assertEqual(result.returncode, 1,
                         f"Expected rc==1 for frontmatter missing description. "
                         f"stderr={result.stderr!r}")

    def test_frontmatter_plugin_with_no_skills_or_agents_skips(self):
        """Synthetic plugin with neither skills/ nor agents/ -> check skips (rc==0).
        This tests the per-plugin skip behavior (not global FAIL-if-none).
        """
        tmp = self._tmp_fixture()
        p = os.path.join(tmp, "plugins", "noskills")
        _write_file(
            os.path.join(p, ".claude-plugin", "plugin.json"),
            json.dumps({"name": "noskills", "version": "0.1.0"}),
        )
        # Add some schemas to make it non-empty in other ways, but NO skills/agents
        _write_file(
            os.path.join(p, "schemas", "noskills.schema.json"),
            json.dumps({"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object"}),
        )
        _write_marketplace(tmp, [{"name": "noskills", "source": "plugins/noskills"}])
        result = self._run_py(self.fm_py, tmp)
        self.assertEqual(result.returncode, 0,
                         f"Expected rc==0 for plugin with no skills/agents (skip). "
                         f"stderr={result.stderr!r}")


# ---------------------------------------------------------------------------
# Structural and live-file assertions (non-execution tests)
# ---------------------------------------------------------------------------

class TestCIStructural(unittest.TestCase):

    def test_named_step_count_is_9(self):
        """The ci.yml must have exactly 9 named steps (grep '- name:')."""
        lines = _read_ci_lines()
        named = [l for l in lines if re.match(r"\s*- name:", l)]
        self.assertEqual(len(named), 9,
                         f"Expected 9 named steps, got {len(named)}: "
                         f"{[l.strip() for l in named]}")

    def test_no_eval_in_ci_yml(self):
        """T-NO-EVALS: ci.yml must contain no 'eval' invocation (AC-5)."""
        lines = _read_ci_lines()
        eval_lines = [
            (i + 1, l.rstrip())
            for i, l in enumerate(lines)
            if re.search(r"\beval\b", l, re.IGNORECASE)
        ]
        self.assertEqual(eval_lines, [],
                         f"ci.yml contains 'eval' on lines: {eval_lines}")

    def test_unit_test_step_unchanged(self):
        """T-UNITTEST-unchanged: unit-test step body is 'discover -s tests' with no plugin loop (AC-6)."""
        lines = _read_ci_lines()
        step_idx = _find_step_start(lines, "Run unit tests")
        self.assertIsNotNone(step_idx, "Step 'Run unit tests' not found in ci.yml")
        # Get the run line(s) after the step name
        block = "".join(lines[step_idx:step_idx + 5])
        self.assertIn("discover -s tests", block,
                      "Unit-test step must contain 'discover -s tests'")
        # Must NOT have a plugins/ loop around it
        self.assertNotIn("plugin_dir", block,
                         "Unit-test step must not have a plugin_dir loop")
        self.assertNotIn("for plugin", block,
                         "Unit-test step must not have a per-plugin loop")

    def test_mar29_validator_intact(self):
        """T-MAR29-intact: Per-entry validator step body contains 'git-subdir' sentinel (AC-4, AC-8, R-B)."""
        body = _extract_heredoc_body(
            _read_ci_lines(),
            "Validate marketplace/plugin version consistency"
        )
        self.assertTrue(body, "Per-entry validator body must not be empty (MAR-29 not present?)")
        self.assertIn("git-subdir", body,
                      "Per-entry validator body must contain 'git-subdir' sentinel (MAR-29)")

    def test_heredoc_eof_openers_and_closers_balance(self):
        """Heredoc openers (<<'EOF') must balance with 10-space EOF closers."""
        lines = _read_ci_lines()
        openers = sum(1 for l in lines if "<<'EOF'" in l)
        closers = sum(1 for l in lines if l.rstrip() == " " * 10 + "EOF")
        self.assertEqual(openers, closers,
                         f"Heredoc openers ({openers}) must equal 10-space EOF closers ({closers})")

    def test_precommit_glob_widened(self):
        """T-PRECOMMIT-glob: .pre-commit-config.yaml acs-free-evals files: glob is '^(evals/|plugins/)' (AC-7)."""
        with open(PRECOMMIT_YAML, encoding="utf-8") as fh:
            content = fh.read()
        self.assertIn(
            "^(evals/|plugins/)",
            content,
            "acs-free-evals files: glob must be '^(evals/|plugins/)' after MAR-30"
        )
        # Must NOT still have the old narrower glob
        self.assertNotIn(
            "^(evals/|plugins/acs/)",
            content,
            "acs-free-evals files: old glob '^(evals/|plugins/acs/)' must be removed"
        )

    def test_precommit_entry_has_plugin_acs(self):
        """T-PRECOMMIT-entry: .pre-commit-config.yaml acs-free-evals entry contains '--plugin acs' (AC-7)."""
        with open(PRECOMMIT_YAML, encoding="utf-8") as fh:
            content = fh.read()
        self.assertIn(
            "--plugin acs",
            content,
            "acs-free-evals entry must contain '--plugin acs' after MAR-30"
        )


# ---------------------------------------------------------------------------
# Live-repo regression: generalized validators pass acs (AC-4)
# ---------------------------------------------------------------------------

class TestLiveACSRegression(_CIShapeBase):
    """Run each generalized validator against the real repo structure (acs plugin).
    This proves AC-4: acs passes every applicable check with no empty-glob error.
    """

    def test_live_schema_step_passes_acs(self):
        """Live acs: schema step must pass (rc==0) against the real repo (AC-4)."""
        result = self._run_py(self.schema_py, REPO_ROOT)
        self.assertEqual(result.returncode, 0,
                         f"Live acs schema step failed. "
                         f"stderr={result.stderr!r} stdout={result.stdout!r}")

    def test_live_settings_step_passes_acs(self):
        """Live acs: settings step must pass (rc==0) against the real repo (AC-4).
        Requires jsonschema; the step installs it. We install it here if absent.
        """
        try:
            import jsonschema  # noqa: F401
        except ImportError:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "--quiet", "jsonschema"],
                check=False,
            )
        result = self._run_py(self.settings_py, REPO_ROOT)
        self.assertEqual(result.returncode, 0,
                         f"Live acs settings step failed. "
                         f"stderr={result.stderr!r} stdout={result.stdout!r}")

    def test_live_xsd_step_passes_acs(self):
        """Live acs: XSD step must pass (rc==0) against the real repo (AC-4)."""
        result = self._run_sh(self.xsd_sh, REPO_ROOT)
        self.assertEqual(result.returncode, 0,
                         f"Live acs XSD step failed. "
                         f"stderr={result.stderr!r} stdout={result.stdout!r}")

    def test_live_hooks_step_passes_acs(self):
        """Live acs: hooks step must pass (rc==0) against the real repo (AC-4)."""
        result = self._run_sh(self.hooks_sh, REPO_ROOT)
        self.assertEqual(result.returncode, 0,
                         f"Live acs hooks step failed. "
                         f"stderr={result.stderr!r} stdout={result.stdout!r}")

    def test_live_frontmatter_step_passes_acs(self):
        """Live acs: frontmatter step must pass (rc==0) against the real repo (AC-4)."""
        result = self._run_py(self.fm_py, REPO_ROOT)
        self.assertEqual(result.returncode, 0,
                         f"Live acs frontmatter step failed. "
                         f"stderr={result.stderr!r} stdout={result.stdout!r}")


if __name__ == "__main__":
    unittest.main()
