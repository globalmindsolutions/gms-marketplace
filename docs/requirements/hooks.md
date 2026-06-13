# Hooks

Pre and post hooks are central to the workflow: they **gate** each skill on
the pipeline's recorded state and **persist** each skill's own state. Hooks
are what make the pipeline order enforceable without relying on the model's
memory or goodwill.

## Requirements

- Every workflow skill — and the product-level `/create-prd`,
  `/create-architecture`, and `/create-project` — MUST have a **pre-hook**
  and a **post-hook**.
- Hooks are implemented as **Python scripts**, named by convention:
  `pre-<skill>.py` and `post-<skill>.py`
  (e.g. `pre-code.py`, `post-code.py`).
- Hooks MUST read and write files only in the **workspace folder**
  (`<workspace>/<repo>/…`), resolved via the `.acs` `settings.json`
  (see [configuration.md](configuration.md)). Most access stays inside
  the ticket's own partition, but hooks also maintain the repo-level files
  (`tickets-index.json`, `metrics.json`, `sessions/`), and
  `pre-create-spec.py` MAY read the parent epic's partition to check its
  design state ([workspace-and-state.md](workspace-and-state.md)).

### Pre-hooks — readiness gating

A pre-hook runs before its skill and checks **readiness**:

- The predecessor skill's state file exists for the current ticket and
  reports **completed**.
- Required input artifacts exist (e.g. `pre-code.py` checks that specs are
  present and `/create-spec` is completed).
- Baseline checks shared by all pre-hooks: `settings.json` exists (else
  "run /init"), `workspace_path` is valid and outside the repo, and the
  `<ticket-id>` partition can be resolved. Pre-hooks also check the ticket's
  `.lock` file and exit 2 if another session holds it
  ([workspace-and-state.md](workspace-and-state.md)).

**Exit code contract:**

| Exit code | Meaning |
|-----------|---------|
| `0` | Ready — the skill proceeds. |
| `2` | **Blocked** — the skill MUST NOT run. The hook's stderr message tells the user what is missing and which skill to run first. |

Example: if `/create-spec` has not completed for ticket `SHOP-123`, then
`pre-code.py` exits 2 and `/code` stops before doing any work.

### Post-hooks — state persistence

A post-hook runs after its skill and writes the skill's state into a JSON
file in the workspace partition:

- e.g. `post-code.py` writes `code-state.json` under
  `<workspace>/<repo>/<ticket-id>/`.
- The state file MUST record at least: the states, findings, and error
  details produced during the run, plus a new entry in the append-only
  `runs` array (timestamps, tokens, cost, status, stop reason). The **last
  `runs` entry is the current state** — the next pre-hook gates on
  `runs[-1].status` ([workspace-and-state.md](workspace-and-state.md));
  nothing is mirrored at top level.
- Post-hooks also update the ticket's **`pipeline-state.json`** step ledger,
  and the repo-level **`tickets-index.json`** and **`metrics.json`**
  (working time, tokens, cost per run — see
  [workspace-and-state.md](workspace-and-state.md)).
- If the skill ends abnormally (crash, interruption), the post-hook MUST
  still write a state with status `failed` or `interrupted` — never leave
  the previous state in place silently.
- See [workspace-and-state.md](workspace-and-state.md) for the state
  file inventory and schemas.

## Hook inventory

| Skill | Pre-hook | Post-hook | Post-hook writes |
|-------|----------|-----------|------------------|
| `/create-prd` | `pre-create-prd.py` | `post-create-prd.py` | `create-prd-state.json` |
| `/create-architecture` | `pre-create-architecture.py` | `post-create-architecture.py` | `create-architecture-state.json` |
| `/create-project` | `pre-create-project.py` | `post-create-project.py` | `create-project-state.json` |
| `/create-ticket` | `pre-create-ticket.py` | `post-create-ticket.py` | `create-ticket-state.json` |
| `/create-design` | `pre-create-design.py` | `post-create-design.py` | `create-design-state.json` |
| `/create-spec` | `pre-create-spec.py` | `post-create-spec.py` | `create-spec-state.json` |
| `/code` | `pre-code.py` | `post-code.py` | `code-state.json` |
| `/create-pr` | `pre-create-pr.py` | `post-create-pr.py` | `create-pr-state.json` |
| `/merge-pr` | `pre-merge-pr.py` | `post-merge-pr.py` | `merge-pr-state.json` |

**[ASSUMPTION]** Naming above follows the `pre-code.py` / `code-state.json`
examples given in the requirements; exact names to confirm.

## Per-skill gate conditions

| Skill | Pre-hook gate (predecessor must be completed) |
|-------|-----------------------------------------------|
| `/create-prd` | `/init` done; product-level — no ticket required. |
| `/create-architecture` | `/init` done; PRD doc set exists (`prd_path`). |
| `/create-project` | `/init` done; architecture doc set exists (greenfield only). |
| `/create-ticket` | `/init` done (settings exist); no pipeline predecessor. |
| `/create-design` | `/create-ticket` completed; ticket flagged `needs_design`. |
| `/create-spec` | `/create-ticket` completed; ticket file exists; if the ticket (or its parent epic) needs design, that design is completed. |
| `/code` | `/create-spec` completed; specs exist. |
| `/create-pr` | `/code` completed **and its verifier passed** (no blocking findings) — the automatic remediation loop inside `/code` runs until this holds ([workflow.md](workflow.md#review-feedback-loop)). |
| `/merge-pr` | A PR reference is recorded: `/create-pr` completed (pipeline tickets), or the product-level skill completed with the PR reference in its state file (delivery tickets — [skills.md](skills.md#product-level-delivery-tickets)). Also **user-invoked only**. |

## Runtime & resolution rules

- **Run lifecycle**: at skill start the coordinator appends an
  **`in_progress` run entry** to the skill's state file; the post-hook
  finalizes it. A hard crash that skips the post-hook therefore still leaves
  `runs[-1].status == "in_progress"` (plus a stale `.lock`) — gates read
  "not completed" and the next run reconciles
  ([workflow.md](workflow.md#resuming-a-ticket)). A deliberate session
  handoff finalizes the entry as `handed_off` and releases the lock
  ([workflow.md](workflow.md#session-handoff)).
- **Ticket id resolution for hooks**: the coordinator writes a
  **per-checkout pointer file** at skill start —
  `<workspace>/<repo>/sessions/<checkout-id>.json` (one per repo
  checkout/worktree, so parallel sessions never clash). Hooks read it to
  resolve the current ticket; the **branch name is the fallback** when no
  pointer exists. Product-level skills create their **delivery ticket** at
  start, so their hooks resolve a normal ticket partition like any other
  skill ([skills.md](skills.md#product-level-delivery-tickets)). Skills themselves resolve via argument → session context →
  branch name ([workflow.md](workflow.md#ticket-context)).
- **Python runtime**: hooks MUST be **stdlib-only Python 3** — no pip
  installs required on consumer machines.
- **Validation**: hooks perform lightweight structural validation of the
  JSON files they read/write (required keys, enum values) in stdlib code;
  full JSON Schema validation happens at skill level
  ([workspace-and-state.md](workspace-and-state.md)).

## Event binding (resolved at implementation)

Resolved against the current Claude Code plugin hooks API (no "skill
completed" event exists):

- **Pre-hooks** bind to the **`PreToolUse`** event matching the **`Skill`**
  tool: a dispatcher (`dispatch.py pre`) extracts the skill name from the
  tool input and routes to the named `pre-<skill>.py` with the same stdin
  payload; exit 2 blocks the skill before it runs. This fires for user-typed
  slash commands and model-initiated Skill calls alike (including the steps
  `/ship` spawns).
- **Post-hooks** are invoked by the skill's **coordinator as its mandatory
  final step** (`post-<skill>.py --result-file …`) — their inputs (final
  status, findings, tokens, cost) exist only in the coordinator's context.
  Enforcement does not rely on the model: the coordinator registers an
  `in_progress` run entry at skill start (`skill-start.py`), and every
  downstream pre-hook gates on `runs[-1].status == "completed"`, so a
  skipped post-hook leaves the gate closed, never open.
- A **`SessionEnd`** hook (`dispatch.py session-end`) finalizes any run this
  checkout left `in_progress` as `interrupted` and releases its lock, so
  abnormal endings still write state.

See `plugins/acs/docs/INTERNALS.md` for the full implementation contract.
