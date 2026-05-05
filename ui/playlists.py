"""
RadioAI — Playlists (Figma 63:2). Phase F7 stub.

Read-only list of playlists + songs in selected playlist + settings panel.
"""

from __future__ import annotations

import logging

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
    CYAN, CYAN_LIGHT, PURPLE, PURPLE_LIGHT,
    GREEN, GREEN_LIGHT, AMBER, RED_LIGHT,
)

log = logging.getLogger("Playlists")

WINDOW_W = 1440; WINDOW_H = 900
HEADER_H = 72; STATUS_H = 36
LEFT_W = 220; RIGHT_W = 360
CENTER_W = WINDOW_W - LEFT_W - RIGHT_W
CONTENT_Y = HEADER_H
CONTENT_H = WINDOW_H - HEADER_H - STATUS_H


class Playlists(QWidget):
    breadcrumb_clicked = pyqtSignal(str)
    studio_clicked     = pyqtSignal()

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self._db = db
        self.setFixedSize(WINDOW_W, WINDOW_H)
        self.setStyleSheet(f"QWidget {{ background: {BG_BASE}; }}")

        h = StubHeader("Playlists", "Playlists",
                       active_color=CYAN_LIGHT, parent=self)
        h.setGeometry(0, 0, WINDOW_W, HEADER_H)
        h.control_panel_clicked.connect(
            lambda: self.breadcrumb_clicked.emit("control_panel"))
        h.scheduling_clicked.connect(
            lambda: self.breadcrumb_clicked.emit("scheduling_hub"))
        h.studio_clicked.connect(self.studio_clicked.emit)

        # Pull playlists
        try:
            pls = list(db._conn().execute(
                "SELECT * FROM playlists ORDER BY name"
            ).fetchall())
        except Exception:
            pls = []

        # Left — playlist list + actions
        left = QFrame(self)
        left.setGeometry(0, CONTENT_Y, LEFT_W, CONTENT_H)
        left.setStyleSheet(f"QFrame {{ background: {BG_DARK}; "
                           f"border-right: 1px solid {BORDER}; }}")
        lv = QVBoxLayout(left); lv.setContentsMargins(10, 14, 10, 14); lv.setSpacing(6)
        head_row = QHBoxLayout()
        title = QLabel(f"{len(pls)} Playlists")
        title.setFont(inter(8, QFont.Weight.Black, letter_spacing=1.4))
        title.setStyleSheet(f"color: {CYAN_LIGHT}; background: transparent;")
        head_row.addWidget(title); head_row.addStretch()
        new = QPushButton("+ New"); new.setFixedHeight(24)
        new.setFont(inter(9, QFont.Weight.DemiBold))
        new.setStyleSheet(
            f"QPushButton {{ background: {rgba(GREEN, 0.16)}; "
            f"color: {GREEN_LIGHT}; "
            f"border: 1px solid {rgba(GREEN, 0.40)}; "
            f"border-radius: 4px; padding: 0 8px; }}"
        )
        new.clicked.connect(lambda: QMessageBox.information(
            self, "New Playlist", "New Playlist — Phase F polish."))
        head_row.addWidget(new)
        lv.addLayout(head_row)

        if not pls:
            empty = QLabel("(no playlists yet — '+ New' to start)")
            empty.setFont(inter(9)); empty.setWordWrap(True)
            empty.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
            lv.addWidget(empty)
        for i, pl in enumerate(pls):
            row = QFrame(); row.setFixedHeight(50)
            bg = rgba(CYAN_LIGHT, 0.16) if i == 0 else BG_CARD_DK
            border = rgba(CYAN_LIGHT, 0.40) if i == 0 else BORDER
            row.setStyleSheet(f"QFrame {{ background: {bg}; "
                              f"border: 1px solid {border}; "
                              f"border-radius: 5px; }}")
            v = QVBoxLayout(row); v.setContentsMargins(8, 4, 8, 4); v.setSpacing(0)
            n = QLabel(str(pl["name"] or "—"))
            n.setFont(inter(10, QFont.Weight.DemiBold))
            n.setStyleSheet(
                f"color: {CYAN_LIGHT if i == 0 else TEXT_SEC}; "
                f"background: transparent;")
            v.addWidget(n)
            d = QLabel(str(pl["description"] or "—")[:30]
                       if "description" in pl.keys() else "—")
            d.setFont(mono(8, bold=False))
            d.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
            v.addWidget(d)
            lv.addWidget(row)

        lv.addStretch()
        for label, color in [("✎ Edit", AMBER),
                             ("⧉ Duplicate", CYAN_LIGHT),
                             ("✗ Delete", RED_LIGHT),
                             ("⇑ Export", PURPLE_LIGHT)]:
            lv.addWidget(self._action_btn(label, color))

        # Center — songs list (placeholder)
        center = QFrame(self)
        center.setGeometry(LEFT_W, CONTENT_Y, CENTER_W, CONTENT_H)
        center.setStyleSheet(f"QFrame {{ background: {BG_BASE}; "
                             f"border-right: 1px solid {BORDER}; }}")
        cv = QVBoxLayout(center); cv.setContentsMargins(20, 14, 20, 14); cv.setSpacing(8)
        title = QLabel(pls[0]["name"] if pls else "Select a playlist")
        title.setFont(inter(13, QFont.Weight.Black, letter_spacing=0.4))
        title.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        cv.addWidget(title)
        sub = QLabel("— songs · Ordered playback · — duration")
        sub.setFont(inter(9))
        sub.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        cv.addWidget(sub)
        # Toolbar
        bar = QHBoxLayout(); bar.setSpacing(6)
        for label, color in [("+ Add Songs", GREEN_LIGHT),
                             ("↑ Move Up", CYAN_LIGHT),
                             ("↓ Move Down", CYAN_LIGHT),
                             ("✗ Remove", RED_LIGHT),
                             ("⇄ Shuffle Order", PURPLE_LIGHT)]:
            b = QPushButton(label); b.setFixedHeight(28)
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.setFont(inter(9, QFont.Weight.DemiBold))
            b.setStyleSheet(
                f"QPushButton {{ background: {rgba(color, 0.18)}; "
                f"color: {color}; "
                f"border: 1px solid {rgba(color, 0.40)}; "
                f"border-radius: 4px; padding: 0 10px; }}"
                f"QPushButton:hover {{ background: {rgba(color, 0.28)}; }}"
            )
            b.clicked.connect(lambda _c=False, _l=label: QMessageBox.information(
                self, _l, f"{_l} — Phase F polish."))
            bar.addWidget(b)
        bar.addStretch()
        cv.addLayout(bar)
        # Songs list
        self._songs = QListWidget()
        self._songs.setStyleSheet(
            f"QListWidget {{ background: {BG_CARD_DK}; "
            f"color: {TEXT_PRI}; "
            f"border: 1px solid {BORDER}; "
            f"border-radius: 6px; padding: 4px; }}"
            f"QListWidget::item {{ padding: 4px; }}"
        )
        # Show first few songs from DB so the list isn't empty
        try:
            for s in db.get_songs(limit=8):
                self._songs.addItem(QListWidgetItem(
                    f"  {s['artist'] or '—'}    {s['title'] or '—'}"))
        except Exception:
            pass
        cv.addWidget(self._songs, 1)

        # Right — playlist settings (read-only)
        right = QFrame(self)
        right.setGeometry(LEFT_W + CENTER_W, CONTENT_Y, RIGHT_W, CONTENT_H)
        right.setStyleSheet(f"QFrame {{ background: {BG_PANEL}; }}")
        rv = QVBoxLayout(right); rv.setContentsMargins(14, 14, 14, 14); rv.setSpacing(8)
        title2 = QLabel("PLAYLIST SETTINGS")
        title2.setFont(inter(8, QFont.Weight.Black, letter_spacing=1.4))
        title2.setStyleSheet(f"color: {AMBER}; background: transparent;")
        rv.addWidget(title2)
        for k, v in [("Playlist Name", pls[0]["name"] if pls else "—"),
                     ("Description",   "—"),
                     ("Playback Mode", "Ordered (1→30)"),
                     ("Repeat Mode",   "Play Once"),
                     ("On Finish",     "Return to Clock Schedule"),
                     ("Crossfade",     "3 seconds"),
                     ("Volume Offset", "0 dB (Normal)")]:
            rv.addWidget(self._kv(k, v))
        rv.addStretch()
        save = QPushButton("✓ Save Playlist Settings")
        save.setFixedHeight(36); save.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        save.setFont(inter(11, QFont.Weight.Bold))
        save.setStyleSheet(
            f"QPushButton {{ background: {rgba(PURPLE, 0.24)}; "
            f"color: {PURPLE_LIGHT}; "
            f"border: 1px solid {rgba(PURPLE, 0.50)}; "
            f"border-radius: 6px; }}"
            f"QPushButton:hover {{ background: {rgba(PURPLE, 0.36)}; }}"
        )
        save.clicked.connect(lambda: QMessageBox.information(
            self, "Save Playlist Settings", "Save — Phase F polish."))
        rv.addWidget(save)

        sb = StubStatusBar("Playlists", parent=self)
        sb.setGeometry(0, WINDOW_H - STATUS_H, WINDOW_W, STATUS_H)

        log.info("Playlists ready (Figma 63:2)")

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
        b.clicked.connect(lambda: QMessageBox.information(
            self, label, f"{label} — Phase F polish."))
        return b
