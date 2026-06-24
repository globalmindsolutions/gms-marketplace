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


if __name__ == "__main__":
    unittest.main()
