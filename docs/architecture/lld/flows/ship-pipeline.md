# Flow — /ship pipeline orchestration

`/ship` adds orchestration only: every step runs the hook-gated flow inside a
fresh subagent context, returning a compact `<handoff>`; the ledger
(`pipeline-state.json`) is the only memory `/ship` needs.

```mermaid
sequenceDiagram
    actor Dev as Developer
    participant SH as /acs:ship (coordinator)
    participant WS as pipeline-state.json
    participant ST as Step subagent (fresh context)
    participant SK as /acs:<step> (hook-gated flow)

    Dev->>SH: /acs:ship "Add wishlist support"  (or SHOP-123 to resume)
    SH->>WS: read ledger -> first incomplete step
    loop create-ticket -> [create-design] -> create-spec -> code -> create-pr
        SH->>ST: spawn with XML <task phase="coordinate"> brief<br/>(ticket id, step, partition path)
        ST->>SK: invoke Skill (PreToolUse gate fires normally)
        SK-->>ST: full run (reflection, hooks, state)
        ST-->>SH: <handoff status="..."> (~1 KB: summary, artifacts, next-step)
        alt status = needs_input
            SH->>Dev: relay <questions>
            Dev-->>SH: answers
            SH->>ST: re-spawn same task + Q/A context<br/>(step records them in the clarification ledger)
        else status = failed
            SH-->>Dev: step, summary, partition, resume command — stop
        else completed
            SH->>WS: (already updated by the step's post-hook)
        end
        note over SH: context may be cleared/compacted here — the ledger holds the pipeline
    end
    SH-->>Dev: pipeline report + "Review the PR, then /acs:merge-pr SHOP-123"
    note over Dev: merging stays a user action — /ship never invokes /acs:merge-pr
```

Properties: every hook gate still fires inside the step subagent (no bypass);
re-running `/ship <ticket>` resumes from the ledger; epic fan-out runs each
child's pipeline independently (parallel worktrees supported).
