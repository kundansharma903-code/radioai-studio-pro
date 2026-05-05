"""
Shared header + status bar for the F4–F8 stub screens.

These stubs all wear the same chrome — RadioAI brand + 3-tab nav
(Control Panel | Scheduling | <self active>) + clock + Open Studio CTA
in the header, and AUTO MODE / AI Active pills in the status bar. Pulling
the shell out here keeps each stub focused on its actual content.

Used by ui/final_log.py, ui/log_viewer.py, ui/force_clocks.py,
ui/playlists.py, ui/rebroadcast.py.
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, QRect, QRectF, QTimer, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QPen, QFont, QCursor
from PyQt6.QtWidgets import (
    QFrame, QLabel, QPushButton, QHBoxLayout,
)

from ui.widgets._tokens import (
    inter, mono, rgba,
    BG_PANEL, BG_CARD_DK,
    TEXT_PRI, TEXT_SEC, TEXT_MUTED, TEXT_DIM,
    CYAN, CYAN_LIGHT, PURPLE, PURPLE_LIGHT, PURPLE_DARK,
    GREEN, GREEN_LIGHT, AMBER,
)

BORDER = "#1c1f38"
HEADER_H = 72
STATUS_H = 36


class StubHeader(QFrame):
    """3-tab header (Control Panel | Scheduling | <active>) + clock + CTA."""

    control_panel_clicked = pyqtSignal()
    scheduling_clicked    = pyqtSignal()
    studio_clicked        = pyqtSignal()

    def __init__(self, screen_label: str, screen_title: str,
                 screen_subtitle: str = "RadioAI Studio · KISS FM 91.5 · Jaipur",
                 active_color: str = GREEN_LIGHT, parent=None):
        super().__init__(parent)
        self._screen_label = screen_label
        self._screen_title = screen_title
        self._screen_subtitle = screen_subtitle
        self._active_color = active_color
        self.setFixedHeight(HEADER_H)
        self.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border-bottom: 1px solid {BORDER}; }}"
        )

        self._clock_text = "00:00:00"
        self._timer = QTimer(self); self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick_clock); self._timer.start()
        self._tick_clock()

        # Nav row (Control Panel | Scheduling | <screen_label active>)
        cp = QPushButton("Control Panel", self)
        cp.setGeometry(220, 22, 110, 28)
        cp.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        cp.setFont(inter(10, QFont.Weight.Medium))
        cp.setStyleSheet(self._nav_qss(False))
        cp.clicked.connect(self.control_panel_clicked.emit)

        sch = QPushButton("Scheduling", self)
        sch.setGeometry(336, 22, 92, 28)
        sch.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        sch.setFont(inter(10, QFont.Weight.Medium))
        sch.setStyleSheet(self._nav_qss(False))
        sch.clicked.connect(self.scheduling_clicked.emit)

        active = QPushButton(screen_label, self)
        # width depends on label length
        w = max(96, 18 + 8 * len(screen_label))
        active.setGeometry(434, 22, w, 28)
        active.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        active.setFont(inter(10, QFont.Weight.DemiBold))
        active.setStyleSheet(self._nav_qss(True, color=active_color))

        st = QPushButton("▶  Open Studio", self)
        st.setGeometry(self._w_for_studio_btn(), 18, 200, 36)
        st.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        st.setFont(inter(11, QFont.Weight.Bold, letter_spacing=0.4))
        st.setStyleSheet(
            f"QPushButton {{ background: qlineargradient("
            f"x1:0,y1:0,x2:1,y2:0, stop:0 {PURPLE_LIGHT}, "
            f"stop:1 {PURPLE_DARK}); "
            f"color: white; border: none; border-radius: 8px; }}"
            f"QPushButton:hover {{ background: qlineargradient("
            f"x1:0,y1:0,x2:1,y2:0, stop:0 #c4b5fd, stop:1 {PURPLE}); }}"
        )
        st.clicked.connect(self.studio_clicked.emit)

    @staticmethod
    def _w_for_studio_btn() -> int:
        # Right-anchored — matches the 1440 design canvas.
        return 1440 - 220

    def _nav_qss(self, active: bool, color: str = CYAN_LIGHT) -> str:
        if active:
            return (
                f"QPushButton {{ background: {rgba(color, 0.18)}; "
                f"color: {color}; "
                f"border: 1px solid {rgba(color, 0.40)}; "
                f"border-radius: 6px; padding: 0 12px; }}"
            )
        return (
            f"QPushButton {{ background: transparent; "
            f"color: {TEXT_SEC}; "
            f"border: 1px solid transparent; "
            f"border-radius: 6px; padding: 0 12px; }}"
            f"QPushButton:hover {{ color: {TEXT_PRI}; "
            f"border: 1px solid {rgba('#ffffff', 0.10)}; }}"
        )

    def _tick_clock(self):
        from datetime import datetime
        self._clock_text = datetime.now().strftime("%H:%M:%S")
        self.update(QRect(900, 0, 220, HEADER_H))

    def paintEvent(self, _e):
        super().paintEvent(_e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Logo dot + RadioAI title block
        p.setBrush(QColor(PURPLE)); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(14, HEADER_H // 2 - 6, 12, 12)
        p.setPen(QColor(TEXT_PRI))
        p.setFont(inter(18, QFont.Weight.Black, letter_spacing=0.4))
        p.drawText(QRectF(75, 14, 200, 22),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "RadioAI")
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(inter(9, QFont.Weight.DemiBold, letter_spacing=1.6))
        p.drawText(QRectF(75, 36, 200, 18),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "STUDIO PRO")

        # Screen title + subtitle (just right of nav)
        p.setPen(QColor(TEXT_PRI))
        p.setFont(inter(15, QFont.Weight.Bold, letter_spacing=0.2))
        p.drawText(QRectF(580, 14, 320, 22),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._screen_title)
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(inter(9))
        p.drawText(QRectF(580, 36, 360, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._screen_subtitle)

        # Live clock (mono, right-of-center)
        p.setPen(QColor(TEXT_PRI))
        p.setFont(mono(20, bold=True))
        p.drawText(QRectF(940, 14, 220, 24),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   self._clock_text)
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(inter(9))
        p.drawText(QRectF(940, 38, 220, 16),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   "KISS FM 91.5")


class StubStatusBar(QFrame):
    """Bottom pills + version. Single shared instance for all stub screens."""

    def __init__(self, screen_label: str, parent=None):
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
        h.addStretch()
        version = QLabel(f"{screen_label} · RadioAI Studio v1.0.0")
        version.setFont(inter(9))
        version.setStyleSheet(f"color: {TEXT_DIM}; background: transparent;")
        h.addWidget(version)
