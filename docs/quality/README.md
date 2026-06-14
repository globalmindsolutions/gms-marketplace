# Quality

**The verify phase of the lifecycle — HOW correctness is assured.** Where
[`requirements/`](../requirements/) defines the behavior that must hold, this set
defines how that behavior is *checked*: the test strategy, what each layer
covers, and the policy that gates a release.

| Doc | What it holds | Status |
|-----|---------------|--------|
| [testing-strategy.md](testing-strategy.md) | The layered test pyramid (contract → deterministic → static → free/paid evals → runtime verifier → dogfooding), the per-skill coverage matrix, principles, and the roadmap to close the gap | ✅ |
| `test-plan.md` | Concrete per-area test plans and the pre-release checklist (currently inline in the [root README](../../README.md#releasing--updating) and [evals/README.md](../../evals/README.md)) | planned |
| `coverage-policy.md` | The measurable coverage bar (which skills need which layers; the guardrail that blocks regressions) | planned |

Verification flows from the layers above it: a `quality/` claim ("create-ticket
is behaviorally covered") must trace to a real check in
[`tests/`](../../tests/) or the [eval harness](../../evals/README.md). Assert on
artifacts, never on prose.
