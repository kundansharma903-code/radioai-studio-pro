"""
Premium-theme app chrome — Header + LiveTimePill + helpers.

These are the reusable layout primitives shared across every premium
theme screen (started in scheduling_hub Figma 231:3, extracted here so
playlists / final_log / log_viewer / etc. can mount the same surface).

What's in here:
- ``drop_shadow(blur, color, dy)``       — QGraphicsDropShadowEffect helper
- ``Header``                             — full top bar (88h)
  - ``_Logo``                            — 52×52 purple gradient + 5 bars
  - ``_ActiveStationCard``               — KISS FM 91.5 card with pulse
  - ``_OpenStudioHeaderButton``          — 200×52 purple CTA
- ``LiveTimePill``                       — 144×44 rose pill with mono clock

Header signals:
  libraries_clicked / settings_clicked / ai_magic_clicked / studio_open_clicked

Header API:
  ``set_time(hhmm, ss, day, date)``      — push live-clock state
  ``station_card`` (property)            — for callers that want to drive
                                           the pulse based on engine state

LiveTimePill API:
  ``set_clock_text(text)``               — update HH:MM:SS

The Header keeps "Scheduling" hardcoded as the active tab — every
premium screen built so far lives in the Scheduling section. Future
sections will get a tab parameter when they land.
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, QRect, QRectF, QPointF, pyqtSignal
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QLinearGradient, QFont, QCursor,
    QMouseEvent, QPainterPath,
)
from PyQt6.QtWidgets import (
    QWidget, QGraphicsDropShadowEffect,
)

from core.settings import Settings
from ui.widgets.tokens import (
    inter, mono,
    COL_TEXT_PRIMARY, COL_TEXT_SECONDARY, COL_TEXT_MUTED,
    COL_CYAN, COL_PURPLE, COL_GREEN, COL_PINK,
    COL_PURPLE_DEEP, COL_PURPLE_MID,
    COL_BORDER_FAINT,
    qcolor_a,
)


# ── Layout (full design canvas) ──────────────────────────────────────────

WINDOW_W = 1440
HEADER_H = 88


# ── Helper ───────────────────────────────────────────────────────────────

def drop_shadow(blur: int, color: QColor, dy: int = 0
                ) -> QGraphicsDropShadowEffect:
    """Quick QGraphicsDropShadowEffect factory matching Figma offsets."""
    eff = QGraphicsDropShadowEffect()
    eff.setBlurRadius(blur)
    eff.setOffset(0, dy)
    eff.setColor(color)
    return eff


# ════════════════════════════════════════════════════════════════════════
# LOGO — 52×52 purple gradient with 5 white waveform bars
# ════════════════════════════════════════════════════════════════════════

class _Logo(QWidget):
    BAR_HEIGHTS = (6, 14, 22, 14, 6)   # Figma 231:9..13

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(52, 52)
        self.setGraphicsEffect(drop_shadow(24, qcolor_a("#7c3aed", 0.40), dy=8))

        g = QLinearGradient(0, 0, 52, 52)   # 135deg
        g.setColorAt(0.00, qcolor_a("#a78bfa", 1.0))
        g.setColorAt(0.25, qcolor_a("#7c3aed", 1.0))
        g.setColorAt(0.50, qcolor_a("#5b21b6", 1.0))
        g.setColorAt(1.00, qcolor_a("#5b21b6", 1.0))
        self._grad = g

        gh = QLinearGradient(0, 0, 0, 26)
        gh.setColorAt(0.0, QColor(255, 255, 255, 38))
        gh.setColorAt(1.0, QColor(255, 255, 255, 0))
        self._highlight = gh

        self._bar = QColor(255, 255, 255, int(0.95 * 255))

    def paintEvent(self, evt):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, 52, 52), 14, 14)
        p.fillPath(path, QBrush(self._grad))
        path_top = QPainterPath()
        path_top.addRoundedRect(QRectF(0, 0, 52, 26), 14, 14)
        p.setClipPath(path)
        p.fillPath(path_top, QBrush(self._highlight))
        p.setClipping(False)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self._bar)
        for i, h in enumerate(self.BAR_HEIGHTS):
            x = 8 + i * 8
            y = (52 - h) // 2
            p.drawRoundedRect(QRectF(x, y, 4, h), 2, 2)


# ════════════════════════════════════════════════════════════════════════
# LIVE TIME PILL — 144×44 rose-tinted pill: pulse dot + LIVE + mono clock
# ════════════════════════════════════════════════════════════════════════

class LiveTimePill(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(144, 44)
        self.setGraphicsEffect(drop_shadow(16, qcolor_a("#f43f5e", 0.20), dy=4))

        self._clock_text = "00:00:00"

        # Body gradient — dark red translucent
        g = QLinearGradient(0, 0, 144, 44)
        g.setColorAt(0.0, QColor(127, 29, 29, int(0.40 * 255)))
        g.setColorAt(0.5, QColor(69, 10, 10,  int(0.40 * 255)))
        g.setColorAt(1.0, QColor(69, 10, 10,  int(0.40 * 255)))
        self._grad = g

        self._border    = qcolor_a("#f43f5e", 0.30)
        self._dot_outer = qcolor_a("#f43f5e", 0.45)
        self._dot_inner = QColor("#f43f5e")
        self._font_live  = inter(11, QFont.Weight.Black, letter_spacing=1.5)
        self._font_clock = mono(13, bold=True)

    def set_clock_text(self, t: str) -> None:
        if t != self._clock_text:
            self._clock_text = t
            self.update(QRect(60, 8, 80, 28))

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
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self._dot_outer); p.drawEllipse(QRectF(11, 14, 14, 14))
        p.setBrush(self._dot_inner); p.drawEllipse(QRectF(14, 17, 8, 8))
        p.setPen(QColor("#f43f5e"))
        p.setFont(self._font_live)
        p.drawText(QRectF(30, 11, 36, 18),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "LIVE")
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
        self._pulse_state = 0.0

        g = QLinearGradient(0, 0, 220, 60)
        g.setColorAt(0.0, qcolor_a(COL_GREEN, 0.12))
        g.setColorAt(0.5, qcolor_a(COL_GREEN, 0.04))
        g.setColorAt(1.0, qcolor_a(COL_GREEN, 0.04))
        self._grad = g

        ag = QLinearGradient(0, 0, 0, 60)
        ag.setColorAt(0.0, QColor(COL_GREEN))
        ag.setColorAt(1.0, QColor(COL_CYAN))
        self._accent = ag

        self._border    = qcolor_a(COL_GREEN, 0.25)
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
        if not self._pulse_on:
            return
        self._pulse_state = phase01
        self.update(QRect(188, 19, 22, 22))

    def paintEvent(self, evt):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, 220, 60), 12, 12)
        p.fillPath(path, QBrush(self._grad))
        p.setPen(QPen(self._border, 1))
        p.setBrush(Qt.BrushStyle.NoBrush); p.drawPath(path)
        p.setClipPath(path)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(self._accent))
        p.drawRect(QRectF(0, 0, 4, 60))
        p.setClipping(False)
        p.setPen(QColor(COL_GREEN))
        p.setFont(self._font_label)
        p.drawText(QRectF(12, 6, 200, 12),
                   Qt.AlignmentFlag.AlignLeft, "ACTIVE STATION")
        p.setPen(QColor(COL_TEXT_PRIMARY))
        p.setFont(self._font_name)
        p.drawText(QRectF(12, 21, 200, 18),
                   Qt.AlignmentFlag.AlignLeft, Settings().station_display)
        p.setPen(QColor(COL_TEXT_SECONDARY))
        p.setFont(self._font_city)
        p.drawText(QRectF(12, 40, 200, 14),
                   Qt.AlignmentFlag.AlignLeft, "Jaipur, Rajasthan")
        if self._pulse_on:
            halo_r = 5 + int(self._pulse_state * 4)
            halo_c = QColor(self._dot_glow)
            halo_c.setAlphaF(0.45 * (1.0 - self._pulse_state))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(halo_c); p.drawEllipse(QPointF(198, 30), halo_r, halo_r)
            p.setBrush(self._dot_color); p.drawEllipse(QRectF(193, 25, 10, 10))
        else:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(COL_TEXT_MUTED))
            p.drawEllipse(QRectF(193, 25, 10, 10))


# ════════════════════════════════════════════════════════════════════════
# OPEN STUDIO HEADER BUTTON — 200×52 purple CTA
# ════════════════════════════════════════════════════════════════════════

class _OpenStudioHeaderButton(QWidget):
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(200, 52)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setGraphicsEffect(drop_shadow(28, qcolor_a("#7c3aed", 0.50), dy=8))
        self._hover = False

        g = QLinearGradient(0, 0, 200, 52)
        g.setColorAt(0.00, qcolor_a("#a78bfa", 1.0))
        g.setColorAt(0.25, qcolor_a("#8b5cf6", 1.0))
        g.setColorAt(0.50, qcolor_a("#7c3aed", 1.0))
        g.setColorAt(1.00, qcolor_a("#7c3aed", 1.0))
        self._grad = g

        hg = QLinearGradient(0, 0, 0, 26)
        hg.setColorAt(0.0, QColor(255, 255, 255, int(0.15 * 255)))
        hg.setColorAt(1.0, QColor(255, 255, 255, 0))
        self._highlight = hg

        self._font_play  = inter(11, QFont.Weight.Bold)
        self._font_label = inter(14, QFont.Weight.Bold, letter_spacing=-0.2)
        self._font_sub   = inter(8, QFont.Weight.DemiBold, letter_spacing=1.8)

    def enterEvent(self, e):
        self._hover = True; self.update(self.rect())

    def leaveEvent(self, e):
        self._hover = False; self.update(self.rect())

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def paintEvent(self, evt):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, 200, 52), 14, 14)
        p.fillPath(path, QBrush(self._grad))
        if self._hover:
            p.fillPath(path, QColor(255, 255, 255, int(0.06 * 255)))
        p.setClipPath(path)
        path_h = QPainterPath()
        path_h.addRoundedRect(QRectF(1, 1, 198, 24), 14, 14)
        p.fillPath(path_h, QBrush(self._highlight))
        p.setClipping(False)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, int(0.20 * 255)))
        p.drawEllipse(QRectF(16, 14, 24, 24))
        p.setPen(QColor("#ffffff"))
        p.setFont(self._font_play)
        p.drawText(QRectF(16, 14, 24, 24), Qt.AlignmentFlag.AlignCenter, "▶")
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
# HEADER — full top bar (88h)
# ════════════════════════════════════════════════════════════════════════

class Header(QWidget):
    libraries_clicked   = pyqtSignal()
    settings_clicked    = pyqtSignal()
    ai_magic_clicked    = pyqtSignal()
    studio_open_clicked = pyqtSignal()

    NAV_TABS = (
        ("Libraries",  240),
        ("Scheduling", 358),    # active for every premium screen so far
        ("Settings",   478),
        ("AI Magic ✦", 590),
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(WINDOW_W, HEADER_H)
        self.setMouseTracking(False)

        bg = QLinearGradient(0, 0, 0, HEADER_H)
        bg.setColorAt(0.0, QColor(16, 19, 31, int(0.90 * 255)))
        bg.setColorAt(1.0, QColor(10, 12, 22, int(0.90 * 255)))
        self._bg = bg

        ug = QLinearGradient(0, 0, 92, 0)
        ug.setColorAt(0.0, QColor(COL_CYAN))
        ug.setColorAt(0.5, QColor(COL_PURPLE))
        ug.setColorAt(1.0, QColor(COL_PINK))
        self._underline = ug

        hl = QLinearGradient(0, 0, WINDOW_W, 0)
        hl.setColorAt(0.0, QColor(255, 255, 255, 0))
        hl.setColorAt(0.5, QColor(255, 255, 255, int(0.10 * 255)))
        hl.setColorAt(1.0, QColor(255, 255, 255, 0))
        self._hairline = hl

        self._font_brand        = inter(22, QFont.Weight.Black, letter_spacing=-0.5)
        self._font_studio_pro   = inter(9,  QFont.Weight.Bold,   letter_spacing=2.5)
        self._font_subtitle     = inter(8,  QFont.Weight.Medium, letter_spacing=1.5)
        self._font_tab          = inter(14, QFont.Weight.Medium, letter_spacing=-0.2)
        self._font_tab_active   = inter(14, QFont.Weight.Black,  letter_spacing=-0.2)
        self._font_clock_lg     = mono(32, bold=True, letter_spacing=-1.0)
        self._font_clock_sm     = mono(26, bold=True, letter_spacing=-1.0)
        self._font_day          = inter(9, QFont.Weight.Bold,   letter_spacing=2.0)
        self._font_date         = inter(9, QFont.Weight.Medium, letter_spacing=1.0)

        # Live-clock state — updated by Hub/Screen 1Hz timer
        self._time_main = "00:00"
        self._time_sec  = ":00"
        self._day_str   = "MONDAY"
        self._date_str  = "JANUARY 1, 2024"

        self._logo = _Logo(self)
        self._logo.move(28, 18)

        self._station = _ActiveStationCard(self)
        self._station.move(968, 14)

        self._open_studio = _OpenStudioHeaderButton(self)
        self._open_studio.move(1208, 18)
        self._open_studio.clicked.connect(self.studio_open_clicked.emit)

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
                # Scheduling — already active, no-op
                return

    # ── paint ─────────────────────────────────────────────────────────

    def paintEvent(self, evt):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        p.fillRect(rect, QBrush(self._bg))

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

        for label, x in self.NAV_TABS:
            active = (label == "Scheduling")
            p.setPen(QColor(COL_TEXT_PRIMARY if active else COL_TEXT_SECONDARY))
            p.setFont(self._font_tab_active if active else self._font_tab)
            p.drawText(QRectF(x, 32, 120, 20),
                       Qt.AlignmentFlag.AlignLeft, label)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(self._underline))
        path = QPainterPath()
        path.addRoundedRect(QRectF(358, 60, 92, 3), 1.5, 1.5)
        p.fillPath(path, QBrush(self._underline))

        p.setPen(QColor(COL_TEXT_PRIMARY))
        p.setFont(self._font_clock_lg)
        p.drawText(QRectF(740, 12, 100, 42),
                   Qt.AlignmentFlag.AlignLeft, self._time_main)
        p.setPen(QColor(COL_TEXT_MUTED))
        p.setFont(self._font_clock_sm)
        p.drawText(QRectF(832, 18, 60, 38),
                   Qt.AlignmentFlag.AlignLeft, self._time_sec)
        p.setPen(QColor(COL_PURPLE))
        p.setFont(self._font_day)
        p.drawText(QRectF(740, 52, 60, 14),
                   Qt.AlignmentFlag.AlignLeft, self._day_str)
        p.setPen(QColor(COL_TEXT_MUTED))
        p.setFont(self._font_date)
        p.drawText(QRectF(800, 52, 200, 14),
                   Qt.AlignmentFlag.AlignLeft, self._date_str)

        p.fillRect(QRectF(0, 87, WINDOW_W, 1), QBrush(self._hairline))


__all__ = [
    "Header",
    "LiveTimePill",
    "drop_shadow",
    "WINDOW_W",
    "HEADER_H",
]
