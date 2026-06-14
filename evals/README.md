# acs behavioral eval harness (M2 epic E1)

Automated behavioral evals for the `acs` plugin: real `claude -p` sessions that
invoke acs skills end to end, asserting on the **workspace artifacts** they
produce — never on the model's prose. This is the regression net that makes
dogfooding (E3) safe.

This is the machine version of the [M2-0 validation
spike](../docs/product/m2-0-validation-spike.md), which proved the same
behaviors once, by hand. See the [roadmap](../docs/product/roadmap.md#epic-e1--behavioral-eval-harness-m2-backbone)
for E1.1–E1.4.

## Why it lives in `evals/`, not `tests/`

PR CI runs `python3 -m unittest discover -s tests`. Those tests cover the
**deterministic** layer (hooks, gates, state) by driving the Python scripts
directly — fast, free, deterministic, and safe to gate every PR.

The **paid** scenarios are different: they spawn `claude -p`, so they cost
money, need an authenticated `claude` CLI, and are non-deterministic — they must
never gate PRs, and run **locally on demand**. The **free** scenarios are
deterministic and `$0`; they run as a **pre-commit hook** (`acs-free-evals`) —
locally on commit and in the *Pre-commit hooks* CI job. Keeping all of this out
of `tests/` is what stops `unittest discover` from ever picking it up.

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
- Python ≥ 3.9, stdlib only (same as the rest of the repo).

## Run

```bash
python3 evals/run_evals.py                  # free tier (no cost)
python3 evals/run_evals.py --paid           # + claude-driven scenarios
python3 evals/run_evals.py --only create_ticket_artifacts --paid
python3 evals/run_evals.py --list
python3 evals/run_evals.py --paid --keep    # keep sandbox dirs to inspect
```

Exit code is non-zero if any selected scenario has a failing assertion.

## Pre-commit & CI

The **free** tier runs automatically as the `acs-free-evals` pre-commit hook
whenever `evals/` or `plugins/acs/` change — locally on `git commit` (run
`pre-commit install` once per clone) and in the *Pre-commit hooks* CI job — with
`ACS_EVAL_SOURCE=1` so it tests the source being committed. There is **no
dedicated eval CI workflow**; the **paid** tier is never automated and is run
locally on demand.

## Adding a scenario

1. Drop `scenarios/sNN_<name>.py` exposing:
   - `META = {"name", "tier", "goal", "summary"}`
   - `run() -> harness.Check`
2. Register it in `scenarios/__init__.py` (`SCENARIOS` list, in run order).
3. Inside `run()`, use `harness.Sandbox` for an isolated repo + workspace,
   drive behavior with `sb.gate(...)` (free) or `sb.run_skill(...)` (paid), and
   assert with `Check.ok/eq` against `sb.repo_json(...)` / `sb.ticket_json(...)`.

Assert on **artifacts**, never on prose: a scenario passes because the right
JSON state exists with the right values, not because the model said the right
thing.

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
