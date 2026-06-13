#!/usr/bin/env python3
"""validate_xml.py — validate coordinator/subagent XML messages against acs-messages.xsd.

Skills validate every task/result/handoff message so malformed messages fail fast
instead of silently degrading the pipeline (docs/requirements/reflection.md).

Strategy (stdlib-only requirement):
  1. When `xmllint` is available (ships with macOS and most Linux distros), run the
     authoritative XSD validation: xmllint --noout --schema acs-messages.xsd <file>.
  2. Otherwise fall back to built-in structural checks that mirror the XSD's rules
     (root element, required attributes, enums, child element shapes).

Usage:
  validate_xml.py <file.xml> [more.xml ...]
  echo "<task ...>...</task>" | validate_xml.py -

Exit codes: 0 = valid, 1 = invalid (details on stderr).
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
XSD_PATH = os.path.join(os.path.dirname(os.path.dirname(SCRIPT_DIR)), "schemas", "acs-messages.xsd")

SKILLS = {"create-prd", "create-architecture", "create-project", "create-ticket",
          "create-design", "create-spec", "code", "create-pr", "merge-pr"}
PHASES = {"plan", "execute", "verify", "coordinate"}
RESULT_STATUSES = {"completed", "failed", "needs_input"}
HANDOFF_STATUSES = {"completed", "failed", "interrupted", "handed_off", "needs_input"}
TICKET_RE = re.compile(r"^[A-Z][A-Z0-9]*-[0-9]+$")

CHILD_ORDER = {
    "task": ["objective", "inputs", "constraints", "context"],
    "result": ["outputs", "findings", "errors", "questions", "metrics", "stop-reason"],
    "handoff": ["summary", "artifacts", "questions", "next-step"],
}
REQUIRED_CHILDREN = {"task": ["objective"], "result": [], "handoff": ["summary"]}


def _attr_errors(root):
    errors = []
    tag = root.tag

    def need(name, check, what):
        value = root.get(name)
        if value is None:
            errors.append("<%s> is missing required attribute %r" % (tag, name))
        elif not check(value):
            errors.append("<%s %s=%r> is invalid (%s)" % (tag, name, value, what))

    need("skill", lambda v: v in SKILLS, "one of: %s" % ", ".join(sorted(SKILLS)))
    need("ticket-id", lambda v: bool(TICKET_RE.match(v)), "pattern <PREFIX>-<n>, e.g. SHOP-123")
    if tag in ("task", "result"):
        need("phase", lambda v: v in PHASES, "one of: %s" % ", ".join(sorted(PHASES)))
        iteration = root.get("iteration")
        if iteration is not None and (not iteration.isdigit() or int(iteration) < 1):
            errors.append("<%s iteration=%r> must be a positive integer" % (tag, iteration))
    if tag == "result":
        need("status", lambda v: v in RESULT_STATUSES, "one of: %s" % ", ".join(sorted(RESULT_STATUSES)))
    if tag == "handoff":
        need("status", lambda v: v in HANDOFF_STATUSES, "one of: %s" % ", ".join(sorted(HANDOFF_STATUSES)))
    return errors


def _child_errors(root):
    errors = []
    tag = root.tag
    allowed = CHILD_ORDER[tag]
    seen = [child.tag for child in root]
    for child_tag in seen:
        if child_tag not in allowed:
            errors.append("<%s> contains unexpected element <%s> (allowed: %s)"
                          % (tag, child_tag, ", ".join(allowed)))
    for required in REQUIRED_CHILDREN[tag]:
        if required not in seen:
            errors.append("<%s> is missing required element <%s>" % (tag, required))
    positions = [allowed.index(t) for t in seen if t in allowed]
    if positions != sorted(positions):
        errors.append("<%s> children out of order; expected order: %s" % (tag, ", ".join(allowed)))

    for list_tag, item_tag in (("inputs", "file"), ("outputs", "file"), ("artifacts", "file"),
                               ("constraints", "constraint"), ("findings", "finding"),
                               ("errors", "error"), ("questions", "question")):
        for container in root.findall(list_tag):
            for item in container:
                if item.tag != item_tag:
                    errors.append("<%s> may only contain <%s>; found <%s>" % (list_tag, item_tag, item.tag))
                if item_tag == "constraint" and item.get("name") is None:
                    errors.append("<constraint> is missing required attribute 'name'")
                if item_tag == "finding":
                    severity = item.get("severity")
                    if severity is not None and severity not in ("blocking", "info"):
                        errors.append("<finding severity=%r> must be blocking|info" % severity)
    for metrics in root.findall("metrics"):
        for attr in ("tokens-input", "tokens-output"):
            value = metrics.get(attr)
            if value is not None and not value.isdigit():
                errors.append("<metrics %s=%r> must be a non-negative integer" % (attr, value))
        cost = metrics.get("cost-usd")
        if cost is not None:
            try:
                float(cost)
            except ValueError:
                errors.append("<metrics cost-usd=%r> must be a decimal" % cost)
    return errors


def validate_structurally(text):
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        return ["not well-formed XML: %s" % exc]
    if root.tag not in CHILD_ORDER:
        return ["root element must be <task>, <result>, or <handoff>; found <%s>" % root.tag]
    return _attr_errors(root) + _child_errors(root)


def validate_with_xmllint(path):
    proc = subprocess.run(
        ["xmllint", "--noout", "--schema", XSD_PATH, path],
        capture_output=True, text=True, timeout=20,
    )
    return proc.returncode == 0, proc.stderr.strip()


def main():
    args = sys.argv[1:]
    if not args:
        sys.stderr.write(__doc__)
        sys.exit(1)

    failures = 0
    for arg in args:
        if arg == "-":
            text = sys.stdin.read()
            with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False) as fh:
                fh.write(text)
                path, label = fh.name, "<stdin>"
        else:
            path, label = arg, arg
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    text = fh.read()
            except OSError as exc:
                sys.stderr.write("%s: cannot read (%s)\n" % (label, exc))
                failures += 1
                continue

        if shutil.which("xmllint") and os.path.isfile(XSD_PATH):
            ok, detail = validate_with_xmllint(path)
            if ok:
                print("%s: valid (xmllint, acs-messages.xsd)" % label)
            else:
                failures += 1
                sys.stderr.write("%s: INVALID per acs-messages.xsd\n%s\n" % (label, detail))
        else:
            errors = validate_structurally(text)
            if not errors:
                print("%s: valid (structural checks; xmllint not available)" % label)
            else:
                failures += 1
                for error in errors:
                    sys.stderr.write("%s: INVALID — %s\n" % (label, error))
        if arg == "-":
            os.unlink(path)

    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
