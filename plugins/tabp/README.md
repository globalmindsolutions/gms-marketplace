# TABP Toolkit

A Claude Cowork plugin for the TABP team. A home for the team's skills — starting with CV screening, with room to add more.

## Skills

### screen-cvs — Screen CVs against a job description

Screens one CV or a batch of CVs against a job description (JD) and tells you who fits and why.

**What it does**

- Parses the JD into **must-have** and **nice-to-have** requirements.
- Checks each candidate's evidence against every requirement (met / partial / missing, with citations).
- Computes a weighted **0–100 match score**; a missing must-have caps the result.
- Bands each candidate **Strong / Moderate / Weak** with a **Recommend / Hold / Reject** call.
- Ranks a batch from best to worst fit.

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

## Inputs & privacy

- **Inputs:** files only (PDF, Word, or pasted text). No external system or ATS connection required.
- **Privacy:** candidate data is treated as confidential and used only for the screening at hand.

## Adding more skills

This plugin is structured to grow. Each new skill lives in its own folder under `skills/`. Ask Claude to "add a skill to the TABP toolkit" to extend it.
