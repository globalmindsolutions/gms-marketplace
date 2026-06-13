# C4 Level 1 — System Context

```mermaid
C4Context
    title acs — system context

    Person(dev, "Developer", "Invokes /acs:* skills; answers clarifications; reviews and merges PRs")

    System(acs, "acs plugin", "Agentic delivery workflow: PRD -> architecture -> tickets -> design -> specs -> TDD code -> PR -> merge")

    System_Ext(cc, "Claude Code", "Runtime: executes skills/agents, fires hook events, spawns subagents")
    System_Ext(repo, "Consumer repository", "Any git repo: source, tests, docs/product, docs/architecture")
    System_Ext(ws, "Workspace folder", "Outside the repo: per-repo/ticket pipeline state, locks, metrics")
    System_Ext(gh, "GitHub", "PRs (gh CLI), optional Projects v2 tracker, marketplace distribution")
    System_Ext(jira, "Jira", "Optional tracker (acli CLI), two-way ticket sync")

    Rel(dev, cc, "types /acs:* commands, answers questions")
    Rel(cc, acs, "loads skills/agents, fires PreToolUse / SessionEnd hooks")
    Rel(acs, repo, "reads code/docs; /code edits source on ticket branches")
    Rel(acs, ws, "all pipeline state: tickets, states, ledger, locks, metrics")
    Rel(acs, gh, "push branch, open/merge PR; sync issues/Projects")
    Rel(acs, jira, "two-way ticket sync (optional)")
```

Trust boundaries: the plugin never stores credentials — `gh` and `acli` own
authentication. The workspace is machine-local; cross-machine handoff is out
of scope (see PRD).
