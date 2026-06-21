"""Deterministic TDD tests for plugins/tabp/helpers/tabp_helper.py (spec 02).

TC-01..TC-28 matching the spec 02 Test plan exactly, plus additional branch
coverage tests required to reach the 90% coverage gate.

Import path: sys.path.insert(0, abs-path-to-plugins/tabp/helpers)
then bare `import tabp_helper` — the pattern from tests/acs/cov_metrics_render.py:43-46.

No model calls. No network. No live Cowork subprocess. stdlib-only.

Run targeted: python3 -m unittest tests.tabp.test_tabp_helper -v
Run full:     python3 -m unittest discover -s tests -v
"""

import copy
import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest

# R-A mitigation: insert helpers dir onto sys.path, then import bare module.
# plugins/__init__.py and plugins/tabp/__init__.py do NOT exist, so a dotted
# import fails. This mirrors tests/acs/cov_metrics_render.py:43-46.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_HELPERS_DIR = os.path.join(_REPO_ROOT, "plugins", "tabp", "helpers")
_SCHEMAS_SAMPLES_DIR = os.path.join(_REPO_ROOT, "plugins", "tabp", "schemas", "samples")
_MODULE_PATH = os.path.join(_HELPERS_DIR, "tabp_helper.py")

if _HELPERS_DIR not in sys.path:
    sys.path.insert(0, _HELPERS_DIR)

# TC-01 (R-A tripwire): a SyntaxError in tabp_helper.py causes this import to
# fail, which CI catches even though ci.yml does not byte-compile helpers/.
import tabp_helper  # noqa: E402


def _load_sample(name):
    """Load a JSON sample from plugins/tabp/schemas/samples/."""
    path = os.path.join(_SCHEMAS_SAMPLES_DIR, name)
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _make_valid_run():
    """Return a valid run record matching run.sample.json shape."""
    return copy.deepcopy(_load_sample("run.sample.json"))


def _make_valid_evidence():
    """Return a valid evidence record matching evidence.sample.json shape."""
    return copy.deepcopy(_load_sample("evidence.sample.json"))


# ---------------------------------------------------------------------------
# Class TestTabpHelperImport — TC-01
# ---------------------------------------------------------------------------

class TestTabpHelperImport(unittest.TestCase):
    """TC-01: Module imports without error (R-A syntax-error tripwire)."""

    def test_tc01_module_import(self):
        """TC-01 (R-A): tabp_helper module is importable and is not None."""
        self.assertIsNotNone(tabp_helper)


# ---------------------------------------------------------------------------
# Class TestAtomicWrite — TC-02..TC-04
# ---------------------------------------------------------------------------

class TestAtomicWrite(unittest.TestCase):
    """TC-02..TC-04: _write_json and _read_json atomic round-trip."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_tc02_atomic_write_round_trip(self):
        """TC-02 (AC-1): Atomic write round-trip — file exists and round-trips correctly."""
        path = os.path.join(self._tmpdir, "out.json")
        tabp_helper._write_json(path, {"key": "value"})
        self.assertTrue(os.path.isfile(path))
        with open(path, "r", encoding="utf-8") as fh:
            content = fh.read()
        data = json.loads(content)
        self.assertEqual(data, {"key": "value"})
        self.assertTrue(content.endswith("\n"), "pretty JSON must end with newline")

    def test_tc03_atomic_write_is_indented(self):
        """TC-03 (AC-1): Atomic write produces pretty (indented) JSON."""
        path = os.path.join(self._tmpdir, "nested.json")
        tabp_helper._write_json(path, {"a": {"b": 1}})
        with open(path, "r", encoding="utf-8") as fh:
            content = fh.read()
        # Two-space indent means at minimum "  " appears in the content
        self.assertIn("\n  ", content, "pretty JSON must contain two-space indent")

    def test_tc04_atomic_write_leaves_no_temp_file(self):
        """TC-04 (AC-1): Atomic write leaves no .tabp-tmp-* file in the directory."""
        path = os.path.join(self._tmpdir, "clean.json")
        tabp_helper._write_json(path, {"x": 1})
        remaining = [f for f in os.listdir(self._tmpdir) if f.startswith(".tabp-tmp-")]
        self.assertEqual(remaining, [], "no .tabp-tmp-* files should remain after write")

    def test_read_json_missing_file_returns_none(self):
        """_read_json on a missing file returns None (tolerant read)."""
        result = tabp_helper._read_json(os.path.join(self._tmpdir, "no-such.json"))
        self.assertIsNone(result)

    def test_read_json_corrupt_file_returns_none(self):
        """_read_json on corrupt JSON returns None and warns to stderr."""
        path = os.path.join(self._tmpdir, "corrupt.json")
        with open(path, "w") as fh:
            fh.write("{not valid json}")
        result = tabp_helper._read_json(path)
        self.assertIsNone(result)

    def test_write_json_creates_nested_dirs(self):
        """_write_json creates intermediate directories when they don't exist."""
        path = os.path.join(self._tmpdir, "a", "b", "c.json")
        tabp_helper._write_json(path, {"deep": True})
        self.assertTrue(os.path.isfile(path))


# ---------------------------------------------------------------------------
# Class TestIsoTimestamps — _now_iso / _parse_iso
# ---------------------------------------------------------------------------

class TestIsoTimestamps(unittest.TestCase):
    """Test _now_iso and _parse_iso."""

    def test_now_iso_format(self):
        """_now_iso returns a string matching YYYY-MM-DDTHH:MM:SSZ."""
        import re
        ts = tabp_helper._now_iso()
        self.assertRegex(ts, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_parse_iso_valid(self):
        """_parse_iso parses a valid ISO string to an aware datetime."""
        from datetime import timezone
        dt = tabp_helper._parse_iso("2026-06-20T09:00:00Z")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.tzinfo, timezone.utc)

    def test_parse_iso_invalid_returns_none(self):
        """_parse_iso returns None for invalid input."""
        self.assertIsNone(tabp_helper._parse_iso("not-a-date"))
        self.assertIsNone(tabp_helper._parse_iso(None))
        self.assertIsNone(tabp_helper._parse_iso(12345))


# ---------------------------------------------------------------------------
# Class TestLock — TC-05..TC-10
# ---------------------------------------------------------------------------

class TestLock(unittest.TestCase):
    """TC-05..TC-10: _acquire_lock, _release_lock, _is_stale_lock."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        # tabp_dir is the .tabp/ directory itself
        self._tabp_dir = os.path.join(self._tmpdir, ".tabp")
        os.makedirs(self._tabp_dir, exist_ok=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _lock_path(self):
        return os.path.join(self._tabp_dir, ".lock")

    def test_tc05_lock_acquire_creates_lock_file(self):
        """TC-05 (AC-1, safety): _acquire_lock creates .lock file with pid/hostname/created_at."""
        tabp_helper._acquire_lock(self._tabp_dir)
        lock_path = self._lock_path()
        self.assertTrue(os.path.isfile(lock_path), ".lock file must exist after acquire")
        with open(lock_path, "r", encoding="utf-8") as fh:
            lock = json.load(fh)
        self.assertIn("pid", lock)
        self.assertIn("hostname", lock)
        self.assertIn("created_at", lock)
        self.assertEqual(lock["pid"], os.getpid())

    def test_tc06_reentrant_lock_same_pid_hostname(self):
        """TC-06 (AC-1, re-entrant branch): second _acquire_lock from same pid/hostname succeeds."""
        tabp_helper._acquire_lock(self._tabp_dir)
        # Second call should not raise
        try:
            tabp_helper._acquire_lock(self._tabp_dir)
        except Exception as exc:
            self.fail("re-entrant lock raised unexpectedly: %s" % exc)

    def test_tc07_foreign_nonstale_lock_raises_tabp_lock_error(self):
        """TC-07 (safety, blocked-lock branch): non-stale foreign lock raises TabpLockError."""
        # Write a lock with a different pid and different hostname, current time (not stale)
        lock_record = {
            "pid": os.getpid() + 99999,  # different pid
            "hostname": "some-other-host-xyz",  # different hostname
            "created_at": tabp_helper._now_iso(),
        }
        tabp_helper._write_json(self._lock_path(), lock_record)
        with self.assertRaises(tabp_helper.TabpLockError):
            tabp_helper._acquire_lock(self._tabp_dir)

    def test_tc08_stale_lock_same_host_raises_tabp_lock_error_with_report(self):
        """TC-08 (safety, stale-lock branch): stale lock on same host raises TabpLockError
        with 'stale' in the message (REPORT-not-steal behavior)."""
        # Use a pid that almost certainly does not exist (very large number)
        lock_record = {
            "pid": 999999999,  # very likely non-existent
            "hostname": socket.gethostname(),  # same host
            "created_at": tabp_helper._now_iso(),
        }
        tabp_helper._write_json(self._lock_path(), lock_record)
        with self.assertRaises(tabp_helper.TabpLockError) as ctx:
            tabp_helper._acquire_lock(self._tabp_dir)
        self.assertIn("stale", str(ctx.exception).lower(),
                      "TabpLockError for stale lock must mention 'stale'")

    def test_tc09_release_own_lock_removes_lock_file(self):
        """TC-09 (safety): _release_lock removes .lock when called by the owner."""
        tabp_helper._acquire_lock(self._tabp_dir)
        self.assertTrue(os.path.isfile(self._lock_path()))
        tabp_helper._release_lock(self._tabp_dir)
        self.assertFalse(os.path.isfile(self._lock_path()),
                         ".lock file must be removed after release")

    def test_tc10_release_no_lock_is_idempotent(self):
        """TC-10 (safety): _release_lock with no lock file raises no exception."""
        # Ensure no lock file
        lock_path = self._lock_path()
        if os.path.exists(lock_path):
            os.unlink(lock_path)
        try:
            tabp_helper._release_lock(self._tabp_dir)
        except Exception as exc:
            self.fail("_release_lock with no lock raised: %s" % exc)

    def test_tc_is_stale_lock_process_lookup_error(self):
        """stale-lock ProcessLookupError branch: same host, pid gone -> stale."""
        lock = {
            "pid": 999999999,  # very likely does not exist
            "hostname": socket.gethostname(),
            "created_at": tabp_helper._now_iso(),
        }
        # This should return True (stale) because os.kill raises ProcessLookupError
        result = tabp_helper._is_stale_lock(lock)
        self.assertTrue(result, "_is_stale_lock must return True for gone pid on same host")

    def test_tc_is_stale_lock_permission_error(self):
        """stale-lock PermissionError branch: same host, pid exists (pid=1) -> not stale."""
        lock = {
            "pid": 1,  # pid 1 (init/launchd) always exists; os.kill raises PermissionError
            "hostname": socket.gethostname(),
            "created_at": tabp_helper._now_iso(),
        }
        result = tabp_helper._is_stale_lock(lock)
        self.assertFalse(result, "_is_stale_lock must return False for existing process (PermissionError)")

    def test_tc_is_stale_lock_cross_host_old(self):
        """stale-lock cross-host age > 24h branch -> stale."""
        lock = {
            "pid": 12345,
            "hostname": "completely-different-host",
            "created_at": "2000-01-01T00:00:00Z",  # very old
        }
        result = tabp_helper._is_stale_lock(lock)
        self.assertTrue(result, "_is_stale_lock must return True for very old cross-host lock")

    def test_tc_is_stale_lock_cross_host_recent(self):
        """stale-lock cross-host age <= 24h branch -> not stale."""
        lock = {
            "pid": 12345,
            "hostname": "completely-different-host",
            "created_at": tabp_helper._now_iso(),  # just now
        }
        result = tabp_helper._is_stale_lock(lock)
        self.assertFalse(result, "_is_stale_lock must return False for recent cross-host lock")

    def test_is_stale_lock_unparseable_created_at(self):
        """stale-lock unparseable created_at -> conservative: not stale."""
        lock = {
            "pid": 12345,
            "hostname": "other-host",
            "created_at": "not-a-date",
        }
        result = tabp_helper._is_stale_lock(lock)
        self.assertFalse(result)

    def test_release_foreign_lock_does_not_unlink(self):
        """_release_lock with a foreign lock does nothing (does not remove it)."""
        foreign_lock = {
            "pid": 1,  # pid 1, not our pid
            "hostname": socket.gethostname(),
            "created_at": tabp_helper._now_iso(),
        }
        tabp_helper._write_json(self._lock_path(), foreign_lock)
        tabp_helper._release_lock(self._tabp_dir)
        # Lock should still exist since it's not ours
        self.assertTrue(os.path.isfile(self._lock_path()),
                        "foreign lock must not be removed")


# ---------------------------------------------------------------------------
# Class TestAppendOnlyHistory — TC-11..TC-14
# ---------------------------------------------------------------------------

class TestAppendOnlyHistory(unittest.TestCase):
    """TC-11..TC-14: _append_run_to_history, _update_run_in_history, _read_history."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._history_path = os.path.join(self._tmpdir, "history.json")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _write_history(self, data):
        with open(self._history_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)

    def _read_history(self):
        with open(self._history_path, "r", encoding="utf-8") as fh:
            return json.load(fh)

    def test_tc11_append_adds_entry_preserves_existing(self):
        """TC-11 (AC-1): append adds entry; existing entries are preserved."""
        self._write_history({"runs": [
            {"run_id": "run-A", "skill": "screen-cvs",
             "started_at": "2026-06-20T08:00:00Z", "status": "completed"}
        ]})
        tabp_helper._append_run_to_history(self._history_path, {
            "run_id": "run-B",
            "skill": "screen-cvs",
            "started_at": "2026-06-20T09:00:00Z",
            "status": "in_progress",
        })
        hist = self._read_history()
        self.assertEqual(len(hist["runs"]), 2)
        self.assertEqual(hist["runs"][0]["run_id"], "run-A",
                         "prior entry must be unchanged")
        self.assertEqual(hist["runs"][-1]["run_id"], "run-B")

    def test_tc12_runs_last_is_current_after_append(self):
        """TC-12 (AC-1): runs[-1] is the current run after append."""
        self._write_history({"runs": []})
        tabp_helper._append_run_to_history(self._history_path, {
            "run_id": "run-X",
            "skill": "screen-cvs",
            "started_at": "2026-06-20T10:00:00Z",
            "status": "in_progress",
        })
        hist = self._read_history()
        self.assertEqual(hist["runs"][-1]["status"], "in_progress",
                         "runs[-1] must be the appended run")

    def test_tc13_update_run_updates_only_matched_entry(self):
        """TC-13 (AC-1): _update_run_in_history updates only the matched entry."""
        t = "2026-06-20T10:30:00Z"
        self._write_history({"runs": [
            {"run_id": "run-A", "skill": "screen-cvs",
             "started_at": "2026-06-20T08:00:00Z", "status": "completed"},
            {"run_id": "run-B", "skill": "screen-cvs",
             "started_at": "2026-06-20T09:00:00Z", "status": "in_progress"},
        ]})
        tabp_helper._update_run_in_history(self._history_path, "run-B", {
            "status": "completed",
            "ended_at": t,
        })
        hist = self._read_history()
        # Prior entry must be unchanged
        self.assertEqual(hist["runs"][0]["status"], "completed",
                         "prior entry must not be changed")
        # Matched entry must be updated
        self.assertEqual(hist["runs"][1]["status"], "completed",
                         "matched entry status must be updated")
        self.assertEqual(hist["runs"][1]["ended_at"], t,
                         "matched entry ended_at must be set")

    def test_tc14_history_absent_returns_safe_default(self):
        """TC-14 (AC-1): _read_history with absent file returns {'runs': []}."""
        result = tabp_helper._read_history(
            os.path.join(self._tmpdir, "nonexistent.json")
        )
        self.assertEqual(result, {"runs": []})

    def test_update_run_in_history_no_match_appends(self):
        """_update_run_in_history with no matching run_id appends a new entry (recovery path)."""
        self._write_history({"runs": [
            {"run_id": "run-A", "skill": "screen-cvs",
             "started_at": "2026-06-20T08:00:00Z", "status": "completed"},
        ]})
        tabp_helper._update_run_in_history(self._history_path, "run-MISSING", {
            "status": "completed",
        })
        hist = self._read_history()
        # Should have appended a new entry
        self.assertEqual(len(hist["runs"]), 2)
        self.assertEqual(hist["runs"][-1]["run_id"], "run-MISSING")

    def test_read_history_corrupt_returns_safe_default(self):
        """_read_history with corrupt JSON returns {'runs': []}."""
        path = os.path.join(self._tmpdir, "corrupt.json")
        with open(path, "w") as fh:
            fh.write("{invalid}")
        result = tabp_helper._read_history(path)
        self.assertEqual(result, {"runs": []})


# ---------------------------------------------------------------------------
# Class TestValidator — TC-15..TC-23
# ---------------------------------------------------------------------------

class TestValidator(unittest.TestCase):
    """TC-15..TC-23: _validate_record across all record types."""

    def test_tc15_run_sample_passes_validator(self):
        """TC-15 (AC-1): run.sample.json passes _validate_record(sample, 'run')."""
        sample = _load_sample("run.sample.json")
        # Should not raise
        tabp_helper._validate_record(sample, "run")

    def test_tc16_evidence_sample_passes_validator(self):
        """TC-16 (AC-4): evidence.sample.json passes _validate_record(sample, 'evidence')."""
        sample = _load_sample("evidence.sample.json")
        tabp_helper._validate_record(sample, "evidence")

    def test_tc17_evidence_empty_evidence_field_raises(self):
        """TC-17 (AC-4): evidence with empty evidence field raises TabpValidationError."""
        bad = _make_valid_evidence()
        bad["requirements"][0]["evidence"] = ""
        with self.assertRaises(tabp_helper.TabpValidationError) as ctx:
            tabp_helper._validate_record(bad, "evidence")
        self.assertIn("evidence", str(ctx.exception).lower(),
                      "error message must name the evidence field (AC-4 enforcement)")

    def test_tc18_evidence_absent_evidence_field_raises(self):
        """TC-18 (AC-4): evidence with absent evidence key raises TabpValidationError."""
        bad = _make_valid_evidence()
        del bad["requirements"][0]["evidence"]
        with self.assertRaises(tabp_helper.TabpValidationError):
            tabp_helper._validate_record(bad, "evidence")

    def test_tc19_decision_sample_passes_validator(self):
        """TC-19 (AC-5): decision.sample.json passes _validate_record(sample, 'decision')."""
        sample = _load_sample("decision.sample.json")
        tabp_helper._validate_record(sample, "decision")

    def test_tc20_history_sample_passes_validator(self):
        """TC-20 (AC-1): history.sample.json passes _validate_record(sample, 'history')."""
        sample = _load_sample("history.sample.json")
        tabp_helper._validate_record(sample, "history")

    def test_tc21_lock_sample_passes_validator(self):
        """TC-21: lock.sample.json passes _validate_record(sample, 'lock')."""
        sample = _load_sample("lock.sample.json")
        tabp_helper._validate_record(sample, "lock")

    def test_tc22_run_invalid_status_raises(self):
        """TC-22 (validation-failure branch): run record with invalid status raises TabpValidationError."""
        bad = _make_valid_run()
        bad["status"] = "unknown-status"
        with self.assertRaises(tabp_helper.TabpValidationError):
            tabp_helper._validate_record(bad, "run")

    def test_tc23_run_missing_required_field_raises(self):
        """TC-23 (validation-failure branch): run record missing run_id raises TabpValidationError
        and the message names run_id."""
        bad = _make_valid_run()
        del bad["run_id"]
        with self.assertRaises(tabp_helper.TabpValidationError) as ctx:
            tabp_helper._validate_record(bad, "run")
        self.assertIn("run_id", str(ctx.exception),
                      "error message must name the missing field 'run_id'")

    def test_validate_run_invalid_state_write_mode(self):
        """_validate_run raises on invalid state_write_mode."""
        bad = _make_valid_run()
        bad["state_write_mode"] = "bad-mode"
        with self.assertRaises(tabp_helper.TabpValidationError):
            tabp_helper._validate_run(bad)

    def test_validate_run_invalid_usage_source(self):
        """_validate_run raises when usage.usage_source is invalid."""
        bad = _make_valid_run()
        bad["usage"]["usage_source"] = "bad-source"
        with self.assertRaises(tabp_helper.TabpValidationError):
            tabp_helper._validate_run(bad)

    def test_validate_run_usage_not_dict(self):
        """_validate_run raises when usage is not a dict."""
        bad = _make_valid_run()
        bad["usage"] = "not-a-dict"
        with self.assertRaises(tabp_helper.TabpValidationError):
            tabp_helper._validate_run(bad)

    def test_validate_evidence_score_out_of_range(self):
        """_validate_evidence raises when score is out of [0, 100]."""
        bad = _make_valid_evidence()
        bad["score"] = 150
        with self.assertRaises(tabp_helper.TabpValidationError):
            tabp_helper._validate_evidence(bad)

    def test_validate_evidence_score_not_number(self):
        """_validate_evidence raises when score is not a number."""
        bad = _make_valid_evidence()
        bad["score"] = "high"
        with self.assertRaises(tabp_helper.TabpValidationError):
            tabp_helper._validate_evidence(bad)

    def test_validate_evidence_invalid_must_have_gate(self):
        """_validate_evidence raises when must_have_gate doesn't match pattern."""
        bad = _make_valid_evidence()
        bad["must_have_gate"] = "Invalid"
        with self.assertRaises(tabp_helper.TabpValidationError):
            tabp_helper._validate_evidence(bad)

    def test_validate_evidence_must_have_gate_missing_prefix(self):
        """_validate_evidence raises when must_have_gate is 'Missing:' with empty suffix."""
        bad = _make_valid_evidence()
        bad["must_have_gate"] = "Missing:"
        with self.assertRaises(tabp_helper.TabpValidationError):
            tabp_helper._validate_evidence(bad)

    def test_validate_evidence_invalid_band(self):
        """_validate_evidence raises when band is invalid."""
        bad = _make_valid_evidence()
        bad["band"] = "Average"
        with self.assertRaises(tabp_helper.TabpValidationError):
            tabp_helper._validate_evidence(bad)

    def test_validate_evidence_invalid_recommendation(self):
        """_validate_evidence raises when recommendation is invalid."""
        bad = _make_valid_evidence()
        bad["recommendation"] = "Maybe"
        with self.assertRaises(tabp_helper.TabpValidationError):
            tabp_helper._validate_evidence(bad)

    def test_validate_evidence_requirements_not_list(self):
        """_validate_evidence raises when requirements is not a list."""
        bad = _make_valid_evidence()
        bad["requirements"] = "not-a-list"
        with self.assertRaises(tabp_helper.TabpValidationError):
            tabp_helper._validate_evidence(bad)

    def test_validate_evidence_requirement_not_dict(self):
        """_validate_evidence raises when a requirement element is not a dict."""
        bad = _make_valid_evidence()
        bad["requirements"] = ["not-a-dict"]
        with self.assertRaises(tabp_helper.TabpValidationError):
            tabp_helper._validate_evidence(bad)

    def test_validate_evidence_requirement_missing_subfield(self):
        """_validate_evidence raises when a requirement is missing a sub-field."""
        bad = _make_valid_evidence()
        del bad["requirements"][0]["judgment"]
        with self.assertRaises(tabp_helper.TabpValidationError):
            tabp_helper._validate_evidence(bad)

    def test_validate_decision_not_bool(self):
        """_validate_decision raises when verification_passed is not a bool."""
        bad = copy.deepcopy(_load_sample("decision.sample.json"))
        bad["verification_passed"] = "yes"
        with self.assertRaises(tabp_helper.TabpValidationError):
            tabp_helper._validate_decision(bad)

    def test_validate_decision_sign_off_not_dict(self):
        """_validate_decision raises when sign_off is not null and not a dict."""
        bad = copy.deepcopy(_load_sample("decision.sample.json"))
        bad["sign_off"] = "invalid"
        with self.assertRaises(tabp_helper.TabpValidationError):
            tabp_helper._validate_decision(bad)

    def test_validate_decision_sign_off_missing_subfield(self):
        """_validate_decision raises when sign_off dict is missing required sub-field."""
        bad = copy.deepcopy(_load_sample("decision.sample.json"))
        bad["sign_off"] = {"recruiter": "Alice"}  # missing confirmed_at
        with self.assertRaises(tabp_helper.TabpValidationError):
            tabp_helper._validate_decision(bad)

    def test_validate_history_runs_not_list(self):
        """_validate_history raises when runs is not a list."""
        bad = {"runs": "not-a-list"}
        with self.assertRaises(tabp_helper.TabpValidationError):
            tabp_helper._validate_history(bad)

    def test_validate_history_run_not_dict(self):
        """_validate_history raises when a run summary element is not a dict."""
        bad = {"runs": ["not-a-dict"]}
        with self.assertRaises(tabp_helper.TabpValidationError):
            tabp_helper._validate_history(bad)

    def test_validate_history_run_missing_required(self):
        """_validate_history raises when a run summary is missing a required field."""
        bad = {"runs": [{"run_id": "run-A", "skill": "screen-cvs", "started_at": "2026-06-20T08:00:00Z"}]}
        with self.assertRaises(tabp_helper.TabpValidationError):
            tabp_helper._validate_history(bad)

    def test_validate_lock_pid_not_int(self):
        """_validate_lock raises when pid is not an int."""
        bad = copy.deepcopy(_load_sample("lock.sample.json"))
        bad["pid"] = "12345"
        with self.assertRaises(tabp_helper.TabpValidationError):
            tabp_helper._validate_lock(bad)

    def test_validate_lock_pid_zero(self):
        """_validate_lock raises when pid is 0 (must be >= 1)."""
        bad = copy.deepcopy(_load_sample("lock.sample.json"))
        bad["pid"] = 0
        with self.assertRaises(tabp_helper.TabpValidationError):
            tabp_helper._validate_lock(bad)

    def test_validate_lock_hostname_empty(self):
        """_validate_lock raises when hostname is empty string."""
        bad = copy.deepcopy(_load_sample("lock.sample.json"))
        bad["hostname"] = ""
        with self.assertRaises(tabp_helper.TabpValidationError):
            tabp_helper._validate_lock(bad)

    def test_validate_lock_hostname_not_string(self):
        """_validate_lock raises when hostname is not a string."""
        bad = copy.deepcopy(_load_sample("lock.sample.json"))
        bad["hostname"] = 12345
        with self.assertRaises(tabp_helper.TabpValidationError):
            tabp_helper._validate_lock(bad)

    def test_validate_lock_created_at_empty(self):
        """_validate_lock raises when created_at is empty string."""
        bad = copy.deepcopy(_load_sample("lock.sample.json"))
        bad["created_at"] = ""
        with self.assertRaises(tabp_helper.TabpValidationError):
            tabp_helper._validate_lock(bad)

    def test_validate_lock_created_at_not_string(self):
        """_validate_lock raises when created_at is not a string."""
        bad = copy.deepcopy(_load_sample("lock.sample.json"))
        bad["created_at"] = 12345
        with self.assertRaises(tabp_helper.TabpValidationError):
            tabp_helper._validate_lock(bad)

    def test_validate_record_unknown_type_raises(self):
        """_validate_record raises TabpValidationError for unknown record_type."""
        with self.assertRaises(tabp_helper.TabpValidationError):
            tabp_helper._validate_record({}, "unknown-type")

    def test_validate_evidence_missing_must_have_gate(self):
        """_validate_evidence raises when must_have_gate is missing."""
        bad = _make_valid_evidence()
        del bad["must_have_gate"]
        with self.assertRaises(tabp_helper.TabpValidationError):
            tabp_helper._validate_evidence(bad)


# ---------------------------------------------------------------------------
# Class TestSubcommands — in-process tests for subcommand implementations
# ---------------------------------------------------------------------------

class TestSubcommands(unittest.TestCase):
    """In-process tests for _cmd_run_start, _cmd_state_write, _cmd_decision_write,
    _cmd_sign_off_write, _cmd_run_finalize, _cmd_run_status, _cmd_validate,
    _cmd_usage_read. These exercise the actual subcommand code to reach coverage."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._project_dir = self._tmpdir
        self._tabp_dir = os.path.join(self._project_dir, ".tabp")
        os.makedirs(self._tabp_dir, exist_ok=True)
        # Save/restore sys.argv and sys.stdout/stderr
        self._orig_argv = sys.argv[:]
        self._orig_stdout = sys.stdout
        self._orig_stderr = sys.stderr

    def tearDown(self):
        import io
        import shutil
        sys.argv = self._orig_argv
        sys.stdout = self._orig_stdout
        sys.stderr = self._orig_stderr
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _capture(self):
        """Return (out_buffer, err_buffer) installed as sys.stdout/stderr."""
        import io
        out = io.StringIO()
        err = io.StringIO()
        sys.stdout = out
        sys.stderr = err
        return out, err

    def _restore_streams(self):
        sys.stdout = self._orig_stdout
        sys.stderr = self._orig_stderr

    def test_cmd_run_start_helper_mode(self):
        """_cmd_run_start with default helper mode writes run.json and history.json."""
        out, err = self._capture()
        try:
            tabp_helper._cmd_run_start([
                "--project-dir", self._project_dir,
                "--skill", "screen-cvs",
                "--jd-slug", "backend-engineer",
            ])
        finally:
            self._restore_streams()
        run_id = out.getvalue().strip()
        self.assertTrue(run_id.startswith("run-"), "stdout must be run_id")
        run_json = os.path.join(self._tabp_dir, "runs", run_id, "run.json")
        self.assertTrue(os.path.isfile(run_json))
        with open(run_json) as fh:
            run = json.load(fh)
        self.assertEqual(run["state_write_mode"], "helper")
        self.assertEqual(run["status"], "in_progress")
        self.assertEqual(run["skill"], "screen-cvs")
        self.assertEqual(run["jd_slug"], "backend-engineer")
        # History should have an entry
        hist = tabp_helper._read_history(os.path.join(self._tabp_dir, "history.json"))
        self.assertEqual(len(hist["runs"]), 1)
        self.assertEqual(hist["runs"][0]["run_id"], run_id)
        # Lock should exist
        self.assertTrue(os.path.isfile(os.path.join(self._tabp_dir, ".lock")))

    def test_cmd_run_start_instructed_mode(self):
        """_cmd_run_start with --state-write-mode instructed writes state_write_mode: 'instructed'."""
        out, err = self._capture()
        try:
            tabp_helper._cmd_run_start([
                "--project-dir", self._project_dir,
                "--skill", "screen-cvs",
                "--state-write-mode", "instructed",
            ])
        finally:
            self._restore_streams()
        run_id = out.getvalue().strip()
        run_json = os.path.join(self._tabp_dir, "runs", run_id, "run.json")
        with open(run_json) as fh:
            run = json.load(fh)
        self.assertEqual(run["state_write_mode"], "instructed")

    def test_cmd_run_start_lock_acquired(self):
        """_cmd_run_start acquires lock; a second run-start raises TabpLockError."""
        out, err = self._capture()
        try:
            tabp_helper._cmd_run_start([
                "--project-dir", self._project_dir,
                "--skill", "screen-cvs",
            ])
        finally:
            self._restore_streams()
        # Now manually set lock to a different pid so re-entrant check fails
        lock_path = os.path.join(self._tabp_dir, ".lock")
        lock = json.loads(open(lock_path).read())
        lock["pid"] = os.getpid() + 99999
        lock["hostname"] = "foreign-host"
        tabp_helper._write_json(lock_path, lock)
        # Second run-start should fail on lock
        with self.assertRaises(tabp_helper.TabpLockError):
            tabp_helper._cmd_run_start([
                "--project-dir", self._project_dir,
                "--skill", "screen-cvs",
            ])

    def _do_run_start(self, mode="helper"):
        """Helper: run run-start and return run_id."""
        out, err = self._capture()
        try:
            tabp_helper._cmd_run_start([
                "--project-dir", self._project_dir,
                "--skill", "screen-cvs",
                "--jd-slug", "test-role",
                "--state-write-mode", mode,
            ])
        finally:
            self._restore_streams()
        return out.getvalue().strip()

    def test_cmd_state_write(self):
        """_cmd_state_write validates and writes evidence JSON."""
        run_id = self._do_run_start()
        evidence = _make_valid_evidence()
        evidence["run_id"] = run_id
        # Write evidence to a temp file
        data_file = os.path.join(self._tmpdir, "ev.json")
        with open(data_file, "w") as fh:
            json.dump(evidence, fh)
        dest_file = os.path.join(self._tabp_dir, "runs", run_id, "evidence-cand01.json")
        tabp_helper._cmd_state_write([
            "--project-dir", self._project_dir,
            "--run-id", run_id,
            "--file", dest_file,
            "--data-file", data_file,
        ])
        self.assertTrue(os.path.isfile(dest_file))
        with open(dest_file) as fh:
            saved = json.load(fh)
        self.assertEqual(saved["run_id"], run_id)

    def test_cmd_state_write_invalid_evidence_raises(self):
        """_cmd_state_write raises TabpValidationError on invalid evidence."""
        run_id = self._do_run_start()
        bad_evidence = _make_valid_evidence()
        bad_evidence["requirements"][0]["evidence"] = ""  # empty = AC-4 violation
        data_file = os.path.join(self._tmpdir, "bad_ev.json")
        with open(data_file, "w") as fh:
            json.dump(bad_evidence, fh)
        dest_file = os.path.join(self._tabp_dir, "runs", run_id, "evidence-bad.json")
        with self.assertRaises(tabp_helper.TabpValidationError):
            tabp_helper._cmd_state_write([
                "--project-dir", self._project_dir,
                "--run-id", run_id,
                "--file", dest_file,
                "--data-file", data_file,
            ])

    def test_cmd_decision_write_true(self):
        """_cmd_decision_write with verification-passed=true writes decision.json."""
        run_id = self._do_run_start()
        tabp_helper._cmd_decision_write([
            "--project-dir", self._project_dir,
            "--run-id", run_id,
            "--verification-passed", "true",
            "--verification-notes", "All evidence cited.",
        ])
        decision_path = os.path.join(self._tabp_dir, "runs", run_id, "decision.json")
        self.assertTrue(os.path.isfile(decision_path))
        with open(decision_path) as fh:
            dec = json.load(fh)
        self.assertTrue(dec["verification_passed"])
        self.assertEqual(dec["verification_notes"], "All evidence cited.")
        self.assertIsNone(dec["sign_off"])

    def test_cmd_decision_write_false(self):
        """_cmd_decision_write with verification-passed=false writes False."""
        run_id = self._do_run_start()
        tabp_helper._cmd_decision_write([
            "--project-dir", self._project_dir,
            "--run-id", run_id,
            "--verification-passed", "false",
        ])
        decision_path = os.path.join(self._tabp_dir, "runs", run_id, "decision.json")
        with open(decision_path) as fh:
            dec = json.load(fh)
        self.assertFalse(dec["verification_passed"])

    def test_cmd_decision_write_invalid_flag_exits(self):
        """_cmd_decision_write with invalid --verification-passed value calls sys.exit."""
        run_id = self._do_run_start()
        with self.assertRaises(SystemExit):
            tabp_helper._cmd_decision_write([
                "--project-dir", self._project_dir,
                "--run-id", run_id,
                "--verification-passed", "maybe",
            ])

    def test_cmd_sign_off_write(self):
        """_cmd_sign_off_write populates sign_off on an existing decision.json."""
        run_id = self._do_run_start()
        # First write the decision
        tabp_helper._cmd_decision_write([
            "--project-dir", self._project_dir,
            "--run-id", run_id,
            "--verification-passed", "true",
        ])
        # Now sign off
        tabp_helper._cmd_sign_off_write([
            "--project-dir", self._project_dir,
            "--run-id", run_id,
            "--recruiter", "Alice",
            "--notes", "Approved.",
        ])
        decision_path = os.path.join(self._tabp_dir, "runs", run_id, "decision.json")
        with open(decision_path) as fh:
            dec = json.load(fh)
        self.assertIsNotNone(dec["sign_off"])
        self.assertEqual(dec["sign_off"]["recruiter"], "Alice")
        self.assertEqual(dec["sign_off"]["notes"], "Approved.")
        self.assertIn("confirmed_at", dec["sign_off"])

    def test_cmd_sign_off_write_no_notes(self):
        """_cmd_sign_off_write without --notes works (notes key absent)."""
        run_id = self._do_run_start()
        tabp_helper._cmd_decision_write([
            "--project-dir", self._project_dir,
            "--run-id", run_id,
            "--verification-passed", "true",
        ])
        tabp_helper._cmd_sign_off_write([
            "--project-dir", self._project_dir,
            "--run-id", run_id,
            "--recruiter", "Bob",
        ])
        decision_path = os.path.join(self._tabp_dir, "runs", run_id, "decision.json")
        with open(decision_path) as fh:
            dec = json.load(fh)
        self.assertNotIn("notes", dec["sign_off"])

    def test_cmd_sign_off_write_missing_decision_exits(self):
        """_cmd_sign_off_write exits 1 when decision.json does not exist."""
        run_id = "run-nonexistent"
        with self.assertRaises(SystemExit) as ctx:
            tabp_helper._cmd_sign_off_write([
                "--project-dir", self._project_dir,
                "--run-id", run_id,
                "--recruiter", "Alice",
            ])
        self.assertEqual(ctx.exception.code, tabp_helper.EXIT_ERROR)

    def test_cmd_run_finalize_completed(self):
        """_cmd_run_finalize with status=completed finalizes run and releases lock."""
        run_id = self._do_run_start()
        tabp_helper._cmd_run_finalize([
            "--project-dir", self._project_dir,
            "--run-id", run_id,
            "--status", "completed",
            "--candidates-screened", "5",
            "--usage-source", "unavailable",
        ])
        run_path = os.path.join(self._tabp_dir, "runs", run_id, "run.json")
        with open(run_path) as fh:
            run = json.load(fh)
        self.assertEqual(run["status"], "completed")
        self.assertIsNotNone(run["ended_at"])
        self.assertEqual(run["candidates_screened"], 5)
        # Lock must be released
        self.assertFalse(os.path.isfile(os.path.join(self._tabp_dir, ".lock")))

    def test_cmd_run_finalize_with_stop_reason(self):
        """_cmd_run_finalize with --stop-reason sets stop_reason in run.json."""
        run_id = self._do_run_start()
        tabp_helper._cmd_run_finalize([
            "--project-dir", self._project_dir,
            "--run-id", run_id,
            "--status", "failed",
            "--stop-reason", "Network error",
        ])
        run_path = os.path.join(self._tabp_dir, "runs", run_id, "run.json")
        with open(run_path) as fh:
            run = json.load(fh)
        self.assertEqual(run["status"], "failed")
        self.assertEqual(run["stop_reason"], "Network error")

    def test_cmd_run_finalize_missing_run_exits(self):
        """_cmd_run_finalize exits 1 when run.json does not exist."""
        with self.assertRaises(SystemExit) as ctx:
            tabp_helper._cmd_run_finalize([
                "--project-dir", self._project_dir,
                "--run-id", "run-nonexistent",
                "--status", "completed",
            ])
        self.assertEqual(ctx.exception.code, tabp_helper.EXIT_ERROR)

    def test_cmd_run_status_in_progress(self):
        """_cmd_run_status prints resume context when in_progress run exists."""
        self._do_run_start()
        out, err = self._capture()
        try:
            tabp_helper._cmd_run_status([
                "--project-dir", self._project_dir,
            ])
        finally:
            self._restore_streams()
        result = json.loads(out.getvalue())
        self.assertIn("run_id", result)
        self.assertIn("started_at", result)
        self.assertIn("candidates_screened", result)
        self.assertIn("evidence_files", result)

    def test_cmd_run_status_no_in_progress_exits(self):
        """_cmd_run_status exits 1 when no in_progress run."""
        # history.json with only completed runs
        history_path = os.path.join(self._tabp_dir, "history.json")
        tabp_helper._write_json(history_path, {"runs": [
            {"run_id": "run-old", "skill": "screen-cvs",
             "started_at": "2026-06-20T08:00:00Z", "status": "completed"},
        ]})
        with self.assertRaises(SystemExit) as ctx:
            tabp_helper._cmd_run_status([
                "--project-dir", self._project_dir,
            ])
        self.assertEqual(ctx.exception.code, tabp_helper.EXIT_ERROR)

    def test_cmd_run_status_with_evidence_files(self):
        """_cmd_run_status lists evidence files in the run directory."""
        run_id = self._do_run_start()
        # Create a fake evidence file
        run_dir = os.path.join(self._tabp_dir, "runs", run_id)
        ev_path = os.path.join(run_dir, "evidence-cand01.json")
        tabp_helper._write_json(ev_path, {"run_id": run_id, "candidate_id": "cand01"})
        out, err = self._capture()
        try:
            tabp_helper._cmd_run_status([
                "--project-dir", self._project_dir,
            ])
        finally:
            self._restore_streams()
        result = json.loads(out.getvalue())
        self.assertIn(ev_path, result["evidence_files"])

    def test_cmd_validate_run_ok(self):
        """_cmd_validate with valid run.json prints {"ok": true}."""
        tmp_file = os.path.join(self._tmpdir, "run.json")
        tabp_helper._write_json(tmp_file, _make_valid_run())
        out, err = self._capture()
        try:
            tabp_helper._cmd_validate([
                "--project-dir", self._project_dir,
                "--type", "run",
                "--file", tmp_file,
            ])
        finally:
            self._restore_streams()
        result = json.loads(out.getvalue())
        self.assertTrue(result["ok"])

    def test_cmd_validate_run_invalid_exits_3(self):
        """_cmd_validate with invalid run.json exits EXIT_VALIDATION_FAILED."""
        bad = _make_valid_run()
        bad["status"] = "invalid"
        tmp_file = os.path.join(self._tmpdir, "bad_run.json")
        tabp_helper._write_json(tmp_file, bad)
        out, err = self._capture()
        try:
            with self.assertRaises(SystemExit) as ctx:
                tabp_helper._cmd_validate([
                    "--project-dir", self._project_dir,
                    "--type", "run",
                    "--file", tmp_file,
                ])
        finally:
            self._restore_streams()
        self.assertEqual(ctx.exception.code, tabp_helper.EXIT_VALIDATION_FAILED)
        result = json.loads(out.getvalue())
        self.assertFalse(result["ok"])
        self.assertIn("error", result)

    def test_cmd_validate_evidence_ok(self):
        """_cmd_validate with valid evidence file prints {"ok": true}."""
        tmp_file = os.path.join(self._tmpdir, "ev.json")
        tabp_helper._write_json(tmp_file, _make_valid_evidence())
        out, err = self._capture()
        try:
            tabp_helper._cmd_validate([
                "--project-dir", self._project_dir,
                "--type", "evidence",
                "--file", tmp_file,
            ])
        finally:
            self._restore_streams()
        result = json.loads(out.getvalue())
        self.assertTrue(result["ok"])

    def test_cmd_validate_decision_ok(self):
        """_cmd_validate with valid decision file prints {"ok": true}."""
        tmp_file = os.path.join(self._tmpdir, "dec.json")
        tabp_helper._write_json(tmp_file, _load_sample("decision.sample.json"))
        out, err = self._capture()
        try:
            tabp_helper._cmd_validate([
                "--project-dir", self._project_dir,
                "--type", "decision",
                "--file", tmp_file,
            ])
        finally:
            self._restore_streams()
        result = json.loads(out.getvalue())
        self.assertTrue(result["ok"])

    def test_cmd_validate_history_ok(self):
        """_cmd_validate with valid history file prints {"ok": true}."""
        tmp_file = os.path.join(self._tmpdir, "hist.json")
        tabp_helper._write_json(tmp_file, _load_sample("history.sample.json"))
        out, err = self._capture()
        try:
            tabp_helper._cmd_validate([
                "--project-dir", self._project_dir,
                "--type", "history",
                "--file", tmp_file,
            ])
        finally:
            self._restore_streams()
        result = json.loads(out.getvalue())
        self.assertTrue(result["ok"])

    def test_cmd_validate_lock_ok(self):
        """_cmd_validate with valid lock file prints {"ok": true}."""
        tmp_file = os.path.join(self._tmpdir, "lock.json")
        tabp_helper._write_json(tmp_file, _load_sample("lock.sample.json"))
        out, err = self._capture()
        try:
            tabp_helper._cmd_validate([
                "--project-dir", self._project_dir,
                "--type", "lock",
                "--file", tmp_file,
            ])
        finally:
            self._restore_streams()
        result = json.loads(out.getvalue())
        self.assertTrue(result["ok"])

    def test_cmd_usage_read_stub_output(self):
        """_cmd_usage_read prints stub output shape with placeholder values."""
        out, err = self._capture()
        try:
            tabp_helper._cmd_usage_read([
                "--project-dir", self._project_dir,
            ])
        finally:
            self._restore_streams()
        result = json.loads(out.getvalue())
        self.assertIn("total_runs", result)
        self.assertIn("completed_runs", result)
        self.assertIn("failed_runs", result)
        self.assertIn("total_candidates_screened", result)
        self.assertIn("total_duration_seconds", result)
        self.assertIn("usage_note", result)
        self.assertIn("runs", result)
        self.assertEqual(result["total_runs"], 0)

    def test_main_no_subcommand_exits_1(self):
        """main() with no subcommand exits 1."""
        orig_argv = sys.argv[:]
        sys.argv = ["tabp_helper.py"]
        try:
            with self.assertRaises(SystemExit) as ctx:
                tabp_helper.main()
        finally:
            sys.argv = orig_argv
        self.assertEqual(ctx.exception.code, tabp_helper.EXIT_ERROR)

    def test_main_unknown_subcommand_exits_1(self):
        """main() with unknown subcommand exits 1."""
        orig_argv = sys.argv[:]
        sys.argv = ["tabp_helper.py", "no-such-command"]
        try:
            with self.assertRaises(SystemExit) as ctx:
                tabp_helper.main()
        finally:
            sys.argv = orig_argv
        self.assertEqual(ctx.exception.code, tabp_helper.EXIT_ERROR)

    def test_main_lock_error_exits_2(self):
        """main() propagates TabpLockError as exit code EXIT_LOCK_BLOCKED."""
        # Write a non-stale foreign lock
        lock_record = {
            "pid": os.getpid() + 99999,
            "hostname": "other-host",
            "created_at": tabp_helper._now_iso(),
        }
        tabp_helper._write_json(os.path.join(self._tabp_dir, ".lock"), lock_record)
        orig_argv = sys.argv[:]
        sys.argv = ["tabp_helper.py", "run-start",
                    "--project-dir", self._project_dir,
                    "--skill", "screen-cvs"]
        try:
            with self.assertRaises(SystemExit) as ctx:
                tabp_helper.main()
        finally:
            sys.argv = orig_argv
        self.assertEqual(ctx.exception.code, tabp_helper.EXIT_LOCK_BLOCKED)

    def test_load_schema_caching(self):
        """_load_schema caches schemas to avoid repeated I/O."""
        # Clear the cache
        tabp_helper._SCHEMA_CACHE.clear()
        schema1 = tabp_helper._load_schema("run")
        schema2 = tabp_helper._load_schema("run")
        self.assertIs(schema1, schema2, "cached schema should be the same object")


# ---------------------------------------------------------------------------
# Class TestRunStatus — TC-24..TC-25 (subprocess tests)
# ---------------------------------------------------------------------------

class TestRunStatus(unittest.TestCase):
    """TC-24..TC-25: run-status subcommand via subprocess."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._project_dir = self._tmpdir
        self._tabp_dir = os.path.join(self._project_dir, ".tabp")
        os.makedirs(self._tabp_dir, exist_ok=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _write_history(self, runs):
        path = os.path.join(self._tabp_dir, "history.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"runs": runs}, fh)

    def test_tc24_run_status_finds_in_progress_run(self):
        """TC-24 (AC-1): run-status finds latest in_progress run and exits 0."""
        self._write_history([
            {"run_id": "run-A", "skill": "screen-cvs",
             "started_at": "2026-06-20T08:00:00Z", "status": "completed",
             "candidates_screened": 3},
            {"run_id": "run-B", "skill": "screen-cvs",
             "started_at": "2026-06-20T09:00:00Z", "status": "in_progress",
             "candidates_screened": 1},
        ])
        result = subprocess.run(
            [sys.executable, _MODULE_PATH, "run-status",
             "--project-dir", self._project_dir],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0,
                         "run-status must exit 0 when in_progress run exists; stderr: %s"
                         % result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["run_id"], "run-B")

    def test_tc25_run_status_exits_1_when_no_in_progress(self):
        """TC-25: run-status exits 1 when no in_progress run exists."""
        self._write_history([
            {"run_id": "run-A", "skill": "screen-cvs",
             "started_at": "2026-06-20T08:00:00Z", "status": "completed",
             "candidates_screened": 3},
        ])
        result = subprocess.run(
            [sys.executable, _MODULE_PATH, "run-status",
             "--project-dir", self._project_dir],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 1,
                         "run-status must exit 1 when no in_progress run; stderr: %s"
                         % result.stderr)


# ---------------------------------------------------------------------------
# Class TestDegradedMode — TC-26
# ---------------------------------------------------------------------------

class TestDegradedMode(unittest.TestCase):
    """TC-26: --state-write-mode instructed branch."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._project_dir = self._tmpdir
        self._tabp_dir = os.path.join(self._project_dir, ".tabp")
        os.makedirs(self._tabp_dir, exist_ok=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_tc26_run_start_instructed_mode_writes_instructed(self):
        """TC-26 (AC-6, degraded-mode branch): run-start with --state-write-mode instructed
        writes state_write_mode: 'instructed' in run.json."""
        result = subprocess.run(
            [sys.executable, _MODULE_PATH, "run-start",
             "--project-dir", self._project_dir,
             "--skill", "screen-cvs",
             "--jd-slug", "backend-engineer",
             "--state-write-mode", "instructed"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0,
                         "run-start must exit 0; stderr: %s" % result.stderr)
        run_id = result.stdout.strip()
        self.assertTrue(run_id.startswith("run-"), "stdout must be the run_id")
        # Find and read run.json
        run_json_path = os.path.join(self._tabp_dir, "runs", run_id, "run.json")
        self.assertTrue(os.path.isfile(run_json_path), "run.json must exist")
        with open(run_json_path, "r", encoding="utf-8") as fh:
            run_data = json.load(fh)
        self.assertEqual(run_data["state_write_mode"], "instructed",
                         "state_write_mode must be 'instructed' when flag is passed")


# ---------------------------------------------------------------------------
# Class TestNamespaceGuard — TC-27..TC-28
# ---------------------------------------------------------------------------

class TestNamespaceGuard(unittest.TestCase):
    """TC-27..TC-28: AC-6 — no acs: or .acs/ in tabp_helper.py source."""

    def _read_source(self):
        with open(_MODULE_PATH, "r", encoding="utf-8") as fh:
            return fh.read()

    def test_tc27_no_acs_colon_or_dotacs_slash_in_source(self):
        """TC-27 (AC-6): tabp_helper.py contains no 'acs:' or '.acs/' substring."""
        source = self._read_source()
        self.assertNotIn("acs:", source,
                         "tabp_helper.py must not contain 'acs:' token (AC-6)")
        self.assertNotIn(".acs/", source,
                         "tabp_helper.py must not contain '.acs/' token (AC-6)")

    def test_tc28_no_import_acs_lib(self):
        """TC-28 (AC-6): tabp_helper.py does not import acs_lib."""
        source = self._read_source()
        self.assertNotIn("import acs_lib", source,
                         "tabp_helper.py must not import acs_lib")
        self.assertNotIn("from acs_lib", source,
                         "tabp_helper.py must not import from acs_lib")


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# Class TestMainDispatch — exercise main() with all subcommands for coverage
# ---------------------------------------------------------------------------

class TestMainDispatch(unittest.TestCase):
    """Exercise main() dispatch for all subcommands to cover elif branches."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._project_dir = self._tmpdir
        self._tabp_dir = os.path.join(self._project_dir, ".tabp")
        os.makedirs(self._tabp_dir, exist_ok=True)
        self._orig_argv = sys.argv[:]
        self._orig_stdout = sys.stdout
        self._orig_stderr = sys.stderr

    def tearDown(self):
        import io
        import shutil
        sys.argv = self._orig_argv
        sys.stdout = self._orig_stdout
        sys.stderr = self._orig_stderr
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _capture(self):
        import io
        out = io.StringIO()
        err = io.StringIO()
        sys.stdout = out
        sys.stderr = err
        return out, err

    def _restore(self):
        sys.stdout = self._orig_stdout
        sys.stderr = self._orig_stderr

    def _do_run_start_via_main(self):
        """Run run-start via main() and return (out, run_id)."""
        sys.argv = ["tabp_helper.py", "run-start",
                    "--project-dir", self._project_dir,
                    "--skill", "screen-cvs",
                    "--jd-slug", "test-role"]
        out, err = self._capture()
        try:
            tabp_helper.main()
        finally:
            self._restore()
        return out.getvalue().strip()

    def test_main_run_start(self):
        """main() dispatches to run-start successfully."""
        run_id = self._do_run_start_via_main()
        self.assertTrue(run_id.startswith("run-"))

    def test_main_state_write(self):
        """main() dispatches to state-write (line 885 covered)."""
        run_id = self._do_run_start_via_main()
        evidence = _make_valid_evidence()
        evidence["run_id"] = run_id
        data_file = os.path.join(self._tmpdir, "ev.json")
        with open(data_file, "w") as fh:
            json.dump(evidence, fh)
        dest_file = os.path.join(self._tabp_dir, "runs", run_id, "evidence-cand01.json")
        sys.argv = ["tabp_helper.py", "state-write",
                    "--project-dir", self._project_dir,
                    "--run-id", run_id,
                    "--file", dest_file,
                    "--data-file", data_file]
        out, err = self._capture()
        try:
            tabp_helper.main()
        finally:
            self._restore()
        self.assertTrue(os.path.isfile(dest_file))

    def test_main_decision_write(self):
        """main() dispatches to decision-write (line 887 covered)."""
        run_id = self._do_run_start_via_main()
        sys.argv = ["tabp_helper.py", "decision-write",
                    "--project-dir", self._project_dir,
                    "--run-id", run_id,
                    "--verification-passed", "true"]
        out, err = self._capture()
        try:
            tabp_helper.main()
        finally:
            self._restore()
        dec_path = os.path.join(self._tabp_dir, "runs", run_id, "decision.json")
        self.assertTrue(os.path.isfile(dec_path))

    def test_main_sign_off_write(self):
        """main() dispatches to sign-off-write (line 889 covered)."""
        run_id = self._do_run_start_via_main()
        # Write decision first
        dec_path = os.path.join(self._tabp_dir, "runs", run_id, "decision.json")
        tabp_helper._write_json(dec_path, {
            "run_id": run_id,
            "verification_passed": True,
            "verification_notes": None,
            "presented_at": tabp_helper._now_iso(),
            "sign_off": None,
        })
        sys.argv = ["tabp_helper.py", "sign-off-write",
                    "--project-dir", self._project_dir,
                    "--run-id", run_id,
                    "--recruiter", "Alice"]
        out, err = self._capture()
        try:
            tabp_helper.main()
        finally:
            self._restore()
        with open(dec_path) as fh:
            dec = json.load(fh)
        self.assertIsNotNone(dec["sign_off"])

    def test_main_run_finalize(self):
        """main() dispatches to run-finalize (line 891 covered)."""
        run_id = self._do_run_start_via_main()
        sys.argv = ["tabp_helper.py", "run-finalize",
                    "--project-dir", self._project_dir,
                    "--run-id", run_id,
                    "--status", "completed"]
        out, err = self._capture()
        try:
            tabp_helper.main()
        finally:
            self._restore()
        run_path = os.path.join(self._tabp_dir, "runs", run_id, "run.json")
        with open(run_path) as fh:
            run = json.load(fh)
        self.assertEqual(run["status"], "completed")

    def test_main_run_status(self):
        """main() dispatches to run-status (line 893 covered)."""
        run_id = self._do_run_start_via_main()
        sys.argv = ["tabp_helper.py", "run-status",
                    "--project-dir", self._project_dir]
        out, err = self._capture()
        try:
            tabp_helper.main()
        finally:
            self._restore()
        result = json.loads(out.getvalue())
        self.assertEqual(result["run_id"], run_id)

    def test_main_validate(self):
        """main() dispatches to validate (line 895 covered)."""
        tmp_file = os.path.join(self._tmpdir, "run.json")
        tabp_helper._write_json(tmp_file, _make_valid_run())
        sys.argv = ["tabp_helper.py", "validate",
                    "--project-dir", self._project_dir,
                    "--type", "run",
                    "--file", tmp_file]
        out, err = self._capture()
        try:
            tabp_helper.main()
        finally:
            self._restore()
        result = json.loads(out.getvalue())
        self.assertTrue(result["ok"])

    def test_main_usage_read(self):
        """main() dispatches to usage-read (line 897 covered)."""
        sys.argv = ["tabp_helper.py", "usage-read",
                    "--project-dir", self._project_dir]
        out, err = self._capture()
        try:
            tabp_helper.main()
        finally:
            self._restore()
        result = json.loads(out.getvalue())
        self.assertIn("total_runs", result)

    def test_main_validation_error_exits_3(self):
        """main() catches TabpValidationError and exits EXIT_VALIDATION_FAILED (lines 907-908)."""
        # Use state-write with invalid evidence to trigger validation error in main()
        run_id = self._do_run_start_via_main()
        bad_evidence = _make_valid_evidence()
        bad_evidence["requirements"][0]["evidence"] = ""
        data_file = os.path.join(self._tmpdir, "bad_ev.json")
        with open(data_file, "w") as fh:
            json.dump(bad_evidence, fh)
        dest_file = os.path.join(self._tabp_dir, "runs", run_id, "evidence-bad.json")
        sys.argv = ["tabp_helper.py", "state-write",
                    "--project-dir", self._project_dir,
                    "--run-id", run_id,
                    "--file", dest_file,
                    "--data-file", data_file]
        out, err = self._capture()
        try:
            with self.assertRaises(SystemExit) as ctx:
                tabp_helper.main()
        finally:
            self._restore()
        self.assertEqual(ctx.exception.code, tabp_helper.EXIT_VALIDATION_FAILED)


# ---------------------------------------------------------------------------
# Class TestCrossProcessLock — the lock lifecycle across SEPARATE processes
# ---------------------------------------------------------------------------

class TestCrossProcessLock(unittest.TestCase):
    """Regression for the lock lifecycle across separate OS processes.

    The screen-cvs coordinator invokes each subcommand as its own
    `python3 tabp_helper.py <subcommand>` process, so run-start and
    run-finalize never share a PID. The in-process TestSubcommands tests cannot
    observe this — they call the _cmd_* functions in one interpreter where
    os.getpid() is constant. These tests drive the real CLI via subprocess so a
    PID-coupled lock-release regression is caught: with PID-based ownership the
    lock leaks and every run after the first is blocked.
    """

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._project_dir = self._tmpdir
        self._tabp_dir = os.path.join(self._project_dir, ".tabp")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _run(self, *cli_args):
        return subprocess.run(
            [sys.executable, _MODULE_PATH, *cli_args],
            capture_output=True, text=True,
        )

    def test_finalize_releases_lock_across_processes(self):
        """run-finalize (a different process from run-start) releases the lock,
        and a subsequent run-start is not blocked."""
        started = self._run("run-start", "--project-dir", self._project_dir,
                             "--skill", "screen-cvs", "--jd-slug", "backend")
        self.assertEqual(started.returncode, 0, started.stderr)
        run_id = started.stdout.strip()
        lock_path = os.path.join(self._tabp_dir, ".lock")
        self.assertTrue(os.path.isfile(lock_path), "run-start must create the lock")

        finalized = self._run("run-finalize", "--project-dir", self._project_dir,
                              "--run-id", run_id, "--status", "completed",
                              "--candidates-screened", "3",
                              "--usage-source", "unavailable")
        self.assertEqual(finalized.returncode, 0, finalized.stderr)
        self.assertFalse(
            os.path.isfile(lock_path),
            "run-finalize in a separate process must release the lock "
            "(regression: PID-coupled ownership left it leaked)",
        )

        # A second run, in yet another process, must NOT be blocked.
        again = self._run("run-start", "--project-dir", self._project_dir,
                          "--skill", "screen-cvs", "--jd-slug", "backend")
        self.assertEqual(
            again.returncode, 0,
            "second run-start must succeed after a clean finalize; "
            "stderr=%r" % again.stderr,
        )
        self.assertNotEqual(again.stdout.strip(), run_id,
                            "second run must get a fresh run_id")

    def test_second_run_start_blocked_while_first_in_progress(self):
        """While the first run's lock is still held (no finalize), a second
        run-start in a new process is lock-blocked (exit 2)."""
        started = self._run("run-start", "--project-dir", self._project_dir,
                             "--skill", "screen-cvs")
        self.assertEqual(started.returncode, 0, started.stderr)
        blocked = self._run("run-start", "--project-dir", self._project_dir,
                            "--skill", "screen-cvs")
        self.assertEqual(blocked.returncode, tabp_helper.EXIT_LOCK_BLOCKED,
                         "a concurrent second run-start must be lock-blocked")


# ---------------------------------------------------------------------------
# Class TestLockOwnershipCrossProcess — run_id-scoped ownership (unit level)
# ---------------------------------------------------------------------------

class TestLockOwnershipCrossProcess(unittest.TestCase):
    """_lock_is_ours / _release_lock recognise run_id ownership regardless of PID."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._tabp_dir = os.path.join(self._tmpdir, ".tabp")
        os.makedirs(self._tabp_dir, exist_ok=True)
        self._lock_path = os.path.join(self._tabp_dir, ".lock")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_release_by_run_id_when_pid_differs(self):
        """A lock acquired by a now-gone process is released via matching run_id."""
        tabp_helper._write_json(self._lock_path, {
            "pid": os.getpid() + 99999,  # a different (gone) process
            "hostname": socket.gethostname(),
            "created_at": tabp_helper._now_iso(),
            "run_id": "run-xyz",
        })
        tabp_helper._release_lock(self._tabp_dir, "run-xyz")
        self.assertFalse(os.path.isfile(self._lock_path),
                         "release must remove a same-host lock with matching run_id")

    def test_no_release_when_run_id_differs(self):
        """A lock for a different run is never released."""
        tabp_helper._write_json(self._lock_path, {
            "pid": os.getpid() + 99999,
            "hostname": socket.gethostname(),
            "created_at": tabp_helper._now_iso(),
            "run_id": "run-other",
        })
        tabp_helper._release_lock(self._tabp_dir, "run-mine")
        self.assertTrue(os.path.isfile(self._lock_path),
                        "release must not remove a lock owned by a different run")

    def test_no_release_cross_host_even_with_matching_run_id(self):
        """A lock on a different host is never released, even if run_id matches."""
        tabp_helper._write_json(self._lock_path, {
            "pid": 4242,
            "hostname": "some-other-host",
            "created_at": tabp_helper._now_iso(),
            "run_id": "run-xyz",
        })
        tabp_helper._release_lock(self._tabp_dir, "run-xyz")
        self.assertTrue(os.path.isfile(self._lock_path),
                        "release must not remove a cross-host lock")

    def test_acquire_resume_reentrant_by_run_id(self):
        """A new process resuming the same run_id re-enters rather than blocking."""
        tabp_helper._write_json(self._lock_path, {
            "pid": os.getpid() + 99999,  # acquired by a prior (gone) process
            "hostname": socket.gethostname(),
            "created_at": tabp_helper._now_iso(),
            "run_id": "run-resume",
        })
        # Must NOT raise: same host + matching run_id == ours (resume).
        tabp_helper._acquire_lock(self._tabp_dir, "run-resume")


# ---------------------------------------------------------------------------
# Class TestSettingsRead — settings-read subcommand (MAR-3 rewrite)
# ---------------------------------------------------------------------------

class TestSettingsRead(unittest.TestCase):
    """TC-SR-01..07: settings-read resolves <project>/tabp settings.json at project root.

    MAR-3 corrects the reader path from <project>/.tabp/settings.json to the
    project-root literal filename "tabp settings.json". The output is now an
    observable envelope with settings_source/from_file/from_default fields.
    """

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._project_dir = self._tmpdir
        # No .tabp/ needed — file lives at project root as "tabp settings.json"
        self._settings_path = os.path.join(self._project_dir, "tabp settings.json")
        self._orig_argv = sys.argv[:]
        self._orig_stdout = sys.stdout
        self._orig_stderr = sys.stderr

    def tearDown(self):
        import shutil
        sys.argv = self._orig_argv
        sys.stdout = self._orig_stdout
        sys.stderr = self._orig_stderr
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _read_envelope(self):
        """Call _cmd_settings_read and return the full JSON envelope dict."""
        import io
        out = io.StringIO()
        sys.stdout = out
        try:
            tabp_helper._cmd_settings_read(["--project-dir", self._project_dir])
        finally:
            sys.stdout = self._orig_stdout
        return json.loads(out.getvalue())

    def _read_settings(self):
        """Return result["settings"] from the envelope — convenience for simple assertions."""
        return self._read_envelope()["settings"]

    # --- TC-SR-01: file present at project root, all five fields overridden ---

    def test_tc_sr_01_file_at_project_root_overrides_all_fields(self):
        """TC-SR-01 (AC-1): tabp settings.json at project root; all five values read."""
        payload = {
            "screening_model": "haiku",
            "synthesis_model": "haiku-mini",
            "cv_folder": "/abs/cvs",
            "jd_folder": "/abs/jds",
            "state_write_mode": "instructed",
        }
        tabp_helper._write_json(self._settings_path, payload)
        envelope = self._read_envelope()
        self.assertEqual(envelope["settings"]["screening_model"], "haiku")
        self.assertEqual(envelope["settings"]["synthesis_model"], "haiku-mini")
        self.assertEqual(envelope["settings"]["cv_folder"], "/abs/cvs")
        self.assertEqual(envelope["settings"]["jd_folder"], "/abs/jds")
        self.assertEqual(envelope["settings"]["state_write_mode"], "instructed")
        self.assertEqual(envelope["settings_source"], "file")
        self.assertCountEqual(envelope["from_file"], list(tabp_helper._SETTINGS_DEFAULTS.keys()))

    # --- TC-SR-02: file absent -> "absent", full defaults ---

    def test_tc_sr_02_absent_file_returns_defaults_and_absent_source(self):
        """TC-SR-02 (AC-3): No tabp settings.json -> defaults + settings_source=absent."""
        envelope = self._read_envelope()
        self.assertEqual(envelope["settings"], tabp_helper._SETTINGS_DEFAULTS)
        self.assertEqual(envelope["settings_source"], "absent")
        self.assertEqual(envelope["from_file"], [])
        self.assertCountEqual(envelope["from_default"], list(tabp_helper._SETTINGS_DEFAULTS.keys()))

    # --- TC-SR-03: corrupt file -> "corrupt", full defaults ---

    def test_tc_sr_03_corrupt_file_returns_defaults_and_corrupt_source(self):
        """TC-SR-03 (AC-3): Corrupt file -> defaults + settings_source=corrupt."""
        import io
        with open(self._settings_path, "w") as fh:
            fh.write("{not json")
        sys.stderr = io.StringIO()  # swallow the _read_json corruption warning
        envelope = self._read_envelope()
        self.assertEqual(envelope["settings"], tabp_helper._SETTINGS_DEFAULTS)
        self.assertEqual(envelope["settings_source"], "corrupt")
        self.assertEqual(envelope["from_file"], [])
        self.assertCountEqual(envelope["from_default"], list(tabp_helper._SETTINGS_DEFAULTS.keys()))

    # --- TC-SR-04: partial file -> partial from_file, partial from_default ---

    def test_tc_sr_04_partial_file_merges_and_tracks_origins(self):
        """TC-SR-04 (AC-2, AC-3): Partial file -> correct merge and from_file/from_default."""
        tabp_helper._write_json(self._settings_path, {"screening_model": "haiku"})
        envelope = self._read_envelope()
        self.assertEqual(envelope["settings"]["screening_model"], "haiku")
        self.assertEqual(envelope["settings"]["synthesis_model"],
                         tabp_helper._SETTINGS_DEFAULTS["synthesis_model"])
        self.assertEqual(envelope["from_file"], ["screening_model"])
        self.assertCountEqual(
            envelope["from_default"],
            ["synthesis_model", "cv_folder", "jd_folder", "state_write_mode"]
        )
        self.assertEqual(envelope["settings_source"], "file")

    # --- TC-SR-05: all five fields in file -> from_default is empty ---

    def test_tc_sr_05_all_five_fields_from_file(self):
        """TC-SR-05 (AC-2): Five-field file -> all in from_file, from_default empty."""
        payload = {
            "screening_model": "s1",
            "synthesis_model": "o1",
            "cv_folder": "./c",
            "jd_folder": "./j",
            "state_write_mode": "helper",
        }
        tabp_helper._write_json(self._settings_path, payload)
        envelope = self._read_envelope()
        for k, v in payload.items():
            self.assertEqual(envelope["settings"][k], v)
        self.assertCountEqual(envelope["from_file"], list(tabp_helper._SETTINGS_DEFAULTS.keys()))
        self.assertEqual(envelope["from_default"], [])

    # --- TC-SR-06: file with unknown key -> unknown key absent from settings ---

    def test_tc_sr_06_unknown_key_in_file_is_ignored(self):
        """TC-SR-06 (AC-2): Unknown key in file not surfaced; known keys resolved."""
        tabp_helper._write_json(self._settings_path, {
            "screening_model": "haiku",
            "unknown_key": "bad",
        })
        envelope = self._read_envelope()
        self.assertNotIn("unknown_key", envelope["settings"])
        self.assertEqual(envelope["settings"]["screening_model"], "haiku")

    # --- TC-SR-07: main() dispatches settings-read, envelope has "settings" key ---

    def test_tc_sr_07_main_dispatch_settings_read_returns_envelope(self):
        """TC-SR-07 (AC-1): main() dispatches settings-read; envelope contains settings key."""
        import io
        sys.argv = ["tabp_helper.py", "settings-read",
                    "--project-dir", self._project_dir]
        out = io.StringIO()
        sys.stdout = out
        try:
            tabp_helper.main()
        finally:
            sys.stdout = self._orig_stdout
        parsed = json.loads(out.getvalue())
        self.assertIn("settings", parsed)
        self.assertIn("settings_source", parsed)
        self.assertIn("from_file", parsed)
        self.assertIn("from_default", parsed)
        self.assertIn("screening_model", parsed["settings"])


# ---------------------------------------------------------------------------
# Class TestSettingsValidate — _validate_settings and _cmd_settings_validate
# ---------------------------------------------------------------------------

class TestSettingsValidate(unittest.TestCase):
    """TC-SV-01..15: _validate_settings and _cmd_settings_validate (MAR-3)."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._orig_stdout = sys.stdout
        self._orig_stderr = sys.stderr
        self._orig_argv = sys.argv[:]

    def tearDown(self):
        import shutil
        sys.stdout = self._orig_stdout
        sys.stderr = self._orig_stderr
        sys.argv = self._orig_argv
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _call_validate(self, args):
        """Call _cmd_settings_validate and return (stdout_str, exit_code)."""
        import io
        out = io.StringIO()
        sys.stdout = out
        try:
            tabp_helper._cmd_settings_validate(args)
            code = 0
        except SystemExit as exc:
            code = exc.code
        finally:
            sys.stdout = self._orig_stdout
        return out.getvalue(), code

    # --- TC-SV-01: empty dict is valid ---

    def test_tc_sv_01_empty_dict_is_valid(self):
        """TC-SV-01 (AC-2): _validate_settings({}) — all optional, no exception."""
        tabp_helper._validate_settings({})  # must not raise

    # --- TC-SV-02: all five valid fields ---

    def test_tc_sv_02_all_five_valid_fields(self):
        """TC-SV-02 (AC-2): All five valid fields — no exception."""
        tabp_helper._validate_settings({
            "screening_model": "sonnet",
            "synthesis_model": "opus",
            "cv_folder": "./cvs",
            "jd_folder": "./jds",
            "state_write_mode": "helper",
        })

    # --- TC-SV-03: screening_model wrong type ---

    def test_tc_sv_03_screening_model_wrong_type(self):
        """TC-SV-03 (AC-2): screening_model is int, not str — TabpValidationError."""
        with self.assertRaises(tabp_helper.TabpValidationError) as ctx:
            tabp_helper._validate_settings({"screening_model": 42})
        self.assertIn("screening_model", str(ctx.exception))

    # --- TC-SV-04: synthesis_model is None ---

    def test_tc_sv_04_synthesis_model_none(self):
        """TC-SV-04 (AC-2): synthesis_model is None — TabpValidationError."""
        with self.assertRaises(tabp_helper.TabpValidationError):
            tabp_helper._validate_settings({"synthesis_model": None})

    # --- TC-SV-05: cv_folder is int ---

    def test_tc_sv_05_cv_folder_int(self):
        """TC-SV-05 (AC-2): cv_folder is 123 — TabpValidationError."""
        with self.assertRaises(tabp_helper.TabpValidationError):
            tabp_helper._validate_settings({"cv_folder": 123})

    # --- TC-SV-06: jd_folder is list ---

    def test_tc_sv_06_jd_folder_list(self):
        """TC-SV-06 (AC-2): jd_folder is ["list"] — TabpValidationError."""
        with self.assertRaises(tabp_helper.TabpValidationError):
            tabp_helper._validate_settings({"jd_folder": ["list"]})

    # --- TC-SV-07: state_write_mode invalid enum ---

    def test_tc_sv_07_state_write_mode_invalid_enum(self):
        """TC-SV-07 (AC-2): state_write_mode="direct" not in enum — TabpValidationError."""
        with self.assertRaises(tabp_helper.TabpValidationError) as ctx:
            tabp_helper._validate_settings({"state_write_mode": "direct"})
        msg = str(ctx.exception)
        self.assertIn("direct", msg)
        # message should name the allowed set
        self.assertTrue("helper" in msg or "instructed" in msg)

    # --- TC-SV-08: unknown key rejected ---

    def test_tc_sv_08_unknown_key_rejected(self):
        """TC-SV-08 (AC-4): Unknown key "unknown_field" — TabpValidationError."""
        with self.assertRaises(tabp_helper.TabpValidationError) as ctx:
            tabp_helper._validate_settings({"unknown_field": "x"})
        self.assertIn("unknown_field", str(ctx.exception))

    # --- TC-SV-09: workspace_path is unknown key -> rejected ---

    def test_tc_sv_09_workspace_path_rejected(self):
        """TC-SV-09 (AC-4): workspace_path is an unknown key — TabpValidationError."""
        with self.assertRaises(tabp_helper.TabpValidationError):
            tabp_helper._validate_settings({"workspace_path": "/some/path"})

    # --- TC-SV-10: .acs/ substring in value rejected ---

    def test_tc_sv_10_acs_substring_in_value_rejected(self):
        """TC-SV-10 (AC-4): cv_folder value contains ".acs/" — TabpValidationError."""
        with self.assertRaises(tabp_helper.TabpValidationError):
            tabp_helper._validate_settings({"cv_folder": "/some/.acs/cvs"})

    # --- TC-SV-11: _cmd_settings_validate --project-dir with valid file ---

    def test_tc_sv_11_cmd_validate_project_dir_valid(self):
        """TC-SV-11 (AC-2): --project-dir with valid tabp settings.json -> ok=true, exit 0."""
        path = os.path.join(self._tmpdir, "tabp settings.json")
        tabp_helper._write_json(path, {"screening_model": "sonnet"})
        out, code = self._call_validate(["--project-dir", self._tmpdir])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)["ok"])

    # --- TC-SV-12: --project-dir where tabp settings.json is absent ---

    def test_tc_sv_12_cmd_validate_project_dir_absent(self):
        """TC-SV-12 (AC-2): --project-dir with no file -> ok=false, EXIT_VALIDATION_FAILED."""
        out, code = self._call_validate(["--project-dir", self._tmpdir])
        self.assertEqual(code, tabp_helper.EXIT_VALIDATION_FAILED)
        parsed = json.loads(out)
        self.assertFalse(parsed["ok"])

    # --- TC-SV-13: --file with valid settings JSON ---

    def test_tc_sv_13_cmd_validate_file_valid(self):
        """TC-SV-13 (AC-2): --file with valid settings JSON -> ok=true, exit 0."""
        path = os.path.join(self._tmpdir, "mysettings.json")
        tabp_helper._write_json(path, {
            "screening_model": "claude-sonnet-4-5",
            "state_write_mode": "helper",
        })
        out, code = self._call_validate(["--file", path])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)["ok"])

    # --- TC-SV-14: --file with invalid state_write_mode ---

    def test_tc_sv_14_cmd_validate_file_invalid(self):
        """TC-SV-14 (AC-2): --file with invalid state_write_mode -> ok=false, EXIT_VALIDATION_FAILED."""
        path = os.path.join(self._tmpdir, "bad_settings.json")
        tabp_helper._write_json(path, {"state_write_mode": "direct"})
        out, code = self._call_validate(["--file", path])
        self.assertEqual(code, tabp_helper.EXIT_VALIDATION_FAILED)
        parsed = json.loads(out)
        self.assertFalse(parsed["ok"])

    # --- TC-SV-15: main() dispatches settings-validate ---

    def test_tc_sv_15_main_dispatches_settings_validate(self):
        """TC-SV-15 (AC-2): main() dispatches settings-validate; valid call exits 0."""
        import io
        path = os.path.join(self._tmpdir, "tabp settings.json")
        tabp_helper._write_json(path, {"screening_model": "sonnet"})
        sys.argv = ["tabp_helper.py", "settings-validate",
                    "--project-dir", self._tmpdir]
        out = io.StringIO()
        sys.stdout = out
        try:
            tabp_helper.main()
        except SystemExit as exc:
            self.assertEqual(exc.code, 0)
        finally:
            sys.stdout = self._orig_stdout
        parsed = json.loads(out.getvalue())
        self.assertTrue(parsed["ok"])

    # --- TC-SV-16: _validate_settings receives non-dict (line 562) ---

    def test_tc_sv_16_validate_settings_non_dict_raises(self):
        """TC-SV-16: _validate_settings receives a non-dict -> TabpValidationError."""
        with self.assertRaises(tabp_helper.TabpValidationError):
            tabp_helper._validate_settings("not a dict")
        with self.assertRaises(tabp_helper.TabpValidationError):
            tabp_helper._validate_settings(42)

    # --- TC-SV-17: _cmd_settings_validate bad args (lines 1073-1077) ---

    def test_tc_sv_17_cmd_settings_validate_bad_args_no_args(self):
        """TC-SV-17: _cmd_settings_validate with no args -> EXIT_ERROR."""
        import io
        sys.stderr = io.StringIO()
        try:
            tabp_helper._cmd_settings_validate([])
        except SystemExit as exc:
            self.assertEqual(exc.code, tabp_helper.EXIT_ERROR)
        finally:
            sys.stderr = self._orig_stderr

    def test_tc_sv_18_cmd_settings_validate_bad_args_both_args(self):
        """TC-SV-18: _cmd_settings_validate with both --project-dir and --file -> EXIT_ERROR."""
        import io
        sys.stderr = io.StringIO()
        path = os.path.join(self._tmpdir, "f.json")
        tabp_helper._write_json(path, {})
        try:
            tabp_helper._cmd_settings_validate([
                "--project-dir", self._tmpdir,
                "--file", path,
            ])
        except SystemExit as exc:
            self.assertEqual(exc.code, tabp_helper.EXIT_ERROR)
        finally:
            sys.stderr = self._orig_stderr

    # --- TC-SV-19: _cmd_settings_validate --project-dir with corrupt file ---

    def test_tc_sv_19_cmd_settings_validate_corrupt_file(self):
        """TC-SV-19: _cmd_settings_validate with corrupt file -> ok=false."""
        import io
        path = os.path.join(self._tmpdir, "tabp settings.json")
        with open(path, "w") as fh:
            fh.write("{not json")
        sys.stderr = io.StringIO()  # swallow _read_json warning
        out, code = self._call_validate(["--project-dir", self._tmpdir])
        self.assertEqual(code, tabp_helper.EXIT_VALIDATION_FAILED)
        parsed = json.loads(out)
        self.assertFalse(parsed["ok"])


# ---------------------------------------------------------------------------
# Class TestHistoryRecoveryFallback — recovery path stays schema-valid
# ---------------------------------------------------------------------------

class TestHistoryRecoveryFallback(unittest.TestCase):
    """_update_run_in_history recovery path produces a schema-valid summary."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._history_path = os.path.join(self._tmpdir, "history.json")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_recovery_entry_carries_fallback_fields(self):
        """With no matching entry, the appended recovery entry includes the
        fallback skill/started_at and validates against history.schema."""
        tabp_helper._write_json(self._history_path, {"runs": []})
        tabp_helper._update_run_in_history(
            self._history_path, "run-MISSING",
            {"status": "completed", "ended_at": "2026-06-20T10:00:00Z"},
            fallback={"skill": "screen-cvs", "started_at": "2026-06-20T09:00:00Z"},
        )
        hist = tabp_helper._read_history(self._history_path)
        entry = hist["runs"][-1]
        self.assertEqual(entry["run_id"], "run-MISSING")
        for field in ("run_id", "skill", "started_at", "status"):
            self.assertIn(field, entry)
        tabp_helper._validate_record(hist, "history")  # must not raise

    def test_run_finalize_recovers_schema_valid_history_entry(self):
        """run-finalize whose history lost the entry rebuilds a schema-valid one
        from run.json (skill + started_at carried via fallback)."""
        import io
        project_dir = self._tmpdir
        tabp_dir = os.path.join(project_dir, ".tabp")
        run_id = "run-recover"
        run_dir = os.path.join(tabp_dir, "runs", run_id)
        os.makedirs(run_dir, exist_ok=True)
        tabp_helper._write_json(os.path.join(run_dir, "run.json"), {
            "run_id": run_id, "skill": "screen-cvs",
            "started_at": "2026-06-20T09:00:00Z", "ended_at": None,
            "status": "in_progress", "stop_reason": None,
            "state_write_mode": "helper",
            "usage": {"usage_source": "unavailable"},
            "candidates_screened": 0, "jd_slug": "backend",
        })
        # history.json exists but does NOT contain this run (lost entry).
        tabp_helper._write_json(os.path.join(tabp_dir, "history.json"), {"runs": []})
        orig_err = sys.stderr
        sys.stderr = io.StringIO()
        try:
            tabp_helper._cmd_run_finalize([
                "--project-dir", project_dir, "--run-id", run_id,
                "--status", "completed", "--candidates-screened", "2",
            ])
        finally:
            sys.stderr = orig_err
        hist = tabp_helper._read_history(os.path.join(tabp_dir, "history.json"))
        entry = hist["runs"][-1]
        self.assertEqual(entry["run_id"], run_id)
        self.assertEqual(entry["skill"], "screen-cvs")
        self.assertEqual(entry["started_at"], "2026-06-20T09:00:00Z")
        tabp_helper._validate_record(hist, "history")  # must not raise


# ---------------------------------------------------------------------------
# Class TestRunIdUniqueness — sub-second run_id precision
# ---------------------------------------------------------------------------

class TestRunIdUniqueness(unittest.TestCase):
    """run_ids carry sub-second precision so same-second runs don't collide."""

    def test_run_stamp_has_microsecond_precision(self):
        stamp = tabp_helper._run_stamp()
        self.assertRegex(
            stamp, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")

    def test_two_run_starts_get_distinct_run_ids(self):
        import io
        import shutil
        tmp = tempfile.mkdtemp()
        try:
            ids = []
            for _ in range(2):
                out = io.StringIO()
                orig = sys.stdout
                sys.stdout = out
                try:
                    tabp_helper._cmd_run_start([
                        "--project-dir", tmp, "--skill", "screen-cvs"])
                finally:
                    sys.stdout = orig
                rid = out.getvalue().strip()
                ids.append(rid)
                # finalize releases the lock before the next start
                tabp_helper._cmd_run_finalize([
                    "--project-dir", tmp, "--run-id", rid, "--status", "completed"])
            self.assertEqual(len(set(ids)), 2, "run_ids must be unique: %r" % ids)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Class TestEvidenceScoreType — score must be a real number, not a bool
# ---------------------------------------------------------------------------

class TestEvidenceScoreType(unittest.TestCase):
    """evidence.score must be a real number; a bool is not a valid score."""

    def test_bool_score_rejected(self):
        bad = _make_valid_evidence()
        bad["score"] = True
        with self.assertRaises(tabp_helper.TabpValidationError):
            tabp_helper._validate_record(bad, "evidence")
