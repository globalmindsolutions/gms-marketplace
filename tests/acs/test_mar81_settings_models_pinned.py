"""MAR-81 — Pin acs subagent models to explicit ids and effort levels.

Asserts the repo-committed .acs/settings.json `models` block holds explicit,
version-stable model ids (claude-opus-4-8 / claude-sonnet-5) plus an explicit
reasoning-effort level per role (object form, mirroring the sibling `hirex`
repo's configuration), instead of the generic runtime aliases ("opus" /
"sonnet") with no effort, and that the file remains valid against
plugins/acs/schemas/settings.schema.json.

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

EXPECTED = {
    "planner": {"model": "claude-opus-4-8", "effort": "high"},
    "executor": {"model": "claude-sonnet-5", "effort": "high"},
    "verifier": {"model": "claude-opus-4-8", "effort": "high"},
    "coordinator": {"model": "claude-opus-4-8", "effort": "medium"},
}


class SettingsModelsPinnedCase(unittest.TestCase):
    """Fixture: load the committed settings.json + schema once."""

    @classmethod
    def setUpClass(cls):
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            cls.settings = json.load(f)
        with open(SCHEMA_PATH, encoding="utf-8") as f:
            cls.schema = json.load(f)

    def test_planner_pinned(self):
        self.assertEqual(self.settings["models"]["planner"], EXPECTED["planner"])

    def test_verifier_pinned(self):
        self.assertEqual(self.settings["models"]["verifier"], EXPECTED["verifier"])

    def test_coordinator_pinned(self):
        self.assertEqual(self.settings["models"]["coordinator"], EXPECTED["coordinator"])

    def test_executor_pinned(self):
        self.assertEqual(self.settings["models"]["executor"], EXPECTED["executor"])

    def test_settings_schema_valid(self):
        """Stdlib-only structural check (no jsonschema dependency): the schema's
        $defs.roleModel accepts an object {model, effort} for each models.*
        role (settings.schema.json's roleModel oneOf second branch), effort is
        one of the enumerated levels, and the four committed values satisfy
        that shape."""
        role_model_def = self.schema["$defs"]["roleModel"]
        object_branch = next(
            branch for branch in role_model_def["oneOf"]
            if branch.get("type") == "object"
        )
        effort_enum = object_branch["properties"]["effort"]["enum"]

        models = self.settings["models"]
        self.assertIsInstance(models, dict)
        for role in ("planner", "executor", "verifier", "coordinator"):
            self.assertIn(role, self.schema["properties"]["models"]["properties"])
            value = models[role]
            self.assertIsInstance(value, dict)
            self.assertEqual(set(value.keys()), {"model", "effort"})
            self.assertIsInstance(value["model"], str)
            self.assertGreaterEqual(len(value["model"]), 1)
            self.assertIn(value["effort"], effort_enum)

    def test_no_alias_literals_remain(self):
        models = self.settings["models"]
        for role in ("planner", "executor", "verifier", "coordinator"):
            self.assertNotIn(
                models[role]["model"],
                ("opus", "sonnet"),
                msg=f"models.{role}.model still holds a generic alias literal: {models[role]['model']!r}",
            )


if __name__ == "__main__":
    unittest.main()
