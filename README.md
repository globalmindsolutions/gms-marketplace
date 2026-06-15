# autonomous-coding-skills

Claude Code agent skills for autonomous coding workflows.

## Plugin marketplace

This repository is a **Claude Code plugin marketplace** named **`gms-marketplace`**
(manifest: [`.claude-plugin/marketplace.json`](.claude-plugin/marketplace.json)).
Add it and install plugins from it. Pin the marketplace to a release tag for a
controlled rollout (recommended), or omit the tag to track the latest:

```text
# Gated: pin to an immutable release tag — only an explicit re-pin upgrades you
claude plugin marketplace add globalmindsolution/gms-marketplace@v0.1.5
claude plugin install acs@gms-marketplace

# Rolling: track the default branch — updates arrive on every version bump
claude plugin marketplace add globalmindsolution/gms-marketplace
```

(Or run `/plugin` inside a Claude Code session and install from the UI.)

For a team, pin the marketplace centrally via managed settings so members
cannot drift onto unreleased versions — upgrade by changing `ref` to a
newer `v<version>` tag:

```json
{
  "extraKnownMarketplaces": {
    "gms-marketplace": {
      "source": {
        "source": "github",
        "repo": "globalmindsolution/gms-marketplace",
        "ref": "v0.1.5"
      }
    }
  }
}
```

### Releasing & updating

The catalog and the `acs` plugin share **one version**. A release bumps
`version` in both `.claude-plugin/marketplace.json` and
`plugins/acs/.claude-plugin/plugin.json` to the same value (CI enforces they
match), points the acs `git-subdir` `source.ref` at the new tag, and the Release
workflow cuts a single immutable `v<version>` tag
([CHANGELOG](plugins/acs/CHANGELOG.md)). acs is fetched remotely from that
pinned tag — individually updatable with `claude plugin update acs` — and
resolves reproducibly regardless of which marketplace commit is fetched.

**Before cutting a release** (before bumping `version`), run the behavioral eval
suite locally as a release gate — including the **paid** tier that the pre-commit
hook and CI deliberately skip (it spawns real `claude -p` sessions and costs a
few dollars):

```bash
python3 evals/run_evals.py --paid     # free + paid; needs an authenticated
                                      # claude CLI with the acs plugin installed
```

Treat a clean run as the gate; investigate any failing scenario before tagging.
The free tier alone (gate + cleanup smoke) already runs on every commit via the
`acs-free-evals` pre-commit hook — see [evals/README.md](evals/README.md).

- **Pinned consumers** (recommended) never receive an update without an
  explicit re-pin: upgrade by re-pinning `ref` to a newer `v<version>` tag,
  then reload.
- **Rolling consumers** run `claude plugin marketplace update gms-marketplace` (or start a
  new session) to fetch the latest plugin versions.

Either way, **`/acs:update`** inside a session compares installed vs latest,
summarizes the changelog delta (flagging breaking changes), refreshes the
marketplace with your consent, and runs post-update migration checks
(settings schema, status-line paths).

Its first plugin, **`acs` (Autonomous Coding Skills)**, provides a complete
agentic software-delivery workflow: from a raw request through product
definition (PRD), architecture, ticketing, design, implementation specs,
TDD implementation with an automatic review loop, pull request, and merge.
Twelve skills (`/acs:init`, `/acs:ship`, `/acs:code`, …) each run a
plan → execute → verify reflection cycle with dedicated subagents; pre/post
hooks gate every step on the recorded state of its predecessor; and all
durable state lives in a workspace folder outside the consumer repo, making
runs resumable and tickets shippable in parallel across git worktrees.

| Where | What |
|-------|------|
| [docs/](docs/README.md) | Product docs: [product/](docs/product/) (PRD, roadmap), [requirements/](docs/requirements/) (behavioral contract), [architecture/](docs/architecture/) (HLD/LLD), [adr/](docs/adr/) |
| [plugins/acs/README.md](plugins/acs/README.md) | Plugin usage: install, quick start, skill reference, configuration, troubleshooting |
| [plugins/acs/docs/INTERNALS.md](plugins/acs/docs/INTERNALS.md) | Implementation contract for contributors (lifecycle, helper CLIs, state shapes, XML rules) |
