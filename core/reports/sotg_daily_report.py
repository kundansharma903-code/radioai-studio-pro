"""
RadioAI Studio Pro — Spot on the Go (SOTG) Daily Report (PDF) generator.

Operator workflow:
  1. AI Magic ✦ → Spot on the Go → Generate Report
  2. Pick a day (default: yesterday)
  3. Click Download PDF — file lands at  E:\\RadioAI_v2\\reports\\sotg\\
     sotg_daily_<YYYY-MM-DD>.pdf  and the OS default PDF viewer opens it.

Also runs unattended at 23:59 every day via MainWindow's minute tick —
writes the same file with that day's data so the operator always has a
historical record on disk without needing to open the screen.

Layout (A4 portrait, 595×842 pt @72dpi):
  • Header band — RadioAI logo + station name + report title + ACTUAL pill
  • Date pill + 3 stat blocks (Total Drops / Played / Missed)
  • Per-show grouped sections (operator-requested grouping):
      - Show banner painted in the show's clock color, with show name,
        RJ, link count, played/missed sub-counters
      - One row per link, ordered by link_order ASC
      - Page break inserted if the next link wouldn't fit
  • Total banner at the end of the last page
  • Footer with page number, generator stamp, station display

The grouping is the v1 operator decision (Option B from the briefing
conversation): "First Show ke Complete links then Next Show, then next
show". Within each show, link_order ASC preserves the broadcast-day
sequence the operator authored in Create Schedule.

Pending statuses (PENDING / READY / CONFLICT) are excluded by default;
caller passes ``include_pending=True`` to keep them — the screen's
"Show pending too" toggle drives this. The midnight auto-save uses
the default (FIRED + MISSED only, the "final" picture for the day).

AI Summary per-link block is wired-but-unused in v1 — every link row
checks for ``ai_summary`` on the assignment dict and paints an
italicised sub-block under it if present. Today the dict never carries
that key, so rows render plain. When the Assign API Key + transcription
pipeline lands, the same row code paints transcription content with
zero additional changes.
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QFontDatabase, QLinearGradient, QPageLayout,
    QPageSize, QPainter, QPainterPath, QPdfWriter, QPen,
)

from core.database import Database
from core.settings import Settings

log = logging.getLogger("SOTGDailyReport")


# ── Font self-loading ──────────────────────────────────────────────────────
INTER_FAMILY = "Inter Variable"
MONO_FAMILY  = "Roboto Mono"

_FONTS_LOADED = False


def _ensure_fonts_loaded() -> None:
    global _FONTS_LOADED
    if _FONTS_LOADED:
        return
    families = set(QFontDatabase.families())
    if INTER_FAMILY in families and MONO_FAMILY in families:
        _FONTS_LOADED = True
        return
    here = Path(__file__).resolve()
    project_root = here.parent.parent.parent     # core/reports/.. → project
    fonts_dir = project_root / "assets" / "fonts"
    if not fonts_dir.is_dir():
        log.warning(f"[sotg_report] fonts dir not found at {fonts_dir} — "
                    f"PDF text may render as boxes")
        return
    for f in sorted(fonts_dir.iterdir()):
        if f.suffix.lower() not in (".ttf", ".otf"):
            continue
        QFontDatabase.addApplicationFont(str(f))
    _FONTS_LOADED = True


# ── Public API ─────────────────────────────────────────────────────────────

def _resolve_default_dir() -> Path:
    """Project-root anchored:  E:\\RadioAI_v2\\reports\\sotg\\

    Operator preference (2026-05-14 briefing): visible folder inside the
    project root, not a hidden %LOCALAPPDATA% path. Falls back to
    ~/Documents/RadioAI/sotg if the project root isn't writable for some
    reason (read-only CD, permissions, etc.)."""
    here = Path(__file__).resolve()
    project_root = here.parent.parent.parent     # core/reports/.. → project
    candidates = [
        project_root / "reports" / "sotg",
        Path(os.path.expanduser("~")) / "Documents" / "RadioAI" / "sotg",
        Path(os.environ.get("LOCALAPPDATA",
                            os.path.expanduser("~/AppData/Local"))
             ) / "RadioAI" / "reports" / "sotg",
    ]
    for c in candidates:
        try:
            c.mkdir(parents=True, exist_ok=True)
            return c
        except (OSError, PermissionError):
            continue
    return candidates[-1]


DEFAULT_REPORT_DIR = _resolve_default_dir()


class SOTGDailyReportError(RuntimeError):
    """Raised when the report cannot be generated (DB unreachable, write
    failure, etc.)."""


# ── Layout constants (1 unit ≈ 1 point on A4) ──────────────────────────────

PAGE_W      = 595
PAGE_H      = 842
MARGIN_X    = 40
PAGE_LIMIT_Y = 760     # rows must finish above this on each page

HEADER_H    = 100
FOOTER_Y    = 802

ROW_H            = 26       # per-link row height
SHOW_BANNER_H    = 38       # group header band
SHOW_GAP_BEFORE  = 14       # vertical space before each new show group
AI_SUMMARY_H     = 32       # reserved height when a link carries ai_summary

# Color tokens (paper / ink palette — distinct from the dark UI tokens)
INK_PRI    = "#0a0c18"
INK_SEC    = "#3d3f55"
INK_MUTED  = "#6b6e8a"
RULE       = "#dadce0"
RULE_LITE  = "#eef0f4"
CYAN       = "#06b6d4"
PURPLE     = "#7c3aed"
GREEN      = "#10b981"
GREEN_INK  = "#047857"
AMBER      = "#f59e0b"
RED        = "#dc2626"
RED_INK    = "#991b1b"


# ── Helpers ────────────────────────────────────────────────────────────────

def _qcolor(hex_str: str, alpha: float = 1.0) -> QColor:
    c = QColor(hex_str)
    c.setAlphaF(alpha)
    return c


def _font(family: str, size: int, weight: QFont.Weight = QFont.Weight.Normal,
          letter_spacing: float = 0.0, italic: bool = False) -> QFont:
    f = QFont(family, size)
    f.setWeight(weight)
    f.setItalic(italic)
    if letter_spacing:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, letter_spacing)
    return f


def _fmt_dur(ms: int) -> str:
    s = max(0, int(ms or 0)) // 1000
    if s < 60:
        return f"0:{s:02d}"
    return f"{s // 60}:{s % 60:02d}"


def _safe_color(value: Optional[str], fallback: str = CYAN) -> str:
    """Validate a hex color string; fall back to cyan if missing/garbled.
    Show banners use the show's configured clock color — if the operator
    saved garbage we don't want to crash a PDF render."""
    if not value:
        return fallback
    v = str(value).strip()
    if v.startswith("#") and len(v) in (4, 7):
        try:
            int(v[1:], 16)
            return v
        except ValueError:
            return fallback
    return fallback


def _status_to_display(status: str) -> tuple[str, str, str]:
    """Map DB status enum → (display_text, badge_color, glyph). Falls
    back to a neutral display for unknown enums so we never crash."""
    s = (status or "").upper()
    if s == "FIRED":
        return ("PLAYED", GREEN, "✓")
    if s == "MISSED":
        return ("MISSED", RED, "✕")
    if s == "PENDING":
        return ("PENDING", AMBER, "◷")
    if s == "READY":
        return ("READY", CYAN, "◯")
    if s == "CONFLICT":
        return ("CONFLICT", AMBER, "⚠")
    return (s or "—", INK_MUTED, "·")


# ── Painter helper ──────────────────────────────────────────────────────────

class _Painter:
    """Wraps QPainter + the page-level utility helpers used by every
    layout block. Same shape as ui.spots_commercials' Play Report
    painter — kept duplicated rather than extracted so changes to one
    don't risk regressing the other."""

    def __init__(self, p: QPainter):
        self.p = p

    def text(self, x, y, w, h, s, *,
             family=INTER_FAMILY, size=10, weight=QFont.Weight.Normal,
             color=INK_PRI, align=None, letter_spacing=0.0, italic=False):
        self.p.setFont(_font(family, size, weight, letter_spacing, italic))
        self.p.setPen(_qcolor(color))
        rect = QRectF(x, y, w, h)
        flags = align or (Qt.AlignmentFlag.AlignLeft
                          | Qt.AlignmentFlag.AlignVCenter)
        self.p.drawText(rect, int(flags), s)

    def rect(self, x, y, w, h, *, fill=None, stroke=None,
             stroke_w=1, radius=0, fill_alpha=1.0, stroke_alpha=1.0):
        self.p.setPen(Qt.PenStyle.NoPen if stroke is None
                      else QPen(_qcolor(stroke, stroke_alpha), stroke_w))
        self.p.setBrush(Qt.BrushStyle.NoBrush if fill is None
                        else QBrush(_qcolor(fill, fill_alpha)))
        if radius:
            self.p.drawRoundedRect(QRectF(x, y, w, h), radius, radius)
        else:
            self.p.drawRect(QRectF(x, y, w, h))

    def hr(self, x, y, w, color=RULE):
        self.p.setPen(QPen(_qcolor(color), 1))
        self.p.drawLine(int(x), int(y), int(x + w), int(y))


# ── Layout drawers ──────────────────────────────────────────────────────────

def _draw_logo_tile(pp: _Painter, x: int, y: int, size: int = 48) -> None:
    """Purple→cyan gradient ellipse + 5 white speaker bars (matches the
    on-screen header logo so the PDF feels first-party)."""
    p = pp.p
    rect = QRectF(x, y, size, size)
    path = QPainterPath()
    path.addEllipse(rect)
    p.save()
    p.setClipPath(path)
    grad = QLinearGradient(x, y, x + size, y + size)
    grad.setColorAt(0.0, _qcolor("#a78bfa"))
    grad.setColorAt(1.0, _qcolor(CYAN))
    p.fillRect(rect, QBrush(grad))
    p.restore()
    centers = [10, 18, 24, 30, 38]
    heights = [10, 18, 28, 18, 10]
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_qcolor("#ffffff", 0.95))
    for cx, h in zip(centers, heights):
        bar_x = x + cx - 1.5
        bar_y = y + (size - h) / 2
        p.drawRoundedRect(QRectF(bar_x, bar_y, 3, h), 1.5, 1.5)


def _draw_header(pp: _Painter, *, station_display: str,
                 report_date: date, total_pages: int) -> None:
    _draw_logo_tile(pp, MARGIN_X, 38, 48)
    pp.text(MARGIN_X + 60, 38, 400, 16, "RadioAI Reporting Tool",
            family=INTER_FAMILY, size=11, weight=QFont.Weight.Bold,
            color=INK_SEC)
    pp.text(MARGIN_X + 60, 56, 400, 22,
            f"{station_display}  ·  Spot on the Go Daily Report",
            family=INTER_FAMILY, size=13, weight=QFont.Weight.Bold,
            color=INK_PRI)
    # ACTUAL badge (top-right) — same convention as Play Report
    pp.rect(460, 46, 95, 22, fill=CYAN, fill_alpha=0.16,
            stroke=CYAN, stroke_alpha=0.5, radius=4)
    pp.text(460, 46, 95, 22, "ACTUAL",
            family=INTER_FAMILY, size=9, weight=QFont.Weight.Bold,
            color=CYAN, letter_spacing=1.4,
            align=Qt.AlignmentFlag.AlignCenter)
    pp.hr(MARGIN_X, 96, PAGE_W - MARGIN_X * 2, color=INK_PRI)


def _draw_summary_strip(pp: _Painter, *, report_date: date,
                         total: int, played: int, missed: int) -> int:
    """Date pill + 3 stat blocks. Returns the y cursor below the strip."""
    y = 108
    # Date pill
    pretty = report_date.strftime("%a, %d %b %Y")
    pp.rect(MARGIN_X, y, 200, 28, fill=PURPLE, fill_alpha=0.10,
            stroke=PURPLE, stroke_alpha=0.35, radius=14)
    pp.text(MARGIN_X + 14, y, 200, 28, f"📅  {pretty}",
            family=INTER_FAMILY, size=11, weight=QFont.Weight.Bold,
            color=PURPLE)
    # 3 stat blocks (right side)
    stats = [
        ("TOTAL", str(total), INK_PRI, INK_MUTED),
        ("PLAYED", str(played), GREEN_INK, GREEN),
        ("MISSED", str(missed), RED_INK, RED),
    ]
    bx = PAGE_W - MARGIN_X - 3 * 90 - 2 * 8
    for label, val, val_c, accent in stats:
        pp.rect(bx, y, 90, 28, stroke=accent, stroke_alpha=0.35, radius=6)
        pp.rect(bx, y, 3, 28, fill=accent)
        pp.text(bx + 10, y, 50, 14, label,
                family=INTER_FAMILY, size=8, weight=QFont.Weight.Bold,
                color=INK_MUTED, letter_spacing=1.2)
        pp.text(bx + 10, y + 11, 70, 17, val,
                family=MONO_FAMILY, size=14, weight=QFont.Weight.Bold,
                color=val_c)
        bx += 98
    return y + 38


# ── Show grouping ───────────────────────────────────────────────────────────

def _draw_show_banner(pp: _Painter, y: int, *, show_name: str,
                      rj_name: str, color: str,
                      played: int, missed: int, total: int) -> int:
    """Per-show colored band: show name + RJ + per-show counters. Operator
    asked for visual differentiation between shows ("color heading ka
    change ho ya kuch or") — this is it."""
    pp.rect(MARGIN_X, y, PAGE_W - MARGIN_X * 2, SHOW_BANNER_H,
            fill=color, fill_alpha=0.10,
            stroke=color, stroke_alpha=0.50, radius=6)
    # Left accent bar (full saturation) so the show color is unambiguous
    pp.rect(MARGIN_X, y, 4, SHOW_BANNER_H, fill=color)
    pp.text(MARGIN_X + 14, y + 5, 300, 16, show_name,
            family=INTER_FAMILY, size=12, weight=QFont.Weight.Bold,
            color=INK_PRI)
    pp.text(MARGIN_X + 14, y + 21, 300, 14, f"RJ: {rj_name or '—'}",
            family=INTER_FAMILY, size=9, weight=QFont.Weight.Medium,
            color=INK_SEC)
    # Right-side per-show counters
    rx = PAGE_W - MARGIN_X - 220
    pp.text(rx, y + 5, 220, 16,
            f"{total} link{'s' if total != 1 else ''}",
            family=INTER_FAMILY, size=10, weight=QFont.Weight.Bold,
            color=INK_PRI,
            align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    pp.text(rx, y + 21, 220, 14,
            f"✓ {played} played   ✕ {missed} missed",
            family=MONO_FAMILY, size=9, weight=QFont.Weight.Bold,
            color=INK_SEC,
            align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return y + SHOW_BANNER_H + 6


def _draw_link_row(pp: _Painter, y: int, *, link_order: int,
                   link_name: str, sharp_time: str, status: str,
                   file_name: str, duration_ms: int,
                   ai_summary: Optional[str] = None) -> int:
    """One link row: [#] · [HH:MM] · LINK NAME · status pill · file ·
    duration. Optional AI summary block underneath when populated."""
    pp.rect(MARGIN_X, y, PAGE_W - MARGIN_X * 2, ROW_H,
            stroke=RULE, stroke_alpha=1.0, radius=4)
    # # number (mono)
    pp.text(MARGIN_X + 10, y, 32, ROW_H, f"#{link_order:02d}",
            family=MONO_FAMILY, size=9, weight=QFont.Weight.Bold,
            color=INK_MUTED)
    # Time (mono)
    pp.text(MARGIN_X + 46, y, 50, ROW_H, sharp_time or "—:—",
            family=MONO_FAMILY, size=10, weight=QFont.Weight.Bold,
            color=INK_PRI)
    # Link name
    pp.text(MARGIN_X + 102, y, 180, ROW_H, link_name or "(unnamed link)",
            family=INTER_FAMILY, size=10, weight=QFont.Weight.Medium,
            color=INK_PRI)
    # Status pill (small)
    disp, badge_c, glyph = _status_to_display(status)
    pill_x = MARGIN_X + 290
    pp.rect(pill_x, y + 5, 64, 16,
            fill=badge_c, fill_alpha=0.16,
            stroke=badge_c, stroke_alpha=0.40, radius=8)
    pp.text(pill_x, y + 5, 64, 16, f"{glyph} {disp}",
            family=INTER_FAMILY, size=8, weight=QFont.Weight.Bold,
            color=badge_c, letter_spacing=0.6,
            align=Qt.AlignmentFlag.AlignCenter)
    # File (truncate gracefully — QPainter elides via Qt::TextSingleLine)
    fname = file_name or "—"
    pp.text(MARGIN_X + 364, y, 120, ROW_H, fname,
            family=MONO_FAMILY, size=8, color=INK_MUTED)
    # Duration (right-aligned)
    pp.text(PAGE_W - MARGIN_X - 64, y, 54, ROW_H,
            _fmt_dur(duration_ms),
            family=MONO_FAMILY, size=9, weight=QFont.Weight.Bold,
            color=INK_PRI,
            align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    new_y = y + ROW_H + 4
    # Optional AI Summary sub-block (v2 future — Assign API Key wires
    # the data, no other changes required here)
    if ai_summary:
        pp.text(MARGIN_X + 14, new_y, PAGE_W - MARGIN_X * 2 - 14,
                AI_SUMMARY_H, f"AI Summary: {ai_summary}",
                family=INTER_FAMILY, size=9,
                weight=QFont.Weight.Medium, color=INK_SEC, italic=True)
        new_y += AI_SUMMARY_H
    return new_y


def _draw_total_banner(pp: _Painter, y: int, *,
                       total: int, played: int, missed: int) -> int:
    pp.rect(MARGIN_X, y, PAGE_W - MARGIN_X * 2, 32,
            fill=AMBER, fill_alpha=0.10,
            stroke=AMBER, stroke_alpha=0.40, radius=4)
    pp.text(MARGIN_X + 16, y + 9, 200, 14, "Daily Total:",
            family=INTER_FAMILY, size=11, weight=QFont.Weight.Bold,
            color=AMBER, letter_spacing=0.6)
    pp.text(160, y + 8, 100, 18, str(total),
            family=MONO_FAMILY, size=14, weight=QFont.Weight.Bold,
            color=INK_PRI)
    pp.text(220, y + 9, PAGE_W - 220 - MARGIN_X, 14,
            f"({played} played, {missed} missed)",
            family=INTER_FAMILY, size=9, color=INK_MUTED)
    return y + 40


def _draw_footer(pp: _Painter, page_num: int, total_pages: int,
                 station_display: str, generated_at: datetime) -> None:
    pp.hr(MARGIN_X, FOOTER_Y, PAGE_W - MARGIN_X * 2)
    pp.text(MARGIN_X, FOOTER_Y + 8, 100, 14,
            f"{page_num} / {total_pages}",
            family=INTER_FAMILY, size=10, weight=QFont.Weight.Bold,
            color=INK_PRI)
    pp.text(MARGIN_X, FOOTER_Y + 22, 200, 12,
            "RadioAI Studio v2.0",
            family=INTER_FAMILY, size=8, color=INK_MUTED)
    pp.text(350, FOOTER_Y + 8, 205, 14, "Spot on the Go · Daily",
            family=INTER_FAMILY, size=10, weight=QFont.Weight.Bold,
            color=INK_PRI, align=Qt.AlignmentFlag.AlignRight
            | Qt.AlignmentFlag.AlignVCenter)
    pp.text(350, FOOTER_Y + 22, 205, 12,
            f"Generated: {generated_at.strftime('%d/%m/%Y %H:%M')}  ·  "
            f"{station_display}",
            family=INTER_FAMILY, size=8, color=INK_MUTED,
            align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)


# ── Data extraction ────────────────────────────────────────────────────────

def _fetch_assignments(db: Database, report_date: date,
                       include_pending: bool) -> list[dict]:
    """Pull every assignment scheduled on report_date. Returns rows
    sorted in DB-native order (sharp_time ASC); we re-sort by show
    + link_order in the grouping step."""
    rows = db.get_sotg_assignments_for_date(report_date.isoformat())
    if include_pending:
        return rows
    return [r for r in rows if (r.get("status") or "").upper()
            in ("FIRED", "MISSED")]


def _group_by_show(rows: list[dict]) -> list[dict]:
    """Group rows by show_id. Each group is sorted internally by
    link_order ASC. Groups are sorted by the earliest sharp_time in
    the group so the PDF reads in broadcast-day order (Show that
    aired first → next show → ...).

    Returns a list of  ``{ "show_id", "show_name", "rj_name", "color",
    "rows": [...], "total", "played", "missed" }``  dicts."""
    by_show: dict[int, dict] = {}
    for r in rows:
        sid = int(r.get("show_id") or 0)
        if sid not in by_show:
            by_show[sid] = {
                "show_id": sid,
                "show_name": r.get("show_name") or "(untitled show)",
                "rj_name": r.get("rj_name") or "",
                "color": _safe_color(r.get("color")),
                "rows": [],
                "total": 0,
                "played": 0,
                "missed": 0,
                "earliest_time": "99:99",
            }
        g = by_show[sid]
        g["rows"].append(r)
        g["total"] += 1
        status = (r.get("status") or "").upper()
        if status == "FIRED":
            g["played"] += 1
        elif status == "MISSED":
            g["missed"] += 1
        t = str(r.get("sharp_time") or "")
        if t and t < g["earliest_time"]:
            g["earliest_time"] = t
    # Sort rows within each group by link_order ASC, fall back to
    # sharp_time so unknown ordering still lands somewhere stable
    for g in by_show.values():
        g["rows"].sort(key=lambda x: (
            int(x.get("link_order") or 9999),
            str(x.get("sharp_time") or ""),
        ))
    # Sort groups by earliest sharp_time
    groups = sorted(by_show.values(), key=lambda g: g["earliest_time"])
    return groups


# ── Pagination ──────────────────────────────────────────────────────────────

def _row_height(row: dict) -> int:
    h = ROW_H + 4
    if row.get("ai_summary"):
        h += AI_SUMMARY_H
    return h


def _paginate(groups: list[dict]) -> list[list[dict]]:
    """Walk the groups + rows and decide where each page break lands.
    Returns a list-of-pages, each page being a list of "render ops":
      { "kind": "banner", "group": {...} }
      { "kind": "row", "row": {...}, "group": {...} }
    Total banner is always on the last page (added by caller).

    Page 1 grid starts at  PAGE1_GRID_START  (after header + summary).
    Pages 2+ grid starts at  PAGEN_GRID_START  (after compact header).
    Reserved tail (footer + final total) is  PAGE_LIMIT_Y."""
    PAGE1_GRID_START = 160
    PAGEN_GRID_START = 110

    pages: list[list[dict]] = [[]]
    cur_y = PAGE1_GRID_START
    page_idx = 0

    def _new_page():
        nonlocal cur_y, page_idx
        page_idx += 1
        pages.append([])
        cur_y = PAGEN_GRID_START

    for g in groups:
        banner_h = SHOW_GAP_BEFORE + SHOW_BANNER_H + 6
        first_row_h = _row_height(g["rows"][0]) if g["rows"] else 0
        if cur_y + banner_h + first_row_h > PAGE_LIMIT_Y and pages[page_idx]:
            _new_page()
        pages[page_idx].append({"kind": "banner", "group": g,
                                 "gap_before": cur_y > PAGEN_GRID_START + 1})
        cur_y += banner_h
        for r in g["rows"]:
            rh = _row_height(r)
            if cur_y + rh > PAGE_LIMIT_Y and pages[page_idx]:
                _new_page()
                # Repeat a compact banner on the new page so the operator
                # knows which show the rows belong to
                pages[page_idx].append({"kind": "banner", "group": g,
                                         "gap_before": False,
                                         "continuation": True})
                cur_y += SHOW_BANNER_H + 6
            pages[page_idx].append({"kind": "row", "row": r, "group": g})
            cur_y += rh
    return pages


# ── Public entry point ─────────────────────────────────────────────────────

def generate_sotg_daily_report(
    report_date: date,
    output_path: Optional[Path] = None,
    db: Optional[Database] = None,
    include_pending: bool = False,
) -> Path:
    """Generate the SOTG daily PDF.

    ``report_date`` — the broadcast day to report on.
    ``output_path`` — explicit override; default lands in
                       ``DEFAULT_REPORT_DIR / sotg_daily_<YYYY-MM-DD>.pdf``.
    ``include_pending`` — when True, surface PENDING/READY/CONFLICT rows
                          (the screen's "Show pending too" toggle path);
                          defaults to False (final-state view, what the
                          midnight auto-saver writes).

    Returns the absolute Path. Raises ``SOTGDailyReportError`` on any
    setup-time failure."""
    if not isinstance(report_date, date):
        raise SOTGDailyReportError(
            f"report_date must be a datetime.date, got {type(report_date)!r}")

    _ensure_fonts_loaded()
    db = db or Database()

    rows = _fetch_assignments(db, report_date, include_pending)
    groups = _group_by_show(rows)
    total = sum(g["total"] for g in groups)
    played = sum(g["played"] for g in groups)
    missed = sum(g["missed"] for g in groups)

    # Resolve output path
    out_dir = (output_path.parent if output_path is not None
               else DEFAULT_REPORT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    if output_path is None:
        fname = f"sotg_daily_{report_date.strftime('%Y-%m-%d')}.pdf"
        output_path = out_dir / fname

    station_display = Settings().station_display
    generated_at = datetime.now()

    pages = _paginate(groups)
    total_pages = max(1, len(pages))

    writer = QPdfWriter(str(output_path))
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    writer.setPageOrientation(QPageLayout.Orientation.Portrait)
    writer.setResolution(72)

    p = QPainter()
    if not p.begin(writer):
        raise SOTGDailyReportError(
            f"QPainter.begin failed for {output_path}")
    try:
        pp = _Painter(p)
        for pi, ops in enumerate(pages):
            page_num = pi + 1
            if pi > 0:
                writer.newPage()
            _draw_header(pp, station_display=station_display,
                         report_date=report_date, total_pages=total_pages)
            if pi == 0:
                y = _draw_summary_strip(pp, report_date=report_date,
                                         total=total, played=played,
                                         missed=missed)
            else:
                y = 110

            if not ops:
                # Empty-day page — render an explicit empty-state line
                pp.text(MARGIN_X, y + 40, PAGE_W - MARGIN_X * 2, 24,
                        "No Spot on the Go drops were scheduled for this day.",
                        family=INTER_FAMILY, size=11,
                        weight=QFont.Weight.Medium, color=INK_MUTED,
                        align=Qt.AlignmentFlag.AlignCenter)

            for op in ops:
                if op["kind"] == "banner":
                    if op.get("gap_before"):
                        y += SHOW_GAP_BEFORE
                    g = op["group"]
                    name = g["show_name"]
                    if op.get("continuation"):
                        name = f"{name}  (continued)"
                    y = _draw_show_banner(pp, y,
                                           show_name=name,
                                           rj_name=g["rj_name"],
                                           color=g["color"],
                                           played=g["played"],
                                           missed=g["missed"],
                                           total=g["total"])
                else:
                    r = op["row"]
                    y = _draw_link_row(
                        pp, y,
                        link_order=int(r.get("link_order") or 0),
                        link_name=str(r.get("link_name") or ""),
                        sharp_time=str(r.get("sharp_time") or ""),
                        status=str(r.get("status") or ""),
                        file_name=str(r.get("file_name") or ""),
                        duration_ms=int(r.get("file_duration_ms") or 0),
                        ai_summary=r.get("ai_summary"),
                    )

            if pi == total_pages - 1 and ops:
                _draw_total_banner(pp, max(y, 700) + 6,
                                    total=total, played=played, missed=missed)
            _draw_footer(pp, page_num, total_pages,
                          station_display, generated_at)
    finally:
        p.end()
    # Force handle release before return (Windows / Edge race — same
    # rationale as core/reports/spot_play_report.py)
    del writer
    import gc
    gc.collect()

    log.info(
        f"[sotg_daily_report] generated date={report_date.isoformat()} "
        f"pages={total_pages} shows={len(groups)} total={total} "
        f"played={played} missed={missed} "
        f"include_pending={include_pending} → {output_path}")
    return output_path
