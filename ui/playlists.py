"""
RadioAI Studio Pro — Playlists screen (Figma 239:2 — Premium Dark).

Sub-screen of the Scheduling Hub. Layout follows the same chrome as
the Hub (Header / LiveTimePill from ui.widgets.app_chrome) and the
shared design tokens from ui.widgets.tokens.

Layout (1440×900)
-----------------
  HEADER         (reused from Hub)              y=  0..88
  Breadcrumb + Title block                       y=116..211
  LiveTimePill (top-right)                       y=144..188
  Toolbar (search + chips + +New / Import)       y=240..296
  Stat row (4 cards × 318×110)                   y=314..424
  Grid (2col × 3row, 442×130 each)               y=444..866
  Detail panel (412×480 right side)              y=444..924
  Footer hairline + version row                  y=856 / y=872

Engine wiring
-------------
- showEvent → load via db.get_playlists_with_stats() (cached + invalidated
  on Add to Schedule / db change).
- Search box debounced 200ms via single-shot QTimer.
- Filter chips: All / Manual / Imported / Smart (counts from data).
- Card click selects → detail panel updates.
- Open → emits screen_requested("playlist_edit:<id>") — MainWindow
  shows a "coming soon" toast.
- + New Playlist emits screen_requested("playlist_new").
- Add to Schedule (in detail panel) calls
  scheduler.add_playlist_to_schedule(id) and refreshes.
- ▶ Preview plays the playlist's first track via the AudioEngine
  preview channel — falls through gracefully when no engine.

═════════════════════════════════════════════════════════════════════════════
PERFORMANCE INVARIANTS — DO NOT VIOLATE
═════════════════════════════════════════════════════════════════════════════
  1. event.rect() clipping in custom paintEvents.
  2. mouseMoveEvent uses self.update(QRect) — not bare self.update().
  3. setMouseTracking only where cursor change is required.
  4. NO db calls in paintEvent — caller-side only.
  5. NO self.update() inside paintEvent.
  6. NO nested QScrollArea.
  7. QGradient/QColor/QFont cached in __init__.
  8. Drop shadows via QGraphicsDropShadowEffect.
═════════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from PyQt6.QtCore import (
    Qt, QRect, QRectF, QPointF, QTimer, pyqtSignal,
)
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QLinearGradient, QFont, QCursor,
    QMouseEvent, QPainterPath,
)
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLineEdit, QMessageBox,
)

from ui.widgets.tokens import (
    inter, mono,
    COL_BG_TOP, COL_BG_MID, COL_BG_BOT,
    COL_BORDER_FAINT,
    COL_CYAN, COL_CYAN_LT, COL_CYAN_DK, COL_CYAN_MD,
    COL_PURPLE, COL_PURPLE_LT, COL_PURPLE_DEEP,
    COL_GREEN, COL_GREEN_LT, COL_GREEN_DK, COL_GREEN_MD,
    COL_AMBER, COL_AMBER_LT, COL_AMBER_DK, COL_AMBER_MD,
    COL_ROSE, COL_ROSE_LT,
    COL_PINK, COL_PINK_DK,
    COL_TEAL, COL_TEAL_LT,
    COL_TEXT_PRIMARY, COL_TEXT_SECONDARY, COL_TEXT_MUTED, COL_TEXT_DIM,
    qcolor_a as _qcolor,
)
from ui.widgets.app_chrome import (
    Header, LiveTimePill, drop_shadow,
    WINDOW_W, HEADER_H,
)

log = logging.getLogger("Playlists")

WINDOW_H = 900


# ── Helpers ─────────────────────────────────────────────────────────────

def _fmt_duration(ms: int) -> str:
    """Format ms as 'H:MM:SS' (or 'MM:SS' under an hour)."""
    s = max(0, int(ms or 0)) // 1000
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def _fmt_relative(ts_str: Optional[str]) -> str:
    """'Recently' / 'just now' / 'Xh ago' / 'Yesterday' / etc."""
    if not ts_str:
        return "Recently"
    from datetime import datetime as _dt
    try:
        ts = _dt.strptime(str(ts_str), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        try:
            ts = _dt.fromisoformat(str(ts_str))
        except ValueError:
            return "Recently"
    delta_s = max(0, int((_dt.now() - ts).total_seconds()))
    if delta_s < 90:
        return "just now"
    if delta_s < 3600:
        return f"{delta_s // 60}m ago"
    if delta_s < 86400:
        return f"{delta_s // 3600}h ago"
    if delta_s < 86400 * 2:
        return "Yesterday"
    if delta_s < 86400 * 30:
        return f"{delta_s // 86400}d ago"
    if delta_s < 86400 * 365:
        return f"{delta_s // (86400 * 30)}mo ago"
    return "Long ago"


# ── Type badge color map ────────────────────────────────────────────────

_BADGE_COLORS = {
    "manual":   (COL_CYAN,   COL_CYAN_LT,   COL_CYAN_DK),
    "imported": (COL_AMBER,  COL_AMBER_LT,  COL_AMBER_DK),
    "smart":    (COL_PURPLE, COL_PURPLE_LT, COL_PURPLE_DEEP),
}


def _kind_norm(kind: Optional[str]) -> str:
    k = (kind or "manual").strip().lower()
    return k if k in _BADGE_COLORS else "manual"


# ════════════════════════════════════════════════════════════════════════
# SEARCH INPUT — themed QLineEdit with leading magnifier glyph
# ════════════════════════════════════════════════════════════════════════

class _SearchInput(QFrame):
    text_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(360, 36)
        # Inner QLineEdit — leaves room for the leading icon
        self._line = QLineEdit(self)
        self._line.setGeometry(36, 6, 320, 24)
        self._line.setPlaceholderText("Search playlists, by name, tag, or owner…")
        self._line.setFont(inter(11, QFont.Weight.Medium))
        self._line.setStyleSheet(
            f"QLineEdit {{ background: transparent; "
            f"color: {COL_TEXT_PRIMARY}; "
            f"border: none; padding: 0; }}"
            f"QLineEdit:focus {{ outline: none; }}"
        )
        # Debounce
        self._debounce = QTimer(self)
        self._debounce.setInterval(200)
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(self._emit_text)
        self._line.textChanged.connect(lambda _t: self._debounce.start())

        self._font_glyph = inter(15, QFont.Weight.Bold)

    def _emit_text(self):
        self.text_changed.emit(self._line.text().strip())

    def text(self) -> str:
        return self._line.text().strip()

    def paintEvent(self, evt):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, 360, 36), 10, 10)
        p.setBrush(QColor(14, 16, 32, int(0.85 * 255)))
        p.setPen(QPen(COL_BORDER_FAINT, 1))
        p.drawPath(path)
        p.setPen(QColor(COL_TEXT_MUTED))
        p.setFont(self._font_glyph)
        p.drawText(QRectF(10, 0, 22, 36),
                   Qt.AlignmentFlag.AlignCenter, "⌕")


# ════════════════════════════════════════════════════════════════════════
# FILTER CHIP — pill with text + count badge, click-to-toggle
# ════════════════════════════════════════════════════════════════════════

class _FilterChip(QWidget):
    clicked = pyqtSignal(str)

    def __init__(self, key: str, label: str, parent=None):
        super().__init__(parent)
        self._key = key
        self._label = label
        self._count = 0
        self._active = False
        self.setFixedSize(86, 30)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        self._font_label = inter(11, QFont.Weight.Bold, letter_spacing=0.3)
        self._font_count = inter(11, QFont.Weight.Black)

    def set_count(self, n: int) -> None:
        if n != self._count:
            self._count = int(n)
            self.update(self.rect())

    def set_active(self, on: bool) -> None:
        if on != self._active:
            self._active = on
            self.update(self.rect())

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._key)

    def paintEvent(self, evt):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, 86, 30), 15, 15)
        if self._active:
            p.setBrush(_qcolor(COL_CYAN, 0.20))
            p.setPen(QPen(_qcolor(COL_CYAN, 0.50), 1))
            p.drawPath(path)
            p.setPen(QColor(COL_CYAN_LT))
        else:
            p.setBrush(QColor(14, 16, 32, int(0.85 * 255)))
            p.setPen(QPen(COL_BORDER_FAINT, 1))
            p.drawPath(path)
            p.setPen(QColor(COL_TEXT_SECONDARY))
        p.setFont(self._font_label)
        p.drawText(QRectF(12, 7, 50, 16),
                   Qt.AlignmentFlag.AlignLeft, self._label)
        # Count badge (28×16, right side)
        bg_path = QPainterPath()
        bg_path.addRoundedRect(QRectF(50, 7, 28, 16), 8, 8)
        if self._active:
            p.setBrush(_qcolor(COL_CYAN, 0.36))
            p.setPen(Qt.PenStyle.NoPen)
        else:
            p.setBrush(QColor(255, 255, 255, int(0.06 * 255)))
            p.setPen(Qt.PenStyle.NoPen)
        p.drawPath(bg_path)
        p.setPen(QColor(COL_CYAN_LT if self._active else COL_TEXT_MUTED))
        p.setFont(self._font_count)
        p.drawText(QRectF(50, 7, 28, 16),
                   Qt.AlignmentFlag.AlignCenter, str(self._count))


# ════════════════════════════════════════════════════════════════════════
# Primary CTA + Secondary Button (toolbar right side)
# ════════════════════════════════════════════════════════════════════════

class _PrimaryButton(QWidget):
    clicked = pyqtSignal()

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self._label = label
        self._hover = False
        self.setFixedSize(160, 44)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setGraphicsEffect(drop_shadow(20, _qcolor("#7c3aed", 0.40), dy=6))

        g = QLinearGradient(0, 0, 160, 44)
        g.setColorAt(0.00, _qcolor("#a78bfa", 1.0))
        g.setColorAt(0.25, _qcolor("#8b5cf6", 1.0))
        g.setColorAt(0.50, _qcolor("#7c3aed", 1.0))
        g.setColorAt(1.00, _qcolor("#7c3aed", 1.0))
        self._grad = g

        hg = QLinearGradient(0, 0, 0, 22)
        hg.setColorAt(0.0, QColor(255, 255, 255, int(0.16 * 255)))
        hg.setColorAt(1.0, QColor(255, 255, 255, 0))
        self._highlight = hg

        self._font = inter(13, QFont.Weight.Bold, letter_spacing=-0.1)

    def enterEvent(self, e):
        self._hover = True; self.update(self.rect())

    def leaveEvent(self, e):
        self._hover = False; self.update(self.rect())

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def paintEvent(self, evt):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, 160, 44), 12, 12)
        p.fillPath(path, QBrush(self._grad))
        if self._hover:
            p.fillPath(path, QColor(255, 255, 255, int(0.06 * 255)))
        p.setClipPath(path)
        p.fillRect(QRectF(1, 1, 158, 18), QBrush(self._highlight))
        p.setClipping(False)
        p.setPen(QColor("#ffffff"))
        p.setFont(self._font)
        p.drawText(QRectF(0, 0, 160, 44), Qt.AlignmentFlag.AlignCenter,
                   self._label)


class _SecondaryButton(QWidget):
    clicked = pyqtSignal()

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self._label = label
        self._hover = False
        self.setFixedSize(120, 44)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        self._font = inter(12, QFont.Weight.DemiBold, letter_spacing=-0.1)

    def enterEvent(self, e):
        self._hover = True; self.update(self.rect())

    def leaveEvent(self, e):
        self._hover = False; self.update(self.rect())

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def paintEvent(self, evt):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, 120, 44), 12, 12)
        bg = _qcolor(COL_CYAN, 0.18) if self._hover else QColor(14, 16, 32, int(0.85 * 255))
        p.setBrush(bg)
        p.setPen(QPen(_qcolor(COL_CYAN, 0.40 if self._hover else 0.20), 1))
        p.drawPath(path)
        p.setPen(QColor(COL_CYAN_LT))
        p.setFont(self._font)
        p.drawText(QRectF(0, 0, 120, 44), Qt.AlignmentFlag.AlignCenter,
                   self._label)


# ════════════════════════════════════════════════════════════════════════
# STAT CARD — 318×110, 3px top accent, big number, label, sub
# ════════════════════════════════════════════════════════════════════════

class _StatCard(QWidget):
    def __init__(self, label: str, value: str, sub: str, accent: str,
                 accent_dk: str, parent=None):
        super().__init__(parent)
        self._label = label
        self._value = value
        self._sub = sub
        self._accent = accent
        self._accent_dk = accent_dk
        self.setFixedSize(318, 110)
        self.setGraphicsEffect(drop_shadow(20, QColor(0, 0, 0, int(0.40 * 255)), dy=8))

        # Body gradient
        g_body = QLinearGradient(0, 0, 0, 110)
        g_body.setColorAt(0.0, QColor(14, 16, 32, int(0.95 * 255)))
        g_body.setColorAt(1.0, QColor(7, 9, 18,  int(0.95 * 255)))
        self._grad_body = g_body
        # Top accent
        g_top = QLinearGradient(0, 0, 318, 0)
        g_top.setColorAt(0.0, QColor(accent))
        g_top.setColorAt(1.0, QColor(accent_dk))
        self._grad_top = g_top
        # Inner haze
        g_haze = QLinearGradient(0, 0, 0, 96)
        g_haze.setColorAt(0.0, _qcolor(accent, 0.06))
        g_haze.setColorAt(1.0, _qcolor(accent, 0.0))
        self._grad_haze = g_haze

        self._font_label = inter(10, QFont.Weight.Bold, letter_spacing=1.6)
        self._font_value = mono(40, bold=True, letter_spacing=-1.5)
        self._font_sub   = inter(11, QFont.Weight.Medium, letter_spacing=-0.05)

    def set_value(self, value: str, sub: str) -> None:
        if value != self._value or sub != self._sub:
            self._value = value
            self._sub = sub
            self.update(self.rect())

    def paintEvent(self, evt):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, 318, 110), 16, 16)
        p.fillPath(path, QBrush(self._grad_body))
        p.setPen(QPen(COL_BORDER_FAINT, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        p.setClipPath(path)
        p.fillRect(QRectF(0, 0, 318, 96), QBrush(self._grad_haze))
        p.fillRect(QRectF(0, 0, 318, 3), QBrush(self._grad_top))
        p.fillRect(QRectF(0, 2, 318, 1), QColor(255, 255, 255, int(0.04 * 255)))
        p.setClipping(False)

        p.setPen(QColor(self._accent))
        p.setFont(self._font_label)
        p.drawText(QRectF(18, 18, 280, 14),
                   Qt.AlignmentFlag.AlignLeft, self._label)
        p.setPen(QColor(COL_TEXT_PRIMARY))
        p.setFont(self._font_value)
        p.drawText(QRectF(18, 36, 280, 50),
                   Qt.AlignmentFlag.AlignLeft, self._value)
        p.setPen(QColor(COL_TEXT_SECONDARY))
        p.setFont(self._font_sub)
        p.drawText(QRectF(18, 84, 282, 16),
                   Qt.AlignmentFlag.AlignLeft, self._sub)


# ════════════════════════════════════════════════════════════════════════
# PLAYLIST CARD — 442×130, cover + title + meta + actions + status pill
# ════════════════════════════════════════════════════════════════════════

class _PlaylistCard(QWidget):
    selected   = pyqtSignal(int)    # playlist id
    open_clicked    = pyqtSignal(int)
    preview_clicked = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(442, 130)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._hover = False
        self._is_selected = False
        self._row: dict = {}

        self.setGraphicsEffect(drop_shadow(20, QColor(0, 0, 0, int(0.40 * 255)), dy=8))

        # Body gradient
        g_body = QLinearGradient(0, 0, 0, 130)
        g_body.setColorAt(0.0, QColor(14, 16, 32, int(0.95 * 255)))
        g_body.setColorAt(1.0, QColor(7, 9, 18,  int(0.95 * 255)))
        self._grad_body = g_body

        self._font_title  = inter(18, QFont.Weight.Black, letter_spacing=-0.4)
        self._font_meta   = inter(13, QFont.Weight.Medium)
        self._font_sub    = inter(11, QFont.Weight.Medium)
        self._font_btn    = inter(11, QFont.Weight.Bold)
        self._font_badge  = inter(9,  QFont.Weight.Black,  letter_spacing=1.5)
        self._font_status = inter(10, QFont.Weight.Bold,   letter_spacing=1.0)
        self._font_cover  = inter(38, QFont.Weight.Black)

    # ── public ──────────────────────────────────────────────────────

    def set_data(self, row: dict) -> None:
        self._row = dict(row or {})
        self.update(self.rect())

    def set_selected(self, on: bool) -> None:
        if on != self._is_selected:
            self._is_selected = on
            self.update(self.rect())

    @property
    def playlist_id(self) -> int:
        return int(self._row.get("id") or 0)

    # ── interaction ─────────────────────────────────────────────────

    def enterEvent(self, e):
        self._hover = True; self.update(self.rect())

    def leaveEvent(self, e):
        self._hover = False; self.update(self.rect())

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() != Qt.MouseButton.LeftButton:
            return
        # Preview button rect (118, 92, 80×30) — translate to local space
        if QRect(118, 92, 80, 30).contains(e.pos()):
            self.preview_clicked.emit(self.playlist_id)
            return
        # Open button rect (206, 92, 70×30)
        if QRect(206, 92, 70, 30).contains(e.pos()):
            self.open_clicked.emit(self.playlist_id)
            return
        # Anywhere else → select
        self.selected.emit(self.playlist_id)

    # ── paint ───────────────────────────────────────────────────────

    def paintEvent(self, evt):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        kind = _kind_norm(self._row.get("kind"))
        accent, accent_lt, accent_dk = _BADGE_COLORS[kind]

        # Body
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, 442, 130), 16, 16)
        p.fillPath(path, QBrush(self._grad_body))
        if self._is_selected:
            p.fillPath(path, _qcolor(COL_CYAN, 0.10))
        elif self._hover:
            p.fillPath(path, _qcolor(accent, 0.06))
        # Border (selected = cyan, otherwise faint)
        if self._is_selected:
            p.setPen(QPen(_qcolor(COL_CYAN, 0.55), 2))
        else:
            p.setPen(QPen(COL_BORDER_FAINT, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

        # Top accent stripe
        p.setClipPath(path)
        gtop = QLinearGradient(0, 0, 442, 0)
        gtop.setColorAt(0.0, QColor(accent))
        gtop.setColorAt(1.0, QColor(accent_dk))
        p.fillRect(QRectF(0, 0, 442, 3), QBrush(gtop))
        p.setClipping(False)

        # Cover (86×86 at 18, 22)
        cover_rect = QRectF(18, 22, 86, 86)
        cpath = QPainterPath(); cpath.addRoundedRect(cover_rect, 14, 14)
        cg = QLinearGradient(18, 22, 104, 108)
        cg.setColorAt(0.0, _qcolor(accent, 0.32))
        cg.setColorAt(1.0, _qcolor(accent_dk, 0.20))
        p.fillPath(cpath, QBrush(cg))
        p.setPen(QPen(_qcolor(accent, 0.40), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(cpath)
        # ♫ glyph
        p.setPen(QColor(COL_TEXT_PRIMARY))
        p.setFont(self._font_cover)
        p.drawText(QRectF(cover_rect), Qt.AlignmentFlag.AlignCenter, "♫")

        # Type badge (top-right): MANUAL / IMPORTED / SMART
        badge_text = kind.upper()
        badge_path = QPainterPath()
        badge_path.addRoundedRect(QRectF(352, 22, 72, 22), 11, 11)
        p.fillPath(badge_path, _qcolor(accent, 0.20))
        p.setPen(QPen(_qcolor(accent, 0.45), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(badge_path)
        p.setPen(QColor(accent_lt))
        p.setFont(self._font_badge)
        p.drawText(QRectF(352, 22, 72, 22),
                   Qt.AlignmentFlag.AlignCenter, badge_text)

        # Title
        p.setPen(QColor(COL_TEXT_PRIMARY))
        p.setFont(self._font_title)
        title = str(self._row.get("name") or "—")
        p.drawText(QRectF(118, 18, 232, 28),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   title)

        # Tracks · duration
        n_tracks = int(self._row.get("track_count") or 0)
        dur = _fmt_duration(int(self._row.get("total_duration_ms") or 0))
        p.setPen(QColor(COL_TEXT_SECONDARY))
        p.setFont(self._font_meta)
        p.drawText(QRectF(118, 48, 232, 18),
                   Qt.AlignmentFlag.AlignLeft, f"{n_tracks} tracks · {dur}")

        # Last edit / scheduled
        scheduled = bool(self._row.get("scheduled_day"))
        prefix = "Scheduled" if scheduled else "Not in schedule"
        edited = _fmt_relative(self._row.get("updated_at"))
        p.setPen(QColor(COL_TEXT_MUTED))
        p.setFont(self._font_sub)
        p.drawText(QRectF(118, 68, 232, 16),
                   Qt.AlignmentFlag.AlignLeft, f"{prefix} · last edit {edited}")

        # Action buttons: ▶ Preview (118, 92, 80×30) + Open → (206, 92, 70×30)
        prev_path = QPainterPath()
        prev_path.addRoundedRect(QRectF(118, 92, 80, 30), 8, 8)
        p.fillPath(prev_path, _qcolor(COL_GREEN, 0.18))
        p.setPen(QPen(_qcolor(COL_GREEN, 0.45), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(prev_path)
        p.setPen(QColor(COL_GREEN_LT))
        p.setFont(self._font_btn)
        p.drawText(QRectF(118, 92, 80, 30),
                   Qt.AlignmentFlag.AlignCenter, "▶  Preview")

        open_path = QPainterPath()
        open_path.addRoundedRect(QRectF(206, 92, 70, 30), 8, 8)
        p.fillPath(open_path, _qcolor(accent, 0.18))
        p.setPen(QPen(_qcolor(accent, 0.40), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(open_path)
        p.setPen(QColor(accent_lt))
        p.setFont(self._font_btn)
        p.drawText(QRectF(206, 92, 70, 30),
                   Qt.AlignmentFlag.AlignCenter, "Open  →")

        # Status pill (right side, 318, 100, 108×22)
        if scheduled:
            sp = QPainterPath()
            sp.addRoundedRect(QRectF(318, 100, 108, 22), 11, 11)
            p.fillPath(sp, _qcolor(COL_GREEN, 0.18))
            p.setPen(QPen(_qcolor(COL_GREEN, 0.40), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(sp)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(COL_GREEN))
            p.drawEllipse(QRectF(330, 108, 6, 6))
            p.setPen(QColor(COL_GREEN_LT))
            p.setFont(self._font_status)
            p.drawText(QRectF(340, 102, 86, 18),
                       Qt.AlignmentFlag.AlignLeft, "IN SCHEDULE")
        else:
            p.setPen(QColor(COL_TEXT_MUTED))
            p.setFont(self._font_status)
            p.drawText(QRectF(318, 102, 108, 18),
                       Qt.AlignmentFlag.AlignCenter, "NOT SCHEDULED")


# ════════════════════════════════════════════════════════════════════════
# DETAIL PANEL — 412×480 right-side panel for selected playlist
# ════════════════════════════════════════════════════════════════════════

class _DetailPanel(QWidget):
    edit_clicked            = pyqtSignal(int)
    add_to_schedule_clicked = pyqtSignal(int)
    overflow_clicked        = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(412, 480)
        self.setGraphicsEffect(drop_shadow(28, QColor(0, 0, 0, int(0.40 * 255)), dy=12))

        self._row: dict = {}
        self._tracks: list[dict] = []
        self._on_air = False

        # Body gradient
        g_body = QLinearGradient(0, 0, 0, 480)
        g_body.setColorAt(0.0, QColor(14, 16, 32, int(0.97 * 255)))
        g_body.setColorAt(1.0, QColor(7, 9, 18,  int(0.97 * 255)))
        self._grad_body = g_body

        # Top accent (rainbow)
        g_top = QLinearGradient(0, 0, 412, 0)
        g_top.setColorAt(0.0,  QColor(COL_CYAN))
        g_top.setColorAt(0.5,  QColor(COL_PURPLE))
        g_top.setColorAt(1.0,  QColor(COL_PINK))
        self._grad_top = g_top

        # Add to Schedule button gradient
        g_btn = QLinearGradient(156, 426, 306, 464)
        g_btn.setColorAt(0.0, _qcolor("#22d3ee", 1.0))
        g_btn.setColorAt(0.5, _qcolor("#06b6d4", 1.0))
        g_btn.setColorAt(1.0, _qcolor("#0e7490", 1.0))
        self._grad_btn = g_btn

        self._font_title       = inter(22, QFont.Weight.Black, letter_spacing=-0.5)
        self._font_meta        = inter(13, QFont.Weight.Medium)
        self._font_sub         = inter(11, QFont.Weight.Medium)
        self._font_section_lbl = inter(9,  QFont.Weight.Black, letter_spacing=1.5)
        self._font_track_title = inter(12, QFont.Weight.DemiBold, letter_spacing=-0.1)
        self._font_track_artist = inter(10, QFont.Weight.Medium)
        self._font_track_dur   = inter(11, QFont.Weight.DemiBold)
        self._font_track_idx   = inter(11, QFont.Weight.Bold)
        self._font_btn         = inter(13, QFont.Weight.Bold, letter_spacing=-0.2)
        self._font_overflow    = inter(18, QFont.Weight.Bold)
        self._font_pill        = inter(10, QFont.Weight.Bold, letter_spacing=1.0)
        self._font_cover       = inter(48, QFont.Weight.Black)

    # ── public ──────────────────────────────────────────────────────

    def set_data(self, row: Optional[dict], tracks: list[dict],
                 on_air: bool = False) -> None:
        self._row = dict(row or {})
        self._tracks = list(tracks or [])
        self._on_air = on_air
        self.update(self.rect())

    @property
    def playlist_id(self) -> int:
        return int(self._row.get("id") or 0)

    # ── interaction ─────────────────────────────────────────────────

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() != Qt.MouseButton.LeftButton or not self._row:
            return
        # Edit button rect (24, 426, 120, 38)
        if QRect(24, 426, 120, 38).contains(e.pos()):
            self.edit_clicked.emit(self.playlist_id); return
        # Add to Schedule rect (156, 426, 150, 38)
        if QRect(156, 426, 150, 38).contains(e.pos()):
            self.add_to_schedule_clicked.emit(self.playlist_id); return
        # Overflow rect (318, 426, 38, 38)
        if QRect(318, 426, 38, 38).contains(e.pos()):
            self.overflow_clicked.emit(self.playlist_id); return

    # ── paint ───────────────────────────────────────────────────────

    def paintEvent(self, evt):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Body
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, 412, 480), 18, 18)
        p.fillPath(path, QBrush(self._grad_body))
        p.setPen(QPen(COL_BORDER_FAINT, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        # Top rainbow accent
        p.setClipPath(path)
        p.fillRect(QRectF(0, 0, 412, 3), QBrush(self._grad_top))
        p.fillRect(QRectF(0, 2, 412, 1), QColor(255, 255, 255, int(0.04 * 255)))
        p.setClipping(False)

        if not self._row:
            p.setPen(QColor(COL_TEXT_MUTED))
            p.setFont(self._font_meta)
            p.drawText(QRectF(0, 220, 412, 32),
                       Qt.AlignmentFlag.AlignCenter,
                       "Pick a playlist to see its tracks")
            return

        kind = _kind_norm(self._row.get("kind"))
        accent, accent_lt, accent_dk = _BADGE_COLORS[kind]

        # Cover (112×112 at 24, 24)
        cpath = QPainterPath()
        cpath.addRoundedRect(QRectF(24, 24, 112, 112), 18, 18)
        cg = QLinearGradient(24, 24, 136, 136)
        cg.setColorAt(0.0, _qcolor(accent, 0.36))
        cg.setColorAt(1.0, _qcolor(accent_dk, 0.20))
        p.fillPath(cpath, QBrush(cg))
        p.setPen(QPen(_qcolor(accent, 0.40), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(cpath)
        p.setPen(QColor(COL_TEXT_PRIMARY))
        p.setFont(self._font_cover)
        p.drawText(QRectF(24, 24, 112, 112),
                   Qt.AlignmentFlag.AlignCenter, "♫")

        # Title
        p.setPen(QColor(COL_TEXT_PRIMARY))
        p.setFont(self._font_title)
        p.drawText(QRectF(152, 30, 240, 30),
                   Qt.AlignmentFlag.AlignLeft, str(self._row.get("name") or "—"))

        # ON AIR NOW pill
        if self._on_air:
            pill_path = QPainterPath()
            pill_path.addRoundedRect(QRectF(152, 64, 110, 22), 11, 11)
            p.fillPath(pill_path, _qcolor(COL_GREEN, 0.20))
            p.setPen(QPen(_qcolor(COL_GREEN, 0.50), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(pill_path)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(COL_GREEN))
            p.drawEllipse(QRectF(164, 72, 6, 6))
            p.setPen(QColor(COL_GREEN_LT))
            p.setFont(self._font_pill)
            p.drawText(QRectF(174, 66, 90, 18),
                       Qt.AlignmentFlag.AlignLeft, "ON AIR NOW")

        # Track count + duration
        n_tracks = int(self._row.get("track_count") or 0)
        dur = _fmt_duration(int(self._row.get("total_duration_ms") or 0))
        p.setPen(QColor(COL_TEXT_SECONDARY))
        p.setFont(self._font_meta)
        p.drawText(QRectF(152, 96, 240, 18),
                   Qt.AlignmentFlag.AlignLeft, f"{n_tracks} tracks · {dur}")
        # Edited time
        edited = _fmt_relative(self._row.get("updated_at"))
        p.setPen(QColor(COL_TEXT_MUTED))
        p.setFont(self._font_sub)
        p.drawText(QRectF(152, 116, 240, 16),
                   Qt.AlignmentFlag.AlignLeft, f"Edited {edited} by Operator")

        # Divider (24, 156, 364×1)
        p.fillRect(QRectF(24, 156, 364, 1),
                   QColor(255, 255, 255, int(0.06 * 255)))

        # TRACK PREVIEW header + counter
        p.setPen(QColor(COL_AMBER))
        p.setFont(self._font_section_lbl)
        p.drawText(QRectF(24, 174, 200, 14),
                   Qt.AlignmentFlag.AlignLeft, "TRACK PREVIEW")
        p.setPen(QColor(COL_TEXT_MUTED))
        p.drawText(QRectF(244, 174, 144, 14),
                   Qt.AlignmentFlag.AlignRight,
                   f"FIRST {min(5, n_tracks)} OF {n_tracks}")

        # Up to 5 track rows starting at y=196, height 44 each (no gap)
        for i in range(min(5, len(self._tracks))):
            t = self._tracks[i]
            row_y = 196 + i * 48
            # First row gets a subtle highlight + play button
            if i == 0:
                rp = QPainterPath()
                rp.addRoundedRect(QRectF(24, row_y, 364, 44), 8, 8)
                p.fillPath(rp, _qcolor(COL_AMBER, 0.06))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(_qcolor(COL_AMBER, 0.20))
                p.drawEllipse(QRectF(32, row_y + 8, 28, 28))
                p.setPen(QColor(COL_AMBER_LT))
                p.setFont(self._font_btn)
                p.drawText(QRectF(32, row_y + 8, 28, 28),
                           Qt.AlignmentFlag.AlignCenter, "▶")
            else:
                p.setPen(QColor(COL_TEXT_MUTED))
                p.setFont(self._font_track_idx)
                p.drawText(QRectF(32, row_y + 14, 28, 18),
                           Qt.AlignmentFlag.AlignCenter, f"{i + 1:02d}")

            # Title + artist
            p.setPen(QColor(COL_TEXT_PRIMARY))
            p.setFont(self._font_track_title)
            p.drawText(QRectF(72, row_y + 6, 240, 16),
                       Qt.AlignmentFlag.AlignLeft, str(t.get("title") or "—"))
            p.setPen(QColor(COL_TEXT_SECONDARY))
            p.setFont(self._font_track_artist)
            p.drawText(QRectF(72, row_y + 22, 240, 14),
                       Qt.AlignmentFlag.AlignLeft, str(t.get("artist") or "—"))
            # Duration
            p.setPen(QColor(COL_TEXT_PRIMARY))
            p.setFont(self._font_track_dur)
            p.drawText(QRectF(330, row_y + 14, 50, 16),
                       Qt.AlignmentFlag.AlignRight,
                       _fmt_duration(int(t.get("duration_ms") or 0)))

        # Bottom action bar (y=410) — divider + Edit + Add to Schedule + ···
        p.fillRect(QRectF(0, 410, 412, 1),
                   QColor(255, 255, 255, int(0.06 * 255)))
        # Edit (24, 426, 120×38)
        ep = QPainterPath()
        ep.addRoundedRect(QRectF(24, 426, 120, 38), 10, 10)
        p.fillPath(ep, QColor(14, 16, 32, int(0.85 * 255)))
        p.setPen(QPen(COL_BORDER_FAINT, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(ep)
        p.setPen(QColor(COL_TEXT_PRIMARY))
        p.setFont(self._font_btn)
        p.drawText(QRectF(24, 426, 120, 38),
                   Qt.AlignmentFlag.AlignCenter, "✎  Edit")
        # Add to Schedule (156, 426, 150×38)
        ap = QPainterPath()
        ap.addRoundedRect(QRectF(156, 426, 150, 38), 12, 12)
        p.fillPath(ap, QBrush(self._grad_btn))
        p.setClipPath(ap)
        hl = QLinearGradient(156, 427, 156, 444)
        hl.setColorAt(0.0, QColor(255, 255, 255, int(0.18 * 255)))
        hl.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.fillRect(QRectF(157, 427, 148, 14), QBrush(hl))
        p.setClipping(False)
        p.setPen(QColor("#ffffff"))
        p.setFont(self._font_btn)
        p.drawText(QRectF(156, 426, 150, 38),
                   Qt.AlignmentFlag.AlignCenter, "Add to Schedule")
        # Overflow ··· (318, 426, 38×38)
        op = QPainterPath()
        op.addRoundedRect(QRectF(318, 426, 38, 38), 10, 10)
        p.fillPath(op, QColor(14, 16, 32, int(0.85 * 255)))
        p.setPen(QPen(COL_BORDER_FAINT, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(op)
        p.setPen(QColor(COL_TEXT_SECONDARY))
        p.setFont(self._font_overflow)
        p.drawText(QRectF(318, 422, 38, 38),
                   Qt.AlignmentFlag.AlignCenter, "···")


# ════════════════════════════════════════════════════════════════════════
# PLAYLISTS SCREEN — top-level
# ════════════════════════════════════════════════════════════════════════

class Playlists(QWidget):
    """Premium-theme Playlists screen.

    Signals:
      screen_requested(str)  — emits 'studio_open' / 'libraries' /
                               'settings' / 'ai_magic' / 'scheduling_hub' /
                               'playlist_new' / 'playlist_edit:<id>'.

    Public API:
      set_studio(studio)     — late-injection of Studio reference for
                               preview + ON AIR NOW pill.
    """

    screen_requested = pyqtSignal(str)

    FILTERS = (("all", "All"),
               ("manual",   "Manual"),
               ("imported", "Imported"),
               ("smart",    "Smart"))

    def __init__(self, db, scheduler=None, studio=None, engine=None,
                 parent=None):
        super().__init__(parent)
        self._db = db
        self._scheduler = scheduler
        self._studio = studio
        self._engine = engine
        self.setFixedSize(WINDOW_W, WINDOW_H)
        self.setMouseTracking(False)

        # Cached state
        self._playlists: list[dict] = []
        self._filter_kind = "all"
        self._search_text = ""
        self._selected_id: Optional[int] = None
        self._program_start = time.time()
        self._preview_cid: Optional[int] = None

        # Cached page background
        bg = QLinearGradient(0, 0, 0, WINDOW_H)
        bg.setColorAt(0.0, QColor(COL_BG_TOP))
        bg.setColorAt(0.5, QColor(COL_BG_MID))
        bg.setColorAt(1.0, QColor(COL_BG_BOT))
        self._bg = bg

        # Cached fonts (page-level)
        self._font_breadcrumb = inter(11, QFont.Weight.Bold,   letter_spacing=2.0)
        self._font_title      = inter(36, QFont.Weight.Black,  letter_spacing=-1.0)
        self._font_subtitle   = inter(13, QFont.Weight.Medium, letter_spacing=-0.1)
        self._font_footer     = inter(10, QFont.Weight.Bold,   letter_spacing=0.3)
        self._font_footer_dot = inter(10, QFont.Weight.Bold)
        self._font_footer_meta = inter(10, QFont.Weight.Medium, letter_spacing=0.3)
        self._font_settings   = inter(11, QFont.Weight.Bold,   letter_spacing=-0.1)

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

        # ── Live Time pill ────────────────────────────────────────────
        self._live_pill = LiveTimePill(self)
        self._live_pill.move(1240, 144)

        # ── Toolbar children ──────────────────────────────────────────
        # Search input — note: the spec puts it inside an outer toolbar
        # frame (56, 240, 900×56). We position children directly in the
        # screen's coordinate space (toolbar is a "visual group" not a
        # widget) so the search input lives at (72, 250).
        self._search = _SearchInput(self)
        self._search.move(72, 250)
        self._search.text_changed.connect(self._on_search)

        self._chips: dict[str, _FilterChip] = {}
        chip_x = 452
        for key, label in self.FILTERS:
            chip = _FilterChip(key, label, self)
            chip.move(chip_x, 253)
            chip.clicked.connect(self._on_chip_clicked)
            self._chips[key] = chip
            chip_x += 94    # 86 + 8 gap

        self._chips["all"].set_active(True)

        self._new_btn = _PrimaryButton("+ New Playlist", self)
        self._new_btn.move(972, 246)
        self._new_btn.clicked.connect(
            lambda: self.screen_requested.emit("playlist_new"))

        self._import_btn = _SecondaryButton("↓ Import", self)
        self._import_btn.move(1140, 246)
        self._import_btn.clicked.connect(self._on_import_stub)

        # ── Stat row ──────────────────────────────────────────────────
        # x positions: 56, 56+318+16=390, 390+318+16=724, 724+318+16=1058
        self._stat_total      = _StatCard(
            "TOTAL PLAYLISTS", "0", "—", COL_CYAN,   COL_CYAN_DK, self)
        self._stat_total.move(56, 314)
        self._stat_tracks     = _StatCard(
            "TOTAL TRACKS", "0", "across all playlists",
            COL_PURPLE, COL_PURPLE_DEEP, self)
        self._stat_tracks.move(390, 314)
        self._stat_avg        = _StatCard(
            "AVG DURATION", "0:00", "min : sec per playlist",
            COL_GREEN, COL_GREEN_DK, self)
        self._stat_avg.move(724, 314)
        self._stat_scheduled  = _StatCard(
            "SCHEDULED", "0", "in this week's broadcast",
            COL_AMBER, COL_AMBER_DK, self)
        self._stat_scheduled.move(1058, 314)

        # ── Playlist grid (6 cards + detail panel) ────────────────────
        self._cards: list[_PlaylistCard] = []
        for i in range(6):
            row = i // 2
            col = i % 2
            card = _PlaylistCard(self)
            card.move(56 + col * 458, 444 + row * 146)
            card.selected.connect(self._on_card_selected)
            card.open_clicked.connect(self._on_open_card)
            card.preview_clicked.connect(self._on_preview_card)
            self._cards.append(card)

        # ── Detail panel ──────────────────────────────────────────────
        self._detail = _DetailPanel(self)
        self._detail.move(972, 444)
        self._detail.edit_clicked.connect(self._on_open_card)
        self._detail.add_to_schedule_clicked.connect(self._on_add_to_schedule)
        self._detail.overflow_clicked.connect(self._on_overflow_stub)

        # ── 1Hz tick (clock + uptime) ─────────────────────────────────
        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._on_tick)
        self._tick.start()
        self._on_tick()

        log.info("Playlists ready (Figma 239:2 — Premium Dark)")

    # ── Public API ────────────────────────────────────────────────────

    def set_studio(self, studio) -> None:
        self._studio = studio

    # ── Lifecycle ────────────────────────────────────────────────────

    def showEvent(self, evt):
        super().showEvent(evt)
        self._reload_playlists()

    # ── Data load ─────────────────────────────────────────────────────

    def _reload_playlists(self) -> None:
        try:
            self._playlists = self._db.get_playlists_with_stats()
        except Exception as exc:
            log.warning(f"playlists load failed: {exc}")
            self._playlists = []
        self._refresh_chips_counts()
        self._refresh_stats()
        # Auto-select first visible
        visible = self._visible_playlists()
        if self._selected_id is None and visible:
            self._selected_id = int(visible[0]["id"])
        self._refresh_grid()
        self._refresh_detail()

    def _visible_playlists(self) -> list[dict]:
        """Apply current filter + search."""
        out = []
        q = self._search_text.lower().strip()
        for p in self._playlists:
            kind = _kind_norm(p.get("kind"))
            if self._filter_kind != "all" and kind != self._filter_kind:
                continue
            if q:
                hay = " ".join((str(p.get("name") or ""),
                                str(p.get("description") or ""))).lower()
                if q not in hay:
                    continue
            out.append(p)
        return out

    def _refresh_chips_counts(self) -> None:
        total = len(self._playlists)
        n_manual = sum(1 for p in self._playlists
                       if _kind_norm(p.get("kind")) == "manual")
        n_imported = sum(1 for p in self._playlists
                         if _kind_norm(p.get("kind")) == "imported")
        n_smart = sum(1 for p in self._playlists
                      if _kind_norm(p.get("kind")) == "smart")
        self._chips["all"].set_count(total)
        self._chips["manual"].set_count(n_manual)
        self._chips["imported"].set_count(n_imported)
        self._chips["smart"].set_count(n_smart)

    def _refresh_stats(self) -> None:
        total = len(self._playlists)
        n_manual = sum(1 for p in self._playlists
                       if _kind_norm(p.get("kind")) == "manual")
        n_imported = sum(1 for p in self._playlists
                         if _kind_norm(p.get("kind")) == "imported")
        n_smart = sum(1 for p in self._playlists
                      if _kind_norm(p.get("kind")) == "smart")
        n_scheduled = sum(1 for p in self._playlists
                          if p.get("scheduled_day"))
        n_tracks = sum(int(p.get("track_count") or 0) for p in self._playlists)
        total_dur_ms = sum(int(p.get("total_duration_ms") or 0)
                           for p in self._playlists)
        # Stat 1
        self._stat_total.set_value(
            str(total),
            f"{n_manual} manual · {n_imported} imported · {n_smart} smart")
        # Stat 2
        self._stat_tracks.set_value(
            f"{n_tracks:,}",
            "across all playlists" if total else "no playlists yet")
        # Stat 3 — avg duration per playlist (mm:ss)
        if total > 0:
            avg_ms = total_dur_ms // total
            avg_s = avg_ms // 1000
            self._stat_avg.set_value(
                f"{avg_s // 60}:{avg_s % 60:02d}",
                "min : sec per playlist")
        else:
            self._stat_avg.set_value("0:00", "no playlists yet")
        # Stat 4
        self._stat_scheduled.set_value(
            str(n_scheduled), "in this week's broadcast")

    def _refresh_grid(self) -> None:
        visible = self._visible_playlists()
        for i, card in enumerate(self._cards):
            if i < len(visible):
                card.set_data(visible[i])
                card.set_selected(int(visible[i]["id"]) == (self._selected_id or 0))
                card.show()
            else:
                card.hide()

    def _refresh_detail(self) -> None:
        if self._selected_id is None:
            self._detail.set_data(None, [], on_air=False)
            return
        row = next((p for p in self._playlists
                    if int(p["id"]) == self._selected_id), None)
        if row is None:
            self._detail.set_data(None, [], on_air=False)
            return
        try:
            tracks = self._db.get_playlist_first_tracks(int(row["id"]), limit=5)
        except Exception:
            tracks = []
        # ON AIR NOW — true if Studio's currently-playing track is in the
        # playlist. We don't have a cheap way to detect this without
        # tracking; for now mark on_air=False unless explicitly wired.
        on_air = self._is_playlist_on_air(int(row["id"]))
        self._detail.set_data(row, tracks, on_air=on_air)

    def _is_playlist_on_air(self, playlist_id: int) -> bool:
        """True iff the Studio deck is currently playing a song that lives
        in this playlist. Cheap join via membership table."""
        if self._studio is None:
            return False
        try:
            cur = getattr(self._studio, "_current_track", None)
        except Exception:
            cur = None
        if not cur or not cur.get("id"):
            return False
        try:
            row = self._db._conn().execute(
                "SELECT 1 FROM playlist_songs "
                "WHERE playlist_id = ? AND song_id = ? LIMIT 1",
                [int(playlist_id), int(cur["id"])],
            ).fetchone()
            return row is not None
        except Exception:
            return False

    # ── Handlers ─────────────────────────────────────────────────────

    def _on_search(self, text: str) -> None:
        if text == self._search_text:
            return
        self._search_text = text
        # Reset selection if it dropped out of view
        visible = self._visible_playlists()
        if self._selected_id is not None and not any(
                int(p["id"]) == self._selected_id for p in visible):
            self._selected_id = int(visible[0]["id"]) if visible else None
        self._refresh_grid()
        self._refresh_detail()

    def _on_chip_clicked(self, key: str) -> None:
        if key == self._filter_kind:
            return
        self._filter_kind = key
        for k, chip in self._chips.items():
            chip.set_active(k == key)
        # Reset selection if needed
        visible = self._visible_playlists()
        if self._selected_id is not None and not any(
                int(p["id"]) == self._selected_id for p in visible):
            self._selected_id = int(visible[0]["id"]) if visible else None
        self._refresh_grid()
        self._refresh_detail()

    def _on_card_selected(self, playlist_id: int) -> None:
        if playlist_id == self._selected_id:
            return
        self._selected_id = int(playlist_id)
        self._refresh_grid()
        self._refresh_detail()

    def _on_open_card(self, playlist_id: int) -> None:
        self.screen_requested.emit(f"playlist_edit:{int(playlist_id)}")

    def _on_preview_card(self, playlist_id: int) -> None:
        """Play the first track via the AudioEngine preview channel.
        Studio on-air status is not affected — preview rides on its own
        channel which is short-circuited by Studio's master mixer."""
        # Confirm if Studio is on-air
        if (self._studio is not None
                and getattr(self._studio, "_current_track", None) is not None):
            box = QMessageBox(self)
            box.setWindowTitle("Preview while on air?")
            box.setText("Studio is currently on air.\n\n"
                        "Preview will not affect the on-air output, but "
                        "make sure you're routing preview to monitors.")
            box.setStandardButtons(
                QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
            if box.exec() != QMessageBox.StandardButton.Ok:
                return
        if self._engine is None:
            QMessageBox.information(
                self, "Preview unavailable",
                "AudioEngine reference not wired into Playlists screen.")
            return
        try:
            tracks = self._db.get_playlist_first_tracks(int(playlist_id), limit=1)
        except Exception as exc:
            log.warning(f"preview track lookup failed: {exc}"); return
        if not tracks:
            QMessageBox.information(self, "Preview",
                                    "Playlist has no tracks.")
            return
        path = tracks[0].get("file_path")
        if not path:
            QMessageBox.information(self, "Preview",
                                    "Track file path missing.")
            return
        # Stop any prior preview
        if self._preview_cid is not None:
            try:
                self._engine.cleanup(self._preview_cid)
            except Exception:
                pass
            self._preview_cid = None
        try:
            cid = self._engine.load_file(path)
            self._engine.set_volume(cid, 75)
            self._engine.play(cid)
            self._preview_cid = cid
            log.info(
                f"[playlists] preview ch={cid} song={tracks[0].get('title')}")
        except Exception as exc:
            log.warning(f"preview load_file failed: {exc}")

    def _on_add_to_schedule(self, playlist_id: int) -> None:
        if self._scheduler is None or not hasattr(
                self._scheduler, "add_playlist_to_schedule"):
            QMessageBox.information(
                self, "Add to Schedule",
                "Scheduler engine reference not wired into Playlists.")
            return
        ok = bool(self._scheduler.add_playlist_to_schedule(int(playlist_id)))
        if ok:
            QMessageBox.information(
                self, "Added to Schedule",
                "Playlist queued for today's schedule.")
        else:
            QMessageBox.warning(
                self, "Add to Schedule",
                "Could not add playlist — see log for details.")
        self._reload_playlists()

    def _on_import_stub(self) -> None:
        QMessageBox.information(
            self, "Import",
            "Import — coming soon.\n\nOpens a file picker for M3U / CSV / "
            "JSON playlist imports.")

    def _on_overflow_stub(self, playlist_id: int) -> None:
        QMessageBox.information(
            self, "More",
            "Overflow menu — coming soon (Duplicate / Delete / Export).")

    # ── 1Hz tick ──────────────────────────────────────────────────────

    def _on_tick(self) -> None:
        from datetime import datetime
        now = datetime.now()
        date_str = f"{now.strftime('%B').upper()} {now.day}, {now.year}"
        self._header.set_time(
            now.strftime("%H:%M"),
            now.strftime(":%S"),
            now.strftime("%A").upper(),
            date_str,
        )
        self._live_pill.set_clock_text(now.strftime("%H:%M:%S"))

    # ── Page paint (gradient bg + breadcrumb + title + footer) ───────

    def paintEvent(self, evt):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QBrush(self._bg))

        # Breadcrumb
        p.setPen(QColor(COL_TEXT_MUTED))
        p.setFont(self._font_breadcrumb)
        p.drawText(QRectF(56, 110, 600, 16),
                   Qt.AlignmentFlag.AlignLeft, "SCHEDULING / PLAYLISTS")

        # Title
        p.setPen(QColor(COL_TEXT_PRIMARY))
        p.setFont(self._font_title)
        p.drawText(QRectF(56, 130, 600, 56),
                   Qt.AlignmentFlag.AlignLeft, "Playlists")
        # Subtitle
        p.setPen(QColor(COL_TEXT_SECONDARY))
        p.setFont(self._font_subtitle)
        p.drawText(QRectF(56, 188, 700, 18),
                   Qt.AlignmentFlag.AlignLeft,
                   "Build manual playlists, import from files, or queue them into the schedule")

        # Footer hairline at y=856
        hl = QLinearGradient(56, 0, 56 + 1328, 0)
        hl.setColorAt(0.0, QColor(255, 255, 255, 0))
        hl.setColorAt(0.5, QColor(255, 255, 255, int(0.06 * 255)))
        hl.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.fillRect(QRectF(56, 856, 1328, 1), QBrush(hl))

        # Footer version row
        p.setPen(QColor(COL_TEXT_MUTED))
        p.setFont(self._font_footer)
        p.drawText(QRectF(56, 868, 200, 14),
                   Qt.AlignmentFlag.AlignLeft, "RadioAI Studio Pro")
        p.setPen(QColor(COL_TEXT_DIM))
        p.setFont(self._font_footer_dot)
        p.drawText(QRectF(162, 868, 6, 14),
                   Qt.AlignmentFlag.AlignLeft, "•")
        p.setPen(QColor(COL_TEXT_MUTED))
        p.setFont(mono(10, bold=False, letter_spacing=0.3))
        p.drawText(QRectF(177, 868, 60, 14),
                   Qt.AlignmentFlag.AlignLeft, "v2.0.0")
        p.setPen(QColor(COL_TEXT_DIM))
        p.setFont(self._font_footer_dot)
        p.drawText(QRectF(225, 868, 6, 14),
                   Qt.AlignmentFlag.AlignLeft, "•")
        p.setPen(QColor(COL_TEXT_MUTED))
        p.setFont(self._font_footer_meta)
        n_total = len(self._playlists)
        n_tracks = sum(int(pl.get("track_count") or 0) for pl in self._playlists)
        p.drawText(QRectF(240, 868, 400, 14),
                   Qt.AlignmentFlag.AlignLeft,
                   f"{n_total} playlists · {n_tracks:,} tracks indexed")
        # Settings link
        p.setPen(QColor(COL_PURPLE))
        p.setFont(inter(14, QFont.Weight.Bold))
        p.drawText(QRectF(1314, 866, 18, 18),
                   Qt.AlignmentFlag.AlignLeft, "⚙")
        p.setPen(QColor(COL_PURPLE))
        p.setFont(self._font_settings)
        p.drawText(QRectF(1334, 868, 60, 14),
                   Qt.AlignmentFlag.AlignLeft, "Settings")
