#!/usr/bin/env python3
"""Entry point for the acs behavioral eval harness (M2 epic E1.1).

Runs scenarios from `evals/scenarios/` and reports per-assertion pass/fail
against workspace artifacts. Free scenarios (no `claude`) run by default;
paid scenarios (real `claude -p`) require `--paid`.

    python3 evals/run_evals.py                 # free tier
    python3 evals/run_evals.py --paid          # + claude-driven scenarios
    python3 evals/run_evals.py --only create_ticket_artifacts --paid
    python3 evals/run_evals.py --list

Exit code is non-zero if any selected scenario has a failing assertion, so it
can gate the nightly job (E1.4).
"""

import argparse
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import installed_scripts_dir  # noqa: E402
from scenarios import SCENARIOS  # noqa: E402

TIERS_DEFAULT = {"free"}


def selected(args):
    tiers = set(TIERS_DEFAULT)
    if args.paid:
        tiers.add("paid")
    if args.forge:
        tiers.add("forge")
    for mod in SCENARIOS:
        meta = mod.META
        if args.only and meta["name"] not in args.only:
            continue
        if meta["tier"] not in tiers and not (args.only and meta["name"] in args.only):
            continue
        yield mod


def main():
    ap = argparse.ArgumentParser(description="acs behavioral eval harness")
    ap.add_argument("--paid", action="store_true",
                    help="also run scenarios that spawn `claude -p` (costs money)")
    ap.add_argument("--forge", action="store_true",
                    help="also run scenarios needing a GitHub remote")
    ap.add_argument("--only", action="append", metavar="NAME",
                    help="run only the named scenario(s); implies its tier")
    ap.add_argument("--keep", action="store_true",
                    help="keep sandbox temp dirs for inspection")
    ap.add_argument("--list", action="store_true", help="list scenarios and exit")
    args = ap.parse_args()

    if args.keep:
        os.environ["ACS_EVAL_KEEP"] = "1"

    if args.list:
        for mod in SCENARIOS:
            m = mod.META
            print("%-28s %-6s %-4s  %s" % (m["name"], m["tier"], m["goal"],
                                           m["summary"]))
        return 0

    _, build = installed_scripts_dir()
    print("acs eval harness — plugin build under test: %s\n" % build)

    chosen = list(selected(args))
    if not chosen:
        print("no scenarios selected (free tier is default; use --paid).")
        return 0

    total_cost = 0.0
    failed = []
    for mod in chosen:
        meta = mod.META
        print("==> %s  [%s, %s]" % (meta["name"], meta["tier"], meta["goal"]))
        try:
            check = mod.run()
        except Exception:
            print("    [FAIL] scenario raised:")
            print("           " + traceback.format_exc().replace("\n", "\n           "))
            failed.append(meta["name"])
            continue
        for line in check.lines():
            print(line)
        if getattr(check, "cost", None):
            total_cost += check.cost
            print("    cost: ~$%.2f" % check.cost)
        if not check.passed:
            failed.append(meta["name"])
        print()

    print("-" * 60)
    print("scenarios: %d run, %d failed" % (len(chosen), len(failed)))
    if total_cost:
        print("total claude cost: ~$%.2f" % total_cost)
    if failed:
        print("FAILED: " + ", ".join(failed))
        return 1
    print("all passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
