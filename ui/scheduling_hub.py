"""
RadioAI Studio Pro — Scheduling Hub (ref 225:3, Jazler-style).

Phase F-Final follow-up: stripped to a pure 7-tile navigation grid that
matches the actual radio-software paradigm. The previous version
(50:2) had a week-assignment matrix + status badges + AI Insight + song
separation rules — all moved out (week matrix lives in F1; rules / AI
are Phase F polish + Phase E territory).

Layout (1440 × 900)
-------------------
  HEADER     1440 ×  72   y=  0..72   — RadioAI brand + 4-tab top nav
  BODY       1440 × ~786  y= 72..858  — title block + 7-tile grid + footer
  STATUSBAR  1440 ×  42   y=858..900

═════════════════════════════════════════════════════════════════════════════
PERFORMANCE NOTES
═════════════════════════════════════════════════════════════════════════════
  Just a static layout — no custom paint surfaces. All children are
  standard QWidgets, no QPainter event clipping required.
═════════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import logging
from typing import Optional

from PyQt6.QtCore import Qt, QRect, QRectF, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QFont, QCursor, QMouseEvent,
)
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QGridLayout,
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
WINDOW_H   = 900
HEADER_H   = 72
STATUS_H   = 42

BORDER = "#1c1f38"


# ── 7-tile spec (matches ref 225:3 — Jazler nav grid) ───────────────────────

# (key, title, glyph, color)
TILE_SPEC = [
    ("playlists",     "Playlists",              "▤",  CYAN_LIGHT),
    ("final_log",     "Final Log Creator",      "📋", PURPLE_LIGHT),
    ("auto_schedule", "Main Auto Schedule",     "⚙",  AMBER),
    ("force_clocks",  "Force Clocks Schedule",  "⚡", AMBER_LIGHT),
    ("rebroadcast",   "Rebroadcast Schedule",   "↻",  RED_LIGHT),
    ("rds_settings",  "RDS",                    "📡", PINK),
    ("log_viewer",    "Log Viewer",             "📜", CYAN),
]


# ════════════════════════════════════════════════════════════════════════════
# HEADER — Libraries / Scheduling (active) / Settings / Utilities
# ════════════════════════════════════════════════════════════════════════════

class _Header(QFrame):
    libraries_clicked = pyqtSignal()
    settings_clicked  = pyqtSignal()
    utilities_clicked = pyqtSignal()

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

        # Top-level tabs: Libraries / Scheduling (active) / Settings / Utilities
        for label, x, signal, active in [
            ("Libraries",  230, self.libraries_clicked, False),
            ("Scheduling", 332, None,                   True),
            ("Settings",   432, self.settings_clicked,  False),
            ("Utilities",  514, self.utilities_clicked, False),
        ]:
            b = QPushButton(label, self)
            b.setGeometry(x, 24, 92, 28)
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.setFont(inter(10, QFont.Weight.DemiBold if active
                                else QFont.Weight.Medium))
            b.setStyleSheet(self._tab_qss(active=active))
            if signal is not None:
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
# NAV TILE — pictorial icon + label, no description, no preview data
# ════════════════════════════════════════════════════════════════════════════

class _NavTile(QFrame):
    clicked = pyqtSignal()

    def __init__(self, title: str, glyph: str, color: str, parent=None):
        super().__init__(parent)
        self._color = color
        self._glyph = glyph
        self._title = title
        self.setFixedSize(280, 200)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setStyleSheet(
            f"QFrame {{ background: {rgba(color, 0.10)}; "
            f"border: 1px solid {rgba(color, 0.32)}; "
            f"border-radius: 12px; }}"
            f"QFrame:hover {{ background: {rgba(color, 0.18)}; "
            f"border-color: {rgba(color, 0.60)}; }}"
        )

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def paintEvent(self, _e):
        super().paintEvent(_e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Big pictorial glyph centered upper-area
        p.setPen(QColor(self._color))
        p.setFont(inter(54, QFont.Weight.Black))
        p.drawText(QRectF(0, 30, self.width(), 90),
                   Qt.AlignmentFlag.AlignCenter, self._glyph)

        # Label centered below glyph
        p.setPen(QColor(TEXT_PRI))
        p.setFont(inter(13, QFont.Weight.Bold, letter_spacing=0.3))
        p.drawText(QRectF(0, 134, self.width(), 28),
                   Qt.AlignmentFlag.AlignCenter, self._title)

        # Faint accent line under label
        accent_y = 168
        p.setPen(QPen(QColor(self._color), 2))
        p.drawLine(self.width() // 2 - 16, accent_y,
                   self.width() // 2 + 16, accent_y)


# ════════════════════════════════════════════════════════════════════════════
# STUDIO LAUNCHER — body bottom-right card (per ref 225:3)
# ════════════════════════════════════════════════════════════════════════════

class _StudioLauncher(QFrame):
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(320, 90)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setStyleSheet(
            f"QFrame {{ background: qlineargradient("
            f"x1:0,y1:0,x2:1,y2:0, stop:0 {PURPLE_DARK}, "
            f"stop:1 {PURPLE_LIGHT}); "
            f"border-radius: 10px; }}"
            f"QFrame:hover {{ background: qlineargradient("
            f"x1:0,y1:0,x2:1,y2:0, stop:0 {PURPLE}, "
            f"stop:1 #c4b5fd); }}"
        )

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def paintEvent(self, _e):
        super().paintEvent(_e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QColor("#ffffff"))
        p.setFont(inter(11, QFont.Weight.DemiBold, letter_spacing=1.4))
        p.drawText(QRectF(20, 18, self.width() - 40, 18),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "▶  OPEN STUDIO")
        p.setPen(QColor("#ffffff"))
        p.setFont(inter(9))
        p.drawText(QRectF(20, 40, self.width() - 40, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "Live broadcast workstation")
        p.setPen(QColor(rgba("#ffffff", 0.70)))
        p.setFont(inter(8, QFont.Weight.Medium, letter_spacing=0.6))
        p.drawText(QRectF(20, 58, self.width() - 40, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "Press F9 anywhere · Quick deck access")


# ════════════════════════════════════════════════════════════════════════════
# STATUS BAR — single status string + version (per ref 225:3)
# ════════════════════════════════════════════════════════════════════════════

class _StatusBar(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(STATUS_H)
        self.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border-top: 1px solid {BORDER}; }}"
        )
        h = QHBoxLayout(self); h.setContentsMargins(20, 8, 20, 8); h.setSpacing(10)
        # Live status indicator dot
        self._status_dot = QLabel("●"); self._status_dot.setFont(inter(13, QFont.Weight.Bold))
        self._status_dot.setStyleSheet(f"color: {GREEN}; background: transparent;")
        h.addWidget(self._status_dot)
        self._status_text = QLabel("Everything running smoothly. No problems.")
        self._status_text.setFont(inter(10))
        self._status_text.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent;")
        h.addWidget(self._status_text)
        h.addStretch()
        version = QLabel("RadioAI Studio v1.0.0")
        version.setFont(inter(9))
        version.setStyleSheet(f"color: {TEXT_DIM}; background: transparent;")
        h.addWidget(version)

    def set_status(self, msg: str, ok: bool = True) -> None:
        self._status_text.setText(msg)
        self._status_dot.setStyleSheet(
            f"color: {GREEN if ok else RED}; background: transparent;")


# ════════════════════════════════════════════════════════════════════════════
# SCHEDULING HUB — top-level
# ════════════════════════════════════════════════════════════════════════════

class SchedulingHub(QWidget):

    breadcrumb_clicked = pyqtSignal(str)
    studio_clicked     = pyqtSignal()

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self._db = db
        self.setFixedSize(WINDOW_W, WINDOW_H)
        self.setStyleSheet(f"QWidget {{ background: {BG_BASE}; }}")

        # Header
        self._header = _Header(self)
        self._header.setGeometry(0, 0, WINDOW_W, HEADER_H)
        self._header.libraries_clicked.connect(
            lambda: self.breadcrumb_clicked.emit("control_panel"))
        self._header.settings_clicked.connect(self._on_settings_stub)
        self._header.utilities_clicked.connect(self._on_utilities_stub)

        # Body container
        body = QWidget(self)
        body.setGeometry(0, HEADER_H, WINDOW_W, WINDOW_H - HEADER_H - STATUS_H)
        body.setStyleSheet(f"QWidget {{ background: {BG_BASE}; }}")

        # Title block
        title = QLabel("Scheduling", body)
        title.setGeometry(40, 18, 400, 44)
        title.setFont(inter(26, QFont.Weight.Black, letter_spacing=0.4))
        title.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")

        sub = QLabel("Plan rotation, build clocks, generate the daily log.", body)
        sub.setGeometry(40, 60, 700, 18)
        sub.setFont(inter(10))
        sub.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

        # 7-tile grid: 4 across × 2 rows (last row has 3 tiles + studio launcher)
        grid_y = 110
        tile_w, tile_h = 280, 200
        gap_x, gap_y = 24, 24
        total_grid_w = 4 * tile_w + 3 * gap_x       # 1192
        grid_x = (WINDOW_W - total_grid_w) // 2     # centered
        # Studio launcher card sits in the second row, fourth column slot
        # (last position of the 8-cell grid layout — replaces what would
        # have been an 8th tile).
        self._tiles: dict[str, _NavTile] = {}
        for i, (key, title_, glyph, color) in enumerate(TILE_SPEC):
            row = i // 4
            col = i % 4
            x = grid_x + col * (tile_w + gap_x)
            y = grid_y + row * (tile_h + gap_y)
            tile = _NavTile(title_, glyph, color, body)
            tile.setGeometry(x, y, tile_w, tile_h)
            tile.clicked.connect(
                lambda _k=False, _key=key: self._on_tile_clicked(_key))
            self._tiles[key] = tile

        # Studio launcher in the empty 8th cell (row 2, col 4)
        launcher_x = grid_x + 3 * (tile_w + gap_x)
        launcher_y = grid_y + 1 * (tile_h + gap_y) + (tile_h - 90) // 2
        self._launcher = _StudioLauncher(body)
        self._launcher.setGeometry(launcher_x, launcher_y, 320, 90)
        self._launcher.clicked.connect(self.studio_clicked.emit)

        # Status bar
        self._status = _StatusBar(self)
        self._status.setGeometry(0, WINDOW_H - STATUS_H, WINDOW_W, STATUS_H)

        log.info("SchedulingHub ready (ref 225:3 — 7-tile nav)")

    # ── handlers ──────────────────────────────────────────────────────────

    def _on_tile_clicked(self, key: str) -> None:
        # Map tile key → MainWindow route (existing screens / stubs)
        target = {
            "auto_schedule": "auto_schedule",
            "final_log":     "final_log",
            "force_clocks":  "force_clocks",
            "playlists":     "playlists",
            "log_viewer":    "log_viewer",
            "rebroadcast":   "rebroadcast",
            "rds_settings":  "rds_settings",
        }.get(key)
        if target:
            self.breadcrumb_clicked.emit(target)

    def _on_settings_stub(self):
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.information(
            self, "Settings",
            "Settings — Phase G.\n\nGlobal application preferences.")

    def _on_utilities_stub(self):
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.information(
            self, "Utilities",
            "Utilities — Phase G.\n\nDB tools, log inspector, "
            "import/export.")
