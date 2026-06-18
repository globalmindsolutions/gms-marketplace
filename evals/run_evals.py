#!/usr/bin/env python3
"""Thin dispatcher for per-plugin behavioral eval runners (M2 epic E1.1).

Parses ``--plugin`` (default ``acs``) and delegates to
``evals/<plugin>/run_evals.py``, forwarding all remaining flags verbatim.
Each per-plugin runner owns its own scenario loop, sys.path mutations, and
any plugin-specific banner — none of that lives here.

    python3 evals/run_evals.py                       # acs free tier (default)
    python3 evals/run_evals.py --plugin acs          # explicit acs free tier
    python3 evals/run_evals.py --plugin acs --paid   # + claude-driven scenarios
    python3 evals/run_evals.py --plugin acs --list

Exit code is the child runner's exit code (non-zero propagated verbatim).
"""

import argparse
import os
import subprocess
import sys

_evals_dir = os.path.dirname(os.path.abspath(__file__))


def main():
    # Peel --plugin; pass everything else through to the per-plugin runner.
    ap = argparse.ArgumentParser(
        description="per-plugin eval dispatcher",
        add_help=False,  # let the per-plugin runner own --help
    )
    ap.add_argument("--plugin", default="acs", metavar="NAME")
    args, forwarded = ap.parse_known_args()

    plugin_runner = os.path.join(_evals_dir, args.plugin, "run_evals.py")
    if not os.path.isfile(plugin_runner):
        sys.stderr.write(
            "error: no runner found for --plugin %s "
            "(expected %s)\n" % (args.plugin, plugin_runner)
        )
        sys.exit(1)

    result = subprocess.run(
        [sys.executable, plugin_runner, *forwarded],
    )
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
