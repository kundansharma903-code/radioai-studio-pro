"""
CategoryPill — small colored category badge.

Auto-sized to text + 16px padding.
2-stop gradient (color 18% → 6%).
1px border (color 30%).
11px border-radius.
Inter Black 7px uppercase + letter-spacing 1.0.
"""

from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QLinearGradient, QFont, QFontMetrics,
)
from PyQt6.QtWidgets import QLabel

from ._tokens import inter, PURPLE


class CategoryPill(QLabel):

    PADDING_X = 12
    HEIGHT    = 22

    def __init__(self, text: str, color: str = PURPLE, parent=None):
        super().__init__(text.upper(), parent)
        self._color = QColor(color)
        self.setFixedHeight(self.HEIGHT)
        self.setFont(inter(8, QFont.Weight.Black, letter_spacing=1.0))
        self._update_width()

    def setText(self, t: str):
        super().setText(t.upper())
        self._update_width()

    def _update_width(self):
        fm = QFontMetrics(self.font())
        tw = fm.horizontalAdvance(self.text())
        self.setFixedWidth(tw + self.PADDING_X * 2)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)

        g = QLinearGradient(0, 0, 0, self.height())
        c1 = QColor(self._color); c1.setAlphaF(0.18)
        c2 = QColor(self._color); c2.setAlphaF(0.06)
        g.setColorAt(0.0, c1)
        g.setColorAt(1.0, c2)
        p.setBrush(QBrush(g))

        bc = QColor(self._color); bc.setAlphaF(0.30)
        p.setPen(QPen(bc, 1))
        p.drawRoundedRect(rect, 11, 11)

        p.setPen(self._color)
        p.setFont(self.font())
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text())
