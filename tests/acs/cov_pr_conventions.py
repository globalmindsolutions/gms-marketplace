#!/usr/bin/env python3
"""Reproducible stdlib-`trace` line-coverage harness for pr-conventions.py (MAR-72 spec 01).

The repo is Python 3.9+ stdlib-only (no pip) — the pip `coverage` package is NOT
installed — so coverage is measured with the stdlib `trace` module, mirroring
tests/acs/cov_validate_xml.py. This harness drives build_title, run_check,
and main() across every branch (both subcommands, both hygiene scans matching
and not matching, check pass and each failure heading, argparse usage error,
the --require-label present/absent branches) under trace.Trace(count=1,
trace=0), then reports:

    executed executable lines / total executable lines -> percentage  (gate: >= 90%)

and the missed-line list.  Run:  python3 tests/acs/cov_pr_conventions.py
(exit 0 iff coverage >= GATE).
"""

import contextlib
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
_TARGET = os.path.join(_SCRIPTS_DIR, "pr-conventions.py")

if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

CONFORMING_BODY = (
    "## Summary\nSome summary text.\n\n"
    "## Ticket\n\n- **MAR-72** — Fix thing (task)\n\n"
    "## Changes\n\n- did stuff\n\n"
    "## Test plan\n\n- ran tests\n"
)
DEFAULT_SECTIONS = "Summary,Ticket,Changes,Test plan"


def _load_target_fresh():
    """Import pr-conventions.py from source as a fresh module object (inside the tracer)."""
    sys.modules.pop("pr_conventions_cov_target", None)
    spec = importlib.util.spec_from_file_location("pr_conventions_cov_target", _TARGET)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["pr_conventions_cov_target"] = mod
    spec.loader.exec_module(mod)
    return mod


def _run_main(mod, argv):
    """Drive mod.main() in-process (sets sys.argv, catches its own sys.exit)."""
    real_argv = sys.argv[:]
    real_stdout = sys.stdout
    sys.argv = ["pr-conventions.py"] + argv
    sys.stdout = io.StringIO()
    try:
        try:
            mod.main()
            code = 0
        except SystemExit as exc:
            code = exc.code if exc.code is not None else 0
        out = sys.stdout.getvalue()
    finally:
        sys.argv = real_argv
        sys.stdout = real_stdout
    return code, out


def _drive():
    """Fresh-import pr-conventions.py and exercise every branch — all inside the traced call."""
    mod = _load_target_fresh()

    # --- build_title: default render, custom render, full token vocab, omitted flag ---
    assert mod.build_title("[{ticket_id}] {title}", "MAR-72", "task", "Fix thing", "", "") \
        == "[MAR-72] Fix thing"
    assert mod.build_title("PR: {ticket_id} — {title}", "MAR-72", "task", "Fix thing", "", "") \
        == "PR: MAR-72 — Fix thing"
    assert mod.build_title(
        "[{ticket_id}]({type}) {title} - {summary} ({external_key})",
        "MAR-72", "task", "Fix thing", "short summary", "ACME-9",
    ) == "[MAR-72](task) Fix thing - short summary (ACME-9)"
    assert mod.build_title("[{ticket_id}] {title} {external_key}", "MAR-72", "", "Fix thing", "", "") \
        == "[MAR-72] Fix thing "

    # --- run_check: pass ---
    ok = mod.run_check(
        title="[MAR-72] Fix thing", body=CONFORMING_BODY, require_label="ACS",
        pr_title_format="[{ticket_id}] {title}", sections=["Summary", "Ticket", "Changes", "Test plan"],
        ticket_prefix="MAR",
    )
    assert ok["passed"] is True
    assert ok["errors"] == []

    # --- run_check: malformed title ---
    bad_title = mod.run_check(
        title="Fix thing", body=CONFORMING_BODY, require_label="ACS",
        pr_title_format="[{ticket_id}] {title}", sections=["Summary", "Ticket", "Changes", "Test plan"],
        ticket_prefix="MAR",
    )
    assert bad_title["passed"] is False
    assert any(e["heading"] == "pr_title" for e in bad_title["errors"])

    # --- run_check: missing required section ---
    missing_section_body = (
        "## Summary\nx\n\n## Ticket\n\n- **MAR-72** — Fix thing (task)\n\n## Changes\n\n- did stuff\n"
    )
    bad_section = mod.run_check(
        title="[MAR-72] Fix thing", body=missing_section_body, require_label="ACS",
        pr_title_format="[{ticket_id}] {title}", sections=["Summary", "Ticket", "Changes", "Test plan"],
        ticket_prefix="MAR",
    )
    assert bad_section["passed"] is False
    assert any(e["heading"] == "pr_description" for e in bad_section["errors"])

    # --- run_check: unrendered placeholder ---
    placeholder_body = CONFORMING_BODY + "\n{summary}\n"
    bad_placeholder = mod.run_check(
        title="[MAR-72] Fix thing", body=placeholder_body, require_label="ACS",
        pr_title_format="[{ticket_id}] {title}", sections=["Summary", "Ticket", "Changes", "Test plan"],
        ticket_prefix="MAR",
    )
    assert bad_placeholder["passed"] is False
    assert any(e["heading"] == "unrendered_placeholder" for e in bad_placeholder["errors"])

    # --- run_check: leftover HTML comment ---
    comment_body = CONFORMING_BODY + "\n<!-- fill this in -->\n"
    bad_comment = mod.run_check(
        title="[MAR-72] Fix thing", body=comment_body, require_label="ACS",
        pr_title_format="[{ticket_id}] {title}", sections=["Summary", "Ticket", "Changes", "Test plan"],
        ticket_prefix="MAR",
    )
    assert bad_comment["passed"] is False
    assert any(e["heading"] == "leftover_template_comment" for e in bad_comment["errors"])

    # --- run_check: --require-label omitted still runs acs_label ---
    no_label = mod.run_check(
        title="[MAR-72] Fix thing", body=CONFORMING_BODY, require_label="",
        pr_title_format="[{ticket_id}] {title}", sections=["Summary", "Ticket", "Changes", "Test plan"],
        ticket_prefix="MAR",
    )
    assert no_label["passed"] is False
    assert any(e["heading"] == "acs_label" for e in no_label["errors"])

    # --- scoping regression: no branch_name/commit_message finding ever ---
    for res in (ok, bad_title, bad_section, bad_placeholder, bad_comment, no_label):
        headings = [e["heading"] for e in res["errors"]]
        assert "branch_name" not in headings
        assert "commit_message" not in headings

    # --- _parse_sections: repeatable flag + comma-separated single flag ---
    assert mod._parse_sections(["Summary,Ticket", "Changes"]) == ["Summary", "Ticket", "Changes"]
    assert mod._parse_sections(None) == []
    assert mod._parse_sections([]) == []

    # --- main(): render-title subcommand ---
    with contextlib.redirect_stdout(io.StringIO()):
        code, out = _run_main(mod, [
            "render-title", "--template", "[{ticket_id}] {title}",
            "--ticket-id", "MAR-72", "--title", "Fix thing",
        ])
    assert code == 0
    assert out.strip() == "[MAR-72] Fix thing"

    # --- main(): render-title with full flag set ---
    with contextlib.redirect_stdout(io.StringIO()):
        code, out = _run_main(mod, [
            "render-title", "--template", "[{ticket_id}]({type}) {title} - {summary} ({external_key})",
            "--ticket-id", "MAR-72", "--type", "task", "--title", "Fix thing",
            "--summary", "short summary", "--external-key", "ACME-9",
        ])
    assert code == 0

    # --- main(): check subcommand, passing body-file, single comma-separated --sections ---
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as fh:
        fh.write(CONFORMING_BODY)
        pass_path = fh.name
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            code, out = _run_main(mod, [
                "check", "--title", "[MAR-72] Fix thing", "--body-file", pass_path,
                "--require-label", "ACS", "--pr-title-format", "[{ticket_id}] {title}",
                "--sections", DEFAULT_SECTIONS, "--ticket-prefix", "MAR",
            ])
        assert code == 0
        assert '"passed": true' in out
    finally:
        os.unlink(pass_path)

    # --- main(): check subcommand, repeatable --sections flags, failing body ---
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as fh:
        fh.write("no sections here")
        fail_path = fh.name
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            code, out = _run_main(mod, [
                "check", "--title", "Fix thing", "--body-file", fail_path,
                "--require-label", "ACS", "--pr-title-format", "[{ticket_id}] {title}",
                "--sections", "Summary", "--sections", "Ticket",
                "--ticket-prefix", "MAR",
            ])
        assert code == 1
        assert '"passed": false' in out
    finally:
        os.unlink(fail_path)

    # --- main(): check subcommand, unreadable --body-file (OSError branch) ---
    with contextlib.redirect_stdout(io.StringIO()):
        code, out = _run_main(mod, [
            "check", "--title", "[MAR-72] Fix thing",
            "--body-file", "/nonexistent_acs_test_path/pr-body.md",
            "--require-label", "ACS", "--pr-title-format", "[{ticket_id}] {title}",
            "--sections", DEFAULT_SECTIONS, "--ticket-prefix", "MAR",
        ])
    assert code == 1
    assert '"body_file"' in out

    # --- main(): argparse usage error (missing required arg) ---
    with contextlib.redirect_stderr(io.StringIO()):
        with contextlib.redirect_stdout(io.StringIO()):
            code, _out = _run_main(mod, ["render-title"])
    assert code == 2

    # --- render_title white-box: confirms build_title delegates to acs_lib.render_format ---
    assert mod.lib.render_format("[{ticket_id}] {title}", {"ticket_id": "MAR-72", "title": "x"}) \
        == "[MAR-72] x"


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
    covdir = tempfile.mkdtemp(prefix="acs-cov-prconv-")
    try:
        tracer = trace.Trace(count=1, trace=0)
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

        cover_file = None
        for name in os.listdir(covdir):
            if name == "pr-conventions.cover":
                cover_file = os.path.join(covdir, name)
                break
        if cover_file is None:
            print("ERROR: no pr-conventions .cover produced in %s" % covdir)
            return 2

        executed, total, missed = _count_from_cover(cover_file)
        pct = (executed * 100.0 / total) if total else 0.0
        print("pr-conventions.py coverage: %d/%d executable lines = %.1f%% (gate %.0f%%)"
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
