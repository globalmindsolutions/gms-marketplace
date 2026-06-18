# acs behavioral eval subtree

This directory contains the acs-specific behavioral eval harness, runner, and
scenario registry. It is the per-plugin eval subtree introduced in MAR-33 as
part of the fully-per-plugin evals layout.

For the marketplace-level overview (why evals live here, tier policy, pre-commit
wiring, CI policy) see [`evals/README.md`](../README.md).

## Running the acs evals

### Via the top-level dispatcher (recommended)

```bash
# acs free tier (default; --plugin defaults to acs)
python3 evals/run_evals.py

# explicit plugin name
python3 evals/run_evals.py --plugin acs

# paid tier (spawns claude -p; costs money)
python3 evals/run_evals.py --plugin acs --paid

# list scenarios without running
python3 evals/run_evals.py --plugin acs --list

# run a single scenario by name (implies its tier)
python3 evals/run_evals.py --plugin acs --only install_gate_smoke

# keep sandbox temp dirs for inspection after a run
python3 evals/run_evals.py --plugin acs --paid --keep
```

### Directly (useful during scenario development)

```bash
python3 evals/acs/run_evals.py
python3 evals/acs/run_evals.py --list
python3 evals/acs/run_evals.py --paid
python3 evals/acs/run_evals.py --only install_gate_smoke
```

### Force the in-repo source tree

The pre-commit hook sets `ACS_EVAL_SOURCE=1` so it tests the source being
committed rather than a stale installed build. Use this locally too when
iterating on harness or scenario code:

```bash
ACS_EVAL_SOURCE=1 python3 evals/run_evals.py
ACS_EVAL_SOURCE=1 python3 evals/acs/run_evals.py
```

Exit code is non-zero if any selected scenario has a failing assertion.

## The acs Sandbox seam

`evals/acs/harness.py` contains the acs-specific seam between the scenario
runner and the acs plugin under test.

### `installed_scripts_dir()` and `SOURCE_SCRIPTS`

`installed_scripts_dir()` resolves the hook-scripts directory of the installed
acs build (`~/.claude/plugins/cache/<marketplace>/acs/<version>/hooks/scripts`),
picking the newest version. Falls back to the in-repo source tree
(`plugins/acs/hooks/scripts`, i.e. `SOURCE_SCRIPTS`) when no installed build is
present.

`ACS_EVAL_SOURCE=1` forces the in-repo source tree regardless of what is
installed. The `REPO_ROOT` constant is resolved as `dirname x3` from
`evals/acs/harness.py` (one more level than the former root-level location) to
reach the repo root correctly.

### `Sandbox`

`Sandbox` is a throwaway consumer repo + outside-the-repo workspace seeded with
valid `.acs/settings.json`. Use it as a context manager:

```python
from harness import Sandbox, Check  # resolves via runner sys.path

def run():
    check = Check("my_scenario")
    with Sandbox(prefix="TKT", slug="shop") as sb:
        rc, msg = sb.gate("create-ticket")          # free: drive the dispatch hook
        check.ok("gate opens", rc == 0, msg)

        result = sb.run_skill("/acs:create-ticket Add feature X")  # paid
        ticket = sb.ticket_json("TKT-1", "ticket.json")
        check.ok("ticket created", ticket["status"] == "open")
    return check
```

**`sb.gate(skill, args="")`** — runs the installed `dispatch.py pre` hook for
`/acs:<skill>`. Returns `(exit_code, stderr)`. `exit 2` means blocked; the
message says what must run first. No `claude` needed.

**`sb.run_skill(prompt, ...)`** — drives a headless `claude -p` session and
returns `{ok, result, cost_usd, num_turns, ...}`. Assert on workspace artifacts
afterwards, not on the model's text output.

**`sb.session_end()`** — runs the installed `dispatch.py session-end` hook.
Tests the abnormal-ending cleanup path.

### `Check`

`Check` collects named assertions into a pass/fail report. It is
plugin-agnostic and may be used by any plugin's scenario runner.

```python
check = Check("scenario_name")
check.ok("label", condition, "optional detail on failure")
check.eq("label", got_value, expected_value)
check.passed  # True iff all assertions passed
```

## Scenario registry

`evals/acs/scenarios/__init__.py` exposes a `SCENARIOS` list: the ordered list
of scenario modules the runner iterates. Each module exposes:

- `META` — `{"name": str, "tier": "free"|"paid"|"forge", "goal": str, "summary": str}`
- `run() -> Check` — runs the scenario and returns a `Check` with all assertions

### Adding a scenario

1. Drop `evals/acs/scenarios/sNN_<name>.py` exposing `META` and `run()`.
2. Register it in `evals/acs/scenarios/__init__.py` (`SCENARIOS` list, in run
   order).
3. Inside `run()`, import `from harness import Sandbox, Check` — the acs runner
   inserts `evals/acs/` on `sys.path` at module scope, so this resolves to
   `evals/acs/harness.py` without any path manipulation in the scenario file.
4. Assert on **artifacts** (JSON state the pipeline writes), never on the
   model's prose output.

### Current scenarios

| Name | Tier | Goal | Summary |
|------|------|------|---------|
| `install_gate_smoke` | free | G1 | Drive the installed dispatch hook through the main gate conditions |
| `create_ticket_artifacts` | paid | G1 | Run `/acs:create-ticket`; assert on ticket.json and pipeline-state.json |
| `resume_and_verify` | paid | G2–G4 | Seed code-ready state; one fresh code session must resume, pass verifier, stay under PR cap |
| `skill_triggers` | paid | routing | One NL request per skill must route to that skill (12 probes) |
| `session_end` | free | cleanup | Abnormal-ending SessionEnd hook finalizes in_progress runs correctly |
