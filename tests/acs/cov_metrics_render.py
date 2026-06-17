#!/usr/bin/env python3
"""Reproducible stdlib-`trace` line-coverage harness for metrics_render.py (MAR-5 spec 04).

The repo is Python 3.9+ stdlib-only (no pip; CLAUDE.md forbids it) — the pip `coverage` package
is NOT installed — so coverage is measured with the stdlib `trace` module. This harness is the
twin of tests/cov_metrics_aggregate.py: it drives the two pure renderers — render_terminal(data)
and render_html(data) — across every panel branch and BOTH degradation forms (whole-panel
"no data"; cell-level "no data"), the empty-workspace whole-payload form, the degraded summary,
plus main()'s stdin-terminal / stdin---html / self-invoke intake paths, under
trace.Trace(count=1, trace=0), then reports:

    executed executable lines / total executable lines  ->  percentage  (gate: >= 90%)

and the missed-line list (the trace .cover annotation marks each unexecuted executable line with
the `>>>>>>` marker). Run:  python3 tests/acs/cov_metrics_render.py   (exit 0 iff coverage >= GATE).

Note on measurement: the target module is imported FROM SOURCE inside the traced driver, so its
module-level statements and every `def` signature line execute under trace.Trace and are counted.

MAR-14 spec 02 extension: _drive() now also exercises render_pm_terminal/html,
render_usage_terminal/html, all five new per-panel renderers (delivery_summary, issues, progress,
deadline, usage_summary) across every branch (populated, no-data, empty-list, degraded-burn_up),
and the --view CLI flag dispatch (pm/usage/all).
"""

import importlib.util
import io
import json
import os
import re
import shutil
import sys
import tempfile
import trace

GATE = 90.0

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_TESTS_DIR))
_SCRIPTS_DIR = os.path.join(_REPO_ROOT, "plugins", "acs", "hooks", "scripts")
_TARGET = os.path.join(_SCRIPTS_DIR, "metrics_render.py")

if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

import acs_lib  # noqa: E402
import metrics_aggregate as agg  # noqa: E402
import test_metrics_aggregate as fx  # reuse the unittest fixtures' workspace synthesizers  # noqa: E402

REPO_ID = fx.REPO_ID


def _load_target_fresh():
    """Import metrics_render from source as a fresh module object (inside the tracer)."""
    sys.modules.pop("metrics_render", None)
    spec = importlib.util.spec_from_file_location("metrics_render", _TARGET)
    module = importlib.util.module_from_spec(spec)
    sys.modules["metrics_render"] = module
    spec.loader.exec_module(module)
    return module


def _full_data():
    with tempfile.TemporaryDirectory() as ws:
        fx.write_index(ws, {"MAR-6": {"status": "done", "type": "task"}})
        fx.write_metrics(ws, {
            "tickets": {"by_status": {"done": 4, "in_review": 1, "in_progress": 1},
                        "by_type": {"task": 5, "story": 1}},
            "prs": {"created": 5, "merged": 4},
            "totals": {"runs": 17, "working_seconds": 64238,
                       "tokens": {"input": 3102000, "output": 508500}, "cost_usd": 18.75}})
        fx.write_pipeline(ws, "MAR-6", steps=fx._full_funnel_steps("merge-pr"),
                          totals={"runs": 5, "working_seconds": 11922,
                                  "tokens": {"input": 1306000, "output": 237000},
                                  "cost_usd": 8.31}, archived=True)
        fx.write_code_state(ws, "MAR-6",
                            {"tests": {"coverage_percent": 93.4, "coverage_target": 90},
                             "verifier_passed": True, "review": {"iterations": 2}}, archived=True)
        fx.write_result_xml(ws, "MAR-6", "code", "plan", 1, ti=42000, to=7500, cost=0.17, archived=True)
        fx.write_result_xml(ws, "MAR-6", "code", "execute", 1, ti=480000, to=90000, cost=3.5, archived=True)
        fx.write_result_xml(ws, "MAR-6", "code", "verify", 1, ti=100000, to=20000, cost=1.0,
                            reorder=True, archived=True)
        return agg.aggregate(ws, REPO_ID)


def _empty_data():
    with tempfile.TemporaryDirectory() as ws:
        fx.write_index(ws, {})
        return agg.aggregate(ws, REPO_ID)


def _degraded_data():
    with tempfile.TemporaryDirectory() as ws:
        fx.write_index(ws, {"MAR-6": {"status": "done", "type": "task"},
                            "MAR-X": {"status": "in_progress", "type": "task"}})
        fx.write_code_state(ws, "MAR-6",
                            {"tests": {"passed": 81, "failed": 0, "coverage_percent": None,
                                       "coverage_target": "n/a (no new production code)"},
                             "verifier_passed": True}, archived=True)
        # MAR-X: no state files -> panels 2/3/4/5 degrade
        return agg.aggregate(ws, REPO_ID)


def _flow_data():
    """Populated Panel-3 averages + a Panel-7 with a numeric lead/cycle AND a 'no data' ticket."""
    with tempfile.TemporaryDirectory() as ws:
        fx.write_index(ws, {"MAR-6": {"status": "done", "type": "task"},
                            "MAR-OPEN": {"status": "in_progress", "type": "task"}})
        fx.write_metrics(ws, {"tickets": {"by_status": {"done": 1, "in_progress": 1},
                                          "by_type": {"task": 2}},
                              "prs": {"created": 2, "merged": 1},
                              "totals": {"working_seconds": 7200, "cost_usd": 6.0}})
        # MAR-6 merged -> numeric lead (10800s) and cycle (9000s).
        fx.write_ticket_json(ws, "MAR-6", "2026-06-15T10:00:00Z", archived=True)
        fx.write_pipeline(ws, "MAR-6",
                          steps=fx._lead_cycle_steps("2026-06-15T10:30:00Z", "2026-06-15T13:00:00Z"),
                          totals={"working_seconds": 3600, "cost_usd": 5.0}, archived=True)
        # MAR-OPEN unmerged -> lead AND cycle "no data".
        fx.write_ticket_json(ws, "MAR-OPEN", "2026-06-15T09:00:00Z")
        fx.write_pipeline(ws, "MAR-OPEN", steps=fx._lead_cycle_steps("2026-06-15T09:30:00Z", None))
        return agg.aggregate(ws, REPO_ID)


def _flow_nodata_data():
    """All four Panel-3 averages 'no data' (zero ticket/PR denominators) + Panel-7 'no data'."""
    with tempfile.TemporaryDirectory() as ws:
        fx.write_index(ws, {"MAR-6": {"status": "done", "type": "task"}})
        # merged == 0 and missing totals -> every average is "no data"; no merge-pr -> lead/cycle "no data".
        fx.write_metrics(ws, {"prs": {"created": 1, "merged": 0}, "totals": {}})
        fx.write_pipeline(ws, "MAR-6", steps=fx._lead_cycle_steps("2026-06-15T10:30:00Z", None),
                          archived=True)
        return agg.aggregate(ws, REPO_ID)


def _pm_full_data():
    """Aggregate with all PM panels fully populated (including burn_up, per_epic)."""
    with tempfile.TemporaryDirectory() as ws:
        fx.write_index(ws, {
            "MAR-E1": {"status": "done", "type": "epic", "title": "Epic One",
                       "children": ["MAR-T1", "MAR-T2"]},
            "MAR-T1": {"status": "done", "type": "task", "title": "Task Alpha",
                       "parent": "MAR-E1"},
            "MAR-T2": {"status": "in_progress", "type": "task", "title": "Task Beta",
                       "parent": "MAR-E1"},
        })
        fx.write_metrics(ws, {
            "tickets": {"by_status": {"done": 2, "in_progress": 1},
                        "by_type": {"epic": 1, "task": 2}},
            "prs": {"created": 2, "merged": 1},
            "totals": {"runs": 5, "working_seconds": 3600,
                       "tokens": {"input": 200000, "output": 40000}, "cost_usd": 2.0},
        })
        fx.write_ticket_json(ws, "MAR-T1", "2026-06-14T08:00:00Z", archived=True)
        fx.write_pipeline(ws, "MAR-T1",
                          steps=fx._lead_cycle_steps("2026-06-14T08:30:00Z",
                                                     "2026-06-14T10:00:00Z"),
                          totals={"runs": 3, "working_seconds": 3600,
                                  "tokens": {"input": 150000, "output": 30000},
                                  "cost_usd": 1.5}, archived=True)
        fx.write_code_state(ws, "MAR-T1",
                            {"tests": {"coverage_percent": 90.0, "coverage_target": 90},
                             "verifier_passed": True, "review": {"iterations": 2}},
                            archived=True)
        fx.write_result_xml(ws, "MAR-T1", "code", "plan", 1, ti=30000, to=6000, cost=0.3, archived=True)
        fx.write_result_xml(ws, "MAR-T1", "code", "execute", 1, ti=100000, to=20000, cost=1.0, archived=True)
        fx.write_result_xml(ws, "MAR-T1", "code", "verify", 1, ti=20000, to=4000, cost=0.2,
                            reorder=True, archived=True)
        return agg.aggregate(ws, REPO_ID)


def _drive():
    """Fresh-import the target and exercise every branch — all inside the traced call."""
    mod = _load_target_fresh()

    full = _full_data()
    empty = _empty_data()
    degraded = _degraded_data()
    flow = _flow_data()
    flow_nodata = _flow_nodata_data()

    # 1) both surfaces on the full happy path (all populated panels, all bar/table branches).
    mod.render_terminal(full)
    mod.render_html(full)

    # 2) both surfaces on the empty whole-payload form (every panel the bare "no data" string).
    mod.render_terminal(empty)
    mod.render_html(empty)

    # 3) both surfaces on the degraded/cell-"no data" mix (panel-4 cell, panel-5 "no data",
    #    pipeline-absent panels, and a populated degraded summary).
    mod.render_terminal(degraded)
    mod.render_html(degraded)

    # 3b) both surfaces on the flow payload: populated Panel-3 averages + a Panel-7 with a numeric
    #     lead/cycle ticket AND a "no data" ticket (exercises the humanizer + nodata-cell branches).
    mod.render_terminal(flow)
    mod.render_html(flow)
    # 3c) both surfaces with EVERY average + every lead/cycle "no data" (the NO_DATA cell branches).
    mod.render_terminal(flow_nodata)
    mod.render_html(flow_nodata)

    # 4) defensive non-dict / odd inputs (never-crash branches: bad top-level, bad panels/meta,
    #    panel rows that are not dicts, empty ticket lists, degraded entries that are not dicts).
    mod.render_terminal("garbage")
    mod.render_html("garbage")
    weird = {
        "panels": {
            "1": {"by_status": {}, "by_type": {}},
            "2": {"steps": {}, "prs": {}},
            # Panel 3 with a non-dict ticket row AND a non-dict `averages` (the four-NO_DATA branch).
            "3": {"tickets": ["not-a-dict"], "repo_totals": {}, "averages": "not-a-dict"},
            "4": {"tickets": ["not-a-dict"]},
            "5": {"tickets": ["not-a-dict"]},
            "6": {"planner": "x", "executor": "x", "verifier": "x"},
            # Panel 7 with a non-dict ticket row + non-list tickets fallback exercised below.
            "7": {"tickets": ["not-a-dict"], "avg_lead_seconds": "no data",
                  "avg_cycle_seconds": 9000},
        },
        "meta": {"repo_id": "r", "generated_at": "t", "ticket_count": 0,
                 "degraded": ["not-a-dict", {"ticket_id": "Z", "panel": 4, "reason": "why"}]},
    }
    mod.render_terminal(weird)
    mod.render_html(weird)
    # empty ticket-list branches (the "no data" table rows)
    empties = {"panels": {"1": "no data", "2": "no data",
                          "3": {"tickets": [], "repo_totals": {}},
                          "4": {"tickets": []}, "5": {"tickets": []},
                          "6": "no data",
                          # Panel 7 with non-list tickets -> single "no data" row branch.
                          "7": {"tickets": "not-a-list"}},
               "meta": {"degraded": None}}
    mod.render_terminal(empties)
    mod.render_html(empties)

    # 5) main() — stdin terminal (default), stdin --html, and the self-invoke (empty stdin) path.
    _run_main(mod, ["metrics_render.py"], json.dumps(full))
    _run_main(mod, ["metrics_render.py", "--html"], json.dumps(full))
    # output with no trailing newline forces the "append \n" branch:
    _run_main(mod, ["metrics_render.py"], json.dumps(empty))

    # self-invoke intake (no piped stdin): patch build_context + a TTY-like stdin with no data.
    _run_self_invoke(mod)

    # 6) the helper-level branches directly (bar peak<=0, bar with bool/non-numeric value).
    mod._bar(5, 0)
    mod._bar(True, 10)
    mod._bar("x", 10)
    mod._is_no_data("no data")
    mod._counts_items("not-a-dict")

    # 6b) _humanize_seconds directly: multi-unit, sub-minute, zero, negative, bool, non-numeric,
    #     and the NO_DATA string — so every branch of the humanizer executes.
    mod._humanize_seconds(2 * 86400 + 3 * 3600 + 4 * 60 + 5)  # "2d 3h"
    mod._humanize_seconds(3 * 3600 + 4 * 60)                  # "3h 4m"
    mod._humanize_seconds(45)                                 # "45s" (sub-minute)
    mod._humanize_seconds(0)                                  # "0s"
    mod._humanize_seconds(-30)                                # negative sign branch
    mod._humanize_seconds(True)                               # bool -> NO_DATA
    mod._humanize_seconds("x")                                # non-numeric -> NO_DATA
    mod._humanize_seconds(mod.NO_DATA)                        # the NO_DATA string -> NO_DATA
    # the Panel-3 average formatter directly: a cost cell whose value is non-numeric -> NO_DATA.
    mod._format_average("x", "cost")
    # _fmt_money directly: numeric 2dp, long-float rounding, the NO_DATA / non-numeric / bool
    # empty branch, and the custom "-" empty marker used by the per-ticket / role cost cells.
    mod._fmt_money(36.0)                       # "36.00"
    mod._fmt_money(5.142857142857143)          # "5.14" (long-float rounding)
    mod._fmt_money(0)                          # "0.00"
    mod._fmt_money(mod.NO_DATA)                # the NO_DATA string -> NO_DATA
    mod._fmt_money(None)                       # non-numeric -> NO_DATA
    mod._fmt_money(True)                       # bool -> NO_DATA
    mod._fmt_money("-", empty="-")             # custom empty marker passthrough

    # 7) the html bar helpers directly: integer-percent path, the divide-by-zero guard
    #    (panel_max <= 0), the bool/non-numeric guards, and the >100 clamp.
    mod._bar_pct(4, 4)        # 100%
    mod._bar_pct(1, 4)        # 25%
    mod._bar_pct(5, 0)        # panel_max 0 -> 0 (never divide by zero)
    mod._bar_pct(True, 10)    # bool value -> 0
    mod._bar_pct("x", 10)     # non-numeric value -> 0
    mod._bar_pct(3, True)     # bool panel_max -> 0
    mod._bar_pct(20, 10)      # clamp to 100
    mod._panel_max([1, 2, 3])
    mod._panel_max([])
    mod._panel_max(["x", True, 2])
    mod._html_bar_cell(2, 4)

    # -----------------------------------------------------------------------
    # MAR-14 spec 02 extensions — new view-entrypoint + per-panel renderer branches
    # -----------------------------------------------------------------------

    pm_full = _pm_full_data()

    # 8) render_pm_terminal / render_pm_html — fully populated aggregate.
    #    Exercises: delivery_summary populated, issues list with items, progress with
    #    per_epic rows + burn_up series, deadline "not set" frame, panels 1/2/4/5/7.
    mod.render_pm_terminal(pm_full)
    mod.render_pm_html(pm_full)

    # 9) render_pm_terminal / render_pm_html — delivery_summary = "no data" branch.
    pm_ds_nodata = json.loads(json.dumps(pm_full))
    pm_ds_nodata["panels"]["delivery_summary"] = "no data"
    mod.render_pm_terminal(pm_ds_nodata)
    mod.render_pm_html(pm_ds_nodata)

    # 10) issues = [] (empty list) branch — "no issues" placeholder path.
    pm_issues_empty = json.loads(json.dumps(pm_full))
    pm_issues_empty["panels"]["issues"] = []
    mod.render_pm_terminal(pm_issues_empty)
    mod.render_pm_html(pm_issues_empty)

    # 11) issues = "no data" branch — whole-panel nodata path.
    pm_issues_nodata = json.loads(json.dumps(pm_full))
    pm_issues_nodata["panels"]["issues"] = "no data"
    mod.render_pm_terminal(pm_issues_nodata)
    mod.render_pm_html(pm_issues_nodata)

    # 12) progress["burn_up"] = "no data" — degraded burn_up branch (B1: section still present).
    pm_burnup_nodata = json.loads(json.dumps(pm_full))
    if isinstance(pm_burnup_nodata["panels"].get("progress"), dict):
        pm_burnup_nodata["panels"]["progress"]["burn_up"] = "no data"
    else:
        pm_burnup_nodata["panels"]["progress"] = {
            "overall": {"done": 1, "total": 2},
            "per_epic": [{"epic_id": "E1", "title": "ep", "done": 1, "total": 2}],
            "burn_up": "no data",
        }
    mod.render_pm_terminal(pm_burnup_nodata)
    mod.render_pm_html(pm_burnup_nodata)

    # 13) progress["burn_up"] = [] — empty burn_up branch (no completed tickets placeholder).
    pm_burnup_empty = json.loads(json.dumps(pm_full))
    if isinstance(pm_burnup_empty["panels"].get("progress"), dict):
        pm_burnup_empty["panels"]["progress"]["burn_up"] = []
    else:
        pm_burnup_empty["panels"]["progress"] = {
            "overall": {"done": 0, "total": 2},
            "per_epic": [],
            "burn_up": [],
        }
    mod.render_pm_terminal(pm_burnup_empty)
    mod.render_pm_html(pm_burnup_empty)

    # 14) progress = "no data" — whole-panel nodata path.
    pm_prog_nodata = json.loads(json.dumps(pm_full))
    pm_prog_nodata["panels"]["progress"] = "no data"
    mod.render_pm_terminal(pm_prog_nodata)
    mod.render_pm_html(pm_prog_nodata)

    # 15) deadline = "no data" — whole-panel nodata path.
    pm_dl_nodata = json.loads(json.dumps(pm_full))
    pm_dl_nodata["panels"]["deadline"] = "no data"
    mod.render_pm_terminal(pm_dl_nodata)
    mod.render_pm_html(pm_dl_nodata)

    # 16) render_usage_terminal / render_usage_html — fully populated aggregate.
    #     Exercises usage_summary (all 10 KPIs populated), panels 3 + 6.
    us_full = json.loads(json.dumps(pm_full))
    us_full["panels"]["usage_summary"] = {
        "total_cost_usd": 2.0,
        "total_tokens_input": 200000,
        "total_tokens_output": 40000,
        "total_runs": 5,
        "total_working_seconds": 3600,
        "prs_merged": 1,
        "avg_working_seconds_per_ticket": 1200.0,
        "avg_working_seconds_per_pr": 3600.0,
        "avg_cost_per_ticket": 0.67,
        "avg_cost_per_pr": 2.0,
    }
    mod.render_usage_terminal(us_full)
    mod.render_usage_html(us_full)

    # 17) usage_summary = "no data" — whole-panel nodata path.
    us_nodata = json.loads(json.dumps(us_full))
    us_nodata["panels"]["usage_summary"] = "no data"
    mod.render_usage_terminal(us_nodata)
    mod.render_usage_html(us_nodata)

    # 18) usage_summary with total_working_seconds = None + all averages "no data" — nodata branches.
    us_none_ws = json.loads(json.dumps(us_full))
    us_none_ws["panels"]["usage_summary"]["total_working_seconds"] = None
    us_none_ws["panels"]["usage_summary"]["avg_working_seconds_per_ticket"] = "no data"
    us_none_ws["panels"]["usage_summary"]["avg_working_seconds_per_pr"] = "no data"
    us_none_ws["panels"]["usage_summary"]["avg_cost_per_ticket"] = "no data"
    us_none_ws["panels"]["usage_summary"]["avg_cost_per_pr"] = "no data"
    mod.render_usage_terminal(us_none_ws)
    mod.render_usage_html(us_none_ws)

    # 19) --view flag dispatch via main() — exercises all three view dispatch branches.
    _run_main(mod, ["metrics_render.py", "--view", "pm"], json.dumps(pm_full))
    _run_main(mod, ["metrics_render.py", "--view", "usage"], json.dumps(us_full))
    _run_main(mod, ["metrics_render.py", "--view", "all"], json.dumps(full))
    # HTML variants
    _run_main(mod, ["metrics_render.py", "--view", "pm", "--html"], json.dumps(pm_full))
    _run_main(mod, ["metrics_render.py", "--view", "usage", "--html"], json.dumps(us_full))
    _run_main(mod, ["metrics_render.py", "--view", "all", "--html"], json.dumps(full))

    # 20) delivery_summary with avg_lead/cycle_seconds as numeric floats — humanizer branches.
    pm_lead_cycle = json.loads(json.dumps(pm_full))
    if isinstance(pm_lead_cycle["panels"].get("delivery_summary"), dict):
        pm_lead_cycle["panels"]["delivery_summary"]["avg_lead_seconds"] = 3723.0
        pm_lead_cycle["panels"]["delivery_summary"]["avg_cycle_seconds"] = 3600.0
    else:
        pm_lead_cycle["panels"]["delivery_summary"] = {
            "tickets_done_over_total": "1/1",
            "prs_merged": 1,
            "avg_lead_seconds": 3723.0,
            "avg_cycle_seconds": 3600.0,
            "coverage_pass_rate": "1/1",
        }
    mod.render_pm_terminal(pm_lead_cycle)
    mod.render_pm_html(pm_lead_cycle)

    # 21) issues list with a non-dict entry inside (the "continue" guard branch).
    pm_issues_weird = json.loads(json.dumps(pm_full))
    pm_issues_weird["panels"]["issues"] = [
        "not-a-dict",
        {"id": "T-1", "title": "ok", "status": "open", "type": "task", "external_key": None},
        {"id": "T-2", "title": "ext", "status": "done", "type": "task", "external_key": "J-42"},
    ]
    mod.render_pm_terminal(pm_issues_weird)
    mod.render_pm_html(pm_issues_weird)

    # 22) progress with per_epic non-dict entry inside (the "continue" guard in per_epic loop).
    pm_prog_weird = json.loads(json.dumps(pm_full))
    pm_prog_weird["panels"]["progress"] = {
        "overall": {"done": 1, "total": 2},
        "per_epic": ["not-a-dict", {"epic_id": "E1", "title": "ep", "done": 1, "total": 2}],
        "burn_up": [
            "not-a-dict",
            {"date": "2026-06-01", "completed_cumulative": 1, "total": 2},
        ],
    }
    mod.render_pm_terminal(pm_prog_weird)
    mod.render_pm_html(pm_prog_weird)


class _NonTtyIO(io.StringIO):
    def isatty(self):
        return False


class _TtyEmpty(io.StringIO):
    def isatty(self):
        return True


def _run_main(mod, argv, stdin_text):
    orig_argv, orig_stdin, orig_stdout = sys.argv, sys.stdin, sys.stdout
    sys.argv = argv
    sys.stdin = _NonTtyIO(stdin_text)
    sys.stdout = io.StringIO()
    try:
        mod.main()
    finally:
        sys.argv, sys.stdin, sys.stdout = orig_argv, orig_stdin, orig_stdout


def _run_self_invoke(mod):
    """Drive _load_payload's self-invoke fallback: stdin is a TTY with no data -> aggregate()."""
    with tempfile.TemporaryDirectory() as ws:
        fx.write_index(ws, {})
        orig_argv, orig_stdin, orig_stdout = sys.argv, sys.stdin, sys.stdout
        orig_ctx = acs_lib.build_context
        sys.argv = ["metrics_render.py"]
        sys.stdin = _TtyEmpty("")
        sys.stdout = io.StringIO()
        acs_lib.build_context = lambda cwd: {"workspace": ws, "repo_id": REPO_ID}
        try:
            mod.main()
        finally:
            sys.argv, sys.stdin, sys.stdout = orig_argv, orig_stdin, orig_stdout
            acs_lib.build_context = orig_ctx


def _count_from_cover(cover_path):
    """Parse a trace .cover file: count executed/total executable lines and collect misses."""
    executed = 0
    total = 0
    missed = []
    line_no = 0
    with open(cover_path, "r", encoding="utf-8") as fh:
        for raw in fh:
            line_no += 1
            if raw.startswith(">>>>>>"):
                total += 1
                missed.append((line_no, raw[6:].rstrip("\n")))
            else:
                m = re.match(r"\s*(\d+):", raw)
                if m:
                    total += 1
                    executed += 1
    return executed, total, missed


def main():
    covdir = tempfile.mkdtemp(prefix="acs-cov-render-")
    try:
        tracer = trace.Trace(count=1, trace=0)
        devnull = open(os.devnull, "w")
        real_stdout = sys.stdout
        sys.stdout = devnull
        try:
            tracer.runfunc(_drive)
        finally:
            sys.stdout = real_stdout
            devnull.close()
        results = tracer.results()
        results.write_results(summary=False, coverdir=covdir)

        cover_file = None
        for name in os.listdir(covdir):
            if name.endswith(".cover") and "metrics_render" in name:
                cover_file = os.path.join(covdir, name)
                break
        if cover_file is None:
            print("ERROR: no metrics_render .cover produced in %s" % covdir)
            return 2

        executed, total, missed = _count_from_cover(cover_file)
        pct = (executed * 100.0 / total) if total else 0.0
        print("metrics_render.py coverage: %d/%d executable lines = %.1f%% (gate %.0f%%)"
              % (executed, total, pct, GATE))
        if missed:
            print("missed lines (>>>>>> in trace .cover):")
            for ln, src in missed:
                print("  L%d: %s" % (ln, src.strip()))
        else:
            print("missed lines: none")
        result = {"executed": executed, "total": total, "percent": round(pct, 1),
                  "gate": GATE, "passed": pct >= GATE,
                  "missed": [ln for ln, _ in missed]}
        print(json.dumps(result))
        return 0 if pct >= GATE else 1
    finally:
        shutil.rmtree(covdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
