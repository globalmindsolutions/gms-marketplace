#!/usr/bin/env python3
"""Post-hook for /acs:merge-pr — finalizes the run entry in merge-pr-state.json and
updates pipeline-state.json, tickets-index.json, and metrics.json.

Invoked by the skill's coordinator as its mandatory final step:
  python3 post-merge-pr.py --result-file <result.json>     # or JSON on stdin

With --pr <ref> it runs the exempt non-ticket metrics-only path instead: it bumps
only the repo pr_merged metric (via update_metrics) and writes no ticket state,
index, pipeline, or archive.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import acs_lib as lib  # noqa: E402


def main():
    # Peek for --pr without disturbing run_post's own argv parsing: --pr diverts to
    # the metrics-only path; everything else falls through to the ticket post-hook.
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--pr", help="exempt non-ticket PR ref (metrics-only path)")
    known, _rest = parser.parse_known_args()
    if known.pr is not None:
        try:
            result = lib.run_post_exempt_pr(os.getcwd())
        except lib.GateError as exc:
            sys.stderr.write("acs post-merge-pr: %s\n" % exc)
            sys.exit(1)
        print(json.dumps(result))
        return
    lib.run_post("merge-pr")


if __name__ == "__main__":
    main()
