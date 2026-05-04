"""
LiveIndicator — pulsing red dot + LIVE label + optional clock.
"""

from PyQt6.QtCore import Qt, QPropertyAnimation, pyqtProperty, QTimer
from PyQt6.QtGui import (
    QPainter, QColor, QFont, QBrush, QPen, QLinearGradient, QPainterPath,
)
from PyQt6.QtWidgets import QFrame, QGraphicsDropShadowEffect

from datetime import datetime

from ._tokens import inter, mono, RED, RED_LIGHT, TEXT_PRI, BG_ELEVATED, rgba


class LiveIndicator(QFrame):

    HEIGHT = 36

    def __init__(self, show_clock: bool = True, parent=None):
        super().__init__(parent)
        self._show_clock = show_clock
        self._dot_alpha = 1.0
        self._time_str = datetime.now().strftime("%H:%M:%S")
        self.setFixedHeight(self.HEIGHT)

        # Pulse animation
        self._anim = QPropertyAnimation(self, b"dotAlpha", self)
        self._anim.setDuration(1400)
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.4)
        self._anim.setLoopCount(-1)
        self._anim.start()

        # Glow on the dot
        # (applied to whole frame — affects everything but works fine)
        glow = QGraphicsDropShadowEffect(self)
        glow.setOffset(0, 0)
        glow.setBlurRadius(14)
        c = QColor(RED); c.setAlpha(160)
        glow.setColor(c)
        self.setGraphicsEffect(glow)

        # Clock tick
        if show_clock:
            self._t = QTimer(self)
            self._t.setInterval(1000)
            self._t.timeout.connect(self._tick_clock)
            self._t.start()

        self._update_width()

    def _tick_clock(self):
        self._time_str = datetime.now().strftime("%H:%M:%S")
        self.update()

    def get_dotAlpha(self) -> float:
        return self._dot_alpha
    def set_dotAlpha(self, v: float):
        self._dot_alpha = v
        self.update()
    dotAlpha = pyqtProperty(float, get_dotAlpha, set_dotAlpha)

    def _update_width(self):
        from PyQt6.QtGui import QFontMetrics
        live_w = QFontMetrics(inter(11, QFont.Weight.Black, 1.5)).horizontalAdvance("LIVE")
        clock_w = QFontMetrics(mono(13, True)).horizontalAdvance(self._time_str) if self._show_clock else 0
        # 16 padding + dot 8 + gap 10 + label + gap 8 + clock + 16 padding
        w = 16 + 8 + 10 + live_w + (8 + clock_w if self._show_clock else 0) + 16
        self.setFixedWidth(w)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(0, 0, -1, -1)
        radius = self.height() / 2

        # Background pill — dark with subtle border
        p.setBrush(QColor(BG_ELEVATED))
        p.setPen(QPen(QColor(255, 255, 255, 20), 1))
        p.drawRoundedRect(rect, radius, radius)

        # Pulsing dot
        x = 16
        cy = self.height() / 2
        dot = QColor(RED); dot.setAlphaF(self._dot_alpha)
        p.setBrush(dot)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(x - 1, int(cy) - 4, 8, 8)

        # LIVE label
        live_x = x + 18
        p.setPen(QColor(RED))
        p.setFont(inter(11, QFont.Weight.Black, 1.5))
        p.drawText(live_x, 0, 60, self.height(),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   "LIVE")

        # Clock
        if self._show_clock:
            from PyQt6.QtGui import QFontMetrics
            label_w = QFontMetrics(inter(11, QFont.Weight.Black, 1.5)).horizontalAdvance("LIVE")
            clock_x = live_x + label_w + 12
            p.setPen(QColor(TEXT_PRI))
            p.setFont(mono(13, True))
            p.drawText(clock_x, 0, 100, self.height(),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       self._time_str)
