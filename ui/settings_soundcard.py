"""
RadioAI Studio Pro — Soundcard Settings
Pixel-accurate match of Figma node 68:394 (file 7oN9K61g94wKx3nu44KKDF).

Maps Windows audio devices to RadioAI's 4 outputs + 1 input. All
selections persist to the existing audio_output_X / audio_vol_outputX /
audio_channel_outputX settings keys via Settings().set().

Layout (1440 × 900):
  Header        y=  0.. 72   Logo + breadcrumb + title + clock + Open Studio
  Section row   y= 72..120   AUDIO ROUTING CONFIGURATION + subtitle
  Channel cards y=120..720   5 horizontal cards (Output 1..4 + Input 1)
  Warning strip y=720..776   Restart-required notice + buttons row
  Status bar    y=864..900   AUTO MODE / N Channels / Devices pills + version

Public signals:
  breadcrumb_clicked(str) — header breadcrumb crumbs
  studio_clicked()        — header Open Studio button

v1 scope cuts (deferred to v1.1):
  - Test Tone / Monitor Channel / Test ALL: toast "Coming v1.1"
    (real tone-gen + temp WAV + cleanup is heavier; DB-save flow is
    the priority for v1)
  - Latency display: static placeholder per channel
  - "Connected & Active" status: green when a device is selected,
    gray placeholder otherwise (no live polling in v1)
  - Audio driver hot-reload: settings persist, AudioEngine re-init is
    v1.1 (the warning strip tells the operator a restart is required)
"""

from __future__ import annotations

import ctypes
import logging
from datetime import datetime
from typing import List, Optional, Tuple

from PyQt6.QtCore import Qt, QRectF, QTimer, pyqtSignal
from core import dialogs
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QLinearGradient, QFont, QCursor,
)
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QComboBox, QSlider,
    QHBoxLayout, QVBoxLayout, QMessageBox, QCheckBox,
)

from core.settings import Settings
from ui.widgets._tokens import (
    inter, mono, rgba,
    BG_BASE, BG_DARK, BG_PANEL, BG_ELEVATED,
    TEXT_PRI, TEXT_SEC, TEXT_MUTED, TEXT_DIM,
    CYAN, CYAN_LIGHT, PURPLE, PURPLE_LIGHT,
    GREEN, GREEN_LIGHT, AMBER, AMBER_LIGHT, RED, RED_LIGHT,
    PINK, PINK_LIGHT,
)

log = logging.getLogger("SettingsSoundcard")


# ════════════════════════════════════════════════════════════════════════════
# Geometry / constants
# ════════════════════════════════════════════════════════════════════════════

WINDOW_W = 1440
WINDOW_H = 900
HEADER_H = 72
STATUS_H = 36

CHANNEL_OPTIONS = ["Stereo", "Mono Left", "Mono Right", "Mono Mix"]
INPUT_CHANNEL_OPTIONS = ["Mono Input", "Stereo Input", "Left Input",
                          "Right Input"]

# Aircheck quality ladder — (kbps value, combo label). ≤48 kbps encodes
# MONO (the recorder passes -ac 1 to ffmpeg): low-rate stereo MP3 sounds
# far worse than mono at the same size, and mono is the compliance-logger
# norm. Default 32 kbps ≈ 14 MB/hour ≈ 15 GB per 90 days.
AIRCHECK_QUALITIES = [
    ("32",  "32 kbps (Mono)"),
    ("48",  "48 kbps (Mono)"),
    ("64",  "64 kbps"),
    ("96",  "96 kbps"),
    ("128", "128 kbps"),
    ("160", "160 kbps"),
    ("192", "192 kbps"),
]


# ════════════════════════════════════════════════════════════════════════════
# Device enumeration via BASS — best-effort, falls back to a stub list
# ════════════════════════════════════════════════════════════════════════════


def enumerate_audio_devices() -> List[Tuple[int, str, bool, bool]]:
    """Return [(device_index, name, is_enabled, is_input), ...] using
    BASS_GetDeviceInfo. Outputs come first; inputs follow. Falls back
    to a single 'Default' entry if BASS isn't loaded yet (during tests
    or before bass_init)."""
    devs: List[Tuple[int, str, bool, bool]] = []
    try:
        from pybass3.bass_module import BASS_GetDeviceInfo, BASS_DEVICEINFO
        i = 0
        while i < 32:
            info = BASS_DEVICEINFO()
            if not BASS_GetDeviceInfo(i, ctypes.byref(info)):
                break
            name = (info.name or b"").decode(errors="ignore")
            enabled = bool(info.flags & 0x1)
            # Skip the synthetic "No sound" device — never useful for routing.
            if name and name.lower() != "no sound":
                devs.append((i, name, enabled, False))
            i += 1
    except Exception as exc:
        log.warning(f"BASS device enum failed: {exc}")
    if not devs:
        devs.append((0, "Default device", True, False))
    return devs


# ════════════════════════════════════════════════════════════════════════════
# Header chrome — same pattern as SettingsGeneral / SettingsHub
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
    """Active breadcrumb crumb — accent-tinted pill. Color matches the
    Settings Hub card accent for this sub-page (cyan for Soundcards)."""

    def __init__(self, label: str, accent: str = CYAN, parent=None):
        super().__init__(parent)
        self._accent = accent
        self.setFixedSize(110, 32)
        self.setStyleSheet(
            f"QFrame {{ background: {rgba(accent, 0.18)}; "
            f"border: 1px solid {rgba(accent, 0.40)}; border-radius: 16px; }}"
        )
        h = QHBoxLayout(self)
        h.setContentsMargins(14, 0, 14, 0); h.setSpacing(0)
        lbl = QLabel(label, self)
        lbl.setFont(inter(11, QFont.Weight.Bold))
        lbl.setStyleSheet(
            f"color: {CYAN_LIGHT}; background: transparent; border: none;")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h.addWidget(lbl)


# ════════════════════════════════════════════════════════════════════════════
# Form primitives
# ════════════════════════════════════════════════════════════════════════════


class _MicroLabel(QLabel):
    """Tiny uppercase letter-spaced label — DEVICE / VOL / CHANNEL."""

    def __init__(self, text: str, color: str = TEXT_MUTED, parent=None):
        super().__init__(text.upper(), parent)
        self.setFont(inter(8, QFont.Weight.Bold, letter_spacing=1.2))
        self.setStyleSheet(
            f"color: {color}; background: transparent; border: none;")


class _DeviceCombo(QComboBox):
    """Dark dropdown styled to fit a channel card. Accent-color tinted
    on hover/focus."""

    def __init__(self, accent: str = CYAN, parent=None):
        super().__init__(parent)
        self.setFixedHeight(28)
        self.setFont(inter(11))
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setStyleSheet(
            f"QComboBox {{ background: {BG_DARK}; color: {TEXT_PRI}; "
            f"border: 1px solid {rgba(accent, 0.30)}; "
            f"border-radius: 5px; padding: 0 8px; }}"
            f"QComboBox:hover {{ "
            f"border: 1px solid {rgba(accent, 0.55)}; }}"
            f"QComboBox::drop-down {{ border: none; width: 20px; }}"
            f"QComboBox::down-arrow {{ image: none; }}"
            f"QComboBox QAbstractItemView {{ background: {BG_PANEL}; "
            f"color: {TEXT_PRI}; "
            f"selection-background-color: {rgba(accent, 0.25)}; "
            f"border: 1px solid {rgba('#ffffff', 0.10)}; outline: 0; }}"
        )


class _VolSlider(QSlider):
    """Horizontal 0-100 slider. Track filled in accent color up to the
    handle position; rest of the track is dark."""

    def __init__(self, accent: str = CYAN, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setRange(0, 100)
        self.setFixedHeight(8)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setStyleSheet(
            f"QSlider::groove:horizontal {{ background: {BG_DARK}; "
            f"height: 8px; border-radius: 4px; }}"
            f"QSlider::sub-page:horizontal {{ background: qlineargradient("
            f"x1:0,y1:0,x2:1,y2:0, stop:0 {accent}, stop:1 {accent}); "
            f"border-radius: 4px; }}"
            f"QSlider::add-page:horizontal {{ background: {BG_DARK}; "
            f"border-radius: 4px; }}"
            f"QSlider::handle:horizontal {{ background: white; "
            f"width: 14px; height: 14px; margin: -4px 0; "
            f"border-radius: 7px; }}"
        )


# ════════════════════════════════════════════════════════════════════════════
# Channel card — one per output / input
# ════════════════════════════════════════════════════════════════════════════


class _CriticalPill(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(72, 20)
        self.setStyleSheet(
            f"QFrame {{ background: {rgba(RED, 0.22)}; "
            f"border: 1px solid {rgba(RED, 0.45)}; border-radius: 10px; }}"
        )
        h = QHBoxLayout(self)
        h.setContentsMargins(8, 0, 8, 0); h.setSpacing(0)
        lbl = QLabel("CRITICAL", self)
        lbl.setFont(inter(8, QFont.Weight.Bold, letter_spacing=1.0))
        lbl.setStyleSheet(
            f"color: {RED_LIGHT}; background: transparent; border: none;")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h.addWidget(lbl)


class _ChannelCard(QFrame):
    """One channel card — output (4 variants) or input. Layout matches
    Figma 68:394 channel cell exactly: icon + title (+ optional CRITICAL),
    description, DEVICE combo, volume slider with label, latency, channel
    combo, action button, connection status."""

    test_clicked = pyqtSignal(str)  # channel_key

    def __init__(self, channel_key: str, title: str, subtitle: str,
                 icon: str, accent: str, accent_light: str,
                 is_critical: bool, is_input: bool, latency_ms: int,
                 parent=None):
        super().__init__(parent)
        self._channel_key = channel_key
        self._accent = accent
        self._accent_light = accent_light
        self._icon = icon
        self._is_input = is_input
        self.setFixedSize(268, 366)
        self.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; "
            f"border-radius: 10px; }}"
        )

        # Icon (top-left)
        ic = QLabel(icon, self)
        ic.setGeometry(14, 16, 28, 28)
        ic.setFont(inter(20, QFont.Weight.Bold))
        ic.setStyleSheet(
            f"color: {accent_light}; background: transparent; border: none;")

        # CRITICAL pill (Output 1 only)
        if is_critical:
            pill = _CriticalPill(self)
            pill.move(self.width() - pill.width() - 14, 18)

        # Title
        t = QLabel(title, self)
        t.setGeometry(14, 52, self.width() - 28, 20)
        t.setFont(inter(13, QFont.Weight.Bold))
        t.setStyleSheet(
            f"color: {TEXT_PRI}; background: transparent; border: none;")

        # Subtitle (wraps to 2 lines)
        sub = QLabel(subtitle, self)
        sub.setGeometry(14, 74, self.width() - 28, 28)
        sub.setFont(inter(9))
        sub.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; border: none;")
        sub.setWordWrap(True)

        # DEVICE label + combo
        dev_lbl = _MicroLabel("DEVICE", parent=self)
        dev_lbl.setGeometry(14, 110, self.width() - 28, 12)
        self._cmb_device = _DeviceCombo(accent, self)
        self._cmb_device.setGeometry(14, 124, self.width() - 28, 28)

        # VOL label + slider + percent
        self._vol_lbl = QLabel("VOL: 100%", self)
        self._vol_lbl.setGeometry(14, 162, self.width() - 28, 12)
        self._vol_lbl.setFont(inter(9, QFont.Weight.Bold,
                                     letter_spacing=0.6))
        self._vol_lbl.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent; border: none;")
        self._sl_vol = _VolSlider(accent, self)
        self._sl_vol.setGeometry(14, 180, self.width() - 28, 8)
        self._sl_vol.valueChanged.connect(self._on_vol_changed)

        # Latency (read-only)
        lat_lbl = QLabel(f"Latency: {latency_ms}ms", self)
        lat_lbl.setGeometry(14, 196, self.width() - 28, 12)
        lat_lbl.setFont(inter(9))
        lat_lbl.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; border: none;")

        # CHANNEL label + combo
        chn_lbl = _MicroLabel("CHANNEL", parent=self)
        chn_lbl.setGeometry(14, 218, self.width() - 28, 12)
        self._cmb_channel = _DeviceCombo(accent, self)
        self._cmb_channel.setGeometry(14, 232, self.width() - 28, 28)
        chn_opts = INPUT_CHANNEL_OPTIONS if is_input else CHANNEL_OPTIONS
        self._cmb_channel.addItems(chn_opts)

        # Test Tone / Monitor button
        btn_text = ("▶  Monitor Channel" if is_input
                    else "▶  Test Tone Channel")
        self._btn_test = QPushButton(btn_text, self)
        self._btn_test.setGeometry(14, 272, self.width() - 28, 32)
        self._btn_test.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._btn_test.setFont(inter(11, QFont.Weight.Bold))
        self._btn_test.setStyleSheet(
            f"QPushButton {{ background: qlineargradient("
            f"x1:0,y1:0,x2:0,y2:1, stop:0 {accent_light}, stop:1 {accent}); "
            f"color: #04141a; border: none; border-radius: 6px; }}"
            f"QPushButton:hover {{ background: qlineargradient("
            f"x1:0,y1:0,x2:0,y2:1, stop:0 #ffffff, stop:1 {accent_light}); }}"
        )
        self._btn_test.clicked.connect(
            lambda _=False: self.test_clicked.emit(self._channel_key))

        # Connection status
        self._status_lbl = QLabel("● Connected & Active", self)
        self._status_lbl.setGeometry(14, 316, self.width() - 28, 14)
        self._status_lbl.setFont(inter(9, QFont.Weight.Bold))
        self._status_lbl.setStyleSheet(
            f"color: {GREEN_LIGHT}; background: transparent; border: none;")

    # paintEvent draws the top accent stripe
    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(QRectF(0, 0, self.width(), 4), QColor(self._accent))
        p.end()

    # ── Public API ────────────────────────────────────────────────────

    def populate_devices(self, devices: List[Tuple[int, str, bool, bool]]) -> None:
        self._cmb_device.clear()
        self._cmb_device.addItem("(none)", userData="")
        for idx, name, _enabled, _is_input in devices:
            self._cmb_device.addItem(name, userData=str(idx))

    def set_selected_device(self, value: str) -> None:
        """`value` is the userData (the device index as a string). Falls
        back to (none) when not found."""
        if not value:
            self._cmb_device.setCurrentIndex(0)
            self._refresh_status()
            return
        for i in range(self._cmb_device.count()):
            if self._cmb_device.itemData(i) == str(value):
                self._cmb_device.setCurrentIndex(i)
                break
        else:
            self._cmb_device.setCurrentIndex(0)
        self._refresh_status()

    def selected_device(self) -> str:
        return self._cmb_device.currentData() or ""

    def set_volume(self, vol: int) -> None:
        v = max(0, min(100, int(vol)))
        self._sl_vol.setValue(v)
        self._on_vol_changed(v)

    def volume(self) -> int:
        return self._sl_vol.value()

    def set_channel_mode(self, mode: str) -> None:
        idx = self._cmb_channel.findText(mode,
                                          Qt.MatchFlag.MatchFixedString)
        if idx >= 0:
            self._cmb_channel.setCurrentIndex(idx)
        elif mode:
            self._cmb_channel.insertItem(0, mode)
            self._cmb_channel.setCurrentIndex(0)

    def channel_mode(self) -> str:
        return self._cmb_channel.currentText()

    # ── Internal ──────────────────────────────────────────────────────

    def _on_vol_changed(self, v: int) -> None:
        self._vol_lbl.setText(f"VOL: {v}%")

    def _refresh_status(self) -> None:
        if self.selected_device():
            self._status_lbl.setText("● Connected & Active")
            self._status_lbl.setStyleSheet(
                f"color: {GREEN_LIGHT}; background: transparent; "
                f"border: none;")
        else:
            self._status_lbl.setText("● Not assigned")
            self._status_lbl.setStyleSheet(
                f"color: {TEXT_MUTED}; background: transparent; "
                f"border: none;")


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


# Channel spec: (key, title, subtitle, icon, accent, accent_light,
# is_critical, is_input, latency_ms, db_device_key, db_vol_key,
# db_channel_key)
CHANNEL_SPECS = [
    ("output_1", "Output 1 — Main On-Air",
     "Goes to transmitter / broadcast chain. This is what listeners hear.",
     "🎙", RED,    RED_LIGHT,    True,  False, 0,
     "audio_output_1", "audio_vol_output1", "audio_channel_output1"),
    ("output_2", "Output 2 — Studio Monitor",
     "DJ headphones / studio speakers for monitoring the on-air feed.",
     "🔊", CYAN,   CYAN_LIGHT,   False, False, 10,
     "audio_output_2", "audio_vol_output2", "audio_channel_output2"),
    ("output_3", "Output 3 — Cue / Preview",
     "Preview next track in headphones before it airs. Private to DJ.",
     "🎧", PURPLE, PURPLE_LIGHT, False, False, 0,
     "audio_output_3", "audio_vol_output3", "audio_channel_output3"),
    ("output_4", "Output 4 — Instant Jingles",
     "Separate output for live jingle pads. Independent from main mix.",
     "⚡", AMBER,  AMBER_LIGHT,  False, False, 5,
     "audio_output_4", "audio_vol_output4", "audio_channel_output4"),
    ("input_1",  "Input 1 — Microphone",
     "DJ microphone input. Used for voice tracking and live announcements.",
     "🎤", PINK,   PINK_LIGHT,   False, True,  0,
     "audio_input_1",  "audio_vol_input1",  "audio_channel_input1"),
]


class SettingsSoundcard(QWidget):
    """Soundcard Settings screen (Figma 68:394).
    Builds 5 channel cards and persists every selection to the
    settings table via Settings().set()."""

    breadcrumb_clicked = pyqtSignal(str)
    studio_clicked     = pyqtSignal()
    # Fired after Save Routing so MainWindow can warn-toast the operator
    # that a restart is needed.
    settings_saved     = pyqtSignal()

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self._db = db
        self.setFixedSize(WINDOW_W, WINDOW_H)
        self.setStyleSheet(f"QWidget {{ background: {BG_BASE}; }}")

        # Enumerate audio devices once (cheap, no need to refresh
        # mid-session — operator does that with a restart anyway).
        self._devices = enumerate_audio_devices()

        self._build_header()
        self._build_section_title()
        self._build_channel_cards()
        self._build_warning_strip()
        self._build_aircheck_section()
        self._build_status_bar()

        self._load_settings()

        # Live clock
        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._tick_clock)
        self._clock_timer.start()
        self._tick_clock()

        log.info(
            f"SettingsSoundcard ready (Figma 68:394) — "
            f"{len(self._devices)} audio devices enumerated")

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

        # Breadcrumb: Control Panel · Settings · [Soundcards]
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

        pill = _BreadcrumbPill("Soundcards", CYAN, h)
        pill.move(358, 20)

        # Title + subtitle
        title = QLabel("Soundcards", h)
        title.setGeometry(484, 12, 220, 24)
        title.setFont(inter(20, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        sub = QLabel(
            "Audio output and input routing — assign devices to each channel",
            h)
        sub.setGeometry(484, 38, 500, 14)
        sub.setFont(inter(10))
        sub.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

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
        self._station_lbl.setObjectName("hdr_station_lbl")
        self._station_lbl.setGeometry(1108, 40, 110, 14)
        self._station_lbl.setFont(inter(9, QFont.Weight.Medium))
        self._station_lbl.setStyleSheet(
            f"color: {GREEN}; background: transparent;")

        osb = _HeaderOpenStudio(h)
        osb.move(1222, 16)
        osb.clicked.connect(self.studio_clicked.emit)

    # ── Section title ─────────────────────────────────────────────────

    def _build_section_title(self) -> None:
        cont = QFrame(self)
        cont.setGeometry(0, HEADER_H, WINDOW_W, 48)
        cont.setStyleSheet("QFrame { background: transparent; }")

        title = QLabel("AUDIO ROUTING CONFIGURATION", cont)
        title.setGeometry(16, 8, 600, 18)
        title.setFont(inter(11, QFont.Weight.Bold, letter_spacing=1.6))
        title.setStyleSheet(
            f"color: {CYAN_LIGHT}; background: transparent; border: none;")

        sub = QLabel(
            "Assign Windows audio devices to each RadioAI output channel. "
            "Changes require restart.",
            cont)
        sub.setGeometry(16, 28, 800, 14)
        sub.setFont(inter(10))
        sub.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; border: none;")

    # ── Channel cards ─────────────────────────────────────────────────

    def _build_channel_cards(self) -> None:
        CARD_W = 268
        CARD_H = 366
        GAP = 12
        total_w = 5 * CARD_W + 4 * GAP
        start_x = (WINDOW_W - total_w) // 2
        y = HEADER_H + 48 + 8

        self._cards: dict = {}
        for i, spec in enumerate(CHANNEL_SPECS):
            (key, title, sub, icon, accent, accent_light,
             critical, is_input, latency,
             _dev_key, _vol_key, _chn_key) = spec
            c = _ChannelCard(key, title, sub, icon, accent, accent_light,
                              critical, is_input, latency, parent=self)
            c.move(start_x + i * (CARD_W + GAP), y)
            c.populate_devices(self._devices)
            c.test_clicked.connect(self._on_test_clicked)
            self._cards[key] = c

    # ── Warning strip + action buttons ────────────────────────────────

    def _build_warning_strip(self) -> None:
        y = HEADER_H + 48 + 8 + 366 + 16
        strip = QFrame(self)
        strip.setGeometry(16, y, WINDOW_W - 32, 64)
        strip.setStyleSheet(
            f"QFrame {{ background: {rgba(AMBER, 0.08)}; "
            f"border: 1px solid {rgba(AMBER, 0.30)}; "
            f"border-radius: 8px; }}"
        )

        ic = QLabel("⚠", strip)
        ic.setGeometry(16, 18, 28, 28)
        ic.setFont(inter(18, QFont.Weight.Bold))
        ic.setStyleSheet(
            f"color: {AMBER_LIGHT}; background: transparent; border: none;")

        main = QLabel(
            "Audio driver changes and volume settings require RadioAI "
            "restart to take full effect.",
            strip)
        main.setGeometry(56, 8, strip.width() - 360, 22)
        main.setFont(inter(12, QFont.Weight.Bold))
        main.setStyleSheet(
            f"color: {AMBER_LIGHT}; background: transparent; border: none;")

        sub = QLabel(
            "Always use 'Test Tone' to verify output before going on air.",
            strip)
        sub.setGeometry(56, 30, strip.width() - 360, 18)
        sub.setFont(inter(10))
        sub.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent; border: none;")

        # Test ALL button
        self._btn_test_all = QPushButton("Test ALL", strip)
        self._btn_test_all.setFixedSize(120, 36)
        self._btn_test_all.move(strip.width() - 290, 14)
        self._btn_test_all.setCursor(
            QCursor(Qt.CursorShape.PointingHandCursor))
        self._btn_test_all.setFont(inter(11, QFont.Weight.Bold))
        self._btn_test_all.setStyleSheet(
            f"QPushButton {{ background: {BG_ELEVATED}; color: {CYAN_LIGHT}; "
            f"border: 1px solid {rgba(CYAN, 0.40)}; "
            f"border-radius: 6px; }}"
            f"QPushButton:hover {{ "
            f"border: 1px solid {rgba(CYAN, 0.70)}; }}"
        )
        self._btn_test_all.clicked.connect(self._on_test_all)

        # Save Routing button
        self._btn_save = QPushButton("✓  Save Routing", strip)
        self._btn_save.setFixedSize(150, 36)
        self._btn_save.move(strip.width() - 160, 14)
        self._btn_save.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._btn_save.setFont(inter(11, QFont.Weight.Bold))
        self._btn_save.setStyleSheet(
            f"QPushButton {{ background: qlineargradient("
            f"x1:0,y1:0,x2:0,y2:1, stop:0 {CYAN_LIGHT}, stop:1 {CYAN}); "
            f"color: #04141a; border: none; border-radius: 6px; }}"
            f"QPushButton:hover {{ background: qlineargradient("
            f"x1:0,y1:0,x2:0,y2:1, stop:0 #67e8f9, stop:1 {CYAN_LIGHT}); }}"
        )
        self._btn_save.clicked.connect(self._on_save_clicked)

    # ── Aircheck Recorder section ─────────────────────────────────────

    def _build_aircheck_section(self) -> None:
        """Hourly broadcast logger controls. The recorder smart-follows
        the playout device's WASAPI loopback; everything here persists
        via the same Save Routing button (settings_saved → MainWindow
        re-resolves the recorder live, no restart needed)."""
        y = HEADER_H + 48 + 8 + 366 + 16 + 64 + 18   # below warning strip

        title = QLabel("AIR-CHECK RECORDER", self)
        title.setGeometry(16, y, 400, 18)
        title.setFont(inter(11, QFont.Weight.Bold, letter_spacing=1.6))
        title.setStyleSheet(
            f"color: {RED_LIGHT}; background: transparent; border: none;")

        sub = QLabel(
            "Hourly broadcast logging — records the on-air output "
            "(loopback) into one MP3 per clock hour.",
            self)
        sub.setGeometry(16, y + 20, 900, 14)
        sub.setFont(inter(10))
        sub.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; border: none;")

        panel = QFrame(self)
        panel.setGeometry(16, y + 42, WINDOW_W - 32, 96)
        panel.setStyleSheet(
            f"QFrame {{ background: {rgba(RED, 0.05)}; "
            f"border: 1px solid {rgba(RED, 0.25)}; "
            f"border-radius: 8px; }}"
        )

        # Enable toggle
        self._chk_aircheck = QCheckBox("Recording Enabled", panel)
        self._chk_aircheck.setGeometry(16, 34, 180, 28)
        self._chk_aircheck.setCursor(
            QCursor(Qt.CursorShape.PointingHandCursor))
        self._chk_aircheck.setFont(inter(11, QFont.Weight.Bold))
        self._chk_aircheck.setStyleSheet(
            f"QCheckBox {{ color: {TEXT_PRI}; background: transparent; "
            f"border: none; spacing: 8px; }}"
            f"QCheckBox::indicator {{ width: 16px; height: 16px; "
            f"border: 1px solid {rgba(RED, 0.5)}; border-radius: 4px; "
            f"background: {BG_ELEVATED}; }}"
            f"QCheckBox::indicator:checked {{ background: {RED}; }}"
        )

        # Device combo — Auto (follow output) + explicit loopbacks
        dev_lbl = _MicroLabel("RECORD DEVICE", parent=panel)
        dev_lbl.setGeometry(220, 14, 300, 12)
        self._cmb_aircheck_dev = _DeviceCombo(accent=RED, parent=panel)
        self._cmb_aircheck_dev.setGeometry(220, 30, 340, 28)
        self._cmb_aircheck_dev.addItem("Auto — follow output device")
        for name in self._loopback_names():
            self._cmb_aircheck_dev.addItem(name)

        # Quality combo
        q_lbl = _MicroLabel("QUALITY", parent=panel)
        q_lbl.setGeometry(584, 14, 120, 12)
        self._cmb_aircheck_quality = _DeviceCombo(accent=RED, parent=panel)
        self._cmb_aircheck_quality.setGeometry(584, 30, 130, 28)
        for _kbps, label in AIRCHECK_QUALITIES:
            self._cmb_aircheck_quality.addItem(label)

        # Retention combo
        r_lbl = _MicroLabel("KEEP RECORDINGS", parent=panel)
        r_lbl.setGeometry(738, 14, 140, 12)
        self._cmb_aircheck_keep = _DeviceCombo(accent=RED, parent=panel)
        self._cmb_aircheck_keep.setGeometry(738, 30, 130, 28)
        for days in ("30", "60", "90", "180"):
            self._cmb_aircheck_keep.addItem(f"{days} days")

        # Folder note — the folder itself is picked in Settings → General
        folder = (Settings().get("path_recordings", "") or "").strip()
        self._lbl_aircheck_folder = QLabel(panel)
        self._lbl_aircheck_folder.setGeometry(
            892, 14, panel.width() - 908, 48)
        self._lbl_aircheck_folder.setFont(inter(9))
        self._lbl_aircheck_folder.setWordWrap(True)
        self._lbl_aircheck_folder.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; border: none;")
        self._lbl_aircheck_folder.setText(
            f"Saving to:  {folder or '(default app folder)'}\n"
            f"Change folder in Settings → General → Storage Locations")

        hint = QLabel(
            "≈14 MB/hour at 32 kbps · ≈58 MB/hour at 128 kbps · files "
            "older than the keep window are deleted automatically",
            panel)
        hint.setGeometry(220, 64, 700, 14)
        hint.setFont(inter(9))
        hint.setStyleSheet(
            f"color: {TEXT_DIM}; background: transparent; border: none;")

    def _loopback_names(self) -> List[str]:
        try:
            from core.aircheck_recorder import enumerate_loopback_devices
            return [name for _idx, name in enumerate_loopback_devices()]
        except Exception as exc:
            log.warning(f"loopback enumeration failed: {exc}")
            return []

    # ── Status bar ────────────────────────────────────────────────────

    def _build_status_bar(self) -> None:
        sb = QFrame(self)
        sb.setGeometry(0, WINDOW_H - STATUS_H, WINDOW_W, STATUS_H)
        sb.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border-top: 1px solid {rgba('#ffffff', 0.06)}; }}"
        )
        x = 12
        active_count = sum(
            1 for k in self._cards if self._cards[k].selected_device())
        for txt, col in (("AUTO MODE", PURPLE),
                          (f"{active_count} Channels Active", CYAN),
                          (f"{len(self._devices)} Devices Found", GREEN)):
            p = _StatusPill(txt, col, sb)
            p.move(x, (STATUS_H - p.height()) // 2)
            x += p.width() + 8

        ver = QLabel("Soundcards  ·  RadioAI Studio v1.0.0", sb)
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

    def _load_settings(self) -> None:
        s = Settings()
        for spec in CHANNEL_SPECS:
            (key, *_rest, dev_k, vol_k, chn_k) = spec
            card = self._cards[key]
            card.set_selected_device(s.get(dev_k, ""))
            card.set_volume(s.get_int(vol_k, 100))
            card.set_channel_mode(s.get(chn_k,
                                          "Mono Input" if key == "input_1"
                                          else "Stereo"))
        # Aircheck recorder block
        self._chk_aircheck.setChecked(s.get_bool("aircheck_enabled", True))
        override = s.get("aircheck_device_override", "") or ""
        idx = self._cmb_aircheck_dev.findText(override) if override else 0
        self._cmb_aircheck_dev.setCurrentIndex(max(0, idx))
        kbps = str(s.get_int("aircheck_bitrate", 32))
        qi = next((i for i, (v, _l) in enumerate(AIRCHECK_QUALITIES)
                   if v == kbps), 0)
        self._cmb_aircheck_quality.setCurrentIndex(qi)
        days = str(s.get_int("aircheck_retention_days", 90))
        ki = self._cmb_aircheck_keep.findText(f"{days} days")
        self._cmb_aircheck_keep.setCurrentIndex(ki if ki >= 0 else 2)

    def _save_all(self) -> None:
        s = Settings()
        for spec in CHANNEL_SPECS:
            (key, *_rest, dev_k, vol_k, chn_k) = spec
            card = self._cards[key]
            s.set(dev_k, card.selected_device())
            s.set(vol_k, str(card.volume()))
            s.set(chn_k, card.channel_mode())
        # Aircheck recorder block — index 0 of the device combo is
        # "Auto — follow output device" which persists as "" (empty
        # override = smart-follow).
        s.set("aircheck_enabled",
              "1" if self._chk_aircheck.isChecked() else "0")
        dev = ("" if self._cmb_aircheck_dev.currentIndex() <= 0
               else self._cmb_aircheck_dev.currentText())
        s.set("aircheck_device_override", dev)
        s.set("aircheck_bitrate",
              AIRCHECK_QUALITIES[
                  self._cmb_aircheck_quality.currentIndex()][0])
        s.set("aircheck_retention_days",
              self._cmb_aircheck_keep.currentText().split()[0])

    # ── Handlers ──────────────────────────────────────────────────────

    def _on_save_clicked(self) -> None:
        try:
            self._save_all()
        except Exception as exc:
            dialogs.warning(
                self, "Save failed",
                f"Could not save soundcard routing:\n{exc}")
            return
        self.settings_saved.emit()
        dialogs.info(
            self, "Saved",
            "Routing saved.\n\nAudio driver changes take effect after "
            "RadioAI restart. Use Test Tone to verify output before "
            "going on air.")

    def _on_test_clicked(self, channel_key: str) -> None:
        is_input = channel_key.startswith("input")
        label = "Monitor Channel" if is_input else "Test Tone Channel"
        dialogs.info(
            self, label,
            f"{label} — coming in v1.1.\n\nChannel: {channel_key}\n\n"
            "Real tone playback wires through AudioEngine and is part "
            "of the next session's roadmap. Routing save works today.")

    def _on_test_all(self) -> None:
        dialogs.info(
            self, "Test ALL",
            "Test ALL — coming in v1.1.\n\nWill cycle a 1kHz test tone "
            "through every assigned output sequentially.")

    # ── Public API ────────────────────────────────────────────────────

    def reload(self) -> None:
        """Re-read settings from DB. Use from MainWindow on screen show."""
        self._load_settings()
