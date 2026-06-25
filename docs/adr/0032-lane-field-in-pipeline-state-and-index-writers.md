# 0032 — Measure G14/G15/G16 by adding one lane field to the existing pipeline-state.json and tickets-index.json writers

**Status**: Accepted · **Date**: 2026-06-25

## Context

Goals G14 (pipeline health by lane), G15 (lead/cycle time by lane), and G16 (catch-rate
per lane) require lane-sliceable data in the workspace state files. The metrics layer
(`metrics_aggregate.py`, `metrics_render.py`) already reads `pipeline-state.json` and
`tickets-index.json` for all other panels. The question is where to add lane data: a
separate lane-indexed file, a new per-lane state file per ticket, or additions to the
existing writers.

## Decision

**Add a single `lane` field to the two existing per-ticket writers:**

1. **`pipeline-state.json`** — written by `update_pipeline`; `lane` is added alongside
   `flow` in the top-level object. Callers pass `lane=ticket.get("lane")` (optional kwarg;
   existing callers without the argument default gracefully).

2. **`tickets-index.json`** — written by `update_index`; `lane` is added alongside
   `needs_design` in each per-ticket entry. No new call site is required; the existing
   `update_index` call in `new-ticket.py` and elsewhere picks up the lane from the
   ticket dict naturally.

The `lane` value is the string computed by `derive_lane` and stored in `ticket.json`
(D5). Both writes are the same single string — no recomputation at write time.

## Alternatives considered

- **Separate lane-indexed file:** introduces a new state file shape, a new write path,
  and a new reader in `metrics_aggregate.py`. The existing files already hold all the
  context the metrics layer needs; adding one field to each is lower coordination cost.
- **Compute lane at metrics-read time from axes:** would require `derive_lane` to be
  callable from `metrics_aggregate.py`; currently the metrics aggregate step is a
  read-only pass over the JSON state files. Adding logic coupling to the routing function
  would break the clean separation.
- **Only index (not pipeline-state):** the pipeline-state approach enables G15 (lead/cycle
  time by lane) because the step timestamps are in pipeline-state; the index enables G14
  (distribution by lane). Both are needed.

## Consequences

- `pipeline-state.json` shape gains a top-level `lane` key alongside `flow`.
  Existing files without `lane` remain valid (the field is absent, not required).
- `tickets-index.json` entries gain a `lane` key alongside `needs_design`.
  Existing entries without `lane` remain valid.
- `update_pipeline` gains an optional `lane=None` keyword argument; all existing
  callers continue to work without modification (defaulting to `lane=None`, which
  skips the write).
- The metrics layer (`metrics_aggregate.py`) can read `lane` from either source for
  panel rendering (G14/G15/G16 panels are planned for a later ticket; this ADR records
  the data-availability decision).
- No migration of existing workspace state is required; both writers are idempotent
  and will populate `lane` on the next write for any ticket that runs through the
  pipeline after this change ships.
