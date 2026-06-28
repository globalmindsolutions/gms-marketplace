"""s06 — /acs:update local logic: semver compare + Step-6 migration checks (free).

The /acs:update skill is mostly a paid workflow (it reasons over a changelog
delta with a real model), but two of its load-bearing steps are pure,
deterministic logic that the free tier can certify offline:

  * Step 3 — semver compare: installed vs latest must classify into exactly
    "update available" (installed < latest), "up to date" (==), or "dev copy"
    (installed > latest), compared numerically (split on ".", compare tuples),
    never as strings (so "0.10.0" > "0.9.0").
  * Step 6 — post-update migration checks: settings still validate against the
    schema (`acs_lib.validate_settings`), and the workspace requirement is
    enforced. On INVALID the skill recommends `/acs:init`.

This scenario drives the *installed build's* `acs_lib` directly (the same module
the skill's Step-6 snippet imports) so it certifies the shipped behavior, and
replicates the documented Step-3 comparison rule to prove it is sound and
unambiguous on the cases the skill must distinguish. `tests/` covers
`validate_settings` on the source tree; this asserts it against the packaged
build the way `/acs:update` actually calls it.
"""

import importlib.util
import os

from harness import Sandbox, Check, _version_key

META = {
    "name": "update_migration",
    "tier": "free",
    "goal": "update",
    "summary": "/acs:update semver compare + Step-6 migration checks (settings valid, workspace enforced)",
}


def _classify(installed, latest):
    """Replicate the skill's Step-3 numeric semver verdict.

    Returns "update-available" | "up-to-date" | "dev-copy". Uses the harness's
    _version_key (split on '.', integer tuples) — the exact "compare as tuples,
    never as strings" rule the skill mandates.
    """
    ik, lk = _version_key(installed), _version_key(latest)
    if ik < lk:
        return "update-available"
    if ik > lk:
        return "dev-copy"
    return "up-to-date"


def _load_acs_lib(scripts_dir):
    """Import the *installed build's* acs_lib — the module /acs:update Step 6 uses."""
    path = os.path.join(scripts_dir, "acs_lib.py")
    spec = importlib.util.spec_from_file_location("acs_lib_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run():
    check = Check(META["name"])

    # -- Step 3: semver compare (pure logic, no sandbox needed) ------------- #
    # Numeric tuple comparison, not lexical: 0.10.0 must beat 0.9.0.
    check.eq("0.2.0 < 0.3.0 -> update available",
             _classify("0.2.0", "0.3.0"), "update-available")
    check.eq("0.3.0 == 0.3.0 -> up to date",
             _classify("0.3.0", "0.3.0"), "up-to-date")
    check.eq("0.4.0 > 0.3.0 -> dev copy",
             _classify("0.4.0", "0.3.0"), "dev-copy")
    check.eq("0.10.0 > 0.9.0 -> numeric, not lexical",
             _classify("0.10.0", "0.9.0"), "dev-copy")

    # -- Step 6: migration checks against the installed build's acs_lib ----- #
    with Sandbox(prefix="EVAL", slug="upd", init=True) as sb:
        lib = _load_acs_lib(sb.scripts)

        # Healthy repo: settings load and validate -> migration "settings: valid".
        settings, found = lib.load_settings(sb.repo)
        check.ok("migration: seeded settings load", len(found) >= 1,
                 "found=%r" % found)
        try:
            ws = lib.validate_settings(settings, sb.repo)
            check.ok("migration: valid settings pass validate_settings", True)
            check.ok("migration: workspace resolves outside the repo",
                     bool(ws) and os.path.commonpath([ws, sb.repo]) != sb.repo,
                     "ws=%r repo=%r" % (ws, sb.repo))
        except lib.GateError as exc:
            check.ok("migration: valid settings pass validate_settings", False,
                     "unexpected GateError: %s" % exc)

        # Broken settings: a bad merge_strategy must be caught -> skill says
        # "settings: INVALID" and recommends /acs:init.
        bad = dict(settings)
        bad["merge_strategy"] = "fast-forward"  # not squash|merge|rebase
        try:
            lib.validate_settings(bad, sb.repo)
            check.ok("migration: invalid settings flagged (recommend /acs:init)",
                     False, "validate_settings accepted a bad merge_strategy")
        except lib.GateError as exc:
            check.ok("migration: invalid settings flagged (recommend /acs:init)",
                     "merge_strategy" in str(exc), str(exc))

        # Workspace requirement: missing workspace_path must block (the Step-6
        # "workspace reachable" / not-initialized case).
        no_ws = {k: v for k, v in settings.items() if k != "workspace_path"}
        try:
            lib.validate_settings(no_ws, sb.repo)
            check.ok("migration: missing workspace_path flagged", False,
                     "validate_settings accepted a missing workspace_path")
        except lib.GateError as exc:
            check.ok("migration: missing workspace_path flagged",
                     "workspace_path" in str(exc), str(exc))

    return check
