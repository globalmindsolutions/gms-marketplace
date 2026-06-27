# Codex CLI runtime adapter — acs plugin (MAR-5)

This directory contains the acs plugin's Codex CLI runtime artifacts.

**Design decision:** D1 Option B (no-bypass wrapper shim calling `dispatch.py pre` at the
command boundary; `design.md:65-73`, ADR-0035).  Option A (native Codex `PreToolUse` hook)
and Option C (in-coordinator self-check) are rejected — see ADR-0035.

---

## Skill definitions (`skills/`)

One file per `HOOKED_SKILL` (`acs_lib.py:43`).  The 9 hooked skills are:

| Skill | Codex skill definition |
|---|---|
| `create-prd` | `skills/create-prd.md` |
| `create-architecture` | `skills/create-architecture.md` |
| `create-project` | `skills/create-project.md` |
| `create-ticket` | `skills/create-ticket.md` |
| `create-design` | `skills/create-design.md` |
| `create-spec` | `skills/create-spec.md` |
| `code` | `skills/code.md` |
| `create-pr` | `skills/create-pr.md` |
| `merge-pr` | `skills/merge-pr.md` |

The 7 unhooked skills (`acs_lib.py:44`: `init`, `ship`, `handoff`, `update`,
`install-hooks`, `metrics`, `usage`) have **no shim** — `dispatch.py pre` already
exits 0 for non-hooked skills (`dispatch.py:57-58`).

### No-bypass authoring contract

Each skill file's **first non-blank, non-comment, non-fence executable line** is:

```bash
echo '{"cwd":"'"$PWD"'","tool_input":{"skill":"acs:<skill>"}}' | python3 "$ACS_PLUGIN_ROOT/hooks/scripts/dispatch.py" pre
```

This synthesizes a shape-(a) payload (`{"cwd": ..., "tool_input": {"skill": "acs:<skill>"}}`)
and pipes it to `dispatch.py pre`.  `dispatch.py`'s `skill_name_from_payload`
(`dispatch.py:25-38`) reads `tool_input.skill`, strips the `acs:` namespace prefix
(`dispatch.py:31-36`), and yields the bare skill name — **zero change to `dispatch.py`**
(AC-2, C-1).

Exit 2 from `dispatch.py pre` propagates via `sys.exit(proc.returncode)` (`dispatch.py:75`),
halting execution before the coordinator AGENTS.md body runs (AC-1, 0 gate escapes).

---

## Stop-handler wiring note (Surface #2)

**Surface #2 — Session termination** (`runtime-coupling-inventory.md:39`):

> "Codex `Stop` event → same `dispatch.py session-end` path."

### Wiring

In Codex CLI, the `Stop` event (session teardown) must be configured to invoke:

```bash
echo '{"cwd":"'"$PWD"'"}' | python3 "$ACS_PLUGIN_ROOT/hooks/scripts/dispatch.py" session-end
```

This is the Codex equivalent of the Claude Code `SessionEnd` hook (`hooks.json:16-26`).

`dispatch.py:49-54` branches on `mode == "session-end"` and calls
`acs_lib.session_end(payload)` (`acs_lib.py:1621`), which:
1. Finalizes any `in_progress` run for this checkout as `interrupted`.
2. Updates pipeline state and metrics.
3. Releases the ticket lock.

**No change to `dispatch.py` or `acs_lib.py`** is required — the Stop handler reuses
the same session-end path as the Claude Code runtime (AC-2).

### Configuration

Add the Stop-handler invocation to the Codex CLI project or global configuration
(analogous to `hooks.json:16-26` for Claude Code).  The `$ACS_PLUGIN_ROOT` environment
variable must resolve to the acs plugin root (the directory containing `hooks/`).

Example configuration entry (Codex CLI `~/.codex/config.toml` Stop hook):

```toml
[hooks.stop]
command = "bash -c 'echo \"{\\\"cwd\\\":\\\"$PWD\\\"}\" | python3 \"$ACS_PLUGIN_ROOT/hooks/scripts/dispatch.py\" session-end'"
timeout = 30
```

---

## Installation

Run `acs:init --runtime codex` to configure the shim and Stop-handler wiring
for a consumer repo.  (Full implementation in a future ticket; the shim files
are authored here as the no-bypass authoring contract.)
