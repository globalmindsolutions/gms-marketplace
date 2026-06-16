# 0013 — acs:metrics derives panels 4-6 from phase artifacts, not a schema extension

**Status**: Accepted · **Date**: 2026-06-16

## Context

MAR-5 adds a read-only `/acs:metrics` dashboard whose six panels include
coverage achieved vs target (panel 4), review iterations before the verifier
passed (panel 5), and token burn by role (panel 6). The data those panels need
already exists in the workspace — `code-state.json` carries coverage and review
iterations, and the role-tagged `<metrics>` elements live in the per-phase
`iter-N-<phase>.xml` artifacts (`acs-messages.xsd:141-145,151`). The question
(design Decision C / ledger item C-3, FIXED) was whether to back these panels
with new state-schema fields or to derive them from the artifacts already on
disk. See `MAR-5/design.md` Decision C and "Panel payload contract".

## Decision

Panels 4-6 **derive entirely from existing phase artifacts and state files** —
no new state-schema field is added to back them. Panel 4 reads
`code-state.json.states.tests`; panel 5 reads
`code-state.json.states.review.iterations` (falling back to the max iteration of
`phases/code/iter-N-verify.xml`); panel 6 sums the `<metrics>` elements across
`phases/<skill>/iter-N-<phase>.xml`, bucketed by the `phase` attribute. The
role-tagged spend lives only in the XML, so per-role burn is reconstructed there
rather than from any JSON the schema would have to grow.

## Consequences

- No `schemas/*.schema.json` and no `acs-messages.xsd` change is required for the
  dashboard; the canonical state shapes are read, never extended.
- The dashboard works retroactively over already-archived tickets with no
  migration or backfill — the artifacts it needs already exist.
- The derivation depends on the current artifact shapes (the flat `<metrics>`
  element, the `code-state` fields); this dependency is pinned by the schema and
  guarded by the helper's unit tests.
