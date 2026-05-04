"""
PremiumBadge — pill-shaped uppercase badge.

2-stop gradient (color 20% → 8%)
1px stroke (color 30%)
Inter Black uppercase + letter-spacing 1.5
Optional pulsing dot on left side
Auto-sized to text + 16px horizontal padding.
"""

from PyQt6.QtCore import Qt, QRectF, QPropertyAnimation, pyqtProperty
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QLinearGradient, QPainterPath, QFont,
)
from PyQt6.QtWidgets import QFrame

from ._tokens import inter, PURPLE


class PremiumBadge(QFrame):

    PADDING_X = 16
    HEIGHT    = 26

    def __init__(self, text: str, color: str = PURPLE,
                 with_dot: bool = False, parent=None):
        super().__init__(parent)
        self._text = text.upper()
        self._color = QColor(color)
        self._with_dot = with_dot
        self._dot_alpha = 1.0
        self.setFixedHeight(self.HEIGHT)

        # Pulsing dot animation
        if with_dot:
            self._anim = QPropertyAnimation(self, b"dotAlpha", self)
            self._anim.setDuration(1600)
            self._anim.setStartValue(1.0)
            self._anim.setEndValue(0.4)
            self._anim.setLoopCount(-1)
            self._anim.start()

        self._update_width()

    def setText(self, text: str):
        self._text = text.upper()
        self._update_width()
        self.update()

    def _font(self):
        return inter(9, QFont.Weight.Black, letter_spacing=1.5)

    def _update_width(self):
        from PyQt6.QtGui import QFontMetrics
        fm = QFontMetrics(self._font())
        text_w = fm.horizontalAdvance(self._text)
        extra = 18 if self._with_dot else 0  # dot + 8px gap
        self.setFixedWidth(text_w + extra + self.PADDING_X * 2)

    def get_dotAlpha(self) -> float:
        return self._dot_alpha
    def set_dotAlpha(self, v: float):
        self._dot_alpha = v
        self.update()
    dotAlpha = pyqtProperty(float, get_dotAlpha, set_dotAlpha)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        radius = self.height() / 2

        # Gradient background
        g = QLinearGradient(0, 0, 0, self.height())
        c20 = QColor(self._color); c20.setAlphaF(0.20)
        c08 = QColor(self._color); c08.setAlphaF(0.08)
        g.setColorAt(0.0, c20)
        g.setColorAt(1.0, c08)
        p.setBrush(QBrush(g))

        # 1px border at color 30%
        bc = QColor(self._color); bc.setAlphaF(0.30)
        p.setPen(QPen(bc, 1))
        p.drawRoundedRect(rect, radius, radius)

        # Text + optional dot
        text_x = self.PADDING_X
        if self._with_dot:
            dot_y = self.height() / 2
            dot_color = QColor(self._color)
            dot_color.setAlphaF(self._dot_alpha)
            p.setBrush(dot_color)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(self.PADDING_X - 2, int(dot_y) - 3, 6, 6)
            text_x += 12

        p.setPen(self._color)
        p.setFont(self._font())
        p.drawText(QRectF(text_x, 0, self.width() - text_x - self.PADDING_X, self.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   self._text)
