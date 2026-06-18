# Scoring Rubric

A consistent, defensible method for turning a JD + CV into a match score. Apply it identically to every candidate in a run.

## Step 1 — Extract requirements from the JD

Read the JD and list discrete, checkable requirements. For each, capture:

- **Text**: a short label (e.g., "5+ years backend engineering", "Python", "AWS", "Bachelor's in CS").
- **Category**:
  - **Must-have** — language like "required", "must", "minimum", "essential", core responsibilities.
  - **Nice-to-have** — "preferred", "bonus", "a plus", "nice to have", "ideally".
- **Type**: skill/technology, years/depth of experience, domain/industry, education/certification, or location/work-authorization (include the last **only if the JD explicitly states it**).

If the JD does not clearly separate required vs. preferred, infer reasonably from phrasing and note the assumption to the user.

## Step 2 — Evaluate evidence per requirement

For each requirement, assign a level based on the CV:

| Level | Meaning | Numeric |
|-------|---------|---------|
| **Met** | Clear, direct evidence the candidate satisfies it | 1.0 |
| **Partial** | Related or transferable evidence, or close-but-short (e.g., 3 yrs vs. 5 yrs asked) | 0.5 |
| **Missing** | No supporting evidence in the CV | 0.0 |

Always cite the evidence (role, project, skill, dates). Count clearly transferable experience as **Partial**, not Missing. Never invent or assume experience the CV doesn't support.

## Step 3 — Weight and compute the score

Default weights (state them if you change them):

- **Must-have** requirement weight = **3**
- **Nice-to-have** requirement weight = **1**

Compute:

```
earned   = Σ (weight × level)        over all requirements
possible = Σ (weight × 1.0)          over all requirements
score    = round( earned / possible × 100 )
```

Score is 0–100.

## Step 4 — Must-have gate

Must-haves are gating, not just heavy:

- If **any must-have is Missing**, the candidate **cannot** be banded Strong or recommended "Recommend" regardless of raw score. Cap the band at **Moderate / Hold** at best, and call out the missing must-have(s) prominently.
- If **multiple must-haves are Missing**, cap at **Weak / Reject** unless the user overrides.

This prevents a high nice-to-have score from masking a disqualifying gap.

## Step 5 — Band and recommendation

| Score | Band | Default recommendation |
|-------|------|------------------------|
| 80–100 | Strong | Recommend |
| 60–79 | Moderate | Hold (worth a human review) |
| 0–59 | Weak | Reject |

Then apply the must-have gate from Step 4, which can only lower the band/recommendation, never raise it.

## Step 6 — Ranking a batch

- Rank by **score**, highest first.
- **Tie-break** by number of must-haves Met, then by fewer Partial must-haves.
- Flag candidates within ~5 points of a band cutoff as borderline — worth a closer human look.

## Edge cases

- **Ambiguous years of experience**: estimate from role dates; if unclear, mark Partial and note the uncertainty.
- **Overqualification**: do not penalize numerically; note it as an observation only if relevant to the role.
- **Equivalent credentials**: treat a clearly equivalent degree/cert as Met (e.g., a relevant bootcamp + strong portfolio may be Partial/Met for a "degree preferred" nice-to-have).
- **Sparse or non-standard CVs**: score what's present; state low confidence rather than guessing.
- **Conflicting evidence**: prefer the most specific, most recent evidence and note the conflict.

## Consistency check

Before finishing, confirm: same requirement list, same weights, same evidence standard applied to every candidate. Inconsistent treatment invalidates a ranking.
