"""Unit + edge + perf tests for plugins/acs/hooks/scripts/metrics_aggregate.py (MAR-5 spec 01).

Pure stdlib (unittest, tempfile, json, os, time, re); NO show_widget import. Tests drive the
PURE aggregate(workspace, repo_id) -> dict function against workspaces synthesized in a
tempfile.TemporaryDirectory mirroring the live archive/MAR-6 artifact shapes (spec 01:199-246,
design.md:182-202). Every test maps to an AC; field-by-field assertions.

The helper module lives beside acs_lib.py; we add that scripts dir to sys.path and import it the
same way the other hooks/scripts do (they share the directory).
"""

import importlib
import json
import os
import re
import sys
import time
import unittest
from tempfile import TemporaryDirectory

_SCRIPTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "plugins", "acs", "hooks", "scripts",
)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import acs_lib  # noqa: E402  (after sys.path mutation)
metrics_aggregate = importlib.import_module("metrics_aggregate")  # noqa: E402

REPO_ID = "globalmindsolution-gms-marketplace"
HOOKED = acs_lib.HOOKED_SKILLS


# ---------------------------------------------------------------------------
# Workspace synthesis helpers — mirror the live archive/MAR-6 shapes
# ---------------------------------------------------------------------------

def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)


def _write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _repo_dir(ws):
    return os.path.join(ws, REPO_ID)


def _ticket_dir(ws, tid, archived=False):
    if archived:
        return os.path.join(_repo_dir(ws), "archive", tid)
    return os.path.join(_repo_dir(ws), tid)


def write_index(ws, tickets):
    """tickets: dict id -> {status, type, ...}. Mirrors tickets-index.json."""
    _write_json(os.path.join(_repo_dir(ws), "tickets-index.json"), {"tickets": tickets})


def write_metrics(ws, data):
    _write_json(os.path.join(_repo_dir(ws), "metrics.json"), data)


def write_pipeline(ws, tid, steps=None, totals=None, archived=False):
    tdir = _ticket_dir(ws, tid, archived)
    payload = {"ticket_id": tid, "flow": "ticket", "steps": steps or {}, "totals": totals or {}}
    _write_json(os.path.join(tdir, "pipeline-state.json"), payload)


def write_code_state(ws, tid, states, archived=False):
    tdir = _ticket_dir(ws, tid, archived)
    _write_json(os.path.join(tdir, "code-state.json"),
                {"skill": "code", "ticket_id": tid, "states": states, "runs": []})


def write_create_pr_state(ws, tid, states=None, archived=False):
    tdir = _ticket_dir(ws, tid, archived)
    _write_json(os.path.join(tdir, "create-pr-state.json"),
                {"skill": "create-pr", "ticket_id": tid, "states": states or {}, "runs": []})


_RESULT_XML = (
    '<result skill="code" phase="{phase}" ticket-id="{tid}" iteration="{it}" status="completed">\n'
    '  <outputs><file>x</file></outputs>\n'
    '  {metrics}\n'
    '</result>\n'
)
_TASK_XML = (
    '<task skill="code" phase="{phase}" ticket-id="{tid}" iteration="{it}">\n'
    '  <objective>dispatch — no metrics here</objective>\n'
    '</task>\n'
)


def write_result_xml(ws, tid, skill_dir, phase, it, ti=0, to=0, cost=0.0,
                     reorder=False, no_metrics=False, archived=False):
    """Write phases/<skill_dir>/iter-<it>-<phase>.xml (a result XML, optionally carrying <metrics>)."""
    tdir = _ticket_dir(ws, tid, archived)
    if no_metrics:
        metrics = ""
    elif reorder:
        metrics = '<metrics cost-usd="%s" tokens-output="%s" tokens-input="%s"/>' % (cost, to, ti)
    else:
        metrics = '<metrics tokens-input="%s" tokens-output="%s" cost-usd="%s"/>' % (ti, to, cost)
    body = _RESULT_XML.format(phase=phase, tid=tid, it=it, metrics=metrics)
    _write_text(os.path.join(tdir, "phases", skill_dir, "iter-%d-%s.xml" % (it, phase)), body)


def write_task_xml(ws, tid, skill_dir, phase, it, archived=False):
    """Write phases/<skill_dir>/iter-<it>-<phase>-task.xml (a task/dispatch XML — never carries metrics)."""
    tdir = _ticket_dir(ws, tid, archived)
    body = _TASK_XML.format(phase=phase, tid=tid, it=it)
    _write_text(os.path.join(tdir, "phases", skill_dir, "iter-%d-%s-task.xml" % (it, phase)), body)


def _full_funnel_steps(reached_through="merge-pr"):
    """A steps dict completing every HOOKED_SKILLS step up to reached_through, with timestamps."""
    steps = {}
    order = HOOKED
    cutoff = order.index(reached_through) if reached_through in order else len(order) - 1
    for i, skill in enumerate(order):
        status = "completed" if i <= cutoff else "in_progress"
        steps[skill] = {
            "started_at": "2026-06-15T10:0%d:00Z" % (i % 6),
            "status": status,
            "ended_at": "2026-06-15T10:0%d:30Z" % (i % 6),
            "summary": "step %s" % skill,
        }
    return steps


# ---------------------------------------------------------------------------
# Panel tests (AC-2) — one per panel, field-by-field
# ---------------------------------------------------------------------------

class Panel1Throughput(unittest.TestCase):
    def test_primary_from_metrics_json(self):
        with TemporaryDirectory() as ws:
            write_index(ws, {"MAR-6": {"status": "done", "type": "task"}})
            write_metrics(ws, {"tickets": {"by_status": {"done": 4, "in_review": 1, "in_progress": 1},
                                           "by_type": {"task": 5, "story": 1}}})
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            p1 = out["panels"]["1"]
            self.assertEqual(p1["by_status"], {"done": 4, "in_review": 1, "in_progress": 1})
            self.assertEqual(p1["by_type"], {"task": 5, "story": 1})

    def test_recompute_fallback_when_metrics_absent(self):
        with TemporaryDirectory() as ws:
            write_index(ws, {
                "MAR-1": {"status": "done", "type": "task"},
                "MAR-2": {"status": "done", "type": "task"},
                "MAR-3": {"status": "in_review", "type": "story"},
            })
            # no metrics.json on disk -> recompute fallback from the index
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            p1 = out["panels"]["1"]
            self.assertEqual(p1["by_status"], {"done": 2, "in_review": 1})
            self.assertEqual(p1["by_type"], {"task": 2, "story": 1})


class Panel2Funnel(unittest.TestCase):
    def test_funnel_counts_completed_steps_and_pr_terminus(self):
        with TemporaryDirectory() as ws:
            write_index(ws, {"MAR-6": {"status": "done", "type": "task"},
                             "MAR-5": {"status": "in_progress", "type": "story"}})
            write_metrics(ws, {"prs": {"created": 5, "merged": 4}})
            # MAR-6 reaches merge-pr (all five steps completed); MAR-5 only reaches code
            write_pipeline(ws, "MAR-6", steps=_full_funnel_steps("merge-pr"), archived=True)
            write_pipeline(ws, "MAR-5", steps=_full_funnel_steps("code"))
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            p2 = out["panels"]["2"]
            self.assertEqual(p2["steps"]["create-ticket"], 2)
            self.assertEqual(p2["steps"]["create-spec"], 2)
            self.assertEqual(p2["steps"]["code"], 2)
            self.assertEqual(p2["steps"]["create-pr"], 1)
            self.assertEqual(p2["steps"]["merge-pr"], 1)
            self.assertEqual(p2["prs"], {"created": 5, "merged": 4})


class Panel3CostTime(unittest.TestCase):
    def test_per_ticket_seconds_and_totals_rollup(self):
        with TemporaryDirectory() as ws:
            write_index(ws, {"MAR-6": {"status": "done", "type": "task"}})
            steps = {
                "code": {"started_at": "2026-06-15T16:24:30Z", "status": "completed",
                         "ended_at": "2026-06-15T17:03:15Z"},
            }
            totals = {"runs": 5, "working_seconds": 11922,
                      "tokens": {"input": 1306000, "output": 237000}, "cost_usd": 8.31}
            write_pipeline(ws, "MAR-6", steps=steps, totals=totals, archived=True)
            write_metrics(ws, {"totals": {"runs": 17, "working_seconds": 64238,
                                          "tokens": {"input": 3102000, "output": 508500}, "cost_usd": 18.75}})
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            p3 = out["panels"]["3"]
            row = next(r for r in p3["tickets"] if r["ticket_id"] == "MAR-6")
            # run_seconds(16:24:30 -> 17:03:15) == 2325s
            self.assertEqual(row["steps"]["code"], 2325)
            self.assertEqual(row["totals"]["working_seconds"], 11922)
            self.assertEqual(row["totals"]["cost_usd"], 8.31)
            self.assertEqual(p3["repo_totals"]["working_seconds"], 64238)
            self.assertEqual(p3["repo_totals"]["cost_usd"], 18.75)


class Panel4Coverage(unittest.TestCase):
    def test_numeric_cell(self):
        with TemporaryDirectory() as ws:
            write_index(ws, {"MAR-9": {"status": "done", "type": "task"}})
            write_code_state(ws, "MAR-9", {"tests": {"coverage_percent": 93.4, "coverage_target": 90},
                                           "verifier_passed": True})
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            row = next(r for r in out["panels"]["4"]["tickets"] if r["ticket_id"] == "MAR-9")
            self.assertEqual(row["achieved"], 93.4)
            self.assertEqual(row["target"], 90)
            self.assertTrue(row["passed"])

    def test_null_percent_or_na_target_is_no_data_with_degraded(self):
        with TemporaryDirectory() as ws:
            write_index(ws, {"MAR-6": {"status": "done", "type": "task"}})
            write_code_state(ws, "MAR-6", {"tests": {"passed": 81, "failed": 0, "coverage_percent": None,
                                                     "coverage_target": "n/a (no new production code)"},
                                           "verifier_passed": True}, archived=True)
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            row = next(r for r in out["panels"]["4"]["tickets"] if r["ticket_id"] == "MAR-6")
            self.assertEqual(row["cell"], "no data")
            self.assertTrue(any(d["ticket_id"] == "MAR-6" and d["panel"] == 4 for d in out["meta"]["degraded"]))


class Panel5ReviewIterations(unittest.TestCase):
    def test_authoritative_from_code_state(self):
        with TemporaryDirectory() as ws:
            write_index(ws, {"MAR-6": {"status": "done", "type": "task"}})
            write_code_state(ws, "MAR-6", {"review": {"iterations": 2, "findings_open": 0}}, archived=True)
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            row = next(r for r in out["panels"]["5"]["tickets"] if r["ticket_id"] == "MAR-6")
            self.assertEqual(row["iterations"], 2)

    def test_verify_xml_max_fallback_when_field_absent(self):
        with TemporaryDirectory() as ws:
            write_index(ws, {"MAR-7": {"status": "done", "type": "task"}})
            # code-state with NO review.iterations -> fallback to max verify-XML iteration
            write_code_state(ws, "MAR-7", {"tests": {"coverage_percent": 91.0, "coverage_target": 90}})
            write_result_xml(ws, "MAR-7", "code", "verify", 1)
            write_result_xml(ws, "MAR-7", "code", "verify", 2)
            write_result_xml(ws, "MAR-7", "code", "verify", 3)
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            row = next(r for r in out["panels"]["5"]["tickets"] if r["ticket_id"] == "MAR-7")
            self.assertEqual(row["iterations"], 3)


class Panel6TokenBurn(unittest.TestCase):
    def test_three_role_buckets_order_independent_coordinate_excluded_and_zero(self):
        with TemporaryDirectory() as ws:
            write_index(ws, {"MAR-6": {"status": "done", "type": "task"}})
            # plan -> planner; execute -> executor; verify -> verifier (one with reordered attrs)
            write_result_xml(ws, "MAR-6", "code", "plan", 1, ti=42000, to=7500, cost=0.17, archived=True)
            write_result_xml(ws, "MAR-6", "code", "execute", 1, ti=480000, to=90000, cost=3.5, archived=True)
            write_result_xml(ws, "MAR-6", "code", "verify", 1, ti=100000, to=20000, cost=1.0,
                             reorder=True, archived=True)
            # coordinate phase -> contributes 0 to all role buckets (ledger C-5)
            write_result_xml(ws, "MAR-6", "code", "coordinate", 1, ti=999999, to=999999, cost=99.0,
                             archived=True)
            # a -task.xml without metrics, and a merge-pr phase dir with NO metrics XML -> 0 contribution
            write_task_xml(ws, "MAR-6", "code", "plan", 1, archived=True)
            write_result_xml(ws, "MAR-6", "merge-pr", "plan", 1, no_metrics=True, archived=True)
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            p6 = out["panels"]["6"]
            self.assertEqual(p6["planner"], {"input": 42000, "output": 7500, "cost": 0.17})
            self.assertEqual(p6["executor"], {"input": 480000, "output": 90000, "cost": 3.5})
            self.assertEqual(p6["verifier"], {"input": 100000, "output": 20000, "cost": 1.0})
            # coordinate's 999999 burn appears in no role bucket
            self.assertNotIn("coordinate", p6)
            self.assertEqual(p6["planner"]["input"], 42000)

    def test_missing_attribute_defaults_to_zero(self):
        with TemporaryDirectory() as ws:
            write_index(ws, {"MAR-8": {"status": "done", "type": "task"}})
            tdir = _ticket_dir(ws, "MAR-8")
            # a metrics tag with only tokens-input present; the others default to schema 0
            body = ('<result skill="code" phase="plan" ticket-id="MAR-8" iteration="1" status="completed">\n'
                    '  <metrics tokens-input="500"/>\n</result>\n')
            _write_text(os.path.join(tdir, "phases", "code", "iter-1-plan.xml"), body)
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            self.assertEqual(out["panels"]["6"]["planner"], {"input": 500, "output": 0, "cost": 0.0})


# ---------------------------------------------------------------------------
# Edge-case tests (AC-5)
# ---------------------------------------------------------------------------

class EmptyWorkspace(unittest.TestCase):
    def test_no_index_all_panels_no_data(self):
        with TemporaryDirectory() as ws:
            os.makedirs(_repo_dir(ws), exist_ok=True)  # repo dir, but no tickets-index.json
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            self.assertEqual(out["meta"]["ticket_count"], 0)
            for k in ("1", "2", "3", "4", "5", "6"):
                self.assertIn(k, out["panels"])
                self.assertEqual(out["panels"][k], "no data")

    def test_empty_tickets_dict_all_panels_no_data(self):
        with TemporaryDirectory() as ws:
            write_index(ws, {})
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            self.assertEqual(out["meta"]["ticket_count"], 0)
            for k in ("1", "2", "3", "4", "5", "6"):
                self.assertEqual(out["panels"][k], "no data")

    def test_main_smoke_exits_zero_on_empty(self):
        # main() resolves context via build_context (git + settings) then prints JSON; we patch
        # build_context so the smoke path runs without git/settings, against an empty workspace.
        with TemporaryDirectory() as ws:
            write_index(ws, {})
            orig = acs_lib.build_context
            acs_lib.build_context = lambda cwd: {"workspace": ws, "repo_id": REPO_ID}
            captured = {}
            orig_print = __builtins__["print"] if isinstance(__builtins__, dict) else None
            try:
                rc = metrics_aggregate.main()
            finally:
                acs_lib.build_context = orig
            self.assertEqual(rc, 0)


class MissingPartialState(unittest.TestCase):
    def test_absent_state_files_degrade_affected_panels(self):
        with TemporaryDirectory() as ws:
            # ticket in the index but NO state files at all on disk
            write_index(ws, {"MAR-X": {"status": "in_progress", "type": "task"}})
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            # panels 4 and 5 (code-state) degrade for this ticket
            deg = out["meta"]["degraded"]
            self.assertTrue(any(d["ticket_id"] == "MAR-X" and d["panel"] == 4 for d in deg))
            self.assertTrue(any(d["ticket_id"] == "MAR-X" and d["panel"] == 5 for d in deg))
            # panel 2/3 (pipeline-state) degrade for this ticket
            self.assertTrue(any(d["ticket_id"] == "MAR-X" and d["panel"] in (2, 3) for d in deg))
            # no exception, all six keys present, reason strings populated
            for k in ("1", "2", "3", "4", "5", "6"):
                self.assertIn(k, out["panels"])
            self.assertTrue(all(isinstance(d["reason"], str) and d["reason"] for d in deg))


# ---------------------------------------------------------------------------
# Performance (AC-6) — 50 tickets, single aggregate() call < 5 s
# ---------------------------------------------------------------------------

class Performance(unittest.TestCase):
    def test_fifty_tickets_under_five_seconds(self):
        with TemporaryDirectory() as ws:
            tickets = {}
            for n in range(50):
                tid = "PERF-%d" % n
                tickets[tid] = {"status": "done", "type": "task"}
                write_pipeline(ws, tid, steps=_full_funnel_steps("merge-pr"),
                               totals={"runs": 5, "working_seconds": 100,
                                       "tokens": {"input": 1, "output": 1}, "cost_usd": 1.0})
                write_code_state(ws, tid, {"tests": {"coverage_percent": 90.0, "coverage_target": 90},
                                           "review": {"iterations": 2}})
                write_create_pr_state(ws, tid)
                # ~22 metric-bearing XMLs per ticket across phases (mirrors live MAR-6 distribution)
                for i in range(4):
                    write_result_xml(ws, tid, "code", "plan", i + 1, ti=1, to=1, cost=0.1)
                for i in range(9):
                    write_result_xml(ws, tid, "code", "execute", i + 1, ti=1, to=1, cost=0.1)
                for i in range(9):
                    write_result_xml(ws, tid, "code", "verify", i + 1, ti=1, to=1, cost=0.1)
            write_index(ws, tickets)
            write_metrics(ws, {"tickets": {"by_status": {"done": 50}, "by_type": {"task": 50}},
                               "prs": {"created": 50, "merged": 50},
                               "totals": {"runs": 250, "working_seconds": 5000,
                                          "tokens": {"input": 50, "output": 50}, "cost_usd": 50.0}})
            t0 = time.monotonic()
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            elapsed = time.monotonic() - t0
            self.assertLess(elapsed, 5.0, "aggregate() took %.3fs (>= 5s) for 50 tickets" % elapsed)
            self.assertEqual(out["meta"]["ticket_count"], 50)
            # each ticket's 22 XMLs (4 plan + 9 execute + 9 verify) summed correctly
            self.assertEqual(out["panels"]["6"]["planner"]["input"], 50 * 4)
            self.assertEqual(out["panels"]["6"]["executor"]["input"], 50 * 9)
            self.assertEqual(out["panels"]["6"]["verifier"]["input"], 50 * 9)


# ---------------------------------------------------------------------------
# Read-only assertion (AC-4 at the helper layer)
# ---------------------------------------------------------------------------

class ReadOnly(unittest.TestCase):
    def _snapshot_mtimes(self, root):
        snap = {}
        for dirpath, _dirs, files in os.walk(root):
            for f in files:
                p = os.path.join(dirpath, f)
                snap[p] = os.stat(p).st_mtime_ns
        return snap

    def test_mtimes_unchanged_and_write_json_never_called(self):
        with TemporaryDirectory() as ws:
            write_index(ws, {"MAR-6": {"status": "done", "type": "task"}})
            write_metrics(ws, {"tickets": {"by_status": {"done": 1}, "by_type": {"task": 1}}})
            write_pipeline(ws, "MAR-6", steps=_full_funnel_steps("merge-pr"),
                           totals={"runs": 5, "working_seconds": 100,
                                   "tokens": {"input": 1, "output": 1}, "cost_usd": 1.0}, archived=True)
            write_code_state(ws, "MAR-6", {"review": {"iterations": 2},
                                           "tests": {"coverage_percent": 90.0, "coverage_target": 90}},
                             archived=True)
            write_result_xml(ws, "MAR-6", "code", "plan", 1, ti=1, to=1, cost=0.1, archived=True)

            before = self._snapshot_mtimes(_repo_dir(ws))

            # spy: assert write_json is never called during a run
            calls = []
            orig_write = acs_lib.write_json
            acs_lib.write_json = lambda *a, **k: calls.append(a)
            try:
                metrics_aggregate.aggregate(ws, REPO_ID)
            finally:
                acs_lib.write_json = orig_write

            after = self._snapshot_mtimes(_repo_dir(ws))
            self.assertEqual(before, after, "workspace file mtimes changed — helper is not read-only")
            self.assertEqual(calls, [], "acs_lib.write_json was called — helper must make zero writes")


if __name__ == "__main__":
    unittest.main()
