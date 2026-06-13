#!/usr/bin/env python3
"""clarify.py — the per-ticket requirement-clarification ledger.

One append-only Q&A record per ticket at <partition>/clarifications.json —
the single source of truth for every requirement ambiguity resolved (or
assumed) during the pipeline. Coordinators MUST read it before asking the
user anything (re-asking an answered question is a defect) and MUST record
every Q&A through this helper (atomic writes; no hand-edited JSON).

Usage:
  clarify.py add    --skill create-spec --question "Overwrite or reject duplicates?"
                    [--answer "reject"] [--source user|assumption]
                    [--rationale "why this assumption is needed"]
                    [--ticket SHOP-123]
  clarify.py answer --id C-2 --answer "reject" [--source user] [--ticket SHOP-123]
  clarify.py list   [--open] [--ticket SHOP-123]

Statuses: open (asked, unanswered — e.g. sent upward in a needs_input
handoff), answered (user decided), assumed (no user available/needed —
requires --rationale; assumptions surface in completion reports and the PR
body until a user confirms them).
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import acs_lib as lib  # noqa: E402


def ledger_path(tdir):
    return os.path.join(tdir, "clarifications.json")


def load_ledger(tdir, ticket_id):
    data = lib.read_json(ledger_path(tdir))
    if not isinstance(data, dict) or not isinstance(data.get("clarifications"), list):
        data = {"ticket_id": ticket_id, "clarifications": []}
    return data


def resolve(args):
    cwd = os.getcwd()
    try:
        ctx = lib.build_context(cwd)
    except lib.GateError as exc:
        sys.stderr.write("acs clarify: %s\n" % exc)
        sys.exit(2)
    ticket_id, _src = lib.resolve_ticket_id(cwd, ctx["settings"], ctx["workspace"], ctx["repo_id"],
                                            explicit=args.ticket)
    if not ticket_id:
        sys.stderr.write("acs clarify: could not resolve the ticket id (pass --ticket)\n")
        sys.exit(2)
    tdir, archived = lib.find_ticket_partition(ctx["workspace"], ctx["repo_id"], ticket_id)
    if not os.path.isdir(tdir):
        sys.stderr.write("acs clarify: no partition for %s\n" % ticket_id)
        sys.exit(2)
    if archived and args.cmd != "list":
        sys.stderr.write("acs clarify: %s is archived — ledger is read-only\n" % ticket_id)
        sys.exit(2)
    return ticket_id, tdir


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_add = sub.add_parser("add")
    p_add.add_argument("--skill", required=True, choices=lib.HOOKED_SKILLS)
    p_add.add_argument("--question", required=True)
    p_add.add_argument("--answer")
    p_add.add_argument("--source", choices=["user", "assumption"], default="user")
    p_add.add_argument("--rationale", help="required when --source assumption")
    p_add.add_argument("--ticket")

    p_ans = sub.add_parser("answer")
    p_ans.add_argument("--id", required=True)
    p_ans.add_argument("--answer", required=True)
    p_ans.add_argument("--source", choices=["user", "assumption"], default="user")
    p_ans.add_argument("--rationale")
    p_ans.add_argument("--ticket")

    p_list = sub.add_parser("list")
    p_list.add_argument("--open", action="store_true", help="only open questions")
    p_list.add_argument("--ticket")

    args = parser.parse_args()
    ticket_id, tdir = resolve(args)
    data = load_ledger(tdir, ticket_id)
    entries = data["clarifications"]

    if args.cmd == "add":
        if args.source == "assumption" and not (args.rationale or "").strip():
            sys.stderr.write("acs clarify: --source assumption requires --rationale\n")
            sys.exit(2)
        if args.source == "assumption" and not args.answer:
            sys.stderr.write("acs clarify: an assumption must state the assumed answer (--answer)\n")
            sys.exit(2)
        entry = {
            "id": "C-%d" % (len(entries) + 1),
            "skill": args.skill,
            "question": args.question.strip(),
            "answer": (args.answer or "").strip() or None,
            "source": args.source if args.answer else None,
            "rationale": (args.rationale or "").strip() or None,
            "status": ("assumed" if args.source == "assumption" else "answered") if args.answer else "open",
            "asked_at": lib.now_iso(),
            "answered_at": lib.now_iso() if args.answer else None,
        }
        entries.append(entry)
        lib.write_json(ledger_path(tdir), data)
        print(json.dumps(entry, indent=2))
        return

    if args.cmd == "answer":
        for entry in entries:
            if entry.get("id") == args.id:
                entry["answer"] = args.answer.strip()
                entry["source"] = args.source
                if args.rationale:
                    entry["rationale"] = args.rationale.strip()
                entry["status"] = "assumed" if args.source == "assumption" else "answered"
                entry["answered_at"] = lib.now_iso()
                lib.write_json(ledger_path(tdir), data)
                print(json.dumps(entry, indent=2))
                return
        sys.stderr.write("acs clarify: no entry %s in %s\n" % (args.id, ledger_path(tdir)))
        sys.exit(2)

    if args.cmd == "list":
        wanted = [e for e in entries if not args.open or e.get("status") == "open"]
        print(json.dumps({"ticket_id": ticket_id, "count": len(wanted), "clarifications": wanted}, indent=2))


if __name__ == "__main__":
    main()
