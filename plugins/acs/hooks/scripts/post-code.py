#!/usr/bin/env python3
"""Post-hook for /acs:code — finalizes the run entry in code-state.json and
updates pipeline-state.json, tickets-index.json, and metrics.json.

Invoked by the skill's coordinator as its mandatory final step:
  python3 post-code.py --result-file <result.json>     # or JSON on stdin
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from acs_lib import run_post

if __name__ == "__main__":
    run_post("code")
