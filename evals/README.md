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
- **E1.4 (scaffolded)** — [`evals-nightly.yml`](../.github/workflows/evals-nightly.yml).
  **Budget-safe by default:** the nightly **schedule runs only the free tier**
  ($0, deterministic) — a daily signal with no recurring spend. The **paid tier
  runs only on a manual, opt-in dispatch** (`paid: true`) when an
  `ANTHROPIC_API_KEY` secret is present, and runs the suite **once** — flake
  handling is per-scenario (e.g. `skill_triggers` re-probes a missed case), so a
  single non-deterministic miss never re-runs the whole expensive suite.

  **To run paid evals:** add an `ANTHROPIC_API_KEY` repo secret **with enough
  credit balance** (a full paid run spawns several real `claude` sessions — a few
  dollars; if the balance runs out mid-run, scenarios fail with *"Credit balance
  is too low"*), then trigger manually: Actions → *Nightly evals* → *Run
  workflow* (leave *paid* checked). To put paid evals back on the nightly
  schedule once budget allows, see the note atop the workflow file.
