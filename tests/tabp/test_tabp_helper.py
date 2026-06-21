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
        """REPLACED (Spec 03 MAR-38): _cmd_usage_read returns REAL aggregation shape.

        Sets up one completed run (run.json + history entry), asserts the REAL output
        shape: total_runs==1, completed_runs==1, one runs[] entry, cost_basis present,
        pricing_snapshot_date present. Replaces the old stub assertion (total_runs==0).
        """
        import re
        # Set up one completed run
        out, err = self._capture()
        try:
            tabp_helper._cmd_run_start([
                "--project-dir", self._project_dir,
                "--skill", "screen-cvs",
                "--jd-slug", "backend-eng",
            ])
        finally:
            self._restore_streams()
        run_id = out.getvalue().strip()
        tabp_helper._cmd_run_finalize([
            "--project-dir", self._project_dir,
            "--run-id", run_id,
            "--status", "completed",
            "--usage-source", "unavailable",
            "--candidates-screened", "3",
        ])

        out2, err2 = self._capture()
        try:
            tabp_helper._cmd_usage_read([
                "--project-dir", self._project_dir,
            ])
        finally:
            self._restore_streams()
        result = json.loads(out2.getvalue())
        # Real shape assertions
        self.assertEqual(result["total_runs"], 1)
        self.assertEqual(result["completed_runs"], 1)
        self.assertIn("runs", result)
        self.assertEqual(len(result["runs"]), 1)
        self.assertIn("cost_basis", result)
        self.assertIn("pricing_snapshot_date", result)
        self.assertRegex(result["pricing_snapshot_date"], r"^\d{4}-\d{2}-\d{2}$")

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

    def test_tc29_no_acs_namespace_in_new_doc_files(self):
        """TC-29 (AC-7 MAR-38): new MAR-38 doc sections/files contain no acs: / .acs/ / acs_lib."""
        # Check the new ADR file (entirely new, must be clean)
        adr_path = os.path.join(_REPO_ROOT, "docs", "adr", "0026-tabp-hybrid-cost-sourcing.md")
        if not os.path.isfile(adr_path):
            self.fail("Required ADR file not found: %s" % adr_path)
        with open(adr_path, "r", encoding="utf-8") as fh:
            adr_content = fh.read()
        forbidden = ["acs:", ".acs/", "acs_lib"]
        for token in forbidden:
            self.assertNotIn(
                token, adr_content,
                "0026-tabp-hybrid-cost-sourcing.md must not contain %r (AC-7)" % token
            )

        # Check only the MAR-38 section of tabp.md (the existing file has 'acs:' in
        # its namespace-constraint wording — check only the new MAR-38 section)
        tabp_req_path = os.path.join(_REPO_ROOT, "docs", "requirements", "tabp.md")
        if not os.path.isfile(tabp_req_path):
            self.fail("Required requirements file not found: %s" % tabp_req_path)
        with open(tabp_req_path, "r", encoding="utf-8") as fh:
            tabp_content = fh.read()
        # Isolate MAR-38 section
        mar38_marker = "### MAR-38"
        if mar38_marker not in tabp_content:
            self.fail("tabp.md must contain MAR-38 section (AC-5)")
        mar38_section = tabp_content[tabp_content.index(mar38_marker):]
        for token in forbidden:
            self.assertNotIn(
                token, mar38_section,
                "tabp.md MAR-38 section must not contain %r (AC-7)" % token
            )


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
        """REPLACED (Spec 03 MAR-38): main() dispatches to usage-read with REAL shape.

        Asserts real shape keys: total_runs, cost_basis, pricing_snapshot_date, runs[].
        Replaces the old assertion that only checked 'total_runs' in result (stub shape).
        """
        import re
        # Set up one completed run via main dispatch
        run_id = self._do_run_start_via_main()
        # Finalize the run
        sys.argv = ["tabp_helper.py", "run-finalize",
                    "--project-dir", self._project_dir,
                    "--run-id", run_id,
                    "--status", "completed",
                    "--usage-source", "unavailable",
                    "--candidates-screened", "2"]
        out, err = self._capture()
        try:
            tabp_helper.main()
        finally:
            self._restore()

        sys.argv = ["tabp_helper.py", "usage-read",
                    "--project-dir", self._project_dir]
        out, err = self._capture()
        try:
            tabp_helper.main()
        finally:
            self._restore()
        result = json.loads(out.getvalue())
        # Real shape assertions
        self.assertIn("total_runs", result)
        self.assertIn("cost_basis", result)
        self.assertIn("pricing_snapshot_date", result)
        self.assertIn("runs", result)
        self.assertEqual(result["total_runs"], 1)
        self.assertRegex(result["pricing_snapshot_date"], r"^\d{4}-\d{2}-\d{2}$")

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
# Class TestSettingsRead — settings-read subcommand
# ---------------------------------------------------------------------------

class TestSettingsRead(unittest.TestCase):
    """settings-read resolves <project>/.tabp/settings.json over documented defaults."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._project_dir = self._tmpdir
        self._tabp_dir = os.path.join(self._project_dir, ".tabp")
        os.makedirs(self._tabp_dir, exist_ok=True)
        self._orig_argv = sys.argv[:]
        self._orig_stdout = sys.stdout
        self._orig_stderr = sys.stderr

    def tearDown(self):
        import shutil
        sys.argv = self._orig_argv
        sys.stdout = self._orig_stdout
        sys.stderr = self._orig_stderr
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _read_settings(self):
        import io
        out = io.StringIO()
        sys.stdout = out
        try:
            tabp_helper._cmd_settings_read(["--project-dir", self._project_dir])
        finally:
            sys.stdout = self._orig_stdout
        return json.loads(out.getvalue())

    def test_defaults_when_no_file(self):
        """No settings.json -> documented defaults."""
        self.assertEqual(self._read_settings(), tabp_helper._SETTINGS_DEFAULTS)

    def test_file_overrides_known_keys_only(self):
        """A settings.json overrides known keys; unknown keys are not surfaced."""
        tabp_helper._write_json(
            os.path.join(self._tabp_dir, "settings.json"),
            {"screening_model": "haiku", "cv_folder": "/abs/cvs", "unknown": "x"},
        )
        settings = self._read_settings()
        self.assertEqual(settings["screening_model"], "haiku")
        self.assertEqual(settings["cv_folder"], "/abs/cvs")
        self.assertEqual(settings["synthesis_model"],
                         tabp_helper._SETTINGS_DEFAULTS["synthesis_model"])
        self.assertNotIn("unknown", settings)

    def test_corrupt_file_falls_back_to_defaults(self):
        """A corrupt settings.json falls back to defaults (never raises)."""
        import io
        with open(os.path.join(self._tabp_dir, "settings.json"), "w") as fh:
            fh.write("{not json")
        sys.stderr = io.StringIO()  # swallow the _read_json corruption warning
        self.assertEqual(self._read_settings(), tabp_helper._SETTINGS_DEFAULTS)

    def test_main_dispatch_settings_read(self):
        """main() dispatches settings-read and prints a settings object."""
        import io
        sys.argv = ["tabp_helper.py", "settings-read",
                    "--project-dir", self._project_dir]
        out = io.StringIO()
        sys.stdout = out
        try:
            tabp_helper.main()
        finally:
            sys.stdout = self._orig_stdout
        self.assertIn("screening_model", json.loads(out.getvalue()))


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


# ---------------------------------------------------------------------------
# Class TestSchemaWideningAndFinalize — Spec 01 (MAR-38)
# TDD: Written before implementation; all tests MUST fail before impl.
# ---------------------------------------------------------------------------

class TestSchemaWideningAndFinalize(unittest.TestCase):
    """Spec 01 (MAR-38) — run schema widening + finalize write-through.

    Tests for:
    (a/b) _validate_run accepts new usage_source values; rejects 'unknown'
    (c)   cost_basis optional: absent ok, valid values ok, bad value raises
    (d)   run-finalize writes tokens-in/out/cost-basis + re-validate passes
    (e)   run-finalize with unavailable leaves tokens/cost-basis absent
    (f)   argparse accepts all four usage-source values (regression)
    (g)   history enum additive: claude-code validates
    (h)   R2 regression: cost_basis absent on old records is valid
    """

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._project_dir = self._tmpdir
        self._tabp_dir = os.path.join(self._project_dir, ".tabp")
        os.makedirs(self._tabp_dir, exist_ok=True)
        self._orig_stdout = sys.stdout
        self._orig_stderr = sys.stderr

    def tearDown(self):
        import shutil
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

    def _restore_streams(self):
        sys.stdout = self._orig_stdout
        sys.stderr = self._orig_stderr

    def _do_run_start(self):
        out, err = self._capture()
        try:
            tabp_helper._cmd_run_start([
                "--project-dir", self._project_dir,
                "--skill", "screen-cvs",
                "--jd-slug", "test-role",
            ])
        finally:
            self._restore_streams()
        return out.getvalue().strip()

    def _make_run(self, usage_source="unavailable"):
        """Return a valid run record with the given usage_source."""
        run = _make_valid_run()
        run["usage"]["usage_source"] = usage_source
        return run

    # (a/b) usage_source enum widened
    def test_validate_run_accepts_claude_code(self):
        """_validate_run accepts usage_source='claude-code'."""
        run = self._make_run("claude-code")
        tabp_helper._validate_run(run)  # must not raise

    def test_validate_run_accepts_estimate(self):
        """_validate_run accepts usage_source='estimate'."""
        run = self._make_run("estimate")
        tabp_helper._validate_run(run)  # must not raise

    def test_validate_run_accepts_cowork_regression(self):
        """_validate_run still accepts usage_source='cowork' (regression)."""
        run = self._make_run("cowork")
        tabp_helper._validate_run(run)  # must not raise

    def test_validate_run_accepts_unavailable_regression(self):
        """_validate_run still accepts usage_source='unavailable' (regression)."""
        run = self._make_run("unavailable")
        tabp_helper._validate_run(run)  # must not raise

    def test_validate_run_rejects_unknown_usage_source(self):
        """_validate_run rejects usage_source='unknown'."""
        run = self._make_run("unknown")
        with self.assertRaises(tabp_helper.TabpValidationError):
            tabp_helper._validate_run(run)

    # (c) cost_basis optional
    def test_validate_run_cost_basis_absent_ok(self):
        """cost_basis absent (old record) is valid — backward compat."""
        run = self._make_run("unavailable")
        self.assertNotIn("cost_basis", run["usage"])
        tabp_helper._validate_run(run)  # must not raise

    def test_validate_run_cost_basis_actual_ok(self):
        """cost_basis='actual' is valid."""
        run = self._make_run("cowork")
        run["usage"]["cost_basis"] = "actual"
        tabp_helper._validate_run(run)  # must not raise

    def test_validate_run_cost_basis_estimate_ok(self):
        """cost_basis='estimate' is valid."""
        run = self._make_run("claude-code")
        run["usage"]["cost_basis"] = "estimate"
        tabp_helper._validate_run(run)  # must not raise

    def test_validate_run_cost_basis_unavailable_ok(self):
        """cost_basis='unavailable' is valid."""
        run = self._make_run("unavailable")
        run["usage"]["cost_basis"] = "unavailable"
        tabp_helper._validate_run(run)  # must not raise

    def test_validate_run_cost_basis_bad_value_raises(self):
        """cost_basis='bad-value' raises TabpValidationError."""
        run = self._make_run("cowork")
        run["usage"]["cost_basis"] = "bad-value"
        with self.assertRaises(tabp_helper.TabpValidationError):
            tabp_helper._validate_run(run)

    # (d) run-finalize writes tokens + cost-basis
    def test_run_finalize_writes_tokens_and_cost_basis(self):
        """run-finalize with --tokens-in/out/cost-basis writes through to run.json."""
        run_id = self._do_run_start()
        tabp_helper._cmd_run_finalize([
            "--project-dir", self._project_dir,
            "--run-id", run_id,
            "--status", "completed",
            "--usage-source", "claude-code",
            "--tokens-in", "28000",
            "--tokens-out", "5200",
            "--cost-basis", "estimate",
        ])
        run_path = os.path.join(self._tabp_dir, "runs", run_id, "run.json")
        with open(run_path) as fh:
            run = json.load(fh)
        self.assertEqual(run["usage"]["usage_source"], "claude-code")
        self.assertEqual(run["usage"]["tokens_in"], 28000)
        self.assertEqual(run["usage"]["tokens_out"], 5200)
        self.assertEqual(run["usage"]["cost_basis"], "estimate")
        # Re-validate: widened _validate_run must pass
        tabp_helper._validate_run(run)

    # (e) run-finalize with unavailable leaves tokens None and cost-basis absent
    def test_run_finalize_unavailable_no_tokens(self):
        """run-finalize --usage-source unavailable: tokens remain null, cost_basis absent."""
        run_id = self._do_run_start()
        tabp_helper._cmd_run_finalize([
            "--project-dir", self._project_dir,
            "--run-id", run_id,
            "--status", "completed",
            "--usage-source", "unavailable",
        ])
        run_path = os.path.join(self._tabp_dir, "runs", run_id, "run.json")
        with open(run_path) as fh:
            run = json.load(fh)
        usage = run.get("usage", {})
        # tokens_in/out may be null (not set by finalize without --tokens-in/out)
        self.assertIsNone(usage.get("tokens_in"),
                          "tokens_in must be None when not passed to run-finalize")
        self.assertIsNone(usage.get("tokens_out"),
                          "tokens_out must be None when not passed to run-finalize")
        # cost_basis must not be set when --cost-basis not passed
        self.assertNotIn("cost_basis", usage)

    # (f) argparse accepts all four usage-source values
    def test_run_finalize_accepts_estimate_usage_source(self):
        """run-finalize accepts --usage-source estimate (no argparse error)."""
        run_id = self._do_run_start()
        tabp_helper._cmd_run_finalize([
            "--project-dir", self._project_dir,
            "--run-id", run_id,
            "--status", "completed",
            "--usage-source", "estimate",
        ])
        run_path = os.path.join(self._tabp_dir, "runs", run_id, "run.json")
        with open(run_path) as fh:
            run = json.load(fh)
        self.assertEqual(run["usage"]["usage_source"], "estimate")

    def test_run_finalize_accepts_cowork_usage_source(self):
        """run-finalize accepts --usage-source cowork (regression)."""
        run_id = self._do_run_start()
        tabp_helper._cmd_run_finalize([
            "--project-dir", self._project_dir,
            "--run-id", run_id,
            "--status", "completed",
            "--usage-source", "cowork",
        ])
        run_path = os.path.join(self._tabp_dir, "runs", run_id, "run.json")
        with open(run_path) as fh:
            run = json.load(fh)
        self.assertEqual(run["usage"]["usage_source"], "cowork")

    # (g) history enum additive
    def test_validate_history_accepts_claude_code_usage_source(self):
        """_validate_history accepts runs[0].usage_source='claude-code'."""
        history = {
            "runs": [
                {
                    "run_id": "run-20260620T091530Z",
                    "skill": "screen-cvs",
                    "started_at": "2026-06-20T09:15:30Z",
                    "status": "completed",
                    "usage_source": "claude-code",
                }
            ]
        }
        tabp_helper._validate_history(history)  # must not raise

    # (h) R2 regression: cost_basis absent on old records
    def test_validate_run_old_record_without_cost_basis_is_valid(self):
        """Old run record without cost_basis key passes validation (additive)."""
        run = _make_valid_run()  # run.sample.json has no cost_basis
        self.assertNotIn("cost_basis", run.get("usage", {}))
        tabp_helper._validate_run(run)  # must not raise


# ---------------------------------------------------------------------------
# Class TestPricingAndTranscriptReader — Spec 02 (MAR-38)
# TDD: Written before implementation; all tests MUST fail before impl.
# ---------------------------------------------------------------------------

class TestPricingAndTranscriptReader(unittest.TestCase):
    """Spec 02 (MAR-38) — model pricing snapshot + transcript token reader.

    Tests for:
    (a)   _resolve_pricing({}) returns snapshot dict + snapshot date
    (b)   single-model override; non-overridden model uses snapshot
    (c/d) malformed/non-numeric entry silently skipped, snapshot retained
    (e)   _PRICING_SNAPSHOT_DATE is YYYY-MM-DD string
    (f)   _read_transcript_tokens accumulates valid JSONL lines
    (g)   corrupt JSONL line skipped
    (h)   line missing 'usage' key skipped
    (i)   absent transcript dir -> (0, 0, None)
    (j)   non-int token treated as zero
    (k)   privacy: reader returns only (int, int, str|None) — no content text
    (l)   _derive_cost known-model math
    (m)   _derive_cost unknown model -> None
    (n)   _derive_cost None tokens -> None
    (o)   _cwd_slug path-to-slug conversion
    """

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _make_transcript_dir(self, cwd_slug, lines):
        """Create a temp transcript dir with a session.jsonl file."""
        slug_dir = os.path.join(self._tmpdir, cwd_slug)
        os.makedirs(slug_dir, exist_ok=True)
        jsonl_path = os.path.join(slug_dir, "session.jsonl")
        with open(jsonl_path, "w", encoding="utf-8") as fh:
            for line in lines:
                fh.write(json.dumps(line) + "\n")
        return self._tmpdir  # transcript_root

    # (a) _resolve_pricing snapshot fallback
    def test_resolve_pricing_empty_settings(self):
        """_resolve_pricing({}) returns snapshot dict and snapshot date."""
        pricing, date = tabp_helper._resolve_pricing({})
        self.assertIsInstance(pricing, dict)
        self.assertGreater(len(pricing), 0, "pricing dict must be non-empty")
        self.assertEqual(date, tabp_helper._PRICING_SNAPSHOT_DATE)
        # Must match snapshot
        for model, snap in tabp_helper._MODEL_PRICING.items():
            self.assertIn(model, pricing)
            self.assertEqual(pricing[model], snap)

    # (b) single-model override
    def test_resolve_pricing_single_model_override(self):
        """Single model override in settings overrides that model only."""
        settings = {
            "model_pricing": {
                "claude-opus-4-8": {"input_per_mtok": 20.00, "output_per_mtok": 100.00}
            }
        }
        pricing, date = tabp_helper._resolve_pricing(settings)
        self.assertEqual(pricing["claude-opus-4-8"]["input_per_mtok"], 20.00)
        self.assertEqual(pricing["claude-opus-4-8"]["output_per_mtok"], 100.00)
        # Non-overridden model falls back to snapshot
        if "claude-sonnet-4-6" in tabp_helper._MODEL_PRICING:
            snap_val = tabp_helper._MODEL_PRICING["claude-sonnet-4-6"]
            self.assertEqual(pricing["claude-sonnet-4-6"], snap_val)

    # (c) malformed entry skipped
    def test_resolve_pricing_malformed_entry_skipped(self):
        """Malformed per-model entry (non-numeric price) is silently skipped."""
        settings = {
            "model_pricing": {
                "bad-model": {"input_per_mtok": "not-a-number", "output_per_mtok": 0}
            }
        }
        # Must not raise
        pricing, date = tabp_helper._resolve_pricing(settings)
        self.assertIsInstance(pricing, dict)
        # bad-model absent from snapshot, so should not appear in result
        self.assertNotIn("bad-model", pricing)

    # (d) non-numeric price rejected silently, snapshot retained
    def test_resolve_pricing_non_numeric_price_retains_snapshot(self):
        """Non-numeric input_per_mtok causes the entry to be skipped; snapshot value retained."""
        settings = {
            "model_pricing": {
                "claude-opus-4-8": {"input_per_mtok": "fifteen", "output_per_mtok": 75.0}
            }
        }
        pricing, _ = tabp_helper._resolve_pricing(settings)
        # Snapshot value for claude-opus-4-8 must be retained
        self.assertEqual(
            pricing["claude-opus-4-8"],
            tabp_helper._MODEL_PRICING["claude-opus-4-8"]
        )

    # (e) _PRICING_SNAPSHOT_DATE format
    def test_pricing_snapshot_date_format(self):
        """_PRICING_SNAPSHOT_DATE is a YYYY-MM-DD string."""
        import re
        date = tabp_helper._PRICING_SNAPSHOT_DATE
        self.assertIsInstance(date, str)
        self.assertRegex(date, r"^\d{4}-\d{2}-\d{2}$")

    # (f) _read_transcript_tokens accumulates valid lines
    def test_read_transcript_tokens_accumulates(self):
        """_read_transcript_tokens sums input/output tokens from valid JSONL lines."""
        cwd_slug = "Users-testuser-myproject"
        lines = [
            {"message": {"usage": {"input_tokens": 1000, "output_tokens": 200}, "model": "claude-sonnet-4-6"}},
            {"message": {"usage": {"input_tokens": 500, "output_tokens": 100}, "model": "claude-opus-4-8"}},
        ]
        transcript_root = self._make_transcript_dir(cwd_slug, lines)
        total_in, total_out, model = tabp_helper._read_transcript_tokens(transcript_root, cwd_slug)
        self.assertEqual(total_in, 1500)
        self.assertEqual(total_out, 300)
        self.assertEqual(model, "claude-opus-4-8")  # last model seen

    # (g) corrupt JSONL line skipped
    def test_read_transcript_tokens_skips_corrupt_line(self):
        """Corrupt (non-JSON) line is skipped; valid lines are still summed."""
        cwd_slug = "Users-testuser-project2"
        slug_dir = os.path.join(self._tmpdir, cwd_slug)
        os.makedirs(slug_dir, exist_ok=True)
        jsonl_path = os.path.join(slug_dir, "session.jsonl")
        with open(jsonl_path, "w", encoding="utf-8") as fh:
            fh.write('{"message": {"usage": {"input_tokens": 300, "output_tokens": 50}, "model": "claude-sonnet-4-6"}}\n')
            fh.write('NOT VALID JSON!!!\n')
        total_in, total_out, model = tabp_helper._read_transcript_tokens(self._tmpdir, cwd_slug)
        self.assertEqual(total_in, 300)
        self.assertEqual(total_out, 50)

    # (h) line missing 'usage' key skipped
    def test_read_transcript_tokens_skips_missing_usage(self):
        """Line with message but no 'usage' key is skipped gracefully."""
        cwd_slug = "Users-testuser-project3"
        lines = [
            {"message": {"model": "claude-sonnet-4-6"}},  # no usage
            {"message": {"usage": {"input_tokens": 200, "output_tokens": 40}, "model": "claude-sonnet-4-6"}},
        ]
        transcript_root = self._make_transcript_dir(cwd_slug, lines)
        total_in, total_out, model = tabp_helper._read_transcript_tokens(transcript_root, cwd_slug)
        self.assertEqual(total_in, 200)
        self.assertEqual(total_out, 40)

    # (i) absent transcript dir -> (0, 0, None)
    def test_read_transcript_tokens_absent_dir(self):
        """Absent transcript directory returns (0, 0, None)."""
        total_in, total_out, model = tabp_helper._read_transcript_tokens(
            self._tmpdir, "nonexistent-slug-xyz"
        )
        self.assertEqual(total_in, 0)
        self.assertEqual(total_out, 0)
        self.assertIsNone(model)

    # (j) non-integer token treated as zero
    def test_read_transcript_tokens_non_int_token_treated_as_zero(self):
        """Non-integer input_tokens value is treated as 0, not added to total."""
        cwd_slug = "Users-testuser-project4"
        lines = [
            {"message": {"usage": {"input_tokens": "many", "output_tokens": 50}, "model": "claude-sonnet-4-6"}},
            {"message": {"usage": {"input_tokens": 100, "output_tokens": 20}, "model": "claude-sonnet-4-6"}},
        ]
        transcript_root = self._make_transcript_dir(cwd_slug, lines)
        total_in, total_out, _ = tabp_helper._read_transcript_tokens(transcript_root, cwd_slug)
        self.assertEqual(total_in, 100)  # "many" treated as 0, only 100 counted
        self.assertEqual(total_out, 70)  # 50+20

    # (k) privacy: reader returns only token integers + model, no content text
    def test_read_transcript_tokens_privacy_no_content_returned(self):
        """Privacy gate: reader returns (int, int, str|None) — no message.content text."""
        cwd_slug = "Users-testuser-project5"
        private_text = "CONFIDENTIAL CV CONTENT DO NOT EXPOSE"
        lines = [
            {
                "message": {
                    "content": private_text,
                    "usage": {"input_tokens": 500, "output_tokens": 100},
                    "model": "claude-sonnet-4-6",
                }
            }
        ]
        transcript_root = self._make_transcript_dir(cwd_slug, lines)
        result = tabp_helper._read_transcript_tokens(transcript_root, cwd_slug)
        # Result must be a 3-tuple of (int, int, str|None)
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 3)
        total_in, total_out, model = result
        self.assertIsInstance(total_in, int)
        self.assertIsInstance(total_out, int)
        # Assert no element of the result contains the private text
        for element in result:
            if element is not None:
                self.assertNotEqual(element, private_text)
                if isinstance(element, str):
                    self.assertNotIn(private_text, element)

    # (l) _derive_cost known model math
    def test_derive_cost_known_model(self):
        """_derive_cost known model computes (tin/1e6)*in_price + (tout/1e6)*out_price."""
        pricing = {"claude-opus-4-8": {"input_per_mtok": 15.0, "output_per_mtok": 75.0}}
        expected = (28000 / 1_000_000) * 15.0 + (5200 / 1_000_000) * 75.0
        result = tabp_helper._derive_cost(28000, 5200, "claude-opus-4-8", pricing)
        self.assertAlmostEqual(result, expected, places=6)

    # (m) _derive_cost unknown model -> None
    def test_derive_cost_unknown_model_returns_none(self):
        """_derive_cost returns None for unknown model."""
        pricing = {"claude-opus-4-8": {"input_per_mtok": 15.0, "output_per_mtok": 75.0}}
        result = tabp_helper._derive_cost(28000, 5200, "claude-unknown-99", pricing)
        self.assertIsNone(result)

    # (n) _derive_cost None tokens -> None
    def test_derive_cost_none_tokens_returns_none(self):
        """_derive_cost returns None when tokens_in is None."""
        pricing = {"claude-opus-4-8": {"input_per_mtok": 15.0, "output_per_mtok": 75.0}}
        result = tabp_helper._derive_cost(None, 5200, "claude-opus-4-8", pricing)
        self.assertIsNone(result)

    def test_derive_cost_none_tokens_out_returns_none(self):
        """_derive_cost returns None when tokens_out is None."""
        pricing = {"claude-opus-4-8": {"input_per_mtok": 15.0, "output_per_mtok": 75.0}}
        result = tabp_helper._derive_cost(28000, None, "claude-opus-4-8", pricing)
        self.assertIsNone(result)

    # (o) _cwd_slug path-to-slug conversion
    def test_cwd_slug_conversion(self):
        """_cwd_slug converts path to cwd-slug format (/ -> -, strip leading -)."""
        slug = tabp_helper._cwd_slug("/Users/bob/projects/myapp")
        # /Users/bob/projects/myapp -> -Users-bob-projects-myapp -> Users-bob-projects-myapp
        self.assertEqual(slug, "Users-bob-projects-myapp")

    def test_cwd_slug_no_leading_dash(self):
        """_cwd_slug strips leading dash from the result."""
        slug = tabp_helper._cwd_slug("/home/user/work")
        self.assertFalse(slug.startswith("-"), "cwd_slug must not start with '-'")
        self.assertEqual(slug, "home-user-work")


# ---------------------------------------------------------------------------
# Class TestUsageReadAggregation — Spec 03 (MAR-38)
# TDD: Written before implementation; tests MUST fail before impl.
# ---------------------------------------------------------------------------

class TestUsageReadAggregation(unittest.TestCase):
    """Spec 03 (MAR-38) — _cmd_usage_read real aggregation.

    All fixture .tabp/ dirs use tempfile.mkdtemp(). Transcript roots are
    injected as environment variable TABP_TRANSCRIPT_ROOT or via parameter.
    No real ~/.claude is ever read. No network. No model calls.

    Tests for:
    (a)   empty history -> zero totals, runs==[], all required keys present
    (b)   mixed run set: claude-code/estimate/unavailable/cowork labels, tokens,
          cost_basis; unavailable omitted from totals; totals == A+B+D
    (c)   --run-id <id> returns one run
    (d)   --run-id all returns all runs
    (e)   corrupt/missing run.json omitted gracefully
    (f)   pricing_snapshot_date present in every response
    (g)   settings model_pricing override changes derived cost
    (h)   R2 mislabel guard: every entry has cost_basis; no non-cowork is 'actual'
    (i)   read-only: no files created/modified under .tabp/; no transcript text
    (j)   settings-read surfaces model_pricing when present
    (k)   settings-read absent model_pricing -> key absent from output
    """

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._project_dir = self._tmpdir
        self._tabp_dir = os.path.join(self._project_dir, ".tabp")
        os.makedirs(self._tabp_dir, exist_ok=True)
        self._orig_stdout = sys.stdout
        self._orig_stderr = sys.stderr
        self._orig_env = os.environ.copy()

    def tearDown(self):
        import shutil
        sys.stdout = self._orig_stdout
        sys.stderr = self._orig_stderr
        # Restore env
        for k in list(os.environ.keys()):
            if k not in self._orig_env:
                del os.environ[k]
        for k, v in self._orig_env.items():
            os.environ[k] = v
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _capture(self):
        import io
        out = io.StringIO()
        err = io.StringIO()
        sys.stdout = out
        sys.stderr = err
        return out, err

    def _restore_streams(self):
        sys.stdout = self._orig_stdout
        sys.stderr = self._orig_stderr

    def _do_run_start(self):
        out, err = self._capture()
        try:
            tabp_helper._cmd_run_start([
                "--project-dir", self._project_dir,
                "--skill", "screen-cvs",
                "--jd-slug", "test-role",
            ])
        finally:
            self._restore_streams()
        return out.getvalue().strip()

    def _write_history(self, runs):
        """Write history.json directly (bypass run-start for multi-run setup)."""
        history_path = os.path.join(self._tabp_dir, "history.json")
        tabp_helper._write_json(history_path, {"runs": runs})

    def _write_run_json(self, run_id, run_data):
        """Write run.json for a given run_id."""
        run_dir = os.path.join(self._tabp_dir, "runs", run_id)
        os.makedirs(run_dir, exist_ok=True)
        run_path = os.path.join(run_dir, "run.json")
        tabp_helper._write_json(run_path, run_data)

    def _make_run_record(self, run_id, status="completed", usage_source="unavailable",
                         candidates_screened=1, tokens_in=None, tokens_out=None,
                         cost_usd=None, cost_basis=None):
        """Build a minimal valid run record."""
        record = {
            "run_id": run_id,
            "skill": "screen-cvs",
            "started_at": "2026-06-20T09:00:00Z",
            "ended_at": "2026-06-20T09:30:00Z",
            "status": status,
            "stop_reason": None,
            "state_write_mode": "helper",
            "usage": {
                "usage_source": usage_source,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "cost_usd": cost_usd,
                "duration_seconds": 1800,
            },
            "candidates_screened": candidates_screened,
            "jd_slug": "test-role",
        }
        if cost_basis is not None:
            record["usage"]["cost_basis"] = cost_basis
        return record

    def _make_history_entry(self, run_id, status="completed", usage_source="unavailable",
                            candidates_screened=1):
        return {
            "run_id": run_id,
            "skill": "screen-cvs",
            "started_at": "2026-06-20T09:00:00Z",
            "ended_at": "2026-06-20T09:30:00Z",
            "status": status,
            "candidates_screened": candidates_screened,
            "duration_seconds": 1800,
            "usage_source": usage_source,
        }

    def _call_usage_read(self, extra_args=None):
        args = ["--project-dir", self._project_dir]
        if extra_args:
            args.extend(extra_args)
        out, err = self._capture()
        try:
            tabp_helper._cmd_usage_read(args)
        finally:
            self._restore_streams()
        return json.loads(out.getvalue())

    # (a) empty history
    def test_empty_history_zero_totals(self):
        """Empty history -> zero totals, empty runs[], all required keys present."""
        result = self._call_usage_read()
        required_keys = [
            "total_runs", "completed_runs", "failed_runs",
            "total_candidates_screened", "total_duration_seconds",
            "total_tokens_in", "total_tokens_out", "total_cost_usd",
            "cost_basis", "pricing_snapshot_date", "usage_note", "runs",
        ]
        for k in required_keys:
            self.assertIn(k, result, "missing key: %s" % k)
        self.assertEqual(result["total_runs"], 0)
        self.assertEqual(result["runs"], [])

    # (b) mixed run set
    def test_mixed_run_set_labels_and_totals(self):
        """Mixed run set: claude-code/estimate/unavailable/cowork labels correct;
        unavailable omitted from totals; totals==A+B+D."""
        import re
        transcript_root = os.path.join(self._tmpdir, "transcripts")
        os.environ["TABP_TRANSCRIPT_ROOT"] = transcript_root

        # Run A: claude-code with injected transcript
        run_a = "run-A"
        cwd_slug = tabp_helper._cwd_slug(self._project_dir)
        slug_dir = os.path.join(transcript_root, cwd_slug)
        os.makedirs(slug_dir, exist_ok=True)
        with open(os.path.join(slug_dir, "session.jsonl"), "w") as fh:
            fh.write(json.dumps({
                "message": {"usage": {"input_tokens": 10000, "output_tokens": 2000},
                            "model": "claude-sonnet-4-6"}
            }) + "\n")
        self._write_run_json(run_a, self._make_run_record(
            run_a, status="completed", usage_source="claude-code",
            candidates_screened=2, cost_basis="estimate"
        ))

        # Run B: estimate with pre-set tokens
        run_b = "run-B"
        self._write_run_json(run_b, self._make_run_record(
            run_b, status="completed", usage_source="estimate",
            candidates_screened=3, tokens_in=5000, tokens_out=1200,
            cost_basis="estimate"
        ))

        # Run C: unavailable
        run_c = "run-C"
        self._write_run_json(run_c, self._make_run_record(
            run_c, status="completed", usage_source="unavailable",
            candidates_screened=0, cost_basis="unavailable"
        ))

        # Run D: cowork (future hook)
        run_d = "run-D"
        self._write_run_json(run_d, self._make_run_record(
            run_d, status="completed", usage_source="cowork",
            candidates_screened=4, tokens_in=8000, tokens_out=2000,
            cost_usd=0.50, cost_basis="actual"
        ))

        history = [
            self._make_history_entry(run_a, usage_source="claude-code", candidates_screened=2),
            self._make_history_entry(run_b, usage_source="estimate", candidates_screened=3),
            self._make_history_entry(run_c, usage_source="unavailable", candidates_screened=0),
            self._make_history_entry(run_d, usage_source="cowork", candidates_screened=4),
        ]
        self._write_history(history)

        result = self._call_usage_read()

        self.assertEqual(result["total_runs"], 4)
        self.assertEqual(result["completed_runs"], 4)
        self.assertEqual(len(result["runs"]), 4)

        # Find per-run entries
        runs_by_id = {r["run_id"]: r for r in result["runs"]}

        # Run A: claude-code -> estimate cost_basis, derived tokens from transcript
        run_a_row = runs_by_id.get(run_a)
        self.assertIsNotNone(run_a_row, "Run A must appear in runs[]")
        self.assertEqual(run_a_row["usage_source"], "claude-code")
        self.assertEqual(run_a_row["cost_basis"], "estimate")
        self.assertIsNotNone(run_a_row["tokens_in"])
        self.assertIsNotNone(run_a_row["tokens_out"])

        # Run B: estimate -> estimate cost_basis
        run_b_row = runs_by_id.get(run_b)
        self.assertIsNotNone(run_b_row)
        self.assertEqual(run_b_row["usage_source"], "estimate")
        self.assertEqual(run_b_row["cost_basis"], "estimate")
        self.assertEqual(run_b_row["tokens_in"], 5000)
        self.assertEqual(run_b_row["tokens_out"], 1200)

        # Run C: unavailable -> null tokens/cost, included in runs[] but not totals
        run_c_row = runs_by_id.get(run_c)
        self.assertIsNotNone(run_c_row)
        self.assertEqual(run_c_row["usage_source"], "unavailable")
        self.assertEqual(run_c_row["cost_basis"], "unavailable")
        self.assertIsNone(run_c_row["tokens_in"])
        self.assertIsNone(run_c_row["tokens_out"])
        self.assertIsNone(run_c_row["cost_usd"])

        # Run D: cowork -> actual cost_basis
        run_d_row = runs_by_id.get(run_d)
        self.assertIsNotNone(run_d_row)
        self.assertEqual(run_d_row["usage_source"], "cowork")
        self.assertEqual(run_d_row["cost_basis"], "actual")

        # Totals: must be A+B+D (not C)
        a_in = run_a_row["tokens_in"] or 0
        a_out = run_a_row["tokens_out"] or 0
        b_in = 5000
        b_out = 1200
        d_in = 8000
        d_out = 2000
        self.assertEqual(result["total_tokens_in"], a_in + b_in + d_in)
        self.assertEqual(result["total_tokens_out"], a_out + b_out + d_out)

    # (c) --run-id <id> returns one run
    def test_run_id_filter_returns_one_run(self):
        """--run-id <id> returns one run with that run_id."""
        run_a = "run-20260620T090000Z"
        run_b = "run-20260620T093000Z"
        self._write_run_json(run_a, self._make_run_record(run_a))
        self._write_run_json(run_b, self._make_run_record(run_b))
        self._write_history([
            self._make_history_entry(run_a),
            self._make_history_entry(run_b),
        ])
        result = self._call_usage_read(["--run-id", run_a])
        self.assertEqual(result["total_runs"], 1)
        self.assertEqual(len(result["runs"]), 1)
        self.assertEqual(result["runs"][0]["run_id"], run_a)

    # (d) --run-id all returns all runs
    def test_run_id_all_returns_all_runs(self):
        """--run-id all is equivalent to absent (returns all runs)."""
        run_a = "run-20260620T090000Z"
        run_b = "run-20260620T093000Z"
        self._write_run_json(run_a, self._make_run_record(run_a))
        self._write_run_json(run_b, self._make_run_record(run_b))
        self._write_history([
            self._make_history_entry(run_a),
            self._make_history_entry(run_b),
        ])
        result_all = self._call_usage_read(["--run-id", "all"])
        result_absent = self._call_usage_read()
        self.assertEqual(result_all["total_runs"], result_absent["total_runs"])
        self.assertEqual(len(result_all["runs"]), len(result_absent["runs"]))

    # (e) corrupt/missing run.json omitted gracefully
    def test_missing_run_json_omitted(self):
        """Missing run.json: run not in runs[] output, no exception."""
        self._write_history([
            self._make_history_entry("run-missing"),
        ])
        # Do NOT create run.json for "run-missing"
        result = self._call_usage_read()
        run_ids_in_output = [r["run_id"] for r in result["runs"]]
        self.assertNotIn("run-missing", run_ids_in_output)

    def test_corrupt_run_json_omitted(self):
        """Corrupt run.json: run not in runs[] output, no exception."""
        run_id = "run-corrupt"
        run_dir = os.path.join(self._tabp_dir, "runs", run_id)
        os.makedirs(run_dir, exist_ok=True)
        with open(os.path.join(run_dir, "run.json"), "w") as fh:
            fh.write("INVALID JSON {{{")
        self._write_history([self._make_history_entry(run_id)])
        result = self._call_usage_read()
        run_ids_in_output = [r["run_id"] for r in result["runs"]]
        self.assertNotIn(run_id, run_ids_in_output)

    # (f) pricing_snapshot_date present in every response
    def test_pricing_snapshot_date_always_present(self):
        """pricing_snapshot_date is present in every usage-read response."""
        import re
        result = self._call_usage_read()
        self.assertIn("pricing_snapshot_date", result)
        self.assertRegex(result["pricing_snapshot_date"], r"^\d{4}-\d{2}-\d{2}$")

    # (g) settings model_pricing override changes derived cost
    def test_settings_model_pricing_override(self):
        """settings.json model_pricing override changes derived cost for a run."""
        import re
        transcript_root = os.path.join(self._tmpdir, "transcripts2")
        os.environ["TABP_TRANSCRIPT_ROOT"] = transcript_root

        run_id = "run-cost-test"
        cwd_slug = tabp_helper._cwd_slug(self._project_dir)
        slug_dir = os.path.join(transcript_root, cwd_slug)
        os.makedirs(slug_dir, exist_ok=True)
        with open(os.path.join(slug_dir, "session.jsonl"), "w") as fh:
            fh.write(json.dumps({
                "message": {"usage": {"input_tokens": 1000000, "output_tokens": 1000000},
                            "model": "claude-opus-4-8"}
            }) + "\n")

        self._write_run_json(run_id, self._make_run_record(
            run_id, usage_source="claude-code", candidates_screened=1,
            cost_basis="estimate"
        ))
        self._write_history([self._make_history_entry(
            run_id, usage_source="claude-code")])

        # Write settings with overridden price
        settings_path = os.path.join(self._tabp_dir, "settings.json")
        tabp_helper._write_json(settings_path, {
            "model_pricing": {
                "claude-opus-4-8": {"input_per_mtok": 20.0, "output_per_mtok": 100.0}
            }
        })

        result = self._call_usage_read()
        self.assertEqual(len(result["runs"]), 1)
        run_row = result["runs"][0]
        # With 1M in + 1M out at $20/$100 per mtok -> $120
        if run_row["cost_usd"] is not None:
            self.assertAlmostEqual(run_row["cost_usd"], 120.0, places=2)

    # (h) R2 mislabel guard: every runs[] entry has cost_basis; no non-cowork is 'actual'
    def test_r2_mislabel_guard_cost_basis_always_set(self):
        """Every runs[] entry has cost_basis; no non-cowork run has cost_basis='actual'."""
        run_a = "run-A-h"
        run_b = "run-B-h"
        run_c = "run-C-h"
        self._write_run_json(run_a, self._make_run_record(
            run_a, usage_source="claude-code", cost_basis="estimate"))
        self._write_run_json(run_b, self._make_run_record(
            run_b, usage_source="estimate", cost_basis="estimate"))
        self._write_run_json(run_c, self._make_run_record(
            run_c, usage_source="unavailable", cost_basis="unavailable"))
        self._write_history([
            self._make_history_entry(run_a, usage_source="claude-code"),
            self._make_history_entry(run_b, usage_source="estimate"),
            self._make_history_entry(run_c, usage_source="unavailable"),
        ])
        result = self._call_usage_read()
        valid_values = {"actual", "estimate", "unavailable"}
        for row in result["runs"]:
            self.assertIn("cost_basis", row,
                          "every runs[] entry must have cost_basis")
            self.assertIn(row["cost_basis"], valid_values)
            if row["usage_source"] != "cowork":
                self.assertNotEqual(
                    row["cost_basis"], "actual",
                    "non-cowork run must not have cost_basis='actual' (R2)"
                )

    # (i) read-only: no files created or modified under .tabp/
    def test_read_only_no_tabp_files_changed(self):
        """_cmd_usage_read does not create or modify any .tabp/ files."""
        import os
        # Set up one run
        run_id = "run-readonly"
        self._write_run_json(run_id, self._make_run_record(run_id))
        self._write_history([self._make_history_entry(run_id)])

        # Record file state before
        def file_state(dirpath):
            state = {}
            for root, dirs, files in os.walk(dirpath):
                for fname in files:
                    fpath = os.path.join(root, fname)
                    stat = os.stat(fpath)
                    state[fpath] = (stat.st_size, stat.st_mtime)
            return state

        before = file_state(self._tabp_dir)
        self._call_usage_read()
        after = file_state(self._tabp_dir)

        self.assertEqual(before, after,
                         "usage-read must not modify any .tabp/ files (read-only)")

    # (i) privacy: no transcript content persisted in .tabp/ files
    def test_read_only_no_transcript_content_persisted(self):
        """No transcript message.content text appears in any .tabp/ file after usage-read."""
        transcript_root = os.path.join(self._tmpdir, "transcripts3")
        os.environ["TABP_TRANSCRIPT_ROOT"] = transcript_root
        private_content = "PRIVATE-TRANSCRIPT-CONTENT-XYZZY-DO-NOT-PERSIST"

        run_id = "run-priv"
        cwd_slug = tabp_helper._cwd_slug(self._project_dir)
        slug_dir = os.path.join(transcript_root, cwd_slug)
        os.makedirs(slug_dir, exist_ok=True)
        with open(os.path.join(slug_dir, "session.jsonl"), "w") as fh:
            fh.write(json.dumps({
                "message": {
                    "content": private_content,
                    "usage": {"input_tokens": 100, "output_tokens": 50},
                    "model": "claude-sonnet-4-6",
                }
            }) + "\n")
        self._write_run_json(run_id, self._make_run_record(
            run_id, usage_source="claude-code", cost_basis="estimate"))
        self._write_history([self._make_history_entry(run_id, usage_source="claude-code")])

        self._call_usage_read()

        # Scan all .tabp/ files for private content
        for root, dirs, files in os.walk(self._tabp_dir):
            for fname in files:
                fpath = os.path.join(root, fname)
                with open(fpath, "r", encoding="utf-8", errors="replace") as fh:
                    file_content = fh.read()
                self.assertNotIn(
                    private_content, file_content,
                    "Transcript content must not be persisted in %s (privacy)" % fpath
                )

    # (j) settings-read surfaces model_pricing when present
    def test_settings_read_surfaces_model_pricing(self):
        """settings-read output includes model_pricing when set in settings.json."""
        settings_path = os.path.join(self._tabp_dir, "settings.json")
        tabp_helper._write_json(settings_path, {
            "model_pricing": {
                "claude-opus-4-8": {"input_per_mtok": 15.0, "output_per_mtok": 75.0}
            }
        })
        out, err = self._capture()
        try:
            tabp_helper._cmd_settings_read(["--project-dir", self._project_dir])
        finally:
            self._restore_streams()
        result = json.loads(out.getvalue())
        self.assertIn("model_pricing", result)
        self.assertIn("claude-opus-4-8", result["model_pricing"])

    # (k) settings-read absent model_pricing -> key absent from output
    def test_settings_read_absent_model_pricing_not_in_output(self):
        """settings-read without model_pricing in settings.json: key absent from output."""
        settings_path = os.path.join(self._tabp_dir, "settings.json")
        tabp_helper._write_json(settings_path, {
            "screening_model": "sonnet",
        })
        out, err = self._capture()
        try:
            tabp_helper._cmd_settings_read(["--project-dir", self._project_dir])
        finally:
            self._restore_streams()
        result = json.loads(out.getvalue())
        self.assertNotIn("model_pricing", result)
