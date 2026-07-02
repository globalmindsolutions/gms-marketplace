"""MAR-81 — Pin acs subagent models to explicit ids.

Asserts the repo-committed .acs/settings.json `models` block holds explicit,
version-stable model ids (claude-opus-4-8 / claude-sonnet-5) instead of the
generic runtime aliases ("opus" / "sonnet"), and that the file remains valid
against plugins/acs/schemas/settings.schema.json.

Uses the same stdlib-only approach as TestHighStakesPathsSettings /
TestDueDateSchema in test_acs_plugin.py (no jsonschema import) -- the CI
"Tests & validation" job does not install jsonschema (only a separate,
dedicated settings-schema-validation CI step does; see .github/workflows/ci.yml
around line 170).

Run:  python3 -m unittest tests.acs.test_mar81_settings_models_pinned -v
"""

import json
import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SETTINGS_PATH = os.path.join(REPO_ROOT, ".acs", "settings.json")
SCHEMA_PATH = os.path.join(REPO_ROOT, "plugins", "acs", "schemas", "settings.schema.json")


class SettingsModelsPinnedCase(unittest.TestCase):
    """Fixture: load the committed settings.json + schema once."""

    @classmethod
    def setUpClass(cls):
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            cls.settings = json.load(f)
        with open(SCHEMA_PATH, encoding="utf-8") as f:
            cls.schema = json.load(f)

    def test_planner_pinned(self):
        self.assertEqual(self.settings["models"]["planner"], "claude-opus-4-8")

    def test_verifier_pinned(self):
        self.assertEqual(self.settings["models"]["verifier"], "claude-opus-4-8")

    def test_coordinator_pinned(self):
        self.assertEqual(self.settings["models"]["coordinator"], "claude-opus-4-8")

    def test_executor_pinned(self):
        self.assertEqual(self.settings["models"]["executor"], "claude-sonnet-5")

    def test_settings_schema_valid(self):
        """Stdlib-only structural check (no jsonschema dependency): the schema's
        $defs.roleModel accepts a plain non-empty string for each models.* role
        (settings.schema.json's roleModel oneOf first branch), and the four
        committed values satisfy that shape."""
        role_model_def = self.schema["$defs"]["roleModel"]
        string_branch = next(
            branch for branch in role_model_def["oneOf"]
            if branch.get("type") == "string"
        )
        self.assertEqual(string_branch.get("minLength"), 1)

        models = self.settings["models"]
        self.assertIsInstance(models, dict)
        for role in ("planner", "executor", "verifier", "coordinator"):
            self.assertIn(role, self.schema["properties"]["models"]["properties"])
            value = models[role]
            self.assertIsInstance(value, str)
            self.assertGreaterEqual(len(value), 1)

    def test_no_alias_literals_remain(self):
        models = self.settings["models"]
        for role in ("planner", "executor", "verifier", "coordinator"):
            self.assertNotIn(
                models[role],
                ("opus", "sonnet"),
                msg=f"models.{role} still holds a generic alias literal: {models[role]!r}",
            )


if __name__ == "__main__":
    unittest.main()
