"""
RadioAI — Force Clocks (Figma 63:521). Phase F6 stub.

Read-only list of force_clocks rows + Add Override stub.
"""

from __future__ import annotations

import logging
from datetime import datetime

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QCursor, QFont
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QMessageBox,
)

from ui.widgets._phase_stub import StubHeader, StubStatusBar, BORDER
from ui.widgets._tokens import (
    inter, mono, rgba,
    BG_BASE, BG_DARK, BG_PANEL, BG_CARD_DK,
    TEXT_PRI, TEXT_SEC, TEXT_MUTED, TEXT_DIM,
    CYAN, CYAN_LIGHT, PURPLE_LIGHT, GREEN, GREEN_LIGHT,
    AMBER, AMBER_LIGHT, RED, RED_LIGHT, PINK,
)

log = logging.getLogger("ForceClocks")

WINDOW_W = 1440; WINDOW_H = 900
HEADER_H = 72; STATUS_H = 36
LEFT_W = 240; RIGHT_W = 360
CENTER_W = WINDOW_W - LEFT_W - RIGHT_W
CONTENT_Y = HEADER_H
CONTENT_H = WINDOW_H - HEADER_H - STATUS_H


class ForceClocks(QWidget):
    breadcrumb_clicked = pyqtSignal(str)
    studio_clicked     = pyqtSignal()

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self._db = db
        self.setFixedSize(WINDOW_W, WINDOW_H)
        self.setStyleSheet(f"QWidget {{ background: {BG_BASE}; }}")

        h = StubHeader("Force Clocks", "Force Clocks",
                       active_color=AMBER, parent=self)
        h.setGeometry(0, 0, WINDOW_W, HEADER_H)
        h.control_panel_clicked.connect(
            lambda: self.breadcrumb_clicked.emit("control_panel"))
        h.scheduling_clicked.connect(
            lambda: self.breadcrumb_clicked.emit("scheduling_hub"))
        h.studio_clicked.connect(self.studio_clicked.emit)

        # Left — overrides list + actions
        left = QFrame(self)
        left.setGeometry(0, CONTENT_Y, LEFT_W, CONTENT_H)
        left.setStyleSheet(
            f"QFrame {{ background: {BG_DARK}; "
            f"border-right: 1px solid {BORDER}; }}"
        )
        lv = QVBoxLayout(left); lv.setContentsMargins(10, 14, 10, 14); lv.setSpacing(6)

        try:
            overrides = list(db._conn().execute(
                "SELECT * FROM force_clocks ORDER BY override_date DESC LIMIT 30"
            ).fetchall())
        except Exception:
            overrides = []

        head_row = QHBoxLayout()
        title = QLabel(f"{len(overrides)} Overrides")
        title.setFont(inter(8, QFont.Weight.Black, letter_spacing=1.4))
        title.setStyleSheet(f"color: {AMBER}; background: transparent;")
        head_row.addWidget(title); head_row.addStretch()
        add_btn = QPushButton("+ Add New")
        add_btn.setFixedHeight(24)
        add_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        add_btn.setFont(inter(9, QFont.Weight.DemiBold))
        add_btn.setStyleSheet(
            f"QPushButton {{ background: {rgba(GREEN, 0.16)}; "
            f"color: {GREEN_LIGHT}; "
            f"border: 1px solid {rgba(GREEN, 0.40)}; "
            f"border-radius: 4px; padding: 0 8px; }}"
        )
        add_btn.clicked.connect(self._on_add_stub)
        head_row.addWidget(add_btn)
        lv.addLayout(head_row)

        if not overrides:
            empty = QLabel("(no force_clocks yet — Add New to override\n"
                           "regular schedule for a specific date)")
            empty.setFont(inter(9)); empty.setWordWrap(True)
            empty.setStyleSheet(
                f"color: {TEXT_MUTED}; background: transparent;")
            lv.addWidget(empty)
        for i, ov in enumerate(overrides):
            row = QFrame(); row.setFixedHeight(50)
            bg = rgba(AMBER, 0.16) if i == 0 else BG_CARD_DK
            border = rgba(AMBER, 0.40) if i == 0 else BORDER
            row.setStyleSheet(
                f"QFrame {{ background: {bg}; "
                f"border: 1px solid {border}; border-radius: 5px; }}"
            )
            v = QVBoxLayout(row); v.setContentsMargins(8, 4, 8, 4); v.setSpacing(0)
            n = QLabel(str(ov["name"] or "—"))
            n.setFont(inter(10, QFont.Weight.DemiBold))
            n.setStyleSheet(
                f"color: {AMBER if i == 0 else TEXT_SEC}; "
                f"background: transparent;")
            v.addWidget(n)
            d = QLabel(f"{ov['override_date']}  ·  All Day"
                       if "override_date" in ov.keys() else "—")
            d.setFont(mono(8, bold=False))
            d.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
            v.addWidget(d)
            lv.addWidget(row)

        lv.addStretch()
        for label, color in [("✎ Edit Override", AMBER),
                             ("⧉ Duplicate", CYAN_LIGHT),
                             ("✗ Delete", RED_LIGHT)]:
            lv.addWidget(self._action_btn(label, color))

        # Center — month calendar placeholder
        center = QFrame(self)
        center.setGeometry(LEFT_W, CONTENT_Y, CENTER_W, CONTENT_H)
        center.setStyleSheet(f"QFrame {{ background: {BG_BASE}; "
                             f"border-right: 1px solid {BORDER}; }}")
        cv = QVBoxLayout(center); cv.setContentsMargins(20, 14, 20, 14); cv.setSpacing(8)
        title = QLabel(f"FORCE CLOCK OVERRIDES — "
                       f"{datetime.now().strftime('%B %Y').upper()}")
        title.setFont(inter(11, QFont.Weight.Black, letter_spacing=1.0))
        title.setStyleSheet(f"color: {AMBER}; background: transparent;")
        cv.addWidget(title)
        cal = QLabel("(monthly calendar grid — Phase F polish)")
        cal.setFont(inter(10)); cal.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cal.setStyleSheet(
            f"QLabel {{ background: {BG_CARD_DK}; "
            f"color: {TEXT_MUTED}; "
            f"border: 1px solid {BORDER}; "
            f"border-radius: 8px; padding: 60px; }}"
        )
        cv.addWidget(cal, 1)

        # Right — Edit Override form (placeholder)
        right = QFrame(self)
        right.setGeometry(LEFT_W + CENTER_W, CONTENT_Y, RIGHT_W, CONTENT_H)
        right.setStyleSheet(f"QFrame {{ background: {BG_PANEL}; }}")
        rv = QVBoxLayout(right); rv.setContentsMargins(14, 14, 14, 14); rv.setSpacing(8)
        title2 = QLabel("EDIT OVERRIDE")
        title2.setFont(inter(8, QFont.Weight.Black, letter_spacing=1.4))
        title2.setStyleSheet(f"color: {AMBER}; background: transparent;")
        rv.addWidget(title2)
        for label, value in [("Override Name", "—"), ("Target Clock", "—"),
                             ("Date Type", "—"), ("Date", "—"),
                             ("Time Range", "All Day (00:00-23:59)"),
                             ("Recurring", "No — One Time Only"),
                             ("Priority", "Highest")]:
            rv.addWidget(self._kv(label, value))
        rv.addStretch()
        rv.addWidget(self._action_btn("✓ Save Override", AMBER, big=True))
        rv.addWidget(self._action_btn("✗ Delete Override", RED_LIGHT))

        sb = StubStatusBar("Force Clocks", parent=self)
        sb.setGeometry(0, WINDOW_H - STATUS_H, WINDOW_W, STATUS_H)

        log.info("ForceClocks ready (Figma 63:521)")

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

    def _action_btn(self, label, color, big=False):
        b = QPushButton(label)
        b.setFixedHeight(36 if big else 28)
        b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        b.setFont(inter(11 if big else 10,
                        QFont.Weight.Bold if big else QFont.Weight.DemiBold))
        b.setStyleSheet(
            f"QPushButton {{ background: {rgba(color, 0.18 if not big else 0.24)}; "
            f"color: {color}; "
            f"border: 1px solid {rgba(color, 0.40)}; "
            f"border-radius: 5px; padding: 0 12px; text-align: left; }}"
            f"QPushButton:hover {{ background: {rgba(color, 0.30)}; }}"
        )
        b.clicked.connect(lambda: QMessageBox.information(
            self, label, f"{label.lstrip('✎⧉✗✓ ')} — Phase F polish."))
        return b

    def _on_add_stub(self):
        QMessageBox.information(
            self, "Add Override",
            "Add Force Clock Override — Phase F polish.\n\n"
            "Will let you select a date and assign a different clock for "
            "that day (holidays, special events).")
