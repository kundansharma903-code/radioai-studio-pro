"""
RadioAI Studio Pro — AI Magic Hub
Pixel-accurate match of Figma node 454:3 (file 7oN9K61g94wKx3nu44KKDF,
page "AI Magic Hub").

Landing page for the AI Magic suite. Operator reaches this screen
from the ControlPanel "AI Magic ✦" entry point or via the AI Magic
breadcrumb on any sibling screen. Two medium option cards present
the two AI automation modules:

  • Spot on the Go — daily-recurring spot scheduler (RJ links, news,
    sponsor reads). Operator uploads once, AI places at fixed times
    every day with playback priority (ducks the music underneath).
  • Scheduling Automation — AI-driven clock rotation. Replaces the
    daily scheduler workflow with rule-based clock changes.

Both modules are placeholders today — cards open a "Coming soon"
toast. Sub-screen designs land in follow-up sessions when the
operator briefs the deeper workflow.

Layout (1440 × 900):
  Header        y=  0.. 72   Logo + breadcrumb + title + clock + Open Studio
  Hero block    y= 88..230   "✦ AI MAGIC" big title + tagline + 3 status pills
  Cards         y=268..668   2 medium cards (480×400, 40px gap, centered)
  Roadmap strip y=712..802   Amber-accented banner listing future modules
  Status bar    y=864..900   AUTO MODE · AI MAGIC HUB · Live Data pills + version

Public signals:
  screen_requested(str) — "spot_on_the_go" / "scheduling_automation" /
                          "control_panel"
  studio_clicked()      — header Open Studio button
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from PyQt6.QtCore import Qt, QRectF, QTimer, QPoint, pyqtSignal
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

log = logging.getLogger("AIMagicHub")

WINDOW_W = 1440
WINDOW_H = 900
HEADER_H = 72
STATUS_H = 36


# ════════════════════════════════════════════════════════════════════════════
# Header chrome (mirrors Settings Hub / Play History chrome —
# the deferred library_chrome.py refactor will collapse these once
# the 9th library lands)
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
    """AI Magic crumb pill — purple-accented, sparkle prefix."""

    def __init__(self, label: str = "✦ AI Magic", parent=None):
        super().__init__(parent)
        self.setFixedSize(124, 32)
        self.setStyleSheet(
            f"QFrame {{ background: {rgba(PURPLE, 0.18)}; "
            f"border: 1px solid {rgba(PURPLE, 0.40)}; border-radius: 16px; }}"
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
# Hero status pill (used in the engine-status row above the cards)
# ════════════════════════════════════════════════════════════════════════════


class _HeroStatusPill(QFrame):
    """Larger status pill for the hero row — wider than the StatusPill
    used in the footer."""

    def __init__(self, label: str, color: str, light: str, parent=None):
        super().__init__(parent)
        self._color = color
        self._light = light
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
# Option card — one large tile per AI module
# ════════════════════════════════════════════════════════════════════════════


class _AIOptionCard(QFrame):
    """One AI module tile. Custom paint for the colored top accent +
    the gradient icon circle. Title / subtitle / bullets are QLabels.
    The Configure → CTA emits the screen-key for routing; the whole
    card is also clickable so the operator can target generously."""

    clicked = pyqtSignal(str)

    CARD_W = 480
    CARD_H = 400

    def __init__(self, title: str, subtitle: str, bullets: list[str],
                 glyph: str, accent: str, accent_light: str,
                 screen_key: str, status_label: str = "● COMING SOON",
                 parent=None):
        super().__init__(parent)
        self._accent = accent
        self._accent_light = accent_light
        self._glyph = glyph
        self._screen_key = screen_key
        self.setFixedSize(self.CARD_W, self.CARD_H)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border: 1px solid {rgba('#ffffff', 0.08)}; "
            f"border-radius: 18px; }}"
        )

        # Title (Inter Black 24px)
        t = QLabel(title, self)
        t.setGeometry(32, 148, self.CARD_W - 64, 36)
        t.setFont(inter(24, QFont.Weight.Black, letter_spacing=-0.4))
        t.setStyleSheet(
            f"color: {TEXT_PRI}; background: transparent; border: none;")

        # Subtitle — multi-line, muted
        s = QLabel(subtitle, self)
        s.setGeometry(32, 190, self.CARD_W - 64, 40)
        s.setFont(inter(12, QFont.Weight.Medium))
        s.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent; border: none;")
        s.setWordWrap(True)
        s.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        # 3 feature bullets — left-aligned, accent dot prefix
        for i, b in enumerate(bullets[:3]):
            row = QFrame(self)
            row.setGeometry(28, 244 + i * 22, self.CARD_W - 56, 18)
            row.setStyleSheet("QFrame { background: transparent; border: none; }")
            dot = QLabel("●", row)
            dot.setGeometry(0, 0, 16, 18)
            dot.setFont(inter(8, QFont.Weight.Bold))
            dot.setStyleSheet(
                f"color: {accent_light}; background: transparent; "
                f"border: none;")
            dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
            txt = QLabel(b, row)
            txt.setGeometry(20, 0, self.CARD_W - 56 - 20, 18)
            txt.setFont(inter(11, QFont.Weight.Medium))
            txt.setStyleSheet(
                f"color: #cbd5ff; background: transparent; border: none;")
            txt.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        # Status pill (bottom-left)
        self._status_pill = QFrame(self)
        self._status_pill.setGeometry(28, self.CARD_H - 50, 138, 24)
        self._status_pill.setStyleSheet(
            f"QFrame {{ background: {rgba(accent, 0.15)}; "
            f"border: 1px solid {rgba(accent, 0.40)}; "
            f"border-radius: 12px; }}"
        )
        sp_layout = QHBoxLayout(self._status_pill)
        sp_layout.setContentsMargins(12, 0, 12, 0); sp_layout.setSpacing(0)
        sp_lbl = QLabel(status_label, self._status_pill)
        sp_lbl.setFont(inter(9, QFont.Weight.Bold, letter_spacing=1.1))
        sp_lbl.setStyleSheet(
            f"color: {accent_light}; background: transparent; border: none;")
        sp_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sp_layout.addWidget(sp_lbl)

        # Configure → CTA (bottom-right, gradient)
        cta = QPushButton("Configure  →", self)
        cta.setGeometry(self.CARD_W - 28 - 152, self.CARD_H - 56,
                         152, 36)
        cta.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        cta.setFont(inter(12, QFont.Weight.Bold, letter_spacing=0.4))
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

        # Top accent stripe (gradient L→R)
        sg = QLinearGradient(0, 0, self.width(), 0)
        sg.setColorAt(0.0, QColor(self._accent))
        sg.setColorAt(1.0, QColor(self._accent_light))
        p.fillRect(QRectF(0, 0, self.width(), 4), QBrush(sg))

        # Soft accent edge (1px on left, subtle inner glow)
        edge = QColor(self._accent); edge.setAlphaF(0.4)
        p.fillRect(QRectF(0, 0, 1, self.height()), edge)

        # Icon halo (radial behind the icon) — premium glow
        ICON = 92
        ix = 32 + ICON / 2
        iy = 36 + ICON / 2
        halo_grad = QRadialGradient(ix, iy, ICON / 2 + 14)
        c0 = QColor(self._accent); c0.setAlphaF(0.45)
        c1 = QColor(self._accent); c1.setAlphaF(0.0)
        halo_grad.setColorAt(0.0, c0)
        halo_grad.setColorAt(1.0, c1)
        p.setBrush(QBrush(halo_grad)); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(ix - ICON / 2 - 14, iy - ICON / 2 - 14,
                              ICON + 28, ICON + 28))

        # Icon circle (gradient diag)
        icon_grad = QLinearGradient(32, 36, 32 + ICON, 36 + ICON)
        icon_grad.setColorAt(0.0, QColor(self._accent))
        icon_grad.setColorAt(1.0, QColor(self._accent_light))
        p.setBrush(QBrush(icon_grad)); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(32, 36, ICON, ICON))

        # Glyph (centered in icon)
        p.setPen(QColor(255, 255, 255, 245))
        p.setFont(inter(42, QFont.Weight.Black))
        p.drawText(QRectF(32, 36, ICON, ICON),
                   Qt.AlignmentFlag.AlignCenter, self._glyph)

        p.end()


# ════════════════════════════════════════════════════════════════════════════
# Background glow layer — radial vignettes painted by the parent
# (premium feel — cards already paint their own halos)
# ════════════════════════════════════════════════════════════════════════════


class _PremiumBackdrop(QWidget):
    """Full-screen widget that paints subtle cyan + purple radial
    glows behind everything else. Sits at the bottom of the z-stack
    so all body widgets float on top. The whole point is the premium
    feel — operator's brief was "premium design"."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setStyleSheet("QWidget { background: transparent; }")

    def paintEvent(self, _e):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Cyan glow top-left (decorative — visible behind the hero)
        g1 = QRadialGradient(180, 360, 360)
        c1a = QColor(CYAN); c1a.setAlphaF(0.10)
        c1b = QColor(CYAN); c1b.setAlphaF(0.0)
        g1.setColorAt(0.0, c1a); g1.setColorAt(1.0, c1b)
        p.setBrush(QBrush(g1)); p.setPen(Qt.PenStyle.NoPen)
        p.drawRect(QRectF(-200, 100, 720, 720))

        # Purple glow center-right (behind the second card)
        g2 = QRadialGradient(1180, 480, 420)
        c2a = QColor(PURPLE); c2a.setAlphaF(0.10)
        c2b = QColor(PURPLE); c2b.setAlphaF(0.0)
        g2.setColorAt(0.0, c2a); g2.setColorAt(1.0, c2b)
        p.setBrush(QBrush(g2)); p.setPen(Qt.PenStyle.NoPen)
        p.drawRect(QRectF(880, 200, 700, 700))
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


class AIMagicHub(QWidget):
    """AI Magic landing page (Figma 454:3). Two option cards present
    the AI automation modules; both route via screen_requested(str)
    so the host (MainWindow) decides what each click does today
    (both are placeholders that toast "coming soon")."""

    screen_requested = pyqtSignal(str)
    studio_clicked   = pyqtSignal()

    def __init__(self, db=None, parent=None):
        super().__init__(parent)
        self._db = db
        self.setFixedSize(WINDOW_W, WINDOW_H)
        self.setStyleSheet(f"QWidget {{ background: {BG_BASE}; }}")

        # Backdrop first (z-bottom)
        self._backdrop = _PremiumBackdrop(self)
        self._backdrop.setGeometry(0, 0, WINDOW_W, WINDOW_H)

        self._build_header()
        self._build_hero()
        self._build_cards()
        self._build_roadmap()
        self._build_status_bar()

        # Live clock
        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._tick_clock)
        self._clock_timer.start()
        self._tick_clock()

        log.info("AIMagicHub ready (Figma 454:3)")

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

        # Breadcrumb: Control Panel | [✦ AI Magic] (active)
        cp = _BreadcrumbLink("Control Panel", h)
        cp.setGeometry(176, 22, 100, 22)
        cp.clicked.connect(
            lambda: self.screen_requested.emit("control_panel"))
        sep = QLabel("|", h); sep.setGeometry(272, 22, 8, 22)
        sep.setFont(inter(11))
        sep.setStyleSheet(f"color: {TEXT_DIM}; background: transparent;")
        pill = _BreadcrumbPill("✦ AI Magic", h)
        pill.move(284, 20)

        # Title + subtitle
        title = QLabel("AI Magic", h)
        title.setGeometry(430, 12, 220, 24)
        title.setFont(inter(20, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        sub = QLabel(
            "Premium automation modules for your radio station", h)
        sub.setGeometry(430, 38, 520, 14)
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
        # Big sigil + title (purple sparkle prefix, then "AI MAGIC" big)
        sigil = QLabel("✦", self)
        sigil.setGeometry(60, 100, 40, 56)
        sigil.setFont(inter(42, QFont.Weight.Bold))
        sigil.setStyleSheet(
            f"color: {PURPLE_LIGHT}; background: transparent; "
            f"border: none;")
        title = QLabel("AI MAGIC", self)
        title.setGeometry(110, 100, 700, 56)
        title.setFont(inter(42, QFont.Weight.Black, letter_spacing=-0.5))
        title.setStyleSheet(
            f"color: {TEXT_PRI}; background: transparent; border: none;")

        sub = QLabel(
            "Hands-off automation for your station. Each module below "
            "adds one AI-driven workflow — pick one to configure.", self)
        sub.setGeometry(60, 162, 900, 18)
        sub.setFont(inter(13, QFont.Weight.Medium))
        sub.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent; border: none;")

        # 3 status pills on the engine row
        x = 60
        for label, col, light in (
                ("ENGINE  ·  STANDBY", GREEN, GREEN_LIGHT),
                ("0 / 2 MODULES ACTIVE", PURPLE, PURPLE_LIGHT),
                ("PREMIUM AUTOMATION", CYAN, CYAN_LIGHT),
        ):
            p = _HeroStatusPill(label, col, light, self)
            p.move(x, 196)
            x += p.width() + 10

        # Right-side counter
        right_top = QLabel("2 modules", self)
        right_top.setGeometry(1240, 196, 180, 14)
        right_top.setFont(inter(10, QFont.Weight.Medium))
        right_top.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent; border: none;")
        right_top.setAlignment(Qt.AlignmentFlag.AlignRight)

        right_sub = QLabel("more launching soon", self)
        right_sub.setGeometry(1240, 212, 180, 14)
        right_sub.setFont(inter(9))
        right_sub.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; border: none;")
        right_sub.setAlignment(Qt.AlignmentFlag.AlignRight)

    # ── Cards ─────────────────────────────────────────────────────────

    def _build_cards(self) -> None:
        # 2 cards × 480w × 400h, 40px gap, horizontally centered.
        # (1440 - 480*2 - 40) / 2 = 220
        CARD_W = _AIOptionCard.CARD_W
        CARD_H = _AIOptionCard.CARD_H
        GAP = 40
        start_x = (WINDOW_W - 2 * CARD_W - GAP) // 2
        ys = 268

        specs = [
            ("Spot on the Go",
             "Daily-recurring uploads — RJ links, news, sponsor reads — "
             "land at their fixed slot every day. AI ducks the music "
             "underneath and takes priority.",
             [
                 "Upload once, plays every day at the same time",
                 "Top-priority playback — softly fades the deck",
                 "Set-and-forget — no daily spot re-adding",
             ],
             "⚡", CYAN, CYAN_LIGHT, "spot_on_the_go"),
            ("Scheduling Automation",
             "AI rotates and replaces your clocks on a schedule you set. "
             "No more daily clock-shuffling — the station evolves on "
             "its own.",
             [
                 "AI-driven daily clock rotation",
                 "Custom rules — energy, genre, vocal mix",
                 "Replaces a full-time scheduler workflow",
             ],
             "♻", PURPLE, PURPLE_LIGHT, "scheduling_automation"),
        ]

        self._cards = []
        for i, (title, sub, bullets, glyph, accent, light, key) in enumerate(specs):
            c = _AIOptionCard(title, sub, bullets, glyph, accent, light,
                               key, parent=self)
            c.move(start_x + i * (CARD_W + GAP), ys)
            c.clicked.connect(self._on_card_clicked)
            self._cards.append(c)

    def _on_card_clicked(self, screen_key: str) -> None:
        log.info(f"AIMagicHub card → {screen_key}")
        self.screen_requested.emit(screen_key)

    # ── Roadmap strip ─────────────────────────────────────────────────

    def _build_roadmap(self) -> None:
        """Amber-accented banner below the cards listing the next-up
        AI modules. Reinforces "more coming" without leaving the
        canvas empty."""
        card = QFrame(self)
        card.setGeometry(60, 712, 1320, 90)
        card.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; "
            f"border-radius: 14px; }}"
        )

        # Left accent stripe (painted)
        class _StripeFrame(QFrame):
            def __init__(self_, parent=None):
                super().__init__(parent)
            def paintEvent(self_, _e):
                p = QPainter(self_); p.setRenderHint(QPainter.RenderHint.Antialiasing)
                p.fillRect(QRectF(0, 0, 4, self_.height()), QColor(AMBER))
                p.end()
        stripe = _StripeFrame(card)
        stripe.setGeometry(0, 0, 4, 90)
        stripe.setStyleSheet("QFrame { background: transparent; border: none; }")

        cap = QLabel("ROADMAP  ·  MORE AUTOMATIONS LAUNCHING", card)
        cap.setGeometry(24, 12, 500, 14)
        cap.setFont(inter(10, QFont.Weight.Bold, letter_spacing=1.4))
        cap.setStyleSheet(
            f"color: {AMBER_LIGHT}; background: transparent; border: none;")

        items = QLabel(
            "Voice Tracking AI   ·   Audience Pulse   ·   Auto Mastering "
            "  ·   Smart Crossfades   ·   Hourly Insight Brief", card)
        items.setGeometry(24, 34, 1200, 18)
        items.setFont(inter(12, QFont.Weight.Medium))
        items.setStyleSheet(
            f"color: #cbd5ff; background: transparent; border: none;")

        foot = QLabel(
            "Each module slots in as a new card here once shipped. "
            "Operator stays in control of which automations are active.",
            card)
        foot.setGeometry(24, 58, 1200, 14)
        foot.setFont(inter(10))
        foot.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; border: none;")

    # ── Status bar ────────────────────────────────────────────────────

    def _build_status_bar(self) -> None:
        sb = QFrame(self)
        sb.setGeometry(0, WINDOW_H - STATUS_H, WINDOW_W, STATUS_H)
        sb.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border-top: 1px solid {rgba('#ffffff', 0.06)}; }}"
        )

        x = 12
        for txt, col in (("AUTO MODE",     PURPLE),
                          ("✦ AI MAGIC HUB", PURPLE_LIGHT),
                          ("Live Data",     GREEN)):
            p = _StatusPill(txt, col, sb)
            p.move(x, (STATUS_H - p.height()) // 2)
            x += p.width() + 8

        ver = QLabel("AI Magic  ·  RadioAI Studio v1.0.0", sb)
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
