# GMS Marketplace behavioral eval harness (M2 epic E1)

Per-plugin automated behavioral evals: real `claude -p` sessions (or free
deterministic smoke tests) that invoke plugin skills end to end and assert on
the **artifacts** they produce — never on the model's prose. This is the
regression net that makes dogfooding (E3) safe.

This is the machine version of the [M2-0 validation
spike](../docs/product/spikes/m2-0-validation-spike.md), which proved the same
behaviors once, by hand. See the [roadmap](../docs/product/roadmap.md#epic-e1--behavioral-eval-harness-m2-backbone)
for E1.1–E1.4.

## Directory layout

```
evals/
├── harness.py              # shared Sandbox + Check layer (acs-specific internals — see Plugin seam)
├── run_evals.py            # per-plugin dispatcher with --plugin selector
└── acs/                    # acs behavioral scenarios
    ├── __init__.py         # acs package marker
    └── scenarios/
        ├── __init__.py     # SCENARIOS registry (imports s01..s05)
        ├── s01_install_gate_smoke.py
        ├── s02_create_ticket_artifacts.py
        ├── s03_resume_and_verify.py
        ├── s04_skill_triggers.py
        └── s05_session_end.py
```

Future plugins add their own `evals/<plugin>/scenarios/` subtree; the shared
`harness.py` and `run_evals.py` at the `evals/` root remain the dispatch layer.

## Why it lives in `evals/`, not `tests/`

PR CI runs `python3 -m unittest discover -s tests`. Those tests cover the
**deterministic** layer (hooks, gates, state) by driving the Python scripts
directly — fast, free, deterministic, and safe to gate every PR.

The **paid** scenarios are different: they spawn `claude -p`, so they cost
money, need an authenticated `claude` CLI, and are non-deterministic — they must
never gate PRs, and run **locally on demand**. The **free** scenarios are
deterministic and `$0`; they run as a **pre-commit hook** (`acs-free-evals`) —
locally on commit and in the *Pre-commit hooks* CI job — with
`ACS_EVAL_SOURCE=1` so it tests the source being committed. Keeping all of this
out of `tests/` is what stops `unittest discover` from ever picking it up.

## Scenario tiers

| Tier | Spawns `claude`? | Default? | Use |
|------|------------------|----------|-----|
| `free`  | no  | yes | drive the **installed** dispatch hook through pipeline states; assert exit codes/messages. Catches packaging/release drift the unittest suite (source tree) can't see. |
| `paid`  | yes | no (`--paid`) | invoke a skill for real; assert on the artifacts the agents write. |
| `forge` | yes | no (`--forge`) | needs a GitHub remote (create-pr / merge-pr). Not yet populated. |

## Prerequisites

- **Free tier:** nothing beyond Python — it uses the installed `acs` plugin if
  present (`~/.claude/plugins/cache/...`, any marketplace name) and otherwise the
  in-repo source. Set `ACS_EVAL_SOURCE=1` to force the source tree (the
  pre-commit hook does this, to test the code being committed).
- **Paid tier:** an authenticated `claude` CLI with the `acs` plugin installed
  and a working model/API credential.
- Python >= 3.9, stdlib only (same as the rest of the repo).

## Run

`--plugin` defaults to `acs`, so bare invocations select the acs registry
(backward-compatible with the pre-commit hook entry which does not yet pass
`--plugin acs` explicitly — MAR-30 will add it):

```bash
# acs — free tier (no cost); --plugin defaults to acs
python3 evals/run_evals.py
python3 evals/run_evals.py --plugin acs          # explicit form

# acs — other tiers
python3 evals/run_evals.py --plugin acs --paid          # + claude-driven scenarios
python3 evals/run_evals.py --plugin acs --only create_ticket_artifacts --paid
python3 evals/run_evals.py --plugin acs --list
python3 evals/run_evals.py --plugin acs --paid --keep   # keep sandbox dirs to inspect
```

Exit code is non-zero if any selected scenario has a failing assertion.

## Pre-commit and CI

**Local-only policy (C-4):** behavioral/LLM evals for **all** plugins run
**locally** — never in CI. The `evals/` directory is excluded from all CI
workflows; `grep -rn "run_evals\|evals/" .github/workflows/` returns nothing
and must continue to return nothing. CI is responsible only for per-plugin
deterministic tests (`tests/<plugin>/`) and static shape checks; it never
executes evals.

The **free** tier of the acs eval runs automatically as the `acs-free-evals`
pre-commit hook whenever `evals/` or `plugins/acs/` change — locally on
`git commit` (run `pre-commit install` once per clone) and in the *Pre-commit
hooks* CI job — with `ACS_EVAL_SOURCE=1` so it tests the source being
committed. There is **no dedicated eval CI workflow**; the **paid** tier is
never automated and is run locally on demand.

## Before a release

The paid tier is the **release gate**. Before bumping the plugin `version`, run
the full suite locally and treat a clean run as a precondition for tagging:

```bash
python3 evals/run_evals.py --plugin acs --paid
```

This is the on-demand counterpart to the per-commit free smoke — it exercises
the real agentic behavior (G1–G4) that CI deliberately doesn't pay for. See the
release steps in the [root README](../README.md#releasing--updating).

## Adding a scenario

1. Drop `evals/<plugin>/scenarios/sNN_<name>.py` exposing:
   - `META = {"name", "tier", "goal", "summary"}`
   - `run() -> harness.Check`
2. Register it in `evals/<plugin>/scenarios/__init__.py` (`SCENARIOS` list, in
   run order).
3. For acs: inside `run()`, use `harness.Sandbox` for an isolated repo +
   workspace, drive behavior with `sb.gate(...)` (free) or `sb.run_skill(...)`
   (paid), and assert with `Check.ok/eq` against `sb.repo_json(...)` /
   `sb.ticket_json(...)`.
4. For a skills-only plugin (e.g. tabp): inside `run()`, drive the skill
   directly (no `Sandbox`); assert on the artifacts the skill produces. Return a
   `harness.Check` with `ok/eq` assertions.

Assert on **artifacts**, never on prose: a scenario passes because the right
JSON state exists with the right values, not because the model said the right
thing.

## Plugin seam

`harness.py` is the **shared** dispatch layer at `evals/` root. It contains two
kinds of symbols:

**acs-scoped** (only acs scenarios use these):

- `SOURCE_SCRIPTS` — path to the in-repo acs hook scripts (`plugins/acs/hooks/scripts`).
- `installed_scripts_dir()` — resolves the installed acs build in `~/.claude/plugins/cache/`.
- `Sandbox` — a throwaway consumer repo + workspace seeded with `.acs/settings.json`;
  drives the acs dispatch hook (`dispatch.py`) and asserts on acs workspace JSON
  artifacts.

**Plugin-agnostic** (any plugin can use these):

- `Check` — collects named assertions into a pass/fail report.

A **skills-only plugin** (e.g. tabp — no `.acs/`, no `hooks/scripts`, no installed
acs build) can run evals through `run_evals.py --plugin <name>` without
triggering any acs cache resolution and without hard-failing. The mechanism:

- `run_evals.py` gates the `installed_scripts_dir()` banner call behind
  `if args.plugin == "acs"`, so a skills-only plugin reaches `mod.run()` (and
  `--list`) with no acs-specific code executed.
- Skills-only scenarios import only `harness.Check` (not `Sandbox` or
  `installed_scripts_dir`), so the acs-scoped seam is never touched at runtime.

This design keeps `harness.py` and `run_evals.py` at the `evals/` root as the
shared layer without duplicating acs internals per plugin.

## Status / roadmap

- **E1.1 (done)** — scenario runner + sandbox + artifact assertions. Seeded
  with `install_gate_smoke` (free, G1) and `create_ticket_artifacts` (paid, G1).
- **E1.2 (done)** — `skill_triggers` (paid): one natural-language request per
  skill (never naming it) must route to that skill; all 12 green. The
  `trigger()` helper captures the first `Skill` call and kills the run, so the
  body never executes — each probe costs only the time-to-route.
- **E1.3 (done)** — per-goal scenarios. `resume_and_verify` (paid) seeds a
  code-ready pipeline for free, then one fresh `claude -p` `code` session — told
  only the ticket id — must resume from the workspace specs (G2), pass the
  verifier so the create-pr gate opens (G3), and keep the change under the
  ~400-line PR cap (G4, measured as the repo diff since the seed — no forge
  needed). `session_end_safety_net` (free) covers the SessionEnd abnormal-ending
  cleanup against the shipped build. With `install_gate_smoke` (G1), the harness
  now exercises G1–G4 plus cleanup.
- **E1.4 (done)** — the **free** tier is wired into
  [`.pre-commit-config.yaml`](../.pre-commit-config.yaml) as the `acs-free-evals`
  hook, so the gate + SessionEnd smoke runs on every commit touching the plugin
  or harness — locally and in the *Pre-commit hooks* CI job, `$0`, no `claude`.
  The **paid** tier stays a local, on-demand developer action (see
  [Run](#run)); flake handling is per-scenario (e.g. `skill_triggers` re-probes
  a missed case). There is no dedicated eval CI workflow — the deterministic
  free smoke at commit time replaces it.
- **MAR-28 (done)** — scenarios relocated to `evals/acs/scenarios/`; harness
  generalized with `--plugin` selector; skills-only plugin tolerance added;
  README updated.
- **MAR-32 (planned)** — `evals/tabp/` directory and `screen-cvs` behavioral
  scenario.
