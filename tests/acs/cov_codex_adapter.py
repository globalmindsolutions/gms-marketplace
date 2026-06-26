#!/usr/bin/env python3
"""Reproducible stdlib-`trace` line-coverage harness for codex_adapter.py (MAR-4 Spec 02).

The repo is Python 3.9+ stdlib-only (no pip; CLAUDE.md forbids it) — the pip `coverage` package
is NOT installed — so coverage is measured with the stdlib `trace` module. This harness imports
codex_adapter FROM SOURCE inside the traced driver (so module-level + `def` signature lines count),
exercises every branch (codex / claude-code / absent / invalid-SystemExit / main stdout path),
reports executed/total -> pct, GATE=90.0, and exits 0 iff pct >= 90.

Run:  python3 tests/acs/cov_codex_adapter.py   (exit 0 iff coverage >= GATE).

Note on measurement: the target module is imported FROM SOURCE inside the traced driver, so its
module-level statements and every `def` signature line execute under trace.Trace and are counted.
An import that happened before tracing started would otherwise leave the top-level body and the
signatures marked as missed (trace counts a line only when it runs during the traced call).
"""

import importlib.util
import io
import json
import os
import re
import shutil
import sys
import tempfile
import trace

GATE = 90.0

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_TESTS_DIR))
_SCRIPTS_DIR = os.path.join(_REPO_ROOT, "plugins", "acs", "hooks", "scripts")
_TARGET = os.path.join(_SCRIPTS_DIR, "codex_adapter.py")

if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)


def _load_target_fresh():
    """Import codex_adapter from source as a fresh module object (inside the tracer)."""
    sys.modules.pop("codex_adapter", None)
    spec = importlib.util.spec_from_file_location("codex_adapter", _TARGET)
    module = importlib.util.module_from_spec(spec)
    sys.modules["codex_adapter"] = module
    spec.loader.exec_module(module)
    return module


def _drive():
    """Fresh-import the target and exercise every branch — all inside the traced call."""
    mod = _load_target_fresh()

    # 1) explicit codex -> "codex"
    result = mod.resolve_runtime(["--runtime", "codex"])
    assert result == "codex", "Expected 'codex', got %r" % result

    # 2) explicit claude-code -> "claude-code"
    result = mod.resolve_runtime(["--runtime", "claude-code"])
    assert result == "claude-code", "Expected 'claude-code', got %r" % result

    # 3) absent -> "claude-code" (ADR-0027 back-compat)
    result = mod.resolve_runtime([])
    assert result == "claude-code", "Expected 'claude-code' (absent), got %r" % result

    # 4) invalid value -> argparse raises SystemExit code 2
    try:
        mod.resolve_runtime(["--runtime", "bogus"])
        assert False, "Expected SystemExit from invalid --runtime value"
    except SystemExit as exc:
        assert exc.code != 0, "Expected non-zero exit code, got %r" % exc.code

    # 5) main() stdout path — capture stdout to avoid cluttering harness output
    old_stdout = sys.stdout
    sys.stdout = io.StringIO()
    try:
        # main() calls sys.exit(0); catch it so the harness does not abort
        try:
            mod.main()
        except SystemExit as exc:
            assert exc.code == 0, "main() should exit 0, got %r" % exc.code
        captured = sys.stdout.getvalue()
    finally:
        sys.stdout = old_stdout
    assert captured.strip() == "claude-code", (
        "main() stdout should be 'claude-code', got %r" % captured
    )


def _count_from_cover(cover_path):
    """Parse a trace .cover file: count executed/total executable lines and collect misses."""
    executed = 0
    total = 0
    missed = []
    line_no = 0
    with open(cover_path, "r", encoding="utf-8") as fh:
        for raw in fh:
            line_no += 1
            # trace lines look like ">>>>>> code" (missed), "    N: code" (hit N times),
            # or "       code" (non-executable: blank/comment/continuation).
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
    covdir = tempfile.mkdtemp(prefix="acs-cov-codex-")
    try:
        tracer = trace.Trace(count=1, trace=0)
        # Silence argparse error output during the invalid-value branch so the
        # harness output stays clean.
        devnull = open(os.devnull, "w")
        real_stderr = sys.stderr
        sys.stderr = devnull
        try:
            tracer.runfunc(_drive)
        finally:
            sys.stderr = real_stderr
            devnull.close()

        results = tracer.results()
        results.write_results(summary=False, coverdir=covdir)

        # Find the produced .cover for codex_adapter.
        cover_file = None
        for name in os.listdir(covdir):
            if name.endswith(".cover") and "codex_adapter" in name:
                cover_file = os.path.join(covdir, name)
                break
        if cover_file is None:
            print("ERROR: no codex_adapter .cover produced in %s" % covdir)
            return 2

        executed, total, missed = _count_from_cover(cover_file)
        pct = (executed * 100.0 / total) if total else 0.0
        print("codex_adapter.py coverage: %d/%d executable lines = %.1f%% (gate %.0f%%)"
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
