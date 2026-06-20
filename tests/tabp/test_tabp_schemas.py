"""Deterministic tests for the tabp plugin JSON Schema contracts and samples.

Covers:
  AC-1 -- run.schema.json + history.schema.json + run/history samples exist with
           correct required fields, enums, and valid JSON.
  AC-4 -- evidence.schema.json requires non-empty `evidence` field (minLength:1);
           evidence sample has non-empty evidence strings.
  AC-5 -- decision.schema.json defines sign_off as nullable; decision sample has
           required fields.
  AC-6 -- Zero "acs:" prefix and zero ".acs/" token in any schema or sample file.

Framework: Python unittest (stdlib only). No jsonschema pip import.
Run: python3 -m unittest tests.tabp.test_tabp_schemas -v
"""

import json
import os
import unittest

# Three dirname calls: __file__ is tests/tabp/test_tabp_schemas.py
# dirname x1 -> tests/tabp
# dirname x2 -> tests
# dirname x3 -> repo root
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SCHEMAS_DIR = os.path.join(REPO_ROOT, "plugins", "tabp", "schemas")
SAMPLES_DIR = os.path.join(SCHEMAS_DIR, "samples")

SCHEMA_FILES = [
    "run.schema.json",
    "evidence.schema.json",
    "decision.schema.json",
    "history.schema.json",
    "lock.schema.json",
]

SAMPLE_FILES = [
    "run.sample.json",
    "evidence.sample.json",
    "decision.sample.json",
    "history.sample.json",
    "lock.sample.json",
]


def _load_json(path):
    """Load JSON from a file, raising AssertionError on failure."""
    with open(path, encoding="utf-8") as fh:
        content = fh.read()
    return json.loads(content), content


class TestTabpSchemaFiles(unittest.TestCase):
    """Structural assertions on the tabp schema files (TC-01..TC-06)."""

    def test_tc01_schema_files_exist_and_parse(self):
        """TC-01: All five schema files exist, parse as valid JSON, and have correct
        top-level $schema/$id keys with no acs: or .acs/ tokens. (AC-1,AC-4,AC-5,AC-6)
        """
        for name in SCHEMA_FILES:
            path = os.path.join(SCHEMAS_DIR, name)
            with self.subTest(schema=name):
                self.assertTrue(
                    os.path.isfile(path),
                    "Schema file not found: %s" % path,
                )
                with open(path, encoding="utf-8") as fh:
                    content = fh.read()
                try:
                    doc = json.loads(content)
                except json.JSONDecodeError as exc:
                    self.fail("Schema file is not valid JSON (%s): %s" % (name, exc))
                self.assertIsInstance(
                    doc, dict, "Schema file top-level must be an object: %s" % name
                )
                # $schema key must be present and correct
                self.assertIn("$schema", doc, "Missing $schema key in %s" % name)
                self.assertEqual(
                    doc["$schema"],
                    "https://json-schema.org/draft/2020-12/schema",
                    "$schema value incorrect in %s" % name,
                )
                # $id key must be present
                self.assertIn("$id", doc, "Missing $id key in %s" % name)
                schema_id = doc["$id"]
                # AC-6: $id must not contain "acs" substring
                self.assertNotIn(
                    "acs",
                    schema_id,
                    "$id contains 'acs' substring in %s: %r" % (name, schema_id),
                )
                # AC-6: $id must not contain ".acs/" substring
                self.assertNotIn(
                    ".acs/",
                    schema_id,
                    "$id contains '.acs/' substring in %s: %r" % (name, schema_id),
                )
                # AC-6: file content must not contain "acs:" anywhere
                self.assertNotIn(
                    "acs:",
                    content,
                    "Schema file content contains 'acs:' in %s" % name,
                )
                # AC-6: file content must not contain ".acs/" anywhere
                self.assertNotIn(
                    ".acs/",
                    content,
                    "Schema file content contains '.acs/' in %s" % name,
                )

    def test_tc02_run_schema_required_fields_and_enums(self):
        """TC-02: run.schema.json has correct required fields, status enum,
        state_write_mode enum, and usage.usage_source enum. (AC-1)
        """
        path = os.path.join(SCHEMAS_DIR, "run.schema.json")
        doc, _ = _load_json(path)

        required = doc.get("required", [])
        for field in ["run_id", "skill", "started_at", "status",
                      "state_write_mode", "usage", "candidates_screened", "jd_slug"]:
            self.assertIn(
                field, required,
                "run.schema.json 'required' missing field: %s" % field,
            )

        props = doc.get("properties", {})

        # status enum
        status_enum = props.get("status", {}).get("enum", [])
        for val in ["in_progress", "completed", "failed", "interrupted"]:
            self.assertIn(
                val, status_enum,
                "run.schema.json status enum missing value: %s" % val,
            )

        # state_write_mode enum
        swm_enum = props.get("state_write_mode", {}).get("enum", [])
        for val in ["helper", "instructed"]:
            self.assertIn(
                val, swm_enum,
                "run.schema.json state_write_mode enum missing value: %s" % val,
            )

        # usage.usage_source enum — usage is an inline object definition
        usage_def = props.get("usage", {})
        usage_props = usage_def.get("properties", {})
        usage_source_enum = usage_props.get("usage_source", {}).get("enum", [])
        for val in ["cowork", "unavailable"]:
            self.assertIn(
                val, usage_source_enum,
                "run.schema.json usage.usage_source enum missing value: %s" % val,
            )

    def test_tc03_evidence_schema_requires_nonempty_evidence(self):
        """TC-03: evidence.schema.json requires non-empty `evidence` field on each
        requirement item (minLength:1), and has correct band/recommendation enums.
        (AC-4)
        """
        path = os.path.join(SCHEMAS_DIR, "evidence.schema.json")
        doc, _ = _load_json(path)

        required = doc.get("required", [])
        self.assertIn(
            "requirements", required,
            "evidence.schema.json 'required' must include 'requirements'",
        )

        props = doc.get("properties", {})

        # requirements items definition
        req_def = props.get("requirements", {})
        items_def = req_def.get("items", {})
        items_required = items_def.get("required", [])
        self.assertIn(
            "evidence", items_required,
            "evidence.schema.json requirements items 'required' must include 'evidence'",
        )

        # evidence field on the item must have minLength:1
        item_props = items_def.get("properties", {})
        evidence_field = item_props.get("evidence", {})
        self.assertEqual(
            evidence_field.get("minLength"),
            1,
            "evidence.schema.json requirements.items.properties.evidence must have minLength:1",
        )

        # band enum
        band_enum = props.get("band", {}).get("enum", [])
        for val in ["Strong", "Moderate", "Weak"]:
            self.assertIn(
                val, band_enum,
                "evidence.schema.json band enum missing value: %s" % val,
            )

        # recommendation enum
        rec_enum = props.get("recommendation", {}).get("enum", [])
        for val in ["Recommend", "Hold", "Reject"]:
            self.assertIn(
                val, rec_enum,
                "evidence.schema.json recommendation enum missing value: %s" % val,
            )

    def test_tc04_decision_schema_sign_off_nullable(self):
        """TC-04: decision.schema.json has correct required fields and sign_off
        allows null. (AC-5)
        """
        path = os.path.join(SCHEMAS_DIR, "decision.schema.json")
        doc, _ = _load_json(path)

        required = doc.get("required", [])
        for field in ["run_id", "verification_passed", "presented_at"]:
            self.assertIn(
                field, required,
                "decision.schema.json 'required' missing field: %s" % field,
            )

        props = doc.get("properties", {})
        sign_off_def = props.get("sign_off", {})

        # sign_off must allow null — either via oneOf, anyOf, or type list
        allows_null = False
        if "oneOf" in sign_off_def:
            for variant in sign_off_def["oneOf"]:
                if variant.get("type") == "null":
                    allows_null = True
        if "anyOf" in sign_off_def:
            for variant in sign_off_def["anyOf"]:
                if variant.get("type") == "null":
                    allows_null = True
        if isinstance(sign_off_def.get("type"), list):
            if "null" in sign_off_def["type"]:
                allows_null = True
        self.assertTrue(
            allows_null,
            "decision.schema.json sign_off must allow null (oneOf/anyOf/type list)",
        )

    def test_tc05_history_schema_runs_array_with_summary_fields(self):
        """TC-05: history.schema.json has runs array with required summary fields.
        (AC-1)
        """
        path = os.path.join(SCHEMAS_DIR, "history.schema.json")
        doc, _ = _load_json(path)

        required = doc.get("required", [])
        self.assertIn(
            "runs", required,
            "history.schema.json 'required' must include 'runs'",
        )

        props = doc.get("properties", {})
        runs_def = props.get("runs", {})
        # runs must be an array
        self.assertEqual(
            runs_def.get("type"),
            "array",
            "history.schema.json properties.runs.type must be 'array'",
        )

        # items definition with required summary fields
        items_def = runs_def.get("items", {})
        items_required = items_def.get("required", [])
        for field in ["run_id", "skill", "started_at", "status"]:
            self.assertIn(
                field, items_required,
                "history.schema.json runs items 'required' missing field: %s" % field,
            )

    def test_tc06_lock_schema_required_fields_and_types(self):
        """TC-06: lock.schema.json has correct required fields and pid is integer.
        (AC-6, lock)
        """
        path = os.path.join(SCHEMAS_DIR, "lock.schema.json")
        doc, _ = _load_json(path)

        required = doc.get("required", [])
        for field in ["pid", "hostname", "created_at"]:
            self.assertIn(
                field, required,
                "lock.schema.json 'required' missing field: %s" % field,
            )

        props = doc.get("properties", {})
        pid_def = props.get("pid", {})
        self.assertEqual(
            pid_def.get("type"),
            "integer",
            "lock.schema.json properties.pid.type must be 'integer'",
        )


class TestTabpSamples(unittest.TestCase):
    """Structural assertions on the tabp sample files (TC-07..TC-11)."""

    def test_tc07_run_sample_valid_with_required_fields_and_enums(self):
        """TC-07: run.sample.json is valid JSON with required fields and valid enum
        values. (AC-1)
        """
        path = os.path.join(SAMPLES_DIR, "run.sample.json")
        self.assertTrue(os.path.isfile(path), "run.sample.json not found: %s" % path)
        sample, _ = _load_json(path)

        for key in ["run_id", "skill", "started_at", "status",
                    "state_write_mode", "usage", "candidates_screened", "jd_slug"]:
            self.assertIn(
                key, sample,
                "run.sample.json missing required key: %s" % key,
            )
        self.assertIn(
            sample["status"],
            ["in_progress", "completed", "failed", "interrupted"],
            "run.sample.json status has invalid value: %r" % sample["status"],
        )
        self.assertIn(
            sample["state_write_mode"],
            ["helper", "instructed"],
            "run.sample.json state_write_mode has invalid value: %r"
            % sample["state_write_mode"],
        )
        self.assertIn(
            sample["usage"]["usage_source"],
            ["cowork", "unavailable"],
            "run.sample.json usage.usage_source has invalid value: %r"
            % sample["usage"]["usage_source"],
        )
        # Namespace guard on sample data
        self.assertFalse(
            str(sample["run_id"]).startswith("acs"),
            "run.sample.json run_id must not start with 'acs'",
        )

    def test_tc08_evidence_sample_nonempty_evidence(self):
        """TC-08: evidence.sample.json has at least one requirement with non-empty
        evidence, and valid band/recommendation values. (AC-4)
        """
        path = os.path.join(SAMPLES_DIR, "evidence.sample.json")
        self.assertTrue(os.path.isfile(path), "evidence.sample.json not found: %s" % path)
        sample, _ = _load_json(path)

        reqs = sample.get("requirements", [])
        self.assertIsInstance(reqs, list, "evidence.sample.json requirements must be a list")
        self.assertGreater(len(reqs), 0, "evidence.sample.json requirements must be non-empty")
        for i, req in enumerate(reqs):
            evidence_val = req.get("evidence", "")
            self.assertIsInstance(
                evidence_val, str,
                "evidence.sample.json requirements[%d].evidence must be a string" % i,
            )
            self.assertGreater(
                len(evidence_val),
                0,
                "evidence.sample.json requirements[%d].evidence must be non-empty" % i,
            )
        self.assertIn(
            sample.get("band"),
            ["Strong", "Moderate", "Weak"],
            "evidence.sample.json band has invalid value: %r" % sample.get("band"),
        )
        self.assertIn(
            sample.get("recommendation"),
            ["Recommend", "Hold", "Reject"],
            "evidence.sample.json recommendation has invalid value: %r"
            % sample.get("recommendation"),
        )

    def test_tc09_decision_sample_nullable_sign_off(self):
        """TC-09: decision.sample.json has required fields and sign_off is None or dict.
        (AC-5)
        """
        path = os.path.join(SAMPLES_DIR, "decision.sample.json")
        self.assertTrue(os.path.isfile(path), "decision.sample.json not found: %s" % path)
        sample, _ = _load_json(path)

        for key in ["run_id", "verification_passed", "presented_at"]:
            self.assertIn(
                key, sample,
                "decision.sample.json missing required key: %s" % key,
            )
        self.assertIn(
            "sign_off", sample,
            "decision.sample.json must have sign_off key (can be null or object)",
        )
        sign_off = sample["sign_off"]
        self.assertTrue(
            sign_off is None or isinstance(sign_off, dict),
            "decision.sample.json sign_off must be null or an object, got: %r" % sign_off,
        )

    def test_tc10_history_sample_runs_array_with_summary_fields(self):
        """TC-10: history.sample.json has valid runs array with required summary
        fields per entry. (AC-1)
        """
        path = os.path.join(SAMPLES_DIR, "history.sample.json")
        self.assertTrue(os.path.isfile(path), "history.sample.json not found: %s" % path)
        sample, _ = _load_json(path)

        runs = sample.get("runs", None)
        self.assertIsInstance(runs, list, "history.sample.json runs must be a list")
        for i, run in enumerate(runs):
            for key in ["run_id", "skill", "started_at", "status"]:
                self.assertIn(
                    key, run,
                    "history.sample.json runs[%d] missing key: %s" % (i, key),
                )

    def test_tc11_lock_sample_required_fields_and_types(self):
        """TC-11: lock.sample.json has required fields with correct types. (lock)
        """
        path = os.path.join(SAMPLES_DIR, "lock.sample.json")
        self.assertTrue(os.path.isfile(path), "lock.sample.json not found: %s" % path)
        sample, _ = _load_json(path)

        self.assertIn("pid", sample, "lock.sample.json missing 'pid' key")
        self.assertIsInstance(
            sample["pid"], int,
            "lock.sample.json pid must be an integer",
        )
        self.assertGreater(sample["pid"], 0, "lock.sample.json pid must be > 0")
        self.assertIn("hostname", sample, "lock.sample.json missing 'hostname' key")
        self.assertIsInstance(
            sample["hostname"], str,
            "lock.sample.json hostname must be a string",
        )
        self.assertGreater(
            len(sample["hostname"]), 0,
            "lock.sample.json hostname must be non-empty",
        )
        self.assertIn("created_at", sample, "lock.sample.json missing 'created_at' key")
        self.assertIsInstance(
            sample["created_at"], str,
            "lock.sample.json created_at must be a string",
        )
        self.assertGreater(
            len(sample["created_at"]), 0,
            "lock.sample.json created_at must be non-empty",
        )


class TestTabpNamespaceGuard(unittest.TestCase):
    """TC-12: No acs: or .acs/ substring anywhere in schema or sample files. (AC-6)"""

    def test_tc12_no_acs_tokens_in_schema_or_sample_files(self):
        """TC-12: Walk all files under plugins/tabp/schemas/ and assert that none
        contain 'acs:' or '.acs/' as substrings. (AC-6, HARD C-3)
        """
        self.assertTrue(
            os.path.isdir(SCHEMAS_DIR),
            "plugins/tabp/schemas/ directory not found: %s" % SCHEMAS_DIR,
        )
        violations = []
        for dirpath, _dirnames, filenames in os.walk(SCHEMAS_DIR):
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                with open(filepath, encoding="utf-8") as fh:
                    content = fh.read()
                if "acs:" in content:
                    violations.append("%s contains 'acs:'" % filepath)
                if ".acs/" in content:
                    violations.append("%s contains '.acs/'" % filepath)
        self.assertEqual(
            violations,
            [],
            "Namespace violations found:\n" + "\n".join(violations),
        )


if __name__ == "__main__":
    unittest.main()
