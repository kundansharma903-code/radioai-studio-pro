"""
RadioAI Studio Pro — Scheduling Hub (Figma 50:2).

Phase F3: top-level scheduling navigation. Aggregates clock count + log
status, exposes quick actions (+New / Generate / Force / View), shows a
read-only THIS WEEK day-part × day matrix, and fans out to 7 sub-screens
via navigation cards.

Layout (1440 × 1050; outer MainWindow scroll handles overflow)
--------------------------------------------------------------
  HEADER     1440 ×  72   y=  0..72
  BODY       1440 × ~940  y= 72..—
    Title block + status badges
    THIS WEEK matrix (6 day-parts × 7 days)
    7 Nav cards row
    SONG SEPARATION RULES (read-only)
    AI SCHEDULING INSIGHT (placeholder)
  STATUSBAR  1440 ×  38   pinned to bottom

═════════════════════════════════════════════════════════════════════════════
PERFORMANCE NOTES
═════════════════════════════════════════════════════════════════════════════
  1. The day-part matrix renders one QPainter pass; event.rect() clipping.
  2. Nav cards are individual widgets — there are only 7 of them, no need
     for the QPainter trick used elsewhere.
  3. NO db calls in paintEvent.
═════════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import logging
from typing import Optional

from PyQt6.QtCore import Qt, QRect, QRectF, QTimer, QPoint, pyqtSignal
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QFont, QCursor, QMouseEvent,
)
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QGridLayout, QMessageBox,
)

from ui.widgets._tokens import (
    inter, mono, rgba,
    BG_BASE, BG_DARK, BG_PANEL, BG_CARD, BG_CARD_DK, BG_ELEVATED,
    TEXT_PRI, TEXT_SEC, TEXT_MUTED, TEXT_DIM,
    CYAN, CYAN_LIGHT, PURPLE, PURPLE_LIGHT, PURPLE_DARK,
    GREEN, GREEN_LIGHT, AMBER, AMBER_LIGHT,
    RED, RED_LIGHT, PINK, PINK_LIGHT, TEAL, TEAL_LIGHT,
)

log = logging.getLogger("SchedulingHub")


# ── Layout ──────────────────────────────────────────────────────────────────

WINDOW_W   = 1440
WINDOW_H   = 1050
HEADER_H   = 72
STATUS_H   = 38

BORDER = "#1c1f38"

DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
DAY_PARTS = (
    # (label, midpoint_hour, lower-hour, upper-hour-exclusive)
    ("Night",      3,  0,  6),
    ("Morning",    8,  6, 10),
    ("Daytime",   12, 10, 14),
    ("Afternoon", 16, 14, 18),
    ("Evening",   20, 18, 22),
    ("Late Night",23, 22, 24),
)

CLOCK_PALETTE = [AMBER, CYAN, PURPLE, PINK, TEAL, GREEN, AMBER_LIGHT, PURPLE_LIGHT]


def _clock_color(clock_id: int) -> str:
    return CLOCK_PALETTE[(int(clock_id) - 1) % len(CLOCK_PALETTE)]


# ════════════════════════════════════════════════════════════════════════════
# HEADER
# ════════════════════════════════════════════════════════════════════════════

class _Header(QFrame):
    libraries_clicked = pyqtSignal()
    scheduling_active = pyqtSignal()    # no-op route since we're already here
    settings_clicked  = pyqtSignal()
    ai_magic_clicked  = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(HEADER_H)
        self.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border-bottom: 1px solid {BORDER}; }}"
        )

        self._clock_text = "00:00:00"
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick_clock)
        self._timer.start()
        self._tick_clock()

        # Top-level tabs
        for label, x, signal, active in [
            ("Libraries", 230, self.libraries_clicked, False),
            ("Scheduling", 332, self.scheduling_active, True),
            ("Settings", 432, self.settings_clicked, False),
            ("AI Magic ✦", 514, self.ai_magic_clicked, False),
        ]:
            b = QPushButton(label, self)
            b.setGeometry(x, 24, 92, 28)
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.setFont(inter(10, QFont.Weight.DemiBold if active else QFont.Weight.Medium))
            b.setStyleSheet(self._tab_qss(active=active))
            b.clicked.connect(signal.emit)

    @staticmethod
    def _tab_qss(active: bool) -> str:
        if active:
            return (
                f"QPushButton {{ background: transparent; "
                f"color: {CYAN_LIGHT}; "
                f"border: none; border-bottom: 2px solid {CYAN}; "
                f"padding: 0 12px; }}"
            )
        return (
            f"QPushButton {{ background: transparent; "
            f"color: {TEXT_SEC}; "
            f"border: none; border-bottom: 2px solid transparent; "
            f"padding: 0 12px; }}"
            f"QPushButton:hover {{ color: {TEXT_PRI}; "
            f"border-bottom: 2px solid {rgba('#ffffff', 0.20)}; }}"
        )

    def _tick_clock(self):
        from datetime import datetime
        self._clock_text = datetime.now().strftime("%H:%M:%S")
        self.update(QRect(620, 0, 220, HEADER_H))

    def paintEvent(self, _e):
        super().paintEvent(_e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Logo dot
        p.setBrush(QColor(PURPLE)); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(14, HEADER_H // 2 - 6, 12, 12)
        # RadioAI title block
        p.setPen(QColor(TEXT_PRI))
        p.setFont(inter(18, QFont.Weight.Black, letter_spacing=0.4))
        p.drawText(QRectF(75, 14, 200, 22),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "RadioAI")
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(inter(8, QFont.Weight.DemiBold, letter_spacing=1.6))
        p.drawText(QRectF(75, 36, 200, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "STUDIO PRO")
        p.setPen(QColor(TEXT_DIM))
        p.setFont(inter(7, QFont.Weight.Bold, letter_spacing=1.0))
        p.drawText(QRectF(75, 50, 200, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "BROADCAST AUTOMATION")

        # Live clock
        p.setPen(QColor(TEXT_PRI))
        p.setFont(mono(20, bold=True))
        p.drawText(QRectF(620, 14, 220, 26),
                   Qt.AlignmentFlag.AlignCenter, self._clock_text)
        from datetime import datetime
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(inter(9))
        date_text = datetime.now().strftime("%A, %d %B %Y")
        p.drawText(QRectF(620, 40, 220, 14),
                   Qt.AlignmentFlag.AlignCenter, date_text)

        # ACTIVE STATION pill
        pill = QRectF(WINDOW_W - 290, 18, 175, 36)
        p.setBrush(QColor(BG_CARD_DK)); p.setPen(QPen(QColor(BORDER), 1))
        p.drawRoundedRect(pill, 8, 8)
        p.setPen(QColor(TEXT_DIM))
        p.setFont(inter(7, QFont.Weight.Bold, letter_spacing=1.0))
        p.drawText(pill.adjusted(12, 4, -10, -20),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   "ACTIVE STATION")
        p.setPen(QColor(CYAN_LIGHT))
        p.setFont(inter(11, QFont.Weight.Bold))
        p.drawText(pill.adjusted(12, 12, -10, 0),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   "KISS FM 91.5")
        # Active dot
        p.setBrush(QColor(GREEN)); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(WINDOW_W - 130, 28, 8, 8))


# ════════════════════════════════════════════════════════════════════════════
# WEEK MATRIX (6 day-parts × 7 days)
# ════════════════════════════════════════════════════════════════════════════

class _WeekMatrix(QWidget):
    """Read-only summary of clock assignments aggregated by day-part."""

    open_part_clicked = pyqtSignal(int, int)   # (day_part_idx, day_idx)

    HEADER_ROW_H = 30
    LABEL_COL_W  = 120
    ROW_H = 70

    def __init__(self, parent=None):
        super().__init__(parent)
        self._grid: dict[tuple[int, int], int] = {}     # (day, hour) → clock_id
        self._clocks: dict[int, dict] = {}
        h = self.HEADER_ROW_H + len(DAY_PARTS) * self.ROW_H + 6
        self.setFixedHeight(h)
        self._open_links: list[tuple[int, int, QRect]] = []  # (part, day, rect)

    def set_data(self, grid: dict, clocks: list[dict]) -> None:
        self._grid = dict(grid or {})
        self._clocks = {int(c["id"]): dict(c) for c in (clocks or [])}
        self.update()

    def _cell_rect(self, day: int, part: int) -> QRect:
        cell_w = (self.width() - self.LABEL_COL_W - 8) // 7
        x = self.LABEL_COL_W + 4 + day * cell_w
        y = self.HEADER_ROW_H + part * self.ROW_H
        return QRect(x + 2, y + 2, cell_w - 4, self.ROW_H - 4)

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() != Qt.MouseButton.LeftButton:
            return
        for part, day, r in self._open_links:
            if r.contains(e.pos()):
                self.open_part_clicked.emit(part, day)
                return

    def _clock_for_part(self, day: int, part_idx: int) -> Optional[int]:
        """Return the clock assigned to the midpoint of this day-part."""
        midpoint = DAY_PARTS[part_idx][1]
        return self._grid.get((day, midpoint))

    def paintEvent(self, evt):
        super().paintEvent(evt)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        dirty = evt.rect()
        self._open_links = []

        w = self.width(); h = self.height()
        cell_w = (w - self.LABEL_COL_W - 8) // 7

        # Background
        p.setBrush(QColor(BG_CARD_DK)); p.setPen(QPen(QColor(BORDER), 1))
        p.drawRoundedRect(QRectF(0, 0, w, h - 2), 8, 8)

        # Header row — day names
        if dirty.intersects(QRect(0, 0, w, self.HEADER_ROW_H)):
            for d in range(7):
                x = self.LABEL_COL_W + 4 + d * cell_w
                weekend = d >= 5
                p.setPen(QColor(PINK if weekend else TEXT_SEC))
                p.setFont(inter(9, QFont.Weight.Black, letter_spacing=1.0))
                p.drawText(QRectF(x, 4, cell_w, self.HEADER_ROW_H - 4),
                           Qt.AlignmentFlag.AlignCenter, DAYS[d])

        # Body
        for part_idx, (label, mid, hi_lo, hi_hi) in enumerate(DAY_PARTS):
            row_y = self.HEADER_ROW_H + part_idx * self.ROW_H
            row_rect = QRect(0, row_y, w, self.ROW_H)
            if not dirty.intersects(row_rect):
                continue
            # Label cell
            p.setPen(QColor(TEXT_MUTED))
            p.setFont(mono(8, bold=False))
            p.drawText(QRectF(8, row_y + 8, self.LABEL_COL_W - 16, 14),
                       Qt.AlignmentFlag.AlignLeft,
                       f"{hi_lo:02d}:00–{hi_hi % 24:02d}:00")
            color = AMBER if part_idx == 0 else CYAN_LIGHT
            p.setPen(QColor(color))
            p.setFont(inter(11, QFont.Weight.Bold))
            p.drawText(QRectF(8, row_y + 22, self.LABEL_COL_W - 16, 22),
                       Qt.AlignmentFlag.AlignLeft, label)

            for day in range(7):
                cell = self._cell_rect(day, part_idx)
                clock_id = self._clock_for_part(day, part_idx)
                if clock_id is None:
                    p.setBrush(QColor(BG_BASE)); p.setPen(QPen(QColor(BORDER), 1))
                    p.drawRoundedRect(QRectF(cell), 4, 4)
                    p.setPen(QColor(TEXT_DIM))
                    p.setFont(inter(9))
                    p.drawText(QRectF(cell), Qt.AlignmentFlag.AlignCenter, "—")
                else:
                    clock = self._clocks.get(clock_id, {})
                    name = str(clock.get("name") or f"#{clock_id}")
                    if len(name) > 14:
                        name = name[:13] + "…"
                    color = _clock_color(clock_id)
                    body = QColor(color); body.setAlphaF(0.20)
                    p.setBrush(body); p.setPen(QPen(QColor(color), 1))
                    p.drawRoundedRect(QRectF(cell), 4, 4)
                    p.setPen(QColor(TEXT_PRI))
                    p.setFont(inter(10, QFont.Weight.DemiBold))
                    p.drawText(QRectF(cell.adjusted(8, 6, -6, -22)),
                               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                               name)
                    # Open → link
                    open_rect = QRect(cell.right() - 56, cell.bottom() - 18, 50, 14)
                    self._open_links.append((part_idx, day, open_rect))
                    p.setPen(QColor(color))
                    p.setFont(inter(8, QFont.Weight.DemiBold))
                    p.drawText(QRectF(open_rect),
                               Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                               "Open →")


# ════════════════════════════════════════════════════════════════════════════
# NAV CARD
# ════════════════════════════════════════════════════════════════════════════

class _NavCard(QFrame):

    clicked = pyqtSignal()

    def __init__(self, title: str, subtitle: str, action_label: str,
                 color: str, parent=None):
        super().__init__(parent)
        self._color = color
        self.setFixedSize(188, 110)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setStyleSheet(
            f"QFrame {{ background: {rgba(color, 0.12)}; "
            f"border: 1px solid {rgba(color, 0.32)}; "
            f"border-radius: 8px; }}"
            f"QFrame:hover {{ background: {rgba(color, 0.18)}; "
            f"border-color: {rgba(color, 0.50)}; }}"
        )
        v = QVBoxLayout(self); v.setContentsMargins(12, 10, 12, 10); v.setSpacing(2)
        # Title
        t = QLabel(title); t.setFont(inter(12, QFont.Weight.Bold))
        t.setStyleSheet(f"color: {color}; background: transparent;")
        v.addWidget(t)
        # Subtitle
        s = QLabel(subtitle); s.setFont(inter(9)); s.setWordWrap(True)
        s.setStyleSheet(f"color: {TEXT_SEC}; background: transparent;")
        v.addWidget(s)
        v.addStretch()
        # Action link
        a = QLabel(action_label + " →"); a.setFont(inter(9, QFont.Weight.DemiBold))
        a.setStyleSheet(f"color: {color}; background: transparent;")
        v.addWidget(a)

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()


# ════════════════════════════════════════════════════════════════════════════
# STATUS BAR
# ════════════════════════════════════════════════════════════════════════════

class _StatusBar(QFrame):
    settings_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(STATUS_H)
        self.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border-top: 1px solid {BORDER}; }}"
        )
        h = QHBoxLayout(self); h.setContentsMargins(14, 6, 14, 6); h.setSpacing(8)
        for label, color in [("AUTO MODE", GREEN),
                             ("AI Active", PURPLE_LIGHT),
                             ("Log Ready", CYAN_LIGHT)]:
            pill = QLabel(label); pill.setFixedHeight(22)
            pill.setFont(inter(8, QFont.Weight.Black, letter_spacing=1.4))
            pill.setStyleSheet(
                f"QLabel {{ background: {rgba(color, 0.16)}; "
                f"color: {color}; "
                f"border: 1px solid {rgba(color, 0.40)}; "
                f"border-radius: 11px; padding: 0 12px; }}"
            )
            h.addWidget(pill)
        self._clocks_pill = QLabel("0 Clocks"); self._clocks_pill.setFixedHeight(22)
        self._clocks_pill.setFont(inter(8, QFont.Weight.Black, letter_spacing=1.4))
        self._clocks_pill.setStyleSheet(
            f"QLabel {{ background: {rgba(AMBER, 0.16)}; "
            f"color: {AMBER}; "
            f"border: 1px solid {rgba(AMBER, 0.40)}; "
            f"border-radius: 11px; padding: 0 12px; }}"
        )
        h.addWidget(self._clocks_pill)
        soho = QLabel("✦ SOHO Auto"); soho.setFixedHeight(22)
        soho.setFont(inter(8, QFont.Weight.Black, letter_spacing=1.4))
        soho.setStyleSheet(
            f"QLabel {{ background: {rgba(PURPLE, 0.16)}; "
            f"color: {PURPLE_LIGHT}; "
            f"border: 1px solid {rgba(PURPLE, 0.40)}; "
            f"border-radius: 11px; padding: 0 12px; }}"
        )
        h.addWidget(soho)
        h.addStretch()
        version = QLabel("RadioAI Studio v1.0.0  ·  Built 2026")
        version.setFont(inter(9))
        version.setStyleSheet(f"color: {TEXT_DIM}; background: transparent;")
        h.addWidget(version)
        s_btn = QPushButton("Settings")
        s_btn.setFixedHeight(24); s_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        s_btn.setFont(inter(9, QFont.Weight.Bold))
        s_btn.setStyleSheet(
            f"QPushButton {{ background: {rgba(PURPLE, 0.18)}; "
            f"color: {PURPLE_LIGHT}; "
            f"border: 1px solid {rgba(PURPLE, 0.40)}; "
            f"border-radius: 5px; padding: 0 14px; }}"
            f"QPushButton:hover {{ background: {rgba(PURPLE, 0.28)}; }}"
        )
        s_btn.clicked.connect(self.settings_clicked.emit)
        h.addWidget(s_btn)

    def set_clock_count(self, n: int) -> None:
        self._clocks_pill.setText(f"{n} Clocks")


# ════════════════════════════════════════════════════════════════════════════
# SCHEDULING HUB — top-level
# ════════════════════════════════════════════════════════════════════════════

class SchedulingHub(QWidget):

    breadcrumb_clicked = pyqtSignal(str)        # 'control_panel' / 'auto_schedule' /
                                                # 'clock_editor' / 'final_log' /
                                                # 'force_clocks' / 'playlists' /
                                                # 'log_viewer' / 'rebroadcast'
    studio_clicked     = pyqtSignal()

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self._db = db
        self.setFixedSize(WINDOW_W, WINDOW_H)
        self.setStyleSheet(f"QWidget {{ background: {BG_BASE}; }}")

        self._header = _Header(self)
        self._header.setGeometry(0, 0, WINDOW_W, HEADER_H)
        self._header.libraries_clicked.connect(
            lambda: self.breadcrumb_clicked.emit("control_panel"))
        self._header.settings_clicked.connect(self._on_settings_stub)
        self._header.ai_magic_clicked.connect(self._on_ai_magic_stub)

        # Scrollable body — but we use a fixed-size single QWidget for now.
        body = QWidget(self)
        body.setGeometry(0, HEADER_H, WINDOW_W, WINDOW_H - HEADER_H - STATUS_H)
        body.setStyleSheet(f"QWidget {{ background: {BG_BASE}; }}")
        v = QVBoxLayout(body); v.setContentsMargins(40, 20, 40, 20); v.setSpacing(14)

        # Title block
        title = QLabel("Scheduling")
        title.setFont(inter(24, QFont.Weight.Black, letter_spacing=0.4))
        title.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        v.addWidget(title)
        sub = QLabel("Plan your broadcast week — clocks, playlists, logs and automation")
        sub.setFont(inter(10))
        sub.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        v.addWidget(sub)

        # Status badges row
        badges = QHBoxLayout(); badges.setSpacing(8)
        self._badge_clocks = self._badge("Clocks Built", "0", GREEN)
        self._badge_log    = self._badge("Log Ready", "—", CYAN_LIGHT)
        self._badge_auto   = self._badge("SOHO Auto", "✦", PURPLE_LIGHT)
        for b in (self._badge_clocks, self._badge_log, self._badge_auto):
            badges.addWidget(b)
        badges.addStretch()
        live = QLabel("● LIVE  21:56:15")
        live.setFont(mono(10, bold=True))
        live.setStyleSheet(
            f"QLabel {{ background: {rgba(GREEN, 0.16)}; "
            f"color: {GREEN}; "
            f"border: 1px solid {rgba(GREEN, 0.40)}; "
            f"border-radius: 11px; padding: 4px 12px; }}"
        )
        self._live_label = live
        # Update live text once a second
        self._live_timer = QTimer(self); self._live_timer.setInterval(1000)
        self._live_timer.timeout.connect(self._tick_live); self._live_timer.start()
        self._tick_live()
        badges.addWidget(live)
        v.addLayout(badges)

        # Section: THIS WEEK
        sec = QLabel("THIS WEEK — CLOCK ASSIGNMENTS")
        sec.setFont(inter(8, QFont.Weight.Black, letter_spacing=1.6))
        sec.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        v.addWidget(sec)

        # Quick-action row
        actions = QHBoxLayout(); actions.setSpacing(8)
        for label, color, signal in [
            ("+ New Clock",            CYAN_LIGHT,   self._on_new_clock),
            ("▶ Generate Today's Log", GREEN_LIGHT,  self._on_generate_log_stub),
            ("⚡ Force Clock",          AMBER,        self._on_force_clock_stub),
            ("📅 View Log",            PURPLE_LIGHT, self._on_view_log_stub),
        ]:
            b = QPushButton(label)
            b.setFixedHeight(34)
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.setFont(inter(10, QFont.Weight.DemiBold))
            b.setStyleSheet(
                f"QPushButton {{ background: {rgba(color, 0.18)}; "
                f"color: {color}; "
                f"border: 1px solid {rgba(color, 0.40)}; "
                f"border-radius: 5px; padding: 0 14px; }}"
                f"QPushButton:hover {{ background: {rgba(color, 0.28)}; }}"
            )
            b.clicked.connect(signal)
            actions.addWidget(b)
        actions.addStretch()
        v.addLayout(actions)

        # Week matrix
        self._matrix = _WeekMatrix()
        self._matrix.open_part_clicked.connect(self._on_open_part)
        v.addWidget(self._matrix)

        # Nav cards row (7 cards)
        cards = QHBoxLayout(); cards.setSpacing(10)
        self._nav_cards: dict[str, _NavCard] = {}
        for key, title_, sub_, action, color in [
            ("clock_editor", "Clock Editor",   "Build and edit rotation clocks",
             "Open Editor",  CYAN),
            ("final_log",    "Final Log",      "Generate today's broadcast log",
             "Generate Log", PURPLE_LIGHT),
            ("force_clocks", "Force Clocks",   "Override schedule for specific dates",
             "Add Override", AMBER),
            ("playlists",    "Playlists",      "Manual song sequence builder",
             "Open Playlists", CYAN),
            ("log_viewer",   "Log Viewer",     "View and edit generated logs",
             "View Logs",    PURPLE_LIGHT),
            ("rebroadcast",  "Rebroadcast",    "Replay recorded broadcasts",
             "Schedule",     RED_LIGHT),
            ("rds_settings", "RDS Settings",   "Radio Data System text config",
             "Configure",    PINK),
        ]:
            card = _NavCard(title_, sub_, action, color)
            card.clicked.connect(lambda _k=False, _key=key: self._on_card(_key))
            cards.addWidget(card)
            self._nav_cards[key] = card
        cards.addStretch()
        v.addLayout(cards)

        # SONG SEPARATION RULES (read-only)
        v.addWidget(self._build_separation_rules())
        # AI SCHEDULING INSIGHT (placeholder)
        v.addWidget(self._build_ai_insight())

        v.addStretch()

        # Status bar
        self._status = _StatusBar(self)
        self._status.setGeometry(0, WINDOW_H - STATUS_H, WINDOW_W, STATUS_H)
        self._status.settings_clicked.connect(self._on_settings_stub)

        # Initial data load
        self._refresh()
        log.info("SchedulingHub ready (Figma 50:2)")

    # ── builders ──────────────────────────────────────────────────────────

    def _badge(self, label: str, value: str, color: str) -> QFrame:
        f = QFrame()
        f.setFixedHeight(28)
        f.setStyleSheet(
            f"QFrame {{ background: {rgba(color, 0.16)}; "
            f"border: 1px solid {rgba(color, 0.40)}; "
            f"border-radius: 14px; }}"
        )
        h = QHBoxLayout(f); h.setContentsMargins(12, 0, 12, 0); h.setSpacing(6)
        txt = QLabel(f"{value}  {label}")
        txt.setFont(inter(9, QFont.Weight.DemiBold))
        txt.setStyleSheet(f"color: {color}; background: transparent;")
        h.addWidget(txt)
        f._txt = txt   # type: ignore[attr-defined]
        f._label = label
        f._color = color
        return f

    def _set_badge(self, badge: QFrame, value) -> None:
        badge._txt.setText(f"{value}  {badge._label}")  # type: ignore[attr-defined]

    def _build_separation_rules(self) -> QFrame:
        f = QFrame()
        f.setStyleSheet(
            f"QFrame {{ background: {BG_CARD}; "
            f"border: 1px solid {BORDER}; border-radius: 8px; }}"
        )
        v = QVBoxLayout(f); v.setContentsMargins(14, 10, 14, 10); v.setSpacing(6)
        h = QHBoxLayout(); h.setSpacing(0)
        title = QLabel("✓  SONG SEPARATION RULES")
        title.setFont(inter(9, QFont.Weight.Black, letter_spacing=1.4))
        title.setStyleSheet(f"color: {GREEN_LIGHT}; background: transparent;")
        h.addWidget(title); h.addStretch()
        edit_btn = QPushButton("Edit Rules")
        edit_btn.setFixedHeight(24)
        edit_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        edit_btn.setFont(inter(9, QFont.Weight.DemiBold))
        edit_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; "
            f"color: {CYAN_LIGHT}; "
            f"border: 1px solid {rgba(CYAN, 0.40)}; "
            f"border-radius: 4px; padding: 0 10px; }}"
            f"QPushButton:hover {{ background: {rgba(CYAN, 0.10)}; }}"
        )
        edit_btn.clicked.connect(self._on_edit_rules_stub)
        h.addWidget(edit_btn)
        v.addLayout(h)

        grid = QGridLayout(); grid.setSpacing(6); grid.setContentsMargins(0, 4, 0, 0)
        rules = [
            ("Same Artist",          "2 hours",    "same artist cannot play again within 2 hours"),
            ("Artist Title Separation", "1 hour",   "between same title from different artists"),
            ("Same Song",            "7 days",     "same song cannot repeat for 7 days"),
            ("Vocal Type",           "Alternate",  "alternate male/female vocals when possible"),
            ("Selection Randomness", "8 (strict)", "strict rotation, 8 = most random"),
        ]
        for i, (name, value, hint) in enumerate(rules):
            r, c = divmod(i, 2)
            cell = QHBoxLayout(); cell.setSpacing(4)
            n_lbl = QLabel(name); n_lbl.setFont(inter(9, QFont.Weight.DemiBold))
            n_lbl.setFixedWidth(190)
            n_lbl.setStyleSheet(f"color: {TEXT_SEC}; background: transparent;")
            cell.addWidget(n_lbl)
            v_lbl = QLabel(value); v_lbl.setFont(inter(9, QFont.Weight.Bold))
            v_lbl.setFixedWidth(80)
            v_lbl.setStyleSheet(
                f"QLabel {{ background: {rgba(CYAN, 0.16)}; "
                f"color: {CYAN_LIGHT}; "
                f"border: 1px solid {rgba(CYAN, 0.40)}; "
                f"border-radius: 4px; padding: 2px 8px; }}"
            )
            cell.addWidget(v_lbl)
            h_lbl = QLabel(hint); h_lbl.setFont(inter(9))
            h_lbl.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
            cell.addWidget(h_lbl, 1)
            cell_w = QWidget(); cell_w.setLayout(cell)
            cell_w.setStyleSheet("background: transparent;")
            grid.addWidget(cell_w, r, c)
        v.addLayout(grid)
        return f

    def _build_ai_insight(self) -> QFrame:
        f = QFrame()
        f.setStyleSheet(
            f"QFrame {{ background: {rgba(PURPLE, 0.10)}; "
            f"border: 1px solid {rgba(PURPLE, 0.36)}; "
            f"border-radius: 8px; }}"
        )
        h = QHBoxLayout(f); h.setContentsMargins(14, 10, 14, 10); h.setSpacing(8)
        title = QLabel("✦  AI SCHEDULING INSIGHT")
        title.setFont(inter(9, QFont.Weight.Black, letter_spacing=1.4))
        title.setStyleSheet(f"color: {PURPLE_LIGHT}; background: transparent;")
        h.addWidget(title)
        body = QLabel("Phase E — Anthropic Claude integration. "
                      "Will analyze rotation health + suggest fixes for "
                      "category gaps and energy distribution.")
        body.setFont(inter(9))
        body.setStyleSheet(f"color: {TEXT_SEC}; background: transparent;")
        body.setWordWrap(True)
        h.addWidget(body, 1)
        fix_btn = QPushButton("Phase E ✦")
        fix_btn.setFixedHeight(28)
        fix_btn.setFont(inter(9, QFont.Weight.DemiBold))
        fix_btn.setEnabled(False)
        fix_btn.setStyleSheet(
            f"QPushButton {{ background: {rgba(PURPLE, 0.16)}; "
            f"color: {PURPLE_LIGHT}; "
            f"border: 1px solid {rgba(PURPLE, 0.40)}; "
            f"border-radius: 5px; padding: 0 12px; }}"
        )
        h.addWidget(fix_btn)
        return f

    # ── data refresh ──────────────────────────────────────────────────────

    def _refresh(self) -> None:
        try:
            clocks = [dict(r) for r in self._db.get_all_clocks()]
        except Exception as exc:
            log.warning(f"clocks load failed: {exc}")
            clocks = []
        try:
            grid = self._db.get_auto_schedule_grid()
        except Exception as exc:
            log.warning(f"grid load failed: {exc}")
            grid = {}
        self._set_badge(self._badge_clocks, str(len(clocks)))
        self._set_badge(self._badge_log, "Today" if grid else "—")
        self._matrix.set_data(grid, clocks)
        self._status.set_clock_count(len(clocks))

    def _tick_live(self):
        from datetime import datetime
        self._live_label.setText(
            f"●  LIVE  {datetime.now().strftime('%H:%M:%S')}")

    # ── handlers ──────────────────────────────────────────────────────────

    def _on_card(self, key: str) -> None:
        # F2 (clock_editor) is real — others are stubs until P5 lands them.
        if key == "clock_editor":
            self.breadcrumb_clicked.emit("clock_editor")
            return
        # Phase F4-F8 stubs / Phase G (RDS Settings)
        target = {
            "final_log":    "final_log",
            "force_clocks": "force_clocks",
            "playlists":    "playlists",
            "log_viewer":   "log_viewer",
            "rebroadcast":  "rebroadcast",
            "rds_settings": "rds_settings",
        }.get(key)
        if target is None:
            return
        self.breadcrumb_clicked.emit(target)

    def _on_open_part(self, part_idx: int, day_idx: int) -> None:
        """Day-part matrix Open → link → jump to F1 Auto Schedule."""
        log.info(f"[hub] open part_idx={part_idx} day={day_idx} → auto_schedule")
        self.breadcrumb_clicked.emit("auto_schedule")

    def _on_new_clock(self) -> None:
        try:
            self._db.create_clock("New Clock")
            log.info("[hub] created new clock — opening Clock Editor")
        except Exception as exc:
            log.warning(f"create_clock failed: {exc}")
        self.breadcrumb_clicked.emit("clock_editor")

    def _on_generate_log_stub(self) -> None:
        QMessageBox.information(
            self, "Generate Today's Log",
            "Generate Log — Phase E (Anthropic Claude AI integration).\n\n"
            "Will compose tomorrow's full broadcast log from this week's "
            "clock assignments + separation rules + category health.")

    def _on_force_clock_stub(self) -> None:
        self.breadcrumb_clicked.emit("force_clocks")

    def _on_view_log_stub(self) -> None:
        self.breadcrumb_clicked.emit("log_viewer")

    def _on_edit_rules_stub(self) -> None:
        QMessageBox.information(
            self, "Edit Separation Rules",
            "Edit Rules — Phase F polish.\n\nThe rules above are read-only "
            "for now. Editing requires per-clock + global rule storage.")

    def _on_settings_stub(self) -> None:
        QMessageBox.information(
            self, "Settings",
            "Settings — Phase G.\n\nGlobal application preferences.")

    def _on_ai_magic_stub(self) -> None:
        QMessageBox.information(
            self, "AI Magic",
            "AI Magic — Phase E.\n\nAnthropic Claude integration for "
            "scheduling, rotation health, and creative copy generation.")
