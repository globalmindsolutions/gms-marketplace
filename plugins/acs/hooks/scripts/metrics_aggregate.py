#!/usr/bin/env python3
"""metrics_aggregate.py — read-only six-panel dashboard aggregator for /acs:metrics (MAR-5).

Stdlib-only (Python 3.9+, no pip). Reads the current repo's workspace artifacts and prints ONE
aggregate JSON object to stdout:

    {
      "panels": {"1": {...}, "2": {...}, "3": {...}, "4": {...}, "5": {...}, "6": {...}},
      "meta": {"generated_at": "<ISO8601>", "repo_id": "...", "ticket_count": <int>,
               "degraded": [{"ticket_id": "...", "panel": <int>, "reason": "..."}, ...]}
    }

Design A1 (helper emits aggregate JSON; the SKILL renders show_widget — ZERO show_widget
dependency here), B1 (every panel key "1".."6" is ALWAYS present; degradation is a "no data"
marker inside the panel plus a meta.degraded entry, never a missing key), C1 (panel 6 token-burn
buckets plan->planner / execute->executor / verify->verifier from the <metrics> element, the
`coordinate` phase EXCLUDED from all three buckets per ledger C-5; panel 5 review iterations from
code-state states.review.iterations authoritative with the max verify-XML-iteration fallback),
D1 (bounded single pass: enumerate tickets from tickets-index.json, resolve each partition
active-then-archive, read the four state files once each, glob phases/*/iter-*-*.xml and extract
<metrics> with a compiled attribute-order-INDEPENDENT regex; xml.etree is a documented reserved
fallback, not used by default).

The helper is READ-ONLY: zero acs_lib.write_json calls; it mutates no workspace file.

Factoring (spec 01 contract): aggregate(workspace, repo_id) -> dict is a PURE function (no git,
no settings, no stdout) and is the test + coverage entry point; main() is a thin smoke path that
resolves {workspace, repo_id} via acs_lib.build_context(), calls aggregate(), and prints the JSON.
"""

import glob
import json
import os
import re
import sys

# Reuse acs_lib (shared scripts dir) the same way the other hooks/scripts do.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import acs_lib  # noqa: E402

PANEL_KEYS = ("1", "2", "3", "4", "5", "6", "7")

# phase attribute -> role bucket (panel 6). `coordinate` maps to no bucket (ledger C-5):
# the role IS the phase; we invent no `role` attribute and add no fourth bucket.
PHASE_ROLE = {"plan": "planner", "execute": "executor", "verify": "verifier"}

# Attribute-order-INDEPENDENT extraction (D1 / Risk R2): pull the <metrics ...> tag, then each
# attribute by its own sub-pattern so tag order does not matter. xml.etree is the reserved
# fallback (D2) and is intentionally not used here.
_METRICS_TAG_RE = re.compile(r"<metrics\b([^>]*?)/?>")
_TI_RE = re.compile(r'\btokens-input\s*=\s*"([^"]*)"')
_TO_RE = re.compile(r'\btokens-output\s*=\s*"([^"]*)"')
_COST_RE = re.compile(r'\bcost-usd\s*=\s*"([^"]*)"')
# the enclosing element's phase attribute (result/task both expose phase=)
_PHASE_RE = re.compile(r'\bphase\s*=\s*"([^"]*)"')
# iteration="N" on a verify result XML (panel 5 fallback)
_ITER_RE = re.compile(r'\biteration\s*=\s*"(\d+)"')


def _to_int(text):
    try:
        return int(text)
    except (TypeError, ValueError):
        return 0


def _to_float(text):
    try:
        return float(text)
    except (TypeError, ValueError):
        return 0.0


def _is_number(value):
    """True for a real int/float, never for bool (mirror the panel-4 guard, line 188)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _safe_avg(numerator, denominator):
    """Guarded division (AC-1): "no data" when either operand is non-numeric or denominator <= 0.

    Treats bool as non-numeric for both operands, so True/False never act as 1/0. The guard
    precedes the division, so ZeroDivisionError is never raised.
    """
    if not _is_number(numerator) or not _is_number(denominator) or denominator <= 0:
        return "no data"
    return numerator / denominator


def _elapsed_seconds(start_iso, end_iso):
    """Wall-clock elapsed `end - start` in whole seconds, or None (AC-2).

    Mirrors acs_lib.run_seconds but returns value-or-None (not 0), so a missing/invalid anchor
    or a negative interval is distinguishable from a true zero-length interval. Total function:
    parse_iso returns None on bad/missing input, so this never raises.

    Overlap-safe guarantee (spec 02 / design B1): an inverted interval (start > end, i.e.
    `not (end >= start)`) returns None rather than raising or returning a negative value.
    Callers (_panel7_row) map None to the string "no data" and append a meta.degraded entry;
    aggregate() writes nothing in any case. This guarantee covers both the lead-inversion case
    (merge-pr.ended_at < ticket.created_at) and the cycle-inversion case
    (code.started_at > merge-pr.ended_at, e.g. a re-cycled ticket). The production guard on
    line `end >= start` below is intentionally NOT a rewrite — it is the minimal total-function
    property (design Decision B1: "a guarantee + test, not a rewrite").
    """
    start, end = acs_lib.parse_iso(start_iso), acs_lib.parse_iso(end_iso)
    if start and end and end >= start:
        return int((end - start).total_seconds())
    return None


def aggregate(workspace, repo_id):
    """Pure aggregator: read the workspace partition for `repo_id`, return the dashboard payload.

    Never raises on missing/partial state — each absent source becomes a "no data" marker plus a
    meta.degraded entry. No git, no settings, no stdout, no writes.
    """
    degraded = []

    def degrade(ticket_id, panel, reason):
        degraded.append({"ticket_id": ticket_id, "panel": panel, "reason": reason})

    index = acs_lib.read_json(acs_lib.index_path(workspace, repo_id))
    tickets = (index or {}).get("tickets") if isinstance(index, dict) else None
    tickets = tickets if isinstance(tickets, dict) else {}

    repo_metrics = acs_lib.read_json(acs_lib.metrics_path(workspace, repo_id))
    repo_metrics = repo_metrics if isinstance(repo_metrics, dict) else None

    meta = {
        "generated_at": acs_lib.now_iso(),
        "repo_id": repo_id,
        "ticket_count": len(tickets),
        "degraded": degraded,
    }

    # Empty workspace (no tickets enumerated): every panel "no data", exit-0 path. B1 keeps all keys.
    if not tickets:
        return {"panels": {k: "no data" for k in PANEL_KEYS}, "meta": meta}

    # Panel 1 — throughput by status/type (repo metrics primary; recompute fallback from the index).
    panel1 = _panel1(tickets, repo_metrics)

    # Panels 2/3 funnel + cost/time, 4 coverage, 5 review iterations, 6 token burn — single pass.
    funnel = {skill: 0 for skill in acs_lib.HOOKED_SKILLS}
    p3_rows = []
    p4_rows = []
    p5_rows = []
    p7_rows = []
    burn = {role: {"input": 0, "output": 0, "cost": 0.0} for role in ("planner", "executor", "verifier")}

    for ticket_id in tickets:
        tdir, _archived = acs_lib.find_ticket_partition(workspace, repo_id, ticket_id)

        pipeline = acs_lib.read_json(os.path.join(tdir, "pipeline-state.json"))
        if isinstance(pipeline, dict):
            _accumulate_funnel(funnel, pipeline)
            p3_rows.append(_panel3_row(ticket_id, pipeline))
        else:
            degrade(ticket_id, 2, "pipeline-state.json absent — ticket omitted from the funnel")
            degrade(ticket_id, 3, "pipeline-state.json absent — no cost/time row")

        code_state = acs_lib.read_json(acs_lib.state_path(tdir, "code"))
        p4_rows.append(_panel4_row(ticket_id, code_state, degrade))
        p5_rows.append(_panel5_row(ticket_id, tdir, code_state, degrade))

        p7_rows.append(_panel7_row(ticket_id, tdir, pipeline, degrade))

        _accumulate_burn(burn, tdir)

    prs = (repo_metrics or {}).get("prs", {"created": 0, "merged": 0})
    totals = (repo_metrics or {}).get("totals", {})
    merged = prs.get("merged") if isinstance(prs, dict) else None
    working_seconds = totals.get("working_seconds") if isinstance(totals, dict) else None
    cost_usd = totals.get("cost_usd") if isinstance(totals, dict) else None
    ticket_count = meta["ticket_count"]

    panel2 = {"steps": funnel, "prs": prs}
    panel3 = {
        "tickets": p3_rows,
        "repo_totals": totals,
        "averages": {
            "avg_working_seconds_per_ticket": _safe_avg(working_seconds, ticket_count),
            "avg_working_seconds_per_pr": _safe_avg(working_seconds, merged),
            "avg_cost_per_ticket": _safe_avg(cost_usd, ticket_count),
            "avg_cost_per_pr": _safe_avg(cost_usd, merged),
        },
    }
    panel4 = {"tickets": p4_rows}
    panel5 = {"tickets": p5_rows}
    panel6 = burn
    panel7 = _panel7(p7_rows)

    panels = {"1": panel1, "2": panel2, "3": panel3, "4": panel4, "5": panel5,
              "6": panel6, "7": panel7}
    return {"panels": panels, "meta": meta}


def _panel1(tickets, repo_metrics):
    """Throughput by status/type: prefer metrics.json.tickets; recompute from the index otherwise."""
    if isinstance(repo_metrics, dict):
        tmetrics = repo_metrics.get("tickets")
        if isinstance(tmetrics, dict) and (tmetrics.get("by_status") or tmetrics.get("by_type")):
            return {"by_status": tmetrics.get("by_status", {}), "by_type": tmetrics.get("by_type", {})}
    by_status = {}
    by_type = {}
    for t in tickets.values():
        if not isinstance(t, dict):
            continue
        st = t.get("status")
        ty = t.get("type")
        if st is not None:
            by_status[st] = by_status.get(st, 0) + 1
        if ty is not None:
            by_type[ty] = by_type.get(ty, 0) + 1
    return {"by_status": by_status, "by_type": by_type}


def _accumulate_funnel(funnel, pipeline):
    steps = pipeline.get("steps")
    if not isinstance(steps, dict):
        return
    for skill in funnel:
        step = steps.get(skill)
        if isinstance(step, dict) and step.get("status") == "completed":
            funnel[skill] += 1


def _panel3_row(ticket_id, pipeline):
    steps = pipeline.get("steps") if isinstance(pipeline.get("steps"), dict) else {}
    per_step = {}
    for skill, step in steps.items():
        if isinstance(step, dict):
            per_step[skill] = acs_lib.run_seconds(step)
    totals = pipeline.get("totals") if isinstance(pipeline.get("totals"), dict) else {}
    return {"ticket_id": ticket_id, "steps": per_step, "totals": totals}


def _panel4_row(ticket_id, code_state, degrade):
    states = code_state.get("states") if isinstance(code_state, dict) else None
    tests = states.get("tests") if isinstance(states, dict) else None
    if not isinstance(tests, dict):
        degrade(ticket_id, 4, "code-state.json (states.tests) absent — coverage unavailable")
        return {"ticket_id": ticket_id, "cell": "no data"}
    achieved = tests.get("coverage_percent")
    target = tests.get("coverage_target")
    if not isinstance(achieved, (int, float)) or isinstance(achieved, bool) or not isinstance(target, (int, float)) or isinstance(target, bool):
        degrade(ticket_id, 4, "coverage_percent null or coverage_target non-numeric — no coverage cell")
        return {"ticket_id": ticket_id, "cell": "no data"}
    return {
        "ticket_id": ticket_id,
        "achieved": achieved,
        "target": target,
        "passed": bool((states or {}).get("verifier_passed")),
    }


def _panel5_row(ticket_id, tdir, code_state, degrade):
    states = code_state.get("states") if isinstance(code_state, dict) else None
    review = states.get("review") if isinstance(states, dict) else None
    if isinstance(review, dict) and isinstance(review.get("iterations"), int):
        return {"ticket_id": ticket_id, "iterations": review["iterations"]}
    # fallback: max iteration among phases/code/iter-N-verify.xml result files
    max_iter = _max_verify_iteration(tdir)
    if max_iter is not None:
        return {"ticket_id": ticket_id, "iterations": max_iter}
    degrade(ticket_id, 5, "no review.iterations and no code/iter-*-verify.xml — iterations unknown")
    return {"ticket_id": ticket_id, "iterations": "no data"}


def _rework_count(tdir):
    """Count distinct positive PR numbers from create-pr-state.json in the resolved partition.

    Reads `state_path(tdir, 'create-pr')` (i.e. <tdir>/create-pr-state.json) and collects
    distinct positive integers from:
      - data["states"]["pr"]["number"] (the current/latest PR number)
      - data["runs"][i]["pr"]["number"] for each run entry (historical PR numbers)

    Returns len({n for n in numbers if isinstance(n, int) and n > 0}).
    Returns 0 on any error: missing file, missing keys, malformed JSON — consistent with the
    B1 "missing input -> no data, never crash" invariant (design.md lines 89-97).
    This function is read-only: it never writes to disk.
    """
    path = acs_lib.state_path(tdir, "create-pr")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return 0

    if not isinstance(data, dict):
        return 0

    numbers = set()

    # Collect from states.pr.number (current PR)
    try:
        n = data["states"]["pr"]["number"]
        if isinstance(n, int) and not isinstance(n, bool) and n > 0:
            numbers.add(n)
    except (KeyError, TypeError):
        pass

    # Collect from runs[i].pr.number (historical PRs across all runs)
    runs = data.get("runs")
    if isinstance(runs, list):
        for run in runs:
            try:
                n = run["pr"]["number"]
                if isinstance(n, int) and not isinstance(n, bool) and n > 0:
                    numbers.add(n)
            except (KeyError, TypeError):
                pass

    return len(numbers)


def _panel7_row(ticket_id, tdir, pipeline, degrade):
    """Per-ticket lead/cycle wall-clock seconds (AC-2). Reads ticket.json.created_at (read-only).

    lead  = merge-pr.ended_at - ticket.json.created_at
    cycle = merge-pr.ended_at - code.started_at
    End anchor is merge-pr (NOT create-pr); value is wall-clock elapsed (NOT working_seconds).
    A value that cannot be computed is the string "no data" plus a panel-7 meta.degraded entry.

    Overlap-safe guarantee (spec 02 / design B1): aggregate() never raises on overlapping or
    re-cycled spans. When code.started_at falls after merge-pr.ended_at (cycle inversion) or
    ticket.created_at falls after merge-pr.ended_at (lead inversion), _elapsed_seconds returns
    None, cycle_seconds / lead_seconds is set to "no data", and the ticket id is appended to
    meta.degraded (panel 7). One row is always returned per ticket; nothing is written.

    rework_count (spec 02 AC-8): per-ticket count of distinct positive PR numbers recoverable
    from create-pr-state.json in the resolved partition (tdir). Additive field; always an int
    >= 0; not averaged. Never raises: missing or malformed state files contribute 0.
    """
    ticket = acs_lib.read_json(os.path.join(tdir, "ticket.json"))
    created_at = ticket.get("created_at") if isinstance(ticket, dict) else None

    steps = pipeline.get("steps") if isinstance(pipeline, dict) else None
    steps = steps if isinstance(steps, dict) else {}
    merge_step = steps.get("merge-pr")
    merge_ended = merge_step.get("ended_at") if isinstance(merge_step, dict) else None
    code_step = steps.get("code")
    code_started = code_step.get("started_at") if isinstance(code_step, dict) else None

    lead = _elapsed_seconds(created_at, merge_ended)
    cycle = _elapsed_seconds(code_started, merge_ended)

    # Degrade reasons (B1): emit the open-ticket reason alone when there is no merge-pr.ended_at
    # (both unavailable for one root cause); otherwise emit at most one reason per missing input.
    if acs_lib.parse_iso(merge_ended) is None:
        degrade(ticket_id, 7, "no merged PR — lead/cycle in progress")
    else:
        if lead is None:
            degrade(ticket_id, 7, "no ticket created_at — lead unavailable")
        if cycle is None:
            degrade(ticket_id, 7, "no code step — cycle unavailable")

    return {
        "ticket_id": ticket_id,
        "lead_seconds": lead if lead is not None else "no data",
        "cycle_seconds": cycle if cycle is not None else "no data",
        "rework_count": _rework_count(tdir),
    }


def _panel7(p7_rows):
    """Assemble panel 7: per-ticket rows plus averages over the subset with a numeric value.

    rework_count is a per-ticket count field, not a duration — it is not averaged here.
    Only lead_seconds and cycle_seconds contribute to the panel-level averages.
    """
    leads = [r["lead_seconds"] for r in p7_rows if _is_number(r["lead_seconds"])]
    cycles = [r["cycle_seconds"] for r in p7_rows if _is_number(r["cycle_seconds"])]
    return {
        "tickets": p7_rows,
        "avg_lead_seconds": _safe_avg(sum(leads), len(leads)),
        "avg_cycle_seconds": _safe_avg(sum(cycles), len(cycles)),
    }


def _max_verify_iteration(tdir):
    best = None
    for path in glob.glob(os.path.join(tdir, "phases", "code", "iter-*-verify.xml")):
        match = _ITER_RE.search(_read_text(path))
        if match:
            n = int(match.group(1))
            best = n if best is None else max(best, n)
    return best


def _accumulate_burn(burn, tdir):
    """Sum <metrics> token burn into role buckets across the ticket's phase XMLs (panel 6)."""
    for path in glob.glob(os.path.join(tdir, "phases", "*", "iter-*-*.xml")):
        text = _read_text(path)
        tag = _METRICS_TAG_RE.search(text)
        if not tag:
            continue  # no <metrics> (e.g. -task.xml or a no-metrics result) contributes 0
        phase_match = _PHASE_RE.search(text)
        role = PHASE_ROLE.get(phase_match.group(1)) if phase_match else None
        if role is None:
            continue  # `coordinate` (or any unmapped phase) is excluded — ledger C-5
        attrs = tag.group(1)
        ti = _TI_RE.search(attrs)
        to = _TO_RE.search(attrs)
        cost = _COST_RE.search(attrs)
        bucket = burn[role]
        bucket["input"] += _to_int(ti.group(1)) if ti else 0
        bucket["output"] += _to_int(to.group(1)) if to else 0
        bucket["cost"] = round(bucket["cost"] + (_to_float(cost.group(1)) if cost else 0.0), 6)


def _read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return ""


def main():
    """Thin smoke path: resolve {workspace, repo_id} via build_context, aggregate, print JSON."""
    ctx = acs_lib.build_context(os.getcwd())
    result = aggregate(ctx["workspace"], ctx["repo_id"])
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
