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

    # -----------------------------------------------------------------------
    # AC-5: cycle-inversion — code.started_at AFTER merge-pr.ended_at
    # -----------------------------------------------------------------------

    def test_cycle_inversion_yields_no_data(self):
        """AC-5: code.started_at AFTER merge-pr.ended_at -> cycle 'no data' + meta.degraded.

        Exercises the not(end >= start) branch in _elapsed_seconds for the CYCLE computation
        specifically (the LEAD path through the same branch is covered by
        test_negative_interval_yields_no_data). The fixture sets a valid lead span so that
        test_cycle_inversion_yields_no_data is a pure cycle-inversion test.
        """
        with TemporaryDirectory() as ws:
            write_index(ws, {"T-001": {"status": "done", "type": "task"}})
            # created_at well before merge_ended -> lead is valid (positive).
            write_ticket_json(ws, "T-001", "2025-01-01T00:00:00Z")
            # code.started_at (2025-06-01) is AFTER merge-pr.ended_at (2025-05-01) -> inversion
            inverted_steps = {
                "code": {
                    "started_at": "2025-06-01T12:00:00Z",   # AFTER merge ended
                    "status": "completed",
                    "ended_at": "2025-06-01T13:00:00Z",
                },
                "merge-pr": {
                    "started_at": "2025-04-30T12:00:00Z",
                    "status": "completed",
                    "ended_at": "2025-05-01T12:00:00Z",     # merge ended BEFORE code started
                },
            }
            write_pipeline(ws, "T-001", steps=inverted_steps)
            # Must not raise (AC-5: "never raises")
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            row = self._row(out, "T-001")
            # AC-5: inverted cycle span -> "no data"
            self.assertEqual(row["cycle_seconds"], "no data")
            # lead should still compute (created_at 2025-01-01 -> merge_ended 2025-05-01 is valid)
            self.assertIsInstance(row["lead_seconds"], int)
            self.assertGreater(row["lead_seconds"], 0)
            # AC-5: meta.degraded must contain an entry for T-001 with panel 7
            self.assertTrue(any(d["ticket_id"] == "T-001" and d["panel"] == 7
                                for d in out["meta"]["degraded"]))
            # AC-5: exactly one row for T-001
            rows_for_t001 = [r for r in out["panels"]["7"]["tickets"] if r["ticket_id"] == "T-001"]
            self.assertEqual(len(rows_for_t001), 1)

    def test_cycle_inverted_full_aggregate_no_raise_one_row_all_panels(self):
        """AC-5 integration: full aggregate() pipeline with a cycle-inverted ticket does not raise.

        Proves AC-6 read-only invariant: aggregate() never writes even in the error path
        (the filesystem must be unchanged). One Panel-7 row per ticket; all panel keys present.
        """
        with TemporaryDirectory() as ws:
            write_index(ws, {"INV": {"status": "done", "type": "task"},
                             "OK": {"status": "done", "type": "task"}})
            write_ticket_json(ws, "INV", "2025-01-01T00:00:00Z")
            # INV: cycle-inverted
            write_pipeline(ws, "INV", steps={
                "code": {"started_at": "2025-06-01T12:00:00Z", "status": "completed",
                         "ended_at": "2025-06-01T13:00:00Z"},
                "merge-pr": {"started_at": "2025-04-30T00:00:00Z", "status": "completed",
                             "ended_at": "2025-05-01T00:00:00Z"},
            })
            write_ticket_json(ws, "OK", "2025-01-01T00:00:00Z")
            # OK: valid cycle
            write_pipeline(ws, "OK", steps=_lead_cycle_steps(
                "2025-02-01T10:00:00Z", "2025-03-01T10:00:00Z"))
            # Must not raise
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            # All seven panel keys present
            for k in ("1", "2", "3", "4", "5", "6", "7"):
                self.assertIn(k, out["panels"])
            # One row per ticket in panel 7
            ids = [r["ticket_id"] for r in out["panels"]["7"]["tickets"]]
            self.assertEqual(sorted(ids), ["INV", "OK"])
            # INV row: cycle "no data"; OK row: cycle valid
            inv_row = self._row(out, "INV")
            ok_row = self._row(out, "OK")
            self.assertEqual(inv_row["cycle_seconds"], "no data")
            self.assertIsInstance(ok_row["cycle_seconds"], int)
            self.assertGreater(ok_row["cycle_seconds"], 0)


# ---------------------------------------------------------------------------
# Panel 7 per-ticket re-work count (AC-8, spec 02)
# ---------------------------------------------------------------------------

class Panel7ReworkCount(unittest.TestCase):
    """Test the rework_count field added to each Panel-7 per-ticket row (AC-8)."""

    def _row(self, out, tid):
        return next(r for r in out["panels"]["7"]["tickets"] if r["ticket_id"] == tid)

    def test_rework_count_distinct_prs_dedup(self):
        """AC-8: rework_count == count of distinct positive PR numbers in create-pr-state.json.

        Two distinct numbers (10 and 11) with a duplicate 10 -> count 2.
        """
        with TemporaryDirectory() as ws:
            write_index(ws, {"MAR-X": {"status": "done", "type": "task"}})
            write_ticket_json(ws, "MAR-X", "2025-01-01T00:00:00Z")
            # Pipeline with valid lead and cycle
            write_pipeline(ws, "MAR-X", steps=_lead_cycle_steps(
                "2025-02-01T10:00:00Z", "2025-03-01T10:00:00Z"))
            # create-pr-state.json in the ACTIVE partition with PR number 10
            # The plan says find_ticket_partition returns ONE partition (active OR archive).
            # Active partition wins here; put both PR numbers in the same state file's history
            # by nesting a "runs" list that records distinct PR numbers.
            # _rework_count reads states.pr.number from the resolved tdir.
            # To test de-dup with two numbers, we need two distinct numbers; since
            # _rework_count(tdir) reads create-pr-state.json once, we store two numbers
            # by using a "pr_numbers" list OR by noting the spec says read states.pr.number.
            # Per plan E2 note: "distinct numbers in the single resolved partition's state file".
            # The simplest approach: write the state file with two distinct PR numbers across
            # runs (the helper reads states.pr.number from the root; the plan note says
            # "simplest is distinct numbers in the single resolved partition's state file").
            # Since the current write_create_pr_state writes {"states": {...}, "runs": []},
            # we write a custom state file with multiple runs, each carrying a pr.number.
            # _rework_count should collect distinct PR numbers from any place they appear.
            # We store PR numbers 10 and 11 (with a dup 10 in runs) to test de-dup.
            tdir = _ticket_dir(ws, "MAR-X")
            _write_json(os.path.join(tdir, "create-pr-state.json"), {
                "skill": "create-pr",
                "ticket_id": "MAR-X",
                "states": {"pr": {"number": 10}},
                "runs": [
                    {"pr": {"number": 10}},   # duplicate
                    {"pr": {"number": 11}},   # distinct
                ],
            })
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            row = self._row(out, "MAR-X")
            # rework_count field must exist on the row
            self.assertIn("rework_count", row)
            # AC-8: 2 distinct positive PR numbers (10 and 11; the dup 10 is de-duped)
            self.assertEqual(row["rework_count"], 2)
            # AC-8: existing keys unchanged
            self.assertIn("ticket_id", row)
            self.assertIn("lead_seconds", row)
            self.assertIn("cycle_seconds", row)

    def test_rework_count_zero_when_no_create_pr_state(self):
        """AC-8: rework_count == 0 when no create-pr-state.json is present."""
        with TemporaryDirectory() as ws:
            write_index(ws, {"MAR-Y": {"status": "done", "type": "task"}})
            write_ticket_json(ws, "MAR-Y", "2025-01-01T00:00:00Z")
            write_pipeline(ws, "MAR-Y", steps=_lead_cycle_steps(
                "2025-02-01T10:00:00Z", "2025-03-01T10:00:00Z"))
            # No create-pr-state.json written
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            row = self._row(out, "MAR-Y")
            self.assertIn("rework_count", row)
            self.assertEqual(row["rework_count"], 0)

    def test_rework_count_zero_when_pr_number_null(self):
        """AC-8: rework_count == 0 when states.pr.number is null/None (not a positive int)."""
        with TemporaryDirectory() as ws:
            write_index(ws, {"MAR-Z": {"status": "done", "type": "task"}})
            write_ticket_json(ws, "MAR-Z", "2025-01-01T00:00:00Z")
            write_pipeline(ws, "MAR-Z", steps=_lead_cycle_steps(
                "2025-02-01T10:00:00Z", "2025-03-01T10:00:00Z"))
            # states.pr.number is null -> should not count
            write_create_pr_state(ws, "MAR-Z", states={"pr": {"number": None}})
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            row = self._row(out, "MAR-Z")
            self.assertIn("rework_count", row)
            self.assertEqual(row["rework_count"], 0)

    def test_rework_count_no_raise_on_malformed_state(self):
        """AC-8: aggregate() does not raise when create-pr-state.json is malformed or absent."""
        with TemporaryDirectory() as ws:
            write_index(ws, {"MAR-W": {"status": "done", "type": "task"}})
            write_ticket_json(ws, "MAR-W", "2025-01-01T00:00:00Z")
            write_pipeline(ws, "MAR-W", steps=_lead_cycle_steps(
                "2025-02-01T10:00:00Z", "2025-03-01T10:00:00Z"))
            # Write a malformed (non-JSON) create-pr-state.json
            tdir = _ticket_dir(ws, "MAR-W")
            _write_text(os.path.join(tdir, "create-pr-state.json"), "not valid json {{{{")
            # Must not raise; rework_count defaults to 0
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            row = self._row(out, "MAR-W")
            self.assertIn("rework_count", row)
            self.assertEqual(row["rework_count"], 0)
            # all panel keys present
            for k in ("1", "2", "3", "4", "5", "6", "7"):
                self.assertIn(k, out["panels"])

    def test_rework_count_not_averaged_in_panel7(self):
        """AC-8: rework_count does not appear in panel-7 averages (it is per-ticket metadata)."""
        with TemporaryDirectory() as ws:
            write_index(ws, {"MAR-A": {"status": "done", "type": "task"}})
            write_ticket_json(ws, "MAR-A", "2025-01-01T00:00:00Z")
            write_pipeline(ws, "MAR-A", steps=_lead_cycle_steps(
                "2025-02-01T10:00:00Z", "2025-03-01T10:00:00Z"))
            write_create_pr_state(ws, "MAR-A", states={"pr": {"number": 5}})
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            p7 = out["panels"]["7"]
            # Panel-7 aggregate keys: only lead and cycle averages
            self.assertIn("avg_lead_seconds", p7)
            self.assertIn("avg_cycle_seconds", p7)
            # rework_count must NOT appear as a panel-level average
            self.assertNotIn("avg_rework_count", p7)
            self.assertNotIn("rework_count", p7)


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


# ---------------------------------------------------------------------------
# MAR-14 spec 01 — new panel key tests (TestDeliverySummary, TestIssues,
# TestProgress, TestDeadline, TestUsageSummary, TestNewPanelKeyPresence,
# TestAggregatorDeterminism extension)
# ---------------------------------------------------------------------------

# Helper: write a ticket.json with both created_at and updated_at
def write_ticket_json_full(ws, tid, created_at, updated_at=None, archived=False):
    """Write <partition>/ticket.json carrying created_at and optional updated_at."""
    tdir = _ticket_dir(ws, tid, archived)
    data = {"id": tid, "created_at": created_at}
    if updated_at is not None:
        data["updated_at"] = updated_at
    _write_json(os.path.join(tdir, "ticket.json"), data)


class TestDeliverySummary(unittest.TestCase):
    """MAR-14 spec 01 §Test plan: delivery_summary (5 KPI panel)."""

    def test_happy_path_all_five_kpis(self):
        """5 KPIs populated: tickets_done_over_total, prs_merged, avg_lead, avg_cycle, coverage_pass_rate."""
        with TemporaryDirectory() as ws:
            write_index(ws, {
                "T1": {"status": "done", "type": "story"},
                "T2": {"status": "done", "type": "story"},
                "T3": {"status": "in_progress", "type": "story"},
            })
            write_metrics(ws, {
                "prs": {"created": 3, "merged": 2},
                "totals": {"runs": 5, "working_seconds": 3600, "cost_usd": 5.0,
                           "tokens": {"input": 1000, "output": 200}},
            })
            # T1 and T2 are done with merge-pr timestamps
            merge_ended_t1 = "2026-06-10T12:00:00Z"
            merge_ended_t2 = "2026-06-11T12:00:00Z"
            write_ticket_json(ws, "T1", "2026-06-01T10:00:00Z")
            write_pipeline(ws, "T1", steps={
                "code": {"started_at": "2026-06-05T10:00:00Z", "status": "completed",
                         "ended_at": "2026-06-05T11:00:00Z"},
                "merge-pr": {"started_at": "2026-06-10T11:00:00Z", "status": "completed",
                             "ended_at": merge_ended_t1},
            })
            write_ticket_json(ws, "T2", "2026-06-02T10:00:00Z")
            write_pipeline(ws, "T2", steps={
                "code": {"started_at": "2026-06-06T10:00:00Z", "status": "completed",
                         "ended_at": "2026-06-06T11:00:00Z"},
                "merge-pr": {"started_at": "2026-06-11T11:00:00Z", "status": "completed",
                             "ended_at": merge_ended_t2},
            })
            write_pipeline(ws, "T3", steps={
                "code": {"started_at": "2026-06-12T10:00:00Z", "status": "in_progress",
                         "ended_at": None},
            })
            # coverage: T1 passes, T2 passes, T3 no data
            write_code_state(ws, "T1", {"tests": {"coverage_percent": 91.0, "coverage_target": 90},
                                        "verifier_passed": True})
            write_code_state(ws, "T2", {"tests": {"coverage_percent": 92.0, "coverage_target": 90},
                                        "verifier_passed": True})
            # T3 code-state missing -> will degrade for p4 but not delivery_summary pass rate

            out = metrics_aggregate.aggregate(ws, REPO_ID)
            ds = out["panels"]["delivery_summary"]
            self.assertEqual(ds["tickets_done_over_total"], "2/3")
            self.assertEqual(ds["prs_merged"], 2)
            self.assertIsInstance(ds["avg_lead_seconds"], float)
            self.assertGreater(ds["avg_lead_seconds"], 0)
            self.assertIsInstance(ds["avg_cycle_seconds"], float)
            self.assertGreater(ds["avg_cycle_seconds"], 0)
            # coverage: T1 passes True, T2 passes True, T3 "no data" -> measured=2, passed=2
            self.assertEqual(ds["coverage_pass_rate"], "2/2")

    def test_no_data_averages_no_merge_pr(self):
        """No merge-pr step -> avg_lead_seconds and avg_cycle_seconds are 'no data'."""
        with TemporaryDirectory() as ws:
            write_index(ws, {"T1": {"status": "in_progress", "type": "story"}})
            write_pipeline(ws, "T1", steps={
                "code": {"started_at": "2026-06-05T10:00:00Z", "status": "in_progress",
                         "ended_at": None},
            })
            write_ticket_json(ws, "T1", "2026-06-01T10:00:00Z")
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            ds = out["panels"]["delivery_summary"]
            self.assertEqual(ds["avg_lead_seconds"], "no data")
            self.assertEqual(ds["avg_cycle_seconds"], "no data")

    def test_no_coverage_data_measured_zero_degrades(self):
        """No coverage rows (measured == 0) -> coverage_pass_rate == 'no data' + meta.degraded."""
        with TemporaryDirectory() as ws:
            write_index(ws, {"T1": {"status": "done", "type": "story"}})
            write_pipeline(ws, "T1", steps={
                "merge-pr": {"started_at": "2026-06-10T11:00:00Z", "status": "completed",
                             "ended_at": "2026-06-10T12:00:00Z"},
            })
            write_ticket_json(ws, "T1", "2026-06-01T10:00:00Z")
            # No code-state.json -> p4_row will have cell="no data" -> measured == 0
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            ds = out["panels"]["delivery_summary"]
            self.assertEqual(ds["coverage_pass_rate"], "no data")
            self.assertTrue(any(
                d["ticket_id"] is None and d["panel"] == "delivery_summary"
                for d in out["meta"]["degraded"]
            ))

    def test_empty_workspace_delivery_summary_no_data(self):
        """Empty workspace early-return path -> panels['delivery_summary'] == 'no data'."""
        with TemporaryDirectory() as ws:
            write_index(ws, {})
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            self.assertEqual(out["panels"]["delivery_summary"], "no data")

    def test_prs_merged_absent_metrics_json_missing(self):
        """metrics.json missing -> prs_merged == 0."""
        with TemporaryDirectory() as ws:
            write_index(ws, {"T1": {"status": "done", "type": "story"}})
            write_ticket_json(ws, "T1", "2026-06-01T10:00:00Z")
            write_pipeline(ws, "T1", steps={
                "merge-pr": {"started_at": "2026-06-10T11:00:00Z", "status": "completed",
                             "ended_at": "2026-06-10T12:00:00Z"},
            })
            # No metrics.json on disk
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            ds = out["panels"]["delivery_summary"]
            self.assertEqual(ds["prs_merged"], 0)

    def test_coverage_pass_rate_format_passed_over_measured(self):
        """coverage_pass_rate string is '<passed>/<measured>' with correct counts."""
        with TemporaryDirectory() as ws:
            # T1: passes, T2: fails (verifier_passed=False), T3: no data
            write_index(ws, {
                "T1": {"status": "done", "type": "story"},
                "T2": {"status": "done", "type": "story"},
                "T3": {"status": "in_progress", "type": "story"},
            })
            write_ticket_json(ws, "T1", "2026-06-01T10:00:00Z")
            write_code_state(ws, "T1", {"tests": {"coverage_percent": 91.0, "coverage_target": 90},
                                        "verifier_passed": True})
            write_ticket_json(ws, "T2", "2026-06-02T10:00:00Z")
            write_code_state(ws, "T2", {"tests": {"coverage_percent": 85.0, "coverage_target": 90},
                                        "verifier_passed": False})
            write_ticket_json(ws, "T3", "2026-06-03T10:00:00Z")
            # T3: no code-state -> p4_row cell="no data" -> not counted in measured
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            ds = out["panels"]["delivery_summary"]
            # measured=2 (T1 and T2 have numeric coverage), passed=1 (T1 passes)
            self.assertEqual(ds["coverage_pass_rate"], "1/2")


class TestIssues(unittest.TestCase):
    """MAR-14 spec 01 §Test plan: issues panel."""

    def test_populated_list_field_by_field(self):
        """Populated list with external variants: external_key from dict, None from None, None from {}."""
        with TemporaryDirectory() as ws:
            write_index(ws, {
                "MAR-1": {"status": "done", "type": "story", "title": "First story",
                          "external": {"provider": "github", "key": "42"}},
                "MAR-2": {"status": "in_progress", "type": "task", "title": "Second task",
                          "external": None},
                "MAR-3": {"status": "open", "type": "epic", "title": "Epic one",
                          "external": {}},
            })
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            issues = out["panels"]["issues"]
            self.assertIsInstance(issues, list)
            self.assertEqual(len(issues), 3)
            # Sorted ascending by id (string sort)
            ids = [i["id"] for i in issues]
            self.assertEqual(ids, sorted(ids))
            # external_key extraction
            i1 = next(i for i in issues if i["id"] == "MAR-1")
            self.assertEqual(i1["external_key"], "42")
            i2 = next(i for i in issues if i["id"] == "MAR-2")
            self.assertIsNone(i2["external_key"])
            i3 = next(i for i in issues if i["id"] == "MAR-3")
            self.assertIsNone(i3["external_key"])
            # Exact keys
            for item in issues:
                self.assertEqual(set(item.keys()), {"id", "title", "status", "type", "external_key"})

    def test_empty_index_issues_empty_list(self):
        """Empty index -> issues == []."""
        with TemporaryDirectory() as ws:
            write_index(ws, {})
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            self.assertEqual(out["panels"]["issues"], "no data")  # empty-workspace early-return

    def test_single_ticket_empty_issues_is_list(self):
        """Non-empty workspace with 1 ticket -> issues is a list."""
        with TemporaryDirectory() as ws:
            write_index(ws, {"MAR-1": {"status": "done", "type": "task", "title": "Task"}})
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            self.assertIsInstance(out["panels"]["issues"], list)
            self.assertEqual(len(out["panels"]["issues"]), 1)

    def test_determinism(self):
        """Same workspace yields identical issues list on two calls."""
        with TemporaryDirectory() as ws:
            write_index(ws, {
                "MAR-3": {"status": "done", "type": "story"},
                "MAR-1": {"status": "open", "type": "task"},
                "MAR-2": {"status": "in_progress", "type": "epic"},
            })
            out1 = metrics_aggregate.aggregate(ws, REPO_ID)
            out2 = metrics_aggregate.aggregate(ws, REPO_ID)
            self.assertEqual(out1["panels"]["issues"], out2["panels"]["issues"])


class TestProgress(unittest.TestCase):
    """MAR-14 spec 01 §Test plan: progress panel."""

    def test_overall_counts(self):
        """overall.done and overall.total count correctly."""
        with TemporaryDirectory() as ws:
            write_index(ws, {
                "T1": {"status": "done", "type": "story"},
                "T2": {"status": "done", "type": "story"},
                "T3": {"status": "done", "type": "story"},
                "T4": {"status": "in_progress", "type": "story"},
                "T5": {"status": "open", "type": "story"},
            })
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            self.assertEqual(out["panels"]["progress"]["overall"], {"done": 3, "total": 5})

    def test_per_epic_populated(self):
        """per_epic with 1 epic and 3 children (2 done, 1 open)."""
        with TemporaryDirectory() as ws:
            write_index(ws, {
                "EP-1": {"status": "in_progress", "type": "epic", "title": "Epic title",
                         "children": ["S1", "S2", "S3"]},
                "S1": {"status": "done", "type": "story"},
                "S2": {"status": "done", "type": "story"},
                "S3": {"status": "in_progress", "type": "story"},
            })
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            per_epic = out["panels"]["progress"]["per_epic"]
            self.assertEqual(len(per_epic), 1)
            ep = per_epic[0]
            self.assertEqual(ep["epic_id"], "EP-1")
            self.assertEqual(ep["title"], "Epic title")
            self.assertEqual(ep["done"], 2)
            self.assertEqual(ep["total"], 3)

    def test_per_epic_sorted_ascending(self):
        """per_epic sorted ascending by epic_id."""
        with TemporaryDirectory() as ws:
            write_index(ws, {
                "EP-2": {"status": "open", "type": "epic", "title": "B", "children": []},
                "EP-1": {"status": "open", "type": "epic", "title": "A", "children": []},
            })
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            per_epic = out["panels"]["progress"]["per_epic"]
            self.assertEqual([ep["epic_id"] for ep in per_epic], ["EP-1", "EP-2"])

    def test_per_epic_child_not_in_index(self):
        """Child id not in index is counted in total only (not in done)."""
        with TemporaryDirectory() as ws:
            write_index(ws, {
                "EP-1": {"status": "open", "type": "epic", "title": "E",
                         "children": ["S1", "S2", "MISSING"]},
                "S1": {"status": "done", "type": "story"},
                "S2": {"status": "in_progress", "type": "story"},
            })
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            ep = out["panels"]["progress"]["per_epic"][0]
            self.assertEqual(ep["done"], 1)
            self.assertEqual(ep["total"], 3)

    def test_no_epics_per_epic_empty(self):
        """No epics in workspace -> per_epic == []."""
        with TemporaryDirectory() as ws:
            write_index(ws, {
                "T1": {"status": "done", "type": "story"},
                "T2": {"status": "open", "type": "task"},
            })
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            self.assertEqual(out["panels"]["progress"]["per_epic"], [])

    def test_burn_up_populated_series(self):
        """burn_up: 2 done tickets with merge-pr.ended_at -> sorted date series, monotonic cumulative."""
        with TemporaryDirectory() as ws:
            write_index(ws, {
                "T1": {"status": "done", "type": "story"},
                "T2": {"status": "done", "type": "story"},
                "T3": {"status": "in_progress", "type": "story"},
            })
            write_ticket_json(ws, "T1", "2026-06-01T10:00:00Z")
            write_pipeline(ws, "T1", steps={
                "merge-pr": {"started_at": "2026-06-10T11:00:00Z", "status": "completed",
                             "ended_at": "2026-06-10T12:00:00Z"},
            })
            write_ticket_json(ws, "T2", "2026-06-02T10:00:00Z")
            write_pipeline(ws, "T2", steps={
                "merge-pr": {"started_at": "2026-06-11T11:00:00Z", "status": "completed",
                             "ended_at": "2026-06-11T12:00:00Z"},
            })
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            burn = out["panels"]["progress"]["burn_up"]
            self.assertIsInstance(burn, list)
            self.assertGreater(len(burn), 0)
            dates = [pt["date"] for pt in burn]
            self.assertEqual(dates, sorted(dates))
            cumulatives = [pt["completed_cumulative"] for pt in burn]
            self.assertEqual(cumulatives, sorted(cumulatives))
            for pt in burn:
                self.assertEqual(pt["total"], 3)
            # Determinism
            out2 = metrics_aggregate.aggregate(ws, REPO_ID)
            self.assertEqual(out["panels"]["progress"]["burn_up"],
                             out2["panels"]["progress"]["burn_up"])

    def test_burn_up_fallback_to_updated_at(self):
        """Done ticket with no merge-pr but with ticket.json.updated_at -> point emitted."""
        with TemporaryDirectory() as ws:
            write_index(ws, {"T1": {"status": "done", "type": "story"}})
            write_ticket_json_full(ws, "T1", created_at="2026-06-01T10:00:00Z",
                                   updated_at="2026-06-15T09:00:00Z")
            # pipeline exists but has no merge-pr step
            write_pipeline(ws, "T1", steps={
                "code": {"started_at": "2026-06-05T10:00:00Z", "status": "completed",
                         "ended_at": "2026-06-05T11:00:00Z"},
            })
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            burn = out["panels"]["progress"]["burn_up"]
            self.assertIsInstance(burn, list)
            self.assertEqual(len(burn), 1)
            self.assertEqual(burn[0]["date"], "2026-06-15")
            self.assertEqual(burn[0]["completed_cumulative"], 1)

    def test_burn_up_no_data_done_ticket_no_timestamps(self):
        """Done ticket with no merge-pr and no readable ticket.json -> burn_up == 'no data' + meta.degraded."""
        with TemporaryDirectory() as ws:
            write_index(ws, {"T1": {"status": "done", "type": "story"}})
            # No ticket.json, no pipeline-state.json -> no timestamps recoverable
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            burn = out["panels"]["progress"]["burn_up"]
            self.assertEqual(burn, "no data")
            self.assertTrue(any(
                d["ticket_id"] is None and d["panel"] == "progress"
                for d in out["meta"]["degraded"]
            ))

    def test_burn_up_empty_no_done_tickets(self):
        """All tickets open -> burn_up == [] (empty series, valid)."""
        with TemporaryDirectory() as ws:
            write_index(ws, {
                "T1": {"status": "in_progress", "type": "story"},
                "T2": {"status": "open", "type": "story"},
            })
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            self.assertEqual(out["panels"]["progress"]["burn_up"], [])

    def test_burn_up_same_date_multiple_tickets(self):
        """Two done tickets on same date -> single point with completed_cumulative == 2."""
        with TemporaryDirectory() as ws:
            write_index(ws, {
                "T1": {"status": "done", "type": "story"},
                "T2": {"status": "done", "type": "story"},
            })
            same_ended = "2026-06-10T12:00:00Z"
            write_ticket_json(ws, "T1", "2026-06-01T10:00:00Z")
            write_pipeline(ws, "T1", steps={
                "merge-pr": {"started_at": "2026-06-10T11:00:00Z", "status": "completed",
                             "ended_at": same_ended},
            })
            write_ticket_json(ws, "T2", "2026-06-02T10:00:00Z")
            write_pipeline(ws, "T2", steps={
                "merge-pr": {"started_at": "2026-06-10T11:30:00Z", "status": "completed",
                             "ended_at": same_ended},
            })
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            burn = out["panels"]["progress"]["burn_up"]
            self.assertIsInstance(burn, list)
            self.assertEqual(len(burn), 1)
            self.assertEqual(burn[0]["date"], "2026-06-10")
            self.assertEqual(burn[0]["completed_cumulative"], 2)
            # Deterministic
            out2 = metrics_aggregate.aggregate(ws, REPO_ID)
            self.assertEqual(burn, out2["panels"]["progress"]["burn_up"])

    def test_burn_up_done_ticket_updated_at_absent_but_ticket_json_present(self):
        """Done ticket with ticket.json but no updated_at and no merge-pr -> excluded, series empty -> no data only if all done tickets fail."""
        with TemporaryDirectory() as ws:
            # T1 done but only ticket.json has no updated_at; T2 done with updated_at
            write_index(ws, {
                "T1": {"status": "done", "type": "story"},
                "T2": {"status": "done", "type": "story"},
            })
            # T1: ticket.json with no updated_at, no pipeline merge-pr
            write_ticket_json(ws, "T1", "2026-06-01T10:00:00Z")
            # T2: ticket.json with updated_at
            write_ticket_json_full(ws, "T2", created_at="2026-06-02T10:00:00Z",
                                   updated_at="2026-06-20T09:00:00Z")
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            burn = out["panels"]["progress"]["burn_up"]
            # T2 produces a point, T1 is excluded silently
            self.assertIsInstance(burn, list)
            self.assertGreater(len(burn), 0)
            self.assertEqual(burn[-1]["completed_cumulative"], 1)


class TestDeadline(unittest.TestCase):
    """MAR-14 spec 01 §Test plan: deadline panel."""

    def test_always_not_set(self):
        """Any workspace -> deadline is 'not set' + meta.degraded."""
        with TemporaryDirectory() as ws:
            write_index(ws, {"T1": {"status": "done", "type": "story"}})
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            dl = out["panels"]["deadline"]
            self.assertEqual(dl["status"], "not set")
            self.assertIsNone(dl["due_date"])
            self.assertIsInstance(dl["message"], str)
            self.assertTrue(dl["message"])
            self.assertTrue(any(d["panel"] == "deadline" for d in out["meta"]["degraded"]))

    def test_populated_workspace_also_not_set(self):
        """Populated workspace: deadline does not vary with workspace content."""
        with TemporaryDirectory() as ws:
            write_index(ws, {
                "T1": {"status": "done", "type": "story"},
                "T2": {"status": "in_progress", "type": "task"},
            })
            write_pipeline(ws, "T1", steps={
                "merge-pr": {"started_at": "2026-06-10T11:00:00Z", "status": "completed",
                             "ended_at": "2026-06-10T12:00:00Z"},
            })
            write_ticket_json(ws, "T1", "2026-06-01T10:00:00Z")
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            dl = out["panels"]["deadline"]
            self.assertEqual(dl["status"], "not set")
            self.assertIsNone(dl["due_date"])
            self.assertTrue(any(d["panel"] == "deadline" for d in out["meta"]["degraded"]))

    def test_empty_workspace_deadline_no_data(self):
        """Empty workspace early-return path -> panels['deadline'] == 'no data'."""
        with TemporaryDirectory() as ws:
            write_index(ws, {})
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            self.assertEqual(out["panels"]["deadline"], "no data")


class TestUsageSummary(unittest.TestCase):
    """MAR-14 spec 01 §Test plan: usage_summary panel."""

    def test_happy_path_all_fields(self):
        """Full metrics.json -> all 8 keys present with expected types."""
        with TemporaryDirectory() as ws:
            write_index(ws, {
                "T1": {"status": "done", "type": "story"},
                "T2": {"status": "done", "type": "story"},
                "T3": {"status": "in_progress", "type": "story"},
            })
            write_metrics(ws, {
                "prs": {"created": 3, "merged": 3},
                "totals": {"runs": 10, "working_seconds": 7200,
                           "tokens": {"input": 50000, "output": 10000}, "cost_usd": 12.50},
            })
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            us = out["panels"]["usage_summary"]
            self.assertAlmostEqual(us["total_cost_usd"], 12.50)
            self.assertEqual(us["total_tokens_input"], 50000)
            self.assertEqual(us["total_tokens_output"], 10000)
            self.assertEqual(us["total_runs"], 10)
            self.assertEqual(us["total_working_seconds"], 7200)
            self.assertEqual(us["prs_merged"], 3)
            # averages from panel3
            self.assertIsInstance(us["avg_working_seconds_per_ticket"], float)
            self.assertIsInstance(us["avg_working_seconds_per_pr"], float)
            self.assertIsInstance(us["avg_cost_per_ticket"], float)
            self.assertIsInstance(us["avg_cost_per_pr"], float)

    def test_missing_metrics_json_zero_defaults(self):
        """No metrics.json -> integer/float totals default to 0/0.0; averages are 'no data'."""
        with TemporaryDirectory() as ws:
            write_index(ws, {"T1": {"status": "done", "type": "story"}})
            # No metrics.json
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            us = out["panels"]["usage_summary"]
            self.assertEqual(us["total_cost_usd"], 0.0)
            self.assertEqual(us["total_tokens_input"], 0)
            self.assertEqual(us["total_tokens_output"], 0)
            self.assertEqual(us["total_runs"], 0)
            self.assertEqual(us["prs_merged"], 0)
            # averages: no totals data -> "no data"
            self.assertEqual(us["avg_working_seconds_per_ticket"], "no data")
            self.assertEqual(us["avg_working_seconds_per_pr"], "no data")
            self.assertEqual(us["avg_cost_per_ticket"], "no data")
            self.assertEqual(us["avg_cost_per_pr"], "no data")

    def test_total_working_seconds_none_when_absent(self):
        """metrics.json present but totals.working_seconds absent -> total_working_seconds is None."""
        with TemporaryDirectory() as ws:
            write_index(ws, {"T1": {"status": "done", "type": "story"}})
            write_metrics(ws, {
                "prs": {"created": 1, "merged": 1},
                "totals": {"runs": 2, "cost_usd": 3.0,
                           "tokens": {"input": 100, "output": 50}},
            })
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            us = out["panels"]["usage_summary"]
            self.assertIsNone(us["total_working_seconds"])

    def test_empty_workspace_usage_summary_no_data(self):
        """Empty workspace early-return path -> panels['usage_summary'] == 'no data'."""
        with TemporaryDirectory() as ws:
            write_index(ws, {})
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            self.assertEqual(out["panels"]["usage_summary"], "no data")


class TestNewPanelKeyPresence(unittest.TestCase):
    """MAR-14 spec 01 §Test plan: key-presence (AC-1 / B1)."""

    _NEW_KEYS = ("delivery_summary", "issues", "progress", "deadline", "usage_summary")
    _OLD_KEYS = ("1", "2", "3", "4", "5", "6", "7")

    def test_all_five_new_keys_present_happy_path(self):
        """All five new string keys exist in panels alongside '1'..'7'."""
        with TemporaryDirectory() as ws:
            write_index(ws, {"T1": {"status": "done", "type": "story"}})
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            for k in self._NEW_KEYS:
                self.assertIn(k, out["panels"], "missing new key: %s" % k)

    def test_all_five_new_keys_present_empty_workspace(self):
        """Empty workspace early-return path: all five new keys present."""
        with TemporaryDirectory() as ws:
            write_index(ws, {})
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            for k in self._NEW_KEYS:
                self.assertIn(k, out["panels"], "missing new key on empty-ws: %s" % k)

    def test_existing_keys_not_renamed_or_removed(self):
        """Existing keys '1'..'7' still present after spec 01 additions."""
        with TemporaryDirectory() as ws:
            write_index(ws, {"T1": {"status": "done", "type": "story"}})
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            for k in self._OLD_KEYS:
                self.assertIn(k, out["panels"], "existing key missing: %s" % k)

    def test_empty_workspace_all_new_keys_are_no_data(self):
        """Empty workspace: all five new keys have value 'no data'."""
        with TemporaryDirectory() as ws:
            write_index(ws, {})
            out = metrics_aggregate.aggregate(ws, REPO_ID)
            for k in self._NEW_KEYS:
                self.assertEqual(out["panels"][k], "no data",
                                 "expected 'no data' for %s on empty-ws" % k)


class TestAggregatorDeterminism(unittest.TestCase):
    """MAR-14 spec 01: new panels identical across two calls (extends existing determinism coverage)."""

    _NEW_KEYS = ("delivery_summary", "issues", "progress", "deadline", "usage_summary")

    def test_new_panels_identical_across_two_calls(self):
        """Run aggregate() twice on the same workspace; new panel values are equal."""
        with TemporaryDirectory() as ws:
            write_index(ws, {
                "EP-1": {"status": "in_progress", "type": "epic", "title": "Epic",
                         "children": ["S1", "S2"]},
                "S1": {"status": "done", "type": "story"},
                "S2": {"status": "in_progress", "type": "story"},
            })
            write_metrics(ws, {
                "prs": {"created": 1, "merged": 1},
                "totals": {"runs": 3, "working_seconds": 3600, "cost_usd": 5.0,
                           "tokens": {"input": 10000, "output": 2000}},
            })
            write_ticket_json(ws, "S1", "2026-06-01T10:00:00Z")
            write_pipeline(ws, "S1", steps={
                "merge-pr": {"started_at": "2026-06-10T11:00:00Z", "status": "completed",
                             "ended_at": "2026-06-10T12:00:00Z"},
            })
            out1 = metrics_aggregate.aggregate(ws, REPO_ID)
            out2 = metrics_aggregate.aggregate(ws, REPO_ID)
            for k in self._NEW_KEYS:
                self.assertEqual(out1["panels"][k], out2["panels"][k],
                                 "non-deterministic result for panel key: %s" % k)
