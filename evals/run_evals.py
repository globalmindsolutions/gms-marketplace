#!/usr/bin/env python3
"""Entry point for the per-plugin behavioral eval harness (M2 epic E1.1).

Runs scenarios from ``evals/<plugin>/scenarios/`` and reports per-assertion
pass/fail against workspace artifacts. The plugin is selected with ``--plugin``
(default: ``acs`` for backward compatibility — C-2). Free scenarios (no
``claude``) run by default; paid scenarios require ``--paid``.

    python3 evals/run_evals.py                       # acs free tier (default)
    python3 evals/run_evals.py --plugin acs          # explicit acs free tier
    python3 evals/run_evals.py --plugin acs --paid   # + claude-driven scenarios
    python3 evals/run_evals.py --plugin acs --only create_ticket_artifacts --paid
    python3 evals/run_evals.py --plugin acs --list

Exit code is non-zero if any selected scenario has a failing assertion, so it
can gate the nightly job (E1.4).
"""

import argparse
import importlib
import os
import sys
import traceback

# evals_dir is the directory containing this file (evals/).
# Adding it to sys.path lets every scenario do `from harness import Sandbox, Check`.
evals_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, evals_dir)

# NOTE: SCENARIOS is NOT imported at module scope — it is loaded after argparse
# resolves --plugin so the correct per-plugin registry is selected.

TIERS_DEFAULT = {"free"}


def load_scenarios(plugin_name):
    """Import SCENARIOS from evals/<plugin_name>/scenarios/__init__.py.

    Inserts ``evals/<plugin_name>/`` onto sys.path so that
    ``import scenarios`` resolves to the plugin-specific package.  For acs this
    gives ``evals/acs/scenarios/__init__.py``; for any other plugin it gives
    ``evals/<plugin>/scenarios/__init__.py``.

    The existing ``sys.path.insert(0, evals_dir)`` at module level keeps
    ``harness`` importable as a top-level module for any code running under
    ``evals/`` — the acs scenarios' ``from harness import Sandbox, Check``
    continues to resolve unchanged after the move.
    """
    plugin_dir = os.path.join(evals_dir, plugin_name)
    sys.path.insert(0, plugin_dir)
    try:
        # Force re-import in case a previous --plugin call cached a different
        # plugin's scenarios under the same module name.
        if "scenarios" in sys.modules:
            del sys.modules["scenarios"]
        scenarios_mod = importlib.import_module("scenarios")
    except ModuleNotFoundError as exc:
        sys.stderr.write(
            "error: cannot find scenarios package for --plugin %s "
            "(expected %s/scenarios/__init__.py): %s\n"
            % (plugin_name, plugin_dir, exc)
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
    ap = argparse.ArgumentParser(description="per-plugin behavioral eval harness")
    ap.add_argument(
        "--plugin", default="acs", metavar="NAME",
        help="select the plugin's scenario registry from evals/<NAME>/scenarios/ "
             "(default: acs — backward-compatible with bare invocation)",
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

    # Per-plugin registry discovery: load SCENARIOS from evals/<plugin>/scenarios/.
    scenarios = load_scenarios(args.plugin)

    if args.list:
        for mod in scenarios:
            m = mod.META
            print("%-28s %-6s %-4s  %s" % (m["name"], m["tier"], m["goal"],
                                            m["summary"]))
        return 0

    # Banner: only for the acs plugin (gates acs cache lookup via
    # installed_scripts_dir() so skills-only plugins reach mod.run() / --list
    # with no acs cache resolution and no hard-fail — AC-5, C-arch-4).
    if args.plugin == "acs":
        from harness import installed_scripts_dir  # noqa: E402 — acs-scoped import
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
