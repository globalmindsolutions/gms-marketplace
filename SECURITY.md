# Security Policy

Security baseline and practices for the **`gms-marketplace`** repository (the
`acs` plugin catalog).

## Reporting a vulnerability

Report security issues **privately** — do not open a public issue or pull
request.

- **Preferred:** GitHub **private vulnerability reporting** — open the
  repository's **Security** tab and click **"Report a vulnerability."** This
  creates a private advisory visible only to maintainers.

Include the affected version or commit, a description, reproduction steps, and
the impact. We aim to acknowledge within **3 business days** and will share a
remediation plan after triage. Please allow a reasonable window to fix and
release before public disclosure (coordinated disclosure).

## Supported versions

The `acs` plugin and the `gms-marketplace` catalog share one version. Fixes land
on `main` and ship in the next tagged release; pin consumers to a released
`v<version>` tag and update promptly when a release notes a security fix.

| Version         | Supported            |
| --------------- | -------------------- |
| latest `v0.2.x` | :white_check_mark:   |
| older releases  | :x: (please upgrade) |

## What ships here

Claude Code plugin definitions (skills, agents, hooks) and stdlib-only Python
tooling (the convention checker, lifecycle hooks, helper CLIs), plus CI
workflows. Installing the plugin grants its skills and hooks the ability to run
in your Claude Code environment — review the source before installing, as with
any plugin. There are **no third-party runtime dependencies** (Python stdlib
only; nothing is fetched at runtime).

## Hardening in place

### Branch protection (active)

A repository **ruleset** protects `main` (mirrored in
[`.github/branch-protection-ruleset.json`](.github/branch-protection-ruleset.json)):

- a pull request is required before merge — **squash-only**, **linear history**;
- these status checks must pass: `PR title convention`, `Secret scan
  (gitleaks)`, `Pre-commit hooks`, `Tests & validation (Python 3.9)` and
  `(Python 3.12)`;
- force-push and branch deletion are blocked.

Required approvals are currently `0` so a solo maintainer can merge; raise to
`1+` once there is a second maintainer. Re-apply the checked-in ruleset with:

```bash
gh api -X PUT repos/globalmindsolution/gms-marketplace/rulesets/<id> \
  --input .github/branch-protection-ruleset.json     # or POST to create a new one
```

### Secret scanning (active)

Secrets are blocked at three layers:

1. **Local pre-commit hook** — [gitleaks](https://github.com/gitleaks/gitleaks)
   runs on every `git commit`.
2. **CI** — `.github/workflows/security.yml` re-runs gitleaks + the pre-commit
   suite on every push/PR to `main` (catching anything a bypassed local hook
   would miss).
3. **GitHub secret scanning + push protection** — server-side detection that
   blocks pushes containing known-provider secrets.

One-time per clone:

```bash
pip install pre-commit        # or: brew install pre-commit
pre-commit install            # commit-time hooks
```

Tune gitleaks false positives in `.gitleaks.toml` (`[allowlist]`) — keep
exceptions narrow; prefer allowlisting a specific path/regex over disabling a
rule.

### Dependencies & supply chain (active)

- **Dependabot** alerts + automated **security** updates are enabled; GitHub
  Actions are also kept current via proactive **version** updates
  ([`.github/dependabot.yml`](.github/dependabot.yml)).
- **GitHub Actions are restricted** to GitHub-owned + verified-creator actions,
  plus an explicit allow for `pre-commit/action` — third-party actions cannot be
  introduced without updating the allowlist.
- **Least-privilege CI** — the default `GITHUB_TOKEN` is read-only; workflows
  request elevated scopes explicitly and per-job.

### Account & repository

- **2FA required** for all organization members.
- Merged branches are auto-deleted; only squash merges are allowed.

## Recommended next steps

- **Pin GitHub Actions to commit SHAs** for stronger supply-chain integrity
  (Dependabot keeps SHA-pinned actions updated).
- **Add CODEOWNERS** and raise required approvals to `1+` as the team grows.
- **Consider CodeQL** code scanning if the Python surface grows.
