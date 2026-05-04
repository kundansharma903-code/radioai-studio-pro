"""
PictorialIcon — custom QPainter-drawn icons (no emoji).

Six types matching the Control Panel categories:
  SONGS    — vinyl disc + music note
  JINGLES  — bell with sound waves
  SPOTS    — circle with $ + ring
  SWEEPERS — broom (handle + bristles + sparkle)
  INSTANT  — lightning bolt + spark dots
  STITCHER — 4-point star with smaller stars

Each shape uses a gradient fill and an outer color glow.
"""

import math
from enum import Enum

from PyQt6.QtCore import Qt, QPointF, QRectF
from PyQt6.QtGui import (
    QPainter, QColor, QBrush, QPen, QLinearGradient, QPainterPath,
    QPolygonF, QFont,
)
from PyQt6.QtWidgets import QWidget, QGraphicsDropShadowEffect

from ._tokens import (
    CYAN, CYAN_LIGHT, PURPLE, PURPLE_LIGHT, GREEN, GREEN_LIGHT,
    AMBER, AMBER_LIGHT, RED, RED_LIGHT, PINK, PINK_LIGHT,
)


class IconType(Enum):
    SONGS    = "songs"
    JINGLES  = "jingles"
    SPOTS    = "spots"
    SWEEPERS = "sweepers"
    INSTANT  = "instant"
    STITCHER = "stitcher"


# Default colors per icon type
_DEFAULTS = {
    IconType.SONGS:    (CYAN,   CYAN_LIGHT),
    IconType.JINGLES:  (AMBER,  AMBER_LIGHT),
    IconType.SPOTS:    (GREEN,  GREEN_LIGHT),
    IconType.SWEEPERS: (PINK,   PINK_LIGHT),
    IconType.INSTANT:  (PURPLE, PURPLE_LIGHT),
    IconType.STITCHER: (RED,    RED_LIGHT),
}


class PictorialIcon(QWidget):

    def __init__(self, icon_type: IconType, color: str = None, light: str = None,
                 size: int = 32, parent=None):
        super().__init__(parent)
        self._type = icon_type
        d_color, d_light = _DEFAULTS[icon_type]
        self._color = QColor(color or d_color)
        self._light = QColor(light or d_light)
        self._size  = size
        self.setFixedSize(size, size)

        # Subtle color glow
        glow = QGraphicsDropShadowEffect(self)
        glow.setOffset(0, 0)
        glow.setBlurRadius(12)
        c = QColor(self._color); c.setAlpha(140)
        glow.setColor(c)
        self.setGraphicsEffect(glow)

    def set_color(self, color: str, light: str = None):
        self._color = QColor(color)
        if light: self._light = QColor(light)
        self.update()

    def _gradient(self) -> QLinearGradient:
        g = QLinearGradient(0, 0, 0, self.height())
        g.setColorAt(0.0, self._light)
        g.setColorAt(1.0, self._color)
        return g

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = self._size
        cx, cy = s / 2, s / 2
        grad = self._gradient()
        brush = QBrush(grad)
        p.setBrush(brush)
        p.setPen(Qt.PenStyle.NoPen)

        t = self._type
        if t == IconType.SONGS:
            self._draw_songs(p, cx, cy, s)
        elif t == IconType.JINGLES:
            self._draw_jingles(p, cx, cy, s)
        elif t == IconType.SPOTS:
            self._draw_spots(p, cx, cy, s)
        elif t == IconType.SWEEPERS:
            self._draw_sweepers(p, cx, cy, s)
        elif t == IconType.INSTANT:
            self._draw_instant(p, cx, cy, s)
        elif t == IconType.STITCHER:
            self._draw_stitcher(p, cx, cy, s)

    # ── Icon shapes ───────────────────────────────────────────────────────

    def _draw_songs(self, p: QPainter, cx: float, cy: float, s: float):
        # Vinyl disc — outer ring + inner ring + tiny center
        r = s * 0.36
        p.drawEllipse(QPointF(cx, cy + s * 0.05), r, r)  # disc
        # Inner ring (darker)
        p.setBrush(QColor(0, 0, 0, 100))
        p.drawEllipse(QPointF(cx, cy + s * 0.05), r * 0.55, r * 0.55)
        # Center hole — bg color (transparent-ish)
        p.setBrush(self._light)
        p.drawEllipse(QPointF(cx, cy + s * 0.05), r * 0.10, r * 0.10)
        # Music note rising from disc — stem + filled head
        p.setBrush(QBrush(self._gradient()))
        # Stem
        stem_x = cx + s * 0.17
        p.setPen(QPen(self._light, max(1.5, s * 0.04)))
        p.drawLine(QPointF(stem_x, cy - s * 0.30), QPointF(stem_x, cy + s * 0.05))
        # Note head (oval)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(stem_x - s * 0.06, cy + s * 0.02),
                      s * 0.10, s * 0.07)
        # Flag
        path = QPainterPath()
        path.moveTo(stem_x, cy - s * 0.30)
        path.cubicTo(QPointF(stem_x + s * 0.20, cy - s * 0.22),
                     QPointF(stem_x + s * 0.18, cy - s * 0.10),
                     QPointF(stem_x + s * 0.04, cy - s * 0.05))
        path.lineTo(stem_x, cy - s * 0.10)
        path.closeSubpath()
        p.drawPath(path)

    def _draw_jingles(self, p: QPainter, cx: float, cy: float, s: float):
        # Bell shape — rounded top, flared bottom
        path = QPainterPath()
        path.moveTo(cx - s * 0.28, cy + s * 0.20)
        path.cubicTo(QPointF(cx - s * 0.30, cy - s * 0.10),
                     QPointF(cx - s * 0.20, cy - s * 0.30),
                     QPointF(cx,            cy - s * 0.30))
        path.cubicTo(QPointF(cx + s * 0.20, cy - s * 0.30),
                     QPointF(cx + s * 0.30, cy - s * 0.10),
                     QPointF(cx + s * 0.28, cy + s * 0.20))
        path.closeSubpath()
        p.drawPath(path)
        # Top knob
        p.drawEllipse(QPointF(cx, cy - s * 0.34), s * 0.06, s * 0.06)
        # Bottom rim
        p.drawRoundedRect(QRectF(cx - s * 0.30, cy + s * 0.20, s * 0.60, s * 0.08),
                          s * 0.04, s * 0.04)
        # Clapper
        p.setBrush(self._light)
        p.drawEllipse(QPointF(cx, cy + s * 0.32), s * 0.04, s * 0.04)
        # Sound wave arcs
        p.setBrush(Qt.BrushStyle.NoBrush)
        pen = QPen(self._color, max(1.2, s * 0.025))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        for r_off in (s * 0.40, s * 0.50):
            p.drawArc(QRectF(cx - r_off, cy - r_off, r_off * 2, r_off * 2),
                      -30 * 16, 60 * 16)

    def _draw_spots(self, p: QPainter, cx: float, cy: float, s: float):
        # Outer ring
        outer_r = s * 0.42
        p.drawEllipse(QPointF(cx, cy), outer_r, outer_r)
        # Inner darker disc
        p.setBrush(QColor(0, 0, 0, 80))
        p.drawEllipse(QPointF(cx, cy), outer_r * 0.78, outer_r * 0.78)
        # $ symbol
        p.setPen(QPen(self._light, max(2, s * 0.08), Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap))
        # vertical bar
        p.drawLine(QPointF(cx, cy - s * 0.22), QPointF(cx, cy + s * 0.22))
        # S curve approx with two arcs
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(QRectF(cx - s * 0.13, cy - s * 0.18, s * 0.26, s * 0.18),
                  10 * 16, 180 * 16)
        p.drawArc(QRectF(cx - s * 0.13, cy, s * 0.26, s * 0.18),
                  190 * 16, 180 * 16)

    def _draw_sweepers(self, p: QPainter, cx: float, cy: float, s: float):
        # Handle (diagonal rect)
        p.save()
        p.translate(cx, cy)
        p.rotate(-30)
        p.drawRoundedRect(QRectF(-s * 0.04, -s * 0.40, s * 0.08, s * 0.50),
                          s * 0.04, s * 0.04)
        # Trapezoid head
        head = QPolygonF([
            QPointF(-s * 0.18, s * 0.10),
            QPointF( s * 0.18, s * 0.10),
            QPointF( s * 0.24, s * 0.22),
            QPointF(-s * 0.24, s * 0.22),
        ])
        p.drawPolygon(head)
        # Bristles (5 lines)
        pen = QPen(self._light, max(1.5, s * 0.04), Qt.PenStyle.SolidLine,
                   Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        for i in range(-2, 3):
            x = i * s * 0.085
            p.drawLine(QPointF(x, s * 0.22), QPointF(x * 1.4, s * 0.40))
        p.restore()
        # Sparkle (4-point star top-right)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self._light)
        sx, sy = cx + s * 0.32, cy - s * 0.30
        spk = QPolygonF([
            QPointF(sx, sy - s * 0.10),
            QPointF(sx + s * 0.04, sy - s * 0.04),
            QPointF(sx + s * 0.10, sy),
            QPointF(sx + s * 0.04, sy + s * 0.04),
            QPointF(sx, sy + s * 0.10),
            QPointF(sx - s * 0.04, sy + s * 0.04),
            QPointF(sx - s * 0.10, sy),
            QPointF(sx - s * 0.04, sy - s * 0.04),
        ])
        p.drawPolygon(spk)

    def _draw_instant(self, p: QPainter, cx: float, cy: float, s: float):
        # Lightning bolt polygon
        bolt = QPolygonF([
            QPointF(cx + s * 0.04,  cy - s * 0.36),
            QPointF(cx - s * 0.18,  cy - s * 0.02),
            QPointF(cx - s * 0.02,  cy - s * 0.02),
            QPointF(cx - s * 0.10,  cy + s * 0.36),
            QPointF(cx + s * 0.18,  cy + s * 0.00),
            QPointF(cx + s * 0.02,  cy + s * 0.00),
            QPointF(cx + s * 0.14,  cy - s * 0.36),
        ])
        p.drawPolygon(bolt)
        # Sparks
        p.setBrush(self._light)
        for px, py, r in [(cx - s * 0.32, cy - s * 0.20, s * 0.04),
                          (cx + s * 0.30, cy - s * 0.30, s * 0.03),
                          (cx + s * 0.34, cy + s * 0.10, s * 0.04),
                          (cx - s * 0.30, cy + s * 0.28, s * 0.03)]:
            p.drawEllipse(QPointF(px, py), r, r)

    def _draw_stitcher(self, p: QPainter, cx: float, cy: float, s: float):
        # Big 4-point star
        def star(cx_, cy_, R, r):
            return QPolygonF([
                QPointF(cx_,     cy_ - R),
                QPointF(cx_ + r, cy_ - r),
                QPointF(cx_ + R, cy_),
                QPointF(cx_ + r, cy_ + r),
                QPointF(cx_,     cy_ + R),
                QPointF(cx_ - r, cy_ + r),
                QPointF(cx_ - R, cy_),
                QPointF(cx_ - r, cy_ - r),
            ])
        p.drawPolygon(star(cx, cy, s * 0.34, s * 0.10))
        # Small star top-right
        p.setBrush(self._light)
        p.drawPolygon(star(cx + s * 0.30, cy - s * 0.28, s * 0.10, s * 0.03))
        # Small star bottom-left
        p.drawPolygon(star(cx - s * 0.30, cy + s * 0.30, s * 0.08, s * 0.025))
        # Twinkle dots
        for px, py, r in [(cx + s * 0.32, cy + s * 0.10, s * 0.025),
                          (cx - s * 0.32, cy - s * 0.04, s * 0.020)]:
            p.drawEllipse(QPointF(px, py), r, r)
