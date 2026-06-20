"""Structural tests for spec 03: tabp coordinator+subagents convention
and self-verification pass.

Covers:
  TC-01..TC-06 -- Agent charter file existence and YAML frontmatter (AC-2)
  TC-07..TC-10 -- SKILL.md additive markers + byte-stable core (AC-2, AC-3)
  TC-11..TC-15 -- Namespace guard: no acs: / .acs/ in new files (AC-6)

No model calls. No subprocess. Stdlib only.
Run: python3 -m unittest tests.tabp.test_tabp_scaffolding -v
"""

import os
import re
import unittest

# REPO_ROOT: tests/tabp/test_tabp_scaffolding.py
# dirname x1 -> tests/tabp
# dirname x2 -> tests
# dirname x3 -> repo root
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TABP_DIR = os.path.join(REPO_ROOT, "plugins", "tabp")
AGENTS_DIR = os.path.join(TABP_DIR, "agents")
SCREEN_CV_CHARTER = os.path.join(AGENTS_DIR, "screen-cv-subagent.md")
SYNTHESIS_CHARTER = os.path.join(AGENTS_DIR, "synthesis-subagent.md")
SKILL_MD = os.path.join(TABP_DIR, "skills", "screen-cvs", "SKILL.md")


def _parse_frontmatter(text, path):
    """Extract YAML frontmatter block between first and second '---' lines.

    Returns (frontmatter_str, body_str) or raises AssertionError.
    Mirrors the helper in test_tabp_plugin.py.
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


# ---------------------------------------------------------------------------
# Fixture: the byte-stable core block (between ## Step 4 and ## Step 5,
# pre-MAR-2 SKILL.md). TC-10 compares the live file's block to this.
# Captured verbatim from screen-cvs/SKILL.md before any MAR-2 edits.
# ---------------------------------------------------------------------------
STEP4_TO_STEP5_FIXTURE = (
    "## Step 4 — Apply fairness guardrails\n"
    "\n"
    "Before scoring, read `references/fairness-guidelines.md` and follow it "
    "throughout. Core rules:\n"
    "\n"
    "- Evaluate **only job-relevant qualifications**.\n"
    "- Do **not** infer, use, or comment on protected characteristics (age, gender, "
    "race/ethnicity, national origin, religion, disability, marital/family status, "
    "etc.) or proxies for them (graduation dates as age signals, names, photos).\n"
    "- Treat employment gaps neutrally — note them without penalizing.\n"
    "- Apply identical criteria to every candidate in a batch.\n"
    "- If the JD itself contains a non-job-relevant or potentially discriminatory "
    "requirement, flag it to the user rather than scoring against it.\n"
    "\n"
)


class TestAgentCharters(unittest.TestCase):
    """TC-01..TC-06: Agent charter files exist with valid YAML frontmatter (AC-2)."""

    # ------------------------------------------------------------------
    # TC-01: screen-cv-subagent.md exists
    # ------------------------------------------------------------------
    def test_tc01_screen_cv_subagent_exists(self):
        """TC-01 (AC-2): plugins/tabp/agents/screen-cv-subagent.md exists and is non-empty."""
        self.assertTrue(
            os.path.isfile(SCREEN_CV_CHARTER),
            "plugins/tabp/agents/screen-cv-subagent.md not found at %s" % SCREEN_CV_CHARTER,
        )
        self.assertGreater(
            os.path.getsize(SCREEN_CV_CHARTER),
            0,
            "plugins/tabp/agents/screen-cv-subagent.md must be non-empty",
        )

    # ------------------------------------------------------------------
    # TC-02: screen-cv-subagent.md has valid 'name' frontmatter
    # ------------------------------------------------------------------
    def test_tc02_screen_cv_subagent_name_frontmatter(self):
        """TC-02 (AC-2): screen-cv-subagent.md has non-empty 'name' frontmatter without 'acs:'."""
        with open(SCREEN_CV_CHARTER, encoding="utf-8") as fh:
            text = fh.read()
        fm, _body = _parse_frontmatter(text, SCREEN_CV_CHARTER)
        name_val = _get_frontmatter_value(fm, "name")
        self.assertTrue(name_val, "screen-cv-subagent.md frontmatter 'name' must be non-empty")
        self.assertNotIn(
            "acs:",
            name_val,
            "screen-cv-subagent.md frontmatter 'name' must not contain 'acs:'",
        )

    # ------------------------------------------------------------------
    # TC-03: screen-cv-subagent.md has valid 'description' frontmatter
    # ------------------------------------------------------------------
    def test_tc03_screen_cv_subagent_description_frontmatter(self):
        """TC-03 (AC-2): screen-cv-subagent.md has non-empty 'description' frontmatter without 'acs:'."""
        with open(SCREEN_CV_CHARTER, encoding="utf-8") as fh:
            text = fh.read()
        fm, _body = _parse_frontmatter(text, SCREEN_CV_CHARTER)
        desc_val = _get_frontmatter_value(fm, "description")
        self.assertTrue(
            desc_val,
            "screen-cv-subagent.md frontmatter 'description' must be non-empty",
        )
        self.assertNotIn(
            "acs:",
            desc_val,
            "screen-cv-subagent.md frontmatter 'description' must not contain 'acs:'",
        )

    # ------------------------------------------------------------------
    # TC-04: synthesis-subagent.md exists
    # ------------------------------------------------------------------
    def test_tc04_synthesis_subagent_exists(self):
        """TC-04 (AC-2): plugins/tabp/agents/synthesis-subagent.md exists and is non-empty."""
        self.assertTrue(
            os.path.isfile(SYNTHESIS_CHARTER),
            "plugins/tabp/agents/synthesis-subagent.md not found at %s" % SYNTHESIS_CHARTER,
        )
        self.assertGreater(
            os.path.getsize(SYNTHESIS_CHARTER),
            0,
            "plugins/tabp/agents/synthesis-subagent.md must be non-empty",
        )

    # ------------------------------------------------------------------
    # TC-05: synthesis-subagent.md has valid 'name' frontmatter
    # ------------------------------------------------------------------
    def test_tc05_synthesis_subagent_name_frontmatter(self):
        """TC-05 (AC-2): synthesis-subagent.md has non-empty 'name' frontmatter without 'acs:'."""
        with open(SYNTHESIS_CHARTER, encoding="utf-8") as fh:
            text = fh.read()
        fm, _body = _parse_frontmatter(text, SYNTHESIS_CHARTER)
        name_val = _get_frontmatter_value(fm, "name")
        self.assertTrue(name_val, "synthesis-subagent.md frontmatter 'name' must be non-empty")
        self.assertNotIn(
            "acs:",
            name_val,
            "synthesis-subagent.md frontmatter 'name' must not contain 'acs:'",
        )

    # ------------------------------------------------------------------
    # TC-06: synthesis-subagent.md has valid 'description' frontmatter
    # ------------------------------------------------------------------
    def test_tc06_synthesis_subagent_description_frontmatter(self):
        """TC-06 (AC-2): synthesis-subagent.md has non-empty 'description' frontmatter without 'acs:'."""
        with open(SYNTHESIS_CHARTER, encoding="utf-8") as fh:
            text = fh.read()
        fm, _body = _parse_frontmatter(text, SYNTHESIS_CHARTER)
        desc_val = _get_frontmatter_value(fm, "description")
        self.assertTrue(
            desc_val,
            "synthesis-subagent.md frontmatter 'description' must be non-empty",
        )
        self.assertNotIn(
            "acs:",
            desc_val,
            "synthesis-subagent.md frontmatter 'description' must not contain 'acs:'",
        )


class TestSkillMdAdditions(unittest.TestCase):
    """TC-07..TC-10: SKILL.md additive markers and byte-stable core (AC-2, AC-3)."""

    def _read_skill_md(self):
        with open(SKILL_MD, encoding="utf-8") as fh:
            return fh.read()

    # ------------------------------------------------------------------
    # TC-07: SKILL.md contains run-start invocation marker (Step 0)
    # ------------------------------------------------------------------
    def test_tc07_skill_md_contains_run_start(self):
        """TC-07 (AC-2, AC-3): SKILL.md Step 0 contains 'run-start' invocation marker."""
        content = self._read_skill_md()
        self.assertIn(
            "run-start",
            content,
            "SKILL.md must contain 'run-start' marker (Step 0 wiring)",
        )

    # ------------------------------------------------------------------
    # TC-08: SKILL.md contains per-CV subagent fan-out marker (Step 3a)
    # ------------------------------------------------------------------
    def test_tc08_skill_md_contains_screen_cv_subagent(self):
        """TC-08 (AC-2): SKILL.md Step 3a references 'screen-cv-subagent' for the fan-out."""
        content = self._read_skill_md()
        self.assertIn(
            "screen-cv-subagent",
            content,
            "SKILL.md must contain 'screen-cv-subagent' marker (Step 3a fan-out)",
        )

    # ------------------------------------------------------------------
    # TC-09: SKILL.md contains the self-verification-before-present gate
    # ------------------------------------------------------------------
    def test_tc09_skill_md_contains_self_verification_pass(self):
        """TC-09 (AC-3): SKILL.md Step 5a contains 'self-verification' heading and
        both 'present' and 'blocking findings' in that section."""
        content = self._read_skill_md()
        # Check heading (case-insensitive)
        self.assertRegex(
            content,
            r"(?i)self.verification",
            "SKILL.md must contain a 'self-verification' (or 'Self-verification') section (Step 5a heading)",
        )
        # Check 'present' and 'blocking findings' both appear in the file
        self.assertIn(
            "blocking findings",
            content,
            "SKILL.md must contain 'blocking findings' in Step 5a (AC-3 gate)",
        )
        # 'present' must appear in context of Step 5a
        self.assertIn(
            "present",
            content,
            "SKILL.md must contain 'present' in proximity to the self-verification gate (Step 5a)",
        )

    # ------------------------------------------------------------------
    # TC-10: Byte-stable core regression guard
    # The block from '## Step 4' to (but not including) '## Step 5' must
    # be byte-for-byte identical to the pre-MAR-2 fixture above.
    # ------------------------------------------------------------------
    def test_tc10_scoring_fairness_core_byte_stable(self):
        """TC-10 (regression guard): The ## Step 4 ... ## Step 5 block is unchanged.

        Spec 03 inserts Step 3a BEFORE Step 4, so line numbers shift. This test
        anchors on the heading strings, not raw line numbers.
        """
        content = self._read_skill_md()
        step4_idx = content.find("## Step 4")
        step5_idx = content.find("## Step 5")
        self.assertNotEqual(
            step4_idx, -1, "SKILL.md must contain '## Step 4' heading"
        )
        self.assertNotEqual(
            step5_idx, -1, "SKILL.md must contain '## Step 5' heading"
        )
        self.assertGreater(
            step5_idx,
            step4_idx,
            "'## Step 5' must appear after '## Step 4' in SKILL.md",
        )
        actual_core_block = content[step4_idx:step5_idx]
        if actual_core_block != STEP4_TO_STEP5_FIXTURE:
            # Produce a line-by-line diff for the failure message
            actual_lines = actual_core_block.splitlines(keepends=True)
            expected_lines = STEP4_TO_STEP5_FIXTURE.splitlines(keepends=True)
            diff_lines = []
            max_len = max(len(actual_lines), len(expected_lines))
            for i in range(max_len):
                a = actual_lines[i] if i < len(actual_lines) else "<missing>"
                e = expected_lines[i] if i < len(expected_lines) else "<missing>"
                if a != e:
                    diff_lines.append(
                        "Line %d differs:\n  expected: %r\n  actual:   %r" % (i + 1, e, a)
                    )
            self.fail(
                "Scoring/fairness core (## Step 4 .. ## Step 5) has changed.\n"
                + "\n".join(diff_lines)
            )


class TestNamespaceGuard(unittest.TestCase):
    """TC-11..TC-15: AC-6 namespace assertions for this spec's new files."""

    # ------------------------------------------------------------------
    # TC-11: screen-cv-subagent.md contains no 'acs:' token
    # ------------------------------------------------------------------
    def test_tc11_screen_cv_subagent_no_acs_prefix(self):
        """TC-11 (AC-6): screen-cv-subagent.md must not contain 'acs:' anywhere."""
        with open(SCREEN_CV_CHARTER, encoding="utf-8") as fh:
            content = fh.read()
        self.assertNotIn(
            "acs:",
            content,
            "screen-cv-subagent.md must not contain 'acs:' (namespace guard AC-6)",
        )

    # ------------------------------------------------------------------
    # TC-12: screen-cv-subagent.md contains no '.acs/' token
    # ------------------------------------------------------------------
    def test_tc12_screen_cv_subagent_no_dotacs_token(self):
        """TC-12 (AC-6): screen-cv-subagent.md must not contain '.acs/' anywhere."""
        with open(SCREEN_CV_CHARTER, encoding="utf-8") as fh:
            content = fh.read()
        self.assertNotIn(
            ".acs/",
            content,
            "screen-cv-subagent.md must not contain '.acs/' (namespace guard AC-6)",
        )

    # ------------------------------------------------------------------
    # TC-13: synthesis-subagent.md contains no 'acs:' token
    # ------------------------------------------------------------------
    def test_tc13_synthesis_subagent_no_acs_prefix(self):
        """TC-13 (AC-6): synthesis-subagent.md must not contain 'acs:' anywhere."""
        with open(SYNTHESIS_CHARTER, encoding="utf-8") as fh:
            content = fh.read()
        self.assertNotIn(
            "acs:",
            content,
            "synthesis-subagent.md must not contain 'acs:' (namespace guard AC-6)",
        )

    # ------------------------------------------------------------------
    # TC-14: synthesis-subagent.md contains no '.acs/' token
    # ------------------------------------------------------------------
    def test_tc14_synthesis_subagent_no_dotacs_token(self):
        """TC-14 (AC-6): synthesis-subagent.md must not contain '.acs/' anywhere."""
        with open(SYNTHESIS_CHARTER, encoding="utf-8") as fh:
            content = fh.read()
        self.assertNotIn(
            ".acs/",
            content,
            "synthesis-subagent.md must not contain '.acs/' (namespace guard AC-6)",
        )

    # ------------------------------------------------------------------
    # TC-15: SKILL.md additions contain no 'acs:' token
    # ------------------------------------------------------------------
    def test_tc15_skill_md_no_acs_token(self):
        """TC-15 (AC-6): SKILL.md must not contain 'acs:' anywhere (covers new additions)."""
        with open(SKILL_MD, encoding="utf-8") as fh:
            content = fh.read()
        self.assertNotIn(
            "acs:",
            content,
            "SKILL.md must not contain 'acs:' anywhere (namespace guard AC-6)",
        )


if __name__ == "__main__":
    unittest.main()
