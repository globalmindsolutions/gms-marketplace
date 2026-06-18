# Excel Scorecard Template

Defines the structure of the `.xlsx` scorecard deliverable. Build it as a real spreadsheet file (use the spreadsheet/xlsx capability available in the session) so the user can filter, sort, and share it.

## File naming

`cv-screening-scorecard-<role>-<date>.xlsx`

- `<role>` — short slug of the JD title (e.g., `backend-engineer`).
- `<date>` — ISO date of the run (e.g., `2026-06-17`).

## Sheet 1 — "Scorecard"

One row per candidate. Columns, left to right:

| Column | Contents |
|--------|----------|
| **Candidate** | Name or anonymized label |
| **Overall Score** | 0–100 integer |
| **Band** | Strong / Moderate / Weak |
| **Recommendation** | Recommend / Hold / Reject |
| **Must-have gate** | "OK" or "Missing: <which must-have(s)>" |
| *one column per must-have requirement* | Met / Partial / Missing |
| *one column per nice-to-have requirement* | Met / Partial / Missing |
| **Key Strengths** | Short, JD-tied bullets (semicolon-separated) |
| **Key Gaps** | Missing/partial must-haves first |
| **Notes** | Confidence caveats, borderline flags, JD red-flags |

Rules:

- Use the **same requirement columns** for every candidate, in the same order as parsed from the JD. Group must-have columns before nice-to-have columns.
- **Sort rows by Overall Score, highest first** (for a single candidate there is just one row).
- Header row in **bold**; freeze the header row and the Candidate column so they stay visible while scrolling.
- Keep requirement column headers short; if a requirement label is long, abbreviate in the header and keep the full text on Sheet 2.
- Optional but encouraged: conditional formatting or fill color for the Met/Partial/Missing cells (e.g., green/amber/grey) and for the Band column.

## Sheet 2 — "JD Requirements"

A reference sheet documenting how candidates were judged:

| Column | Contents |
|--------|----------|
| **Requirement** | Full requirement text |
| **Category** | Must-have / Nice-to-have |
| **Type** | Skill / Experience / Domain / Education / Other |
| **Weight** | 3 for must-have, 1 for nice-to-have (or as configured) |

This makes the scoring auditable and lets a reviewer see exactly what each column means.

## General

- Keep personal data minimal — name and job-relevant fields only.
- If a requirement could not be assessed from a CV, mark the cell `Missing` and add a confidence note in the Notes column rather than leaving it blank.
- After creating the file, tell the user the filename and that the rows are ranked (for a batch).
