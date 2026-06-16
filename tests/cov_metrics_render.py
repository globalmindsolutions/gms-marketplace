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
the `>>>>>>` marker). Run:  python3 tests/cov_metrics_render.py   (exit 0 iff coverage >= GATE).

Note on measurement: the target module is imported FROM SOURCE inside the traced driver, so its
module-level statements and every `def` signature line execute under trace.Trace and are counted.
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
_REPO_ROOT = os.path.dirname(_TESTS_DIR)
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


def _drive():
    """Fresh-import the target and exercise every branch — all inside the traced call."""
    mod = _load_target_fresh()

    full = _full_data()
    empty = _empty_data()
    degraded = _degraded_data()

    # 1) both surfaces on the full happy path (all six populated panels, all bar/table branches).
    mod.render_terminal(full)
    mod.render_html(full)

    # 2) both surfaces on the empty whole-payload form (every panel the bare "no data" string).
    mod.render_terminal(empty)
    mod.render_html(empty)

    # 3) both surfaces on the degraded/cell-"no data" mix (panel-4 cell, panel-5 "no data",
    #    pipeline-absent panels, and a populated degraded summary).
    mod.render_terminal(degraded)
    mod.render_html(degraded)

    # 4) defensive non-dict / odd inputs (never-crash branches: bad top-level, bad panels/meta,
    #    panel rows that are not dicts, empty ticket lists, degraded entries that are not dicts).
    mod.render_terminal("garbage")
    mod.render_html("garbage")
    weird = {
        "panels": {
            "1": {"by_status": {}, "by_type": {}},
            "2": {"steps": {}, "prs": {}},
            "3": {"tickets": ["not-a-dict"], "repo_totals": {}},
            "4": {"tickets": ["not-a-dict"]},
            "5": {"tickets": ["not-a-dict"]},
            "6": {"planner": "x", "executor": "x", "verifier": "x"},
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
                          "6": "no data"},
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
