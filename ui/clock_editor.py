"""
RadioAI Studio Pro — Clock Editor (Figma 285:2 — Premium Dark).

Frame 11. Greenfield. Full-screen route mounted on MainWindow's stack.

Routes (set via `load_for_mode` before show):
  - "new"        → blank create mode; defaults to name="New Clock", color=Rose
  - "edit"       → load via db.get_clock(id) + db.get_clock_slots(id)
  - "duplicate"  → load source as edit, prefix name "Copy of ", treat as create
                   on save (no id reuse)

Storage / wiring contract
-------------------------
- Top-level meta saved via ``db.save_clock(id, dict)`` — partial UPDATE for
  any of {name, comments, color, backup_song_filter, loop_cycle_enabled,
  show_only_descriptions} that already exist (idempotent ALTER guarantees
  the cols are present).
- Slots saved via ``db.save_clock_slots(id, list[dict])`` — atomic
  DELETE+INSERT replace inside one transaction. The screen mutates an
  in-memory list (ADD/INSERT/REPLACE/DELETE) and only writes on OK.
- Filter resolution + count via ``scheduler._songs_matching_filter_json``
  — scheduler engine is the canonical place for filter→songs SQL. The
  underscore-method is documented as the implementation behind the public
  ``count_songs_matching_filter``; we call it directly here so we can
  compute *both* count + avg duration from one pass without re-querying.

Layout (1440 × 900) — exact Figma 285:2 coords
-------------------------------------------
  HEADER     1440 ×  88
  Title block @ y=116..220 (breadcrumb / "Create New Clock" / subtitle)
  Meta strip @ y=230, 1328 × 76
  LEFT  (Available Clock Elements)  56,320 → 432 × 540
  CENTER-TOP (Filter Results)       504,320 → 180 × 220
  CENTER-BOT (Action Stack)         504,552 → 80 × 332
  RIGHT (Clock Editor card)         704,320 → 680 × 564
  Action bar:  OK 1156,836 (120×44) · Cancel 1284,836 (110×44)

═══════════════════════════════════════════════════════════════════════════
PERFORMANCE INVARIANTS — DO NOT VIOLATE
═══════════════════════════════════════════════════════════════════════════
  1. event.rect() clipping in every paintEvent (clock face + filter
     dropdowns are the hot paths).
  2. Clock face is a single custom-paint widget with cached QPainterPath
     per arc segment. No child widgets per segment.
  3. mouseMoveEvent — clock face uses click-only (no drag-reorder in v1),
     so no setMouseTracking needed.
  4. No DB calls in paintEvent — all data preloaded.
  5. No self.update() inside paintEvent.
  6. Cached QGradient / QColor / QFont per element-type-color in __init__.
  7. Drop shadows via QGraphicsDropShadowEffect.
  8. Filter dropdown changes: 200ms debounce timer (single-shot pattern
     from playlist_new.py).
═══════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import json
import logging
import math
from typing import Optional, Literal
from core import dialogs

from PyQt6.QtCore import (
    Qt, QRect, QRectF, QPoint, QPointF, QSize, QTimer, pyqtSignal, QEvent,
)
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QLinearGradient, QRadialGradient,
    QFont, QMouseEvent, QKeyEvent, QPaintEvent, QPainterPath, QFocusEvent,
)
from PyQt6.QtWidgets import (
    QWidget, QMessageBox, QGraphicsDropShadowEffect, QLineEdit,
    QMenu, QApplication, QStyledItemDelegate, QFrame,
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
from ui.widgets.clock_face import (
    ClockFaceWidget,
    ELEMENT_TYPE_COLORS as _CLOCK_FACE_TYPE_COLORS,
    DEFAULT_DURATION_S as _CLOCK_FACE_DEFAULT_DURATION_S,
    DEFAULT_COLORIZE_BY as _CLOCK_FACE_DEFAULT_COLORIZE_BY,
)

log = logging.getLogger("ClockEditor")

WINDOW_H = 900

# ── Modes ────────────────────────────────────────────────────────────────

MODE_NEW       = "new"
MODE_EDIT      = "edit"
MODE_DUPLICATE = "duplicate"
Mode = Literal["new", "edit", "duplicate"]

# ── Element types — UI key ↔ DB slot_type mapping ────────────────────────

# Order matters — drives the Figma type-icon row left-to-right
ELEMENT_TYPES: list[str] = ["song", "jingle", "spot", "voice", "sweeper"]
ELEMENT_TYPE_LABELS = {
    "song": "Song",      "jingle": "Jingle",  "spot": "Spot",
    "voice": "Voice",    "sweeper": "Sweeper",
}
ELEMENT_TYPE_ICONS = {
    "song": "♪",   "jingle": "🔔", "spot": "$",
    "voice": "🎤", "sweeper": "★",
}
# Re-export from clock_face — single source of truth lives with the widget.
ELEMENT_TYPE_COLORS = _CLOCK_FACE_TYPE_COLORS
# UI → DB slot_type
ELEMENT_TYPE_TO_DB = {
    "song":    "song",
    "jingle":  "jingle",
    "spot":    "break",       # SchedulerEngine accepts "break" (legacy "spot" alias)
    "voice":   "voice_track",
    "sweeper": "sweeper",
}
# DB → UI element_type (handles legacy "spot" too)
DB_TO_ELEMENT_TYPE = {
    "song":        "song",
    "jingle":      "jingle",
    "break":       "spot",
    "spot":        "spot",
    "voice_track": "voice",
    "sweeper":     "sweeper",
    "station_id":  "jingle",  # internally distinct but UI groups w/ jingles
}

# Re-export from clock_face — single source of truth lives with the widget.
DEFAULT_DURATION_S = _CLOCK_FACE_DEFAULT_DURATION_S

# ── Clock color swatches (meta strip) ────────────────────────────────────

CLOCK_COLOR_OPTIONS: list[tuple[str, str]] = [
    ("Rose",   COL_ROSE),
    ("Cyan",   COL_CYAN),
    ("Purple", COL_PURPLE_MID),
    ("Green",  COL_GREEN),
    ("Amber",  COL_AMBER),
    ("Pink",   COL_PINK),
]
DEFAULT_CLOCK_COLOR = COL_ROSE

# ── Filter axis option lists (decorative axes are no-op) ─────────────────

# The DB-backed axes; "(All)" is the wildcard / no-op.
ERA_OPTIONS         = ["(All)", "60s", "70s", "80s", "90s", "2000s", "2010s", "2020s"]
VOCAL_OPTIONS       = ["(All)", "vocal", "instrumental"]
YEAR_OPTIONS        = ["(All)"] + [str(y) for y in range(1960, 2031, 5)]
PRIORITY_OPTIONS    = ["(All)"] + [str(i) for i in range(1, 10)]   # 1..9
BPM_OPTIONS         = ["(All)"] + [str(b) for b in range(60, 201, 10)]

# Decorative — no song schema field, render-only. Flagged in NIGHT_LOG.
SOUND_CODE_OPTIONS  = ["(All)"]
POPULARITY_OPTIONS  = ["(All)"]
PROPERTIES_OPTIONS  = ["(All)"]

# ── Settings keys ────────────────────────────────────────────────────────

SETTINGS_KEY_COLORIZE_BY = "clock_editor.colorize_by"
# Re-export from clock_face — same default lives with the widget.
DEFAULT_COLORIZE_BY = _CLOCK_FACE_DEFAULT_COLORIZE_BY

# ── Common painter helpers ───────────────────────────────────────────────


def _qfill_card(p: QPainter, rect: QRectF) -> None:
    """Standard premium card surface gradient."""
    bg = QLinearGradient(0, 0, 0, rect.height())
    bg.setColorAt(0.0, QColor(14, 16, 32, 242))
    bg.setColorAt(1.0, QColor(7, 9, 18, 242))
    p.fillRect(rect, QBrush(bg))


def _qstroke_card(p: QPainter, rect: QRectF, radius: float = 12.0) -> None:
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(QColor(255, 255, 255, 18)))
    p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)


def _draw_top_accent(p: QPainter, w: int, color_a: str, color_b: Optional[str] = None,
                     mid: Optional[str] = None) -> None:
    """3px horizontal gradient strip used for card top accents."""
    grad = QLinearGradient(0, 0, w, 0)
    grad.setColorAt(0.0, QColor(color_a))
    if mid:
        grad.setColorAt(0.5, QColor(mid))
    grad.setColorAt(1.0, QColor(color_b or color_a))
    p.fillRect(QRectF(0, 0, w, 3), QBrush(grad))


# ════════════════════════════════════════════════════════════════════════
# CLOCK FACE — moved to ui/widgets/clock_face.py for reuse + smaller file
# Imported as ``ClockFaceWidget`` at the top of this module.
# ════════════════════════════════════════════════════════════════════════


# ════════════════════════════════════════════════════════════════════════
# META STRIP — name / comments / color / backup filter
# ════════════════════════════════════════════════════════════════════════

class _MetaStrip(QWidget):
    """The 1328 × 76 strip with the four meta fields."""

    name_changed   = pyqtSignal(str)
    comments_changed = pyqtSignal(str)
    color_changed  = pyqtSignal(str)   # emits hex like "#06b6d4"
    backup_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(1328, 76)

        self._color_hex = DEFAULT_CLOCK_COLOR

        self._font_label = inter(9, QFont.Weight.Bold, letter_spacing=1.2)
        self._font_value = inter(12, QFont.Weight.Bold, letter_spacing=-0.05)
        self._font_track = inter(10, QFont.Weight.Black, letter_spacing=0.8)
        self._font_filter = inter(11, QFont.Weight.Medium)

        # CLOCK NAME — QLineEdit at (15, 27, 220x36)
        self._name_edit = QLineEdit("New Clock", self)
        self._name_edit.setGeometry(15, 27, 220, 36)
        self._name_edit.setFont(inter(14, QFont.Weight.Bold, letter_spacing=-0.2))
        self._name_edit.setStyleSheet(
            "QLineEdit { background: rgba(7,8,16,0.7); "
            "border: 1px solid rgba(6,182,212,0.4); border-radius: 8px; "
            f"color: {COL_TEXT_PRIMARY}; padding: 0 11px; }} "
            "QLineEdit:focus { border-color: rgba(6,182,212,0.85); }"
        )
        self._name_edit.textChanged.connect(self.name_changed.emit)

        # COMMENTS — QLineEdit at (251, 27, 560x36)
        self._comments_edit = QLineEdit(self)
        self._comments_edit.setGeometry(251, 27, 560, 36)
        self._comments_edit.setPlaceholderText("Add notes about this clock…")
        self._comments_edit.setFont(inter(12, QFont.Weight.Medium))
        self._comments_edit.setStyleSheet(
            "QLineEdit { background: rgba(7,8,16,0.7); "
            "border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; "
            f"color: {COL_TEXT_PRIMARY}; padding: 0 11px; }} "
            f"QLineEdit::placeholder {{ color: {COL_TEXT_DIM}; }} "
            "QLineEdit:focus { border-color: rgba(6,182,212,0.45); }"
        )
        self._comments_edit.textChanged.connect(self.comments_changed.emit)

        # COLOR dropdown — custom paint at (827, 27, 180x36)
        self._color_btn = _ColorDropdownButton(self._color_hex, self)
        self._color_btn.move(827, 27)
        self._color_btn.color_picked.connect(self._on_color_picked)

        # BACKUP SONG FILTER — at (1023, 27, 288x36)
        self._backup_btn = _BackupFilterButton(self)
        self._backup_btn.move(1023, 27)
        self._backup_btn.dots_clicked.connect(self.backup_clicked.emit)

    # ── Public API ───────────────────────────────────────────────────────

    def set_name(self, name: str) -> None:
        if self._name_edit.text() != name:
            self._name_edit.setText(name or "")

    def name(self) -> str:
        return self._name_edit.text().strip()

    def set_comments(self, txt: str) -> None:
        if self._comments_edit.text() != (txt or ""):
            self._comments_edit.setText(txt or "")

    def comments(self) -> str:
        return self._comments_edit.text().strip()

    def set_color(self, hex_color: str) -> None:
        if hex_color == self._color_hex:
            return
        self._color_hex = hex_color or DEFAULT_CLOCK_COLOR
        self._color_btn.set_color(self._color_hex)

    def color(self) -> str:
        return self._color_hex

    def _on_color_picked(self, hex_color: str) -> None:
        self._color_hex = hex_color
        self.color_changed.emit(hex_color)

    def focus_name(self) -> None:
        self._name_edit.setFocus(Qt.FocusReason.OtherFocusReason)
        self._name_edit.selectAll()

    # ── Paint ────────────────────────────────────────────────────────────

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        _qfill_card(p, r)
        _draw_top_accent(p, self.width(),
                         COL_CYAN, COL_PINK, mid=COL_PURPLE_MID)
        _qstroke_card(p, r)

        # Labels
        p.setPen(QColor(COL_TEXT_DIM)); p.setFont(self._font_label)
        for x, txt in [(15, "CLOCK NAME"), (251, "COMMENTS"),
                       (827, "COLOR"), (1023, "BACKUP SONG FILTER")]:
            p.drawText(QRectF(x, 11, 240, 11),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       txt)
        p.end()


class _ColorDropdownButton(QWidget):
    """180×36 button: swatch + label + chevron, opens popup with 6 colors."""

    color_picked = pyqtSignal(str)   # hex

    def __init__(self, initial_hex: str, parent=None):
        super().__init__(parent)
        self.setFixedSize(180, 36)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hex = initial_hex
        self._font = inter(12, QFont.Weight.Bold, letter_spacing=-0.05)
        self._font_chev = inter(9, QFont.Weight.Bold)

    def set_color(self, hex_color: str) -> None:
        if hex_color == self._hex:
            return
        self._hex = hex_color
        self.update(self.rect())

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._open_menu()
        super().mousePressEvent(e)

    def _open_menu(self) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(_MENU_QSS)
        for label, hex_c in CLOCK_COLOR_OPTIONS:
            act = menu.addAction(f"  ●  {label}")
            act.setData(hex_c)
        chosen = menu.exec(self.mapToGlobal(QPoint(0, self.height())))
        if chosen is None:
            return
        new_hex = chosen.data()
        if isinstance(new_hex, str):
            self._hex = new_hex
            self.update(self.rect())
            self.color_picked.emit(new_hex)

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        p.fillRect(r, QColor(7, 8, 16, 178))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 22)))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        # Swatch
        p.setBrush(QColor(self._hex))
        p.setPen(QPen(QColor(255, 255, 255, 50)))
        p.drawRoundedRect(QRectF(7, 7, 20, 20), 4, 4)
        # Label (color name lookup)
        name = next(
            (n for n, h in CLOCK_COLOR_OPTIONS if h == self._hex), "Custom")
        p.setPen(_qcolor(self._hex, 0.95))
        p.setFont(self._font)
        p.drawText(QRectF(35, 0, self.width() - 60, self.height()),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   name)
        # Chevron
        p.setPen(QColor(COL_TEXT_DIM)); p.setFont(self._font_chev)
        p.drawText(QRectF(self.width() - 22, 0, 16, self.height()),
                   Qt.AlignmentFlag.AlignCenter, "▾")
        p.end()


class _BackupFilterButton(QWidget):
    """288×36 backup-filter pill. ··· menu emits ``dots_clicked``."""

    dots_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(288, 36)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._font_track = inter(10, QFont.Weight.Black, letter_spacing=0.8)
        self._font_note  = inter(11, QFont.Weight.Medium)
        self._font_dots  = inter(13, QFont.Weight.Bold)

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            # Hit-test the ··· region (right edge)
            if e.position().toPoint().x() > self.width() - 30:
                self.dots_clicked.emit()
        super().mousePressEvent(e)

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        p.fillRect(r, QColor(7, 8, 16, 178))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 22)))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        # TRACK pill (amber gradient)
        pill = QRectF(7, 6, 48, 22)
        grad = QLinearGradient(pill.topLeft(), pill.topRight())
        grad.setColorAt(0.0, _qcolor(COL_AMBER, 0.95))
        grad.setColorAt(1.0, _qcolor(COL_AMBER_DK, 0.95))
        p.fillRect(pill, QBrush(grad))
        p.setPen(QColor(0, 0, 0)); p.setFont(self._font_track)
        p.drawText(pill, Qt.AlignmentFlag.AlignCenter, "TRACK")
        # ♪ + label
        p.setPen(QColor(COL_PURPLE_LT))
        p.setFont(inter(12, QFont.Weight.Bold))
        p.drawText(QRectF(63, 8, 14, 20),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "♪")
        p.setPen(QColor(COL_TEXT_PRIMARY)); p.setFont(self._font_note)
        p.drawText(QRectF(79, 0, 180, self.height()),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "Random song · No Filter")
        # ··· menu indicator
        p.setPen(QColor(COL_TEXT_DIM)); p.setFont(self._font_dots)
        p.drawText(QRectF(self.width() - 30, 0, 24, self.height()),
                   Qt.AlignmentFlag.AlignCenter, "···")
        p.end()


# Common QMenu styling used by all dropdowns
_MENU_QSS = (
    "QMenu { background: #0e1020; border: 1px solid rgba(255,255,255,0.1); "
    "border-radius: 8px; padding: 4px; color: #f1f5ff; }"
    "QMenu::item { padding: 6px 16px; border-radius: 4px; "
    "font-family: Inter; font-size: 12px; }"
    "QMenu::item:selected { background: rgba(6,182,212,0.18); color: #22d3ee; }"
    "QMenu::separator { height: 1px; background: rgba(255,255,255,0.06); "
    "margin: 4px 8px; }"
)


# ════════════════════════════════════════════════════════════════════════
# AVAILABLE CLOCK ELEMENTS — left card (432 × 540)
# ════════════════════════════════════════════════════════════════════════

class _TypeIconTile(QWidget):
    """76 × 44 tile for one element type. Click → ``clicked(type_key)``."""

    clicked = pyqtSignal(str)

    def __init__(self, type_key: str, parent=None):
        super().__init__(parent)
        self.setFixedSize(76, 44)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._type_key = type_key
        self._active = False
        self._color = ELEMENT_TYPE_COLORS[type_key]
        self._icon  = ELEMENT_TYPE_ICONS[type_key]
        self._font  = inter(22, QFont.Weight.Black)

    def set_active(self, on: bool) -> None:
        if on == self._active:
            return
        self._active = bool(on)
        self.update(self.rect())

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._type_key)
        super().mousePressEvent(e)

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        if self._active:
            grad = QLinearGradient(0, 0, self.width(), 0)
            grad.setColorAt(0.0, _qcolor(self._color, 0.28))
            grad.setColorAt(1.0, _qcolor(self._color, 0.10))
            p.fillRect(r, QBrush(grad))
            p.setPen(QPen(_qcolor(self._color, 0.55))); p.setBrush(Qt.BrushStyle.NoBrush)
        else:
            p.fillRect(r, QColor(7, 8, 16, 153))
            p.setPen(QPen(QColor(255, 255, 255, 22))); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        # Icon
        p.setPen(QColor(self._color)); p.setFont(self._font)
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, self._icon)
        p.end()


class _SubTab(QWidget):
    """One of three sub-tabs (Filters / Song Tracks / Artists)."""

    clicked = pyqtSignal(str)

    def __init__(self, key: str, label: str, width: int,
                 accent: str = COL_CYAN, parent=None):
        super().__init__(parent)
        self.setFixedSize(width, 32)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._key = key; self._label = label
        self._active = False
        self._accent = accent
        self._font = inter(12, QFont.Weight.Bold, letter_spacing=0.3)

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
            grad.setColorAt(0.0, _qcolor(self._accent, 0.22))
            grad.setColorAt(1.0, _qcolor(self._accent, 0.08))
            p.fillRect(r, QBrush(grad))
            p.setPen(QPen(_qcolor(self._accent, 0.5)))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
            p.setPen(_qcolor(self._accent, 0.95))
        else:
            p.fillRect(r, QColor(7, 8, 16, 153))
            p.setPen(QPen(QColor(255, 255, 255, 22)))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
            p.setPen(QColor(COL_TEXT_SECONDARY))
        p.setFont(self._font)
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, self._label)
        p.end()


class _SmallDropdown(QWidget):
    """Generic 192×32 (or sized) filter dropdown. Shows current label + ▾.
    Click → opens QMenu with options. Emits ``selection_changed(value)``."""

    selection_changed = pyqtSignal(str)

    def __init__(self, options: list[str], width: int = 192, height: int = 32,
                 enabled: bool = True, parent=None):
        super().__init__(parent)
        self.setFixedSize(width, height)
        self.setCursor(Qt.CursorShape.PointingHandCursor if enabled
                       else Qt.CursorShape.ArrowCursor)
        self._options = list(options)
        self._value = options[0] if options else "(All)"
        self._enabled = enabled
        self._font = inter(11 if height < 32 else 12, QFont.Weight.Medium)
        self._font_chev = inter(9, QFont.Weight.Bold)

    def value(self) -> str:
        return self._value

    def set_value(self, v: str) -> None:
        if v == self._value:
            return
        self._value = v if v in self._options else (self._options[0] if self._options else "(All)")
        self.update(self.rect())

    def set_enabled(self, on: bool) -> None:
        self._enabled = bool(on)
        self.setCursor(Qt.CursorShape.PointingHandCursor if on
                       else Qt.CursorShape.ArrowCursor)
        self.update(self.rect())

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton and self._enabled:
            self._open_menu()
        super().mousePressEvent(e)

    def _open_menu(self) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(_MENU_QSS)
        for opt in self._options:
            menu.addAction(opt)
        chosen = menu.exec(self.mapToGlobal(QPoint(0, self.height())))
        if chosen is None:
            return
        new_v = chosen.text()
        if new_v != self._value:
            self._value = new_v
            self.update(self.rect())
            self.selection_changed.emit(new_v)

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        p.fillRect(r, QColor(7, 8, 16, 178))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 22)))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        p.setPen(QColor(COL_TEXT_PRIMARY) if self._enabled
                 else QColor(COL_TEXT_DIM))
        p.setFont(self._font)
        p.drawText(QRectF(11, 0, self.width() - 24, self.height()),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._value)
        p.setPen(QColor(COL_TEXT_DIM)); p.setFont(self._font_chev)
        p.drawText(QRectF(self.width() - 18, 0, 14, self.height()),
                   Qt.AlignmentFlag.AlignCenter, "▾")
        p.end()


class _CategoryDropdown(QWidget):
    """Big 400×52 cyan-glow category dropdown. Click → opens picker menu."""

    selection_changed = pyqtSignal(int, str)   # (category_id or -1 for All, name)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(400, 52)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._categories: list[dict] = []
        self._selected_id: Optional[int] = None
        self._selected_name: str = "All Songs"
        self._total_song_count: int = 0
        self._font_main = inter(14, QFont.Weight.Bold, letter_spacing=-0.2)
        self._font_count = mono(11)
        self._font_chev = inter(12, QFont.Weight.Bold)
        self.setGraphicsEffect(drop_shadow(12, _qcolor(COL_CYAN, 0.25), 4))

    def set_categories(self, categories: list[dict], total_song_count: int) -> None:
        self._categories = list(categories or [])
        self._total_song_count = int(total_song_count or 0)
        self.update(self.rect())

    def set_selected(self, cat_id: Optional[int]) -> None:
        if cat_id == self._selected_id:
            return
        self._selected_id = cat_id
        if cat_id is None:
            self._selected_name = "All Songs"
        else:
            for c in self._categories:
                if int(c.get("id") or -1) == int(cat_id):
                    self._selected_name = str(c.get("name") or "Category")
                    break
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
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)
        # Color dot left
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(_qcolor(COL_CYAN_LT, 0.95))
        p.drawEllipse(QRectF(13, 21, 10, 10))
        # Name
        p.setPen(_qcolor(COL_CYAN_LT, 0.95)); p.setFont(self._font_main)
        p.drawText(QRectF(31, 5, self.width() - 60, 22),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._selected_name)
        # Count
        if self._selected_id is None:
            count_str = f"{self._total_song_count:,} songs"
        else:
            cnt = next((c.get("song_count") for c in self._categories
                        if int(c.get("id") or -1) == self._selected_id), 0)
            count_str = f"{int(cnt or 0):,} songs"
        p.setPen(QColor(COL_TEXT_SECONDARY)); p.setFont(self._font_count)
        p.drawText(QRectF(31, 25, self.width() - 60, 18),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   count_str)
        # Chevron
        p.setPen(_qcolor(COL_CYAN_LT, 0.95)); p.setFont(self._font_chev)
        p.drawText(QRectF(self.width() - 24, 0, 18, self.height()),
                   Qt.AlignmentFlag.AlignCenter, "▾")
        p.end()


class _RangeArrow(QWidget):
    """The amber > between FROM and TO range dropdowns."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(22, 32)
        self._font = inter(14, QFont.Weight.Black)

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setPen(QColor(COL_AMBER_LT)); p.setFont(self._font)
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, ">")
        p.end()


class _AvailableElementsCard(QWidget):
    """Left card (432×540) containing type icons, sub-tabs, filter panel."""

    type_changed   = pyqtSignal(str)
    subtab_changed = pyqtSignal(str)
    filter_changed = pyqtSignal()    # any filter UI changed (debounced caller-side)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(432, 540)

        self._element_type = "song"
        self._subtab = "filters"
        self._categories: list[dict] = []
        self._total_songs: int = 0

        self._font_h_section = inter(12, QFont.Weight.Black, letter_spacing=0.5)
        self._font_avail     = mono(10, bold=True, letter_spacing=0.3)
        self._font_helper    = inter(10, QFont.Weight.Medium)
        self._font_manage    = inter(10, QFont.Weight.Bold, letter_spacing=0.3)

        # ── Type icons row (y=43) ──
        self._type_tiles: dict[str, _TypeIconTile] = {}
        for i, t in enumerate(ELEMENT_TYPES):
            tile = _TypeIconTile(t, self)
            tile.move(15 + i * 80, 43)
            tile.clicked.connect(self._on_type_clicked)
            tile.set_active(t == self._element_type)
            self._type_tiles[t] = tile

        # ── Sub-tabs (y=99) ──
        self._sub_filters = _SubTab("filters", "Filters", 132, COL_CYAN, self)
        self._sub_filters.move(15, 99); self._sub_filters.set_active(True)
        self._sub_filters.clicked.connect(self._on_subtab_clicked)
        self._sub_tracks = _SubTab("tracks", "Song Tracks", 140, COL_CYAN, self)
        self._sub_tracks.move(151, 99)
        self._sub_tracks.clicked.connect(self._on_subtab_clicked)
        self._sub_artists = _SubTab("artists", "Artists", 130, COL_CYAN, self)
        self._sub_artists.move(295, 99)
        self._sub_artists.clicked.connect(self._on_subtab_clicked)

        # ── Filter dropdowns (Filters tab content) ──
        self._dd_sound_code = _SmallDropdown(SOUND_CODE_OPTIONS, 192, 32, parent=self)
        self._dd_sound_code.move(15, 183)
        self._dd_popularity = _SmallDropdown(POPULARITY_OPTIONS, 192, 32, parent=self)
        self._dd_popularity.move(223, 183)
        self._dd_era = _SmallDropdown(ERA_OPTIONS, 192, 32, parent=self)
        self._dd_era.move(15, 223)
        self._dd_era.selection_changed.connect(lambda _: self.filter_changed.emit())
        self._dd_properties = _SmallDropdown(PROPERTIES_OPTIONS, 192, 32, parent=self)
        self._dd_properties.move(223, 223)
        self._dd_vocal = _SmallDropdown(VOCAL_OPTIONS, 192, 32, parent=self)
        self._dd_vocal.move(15, 263)
        self._dd_vocal.selection_changed.connect(lambda _: self.filter_changed.emit())

        # Range pairs (Year / Priorities / BPM)
        self._dd_year_min = _SmallDropdown(YEAR_OPTIONS, 138, 32, parent=self)
        self._dd_year_min.move(15, 303)
        self._dd_year_min.selection_changed.connect(lambda _: self.filter_changed.emit())
        self._arrow_year = _RangeArrow(self); self._arrow_year.move(159, 303)
        self._dd_year_max = _SmallDropdown(YEAR_OPTIONS, 138, 32, parent=self)
        self._dd_year_max.move(183, 303)
        self._dd_year_max.selection_changed.connect(lambda _: self.filter_changed.emit())

        self._dd_pri_min = _SmallDropdown(PRIORITY_OPTIONS, 138, 32, parent=self)
        self._dd_pri_min.move(15, 343)
        self._dd_pri_min.selection_changed.connect(lambda _: self.filter_changed.emit())
        self._arrow_pri = _RangeArrow(self); self._arrow_pri.move(159, 343)
        self._dd_pri_max = _SmallDropdown(PRIORITY_OPTIONS, 138, 32, parent=self)
        self._dd_pri_max.move(183, 343)
        self._dd_pri_max.selection_changed.connect(lambda _: self.filter_changed.emit())

        self._dd_bpm_min = _SmallDropdown(BPM_OPTIONS, 138, 32, parent=self)
        self._dd_bpm_min.move(15, 383)
        self._dd_bpm_min.selection_changed.connect(lambda _: self.filter_changed.emit())
        self._arrow_bpm = _RangeArrow(self); self._arrow_bpm.move(159, 383)
        self._dd_bpm_max = _SmallDropdown(BPM_OPTIONS, 138, 32, parent=self)
        self._dd_bpm_max.move(183, 383)
        self._dd_bpm_max.selection_changed.connect(lambda _: self.filter_changed.emit())

        # Big category dropdown
        self._cat_dd = _CategoryDropdown(self)
        self._cat_dd.move(15, 455)
        self._cat_dd.selection_changed.connect(lambda *_: self.filter_changed.emit())

        # Sweeper-type config — only visible when element_type='sweeper'.
        # Replaces the song-only filter dropdowns above for the sweeper
        # rotation type. Picker defaults to "Random (any)" → scheduler
        # uses random_from_category. Selecting a specific sweeper pins
        # the slot via clock_slots.item_id (selection_mode='specific').
        # Position drives clock_slots.sweeper_position so SweeperEngine
        # can compute the correct trigger offset on the deck song.
        from typing import Optional as _Opt
        self._dd_sweeper_pick = _SmallDropdown(
            ["Random (any)"], 400, 32, parent=self)
        self._dd_sweeper_pick.move(15, 183)
        self._dd_sweeper_pick.selection_changed.connect(
            lambda _: self.filter_changed.emit())
        self._dd_sweeper_pick.setVisible(False)
        # label → sweeper_id lookup; rebuilt by set_sweepers().
        self._sweeper_id_by_label: dict[str, int] = {}

        self._dd_sweeper_position = _SmallDropdown(
            ["Bridge at End", "Start of Song", "Before Intro",
             "Before End", "Independent", "Custom Position"],
            400, 32, parent=self)
        self._dd_sweeper_position.move(15, 223)
        self._dd_sweeper_position.selection_changed.connect(
            lambda _: self.filter_changed.emit())
        self._dd_sweeper_position.setVisible(False)

        # Jingle-type config — only visible when element_type='jingle'.
        # Single dropdown (no position concept like sweepers — jingles
        # are standalone). "Random (any)" pulls from the master library
        # via random_from_category mode + no category constraint;
        # picking a specific jingle pins the slot via item_id.
        self._dd_jingle_pick = _SmallDropdown(
            ["Random (any)"], 400, 32, parent=self)
        self._dd_jingle_pick.move(15, 183)
        self._dd_jingle_pick.selection_changed.connect(
            lambda _: self.filter_changed.emit())
        self._dd_jingle_pick.setVisible(False)
        self._jingle_id_by_label: dict[str, int] = {}

        # Final visibility pass after every widget exists.
        self._apply_sweeper_visibility()

    # ── Public API ────────────────────────────────────────────────────────

    def element_type(self) -> str:
        return self._element_type

    def set_element_type(self, t: str) -> None:
        if t not in ELEMENT_TYPES or t == self._element_type:
            return
        self._element_type = t
        for k, tile in self._type_tiles.items():
            tile.set_active(k == t)
        self._apply_sweeper_visibility()

    def set_subtab(self, key: str) -> None:
        if key not in ("filters", "tracks", "artists") or key == self._subtab:
            return
        self._subtab = key
        self._sub_filters.set_active(key == "filters")
        self._sub_tracks.set_active(key == "tracks")
        self._sub_artists.set_active(key == "artists")
        # Visibility for filter-tab widgets routes through the helper so
        # the sweeper config (when active) is also factored in.
        self._apply_sweeper_visibility()
        self.update(self.rect())

    def set_categories(self, categories: list[dict], total_song_count: int) -> None:
        self._categories = list(categories or [])
        self._total_songs = int(total_song_count or 0)
        self._cat_dd.set_categories(categories, total_song_count)

    # ── Sweeper-type config ──────────────────────────────────────────────

    def _apply_sweeper_visibility(self) -> None:
        """Filters-tab visibility is per element type:
          • song / spot / voice → song-filter dropdowns visible
          • sweeper             → sweeper picker + position visible
          • jingle              → jingle picker visible (no position)
        All groups hide when the sub-tab leaves Filters."""
        on_filters = self._subtab == "filters"
        is_sweeper = self._element_type == "sweeper"
        is_jingle  = self._element_type == "jingle"
        is_song_like = not (is_sweeper or is_jingle)
        song_filter_widgets = (
            self._dd_sound_code, self._dd_popularity, self._dd_era,
            self._dd_properties, self._dd_vocal,
            self._dd_year_min, self._arrow_year, self._dd_year_max,
            self._dd_pri_min, self._arrow_pri, self._dd_pri_max,
            self._dd_bpm_min, self._arrow_bpm, self._dd_bpm_max,
            self._cat_dd,
        )
        for w in song_filter_widgets:
            w.setVisible(on_filters and is_song_like)
        self._dd_sweeper_pick.setVisible(on_filters and is_sweeper)
        self._dd_sweeper_position.setVisible(on_filters and is_sweeper)
        self._dd_jingle_pick.setVisible(on_filters and is_jingle)

    def set_sweepers(self, sweepers: list) -> None:
        """Populate the specific-sweeper picker. Each entry is either a
        sqlite3.Row or a dict — uses ``id`` and ``name`` columns. The
        first label is always ``"Random (any)"`` so the operator can
        keep the historic random_from_category behaviour."""
        labels = ["Random (any)"]
        self._sweeper_id_by_label = {}
        for sw in sweepers or []:
            try:
                sid = int(sw["id"])
            except (KeyError, TypeError, ValueError):
                continue
            try:
                name = str(sw["name"]) if sw["name"] else f"Sweeper #{sid}"
            except Exception:
                name = f"Sweeper #{sid}"
            label = f"{name}  (#{sid})"
            labels.append(label)
            self._sweeper_id_by_label[label] = sid
        # Reseat the dropdown's options + value (no public API for this
        # on _SmallDropdown so we update the internal state directly).
        self._dd_sweeper_pick._options = labels
        if self._dd_sweeper_pick._value not in labels:
            self._dd_sweeper_pick._value = labels[0]
        self._dd_sweeper_pick.update()

    def selected_sweeper_id(self):
        """Return the sweeper_id for the current pick, or None when the
        operator left the picker on 'Random (any)'."""
        label = self._dd_sweeper_pick.value()
        return self._sweeper_id_by_label.get(label)

    def selected_sweeper_position(self) -> str:
        return self._dd_sweeper_position.value()

    def set_jingles(self, jingles: list) -> None:
        """Populate the specific-jingle picker. Each entry is a
        sqlite3.Row or dict — uses ``id`` and ``name``. The first
        label is always ``"Random (any)"`` so the operator can keep
        the historic random behaviour without picking a specific row."""
        labels = ["Random (any)"]
        self._jingle_id_by_label = {}
        for j in jingles or []:
            try:
                jid = int(j["id"])
            except (KeyError, TypeError, ValueError):
                continue
            try:
                name = str(j["name"]) if j["name"] else f"Jingle #{jid}"
            except Exception:
                name = f"Jingle #{jid}"
            label = f"{name}  (#{jid})"
            labels.append(label)
            self._jingle_id_by_label[label] = jid
        self._dd_jingle_pick._options = labels
        if self._dd_jingle_pick._value not in labels:
            self._dd_jingle_pick._value = labels[0]
        self._dd_jingle_pick.update()

    def selected_jingle_id(self):
        """Return the jingle_id for the current pick, or None when the
        operator left the picker on 'Random (any)'."""
        label = self._dd_jingle_pick.value()
        return self._jingle_id_by_label.get(label)

    def filter_state(self) -> dict:
        """Snapshot the filter UI as a dict matching scheduler's
        ``filter_json`` keys. ``(All)`` values are dropped (no constraint)."""
        d: dict = {}

        # Category — Pick Category dropdown drives sound_code by name
        cid = self._cat_dd.selected_id()
        if cid is not None:
            d["sound_code"] = self._cat_dd.selected_name()
            d["category_id"] = int(cid)

        # Era / Vocal
        if self._dd_era.value() not in ("(All)", ""):
            d["era"] = self._dd_era.value()
        if self._dd_vocal.value() not in ("(All)", ""):
            d["vocal"] = self._dd_vocal.value()

        # Range axes — only emit if not All
        for k, v in [("year_min", self._dd_year_min.value()),
                     ("year_max", self._dd_year_max.value()),
                     ("priority_min", self._dd_pri_min.value()),
                     ("priority_max", self._dd_pri_max.value()),
                     ("bpm_min", self._dd_bpm_min.value()),
                     ("bpm_max", self._dd_bpm_max.value())]:
            if v in (None, "", "(All)"):
                continue
            try:
                d[k] = int(v)
            except (TypeError, ValueError):
                pass
        return d

    def reset_filters(self) -> None:
        for dd in (self._dd_sound_code, self._dd_popularity, self._dd_era,
                   self._dd_properties, self._dd_vocal,
                   self._dd_year_min, self._dd_year_max,
                   self._dd_pri_min, self._dd_pri_max,
                   self._dd_bpm_min, self._dd_bpm_max):
            dd.set_value("(All)")
        self._cat_dd.set_selected(None)
        self.filter_changed.emit()

    # ── Internal handlers ────────────────────────────────────────────────

    def _on_type_clicked(self, t: str) -> None:
        if t == self._element_type:
            return
        self.set_element_type(t)
        self.type_changed.emit(t)

    def _on_subtab_clicked(self, key: str) -> None:
        if key == self._subtab:
            return
        self.set_subtab(key)
        self.subtab_changed.emit(key)

    # ── Paint ────────────────────────────────────────────────────────────

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        _qfill_card(p, r)
        _draw_top_accent(p, self.width(), COL_AMBER, COL_AMBER + "66")
        _qstroke_card(p, r)

        # "Available Clock Elements"
        p.setPen(QColor(COL_AMBER_LT)); p.setFont(self._font_h_section)
        p.drawText(QRectF(15, 15, 300, 13),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "Available Clock Elements")

        if self._subtab == "filters":
            # "Categories" label
            p.setPen(QColor(COL_AMBER_LT)); p.setFont(self._font_h_section)
            p.drawText(QRectF(15, 151, 200, 14),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       "Categories")
            # "Pick Category" + count badge
            p.setPen(QColor(COL_AMBER_LT)); p.setFont(self._font_h_section)
            p.drawText(QRectF(15, 431, 200, 14),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       "Pick Category")
            # "8 AVAIL" badge — show real count
            badge_count = len(self._categories) or 0
            badge_rect = QRectF(self.width() - 73, 431, 56, 18)
            p.fillRect(badge_rect, _qcolor(COL_AMBER, 0.18))
            p.setPen(QPen(_qcolor(COL_AMBER, 0.4)))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(badge_rect.adjusted(0.5, 0.5, -0.5, -0.5), 9, 9)
            p.setPen(QColor(COL_AMBER_LT)); p.setFont(self._font_avail)
            p.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter,
                       f"{badge_count} AVAIL")
            # Helper line
            p.setPen(QColor(COL_TEXT_SECONDARY)); p.setFont(self._font_helper)
            p.drawText(QRectF(15, 513, 280, 14),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       self._build_helper_line())
            # "⚙ Manage" purple link, right
            p.setPen(QColor(COL_PURPLE_LT)); p.setFont(self._font_manage)
            p.drawText(QRectF(self.width() - 90, 513, 80, 14),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       "⚙  Manage")
        else:
            # Placeholder for Song Tracks / Artists tabs
            p.setPen(QColor(COL_TEXT_DIM))
            p.setFont(inter(13, QFont.Weight.Bold))
            label = ("Song Tracks picker — coming soon."
                     if self._subtab == "tracks"
                     else "Artists picker — coming soon.")
            p.drawText(QRectF(15, 160, self.width() - 30, 30),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       label)
            p.setFont(inter(11, QFont.Weight.Medium))
            p.drawText(QRectF(15, 195, self.width() - 30, 40),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop |
                       Qt.TextFlag.TextWordWrap,
                       "Use Filters tab for category-based rotations.")
        p.end()

    def _build_helper_line(self) -> str:
        """Top categories preview — first 5 names + +N more."""
        if not self._categories:
            return "Click to switch · No categories yet"
        names = [str(c.get("name") or "").strip()
                 for c in self._categories[:5] if c.get("name")]
        rest = max(0, len(self._categories) - 5)
        suffix = f" · +{rest}" if rest else ""
        return "Click to switch · " + " · ".join(names) + suffix


# ════════════════════════════════════════════════════════════════════════
# FILTER RESULTS CARD (180×220)
# ════════════════════════════════════════════════════════════════════════

class _FilterResultsCard(QWidget):
    """Live count + estimated avg duration of the filter set."""

    reset_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(180, 220)
        self._count = 0
        self._avg_s = 0.0
        self._font_h     = inter(12, QFont.Weight.Black, letter_spacing=0.5)
        self._font_reset = inter(11, QFont.Weight.Bold, letter_spacing=0.3)
        self._font_count = mono(44, bold=True, letter_spacing=-2.0)
        self._font_subtitle = inter(11, QFont.Weight.Bold, letter_spacing=0.3)
        self._font_dur   = mono(22, bold=True, letter_spacing=-0.5)
        self._font_dur_lbl = inter(9, QFont.Weight.Bold, letter_spacing=0.6)

    def set_data(self, count: int, avg_s: float) -> None:
        if count == self._count and abs(avg_s - self._avg_s) < 0.01:
            return
        self._count = int(count)
        self._avg_s = float(avg_s)
        self.update(self.rect())

    def mousePressEvent(self, e: QMouseEvent) -> None:
        # Click "Reset All Filters" hot zone (rough)
        if (e.button() == Qt.MouseButton.LeftButton
                and 15 <= e.position().toPoint().x() <= 130
                and 38 <= e.position().toPoint().y() <= 56):
            self.reset_clicked.emit()
        super().mousePressEvent(e)

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        _qfill_card(p, r)
        _draw_top_accent(p, self.width(), COL_AMBER, COL_AMBER + "66")
        _qstroke_card(p, r)

        p.setPen(QColor(COL_AMBER_LT)); p.setFont(self._font_h)
        p.drawText(QRectF(15, 15, 200, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "Filter Results")
        # Reset link
        p.setPen(QColor(COL_ROSE_LT)); p.setFont(self._font_reset)
        p.drawText(QRectF(15, 41, 120, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "Reset All Filters")
        p.fillRect(QRectF(15, 56, 112, 1), _qcolor(COL_ROSE, 0.4))
        # Big count
        p.setPen(QColor(COL_AMBER_LT)); p.setFont(self._font_count)
        p.drawText(QRectF(0, 69, self.width(), 50),
                   Qt.AlignmentFlag.AlignCenter,
                   str(self._count))
        # Subtitle
        p.setPen(QColor(COL_AMBER_LT)); p.setFont(self._font_subtitle)
        p.drawText(QRectF(0, 121, self.width(), 14),
                   Qt.AlignmentFlag.AlignCenter, "Songs Available")
        # Divider
        p.fillRect(QRectF(15, 147, self.width() - 30, 1),
                   QColor(255, 255, 255, 18))
        # Duration
        p.setPen(QColor(COL_AMBER_LT)); p.setFont(self._font_dur)
        dur_text = f"{self._avg_s:.1f}s" if self._avg_s < 60 \
            else f"{int(self._avg_s // 60)}m{int(self._avg_s % 60):02d}"
        p.drawText(QRectF(0, 157, self.width(), 26),
                   Qt.AlignmentFlag.AlignCenter, dur_text)
        p.setPen(QColor(COL_TEXT_DIM)); p.setFont(self._font_dur_lbl)
        p.drawText(QRectF(15, 191, self.width() - 30, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "EST. AVG DURATION")
        p.end()


# ════════════════════════════════════════════════════════════════════════
# ACTION STACK — 4 vertical buttons (80×332)
# ════════════════════════════════════════════════════════════════════════

class _ActionTile(QWidget):
    """One 64×70 vertical button. Variants: primary green / outline green /
    outline rose."""

    clicked = pyqtSignal()

    def __init__(self, icon: str, label: str, accent: str = COL_GREEN,
                 primary: bool = False, parent=None):
        super().__init__(parent)
        self.setFixedSize(64, 70)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._icon = icon; self._label = label
        self._accent = accent
        self._primary = primary
        self._enabled = True
        self._font_icon  = inter(26, QFont.Weight.Black)
        self._font_label = inter(10, QFont.Weight.Black, letter_spacing=0.6)
        if primary:
            self.setGraphicsEffect(drop_shadow(14, _qcolor(accent, 0.45), 6))

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
            sheen = QLinearGradient(0, 0, 0, 18)
            sheen.setColorAt(0.0, QColor(255, 255, 255, 50))
            sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
            p.fillRect(QRectF(1, 1, self.width() - 2, 18), QBrush(sheen))
            p.setPen(QPen(QColor(255, 255, 255, 30)))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)
            text_color = QColor(255, 255, 255)
        else:
            alpha = 0.18 if self._enabled else 0.05
            p.fillRect(r, _qcolor(self._accent, alpha))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(_qcolor(self._accent,
                                  0.4 if self._enabled else 0.12)))
            p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)
            text_color = QColor(self._accent + ("" if self._enabled else "66"))
            if not self._enabled:
                text_color = _qcolor(self._accent, 0.35)
        # Icon
        p.setPen(text_color); p.setFont(self._font_icon)
        p.drawText(QRectF(0, 5, self.width(), 35),
                   Qt.AlignmentFlag.AlignCenter, self._icon)
        # Label
        p.setFont(self._font_label)
        p.drawText(QRectF(0, 45, self.width(), 20),
                   Qt.AlignmentFlag.AlignCenter, self._label)
        p.end()


class _ActionStack(QWidget):
    """80 × 332 column with ADD / INSERT / REPLACE / DELETE."""

    add_clicked     = pyqtSignal()
    insert_clicked  = pyqtSignal()
    replace_clicked = pyqtSignal()
    delete_clicked  = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(80, 332)
        self._add = _ActionTile("+", "ADD", COL_GREEN, primary=True, parent=self)
        self._add.move(7, 7); self._add.clicked.connect(self.add_clicked.emit)
        self._insert = _ActionTile("↳", "INSERT", COL_GREEN, parent=self)
        self._insert.move(7, 85); self._insert.clicked.connect(self.insert_clicked.emit)
        self._insert.set_enabled(False)
        self._replace = _ActionTile("⇄", "REPLACE", COL_GREEN, parent=self)
        self._replace.move(7, 163); self._replace.clicked.connect(self.replace_clicked.emit)
        self._replace.set_enabled(False)
        self._delete = _ActionTile("🗑", "DELETE", COL_ROSE, parent=self)
        self._delete.move(7, 241); self._delete.clicked.connect(self.delete_clicked.emit)
        self._delete.set_enabled(False)

    def set_states(self, add_on: bool, has_selection: bool) -> None:
        self._add.set_enabled(add_on)
        self._insert.set_enabled(has_selection)
        self._replace.set_enabled(has_selection)
        self._delete.set_enabled(has_selection)

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        _qfill_card(p, r)
        _qstroke_card(p, r)
        p.end()


# ════════════════════════════════════════════════════════════════════════
# CLOCK EDITOR CARD — wraps face + Colorize By + status bar + checkboxes
# ════════════════════════════════════════════════════════════════════════

class _Checkbox(QWidget):
    """Small click-to-toggle checkbox + label."""

    toggled = pyqtSignal(bool)

    def __init__(self, label: str, accent: str = COL_CYAN, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._label = label
        self._accent = accent
        self._checked = False
        self._font = inter(11, QFont.Weight.Medium)
        # Width auto from label
        m = self._font.pointSizeF() * 0.6
        self.setFixedSize(int(20 + len(label) * 7), 18)

    def set_checked(self, on: bool) -> None:
        if on == self._checked:
            return
        self._checked = bool(on)
        self.update(self.rect())

    def is_checked(self) -> bool:
        return self._checked

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._checked = not self._checked
            self.update(self.rect())
            self.toggled.emit(self._checked)
        super().mousePressEvent(e)

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Box
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
        # Label
        p.setPen(_qcolor(self._accent if self._checked else COL_TEXT_SECONDARY, 0.95))
        p.setFont(self._font)
        p.drawText(QRectF(20, 0, self.width() - 22, self.height()),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._label)
        p.end()


class _ClockContentsList(QWidget):
    """Readable play-order list — sits in the empty band to the RIGHT of
    the clock face circle inside the face frame (task B, 2026-07-09).

    Display-only mirror of the screen's element list so the operator can
    READ what the clock plays (type + category / pinned item) without
    decoding the arc ring. Rows are precomputed dicts:
        {"title": "Song", "sub": "Pool 08", "color": "#fcd34d"}
    Click a row → ``row_clicked(idx)`` (screen syncs the face selection).
    """

    row_clicked = pyqtSignal(int)

    _HEADER_H = 24
    _ROW_H    = 30

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(156, 364)
        self._rows: list[dict] = []
        self._selected: Optional[int] = None

        self._font_hdr   = inter(9, QFont.Weight.Bold, letter_spacing=1.2)
        self._font_num   = mono(9)
        self._font_title = inter(11, QFont.Weight.Bold, letter_spacing=-0.1)
        self._font_sub   = inter(9, QFont.Weight.Medium)

    # ── Public API ───────────────────────────────────────────────────────

    def set_rows(self, rows: list[dict]) -> None:
        self._rows = list(rows or [])
        if self._selected is not None and self._selected >= len(self._rows):
            self._selected = None
        self.update(self.rect())

    def set_selected(self, idx: Optional[int]) -> None:
        if idx == self._selected:
            return
        self._selected = idx
        self.update(self.rect())

    def _max_visible(self) -> int:
        return max(1, (self.height() - self._HEADER_H - 6) // self._ROW_H)

    def _row_at(self, y: int) -> Optional[int]:
        if y < self._HEADER_H:
            return None
        idx = (y - self._HEADER_H) // self._ROW_H
        if 0 <= idx < min(len(self._rows), self._max_visible()):
            return int(idx)
        return None

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            idx = self._row_at(int(e.position().y()))
            if idx is not None:
                self.row_clicked.emit(idx)
        super().mousePressEvent(e)

    # ── Paint ────────────────────────────────────────────────────────────

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        p.fillRect(r, QColor(255, 255, 255, 8))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 14)))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)

        # Header
        p.setPen(QColor(COL_TEXT_DIM)); p.setFont(self._font_hdr)
        p.drawText(QRectF(10, 0, self.width() - 20, self._HEADER_H),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "PLAY ORDER")

        if not self._rows:
            p.setPen(QColor(COL_TEXT_MUTED)); p.setFont(self._font_sub)
            p.drawText(QRectF(10, self._HEADER_H, self.width() - 20, 30),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       "No elements")
            p.end(); return

        max_vis = self._max_visible()
        overflow = len(self._rows) - max_vis
        visible = self._rows[:max_vis] if overflow > 0 else self._rows
        # Overflow steals the last row slot for the "+N more" line
        if overflow > 0:
            visible = self._rows[:max_vis - 1]
            overflow = len(self._rows) - len(visible)

        fm_title = None
        fm_sub = None
        for i, row in enumerate(visible):
            y = self._HEADER_H + i * self._ROW_H
            rr = QRectF(2, y, self.width() - 4, self._ROW_H)
            color = QColor(row.get("color") or COL_AMBER_LT)
            if self._selected == i:
                p.fillRect(rr, QColor(255, 255, 255, 18))
                p.fillRect(QRectF(2, y + 4, 3, self._ROW_H - 8), color)
            # number
            p.setPen(QColor(COL_TEXT_MUTED)); p.setFont(self._font_num)
            p.drawText(QRectF(10, y, 14, 16),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       str(i + 1))
            # type color dot
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(color))
            p.drawEllipse(QPointF(30, y + 8), 3.0, 3.0)
            p.setBrush(Qt.BrushStyle.NoBrush)
            # title line
            p.setPen(QColor(COL_TEXT_PRIMARY)); p.setFont(self._font_title)
            if fm_title is None:
                fm_title = p.fontMetrics()
            title = fm_title.elidedText(
                str(row.get("title") or ""), Qt.TextElideMode.ElideRight,
                self.width() - 50)
            p.drawText(QRectF(40, y, self.width() - 50, 16),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       title)
            # sub line (category / random / pinned name)
            p.setPen(QColor(COL_TEXT_SECONDARY)); p.setFont(self._font_sub)
            if fm_sub is None:
                fm_sub = p.fontMetrics()
            sub = fm_sub.elidedText(
                str(row.get("sub") or ""), Qt.TextElideMode.ElideRight,
                self.width() - 50)
            p.drawText(QRectF(40, y + 15, self.width() - 50, 12),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       sub)

        if overflow > 0:
            y = self._HEADER_H + len(visible) * self._ROW_H
            p.setPen(QColor(COL_TEXT_MUTED)); p.setFont(self._font_sub)
            p.drawText(QRectF(10, y, self.width() - 20, self._ROW_H),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       f"+{overflow} more…")
        p.end()


class _ClockEditorCard(QWidget):
    """680 × 564 right-side card. Title + Colorize By + status bar +
    clock face + bottom checkboxes."""

    colorize_changed = pyqtSignal(str)
    loop_changed     = pyqtSignal(bool)
    show_only_descriptions_changed = pyqtSignal(bool)
    element_clicked  = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(680, 564)

        self._status_state = "ok"   # "ok" | "warn" | "error"
        self._status_text  = "No Errors Found"
        self._colorize_by  = DEFAULT_COLORIZE_BY

        self._font_h     = inter(14, QFont.Weight.Black, letter_spacing=-0.2)
        self._font_clbl  = inter(10, QFont.Weight.Bold, letter_spacing=1.0)
        self._font_status = inter(12, QFont.Weight.Bold, letter_spacing=0.3)

        # Colorize By dropdown (160×30 at 503,13)
        self._colorize_dd = _SmallDropdown(
            ["Sound Code", "Type", "Era"], 160, 30, parent=self)
        self._colorize_dd.move(503, 13)
        self._colorize_dd.set_value("Sound Code")
        self._colorize_dd.selection_changed.connect(self._on_colorize_changed)

        # Status bar at (15, 55, 648×34) — repainted by us; no widget
        # Clock face inner frame at (15, 99, 648×380)
        self._face_frame = QRectF(15, 99, 648, 380)
        # Clock face widget
        self._face = ClockFaceWidget(self)
        self._face.move(int(self._face_frame.x()), int(self._face_frame.y()))
        self._face.element_clicked.connect(self.element_clicked.emit)

        # Play-order list — created AFTER the face so it stacks on top of
        # the empty band right of the circle (circle glow ends at x≈499).
        self._contents = _ClockContentsList(self)
        self._contents.move(504, 107)

        # Checkboxes at y=499
        self._loop_cb = _Checkbox("Loop / Cycle clock elements",
                                  COL_CYAN, self)
        self._loop_cb.move(15, 499)
        self._loop_cb.toggled.connect(self.loop_changed.emit)
        self._desc_cb = _Checkbox("Show only song descriptions",
                                  COL_CYAN, self)
        self._desc_cb.move(239, 499)
        self._desc_cb.set_checked(True)
        self._desc_cb.toggled.connect(self.show_only_descriptions_changed.emit)

    # ── Public API ───────────────────────────────────────────────────────

    def face(self) -> ClockFaceWidget:
        return self._face

    def contents_list(self) -> "_ClockContentsList":
        return self._contents

    def set_status(self, state: str, text: str) -> None:
        self._status_state = state if state in ("ok", "warn", "error") else "ok"
        self._status_text = text or ""
        self.update(QRect(15, 55, 648, 34))

    def colorize_by(self) -> str:
        return self._colorize_by

    def set_colorize_by(self, mode: str) -> None:
        m = (mode or "type").lower()
        if m == "sound code" or m == "category":
            self._colorize_by = "category"
            self._colorize_dd.set_value("Sound Code")
        elif m == "era":
            self._colorize_by = "era"
            self._colorize_dd.set_value("Era")
        else:
            self._colorize_by = "type"
            self._colorize_dd.set_value("Type")
        self._face.set_colorize_by(self._colorize_by)

    def set_loop(self, on: bool) -> None:
        self._loop_cb.set_checked(bool(on))

    def loop(self) -> bool:
        return self._loop_cb.is_checked()

    def set_show_only_descriptions(self, on: bool) -> None:
        self._desc_cb.set_checked(bool(on))

    def show_only_descriptions(self) -> bool:
        return self._desc_cb.is_checked()

    def _on_colorize_changed(self, label: str) -> None:
        l = (label or "").lower()
        if l == "sound code":
            self._colorize_by = "category"
        elif l == "era":
            self._colorize_by = "era"
        else:
            self._colorize_by = "type"
        self._face.set_colorize_by(self._colorize_by)
        self.colorize_changed.emit(self._colorize_by)

    # ── Paint ────────────────────────────────────────────────────────────

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        _qfill_card(p, r)
        _draw_top_accent(p, self.width(), COL_CYAN, COL_PINK, mid=COL_PURPLE_MID)
        _qstroke_card(p, r)

        # Title
        p.setPen(QColor(COL_TEXT_PRIMARY)); p.setFont(self._font_h)
        p.drawText(QRectF(19, 15, 200, 18),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "Clock Editor")
        # COLORIZE BY: label — starts earlier + wide enough so it ends
        # BEFORE the dropdown at x=503 (the old 50px rect clipped it to
        # "COLOR" half-hidden behind the combo; audit 2026-07-03).
        p.setPen(QColor(COL_TEXT_DIM)); p.setFont(self._font_clbl)
        p.drawText(QRectF(410, 21, 88, 12),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   "COLORIZE BY:")

        # Status bar
        bar = QRectF(15, 55, 648, 34)
        if self._status_state == "ok":
            tone = COL_GREEN; tone_lt = COL_GREEN_LT
        elif self._status_state == "warn":
            tone = COL_AMBER; tone_lt = COL_AMBER_LT
        else:
            tone = COL_ROSE;  tone_lt = COL_ROSE_LT
        p.fillRect(bar, _qcolor(tone, 0.10))
        p.setPen(QPen(_qcolor(tone, 0.3))); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(bar.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        # Mini check indicator
        pill = QRectF(26, 63, 16, 16)
        p.fillRect(pill, _qcolor(tone, 0.4))
        p.setPen(QPen(_qcolor(tone, 0.95), 1.5))
        p.drawRoundedRect(pill.adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)
        p.setPen(QColor(tone_lt))
        p.setFont(inter(10, QFont.Weight.Bold))
        marker = "✓" if self._status_state == "ok" else (
            "!" if self._status_state == "warn" else "×")
        p.drawText(pill, Qt.AlignmentFlag.AlignCenter, marker)
        # Status text
        p.setPen(QColor(tone_lt)); p.setFont(self._font_status)
        p.drawText(QRectF(50, 55, self.width() - 70, 34),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._status_text)
        # Clock face frame outline
        p.fillRect(self._face_frame, QColor(0, 0, 0, 76))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 10)))
        p.drawRoundedRect(self._face_frame.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        p.end()


# ════════════════════════════════════════════════════════════════════════
# OK / Cancel bottom buttons
# ════════════════════════════════════════════════════════════════════════

class _OkButton(QWidget):
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(120, 44)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setGraphicsEffect(drop_shadow(20, _qcolor(COL_PURPLE_DEEP, 0.45), 8))
        self._font = inter(14, QFont.Weight.Bold, letter_spacing=0.3)

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        grad = QLinearGradient(0, 0, 0, self.height())
        grad.setColorAt(0.0, QColor(COL_PURPLE_LT))
        grad.setColorAt(1.0, QColor(COL_PURPLE_DEEP))
        p.fillRect(r, QBrush(grad))
        sheen = QLinearGradient(0, 0, 0, 16)
        sheen.setColorAt(0.0, QColor(255, 255, 255, 45))
        sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.fillRect(QRectF(1, 1, self.width() - 2, 16), QBrush(sheen))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 30)))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)
        p.setPen(QColor(255, 255, 255)); p.setFont(self._font)
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, "✓  OK")
        p.end()


class _CancelButton(QWidget):
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(110, 44)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._font = inter(14, QFont.Weight.Bold, letter_spacing=0.3)

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        p.fillRect(r, QColor(7, 8, 16, 178))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_qcolor(COL_ROSE, 0.3)))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)
        p.setPen(QColor(COL_ROSE_LT)); p.setFont(self._font)
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, "Cancel")
        p.end()


# ════════════════════════════════════════════════════════════════════════
# CLOCK EDITOR — the screen
# ════════════════════════════════════════════════════════════════════════

class ClockEditor(QWidget):
    """Premium-theme Clock Editor screen.

    Signals:
      screen_requested(str) — 'studio_open' / 'libraries' / 'settings' /
                              'ai_magic' / 'main_auto_schedule'

    Mode handling: call ``load_for_mode(mode, clock_id=None)`` BEFORE
    showing the screen. ``mode``:
        "new"        — blank create
        "edit"       — load db.get_clock(clock_id) + slots
        "duplicate"  — load source clock; treated as create on save
                       (no id reused; name prefixed "Copy of ")
    """

    screen_requested = pyqtSignal(str)
    saved = pyqtSignal(int)   # emits the (new) clock id

    FILTER_DEBOUNCE_MS = 200

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

        # ── State (load_for_mode populates) ────────────────────────────
        self._mode: Mode = MODE_NEW
        self._source_id: Optional[int] = None    # for edit/duplicate
        self._elements: list[dict] = []          # in-memory slot list
        self._dirty: bool = False
        # Suppress dirty tracking while we programmatically load — the
        # set_name/set_comments/set_color path fires textChanged and the
        # color_picked signal, which would otherwise mark every load as
        # dirty before the user does anything.
        self._is_loading: bool = False
        self._categories_cache: list[dict] = []
        self._total_song_count: int = 0

        # Cached fonts
        self._font_breadcrumb = inter(11, QFont.Weight.Bold, letter_spacing=1.5)
        self._font_title      = inter(36, QFont.Weight.Black, letter_spacing=-1.5)
        self._font_subtitle   = inter(14, QFont.Weight.Medium, letter_spacing=-0.1)

        # ── Header ────────────────────────────────────────────────────
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

        # ── Meta strip ────────────────────────────────────────────────
        self._meta = _MetaStrip(self)
        self._meta.move(56, 230)
        self._meta.name_changed.connect(self._on_name_changed)
        self._meta.comments_changed.connect(self._on_dirty)
        self._meta.color_changed.connect(self._on_dirty)
        self._meta.backup_clicked.connect(self._on_backup_clicked)

        # ── Available Elements card ───────────────────────────────────
        self._lib = _AvailableElementsCard(self)
        self._lib.move(56, 320)
        self._lib.type_changed.connect(self._on_type_changed)
        self._lib.subtab_changed.connect(self._on_subtab_changed)
        self._lib.filter_changed.connect(self._on_filter_changed)

        # ── Filter Results card ───────────────────────────────────────
        self._results = _FilterResultsCard(self)
        self._results.move(504, 320)
        self._results.reset_clicked.connect(self._on_reset_filters)

        # ── Action stack ──────────────────────────────────────────────
        self._actions = _ActionStack(self)
        self._actions.move(504, 552)
        self._actions.add_clicked.connect(self._on_add)
        self._actions.insert_clicked.connect(self._on_insert)
        self._actions.replace_clicked.connect(self._on_replace)
        self._actions.delete_clicked.connect(self._on_delete)

        # ── Clock Editor card (right) ─────────────────────────────────
        self._editor = _ClockEditorCard(self)
        self._editor.move(704, 320)
        self._editor.element_clicked.connect(self._on_face_element_clicked)
        self._editor.contents_list().row_clicked.connect(
            self._on_content_row_clicked)
        self._editor.colorize_changed.connect(self._on_colorize_changed)
        self._editor.loop_changed.connect(self._on_dirty)
        self._editor.show_only_descriptions_changed.connect(self._on_dirty)

        # ── OK / Cancel ───────────────────────────────────────────────
        self._ok = _OkButton(self); self._ok.move(1156, 836)
        self._ok.clicked.connect(self._on_ok)
        self._cancel = _CancelButton(self); self._cancel.move(1284, 836)
        self._cancel.clicked.connect(self._on_cancel)

        # ── Filter debounce timer ─────────────────────────────────────
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(self.FILTER_DEBOUNCE_MS)
        self._filter_timer.timeout.connect(self._refresh_filter_results)

        # ── 1Hz tick for header time ──────────────────────────────────
        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._on_tick)
        self._tick.start()
        self._on_tick()

        # Initial state
        self.load_for_mode(MODE_NEW)
        log.info("ClockEditor ready (Figma 285:2 — Premium Dark)")

    # ── Lifecycle / mode loader ─────────────────────────────────────────

    def load_for_mode(self, mode: Mode,
                      clock_id: Optional[int] = None) -> None:
        """MainWindow calls this BEFORE setCurrentWidget."""
        if mode not in (MODE_NEW, MODE_EDIT, MODE_DUPLICATE):
            mode = MODE_NEW
        self._mode = mode
        self._source_id = int(clock_id) if clock_id else None
        self._dirty = False
        self._is_loading = True

        # Refresh categories cache
        try:
            cats = list(self._db.get_categories())
            self._categories_cache = [
                {"id": int(c["id"]), "name": c["name"],
                 "color": c["color"] if "color" in c.keys() else None,
                 "song_count": int(c["song_count"] or 0)
                 if "song_count" in c.keys() else 0}
                for c in cats]
        except Exception as exc:
            log.warning(f"load categories failed: {exc}")
            self._categories_cache = []
        try:
            total = self._db._conn().execute(
                "SELECT COUNT(*) FROM songs WHERE is_enabled=1"
            ).fetchone()
            self._total_song_count = int(total[0] or 0) if total else 0
        except Exception:
            self._total_song_count = 0
        self._lib.set_categories(self._categories_cache, self._total_song_count)
        # Refresh the sweeper picker — it appears when the operator
        # picks element_type='sweeper'. Pulled fresh on every load so
        # newly-added sweepers from the Sweepers Library show up
        # without a screen reconstruct.
        try:
            self._lib.set_sweepers(list(self._db.get_sweepers_active()))
        except Exception as exc:
            log.warning(f"load sweepers failed: {exc}")
        # Same pattern for jingles — picker appears when element_type=
        # 'jingle'. Pulls active rows from the master `jingles` library
        # so anything added via the Jingles Library editor (Figma 106:2)
        # shows up immediately.
        try:
            jingle_rows = self._db._conn().execute(
                "SELECT * FROM jingles WHERE is_enabled = 1 "
                "ORDER BY display_order, id"
            ).fetchall()
            self._lib.set_jingles(list(jingle_rows))
        except Exception as exc:
            log.warning(f"load jingles failed: {exc}")

        # Populate fields per mode
        if mode == MODE_NEW or self._source_id is None:
            self._meta.set_name("New Clock")
            self._meta.set_comments("")
            self._meta.set_color(DEFAULT_CLOCK_COLOR)
            self._editor.set_loop(True)
            self._editor.set_show_only_descriptions(False)
            self._elements = []
        else:
            try:
                row = self._db.get_clock(int(self._source_id))
                slots = list(self._db.get_clock_slots(int(self._source_id)))
            except Exception as exc:
                log.warning(f"load clock {self._source_id} failed: {exc}")
                row = None; slots = []
            if row is not None:
                src_name = str(row["name"] or "Clock")
                if mode == MODE_DUPLICATE:
                    src_name = f"Copy of {src_name}"
                self._meta.set_name(src_name)
                self._meta.set_comments(
                    str(row["comments"]) if "comments" in row.keys() and row["comments"] else "")
                color = (row["color"] if "color" in row.keys() and row["color"]
                         else DEFAULT_CLOCK_COLOR)
                self._meta.set_color(color)
                self._editor.set_loop(
                    bool(int(row["loop_cycle_enabled"] or 0))
                    if "loop_cycle_enabled" in row.keys() else True)
                self._editor.set_show_only_descriptions(
                    bool(int(row["show_only_descriptions"] or 0))
                    if "show_only_descriptions" in row.keys() else False)
            self._elements = self._slots_to_elements(slots)

        # Sync UI to elements
        self._editor.face().set_elements(self._elements)
        self._editor.face().set_selected(None)
        self._sync_contents_list()
        self._editor.set_status("ok", "No Errors Found")
        self._refresh_action_states()
        self._refresh_filter_results()
        # End of programmatic load — re-enable dirty tracking
        self._is_loading = False
        # In duplicate mode, mark dirty so OK button has effect on first save
        # even without further user changes (the rename itself is the change).
        if mode == MODE_DUPLICATE:
            self._dirty = True
        self.update(self.rect())

    @staticmethod
    def _slots_to_elements(slots) -> list[dict]:
        """Convert sqlite Rows → element dicts the screen owns."""
        out: list[dict] = []
        for s in slots:
            keys = s.keys()
            stype_db = (s["slot_type"] if "slot_type" in keys else "song") or "song"
            ui_type = DB_TO_ELEMENT_TYPE.get(stype_db.lower(), "song")
            cat_id = s["category_id"] if "category_id" in keys else None
            cat_color = s["cat_color"] if "cat_color" in keys else None
            fjs = s["filter_json"] if "filter_json" in keys else None
            try:
                fj = json.loads(fjs) if fjs else {}
            except Exception:
                fj = {}
            mp_raw = s["minute_position"] if "minute_position" in keys else None
            out.append({
                "element_type":      ui_type,
                "slot_type_db":      stype_db,
                "category_id":       int(cat_id) if cat_id else None,
                "category_color":    cat_color,
                "cat_name":          str(s["cat_name"])
                                     if "cat_name" in keys and s["cat_name"] else None,
                "filter_json":       fj,
                # 0/NULL means "sequential" (the auto-grid builder writes 0
                # for every slot) → None so the face chains the element after
                # the previous one instead of stacking all arcs at minute 0
                # (the "empty AUTO clock face" bug, 2026-07-09 task A).
                "minute_position":   int(mp_raw) if mp_raw else None,
                "duration_seconds":  int(s["duration_seconds"] or 0)
                                     if "duration_seconds" in keys else 0,
                "selection_mode":    str(s["selection_mode"] or "")
                                     if "selection_mode" in keys else "",
                # Carry the pin columns so a load→save round-trip keeps a
                # pinned sweeper/jingle (save payload forwards them when set).
                "item_id":           int(s["item_id"])
                                     if "item_id" in keys and s["item_id"] else None,
                "sweeper_position":  s["sweeper_position"]
                                     if "sweeper_position" in keys else None,
                "ref_text":          s["ref_text"] if "ref_text" in keys else None,
                "era":               fj.get("era") if isinstance(fj, dict) else None,
            })
        return out

    # ── Filter pipeline ──────────────────────────────────────────────────

    def _on_filter_changed(self) -> None:
        # Restart debounce — final value within 200ms of last edit
        self._filter_timer.start()

    def _on_reset_filters(self) -> None:
        self._lib.reset_filters()

    def _refresh_filter_results(self) -> None:
        """Compute live count + avg duration via the scheduler engine's
        filter helper (single source of truth for filter→songs SQL)."""
        if self._scheduler is None:
            self._results.set_data(0, 0.0)
            return
        fdict = self._lib.filter_state()
        try:
            fjs = json.dumps(fdict)
            rows = self._scheduler._songs_matching_filter_json(fjs)  # see docstring note
        except Exception as exc:
            log.warning(f"filter resolution failed: {exc}")
            self._results.set_data(0, 0.0); return
        count = len(rows)
        if count > 0:
            durs = [int(r["duration_ms"] or 0) for r in rows
                    if "duration_ms" in r.keys() and r["duration_ms"]]
            avg_s = (sum(durs) / len(durs)) / 1000.0 if durs else 0.0
        else:
            avg_s = 0.0
        self._results.set_data(count, avg_s)
        self._refresh_action_states()

    # ── Element CRUD (in-memory, atomic save on OK) ─────────────────────

    def _build_element_from_filters(self) -> dict:
        """Construct a new element dict from the current filter UI state."""
        ui_type = self._lib.element_type()
        fdict = self._lib.filter_state()
        cat_id = fdict.get("category_id")
        # Estimate duration from filter result avg if available, else default
        try:
            cnt_text = ""    # (the results card has _avg_s privately)
            avg_s = float(self._results._avg_s) if hasattr(
                self._results, "_avg_s") else 0.0
        except Exception:
            avg_s = 0.0
        if avg_s <= 0.0:
            avg_s = float(DEFAULT_DURATION_S.get(ui_type, 240))
        cat_color = None
        if cat_id is not None:
            for c in self._categories_cache:
                if int(c["id"]) == int(cat_id):
                    cat_color = c.get("color"); break
        # Minute position = end of last element. Mirrors the face's
        # running-minute layout so sequential elements (minute_position
        # None — see _slots_to_elements) chain instead of counting as 0.
        next_min = 0.0
        running = 0.0
        for e in self._elements:
            mp = e.get("minute_position")
            start = float(mp) if mp is not None else running
            ds = e.get("duration_seconds") or 0
            running = start + float(ds) / 60.0
            next_min = max(next_min, running)
        # Sweeper / Jingle slots can be pinned to a specific row from
        # the corresponding library or left as random_from_category.
        # The picker dropdowns only show for matching element_type;
        # other types ignore them.
        sweeper_id = None
        sweeper_position = None
        jingle_id = None
        item_id = None
        selection_mode = "random_from_category"
        if ui_type == "sweeper":
            sweeper_id = self._lib.selected_sweeper_id()
            sweeper_position = self._lib.selected_sweeper_position()
            if sweeper_id is not None:
                item_id = sweeper_id
                selection_mode = "specific"
        elif ui_type == "jingle":
            jingle_id = self._lib.selected_jingle_id()
            if jingle_id is not None:
                item_id = jingle_id
                selection_mode = "specific"
        return {
            "element_type":     ui_type,
            "slot_type_db":     ELEMENT_TYPE_TO_DB[ui_type],
            "category_id":      cat_id,
            "category_color":   cat_color,
            "filter_json":      {k: v for k, v in fdict.items()
                                 if k != "category_id"},
            "minute_position":  int(min(59.0, next_min)),
            "duration_seconds": int(avg_s),
            "selection_mode":   selection_mode,
            "item_id":          item_id,
            "sweeper_position": sweeper_position,
            "era":              fdict.get("era"),
        }

    def _on_add(self) -> None:
        el = self._build_element_from_filters()
        self._elements.append(el)
        self._on_dirty()
        self._editor.face().set_elements(self._elements)
        self._editor.face().set_selected(len(self._elements) - 1)
        self._sync_contents_list()
        self._refresh_action_states()
        self._update_status_bar()

    def _on_insert(self) -> None:
        idx = self._editor.face().selected_idx()
        if idx is None:
            return
        el = self._build_element_from_filters()
        self._elements.insert(idx, el)
        self._on_dirty()
        self._editor.face().set_elements(self._elements)
        self._editor.face().set_selected(idx)
        self._sync_contents_list()
        self._refresh_action_states()
        self._update_status_bar()

    def _on_replace(self) -> None:
        idx = self._editor.face().selected_idx()
        if idx is None or idx >= len(self._elements):
            return
        el = self._build_element_from_filters()
        # Preserve the existing minute_position so the swap is in-place
        el["minute_position"] = self._elements[idx].get("minute_position", 0)
        self._elements[idx] = el
        self._on_dirty()
        self._editor.face().set_elements(self._elements)
        self._editor.face().set_selected(idx)
        self._sync_contents_list()
        self._refresh_action_states()
        self._update_status_bar()

    def _on_delete(self) -> None:
        idx = self._editor.face().selected_idx()
        if idx is None or idx >= len(self._elements):
            return
        del self._elements[idx]
        self._on_dirty()
        self._editor.face().set_elements(self._elements)
        new_idx = idx if idx < len(self._elements) else None
        self._editor.face().set_selected(new_idx)
        self._sync_contents_list()
        self._refresh_action_states()
        self._update_status_bar()

    def _on_face_element_clicked(self, idx: int) -> None:
        # idx == -1 means clicked empty area
        self._editor.contents_list().set_selected(idx if idx >= 0 else None)
        self._refresh_action_states()
        self._update_status_bar()

    def _on_content_row_clicked(self, idx: int) -> None:
        """Play-order list row click → select the matching face arc."""
        if idx < 0 or idx >= len(self._elements):
            return
        self._editor.face().set_selected(idx)
        self._editor.contents_list().set_selected(idx)
        self._refresh_action_states()

    # ── Play-order list (task B, 2026-07-09) ────────────────────────────

    def _sync_contents_list(self) -> None:
        """Rebuild the readable play-order list from the element list and
        mirror the face's current selection. Display-only."""
        lst = self._editor.contents_list()
        lst.set_rows(self._content_rows())
        lst.set_selected(self._editor.face().selected_idx())

    def _content_rows(self) -> list[dict]:
        rows: list[dict] = []
        for el in self._elements:
            t = el.get("element_type") or "song"
            title = ELEMENT_TYPE_LABELS.get(t, t.title())
            color = ELEMENT_TYPE_COLORS.get(t, COL_AMBER_LT)
            if t == "song":
                sub = self._category_display_name(el) or "Any song"
            elif t in ("jingle", "sweeper"):
                if (el.get("selection_mode") or "") == "specific" \
                        and el.get("item_id"):
                    sub = self._item_display_name(t, int(el["item_id"])) \
                          or "Pinned"
                else:
                    sub = "Random"
            elif t == "spot":
                sub = "Commercial break"
            elif t == "voice":
                sub = str(el.get("ref_text") or "Voice track")
            else:
                sub = ""
            rows.append({"title": title, "sub": sub, "color": color})
        return rows

    def _category_display_name(self, el: dict) -> Optional[str]:
        cid = el.get("category_id")
        if cid is None:
            return None
        for c in self._categories_cache:
            if int(c["id"]) == int(cid):
                return str(c["name"])
        # Cache miss (e.g. category renamed mid-session) — the load JOIN
        # already gave us the name; last resort one exact-id SELECT.
        if el.get("cat_name"):
            return str(el["cat_name"])
        try:
            row = self._db.get_category(int(cid))
            return str(row["name"]) if row is not None else None
        except Exception:
            return None

    def _item_display_name(self, ui_type: str, item_id: int) -> Optional[str]:
        """Name of a pinned sweeper/jingle. Read-only exact-id SELECT."""
        table = "sweepers" if ui_type == "sweeper" else "jingles"
        try:
            row = self._db._conn().execute(
                f"SELECT name FROM {table} WHERE id = ?", [int(item_id)]
            ).fetchone()
            return str(row["name"]) if row is not None else None
        except Exception:
            return None

    # ── Status bar / button-state sync ──────────────────────────────────

    def _refresh_action_states(self) -> None:
        # ADD: enabled when there's at least 1 song in the filter result
        # AND the clock has room (current total <60 min).
        cur_total_min = sum(
            (e.get("duration_seconds") or 0) / 60.0 for e in self._elements)
        room = cur_total_min < 60.0
        # We need the filter count — read from the FilterResultsCard
        try:
            count = int(self._results._count)
        except Exception:
            count = 0
        # For non-song types, count check is skipped (a Spot doesn't depend
        # on song-filter availability; UI keeps + ADD enabled).
        ui_type = self._lib.element_type()
        if ui_type == "song":
            add_on = (count > 0) and room
        else:
            add_on = room
        has_sel = self._editor.face().selected_idx() is not None
        self._actions.set_states(add_on, has_sel)

    def _update_status_bar(self) -> None:
        if not self._elements:
            self._editor.set_status("ok", "No Errors Found")
            return
        total_min = sum(
            (e.get("duration_seconds") or 0) / 60.0 for e in self._elements)
        if total_min > 60:
            over = total_min - 60
            self._editor.set_status(
                "warn", f"Clock total {total_min:.1f}m exceeds 60m by "
                f"{over:.1f}m — last elements may be cut")
        elif total_min < 50:
            self._editor.set_status(
                "warn", f"Clock fill {total_min:.1f}m — under 50m, "
                "scheduler may loop early")
        else:
            self._editor.set_status("ok", "No Errors Found")

    # ── State change helpers ────────────────────────────────────────────

    def _on_dirty(self, *_args) -> None:
        if self._is_loading:
            return
        if not self._dirty:
            self._dirty = True

    def _on_name_changed(self, _txt: str) -> None:
        self._on_dirty()

    def _on_type_changed(self, _t: str) -> None:
        self._refresh_action_states()
        self._refresh_filter_results()

    def _on_subtab_changed(self, _key: str) -> None:
        # Only Filters tab affects results count
        self._refresh_filter_results()

    def _on_colorize_changed(self, _mode: str) -> None:
        try:
            self._db.set_setting(
                SETTINGS_KEY_COLORIZE_BY, self._editor.colorize_by())
        except Exception:
            pass

    def _on_backup_clicked(self) -> None:
        dialogs.info(
            self, "Backup Song Filter",
            "Filter picker — coming soon.\n\n"
            "For now the clock's backup filter is recorded as "
            "'Random song · No Filter'.")

    # ── Save / Cancel ───────────────────────────────────────────────────

    def _validate_for_save(self) -> Optional[str]:
        name = self._meta.name()
        if not name:
            return "Clock name cannot be empty."
        if not self._elements:
            return ("Clock must have at least one element. "
                    "Use + ADD to insert one.")
        return None

    def _on_ok(self) -> None:
        err = self._validate_for_save()
        if err:
            self._editor.set_status("error", err)
            dialogs.warning(self, "Cannot save", err)
            return
        new_id = self._save()
        if new_id is None:
            return
        self.saved.emit(int(new_id))
        self._dirty = False
        self.screen_requested.emit("main_auto_schedule")

    def _save(self) -> Optional[int]:
        """Persist the in-memory state. Returns the (new) clock id, or
        None on failure."""
        meta_payload = {
            "name":                   self._meta.name(),
            "comments":               self._meta.comments(),
            "color":                  self._meta.color(),
            "backup_song_filter":     None,    # picker out of scope
            "loop_cycle_enabled":     1 if self._editor.loop() else 0,
            "show_only_descriptions": 1 if self._editor.show_only_descriptions() else 0,
        }
        if self._mode == MODE_EDIT and self._source_id is not None:
            target_id = int(self._source_id)
            try:
                self._db.save_clock(target_id, meta_payload)
            except Exception as exc:
                log.warning(f"save_clock failed: {exc}")
                dialogs.warning(self, "Save failed", str(exc))
                return None
        else:
            # NEW or DUPLICATE — create a fresh row, then save the rest.
            try:
                target_id = int(self._db.create_clock(meta_payload["name"]))
                self._db.save_clock(target_id, meta_payload)
            except Exception as exc:
                log.warning(f"create_clock failed: {exc}")
                dialogs.warning(self, "Save failed", str(exc))
                return None
        # Slots — atomic replace
        slots = self._elements_to_slot_payload(self._elements)
        try:
            self._db.save_clock_slots(target_id, slots)
        except Exception as exc:
            log.warning(f"save_clock_slots failed: {exc}")
            dialogs.warning(self, "Save failed",
                                f"Slot save failed: {exc}")
            return None
        log.info(f"[clock_editor] saved clock {target_id} "
                 f"(mode={self._mode}, elements={len(slots)})")
        return target_id

    @staticmethod
    def _elements_to_slot_payload(elements: list[dict]) -> list[dict]:
        """Project the screen's element dicts into the shape
        ``db.save_clock_slots`` accepts. Renumbers minute_position so the
        sequence packs left-to-right with no gap (consistent with the
        face's visual rendering)."""
        out: list[dict] = []
        running_min = 0.0
        for el in elements:
            ui_type = el.get("element_type") or "song"
            stype_db = ELEMENT_TYPE_TO_DB.get(ui_type, "song")
            dur_s = int(el.get("duration_seconds") or
                        DEFAULT_DURATION_S.get(ui_type, 240))
            mp = int(round(running_min))
            running_min += dur_s / 60.0
            fj = el.get("filter_json") or {}
            slot: dict = {
                "slot_type":         stype_db,
                "category_id":       el.get("category_id"),
                "duration_seconds":  dur_s,
                "minute_position":   mp,
                "filter_json":       json.dumps(fj),
                "selection_mode":    el.get("selection_mode")
                                     or "random_from_category",
                "is_break":          1 if stype_db == "break" else 0,
            }
            # Sweeper-specific columns — only forwarded when the element
            # actually carries them so non-sweeper rows get NULL columns
            # (matches the existing schema default).
            if el.get("item_id") is not None:
                slot["item_id"] = int(el["item_id"])
            if el.get("sweeper_position"):
                slot["sweeper_position"] = el["sweeper_position"]
            out.append(slot)
        return out

    def _on_cancel(self) -> None:
        self._cancel_then_route("main_auto_schedule")

    def _cancel_then_route(self, route: str) -> None:
        if self._dirty:
            if not dialogs.confirm(
                    self, "Discard changes?",
                    "You have unsaved changes. Discard and leave "
                    "the editor?",
                    danger=True, yes_label="Discard"):
                return
        self._dirty = False
        self.screen_requested.emit(route)

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
        crumb = "SCHEDULING  /  CLOCKS  /  " + (
            "EDIT" if self._mode == MODE_EDIT else "NEW")
        title = ("Edit Clock" if self._mode == MODE_EDIT
                 else "Create New Clock")
        p.setPen(QColor(COL_TEXT_DIM)); p.setFont(self._font_breadcrumb)
        p.drawText(QRectF(56, 116, 600, 13),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   crumb)
        p.setPen(QColor(COL_TEXT_PRIMARY)); p.setFont(self._font_title)
        p.drawText(QRectF(56, 138, 900, 50),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   title)
        p.setPen(QColor(COL_TEXT_SECONDARY)); p.setFont(self._font_subtitle)
        p.drawText(QRectF(56, 188, 900, 17),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "Define a clock — set elements, filters, and "
                   "categories for rotation")
        p.end()
