"""
RadioAI — Log Viewer (Figma 64:533). Phase F5 stub.

Read-only broadcast_log browser with date filter. Displays the most
recent broadcast plays plus an entry-detail panel on the right.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QCursor, QFont
from core import dialogs
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QMessageBox,
)

from ui.widgets._phase_stub import StubHeader, StubStatusBar, BORDER
from ui.widgets._tokens import (
    inter, mono, rgba,
    BG_BASE, BG_DARK, BG_PANEL, BG_CARD_DK,
    TEXT_PRI, TEXT_SEC, TEXT_MUTED, TEXT_DIM,
    CYAN, CYAN_LIGHT, PURPLE_LIGHT, GREEN, GREEN_LIGHT, AMBER, RED_LIGHT, PINK,
)

log = logging.getLogger("LogViewer")

WINDOW_W = 1440; WINDOW_H = 900
HEADER_H = 72; STATUS_H = 36
LEFT_W = 200; RIGHT_W = 280
CENTER_W = WINDOW_W - LEFT_W - RIGHT_W
CONTENT_Y = HEADER_H
CONTENT_H = WINDOW_H - HEADER_H - STATUS_H


class LogViewer(QWidget):
    breadcrumb_clicked = pyqtSignal(str)
    studio_clicked     = pyqtSignal()

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self._db = db
        self.setFixedSize(WINDOW_W, WINDOW_H)
        self.setStyleSheet(f"QWidget {{ background: {BG_BASE}; }}")

        h = StubHeader("Log Viewer", "Log Viewer",
                       active_color=CYAN_LIGHT, parent=self)
        h.setGeometry(0, 0, WINDOW_W, HEADER_H)
        h.control_panel_clicked.connect(
            lambda: self.breadcrumb_clicked.emit("control_panel"))
        h.scheduling_clicked.connect(
            lambda: self.breadcrumb_clicked.emit("scheduling_hub"))
        h.studio_clicked.connect(self.studio_clicked.emit)

        # Left — saved logs list (one row per recent date)
        left = QFrame(self)
        left.setGeometry(0, CONTENT_Y, LEFT_W, CONTENT_H)
        left.setStyleSheet(
            f"QFrame {{ background: {BG_DARK}; "
            f"border-right: 1px solid {BORDER}; }}"
        )
        lv = QVBoxLayout(left); lv.setContentsMargins(10, 14, 10, 14); lv.setSpacing(6)
        lbl = QLabel("SAVED LOGS")
        lbl.setFont(inter(8, QFont.Weight.Black, letter_spacing=1.6))
        lbl.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        lv.addWidget(lbl)
        # Pull date list from broadcast_log
        try:
            rows = db._conn().execute(
                "SELECT date(played_at) AS d, COUNT(*) AS n "
                "FROM broadcast_log GROUP BY d ORDER BY d DESC LIMIT 10"
            ).fetchall()
        except Exception:
            rows = []
        if not rows:
            empty = QLabel("(no broadcast log yet)")
            empty.setFont(inter(9))
            empty.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
            lv.addWidget(empty)
        for i, r in enumerate(rows):
            d = str(r["d"] or "")
            n = int(r["n"] or 0)
            row = QFrame(); row.setFixedHeight(36)
            bg = rgba(GREEN_LIGHT, 0.16) if i == 0 else BG_CARD_DK
            border = rgba(GREEN_LIGHT, 0.40) if i == 0 else BORDER
            row.setStyleSheet(
                f"QFrame {{ background: {bg}; "
                f"border: 1px solid {border}; border-radius: 5px; }}"
            )
            rh = QHBoxLayout(row); rh.setContentsMargins(8, 0, 8, 0)
            d_lbl = QLabel(d); d_lbl.setFont(inter(10, QFont.Weight.DemiBold))
            d_lbl.setStyleSheet(
                f"color: {GREEN_LIGHT if i == 0 else TEXT_SEC}; "
                f"background: transparent;")
            rh.addWidget(d_lbl); rh.addStretch()
            tag = QLabel(f"{n} entries"); tag.setFont(mono(8, bold=False))
            tag.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
            rh.addWidget(tag)
            lv.addWidget(row)
        lv.addStretch()

        # Center — log entries
        center = QFrame(self)
        center.setGeometry(LEFT_W, CONTENT_Y, CENTER_W, CONTENT_H)
        center.setStyleSheet(f"QFrame {{ background: {BG_BASE}; "
                             f"border-right: 1px solid {BORDER}; }}")
        cv = QVBoxLayout(center); cv.setContentsMargins(20, 14, 20, 14); cv.setSpacing(8)
        title = QLabel(
            f"LOG — {datetime.now().strftime('%A %d %B %Y')}  🔒 LOCKED")
        title.setFont(inter(13, QFont.Weight.Black, letter_spacing=0.6))
        title.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        cv.addWidget(title)
        sub = QLabel("Filter:  All  Songs  Spots  Jingles  Breaks")
        sub.setFont(inter(9))
        sub.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        cv.addWidget(sub)
        # Entries
        self._list = QListWidget()
        self._list.setStyleSheet(
            f"QListWidget {{ background: {BG_CARD_DK}; "
            f"color: {TEXT_PRI}; "
            f"border: 1px solid {BORDER}; "
            f"border-radius: 6px; padding: 4px; }}"
            f"QListWidget::item {{ padding: 4px; }}"
        )
        try:
            recent = list(db.get_history(limit=30))
        except Exception:
            recent = []
        if not recent:
            self._list.addItem(QListWidgetItem(
                "  No broadcast_log entries — start the scheduler in Studio "
                "to generate live air log."))
        for r in recent:
            time_part = (str(r["played_at"]) or "").split(" ")[-1][:8]
            kind = (r["entry_type"] or "—").upper()
            artist = r["artist"] if "artist" in r.keys() else ""
            title_t = r["title"] if "title" in r.keys() else ""
            item = QListWidgetItem(
                f"  {time_part}   {kind:<6}  {artist or '—':<30} {title_t or ''}")
            self._list.addItem(item)
        cv.addWidget(self._list, 1)

        bot = QHBoxLayout()
        bot.addWidget(self._mini_btn("Export", CYAN_LIGHT))
        bot.addWidget(self._mini_btn("Print", PURPLE_LIGHT))
        bot.addStretch()
        cv.addLayout(bot)

        # Right — entry detail
        right = QFrame(self)
        right.setGeometry(LEFT_W + CENTER_W, CONTENT_Y, RIGHT_W, CONTENT_H)
        right.setStyleSheet(f"QFrame {{ background: {BG_PANEL}; }}")
        rv = QVBoxLayout(right); rv.setContentsMargins(14, 14, 14, 14); rv.setSpacing(8)
        rv.addWidget(self._section("ENTRY DETAIL", PURPLE_LIGHT))
        rv.addWidget(self._kv("Scheduled",  "—"))
        rv.addWidget(self._kv("Actual Play", "—"))
        rv.addWidget(self._kv("Variance",   "—"))
        rv.addWidget(self._kv("Duration",   "—"))
        rv.addWidget(self._kv("Category",   "—"))
        rv.addWidget(self._kv("BPM",        "—"))
        rv.addWidget(self._kv("Energy",     "—"))
        rv.addWidget(self._kv("Last Played", "—"))
        rv.addStretch()

        sb = StubStatusBar("Log Viewer", parent=self)
        sb.setGeometry(0, WINDOW_H - STATUS_H, WINDOW_W, STATUS_H)

        log.info("LogViewer ready (Figma 64:533)")

    def _section(self, text, color):
        lbl = QLabel(text)
        lbl.setFont(inter(8, QFont.Weight.Black, letter_spacing=1.6))
        lbl.setStyleSheet(f"color: {color}; background: transparent;")
        return lbl

    def _kv(self, k, v):
        f = QFrame(); f.setFixedHeight(34)
        f.setStyleSheet(f"QFrame {{ background: {BG_CARD_DK}; "
                        f"border: 1px solid {BORDER}; border-radius: 5px; }}")
        v_l = QVBoxLayout(f); v_l.setContentsMargins(10, 4, 10, 4); v_l.setSpacing(0)
        c = QLabel(k); c.setFont(inter(7, QFont.Weight.Medium, letter_spacing=0.6))
        c.setStyleSheet(f"color: {TEXT_DIM}; background: transparent;")
        d = QLabel(v); d.setFont(inter(10, QFont.Weight.Medium))
        d.setStyleSheet(f"color: {TEXT_SEC}; background: transparent;")
        v_l.addWidget(c); v_l.addWidget(d)
        return f

    def _mini_btn(self, label, color):
        b = QPushButton(label); b.setFixedHeight(28)
        b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        b.setFont(inter(9, QFont.Weight.DemiBold))
        b.setStyleSheet(
            f"QPushButton {{ background: {rgba(color, 0.18)}; "
            f"color: {color}; "
            f"border: 1px solid {rgba(color, 0.40)}; "
            f"border-radius: 4px; padding: 0 14px; }}"
            f"QPushButton:hover {{ background: {rgba(color, 0.28)}; }}"
        )
        b.clicked.connect(lambda: dialogs.info(
            self, label, f"{label} — Phase F polish."))
        return b
