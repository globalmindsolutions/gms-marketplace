#!/usr/bin/env python3
"""handoff.py — graceful session handoff for the current ticket.

Run by the /handoff utility skill (or proactively by a coordinator under context
pressure) AFTER it has flushed all soft context to the ticket partition:

  * finalizes the current `in_progress` run entry as `handed_off`, attaching the
    handoff summary (what is done, what is in flight, next actions, decisions);
  * updates the pipeline ledger;
  * releases the partition .lock so ANY session can take over;
  * prints the exact command to continue in a fresh session.

Usage:
  handoff.py --summary "done: specs 1-2; in flight: spec 3 tests; next: coverage" [--ticket SHOP-123]
  handoff.py --summary-file <path> [--ticket SHOP-123]
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import acs_lib as lib  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", help="handoff summary text")
    parser.add_argument("--summary-file", help="file containing the handoff summary")
    parser.add_argument("--ticket", help="ticket id (defaults to this checkout's pointer)")
    args = parser.parse_args()

    summary = args.summary
    if args.summary_file:
        with open(args.summary_file, "r", encoding="utf-8") as fh:
            summary = fh.read().strip()
    if not summary:
        sys.stderr.write("acs handoff: a handoff summary is required (--summary or --summary-file)\n")
        sys.exit(2)

    cwd = os.getcwd()
    try:
        ctx = lib.build_context(cwd)
    except lib.GateError as exc:
        sys.stderr.write("acs handoff: %s\n" % exc)
        sys.exit(2)

    ticket_id, _ = lib.resolve_ticket_id(cwd, ctx["settings"], ctx["workspace"], ctx["repo_id"],
                                         explicit=args.ticket)
    if not ticket_id:
        sys.stderr.write("acs handoff: no current ticket for this checkout (nothing to hand off)\n")
        sys.exit(2)
    tdir, archived = lib.find_ticket_partition(ctx["workspace"], ctx["repo_id"], ticket_id)
    if archived or not os.path.isdir(tdir):
        sys.stderr.write("acs handoff: no active partition for %s\n" % ticket_id)
        sys.exit(2)

    # Find the skill whose run is in progress (pointer first, then scan).
    pointer = lib.read_json(lib.pointer_path(ctx["workspace"], ctx["repo_id"], ctx["checkout_id"]))
    candidates = []
    if isinstance(pointer, dict) and pointer.get("skill"):
        candidates.append(pointer["skill"])
    candidates += [s for s in lib.HOOKED_SKILLS if s not in candidates]

    handed = None
    for skill in candidates:
        if lib.last_run_status(tdir, skill) == "in_progress":
            _state, entry = lib.finalize_run(tdir, skill, ticket_id, {
                "status": "handed_off",
                "stop_reason": "session handoff",
                "handoff_summary": summary,
            })
            lib.update_pipeline(tdir, ticket_id, skill, "handed_off", summary=summary,
                                flow="product" if skill in lib.PRODUCT_SKILLS else "ticket")
            # a handed-off run still spent time/tokens — keep repo metrics
            # consistent with the ticket ledger
            lib.update_metrics(ctx["workspace"], ctx["repo_id"], run_entry=entry)
            handed = skill
            break

    lib.release_lock(tdir, cwd)

    if handed:
        resume = "/acs:%s %s" % (handed, ticket_id)
    else:
        resume = "/acs:ship %s" % ticket_id
    print(json.dumps({
        "ok": True,
        "ticket_id": ticket_id,
        "skill": handed,
        "lock_released": True,
        "continue_with": resume,
    }, indent=2))


if __name__ == "__main__":
    main()
