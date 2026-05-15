"""
RadioAI — Rebroadcast Schedule (Figma 65:2). Phase F8 stub.

Replay-recorded broadcast scheduling skeleton. No DB table yet — list is
in-memory placeholder. Actual recording + replay scheduling = Phase F polish.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QCursor, QFont
from core import dialogs
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QMessageBox,
)

from ui.widgets._phase_stub import StubHeader, StubStatusBar, BORDER
from ui.widgets._tokens import (
    inter, mono, rgba,
    BG_BASE, BG_DARK, BG_PANEL, BG_CARD_DK,
    TEXT_PRI, TEXT_SEC, TEXT_MUTED, TEXT_DIM,
    CYAN, CYAN_LIGHT, PURPLE, PURPLE_LIGHT,
    GREEN, GREEN_LIGHT, AMBER, RED, RED_LIGHT, PINK,
)

log = logging.getLogger("Rebroadcast")

WINDOW_W = 1440; WINDOW_H = 900
HEADER_H = 72; STATUS_H = 36
LEFT_W = 240; RIGHT_W = 300
CENTER_W = WINDOW_W - LEFT_W - RIGHT_W
CONTENT_Y = HEADER_H
CONTENT_H = WINDOW_H - HEADER_H - STATUS_H


class Rebroadcast(QWidget):
    breadcrumb_clicked = pyqtSignal(str)
    studio_clicked     = pyqtSignal()

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self._db = db
        self.setFixedSize(WINDOW_W, WINDOW_H)
        self.setStyleSheet(f"QWidget {{ background: {BG_BASE}; }}")

        h = StubHeader("Rebroadcast", "Rebroadcast Schedule",
                       active_color=RED_LIGHT, parent=self)
        h.setGeometry(0, 0, WINDOW_W, HEADER_H)
        h.control_panel_clicked.connect(
            lambda: self.breadcrumb_clicked.emit("control_panel"))
        h.scheduling_clicked.connect(
            lambda: self.breadcrumb_clicked.emit("scheduling_hub"))
        h.studio_clicked.connect(self.studio_clicked.emit)

        # Left — list of rebroadcast jobs (in-memory placeholder)
        left = QFrame(self)
        left.setGeometry(0, CONTENT_Y, LEFT_W, CONTENT_H)
        left.setStyleSheet(f"QFrame {{ background: {BG_DARK}; "
                           f"border-right: 1px solid {BORDER}; }}")
        lv = QVBoxLayout(left); lv.setContentsMargins(10, 14, 10, 14); lv.setSpacing(6)
        head_row = QHBoxLayout()
        title = QLabel("REBROADCASTS")
        title.setFont(inter(8, QFont.Weight.Black, letter_spacing=1.4))
        title.setStyleSheet(f"color: {RED_LIGHT}; background: transparent;")
        head_row.addWidget(title); head_row.addStretch()
        sched = QPushButton("+ Schedule"); sched.setFixedHeight(24)
        sched.setFont(inter(9, QFont.Weight.DemiBold))
        sched.setStyleSheet(
            f"QPushButton {{ background: {rgba(GREEN, 0.16)}; "
            f"color: {GREEN_LIGHT}; "
            f"border: 1px solid {rgba(GREEN, 0.40)}; "
            f"border-radius: 4px; padding: 0 8px; }}"
        )
        sched.clicked.connect(self._on_schedule_stub)
        head_row.addWidget(sched)
        lv.addLayout(head_row)

        # Empty state
        empty = QLabel("(no scheduled rebroadcasts yet)\n\n"
                       "+ Schedule to record a live show window and "
                       "replay it later.")
        empty.setFont(inter(9)); empty.setWordWrap(True)
        empty.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        lv.addWidget(empty)
        lv.addStretch()
        for label, color in [("✎ Edit", AMBER),
                             ("✗ Cancel", RED_LIGHT),
                             ("▶ Preview", CYAN_LIGHT)]:
            lv.addWidget(self._action_btn(label, color))

        # Center — schedule form
        center = QFrame(self)
        center.setGeometry(LEFT_W, CONTENT_Y, CENTER_W, CONTENT_H)
        center.setStyleSheet(f"QFrame {{ background: {BG_BASE}; "
                             f"border-right: 1px solid {BORDER}; }}")
        cv = QVBoxLayout(center); cv.setContentsMargins(20, 14, 20, 14); cv.setSpacing(8)
        cv.addWidget(self._section("NEW REBROADCAST SCHEDULE", PINK))
        sub = QLabel("Record a live window and schedule it to replay at a "
                     "future time")
        sub.setFont(inter(9))
        sub.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        cv.addWidget(sub)

        # Step 1
        cv.addWidget(self._section("STEP 1 — SELECT RECORDING", RED_LIGHT))
        for k, v in [("Recording Name", "—"),
                     ("Record From",    "—"), ("Record To", "—"),
                     ("Audio Source",   "Output 1 — Main On-Air Feed")]:
            cv.addWidget(self._kv(k, v))
        # Recording status (placeholder)
        rec = QLabel("● Recording: not started")
        rec.setFont(inter(10, QFont.Weight.DemiBold))
        rec.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        cv.addWidget(rec)

        cv.addWidget(self._section("STEP 2 — SCHEDULE REPLAY", RED_LIGHT))
        for k, v in [("Replay Date", "—"), ("Replay Time", "—"),
                     ("Override Active Clock?", "—"),
                     ("Include Commercial Breaks?", "—"),
                     ("Adjust for time offset?", "—")]:
            cv.addWidget(self._kv(k, v))

        # Bottom action row
        bot = QHBoxLayout(); bot.setSpacing(8)
        s = QPushButton("● Schedule Rebroadcast"); s.setFixedHeight(36)
        s.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        s.setFont(inter(11, QFont.Weight.Bold))
        s.setStyleSheet(
            f"QPushButton {{ background: {rgba(RED, 0.24)}; "
            f"color: {RED_LIGHT}; "
            f"border: 1px solid {rgba(RED, 0.50)}; "
            f"border-radius: 6px; padding: 0 18px; }}"
            f"QPushButton:hover {{ background: {rgba(RED, 0.36)}; }}"
        )
        s.clicked.connect(self._on_schedule_stub)
        bot.addWidget(s)
        p = QPushButton("▶ Preview Recording"); p.setFixedHeight(36)
        p.setFont(inter(11, QFont.Weight.DemiBold))
        p.setStyleSheet(
            f"QPushButton {{ background: transparent; "
            f"color: {TEXT_SEC}; "
            f"border: 1px solid {BORDER}; "
            f"border-radius: 6px; padding: 0 18px; }}"
        )
        p.clicked.connect(lambda: dialogs.info(
            self, "Preview", "Preview Recording — Phase F polish."))
        bot.addWidget(p)
        bot.addStretch()
        cv.addLayout(bot)
        cv.addStretch()

        # Right — How It Works (instructional)
        right = QFrame(self)
        right.setGeometry(LEFT_W + CENTER_W, CONTENT_Y, RIGHT_W, CONTENT_H)
        right.setStyleSheet(f"QFrame {{ background: {BG_PANEL}; }}")
        rv = QVBoxLayout(right); rv.setContentsMargins(14, 14, 14, 14); rv.setSpacing(8)
        rv.addWidget(self._section("HOW IT WORKS", PURPLE_LIGHT))
        for n, (label, color, body) in enumerate([
            ("Record",    AMBER,        "System records the live audio "
                                        "feed during the set window."),
            ("Store",     PURPLE_LIGHT, "Saved as WAV in the recordings "
                                        "folder."),
            ("Schedule",  CYAN_LIGHT,   "Set the future date and time."),
            ("Auto-Play", GREEN,        "Suspends the clock and plays back "
                                        "automatically."),
            ("Resume",    PINK,         "Regular clock scheduling resumes "
                                        "after the recording ends."),
        ], start=1):
            rv.addWidget(self._step(n, label, color, body))
        rv.addStretch()
        ai = QLabel("✦ AI strips time stings and regenerates them for the "
                    "replay time automatically.")
        ai.setFont(inter(9)); ai.setWordWrap(True)
        ai.setStyleSheet(
            f"QLabel {{ background: {rgba(PURPLE, 0.14)}; "
            f"color: {PURPLE_LIGHT}; "
            f"border: 1px solid {rgba(PURPLE, 0.40)}; "
            f"border-radius: 5px; padding: 8px; }}"
        )
        rv.addWidget(ai)

        sb = StubStatusBar("Rebroadcast Schedule", parent=self)
        sb.setGeometry(0, WINDOW_H - STATUS_H, WINDOW_W, STATUS_H)

        log.info("Rebroadcast ready (Figma 65:2)")

    def _section(self, text, color):
        lbl = QLabel(text)
        lbl.setFont(inter(8, QFont.Weight.Black, letter_spacing=1.4))
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

    def _step(self, n, label, color, body):
        f = QFrame(); f.setFixedHeight(54)
        f.setStyleSheet(
            f"QFrame {{ background: {rgba(color, 0.10)}; "
            f"border-left: 3px solid {color}; "
            f"border-radius: 4px; }}"
        )
        h = QHBoxLayout(f); h.setContentsMargins(8, 4, 8, 4); h.setSpacing(8)
        num = QLabel(str(n)); num.setFixedWidth(20)
        num.setFont(inter(13, QFont.Weight.Black))
        num.setStyleSheet(f"color: {color}; background: transparent;")
        h.addWidget(num)
        col = QVBoxLayout(); col.setSpacing(0)
        t = QLabel(label); t.setFont(inter(10, QFont.Weight.Bold))
        t.setStyleSheet(f"color: {color}; background: transparent;")
        b = QLabel(body); b.setFont(inter(8)); b.setWordWrap(True)
        b.setStyleSheet(f"color: {TEXT_SEC}; background: transparent;")
        col.addWidget(t); col.addWidget(b)
        h.addLayout(col, 1)
        return f

    def _action_btn(self, label, color):
        b = QPushButton(label); b.setFixedHeight(28)
        b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        b.setFont(inter(10, QFont.Weight.DemiBold))
        b.setStyleSheet(
            f"QPushButton {{ background: {rgba(color, 0.18)}; "
            f"color: {color}; "
            f"border: 1px solid {rgba(color, 0.40)}; "
            f"border-radius: 5px; padding: 0 12px; text-align: left; }}"
            f"QPushButton:hover {{ background: {rgba(color, 0.30)}; }}"
        )
        b.clicked.connect(lambda: dialogs.info(
            self, label, f"{label} — Phase F polish."))
        return b

    def _on_schedule_stub(self):
        dialogs.info(
            self, "Schedule Rebroadcast",
            "Schedule Rebroadcast — Phase F polish.\n\n"
            "Will record the live On-Air feed for the chosen window and "
            "schedule it to replay at a future date+time.")
