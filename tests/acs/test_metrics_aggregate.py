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
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
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


def write_ticket_json(ws, tid, created_at, archived=False):
    """Write <partition>/ticket.json carrying created_at (lead-time anchor for panel 7)."""
    tdir = _ticket_dir(ws, tid, archived)
    _write_json(os.path.join(tdir, "ticket.json"),
                {"id": tid, "created_at": created_at})


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
# Panel 3 averages (AC-1) — four averages incl. both divide-by-zero
# ---------------------------------------------------------------------------

class AveragesPanel3(unittest.TestCase):
    def test_exact_four_averages(self):
        with TemporaryDirectory() as ws:
            # 4 tickets -> ticket_count == 4; prs.merged == 2
            write_index(ws, {
                "MAR-1": {"status": "done", "type": "task"},
                "MAR-2": {"status": "done", "type": "task"},
                "MAR-3": {"status": "done", "type": "task"},
                "MAR-4": {"status": "in_progress", "type": "task"},
            })
            write_metrics(ws, {"prs": {"created": 4, "merged": 2},
                               "totals": {"working_seconds": 64238, "cost_usd": 18.76}})
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            avgs = out["panels"]["3"]["averages"]
            self.assertEqual(avgs["avg_working_seconds_per_ticket"], 64238 / 4)
            self.assertEqual(avgs["avg_working_seconds_per_pr"], 64238 / 2)
            self.assertEqual(avgs["avg_cost_per_ticket"], 18.76 / 4)
            self.assertEqual(avgs["avg_cost_per_pr"], 18.76 / 2)
            # existing Panel 3 keys untouched (additive)
            self.assertIn("tickets", out["panels"]["3"])
            self.assertIn("repo_totals", out["panels"]["3"])

    def test_divide_by_zero_ticket_count_empty_early_return(self):
        # ticket_count == 0 -> the empty-workspace early return; averages unreachable, panel "no data".
        with TemporaryDirectory() as ws:
            write_index(ws, {})
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            self.assertEqual(out["panels"]["3"], "no data")  # no exception, no ZeroDivisionError

    def test_divide_by_zero_prs_merged_zero(self):
        # populated workspace (per-ticket averages compute) but prs.merged == 0 -> per-PR "no data".
        with TemporaryDirectory() as ws:
            write_index(ws, {"MAR-6": {"status": "done", "type": "task"}})
            write_metrics(ws, {"prs": {"created": 3, "merged": 0},
                               "totals": {"working_seconds": 1200, "cost_usd": 4.0}})
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            avgs = out["panels"]["3"]["averages"]
            self.assertEqual(avgs["avg_working_seconds_per_pr"], "no data")
            self.assertEqual(avgs["avg_cost_per_pr"], "no data")
            # per-ticket averages still compute (ticket_count == 1)
            self.assertEqual(avgs["avg_working_seconds_per_ticket"], 1200.0)
            self.assertEqual(avgs["avg_cost_per_ticket"], 4.0)

    def test_prs_absent_defaults_merged_zero(self):
        # no prs key in metrics.json -> defaults to merged == 0 -> per-PR averages "no data".
        with TemporaryDirectory() as ws:
            write_index(ws, {"MAR-6": {"status": "done", "type": "task"}})
            write_metrics(ws, {"totals": {"working_seconds": 1200, "cost_usd": 4.0}})
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            avgs = out["panels"]["3"]["averages"]
            self.assertEqual(avgs["avg_working_seconds_per_pr"], "no data")
            self.assertEqual(avgs["avg_cost_per_pr"], "no data")

    def test_non_numeric_totals_are_no_data(self):
        # totals.working_seconds None / cost_usd absent -> those averages "no data", no exception.
        with TemporaryDirectory() as ws:
            write_index(ws, {"MAR-6": {"status": "done", "type": "task"}})
            write_metrics(ws, {"prs": {"created": 2, "merged": 2},
                               "totals": {"working_seconds": None}})
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            avgs = out["panels"]["3"]["averages"]
            self.assertEqual(avgs["avg_working_seconds_per_ticket"], "no data")
            self.assertEqual(avgs["avg_working_seconds_per_pr"], "no data")
            self.assertEqual(avgs["avg_cost_per_ticket"], "no data")
            self.assertEqual(avgs["avg_cost_per_pr"], "no data")

    def test_bool_denominator_treated_non_numeric(self):
        # a bool merged value must not act as 1 -> "no data" (mirror panel-4 bool guard).
        with TemporaryDirectory() as ws:
            write_index(ws, {"MAR-6": {"status": "done", "type": "task"}})
            write_metrics(ws, {"prs": {"created": 1, "merged": True},
                               "totals": {"working_seconds": 100, "cost_usd": 1.0}})
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            avgs = out["panels"]["3"]["averages"]
            self.assertEqual(avgs["avg_working_seconds_per_pr"], "no data")
            self.assertEqual(avgs["avg_cost_per_pr"], "no data")


# ---------------------------------------------------------------------------
# Panel 7 lead/cycle wall-clock (AC-2) — exact seconds, edges, subset averages
# ---------------------------------------------------------------------------

def _lead_cycle_steps(code_started, merge_ended, create_pr_ended=None):
    """A steps dict carrying the code.started_at and merge-pr.ended_at anchors panel 7 reads.

    create_pr_ended is a deliberately-different create-pr.ended_at so a test can prove the end
    anchor is merge-pr (not create-pr).
    """
    steps = {
        "code": {"started_at": code_started, "status": "completed",
                 "ended_at": "2026-06-15T11:00:00Z"},
        "merge-pr": {"started_at": "2026-06-15T12:00:00Z", "status": "completed",
                     "ended_at": merge_ended},
    }
    if create_pr_ended is not None:
        steps["create-pr"] = {"started_at": "2026-06-15T11:30:00Z", "status": "completed",
                              "ended_at": create_pr_ended}
    return steps


class LeadCyclePanel7(unittest.TestCase):
    def _row(self, out, tid):
        return next(r for r in out["panels"]["7"]["tickets"] if r["ticket_id"] == tid)

    def test_exact_lead_and_cycle_seconds_merge_pr_anchor(self):
        with TemporaryDirectory() as ws:
            write_index(ws, {"MAR-6": {"status": "done", "type": "task"}})
            # created 10:00:00, code started 10:30:00, merge-pr ended 13:00:00,
            # create-pr ended 11:45:00 (different -> proves merge-pr is the anchor).
            write_ticket_json(ws, "MAR-6", "2026-06-15T10:00:00Z", archived=True)
            write_pipeline(ws, "MAR-6",
                           steps=_lead_cycle_steps("2026-06-15T10:30:00Z", "2026-06-15T13:00:00Z",
                                                   create_pr_ended="2026-06-15T11:45:00Z"),
                           archived=True)
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            row = self._row(out, "MAR-6")
            # lead = 13:00:00 - 10:00:00 = 3h = 10800s
            self.assertEqual(row["lead_seconds"], 10800)
            # cycle = 13:00:00 - 10:30:00 = 2h30m = 9000s
            self.assertEqual(row["cycle_seconds"], 9000)
            # NOT the create-pr figure: lead to create-pr would be 6300s; cycle 4500s
            self.assertNotEqual(row["lead_seconds"], 6300)
            self.assertNotEqual(row["cycle_seconds"], 4500)
            # averages over the single ticket with values
            self.assertEqual(out["panels"]["7"]["avg_lead_seconds"], 10800.0)
            self.assertEqual(out["panels"]["7"]["avg_cycle_seconds"], 9000.0)

    def test_open_ticket_no_merge_pr_ended_both_no_data(self):
        with TemporaryDirectory() as ws:
            write_index(ws, {"MAR-4": {"status": "in_progress", "type": "task"}})
            write_ticket_json(ws, "MAR-4", "2026-06-15T10:00:00Z")
            # code present, but merge-pr.ended_at is None (unmerged)
            write_pipeline(ws, "MAR-4",
                           steps=_lead_cycle_steps("2026-06-15T10:30:00Z", None))
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            row = self._row(out, "MAR-4")
            self.assertEqual(row["lead_seconds"], "no data")
            self.assertEqual(row["cycle_seconds"], "no data")
            self.assertTrue(any(d["ticket_id"] == "MAR-4" and d["panel"] == 7
                                and isinstance(d["reason"], str) and d["reason"]
                                for d in out["meta"]["degraded"]))

    def test_merged_missing_code_step_cycle_no_data_lead_computes(self):
        with TemporaryDirectory() as ws:
            write_index(ws, {"MAR-1": {"status": "done", "type": "task"}})
            write_ticket_json(ws, "MAR-1", "2026-06-15T10:00:00Z", archived=True)
            # merged (merge-pr.ended present) but code.started_at is None
            write_pipeline(ws, "MAR-1",
                           steps=_lead_cycle_steps(None, "2026-06-15T13:00:00Z"),
                           archived=True)
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            row = self._row(out, "MAR-1")
            self.assertEqual(row["lead_seconds"], 10800)        # lead still computes
            self.assertEqual(row["cycle_seconds"], "no data")   # cycle unavailable
            self.assertTrue(any(d["ticket_id"] == "MAR-1" and d["panel"] == 7
                                for d in out["meta"]["degraded"]))

    def test_missing_created_at_lead_no_data_cycle_computes(self):
        with TemporaryDirectory() as ws:
            write_index(ws, {"MAR-2": {"status": "done", "type": "task"}})
            # NO ticket.json -> created_at absent
            write_pipeline(ws, "MAR-2",
                           steps=_lead_cycle_steps("2026-06-15T10:30:00Z", "2026-06-15T13:00:00Z"),
                           archived=True)
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            row = self._row(out, "MAR-2")
            self.assertEqual(row["lead_seconds"], "no data")    # lead unavailable
            self.assertEqual(row["cycle_seconds"], 9000)        # cycle still computes
            self.assertTrue(any(d["ticket_id"] == "MAR-2" and d["panel"] == 7
                                for d in out["meta"]["degraded"]))

    def test_averages_only_over_tickets_with_a_value(self):
        with TemporaryDirectory() as ws:
            write_index(ws, {
                "FULL": {"status": "done", "type": "task"},      # lead + cycle both
                "OPEN": {"status": "in_progress", "type": "task"},  # neither
                "NOCODE": {"status": "done", "type": "task"},    # lead only
            })
            write_ticket_json(ws, "FULL", "2026-06-15T10:00:00Z")
            write_pipeline(ws, "FULL",
                           steps=_lead_cycle_steps("2026-06-15T10:30:00Z", "2026-06-15T13:00:00Z"))
            write_ticket_json(ws, "OPEN", "2026-06-15T10:00:00Z")
            write_pipeline(ws, "OPEN", steps=_lead_cycle_steps("2026-06-15T10:30:00Z", None))
            write_ticket_json(ws, "NOCODE", "2026-06-15T09:00:00Z")
            write_pipeline(ws, "NOCODE", steps=_lead_cycle_steps(None, "2026-06-15T13:00:00Z"))
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            p7 = out["panels"]["7"]
            # leads with a value: FULL 10800, NOCODE (13:00-09:00) 14400 -> mean 12600
            self.assertEqual(p7["avg_lead_seconds"], (10800 + 14400) / 2)
            # cycles with a value: only FULL 9000 -> mean 9000
            self.assertEqual(p7["avg_cycle_seconds"], 9000.0)

    def test_no_ticket_has_a_value_averages_no_data(self):
        with TemporaryDirectory() as ws:
            write_index(ws, {"OPEN": {"status": "in_progress", "type": "task"}})
            write_ticket_json(ws, "OPEN", "2026-06-15T10:00:00Z")
            write_pipeline(ws, "OPEN", steps=_lead_cycle_steps("2026-06-15T10:30:00Z", None))
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            p7 = out["panels"]["7"]
            self.assertEqual(p7["avg_lead_seconds"], "no data")
            self.assertEqual(p7["avg_cycle_seconds"], "no data")

    def test_negative_interval_yields_no_data(self):
        # merge-pr.ended_at BEFORE created_at -> negative -> lead "no data" (total function).
        with TemporaryDirectory() as ws:
            write_index(ws, {"MAR-9": {"status": "done", "type": "task"}})
            write_ticket_json(ws, "MAR-9", "2026-06-15T14:00:00Z")
            write_pipeline(ws, "MAR-9",
                           steps=_lead_cycle_steps("2026-06-15T10:30:00Z", "2026-06-15T13:00:00Z"))
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            row = self._row(out, "MAR-9")
            self.assertEqual(row["lead_seconds"], "no data")   # 13:00 < 14:00 -> negative
            self.assertEqual(row["cycle_seconds"], 9000)       # cycle still positive

    def test_pipeline_absent_panel7_open_ticket_row(self):
        # ticket in index, NO pipeline-state.json -> panel-7 row present, both "no data", degrade.
        with TemporaryDirectory() as ws:
            write_index(ws, {"MAR-X": {"status": "in_progress", "type": "task"}})
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            row = self._row(out, "MAR-X")
            self.assertEqual(row["lead_seconds"], "no data")
            self.assertEqual(row["cycle_seconds"], "no data")
            self.assertTrue(any(d["ticket_id"] == "MAR-X" and d["panel"] == 7
                                for d in out["meta"]["degraded"]))

    def test_never_raises_one_row_per_ticket(self):
        with TemporaryDirectory() as ws:
            write_index(ws, {"A": {"status": "done", "type": "task"},
                             "B": {"status": "in_progress", "type": "task"}})
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            ids = [r["ticket_id"] for r in out["panels"]["7"]["tickets"]]
            self.assertEqual(sorted(ids), ["A", "B"])  # one row per ticket
            for k in ("1", "2", "3", "4", "5", "6", "7"):
                self.assertIn(k, out["panels"])


# ---------------------------------------------------------------------------
# Edge-case tests (AC-5)
# ---------------------------------------------------------------------------

class EmptyWorkspace(unittest.TestCase):
    def test_no_index_all_panels_no_data(self):
        with TemporaryDirectory() as ws:
            os.makedirs(_repo_dir(ws), exist_ok=True)  # repo dir, but no tickets-index.json
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            self.assertEqual(out["meta"]["ticket_count"], 0)
            for k in ("1", "2", "3", "4", "5", "6", "7"):
                self.assertIn(k, out["panels"])
                self.assertEqual(out["panels"][k], "no data")

    def test_empty_tickets_dict_all_panels_no_data(self):
        with TemporaryDirectory() as ws:
            write_index(ws, {})
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            self.assertEqual(out["meta"]["ticket_count"], 0)
            for k in ("1", "2", "3", "4", "5", "6", "7"):
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
            # panel 7 (no pipeline) degrades for this ticket too
            self.assertTrue(any(d["ticket_id"] == "MAR-X" and d["panel"] == 7 for d in deg))
            # no exception, all seven keys present, reason strings populated
            for k in ("1", "2", "3", "4", "5", "6", "7"):
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
            # panel-7 lead-time anchor: a per-ticket ticket.json the new read opens read-only
            write_ticket_json(ws, "MAR-6", "2026-06-15T10:00:00Z", archived=True)
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
