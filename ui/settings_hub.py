"""
RadioAI Studio Pro — Settings Hub
Pixel-accurate match of Figma node 426:3 (file 7oN9K61g94wKx3nu44KKDF,
page "Settings Hub").

Settings landing/hub page. Operator lands here when clicking "Settings"
from anywhere in the app; this page presents the three sub-section
entry points (General / Soundcard / Studio) as colored option cards.

Layout (1440 × 900):
  Header        y=  0.. 72   Logo + breadcrumb + title + clock + Open Studio
  Body          y= 72..864   3 cards (416 × 460 each, 32px gap, centered)
  Status bar    y=864..900   AUTO MODE · Settings · All OK pills + version

Public signals:
  screen_requested(str) — "settings_general" / "settings_soundcard" /
                          "settings_studio" / "control_panel"
  studio_clicked()      — header Open Studio button

v1 scope:
  General Settings card → routes to existing SettingsGeneral screen.
  Soundcard + Studio cards → coming-v1.1 toast (sub-screens deferred).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from PyQt6.QtCore import Qt, QRectF, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QLinearGradient, QFont, QCursor,
)
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QHBoxLayout, QVBoxLayout,
)

from core.settings import Settings
from ui.widgets._tokens import (
    inter, mono, rgba,
    BG_BASE, BG_DARK, BG_PANEL,
    TEXT_PRI, TEXT_SEC, TEXT_MUTED, TEXT_DIM,
    CYAN, CYAN_LIGHT, PURPLE, PURPLE_LIGHT,
    GREEN, GREEN_LIGHT, AMBER, AMBER_LIGHT,
)

log = logging.getLogger("SettingsHub")

WINDOW_W = 1440
WINDOW_H = 900
HEADER_H = 72
STATUS_H = 36


# ════════════════════════════════════════════════════════════════════════════
# Header chrome (shared visual contract with SettingsGeneral)
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
    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self.setFixedSize(110, 32)
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
# Option card — one tile per Settings sub-section
# ════════════════════════════════════════════════════════════════════════════


class _OptionCard(QFrame):
    """One Settings sub-section tile. Custom paint for the colored top
    accent + the icon-circle. Title / tagline / body are QLabels. The
    Open → CTA at the bottom emits the screen-key for routing.

    Click anywhere on the card (or the CTA) fires .clicked(screen_key)."""

    clicked = pyqtSignal(str)

    def __init__(self, title: str, tagline: str, body: str, icon: str,
                 accent: str, accent_light: str, screen_key: str,
                 parent=None):
        super().__init__(parent)
        self._accent = accent
        self._accent_light = accent_light
        self._icon = icon
        self._screen_key = screen_key
        self.setFixedSize(416, 460)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; "
            f"border-radius: 12px; }}"
        )

        # Title — centered, large bold
        t = QLabel(title, self)
        t.setGeometry(24, 168, self.width() - 48, 32)
        t.setFont(inter(20, QFont.Weight.Bold))
        t.setStyleSheet(
            f"color: {TEXT_PRI}; background: transparent; border: none;")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Tagline — uppercase, accent-tinted, letter-spaced
        tg = QLabel(tagline, self)
        tg.setGeometry(16, 208, self.width() - 32, 16)
        tg.setFont(inter(9, QFont.Weight.Bold, letter_spacing=1.2))
        tg.setStyleSheet(
            f"color: {accent_light}; background: transparent; border: none;")
        tg.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Body description — multi-line, muted gray, center-aligned
        b = QLabel(body, self)
        b.setGeometry(32, 248, self.width() - 64, 112)
        b.setFont(inter(11))
        b.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent; border: none;")
        b.setAlignment(Qt.AlignmentFlag.AlignHCenter
                       | Qt.AlignmentFlag.AlignTop)
        b.setWordWrap(True)

        # Open → CTA
        cta = QPushButton("Open  →", self)
        cta.setGeometry((self.width() - 180) // 2, self.height() - 76,
                         180, 44)
        cta.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        cta.setFont(inter(12, QFont.Weight.Bold, letter_spacing=0.6))
        cta.setStyleSheet(
            f"QPushButton {{ background: {rgba(accent, 0.18)}; "
            f"color: {accent_light}; "
            f"border: 1px solid {rgba(accent, 0.40)}; "
            f"border-radius: 8px; }}"
            f"QPushButton:hover {{ background: {rgba(accent, 0.28)}; }}"
        )
        cta.clicked.connect(lambda _=False: self.clicked.emit(self._screen_key))

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._screen_key)
        super().mousePressEvent(e)

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Top accent stripe (4px)
        p.fillRect(QRectF(0, 0, self.width(), 4), QColor(self._accent))
        # Icon circle (96 at top, centered)
        cx = (self.width() - 96) / 2
        cy = 48
        p.setBrush(QColor(rgba(self._accent, 0.10)))
        p.setPen(QPen(QColor(rgba(self._accent, 0.30)), 1))
        p.drawEllipse(QRectF(cx, cy, 96, 96))
        # Icon glyph
        p.setPen(QColor(self._accent_light))
        p.setFont(inter(48, QFont.Weight.Bold))
        p.drawText(QRectF(0, 60, self.width(), 72),
                   Qt.AlignmentFlag.AlignCenter, self._icon)
        p.end()


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


class SettingsHub(QWidget):
    """Settings landing page (Figma 426:3). Three option cards route
    to: General Settings (built), Soundcard Settings (v1.1 toast),
    Studio Settings (v1.1 toast). Operator reaches this screen from
    every "Settings" entry point in the app."""

    screen_requested = pyqtSignal(str)
    studio_clicked   = pyqtSignal()

    def __init__(self, db=None, parent=None):
        super().__init__(parent)
        self._db = db
        self.setFixedSize(WINDOW_W, WINDOW_H)
        self.setStyleSheet(f"QWidget {{ background: {BG_BASE}; }}")

        self._build_header()
        self._build_cards()
        self._build_status_bar()

        # Live clock
        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._tick_clock)
        self._clock_timer.start()
        self._tick_clock()

        log.info("SettingsHub ready (Figma 426:3)")

    # ── Header ────────────────────────────────────────────────────────

    def _build_header(self) -> None:
        h = QFrame(self)
        h.setGeometry(0, 0, WINDOW_W, HEADER_H)
        h.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border-bottom: 1px solid {rgba('#ffffff', 0.06)}; }} "
            f"QLabel {{ border: none; }}"
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

        # Breadcrumb: Control Panel · [Settings] (active)
        cp = _BreadcrumbLink("Control Panel", h)
        cp.setGeometry(176, 22, 100, 22)
        cp.clicked.connect(
            lambda: self.screen_requested.emit("control_panel"))
        sep = QLabel("|", h); sep.setGeometry(272, 22, 8, 22)
        sep.setFont(inter(11))
        sep.setStyleSheet(f"color: {TEXT_DIM}; background: transparent;")
        pill = _BreadcrumbPill("Settings", h)
        pill.move(284, 20)

        # Title + subtitle
        title = QLabel("Settings", h)
        title.setGeometry(416, 12, 220, 24)
        title.setFont(inter(20, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        sub = QLabel(
            "Configure your station, audio, and broadcast preferences",
            h)
        sub.setGeometry(416, 38, 500, 14)
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

    # ── Body ──────────────────────────────────────────────────────────

    def _build_cards(self) -> None:
        CARD_W = 416; CARD_H = 460; GAP = 32
        total_w = 3 * CARD_W + 2 * GAP
        start_x = (WINDOW_W - total_w) // 2

        specs = [
            ("General Settings",
             "STATION · PATHS · STARTUP · DATE · BACKUP",
             "Station identity, broadcast frequency, contact email, "
             "file paths, startup behaviour, date and time format, "
             "language, and automatic backup.",
             "⚙", AMBER, AMBER_LIGHT, "settings_general"),
            ("Soundcard Settings",
             "DEVICES · CHANNELS · LEVELS · ROUTING",
             "Pick input/output audio devices, calibrate VU meters, "
             "configure on-air vs monitor signal paths, set sample "
             "rate, bit depth, and buffer size.",
             "♫", CYAN, CYAN_LIGHT, "settings_soundcard"),
            ("Studio Settings",
             "AUTO · MIX · SEPARATION · AI ENGINE",
             "Tune the broadcast engine — AUTO mode rules, same-song "
             "/ artist separation gaps, mix and crossfade defaults, "
             "AI scheduler tuning, fallback policy.",
             "▶", PURPLE, PURPLE_LIGHT, "settings_studio"),
        ]

        self._cards = []
        for i, (title, tag, body, icon, accent, light, key) in enumerate(specs):
            c = _OptionCard(title, tag, body, icon, accent, light, key,
                             parent=self)
            c.move(start_x + i * (CARD_W + GAP), 200)
            c.clicked.connect(self._on_card_clicked)
            self._cards.append(c)

    def _on_card_clicked(self, screen_key: str) -> None:
        log.info(f"SettingsHub card → {screen_key}")
        self.screen_requested.emit(screen_key)

    # ── Status bar ────────────────────────────────────────────────────

    def _build_status_bar(self) -> None:
        sb = QFrame(self)
        sb.setGeometry(0, WINDOW_H - STATUS_H, WINDOW_W, STATUS_H)
        sb.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border-top: 1px solid {rgba('#ffffff', 0.06)}; }} "
            f"QLabel {{ border: none; }}"
        )

        x = 12
        for txt, col in (("AUTO MODE", PURPLE),
                          ("Settings",  AMBER),
                          ("All OK",    GREEN)):
            p = _StatusPill(txt, col, sb)
            p.move(x, (STATUS_H - p.height()) // 2)
            x += p.width() + 8

        ver = QLabel("Settings  ·  RadioAI Studio v1.0.0", sb)
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

    # ── Clock tick ────────────────────────────────────────────────────

    def _tick_clock(self) -> None:
        self._clock_lbl.setText(datetime.now().strftime("%H:%M:%S"))
