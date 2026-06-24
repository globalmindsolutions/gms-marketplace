"""Mermaid diagram validation.

Two layers:
  1. Unit tests for the heuristic linter (`mermaid_lint`) — it flags the syntax
     errors that have actually shipped broken and passes valid diagrams.
  2. A repo-wide guard: every ```mermaid block in every tracked Markdown file
     must lint clean. This runs in CI via `unittest discover -s tests`, so a
     regression in the architecture/design docs (or the templates) fails the
     build.

Why heuristic and not a real Mermaid parse: a full parse needs Node + the
mermaid package, which this Python/$0 CI deliberately avoids. The linter targets
the deterministic GitHub-renderer breakers (semicolons in sequence diagrams,
space-separated erDiagram keys, unknown diagram types). The authoring rules in
the executor/verifier agent prompts cover the rest at generation time.
"""

import contextlib
import io
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mermaid_lint  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".claude"}


def _markdown_files(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if name.endswith(".md"):
                yield os.path.join(dirpath, name)


class TestMermaidLinter(unittest.TestCase):
    """Unit tests for the linter rules themselves."""

    def test_clean_sequence_diagram_passes(self):
        text = (
            "```mermaid\n"
            "sequenceDiagram\n"
            "    actor Dev as Developer (after review)\n"
            "    Dev->>CO: merge (squash), then delete branch\n"
            "    Note over Dev: all good\n"
            "```\n"
        )
        self.assertEqual(mermaid_lint.lint_text(text), [])

    def test_semicolon_in_sequence_message_is_flagged(self):
        text = (
            "```mermaid\n"
            "sequenceDiagram\n"
            "    Dev->>CO: merge (squash); delete branch\n"
            "```\n"
        )
        findings = mermaid_lint.lint_text(text)
        self.assertEqual([f.rule for f in findings], ["sequence-semicolon"])

    def test_space_separated_er_keys_flagged(self):
        text = (
            "```mermaid\n"
            "erDiagram\n"
            "    DECISION_RECORD {\n"
            "        string run_id FK PK\n"
            "    }\n"
            "```\n"
        )
        findings = mermaid_lint.lint_text(text)
        self.assertEqual([f.rule for f in findings], ["er-key-space"])

    def test_comma_separated_er_keys_pass(self):
        text = (
            "```mermaid\n"
            "erDiagram\n"
            "    DECISION_RECORD {\n"
            "        string run_id PK,FK\n"
            "    }\n"
            "```\n"
        )
        self.assertEqual(mermaid_lint.lint_text(text), [])

    def test_pk_fk_inside_er_comment_not_flagged(self):
        text = (
            "```mermaid\n"
            "erDiagram\n"
            "    R {\n"
            '        string id PK "joins PK FK tables"\n'
            "    }\n"
            "```\n"
        )
        self.assertEqual(mermaid_lint.lint_text(text), [])

    def test_unknown_diagram_type_flagged(self):
        text = "```mermaid\nsequenceDigram\n    A->>B: hi\n```\n"  # typo
        findings = mermaid_lint.lint_text(text)
        self.assertEqual([f.rule for f in findings], ["unknown-diagram-type"])

    def test_semicolon_outside_sequence_is_allowed(self):
        # Semicolons are only a problem inside sequenceDiagram; a flowchart edge
        # label or erDiagram relationship comment may legitimately contain one.
        text = (
            "```mermaid\n"
            "flowchart TD\n"
            '    A -->|"step 1; step 2"| B\n'
            "```\n"
        )
        self.assertEqual(mermaid_lint.lint_text(text), [])

    def test_line_numbers_are_absolute(self):
        text = "intro\n\n```mermaid\nsequenceDiagram\n    A->>B: x;y\n```\n"
        findings = mermaid_lint.lint_text(text)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].line, 5)

    def test_unterminated_fence_still_linted(self):
        # A ```mermaid block with no closing ``` still emits findings
        # (covers the unterminated-fence branch in extract_blocks, line 91).
        text = "```mermaid\nsequenceDiagram\n    A->>B: bad;semicolon\n"
        findings = mermaid_lint.lint_text(text)
        self.assertEqual([f.rule for f in findings], ["sequence-semicolon"])

    def test_empty_block_finding(self):
        # A ```mermaid block with no content (no lines at all) produces an
        # empty-block finding (covers lines 119-121).
        text = "```mermaid\n```\n"
        findings = mermaid_lint.lint_text(text)
        self.assertEqual([f.rule for f in findings], ["empty-block"])

    def test_comment_only_block_is_empty_block(self):
        # A block whose only lines are %% comments is treated as empty
        # (covers _first_meaningful returning None, lines 100/102).
        text = "```mermaid\n%% this is a comment\n%% another comment\n```\n"
        findings = mermaid_lint.lint_text(text)
        self.assertEqual([f.rule for f in findings], ["empty-block"])


class TestMermaidLintCLI(unittest.TestCase):
    """Tests for the main(argv) CLI entry point."""

    def _run_main(self, argv):
        """Call mermaid_lint.main(argv) and return (exit_code, stderr_text)."""
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            code = mermaid_lint.main(argv)
        return code, buf.getvalue()

    def test_main_no_args_exits_2(self):
        # main(argv) with no file arguments prints usage and returns 2
        # (covers lines 159-162).
        code, err = self._run_main(["mermaid_lint.py"])
        self.assertEqual(code, 2)
        self.assertIn("usage", err.lower())

    def test_main_clean_md_file_exits_0(self):
        # main(argv) with a lint-clean .md file returns 0 (covers lines
        # 163-176 happy path).
        content = (
            "# Heading\n\n"
            "```mermaid\n"
            "sequenceDiagram\n"
            "    A->>B: hello\n"
            "```\n"
        )
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w",
                                         encoding="utf-8", delete=False) as f:
            f.write(content)
            path = f.name
        try:
            code, _ = self._run_main(["mermaid_lint.py", path])
            self.assertEqual(code, 0)
        finally:
            os.unlink(path)

    def test_main_broken_md_file_exits_1_and_prints_finding(self):
        # main(argv) with a broken .md file returns 1 and prints the finding
        # to stderr (covers lines 172-176 findings path).
        content = (
            "```mermaid\n"
            "sequenceDiagram\n"
            "    A->>B: step1; step2\n"
            "```\n"
        )
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w",
                                         encoding="utf-8", delete=False) as f:
            f.write(content)
            path = f.name
        try:
            code, err = self._run_main(["mermaid_lint.py", path])
            self.assertEqual(code, 1)
            self.assertIn("sequence-semicolon", err)
        finally:
            os.unlink(path)

    def test_main_non_md_path_is_skipped(self):
        # main(argv) skips non-.md paths; if all are skipped it exits 0
        # (covers the `if not path.endswith(".md"): continue` guard, line 165).
        code, _ = self._run_main(["mermaid_lint.py", "/tmp/not_a_diagram.txt"])
        self.assertEqual(code, 0)

    def test_main_missing_file_exits_2(self):
        # main(argv) with an unreadable/missing .md path prints an error and
        # returns 2 (covers the OSError branch, lines 169-171).
        code, err = self._run_main(
            ["mermaid_lint.py", "/tmp/does_not_exist_MAR46.md"]
        )
        self.assertEqual(code, 2)
        self.assertIn("error", err.lower())


class TestRepoDiagramsLintClean(unittest.TestCase):
    """Every ```mermaid block in the repo's Markdown must lint clean."""

    def test_all_repo_markdown_lints_clean(self):
        findings = []
        for path in _markdown_files(REPO_ROOT):
            findings.extend(mermaid_lint.lint_file(path))
        if findings:
            rel = [
                "%s:%d [%s] %s"
                % (os.path.relpath(f.source, REPO_ROOT), f.line, f.rule, f.message)
                for f in findings
            ]
            self.fail(
                "%d broken Mermaid diagram(s):\n  %s"
                % (len(findings), "\n  ".join(rel))
            )


if __name__ == "__main__":
    unittest.main()
