#!/usr/bin/env python3
"""pr-conventions.py — deterministic PR title render + pre-open convention self-check.

Gives /acs:create-pr and the three product-level skills (/acs:create-prd,
/acs:create-architecture, /acs:create-project) a deterministic way to:

  render-title  Render settings.formats.pr_title via acs_lib.render_format
                (the deterministic path, not LLM prose) and print it verbatim
                to stdout for the caller to pass straight to
                `gh pr create/edit --title`.

  check         Self-check a rendered title + a filled PR body against the
                repo's configured PR conventions BEFORE a PR is opened, by
                driving check-conventions.py's evaluate() (single source of
                truth) — this module never re-implements the convention rules.
                Two additional producer-only hygiene scans (unrendered
                {placeholder} tokens, leftover <!-- --> template comments) run
                on top of, never instead of, evaluate().

Stdlib-only, runtime-agnostic. Shape mirrors clarify.py / new-ticket.py:
argparse with subparsers, JSON to stdout, sys.exit non-zero on failure.

Usage:
  pr-conventions.py render-title --template "[{ticket_id}] {title}" \\
      --ticket-id MAR-72 --type task --title "Fix thing" \\
      --summary "..." --external-key ""

  pr-conventions.py check --title "[MAR-72] Fix thing" \\
      --body-file pr-body.md --require-label ACS \\
      --pr-title-format "[{ticket_id}] {title}" \\
      --sections "Summary,Ticket,Changes,Test plan" --ticket-prefix MAR
"""

import argparse
import importlib.util
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import acs_lib as lib  # noqa: E402

# ---------------------------------------------------------------------------
# Load check-conventions.py by file path — the SAME in-plugin template path
# tests/acs/test_conventions_check.py loads, never a consumer-repo copy at
# <checkout_root>/.acs/ci/check-conventions.py (which may be stale). This is
# the single source of truth for convention evaluation (AC-3): this module
# calls ONLY cc.evaluate/cc.format_to_regex, never re-implements them.
_PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CHECKER = os.path.join(_PLUGIN_ROOT, "templates", "ci", "check-conventions.py")
_cc_spec = importlib.util.spec_from_file_location("acs_check_conventions", CHECKER)
cc = importlib.util.module_from_spec(_cc_spec)
_cc_spec.loader.exec_module(cc)

# Producer-only body-fill hygiene scans — NOT convention rules, distinct
# headings, run in addition to (never instead of) cc.evaluate().
_PLACEHOLDER_RE = re.compile(r"\{[a-z_]+\}")
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def build_title(template, ticket_id, type_, title, summary, external_key):
    """Render the PR title via acs_lib.render_format — the AC-1 mechanism.

    No re-implementation: this is a thin mapping-builder around the existing
    render_format(template, mapping) function (acs_lib.py:621-622).
    """
    mapping = {
        "ticket_id": ticket_id or "",
        "type": type_ or "",
        "title": title or "",
        "summary": summary or "",
        "external_key": external_key or "",
    }
    return lib.render_format(template, mapping)


def _hygiene_errors(body):
    """The two producer-only hygiene scans, distinct from evaluate()'s headings."""
    errors = []
    if _PLACEHOLDER_RE.search(body or ""):
        errors.append({
            "heading": "unrendered_placeholder",
            "detail": "PR body contains an unrendered {token} placeholder — "
                      "fill every template placeholder before opening the PR.",
        })
    if _HTML_COMMENT_RE.search(body or ""):
        errors.append({
            "heading": "leftover_template_comment",
            "detail": "PR body contains a leftover <!-- --> template guidance "
                      "comment — delete it when filling the section.",
        })
    return errors


def run_check(title, body, require_label, pr_title_format, sections, ticket_prefix):
    """Drive cc.evaluate(settings, ctx, "pr") scoped to pr_title + pr_description
    (+ acs_label when --require-label is supplied), plus the two hygiene scans.

    Scoping (AC-3, no fork of evaluate's logic): branch_name and commit_message
    are routed to res.skipped via evaluate's OWN _enabled() disable gate —
    this helper never derives a branch name or commit history itself.
    """
    settings = {
        "ticket_prefix": ticket_prefix,
        "formats": {"pr_title": pr_title_format},
        "enforcement": {
            "checks": {"branch_name": False, "commit_message": False},
            "pr_description_sections": list(sections or []),
        },
    }
    ctx = {
        "title": title,
        "body": body,
        "labels": [require_label] if require_label else [],
        "branch": "",
        "commit_subjects": [],
    }

    res = cc.evaluate(settings, ctx, "pr")
    errors = [{"heading": heading, "detail": detail} for heading, detail in res.errors]
    errors.extend(_hygiene_errors(body))
    skipped = list(res.skipped)

    return {"passed": not errors, "errors": errors, "skipped": skipped}


# ---------------------------------------------------------------------------
# argparse plumbing — testable core above is callable without it.
# ---------------------------------------------------------------------------

def _add_render_title_parser(sub):
    p = sub.add_parser("render-title")
    p.add_argument("--template", required=True)
    p.add_argument("--ticket-id", default="")
    p.add_argument("--type", dest="type_", default="")
    p.add_argument("--title", default="")
    p.add_argument("--summary", default="")
    p.add_argument("--external-key", default="")
    return p


def _add_check_parser(sub):
    p = sub.add_parser("check")
    p.add_argument("--title", required=True)
    p.add_argument("--body-file", required=True)
    p.add_argument("--require-label", default="")
    p.add_argument("--pr-title-format", required=True)
    p.add_argument("--sections", default=None, action="append",
                    help="repeatable, or a single comma-separated flag")
    p.add_argument("--ticket-prefix", required=True)
    return p


def _parse_sections(raw_list):
    sections = []
    for raw in raw_list or []:
        for part in str(raw).split(","):
            part = part.strip()
            if part:
                sections.append(part)
    return sections


def main(argv=None):
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    _add_render_title_parser(sub)
    _add_check_parser(sub)
    args = parser.parse_args(argv)

    if args.cmd == "render-title":
        title = build_title(
            template=args.template,
            ticket_id=args.ticket_id,
            type_=args.type_,
            title=args.title,
            summary=args.summary,
            external_key=args.external_key,
        )
        print(title)
        sys.exit(0)

    if args.cmd == "check":
        try:
            with open(args.body_file, "r", encoding="utf-8") as fh:
                body = fh.read()
        except OSError as exc:
            print(json.dumps({"passed": False,
                               "errors": [{"heading": "body_file",
                                           "detail": "could not read --body-file: %s" % exc}],
                               "skipped": []}))
            sys.exit(1)
        result = run_check(
            title=args.title,
            body=body,
            require_label=args.require_label,
            pr_title_format=args.pr_title_format,
            sections=_parse_sections(args.sections),
            ticket_prefix=args.ticket_prefix,
        )
        print(json.dumps(result))
        sys.exit(0 if result["passed"] else 1)

    sys.exit(2)  # pragma: no cover - unreachable, argparse `required=True` gates cmd


if __name__ == "__main__":
    main()
