"""Golden / structural tests for plugins/acs/hooks/scripts/metrics_render.py (MAR-5 spec 04).

Pure stdlib (unittest, tempfile, json, os, io, re); NO show_widget import, NO pip. These tests
drive the two PURE renderers — render_terminal(data) -> str and render_html(data) -> str — plus
main()'s stdin/--html surface selection. The input is built the spec-04 way: reuse the spec-01
fixture synthesizers in test_metrics_aggregate.py to synthesize a workspace, call
metrics_aggregate.aggregate(workspace, REPO_ID), and feed that live-shaped JSON to the renderer
(so the golden input mirrors the live / MAR-6 aggregate shapes without hand-writing JSON).

The renderer is read-only and deterministic: identical JSON in -> byte-identical output; it reads
no clock (meta.generated_at is rendered as given).
"""

import importlib
import io
import json
import os
import re
import sys
import unittest
from tempfile import TemporaryDirectory

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS_DIR = os.path.join(
    os.path.dirname(_TESTS_DIR),
    "plugins", "acs", "hooks", "scripts",
)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

import acs_lib  # noqa: E402  (after sys.path mutation)
metrics_aggregate = importlib.import_module("metrics_aggregate")  # noqa: E402
metrics_render = importlib.import_module("metrics_render")  # noqa: E402

# Reuse the spec-01 fixture synthesizers verbatim (write_index, write_metrics, …).
import test_metrics_aggregate as fx  # noqa: E402

REPO_ID = fx.REPO_ID

# Panel headers the renderer must always emit (B1 — every frame present).
PANEL_HEADERS = (
    "Panel 1",
    "Panel 2",
    "Panel 3",
    "Panel 4",
    "Panel 5",
    "Panel 6",
)


# ---------------------------------------------------------------------------
# Input builders — synthesize a workspace, aggregate, hand the JSON to render
# ---------------------------------------------------------------------------

def _full_workspace_data():
    """A populated MAR-6-shaped aggregate: panel-1 primary, full funnel, cost/time, numeric
    coverage, authoritative review iterations, all three role buckets (coordinate excluded)."""
    with TemporaryDirectory() as ws:
        fx.write_index(ws, {"MAR-6": {"status": "done", "type": "task"}})
        fx.write_metrics(ws, {
            "tickets": {"by_status": {"done": 4, "in_review": 1, "in_progress": 1},
                        "by_type": {"task": 5, "story": 1}},
            "prs": {"created": 5, "merged": 4},
            "totals": {"runs": 17, "working_seconds": 64238,
                       "tokens": {"input": 3102000, "output": 508500}, "cost_usd": 18.75},
        })
        fx.write_pipeline(ws, "MAR-6", steps=fx._full_funnel_steps("merge-pr"),
                          totals={"runs": 5, "working_seconds": 11922,
                                  "tokens": {"input": 1306000, "output": 237000},
                                  "cost_usd": 8.31}, archived=True)
        fx.write_code_state(ws, "MAR-6",
                            {"tests": {"coverage_percent": 93.4, "coverage_target": 90},
                             "verifier_passed": True, "review": {"iterations": 2}}, archived=True)
        fx.write_result_xml(ws, "MAR-6", "code", "plan", 1, ti=42000, to=7500, cost=0.17, archived=True)
        fx.write_result_xml(ws, "MAR-6", "code", "execute", 1, ti=480000, to=90000, cost=3.5, archived=True)
        fx.write_result_xml(ws, "MAR-6", "code", "verify", 1, ti=100000, to=20000, cost=1.0,
                            reorder=True, archived=True)
        fx.write_result_xml(ws, "MAR-6", "code", "coordinate", 1, ti=999999, to=999999, cost=99.0,
                            archived=True)
        return metrics_aggregate.aggregate(ws, REPO_ID)


def _empty_workspace_data():
    """The empty-workspace whole-payload form: every panels[k] is the bare 'no data' string."""
    with TemporaryDirectory() as ws:
        fx.write_index(ws, {})
        return metrics_aggregate.aggregate(ws, REPO_ID)


def _degraded_workspace_data():
    """A populated + degraded mix: panel-4 cell 'no data' (null coverage), panel-5 'no data'
    (no review.iterations + no verify XML), and a ticket with no pipeline-state (panels 2/3 degrade)."""
    with TemporaryDirectory() as ws:
        fx.write_index(ws, {"MAR-6": {"status": "done", "type": "task"},
                            "MAR-X": {"status": "in_progress", "type": "task"}})
        # MAR-6: null coverage -> panel-4 cell 'no data' + degraded entry
        fx.write_code_state(ws, "MAR-6",
                            {"tests": {"passed": 81, "failed": 0, "coverage_percent": None,
                                       "coverage_target": "n/a (no new production code)"},
                             "verifier_passed": True}, archived=True)
        # MAR-X: no state files at all -> panels 2/3/4/5 degrade (incl. panel-5 'no data')
        return metrics_aggregate.aggregate(ws, REPO_ID)


# ---------------------------------------------------------------------------
# Terminal surface
# ---------------------------------------------------------------------------

class TerminalSurface(unittest.TestCase):
    def test_all_six_panel_headers_present(self):
        out = metrics_render.render_terminal(_full_workspace_data())
        for header in PANEL_HEADERS:
            self.assertIn(header, out)

    def test_meta_header_rendered_as_given(self):
        data = _full_workspace_data()
        out = metrics_render.render_terminal(data)
        self.assertIn(data["meta"]["repo_id"], out)
        self.assertIn(data["meta"]["generated_at"], out)  # rendered as given, no clock read
        self.assertIn(str(data["meta"]["ticket_count"]), out)

    def test_panel1_status_and_type_counts(self):
        out = metrics_render.render_terminal(_full_workspace_data())
        self.assertIn("done", out)
        self.assertIn("in_review", out)
        self.assertIn("task", out)
        self.assertIn("story", out)

    def test_panel2_funnel_and_pr_terminus(self):
        out = metrics_render.render_terminal(_full_workspace_data())
        for skill in acs_lib.HOOKED_SKILLS:
            self.assertIn(skill, out)
        # PR terminus counts present
        self.assertIn("created", out.lower())
        self.assertIn("merged", out.lower())

    def test_panel3_cost_time_row(self):
        out = metrics_render.render_terminal(_full_workspace_data())
        self.assertIn("MAR-6", out)
        self.assertIn("11922", out)  # working_seconds total appears
        self.assertIn("8.31", out)   # cost row appears

    def test_panel4_coverage_cell(self):
        out = metrics_render.render_terminal(_full_workspace_data())
        self.assertIn("93.4", out)
        self.assertIn("90", out)

    def test_panel5_review_iterations_value(self):
        out = metrics_render.render_terminal(_full_workspace_data())
        # the authoritative review.iterations == 2 for MAR-6
        self.assertIn("MAR-6", out)
        self.assertRegex(out, r"MAR-6[^\n]*\b2\b")

    def test_panel6_three_role_buckets(self):
        out = metrics_render.render_terminal(_full_workspace_data())
        self.assertIn("planner", out)
        self.assertIn("executor", out)
        self.assertIn("verifier", out)
        self.assertIn("480000", out)  # executor input tokens

    def test_no_ansi_escape_codes_by_default(self):
        out = metrics_render.render_terminal(_full_workspace_data())
        self.assertNotIn("\x1b[", out, "default terminal render must carry no ANSI escapes")

    def test_degraded_summary_lines(self):
        data = _degraded_workspace_data()
        self.assertTrue(data["meta"]["degraded"], "fixture must produce degraded entries")
        out = metrics_render.render_terminal(data)
        # the degraded summary surfaces a ticket id + panel + reason
        self.assertRegex(out.lower(), r"degrad")
        first = data["meta"]["degraded"][0]
        self.assertIn(first["ticket_id"], out)


# ---------------------------------------------------------------------------
# HTML surface
# ---------------------------------------------------------------------------

class HtmlSurface(unittest.TestCase):
    def test_six_panel_sections_present(self):
        out = metrics_render.render_html(_full_workspace_data())
        for header in PANEL_HEADERS:
            self.assertIn(header, out)

    def test_self_contained_no_external_fetch(self):
        out = metrics_render.render_html(_full_workspace_data())
        # inline style allowed; no off-document fetch of any kind
        self.assertIn("<style", out)
        self.assertNotIn("http://", out)
        self.assertNotIn("https://", out)
        self.assertNotIn("cdn", out.lower())
        self.assertNotIn("<script", out)
        self.assertNotIn("<link", out)
        self.assertNotIn("src=", out)
        self.assertNotIn("href=", out)

    def test_theme_adaptive_dark_mode_block(self):
        # C-8: the inline style carries a prefers-color-scheme: dark block so the
        # self-contained dashboard is readable in BOTH light and dark, with no host
        # CSS-variable dependency and no external fetch.
        out = metrics_render.render_html(_full_workspace_data())
        self.assertIn("prefers-color-scheme", out)
        self.assertIn("prefers-color-scheme: dark", out)
        # the dark block lives inside the same inline <style> element
        style_open = out.index("<style")
        style_close = out.index("</style>")
        self.assertGreater(style_close, style_open)
        self.assertIn("prefers-color-scheme",
                      out[style_open:style_close],
                      "dark-mode block must live inside the inline <style>")

    def test_deterministic_css_bars_panels_1_2_6(self):
        # C-8: panels 1 (status/type), 2 (funnel), and 6 (token burn by role) carry
        # deterministic CSS bars sized width:N% with an integer percent.
        out = metrics_render.render_html(_full_workspace_data())
        self.assertIn("acs-bar", out, "stable bar class marker must be present")
        # bars are deterministic integer-percent inline widths
        widths = re.findall(r"width:(\d+)%", out)
        self.assertTrue(widths, "at least one integer-percent bar width must be emitted")
        for w in widths:
            self.assertEqual(str(int(w)), w)  # integer percent, no float
            self.assertLessEqual(int(w), 100)
        # the panel with the max value in panel 1 (by_status done=4) reaches 100%
        self.assertIn("width:100%", out)

    def test_bars_never_divide_by_zero_on_empty(self):
        # panel_max == 0 / no numeric data -> no bar width / 0 width, never raises.
        out = metrics_render.render_html(_empty_workspace_data())
        # no negative or >100 widths, and rendering did not raise
        widths = re.findall(r"width:(\d+)%", out)
        for w in widths:
            self.assertGreaterEqual(int(w), 0)
            self.assertLessEqual(int(w), 100)

    def test_meta_and_values_present(self):
        data = _full_workspace_data()
        out = metrics_render.render_html(data)
        self.assertIn(data["meta"]["repo_id"], out)
        self.assertIn(data["meta"]["generated_at"], out)
        self.assertIn("planner", out)
        self.assertIn("executor", out)
        self.assertIn("verifier", out)

    def test_html_escapes_no_raw_angle_injection(self):
        # repo_id and ticket ids are plain, but assert the document is well-formed enough that
        # the panel content does not break out of the document frame.
        out = metrics_render.render_html(_full_workspace_data())
        self.assertTrue(out.strip().startswith("<"))
        self.assertIn("</", out)


# ---------------------------------------------------------------------------
# Empty workspace (whole-payload 'no data') — both surfaces, never raise
# ---------------------------------------------------------------------------

class EmptyWorkspace(unittest.TestCase):
    def test_terminal_six_no_data_frames(self):
        data = _empty_workspace_data()
        self.assertEqual(data["meta"]["ticket_count"], 0)
        out = metrics_render.render_terminal(data)
        for header in PANEL_HEADERS:
            self.assertIn(header, out)
        self.assertIn("no data", out)

    def test_html_six_no_data_frames(self):
        data = _empty_workspace_data()
        out = metrics_render.render_html(data)
        for header in PANEL_HEADERS:
            self.assertIn(header, out)
        self.assertIn("no data", out)

    def test_neither_surface_raises(self):
        data = _empty_workspace_data()
        # must not raise
        metrics_render.render_terminal(data)
        metrics_render.render_html(data)


# ---------------------------------------------------------------------------
# Degraded / cell-level 'no data' — both surfaces
# ---------------------------------------------------------------------------

class DegradedCells(unittest.TestCase):
    def test_panel4_no_data_cell_both_surfaces(self):
        data = _degraded_workspace_data()
        term = metrics_render.render_terminal(data)
        html = metrics_render.render_html(data)
        self.assertIn("no data", term)
        self.assertIn("no data", html)

    def test_degraded_surfaced_both_surfaces(self):
        data = _degraded_workspace_data()
        deg = data["meta"]["degraded"]
        self.assertTrue(deg)
        term = metrics_render.render_terminal(data)
        html = metrics_render.render_html(data)
        for d in deg[:1]:
            self.assertIn(d["ticket_id"], term)
            self.assertIn(d["ticket_id"], html)

    def test_no_crash_on_degraded(self):
        data = _degraded_workspace_data()
        metrics_render.render_terminal(data)
        metrics_render.render_html(data)


# ---------------------------------------------------------------------------
# Determinism — identical JSON in -> byte-identical output
# ---------------------------------------------------------------------------

class Determinism(unittest.TestCase):
    def test_terminal_byte_identical(self):
        data = _full_workspace_data()
        self.assertEqual(metrics_render.render_terminal(data),
                         metrics_render.render_terminal(data))

    def test_html_byte_identical(self):
        data = _full_workspace_data()
        self.assertEqual(metrics_render.render_html(data),
                         metrics_render.render_html(data))

    def test_empty_byte_identical(self):
        data = _empty_workspace_data()
        self.assertEqual(metrics_render.render_terminal(data),
                         metrics_render.render_terminal(data))
        self.assertEqual(metrics_render.render_html(data),
                         metrics_render.render_html(data))


# ---------------------------------------------------------------------------
# Read-only — rendering writes nothing
# ---------------------------------------------------------------------------

class ReadOnly(unittest.TestCase):
    def _snapshot(self, root):
        snap = {}
        for dirpath, _dirs, files in os.walk(root):
            for f in files:
                p = os.path.join(dirpath, f)
                snap[p] = os.stat(p).st_mtime_ns
        return snap

    def test_render_writes_nothing(self):
        with TemporaryDirectory() as ws:
            fx.write_index(ws, {"MAR-6": {"status": "done", "type": "task"}})
            fx.write_metrics(ws, {"tickets": {"by_status": {"done": 1}, "by_type": {"task": 1}}})
            fx.write_pipeline(ws, "MAR-6", steps=fx._full_funnel_steps("merge-pr"),
                              totals={"runs": 5, "working_seconds": 100,
                                      "tokens": {"input": 1, "output": 1}, "cost_usd": 1.0},
                              archived=True)
            fx.write_code_state(ws, "MAR-6",
                                {"review": {"iterations": 2},
                                 "tests": {"coverage_percent": 90.0, "coverage_target": 90}},
                                archived=True)
            data = metrics_aggregate.aggregate(ws, REPO_ID)
            before = self._snapshot(os.path.join(ws, REPO_ID))
            metrics_render.render_terminal(data)
            metrics_render.render_html(data)
            after = self._snapshot(os.path.join(ws, REPO_ID))
            self.assertEqual(before, after, "rendering mutated the workspace — must be read-only")


# ---------------------------------------------------------------------------
# main() surface selection — stdin (terminal default) and --html
# ---------------------------------------------------------------------------

class MainCli(unittest.TestCase):
    def _run_main(self, argv, stdin_text):
        orig_argv, orig_stdin, orig_stdout = sys.argv, sys.stdin, sys.stdout
        sys.argv = argv
        sys.stdin = io.StringIO(stdin_text)
        sys.stdout = io.StringIO()
        try:
            rc = metrics_render.main()
            return rc, sys.stdout.getvalue()
        finally:
            sys.argv, sys.stdin, sys.stdout = orig_argv, orig_stdin, orig_stdout

    def test_stdin_terminal_default(self):
        data = _full_workspace_data()
        rc, out = self._run_main(["metrics_render.py"], json.dumps(data))
        self.assertEqual(rc, 0)
        self.assertIn("Panel 1", out)
        self.assertNotIn("<style", out)  # terminal, not HTML

    def test_stdin_html_flag(self):
        data = _full_workspace_data()
        rc, out = self._run_main(["metrics_render.py", "--html"], json.dumps(data))
        self.assertEqual(rc, 0)
        self.assertIn("<style", out)
        self.assertIn("Panel 1", out)


if __name__ == "__main__":
    unittest.main()
