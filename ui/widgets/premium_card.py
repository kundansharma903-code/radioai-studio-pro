"""
PremiumCard — base card widget for all dashboard tiles.

Multi-stop gradient bg (#0e1020 → #070912)
3px top accent gradient bar (color-tinted, color → light)
1px white border @ 6% opacity (rgba)
16px border-radius
Outer drop shadow (0,8,24, black 40%)
Hoverable — emits hovered(bool) signal
"""

from PyQt6.QtCore import Qt, QRectF, pyqtSignal
from PyQt6.QtGui import (
    QPainter, QColor, QBrush, QPen, QLinearGradient, QPainterPath,
)
from PyQt6.QtWidgets import QFrame, QGraphicsDropShadowEffect

from ._tokens import (
    BG_CARD, BG_CARD_DK, PURPLE, PURPLE_LIGHT,
)


class PremiumCard(QFrame):
    """Base card. Contains a child layout area with 24px padding by default."""

    hovered = pyqtSignal(bool)

    RADIUS = 16

    def __init__(self, accent_color: str = PURPLE, light_color: str = PURPLE_LIGHT,
                 parent=None):
        super().__init__(parent)
        self._accent = QColor(accent_color)
        self._light  = QColor(light_color)
        self._is_hover = False
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        # Outer drop shadow — black 40%, 8px down, 24 blur
        sh = QGraphicsDropShadowEffect(self)
        sh.setOffset(0, 8)
        sh.setBlurRadius(24)
        sh.setColor(QColor(0, 0, 0, 102))  # 40% = 102/255
        self.setGraphicsEffect(sh)

    # ── Public API ────────────────────────────────────────────────────────

    def set_color(self, accent: str, light: str) -> None:
        self._accent = QColor(accent)
        self._light  = QColor(light)
        self.update()

    @property
    def accent(self) -> QColor:
        return self._accent

    # ── Paint ─────────────────────────────────────────────────────────────

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect().adjusted(0, 0, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), self.RADIUS, self.RADIUS)
        p.setClipPath(path)

        # Body — vertical gradient
        body = QLinearGradient(0, 0, 0, self.height())
        body.setColorAt(0.0, QColor(BG_CARD))
        body.setColorAt(1.0, QColor(BG_CARD_DK))
        p.fillRect(self.rect(), QBrush(body))

        # Hover tint — accent at very low opacity overlays the body
        if self._is_hover:
            hov = QColor(self._accent)
            hov.setAlphaF(0.06)
            p.fillRect(self.rect(), hov)

        # Top 3px accent gradient bar (accent → light, horizontal)
        top_grad = QLinearGradient(0, 0, self.width(), 0)
        top_grad.setColorAt(0.0, self._accent)
        top_grad.setColorAt(1.0, self._light)
        p.fillRect(0, 0, self.width(), 3, QBrush(top_grad))

        # Subtle inner top highlight (white 8% gradient, 1px)
        hi = QColor(255, 255, 255, 20)
        p.fillRect(0, 3, self.width(), 1, hi)

        # 1px border at white 6% (drawn last, inside clip)
        p.setClipping(False)
        pen = QPen(QColor(255, 255, 255, 15), 1)  # 6% ≈ 15/255
        if self._is_hover:
            pen.setColor(QColor(self._accent.red(),
                                self._accent.green(),
                                self._accent.blue(), 80))
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(rect), self.RADIUS, self.RADIUS)

    # ── Hover events ──────────────────────────────────────────────────────

    def enterEvent(self, e):
        self._is_hover = True
        self.hovered.emit(True)
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._is_hover = False
        self.hovered.emit(False)
        self.update()
        super().leaveEvent(e)
