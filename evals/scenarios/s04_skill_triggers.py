"""s04 — description-trigger evals for all 12 skills (paid, E1.2).

For each skill, a natural-language request that describes the intent *without
naming the skill* must route to that skill. Asserts on the first `Skill`
tool_use the model makes (captured and then killed, so the skill body never
runs). A miss is a real finding: the skill's `description` frontmatter isn't
discriminating that request from its neighbors.
"""

from harness import Sandbox, Check

META = {
    "name": "skill_triggers",
    "tier": "paid",
    "goal": "route",
    "summary": "the right skill fires for a natural-language request (all 12)",
}

# (label, init?, request, expected skill) — requests avoid naming the skill.
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
     "Merge the pull request for ticket EVAL-1 now that it has been approved.",
     "merge-pr"),
]


def run():
    check = Check(META["name"])
    for label, init, request, expected in CASES:
        want = "acs:" + expected
        with Sandbox(prefix="EVAL", slug="trig", init=init) as sb:
            got = sb.trigger(request)
            if got != want:
                # Routing is mildly non-deterministic; re-probe once before
                # calling it a miss. Cheap (one ~5s probe) and contained to the
                # flaky case — no whole-suite retry needed.
                got = sb.trigger(request)
        check.ok("%-20s -> %s" % (label, want), got == want, "got=%r" % got)
    return check
