# Operations

**The release & run phase of the lifecycle — HOW the product ships and is
operated.** Where [`architecture/`](../architecture/) describes the *static*
structure (including [deployment](../architecture/hld/deployment.md)), this set
holds the *runtime procedures*: how a version is cut, how it's rolled out, how
it's observed, and what to do when something breaks.

Today these live scattered across the repo; this set is their home as they're
consolidated.

| Doc | What it holds | Status |
|-----|---------------|--------|
| Release process | Version/tag/CHANGELOG flow | currently in the [root README](../../README.md#releasing--updating) + [CHANGELOG](../../plugins/acs/CHANGELOG.md) |
| Validation runbook | Step-by-step end-to-end install/run checks | the [M2-0 validation spike](../product/m2-0-validation-spike.md) is the first such runbook |
| [observability.md](observability.md) | Metrics/status surfaces and how to read them (the `acs:metrics` dashboard, status lines — PRD goal G7) | ✅ |
| `incident-response.md` | What to do when a release misbehaves; rollback (re-pin to the previous `v<version>` tag) | planned |
| [release-runbook.md](release-runbook.md) | The consolidated release checklist (incl. the pre-release eval gate: `python3 evals/run_evals.py --paid`) and rollback | ✅ |

Release readiness traces upward: a release is cut only after the
[quality](../quality/) gate (the pre-release paid eval suite) passes.
