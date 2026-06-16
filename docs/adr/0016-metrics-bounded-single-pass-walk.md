# 0016 — metrics aggregation uses a bounded single-pass walk with regex extraction

**Status**: Accepted · **Date**: 2026-06-16

## Context

The `/acs:metrics` helper must aggregate and render six panels in **≤ 5 s for
≤ 50 tickets** (the binding G7 NFR, `docs/product/prd.md:41`). The token-burn
panel needs the `<metrics>` elements out of every per-phase XML artifact. Two
strategies were weighed (design Decision D): a bounded single-pass file walk with
lightweight regex extraction, or a full `xml.etree.ElementTree` DOM parse of
every artifact. See `MAR-5/design.md` Decision D.

## Decision

Aggregation uses a **bounded single-pass walk**: enumerate tickets from
`tickets-index.json` (one read), resolve each partition active-then-archive, and
read only the four state files plus one `glob` of `phases/*/iter-*-*.xml` per
ticket — each file read once. The `<metrics>` element is extracted with a
**compiled regex** that matches each attribute independently (not positionally),
so attribute reordering cannot break it. A full `xml.etree` DOM parse is
**reserved as the documented fallback**, used only if the regex proves brittle
under the panel-6 unit test.

## Consequences

- O(tickets × phase-files) with one read per file and microsecond-scale regex
  over small XML — comfortably inside the 5 s / 50-ticket budget, asserted by a
  synthesized 50-ticket perf test.
- The extraction depends on the flat `<metrics …/>` shape; this is acceptable
  because the shape is schema-pinned (`acs-messages.xsd:141-145`) and guarded by
  an attribute-reordered unit-test case.
- `xml.etree` remains available as a drop-in fallback if a future XML shape
  defeats the regex, without changing the surrounding walk.
