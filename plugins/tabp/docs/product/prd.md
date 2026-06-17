# tabp — Product Requirements Document

## Vision

tabp is the TABP team's dedicated hiring toolkit delivered as a Claude Cowork plugin.
Starting with CV-to-JD screening (`screen-cvs`), it provides a consistent,
evidence-backed, and fair first-pass hiring workflow that keeps humans accountable for
every final decision — freeing recruiters and hiring managers from slow, error-prone
manual review while producing auditable scorecards they can share and defend.

## Problem statement

Manual CV-versus-JD screening is slow, inconsistent across reviewers, and susceptible
to bias. A recruiter or hiring manager reading twenty CVs in a sitting applies slightly
different mental rubrics to each one, skips evidence-grounding, and rarely produces a
document the wider team can inspect or challenge. The result is hiring decisions that
are difficult to explain, hard to audit, and potentially unfair. The TABP team needs a
first-pass screening tool that: (1) reads every CV against the same structured rubric
derived from the JD, (2) surfaces explicit evidence for every judgment, (3) outputs a
shareable scorecard, and (4) flags non-job-relevant or potentially discriminatory JD
requirements — all without replacing the human's final decision.

## Target users & personas

### P1 — TABP Recruiter / Talent Partner

**Context:** Receives inbound CVs for open TABP roles. Owns the initial screening step
before CVs reach the hiring manager.

**Job to be done:** Screen a batch of CVs against a JD quickly and consistently, then
hand a ranked shortlist and evidence-backed scorecard to the hiring manager.

**Goals:** Reduce time-to-shortlist; apply the same rubric to every candidate; produce
a record of why each candidate was advanced or not.

**Frustrations:** Manual review is slow when inbound volume spikes; different reviewers
produce different shortlists from the same CV pool; there is no audit trail for
screening decisions.

### P2 — Hiring Manager

**Context:** Owns the hiring decision for TABP roles. Receives the shortlist from the
recruiter and decides who to interview.

**Job to be done:** Review a ranked shortlist with evidence and scores rather than raw
CVs; trust that protected characteristics played no role in scoring; give the team a
shareable, defensible artefact.

**Goals:** Spend interview slots efficiently; be confident the screen was fair and
job-relevant; have a document to share with stakeholders or retain for compliance.

**Frustrations:** Shortlists without rationale require re-reading CVs from scratch;
undocumented screening creates compliance risk; manual ranking is not reproducible.

## Goals & success metrics

| # | Goal | Success metric |
|---|------|---------------|
| G1 | **Speed** — screen a batch substantially faster than manual review via parallel fan-out | Reduce wall-clock time to screen a 20-CV batch against one JD by **≥ 70% vs. the manual baseline**, measured **within the first month of TABP adoption**. Baseline = team's current manual minutes-per-CV, to be captured at rollout. |
| G2 | **Consistency** — identical rubric and weights applied to every candidate in a run; reproducible scores across re-runs | **100% of candidates in a run** are scored against the same parsed rubric and weights; **re-running the same CV+JD pair yields the same band and recommendation in ≥ 95% of cases**, measured on a **10-CV regression set per release**. |
| G3 | **Evidence & auditability** — every Met/Partial/Missing judgment cites CV evidence; every run produces a shareable scorecard | **100% of Met/Partial/Missing judgments carry a CV citation**, and **100% of runs emit a shareable Excel scorecard**, verified on **every run from M1 onward**. |
| G4 | **Fairness** — only job-relevant criteria scored; protected characteristics and proxy criteria excluded; bias-relevant JD requirements flagged | **0 protected-characteristic or proxy criteria** appear in scoring output, and **100% of non-job-relevant / potentially discriminatory JD requirements are flagged**, verified on a **fairness test set of ≥ 15 JD/CV pairs per release**. |
| G5 | **Adoption** — TABP team uses `screen-cvs` as the standard first-pass screen | **≥ 80% of new TABP role openings** use `screen-cvs` as the first-pass screen **within 3 months (one quarter) of M1 release**. |

## Features (prioritized)

MoSCoW groups; every feature names the goal(s) it serves. Features marked **Must**
form the complete v1 `screen-cvs` skill.

| ID | Feature | Priority | Supports goals | Notes |
|----|---------|----------|----------------|-------|
| F1 | **JD parsing into must-have vs. nice-to-have requirements** (file or pasted text) | Must | G2, G3, G4 | Produces the structured rubric that all downstream scoring uses. |
| F2 | **Per-requirement evidence judgment** — Met / Partial / Missing, each with an explicit CV citation | Must | G2, G3 | Every judgment must carry a direct quote or reference from the CV. |
| F3 | **Weighted 0-100 match score + banding + recommendation** with configurable weights | Must | G2, G3 | Default scheme: must-have weight ×3, nice-to-have weight ×1. Any missing must-have caps the result at the Hold recommendation (candidate cannot be scored Strong or Recommend). Users may override the weights and the must-have cap per JD/run. Bands: Strong / Moderate / Weak. Recommendations: Recommend / Hold / Reject. (supports G2, G3) |
| F4 | **Single-CV screening** — one CV vs. one JD | Must | G1, G2, G3 | Baseline usage path; also the unit exercised by the G2 regression set. |
| F5 | **Batch screening with parallel fan-out + central synthesis and ranking** | Must | G1, G2 | One screening unit per CV, up to ~100 CVs per run (concurrency-limited; graceful degradation beyond that). Ranked output list by score. Architecture: per-CV screening subagents on Sonnet; central synthesis and ranking on Opus. The 20-CV batch is the G1 measurement basis. |
| F6 | **Inline summary deliverable** — score, band, recommendation, top strengths, key gaps, short rationale; ranked list first for batches | Must | G3 | Readable directly in the Cowork chat. |
| F7 | **Excel scorecard deliverable** — single `.xlsx`, two sheets, written to the Cowork project folder | Must | G3 | Sheet 1 (Scorecard): one row per candidate, one column per JD requirement (Met/Partial/Missing), plus overall score, band, recommendation, key strengths, key gaps, notes. Sheet 2 (JD Requirements): parsed requirements and their weights. File naming: `cv-screening-scorecard-<role>-<date>.xlsx`. Written to the Cowork project folder. (supports G3) |
| F8 | **Fairness guardrails** — job-relevant-only scoring; proxy/characteristic exclusion; neutral gap handling; JD flagging; decision-support framing | Must | G4 | Never infer, use, or comment on protected characteristics or proxies. Treat employment gaps neutrally. Flag non-job-relevant or potentially discriminatory JD requirements. Present all output as decision-support; the human makes the final call. (supports G4) |
| F9 | **Project-folder input resolution** — read CV(s) and JD from the Cowork project folder | Must | G1, G3 | Prefer files already in the project; fall back to chat attachments for that run. Accept PDF, Word, and plain-text CVs; accept JD as file or pasted text. (supports G1, G3) |
| F10 | **Extensible skills layout** — plugin structured so additional TABP skills can be added later without rework | Should | G5 | Cowork plugin using the skills format with progressive disclosure (lean `SKILL.md` plus references). Enables future skills without repo restructuring. (supports G5) |

### Won't — v1

The following are explicitly deferred (see Out of scope):

- Additional TABP skills (interview question kit, JD drafting/review, candidate outreach drafts)
- ATS / connector / MCP external integrations
- Autonomous accept/reject decisions

## Non-functional requirements

### Performance / scale

- Batch screening MUST fan out across candidates in parallel: one screening unit per
  CV, synthesised and ranked centrally. This is what delivers the G1 speed target.
- Architecture guidance: per-CV screening subagents run on **Sonnet**; central
  synthesis and ranking run on **Opus**.
- Fan-out must support up to **~100 CVs per run** (concurrency-limited). Graceful
  degradation is required beyond that ceiling — the skill must not silently fail or
  corrupt results when the ceiling is approached or exceeded; it must surface a clear
  message and process what it can.
- The **20-CV batch** is the canonical G1 measurement basis; performance targets in §4
  refer to this batch size.

### Fairness / compliance

- Evaluate only job-relevant qualifications. Never infer, use, or comment on protected
  characteristics (age, gender, ethnicity, disability, marital status, etc.) or proxy
  attributes (name-based inferences, school prestige as a protected-class proxy, etc.).
- Treat employment gaps neutrally — do not penalise or comment on them.
- Apply identical rubric and weights to every candidate in a batch.
- Flag non-job-relevant or potentially discriminatory JD requirements before scoring
  (for the recruiter/hiring manager to decide whether to keep them).
- Present all output as decision-support: make clear that a human is responsible for
  the final hiring decision.

### Privacy

- Treat CV data as confidential. Surface only job-relevant details in the scorecard and
  inline summary. Do not log or persist CV content beyond what the Cowork session and
  project folder already manage.

### Portability

- v1 is files-only: no external ATS, connector, or MCP integration.
- Implemented as a Claude Cowork plugin (`skills/*/SKILL.md`) using the standard skills
  format with progressive disclosure (lean `SKILL.md` entry point plus separate
  referenced docs for depth).
- Distributed via the GMS marketplace at `plugins/tabp`.

## Constraints & assumptions

### Constraints

- **Delivery target**: Claude Cowork plugin (`plugins/tabp`), distributed via the GMS
  marketplace.
- **v1 scope**: exactly one skill (`screen-cvs`). Plugin architecture must leave room
  for additional TABP skills in future iterations without restructuring the repo.
- **No external services in v1**: all inputs come from the Cowork project folder or
  chat attachments; all outputs are written to the project folder or the chat.
- **Model availability**: the fan-out architecture assumes Sonnet is available for
  per-CV subagents and Opus is available for central synthesis at the time of M1
  release.

### Assumptions

- **G1 manual baseline**: the team's current manual minutes-per-CV figure is not yet
  captured. It will be measured at rollout; without it the ≥ 70% reduction target
  cannot be verified. This is a confirmed assumption — baseline capture is an M1
  rollout task.
- **G2 regression set**: a 10-CV regression set will be curated before M1 release and
  run as part of the release checklist from M1 onward.
- **G4 fairness test set**: a ≥ 15-pair JD/CV fairness test set will be curated (team
  responsibility) before M1 release and re-run each release.
- **Scoring weights**: the default scheme (must-have ×3, nice-to-have ×1, missing
  must-have caps at Hold) is sufficient for most TABP roles. Per-JD/run overrides
  handle exceptions in v1.
- **Cowork skills format stability**: the skills format and progressive-disclosure
  conventions remain stable between now and M1 delivery.

## Out of scope

The following are explicitly not in scope for tabp v1:

- **Additional TABP skills**: interview question kit, JD drafting/review tool,
  candidate outreach draft generator. These are listed in the "Later" roadmap section
  and are not committed.
- **ATS / connector / MCP inputs**: no external applicant-tracking-system integration,
  no third-party connector, no MCP data source in v1. All inputs are files or pasted
  text only.
- **Autonomous hiring decisions**: tabp is decision-support software. It produces a
  score, band, and recommendation, but the human recruiter or hiring manager makes
  every accept/reject decision. Autonomous or automated hiring actions are out of scope
  by design.
- **Marketplace registration and skill scaffolding**: registering `plugins/tabp` in
  `.claude-plugin/marketplace.json` and scaffolding the `screen-cvs` skill code are
  downstream engineering tasks, not part of this PRD ticket.
