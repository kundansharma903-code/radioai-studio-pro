"""
RadioAI Studio Pro — Sweeper Editor Dialog (Add / Edit)
Pixel-accurate match of Figma node 108:2 (file 7oN9K61g94wKx3nu44KKDF).

Single dialog used for both "Add New Sweeper" and "Edit Sweeper":
  • Mode NEW  — sweeper_id is None; AUTO CODE is generated server-side
                (db.next_sweeper_auto_code) and shown in the header pill.
  • Mode EDIT — sweeper_id is provided; existing row's data is preloaded
                into every field; auto_code is read-only display.

Layout (900×660, three-zone BaseDialog):
  HEADER (52h)   〜 NEW SWEEPER · subtitle · AUTO CODE pill · ✕
  CONTENT
    LEFT (590w):  Title* · Author / Code / Date · Comments ·
                  CATEGORY tile grid · TRACK PROPERTIES · POSITION SETTINGS
                  (timeline + 6 chips) · AUDIO FILE picker
    RIGHT (282w): AVAILABILITY · OVERLAY BEHAVIOR · POSITION OFFSET ·
                  SCHEDULING · SEPARATION · ✦ AI Auto-fill (stub)
  FOOTER (52h)   * Required fields · Cancel · ✓ Save

Persistence:
  Save → calls db.add_sweeper / update_sweeper. Emits sweeper_saved(id).

Phase status (consistent with the Sweepers Library screen build cadence):
  [✓] Full layout, all fields editable, save round-trips through DB.
  [ ] AI Auto-fill Metadata — stub toast (no LLM hookup yet)
  [ ] Mix Point dragging on the timeline strip — visual only
  [ ] Audio file probe (auto-fill duration_ms from BASS) — operator types
      duration manually for now
  [ ] Edit-Audio button → AudioCueEditorDialog hookup (future)
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Optional

from PyQt6.QtCore import Qt, QRectF, pyqtSignal
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QPainterPath, QFont, QCursor,
    QFontMetrics, QIntValidator, QDoubleValidator,
)
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QLineEdit, QTextEdit, QComboBox,
    QHBoxLayout, QVBoxLayout, QFileDialog, QMessageBox, QSizePolicy,
)

from ui.dialogs.base_dialog import BaseDialog
from ui.widgets._tokens import (
    inter, mono, rgba,
    BG_BASE, BG_PANEL, BG_CARD, BG_ELEVATED,
    TEXT_PRI, TEXT_SEC, TEXT_MUTED, TEXT_DIM,
    CYAN, CYAN_LIGHT, PURPLE, PURPLE_LIGHT, GREEN, GREEN_LIGHT,
    AMBER, AMBER_LIGHT, RED, RED_LIGHT, PINK, PINK_LIGHT,
)

log = logging.getLogger("SweeperEditorDialog")


# ════════════════════════════════════════════════════════════════════════════
# Geometry tokens (relative to the inner content area inside BaseDialog)
# ════════════════════════════════════════════════════════════════════════════

DLG_W = 900
DLG_H = 660

LEFT_W = 590
RIGHT_W = 282

CATEGORY_OPTIONS = [
    "Station", "Music", "News", "Promo",
    "Weather", "Traffic", "Sports", "Custom",
]

POSITION_OPTIONS = [
    "Start of Song", "Before Intro", "Before End",
    "Bridge at End", "Independent", "Custom Position",
]

POSITION_GLYPHS = {
    "Start of Song":   "→",
    "Before Intro":    "⤷",
    "Before End":      "←",
    "Bridge at End":   "⇌",
    "Independent":     "◈",
    "Custom Position": "⊕",
}


def _fmt_duration(ms: int) -> str:
    s = int((ms or 0) // 1000)
    return f"{s // 60}:{s % 60:02d}"


def _parse_duration(text: str) -> int:
    """'M:SS' → ms. Returns 0 on parse error."""
    text = (text or "").strip()
    if not text:
        return 0
    try:
        if ":" in text:
            m, s = text.split(":", 1)
            return (int(m) * 60 + int(s)) * 1000
        return int(text) * 1000
    except Exception:
        return 0


# ════════════════════════════════════════════════════════════════════════════
# Reusable widgets
# ════════════════════════════════════════════════════════════════════════════

class _SectionHeader(QFrame):
    """ALL-CAPS section header strip with cyan left accent bar."""

    def __init__(self, text: str, color: str = CYAN, parent=None):
        super().__init__(parent)
        self._text = text
        self._color = QColor(color)
        self.setFixedHeight(24)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        # Card background
        bg = QColor(self._color); bg.setAlphaF(0.06)
        p.fillRect(QRectF(0, 0, w, h), bg)
        # Left accent bar
        p.fillRect(QRectF(0, 0, 3, h), self._color)
        # Label
        p.setPen(self._color)
        p.setFont(inter(10, QFont.Weight.Bold, letter_spacing=1.4))
        p.drawText(QRectF(12, 0, w - 16, h),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._text.upper())


def _styled_lineedit(placeholder: str = "",
                     mono_font: bool = False) -> QLineEdit:
    e = QLineEdit()
    e.setPlaceholderText(placeholder)
    e.setFixedHeight(30)
    if mono_font:
        e.setFont(mono(11))
    else:
        e.setFont(inter(11))
    e.setStyleSheet(
        f"QLineEdit {{ background: {BG_CARD}; color: {TEXT_PRI}; "
        f"border: 1px solid {rgba('#ffffff', 0.06)}; border-radius: 6px; "
        f"padding-left: 10px; padding-right: 10px; }}"
        f"QLineEdit:focus {{ border-color: {rgba(CYAN, 0.45)}; }}"
        f"QLineEdit::placeholder {{ color: {TEXT_MUTED}; }}"
    )
    return e


def _styled_textedit(placeholder: str = "") -> QTextEdit:
    t = QTextEdit()
    t.setPlaceholderText(placeholder)
    t.setFixedHeight(44)
    t.setFont(inter(10))
    t.setStyleSheet(
        f"QTextEdit {{ background: {BG_CARD}; color: {TEXT_PRI}; "
        f"border: 1px solid {rgba('#ffffff', 0.06)}; border-radius: 6px; "
        f"padding: 6px 10px; }}"
        f"QTextEdit:focus {{ border-color: {rgba(CYAN, 0.45)}; }}"
    )
    return t


def _styled_combo(items: list, default: str = "") -> QComboBox:
    c = QComboBox()
    c.addItems(items)
    c.setFixedHeight(30)
    c.setFont(inter(11))
    if default and default in items:
        c.setCurrentText(default)
    c.setStyleSheet(
        f"QComboBox {{ background: {BG_CARD}; color: {TEXT_PRI}; "
        f"border: 1px solid {rgba('#ffffff', 0.06)}; border-radius: 6px; "
        f"padding-left: 10px; padding-right: 24px; }}"
        f"QComboBox::drop-down {{ border: none; width: 20px; }}"
        f"QComboBox::down-arrow {{ image: none; width: 0; height: 0; "
        f"border-left: 4px solid transparent; "
        f"border-right: 4px solid transparent; "
        f"border-top: 5px solid {TEXT_MUTED}; margin-right: 8px; }}"
        f"QComboBox QAbstractItemView {{ background: {BG_CARD}; "
        f"color: {TEXT_PRI}; "
        f"border: 1px solid {rgba('#ffffff', 0.06)}; border-radius: 6px; "
        f"selection-background-color: {rgba(CYAN, 0.20)}; "
        f"selection-color: {CYAN_LIGHT}; outline: none; padding: 4px; }}"
    )
    return c


class _LabeledField(QFrame):
    """Vertical label + input wrapper. Label sits at top, input fills below."""

    def __init__(self, label: str, widget: QWidget, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        lbl = QLabel(label)
        lbl.setFont(inter(9, QFont.Weight.DemiBold))
        lbl.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        v.addWidget(lbl)
        v.addWidget(widget)
        self._label_widget = lbl
        self._input_widget = widget


class _CategoryTile(QPushButton):
    """One category tile in the 4×2 grid. Cyan-bordered when selected."""

    def __init__(self, name: str, parent=None):
        super().__init__(name, parent)
        self._name = name
        self._active = False
        self._hover = False
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFlat(True)
        self.setFixedHeight(28)
        self.setStyleSheet("background: transparent; border: none;")

    def set_active(self, active: bool):
        self._active = bool(active)
        self.update()

    def enterEvent(self, e): self._hover = True;  self.update(); super().enterEvent(e)
    def leaveEvent(self, e): self._hover = False; self.update(); super().leaveEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        rect = QRectF(0.5, 0.5, w - 1, h - 1)
        path = QPainterPath(); path.addRoundedRect(rect, 6, 6)
        p.setClipPath(path)
        if self._active:
            tint = QColor(CYAN); tint.setAlphaF(0.20)
            p.fillRect(rect, tint)
            p.setClipping(False)
            p.setPen(QPen(QColor(rgba(CYAN, 0.55)), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(rect, 6, 6)
            p.fillRect(QRectF(0, 0, 2, h), QColor(CYAN))
            p.setPen(QColor(CYAN_LIGHT))
        else:
            p.fillRect(rect, QColor("#0a0c18"))
            if self._hover:
                p.fillRect(rect, QColor(255, 255, 255, 8))
            p.setClipping(False)
            p.setPen(QPen(QColor(rgba("#ffffff", 0.06)), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(rect, 6, 6)
            p.setPen(QColor(TEXT_SEC if self._hover else TEXT_MUTED))
        p.setFont(inter(10, QFont.Weight.DemiBold if self._active
                                   else QFont.Weight.Medium))
        p.drawText(QRectF(10, 0, w - 14, h),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._name)


class _PositionChip(QPushButton):
    """One position chip in the 3×2 grid (Start of Song, Before Intro, ...).
    Selected chip gets a cyan left bar + cyan border."""

    def __init__(self, name: str, parent=None):
        super().__init__(name, parent)
        self._name = name
        self._glyph = POSITION_GLYPHS.get(name, "•")
        self._active = False
        self._hover = False
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFlat(True)
        self.setFixedHeight(28)
        self.setStyleSheet("background: transparent; border: none;")

    def set_active(self, active: bool):
        self._active = bool(active)
        self.update()

    def enterEvent(self, e): self._hover = True;  self.update(); super().enterEvent(e)
    def leaveEvent(self, e): self._hover = False; self.update(); super().leaveEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        rect = QRectF(0.5, 0.5, w - 1, h - 1)
        path = QPainterPath(); path.addRoundedRect(rect, 6, 6)
        p.setClipPath(path)
        if self._active:
            tint = QColor(CYAN); tint.setAlphaF(0.18)
            p.fillRect(rect, tint)
            p.setClipping(False)
            p.setPen(QPen(QColor(rgba(CYAN, 0.55)), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(rect, 6, 6)
            p.fillRect(QRectF(0, 0, 2, h), QColor(CYAN))
            p.setPen(QColor(CYAN_LIGHT))
        else:
            p.fillRect(rect, QColor("#0a0c18"))
            if self._hover:
                p.fillRect(rect, QColor(255, 255, 255, 8))
            p.setClipping(False)
            p.setPen(QPen(QColor(rgba("#ffffff", 0.06)), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(rect, 6, 6)
            p.setPen(QColor(TEXT_SEC if self._hover else TEXT_MUTED))
        p.setFont(inter(10, QFont.Weight.DemiBold if self._active
                                   else QFont.Weight.Medium))
        p.drawText(QRectF(10, 0, w - 14, h),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   f"{self._glyph}  {self._name}")


class _PositionTimelineStrip(QFrame):
    """Visual timeline showing Song duration with Start / Before Intro /
    Bridge / Before End / Mix Point markers. Visual only — drag handle for
    Mix Point is deferred per the plan."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(54)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        # Card background
        p.fillRect(QRectF(0, 0, w, h), QColor("#0a0c18"))
        p.setPen(QPen(QColor(rgba("#ffffff", 0.06)), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 6, 6)

        # SONG label
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(inter(8, QFont.Weight.Bold, letter_spacing=1.2))
        p.drawText(QRectF(8, 6, 50, 12),
                   Qt.AlignmentFlag.AlignLeft, "SONG")

        # Timeline track
        track_x = 46
        track_y = h // 2 - 7
        track_w = w - track_x - 88     # leaves space for "Mix Point" caption
        # Background track gradient
        from PyQt6.QtGui import QLinearGradient
        g = QLinearGradient(track_x, 0, track_x + track_w, 0)
        g.setColorAt(0.0, QColor("#1c1f38"))
        g.setColorAt(1.0, QColor("#2a2e4d"))
        p.setBrush(QBrush(g)); p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(track_x, track_y, track_w, 14), 4, 4)

        # Markers (fractional positions along the track)
        markers = [
            (0.00,  "Start",        CYAN),
            (0.16,  "Before Intro", AMBER),
            (0.66,  "Bridge",       PURPLE_LIGHT),
            (0.83,  "Before End",   AMBER_LIGHT),
        ]
        for frac, label, col in markers:
            mx = int(track_x + track_w * frac)
            p.fillRect(QRectF(mx, track_y, 2, 14), QColor(col))
            p.setPen(QColor(col))
            p.setFont(inter(8, QFont.Weight.DemiBold))
            p.drawText(QRectF(mx + 2, track_y + 16, 80, 10),
                       Qt.AlignmentFlag.AlignLeft, label)

        # Mix Point marker (red, near end with ← caption to the right)
        mp_x = track_x + track_w
        p.fillRect(QRectF(mp_x, track_y - 4, 2, 22), QColor(RED_LIGHT))
        # Mix Point dot above
        p.setBrush(QColor(RED_LIGHT)); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(mp_x - 4, track_y - 6, 10, 10)
        # Caption to the right
        p.setPen(QColor(RED_LIGHT))
        p.setFont(inter(8, QFont.Weight.Bold))
        p.drawText(QRectF(mp_x + 8, track_y + 1, 80, 10),
                   Qt.AlignmentFlag.AlignLeft, "● Mix Point")
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(inter(7))
        p.drawText(QRectF(mp_x + 8, track_y + 14, 80, 10),
                   Qt.AlignmentFlag.AlignLeft, "← Mix Point")


class _AvailabilityCard(QFrame):
    """Two-row availability picker: ✓ Enabled (default) / Disabled.
    Click anywhere on a row toggles selection."""

    changed = pyqtSignal(bool)   # True = enabled

    def __init__(self, parent=None):
        super().__init__(parent)
        self._enabled = True
        self.setFixedHeight(58)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

    def is_enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, en: bool):
        was = self._enabled
        self._enabled = bool(en)
        self.update()
        if was != self._enabled:
            self.changed.emit(self._enabled)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            # Top half = Enabled, bottom half = Disabled
            mid = self.height() // 2
            self.set_enabled(e.position().y() < mid)
        super().mousePressEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        # Card background (selected = green-tinted)
        bg = QColor(GREEN); bg.setAlphaF(0.06 if self._enabled else 0.0)
        p.fillRect(QRectF(0, 0, w, h), bg)
        # Left accent (green when enabled, dim red when disabled)
        accent = QColor(GREEN) if self._enabled else QColor(rgba(RED, 0.30))
        p.fillRect(QRectF(0, 0, 3, h), accent)
        # Border
        bc = QColor(GREEN) if self._enabled else QColor("#1c1f38")
        if self._enabled:
            bc.setAlphaF(0.45)
        p.setPen(QPen(bc, 1)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 6, 6)

        def _row(y, label, sub, active):
            # Checkbox
            box = QRectF(10, y, 16, 16)
            if active:
                p.fillRect(box, QColor(GREEN))
                p.setPen(QColor("#04220f"))
                p.setFont(inter(10, QFont.Weight.Black))
                p.drawText(box, Qt.AlignmentFlag.AlignCenter, "✓")
            else:
                p.fillRect(box, QColor("#0a0c18"))
                p.setPen(QPen(QColor(rgba("#ffffff", 0.10)), 1))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(box)
            # Label
            p.setPen(QColor(GREEN_LIGHT if active else TEXT_SEC))
            p.setFont(inter(11, QFont.Weight.Bold))
            p.drawText(QRectF(32, y - 1, w - 36, 16),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       label)
            # Subtitle
            if sub:
                p.setPen(QColor(TEXT_MUTED))
                p.setFont(inter(9))
                p.drawText(QRectF(32, y + 14, w - 36, 12),
                           Qt.AlignmentFlag.AlignLeft, sub)

        _row(8,  "Enabled", "Sweeper will play in rotation", self._enabled)
        _row(38, "Disabled (Inactive)", "", not self._enabled)


class _VolumeSlider(QFrame):
    """Labeled slider with percentage readout. Click anywhere on the track
    sets the value to that fraction. Drag is deferred."""

    changed = pyqtSignal(int)

    def __init__(self, label: str, value_pct: int, parent=None):
        super().__init__(parent)
        self._label = label
        self._value = max(0, min(100, int(value_pct)))
        self.setFixedHeight(20)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

    def value(self) -> int:
        return self._value

    def set_value(self, v: int):
        new = max(0, min(100, int(v)))
        if new != self._value:
            self._value = new
            self.update()
            self.changed.emit(self._value)

    def mousePressEvent(self, e):
        track_x, track_w = 56, 124
        x = max(0, min(track_w, int(e.position().x()) - track_x))
        self.set_value(int(round(x * 100 / max(1, track_w))))
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.MouseButton.LeftButton:
            self.mousePressEvent(e)
        super().mouseMoveEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        # Label
        p.setPen(QColor(TEXT_SEC))
        p.setFont(inter(9, QFont.Weight.Medium))
        p.drawText(QRectF(0, 0, 56, h),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._label)
        # Track
        track_x, track_w = 56, 124
        track_y = h // 2 - 4
        p.setBrush(QColor("#1c1f38")); p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(track_x, track_y, track_w, 8), 4, 4)
        fill = int(track_w * self._value / 100)
        p.setBrush(QColor(PURPLE_LIGHT))
        p.drawRoundedRect(QRectF(track_x, track_y, fill, 8), 4, 4)
        # Value text
        p.setPen(QColor(TEXT_PRI))
        p.setFont(mono(9, bold=True))
        p.drawText(QRectF(track_x + track_w + 6, 0, 36, h),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   f"{self._value}%")


class _AICard(QPushButton):
    """Purple AI Auto-fill card — visual button. Stub for now."""

    def __init__(self, parent=None):
        super().__init__("", parent)
        self._hover = False
        self.setFixedHeight(36)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFlat(True)
        self.setStyleSheet("background: transparent; border: none;")

    def enterEvent(self, e): self._hover = True;  self.update(); super().enterEvent(e)
    def leaveEvent(self, e): self._hover = False; self.update(); super().leaveEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        rect = QRectF(0.5, 0.5, w - 1, h - 1)
        bg = QColor(PURPLE); bg.setAlphaF(0.20 if self._hover else 0.10)
        p.fillRect(rect, bg)
        bc = QColor(PURPLE); bc.setAlphaF(0.45)
        p.setPen(QPen(bc, 1)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 6, 6)
        p.fillRect(QRectF(0, 0, 3, h), QColor(PURPLE))
        # Glyph + title
        p.setPen(QColor(PURPLE_LIGHT))
        p.setFont(inter(13, QFont.Weight.Bold))
        p.drawText(QRectF(12, 0, 18, h),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   "✦")
        p.setFont(inter(11, QFont.Weight.Bold))
        p.drawText(QRectF(32, 4, w - 40, 16),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   "AI Auto-fill Metadata")
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(inter(9))
        p.drawText(QRectF(32, 18, w - 40, 14),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   "Auto-detect position from audio")


# ════════════════════════════════════════════════════════════════════════════
# Main dialog
# ════════════════════════════════════════════════════════════════════════════

class SweeperEditorDialog(BaseDialog):
    """Add or Edit a sweeper. See module docstring for layout + persistence."""

    HEADER_H = 52
    FOOTER_H = 52

    sweeper_saved = pyqtSignal(int)   # id of inserted/updated sweeper

    def __init__(self, db, sweeper_id: Optional[int] = None, parent=None):
        self._db = db
        self._sweeper_id = sweeper_id
        self._mode_edit = sweeper_id is not None

        # Make sure the schema can accept the dialog's writes before any
        # widget queries the row (PRAGMA + ALTER TABLE — idempotent).
        try:
            self._db._ensure_sweepers_columns()
        except Exception as exc:
            log.error(f"_ensure_sweepers_columns failed: {exc}")

        # Pre-fetch existing row if editing
        self._existing: dict = {}
        if self._mode_edit:
            self._existing = self._fetch_existing(int(sweeper_id))

        # State driven by widgets — wired in _build_*
        self._auto_code: str = (self._existing.get("auto_code")
                                if self._mode_edit
                                else db.next_sweeper_auto_code())
        self._selected_category: str = (self._existing.get("category")
                                        or "Station")
        self._selected_position: str = (self._existing.get("position")
                                        or "Bridge at End")

        # Widget refs (resolved after _build_content)
        self._title_input: Optional[QLineEdit] = None
        self._author_input: Optional[QLineEdit] = None
        self._code_input: Optional[QLineEdit] = None
        self._date_input: Optional[QLineEdit] = None
        self._comments_input: Optional[QTextEdit] = None
        self._props_input: Optional[QLineEdit] = None
        self._duration_input: Optional[QLineEdit] = None
        self._bpm_input: Optional[QLineEdit] = None
        self._era_input: Optional[QLineEdit] = None
        self._file_input: Optional[QLineEdit] = None
        self._cat_tiles: dict[str, _CategoryTile] = {}
        self._pos_chips: dict[str, _PositionChip] = {}
        self._timeline: Optional[_PositionTimelineStrip] = None
        self._availability: Optional[_AvailabilityCard] = None
        self._song_vol: Optional[_VolumeSlider] = None
        self._swp_vol: Optional[_VolumeSlider] = None
        self._offset_input: Optional[QLineEdit] = None
        self._fade_input: Optional[QLineEdit] = None
        self._clock_combo: Optional[QComboBox] = None
        self._clocks_index: list[int] = []        # row index → clock_id
        self._min_gap_input: Optional[QLineEdit] = None
        self._max_per_hour_input: Optional[QLineEdit] = None

        super().__init__(target_size=(DLG_W, DLG_H), parent=parent)
        self.setWindowTitle(
            "Edit Sweeper" if self._mode_edit else "New Sweeper")

        # Now the widgets exist — populate them from _existing (if any).
        self._populate_from_existing()

        log.info(
            f"SweeperEditorDialog ready (mode="
            f"{'EDIT' if self._mode_edit else 'NEW'}, id={sweeper_id}, "
            f"auto_code={self._auto_code})")

    # ── Data helpers ─────────────────────────────────────────────────────

    def _fetch_existing(self, sid: int) -> dict:
        try:
            row = self._db._conn().execute(
                "SELECT * FROM sweepers WHERE id = ?", [sid]).fetchone()
            if row is None:
                return {}
            return dict(row)
        except Exception as exc:
            log.error(f"fetch_existing(id={sid}) failed: {exc}")
            return {}

    # ── Header ───────────────────────────────────────────────────────────

    def _build_header(self) -> QWidget:
        f = QFrame()
        f.setObjectName("sweeperEditorHeader")
        f.setStyleSheet(
            "QFrame#sweeperEditorHeader { "
            "background: qlineargradient(x1:0,y1:0,x2:0,y2:1, "
            "stop:0 rgba(20,22,40,0.95), stop:1 rgba(13,15,30,0.95)); "
            "border-top-left-radius: 12px; "
            "border-top-right-radius: 12px; "
            f"border-bottom: 1px solid {rgba('#ffffff', 0.06)};"
            "}"
        )
        # Icon tile
        icon = QLabel("〜", f)
        icon.setGeometry(14, 12, 28, 28)
        icon.setFont(inter(14, QFont.Weight.Black))
        icon.setStyleSheet(
            f"QLabel {{ background: {rgba(PINK, 0.18)}; color: {PINK_LIGHT}; "
            f"border: 1px solid {rgba(PINK, 0.30)}; border-radius: 6px; }}"
        )
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Title
        title = QLabel(
            "EDIT SWEEPER" if self._mode_edit else "NEW SWEEPER", f)
        title.setGeometry(50, 10, 240, 18)
        title.setFont(inter(13, QFont.Weight.Bold, letter_spacing=1.2))
        title.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        sub = QLabel(
            "Update an existing audio overlay sweeper"
            if self._mode_edit
            else "Add a new audio overlay sweeper to the library", f)
        sub.setGeometry(50, 30, 320, 14)
        sub.setFont(inter(9))
        sub.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

        # AUTO CODE pill
        pill = QFrame(f)
        pill.setGeometry(700, 12, 110, 28)
        pill.setStyleSheet(
            f"QFrame {{ background: {rgba(GREEN, 0.16)}; "
            f"border: 1px solid {rgba(GREEN, 0.40)}; "
            f"border-radius: 6px; }}"
        )
        cl = QLabel("AUTO CODE", pill)
        cl.setGeometry(8, 3, 60, 11)
        cl.setFont(inter(8, QFont.Weight.Bold, letter_spacing=1.0))
        cl.setStyleSheet(f"color: {GREEN}; background: transparent;")
        cv = QLabel(self._auto_code, pill)
        cv.setGeometry(8, 14, 100, 13)
        cv.setFont(mono(11, bold=True))
        cv.setStyleSheet(f"color: {GREEN_LIGHT}; background: transparent;")

        # Close
        x = QPushButton("✕", f)
        x.setGeometry(858, 11, 30, 30)
        x.setFont(inter(13, QFont.Weight.Bold))
        x.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        x.setStyleSheet(
            f"QPushButton {{ background: #1c1f38; color: {TEXT_SEC}; "
            f"border: none; border-radius: 6px; }}"
            f"QPushButton:hover {{ background: {rgba(RED, 0.20)}; "
            f"color: {RED_LIGHT}; }}"
        )
        x.clicked.connect(self.reject)
        return f

    # ── Content ──────────────────────────────────────────────────────────

    def _build_content(self) -> QWidget:
        """Two-column body wrapped in a single QFrame so the BaseDialog's
        scroll area can host it without complaining."""
        body = QFrame()
        body.setStyleSheet("background: transparent;")
        h = QHBoxLayout(body)
        h.setContentsMargins(16, 12, 16, 12)
        h.setSpacing(12)

        h.addWidget(self._build_left_form(), 0)

        # 1px vertical divider — Figma shows it at x=590..591
        sep = QFrame()
        sep.setFixedWidth(1)
        sep.setStyleSheet(f"background: {rgba('#ffffff', 0.06)};")
        h.addWidget(sep)

        h.addWidget(self._build_right_sidebar(), 0)
        h.addStretch()
        return body

    # ── Left form ────────────────────────────────────────────────────────

    def _build_left_form(self) -> QWidget:
        wrap = QFrame()
        wrap.setFixedWidth(LEFT_W)
        wrap.setStyleSheet("background: transparent;")
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)

        # Sweeper Title *
        self._title_input = _styled_lineedit("Enter sweeper name...")
        v.addWidget(_LabeledField("Sweeper Title *", self._title_input))

        # Author / Playlister Code / Entry Date — three-column row
        triple = QFrame(); triple.setStyleSheet("background: transparent;")
        th = QHBoxLayout(triple)
        th.setContentsMargins(0, 0, 0, 0); th.setSpacing(8)
        self._author_input = _styled_lineedit("e.g. RadioAI")
        author_box = _LabeledField("Author", self._author_input)
        author_box.setFixedWidth(200)
        self._code_input = _styled_lineedit(
            self._existing.get("playlister_code") or "SS-0042", mono_font=True)
        code_box = _LabeledField("Playlister Code", self._code_input)
        code_box.setFixedWidth(160)
        self._date_input = _styled_lineedit("Now (Auto)")
        date_box = _LabeledField("Entry Date", self._date_input)
        date_box.setFixedWidth(184)
        th.addWidget(author_box); th.addWidget(code_box); th.addWidget(date_box)
        th.addStretch()
        v.addWidget(triple)

        # Comments
        self._comments_input = _styled_textedit(
            "Created automatically — auto-generated comment")
        v.addWidget(_LabeledField("Comments", self._comments_input))

        # CATEGORY section
        v.addWidget(_SectionHeader("CATEGORY", CYAN))
        cat_grid = QFrame(); cat_grid.setStyleSheet("background: transparent;")
        cv = QVBoxLayout(cat_grid)
        cv.setContentsMargins(0, 0, 0, 0); cv.setSpacing(8)
        for row_idx in range(2):
            row = QFrame(); row.setStyleSheet("background: transparent;")
            rh = QHBoxLayout(row)
            rh.setContentsMargins(0, 0, 0, 0); rh.setSpacing(8)
            for col in range(4):
                name = CATEGORY_OPTIONS[row_idx * 4 + col]
                tile = _CategoryTile(name)
                tile.setFixedWidth(134)
                tile.clicked.connect(
                    lambda _checked=False, n=name: self._on_category_picked(n))
                self._cat_tiles[name] = tile
                rh.addWidget(tile)
            rh.addStretch()
            cv.addWidget(row)
        v.addWidget(cat_grid)

        # TRACK PROPERTIES section
        v.addWidget(_SectionHeader("TRACK PROPERTIES", CYAN))
        props_row = QFrame()
        props_row.setStyleSheet("background: transparent;")
        ph = QHBoxLayout(props_row)
        ph.setContentsMargins(0, 0, 0, 0); ph.setSpacing(8)
        self._props_input = _styled_lineedit("Regular")
        props_box = _LabeledField("Properties", self._props_input)
        props_box.setFixedWidth(130)
        self._duration_input = _styled_lineedit("0:08", mono_font=True)
        dur_box = _LabeledField("Duration", self._duration_input)
        dur_box.setFixedWidth(130)
        self._bpm_input = _styled_lineedit("Optional")
        bpm_box = _LabeledField("BPM", self._bpm_input)
        bpm_box.setFixedWidth(130)
        self._era_input = _styled_lineedit(str(datetime.now().year))
        era_box = _LabeledField("Era / Year", self._era_input)
        era_box.setFixedWidth(146)
        ph.addWidget(props_box); ph.addWidget(dur_box)
        ph.addWidget(bpm_box); ph.addWidget(era_box); ph.addStretch()
        v.addWidget(props_row)

        # POSITION SETTINGS section + timeline + chip grid
        v.addWidget(_SectionHeader("POSITION SETTINGS", CYAN))
        self._timeline = _PositionTimelineStrip()
        v.addWidget(self._timeline)
        chip_grid = QFrame(); chip_grid.setStyleSheet("background: transparent;")
        gv = QVBoxLayout(chip_grid)
        gv.setContentsMargins(0, 0, 0, 0); gv.setSpacing(8)
        for row_idx in range(2):
            row = QFrame(); row.setStyleSheet("background: transparent;")
            rh = QHBoxLayout(row)
            rh.setContentsMargins(0, 0, 0, 0); rh.setSpacing(8)
            for col in range(3):
                name = POSITION_OPTIONS[row_idx * 3 + col]
                chip = _PositionChip(name)
                chip.setFixedWidth(182)
                chip.clicked.connect(
                    lambda _checked=False, n=name: self._on_position_picked(n))
                self._pos_chips[name] = chip
                rh.addWidget(chip)
            rh.addStretch()
            gv.addWidget(row)
        v.addWidget(chip_grid)

        # AUDIO FILE section
        v.addWidget(_SectionHeader("AUDIO FILE", AMBER))
        af_row = QFrame(); af_row.setStyleSheet("background: transparent;")
        ah = QHBoxLayout(af_row)
        ah.setContentsMargins(0, 0, 0, 0); ah.setSpacing(8)
        self._file_input = _styled_lineedit("C:\\Audio\\Sweepers\\select file...")
        ah.addWidget(self._file_input, 1)
        browse = QPushButton("…")
        browse.setFixedSize(34, 30)
        browse.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        browse.setFont(inter(11, QFont.Weight.Bold))
        browse.setStyleSheet(
            f"QPushButton {{ background: {BG_CARD}; color: {TEXT_SEC}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; border-radius: 6px; }}"
            f"QPushButton:hover {{ background: {rgba(CYAN, 0.16)}; "
            f"color: {CYAN_LIGHT}; }}"
        )
        browse.clicked.connect(self._on_browse_audio)
        ah.addWidget(browse)
        edit = QPushButton("Edit")
        edit.setFixedSize(44, 30)
        edit.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        edit.setFont(inter(10, QFont.Weight.Bold))
        edit.setStyleSheet(
            f"QPushButton {{ background: {BG_CARD}; color: {TEXT_MUTED}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; border-radius: 6px; }}"
            f"QPushButton:hover {{ background: {rgba(AMBER, 0.16)}; "
            f"color: {AMBER_LIGHT}; }}"
        )
        edit.clicked.connect(self._on_edit_audio_clicked)
        ah.addWidget(edit)
        v.addWidget(af_row)

        v.addStretch()
        return wrap

    # ── Right sidebar ────────────────────────────────────────────────────

    def _build_right_sidebar(self) -> QWidget:
        wrap = QFrame()
        wrap.setFixedWidth(RIGHT_W)
        wrap.setStyleSheet("background: transparent;")
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)

        # AVAILABILITY
        v.addWidget(_SectionHeader("AVAILABILITY", GREEN))
        self._availability = _AvailabilityCard()
        v.addWidget(self._availability)

        # OVERLAY BEHAVIOR
        v.addWidget(_SectionHeader("OVERLAY BEHAVIOR", AMBER))
        ov = QFrame()
        ov.setStyleSheet(
            f"background: {BG_CARD}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; border-radius: 6px;")
        ovv = QVBoxLayout(ov)
        ovv.setContentsMargins(10, 8, 10, 8); ovv.setSpacing(6)
        cap = QLabel("Volume during overlay")
        cap.setFont(inter(9, QFont.Weight.Medium))
        cap.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        ovv.addWidget(cap)
        self._song_vol = _VolumeSlider("Song Vol:", 60)
        ovv.addWidget(self._song_vol)
        self._swp_vol = _VolumeSlider("Swpr Vol:", 100)
        ovv.addWidget(self._swp_vol)
        cap2 = QLabel("↕ Plays simultaneously with song")
        cap2.setFont(inter(9, QFont.Weight.Medium))
        cap2.setStyleSheet(f"color: {AMBER_LIGHT}; background: transparent;")
        ovv.addWidget(cap2)
        v.addWidget(ov)

        # POSITION OFFSET
        v.addWidget(_SectionHeader("POSITION OFFSET", PURPLE_LIGHT))
        po_row = QFrame(); po_row.setStyleSheet("background: transparent;")
        poh = QHBoxLayout(po_row)
        poh.setContentsMargins(0, 0, 0, 0); poh.setSpacing(8)
        self._offset_input = _styled_lineedit("0.0 sec")
        self._offset_input.setValidator(
            QDoubleValidator(-60.0, 60.0, 1, self._offset_input))
        of_box = _LabeledField("Offset (s)", self._offset_input)
        of_box.setFixedWidth(130)
        self._fade_input = _styled_lineedit("0.5 sec")
        self._fade_input.setValidator(
            QDoubleValidator(0.0, 10.0, 1, self._fade_input))
        fd_box = _LabeledField("Fade (s)", self._fade_input)
        fd_box.setFixedWidth(142)
        poh.addWidget(of_box); poh.addWidget(fd_box); poh.addStretch()
        v.addWidget(po_row)

        # SCHEDULING — clock dropdown populated from `clocks` table
        v.addWidget(_SectionHeader("SCHEDULING", CYAN_LIGHT))
        clock_items, ids = self._fetch_clocks()
        self._clocks_index = ids
        self._clock_combo = _styled_combo(clock_items, default=clock_items[0])
        v.addWidget(_LabeledField("Clock Assignment", self._clock_combo))

        # SEPARATION
        v.addWidget(_SectionHeader("SEPARATION", PINK_LIGHT))
        sep_row = QFrame(); sep_row.setStyleSheet("background: transparent;")
        sh = QHBoxLayout(sep_row)
        sh.setContentsMargins(0, 0, 0, 0); sh.setSpacing(8)
        self._min_gap_input = _styled_lineedit("15")
        self._min_gap_input.setValidator(
            QIntValidator(0, 1440, self._min_gap_input))
        mg_box = _LabeledField("Min gap (min)", self._min_gap_input)
        mg_box.setFixedWidth(134)
        self._max_per_hour_input = _styled_lineedit("4")
        self._max_per_hour_input.setValidator(
            QIntValidator(0, 60, self._max_per_hour_input))
        mp_box = _LabeledField("Max per hour", self._max_per_hour_input)
        mp_box.setFixedWidth(138)
        sh.addWidget(mg_box); sh.addWidget(mp_box); sh.addStretch()
        v.addWidget(sep_row)

        # AI Auto-fill (stub)
        ai = _AICard()
        ai.clicked.connect(self._on_ai_autofill)
        v.addWidget(ai)

        v.addStretch()
        return wrap

    def _fetch_clocks(self) -> tuple[list[str], list[int]]:
        """Pull clocks from DB for the combo. Always include a default
        '— No clock —' sentinel at index 0 so the operator can save without
        binding to a clock."""
        items = ["— No clock —"]
        ids: list[int] = [0]   # 0 = no clock
        try:
            rows = self._db._conn().execute(
                "SELECT id, name FROM clocks ORDER BY id DESC"
            ).fetchall()
            for r in rows:
                items.append(str(r["name"] or f"Clock #{r['id']}"))
                ids.append(int(r["id"]))
        except Exception as exc:
            log.error(f"clocks fetch failed: {exc}")
        return items, ids

    # ── Footer ───────────────────────────────────────────────────────────

    def _build_footer(self) -> QWidget:
        f = QFrame()
        f.setStyleSheet(
            "QFrame { background: rgba(13,15,30,0.95); "
            f"border-top: 1px solid {rgba('#ffffff', 0.06)}; "
            "border-bottom-left-radius: 12px; "
            "border-bottom-right-radius: 12px; }"
        )
        rq = QLabel("* Required fields", f)
        rq.setGeometry(16, 18, 200, 14)
        rq.setFont(inter(9))
        rq.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

        cancel = QPushButton("Cancel", f)
        cancel.setGeometry(710, 12, 82, 30)
        cancel.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        cancel.setFont(inter(11, QFont.Weight.DemiBold))
        cancel.setStyleSheet(
            f"QPushButton {{ background: #1c1f38; color: {TEXT_SEC}; "
            f"border: none; border-radius: 6px; }}"
            f"QPushButton:hover {{ background: #262947; color: {TEXT_PRI}; }}"
        )
        cancel.clicked.connect(self.reject)

        save = QPushButton("✓ Save", f)
        save.setGeometry(800, 12, 84, 30)
        save.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        save.setFont(inter(11, QFont.Weight.Bold))
        save.setStyleSheet(
            f"QPushButton {{ background: {GREEN}; color: white; "
            f"border: none; border-radius: 6px; }}"
            f"QPushButton:hover {{ background: {GREEN_LIGHT}; }}"
        )
        save.clicked.connect(self._on_save)
        return f

    # ── Populate / commit ────────────────────────────────────────────────

    def _populate_from_existing(self):
        """Push values from self._existing into the widgets. Runs once after
        BaseDialog has built all zones."""
        # Always set selected category + position (defaults if NEW)
        self._sync_category_visual()
        self._sync_position_visual()
        if not self._mode_edit:
            return
        e = self._existing
        if self._title_input:
            self._title_input.setText(e.get("name") or "")
        if self._author_input:
            self._author_input.setText(e.get("author") or "")
        if self._code_input:
            self._code_input.setText(e.get("playlister_code") or "")
        if self._date_input:
            self._date_input.setText(e.get("entry_date") or "")
        if self._comments_input:
            self._comments_input.setPlainText(e.get("comments") or "")
        if self._props_input:
            self._props_input.setText(e.get("properties") or "")
        if self._duration_input:
            self._duration_input.setText(
                _fmt_duration(e.get("duration_ms") or 0))
        if self._bpm_input:
            self._bpm_input.setText(e.get("bpm") or "")
        if self._era_input:
            self._era_input.setText(e.get("era_year") or "")
        if self._file_input:
            self._file_input.setText(e.get("file_path") or "")
        if self._availability:
            self._availability.set_enabled(bool(e.get("is_enabled", 1)))
        if self._song_vol:
            self._song_vol.set_value(int(e.get("volume_song_pct") or 60))
        if self._swp_vol:
            self._swp_vol.set_value(int(e.get("volume_sweeper_pct") or 100))
        if self._offset_input:
            self._offset_input.setText(
                f"{float(e.get('offset_seconds') or 0.0):.1f}")
        if self._fade_input:
            self._fade_input.setText(
                f"{float(e.get('fade_seconds') or 0.5):.1f}")
        if self._clock_combo:
            cid = int(e.get("clock_id") or 0)
            if cid in self._clocks_index:
                self._clock_combo.setCurrentIndex(
                    self._clocks_index.index(cid))
        if self._min_gap_input:
            self._min_gap_input.setText(str(int(e.get("min_gap_minutes")
                                                or 15)))
        if self._max_per_hour_input:
            self._max_per_hour_input.setText(str(int(e.get("max_per_hour")
                                                     or 4)))

    def _collect_values(self) -> dict:
        """Pull current widget state into a dict matching
        Database.SWEEPER_EDITABLE_FIELDS."""
        cur_clock_id = 0
        if self._clock_combo:
            idx = self._clock_combo.currentIndex()
            if 0 <= idx < len(self._clocks_index):
                cur_clock_id = self._clocks_index[idx]
        return {
            "name":               (self._title_input.text() if self._title_input
                                   else "").strip(),
            "category":           self._selected_category,
            "file_path":          (self._file_input.text() if self._file_input
                                   else "").strip(),
            "duration_ms":        _parse_duration(
                self._duration_input.text() if self._duration_input else ""),
            "position":           self._selected_position,
            "properties":         (self._props_input.text() if self._props_input
                                   else "").strip(),
            "playlister_code":    (self._code_input.text() if self._code_input
                                   else "").strip(),
            "is_enabled":         self._availability.is_enabled()
                                   if self._availability else True,
            "author":             (self._author_input.text() if self._author_input
                                   else "").strip(),
            "entry_date":         self._effective_entry_date(),
            "comments":           (self._comments_input.toPlainText()
                                   if self._comments_input else "").strip(),
            "bpm":                (self._bpm_input.text() if self._bpm_input
                                   else "").strip(),
            "era_year":           (self._era_input.text() if self._era_input
                                   else "").strip(),
            "volume_song_pct":    self._song_vol.value() if self._song_vol else 60,
            "volume_sweeper_pct": self._swp_vol.value() if self._swp_vol else 100,
            "offset_seconds":     self._safe_float(
                self._offset_input.text() if self._offset_input else "", 0.0),
            "fade_seconds":       self._safe_float(
                self._fade_input.text() if self._fade_input else "", 0.5),
            "clock_id":           cur_clock_id or None,
            "min_gap_minutes":    self._safe_int(
                self._min_gap_input.text() if self._min_gap_input else "", 15),
            "max_per_hour":       self._safe_int(
                self._max_per_hour_input.text()
                if self._max_per_hour_input else "", 4),
        }

    def _effective_entry_date(self) -> str:
        text = (self._date_input.text() if self._date_input else "").strip()
        if not text or text.lower().startswith("now"):
            return datetime.now().strftime("%Y-%m-%d")
        return text

    @staticmethod
    def _safe_float(text: str, default: float) -> float:
        try:
            return float((text or "").strip().split()[0])
        except Exception:
            return default

    @staticmethod
    def _safe_int(text: str, default: int) -> int:
        try:
            return int((text or "").strip().split()[0])
        except Exception:
            return default

    # ── Event handlers ───────────────────────────────────────────────────

    def _on_category_picked(self, name: str):
        self._selected_category = name
        self._sync_category_visual()

    def _sync_category_visual(self):
        for n, tile in self._cat_tiles.items():
            tile.set_active(n == self._selected_category)

    def _on_position_picked(self, name: str):
        self._selected_position = name
        self._sync_position_visual()

    def _sync_position_visual(self):
        for n, chip in self._pos_chips.items():
            chip.set_active(n == self._selected_position)

    def _on_browse_audio(self):
        start_dir = ""
        if self._file_input and self._file_input.text():
            start_dir = os.path.dirname(self._file_input.text())
        path, _ = QFileDialog.getOpenFileName(
            self, "Select sweeper audio file", start_dir,
            "Audio files (*.mp3 *.wav *.ogg *.flac *.m4a);;All files (*.*)")
        if path and self._file_input:
            self._file_input.setText(path)

    def _on_edit_audio_clicked(self):
        # AudioCueEditorDialog hookup deferred — explicit toast.
        QMessageBox.information(
            self, "Coming soon",
            "Audio cue editor for sweepers is being wired in a follow-up "
            "session — for now, set the file path here and adjust cue points "
            "via the Songs Library audio editor on the source file.")

    def _on_ai_autofill(self):
        QMessageBox.information(
            self, "Coming soon",
            "AI Auto-fill Metadata will detect the natural sweeper position "
            "from the audio file. Hookup deferred — populate fields manually "
            "for now.")

    def _on_save(self):
        data = self._collect_values()
        # Required: title
        if not data["name"]:
            QMessageBox.warning(
                self, "Missing required field",
                "Sweeper Title is required.")
            if self._title_input:
                self._title_input.setFocus()
            return
        try:
            if self._mode_edit:
                self._db.update_sweeper(int(self._sweeper_id), data)
                new_id = int(self._sweeper_id)
            else:
                new_id = self._db.add_sweeper(data)
        except Exception as exc:
            log.error(f"save failed: {exc}", exc_info=True)
            QMessageBox.critical(
                self, "Save failed",
                f"Could not save sweeper:\n\n{exc}")
            return
        log.info(
            f"Sweeper saved: id={new_id} "
            f"({'EDIT' if self._mode_edit else 'NEW'}) "
            f"name={data['name']!r} position={data['position']!r}")
        self.sweeper_saved.emit(int(new_id))
        self.accept()
