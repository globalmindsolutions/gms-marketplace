#!/usr/bin/env python3
"""record-external.py — stamp external={provider,key} into one ticket's ticket.json.

The deterministic write seam for tracker sync (MAR-84 spec 01): `gh issue
create` / `gh project item-add` / field-set calls stay in prose
(create-ticket/SKILL.md Step 5, create-ticket-executor.md Step 5). Once that
prose sequence has a real remote {provider, key} in hand for one ticket, it
calls this helper to record it. This helper does NOT call gh/acli, does not
touch the network, and does not decide whether a ticket should be synced — it
only performs (and validates) the single-ticket write, once per invocation.

Refuses, in order:
  1. context cannot be built (acs_lib.GateError, e.g. not initialized).
  2. the ticket partition is absent or archived (not-found refusal).
  3. the ticket's title is one of acs_lib.PRODUCT_TICKET_TITLES' values —
     product-flow tickets are never synced by this helper (AC-4 defense in
     depth: even a caller mistakenly pointed at one is refused here too).

On success, writes ticket["external"] = {"provider": ..., "key": ...} via
acs_lib.save_ticket (which also refreshes updated_at) and prints
{"ticket_id": ..., "external": {...}} to stdout.

Usage:
  record-external.py --ticket SHOP-123 --provider github --key 456
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import acs_lib as lib  # noqa: E402


def record_external(cwd, ticket_id, provider, key):
    """Testable core: resolve the ticket, validate, write. No argparse, no
    sys.exit — returns (ok, payload_or_message) so callers (main() and unit
    tests / the coverage harness) can drive every branch without a subprocess.

    Returns (True, {"ticket_id": ..., "external": {...}}) on success, or
    (False, "<stderr message>") on any refusal.
    """
    ctx = lib.build_context(cwd)
    workspace, repo_id = ctx["workspace"], ctx["repo_id"]

    tdir, archived = lib.find_ticket_partition(workspace, repo_id, ticket_id)
    ticket = lib.load_ticket(tdir) if os.path.isdir(tdir) else None
    if archived or not ticket:
        return False, "acs record-external: ticket %s not found (or archived)" % ticket_id

    if ticket.get("title") in lib.PRODUCT_TICKET_TITLES.values():
        return False, (
            "acs record-external: ticket %s (%r) is a product-flow ticket — "
            "product-flow tickets are never synced by this helper" % (ticket_id, ticket.get("title"))
        )

    ticket["external"] = {"provider": provider, "key": key}
    lib.save_ticket(tdir, ticket)
    return True, {"ticket_id": ticket_id, "external": ticket["external"]}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticket", required=True)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--key", required=True)
    args = parser.parse_args(argv)

    try:
        ok, result = record_external(os.getcwd(), args.ticket, args.provider, args.key)
    except lib.GateError as exc:
        sys.stderr.write("acs record-external: %s\n" % exc)
        sys.exit(2)

    if not ok:
        sys.stderr.write("%s\n" % result)
        sys.exit(2)

    print(json.dumps(result))
    sys.exit(0)


if __name__ == "__main__":
    main()  # pragma: no cover
