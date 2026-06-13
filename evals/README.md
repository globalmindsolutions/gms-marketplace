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

These evals are different: they spawn `claude -p`, so they **cost money, need
network + an authenticated `claude` CLI, and are non-deterministic.** They must
not gate PRs. They run on demand and in the nightly job (E1.4). Keeping them
out of `tests/` is what stops `unittest discover` from ever picking them up.

## Scenario tiers

| Tier | Spawns `claude`? | Default? | Use |
|------|------------------|----------|-----|
| `free`  | no  | yes | drive the **installed** dispatch hook through pipeline states; assert exit codes/messages. Catches packaging/release drift the unittest suite (source tree) can't see. |
| `paid`  | yes | no (`--paid`) | invoke a skill for real; assert on the artifacts the agents write. |
| `forge` | yes | no (`--forge`) | needs a GitHub remote (create-pr / merge-pr). Not yet populated. |

## Prerequisites

- `claude` CLI authenticated, and the `acs@gms-plugins` plugin installed
  (the free tier reads `~/.claude/plugins/cache/...`; it falls back to the
  in-repo source tree when no install is present).
- For `--paid`: a working model/API credential the `claude` CLI can use.
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
- **E1.2** — description-trigger evals for all 12 skills.
- **E1.3 (in progress)** — per-goal scenarios. Added `resume_and_verify`
  (paid, G2 + G3): seeds a code-ready pipeline for free, then one fresh
  `claude -p` `code` session — told only the ticket id — must resume from the
  workspace specs (G2) and pass the verifier so the create-pr gate opens (G3).
  Remaining: PR ≤ ~400 lines (G4, needs the `forge` tier) and a kill-mid-run
  scenario for the `SessionEnd` safety net.
- **E1.4** — nightly CI job (needs an API-credential secret) with
  variance/flake handling.
