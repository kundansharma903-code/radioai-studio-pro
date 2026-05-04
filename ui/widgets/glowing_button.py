"""
GlowingButton — gradient button with multi-layer glow.

3-stop linear gradient (light → main → dark)
Outer color glow via QGraphicsDropShadowEffect
Inner top highlight (white 25% gradient on top half)
14px border-radius
Hover: brighter via repaint
"""

from PyQt6.QtCore import Qt, QRectF, QSize
from PyQt6.QtGui import (
    QPainter, QColor, QBrush, QPen, QLinearGradient, QPainterPath, QFont,
)
from PyQt6.QtWidgets import QPushButton, QGraphicsDropShadowEffect

from ._tokens import inter, PURPLE, PURPLE_LIGHT, PURPLE_DARK


class GlowingButton(QPushButton):
    """Premium gradient button. Use for primary CTAs."""

    RADIUS = 14

    def __init__(self, text: str = "", color: str = PURPLE,
                 light: str = PURPLE_LIGHT, dark: str = PURPLE_DARK,
                 height: int = 48, parent=None):
        super().__init__(text, parent)
        self._color = QColor(color)
        self._light = QColor(light)
        self._dark  = QColor(dark)
        self._hover = False

        self.setMinimumHeight(height)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFlat(True)
        self.setStyleSheet("background: transparent; border: none;")

        # Glow — accent color, 50% opacity, blur 24
        glow = QGraphicsDropShadowEffect(self)
        glow.setOffset(0, 6)
        glow.setBlurRadius(28)
        c = QColor(self._color)
        c.setAlpha(140)  # ~55%
        glow.setColor(c)
        self.setGraphicsEffect(glow)

    # ── Public API ────────────────────────────────────────────────────────

    def set_color(self, color: str, light: str = None, dark: str = None):
        self._color = QColor(color)
        if light: self._light = QColor(light)
        if dark:  self._dark  = QColor(dark)
        self.update()

    def sizeHint(self):
        s = super().sizeHint()
        return QSize(max(120, s.width() + 32), max(48, s.height()))

    # ── Paint ─────────────────────────────────────────────────────────────

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect().adjusted(0, 0, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), self.RADIUS, self.RADIUS)
        p.setClipPath(path)

        # 3-stop gradient (light → main → dark, vertical)
        grad = QLinearGradient(0, 0, 0, self.height())
        if self._hover:
            grad.setColorAt(0.0, self._light)
            grad.setColorAt(0.5, self._color)
            grad.setColorAt(1.0, self._color)
        else:
            grad.setColorAt(0.0, self._light)
            grad.setColorAt(0.5, self._color)
            grad.setColorAt(1.0, self._dark)
        p.fillRect(self.rect(), QBrush(grad))

        # Inner top highlight — white 25% gradient on top half
        hi = QLinearGradient(0, 0, 0, self.height() / 2)
        hi.setColorAt(0.0, QColor(255, 255, 255, 64))   # 25%
        hi.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.fillRect(0, 0, self.width(), self.height() // 2, QBrush(hi))

        # Border
        p.setClipping(False)
        p.setPen(QPen(QColor(255, 255, 255, 30), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(rect), self.RADIUS, self.RADIUS)

        # Text
        p.setPen(QColor("#ffffff"))
        font = inter(14, QFont.Weight.Bold, letter_spacing=-0.2)
        p.setFont(font)
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text())

    # ── Hover ─────────────────────────────────────────────────────────────

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)
