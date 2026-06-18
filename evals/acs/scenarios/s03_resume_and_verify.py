"""s03 — resume-from-state + verifier-clean + PR-size (paid, G2 + G3 + G4).

Seeds the pipeline to "ready for /acs:code" deterministically (mint a task,
mark create-spec done, drop a real spec file) — no `claude` spent yet — then
runs ONE fresh `claude -p` session that is told *only the ticket id*. The
session must discover the work from the ticket's specs in the workspace
(resume from state only, **G2**), implement it via the code TDD cycle and pass
the verifier so the create-pr gate opens (verifier-clean, **G3**), and the
resulting change must stay under the ~400-line PR-size cap (**G4**, measured as
the repo diff since the seed — no forge needed).

The G2 evidence is concrete: the prompt never names "/health", so an
implementation that wires `/health` can only have come from reading the seeded
spec out of workspace state.
"""

import os

from harness import Sandbox, Check

META = {
    "name": "resume_and_verify",
    "tier": "paid",
    "goal": "G2+G3+G4",
    "summary": "fresh code session resumes from specs, verifies clean, under PR-size cap",
}

SPEC = """# Spec 01 — GET /health

## Behavior
- Expose an HTTP endpoint `GET /health`.
- It responds `200` with the body exactly `ok`.
- The body must come from the existing `health()` function in `app.py`
  (single source of truth) — do not hard-code the `"ok"` literal elsewhere.

## Test plan
- An automated test asserts a `GET /health` request yields status `200` and
  body `ok`.
"""

PROMPT = (
    "Run the /acs:code skill for ticket EVAL-1. I am giving you no other "
    "context: determine everything you need from the acs workspace state and "
    "the ticket's specs. Do not ask me anything. Complete the code TDD cycle."
)


def _repo_mentions(repo, needle):
    """True if any non-vcs source file in the repo working tree contains needle."""
    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in (".git", ".acs", "__pycache__")]
        for name in files:
            try:
                with open(os.path.join(root, name), encoding="utf-8") as fh:
                    if needle in fh.read():
                        return True
            except (UnicodeDecodeError, OSError):
                continue
    return False


def run():
    check = Check(META["name"])
    with Sandbox(prefix="EVAL", slug="shop", init=True) as sb:
        # --- deterministic seed: pipeline at "ready for /acs:code" ---------
        tid = sb.mint_ticket("Add a /health endpoint returning ok", "task",
                             needs_design=False)
        sb.start_run("create-spec", tid)
        specs = sb.ticket_path(tid, "specs")
        os.makedirs(specs, exist_ok=True)
        with open(os.path.join(specs, "01-health.md"), "w") as fh:
            fh.write(SPEC)
        sb.complete_run("create-spec", tid,
                        {"status": "completed", "states": {"specs": ["01-health"]}})
        code_gate, _ = sb.gate("code", tid)
        if not check.ok("seed reached code-ready state", code_gate == 0,
                        "code gate exit=%s" % code_gate):
            return check

        # --- one paid session, told only the ticket id --------------------
        r = sb.run_skill(PROMPT)
        check.cost = r.get("cost_usd")
        if not check.ok("claude code session completed", r["ok"],
                        (r.get("stderr") or r.get("raw") or "")[:200]):
            return check

        # G2: implementation reflects the spec it could only have read from state
        check.ok("resumed from state: wired /health (never named in prompt)",
                 _repo_mentions(sb.repo, "/health"))

        # pipeline advanced code -> completed
        ps = sb.ticket_json(tid, "pipeline-state.json")
        check.eq("code step completed",
                 ps.get("steps", {}).get("code", {}).get("status"), "completed")

        # G3: verifier passed => the create-pr gate now opens
        pr_gate, err = sb.gate("create-pr", tid)
        check.ok("verifier-clean: create-pr gate opened after code",
                 pr_gate == 0, "exit=%s %s" % (pr_gate, err))

        # G4: the change a PR would carry stays under the ~400-line cap
        lines = sb.changed_lines()
        check.ok("PR-size under cap (G4): %d <= 400 changed lines" % lines,
                 lines <= 400, "lines=%d" % lines)

    return check
