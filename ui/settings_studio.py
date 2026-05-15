"""
RadioAI Studio Pro — Studio Settings
Pixel-accurate match of Figma node 69:2 (file 7oN9K61g94wKx3nu44KKDF).

Third Settings sub-page. Configures the broadcast engine — crossfade
curves, autocue thresholds, master/cue/jingle/mic levels, VU meter
behaviour, cue-split mode for headphone monitoring, and the
underlying audio engine selection. Every field persists to existing
settings table keys via Settings().set().

Layout (1440 × 900):
  Header        y=  0.. 72   Logo + breadcrumb + title + clock + Open Studio
  Body          y= 72..864   3 columns of cards in scroll areas:
    LEFT col   460w  CROSSFADE & TRANSITIONS + NEXT SONG LOAD +
                     PLAYBACK FALLBACK + Save Transition Settings
    CENTER col 460w  AUTOCUE SETTINGS + VOLUME & LEVELS + VU METERS +
                     Save Audio Settings
    RIGHT col  460w  CUE SPLIT + CROSSFADE PREVIEW + AUDIO ENGINE +
                     restart warning + Save Studio Settings
  Status bar    y=864..900   AUTO MODE / WASAPI Active / Audio OK pills

Public signals:
  breadcrumb_clicked(str) — header crumbs (control_panel / settings)
  studio_clicked()        — header Open Studio button

v1 scope cuts (deferred to v1.1):
  - Settings save persists to DB; actual AudioEngine hot-reload is
    v1.1 (restart-required warning is already in the design).
  - Crossfade Preview / Mix Point flash toggles save only — Studio
    waveform overlay rendering wires v1.1.
  - AutoCue scan mode persists; real auto-cue-point detection is v1.1.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional

from PyQt6.QtCore import Qt, QRectF, QTimer, pyqtSignal
from core import dialogs
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QLinearGradient, QFont, QCursor,
)
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QComboBox, QSlider,
    QHBoxLayout, QVBoxLayout, QScrollArea, QMessageBox,
)

from core.settings import Settings
from ui.widgets._tokens import (
    inter, mono, rgba,
    BG_BASE, BG_DARK, BG_PANEL, BG_ELEVATED,
    TEXT_PRI, TEXT_SEC, TEXT_MUTED, TEXT_DIM,
    CYAN, CYAN_LIGHT, PURPLE, PURPLE_LIGHT, PURPLE_DARK,
    GREEN, GREEN_LIGHT, AMBER, AMBER_LIGHT, RED, RED_LIGHT,
    PINK, PINK_LIGHT, TEAL, TEAL_LIGHT,
)

log = logging.getLogger("SettingsStudio")


# ════════════════════════════════════════════════════════════════════════════
# Geometry
# ════════════════════════════════════════════════════════════════════════════

WINDOW_W = 1440
WINDOW_H = 900
HEADER_H = 72
STATUS_H = 36
BODY_Y0  = HEADER_H
BODY_H   = WINDOW_H - HEADER_H - STATUS_H   # 792
COL_W    = 460
COL_GAP  = 14
COL_PAD  = 16

# Dropdown options
FADE_CURVES = ["Linear", "Logarithmic", "Exponential", "S-Curve"]
LOAD_NEXT_SONG_OPTIONS = [
    "At mix point of current", "When current ends",
    "At fade-out start", "Manual only",
]
PRELOAD_BUFFER_OPTIONS = [
    "5 seconds ahead", "10 seconds ahead",
    "15 seconds ahead", "30 seconds ahead",
]
AUTOMIX_TRIGGER_OPTIONS = [
    "At song MIX POINT marker", "At fade-out start",
    "At end of song", "Manual only",
]
FALLBACK_ACTIONS = [
    "Skip and play next available song",
    "Play default fallback track",
    "Stop playback + alert operator",
    "Re-queue the same song",
]
AUTOCUE_SCAN_MODES = [
    "Scan first 10s + last 10s (Fast)",
    "Scan entire file (Accurate)",
    "First 5s only (Fastest)",
    "Disabled — manual cue points only",
]
VU_DECAY_OPTIONS = [
    "Slow (500ms decay)", "Normal (300ms decay)",
    "Fast (150ms decay)", "Instant (no decay)",
]
PEAK_HOLD_OPTIONS = [
    "1 second", "2 seconds", "3 seconds", "Hold until reset",
]
CUE_SPLIT_OPTIONS = [
    ("off",       "Off — Hear only monitor output"),
    ("cue_left",  "Left: Cue  ·  Right: On-Air"),
    ("air_left",  "Left: On-Air  ·  Right: Cue"),
    ("blend",     "Blend: 50% Cue + 50% On-Air"),
]


# ════════════════════════════════════════════════════════════════════════════
# Header chrome — same pattern as siblings
# ════════════════════════════════════════════════════════════════════════════


class _HeaderLogo(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(40, 40)

    def paintEvent(self, _e):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        g = QLinearGradient(0, 0, self.width(), self.height())
        g.setColorAt(0.0, QColor(CYAN))
        g.setColorAt(1.0, QColor(PURPLE))
        p.setBrush(QBrush(g)); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(2, 2, self.width() - 4, self.height() - 4)
        p.setPen(QPen(QColor(255, 255, 255, 230), 2))
        cx, cy = self.width() / 2, self.height() / 2
        for i, h in enumerate([6, 10, 14, 10, 6]):
            x = cx - 8 + i * 4
            p.drawLine(int(x), int(cy - h / 2), int(x), int(cy + h / 2))
        p.end()


class _HeaderOpenStudio(QPushButton):
    def __init__(self, parent=None):
        super().__init__("▶  Open Studio", parent)
        self.setFixedSize(110, 40)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFont(inter(11, QFont.Weight.Bold))
        self.setStyleSheet(
            f"QPushButton {{ background: qlineargradient("
            f"x1:0,y1:0,x2:0,y2:1, stop:0 {GREEN_LIGHT}, stop:1 {GREEN}); "
            f"color: white; border: none; border-radius: 8px; }}"
            f"QPushButton:hover {{ background: qlineargradient("
            f"x1:0,y1:0,x2:0,y2:1, stop:0 #34d399, stop:1 {GREEN}); }}"
        )


class _BreadcrumbLink(QPushButton):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFont(inter(11, QFont.Weight.Medium))
        self.setFlat(True)
        self.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {TEXT_MUTED}; "
            f"border: none; padding: 0 4px; text-align: left; }}"
            f"QPushButton:hover {{ color: {TEXT_PRI}; }}"
        )


class _BreadcrumbPill(QFrame):
    """Active breadcrumb crumb tinted with the sub-page accent (purple
    for Studio Settings)."""

    def __init__(self, label: str, accent: str = PURPLE, parent=None):
        super().__init__(parent)
        self.setFixedSize(130, 32)
        self.setStyleSheet(
            f"QFrame {{ background: {rgba(accent, 0.18)}; "
            f"border: 1px solid {rgba(accent, 0.40)}; border-radius: 16px; }}"
        )
        h = QHBoxLayout(self)
        h.setContentsMargins(14, 0, 14, 0); h.setSpacing(0)
        lbl = QLabel(label, self)
        lbl.setFont(inter(11, QFont.Weight.Bold))
        lbl.setStyleSheet(
            f"color: {PURPLE_LIGHT}; background: transparent; border: none;")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h.addWidget(lbl)


# ════════════════════════════════════════════════════════════════════════════
# Section card (with colored top accent + heading)
# ════════════════════════════════════════════════════════════════════════════


class _SectionCard(QFrame):
    """Card with a 4px colored top accent + heading band. Children go
    in the body QVBoxLayout via add_row()."""

    def __init__(self, title: str, accent: str, parent=None):
        super().__init__(parent)
        self._accent = accent
        self._title = title
        self.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; "
            f"border-radius: 8px; }}"
        )
        self._body = QFrame(self)
        self._body.setStyleSheet(
            "QFrame { background: transparent; border: none; }")
        self._body_v = QVBoxLayout(self._body)
        self._body_v.setContentsMargins(20, 38, 20, 14)
        self._body_v.setSpacing(10)

    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(QRectF(0, 0, self.width(), 4), QColor(self._accent))
        p.setPen(QColor(self._accent))
        p.setFont(inter(9, QFont.Weight.Bold, letter_spacing=1.4))
        p.drawText(QRectF(20, 10, self.width() - 40, 20),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._title.upper())
        p.end()
        super().paintEvent(e)

    def resizeEvent(self, e):
        self._body.setGeometry(0, 0, self.width(), self.height())
        super().resizeEvent(e)

    def add_row(self, widget: QWidget) -> None:
        self._body_v.addWidget(widget)


# ════════════════════════════════════════════════════════════════════════════
# Form primitives
# ════════════════════════════════════════════════════════════════════════════


class _FieldLabel(QLabel):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setFont(inter(10, QFont.Weight.Medium))
        self.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent; border: none;")


class _SubFieldLabel(QLabel):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setFont(inter(9))
        self.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; border: none;")


class _DarkComboBox(QComboBox):
    def __init__(self, accent: str = PURPLE, parent=None):
        super().__init__(parent)
        self.setFixedHeight(30)
        self.setFont(inter(11))
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setStyleSheet(
            f"QComboBox {{ background: {BG_DARK}; color: {TEXT_PRI}; "
            f"border: 1px solid {rgba(accent, 0.25)}; "
            f"border-radius: 5px; padding: 0 10px; }}"
            f"QComboBox:hover {{ "
            f"border: 1px solid {rgba(accent, 0.55)}; }}"
            f"QComboBox::drop-down {{ border: none; width: 22px; }}"
            f"QComboBox::down-arrow {{ image: none; }}"
            f"QComboBox QAbstractItemView {{ background: {BG_PANEL}; "
            f"color: {TEXT_PRI}; "
            f"selection-background-color: {rgba(accent, 0.25)}; "
            f"border: 1px solid {rgba('#ffffff', 0.10)}; outline: 0; }}"
        )


class _LabeledDropdown(QWidget):
    def __init__(self, label: str, options: list, accent: str = PURPLE,
                 caption: str = "", parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0); v.setSpacing(4)
        v.addWidget(_FieldLabel(label))
        self._cmb = _DarkComboBox(accent, self)
        self._cmb.addItems(options)
        v.addWidget(self._cmb)
        if caption:
            v.addWidget(_SubFieldLabel(caption))

    def current_text(self) -> str:
        return self._cmb.currentText()

    def set_current_text(self, txt: str) -> None:
        if not txt:
            return
        idx = self._cmb.findText(txt, Qt.MatchFlag.MatchFixedString)
        if idx >= 0:
            self._cmb.setCurrentIndex(idx)
        else:
            self._cmb.insertItem(0, txt)
            self._cmb.setCurrentIndex(0)


class _ColoredSlider(QSlider):
    """Horizontal slider with track filled in accent color up to the
    handle. Used for crossfade duration, fade-out start, audio levels,
    autocue threshold."""

    def __init__(self, vmin: int, vmax: int, accent: str = PURPLE,
                 parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setRange(vmin, vmax)
        self.setFixedHeight(10)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setStyleSheet(
            f"QSlider::groove:horizontal {{ background: {BG_DARK}; "
            f"height: 10px; border-radius: 5px; }}"
            f"QSlider::sub-page:horizontal {{ background: {accent}; "
            f"border-radius: 5px; }}"
            f"QSlider::add-page:horizontal {{ background: {BG_DARK}; "
            f"border-radius: 5px; }}"
            f"QSlider::handle:horizontal {{ background: white; "
            f"width: 16px; height: 16px; margin: -4px 0; "
            f"border-radius: 8px; }}"
        )


class _LabeledSlider(QWidget):
    """Slider with top label + current/min/max numerals + caption below.
    Min/max suffix string is appended next to the numeric value (e.g.,
    'dB', '%', '')."""

    def __init__(self, label: str, vmin: int, vmax: int, value: int,
                 accent: str = PURPLE, suffix: str = "",
                 caption: str = "", parent=None):
        super().__init__(parent)
        self._suffix = suffix
        self._vmin = vmin
        self._vmax = vmax
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0); v.setSpacing(2)

        # Label row — left label + right "value suffix"
        lbl_row = QFrame(self)
        lbl_row.setStyleSheet("QFrame { background: transparent; }")
        h = QHBoxLayout(lbl_row)
        h.setContentsMargins(0, 0, 0, 0); h.setSpacing(0)
        self._lbl = _FieldLabel(label)
        h.addWidget(self._lbl)
        h.addStretch()
        self._val_lbl = QLabel("", lbl_row)
        self._val_lbl.setFont(mono(10, bold=True))
        self._val_lbl.setStyleSheet(
            f"color: {accent}; background: transparent; border: none;")
        h.addWidget(self._val_lbl)
        v.addWidget(lbl_row)

        # Min .. slider .. max
        row = QFrame(self)
        row.setStyleSheet("QFrame { background: transparent; }")
        rh = QHBoxLayout(row)
        rh.setContentsMargins(0, 4, 0, 4); rh.setSpacing(8)
        min_lbl = QLabel(str(vmin), row); min_lbl.setFont(mono(9))
        min_lbl.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; "
            f"border: none;")
        rh.addWidget(min_lbl)
        self._sl = _ColoredSlider(vmin, vmax, accent, row)
        rh.addWidget(self._sl, stretch=1)
        max_lbl = QLabel(str(vmax), row); max_lbl.setFont(mono(9))
        max_lbl.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; "
            f"border: none;")
        rh.addWidget(max_lbl)
        v.addWidget(row)

        if caption:
            v.addWidget(_SubFieldLabel(caption))

        self._sl.valueChanged.connect(self._on_changed)
        self.set_value(value)

    def _on_changed(self, v: int) -> None:
        self._val_lbl.setText(f"{v}{self._suffix}")

    def set_value(self, v: int) -> None:
        v = max(self._vmin, min(self._vmax, int(v)))
        self._sl.setValue(v)
        self._on_changed(v)

    def value(self) -> int:
        return self._sl.value()


class _CurveButtonGroup(QFrame):
    """Four exclusive buttons in a horizontal row — Linear / Logarithmic
    / Exponential / S-Curve. Active button is filled with the accent
    color tint."""

    changed = pyqtSignal(str)

    def __init__(self, options: list, accent: str = PURPLE, parent=None):
        super().__init__(parent)
        self._options = options
        self._accent = accent
        self._active = options[0] if options else ""
        self.setFixedHeight(34)
        self.setStyleSheet("QFrame { background: transparent; }")
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0); h.setSpacing(6)
        self._btns: dict = {}
        for opt in options:
            b = QPushButton(opt, self)
            b.setFixedHeight(30)
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.setFont(inter(10, QFont.Weight.Bold))
            b.clicked.connect(lambda _=False, k=opt: self.set_active(k))
            h.addWidget(b, stretch=1)
            self._btns[opt] = b
        self._refresh_styles()

    def _refresh_styles(self) -> None:
        for opt, btn in self._btns.items():
            if opt == self._active:
                btn.setStyleSheet(
                    f"QPushButton {{ background: {rgba(self._accent, 0.22)}; "
                    f"color: {PURPLE_LIGHT if self._accent == PURPLE else self._accent}; "
                    f"border: 1px solid {rgba(self._accent, 0.55)}; "
                    f"border-radius: 6px; }}"
                )
            else:
                btn.setStyleSheet(
                    f"QPushButton {{ background: {BG_DARK}; "
                    f"color: {TEXT_MUTED}; "
                    f"border: 1px solid {rgba('#ffffff', 0.08)}; "
                    f"border-radius: 6px; }}"
                    f"QPushButton:hover {{ color: {TEXT_PRI}; "
                    f"border: 1px solid {rgba(self._accent, 0.40)}; }}"
                )

    def set_active(self, opt: str) -> None:
        if opt not in self._btns or opt == self._active:
            return
        self._active = opt
        self._refresh_styles()
        self.changed.emit(opt)

    def active(self) -> str:
        return self._active


class _CurveRow(QWidget):
    """Wrapper that adds a label above the button group."""

    def __init__(self, label: str, options: list, accent: str, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0); v.setSpacing(4)
        v.addWidget(_FieldLabel(label))
        self._grp = _CurveButtonGroup(options, accent)
        v.addWidget(self._grp)

    def active(self) -> str:
        return self._grp.active()

    def set_active(self, opt: str) -> None:
        self._grp.set_active(opt)


class _ToggleSwitch(QFrame):
    """44×22 pill toggle, accent-colored when on."""

    toggled = pyqtSignal(bool)

    def __init__(self, on_color: str = GREEN, parent=None):
        super().__init__(parent)
        self.setFixedSize(44, 22)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._on_color = on_color
        self._on = False

    def is_on(self) -> bool:
        return self._on

    def set_on(self, on: bool) -> None:
        was = self._on
        self._on = bool(on)
        self.update()
        if was != self._on:
            self.toggled.emit(self._on)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.set_on(not self._on)
        super().mousePressEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        bg = QColor(self._on_color) if self._on else QColor(BG_ELEVATED)
        p.setBrush(QBrush(bg))
        p.setPen(QPen(QColor(rgba('#ffffff', 0.06)), 1))
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), h / 2, h / 2)
        knob_d = h - 6
        knob_x = (w - 3 - knob_d) if self._on else 3
        p.setBrush(QColor("#ffffff"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(knob_x, 3, knob_d, knob_d))


class _ToggleRow(QWidget):
    """Inline toggle + label."""

    def __init__(self, label: str, on_color: str = GREEN, parent=None):
        super().__init__(parent)
        self.setFixedHeight(32)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0); h.setSpacing(12)
        self._toggle = _ToggleSwitch(on_color, self)
        h.addWidget(self._toggle,
                    alignment=Qt.AlignmentFlag.AlignVCenter)
        lbl = QLabel(label, self)
        lbl.setFont(inter(11, QFont.Weight.Medium))
        lbl.setStyleSheet(
            f"color: {TEXT_PRI}; background: transparent; border: none;")
        h.addWidget(lbl, stretch=1,
                    alignment=Qt.AlignmentFlag.AlignVCenter)

    def is_on(self) -> bool:
        return self._toggle.is_on()

    def set_on(self, on: bool) -> None:
        self._toggle.set_on(on)


class _LabeledToggle(QWidget):
    """Two-row form: top label (e.g., 'Missing file alert:') +
    underneath a toggle row with secondary text."""

    def __init__(self, label: str, toggle_text: str,
                 on_color: str = GREEN, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0); v.setSpacing(4)
        v.addWidget(_FieldLabel(label))
        self._row = _ToggleRow(toggle_text, on_color, self)
        v.addWidget(self._row)

    def is_on(self) -> bool:
        return self._row.is_on()

    def set_on(self, on: bool) -> None:
        self._row.set_on(on)


class _RadioOption(QFrame):
    """One row in a radio-option list — circular check + label.
    Click anywhere on the row selects this option (parent group
    enforces exclusivity)."""

    clicked = pyqtSignal(str)

    def __init__(self, key: str, label: str, accent: str = GREEN,
                 parent=None):
        super().__init__(parent)
        self._key = key
        self._label = label
        self._accent = accent
        self._selected = False
        self.setFixedHeight(38)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

    def key(self) -> str:
        return self._key

    def is_selected(self) -> bool:
        return self._selected

    def set_selected(self, on: bool) -> None:
        self._selected = bool(on)
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._key)
        super().mousePressEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        # Background
        if self._selected:
            p.fillRect(QRectF(0, 0, w, h),
                       QColor(rgba(self._accent, 0.16)))
            p.setPen(QPen(QColor(rgba(self._accent, 0.45)), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 6, 6)
        else:
            p.setPen(QPen(QColor(rgba('#ffffff', 0.06)), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 6, 6)
        # Circle
        cx, cy = 16, h / 2
        if self._selected:
            p.setBrush(QColor(self._accent))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QRectF(cx - 7, cy - 7, 14, 14))
            p.setPen(QColor("#04141a"))
            p.setFont(inter(10, QFont.Weight.Black))
            p.drawText(QRectF(cx - 8, cy - 8, 16, 16),
                       Qt.AlignmentFlag.AlignCenter, "✓")
        else:
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(rgba('#ffffff', 0.20)), 1))
            p.drawEllipse(QRectF(cx - 7, cy - 7, 14, 14))
        # Label
        p.setPen(QColor(
            GREEN_LIGHT if self._selected else TEXT_SEC))
        p.setFont(inter(11,
                        QFont.Weight.Bold if self._selected
                        else QFont.Weight.Medium))
        p.drawText(QRectF(36, 0, w - 48, h),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._label)


class _RadioGroup(QWidget):
    """Exclusive group of _RadioOption rows."""

    changed = pyqtSignal(str)

    def __init__(self, options: list, accent: str = GREEN, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0); v.setSpacing(6)
        self._items: dict = {}
        for key, label in options:
            row = _RadioOption(key, label, accent, self)
            row.clicked.connect(self._on_clicked)
            v.addWidget(row)
            self._items[key] = row
        self._selected: Optional[str] = None
        if options:
            self.set_selected(options[0][0])

    def _on_clicked(self, key: str) -> None:
        self.set_selected(key)
        self.changed.emit(key)

    def set_selected(self, key: str) -> None:
        if key not in self._items:
            return
        if self._selected == key:
            return
        if self._selected is not None:
            self._items[self._selected].set_selected(False)
        self._selected = key
        self._items[key].set_selected(True)

    def selected(self) -> str:
        return self._selected or ""


class _InfoRow(QWidget):
    """Read-only label + value row (for Audio Engine info card)."""

    def __init__(self, label: str, value: str, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0); v.setSpacing(2)
        v.addWidget(_FieldLabel(label))
        val = QLabel(value, self)
        val.setFont(mono(11, bold=True))
        val.setStyleSheet(
            f"color: {TEXT_PRI}; background: {BG_DARK}; "
            f"border: 1px solid {rgba('#ffffff', 0.08)}; "
            f"border-radius: 5px; padding: 6px 10px;")
        self._val = val
        v.addWidget(val)

    def set_value(self, val: str) -> None:
        self._val.setText(val)


# ════════════════════════════════════════════════════════════════════════════
# Buttons
# ════════════════════════════════════════════════════════════════════════════


class _PrimarySaveButton(QPushButton):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setFixedHeight(44)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFont(inter(12, QFont.Weight.Bold, letter_spacing=0.6))
        self.setStyleSheet(
            f"QPushButton {{ background: qlineargradient("
            f"x1:0,y1:0,x2:0,y2:1, stop:0 {PURPLE_LIGHT}, stop:1 {PURPLE}); "
            f"color: white; border: none; border-radius: 8px; }}"
            f"QPushButton:hover {{ background: qlineargradient("
            f"x1:0,y1:0,x2:0,y2:1, stop:0 #c4b5fd, stop:1 {PURPLE_LIGHT}); }}"
        )


# ════════════════════════════════════════════════════════════════════════════
# Status bar
# ════════════════════════════════════════════════════════════════════════════


class _StatusPill(QFrame):
    def __init__(self, label: str, color: str, parent=None):
        super().__init__(parent)
        self.setFixedHeight(22)
        self.setStyleSheet(
            f"QFrame {{ background: {rgba(color, 0.18)}; "
            f"border: 1px solid {rgba(color, 0.40)}; border-radius: 11px; }}"
        )
        h = QHBoxLayout(self)
        h.setContentsMargins(10, 0, 12, 0); h.setSpacing(6)
        dot = QLabel("●", self)
        dot.setFont(inter(8))
        dot.setStyleSheet(
            f"color: {color}; background: transparent; border: none;")
        lbl = QLabel(label, self)
        lbl.setFont(inter(9, QFont.Weight.Bold))
        lbl.setStyleSheet(
            f"color: {color}; background: transparent; border: none;")
        h.addWidget(dot)
        h.addWidget(lbl)
        self.adjustSize()


# ════════════════════════════════════════════════════════════════════════════
# Public screen
# ════════════════════════════════════════════════════════════════════════════


class SettingsStudio(QWidget):
    """Studio Settings screen (Figma 69:2)."""

    breadcrumb_clicked = pyqtSignal(str)
    studio_clicked     = pyqtSignal()
    settings_saved     = pyqtSignal()

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self._db = db
        self.setFixedSize(WINDOW_W, WINDOW_H)
        self.setStyleSheet(f"QWidget {{ background: {BG_BASE}; }}")

        self._build_header()
        self._build_left_column()
        self._build_center_column()
        self._build_right_column()
        self._build_status_bar()

        self._load_settings()

        # Live clock
        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._tick_clock)
        self._clock_timer.start()
        self._tick_clock()

        log.info("SettingsStudio ready (Figma 69:2)")

    # ── Header ────────────────────────────────────────────────────────

    def _build_header(self) -> None:
        h = QFrame(self)
        h.setGeometry(0, 0, WINDOW_W, HEADER_H)
        h.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border-bottom: 1px solid {rgba('#ffffff', 0.06)}; }}"
        )

        _HeaderLogo(h).move(14, 16)
        l = QLabel("RadioAI", h)
        l.setGeometry(64, 14, 120, 18)
        l.setFont(inter(15, QFont.Weight.Bold))
        l.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        l2 = QLabel("STUDIO PRO", h)
        l2.setGeometry(64, 34, 120, 12)
        l2.setFont(inter(8, QFont.Weight.Bold, letter_spacing=1.2))
        l2.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

        cp = _BreadcrumbLink("Control Panel", h)
        cp.setGeometry(176, 22, 100, 22)
        cp.clicked.connect(
            lambda: self.breadcrumb_clicked.emit("control_panel"))

        sep1 = QLabel("|", h); sep1.setGeometry(272, 22, 8, 22)
        sep1.setFont(inter(11))
        sep1.setStyleSheet(f"color: {TEXT_DIM}; background: transparent;")

        st = _BreadcrumbLink("Settings", h)
        st.setGeometry(284, 22, 60, 22)
        st.clicked.connect(
            lambda: self.breadcrumb_clicked.emit("settings"))

        sep2 = QLabel("|", h); sep2.setGeometry(346, 22, 8, 22)
        sep2.setFont(inter(11))
        sep2.setStyleSheet(f"color: {TEXT_DIM}; background: transparent;")

        pill = _BreadcrumbPill("Studio Settings", PURPLE, h)
        pill.move(358, 20)

        title = QLabel("Studio Settings", h)
        title.setGeometry(500, 12, 240, 24)
        title.setFont(inter(20, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        sub = QLabel(
            "Crossfade, fade curves, AutoCue, cue split and audio engine "
            "preferences",
            h)
        sub.setGeometry(500, 38, 560, 14)
        sub.setFont(inter(10))
        sub.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

        self._clock_lbl = QLabel("", h)
        self._clock_lbl.setGeometry(1108, 14, 100, 24)
        self._clock_lbl.setFont(mono(20, bold=True))
        self._clock_lbl.setStyleSheet(
            f"color: {TEXT_PRI}; background: transparent;")
        try:
            station = Settings().station_display or "KISS FM 91.5"
        except Exception:
            station = "KISS FM 91.5"
        self._station_lbl = QLabel(station, h)
        self._station_lbl.setObjectName("hdr_station_lbl")
        self._station_lbl.setGeometry(1108, 40, 110, 14)
        self._station_lbl.setFont(inter(9, QFont.Weight.Medium))
        self._station_lbl.setStyleSheet(
            f"color: {GREEN}; background: transparent;")

        osb = _HeaderOpenStudio(h)
        osb.move(1222, 16)
        osb.clicked.connect(self.studio_clicked.emit)

    # ── Column scaffold ───────────────────────────────────────────────

    def _build_column_scroll(self, x: int) -> tuple:
        scroll = QScrollArea(self)
        scroll.setGeometry(x, BODY_Y0, COL_W, BODY_H)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setStyleSheet(
            f"QScrollArea {{ background: transparent; border: none; }}"
            f"QScrollBar:vertical {{ background: {BG_DARK}; width: 8px; }}"
            f"QScrollBar::handle:vertical {{ background: "
            f"{rgba('#ffffff', 0.10)}; border-radius: 4px; "
            f"min-height: 24px; }}"
            f"QScrollBar::handle:vertical:hover {{ background: "
            f"{rgba('#ffffff', 0.18)}; }}"
            f"QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}"
        )
        content = QWidget()
        content.setStyleSheet("QWidget { background: transparent; }")
        v = QVBoxLayout(content)
        v.setContentsMargins(COL_PAD, COL_PAD, COL_PAD, COL_PAD)
        v.setSpacing(COL_GAP)
        scroll.setWidget(content)
        return scroll, content, v

    # ── Left column ───────────────────────────────────────────────────

    def _build_left_column(self) -> None:
        scroll, content, v = self._build_column_scroll(0)

        # CROSSFADE & TRANSITIONS
        c1 = _SectionCard("Crossfade & Transitions", PURPLE, content)
        self._sl_crossfade = _LabeledSlider(
            "Crossfade Duration", 0, 10, 3, PURPLE, "",
            caption="How long songs overlap during mix")
        self._sl_fade_out = _LabeledSlider(
            "Fade Out Start", 0, 10, 6, AMBER, "",
            caption="When outgoing song starts fading")
        self._curve = _CurveRow("Fade Curve Type", FADE_CURVES, PURPLE)
        for w in (self._sl_crossfade, self._sl_fade_out, self._curve):
            c1.add_row(w)
        c1.setFixedHeight(38 + 80 + 80 + 70 + 16)
        v.addWidget(c1)

        # NEXT SONG LOAD
        c2 = _SectionCard("Next Song Load", CYAN, content)
        self._cmb_load_next = _LabeledDropdown(
            "Load next song", LOAD_NEXT_SONG_OPTIONS, CYAN)
        self._cmb_preload = _LabeledDropdown(
            "Preload buffer", PRELOAD_BUFFER_OPTIONS, CYAN)
        self._cmb_automix = _LabeledDropdown(
            "AutoMix trigger", AUTOMIX_TRIGGER_OPTIONS, CYAN)
        for w in (self._cmb_load_next, self._cmb_preload,
                  self._cmb_automix):
            c2.add_row(w)
        c2.setFixedHeight(38 + 3 * 54 + 16)
        v.addWidget(c2)

        # PLAYBACK FALLBACK
        c3 = _SectionCard("Playback Fallback", RED, content)
        self._cmb_fallback = _LabeledDropdown(
            "If next song file is missing:", FALLBACK_ACTIONS, RED)
        self._tg_missing_alert = _LabeledToggle(
            "Missing file alert:",
            "Show on-screen warning immediately", GREEN)
        c3.add_row(self._cmb_fallback)
        c3.add_row(self._tg_missing_alert)
        c3.setFixedHeight(38 + 54 + 64 + 16)
        v.addWidget(c3)

        # Save Transition Settings
        self._btn_save_left = _PrimarySaveButton(
            "✓  Save Transition Settings", content)
        self._btn_save_left.clicked.connect(self._on_save_left)
        v.addWidget(self._btn_save_left)
        v.addStretch()

    # ── Center column ─────────────────────────────────────────────────

    def _build_center_column(self) -> None:
        scroll, content, v = self._build_column_scroll(COL_W + COL_GAP)

        # AUTOCUE SETTINGS
        c1 = _SectionCard("AutoCue Settings", GREEN, content)
        self._sl_autocue = _LabeledSlider(
            "AutoCue dB Threshold", -70, 0, -40, GREEN, " dB",
            caption=(
                "Sets the silence level AutoCue uses to find the "
                "start/end of audio"))
        self._cmb_autocue_scan = _LabeledDropdown(
            "AutoCue scan mode", AUTOCUE_SCAN_MODES, GREEN)
        c1.add_row(self._sl_autocue)
        c1.add_row(self._cmb_autocue_scan)
        c1.setFixedHeight(38 + 92 + 54 + 16)
        v.addWidget(c1)

        # VOLUME & LEVELS
        c2 = _SectionCard("Volume & Levels", AMBER, content)
        self._sl_master = _LabeledSlider(
            "Master Output Level", 0, 100, 85, AMBER)
        self._sl_cue = _LabeledSlider(
            "Cue / Preview Level", 0, 100, 70, CYAN)
        self._sl_jingle = _LabeledSlider(
            "Jingle Pad Level", 0, 100, 90, GREEN)
        self._sl_mic = _LabeledSlider(
            "Microphone Level", 0, 100, 75, PINK)
        for w in (self._sl_master, self._sl_cue,
                  self._sl_jingle, self._sl_mic):
            c2.add_row(w)
        c2.setFixedHeight(38 + 4 * 64 + 16)
        v.addWidget(c2)

        # VU METERS
        c3 = _SectionCard("VU Meters", TEAL, content)
        self._cmb_vu_decay = _LabeledDropdown(
            "VU meter decay speed", VU_DECAY_OPTIONS, TEAL)
        self._cmb_peak_hold = _LabeledDropdown(
            "Peak hold duration", PEAK_HOLD_OPTIONS, TEAL)
        self._tg_clip = _LabeledToggle(
            "Over 0dB clip indicator", "Flash red on clip", RED)
        for w in (self._cmb_vu_decay, self._cmb_peak_hold, self._tg_clip):
            c3.add_row(w)
        c3.setFixedHeight(38 + 2 * 54 + 64 + 16)
        v.addWidget(c3)

        # Save Audio Settings
        self._btn_save_center = _PrimarySaveButton(
            "✓  Save Audio Settings", content)
        self._btn_save_center.clicked.connect(self._on_save_center)
        v.addWidget(self._btn_save_center)
        v.addStretch()

    # ── Right column ──────────────────────────────────────────────────

    def _build_right_column(self) -> None:
        scroll, content, v = self._build_column_scroll(
            2 * (COL_W + COL_GAP))

        # CUE SPLIT
        c1 = _SectionCard("Cue Split (Headphone Monitoring)",
                           CYAN, content)
        self._cue_split = _RadioGroup(CUE_SPLIT_OPTIONS, GREEN)
        c1.add_row(self._cue_split)
        c1.setFixedHeight(38 + 4 * 44 + 16)
        v.addWidget(c1)

        # CROSSFADE PREVIEW
        c2 = _SectionCard("Crossfade Preview", PURPLE, content)
        self._tg_show_preview = _LabeledToggle(
            "Show crossfade overlap on waveform?",
            "Show purple overlap zone on Studio waveforms", PURPLE)
        self._tg_flash_mix = _LabeledToggle(
            "Animate mix point approach?",
            "Flash green 10s before mix point", GREEN)
        c2.add_row(self._tg_show_preview)
        c2.add_row(self._tg_flash_mix)
        c2.setFixedHeight(38 + 2 * 64 + 16)
        v.addWidget(c2)

        # AUDIO ENGINE
        c3 = _SectionCard("Audio Engine", AMBER, content)
        self._info_buffer = _InfoRow("Audio buffer size",
                                       "256 samples (5ms)")
        self._info_rate = _InfoRow("Sample rate", "44100 Hz")
        self._info_bit = _InfoRow("Bit depth", "32-bit float")
        self._info_engine = _InfoRow("Audio engine",
                                       "WASAPI (Low Latency)")
        for w in (self._info_buffer, self._info_rate,
                  self._info_bit, self._info_engine):
            c3.add_row(w)
        c3.setFixedHeight(38 + 4 * 50 + 16)
        v.addWidget(c3)

        # Restart warning strip
        warn = QFrame()
        warn.setFixedHeight(56)
        warn.setStyleSheet(
            f"QFrame {{ background: {rgba(AMBER, 0.08)}; "
            f"border: 1px solid {rgba(AMBER, 0.30)}; "
            f"border-radius: 6px; }}"
        )
        wh = QHBoxLayout(warn)
        wh.setContentsMargins(14, 6, 14, 6); wh.setSpacing(10)
        ic = QLabel("⚠", warn)
        ic.setFont(inter(16, QFont.Weight.Bold))
        ic.setStyleSheet(
            f"color: {AMBER_LIGHT}; background: transparent; border: none;")
        wh.addWidget(ic, alignment=Qt.AlignmentFlag.AlignTop)
        txt_box = QFrame(warn)
        txt_box.setStyleSheet("QFrame { background: transparent; }")
        tv = QVBoxLayout(txt_box)
        tv.setContentsMargins(0, 0, 0, 0); tv.setSpacing(2)
        ml = QLabel("Audio engine changes require restart.", txt_box)
        ml.setFont(inter(11, QFont.Weight.Bold))
        ml.setStyleSheet(
            f"color: {AMBER_LIGHT}; background: transparent; border: none;")
        sl = QLabel(
            "Always test audio outputs after changing engine settings.",
            txt_box)
        sl.setFont(inter(9))
        sl.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent; border: none;")
        tv.addWidget(ml)
        tv.addWidget(sl)
        wh.addWidget(txt_box, stretch=1)
        v.addWidget(warn)

        # Save Studio Settings
        self._btn_save_right = _PrimarySaveButton(
            "✓  Save Studio Settings", content)
        self._btn_save_right.clicked.connect(self._on_save_right)
        v.addWidget(self._btn_save_right)
        v.addStretch()

    # ── Status bar ────────────────────────────────────────────────────

    def _build_status_bar(self) -> None:
        sb = QFrame(self)
        sb.setGeometry(0, WINDOW_H - STATUS_H, WINDOW_W, STATUS_H)
        sb.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border-top: 1px solid {rgba('#ffffff', 0.06)}; }}"
        )
        x = 12
        engine_label = (Settings().get("audio_engine") or "WASAPI")
        pills = (("AUTO MODE", PURPLE),
                  (f"{engine_label} Active", GREEN),
                  ("Audio OK",  GREEN))
        for txt, col in pills:
            p = _StatusPill(txt, col, sb)
            p.move(x, (STATUS_H - p.height()) // 2)
            x += p.width() + 8

        ver = QLabel("Studio Settings  ·  RadioAI Studio v1.0.0", sb)
        ver.setFont(inter(9))
        ver.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; border: none;")
        ver.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        ver.setFixedSize(360, STATUS_H)
        ver.move(WINDOW_W - 24 - 360 - 130, 0)

        osb = QPushButton("▶  Open Studio", sb)
        osb.setFixedSize(120, 26)
        osb.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        osb.setFont(inter(10, QFont.Weight.Bold))
        osb.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {GREEN_LIGHT}; "
            f"border: none; padding: 0 8px; }}"
            f"QPushButton:hover {{ color: {GREEN}; }}"
        )
        osb.move(WINDOW_W - 12 - 120, (STATUS_H - 26) // 2)
        osb.clicked.connect(self.studio_clicked.emit)

    # ── Clock ─────────────────────────────────────────────────────────

    def _tick_clock(self) -> None:
        self._clock_lbl.setText(datetime.now().strftime("%H:%M:%S"))

    # ── Settings IO ───────────────────────────────────────────────────
    #
    # Three save buttons map to three logical groups; the load path
    # reads every key into the form on entry so any save button
    # writes a consistent snapshot.

    def _load_settings(self) -> None:
        s = Settings()
        # Left column
        self._sl_crossfade.set_value(s.get_int("crossfade_duration", 3))
        self._sl_fade_out.set_value(s.get_int("fade_out_start", 6))
        self._curve.set_active(
            s.get("fade_curve_type", "Logarithmic") or "Logarithmic")
        self._cmb_load_next.set_current_text(
            s.get("load_next_song", "At mix point of current"))
        self._cmb_preload.set_current_text(
            s.get("preload_buffer", "10 seconds ahead"))
        self._cmb_automix.set_current_text(
            s.get("automix_trigger", "At song MIX POINT marker"))
        self._cmb_fallback.set_current_text(
            s.get("fallback_action",
                  "Skip and play next available song"))
        self._tg_missing_alert.set_on(s.get_bool("missing_file_alert"))

        # Center column
        self._sl_autocue.set_value(s.get_int("autocue_threshold", -40))
        self._cmb_autocue_scan.set_current_text(
            s.get("autocue_scan_mode",
                  "Scan first 10s + last 10s (Fast)"))
        self._sl_master.set_value(s.get_int("master_volume", 85))
        self._sl_cue.set_value(s.get_int("cue_volume", 70))
        self._sl_jingle.set_value(s.get_int("jingle_volume", 90))
        self._sl_mic.set_value(s.get_int("mic_volume", 75))
        self._cmb_vu_decay.set_current_text(
            s.get("vu_decay_speed", "Normal (300ms decay)"))
        self._cmb_peak_hold.set_current_text(
            s.get("peak_hold_duration", "2 seconds"))
        self._tg_clip.set_on(s.get_bool("clip_indicator"))

        # Right column
        # cue_split_mode persisted by the option key (off / cue_left /
        # air_left / blend). Older rows may have a long human-readable
        # string; fall through to a sensible default in that case.
        cs = s.get("cue_split_mode", "cue_left") or "cue_left"
        if cs not in {k for k, _ in CUE_SPLIT_OPTIONS}:
            cs = "cue_left"
        self._cue_split.set_selected(cs)
        self._tg_show_preview.set_on(s.get_bool("show_crossfade_preview"))
        self._tg_flash_mix.set_on(s.get_bool("flash_mix_point"))

        # Audio Engine read-only displays
        self._info_buffer.set_value(
            f"{s.get('audio_buffer_size', '256')} samples (5ms)")
        self._info_rate.set_value(f"{s.get('sample_rate', '44100')} Hz")
        self._info_bit.set_value(s.get("bit_depth", "32-bit float"))
        self._info_engine.set_value(
            f"{s.get('audio_engine', 'WASAPI')} (Low Latency)")

    def _save_left(self) -> None:
        s = Settings()
        s.set("crossfade_duration", str(self._sl_crossfade.value()))
        s.set("fade_out_start",     str(self._sl_fade_out.value()))
        s.set("fade_curve_type",    self._curve.active())
        s.set("load_next_song",     self._cmb_load_next.current_text())
        s.set("preload_buffer",     self._cmb_preload.current_text())
        s.set("automix_trigger",    self._cmb_automix.current_text())
        s.set("fallback_action",    self._cmb_fallback.current_text())
        s.set("missing_file_alert",
              "1" if self._tg_missing_alert.is_on() else "0")

    def _save_center(self) -> None:
        s = Settings()
        s.set("autocue_threshold",   str(self._sl_autocue.value()))
        s.set("autocue_scan_mode",   self._cmb_autocue_scan.current_text())
        s.set("master_volume",       str(self._sl_master.value()))
        s.set("cue_volume",          str(self._sl_cue.value()))
        s.set("jingle_volume",       str(self._sl_jingle.value()))
        s.set("mic_volume",          str(self._sl_mic.value()))
        s.set("vu_decay_speed",      self._cmb_vu_decay.current_text())
        s.set("peak_hold_duration",  self._cmb_peak_hold.current_text())
        s.set("clip_indicator",      "1" if self._tg_clip.is_on() else "0")

    def _save_right(self) -> None:
        s = Settings()
        s.set("cue_split_mode",             self._cue_split.selected())
        s.set("show_crossfade_preview",
              "1" if self._tg_show_preview.is_on() else "0")
        s.set("flash_mix_point",
              "1" if self._tg_flash_mix.is_on() else "0")

    def _on_save_left(self) -> None:
        try:
            self._save_left()
        except Exception as exc:
            dialogs.warning(self, "Save failed", str(exc))
            return
        self.settings_saved.emit()
        dialogs.info(
            self, "Saved",
            "Transition + fade settings saved.")

    def _on_save_center(self) -> None:
        try:
            self._save_center()
        except Exception as exc:
            dialogs.warning(self, "Save failed", str(exc))
            return
        self.settings_saved.emit()
        dialogs.info(
            self, "Saved",
            "Audio levels + VU + AutoCue settings saved.")

    def _on_save_right(self) -> None:
        try:
            self._save_right()
        except Exception as exc:
            dialogs.warning(self, "Save failed", str(exc))
            return
        self.settings_saved.emit()
        dialogs.info(
            self, "Saved",
            "Cue split + preview + audio engine preferences saved.\n\n"
            "Audio engine changes take effect after RadioAI restart.")

    # ── Public API ────────────────────────────────────────────────────

    def reload(self) -> None:
        self._load_settings()
