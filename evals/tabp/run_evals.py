#!/usr/bin/env python3
"""tabp behavioral eval runner — entry point for the tabp plugin's scenario suite.

Self-contained: no Sandbox, no installed_scripts_dir, no acs banner.
Scenarios live in evals/tabp/scenarios/.  Currently one scenario:
  - screen_cvs_eval (tier: paid) — asserts the screen-cvs rubric contract.

The live model invocation is gated behind ``--paid``.  The default
(free-tier) run is import-clean and list-able with NO model call.

Can be invoked directly or via the top-level dispatcher::

    python3 evals/tabp/run_evals.py --list          # list scenarios, exit 0
    python3 evals/tabp/run_evals.py                 # default: no paid → no-op
    python3 evals/tabp/run_evals.py --paid          # run screen_cvs_eval (needs Cowork)

Via dispatcher::

    python3 evals/run_evals.py --plugin tabp --list
    python3 evals/run_evals.py --plugin tabp
    python3 evals/run_evals.py --plugin tabp --paid

Exit code is non-zero if any selected scenario's Check.passed is False.

Developer note — running the live eval locally
----------------------------------------------
Requires: the Cowork model runtime and ``pip install openpyxl`` (absent from
the stdlib-only repo CI env; deferred inside the paid run path).

    pip install openpyxl
    python3 evals/run_evals.py --plugin tabp --paid
"""

import argparse
import importlib
import os
import sys
import traceback

# Insert this file's own directory onto sys.path at module scope so that
# ``import scenarios`` resolves to evals/tabp/scenarios/__init__.py without
# relying on the calling process's sys.path.  This mirrors the pattern
# proved in tests/acs/test_run_evals_dispatch.py lines 97-153 and
# evals/acs/run_evals.py lines 28-29.
_tabp_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _tabp_dir)

# NO Sandbox import.  NO installed_scripts_dir.  NO acs-specific banner.
# (See spec 03 runner design; test_run_evals_dispatch.py lines 182-189.)

TIERS_DEFAULT = {"free"}


def load_scenarios():
    """Import SCENARIOS from evals/tabp/scenarios/__init__.py."""
    # Clear any stale cached module so repeated calls work correctly (mirrors
    # evals/acs/run_evals.py lines 47-50).
    if "scenarios" in sys.modules:
        del sys.modules["scenarios"]
    try:
        scenarios_mod = importlib.import_module("scenarios")
    except ModuleNotFoundError as exc:
        sys.stderr.write(
            "error: cannot find scenarios package for tabp "
            "(expected %s/scenarios/__init__.py): %s\n"
            % (_tabp_dir, exc)
        )
        sys.exit(1)
    return getattr(scenarios_mod, "SCENARIOS", [])


def selected(scenarios, args):
    """Yield scenario modules that match the active tier set."""
    tiers = set(TIERS_DEFAULT)
    if args.paid:
        tiers.add("paid")
    if args.forge:
        tiers.add("forge")
    for mod in scenarios:
        meta = mod.META
        # --only overrides tier gating for the named scenarios
        if args.only and meta["name"] in args.only:
            yield mod
            continue
        if meta["tier"] not in tiers:
            continue
        yield mod


def main():
    ap = argparse.ArgumentParser(description="tabp behavioral eval runner")
    ap.add_argument(
        "--plugin", default="tabp", metavar="NAME",
        help="kept for CLI compatibility when invoked via the dispatcher; "
             "default: tabp",
    )
    ap.add_argument(
        "--paid", action="store_true",
        help="also run scenarios that invoke the Cowork model (costs money)",
    )
    ap.add_argument(
        "--forge", action="store_true",
        help="also run scenarios needing a GitHub remote",
    )
    ap.add_argument(
        "--only", action="append", metavar="NAME",
        help="run only the named scenario(s); implies its tier",
    )
    ap.add_argument(
        "--keep", action="store_true",
        help="keep temp dirs for inspection",
    )
    ap.add_argument(
        "--list", action="store_true",
        help="list scenarios and exit 0",
    )
    args = ap.parse_args()

    if args.keep:
        os.environ["TABP_EVAL_KEEP"] = "1"

    scenarios = load_scenarios()

    if args.list:
        for mod in scenarios:
            m = mod.META
            print("%-28s %-6s %-4s  %s" % (
                m["name"], m["tier"], m["goal"], m["summary"],
            ))
        return 0

    # No banner for skills-only plugins (spec 03 runner design note 2;
    # test_run_evals_dispatch.py line 185 asserts banner absent).

    chosen = list(selected(scenarios, args))
    if not chosen:
        print("no scenarios selected (free tier is default; use --paid).")
        return 0

    failed = []
    for mod in chosen:
        meta = mod.META
        print("==> %s  [%s, %s]" % (meta["name"], meta["tier"], meta["goal"]))
        try:
            check = mod.run()
        except Exception:
            print("    [FAIL] scenario raised:")
            print(
                "           "
                + traceback.format_exc().replace("\n", "\n           ")
            )
            failed.append(meta["name"])
            continue
        for line in check.lines():
            print(line)
        if not check.passed:
            failed.append(meta["name"])
        print()

    print("-" * 60)
    print("scenarios: %d run, %d failed" % (len(chosen), len(failed)))
    if failed:
        print("FAILED: " + ", ".join(failed))
        return 1
    print("all passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
