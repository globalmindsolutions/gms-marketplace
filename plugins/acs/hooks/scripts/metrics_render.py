#!/usr/bin/env python3
"""metrics_render.py — deterministic cross-surface renderer for the /acs:metrics dashboard (MAR-5).

Stdlib-only (Python 3.9+, no pip; NEVER imports show_widget). Consumes the spec-01 aggregate JSON
({panels:{"1".."7"}, meta:{generated_at, repo_id, ticket_count, degraded}}) emitted by
metrics_aggregate.py and renders the SAME seven panels for TWO surfaces:

    render_terminal(data) -> str   deterministic Unicode block-bar terminal dashboard (CLI default)
    render_html(data)     -> str   ONE self-contained HTML string (Desktop/claude.ai; handed to
                                   show_widget verbatim) — inline CSS only, NO external fetch.

Plus a thin main() that reads the aggregate JSON from stdin (json.load) — or self-invokes
metrics_aggregate.aggregate via acs_lib.build_context when stdin is empty — picks the surface
(terminal by default, HTML on --html), prints it to stdout, and returns 0.

This is the C-7 deterministic cross-surface renderer that SUPERSEDES the model-improvised
Markdown fallback (former ledger C-4). The aggregate-JSON contract (spec 01 / A1) is UNCHANGED —
no field added, no key renamed; the panel value shapes are exactly those metrics_aggregate emits.

Invariants (AC-8):
  * B1 — every panel key "1".."7" is ALWAYS rendered as a framed section; a bare "no data" panel
    draws a "no data" frame and a cell-level {"cell"/"iterations": "no data"} draws a "no data"
    cell — never an omitted frame.
  * Determinism — identical JSON in -> byte-identical output. The renderer reads NO clock and
    generates NO random value; meta.generated_at is rendered EXACTLY as given (it is the
    aggregator that stamps it). Every dict is iterated in a fixed, reproducible order.
  * Read-only — zero writes (no file, no state, no schema/config). The only effects of main() are
    reading stdin and printing to stdout.
  * Never crash — a panel value is sometimes a dict and sometimes the bare string "no data"; the
    renderer renders a "no data" frame for either form on both surfaces and never raises (the
    never-crash discipline of statusline.py).

ANSI color is OFF by default (determinism forbids surface-dependent escapes in the golden output).
"""

import html as _html
import json
import os
import sys

# Reuse acs_lib (shared scripts dir) the same way the other hooks/scripts do.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import acs_lib  # noqa: E402

PANEL_KEYS = ("1", "2", "3", "4", "5", "6", "7")

# Canonical, fixed iteration orders (determinism — never rely on dict insertion order).
ROLE_ORDER = ("planner", "executor", "verifier")

PANEL_TITLES = {
    "1": "Panel 1 — Throughput by status / type",
    "2": "Panel 2 — Pipeline funnel",
    "3": "Panel 3 — Cost + time per ticket by step",
    "4": "Panel 4 — Coverage achieved vs target",
    "5": "Panel 5 — Review iterations before pass",
    "6": "Panel 6 — Token burn by role",
    "7": "Panel 7 — Lead + cycle time per ticket",
}

# Fixed-key order for the Panel 3 averages summary rows (determinism — read by name, not by
# dict iteration). The aggregate (spec 01) emits exactly these four keys.
AVERAGE_ROWS = (
    ("avg working time / ticket", "avg_working_seconds_per_ticket", "duration"),
    ("avg working time / merged PR", "avg_working_seconds_per_pr", "duration"),
    ("avg cost / ticket", "avg_cost_per_ticket", "cost"),
    ("avg cost / merged PR", "avg_cost_per_pr", "cost"),
)

NO_DATA = "no data"

# Unicode block glyphs for the deterministic block-bar (statusline.py's deterministic-glyph style).
_BAR_FULL = "█"   # █
_BAR_EMPTY = "·"  # ·
_BAR_WIDTH = 24        # fixed bar width so output is deterministic regardless of value magnitude


# ---------------------------------------------------------------------------
# Shared helpers (pure; no I/O, no clock)
# ---------------------------------------------------------------------------

def _is_no_data(value):
    """A panel/cell value that means 'no data' (the bare string, the whole-panel empty form)."""
    return value == NO_DATA


def _bar(value, peak):
    """A fixed-width Unicode block bar for `value` relative to `peak` (peak<=0 -> empty bar)."""
    if not isinstance(value, (int, float)) or isinstance(value, bool) or peak <= 0:
        filled = 0
    else:
        filled = int(round((value / peak) * _BAR_WIDTH))
        filled = max(0, min(_BAR_WIDTH, filled))
    return _BAR_FULL * filled + _BAR_EMPTY * (_BAR_WIDTH - filled)


def _humanize_seconds(value):
    """Format a seconds count as a human-readable duration, or NO_DATA for any non-number.

    Pure function of its argument only — NO clock, NO locale, NO random (determinism / R4).
    A numeric value renders the two most significant non-zero units in descending order
    (d/h/m/s), e.g. "2d 3h", "3h 4m", "5m 12s", "12s", "0s". bool (an int subclass) and any
    non-numeric value (including the literal NO_DATA string) return NO_DATA — this is what makes
    the "no data" cell appear (B1). Mirrors the bool guard in _bar/_bar_pct.
    """
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return NO_DATA
    total = int(value)
    sign = "-" if total < 0 else ""
    total = abs(total)
    units = (("d", 86400), ("h", 3600), ("m", 60), ("s", 1))
    parts = []
    remaining = total
    for label, size in units:
        count = remaining // size
        remaining -= count * size
        if count or (label == "s" and not parts):
            parts.append("%d%s" % (count, label))
    # Two most significant units; "0s" for an all-zero duration (parts is then just ["0s"]).
    return sign + " ".join(parts[:2])


def _fmt_money(value, empty=NO_DATA):
    """Format a USD cost cell to EXACTLY 2 decimals, or the cell's empty marker for any non-number.

    Pure function of its arguments only — NO clock, NO locale, NO random (determinism / R4).
    A numeric value renders "%.2f" (e.g. 36.0 -> "36.00", 5.142857... -> "5.14", 7.2 -> "7.20").
    bool (an int subclass) and any non-numeric value (the literal NO_DATA string, a missing-cell
    default, None) return `empty` — the marker the calling cell uses for its empty state (NO_DATA
    for the average cells, "-" for the per-ticket / REPO-TOTAL / role cost columns), so the cell's
    existing empty handling and B1 ("no data" cells still render) are preserved. Mirrors the bool
    guard in _humanize_seconds.
    """
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return empty
    return "%.2f" % value


def _meta_lines(meta):
    """The header lines drawn from meta (rendered as given — generated_at is data, no clock read)."""
    meta = meta if isinstance(meta, dict) else {}
    return [
        "repo: %s" % meta.get("repo_id", ""),
        "generated_at: %s" % meta.get("generated_at", ""),
        "tickets: %s" % meta.get("ticket_count", 0),
    ]


def _counts_items(mapping):
    """Sorted (label, count) pairs from a {label: int} mapping — fixed order for determinism."""
    if not isinstance(mapping, dict):
        return []
    return sorted(((str(k), v) for k, v in mapping.items()), key=lambda kv: kv[0])


# ---------------------------------------------------------------------------
# Terminal surface (default) — deterministic Unicode, no ANSI, no color
# ---------------------------------------------------------------------------

def render_terminal(data):
    """Deterministic Unicode block-bar dashboard for ALL SEVEN panels (CLI default). Never raises."""
    data = data if isinstance(data, dict) else {}
    panels = data.get("panels") if isinstance(data.get("panels"), dict) else {}
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}

    lines = []
    lines.append("=" * 60)
    lines.append("/acs:metrics dashboard")
    for ml in _meta_lines(meta):
        lines.append("  " + ml)
    lines.append("=" * 60)

    for key in PANEL_KEYS:
        lines.append("")
        lines.append(PANEL_TITLES[key])
        lines.append("-" * 60)
        value = panels.get(key, NO_DATA)
        renderer = _TERMINAL_PANELS[key]
        lines.extend(renderer(value))

    lines.append("")
    lines.extend(_terminal_degraded(meta.get("degraded")))
    return "\n".join(lines) + "\n"


def _term_no_data_block():
    return ["  " + NO_DATA]


def _term_panel1(value):
    if _is_no_data(value) or not isinstance(value, dict):
        return _term_no_data_block()
    out = ["  by status:"]
    status_items = _counts_items(value.get("by_status"))
    type_items = _counts_items(value.get("by_type"))
    peak = max([c for _, c in status_items + type_items if isinstance(c, (int, float))] or [0])
    if not status_items:
        out.append("    " + NO_DATA)
    for label, count in status_items:
        out.append("    %-14s %s %s" % (label, _bar(count, peak), count))
    out.append("  by type:")
    if not type_items:
        out.append("    " + NO_DATA)
    for label, count in type_items:
        out.append("    %-14s %s %s" % (label, _bar(count, peak), count))
    return out


def _term_panel2(value):
    if _is_no_data(value) or not isinstance(value, dict):
        return _term_no_data_block()
    steps = value.get("steps") if isinstance(value.get("steps"), dict) else {}
    out = ["  funnel (tickets reaching each step):"]
    # Fixed order: the canonical HOOKED_SKILLS order.
    counts = [steps.get(skill, 0) for skill in acs_lib.HOOKED_SKILLS]
    peak = max([c for c in counts if isinstance(c, (int, float))] or [0])
    for skill in acs_lib.HOOKED_SKILLS:
        count = steps.get(skill, 0)
        out.append("    %-14s %s %s" % (skill, _bar(count, peak), count))
    prs = value.get("prs") if isinstance(value.get("prs"), dict) else {}
    out.append("  PRs:  created %s   merged %s"
               % (prs.get("created", 0), prs.get("merged", 0)))
    return out


def _format_average(value, kind):
    """Format a Panel-3 average cell: duration averages humanized, cost averages numeric.

    A "no data" (or any non-numeric) value renders the NO_DATA cell for either kind (B1).
    """
    if _is_no_data(value):
        return NO_DATA
    if kind == "duration":
        return _humanize_seconds(value)
    # kind == "cost": money to exactly 2 decimals; non-numeric -> NO_DATA cell (B1).
    return _fmt_money(value, empty=NO_DATA)


def _average_cells(value):
    """The (label, formatted_value) pairs for Panel 3's four averages (fixed order, B1).

    A missing or non-dict `averages` renders four NO_DATA cells — never an omitted row.
    """
    averages = value.get("averages") if isinstance(value, dict) else None
    averages = averages if isinstance(averages, dict) else {}
    out = []
    for label, key, kind in AVERAGE_ROWS:
        out.append((label, _format_average(averages.get(key, NO_DATA), kind)))
    return out


def _term_panel3(value):
    if _is_no_data(value) or not isinstance(value, dict):
        return _term_no_data_block()
    rows = value.get("tickets") if isinstance(value.get("tickets"), list) else []
    out = ["  %-12s %12s %12s" % ("ticket", "seconds", "cost_usd")]
    if not rows:
        out.append("  " + NO_DATA)
    for row in rows:
        if not isinstance(row, dict):
            continue
        totals = row.get("totals") if isinstance(row.get("totals"), dict) else {}
        seconds = totals.get("working_seconds", "-")
        cost = _fmt_money(totals.get("cost_usd", "-"), empty="-")
        out.append("  %-12s %12s %12s" % (str(row.get("ticket_id", "?")), seconds, cost))
    repo_totals = value.get("repo_totals") if isinstance(value.get("repo_totals"), dict) else {}
    if repo_totals:
        out.append("  %-12s %12s %12s"
                   % ("REPO TOTAL", repo_totals.get("working_seconds", "-"),
                      _fmt_money(repo_totals.get("cost_usd", "-"), empty="-")))
    # Four averages summary rows after REPO TOTAL (B1 — each value present, "no data" when absent).
    for label, formatted in _average_cells(value):
        out.append("  %-30s %12s" % (label, formatted))
    return out


def _term_panel4(value):
    if _is_no_data(value) or not isinstance(value, dict):
        return _term_no_data_block()
    rows = value.get("tickets") if isinstance(value.get("tickets"), list) else []
    out = ["  %-12s %10s %10s %8s" % ("ticket", "achieved", "target", "passed")]
    if not rows:
        out.append("  " + NO_DATA)
    for row in rows:
        if not isinstance(row, dict):
            continue
        tid = str(row.get("ticket_id", "?"))
        if row.get("cell") == NO_DATA or "achieved" not in row:
            out.append("  %-12s %10s" % (tid, NO_DATA))
            continue
        out.append("  %-12s %10s %10s %8s"
                   % (tid, row.get("achieved"), row.get("target"),
                      "yes" if row.get("passed") else "no"))
    return out


def _term_panel5(value):
    if _is_no_data(value) or not isinstance(value, dict):
        return _term_no_data_block()
    rows = value.get("tickets") if isinstance(value.get("tickets"), list) else []
    out = ["  %-12s %12s" % ("ticket", "iterations")]
    if not rows:
        out.append("  " + NO_DATA)
    for row in rows:
        if not isinstance(row, dict):
            continue
        out.append("  %-12s %12s"
                   % (str(row.get("ticket_id", "?")), row.get("iterations", NO_DATA)))
    return out


def _term_panel6(value):
    if _is_no_data(value) or not isinstance(value, dict):
        return _term_no_data_block()
    out = ["  %-10s %12s %12s %10s" % ("role", "input", "output", "cost_usd")]
    inputs = []
    for role in ROLE_ORDER:
        bucket = value.get(role) if isinstance(value.get(role), dict) else {}
        if isinstance(bucket.get("input"), (int, float)):
            inputs.append(bucket.get("input"))
    peak = max(inputs or [0])
    for role in ROLE_ORDER:
        bucket = value.get(role) if isinstance(value.get(role), dict) else {}
        inp = bucket.get("input", 0)
        out.append("  %-10s %12s %12s %10s   %s"
                   % (role, inp, bucket.get("output", 0),
                      _fmt_money(bucket.get("cost", 0), empty="-"), _bar(inp, peak)))
    return out


def _term_panel7(value):
    if _is_no_data(value) or not isinstance(value, dict):
        return _term_no_data_block()
    rows = value.get("tickets") if isinstance(value.get("tickets"), list) else []
    out = ["  %-12s %12s %12s" % ("ticket", "lead", "cycle")]
    if not rows:
        out.append("  " + NO_DATA)
    for row in rows:
        if not isinstance(row, dict):
            continue
        out.append("  %-12s %12s %12s"
                   % (str(row.get("ticket_id", "?")),
                      _humanize_seconds(row.get("lead_seconds", NO_DATA)),
                      _humanize_seconds(row.get("cycle_seconds", NO_DATA))))
    # Two average summary rows (B1 — humanized, or a "no data" cell when there is no value).
    out.append("  %-30s %12s" % ("avg lead", _humanize_seconds(value.get("avg_lead_seconds", NO_DATA))))
    out.append("  %-30s %12s" % ("avg cycle", _humanize_seconds(value.get("avg_cycle_seconds", NO_DATA))))
    return out


_TERMINAL_PANELS = {
    "1": _term_panel1,
    "2": _term_panel2,
    "3": _term_panel3,
    "4": _term_panel4,
    "5": _term_panel5,
    "6": _term_panel6,
    "7": _term_panel7,
}


def _terminal_degraded(degraded):
    out = ["Degraded (panels that fell back to 'no data'):", "-" * 60]
    if not isinstance(degraded, list) or not degraded:
        out.append("  none — all panels had data")
        return out
    for entry in degraded:
        if not isinstance(entry, dict):
            continue
        out.append("  %s  panel %s  %s"
                   % (entry.get("ticket_id", "?"), entry.get("panel", "?"),
                      entry.get("reason", "")))
    return out


# ---------------------------------------------------------------------------
# HTML surface (--html) — ONE self-contained string, inline CSS, NO external fetch
# ---------------------------------------------------------------------------

# Self-contained, theme-adaptive inline style (C-8). Default colors are LIGHT; an
# @media (prefers-color-scheme: dark) block inside the SAME <style> element overrides
# text/surfaces/borders/bars to dark-appropriate tones so the standalone dashboard is
# readable in BOTH light and dark — no host CSS-variable dependency, no external fetch.
# .acs-bar is a deterministic CSS bar: a fixed-width track holding a fill whose
# width:N% is computed (integer percent) from the panel data by _bar_pct.
_HTML_STYLE = (
    "<style>"
    # --- light defaults ---
    ".acs-metrics{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:13px;"
    "line-height:1.4;color:#1a1a1a}"
    ".acs-metrics h2{font-size:15px;margin:0 0 4px}"
    ".acs-metrics .panel{border:1px solid #ccc;border-radius:6px;padding:10px 12px;margin:8px 0}"
    ".acs-metrics .panel h3{font-size:13px;margin:0 0 6px}"
    ".acs-metrics table{border-collapse:collapse;width:100%}"
    ".acs-metrics th,.acs-metrics td{text-align:left;padding:2px 8px 2px 0;"
    "border-bottom:1px solid #eee}"
    ".acs-metrics .meta{color:#555;font-size:12px}"
    ".acs-metrics .nodata{color:#999;font-style:italic}"
    ".acs-metrics .acs-bar-track{display:inline-block;width:120px;height:9px;"
    "background:#e9edf2;border-radius:3px;overflow:hidden;vertical-align:middle}"
    ".acs-metrics .acs-bar{display:block;height:9px;background:#3b6ea5;border-radius:3px}"
    # --- dark overrides (same <style>, no host variable) ---
    "@media (prefers-color-scheme: dark){"
    ".acs-metrics{color:#e6e6e6}"
    ".acs-metrics .panel{border-color:#3a3f46}"
    ".acs-metrics th,.acs-metrics td{border-bottom-color:#2b2f35}"
    ".acs-metrics .meta{color:#a8b0ba}"
    ".acs-metrics .nodata{color:#7c828b}"
    ".acs-metrics .acs-bar-track{background:#2b2f35}"
    ".acs-metrics .acs-bar{background:#5a93d6}"
    "}"
    "</style>"
)


def _esc(value):
    """HTML-escape any scalar to text (quotes too) — defends the document frame."""
    return _html.escape(str(value), quote=True)


def _bar_pct(value, panel_max):
    """Deterministic integer bar percent: round(value / panel_max * 100), clamped 0..100.

    panel_max <= 0 (or a non-numeric / bool value) yields 0 — never divides by zero.
    """
    if (not isinstance(value, (int, float)) or isinstance(value, bool)
            or not isinstance(panel_max, (int, float)) or isinstance(panel_max, bool)
            or panel_max <= 0):
        return 0
    pct = int(round((value / panel_max) * 100))
    return max(0, min(100, pct))


def _html_bar_cell(value, panel_max):
    """A theme-adaptive CSS bar cell sized width:N% (integer percent) for `value`.

    Rendered as a fixed-width track holding a deterministic fill; panel_max <= 0
    (or a non-numeric value) renders a 0-width fill rather than dividing by zero.
    """
    pct = _bar_pct(value, panel_max)
    return ('<td><span class="acs-bar-track">'
            '<span class="acs-bar" style="width:%d%%"></span></span></td>') % pct


def _panel_max(values):
    """The max numeric value in `values` (bools/non-numerics ignored); 0 when none."""
    nums = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    return max(nums) if nums else 0


def render_html(data):
    """ONE self-contained HTML string rendering the SAME seven panels. Inline CSS, no fetch. Never raises."""
    data = data if isinstance(data, dict) else {}
    panels = data.get("panels") if isinstance(data.get("panels"), dict) else {}
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}

    parts = ['<div class="acs-metrics">']
    parts.append(_HTML_STYLE)
    parts.append("<h2>/acs:metrics dashboard</h2>")
    parts.append('<div class="meta">')
    parts.append(" &middot; ".join(_esc(ml) for ml in _meta_lines(meta)))
    parts.append("</div>")

    for key in PANEL_KEYS:
        value = panels.get(key, NO_DATA)
        parts.append('<div class="panel">')
        parts.append("<h3>%s</h3>" % _esc(PANEL_TITLES[key]))
        parts.append(_HTML_PANELS[key](value))
        parts.append("</div>")

    parts.append(_html_degraded(meta.get("degraded")))
    parts.append("</div>")
    return "".join(parts)


def _html_no_data():
    return '<div class="nodata">%s</div>' % NO_DATA


def _html_counts_table(caption, items, panel_max):
    """A counts table with a deterministic theme-adaptive bar column (width:N% of panel_max)."""
    rows = ["<tr><th>%s</th><th>count</th><th>bar</th></tr>" % _esc(caption)]
    if not items:
        rows.append('<tr><td colspan="3" class="nodata">%s</td></tr>' % NO_DATA)
    for label, count in items:
        rows.append("<tr><td>%s</td><td>%s</td>%s</tr>"
                    % (_esc(label), _esc(count), _html_bar_cell(count, panel_max)))
    return "<table>" + "".join(rows) + "</table>"


def _html_panel1(value):
    if _is_no_data(value) or not isinstance(value, dict):
        return _html_no_data()
    status_items = _counts_items(value.get("by_status"))
    type_items = _counts_items(value.get("by_type"))
    # Shared panel_max across status+type so the bars are comparable within the panel
    # (matches the terminal surface's combined peak).
    panel_max = _panel_max([c for _, c in status_items + type_items])
    return (_html_counts_table("status", status_items, panel_max)
            + _html_counts_table("type", type_items, panel_max))


def _html_panel2(value):
    if _is_no_data(value) or not isinstance(value, dict):
        return _html_no_data()
    steps = value.get("steps") if isinstance(value.get("steps"), dict) else {}
    counts = [steps.get(skill, 0) for skill in acs_lib.HOOKED_SKILLS]
    panel_max = _panel_max(counts)
    rows = ["<tr><th>step</th><th>tickets</th><th>bar</th></tr>"]
    for skill in acs_lib.HOOKED_SKILLS:
        count = steps.get(skill, 0)
        rows.append("<tr><td>%s</td><td>%s</td>%s</tr>"
                    % (_esc(skill), _esc(count), _html_bar_cell(count, panel_max)))
    prs = value.get("prs") if isinstance(value.get("prs"), dict) else {}
    rows.append('<tr><td>PRs created</td><td>%s</td><td></td></tr>' % _esc(prs.get("created", 0)))
    rows.append('<tr><td>PRs merged</td><td>%s</td><td></td></tr>' % _esc(prs.get("merged", 0)))
    return "<table>" + "".join(rows) + "</table>"


def _html_panel3(value):
    if _is_no_data(value) or not isinstance(value, dict):
        return _html_no_data()
    rows = ["<tr><th>ticket</th><th>seconds</th><th>cost_usd</th></tr>"]
    tickets = value.get("tickets") if isinstance(value.get("tickets"), list) else []
    if not tickets:
        rows.append('<tr><td colspan="3" class="nodata">%s</td></tr>' % NO_DATA)
    for row in tickets:
        if not isinstance(row, dict):
            continue
        totals = row.get("totals") if isinstance(row.get("totals"), dict) else {}
        rows.append("<tr><td>%s</td><td>%s</td><td>%s</td></tr>"
                    % (_esc(row.get("ticket_id", "?")), _esc(totals.get("working_seconds", "-")),
                       _esc(_fmt_money(totals.get("cost_usd", "-"), empty="-"))))
    repo_totals = value.get("repo_totals") if isinstance(value.get("repo_totals"), dict) else {}
    if repo_totals:
        rows.append("<tr><td>REPO TOTAL</td><td>%s</td><td>%s</td></tr>"
                    % (_esc(repo_totals.get("working_seconds", "-")),
                       _esc(_fmt_money(repo_totals.get("cost_usd", "-"), empty="-"))))
    # Four averages summary rows (B1 — a "no data" average renders the nodata cell, never omitted).
    for label, formatted in _average_cells(value):
        cls = ' class="nodata"' if formatted == NO_DATA else ""
        rows.append('<tr><td>%s</td><td colspan="2"%s>%s</td></tr>'
                    % (_esc(label), cls, _esc(formatted)))
    return "<table>" + "".join(rows) + "</table>"


def _html_panel4(value):
    if _is_no_data(value) or not isinstance(value, dict):
        return _html_no_data()
    rows = ["<tr><th>ticket</th><th>achieved</th><th>target</th><th>passed</th></tr>"]
    tickets = value.get("tickets") if isinstance(value.get("tickets"), list) else []
    if not tickets:
        rows.append('<tr><td colspan="4" class="nodata">%s</td></tr>' % NO_DATA)
    for row in tickets:
        if not isinstance(row, dict):
            continue
        tid = _esc(row.get("ticket_id", "?"))
        if row.get("cell") == NO_DATA or "achieved" not in row:
            rows.append('<tr><td>%s</td><td colspan="3" class="nodata">%s</td></tr>' % (tid, NO_DATA))
            continue
        rows.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
                    % (tid, _esc(row.get("achieved")), _esc(row.get("target")),
                       "yes" if row.get("passed") else "no"))
    return "<table>" + "".join(rows) + "</table>"


def _html_panel5(value):
    if _is_no_data(value) or not isinstance(value, dict):
        return _html_no_data()
    rows = ["<tr><th>ticket</th><th>iterations</th></tr>"]
    tickets = value.get("tickets") if isinstance(value.get("tickets"), list) else []
    if not tickets:
        rows.append('<tr><td colspan="2" class="nodata">%s</td></tr>' % NO_DATA)
    for row in tickets:
        if not isinstance(row, dict):
            continue
        rows.append("<tr><td>%s</td><td>%s</td></tr>"
                    % (_esc(row.get("ticket_id", "?")), _esc(row.get("iterations", NO_DATA))))
    return "<table>" + "".join(rows) + "</table>"


def _html_panel6(value):
    if _is_no_data(value) or not isinstance(value, dict):
        return _html_no_data()
    # Bar on `input` tokens (consistent with the terminal surface's panel-6 peak).
    inputs = []
    for role in ROLE_ORDER:
        bucket = value.get(role) if isinstance(value.get(role), dict) else {}
        inputs.append(bucket.get("input", 0))
    panel_max = _panel_max(inputs)
    rows = ["<tr><th>role</th><th>input</th><th>output</th><th>cost_usd</th><th>bar</th></tr>"]
    for role in ROLE_ORDER:
        bucket = value.get(role) if isinstance(value.get(role), dict) else {}
        inp = bucket.get("input", 0)
        rows.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td>%s</tr>"
                    % (_esc(role), _esc(inp), _esc(bucket.get("output", 0)),
                       _esc(_fmt_money(bucket.get("cost", 0), empty="-")),
                       _html_bar_cell(inp, panel_max)))
    return "<table>" + "".join(rows) + "</table>"


def _html_lead_cycle_cell(value):
    """One lead/cycle <td> — humanized duration, or a nodata cell when the value is "no data" (B1)."""
    formatted = _humanize_seconds(value)
    cls = ' class="nodata"' if formatted == NO_DATA else ""
    return "<td%s>%s</td>" % (cls, _esc(formatted))


def _html_panel7(value):
    if _is_no_data(value) or not isinstance(value, dict):
        return _html_no_data()
    rows = ["<tr><th>ticket</th><th>lead</th><th>cycle</th></tr>"]
    tickets = value.get("tickets") if isinstance(value.get("tickets"), list) else []
    if not tickets:
        rows.append('<tr><td colspan="3" class="nodata">%s</td></tr>' % NO_DATA)
    for row in tickets:
        if not isinstance(row, dict):
            continue
        rows.append("<tr><td>%s</td>%s%s</tr>"
                    % (_esc(row.get("ticket_id", "?")),
                       _html_lead_cycle_cell(row.get("lead_seconds", NO_DATA)),
                       _html_lead_cycle_cell(row.get("cycle_seconds", NO_DATA))))
    # Two average summary rows (B1 — humanized, or a nodata cell when there is no value).
    for label, raw in (("avg lead", value.get("avg_lead_seconds", NO_DATA)),
                       ("avg cycle", value.get("avg_cycle_seconds", NO_DATA))):
        formatted = _humanize_seconds(raw)
        cls = ' class="nodata"' if formatted == NO_DATA else ""
        rows.append('<tr><td>%s</td><td colspan="2"%s>%s</td></tr>'
                    % (_esc(label), cls, _esc(formatted)))
    return "<table>" + "".join(rows) + "</table>"


_HTML_PANELS = {
    "1": _html_panel1,
    "2": _html_panel2,
    "3": _html_panel3,
    "4": _html_panel4,
    "5": _html_panel5,
    "6": _html_panel6,
    "7": _html_panel7,
}


def _html_degraded(degraded):
    parts = ['<div class="panel"><h3>Degraded</h3>']
    if not isinstance(degraded, list) or not degraded:
        parts.append('<div class="nodata">none — all panels had data</div>')
        parts.append("</div>")
        return "".join(parts)
    rows = ["<tr><th>ticket</th><th>panel</th><th>reason</th></tr>"]
    for entry in degraded:
        if not isinstance(entry, dict):
            continue
        rows.append("<tr><td>%s</td><td>%s</td><td>%s</td></tr>"
                    % (_esc(entry.get("ticket_id", "?")), _esc(entry.get("panel", "?")),
                       _esc(entry.get("reason", ""))))
    parts.append("<table>" + "".join(rows) + "</table>")
    parts.append("</div>")
    return "".join(parts)


# ---------------------------------------------------------------------------
# CLI: stdin (primary) or self-invoke aggregate (fallback); terminal default, --html on flag
# ---------------------------------------------------------------------------

def _load_payload():
    """Read the aggregate JSON from stdin when piped; else self-invoke metrics_aggregate."""
    stdin = sys.stdin
    piped = False
    try:
        piped = not stdin.isatty()
    except (ValueError, AttributeError):
        piped = True
    if piped:
        raw = stdin.read()
        if raw and raw.strip():
            return json.loads(raw)
    # Secondary — self-invoke the aggregator (no piped input).
    import metrics_aggregate
    ctx = acs_lib.build_context(os.getcwd())
    return metrics_aggregate.aggregate(ctx["workspace"], ctx["repo_id"])


def main():
    """Read the payload, render the chosen surface (terminal default, HTML on --html), print, exit 0."""
    want_html = "--html" in sys.argv[1:]
    data = _load_payload()
    output = render_html(data) if want_html else render_terminal(data)
    sys.stdout.write(output)
    if not output.endswith("\n"):
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
