"""Contract tests for the prose layer: SKILL.md and agent definitions.

Skills and agents are product code written in markdown — a stale path, a
missing section, or a contradiction with the deterministic layer breaks the
pipeline even when every Python test passes. This module pins the structural
invariants that INTERNALS.md / AUTHORING.md declare, so drift fails CI
instead of surfacing mid-pipeline. (Behavioral quality — does the model
follow the prose — is the agentic-e2e tier, not unit-testable.)
"""

import glob
import os
import re
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLUGIN = os.path.join(REPO_ROOT, "plugins", "acs")

HOOKED_SKILLS = ["create-prd", "create-architecture", "create-project",
                 "create-ticket", "create-design", "create-spec", "code",
                 "create-pr", "merge-pr"]
ALL_SKILLS = HOOKED_SKILLS + ["init", "ship", "handoff", "update", "install-hooks", "metrics", "usage"]
ROLES = ["planner", "executor", "verifier"]


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def frontmatter(text, path):
    parts = text.split("---\n", 2)
    assert len(parts) >= 3 and parts[0] == "", "%s: missing frontmatter" % path
    return parts[1], parts[2]


class TestSkillContracts(unittest.TestCase):
    def skill_path(self, name):
        return os.path.join(PLUGIN, "skills", name, "SKILL.md")

    def test_all_skills_exist_no_strays(self):
        found = sorted(os.path.basename(os.path.dirname(p))
                       for p in glob.glob(os.path.join(PLUGIN, "skills", "*", "SKILL.md")))
        self.assertEqual(found, sorted(ALL_SKILLS))

    def test_frontmatter_and_name_matches_directory(self):
        for name in ALL_SKILLS:
            text = read(self.skill_path(name))
            fm, _body = frontmatter(text, name)
            self.assertRegex(fm, r"(?m)^name: %s$" % re.escape(name))
            self.assertRegex(fm, r"(?m)^description: \S")

    def test_hooked_skills_call_their_lifecycle_scripts(self):
        for name in HOOKED_SKILLS:
            body = read(self.skill_path(name))
            self.assertIn("skill-start.py", body, name)
            self.assertRegex(body, r"--skill %s\b" % re.escape(name), name)
            self.assertIn("post-%s.py" % name, body, name)
            self.assertIn("validate_xml.py", body, name)

    def test_every_skill_has_completion_report(self):
        for name in ALL_SKILLS:
            self.assertIn("## Completion report (normative)",
                          read(self.skill_path(name)), name)

    def test_hooked_skills_have_clarification_ledger_rule(self):
        for name in HOOKED_SKILLS:
            body = read(self.skill_path(name))
            self.assertIn("Clarification ledger first.", body, name)
            self.assertIn("clarify.py", body, name)

    def test_coordinator_tool_restrictions(self):
        for name in HOOKED_SKILLS + ["ship"]:
            fm, _ = frontmatter(read(self.skill_path(name)), name)
            self.assertRegex(fm, r"(?m)^disallowed-tools: Edit, NotebookEdit$", name)
        for name in ("init", "handoff", "update", "install-hooks"):
            fm, _ = frontmatter(read(self.skill_path(name)), name)
            self.assertNotIn("disallowed-tools", fm, name)

    def test_ship_no_per_step_subagent_spawn(self):
        # /acs:ship drives the pipeline by invoking each step skill DIRECTLY via
        # the Skill tool — not by spawning a general-purpose subagent per step
        # (a subagent cannot spawn the step skill's planner/executor/verifier).
        # Guard the antipattern, not exact positive wording, so the test stays
        # stable across legitimate future edits to the direct-invocation prose.
        body = read(self.skill_path("ship"))
        self.assertNotIn('subagent_type: "general-purpose"', body)
        self.assertNotIn("one subagent per step", body)
        self.assertIsNone(re.search(r"spawn a fresh subagent", body, re.IGNORECASE))

    def test_user_action_only_skills(self):
        # update + install-hooks change the environment; merge-pr is now
        # agent/model-invocable (MAR-42), so it is NOT in this set.
        user_action = ("update", "install-hooks")
        for name in user_action:
            fm, _ = frontmatter(read(self.skill_path(name)), name)
            self.assertRegex(fm, r"(?m)^disable-model-invocation: true$", name)
        for name in ALL_SKILLS:
            if name in user_action:
                continue
            fm, _ = frontmatter(read(self.skill_path(name)), name)
            self.assertNotIn("disable-model-invocation: true", fm, name)

    def test_merge_pr_is_agent_invocable(self):
        # MAR-42: /acs:merge-pr is agent/model-invocable; the readiness gate +
        # branch protection are the merge brakes, and merges require an APPROVED
        # review (m6). The old user-action-only invariant must be gone.
        text = read(self.skill_path("merge-pr"))
        fm, body = frontmatter(text, "merge-pr")
        self.assertNotIn("disable-model-invocation", fm,
                         "merge-pr must not set disable-model-invocation (MAR-42)")
        self.assertNotIn("User action only", body,
                         "merge-pr must drop the 'User action only' section (MAR-42)")
        self.assertNotIn("user-invoked only", body,
                         "merge-pr must drop the 'user-invoked only' framing (MAR-42)")
        self.assertIn("Invocation and safety model", body,
                      "merge-pr must carry the new invocation/safety section (MAR-42)")
        self.assertRegex(body, r"(?i)reviewDecision`? is `?APPROVED",
                         "merge-pr approvals dimension must require APPROVED (m6)")

    def test_no_forked_context_in_frontmatter(self):
        # context: fork would break clarifying questions (AUTHORING.md)
        for name in ALL_SKILLS:
            fm, _ = frontmatter(read(self.skill_path(name)), name)
            self.assertNotRegex(fm, r"(?m)^context:", name)
            self.assertNotRegex(fm, r"(?m)^model:", name)


class TestAgentContracts(unittest.TestCase):
    def agent_path(self, skill, role):
        return os.path.join(PLUGIN, "agents", "%s-%s.md" % (skill, role))

    def test_all_27_agents_exist_no_strays(self):
        expected = sorted("%s-%s.md" % (s, r) for s in HOOKED_SKILLS for r in ROLES)
        found = sorted(os.path.basename(p)
                       for p in glob.glob(os.path.join(PLUGIN, "agents", "*.md")))
        self.assertEqual(found, expected)

    def test_frontmatter_name_description(self):
        for skill in HOOKED_SKILLS:
            for role in ROLES:
                fm, _ = frontmatter(read(self.agent_path(skill, role)), skill + role)
                self.assertRegex(fm, r"(?m)^name: %s-%s$" % (re.escape(skill), role))
                self.assertIn("not for direct invocation", fm)
                self.assertNotRegex(fm, r"(?m)^model:")    # settings.json owns models
                self.assertNotRegex(fm, r"(?m)^effort:")

    def test_role_tool_restrictions(self):
        for skill in HOOKED_SKILLS:
            for role in ("planner", "verifier"):
                fm, _ = frontmatter(read(self.agent_path(skill, role)), skill)
                self.assertRegex(fm, r"(?m)^tools: Read, Glob, Grep, Bash, Write$",
                                 "%s-%s" % (skill, role))
            fm, _ = frontmatter(read(self.agent_path(skill, "executor")), skill)
            self.assertRegex(fm, r"(?m)^disallowedTools: Agent, Skill$", skill)
            self.assertNotRegex(fm, r"(?m)^tools:", skill)  # executors keep broad access

    def test_grounding_section_everywhere(self):
        for skill in HOOKED_SKILLS:
            for role in ROLES:
                body = read(self.agent_path(skill, role))
                self.assertIn("## Grounding (anti-hallucination)", body,
                              "%s-%s" % (skill, role))
                if role == "verifier":
                    self.assertIn("police grounding", body, skill)

    def test_phase_artifact_mandated(self):
        artifact = {"planner": "plan", "executor": "execute", "verifier": "verify"}
        for skill in HOOKED_SKILLS:
            for role, kind in artifact.items():
                body = read(self.agent_path(skill, role))
                self.assertRegex(body, r"iter-<n(?:>|\b)[^\n]*%s" % kind,
                                 "%s-%s missing iter-<n>-%s artifact" % (skill, role, kind))

    def test_no_stale_heredoc_claims(self):
        # the drift this session actually found — keep it dead
        for path in glob.glob(os.path.join(PLUGIN, "agents", "*.md")):
            body = read(path)
            self.assertNotIn("no Write tool", body, path)
            self.assertNotIn("heredoc", body, path)

    def test_result_is_final_message(self):
        for skill in HOOKED_SKILLS:
            for role in ROLES:
                body = read(self.agent_path(skill, role))
                self.assertIn("<result", body, "%s-%s" % (skill, role))
                self.assertIn("FINAL message", body, "%s-%s" % (skill, role))


class TestCrossReferences(unittest.TestCase):
    """Every path the prose tells the model to use must exist on disk."""

    def collect_bodies(self):
        for pattern in ("skills/*/SKILL.md", "agents/*.md"):
            for path in glob.glob(os.path.join(PLUGIN, pattern)):
                yield path, read(path)

    def test_referenced_helper_scripts_exist(self):
        for path, body in self.collect_bodies():
            for script in set(re.findall(r"hooks/scripts/([a-zA-Z0-9_\-]+\.py)", body)):
                target = os.path.join(PLUGIN, "hooks", "scripts", script)
                self.assertTrue(os.path.isfile(target),
                                "%s references missing script %s" % (path, script))

    def test_referenced_schemas_exist(self):
        for path, body in self.collect_bodies():
            for schema in set(re.findall(r"schemas/([a-zA-Z0-9_\-\.]+\.(?:xsd|json))", body)):
                target = os.path.join(PLUGIN, "schemas", schema)
                self.assertTrue(os.path.isfile(target),
                                "%s references missing schema %s" % (path, schema))

    def test_skills_reference_existing_agents(self):
        for path, body in self.collect_bodies():
            for skill, role in set(re.findall(
                    r"acs:(%s)-(planner|executor|verifier)" % "|".join(HOOKED_SKILLS), body)):
                target = os.path.join(PLUGIN, "agents", "%s-%s.md" % (skill, role))
                self.assertTrue(os.path.isfile(target),
                                "%s references missing agent %s-%s" % (path, skill, role))

    def test_referenced_templates_exist(self):
        for path, body in self.collect_bodies():
            for name in set(re.findall(r"\b(pr|epic|story|task)-default\b", body)):
                target = os.path.join(PLUGIN, "templates", "%s-default.md" % name)
                self.assertTrue(os.path.isfile(target), "%s -> %s-default" % (path, name))


class TestExemptPrDocs(unittest.TestCase):
    """MAR-9 (spec 04): the exempt --pr merge path and the /acs:init CLAUDE.md
    managed block must stay surfaced in the merge-pr skill prose and the docs.
    Additive existence/section assertions only — they pin the new prose so a
    later edit that drops it fails CI. No existing assertion is modified."""

    def skill_path(self, name):
        return os.path.join(PLUGIN, "skills", name, "SKILL.md")

    def doc_path(self, *parts):
        return os.path.join(PLUGIN, *parts)

    def test_merge_pr_argument_hint_includes_pr_form(self):
        fm, _ = frontmatter(read(self.skill_path("merge-pr")), "merge-pr")
        self.assertRegex(
            fm, r'(?m)^argument-hint: "\[ticket-id\] \| --pr PRNUMBER"$')

    def test_merge_pr_has_exempt_mode_section(self):
        body = read(self.skill_path("merge-pr"))
        self.assertIn("Exempt non-ticket PR mode", body)

    def test_init_documents_claude_md_managed_block(self):
        body = read(self.skill_path("init"))
        self.assertIn("CLAUDE.acs.md", body)
        self.assertIn("upsert_managed_block", body)

    def test_internals_mentions_exempt_pr_merge(self):
        body = read(self.doc_path("docs", "INTERNALS.md"))
        self.assertIn("--pr", body)
        self.assertIn("CLAUDE.acs.md", body)

    def test_readme_mentions_exempt_pr_merge(self):
        body = read(self.doc_path("README.md"))
        self.assertIn("--pr", body)
        self.assertIn("CLAUDE.md", body)

    def test_changelog_mentions_exempt_pr_merge(self):
        body = read(self.doc_path("CHANGELOG.md"))
        self.assertIn("(MAR-9)", body)
        self.assertIn("--pr", body)


class TestMergePrBehindAutoUpdate(unittest.TestCase):
    """MAR-47 (spec 03): pin the BEHIND→update-branch prose contract across all
    three behavior surfaces (SKILL.md, planner, executor) and the exempt --pr
    path. Additive existence/co-occurrence assertions only — they enforce AC-6
    (and AC-1, AC-2, AC-4 across surfaces) so a future edit that drops or
    reverts the carve-out fails CI. No existing assertion is modified."""

    def skill_path(self, name):
        return os.path.join(PLUGIN, "skills", name, "SKILL.md")

    def agent_path(self, skill, role):
        return os.path.join(PLUGIN, "agents", "%s-%s.md" % (skill, role))

    def test_skill_behind_routes_to_update_branch(self):
        body = read(self.skill_path("merge-pr"))
        # Basic existence: update-branch is present in the skill prose.
        self.assertIn("update-branch", body,
                      "SKILL.md must mention update-branch (MAR-47 AC-1)")
        # Co-occurrence: BEHIND and update-branch must appear in proximity,
        # proving the routing (not unconditionally report-only).
        self.assertIsNotNone(
            re.search(r"BEHIND.*update-branch|update-branch.*BEHIND", body, re.DOTALL),
            "SKILL.md must co-locate BEHIND and update-branch (MAR-47 AC-1)")

    def test_planner_behind_routes_to_update_branch(self):
        body = read(self.agent_path("merge-pr", "planner"))
        # Basic existence: update-branch is present in the planner prose.
        self.assertIn("update-branch", body,
                      "merge-pr-planner.md must mention update-branch (MAR-47 AC-2)")
        # Co-occurrence: BEHIND and update-branch appear together.
        self.assertIsNotNone(
            re.search(r"BEHIND.*update-branch|update-branch.*BEHIND", body, re.DOTALL),
            "merge-pr-planner.md must co-locate BEHIND and update-branch (MAR-47 AC-2)")
        # C-7 verdict tokens: pin the verdict shape without requiring the exact
        # full sentence — robust to minor rewording of surrounding context.
        self.assertIn("was BEHIND", body,
                      "merge-pr-planner.md must carry 'was BEHIND' verdict token (MAR-47 C-7)")
        self.assertIn("auto-updated", body,
                      "merge-pr-planner.md must carry 'auto-updated' verdict token (MAR-47 C-7)")

    def test_executor_behind_routes_to_update_branch(self):
        body = read(self.agent_path("merge-pr", "executor"))
        # Basic existence: update-branch is present in the executor prose.
        self.assertIn("update-branch", body,
                      "merge-pr-executor.md must mention update-branch (MAR-47 AC-2)")
        # BEHIND-only guard: the executor must scope the update-branch step
        # strictly to when mergeStateStatus == BEHIND (AC-2 — SKIP otherwise).
        self.assertIsNotNone(
            re.search(
                r"(?i)(only when.*BEHIND|BEHIND.*only|skip.*if.*BEHIND"
                r"|mergeStateStatus != BEHIND)",
                body),
            "merge-pr-executor.md must carry the BEHIND-only guard for update-branch "
            "(MAR-47 AC-2 — 'SKIP if mergeStateStatus != BEHIND')")

    def test_conflict_and_timeout_fallbacks_in_skill(self):
        body = read(self.skill_path("merge-pr"))
        # Verbatim load-bearing fallback tokens (design.md lines 238-239).
        # A future edit that drops either fallback will be caught here.
        self.assertIn("update-branch conflict", body,
                      "SKILL.md must carry 'update-branch conflict' fallback stop_reason "
                      "(MAR-47 AC-4)")
        self.assertIn("branch updated but required CI still running", body,
                      "SKILL.md must carry CI-timeout fallback stop_reason (MAR-47 AC-4)")

    def test_conflict_and_timeout_fallbacks_in_executor(self):
        body = read(self.agent_path("merge-pr", "executor"))
        # Same two verbatim fallback tokens must appear in the executor prose
        # independently — asserting both surfaces catches a partial edit that
        # updates only skill or only executor.
        self.assertIn("update-branch conflict", body,
                      "merge-pr-executor.md must carry 'update-branch conflict' fallback "
                      "stop_reason (MAR-47 AC-4)")
        self.assertIn("branch updated but required CI still running", body,
                      "merge-pr-executor.md must carry CI-timeout fallback stop_reason "
                      "(MAR-47 AC-4)")

    def test_exempt_pr_path_behind_routes_to_update_branch(self):
        # C-10 extension: the BEHIND carve-out applies to the exempt --pr path
        # as well as the ticket path (clarifications.json:104-113).
        body = read(self.skill_path("merge-pr"))
        # Exempt section heading must be present (also asserted by TestExemptPrDocs).
        self.assertIn("Exempt non-ticket PR mode", body,
                      "SKILL.md must carry the 'Exempt non-ticket PR mode' section")
        # update-branch must appear within 3000 chars after the exempt heading,
        # proving the exempt section itself was amended — not just the ticket path.
        self.assertIsNotNone(
            re.search(r"(?s)Exempt non-ticket PR mode.{0,3000}update-branch", body),
            "SKILL.md exempt section must mention update-branch within 3000 chars "
            "of its heading (MAR-47 C-10)")
        # BEHIND must also appear within that window.
        self.assertIsNotNone(
            re.search(r"(?s)Exempt non-ticket PR mode.{0,3000}BEHIND", body),
            "SKILL.md exempt section must mention BEHIND within 3000 chars "
            "of its heading (MAR-47 C-10)")


class TestApplyTierInline(unittest.TestCase):
    """MAR-60 (spec 05): pin the apply-tier inline contract across create-pr,
    merge-pr, and create-ticket. Assertions enforce MAR-55 invariant (b) —
    'Apply-work (create-pr, merge-pr, create-ticket) is always
    deterministic-inline (coordinator + at most one executor), never a triad'
    — and the AC-1 through AC-7 acceptance criteria from the ticket.
    These tests are written first (TDD RED) and turn green after specs 01-04
    apply the SKILL.md and doc rewrites. No existing assertion is modified."""

    def skill_path(self, name):
        return os.path.join(PLUGIN, "skills", name, "SKILL.md")

    def doc_path(self, *parts):
        return os.path.join(REPO_ROOT, *parts)

    # ------------------------------------------------------------------ Group 1
    # AC-1, AC-2: no planner / no verifier spawn in each apply-work SKILL.md.

    def test_create_pr_no_planner_verifier_spawn(self):
        """AC-1/AC-2 [create-pr]: SKILL.md must not spawn -planner or -verifier."""
        body = read(self.skill_path("create-pr"))
        self.assertIsNone(
            re.search(r"acs:create-pr-planner", body),
            "AC-1 [create-pr]: SKILL.md must not spawn acs:create-pr-planner subagent")
        self.assertIsNone(
            re.search(r"acs:create-pr-verifier", body),
            "AC-1 [create-pr]: SKILL.md must not spawn acs:create-pr-verifier subagent")
        self.assertIsNone(
            re.search(r"\bcreate-pr-planner\b", body),
            "AC-2 [create-pr]: SKILL.md must carry no bare create-pr-planner token")
        self.assertIsNone(
            re.search(r"\bcreate-pr-verifier\b", body),
            "AC-2 [create-pr]: SKILL.md must carry no bare create-pr-verifier token")

    def test_merge_pr_no_planner_verifier_spawn(self):
        """AC-1/AC-2 [merge-pr]: SKILL.md must not spawn -planner or -verifier."""
        body = read(self.skill_path("merge-pr"))
        self.assertIsNone(
            re.search(r"acs:merge-pr-planner", body),
            "AC-1 [merge-pr]: SKILL.md must not spawn acs:merge-pr-planner subagent")
        self.assertIsNone(
            re.search(r"acs:merge-pr-verifier", body),
            "AC-1 [merge-pr]: SKILL.md must not spawn acs:merge-pr-verifier subagent")
        self.assertIsNone(
            re.search(r"\bmerge-pr-planner\b", body),
            "AC-2 [merge-pr]: SKILL.md must carry no bare merge-pr-planner token")
        self.assertIsNone(
            re.search(r"\bmerge-pr-verifier\b", body),
            "AC-2 [merge-pr]: SKILL.md must carry no bare merge-pr-verifier token")

    def test_create_ticket_no_planner_verifier_spawn(self):
        """AC-1/AC-2 [create-ticket]: SKILL.md must not spawn -planner or -verifier."""
        body = read(self.skill_path("create-ticket"))
        self.assertIsNone(
            re.search(r"acs:create-ticket-planner", body),
            "AC-1 [create-ticket]: SKILL.md must not spawn acs:create-ticket-planner subagent")
        self.assertIsNone(
            re.search(r"acs:create-ticket-verifier", body),
            "AC-1 [create-ticket]: SKILL.md must not spawn acs:create-ticket-verifier subagent")
        self.assertIsNone(
            re.search(r"\bcreate-ticket-planner\b", body),
            "AC-2 [create-ticket]: SKILL.md must carry no bare create-ticket-planner token")
        self.assertIsNone(
            re.search(r"\bcreate-ticket-verifier\b", body),
            "AC-2 [create-ticket]: SKILL.md must carry no bare create-ticket-verifier token")

    # ------------------------------------------------------------------ Group 2
    # AC-2: no plan->execute->verify triad instruction in any apply-work SKILL.md.

    def test_apply_skills_no_triad_instruction(self):
        """AC-2: no ASCII-arrow, Unicode-arrow, or prose triad instruction."""
        for skill in ("create-pr", "merge-pr", "create-ticket"):
            body = read(self.skill_path(skill))
            self.assertIsNone(
                re.search(r"plan\s*->\s*execute\s*->\s*verify", body, re.IGNORECASE),
                "AC-2 [%s]: SKILL.md must not contain 'plan -> execute -> verify'" % skill)
            self.assertIsNone(
                re.search(r"plan\s*→\s*execute\s*→\s*verify", body, re.IGNORECASE),
                "AC-2 [%s]: SKILL.md must not contain 'plan → execute → verify'" % skill)
            self.assertIsNone(
                re.search(r"plan to execute to verify", body, re.IGNORECASE),
                "AC-2 [%s]: SKILL.md must not contain 'plan to execute to verify'" % skill)

    # ------------------------------------------------------------------ Group 3
    # AC-1 positive shape: planner and verifier token count must be zero.

    def test_apply_skills_executor_token_allowed(self):
        """AC-1: planner and verifier counts are zero; executor is unconstrained."""
        for skill in ("create-pr", "merge-pr", "create-ticket"):
            body = read(self.skill_path(skill))
            self.assertEqual(
                len(re.findall(r"\b%s-planner\b" % skill, body)), 0,
                "AC-1 [%s]: SKILL.md must have 0 occurrences of %s-planner" % (skill, skill))
            self.assertEqual(
                len(re.findall(r"\b%s-verifier\b" % skill, body)), 0,
                "AC-1 [%s]: SKILL.md must have 0 occurrences of %s-verifier" % (skill, skill))

    # ------------------------------------------------------------------ Group 4
    # AC-3: no lane keyword co-occurs with a planner/verifier spawn in any apply
    # SKILL.md — no lane must conditionally re-introduce the triad.

    def test_apply_skills_no_lane_conditional_triad(self):
        """AC-3: no lane keyword co-occurs within 500 chars of a planner/verifier spawn."""
        for skill in ("create-pr", "merge-pr", "create-ticket"):
            body = read(self.skill_path(skill))
            for lane in ("TRIVIAL", "SMALL", "STANDARD", "COMPLEX"):
                self.assertIsNone(
                    re.search(
                        r"(?s)" + lane + r".{0,500}acs:" + skill + r"-(planner|verifier)"
                        + r"|acs:" + skill + r"-(planner|verifier).{0,500}" + lane,
                        body),
                    "AC-3 [%s]: lane '%s' must not co-occur with planner/verifier spawn"
                    % (skill, lane))

    # ------------------------------------------------------------------ Group 5
    # AC-4: load-bearing step tokens and post-hook references survive the inline
    # rewrite in each apply-work SKILL.md.

    def test_apply_skills_preserved_load_bearing_steps(self):
        """AC-4: canonical states keys and post-hook references must survive."""
        # create-pr: states.pr nested object plus post-hook
        create_pr_body = read(self.skill_path("create-pr"))
        self.assertIsNotNone(
            re.search(r'"states"\s*:\s*\{\s*"pr"\s*:', create_pr_body),
            "AC-4 [create-pr]: Finish must declare the canonical states.pr object")
        self.assertIn('"number"', create_pr_body,
                      "AC-4 [create-pr]: states.pr.number field must survive")
        self.assertIn('"url"', create_pr_body,
                      "AC-4 [create-pr]: states.pr.url field must survive")
        self.assertIn('"branch"', create_pr_body,
                      "AC-4 [create-pr]: states.pr.branch field must survive")
        self.assertIn('"base"', create_pr_body,
                      "AC-4 [create-pr]: states.pr.base field must survive")
        self.assertIn("post-create-pr.py", create_pr_body,
                      "AC-4 [create-pr]: post-hook reference must survive inline rewrite")

        # merge-pr: canonical key set plus post-hook
        merge_pr_body = read(self.skill_path("merge-pr"))
        self.assertIn("merged", merge_pr_body,
                      "AC-4 [merge-pr]: Finish must name states.merged key")
        self.assertIn("merge_strategy", merge_pr_body,
                      "AC-4 [merge-pr]: Finish must name states.merge_strategy key")
        self.assertIn("readiness", merge_pr_body,
                      "AC-4 [merge-pr]: Finish must name states.readiness key")
        self.assertIn("post-merge-pr.py", merge_pr_body,
                      "AC-4 [merge-pr]: post-hook reference must survive")

        # create-ticket: canonical key set plus confirmation-gate tokens and post-hook
        create_ticket_body = read(self.skill_path("create-ticket"))
        self.assertIn("ticket_id", create_ticket_body,
                      "AC-4 [create-ticket]: Finish must name states.ticket_id key")
        self.assertIn("type", create_ticket_body,
                      "AC-4 [create-ticket]: Finish must name states.type key")
        self.assertIn("needs_design", create_ticket_body,
                      "AC-4 [create-ticket]: Finish must name states.needs_design key "
                      "(also a confirmation-gate token)")
        self.assertIn("children", create_ticket_body,
                      "AC-4 [create-ticket]: Finish must name states.children key")
        self.assertIn("prd_trace", create_ticket_body,
                      "AC-4 [create-ticket]: Finish must name states.prd_trace key")
        self.assertIn("post-create-ticket.py", create_ticket_body,
                      "AC-4 [create-ticket]: post-hook reference must survive")
        self.assertIn("size", create_ticket_body,
                      "AC-4 [create-ticket]: user-confirmation gate token size must survive")
        self.assertIn("stakes", create_ticket_body,
                      "AC-4 [create-ticket]: user-confirmation gate token stakes must survive")
        self.assertIn("lane", create_ticket_body,
                      "AC-4 [create-ticket]: user-confirmation gate token lane must survive")

    # ------------------------------------------------------------------ Group 6
    # AC-6: the six triad-keeping skills still reference planner and verifier.

    def test_triad_skills_still_reference_planner_and_verifier(self):
        """AC-6: workflow/product skills must still reference their planner+verifier."""
        for skill in ("create-spec", "code", "create-prd",
                      "create-design", "create-architecture", "create-project"):
            body = read(self.skill_path(skill))
            self.assertIsNotNone(
                re.search(r"acs:" + skill + r"-planner", body),
                "AC-6 [%s]: must still reference acs:%s-planner" % (skill, skill))
            self.assertIsNotNone(
                re.search(r"acs:" + skill + r"-verifier", body),
                "AC-6 [%s]: must still reference acs:%s-verifier" % (skill, skill))

    # ------------------------------------------------------------------ Group 7
    # AC-7: requirements docs updated to reflect inline shape.

    def test_skills_md_apply_skills_no_triad_in_subagents(self):
        """AC-7: skills.md must not list planner for apply skills and must carry
        an inline/apply-work carve-out token."""
        body = read(self.doc_path("docs", "requirements", "skills.md"))
        self.assertIsNone(
            re.search(
                r"(?s)(create-pr|merge-pr|create-ticket).{0,500}Subagents.{0,300}planner",
                body),
            "AC-7: skills.md per-skill Subagents must not list planner for apply skills")
        self.assertIsNotNone(
            re.search(r"(?i)(inline|deterministic.inline|apply.work)", body),
            "AC-7: skills.md must carry an inline/apply-work carve-out token")

    def test_reflection_md_no_all_skills_triad_claim(self):
        """AC-7: reflection.md must not describe apply skills as running their own
        planner+verifier triad, and must carry a carve-out or drop the
        unconditional all-skills triad claim."""
        body = read(self.doc_path("docs", "requirements", "reflection.md"))
        self.assertIsNone(
            re.search(
                r"(?s)(create-pr|merge-pr|create-ticket).{0,300}planner.{0,300}verifier",
                body),
            "AC-7: reflection.md must not describe apply skills as running "
            "planner+verifier")
        unconditional = re.search(
            r"Every workflow skill MUST apply the Reflection pattern", body)
        carve_out = re.search(
            r"(?i)(apply.work|create-pr.*inline|inline.*create-pr)", body)
        self.assertTrue(
            unconditional is None or carve_out is not None,
            "AC-7: reflection.md must either drop the all-skills triad claim or "
            "carry an apply-work carve-out")

class TestCodeSkillEscalation(unittest.TestCase):
    """MAR-57 Spec 02 (AC-1, AC-2, AC-6): pin the in-loop escalation contract in
    plugins/acs/skills/code/SKILL.md. Doc-assertion tests that read the prose
    and assert the presence of normative tokens. The tests are RED before the
    escalation subsection is added; GREEN after.
    """

    def skill_path(self, name):
        return os.path.join(PLUGIN, "skills", name, "SKILL.md")

    def _body(self):
        return read(self.skill_path("code"))

    # --- AC-6: exactly three triggers enumerated ---

    def test_trigger_a_verifier_finding(self):
        """AC-6: code/SKILL.md must name trigger (a) — verifier finding signaling higher
        stakes/size."""
        body = self._body()
        # Accept either 'verifier finding' or 'finding' near 'stakes' or 'size'
        self.assertIsNotNone(
            re.search(r"(?i)verifier finding|finding.*higher.{0,60}(stakes|size)", body),
            "code/SKILL.md must enumerate trigger (a): verifier finding signaling "
            "higher stakes/size (MAR-57 AC-6)")

    def test_trigger_b_high_stakes_paths_glob(self):
        """AC-6: code/SKILL.md must name trigger (b) using high_stakes_paths (the glob
        mechanism, not a re-implementation)."""
        body = self._body()
        self.assertIn("high_stakes_paths", body,
                      "code/SKILL.md must reference high_stakes_paths for trigger (b) "
                      "(MAR-57 AC-6 — reuse glob mechanism, not a re-implementation)")

    def test_trigger_c_explicit_user_agent_request(self):
        """AC-6: code/SKILL.md must name trigger (c) — explicit user/agent escalation
        request."""
        body = self._body()
        self.assertIsNotNone(
            re.search(r"(?i)explicit.{0,40}(user|agent)|user.{0,40}agent.{0,40}(escalat|request)",
                      body),
            "code/SKILL.md must enumerate trigger (c): explicit user/agent escalation "
            "request (MAR-57 AC-6)")

    def test_escalate_lane_named(self):
        """AC-4/AC-6: code/SKILL.md must name escalate_lane (the Spec-01 helper) so the
        coordinator recomputes via the canonical derive_lane path (not hand-set)."""
        body = self._body()
        self.assertIn("escalate_lane", body,
                      "code/SKILL.md must reference escalate_lane (MAR-57 AC-4/AC-6)")

    # --- AC-2: first-signal / immediate evaluation ---

    def test_first_signal_evaluated_immediately(self):
        """AC-2: code/SKILL.md must state that escalation is evaluated on the FIRST
        signal (not after N findings or cap exhaustion)."""
        body = self._body()
        self.assertIsNotNone(
            re.search(r"(?i)(first.{0,30}signal|immediately|on.{0,30}first)", body),
            "code/SKILL.md must state escalation is evaluated on the first signal / "
            "immediately (MAR-57 AC-2)")

    # --- AC-1: no-restart / continue-from-current-point ---

    def test_no_restart_property(self):
        """AC-1: code/SKILL.md must state the no-restart / continue-from-current-point
        property: completed work is not discarded when escalation fires."""
        body = self._body()
        self.assertIsNotNone(
            re.search(
                r"(?i)(no.restart|without restart|without discard|continue.{0,60}"
                r"(current|completed)|completed work)",
                body),
            "code/SKILL.md must state the no-restart / continue-from-current-point "
            "property on escalation (MAR-57 AC-1)")

    # --- AC-1/AC-7: upward-only, ceiling never lowered ---

    def test_upward_only_stated(self):
        """AC-1/AC-7: code/SKILL.md must state the lane is only ever raised, never
        lowered (upward-only monotone escalation)."""
        body = self._body()
        self.assertIsNotNone(
            re.search(r"(?i)(upward.only|only.{0,30}rais|never.{0,30}lower|monoton)", body),
            "code/SKILL.md must state upward-only / never-lower escalation "
            "(MAR-57 AC-1/AC-7)")

    # --- AC-4: re-persist to all three state files ---

    def test_repersist_ticket_json(self):
        """AC-4: code/SKILL.md must state that the escalated lane is persisted to
        ticket.json via save_ticket (or by name)."""
        body = self._body()
        self.assertTrue(
            "ticket.json" in body or "save_ticket" in body,
            "code/SKILL.md must mention ticket.json or save_ticket for re-persist "
            "(MAR-57 AC-4)")

    def test_repersist_pipeline_state(self):
        """AC-4: code/SKILL.md must state that pipeline-state.json is updated on
        escalation via update_pipeline."""
        body = self._body()
        self.assertTrue(
            "pipeline-state.json" in body or "update_pipeline" in body,
            "code/SKILL.md must mention pipeline-state.json or update_pipeline for "
            "re-persist (MAR-57 AC-4)")

    def test_repersist_tickets_index(self):
        """AC-4: code/SKILL.md must state that tickets-index.json is updated on
        escalation via update_index."""
        body = self._body()
        self.assertTrue(
            "tickets-index.json" in body or "update_index" in body,
            "code/SKILL.md must mention tickets-index.json or update_index for "
            "re-persist (MAR-57 AC-4)")


class TestStageReintroduction(unittest.TestCase):
    """MAR-57 Spec 03 (AC-5, AC-8): pin the stage re-introduction contract in
    create-spec/SKILL.md and the cross-reference in code/SKILL.md.

    These doc-assertion tests are RED before the 'Escalation pickup' subsection
    is added to create-spec/SKILL.md and the cross-reference is added to
    code/SKILL.md; GREEN after.

    Per plan Q1 resolution: since MAR-59 fold prose is not yet on disk, the
    MAR-59-unchanged assertion targets the NEW pickup subsection's own statement
    that fold behavior is unchanged for non-escalating tickets — not absent
    pre-existing fold prose.
    """

    def skill_path(self, name):
        return os.path.join(PLUGIN, "skills", name, "SKILL.md")

    def _create_spec_body(self):
        return read(self.skill_path("create-spec"))

    def _code_body(self):
        return read(self.skill_path("code"))

    # --- AC-5: create-spec/SKILL.md has an 'Escalation pickup' subsection ---

    def test_skill_md_documents_escalation_pickup(self):
        """AC-5: create-spec/SKILL.md must contain an 'Escalation pickup' heading
        (or equivalent) describing the mid-/code invocation path."""
        body = self._create_spec_body()
        self.assertIsNotNone(
            re.search(r"(?i)escalation pickup|escalation pick.?up", body),
            "create-spec/SKILL.md must have an 'Escalation pickup' subsection "
            "(MAR-57 AC-5)")

    # --- AC-5: pickup subsection states create-spec rigor is invoked, not skipped ---

    def test_skill_md_pickup_does_not_skip_spec_stage(self):
        """AC-5: the pickup subsection must state that create-spec rigor is invoked
        (not skipped) when a ticket escalates from a fast lane into STANDARD/COMPLEX."""
        body = self._create_spec_body()
        # Must state the escalation pickup runs full create-spec rigor.
        # Patterns: 'create-spec' near 'rigor' near 'invok/run/not skipped', OR
        # 'rigor' near 'not skip/invok', OR 'spec.rigor' directly adjacent.
        self.assertIsNotNone(
            re.search(
                r"(?i)"
                r"create.spec.{0,30}rigor.{0,300}(invok|not skip|pick.?up)|"
                r"(invok|not skip|pick.?up).{0,300}create.spec.{0,30}rigor|"
                r"(rigor).{0,200}(not skip|invok)",
                body, re.DOTALL),
            "create-spec/SKILL.md pickup subsection must state create-spec rigor "
            "is invoked (not skipped) on fast-lane escalation (MAR-57 AC-5)")

    # --- AC-5: pickup subsection references higher verify ceiling ---

    def test_skill_md_pickup_adopts_higher_ceiling(self):
        """AC-5: the pickup subsection must reference adoption of the higher verify
        ceiling after escalation."""
        body = self._create_spec_body()
        self.assertIsNotNone(
            re.search(
                r"(?i)(higher.{0,30}(ceiling|verify)|verify.{0,30}ceiling.{0,30}(higher|raise|adopt)|"
                r"ceiling.{0,30}(raise|adopt|higher))",
                body),
            "create-spec/SKILL.md pickup subsection must reference the higher verify "
            "ceiling adopted on escalation (MAR-57 AC-5)")

    # --- AC-8 sibling-no-regression: pickup subsection states fold is unchanged for
    #     non-escalating tickets (per Q1: assert the NEW subsection's own statement,
    #     NOT pre-existing fold prose from MAR-59 which is not yet on disk) ---

    def test_mar59_fold_behavior_stated_unchanged_for_noescalation(self):
        """AC-8: the pickup subsection must state that for non-escalating TRIVIAL/SMALL
        tickets the fast-lane fold behavior is unchanged — the new subsection is a
        NEW branch only, not a change to the normal fast-lane flow."""
        body = self._create_spec_body()
        self.assertIsNotNone(
            re.search(
                r"(?i)(non.escalat|not escalat).{0,300}(unchanged|unaffected|fold|fast.lane|normal|intact)|"
                r"(fast.lane|fold).{0,300}(unchanged|unaffected|unmodified|intact|not.{0,20}changed).{0,100}"
                r"(non.escalat|not escalat|without escalat)",
                body, re.DOTALL),
            "create-spec/SKILL.md pickup subsection must state fast-lane fold is "
            "unchanged for non-escalating tickets (MAR-57 AC-8 / Q1 resolution)")

    # --- AC-5: code/SKILL.md cross-references the create-spec pickup subsection ---

    def test_code_skill_md_cross_references_create_spec_pickup(self):
        """AC-5: code/SKILL.md must contain a cross-reference to the
        create-spec/SKILL.md 'Escalation pickup' subsection."""
        body = self._code_body()
        # Must mention create-spec in the context of escalation pickup or stage reintroduction
        self.assertIsNotNone(
            re.search(
                r"(?i)create.spec.{0,300}(escalation pickup|pickup|stage.reintroduc|"
                r"fold.boundar|fast.lane.{0,40}escalat)|"
                r"(escalation pickup|stage.reintroduc).{0,300}create.spec",
                body, re.DOTALL),
            "code/SKILL.md must cross-reference the create-spec 'Escalation pickup' "
            "subsection (MAR-57 AC-5)")

    # --- guard_axes must be referenced in code/SKILL.md escalation sequence ---

    def test_code_skill_md_references_guard_axes(self):
        """AC-3/Spec 03: code/SKILL.md must reference guard_axes in the escalation
        sequence (the axis-guard step added by Spec 03)."""
        body = self._code_body()
        self.assertIn("guard_axes", body,
                      "code/SKILL.md must reference guard_axes in the escalation "
                      "sequence (MAR-57 AC-3/Spec 03)")

    # --- AC-3: no automatic-downgrade code path exists in either SKILL ---

    def test_no_automatic_downgrade_path_in_code_skill(self):
        """AC-3: code/SKILL.md must NOT describe an automatic de-escalation or
        downgrade path (outside of the out-of-scope / negative-guarantee note).
        Assertive phrases (e.g. 'will automatically lower the lane') must be absent;
        negating phrases (e.g. 'never lowered', 'no automatic path lowers') are
        the negative-guarantee language and are acceptable."""
        body = self._code_body()
        # Detect assertive automatic-downgrade phrases: patterns where the automatic
        # downgrade is affirmed, not denied.  We exclude lines containing 'never',
        # 'not', 'no automatic' etc. that express the negative guarantee itself.
        # Strategy: search for matches, then verify none is assertive (not negated).
        matches = list(re.finditer(
            r"(?i)(automatic(ally)?.{0,50}(lower.{0,20}lane|de.escalat|downgrad)|"
            r"(lower.{0,20}lane|de.escalat|downgrad).{0,50}automatic)",
            body))
        for m in matches:
            # Allow matches that are explicitly negated (part of the safety contract)
            surrounding = body[max(0, m.start()-30):m.end()+10]
            if re.search(r"(?i)(never|not|no |cannot|must not|does not)", surrounding):
                continue  # this is a negating / negative-guarantee statement
            self.fail(
                "code/SKILL.md describes an automatic downgrade path outside of a "
                "negating context (AC-3 negative guarantee). Found: %r" % m.group(0))

    def test_no_automatic_downgrade_path_in_create_spec_skill(self):
        """AC-3: create-spec/SKILL.md must NOT describe an automatic de-escalation or
        downgrade path. Negating / negative-guarantee statements ('does not introduce
        an automatic...', 'never') are acceptable."""
        body = self._create_spec_body()
        matches = list(re.finditer(
            r"(?i)(automatic(ally)?.{0,50}(lower.{0,20}lane|de.escalat|downgrad)|"
            r"(lower.{0,20}lane|de.escalat|downgrad).{0,50}automatic)",
            body))
        for m in matches:
            surrounding = body[max(0, m.start()-30):m.end()+10]
            if re.search(r"(?i)(never|not|no |cannot|must not|does not)", surrounding):
                continue  # negating / negative-guarantee statement: allowed
            self.fail(
                "create-spec/SKILL.md describes an automatic downgrade path outside of "
                "a negating context (AC-3 negative guarantee). Found: %r" % m.group(0))


class TestMidFlightEscalationContract(unittest.TestCase):
    """MAR-57 Spec 04 (AC-3, AC-6, AC-7, AC-8): pin the mid-flight escalation
    contract in docs/requirements/skills.md.

    Doc-assertion tests reading skills.md and verifying the standing contract
    is present. RED before the 'Mid-flight lane escalation' subsection is added;
    GREEN after.
    """

    def _skills_md_path(self):
        return os.path.join(REPO_ROOT, "docs", "requirements", "skills.md")

    def _body(self):
        return read(self._skills_md_path())

    # --- AC-6: exactly three triggers, each enumerated ---

    def test_skills_md_contains_escalation_trigger_a(self):
        """AC-6: skills.md must enumerate trigger (a) — verifier finding signaling
        higher stakes/size."""
        body = self._body()
        self.assertIsNotNone(
            re.search(
                r"(?i)(verifier finding.{0,100}(higher|stakes|size)|"
                r"finding.{0,60}(higher.{0,30}(stakes|size)|stakes|size))",
                body),
            "skills.md must enumerate trigger (a): verifier finding signaling "
            "higher stakes/size (MAR-57 AC-6)")

    def test_skills_md_contains_escalation_trigger_b(self):
        """AC-6: skills.md must enumerate trigger (b) — high_stakes_paths glob match."""
        body = self._body()
        self.assertIn(
            "high_stakes_paths", body,
            "skills.md must enumerate trigger (b): high_stakes_paths glob match "
            "(MAR-57 AC-6)")

    def test_skills_md_contains_escalation_trigger_c(self):
        """AC-6: skills.md must enumerate trigger (c) — explicit user/agent escalation
        request."""
        body = self._body()
        self.assertIsNotNone(
            re.search(
                r"(?i)(explicit.{0,60}(user|agent).{0,60}(escalat|request)|"
                r"user.{0,40}agent.{0,60}escalat)",
                body),
            "skills.md must enumerate trigger (c): explicit user/agent escalation "
            "request (MAR-57 AC-6)")

    def test_skills_md_trigger_set_is_exactly_three(self):
        """AC-6: skills.md must enumerate exactly triggers (a), (b), (c) in the
        escalation section — no fourth trigger listed."""
        body = self._body()
        # Find the escalation subsection
        section_match = re.search(
            r"(?i)mid.?flight.{0,20}(lane.{0,20}escalation|escalation)", body)
        self.assertIsNotNone(
            section_match,
            "skills.md must have a mid-flight escalation section (MAR-57 AC-6)")
        section_start = section_match.start()
        # Take up to 3000 chars after the section heading
        section = body[section_start:section_start + 3000]
        # Exactly three labeled triggers (a), (b), (c) in the trigger list
        trigger_labels = re.findall(r"\(([abc])\)", section)
        for label in ("a", "b", "c"):
            self.assertIn(
                label, trigger_labels,
                "skills.md escalation section must label trigger (%s) (MAR-57 AC-6)" % label)
        # Must not list a (d) trigger
        self.assertNotIn(
            "d", trigger_labels,
            "skills.md escalation section must NOT list a fourth trigger (d) "
            "(MAR-57 AC-6 — bounded trigger set)")

    # --- AC-3/AC-8: upward-only automatic escalation ---

    def test_skills_md_upward_only_contract(self):
        """AC-3/AC-8: skills.md must state the upward-only automatic escalation contract."""
        body = self._body()
        self.assertIsNotNone(
            re.search(
                r"(?i)(upward.only|upward only|only.{0,30}rais|automatically escalat|"
                r"automatic.{0,30}escalat)",
                body),
            "skills.md must state upward-only automatic escalation contract "
            "(MAR-57 AC-3/AC-8)")

    # --- AC-3: negative guarantee (no automatic downgrade) ---

    def test_skills_md_negative_guarantee(self):
        """AC-3: skills.md must state that no automatic/unattended code path lowers
        the lane or authoritative axes below a user-confirmed value."""
        body = self._body()
        self.assertIsNotNone(
            re.search(
                r"(?i)(never automatic|no automatic.{0,60}(lower|lowers|de.escalat)|"
                r"automatic.{0,30}(never|not|never).{0,60}(lower|lowers)|"
                r"negative guarantee|automatic.{0,50}silent)",
                body),
            "skills.md must state the negative guarantee: no automatic/unattended "
            "path lowers the lane or axes below a user-confirmed value (MAR-57 AC-3)")

    # --- AC-3/AC-8: user-confirmed-only de-escalation + interactive downgrade deferred ---

    def test_skills_md_user_confirmed_only_de_escalation(self):
        """AC-3/AC-8: skills.md must state that de-escalation requires explicit user
        confirmation and that interactive downgrade is deferred."""
        body = self._body()
        # Must state user confirmation required for de-escalation
        self.assertIsNotNone(
            re.search(
                r"(?i)(de.escalat.{0,100}(user.confirm|explicit.confirm|explicit.user)|"
                r"(user.confirm|explicit).{0,100}de.escalat|"
                r"lower.{0,60}user.confirm)",
                body),
            "skills.md must state de-escalation requires explicit user confirmation "
            "(MAR-57 AC-3/AC-8)")
        # Must state the interactive downgrade command is deferred
        self.assertIsNotNone(
            re.search(
                r"(defer|deferred|out.of.scope).{0,200}(downgrade|de.escalat|interactiv)|"
                r"(downgrade|de.escalat|interactiv).{0,200}(defer|deferred|out.of.scope)",
                body, re.IGNORECASE | re.DOTALL),
            "skills.md must state the interactive downgrade command is deferred "
            "(MAR-57 AC-3/AC-8)")

    # --- AC-5/AC-8: stage re-introduction mentioned ---

    def test_skills_md_stage_reintroduction_mentioned(self):
        """AC-5/AC-8: skills.md must mention stage re-introduction (picking up
        create-spec rigor on fast-lane escalation)."""
        body = self._body()
        self.assertIsNotNone(
            re.search(
                r"(?i)(stage re.?introduc|re.?introduc.{0,60}(stage|create.spec)|"
                r"create.spec.{0,100}(rigor|skip|pick.?up)|"
                r"fast.lane.{0,200}escalat.{0,200}create.spec)",
                body, re.DOTALL),
            "skills.md must mention stage re-introduction (picking up create-spec "
            "rigor on fast-lane escalation) (MAR-57 AC-5/AC-8)")

    # --- AC-8: sibling behaviors MAR-59 / MAR-60 stated unchanged ---

    def test_skills_md_mar59_fold_unchanged(self):
        """AC-8: skills.md must state that the fast-lane fold (MAR-59) is unchanged
        for non-escalating tickets."""
        body = self._body()
        self.assertIsNotNone(
            re.search(
                r"(?i)(MAR.59|fast.lane fold|fast.?lane.{0,60}fold)"
                r".{0,300}(unchanged|unaffected|not changed|intact)|"
                r"(unchanged|unaffected|not changed).{0,300}(MAR.59|fast.lane fold)",
                body, re.DOTALL),
            "skills.md must state the fast-lane fold (MAR-59) is unchanged for "
            "non-escalating tickets (MAR-57 AC-8)")

    def test_skills_md_mar60_apply_tier_unchanged(self):
        """AC-8: skills.md must state that apply-tier inlining (MAR-60) is unchanged."""
        body = self._body()
        self.assertIsNotNone(
            re.search(
                r"(?i)(MAR.60|apply.tier).{0,300}(unchanged|unaffected|not changed|intact)|"
                r"(unchanged|unaffected|not changed).{0,300}(MAR.60|apply.tier)",
                body, re.DOTALL),
            "skills.md must state apply-tier inlining (MAR-60) is unchanged "
            "(MAR-57 AC-8)")

    # --- AC-6: routing always via derive_lane ---

    def test_skills_md_derive_lane_as_single_authority(self):
        """AC-6: skills.md must state routing always via derive_lane (no caller
        re-implements routing)."""
        body = self._body()
        self.assertIn(
            "derive_lane", body,
            "skills.md must reference derive_lane as the single routing authority "
            "(MAR-57 AC-6)")


class TestReflectionMdEscalationCeiling(unittest.TestCase):
    """MAR-57 Spec 04 (AC-1, AC-7, AC-8): pin the in-loop ceiling-raise contract
    in docs/requirements/reflection.md.

    Doc-assertion tests reading reflection.md and verifying the escalation
    ceiling-raise prose is present and invariants are retained. RED before the
    ADD-only ceiling-raise paragraph is added; GREEN after.
    """

    def _reflection_md_path(self):
        return os.path.join(REPO_ROOT, "docs", "requirements", "reflection.md")

    def _body(self):
        return read(self._reflection_md_path())

    def test_reflection_md_exists_at_expected_path(self):
        """AC-8: docs/requirements/reflection.md must exist at the expected path."""
        self.assertTrue(
            os.path.isfile(self._reflection_md_path()),
            "docs/requirements/reflection.md must exist (MAR-57 AC-8)")

    def test_reflection_md_in_loop_ceiling_raise(self):
        """AC-8/AC-1: reflection.md must describe the in-loop ceiling raise on
        escalation (e.g. 'escalation', 'mid-run', 'ceiling' adjustment, or monotone raise)."""
        body = self._body()
        self.assertIsNotNone(
            re.search(
                r"(?i)(escalat.{0,200}(ceiling|ceiling raise|mid.run|in.loop|raise)|"
                r"ceiling.{0,200}(raise|escalat|mid.run)|"
                r"mid.run.{0,100}ceiling|in.loop.{0,100}ceiling)",
                body, re.DOTALL),
            "reflection.md must describe the in-loop ceiling raise on escalation "
            "(MAR-57 AC-8/AC-1)")

    def test_reflection_md_invariants_preserved(self):
        """AC-7: reflection.md must retain language about absolute invariants
        (verifier always runs; TDD/coverage gate immutable) — the existing
        invariant text is not removed or weakened by this spec's edit."""
        body = self._body()
        # Check both invariants are still stated
        self.assertIn(
            "Absolute invariants", body,
            "reflection.md must retain the 'Absolute invariants' block "
            "(MAR-57 AC-7 — ADD-only, must not remove)")
        self.assertIsNotNone(
            re.search(r"(?i)(verifier.{0,60}(always runs|every lane)|every lane.{0,60}verifier)",
                      body),
            "reflection.md must retain 'verifier always runs in every lane' invariant "
            "(MAR-57 AC-7)")
        self.assertIsNotNone(
            re.search(r"(?i)(TDD.{0,60}coverage.{0,60}(gate|immutable|never trimmed)|"
                      r"coverage.{0,60}gate.{0,60}(immutable|never trimmed|full))",
                      body),
            "reflection.md must retain 'TDD/coverage gate immutable' invariant "
            "(MAR-57 AC-7)")

class TestClarifyBatchingContract(unittest.TestCase):
    """MAR-61 (spec 03): pin the grouped-ask clarify-batching contract across
    all 9 hooked coordinator skill bodies and the cross-cutting requirements.
    Additive existence/co-occurrence assertions only — they enforce AC-7
    so a future edit that drops the grouped-ask prose fails CI."""

    def skill_path(self, name):
        return os.path.join(PLUGIN, "skills", name, "SKILL.md")

    def test_grouped_ask_present_in_all_hooked_skills(self):
        for name in HOOKED_SKILLS:
            body = read(self.skill_path(name))
            # Co-occurrence: "ONE grouped" near "interaction" (may span a line
            # break). re.DOTALL so "." crosses newlines — same discipline as
            # the MAR-47 co-occurrence tests (test_skill_contracts.py:289-292).
            self.assertIsNotNone(
                re.search(
                    r"(?i)(ONE grouped[\s\S]{0,50}interaction"
                    r"|grouped[\s\S]{0,50}interaction"
                    r"|single[\s\S]{0,80}interaction[\s\S]{0,80}question)",
                    body),
                "%s: SKILL.md must document presenting >=2 open clarifications in "
                "ONE grouped interaction (MAR-61 AC-7)" % name)

    def test_per_question_ledger_entry_documented_in_all_hooked_skills(self):
        for name in HOOKED_SKILLS:
            body = read(self.skill_path(name))
            # Co-occurrence: "each answer" near "clarify.py" or "per question"
            # near "clarify.py", or "one C-<n>" phrasing.
            self.assertIsNotNone(
                re.search(
                    r"(?i)(each answer.*clarify\.py|per question.*clarify\.py"
                    r"|clarify\.py.*per question|one `C-"
                    r"|each.*own.*clarify\.py|clarify\.py add.*per question"
                    r"|Record each answer)",
                    body, re.DOTALL),
                "%s: SKILL.md must document recording each answer as its own "
                "clarify.py ledger entry (MAR-61 AC-7)" % name)

    def test_no_auto_answer_documented_in_all_hooked_skills(self):
        for name in HOOKED_SKILLS:
            body = read(self.skill_path(name))
            # The prose must mention that questions are not skipped/merged/
            # auto-answered outside the assumption rule.
            self.assertIsNotNone(
                re.search(
                    r"(?i)(never skip|never.*merge|never.*auto.?answer"
                    r"|not.*skip.*question|outside.*assumption)",
                    body),
                "%s: SKILL.md must document not skipping/merging/auto-answering "
                "questions outside the assumption rule (MAR-61 AC-7)" % name)

    def test_skills_requirements_doc_carries_grouped_ask_rule(self):
        path = os.path.join(REPO_ROOT, "docs", "requirements", "skills.md")
        body = read(path)
        self.assertIsNotNone(
            re.search(
                r"(?i)(grouped interaction|ONE grouped|one.*interaction.*question"
                r"|grouped.*clarif)",
                body),
            "docs/requirements/skills.md must document the grouped-ask rule "
            "(MAR-61 AC-7)")




if __name__ == "__main__":
    unittest.main()
