# Usage Walkthroughs

How a developer drives `acs` day to day. Commands are typed in a Claude Code
session inside the consumer repo. Everything here follows the requirements
in the sibling files; this doc adds no new rules, it shows them in action.

## One-time setup (any repo)

```text
cd acme-shop
/init
  → scope?            project            (.acs/settings.json + gitignored .acs/settings.local.json)
  → workspace_path?   ~/acs-workspace    (must be outside the repo)
  → ticket_prefix?    SHOP               (suggested from the repo name)
  → coverage 90, merge_strategy squash, tracker local  (defaults, editable)
```

### Existing product (brownfield)

```text
/create-prd            # reverse-engineers a baseline PRD from code + docs,
                       #   asks you to confirm open points
                       # → delivery ticket SHOP-1, docs PR "[SHOP-1] Product definition"
/merge-pr SHOP-1       # after you review the PR yourself

/create-architecture   # reverse-engineers HLD (C4 1–3, data model, deployment)
                       #   + LLD (key flows you confirm), all Mermaid
                       # → delivery ticket SHOP-2, docs PR
/merge-pr SHOP-2
```

### Fresh product (greenfield)

Same as above, but `/create-prd` and `/create-architecture` *elicit* instead
of reverse-engineer, and one extra step scaffolds the repo:

```text
/create-project        # layout per the C4 containers, build config,
                       #   test framework + coverage tooling, lint, CI,
                       #   minimal green vertical slice
                       # → delivery ticket SHOP-3, bootstrap PR (CI runs on it)
/merge-pr SHOP-3
```

## Ship a feature — umbrella mode

```text
/ship Add wishlist support so customers can save products for later
```

What happens (you are asked clarifying questions along the way):

1. `/create-ticket` — analyzes the prompt against the PRD, codebase, and
   docs; creates epic `SHOP-4` with children `SHOP-5`, `SHOP-6` (you
   confirm the breakdown and `needs_design` flags). Epic flips to
   **In Progress** when work starts.
2. Per child: `/create-design` (or the child inherits the epic's design) →
   `/create-spec` → `/code` (TDD against 90% coverage, verifier review loop
   ≤3 iterations, docs + architecture updated) → `/create-pr`.
3. `/ship` **stops before merge** — it never merges for you.

Then, per PR, after your own review:

```text
/merge-pr SHOP-5       # readiness check → squash merge → delete branch →
                       #   clean worktree → ticket done (+ tracker sync) →
                       #   partition archived; epic auto-done after last child
```

## Ship a ticket — step-by-step mode

Every step is invocable on its own; hooks enforce the order:

```text
/create-ticket Fix flaky checkout total rounding     # → SHOP-7 (task)
/code SHOP-7
  ✗ pre-code.py: blocked — /create-spec has not completed for SHOP-7
/create-spec SHOP-7
/code SHOP-7                                          # TDD + review loop
/create-pr SHOP-7
/merge-pr SHOP-7
```

The ticket id argument is optional when the context is unambiguous —
resolution order is explicit argument → session context → branch name.

## Ship an existing ticket

```text
/ship SHOP-123         # continues from the first incomplete step
                       #   (ledger decides; gates re-verify)

# ticket only exists in Jira / GitHub Projects?
/create-ticket PROJ-456    # imports it: local id + external mapping,
                           #   then normal analysis/clarification
/ship SHOP-124             # ship the imported ticket
```

Interrupted or handed-off tickets resume the same way — the coordinator
reconciles recorded progress (re-runs tests for specs marked implemented)
before continuing.

## Parallel tickets with worktrees

```text
git worktree add ../shop-SHOP-5 && cd ../shop-SHOP-5
/ship SHOP-5           # session A

# meanwhile, in another terminal:
git worktree add ../shop-SHOP-6 && cd ../shop-SHOP-6
/ship SHOP-6           # session B
```

Each worktree gets its own `sessions/<checkout-id>.json` pointer; each
ticket partition is locked by its session, so the two never collide. The
workspace lives outside the repo precisely so both worktrees share one
state store.

## Long session? Hand off

```text
/handoff
  → flushed in-flight work + decisions to SHOP-5's partition
  → run entry marked handed_off, lock released
  → continue with:  /code SHOP-5   (in a fresh session)
```

Crashed or interrupted instead? Just re-run the same skill — the
coordinator sees the `in_progress` run entry and reconciles (e.g. re-runs
the tests for specs marked implemented) before continuing.

## Changing product scope

```text
/create-ticket Let customers share wishlists publicly
  → diverges from the PRD (sharing is out-of-scope) — amend the PRD?
/create-prd            # confirmed amendment → new delivery ticket + docs PR
```

## Where everything lives

| Location | Contents |
|----------|----------|
| Consumer repo | Code, `docs/product/` (PRD), `docs/architecture/` (HLD/LLD), ADRs, scaffold |
| `<workspace>/<repo>/` | `tickets-index.json`, `counters.json`, `metrics.json`, `sessions/`, `archive/`, one partition per ticket (states, specs, designs, runs with time/tokens/cost) |

Inspect progress and spend anytime: `tickets-index.json` for status across
tickets, `metrics.json` for per-repo totals, a ticket's
`pipeline-state.json` for where it stands in the pipeline.
