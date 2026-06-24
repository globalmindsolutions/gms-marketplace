"""Regression guard for MAR-43: the acs-conventions workflow must not cancel its
own required status check.

Both copies of the workflow (the template `/acs:init` installs, and this repo's
live copy) declare a per-PR concurrency group. With `cancel-in-progress: true`,
the `opened` + `labeled` events that fire together on `gh pr create --label ACS`
produced two runs in the same group; the cancelled one left a non-SUCCESS
conclusion on the required "Branch / PR / commit conventions" check for the head
SHA, which branch protection treats as unmet and BLOCKS the PR (observed as PR
#96). The fix is `cancel-in-progress: false` in both files, with the per-PR
group retained and an explanatory comment.

Run: python3 -m unittest discover -s tests -v
"""

import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

WORKFLOW_PATHS = [
    os.path.join(REPO_ROOT, "plugins", "acs", "templates", "ci", "acs-conventions.yml"),
    os.path.join(REPO_ROOT, ".github", "workflows", "acs-conventions.yml"),
]

PER_PR_GROUP = "group: acs-conventions-${{ github.event.pull_request.number }}"
RATIONALE_PHRASE = "leaves a non-SUCCESS conclusion"


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


class TestAcsConventionsConcurrency(unittest.TestCase):
    def test_cancel_in_progress_disabled(self):
        """(a) cancel-in-progress is false, not true, in both files. [AC-1, AC-2]"""
        for path in WORKFLOW_PATHS:
            with self.subTest(path=path):
                content = _read(path)
                self.assertIn(
                    "cancel-in-progress: false", content,
                    f"{path}: cancel-in-progress must be false",
                )
                self.assertNotIn(
                    "cancel-in-progress: true", content,
                    f"{path}: cancel-in-progress: true must be removed",
                )

    def test_per_pr_group_retained(self):
        """(b) the per-PR concurrency group string is retained. [AC-4]"""
        for path in WORKFLOW_PATHS:
            with self.subTest(path=path):
                content = _read(path)
                self.assertIn(
                    PER_PR_GROUP, content,
                    f"{path}: per-PR concurrency group must be retained",
                )

    def test_explanatory_comment_present(self):
        """(c) the concurrency comment states why cancellation is disabled. [AC-3]"""
        for path in WORKFLOW_PATHS:
            with self.subTest(path=path):
                content = _read(path)
                self.assertIn(
                    RATIONALE_PHRASE, content,
                    f"{path}: comment must explain why cancellation is disabled "
                    f"(contains {RATIONALE_PHRASE!r})",
                )

    def test_template_and_live_copy_identical(self):
        """(d) the template and the live workflow stay byte-identical."""
        template, live = (_read(p) for p in WORKFLOW_PATHS)
        self.assertEqual(
            template, live,
            "the acs-conventions template and the live .github/workflows copy "
            "must be byte-identical",
        )


if __name__ == "__main__":
    unittest.main()
