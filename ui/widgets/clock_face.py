"""
Premium-theme circular clock face widget.

Used by the Clock Editor (Figma 285:2 / Frame 11). May be reused later
by the Auto Schedule preview, the Final Log creator's hour summary, etc.

Geometry (Figma 288:37 inner frame, normalized to 648 × 380):
  - Outer glow ellipse:   320 × 320 at (163, 29)
  - Inner clock circle:   280 × 280 at (183, 49)
  - Arc segments live in the annular band between r_in and r_out
  - 12 tick marks at hour positions on the inner edge

Arc geometry:
  - Minute 0 sits at the top (12 o'clock = 90° in Qt math)
  - Each minute sweeps -6° clockwise
  - Each segment occupies a sweep proportional to ``duration_seconds``

Selection: click an arc → emits ``element_clicked(idx)``. Selected arc
paints with bright white outline + glow. Click on empty area emits -1.
"""

from __future__ import annotations

import math
from typing import Optional

from PyQt6.QtCore import Qt, QRect, QRectF, QPoint, QPointF, pyqtSignal
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QLinearGradient, QRadialGradient,
    QFont, QMouseEvent, QPaintEvent, QPainterPath,
)
from PyQt6.QtWidgets import QWidget

from ui.widgets.tokens import (
    inter, mono,
    COL_CYAN, COL_CYAN_LT,
    COL_PURPLE_LT,
    COL_GREEN_LT,
    COL_AMBER, COL_AMBER_LT,
    COL_PINK,
    COL_TEAL_LT,
    COL_TEXT_DIM, COL_TEXT_MUTED,
    qcolor_a as _qcolor,
)


# ── Constants the widget owns ────────────────────────────────────────────

# Default per-UI-element-type accent color (matches Figma 285:2 type icon
# row). Public so other modules (e.g. type-tile button) can share.
ELEMENT_TYPE_COLORS = {
    "song":    COL_AMBER_LT,    # ♪
    "jingle":  COL_CYAN_LT,     # 🔔
    "spot":    COL_GREEN_LT,    # $   (DB slot_type = "break")
    "voice":   "#f472b6",       # 🎤  pink
    "sweeper": COL_PURPLE_LT,   # ★
}

# Sensible duration defaults when an element doesn't carry its own.
DEFAULT_DURATION_S = {
    "song":    240,
    "jingle":  8,
    "spot":    30,
    "voice":   30,
    "sweeper": 8,
}

DEFAULT_COLORIZE_BY = "type"   # "type" | "category" | "era"


# ════════════════════════════════════════════════════════════════════════
# CLOCK FACE WIDGET — circular, custom-paint, click-to-select
# ════════════════════════════════════════════════════════════════════════

class ClockFaceWidget(QWidget):
    """The big circular clock face (648 × 380 area)."""

    element_clicked = pyqtSignal(int)   # -1 = clicked empty area

    # Geometry constants
    _W, _H = 648, 380
    _CENTER = QPointF(_W / 2, _H / 2 + 10)   # +10 visual nudge per Figma
    _R_GLOW       = 160       # outer glow ellipse radius
    _R_OUTER      = 140       # outer arc edge
    _R_INNER      = 110       # inner arc edge (band thickness 30)
    _R_CIRCLE     = 140       # cyan border circle radius
    _R_CENTER_DOT = 4

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(self._W, self._H)
        self._elements: list[dict] = []
        self._selected_idx: Optional[int] = None
        self._colorize_by: str = DEFAULT_COLORIZE_BY

        # Pre-cached painter resources
        self._font_empty_title = inter(10, QFont.Weight.Bold, letter_spacing=1.5)
        self._font_empty_hint  = inter(10, QFont.Weight.Medium)
        self._font_minute      = mono(8, bold=False)

        # Per-element computed paint state, recomputed on data change.
        # Tuple shape: (path, hex_color, start_min, dur_min) — used by
        # both paintEvent and _hit_test.
        self._segment_paths: list[tuple[QPainterPath, str, float, float]] = []

        self._tick_path = self._build_tick_path()

    # ── Public API ───────────────────────────────────────────────────────

    def set_elements(self, elements: list[dict]) -> None:
        """Replace the displayed elements. ``elements`` are dicts with at
        least: ``element_type``, ``minute_position``, ``duration_seconds``.
        Optional: ``category_color``, ``era`` (for the "category" / "era"
        colorize-by modes)."""
        self._elements = list(elements or [])
        self._rebuild_paths()
        self.update(self.rect())

    def set_selected(self, idx: Optional[int]) -> None:
        if idx == self._selected_idx:
            return
        self._selected_idx = idx
        self.update(self.rect())

    def selected_idx(self) -> Optional[int]:
        return self._selected_idx

    def set_colorize_by(self, mode: str) -> None:
        if mode == self._colorize_by:
            return
        self._colorize_by = mode if mode in ("type", "category", "era") else "type"
        self._rebuild_paths()
        self.update(self.rect())

    # ── Geometry helpers ─────────────────────────────────────────────────

    @classmethod
    def _polar(cls, radius: float, angle_deg: float) -> QPointF:
        """Center-relative point at (radius, angle). Angle 90° = 12
        o'clock; positive direction = counter-clockwise (Qt math)."""
        rad = math.radians(angle_deg)
        return QPointF(cls._CENTER.x() + radius * math.cos(rad),
                       cls._CENTER.y() - radius * math.sin(rad))

    def _build_tick_path(self) -> QPainterPath:
        """12 short tick marks at the hour positions (0, 5, 10, ... 55)."""
        path = QPainterPath()
        for i in range(12):
            angle_deg = 90 - i * 30
            outer = self._polar(self._R_CIRCLE - 2, angle_deg)
            inner = self._polar(self._R_CIRCLE - 8, angle_deg)
            path.moveTo(outer); path.lineTo(inner)
        return path

    @classmethod
    def _segment_path(cls, start_min: float, dur_min: float,
                      r_inner: float, r_outer: float) -> QPainterPath:
        """Build an annular wedge from start_min for dur_min minutes."""
        a0 = 90 - start_min * 6
        a1 = 90 - (start_min + dur_min) * 6
        rect_outer = QRectF(cls._CENTER.x() - r_outer, cls._CENTER.y() - r_outer,
                            2 * r_outer, 2 * r_outer)
        rect_inner = QRectF(cls._CENTER.x() - r_inner, cls._CENTER.y() - r_inner,
                            2 * r_inner, 2 * r_inner)
        path = QPainterPath()
        p_start_outer = cls._polar(r_outer, a0)
        path.moveTo(p_start_outer)
        path.arcTo(rect_outer, a0, a1 - a0)        # outer (clockwise)
        p_end_inner = cls._polar(r_inner, a1)
        path.lineTo(p_end_inner)
        path.arcTo(rect_inner, a1, a0 - a1)        # inner (counter-clockwise)
        path.closeSubpath()
        return path

    def _rebuild_paths(self) -> None:
        """Compute one path + color per element. Total clock = 60 minutes;
        elements that overflow are clipped to the remaining minutes (caller
        flags overflow via a status bar)."""
        out: list[tuple[QPainterPath, str, float, float]] = []
        running_min = 0.0
        for el in self._elements:
            mp = el.get("minute_position")
            start_m = float(mp) if mp is not None else running_min
            dur_s = el.get("duration_seconds") or DEFAULT_DURATION_S.get(
                el.get("element_type") or "song", 240)
            dur_m = max(0.5, min(60.0 - start_m, float(dur_s) / 60.0))
            color = self._color_for(el)
            path = self._segment_path(start_m, dur_m,
                                      self._R_INNER, self._R_OUTER)
            out.append((path, color, start_m, dur_m))
            running_min = start_m + dur_m
        self._segment_paths = out

    def _color_for(self, el: dict) -> str:
        if self._colorize_by == "category":
            return el.get("category_color") or ELEMENT_TYPE_COLORS.get(
                el.get("element_type") or "song", COL_AMBER_LT)
        if self._colorize_by == "era":
            era = (el.get("era") or "").lower()
            return {"60s": COL_AMBER_LT, "70s": COL_AMBER, "80s": COL_PINK,
                    "90s": COL_PURPLE_LT, "2000s": COL_CYAN_LT,
                    "2010s": COL_TEAL_LT, "2020s": COL_GREEN_LT,
                    }.get(era, COL_TEXT_MUTED)
        return ELEMENT_TYPE_COLORS.get(
            el.get("element_type") or "song", COL_AMBER_LT)

    # ── Hit testing ──────────────────────────────────────────────────────

    def _hit_test(self, p: QPoint) -> Optional[int]:
        pt = QPointF(p.x(), p.y())
        for idx, (path, _c, _s, _d) in enumerate(self._segment_paths):
            if path.contains(pt):
                return idx
        return None

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            idx = self._hit_test(e.position().toPoint())
            if idx is not None:
                self.set_selected(idx)
                self.element_clicked.emit(int(idx))
            else:
                self.set_selected(None)
                self.element_clicked.emit(-1)
        super().mousePressEvent(e)

    # ── Paint ────────────────────────────────────────────────────────────

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        cx, cy = self._CENTER.x(), self._CENTER.y()

        # Outer glow ring (cyan radial)
        glow = QRadialGradient(QPointF(cx, cy), self._R_GLOW)
        glow.setColorAt(0.55, QColor(0, 0, 0, 0))
        glow.setColorAt(0.85, _qcolor(COL_CYAN, 0.18))
        glow.setColorAt(1.00, _qcolor(COL_CYAN, 0.0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(glow))
        p.drawEllipse(QPointF(cx, cy), self._R_GLOW, self._R_GLOW)

        # Inner clock disc (very dark, cyan border)
        p.setBrush(QColor(0, 4, 10, 230))
        p.setPen(QPen(_qcolor(COL_CYAN, 0.45), 1.5))
        p.drawEllipse(QPointF(cx, cy), self._R_CIRCLE, self._R_CIRCLE)

        # Tick marks
        p.setPen(QPen(QColor(255, 255, 255, 64), 2))
        p.drawPath(self._tick_path)

        # Arc segments (if populated)
        if self._segment_paths:
            for idx, (path, color_hex, _s, _d) in enumerate(self._segment_paths):
                is_sel = (idx == self._selected_idx)
                grad = QRadialGradient(QPointF(cx, cy), self._R_OUTER)
                grad.setColorAt(0.65, _qcolor(color_hex, 0.0))
                grad.setColorAt(0.75, _qcolor(color_hex, 0.45))
                grad.setColorAt(1.00, _qcolor(color_hex, 0.85))
                p.setBrush(QBrush(grad))
                if is_sel:
                    p.setPen(QPen(QColor(255, 255, 255, 240), 1.8))
                else:
                    p.setPen(QPen(_qcolor(color_hex, 0.55), 1.0))
                p.drawPath(path)

        # Center dot
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_qcolor(COL_CYAN, 0.95))
        p.drawEllipse(QPointF(cx, cy),
                      self._R_CENTER_DOT, self._R_CENTER_DOT)

        # Empty state hint
        if not self._segment_paths:
            p.setPen(QColor(COL_TEXT_DIM))
            p.setFont(self._font_empty_title)
            p.drawText(QRectF(cx - 60, cy + 25, 120, 14),
                       Qt.AlignmentFlag.AlignCenter, "EMPTY CLOCK")
            p.setFont(self._font_empty_hint)
            p.drawText(QRectF(cx - 100, cy + 41, 200, 14),
                       Qt.AlignmentFlag.AlignCenter,
                       "Click + Add to insert elements")
        p.end()
