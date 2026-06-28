"""s04 — routing evals for all 16 skills (paid, E1.2).

Three kinds of probe, covering every skill:

1. Description-trigger (14 model-invocable skills): a natural-language request
   that describes the intent *without naming the skill* must route to that
   skill. A miss is a real finding — the skill's `description` frontmatter
   isn't discriminating that request from its neighbors.

2. Explicit-invocation (the 2 user-only skills `install-hooks` and `update`,
   which set `disable-model-invocation: true`): the explicit `/acs:<skill>`
   command must still route to the skill. The model is forbidden from
   auto-routing to these, so a description probe can't reach them — but the
   explicit path the user types must work.

3. Negative-routing (same 2 user-only skills): a bare description of their
   intent must NOT auto-route to them, proving `disable-model-invocation` is
   honored — the model should pick a different skill or no skill at all.

All probes assert on the first `Skill` tool_use the model makes (captured and
then killed, so the skill body never runs).
"""

from harness import Sandbox, Check

META = {
    "name": "skill_triggers",
    "tier": "paid",
    "goal": "route",
    "summary": "right skill routes for all 16 (14 by description, 2 user-only by explicit cmd + no-auto-route)",
}

# Description-trigger + explicit-invocation cases.
# (label, init?, request, expected skill).
#   - The 14 model-invocable skills use a request that avoids naming the skill.
#   - The 2 user-only skills (install-hooks, update) set
#     disable-model-invocation, so they can only be reached by the explicit
#     `/acs:<skill>` command — a description would never route to them. Their
#     positive case is therefore the literal explicit invocation; their
#     no-auto-route guarantee is covered by NEGATIVE below.
CASES = [
    ("init", False,
     "Set up and initialize the acs configuration for this repository.",
     "init"),
    ("ship", True,
     "Take a CSV-export feature all the way from idea to an open pull request — "
     "drive the whole delivery pipeline end to end.",
     "ship"),
    ("handoff", True,
     "Let's stop here and hand this work off to a fresh session so I can "
     "resume it later without losing state.",
     "handoff"),
    ("create-prd", True,
     "Write the product requirements document — vision, personas, goals and "
     "success metrics — for this product.",
     "create-prd"),
    ("create-architecture", True,
     "Generate the architecture documentation: the C4 diagrams and the "
     "high- and low-level design flows for this product.",
     "create-architecture"),
    ("create-project", True,
     "Scaffold the repository skeleton — build config, test framework, CI — "
     "from the approved architecture docs.",
     "create-project"),
    ("create-ticket", True,
     "Create a ticket to add a dark mode toggle to the settings page.",
     "create-ticket"),
    ("create-design", True,
     "Settle the system design for ticket EVAL-1, weighing options and "
     "trade-offs, before we start implementing it.",
     "create-design"),
    ("create-spec", True,
     "Break ticket EVAL-1 down into dependency-ordered implementation specs.",
     "create-spec"),
    ("code", True,
     "Implement ticket EVAL-1 from its specs, using TDD on a dedicated branch.",
     "code"),
    ("create-pr", True,
     "Open the pull request for ticket EVAL-1's finished implementation.",
     "create-pr"),
    ("merge-pr", True,
     "Land ticket EVAL-1: merge its pull request and finish the ticket.",
     "merge-pr"),
    ("metrics", True,
     "Show me a dashboard of throughput, cost, coverage and review effort for "
     "this repo, read straight from the workspace state — no external tools.",
     "metrics"),
    ("usage", True,
     "Show me a breakdown of AI spend, token consumption, and average working "
     "time per ticket for this repo — not delivery throughput, just the tool "
     "usage and cost side.",
     "usage"),
    # User-only skills: positive case = the explicit command the user types.
    # (A description can't reach them — see NEGATIVE for that guarantee.)
    ("install-hooks", True,
     "/acs:install-hooks",
     "install-hooks"),
    ("update", True,
     "/acs:update",
     "update"),
]

# Negative-routing cases for the two user-only skills: a bare description of
# their intent must NOT auto-route to them (disable-model-invocation is
# honored). PASS when the model picks anything other than the forbidden skill
# — a different skill, or no skill at all (None).
# (label, init?, request, forbidden skill)
NEGATIVE = [
    ("install-hooks", True,
     "Set up the local git hooks for this clone so our configured commit-message "
     "and branch-name conventions are enforced before anything gets pushed.",
     "install-hooks"),
    ("update", True,
     "Check whether there's a newer version of the acs plugin available and "
     "summarize what changed since the version I have installed.",
     "update"),
]


def run():
    check = Check(META["name"])

    def _norm(skill):
        # The Skill tool_use may report the skill name bare ("init") or
        # namespaced ("acs:init") depending on the runtime; compare on the
        # bare name so the assertion is independent of that.
        return skill.split(":", 1)[-1] if isinstance(skill, str) else skill

    for label, init, request, expected in CASES:
        want = "acs:" + expected
        with Sandbox(prefix="EVAL", slug="trig", init=init) as sb:
            # Routing is mildly non-deterministic; re-probe up to twice before
            # calling it a miss. Cheap (~5s/probe) and contained to the flaky
            # case — no whole-suite retry needed.
            got = sb.trigger(request)
            for _ in range(2):
                if _norm(got) == expected:
                    break
                got = sb.trigger(request)
        check.ok("%-20s -> %s" % (label, want), _norm(got) == expected, "got=%r" % got)

    # Negative routing: a bare description must NOT auto-invoke a user-only
    # skill. One probe is enough — a single auto-route is already a failure;
    # re-probing could only mask a real disable-model-invocation regression.
    for label, init, request, forbidden in NEGATIVE:
        with Sandbox(prefix="EVAL", slug="trig", init=init) as sb:
            got = sb.trigger(request)
        check.ok("%-20s -/> %s (no auto-route)" % (label, "acs:" + forbidden),
                 _norm(got) != forbidden, "got=%r" % got)
    return check
