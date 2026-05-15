"""
RadioAI Studio Pro — Add New Song dialog
Figma node 28:2 (file 7oN9K61g94wKx3nu44KKDF).

Built on BaseDialog with the 3-zone layout pattern:
- Header pinned at top (NEW SONG title + AUTO CODE + close)
- Scrollable middle (form fields, category, track properties, audio file
  + right sidebar with availability/linked/properties/separation/AI banner)
- Footer pinned at bottom (Cancel + ✓ Save) — ALWAYS reachable

Adaptive sizing: the dialog never exceeds 95%×92% of the available screen,
so the bottom Save/Cancel buttons cannot be pushed offscreen on a 1366×768
laptop. A premium scrollbar appears for content that doesn't fit.
"""

import logging
import os
import random
from datetime import datetime
from typing import Optional

from PyQt6.QtCore import Qt, QRectF, pyqtSignal
from core import dialogs
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QLinearGradient, QPainterPath, QFont,
    QCursor,
)
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QLineEdit, QComboBox, QTextEdit,
    QFileDialog, QMessageBox, QHBoxLayout, QVBoxLayout, QGridLayout,
    QSizePolicy, QSpacerItem,
)

from ui.widgets._tokens import (
    inter, mono, rgba,
    TEXT_PRI, TEXT_SEC, TEXT_MUTED, TEXT_DIM,
    CYAN, CYAN_LIGHT, PURPLE, PURPLE_LIGHT, GREEN, GREEN_LIGHT,
    AMBER, AMBER_LIGHT, RED, RED_LIGHT,
)
from ui.dialogs.base_dialog import BaseDialog

log = logging.getLogger("AddNewSongDialog")

INPUT_BG = "#0a0c18"
INPUT_BORDER = rgba("#ffffff", 0.06)
SECTION_BG = "#131626"


# ════════════════════════════════════════════════════════════════════════════
# Reusable styled widgets
# ════════════════════════════════════════════════════════════════════════════

def _muted_label(text: str) -> QLabel:
    l = QLabel(text)
    l.setFont(inter(10, QFont.Weight.Medium))
    l.setStyleSheet(f"color: {TEXT_SEC}; background: transparent;")
    l.setFixedHeight(14)
    return l


def _required_label(text: str) -> QLabel:
    l = QLabel(f"{text} <span style='color:{RED};'>*</span>")
    l.setFont(inter(10, QFont.Weight.Medium))
    l.setStyleSheet(f"color: {TEXT_SEC}; background: transparent;")
    l.setFixedHeight(14)
    return l


def _make_input(placeholder: str = "", height: int = 32) -> QLineEdit:
    e = QLineEdit()
    e.setPlaceholderText(placeholder)
    e.setFixedHeight(height)
    e.setFont(inter(10))
    e.setStyleSheet(
        f"QLineEdit {{ background: {INPUT_BG}; color: {TEXT_PRI}; "
        f"border: 1px solid {INPUT_BORDER}; border-radius: 6px; "
        f"padding-left: 8px; padding-right: 8px; "
        f"selection-background-color: {rgba(CYAN, 0.25)}; }}"
        f"QLineEdit:focus {{ border-color: {CYAN}; background: #06080f; }}"
    )
    return e


def _make_combo(items: list, height: int = 28) -> QComboBox:
    c = QComboBox()
    c.addItems(items)
    c.setFixedHeight(height)
    c.setFont(inter(10))
    c.setStyleSheet(
        f"QComboBox {{ background: {INPUT_BG}; color: {TEXT_PRI}; "
        f"border: 1px solid {INPUT_BORDER}; border-radius: 6px; "
        f"padding-left: 8px; padding-right: 24px; }}"
        f"QComboBox:focus {{ border-color: {CYAN}; }}"
        f"QComboBox::drop-down {{ border: none; width: 18px; }}"
        f"QComboBox::down-arrow {{ image: none; width: 0; height: 0; "
        f"border-left: 4px solid transparent; border-right: 4px solid transparent; "
        f"border-top: 5px solid {TEXT_MUTED}; margin-right: 6px; }}"
        f"QComboBox QAbstractItemView {{ background: {INPUT_BG}; color: {TEXT_PRI}; "
        f"border: 1px solid {INPUT_BORDER}; border-radius: 5px; "
        f"selection-background-color: {rgba(CYAN, 0.20)}; selection-color: {CYAN_LIGHT}; "
        f"outline: none; padding: 4px; }}"
    )
    return c


def _make_field(label_widget: QLabel, control: QWidget) -> QWidget:
    """Compose a label-on-top-of-input vertical field."""
    w = QWidget()
    w.setStyleSheet("background: transparent;")
    v = QVBoxLayout(w)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(4)
    v.addWidget(label_widget)
    v.addWidget(control)
    return w


# ════════════════════════════════════════════════════════════════════════════
# Section header strip (full width inside its column)
# ════════════════════════════════════════════════════════════════════════════

class _SectionHeader(QFrame):

    def __init__(self, text: str, accent_color: str = "#252848",
                 text_color: str = "#7b7d9a", parent=None):
        super().__init__(parent)
        self._text = text.upper()
        self._accent = QColor(accent_color)
        self._text_color = QColor(text_color)
        self.setFixedHeight(24)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Fixed)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0, 0, self.width(), self.height())
        path = QPainterPath()
        path.addRoundedRect(rect, 4, 4)
        p.setClipPath(path)
        p.fillRect(rect, QColor(SECTION_BG))
        p.fillRect(0, 0, 3, int(self.height()), self._accent)
        p.setClipping(False)
        p.setPen(self._text_color)
        p.setFont(inter(11, QFont.Weight.DemiBold, letter_spacing=1.0))
        p.drawText(10, 0, int(self.width()) - 14, int(self.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   self._text)


# ════════════════════════════════════════════════════════════════════════════
# Header logo (28×28)
# ════════════════════════════════════════════════════════════════════════════

class _HeaderLogo(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(28, 28)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, 28, 28), 6, 6)
        p.setClipPath(path)
        p.fillRect(QRectF(0, 0, 28, 28), QColor("#1e1535"))
        p.setBrush(QColor("#a78bfa"))
        p.setPen(Qt.PenStyle.NoPen)
        for x_off, h in [(5, 4), (10, 8), (15, 12), (20, 8), (25, 4)]:
            top = (28 - h) // 2
            p.drawRoundedRect(QRectF(x_off - 1.5, top, 3, h), 1, 1)


# ════════════════════════════════════════════════════════════════════════════
# Category pill
# ════════════════════════════════════════════════════════════════════════════

class _CategoryPill(QPushButton):
    toggled_active = pyqtSignal(str)

    def __init__(self, text: str, color: str = AMBER, parent=None):
        super().__init__(text, parent)
        self._color = QColor(color)
        self._active = False
        self.setFixedSize(74, 28)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFlat(True)
        self.setStyleSheet("background: transparent; border: none;")
        self.setFont(inter(9, QFont.Weight.DemiBold))

    def set_active(self, active: bool):
        self._active = active
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.toggled_active.emit(self.text())
        super().mousePressEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0, 0, 74, 28)
        path = QPainterPath()
        path.addRoundedRect(rect, 6, 6)
        p.setClipPath(path)
        if self._active:
            p.fillRect(rect, QColor("#2d1a00"))
            p.setClipping(False)
            p.fillRect(0, 0, 2, 28, self._color)
            p.setPen(self._color)
            p.setFont(inter(9, QFont.Weight.DemiBold))
        else:
            p.fillRect(rect, QColor("#1c1f38"))
            p.setClipping(False)
            p.setPen(QColor(TEXT_MUTED))
            p.setFont(inter(9))
        p.drawText(8 if self._active else 6, 0, 70, 28,
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   self.text())


# ════════════════════════════════════════════════════════════════════════════
# Custom checkbox
# ════════════════════════════════════════════════════════════════════════════

class _Checkbox(QPushButton):

    def __init__(self, color: str = GREEN, parent=None):
        super().__init__("", parent)
        self._color = QColor(color)
        self._checked = False
        self.setFixedSize(16, 16)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFlat(True)
        self.setStyleSheet("background: transparent; border: none;")
        self.clicked.connect(self.toggle)

    def setChecked(self, c): self._checked = c; self.update()
    def isChecked(self): return self._checked
    def toggle(self): self._checked = not self._checked; self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0, 0, 16, 16)
        path = QPainterPath()
        path.addRoundedRect(rect, 4, 4)
        p.setClipPath(path)
        if self._checked:
            tint = QColor(self._color); tint.setAlphaF(0.20)
            p.fillRect(rect, tint)
            inner = QRectF(2, 2, 12, 12)
            inner_path = QPainterPath()
            inner_path.addRoundedRect(inner, 3, 3)
            p.fillPath(inner_path, self._color)
            p.setClipping(False)
            p.setPen(QColor("#ffffff"))
            p.setFont(inter(9, QFont.Weight.Bold))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, "✓")
        else:
            p.fillRect(rect, QColor("#252848"))


# ════════════════════════════════════════════════════════════════════════════
# Mini ± button
# ════════════════════════════════════════════════════════════════════════════

class _MiniIconBtn(QPushButton):
    def __init__(self, glyph: str, parent=None):
        super().__init__(glyph, parent)
        self.setFixedSize(22, 20)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFlat(True)
        self.setFont(inter(12, QFont.Weight.Bold))
        self.setStyleSheet(
            f"QPushButton {{ background: #252848; color: {TEXT_SEC}; "
            f"border: none; border-radius: 6px; padding: 0; }}"
            f"QPushButton:hover {{ background: {rgba(CYAN, 0.30)}; color: {CYAN_LIGHT}; }}"
        )


# ════════════════════════════════════════════════════════════════════════════
# Mini waveform shown in audio preview band
# ════════════════════════════════════════════════════════════════════════════

class _MiniWaveform(QWidget):

    def __init__(self, n_bars: int = 92, parent=None):
        super().__init__(parent)
        import math, random as r
        r.seed(28)
        self._n = n_bars
        self._heights = []
        for i in range(n_bars):
            phase = i / n_bars * 2 * math.pi * 4
            base = 6 + 5 * math.sin(phase) + r.uniform(-3, 3)
            self._heights.append(max(2, min(12, int(base))))
        self.setMinimumHeight(36)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0, 0, self.width(), self.height())
        path = QPainterPath()
        path.addRoundedRect(rect, 6, 6)
        p.setClipPath(path)
        p.fillRect(rect, QColor(INPUT_BG))
        p.setClipping(False)
        p.setPen(QPen(QColor(28, 31, 56, 102), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 6, 6)

        cy = self.height() / 2
        bar_w = 4
        gap = 2
        c = QColor(PURPLE); c.setAlphaF(0.4)
        p.setBrush(c); p.setPen(Qt.PenStyle.NoPen)
        for i in range(self._n):
            x = 90 + i * (bar_w + gap)  # offset 90 to clear "▶ Preview"
            if x + bar_w > self.width() - 4:
                break
            h = self._heights[i]
            p.drawRoundedRect(QRectF(x, cy - h / 2, bar_w, h), 1, 1)

        # ▶ Preview overlay text
        p.setPen(QColor(PURPLE_LIGHT))
        p.setFont(inter(10, QFont.Weight.DemiBold))
        p.drawText(14, 0, 80, int(self.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   "▶ Preview")


# ════════════════════════════════════════════════════════════════════════════
# Main dialog
# ════════════════════════════════════════════════════════════════════════════

class AddNewSongDialog(BaseDialog):
    """Modal dialog — add a new song. Emits song_saved(dict) on success."""

    song_saved = pyqtSignal(dict)

    HEADER_H = 52
    FOOTER_H = 52

    def __init__(self, parent=None, db=None):
        self._db = db
        self._auto_code = f"{random.randint(100000, 999999)}"
        self._selected_category = "Hot Currents"
        self._audio_file_path: Optional[str] = None
        # Refs filled during build
        self._artist_input = self._title_input = self._album_input = None
        self._playlister_input = self._label_input = self._cdkey_input = None
        self._barcode_input = self._songwriter_input = self._composer_input = None
        self._comments_box = self._filename_input = None
        self._era_combo = self._vocal_combo = self._priority_combo = None
        self._year_combo = self._bpm_combo = None
        self._enabled_chk = self._frozen_chk = None
        self._cat_pills: dict = {}

        super().__init__(target_size=(920, 720), parent=parent)

    # ── Header ────────────────────────────────────────────────────────────

    def _build_header(self) -> QWidget:
        f = QFrame()
        f.setStyleSheet(
            f"QFrame {{ background: #0d0f1e; border-bottom: 1px solid #1c1f38; }}"
        )
        h = QHBoxLayout(f)
        h.setContentsMargins(14, 10, 10, 10)
        h.setSpacing(12)

        h.addWidget(_HeaderLogo())

        # Title + subtitle stacked
        title_box = QWidget(); title_box.setStyleSheet("background: transparent;")
        tv = QVBoxLayout(title_box)
        tv.setContentsMargins(0, 0, 0, 0); tv.setSpacing(2)
        title = QLabel("NEW SONG")
        title.setFont(inter(16, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        sub = QLabel("Add a new track to your music library")
        sub.setFont(inter(10))
        sub.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        tv.addWidget(title); tv.addWidget(sub)
        h.addWidget(title_box)
        h.addStretch()

        # AUTO CODE box
        code_box = QFrame()
        code_box.setFixedSize(110, 32)
        code_box.setStyleSheet("background: #1e1535; border-radius: 6px;")
        cv = QVBoxLayout(code_box)
        cv.setContentsMargins(8, 4, 8, 4); cv.setSpacing(0)
        ac_lbl = QLabel("AUTO CODE")
        ac_lbl.setFont(inter(8, QFont.Weight.Medium, letter_spacing=1.0))
        ac_lbl.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        ac_val = QLabel(self._auto_code)
        ac_val.setFont(mono(12))
        ac_val.setStyleSheet(f"color: {PURPLE_LIGHT}; background: transparent;")
        cv.addWidget(ac_lbl); cv.addWidget(ac_val)
        h.addWidget(code_box)

        # Close ✕
        x_btn = QPushButton("✕")
        x_btn.setFixedSize(30, 30)
        x_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        x_btn.setFont(inter(13, QFont.Weight.Bold))
        x_btn.setStyleSheet(
            f"QPushButton {{ background: #1c1f38; color: {TEXT_SEC}; "
            f"border: none; border-radius: 6px; }}"
            f"QPushButton:hover {{ background: {rgba(RED, 0.20)}; color: {RED_LIGHT}; }}"
        )
        x_btn.clicked.connect(self.reject)
        h.addWidget(x_btn)
        return f

    # ── Content (scrollable) ──────────────────────────────────────────────

    def _build_content(self) -> QWidget:
        # Outer content widget (fills scroll area, vertical-only scroll)
        content = QFrame()
        content.setStyleSheet("background: transparent;")
        outer = QHBoxLayout(content)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(20)

        outer.addWidget(self._build_left_column(), stretch=60)
        outer.addWidget(self._build_right_column(), stretch=40)

        return content

    # ── Left column ───────────────────────────────────────────────────────

    def _build_left_column(self) -> QWidget:
        col = QWidget()
        col.setStyleSheet("background: transparent;")
        v = QVBoxLayout(col)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(14)

        # Artist row
        self._artist_input = _make_input("Type artist name...")
        find_btn = QPushButton("Find Artist")
        find_btn.setFixedSize(72, 32)
        find_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        find_btn.setFont(inter(10, QFont.Weight.DemiBold))
        find_btn.setStyleSheet(
            f"QPushButton {{ background: #1e1535; color: {PURPLE_LIGHT}; "
            f"border: none; border-left: 2px solid {PURPLE}; border-radius: 7px; }}"
            f"QPushButton:hover {{ background: {rgba(PURPLE, 0.25)}; }}"
        )
        find_btn.clicked.connect(self._open_find_artist)
        new_btn = QPushButton("+ New")
        new_btn.setFixedSize(72, 32)
        new_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        new_btn.setFont(inter(10, QFont.Weight.DemiBold))
        new_btn.setStyleSheet(
            f"QPushButton {{ background: #052e16; color: {GREEN}; "
            f"border: none; border-left: 2px solid {GREEN}; border-radius: 7px; }}"
            f"QPushButton:hover {{ background: {rgba(GREEN, 0.25)}; }}"
        )
        new_btn.clicked.connect(self._open_add_artist)
        artist_row = QWidget(); artist_row.setStyleSheet("background: transparent;")
        ar_v = QVBoxLayout(artist_row)
        ar_v.setContentsMargins(0, 0, 0, 0); ar_v.setSpacing(4)
        ar_v.addWidget(_required_label("Artist"))
        ar_h = QHBoxLayout()
        ar_h.setContentsMargins(0, 0, 0, 0); ar_h.setSpacing(8)
        ar_h.addWidget(self._artist_input, stretch=1)
        ar_h.addWidget(find_btn); ar_h.addWidget(new_btn)
        ar_v.addLayout(ar_h)
        v.addWidget(artist_row)

        # Song Title (full width)
        self._title_input = _make_input("Enter full song title...")
        v.addWidget(_make_field(_required_label("Song Title"), self._title_input))

        # Album / Playlister Code
        self._album_input = _make_input("Album name", height=28)
        self._playlister_input = _make_input("e.g. S0015", height=28)
        row = QHBoxLayout()
        row.setSpacing(14)
        row.addWidget(_make_field(_muted_label("Album"), self._album_input), stretch=1)
        row.addWidget(_make_field(_muted_label("Playlister Code"), self._playlister_input), stretch=1)
        v.addLayout(row)

        # Label / CD Key / Barcode
        self._label_input   = _make_input("Record label",   height=28)
        self._cdkey_input   = _make_input("CD key",         height=28)
        self._barcode_input = _make_input("Barcode number", height=28)
        row = QHBoxLayout()
        row.setSpacing(14)
        row.addWidget(_make_field(_muted_label("Label"),   self._label_input),   stretch=1)
        row.addWidget(_make_field(_muted_label("CD Key"),  self._cdkey_input),   stretch=1)
        row.addWidget(_make_field(_muted_label("Barcode"), self._barcode_input), stretch=1)
        v.addLayout(row)

        # Songwriter / Comments
        self._songwriter_input = _make_input("Songwriter", height=28)
        self._comments_box = QTextEdit()
        self._comments_box.setFixedHeight(56)
        self._comments_box.setFont(inter(10))
        creator = os.environ.get("USERNAME", "User")
        now = datetime.now().strftime("%#m/%#d/%Y %#I:%M:%S %p" if os.name == "nt" else "%-m/%-d/%Y %-I:%M:%S %p")
        self._comments_box.setPlainText(f"Created by DESKTOP\\{creator} on {now}")
        self._comments_box.setStyleSheet(
            f"QTextEdit {{ background: {INPUT_BG}; color: {TEXT_MUTED}; "
            f"border: 1px solid {INPUT_BORDER}; border-radius: 6px; "
            f"padding: 6px 8px; font-size: 10px; }}"
            f"QTextEdit:focus {{ border-color: {CYAN}; color: {TEXT_PRI}; }}"
        )
        row = QHBoxLayout()
        row.setSpacing(14)
        row.addWidget(_make_field(_muted_label("Songwriter"), self._songwriter_input), stretch=1)
        row.addWidget(_make_field(_muted_label("Comments"),   self._comments_box),     stretch=2)
        v.addLayout(row)

        # Composer
        self._composer_input = _make_input("Composer name", height=28)
        comp_w = _make_field(_muted_label("Composer"), self._composer_input)
        # Match Figma: composer is half-width
        comp_wrapper = QHBoxLayout()
        comp_wrapper.setContentsMargins(0, 0, 0, 0); comp_wrapper.setSpacing(0)
        comp_wrapper.addWidget(comp_w, stretch=1)
        comp_wrapper.addStretch(1)
        v.addLayout(comp_wrapper)

        # CATEGORY section
        cat_hdr = _SectionHeader("CATEGORY", accent_color=PURPLE,
                                 text_color=PURPLE_LIGHT)
        v.addSpacing(4)
        v.addWidget(cat_hdr)

        cat_row = QHBoxLayout()
        cat_row.setContentsMargins(0, 4, 0, 0); cat_row.setSpacing(6)
        for name in ["Hot Currents", "Classics", "Pop", "Oldies", "Dance", "Rock", "R&B"]:
            pill = _CategoryPill(name, color=AMBER)
            pill.set_active(name == "Hot Currents")
            pill.toggled_active.connect(self._on_cat_pill)
            self._cat_pills[name] = pill
            cat_row.addWidget(pill)
        cat_row.addStretch()
        v.addLayout(cat_row)

        # TRACK PROPERTIES section
        v.addSpacing(8)
        v.addWidget(_SectionHeader("TRACK PROPERTIES"))

        # 5 dropdowns
        cur_y = datetime.now().year
        self._era_combo      = _make_combo(["Select...", "60s", "70s", "80s", "90s", "2000s", "2010s", "2020s"])
        self._vocal_combo    = _make_combo(["Select...", "Male", "Female", "Group", "Instrumental"])
        self._priority_combo = _make_combo([str(i) for i in range(1, 10)])
        self._year_combo     = _make_combo(["Select..."] + [str(y) for y in range(cur_y, 1949, -1)])
        self._year_combo.setCurrentText(str(cur_y))
        self._bpm_combo      = _make_combo(["Select..."] + [str(b) for b in range(60, 201, 5)])
        prop_row = QHBoxLayout()
        prop_row.setContentsMargins(0, 4, 0, 0); prop_row.setSpacing(10)
        prop_row.addWidget(_make_field(_muted_label("ERA"),      self._era_combo),      stretch=1)
        prop_row.addWidget(_make_field(_muted_label("Vocal"),    self._vocal_combo),    stretch=1)
        prop_row.addWidget(_make_field(_muted_label("Priority"), self._priority_combo), stretch=1)
        prop_row.addWidget(_make_field(_muted_label("Year"),     self._year_combo),     stretch=1)
        prop_row.addWidget(_make_field(_muted_label("BPM"),      self._bpm_combo),      stretch=1)
        v.addLayout(prop_row)

        # AUDIO FILE section
        v.addSpacing(8)
        v.addWidget(_SectionHeader("AUDIO FILE"))

        self._filename_input = _make_input(r"C:\Audio\Songs\select file...", height=30)
        browse_btn = QPushButton("...")
        browse_btn.setFixedSize(34, 30)
        browse_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        browse_btn.setFont(inter(11, QFont.Weight.Bold))
        browse_btn.setStyleSheet(
            f"QPushButton {{ background: #252848; color: {TEXT_SEC}; "
            f"border: none; border-radius: 6px; }}"
            f"QPushButton:hover {{ background: {rgba(CYAN, 0.30)}; color: {CYAN_LIGHT}; }}"
        )
        browse_btn.clicked.connect(self._on_browse)
        edit_btn = QPushButton("Edit")
        edit_btn.setFixedSize(36, 30)
        edit_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        edit_btn.setFont(inter(10, QFont.Weight.DemiBold))
        edit_btn.setStyleSheet(
            f"QPushButton {{ background: #1e1535; color: {PURPLE_LIGHT}; "
            f"border: none; border-left: 2px solid {PURPLE}; border-radius: 6px; }}"
            f"QPushButton:hover {{ background: {rgba(PURPLE, 0.25)}; }}"
        )
        file_row = QWidget(); file_row.setStyleSheet("background: transparent;")
        fr_v = QVBoxLayout(file_row); fr_v.setContentsMargins(0, 4, 0, 0); fr_v.setSpacing(4)
        fr_v.addWidget(_muted_label("Filename"))
        fr_h = QHBoxLayout()
        fr_h.setContentsMargins(0, 0, 0, 0); fr_h.setSpacing(8)
        fr_h.addWidget(self._filename_input, stretch=1)
        fr_h.addWidget(browse_btn); fr_h.addWidget(edit_btn)
        fr_v.addLayout(fr_h)
        v.addWidget(file_row)

        # Waveform preview
        v.addWidget(_MiniWaveform())

        v.addStretch()
        return col

    # ── Right column ──────────────────────────────────────────────────────

    def _build_right_column(self) -> QWidget:
        col = QWidget()
        col.setStyleSheet("background: transparent;")
        v = QVBoxLayout(col)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(14)

        # Entry Date
        ed_box = QFrame()
        ed_box.setFixedHeight(26)
        ed_box.setStyleSheet("background: #1c1f38; border-radius: 6px;")
        ed_l = QHBoxLayout(ed_box)
        ed_l.setContentsMargins(8, 0, 8, 0); ed_l.setSpacing(0)
        ed_lbl = QLabel("Now  (Auto)")
        ed_lbl.setFont(inter(11))
        ed_lbl.setStyleSheet(f"color: {TEXT_SEC}; background: transparent;")
        ed_l.addWidget(ed_lbl); ed_l.addStretch()
        v.addWidget(_make_field(_muted_label("Entry Date"), ed_box))

        # AVAILABILITY section
        v.addSpacing(4)
        v.addWidget(_SectionHeader("AVAILABILITY"))

        av_card = QFrame()
        av_card.setFixedHeight(58)
        av_card.setStyleSheet(
            f"QFrame {{ background: {rgba(GREEN, 0.06)}; "
            f"border-left: 3px solid {GREEN}; border-radius: 8px; }}"
        )
        av_grid = QGridLayout(av_card)
        av_grid.setContentsMargins(8, 8, 8, 8)
        av_grid.setHorizontalSpacing(8)
        av_grid.setVerticalSpacing(4)
        # Row 0: Enabled
        self._enabled_chk = _Checkbox(GREEN); self._enabled_chk.setChecked(True)
        en_lbl = QLabel("Enabled")
        en_lbl.setFont(inter(12, QFont.Weight.DemiBold))
        en_lbl.setStyleSheet(f"color: {GREEN}; background: transparent;")
        en_sub = QLabel("Song will appear in auto scheduling")
        en_sub.setFont(inter(9))
        en_sub.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        av_grid.addWidget(self._enabled_chk, 0, 0)
        av_grid.addWidget(en_lbl, 0, 1, Qt.AlignmentFlag.AlignLeft)
        av_grid.addWidget(en_sub, 1, 1, Qt.AlignmentFlag.AlignLeft)
        # Row 2: Frozen
        self._frozen_chk = _Checkbox("#252848")
        fr_lbl = QLabel("Frozen (Not Selected in Auto)")
        fr_lbl.setFont(inter(10))
        fr_lbl.setStyleSheet(f"color: {TEXT_SEC}; background: transparent;")
        av_grid.addWidget(self._frozen_chk, 2, 0)
        av_grid.addWidget(fr_lbl, 2, 1, Qt.AlignmentFlag.AlignLeft)
        v.addWidget(av_card)

        # LINKED SONGS section
        v.addSpacing(4)
        v.addWidget(self._build_section_with_buttons("LINKED SONGS"))
        v.addWidget(self._build_empty_box("No linked songs", height=72))

        # SONG PROPERTIES section
        v.addSpacing(4)
        v.addWidget(self._build_section_with_buttons("SONG PROPERTIES"))
        v.addWidget(self._build_empty_box("No properties assigned", height=72))

        # SONG SEPARATION section
        v.addSpacing(4)
        v.addWidget(_SectionHeader("SONG SEPARATION"))
        sep_card = QFrame()
        sep_card.setStyleSheet(f"QFrame {{ background: #171825; border-radius: 8px; }}")
        sep_v = QVBoxLayout(sep_card)
        sep_v.setContentsMargins(10, 8, 10, 10); sep_v.setSpacing(4)
        sep_lbl = QLabel("Override global separation time")
        sep_lbl.setFont(inter(10, QFont.Weight.Medium))
        sep_lbl.setStyleSheet(f"color: {TEXT_SEC}; background: transparent;")
        sep_v.addWidget(sep_lbl)
        sep_combo = _make_combo(["Use global settings", "Custom..."])
        sep_v.addWidget(sep_combo)
        v.addWidget(sep_card)

        # AI Auto-fill banner
        v.addSpacing(6)
        ai_btn = QPushButton("✦  AI Auto-fill Metadata")
        ai_btn.setFixedHeight(34)
        ai_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        ai_btn.setFont(inter(11, QFont.Weight.DemiBold))
        ai_btn.setStyleSheet(
            f"QPushButton {{ background: #1e1535; color: {PURPLE_LIGHT}; "
            f"border: none; border-left: 3px solid {PURPLE}; border-radius: 8px; "
            f"text-align: left; padding-left: 18px; }}"
            f"QPushButton:hover {{ background: {rgba(PURPLE, 0.25)}; color: {TEXT_PRI}; }}"
        )
        ai_btn.clicked.connect(self._on_ai_autofill)
        v.addWidget(ai_btn)

        v.addStretch()
        return col

    def _build_section_with_buttons(self, text: str) -> QWidget:
        """Section header + +/- buttons on the right."""
        w = QWidget(); w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0); h.setSpacing(6)
        h.addWidget(_SectionHeader(text), stretch=1)
        h.addWidget(_MiniIconBtn("+"))
        h.addWidget(_MiniIconBtn("−"))
        return w

    def _build_empty_box(self, text: str, height: int = 72) -> QWidget:
        f = QFrame()
        f.setFixedHeight(height)
        f.setStyleSheet(
            f"QFrame {{ background: #171825; border: 1px solid {INPUT_BORDER}; "
            f"border-radius: 8px; }}"
        )
        v = QVBoxLayout(f)
        v.setContentsMargins(0, 0, 0, 0); v.setSpacing(0)
        l = QLabel(text)
        l.setAlignment(Qt.AlignmentFlag.AlignCenter)
        l.setFont(inter(10))
        l.setStyleSheet(f"color: {TEXT_DIM}; background: transparent;")
        v.addWidget(l)
        return f

    # ── Footer ────────────────────────────────────────────────────────────

    def _build_footer(self) -> QWidget:
        f = QFrame()
        f.setStyleSheet(
            f"QFrame {{ background: #0d0f1e; border-top: 1px solid #1c1f38; }}"
        )
        h = QHBoxLayout(f)
        h.setContentsMargins(20, 10, 20, 10); h.setSpacing(10)

        l = QLabel("* Required fields")
        l.setFont(inter(10))
        l.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        h.addWidget(l)
        h.addStretch()

        cancel = QPushButton("Cancel")
        cancel.setFixedSize(82, 32)
        cancel.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        cancel.setFont(inter(12, QFont.Weight.Medium))
        cancel.setStyleSheet(
            f"QPushButton {{ background: #1c1f38; color: {TEXT_SEC}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; border-radius: 8px; }}"
            f"QPushButton:hover {{ background: #252848; color: {TEXT_PRI}; }}"
        )
        cancel.clicked.connect(self.reject)
        h.addWidget(cancel)

        save = QPushButton("✓  Save")
        save.setFixedSize(96, 32)
        save.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        save.setFont(inter(12, QFont.Weight.DemiBold))
        save.setStyleSheet(
            f"QPushButton {{ background: qlineargradient("
            f"x1:0,y1:0,x2:0,y2:1, stop:0 {PURPLE_LIGHT}, stop:1 #7c3aed); "
            f"color: white; border: none; border-radius: 8px; }}"
            f"QPushButton:hover {{ background: qlineargradient("
            f"x1:0,y1:0,x2:0,y2:1, stop:0 #c4b5fd, stop:1 {PURPLE}); }}"
        )
        save.clicked.connect(self._on_save)
        h.addWidget(save)
        return f

    # ── Behavior ──────────────────────────────────────────────────────────

    def _on_cat_pill(self, name: str):
        for n, p in self._cat_pills.items():
            p.set_active(n == name)
        self._selected_category = name

    def _open_find_artist(self):
        """Open the Find Artist dialog. On select, populate the artist input."""
        from ui.dialogs.find_artist_dialog import FindArtistDialog
        dlg = FindArtistDialog(parent=self, db=self._db)
        dlg.artist_selected.connect(
            lambda _aid, name: self._artist_input.setText(name)
        )
        dlg.exec()

    def _open_add_artist(self):
        """Open the Add Artist dialog. On save, populate the artist input."""
        from ui.dialogs.add_artist_dialog import AddArtistDialog
        prefill = self._artist_input.text().strip()
        dlg = AddArtistDialog(parent=self, db=self._db, prefill_name=prefill)
        dlg.artist_saved.connect(
            lambda _aid, name: self._artist_input.setText(name)
        )
        dlg.exec()

    def _on_browse(self):
        f, _ = QFileDialog.getOpenFileName(
            self, "Select audio file", "",
            "Audio files (*.mp3 *.wav *.flac *.m4a *.ogg)",
        )
        if f:
            self._audio_file_path = f
            self._filename_input.setText(f)

    def _on_ai_autofill(self):
        dialogs.info(
            self, "AI Auto-fill",
            "AI metadata auto-fill is not yet wired to Claude — coming in a future phase.",
        )

    def _on_save(self):
        artist = self._artist_input.text().strip()
        title  = self._title_input.text().strip()
        missing = [name for name, ok in [("Artist", artist), ("Song Title", title)] if not ok]
        if missing:
            dialogs.warning(self, "Required fields missing",
                                f"Please fill in: {', '.join(missing)}")
            (self._artist_input if not artist else self._title_input).setFocus()
            return

        # Resolve category id
        category_id = None
        try:
            row = self._db._conn().execute(
                "SELECT id FROM categories WHERE name = ? LIMIT 1",
                [self._selected_category],
            ).fetchone()
            if row:
                category_id = row[0]
        except Exception as exc:
            log.error(f"category lookup failed: {exc}")

        def _int(s, default=None):
            try: return int(s)
            except (ValueError, TypeError): return default

        duration_ms = 0
        if self._audio_file_path:
            try:
                from mutagen import File as MF
                mf = MF(self._audio_file_path)
                if mf and mf.info and mf.info.length:
                    duration_ms = int(mf.info.length * 1000)
            except Exception:
                pass

        song = {
            "title":           title,
            "artist":          artist,
            "album":           self._album_input.text().strip() or None,
            "year":            _int(self._year_combo.currentText()),
            "category_id":     category_id,
            "vocal":           self._vocal_combo.currentText() if self._vocal_combo.currentText() != "Select..." else None,
            "bpm":             _int(self._bpm_combo.currentText()),
            "duration_ms":     duration_ms,
            "file_path":       self._audio_file_path,
            "is_enabled":      1 if self._enabled_chk.isChecked() else 0,
            "is_frozen":       1 if self._frozen_chk.isChecked() else 0,
            "auto_code":       self._auto_code,
            "label":           self._label_input.text().strip() or None,
            "cd_key":          self._cdkey_input.text().strip() or None,
            "barcode":         self._barcode_input.text().strip() or None,
            "songwriter":      self._songwriter_input.text().strip() or None,
            "composer":        self._composer_input.text().strip() or None,
            "playlister_code": self._playlister_input.text().strip() or None,
        }

        try:
            new_id = self._db.add_song(song)
            song["id"] = new_id
        except Exception as exc:
            dialogs.error(self, "Save failed",
                                 f"Could not save song to database:\n\n{exc}")
            return

        log.info(f"Song added: id={new_id} '{artist} — {title}'")
        self.song_saved.emit(song)
        self.accept()
