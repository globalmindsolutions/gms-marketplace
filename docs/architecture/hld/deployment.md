# HLD — Deployment & runtime topology

```mermaid
flowchart LR
    subgraph github["GitHub"]
        MR["globalmindsolution/gms-marketplace<br/>(marketplace repo)"]
        ACT["GitHub Actions<br/>CI: tests/acs/ + tests/tabp/<br/>(per-plugin shape-conditional validation)<br/>Release: tag on version bump"]
        PRS["Consumer-repo PRs"]
        EVALS["evals/&lt;plugin&gt;/<br/>(local only — NOT in CI)"]
    end

    subgraph machine["Developer machine"]
        CC["Claude Code<br/>(plugin host — acs)"]
        CX["Codex CLI<br/>(plugin host — acs, second runtime)"]
        CW["Cowork<br/>(plugin host — tabp)"]
        PI_ACS["Installed acs plugin<br/>~/.claude/... (full-shape)"]
        PI_ACS_CX["acs plugin shim<br/>(plugins/acs/runtimes/codex/skills/ — custom skill)"]
        PI_TABP["Installed tabp plugin<br/>Cowork environment (fuller shape: skills + helper + schemas + subagent charters)"]
        subgraph checkouts["Consumer repo checkouts"]
            CO1["main checkout"]
            CO2["worktree per ticket (parallel sessions)"]
        end
        WS["Workspace folder<br/>(outside every checkout)"]
        PY["python3 (stdlib) · git · gh · acli? · xmllint?"]
    end

    MR -- "claude plugin install acs@gms-marketplace" --> PI_ACS
    MR -- "acs:init --runtime codex (configures shim)" --> PI_ACS_CX
    MR -- "claude plugin install tabp@gms-marketplace" --> PI_TABP
    MR --- ACT
    CC --> PI_ACS
    PI_ACS -- hooks/skills --> CC
    CX --> PI_ACS_CX
    PI_ACS_CX -- "shim -> dispatch.py pre -> gate" --> CX
    CW --> PI_TABP
    PI_TABP -- skills --> CW
    CC --> CO1 & CO2
    CO1 & CO2 -- "all pipeline state" --> WS
    CC -- "gh pr create / merge" --> PRS
```

Key facts:

- **Distribution**: GitHub URL only; semver in `plugin.json`; the release
  workflow tags `v<version>` when the version bumps on `main` (updates reach
  users only on version bumps).
- **Per-plugin install paths**: acs installs into Claude Code
  (`claude plugin install acs@gms-marketplace`); tabp installs into the Cowork
  environment (`claude plugin install tabp@gms-marketplace`). Each plugin
  targets a different runtime host.
- **One workspace, many repos**: `workspace_path` is machine-local
  (`settings.local.json`, gitignored) and may serve any number of consumer
  repos — partitions are keyed by repo identity derived from the git remote,
  so every worktree of a repo shares one partition.
- **No server-side anything**: the plugins are files; all execution happens in
  the user's Claude Code / Cowork session and shell. Tracker/PR access goes
  through the user's authenticated CLIs.
- **This repo's own CI** runs the deterministic-layer suite (Python 3.9 +
  3.12), JSON/schema validation, and the prose contract tests on every PR via
  per-plugin test discovery (`tests/acs/` and `tests/tabp/`). Behavioral evals
  (`evals/<plugin>/`) run **locally only** — they make LLM calls and are not
  coupled to CI.
