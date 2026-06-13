#!/usr/bin/env python3
"""statusline.py — optional Claude Code status line for acs.

Renders the current ticket's pipeline at a glance, straight from workspace
state (the same files the hooks gate on — no model involvement):

    Opus 4.8 · SHOP-123 story · ✓ticket ✓design ✓spec ▶code ○pr ○merge · ~$4.21

Wire-up (offered by /acs:init, or manually) — statusLine is a USER setting,
never forced by the plugin. In ~/.claude/settings.json or
<repo>/.claude/settings.json:

    {"statusLine": {"type": "command",
                    "command": "python3 /abs/path/to/plugins/acs/hooks/scripts/statusline.py"}}

Claude Code pipes a JSON payload on stdin (model, workspace, session, cost);
we parse it defensively and NEVER crash — on any problem we print a minimal
fallback line, because a broken status line is worse than none.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

GLYPHS = {"completed": "✓", "in_progress": "▶", "failed": "✗",
          "interrupted": "⏸", "handed_off": "⏸"}
SHORT_STEPS = [("create-ticket", "ticket"), ("create-design", "design"),
               ("create-spec", "spec"), ("code", "code"),
               ("create-pr", "pr"), ("merge-pr", "merge")]


def fallback(payload):
    model = ((payload.get("model") or {}).get("display_name")) or "Claude"
    cwd = ((payload.get("workspace") or {}).get("current_dir")) or payload.get("cwd") or os.getcwd()
    return "%s · %s" % (model, os.path.basename(cwd.rstrip("/")) or cwd)


def render(payload):
    import acs_lib as lib

    cwd = ((payload.get("workspace") or {}).get("current_dir")) or payload.get("cwd") or os.getcwd()
    ctx = lib.build_context(cwd)  # raises GateError when not initialized

    pointer = lib.read_json(lib.pointer_path(ctx["workspace"], ctx["repo_id"], ctx["checkout_id"]))
    ticket_id = (pointer or {}).get("ticket_id")
    if not ticket_id:
        ticket_id, _src = lib.resolve_ticket_id(cwd, ctx["settings"], ctx["workspace"], ctx["repo_id"])
    if not ticket_id:
        return "%s · acs: no active ticket" % fallback(payload)

    tdir, archived = lib.find_ticket_partition(ctx["workspace"], ctx["repo_id"], ticket_id)
    if not os.path.isdir(tdir):
        return "%s · acs: %s (no partition)" % (fallback(payload), ticket_id)

    ticket = lib.load_ticket(tdir) or {}
    pipeline = lib.load_pipeline(tdir, ticket_id)
    steps = pipeline.get("steps", {})

    parts = []
    if pipeline.get("flow") == "product":
        for skill in lib.PRODUCT_SKILLS + ["merge-pr"]:
            if skill in steps:
                glyph = GLYPHS.get(steps[skill].get("status"), "○")
                parts.append("%s%s" % (glyph, skill.replace("create-", "")))
    else:
        needs_design = bool(ticket.get("needs_design"))
        if not needs_design and ticket.get("parent"):
            # children inherit the parent epic's design — design is not their step
            needs_design = False
        for skill, label in SHORT_STEPS:
            if skill == "create-design" and not needs_design:
                continue
            glyph = GLYPHS.get((steps.get(skill) or {}).get("status"), "○")
            parts.append("%s%s" % (glyph, label))

    cost = (pipeline.get("totals") or {}).get("cost_usd") or 0.0
    bits = [
        ((payload.get("model") or {}).get("display_name")) or "Claude",
        "%s%s%s" % (ticket_id,
                    " %s" % ticket.get("type") if ticket.get("type") else "",
                    " (archived)" if archived else ""),
        " ".join(parts) if parts else "pipeline not started",
    ]
    if cost:
        bits.append("~$%.2f" % cost)
    lock = lib.read_lock(tdir)
    if isinstance(lock, dict) and lock.get("checkout_id") not in (None, ctx["checkout_id"]):
        bits.append("🔒other session")
    return " · ".join(bits)


def main():
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        payload = {}
    try:
        print(render(payload))
    except Exception:
        # any failure (uninitialized repo, corrupt state, no git): minimal line
        try:
            print(fallback(payload))
        except Exception:
            print("Claude")


if __name__ == "__main__":
    main()
