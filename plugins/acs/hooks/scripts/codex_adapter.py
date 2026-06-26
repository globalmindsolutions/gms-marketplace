#!/usr/bin/env python3
"""codex_adapter — thin runtime-resolution glue; the seam MAR-5 and MAR-6 extend.

Role
----
This module is the Rollout Step 1 scaffold for multi-runtime support (D2 Option A,
design.md:87-93, MAR-3/design.md:457). It resolves the ``--runtime`` flag to a
canonical runtime string ("claude-code" or "codex") and does nothing else. MAR-5
wires this into the dispatch / no-bypass shim layer; MAR-6 adds model-role routing
and settings-schema changes.

Coupled surfaces (see inventory)
---------------------------------
The runtime-coupling seam inventory is at:
    docs/architecture/lld/runtime-coupling-inventory.md
That document enumerates all runtime-coupled surfaces this adapter is the first
seam to bridge. Consult it before extending this file.

CLI contract
------------
    python3 codex_adapter.py [--runtime {claude-code,codex}]

Exits 0 and prints the resolved runtime string (one line) to stdout.
If ``--runtime`` receives a value outside {"claude-code", "codex"}, argparse
exits 2 with a message of the form:
    error: argument --runtime: invalid choice: '<value>'
    (choose from 'claude-code', 'codex')

resolve_runtime() contract
--------------------------
    def resolve_runtime(argv=None) -> str

    argv  -- optional list[str]; defaults to sys.argv[1:] when None.
             Pass an explicit list for testability without patching sys.argv.
    Returns "claude-code" or "codex".
    Absent --runtime flag returns "claude-code" (ADR-0027 back-compat default).
    Invalid value raises SystemExit (argparse standard behavior for choices).
    Side effects: none. No file I/O, no network, no acs_lib access.

ADR-0001 constraint
--------------------
This module imports ONLY argparse and sys at module level. Any future acs_lib
import MUST be inside a function body, never at the top level, so that importing
codex_adapter causes zero side effects on acs_lib state. The Claude Code pipeline
path is byte-for-byte unchanged by this module's existence.
"""

import argparse
import sys


def resolve_runtime(argv=None):
    """Resolve the --runtime flag and return the runtime string.

    Parameters
    ----------
    argv : list[str] or None
        Argument list to parse. When None, sys.argv[1:] is used.

    Returns
    -------
    str
        "claude-code" (default/absent/explicit) or "codex" (explicit).
        Raises SystemExit (code 2) via argparse on invalid choice.
    """
    parser = argparse.ArgumentParser(
        prog="codex_adapter",
        description="Resolve the --runtime flag to a canonical runtime string.",
        add_help=True,
    )
    parser.add_argument(
        "--runtime",
        choices=["claude-code", "codex"],
        default="claude-code",
        help="Target runtime (default: claude-code).",
    )
    args = parser.parse_args(argv)
    return args.runtime


def main():
    """Print the resolved runtime to stdout (one line) and exit 0."""
    print(resolve_runtime())
    sys.exit(0)


if __name__ == "__main__":
    main()
