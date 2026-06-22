# TABP Toolkit

A Claude Cowork plugin for the TABP team. A home for the team's skills — starting with CV screening, with room to add more.

## Plugin shape

The tabp plugin has grown beyond a simple skills folder. Its full shape is:

- **`skills/`** — Cowork skill definitions (coordinator protocols). `screen-cvs/SKILL.md` now orchestrates a coordinator+subagents flow.
- **`agents/`** — Reusable tabp-namespaced subagent charters spawned by the coordinator: `screen-cv-subagent.md` (Sonnet, one per CV), `synthesis-subagent.md` (Opus, once per run), and `screen-verifier-subagent.md` (Sonnet, independent verifier, always-on).
- **`helpers/`** — `tabp_helper.py`: stdlib-only Python helper for atomic `.tabp/` state writes, spin-lock, schema validation, run history, and usage aggregation. Invoked via Bash; no external imports.
- **`schemas/`** — JSON Schema contracts for run records, evidence, decisions, history, and lock files. Used by the helper for validation.
- **`.tabp/`** — Per-project state directory (created at runtime in the recruiter's project folder, not in this repo). Holds `runs/<run-id>/run.json`, `evidence-<id>.json`, `decision.json`, `history.json`, and `lock`.

The `screen-cvs` coordinator follows this pattern per run:

1. Calls `tabp_helper.py run-start` (Step 0) to initialise the run record.
2. Fans out one Sonnet subagent per candidate CV in parallel (Step 3a), with each subagent following `agents/screen-cv-subagent.md`.
3. Persists each evidence record via `tabp_helper.py state-write` (Step 3a).
4. Invokes the Opus synthesis subagent once (Step 3a), following `agents/synthesis-subagent.md`.
5. Spawns the independent verifier subagent (Step 5a), following `agents/screen-verifier-subagent.md`. The verifier runs always-on (no skip path) and returns a `pass` or `blocking` verdict. On blocking findings, the coordinator remediates and re-verifies, capped at N=3 total verifier invocations.
6. Delivers results only after the verifier returns a clean `pass` verdict (Step 6). On cap-hit with unresolved findings, writes `verification_passed=false` and notifies the recruiter without presenting results.

If the Cowork runtime denies Bash access, the coordinator falls back to direct file writes (`state_write_mode: "instructed"`). All other steps — including the verifier subagent — are unaffected by this degradation.

## Skills

### screen-cvs — Screen CVs against a job description

Screens one CV or a batch of CVs against a job description (JD) and tells you who fits and why.

**What it does**

- Parses the JD into **must-have** and **nice-to-have** requirements.
- Fans out one Sonnet subagent per candidate CV for parallel evidence collection.
- Invokes an Opus synthesis subagent to score, band, and rank the batch.
- Spawns an independent verifier subagent (always-on) to confirm all evidence is cited and fairness guardrails were followed before presenting results. On blocking findings, remediates and re-verifies (capped at N=3).
- Bands each candidate **Strong / Moderate / Weak** with a **Recommend / Hold / Reject** call.
- Persists all evidence, synthesis, and decision records in the `.tabp/` state directory.

**What you get back**

- An **inline summary** — score, recommendation, top strengths, key gaps, and a short rationale (ranked list first for a batch).
- An **Excel scorecard** — one row per candidate, a column per requirement, overall score, band, recommendation, strengths, gaps, and notes.

**How to use it**

In Cowork, drop in the candidate CV file(s) (PDF or Word) and the job description (a file or pasted text), then ask something like:

- "Screen these CVs against this JD."
- "How well does this resume match the job description?"
- "Rank these candidates for the role and give me a scorecard."

**Built-in fairness guardrails**

The skill scores only job-relevant qualifications and ignores protected characteristics (age, gender, ethnicity, etc.) and their proxies. It treats career gaps neutrally, applies the same criteria to everyone, and flags non-job-relevant requirements in a JD. Results are **decision-support** — the final hiring decision rests with the human recruiter.

### usage — Show cost, time, and token usage for screening runs

Reads aggregated cost, time, and token data from the `.tabp/` run history and
presents a clear per-run breakdown plus aggregate totals. Works for a single
run or all runs in a project.

**What it does**

- Invokes `tabp_helper.py usage-read` to read `.tabp/history.json` and per-run
  `run.json` records.
- Computes aggregate totals for cost (USD), time (duration_seconds), and tokens
  (in/out) across all runs.
- Labels derived cost figures as estimates (`cost_basis="estimate"`) and surfaces
  `pricing_snapshot_date` so the reader knows which pricing snapshot was used.
- Renders "—" for unavailable runs and shows the `usage_note` explaining why
  data is missing. Never fabricates cost or token figures.

**What you get back**

- A **per-run table** — one row per screening run showing run ID, date, status,
  candidates screened, duration, tokens in/out, cost (USD), cost basis, and
  usage source.
- A **Totals summary** — aggregate counts and costs across all runs, with
  `pricing_snapshot_date` and the helper's `usage_note`.

**How to use it**

In Cowork, ask something like:

- "Show me usage for this project."
- "How much did CV screening cost?"
- "What are the token totals for all screening runs?"
- "Give me a spend breakdown for this project."

**Note:** This skill is read-only. It performs no writes, no re-screening, and
no network calls. Cost figures labeled `cost_basis="estimate"` are derived from
token counts and a pricing snapshot; they are not actual billed amounts.

## Inputs & privacy

- **Inputs:** files only (PDF, Word, or pasted text). No external system or ATS connection required.
- **Privacy:** candidate data is treated as confidential and used only for the screening at hand.

## Adding more skills

This plugin is structured to grow. Each new skill lives in its own folder under `skills/`. Subagent charters for a new skill live under `agents/`. Ask Claude to "add a skill to the TABP toolkit" to extend it.
