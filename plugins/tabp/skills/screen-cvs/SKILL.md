---
name: screen-cvs
description: Screen one or more CVs/resumes against a job description (JD). Parse the JD into weighted requirements, evaluate each candidate's evidence as met/partial/missing, compute a 0-100 match score with a Recommend/Hold/Reject call, and deliver both an inline summary and an Excel scorecard. Use when the user wants to screen a CV, match a resume to a job description, shortlist or rank candidates, evaluate or score applicants, or assess fit for a role.
---

# Screen CVs against a Job Description

Screen candidate CVs/resumes against a job description (JD), score fit objectively, and hand back a clear recommendation plus a shareable scorecard. Works for a single candidate or a batch ranked against one JD.

This skill is decision-support for a human recruiter — never the final hiring decision. Apply the fairness guardrails on every run.

## When to use

Use when the user wants to: screen a CV against a JD, match a resume to a role, shortlist or rank applicants, score candidates, or judge whether someone fits a job. The user typically provides CV file(s) (PDF/Word/text) and a JD (file or pasted text).

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
