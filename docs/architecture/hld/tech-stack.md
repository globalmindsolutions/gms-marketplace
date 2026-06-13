# HLD — Tech stack & conventions

| Layer | Technology | Why |
|-------|------------|-----|
| Skills (12) | Markdown SKILL.md, Claude Code plugin skill format | Coordinator protocols; user-invocable as `/acs:<name>` |
| Subagents (27) | Markdown agent definitions | Separate contexts per reflection phase; tool allowlists in frontmatter |
| Hooks & helpers | **Python ≥ 3.9, stdlib only** | Deterministic gating/persistence with zero consumer-machine installs |
| State | JSON (pretty-printed, atomic writes), JSON Schema 2020-12 | Human-auditable, machine-validated |
| Messaging | XML validated against `acs-messages.xsd` (xmllint when present, stdlib structural fallback) | Fail-fast malformed coordinator↔subagent traffic |
| Diagrams | Mermaid (C4, ER, sequence, state) | Diffable, GitHub-rendered, agent-maintainable |
| VCS / delivery | git, GitHub via `gh` CLI | Branch-per-ticket, PR-based delivery |
| Trackers (optional) | `gh` (Projects v2), `acli` (Jira) | Two-way sync; CLIs own auth — no secrets in settings |
| CI / release | GitHub Actions | Tests + validation per PR; tag-on-version-bump releases |
| Tests | `unittest` (stdlib) | Deterministic-layer integration tests + prose contract tests |

## Conventions

- **Naming**: skills `kebab-case` = directory name; agents `<skill>-<role>`;
  hooks `pre-/post-<skill>.py`; state files `<skill>-state.json`; phase
  artifacts `iter-<n>-<phase>.*`; ticket ids `<PREFIX>-<n>`.
- **Writes**: temp-file + `os.replace` (atomic); counters guarded by an
  `O_EXCL` spin lock; corrupt JSON read as "absent", reported, never fatal.
- **Failure policy**: gates fail **closed**; helper CLIs exit 2 with
  actionable stderr; status-line scripts fail **open** (fallback line) —
  observability must never block work.
- **Python compatibility**: 3.9+ (no `match`, no `X | Y` unions); `python3`
  on PATH is the only assumption.
- **Docs altitude**: requirements (`docs/0*.md`) → PRD (`docs/product/`) →
  this doc set (`docs/architecture/`) → implementation contract
  (`plugins/acs/docs/INTERNALS.md`) → authoring standard (`AUTHORING.md`).
