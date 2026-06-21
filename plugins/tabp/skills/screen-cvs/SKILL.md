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

## Step 5a — Independent verification (present only after clean verdict)

Before presenting any results to the recruiter, spawn an independent verifier
subagent. This is the AC-3 gate: results are presented ONLY after the verifier
returns a clean `pass` verdict. The verifier runs on every `screen-cvs` run with
no skip path (always-on).

**Always-on rule:** There is no condition under which the verifier invocation is
bypassed. Every run must complete Step 5a before proceeding to Step 5b and
Step 6.

### 1. Spawn the verifier

After the Opus synthesis subagent returns (Step 3a), before writing any decision
record, spawn one Sonnet verifier subagent following the charter at
`plugins/tabp/agents/screen-verifier-subagent.md`. Pass exactly the six inline
inputs:

- `run_id` — the active run identifier
- `jd_requirements` — the parsed requirement list from Step 2
- `evidence_records` — all completed `evidence-<candidate-id>.json` records
- `synthesis_result` — the ranked batch result from the Opus synthesis subagent
- `scoring_rubric` — the full content of `references/scoring-rubric.md`
- `fairness_guidelines` — the full content of `references/fairness-guidelines.md`

Do NOT include coordinator reasoning, in-progress evaluation notes, or any
framing of the evidence in the task payload. The verifier operates in isolation
from the coordinator's perspective.

### 2. Evaluate the verdict

Receive the verifier's JSON response:

```json
{"status": "pass" | "blocking", "blocking_findings": [...]}
```

- If `status` is `pass` and `blocking_findings` is empty: proceed directly to
  Step 5b and then Step 6.
- If `status` is `blocking`: enter the remediate-and-re-verify loop (step 3).

### 3. Remediate-and-re-verify loop (capped at N=3 total verifier invocations)

The loop cap is **N=3 total verifier invocations** (including the initial one in
step 1 above). If the second or third invocation still returns `blocking`, the
loop exits after the third.

On each `blocking` verdict:

a. Examine the `blocking_findings` array. For each finding:
   - For `evidence_citation_missing` or `fairness_violation` findings: re-spawn
     the affected `screen-cv-subagent` instance(s) and pass the updated evidence
     records back to the verifier.
   - For `rubric_inconsistency` or `consistency_violation` findings: re-run the
     synthesis subagent with the current evidence records to obtain a corrected
     synthesis result.
   - For `must_have_gate_error` findings: correct the affected evidence record's
     `must_have_gate` and `recommendation` fields directly.

b. Persist any updated evidence records via `state-write` before re-verifying.

c. Re-spawn the verifier with the updated artifacts. This counts as one
   additional verifier invocation toward the N=3 cap.

d. Evaluate the new verdict. If `pass`, proceed to Step 5b. If still `blocking`
   and fewer than N=3 total invocations have been made, repeat from (a). If
   N=3 invocations have been made and the verdict is still `blocking`, exit the
   loop (the cap is hit).

### 4. Gate on clean verdict

Present results to the recruiter (Step 6) **only** if the final verifier
verdict is `pass`. If the N=3 cap is hit with unresolved blocking findings, do
NOT proceed to Step 6 result delivery — go to Step 5b to record the failure and
notify the recruiter.

**Degradation path.** When Cowork denies Bash access, all `state-write` calls
become coordinator direct file writes as documented in the Step 0 degradation
path. The verifier still runs — it is a subagent, not a helper call — and the
`state_write_mode="instructed"` flag is already set. This is unchanged.

## Step 5b — Record the decision

After Step 5a completes (whether with a clean `pass` or with unresolved
blocking findings at the N=3 cap), record the independent verifier verdict
before taking any further action.

1. **Clean pass — verification succeeded.** Invoke:
   ```
   python3 plugins/tabp/helpers/tabp_helper.py decision-write \
     --project-dir <project-folder> \
     --run-id <run_id> \
     --verification-passed true \
     --verification-notes "<summary of the independent verifier verdict: pass on iteration N>"
   ```
   The helper writes `.tabp/runs/<run_id>/decision.json` atomically with:
   - `verification_passed: true`
   - `verification_notes`: the summary string above
   - `presented_at`: the current UTC timestamp (set by the helper)
   - `sign_off: null`

   After writing, proceed to Step 6 to deliver results.

2. **Cap hit — unresolved blocking findings.** When the N=3 cap is reached and
   the verifier still returns `blocking`, write with `--verification-passed false`
   and include the unresolved `blocking_findings` in `--verification-notes`:
   ```
   python3 plugins/tabp/helpers/tabp_helper.py decision-write \
     --project-dir <project-folder> \
     --run-id <run_id> \
     --verification-passed false \
     --verification-notes "<list the unresolved blocking findings here>"
   ```
   Do NOT proceed to Step 6. Notify the recruiter that the run produced
   unresolved verification issues (summarise the blocking findings) and advise
   them not to proceed to scorecard use without manual review.

3. **Degradation path.** If Bash is unavailable, write `decision.json`
   directly into `.tabp/runs/<run_id>/` using the file-write capability,
   populating the fields as described above. Set `sign_off` to `null`.

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
