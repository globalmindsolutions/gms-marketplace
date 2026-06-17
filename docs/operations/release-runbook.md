# Release runbook

The actionable checklist for cutting a release. The *why* and the consumer-facing
mechanics live in the [root README](../../README.md#releasing--updating); this is
the step-by-step the maintainer follows.

## Preconditions

- `main` is green (tests 3.9 + 3.12, pre-commit, gitleaks, per-entry name/version consistency).
- Working tree clean; you're on a release branch off the latest `main`.

## Steps

1. **Run the pre-release quality gate** — the paid eval suite (real `claude`
   sessions; a few dollars):
   ```bash
   python3 evals/run_evals.py --paid
   ```
   Treat a clean run as the gate. Investigate any failing scenario before
   continuing — do not tag on red. (The free smoke already ran on every commit
   via pre-commit; this adds the agentic G1–G4 + cleanup coverage.)
2. **Bump the version** — set the same `version` in both
   `.claude-plugin/marketplace.json` and
   `plugins/acs/.claude-plugin/plugin.json` (by convention both are kept in
   sync), and point the acs `git-subdir` `source.ref` at the new tag.
3. **Update the changelog** — add the matching section to
   [`plugins/acs/CHANGELOG.md`](../../plugins/acs/CHANGELOG.md) (Keep a Changelog
   format); this becomes the release notes.
4. **Open the release PR**, get CI green, and merge (squash). On merge the
   Release workflow cuts the immutable `v<version>` tag and publishes the
   release from the changelog section.
5. **Verify the tag** resolves and the plugin installs from it:
   ```bash
   claude plugin marketplace add globalmindsolution/gms-marketplace@v<version>
   claude plugin install acs@gms-marketplace
   ```

## Rollback

A release is just a tag. To roll back, **re-pin** consumers to the previous
`v<version>` tag (managed settings `ref`, or `@v<version>` on add) and reload;
then cut a fix-forward release. Never delete a published tag — pinned consumers
depend on its immutability.

## See also

- [root README — Releasing & updating](../../README.md#releasing--updating)
- [quality/testing-strategy.md](../quality/testing-strategy.md) — why the paid
  evals are the gate
- [m2-0-validation-spike.md](../product/m2-0-validation-spike.md) — the
  end-to-end install/run validation runbook
