# autonomous-coding-skills

Claude Code agent skills for autonomous coding workflows.

## Plugin marketplace

This repository is a **Claude Code plugin marketplace** named **`gms-marketplace`**
(manifest: [`.claude-plugin/marketplace.json`](.claude-plugin/marketplace.json)).
Add it and install plugins from it. Pin the marketplace to a release tag for a
controlled rollout (recommended), or omit the tag to track the latest:

```text
# Gated: pin to an immutable marketplace release — only an explicit re-pin upgrades you
claude plugin marketplace add globalmindsolutions/gms-marketplace@marketplace-v0.1.0
claude plugin install acs@gms-marketplace

# Rolling: track the default branch — updates arrive on every plugin version bump
claude plugin marketplace add globalmindsolutions/gms-marketplace
```

(Or run `/plugin` inside a Claude Code session and install from the UI.)

For a team, pin the marketplace centrally via managed settings so members
cannot drift onto unreleased plugin versions — upgrade by changing `ref` to a
newer `marketplace-v<version>` tag:

```json
{
  "extraKnownMarketplaces": {
    "gms-marketplace": {
      "source": {
        "source": "github",
        "repo": "globalmindsolutions/gms-marketplace",
        "ref": "marketplace-v0.1.0"
      }
    }
  }
}
```

### Releasing & updating

Each plugin's version lives in its `plugin.json` and is what Claude Code uses to
detect updates; the marketplace's own top-level `version` labels the catalog.
They ship **together**: CI blocks a plugin version bump unless
`.claude-plugin/marketplace.json` `version` is bumped too, and every marketplace
bump auto-cuts an immutable `marketplace-v<version>` tag whose release notes
list the exact plugin versions it bundles ([CHANGELOG](plugins/acs/CHANGELOG.md)).
The catalog sources each plugin from its own pinned release tag (acs via
`git-subdir` at `v<version>`), so plugins are fetched remotely — individually
updatable with `claude plugin update acs` — and resolve reproducibly regardless
of which marketplace commit is fetched.

- **Pinned consumers** (recommended) never receive a plugin update without an
  explicit marketplace release: upgrade by re-pinning `ref` to a newer
  `marketplace-v<version>` tag, then reload.
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
