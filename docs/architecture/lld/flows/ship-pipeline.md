# Flow — /ship pipeline orchestration

`/ship` adds orchestration only: the coordinator invokes each step's hook-gated
flow **directly** via the Skill tool in its own context, reading a compact
`<handoff>` back; the ledger (`pipeline-state.json`) is the only memory `/ship`
needs.

```mermaid
sequenceDiagram
    actor Dev as Developer
    participant SH as /acs:ship (coordinator)
    participant WS as pipeline-state.json
    participant SK as /acs:<step> (hook-gated flow)

    Dev->>SH: /acs:ship "Add wishlist support"  (or SHOP-123 to resume)
    SH->>WS: read ledger -> first incomplete step
    loop create-ticket -> [create-design] -> create-spec -> code -> create-pr
        SH->>SK: invoke Skill acs:<step> <ticket-id> directly<br/>(PreToolUse gate fires on the coordinator's call)
        SK-->>SH: full run (reflection, hooks, state) then <handoff status="..."><br/>(~1 KB: summary, artifacts, next-step)
        alt status = needs_input
            SH->>Dev: relay <questions>
            Dev-->>SH: answers
            SH->>SK: re-invoke same step directly + Q/A context<br/>(step records them in the clarification ledger)
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

Properties: every hook gate still fires on the coordinator's direct Skill call
(no bypass); re-running `/ship <ticket>` resumes from the ledger; epic fan-out
runs each child's pipeline independently (parallel worktrees supported).
