#!/usr/bin/env python3
"""run-tests.py — acs CI tests + coverage gate.

Installed by /acs:init into the consumer repo at .acs/ci/run-tests.py and run by
.github/workflows/acs-tests.yml on every PR. The CI runner has no acs install,
so this reads the suite command from the committed <repo>/.acs/settings.json,
runs the optional setup then the command, and exits with the command's status.

Coverage is the command's responsibility — delegate to the tool, e.g.
`pytest --cov --cov-fail-under=$ACS_COVERAGE`. acs exports ACS_COVERAGE
(= settings.test_coverage_percent) into the environment so the command can
reference it. A failing suite OR a coverage shortfall fails the check.
"""

import json
import os
import subprocess
import sys

SETTINGS = os.path.join(".acs", "settings.json")


def fail(msg):
    sys.stderr.write("acs run-tests: %s\n" % msg)
    sys.exit(1)


def main():
    if not os.path.isfile(SETTINGS):
        fail("%s not found — commit project settings, or run /acs:init." % SETTINGS)
    try:
        with open(SETTINGS, encoding="utf-8") as fh:
            settings = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        fail("cannot read %s: %s" % (SETTINGS, exc))

    tests = settings.get("tests")
    if not isinstance(tests, dict) or not tests.get("command"):
        fail("no `tests.command` in %s — re-run /acs:init and enable the tests "
             "CI gate (the command must run the suite and fail on coverage "
             "shortfall)." % SETTINGS)

    coverage = settings.get("test_coverage_percent", 90)
    env = dict(os.environ)
    env["ACS_COVERAGE"] = str(coverage)

    setup = tests.get("setup")
    if setup:
        print("::group::acs tests — setup\n$ %s" % setup, flush=True)
        rc = subprocess.run(setup, shell=True, env=env).returncode
        print("::endgroup::", flush=True)
        if rc != 0:
            fail("setup failed (exit %d): %s" % (rc, setup))

    command = tests["command"]
    print("acs tests — ACS_COVERAGE=%s\n$ %s" % (coverage, command), flush=True)
    rc = subprocess.run(command, shell=True, env=env).returncode
    if rc != 0:
        fail("test suite / coverage gate failed (exit %d)." % rc)
    print("acs tests — passed (suite green, coverage gate >= %s%%)." % coverage)


if __name__ == "__main__":
    main()
