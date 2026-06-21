"""Structural tests for spec 03: tabp coordinator+subagents convention
and independent verification pass.

Covers:
  TC-01..TC-06 -- Agent charter file existence and YAML frontmatter (AC-2)
  TC-07..TC-10 -- SKILL.md additive markers + byte-stable core (AC-2, AC-3)
  TC-11..TC-15 -- Namespace guard: no acs: / .acs/ in new files (AC-6)
  T-01..T-09   -- screen-verifier-subagent charter structural assertions (AC-1, AC-2, AC-5)
  T-09a..e     -- SKILL.md independent-verifier wording assertions (AC-3, AC-4)
  T-10..T-15   -- SKILL.md / flow / README / namespace guards for MAR-37 (AC-3..AC-5)

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
SCREEN_VERIFIER_CHARTER = os.path.join(AGENTS_DIR, "screen-verifier-subagent.md")
SKILL_MD = os.path.join(TABP_DIR, "skills", "screen-cvs", "SKILL.md")
FLOW_DOC = os.path.join(
    REPO_ROOT, "docs", "architecture", "lld", "flows", "tabp-screening-state-write.md"
)
README_MD = os.path.join(TABP_DIR, "README.md")


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
    # TC-09 (REPLACED): SKILL.md independent-verifier Step 5a assertions
    # The old self-verification heading is retired; this test asserts the new wording.
    # ------------------------------------------------------------------
    def test_tc09_skill_md_independent_verification(self):
        """TC-09 (AC-3): SKILL.md Step 5a uses independent verifier (not self-verification).

        T-09a: no 'self-verification' (retired heading is gone).
        T-09b: 'screen-verifier-subagent' spawn marker present.
        T-09c: 'blocking' findings verdict language present.
        T-09d: 'present' gate marker present.
        T-09e: 'independent verif' framing present.
        """
        content = self._read_skill_md()

        # T-09a: no self-verification heading (step 5a heading is retired)
        self.assertNotRegex(
            content,
            r"(?i)self.verification",
            "SKILL.md must NOT contain 'self-verification' (Step 5a heading was retired — AC-3)",
        )

        # T-09b: verifier spawn marker
        self.assertIn(
            "screen-verifier-subagent",
            content,
            "SKILL.md must contain 'screen-verifier-subagent' (verifier spawn marker — AC-3)",
        )

        # T-09c: blocking-findings verdict language
        self.assertRegex(
            content,
            r"(?i)blocking.findings",
            "SKILL.md must contain 'blocking findings' (verifier verdict language — AC-3)",
        )

        # T-09d: present-only-after-clean gate marker
        self.assertIn(
            "present",
            content,
            "SKILL.md must contain 'present' (result-presentation gate marker — AC-3)",
        )

        # T-09e: independent-verifier framing
        self.assertRegex(
            content,
            r"(?i)independent verif",
            "SKILL.md must contain 'independent verif' framing (AC-3, AC-4)",
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


# ---------------------------------------------------------------------------
# MAR-37: TestVerifierCharter  (T-01..T-09)
# New class: structural assertions for the screen-verifier-subagent charter.
# ---------------------------------------------------------------------------
class TestVerifierCharter(unittest.TestCase):
    """T-01..T-09: screen-verifier-subagent charter structural assertions (AC-1, AC-2, AC-5)."""

    def _read_charter(self):
        with open(SCREEN_VERIFIER_CHARTER, encoding="utf-8") as fh:
            return fh.read()

    # ------------------------------------------------------------------
    # T-01: charter file exists and is non-empty
    # ------------------------------------------------------------------
    def test_t01_verifier_charter_exists(self):
        """T-01 (AC-1): plugins/tabp/agents/screen-verifier-subagent.md exists and is non-empty."""
        self.assertTrue(
            os.path.isfile(SCREEN_VERIFIER_CHARTER),
            "plugins/tabp/agents/screen-verifier-subagent.md not found at %s"
            % SCREEN_VERIFIER_CHARTER,
        )
        self.assertGreater(
            os.path.getsize(SCREEN_VERIFIER_CHARTER),
            0,
            "plugins/tabp/agents/screen-verifier-subagent.md must be non-empty",
        )

    # ------------------------------------------------------------------
    # T-02: frontmatter 'name' is non-empty and contains no 'acs:'
    # ------------------------------------------------------------------
    def test_t02_verifier_charter_name_frontmatter(self):
        """T-02 (AC-1, AC-5): charter frontmatter 'name' is non-empty and has no 'acs:'."""
        text = self._read_charter()
        fm, _body = _parse_frontmatter(text, SCREEN_VERIFIER_CHARTER)
        name_val = _get_frontmatter_value(fm, "name")
        self.assertTrue(
            name_val,
            "screen-verifier-subagent.md frontmatter 'name' must be non-empty",
        )
        self.assertNotIn(
            "acs:",
            name_val,
            "screen-verifier-subagent.md frontmatter 'name' must not contain 'acs:'",
        )

    # ------------------------------------------------------------------
    # T-03: frontmatter 'description' is non-empty and contains no 'acs:'
    # ------------------------------------------------------------------
    def test_t03_verifier_charter_description_frontmatter(self):
        """T-03 (AC-1, AC-5): charter frontmatter 'description' is non-empty and has no 'acs:'."""
        text = self._read_charter()
        fm, _body = _parse_frontmatter(text, SCREEN_VERIFIER_CHARTER)
        desc_val = _get_frontmatter_value(fm, "description")
        self.assertTrue(
            desc_val,
            "screen-verifier-subagent.md frontmatter 'description' must be non-empty",
        )
        self.assertNotIn(
            "acs:",
            desc_val,
            "screen-verifier-subagent.md frontmatter 'description' must not contain 'acs:'",
        )

    # ------------------------------------------------------------------
    # T-04: body contains all six input-contract markers
    # ------------------------------------------------------------------
    def test_t04_verifier_charter_six_inputs(self):
        """T-04 (AC-1): charter body contains all six artifact-only input markers."""
        text = self._read_charter()
        _fm, body = _parse_frontmatter(text, SCREEN_VERIFIER_CHARTER)
        for marker in [
            "run_id",
            "jd_requirements",
            "evidence_records",
            "synthesis_result",
            "scoring_rubric",
            "fairness_guidelines",
        ]:
            self.assertIn(
                marker,
                body,
                "screen-verifier-subagent.md body must contain input marker '%s'" % marker,
            )

    # ------------------------------------------------------------------
    # T-05a: body contains 'pass' verdict marker
    # ------------------------------------------------------------------
    def test_t05a_verifier_charter_pass_verdict(self):
        """T-05a (AC-2): charter body contains 'pass' output-contract verdict marker."""
        text = self._read_charter()
        _fm, body = _parse_frontmatter(text, SCREEN_VERIFIER_CHARTER)
        self.assertIn(
            "pass",
            body,
            "screen-verifier-subagent.md body must contain 'pass' verdict marker (Output contract)",
        )

    # ------------------------------------------------------------------
    # T-05b: body contains 'blocking' verdict marker
    # ------------------------------------------------------------------
    def test_t05b_verifier_charter_blocking_verdict(self):
        """T-05b (AC-2): charter body contains 'blocking' output-contract verdict marker."""
        text = self._read_charter()
        _fm, body = _parse_frontmatter(text, SCREEN_VERIFIER_CHARTER)
        self.assertIn(
            "blocking",
            body,
            "screen-verifier-subagent.md body must contain 'blocking' verdict marker (Output contract)",
        )

    # ------------------------------------------------------------------
    # T-06: body contains no-state-writes mandate
    # ------------------------------------------------------------------
    def test_t06_verifier_charter_no_state_writes(self):
        """T-06 (AC-1): charter body contains no-state-writes mandate."""
        text = self._read_charter()
        _fm, body = _parse_frontmatter(text, SCREEN_VERIFIER_CHARTER)
        has_mandate = "No state writes" in body or "does not invoke" in body
        self.assertTrue(
            has_mandate,
            "screen-verifier-subagent.md body must contain 'No state writes' or 'does not invoke' mandate",
        )

    # ------------------------------------------------------------------
    # T-07: no 'acs:' anywhere in full file
    # ------------------------------------------------------------------
    def test_t07_verifier_charter_no_acs_prefix(self):
        """T-07 (AC-5): charter file must not contain 'acs:' anywhere."""
        text = self._read_charter()
        self.assertNotIn(
            "acs:",
            text,
            "screen-verifier-subagent.md must not contain 'acs:' (namespace guard AC-5/AC-6)",
        )

    # ------------------------------------------------------------------
    # T-08: no '.acs/' anywhere in full file
    # ------------------------------------------------------------------
    def test_t08_verifier_charter_no_dotacs_token(self):
        """T-08 (AC-5): charter file must not contain '.acs/' anywhere."""
        text = self._read_charter()
        self.assertNotIn(
            ".acs/",
            text,
            "screen-verifier-subagent.md must not contain '.acs/' (namespace guard AC-5/AC-6)",
        )

    # ------------------------------------------------------------------
    # T-09 (charter): no 'acs_lib' anywhere in full file
    # ------------------------------------------------------------------
    def test_t09_verifier_charter_no_acs_lib(self):
        """T-09 charter (AC-5): charter file must not contain 'acs_lib' anywhere."""
        text = self._read_charter()
        self.assertNotIn(
            "acs_lib",
            text,
            "screen-verifier-subagent.md must not contain 'acs_lib' (namespace guard AC-5/AC-6)",
        )


# ---------------------------------------------------------------------------
# MAR-37: TestIndependentVerifierFlow  (T-10..T-15 + T-14a..e)
# New class: SKILL.md / flow / README structural assertions for MAR-37.
# ---------------------------------------------------------------------------
class TestIndependentVerifierFlow(unittest.TestCase):
    """T-10..T-15: SKILL.md / flow / README structural assertions (AC-3, AC-4, AC-5)."""

    def _read_skill_md(self):
        with open(SKILL_MD, encoding="utf-8") as fh:
            return fh.read()

    def _read_flow_doc(self):
        with open(FLOW_DOC, encoding="utf-8") as fh:
            return fh.read()

    def _read_readme(self):
        with open(README_MD, encoding="utf-8") as fh:
            return fh.read()

    # ------------------------------------------------------------------
    # T-10: SKILL.md contains N=3 cap marker
    # Use re.IGNORECASE flag separately to avoid inline (?i) alternation issue.
    # ------------------------------------------------------------------
    def test_t10_skill_md_n3_cap_marker(self):
        """T-10 (AC-3): SKILL.md contains the N=3 loop cap marker."""
        content = self._read_skill_md()
        # Check for 'N=3' first (simple substring), then regex patterns
        has_cap = (
            "N=3" in content
            or bool(re.search(r"capped.*(N=3|3 iterations)", content, re.IGNORECASE))
        )
        self.assertTrue(
            has_cap,
            "SKILL.md must contain N=3 cap marker (AC-3: bounded remediate-and-re-verify loop)",
        )

    # ------------------------------------------------------------------
    # T-11: SKILL.md contains 'verification_passed' (independent verdict in Step 5b)
    # ------------------------------------------------------------------
    def test_t11_skill_md_verification_passed(self):
        """T-11 (AC-4): SKILL.md Step 5b contains 'verification_passed' (independent verdict)."""
        content = self._read_skill_md()
        self.assertIn(
            "verification_passed",
            content,
            "SKILL.md must contain 'verification_passed' (Step 5b independent verdict — AC-4)",
        )

    # ------------------------------------------------------------------
    # T-12: flow doc does NOT contain 'self-verification pass'
    # ------------------------------------------------------------------
    def test_t12_flow_doc_no_self_verification_pass(self):
        """T-12 (AC-3): tabp-screening-state-write.md must not contain 'self-verification pass'."""
        content = self._read_flow_doc()
        self.assertNotIn(
            "self-verification pass",
            content,
            "tabp-screening-state-write.md must not contain 'self-verification pass' (AC-3: retired)",
        )

    # ------------------------------------------------------------------
    # T-13: flow doc contains verifier subagent reference
    # ------------------------------------------------------------------
    def test_t13_flow_doc_verifier_subagent_reference(self):
        """T-13 (AC-3): flow doc contains 'screen-verifier-subagent' or 'Verifier subagent'."""
        content = self._read_flow_doc()
        has_ref = "screen-verifier-subagent" in content or "Verifier subagent" in content
        self.assertTrue(
            has_ref,
            "tabp-screening-state-write.md must reference 'screen-verifier-subagent' or "
            "'Verifier subagent' (AC-3: verifier exchange must be documented)",
        )

    # ------------------------------------------------------------------
    # T-14a: SKILL.md contains no 'acs:' token
    # ------------------------------------------------------------------
    def test_t14a_skill_md_no_acs_prefix(self):
        """T-14a (AC-5): SKILL.md must not contain 'acs:' anywhere."""
        content = self._read_skill_md()
        self.assertNotIn(
            "acs:",
            content,
            "SKILL.md must not contain 'acs:' (namespace guard AC-5/AC-6)",
        )

    # ------------------------------------------------------------------
    # T-14b: flow doc contains no 'acs:' token
    # ------------------------------------------------------------------
    def test_t14b_flow_doc_no_acs_prefix(self):
        """T-14b (AC-5): tabp-screening-state-write.md must not contain 'acs:' anywhere."""
        content = self._read_flow_doc()
        self.assertNotIn(
            "acs:",
            content,
            "tabp-screening-state-write.md must not contain 'acs:' (namespace guard AC-5/AC-6)",
        )

    # ------------------------------------------------------------------
    # T-14c: README contains no 'acs:' token
    # ------------------------------------------------------------------
    def test_t14c_readme_no_acs_prefix(self):
        """T-14c (AC-5): plugins/tabp/README.md must not contain 'acs:' anywhere."""
        content = self._read_readme()
        self.assertNotIn(
            "acs:",
            content,
            "plugins/tabp/README.md must not contain 'acs:' (namespace guard AC-5/AC-6)",
        )

    # ------------------------------------------------------------------
    # T-14d: SKILL.md contains no '.acs/' token
    # ------------------------------------------------------------------
    def test_t14d_skill_md_no_dotacs_token(self):
        """T-14d (AC-5): SKILL.md must not contain '.acs/' anywhere."""
        content = self._read_skill_md()
        self.assertNotIn(
            ".acs/",
            content,
            "SKILL.md must not contain '.acs/' (namespace guard AC-5/AC-6)",
        )

    # ------------------------------------------------------------------
    # T-14e: flow doc contains no '.acs/' token
    # ------------------------------------------------------------------
    def test_t14e_flow_doc_no_dotacs_token(self):
        """T-14e (AC-5): tabp-screening-state-write.md must not contain '.acs/' anywhere."""
        content = self._read_flow_doc()
        self.assertNotIn(
            ".acs/",
            content,
            "tabp-screening-state-write.md must not contain '.acs/' (namespace guard AC-5/AC-6)",
        )

    # ------------------------------------------------------------------
    # T-15: TC-10 byte-stable guard still passes (regression check reference)
    # TC-10 is tested in TestSkillMdAdditions.test_tc10_scoring_fairness_core_byte_stable.
    # This test confirms the ## Step 4 heading is still in SKILL.md (no heading removal).
    # ------------------------------------------------------------------
    def test_t15_tc10_regression_byte_stable_block_present(self):
        """T-15 (regression): ## Step 4 and ## Step 5 headings still present in SKILL.md."""
        content = self._read_skill_md()
        self.assertIn(
            "## Step 4",
            content,
            "SKILL.md must still contain '## Step 4' heading (TC-10 byte-stable region)",
        )
        # ## Step 5 heading (matches '## Step 5 — ...' via startswith pattern)
        self.assertTrue(
            bool(re.search(r"^## Step 5 ", content, re.MULTILINE)),
            "SKILL.md must still contain '## Step 5' heading (TC-10 byte-stable region)",
        )


if __name__ == "__main__":
    unittest.main()
