# C4 Level 1 — System Context

```mermaid
C4Context
    title GMS Marketplace — system context

    Person(dev, "Developer", "Invokes /acs:* skills; answers clarifications; reviews and merges PRs")

    System(mkt, "GMS Marketplace", "Curated plugin catalog hosting heterogeneous plugins: acs (full-shape, agentic delivery workflow via Claude Code) and tabp (fuller shape: skills + helper + schemas + subagent charters + .tabp/ state, screen-CVs recruiting workflow via Cowork)")

    System_Ext(cc, "Claude Code", "Runtime: executes skills/agents, fires hook events, spawns subagents (acs targets Claude Code)")
    System_Ext(cowork, "Cowork", "Runtime: executes Cowork skills (tabp targets Cowork for screen-cvs)")
    System_Ext(repo, "Consumer repository", "Any git repo: source, tests, docs/product, docs/architecture")
    System_Ext(ws, "Workspace folder", "Outside the repo: per-repo/ticket pipeline state, locks, metrics")
    System_Ext(gh, "GitHub", "PRs (gh CLI), optional Projects v2 tracker, marketplace distribution")
    System_Ext(jira, "Jira", "Optional tracker (acli CLI), two-way ticket sync")

    Rel(dev, cc, "types /acs:* commands, answers questions")
    Rel(cc, mkt, "loads skills/agents, fires PreToolUse / SessionEnd hooks")
    Rel(mkt, cowork, "tabp screen-cvs skill dispatched via Cowork")
    Rel(mkt, repo, "reads code/docs; /code edits source on ticket branches")
    Rel(mkt, ws, "all pipeline state: tickets, states, ledger, locks, metrics")
    Rel(mkt, gh, "push branch, open/merge PR; sync issues/Projects")
    Rel(mkt, jira, "two-way ticket sync (optional)")
```

Trust boundaries: the marketplace plugins never store credentials — `gh` and
`acli` own authentication. The workspace is machine-local; cross-machine
handoff is out of scope (see PRD).
