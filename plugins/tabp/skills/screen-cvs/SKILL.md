---
name: screen-cvs
description: Screen one or more CVs/resumes against a job description (JD). Parse the JD into weighted requirements, evaluate each candidate's evidence as met/partial/missing, compute a 0-100 match score with a Recommend/Hold/Reject call, and deliver both an inline summary and an Excel scorecard. Use when the user wants to screen a CV, match a resume to a job description, shortlist or rank candidates, evaluate or score applicants, or assess fit for a role.
---

# Screen CVs against a Job Description

Screen candidate CVs/resumes against a job description (JD), score fit objectively, and hand back a clear recommendation plus a shareable scorecard. Works for a single candidate or a batch ranked against one JD.

This skill is decision-support for a human recruiter — never the final hiring decision. Apply the fairness guardrails on every run.

## When to use

Use when the user wants to: screen a CV against a JD, match a resume to a role, shortlist or rank applicants, score candidates, or judge whether someone fits a job. The user typically provides CV file(s) (PDF/Word/text) and a JD (file or pasted text).

## Step 0 — Initialise the tabp run

Before gathering inputs, initialise a tabp run record so all state is tracked
from the start.

1. **Read settings (with fallback).** Attempt to read `tabp settings.json`
   from the Cowork project folder via:
   ```
   python3 plugins/tabp/helpers/tabp_helper.py settings-read \
     --project-dir <project-folder>
   ```
   If the file is absent or the command is unavailable, apply documented
   fallback values: screening model = coordinator default Sonnet, synthesis
   model = coordinator default Opus, cv_folder = `./cvs`, jd_folder = `./jds`,
   state_write_mode = `helper`.

2. **Start the run record.** Invoke:
   ```
   python3 plugins/tabp/helpers/tabp_helper.py run-start \
     --project-dir <project-folder> \
     --skill screen-cvs \
     --jd-slug <role-slug>
   ```
   Capture the printed `run_id` for use in all subsequent helper calls.
   This acquires the `.tabp/` lock and writes an `in_progress` run record to
   `.tabp/runs/<run-id>/run.json`.

3. **Degradation path.** If Cowork denies Bash access (the helper invocation
   fails or is unavailable), proceed without the helper. Write an initial
   `run.json` directly into the project folder's `.tabp/runs/<run-id>/`
   directory using the file-write capability, setting
   `"state_write_mode": "instructed"`. Record the run identifier and continue
   through the remaining steps using direct file writes wherever a helper
   subcommand is called below. The loss of atomic write and spin-lock
   guarantees is acknowledged and recorded in `run.json`.

## Step 1 — Gather inputs

1. **Identify the JD.** It may be an attached file or pasted text. If no JD is present, ask the user for it before scoring anything — there is nothing to screen against without it.
2. **Identify the CV(s).** One CV or many. Read each file fully (PDF, Word/.docx, or plain text). Note each candidate's name (or a label like "Candidate 1" if anonymized).
3. **Confirm scope only if ambiguous.** If it's unclear which file is the JD vs. a CV, or which role applies when several JDs are present, ask one brief clarifying question. Otherwise proceed.

If a file cannot be read or is empty, tell the user which one and continue with the rest.

## Step 2 — Parse the JD into requirements

Read `references/scoring-rubric.md` for the full method. In short:

- Extract concrete requirements and split them into **must-haves** (required) and **nice-to-haves** (preferred/bonus).
- Capture requirement types: technical/role skills, years and depth of experience, domain/industry, education and certifications, and — only if the JD explicitly states it — location or work authorization.
- Record role title and seniority for context.

Keep the parsed requirement list; it drives both the score and the scorecard columns.

## Step 3 — Evaluate each CV against the requirements

For every requirement, judge the CV's evidence as **Met**, **Partial**, or **Missing**, and cite the specific evidence (e.g., a role, project, or skill from the CV). Treat clearly transferable experience as Partial rather than Missing. Use only what the CV actually supports — do not speculate or invent experience.

## Step 3a — Fan out Sonnet subagents and persist evidence

Replace the manual per-CV evaluation in Step 3 with a parallel subagent
fan-out:

1. **Fan out one Sonnet subagent per CV.** For each candidate's CV, spawn a
   subagent following the charter in `plugins/tabp/agents/screen-cv-subagent.md`.
   Pass each subagent:
   - `run_id` (from Step 0)
   - `candidate_id` (a stable label, e.g., `candidate-01`, `candidate-02`)
   - `candidate_name`
   - `jd_requirements` (the parsed requirement list from Step 2)
   - `cv_content` (the full text of that candidate's CV)
   - `fairness_guidelines` (content of `references/fairness-guidelines.md`)
   Subagents run in parallel; each returns a structured evidence record per the
   `evidence.schema.json` contract.

2. **Persist each evidence record after it returns.** After each Sonnet
   subagent completes and returns its evidence record, invoke:
   ```
   python3 plugins/tabp/helpers/tabp_helper.py state-write \
     --project-dir <project-folder> \
     --run-id <run_id> \
     --file .tabp/runs/<run_id>/evidence-<candidate-id>.json \
     --data-file <temp-file-containing-evidence-json>
   ```
   Write the evidence JSON to a temporary file first (using the file-write
   capability), then pass its path to `state-write`. If Bash is unavailable,
   write the evidence JSON directly to
   `.tabp/runs/<run_id>/evidence-<candidate-id>.json`.

3. **Spawn the Opus-synthesis subagent.** After all per-CV subagents have
   completed and their evidence records are persisted, spawn one synthesis
   subagent following the charter in
   `plugins/tabp/agents/synthesis-subagent.md`. Pass:
   - `run_id`
   - `evidence_records` (the array of all completed evidence records)
   - `jd_slug`
   - `scoring_rubric` (content of `references/scoring-rubric.md`)
   The synthesis subagent returns the ranked batch result.

## Step 4 — Apply fairness guardrails

Before scoring, read `references/fairness-guidelines.md` and follow it throughout. Core rules:

- Evaluate **only job-relevant qualifications**.
- Do **not** infer, use, or comment on protected characteristics (age, gender, race/ethnicity, national origin, religion, disability, marital/family status, etc.) or proxies for them (graduation dates as age signals, names, photos).
- Treat employment gaps neutrally — note them without penalizing.
- Apply identical criteria to every candidate in a batch.
- If the JD itself contains a non-job-relevant or potentially discriminatory requirement, flag it to the user rather than scoring against it.

## Step 5 — Score and recommend

Compute the weighted match score per the rubric (must-haves weighted heavily; any **missing must-have caps the result** so it cannot land as Strong/Recommend). Then assign:

- **Band:** Strong (80–100), Moderate (60–79), Weak (0–59).
- **Recommendation:** Recommend, Hold, or Reject (adjusted by the must-have gate).

For a batch, rank candidates by score (tie-break by number of must-haves met).

## Step 5a — Self-verification pass (present only after pass)

Before presenting any results to the recruiter, run a single coordinator
self-verification pass. This is the AC-3 gate: results are presented ONLY
after this pass produces no blocking findings.

**What to re-verify:**

1. **Evidence citations.** For every judgment across all evidence records,
   confirm the `evidence` field is non-empty and names a specific CV source
   (role, project, skill, or section). An empty or absent citation is a
   blocking finding.

2. **Fairness guardrails.** Confirm that protected characteristics were not
   used, inferred, or commented upon in any judgment. Confirm that identical
   criteria were applied to every candidate. Confirm that employment gaps
   were treated neutrally. Any fairness violation is a blocking finding.

3. **Must-have gates.** Confirm that any candidate with a `Missing` judgment
   on a must-have requirement has a `must_have_gate` value of
   `"Missing:<list>"` and a `recommendation` of `Hold` or `Reject`. A
   discrepancy is a blocking finding.

4. **Rubric consistency.** Confirm that the scoring formula from
   `references/scoring-rubric.md` was applied uniformly — same weighting and
   same band thresholds (Strong 80-100, Moderate 60-79, Weak 0-59) for all
   candidates. An inconsistency is a blocking finding.

**If blocking findings exist:**

- Re-evaluate the flagged candidates or judgments.
- Correct the finding (update the evidence record and re-score where needed).
- Re-run the self-verification pass until no blocking findings remain.

**Present results only after the pass finds no blocking findings.**

After the pass is complete (no blocking findings), proceed to Step 6 to deliver
results. The `decision-write` call that records `verification_passed=true` is
performed by the step that follows this section (added in the spec 04
changeset).

**Upgrade path (not implemented here):** an independent Sonnet sub-agent
verifier may be added in a future iteration (assumption C-7) to provide more
independence than a single coordinator pass. The charter for that verifier would
follow the same `plugins/tabp/agents/` convention as the screening and
synthesis charters defined in this spec.

## Step 6 — Deliver results

Produce **both** deliverables:

### A. Inline summary

For a single candidate:

- **Score & band**, and the **Recommend/Hold/Reject** call.
- **Top strengths** (2–4 bullets tied to JD requirements).
- **Key gaps** (the missing/partial must-haves first).
- A 1–2 sentence rationale.

For a batch: lead with a **ranked list** (candidate — score — recommendation), then a short block per candidate as above. Note anything close to a cutoff that's worth a human second look.

### B. Excel scorecard

Build an `.xlsx` scorecard following `references/scorecard-template.md`: one row per candidate, a column per requirement (Met/Partial/Missing), plus overall score, band, recommendation, key strengths, key gaps, and notes. Sort batch rows by score, highest first. Name it `cv-screening-scorecard-<role>-<date>.xlsx` and provide it as a downloadable file.

## Guardrails & limits

- Output is **decision-support**; state that the final decision rests with the human recruiter.
- Be transparent about uncertainty — when evidence is thin, say so rather than guessing.
- Keep candidate data confidential; include only the contact details the user needs.
- Stay consistent: the same rubric and weighting across every candidate in a run.

## Reference files

- `references/scoring-rubric.md` — requirement extraction, weighting, scoring formula, bands, recommendation mapping, edge cases.
- `references/fairness-guidelines.md` — bias-avoidance rules, protected characteristics, JD red-flags, privacy.
- `references/scorecard-template.md` — exact Excel structure, columns, sheets, formatting, naming.
