# Flow — Ticket lifecycle & merge

## Status lifecycle

```mermaid
stateDiagram-v2
    [*] --> open: created (/create-ticket, child mint, import)
    open --> in_progress: first skill run starts work<br/>(child activity also flips its epic)
    in_progress --> in_review: /create-pr completed<br/>(or product-level skill records its PR)
    in_review --> done: /merge-pr completed
    done --> [*]: partition archived

    note right of in_progress
        runs[-1].status per skill:
        in_progress | completed | failed |
        interrupted | handed_off
        (gates read this, never ticket.status)
    end note
```

## Merge & archive sequence

```mermaid
sequenceDiagram
    actor Dev as Developer (after own PR review)
    participant CO as /acs:merge-pr coordinator
    participant GH as GitHub (gh CLI)
    participant POST as post-merge-pr.py
    participant WS as Workspace

    Dev->>CO: /acs:merge-pr SHOP-123
    CO->>GH: readiness: CI status, approvals, conflicts, protections
    alt not ready
        CO-->>Dev: report-only — what blocks, no auto-fix
    else ready
        CO->>GH: merge (configured strategy, default squash), then delete branch
        CO->>CO: clean worktree if one was used, then tracker sync to Done
        CO->>POST: result document
        POST->>WS: ticket done, epic auto-done when last child,<br/>clear pointers, metrics (pr merged)
        POST->>WS: move partition -> archive/SHOP-123/
        CO-->>Dev: completion report (cleanup performed, archive path)
    else mergeStateStatus == BEHIND and all other dimensions pass
        note over CO,GH: BEHIND carve-out — up to 2 update attempts (merge-update, no rebase, no force-push)
        loop up to 2 total update attempts
            CO->>GH: gh pr update-branch NUMBER (merge-update)
            alt update-branch conflict
                CO-->>Dev: report-only — "conflict updating branch — resolve and re-invoke /acs:merge-pr"
            else update succeeded
                loop poll every 15s, max 5 min
                    CO->>GH: gh pr checks NUMBER --required
                    alt all required checks pass
                        CO->>GH: merge (configured strategy, default squash), then delete branch
                        CO->>CO: clean worktree if one was used, then tracker sync to Done
                        CO->>POST: result document (protections="pass, was BEHIND — auto-updated via gh pr update-branch")
                        POST->>WS: ticket done, epic auto-done when last child,<br/>clear pointers, metrics (pr merged)
                        POST->>WS: move partition -> archive/SHOP-123/
                        CO-->>Dev: completion report (cleanup performed, archive path)
                    else BEHIND again (base advanced mid-poll)
                        note over CO: re-enter update loop if attempts < 2
                    else poll timeout (5 min elapsed)
                        CO-->>Dev: report-only — "branch updated — re-invoke /acs:merge-pr once CI passes"
                    end
                end
            end
        end
        alt 2 update attempts exhausted, still BEHIND
            CO-->>Dev: report-only — "base advanced again — re-invoke /acs:merge-pr"
        end
    end
```

Epic auto-management: **In Progress** on first child activity (skill-start),
**Done** when the last child merges (post-merge-pr checks siblings via the
index) — both performed by the deterministic layer, not prose.
