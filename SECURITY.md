# Security

Security baseline and practices for this repository.

## Secret scanning (active)

Secrets are blocked at two layers:

1. **Local pre-commit hook** — [gitleaks](https://github.com/gitleaks/gitleaks)
   runs on every `git commit` and blocks credentials, keys, and tokens before
   they ever reach a commit.
2. **CI** — `.github/workflows/security.yml` re-runs gitleaks + the pre-commit
   suite on every push and PR to `main`, catching anything a locally bypassed
   hook (`--no-verify`) would miss.

### One-time setup per clone

```bash
pip install pre-commit        # or: brew install pre-commit
brew install gitleaks         # local CLI (optional; CI uses its own)
pre-commit install            # wires the git hook
```

Run manually against the whole repo:

```bash
pre-commit run --all-files
gitleaks detect --config .gitleaks.toml
```

Tune false positives in `.gitleaks.toml` (`[allowlist]`) — keep exceptions
narrow; prefer allowlisting a specific path/regex over disabling a rule.

## Branch protection (pending paid plan)

Enforced branch protection on `main` requires GitHub Pro/Team for **private**
repos. The desired ruleset is checked in at
`.github/branch-protection-ruleset.json`. Apply it once the org is on a paid
plan:

```bash
gh api -X POST repos/globalmindsolutions/autonomous-coding-skills/rulesets \
  --input .github/branch-protection-ruleset.json
```

The ruleset requires PRs (1 approval + thread resolution), blocks force-push
and deletion, enforces linear history, and requires the security CI checks to
pass before merge.

Until then, the team relies on the soft guardrails: feature branches, PRs into
`main`, and the CI checks above.

## Recommended next steps

- **Enable GitHub secret scanning + push protection** (Settings → Code security)
  — server-side detection of known provider secrets; free on public repos,
  included with GitHub Advanced Security / paid plans for private.
- **Enable Dependabot** alerts + security updates for dependency CVEs.
- **Add CODEOWNERS** once the team grows, to auto-request reviews.
- **Least-privilege tokens** — scope CI/deploy tokens narrowly; never commit
  `.env` files (add them to `.gitignore`).
- **2FA** required for all org members.

## Reporting a vulnerability

Report security issues privately to the maintainers rather than opening a
public issue.
