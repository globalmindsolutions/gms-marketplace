#!/usr/bin/env python3
"""Reproducible stdlib-`trace` line-coverage harness for metrics_aggregate.py (MAR-5 spec 01).

The repo is Python 3.9+ stdlib-only (no pip; CLAUDE.md forbids it) — the pip `coverage` package
is NOT installed — so coverage is measured with the stdlib `trace` module. This harness drives the
pure aggregate(workspace, repo_id) function across every panel branch and BOTH degradation paths
(missing/None state file; missing phase XML), plus the empty-workspace and 50-ticket paths and the
main() smoke path, under trace.Trace(count=1, trace=0), then reports:

    executed executable lines / total executable lines  ->  percentage  (gate: >= 90%)

and the missed-line list (the trace .cover annotation marks each unexecuted executable line with
the `>>>>>>` marker). Run:  python3 tests/cov_metrics_aggregate.py   (exit 0 iff coverage >= GATE).

Note on measurement: the target module is imported FROM SOURCE inside the traced driver, so its
module-level statements and every `def` signature line execute under trace.Trace and are counted.
An import that happened before tracing started would otherwise leave the top-level body and the
signatures marked as missed (trace counts a line only when it runs during the traced call).
"""

import importlib.util
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
_TARGET = os.path.join(_SCRIPTS_DIR, "metrics_aggregate.py")

if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

import acs_lib  # noqa: E402
import test_metrics_aggregate as fx  # reuse the unittest fixtures' workspace synthesizers  # noqa: E402

REPO_ID = fx.REPO_ID


def _load_target_fresh():
    """Import metrics_aggregate from source as a fresh module object (inside the tracer)."""
    sys.modules.pop("metrics_aggregate", None)
    spec = importlib.util.spec_from_file_location("metrics_aggregate", _TARGET)
    module = importlib.util.module_from_spec(spec)
    sys.modules["metrics_aggregate"] = module
    spec.loader.exec_module(module)
    return module


def _drive():
    """Fresh-import the target and exercise every branch — all inside the traced call."""
    mod = _load_target_fresh()

    # 1) empty workspace (no index) -> all panels "no data"
    with tempfile.TemporaryDirectory() as ws:
        os.makedirs(os.path.join(ws, REPO_ID), exist_ok=True)
        mod.aggregate(ws, REPO_ID)

    # 2) empty tickets dict
    with tempfile.TemporaryDirectory() as ws:
        fx.write_index(ws, {})
        mod.aggregate(ws, REPO_ID)

    # 3) full happy path: panel-1 primary, funnel, cost/time, numeric coverage, authoritative
    #    review iterations, all three role buckets (incl. reordered attrs, coordinate excluded,
    #    a -task.xml and a no-metrics result XML).
    with tempfile.TemporaryDirectory() as ws:
        fx.write_index(ws, {"MAR-6": {"status": "done", "type": "task"}})
        fx.write_metrics(ws, {"tickets": {"by_status": {"done": 4, "in_review": 1, "in_progress": 1},
                                          "by_type": {"task": 5, "story": 1}},
                              "prs": {"created": 5, "merged": 4},
                              "totals": {"runs": 17, "working_seconds": 64238,
                                         "tokens": {"input": 3102000, "output": 508500}, "cost_usd": 18.75}})
        fx.write_pipeline(ws, "MAR-6", steps=fx._full_funnel_steps("merge-pr"),
                          totals={"runs": 5, "working_seconds": 11922,
                                  "tokens": {"input": 1306000, "output": 237000}, "cost_usd": 8.31},
                          archived=True)
        fx.write_code_state(ws, "MAR-6", {"tests": {"coverage_percent": 93.4, "coverage_target": 90},
                                          "verifier_passed": True,
                                          "review": {"iterations": 2}}, archived=True)
        fx.write_result_xml(ws, "MAR-6", "code", "plan", 1, ti=42000, to=7500, cost=0.17, archived=True)
        fx.write_result_xml(ws, "MAR-6", "code", "execute", 1, ti=480000, to=90000, cost=3.5, archived=True)
        fx.write_result_xml(ws, "MAR-6", "code", "verify", 1, ti=100000, to=20000, cost=1.0,
                            reorder=True, archived=True)
        fx.write_result_xml(ws, "MAR-6", "code", "coordinate", 1, ti=999999, to=999999, cost=99.0, archived=True)
        fx.write_task_xml(ws, "MAR-6", "code", "plan", 1, archived=True)
        fx.write_result_xml(ws, "MAR-6", "merge-pr", "plan", 1, no_metrics=True, archived=True)
        mod.aggregate(ws, REPO_ID)

    # 4) panel-1 recompute fallback (no metrics.json) + panel-5 verify-XML-max fallback +
    #    a metrics tag with only tokens-input (missing-attribute-defaults path).
    with tempfile.TemporaryDirectory() as ws:
        fx.write_index(ws, {"MAR-7": {"status": "in_review", "type": "story"}})
        fx.write_code_state(ws, "MAR-7", {"tests": {"coverage_percent": 91.0, "coverage_target": 90}})
        for it in (1, 2, 3):
            fx.write_result_xml(ws, "MAR-7", "code", "verify", it)
        tdir = fx._ticket_dir(ws, "MAR-7")
        fx._write_text(os.path.join(tdir, "phases", "code", "iter-1-plan.xml"),
                       '<result skill="code" phase="plan" ticket-id="MAR-7" iteration="1" status="completed">\n'
                       '  <metrics tokens-input="500"/>\n</result>\n')
        mod.aggregate(ws, REPO_ID)

    # 5) panel-4 null-coverage "no data" degradation + missing pipeline/code-state degradation +
    #    panel-5 absent-everything "no data" path.
    with tempfile.TemporaryDirectory() as ws:
        fx.write_index(ws, {"MAR-6": {"status": "done", "type": "task"},
                            "MAR-X": {"status": "in_progress", "type": "task"}})
        fx.write_code_state(ws, "MAR-6", {"tests": {"passed": 81, "failed": 0, "coverage_percent": None,
                                                    "coverage_target": "n/a (no new production code)"},
                                          "verifier_passed": True}, archived=True)
        # MAR-X: no state files at all -> panels 2/3/4/5 degrade (incl. panel-5 "no data" branch)
        mod.aggregate(ws, REPO_ID)

    # 6) 50-ticket perf path (drives the enumeration/walk branches at scale)
    with tempfile.TemporaryDirectory() as ws:
        tickets = {}
        for n in range(50):
            tid = "PERF-%d" % n
            tickets[tid] = {"status": "done", "type": "task"}
            fx.write_pipeline(ws, tid, steps=fx._full_funnel_steps("merge-pr"),
                              totals={"runs": 5, "working_seconds": 100,
                                      "tokens": {"input": 1, "output": 1}, "cost_usd": 1.0})
            fx.write_code_state(ws, tid, {"tests": {"coverage_percent": 90.0, "coverage_target": 90},
                                          "review": {"iterations": 2}})
            for i in range(4):
                fx.write_result_xml(ws, tid, "code", "plan", i + 1, ti=1, to=1, cost=0.1)
            for i in range(9):
                fx.write_result_xml(ws, tid, "code", "execute", i + 1, ti=1, to=1, cost=0.1)
            for i in range(9):
                fx.write_result_xml(ws, tid, "code", "verify", i + 1, ti=1, to=1, cost=0.1)
        fx.write_index(ws, tickets)
        mod.aggregate(ws, REPO_ID)

    # 7) main() smoke path (build_context patched so the harness runs without git/settings).
    with tempfile.TemporaryDirectory() as ws:
        fx.write_index(ws, {})
        orig = acs_lib.build_context
        acs_lib.build_context = lambda cwd: {"workspace": ws, "repo_id": REPO_ID}
        try:
            mod.main()
        finally:
            acs_lib.build_context = orig

    # also drive the _to_int/_to_float error branches directly (non-numeric input)
    mod._to_int("not-an-int")
    mod._to_float("not-a-float")
    # and _read_text's OSError branch (a path that cannot be opened)
    mod._read_text(os.path.join(tempfile.gettempdir(), "acs-nonexistent-dir-xyz", "missing.xml"))


def _count_from_cover(cover_path):
    """Parse a trace .cover file: count executed/total executable lines and collect misses."""
    executed = 0
    total = 0
    missed = []
    line_no = 0
    with open(cover_path, "r", encoding="utf-8") as fh:
        for raw in fh:
            line_no += 1
            # trace lines look like ">>>>>> code" (missed), "    N: code" (hit N times),
            # or "       code" (non-executable: blank/comment/continuation).
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
    covdir = tempfile.mkdtemp(prefix="acs-cov-")
    try:
        tracer = trace.Trace(count=1, trace=0)
        # Silence the empty-workspace main() print so the harness output stays clean.
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

        # Find the produced .cover for metrics_aggregate (the filename embeds the module path).
        cover_file = None
        for name in os.listdir(covdir):
            if name.endswith(".cover") and "metrics_aggregate" in name:
                cover_file = os.path.join(covdir, name)
                break
        if cover_file is None:
            print("ERROR: no metrics_aggregate .cover produced in %s" % covdir)
            return 2

        executed, total, missed = _count_from_cover(cover_file)
        pct = (executed * 100.0 / total) if total else 0.0
        print("metrics_aggregate.py coverage: %d/%d executable lines = %.1f%% (gate %.0f%%)"
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
