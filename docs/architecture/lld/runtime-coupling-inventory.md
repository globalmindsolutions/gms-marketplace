# Runtime-coupling seam inventory

**Ticket:** MAR-4 — "Runtime abstraction — inventory and isolate the runtime-coupled surface"
**Committed path (stable citation target):** `docs/architecture/lld/runtime-coupling-inventory.md`
**Superseded by:** N/A — this is the canonical seam definition for the MAR-3 epic family.

> **Correction (2026-06-28).** The original Codex-CLI-equivalent entries for Surfaces
> #1–#3 below were authored from *unverified assumptions* about Codex's hook/skill/subagent
> surfaces. Those assumptions are **refuted by the official OpenAI Codex documentation**
> (Build plugins, Hooks, Agent Skills, Subagents); the affected cells and the seam-boundary
> statement are corrected in place. The corresponding MAR-5 implementation (PR #134) was
> **rejected** and the multi-runtime epic must be re-scoped against these constraints. Key
> facts: Codex exposes **no `Skill` hook matcher** and **no `SessionEnd` event**;
> `PreToolUse` is *"a guardrail rather than a complete enforcement boundary"* and fires only
> for `Bash`/`apply_patch`/MCP tools; plugin hooks run only once user-trusted, so
> **non-bypassable gating requires org-managed `requirements.toml` hooks**; Codex injects
> `${CLAUDE_PLUGIN_ROOT}` (not `$ACS_PLUGIN_ROOT`); and Codex spawns subagents **only on
> explicit request** via a distinct custom-agent format (`.codex/agents/*.toml`,
> not plugin-bundled), so the coordinator-driven reflection cycle does not port 1:1.

---

## Purpose

This document is the committed seam definition for MAR-4. It establishes the boundary
between the **runtime-coupled surface** (the five mechanisms that require a Codex CLI adapter
or shim) and the **runtime-agnostic deterministic stdlib layer** (components invoked via Bash,
reading/writing workspace JSON — unchanged on any runtime).

The seam is the target interface for the Codex CLI adapter children MAR-5 and MAR-6.
MAR-5 and MAR-6 MUST cite this exact path (`docs/architecture/lld/runtime-coupling-inventory.md`)
verbatim to satisfy AC-3.

**ADR-0001 invariant (binding):** the deterministic stdlib layer (`acs_lib.py` gating/state/ledger/
metrics/locks; all `*.schema.json` files; `acs-messages.xsd`) is semantically unchanged across any
runtime (`design.md:21,229-230`; `overview.md:37-41`). Every component in the runtime-agnostic
surface list below is governed by this invariant.

---

## 1. Runtime-coupled surfaces

These five mechanisms are specific to Claude Code and require a Codex CLI adapter. Each entry
states the surface name, the Claude Code mechanism, the verified file:line entry points, and the
**corrected** Codex CLI equivalent owned by the named child (see Correction note above — the
original "no-bypass shim" framing is refuted by the official Codex docs).

Source: `MAR-3/design.md:234-243` (reproduced exactly; anchors re-verified against the live repo
immediately before commit).

| # | Surface | Claude Code mechanism | Verified entry points | Codex CLI equivalent | Owning child |
|---|---------|----------------------|-----------------------|---------------------|--------------|
| 1 | Hook gating | `PreToolUse(Skill)` → `dispatch.py pre` → exit-2 blocks before coordinator runs | `hooks.json:3-14` (PreToolUse matcher `Skill`, command `dispatch.py pre`, timeout 30); `dispatch.py:25-38` (`def skill_name_from_payload`); `dispatch.py:41-75` (`def main()` — routes by skill, exit 2 on missing/blocked); `acs_lib.py:43` (`HOOKED_SKILLS` allowlist) | **Corrected:** Codex has **no `Skill` matcher** and `PreToolUse` is a guardrail, not an enforcement boundary. Gate via `PreToolUse` on `Bash`/`apply_patch` returning `permissionDecision:deny` (or exit 2), reusing `dispatch.py` via `${CLAUDE_PLUGIN_ROOT}`. **Best-effort by default; non-bypassable only via org-managed `requirements.toml` hooks.** (Original "no-bypass shim" is unachievable — refuted; PR #134 rejected.) | MAR-5 |
| 2 | Session termination | `SessionEnd` → `dispatch.py session-end` → `interrupted` + lock release | `hooks.json:16-26` (SessionEnd hook, command `dispatch.py session-end`, timeout 30); `dispatch.py:49-54` (session-end branch → `acs_lib.session_end`); `acs_lib.py:1621` (`def session_end`) | **Corrected:** Codex has **no `SessionEnd` event**. `Stop` is per-turn (fires at every turn end, requires JSON on stdout, `decision:block` means *continue*) — so it must **not** be mapped to `dispatch.py session-end` (that would release the lock mid-session). Session finalization / lock release on Codex is **lease / next-run-reconcile** based. | MAR-5 |
| 3 | Reflection-subagent dispatch | `Agent` tool spawns planner/executor/verifier in separate contexts; XML `<task>`/`<result>` validated against `acs-messages.xsd` | `acs-messages.xsd` (`contracts.md:6-14`); validated by `validate_xml.py`; coordinator/agent invocation is prompt-layer; file-anchored via partition (`overview.md:30,41`) | **Corrected:** Codex spawns subagents **only on explicit request** and manages orchestration itself; custom agents are `.codex/agents/*.toml` (fields `name`/`description`/`developer_instructions`) — a different format/location, **not plugin-bundled** — with `max_depth` default 1. The coordinator-driven planner/executor/verifier fan-out does **not** port 1:1. Native Codex custom-agents vs a single-agent fallback is an **open epic design decision**; the XML `<task>`/`<result>` artifact contract (`acs-messages.xsd`) stays unchanged whichever is chosen. | MAR-6 |
| 4 | Per-role model/effort | `settings.models.<role>` + `overrides` → `acs_lib.resolve_role_model` | `acs_lib.py:485-500` (`def resolve_role_model(settings, skill, role)`); config surface `settings.schema.json` `models` block (`contracts.md:51-58`) | `settings.models.codex.<role>` → `resolve_role_model` with `runtime=codex` parameter (MAR-6 adds `runtime` param); FAIL on rejected model/effort unchanged | MAR-6 |
| 5 | Cost/token sourcing | Coordinator fills `tokens`/`cost_usd` in result doc; ADR-0026 hybrid precedent | `data-model.md:46-54` (RUN_ENTRY `tokens`/`cost_usd` fields); `contracts.md:21` (result doc contract); `docs/adr/0026-tabp-hybrid-cost-sourcing.md` | `~/.codex/sessions/` token actuals if available; OpenAI pricing snapshot added; `cost_basis` label preserves auditability; `cost_basis=estimate` fallback when session token source unavailable | MAR-6/MAR-7 |

### Entry-point anchor verification record

The following table records the re-verification performed against the live repo immediately
before commit (re-verification mandate from `iter-1-plan.md:38`):

| Anchor | Entry point named | Verification |
|--------|-------------------|--------------|
| `hooks.json:3-14` | PreToolUse matcher `Skill`, command `dispatch.py pre`, timeout 30 | Line 3: `"PreToolUse": [`; line 5: `"matcher": "Skill"`; line 9: command with `dispatch.py pre`; line 10: `"timeout": 30` — confirmed |
| `hooks.json:16-26` | SessionEnd hook, command `dispatch.py session-end`, timeout 30 | Line 16: `"SessionEnd": [`; line 21: command with `dispatch.py session-end`; line 22: `"timeout": 30` — confirmed |
| `dispatch.py:25-38` | `def skill_name_from_payload(payload)` | Line 25: `def skill_name_from_payload(payload):`; function ends at line 38 — confirmed |
| `dispatch.py:41-75` | `def main()` — routes by skill, exit 2 on missing/blocked | Line 41: `def main():`; line 75: `sys.exit(proc.returncode)` — confirmed |
| `dispatch.py:49-54` | session-end branch → `acs_lib.session_end` | Line 49: `if mode == "session-end":`; line 51: `acs_lib.session_end(payload)`; line 54: `sys.exit(0)` — confirmed |
| `acs_lib.py:43` | `HOOKED_SKILLS` allowlist | Line 43: `HOOKED_SKILLS = PRODUCT_SKILLS + WORKFLOW_SKILLS` — confirmed |
| `acs_lib.py:485-500` | `def resolve_role_model(settings, skill, role)` | Line 485: `def resolve_role_model(settings, skill, role):`; function ends at line 500 — confirmed |
| `acs_lib.py:1621` | `def session_end(payload)` | Line 1621: `def session_end(payload):` — confirmed |
| `contracts.md:6-14` | XML coordinator ↔ subagent contract, `acs-messages.xsd` reference | Line 6: `## Coordinator ↔ subagent (XML, ...acs-messages.xsd...)`; lines 8-12 table; line 14: `Validation:...` — confirmed |
| `contracts.md:51-58` | Settings `models` block | Line 51: `## Settings (consumer repo)`; lines 52-58: `.acs/settings.json...models...` — confirmed |
| `data-model.md:46-54` | RUN_ENTRY `tokens`/`cost_usd` fields | Line 46: `RUN_ENTRY {`; line 49: `json tokens "input/output"`; line 50: `number cost_usd`; line 54: `}` — confirmed |

---

## 2. Runtime-agnostic surfaces

Components invoked via Bash and reading/writing workspace JSON — runtime-independent by
construction (`design.md:229-230`; `c4-component.md`). All are governed by the ADR-0001
invariant: their deterministic stdlib semantics are byte-for-byte unchanged across runtimes.

### From `design.md:244-245` (reproduced exactly)

- `acs_lib.py` — all gating/state/ledger/metrics/lock functions
- All `*.schema.json` (10 files — see Reconciliation subsection below)
- `acs-messages.xsd`
- `new-ticket.py`
- `clarify.py`
- `validate_xml.py`
- `metrics_aggregate.py`
- `metrics_render.py`
- All `pre-<skill>.py` (9 files: `pre-code.py`, `pre-create-architecture.py`,
  `pre-create-design.py`, `pre-create-prd.py`, `pre-create-project.py`,
  `pre-create-pr.py`, `pre-create-spec.py`, `pre-create-ticket.py`, `pre-merge-pr.py`)
- All `post-<skill>.py` (9 files: `post-code.py`, `post-create-architecture.py`,
  `post-create-design.py`, `post-create-prd.py`, `post-create-project.py`,
  `post-create-pr.py`, `post-create-spec.py`, `post-create-ticket.py`, `post-merge-pr.py`)

### Additionally confirmed agnostic, beyond the design list (assumption C-1)

The following scripts exist in `plugins/acs/hooks/scripts/` and are runtime-agnostic by
construction (Bash-invoked, read/write workspace JSON or partition state). The design's
`design.md:244-245` list omitted them; they are flagged here so AC-1
("every … component") holds completely.

- `skill-start.py` — acquires lock, registers `in_progress` run, writes pointer, returns
  context JSON; reads/writes workspace JSON via Bash invocation.
- `handoff.py` — finalizes `handed_off` status, releases lock, prints `continue_with`;
  reads/writes workspace JSON via Bash invocation.
- `statusline.py` — renders the pipeline statusline for coordinator context; reads workspace
  JSON via Bash invocation.
- `subagent-statusline.py` — renders the subagent statusline; reads workspace JSON via Bash
  invocation.

All four exist in `plugins/acs/hooks/scripts/` (confirmed by `ls plugins/acs/hooks/scripts/`).

---

## 3. Seam boundary statement

The seam is the line between surfaces 1–5 (runtime-coupled) and the agnostic list above.

**Runtime-coupled side (surfaces 1–5):** mechanisms that depend on a Claude Code primitive
(`PreToolUse(Skill)`, `SessionEnd`, `Agent` tool, `settings.models.<role>` resolution path,
coordinator-sourced token/cost data). These require a Codex CLI adapter — and, per the
Correction note, **not all have a Codex equivalent**: Codex has no `Skill` matcher and no
`SessionEnd`, its `PreToolUse` gates only `Bash`/`apply_patch`/MCP as a best-effort guardrail
(non-bypassable only via managed `requirements.toml`), and its subagent model diverges from the
`Agent`-tool reflection cycle.

**Runtime-agnostic side:** the entire deterministic stdlib layer — all components invoked via
Bash and reading/writing workspace JSON — is identical on both runtimes. No adapter is needed
for these; they are called by the same `python3 <script>` Bash invocations on both Claude Code
and Codex CLI.

**The adapter:** `codex_adapter.py` (delivered by Spec 02, MAR-4) is the thin stdlib glue
that sits at this seam. It reads `--runtime {claude-code,codex}` and routes to the appropriate
mechanism on each coupled surface. The agnostic stdlib side requires NO adapter — it is invoked
identically on both runtimes. The `codex_adapter.py` module uses only `argparse`/`sys` at
module level; it does NOT import `acs_lib` at load time (ADR-0001 invariant: no side effects
from the deterministic layer at adapter import).

---

## 4. Reconciliation

### A. `check-conventions.py` — ticket description vs. repo

The ticket description names `check-conventions.py` among runtime-agnostic components. There
is NO `check-conventions.py` in `plugins/acs/hooks/scripts/`. What exists is a CI template at
`plugins/acs/templates/ci/check-conventions.py` that `/acs:init` copies into the consumer repo
at `.acs/ci/check-conventions.py` (confirmed by `ls plugins/acs/templates/ci/`). It is a
consumer-repo commit-convention checker, NOT a plugin runtime component. The design's
runtime-agnostic list (`design.md:244-245`) correctly omits it.

This inventory follows the design (the real runtime files) and records this discrepancy so the
ticket-description divergence is noted rather than silently propagated into documentation.

### B. Schema count reconciliation (C-2)

The design (`design.md:21`) states "the 9 `*.schema.json` files." The repo
(`ls plugins/acs/schemas/`) has **10 `*.schema.json` files** + `acs-messages.xsd`:

| File | Type |
|------|------|
| `clarifications.schema.json` | `*.schema.json` |
| `counters.schema.json` | `*.schema.json` |
| `lock.schema.json` | `*.schema.json` |
| `metrics.schema.json` | `*.schema.json` |
| `pipeline-state.schema.json` | `*.schema.json` |
| `session-pointer.schema.json` | `*.schema.json` |
| `settings.schema.json` | `*.schema.json` |
| `skill-state.schema.json` | `*.schema.json` |
| `ticket.schema.json` | `*.schema.json` |
| `tickets-index.schema.json` | `*.schema.json` |
| `acs-messages.xsd` | XSD (separate format) |

Total: **10 `*.schema.json` files + 1 `.xsd` = 11 schema files.** The design's "9" is an
approximation. The inventory records the actual count. All 11 are runtime-agnostic.

---

## 5. Doc-set updates owned by children

The architecture doc-set currently describes Claude Code as the sole runtime. The inventory
records which files require updates when the corresponding Codex runtime mechanisms are
implemented; these edits are owned by the named child's `/acs:code` task.

**Source:** `MAR-3/design.md:402-415`. The table below references that source; this inventory
does NOT edit any of the listed files.

| Doc-set file | Required change | Owning child |
|---|---|---|
| `docs/architecture/hld/overview.md` | Replace "targets Claude Code" with second-runtime language; add Key architectural decision #5 (runtime-coupling-isolated design) | MAR-5 or MAR-6 |
| `docs/architecture/hld/c4-context.md` | Add Codex CLI as a parallel external system actor | MAR-5 |
| `docs/architecture/hld/c4-container.md` | Add Codex CLI runtime container; add `codex_adapter.py` container | MAR-5 |
| `docs/architecture/hld/c4-component.md` | Add `codex_adapter.py` component to the hook & helper layer | MAR-5 |
| `docs/architecture/hld/deployment.md` | Add Codex CLI host path to deployment diagram | MAR-5 |
| `docs/architecture/hld/tech-stack.md` | Add Codex CLI shim row; add Codex runtime adapter row | MAR-5 |
| `docs/architecture/lld/contracts.md` | Add "Hook events (Codex CLI)" section; add `models.claude-code`/`models.codex` to Settings section | MAR-5 (shim section), MAR-6 (settings section) |
| `docs/architecture/lld/flows/hook-gated-skill-run.md` | Add Codex CLI variant note after the existing Claude Code sequence diagram | MAR-5 |
| `plugins/acs/schemas/settings.schema.json` | Add `models.claude-code` and `models.codex` sub-objects (D4 Option A; activates `ci.yml:197-199`) | MAR-6 |

**Scope guard:** MAR-4 does NOT edit any of these files. Editing them before the corresponding
code exists would document behavior that has no implementation, breaking the conformance chain
(`overview.md:43-44`).
