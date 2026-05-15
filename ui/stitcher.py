"""
RadioAI Studio Pro — The Stitcher
Pixel-accurate match of Figma node 46:481 (file 7oN9K61g94wKx3nu44KKDF).

The Stitcher pre-mixes a "Coming Up Next" hook montage just before
ad breaks — opening jingle + N song hooks (separated by a swoosh) +
closing jingle. The whole sequence becomes ONE seamless WAV played
through BASS, so listeners hear:

    "Coming up next on KISS FM…"
    [hook from song A] [swoosh] [hook from song B] [swoosh] [hook
    from song C]
    "Stay tuned!"

…and then the break fires.

Layout (1440×900):
  Header           y=0..72         Logo, breadcrumb, title, clock, Open Studio
  Tab bar          y=72..108       3 module tabs (Next Songs Hooks active)
  Body             y=108..850
    Left col      300w  Module config: enabled toggle, 4 audio file
                          pickers, hook settings, Save Configuration
    Center col    510w  Audio Assembly Flow visual + Sample Playlist
                          Preview + Preview Full Stitcher Output
    Right col     430w  AI Insights/Stats + Recommendations + Other
                          Modules
  Status bar       y=850..900      Pills + version + Open Studio mini

Backend: existing `stitcher_config` schema (single row id=1) +
`core/stitcher_engine.py`. Hook cue points live on `songs.hook_in_ms`
+ `songs.hook_out_ms` (set via the Songs Library Audio Cue Editor).

Phase status:
  [✓] Tab 1 (Next Songs Hooks): config form, save round-trip,
      sample playlist preview from scheduler.peek_next, ▶ Preview
      Full Stitcher Output wires to StitcherEngine.play_block.
  [ ] Tab 2 (Real Time Announcement) — placeholder "Coming soon"
  [ ] Tab 3 (News Assembly) — placeholder
  [ ] AI Insights/Stats real metrics — placeholders for now
  [ ] Trigger wiring (engine fires before breaks) — Studio
      integration is a separate commit.
  [ ] Set-Hook deep-link to Audio Cue Editor — currently toasts.
"""

from __future__ import annotations

import logging
import os
from typing import Optional, Callable
from datetime import datetime
from core import dialogs

from PyQt6.QtCore import (
    Qt, QRectF, QTimer, pyqtSignal,
)
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QLinearGradient, QPainterPath, QFont,
    QCursor, QIntValidator,
)
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QHBoxLayout, QVBoxLayout,
    QScrollArea, QMessageBox, QLineEdit, QFileDialog,
)

from core.settings import Settings
from ui.widgets._tokens import (
    inter, mono, rgba,
    BG_BASE, BG_PANEL, BG_CARD, BG_ELEVATED,
    TEXT_PRI, TEXT_SEC, TEXT_MUTED, TEXT_DIM,
    CYAN, CYAN_LIGHT, PURPLE, PURPLE_LIGHT, PURPLE_DARK,
    GREEN, GREEN_LIGHT, AMBER, AMBER_LIGHT, RED, RED_LIGHT,
    PINK, PINK_LIGHT, TEAL, TEAL_LIGHT,
)

log = logging.getLogger("Stitcher")


# ════════════════════════════════════════════════════════════════════════════
# Geometry tokens
# ════════════════════════════════════════════════════════════════════════════

WINDOW_W = 1440
WINDOW_H = 900
HEADER_H = 72
TAB_BAR_H = 36
STATUS_H  = 50

LEFT_W   = 300
CENTER_W = 510
RIGHT_W  = WINDOW_W - LEFT_W - CENTER_W      # 630 → trim margins to 430

BODY_Y0 = HEADER_H + TAB_BAR_H               # 108
BODY_H  = WINDOW_H - BODY_Y0 - STATUS_H      # 742

# Trigger-mode dropdown options (single source of truth for the dropdown
# label cycler + the DB value written on Save).
TRIGGER_MODE_OPTIONS = [
    "Break reference",
    "Every N songs",
    "Top of hour",
    "Manual only",
]

# Module tab definitions — three radio-broadcast modules the stitcher
# can drive. Tab 1 is the only one fully wired in v1; the other two
# render placeholder content until separate sessions land them.
MODULE_TABS = (
    "Next Songs Hooks",
    "Real Time Announcement",
    "News Assembly",
)

# Sample-playlist row count — matches the Figma "next 3-4 hooks" cap.
SAMPLE_PREVIEW_COUNT = 5


# ════════════════════════════════════════════════════════════════════════════
# Header chrome — self-contained (mirrors sweepers_library.py / jingles_library.py
# pattern; future ui/widgets/library_chrome.py extraction stays a flagged
# carry-over).
# ════════════════════════════════════════════════════════════════════════════


class _HeaderLogo(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(40, 40)

    def paintEvent(self, e):
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


class _ActiveBreadcrumbChip(QFrame):
    """▶ The Stitcher — active breadcrumb crumb. Cyan accent matches the
    Figma frame's tab + status pill colors."""

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self.setFixedSize(140, 32)
        self.setStyleSheet(
            f"QFrame {{ background: {rgba(CYAN, 0.18)}; "
            f"border: 1px solid {rgba(CYAN, 0.40)}; border-radius: 16px; }}"
        )
        h = QHBoxLayout(self)
        h.setContentsMargins(12, 0, 14, 0); h.setSpacing(6)
        ic = QLabel("▶", self)
        ic.setFont(inter(11, QFont.Weight.Bold))
        ic.setStyleSheet(
            f"color: {CYAN_LIGHT}; background: transparent; border: none;")
        h.addWidget(ic)
        lbl = QLabel(label, self)
        lbl.setFont(inter(11, QFont.Weight.Bold))
        lbl.setStyleSheet(
            f"color: {CYAN_LIGHT}; background: transparent; border: none;")
        h.addWidget(lbl)
        h.addStretch()


# ════════════════════════════════════════════════════════════════════════════
# Tab bar
# ════════════════════════════════════════════════════════════════════════════


class _ModuleTab(QPushButton):
    """One of the three module tabs — Next Songs Hooks / Real Time
    Announcement / News Assembly. Active tab shows a colored underline
    + bright text; inactive tabs are dim with a tiny status bullet."""

    BULLETS = {
        "Next Songs Hooks":      CYAN,
        "Real Time Announcement": RED,
        "News Assembly":         GREEN,
    }

    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self._name = name
        self._active = False
        self._hover = False
        self.setFixedHeight(TAB_BAR_H)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFlat(True)
        self.setStyleSheet("QPushButton { background: transparent; "
                           "border: none; }")
        # Width sized to label — pad generously so click hit-zone is forgiving.
        self.setMinimumWidth(180)

    def set_active(self, on: bool) -> None:
        self._active = bool(on)
        self.update()

    def enterEvent(self, e):
        self._hover = True; self.update(); super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False; self.update(); super().leaveEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0, 0, self.width(), self.height())
        bullet_color = self.BULLETS.get(self._name, TEXT_MUTED)

        if self._active:
            # Cyan-tinted active background + bright underline
            p.fillRect(rect, QColor(rgba(CYAN, 0.10)))
            p.fillRect(QRectF(0, self.height() - 2, self.width(), 2),
                       QColor(CYAN))
            text_color = CYAN_LIGHT
        else:
            if self._hover:
                p.fillRect(rect, QColor(rgba("#ffffff", 0.03)))
            text_color = TEXT_SEC if self._hover else TEXT_MUTED

        # Bullet — colored dot before the label
        p.setBrush(QColor(bullet_color))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(14, int(self.height() / 2 - 4), 8, 8)

        # Label
        p.setPen(QColor(text_color))
        p.setFont(inter(11, QFont.Weight.Bold if self._active
                                   else QFont.Weight.Medium))
        p.drawText(QRectF(28, 0, self.width() - 36, self.height()),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._name)


# ════════════════════════════════════════════════════════════════════════════
# Left column — module config form widgets
# ════════════════════════════════════════════════════════════════════════════


class _SectionLabel(QLabel):
    def __init__(self, text: str, color: str = CYAN, parent=None):
        super().__init__(text.upper(), parent)
        self.setFont(inter(8, QFont.Weight.Bold, letter_spacing=1.4))
        self.setStyleSheet(
            f"color: {color}; background: transparent; border: none;")


class _ModuleEnabledCard(QFrame):
    """Top-of-left-column ✓ Module Enabled card — green tinted when
    on, dim red when disabled. Click anywhere on the row toggles."""

    toggled = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._enabled = True
        self.setFixedHeight(58)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

    def set_enabled(self, on: bool) -> None:
        was = self._enabled
        self._enabled = bool(on)
        self.update()
        if was != self._enabled:
            self.toggled.emit(self._enabled)

    def is_enabled(self) -> bool:
        return self._enabled

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.set_enabled(not self._enabled)
        super().mousePressEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        accent = QColor(GREEN) if self._enabled else QColor(rgba(RED, 0.45))
        bg = QColor(GREEN if self._enabled else RED)
        bg.setAlphaF(0.10 if self._enabled else 0.04)
        p.fillRect(QRectF(0, 0, w, h), bg)
        p.fillRect(QRectF(0, 0, 3, h), accent)
        bc = QColor(GREEN if self._enabled else "#1c1f38")
        if self._enabled:
            bc.setAlphaF(0.45)
        p.setPen(QPen(bc, 1)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 6, 6)
        # ✓ box
        box = QRectF(12, 18, 18, 18)
        if self._enabled:
            p.fillRect(box, QColor(GREEN))
            p.setPen(QColor("#04220f")); p.setFont(inter(11, QFont.Weight.Black))
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, "✓")
        else:
            p.fillRect(box, QColor("#0a0c18"))
            p.setPen(QPen(QColor(rgba("#ffffff", 0.20)), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(box)
        # Label
        p.setPen(QColor(GREEN_LIGHT if self._enabled else RED_LIGHT))
        p.setFont(inter(11, QFont.Weight.Bold))
        p.drawText(QRectF(38, 8, w - 50, 18),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "Module Enabled" if self._enabled else "Module Disabled")
        # Subtitle
        p.setPen(QColor(TEXT_MUTED)); p.setFont(inter(9))
        p.drawText(QRectF(38, 30, w - 50, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "Will broadcast before major breaks"
                   if self._enabled else "Off — no auto-stitching")


def _styled_lineedit(placeholder: str = "",
                     mono_font: bool = False) -> QLineEdit:
    e = QLineEdit()
    e.setPlaceholderText(placeholder)
    e.setFixedHeight(28)
    e.setFont(mono(10) if mono_font else inter(10))
    e.setStyleSheet(
        f"QLineEdit {{ background: {BG_CARD}; color: {TEXT_PRI}; "
        f"border: 1px solid {rgba('#ffffff', 0.06)}; border-radius: 5px; "
        f"padding-left: 8px; padding-right: 8px; }}"
        f"QLineEdit:focus {{ border-color: {rgba(CYAN, 0.45)}; }}"
        f"QLineEdit::placeholder {{ color: {TEXT_MUTED}; }}"
    )
    return e


class _AudioFileRow(QFrame):
    """Path field + ⋯ browse button + ▶ preview button. Used for the
    four config audio paths (opening / separator / closing / fallback).
    Operator picks a file via the file dialog; ▶ runs a short preview
    via the AudioEngine on a single shared preview channel."""

    path_changed = pyqtSignal(str)
    preview_clicked = pyqtSignal()

    def __init__(self, label: str, sub: str, parent=None):
        super().__init__(parent)
        self._label = label
        self.setFixedHeight(64)

        cap = QLabel(label, self)
        cap.setGeometry(0, 0, 240, 14)
        cap.setFont(inter(10, QFont.Weight.DemiBold))
        cap.setStyleSheet(
            f"color: {TEXT_PRI}; background: transparent;")

        if sub:
            sub_lbl = QLabel(sub, self)
            sub_lbl.setGeometry(0, 16, 280, 12)
            sub_lbl.setFont(inter(8))
            sub_lbl.setStyleSheet(
                f"color: {TEXT_MUTED}; background: transparent;")

        self._edit = _styled_lineedit("select file…")
        self._edit.setParent(self)
        self._edit.setGeometry(0, 32, 200, 28)
        self._edit.editingFinished.connect(
            lambda: self.path_changed.emit(self._edit.text()))

        self._browse = QPushButton("⋯", self)
        self._browse.setGeometry(204, 32, 32, 28)
        self._browse.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._browse.setFont(inter(13, QFont.Weight.Bold))
        self._browse.setStyleSheet(
            f"QPushButton {{ background: {BG_CARD}; color: {TEXT_SEC}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; "
            f"border-radius: 5px; }}"
            f"QPushButton:hover {{ background: {rgba(CYAN, 0.18)}; "
            f"color: {CYAN_LIGHT}; }}"
        )
        self._browse.clicked.connect(self._on_browse)

        self._preview = QPushButton("▶", self)
        self._preview.setGeometry(240, 32, 32, 28)
        self._preview.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._preview.setFont(inter(11, QFont.Weight.Black))
        self._preview.setStyleSheet(
            f"QPushButton {{ background: {rgba(GREEN, 0.18)}; "
            f"color: {GREEN_LIGHT}; "
            f"border: 1px solid {rgba(GREEN, 0.40)}; border-radius: 5px; }}"
            f"QPushButton:hover {{ background: {rgba(GREEN, 0.30)}; }}"
        )
        self._preview.clicked.connect(self.preview_clicked.emit)

    def set_path(self, p: str) -> None:
        self._edit.setText(p or "")

    def path(self) -> str:
        return self._edit.text().strip()

    def _on_browse(self) -> None:
        start_dir = ""
        if self._edit.text():
            start_dir = os.path.dirname(self._edit.text())
        path, _ = QFileDialog.getOpenFileName(
            self, f"Select {self._label.lower()} file", start_dir,
            "Audio files (*.mp3 *.wav *.ogg *.flac *.m4a);;All files (*.*)")
        if path:
            self._edit.setText(path)
            self.path_changed.emit(path)


class _DropdownButton(QPushButton):
    """Cycles through a list of options on click. Same pattern as the
    Jingles Library filter dropdowns — paints a chevron on the right."""

    picked = pyqtSignal(str)

    def __init__(self, options: list[str], parent=None):
        super().__init__(parent)
        self.setFixedHeight(28)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._options = list(options)
        self._idx = 0
        self.setFont(inter(10))
        self._apply_label()
        self.setStyleSheet(
            f"QPushButton {{ background: {BG_CARD}; color: {TEXT_PRI}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; border-radius: 5px; "
            f"text-align: left; padding-left: 10px; padding-right: 22px; }}"
            f"QPushButton:hover {{ border: 1px solid {rgba(CYAN, 0.40)}; }}"
        )
        self.clicked.connect(self._cycle)

    def _apply_label(self) -> None:
        self.setText(self._options[self._idx])

    def _cycle(self) -> None:
        self._idx = (self._idx + 1) % len(self._options)
        self._apply_label()
        self.picked.emit(self._options[self._idx])

    def value(self) -> str:
        return self._options[self._idx]

    def set_value(self, v: str) -> None:
        if v in self._options:
            self._idx = self._options.index(v)
            self._apply_label()

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(TEXT_MUTED), 1.2))
        cx = self.width() - 14; cy = self.height() / 2
        p.drawLine(int(cx - 4), int(cy - 2), int(cx), int(cy + 2))
        p.drawLine(int(cx + 4), int(cy - 2), int(cx), int(cy + 2))
        p.end()


# ════════════════════════════════════════════════════════════════════════════
# Center column — Audio Assembly Flow + Sample Playlist
# ════════════════════════════════════════════════════════════════════════════


class _AssemblyStep(QFrame):
    """One block in the Audio Assembly Flow visual — numbered tile
    showing OPENING / HOOK N / CLOSING with a sub-label + duration."""

    def __init__(self, n: int, kind: str, label: str, sub: str,
                 accent: str, parent=None):
        super().__init__(parent)
        self._n = int(n); self._kind = kind
        self._label = label; self._sub = sub
        self._accent = accent
        self.setFixedSize(126, 56)

    def set_label(self, label: str, sub: str) -> None:
        self._label = label; self._sub = sub
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        col = QColor(self._accent)
        bg = QColor(col); bg.setAlphaF(0.18)
        p.fillRect(rect, bg)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(rgba(self._accent, 0.45)), 1))
        p.drawRoundedRect(rect, 6, 6)
        # Header strip
        p.setPen(QColor(self._accent))
        p.setFont(inter(8, QFont.Weight.Bold, letter_spacing=1.0))
        p.drawText(QRectF(8, 4, self.width() - 16, 12),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   f"{self._n}. {self._kind.upper()}")
        # Label
        p.setPen(QColor(TEXT_PRI))
        p.setFont(inter(10, QFont.Weight.Bold))
        p.drawText(QRectF(8, 18, self.width() - 16, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._label or "—")
        # Sub
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(mono(8, bold=True))
        p.drawText(QRectF(8, 34, self.width() - 16, 12),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._sub or "")


class _SamplePlaylistRow(QFrame):
    """One row in the Sample Playlist Preview table — bullet + artist
    + title + hook range (or "No hook set" + Set Hook button)."""

    set_hook_requested = pyqtSignal(int)   # song id

    def __init__(self, song: dict, parent=None):
        super().__init__(parent)
        self._song = song
        self.setFixedHeight(32)
        sid = int(song.get("id") or 0)
        # Bullet color cycles by index (visual variety)
        accent = song.get("_accent_color") or PURPLE_LIGHT
        self._accent = accent

        if int(song.get("hook_in_ms") or 0) > 0 and int(
                song.get("hook_out_ms") or 0) > int(song.get("hook_in_ms") or 0):
            self._has_hook = True
        else:
            self._has_hook = False

        if not self._has_hook:
            btn = QPushButton("Set Hook", self)
            btn.setGeometry(0, 0, 80, 24)
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn.setFont(inter(9, QFont.Weight.Bold))
            btn.setStyleSheet(
                f"QPushButton {{ background: {rgba(AMBER, 0.20)}; "
                f"color: {AMBER_LIGHT}; "
                f"border: 1px solid {rgba(AMBER, 0.45)}; "
                f"border-radius: 4px; }}"
                f"QPushButton:hover {{ background: {rgba(AMBER, 0.30)}; }}"
            )
            btn.clicked.connect(lambda: self.set_hook_requested.emit(sid))
            self._set_btn = btn
        else:
            self._set_btn = None

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._set_btn is not None:
            self._set_btn.move(self.width() - 92, (self.height() - 24) // 2)

    def paintEvent(self, _e):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0, 0, self.width(), self.height())
        # Bottom hairline
        p.setPen(QPen(QColor(rgba("#ffffff", 0.05)), 1))
        p.drawLine(0, self.height() - 1, self.width(), self.height() - 1)
        # Bullet
        p.setBrush(QColor(self._accent)); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(8, int(self.height() / 2 - 4), 8, 8)
        # Artist
        p.setPen(QColor(TEXT_PRI)); p.setFont(inter(10, QFont.Weight.DemiBold))
        p.drawText(QRectF(24, 0, 140, self.height()),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   (self._song.get("artist") or "—")[:24])
        # Title
        p.setPen(QColor(TEXT_SEC)); p.setFont(inter(10))
        p.drawText(QRectF(168, 0, 200, self.height()),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   (self._song.get("title") or "—")[:30])
        # Hook range
        if self._has_hook:
            hi = int(self._song.get("hook_in_ms") or 0)
            ho = int(self._song.get("hook_out_ms") or 0)
            label = f"Hook: {_fmt_ms_short(hi)}–{_fmt_ms_short(ho)}"
            p.setPen(QColor(GREEN_LIGHT))
            p.setFont(mono(9, bold=True))
        else:
            label = "No hook set ⚠"
            p.setPen(QColor(AMBER))
            p.setFont(inter(9, QFont.Weight.Bold))
        p.drawText(QRectF(380, 0, self.width() - 484, self.height()),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   label)


def _fmt_ms_short(ms: int) -> str:
    s = max(0, int(ms) // 1000)
    return f"{s // 60}:{s % 60:02d}"


# ════════════════════════════════════════════════════════════════════════════
# Right column — AI Insights / Recommendations / Other Modules
# ════════════════════════════════════════════════════════════════════════════


class _StatCard(QFrame):
    """Compact KPI tile — colored top border, big number, sub label."""

    def __init__(self, label: str, value: str, accent: str, parent=None):
        super().__init__(parent)
        self._label = label; self._value = value; self._accent = accent
        self.setFixedSize(126, 64)

    def set_value(self, v: str) -> None:
        self._value = v
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        bg = QColor(self._accent); bg.setAlphaF(0.10)
        p.fillRect(rect, bg)
        p.setPen(QPen(QColor(rgba(self._accent, 0.40)), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 6, 6)
        # Top accent
        p.fillRect(QRectF(0, 0, self.width(), 2), QColor(self._accent))
        # Label
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(inter(8, QFont.Weight.Bold, letter_spacing=1.0))
        p.drawText(QRectF(10, 8, self.width() - 16, 12),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._label.upper())
        # Value
        p.setPen(QColor(self._accent))
        p.setFont(mono(18, bold=True))
        p.drawText(QRectF(10, 22, self.width() - 16, 28),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._value or "—")


class _RecommendationCard(QFrame):
    """One AI Recommendations row — colored left bar + title + body."""

    def __init__(self, kind: str, title: str, body: str,
                 accent: str, parent=None):
        super().__init__(parent)
        self._title = title; self._body = body; self._accent = accent
        self._kind = kind
        self.setFixedHeight(56)

    def paintEvent(self, _e):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        bg = QColor(self._accent); bg.setAlphaF(0.08)
        p.fillRect(rect, bg)
        p.setPen(QPen(QColor(rgba(self._accent, 0.30)), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 6, 6)
        # Left accent bar
        p.fillRect(QRectF(0, 0, 3, self.height()), QColor(self._accent))
        # Title
        p.setPen(QColor(self._accent))
        p.setFont(inter(10, QFont.Weight.Bold))
        p.drawText(QRectF(12, 6, self.width() - 16, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._title)
        # Body
        p.setPen(QColor(TEXT_SEC))
        p.setFont(inter(9))
        p.drawText(QRectF(12, 24, self.width() - 16, 28),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
                   | Qt.TextFlag.TextWordWrap,
                   self._body)


class _OtherModuleCard(QFrame):
    """Compact card for the OTHER MODULES list — small tile + title +
    sub + Configure → button."""

    configure_clicked = pyqtSignal(str)   # module name

    def __init__(self, name: str, sub: str, accent: str, parent=None):
        super().__init__(parent)
        self._name = name; self._sub = sub; self._accent = accent
        self.setFixedHeight(54)

        btn = QPushButton("Configure  →", self)
        btn.setFixedSize(96, 26)
        btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn.setFont(inter(9, QFont.Weight.Bold))
        btn.setStyleSheet(
            f"QPushButton {{ background: {rgba(accent, 0.20)}; "
            f"color: {accent}; "
            f"border: 1px solid {rgba(accent, 0.45)}; "
            f"border-radius: 5px; }}"
            f"QPushButton:hover {{ background: {rgba(accent, 0.30)}; }}"
        )
        btn.clicked.connect(lambda: self.configure_clicked.emit(self._name))
        self._btn = btn

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._btn.move(self.width() - 110, (self.height() - 26) // 2)

    def paintEvent(self, _e):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        bg = QColor(self._accent); bg.setAlphaF(0.06)
        p.fillRect(rect, bg)
        p.setPen(QPen(QColor(rgba(self._accent, 0.30)), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 6, 6)
        p.fillRect(QRectF(0, 0, 3, self.height()), QColor(self._accent))
        # Tile glyph
        p.setPen(QColor(self._accent))
        p.setFont(inter(11, QFont.Weight.Bold))
        p.drawText(QRectF(12, 4, self.width() - 130, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._name)
        # Sub
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(inter(9))
        p.drawText(QRectF(12, 22, self.width() - 130, 28),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
                   | Qt.TextFlag.TextWordWrap,
                   self._sub)


# ════════════════════════════════════════════════════════════════════════════
# Main screen
# ════════════════════════════════════════════════════════════════════════════


class Stitcher(QWidget):

    breadcrumb_clicked = pyqtSignal(str)
    studio_clicked     = pyqtSignal()
    songs_clicked      = pyqtSignal()       # deep-link "Set Hook" → Songs Library

    def __init__(self, db, parent=None, engine=None, scheduler=None,
                 stitcher_engine=None):
        super().__init__(parent)
        self._db = db
        self._engine = engine
        self._scheduler = scheduler
        self._stitcher_engine = stitcher_engine

        # State
        self._active_tab: str = MODULE_TABS[0]
        self._cfg: dict = {}
        self._sample_songs: list[dict] = []

        # Refs
        self._tab_widgets: dict[str, _ModuleTab] = {}
        self._enabled_card: Optional[_ModuleEnabledCard] = None
        self._row_opening: Optional[_AudioFileRow] = None
        self._row_separator: Optional[_AudioFileRow] = None
        self._row_closing: Optional[_AudioFileRow] = None
        self._row_fallback: Optional[_AudioFileRow] = None
        self._inp_min_hooks: Optional[QLineEdit] = None
        self._inp_max_hooks: Optional[QLineEdit] = None
        self._inp_hook_dur: Optional[QLineEdit] = None
        self._dd_trigger: Optional[_DropdownButton] = None
        self._save_btn: Optional[QPushButton] = None
        self._assembly_steps: list[_AssemblyStep] = []
        self._sample_layout: Optional[QVBoxLayout] = None
        self._sample_rows: list[_SamplePlaylistRow] = []
        self._total_dur_lbl: Optional[QLabel] = None
        self._stat_used: Optional[_StatCard] = None
        self._stat_retention: Optional[_StatCard] = None
        self._stat_no_hooks: Optional[_StatCard] = None
        self._clock_lbl: Optional[QLabel] = None
        self._left_panel: Optional[QWidget] = None
        self._center_panel: Optional[QWidget] = None
        self._right_panel: Optional[QWidget] = None
        self._tab_placeholder: Optional[QWidget] = None
        self._preview_cid: Optional[int] = None

        self.setFixedSize(WINDOW_W, WINDOW_H)
        self.setStyleSheet(
            "background: qlineargradient("
            "x1:0, y1:0, x2:1, y2:1, "
            "stop:0 #0a0d1a, stop:0.5 #06080f, stop:1 #020308);"
        )

        self._build_header()
        self._build_tab_bar()
        self._build_body()
        self._build_status_bar()

        self._load_config()
        self._refresh_assembly_flow()
        self._reload_sample_playlist()

        # Live clock
        self._tick()
        t = QTimer(self)
        t.setInterval(1000); t.timeout.connect(self._tick); t.start()

        log.info("Stitcher ready (Figma 46:481)")

    # ── HEADER ───────────────────────────────────────────────────────────

    def _build_header(self):
        bg = QFrame(self)
        bg.setGeometry(0, 0, WINDOW_W, HEADER_H)
        bg.setStyleSheet(
            f"background: qlineargradient(x1:0,y1:0,x2:0,y2:1, "
            f"stop:0 rgba(16,19,31,0.95), stop:1 rgba(10,12,22,0.95)); "
            f"border-bottom: 1px solid {rgba('#ffffff', 0.06)};"
        )
        hl = QFrame(self)
        hl.setGeometry(0, HEADER_H - 1, WINDOW_W, 1)
        hl.setStyleSheet(
            "background: qlineargradient(x1:0,y1:0,x2:1,y2:0, "
            "stop:0 rgba(255,255,255,0), stop:0.5 rgba(255,255,255,0.10), "
            "stop:1 rgba(255,255,255,0));"
        )

        _HeaderLogo(self).move(14, 16)
        l = QLabel("RadioAI", self)
        l.setGeometry(64, 14, 120, 18)
        l.setFont(inter(15, QFont.Weight.Bold))
        l.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        l = QLabel("STUDIO PRO", self)
        l.setGeometry(64, 34, 120, 12)
        l.setFont(inter(8, QFont.Weight.Bold, letter_spacing=1.2))
        l.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

        # Breadcrumb
        cp_btn = QPushButton("Control Panel", self)
        cp_btn.setGeometry(170, 22, 100, 22)
        cp_btn.setFont(inter(11, QFont.Weight.Medium))
        cp_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        cp_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {TEXT_MUTED}; "
            f"border: none; padding: 0; text-align: left; }}"
            f"QPushButton:hover {{ color: {TEXT_PRI}; }}"
        )
        cp_btn.clicked.connect(
            lambda: self.breadcrumb_clicked.emit("control_panel"))

        sep = QLabel("|", self); sep.setGeometry(266, 22, 8, 22)
        sep.setFont(inter(11))
        sep.setStyleSheet(f"color: {TEXT_DIM}; background: transparent;")

        l = QLabel("Libraries", self)
        l.setGeometry(276, 22, 60, 22)
        l.setFont(inter(11, QFont.Weight.Medium))
        l.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

        sep2 = QLabel("|", self); sep2.setGeometry(336, 22, 8, 22)
        sep2.setFont(inter(11))
        sep2.setStyleSheet(f"color: {TEXT_DIM}; background: transparent;")

        chip = _ActiveBreadcrumbChip("The Stitcher", self)
        chip.move(348, 20)

        # Title
        l = QLabel("The Stitcher", self)
        l.setGeometry(508, 12, 360, 24)
        l.setFont(inter(20, QFont.Weight.Bold))
        l.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        l = QLabel(
            "Automated audio production — hooks, time announcements and "
            "news assembly", self)
        l.setGeometry(508, 38, 540, 14)
        l.setFont(inter(10))
        l.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

        # Clock + station
        self._clock_lbl = QLabel("21:56:15", self)
        self._clock_lbl.setGeometry(1108, 14, 100, 24)
        self._clock_lbl.setFont(mono(20, bold=True))
        self._clock_lbl.setStyleSheet(
            f"color: {TEXT_PRI}; background: transparent;")
        l = QLabel(Settings().station_display, self)
        l.setObjectName("hdr_station_lbl")
        l.setGeometry(1108, 40, 100, 14)
        l.setFont(inter(9, QFont.Weight.Medium))
        l.setStyleSheet(f"color: {GREEN}; background: transparent;")

        osb = _HeaderOpenStudio(self)
        osb.move(1222, 16)
        osb.clicked.connect(self.studio_clicked.emit)

    # ── TAB BAR ──────────────────────────────────────────────────────────

    def _build_tab_bar(self):
        bg = QFrame(self)
        bg.setGeometry(0, HEADER_H, WINDOW_W, TAB_BAR_H)
        bg.setStyleSheet(
            f"background: rgba(8,10,18,0.95); "
            f"border-bottom: 1px solid {rgba('#ffffff', 0.06)};"
        )
        x = 16
        for name in MODULE_TABS:
            tab = _ModuleTab(name, self)
            tab.setGeometry(x, HEADER_H, 200, TAB_BAR_H)
            tab.set_active(name == self._active_tab)
            tab.clicked.connect(
                lambda _checked=False, n=name: self._on_tab_clicked(n))
            self._tab_widgets[name] = tab
            x += 220

    def _on_tab_clicked(self, name: str) -> None:
        if name == self._active_tab:
            return
        self._active_tab = name
        for k, t in self._tab_widgets.items():
            t.set_active(k == name)
        # Hide / show body panels per tab. Tab 1 is the only one fully
        # built; tabs 2+3 swap to a placeholder card.
        is_tab1 = (name == MODULE_TABS[0])
        for w in (self._left_panel, self._center_panel, self._right_panel):
            if w is not None:
                w.setVisible(is_tab1)
        if self._tab_placeholder is not None:
            self._tab_placeholder.setVisible(not is_tab1)
            if not is_tab1:
                self._update_tab_placeholder(name)
        log.info(f"[stitcher] tab → {name}")

    # ── BODY ─────────────────────────────────────────────────────────────

    def _build_body(self):
        # Left panel
        self._left_panel = QFrame(self)
        self._left_panel.setGeometry(0, BODY_Y0, LEFT_W, BODY_H)
        self._left_panel.setStyleSheet(
            f"QFrame {{ background: rgba(10,12,22,0.65); "
            f"border-right: 1px solid {rgba('#ffffff', 0.06)}; }}"
        )
        self._build_left_form()

        # Center panel
        self._center_panel = QFrame(self)
        self._center_panel.setGeometry(LEFT_W + 12, BODY_Y0,
                                       CENTER_W, BODY_H)
        self._center_panel.setStyleSheet("background: transparent;")
        self._build_center()

        # Right panel
        right_x = LEFT_W + CENTER_W + 24
        right_w = WINDOW_W - right_x - 12
        self._right_panel = QFrame(self)
        self._right_panel.setGeometry(right_x, BODY_Y0, right_w, BODY_H)
        self._right_panel.setStyleSheet("background: transparent;")
        self._build_right(right_w)

        # Tab 2/3 placeholder — single card centered in the body when
        # the operator switches off Tab 1. Lives parented to self so
        # it overlays the left/center/right panels (which get hidden).
        self._tab_placeholder = QFrame(self)
        self._tab_placeholder.setGeometry(40, BODY_Y0 + 40,
                                          WINDOW_W - 80, BODY_H - 80)
        self._tab_placeholder.setStyleSheet(
            f"QFrame {{ background: {rgba(PURPLE, 0.06)}; "
            f"border: 1px dashed {rgba(PURPLE, 0.40)}; "
            f"border-radius: 12px; }}"
        )
        self._tab_placeholder.setVisible(False)
        self._tab_placeholder_lbl = QLabel(
            "", self._tab_placeholder)
        self._tab_placeholder_lbl.setGeometry(40, 40,
            self._tab_placeholder.width() - 80,
            self._tab_placeholder.height() - 80)
        self._tab_placeholder_lbl.setFont(inter(13, QFont.Weight.Medium))
        self._tab_placeholder_lbl.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent;")
        self._tab_placeholder_lbl.setAlignment(
            Qt.AlignmentFlag.AlignCenter)
        self._tab_placeholder_lbl.setWordWrap(True)

    def _update_tab_placeholder(self, name: str) -> None:
        if name == "Real Time Announcement":
            txt = ("⏱   Real Time Announcement\n\n"
                   "Auto announces exact time by stitching prerecorded "
                   "time-of-day audio onto the broadcast deck.\n\n"
                   "Module lands in a separate session — config UI + "
                   "time-stitch engine + trigger wiring.")
        elif name == "News Assembly":
            txt = ("📰   News Assembly\n\n"
                   "Plays opening + bed (auto-trimmed) + news voiceover "
                   "+ closing as one seamless sequence.\n\n"
                   "Module lands in a separate session — pulls news audio "
                   "from a configurable folder + per-bulletin metadata.")
        else:
            txt = name + " — placeholder."
        self._tab_placeholder_lbl.setText(txt)

    # ── LEFT — module config form ────────────────────────────────────────

    def _build_left_form(self):
        wrap = self._left_panel
        # Section header
        hdr = _SectionLabel("MODULE: NEXT SONGS HOOKS", CYAN, wrap)
        hdr.setGeometry(14, 12, 280, 14)

        # Module Enabled card
        self._enabled_card = _ModuleEnabledCard(wrap)
        self._enabled_card.setGeometry(14, 32, LEFT_W - 28, 58)

        # AUDIO FILE CONFIGURATION section
        sec_y = 100
        cap = _SectionLabel("Audio File Configuration", AMBER, wrap)
        cap.setGeometry(14, sec_y, 280, 14)

        rows_y = sec_y + 18
        self._row_opening = _AudioFileRow(
            "Opening Audio", "Will broadcast before major breaks", wrap)
        self._row_opening.setGeometry(14, rows_y, LEFT_W - 28, 64)
        self._row_opening.preview_clicked.connect(
            lambda: self._preview_audio_file(self._row_opening.path()))

        self._row_separator = _AudioFileRow(
            "Songs Separator", "Plays between hooks", wrap)
        self._row_separator.setGeometry(14, rows_y + 70, LEFT_W - 28, 64)
        self._row_separator.preview_clicked.connect(
            lambda: self._preview_audio_file(self._row_separator.path()))

        self._row_closing = _AudioFileRow(
            "Closing Audio", "Plays after the last hook", wrap)
        self._row_closing.setGeometry(14, rows_y + 140, LEFT_W - 28, 64)
        self._row_closing.preview_clicked.connect(
            lambda: self._preview_audio_file(self._row_closing.path()))

        self._row_fallback = _AudioFileRow(
            "Default Fallback",
            "Used when min hooks not available", wrap)
        self._row_fallback.setGeometry(14, rows_y + 210, LEFT_W - 28, 64)
        self._row_fallback.preview_clicked.connect(
            lambda: self._preview_audio_file(self._row_fallback.path()))

        # HOOK SETTINGS section
        hs_y = rows_y + 290
        cap = _SectionLabel("Hook Settings", PURPLE_LIGHT, wrap)
        cap.setGeometry(14, hs_y, 280, 14)

        # Min songs with hooks required
        l = QLabel("Min songs with hooks required", wrap)
        l.setGeometry(14, hs_y + 22, 200, 14)
        l.setFont(inter(9, QFont.Weight.Medium))
        l.setStyleSheet(f"color: {TEXT_SEC}; background: transparent;")
        self._inp_min_hooks = _styled_lineedit("2")
        self._inp_min_hooks.setParent(wrap)
        self._inp_min_hooks.setGeometry(14, hs_y + 38, LEFT_W - 28, 28)
        self._inp_min_hooks.setValidator(QIntValidator(0, 10, wrap))

        # Max songs to announce
        l = QLabel("Max songs to announce", wrap)
        l.setGeometry(14, hs_y + 76, 200, 14)
        l.setFont(inter(9, QFont.Weight.Medium))
        l.setStyleSheet(f"color: {TEXT_SEC}; background: transparent;")
        self._inp_max_hooks = _styled_lineedit("4")
        self._inp_max_hooks.setParent(wrap)
        self._inp_max_hooks.setGeometry(14, hs_y + 92, LEFT_W - 28, 28)
        self._inp_max_hooks.setValidator(QIntValidator(1, 20, wrap))

        # Hook preview duration
        l = QLabel("Hook preview duration (seconds)", wrap)
        l.setGeometry(14, hs_y + 130, 220, 14)
        l.setFont(inter(9, QFont.Weight.Medium))
        l.setStyleSheet(f"color: {TEXT_SEC}; background: transparent;")
        self._inp_hook_dur = _styled_lineedit("8")
        self._inp_hook_dur.setParent(wrap)
        self._inp_hook_dur.setGeometry(14, hs_y + 146, LEFT_W - 28, 28)
        self._inp_hook_dur.setValidator(QIntValidator(1, 30, wrap))

        # Trigger mode dropdown
        l = QLabel("Announce when triggered by", wrap)
        l.setGeometry(14, hs_y + 184, 220, 14)
        l.setFont(inter(9, QFont.Weight.Medium))
        l.setStyleSheet(f"color: {TEXT_SEC}; background: transparent;")
        self._dd_trigger = _DropdownButton(TRIGGER_MODE_OPTIONS, wrap)
        self._dd_trigger.setGeometry(14, hs_y + 200, LEFT_W - 28, 28)

        # Save Configuration button
        save_y = hs_y + 244
        self._save_btn = QPushButton("✓ Save Configuration", wrap)
        self._save_btn.setGeometry(14, save_y, LEFT_W - 28, 36)
        self._save_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._save_btn.setFont(inter(11, QFont.Weight.Bold))
        self._save_btn.setStyleSheet(
            f"QPushButton {{ background: qlineargradient("
            f"x1:0,y1:0,x2:0,y2:1, stop:0 {GREEN_LIGHT}, stop:1 {GREEN}); "
            f"color: white; border: none; border-radius: 6px; }}"
            f"QPushButton:hover {{ background: qlineargradient("
            f"x1:0,y1:0,x2:0,y2:1, stop:0 #34d399, stop:1 {GREEN}); }}"
        )
        self._save_btn.clicked.connect(self._on_save_config)

    # ── CENTER — assembly flow + sample playlist ─────────────────────────

    def _build_center(self):
        wrap = self._center_panel
        # Section header
        hdr = _SectionLabel("How It Sounds — Preview", CYAN, wrap)
        hdr.setGeometry(0, 12, 280, 14)

        # "Audio Assembly Flow" sub-title
        sub = QLabel("Audio Assembly Flow", wrap)
        sub.setGeometry(0, 32, 220, 16)
        sub.setFont(inter(11, QFont.Weight.Bold))
        sub.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        sub2 = QLabel(
            "This is exactly what listeners will hear when Next Songs "
            "Hooks plays:", wrap)
        sub2.setGeometry(0, 50, CENTER_W, 12)
        sub2.setFont(inter(9))
        sub2.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

        # Assembly flow row — 5 steps (OPENING + 3 HOOKS + CLOSING)
        flow_y = 72
        self._assembly_steps = []
        accents = [AMBER, PURPLE_LIGHT, PURPLE_LIGHT, PURPLE_LIGHT, AMBER]
        kinds   = ["opening", "hook 1", "hook 2", "hook 3", "closing"]
        labels  = ["—", "—", "—", "—", "—"]
        subs    = ["", "", "", "", ""]
        for i in range(5):
            step = _AssemblyStep(i + 1, kinds[i], labels[i], subs[i],
                                 accents[i], wrap)
            # Two rows: 0..3 on row 1, last (closing) on row 2
            if i < 4:
                step.move(i * 130, flow_y)
            else:
                step.move(0, flow_y + 70)
            self._assembly_steps.append(step)

        # Total duration card next to closing
        self._total_dur_lbl = QLabel("Total Duration: —", wrap)
        self._total_dur_lbl.setGeometry(140, flow_y + 70, 220, 56)
        self._total_dur_lbl.setFont(inter(11, QFont.Weight.Bold))
        self._total_dur_lbl.setStyleSheet(
            f"QLabel {{ color: {TEXT_PRI}; "
            f"background: {BG_CARD}; "
            f"border: 1px solid {rgba(CYAN, 0.30)}; "
            f"border-radius: 6px; padding-left: 12px; }}")

        # SAMPLE PLAYLIST PREVIEW section
        sp_y = flow_y + 140
        cap = _SectionLabel("Sample Playlist Preview", PURPLE_LIGHT, wrap)
        cap.setGeometry(0, sp_y, 280, 14)
        hint = QLabel(
            "Select below to preview how stitcher will assemble", wrap)
        hint.setGeometry(0, sp_y + 18, CENTER_W, 12)
        hint.setFont(inter(9))
        hint.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

        # Scrollable sample list
        scroll = QScrollArea(wrap)
        scroll.setGeometry(0, sp_y + 36, CENTER_W, 32 * SAMPLE_PREVIEW_COUNT + 8)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }")
        body = QFrame(); body.setStyleSheet("background: transparent;")
        self._sample_layout = QVBoxLayout(body)
        self._sample_layout.setContentsMargins(0, 0, 0, 0)
        self._sample_layout.setSpacing(0)
        self._sample_layout.addStretch()
        scroll.setWidget(body)

        # Action buttons
        ab_y = sp_y + 36 + 32 * SAMPLE_PREVIEW_COUNT + 16
        prev_btn = QPushButton("▶  Preview Full Stitcher Output", wrap)
        prev_btn.setGeometry(0, ab_y, 280, 38)
        prev_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        prev_btn.setFont(inter(11, QFont.Weight.Bold))
        prev_btn.setStyleSheet(
            f"QPushButton {{ background: qlineargradient("
            f"x1:0,y1:0,x2:0,y2:1, stop:0 {CYAN_LIGHT}, stop:1 {CYAN}); "
            f"color: white; border: none; border-radius: 6px; }}"
            f"QPushButton:hover {{ background: qlineargradient("
            f"x1:0,y1:0,x2:0,y2:1, stop:0 #67e8f9, stop:1 {CYAN}); }}"
        )
        prev_btn.clicked.connect(self._on_preview_full)

        reset_btn = QPushButton("↺  Reset to Default Settings", wrap)
        reset_btn.setGeometry(290, ab_y, 220, 38)
        reset_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        reset_btn.setFont(inter(11, QFont.Weight.Bold))
        reset_btn.setStyleSheet(
            f"QPushButton {{ background: {BG_CARD}; color: {TEXT_SEC}; "
            f"border: 1px solid {rgba('#ffffff', 0.10)}; border-radius: 6px; }}"
            f"QPushButton:hover {{ color: {TEXT_PRI}; "
            f"border: 1px solid {rgba(AMBER, 0.40)}; }}"
        )
        reset_btn.clicked.connect(self._on_reset_defaults)

    # ── RIGHT — AI Insights + Recommendations + Other Modules ────────────

    def _build_right(self, panel_w: int):
        wrap = self._right_panel
        # AI INSIGHTS & STATS
        hdr = _SectionLabel("✦ AI Insights & Stats", PURPLE_LIGHT, wrap)
        hdr.setGeometry(0, 12, 280, 14)
        hint = QLabel("Powered by RadioAI Intelligence Engine", wrap)
        hint.setGeometry(0, 30, panel_w, 12)
        hint.setFont(inter(9))
        hint.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

        cards_y = 50
        self._stat_used = _StatCard("Times Used Today", "—", CYAN, wrap)
        self._stat_used.move(0, cards_y)
        self._stat_retention = _StatCard(
            "Avg Listener Retention", "—", GREEN, wrap)
        self._stat_retention.move(132, cards_y)
        self._stat_no_hooks = _StatCard(
            "Songs Without Hooks", "—", RED, wrap)
        self._stat_no_hooks.move(264, cards_y)

        # AI RECOMMENDATIONS
        rec_y = cards_y + 80
        cap = _SectionLabel("AI Recommendations", PURPLE_LIGHT, wrap)
        cap.setGeometry(0, rec_y, 280, 14)
        recs = [
            (RED,
             "● Missing Hooks",
             "One or more songs in the upcoming queue have no hook "
             "set. Set hooks via Audio Cue Editor in Songs Library."),
            (GREEN,
             "▶ Timing Optimal",
             "Current 0–39s duration is fine — listeners stay engaged "
             "for under 45s tease blocks."),
            (PURPLE_LIGHT,
             "+ Increase to 4 hooks",
             "Adding one more song hook will improve engagement by "
             "≈6%."),
            (AMBER_LIGHT,
             "◆ Schedule Insight",
             "This routine fires before every break — consider "
             "scheduling before 13:00, 16:00 and 18:00 break windows."),
        ]
        ry = rec_y + 22
        for accent, title, body in recs:
            card = _RecommendationCard("rec", title, body, accent, wrap)
            card.setGeometry(0, ry, panel_w, 56)
            ry += 64

        # OTHER MODULES section
        om_y = ry + 8
        cap = _SectionLabel("Other Modules", AMBER_LIGHT, wrap)
        cap.setGeometry(0, om_y, 280, 14)
        modules = [
            ("Real Time Announcement",
             "Auto announces exact time by stitching prerecorded ti…",
             AMBER_LIGHT),
            ("News Assembly",
             "Plays opening + bed (auto-trimmed) + news voiceover …",
             GREEN_LIGHT),
        ]
        my = om_y + 22
        for name, sub, accent in modules:
            card = _OtherModuleCard(name, sub, accent, wrap)
            card.setGeometry(0, my, panel_w, 54)
            card.configure_clicked.connect(self._on_other_module_configure)
            my += 60

    # ── STATUS BAR ───────────────────────────────────────────────────────

    def _build_status_bar(self):
        sb = QFrame(self)
        sb.setGeometry(0, WINDOW_H - STATUS_H, WINDOW_W, STATUS_H)
        sb.setStyleSheet(
            f"QFrame {{ background: rgba(13,15,30,0.95); "
            f"border-top: 1px solid {rgba('#ffffff', 0.06)}; }}"
        )

        def _pill(x, text, fg, bg, w=110):
            l = QLabel(text, sb)
            l.setGeometry(x, 14, w, 22)
            l.setFont(inter(9, QFont.Weight.Bold, letter_spacing=1.0))
            l.setStyleSheet(
                f"QLabel {{ background: {bg}; color: {fg}; "
                f"border-radius: 11px; padding-left: 10px; }}"
            )
            return l

        _pill(12,  "● AUTO MODE", PURPLE_LIGHT, rgba(PURPLE, 0.18))
        _pill(130, "● AI Active", GREEN_LIGHT,  rgba(GREEN,  0.18), w=96)
        _pill(234, "● 3 Modules Ready",
              AMBER_LIGHT, rgba(AMBER, 0.18), w=140)

        version = QLabel(
            "The Stitcher  ·  RadioAI Studio v2.0", sb)
        version.setGeometry(WINDOW_W - 380, 16, 280, 16)
        version.setFont(inter(9))
        version.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent;")
        version.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        os_btn = QPushButton("▶  Open Studio", sb)
        os_btn.setGeometry(WINDOW_W - 100, 12, 88, 26)
        os_btn.setFont(inter(10, QFont.Weight.Bold))
        os_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        os_btn.setStyleSheet(
            f"QPushButton {{ background: {rgba(GREEN, 0.18)}; color: {GREEN_LIGHT}; "
            f"border: 1px solid {rgba(GREEN, 0.4)}; border-radius: 5px; }}"
            f"QPushButton:hover {{ background: {rgba(GREEN, 0.30)}; }}"
        )
        os_btn.clicked.connect(self.studio_clicked.emit)

    # ── DATA / SAVE ──────────────────────────────────────────────────────

    def _load_config(self):
        """Pull current stitcher_config from DB and populate widgets."""
        try:
            self._cfg = self._db.get_stitcher_config()
        except Exception as exc:
            log.warning(f"[stitcher] config load failed: {exc}")
            self._cfg = {}
        c = self._cfg
        if self._enabled_card:
            self._enabled_card.set_enabled(bool(c.get("module_enabled", 1)))
        if self._row_opening:
            self._row_opening.set_path(c.get("opening_audio") or "")
        if self._row_separator:
            self._row_separator.set_path(c.get("separator_audio") or "")
        if self._row_closing:
            self._row_closing.set_path(c.get("closing_audio") or "")
        if self._row_fallback:
            self._row_fallback.set_path(c.get("fallback_audio") or "")
        if self._inp_min_hooks:
            self._inp_min_hooks.setText(str(int(c.get("min_hooks_required") or 2)))
        if self._inp_max_hooks:
            self._inp_max_hooks.setText(str(int(c.get("max_hooks") or 4)))
        if self._inp_hook_dur:
            self._inp_hook_dur.setText(str(int(c.get("hook_duration_seconds") or 8)))
        if self._dd_trigger:
            label = self._trigger_value_to_label(c.get("trigger_mode") or "")
            self._dd_trigger.set_value(label)
        # Stat cards — Songs Without Hooks is computable; the others
        # need broadcast_log / retention metrics that aren't tracked
        # for stitcher output yet, so they stay "—".
        try:
            row = self._db._conn().execute(
                "SELECT COUNT(*) FROM songs WHERE is_enabled = 1 AND ("
                "hook_in_ms IS NULL OR hook_out_ms IS NULL OR "
                "hook_in_ms = 0 OR hook_out_ms <= hook_in_ms)"
            ).fetchone()
            no_hooks_count = int(row[0]) if row else 0
        except Exception:
            no_hooks_count = 0
        if self._stat_no_hooks:
            self._stat_no_hooks.set_value(str(no_hooks_count))

    def _on_save_config(self):
        """Collect form state and persist via update_stitcher_config."""
        try:
            min_h = max(0, int(self._inp_min_hooks.text() or 2))
        except Exception:
            min_h = 2
        try:
            max_h = max(1, int(self._inp_max_hooks.text() or 4))
        except Exception:
            max_h = 4
        try:
            dur_s = max(1, int(self._inp_hook_dur.text() or 8))
        except Exception:
            dur_s = 8
        if min_h > max_h:
            dialogs.warning(
                self, "Invalid range",
                "Min songs with hooks required cannot exceed Max songs "
                "to announce.")
            return
        trigger_label = self._dd_trigger.value() if self._dd_trigger else (
            "Break reference")
        trigger_db = self._trigger_label_to_value(trigger_label)
        data = {
            "module_enabled":           self._enabled_card.is_enabled()
                                        if self._enabled_card else True,
            "opening_audio":            self._row_opening.path()
                                        if self._row_opening else "",
            "separator_audio":          self._row_separator.path()
                                        if self._row_separator else "",
            "closing_audio":            self._row_closing.path()
                                        if self._row_closing else "",
            "fallback_audio":           self._row_fallback.path()
                                        if self._row_fallback else "",
            "min_hooks_required":       min_h,
            "max_hooks":                max_h,
            "hook_duration_seconds":    dur_s,
            "trigger_mode":             trigger_db,
            "trigger_before_every_break":
                1 if trigger_db == "break_reference" else 0,
            "trigger_every_n_songs":
                1 if trigger_db == "every_n_songs" else 0,
            "trigger_top_of_hour":
                1 if trigger_db == "top_of_hour" else 0,
        }
        try:
            self._db.update_stitcher_config(data)
        except Exception as exc:
            log.error(f"[stitcher] save failed: {exc}", exc_info=True)
            dialogs.error(
                self, "Save failed",
                f"Could not save stitcher config:\n\n{exc}")
            return
        log.info(
            f"[stitcher] config saved: "
            f"trigger={trigger_db} min/max={min_h}/{max_h} "
            f"dur={dur_s}s enabled={data['module_enabled']}")
        # Refresh in-memory cache + assembly flow visual.
        self._load_config()
        self._refresh_assembly_flow()
        dialogs.info(
            self, "Saved", "Stitcher configuration saved.")

    @staticmethod
    def _trigger_label_to_value(label: str) -> str:
        return {
            "Break reference": "break_reference",
            "Every N songs":   "every_n_songs",
            "Top of hour":     "top_of_hour",
            "Manual only":     "manual",
        }.get(label, "break_reference")

    @staticmethod
    def _trigger_value_to_label(value: str) -> str:
        return {
            "break_reference": "Break reference",
            "every_n_songs":   "Every N songs",
            "top_of_hour":     "Top of hour",
            "manual":          "Manual only",
        }.get(value or "", "Break reference")

    # ── SAMPLE PLAYLIST ──────────────────────────────────────────────────

    def _reload_sample_playlist(self):
        """Pull next-N upcoming songs from the scheduler and surface
        their hook ranges. Falls back to a recent-songs query when no
        scheduler is wired (decorative / test path)."""
        rows: list[dict] = []
        if (self._scheduler is not None
                and hasattr(self._scheduler, "peek_next")):
            try:
                items = self._scheduler.peek_next(SAMPLE_PREVIEW_COUNT) or []
            except Exception as exc:
                log.debug(f"[stitcher] scheduler peek failed: {exc}")
                items = []
            for it in items:
                if (it or {}).get("item_type") != "song":
                    continue
                rid = it.get("item_id") or it.get("song_id")
                if rid is None:
                    continue
                try:
                    song = self._db._conn().execute(
                        "SELECT id, title, artist, hook_in_ms, "
                        "hook_out_ms FROM songs WHERE id = ?",
                        [int(rid)]).fetchone()
                except Exception:
                    song = None
                if song:
                    rows.append(dict(song))
        if not rows:
            try:
                fb = self._db._conn().execute(
                    "SELECT id, title, artist, hook_in_ms, hook_out_ms "
                    "FROM songs WHERE is_enabled = 1 "
                    "ORDER BY id DESC LIMIT ?",
                    [SAMPLE_PREVIEW_COUNT]).fetchall()
                rows = [dict(r) for r in fb]
            except Exception:
                rows = []
        # Cycle accent colors by index for visual variety.
        ACCENTS = [PURPLE_LIGHT, CYAN, RED, AMBER, GREEN]
        for i, r in enumerate(rows):
            r["_accent_color"] = ACCENTS[i % len(ACCENTS)]
        self._sample_songs = rows
        self._render_sample_playlist()
        self._refresh_assembly_flow()

    def _render_sample_playlist(self):
        if self._sample_layout is None:
            return
        for w in self._sample_rows:
            w.setParent(None); w.deleteLater()
        self._sample_rows = []
        for s in self._sample_songs:
            row = _SamplePlaylistRow(s)
            row.set_hook_requested.connect(self._on_set_hook_requested)
            self._sample_layout.insertWidget(
                len(self._sample_rows), row)
            self._sample_rows.append(row)

    def _refresh_assembly_flow(self):
        """Update the Audio Assembly Flow tiles with names + durations
        derived from the saved config + the sample playlist's hook
        ranges."""
        cfg = self._cfg
        hook_dur_s = int(cfg.get("hook_duration_seconds") or 8)
        max_hooks = int(cfg.get("max_hooks") or 4)
        # OPENING tile
        if self._assembly_steps:
            opening_name = os.path.basename(cfg.get("opening_audio") or "") \
                           or "—"
            self._assembly_steps[0].set_label(
                opening_name, "auto-trim")
        # HOOK 1..3 tiles
        for i in range(1, 4):
            if i - 1 < len(self._sample_songs) and i - 1 < max_hooks:
                song = self._sample_songs[i - 1]
                title = (song.get("title") or "—")[:18]
                artist = (song.get("artist") or "—")[:18]
                self._assembly_steps[i].set_label(
                    artist, title)
            else:
                self._assembly_steps[i].set_label("—", "")
        # CLOSING tile
        if len(self._assembly_steps) >= 5:
            closing_name = os.path.basename(cfg.get("closing_audio") or "") \
                           or "—"
            self._assembly_steps[4].set_label(
                closing_name, "auto-trim")
        # Total duration estimate: opening 4s + N×hook_dur + (N-1)×sep
        # + closing 4s. We don't probe the actual files here; this is a
        # quick visual estimate that matches the Figma "≈0:39" hint.
        n_hooks = min(max_hooks, len(self._sample_songs), 3)
        total_s = 4 + n_hooks * hook_dur_s + max(0, n_hooks - 1) * 1 + 4
        if self._total_dur_lbl:
            self._total_dur_lbl.setText(
                f"Total Duration: ~{_fmt_ms_short(total_s * 1000)}")

    # ── EVENT HANDLERS ───────────────────────────────────────────────────

    def _preview_audio_file(self, path: str) -> None:
        """One-shot preview of an arbitrary file via AudioEngine on a
        dedicated single-channel preview slot. Idempotent — clicking ▶
        again on the same row stops the previous preview first."""
        if self._engine is None:
            log.warning("[stitcher] preview skipped — no AudioEngine")
            return
        if not path:
            return
        if not os.path.exists(path):
            log.warning(f"[stitcher] preview file missing: {path}")
            dialogs.warning(
                self, "File missing",
                f"Could not preview — file not found:\n\n{path}")
            return
        # Tear down any previous preview first.
        if self._preview_cid is not None:
            try:
                self._engine.cleanup(self._preview_cid)
            except Exception:
                pass
            self._preview_cid = None
        try:
            cid = self._engine.load_file(path)
            self._engine.set_volume(cid, 80)
            self._engine.play(cid)
            self._preview_cid = cid
            log.info(f"[stitcher] preview ch={cid} path={path}")
        except Exception as exc:
            log.warning(f"[stitcher] preview load_file failed: {exc}")

    def _on_preview_full(self) -> None:
        """▶ Preview Full Stitcher Output — assembles a sequence dict
        from the current config + sample playlist hooks and routes it
        through StitcherEngine.play_block(...). The engine concatenates
        opening + N hook clips + closing into one tempfile WAV and
        plays through BASS."""
        if self._stitcher_engine is None:
            dialogs.info(
                self, "Engine not wired",
                "The Stitcher engine isn't attached to this Studio "
                "session. Restart the app — MainWindow injects the "
                "shared instance at boot.")
            return
        cfg = self._cfg
        if not cfg.get("module_enabled"):
            dialogs.info(
                self, "Module disabled",
                "Enable the module first (toggle the green card) "
                "before previewing the assembly.")
            return
        sequence: list[dict] = []
        opening = (cfg.get("opening_audio") or "").strip()
        sep = (cfg.get("separator_audio") or "").strip()
        closing = (cfg.get("closing_audio") or "").strip()
        max_hooks = int(cfg.get("max_hooks") or 4)
        if opening and os.path.exists(opening):
            sequence.append(
                {"file_path": opening, "play_full": True,
                 "label": "OPENING"})
        # Pick songs that have a hook set; cap at max_hooks.
        hooked = [s for s in self._sample_songs
                  if int(s.get("hook_in_ms") or 0) > 0
                  and int(s.get("hook_out_ms") or 0)
                          > int(s.get("hook_in_ms") or 0)]
        hooked = hooked[:max_hooks]
        if len(hooked) < int(cfg.get("min_hooks_required") or 2):
            fb = (cfg.get("fallback_audio") or "").strip()
            if fb and os.path.exists(fb):
                log.info(
                    "[stitcher] not enough hooks — using fallback audio")
                sequence = [{"file_path": fb, "play_full": True,
                             "label": "FALLBACK"}]
            else:
                dialogs.warning(
                    self, "Not enough hooks",
                    f"Only {len(hooked)} song(s) have hooks set — "
                    f"min required is "
                    f"{cfg.get('min_hooks_required', 2)}. Set hooks "
                    f"via the Audio Cue Editor in Songs Library, or "
                    f"configure a Default Fallback audio.")
                return
        else:
            for i, song in enumerate(hooked):
                hi = int(song.get("hook_in_ms") or 0)
                ho = int(song.get("hook_out_ms") or 0)
                # Resolve the song's actual file_path for the engine.
                row = self._db._conn().execute(
                    "SELECT file_path FROM songs WHERE id = ?",
                    [int(song.get("id") or 0)]).fetchone()
                fp = row[0] if row else None
                if not fp or not os.path.exists(fp):
                    continue
                sequence.append({
                    "file_path": fp,
                    "seek_sec":  hi / 1000.0,
                    "label":     song.get("title") or "HOOK",
                })
                # Insert separator between hooks (not after the last).
                if i < len(hooked) - 1 and sep and os.path.exists(sep):
                    sequence.append(
                        {"file_path": sep, "play_full": True,
                         "label": "SEP"})
        if closing and os.path.exists(closing):
            sequence.append(
                {"file_path": closing, "play_full": True,
                 "label": "CLOSING"})
        if not sequence:
            dialogs.warning(
                self, "Nothing to play",
                "Could not assemble a stitcher sequence — no audio "
                "paths configured or no hooks resolvable to playable "
                "files.")
            return
        try:
            self._stitcher_engine.play_block(
                sequence, target_vol=85,
                on_done=lambda: log.info("[stitcher] preview done"))
            log.info(
                f"[stitcher] preview firing — {len(sequence)} parts")
        except Exception as exc:
            log.error(f"[stitcher] play_block failed: {exc}",
                      exc_info=True)
            dialogs.error(
                self, "Preview failed", str(exc))

    def _on_reset_defaults(self) -> None:
        if not dialogs.confirm(
                self, "Reset to defaults?",
                "This will reset Hook Settings (min / max / duration / "
                "trigger mode) to the factory defaults. Audio file paths "
                "stay untouched.\n\nContinue?",
                yes_label="Reset"):
            return
        try:
            self._db.update_stitcher_config({
                "min_hooks_required": 2,
                "max_hooks": 4,
                "hook_duration_seconds": 8,
                "trigger_mode": "break_reference",
                "trigger_before_every_break": 1,
                "trigger_every_n_songs": 0,
                "trigger_top_of_hour": 0,
            })
        except Exception as exc:
            log.error(f"[stitcher] reset failed: {exc}", exc_info=True)
            return
        self._load_config()
        self._refresh_assembly_flow()

    def _on_set_hook_requested(self, song_id: int) -> None:
        log.info(
            f"[stitcher] Set Hook clicked for song id={song_id} "
            f"(deep-link to Audio Cue Editor — TODO)")
        dialogs.info(
            self, "Set Hook",
            "Hook editing happens in the Audio Cue Editor in Songs "
            "Library. Open Songs Library → pick the row → CUE EDIT to "
            "set Hook In / Hook Out.")
        # Fire breadcrumb to nudge the operator over.
        self.songs_clicked.emit()

    def _on_other_module_configure(self, name: str) -> None:
        log.info(f"[stitcher] Configure → {name}")
        dialogs.info(
            self, "Coming soon",
            f"{name} module configuration lands in a separate "
            f"session.")

    # ── CLOCK ────────────────────────────────────────────────────────────

    def _tick(self):
        if self._clock_lbl:
            self._clock_lbl.setText(datetime.now().strftime("%H:%M:%S"))
