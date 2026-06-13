# autonomous-coding-skills

Claude Code agent skills for autonomous coding workflows.

## Plugin marketplace

This repository is a **Claude Code plugin marketplace** named **`gms`**
(manifest: [`.claude-plugin/marketplace.json`](.claude-plugin/marketplace.json)).
Add it and install plugins from it:

```text
claude plugin marketplace add globalmindsolutions/acs
claude plugin install acs@gms
```

(Or run `/plugin` inside a Claude Code session, add the marketplace
`globalmindsolutions/acs`, and install from the UI.)

### Updating

Releases are semver-tagged automatically when `plugins/acs/.claude-plugin/plugin.json`
bumps its `version` on `main` ([CHANGELOG](plugins/acs/CHANGELOG.md)) — consumers
receive updates **only on version bumps**. To update:

```text
claude plugin marketplace update gms     # fetch the latest plugin version
/reload-plugins                          # or start a new session
```

Or run **`/acs:update`** inside a session: it compares installed vs latest,
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
