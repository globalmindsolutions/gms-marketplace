"""Unit tests for the convention checker that /acs:init ships into consumer repos.

The checker (plugins/acs/templates/ci/check-conventions.py) runs in the
consumer's CI and as a local pre-push hook with ZERO acs dependencies — only the
Python stdlib — so these tests load it straight from the template path and drive
its pure `evaluate()` core plus the format->regex compiler.

Run:  python3 -m unittest discover -s tests -v
"""

import importlib.util
import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHECKER = os.path.join(REPO_ROOT, "plugins", "acs", "templates", "ci", "check-conventions.py")

_spec = importlib.util.spec_from_file_location("acs_check_conventions", CHECKER)
cc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cc)


def settings(**overrides):
    base = {"ticket_prefix": "MAR", "formats": {}}
    base.update(overrides)
    return base


def ctx(branch="task/MAR-12-add-foo", title="[MAR-12] Add foo",
        body=None, labels=None, commits=None):
    if body is None:
        body = "## Summary\nx\n## Ticket\nx\n## Changes\nx\n## Test plan\nx\n"
    return {
        "branch": branch,
        "title": title,
        "body": body,
        "labels": ["ACS"] if labels is None else labels,
        "commit_subjects": ["MAR-12 add foo"] if commits is None else commits,
    }


def headings(*names):
    return "".join("## %s\n\nbody\n\n" % n for n in names)


class FormatToRegexTests(unittest.TestCase):
    def test_branch_default(self):
        rx = cc.format_to_regex("{type}/{ticket_id}-{slug}", "MAR")
        self.assertTrue(rx.match("task/MAR-12-add-bulk-import"))
        self.assertTrue(rx.match("epic/MAR-1-x"))
        self.assertFalse(rx.match("claude/foo"))
        self.assertFalse(rx.match("task/MAR-12"))          # missing slug
        self.assertFalse(rx.match("task/SHOP-12-x"))       # wrong prefix
        self.assertFalse(rx.match("wip/MAR-12-x"))         # wrong type
        self.assertFalse(rx.match("task/MAR-12-Add_Foo"))  # slug not lower-kebab

    def test_title_default(self):
        rx = cc.format_to_regex("[{ticket_id}] {title}", "MAR")
        self.assertTrue(rx.match("[MAR-3] Product definition (PRD)"))
        self.assertFalse(rx.match("MAR-3 Product definition"))   # no brackets
        self.assertFalse(rx.match("[MAR-3] "))                   # empty title
        self.assertFalse(rx.match("docs: relocate runbook"))

    def test_commit_default(self):
        rx = cc.format_to_regex("{ticket_id} {summary}", "MAR")
        self.assertTrue(rx.match("MAR-7 fix the thing"))
        self.assertFalse(rx.match("fix the thing"))

    def test_custom_prefix_is_escaped(self):
        rx = cc.format_to_regex("[{ticket_id}] {title}", "A.B")
        self.assertTrue(rx.match("[A.B-9] hi"))
        self.assertFalse(rx.match("[AxB-9] hi"))  # '.' is literal, not any-char


class EvaluatePrTests(unittest.TestCase):
    def assertPasses(self, res):
        self.assertEqual(res.errors, [], "unexpected errors: %s" % res.errors)
        self.assertIsNone(res.exempt)

    def assertFails(self, res, heading):
        self.assertIn(heading, [h for h, _ in res.errors],
                      "expected a %r error, got %s" % (heading, res.errors))

    def test_conforming_pr_passes(self):
        self.assertPasses(cc.evaluate(settings(), ctx(), "pr"))

    def test_bad_branch_fails(self):
        self.assertFails(cc.evaluate(settings(), ctx(branch="claude/foo"), "pr"), "branch_name")

    def test_bad_title_fails(self):
        self.assertFails(cc.evaluate(settings(), ctx(title="Add foo"), "pr"), "pr_title")

    def test_missing_acs_label_fails(self):
        self.assertFails(cc.evaluate(settings(), ctx(labels=[]), "pr"), "acs_label")

    def test_missing_description_section_fails(self):
        res = cc.evaluate(settings(), ctx(body=headings("Summary", "Ticket")), "pr")
        self.assertFails(res, "pr_description")

    def test_description_headings_case_insensitive(self):
        body = headings("summary", "TICKET", "Changes") + "### Test plan\n\nok\n"
        self.assertPasses(cc.evaluate(settings(), ctx(body=body), "pr"))

    def test_commit_check_off_by_default(self):
        # commit_message defaults OFF -> a bad commit subject is ignored.
        self.assertPasses(cc.evaluate(settings(), ctx(commits=["wip"]), "pr"))

    def test_commit_check_when_enabled(self):
        s = settings(enforcement={"checks": {"commit_message": True}})
        self.assertFails(cc.evaluate(s, ctx(commits=["wip"]), "pr"), "commit_message")
        self.assertPasses(cc.evaluate(s, ctx(commits=["MAR-12 real subject"]), "pr"))

    def test_merge_commits_ignored_when_commit_check_on(self):
        s = settings(enforcement={"checks": {"commit_message": True}})
        commits = ["Merge branch 'main' into x", "MAR-12 real work"]
        self.assertPasses(cc.evaluate(s, ctx(commits=commits), "pr"))


class ExemptionTests(unittest.TestCase):
    def test_exempt_label_skips_everything(self):
        res = cc.evaluate(settings(), ctx(branch="whatever", title="nope",
                                          labels=["acs-exempt"], commits=["wip"]), "pr")
        self.assertIsNotNone(res.exempt)
        self.assertEqual(res.errors, [])

    def test_exempt_branch_glob_skips(self):
        res = cc.evaluate(settings(), ctx(branch="release/v1.2.0", title="nope", labels=[]), "pr")
        self.assertIsNotNone(res.exempt)
        self.assertEqual(res.errors, [])

    def test_custom_exempt_config(self):
        s = settings(enforcement={"exempt_branches": ["hotfix/*"], "exempt_label": "skip-acs"})
        self.assertIsNotNone(cc.evaluate(s, ctx(branch="hotfix/x", labels=[]), "pr").exempt)
        self.assertIsNotNone(cc.evaluate(s, ctx(branch="b", labels=["skip-acs"]), "pr").exempt)
        # the built-in release/* no longer applies once overridden
        self.assertIsNone(cc.evaluate(s, ctx(branch="release/x", labels=[],
                                             title="bad", commits=[]), "pr").exempt)


class FailClosedTests(unittest.TestCase):
    def test_no_settings_fails_closed(self):
        res = cc.evaluate({}, ctx(), "pr")
        self.assertFails_settings(res)

    def test_prefix_without_formats_fails_closed(self):
        res = cc.evaluate({"ticket_prefix": "MAR"}, ctx(), "pr")
        self.assertFails_settings(res)

    def assertFails_settings(self, res):
        self.assertIn("settings", [h for h, _ in res.errors])


class PrePushModeTests(unittest.TestCase):
    def test_prepush_checks_branch_only_by_default(self):
        # bad title/body/labels are ignored in pre-push; branch is fine -> passes
        res = cc.evaluate(settings(), ctx(branch="task/MAR-12-x", title="bad",
                                          body="", labels=[]), "pre-push")
        self.assertEqual(res.errors, [])

    def test_prepush_flags_bad_branch(self):
        res = cc.evaluate(settings(), ctx(branch="wip", title="bad"), "pre-push")
        self.assertIn("branch_name", [h for h, _ in res.errors])

    def test_prepush_runs_commit_check_when_enabled(self):
        s = settings(enforcement={"checks": {"commit_message": True}})
        res = cc.evaluate(s, ctx(branch="task/MAR-12-x", commits=["nope"]), "pre-push")
        self.assertIn("commit_message", [h for h, _ in res.errors])


class DisabledChecksTests(unittest.TestCase):
    def test_disabling_a_check_skips_it(self):
        s = settings(enforcement={"checks": {"pr_title": False, "acs_label": False}})
        res = cc.evaluate(s, ctx(title="totally wrong", labels=[]), "pr")
        self.assertEqual(res.errors, [])
        self.assertIn("pr_title", res.skipped)
        self.assertIn("acs_label", res.skipped)


class CommitMsgModeTests(unittest.TestCase):
    """The commit-msg hook checks only the commit subject, against the configured
    formats.commit_message — never the branch/title/label (unknown at commit)."""

    def test_commit_check_off_by_default_passes(self):
        res = cc.evaluate(settings(), ctx(commits=["wip"]), "commit-msg")
        self.assertEqual(res.errors, [])

    def test_bad_subject_fails_when_enabled(self):
        s = settings(enforcement={"checks": {"commit_message": True}})
        self.assertIn("commit_message",
                      [h for h, _ in cc.evaluate(s, ctx(commits=["wip"]), "commit-msg").errors])

    def test_good_subject_passes_when_enabled(self):
        s = settings(enforcement={"checks": {"commit_message": True}})
        self.assertEqual(cc.evaluate(s, ctx(commits=["MAR-9 do the thing"]), "commit-msg").errors, [])

    def test_uses_configured_commit_format(self):
        # A repo that configured a different commit_message format is honoured.
        s = settings(formats={"commit_message": "{type}: {summary}"},
                     enforcement={"checks": {"commit_message": True}})
        self.assertEqual(cc.evaluate(s, ctx(commits=["task: ship it"]), "commit-msg").errors, [])
        self.assertIn("commit_message",
                      [h for h, _ in cc.evaluate(s, ctx(commits=["MAR-9 nope"]), "commit-msg").errors])

    def test_does_not_check_branch_or_title(self):
        s = settings(enforcement={"checks": {"commit_message": True, "branch_name": True}})
        res = cc.evaluate(s, ctx(branch="garbage", title="garbage",
                                 commits=["MAR-9 ok"]), "commit-msg")
        self.assertEqual(res.errors, [])  # branch_name not in commit-msg mode

    def test_merge_subject_ignored(self):
        s = settings(enforcement={"checks": {"commit_message": True}})
        self.assertEqual(cc.evaluate(s, ctx(commits=["Merge branch 'main'"]), "commit-msg").errors, [])

    def test_exempt_branch_skips(self):
        s = settings(enforcement={"checks": {"commit_message": True}})
        res = cc.evaluate(s, ctx(branch="release/v1", commits=["wip"]), "commit-msg")
        self.assertIsNotNone(res.exempt)
        self.assertEqual(res.errors, [])


class ReadCommitSubjectTests(unittest.TestCase):
    def test_skips_comments_and_blanks(self):
        import tempfile, os
        fd, path = tempfile.mkstemp()
        os.close(fd)
        self.addCleanup(os.unlink, path)
        with open(path, "w") as fh:
            fh.write("\n# a comment\nMAR-9 real subject\n# more\nbody line\n")
        self.assertEqual(cc._read_commit_subject(path), "MAR-9 real subject")


if __name__ == "__main__":
    unittest.main()
