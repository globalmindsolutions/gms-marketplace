#!/usr/bin/env python3
"""Pre-hook gate for /acs:create-spec — exit 0 = ready, exit 2 = blocked (see stderr)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from acs_lib import run_pre

if __name__ == "__main__":
    run_pre("create-spec")
