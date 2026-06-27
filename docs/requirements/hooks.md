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
| `/merge-pr` | A PR reference is recorded: `/create-pr` completed (pipeline tickets), or the product-level skill completed with the PR reference in its state file (delivery tickets — [skills.md](skills.md#product-level-delivery-tickets)). |

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
  slash commands and model-initiated Skill calls alike (including the step skills
  `/ship` invokes directly).
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

## Codex CLI runtime — gate dispatch (MAR-5)

The hook gating and session-termination contracts extend to the Codex CLI runtime
via the no-bypass shim adapter (D1 Option B; ADR-0035; `design.md:65-73`).

### Pre-hook gate equivalent (Surface #1)

On Codex CLI, the `PreToolUse(Skill)` kernel event is replaced by a **no-bypass shim**
that is the mandatory first instruction in each hooked acs skill's Codex entry point
(`plugins/acs/runtimes/codex/skills/<skill>.md`).

- The shim synthesizes a Claude-Code-shaped stdin payload and pipes it to
  `dispatch.py pre` (shape a; C-1):
  ```
  echo '{"cwd":"'"$PWD"'","tool_input":{"skill":"acs:<skill>"}}' | \
      python3 "$ACS_PLUGIN_ROOT/hooks/scripts/dispatch.py" pre
  ```
- `dispatch.py pre` reuses `skill_name_from_payload` (`dispatch.py:25-38`) and the full
  `HOOKED_SKILLS` gate path (`acs_lib.py:1443-1462`) **unchanged** (AC-2, C-2).
- Exit 2 from `dispatch.py pre` propagates via `sys.exit(proc.returncode)` (`dispatch.py:75`),
  halting execution before any coordinator instruction runs (AC-1, 0 gate escapes).
- The shim is the **only** non-optional step before the coordinator body; no branch skips it.
- The 7 unhooked skills (`UNHOOKED_SKILLS`, `acs_lib.py:44`) have no shim. `dispatch.py:57-58`
  exits 0 for any skill not in `HOOKED_SKILLS`.

### Session termination (Surface #2)

The Codex `Stop` event (session teardown) must be wired to:
```
echo '{"cwd":"'"$PWD"'"}' | python3 "$ACS_PLUGIN_ROOT/hooks/scripts/dispatch.py" session-end
```
This reuses the same `dispatch.py session-end` path as the Claude Code `SessionEnd` hook
(`hooks.json:16-26`). `acs_lib.session_end` (`acs_lib.py:1621`) finalizes any `in_progress`
run as `interrupted`, updates pipeline state and metrics, and releases the ticket lock.
**Zero change** to `dispatch.py` or `acs_lib.py` is required (AC-2, C-2).

### Scope and isolation

- The deterministic stdlib gate layer (`acs_lib.py`, all `*.schema.json`, `acs-messages.xsd`)
  is semantically unchanged across runtimes (ADR-0001 invariant).
- Only the dispatch entry point is runtime-specific (AC-2); the gate logic is reused
  verbatim.
- The Claude Code path (`hooks.json`, `dispatch.py`, `acs_lib.py`, all `pre-<skill>.py`)
  is byte-for-byte unchanged.
- Surfaces #3-5 (reflection-subagent dispatch, per-role model/effort, cost/token sourcing)
  are addressed in MAR-6/MAR-7, not here.
