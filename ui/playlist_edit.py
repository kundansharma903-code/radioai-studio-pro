"""
RadioAI Studio Pro — Edit Playlist (Figma 248:2 — Frame 9, Premium Dark).

Power-user playlist editor — reuses Frame 8 (Create New Playlist)
patterns (queue model, library search, debounce timer, engine wiring)
plus extra tooling: ▶ Preview from queue + transport bar with progress
slider + Analyze Selected Track right panel.

THE SCREEN that actually consumes the AudioEngine wiring landed in
commit 2a7c6ca. ▶ Preview button (top toolbar) and the transport ▶
both route through ``self._engine`` with on-air protection (confirm
dialog when ``studio._current_track is not None``).

Storage / wiring contract
-------------------------
- Top-level meta: ``db.update_playlist_draft(id, name, kind, color,
  tags)``  — partial UPDATE; misnamed but works for active playlists
  too (no status check inside; consistent across all playlist screens).
- Tracks: ``db.replace_playlist_songs(id, song_ids)`` — atomic
  DELETE+INSERT inside one transaction.
- Save calls both back-to-back. Each is atomic individually but not
  paired — failure in the second surfaces via QMessageBox so the user
  retries. Same pattern as Clock Editor's two-call save.
- Loaded via ``db.get_playlist(id)`` + ``db.get_playlist_songs(id)``
  (added in this commit).
- Filter / count: ``db.search_songs(query, category_id, ...)`` +
  ``db.count_songs(...)`` (existing — paginated by Frame 8's commit).

Layout (1440 × 900) — exact Figma 248:2 coords
-------------------------------------------
  HEADER         1440 ×  88
  Title block    @ y=116..220
  TOP TOOLBAR    1328 × 44   @ y=226 (Preview / Preview Breaks /
                                       search / mic + 4 tabs)
  LEFT COL       140 × 560   @ x=56,  y=290  (Preview Slot)
  ELEMENT ICONS  820 × 60    @ x=212, y=290  (7 type tiles)
  ACTION STACK   80  × 304   @ x=212, y=362  (5 vertical buttons)
  PLAYLIST TABLE 732 × 304   @ x=300, y=362
  FILTER PANEL   732 × 174   @ x=300, y=678  (search + checkboxes +
                                              category dropdown)
  ANALYZE PANEL  336 × 562   @ x=1048,y=290
  BOTTOM BAR     1440 × 50   @ y=866           (transport + save)

═══════════════════════════════════════════════════════════════════════════
PERFORMANCE INVARIANTS — DO NOT VIOLATE
═══════════════════════════════════════════════════════════════════════════
  1. event.rect() clipping in every paintEvent.
  2. Playlist queue uses QAbstractListModel with moveRows(); rows
     painted via custom delegate.
  3. mouseMoveEvent only during a real drag (no setMouseTracking).
  4. No DB calls in paintEvent — all preloaded.
  5. No self.update() inside paintEvent.
  6. Cached QGradient / QColor / QFont per element type in __init__.
  7. Drop shadows via QGraphicsDropShadowEffect.
  8. Search debounce 200ms (single-shot timer, restart on each keystroke).
  9. Transport progress slider — engine fires position_changed at ≤1Hz,
     we just forward; throttle is upstream.
═══════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import logging
from typing import Optional, Literal
from core import dialogs

from PyQt6.QtCore import (
    Qt, QRect, QRectF, QPoint, QPointF, QSize, QTimer, QModelIndex,
    QAbstractListModel, QMimeData, pyqtSignal, QEvent,
)
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QLinearGradient, QFont,
    QMouseEvent, QPaintEvent, QKeyEvent, QPainterPath,
)
from PyQt6.QtWidgets import (
    QWidget, QMessageBox, QGraphicsDropShadowEffect, QLineEdit,
    QMenu, QListView, QStyledItemDelegate, QStyleOptionViewItem,
    QAbstractItemView, QFrame, QStyle,
)

from ui.widgets.tokens import (
    inter, mono,
    COL_BG_TOP, COL_BG_MID, COL_BG_BOT,
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
    Header, drop_shadow, WINDOW_W, HEADER_H,
)

log = logging.getLogger("PlaylistEdit")

WINDOW_H = 900

# ── Element types ────────────────────────────────────────────────────────

# Frame 9 shows 7 type tiles. The first 5 are real (match Clock Editor's
# DB-backed types); 📁 Folder + ♥ Heart are render-only — no songs schema
# field for either. Click → "Coming soon" toast. NIGHT_LOG carry-over.
ELEMENT_TYPES: list[str] = [
    "song", "jingle", "spot", "voice", "sweeper", "folder", "heart",
]
ELEMENT_ICONS = {
    "song":    "♪",  "jingle": "🔔", "spot": "$",
    "voice":   "🎤", "sweeper": "★",
    "folder":  "📁", "heart":   "♥",
}
ELEMENT_COLORS = {
    "song":    COL_AMBER_LT,
    "jingle":  COL_CYAN_LT,
    "spot":    COL_GREEN_LT,
    "voice":   "#f472b6",      # pink (matches Clock Editor)
    "sweeper": COL_PURPLE_LT,
    "folder":  COL_PURPLE_MID,
    "heart":   COL_ROSE,
}
# Element types that actually filter the song library
FUNCTIONAL_TYPES = {"song", "jingle", "spot", "voice", "sweeper"}

# ── Format helpers ───────────────────────────────────────────────────────


def _fmt_duration(ms: Optional[int]) -> str:
    """Format milliseconds as M:SS (or H:MM:SS for ≥1h). Robust to None."""
    s = max(0, int(ms or 0)) // 1000
    h, rem = divmod(s, 3600)
    m, ss = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{ss:02d}"
    return f"{m}:{ss:02d}"


def _fmt_loaded_total(elements: list[dict]) -> str:
    """HH:MM:SS aggregate of every element's duration_ms (default 240s
    for items missing a duration — matches Clock Editor convention)."""
    total_ms = 0
    for el in elements:
        d = el.get("duration_ms") or el.get("duration_seconds")
        if d is None:
            total_ms += 240_000
            continue
        # Allow either ms or seconds depending on source row
        if isinstance(d, (int, float)):
            total_ms += int(d * 1000) if d < 60 * 60 else int(d)
    s = total_ms // 1000
    h, rem = divmod(s, 3600)
    m, ss = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{ss:02d}"


# ── Common QMenu styling shared with Clock Editor's dropdowns ───────────

_MENU_QSS = (
    "QMenu { background: #0e1020; border: 1px solid rgba(255,255,255,0.1); "
    "border-radius: 8px; padding: 4px; color: #f1f5ff; }"
    "QMenu::item { padding: 6px 16px; border-radius: 4px; "
    "font-family: Inter; font-size: 12px; }"
    "QMenu::item:selected { background: rgba(6,182,212,0.18); color: #22d3ee; }"
    "QMenu::separator { height: 1px; background: rgba(255,255,255,0.06); "
    "margin: 4px 8px; }"
)


# Common painter helpers


def _qfill_card(p: QPainter, rect: QRectF) -> None:
    bg = QLinearGradient(0, 0, 0, rect.height())
    bg.setColorAt(0.0, QColor(14, 16, 32, 242))
    bg.setColorAt(1.0, QColor(7, 9, 18, 242))
    p.fillRect(rect, QBrush(bg))


def _qstroke_card(p: QPainter, rect: QRectF, radius: float = 12.0) -> None:
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(QColor(255, 255, 255, 18)))
    p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)


def _draw_top_accent(p: QPainter, w: int, color_a: str,
                     color_b: Optional[str] = None,
                     mid: Optional[str] = None) -> None:
    grad = QLinearGradient(0, 0, w, 0)
    grad.setColorAt(0.0, QColor(color_a))
    if mid:
        grad.setColorAt(0.5, QColor(mid))
    grad.setColorAt(1.0, QColor(color_b or color_a))
    p.fillRect(QRectF(0, 0, w, 3), QBrush(grad))


# ════════════════════════════════════════════════════════════════════════
# TOP TOOLBAR — Preview / Preview Breaks / Search / Mic + 4 tabs
# ════════════════════════════════════════════════════════════════════════

class _ToolbarButton(QWidget):
    """Generic toolbar button with icon + label. Click → ``clicked``."""
    clicked = pyqtSignal()

    def __init__(self, label: str, accent: str, width: int = 80,
                 with_dot: bool = False, parent=None):
        super().__init__(parent)
        self.setFixedSize(width, 28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._label = label
        self._accent = accent
        self._with_dot = with_dot
        self._hover = False
        self._font = inter(11, QFont.Weight.Bold, letter_spacing=0.2)

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
        alpha = 0.20 if self._hover else 0.10
        p.fillRect(r, _qcolor(self._accent, alpha))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_qcolor(self._accent, 0.45)))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
        # Optional rec dot
        x_text = 10
        if self._with_dot:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(self._accent))
            p.drawEllipse(QRectF(8, 10, 8, 8))
            x_text = 22
        p.setPen(_qcolor(self._accent, 0.95))
        p.setFont(self._font)
        p.drawText(QRectF(x_text, 0, self.width() - x_text - 8, self.height()),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._label)
        p.end()


class _TabButton(QWidget):
    clicked = pyqtSignal(str)

    def __init__(self, key: str, label: str, parent=None):
        super().__init__(parent)
        self.setFixedSize(150, 32)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._key = key
        self._label = label
        self._active = False
        self._font_active = inter(13, QFont.Weight.Black, letter_spacing=-0.1)
        self._font_inactive = inter(13, QFont.Weight.Medium, letter_spacing=-0.1)

    def set_active(self, on: bool) -> None:
        if on == self._active:
            return
        self._active = bool(on)
        self.update(self.rect())

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._key)
        super().mousePressEvent(e)

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._active:
            p.setPen(QColor(COL_TEXT_PRIMARY))
            p.setFont(self._font_active)
        else:
            p.setPen(QColor(COL_TEXT_SECONDARY))
            p.setFont(self._font_inactive)
        p.drawText(QRectF(0, 0, self.width(), self.height() - 6),
                   Qt.AlignmentFlag.AlignCenter, self._label)
        if self._active:
            grad = QLinearGradient(0, 0, self.width(), 0)
            grad.setColorAt(0.0, QColor(COL_CYAN))
            grad.setColorAt(1.0, QColor(COL_PINK))
            bar_w = max(40, len(self._label) * 8)
            x = (self.width() - bar_w) // 2
            p.fillRect(QRectF(x, self.height() - 4, bar_w, 3), QBrush(grad))
        p.end()


class _TopToolbar(QWidget):
    """1328 × 44 toolbar: action buttons left, tab row right."""

    preview_clicked     = pyqtSignal()
    preview_breaks_clicked = pyqtSignal()
    search_clicked      = pyqtSignal()
    mic_clicked         = pyqtSignal()
    tab_clicked         = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(1328, 44)
        # Action buttons (left)
        self._btn_preview = _ToolbarButton("▶ Preview", COL_GREEN, 100, parent=self)
        self._btn_preview.move(8, 8)
        self._btn_preview.clicked.connect(self.preview_clicked.emit)

        self._btn_breaks = _ToolbarButton("● Preview Breaks", COL_ROSE, 138,
                                          with_dot=False, parent=self)
        self._btn_breaks.move(116, 8)
        self._btn_breaks.clicked.connect(self.preview_breaks_clicked.emit)

        self._btn_search = _ToolbarButton("⌕ search", COL_CYAN, 90, parent=self)
        self._btn_search.move(262, 8)
        self._btn_search.clicked.connect(self.search_clicked.emit)

        self._btn_mic = _ToolbarButton("🎤", COL_PINK, 36, parent=self)
        self._btn_mic.move(360, 8)
        self._btn_mic.clicked.connect(self.mic_clicked.emit)

        # Tabs (right)
        self._tab_edit = _TabButton("edit", "Edit Playlist", self)
        self._tab_edit.move(700, 6); self._tab_edit.set_active(True)
        self._tab_edit.clicked.connect(self.tab_clicked.emit)

        self._tab_memos = _TabButton("memos", "Memos", self)
        self._tab_memos.move(860, 6)
        self._tab_memos.clicked.connect(self.tab_clicked.emit)

        self._tab_sched = _TabButton("schedule", "Schedule & Details", self)
        self._tab_sched.move(1020, 6)
        self._tab_sched.clicked.connect(self.tab_clicked.emit)

        self._tab_export = _TabButton("export", "Export Playlist", self)
        self._tab_export.move(1175, 6)
        self._tab_export.clicked.connect(self.tab_clicked.emit)

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        _qfill_card(p, r)
        _qstroke_card(p, r, radius=10)
        p.end()


# ════════════════════════════════════════════════════════════════════════
# PREVIEW SLOT — left-column placeholder showing the selected track
# ════════════════════════════════════════════════════════════════════════

class _PreviewSlot(QWidget):
    """140 × 560 column. Shows the currently-selected queue track meta
    (artist / title / duration). Empty state when no selection."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(140, 560)
        self._track: Optional[dict] = None
        self._font_h = inter(11, QFont.Weight.Black, letter_spacing=1.2)
        self._font_artist = inter(12, QFont.Weight.Bold, letter_spacing=-0.1)
        self._font_title  = inter(11, QFont.Weight.Medium)
        self._font_dur    = mono(11, bold=True)
        self._font_em     = inter(11, QFont.Weight.Bold, letter_spacing=1.5)

    def set_track(self, track: Optional[dict]) -> None:
        self._track = dict(track) if track else None
        self.update(self.rect())

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        _qfill_card(p, r)
        _draw_top_accent(p, self.width(), COL_AMBER, COL_AMBER + "55")
        _qstroke_card(p, r)
        # Header
        p.setPen(QColor(COL_AMBER_LT)); p.setFont(self._font_h)
        p.drawText(QRectF(12, 14, self.width() - 24, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "PREVIEW SLOT")
        if self._track is None:
            # Empty state — big "—"
            p.setPen(QColor(COL_TEXT_DIM))
            p.setFont(inter(48, QFont.Weight.Black))
            p.drawText(QRectF(0, 0, self.width(), self.height()),
                       Qt.AlignmentFlag.AlignCenter, "—")
            return
        # Filled state
        p.setPen(QColor(COL_TEXT_PRIMARY)); p.setFont(self._font_artist)
        p.drawText(QRectF(12, 60, self.width() - 24, 18),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   str(self._track.get("artist") or "Unknown Artist"))
        p.setPen(QColor(COL_TEXT_SECONDARY)); p.setFont(self._font_title)
        p.drawText(QRectF(12, 80, self.width() - 24, 80),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
                   | Qt.TextFlag.TextWordWrap,
                   str(self._track.get("title") or ""))
        p.setPen(QColor(COL_AMBER_LT)); p.setFont(self._font_dur)
        p.drawText(QRectF(12, 170, self.width() - 24, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   _fmt_duration(self._track.get("duration_ms")))
        p.end()


# ════════════════════════════════════════════════════════════════════════
# ELEMENT-ICON ROW — 7 type tiles with single-select
# ════════════════════════════════════════════════════════════════════════

class _ElementIconTile(QWidget):
    clicked = pyqtSignal(str)

    def __init__(self, key: str, parent=None):
        super().__init__(parent)
        self.setFixedSize(110, 60)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._key = key
        self._color = ELEMENT_COLORS[key]
        self._icon = ELEMENT_ICONS[key]
        self._active = False
        self._font = inter(24, QFont.Weight.Black)

    def set_active(self, on: bool) -> None:
        if on == self._active:
            return
        self._active = bool(on)
        self.update(self.rect())

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._key)
        super().mousePressEvent(e)

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        if self._active:
            grad = QLinearGradient(0, 0, self.width(), 0)
            grad.setColorAt(0.0, _qcolor(self._color, 0.30))
            grad.setColorAt(1.0, _qcolor(self._color, 0.10))
            p.fillRect(r, QBrush(grad))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(_qcolor(self._color, 0.55)))
        else:
            p.fillRect(r, QColor(7, 8, 16, 153))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(255, 255, 255, 22)))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        p.setPen(QColor(self._color))
        p.setFont(self._font)
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, self._icon)
        p.end()


class _ElementIconRow(QWidget):
    """820 × 60 row with 7 type tiles."""

    type_changed = pyqtSignal(str)
    placeholder_clicked = pyqtSignal(str)   # for 📁 / ♥

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(820, 60)
        self._current = "song"
        self._tiles: dict[str, _ElementIconTile] = {}
        for i, t in enumerate(ELEMENT_TYPES):
            tile = _ElementIconTile(t, self)
            tile.move(i * 116, 0)
            tile.clicked.connect(self._on_tile_clicked)
            self._tiles[t] = tile
        self._tiles["song"].set_active(True)

    def current(self) -> str:
        return self._current

    def set_current(self, key: str) -> None:
        if key not in ELEMENT_TYPES or key == self._current:
            return
        if key not in FUNCTIONAL_TYPES:
            return    # decorative, can't be "current"
        self._current = key
        for k, tile in self._tiles.items():
            tile.set_active(k == key)

    def _on_tile_clicked(self, key: str) -> None:
        if key not in FUNCTIONAL_TYPES:
            self.placeholder_clicked.emit(key)
            return
        self.set_current(key)
        self.type_changed.emit(key)


# ════════════════════════════════════════════════════════════════════════
# ACTION STACK — 5 vertical buttons (ADD / INSERT / REPLACE / PREPAIR / DELETE)
# ════════════════════════════════════════════════════════════════════════

class _ActionTile(QWidget):
    clicked = pyqtSignal()

    def __init__(self, icon: str, label: str, accent: str = COL_GREEN,
                 primary: bool = False, parent=None):
        super().__init__(parent)
        self.setFixedSize(64, 50)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._icon = icon; self._label = label
        self._accent = accent; self._primary = primary
        self._enabled = True
        self._font_icon  = inter(20, QFont.Weight.Black)
        self._font_label = inter(8, QFont.Weight.Black, letter_spacing=0.5)
        if primary:
            self.setGraphicsEffect(drop_shadow(12, _qcolor(accent, 0.4), 4))

    def set_enabled(self, on: bool) -> None:
        if on == self._enabled:
            return
        self._enabled = bool(on)
        self.setCursor(Qt.CursorShape.PointingHandCursor if on
                       else Qt.CursorShape.ForbiddenCursor)
        self.update(self.rect())

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if self._enabled and e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        if self._primary and self._enabled:
            grad = QLinearGradient(0, 0, 0, self.height())
            grad.setColorAt(0.0, _qcolor(self._accent, 0.95))
            grad.setColorAt(1.0, _qcolor(COL_GREEN_DK, 0.95))
            p.fillRect(r, QBrush(grad))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(255, 255, 255, 30)))
            p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
            text_color = QColor(255, 255, 255)
        else:
            alpha = 0.18 if self._enabled else 0.05
            p.fillRect(r, _qcolor(self._accent, alpha))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(_qcolor(self._accent,
                                  0.4 if self._enabled else 0.12)))
            p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
            text_color = (_qcolor(self._accent, 0.95) if self._enabled
                          else _qcolor(self._accent, 0.30))
        p.setPen(text_color); p.setFont(self._font_icon)
        p.drawText(QRectF(0, 4, self.width(), 24),
                   Qt.AlignmentFlag.AlignCenter, self._icon)
        p.setFont(self._font_label)
        p.drawText(QRectF(0, 30, self.width(), 16),
                   Qt.AlignmentFlag.AlignCenter, self._label)
        p.end()


class _ActionStack(QWidget):
    add_clicked     = pyqtSignal()
    insert_clicked  = pyqtSignal()
    replace_clicked = pyqtSignal()
    prepair_clicked = pyqtSignal()
    delete_clicked  = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(80, 304)
        self._add = _ActionTile("+", "ADD", COL_GREEN, primary=True, parent=self)
        self._add.move(8, 8); self._add.clicked.connect(self.add_clicked.emit)
        self._ins = _ActionTile("↳", "INSERT", COL_GREEN, parent=self)
        self._ins.move(8, 66); self._ins.clicked.connect(self.insert_clicked.emit)
        self._ins.set_enabled(False)
        self._rep = _ActionTile("⇄", "REPLACE", COL_GREEN, parent=self)
        self._rep.move(8, 124); self._rep.clicked.connect(self.replace_clicked.emit)
        self._rep.set_enabled(False)
        self._prep = _ActionTile("🎙", "PREPAIR", COL_PINK, parent=self)
        self._prep.move(8, 182); self._prep.clicked.connect(self.prepair_clicked.emit)
        self._del = _ActionTile("🗑", "DELETE", COL_ROSE, parent=self)
        self._del.move(8, 240); self._del.clicked.connect(self.delete_clicked.emit)
        self._del.set_enabled(False)

    def set_states(self, add_on: bool, has_selection: bool) -> None:
        self._add.set_enabled(add_on)
        self._ins.set_enabled(has_selection)
        self._rep.set_enabled(has_selection)
        self._del.set_enabled(has_selection)

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        _qfill_card(p, r)
        _qstroke_card(p, r, radius=10)
        p.end()


# ════════════════════════════════════════════════════════════════════════
# PLAYLIST QUEUE MODEL + TABLE
# ════════════════════════════════════════════════════════════════════════

class _QueueModel(QAbstractListModel):
    """In-memory queue. ``rows`` is a list of dicts with at least:
    ``id``, ``artist``, ``title``, ``duration_ms``. Drag-internal-move
    via moveRows(). Atomic save on OK — see PlaylistEdit._save."""

    queue_changed = pyqtSignal()    # emitted on any add/remove/move

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[dict] = []

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def data(self, idx: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not idx.isValid() or idx.row() >= len(self._rows):
            return None
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return self._rows[idx.row()]
        return None

    def flags(self, idx: QModelIndex):
        f = super().flags(idx)
        if idx.isValid():
            f |= (Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
                  | Qt.ItemFlag.ItemIsDragEnabled)
        else:
            f |= Qt.ItemFlag.ItemIsDropEnabled
        return f

    def supportedDropActions(self):
        return Qt.DropAction.MoveAction

    def supportedDragActions(self):
        return Qt.DropAction.MoveAction

    # ── Drag/drop internal-move plumbing ─────────────────────────────────
    # Qt's default DnD pipeline drives mimeData()/dropMimeData(), never
    # moveRows() directly. We carry the source row in a private mime type
    # and route the drop back through the existing moveRows() so the
    # reorder + queue_changed signal (→ dirty/save) stay in one place.

    _MIME = "application/x-radioai-queue-row"

    def mimeTypes(self):
        return [self._MIME]

    def mimeData(self, indexes):
        rows = sorted({i.row() for i in indexes if i.isValid()})
        md = QMimeData()
        if rows:
            md.setData(self._MIME, str(rows[0]).encode("ascii"))
        return md

    def dropMimeData(self, data, action, row, column, parent):
        if action != Qt.DropAction.MoveAction:
            return False
        if not data.hasFormat(self._MIME):
            return False
        try:
            src = int(bytes(data.data(self._MIME)).decode("ascii"))
        except (ValueError, TypeError):
            return False
        # Resolve the insertion index Qt handed us. row == -1 means the
        # drop landed on/after the last item → append to the end.
        if row < 0:
            dest = parent.row() if parent.isValid() else len(self._rows)
        else:
            dest = row
        self.moveRows(QModelIndex(), src, 1, QModelIndex(), dest)
        # Always return False: we complete the reorder in-place via
        # moveRows(). Returning True would make QAbstractItemView's
        # InternalMove pipeline call removeRows() on the (now stale)
        # source row afterwards, deleting the wrong track.
        return False

    # ── Python-side mutators ─────────────────────────────────────────────

    def replace_all(self, rows: list[dict]) -> None:
        self.beginResetModel()
        self._rows = list(rows or [])
        self.endResetModel()
        self.queue_changed.emit()

    def append(self, row: dict) -> int:
        n = len(self._rows)
        self.beginInsertRows(QModelIndex(), n, n)
        self._rows.append(dict(row))
        self.endInsertRows()
        self.queue_changed.emit()
        return n

    def insert_at(self, position: int, row: dict) -> int:
        position = max(0, min(position, len(self._rows)))
        self.beginInsertRows(QModelIndex(), position, position)
        self._rows.insert(position, dict(row))
        self.endInsertRows()
        self.queue_changed.emit()
        return position

    def replace_at(self, position: int, row: dict) -> None:
        if position < 0 or position >= len(self._rows):
            return
        self._rows[position] = dict(row)
        idx = self.index(position, 0)
        self.dataChanged.emit(idx, idx)
        self.queue_changed.emit()

    def remove_at(self, position: int) -> None:
        if position < 0 or position >= len(self._rows):
            return
        self.beginRemoveRows(QModelIndex(), position, position)
        del self._rows[position]
        self.endRemoveRows()
        self.queue_changed.emit()

    def moveRows(self, sourceParent, sourceRow, count, destParent, destRow) -> bool:
        if count != 1:
            return False
        n = len(self._rows)
        if sourceRow < 0 or sourceRow >= n:
            return False
        destRow = max(0, min(destRow, n))
        if destRow == sourceRow or destRow == sourceRow + 1:
            return False
        ok = self.beginMoveRows(QModelIndex(), sourceRow, sourceRow,
                                QModelIndex(), destRow)
        if not ok:
            return False
        item = self._rows.pop(sourceRow)
        target = destRow - 1 if destRow > sourceRow else destRow
        self._rows.insert(target, item)
        self.endMoveRows()
        self.queue_changed.emit()
        return True

    def all_rows(self) -> list[dict]:
        return [dict(r) for r in self._rows]

    def song_ids(self) -> list[int]:
        return [int(r["id"]) for r in self._rows if r.get("id") is not None]


class _QueueRowDelegate(QStyledItemDelegate):
    """Custom paint for one queue row: NAME / TITLE / RUN TIME columns
    on a yellow-tinted band."""

    ROW_H = 30

    def __init__(self, parent=None):
        super().__init__(parent)
        self._font_artist = inter(12, QFont.Weight.Bold, letter_spacing=-0.1)
        self._font_title  = inter(11, QFont.Weight.Medium)
        self._font_dur    = mono(11, bold=True)
        self._font_index  = mono(10, bold=False)

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        return QSize(option.rect.width(), self.ROW_H)

    def paint(self, p: QPainter, option: QStyleOptionViewItem,
              index: QModelIndex) -> None:
        row = index.data(Qt.ItemDataRole.DisplayRole) or {}
        rect = option.rect
        sel = bool(option.state & QStyle.StateFlag.State_Selected)
        # Background — alternating amber tint
        if sel:
            p.fillRect(rect, _qcolor(COL_AMBER, 0.30))
        else:
            tint_alpha = 0.10 if (index.row() % 2 == 0) else 0.06
            p.fillRect(rect, _qcolor(COL_AMBER, tint_alpha))
        # Index column (left)
        p.setPen(QColor(COL_TEXT_DIM)); p.setFont(self._font_index)
        p.drawText(QRect(rect.x() + 8, rect.y(), 20, rect.height()),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   f"{index.row() + 1}")
        # NAME (artist) column
        p.setPen(QColor(COL_TEXT_PRIMARY)); p.setFont(self._font_artist)
        p.drawText(QRect(rect.x() + 36, rect.y(), 220, rect.height()),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   str(row.get("artist") or "—"))
        # TITLE column
        p.setPen(QColor(COL_TEXT_SECONDARY)); p.setFont(self._font_title)
        p.drawText(QRect(rect.x() + 268, rect.y(), 320, rect.height()),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   str(row.get("title") or "—"))
        # RUN TIME (right)
        p.setPen(QColor(COL_AMBER_LT)); p.setFont(self._font_dur)
        p.drawText(QRect(rect.x() + rect.width() - 80, rect.y(), 70, rect.height()),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   _fmt_duration(row.get("duration_ms")))


class _PlaylistTable(QListView):
    """QListView wrapper with custom delegate. Supports drag-internal-move
    via the model's moveRows()."""

    def __init__(self, model: _QueueModel, parent=None):
        super().__init__(parent)
        self.setFixedSize(732, 274)
        self.setModel(model)
        self.setItemDelegate(_QueueRowDelegate(self))
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDragEnabled(True); self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setUniformItemSizes(True)
        self.setSpacing(0)
        self.setStyleSheet(
            "QListView { background: transparent; border: none; "
            "outline: 0; }"
            "QListView::item { padding: 0; }"
            "QScrollBar:vertical { background: rgba(255,255,255,0.02); "
            "width: 6px; }"
            "QScrollBar::handle:vertical { background: rgba(245,158,11,0.4); "
            "border-radius: 3px; min-height: 24px; }"
            "QScrollBar::handle:vertical:hover { background: rgba(245,158,11,0.6); }"
            "QScrollBar::add-line, QScrollBar::sub-line { height: 0; }"
        )

    def selected_row(self) -> Optional[int]:
        idx = self.currentIndex()
        return idx.row() if idx.isValid() else None


class _PlaylistTableCard(QWidget):
    """732 × 304 wrapper: header row (NAME / TITLE / RUN TIME) + the table."""

    selection_changed = pyqtSignal(int)   # row index, -1 for none

    def __init__(self, model: _QueueModel, parent=None):
        super().__init__(parent)
        self.setFixedSize(732, 304)
        self._font_h = inter(10, QFont.Weight.Black, letter_spacing=1.2)
        self._table = _PlaylistTable(model, self)
        self._table.move(0, 30)
        sm = self._table.selectionModel()
        if sm is not None:
            sm.currentRowChanged.connect(self._on_row_changed)

    def table(self) -> _PlaylistTable:
        return self._table

    def _on_row_changed(self, current: QModelIndex, _previous):
        self.selection_changed.emit(current.row() if current.isValid() else -1)

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        _qfill_card(p, r)
        _qstroke_card(p, r, radius=10)
        # Column header row
        p.setPen(QColor(COL_TEXT_DIM)); p.setFont(self._font_h)
        p.drawText(QRectF(36, 0, 200, 30),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "NAME")
        p.drawText(QRectF(268, 0, 200, 30),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "TITLE")
        p.drawText(QRectF(self.width() - 90, 0, 70, 30),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   "RUN TIME")
        p.fillRect(QRectF(0, 30, self.width(), 1),
                   QColor(255, 255, 255, 18))
        p.end()


# ════════════════════════════════════════════════════════════════════════
# FILTER PANEL — search + 3 checkboxes + category dropdown
# ════════════════════════════════════════════════════════════════════════

class _PillButton(QWidget):
    clicked = pyqtSignal()

    def __init__(self, label: str, accent: str = COL_CYAN, w: int = 70,
                 parent=None):
        super().__init__(parent)
        self.setFixedSize(w, 30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._label = label
        self._accent = accent
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
        p.fillRect(r, _qcolor(self._accent, 0.20 if self._hover else 0.10))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_qcolor(self._accent, 0.45)))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
        p.setPen(_qcolor(self._accent, 0.95)); p.setFont(self._font)
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, self._label)
        p.end()


class _Checkbox(QWidget):
    """Reused from clock_editor's pattern — local copy to keep
    playlist_edit.py self-contained."""
    toggled = pyqtSignal(bool)

    def __init__(self, label: str, accent: str = COL_CYAN, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._label = label
        self._accent = accent
        self._checked = False
        self._font = inter(11, QFont.Weight.Medium)
        self.setFixedSize(int(20 + len(label) * 7), 18)

    def is_checked(self) -> bool: return self._checked

    def set_checked(self, on: bool) -> None:
        if on == self._checked:
            return
        self._checked = bool(on)
        self.update(self.rect())

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._checked = not self._checked
            self.update(self.rect())
            self.toggled.emit(self._checked)
        super().mousePressEvent(e)

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        box = QRectF(0, 2, 14, 14)
        if self._checked:
            p.fillRect(box, _qcolor(self._accent, 0.25))
            p.setPen(QPen(_qcolor(self._accent, 0.95), 1.5))
        else:
            p.fillRect(box, QColor(7, 8, 16, 178))
            p.setPen(QPen(QColor(255, 255, 255, 50), 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(box.adjusted(0.5, 0.5, -0.5, -0.5), 3, 3)
        if self._checked:
            p.setPen(QColor(self._accent))
            p.setFont(inter(10, QFont.Weight.Bold))
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, "✓")
        p.setPen(_qcolor(self._accent if self._checked else COL_TEXT_SECONDARY, 0.95))
        p.setFont(self._font)
        p.drawText(QRectF(20, 0, self.width() - 22, self.height()),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._label)
        p.end()


class _CategoryDropdown(QWidget):
    """Big 380×44 cyan-glow category picker."""

    selection_changed = pyqtSignal(int, str)   # (cat_id or -1, name)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(380, 44)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._categories: list[dict] = []
        self._selected_id: Optional[int] = None
        self._selected_name = "All Songs"
        self._total_song_count = 0
        self._font_main = inter(13, QFont.Weight.Bold, letter_spacing=-0.2)
        self._font_count = mono(10)
        self._font_chev = inter(11, QFont.Weight.Bold)
        self.setGraphicsEffect(drop_shadow(8, _qcolor(COL_CYAN, 0.2), 3))

    def set_categories(self, cats: list[dict], total: int) -> None:
        self._categories = list(cats or [])
        self._total_song_count = int(total or 0)
        self.update(self.rect())

    def selected_id(self) -> Optional[int]:
        return self._selected_id

    def selected_name(self) -> str:
        return self._selected_name

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._open_menu()
        super().mousePressEvent(e)

    def _open_menu(self) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(_MENU_QSS)
        all_act = menu.addAction(f"All Songs · {self._total_song_count} songs")
        all_act.setData(-1)
        if self._categories:
            menu.addSeparator()
        for c in self._categories:
            cid = int(c.get("id") or -1)
            cnt = int(c.get("song_count") or 0)
            act = menu.addAction(f"{c.get('name')} · {cnt} songs")
            act.setData(cid)
        chosen = menu.exec(self.mapToGlobal(QPoint(0, self.height())))
        if chosen is None:
            return
        new_id = chosen.data()
        if not isinstance(new_id, int):
            return
        if new_id == -1:
            self._selected_id = None
            self._selected_name = "All Songs"
        else:
            self._selected_id = new_id
            for c in self._categories:
                if int(c.get("id") or -1) == new_id:
                    self._selected_name = str(c.get("name") or "Category")
                    break
        self.update(self.rect())
        self.selection_changed.emit(new_id, self._selected_name)

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        grad = QLinearGradient(0, 0, self.width(), 0)
        grad.setColorAt(0.0, _qcolor(COL_CYAN, 0.10))
        grad.setColorAt(1.0, _qcolor(COL_CYAN, 0.04))
        p.fillRect(r, QBrush(grad))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_qcolor(COL_CYAN, 0.4)))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(_qcolor(COL_CYAN_LT, 0.95))
        p.drawEllipse(QRectF(11, 17, 10, 10))
        p.setPen(_qcolor(COL_CYAN_LT, 0.95)); p.setFont(self._font_main)
        p.drawText(QRectF(28, 4, self.width() - 60, 20),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._selected_name)
        if self._selected_id is None:
            count_str = f"{self._total_song_count:,} songs"
        else:
            cnt = next((c.get("song_count") for c in self._categories
                        if int(c.get("id") or -1) == self._selected_id), 0)
            count_str = f"{int(cnt or 0):,} songs"
        p.setPen(QColor(COL_TEXT_SECONDARY)); p.setFont(self._font_count)
        p.drawText(QRectF(28, 22, self.width() - 60, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   count_str)
        p.setPen(_qcolor(COL_CYAN_LT, 0.95)); p.setFont(self._font_chev)
        p.drawText(QRectF(self.width() - 22, 0, 18, self.height()),
                   Qt.AlignmentFlag.AlignCenter, "▾")
        p.end()


class _FilterPanel(QWidget):
    """732 × 174 — search input + buttons + checkboxes + category dropdown."""

    filter_changed = pyqtSignal()
    search_clicked = pyqtSignal()
    reset_clicked  = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(732, 174)

        self._font_count = inter(11, QFont.Weight.Bold, letter_spacing=0.3)
        self._font_helper = inter(10, QFont.Weight.Medium)
        self._font_manage = inter(10, QFont.Weight.Bold, letter_spacing=0.3)

        self._results_count = 0
        self._cat_total = 0

        # Search input (220×30) at (16, 16)
        self._search = QLineEdit(self)
        self._search.setGeometry(16, 16, 220, 30)
        self._search.setPlaceholderText("Search songs by title or artist…")
        self._search.setFont(inter(11, QFont.Weight.Medium))
        self._search.setStyleSheet(
            "QLineEdit { background: rgba(7,8,16,0.7); "
            "border: 1px solid rgba(255,255,255,0.10); border-radius: 6px; "
            f"color: {COL_TEXT_PRIMARY}; padding: 0 10px; }} "
            f"QLineEdit::placeholder {{ color: {COL_TEXT_DIM}; }} "
            "QLineEdit:focus { border-color: rgba(6,182,212,0.5); }"
        )
        self._search.textChanged.connect(lambda _: self.filter_changed.emit())

        # Search button + Reset button
        self._btn_search = _PillButton("Search", COL_CYAN, 70, self)
        self._btn_search.move(316, 16)
        self._btn_search.clicked.connect(self.search_clicked.emit)
        self._btn_reset = _PillButton("Reset", COL_ROSE, 70, self)
        self._btn_reset.move(390, 16)
        self._btn_reset.clicked.connect(self._on_reset)

        # Checkboxes (y=58)
        self._cb_super = _Checkbox("SuperSearch", COL_CYAN, self)
        self._cb_super.move(16, 58); self._cb_super.set_checked(True)
        self._cb_super.toggled.connect(lambda _: self.filter_changed.emit())
        self._cb_new = _Checkbox("Show Only NEW Additions", COL_PURPLE_MID, self)
        self._cb_new.move(140, 58)
        self._cb_new.toggled.connect(lambda _: self.filter_changed.emit())
        self._cb_surname = _Checkbox("Sort by Surname", COL_AMBER_LT, self)
        self._cb_surname.move(360, 58)
        self._cb_surname.toggled.connect(lambda _: self.filter_changed.emit())

        # Category dropdown (380×44 at 16, 96)
        self._cat = _CategoryDropdown(self)
        self._cat.move(16, 96)
        self._cat.selection_changed.connect(lambda *_: self.filter_changed.emit())

    # ── Public API ───────────────────────────────────────────────────────

    def search_text(self) -> str:
        return self._search.text().strip()

    def category_id(self) -> Optional[int]:
        return self._cat.selected_id()

    def super_search(self) -> bool:
        return self._cb_super.is_checked()

    def only_new(self) -> bool:
        return self._cb_new.is_checked()

    def sort_by_surname(self) -> bool:
        return self._cb_surname.is_checked()

    def set_categories(self, cats: list[dict], total: int) -> None:
        self._cat_total = len(cats or [])
        self._cat.set_categories(cats, total)

    def set_results_count(self, n: int) -> None:
        if n == self._results_count:
            return
        self._results_count = int(n)
        self.update(QRect(245, 16, 60, 30))

    def _on_reset(self) -> None:
        self._search.clear()
        self._cb_super.set_checked(True)
        self._cb_new.set_checked(False)
        self._cb_surname.set_checked(False)
        self._cat.set_categories(self._cat._categories, self._cat._total_song_count)
        self._cat._selected_id = None
        self._cat._selected_name = "All Songs"
        self._cat.update(self._cat.rect())
        self.filter_changed.emit()
        self.reset_clicked.emit()

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        _qfill_card(p, r)
        _qstroke_card(p, r, radius=10)
        # Songs Found pill
        p.setPen(QColor(COL_AMBER_LT)); p.setFont(self._font_count)
        p.drawText(QRectF(245, 16, 70, 30),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   f"{self._results_count} Songs Found")
        # Helper line
        p.setPen(QColor(COL_TEXT_SECONDARY)); p.setFont(self._font_helper)
        p.drawText(QRectF(404, 96, 200, 44),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop |
                   Qt.TextFlag.TextWordWrap,
                   f"Click to pick a category · {self._cat_total} available")
        # ⚙ Manage Categories link
        p.setPen(QColor(COL_PURPLE_LT)); p.setFont(self._font_manage)
        p.drawText(QRectF(404, 128, 180, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "⚙  Manage Categories")
        p.end()


# ════════════════════════════════════════════════════════════════════════
# ANALYZE SELECTED TRACK — right panel
# ════════════════════════════════════════════════════════════════════════

class _AnalyzePanel(QWidget):
    """336 × 562 right-side panel. Track meta + 14 hour-cells (00..13)
    rendered visually with empty data + "play history coming soon" hint
    until db.get_track_play_history exists (NIGHT_LOG carry-over)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(336, 562)
        self._track: Optional[dict] = None
        self._font_h = inter(13, QFont.Weight.Black, letter_spacing=-0.1)
        self._font_artist = inter(15, QFont.Weight.Bold, letter_spacing=-0.1)
        self._font_title  = inter(12, QFont.Weight.Medium)
        self._font_meta   = inter(10, QFont.Weight.Medium, letter_spacing=0.2)
        self._font_meta_value = mono(11, bold=True)
        self._font_hour_label = mono(8, bold=False)
        self._font_empty = inter(11, QFont.Weight.Medium)
        self._font_hint  = inter(10, QFont.Weight.Medium, letter_spacing=0.2)

    def set_track(self, track: Optional[dict]) -> None:
        self._track = dict(track) if track else None
        self.update(self.rect())

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        _qfill_card(p, r)
        _draw_top_accent(p, self.width(), COL_PURPLE_MID,
                         COL_PURPLE_MID + "55")
        _qstroke_card(p, r)
        # Header
        p.setPen(QColor(COL_TEXT_PRIMARY)); p.setFont(self._font_h)
        p.drawText(QRectF(15, 15, self.width() - 30, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "Analyze Selected Track")
        if self._track is None:
            self._paint_empty_state(p)
            return
        # Filled state — track meta block
        p.setPen(QColor(COL_TEXT_PRIMARY)); p.setFont(self._font_artist)
        p.drawText(QRectF(15, 50, self.width() - 30, 22),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   str(self._track.get("artist") or "Unknown Artist"))
        p.setPen(QColor(COL_TEXT_SECONDARY)); p.setFont(self._font_title)
        p.drawText(QRectF(15, 74, self.width() - 30, 18),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   str(self._track.get("title") or "—"))
        # Meta key-value pairs
        rows = [
            ("YEAR",    str(self._track.get("year") or "—")),
            ("ALBUM",   str(self._track.get("album") or "—")),
            ("BPM",     str(self._track.get("bpm") or "—")),
            ("RUN TIME", _fmt_duration(self._track.get("duration_ms"))),
        ]
        y = 110
        for label, value in rows:
            p.setPen(QColor(COL_TEXT_DIM)); p.setFont(self._font_meta)
            p.drawText(QRectF(15, y, 80, 20),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       label)
            p.setPen(QColor(COL_TEXT_PRIMARY)); p.setFont(self._font_meta_value)
            p.drawText(QRectF(100, y, self.width() - 115, 20),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       value)
            y += 24
        # Hour cells row (placeholder — empty data)
        self._paint_hour_cells_placeholder(p, y + 24)

    def _paint_empty_state(self, p: QPainter) -> None:
        p.setPen(QColor(COL_TEXT_DIM)); p.setFont(self._font_empty)
        p.drawText(QRectF(20, 0, self.width() - 40, self.height()),
                   Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                   "Please select a track\nto see its info")
        p.end()

    def _paint_hour_cells_placeholder(self, p: QPainter, y0: int) -> None:
        # Date / hour-cells row header
        p.setPen(QColor(COL_TEXT_DIM)); p.setFont(self._font_meta)
        p.drawText(QRectF(15, y0, 200, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "PLAY HISTORY · HOURS 00-13")
        # 14 cells
        cell_w = (self.width() - 30) / 14.0
        cell_y = y0 + 22
        cell_h = 32
        for i in range(14):
            cx = 15 + i * cell_w
            cell = QRectF(cx, cell_y, cell_w - 2, cell_h)
            p.fillRect(cell, _qcolor(COL_TEXT_MUTED, 0.06))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(255, 255, 255, 14)))
            p.drawRoundedRect(cell.adjusted(0.5, 0.5, -0.5, -0.5), 3, 3)
            p.setPen(QColor(COL_TEXT_DIM)); p.setFont(self._font_hour_label)
            p.drawText(cell, Qt.AlignmentFlag.AlignCenter, f"{i:02d}")
        # Hint
        p.setPen(QColor(COL_TEXT_DIM)); p.setFont(self._font_hint)
        p.drawText(QRectF(15, cell_y + cell_h + 8, self.width() - 30, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "Play history — coming soon")
        p.end()


# ════════════════════════════════════════════════════════════════════════
# TRANSPORT BAR (▶ ■ + progress + AutoPlay) + BOTTOM ACTION BAR
# ════════════════════════════════════════════════════════════════════════

class _PlayStopButton(QWidget):
    """34×34 round button. Variants: play (green) / stop (rose)."""

    clicked = pyqtSignal()

    def __init__(self, kind: str, parent=None):
        super().__init__(parent)
        self.setFixedSize(34, 34)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._kind = kind   # "play" | "stop"
        self._enabled = True
        self._font = inter(13, QFont.Weight.Black)

    def set_enabled(self, on: bool) -> None:
        self._enabled = bool(on)
        self.setCursor(Qt.CursorShape.PointingHandCursor if on
                       else Qt.CursorShape.ForbiddenCursor)
        self.update(self.rect())

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if self._enabled and e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        accent = COL_GREEN if self._kind == "play" else COL_ROSE
        if self._enabled:
            grad = QLinearGradient(0, 0, 0, self.height())
            grad.setColorAt(0.0, _qcolor(accent, 0.95))
            dk = COL_GREEN_DK if self._kind == "play" else COL_ROSE_DK
            grad.setColorAt(1.0, _qcolor(dk, 0.95))
            p.setBrush(QBrush(grad))
        else:
            p.setBrush(_qcolor(accent, 0.10))
        p.setPen(QPen(_qcolor(accent, 0.5 if self._enabled else 0.15)))
        p.drawEllipse(QPointF(self.width() / 2, self.height() / 2), 16, 16)
        p.setPen(QColor(COL_TEXT_PRIMARY) if self._enabled
                 else QColor(COL_TEXT_DIM))
        p.setFont(self._font)
        glyph = "▶" if self._kind == "play" else "■"
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, glyph)
        p.end()


class _ProgressSlider(QWidget):
    """360 × 22 progress bar. Click anywhere to seek (emits seek_requested
    with float position 0..1). Drag-to-seek not implemented — phase 2."""

    seek_requested = pyqtSignal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(360, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._progress: float = 0.0   # 0..1
        self._enabled = False
        self._font = mono(9, bold=False)

    def set_enabled(self, on: bool) -> None:
        self._enabled = bool(on)
        self.setCursor(Qt.CursorShape.PointingHandCursor if on
                       else Qt.CursorShape.ArrowCursor)
        self.update(self.rect())

    def set_progress(self, p_frac: float) -> None:
        p_clamped = max(0.0, min(1.0, float(p_frac)))
        if abs(p_clamped - self._progress) < 0.005:
            return
        self._progress = p_clamped
        self.update(self.rect())

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if self._enabled and e.button() == Qt.MouseButton.LeftButton:
            x = e.position().toPoint().x()
            self.seek_requested.emit(max(0.0, min(1.0, x / self.width())))
        super().mousePressEvent(e)

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Track
        track = QRectF(0, 9, self.width(), 4)
        p.fillRect(track, QColor(255, 255, 255, 22))
        # Fill
        if self._progress > 0:
            fill = QRectF(0, 9, self.width() * self._progress, 4)
            grad = QLinearGradient(0, 0, fill.width(), 0)
            grad.setColorAt(0.0, QColor(COL_CYAN))
            grad.setColorAt(1.0, QColor(COL_PURPLE_MID))
            p.fillRect(fill, QBrush(grad))
            # Thumb
            cx = fill.right()
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(COL_CYAN_LT))
            p.drawEllipse(QPointF(cx, 11), 7, 7)
        p.end()


class _AutoPlayToggle(QWidget):
    toggled = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(100, 30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._on = False
        self._font = inter(10, QFont.Weight.Bold, letter_spacing=0.6)

    def is_on(self) -> bool: return self._on

    def set_on(self, on: bool) -> None:
        if on == self._on:
            return
        self._on = bool(on)
        self.update(self.rect())

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._on = not self._on
            self.update(self.rect())
            self.toggled.emit(self._on)
        super().mousePressEvent(e)

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        if self._on:
            grad = QLinearGradient(0, 0, self.width(), 0)
            grad.setColorAt(0.0, _qcolor(COL_PURPLE_MID, 0.95))
            grad.setColorAt(1.0, _qcolor(COL_PURPLE_DEEP, 0.95))
            p.fillRect(r, QBrush(grad))
            p.setPen(QColor(COL_TEXT_PRIMARY))
        else:
            p.fillRect(r, _qcolor(COL_PURPLE_MID, 0.12))
            p.setPen(QColor(COL_PURPLE_LT))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_qcolor(COL_PURPLE_MID, 0.5)))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
        p.setPen(QColor(COL_TEXT_PRIMARY) if self._on
                 else QColor(COL_PURPLE_LT))
        p.setFont(self._font)
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, "AutoPlay")
        p.end()


class _BottomActionBar(QWidget):
    play_clicked    = pyqtSignal()
    stop_clicked    = pyqtSignal()
    seek_requested  = pyqtSignal(float)
    autoplay_toggled = pyqtSignal(bool)
    save_clicked    = pyqtSignal()
    save_exit_clicked = pyqtSignal()
    cancel_clicked  = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(1440, 50)
        self._loaded_total = "00:00:00"
        self._font_loaded = inter(10, QFont.Weight.Bold, letter_spacing=0.6)
        self._font_loaded_val = mono(13, bold=True)

        # Transport widgets
        self._play = _PlayStopButton("play", self)
        self._play.move(208, 8); self._play.clicked.connect(self.play_clicked.emit)
        self._stop = _PlayStopButton("stop", self)
        self._stop.move(248, 8); self._stop.clicked.connect(self.stop_clicked.emit)
        self._slider = _ProgressSlider(self)
        self._slider.move(290, 14)
        self._slider.seek_requested.connect(self.seek_requested.emit)
        self._autoplay = _AutoPlayToggle(self)
        self._autoplay.move(660, 10)
        self._autoplay.toggled.connect(self.autoplay_toggled.emit)

        # Save group on the right
        self._save_exit = _PillButton("✓ Save and Exit", COL_GREEN, 130, self)
        self._save_exit.move(998, 10)
        self._save_exit.clicked.connect(self.save_exit_clicked.emit)
        self._save = _PillButton("✓ Save", COL_PURPLE_MID, 100, self)
        self._save.move(1138, 10)
        self._save.clicked.connect(self.save_clicked.emit)
        self._cancel = _PillButton("Cancel", COL_ROSE, 100, self)
        self._cancel.move(1248, 10)
        self._cancel.clicked.connect(self.cancel_clicked.emit)

    # ── Public API ───────────────────────────────────────────────────────

    def set_loaded_total(self, text: str) -> None:
        if text == self._loaded_total:
            return
        self._loaded_total = text
        self.update(QRect(8, 0, 200, self.height()))

    def set_progress(self, frac: float) -> None:
        self._slider.set_progress(frac)

    def set_transport_enabled(self, on: bool) -> None:
        self._play.set_enabled(on)
        self._stop.set_enabled(on)
        self._slider.set_enabled(on)

    def is_autoplay_on(self) -> bool:
        return self._autoplay.is_on()

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        _qfill_card(p, r)
        _qstroke_card(p, r, radius=10)
        # Loaded Duration label
        p.setPen(QColor(COL_TEXT_DIM)); p.setFont(self._font_loaded)
        p.drawText(QRectF(16, 6, 140, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "LOADED DURATION")
        p.setPen(QColor(COL_AMBER_LT)); p.setFont(self._font_loaded_val)
        p.drawText(QRectF(16, 22, 180, 18),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._loaded_total)
        p.end()


# ════════════════════════════════════════════════════════════════════════
# PLAYLIST EDIT — the screen
# ════════════════════════════════════════════════════════════════════════

class PlaylistEdit(QWidget):
    """Premium-theme Edit Playlist screen.

    Lifecycle:
      - Mounted once in MainWindow with constructor injection
        (db, scheduler, engine, studio).
      - ``load_for_id(playlist_id)`` is called BEFORE setCurrentWidget;
        populates meta + queue from db.
      - On Save/Save Exit: db.update_playlist_draft + db.replace_playlist_songs
        (two atomic calls; failure of second surfaces via QMessageBox).
      - ``set_studio(studio)`` for lazy on-air detection (matches
        Playlists screen 2 pattern).

    Signals:
      screen_requested(str) — 'studio_open' / 'libraries' / 'settings' /
                              'ai_magic' / 'playlists' (Save / Cancel
                              both return here).
      saved(int)            — emitted with the playlist id on successful save.
    """

    screen_requested = pyqtSignal(str)
    saved = pyqtSignal(int)

    FILTER_DEBOUNCE_MS = 200

    def __init__(self, db, scheduler=None, engine=None, studio=None,
                 parent=None):
        super().__init__(parent)
        self._db = db
        self._scheduler = scheduler
        self._engine = engine
        self._studio = studio
        self.setFixedSize(WINDOW_W, WINDOW_H)
        self.setMouseTracking(False)

        # Cached page bg
        bg = QLinearGradient(0, 0, 0, WINDOW_H)
        bg.setColorAt(0.0, QColor(COL_BG_TOP))
        bg.setColorAt(0.5, QColor(COL_BG_MID))
        bg.setColorAt(1.0, QColor(COL_BG_BOT))
        self._bg = bg

        # State
        self._playlist_id: Optional[int] = None
        self._meta: dict = {}
        self._dirty: bool = False
        self._is_loading: bool = False
        self._title_text: str = "Edit Playlist"
        self._categories_cache: list[dict] = []
        self._total_song_count: int = 0
        # Preview channel id (engine)
        self._preview_cid: Optional[int] = None

        # Cached fonts
        self._font_breadcrumb = inter(11, QFont.Weight.Bold, letter_spacing=1.5)
        self._font_title      = inter(36, QFont.Weight.Black, letter_spacing=-1.5)
        self._font_subtitle   = inter(14, QFont.Weight.Medium, letter_spacing=-0.1)

        # Header
        self._header = Header(self)
        self._header.move(0, 0)
        self._header.libraries_clicked.connect(
            lambda: self._cancel_then_route("libraries"))
        self._header.settings_clicked.connect(
            lambda: self._cancel_then_route("settings"))
        self._header.ai_magic_clicked.connect(
            lambda: self._cancel_then_route("ai_magic"))
        self._header.studio_open_clicked.connect(
            lambda: self._cancel_then_route("studio_open"))

        # Top toolbar
        self._toolbar = _TopToolbar(self)
        self._toolbar.move(56, 226)
        self._toolbar.preview_clicked.connect(self._on_preview_track)
        self._toolbar.preview_breaks_clicked.connect(self._on_preview_breaks)
        self._toolbar.search_clicked.connect(self._on_inline_search)
        self._toolbar.mic_clicked.connect(self._on_mic_clicked)
        self._toolbar.tab_clicked.connect(self._on_tab_clicked)

        # Preview slot column
        self._preview_slot = _PreviewSlot(self)
        self._preview_slot.move(56, 290)

        # Element icon row
        self._icon_row = _ElementIconRow(self)
        self._icon_row.move(212, 290)
        self._icon_row.type_changed.connect(self._on_type_changed)
        self._icon_row.placeholder_clicked.connect(self._on_decorative_icon)

        # Action stack
        self._actions = _ActionStack(self)
        self._actions.move(212, 362)
        self._actions.add_clicked.connect(self._on_add)
        self._actions.insert_clicked.connect(self._on_insert)
        self._actions.replace_clicked.connect(self._on_replace)
        self._actions.prepair_clicked.connect(self._on_prepair)
        self._actions.delete_clicked.connect(self._on_delete)

        # Playlist queue model + table
        self._model = _QueueModel(self)
        self._model.queue_changed.connect(self._on_queue_changed)
        self._table_card = _PlaylistTableCard(self._model, self)
        self._table_card.move(300, 362)
        self._table_card.selection_changed.connect(self._on_row_selected)

        # Filter panel
        self._filter = _FilterPanel(self)
        self._filter.move(300, 678)
        self._filter.filter_changed.connect(self._on_filter_changed)
        self._filter.search_clicked.connect(self._refresh_filter_results)
        self._filter.reset_clicked.connect(self._refresh_filter_results)

        # Analyze panel
        self._analyze = _AnalyzePanel(self)
        self._analyze.move(1048, 290)

        # Bottom action bar
        self._bottom = _BottomActionBar(self)
        self._bottom.move(0, 850)
        self._bottom.play_clicked.connect(self._on_transport_play)
        self._bottom.stop_clicked.connect(self._on_transport_stop)
        self._bottom.seek_requested.connect(self._on_seek_requested)
        self._bottom.save_clicked.connect(self._on_save)
        self._bottom.save_exit_clicked.connect(self._on_save_exit)
        self._bottom.cancel_clicked.connect(self._on_cancel)
        self._bottom.set_transport_enabled(False)

        # Engine signal subscriptions
        if self._engine is not None:
            self._engine.position_changed.connect(self._on_engine_position)
            self._engine.playback_ended.connect(self._on_engine_playback_ended)
            self._engine.error_occurred.connect(self._on_engine_error)

        # Filter debounce timer
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(self.FILTER_DEBOUNCE_MS)
        self._filter_timer.timeout.connect(self._refresh_filter_results)

        # 1Hz tick for header time
        self._tick = QTimer(self)
        self._tick.setInterval(1000); self._tick.timeout.connect(self._on_tick)
        self._tick.start(); self._on_tick()

        log.info("PlaylistEdit ready (Figma 248:2 — Premium Dark)")

    # ── External wiring helpers ──────────────────────────────────────────

    def set_studio(self, studio) -> None:
        self._studio = studio

    # ── Lifecycle / loader ───────────────────────────────────────────────

    def load_for_id(self, playlist_id: int) -> None:
        """Load a playlist for editing. Called by MainWindow before
        setCurrentWidget."""
        self._is_loading = True
        self._dirty = False
        self._playlist_id = int(playlist_id)
        # Reload categories cache
        try:
            cats = list(self._db.get_categories())
            self._categories_cache = [
                {"id": int(c["id"]), "name": c["name"],
                 "color": c["color"] if "color" in c.keys() else None,
                 "song_count": int(c["song_count"] or 0)
                 if "song_count" in c.keys() else 0}
                for c in cats]
            total = self._db._conn().execute(
                "SELECT COUNT(*) FROM songs WHERE is_enabled=1"
            ).fetchone()
            self._total_song_count = int(total[0] or 0) if total else 0
        except Exception as exc:
            log.warning(f"load categories failed: {exc}")
            self._categories_cache = []
            self._total_song_count = 0
        self._filter.set_categories(self._categories_cache,
                                    self._total_song_count)
        # Load meta
        try:
            row = self._db.get_playlist(int(playlist_id))
        except Exception as exc:
            log.warning(f"get_playlist({playlist_id}) failed: {exc}")
            row = None
        if row is None:
            dialogs.warning(self, "Playlist not found",
                                f"Could not load playlist id={playlist_id}.")
            self._is_loading = False
            self.screen_requested.emit("playlists")
            return
        self._meta = {
            "name":   str(row["name"] or "Untitled"),
            "kind":   str(row["kind"] if "kind" in row.keys() and row["kind"]
                          else "manual"),
            "color":  str(row["color"] if "color" in row.keys() and row["color"]
                          else COL_CYAN),
            "tags":   str(row["tags"] if "tags" in row.keys() and row["tags"]
                          else ""),
        }
        self._title_text = self._meta["name"]
        # Load tracks
        try:
            tracks = list(self._db.get_playlist_songs(int(playlist_id)))
        except Exception as exc:
            log.warning(f"get_playlist_songs({playlist_id}) failed: {exc}")
            tracks = []
        self._model.replace_all(tracks)
        # Sync UI
        self._refresh_filter_results()
        self._refresh_action_states()
        self._update_loaded_duration()
        self._is_loading = False
        self.update(self.rect())

    # ── Filter pipeline ──────────────────────────────────────────────────

    def _on_filter_changed(self) -> None:
        self._filter_timer.start()

    def _refresh_filter_results(self) -> None:
        try:
            count = int(self._db.count_songs(
                query=self._filter.search_text() or None,
                category_id=self._filter.category_id(),
            ))
        except Exception as exc:
            log.warning(f"count_songs failed: {exc}")
            count = 0
        self._filter.set_results_count(count)
        self._refresh_action_states()

    # ── Element CRUD ────────────────────────────────────────────────────

    def _first_filter_match(self) -> Optional[dict]:
        """Return the first song row matching current filter, or None."""
        try:
            rows = self._db.search_songs(
                query=self._filter.search_text() or None,
                category_id=self._filter.category_id(),
                sort="recent",
                offset=0, limit=1,
            )
        except Exception as exc:
            log.warning(f"search_songs failed: {exc}")
            return None
        if not rows:
            return None
        r = rows[0]
        return {
            "id":          int(r["id"]),
            "artist":      r["artist"],
            "title":       r["title"],
            "duration_ms": int(r["duration_ms"] or 0),
            "file_path":   r["file_path"],
            "year":        r["year"] if "year" in r.keys() else None,
            "bpm":         r["bpm"]  if "bpm"  in r.keys() else None,
            "album":       r["album"] if "album" in r.keys() else None,
            "category_id": r["category_id"] if "category_id" in r.keys() else None,
        }

    def _on_add(self) -> None:
        track = self._first_filter_match()
        if track is None:
            dialogs.info(
                self, "Nothing to add",
                "No songs match the current filter.")
            return
        new_idx = self._model.append(track)
        self._table_card.table().setCurrentIndex(self._model.index(new_idx, 0))
        self._mark_dirty()

    def _on_insert(self) -> None:
        sel = self._table_card.table().selected_row()
        if sel is None:
            return
        track = self._first_filter_match()
        if track is None:
            dialogs.info(self, "Nothing to insert",
                                    "No songs match the current filter.")
            return
        self._model.insert_at(sel, track)
        self._table_card.table().setCurrentIndex(self._model.index(sel, 0))
        self._mark_dirty()

    def _on_replace(self) -> None:
        sel = self._table_card.table().selected_row()
        if sel is None:
            return
        track = self._first_filter_match()
        if track is None:
            dialogs.info(self, "Nothing to replace with",
                                    "No songs match the current filter.")
            return
        self._model.replace_at(sel, track)
        self._mark_dirty()

    def _on_delete(self) -> None:
        sel = self._table_card.table().selected_row()
        if sel is None:
            return
        self._model.remove_at(sel)
        self._mark_dirty()

    def _on_prepair(self) -> None:
        dialogs.info(
            self, "PREPAIR — voice track",
            "Voice-track prep — coming soon.")

    def _on_queue_changed(self) -> None:
        self._mark_dirty()
        self._update_loaded_duration()
        self._refresh_action_states()

    def _on_row_selected(self, row: int) -> None:
        self._refresh_action_states()
        if row < 0 or row >= self._model.rowCount():
            self._preview_slot.set_track(None)
            self._analyze.set_track(None)
            return
        track = self._model.all_rows()[row]
        self._preview_slot.set_track(track)
        self._analyze.set_track(track)

    def _on_type_changed(self, _key: str) -> None:
        # v1: type icon does not yet wire to a separate library — Frame
        # 9 only filters via category + search. Leaving as a no-op so
        # the icon-row visual feedback works without surprising the user.
        pass

    def _on_decorative_icon(self, key: str) -> None:
        dialogs.info(
            self, "Coming soon",
            f"'{ELEMENT_ICONS.get(key, key)}' — coming soon.")

    # ── Toolbar actions ──────────────────────────────────────────────────

    def _on_preview_track(self) -> None:
        sel = self._table_card.table().selected_row()
        if sel is None or sel >= self._model.rowCount():
            dialogs.info(self, "Preview",
                                    "Select a track in the queue first.")
            return
        track = self._model.all_rows()[sel]
        self._start_preview(track)

    def _start_preview(self, track: dict) -> None:
        if self._engine is None:
            dialogs.info(
                self, "Preview unavailable",
                "AudioEngine reference not wired into Edit Playlist.")
            return
        # On-air protection — confirm if Studio is on-air
        if (self._studio is not None
                and getattr(self._studio, "_current_track", None) is not None):
            if not dialogs.confirm(
                    self, "Preview while on air?",
                    "Studio is currently on air.\n\n"
                    "Preview will not affect the on-air output, but "
                    "make sure you're routing preview to monitors.",
                    yes_label="Preview Anyway"):
                return
        path = track.get("file_path")
        if not path:
            dialogs.info(self, "Preview",
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
            self._bottom.set_transport_enabled(True)
            log.info(f"[playlist_edit] preview ch={cid} "
                     f"track={track.get('title')!r}")
        except Exception as exc:
            log.warning(f"preview load_file failed: {exc}")
            dialogs.warning(self, "Preview failed", str(exc))

    def _on_preview_breaks(self) -> None:
        dialogs.info(
            self, "Preview Breaks",
            "Preview Breaks — coming soon.\n\nWill auto-play the "
            "current campaign break in context.")

    def _on_inline_search(self) -> None:
        # Focus the search input in the Filter Panel
        self._filter._search.setFocus(Qt.FocusReason.OtherFocusReason)
        self._filter._search.selectAll()

    def _on_mic_clicked(self) -> None:
        dialogs.info(
            self, "Mic recording",
            "Voice-track mic recording — coming soon.")

    def _on_tab_clicked(self, key: str) -> None:
        if key == "edit":
            return    # already on this tab
        labels = {"memos": "Memos", "schedule": "Schedule & Details",
                  "export": "Export Playlist"}
        dialogs.info(
            self, labels.get(key, "Tab"),
            f"{labels.get(key, key)} — coming soon. Edit Playlist active.")

    # ── Transport bar handlers ──────────────────────────────────────────

    def _on_transport_play(self) -> None:
        # If we already have a preview channel, resume; else start fresh
        if (self._engine is not None and self._preview_cid is not None):
            try:
                if self._engine.get_state(self._preview_cid) == "paused":
                    self._engine.resume(self._preview_cid); return
            except Exception:
                pass
        # Fallback — start new preview from selected row
        self._on_preview_track()

    def _on_transport_stop(self) -> None:
        if self._engine is None or self._preview_cid is None:
            return
        try:
            self._engine.cleanup(self._preview_cid)
        except Exception as exc:
            log.warning(f"stop preview cleanup failed: {exc}")
        self._preview_cid = None
        self._bottom.set_progress(0.0)
        self._bottom.set_transport_enabled(False)

    def _on_seek_requested(self, frac: float) -> None:
        if (self._engine is None or self._preview_cid is None):
            return
        dur = self._engine.get_duration_ms(self._preview_cid) or 0
        if dur <= 0:
            return
        target_ms = int(dur * frac)
        try:
            self._engine.seek_to_ms(self._preview_cid, target_ms)
        except Exception as exc:
            log.warning(f"seek_to_ms failed: {exc}")

    # ── Engine signal handlers ──────────────────────────────────────────

    def _on_engine_position(self, channel_id: int, position_ms: int) -> None:
        if channel_id != self._preview_cid:
            return
        dur = self._engine.get_duration_ms(channel_id) or 0
        if dur <= 0:
            return
        self._bottom.set_progress(position_ms / dur)

    def _on_engine_playback_ended(self, channel_id: int) -> None:
        if channel_id != self._preview_cid:
            return
        self._preview_cid = None
        self._bottom.set_progress(0.0)
        self._bottom.set_transport_enabled(False)
        # AutoPlay — advance to next queue track
        if self._bottom.is_autoplay_on():
            sel = self._table_card.table().selected_row()
            if sel is None:
                return
            next_row = sel + 1
            if next_row < self._model.rowCount():
                self._table_card.table().setCurrentIndex(
                    self._model.index(next_row, 0))
                track = self._model.all_rows()[next_row]
                self._start_preview(track)

    def _on_engine_error(self, channel_id: int, msg: str) -> None:
        if channel_id != self._preview_cid:
            return
        log.warning(f"[playlist_edit] engine error: {msg}")

    # ── Save / Cancel ────────────────────────────────────────────────────

    def _validate_for_save(self) -> Optional[str]:
        if not (self._meta.get("name") or "").strip():
            return "Playlist name cannot be empty."
        if self._model.rowCount() == 0:
            return "Playlist must have at least one track."
        return None

    def _save(self) -> bool:
        """Two-step atomic save (meta then tracks). Returns True on
        full success, False on any failure (failure surfaced via
        QMessageBox per the clock-save-bug lesson)."""
        if self._playlist_id is None:
            return False
        # Step 1 — meta
        try:
            self._db.update_playlist_draft(
                int(self._playlist_id),
                name=self._meta.get("name"),
                kind=self._meta.get("kind") or "manual",
                color=self._meta.get("color"),
                tags=self._meta.get("tags") or "",
            )
        except Exception as exc:
            log.warning(f"update_playlist_draft failed: {exc}")
            dialogs.warning(
                self, "Save failed",
                f"Could not save playlist meta:\n{exc}")
            return False
        # Step 2 — tracks
        try:
            self._db.replace_playlist_songs(
                int(self._playlist_id), self._model.song_ids())
        except Exception as exc:
            log.warning(f"replace_playlist_songs failed: {exc}")
            dialogs.warning(
                self, "Save partially failed",
                f"Meta saved, but track list save failed:\n{exc}\n\n"
                "Click Save again to retry the track list.")
            return False
        log.info(f"[playlist_edit] saved playlist id={self._playlist_id} "
                 f"tracks={self._model.rowCount()}")
        return True

    def _on_save(self) -> None:
        err = self._validate_for_save()
        if err:
            dialogs.warning(self, "Cannot save", err); return
        if self._save():
            self._dirty = False
            self.saved.emit(int(self._playlist_id))
            dialogs.info(self, "Saved",
                                    "Playlist saved successfully.")

    def _on_save_exit(self) -> None:
        err = self._validate_for_save()
        if err:
            dialogs.warning(self, "Cannot save", err); return
        if self._save():
            self._dirty = False
            self.saved.emit(int(self._playlist_id))
            self.screen_requested.emit("playlists")

    def _on_cancel(self) -> None:
        self._cancel_then_route("playlists")

    def _cancel_then_route(self, route: str) -> None:
        if self._dirty:
            if not dialogs.confirm(
                    self, "Discard changes?",
                    "You have unsaved changes. Discard and leave "
                    "the editor?",
                    danger=True, yes_label="Discard"):
                return
        # Stop any active preview before leaving
        self._on_transport_stop()
        self._dirty = False
        self.screen_requested.emit(route)

    # ── State helpers ───────────────────────────────────────────────────

    def _mark_dirty(self) -> None:
        if self._is_loading:
            return
        if not self._dirty:
            self._dirty = True

    def _refresh_action_states(self) -> None:
        sel = self._table_card.table().selected_row()
        has_sel = sel is not None and sel >= 0
        # ADD: enabled when filter resolves to ≥1 track
        try:
            count = self._filter._results_count
        except Exception:
            count = 0
        self._actions.set_states(add_on=(count > 0), has_selection=has_sel)

    def _update_loaded_duration(self) -> None:
        rows = self._model.all_rows()
        # Each row carries duration_ms — convert to total HH:MM:SS
        total_ms = sum(int(r.get("duration_ms") or 0) for r in rows)
        s = total_ms // 1000
        h, rem = divmod(s, 3600)
        m, ss = divmod(rem, 60)
        self._bottom.set_loaded_total(f"{h:02d}:{m:02d}:{ss:02d}")

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
        p.fillRect(QRectF(0, 0, self.width(), self.height()), QBrush(self._bg))
        # Title block
        p.setPen(QColor(COL_TEXT_DIM)); p.setFont(self._font_breadcrumb)
        p.drawText(QRectF(56, 116, 600, 13),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "SCHEDULING  /  PLAYLISTS  /  EDIT")
        p.setPen(QColor(COL_TEXT_PRIMARY)); p.setFont(self._font_title)
        p.drawText(QRectF(56, 138, 900, 50),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._title_text)
        p.setPen(QColor(COL_TEXT_SECONDARY)); p.setFont(self._font_subtitle)
        p.drawText(QRectF(56, 188, 900, 17),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "Edit playlist tracks, preview, reorder, and save")
        p.end()
