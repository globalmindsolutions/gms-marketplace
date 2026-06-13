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

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN = os.path.join(REPO_ROOT, "plugins", "acs")

HOOKED_SKILLS = ["create-prd", "create-architecture", "create-project",
                 "create-ticket", "create-design", "create-spec", "code",
                 "create-pr", "merge-pr"]
ALL_SKILLS = HOOKED_SKILLS + ["init", "ship", "handoff", "update"]
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
        for name in ("init", "handoff", "update"):
            fm, _ = frontmatter(read(self.skill_path(name)), name)
            self.assertNotIn("disallowed-tools", fm, name)

    def test_user_action_only_skills(self):
        # merge-pr (human merge gate) and update (changes the environment)
        for name in ("merge-pr", "update"):
            fm, _ = frontmatter(read(self.skill_path(name)), name)
            self.assertRegex(fm, r"(?m)^disable-model-invocation: true$", name)
        for name in ALL_SKILLS:
            if name in ("merge-pr", "update"):
                continue
            fm, _ = frontmatter(read(self.skill_path(name)), name)
            self.assertNotIn("disable-model-invocation: true", fm, name)

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


if __name__ == "__main__":
    unittest.main()
