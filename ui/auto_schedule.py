"""
RadioAI Studio Pro — Main Auto Schedule (Figma 278:2 — Premium Dark).

The central scheduling screen. Routes from Hub → "Main Auto Schedule".
24 hours × 7 days grid editor. Multi-select cells, pick a clock from the
left rail, hit SET to assign. Mode switch between Weekdays (write
expansion to Mon-Fri uniformly) and Specific Days (per-cell).

Storage / wiring contract
-------------------------
- All schedule CRUD goes through the live ``Database`` singleton —
  ``db.get_auto_schedule_grid()``, ``db.set_auto_schedule_cell``,
  ``db.clear_auto_schedule_cell``, ``db.clear_all_auto_schedule``.
- All clock CRUD via ``db.get_all_clocks``, ``db.create_clock``,
  ``db.delete_clock``, ``db.duplicate_clock``.
- ``SchedulerEngine`` is read-only here. It re-queries the DB on every
  tick for the active clock, so DB writes propagate naturally — no
  refresh signal to fire after a write.
- Mode persists in the ``settings`` table under
  ``"auto_schedule.mode"`` (values ``"weekdays"`` / ``"specific"``).
- Frame 11 (Clock Editor) is not built yet — Create / Edit / Duplicate
  emit ``screen_requested("clock_*")`` and MainWindow falls through to
  the generic "coming soon" toast.

Layout (1440 × 900)
-------------------
  HEADER     1440 ×  88
  Title block @ y=116..220 (breadcrumb / title / subtitle)

  LEFT RAIL  (x=56, w=280)
    Available Clocks  280 × 240    @ y=240..480
    SET button        280 ×  80    @ y=496..576
    Action stack      280 ×  38×4  @ y=592..756 (gap 4)
    Auto Program …    280 ×  44    @ y=776..820

  RIGHT GRID (x=360, w=1024)
    Card              1024 × 580   @ y=240..820
      Header strip    1024 ×  60   (title + tabs + Clear)
      Day header row  992  ×  36
      Grid           992  × 480    (24 rows × 20h, 7 day cols × 128 pitch)

═══════════════════════════════════════════════════════════════════════════
PERFORMANCE INVARIANTS — DO NOT VIOLATE
═══════════════════════════════════════════════════════════════════════════
  1. event.rect() clipping in every paintEvent (especially the grid).
  2. Grid is one custom-paint widget — NOT 168 child widgets.
  3. mouseMoveEvent → self.update(QRect) on cell-region union, not bare.
  4. No setMouseTracking — drag only when button held.
  5. No DB calls in paintEvent — all data preloaded into model dicts.
  6. No self.update() inside paintEvent.
  7. No nested QScrollArea (parent MainWindow handles overflow).
  8. Cached QGradient / QColor / QFont in __init__.
  9. Drop shadows via QGraphicsDropShadowEffect, never paint blurs.
═══════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import logging
from typing import Optional, Literal
from core import dialogs

from PyQt6.QtCore import (
    Qt, QRect, QRectF, QPoint, QPointF, QTimer, pyqtSignal,
)
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QLinearGradient, QFont,
    QMouseEvent, QKeyEvent, QPaintEvent, QPolygonF, QWheelEvent,
)
from PyQt6.QtWidgets import (
    QWidget, QMessageBox, QGraphicsDropShadowEffect,
)

from ui.widgets.tokens import (
    inter, mono,
    COL_BG_TOP, COL_BG_MID, COL_BG_BOT,
    COL_CARD_TOP, COL_CARD_BOT,
    COL_BORDER_FAINT,
    COL_CYAN, COL_CYAN_LT, COL_CYAN_DK, COL_CYAN_MD,
    COL_PURPLE, COL_PURPLE_LT, COL_PURPLE_DEEP, COL_PURPLE_MID,
    COL_GREEN, COL_GREEN_LT, COL_GREEN_DK, COL_GREEN_MD,
    COL_AMBER, COL_AMBER_LT, COL_AMBER_DK, COL_AMBER_MD,
    COL_ROSE, COL_ROSE_LT, COL_ROSE_DK, COL_ROSE_MD,
    COL_PINK, COL_PINK_LT, COL_PINK_DK, COL_PINK_MD,
    COL_TEAL, COL_TEAL_LT, COL_TEAL_DK, COL_TEAL_MD,
    COL_TEXT_PRIMARY, COL_TEXT_SECONDARY, COL_TEXT_MUTED, COL_TEXT_DIM,
    qcolor_a as _qcolor,
)
from ui.widgets.app_chrome import (
    Header, LiveTimePill, drop_shadow,
    WINDOW_W, HEADER_H,
)

log = logging.getLogger("AutoSchedule")

WINDOW_H = 900

# ── Storage / mode constants ─────────────────────────────────────────────
SETTINGS_KEY_MODE = "auto_schedule.mode"
MODE_WEEKDAYS = "weekdays"
MODE_SPECIFIC = "specific"
DEFAULT_MODE = MODE_WEEKDAYS

Mode = Literal["weekdays", "specific"]

DAY_NAMES = [
    "Monday", "Tuesday", "Wednesday", "Thursday",
    "Friday", "Saturday", "Sunday",
]
DAY_NAMES_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
WEEKDAY_INDICES = (0, 1, 2, 3, 4)    # Mon..Fri (per Python weekday())

# Stable clock color palette — indexed by id so colors survive restart.
_CLOCK_PALETTE = [
    COL_PURPLE_MID, COL_CYAN, COL_GREEN, COL_AMBER, COL_ROSE,
    COL_PINK, COL_TEAL, COL_PURPLE_DEEP, COL_CYAN_DK, COL_AMBER_MD,
]


def color_for_clock_id(cid) -> str:
    """Deterministic hex for a clock id. Survives restart (palette index
    = id % len). Returns the muted text color for None."""
    if cid is None:
        return COL_TEXT_DIM
    return _CLOCK_PALETTE[int(cid) % len(_CLOCK_PALETTE)]


# ── Grid geometry (relative to _ScheduleGrid widget origin) ──────────────
GRID_W        = 992
GRID_H        = 480
TIME_COL_W    = 100
CELL_PITCH_X  = 128       # 120 cell + 8 gutter
CELL_W        = 120
CELL_H        = 16
ROW_H         = 20
CELL_PAD_Y    = 2         # cell starts 2px below row top
N_HOURS       = 24
N_DAYS        = 7


def _cell_rect(d: int, h: int) -> QRect:
    """Cell rect in _ScheduleGrid local coords."""
    x = TIME_COL_W + d * CELL_PITCH_X
    y = h * ROW_H + CELL_PAD_Y
    return QRect(x, y, CELL_W, CELL_H)


# ════════════════════════════════════════════════════════════════════════
# CLOCK ROW — 248 × 52 row inside the Available Clocks panel
# ════════════════════════════════════════════════════════════════════════

class _ClockRow(QWidget):
    """One clock row. Click → ``clicked(clock_id)``."""

    clicked = pyqtSignal(int)

    def __init__(self, clock_id: int, name: str, desc: str,
                 accent_hex: str, parent=None):
        super().__init__(parent)
        self.setFixedSize(248, 52)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._cid = int(clock_id)
        self._name = name or "Clock"
        self._desc = desc or ""
        self._accent = accent_hex
        self._selected = False
        self._hint = ""
        self._font_name = inter(13, QFont.Weight.Bold)
        self._font_desc = inter(10, QFont.Weight.Medium)
        self._font_hint = mono(10, bold=False)

    @property
    def clock_id(self) -> int:
        return self._cid

    def set_selected(self, on: bool) -> None:
        if bool(on) == self._selected:
            return
        self._selected = bool(on)
        if self._selected:
            self.setGraphicsEffect(
                drop_shadow(20, _qcolor(COL_ROSE, 0.5), 4))
        else:
            self.setGraphicsEffect(None)
        self.update(self.rect())

    def set_hint(self, txt: str) -> None:
        if (txt or "") == self._hint:
            return
        self._hint = txt or ""
        self.update(self.rect())

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._cid)
        super().mousePressEvent(e)

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self)
        p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        if self._selected:
            grad = QLinearGradient(0, 0, self.width(), 0)
            grad.setColorAt(0.0, _qcolor(COL_ROSE, 0.18))
            grad.setColorAt(1.0, _qcolor(COL_ROSE, 0.06))
            p.fillRect(r, QBrush(grad))
            pen = QPen(_qcolor(COL_ROSE, 0.55)); pen.setWidthF(1.0)
        else:
            p.fillRect(r, _qcolor(COL_CYAN, 0.04))
            pen = QPen(QColor(255, 255, 255, 22)); pen.setWidthF(1.0)
        p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        # Color dot
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(self._accent))
        p.drawEllipse(QRectF(12, 22, 8, 8))
        # Name
        p.setPen(QColor(COL_TEXT_PRIMARY))
        p.setFont(self._font_name)
        p.drawText(QRectF(28, 6, 140, 18),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._name)
        # Description
        p.setPen(QColor(COL_TEXT_MUTED))
        p.setFont(self._font_desc)
        p.drawText(QRectF(28, 24, 140, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._desc)
        # Hint (right side, only when selected with text)
        if self._selected and self._hint:
            p.setPen(_qcolor(COL_ROSE_LT, 0.95))
            p.setFont(self._font_hint)
            p.drawText(QRectF(160, 19, 80, 14),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       self._hint)
        p.end()


# ════════════════════════════════════════════════════════════════════════
# AVAILABLE CLOCKS PANEL — 280 × 240
# ════════════════════════════════════════════════════════════════════════

class _ClocksPanel(QWidget):
    """Card with amber top accent, clock list, count badge.

    Renders ALL clocks (not just the top 3) and scrolls the visible window
    of 3 rows via mouse wheel + ▲/▼ chevron buttons. No nested QScrollArea
    (per file perf invariant #7) — uses absolute child positioning with a
    snap-to-row scroll offset and a custom-painted track.
    """

    clock_selected = pyqtSignal(int)

    # Layout constants — the visible row window inside the 280×240 card
    _ROWS_TOP     = 44      # y of the first visible row
    _ROWS_PITCH   = 60      # row spacing (row 52h + 8 gutter)
    _ROWS_VISIBLE = 3       # how many rows fit at once
    _BTN_X        = 266     # chevron column (right edge of card, after rows)
    _BTN_W        = 12

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(280, 240)
        self._rows: list[_ClockRow] = []
        self._selected_id: Optional[int] = None
        self._scroll_y: int = 0          # offset in px; snapped to _ROWS_PITCH
        self._max_scroll: int = 0
        self._count_total: int = 0
        self._hover_up: bool = False
        self._hover_dn: bool = False
        self.setMouseTracking(True)      # for hover state on chevrons
        self._font_title = inter(11, QFont.Weight.Black, letter_spacing=2.0)
        self._font_count = inter(15, QFont.Weight.Bold)

    # ── Public API ────────────────────────────────────────────────────────

    def selected_id(self) -> Optional[int]:
        return self._selected_id

    def set_clocks(self, clocks: list[dict]) -> None:
        """Replace the list. ``clocks`` items shape:
        ``{"id": int, "name": str, "description": str}``.

        All clocks become children; only rows fully inside the 180px window
        (y ∈ [44, 172]) are shown. Wheel / chevron buttons advance the window.
        """
        for r in self._rows:
            r.setParent(None); r.deleteLater()
        self._rows.clear()
        for c in clocks:
            cid = int(c["id"])
            row = _ClockRow(
                cid, str(c.get("name") or "Clock"),
                str(c.get("description") or ""),
                color_for_clock_id(cid), parent=self,
            )
            row.clicked.connect(self._on_row_clicked)
            self._rows.append(row)
        # Recompute max scroll (snapped to row pitch) and re-clamp
        extra = max(0, len(clocks) - self._ROWS_VISIBLE)
        self._max_scroll = extra * self._ROWS_PITCH
        if self._scroll_y > self._max_scroll:
            self._scroll_y = self._max_scroll
        self._relayout_rows()
        # If selected id is gone, clear selection
        if (self._selected_id is not None
                and self._selected_id not in [r.clock_id for r in self._rows]):
            self._selected_id = None
        # Reflect selection state on rows
        for r in self._rows:
            r.set_selected(r.clock_id == self._selected_id)
        # Cache total for the count badge
        self._count_total = len(clocks)
        self.update(self.rect())

    def select_clock(self, cid: Optional[int]) -> None:
        if cid == self._selected_id:
            return
        self._selected_id = cid
        for r in self._rows:
            r.set_selected(r.clock_id == cid)
        self.update(QRect(0, 0, self.width(), 36))   # repaint count area only
        self.clock_selected.emit(int(cid)) if cid is not None \
            else self.clock_selected.emit(-1)

    def set_hint_for(self, cid: int, hint: str) -> None:
        for r in self._rows:
            if r.clock_id == cid:
                r.set_hint(hint)
                return

    def visible_rows(self) -> list["_ClockRow"]:
        """Subset of ``_rows`` currently inside the 3-row visible window.
        Used by tests + selection plumbing that cares about what the
        operator can actually click."""
        return [r for r in self._rows if not r.isHidden()]

    def scroll_to_clock(self, cid: int) -> None:
        """Ensure the row for ``cid`` is in the visible window. No-op if
        already visible. Called after selection from external code."""
        for i, r in enumerate(self._rows):
            if r.clock_id == int(cid):
                # Row natural y at scroll=0 is _ROWS_TOP + i * _ROWS_PITCH.
                # Pick a scroll that places it inside [_ROWS_TOP, _ROWS_TOP + 2*PITCH].
                natural_y = self._ROWS_TOP + i * self._ROWS_PITCH
                # Snap scroll so the target row sits at one of the visible slots.
                min_scroll = max(0,
                                 natural_y - (self._ROWS_TOP + (self._ROWS_VISIBLE - 1)
                                              * self._ROWS_PITCH))
                max_scroll = max(0, natural_y - self._ROWS_TOP)
                clamped = max(min_scroll, min(self._scroll_y, max_scroll))
                clamped = max(0, min(self._max_scroll, clamped))
                # Snap to row pitch
                clamped = (clamped // self._ROWS_PITCH) * self._ROWS_PITCH
                if clamped != self._scroll_y:
                    self._scroll_y = clamped
                    self._relayout_rows()
                    self.update(self.rect())
                return

    # ── Scroll plumbing ───────────────────────────────────────────────────

    def _relayout_rows(self) -> None:
        """Position every row absolutely; show only the 3 fully inside the
        180px visible band. Rows outside the band are hidden so they
        can't receive clicks."""
        for i, row in enumerate(self._rows):
            y = self._ROWS_TOP + i * self._ROWS_PITCH - self._scroll_y
            row.move(16, y)
            # Row height is 52; visible if 44 <= y <= 172 (so y+52 <= 224)
            if self._ROWS_TOP <= y <= (self._ROWS_TOP
                                       + (self._ROWS_VISIBLE - 1) * self._ROWS_PITCH):
                row.show()
            else:
                row.hide()

    def _scroll_by(self, delta_rows: int) -> None:
        """Step the visible window by ``delta_rows`` (positive = scroll down).
        Snaps to row pitch."""
        if self._max_scroll <= 0:
            return
        new = self._scroll_y + delta_rows * self._ROWS_PITCH
        new = max(0, min(self._max_scroll, new))
        if new == self._scroll_y:
            return
        self._scroll_y = new
        self._relayout_rows()
        self.update(self.rect())

    def _can_scroll(self) -> bool:
        return self._max_scroll > 0

    def _can_scroll_up(self) -> bool:
        return self._scroll_y > 0

    def _can_scroll_dn(self) -> bool:
        return self._scroll_y < self._max_scroll

    def _up_btn_rect(self) -> QRect:
        return QRect(self._BTN_X, 44, self._BTN_W, 14)

    def _dn_btn_rect(self) -> QRect:
        return QRect(self._BTN_X, 210, self._BTN_W, 14)

    # ── Event handlers ────────────────────────────────────────────────────

    def wheelEvent(self, e: QWheelEvent) -> None:
        if self._max_scroll <= 0:
            super().wheelEvent(e); return
        dy = e.angleDelta().y()
        self._scroll_by(-1 if dy > 0 else 1)
        e.accept()

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton and self._can_scroll():
            pt = e.position().toPoint()
            if self._up_btn_rect().contains(pt):
                self._scroll_by(-1); e.accept(); return
            if self._dn_btn_rect().contains(pt):
                self._scroll_by(1); e.accept(); return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        pt = e.position().toPoint()
        new_up = self._can_scroll_up() and self._up_btn_rect().contains(pt)
        new_dn = self._can_scroll_dn() and self._dn_btn_rect().contains(pt)
        if new_up != self._hover_up or new_dn != self._hover_dn:
            self._hover_up = new_up
            self._hover_dn = new_dn
            self.update(self.rect())
        super().mouseMoveEvent(e)

    def leaveEvent(self, e):
        if self._hover_up or self._hover_dn:
            self._hover_up = False
            self._hover_dn = False
            self.update(self.rect())
        super().leaveEvent(e)

    def _on_row_clicked(self, cid: int) -> None:
        # Toggle: clicking the already-selected row deselects
        new = None if self._selected_id == cid else int(cid)
        self.select_clock(new)

    # ── Paint ─────────────────────────────────────────────────────────────

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        # Card background
        bg = QLinearGradient(0, 0, 0, self.height())
        bg.setColorAt(0.0, QColor(14, 16, 32, 242))
        bg.setColorAt(1.0, QColor(7, 9, 18, 242))
        p.fillRect(r, QBrush(bg))
        # Top accent (3px amber gradient)
        accent = QLinearGradient(0, 0, self.width(), 0)
        accent.setColorAt(0.0, QColor(COL_AMBER))
        accent.setColorAt(1.0, QColor(COL_AMBER_LT))
        p.fillRect(QRectF(0, 0, self.width(), 3), QBrush(accent))
        # Border
        p.setPen(QPen(QColor(255, 255, 255, 18))); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)
        # Title
        p.setPen(_qcolor(COL_AMBER_LT, 0.95))
        p.setFont(self._font_title)
        p.drawText(QRectF(16, 16, 200, 13),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "AVAILABLE CLOCKS")
        # Count badge
        p.setPen(QColor(COL_TEXT_PRIMARY))
        p.setFont(self._font_count)
        p.drawText(QRectF(self.width() - 30, 14, 18, 18),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   str(self._count_total))
        # Scroll chrome — only when scrolling is possible
        if self._can_scroll():
            self._paint_scroll_chrome(p)
        p.end()

    def _paint_scroll_chrome(self, p: QPainter) -> None:
        """Draw ▲/▼ chevron buttons + thin track between them."""
        p.setPen(Qt.PenStyle.NoPen)

        # ▲ button
        up_r = self._up_btn_rect()
        up_hot = self._can_scroll_up()
        up_a = 1.0 if (self._hover_up and up_hot) else (0.85 if up_hot else 0.25)
        ax = up_r.x() + up_r.width() / 2.0
        ay = up_r.y() + 4
        up_poly = QPolygonF([
            QPointF(ax,        ay),
            QPointF(ax - 5.0,  ay + 6.0),
            QPointF(ax + 5.0,  ay + 6.0),
        ])
        p.setBrush(_qcolor(COL_AMBER_LT, up_a))
        p.drawPolygon(up_poly)

        # ▼ button
        dn_r = self._dn_btn_rect()
        dn_hot = self._can_scroll_dn()
        dn_a = 1.0 if (self._hover_dn and dn_hot) else (0.85 if dn_hot else 0.25)
        bx = dn_r.x() + dn_r.width() / 2.0
        by = dn_r.y() + 10
        dn_poly = QPolygonF([
            QPointF(bx,        by),
            QPointF(bx - 5.0,  by - 6.0),
            QPointF(bx + 5.0,  by - 6.0),
        ])
        p.setBrush(_qcolor(COL_AMBER_LT, dn_a))
        p.drawPolygon(dn_poly)

        # Track + thumb between the two chevrons
        track_x = self._BTN_X + (self._BTN_W // 2) - 1   # centred under chevrons
        track_y = 64
        track_h = 140
        p.setBrush(QColor(255, 255, 255, 22))
        p.drawRoundedRect(QRectF(track_x, track_y, 3, track_h), 1.5, 1.5)
        # Thumb size proportional to visible/total ratio
        visible_h = self._ROWS_VISIBLE * self._ROWS_PITCH       # 180
        total_h = visible_h + self._max_scroll
        thumb_ratio = visible_h / total_h if total_h > 0 else 1.0
        thumb_h = max(24, int(track_h * thumb_ratio))
        thumb_max_off = max(0, track_h - thumb_h)
        thumb_off = (int(self._scroll_y / self._max_scroll * thumb_max_off)
                     if self._max_scroll > 0 else 0)
        p.setBrush(_qcolor(COL_AMBER, 0.85))
        p.drawRoundedRect(QRectF(track_x, track_y + thumb_off, 3, thumb_h),
                          1.5, 1.5)


# ════════════════════════════════════════════════════════════════════════
# SET BUTTON — 280 × 80 primary rose CTA
# ════════════════════════════════════════════════════════════════════════

class _SetButton(QWidget):
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(280, 80)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._enabled = False
        self._hover = False
        self._font_set = inter(28, QFont.Weight.Black, letter_spacing=4.0)
        self._font_arrow = inter(28, QFont.Weight.Black)
        self._font_help = inter(9, QFont.Weight.Bold, letter_spacing=1.4)
        self.setGraphicsEffect(drop_shadow(24, _qcolor(COL_ROSE, 0.45), 6))

    def set_enabled(self, on: bool) -> None:
        if on == self._enabled:
            return
        self._enabled = bool(on)
        self.setCursor(Qt.CursorShape.PointingHandCursor if on
                       else Qt.CursorShape.ForbiddenCursor)
        if on:
            self.setGraphicsEffect(drop_shadow(24, _qcolor(COL_ROSE, 0.45), 6))
        else:
            self.setGraphicsEffect(None)
        self.update(self.rect())

    def enterEvent(self, e):
        if self._enabled and not self._hover:
            self._hover = True; self.update(self.rect())
        super().enterEvent(e)

    def leaveEvent(self, e):
        if self._hover:
            self._hover = False; self.update(self.rect())
        super().leaveEvent(e)

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if self._enabled and e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        if self._enabled:
            base_a = QColor(COL_ROSE);    base_a.setAlpha(255 if self._hover else 235)
            base_b = QColor(COL_ROSE_DK); base_b.setAlpha(255 if self._hover else 235)
            grad = QLinearGradient(0, 0, 0, self.height())
            grad.setColorAt(0.0, base_a); grad.setColorAt(1.0, base_b)
            p.fillRect(r, QBrush(grad))
        else:
            p.fillRect(r, QColor(255, 255, 255, 12))
        # Top sheen (gradient highlight)
        sheen = QLinearGradient(0, 0, 0, 28)
        sheen.setColorAt(0.0, QColor(255, 255, 255, 60 if self._enabled else 14))
        sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.fillRect(QRectF(1, 1, self.width() - 2, 28), QBrush(sheen))
        # Border
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_qcolor(COL_ROSE_LT, 0.5 if self._enabled else 0.15)))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)
        # SET text + arrows centered horizontally on top
        p.setPen(QColor(COL_TEXT_PRIMARY) if self._enabled
                 else QColor(COL_TEXT_DIM))
        p.setFont(self._font_set)
        p.drawText(QRectF(0, 8, 220, 36),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   "SET")
        p.setFont(self._font_arrow)
        p.drawText(QRectF(228, 8, 50, 36),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "›››")
        # Helper text — shorter copy: the old 41-char line was wider
        # than the button and Qt clipped BOTH ends (audit 2026-07-03).
        p.setPen(_qcolor(COL_TEXT_PRIMARY, 0.85 if self._enabled else 0.35))
        p.setFont(self._font_help)
        p.drawText(QRectF(8, 50, self.width() - 16, 16),
                   Qt.AlignmentFlag.AlignCenter,
                   "APPLY CLOCK TO SELECTED CELLS")
        p.end()


# ════════════════════════════════════════════════════════════════════════
# ACTION BUTTONS — 280 × 38 row in the action stack
# ════════════════════════════════════════════════════════════════════════

class _ActionRowButton(QWidget):
    """Generic accent-tinted action row. Icon char + label."""

    clicked = pyqtSignal()

    def __init__(self, icon: str, label: str, accent_hex: str,
                 parent=None):
        super().__init__(parent)
        self.setFixedSize(280, 38)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._icon = icon
        self._label = label
        self._accent = accent_hex
        self._enabled = True
        self._hover = False
        self._font_icon  = inter(13, QFont.Weight.Bold)
        self._font_label = inter(12, QFont.Weight.Bold, letter_spacing=-0.1)

    def set_enabled(self, on: bool) -> None:
        if on == self._enabled:
            return
        self._enabled = bool(on)
        self.setCursor(Qt.CursorShape.PointingHandCursor if on
                       else Qt.CursorShape.ForbiddenCursor)
        self.update(self.rect())

    def enterEvent(self, e):
        if self._enabled and not self._hover:
            self._hover = True; self.update(self.rect())
        super().enterEvent(e)

    def leaveEvent(self, e):
        if self._hover:
            self._hover = False; self.update(self.rect())
        super().leaveEvent(e)

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if self._enabled and e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        bg_alpha = 0.12 if self._hover else 0.06
        if not self._enabled:
            bg_alpha = 0.025
        p.fillRect(r, _qcolor(self._accent, bg_alpha))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_qcolor(self._accent,
                              0.4 if self._enabled else 0.12)))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        # Icon
        p.setPen(_qcolor(self._accent, 0.95 if self._enabled else 0.3))
        p.setFont(self._font_icon)
        p.drawText(QRectF(14, 0, 20, self.height()),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._icon)
        # Label
        p.setPen(QColor(COL_TEXT_PRIMARY) if self._enabled
                 else QColor(COL_TEXT_MUTED))
        p.setFont(self._font_label)
        p.drawText(QRectF(40, 0, self.width() - 48, self.height()),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._label)
        p.end()


# ════════════════════════════════════════════════════════════════════════
# AUTO PROGRAM BUTTON — 280 × 44 footer
# ════════════════════════════════════════════════════════════════════════

class _AutoProgramButton(_ActionRowButton):
    def __init__(self, parent=None):
        super().__init__("⚙", "Auto Program Settings",
                         COL_TEXT_SECONDARY, parent)
        self.setFixedSize(280, 44)


# ════════════════════════════════════════════════════════════════════════
# MODE TAB + CLEAR BUTTON in the schedule card header
# ════════════════════════════════════════════════════════════════════════

class _ModeTab(QWidget):
    clicked = pyqtSignal()

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self.setFixedSize(140, 32)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._label = label
        self._active = False
        self._font = inter(11, QFont.Weight.Bold, letter_spacing=-0.1)

    def set_active(self, on: bool) -> None:
        if on == self._active:
            return
        self._active = bool(on)
        self.update(self.rect())

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        if self._active:
            grad = QLinearGradient(0, 0, 0, self.height())
            grad.setColorAt(0.0, QColor(COL_ROSE))
            grad.setColorAt(1.0, QColor(COL_ROSE_DK))
            p.fillRect(r, QBrush(grad))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(_qcolor(COL_ROSE_LT, 0.6)))
            p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
            p.setPen(QColor(COL_TEXT_PRIMARY))
        else:
            p.fillRect(r, _qcolor(COL_PURPLE_DEEP, 0.18))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(255, 255, 255, 22)))
            p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
            p.setPen(QColor(COL_TEXT_SECONDARY))
        p.setFont(self._font)
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, self._label)
        p.end()


class _ClearButton(QWidget):
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(80, 32)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hover = False
        self._font = inter(11, QFont.Weight.Bold)

    def enterEvent(self, e):
        if not self._hover:
            self._hover = True; self.update(self.rect())
        super().enterEvent(e)

    def leaveEvent(self, e):
        if self._hover:
            self._hover = False; self.update(self.rect())
        super().leaveEvent(e)

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        p.fillRect(r, _qcolor(COL_ROSE, 0.16 if self._hover else 0.08))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_qcolor(COL_ROSE, 0.5)))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        p.setPen(QColor(COL_ROSE_LT)); p.setFont(self._font)
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, "Clear")
        p.end()


# ════════════════════════════════════════════════════════════════════════
# SCHEDULE GRID — 992 × 480 single custom-paint widget
# ════════════════════════════════════════════════════════════════════════

class _ScheduleGrid(QWidget):
    """The 24×7 cell grid. Owns the selection model and paints every cell.

    Public API:
        set_clocks(list[dict])        — clocks with id, name (for cell labels)
        set_grid(dict[(d, h), int])   — current schedule snapshot
        set_assignment(d, h, cid|None)
        select_cell(d, h)             — programmatic select
        clear_selection()
        select_all()
        selected_cells -> set[(d, h)] (read-only copy)

    Signals:
        selection_changed()
    """

    DRAG_THRESHOLD_PX = 4

    selection_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(GRID_W, GRID_H)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._grid: dict[tuple[int, int], int] = {}
        # Cells placed by the Category Auto-Grid builder (loaded alongside
        # the grid snapshot — never queried from paintEvent).
        self._auto_cells: set[tuple[int, int]] = set()
        self._clock_meta: dict[int, dict] = {}
        self._sel: set[tuple[int, int]] = set()
        self._anchor: Optional[tuple[int, int]] = None

        # Drag state
        self._drag_active = False
        self._drag_origin: Optional[QPoint] = None
        self._drag_press_cell: Optional[tuple[int, int]] = None
        self._drag_modifier: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier
        self._drag_preview_cells: set[tuple[int, int]] = set()
        # Snapshot of selection at drag start so Shift/Ctrl-drag can compose
        self._drag_base: set[tuple[int, int]] = set()

        # Cached fonts
        self._font_time = mono(10, bold=False)
        self._font_cell = inter(10, QFont.Weight.Bold, letter_spacing=-0.1)
        self._font_auto = inter(7, QFont.Weight.Bold, letter_spacing=0.6)
        # Cached row backgrounds (alternating)
        self._row_bg_a = QColor(255, 255, 255, 4)
        self._row_bg_b = QColor(255, 255, 255, 8)
        # AUTO tag ink (semi-transparent so it reads as a watermark)
        self._auto_tag_ink = QColor(255, 255, 255, 110)

        # Pre-build time labels
        self._time_labels = [
            f"{h:02d}:00 - {h:02d}:59" for h in range(N_HOURS)
        ]

    # ── Public model API ─────────────────────────────────────────────────

    def set_clocks(self, clocks: list[dict]) -> None:
        self._clock_meta = {
            int(c["id"]): {
                "name": str(c.get("name") or "Clock"),
                "color": color_for_clock_id(int(c["id"])),
            }
            for c in clocks
        }
        self.update(self.rect())

    def set_grid(self, grid: dict,
                 auto_cells: Optional[set[tuple[int, int]]] = None) -> None:
        self._grid = {(int(d), int(h)): int(cid) for (d, h), cid in grid.items()}
        self._auto_cells = {
            (int(d), int(h)) for d, h in (auto_cells or set())
        }
        self.update(self.rect())

    def set_assignment(self, d: int, h: int, cid: Optional[int]) -> None:
        key = (int(d), int(h))
        prev = self._grid.get(key)
        was_auto = key in self._auto_cells
        # Any manual write supersedes an auto placement — the builder
        # releases the registry row; the badge must drop immediately too.
        self._auto_cells.discard(key)
        if cid is None:
            self._grid.pop(key, None)
        else:
            self._grid[key] = int(cid)
        if prev != self._grid.get(key) or was_auto:
            self.update(_cell_rect(d, h))

    @property
    def selected_cells(self) -> set[tuple[int, int]]:
        return set(self._sel)

    def select_cell(self, d: int, h: int) -> None:
        cell = (int(d), int(h))
        if cell in self._sel:
            return
        self._sel.add(cell); self._anchor = cell
        self.update(_cell_rect(d, h))
        self.selection_changed.emit()

    def clear_selection(self) -> None:
        if not self._sel:
            return
        prev = self._sel
        self._sel = set()
        self._anchor = None
        for d, h in prev:
            self.update(_cell_rect(d, h))
        self.selection_changed.emit()

    def select_all(self) -> None:
        all_cells = {(d, h) for d in range(N_DAYS) for h in range(N_HOURS)}
        if all_cells == self._sel:
            return
        added = all_cells - self._sel
        self._sel = all_cells
        self._anchor = (0, 0)
        for d, h in added:
            self.update(_cell_rect(d, h))
        self.selection_changed.emit()

    # ── Hit testing ──────────────────────────────────────────────────────

    @staticmethod
    def cell_at(p: QPoint) -> Optional[tuple[int, int]]:
        x, y = p.x(), p.y()
        if x < TIME_COL_W or y < 0 or y >= N_HOURS * ROW_H:
            return None
        rel = x - TIME_COL_W
        d = rel // CELL_PITCH_X
        if d < 0 or d >= N_DAYS:
            return None
        if rel % CELL_PITCH_X >= CELL_W:
            return None    # in horizontal gutter
        h = y // ROW_H
        if y % ROW_H < CELL_PAD_Y or y % ROW_H >= CELL_PAD_Y + CELL_H:
            return None    # in vertical padding
        return (int(d), int(h))

    @staticmethod
    def _cells_in_rect(p1: QPoint, p2: QPoint) -> set[tuple[int, int]]:
        """All (d, h) cells whose rect intersects the bounding rect of p1-p2.
        Used by drag-lasso. Snapping is generous: we expand to the rows/cols
        the drag covers in pixel-space."""
        x0, x1 = sorted([p1.x(), p2.x()])
        y0, y1 = sorted([p1.y(), p2.y()])
        # Clamp to grid
        x0 = max(x0, TIME_COL_W); x1 = min(x1, GRID_W - 1)
        y0 = max(y0, 0); y1 = min(y1, N_HOURS * ROW_H - 1)
        if x1 < x0 or y1 < y0:
            return set()
        # Day columns covered
        d_lo = max(0, (x0 - TIME_COL_W) // CELL_PITCH_X)
        d_hi = min(N_DAYS - 1, (x1 - TIME_COL_W) // CELL_PITCH_X)
        h_lo = max(0, y0 // ROW_H)
        h_hi = min(N_HOURS - 1, y1 // ROW_H)
        return {(d, h) for d in range(d_lo, d_hi + 1)
                for h in range(h_lo, h_hi + 1)}

    # ── Mouse handling ───────────────────────────────────────────────────

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(e); return
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        cell = self.cell_at(e.position().toPoint())
        mods = e.modifiers()
        self._drag_active = True
        self._drag_origin = e.position().toPoint()
        self._drag_press_cell = cell
        self._drag_modifier = mods
        self._drag_base = set(self._sel)
        self._drag_preview_cells = set()
        # Immediate response to a click — we'll re-evaluate on move/release
        if cell is None:
            return
        if mods & Qt.KeyboardModifier.ShiftModifier and self._anchor is not None:
            new_sel = self._drag_base | self._cells_in_rect(
                self._cell_pixel(self._anchor), self._cell_pixel(cell))
            self._apply_selection(new_sel)
        elif mods & Qt.KeyboardModifier.ControlModifier:
            new_sel = set(self._sel)
            if cell in new_sel:
                new_sel.discard(cell)
            else:
                new_sel.add(cell)
            self._anchor = cell
            self._apply_selection(new_sel)
        else:
            self._anchor = cell
            self._apply_selection({cell})

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        if not self._drag_active or self._drag_origin is None:
            return
        pos = e.position().toPoint()
        if (abs(pos.x() - self._drag_origin.x()) < self.DRAG_THRESHOLD_PX
                and abs(pos.y() - self._drag_origin.y()) < self.DRAG_THRESHOLD_PX):
            return
        cells = self._cells_in_rect(self._drag_origin, pos)
        if cells == self._drag_preview_cells:
            return
        # Compose with base selection per modifier
        mods = self._drag_modifier
        if mods & Qt.KeyboardModifier.ShiftModifier:
            new_sel = self._drag_base | cells
        elif mods & Qt.KeyboardModifier.ControlModifier:
            new_sel = self._drag_base ^ cells
        else:
            new_sel = set(cells)
        self._drag_preview_cells = cells
        self._apply_selection(new_sel)

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        if e.button() != Qt.MouseButton.LeftButton:
            super().mouseReleaseEvent(e); return
        self._drag_active = False
        self._drag_origin = None
        self._drag_press_cell = None
        self._drag_modifier = Qt.KeyboardModifier.NoModifier
        self._drag_base = set()
        self._drag_preview_cells = set()

    # ── Keyboard ─────────────────────────────────────────────────────────

    def keyPressEvent(self, e: QKeyEvent) -> None:
        if e.key() == Qt.Key.Key_Escape:
            self.clear_selection(); e.accept(); return
        if (e.key() == Qt.Key.Key_A
                and e.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.select_all(); e.accept(); return
        super().keyPressEvent(e)

    # ── Internal selection helpers ───────────────────────────────────────

    @staticmethod
    def _cell_pixel(cell: tuple[int, int]) -> QPoint:
        d, h = cell
        return QPoint(TIME_COL_W + d * CELL_PITCH_X + CELL_W // 2,
                      h * ROW_H + ROW_H // 2)

    def _apply_selection(self, new_sel: set[tuple[int, int]]) -> None:
        if new_sel == self._sel:
            return
        diff = new_sel.symmetric_difference(self._sel)
        self._sel = set(new_sel)
        for d, h in diff:
            self.update(_cell_rect(d, h))
        self.selection_changed.emit()

    # ── Paint ────────────────────────────────────────────────────────────

    def paintEvent(self, e: QPaintEvent) -> None:
        clip = e.rect()
        p = QPainter(self); p.setClipRect(clip)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        # Determine which rows intersect the clip
        h_lo = max(0, clip.y() // ROW_H)
        h_hi = min(N_HOURS - 1,
                   max(0, (clip.y() + clip.height() - 1) // ROW_H))
        for h in range(h_lo, h_hi + 1):
            row_rect = QRect(0, h * ROW_H, GRID_W, ROW_H)
            if not row_rect.intersects(clip):
                continue
            # Alternating row background
            p.fillRect(row_rect,
                       self._row_bg_a if h % 2 == 0 else self._row_bg_b)
            # Time label
            p.setPen(QColor(COL_TEXT_MUTED))
            p.setFont(self._font_time)
            p.drawText(QRect(10, h * ROW_H, TIME_COL_W - 20, ROW_H),
                       Qt.AlignmentFlag.AlignLeft
                       | Qt.AlignmentFlag.AlignVCenter,
                       self._time_labels[h])
            # Cells
            for d in range(N_DAYS):
                self._paint_cell(p, d, h)
        p.end()

    def _paint_cell(self, p: QPainter, d: int, h: int) -> None:
        rect = _cell_rect(d, h)
        cid = self._grid.get((d, h))
        meta = self._clock_meta.get(cid) if cid is not None else None
        accent = meta["color"] if meta else None
        sel = (d, h) in self._sel
        is_auto = (d, h) in self._auto_cells
        rf = QRectF(rect)
        # Fill
        if accent:
            p.fillRect(rf, _qcolor(accent, 0.36 if sel else 0.18))
        else:
            p.fillRect(rf, QColor(255, 255, 255, 18 if sel else 6))
        # Border — auto-placed cells get a dashed accent outline
        p.setBrush(Qt.BrushStyle.NoBrush)
        if sel:
            pen = QPen(QColor(255, 255, 255, 220)); pen.setWidthF(1.5)
        elif accent:
            pen = QPen(_qcolor(accent, 0.5)); pen.setWidthF(1.0)
            if is_auto:
                pen.setStyle(Qt.PenStyle.DashLine)
        else:
            pen = QPen(QColor(255, 255, 255, 22)); pen.setWidthF(1.0)
        p.setPen(pen)
        p.drawRoundedRect(rf.adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)
        # Label (clock name) — only when assigned
        if meta:
            p.setPen(QColor(COL_TEXT_PRIMARY))
            p.setFont(self._font_cell)
            p.drawText(rf, Qt.AlignmentFlag.AlignCenter, meta["name"])
            # AUTO watermark tag, right-aligned inside the cell
            if is_auto:
                p.setPen(self._auto_tag_ink)
                p.setFont(self._font_auto)
                p.drawText(rf.adjusted(0, 0, -5, 0),
                           Qt.AlignmentFlag.AlignRight
                           | Qt.AlignmentFlag.AlignVCenter,
                           "AUTO")


# ════════════════════════════════════════════════════════════════════════
# SCHEDULE CARD — wraps the day-header row, mode tabs, Clear button, grid
# ════════════════════════════════════════════════════════════════════════

class _ScheduleCard(QWidget):
    """1024 × 580 card. Header strip + day-header row + grid."""

    mode_changed = pyqtSignal(str)
    clear_clicked = pyqtSignal()
    selection_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(1024, 580)
        self._mode: Mode = DEFAULT_MODE
        self._font_title = inter(14, QFont.Weight.Black, letter_spacing=-0.1)
        self._font_day = inter(13, QFont.Weight.Bold, letter_spacing=-0.1)

        # Mode tabs + Clear button
        self._tab_weekdays = _ModeTab("Weekdays", self)
        self._tab_weekdays.move(200, 14)
        self._tab_weekdays.set_active(True)
        self._tab_weekdays.clicked.connect(
            lambda: self._set_mode(MODE_WEEKDAYS))

        self._tab_specific = _ModeTab("Specific Days", self)
        self._tab_specific.move(350, 14)
        self._tab_specific.clicked.connect(
            lambda: self._set_mode(MODE_SPECIFIC))

        self._clear = _ClearButton(self)
        self._clear.move(924, 14)
        self._clear.clicked.connect(self.clear_clicked.emit)

        # Grid (positioned below the day-header band)
        self._grid = _ScheduleGrid(self)
        self._grid.move(16, 100)
        self._grid.selection_changed.connect(self.selection_changed.emit)

    # Public passthrough ─────────────────────────────────────────────────
    @property
    def grid(self) -> _ScheduleGrid:
        return self._grid

    def mode(self) -> Mode:
        return self._mode

    def set_mode(self, mode: Mode) -> None:
        self._set_mode(mode, emit=False)

    def _set_mode(self, mode: Mode, emit: bool = True) -> None:
        if mode not in (MODE_WEEKDAYS, MODE_SPECIFIC):
            mode = DEFAULT_MODE
        if mode == self._mode:
            return
        self._mode = mode
        self._tab_weekdays.set_active(mode == MODE_WEEKDAYS)
        self._tab_specific.set_active(mode == MODE_SPECIFIC)
        if emit:
            self.mode_changed.emit(mode)

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        # Card background
        bg = QLinearGradient(0, 0, 0, self.height())
        bg.setColorAt(0.0, QColor(14, 16, 32, 242))
        bg.setColorAt(1.0, QColor(7, 9, 18, 242))
        p.fillRect(r, QBrush(bg))
        # Top accent (cyan → purple → pink)
        accent = QLinearGradient(0, 0, self.width(), 0)
        accent.setColorAt(0.0, QColor(COL_CYAN))
        accent.setColorAt(0.5, QColor(COL_PURPLE_MID))
        accent.setColorAt(1.0, QColor(COL_PINK))
        p.fillRect(QRectF(0, 0, self.width(), 3), QBrush(accent))
        # Border
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 18)))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)
        # Title
        p.setPen(QColor(COL_TEXT_PRIMARY)); p.setFont(self._font_title)
        p.drawText(QRectF(20, 18, 200, 17),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "Clocks Schedule")
        # Day-header row (TIME / Mon..Sun) — y=60..96, h=36
        # TIME label
        p.setPen(QColor(COL_TEXT_MUTED)); p.setFont(self._font_day)
        p.drawText(QRectF(28, 60, 60, 36),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "TIME")
        # Day labels — same column centers as cells
        p.setPen(QColor(COL_TEXT_PRIMARY)); p.setFont(self._font_day)
        # Grid is at (16, 100); cell centers are at (16 + 100 + d*128 + 60, 60..96)
        for d, label in enumerate(DAY_NAMES):
            x = 16 + TIME_COL_W + d * CELL_PITCH_X
            p.drawText(QRectF(x, 60, CELL_W, 36),
                       Qt.AlignmentFlag.AlignCenter, label)
        # Hairline below the day-header row
        p.fillRect(QRectF(16, 96, self.width() - 32, 1),
                   QColor(255, 255, 255, 18))
        p.end()


# ════════════════════════════════════════════════════════════════════════
# AUTO SCHEDULE — the screen
# ════════════════════════════════════════════════════════════════════════

class AutoSchedule(QWidget):
    """Premium-theme Main Auto Schedule screen.

    Signals:
      screen_requested(str) — 'studio_open' / 'libraries' / 'settings' /
                              'ai_magic' / 'scheduling_hub' / 'clock_new'
                              / 'clock_edit:<id>' / 'auto_program_settings'
    """

    screen_requested = pyqtSignal(str)

    def __init__(self, db, scheduler=None, parent=None):
        super().__init__(parent)
        self._db = db
        self._scheduler = scheduler
        self.setFixedSize(WINDOW_W, WINDOW_H)
        self.setMouseTracking(False)

        # Cached page bg
        bg = QLinearGradient(0, 0, 0, WINDOW_H)
        bg.setColorAt(0.0, QColor(COL_BG_TOP))
        bg.setColorAt(0.5, QColor(COL_BG_MID))
        bg.setColorAt(1.0, QColor(COL_BG_BOT))
        self._bg = bg

        # Cached fonts
        self._font_breadcrumb = inter(11, QFont.Weight.Bold, letter_spacing=2.0)
        self._font_title      = inter(36, QFont.Weight.Black, letter_spacing=-1.0)
        self._font_subtitle   = inter(14, QFont.Weight.Medium, letter_spacing=-0.1)

        # ── Header ────────────────────────────────────────────────────
        self._header = Header(self)
        self._header.move(0, 0)
        self._header.libraries_clicked.connect(
            lambda: self.screen_requested.emit("libraries"))
        self._header.settings_clicked.connect(
            lambda: self.screen_requested.emit("settings"))
        self._header.ai_magic_clicked.connect(
            lambda: self.screen_requested.emit("ai_magic"))
        self._header.studio_open_clicked.connect(
            lambda: self.screen_requested.emit("studio_open"))

        # ── Left rail ─────────────────────────────────────────────────
        self._clocks_panel = _ClocksPanel(self)
        self._clocks_panel.move(56, 240)
        self._clocks_panel.clock_selected.connect(self._on_clock_selected)

        self._set_btn = _SetButton(self)
        self._set_btn.move(56, 496)
        self._set_btn.clicked.connect(self._on_set_clicked)

        self._btn_create = _ActionRowButton("+", "Create New Clock",
                                            COL_GREEN, self)
        self._btn_create.move(56, 592)
        self._btn_create.clicked.connect(
            lambda: self.screen_requested.emit("clock_new"))

        self._btn_delete = _ActionRowButton("🗑", "Delete Selected Clock",
                                            COL_ROSE, self)
        self._btn_delete.move(56, 634)
        self._btn_delete.set_enabled(False)
        self._btn_delete.clicked.connect(self._on_delete_clicked)

        self._btn_edit = _ActionRowButton("✎", "Edit Selected Clock",
                                          COL_CYAN, self)
        self._btn_edit.move(56, 676)
        self._btn_edit.set_enabled(False)
        self._btn_edit.clicked.connect(self._on_edit_clicked)

        self._btn_dup = _ActionRowButton("⧉", "Duplicate Selected Clock",
                                         COL_PURPLE_MID, self)
        self._btn_dup.move(56, 718)
        self._btn_dup.set_enabled(False)
        self._btn_dup.clicked.connect(self._on_duplicate_clicked)

        self._btn_auto = _AutoProgramButton(self)
        self._btn_auto.move(56, 776)
        self._btn_auto.clicked.connect(
            lambda: self.screen_requested.emit("auto_program_settings"))

        # ── Right grid card ────────────────────────────────────────────
        self._card = _ScheduleCard(self)
        self._card.move(360, 240)
        self._card.mode_changed.connect(self._on_mode_changed)
        self._card.clear_clicked.connect(self._on_clear_clicked)
        self._card.selection_changed.connect(self._on_selection_changed)

        # ── 1Hz tick for header time ──────────────────────────────────
        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._on_tick)
        self._tick.start()
        self._on_tick()

        # ── Initial load (mode + grid) ────────────────────────────────
        self._load_mode_from_settings()
        self._reload_clocks_and_grid()

        log.info("AutoSchedule ready (Figma 278:2 — Premium Dark)")

    # ── Lifecycle ────────────────────────────────────────────────────────

    def showEvent(self, e):
        # Refresh whenever the screen is shown; cheap (single SELECT each).
        self._reload_clocks_and_grid()
        super().showEvent(e)

    # ── Mode persistence ─────────────────────────────────────────────────

    def _load_mode_from_settings(self) -> None:
        try:
            m = self._db.get_setting(SETTINGS_KEY_MODE, DEFAULT_MODE)
        except Exception as exc:
            log.warning(f"load mode setting failed: {exc}")
            m = DEFAULT_MODE
        if m not in (MODE_WEEKDAYS, MODE_SPECIFIC):
            m = DEFAULT_MODE
        self._card.set_mode(m)

    def _on_mode_changed(self, mode: str) -> None:
        try:
            self._db.set_setting(SETTINGS_KEY_MODE, str(mode))
        except Exception as exc:
            log.warning(f"persist mode setting failed: {exc}")

    # ── Reload helpers ───────────────────────────────────────────────────

    def _reload_clocks_and_grid(self) -> None:
        try:
            rows = self._db.get_all_clocks()
            clocks = [
                {"id": int(r["id"]),
                 "name": r["name"],
                 "description": r["description"]
                                if "description" in r.keys() else ""}
                for r in rows
            ]
        except Exception as exc:
            log.warning(f"load clocks failed: {exc}")
            clocks = []
        # Sort newest-first so a freshly-saved clock always lands at the
        # top of the visible window without the operator scrolling.
        # db.get_all_clocks() orders by name — fine for full-list callers,
        # but here the operator's mental model is "the clock I just made."
        # Higher id = more recently created (autoincrement primary key).
        clocks.sort(key=lambda c: int(c["id"]), reverse=True)
        try:
            grid = self._db.get_auto_schedule_grid()
        except Exception as exc:
            log.warning(f"load grid failed: {exc}")
            grid = {}
        # Category Auto-Grid registry — a cell is "auto" only while the
        # registry and the live grid agree on the clock. Manual overwrites
        # break the match, so the badge drops on the next refresh.
        try:
            records = self._db.get_auto_grid_cell_records()
        except Exception as exc:
            log.warning(f"load auto-grid records failed: {exc}")
            records = {}
        auto_cells = {
            (int(d), int(h)) for (d, h), cid in records.items()
            if grid.get((int(d), int(h))) == int(cid)
        }
        self._clocks_panel.set_clocks(clocks)
        self._card.grid.set_clocks(clocks)
        self._card.grid.set_grid(grid, auto_cells)
        self._update_button_states()

    # ── State / UI sync ──────────────────────────────────────────────────

    def _on_clock_selected(self, cid: int) -> None:
        self._update_button_states()
        # Hint for the selected clock — first cell that uses it
        if cid is None or cid < 0:
            return
        for (d, h), assigned in sorted(self._card.grid._grid.items()):
            if assigned == cid:
                self._clocks_panel.set_hint_for(
                    cid, f"{DAY_NAMES_SHORT[d]} · {h:02d}:00")
                break

    def _on_selection_changed(self) -> None:
        self._update_button_states()

    def _update_button_states(self) -> None:
        sel_clock = self._clocks_panel.selected_id()
        sel_cells = self._card.grid.selected_cells
        # SET enabled iff both selected
        self._set_btn.set_enabled(sel_clock is not None and bool(sel_cells))
        # Clock-action buttons enabled iff a clock is selected
        has_clock = sel_clock is not None
        self._btn_delete.set_enabled(has_clock)
        self._btn_edit.set_enabled(has_clock)
        self._btn_dup.set_enabled(has_clock)

    # ── Actions ──────────────────────────────────────────────────────────

    def _expand_targets(self, cells: set[tuple[int, int]]
                        ) -> set[tuple[int, int]]:
        """Apply the current mode's expansion to a selection set.

        Weekdays mode: any (d, h) where d is Mon..Fri expands to the full
        weekday strip (Mon..Fri) at that hour. Sat / Sun stay literal.
        Specific mode: identity.
        """
        if self._card.mode() != MODE_WEEKDAYS:
            return set(cells)
        out: set[tuple[int, int]] = set()
        for d, h in cells:
            if d in WEEKDAY_INDICES:
                for wd in WEEKDAY_INDICES:
                    out.add((wd, h))
            else:
                out.add((d, h))
        return out

    def _on_set_clicked(self) -> None:
        cid = self._clocks_panel.selected_id()
        sel = self._card.grid.selected_cells
        if cid is None or not sel:
            return
        targets = self._expand_targets(sel)
        ok = 0
        for d, h in sorted(targets):
            try:
                self._db.set_auto_schedule_cell(int(d), int(h), int(cid))
                self._card.grid.set_assignment(d, h, int(cid))
                ok += 1
            except Exception as exc:
                log.warning(f"set_auto_schedule_cell({d},{h},{cid}): {exc}")
        log.info(
            f"[auto_sched] SET clock={cid} cells={len(sel)} → "
            f"wrote {ok}/{len(targets)} (mode={self._card.mode()})")

    def _on_clear_clicked(self) -> None:
        if not dialogs.confirm(
                self, "Clear schedule?",
                "Clear the entire weekly schedule? Every cell will "
                "be unset.\n\nThis cannot be undone.",
                danger=True, yes_label="Clear"):
            return
        try:
            n = self._db.clear_all_auto_schedule()
        except Exception as exc:
            log.warning(f"clear_all_auto_schedule failed: {exc}")
            return
        self._card.grid.set_grid({})
        log.info(f"[auto_sched] cleared schedule ({n} rows)")

    def _cells_assigned_to(self, cid: int) -> list[tuple[int, int]]:
        """Return every (day, hour) cell currently assigned to ``cid``.
        Reads from the grid cache populated by ``_reload_clocks_and_grid``."""
        return sorted(
            (d, h) for (d, h), assigned
            in self._card.grid._grid.items()
            if assigned == int(cid)
        )

    def _on_delete_clicked(self) -> None:
        cid = self._clocks_panel.selected_id()
        if cid is None:
            return
        meta = self._card.grid._clock_meta.get(int(cid)) or {}
        name = meta.get("name") or f"clock #{cid}"
        # Refuse delete if the clock is still assigned to any grid cell —
        # the operator must clear those cells first. Protects against
        # accidental wipe of the day's schedule via a delete.
        assigned = self._cells_assigned_to(int(cid))
        if assigned:
            sample = ", ".join(
                f"{DAY_NAMES_SHORT[d]} {h:02d}:00" for d, h in assigned[:3]
            )
            tail = (f" + {len(assigned) - 3} more"
                    if len(assigned) > 3 else "")
            dialogs.warning(
                self, "Clock is in use",
                f"'{name}' is assigned to {len(assigned)} schedule slot"
                f"{'s' if len(assigned) != 1 else ''} ({sample}{tail}).\n\n"
                f"Remove this clock from every schedule cell first, then "
                f"the delete will go through.")
            return
        if not dialogs.confirm(
                self, "Delete clock?",
                f"Delete '{name}'?",
                danger=True, yes_label="Delete Clock"):
            return
        try:
            # db.delete_clock manual-cascades clock_slots / broadcast_log /
            # ai_rotation_decisions / force_clocks (see commit d65ba98).
            # No auto_schedule cells exist for this clock (just checked
            # above), so the bare delete is safe.
            self._db.delete_clock(int(cid))
        except ValueError as exc:
            dialogs.info(self, "Cannot delete", str(exc)); return
        except Exception as exc:
            log.warning(f"delete_clock failed: {exc}"); return
        self._clocks_panel.select_clock(None)
        self._reload_clocks_and_grid()
        log.info(f"[auto_sched] deleted clock {cid}")

    def _on_edit_clicked(self) -> None:
        cid = self._clocks_panel.selected_id()
        if cid is None:
            return
        self.screen_requested.emit(f"clock_edit:{int(cid)}")

    def _on_duplicate_clicked(self) -> None:
        cid = self._clocks_panel.selected_id()
        if cid is None:
            return
        # Route to Clock Editor in duplicate mode — user gets an
        # opportunity to rename / tweak before the clone is committed.
        self.screen_requested.emit(f"clock_duplicate:{int(cid)}")

    # ── Header tick ──────────────────────────────────────────────────────

    def _on_tick(self) -> None:
        from datetime import datetime
        now = datetime.now()
        self._header.set_time(
            now.strftime("%H:%M"), f":{now.second:02d}",
            now.strftime("%A").upper(),
            now.strftime("%B %d, %Y").upper())

    # ── Paint ────────────────────────────────────────────────────────────

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        # Page background
        p.fillRect(QRectF(0, 0, self.width(), self.height()), QBrush(self._bg))
        # Title block
        p.setPen(QColor(COL_TEXT_MUTED)); p.setFont(self._font_breadcrumb)
        p.drawText(QRectF(56, 116, 600, 13),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "SCHEDULING / MAIN AUTO SCHEDULE")
        p.setPen(QColor(COL_TEXT_PRIMARY)); p.setFont(self._font_title)
        p.drawText(QRectF(56, 138, 800, 50),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "Main Auto Schedule")
        p.setPen(QColor(COL_TEXT_SECONDARY)); p.setFont(self._font_subtitle)
        p.drawText(QRectF(56, 188, 900, 17),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "Set up your weekly clocks rotation across all 24 "
                   "hours · Mon to Sun")
        p.end()
