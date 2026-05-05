"""
RadioAI Studio Pro — Scheduling Hub (Figma 231:3 — Premium Dark Theme).

Top-level scheduling navigation rebuilt from the new premium theme. Pure
navigation + a Studio launcher; status footer reflects scheduler engine
state. Layout patterns here (header, tile system, footer) are reused
across the next ~13 screens.

Layout (1440 × 900)
-------------------
  HEADER     1440 ×  88   y=  0..88
  BODY       1440 × 712   y= 88..800
    Title block + Live Time Pill
    Two-column tile grid:
      LEFT  (x=56,  w=652): Playlists, Main Auto Schedule,
                            Force Clocks Schedule, Rebroadcast Schedule, RDS
      RIGHT (x=732, w=652): Final Log Creator, Log Viewer,
                            then Studio Launcher (taller, 182h)
  STATUS    660 ×  50   (56, 800)
  HAIRLINE  1328×1     y=856
  VERSION   y=872     ...

═════════════════════════════════════════════════════════════════════════════
PERFORMANCE INVARIANTS — DO NOT VIOLATE
═════════════════════════════════════════════════════════════════════════════
  1. event.rect() clipping in every paintEvent that draws structure.
  2. mouseMoveEvent uses self.update(QRect) — NOT bare self.update().
  3. setMouseTracking only where cursor change is needed (none here).
  4. No db calls in paintEvent.
  5. No self.update() inside paintEvent.
  6. No nested QScrollArea (parent MainWindow handles scrolling).
  7. No setFixedSize on heights >2000px.
  8. QLinearGradient / QColor / QFont cached in __init__.
  9. Hover state changes call self.update(self.rect()) only.
  10. Drop shadows use QGraphicsDropShadowEffect — never paint blurs.
═════════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from PyQt6.QtCore import Qt, QRect, QRectF, QPointF, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QLinearGradient, QFont, QCursor,
    QMouseEvent, QPainterPath, QRadialGradient,
)
from PyQt6.QtWidgets import (
    QWidget, QFrame, QGraphicsDropShadowEffect,
)

from ui.widgets._tokens import inter, mono

log = logging.getLogger("SchedulingHub")


# ── Design tokens (per Figma 231:3) ─────────────────────────────────────────

# Background gradient (page-level)
COL_BG_TOP = "#0a0d1a"
COL_BG_MID = "#06080f"
COL_BG_BOT = "#020308"

# Card surfaces
COL_CARD_TOP = "rgba(14,16,32,0.95)"
COL_CARD_BOT = "rgba(7,9,18,0.95)"

# Borders + hairlines
COL_BORDER_FAINT  = QColor(255, 255, 255, 15)   # ~rgba(255,255,255,0.06)
COL_BORDER_HAIRLINE = QColor(255, 255, 255, 10) # ~0.04

# Accent palette (per tile)
COL_CYAN   = "#06b6d4"; COL_CYAN_LT   = "#22d3ee"; COL_CYAN_DK   = "#0e7490"; COL_CYAN_MD   = "#0891b2"
COL_PURPLE = "#a78bfa"; COL_PURPLE_LT = "#c4b5fd"; COL_PURPLE_DEEP = "#7c3aed"; COL_PURPLE_MID = "#8b5cf6"
COL_GREEN  = "#10b981"; COL_GREEN_LT  = "#34d399"; COL_GREEN_DK  = "#047857"; COL_GREEN_MD  = "#059669"
COL_AMBER  = "#f59e0b"; COL_AMBER_LT  = "#fbbf24"; COL_AMBER_DK  = "#b45309"; COL_AMBER_MD  = "#d97706"
COL_ROSE   = "#f43f5e"; COL_ROSE_LT   = "#fb7185"; COL_ROSE_DK   = "#be123c"; COL_ROSE_MD   = "#e11d48"
COL_PINK   = "#ec4899"; COL_PINK_LT   = "#f472b6"; COL_PINK_DK   = "#be185d"; COL_PINK_MD   = "#db2777"
COL_TEAL   = "#14b8a6"; COL_TEAL_LT   = "#5eead4"; COL_TEAL_DK   = "#0f766e"; COL_TEAL_MD   = "#0d9488"

# Text
COL_TEXT_PRIMARY   = "#f1f5ff"
COL_TEXT_SECONDARY = "#8891b8"
COL_TEXT_MUTED     = "#454d6d"
COL_TEXT_DIM       = "#252840"

# Window
WINDOW_W = 1440
WINDOW_H = 900
HEADER_H = 88


def _qcolor(hex_color: str, alpha: float = 1.0) -> QColor:
    """hex like '#06b6d4' + 0..1 alpha → QColor."""
    c = QColor(hex_color)
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


def _shadow(blur: int, color: QColor, dy: int = 0) -> QGraphicsDropShadowEffect:
    """Helper to make a drop shadow effect with given blur + offset."""
    eff = QGraphicsDropShadowEffect()
    eff.setBlurRadius(blur)
    eff.setOffset(0, dy)
    eff.setColor(color)
    return eff


# ════════════════════════════════════════════════════════════════════════
# LOGO — 52×52 purple gradient with 5 white waveform bars + drop shadow
# ════════════════════════════════════════════════════════════════════════

class _Logo(QWidget):
    BAR_HEIGHTS = (6, 14, 22, 14, 6)   # Figma 231:9..13

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(52, 52)
        # Drop shadow: 0 8px 24px rgba(124,58,237,0.4)
        self.setGraphicsEffect(_shadow(24, _qcolor("#7c3aed", 0.40), dy=8))

        # Cache gradient for the logo body
        g = QLinearGradient(0, 0, 52, 52)   # 135deg
        g.setColorAt(0.0, _qcolor("#a78bfa", 1.0))
        g.setColorAt(0.25, _qcolor("#7c3aed", 1.0))
        g.setColorAt(0.50, _qcolor("#5b21b6", 1.0))
        g.setColorAt(1.0, _qcolor("#5b21b6", 1.0))
        self._grad = g

        # Cache top highlight
        gh = QLinearGradient(0, 0, 0, 26)
        gh.setColorAt(0.0, QColor(255, 255, 255, 38))   # 0.15
        gh.setColorAt(1.0, QColor(255, 255, 255, 0))
        self._highlight = gh

        # Bar color
        self._bar = QColor(255, 255, 255, int(0.95 * 255))

    def paintEvent(self, evt):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Body
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, 52, 52), 14, 14)
        p.fillPath(path, QBrush(self._grad))
        # Top highlight
        path_top = QPainterPath()
        path_top.addRoundedRect(QRectF(0, 0, 52, 26), 14, 14)
        p.setClipPath(path)
        p.fillPath(path_top, QBrush(self._highlight))
        p.setClipping(False)
        # Waveform bars: 5 bars at x=8/16/24/32/40, width=4, centered vertically
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self._bar)
        for i, h in enumerate(self.BAR_HEIGHTS):
            x = 8 + i * 8
            y = (52 - h) // 2
            p.drawRoundedRect(QRectF(x, y, 4, h), 2, 2)


# ════════════════════════════════════════════════════════════════════════
# LIVE TIME PILL — 144×44 rose-tinted: red dot + LIVE + clock
# ════════════════════════════════════════════════════════════════════════

class _LiveTimePill(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(144, 44)
        self.setGraphicsEffect(_shadow(16, _qcolor("#f43f5e", 0.20), dy=4))

        self._clock_text = "00:00:00"
        # Cache gradient: rgba(127,29,29,0.4) → rgba(69,10,10,0.4) at 163deg
        g = QLinearGradient(0, 0, 144, 44)
        g.setColorAt(0.0, QColor(127, 29, 29, int(0.40 * 255)))
        g.setColorAt(0.5, QColor(69, 10, 10, int(0.40 * 255)))
        g.setColorAt(1.0, QColor(69, 10, 10, int(0.40 * 255)))
        self._grad = g
        self._border = _qcolor("#f43f5e", 0.30)
        self._dot_outer = _qcolor("#f43f5e", 0.45)
        self._dot_inner = QColor("#f43f5e")
        self._font_live = inter(11, QFont.Weight.Black, letter_spacing=1.5)
        self._font_clock = mono(13, bold=True)

    def set_clock_text(self, t: str) -> None:
        if t != self._clock_text:
            self._clock_text = t
            self.update(QRect(60, 8, 80, 28))   # only clock region

    def paintEvent(self, evt):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), 22, 22)
        p.fillPath(path, QBrush(self._grad))
        p.setPen(QPen(self._border, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        # Pulse dot — outer glow + inner core
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self._dot_outer)
        p.drawEllipse(QRectF(11, 14, 14, 14))
        p.setBrush(self._dot_inner)
        p.drawEllipse(QRectF(14, 17, 8, 8))
        # LIVE label
        p.setPen(QColor("#f43f5e"))
        p.setFont(self._font_live)
        p.drawText(QRectF(30, 11, 36, 18),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "LIVE")
        # Clock
        p.setPen(QColor(COL_TEXT_PRIMARY))
        p.setFont(self._font_clock)
        p.drawText(QRectF(64, 11, 80, 18),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._clock_text)


# ════════════════════════════════════════════════════════════════════════
# ACTIVE STATION CARD — 220×60 green-tinted with pulsing dot
# ════════════════════════════════════════════════════════════════════════

class _ActiveStationCard(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(220, 60)
        self._pulse_on = False
        self._pulse_state = 0.0    # 0..1 used by the pulse animation tick

        # Background gradient at 165deg
        g = QLinearGradient(0, 0, 220, 60)
        g.setColorAt(0.0, _qcolor(COL_GREEN, 0.12))
        g.setColorAt(0.5, _qcolor(COL_GREEN, 0.04))
        g.setColorAt(1.0, _qcolor(COL_GREEN, 0.04))
        self._grad = g

        # Left accent: 4×60 green→cyan vertical
        ag = QLinearGradient(0, 0, 0, 60)
        ag.setColorAt(0.0, QColor(COL_GREEN))
        ag.setColorAt(1.0, QColor(COL_CYAN))
        self._accent = ag

        self._border = _qcolor(COL_GREEN, 0.25)
        self._dot_color = QColor(COL_GREEN)
        self._dot_glow  = QColor(COL_GREEN); self._dot_glow.setAlphaF(0.45)

        self._font_label = inter(8, QFont.Weight.Bold, letter_spacing=1.5)
        self._font_name  = inter(14, QFont.Weight.Bold, letter_spacing=-0.2)
        self._font_city  = inter(10, QFont.Weight.Medium)

    def set_pulse(self, on: bool) -> None:
        if on != self._pulse_on:
            self._pulse_on = on
            self.update(QRect(188, 19, 22, 22))

    def tick_pulse(self, phase01: float) -> None:
        """Called by the 1Hz/sub-Hz hub timer to animate the dot's halo."""
        if not self._pulse_on:
            return
        self._pulse_state = phase01
        self.update(QRect(188, 19, 22, 22))

    def paintEvent(self, evt):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Body
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, 220, 60), 12, 12)
        p.fillPath(path, QBrush(self._grad))
        p.setPen(QPen(self._border, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        # Left accent (4×60, only visible inside the rounded clip)
        p.setClipPath(path)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(self._accent))
        p.drawRect(QRectF(0, 0, 4, 60))
        p.setClipping(False)
        # Labels
        p.setPen(QColor(COL_GREEN))
        p.setFont(self._font_label)
        p.drawText(QRectF(12, 6, 200, 12),
                   Qt.AlignmentFlag.AlignLeft, "ACTIVE STATION")
        p.setPen(QColor(COL_TEXT_PRIMARY))
        p.setFont(self._font_name)
        p.drawText(QRectF(12, 21, 200, 18),
                   Qt.AlignmentFlag.AlignLeft, "KISS FM 91.5")
        p.setPen(QColor(COL_TEXT_SECONDARY))
        p.setFont(self._font_city)
        p.drawText(QRectF(12, 40, 200, 14),
                   Qt.AlignmentFlag.AlignLeft, "Jaipur, Rajasthan")
        # Pulsing dot — at (193, 24) 10×10 outer + (196, 27) 4×4 inner
        if self._pulse_on:
            halo_r = 5 + int(self._pulse_state * 4)   # 5..9
            halo_c = QColor(self._dot_glow)
            halo_c.setAlphaF(0.45 * (1.0 - self._pulse_state))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(halo_c)
            p.drawEllipse(QPointF(198, 30), halo_r, halo_r)
            p.setBrush(self._dot_color)
            p.drawEllipse(QRectF(193, 25, 10, 10))
        else:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(COL_TEXT_MUTED))
            p.drawEllipse(QRectF(193, 25, 10, 10))


# ════════════════════════════════════════════════════════════════════════
# OPEN STUDIO HEADER BUTTON — 200×52 purple gradient w/ ▶ + label + sub
# ════════════════════════════════════════════════════════════════════════

class _OpenStudioHeaderButton(QWidget):
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(200, 52)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        # Drop shadow: 0 8px 24px rgba(124,58,237,0.5) + 0 0 40px rgba(167,139,250,0.3)
        self.setGraphicsEffect(_shadow(28, _qcolor("#7c3aed", 0.50), dy=8))
        self._hover = False

        # Background gradient 165deg purple-light → purple-mid → purple-deep
        g = QLinearGradient(0, 0, 200, 52)
        g.setColorAt(0.0, _qcolor("#a78bfa", 1.0))
        g.setColorAt(0.25, _qcolor("#8b5cf6", 1.0))
        g.setColorAt(0.5, _qcolor("#7c3aed", 1.0))
        g.setColorAt(1.0, _qcolor("#7c3aed", 1.0))
        self._grad = g
        # Top highlight
        hg = QLinearGradient(0, 0, 0, 26)
        hg.setColorAt(0.0, QColor(255, 255, 255, int(0.15 * 255)))
        hg.setColorAt(1.0, QColor(255, 255, 255, 0))
        self._highlight = hg

        self._font_play = inter(11, QFont.Weight.Bold)
        self._font_label = inter(14, QFont.Weight.Bold, letter_spacing=-0.2)
        self._font_sub = inter(8, QFont.Weight.DemiBold, letter_spacing=1.8)

    def enterEvent(self, e):
        self._hover = True
        self.update(self.rect())

    def leaveEvent(self, e):
        self._hover = False
        self.update(self.rect())

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def paintEvent(self, evt):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, 200, 52), 14, 14)
        p.fillPath(path, QBrush(self._grad))
        # Hover lighten — overlay 6% white
        if self._hover:
            p.fillPath(path, QColor(255, 255, 255, int(0.06 * 255)))
        # Top highlight inside rounded clip
        p.setClipPath(path)
        path_h = QPainterPath()
        path_h.addRoundedRect(QRectF(1, 1, 198, 24), 14, 14)
        p.fillPath(path_h, QBrush(self._highlight))
        p.setClipping(False)
        # Play icon circle + ▶ glyph
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, int(0.20 * 255)))
        p.drawEllipse(QRectF(16, 14, 24, 24))
        p.setPen(QColor("#ffffff"))
        p.setFont(self._font_play)
        p.drawText(QRectF(16, 14, 24, 24), Qt.AlignmentFlag.AlignCenter, "▶")
        # "Open Studio" + "GO LIVE NOW"
        p.setPen(QColor("#ffffff"))
        p.setFont(self._font_label)
        p.drawText(QRectF(50, 11, 140, 18),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "Open Studio")
        p.setPen(QColor(255, 255, 255, int(0.70 * 255)))
        p.setFont(self._font_sub)
        p.drawText(QRectF(50, 30, 140, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "GO LIVE NOW")


# ════════════════════════════════════════════════════════════════════════
# HEADER — Logo + wordmark + nav tabs + clock + ActiveStation + OpenStudio
# ════════════════════════════════════════════════════════════════════════

class _Header(QWidget):
    libraries_clicked   = pyqtSignal()
    settings_clicked    = pyqtSignal()
    ai_magic_clicked    = pyqtSignal()
    studio_open_clicked = pyqtSignal()

    NAV_TABS = (
        ("Libraries",  240),
        ("Scheduling", 358),    # active
        ("Settings",   478),
        ("AI Magic ✦", 590),
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(WINDOW_W, HEADER_H)
        self.setMouseTracking(False)

        # Header background gradient (top→bottom dark navy with slight
        # transparency for the page glows to peek through)
        bg = QLinearGradient(0, 0, 0, HEADER_H)
        bg.setColorAt(0.0, QColor(16, 19, 31, int(0.90 * 255)))
        bg.setColorAt(1.0, QColor(10, 12, 22, int(0.90 * 255)))
        self._bg = bg

        # Active tab underline gradient (cyan → purple → pink)
        ug = QLinearGradient(0, 0, 92, 0)
        ug.setColorAt(0.0, QColor(COL_CYAN))
        ug.setColorAt(0.5, QColor(COL_PURPLE))
        ug.setColorAt(1.0, QColor(COL_PINK))
        self._underline = ug

        # Hairline gradient at y=87
        hl = QLinearGradient(0, 0, WINDOW_W, 0)
        hl.setColorAt(0.0, QColor(255, 255, 255, 0))
        hl.setColorAt(0.5, QColor(255, 255, 255, int(0.10 * 255)))
        hl.setColorAt(1.0, QColor(255, 255, 255, 0))
        self._hairline = hl

        # Cached fonts
        self._font_brand    = inter(22, QFont.Weight.Black, letter_spacing=-0.5)
        self._font_studio_pro = inter(9, QFont.Weight.Bold, letter_spacing=2.5)
        self._font_subtitle = inter(8, QFont.Weight.Medium, letter_spacing=1.5)
        self._font_tab      = inter(14, QFont.Weight.Medium, letter_spacing=-0.2)
        self._font_tab_active = inter(14, QFont.Weight.Black, letter_spacing=-0.2)
        self._font_clock_lg = mono(32, bold=True, letter_spacing=-1.0)
        self._font_clock_sm = mono(26, bold=True, letter_spacing=-1.0)
        self._font_day      = inter(9, QFont.Weight.Bold, letter_spacing=2.0)
        self._font_date     = inter(9, QFont.Weight.Medium, letter_spacing=1.0)

        # Live time state — updated by Hub's QTimer
        self._time_main = "00:00"
        self._time_sec  = ":00"
        self._day_str   = "MONDAY"
        self._date_str  = "JANUARY 1, 2024"

        # Children
        self._logo = _Logo(self)
        self._logo.move(28, 18)

        self._station = _ActiveStationCard(self)
        self._station.move(968, 14)

        self._open_studio = _OpenStudioHeaderButton(self)
        self._open_studio.move(1208, 18)
        self._open_studio.clicked.connect(self.studio_open_clicked.emit)

        # Nav tab hit rects
        self._tab_rects: dict[str, QRect] = {}

    # ── public ────────────────────────────────────────────────────────

    def set_time(self, hhmm: str, ss: str, day: str, date: str) -> None:
        if hhmm != self._time_main or ss != self._time_sec:
            self._time_main = hhmm
            self._time_sec = ss
            self.update(QRect(740, 12, 200, 50))
        if day != self._day_str or date != self._date_str:
            self._day_str = day
            self._date_str = date
            self.update(QRect(740, 50, 220, 18))

    @property
    def station_card(self) -> _ActiveStationCard:
        return self._station

    # ── interaction ───────────────────────────────────────────────────

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() != Qt.MouseButton.LeftButton:
            return
        for label, x in self.NAV_TABS:
            r = QRect(x - 6, 30, 100, 28)
            if r.contains(e.pos()):
                if label == "Libraries":
                    self.libraries_clicked.emit()
                elif label == "Settings":
                    self.settings_clicked.emit()
                elif label == "AI Magic ✦":
                    self.ai_magic_clicked.emit()
                # Scheduling is the active tab — no-op
                return

    # ── paint ─────────────────────────────────────────────────────────

    def paintEvent(self, evt):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        # Header bg
        p.fillRect(rect, QBrush(self._bg))

        # Wordmark text block
        p.setPen(QColor(COL_TEXT_PRIMARY))
        p.setFont(self._font_brand)
        p.drawText(QRectF(92, 14, 200, 28),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "RadioAI")
        p.setPen(QColor(COL_PURPLE))
        p.setFont(self._font_studio_pro)
        p.drawText(QRectF(92, 45, 200, 14),
                   Qt.AlignmentFlag.AlignLeft, "STUDIO PRO")
        p.setPen(QColor(COL_TEXT_MUTED))
        p.setFont(self._font_subtitle)
        p.drawText(QRectF(92, 60, 200, 14),
                   Qt.AlignmentFlag.AlignLeft, "BROADCAST AUTOMATION")

        # Nav tabs
        for label, x in self.NAV_TABS:
            active = (label == "Scheduling")
            p.setPen(QColor(COL_TEXT_PRIMARY if active else COL_TEXT_SECONDARY))
            p.setFont(self._font_tab_active if active else self._font_tab)
            p.drawText(QRectF(x, 32, 120, 20),
                       Qt.AlignmentFlag.AlignLeft, label)
        # Active tab underline 92×3 at (358, 60), gradient cyan→purple→pink
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(self._underline))
        path = QPainterPath()
        path.addRoundedRect(QRectF(358, 60, 92, 3), 1.5, 1.5)
        p.fillPath(path, QBrush(self._underline))

        # Center clock
        p.setPen(QColor(COL_TEXT_PRIMARY))
        p.setFont(self._font_clock_lg)
        p.drawText(QRectF(740, 12, 100, 42),
                   Qt.AlignmentFlag.AlignLeft, self._time_main)
        p.setPen(QColor(COL_TEXT_MUTED))
        p.setFont(self._font_clock_sm)
        p.drawText(QRectF(832, 18, 60, 38),
                   Qt.AlignmentFlag.AlignLeft, self._time_sec)
        # Day + date
        p.setPen(QColor(COL_PURPLE))
        p.setFont(self._font_day)
        p.drawText(QRectF(740, 52, 60, 14),
                   Qt.AlignmentFlag.AlignLeft, self._day_str)
        p.setPen(QColor(COL_TEXT_MUTED))
        p.setFont(self._font_date)
        p.drawText(QRectF(800, 52, 200, 14),
                   Qt.AlignmentFlag.AlignLeft, self._date_str)

        # Hairline at y=87
        p.fillRect(QRectF(0, 87, WINDOW_W, 1), QBrush(self._hairline))


# ════════════════════════════════════════════════════════════════════════
# TILE CARD — 652×96 colored-accent navigation card
# ════════════════════════════════════════════════════════════════════════

class _TileSpec:
    """Compact descriptor passed to _TileCard for one tile."""
    __slots__ = ("key", "title", "desc", "accent", "accent_dk", "accent_md",
                 "accent_lt", "icon_kind")

    def __init__(self, key, title, desc, accent, accent_dk, accent_md,
                 accent_lt, icon_kind):
        self.key = key; self.title = title; self.desc = desc
        self.accent = accent; self.accent_dk = accent_dk
        self.accent_md = accent_md; self.accent_lt = accent_lt
        self.icon_kind = icon_kind   # one of the icon-render modes below


# Icon kinds — each draws a small graphic inside the 66×66 icon container
ICON_KIND_ROWS_AND_DOTS = "rows_and_dots"   # Playlists
ICON_KIND_GRID          = "grid"            # Main Auto Schedule
ICON_KIND_BOLT          = "bolt"            # Force Clocks
ICON_KIND_RADIO         = "radio"           # Rebroadcast
ICON_KIND_SIGNAL        = "signal"          # RDS
ICON_KIND_CLIPBOARD     = "clipboard"       # Final Log Creator
ICON_KIND_LIST          = "list"            # Log Viewer


class _TileCard(QWidget):
    """One navigation tile. Click anywhere on the card emits clicked."""
    clicked = pyqtSignal(str)

    def __init__(self, spec: _TileSpec, parent=None):
        super().__init__(parent)
        self._spec = spec
        self.setFixedSize(652, 96)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._hover = False

        # Drop shadow: 0 8px 24px rgba(0,0,0,0.4) + 0 16px 48px <accent 0.06>
        self.setGraphicsEffect(_shadow(20, QColor(0, 0, 0, int(0.40 * 255)), dy=8))

        # Card body gradient (vertical) — a near-black with purple haze
        g_body = QLinearGradient(0, 0, 0, 96)
        g_body.setColorAt(0.0, QColor(14, 16, 32, int(0.95 * 255)))
        g_body.setColorAt(1.0, QColor(7, 9, 18, int(0.95 * 255)))
        self._grad_body = g_body

        # 3px top accent gradient (left→right): accent → accent_md → accent_dk
        g_top = QLinearGradient(0, 0, 652, 0)
        g_top.setColorAt(0.0, QColor(spec.accent))
        g_top.setColorAt(0.5, QColor(spec.accent_md))
        g_top.setColorAt(1.0, QColor(spec.accent_dk))
        self._grad_top = g_top

        # Inner accent haze under the top edge (vertical)
        g_haze = QLinearGradient(0, 0, 0, 87)
        g_haze.setColorAt(0.0, _qcolor(spec.accent, 0.05))
        g_haze.setColorAt(0.7, _qcolor(spec.accent, 0.0))
        g_haze.setColorAt(1.0, _qcolor(spec.accent, 0.0))
        self._grad_haze = g_haze

        # Icon container gradient (135deg)
        g_icon = QLinearGradient(0, 0, 66, 66)
        g_icon.setColorAt(0.0, _qcolor(spec.accent, 0.22))
        g_icon.setColorAt(0.5, _qcolor(spec.accent_dk, 0.10))
        g_icon.setColorAt(1.0, _qcolor(spec.accent_dk, 0.10))
        self._grad_icon = g_icon

        # Icon top highlight
        g_icon_hl = QLinearGradient(0, 0, 0, 32)
        g_icon_hl.setColorAt(0.0, QColor(255, 255, 255, int(0.15 * 255)))
        g_icon_hl.setColorAt(1.0, QColor(255, 255, 255, 0))
        self._grad_icon_hl = g_icon_hl

        # Open button gradient (horizontal) — accent at low alpha
        g_btn = QLinearGradient(0, 0, 70, 0)
        g_btn.setColorAt(0.0, _qcolor(spec.accent, 0.18))
        g_btn.setColorAt(1.0, _qcolor(spec.accent, 0.06))
        self._grad_btn = g_btn

        # Hover overlay color (subtle accent wash)
        self._hover_wash = _qcolor(spec.accent, 0.08)

        # Cached fonts
        self._font_title = inter(24, QFont.Weight.Black, letter_spacing=-0.6)
        self._font_desc  = inter(12, QFont.Weight.Medium, letter_spacing=-0.05)
        self._font_btn   = inter(11, QFont.Weight.Bold, letter_spacing=0.3)

    # ── interaction ───────────────────────────────────────────────────

    def enterEvent(self, e):
        self._hover = True
        self.update(self.rect())

    def leaveEvent(self, e):
        self._hover = False
        self.update(self.rect())

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._spec.key)

    # ── paint ─────────────────────────────────────────────────────────

    def paintEvent(self, evt):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Body (rounded 18)
        body_path = QPainterPath()
        body_path.addRoundedRect(QRectF(0, 0, 652, 96), 18, 18)
        p.fillPath(body_path, QBrush(self._grad_body))
        if self._hover:
            p.fillPath(body_path, self._hover_wash)
        # Border
        p.setPen(QPen(COL_BORDER_FAINT, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(body_path)

        # Inner accent haze (clip to body)
        p.setClipPath(body_path)
        p.fillRect(QRectF(0, 0, 652, 87), QBrush(self._grad_haze))
        # 3px top accent (clipped to body so corners are rounded)
        p.fillRect(QRectF(0, 0, 652, 3), QBrush(self._grad_top))
        # Highlight hairline at y=2..3
        p.fillRect(QRectF(0, 2, 652, 1), QColor(255, 255, 255, int(0.04 * 255)))
        p.setClipping(False)

        # Icon container (66×66 at x=22, y=14, rounded 16)
        ic_rect = QRectF(22, 14, 66, 66)
        ic_path = QPainterPath(); ic_path.addRoundedRect(ic_rect, 16, 16)
        p.fillPath(ic_path, QBrush(self._grad_icon))
        p.setPen(QPen(_qcolor(self._spec.accent, 0.35), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(ic_path)
        # Icon top highlight (clip)
        p.setClipPath(ic_path)
        p.fillRect(QRectF(22, 14, 64, 32), QBrush(self._grad_icon_hl))
        p.setClipping(False)
        # Icon graphic
        self._paint_icon_glyph(p, ic_rect)

        # Title + description
        p.setPen(QColor(COL_TEXT_PRIMARY))
        p.setFont(self._font_title)
        p.drawText(QRectF(108, 13, 440, 32),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._spec.title)
        p.setPen(QColor(COL_TEXT_SECONDARY))
        p.setFont(self._font_desc)
        p.drawText(QRectF(108, 49, 432, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._spec.desc)

        # Open button (70×26 at x=561, y=34, rounded 8)
        btn_path = QPainterPath()
        btn_path.addRoundedRect(QRectF(561, 34, 70, 26), 8, 8)
        p.fillPath(btn_path, QBrush(self._grad_btn))
        p.setPen(QPen(_qcolor(self._spec.accent, 0.30), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(btn_path)
        p.setPen(QColor(self._spec.accent_lt))
        p.setFont(self._font_btn)
        p.drawText(QRectF(561, 34, 70, 26),
                   Qt.AlignmentFlag.AlignCenter, "Open  →")

    def _paint_icon_glyph(self, p: QPainter, rect: QRectF) -> None:
        """Tiny accent-colored shape inside the 66×66 icon container.
        Each kind is a quick QPainter sketch — no SVG dependency."""
        kind = self._spec.icon_kind
        white = QColor(255, 255, 255, int(0.95 * 255))
        white_dim = QColor(255, 255, 255, int(0.85 * 255))
        white_dimmer = QColor(255, 255, 255, int(0.70 * 255))
        cx, cy = rect.x() + 33, rect.y() + 33
        p.setPen(Qt.PenStyle.NoPen)

        if kind == ICON_KIND_ROWS_AND_DOTS:
            # 3 rows of dot+line (Playlists)
            p.setBrush(white)
            for i, dy in enumerate((-12, 0, 12)):
                p.drawRoundedRect(QRectF(cx - 14, cy + dy - 2, 4, 4), 1, 1)
                p.drawRoundedRect(QRectF(cx - 8, cy + dy - 1, 22, 2), 1, 1)
        elif kind == ICON_KIND_GRID:
            # 3×3 grid (Main Auto Schedule)
            p.setBrush(white)
            for r in range(3):
                for c in range(3):
                    x = cx - 12 + c * 8
                    y = cy - 12 + r * 8
                    a = QColor(255, 255, 255, 250 - r * 40 - c * 20)
                    p.setBrush(a)
                    p.drawRoundedRect(QRectF(x, y, 5, 5), 1, 1)
        elif kind == ICON_KIND_BOLT:
            # Lightning bolt (Force Clocks)
            path = QPainterPath()
            path.moveTo(cx - 4, cy - 14)
            path.lineTo(cx + 6, cy - 14)
            path.lineTo(cx, cy)
            path.lineTo(cx + 8, cy)
            path.lineTo(cx - 8, cy + 14)
            path.lineTo(cx - 2, cy + 2)
            path.lineTo(cx - 8, cy + 2)
            path.closeSubpath()
            p.setBrush(white)
            p.drawPath(path)
        elif kind == ICON_KIND_RADIO:
            # Concentric arcs + center dot (Rebroadcast)
            p.setPen(QPen(white, 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            for r in (6, 10, 14):
                p.drawArc(QRectF(cx - r, cy - r, r * 2, r * 2),
                          int(45 * 16), int(90 * 16))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(white)
            p.drawEllipse(QPointF(cx, cy), 3, 3)
        elif kind == ICON_KIND_SIGNAL:
            # Tower with ascending bars (RDS)
            p.setBrush(white)
            for i, h in enumerate((6, 10, 14, 18)):
                p.drawRoundedRect(QRectF(cx - 12 + i * 6, cy + 8 - h, 4, h), 1, 1)
        elif kind == ICON_KIND_CLIPBOARD:
            # Clipboard shape (Final Log Creator)
            p.setPen(QPen(white, 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(cx - 11, cy - 13, 22, 28), 3, 3)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(white)
            p.drawRoundedRect(QRectF(cx - 5, cy - 16, 10, 5), 2, 2)
            for i, dy in enumerate((-4, 1, 6)):
                p.drawRoundedRect(QRectF(cx - 7, cy + dy, 14, 1.5), 1, 1)
        elif kind == ICON_KIND_LIST:
            # Lined list with descending opacity (Log Viewer)
            p.setPen(QPen(white, 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(cx - 11, cy - 13, 22, 28), 3, 3)
            for i, alpha in enumerate((0.85, 0.75, 0.65, 0.55, 0.45)):
                col = QColor(255, 255, 255, int(alpha * 255))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(col)
                p.drawRoundedRect(QRectF(cx - 8, cy - 9 + i * 5, 14, 1.5), 1, 1)


# ════════════════════════════════════════════════════════════════════════
# STUDIO LAUNCHER — 652×182 hero card with NOW PLAYING + Go Live button
# ════════════════════════════════════════════════════════════════════════

class _StudioLauncher(QWidget):
    clicked = pyqtSignal()
    go_live_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(652, 182)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._hover = False

        # Drop shadow: deep purple glow
        self.setGraphicsEffect(_shadow(34, _qcolor("#7c3aed", 0.45), dy=16))

        # Body gradient (164deg) — deep purple to near-black
        g_body = QLinearGradient(0, 0, 652, 182)
        g_body.setColorAt(0.0, QColor(26, 13, 58))
        g_body.setColorAt(0.25, QColor(17, 8, 43))
        g_body.setColorAt(0.5, QColor(7, 3, 20))
        g_body.setColorAt(1.0, QColor(7, 3, 20))
        self._grad_body = g_body

        # 4px top rainbow gradient — cyan → purple → pink → rose
        g_top = QLinearGradient(0, 0, 652, 0)
        g_top.setColorAt(0.0, QColor(COL_CYAN))
        g_top.setColorAt(0.33, QColor(COL_PURPLE))
        g_top.setColorAt(0.66, QColor(COL_PINK))
        g_top.setColorAt(1.0, QColor(COL_ROSE))
        self._grad_top = g_top

        # Top haze
        g_haze = QLinearGradient(0, 0, 0, 90)
        g_haze.setColorAt(0.0, _qcolor(COL_PURPLE, 0.10))
        g_haze.setColorAt(1.0, _qcolor(COL_PURPLE, 0.0))
        self._grad_haze = g_haze

        # Studio icon box gradient (135deg)
        g_icon = QLinearGradient(0, 0, 130, 130)
        g_icon.setColorAt(0.0, _qcolor(COL_PURPLE, 0.30))
        g_icon.setColorAt(1.0, _qcolor(COL_PURPLE_DEEP, 0.10))
        self._grad_icon = g_icon

        # Go Live button gradient (purple)
        g_btn = QLinearGradient(0, 0, 152, 44)
        g_btn.setColorAt(0.0, _qcolor("#a78bfa", 1.0))
        g_btn.setColorAt(0.25, _qcolor("#8b5cf6", 1.0))
        g_btn.setColorAt(0.5, _qcolor("#7c3aed", 1.0))
        g_btn.setColorAt(1.0, _qcolor("#7c3aed", 1.0))
        self._grad_btn = g_btn

        # Cached fonts
        self._font_studio_label = inter(10, QFont.Weight.Bold, letter_spacing=3.0)
        self._font_open_studio  = inter(32, QFont.Weight.Black, letter_spacing=-1.0)
        self._font_now_label    = inter(9, QFont.Weight.Bold, letter_spacing=1.5)
        self._font_track        = inter(14, QFont.Weight.DemiBold, letter_spacing=-0.2)
        self._font_track_meta   = inter(11, QFont.Weight.Medium)
        self._font_btn          = inter(14, QFont.Weight.Bold, letter_spacing=-0.2)

        # Now playing state
        self._track_title  = "—"
        self._track_meta   = "Studio idle"

    def set_now_playing(self, title: str, meta: str) -> None:
        if title != self._track_title or meta != self._track_meta:
            self._track_title = title
            self._track_meta = meta
            self.update(QRect(177, 80, 460, 60))

    def enterEvent(self, e):
        self._hover = True
        self.update(self.rect())

    def leaveEvent(self, e):
        self._hover = False
        self.update(self.rect())

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() != Qt.MouseButton.LeftButton:
            return
        # Go Live button at (473, 123) 152×44
        if QRect(473, 123, 152, 44).contains(e.pos()):
            self.go_live_clicked.emit()
            return
        self.clicked.emit()

    def paintEvent(self, evt):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Body
        body_path = QPainterPath()
        body_path.addRoundedRect(QRectF(0, 0, 652, 182), 22, 22)
        p.fillPath(body_path, QBrush(self._grad_body))
        if self._hover:
            p.fillPath(body_path, _qcolor(COL_PURPLE, 0.06))
        p.setPen(QPen(_qcolor(COL_PURPLE, 0.40), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(body_path)
        # Top accent + haze (clip)
        p.setClipPath(body_path)
        p.fillRect(QRectF(0, 0, 652, 4), QBrush(self._grad_top))
        p.fillRect(QRectF(0, 4, 652, 90), QBrush(self._grad_haze))
        p.fillRect(QRectF(0, 4, 652, 1), QColor(255, 255, 255, int(0.06 * 255)))
        p.setClipping(False)

        # Studio icon box (130×130 at 25,25, rounded 18)
        icon_rect = QRectF(25, 25, 130, 130)
        ic_path = QPainterPath(); ic_path.addRoundedRect(icon_rect, 18, 18)
        p.fillPath(ic_path, QBrush(self._grad_icon))
        p.setPen(QPen(_qcolor(COL_PURPLE, 0.35), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(ic_path)
        # Studio glyph: simplified mic icon centered
        cx, cy = 90, 90
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, int(0.92 * 255)))
        p.drawRoundedRect(QRectF(cx - 14, cy - 32, 28, 44), 14, 14)
        p.setPen(QPen(QColor(255, 255, 255, int(0.65 * 255)), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(QRectF(cx - 22, cy - 14, 44, 36),
                  int(200 * 16), int(140 * 16))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, int(0.85 * 255)))
        p.drawRoundedRect(QRectF(cx - 2, cy + 18, 4, 14), 1, 1)
        p.drawRoundedRect(QRectF(cx - 10, cy + 32, 20, 3), 1.5, 1.5)

        # STUDIO label
        p.setPen(QColor(COL_PURPLE))
        p.setFont(self._font_studio_label)
        p.drawText(QRectF(177, 23, 200, 14),
                   Qt.AlignmentFlag.AlignLeft, "STUDIO")
        # Open Studio big title
        p.setPen(QColor(COL_TEXT_PRIMARY))
        p.setFont(self._font_open_studio)
        p.drawText(QRectF(177, 40, 400, 44),
                   Qt.AlignmentFlag.AlignLeft, "Open Studio")
        # NOW PLAYING + track
        p.setPen(QColor(COL_TEXT_SECONDARY))
        p.setFont(self._font_now_label)
        p.drawText(QRectF(177, 86, 200, 14),
                   Qt.AlignmentFlag.AlignLeft, "NOW PLAYING")
        p.setPen(QColor(COL_TEXT_PRIMARY))
        p.setFont(self._font_track)
        p.drawText(QRectF(177, 102, 280, 18),
                   Qt.AlignmentFlag.AlignLeft, self._track_title)
        p.setPen(QColor(COL_TEXT_MUTED))
        p.setFont(self._font_track_meta)
        p.drawText(QRectF(177, 122, 290, 16),
                   Qt.AlignmentFlag.AlignLeft, self._track_meta)

        # Go Live button (152×44 at 473, 123, rounded 12)
        btn_path = QPainterPath()
        btn_path.addRoundedRect(QRectF(473, 123, 152, 44), 12, 12)
        p.fillPath(btn_path, QBrush(self._grad_btn))
        # Top highlight on button
        p.setClipPath(btn_path)
        hl = QLinearGradient(0, 124, 0, 144)
        hl.setColorAt(0.0, QColor(255, 255, 255, int(0.20 * 255)))
        hl.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.fillRect(QRectF(474, 124, 150, 20), QBrush(hl))
        p.setClipping(False)
        p.setPen(QColor("#ffffff"))
        p.setFont(self._font_btn)
        p.drawText(QRectF(473, 123, 152, 44),
                   Qt.AlignmentFlag.AlignCenter, "▶  Go Live Now")


# ════════════════════════════════════════════════════════════════════════
# STATUS FOOTER — 660×50 with pulse dot + system status + uptime
# ════════════════════════════════════════════════════════════════════════

class _StatusFooter(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(660, 50)
        self._healthy = True
        self._uptime_text = "Program start up just now"
        self._heading = "SYSTEM HEALTHY"
        self._message = "Everything running smoothly. No problems."

        # Healthy / unhealthy gradient sets
        g_ok = QLinearGradient(0, 0, 660, 0)
        g_ok.setColorAt(0.0, _qcolor(COL_GREEN, 0.08))
        g_ok.setColorAt(1.0, QColor(14, 16, 32, int(0.50 * 255)))
        self._grad_ok = g_ok
        g_err = QLinearGradient(0, 0, 660, 0)
        g_err.setColorAt(0.0, _qcolor(COL_ROSE, 0.10))
        g_err.setColorAt(1.0, QColor(14, 16, 32, int(0.50 * 255)))
        self._grad_err = g_err

        self._font_label = inter(9, QFont.Weight.Bold, letter_spacing=1.5)
        self._font_msg   = inter(13, QFont.Weight.DemiBold, letter_spacing=-0.1)
        self._font_meta  = inter(11, QFont.Weight.Medium)

    def set_state(self, healthy: bool, heading: str, message: str) -> None:
        if (healthy, heading, message) != (self._healthy, self._heading, self._message):
            self._healthy = healthy
            self._heading = heading
            self._message = message
            self.update(self.rect())

    def set_uptime(self, text: str) -> None:
        if text != self._uptime_text:
            self._uptime_text = text
            self.update(QRect(330, 18, 320, 16))

    def paintEvent(self, evt):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, 660, 50), 12, 12)
        accent = COL_GREEN if self._healthy else COL_ROSE
        grad = self._grad_ok if self._healthy else self._grad_err
        p.fillPath(path, QBrush(grad))
        p.setPen(QPen(_qcolor(accent, 0.18), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        # Pulse dot 10×10 at (17, 20) + inner 4×4 at (20, 23)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_qcolor(accent, 0.45))
        p.drawEllipse(QRectF(15, 18, 14, 14))
        p.setBrush(QColor(accent))
        p.drawEllipse(QRectF(17, 20, 10, 10))
        # Heading + message
        p.setPen(QColor(accent))
        p.setFont(self._font_label)
        p.drawText(QRectF(37, 6, 200, 14),
                   Qt.AlignmentFlag.AlignLeft, self._heading)
        p.setPen(QColor(COL_TEXT_PRIMARY))
        p.setFont(self._font_msg)
        p.drawText(QRectF(37, 22, 320, 18),
                   Qt.AlignmentFlag.AlignLeft, self._message)
        # Uptime
        p.setPen(QColor(COL_TEXT_SECONDARY))
        p.setFont(self._font_meta)
        p.drawText(QRectF(330, 22, 320, 16),
                   Qt.AlignmentFlag.AlignLeft, self._uptime_text)


# ════════════════════════════════════════════════════════════════════════
# SCHEDULING HUB — top-level
# ════════════════════════════════════════════════════════════════════════

# 7 tile specs in render order. `key` is the value emitted by
# screen_requested when the tile is clicked.
_TILE_SPECS_LEFT = [
    _TileSpec("playlists",            "Playlists",
              "Custom playlists — build, import, and schedule",
              COL_CYAN,   COL_CYAN_DK,   COL_CYAN_MD,   COL_CYAN_LT,
              ICON_KIND_ROWS_AND_DOTS),
    _TileSpec("main_auto_schedule",   "Main Auto Schedule",
              "Edit and schedule the clocks for all week",
              COL_PURPLE, COL_PURPLE_DEEP, "#8b5cf6", COL_PURPLE_LT,
              ICON_KIND_GRID),
    _TileSpec("force_clocks",         "Force Clocks Schedule",
              "Override rotation with custom playlist clocks",
              COL_AMBER,  COL_AMBER_DK,  COL_AMBER_MD,  COL_AMBER_LT,
              ICON_KIND_BOLT),
    _TileSpec("rebroadcast",          "Rebroadcast Schedule",
              "Edit and schedule your rebroadcasting sources",
              COL_GREEN,  COL_GREEN_DK,  COL_GREEN_MD,  COL_GREEN_LT,
              ICON_KIND_RADIO),
    _TileSpec("rds",                  "RDS",
              "Edit and schedule your RDS texts",
              COL_PINK,   COL_PINK_DK,   COL_PINK_MD,   COL_PINK_LT,
              ICON_KIND_SIGNAL),
]
_TILE_SPECS_RIGHT_TOP = [
    _TileSpec("final_log_creator",    "Final Log Creator",
              "Create or edit the full final playlist for the day",
              COL_ROSE,   COL_ROSE_DK,   COL_ROSE_MD,   COL_ROSE_LT,
              ICON_KIND_CLIPBOARD),
    _TileSpec("log_viewer",           "Log Viewer",
              "See what played on-air vs the planned log",
              COL_TEAL,   COL_TEAL_DK,   COL_TEAL_MD,   COL_TEAL_LT,
              ICON_KIND_LIST),
]


class SchedulingHub(QWidget):
    """Premium-theme scheduling hub. Emits screen_requested(str) when the
    user picks a tile / launcher / settings link."""

    screen_requested = pyqtSignal(str)

    def __init__(self, db, scheduler=None, studio=None, parent=None):
        super().__init__(parent)
        self._db = db
        self._scheduler = scheduler
        self._studio = studio
        self.setFixedSize(WINDOW_W, WINDOW_H)
        self.setMouseTracking(False)

        # Cached page background gradient
        bg = QLinearGradient(0, 0, 0, WINDOW_H)
        bg.setColorAt(0.0, QColor(COL_BG_TOP))
        bg.setColorAt(0.5, QColor(COL_BG_MID))
        bg.setColorAt(1.0, QColor(COL_BG_BOT))
        self._bg = bg

        # Cached title fonts (page-level)
        self._font_title    = inter(44, QFont.Weight.Black, letter_spacing=-1.5)
        self._font_subtitle = inter(14, QFont.Weight.Medium, letter_spacing=-0.1)
        self._font_version_label = inter(10, QFont.Weight.Bold, letter_spacing=0.3)
        self._font_version_dot   = inter(10, QFont.Weight.Bold)
        self._font_version_value = mono(10, bold=False, letter_spacing=0.3)
        self._font_version_meta  = inter(10, QFont.Weight.Medium, letter_spacing=0.3)
        self._font_settings_gear = inter(14, QFont.Weight.Bold)
        self._font_settings_lbl  = inter(11, QFont.Weight.Bold, letter_spacing=-0.1)

        # Track program start for uptime string
        self._program_start = time.time()

        # ── Header ────────────────────────────────────────────────────
        self._header = _Header(self)
        self._header.move(0, 0)
        self._header.libraries_clicked.connect(
            lambda: self.screen_requested.emit("libraries"))
        self._header.settings_clicked.connect(
            lambda: self.screen_requested.emit("settings"))
        self._header.ai_magic_clicked.connect(
            lambda: self.screen_requested.emit("ai_magic"))
        self._header.studio_open_clicked.connect(
            lambda: self.screen_requested.emit("studio_open"))

        # ── Live Time Pill (top-right of body) ─────────────────────────
        self._live_pill = _LiveTimePill(self)
        self._live_pill.move(1240, 136)

        # ── Tiles ─────────────────────────────────────────────────────
        self._tiles: dict[str, _TileCard] = {}
        # Left column at x=56, vertical spacing 18 (96 + 18 = 114px stride)
        for i, spec in enumerate(_TILE_SPECS_LEFT):
            tile = _TileCard(spec, parent=self)
            tile.move(56, 230 + i * 114)
            tile.clicked.connect(self.screen_requested.emit)
            self._tiles[spec.key] = tile
        # Right column top tiles at x=732
        # Final Log Creator at y=230, Log Viewer at y=458 (per Figma)
        self._tiles[_TILE_SPECS_RIGHT_TOP[0].key] = _TileCard(_TILE_SPECS_RIGHT_TOP[0], self)
        self._tiles[_TILE_SPECS_RIGHT_TOP[0].key].move(732, 230)
        self._tiles[_TILE_SPECS_RIGHT_TOP[1].key] = _TileCard(_TILE_SPECS_RIGHT_TOP[1], self)
        self._tiles[_TILE_SPECS_RIGHT_TOP[1].key].move(732, 458)
        for spec in _TILE_SPECS_RIGHT_TOP:
            self._tiles[spec.key].clicked.connect(self.screen_requested.emit)

        # ── Studio Launcher ───────────────────────────────────────────
        self._launcher = _StudioLauncher(self)
        self._launcher.move(732, 600)
        self._launcher.clicked.connect(
            lambda: self.screen_requested.emit("studio_open"))
        self._launcher.go_live_clicked.connect(
            lambda: self.screen_requested.emit("studio_open"))

        # ── Status footer ─────────────────────────────────────────────
        self._footer = _StatusFooter(self)
        self._footer.move(56, 800)

        # ── 1Hz tick (single timer for all live updates) ──────────────
        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._on_tick)
        self._tick.start()
        self._on_tick()    # initial paint with real values

        # ── Wire scheduler engine state ───────────────────────────────
        self._on_scheduler_state(False)
        if self._scheduler is not None:
            try:
                self._scheduler.started.connect(
                    lambda: self._on_scheduler_state(True))
                self._scheduler.stopped.connect(
                    lambda: self._on_scheduler_state(False))
                # Initial state — engine may already be running
                if hasattr(self._scheduler, "is_running"):
                    self._on_scheduler_state(bool(self._scheduler.is_running()))
            except Exception as exc:
                log.debug(f"scheduler signal hookup failed: {exc}")

        log.info("SchedulingHub ready (Figma 231:3 — Premium Dark)")

    # ── Public ─────────────────────────────────────────────────────────

    def set_studio(self, studio) -> None:
        """Inject Studio reference after construction (MainWindow may
        construct hub before Studio in some startup orders)."""
        self._studio = studio

    # ── Engine wiring ─────────────────────────────────────────────────

    def _on_scheduler_state(self, running: bool) -> None:
        """Flip the footer + station-card pulse based on engine state."""
        self._header.station_card.set_pulse(running)
        if running:
            self._footer.set_state(
                True, "SYSTEM HEALTHY",
                "Everything running smoothly. No problems.")
        else:
            self._footer.set_state(
                False, "ENGINE STOPPED",
                "Click any tile to start scheduling.")

    # ── 1Hz tick ──────────────────────────────────────────────────────

    def _on_tick(self) -> None:
        from datetime import datetime
        now = datetime.now()
        # Header time (HH:MM + :SS) + day + date
        # Use manual day formatting — Windows lacks strftime("%-d").
        date_str = f"{now.strftime('%B').upper()} {now.day}, {now.year}"
        self._header.set_time(
            now.strftime("%H:%M"),
            now.strftime(":%S"),
            now.strftime("%A").upper(),
            date_str,
        )
        # Live pill clock
        self._live_pill.set_clock_text(now.strftime("%H:%M:%S"))
        # Footer uptime
        elapsed = int(time.time() - self._program_start)
        if elapsed < 60:
            self._footer.set_uptime("Program start up just now")
        else:
            mins = elapsed // 60
            self._footer.set_uptime(
                f"Program running {mins} minute{'s' if mins != 1 else ''}")
        # Station card pulse animation phase (0..1)
        phase = (elapsed % 2) / 2.0
        self._header.station_card.tick_pulse(phase)
        # Studio now-playing poll
        track_title = "—"
        track_meta = "Studio idle"
        if self._studio is not None:
            try:
                cur = getattr(self._studio, "_current_track", None)
                if cur:
                    title = cur.get("title") or "—"
                    artist = cur.get("artist") or ""
                    track_title = f"{title} — {artist}" if artist else title
                    track_meta = "On air now"
            except Exception:
                pass
        self._launcher.set_now_playing(track_title, track_meta)

    # ── Footer click (Settings) ───────────────────────────────────────

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() != Qt.MouseButton.LeftButton:
            return
        # Settings link at right of version row (1319, 870 .. 1390, 884)
        if QRect(1310, 866, 90, 18).contains(e.pos()):
            self.screen_requested.emit("settings")
            return

    # ── Page paint (gradient bg + hairline + version row) ─────────────

    def paintEvent(self, evt):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Page gradient
        p.fillRect(self.rect(), QBrush(self._bg))
        # Title block (page-level)
        p.setPen(QColor(COL_TEXT_PRIMARY))
        p.setFont(self._font_title)
        p.drawText(QRectF(56, 124, 600, 56),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "Scheduling")
        p.setPen(QColor(COL_TEXT_SECONDARY))
        p.setFont(self._font_subtitle)
        p.drawText(QRectF(56, 184, 700, 18),
                   Qt.AlignmentFlag.AlignLeft,
                   "Build clocks, schedule rotations, and shape the day's broadcast")
        # Footer hairline at y=856 — soft gradient transparent → 0.06 → transparent
        hl = QLinearGradient(56, 0, 56 + 1328, 0)
        hl.setColorAt(0.0, QColor(255, 255, 255, 0))
        hl.setColorAt(0.5, QColor(255, 255, 255, int(0.06 * 255)))
        hl.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.fillRect(QRectF(56, 856, 1328, 1), QBrush(hl))
        # Version row at y=872
        p.setPen(QColor(COL_TEXT_MUTED))
        p.setFont(self._font_version_label)
        p.drawText(QRectF(56, 868, 200, 14),
                   Qt.AlignmentFlag.AlignLeft, "RadioAI Studio Pro")
        p.setPen(QColor(COL_TEXT_DIM))
        p.setFont(self._font_version_dot)
        p.drawText(QRectF(162, 868, 6, 14),
                   Qt.AlignmentFlag.AlignLeft, "•")
        p.setPen(QColor(COL_TEXT_MUTED))
        p.setFont(self._font_version_value)
        p.drawText(QRectF(177, 868, 60, 14),
                   Qt.AlignmentFlag.AlignLeft, "v2.0.0")
        p.setPen(QColor(COL_TEXT_DIM))
        p.setFont(self._font_version_dot)
        p.drawText(QRectF(225, 868, 6, 14),
                   Qt.AlignmentFlag.AlignLeft, "•")
        # Uptime mirror text (the footer has its own; this row just hints)
        p.setPen(QColor(COL_TEXT_MUTED))
        p.setFont(self._font_version_meta)
        elapsed = int(time.time() - self._program_start)
        mins = max(1, elapsed // 60)
        p.drawText(QRectF(240, 868, 300, 14),
                   Qt.AlignmentFlag.AlignLeft,
                   f"Program running {mins} minute{'s' if mins != 1 else ''}")
        # Settings link at right
        p.setPen(QColor(COL_PURPLE))
        p.setFont(self._font_settings_gear)
        p.drawText(QRectF(1314, 866, 18, 18),
                   Qt.AlignmentFlag.AlignLeft, "⚙")
        p.setPen(QColor(COL_PURPLE))
        p.setFont(self._font_settings_lbl)
        p.drawText(QRectF(1334, 868, 60, 14),
                   Qt.AlignmentFlag.AlignLeft, "Settings")
