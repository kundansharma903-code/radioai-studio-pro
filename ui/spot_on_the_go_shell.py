"""
RadioAI Studio Pro — Spot on the Go (shell)
Pixel-accurate match of Figma node 462:3 (file 7oN9K61g94wKx3nu44KKDF,
page "Spot on the Go").

Landing shell for the Spot on the Go module — one of two AI Magic
submodules. Surfaces 4 step cards that route to dedicated sub-screens
(all "coming soon" today; the operator will brief each in a later
session):

  1. Create Schedule  — Build the day's programming (RJ, show, links,
                        time slots).
  2. Assign           — Upload audio, set sharp HH:MM, pick High / Low
                        priority per link.
  3. Generate Report  — Daily PDF play log + optional AI transcription
                        summary per link.
  4. Assign API Key   — Wire Gemini / Claude / ChatGPT for transcription.

Layout (1440 × 900):
  Header        y=  0.. 72   Logo + 3-step breadcrumb + title + clock + Open Studio
  Hero block    y= 88..240   "✦ SPOT ON THE GO" + tagline + 3 status pills
  Cards         y=260..640   4 step cards (312×380, 24px gap, centered)
  Priority box  y=668..798   3-tier priority ladder (Spots & Commercials >
                              Spot on the Go > Songs)
  Status bar    y=864..900   AUTO MODE · ✦ SPOT ON THE GO · Live Data + version

Public signals:
  screen_requested(str) — "create_schedule" / "assign" /
                          "generate_report" / "assign_api_key" /
                          "ai_magic" / "control_panel"
  studio_clicked()      — header Open Studio button
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from PyQt6.QtCore import Qt, QRectF, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QLinearGradient, QRadialGradient,
    QFont, QCursor,
)
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QHBoxLayout,
)

from core.settings import Settings
from ui.widgets._tokens import (
    inter, mono, rgba,
    BG_BASE, BG_PANEL,
    TEXT_PRI, TEXT_SEC, TEXT_MUTED, TEXT_DIM,
    CYAN, CYAN_LIGHT, PURPLE, PURPLE_LIGHT,
    GREEN, GREEN_LIGHT, AMBER, AMBER_LIGHT,
)

log = logging.getLogger("SpotOnTheGoShell")

WINDOW_W = 1440
WINDOW_H = 900
HEADER_H = 72
STATUS_H = 36


# ════════════════════════════════════════════════════════════════════════════
# Header chrome (duplicated from AI Magic Hub — same library_chrome.py
# extraction TODO applies)
# ════════════════════════════════════════════════════════════════════════════


class _HeaderLogo(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(40, 40)

    def paintEvent(self, _e):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        g = QLinearGradient(0, 0, self.width(), self.height())
        g.setColorAt(0.0, QColor(PURPLE))
        g.setColorAt(1.0, QColor(CYAN))
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
    """Active crumb pill — cyan accent for Spot on the Go (mirrors the
    Figma cyan accent for this screen)."""

    def __init__(self, label: str = "✦ Spot on the Go", parent=None):
        super().__init__(parent)
        self.setFixedSize(152, 32)
        self.setStyleSheet(
            f"QFrame {{ background: {rgba(CYAN, 0.18)}; "
            f"border: 1px solid {rgba(CYAN, 0.40)}; border-radius: 16px; }}"
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
# Hero status pill
# ════════════════════════════════════════════════════════════════════════════


class _HeroStatusPill(QFrame):
    def __init__(self, label: str, color: str, light: str, parent=None):
        super().__init__(parent)
        self.setFixedHeight(26)
        self.setStyleSheet(
            f"QFrame {{ background: {rgba(color, 0.15)}; "
            f"border: 1px solid {rgba(color, 0.40)}; border-radius: 13px; }}"
        )
        h = QHBoxLayout(self)
        h.setContentsMargins(12, 0, 14, 0); h.setSpacing(8)
        dot = QLabel("●", self)
        dot.setFont(inter(8))
        dot.setStyleSheet(
            f"color: {color}; background: transparent; border: none;")
        lbl = QLabel(label, self)
        lbl.setFont(inter(9, QFont.Weight.Bold, letter_spacing=1.2))
        lbl.setStyleSheet(
            f"color: {light}; background: transparent; border: none;")
        h.addWidget(dot)
        h.addWidget(lbl)
        self.adjustSize()


# ════════════════════════════════════════════════════════════════════════════
# Step card — one of the four numbered tiles
# ════════════════════════════════════════════════════════════════════════════


class _StepCard(QFrame):
    """One Spot on the Go step tile (312×380). Custom paint for the
    top accent stripe + gradient icon halo. Title / subtitle / status
    pill / CTA all QLabels & QPushButtons. The whole card is
    clickable; emits clicked(screen_key) for the host to route."""

    clicked = pyqtSignal(str)

    CARD_W = 312
    CARD_H = 380

    def __init__(self, step_num: int, title: str, subtitle: str,
                 glyph: str, accent: str, accent_light: str,
                 screen_key: str, status_label: str = "● COMING SOON",
                 parent=None):
        super().__init__(parent)
        self._accent = accent
        self._accent_light = accent_light
        self._glyph = glyph
        self._screen_key = screen_key
        self._step_num = step_num
        self.setFixedSize(self.CARD_W, self.CARD_H)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border: 1px solid {rgba('#ffffff', 0.08)}; "
            f"border-radius: 16px; }}"
        )

        # Step number tag (top-right)
        step_lbl = QLabel(f"STEP {step_num}", self)
        step_lbl.setGeometry(self.CARD_W - 84, 20, 64, 14)
        step_lbl.setFont(
            inter(8, QFont.Weight.Bold, letter_spacing=1.4))
        step_lbl.setStyleSheet(
            f"color: {accent_light}; background: transparent; "
            f"border: none;")
        step_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)

        # Title — centered
        t = QLabel(title, self)
        t.setGeometry(18, 160, self.CARD_W - 36, 30)
        t.setFont(inter(20, QFont.Weight.Black, letter_spacing=-0.3))
        t.setStyleSheet(
            f"color: {TEXT_PRI}; background: transparent; border: none;")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Subtitle — multi-line, muted, centered
        s = QLabel(subtitle, self)
        s.setGeometry(22, 200, self.CARD_W - 44, 80)
        s.setFont(inter(11, QFont.Weight.Medium))
        s.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent; border: none;")
        s.setWordWrap(True)
        s.setAlignment(Qt.AlignmentFlag.AlignHCenter
                        | Qt.AlignmentFlag.AlignTop)

        # Status pill (bottom-left)
        sp = QFrame(self)
        sp.setGeometry(18, self.CARD_H - 50, 116, 22)
        sp.setStyleSheet(
            f"QFrame {{ background: {rgba(accent, 0.15)}; "
            f"border: 1px solid {rgba(accent, 0.40)}; "
            f"border-radius: 11px; }}"
        )
        sp_layout = QHBoxLayout(sp)
        sp_layout.setContentsMargins(10, 0, 10, 0); sp_layout.setSpacing(0)
        sp_lbl = QLabel(status_label, sp)
        sp_lbl.setFont(inter(8, QFont.Weight.Bold, letter_spacing=1.0))
        sp_lbl.setStyleSheet(
            f"color: {accent_light}; background: transparent; "
            f"border: none;")
        sp_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sp_layout.addWidget(sp_lbl)

        # CTA "Open →" gradient button (bottom-right)
        cta = QPushButton("Open  →", self)
        cta.setGeometry(self.CARD_W - 18 - 132, self.CARD_H - 54, 132, 32)
        cta.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        cta.setFont(inter(11, QFont.Weight.Bold, letter_spacing=0.4))
        cta.setStyleSheet(
            f"QPushButton {{ background: qlineargradient("
            f"x1:0,y1:0,x2:1,y2:0, stop:0 {accent}, stop:1 {accent_light}); "
            f"color: {BG_BASE}; border: none; border-radius: 8px; "
            f"padding: 0 6px; }}"
            f"QPushButton:hover {{ background: qlineargradient("
            f"x1:0,y1:0,x2:1,y2:0, stop:0 {accent_light}, stop:1 {accent_light}); }}"
        )
        cta.clicked.connect(
            lambda _=False: self.clicked.emit(self._screen_key))

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._screen_key)
        super().mousePressEvent(e)

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Top accent stripe gradient
        sg = QLinearGradient(0, 0, self.width(), 0)
        sg.setColorAt(0.0, QColor(self._accent))
        sg.setColorAt(1.0, QColor(self._accent_light))
        p.fillRect(QRectF(0, 0, self.width(), 4), QBrush(sg))

        # Left edge tint
        edge = QColor(self._accent); edge.setAlphaF(0.35)
        p.fillRect(QRectF(0, 0, 1, self.height()), edge)

        # Icon halo (radial) + circle
        ICON = 72
        ix = (self.CARD_W - ICON) / 2
        iy = 56
        halo_grad = QRadialGradient(ix + ICON / 2, iy + ICON / 2,
                                      ICON / 2 + 12)
        c0 = QColor(self._accent); c0.setAlphaF(0.45)
        c1 = QColor(self._accent); c1.setAlphaF(0.0)
        halo_grad.setColorAt(0.0, c0); halo_grad.setColorAt(1.0, c1)
        p.setBrush(QBrush(halo_grad)); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(ix - 12, iy - 12, ICON + 24, ICON + 24))

        # Icon circle (diag gradient)
        icon_grad = QLinearGradient(ix, iy, ix + ICON, iy + ICON)
        icon_grad.setColorAt(0.0, QColor(self._accent))
        icon_grad.setColorAt(1.0, QColor(self._accent_light))
        p.setBrush(QBrush(icon_grad)); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(ix, iy, ICON, ICON))

        # Glyph
        p.setPen(QColor(255, 255, 255, 245))
        p.setFont(inter(34, QFont.Weight.Black))
        p.drawText(QRectF(ix, iy, ICON, ICON),
                   Qt.AlignmentFlag.AlignCenter, self._glyph)

        p.end()


# ════════════════════════════════════════════════════════════════════════════
# Premium backdrop (cyan + purple radial vignettes)
# ════════════════════════════════════════════════════════════════════════════


class _PremiumBackdrop(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setStyleSheet("QWidget { background: transparent; }")

    def paintEvent(self, _e):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Cyan glow top-left
        g1 = QRadialGradient(180, 410, 350)
        c1a = QColor(CYAN); c1a.setAlphaF(0.10)
        c1b = QColor(CYAN); c1b.setAlphaF(0.0)
        g1.setColorAt(0.0, c1a); g1.setColorAt(1.0, c1b)
        p.setBrush(QBrush(g1)); p.setPen(Qt.PenStyle.NoPen)
        p.drawRect(QRectF(-200, 60, 760, 700))
        # Purple glow center-right
        g2 = QRadialGradient(1250, 540, 380)
        c2a = QColor(PURPLE); c2a.setAlphaF(0.08)
        c2b = QColor(PURPLE); c2b.setAlphaF(0.0)
        g2.setColorAt(0.0, c2a); g2.setColorAt(1.0, c2b)
        p.setBrush(QBrush(g2)); p.setPen(Qt.PenStyle.NoPen)
        p.drawRect(QRectF(900, 280, 700, 700))
        p.end()


# ════════════════════════════════════════════════════════════════════════════
# Priority ladder card (bottom strip explaining airplay priority order)
# ════════════════════════════════════════════════════════════════════════════


class _PriorityLadder(QFrame):
    """Bottom-of-screen strip showing the 3-tier priority order. Pinned
    in the design because the operator wanted the priority semantics
    visible at the shell level — sets expectations before Configure."""

    TIERS = (
        ("1", "Spots & Commercials", AMBER, AMBER_LIGHT,
         "Always wins. If a paid spot is on air at the same minute, "
         "let it finish first."),
        ("2", "Spot on the Go",      CYAN,  CYAN_LIGHT,
         "Plays at sharp HH:MM. Songs fade out over 10s to make room. "
         "One-time only — file is consumed after play."),
        ("3", "Songs (Library)",     PURPLE, PURPLE_LIGHT,
         "Music is the baseline. Any higher-priority drop interrupts "
         "the deck gracefully."),
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(1320, 130)
        self.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; "
            f"border-radius: 14px; }}"
        )

        cap = QLabel(
            "PRIORITY LADDER  ·  HOW SPOT ON THE GO BEHAVES ON AIR", self)
        cap.setGeometry(24, 14, 600, 14)
        cap.setFont(inter(10, QFont.Weight.Bold, letter_spacing=1.4))
        cap.setStyleSheet(
            f"color: {CYAN_LIGHT}; background: transparent; border: none;")

        # 3 tier rows
        for i, (rank, label, accent, accent_light, desc) in enumerate(
                self.TIERS):
            y = 40 + i * 28

            # Rank badge (circle)
            badge = QFrame(self)
            badge.setGeometry(24, y, 22, 22)
            badge.setStyleSheet(
                f"QFrame {{ background: {rgba(accent, 0.18)}; "
                f"border: 1px solid {rgba(accent, 0.50)}; "
                f"border-radius: 11px; }}"
            )
            bh = QHBoxLayout(badge)
            bh.setContentsMargins(0, 0, 0, 0); bh.setSpacing(0)
            num = QLabel(rank, badge)
            num.setFont(inter(11, QFont.Weight.Bold))
            num.setStyleSheet(
                f"color: {accent}; background: transparent; border: none;")
            num.setAlignment(Qt.AlignmentFlag.AlignCenter)
            bh.addWidget(num)

            # Label
            tier_lbl = QLabel(label, self)
            tier_lbl.setGeometry(56, y, 240, 22)
            tier_lbl.setFont(inter(12, QFont.Weight.Bold,
                                     letter_spacing=-0.2))
            tier_lbl.setStyleSheet(
                f"color: {TEXT_PRI}; background: transparent; "
                f"border: none;")

            # Description
            desc_lbl = QLabel(desc, self)
            desc_lbl.setGeometry(296, y, 1000, 22)
            desc_lbl.setFont(inter(11, QFont.Weight.Medium))
            desc_lbl.setStyleSheet(
                f"color: {TEXT_SEC}; background: transparent; "
                f"border: none;")

    def paintEvent(self, e):
        super().paintEvent(e)
        # Left accent stripe
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(QRectF(0, 0, 4, self.height()), QColor(CYAN))
        p.end()


# ════════════════════════════════════════════════════════════════════════════
# Status pill (footer)
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


class SpotOnTheGoShell(QWidget):
    """Spot on the Go landing page (Figma 462:3). Four step cards
    route to dedicated sub-screens that get briefed + designed in
    follow-up sessions. Today every card toasts 'coming soon' via
    the host."""

    screen_requested = pyqtSignal(str)
    studio_clicked   = pyqtSignal()

    def __init__(self, db=None, parent=None):
        super().__init__(parent)
        self._db = db
        self.setFixedSize(WINDOW_W, WINDOW_H)
        self.setStyleSheet(f"QWidget {{ background: {BG_BASE}; }}")

        self._backdrop = _PremiumBackdrop(self)
        self._backdrop.setGeometry(0, 0, WINDOW_W, WINDOW_H)

        self._build_header()
        self._build_hero()
        self._build_cards()
        self._build_priority_ladder()
        self._build_status_bar()

        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._tick_clock)
        self._clock_timer.start()
        self._tick_clock()

        log.info("SpotOnTheGoShell ready (Figma 462:3)")

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

        # 3-step breadcrumb: Control Panel | AI Magic | [Spot on the Go]
        cp = _BreadcrumbLink("Control Panel", h)
        cp.setGeometry(176, 22, 100, 22)
        cp.clicked.connect(
            lambda: self.screen_requested.emit("control_panel"))
        sep1 = QLabel("|", h); sep1.setGeometry(272, 22, 8, 22)
        sep1.setFont(inter(11))
        sep1.setStyleSheet(f"color: {TEXT_DIM}; background: transparent;")
        am = _BreadcrumbLink("AI Magic", h)
        am.setGeometry(284, 22, 80, 22)
        am.clicked.connect(
            lambda: self.screen_requested.emit("ai_magic"))
        sep2 = QLabel("|", h); sep2.setGeometry(360, 22, 8, 22)
        sep2.setFont(inter(11))
        sep2.setStyleSheet(f"color: {TEXT_DIM}; background: transparent;")
        pill = _BreadcrumbPill("✦ Spot on the Go", h)
        pill.move(372, 20)

        # Title + subtitle
        title = QLabel("Spot on the Go", h)
        title.setGeometry(548, 12, 240, 24)
        title.setFont(inter(20, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        sub = QLabel(
            "One-shot scheduled audio drops with priority over music",
            h)
        sub.setGeometry(548, 38, 520, 14)
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

    # ── Hero block ────────────────────────────────────────────────────

    def _build_hero(self) -> None:
        sigil = QLabel("✦", self)
        sigil.setGeometry(60, 100, 40, 56)
        sigil.setFont(inter(42, QFont.Weight.Bold))
        sigil.setStyleSheet(
            f"color: {CYAN_LIGHT}; background: transparent; border: none;")
        title = QLabel("SPOT ON THE GO", self)
        title.setGeometry(110, 100, 900, 56)
        title.setFont(inter(42, QFont.Weight.Black, letter_spacing=-0.5))
        title.setStyleSheet(
            f"color: {TEXT_PRI}; background: transparent; border: none;")

        sub = QLabel(
            "Upload a file. Pick the sharp time. Software fades the "
            "music and plays it once. RJ links · news · sponsor reads "
            "— handled in four steps below.", self)
        sub.setGeometry(60, 162, 1100, 18)
        sub.setFont(inter(13, QFont.Weight.Medium))
        sub.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent; border: none;")

        # 3 status pills (live counters today are zero — placeholders
        # until Create / Assign sub-screens land)
        x = 60
        for label, col, light in (
                ("MODULE  ·  STANDBY", CYAN,   CYAN_LIGHT),
                ("0 SCHEDULED TODAY",  PURPLE, PURPLE_LIGHT),
                ("0 LINKS QUEUED",     GREEN,  GREEN_LIGHT),
        ):
            p = _HeroStatusPill(label, col, light, self)
            p.move(x, 200)
            x += p.width() + 10

        # Right-side counter
        right_top = QLabel("4 sections", self)
        right_top.setGeometry(1240, 200, 180, 14)
        right_top.setFont(inter(10, QFont.Weight.Medium))
        right_top.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent; border: none;")
        right_top.setAlignment(Qt.AlignmentFlag.AlignRight)

        right_sub = QLabel("set up in order", self)
        right_sub.setGeometry(1240, 216, 180, 14)
        right_sub.setFont(inter(9))
        right_sub.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; border: none;")
        right_sub.setAlignment(Qt.AlignmentFlag.AlignRight)

    # ── Cards ─────────────────────────────────────────────────────────

    CARD_SPECS = (
        # step, title, subtitle, glyph, accent, accent_light, screen_key
        (1, "Create Schedule",
         "Build the day's programming — RJ name, show, links, and "
         "time slots.",
         "✚", CYAN,   CYAN_LIGHT,   "create_schedule"),
        (2, "Assign",
         "Upload audio, set the sharp time, pick High or Low priority "
         "for each link.",
         "↗", PURPLE, PURPLE_LIGHT, "assign"),
        (3, "Generate Report",
         "Daily PDF play log. Optional AI transcription summarises "
         "every link's content.",
         "▤", GREEN,  GREEN_LIGHT,  "generate_report"),
        (4, "Assign API Key",
         "Wire your Gemini, Claude or ChatGPT key to power AI "
         "transcription of links.",
         "⚿", AMBER,  AMBER_LIGHT,  "assign_api_key"),
    )

    def _build_cards(self) -> None:
        # 4 × 312w × 380h, 24px gap, centered.
        # (1440 - 4*312 - 3*24) / 2 = 60
        CARD_W = _StepCard.CARD_W
        CARD_H = _StepCard.CARD_H
        GAP = 24
        start_x = (WINDOW_W - 4 * CARD_W - 3 * GAP) // 2
        ys = 260

        self._cards = []
        for i, (step, title, sub, glyph, accent, light, key) in enumerate(
                self.CARD_SPECS):
            c = _StepCard(step, title, sub, glyph, accent, light,
                           key, parent=self)
            c.move(start_x + i * (CARD_W + GAP), ys)
            c.clicked.connect(self._on_card_clicked)
            self._cards.append(c)

    def _on_card_clicked(self, screen_key: str) -> None:
        log.info(f"SpotOnTheGoShell card → {screen_key}")
        self.screen_requested.emit(screen_key)

    # ── Priority ladder strip ─────────────────────────────────────────

    def _build_priority_ladder(self) -> None:
        ladder = _PriorityLadder(self)
        ladder.move(60, 668)

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
        for txt, col in (("AUTO MODE",         PURPLE),
                          ("✦ SPOT ON THE GO", CYAN_LIGHT),
                          ("Live Data",        GREEN)):
            p = _StatusPill(txt, col, sb)
            p.move(x, (STATUS_H - p.height()) // 2)
            x += p.width() + 8

        ver = QLabel("Spot on the Go  ·  RadioAI Studio v1.0.0", sb)
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
