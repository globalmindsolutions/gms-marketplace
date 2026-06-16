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

PANEL_KEYS = ("1", "2", "3", "4", "5", "6")

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

        _accumulate_burn(burn, tdir)

    panel2 = {"steps": funnel, "prs": (repo_metrics or {}).get("prs", {"created": 0, "merged": 0})}
    panel3 = {"tickets": p3_rows, "repo_totals": (repo_metrics or {}).get("totals", {})}
    panel4 = {"tickets": p4_rows}
    panel5 = {"tickets": p5_rows}
    panel6 = burn

    panels = {"1": panel1, "2": panel2, "3": panel3, "4": panel4, "5": panel5, "6": panel6}
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
