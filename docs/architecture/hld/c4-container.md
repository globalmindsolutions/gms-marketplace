# C4 Level 2 — Containers

```mermaid
C4Container
    title acs plugin — containers

    Person(dev, "Developer")
    System_Boundary(plugin, "acs plugin (installed from this marketplace)") {
        Container(skills, "Skills", "12 x SKILL.md", "Coordinator protocols: lifecycle, reflection loop, user interaction, completion reports")
        Container(agents, "Subagents", "27 x agent .md", "Planner/executor/verifier charters per hooked skill; grounding rules; XML I/O")
        Container(hooks, "Hook & helper layer", "Python 3.9+ stdlib", "dispatch + 9 pre + 9 post hooks; skill-start, new-ticket, handoff, clarify, validate_xml, status lines; acs_lib")
        Container(schemas, "Schemas & templates", "JSON Schema / XSD / md", "9 state schemas, acs-messages.xsd, 4 description templates")
    }
    System_Ext(cc, "Claude Code runtime")
    ContainerDb_Ext(ws, "Workspace store", "Filesystem", "<workspace>/<repo>/<ticket>/ partitions + repo-level index/counters/metrics/sessions")
    System_Ext(repo, "Consumer repo")
    System_Ext(trackers, "GitHub / Jira")

    Rel(dev, cc, "/acs:*")
    Rel(cc, skills, "expands skill, runs coordinator")
    Rel(cc, hooks, "PreToolUse(Skill) -> dispatch; SessionEnd")
    Rel(skills, agents, "spawns via Agent tool (XML task)")
    Rel(skills, hooks, "skill-start / post-hook / helpers (Bash)")
    Rel(agents, ws, "phase artifacts (plan/execute/verify)")
    Rel(hooks, ws, "state files, ledger, locks, index, metrics")
    Rel(agents, repo, "executors edit source/docs on ticket branch")
    Rel(skills, trackers, "gh / acli (sync, PRs)")
    Rel(skills, schemas, "validate messages & state; render templates")
```

Container responsibilities are deliberately asymmetric: **skills/agents decide,
the hook layer records and gates** — no prose can unlock a gate, and no script
makes a judgment call.
