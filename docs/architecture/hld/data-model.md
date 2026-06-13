# HLD — Data model (workspace state)

All entities are JSON files under `<workspace>/<repo-id>/`; schemas ship with
the plugin (`plugins/acs/schemas/`). Pretty-printed, atomically written,
human-auditable.

```mermaid
erDiagram
    REPO_PARTITION ||--o{ TICKET : contains
    REPO_PARTITION ||--|| TICKETS_INDEX : "indexes all tickets"
    REPO_PARTITION ||--|| COUNTERS : "id sequence"
    REPO_PARTITION ||--|| METRICS : "aggregates"
    REPO_PARTITION ||--o{ SESSION_POINTER : "one per checkout/worktree"
    TICKET ||--o{ SKILL_STATE : "one per skill that ran"
    TICKET ||--|| PIPELINE_STATE : "step ledger"
    TICKET ||--o| CLARIFICATIONS : "Q&A ledger"
    TICKET ||--o| LOCK : "held while worked"
    TICKET ||--o{ PHASE_ARTIFACT : "plan/execute/verify per iteration"
    TICKET ||--o{ TICKET : "epic -> children (both directions)"
    SKILL_STATE ||--|{ RUN_ENTRY : "append-only"

    TICKET {
        string id PK "SHOP-123"
        string title
        enum type "epic|story|task"
        string description
        array acceptance_criteria
        enum priority "critical|high|medium|low"
        string parent FK "epic id or null"
        array children
        enum status "open|in_progress|in_review|done"
        json external "tracker mapping or null"
        string assignee
        number story_points
        bool needs_design
        bool docs_only
    }
    SKILL_STATE {
        string skill PK
        string ticket_id FK
        json states "canonical keys per skill"
        array findings
        array errors
    }
    RUN_ENTRY {
        datetime started_at
        datetime ended_at
        json tokens "input/output"
        number cost_usd
        enum status "in_progress|completed|failed|interrupted|handed_off"
        string stop_reason
        string handoff_summary "when handed_off"
    }
    PIPELINE_STATE {
        string ticket_id PK
        enum flow "ticket|product"
        json steps "per-skill status/timestamps/summary"
        json totals "runs, seconds, tokens, cost"
    }
    CLARIFICATIONS {
        string ticket_id PK
        array clarifications "C-n: question, answer, source, status, rationale"
    }
    LOCK {
        string checkout_id
        int pid
        string hostname
        datetime created_at
    }
    SESSION_POINTER {
        string checkout_id PK
        string ticket_id
        string skill
    }
```

Invariants (enforced by `acs_lib` + schemas + tests):

- `runs[-1]` is the only source of current status — nothing mirrored at top level.
- Epic ↔ child links stored in **both** directions; epic status auto-managed.
- Cross-partition writes limited to the defined parent-epic updates; reads
  (e.g. a child consuming the epic's `design.md`) are allowed.
- Done partitions move to `archive/` — never deleted; the index keeps them.
