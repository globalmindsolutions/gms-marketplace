<!--
  pr-default — built-in PR description template (used by /create-pr and the
  product-level skills). Placeholders: {ticket_id}, {type}, {title}, {summary},
  {external_key}. Fill every section from workspace state (ticket.json, specs/,
  design.md, code-state.json) — never from conversation memory.
-->
## Summary

{summary}

## Ticket

- **{ticket_id}** — {title} ({type}){external_key_line}
- Acceptance criteria, specs, design, and the full audit trail live in the ticket's workspace partition.
- Closes #{external_key}

## Changes

<!-- Bullet the changes by area: code, tests, docs (incl. architecture doc set updates). -->

## Test plan

<!-- How this was verified: TDD cycle, test suites run, coverage achieved vs target, manual checks. -->

## Checklist

- [ ] Tests written first (TDD) and passing
- [ ] Coverage target met
- [ ] Code-verifier review loop passed with zero findings
- [ ] Affected docs updated (README / API docs / changelog / architecture doc set)
- [ ] Commit messages follow the configured format
