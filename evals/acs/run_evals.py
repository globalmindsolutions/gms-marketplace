#!/usr/bin/env python3
"""acs behavioral eval runner — entry point for the acs plugin's scenario suite.

Runs scenarios from ``evals/acs/scenarios/`` and reports per-assertion
pass/fail against workspace artifacts. Free scenarios (no ``claude``) run by
default; paid scenarios require ``--paid``.

Can be invoked directly or via the top-level dispatcher:

    python3 evals/acs/run_evals.py                    # acs free tier (direct)
    python3 evals/acs/run_evals.py --paid             # + claude-driven scenarios
    python3 evals/acs/run_evals.py --list
    python3 evals/run_evals.py                        # via dispatcher (default acs)
    python3 evals/run_evals.py --plugin acs           # via dispatcher (explicit)

Exit code is non-zero if any selected scenario has a failing assertion.
"""

import argparse
import importlib
import os
import sys
import traceback

# Insert evals/acs/ onto sys.path at module scope so every scenario file's
# `from harness import Sandbox, Check` resolves to evals/acs/harness.py
# without modifying any scenario import line (AC-4).
_acs_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _acs_dir)

# The banner import resolves via the sys.path insertion above.
from harness import installed_scripts_dir  # noqa: E402

TIERS_DEFAULT = {"free"}


def load_scenarios(plugin_name="acs"):
    """Import SCENARIOS from evals/acs/scenarios/__init__.py.

    Inserts the acs runner's own directory (evals/acs/) onto sys.path so that
    ``import scenarios`` resolves to the acs scenarios package.
    """
    plugin_dir = _acs_dir
    if plugin_dir not in sys.path:
        sys.path.insert(0, plugin_dir)
    try:
        # Force re-import in case a previous call cached a different module.
        if "scenarios" in sys.modules:
            del sys.modules["scenarios"]
        scenarios_mod = importlib.import_module("scenarios")
    except ModuleNotFoundError as exc:
        sys.stderr.write(
            "error: cannot find scenarios package for acs "
            "(expected %s/scenarios/__init__.py): %s\n"
            % (plugin_dir, exc)
        )
        sys.exit(1)
    return getattr(scenarios_mod, "SCENARIOS", [])


def selected(scenarios, args):
    tiers = set(TIERS_DEFAULT)
    if args.paid:
        tiers.add("paid")
    if args.forge:
        tiers.add("forge")
    for mod in scenarios:
        meta = mod.META
        if args.only and meta["name"] not in args.only:
            continue
        if meta["tier"] not in tiers and not (args.only and meta["name"] in args.only):
            continue
        yield mod


def main():
    ap = argparse.ArgumentParser(description="acs behavioral eval runner")
    ap.add_argument(
        "--plugin", default="acs", metavar="NAME",
        help="kept for CLI compatibility when invoked via the dispatcher "
             "(evals/acs/run_evals.py always runs the acs scenarios); default: acs",
    )
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

    scenarios = load_scenarios()

    if args.list:
        for mod in scenarios:
            m = mod.META
            print("%-28s %-6s %-4s  %s" % (m["name"], m["tier"], m["goal"],
                                            m["summary"]))
        return 0

    # Banner: always shown in the acs runner (this runner is always acs).
    _, build = installed_scripts_dir()
    print("acs eval harness — plugin build under test: %s\n" % build)

    chosen = list(selected(scenarios, args))
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
