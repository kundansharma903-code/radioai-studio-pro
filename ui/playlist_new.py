"""
RadioAI Studio Pro — Create New Playlist (Figma 243:2 — Premium Dark).

Sub-screen of the Playlists screen. Lets the operator pick songs from
the library, drag them into a queue, set metadata (name / type / color /
tags / cover) and save as a real playlist. Auto-saves a draft 1500ms
after each change so navigation away never loses work.

Layout (1440×900)
-----------------
  HEADER (reused from chrome)        y=  0..88
  Title block + breadcrumb            y=110..211
  Cancel / Save buttons               y=144..188
  Meta form strip (1328×116)          y=226..342
  Library browser (760×484, x=56)     y=360..844
  Playlist builder (540×484, x=844)   y=360..844
  Footer hairline + version row       y=856 / y=872

Engine wiring
-------------
- showEvent → ensure draft exists, populate library page
- Search input: 200ms QTimer single-shot debouncer
- Page flip / filter change → re-query db.search_songs(...)
- + ADD: append song_id to _queue_ids, library row paints ✓ ADDED
- × Remove: pop from _queue_ids, library row reverts to + ADD
- Drag-reorder: QAbstractListModel + moveRows() — no full list
  recreation, repaints only the swapped rows
- Auto-save: any meta/queue change → _dirty=True, restart 1500ms QTimer.
  Tick: db.update_playlist_draft + db.replace_playlist_songs.
- Save Playlist: commit_playlist_draft + (optional) scheduler register
  + emit screen_requested("playlists")
- Cancel with _dirty: confirm dialog → delete_playlist_draft + back

Performance
-----------
- event.rect() clipping in custom paintEvents
- mouseMoveEvent uses self.update(QRect)
- All gradients/colors/fonts cached in __init__
- Library shows at most 10 rows at a time — re-bound on page flip,
  not recreated. Total DB load per page = 1 SELECT ... LIMIT 10 OFFSET N.
"""

from __future__ import annotations

import logging
import time
from typing import Optional
from core import dialogs

from PyQt6.QtCore import (
    Qt, QRect, QRectF, QPointF, QSize, QTimer, QModelIndex,
    QAbstractListModel, QMimeData, pyqtSignal,
)
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QLinearGradient, QFont, QCursor,
    QMouseEvent, QPainterPath, QDrag,
)
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLineEdit, QPushButton, QComboBox, QMessageBox,
    QFileDialog, QListView, QStyledItemDelegate, QAbstractItemView,
    QStyleOptionViewItem,
)

from ui.widgets.tokens import (
    inter, mono,
    COL_BG_TOP, COL_BG_MID, COL_BG_BOT,
    COL_BORDER_FAINT,
    COL_CYAN, COL_CYAN_LT, COL_CYAN_DK, COL_CYAN_MD,
    COL_PURPLE, COL_PURPLE_LT, COL_PURPLE_DEEP,
    COL_GREEN, COL_GREEN_LT, COL_GREEN_DK,
    COL_AMBER, COL_AMBER_LT, COL_AMBER_DK,
    COL_ROSE, COL_ROSE_LT,
    COL_PINK, COL_PINK_DK,
    COL_TEAL, COL_TEAL_LT,
    COL_TEXT_PRIMARY, COL_TEXT_SECONDARY, COL_TEXT_MUTED, COL_TEXT_DIM,
    qcolor_a as _qcolor,
)
from ui.widgets.app_chrome import (
    Header, drop_shadow,
    WINDOW_W, HEADER_H,
)

log = logging.getLogger("PlaylistNew")

WINDOW_H = 900

# 6-color palette for the metadata "COLOR" picker (matches Figma 244:17..22)
COLOR_SWATCHES: tuple[str, ...] = (
    COL_CYAN, COL_PURPLE, COL_GREEN, COL_AMBER, COL_ROSE, COL_PINK,
)


# ── Helpers ─────────────────────────────────────────────────────────────


def _fmt_duration(ms: int) -> str:
    """ms → 'M:SS' or 'H:MM:SS'."""
    s = max(0, int(ms or 0)) // 1000
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def _fmt_track_total(total_ms: int) -> str:
    """Stat display — '14:28'."""
    s = max(0, int(total_ms or 0)) // 1000
    m, sec = divmod(s, 60)
    return f"{m}:{sec:02d}"


# ════════════════════════════════════════════════════════════════════════
# CANCEL / SAVE ACTION BUTTONS
# ════════════════════════════════════════════════════════════════════════

class _CancelButton(QWidget):
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(110, 44)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._hover = False
        self._font = inter(13, QFont.Weight.DemiBold, letter_spacing=-0.1)

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
        path.addRoundedRect(QRectF(0, 0, 110, 44), 12, 12)
        bg = QColor(14, 16, 32, int(0.85 * 255))
        if self._hover:
            bg = QColor(20, 22, 40, int(0.92 * 255))
        p.setBrush(bg)
        p.setPen(QPen(COL_BORDER_FAINT, 1))
        p.drawPath(path)
        p.setPen(QColor(COL_TEXT_SECONDARY if not self._hover else COL_TEXT_PRIMARY))
        p.setFont(self._font)
        p.drawText(QRectF(0, 0, 110, 44), Qt.AlignmentFlag.AlignCenter, "Cancel")


class _SaveButton(QWidget):
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(150, 44)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._hover = False
        self.setGraphicsEffect(drop_shadow(20, _qcolor("#7c3aed", 0.45), dy=6))

        g = QLinearGradient(0, 0, 150, 44)
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
        path.addRoundedRect(QRectF(0, 0, 150, 44), 12, 12)
        p.fillPath(path, QBrush(self._grad))
        if self._hover:
            p.fillPath(path, QColor(255, 255, 255, int(0.06 * 255)))
        p.setClipPath(path)
        p.fillRect(QRectF(1, 1, 148, 18), QBrush(self._highlight))
        p.setClipping(False)
        p.setPen(QColor("#ffffff"))
        p.setFont(self._font)
        p.drawText(QRectF(0, 0, 150, 44),
                   Qt.AlignmentFlag.AlignCenter, "✓ Save Playlist")


# ════════════════════════════════════════════════════════════════════════
# META FORM STRIP — cover + name + type + color + tags
# ════════════════════════════════════════════════════════════════════════

class _CoverPicker(QWidget):
    cover_picked = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(86, 86)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._hover = False
        self._cover_path: Optional[str] = None

        self._font_plus = inter(28, QFont.Weight.Black)
        self._font_lbl  = inter(8, QFont.Weight.Bold, letter_spacing=1.4)

    def set_cover_path(self, p: Optional[str]) -> None:
        self._cover_path = p
        self.update(self.rect())

    def enterEvent(self, e):
        self._hover = True; self.update(self.rect())

    def leaveEvent(self, e):
        self._hover = False; self.update(self.rect())

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            path, _ = QFileDialog.getOpenFileName(
                self, "Pick a cover image", "",
                "Images (*.png *.jpg *.jpeg)")
            if path:
                self._cover_path = path
                self.cover_picked.emit(path)
                self.update(self.rect())

    def paintEvent(self, evt):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, 86, 86), 14, 14)
        # Body fill
        if self._cover_path:
            p.fillPath(path, _qcolor(COL_CYAN, 0.20))
        else:
            p.fillPath(path, QColor(20, 22, 40, int(0.50 * 255)))
        # Dashed border
        pen = QPen(QColor(COL_TEXT_MUTED), 1.5, Qt.PenStyle.DashLine)
        if self._hover:
            pen = QPen(QColor(COL_CYAN_LT), 1.5, Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        # Centre glyph + label
        if self._cover_path:
            p.setPen(QColor(COL_CYAN_LT))
            p.setFont(inter(11, QFont.Weight.Bold))
            p.drawText(QRectF(rect), Qt.AlignmentFlag.AlignCenter, "✓ Cover")
        else:
            p.setPen(QColor(COL_TEXT_MUTED if not self._hover else COL_CYAN_LT))
            p.setFont(self._font_plus)
            p.drawText(QRectF(0, 12, 86, 36),
                       Qt.AlignmentFlag.AlignCenter, "+")
            p.setPen(QColor(COL_TEXT_MUTED if not self._hover else COL_CYAN_LT))
            p.setFont(self._font_lbl)
            p.drawText(QRectF(0, 56, 86, 18),
                       Qt.AlignmentFlag.AlignCenter, "ADD COVER")


class _NameInput(QFrame):
    name_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(560, 44)
        self._line = QLineEdit(self)
        self._line.setGeometry(14, 8, 540, 28)
        self._line.setPlaceholderText("Untitled Playlist")
        self._line.setFont(inter(15, QFont.Weight.DemiBold))
        self._line.setStyleSheet(
            f"QLineEdit {{ background: transparent; "
            f"color: {COL_TEXT_PRIMARY}; "
            f"border: none; padding: 0; }}"
        )
        self._line.textChanged.connect(self.name_changed.emit)

    def text(self) -> str:
        return self._line.text().strip()

    def set_text(self, t: str) -> None:
        self._line.setText(t)

    def paintEvent(self, evt):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, 560, 44), 12, 12)
        p.setBrush(QColor(20, 22, 40, int(0.85 * 255)))
        focused = self._line.hasFocus()
        if focused:
            p.setPen(QPen(_qcolor(COL_CYAN, 0.55), 1.5))
        else:
            p.setPen(QPen(COL_BORDER_FAINT, 1))
        p.drawPath(path)


class _TypeDropdown(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(180, 44)
        self.setFont(inter(13, QFont.Weight.DemiBold))
        for k, label in (("manual", "Manual"),
                         ("imported", "Imported"),
                         ("smart", "Smart")):
            self.addItem(label, userData=k)
        self.setStyleSheet(
            f"QComboBox {{ background: rgba(20,22,40,0.85); "
            f"color: {COL_TEXT_PRIMARY}; "
            f"border: 1px solid rgba(255,255,255,0.06); "
            f"border-radius: 12px; padding: 0 14px; }}"
            f"QComboBox:hover {{ border-color: rgba(6,182,212,0.40); }}"
            f"QComboBox::drop-down {{ border: none; width: 22px; }}"
            f"QComboBox QAbstractItemView {{ background: #0e1020; "
            f"color: {COL_TEXT_PRIMARY}; "
            f"selection-background-color: rgba(6,182,212,0.20); "
            f"border: 1px solid rgba(255,255,255,0.08); }}"
        )

    def kind(self) -> str:
        return str(self.currentData() or "manual")

    def set_kind(self, k: str) -> None:
        for i in range(self.count()):
            if self.itemData(i) == k:
                self.setCurrentIndex(i); return


class _ColorSwatchRow(QWidget):
    color_changed = pyqtSignal(str)

    SIZE = 28
    GAP = 4

    def __init__(self, parent=None):
        super().__init__(parent)
        n = len(COLOR_SWATCHES)
        self.setFixedSize(n * self.SIZE + (n - 1) * self.GAP, self.SIZE)
        self._color: str = COLOR_SWATCHES[0]
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

    def color(self) -> str:
        return self._color

    def set_color(self, hex_color: str) -> None:
        if hex_color in COLOR_SWATCHES and hex_color != self._color:
            self._color = hex_color
            self.update(self.rect())

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() != Qt.MouseButton.LeftButton:
            return
        for i, hex_color in enumerate(COLOR_SWATCHES):
            x = i * (self.SIZE + self.GAP)
            r = QRect(x, 0, self.SIZE, self.SIZE)
            if r.contains(e.pos()):
                if hex_color != self._color:
                    self._color = hex_color
                    self.update(self.rect())
                    self.color_changed.emit(hex_color)
                return

    def paintEvent(self, evt):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        for i, hex_color in enumerate(COLOR_SWATCHES):
            x = i * (self.SIZE + self.GAP)
            rect = QRectF(x, 0, self.SIZE, self.SIZE)
            p.setBrush(QColor(hex_color))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(rect)
            if hex_color == self._color:
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(QColor("#ffffff"), 2))
                p.drawEllipse(rect.adjusted(-2, -2, 2, 2))


class _TagInput(QFrame):
    tags_changed = pyqtSignal(str)    # comma-separated string

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(208, 44)
        self._line = QLineEdit(self)
        self._line.setGeometry(14, 8, 188, 28)
        self._line.setPlaceholderText("morning, energy, drive…")
        self._line.setFont(inter(12, QFont.Weight.Medium))
        self._line.setStyleSheet(
            f"QLineEdit {{ background: transparent; "
            f"color: {COL_TEXT_PRIMARY}; border: none; padding: 0; }}")
        self._line.textChanged.connect(self._on_changed)

    def _on_changed(self, _t: str):
        # Normalize: trim each token, drop empties, rejoin
        toks = [t.strip() for t in self._line.text().split(",")]
        toks = [t for t in toks if t]
        self.tags_changed.emit(", ".join(toks))

    def tags(self) -> str:
        toks = [t.strip() for t in self._line.text().split(",")]
        toks = [t for t in toks if t]
        return ", ".join(toks)

    def set_tags(self, t: str) -> None:
        self._line.setText(t or "")

    def paintEvent(self, evt):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, 208, 44), 12, 12)
        p.setBrush(QColor(20, 22, 40, int(0.85 * 255)))
        focused = self._line.hasFocus()
        if focused:
            p.setPen(QPen(_qcolor(COL_CYAN, 0.45), 1.5))
        else:
            p.setPen(QPen(COL_BORDER_FAINT, 1))
        p.drawPath(path)


class _MetaFormStrip(QFrame):
    """1328×116 strip housing the cover, name, type, color, tags inputs.
    Emits a unified `meta_changed(dict)` whenever any sub-field changes."""

    meta_changed = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(1328, 116)
        self.setGraphicsEffect(drop_shadow(24, QColor(0, 0, 0, int(0.40 * 255)), dy=10))

        # Body gradient
        g_body = QLinearGradient(0, 0, 0, 116)
        g_body.setColorAt(0.0, QColor(14, 16, 32, int(0.95 * 255)))
        g_body.setColorAt(1.0, QColor(7, 9, 18,  int(0.95 * 255)))
        self._grad_body = g_body
        # Top accent rainbow
        g_top = QLinearGradient(0, 0, 1328, 0)
        g_top.setColorAt(0.0, QColor(COL_CYAN))
        g_top.setColorAt(0.5, QColor(COL_PURPLE))
        g_top.setColorAt(1.0, QColor(COL_PINK))
        self._grad_top = g_top

        self._font_label = inter(8, QFont.Weight.Bold, letter_spacing=1.5)

        # Children — positioned per Figma metadata
        self._cover = _CoverPicker(self); self._cover.move(18, 15)
        self._name  = _NameInput(self);   self._name.move(122, 32)
        self._type  = _TypeDropdown(self); self._type.move(698, 32)
        self._color = _ColorSwatchRow(self); self._color.move(894, 44)
        self._tags  = _TagInput(self);    self._tags.move(1102, 32)

        # Wire change signals → unified emitter
        self._name.name_changed.connect(lambda _t: self._emit())
        self._type.currentIndexChanged.connect(lambda _i: self._emit())
        self._color.color_changed.connect(lambda _c: self._emit())
        self._tags.tags_changed.connect(lambda _t: self._emit())
        self._cover.cover_picked.connect(lambda _p: self._emit())

    def _emit(self):
        self.meta_changed.emit(self.data())

    def data(self) -> dict:
        return {
            "name":       self._name.text() or "Untitled Playlist",
            "kind":       self._type.kind(),
            "color":      self._color.color(),
            "tags":       self._tags.tags(),
            "cover_path": self._cover._cover_path,
        }

    def set_data(self, d: dict) -> None:
        if "name" in d:        self._name.set_text(d["name"] or "")
        if "kind" in d:        self._type.set_kind(d.get("kind") or "manual")
        if "color" in d:       self._color.set_color(d.get("color") or COL_CYAN)
        if "tags" in d:        self._tags.set_tags(d.get("tags") or "")
        if "cover_path" in d:  self._cover.set_cover_path(d.get("cover_path"))

    def paintEvent(self, evt):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, 1328, 116), 16, 16)
        p.fillPath(path, QBrush(self._grad_body))
        p.setPen(QPen(COL_BORDER_FAINT, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        p.setClipPath(path)
        p.fillRect(QRectF(0, 0, 1328, 3), QBrush(self._grad_top))
        p.fillRect(QRectF(0, 2, 1328, 1),
                   QColor(255, 255, 255, int(0.04 * 255)))
        p.setClipping(False)
        # Section labels
        p.setPen(QColor(COL_TEXT_MUTED))
        p.setFont(self._font_label)
        for label, x in (("PLAYLIST NAME", 122),
                         ("TYPE",          698),
                         ("COLOR",         894),
                         ("TAGS (OPTIONAL)", 1102)):
            p.drawText(QRectF(x, 18, 200, 12),
                       Qt.AlignmentFlag.AlignLeft, label)


# ════════════════════════════════════════════════════════════════════════
# LIBRARY — search box + chips + filters + 10-row table + pagination
# ════════════════════════════════════════════════════════════════════════

class _SearchBox(QFrame):
    text_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(720, 38)
        self._line = QLineEdit(self)
        self._line.setGeometry(36, 6, 680, 26)
        self._line.setPlaceholderText("Search title, artist, album, year, BPM…")
        self._line.setFont(inter(12, QFont.Weight.Medium))
        self._line.setStyleSheet(
            f"QLineEdit {{ background: transparent; "
            f"color: {COL_TEXT_PRIMARY}; border: none; padding: 0; }}")

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(200)
        self._debounce.timeout.connect(
            lambda: self.text_changed.emit(self._line.text().strip()))
        self._line.textChanged.connect(lambda _t: self._debounce.start())

        self._font_glyph = inter(15, QFont.Weight.Bold)

    def text(self) -> str:
        return self._line.text().strip()

    def paintEvent(self, evt):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, 720, 38), 10, 10)
        p.setBrush(QColor(14, 16, 32, int(0.85 * 255)))
        p.setPen(QPen(COL_BORDER_FAINT, 1))
        p.drawPath(path)
        p.setPen(QColor(COL_TEXT_MUTED))
        p.setFont(self._font_glyph)
        p.drawText(QRectF(10, 0, 22, 38),
                   Qt.AlignmentFlag.AlignCenter, "⌕")


class _CategoryChip(QWidget):
    clicked = pyqtSignal(object)    # category_id (None for "All Songs")

    def __init__(self, label: str, count: int,
                 cat_id: Optional[int], width: int = 124, parent=None):
        super().__init__(parent)
        self._label = label
        self._count = int(count)
        self._cat_id = cat_id
        self._active = False
        self.setFixedSize(width, 28)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        self._font_lbl   = inter(11, QFont.Weight.Bold, letter_spacing=0.2)
        self._font_count = inter(10, QFont.Weight.Black)

    def set_active(self, on: bool) -> None:
        if on != self._active:
            self._active = on
            self.update(self.rect())

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._cat_id)

    def paintEvent(self, evt):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, self.width(), 28), 14, 14)
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
        p.setFont(self._font_lbl)
        p.drawText(QRectF(12, 7, self.width() - 60, 16),
                   Qt.AlignmentFlag.AlignLeft, self._label)
        # Count
        p.setPen(QColor(COL_CYAN_LT if self._active else COL_TEXT_MUTED))
        p.setFont(self._font_count)
        p.drawText(QRectF(self.width() - 50, 7, 38, 16),
                   Qt.AlignmentFlag.AlignRight, f"{self._count:,}")


class _LibraryFilterBar(QWidget):
    """BPM range + Year + Sort dropdowns + 'Showing N results' label."""

    filters_changed = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(720, 32)

        self._bpm = self._make_combo(160, [
            ("BPM ALL",     (None, None)),
            ("BPM 60–90",   (60, 90)),
            ("BPM 90–110",  (90, 110)),
            ("BPM 110–130", (110, 130)),
            ("BPM 130–150", (130, 150)),
            ("BPM 150+",    (150, None)),
        ])
        self._bpm.move(0, 1)
        self._year = self._make_combo(160, [
            ("YEAR ANY",      (None, None)),
            ("YEAR <2000",    (None, 1999)),
            ("YEAR 2000–10",  (2000, 2010)),
            ("YEAR 2010–20",  (2010, 2020)),
            ("YEAR 2020+",    (2020, None)),
        ])
        self._year.move(168, 1)
        self._sort = self._make_combo(160, [
            ("SORT RECENT", "recent"),
            ("SORT A–Z",    "az"),
            ("SORT BPM",    "bpm"),
        ])
        self._sort.move(336, 1)

        self._results_count = 0
        self._font_count = inter(11, QFont.Weight.DemiBold)

        for cb in (self._bpm, self._year, self._sort):
            cb.currentIndexChanged.connect(lambda _i: self.filters_changed.emit(self.data()))

    @staticmethod
    def _make_combo(width: int, options: list) -> QComboBox:
        cb = QComboBox()
        cb.setFixedSize(width, 30)
        cb.setFont(inter(10, QFont.Weight.Bold, letter_spacing=0.6))
        cb.setStyleSheet(
            f"QComboBox {{ background: rgba(14,16,32,0.85); "
            f"color: {COL_TEXT_SECONDARY}; "
            f"border: 1px solid rgba(255,255,255,0.06); "
            f"border-radius: 6px; padding: 0 12px; }}"
            f"QComboBox:hover {{ border-color: rgba(6,182,212,0.30); "
            f"color: {COL_TEXT_PRIMARY}; }}"
            f"QComboBox::drop-down {{ border: none; width: 18px; }}"
            f"QComboBox QAbstractItemView {{ background: #0e1020; "
            f"color: {COL_TEXT_PRIMARY}; "
            f"selection-background-color: rgba(6,182,212,0.20); }}"
        )
        for label, val in options:
            cb.addItem(label, userData=val)
        return cb

    def set_results_count(self, n: int) -> None:
        if n != self._results_count:
            self._results_count = int(n)
            self.update(QRect(540, 0, 180, 32))

    def data(self) -> dict:
        bpm_min, bpm_max = self._bpm.currentData()
        year_min, year_max = self._year.currentData()
        return {
            "bpm_min": bpm_min, "bpm_max": bpm_max,
            "year_min": year_min, "year_max": year_max,
            "sort": self._sort.currentData() or "recent",
        }

    def paintEvent(self, evt):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QColor(COL_TEXT_MUTED))
        p.setFont(self._font_count)
        p.drawText(QRectF(540, 8, 180, 16),
                   Qt.AlignmentFlag.AlignRight,
                   f"Showing {self._results_count:,} results")


class _LibraryRow(QWidget):
    """One song row — 720×22. Click anywhere → row clicked. + ADD button
    flips to ✓ ADDED when the song is in the queue."""

    add_clicked = pyqtSignal(int)    # song id

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(720, 22)
        self.setMouseTracking(False)
        self._row: dict = {}
        self._rank: int = 1
        self._is_added: bool = False
        self._hover_btn: bool = False

        self._font_idx     = mono(11, bold=True)
        self._font_title   = inter(12, QFont.Weight.Bold, letter_spacing=-0.1)
        self._font_artist  = inter(12, QFont.Weight.Medium)
        self._font_meta    = mono(11, bold=True)
        self._font_btn     = inter(10, QFont.Weight.Bold, letter_spacing=0.2)

    def set_data(self, row: dict, rank: int, is_added: bool) -> None:
        self._row = dict(row or {})
        self._rank = int(rank)
        self._is_added = bool(is_added)
        self.update(self.rect())

    @property
    def song_id(self) -> int:
        return int(self._row.get("id") or 0)

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() != Qt.MouseButton.LeftButton:
            return
        # + ADD / ✓ ADDED button hit-test (50×18 at x=656, y=2)
        if QRect(656, 2, 50, 18).contains(e.pos()) and not self._is_added:
            self.add_clicked.emit(self.song_id)

    def enterEvent(self, e):
        # Track whether mouse is over the +ADD button area to highlight it
        # without enabling full mouse tracking (cursor change isn't needed
        # globally, just for the button rect).
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

    def leaveEvent(self, e):
        if self._hover_btn:
            self._hover_btn = False
            self.update(QRect(656, 2, 50, 18))

    def paintEvent(self, evt):
        if not self._row:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Rank
        p.setPen(QColor(COL_TEXT_MUTED))
        p.setFont(self._font_idx)
        p.drawText(QRectF(8, 4, 24, 16),
                   Qt.AlignmentFlag.AlignLeft, f"{self._rank:02d}")
        # Color dot — use category color if known, otherwise cyan
        cat_color = self._row.get("cat_color") or COL_CYAN
        p.setBrush(QColor(cat_color))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(36, 8, 6, 6))
        # Title
        p.setPen(QColor(COL_TEXT_PRIMARY))
        p.setFont(self._font_title)
        title = str(self._row.get("title") or "—")
        p.drawText(QRectF(56, 4, 220, 16),
                   Qt.AlignmentFlag.AlignLeft, title)
        # Artist
        p.setPen(QColor(COL_TEXT_SECONDARY))
        p.setFont(self._font_artist)
        artist = str(self._row.get("artist") or "—")
        p.drawText(QRectF(280, 4, 170, 16),
                   Qt.AlignmentFlag.AlignLeft, artist)
        # Duration
        p.setPen(QColor(COL_TEXT_PRIMARY))
        p.setFont(self._font_meta)
        p.drawText(QRectF(460, 4, 60, 16),
                   Qt.AlignmentFlag.AlignLeft,
                   _fmt_duration(int(self._row.get("duration_ms") or 0)))
        # BPM
        bpm = int(self._row.get("bpm") or 0)
        p.drawText(QRectF(540, 4, 40, 16),
                   Qt.AlignmentFlag.AlignLeft, str(bpm) if bpm else "—")
        # Year
        year = int(self._row.get("year") or 0)
        p.drawText(QRectF(590, 4, 50, 16),
                   Qt.AlignmentFlag.AlignLeft, str(year) if year else "—")
        # +ADD / ✓ADDED button (50×18 at 656, 2)
        path = QPainterPath()
        path.addRoundedRect(QRectF(656, 2, 50, 18), 9, 9)
        if self._is_added:
            p.fillPath(path, _qcolor(COL_GREEN, 0.20))
            p.setPen(QPen(_qcolor(COL_GREEN, 0.45), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
            p.setPen(QColor(COL_GREEN_LT))
            p.setFont(self._font_btn)
            p.drawText(QRectF(656, 2, 50, 18),
                       Qt.AlignmentFlag.AlignCenter, "✓ ADDED")
        else:
            p.fillPath(path, _qcolor(COL_CYAN, 0.18))
            p.setPen(QPen(_qcolor(COL_CYAN, 0.40), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
            p.setPen(QColor(COL_CYAN_LT))
            p.setFont(self._font_btn)
            p.drawText(QRectF(656, 2, 50, 18),
                       Qt.AlignmentFlag.AlignCenter, "+ ADD")


class _LibraryBrowser(QFrame):
    """760×484 panel: search + chips + filters + 10-row table + pagination."""

    add_song = pyqtSignal(int)           # song_id added to queue
    add_all_visible = pyqtSignal(list)    # list of song_ids
    library_state_changed = pyqtSignal()  # bubbles to screen for autosave
    PAGE_SIZE = 10

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.setFixedSize(760, 484)
        self._db = db
        self._added_ids: set[int] = set()
        self._page = 0
        self._total = 0
        self._rows: list[dict] = []
        self._search_text = ""
        self._cat_id: Optional[int] = None
        self._filters: dict = {
            "bpm_min": None, "bpm_max": None,
            "year_min": None, "year_max": None,
            "sort": "recent",
        }
        self.setGraphicsEffect(drop_shadow(24, QColor(0, 0, 0, int(0.40 * 255)), dy=10))

        # Body gradient + amber top accent
        g_body = QLinearGradient(0, 0, 0, 484)
        g_body.setColorAt(0.0, QColor(14, 16, 32, int(0.95 * 255)))
        g_body.setColorAt(1.0, QColor(7, 9, 18,  int(0.95 * 255)))
        self._grad_body = g_body
        g_top = QLinearGradient(0, 0, 760, 0)
        g_top.setColorAt(0.0, QColor(COL_AMBER))
        g_top.setColorAt(1.0, QColor(COL_AMBER_DK))
        self._grad_top = g_top

        self._font_section = inter(11, QFont.Weight.Black, letter_spacing=1.5)
        self._font_total   = inter(13, QFont.Weight.DemiBold)
        self._font_hdr     = inter(10, QFont.Weight.Bold, letter_spacing=1.2)
        self._font_pager   = inter(11, QFont.Weight.DemiBold)

        # Search
        self._search = _SearchBox(self); self._search.move(20, 42)
        self._search.text_changed.connect(self._on_search)

        # Category chips — built lazily once db.get_categories() runs
        self._chips: list[_CategoryChip] = []
        self._build_chips()

        # Filter bar
        self._filterbar = _LibraryFilterBar(self); self._filterbar.move(20, 130)
        self._filterbar.filters_changed.connect(self._on_filters)

        # 10 fixed library rows
        self._row_widgets: list[_LibraryRow] = []
        for i in range(self.PAGE_SIZE):
            r = _LibraryRow(self)
            r.move(20, 208 + i * 22)
            r.add_clicked.connect(self._on_add_song)
            r.hide()
            self._row_widgets.append(r)

        # Pagination buttons (28×22 at x=622/656, y=440)
        self._prev_btn = QPushButton("‹", self); self._prev_btn.setGeometry(622, 444, 28, 22)
        self._next_btn = QPushButton("›", self); self._next_btn.setGeometry(656, 444, 28, 22)
        for b in (self._prev_btn, self._next_btn):
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.setFont(inter(13, QFont.Weight.Bold))
            b.setStyleSheet(
                f"QPushButton {{ background: rgba(14,16,32,0.85); "
                f"color: {COL_TEXT_PRIMARY}; "
                f"border: 1px solid rgba(255,255,255,0.06); "
                f"border-radius: 4px; }}"
                f"QPushButton:hover {{ border-color: rgba(6,182,212,0.40); }}"
                f"QPushButton:disabled {{ color: {COL_TEXT_DIM}; }}"
            )
        self._prev_btn.clicked.connect(self._prev_page)
        self._next_btn.clicked.connect(self._next_page)

        # Initial load
        self.refresh()

    # ── public ──────────────────────────────────────────────────────────

    def set_added_ids(self, ids: set[int]) -> None:
        if ids != self._added_ids:
            self._added_ids = set(ids)
            self._refresh_rows()

    def refresh(self) -> None:
        """Re-query db with current filter state, repaint."""
        try:
            self._total = int(self._db.count_songs(
                query=self._search_text, category_id=self._cat_id,
                bpm_min=self._filters.get("bpm_min"),
                bpm_max=self._filters.get("bpm_max"),
                year_min=self._filters.get("year_min"),
                year_max=self._filters.get("year_max"),
            ))
        except Exception as exc:
            log.warning(f"count_songs failed: {exc}")
            self._total = 0
        # Clamp page if filter shrunk results
        max_page = max(0, (self._total - 1) // self.PAGE_SIZE)
        if self._page > max_page:
            self._page = max_page
        try:
            rows = self._db.search_songs(
                query=self._search_text, category_id=self._cat_id,
                bpm_min=self._filters.get("bpm_min"),
                bpm_max=self._filters.get("bpm_max"),
                year_min=self._filters.get("year_min"),
                year_max=self._filters.get("year_max"),
                sort=self._filters.get("sort", "recent"),
                offset=self._page * self.PAGE_SIZE,
                limit=self.PAGE_SIZE,
            )
            self._rows = [{k: r[k] for k in r.keys()} for r in rows]
        except Exception as exc:
            log.warning(f"search_songs failed: {exc}")
            self._rows = []
        self._filterbar.set_results_count(self._total)
        self._refresh_rows()
        # Pager state
        self._prev_btn.setEnabled(self._page > 0)
        self._next_btn.setEnabled((self._page + 1) * self.PAGE_SIZE < self._total)
        self.update(QRect(540, 440, 180, 22))

    @property
    def visible_song_ids(self) -> list[int]:
        return [int(r.get("id") or 0) for r in self._rows]

    # ── private ─────────────────────────────────────────────────────────

    def _refresh_rows(self) -> None:
        for i, w in enumerate(self._row_widgets):
            if i < len(self._rows):
                rank = self._page * self.PAGE_SIZE + i + 1
                sid = int(self._rows[i].get("id") or 0)
                w.set_data(self._rows[i], rank, is_added=(sid in self._added_ids))
                w.show()
            else:
                w.hide()

    def _build_chips(self) -> None:
        for c in self._chips:
            c.setParent(None); c.deleteLater()
        self._chips.clear()
        try:
            cats = list(self._db.get_categories())
        except Exception:
            cats = []
        total = 0
        try:
            total = int(self._db.count_songs())
        except Exception:
            pass
        # All Songs first
        all_chip = _CategoryChip("All Songs", total, None, width=124, parent=self)
        all_chip.move(20, 92)
        all_chip.set_active(True)
        all_chip.clicked.connect(self._on_chip_clicked)
        self._chips.append(all_chip)
        x = 20 + 132
        for c in cats[:5]:    # show top 5 categories from db
            try:
                count = int(c["song_count"]) if "song_count" in c.keys() else 0
            except Exception:
                count = 0
            try:
                name = c["name"] if "name" in c.keys() else None
            except Exception:
                name = None
            label = str(name or "—")
            # Width grows with label length
            w = max(100, 60 + 8 * len(label) + 30)
            chip = _CategoryChip(label, count, int(c["id"]),
                                 width=w, parent=self)
            chip.move(x, 92)
            chip.clicked.connect(self._on_chip_clicked)
            self._chips.append(chip)
            x += w + 8

    def _on_chip_clicked(self, cat_id: Optional[int]) -> None:
        if cat_id == self._cat_id:
            return
        self._cat_id = cat_id
        for c in self._chips:
            c.set_active(c._cat_id == cat_id)
        self._page = 0
        self.refresh()
        self.library_state_changed.emit()

    def _on_search(self, text: str) -> None:
        if text == self._search_text:
            return
        self._search_text = text
        self._page = 0
        self.refresh()
        self.library_state_changed.emit()

    def _on_filters(self, data: dict) -> None:
        self._filters = dict(data)
        self._page = 0
        self.refresh()
        self.library_state_changed.emit()

    def _prev_page(self) -> None:
        if self._page > 0:
            self._page -= 1
            self.refresh()

    def _next_page(self) -> None:
        if (self._page + 1) * self.PAGE_SIZE < self._total:
            self._page += 1
            self.refresh()

    def _on_add_song(self, song_id: int) -> None:
        if song_id in self._added_ids:
            return
        self._added_ids.add(song_id)
        self.add_song.emit(int(song_id))
        self._refresh_rows()

    # ── paint ─────────────────────────────────────────────────────────

    def paintEvent(self, evt):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, 760, 484), 16, 16)
        p.fillPath(path, QBrush(self._grad_body))
        p.setPen(QPen(COL_BORDER_FAINT, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        p.setClipPath(path)
        p.fillRect(QRectF(0, 0, 760, 3), QBrush(self._grad_top))
        p.fillRect(QRectF(0, 2, 760, 1),
                   QColor(255, 255, 255, int(0.04 * 255)))
        p.setClipping(False)
        # Title + total
        p.setPen(QColor(COL_AMBER))
        p.setFont(self._font_section)
        p.drawText(QRectF(20, 14, 200, 16),
                   Qt.AlignmentFlag.AlignLeft, "MUSIC LIBRARY")
        p.setPen(QColor(COL_TEXT_SECONDARY))
        p.setFont(self._font_total)
        try:
            total = int(self._db.count_songs())
        except Exception:
            total = 0
        p.drawText(QRectF(150, 14, 200, 18),
                   Qt.AlignmentFlag.AlignLeft, f"{total:,} songs")
        # Header row (TITLE | ARTIST | DURATION | BPM | YEAR | ADD)
        p.setPen(QColor(COL_TEXT_MUTED))
        p.setFont(self._font_hdr)
        for label, x in (("TITLE", 56), ("ARTIST", 280),
                         ("DURATION", 460), ("BPM", 540),
                         ("YEAR", 590), ("ADD", 656)):
            p.drawText(QRectF(20 + x - 20, 178, 80, 14),
                       Qt.AlignmentFlag.AlignLeft, label)
        # Page indicator
        max_page = max(0, (self._total - 1) // self.PAGE_SIZE)
        p.setPen(QColor(COL_TEXT_SECONDARY))
        p.setFont(self._font_pager)
        p.drawText(QRectF(540, 444, 80, 22),
                   Qt.AlignmentFlag.AlignLeft,
                   f"Page {self._page + 1} / {max_page + 1}")


# ════════════════════════════════════════════════════════════════════════
# QUEUE — model-view with drag-reorder
# ════════════════════════════════════════════════════════════════════════

class _QueueModel(QAbstractListModel):
    """List of dicts with: id, title, artist, duration_ms.
    Supports drag-internal-move via moveRows()."""

    queue_changed = pyqtSignal()    # emitted on add / remove / move

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tracks: list[dict] = []

    # ── Read API ────────────────────────────────────────────────────

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._tracks)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self._tracks):
            return None
        if role == Qt.ItemDataRole.UserRole:
            return self._tracks[index.row()]
        return None

    def flags(self, index: QModelIndex):
        base = super().flags(index)
        if index.isValid():
            return base | Qt.ItemFlag.ItemIsDragEnabled | Qt.ItemFlag.ItemIsSelectable
        return base | Qt.ItemFlag.ItemIsDropEnabled

    def supportedDropActions(self):
        return Qt.DropAction.MoveAction

    def supportedDragActions(self):
        return Qt.DropAction.MoveAction

    # ── Drag/drop internal-move plumbing ───────────────────────────
    # Qt's default DnD pipeline drives mimeData()/dropMimeData(), never
    # moveRows() directly. We carry the source row in a private mime type
    # and route the drop back through the existing moveRows() so the
    # reorder + queue_changed signal (→ autosave) stay in one place.

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
            dest = parent.row() if parent.isValid() else len(self._tracks)
        else:
            dest = row
        self.moveRows(QModelIndex(), src, 1, QModelIndex(), dest)
        # Always return False: we complete the reorder in-place via
        # moveRows(). Returning True would make QAbstractItemView's
        # InternalMove pipeline call removeRows() on the (now stale)
        # source row afterwards, deleting the wrong track.
        return False

    # ── Mutation API ───────────────────────────────────────────────

    def append_track(self, track: dict) -> None:
        n = len(self._tracks)
        self.beginInsertRows(QModelIndex(), n, n)
        self._tracks.append(dict(track))
        self.endInsertRows()
        self.queue_changed.emit()

    def remove_at(self, row: int) -> Optional[int]:
        """Pops track at row. Returns the song_id removed (for the
        library to flip its button back). None if invalid."""
        if not (0 <= row < len(self._tracks)):
            return None
        sid = int(self._tracks[row].get("id") or 0)
        self.beginRemoveRows(QModelIndex(), row, row)
        del self._tracks[row]
        self.endRemoveRows()
        self.queue_changed.emit()
        return sid

    def clear(self) -> None:
        if not self._tracks:
            return
        self.beginResetModel()
        self._tracks = []
        self.endResetModel()
        self.queue_changed.emit()

    def shuffle(self) -> None:
        if len(self._tracks) <= 1:
            return
        import random
        self.beginResetModel()
        random.shuffle(self._tracks)
        self.endResetModel()
        self.queue_changed.emit()

    def moveRows(self, sourceParent, sourceRow, count, destParent, destRow) -> bool:
        """Reorder rows in-place. Used by Qt's internal-move drag flow."""
        if (count != 1 or sourceRow < 0 or sourceRow >= len(self._tracks)
                or destRow < 0 or destRow > len(self._tracks)):
            return False
        if sourceRow == destRow or sourceRow == destRow - 1:
            return False
        if not self.beginMoveRows(QModelIndex(), sourceRow, sourceRow,
                                  QModelIndex(), destRow):
            return False
        track = self._tracks.pop(sourceRow)
        target = destRow if destRow < sourceRow else destRow - 1
        self._tracks.insert(target, track)
        self.endMoveRows()
        self.queue_changed.emit()
        return True

    # ── Convenience ────────────────────────────────────────────────

    def song_ids(self) -> list[int]:
        return [int(t.get("id") or 0) for t in self._tracks]

    def total_duration_ms(self) -> int:
        return sum(int(t.get("duration_ms") or 0) for t in self._tracks)

    def tracks(self) -> list[dict]:
        return [dict(t) for t in self._tracks]


class _QueueRowDelegate(QStyledItemDelegate):
    """Paints a queue row — color bar, ⋮⋮, rank, title, artist, duration,
    × on hover. The × button hit area lives in the parent QListView's
    mouse-event handling (we paint state here)."""

    ROW_H = 56

    def __init__(self, color_provider, hover_provider, parent=None):
        super().__init__(parent)
        self._color_provider = color_provider     # callable() → hex
        self._hover_provider = hover_provider     # callable(row) → bool

        self._font_drag   = inter(15, QFont.Weight.Bold)
        self._font_rank   = inter(13, QFont.Weight.Bold)
        self._font_title  = inter(13, QFont.Weight.DemiBold, letter_spacing=-0.1)
        self._font_artist = inter(11, QFont.Weight.Medium)
        self._font_dur    = mono(12, bold=True)
        self._font_x      = inter(15, QFont.Weight.Bold)

    def sizeHint(self, option, index) -> QSize:
        return QSize(500, self.ROW_H + 4)

    def paint(self, p: QPainter, option: QStyleOptionViewItem,
              index: QModelIndex) -> None:
        track = index.data(Qt.ItemDataRole.UserRole) or {}
        rect = option.rect
        # Body gradient + border
        body = QRectF(rect.x() + 2, rect.y() + 2, rect.width() - 4, self.ROW_H)
        path = QPainterPath()
        path.addRoundedRect(body, 12, 12)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillPath(path, QColor(20, 22, 40, int(0.85 * 255)))
        p.setPen(QPen(COL_BORDER_FAINT, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        # Left color bar (3w accent matching playlist color)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(self._color_provider() or COL_CYAN))
        p.drawRect(QRectF(body.x(), body.y(), 3, body.height()))
        # ⋮⋮ drag handle
        p.setPen(QColor(COL_TEXT_MUTED))
        p.setFont(self._font_drag)
        p.drawText(QRectF(body.x() + 12, body.y() + 18, 14, 24),
                   Qt.AlignmentFlag.AlignCenter, "⋮⋮")
        # Rank box (28×28 at body.x()+32, body.y()+14)
        rank_rect = QRectF(body.x() + 32, body.y() + 14, 28, 28)
        rp = QPainterPath(); rp.addRoundedRect(rank_rect, 8, 8)
        p.fillPath(rp, QColor(14, 16, 32, int(0.85 * 255)))
        p.setPen(QPen(COL_BORDER_FAINT, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(rp)
        p.setPen(QColor(COL_TEXT_PRIMARY))
        p.setFont(self._font_rank)
        p.drawText(rank_rect, Qt.AlignmentFlag.AlignCenter,
                   f"{index.row() + 1:02d}")
        # Title + artist
        p.setPen(QColor(COL_TEXT_PRIMARY))
        p.setFont(self._font_title)
        p.drawText(QRectF(body.x() + 72, body.y() + 9, 320, 18),
                   Qt.AlignmentFlag.AlignLeft, str(track.get("title") or "—"))
        p.setPen(QColor(COL_TEXT_SECONDARY))
        p.setFont(self._font_artist)
        p.drawText(QRectF(body.x() + 72, body.y() + 28, 320, 14),
                   Qt.AlignmentFlag.AlignLeft, str(track.get("artist") or "—"))
        # Duration
        p.setPen(QColor(COL_TEXT_PRIMARY))
        p.setFont(self._font_dur)
        p.drawText(QRectF(body.x() + 392, body.y() + 20, 50, 16),
                   Qt.AlignmentFlag.AlignLeft,
                   _fmt_duration(int(track.get("duration_ms") or 0)))
        # × remove button on hover (26×26 at body.right()-30, body.y()+15)
        if self._hover_provider(index.row()):
            x_rect = QRectF(body.right() - 38, body.y() + 15, 26, 26)
            xp = QPainterPath(); xp.addRoundedRect(x_rect, 8, 8)
            p.fillPath(xp, _qcolor(COL_ROSE, 0.20))
            p.setPen(QPen(_qcolor(COL_ROSE, 0.50), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(xp)
            p.setPen(QColor(COL_ROSE_LT))
            p.setFont(self._font_x)
            p.drawText(x_rect, Qt.AlignmentFlag.AlignCenter, "×")


class _QueueListView(QListView):
    """QListView wired for internal drag-reorder + × on hover."""

    remove_track = pyqtSignal(int)     # row index

    def __init__(self, model: _QueueModel, color_provider, parent=None):
        super().__init__(parent)
        self.setModel(model)
        self._hover_row: int = -1
        self._delegate = _QueueRowDelegate(color_provider,
                                           lambda r: r == self._hover_row,
                                           parent=self)
        self.setItemDelegate(self._delegate)
        self.setViewMode(QListView.ViewMode.ListMode)
        self.setSpacing(2)
        self.setMouseTracking(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setStyleSheet(
            "QListView { background: transparent; border: none; padding: 0; }"
            "QListView::item { background: transparent; }"
            "QScrollBar:vertical { background: transparent; width: 6px; }"
            "QScrollBar::handle:vertical { background: rgba(255,255,255,0.10); "
            "border-radius: 3px; min-height: 24px; }"
            "QScrollBar::add-line, QScrollBar::sub-line { height: 0; }"
        )

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        idx = self.indexAt(e.pos())
        new_row = idx.row() if idx.isValid() else -1
        if new_row != self._hover_row:
            old = self._hover_row
            self._hover_row = new_row
            for row in (old, new_row):
                if row >= 0:
                    self.update(self.model().index(row, 0))
        super().mouseMoveEvent(e)

    def leaveEvent(self, e):
        if self._hover_row >= 0:
            old = self._hover_row
            self._hover_row = -1
            self.update(self.model().index(old, 0))
        super().leaveEvent(e)

    def mousePressEvent(self, e: QMouseEvent) -> None:
        # × hit-test BEFORE delegating to default (otherwise drag starts)
        if e.button() == Qt.MouseButton.LeftButton:
            idx = self.indexAt(e.pos())
            if idx.isValid():
                row_rect = self.visualRect(idx)
                # × button area: right - 38..-12, top + 15..+41
                x_rect = QRect(
                    row_rect.right() - 38, row_rect.top() + 15, 26, 26)
                if x_rect.contains(e.pos()):
                    self.remove_track.emit(idx.row())
                    return
        super().mousePressEvent(e)


# ════════════════════════════════════════════════════════════════════════
# AUTO-SCHEDULE TOGGLE — small two-state pill
# ════════════════════════════════════════════════════════════════════════

class _ToggleSwitch(QWidget):
    toggled = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(44, 24)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._on = False

    def is_on(self) -> bool:
        return self._on

    def set_on(self, on: bool) -> None:
        on = bool(on)
        if on != self._on:
            self._on = on
            self.update(self.rect())

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._on = not self._on
            self.update(self.rect())
            self.toggled.emit(self._on)

    def paintEvent(self, evt):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, 44, 24), 12, 12)
        if self._on:
            p.setBrush(_qcolor(COL_GREEN, 0.40))
            p.setPen(QPen(_qcolor(COL_GREEN, 0.60), 1))
        else:
            p.setBrush(QColor(20, 22, 40, int(0.85 * 255)))
            p.setPen(QPen(COL_BORDER_FAINT, 1))
        p.drawPath(path)
        # Knob
        x = 22 if self._on else 2
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(COL_GREEN_LT if self._on else COL_TEXT_MUTED))
        p.drawEllipse(QRectF(x + 2, 2, 20, 20))


# ════════════════════════════════════════════════════════════════════════
# PLAYLIST BUILDER — queue + footer toggle/buttons
# ════════════════════════════════════════════════════════════════════════

class _PlaylistBuilder(QFrame):
    """540×484 panel hosting the queue + bottom action bar."""

    add_to_schedule_changed = pyqtSignal(bool)
    clear_clicked   = pyqtSignal()
    shuffle_clicked = pyqtSignal()
    queue_changed   = pyqtSignal()

    def __init__(self, model: _QueueModel, color_provider, parent=None):
        super().__init__(parent)
        self.setFixedSize(540, 484)
        self.setGraphicsEffect(drop_shadow(24, QColor(0, 0, 0, int(0.40 * 255)), dy=10))

        self._model = model
        self._color_provider = color_provider

        # Body gradient + cyan top accent (queue is "music")
        g_body = QLinearGradient(0, 0, 0, 484)
        g_body.setColorAt(0.0, QColor(14, 16, 32, int(0.95 * 255)))
        g_body.setColorAt(1.0, QColor(7, 9, 18,  int(0.95 * 255)))
        self._grad_body = g_body
        g_top = QLinearGradient(0, 0, 540, 0)
        g_top.setColorAt(0.0, QColor(COL_CYAN))
        g_top.setColorAt(1.0, QColor(COL_PURPLE))
        self._grad_top = g_top

        self._font_section = inter(11, QFont.Weight.Black, letter_spacing=1.5)
        self._font_count   = inter(13, QFont.Weight.DemiBold)
        self._font_hint    = inter(11, QFont.Weight.Medium)
        self._font_btn     = inter(11, QFont.Weight.DemiBold)

        # Queue list view
        self._view = _QueueListView(model, color_provider, parent=self)
        self._view.setGeometry(20, 76, 500, 320)
        self._view.remove_track.connect(self._on_remove_track)
        # Bridge the model's queue_changed → builder's signal
        self._model.queue_changed.connect(self.queue_changed.emit)

        # Footer area — toggle + buttons
        self._toggle = _ToggleSwitch(self); self._toggle.move(252, 432)
        self._toggle.toggled.connect(self.add_to_schedule_changed.emit)

        self._clear_btn = self._make_btn("Clear", 80, COL_ROSE_LT)
        self._clear_btn.move(322, 430)
        self._clear_btn.clicked.connect(self.clear_clicked.emit)
        self._shuffle_btn = self._make_btn("⇄ Shuffle", 94, COL_PURPLE_LT)
        self._shuffle_btn.move(412, 430)
        self._shuffle_btn.clicked.connect(self.shuffle_clicked.emit)

    def _make_btn(self, label: str, w: int, color: str) -> QPushButton:
        b = QPushButton(label, self)
        b.setFixedSize(w, 32)
        b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        b.setFont(self._font_btn)
        b.setStyleSheet(
            f"QPushButton {{ background: rgba(14,16,32,0.85); "
            f"color: {color}; "
            f"border: 1px solid rgba(255,255,255,0.06); "
            f"border-radius: 8px; }}"
            f"QPushButton:hover {{ border-color: rgba(167,139,250,0.30); }}"
        )
        return b

    def _on_remove_track(self, row: int) -> None:
        sid = self._model.remove_at(row)
        if sid is not None:
            # bubble up so library can flip its button back
            self.queue_changed.emit()

    def set_auto_schedule_enabled(self, on: bool) -> None:
        self._toggle.set_on(on)

    def auto_schedule_enabled(self) -> bool:
        return self._toggle.is_on()

    def paintEvent(self, evt):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, 540, 484), 16, 16)
        p.fillPath(path, QBrush(self._grad_body))
        p.setPen(QPen(COL_BORDER_FAINT, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        p.setClipPath(path)
        p.fillRect(QRectF(0, 0, 540, 3), QBrush(self._grad_top))
        p.fillRect(QRectF(0, 2, 540, 1),
                   QColor(255, 255, 255, int(0.04 * 255)))
        p.setClipping(False)

        # Title
        p.setPen(QColor(COL_CYAN))
        p.setFont(self._font_section)
        p.drawText(QRectF(20, 14, 200, 16),
                   Qt.AlignmentFlag.AlignLeft, "PLAYLIST QUEUE")

        # Count badge
        n = self._model.rowCount()
        total = self._model.total_duration_ms()
        badge = f"{n} track{'s' if n != 1 else ''} · {_fmt_track_total(total)}"
        bp_w = max(120, 14 + 8 * len(badge))
        bp = QPainterPath()
        bp.addRoundedRect(QRectF(540 - bp_w - 20, 14, bp_w, 22), 11, 11)
        p.fillPath(bp, _qcolor(COL_CYAN, 0.18))
        p.setPen(QPen(_qcolor(COL_CYAN, 0.40), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(bp)
        p.setPen(QColor(COL_CYAN_LT))
        p.setFont(self._font_count)
        p.drawText(QRectF(540 - bp_w - 20, 14, bp_w, 22),
                   Qt.AlignmentFlag.AlignCenter, badge)

        # Hint
        p.setPen(QColor(COL_TEXT_MUTED))
        p.setFont(self._font_hint)
        p.drawText(QRectF(20, 44, 400, 14),
                   Qt.AlignmentFlag.AlignLeft,
                   "Drag to reorder · Hover row for actions")

        # Footer divider
        p.fillRect(QRectF(0, 408, 540, 1),
                   QColor(255, 255, 255, int(0.06 * 255)))
        # "Add to Auto Schedule" label + helper text
        p.setPen(QColor(COL_TEXT_PRIMARY))
        p.setFont(inter(13, QFont.Weight.DemiBold, letter_spacing=-0.1))
        p.drawText(QRectF(20, 422, 220, 18),
                   Qt.AlignmentFlag.AlignLeft, "Add to Auto Schedule")
        p.setPen(QColor(COL_TEXT_MUTED))
        p.setFont(inter(11, QFont.Weight.Medium))
        p.drawText(QRectF(20, 442, 240, 14),
                   Qt.AlignmentFlag.AlignLeft,
                   "Use this playlist in your weekly clocks")


# ════════════════════════════════════════════════════════════════════════
# PLAYLIST NEW — top-level
# ════════════════════════════════════════════════════════════════════════

class PlaylistNew(QWidget):
    """Premium-theme Create New Playlist screen.

    Signals:
      screen_requested(str) — 'studio_open' / 'libraries' / 'settings' /
                              'ai_magic' / 'playlists' (Save / Cancel
                              both return here).
    """

    screen_requested = pyqtSignal(str)

    AUTO_SAVE_MS = 1500

    def __init__(self, db, scheduler=None, parent=None, engine=None):
        super().__init__(parent)
        self._db = db
        self._scheduler = scheduler
        # Shared AudioEngine (Phase B Option C: singleton + DI). Frame 8
        # has no Preview button per Figma — engine is held for the
        # eventual Edit Playlist (Frame 9) preview hook and any future
        # row-level preview affordance. None is a valid runtime state;
        # all engine consumers must guard.
        self._engine = engine
        self.setFixedSize(WINDOW_W, WINDOW_H)
        self.setMouseTracking(False)

        # Cached page bg
        bg = QLinearGradient(0, 0, 0, WINDOW_H)
        bg.setColorAt(0.0, QColor(COL_BG_TOP))
        bg.setColorAt(0.5, QColor(COL_BG_MID))
        bg.setColorAt(1.0, QColor(COL_BG_BOT))
        self._bg = bg

        # State
        self._draft_id: Optional[int] = None
        self._meta: dict = {
            "name": "Untitled Playlist", "kind": "manual",
            "color": COL_CYAN, "tags": "", "cover_path": None,
        }
        self._queue_model = _QueueModel(self)
        self._dirty: bool = False
        self._program_start = time.time()

        # Cached fonts
        self._font_breadcrumb = inter(11, QFont.Weight.Bold, letter_spacing=2.0)
        self._font_title      = inter(36, QFont.Weight.Black, letter_spacing=-1.0)
        self._font_subtitle   = inter(13, QFont.Weight.Medium, letter_spacing=-0.1)
        self._font_status     = inter(11, QFont.Weight.Medium)
        self._font_footer     = inter(10, QFont.Weight.Bold, letter_spacing=0.3)
        self._font_footer_dot = inter(10, QFont.Weight.Bold)
        self._font_settings   = inter(11, QFont.Weight.Bold, letter_spacing=-0.1)

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

        # ── Cancel / Save (top-right) ─────────────────────────────────
        self._cancel = _CancelButton(self); self._cancel.move(1118, 144)
        self._cancel.clicked.connect(self._on_cancel)
        self._save = _SaveButton(self);     self._save.move(1234, 144)
        self._save.clicked.connect(self._on_save)

        # ── Meta form strip ───────────────────────────────────────────
        self._meta_form = _MetaFormStrip(self)
        self._meta_form.move(56, 226)
        self._meta_form.meta_changed.connect(self._on_meta_changed)

        # ── Library + Builder ─────────────────────────────────────────
        self._library = _LibraryBrowser(self._db, self)
        self._library.move(56, 360)
        self._library.add_song.connect(self._on_library_add)

        self._builder = _PlaylistBuilder(
            self._queue_model, lambda: self._meta.get("color") or COL_CYAN,
            self)
        self._builder.move(844, 360)
        self._builder.queue_changed.connect(self._on_queue_changed)
        self._builder.add_to_schedule_changed.connect(
            self._on_auto_schedule_toggle)
        self._builder.clear_clicked.connect(self._on_clear_queue)
        self._builder.shuffle_clicked.connect(self._on_shuffle_queue)

        # ── Auto-save timer ───────────────────────────────────────────
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(self.AUTO_SAVE_MS)
        self._save_timer.timeout.connect(self._on_autosave)

        # ── 1Hz tick for header time ─────────────────────────────────
        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._on_tick)
        self._tick.start()
        self._on_tick()

        log.info("PlaylistNew ready (Figma 243:2 — Premium Dark)")

    # ── lifecycle ─────────────────────────────────────────────────────

    def showEvent(self, evt):
        super().showEvent(evt)
        # Reset state for a fresh creation flow each time
        self._reset_for_new_draft()

    # ── State reset ───────────────────────────────────────────────────

    def _reset_for_new_draft(self) -> None:
        self._meta = {
            "name": "Untitled Playlist", "kind": "manual",
            "color": COL_CYAN, "tags": "", "cover_path": None,
        }
        self._meta_form.set_data(self._meta)
        self._queue_model.clear()
        self._library.set_added_ids(set())
        self._builder.set_auto_schedule_enabled(False)
        self._dirty = False
        self._draft_id = None
        # Library widget already refreshes itself on filters/search; do an
        # explicit refresh now so the row data is up-to-date.
        self._library.refresh()

    def _ensure_draft(self) -> None:
        """Create the draft row in the DB on first dirtying interaction.
        Subsequent autosaves UPDATE the same row."""
        if self._draft_id is not None:
            return
        try:
            self._draft_id = self._db.create_playlist_draft(
                name=self._meta.get("name", "Untitled Playlist"),
                kind=self._meta.get("kind", "manual"),
                color=self._meta.get("color"),
                tags=self._meta.get("tags") or None,
            )
        except Exception as exc:
            log.warning(f"create_playlist_draft failed: {exc}")
            self._draft_id = None

    # ── handlers ─────────────────────────────────────────────────────

    def _on_meta_changed(self, data: dict) -> None:
        self._meta.update(data)
        self._mark_dirty()

    def _on_library_add(self, song_id: int) -> None:
        # Pull full song row
        row = self._db.get_song(int(song_id))
        if row is None:
            return
        self._queue_model.append_track({
            "id":          int(row["id"]),
            "title":       row["title"],
            "artist":      row["artist"],
            "duration_ms": int(row["duration_ms"] or 0),
        })
        # Library updated_added_ids handled inside library on click,
        # but we also keep them in sync here for safety
        self._library.set_added_ids(set(self._queue_model.song_ids()))
        self._mark_dirty()

    def _on_queue_changed(self) -> None:
        # Re-sync library's added_ids set
        self._library.set_added_ids(set(self._queue_model.song_ids()))
        self.update(QRect(56, 856, 1328, 28))   # footer status
        self._mark_dirty()

    def _on_auto_schedule_toggle(self, on: bool) -> None:
        self._mark_dirty()

    def _on_clear_queue(self) -> None:
        if self._queue_model.rowCount() == 0:
            return
        self._queue_model.clear()
        self._library.set_added_ids(set())
        self._mark_dirty()

    def _on_shuffle_queue(self) -> None:
        self._queue_model.shuffle()
        self._mark_dirty()

    # ── Auto-save ────────────────────────────────────────────────────

    def _mark_dirty(self) -> None:
        self._dirty = True
        self._save_timer.start()    # restarts the 1500ms debouncer
        self.update(QRect(56, 856, 1328, 28))

    def _on_autosave(self) -> None:
        if not self._dirty:
            return
        self._ensure_draft()
        if self._draft_id is None:
            return
        try:
            self._db.update_playlist_draft(
                self._draft_id,
                name=self._meta.get("name") or "Untitled Playlist",
                kind=self._meta.get("kind"),
                color=self._meta.get("color"),
                tags=self._meta.get("tags") or None,
                cover_path=self._meta.get("cover_path"),
                auto_schedule_enabled=self._builder.auto_schedule_enabled(),
            )
            self._db.replace_playlist_songs(
                self._draft_id, self._queue_model.song_ids())
        except Exception as exc:
            log.warning(f"autosave failed: {exc}")
            return
        self._dirty = False
        log.info(f"[playlist-new] autosaved draft id={self._draft_id} "
                 f"tracks={self._queue_model.rowCount()}")
        self.update(QRect(56, 856, 1328, 28))

    # ── Save / Cancel ────────────────────────────────────────────────

    def _on_save(self) -> None:
        # Force-flush any pending autosave
        if self._save_timer.isActive():
            self._save_timer.stop()
        self._on_autosave()
        if self._draft_id is None:
            # Nothing to save — user hasn't dirtied; just navigate back
            self.screen_requested.emit("playlists")
            return
        try:
            self._db.commit_playlist_draft(int(self._draft_id))
        except Exception as exc:
            log.warning(f"commit_playlist_draft failed: {exc}")
            dialogs.warning(self, "Save failed", str(exc))
            return
        # Optionally register with scheduler engine
        if (self._builder.auto_schedule_enabled()
                and self._scheduler is not None
                and hasattr(self._scheduler, "add_playlist_to_schedule")):
            try:
                self._scheduler.add_playlist_to_schedule(int(self._draft_id))
            except Exception as exc:
                log.warning(
                    f"add_playlist_to_schedule failed: {exc}")
        log.info(f"[playlist-new] saved playlist id={self._draft_id}")
        self.screen_requested.emit("playlists")

    def _on_cancel(self) -> None:
        if self._dirty or self._draft_id is not None:
            if not dialogs.confirm(
                    self, "Discard playlist?",
                    "This playlist hasn't been saved.\n\n"
                    "Discard changes and go back?",
                    danger=True, yes_label="Discard"):
                return
            if self._draft_id is not None:
                try:
                    self._db.delete_playlist_draft(int(self._draft_id))
                except Exception as exc:
                    log.warning(f"delete_playlist_draft: {exc}")
                self._draft_id = None
        self.screen_requested.emit("playlists")

    # ── 1Hz tick ─────────────────────────────────────────────────────

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

    # ── Page paint (gradient bg + breadcrumb + title + footer) ───────

    def paintEvent(self, evt):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QBrush(self._bg))

        # Breadcrumb
        p.setPen(QColor(COL_TEXT_MUTED))
        p.setFont(self._font_breadcrumb)
        p.drawText(QRectF(56, 110, 600, 16),
                   Qt.AlignmentFlag.AlignLeft,
                   "SCHEDULING / PLAYLISTS / NEW")
        # Title
        p.setPen(QColor(COL_TEXT_PRIMARY))
        p.setFont(self._font_title)
        p.drawText(QRectF(56, 130, 800, 56),
                   Qt.AlignmentFlag.AlignLeft, "Create New Playlist")
        # Subtitle
        p.setPen(QColor(COL_TEXT_SECONDARY))
        p.setFont(self._font_subtitle)
        p.drawText(QRectF(56, 188, 700, 18),
                   Qt.AlignmentFlag.AlignLeft,
                   "Pick songs from your library and arrange them into a custom playlist")

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
        # Status string — dynamic
        n = self._queue_model.rowCount()
        total = self._queue_model.total_duration_ms()
        if self._dirty:
            status = (f"{n} track{'s' if n != 1 else ''} selected · "
                      f"{_fmt_track_total(total)} total · saving…")
        elif self._draft_id is not None:
            status = (f"{n} track{'s' if n != 1 else ''} selected · "
                      f"{_fmt_track_total(total)} total · auto-saved")
        else:
            status = "Start adding tracks — auto-saves as you build"
        p.setPen(QColor(COL_TEXT_MUTED))
        p.setFont(self._font_footer)
        p.drawText(QRectF(240, 868, 700, 14),
                   Qt.AlignmentFlag.AlignLeft, status)
        # Settings link
        p.setPen(QColor(COL_PURPLE))
        p.setFont(inter(14, QFont.Weight.Bold))
        p.drawText(QRectF(1314, 866, 18, 18),
                   Qt.AlignmentFlag.AlignLeft, "⚙")
        p.setPen(QColor(COL_PURPLE))
        p.setFont(self._font_settings)
        p.drawText(QRectF(1334, 868, 60, 14),
                   Qt.AlignmentFlag.AlignLeft, "Settings")
