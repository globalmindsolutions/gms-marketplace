# Documentation

Product documentation for **`acs`**, organized as the doc sets the acs
workflow maintains for every consumer repo. Each set answers a different
question and is normative for its own concern — none replaces another.

| Set | What it holds | Question it answers |
|-----|---------------|---------------------|
| [product/](product/) | PRD, roadmap | WHY & WHAT, prioritized — vision, goals, features, product NFRs |
| [requirements/](requirements/) | Living behavioral contract, one file per feature area | the detailed, testable behavior (every MUST/SHOULD/MAY) |
| [architecture/](architecture/) | HLD (C4, data model, deployment, tech stack) + LLD (flow sequence diagrams, contracts) | HOW the system is structured |
| [adr/](adr/) | Architecture decision records | WHY each structural choice was made |

Conformance flows top to bottom: **PRD → architecture → design → specs →
code**, each level verified against the one above it. On conflict, the PRD
wins on intent and prioritization, the requirements set wins on behavior, and
the relevant ADR records how the choice was settled.

> This repo dogfoods acs on itself, so these are also acs's own product docs.
> Implementation docs for the plugin live separately under
> [`plugins/acs/docs/`](../plugins/acs/docs/) (INTERNALS, AUTHORING).
