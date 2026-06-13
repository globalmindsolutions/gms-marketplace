#!/usr/bin/env python3
"""skill-start.py — run by a skill's coordinator as its FIRST action.

Performs the deterministic start-of-run bookkeeping:
  * resolves settings, repo partition, and ticket id (argument -> pointer -> branch);
  * for /create-ticket and the product-level skills, allocates the (delivery) ticket
    id and creates the partition + ticket.json skeleton (--allocate);
  * acquires the partition .lock (re-entrant for this checkout);
  * writes the per-checkout pointer file sessions/<checkout-id>.json;
  * appends an `in_progress` run entry to <skill>-state.json (so even a hard crash
    leaves evidence and downstream gates read "not completed");
  * marks the ticket — and its parent epic, on the first workflow-skill run of a
    child — In Progress;
  * prints a context JSON document for the coordinator: paths, resolved settings,
    ticket, reconcile/handoff information, and the design source partition.

Usage:
  skill-start.py --skill code [--ticket SHOP-123] [--args "$ARGUMENTS"]
  skill-start.py --skill create-ticket --allocate [--title "..."] [--type task]
  skill-start.py --skill create-prd --allocate
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import acs_lib as lib  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skill", required=True, choices=lib.HOOKED_SKILLS)
    parser.add_argument("--ticket", help="explicit ticket id")
    parser.add_argument("--args", default="", help="the skill's raw $ARGUMENTS (ticket id is extracted)")
    parser.add_argument("--allocate", action="store_true",
                        help="allocate a new ticket id + partition (create-ticket / product-level skills)")
    parser.add_argument("--title", help="ticket title when allocating")
    parser.add_argument("--type", dest="ttype", choices=lib.TICKET_TYPES, default="task",
                        help="ticket type when allocating (default: task)")
    args = parser.parse_args()

    cwd = os.getcwd()
    try:
        ctx = lib.build_context(cwd)
    except lib.GateError as exc:
        sys.stderr.write("acs skill-start: %s\n" % exc)
        sys.exit(2)

    workspace, repo_id = ctx["workspace"], ctx["repo_id"]
    flow = "product" if args.skill in lib.PRODUCT_SKILLS else "ticket"

    if args.allocate:
        if args.skill not in lib.PRODUCT_SKILLS and args.skill != "create-ticket":
            sys.stderr.write("acs skill-start: --allocate is only valid for /create-ticket and product-level skills\n")
            sys.exit(2)
        prefix = ctx["settings"]["ticket_prefix"]
        ticket_id = lib.allocate_ticket_id(workspace, repo_id, prefix)
        tdir = lib.ticket_dir(workspace, repo_id, ticket_id)
        os.makedirs(tdir, exist_ok=True)
        title = args.title or lib.PRODUCT_TICKET_TITLES.get(args.skill, "(ticket under analysis)")
        ttype = "task" if args.skill in lib.PRODUCT_SKILLS else args.ttype
        ticket = lib.new_ticket_doc(ticket_id, title, ttype, status="in_progress")
        lib.save_ticket(tdir, ticket)
        lib.update_index(workspace, repo_id, ticket, archived=False)
    else:
        ticket_id, source = lib.resolve_ticket_id(cwd, ctx["settings"], workspace, repo_id,
                                                  explicit=args.ticket, args_text=args.args)
        if not ticket_id:
            sys.stderr.write(
                "acs skill-start: could not resolve a ticket id (argument -> session pointer -> branch name). "
                "Pass --ticket explicitly.\n")
            sys.exit(2)
        tdir, archived = lib.find_ticket_partition(workspace, repo_id, ticket_id)
        if archived:
            sys.stderr.write("acs skill-start: ticket %s is archived (done)\n" % ticket_id)
            sys.exit(2)
        if not os.path.isdir(tdir):
            sys.stderr.write("acs skill-start: no partition for %s — run /acs:create-ticket first\n" % ticket_id)
            sys.exit(2)
        ticket = lib.load_ticket(tdir)
        if not ticket:
            sys.stderr.write("acs skill-start: ticket.json missing/corrupt for %s\n" % ticket_id)
            sys.exit(2)

    try:
        lib.acquire_lock(tdir, cwd)
    except lib.GateError as exc:
        sys.stderr.write("acs skill-start: %s\n" % exc)
        sys.exit(2)

    # Per-checkout pointer: hooks and later skills resolve the current ticket from it.
    lib.write_json(lib.pointer_path(workspace, repo_id, ctx["checkout_id"]), {
        "checkout_id": ctx["checkout_id"],
        "checkout_path": ctx["checkout_root"],
        "ticket_id": ticket_id,
        "skill": args.skill,
        "updated_at": lib.now_iso(),
    })

    # Reconcile / handoff detection BEFORE appending the new run entry.
    prior_status = lib.last_run_status(tdir, args.skill)
    prior_state = lib.load_state(tdir, args.skill, ticket_id)
    handoff_summary = None
    if prior_status == "handed_off":
        entry = lib.last_run(prior_state) or {}
        handoff_summary = entry.get("handoff_summary")
    reconcile = prior_status in ("in_progress", "failed", "interrupted", "handed_off")

    lib.append_in_progress_run(tdir, args.skill, ticket_id)
    lib.update_pipeline(tdir, ticket_id, args.skill, "in_progress", flow=flow)

    # Work starts: ticket open -> in_progress; first child activity flips the epic.
    epic_marked = None
    if ticket.get("status") == "open":
        ticket["status"] = "in_progress"
        lib.save_ticket(tdir, ticket)
        lib.update_index(workspace, repo_id, ticket)
    parent_id, pdir = lib.parent_epic_dir(ctx, ticket)
    if parent_id and pdir:
        parent = lib.load_ticket(pdir)
        if parent and parent.get("status") == "open":
            parent["status"] = "in_progress"
            lib.save_ticket(pdir, parent)
            lib.update_index(workspace, repo_id, parent)
            epic_marked = parent_id

    design_required, design_dir, design_source = lib.design_requirement(ctx, tdir, ticket)

    print(json.dumps({
        "skill": args.skill,
        "flow": flow,
        "ticket_id": ticket_id,
        "ticket": ticket,
        "partition": tdir,
        "repo_id": repo_id,
        "workspace": workspace,
        "checkout_id": ctx["checkout_id"],
        "checkout_root": ctx["checkout_root"],
        "plugin_root": ctx["plugin_root"],
        "settings": ctx["settings"],
        "settings_sources": ctx["settings_sources"],
        "models": {role: lib.resolve_role_model(ctx["settings"], args.skill, role)
                   for role in ("planner", "executor", "verifier")},
        "prior_run_status": prior_status,
        "reconcile": reconcile,
        "handoff_summary": handoff_summary,
        "design": {"required": design_required, "dir": design_dir, "source": design_source},
        "pipeline": lib.load_pipeline(tdir, ticket_id, flow),
        "epic_marked_in_progress": epic_marked,
        "post_hook": os.path.join(ctx["plugin_root"], "hooks", "scripts", "post-%s.py" % args.skill),
    }, indent=2))


if __name__ == "__main__":
    main()
