#!/usr/bin/env python3
"""dispatch.py — single hook entry point for the acs plugin.

Registered in hooks/hooks.json:
  * `dispatch.py pre`         on PreToolUse (matcher: Skill) — routes to pre-<skill>.py.
    Exit 2 from the routed script blocks the skill; its stderr explains what to run first.
  * `dispatch.py session-end` on SessionEnd — finalizes runs left in_progress by this
    checkout as `interrupted` and releases the ticket lock.

The dispatcher itself never gates: skills that are not part of the acs pipeline
(or acs skills without hooks: init, ship, handoff) pass through with exit 0.
"""

import json
import os
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

import acs_lib  # noqa: E402


def skill_name_from_payload(payload):
    tool_input = payload.get("tool_input") or {}
    for key in ("skill", "skill_name", "name", "command"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            name = value.strip()
            # plugin skills are namespaced (acs:create-ticket); strip the namespace
            if ":" in name:
                prefix, _, rest = name.partition(":")
                if prefix != "acs":
                    return None  # another plugin's skill — not ours to gate
                name = rest
            return name.lstrip("/").strip()
    return None


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "pre"
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        payload = {}

    if mode == "session-end":
        try:
            acs_lib.session_end(payload)
        except Exception as exc:  # cleanup must never break session teardown
            sys.stderr.write("acs session-end: %r\n" % exc)
        sys.exit(0)

    skill = skill_name_from_payload(payload)
    if skill not in acs_lib.HOOKED_SKILLS:
        sys.exit(0)

    script = os.path.join(SCRIPT_DIR, "pre-%s.py" % skill)
    if not os.path.isfile(script):
        sys.stderr.write("acs: missing hook script %s\n" % script)
        sys.exit(2)
    proc = subprocess.run(
        [sys.executable or "python3", script],
        input=raw.encode("utf-8"),
        capture_output=True,
        cwd=payload.get("cwd") or os.getcwd(),
        timeout=25,
    )
    if proc.stdout:
        sys.stdout.buffer.write(proc.stdout)
    if proc.stderr:
        sys.stderr.buffer.write(proc.stderr)
    sys.exit(proc.returncode)


if __name__ == "__main__":
    main()
