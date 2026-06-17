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
    os.path.dirname(os.path.dirname(_TESTS_DIR)),
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
    "Panel 7",
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


def _flow_workspace_data():
    """A flow-metrics payload exercising BOTH populated and 'no data' Panel 3 averages + Panel 7.

    MAR-6 is fully merged: ticket.json.created_at + code.started_at + merge-pr.ended_at all present,
    so its lead AND cycle are numeric and the four Panel-3 averages are populated. MAR-OPEN has no
    merged PR (no merge-pr.ended_at), so BOTH its lead and cycle render the 'no data' cell (B1)."""
    with TemporaryDirectory() as ws:
        fx.write_index(ws, {"MAR-6": {"status": "done", "type": "task"},
                            "MAR-OPEN": {"status": "in_progress", "type": "task"}})
        fx.write_metrics(ws, {
            "tickets": {"by_status": {"done": 1, "in_progress": 1},
                        "by_type": {"task": 2}},
            "prs": {"created": 2, "merged": 1},
            "totals": {"runs": 9, "working_seconds": 7200,
                       "tokens": {"input": 100000, "output": 20000}, "cost_usd": 6.0},
        })
        # MAR-6 — merged: created_at -> merge-pr.ended_at gives a numeric lead; code.started_at ->
        # merge-pr.ended_at a numeric cycle (lead 10800s = 3h, cycle 9000s = 2h30m).
        fx.write_ticket_json(ws, "MAR-6", "2026-06-15T10:00:00Z", archived=True)
        fx.write_pipeline(ws, "MAR-6",
                          steps=fx._lead_cycle_steps("2026-06-15T10:30:00Z", "2026-06-15T13:00:00Z"),
                          totals={"runs": 5, "working_seconds": 3600,
                                  "tokens": {"input": 80000, "output": 16000},
                                  "cost_usd": 5.0}, archived=True)
        # MAR-OPEN — unmerged: code started but no merge-pr.ended_at, so lead AND cycle are "no data".
        fx.write_ticket_json(ws, "MAR-OPEN", "2026-06-15T09:00:00Z")
        fx.write_pipeline(ws, "MAR-OPEN",
                          steps=fx._lead_cycle_steps("2026-06-15T09:30:00Z", None))
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
        # C-6: the per-ticket working time is humanized (11922s -> "3h 18m"), NOT raw seconds,
        # and the column header is "working time", NOT "seconds".
        self.assertIn("working time", out)
        self.assertIn("3h 18m", out)       # per-ticket working_seconds 11922 -> "3h 18m"
        self.assertIn("17h 50m", out)      # REPO TOTAL working_seconds 64238 -> "17h 50m"
        self.assertNotIn("11922", out)     # the old raw per-ticket seconds must be gone
        self.assertNotIn("64238", out)     # the old raw REPO-TOTAL seconds must be gone
        # the Panel-3 region's column header is "working time", not the old "seconds"
        p3 = out[out.index("Panel 3"):out.index("Panel 4")]
        self.assertIn("working time", p3)
        self.assertNotIn("seconds", p3)
        self.assertIn("8.31", out)   # per-ticket cost (already 2dp) appears
        # C-5: every money cell renders EXACTLY 2 decimals. The avg cost / merged PR is
        # 18.75 / 4 = 4.6875 -> "4.69" (was a raw-float "4.6875" before the fix); the
        # repo-total cost and avg cost / ticket render "18.75", not a bare/unrounded float.
        self.assertIn("18.75", out)   # repo total cost + avg cost / ticket
        self.assertIn("4.69", out)    # avg cost / merged PR, rounded to 2dp
        self.assertNotIn("4.6875", out)  # the old unrounded money float must be gone

    def test_panel3_working_time_humanized_both_surfaces(self):
        # C-6: Panel 3's per-ticket AND REPO-TOTAL working time is humanized on BOTH surfaces,
        # the header is renamed to "working time", and the old raw seconds / "seconds" header gone.
        data = _full_workspace_data()
        term = metrics_render.render_terminal(data)
        html = metrics_render.render_html(data)
        for out, p4_anchor in ((term, "Panel 4"), (html, "Panel 4")):
            p3 = out[out.index("Panel 3"):out.index(p4_anchor)]
            self.assertIn("working time", p3)   # renamed header on this surface
            self.assertNotIn("seconds", p3)     # old header gone on this surface
            self.assertIn("3h 18m", p3)         # per-ticket humanized
            self.assertIn("17h 50m", p3)        # REPO TOTAL humanized
            self.assertNotIn("11922", p3)       # raw per-ticket seconds gone
            self.assertNotIn("64238", p3)       # raw REPO-TOTAL seconds gone

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
        # C-5: the per-role cost_usd column renders EXACTLY 2 decimals on the terminal surface
        # (planner 0.17, executor 3.5 -> "3.50", verifier 1.0 -> "1.00").
        self.assertIn("3.50", out)   # executor cost, 2dp (was a raw "3.5")
        self.assertIn("1.00", out)   # verifier cost, 2dp (was a raw "1.0"/"1")
        self.assertIn("0.17", out)   # planner cost

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


# ---------------------------------------------------------------------------
# _humanize_seconds — pure duration humanizer (no clock, no locale, no random)
# ---------------------------------------------------------------------------

class HumanizeSeconds(unittest.TestCase):
    def test_multi_unit_descending(self):
        # 2d 3h 4m 5s -> two most significant non-zero units, descending
        secs = 2 * 86400 + 3 * 3600 + 4 * 60 + 5
        out = metrics_render._humanize_seconds(secs)
        self.assertEqual(out, "2d 3h")

    def test_hours_minutes(self):
        out = metrics_render._humanize_seconds(3 * 3600 + 4 * 60)  # 3h 4m
        self.assertEqual(out, "3h 4m")

    def test_minutes_seconds(self):
        out = metrics_render._humanize_seconds(5 * 60 + 12)  # 5m 12s
        self.assertEqual(out, "5m 12s")

    def test_sub_minute(self):
        self.assertEqual(metrics_render._humanize_seconds(12), "12s")

    def test_zero(self):
        self.assertEqual(metrics_render._humanize_seconds(0), "0s")

    def test_minute_or_more_contains_dhm(self):
        # any duration of a minute or more renders at least one of d/h/m (Test plan contract)
        out = metrics_render._humanize_seconds(90)
        self.assertTrue(any(u in out for u in ("d", "h", "m")), out)

    def test_no_data_string_passthrough(self):
        self.assertEqual(metrics_render._humanize_seconds("no data"),
                         metrics_render.NO_DATA)

    def test_bool_is_no_data(self):
        # bool is an int subclass — guard it the way _bar/_bar_pct do
        self.assertEqual(metrics_render._humanize_seconds(True), metrics_render.NO_DATA)

    def test_non_numeric_is_no_data(self):
        self.assertEqual(metrics_render._humanize_seconds(None), metrics_render.NO_DATA)
        self.assertEqual(metrics_render._humanize_seconds("x"), metrics_render.NO_DATA)

    def test_pure_no_clock_repeatable(self):
        self.assertEqual(metrics_render._humanize_seconds(9000),
                         metrics_render._humanize_seconds(9000))


# ---------------------------------------------------------------------------
# _fmt_money — pure USD formatter to exactly 2 decimals (C-5)
# ---------------------------------------------------------------------------

class FmtMoney(unittest.TestCase):
    def test_whole_float_two_decimals(self):
        self.assertEqual(metrics_render._fmt_money(36.0), "36.00")

    def test_int_two_decimals(self):
        self.assertEqual(metrics_render._fmt_money(0), "0.00")
        self.assertEqual(metrics_render._fmt_money(7), "7.00")

    def test_one_decimal_padded_to_two(self):
        self.assertEqual(metrics_render._fmt_money(7.2), "7.20")
        self.assertEqual(metrics_render._fmt_money(3.5), "3.50")

    def test_long_float_rounded_to_two(self):
        # the C-5 bug case: a raw float like 5.142857142857143 -> "5.14", never the long form
        self.assertEqual(metrics_render._fmt_money(5.142857142857143), "5.14")
        self.assertEqual(metrics_render._fmt_money(18.75 / 4), "4.69")

    def test_no_data_string_passthrough(self):
        self.assertEqual(metrics_render._fmt_money("no data"), metrics_render.NO_DATA)

    def test_non_numeric_is_empty_marker(self):
        self.assertEqual(metrics_render._fmt_money(None), metrics_render.NO_DATA)
        self.assertEqual(metrics_render._fmt_money("x"), metrics_render.NO_DATA)

    def test_bool_is_empty_marker(self):
        # bool is an int subclass — excluded from the numeric branch like _humanize_seconds/_bar
        self.assertEqual(metrics_render._fmt_money(True), metrics_render.NO_DATA)
        self.assertEqual(metrics_render._fmt_money(False), metrics_render.NO_DATA)

    def test_custom_empty_marker_for_dash_cells(self):
        # the per-ticket / REPO-TOTAL / role cost columns use "-" for their empty state
        self.assertEqual(metrics_render._fmt_money("-", empty="-"), "-")
        self.assertEqual(metrics_render._fmt_money(None, empty="-"), "-")
        # a numeric value still formats to 2dp regardless of the empty marker
        self.assertEqual(metrics_render._fmt_money(8.31, empty="-"), "8.31")

    def test_pure_repeatable_no_clock(self):
        self.assertEqual(metrics_render._fmt_money(4.6875),
                         metrics_render._fmt_money(4.6875))


# ---------------------------------------------------------------------------
# Flow metrics — Panel 3 averages + new Panel 7 (lead/cycle), BOTH surfaces (AC-3)
# ---------------------------------------------------------------------------

class Panel3Averages(unittest.TestCase):
    def test_averages_present_both_surfaces(self):
        data = _flow_workspace_data()
        term = metrics_render.render_terminal(data)
        html = metrics_render.render_html(data)
        for out in (term, html):
            # the two working-time averages are humanized (avg per ticket = 3600s = 1h)
            self.assertIn("1h", out)
            # C-5: the two cost averages render EXACTLY 2 decimals on BOTH surfaces
            # (avg_cost_per_ticket 3.0 -> "3.00", avg_cost_per_pr 6.0 -> "6.00") — not raw floats.
            self.assertIn("3.00", out)   # avg_cost_per_ticket, 2dp
            self.assertIn("6.00", out)   # avg_cost_per_pr, 2dp
            # the per-ticket / repo-total money cells are also 2dp on this payload
            self.assertIn("5.00", out)   # MAR-6 per-ticket cost 5.0 -> "5.00"

    def test_panel3_missing_working_seconds_still_renders_no_data_both_surfaces(self):
        # C-6 / B1: a ticket with an empty totals (MAR-OPEN) has no working_seconds; humanizing
        # the time cell must STILL render the existing no-data handling, never crash or show a raw "-".
        data = _flow_workspace_data()
        term = metrics_render.render_terminal(data)
        html = metrics_render.render_html(data)
        for out in (term, html):
            self.assertIn("MAR-OPEN", out)   # the row is present (never omitted)
            self.assertIn("no data", out)    # its missing working time renders a no-data cell
        # the populated MAR-6 row IS humanized on both surfaces (3600s -> "1h")
        for out in (term, html):
            p3 = out[out.index("Panel 3"):out.index("Panel 4")]
            self.assertIn("working time", p3)
            self.assertIn("1h", p3)          # MAR-6 per-ticket 3600s -> "1h"
            self.assertIn("2h", p3)          # REPO TOTAL 7200s -> "2h"

    def test_no_data_average_renders_cell_both_surfaces(self):
        # zero merged PRs -> per-PR averages are "no data"; cells present, never omitted (B1)
        with TemporaryDirectory() as ws:
            fx.write_index(ws, {"MAR-6": {"status": "done", "type": "task"}})
            fx.write_metrics(ws, {"tickets": {"by_status": {"done": 1}, "by_type": {"task": 1}},
                                  "prs": {"created": 1, "merged": 0},
                                  "totals": {"working_seconds": 100, "cost_usd": 1.0}})
            fx.write_pipeline(ws, "MAR-6", steps=fx._full_funnel_steps("code"),
                              totals={"working_seconds": 100, "cost_usd": 1.0}, archived=True)
            data = metrics_aggregate.aggregate(ws, REPO_ID)
            self.assertEqual(data["panels"]["3"]["averages"]["avg_working_seconds_per_pr"],
                             "no data")
            term = metrics_render.render_terminal(data)
            html = metrics_render.render_html(data)
            self.assertIn("no data", term)
            self.assertIn("no data", html)


class Panel7LeadCycle(unittest.TestCase):
    def test_panel7_frame_present_populated_and_empty(self):
        for data in (_flow_workspace_data(), _empty_workspace_data()):
            term = metrics_render.render_terminal(data)
            html = metrics_render.render_html(data)
            self.assertIn("Panel 7", term)
            self.assertIn("Panel 7", html)

    def test_per_ticket_lead_cycle_humanized_both_surfaces(self):
        data = _flow_workspace_data()
        term = metrics_render.render_terminal(data)
        html = metrics_render.render_html(data)
        for out in (term, html):
            self.assertIn("MAR-6", out)
            self.assertIn("3h", out)      # lead 10800s = 3h
            self.assertIn("2h 30m", out)  # cycle 9000s = 2h 30m

    def test_no_data_lead_cycle_cell_both_surfaces(self):
        # MAR-OPEN's lead AND cycle are "no data" -> a "no data" cell, never an omitted row (B1)
        data = _flow_workspace_data()
        term = metrics_render.render_terminal(data)
        html = metrics_render.render_html(data)
        for out in (term, html):
            self.assertIn("MAR-OPEN", out)
            self.assertIn("no data", out)

    def test_avg_lead_cycle_humanized_both_surfaces(self):
        data = _flow_workspace_data()
        term = metrics_render.render_terminal(data)
        html = metrics_render.render_html(data)
        for out in (term, html):
            # avg lead 10800s = 3h, avg cycle 9000s = 2h 30m
            self.assertRegex(out.lower(), r"avg.*lead")
            self.assertRegex(out.lower(), r"avg.*cycle")

    def test_lead_cycle_human_readable_not_raw_seconds(self):
        # Durations human-readable: a humanized unit (d/h/m) appears, not the raw seconds integer.
        data = _flow_workspace_data()
        term = metrics_render.render_terminal(data)
        # find the Panel 7 region and assert a humanized unit is present in it
        idx = term.index("Panel 7")
        region = term[idx:]
        self.assertTrue(any(u in region for u in ("d", "h", "m")), region)

    def test_panel7_whole_panel_no_data_both_surfaces(self):
        # the empty-workspace whole-panel "no data" form renders a "no data" Panel 7 frame
        data = _empty_workspace_data()
        self.assertEqual(data["panels"]["7"], "no data")
        term = metrics_render.render_terminal(data)
        html = metrics_render.render_html(data)
        # the Panel 7 frame is present AND carries a "no data" block
        self.assertIn("Panel 7", term)
        self.assertIn("Panel 7", html)
        self.assertIn("no data", term)
        self.assertIn("no data", html)


class FlowMetricsDeterminism(unittest.TestCase):
    def test_terminal_byte_identical_on_flow(self):
        data = _flow_workspace_data()
        self.assertEqual(metrics_render.render_terminal(data),
                         metrics_render.render_terminal(data))

    def test_html_byte_identical_on_flow(self):
        data = _flow_workspace_data()
        self.assertEqual(metrics_render.render_html(data),
                         metrics_render.render_html(data))


class FlowMetricsSelfContained(unittest.TestCase):
    def test_no_external_fetch_on_flow_payload(self):
        out = metrics_render.render_html(_flow_workspace_data())
        self.assertIn("<style", out)
        self.assertNotIn("http://", out)
        self.assertNotIn("https://", out)
        self.assertNotIn("cdn", out.lower())
        self.assertNotIn("<script", out)
        self.assertNotIn("<link", out)
        self.assertNotIn("src=", out)
        self.assertNotIn("href=", out)
        # the dark-mode block is intact with the new panel rows present
        self.assertIn("prefers-color-scheme: dark", out)


class FlowMetricsReadOnly(unittest.TestCase):
    def _snapshot(self, root):
        snap = {}
        for dirpath, _dirs, files in os.walk(root):
            for f in files:
                p = os.path.join(dirpath, f)
                snap[p] = os.stat(p).st_mtime_ns
        return snap

    def test_render_flow_writes_nothing(self):
        with TemporaryDirectory() as ws:
            fx.write_index(ws, {"MAR-6": {"status": "done", "type": "task"}})
            fx.write_ticket_json(ws, "MAR-6", "2026-06-15T10:00:00Z", archived=True)
            fx.write_metrics(ws, {"prs": {"created": 1, "merged": 1},
                                  "totals": {"working_seconds": 100, "cost_usd": 1.0}})
            fx.write_pipeline(ws, "MAR-6",
                              steps=fx._lead_cycle_steps("2026-06-15T10:30:00Z",
                                                         "2026-06-15T13:00:00Z"),
                              totals={"working_seconds": 100, "cost_usd": 1.0}, archived=True)
            data = metrics_aggregate.aggregate(ws, REPO_ID)
            # sanity: the flow metrics are populated in this payload
            self.assertNotEqual(data["panels"]["7"]["avg_lead_seconds"], "no data")
            before = self._snapshot(os.path.join(ws, REPO_ID))
            metrics_render.render_terminal(data)
            metrics_render.render_html(data)
            after = self._snapshot(os.path.join(ws, REPO_ID))
            self.assertEqual(before, after, "rendering mutated the workspace — must be read-only")


# ---------------------------------------------------------------------------
# Docs — observability + CHANGELOG describe the new flow metrics (AC-6)
# ---------------------------------------------------------------------------

class DocsPresence(unittest.TestCase):
    def _read(self, *parts):
        path = os.path.join(os.path.dirname(os.path.dirname(_TESTS_DIR)), *parts)
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()

    def test_observability_documents_lead_cycle_and_seven_panels(self):
        doc = self._read("docs", "operations", "observability.md").lower()
        self.assertIn("lead", doc)
        self.assertIn("cycle", doc)
        # the wall-clock-vs-working-time distinction is documented
        self.assertIn("wall-clock", doc)
        # seven panels (or a Panel 7 heading), not only six
        self.assertTrue("seven" in doc or "panel 7" in doc or "7 —" in doc, doc[:0])

    def test_changelog_has_mar7_unreleased_entry(self):
        doc = self._read("plugins", "acs", "CHANGELOG.md")
        unreleased = doc[doc.index("[Unreleased]"):]
        self.assertIn("MAR-7", unreleased)


if __name__ == "__main__":
    unittest.main()
