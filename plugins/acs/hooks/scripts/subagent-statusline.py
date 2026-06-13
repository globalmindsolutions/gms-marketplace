#!/usr/bin/env python3
"""subagent-statusline.py — optional Claude Code agent-panel rows for acs subagents.

Claude Code invokes this once per refresh tick with ONE JSON object on stdin:

    {"columns": <usable row width>, "tasks": [{"id", "name", "type", "status",
     "description", "label", "startTime", "tokenCount", "cwd", ...}, ...]}

For every task we recognize as an acs reflection subagent
(<skill>-planner/-executor/-verifier), we emit one JSON line:

    {"id": "<task id>", "content": "<row body>"}

restyling the row as, e.g.:

    ▶ verify · code-verifier · SHOP-123 · 45k tok · 1m32s

Tasks we do not recognize get NO line — they keep Claude Code's default
rendering. We never crash and never write garbage: on any problem we emit
nothing and the panel falls back to defaults.

Wire-up (offered by /acs:init Step 7b; statusLine rules apply — user-owned,
absolute path, never forced):

    {"subagentStatusLine": {"type": "command",
                            "command": "python3 /abs/path/hooks/scripts/subagent-statusline.py"}}
"""

import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROLE_RE = re.compile(
    r"\b(create-prd|create-architecture|create-project|create-ticket|"
    r"create-design|create-spec|code|create-pr|merge-pr)-(planner|executor|verifier)\b"
)
PHASE = {"planner": "plan", "executor": "execute", "verifier": "verify"}
STATUS_GLYPH = {"running": "▶", "in_progress": "▶", "pending": "○",
                "completed": "✓", "done": "✓", "failed": "✗", "error": "✗"}


def detect_role(task):
    for key in ("type", "name", "label", "description"):
        value = task.get(key)
        if isinstance(value, str):
            match = ROLE_RE.search(value)
            if match:
                return match.group(1), match.group(2)
    return None, None


def ticket_for(task):
    """Best effort: the per-checkout pointer of the task's cwd names the ticket."""
    cwd = task.get("cwd")
    if not isinstance(cwd, str) or not cwd:
        return None
    try:
        import acs_lib as lib
        ctx = lib.build_context(cwd)
        pointer = lib.read_json(lib.pointer_path(ctx["workspace"], ctx["repo_id"], ctx["checkout_id"]))
        if isinstance(pointer, dict):
            return pointer.get("ticket_id")
    except Exception:
        pass
    return None


def elapsed(start):
    if not isinstance(start, (int, float)) or start <= 0:
        return None
    if start > 1e12:  # epoch milliseconds
        start = start / 1000.0
    seconds = int(time.time() - start)
    if seconds < 0:
        return None
    if seconds < 60:
        return "%ds" % seconds
    return "%dm%02ds" % (seconds // 60, seconds % 60)


def tokens(count):
    if not isinstance(count, (int, float)) or count <= 0:
        return None
    if count >= 1000:
        return "%.0fk tok" % (count / 1000.0)
    return "%d tok" % count


def row(task, columns):
    skill, role = detect_role(task)
    if not skill:
        return None
    glyph = STATUS_GLYPH.get(str(task.get("status") or "").lower(), "▶")
    bits = ["%s %s" % (glyph, PHASE[role]), "%s-%s" % (skill, role)]
    ticket = ticket_for(task)
    if ticket:
        bits.insert(2, ticket)
    tok = tokens(task.get("tokenCount"))
    if tok:
        bits.append(tok)
    span = elapsed(task.get("startTime"))
    if span:
        bits.append(span)
    content = " · ".join(bits)
    if isinstance(columns, int) and columns > 4 and len(content) > columns:
        content = content[: columns - 1] + "…"
    return {"id": task.get("id"), "content": content}


def main():
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return
    columns = payload.get("columns")
    for task in payload.get("tasks") or []:
        if not isinstance(task, dict) or task.get("id") in (None, ""):
            continue
        try:
            line = row(task, columns)
        except Exception:
            line = None  # never break the panel for one row
        if line:
            sys.stdout.write(json.dumps(line) + "\n")


if __name__ == "__main__":
    main()
