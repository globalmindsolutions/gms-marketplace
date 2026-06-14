# Contributing

Thanks for working on **acs**. This repo dogfoods acs on itself, so the same
discipline acs applies to consumer repos applies here.

## Setup

- **Requirements:** `git`, `python3` ≥ 3.9 (stdlib only — no pip installs),
  `gh` authenticated. For paid evals: an authenticated `claude` CLI with the
  `acs` plugin installed.
- **Install the hooks once per clone:**
  ```bash
  pre-commit install
  ```
  This wires the repo's [pre-commit hooks](.pre-commit-config.yaml) (secret
  scanning, hygiene, and the `acs-free-evals` smoke) into `git commit`.

## Tests & quality

Quality is layered — see the strategy in
[docs/quality/testing-strategy.md](docs/quality/testing-strategy.md). What you'll
run day to day:

```bash
python3 -m unittest discover -s tests -v   # deterministic + contract suites (free)
python3 evals/run_evals.py                 # free behavioral smoke (gate + cleanup)
python3 evals/run_evals.py --paid          # full agentic suite — PRE-RELEASE gate ($)
```

- The **free** layers gate every commit (pre-commit) and every PR (CI). Keep
  them green — a red `acs-free-evals` hook means a gate or cleanup regression.
- The **paid** evals are a **pre-release gate**, run locally on demand (they
  cost money and are non-deterministic). Run them before bumping `version` —
  see the [release runbook](docs/operations/release-runbook.md).

## Pull requests

- Branch off `main`; never commit directly to `main` (it's protected).
- Keep commit subjects imperative; reference the ticket id when there is one.
- CI must be green (tests on 3.9 + 3.12, pre-commit, gitleaks, version
  consistency). PRs merge **squash**.
- Touching the plugin? Update the docs it affects in the same PR — acs treats
  docs as part of the change, not an afterthought.

## Where things live

- [docs/README.md](docs/README.md) — the full-SDLC doc map (product →
  requirements → architecture → adr → quality → operations).
- [plugins/acs/docs/](plugins/acs/docs/) — implementation contract for
  contributors (INTERNALS, AUTHORING).
- [docs/product/roadmap.md](docs/product/roadmap.md) — what's planned and why.

## Dogfooding

Where practical, ship changes to this repo through acs itself
(`/acs:ship <prompt>`, or step by step from `/acs:create-ticket`) — that's
Epic E3, and it's the best behavioral coverage we have.
