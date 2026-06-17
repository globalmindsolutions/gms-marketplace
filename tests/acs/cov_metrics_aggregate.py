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
_REPO_ROOT = os.path.dirname(os.path.dirname(_TESTS_DIR))
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

    # 6b) panel-3 averages + panel-7 lead/cycle new branches:
    #     - averages happy path + prs.merged == 0 divide-by-zero + non-numeric totals,
    #     - lead/cycle happy path (both values), missing-code-step (cycle "no data"),
    #       missing-created_at (lead "no data"), open-ticket (no merge-pr.ended_at),
    #     - empty-subset averages ("no data") via the open-only workspace.
    def _lc_steps(code_started, merge_ended):
        return {
            "code": {"started_at": code_started, "status": "completed",
                     "ended_at": "2026-06-15T11:00:00Z"},
            "merge-pr": {"started_at": "2026-06-15T12:00:00Z", "status": "completed",
                         "ended_at": merge_ended},
        }

    # populated, prs.merged == 0 -> per-PR averages "no data"; per-ticket averages compute;
    # FULL has both lead+cycle, NOCODE has lead only (cycle "no data" -> drives L291).
    with tempfile.TemporaryDirectory() as ws:
        fx.write_index(ws, {"FULL": {"status": "done", "type": "task"},
                            "NOCODE": {"status": "done", "type": "task"}})
        fx.write_metrics(ws, {"prs": {"created": 2, "merged": 0},
                              "totals": {"working_seconds": 1200, "cost_usd": 4.0}})
        fx.write_ticket_json(ws, "FULL", "2026-06-15T10:00:00Z")
        fx.write_pipeline(ws, "FULL", steps=_lc_steps("2026-06-15T10:30:00Z", "2026-06-15T13:00:00Z"))
        fx.write_ticket_json(ws, "NOCODE", "2026-06-15T09:00:00Z")
        fx.write_pipeline(ws, "NOCODE", steps=_lc_steps(None, "2026-06-15T13:00:00Z"))
        mod.aggregate(ws, REPO_ID)

    # non-numeric totals -> averages "no data" (numerator guard); missing-created_at lead path.
    with tempfile.TemporaryDirectory() as ws:
        fx.write_index(ws, {"NOCREATED": {"status": "done", "type": "task"}})
        fx.write_metrics(ws, {"prs": {"created": 1, "merged": 1}, "totals": {"working_seconds": None}})
        # no ticket.json -> created_at absent -> lead "no data"; cycle computes
        fx.write_pipeline(ws, "NOCREATED",
                          steps=_lc_steps("2026-06-15T10:30:00Z", "2026-06-15T13:00:00Z"))
        mod.aggregate(ws, REPO_ID)

    # open-only workspace -> both lead/cycle "no data" + empty-subset averages "no data".
    with tempfile.TemporaryDirectory() as ws:
        fx.write_index(ws, {"OPEN": {"status": "in_progress", "type": "task"}})
        fx.write_ticket_json(ws, "OPEN", "2026-06-15T10:00:00Z")
        fx.write_pipeline(ws, "OPEN", steps=_lc_steps("2026-06-15T10:30:00Z", None))
        mod.aggregate(ws, REPO_ID)

    # also drive the helpers' guard branches directly.
    mod._safe_avg(10, 0)            # zero denominator
    mod._safe_avg(None, 2)          # non-numeric numerator
    mod._safe_avg(10, True)         # bool denominator treated non-numeric
    mod._elapsed_seconds(None, None)  # both anchors missing -> None

    # 6c) Spec 02 new branches — cycle-inversion + _rework_count present/absent/malformed.
    #
    # Cycle-inversion: exercises the `not (end >= start)` branch in _elapsed_seconds for the
    # CYCLE computation specifically (code.started_at AFTER merge-pr.ended_at).  The lead path
    # through the same branch is already traced via the negative-interval fixture above.
    with tempfile.TemporaryDirectory() as ws:
        fx.write_index(ws, {"INV": {"status": "done", "type": "task"}})
        fx.write_ticket_json(ws, "INV", "2025-01-01T00:00:00Z")
        fx.write_pipeline(ws, "INV", steps={
            "code": {"started_at": "2025-06-01T12:00:00Z", "status": "completed",
                     "ended_at": "2025-06-01T13:00:00Z"},
            "merge-pr": {"started_at": "2025-04-30T00:00:00Z", "status": "completed",
                         "ended_at": "2025-05-01T00:00:00Z"},
        })
        mod.aggregate(ws, REPO_ID)

    # _rework_count — ticket WITH create-pr-state.json (states.pr.number + runs[].pr.number)
    with tempfile.TemporaryDirectory() as ws:
        fx.write_index(ws, {"RC1": {"status": "done", "type": "task"}})
        fx.write_ticket_json(ws, "RC1", "2025-01-01T00:00:00Z")
        fx.write_pipeline(ws, "RC1", steps=_lc_steps("2025-02-01T10:00:00Z", "2025-03-01T10:00:00Z"))
        tdir_rc1 = fx._ticket_dir(ws, "RC1")
        fx._write_json(os.path.join(tdir_rc1, "create-pr-state.json"), {
            "skill": "create-pr",
            "ticket_id": "RC1",
            "states": {"pr": {"number": 42}},
            "runs": [{"pr": {"number": 42}}, {"pr": {"number": 43}}],
        })
        mod.aggregate(ws, REPO_ID)

    # _rework_count — ticket WITHOUT create-pr-state.json (absent file -> OSError branch -> 0)
    with tempfile.TemporaryDirectory() as ws:
        fx.write_index(ws, {"RC2": {"status": "done", "type": "task"}})
        fx.write_ticket_json(ws, "RC2", "2025-01-01T00:00:00Z")
        fx.write_pipeline(ws, "RC2", steps=_lc_steps("2025-02-01T10:00:00Z", "2025-03-01T10:00:00Z"))
        # no create-pr-state.json -> OSError branch -> rework_count == 0
        mod.aggregate(ws, REPO_ID)

    # _rework_count — malformed JSON (JSONDecodeError branch -> 0)
    with tempfile.TemporaryDirectory() as ws:
        fx.write_index(ws, {"RC3": {"status": "done", "type": "task"}})
        fx.write_ticket_json(ws, "RC3", "2025-01-01T00:00:00Z")
        fx.write_pipeline(ws, "RC3", steps=_lc_steps("2025-02-01T10:00:00Z", "2025-03-01T10:00:00Z"))
        tdir_rc3 = fx._ticket_dir(ws, "RC3")
        fx._write_text(os.path.join(tdir_rc3, "create-pr-state.json"), "not valid json {{{{")
        mod.aggregate(ws, REPO_ID)

    # _rework_count — states.pr.number is None (excluded from the set -> rework_count == 0)
    with tempfile.TemporaryDirectory() as ws:
        fx.write_index(ws, {"RC4": {"status": "done", "type": "task"}})
        fx.write_ticket_json(ws, "RC4", "2025-01-01T00:00:00Z")
        fx.write_pipeline(ws, "RC4", steps=_lc_steps("2025-02-01T10:00:00Z", "2025-03-01T10:00:00Z"))
        fx.write_create_pr_state(ws, "RC4", states={"pr": {"number": None}})
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

    # --- MAR-14 spec 01: new panel branch coverage ---

    # 8a) delivery_summary: happy path (coverage_pass_rate "<passed>/<measured>") and
    #     prs_merged bool -> 0 branch (L294); also drives L304 (row.cell != "no data" continue).
    with tempfile.TemporaryDirectory() as ws:
        fx.write_index(ws, {
            "DS1": {"status": "done", "type": "story"},
            "DS2": {"status": "in_progress", "type": "story"},
        })
        fx.write_metrics(ws, {
            "prs": {"created": 2, "merged": True},  # bool merged -> prs_merged = 0 branch
            "totals": {"runs": 5, "working_seconds": 3600, "cost_usd": 5.0,
                       "tokens": {"input": 1000, "output": 200}},
        })
        fx.write_ticket_json(ws, "DS1", "2026-06-01T10:00:00Z")
        fx.write_pipeline(ws, "DS1", steps={
            "code": {"started_at": "2026-06-05T10:00:00Z", "status": "completed",
                     "ended_at": "2026-06-05T11:00:00Z"},
            "merge-pr": {"started_at": "2026-06-10T11:00:00Z", "status": "completed",
                         "ended_at": "2026-06-10T12:00:00Z"},
        })
        # DS1 has numeric coverage (cell != "no data") + passed=True -> measured=1, passed=1
        fx.write_code_state(ws, "DS1", {"tests": {"coverage_percent": 91.0, "coverage_target": 90},
                                        "verifier_passed": True})
        mod.aggregate(ws, REPO_ID)

    # 8b) delivery_summary: coverage_pass_rate "no data" + meta.degraded (measured == 0).
    #     All p4_rows have cell == "no data" -> the continue branch + degrade.
    with tempfile.TemporaryDirectory() as ws:
        fx.write_index(ws, {"DS3": {"status": "done", "type": "story"}})
        fx.write_ticket_json(ws, "DS3", "2026-06-01T10:00:00Z")
        # No code-state -> p4_row has cell="no data" -> measured=0 -> "no data" + degrade
        mod.aggregate(ws, REPO_ID)

    # 8c) issues: external_key extraction from external["key"] (present); entry-not-a-dict path.
    with tempfile.TemporaryDirectory() as ws:
        fx.write_index(ws, {
            "ISS1": {"status": "done", "type": "story", "title": "A",
                     "external": {"provider": "github", "key": "99"}},
            "ISS2": "not-a-dict",  # not a dict -> entry = {} branch
        })
        mod.aggregate(ws, REPO_ID)

    # 8d) progress: per_epic branch with children (epic_id loop, child_done, per_epic.append)
    #     + burn_up fallback to ticket.json.updated_at when no merge-pr.ended_at.
    with tempfile.TemporaryDirectory() as ws:
        fx.write_index(ws, {
            "EP1": {"status": "open", "type": "epic", "title": "Big Epic",
                    "children": ["CH1", "CH2", "MISSING_KID"]},
            "CH1": {"status": "done", "type": "story"},
            "CH2": {"status": "in_progress", "type": "story"},
            # MISSING_KID not in index -> counted in total only
        })
        # CH1 done with no merge-pr but ticket.json has updated_at -> burn_up fallback branch
        fx.write_ticket_json_full(ws, "CH1",
                                  created_at="2026-06-01T10:00:00Z",
                                  updated_at="2026-06-15T09:00:00Z")
        mod.aggregate(ws, REPO_ID)

    # 8e) progress: burn_up "no data" branch (done ticket exists but no timestamps recoverable).
    with tempfile.TemporaryDirectory() as ws:
        fx.write_index(ws, {"BU1": {"status": "done", "type": "story"}})
        # No ticket.json, no pipeline-state.json -> no timestamps -> burn_up "no data" + degrade
        mod.aggregate(ws, REPO_ID)

    # 8f) progress: burn_up [] branch (no done tickets; empty series).
    with tempfile.TemporaryDirectory() as ws:
        fx.write_index(ws, {"OP1": {"status": "in_progress", "type": "story"}})
        mod.aggregate(ws, REPO_ID)

    # 8g) deadline: always-degraded path exercises _deadline_panel body.
    with tempfile.TemporaryDirectory() as ws:
        fx.write_index(ws, {"DL1": {"status": "done", "type": "story"}})
        mod.aggregate(ws, REPO_ID)

    # 8h) usage_summary: non-numeric/bool branches for total_cost_usd, tokens, runs, prs_merged.
    with tempfile.TemporaryDirectory() as ws:
        fx.write_index(ws, {"US1": {"status": "done", "type": "story"}})
        fx.write_metrics(ws, {
            "prs": {"created": 1, "merged": True},  # bool -> prs_merged = 0 branch
            "totals": {
                "runs": "bad",        # non-int -> total_runs = 0 branch
                "cost_usd": "bad",    # non-numeric -> total_cost_usd = 0.0 branch
                "tokens": {
                    "input": True,    # bool int -> total_tokens_input = 0 branch
                    "output": True,   # bool int -> total_tokens_output = 0 branch
                },
            },
        })
        mod.aggregate(ws, REPO_ID)

    # 8i) usage_summary: no metrics.json -> zero defaults + "no data" averages.
    with tempfile.TemporaryDirectory() as ws:
        fx.write_index(ws, {"US2": {"status": "done", "type": "story"}})
        # No metrics.json -> prs default, totals empty
        mod.aggregate(ws, REPO_ID)

    # 8j) Direct helper invocations for hard-to-reach branches:
    #     L304 (row not a dict in _delivery_summary), L539 (_accumulate_funnel steps not a dict),
    #     L609 (_rework_count data not a dict), L618/619 and L629/630 (KeyError/TypeError handlers).

    # L304: p4_rows entry that is not a dict (call _delivery_summary directly)
    _dummy_degrade = lambda tid, panel, reason: None
    _dummy_p7 = {"avg_lead_seconds": "no data", "avg_cycle_seconds": "no data"}
    mod._delivery_summary({"T1": {"status": "done"}}, {}, _dummy_p7, ["not-a-dict"], _dummy_degrade)

    # L539: _accumulate_funnel with steps not a dict (call directly with non-dict steps)
    mod._accumulate_funnel({}, {"steps": ["not", "a", "dict"]})

    # L609: _rework_count with file containing JSON null (data is None, not a dict -> return 0)
    with tempfile.TemporaryDirectory() as _td:
        _sp = os.path.join(_td, "create-pr-state.json")
        fx._write_text(_sp, "null")
        mod._rework_count(_td)

    # L618/619: states.pr key missing (KeyError in try block for states.pr.number)
    # L629/630: run has no "pr" key (KeyError in try block for run["pr"]["number"])
    with tempfile.TemporaryDirectory() as _td:
        _sp = os.path.join(_td, "create-pr-state.json")
        fx._write_json(_sp, {"states": {}, "runs": [{"not_pr": 1}]})
        mod._rework_count(_td)


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
