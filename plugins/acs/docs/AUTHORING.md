# Authoring guide — skills & subagents

Best practices for writing and changing the `acs` plugin's SKILL.md files and
agent definitions. The binding *contract* (lifecycle, file shapes, canonical
keys) lives in [INTERNALS.md](INTERNALS.md); this guide is about writing the
components well. The business requirements in the repo's `docs/` folder always
win — change them first, then the implementation.

## Skill definitions (`skills/<name>/SKILL.md`)

### Frontmatter

| Field | Rule |
|-------|------|
| `name` | Equals the directory name, kebab-case. Users invoke `/acs:<name>`. |
| `description` | 1–2 sentences: what it does **and when to use it** — this text is what drives model auto-invocation, so write the trigger condition into it ("Use when …"). Keep it under ~2 lines; details belong in the body. |
| `argument-hint` | Always set for skills taking arguments (`"[ticket-id]"`, `"<request or remote-key>"`). |
| `disable-model-invocation` | `true` **only** for user-action-only skills (`update`). Everything else stays model-invocable — `/ship` invokes each step skill via the Skill tool. |
| `disallowed-tools` | `Edit, NotebookEdit` on every hooked skill and `/ship`: coordinators orchestrate — they Write workspace files but never edit repo source themselves (a fix is a remediation iteration through the executor, not a coordinator hot-patch). `/init` and `/handoff` stay unrestricted (user-present utility skills; `/init` legitimately edits `.gitignore`). |
| `model` / `effort` / `context` / `agent` | **Do not set.** Hooked skills must run in the invoking context so they can talk to the user; `context: fork` would break clarifying questions. Model/effort for *subagents* comes from `settings.json`, not frontmatter. |

### Body

1. **Address the coordinator, imperatively.** "You are the coordinator of
   `/acs:<skill>`. … Run X. If Y, stop and report Z." No narrative prose, no
   options left to taste.
2. **Deterministic work belongs in scripts, not prose.** Anything a Python
   script can decide (gating, id allocation, state writes, locking) is done by
   `hooks/scripts/*` — the SKILL.md *calls* the script and parses its JSON. If
   you find yourself writing "carefully update the JSON so that …", add a
   helper script instead. Order is enforced by hooks, never by asking the
   model to behave.
3. **Follow the hooked-skill skeleton** (INTERNALS.md lifecycle) section by
   section: Start → Resume & reconcile → Reflection loop → User interaction →
   Context pressure → Finish. The Finish section must make the post-hook call
   unconditional — including on failure.
4. **Exact commands, exact paths.** Every command is copy-runnable with
   `${CLAUDE_PLUGIN_ROOT}` paths; every artifact has its partition-relative
   path spelled out. A SKILL.md with a "TODO" or an ambiguous path is a bug.
5. **State lives in the workspace, never in conversation.** A skill must work
   in a fresh session from workspace state alone. If an instruction depends on
   "what was said earlier", rewrite it to read a state file — and make sure
   something wrote that file.
6. **Plan for the headless case.** Any point where you would ask the user must
   specify the `/ship` behavior too: return a `<handoff status="needs_input">`
   with `<questions>` instead of guessing.
7. **Length budget 180–330 lines.** Shorter usually means missing failure
   paths; longer usually means prose that belongs in INTERNALS.md or a script.
8. **Failure paths are first-class.** Iteration cap, coverage hard-fail,
   blocked gates, lock contention, dirty resume — each needs an explicit
   instruction (status, stop_reason, what to tell the user).
9. **End with the standard completion report.** Every skill closes with a
   "Completion report (normative)" section instantiating the standard block
   from INTERNALS.md — same labels, same order, every terminal status,
   rendered only after the post-hook succeeded. Only the Results/Next content
   is skill-specific; under `/acs:ship` the `<handoff>` XML replaces it.

## Subagent definitions (`agents/<skill>-<role>.md`)

### Frontmatter

| Field | Rule |
|-------|------|
| `name` | `<skill>-<role>`, role ∈ planner/executor/verifier. Never reuse an agent across skills — the per-skill charter is the point. |
| `description` | One sentence: role, owning skill, and "Spawned by the /acs:<skill> coordinator with an XML task; not for direct invocation." |
| `tools` | Planner/verifier: `Read, Glob, Grep, Bash, Write` (Write *solely* for their own `phases/<skill>/` artifact — restate this in the body; Bash is for read-only inspection and running tests/builds). The allowlist deliberately omits `Agent` and `Skill`. Executor: omit `tools` (it needs broad file/shell access) but set `disallowedTools: Agent, Skill` — decomposition is the coordinator's job, and a skill invocation from inside an executor would re-enter the hook pipeline. |
| `disallowedTools` | `Agent, Skill` on every executor (see above). |
| `model` / `effort` | **Never set.** The coordinator resolves `settings.json` `models.<role>` / `models.overrides.<skill>.<role>` and applies them at spawn; frontmatter values would silently fight user configuration. |

### Body (the system prompt)

1. **One phase, one charter.** State what this role does *for this skill* —
   not generic "you are a planner" filler. The three roles must be
   meaningfully different; if a planner and verifier body read the same, the
   verifier will rubber-stamp.
2. **Spell out the I/O contract.** Input: an XML `<task>` (objective, file
   `<inputs>`, constraints, prior-iteration findings in `<context>`). Output:
   the **final message is only** an XML `<result>` per
   `schemas/acs-messages.xsd` — nothing after it. Malformed XML gets
   re-requested once, then the run fails; don't make the coordinator parse
   prose.
3. **Mandate the phase artifact.** Planner writes `iter-<n>-plan.md`,
   executor `iter-<n>-execute[-<k>].json`, verifier `iter-<n>-verify.md`
   (see INTERNALS.md "Phase artifacts") and references it in `<outputs>`.
   Resumption depends on these files existing even when the run dies right
   after the phase.
4. **No memory assumptions.** The subagent shares nothing with the
   coordinator: every fact it needs must come from `<inputs>` file paths it
   reads itself. Never write "as discussed" or rely on the ticket being "the
   current one" — the ticket id is in the task.
5. **No sub-subagents, no scope creep.** Decomposition is the coordinator's
   job; a subagent that spawns agents or "helpfully" fixes things outside its
   phase breaks the audit trail. Executors change only what the plan covers.
6. **Grounding is mandatory.** Every agent body ends with the standard
   "Grounding (anti-hallucination)" section (identical wording across all 27 —
   copy it from any existing agent): every decision/claim/finding cites the
   file (path + line/section) or quotes the command output it rests on;
   nothing unobserved is asserted; missing inputs go to `<errors>`;
   unverifiable points are flagged as assumptions, never silently defaulted.
   Verifiers treat ungrounded plan/execute artifacts as findings.
7. **Verifiers: independence is the value.** List every check dimension for
   the skill explicitly (e.g. the code-verifier's eight review dimensions plus
   spec conformance, tests, coverage). Re-run cheap checks rather than
   trusting recorded results. All findings block — write findings the
   executor can act on (file, expectation, observed behavior), one
   `<finding>` per issue, full detail in the verify report.
8. **Length budget 60–140 lines** per agent (the grounding section counts).

## Tool-restriction policy (summary)

| Component | Restriction | Enforces |
|-----------|-------------|----------|
| Hooked skills + `/ship` | `disallowed-tools: Edit, NotebookEdit` | coordinators orchestrate; only executors mutate sources |
| `/init`, `/handoff` | none | user-present utility skills |
| Planners / verifiers | `tools: Read, Glob, Grep, Bash, Write` | read-only discipline + own phase artifact; no spawning, no skill calls |
| Executors | `disallowedTools: Agent, Skill` | no sub-subagents; no re-entering the hook pipeline |

Be honest about what this buys: with Bash granted (planners need read commands,
verifiers must run tests/builds, executors run everything), these lists are
**guardrails against accidental scope creep, not a sandbox** — a shell can
touch anything. The *enforced* boundaries remain the deterministic layer:
pre-hook gates, locks, and the fact that a skipped post-hook leaves the next
gate closed. Tighten tool lists for signal and accident-prevention; never
rely on them for ordering or safety guarantees.

## Cross-cutting rules

- **Clarification ledger.** All requirement Q&A goes through
  `clarify.py` into `<partition>/clarifications.json` (see INTERNALS.md
  "Requirement clarification"): research first, ask once at the cheapest
  phase, record everything, assumptions are visible debt. A skill that asks
  the user something the ledger already answers — or acts on an answer
  without recording it — is defective.
- **Altitude boundaries between pipeline artifacts.** Each artifact owns one
  altitude and does not duplicate the next one down: the ticket owns the WHY
  and acceptance criteria; `design.md` owns options/decision/architecture;
  specs own the WHAT — contracts, API/data changes, acceptance-level test
  plan, scope boundary (indicative paths at most); the `/code` plan owns the
  HOW — the authoritative file map, executor decomposition, concrete failing
  tests, commands. Downstream phases trust gated upstream artifacts (the gate
  already verified them) and re-litigate only on contradiction with reality.

- **Namespaced invocations everywhere** users/models will type them:
  `/acs:ship`, not `/ship`.
- **Schema changes are additive.** State files tolerate unknown keys; never
  rename canonical `states` keys (INTERNALS.md table) without migrating every
  reader (gates in `acs_lib.py`, downstream SKILL.mds, tests).
- **Plan mode:** never instruct skills or agents to enter native plan mode —
  see INTERNALS.md "Why not Claude Code's native plan mode".
- **Test the deterministic layer.** Any change to `hooks/scripts/*` needs a
  test in `tests/` (`python3 -m unittest discover -s tests`); CI also
  byte-compiles scripts and checks every SKILL.md / agent file has
  `name` + `description` frontmatter.
- **Keep docs honest.** A behavior change updates, in this order: `docs/`
  requirements (+ decision-log row) → INTERNALS.md contract → SKILL.md /
  agents → tests → CHANGELOG.md.
