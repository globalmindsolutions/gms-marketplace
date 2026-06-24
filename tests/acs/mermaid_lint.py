#!/usr/bin/env python3
"""Dependency-free linter for Mermaid diagrams embedded in Markdown.

The acs skills (`/acs:create-architecture`, `/acs:create-design`) emit
architecture/design docs whose diagrams are fenced ```mermaid blocks rendered
by GitHub. GitHub's renderer is strict: a single syntax error turns the whole
block into an error box. This linter is a deterministic ($0, no Node, no
network) backstop that catches the syntax errors which have actually shipped
broken — it is heuristic, not a full Mermaid parser, so it targets the known
breakers rather than claiming to validate every grammar rule.

Rules:
  - unknown-diagram-type : block's first keyword is not a known Mermaid type.
  - sequence-semicolon   : a `;` inside a `sequenceDiagram` block. `;` is a
                           statement separator, so it splits message/note text
                           and breaks the parse.
  - er-key-space         : an `erDiagram` attribute with space-separated key
                           constraints (`PK FK`) instead of comma-separated
                           (`PK,FK`).

Usage:
  python3 tests/acs/mermaid_lint.py FILE.md [FILE.md ...]   # exits 1 on findings
Importable:
  from mermaid_lint import lint_text, lint_file, Finding
"""

import re
import sys
from collections import namedtuple

Finding = namedtuple("Finding", ["source", "line", "rule", "message"])

# Known Mermaid diagram declarations (longest-first so e.g. stateDiagram-v2 is
# matched before stateDiagram). Kept as plain prefixes — a block is valid if its
# first meaningful line starts with one of these tokens.
KNOWN_TYPES = sorted(
    [
        "flowchart", "graph",
        "sequenceDiagram",
        "classDiagram-v2", "classDiagram",
        "stateDiagram-v2", "stateDiagram",
        "erDiagram",
        "journey",
        "gantt",
        "pie",
        "quadrantChart",
        "requirementDiagram",
        "gitGraph",
        "mindmap",
        "timeline",
        "zenuml",
        "C4Context", "C4Container", "C4Component", "C4Dynamic", "C4Deployment",
        "sankey-beta",
        "xychart-beta",
        "block-beta",
        "packet-beta",
        "architecture-beta",
        "kanban",
    ],
    key=len,
    reverse=True,
)

_ER_KEY_PAIR = re.compile(r"\b(?:PK|FK|UK)\s+(?:PK|FK|UK)\b")
_QUOTED = re.compile(r'"[^"]*"')
_FENCE_OPEN = re.compile(r"^\s*```+\s*mermaid\s*$", re.IGNORECASE)
_FENCE_CLOSE = re.compile(r"^\s*```+\s*$")

Block = namedtuple("Block", ["start_line", "lines"])  # lines: list of (abs_line, text)


def extract_blocks(text):
    """Return the ```mermaid blocks in *text* with absolute (1-based) line numbers."""
    blocks = []
    in_block = False
    current = None
    for idx, raw in enumerate(text.split("\n"), start=1):
        if not in_block and _FENCE_OPEN.match(raw):
            in_block = True
            current = Block(start_line=idx, lines=[])
            continue
        if in_block and _FENCE_CLOSE.match(raw):
            blocks.append(current)
            in_block = False
            current = None
            continue
        if in_block:
            current.lines.append((idx, raw))
    if in_block and current is not None:
        # Unterminated fence — keep what we have so callers still see the block.
        blocks.append(current)
    return blocks


def _first_meaningful(lines):
    """First non-blank, non-comment line: returns (abs_line, stripped_text) or None."""
    for abs_line, text in lines:
        stripped = text.strip()
        if not stripped or stripped.startswith("%%"):
            continue
        return abs_line, stripped
    return None


def _diagram_type(first_line_text):
    for kw in KNOWN_TYPES:
        if first_line_text == kw or first_line_text.startswith(kw + " ") \
                or first_line_text.startswith(kw + "\t") or first_line_text.startswith(kw + ":"):
            return kw
    return None


def lint_text(text, source="<text>"):
    """Lint all ```mermaid blocks in *text*; return a list of Finding."""
    findings = []
    for block in extract_blocks(text):
        head = _first_meaningful(block.lines)
        if head is None:
            findings.append(Finding(source, block.start_line, "empty-block",
                                    "empty ```mermaid block"))
            continue
        head_line, head_text = head
        dtype = _diagram_type(head_text)
        if dtype is None:
            findings.append(Finding(
                source, head_line, "unknown-diagram-type",
                "unrecognized diagram type %r (typo or unsupported keyword)"
                % head_text.split()[0]))
            continue

        for abs_line, raw in block.lines:
            stripped = raw.strip()
            if not stripped or stripped.startswith("%%"):
                continue

            if dtype == "sequenceDiagram" and ";" in raw:
                findings.append(Finding(
                    source, abs_line, "sequence-semicolon",
                    "';' in sequenceDiagram is a statement separator and breaks "
                    "the parse — use ',' or '—' instead"))

            if dtype == "erDiagram":
                # Ignore quoted comments so "PK FK" inside a comment is not flagged.
                bare = _QUOTED.sub("", raw)
                if _ER_KEY_PAIR.search(bare):
                    findings.append(Finding(
                        source, abs_line, "er-key-space",
                        "erDiagram key constraints must be comma-separated "
                        "('PK,FK'), not space-separated ('PK FK')"))
    return findings


def lint_file(path):
    with open(path, encoding="utf-8") as fh:
        return lint_text(fh.read(), source=str(path))


def main(argv):
    paths = argv[1:]
    if not paths:
        print("usage: mermaid_lint.py FILE.md [FILE.md ...]", file=sys.stderr)
        return 2
    all_findings = []
    for path in paths:
        if not path.endswith(".md"):
            continue
        try:
            all_findings.extend(lint_file(path))
        except (OSError, UnicodeDecodeError) as exc:
            print("error reading %s: %s" % (path, exc), file=sys.stderr)
            return 2
    for f in all_findings:
        print("%s:%d: [%s] %s" % (f.source, f.line, f.rule, f.message), file=sys.stderr)
    if all_findings:
        print("\n%d mermaid finding(s)." % len(all_findings), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
