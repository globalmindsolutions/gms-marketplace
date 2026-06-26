#!/usr/bin/env python3
"""validate_xml.py — validate coordinator/subagent XML messages against acs-messages.xsd.

Skills validate every task/result/handoff message so malformed messages fail fast
instead of silently degrading the pipeline (docs/requirements/reflection.md).

Strategy (stdlib-only requirement):
  Default fast path: every message is validated IN-PROCESS by validate_structurally(),
  a pure stdlib (xml.etree) structural validator raised to XSD-equivalent coverage.
  No subprocess is spawned per message on the default path.

  Opt-in authoritative check: when the caller sets ACS_XML_AUTHORITATIVE=1 in the
  environment AND xmllint is found on PATH AND acs-messages.xsd is present,
  validate_with_xmllint() is invoked instead of the in-process engine.  xmllint
  absence never blocks a verdict — if the env var is set but xmllint is not on PATH,
  the in-process engine runs silently.  This preserves AC-5 (strict stdlib): no
  mandatory third-party dependency; a stdlib-only interpreter always gets a verdict.

  Gap-closure audit (MAR-61): the in-process validator matches xmllint for these
  violation classes: bad root element, missing/invalid attribute, bad ticket-id
  pattern, out-of-order children, wrong list-item tag, bad status/severity enum,
  duplicate maxOccurs=1 sequence children (cardinality), xs:decimal grammar for
  cost-usd (no exponent, no inf/nan, no underscores), and — closing the content
  model — undeclared attributes (the XSD declares no anyAttribute/wildcard) and
  element children inside text-only (xs:string) leaves.  The ALLOWED_ATTRS and
  TEXT_LEAVES tables below mirror acs-messages.xsd and MUST be kept in sync with
  it.  The AC-2 parity corpus (tests/acs/test_acs_plugin.py:TestValidators) is the
  binding proof — every listed class produces identical pass/fail verdicts under
  both paths.  If the XSD gains a construct not in that corpus, extend the corpus
  so any in-process/xmllint divergence fails the build.

Usage:
  validate_xml.py <file.xml> [more.xml ...]
  echo "<task ...>...</task>" | validate_xml.py -

  ACS_XML_AUTHORITATIVE=1 validate_xml.py <file.xml>   # opt-in xmllint check

Exit codes: 0 = valid, 1 = invalid (details on stderr).

Batch API (Python-callable; no subprocess):
  from validate_xml import validate_batch, batch_overall_ok

  results = validate_batch([msg1, msg2, msg3])
  # returns [(True, []), (False, ["<foo> root …"]), …] — one (ok, errors) per message

  if not batch_overall_ok(results):
      # at least one message is invalid
      ...

  validate_batch() calls validate_structurally() in a plain for-loop; no thread
  pool, no subprocess, no xmllint invocation.  An empty messages list returns [].
  The ACS_XML_AUTHORITATIVE env var is NOT honoured by the batch path (it is a
  per-message CLI concern); callers needing authoritative xmllint validation call
  validate_with_xmllint() directly.
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

# Closed content model (mirrors acs-messages.xsd). The XSD declares no
# anyAttribute / wildcard anywhere, so any attribute not listed here is invalid.
# Keep in sync with the XSD when it changes.
ALLOWED_ATTRS = {
    "task": {"skill", "phase", "ticket-id", "iteration"},
    "result": {"skill", "phase", "ticket-id", "iteration", "status"},
    "handoff": {"skill", "ticket-id", "status"},
    "finding": {"severity", "dimension", "file"},
    "constraint": {"name"},
    "metrics": {"tokens-input", "tokens-output", "cost-usd"},
}
# Elements typed xs:string in the XSD: text-only, no element children allowed.
TEXT_LEAVES = frozenset({
    "objective", "context", "stop-reason", "summary", "next-step",
    "file", "question", "error",
})


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

    # Closed content model: reject any attribute the XSD does not declare.
    errors.extend(_undeclared_attr_errors(root))
    return errors


def _undeclared_attr_errors(elem):
    """Reject attributes not declared for *elem* in the closed XSD content model."""
    allowed = ALLOWED_ATTRS.get(elem.tag)
    if allowed is None:
        # Elements with no declared attributes (e.g. inputs, outputs, file,
        # objective, ...) permit none.
        allowed = frozenset()
    return ["<%s> has undeclared attribute %r (allowed: %s)"
            % (elem.tag, name, ", ".join(sorted(allowed)) or "none")
            for name in elem.keys() if name not in allowed]


def _is_xs_decimal(value):
    """Return True iff *value* conforms to the xs:decimal lexical space.

    xs:decimal allows: optional leading sign (+ or -), one or more decimal
    digits, and an optional single decimal point anywhere in the digit sequence.
    It does NOT allow exponent notation (1e5), inf, nan, underscores (1_000),
    or an empty string.  This matches the W3C XML Schema Part 2 definition and
    the behaviour of xmllint --schema when validating xs:decimal attributes.
    """
    return bool(re.fullmatch(r"[+-]?(\d+\.?\d*|\d*\.\d+)", value))


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

    # Cardinality: every element in the xs:sequence has maxOccurs=1 (the XSD
    # default).  Count occurrences of each known child and reject duplicates.
    for child_tag in allowed:
        count = seen.count(child_tag)
        if count > 1:
            errors.append("<%s> contains %d occurrences of <%s>; at most 1 is allowed"
                          % (tag, count, child_tag))

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

    # Closed content model: text-only (xs:string) leaves admit no element
    # children, and every descendant's attributes must be declared.
    for elem in root.iter():
        if elem is root:
            continue
        errors.extend(_undeclared_attr_errors(elem))
        if elem.tag in TEXT_LEAVES and len(elem):
            child = list(elem)[0].tag
            errors.append("<%s> is a text-only element and may not contain child <%s>"
                          % (elem.tag, child))
    for metrics in root.findall("metrics"):
        for attr in ("tokens-input", "tokens-output"):
            value = metrics.get(attr)
            if value is not None and not value.isdigit():
                errors.append("<metrics %s=%r> must be a non-negative integer" % (attr, value))
        cost = metrics.get("cost-usd")
        if cost is not None:
            if not _is_xs_decimal(cost):
                errors.append(
                    "<metrics cost-usd=%r> must be a valid xs:decimal "
                    "(digits with optional sign and/or decimal point; "
                    "no exponent, no inf/nan, no underscores)" % cost
                )
    return errors


def validate_structurally(text):
    if not isinstance(text, str):
        return ["expected an XML string, got %s" % type(text).__name__]
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


def validate_batch(messages):
    """Validate a list of XML message strings in one call.

    Returns a list of (ok, errors) tuples — one per input message, in order.
    ``ok`` is True when the message is valid; ``errors`` is an empty list when
    ok and a non-empty list of error strings otherwise.

    No subprocess is spawned; each message is validated in-process via
    validate_structurally().  An empty messages list returns [].
    The ACS_XML_AUTHORITATIVE env var is NOT honoured here — this is strictly
    the in-process fast path.

    Args:
        messages: list[str] — XML message strings to validate.

    Returns:
        list[tuple[bool, list[str]]] — one (ok, errors) per input, in order.
    """
    results = []
    for text in messages:
        errors = validate_structurally(text)
        results.append((len(errors) == 0, errors))
    return results


def batch_overall_ok(batch_results):
    """Return True iff every (ok, errors) tuple in batch_results has ok=True.

    Args:
        batch_results: list[tuple[bool, list[str]]] — as returned by validate_batch().

    Returns:
        bool — True when all members are valid, False when any member is invalid.
        An empty batch_results returns True (vacuously true: no invalid members).
    """
    return all(ok for ok, _ in batch_results)


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

        if os.environ.get("ACS_XML_AUTHORITATIVE") and shutil.which("xmllint") and os.path.isfile(XSD_PATH):
            ok, detail = validate_with_xmllint(path)
            if ok:
                print("%s: valid (xmllint, acs-messages.xsd)" % label)
            else:
                failures += 1
                sys.stderr.write("%s: INVALID per acs-messages.xsd\n%s\n" % (label, detail))
        else:
            errors = validate_structurally(text)
            if not errors:
                print("%s: valid (in-process, acs-messages.xsd)" % label)
            else:
                failures += 1
                for error in errors:
                    sys.stderr.write("%s: INVALID — %s\n" % (label, error))
        if arg == "-":
            os.unlink(path)

    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
