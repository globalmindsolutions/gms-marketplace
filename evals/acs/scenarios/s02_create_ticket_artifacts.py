"""s02 — create-ticket artifacts (paid, G1).

Runs a real `claude -p` session that invokes `/acs:create-ticket` on a trivial
request, then asserts on the workspace artifacts the skill writes — the ticket
schema, the repo-level index/counters/metrics, the pipeline state — and that
the gate has advanced exactly one step. This is the canonical agentic eval:
the assertion target is workspace state, never the model's prose.
"""

from harness import Sandbox, Check

META = {
    "name": "create_ticket_artifacts",
    "tier": "paid",
    "goal": "G1",
    "summary": "/acs:create-ticket writes a schema-complete task ticket + indexes",
}

PROMPT = (
    'Run the /acs:create-ticket skill with this request: '
    'Add a /health endpoint that returns "ok". '
    'This is a simple TASK (not epic/story) and needs_design is FALSE — treat '
    'both as already confirmed and DO NOT ask me anything. Complete the full '
    'skill including its reflection cycle.'
)


def run():
    check = Check(META["name"])
    with Sandbox(prefix="EVAL", slug="shop", init=True) as sb:
        r = sb.run_skill(PROMPT)
        check.cost = r.get("cost_usd")
        if not check.ok("claude session completed without error", r["ok"],
                        (r.get("stderr") or r.get("raw") or "")[:200]):
            return check  # nothing to assert on if the session died

        tid = "EVAL-1"  # first allocation under prefix EVAL

        # Repo-level artifacts exist and are well-formed.
        idx = sb.repo_json("tickets-index.json")
        sb.repo_json("counters.json")
        sb.repo_json("metrics.json")
        check.ok("ticket appears in tickets-index", tid in idx.get("tickets", {}),
                 list(idx.get("tickets", {})))

        # Ticket schema fields.
        t = sb.ticket_json(tid, "ticket.json")
        check.eq("ticket id honors prefix", t.get("id"), tid)
        check.eq("ticket type is task", t.get("type"), "task")
        check.eq("needs_design is false", t.get("needs_design"), False)

        # Pipeline state advanced create-ticket to completed.
        ps = sb.ticket_json(tid, "pipeline-state.json")
        step = ps.get("steps", {}).get("create-ticket", {})
        check.eq("create-ticket step completed", step.get("status"), "completed")

        # Gate moved forward by exactly one step (G1).
        code, err = sb.gate("code", tid)
        check.ok("gate advanced to create-spec",
                 code == 2 and "create-spec" in err, err)

    return check
