"""
RadioAI Studio Pro — Spot Play Report (PDF) generator.

Operator workflow:
  1. Open Spots & Commercials → select a campaign
  2. Right panel → Play Reports tab → choose Actual or Scheduled +
     a date range → Generate
  3. PDF lands at  %LOCALAPPDATA%\\RadioAI\\reports\\<campaign>_<mode>_
     <start>_to_<end>.pdf
  4. Default viewer opens automatically (handled by the UI hook).

Layout mirrors Figma frame 415:2 — Jazler-style metadata block over a
day-by-day schedule grid, with a final Total banner and a footer that
tags the source mode ("ACTUAL" cyan / "SCHEDULED" amber).

Implementation notes:
  • QPdfWriter + QPainter (no extra dependencies). Coordinates use the
    A4 canvas Figma was sized against (595 × 842) — QPdfWriter is set
    to 72 DPI so 1 unit ≈ 1 point ≈ 1 pixel in the design.
  • Pagination: the daily-rows region keeps a running ``y`` cursor;
    once it crosses the page-content limit we flush the current page
    and start a new one with a compact header band. Final page also
    paints the Total banner + footer.
  • Station name + frequency come from Settings.station_display so
    re-branding the station propagates here without code changes.
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QFontDatabase, QLinearGradient, QPageLayout,
    QPageSize, QPainter, QPainterPath, QPdfWriter, QPen,
)

from core.database import Database
from core.settings import Settings

log = logging.getLogger("SpotPlayReport")


# ── Font self-loading ──────────────────────────────────────────────────────
#
# Project-wide font family names — match ui/widgets/_tokens.py so the
# PDF text uses the same typography as the on-screen Studio panels.
# IMPORTANT: the bundled InterVariable.ttf registers the family name
# "Inter Variable" (not "Inter"). Specifying the wrong family causes
# Qt to fall back to a default font whose glyph coverage may be
# limited — produces an all-boxes PDF when viewed.
INTER_FAMILY = "Inter Variable"
MONO_FAMILY  = "Roboto Mono"

# At app boot main.py's load_fonts() registers every .ttf in
# assets/fonts/ with QFontDatabase. The report generator needs the same
# fonts available to QPdfWriter so the embedded glyphs render correctly
# in any PDF viewer.
#
# Most callers go through the running app and inherit the loaded fonts
# already. This helper makes the generator self-sufficient: callers
# from the test suite, CLI, or scheduled-cron contexts get the fonts
# loaded too. Idempotent — second call is a no-op once the families
# are visible.

_FONTS_LOADED = False


def _ensure_fonts_loaded() -> None:
    global _FONTS_LOADED
    if _FONTS_LOADED:
        return
    families = set(QFontDatabase.families())
    if INTER_FAMILY in families and MONO_FAMILY in families:
        _FONTS_LOADED = True
        return
    # Locate assets/fonts relative to the project root.
    here = Path(__file__).resolve()
    project_root = here.parent.parent.parent     # core/reports/.. → project
    fonts_dir = project_root / "assets" / "fonts"
    if not fonts_dir.is_dir():
        log.warning(f"[reports] fonts dir not found at {fonts_dir} — "
                    f"PDF text may render as boxes")
        return
    for f in sorted(fonts_dir.iterdir()):
        if f.suffix.lower() not in (".ttf", ".otf"):
            continue
        fid = QFontDatabase.addApplicationFont(str(f))
        if fid != -1:
            log.debug(f"[reports] loaded font {f.name}")
    _FONTS_LOADED = True


# ── Public API constants ────────────────────────────────────────────────────

REPORT_MODE_ACTUAL = "actual"
REPORT_MODE_SCHEDULED = "scheduled"

DEFAULT_REPORT_DIR = Path(
    os.environ.get("LOCALAPPDATA",
                   os.path.expanduser("~/AppData/Local"))
) / "RadioAI" / "reports"


class SpotPlayReportError(RuntimeError):
    """Raised when the report cannot be generated (missing campaign,
    invalid date range, write failure, etc.)."""


# ── Layout constants (1 unit ≈ 1 point on A4) ──────────────────────────────

PAGE_W      = 595
PAGE_H      = 842
MARGIN_X    = 40
PAGE_LIMIT_Y = 760     # daily rows must finish above this on each page

HEADER_H    = 100      # logo + title + underline
FOOTER_Y    = 802

# Daily row geometry
ROW_GAP        = 8
ROW_LINE_H     = 14
LABEL_X        = MARGIN_X
LABEL_W        = 110
SLOTS_X        = 156
SLOTS_W        = 400
SLOTS_PER_LINE = 6     # how many "(N)HH:MM" entries fit per line

# Color tokens (paper / ink palette — distinct from the dark UI tokens
# in core/constants.py because the PDF prints on white)
INK_PRI    = "#0a0c18"
INK_SEC    = "#3d3f55"
INK_MUTED  = "#6b6e8a"
RULE       = "#dadce0"
RULE_LITE  = "#eef0f4"
CYAN       = "#06b6d4"
PURPLE     = "#7c3aed"
PURPLE_L   = "#a78bfa"
AMBER      = "#f59e0b"


# ── Helpers ────────────────────────────────────────────────────────────────

def _qcolor(hex_str: str, alpha: float = 1.0) -> QColor:
    c = QColor(hex_str)
    c.setAlphaF(alpha)
    return c


def _font(family: str, size: int, weight: QFont.Weight = QFont.Weight.Normal,
          letter_spacing: float = 0.0) -> QFont:
    f = QFont(family, size)
    f.setWeight(weight)
    if letter_spacing:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, letter_spacing)
    return f


def _slugify(text: str) -> str:
    """Filename-safe slug from a campaign name."""
    out = []
    for ch in (text or "report").lower():
        if ch.isalnum():
            out.append(ch)
        elif ch in (" ", "_", "-"):
            out.append("_")
    s = "".join(out).strip("_") or "report"
    return s[:48]


def _fmt_dur(ms: int) -> str:
    s = max(0, int(ms or 0)) // 1000
    if s < 60:
        return f"{s}sec"
    return f"{s // 60}:{s % 60:02d}"


def _date_range(start: date, end: date) -> list[date]:
    if end < start:
        return []
    out: list[date] = []
    cur = start
    while cur <= end:
        out.append(cur)
        cur += timedelta(days=1)
    return out


def _dow_short(d: date) -> str:
    return ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")[d.weekday()]


def _fmt_short(d: date) -> str:
    return f"{_dow_short(d)} {d.strftime('%d/%m/%y')}"


def _fmt_long(d: date) -> str:
    return d.strftime("%A, %B %d, %Y")


# ── Data extraction ────────────────────────────────────────────────────────

def _fetch_campaign(db: Database, campaign_id: int) -> dict:
    row = db._conn().execute(
        "SELECT * FROM campaigns WHERE id = ?", [int(campaign_id)]).fetchone()
    if row is None:
        raise SpotPlayReportError(
            f"Campaign id={campaign_id} not found")
    return dict(row)


def _fetch_spot_files(db: Database, campaign_id: int) -> list[dict]:
    rows = db._conn().execute(
        "SELECT id, filename, file_path, duration_ms, is_active, "
        "       display_order "
        "FROM   spot_files "
        "WHERE  campaign_id = ? "
        "ORDER  BY display_order ASC, id ASC",
        [int(campaign_id)]).fetchall()
    return [dict(r) for r in rows]


def _fetch_scheduled_plays(db: Database, campaign_id: int,
                            start: date, end: date,
                            spot_count: int) -> dict[date, list[tuple[int, str]]]:
    """For Scheduled mode: expand campaign_schedule across the date
    range. Returns ``{date: [(spot_index, "HH:MM"), ...]}``.

    spot_index is 1-based; if multiple spot files exist, the slot_order
    cycles through them. With one file (the common case) every slot
    gets index 1."""
    rows = db._conn().execute(
        "SELECT day_of_week, break_time, slot_order "
        "FROM   campaign_schedule "
        "WHERE  campaign_id = ? "
        "ORDER  BY day_of_week, break_time, slot_order",
        [int(campaign_id)]).fetchall()
    by_dow: dict[int, list[tuple[int, str]]] = {}
    spot_max = max(1, int(spot_count or 1))
    for r in rows:
        dow = int(r["day_of_week"])
        slot_order = int(r["slot_order"] or 0)
        idx = (slot_order % spot_max) + 1
        by_dow.setdefault(dow, []).append((idx, str(r["break_time"] or "")))
    out: dict[date, list[tuple[int, str]]] = {}
    for d in _date_range(start, end):
        out[d] = list(by_dow.get(d.weekday(), []))
    return out


def _fetch_actual_plays(db: Database, campaign_id: int,
                         start: date, end: date,
                         spot_count: int) -> dict[date, list[tuple[int, str]]]:
    """For Actual mode: pull broadcast_log rows where entry_type IN
    ('spot', 'ad', 'break') AND campaign_id = ? AND played_at falls
    inside the date range. Returns the same shape as
    _fetch_scheduled_plays."""
    rows = db._conn().execute(
        "SELECT played_at, slot_idx "
        "FROM   broadcast_log "
        "WHERE  campaign_id = ? "
        "AND    entry_type IN ('spot', 'ad', 'break') "
        "AND    played_at  IS NOT NULL "
        "AND    DATE(played_at) BETWEEN ? AND ? "
        "ORDER  BY played_at ASC",
        [int(campaign_id), start.isoformat(), end.isoformat()]).fetchall()
    out: dict[date, list[tuple[int, str]]] = {}
    spot_max = max(1, int(spot_count or 1))
    for d in _date_range(start, end):
        out[d] = []
    for r in rows:
        try:
            played = datetime.fromisoformat(str(r["played_at"]))
        except ValueError:
            continue
        d = played.date()
        if d in out:
            slot_idx = int(r["slot_idx"] or 0)
            idx = (slot_idx % spot_max) + 1
            out[d].append((idx, played.strftime("%H:%M")))
    return out


# ── Page rendering primitives ──────────────────────────────────────────────

class _Painter:
    """Wraps QPainter + the page-level utility helpers used by every
    layout block. Holds the running ``y`` cursor for the daily grid."""

    def __init__(self, p: QPainter):
        self.p = p

    def text(self, x, y, w, h, s, *,
             family=INTER_FAMILY, size=10, weight=QFont.Weight.Normal,
             color=INK_PRI, align=None, letter_spacing=0.0):
        self.p.setFont(_font(family, size, weight, letter_spacing))
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


def _draw_logo_tile(pp: _Painter, x: int, y: int, size: int = 48) -> None:
    """Purple gradient tile + 5 white speaker bars (matches Figma 415:2)."""
    p = pp.p
    rect = QRectF(x, y, size, size)
    path = QPainterPath()
    path.addRoundedRect(rect, 12, 12)
    p.save()
    p.setClipPath(path)
    grad = QLinearGradient(x, y, x + size, y + size)
    grad.setColorAt(0.0, _qcolor("#a78bfa"))
    grad.setColorAt(0.5, _qcolor(PURPLE))
    grad.setColorAt(1.0, _qcolor("#5b21b6"))
    p.fillRect(rect, QBrush(grad))
    p.restore()
    # Speaker bars
    centers = [10, 18, 24, 30, 38]    # x-offsets within the tile
    heights = [10, 18, 28, 18, 10]
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_qcolor("#ffffff", 0.95))
    for cx, h in zip(centers, heights):
        bar_x = x + cx - 1.5
        bar_y = y + (size - h) / 2
        p.drawRoundedRect(QRectF(bar_x, bar_y, 3, h), 1.5, 1.5)


def _draw_header(pp: _Painter, *, mode: str, station_display: str,
                 page_num: int) -> None:
    """Top header band — logo + title + mode badge + underline. Page 1
    paints the full version; pages 2+ paint a compact band the same
    height so the daily grid still has consistent y math."""
    _draw_logo_tile(pp, MARGIN_X, 40, 48)
    pp.text(MARGIN_X + 60, 42, 400, 18, "RadioAI Reporting Tool",
            family=INTER_FAMILY, size=12, weight=QFont.Weight.Bold,
            color=INK_SEC)
    pp.text(MARGIN_X + 60, 62, 400, 22,
            f"{station_display}  Spots Broadcast Analysis",
            family=INTER_FAMILY, size=14, weight=QFont.Weight.Bold,
            color=INK_PRI)

    # Mode badge top-right
    badge_color = AMBER if mode == REPORT_MODE_SCHEDULED else CYAN
    pp.rect(460, 48, 95, 22, fill=badge_color, fill_alpha=0.16,
            stroke=badge_color, stroke_alpha=0.5, radius=4)
    pp.text(460, 48, 95, 22,
            "SCHEDULED" if mode == REPORT_MODE_SCHEDULED else "ACTUAL",
            family=INTER_FAMILY, size=9, weight=QFont.Weight.Bold,
            color=badge_color, letter_spacing=1.4,
            align=Qt.AlignmentFlag.AlignCenter)

    pp.hr(MARGIN_X, 100, PAGE_W - MARGIN_X * 2, color=INK_PRI)


def _draw_metadata(pp: _Painter, campaign: dict, spot_files: list[dict],
                   start: date, end: date,
                   station_display: str) -> int:
    """Metadata block — Spot Title / Ad Company / Client / Media Shop
    / Start & Expire. Returns the y cursor below the block."""
    label_opts = dict(family=INTER_FAMILY, size=10, weight=QFont.Weight.Bold,
                      color=INK_MUTED, align=Qt.AlignmentFlag.AlignRight
                      | Qt.AlignmentFlag.AlignVCenter)
    val_opts = dict(family=INTER_FAMILY, size=10, weight=QFont.Weight.Medium,
                    color=INK_PRI)

    # Field mapping (reasonable defaults — operator can configure later)
    spot_title = (spot_files[0]["filename"]
                  if spot_files else f"{campaign.get('name') or 'Spot'}.mp3")
    ad_company = ""    # operator may add a settings key in v2
    client = (campaign.get("description") or campaign.get("name") or "").strip()
    media_shop = station_display
    start_expire = (f"{_fmt_long(start)} > {_fmt_long(end)}")

    rows = [
        ("Spot Title:", spot_title, None, None),
        ("Ad Company:", ad_company, "Media Shop:", media_shop),
        ("Client:", client, None, None),
        ("Start & Expire:", start_expire, None, None),
    ]
    y = 120
    for lbl, val, lbl2, val2 in rows:
        pp.text(40, y, 110, 14, lbl, **label_opts)
        pp.text(156, y, 200, 14, val, **val_opts)
        if lbl2:
            pp.text(360, y, 90, 14, lbl2, **label_opts)
            pp.text(456, y, 100, 14, val2, **val_opts)
        y += 18
    pp.hr(MARGIN_X, y + 6, PAGE_W - MARGIN_X * 2)
    return y + 16


def _draw_spots_list(pp: _Painter, spot_files: list[dict], y: int) -> int:
    pp.text(40, y, 110, 14, "Spots List:",
            family=INTER_FAMILY, size=10, weight=QFont.Weight.Bold,
            color=INK_MUTED, align=Qt.AlignmentFlag.AlignRight
            | Qt.AlignmentFlag.AlignVCenter)
    if spot_files:
        line = ", ".join(
            f"({i + 1}) {sf.get('filename') or '—'} - "
            f"{_fmt_dur(sf.get('duration_ms') or 0)}"
            for i, sf in enumerate(spot_files))
    else:
        line = "(no audio files attached to this campaign)"
    pp.text(156, y, 400, 14, line,
            family=MONO_FAMILY, size=10, color=INK_PRI)
    y += 22

    pp.text(40, y, 110, 14, "Play Order:",
            family=INTER_FAMILY, size=10, weight=QFont.Weight.Bold,
            color=INK_MUTED, align=Qt.AlignmentFlag.AlignRight
            | Qt.AlignmentFlag.AlignVCenter)
    pp.text(156, y, 400, 14,
            "The spots are scheduled to play based on the number in the "
            "spots list.",
            family=INTER_FAMILY, size=9, color=INK_MUTED)
    y += 22
    pp.hr(MARGIN_X, y, PAGE_W - MARGIN_X * 2)
    return y + 14


def _format_slot_lines(plays: list[tuple[int, str]]) -> list[str]:
    """Group "(N)HH:MM" entries into SLOTS_PER_LINE-wide lines for
    pretty wrap. Empty list → one ``— no plays —`` placeholder line."""
    if not plays:
        return ["— no plays —"]
    out: list[str] = []
    for i in range(0, len(plays), SLOTS_PER_LINE):
        chunk = plays[i:i + SLOTS_PER_LINE]
        line = ", ".join(f"({idx}){t}" for idx, t in chunk)
        if i + SLOTS_PER_LINE < len(plays):
            line += ","
        out.append(line)
    return out


def _draw_day_row(pp: _Painter, day: date, plays: list[tuple[int, str]],
                  y: int) -> int:
    lines = _format_slot_lines(plays)
    pp.text(LABEL_X, y, LABEL_W, ROW_LINE_H, _fmt_short(day),
            family=INTER_FAMILY, size=10, weight=QFont.Weight.Bold,
            color=INK_PRI)
    for i, line in enumerate(lines):
        pp.text(SLOTS_X, y + i * ROW_LINE_H, SLOTS_W, ROW_LINE_H, line,
                family=MONO_FAMILY, size=9, color=INK_PRI)
    new_y = y + len(lines) * ROW_LINE_H + ROW_GAP
    pp.hr(MARGIN_X, new_y - 4, PAGE_W - MARGIN_X * 2, color=RULE_LITE)
    return new_y


def _draw_total_banner(pp: _Painter, y: int, total_plays: int,
                       day_count: int, plays_per_day_avg: float) -> int:
    pp.rect(MARGIN_X, y, PAGE_W - MARGIN_X * 2, 32,
            fill=AMBER, fill_alpha=0.10,
            stroke=AMBER, stroke_alpha=0.4, radius=4)
    pp.text(MARGIN_X + 16, y + 9, 200, 14, "Total Spots:",
            family=INTER_FAMILY, size=11, weight=QFont.Weight.Bold,
            color=AMBER, letter_spacing=0.6)
    pp.text(156, y + 8, 100, 18, str(total_plays),
            family=MONO_FAMILY, size=14, weight=QFont.Weight.Bold,
            color=INK_PRI)
    pp.text(350, y + 9, PAGE_W - 350 - MARGIN_X, 14,
            f"({day_count} days × ~{plays_per_day_avg:.0f} plays/day)",
            family=INTER_FAMILY, size=9, color=INK_MUTED,
            align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
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
    pp.text(350, FOOTER_Y + 8, 205, 14, "RadioAI Spot Reports",
            family=INTER_FAMILY, size=10, weight=QFont.Weight.Bold,
            color=INK_PRI, align=Qt.AlignmentFlag.AlignRight
            | Qt.AlignmentFlag.AlignVCenter)
    pp.text(350, FOOTER_Y + 22, 205, 12,
            f"Generated: {generated_at.strftime('%d/%m/%Y %H:%M')}  ·  "
            f"{station_display}",
            family=INTER_FAMILY, size=8, color=INK_MUTED,
            align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)


# ── Public entry point ─────────────────────────────────────────────────────

def generate_spot_play_report(
    campaign_id: int,
    mode: str,
    start_date: date,
    end_date: date,
    output_path: Optional[Path] = None,
    db: Optional[Database] = None,
) -> Path:
    """Generate the PDF report for a campaign.

    Returns the absolute Path of the written file. Raises
    SpotPlayReportError on any setup-time failure (missing campaign,
    invalid range, write failure).
    """
    if mode not in (REPORT_MODE_ACTUAL, REPORT_MODE_SCHEDULED):
        raise SpotPlayReportError(
            f"unknown report mode {mode!r}; expected "
            f"{REPORT_MODE_ACTUAL!r} or {REPORT_MODE_SCHEDULED!r}")
    if end_date < start_date:
        raise SpotPlayReportError(
            f"end_date {end_date} precedes start_date {start_date}")

    _ensure_fonts_loaded()
    db = db or Database()
    campaign = _fetch_campaign(db, campaign_id)
    spot_files = _fetch_spot_files(db, campaign_id)
    spot_count = len(spot_files) or 1

    if mode == REPORT_MODE_SCHEDULED:
        plays_by_day = _fetch_scheduled_plays(
            db, campaign_id, start_date, end_date, spot_count)
    else:
        plays_by_day = _fetch_actual_plays(
            db, campaign_id, start_date, end_date, spot_count)

    days = _date_range(start_date, end_date)
    total_plays = sum(len(plays_by_day.get(d, [])) for d in days)
    plays_per_day_avg = total_plays / max(1, len(days))

    # Resolve output path
    out_dir = (output_path.parent if output_path is not None
               else DEFAULT_REPORT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    if output_path is None:
        slug = _slugify(campaign.get("name") or f"campaign{campaign_id}")
        fname = (f"{slug}_{mode}_"
                 f"{start_date.strftime('%Y%m%d')}_to_"
                 f"{end_date.strftime('%Y%m%d')}.pdf")
        output_path = out_dir / fname

    station_display = Settings().station_display
    generated_at = datetime.now()

    # ── Compute pagination ──
    # Each day occupies (lines * ROW_LINE_H + ROW_GAP) px. We need to
    # know which day-rows fit per page. Pre-compute heights.
    day_heights: list[int] = []
    for d in days:
        n_lines = len(_format_slot_lines(plays_by_day.get(d, [])))
        day_heights.append(n_lines * ROW_LINE_H + ROW_GAP)

    # Page 1: header(100) + metadata(~110) + spots-list(~50) → grid starts ~290
    # Pages 2+: header(100) → grid starts ~110
    PAGE1_GRID_START = 290
    PAGEN_GRID_START = 110
    # Reserve space at the bottom of the LAST page for the Total banner
    # + footer (40 + 70 ≈ 110). On non-last pages just need footer (60).

    pages: list[list[int]] = [[]]    # list of day-indices per page
    cur_y = PAGE1_GRID_START
    page_idx = 0
    for di, h in enumerate(day_heights):
        # Reserve 110 on the LAST page for total+footer; we don't know
        # which page is last yet, so reserve on every page conservatively
        # and adjust if there's slack on the final page.
        limit = PAGE_LIMIT_Y - 110
        if cur_y + h > limit and pages[page_idx]:
            page_idx += 1
            pages.append([])
            cur_y = PAGEN_GRID_START
        pages[page_idx].append(di)
        cur_y += h

    total_pages = len(pages)

    # ── Render ──
    writer = QPdfWriter(str(output_path))
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    writer.setPageOrientation(QPageLayout.Orientation.Portrait)
    writer.setResolution(72)     # 1 unit ≈ 1 pt

    p = QPainter()
    if not p.begin(writer):
        raise SpotPlayReportError(
            f"QPainter.begin failed for {output_path}")
    try:
        pp = _Painter(p)
        for pi, day_indices in enumerate(pages):
            page_num = pi + 1
            if pi > 0:
                writer.newPage()
            # Header
            _draw_header(pp, mode=mode, station_display=station_display,
                         page_num=page_num)
            # Metadata + spots list only on page 1
            if pi == 0:
                y = _draw_metadata(pp, campaign, spot_files,
                                    start_date, end_date, station_display)
                y = _draw_spots_list(pp, spot_files, y)
            else:
                y = PAGEN_GRID_START
            # Daily rows for this page
            for di in day_indices:
                y = _draw_day_row(pp, days[di], plays_by_day.get(days[di], []),
                                   y)
            # Total banner on last page only
            if pi == total_pages - 1:
                _draw_total_banner(pp, y + 4, total_plays,
                                    len(days), plays_per_day_avg)
            # Footer on every page
            _draw_footer(pp, page_num, total_pages,
                          station_display, generated_at)
    finally:
        p.end()

    log.info(
        f"[spot_play_report] generated id={campaign_id} mode={mode} "
        f"range={start_date}→{end_date} pages={total_pages} "
        f"total_plays={total_plays} → {output_path}")
    return output_path
