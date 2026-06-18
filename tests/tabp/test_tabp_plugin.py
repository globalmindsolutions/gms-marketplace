"""Deterministic tests for the tabp plugin scaffold and registration.

Covers:
  AC1 -- plugins/tabp/.claude-plugin/plugin.json exists, name=="tabp", skills-only shape.
  AC2 -- screen-cvs SKILL.md + 3 references present, frontmatter intact.
  AC3 -- marketplace.json tabp entry exists, entry name == plugin.json name == "tabp".
  AC4 -- this module is discovered by unittest discover -s tests and is green.
  AC5 -- skills-only shape proven by the TestSkillsOnlyShape assertions.

No model call. No subprocess. Stdlib only.
Run: python3 -m unittest tests.tabp.test_tabp_plugin -v
"""

import json
import os
import re
import unittest

# Three dirname calls: __file__ is tests/tabp/test_tabp_plugin.py
# dirname x1 -> tests/tabp
# dirname x2 -> tests
# dirname x3 -> repo root
# Mirrors tests/acs/test_acs_plugin.py line 22.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TABP_DIR = os.path.join(REPO_ROOT, "plugins", "tabp")
PLUGIN_JSON = os.path.join(TABP_DIR, ".claude-plugin", "plugin.json")
SKILL_DIR = os.path.join(TABP_DIR, "skills", "screen-cvs")
SKILL_MD = os.path.join(SKILL_DIR, "SKILL.md")
REFS_DIR = os.path.join(SKILL_DIR, "references")
MARKETPLACE = os.path.join(REPO_ROOT, ".claude-plugin", "marketplace.json")


def frontmatter(text, path):
    """Parse YAML frontmatter delimited by triple-dash lines.

    Mirrors tests/acs/test_skill_contracts.py lines 31-34.
    Returns (frontmatter_str, body_str).
    """
    parts = text.split("---\n", 2)
    assert len(parts) >= 3 and parts[0] == "", "%s: missing frontmatter" % path
    return parts[1], parts[2]


class TestPluginJson(unittest.TestCase):
    """Group 1 -- plugin.json validity (AC1)."""

    def test_plugin_json_exists(self):
        self.assertTrue(
            os.path.isfile(PLUGIN_JSON),
            "plugins/tabp/.claude-plugin/plugin.json not found at %s" % PLUGIN_JSON,
        )

    def test_plugin_json_parses(self):
        with open(PLUGIN_JSON, encoding="utf-8") as fh:
            data = json.load(fh)  # raises on invalid JSON
        self.assertIsInstance(data, dict)

    def test_plugin_json_name_is_tabp(self):
        with open(PLUGIN_JSON, encoding="utf-8") as fh:
            pj = json.load(fh)
        self.assertEqual(
            pj.get("name"),
            "tabp",
            "plugin.json name must be 'tabp', got %r" % pj.get("name"),
        )


class TestSkillsOnlyShape(unittest.TestCase):
    """Group 2 -- skills-only shape (AC1, AC5).

    Asserts that none of the full-shape directories are present under
    plugins/tabp/. Their absence ensures the CI shape-conditional steps
    (JSON Schema, settings validation, XSD, hook byte-compile) all skip
    for tabp -- see spec 02 CI table.
    """

    def test_no_acs_dir(self):
        acs_dir = os.path.join(TABP_DIR, ".acs")
        self.assertFalse(
            os.path.isdir(acs_dir),
            "plugins/tabp/.acs/ must not exist for a skills-only plugin",
        )

    def test_no_schemas_dir(self):
        schemas_dir = os.path.join(TABP_DIR, "schemas")
        self.assertFalse(
            os.path.isdir(schemas_dir),
            "plugins/tabp/schemas/ must not exist for a skills-only plugin",
        )

    def test_no_hooks_dir(self):
        hooks_dir = os.path.join(TABP_DIR, "hooks")
        self.assertFalse(
            os.path.isdir(hooks_dir),
            "plugins/tabp/hooks/ must not exist for a skills-only plugin",
        )

    def test_no_agents_dir(self):
        agents_dir = os.path.join(TABP_DIR, "agents")
        self.assertFalse(
            os.path.isdir(agents_dir),
            "plugins/tabp/agents/ must not exist for a skills-only plugin",
        )


class TestScreenCvsSkill(unittest.TestCase):
    """Group 3 -- skill structure and frontmatter (AC2)."""

    def _read_skill_md(self):
        with open(SKILL_MD, encoding="utf-8") as fh:
            return fh.read()

    def test_skill_md_exists(self):
        self.assertTrue(
            os.path.isfile(SKILL_MD),
            "plugins/tabp/skills/screen-cvs/SKILL.md not found at %s" % SKILL_MD,
        )

    def test_frontmatter_name(self):
        text = self._read_skill_md()
        fm, _body = frontmatter(text, SKILL_MD)
        self.assertRegex(
            fm,
            r"(?m)^name: screen-cvs$",
            "SKILL.md frontmatter must contain 'name: screen-cvs'",
        )

    def test_frontmatter_description(self):
        text = self._read_skill_md()
        fm, _body = frontmatter(text, SKILL_MD)
        self.assertRegex(
            fm,
            r"(?m)^description: \S",
            "SKILL.md frontmatter must contain a non-empty description",
        )

    def test_scoring_rubric_exists(self):
        path = os.path.join(REFS_DIR, "scoring-rubric.md")
        self.assertTrue(
            os.path.isfile(path),
            "references/scoring-rubric.md not found at %s" % path,
        )

    def test_fairness_guidelines_exists(self):
        path = os.path.join(REFS_DIR, "fairness-guidelines.md")
        self.assertTrue(
            os.path.isfile(path),
            "references/fairness-guidelines.md not found at %s" % path,
        )

    def test_scorecard_template_exists(self):
        path = os.path.join(REFS_DIR, "scorecard-template.md")
        self.assertTrue(
            os.path.isfile(path),
            "references/scorecard-template.md not found at %s" % path,
        )


class TestMarketplaceRegistration(unittest.TestCase):
    """Group 4 -- marketplace registration live regression (AC3).

    Mirrors tests/acs/test_marketplace_consistency.py lines 350-378
    (test_live_acs_entry_name_matches).
    """

    def _load(self):
        with open(MARKETPLACE, encoding="utf-8") as fh:
            mkt = json.load(fh)
        with open(PLUGIN_JSON, encoding="utf-8") as fh:
            pj = json.load(fh)
        return mkt, pj

    def _find_tabp_entry(self, mkt):
        for entry in mkt.get("plugins", []):
            if entry.get("name") == "tabp":
                return entry
        return None

    def test_tabp_entry_exists(self):
        mkt, _pj = self._load()
        entry = self._find_tabp_entry(mkt)
        self.assertIsNotNone(
            entry,
            "No 'tabp' entry found in .claude-plugin/marketplace.json plugins[]",
        )

    def test_tabp_entry_name_matches_plugin_json(self):
        mkt, pj = self._load()
        entry = self._find_tabp_entry(mkt)
        self.assertIsNotNone(entry, "tabp entry missing from marketplace.json")
        self.assertEqual(
            entry.get("name"),
            pj.get("name"),
            "marketplace.json tabp entry name %r != plugin.json name %r"
            % (entry.get("name"), pj.get("name")),
        )

    def test_plugin_json_name_is_tabp(self):
        _mkt, pj = self._load()
        self.assertEqual(
            pj.get("name"),
            "tabp",
            "plugin.json name must be 'tabp' (AC3 cross-check), got %r" % pj.get("name"),
        )


if __name__ == "__main__":
    unittest.main()
