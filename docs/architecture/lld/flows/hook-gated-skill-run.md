# Flow — Hook-gated skill run

The core runtime flow: every hooked skill, direct invocation. (Under `/ship`
the coordinator invokes the same flow directly — see `ship-pipeline.md`.)

```mermaid
sequenceDiagram
    actor Dev as Developer
    participant CC as Claude Code
    participant D as dispatch.py (PreToolUse)
    participant PRE as pre-<skill>.py
    participant CO as Coordinator (SKILL.md)
    participant SS as skill-start.py
    participant PL as <skill>-planner
    participant EX as <skill>-executor(s)
    participant VF as <skill>-verifier
    participant POST as post-<skill>.py
    participant WS as Workspace partition

    Dev->>CC: /acs:code SHOP-123
    CC->>D: PreToolUse(Skill) payload
    D->>PRE: route by skill name (same stdin)
    alt gate fails
        PRE-->>CC: exit 2 + stderr ("run /acs:create-spec first")
        CC-->>Dev: skill blocked, actionable message
    else gate passes
        PRE-->>CC: exit 0
        CC->>CO: run SKILL.md
        CO->>SS: --skill code --args "$ARGUMENTS"
        SS->>WS: lock, pointer, in_progress run, ledger
        SS-->>CO: context JSON (settings, ticket, reconcile, models)
        opt reconcile / handoff resume
            CO->>WS: read runs[-1], phase artifacts, re-verify recorded work
        end
        loop reflection (max 3 iterations)
            CO->>PL: XML <task phase="plan">
            PL->>WS: iter-n-plan.md
            PL-->>CO: XML <result> (validated)
            opt open questions
                CO->>Dev: clarify (ledger first, record answers)
            end
            CO->>EX: XML <task phase="execute"> (parallel if file maps disjoint)
            EX->>WS: iter-n-execute.json (+ repo edits, commits)
            EX-->>CO: XML <result>
            CO->>VF: XML <task phase="verify">
            VF->>WS: iter-n-verify.md (re-runs tests/coverage/lint/e2e)
            VF-->>CO: XML <result> + findings
            CO->>WS: persist iter-n-*.xml at each boundary
        end
        CO->>WS: phases/<skill>/result.json
        CO->>POST: --result-file result.json
        POST->>WS: finalize run, ledger, index, metrics, release lock
        CO-->>Dev: standard completion report
    end
```

Failure shapes: iteration cap → `failed` with findings recorded; coverage
hard-fail → `failed`, `/create-pr` gate stays closed; crash → `in_progress`
left behind, SessionEnd marks `interrupted`, next run reconciles.

## Verify-depth scaling (MAR-58 / D4)

The iteration ceiling for the reflection loop is **lane-driven**:

- **TRIVIAL/SMALL lanes** (low/normal stakes): cap = **1** iteration — light
  verify (single verifier pass that may iterate once on blocking findings).
- **STANDARD/COMPLEX lanes** (or any high-stakes ticket): cap = **3** iterations
  — full verify (existing plan→execute→verify loop + full 11-dimension review
  + e2e when configured), unchanged.

The ceiling is determined by `verify_depth(ticket.lane, ticket.stakes)` in
`acs_lib.py` (see `VERIFY_ITERATION_CAP`). High-stakes tickets ALWAYS use full
verify regardless of size (stakes floor; AC-2).

**The verifier subagent runs in every lane as the in-loop gate (C-5).** Light
verify reduces the iteration ceiling only — the verifier always runs; there is
no inline human-approval gate. The TDD/coverage gate (Coverage hard fail) is
never trimmed by the verify-depth selection and applies in full in every lane.
