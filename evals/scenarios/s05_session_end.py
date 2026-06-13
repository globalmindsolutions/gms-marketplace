"""s05 — SessionEnd safety net (free).

When a session ends mid-skill, the installed SessionEnd hook must finalize the
in-progress run as `interrupted` and release the ticket lock — otherwise the
next session is blocked by a stale lock and state lies about what happened.
Seeds an in-progress run via the installed helper CLIs, fires the installed
session-end hook, and asserts the transition against the shipped build
(`tests/` covers the same logic on the source tree).
"""

import os

from harness import Sandbox, Check

META = {
    "name": "session_end_safety_net",
    "tier": "free",
    "goal": "cleanup",
    "summary": "SessionEnd finalizes an interrupted run and releases the lock",
}


def run():
    check = Check(META["name"])
    with Sandbox(prefix="EVAL", slug="shop", init=True) as sb:
        tid = sb.mint_ticket("Add a /health endpoint returning ok", "task",
                             needs_design=False)
        sb.start_run("create-spec", tid)  # in_progress + lock + session pointer

        st = sb.ticket_json(tid, "create-spec-state.json")
        check.eq("seed: create-spec is in_progress",
                 st["runs"][-1]["status"], "in_progress")
        check.ok("seed: ticket lock held",
                 os.path.exists(sb.ticket_path(tid, ".lock")))

        rc, err = sb.session_end()
        check.eq("session-end exits 0", rc, 0)

        st2 = sb.ticket_json(tid, "create-spec-state.json")
        check.eq("run finalized as interrupted",
                 st2["runs"][-1]["status"], "interrupted")
        check.ok("lock released",
                 not os.path.exists(sb.ticket_path(tid, ".lock")), err)

    return check
