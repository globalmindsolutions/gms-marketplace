#!/usr/bin/env python3
"""Reproducible stdlib-`trace` line-coverage harness for validate_xml.py (MAR-61 spec 01).

The repo is Python 3.9+ stdlib-only (no pip) — the pip `coverage` package is NOT
installed — so coverage is measured with the stdlib `trace` module.  This harness
drives validate_structurally, validate_with_xmllint, and main() across every
branch and BOTH engine paths (default in-process and ACS_XML_AUTHORITATIVE opt-in)
under trace.Trace(count=1, trace=0), then reports:

    executed executable lines / total executable lines -> percentage  (gate: >= 90%)

and the missed-line list.  Run:  python3 tests/acs/cov_validate_xml.py
(exit 0 iff coverage >= GATE).
"""

import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import trace

GATE = 90.0

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_TESTS_DIR))
_SCRIPTS_DIR = os.path.join(_REPO_ROOT, "plugins", "acs", "hooks", "scripts")
_TARGET = os.path.join(_SCRIPTS_DIR, "validate_xml.py")

if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

# --- Corpus fixtures (mirrored from TestValidators for driver coverage) ---

VALID_TASK = (
    '<task skill="code" phase="execute" ticket-id="SHOP-1">'
    '<objective>Implement feature X</objective>'
    '<inputs><file>/src/foo.py</file></inputs>'
    '<constraints><constraint name="c1">no breaking changes</constraint></constraints>'
    '<context>background info</context>'
    '</task>'
)
VALID_RESULT = (
    '<result skill="code" phase="execute" ticket-id="SHOP-1" status="completed">'
    '<outputs><file>/src/foo.py</file></outputs>'
    '<findings><finding severity="info">all clear</finding></findings>'
    '<metrics tokens-input="1000" tokens-output="200" cost-usd="0.05"/>'
    '<stop-reason>done</stop-reason>'
    '</result>'
)
VALID_HANDOFF = (
    '<handoff skill="create-spec" ticket-id="SHOP-1" status="needs_input">'
    '<summary>Summarised progress</summary>'
    '<questions><question>What priority?</question></questions>'
    '<next-step>resume after user answers</next-step>'
    '</handoff>'
)
MALFORMED_BAD_ROOT = '<foo skill="code" phase="execute" ticket-id="SHOP-1"/>'
MALFORMED_MISSING_SKILL = (
    '<task phase="execute" ticket-id="SHOP-1"><objective>obj</objective></task>'
)
MALFORMED_INVALID_SKILL = (
    '<task skill="nope" phase="execute" ticket-id="SHOP-1">'
    '<objective>obj</objective></task>'
)
MALFORMED_BAD_TICKET_ID = (
    '<task skill="code" phase="execute" ticket-id="123">'
    '<objective>obj</objective></task>'
)
MALFORMED_OUT_OF_ORDER = (
    '<task skill="code" phase="execute" ticket-id="SHOP-1">'
    '<constraints><constraint name="c1">x</constraint></constraints>'
    '<objective>obj</objective></task>'
)
MALFORMED_WRONG_LIST_ITEM = (
    '<task skill="code" phase="execute" ticket-id="SHOP-1">'
    '<objective>obj</objective><inputs><bar/></inputs></task>'
)
MALFORMED_BAD_STATUS_ENUM = (
    '<result skill="code" phase="execute" ticket-id="SHOP-1" status="bad_status"/>'
)
MALFORMED_BAD_SEVERITY_ENUM = (
    '<result skill="code" phase="execute" ticket-id="SHOP-1" status="completed">'
    '<findings><finding severity="critical">something bad</finding></findings>'
    '</result>'
)
MALFORMED_MISSING_CONSTRAINT_NAME = (
    '<task skill="code" phase="execute" ticket-id="SHOP-1">'
    '<objective>obj</objective>'
    '<constraints><constraint>missing name attr</constraint></constraints>'
    '</task>'
)
MALFORMED_BAD_METRICS = (
    '<result skill="code" phase="execute" ticket-id="SHOP-1" status="completed">'
    '<metrics tokens-input="notanint" tokens-output="200" cost-usd="notadecimal"/>'
    '</result>'
)
MALFORMED_BAD_ITERATION = (
    '<task skill="code" phase="execute" ticket-id="SHOP-1" iteration="0">'
    '<objective>obj</objective></task>'
)
MALFORMED_NOT_WELLFORMED = '<unclosed>'
MALFORMED_HANDOFF_BAD_STATUS = (
    '<handoff skill="code" ticket-id="SHOP-1" status="bad_handoff_status">'
    '<summary>s</summary></handoff>'
)
MALFORMED_UNEXPECTED_CHILD = (
    '<task skill="code" phase="execute" ticket-id="SHOP-1">'
    '<objective>obj</objective>'
    '<unexpected_child>x</unexpected_child>'
    '</task>'
)
MALFORMED_MISSING_SUMMARY_HANDOFF = (
    '<handoff skill="code" ticket-id="SHOP-1" status="completed">'
    '</handoff>'
)
# (vi) cardinality: duplicate maxOccurs=1 sequence children
MALFORMED_DUP_OBJECTIVE = (
    '<task skill="code" phase="execute" ticket-id="SHOP-1">'
    '<objective>first</objective>'
    '<objective>second</objective>'
    '</task>'
)
MALFORMED_DUP_METRICS = (
    '<result skill="code" phase="execute" ticket-id="SHOP-1" status="completed">'
    '<metrics tokens-input="100" tokens-output="50" cost-usd="0.01"/>'
    '<metrics tokens-input="200" tokens-output="100" cost-usd="0.02"/>'
    '</result>'
)
# (vii) xs:decimal grammar violations
MALFORMED_COST_USD_INF = (
    '<result skill="code" phase="execute" ticket-id="SHOP-1" status="completed">'
    '<metrics tokens-input="100" tokens-output="50" cost-usd="inf"/>'
    '</result>'
)
MALFORMED_COST_USD_EXPONENT = (
    '<result skill="code" phase="execute" ticket-id="SHOP-1" status="completed">'
    '<metrics tokens-input="100" tokens-output="50" cost-usd="1e5"/>'
    '</result>'
)


def _load_target_fresh():
    """Import validate_xml from source as a fresh module object (inside the tracer)."""
    sys.modules.pop("validate_xml", None)
    spec = importlib.util.spec_from_file_location("validate_xml", _TARGET)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["validate_xml"] = mod
    spec.loader.exec_module(mod)
    return mod


def _drive():
    """Fresh-import validate_xml and exercise every branch — all inside the traced call."""
    mod = _load_target_fresh()

    # 1) validate_structurally — valid messages (all three root elements)
    for xml in (VALID_TASK, VALID_RESULT, VALID_HANDOFF):
        errors = mod.validate_structurally(xml)
        assert errors == [], "Expected no errors: %r" % errors

    # 2) validate_structurally — malformed messages (all XSD violation classes)
    for xml in (
        MALFORMED_BAD_ROOT,
        MALFORMED_MISSING_SKILL,
        MALFORMED_INVALID_SKILL,
        MALFORMED_BAD_TICKET_ID,
        MALFORMED_OUT_OF_ORDER,
        MALFORMED_WRONG_LIST_ITEM,
        MALFORMED_BAD_STATUS_ENUM,
        MALFORMED_BAD_SEVERITY_ENUM,
        MALFORMED_MISSING_CONSTRAINT_NAME,
        MALFORMED_BAD_METRICS,
        MALFORMED_BAD_ITERATION,
        MALFORMED_NOT_WELLFORMED,
        MALFORMED_HANDOFF_BAD_STATUS,
        MALFORMED_UNEXPECTED_CHILD,
        MALFORMED_MISSING_SUMMARY_HANDOFF,
        # (vi) cardinality — duplicate maxOccurs=1 sequence children
        MALFORMED_DUP_OBJECTIVE,
        MALFORMED_DUP_METRICS,
        # (vii) xs:decimal grammar violations
        MALFORMED_COST_USD_INF,
        MALFORMED_COST_USD_EXPONENT,
    ):
        errors = mod.validate_structurally(xml)
        assert errors, "Expected errors for %r but got empty list" % xml[:40]

    # 3) validate_with_xmllint (if xmllint is available) — exercises the subprocess path
    if shutil.which("xmllint"):
        with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False) as fh:
            fh.write(VALID_TASK)
            tmp_valid = fh.name
        with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False) as fh:
            fh.write(MALFORMED_BAD_ROOT)
            tmp_bad = fh.name
        try:
            ok, _ = mod.validate_with_xmllint(tmp_valid)
            assert ok, "xmllint should accept valid task"
            ok_bad, _ = mod.validate_with_xmllint(tmp_bad)
            assert not ok_bad, "xmllint should reject bad root"
        finally:
            os.unlink(tmp_valid)
            os.unlink(tmp_bad)

    # 4) main() — default in-process fast path via stdin
    with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False) as fh:
        fh.write(VALID_TASK)
        tmp_valid_file = fh.name
    with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False) as fh:
        fh.write(MALFORMED_BAD_ROOT)
        tmp_bad_file = fh.name
    try:
        # 4a) main() with valid file arg — exits 0
        real_argv = sys.argv[:]
        real_stdout = sys.stdout
        real_stderr = sys.stderr
        sys.argv = ["validate_xml.py", tmp_valid_file]
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        try:
            try:
                mod.main()
            except SystemExit as e:
                assert e.code == 0, "Expected exit 0 for valid file, got %r" % e.code
        finally:
            sys.argv = real_argv
            sys.stdout = real_stdout
            sys.stderr = real_stderr

        # 4b) main() with invalid file arg — exits 1, INVALID in stderr
        sys.argv = ["validate_xml.py", tmp_bad_file]
        captured_out = io.StringIO()
        captured_err = io.StringIO()
        sys.stdout = captured_out
        sys.stderr = captured_err
        try:
            try:
                mod.main()
            except SystemExit as e:
                assert e.code == 1, "Expected exit 1 for invalid file, got %r" % e.code
        finally:
            sys.argv = real_argv
            sys.stdout = real_stdout
            sys.stderr = real_stderr
        assert "INVALID" in captured_err.getvalue()

        # 4c) main() with stdin '-' — valid task
        sys.argv = ["validate_xml.py", "-"]
        sys.stdin = io.StringIO(VALID_TASK)
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        try:
            try:
                mod.main()
            except SystemExit as e:
                assert e.code == 0, "Expected exit 0 for valid stdin, got %r" % e.code
        finally:
            sys.argv = real_argv
            sys.stdin = sys.__stdin__
            sys.stdout = real_stdout
            sys.stderr = real_stderr

        # 4d) main() with stdin '-' — invalid message
        sys.argv = ["validate_xml.py", "-"]
        sys.stdin = io.StringIO(MALFORMED_BAD_ROOT)
        captured_err2 = io.StringIO()
        sys.stdout = io.StringIO()
        sys.stderr = captured_err2
        try:
            try:
                mod.main()
            except SystemExit as e:
                assert e.code == 1, "Expected exit 1 for invalid stdin, got %r" % e.code
        finally:
            sys.argv = real_argv
            sys.stdin = sys.__stdin__
            sys.stdout = real_stdout
            sys.stderr = real_stderr
        assert "INVALID" in captured_err2.getvalue()

        # 4e) main() no args — exits 1 with usage
        sys.argv = ["validate_xml.py"]
        sys.stdout = io.StringIO()
        captured_err3 = io.StringIO()
        sys.stderr = captured_err3
        try:
            try:
                mod.main()
            except SystemExit as e:
                assert e.code == 1, "Expected exit 1 for no args, got %r" % e.code
        finally:
            sys.argv = real_argv
            sys.stdout = real_stdout
            sys.stderr = real_stderr

        # 4f) main() with unreadable file path — OSError branch
        sys.argv = ["validate_xml.py", "/nonexistent_acs_test_path/file.xml"]
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        try:
            try:
                mod.main()
            except SystemExit as e:
                assert e.code == 1, "Expected exit 1 for unreadable file, got %r" % e.code
        finally:
            sys.argv = real_argv
            sys.stdout = real_stdout
            sys.stderr = real_stderr

        # 4g) main() with multiple file args — both valid
        with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False) as fh2:
            fh2.write(VALID_RESULT)
            tmp_valid_file2 = fh2.name
        try:
            sys.argv = ["validate_xml.py", tmp_valid_file, tmp_valid_file2]
            sys.stdout = io.StringIO()
            sys.stderr = io.StringIO()
            try:
                try:
                    mod.main()
                except SystemExit as e:
                    assert e.code == 0, "Expected exit 0 for two valid files, got %r" % e.code
            finally:
                sys.argv = real_argv
                sys.stdout = real_stdout
                sys.stderr = real_stderr
        finally:
            os.unlink(tmp_valid_file2)

    finally:
        os.unlink(tmp_valid_file)
        os.unlink(tmp_bad_file)

    # 5) validate_batch / batch_overall_ok (Spec 02 batch API, T2)
    # 5a) Mixed batch: some valid, some invalid — exercises the loop + tuple construction
    batch_mixed = [VALID_TASK, MALFORMED_BAD_ROOT, VALID_RESULT, MALFORMED_MISSING_SKILL]
    batch_results = mod.validate_batch(batch_mixed)
    assert len(batch_results) == 4, "Expected 4 results from 4-message batch"
    assert batch_results[0] == (True, []), "First (valid_task) should be (True, [])"
    assert batch_results[1][0] is False, "Second (bad_root) should have ok=False"
    assert len(batch_results[1][1]) > 0, "Second (bad_root) should have non-empty errors"
    assert batch_results[2] == (True, []), "Third (valid_result) should be (True, [])"
    assert batch_results[3][0] is False, "Fourth (missing_skill) should have ok=False"

    # 5b) batch_overall_ok False when any member invalid
    assert mod.batch_overall_ok(batch_results) is False, \
        "batch_overall_ok should be False when any member is invalid"

    # 5c) All-valid batch: batch_overall_ok True
    batch_all_valid = [VALID_TASK, VALID_RESULT, VALID_HANDOFF]
    all_valid_results = mod.validate_batch(batch_all_valid)
    assert all(ok for ok, _ in all_valid_results), "All members should be ok=True"
    assert mod.batch_overall_ok(all_valid_results) is True, \
        "batch_overall_ok should be True for all-valid batch"

    # 5d) Empty batch edge case
    empty_results = mod.validate_batch([])
    assert empty_results == [], "validate_batch([]) should return []"
    assert mod.batch_overall_ok([]) is True, \
        "batch_overall_ok([]) should be True (vacuously)"

    # 5e) Single-message batch parity with validate_structurally
    for xml in (VALID_TASK, MALFORMED_BAD_ROOT, MALFORMED_MISSING_SKILL):
        vs_errors = mod.validate_structurally(xml)
        expected = (len(vs_errors) == 0, vs_errors)
        batch_single = mod.validate_batch([xml])[0]
        assert batch_single == expected, \
            "Parity mismatch: batch=%r expected=%r for %.40r" % (batch_single, expected, xml)

    # 6) ACS_XML_AUTHORITATIVE opt-in path in main() (only when xmllint present)
    if shutil.which("xmllint") and os.path.isfile(mod.XSD_PATH):
        with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False) as fh:
            fh.write(VALID_TASK)
            tmp_auth = fh.name
        try:
            orig_env = os.environ.get("ACS_XML_AUTHORITATIVE")
            os.environ["ACS_XML_AUTHORITATIVE"] = "1"
            sys.argv = ["validate_xml.py", tmp_auth]
            sys.stdout = io.StringIO()
            sys.stderr = io.StringIO()
            real_argv2 = sys.argv[:]
            try:
                try:
                    mod.main()
                except SystemExit as e:
                    assert e.code == 0, "Expected exit 0 for valid file via xmllint opt-in, got %r" % e.code
            finally:
                sys.argv = real_argv
                sys.stdout = real_stdout
                sys.stderr = real_stderr
                if orig_env is None:
                    os.environ.pop("ACS_XML_AUTHORITATIVE", None)
                else:
                    os.environ["ACS_XML_AUTHORITATIVE"] = orig_env
        finally:
            os.unlink(tmp_auth)

        # ACS_XML_AUTHORITATIVE with an invalid file
        with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False) as fh:
            fh.write(MALFORMED_BAD_ROOT)
            tmp_auth_bad = fh.name
        try:
            orig_env = os.environ.get("ACS_XML_AUTHORITATIVE")
            os.environ["ACS_XML_AUTHORITATIVE"] = "1"
            sys.argv = ["validate_xml.py", tmp_auth_bad]
            sys.stdout = io.StringIO()
            captured_auth_err = io.StringIO()
            sys.stderr = captured_auth_err
            try:
                try:
                    mod.main()
                except SystemExit as e:
                    assert e.code == 1, "Expected exit 1 for invalid via xmllint opt-in, got %r" % e.code
            finally:
                sys.argv = real_argv
                sys.stdout = real_stdout
                sys.stderr = real_stderr
                if orig_env is None:
                    os.environ.pop("ACS_XML_AUTHORITATIVE", None)
                else:
                    os.environ["ACS_XML_AUTHORITATIVE"] = orig_env
            assert "INVALID" in captured_auth_err.getvalue()
        finally:
            os.unlink(tmp_auth_bad)


def _count_from_cover(cover_path):
    """Parse a trace .cover file: count executed/total executable lines and collect misses."""
    import re
    executed = 0
    total = 0
    missed = []
    line_no = 0
    with open(cover_path, "r", encoding="utf-8") as fh:
        for raw in fh:
            line_no += 1
            # trace lines: ">>>>>> code" (missed), "    N: code" (hit), "       code" (non-exec).
            if raw.startswith(">>>>>>"):
                total += 1
                missed.append((line_no, raw[6:].rstrip("\n")))
            else:
                m = re.match(r"\s*(\d+):", raw)
                if m:
                    total += 1
                    executed += 1
    return executed, total, missed


def main():
    covdir = tempfile.mkdtemp(prefix="acs-cov-vxml-")
    try:
        tracer = trace.Trace(count=1, trace=0)
        # Suppress stdout from the script under test (valid messages print to stdout)
        devnull = open(os.devnull, "w")
        real_stdout = sys.stdout
        sys.stdout = devnull
        try:
            tracer.runfunc(_drive)
        finally:
            sys.stdout = real_stdout
            devnull.close()
        results = tracer.results()
        results.write_results(summary=False, coverdir=covdir)

        # Find the produced .cover for validate_xml
        cover_file = None
        for name in os.listdir(covdir):
            if name.endswith(".cover") and "validate_xml" in name:
                cover_file = os.path.join(covdir, name)
                break
        if cover_file is None:
            print("ERROR: no validate_xml .cover produced in %s" % covdir)
            return 2

        executed, total, missed = _count_from_cover(cover_file)
        pct = (executed * 100.0 / total) if total else 0.0
        print("validate_xml.py coverage: %d/%d executable lines = %.1f%% (gate %.0f%%)"
              % (executed, total, pct, GATE))
        if missed:
            print("missed lines (>>>>>> in trace .cover):")
            for ln, src in missed:
                print("  L%d: %s" % (ln, src.strip()))
        else:
            print("missed lines: none")
        result = {"executed": executed, "total": total, "percent": round(pct, 1),
                  "gate": GATE, "passed": pct >= GATE,
                  "missed": [ln for ln, _ in missed]}
        print(json.dumps(result))
        return 0 if pct >= GATE else 1
    finally:
        shutil.rmtree(covdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
