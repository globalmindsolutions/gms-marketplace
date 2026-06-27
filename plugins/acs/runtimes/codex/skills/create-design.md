# acs:create-design — Codex CLI skill entry point (MAR-5, D1 Option B, shape a)
# First executable line: no-bypass shim calling dispatch.py pre.
# Exit 2 from dispatch.py pre blocks the coordinator body (AC-1, 0 gate escapes).
# Source: runtime-coupling-inventory.md:38; design.md:65-73.

```bash
echo '{"cwd":"'"$PWD"'","tool_input":{"skill":"acs:create-design"}}' | python3 "$ACS_PLUGIN_ROOT/hooks/scripts/dispatch.py" pre
```

Coordinator body follows — unreachable if the shim above exits non-zero.

This is the Codex CLI entry point for the `/acs:create-design` skill.
The shim synthesizes a shape-(a) payload and pipes it to `dispatch.py pre`,
reusing `skill_name_from_payload` (dispatch.py:25-38) unchanged (AC-2).

See `plugins/acs/runtimes/codex/README.md` for the Stop-handler wiring note.
