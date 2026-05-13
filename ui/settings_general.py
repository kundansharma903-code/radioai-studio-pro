"""
RadioAI Studio Pro — General Settings
Pixel-accurate match of Figma node 68:2 (file 7oN9K61g94wKx3nu44KKDF).

Top-level Settings page (currently the only Settings sub-page). The
operator edits station identity, library paths, startup behaviour,
date/time format and backup preferences. All fields persist to the
existing `settings` table via the Settings singleton + db.set_setting.

Layout (1440 × 900):
  Header        y=  0.. 72   Logo + breadcrumb + title + clock + Open Studio
  Body          y= 72..864   Two columns, ~16px gap
    Left col   700w  STATION IDENTITY + FILE PATHS + Save Station Settings
    Right col  700w  STARTUP & BEHAVIOUR + DATE/TIME + BACKUP + Save All
  Status bar    y=864..900   AUTO MODE · Settings · All OK pills + version

Settings keys (all already in the DB except where flagged NEW):
  station_name, station_city, station_region, station_frequency,
  station_slogan, station_email
  path_music, path_recordings, path_logs, path_exports, path_backup
  start_on_windows_startup, auto_load_last_session, start_in_auto_mode,
  show_splash_screen, minimize_to_tray, check_updates, send_usage_stats
  date_format, time_format
  timezone           (NEW — default 'IST — Asia/Kolkata (UTC+5:30)')
  language           (NEW — default 'English (India)')
  backup_interval    (NEW — default 'Every 24 hours')

Public signals:
  breadcrumb_clicked(str) — header breadcrumb / tab navigation
  studio_clicked()        — header Open Studio button

v1 scope cuts (per pre-build pushback, deferred to v1.1):
  - Backup Now / Restore Backup: toast "Coming v1.1" (real backup wiring
    is platform-heavy + risky for live data)
  - "Start on Windows startup" toggle writes to DB only; the actual
    Windows registry write is v1.1
  - "Start in AUTO MODE automatically" writes to DB only; the Studio
    boot behaviour change is v1.1
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Tuple

from PyQt6.QtCore import Qt, QRectF, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QLinearGradient, QFont, QCursor,
)
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QLineEdit, QComboBox,
    QHBoxLayout, QVBoxLayout, QScrollArea, QMessageBox, QFileDialog,
)

from core.settings import Settings
from ui.widgets._tokens import (
    inter, mono, rgba,
    BG_BASE, BG_DARK, BG_PANEL, BG_CARD, BG_CARD_DK, BG_ELEVATED,
    TEXT_PRI, TEXT_SEC, TEXT_MUTED, TEXT_DIM,
    CYAN, CYAN_LIGHT, PURPLE, PURPLE_LIGHT, PURPLE_DARK,
    GREEN, GREEN_LIGHT, AMBER, AMBER_LIGHT, RED, RED_LIGHT,
    PINK, TEAL, TEAL_LIGHT,
)

log = logging.getLogger("SettingsGeneral")


# ════════════════════════════════════════════════════════════════════════════
# Geometry
# ════════════════════════════════════════════════════════════════════════════

WINDOW_W   = 1440
WINDOW_H   = 900
HEADER_H   = 72
STATUS_H   = 36
BODY_Y0    = HEADER_H
BODY_H     = WINDOW_H - HEADER_H - STATUS_H   # 792
COL_GAP    = 12
COL_PAD    = 16
COL_W      = (WINDOW_W - COL_GAP) // 2        # 714

# Toggle options
DATE_FORMATS = ["DD/MM/YYYY", "MM/DD/YYYY", "YYYY-MM-DD",
                "DD-MMM-YYYY", "MMM DD, YYYY"]
TIME_FORMATS = ["24-hour (HH:MM:SS)", "12-hour (HH:MM:SS AM/PM)",
                "24-hour (HH:MM)", "12-hour (HH:MM AM/PM)"]
TIMEZONES = [
    "IST — Asia/Kolkata (UTC+5:30)",
    "UTC",
    "GMT — Europe/London",
    "EST — America/New_York (UTC-5)",
    "PST — America/Los_Angeles (UTC-8)",
    "JST — Asia/Tokyo (UTC+9)",
    "AEST — Australia/Sydney (UTC+10)",
]
LANGUAGES = [
    "English (India)", "English (US)", "English (UK)",
    "Hindi", "Marathi", "Tamil", "Bengali",
]
BACKUP_INTERVALS = [
    "Every 6 hours", "Every 12 hours", "Every 24 hours",
    "Every 3 days", "Every 7 days", "Manual only",
]


# ════════════════════════════════════════════════════════════════════════════
# Header chrome — RadioAI logo + breadcrumb + title + clock + Open Studio
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
    """Gray link in the breadcrumb chain (Control Panel · Settings ·)."""

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
    """Active breadcrumb crumb — amber-tinted pill matching the design."""

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self.setFixedSize(140, 32)
        self.setStyleSheet(
            f"QFrame {{ background: {rgba(AMBER, 0.18)}; "
            f"border: 1px solid {rgba(AMBER, 0.40)}; border-radius: 16px; }}"
        )
        h = QHBoxLayout(self)
        h.setContentsMargins(14, 0, 14, 0); h.setSpacing(0)
        lbl = QLabel(label, self)
        lbl.setFont(inter(11, QFont.Weight.Bold))
        lbl.setStyleSheet(
            f"color: {AMBER_LIGHT}; background: transparent; border: none;")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h.addWidget(lbl)


# ════════════════════════════════════════════════════════════════════════════
# Card chrome — section card with colored top accent + heading
# ════════════════════════════════════════════════════════════════════════════


class _SectionCard(QFrame):
    """Form-section card with a 4px colored top accent stripe + heading.
    Children are added to the QVBoxLayout via add_row()."""

    def __init__(self, title: str, accent: str, parent=None):
        super().__init__(parent)
        self._accent = accent
        self.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; "
            f"border-radius: 8px; }}"
        )
        # Manual layout — we draw the accent in paintEvent + lay rows
        # inside a content frame so accent stripe stays pixel-perfect.
        self._title = title
        self._body = QFrame(self)
        self._body.setStyleSheet("QFrame { background: transparent; "
                                  "border: none; }")
        self._body_v = QVBoxLayout(self._body)
        self._body_v.setContentsMargins(20, 36, 20, 16)
        self._body_v.setSpacing(12)

    def paintEvent(self, e):
        # 1px accent stripe at top, plus a small heading band
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(QRectF(0, 0, self.width(), 4), QColor(self._accent))
        p.setPen(QColor(self._accent))
        p.setFont(inter(9, QFont.Weight.Bold, letter_spacing=1.4))
        p.drawText(QRectF(20, 8, self.width() - 40, 20),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._title.upper())
        p.end()
        super().paintEvent(e)

    def resizeEvent(self, e):
        self._body.setGeometry(0, 0, self.width(), self.height())
        super().resizeEvent(e)

    def add_row(self, widget: QWidget) -> None:
        self._body_v.addWidget(widget)

    def add_stretch(self) -> None:
        self._body_v.addStretch()


# ════════════════════════════════════════════════════════════════════════════
# Form widgets — labeled text input, labeled dropdown, browse-row, toggle
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


class _DarkLineEdit(QLineEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(34)
        self.setFont(inter(12))
        self.setStyleSheet(
            f"QLineEdit {{ background: {BG_DARK}; color: {TEXT_PRI}; "
            f"border: 1px solid {rgba('#ffffff', 0.08)}; "
            f"border-radius: 6px; padding: 0 10px; }}"
            f"QLineEdit:hover {{ "
            f"border: 1px solid {rgba(AMBER, 0.40)}; }}"
            f"QLineEdit:focus {{ "
            f"border: 1px solid {rgba(AMBER, 0.70)}; }}"
        )


class _DarkComboBox(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(34)
        self.setFont(inter(12))
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setStyleSheet(
            f"QComboBox {{ background: {BG_DARK}; color: {TEXT_PRI}; "
            f"border: 1px solid {rgba('#ffffff', 0.08)}; "
            f"border-radius: 6px; padding: 0 10px; }}"
            f"QComboBox:hover {{ "
            f"border: 1px solid {rgba(AMBER, 0.40)}; }}"
            f"QComboBox::drop-down {{ border: none; width: 24px; }}"
            f"QComboBox::down-arrow {{ image: none; }}"
            f"QComboBox QAbstractItemView {{ background: {BG_PANEL}; "
            f"color: {TEXT_PRI}; "
            f"selection-background-color: {rgba(AMBER, 0.25)}; "
            f"border: 1px solid {rgba('#ffffff', 0.10)}; outline: 0; }}"
        )


class _LabeledLineEdit(QWidget):
    """Two-row form field — top label + bottom input + helper-text caption."""

    def __init__(self, label: str, caption: str = "",
                 placeholder: str = "", parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0); v.setSpacing(4)
        self._lbl = _FieldLabel(label, self)
        self._inp = _DarkLineEdit(self)
        if placeholder:
            self._inp.setPlaceholderText(placeholder)
        self._cap = _SubFieldLabel(caption, self) if caption else None
        v.addWidget(self._lbl)
        v.addWidget(self._inp)
        if self._cap is not None:
            v.addWidget(self._cap)

    def text(self) -> str:
        return self._inp.text()

    def set_text(self, val: str) -> None:
        self._inp.setText(val)


class _LabeledComboBox(QWidget):
    def __init__(self, label: str, options: list, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0); v.setSpacing(4)
        self._lbl = _FieldLabel(label, self)
        self._cmb = _DarkComboBox(self)
        self._cmb.addItems(options)
        v.addWidget(self._lbl)
        v.addWidget(self._cmb)

    def current_text(self) -> str:
        return self._cmb.currentText()

    def set_current_text(self, txt: str) -> None:
        idx = self._cmb.findText(txt, Qt.MatchFlag.MatchFixedString)
        if idx >= 0:
            self._cmb.setCurrentIndex(idx)
        elif txt:
            # Unknown value — prepend so the user's choice is preserved
            self._cmb.insertItem(0, txt)
            self._cmb.setCurrentIndex(0)


class _BrowseField(QWidget):
    """Path field with inline Browse button. Used for the 4 file-path
    inputs (Music / Recordings / Logs / Exports) + the backup destination."""

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0); v.setSpacing(4)
        self._lbl = _FieldLabel(label, self)
        v.addWidget(self._lbl)

        row = QFrame(self)
        row.setStyleSheet("QFrame { background: transparent; }")
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0); h.setSpacing(8)
        self._inp = _DarkLineEdit(row)
        self._btn = QPushButton("Browse", row)
        self._btn.setFixedHeight(34)
        self._btn.setFixedWidth(80)
        self._btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._btn.setFont(inter(11, QFont.Weight.Medium))
        self._btn.setStyleSheet(
            f"QPushButton {{ background: {BG_ELEVATED}; color: {TEXT_PRI}; "
            f"border: 1px solid {rgba('#ffffff', 0.10)}; "
            f"border-radius: 6px; }}"
            f"QPushButton:hover {{ "
            f"border: 1px solid {rgba(CYAN, 0.50)}; }}"
        )
        h.addWidget(self._inp, stretch=1)
        h.addWidget(self._btn)
        v.addWidget(row)

        self._btn.clicked.connect(self._on_browse)

    def text(self) -> str:
        return self._inp.text()

    def set_text(self, val: str) -> None:
        self._inp.setText(val)

    def _on_browse(self) -> None:
        start = self._inp.text() or str(Path.home())
        path = QFileDialog.getExistingDirectory(
            self, "Select folder", start)
        if path:
            # Normalize to native separators with trailing slash
            norm = str(Path(path)).rstrip("/\\") + "\\"
            self._inp.setText(norm)


# ── Toggle switch ──────────────────────────────────────────────────────────


class _ToggleSwitch(QFrame):
    """44×24 pill toggle. Color-customisable for the per-row tint
    (green = lifestyle, purple = AUTO mode, cyan = updates, etc.)."""

    toggled = pyqtSignal(bool)

    def __init__(self, on_color: str = GREEN, parent=None):
        super().__init__(parent)
        self.setFixedSize(44, 24)
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
        # Track
        if self._on:
            bg = QColor(self._on_color)
        else:
            bg = QColor(BG_ELEVATED)
        p.setBrush(QBrush(bg))
        p.setPen(QPen(QColor(rgba('#ffffff', 0.06)), 1))
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), h / 2, h / 2)
        # Knob
        knob_d = h - 6
        knob_x = (w - 3 - knob_d) if self._on else 3
        p.setBrush(QColor("#ffffff"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(knob_x, 3, knob_d, knob_d))


class _ToggleRow(QWidget):
    """One row in the Startup & Behaviour card — toggle on the left, label
    on the right. The label color stays muted; on-state tint lives on the
    toggle pill itself."""

    def __init__(self, label: str, on_color: str = GREEN, parent=None):
        super().__init__(parent)
        self.setFixedHeight(36)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0); h.setSpacing(12)
        self._toggle = _ToggleSwitch(on_color=on_color, parent=self)
        h.addWidget(self._toggle, alignment=Qt.AlignmentFlag.AlignVCenter)
        lbl = QLabel(label, self)
        lbl.setFont(inter(12, QFont.Weight.Medium))
        lbl.setStyleSheet(
            f"color: {TEXT_PRI}; background: transparent; border: none;")
        h.addWidget(lbl, stretch=1,
                    alignment=Qt.AlignmentFlag.AlignVCenter)

    def is_on(self) -> bool:
        return self._toggle.is_on()

    def set_on(self, on: bool) -> None:
        self._toggle.set_on(on)


# ── Buttons ────────────────────────────────────────────────────────────────


class _PrimarySaveButton(QPushButton):
    """Large amber save button — main CTA of each column."""

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setFixedHeight(46)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFont(inter(13, QFont.Weight.Bold, letter_spacing=0.8))
        self.setStyleSheet(
            f"QPushButton {{ background: qlineargradient("
            f"x1:0,y1:0,x2:0,y2:1, stop:0 {AMBER_LIGHT}, stop:1 {AMBER}); "
            f"color: #2a1a02; border: none; border-radius: 8px; }}"
            f"QPushButton:hover {{ background: qlineargradient("
            f"x1:0,y1:0,x2:0,y2:1, stop:0 #fcd34d, stop:1 {AMBER_LIGHT}); }}"
        )


class _SecondaryButton(QPushButton):
    """Smaller flat button — Backup Now / Restore Backup."""

    def __init__(self, text: str, accent: str = TEAL, parent=None):
        super().__init__(text, parent)
        self.setFixedHeight(36)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFont(inter(11, QFont.Weight.Bold))
        self.setStyleSheet(
            f"QPushButton {{ background: {rgba(accent, 0.18)}; "
            f"color: {accent}; "
            f"border: 1px solid {rgba(accent, 0.40)}; "
            f"border-radius: 7px; padding: 0 18px; }}"
            f"QPushButton:hover {{ background: {rgba(accent, 0.28)}; }}"
        )


# ════════════════════════════════════════════════════════════════════════════
# Status bar
# ════════════════════════════════════════════════════════════════════════════


class _StatusPill(QFrame):
    def __init__(self, text: str, color: str, parent=None):
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
        lbl = QLabel(text, self)
        lbl.setFont(inter(9, QFont.Weight.Bold))
        lbl.setStyleSheet(
            f"color: {color}; background: transparent; border: none;")
        h.addWidget(dot)
        h.addWidget(lbl)
        self.adjustSize()


class _StatusBar(QFrame):
    studio_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(WINDOW_W, STATUS_H)
        self.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border-top: 1px solid {rgba('#ffffff', 0.06)}; }}"
        )
        x = 12
        for txt, col in (("AUTO MODE", PURPLE),
                          ("Settings",  AMBER),
                          ("All OK",    GREEN)):
            p = _StatusPill(txt, col, self)
            p.move(x, (STATUS_H - p.height()) // 2)
            x += p.width() + 8

        # Right side — version stamp + mini Open Studio
        ver = QLabel("General Settings  ·  RadioAI Studio v1.0.0", self)
        ver.setFont(inter(9))
        ver.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; border: none;")
        ver.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        ver.setFixedSize(360, STATUS_H)
        ver.move(WINDOW_W - 24 - 360 - 130, 0)

        osb = QPushButton("▶  Open Studio", self)
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


# ════════════════════════════════════════════════════════════════════════════
# Public screen
# ════════════════════════════════════════════════════════════════════════════


class SettingsGeneral(QWidget):
    """General Settings screen — first sub-page of the Settings hierarchy.
    See module docstring for the full DB-key map and layout breakdown."""

    breadcrumb_clicked = pyqtSignal(str)
    studio_clicked     = pyqtSignal()
    # Fired after any successful save so MainWindow can broadcast a
    # station-branding refresh to every other mounted screen (header
    # labels cache Settings().station_display at construction time;
    # this signal is how they learn the cached value is stale).
    settings_saved     = pyqtSignal()

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self._db = db
        self.setFixedSize(WINDOW_W, WINDOW_H)
        self.setStyleSheet(f"QWidget {{ background: {BG_BASE}; }}")

        self._build_header()
        self._build_left_column()
        self._build_right_column()
        self._build_status_bar()

        # Initial load
        self._load_settings()

        # Live clock
        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._tick_clock)
        self._clock_timer.start()
        self._tick_clock()

        log.info("SettingsGeneral ready (Figma 68:2)")

    # ── Header ────────────────────────────────────────────────────────

    def _build_header(self) -> None:
        h = QFrame(self)
        h.setGeometry(0, 0, WINDOW_W, HEADER_H)
        h.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border-bottom: 1px solid {rgba('#ffffff', 0.06)}; }}"
        )

        _HeaderLogo(h).move(14, 16)
        lbl = QLabel("RadioAI", h)
        lbl.setGeometry(64, 14, 120, 18)
        lbl.setFont(inter(15, QFont.Weight.Bold))
        lbl.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        sub = QLabel("STUDIO PRO", h)
        sub.setGeometry(64, 34, 120, 12)
        sub.setFont(inter(8, QFont.Weight.Bold, letter_spacing=1.2))
        sub.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

        # Breadcrumbs: Control Panel · Settings · [General Settings]
        cp = _BreadcrumbLink("Control Panel", h)
        cp.setGeometry(176, 22, 100, 22)
        cp.clicked.connect(
            lambda: self.breadcrumb_clicked.emit("control_panel"))

        sep1 = QLabel("|", h); sep1.setGeometry(272, 22, 8, 22)
        sep1.setFont(inter(11))
        sep1.setStyleSheet(f"color: {TEXT_DIM}; background: transparent;")

        st = _BreadcrumbLink("Settings", h)
        st.setGeometry(284, 22, 60, 22)
        # Settings hub page doesn't exist yet — same target as the active
        # crumb (no-op). When the Settings hub lands, this routes there.
        st.clicked.connect(
            lambda: self.breadcrumb_clicked.emit("settings"))

        sep2 = QLabel("|", h); sep2.setGeometry(346, 22, 8, 22)
        sep2.setFont(inter(11))
        sep2.setStyleSheet(f"color: {TEXT_DIM}; background: transparent;")

        pill = _BreadcrumbPill("General Settings", h)
        pill.move(358, 20)

        # Title + subtitle
        title = QLabel("General Settings", h)
        title.setGeometry(516, 12, 360, 24)
        title.setFont(inter(20, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        sub2 = QLabel(
            "Station identity, library paths, startup & backup preferences",
            h)
        sub2.setGeometry(516, 38, 460, 14)
        sub2.setFont(inter(10))
        sub2.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

        # Clock + station
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
        self._station_lbl.setGeometry(1108, 40, 110, 14)
        self._station_lbl.setFont(inter(9, QFont.Weight.Medium))
        self._station_lbl.setStyleSheet(
            f"color: {GREEN}; background: transparent;")

        osb = _HeaderOpenStudio(h)
        osb.move(1222, 16)
        osb.clicked.connect(self.studio_clicked.emit)

    # ── Body scaffolding ──────────────────────────────────────────────
    #
    # Each column is a vertical scroll area. Cards flow top-to-bottom
    # inside; the column's Save button is the final item so the operator
    # always reaches it by scrolling (no more clipped-below-the-fold).

    @staticmethod
    def _build_column_scroll(parent, x, y, w, h) -> tuple:
        """Returns (scroll_area, content_widget, vbox_layout). Caller
        adds widgets to the vbox; scroll handles overflow."""
        scroll = QScrollArea(parent)
        scroll.setGeometry(x, y, w, h)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setStyleSheet(
            f"QScrollArea {{ background: transparent; border: none; }}"
            f"QScrollBar:vertical {{ background: {BG_DARK}; width: 8px; "
            f"margin: 0; }}"
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
        scroll, content, v = self._build_column_scroll(
            self, 0, BODY_Y0, COL_W, BODY_H)
        self._left_scroll = scroll

        # STATION IDENTITY card
        self._card_identity = _SectionCard("Station Identity", AMBER, content)
        self._fld_name = _LabeledLineEdit(
            "Station Name",
            caption="Full name shown in software, logs and reports")
        self._fld_city = _LabeledLineEdit(
            "Station City", caption="City of broadcast")
        self._fld_region = _LabeledLineEdit(
            "Station Region", caption="Region/State")
        self._fld_freq = _LabeledLineEdit(
            "Broadcast Frequency", caption="Your FM frequency")
        self._fld_slogan = _LabeledLineEdit(
            "Station Slogan", caption="Used in RDS and exports")
        self._fld_email = _LabeledLineEdit(
            "Contact Email", caption="For system notifications")
        for w in (self._fld_name, self._fld_city, self._fld_region,
                  self._fld_freq, self._fld_slogan, self._fld_email):
            self._card_identity.add_row(w)
        self._card_identity.setFixedHeight(36 + 6 * 76 + 16)
        v.addWidget(self._card_identity)

        # FILE PATHS card
        self._card_paths = _SectionCard("File Paths", CYAN, content)
        self._fld_path_music    = _BrowseField("Music Library Root")
        self._fld_path_recordings = _BrowseField("Recordings Folder")
        self._fld_path_logs     = _BrowseField("Log Files Folder")
        self._fld_path_exports  = _BrowseField("Exports Folder")
        for w in (self._fld_path_music, self._fld_path_recordings,
                  self._fld_path_logs, self._fld_path_exports):
            self._card_paths.add_row(w)
        self._card_paths.setFixedHeight(36 + 4 * 66 + 16)
        v.addWidget(self._card_paths)

        # Save Station Settings button (last item — always reachable
        # by scrolling, no longer clipped below the 900px fold).
        self._btn_save_station = _PrimarySaveButton(
            "✓  Save Station Settings", content)
        self._btn_save_station.clicked.connect(self._on_save_station)
        v.addWidget(self._btn_save_station)
        v.addStretch()

    # ── Right column ──────────────────────────────────────────────────

    def _build_right_column(self) -> None:
        scroll, content, v = self._build_column_scroll(
            self, COL_W + COL_GAP, BODY_Y0, COL_W, BODY_H)
        self._right_scroll = scroll

        # STARTUP & BEHAVIOUR card
        self._card_startup = _SectionCard(
            "Startup & Behaviour", PURPLE, content)
        self._tg_win_startup    = _ToggleRow(
            "Start RadioAI on Windows startup", GREEN)
        self._tg_autoload       = _ToggleRow(
            "Auto-load last session on open", GREEN)
        self._tg_auto_mode      = _ToggleRow(
            "Start in AUTO MODE automatically", PURPLE)
        self._tg_splash         = _ToggleRow(
            "Show splash screen on launch", GREEN)
        self._tg_minimize_tray  = _ToggleRow(
            "Minimize to system tray on close", GREEN)
        self._tg_check_updates  = _ToggleRow(
            "Check for updates automatically", CYAN)
        self._tg_send_stats     = _ToggleRow(
            "Send anonymous usage statistics", GREEN)
        for w in (self._tg_win_startup, self._tg_autoload,
                  self._tg_auto_mode, self._tg_splash,
                  self._tg_minimize_tray, self._tg_check_updates,
                  self._tg_send_stats):
            self._card_startup.add_row(w)
        self._card_startup.setFixedHeight(36 + 7 * 40 + 16)
        v.addWidget(self._card_startup)

        # DATE & TIME FORMAT card
        self._card_datetime = _SectionCard(
            "Date & Time Format", AMBER, content)
        self._cmb_date_fmt = _LabeledComboBox("Date Format", DATE_FORMATS)
        self._cmb_time_fmt = _LabeledComboBox("Time Format", TIME_FORMATS)
        self._cmb_tz       = _LabeledComboBox("Timezone", TIMEZONES)
        self._cmb_lang     = _LabeledComboBox("Language", LANGUAGES)
        for w in (self._cmb_date_fmt, self._cmb_time_fmt,
                  self._cmb_tz, self._cmb_lang):
            self._card_datetime.add_row(w)
        self._card_datetime.setFixedHeight(36 + 4 * 58 + 16)
        v.addWidget(self._card_datetime)

        # BACKUP card
        self._card_backup = _SectionCard("Backup", TEAL, content)
        self._cmb_backup_interval = _LabeledComboBox(
            "Auto-backup interval", BACKUP_INTERVALS)
        self._fld_backup_path = _BrowseField("Backup destination")
        btn_row = QFrame()
        btn_row.setStyleSheet("QFrame { background: transparent; }")
        bh = QHBoxLayout(btn_row)
        bh.setContentsMargins(0, 4, 0, 0); bh.setSpacing(10)
        self._btn_backup_now = _SecondaryButton("⬛  Backup Now", TEAL)
        self._btn_restore    = _SecondaryButton("↺  Restore Backup",
                                                  TEXT_SEC)
        self._btn_backup_now.clicked.connect(self._on_backup_now)
        self._btn_restore.clicked.connect(self._on_restore_backup)
        bh.addWidget(self._btn_backup_now)
        bh.addWidget(self._btn_restore)
        bh.addStretch()
        for w in (self._cmb_backup_interval, self._fld_backup_path, btn_row):
            self._card_backup.add_row(w)
        self._card_backup.setFixedHeight(36 + 58 + 66 + 50 + 16)
        v.addWidget(self._card_backup)

        # Save All Preferences button (last item — same reachability
        # guarantee as the left column).
        self._btn_save_all = _PrimarySaveButton(
            "✓  Save All Preferences", content)
        self._btn_save_all.clicked.connect(self._on_save_all)
        v.addWidget(self._btn_save_all)
        v.addStretch()

    # ── Status bar ────────────────────────────────────────────────────

    def _build_status_bar(self) -> None:
        self._status_bar = _StatusBar(self)
        self._status_bar.move(0, WINDOW_H - STATUS_H)
        self._status_bar.studio_clicked.connect(self.studio_clicked.emit)

    # ── Clock tick ────────────────────────────────────────────────────

    def _tick_clock(self) -> None:
        self._clock_lbl.setText(datetime.now().strftime("%H:%M:%S"))

    # ── Settings IO ───────────────────────────────────────────────────

    def _settings(self) -> Settings:
        # Use the singleton; tests may pass their own thin shape, but
        # production wires it via Settings().load(db) at boot.
        return Settings()

    def _load_settings(self) -> None:
        s = self._settings()
        # STATION IDENTITY
        self._fld_name.set_text(s.get("station_name", "") or "")
        self._fld_city.set_text(s.get("station_city", "") or "")
        self._fld_region.set_text(s.get("station_region", "") or "")
        self._fld_freq.set_text(s.get("station_frequency", "") or "")
        self._fld_slogan.set_text(s.get("station_slogan", "") or "")
        self._fld_email.set_text(s.get("station_email", "") or "")

        # FILE PATHS
        self._fld_path_music.set_text(
            s.get("path_music", "C:\\RadioAI\\Music\\"))
        self._fld_path_recordings.set_text(
            s.get("path_recordings", "C:\\RadioAI\\Recordings\\"))
        self._fld_path_logs.set_text(
            s.get("path_logs", "C:\\RadioAI\\Logs\\"))
        self._fld_path_exports.set_text(
            s.get("path_exports", "C:\\RadioAI\\Exports\\"))

        # STARTUP & BEHAVIOUR
        self._tg_win_startup.set_on(
            s.get_bool("start_on_windows_startup", False))
        self._tg_autoload.set_on(
            s.get_bool("auto_load_last_session", True))
        self._tg_auto_mode.set_on(
            s.get_bool("start_in_auto_mode", True))
        self._tg_splash.set_on(
            s.get_bool("show_splash_screen", True))
        self._tg_minimize_tray.set_on(
            s.get_bool("minimize_to_tray", True))
        self._tg_check_updates.set_on(
            s.get_bool("check_updates", True))
        self._tg_send_stats.set_on(
            s.get_bool("send_usage_stats", False))

        # DATE & TIME FORMAT
        self._cmb_date_fmt.set_current_text(
            s.get("date_format", "DD/MM/YYYY"))
        # time_format stored as '24h' / '12h' shorthand historically — map
        # back to the longer label when possible.
        tf = (s.get("time_format") or "24h").lower()
        tf_map = {"24h": "24-hour (HH:MM:SS)",
                  "12h": "12-hour (HH:MM:SS AM/PM)"}
        self._cmb_time_fmt.set_current_text(
            tf_map.get(tf, s.get("time_format", "24-hour (HH:MM:SS)")))
        self._cmb_tz.set_current_text(
            s.get("timezone", "IST — Asia/Kolkata (UTC+5:30)"))
        self._cmb_lang.set_current_text(
            s.get("language", "English (India)"))

        # BACKUP
        self._cmb_backup_interval.set_current_text(
            s.get("backup_interval", "Every 24 hours"))
        self._fld_backup_path.set_text(
            s.get("path_backup", "C:\\RadioAI\\Backups\\"))

    def _save_left_column(self) -> None:
        """Save just the station-identity + file-paths fields. Returns the
        number of keys written so the toast can report it."""
        s = self._settings()
        s.set("station_name",      self._fld_name.text())
        s.set("station_city",      self._fld_city.text())
        s.set("station_region",    self._fld_region.text())
        s.set("station_frequency", self._fld_freq.text())
        s.set("station_slogan",    self._fld_slogan.text())
        s.set("station_email",     self._fld_email.text())
        s.set("path_music",        self._fld_path_music.text())
        s.set("path_recordings",   self._fld_path_recordings.text())
        s.set("path_logs",         self._fld_path_logs.text())
        s.set("path_exports",      self._fld_path_exports.text())
        # Refresh the header station label live
        try:
            self._station_lbl.setText(
                Settings().station_display or "")
        except Exception:
            pass

    def _save_right_column(self) -> None:
        s = self._settings()
        # STARTUP & BEHAVIOUR — bool → '1'/'0' so get_bool reads correctly
        s.set("start_on_windows_startup",
              "1" if self._tg_win_startup.is_on() else "0")
        s.set("auto_load_last_session",
              "1" if self._tg_autoload.is_on() else "0")
        s.set("start_in_auto_mode",
              "1" if self._tg_auto_mode.is_on() else "0")
        s.set("show_splash_screen",
              "1" if self._tg_splash.is_on() else "0")
        s.set("minimize_to_tray",
              "1" if self._tg_minimize_tray.is_on() else "0")
        s.set("check_updates",
              "1" if self._tg_check_updates.is_on() else "0")
        s.set("send_usage_stats",
              "1" if self._tg_send_stats.is_on() else "0")

        # DATE & TIME FORMAT
        s.set("date_format", self._cmb_date_fmt.current_text())
        # Reverse-map the time-format label back to the shorthand.
        tf = self._cmb_time_fmt.current_text().lower()
        if "24-hour" in tf:
            s.set("time_format", "24h")
        elif "12-hour" in tf:
            s.set("time_format", "12h")
        else:
            s.set("time_format", self._cmb_time_fmt.current_text())
        s.set("timezone", self._cmb_tz.current_text())
        s.set("language", self._cmb_lang.current_text())

        # BACKUP
        s.set("backup_interval",
              self._cmb_backup_interval.current_text())
        s.set("path_backup", self._fld_backup_path.text())

    def _on_save_station(self) -> None:
        try:
            self._save_left_column()
        except Exception as exc:
            QMessageBox.warning(
                self, "Save failed",
                f"Could not save station settings:\n{exc}")
            return
        self.settings_saved.emit()
        QMessageBox.information(
            self, "Saved",
            "Station identity + file paths saved.")

    def _on_save_all(self) -> None:
        try:
            self._save_left_column()
            self._save_right_column()
        except Exception as exc:
            QMessageBox.warning(
                self, "Save failed",
                f"Could not save preferences:\n{exc}")
            return
        self.settings_saved.emit()
        QMessageBox.information(
            self, "Saved",
            "All General Settings preferences saved.")

    def _on_backup_now(self) -> None:
        QMessageBox.information(
            self, "Backup Now",
            "Backup Now — coming in v1.1.\n\n"
            "Path is saved; manual filesystem copy works for now.")

    def _on_restore_backup(self) -> None:
        QMessageBox.information(
            self, "Restore Backup",
            "Restore Backup — coming in v1.1.\n\n"
            "Manual restore from the backup folder works for now.")

    # ── Public API ────────────────────────────────────────────────────

    def reload(self) -> None:
        """Re-read settings from DB into the form. Call from MainWindow
        when the screen is shown so any external change (e.g. operator
        edited via SQL or another panel) is reflected."""
        self._load_settings()
