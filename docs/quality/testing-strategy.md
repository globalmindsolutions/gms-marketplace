# Ensuring acs skill quality — a layered testing strategy

acs skills are **agentic**: they drive non-deterministic `claude` sessions, so a
skill's *output* cannot be unit-tested the way the deterministic layer can.
Quality therefore comes from a **pyramid of layers** — cheapest and most
deterministic at the base, most expensive and least deterministic at the top.

> **The rule:** push every check as far *down* the pyramid as it will go.
> Anything assertable deterministically (structure, schema-conformance, gate
> transitions) belongs in the free layers that gate every PR. Reserve paid,
> live-agent evals for what genuinely needs a running model.

## The pyramid

| # | Layer | What it verifies | Cost / determinism | Where | Runs |
|---|-------|------------------|--------------------|-------|------|
| 1 | Structural / contract | every skill & agent is wired right — frontmatter, lifecycle-script calls, completion reports, tool restrictions, grounding, phase artifacts | free, deterministic | [tests/test_skill_contracts.py](../../tests/acs/test_skill_contracts.py) | every PR |
| 2 | Deterministic layer | gates block/advance, state/locks/counters/metrics, helper CLIs | free, deterministic | [tests/test_acs_plugin.py](../../tests/acs/test_acs_plugin.py) | every PR |
| 3 | Static validation | JSON / JSON-Schema / XSD parse, byte-compile, version consistency | free, deterministic | [ci.yml](../../.github/workflows/ci.yml) | every PR |
| 4 | Free eval smoke | the *shipped build* still installs & gates; SessionEnd cleanup | free, deterministic | `evals/` (`install_gate_smoke`, `session_end_safety_net`) | pre-commit + CI |
| 5 | Trigger evals | the *right skill fires* for a natural-language request | paid (cheap), ~deterministic w/ re-probe | `evals/skill_triggers` | on-demand |
| 6 | Artifact / behavioral evals | a *real run* produces correct workspace artifacts | paid (costly), non-deterministic | `evals/` (`create_ticket_artifacts`, `resume_and_verify`) | pre-release |
| 7 | Runtime reflection verifier | each individual run's output is correct (in-band, per-run) | part of normal use | the plan→execute→verify cycle inside every skill | every real invocation |
| 8 | Dogfooding (E3) | end-to-end quality under real use | the cost of using acs | shipping acs changes via `/acs:ship` | ongoing |
| 9 | LLM-as-judge *(not built)* | subjective quality — is the PRD/design *sound*? | paid + noisy | future | pre-release for product skills |

Layers 1–4 are free and gate every PR (and, for layer 4, every commit via the
`acs-free-evals` pre-commit hook). Layers 5–6 are the paid
[eval harness](../../evals/README.md). Layer 7 is a *runtime control*, not a test.

## Coverage today (per skill)

| Skill | Structure (1) | Gate (2) | Trigger (5) | Artifact (6) |
|-------|:---:|:---:|:---:|:---:|
| `init` | ✅ | ✅ | ✅ | — |
| `ship` | ✅ | n/a (umbrella) | ✅ | — |
| `handoff` | ✅ | n/a | ✅ | — |
| `create-prd` | ✅ | ✅ | ✅ | — |
| `create-architecture` | ✅ | ✅ | ✅ | — |
| `create-project` | ✅ | ✅ | ✅ | — |
| `create-ticket` | ✅ | ✅ | ✅ | ✅ |
| `create-design` | ✅ | ✅ | ✅ | — |
| `create-spec` | ✅ | ✅ | ✅ | ~ (seeded only) |
| `code` | ✅ | ✅ | ✅ | ✅ |
| `create-pr` | ✅ | ✅ | ✅ | — (needs forge) |
| `merge-pr` | ✅ | ✅ | ✅ | — (needs forge) |

**The gap is behavioral (artifact) coverage:** only 2 of 12 skills are verified
at the output level. Structure, gating, and routing are covered for all 12 — so
the *common* skill bugs (a missing script reference, a malformed completion
report, a broken gate, the wrong skill firing) are already caught cheaply.

## Principles

1. **Assert artifacts, never prose.** A scenario passes because the right JSON
   state exists with the right values — not because the model "said" the right
   thing. Validate produced artifacts against
   [`plugins/acs/schemas/*.schema.json`](../../plugins/acs/schemas/).
2. **Push checks down the pyramid.** Prefer a deterministic assertion (layers
   1–4) over a paid eval whenever the property is structural.
3. **One run, many assertions.** The live-agent run is the expensive part —
   once you've paid for it, validate *everything* about its output (schema
   conformance + completeness + gate progression), not just one field.
4. **The verifier is the runtime gate; tests are the regression net.** The
   reflection verifier catches a bad run in the moment; evals catch a regression
   in the skill across changes. They are complementary, not redundant.
5. **Cost-aware tiering.** Free tiers gate every commit/PR; the paid suite is a
   **pre-release gate** (`python3 evals/run_evals.py --paid` before tagging).
   Never put paid evals on a per-commit or scheduled path.

## Roadmap to close the gap (prioritized by value ÷ cost)

1. **Schema-validate produced artifacts** *(cheap, broad, mostly free).* Add a
   harness helper that validates any workspace JSON against its schema; call it
   in every artifact scenario and in the deterministic seeds. Turns "is the
   output good?" into "is it well-formed and complete?" — deterministically.
2. **Coverage matrix + guardrail** *(cheap).* Keep the table above current and
   add a contract test that fails if a new skill ships without at least a
   trigger eval, so coverage cannot silently regress.
3. **Fill critical-path artifact evals** *(paid, pre-release).* In order:
   `create-spec` (real run), a **forge tier** for `create-pr` + `merge-pr`
   (throwaway GitHub repo), then `ship` end-to-end — covering the delivery spine.
4. **LLM-as-judge for subjective skills** *(paid).* Rubric-scored evals for
   `create-prd` / `create-architecture` / `create-design`, whose quality is
   about content soundness rather than artifact shape.
5. **Dogfooding as standing coverage (E3).** Every acs change shipped via
   `/acs:ship` is a real behavioral test; per-ticket metrics surface regressions.

## See also

- [evals/README.md](../../evals/README.md) — the harness, cost tiers, how to add a scenario
- [tests/](../../tests/) — the deterministic + contract suites
- [docs/product/roadmap.md](../product/roadmap.md) — Epic **E1** (eval harness) and **E3** (dogfood)
