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
        string due_date "ISO-8601 date or null (NEW, MAR-8 Child 3)"
        enum size "trivial|small|standard|large (axis for derive_lane; MAR-56)"
        enum stakes "low|normal|high (axis for derive_lane; MAR-56)"
        enum lane "TRIVIAL|SMALL|STANDARD|COMPLEX (derived cache from size x stakes via derive_lane; MAR-56)"
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
        string lane "TRIVIAL|SMALL|STANDARD|COMPLEX (mirror of ticket.lane; written by update_pipeline; not declared in schema, allowed via additionalProperties)"
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

---

## tabp plugin data model

Source: `MAR-2/specs/01-tabp-state-json-schemas.md`, `MAR-1/design.md:652-722`.
Schemas: `plugins/tabp/schemas/`. All entities live in `<project>/.tabp/`
within the Cowork project folder (separate from the acs workspace partition).

```mermaid
erDiagram
    TABP_PROJECT ||--o{ TABP_RUN : "run history (append-only)"
    TABP_PROJECT ||--|| TABP_HISTORY : "history.json"
    TABP_RUN ||--o{ EVIDENCE_RECORD : "one per candidate screened"
    TABP_RUN ||--o| DECISION_RECORD : "created at sign-off"
    TABP_RUN ||--|| XLSX_SCORECARD : "cv-screening-scorecard-<role>-<date>.xlsx"
    TABP_PROJECT ||--o| TABP_SETTINGS : "tabp settings.json"
    TABP_PROJECT ||--o| TABP_LOCK : "held during active run"

    TABP_PROJECT {
        string project_folder PK "Cowork project folder path"
    }
    TABP_HISTORY {
        string project_folder FK
        array runs "append-only array of run summaries"
    }
    TABP_RUN {
        string run_id PK "run-<ISO8601>"
        string skill "screen-cvs"
        datetime started_at
        datetime ended_at
        enum status "in_progress|completed|failed|interrupted"
        string stop_reason
        enum state_write_mode "helper|instructed"
        string usage_source "cowork|claude-code|estimate|unavailable"
        number tokens_in "null if unavailable"
        number tokens_out "null if unavailable"
        number cost_usd "null if unavailable"
        string cost_basis "actual|estimate|unavailable (optional; absent = unavailable)"
        number duration_seconds
        number candidates_screened
        string jd_slug
        string scorecard_file
    }
    EVIDENCE_RECORD {
        string run_id FK
        string candidate_id PK
        string candidate_name
        array requirements "judgment+evidence per requirement"
        number score
        string band "Strong|Moderate|Weak"
        string recommendation "Recommend|Hold|Reject"
        string must_have_gate "OK|Missing:<list>"
        bool fairness_check_passed
        array bias_flags
    }
    DECISION_RECORD {
        string run_id PK,FK
        bool verification_passed
        string verification_notes
        datetime presented_at
        object sign_off "null until recruiter confirms"
    }
    XLSX_SCORECARD {
        string run_id FK
        string filename "cv-screening-scorecard-<role>-<date>.xlsx"
    }
    TABP_SETTINGS {
        string project_folder FK
        string screening_model
        string synthesis_model
        string cv_folder
        string jd_folder
        enum state_write_mode "helper|instructed"
    }
    TABP_LOCK {
        string project_folder FK
        int pid
        string hostname
        datetime created_at
    }
```

Invariants (enforced by `tabp_helper.py` at runtime, not by schema alone):

- `runs[-1]` in `history.json` is the current status of the most recent run.
- `status = "in_progress"` means the run is resumable from `.tabp/runs/<run-id>/`.
- Evidence records and the decision record are appended/updated only within an `in_progress` run.
- The lock is held while `status = "in_progress"`; stale locks are reported, not stolen.
- No entry in `history.json` or any per-run file is ever deleted; archives are never purged.

PII-minimal rule: `candidate_name` holds only a name or anonymised label. No contact
details, no protected-class attributes, no secrets in any state file
(`design.md:129-132`).
