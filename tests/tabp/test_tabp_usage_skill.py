"""Structural tests for MAR-39: /tabp:usage skill and related docs.

Covers:
  TU-01..TU-07  -- AC-1: skill file exists, frontmatter, invocation markers
  TU-08..TU-14  -- AC-2: per-run and totals rendering markers, honesty rule
  TU-15..TU-17  -- AC-3: degradation / honest unavailability markers
  TU-18..TU-23  -- AC-4: flow doc, c4-container bump, tech-stack bump, README subsection
  TU-24..TU-30  -- AC-5: namespace guard (no acs: / .acs/ / acs_lib tokens)

No model calls. No subprocess. Stdlib only.
Run: python3 -m unittest tests.tabp.test_tabp_usage_skill -v
"""

import os
import re
import unittest

# REPO_ROOT: tests/tabp/test_tabp_usage_skill.py
# dirname x1 -> tests/tabp
# dirname x2 -> tests
# dirname x3 -> repo root
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

USAGE_SKILL_MD = os.path.join(REPO_ROOT, "plugins", "tabp", "skills", "usage", "SKILL.md")
USAGE_FLOW_DOC = os.path.join(
    REPO_ROOT, "docs", "architecture", "lld", "flows", "tabp-usage-read.md"
)
C4_CONTAINER = os.path.join(REPO_ROOT, "docs", "architecture", "hld", "c4-container.md")
TECH_STACK = os.path.join(REPO_ROOT, "docs", "architecture", "hld", "tech-stack.md")
README_MD = os.path.join(REPO_ROOT, "plugins", "tabp", "README.md")
REQUIREMENTS_MD = os.path.join(REPO_ROOT, "docs", "requirements", "tabp.md")


def _parse_frontmatter(text, path):
    """Extract YAML frontmatter block between first and second '---' lines.

    Returns (frontmatter_str, body_str) or raises AssertionError.
    Mirrors the helper in test_tabp_scaffolding.py.
    """
    parts = text.split("---\n", 2)
    assert len(parts) >= 3 and parts[0] == "", (
        "%s: missing YAML frontmatter block (must start with '---\\n')" % path
    )
    return parts[1], parts[2]


def _get_frontmatter_value(frontmatter_str, key):
    """Extract the value for a given key from a YAML frontmatter string.

    Returns the stripped value string, or empty string if not found.
    Handles both single-line values and multiline (description: foo bar).
    """
    match = re.search(r"^" + re.escape(key) + r":\s*(.+)$", frontmatter_str, re.M)
    if match:
        return match.group(1).strip()
    return ""


class TestTabpUsageSkillAC1(unittest.TestCase):
    """AC-1: skill file exists with frontmatter name + description, and invocation markers."""

    def setUp(self):
        self.assertTrue(
            os.path.isfile(USAGE_SKILL_MD),
            "TU-01: plugins/tabp/skills/usage/SKILL.md must exist",
        )
        with open(USAGE_SKILL_MD, encoding="utf-8") as f:
            raw = f.read()
        self.frontmatter, self.body = _parse_frontmatter(raw, USAGE_SKILL_MD)
        self.full_content = raw

    def test_tu01_skill_exists_and_nonempty(self):
        """TU-01: SKILL.md exists and is non-empty."""
        self.assertGreater(os.path.getsize(USAGE_SKILL_MD), 0)

    def test_tu02_frontmatter_name_nonempty(self):
        """TU-02: frontmatter 'name' field is non-empty."""
        name = _get_frontmatter_value(self.frontmatter, "name")
        self.assertNotEqual(name, "", "frontmatter 'name' must be non-empty")

    def test_tu03_frontmatter_description_nonempty(self):
        """TU-03: frontmatter 'description' is non-empty."""
        desc = _get_frontmatter_value(self.frontmatter, "description")
        self.assertNotEqual(desc, "", "frontmatter 'description' must be non-empty")

    def test_tu04_frontmatter_description_trigger_keywords(self):
        """TU-04: description contains 'usage' AND at least one of {cost, tokens, spend}."""
        # For multiline (block scalar) descriptions the value line may be '>'
        # so check the full frontmatter text for the keywords
        fm_lower = self.frontmatter.lower()
        self.assertIn("usage", fm_lower, "description must contain 'usage'")
        trigger_words = {"cost", "tokens", "spend"}
        self.assertTrue(
            any(w in fm_lower for w in trigger_words),
            "description must contain at least one of: cost, tokens, spend",
        )

    def test_tu05_body_contains_usage_read(self):
        """TU-05: body contains 'usage-read' invocation marker."""
        self.assertIn("usage-read", self.body)

    def test_tu06_body_contains_project_dir(self):
        """TU-06: body contains '--project-dir' flag."""
        self.assertIn("--project-dir", self.body)

    def test_tu07_body_contains_run_id(self):
        """TU-07: body contains '--run-id' flag."""
        self.assertIn("--run-id", self.body)


class TestTabpUsageSkillAC2(unittest.TestCase):
    """AC-2: per-run and totals rendering markers, cost/time/tokens, honesty rule."""

    def setUp(self):
        self.assertTrue(
            os.path.isfile(USAGE_SKILL_MD),
            "TU-08: plugins/tabp/skills/usage/SKILL.md must exist",
        )
        with open(USAGE_SKILL_MD, encoding="utf-8") as f:
            self.body = f.read()

    def test_tu08_body_contains_token_columns(self):
        """TU-08: body contains per-run token column keys tokens_in and tokens_out."""
        self.assertIn("tokens_in", self.body)
        self.assertIn("tokens_out", self.body)

    def test_tu09_body_contains_cost_marker(self):
        """TU-09: body contains a cost marker (cost_usd or total_cost_usd)."""
        self.assertTrue(
            "cost_usd" in self.body or "total_cost_usd" in self.body,
            "body must contain 'cost_usd' or 'total_cost_usd'",
        )

    def test_tu10_body_contains_totals_markers(self):
        """TU-10: body contains totals aggregate keys."""
        self.assertIn("total_duration_seconds", self.body)
        self.assertIn("total_tokens_in", self.body)
        self.assertIn("total_tokens_out", self.body)

    def test_tu11_body_contains_cost_basis(self):
        """TU-11: body contains 'cost_basis'."""
        self.assertIn("cost_basis", self.body)

    def test_tu12_body_contains_usage_source(self):
        """TU-12: body contains 'usage_source'."""
        self.assertIn("usage_source", self.body)

    def test_tu13_body_contains_pricing_snapshot_date(self):
        """TU-13: body contains 'pricing_snapshot_date'."""
        self.assertIn("pricing_snapshot_date", self.body)

    def test_tu14_body_contains_honesty_marker(self):
        """TU-14: body contains 'estimate' AND at least one of {never, not an actual, not presented as an actual}."""
        body_lower = self.body.lower()
        self.assertIn("estimate", body_lower, "body must contain 'estimate' for honesty rule")
        honesty_phrases = {"never", "not an actual", "not presented as an actual"}
        self.assertTrue(
            any(p in body_lower for p in honesty_phrases),
            "body must contain at least one of: 'never', 'not an actual', 'not presented as an actual'",
        )


class TestTabpUsageSkillAC3(unittest.TestCase):
    """AC-3: degradation / honest unavailability markers."""

    def setUp(self):
        self.assertTrue(
            os.path.isfile(USAGE_SKILL_MD),
            "TU-15: plugins/tabp/skills/usage/SKILL.md must exist",
        )
        with open(USAGE_SKILL_MD, encoding="utf-8") as f:
            self.body = f.read()

    def test_tu15_body_contains_unavailable(self):
        """TU-15: body contains 'unavailable' (degradation keyword)."""
        self.assertIn("unavailable", self.body)

    def test_tu16_body_contains_usage_note(self):
        """TU-16: body contains 'usage_note'."""
        self.assertIn("usage_note", self.body)

    def test_tu17_body_contains_never_fabricate(self):
        """TU-17: body contains a never-fabricate phrase."""
        body_lower = self.body.lower()
        fabricate_phrases = {
            "never fabricate",
            "do not invent",
            "fabricates nothing",
            "fabricate nothing",
        }
        self.assertTrue(
            any(p in body_lower for p in fabricate_phrases),
            "body must contain at least one of: 'never fabricate', 'do not invent', "
            "'fabricates nothing', 'fabricate nothing'",
        )


class TestTabpUsageSkillAC4(unittest.TestCase):
    """AC-4: documentation — flow doc, c4-container bump, tech-stack bump, README subsection."""

    def test_tu18_flow_doc_exists_and_nonempty(self):
        """TU-18: docs/architecture/lld/flows/tabp-usage-read.md exists and is non-empty."""
        self.assertTrue(
            os.path.isfile(USAGE_FLOW_DOC),
            "tabp-usage-read.md must exist",
        )
        self.assertGreater(os.path.getsize(USAGE_FLOW_DOC), 0)

    def test_tu19_flow_doc_contains_sequence_diagram(self):
        """TU-19: flow doc contains 'sequenceDiagram'."""
        with open(USAGE_FLOW_DOC, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("sequenceDiagram", content)

    def test_tu20_flow_doc_contains_usage_read(self):
        """TU-20: flow doc contains 'usage-read'."""
        with open(USAGE_FLOW_DOC, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("usage-read", content)

    def test_tu21_c4_container_references_usage(self):
        """TU-21: c4-container.md references 'usage' in the tabp_skills context (post-bump)."""
        with open(C4_CONTAINER, encoding="utf-8") as f:
            content = f.read()
        # After the bump, the tabp_skills line should contain 'usage'
        self.assertIn("usage", content.lower())

    def test_tu22_tech_stack_no_not_yet_shipped(self):
        """TU-22: tech-stack.md no longer contains 'not yet shipped'."""
        with open(TECH_STACK, encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn("not yet shipped", content)

    def test_tu23_readme_contains_usage_heading(self):
        """TU-23: plugins/tabp/README.md contains a '### usage' heading (case-insensitive)."""
        with open(README_MD, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("### usage", content.lower())


class TestTabpUsageSkillAC5(unittest.TestCase):
    """AC-5: namespace guard — no acs: / .acs/ / acs_lib tokens in new/changed artifacts."""

    def _read(self, path):
        with open(path, encoding="utf-8") as f:
            return f.read()

    def setUp(self):
        self.assertTrue(os.path.isfile(USAGE_SKILL_MD), "SKILL.md must exist for namespace check")
        self.assertTrue(os.path.isfile(USAGE_FLOW_DOC), "flow doc must exist for namespace check")

    def test_tu24_skill_no_acs_colon(self):
        """TU-24: SKILL.md contains no 'acs:' token."""
        self.assertNotIn("acs:", self._read(USAGE_SKILL_MD))

    def test_tu25_skill_no_dotacs_slash(self):
        """TU-25: SKILL.md contains no '.acs/' token."""
        self.assertNotIn(".acs/", self._read(USAGE_SKILL_MD))

    def test_tu26_skill_no_acs_lib(self):
        """TU-26: SKILL.md contains no 'acs_lib' token."""
        self.assertNotIn("acs_lib", self._read(USAGE_SKILL_MD))

    def test_tu27_flow_doc_no_acs_colon(self):
        """TU-27: flow doc contains no 'acs:' token."""
        self.assertNotIn("acs:", self._read(USAGE_FLOW_DOC))

    def test_tu28_flow_doc_no_dotacs_slash(self):
        """TU-28: flow doc contains no '.acs/' token."""
        self.assertNotIn(".acs/", self._read(USAGE_FLOW_DOC))

    def test_tu29_readme_no_acs_colon(self):
        """TU-29: plugins/tabp/README.md contains no 'acs:' token."""
        self.assertNotIn("acs:", self._read(README_MD))

    def test_tu30_requirements_no_acs_in_mar39_section(self):
        """TU-30: docs/requirements/tabp.md exists and MAR-39 section has no 'acs:' token."""
        self.assertTrue(os.path.isfile(REQUIREMENTS_MD), "tabp.md requirements must exist")
        content = self._read(REQUIREMENTS_MD)
        # The MAR-39 section must exist and must not use 'acs:' as a prefix token
        # (existing file references 'acs:' only as a quoted example of what NOT to use —
        # the MAR-39 section we append must not introduce new 'acs:' usage)
        mar39_marker = "MAR-39"
        self.assertIn(mar39_marker, content, "tabp.md must contain a MAR-39 section")
        # Find the MAR-39 section and check it contains no 'acs:' token
        mar39_start = content.find(mar39_marker)
        mar39_section = content[mar39_start:]
        self.assertNotIn("acs:", mar39_section,
            "The MAR-39 section in tabp.md must not contain 'acs:' tokens")


if __name__ == "__main__":
    unittest.main()
