# GMS Marketplace

A curated catalog of Claude plugins for agentic and AI-assisted workflows.

## Prerequisites

- **Claude Code** (for the `acs` plugin) — install per the
  [official guide](https://docs.claude.com/en/docs/claude-code/overview), then
  confirm the `claude` CLI is on your `PATH` (`claude --version`).
- **Claude Cowork** (for the `tabp` plugin) — `tabp` is a Cowork plugin; install
  it from a Cowork session.
- Each plugin has its own runtime tools (e.g. `acs` needs `git`, `python3` 3.9+,
  and an authenticated `gh`). See the per-plugin READMEs linked below for the
  full list.

Not sure which plugin you want? **`acs`** automates the coding workflow inside
**Claude Code**; **`tabp`** screens CVs inside **Claude Cowork**.

## Plugin marketplace

This repository is a **Claude Code plugin marketplace** named **`gms-marketplace`**
(manifest: [`.claude-plugin/marketplace.json`](.claude-plugin/marketplace.json)).
Add it and install plugins from it. Pin the marketplace to a release tag for a
controlled rollout (recommended), or omit the tag to track the latest:

```text
# Gated: pin to an immutable release tag — only an explicit re-pin upgrades you
claude plugin marketplace add globalmindsolution/gms-marketplace@v0.2.0

# Install the acs plugin (full-shape: Claude Code agentic workflow)
claude plugin install acs@gms-marketplace

# Install the tabp plugin (skills-only: Cowork screen-cvs)
claude plugin install tabp@gms-marketplace

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
        "ref": "v0.2.0"
      }
    }
  }
}
```

### Releasing & updating

The catalog (`marketplace.json`) version is a marketplace-level identifier
(currently 0.2.0) and is not CI-coupled to any plugin's version. The `acs`
`plugin.json` version governs how acs updates ship. A release bumps `version`
in both `.claude-plugin/marketplace.json` and
`plugins/acs/.claude-plugin/plugin.json` (by convention both are kept in sync),
points the acs `git-subdir` `source.ref` at the new tag, and the Release
workflow cuts a single immutable `v<version>` tag
([CHANGELOG](plugins/acs/CHANGELOG.md)). acs is fetched remotely from that
pinned tag — individually updatable with `claude plugin update acs` — and
resolves reproducibly regardless of which marketplace commit is fetched. The
per-entry CI validator checks each entry's `name` (always) and `version` (only
when the entry declares one) against the plugin's own `plugin.json`.

**Before cutting a release** (before bumping `version`), run the behavioral eval
suite locally as a release gate — including the **paid** tier that the pre-commit
hook and CI deliberately skip (it spawns real `claude -p` sessions and costs a
few dollars):

```bash
python3 evals/run_evals.py --plugin acs --paid   # free + paid; needs an authenticated
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

The marketplace currently ships two plugins:

- **`acs` (Autonomous Coding Skills)** — full-shape plugin targeting Claude Code.
  Provides a complete agentic software-delivery workflow: from a raw request
  through product definition (PRD), architecture, ticketing, design,
  implementation specs, TDD implementation with an automatic review loop, pull
  request, and merge. Sixteen skills (`/acs:init`, `/acs:ship`, `/acs:code`, …)
  each run a plan → execute → verify reflection cycle with dedicated subagents;
  pre/post hooks gate every step on the recorded state of its predecessor; and
  all durable state lives in a workspace folder outside the consumer repo, making
  runs resumable and tickets shippable in parallel across git worktrees.

- **`tabp` (Team AI Builder Pack)** — skills-only plugin targeting Claude Cowork.
  Starts with `screen-cvs`, a skill that screens CVs against a job description
  with weighted scoring, fairness guardrails, and an Excel scorecard.

| Where | What |
|-------|------|
| [docs/](docs/README.md) | Product docs: [product/](docs/product/) (PRD, roadmap), [requirements/](docs/requirements/) (behavioral contract), [architecture/](docs/architecture/) (HLD/LLD), [adr/](docs/adr/) |
| [plugins/acs/README.md](plugins/acs/README.md) | acs plugin usage: install, quick start, skill reference, configuration, troubleshooting |
| [plugins/acs/docs/INTERNALS.md](plugins/acs/docs/INTERNALS.md) | acs implementation contract for contributors (lifecycle, helper CLIs, state shapes, XML rules) |
| [plugins/tabp/README.md](plugins/tabp/README.md) | tabp plugin usage: install, quick start, screen-cvs skill reference |
