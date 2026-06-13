# HLD — Deployment & runtime topology

```mermaid
flowchart LR
    subgraph github["GitHub"]
        MR["globalmindsolutions/acs<br/>(marketplace repo)"]
        ACT["GitHub Actions<br/>CI: tests + validation<br/>Release: tag on version bump"]
        PRS["Consumer-repo PRs"]
    end

    subgraph machine["Developer machine"]
        CC["Claude Code<br/>(plugin host)"]
        PI["Installed plugin copy<br/>~/.claude/... (per marketplace add)"]
        subgraph checkouts["Consumer repo checkouts"]
            CO1["main checkout"]
            CO2["worktree per ticket (parallel sessions)"]
        end
        WS["Workspace folder<br/>(outside every checkout)"]
        PY["python3 (stdlib) · git · gh · acli? · xmllint?"]
    end

    MR -- "claude plugin marketplace add<br/>claude plugin install acs@gms" --> PI
    MR --- ACT
    CC --> PI
    PI -- hooks/skills --> CC
    CC --> CO1 & CO2
    CO1 & CO2 -- "all pipeline state" --> WS
    CC -- "gh pr create / merge" --> PRS
```

Key facts:

- **Distribution**: GitHub URL only; semver in `plugin.json`; the release
  workflow tags `v<version>` when the version bumps on `main` (updates reach
  users only on version bumps).
- **One workspace, many repos**: `workspace_path` is machine-local
  (`settings.local.json`, gitignored) and may serve any number of consumer
  repos — partitions are keyed by repo identity derived from the git remote,
  so every worktree of a repo shares one partition.
- **No server-side anything**: the plugin is files; all execution happens in
  the user's Claude Code session and shell. Tracker/PR access goes through
  the user's authenticated CLIs.
- **This repo's own CI** runs the deterministic-layer suite (Python 3.9 +
  3.12), JSON/schema validation, and the prose contract tests on every PR.
