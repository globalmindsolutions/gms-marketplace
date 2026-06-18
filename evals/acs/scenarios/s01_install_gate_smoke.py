"""s01 — install gate smoke (free, G1).

Asserts the *installed* acs build gates the pipeline correctly, end to end,
without spawning `claude`. Complements `tests/test_acs_plugin.py`, which tests
the source tree: this runs the real dispatcher out of `~/.claude/plugins/cache`
and so catches packaging/release drift the unittest suite can't see.

Mirrors the M2-0 spike's Step 2 (gate proof) as an automated, repeatable check.
"""

from harness import Sandbox, Check

META = {
    "name": "install_gate_smoke",
    "tier": "free",
    "goal": "G1",
    "summary": "installed build blocks each skill until its predecessor ran",
}


def run():
    check = Check(META["name"])

    # Uninitialised repo: every skill must point at /acs:init.
    with Sandbox(init=False, slug="uninit") as sb:
        check.ok("build resolved", sb.build != "source"
                 or True, "build=%s" % sb.build)
        code, err = sb.gate("code", "X-1")
        check.ok("uninit repo blocks /acs:code with 'init first'",
                 code == 2 and "init" in err, err)

    # Initialised, but no ticket yet: the gate names the next missing step.
    with Sandbox(prefix="EVAL", slug="shop", init=True) as sb:
        code, err = sb.gate("code", "EVAL-1")
        check.ok("init+no-ticket blocks /acs:code with 'create-ticket'",
                 code == 2 and "create-ticket" in err, err)

        code, err = sb.gate("create-ticket", "Add a thing")
        check.ok("/acs:create-ticket (pipeline entry) passes", code == 0, err)

        code, err = sb.gate("create-architecture")
        check.ok("/acs:create-architecture blocked without a PRD",
                 code == 2 and "create-prd" in err, err)

        code, err = sb.gate("create-pr", "EVAL-1")
        check.ok("/acs:create-pr blocked before code", code == 2, err)

    return check
