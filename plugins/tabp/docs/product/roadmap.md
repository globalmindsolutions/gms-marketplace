# tabp — Roadmap

This roadmap covers the committed M1 milestone and a non-committed backlog of later
ideas. Feature IDs (F1–F10) refer to `prd.md § Features (prioritized)`.

---

## M1 — MVP: `screen-cvs` (committed)

**Goal:** Deliver the complete `screen-cvs` skill end-to-end so the TABP team can use
it as their standard first-pass screen from day one.

All Must-have features (F1–F9) and the single Should feature (F10) land in M1.

### Epic E1 — JD & CV ingestion

Deliver the input layer: read CVs and the JD from the Cowork project folder (or chat
attachments) and parse the JD into a structured must-have / nice-to-have rubric.

| Feature | Description |
|---------|-------------|
| F9 | Project-folder input resolution — PDF/Word/text CVs; JD as file or pasted text |
| F1 | JD parsing into must-have vs. nice-to-have requirements |

### Epic E2 — Scoring engine

Deliver the core scoring logic: per-requirement evidence judgments, weighted match
score, configurable must-have cap, banding, and recommendation.

| Feature | Description |
|---------|-------------|
| F2 | Per-requirement Met/Partial/Missing judgment, each with a CV citation |
| F3 | Weighted 0-100 score + banding + recommendation; default scheme (must-have ×3, nice-to-have ×1, missing must-have caps at Hold); per-JD/run weight override |

### Epic E3 — Single & batch screening

Deliver both usage paths — screening one CV and screening a batch — with the parallel
fan-out architecture that achieves the G1 speed target.

| Feature | Description |
|---------|-------------|
| F4 | Single-CV screening — one CV vs. one JD |
| F5 | Batch screening — parallel fan-out up to ~100 CVs/run (concurrency-limited, graceful degradation); Sonnet per-CV subagents, Opus central synthesis and ranking |

### Epic E4 — Deliverables

Deliver the two output artefacts: the in-chat ranked summary and the Excel scorecard
written to the project folder.

| Feature | Description |
|---------|-------------|
| F6 | Inline summary — score, band, recommendation, top strengths, key gaps, rationale; ranked list first for batches |
| F7 | Excel scorecard — `cv-screening-scorecard-<role>-<date>.xlsx` written to Cowork project folder; Sheet 1 (Scorecard: one row per candidate × one column per requirement + score/band/recommendation/strengths/gaps/notes); Sheet 2 (JD Requirements: parsed requirements and weights) |

### Epic E5 — Fairness & compliance guardrails

Embed the fairness controls at every layer of the skill: input parsing, scoring, and
output framing.

| Feature | Description |
|---------|-------------|
| F8 | Fairness guardrails — job-relevant-only scoring; proxy/characteristic exclusion; neutral gap handling; bias-relevant JD requirement flagging; decision-support framing |

### Epic E6 — Plugin packaging & extensibility

Package the skill as a compliant Claude Cowork plugin and structure the repository so
future TABP skills can be added without rework.

| Feature | Description |
|---------|-------------|
| F10 | Extensible skills layout — Cowork plugin format, progressive disclosure (lean `SKILL.md` + references), marketplace distribution at `plugins/tabp` |

### M1 Must-have coverage check

| Feature | Priority | Covered by epic |
|---------|----------|----------------|
| F1 | Must | E1 |
| F2 | Must | E2 |
| F3 | Must | E2 |
| F4 | Must | E3 |
| F5 | Must | E3 |
| F6 | Must | E4 |
| F7 | Must | E4 |
| F8 | Must | E5 |
| F9 | Must | E1 |
| F10 | Should | E6 |

All nine Must-have features (F1–F9) are covered by M1. The single Should feature (F10)
is also delivered in M1 as part of the packaging epic.

---

## Later — not committed

The items below represent ideas for future TABP skills after `screen-cvs` is live and
adopted. No dates, priorities, or delivery commitments are attached to any of them.
They are listed here to signal intent and to ensure the M1 plugin structure leaves room
for them (see F10 / Epic E6).

- **Interview question kit** — generate a structured interview guide from the JD and
  the candidate scorecard (role-relevant technical, behavioural, and values questions).
- **JD drafting / review tool** — draft a JD from a role brief, or review an existing
  JD for clarity, inclusivity, and legal compliance.
- **Candidate outreach drafts** — generate personalised outreach messages for shortlisted
  candidates.
- **ATS / connector / MCP integration** — ingest CVs and JDs directly from an
  applicant-tracking system or via an MCP data source (requires external-service
  integration, out of scope for v1).
