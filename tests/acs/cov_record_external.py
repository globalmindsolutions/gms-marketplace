#!/usr/bin/env python3
"""Reproducible stdlib-`trace` line-coverage harness for record-external.py (MAR-84 spec 01).

The repo is Python 3.9+ stdlib-only (no pip) — the pip `coverage` package is NOT
installed — so coverage is measured with the stdlib `trace` module, mirroring
tests/acs/cov_pr_conventions.py. This harness drives record_external() and
main() across every branch (successful write, product-flow refusal,
not-found/archived refusal, build_context GateError, argparse success +
missing-arg usage error) under trace.Trace(count=1, trace=0), then reports:

    executed executable lines / total executable lines -> percentage  (gate: >= 90%)

and the missed-line list.  Run:  python3 tests/acs/cov_record_external.py
(exit 0 iff coverage >= GATE).
"""

import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import trace

GATE = 90.0

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_TESTS_DIR))
_SCRIPTS_DIR = os.path.join(_REPO_ROOT, "plugins", "acs", "hooks", "scripts")
_TARGET = os.path.join(_SCRIPTS_DIR, "record-external.py")

if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)


def _load_target_fresh():
    """Import record-external.py from source as a fresh module object (inside the tracer)."""
    sys.modules.pop("record_external_cov_target", None)
    sys.modules.pop("acs_lib", None)
    spec = importlib.util.spec_from_file_location("record_external_cov_target", _TARGET)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["record_external_cov_target"] = mod
    spec.loader.exec_module(mod)
    return mod


def _run_main(mod, argv):
    """Drive mod.main() in-process (sets sys.argv, catches its own sys.exit)."""
    real_argv = sys.argv[:]
    real_stdout = sys.stdout
    sys.argv = ["record-external.py"] + argv
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


def _seed_repo(tmp):
    """Build a throwaway git repo + workspace with one non-epic ticket and one
    product-flow-titled ticket, mirroring AcsWorkspaceCase's fixture."""
    repo = os.path.join(tmp, "shop")
    ws = os.path.join(tmp, "workspace")
    os.makedirs(repo)
    subprocess.run(["git", "init", "-q", repo], check=True)
    subprocess.run(["git", "-C", repo, "remote", "add", "origin",
                    "https://github.com/acme/shop.git"], check=True)
    os.makedirs(os.path.join(repo, ".acs"))
    with open(os.path.join(repo, ".acs", "settings.json"), "w") as fh:
        json.dump({"ticket_prefix": "SHOP", "test_coverage_percent": 90}, fh)
    with open(os.path.join(repo, ".acs", "settings.local.json"), "w") as fh:
        json.dump({"workspace_path": ws}, fh)

    def mint(title, ttype="task"):
        out = subprocess.run(
            [sys.executable, os.path.join(_SCRIPTS_DIR, "new-ticket.py"),
             "--title", title, "--type", ttype],
            cwd=repo, capture_output=True, text=True,
        )
        assert out.returncode == 0, out.stderr
        return json.loads(out.stdout)["ticket_id"]

    normal_id = mint("Add health endpoint")
    product_id = mint("Product definition (PRD)")
    return repo, normal_id, product_id


def _drive():
    """Fresh-import record-external.py and exercise every branch — all inside the traced call."""
    mod = _load_target_fresh()

    tmp = tempfile.mkdtemp(prefix="acs-cov-recext-")
    try:
        repo, normal_id, product_id = _seed_repo(tmp)

        # --- record_external(): successful write ---
        ok, payload = mod.record_external(repo, normal_id, "github", "123")
        assert ok is True
        assert payload == {"ticket_id": normal_id, "external": {"provider": "github", "key": "123"}}

        # --- record_external(): product-flow refusal ---
        ok, message = mod.record_external(repo, product_id, "github", "999")
        assert ok is False
        assert "product-flow" in message

        # --- record_external(): not-found refusal ---
        ok, message = mod.record_external(repo, "SHOP-9999", "github", "1")
        assert ok is False
        assert "not found" in message

        # --- record_external(): archived refusal ---
        import acs_lib as lib
        ctx = lib.build_context(repo)
        tdir = lib.ticket_dir(ctx["workspace"], ctx["repo_id"], normal_id)
        archive_dir = lib.archive_dir(ctx["workspace"], ctx["repo_id"])
        os.makedirs(archive_dir, exist_ok=True)
        shutil.move(tdir, os.path.join(archive_dir, normal_id))
        ok, message = mod.record_external(repo, normal_id, "github", "1")
        assert ok is False
        assert "not found" in message
        # restore for the argparse-driven calls below
        shutil.move(os.path.join(archive_dir, normal_id), tdir)

        # --- record_external(): build_context GateError (no .acs/settings.json) ---
        bare = os.path.join(tmp, "bare")
        os.makedirs(bare)
        subprocess.run(["git", "init", "-q", bare], check=True)
        raised = False
        try:
            mod.record_external(bare, "X-1", "github", "1")
        except lib.GateError:
            raised = True
        assert raised

        # --- main(): success path (argparse + stdout JSON + exit 0) ---
        real_cwd = os.getcwd()
        os.chdir(repo)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                code, out = _run_main(mod, [
                    "--ticket", normal_id, "--provider", "github", "--key", "456",
                ])
            assert code == 0
            assert '"ticket_id"' in out

            # --- main(): refusal path (product-flow, exit non-zero) ---
            with contextlib.redirect_stderr(io.StringIO()):
                with contextlib.redirect_stdout(io.StringIO()):
                    code, _out = _run_main(mod, [
                        "--ticket", product_id, "--provider", "github", "--key", "1",
                    ])
            assert code != 0

            # --- main(): GateError path (run from the bare repo) ---
            os.chdir(bare)
            with contextlib.redirect_stderr(io.StringIO()):
                with contextlib.redirect_stdout(io.StringIO()):
                    code, _out = _run_main(mod, [
                        "--ticket", "X-1", "--provider", "github", "--key", "1",
                    ])
            assert code == 2
        finally:
            os.chdir(real_cwd)

        # --- main(): argparse usage error (missing required arg) ---
        with contextlib.redirect_stderr(io.StringIO()):
            with contextlib.redirect_stdout(io.StringIO()):
                code, _out = _run_main(mod, ["--ticket", "X-1"])
        assert code == 2
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


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
    covdir = tempfile.mkdtemp(prefix="acs-cov-recext-out-")
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
            if name == "record-external.cover":
                cover_file = os.path.join(covdir, name)
                break
        if cover_file is None:
            print("ERROR: no record-external .cover produced in %s" % covdir)
            return 2

        executed, total, missed = _count_from_cover(cover_file)
        pct = (executed * 100.0 / total) if total else 0.0
        print("record-external.py coverage: %d/%d executable lines = %.1f%% (gate %.0f%%)"
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
