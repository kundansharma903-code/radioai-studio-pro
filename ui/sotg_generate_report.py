"""
RadioAI Studio Pro — Spot on the Go · Generate Report (Figma 497:2)

Step 3 of Spot on the Go. Shows the daily play log for every SOTG drop
on the selected date, scrollable table, with a Download PDF button
that pipes through ``core.reports.generate_sotg_daily_report`` and
opens the result in the OS default viewer.

Same data also lands at  E:\\RadioAI_v2\\reports\\sotg\\
sotg_daily_<YYYY-MM-DD>.pdf  unattended at 23:59 every day via
MainWindow's minute tick. Manual Download from this screen overwrites
that same file (same path, same data), so the operator always has
both an on-demand and an end-of-day-frozen copy.

Public signals:
  screen_requested(str) — "control_panel" / "ai_magic" / "spot_on_the_go"
  studio_clicked()      — header Open Studio button
"""

from __future__ import annotations

import logging
import os
from datetime import date as ddate, datetime, timedelta
from typing import Optional

from PyQt6.QtCore import Qt, QDate, QRectF, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QLinearGradient, QRadialGradient,
    QFont, QCursor,
)
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QHBoxLayout, QVBoxLayout,
    QScrollArea, QCalendarWidget, QMessageBox, QCheckBox,
)

from core.settings import Settings
from ui.widgets._tokens import (
    inter, mono, rgba,
    BG_BASE, BG_PANEL,
    TEXT_PRI, TEXT_SEC, TEXT_MUTED, TEXT_DIM,
    CYAN, CYAN_LIGHT, PURPLE, PURPLE_LIGHT,
    GREEN, GREEN_LIGHT, AMBER, AMBER_LIGHT,
    PINK, RED,
)
from ui.spot_on_the_go_shell import (
    _HeaderLogo, _HeaderOpenStudio, _BreadcrumbLink, _BreadcrumbPill,
    _StatusPill, _PremiumBackdrop,
)

log = logging.getLogger("SOTGGenerateReport")

WINDOW_W = 1440
WINDOW_H = 900
HEADER_H = 72
STATUS_H = 36

# Light red for missed; helper for chip styling
RED_LIGHT = "#fb7185"

# Status palette (mirrors core/reports + sotg_assign)
STATUS_STYLE = {
    "FIRED":    ("PLAYED",   GREEN,  GREEN_LIGHT, "✓"),
    "MISSED":   ("MISSED",   RED,    RED_LIGHT,   "✕"),
    "PENDING":  ("PENDING",  AMBER,  AMBER_LIGHT, "◷"),
    "READY":    ("READY",    CYAN,   CYAN_LIGHT,  "◯"),
    "CONFLICT": ("CONFLICT", AMBER,  AMBER_LIGHT, "⚠"),
}


def _format_duration_ms(ms: Optional[int]) -> str:
    if ms is None or ms <= 0:
        return "—"
    s = int(ms) // 1000
    return f"{s // 60}:{s % 60:02d}"


def _safe_color(value: Optional[str], fallback: str = CYAN) -> str:
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


# ════════════════════════════════════════════════════════════════════════════
# Small custom widgets
# ════════════════════════════════════════════════════════════════════════════


class _StatPill(QFrame):
    """Hero right-side stat block — left accent bar + label + value.
    Built once with placeholder; ``set_value(int)`` refreshes the count
    in place (per incident #19 — capture QLabel ref, never findChild)."""

    def __init__(self, label: str, glyph: str,
                 accent: str, value_color: str, parent=None):
        super().__init__(parent)
        self._accent = accent
        self.setFixedSize(200, 80)
        self.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border: 1px solid {rgba(accent, 0.35)}; "
            f"border-radius: 12px; }}"
        )
        # Left accent bar (decorative)
        bar = QFrame(self)
        bar.setGeometry(0, 0, 4, 80)
        bar.setStyleSheet(
            f"background: {accent}; border-top-left-radius: 2px; "
            f"border-bottom-left-radius: 2px; border: none;")

        glyph_lbl = QLabel(glyph, self)
        glyph_lbl.setGeometry(18, 16, 28, 28)
        glyph_lbl.setFont(inter(22, QFont.Weight.Bold))
        glyph_lbl.setStyleSheet(
            f"color: {accent}; background: transparent; border: none;")

        lbl = QLabel(label, self)
        lbl.setGeometry(54, 20, 130, 14)
        lbl.setFont(inter(10, QFont.Weight.Bold, letter_spacing=1.2))
        lbl.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent; border: none;")

        self._value_lbl = QLabel("0", self)
        self._value_lbl.setGeometry(54, 36, 130, 36)
        self._value_lbl.setFont(mono(26, bold=True))
        self._value_lbl.setStyleSheet(
            f"color: {value_color}; background: transparent; border: none;")

    def set_value(self, n: int) -> None:
        self._value_lbl.setText(str(int(n)))


class _DateNavButton(QPushButton):
    """◀ / ▶ chevron button — fixed 40×40, themed like the SOTG family."""

    def __init__(self, glyph: str, parent=None):
        super().__init__(glyph, parent)
        self.setFixedSize(40, 40)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFont(inter(13, QFont.Weight.Bold))
        self.setStyleSheet(
            f"QPushButton {{ background: {BG_PANEL}; color: {TEXT_PRI}; "
            f"border: 1px solid {rgba('#ffffff', 0.10)}; "
            f"border-radius: 10px; }}"
            f"QPushButton:hover {{ border-color: {rgba(CYAN, 0.50)}; }}"
        )


class _DatePill(QPushButton):
    """Calendar pill — clicking pops a QCalendarWidget. Text updates
    via ``set_date(date)``."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(264, 40)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFont(inter(13, QFont.Weight.Bold))
        self.setStyleSheet(
            f"QPushButton {{ background: {BG_PANEL}; color: {TEXT_PRI}; "
            f"border: 1px solid {rgba(CYAN, 0.45)}; border-radius: 10px; "
            f"text-align: left; padding: 0 16px; }}"
            f"QPushButton:hover {{ border-color: {CYAN_LIGHT}; }}"
        )

    def set_date(self, d: ddate) -> None:
        pretty = d.strftime("%a, %d %b %Y")
        self.setText(f"📅   {pretty}")


class _TodayButton(QPushButton):
    def __init__(self, parent=None):
        super().__init__("Today", parent)
        self.setFixedSize(90, 40)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFont(inter(12, QFont.Weight.Bold))
        self.setStyleSheet(
            f"QPushButton {{ background: {rgba(CYAN, 0.18)}; color: {CYAN}; "
            f"border: 1px solid {rgba(CYAN, 0.45)}; border-radius: 10px; }}"
            f"QPushButton:hover {{ background: {rgba(CYAN, 0.28)}; }}"
        )


class _PendingToggle(QFrame):
    """Right-side filter: "Show pending too" with a custom checkbox so
    the look matches the SOTG family (QCheckBox theming on Qt6/Windows
    is notoriously fragile)."""

    toggled = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(198, 40)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border: 1px solid {rgba('#ffffff', 0.10)}; "
            f"border-radius: 10px; }}"
        )
        self._checked = False

        self._box = QFrame(self)
        self._box.setGeometry(16, 12, 16, 16)
        self._render_box()

        lbl = QLabel("Show pending too", self)
        lbl.setGeometry(42, 8, 150, 24)
        lbl.setFont(inter(12, QFont.Weight.Medium))
        lbl.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent; border: none;")

    def _render_box(self) -> None:
        if self._checked:
            self._box.setStyleSheet(
                f"QFrame {{ background: {CYAN}; "
                f"border: 1px solid {CYAN}; border-radius: 4px; }}"
            )
        else:
            self._box.setStyleSheet(
                f"QFrame {{ background: transparent; "
                f"border: 1px solid {rgba(TEXT_SEC, 0.50)}; "
                f"border-radius: 4px; }}"
            )

    def is_checked(self) -> bool:
        return self._checked

    def set_checked(self, v: bool) -> None:
        new = bool(v)
        if new == self._checked:
            return
        self._checked = new
        self._render_box()
        self.toggled.emit(self._checked)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.set_checked(not self._checked)
        super().mousePressEvent(e)


class _AssignmentRow(QFrame):
    """One link row inside the scrollable table. Captures all QLabel
    references at build time (per incident #19) so refresh is a clean
    setText on each.

    Height expands from 56 → 116 when ``ai_summary`` is populated —
    a 4-line italic block lands beneath the link name to mirror the
    PDF's per-row layout (operator's 2026-05-14 spec)."""

    HEIGHT = 56
    HEIGHT_WITH_SUMMARY = 116

    def __init__(self, data: dict, parent=None):
        super().__init__(parent)
        self._data = data
        ai_status = (data.get("ai_status") or "").upper()
        summary = (data.get("ai_summary") or "").strip()
        self._has_summary = ai_status == "DONE" and bool(summary)
        h = self.HEIGHT_WITH_SUMMARY if self._has_summary else self.HEIGHT
        self.setFixedHeight(h)
        show_color = _safe_color(data.get("color"))
        self._show_color = show_color
        self.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border: 1px solid {rgba('#ffffff', 0.08)}; "
            f"border-radius: 8px; }}"
        )

        # Left accent bar (paints in show color via paintEvent)
        # # column
        num_lbl = QLabel(f"{int(data.get('link_order') or 0):02d}", self)
        num_lbl.setGeometry(20, 20, 36, 18)
        num_lbl.setFont(mono(13, bold=True))
        num_lbl.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; border: none;")

        # TIME column
        time_lbl = QLabel(str(data.get("sharp_time") or "—:—"), self)
        time_lbl.setGeometry(64, 20, 60, 18)
        time_lbl.setFont(mono(14, bold=True))
        time_lbl.setStyleSheet(
            f"color: {TEXT_PRI}; background: transparent; border: none;")

        # SHOW dot + name
        # Dot is painted in paintEvent so it stays in show color
        show_lbl = QLabel(str(data.get("show_name") or "(untitled)"), self)
        show_lbl.setGeometry(158, 20, 200, 18)
        show_lbl.setFont(inter(13, QFont.Weight.DemiBold))
        show_lbl.setStyleSheet(
            f"color: {TEXT_PRI}; background: transparent; border: none;")

        # RJ
        rj_lbl = QLabel(str(data.get("rj_name") or "—"), self)
        rj_lbl.setGeometry(372, 20, 120, 18)
        rj_lbl.setFont(inter(12, QFont.Weight.Medium))
        rj_lbl.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent; border: none;")

        # LINK
        link_lbl = QLabel(str(data.get("link_name") or "—"), self)
        link_lbl.setGeometry(504, 20, 240, 18)
        link_lbl.setFont(inter(12, QFont.Weight.Medium))
        link_lbl.setStyleSheet(
            f"color: {TEXT_PRI}; background: transparent; border: none;")

        # STATUS pill
        status = (data.get("status") or "").upper()
        disp, badge_c, badge_light, glyph = STATUS_STYLE.get(
            status, ("—", TEXT_MUTED, TEXT_MUTED, "·"))
        pill = QFrame(self)
        pill.setGeometry(756, 14, 100, 28)
        pill.setStyleSheet(
            f"QFrame {{ background: {rgba(badge_c, 0.18)}; "
            f"border: 1px solid {rgba(badge_c, 0.45)}; "
            f"border-radius: 14px; }}"
        )
        plbl = QLabel(f"{glyph}  {disp}", pill)
        plbl.setGeometry(0, 0, 100, 28)
        plbl.setFont(inter(10, QFont.Weight.Bold, letter_spacing=0.8))
        plbl.setStyleSheet(
            f"color: {badge_light}; background: transparent; border: none;")
        plbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # FILE column
        file_lbl = QLabel(str(data.get("file_name") or "—"), self)
        file_lbl.setGeometry(872, 20, 320, 18)
        file_lbl.setFont(mono(11))
        file_lbl.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent; border: none;")

        # DURATION (right-aligned)
        dur_lbl = QLabel(
            _format_duration_ms(data.get("file_duration_ms")), self)
        dur_lbl.setGeometry(1212, 20, 80, 18)
        dur_lbl.setFont(mono(12, bold=True))
        dur_lbl.setStyleSheet(
            f"color: {TEXT_PRI}; background: transparent; border: none;")
        dur_lbl.setAlignment(Qt.AlignmentFlag.AlignRight
                              | Qt.AlignmentFlag.AlignVCenter)

        # 4-line AI summary sub-block — only when status is DONE +
        # ai_summary populated. Spec: italic, indented under link name,
        # smaller font, secondary color. Each line clipped at 1240px.
        if self._has_summary:
            lines = summary.splitlines()[:4]
            base_y = 50
            for i, line in enumerate(lines):
                slbl = QLabel(line, self)
                slbl.setGeometry(58, base_y + i * 14, 1230, 14)
                slbl.setFont(inter(10, italic=True))
                slbl.setStyleSheet(
                    f"color: {TEXT_SEC}; background: transparent; "
                    f"border: none;")

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Left accent bar in show color
        p.fillRect(QRectF(0, 0, 3, self.height()), QColor(self._show_color))
        # Show color dot at x=142
        p.setBrush(QBrush(QColor(self._show_color)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(140, 23, 10, 10))
        p.end()


# ════════════════════════════════════════════════════════════════════════════
# Public screen
# ════════════════════════════════════════════════════════════════════════════


class SOTGGenerateReport(QWidget):
    """Spot on the Go · Generate Report (Figma 497:2)."""

    screen_requested = pyqtSignal(str)
    studio_clicked   = pyqtSignal()

    def __init__(self, db=None, parent=None):
        super().__init__(parent)
        self._db = db
        self.setFixedSize(WINDOW_W, WINDOW_H)
        self.setStyleSheet(f"QWidget {{ background: {BG_BASE}; }}")

        # State
        self._report_date: ddate = ddate.today() - timedelta(days=1)
        self._include_pending: bool = False
        self._rows_cache: list[dict] = []
        # Track rebuilt row widgets in an instance list (incident #17 —
        # never iterate parent.children() for cleanup)
        self._row_widgets: list[QWidget] = []

        self._backdrop = _PremiumBackdrop(self)
        self._backdrop.setGeometry(0, 0, WINDOW_W, WINDOW_H)

        self._build_header()
        self._build_hero()
        self._build_date_bar()
        self._build_table()
        self._build_action_bar()
        self._build_status_bar()

        # Clock + footer last-save tick
        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._tick_clock)
        self._clock_timer.start()
        self._tick_clock()

        self._refresh_data()
        log.info("SOTGGenerateReport ready (Figma 497:2)")

    # ── Header ────────────────────────────────────────────────────────

    def _build_header(self) -> None:
        h = QFrame(self)
        h.setGeometry(0, 0, WINDOW_W, HEADER_H)
        h.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border-bottom: 1px solid {rgba('#ffffff', 0.06)}; }}"
        )

        _HeaderLogo(h).move(14, 16)
        l = QLabel("RadioAI", h)
        l.setGeometry(64, 14, 120, 18)
        l.setFont(inter(15, QFont.Weight.Bold))
        l.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        l2 = QLabel("STUDIO PRO", h)
        l2.setGeometry(64, 34, 120, 12)
        l2.setFont(inter(8, QFont.Weight.Bold, letter_spacing=1.2))
        l2.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

        # 4-crumb breadcrumb: Control Panel | AI Magic | Spot on the Go | [Generate Report]
        cp = _BreadcrumbLink("Control Panel", h)
        cp.setGeometry(176, 22, 100, 22)
        cp.clicked.connect(
            lambda: self.screen_requested.emit("control_panel"))
        sep1 = QLabel("|", h); sep1.setGeometry(272, 22, 8, 22)
        sep1.setFont(inter(11))
        sep1.setStyleSheet(f"color: {TEXT_DIM}; background: transparent;")

        am = _BreadcrumbLink("AI Magic", h)
        am.setGeometry(284, 22, 80, 22)
        am.clicked.connect(
            lambda: self.screen_requested.emit("ai_magic"))
        sep2 = QLabel("|", h); sep2.setGeometry(364, 22, 8, 22)
        sep2.setFont(inter(11))
        sep2.setStyleSheet(f"color: {TEXT_DIM}; background: transparent;")

        sog = _BreadcrumbLink("Spot on the Go", h)
        sog.setGeometry(376, 22, 110, 22)
        sog.clicked.connect(
            lambda: self.screen_requested.emit("spot_on_the_go"))
        sep3 = QLabel("|", h); sep3.setGeometry(490, 22, 8, 22)
        sep3.setFont(inter(11))
        sep3.setStyleSheet(f"color: {TEXT_DIM}; background: transparent;")

        pill = _BreadcrumbPill("▤ Generate Report", h)
        pill.move(502, 20)

        # Title + subtitle
        title = QLabel("Generate Report", h)
        title.setGeometry(680, 12, 240, 24)
        title.setFont(inter(20, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        sub = QLabel(
            "Daily play log + auto-saved PDF for every SOTG drop",
            h)
        sub.setGeometry(680, 38, 420, 14)
        sub.setFont(inter(10))
        sub.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

        # Clock + station
        self._clock_lbl = QLabel("", h)
        self._clock_lbl.setGeometry(1108, 14, 100, 24)
        self._clock_lbl.setFont(mono(20, bold=True))
        self._clock_lbl.setStyleSheet(
            f"color: {TEXT_PRI}; background: transparent;")
        try:
            station = Settings().station_display or "KISS FM 91.5"
        except Exception:
            station = "KISS FM 91.5"
        self._station_lbl = QLabel(station, h)
        self._station_lbl.setObjectName("hdr_station_lbl")
        self._station_lbl.setGeometry(1108, 40, 110, 14)
        self._station_lbl.setFont(inter(9, QFont.Weight.Medium))
        self._station_lbl.setStyleSheet(
            f"color: {GREEN}; background: transparent;")

        osb = _HeaderOpenStudio(h)
        osb.move(1222, 16)
        osb.clicked.connect(self.studio_clicked.emit)

    # ── Hero ──────────────────────────────────────────────────────────

    def _build_hero(self) -> None:
        sigil = QLabel("▤", self)
        sigil.setGeometry(60, 100, 40, 36)
        sigil.setFont(inter(28, QFont.Weight.Bold))
        sigil.setStyleSheet(
            f"color: {GREEN_LIGHT}; background: transparent; border: none;")
        title = QLabel("GENERATE REPORT", self)
        title.setGeometry(106, 96, 700, 44)
        title.setFont(inter(28, QFont.Weight.Black, letter_spacing=-0.4))
        title.setStyleSheet(
            f"color: {TEXT_PRI}; background: transparent; border: none;")

        sub1 = QLabel(
            "Daily play log for every Spot on the Go drop. Auto-saves "
            "at 11:59 PM to E:\\RadioAI_v2\\reports\\sotg\\.", self)
        sub1.setGeometry(60, 144, 1100, 18)
        sub1.setFont(inter(13, QFont.Weight.Medium))
        sub1.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent; border: none;")

        sub2 = QLabel(
            "Manual download below — same data the auto-saver writes.",
            self)
        sub2.setGeometry(60, 166, 1100, 16)
        sub2.setFont(inter(11, QFont.Weight.Medium))
        sub2.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; border: none;")

        # 3 stat pills (right side)
        self._pill_total = _StatPill("TOTAL DROPS", "▦", PURPLE, TEXT_PRI,
                                       parent=self)
        self._pill_played = _StatPill("PLAYED", "✓", GREEN, GREEN,
                                        parent=self)
        self._pill_missed = _StatPill("MISSED", "✕", RED, RED,
                                        parent=self)
        gap = 12
        right_edge = WINDOW_W - 60
        pw = 200
        self._pill_missed.move(right_edge - pw, 104)
        self._pill_played.move(right_edge - 2 * pw - gap, 104)
        self._pill_total.move(right_edge - 3 * pw - 2 * gap, 104)

    # ── Date bar ──────────────────────────────────────────────────────

    def _build_date_bar(self) -> None:
        bar = QFrame(self)
        bar.setGeometry(60, 216, 1320, 48)
        bar.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border: 1px solid {rgba('#ffffff', 0.08)}; "
            f"border-radius: 12px; }}"
        )

        prev_btn = _DateNavButton("◀", self)
        prev_btn.move(72, 220)
        prev_btn.clicked.connect(self._on_prev_day)

        self._date_pill = _DatePill(self)
        self._date_pill.move(120, 220)
        self._date_pill.set_date(self._report_date)
        self._date_pill.clicked.connect(self._on_open_calendar)

        next_btn = _DateNavButton("▶", self)
        next_btn.move(392, 220)
        next_btn.clicked.connect(self._on_next_day)

        today_btn = _TodayButton(self)
        today_btn.move(444, 220)
        today_btn.clicked.connect(self._on_today)

        self._pending_toggle = _PendingToggle(self)
        self._pending_toggle.move(1170, 220)
        self._pending_toggle.toggled.connect(self._on_toggle_pending)

    # ── Table ─────────────────────────────────────────────────────────

    def _build_table(self) -> None:
        # Table header band
        hdr = QFrame(self)
        hdr.setGeometry(60, 280, 1320, 40)
        hdr.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border: 1px solid {rgba('#ffffff', 0.08)}; "
            f"border-radius: 8px; }}"
        )
        cols = [
            (20, 36, "#"),
            (64, 60, "TIME"),
            (158, 180, "SHOW"),
            (372, 120, "RJ"),
            (504, 240, "LINK"),
            (756, 100, "STATUS"),
            (872, 320, "FILE"),
            (1212, 80, "DURATION"),
        ]
        for x, w, label in cols:
            lbl = QLabel(label, hdr)
            lbl.setGeometry(x, 12, w, 16)
            lbl.setFont(inter(9, QFont.Weight.Bold, letter_spacing=1.4))
            lbl.setStyleSheet(
                f"color: {TEXT_MUTED}; background: transparent; border: none;")
            if label == "DURATION":
                lbl.setAlignment(Qt.AlignmentFlag.AlignRight
                                  | Qt.AlignmentFlag.AlignVCenter)

        # Scroll area for rows
        scroll = QScrollArea(self)
        scroll.setGeometry(60, 328, 1320, 446)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            f"QScrollArea {{ background: transparent; border: none; }}"
            f"QScrollBar:vertical {{ background: {BG_PANEL}; "
            f"width: 10px; border-radius: 5px; }}"
            f"QScrollBar::handle:vertical {{ background: "
            f"{rgba('#ffffff', 0.12)}; border-radius: 5px; "
            f"min-height: 30px; }}"
            f"QScrollBar::handle:vertical:hover {{ background: "
            f"{rgba(CYAN, 0.40)}; }}"
            f"QScrollBar::add-line:vertical, "
            f"QScrollBar::sub-line:vertical {{ height: 0; }}"
        )
        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        self._rows_layout = QVBoxLayout(inner)
        self._rows_layout.setContentsMargins(0, 0, 8, 0)
        self._rows_layout.setSpacing(8)
        self._rows_layout.addStretch()
        scroll.setWidget(inner)
        self._rows_inner = inner
        self._rows_scroll = scroll

        # Footer hint band (below the scroll area)
        hint_left = QLabel("", self)
        hint_left.setGeometry(60, 778, 720, 16)
        hint_left.setFont(inter(11, QFont.Weight.Medium))
        hint_left.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; border: none;")
        self._hint_pending_lbl = hint_left

        hint_right = QLabel(
            "AI Summary per link unlocks once an API key is assigned "
            "(coming soon).",
            self)
        hint_right.setGeometry(760, 778, 620, 16)
        hint_right.setFont(inter(11, QFont.Weight.Medium))
        hint_right.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; border: none;")
        hint_right.setAlignment(Qt.AlignmentFlag.AlignRight)

    # ── Action bar ────────────────────────────────────────────────────

    def _build_action_bar(self) -> None:
        bar = QFrame(self)
        bar.setGeometry(60, 804, 1320, 48)
        bar.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border: 1px solid {rgba('#ffffff', 0.08)}; "
            f"border-radius: 12px; }}"
        )

        folder_icon = QLabel("📁", bar)
        folder_icon.setGeometry(18, 14, 22, 20)
        folder_icon.setFont(inter(15))
        folder_icon.setStyleSheet(
            f"color: {TEXT_PRI}; background: transparent; border: none;")

        prefix = QLabel("Auto-saved daily at 11:59 PM to", bar)
        prefix.setGeometry(46, 16, 220, 16)
        prefix.setFont(inter(12, QFont.Weight.Medium))
        prefix.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent; border: none;")

        from core.reports.sotg_daily_report import DEFAULT_REPORT_DIR
        path_lbl = QLabel(str(DEFAULT_REPORT_DIR), bar)
        path_lbl.setGeometry(270, 16, 380, 16)
        path_lbl.setFont(mono(11, bold=True))
        path_lbl.setStyleSheet(
            f"color: {CYAN}; background: transparent; border: none;")

        self._last_save_lbl = QLabel("", bar)
        self._last_save_lbl.setGeometry(660, 16, 360, 16)
        self._last_save_lbl.setFont(inter(11))
        self._last_save_lbl.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; border: none;")

        download = QPushButton("📥   Download PDF", bar)
        download.setGeometry(1152, 8, 156, 32)
        download.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        download.setFont(inter(12, QFont.Weight.Bold))
        download.setStyleSheet(
            f"QPushButton {{ background: {rgba(GREEN, 0.22)}; color: {GREEN}; "
            f"border: 1px solid {rgba(GREEN, 0.55)}; border-radius: 10px; }}"
            f"QPushButton:hover {{ background: {rgba(GREEN, 0.30)}; }}"
        )
        download.clicked.connect(self._on_download_pdf)
        self._download_btn = download

        self._refresh_last_save_label()

    # ── Status bar ────────────────────────────────────────────────────

    def _build_status_bar(self) -> None:
        sb = QFrame(self)
        sb.setGeometry(0, WINDOW_H - STATUS_H, WINDOW_W, STATUS_H)
        sb.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border-top: 1px solid {rgba('#ffffff', 0.06)}; }}"
        )

        x = 12
        for txt, col in (("AUTO MODE",         PURPLE),
                          ("▤ GENERATE REPORT", GREEN_LIGHT),
                          ("Live Data",         GREEN)):
            p = _StatusPill(txt, col, sb)
            p.move(x, (STATUS_H - p.height()) // 2)
            x += p.width() + 8

        ver = QLabel("v2.0.0", sb)
        ver.setGeometry(WINDOW_W - 80, 8, 60, 20)
        ver.setFont(mono(10))
        ver.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; border: none;")
        ver.setAlignment(Qt.AlignmentFlag.AlignRight
                          | Qt.AlignmentFlag.AlignVCenter)

    # ── Refresh ───────────────────────────────────────────────────────

    def _tick_clock(self) -> None:
        if hasattr(self, "_clock_lbl"):
            self._clock_lbl.setText(datetime.now().strftime("%I:%M %p"))

    def _refresh_data(self) -> None:
        """Re-pull assignments for the current date + filter, rebuild
        rows, recompute stat pills. Tracks rebuilt widgets in
        ``_row_widgets`` (incident #17) and calls .show() on each so
        rebuild on a visible parent isn't hidden."""
        rows: list[dict] = []
        try:
            if self._db is not None:
                rows = self._db.get_sotg_assignments_for_date(
                    self._report_date.isoformat())
        except Exception as exc:
            log.warning(f"get_sotg_assignments_for_date failed: {exc}")
            rows = []

        if not self._include_pending:
            rows = [r for r in rows if (r.get("status") or "").upper()
                    in ("FIRED", "MISSED")]
        self._rows_cache = rows

        # Stat counts — count from the FULL day, not the filtered slice
        try:
            full = (self._db.get_sotg_assignments_for_date(
                self._report_date.isoformat())
                    if self._db is not None else [])
        except Exception:
            full = []
        total = len(full)
        played = sum(1 for r in full
                     if (r.get("status") or "").upper() == "FIRED")
        missed = sum(1 for r in full
                     if (r.get("status") or "").upper() == "MISSED")
        self._pill_total.set_value(total)
        self._pill_played.set_value(played)
        self._pill_missed.set_value(missed)

        # Hint text: pending hidden count
        if not self._include_pending:
            hidden = total - played - missed
            if hidden > 0:
                self._hint_pending_lbl.setText(
                    f"{hidden} pending drop{'s' if hidden != 1 else ''} "
                    f"hidden — toggle \"Show pending too\" above to view.")
            else:
                self._hint_pending_lbl.setText("")
        else:
            self._hint_pending_lbl.setText(
                "Showing all statuses — toggle off to filter to "
                "PLAYED + MISSED only.")

        # Clear previous rows
        for w in self._row_widgets:
            w.setParent(None)
            w.deleteLater()
        self._row_widgets.clear()
        # Remove the stretch and re-add at end so new rows append cleanly
        # Layout has exactly one stretch item at construction time
        while self._rows_layout.count():
            item = self._rows_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

        # Build new rows
        if not rows:
            empty = QFrame(self._rows_inner)
            empty.setFixedHeight(120)
            empty.setStyleSheet(
                f"QFrame {{ background: {BG_PANEL}; "
                f"border: 1px dashed {rgba('#ffffff', 0.10)}; "
                f"border-radius: 12px; }}")
            v = QVBoxLayout(empty)
            v.setContentsMargins(0, 28, 0, 28); v.setSpacing(4)
            t = QLabel("No drops for this day", empty)
            t.setFont(inter(14, QFont.Weight.Bold))
            t.setStyleSheet(
                f"color: {TEXT_SEC}; background: transparent; border: none;")
            t.setAlignment(Qt.AlignmentFlag.AlignCenter)
            s = QLabel(
                "Try a different date, or check the Assign screen to "
                "schedule one.", empty)
            s.setFont(inter(11, QFont.Weight.Medium))
            s.setStyleSheet(
                f"color: {TEXT_MUTED}; background: transparent; "
                f"border: none;")
            s.setAlignment(Qt.AlignmentFlag.AlignCenter)
            v.addWidget(t); v.addWidget(s)
            self._rows_layout.addWidget(empty)
            empty.show()
            self._row_widgets.append(empty)
        else:
            for r in rows:
                row_w = _AssignmentRow(r, self._rows_inner)
                self._rows_layout.addWidget(row_w)
                row_w.show()
                self._row_widgets.append(row_w)

        self._rows_layout.addStretch()
        # Update last-save footer (in case midnight ran while we waited)
        self._refresh_last_save_label()

    def _refresh_last_save_label(self) -> None:
        if not hasattr(self, "_last_save_lbl"):
            return
        try:
            stamp = Settings().get("last_sotg_report_save_at", "") or ""
        except Exception:
            stamp = ""
        if stamp:
            self._last_save_lbl.setText(f"   ·    Last save: {stamp}")
        else:
            self._last_save_lbl.setText("   ·    Auto-save not yet run today")

    # ── Date controls ─────────────────────────────────────────────────

    def _on_prev_day(self) -> None:
        self._report_date -= timedelta(days=1)
        self._date_pill.set_date(self._report_date)
        self._refresh_data()

    def _on_next_day(self) -> None:
        self._report_date += timedelta(days=1)
        self._date_pill.set_date(self._report_date)
        self._refresh_data()

    def _on_today(self) -> None:
        self._report_date = ddate.today()
        self._date_pill.set_date(self._report_date)
        self._refresh_data()

    def _on_open_calendar(self) -> None:
        cal_dlg = _CalendarPopup(self._report_date, self)
        cal_dlg.date_picked.connect(self._on_calendar_picked)
        # Position below the date pill
        cal_dlg.move(self._date_pill.mapToGlobal(
            self._date_pill.rect().bottomLeft()))
        cal_dlg.show()

    def _on_calendar_picked(self, qd: QDate) -> None:
        self._report_date = ddate(qd.year(), qd.month(), qd.day())
        self._date_pill.set_date(self._report_date)
        self._refresh_data()

    def _on_toggle_pending(self, on: bool) -> None:
        self._include_pending = bool(on)
        self._refresh_data()

    # ── Download ──────────────────────────────────────────────────────

    def _on_download_pdf(self) -> None:
        from core.reports.sotg_daily_report import (
            generate_sotg_daily_report, SOTGDailyReportError,
        )
        try:
            path = generate_sotg_daily_report(
                self._report_date,
                db=self._db,
                include_pending=self._include_pending,
            )
        except SOTGDailyReportError as exc:
            QMessageBox.warning(
                self, "Generate Report",
                f"Couldn't generate the report:\n\n{exc}")
            return
        except Exception as exc:
            log.exception("PDF generation failed")
            QMessageBox.warning(
                self, "Generate Report",
                f"Unexpected error while generating the report:\n\n{exc}")
            return

        # Open with the OS default PDF handler
        try:
            os.startfile(str(path))   # type: ignore[attr-defined]
        except Exception as exc:
            log.warning(f"os.startfile failed: {exc}")
            QMessageBox.information(
                self, "Generate Report",
                f"PDF generated:\n\n{path}\n\nCouldn't open viewer "
                "automatically — open it from File Explorer.")
            return
        log.info(f"SOTG report downloaded → {path}")

    # ── External hooks ────────────────────────────────────────────────

    def refresh(self) -> None:
        """Called by MainWindow when the screen is shown — refreshes
        data + last-save label."""
        self._refresh_data()

    def set_report_date(self, d: ddate) -> None:
        self._report_date = d
        if hasattr(self, "_date_pill"):
            self._date_pill.set_date(d)
        self._refresh_data()

    def showEvent(self, e):
        super().showEvent(e)
        # Force a refresh every time the screen becomes visible — the
        # operator may have fired or missed a drop on Studio in between
        self._refresh_data()


# ════════════════════════════════════════════════════════════════════════════
# Calendar popup
# ════════════════════════════════════════════════════════════════════════════


class _CalendarPopup(QFrame):
    """Lightweight floating calendar popup. Click a day → emits
    ``date_picked(QDate)`` and closes. Themed to match SOTG family."""

    date_picked = pyqtSignal(QDate)

    def __init__(self, initial: ddate, parent=None):
        super().__init__(parent, Qt.WindowType.Popup)
        self.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border: 1px solid {rgba(CYAN, 0.40)}; border-radius: 12px; }}"
            f"QCalendarWidget {{ background: {BG_PANEL}; "
            f"color: {TEXT_PRI}; }}"
            f"QCalendarWidget QToolButton {{ color: {TEXT_PRI}; }}"
            f"QCalendarWidget QMenu {{ background: {BG_PANEL}; "
            f"color: {TEXT_PRI}; }}"
            f"QCalendarWidget QSpinBox {{ background: {BG_PANEL}; "
            f"color: {TEXT_PRI}; }}"
        )
        self.setFixedSize(320, 264)
        cal = QCalendarWidget(self)
        cal.setGeometry(0, 0, 320, 264)
        cal.setSelectedDate(QDate(initial.year, initial.month, initial.day))
        cal.setVerticalHeaderFormat(
            QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        cal.clicked.connect(self._on_picked)
        self._cal = cal

    def _on_picked(self, qd: QDate) -> None:
        self.date_picked.emit(qd)
        self.close()
