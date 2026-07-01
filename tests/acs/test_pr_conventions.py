"""Unit tests for the PR-convention helper CLI (MAR-72 spec 01).

plugins/acs/hooks/scripts/pr-conventions.py gives SKILL prose a deterministic
way to (a) render the configured PR title via acs_lib.render_format and (b)
self-check a rendered title + body against the repo's configured PR
conventions by driving check-conventions.py's evaluate() — never a divergent
re-implementation of the convention rules.

Loaded via the same importlib file-path pattern as
tests/acs/test_conventions_check.py, so these tests exercise the shipped file
directly, not an installed copy.

Run:  python3 -m unittest discover -s tests -v
"""

import importlib.util
import os
import unittest
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TARGET = os.path.join(REPO_ROOT, "plugins", "acs", "hooks", "scripts", "pr-conventions.py")

_spec = importlib.util.spec_from_file_location("acs_pr_conventions", TARGET)
pc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pc)


DEFAULT_SECTIONS = ["Summary", "Ticket", "Changes", "Test plan"]


def conforming_body():
    return (
        "## Summary\nSome summary text.\n\n"
        "## Ticket\n\n- **MAR-72** — Fix thing (task)\n\n"
        "## Changes\n\n- did stuff\n\n"
        "## Test plan\n\n- ran tests\n"
    )


class TestRenderTitle(unittest.TestCase):
    """Case 1 & 2: render-title reuses acs_lib.render_format verbatim."""

    def test_default_pr_title_render(self):
        # Case 1: default pr_title format renders exactly.
        result = pc.build_title(
            template="[{ticket_id}] {title}",
            ticket_id="MAR-72",
            type_="task",
            title="Fix thing",
            summary="",
            external_key="",
        )
        self.assertEqual(result, "[MAR-72] Fix thing")

    def test_custom_pr_title_render(self):
        # Case 2: custom (non-default) pr_title format.
        result = pc.build_title(
            template="PR: {ticket_id} — {title}",
            ticket_id="MAR-72",
            type_="task",
            title="Fix thing",
            summary="",
            external_key="",
        )
        self.assertEqual(result, "PR: MAR-72 — Fix thing")

    def test_custom_pr_title_full_token_vocabulary(self):
        # Full mapping: {type}/{summary}/{external_key} all render.
        result = pc.build_title(
            template="[{ticket_id}]({type}) {title} - {summary} ({external_key})",
            ticket_id="MAR-72",
            type_="task",
            title="Fix thing",
            summary="short summary",
            external_key="ACME-9",
        )
        self.assertEqual(
            result,
            "[MAR-72](task) Fix thing - short summary (ACME-9)",
        )

    def test_omitted_flag_renders_as_empty_string(self):
        # An omitted token renders empty, matching render_format's own behavior.
        result = pc.build_title(
            template="[{ticket_id}] {title} {external_key}",
            ticket_id="MAR-72",
            type_="",
            title="Fix thing",
            summary="",
            external_key="",
        )
        self.assertEqual(result, "[MAR-72] Fix thing ")

    def test_render_title_uses_acs_lib_render_format(self):
        # White-box: build_title must call acs_lib.render_format, not
        # reimplement the substitution.
        with mock.patch.object(pc.lib, "render_format",
                                wraps=pc.lib.render_format) as spy:
            pc.build_title(
                template="[{ticket_id}] {title}",
                ticket_id="MAR-72",
                type_="task",
                title="Fix thing",
                summary="",
                external_key="",
            )
        spy.assert_called_once()


class TestCheckPasses(unittest.TestCase):
    """Case 3: check passes a conforming title + body."""

    def test_check_passes_conforming_title_and_body(self):
        result = pc.run_check(
            title="[MAR-72] Fix thing",
            body=conforming_body(),
            require_label="ACS",
            pr_title_format="[{ticket_id}] {title}",
            sections=DEFAULT_SECTIONS,
            ticket_prefix="MAR",
        )
        self.assertTrue(result["passed"])
        self.assertEqual(result["errors"], [])


class TestCheckFailures(unittest.TestCase):
    """Cases 4-7: check fails malformed title / missing section / placeholder / comment."""

    def test_check_fails_malformed_title(self):
        # Case 4: title missing the required [MAR-72] prefix.
        result = pc.run_check(
            title="Fix thing",
            body=conforming_body(),
            require_label="ACS",
            pr_title_format="[{ticket_id}] {title}",
            sections=DEFAULT_SECTIONS,
            ticket_prefix="MAR",
        )
        self.assertFalse(result["passed"])
        headings = [e["heading"] for e in result["errors"]]
        self.assertIn("pr_title", headings)

    def test_check_fails_missing_required_section(self):
        # Case 5: body omits "## Test plan".
        body = (
            "## Summary\nSome summary text.\n\n"
            "## Ticket\n\n- **MAR-72** — Fix thing (task)\n\n"
            "## Changes\n\n- did stuff\n"
        )
        result = pc.run_check(
            title="[MAR-72] Fix thing",
            body=body,
            require_label="ACS",
            pr_title_format="[{ticket_id}] {title}",
            sections=DEFAULT_SECTIONS,
            ticket_prefix="MAR",
        )
        self.assertFalse(result["passed"])
        headings = [e["heading"] for e in result["errors"]]
        self.assertIn("pr_description", headings)

    def test_check_fails_unrendered_placeholder(self):
        # Case 6: a literal {summary} token survived in the body.
        body = conforming_body() + "\n{summary}\n"
        result = pc.run_check(
            title="[MAR-72] Fix thing",
            body=body,
            require_label="ACS",
            pr_title_format="[{ticket_id}] {title}",
            sections=DEFAULT_SECTIONS,
            ticket_prefix="MAR",
        )
        self.assertFalse(result["passed"])
        headings = [e["heading"] for e in result["errors"]]
        self.assertIn("unrendered_placeholder", headings)

    def test_check_fails_leftover_template_comment(self):
        # Case 7: an un-deleted HTML guidance comment survived.
        body = conforming_body() + "\n<!-- fill this in -->\n"
        result = pc.run_check(
            title="[MAR-72] Fix thing",
            body=body,
            require_label="ACS",
            pr_title_format="[{ticket_id}] {title}",
            sections=DEFAULT_SECTIONS,
            ticket_prefix="MAR",
        )
        self.assertFalse(result["passed"])
        headings = [e["heading"] for e in result["errors"]]
        self.assertIn("leftover_template_comment", headings)


class TestScopingRegression(unittest.TestCase):
    """Case 8: no regression to ACS label, base-branch detection, or tracker sync."""

    def test_no_branch_name_or_commit_message_finding_ever(self):
        # Construct a call where title/body conform but WOULD violate
        # branch_name/commit_message if those checks ran (they never do here,
        # since the helper never receives a branch or commit subjects).
        result = pc.run_check(
            title="[MAR-72] Fix thing",
            body=conforming_body(),
            require_label="ACS",
            pr_title_format="[{ticket_id}] {title}",
            sections=DEFAULT_SECTIONS,
            ticket_prefix="MAR",
        )
        headings = [e["heading"] for e in result["errors"]]
        self.assertNotIn("branch_name", headings)
        self.assertNotIn("commit_message", headings)

    def test_omitting_require_label_still_runs_acs_label(self):
        # Omitting --require-label does NOT silently disable acs_label — it
        # is left enabled by default and reports a finding because no label
        # was asserted.
        result = pc.run_check(
            title="[MAR-72] Fix thing",
            body=conforming_body(),
            require_label="",
            pr_title_format="[{ticket_id}] {title}",
            sections=DEFAULT_SECTIONS,
            ticket_prefix="MAR",
        )
        headings = [e["heading"] for e in result["errors"]]
        self.assertIn("acs_label", headings)

    def test_helper_module_has_no_git_or_tracker_reference(self):
        # Behavioral: the helper's own EXECUTABLE source never touches git,
        # base-branch detection, or tracker-sync logic — nothing to regress.
        # (Module-level prose documenting the caller's contract, e.g. "pass
        # verbatim to gh pr create/edit --title", is not executable logic and
        # is excluded by stripping the leading module docstring first.)
        with open(TARGET, "r", encoding="utf-8") as fh:
            src = fh.read()
        _, _, code_after_docstring = src.partition('"""')
        _, _, code = code_after_docstring.partition('"""')
        self.assertNotIn("subprocess", code)
        self.assertNotIn("import git", code)
        self.assertNotIn("gh issue", code)
        self.assertNotIn("acli jira", code)


class TestEvaluateReuse(unittest.TestCase):
    """Case 9: check path calls the importlib-loaded cc.evaluate — pins AC-3."""

    def test_check_calls_cc_evaluate_with_expected_args(self):
        with mock.patch.object(pc.cc, "evaluate", wraps=pc.cc.evaluate) as spy:
            pc.run_check(
                title="[MAR-72] Fix thing",
                body=conforming_body(),
                require_label="ACS",
                pr_title_format="[{ticket_id}] {title}",
                sections=DEFAULT_SECTIONS,
                ticket_prefix="MAR",
            )
        spy.assert_called_once()
        args, kwargs = spy.call_args
        settings, ctx, mode = args
        self.assertEqual(mode, "pr")
        self.assertEqual(settings["ticket_prefix"], "MAR")
        self.assertEqual(settings["formats"]["pr_title"], "[{ticket_id}] {title}")
        self.assertFalse(settings["enforcement"]["checks"]["branch_name"])
        self.assertFalse(settings["enforcement"]["checks"]["commit_message"])
        self.assertEqual(settings["enforcement"]["pr_description_sections"], DEFAULT_SECTIONS)
        self.assertEqual(ctx["title"], "[MAR-72] Fix thing")
        self.assertEqual(ctx["labels"], ["ACS"])


class TestMain(unittest.TestCase):
    """Drive main() end-to-end (argparse plumbing, stdout/exit-code contract)."""

    def _run_main(self, argv):
        import io
        import sys
        real_argv = sys.argv[:]
        real_stdout = sys.stdout
        sys.argv = ["pr-conventions.py"] + argv
        sys.stdout = io.StringIO()
        try:
            try:
                pc.main()
                code = 0
            except SystemExit as exc:
                code = exc.code if exc.code is not None else 0
            out = sys.stdout.getvalue()
        finally:
            sys.argv = real_argv
            sys.stdout = real_stdout
        return code, out

    def test_main_render_title(self):
        code, out = self._run_main([
            "render-title",
            "--template", "[{ticket_id}] {title}",
            "--ticket-id", "MAR-72",
            "--title", "Fix thing",
        ])
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "[MAR-72] Fix thing")

    def test_main_check_pass(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as fh:
            fh.write(conforming_body())
            body_path = fh.name
        try:
            code, out = self._run_main([
                "check",
                "--title", "[MAR-72] Fix thing",
                "--body-file", body_path,
                "--require-label", "ACS",
                "--pr-title-format", "[{ticket_id}] {title}",
                "--sections", "Summary,Ticket,Changes,Test plan",
                "--ticket-prefix", "MAR",
            ])
        finally:
            os.unlink(body_path)
        self.assertEqual(code, 0)
        self.assertIn('"passed": true', out)

    def test_main_check_fail_exits_nonzero(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as fh:
            fh.write("no sections here")
            body_path = fh.name
        try:
            code, out = self._run_main([
                "check",
                "--title", "Fix thing",
                "--body-file", body_path,
                "--require-label", "ACS",
                "--pr-title-format", "[{ticket_id}] {title}",
                "--sections", "Summary,Ticket,Changes,Test plan",
                "--ticket-prefix", "MAR",
            ])
        finally:
            os.unlink(body_path)
        self.assertEqual(code, 1)
        self.assertIn('"passed": false', out)

    def test_main_usage_error_missing_required_arg(self):
        import contextlib
        import io as io_
        with contextlib.redirect_stderr(io_.StringIO()):
            code, _out = self._run_main(["render-title"])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
