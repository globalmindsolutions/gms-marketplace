# Reflection & Subagent Architecture

## Coordinator–subagents pattern

The workflow is built on a **coordinator–subagents** architecture:

- For each skill invocation, a **coordinator** (the main agent running the
  skill) orchestrates dedicated **subagents**.
- The coordinator performs **dynamic decomposition**: it breaks the skill's
  work into subagent tasks based on the actual ticket/specs at hand (e.g. one
  executor task per spec), rather than a fixed, hard-coded task list.
- The coordinator MUST NOT keep conversation history between workflow steps.
  Everything a later step needs is read from JSON files in the workspace
  (see [workspace-and-state.md](workspace-and-state.md)).

## Reflection pattern: plan → execute → verify

Every workflow skill MUST apply the Reflection pattern as a
**plan–execute–verify cycle**, with a **different subagent for each phase**:

| Phase | Subagent (example for `/create-ticket`) | Responsibility |
|-------|------------------------------------------|----------------|
| Plan | `create-ticket-planner` | Analyze inputs (workspace state, repo, docs, config); produce a concrete plan for the executor. |
| Execute | `create-ticket-executor` | Carry out the plan; produce the skill's artifacts (ticket, design, specs, code, PR, merge). |
| Verify | `create-ticket-verifier` | Independently check the executor's output against the plan and the skill's quality bar; report pass/fail with findings. |

Requirements:

- The three phases MUST be separate subagents (separate context windows), so
  the verifier judges the work fresh rather than rubber-stamping its own
  output.
- On verification failure, the cycle reflects: the coordinator feeds the
  verifier's findings back into another plan/execute iteration.
  - The cycle runs at most **3 iterations**; on hitting the cap the skill
    stops and records its findings and stop reason in its state file.
- Subagent naming convention: `<skill>-planner`, `<skill>-executor`,
  `<skill>-verifier` for all six workflow skills, plus the product-level
  `/create-prd`, `/create-architecture`, and `/create-project` triples —
  27 subagents total.
- Each role's **model and reasoning effort are user-configurable** in
  `settings.json` (`models.planner` / `executor` / `verifier`, with
  per-skill overrides); unset values inherit the parent context's model and
  effort ([configuration.md](configuration.md#subagent-models)).

> **Note:** the `code-verifier` carries the broadest verification scope: in
> addition to spec conformance, tests, and coverage, it reviews the whole
> changeset (business logic, features, quality, technical standards,
> architecture, system design, security, documentation). There is no
> separate review skill — see [skills.md](skills.md).
>
> **Verifier anchoring**: a verifier judges the work against the **gated
> upstream contracts** (specs, ticket, design), never against the
> same-iteration plan — an unverified plan must not be able to certify the
> work it shaped. The plan's contribution to verification is its **verifier
> checklist** section only (a floor, never a ceiling), and verifiers never
> read executor reasoning — only artifacts.

```mermaid
flowchart TD
    CO[Coordinator] -->|XML task| PL[planner]
    PL -->|XML plan| CO
    CO -->|XML task + plan| EX[executor]
    EX -->|XML result| CO
    CO -->|XML task + result| VF[verifier]
    VF -->|XML verdict| CO
    CO -->|verdict = fail, iterations left| PL
    CO -->|verdict = pass| ST[(write state JSON via post-hook)]
```

## Coordinator ↔ subagent communication: XML

- All communication between the coordinator and subagents MUST use a defined
  **XML format** — both task assignments (coordinator → subagent) and results
  (subagent → coordinator).
- Messages MUST be **validated against a formal schema (XSD)** shipped with
  the plugin, so malformed messages fail fast instead of silently degrading
  the pipeline.
- The format SHOULD carry, at minimum: ticket id, skill, phase, task
  description, references to workspace input files, and (on the way back)
  status, findings, error details, and output file references.

**[ASSUMPTION]** Illustrative shape — the concrete schema is to be defined
during design:

```xml
<task skill="code" phase="execute" ticket-id="SHOP-123">
  <objective>Implement spec 02-api-endpoints</objective>
  <inputs>
    <file>specs/02-api-endpoints.md</file>
    <file>plan.json</file>
  </inputs>
  <constraints>
    <tdd>true</tdd>
    <coverage-target>90</coverage-target>
  </constraints>
</task>

<result skill="code" phase="execute" ticket-id="SHOP-123" status="completed">
  <outputs>
    <file>code-progress.json</file>
  </outputs>
  <findings>…</findings>
  <errors>…</errors>
  <stop-reason>…</stop-reason>
</result>
```

## File-based state instead of conversation memory

- Subagents MUST write their **states, findings, error details, and stop
  reasons** into JSON files in the workspace folder. Concretely, every phase
  writes its own artifact into `<partition>/phases/<skill>/`: the planner
  `iter-<n>-plan.md` (the complete plan), each executor
  `iter-<n>-execute[-<k>].json` (artifacts produced, repo files changed,
  commands run with outcomes), the verifier `iter-<n>-verify.md` (every check
  with evidence, every finding in detail). XML results reference these files,
  never inline their bodies.
- **Grounding**: every subagent decision, claim, and finding MUST be traceable
  to a source read or run in that task — cited file/section next to the
  statement, or the quoted command and output. A missing input is an error,
  not a guess; an unverifiable point is an explicit assumption with rationale;
  verifiers treat ungrounded plans/reports as blocking findings.
- Native **plan mode is not used** for the reflection plan phase: planners are
  spawned subagents with no user to approve a plan, and resumability comes
  from the phase artifacts plus gates. The planner's read-only discipline is
  enforced by its tool allowlist (planners/verifiers: read tools + Write
  solely for their own phase artifact; executors additionally may not spawn
  agents or invoke skills).
- The coordinator MUST persist each phase's output (plan, executor results,
  verifier verdict) to the ticket partition **at the phase boundary**,
  before starting the next phase — a context loss or crash never loses more
  than the in-flight phase
  ([workflow.md](workflow.md#resuming-a-ticket)).
- The coordinator reads these files to decide the next action; it never
  depends on having seen earlier messages.
- This makes every step **resumable** (a crashed or interrupted skill can be
  re-run and continue from recorded state) and **inspectable** (the user can
  audit any step's reasoning trail in the workspace).

## Decomposition & concurrency rules

- Decomposition is **exclusively the coordinator's job**: planner, executor,
  and verifier subagents MUST NOT spawn their own sub-subagents. This keeps
  the state files and the XML message flow predictable.
- The coordinator MAY run **multiple executors in parallel** within one
  skill (e.g. one executor per spec in `/code`), provided their outputs do
  not conflict; the verifier runs after all parallel executors complete and
  judges the combined result.
- The exact XSD is defined during design; the XML shapes in this document
  are illustrative.
