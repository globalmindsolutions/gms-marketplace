#!/usr/bin/env python3
"""new-ticket.py — allocate a ticket id and create its workspace partition.

Used by the /create-ticket executor (epic children fan-out, remote imports) and
anywhere else a ticket must be minted. Maintains both directions of the
epic <-> child link and the repo-level tickets-index.json.

Usage:
  new-ticket.py --title "Wishlist API" --type story [--parent SHOP-122]
                [--description "..."] [--priority high] [--needs-design true]
                [--external jira:PROJ-456] [--assignee jane] [--story-points 3]

Prints {"ticket_id": ..., "partition": ...} on success.
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import acs_lib as lib  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", required=True)
    parser.add_argument("--type", dest="ttype", required=True, choices=lib.TICKET_TYPES)
    parser.add_argument("--description", default="")
    parser.add_argument("--priority", default="medium", choices=lib.PRIORITIES)
    parser.add_argument("--parent", help="parent epic ticket id")
    parser.add_argument("--needs-design", dest="needs_design", choices=["true", "false"],
                        help="override the needs_design flag (epics default to true)")
    parser.add_argument("--docs-only", dest="docs_only", choices=["true", "false"], default="false",
                        help="user-confirmed docs-only flag (relaxes /code TDD/coverage gates)")
    parser.add_argument("--external", help="remote tracker mapping, e.g. jira:PROJ-456 or github:123")
    parser.add_argument("--assignee")
    parser.add_argument("--story-points", dest="story_points", type=int)
    parser.add_argument("--due-date", dest="due_date",
                        help="Optional delivery target date, ISO-8601 YYYY-MM-DD.")
    parser.add_argument("--size", dest="size",
                        choices=["trivial", "small", "standard", "large"],
                        default="standard",
                        help="Ticket size axis (default: standard).")
    parser.add_argument("--stakes", dest="stakes",
                        choices=["low", "normal", "high"],
                        default="normal",
                        help="Stakes axis (default: normal).")
    args = parser.parse_args()

    if args.due_date is not None:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.due_date):
            sys.stderr.write(
                "acs new-ticket: --due-date must be YYYY-MM-DD, got: %r\n" % args.due_date
            )
            sys.exit(2)

    cwd = os.getcwd()
    try:
        ctx = lib.build_context(cwd)
    except lib.GateError as exc:
        sys.stderr.write("acs new-ticket: %s\n" % exc)
        sys.exit(2)
    workspace, repo_id = ctx["workspace"], ctx["repo_id"]

    external = None
    if args.external:
        provider, _, key = args.external.partition(":")
        if not key:
            sys.stderr.write("acs new-ticket: --external must be <provider>:<key>\n")
            sys.exit(2)
        external = {"provider": provider, "key": key}

    parent_dir = None
    parent_ticket = None
    if args.parent:
        parent_dir, archived = lib.find_ticket_partition(workspace, repo_id, args.parent)
        parent_ticket = lib.load_ticket(parent_dir) if os.path.isdir(parent_dir) else None
        if archived or not parent_ticket:
            sys.stderr.write("acs new-ticket: parent ticket %s not found (or archived)\n" % args.parent)
            sys.exit(2)
        if parent_ticket.get("type") != "epic":
            sys.stderr.write("acs new-ticket: parent %s is a %s, not an epic\n" % (args.parent, parent_ticket.get("type")))
            sys.exit(2)

    ticket_id = lib.allocate_ticket_id(workspace, repo_id, ctx["settings"]["ticket_prefix"])
    tdir = lib.ticket_dir(workspace, repo_id, ticket_id)
    os.makedirs(tdir, exist_ok=True)

    needs_design = (args.ttype == "epic")
    if args.needs_design is not None:
        needs_design = args.needs_design == "true"

    ticket = lib.new_ticket_doc(
        ticket_id, args.title, args.ttype,
        description=args.description,
        priority=args.priority,
        parent=args.parent,
        external=external,
        assignee=args.assignee,
        story_points=args.story_points,
        needs_design=needs_design,
        docs_only=args.docs_only == "true",
        size=args.size,
        stakes=args.stakes,
        due_date=args.due_date,
    )
    lib.save_ticket(tdir, ticket)
    lib.update_index(workspace, repo_id, ticket, archived=False)

    # Children of an epic (and remote imports finalized here) do not run
    # /create-ticket themselves — their pipeline starts at /create-spec (or
    # /create-design). Record a completed create-ticket run so the downstream
    # gates hold uniformly: "create-ticket completed" == "the ticket was
    # properly created".
    lib.append_in_progress_run(tdir, "create-ticket", ticket_id)
    lib.finalize_run(tdir, "create-ticket", ticket_id, {
        "status": "completed",
        "stop_reason": "ticket created via /create-ticket"
                       + (" (child of %s)" % args.parent if args.parent else ""),
        "states": {
            "ticket_id": ticket_id,
            "type": args.ttype,
            "needs_design": needs_design,
            "parent": args.parent,
        },
    })
    lib.update_pipeline(tdir, ticket_id, "create-ticket", "completed",
                        summary="created" + (" as child of %s" % args.parent if args.parent else ""),
                        lane=ticket.get("lane"))

    if parent_ticket is not None:
        children = parent_ticket.setdefault("children", [])
        if ticket_id not in children:
            children.append(ticket_id)
        lib.save_ticket(parent_dir, parent_ticket)
        lib.update_index(workspace, repo_id, parent_ticket)

    lib.update_metrics(workspace, repo_id)
    print(json.dumps({"ticket_id": ticket_id, "partition": tdir}, indent=2))


if __name__ == "__main__":
    main()
