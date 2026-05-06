"""
RadioAI Studio Pro — Studio v3 (Figma 312:2 — Premium Jazler Style).

STEP-BY-STEP REBUILD per Plan A (Kavish, 2026-05-06):
  ✅ Step 1: 1920×1080 canvas + new Header
  ✅ Step 2: Master strip (NowPlayer + NextChip + ControlCluster +
             LevelMeters + ClockFace + Wordmark)              ← THIS COMMIT
  □  Step 3: Up Coming queue (rich track cards)
  □  Step 4: Libraries panel (type icons + Action Stack + table + filter)
  □  Step 5: Instant Jingles (6-pad + numeric pad + hotkeys)
  □  Step 6: History panel (12 alternating rows)
  □  Step 7: Next Break + RDS + Problems trio
  □  Step 8: Bottom transport
  □  Step 9: Final assembly + integration

Engine wires preserved verbatim from ``ui/studio_legacy.py`` so the
9 existing tests pass at every step:
  - Constructor: Studio(db, parent=None, engine=None, scheduler=None)
  - State attrs: _queue_songs, _playback_cid, _current_track,
    _loop_enabled, _stop_after_current, _pre_spot_song_id,
    _playback_kind, _playback_campaign_id, _master_volume,
    _fade_out_timer, _current_duration_ms
  - Methods: _on_queue_song_play, _on_engine_playback_ended,
    _compute_next_song, _tags_for_item_type, _derive_tags

Body widgets in this commit are PLACEHOLDER FRAMES — solid dark
rectangles with section labels, replaced widget-by-widget in the
upcoming steps. The Header is the only fully-built widget here.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Optional

from PyQt6.QtCore import (
    Qt, QRect, QRectF, QPoint, QPointF, QTimer, pyqtSignal,
)
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QLinearGradient, QRadialGradient,
    QFont, QMouseEvent, QPaintEvent,
)
from PyQt6.QtWidgets import (
    QWidget, QFrame, QGraphicsDropShadowEffect, QMessageBox,
)

from ui.widgets._tokens import (
    inter, mono,
    BG_BASE, BG_DARK, BG_PANEL, BG_CARD, BG_CARD_DK, BG_ELEVATED,
    TEXT_PRI, TEXT_SEC, TEXT_MUTED, TEXT_DIM,
    CYAN, CYAN_LIGHT,
    PURPLE, PURPLE_LIGHT, PURPLE_DARK,
    GREEN, GREEN_LIGHT,
    AMBER, AMBER_LIGHT,
    RED, RED_LIGHT,
    PINK, PINK_LIGHT,
)

log = logging.getLogger("Studio")

# ── Layout constants (Figma 312:2 — 1920×1080) ───────────────────────────

WINDOW_W = 1920
WINDOW_H = 1080

HEADER_H        = 72         # taller header per Figma (logo + wordmark stack)
MASTER_Y        = 72
MASTER_H        = 96         # master strip below header
BODY_Y          = 172
BODY_H          = 820
BOTTOM_TRANS_Y  = 1000
BOTTOM_TRANS_H  = 80

# Helper formatters (preserved from legacy module)


def _fmt_duration(ms: int) -> str:
    s = max(0, int(ms or 0)) // 1000
    h, rem = divmod(s, 3600)
    m, ss = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{ss:02d}"
    return f"{m}:{ss:02d}"


def _qcolor_a(hex_color: str, alpha: float) -> QColor:
    c = QColor(hex_color)
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


def _drop_shadow(blur: int, color: QColor, dy: int = 0) -> QGraphicsDropShadowEffect:
    eff = QGraphicsDropShadowEffect()
    eff.setBlurRadius(blur)
    eff.setOffset(0, dy)
    eff.setColor(color)
    return eff


# ════════════════════════════════════════════════════════════════════════
# HEADER — 1920 × 72 (Figma 312:2)
#
# Layout — left → right:
#   16    Logo block (44×44 purple gradient with 5 white waveform bars)
#   72    Wordmark stack: "RadioAI" 22pt black + "STUDIO PRO" 9pt purple
#         + "BROADCAST AUTOMATION" 8pt muted
#   Center  Clock "21:55:26" 32pt mono bold + day-of-week + date underneath
#   1080  Active Station card (220×56) — green pulse + KISS FM 91.5 +
#         Jaipur, Rajasthan
#   1320  3 status pills (SIGNAL / STREAM / AUTO) — 64×28 each, gap 8
#   1580  Control Panel button (140×40) — dark with purple chevron
#   1740  Settings cog (32×32 cog glyph)
# ════════════════════════════════════════════════════════════════════════

class _Header(QWidget):
    """Full-width 72h chrome bar matching Figma 312:2 header."""

    control_panel_clicked = pyqtSignal()
    settings_clicked      = pyqtSignal()

    # Clock + status state
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(WINDOW_W, HEADER_H)

        # State driven by Studio's 1Hz tick + engine/scheduler signals
        self._clock_hms   = "00:00:00"
        self._day_text    = ""
        self._date_text   = ""
        self._on_air      = False
        self._auto_mode   = False
        self._signal_ok   = True
        self._stream_ok   = True

        # Cached fonts
        self._font_brand_big = inter(22, QFont.Weight.Black,
                                     letter_spacing=-0.5)
        self._font_brand_sub = inter(9, QFont.Weight.Bold, letter_spacing=2.5)
        self._font_brand_xs  = inter(8, QFont.Weight.Medium, letter_spacing=1.5)
        self._font_clock     = mono(32, bold=True, letter_spacing=-1.0)
        self._font_clock_s   = mono(26, bold=True, letter_spacing=-1.0)
        self._font_day       = inter(9, QFont.Weight.Bold, letter_spacing=2.0)
        self._font_date      = inter(9, QFont.Weight.Medium, letter_spacing=1.0)
        self._font_station_h = inter(8, QFont.Weight.Bold, letter_spacing=1.5)
        self._font_station   = inter(13, QFont.Weight.Bold, letter_spacing=-0.2)
        self._font_station_s = inter(10, QFont.Weight.Medium)
        self._font_pill      = inter(8, QFont.Weight.Bold, letter_spacing=1.5)
        self._font_cp        = inter(11, QFont.Weight.Bold, letter_spacing=0.3)
        self._font_cog       = inter(18, QFont.Weight.Medium)

        # Pre-cached gradients
        self._bg_grad = QLinearGradient(0, 0, self.width(), 0)
        self._bg_grad.setColorAt(0.0, QColor(16, 19, 31, 230))
        self._bg_grad.setColorAt(1.0, QColor(10, 12, 22, 230))

        self._logo_grad = QLinearGradient(0, 0, 44, 44)
        self._logo_grad.setColorAt(0.143, QColor(167, 139, 250))
        self._logo_grad.setColorAt(0.500, QColor(139,  92, 246))
        self._logo_grad.setColorAt(0.857, QColor(124,  58, 237))

        self._cp_grad = QLinearGradient(0, 0, 140, 40)
        self._cp_grad.setColorAt(0.0, QColor(167, 139, 250))
        self._cp_grad.setColorAt(1.0, QColor(124,  58, 237))

        # Hit zones
        self._cp_btn_rect = QRect(WINDOW_W - 180, 16, 140, 40)
        self._cog_rect    = QRect(WINDOW_W - 32 - 4, 20, 32, 32)

    # ── Public API ───────────────────────────────────────────────────────

    def set_clock(self, hms: str, day: str = "", date: str = "") -> None:
        if hms == self._clock_hms and day == self._day_text and date == self._date_text:
            return
        self._clock_hms = hms
        self._day_text = day
        self._date_text = date
        # Repaint just the center clock band
        self.update(QRect(720, 0, 480, HEADER_H))

    def set_on_air(self, on: bool) -> None:
        if on == self._on_air:
            return
        self._on_air = bool(on)
        self.update(self.rect())

    def set_auto_mode(self, on: bool) -> None:
        if on == self._auto_mode:
            return
        self._auto_mode = bool(on)
        # Repaint the AUTO pill region
        self.update(QRect(1320, 12, 280, 32))

    def set_signal(self, ok: bool) -> None:
        if ok == self._signal_ok:
            return
        self._signal_ok = bool(ok)
        self.update(QRect(1320, 12, 90, 32))

    def set_stream(self, ok: bool) -> None:
        if ok == self._stream_ok:
            return
        self._stream_ok = bool(ok)
        self.update(QRect(1410, 12, 90, 32))

    # ── Mouse ────────────────────────────────────────────────────────────

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            p = e.position().toPoint()
            if self._cp_btn_rect.contains(p):
                self.control_panel_clicked.emit()
            elif self._cog_rect.contains(p):
                self.settings_clicked.emit()
        super().mousePressEvent(e)

    # ── Paint ────────────────────────────────────────────────────────────

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Header background gradient
        p.fillRect(self.rect(), QBrush(self._bg_grad))
        # Hairline at bottom
        p.fillRect(QRectF(0, self.height() - 1, self.width(), 1),
                   QColor(255, 255, 255, 18))

        self._paint_logo(p)
        self._paint_wordmark(p)
        self._paint_clock(p)
        self._paint_active_station(p)
        self._paint_status_pills(p)
        self._paint_control_panel_btn(p)
        self._paint_settings_cog(p)

        p.end()

    def _paint_logo(self, p: QPainter) -> None:
        """44×44 purple gradient square at (16, 14) with 5 white waveform
        bars + drop-shadow purple glow per Figma."""
        logo = QRectF(16, 14, 44, 44)
        # Cached gradient (already built)
        # Update gradient stops to match logo position
        grad = QLinearGradient(logo.topLeft(), logo.bottomRight())
        grad.setColorAt(0.143, QColor(167, 139, 250))
        grad.setColorAt(0.500, QColor(139,  92, 246))
        grad.setColorAt(0.857, QColor(124,  58, 237))
        # Drop shadow (drawn first as a slight purple halo)
        halo = QRectF(logo.x() - 4, logo.y() + 2, logo.width() + 8,
                      logo.height() + 8)
        halo_grad = QLinearGradient(halo.topLeft(), halo.bottomLeft())
        halo_grad.setColorAt(0.0, _qcolor_a(PURPLE_DARK, 0.0))
        halo_grad.setColorAt(1.0, _qcolor_a(PURPLE_DARK, 0.4))
        p.setBrush(QBrush(halo_grad)); p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(halo, 14, 14)
        # Logo body
        p.setBrush(QBrush(grad))
        p.drawRoundedRect(logo, 12, 12)
        # 5 vertical waveform bars centered inside
        bar_h = (5, 12, 18, 12, 5)
        for i, h in enumerate(bar_h):
            x = logo.x() + 7 + i * 6
            y = logo.y() + 22 - h / 2
            p.fillRect(QRectF(x, y, 3.5, h),
                       QColor(255, 255, 255, 245))

    def _paint_wordmark(self, p: QPainter) -> None:
        # "RadioAI"
        p.setPen(QColor(TEXT_PRI)); p.setFont(self._font_brand_big)
        p.drawText(QRectF(72, 12, 220, 28),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "RadioAI")
        # "STUDIO PRO"
        p.setPen(QColor(PURPLE_LIGHT)); p.setFont(self._font_brand_sub)
        p.drawText(QRectF(72, 38, 220, 12),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "STUDIO PRO")
        # "BROADCAST AUTOMATION"
        p.setPen(QColor(TEXT_MUTED)); p.setFont(self._font_brand_xs)
        p.drawText(QRectF(72, 52, 240, 12),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "BROADCAST AUTOMATION")

    def _paint_clock(self, p: QPainter) -> None:
        # Clock — split HH:MM (white) + :SS (muted)
        # Center the stack horizontally; Figma places clock around x=860..980
        clock_x = 860
        # Split into HH:MM:SS — last 3 chars are :SS (different color)
        hms = self._clock_hms
        if len(hms) == 8 and hms[2] == ':' and hms[5] == ':':
            hh_mm = hms[:5]    # "21:55"
            ss = hms[5:]       # ":26"
        else:
            hh_mm = hms; ss = ""
        # HH:MM
        p.setPen(QColor(TEXT_PRI)); p.setFont(self._font_clock)
        p.drawText(QRectF(clock_x, 4, 130, 44),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   hh_mm)
        # :SS in muted
        p.setPen(QColor(TEXT_MUTED)); p.setFont(self._font_clock_s)
        p.drawText(QRectF(clock_x + 92, 8, 60, 40),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   ss)
        # Day + date row
        p.setPen(QColor(PURPLE_LIGHT)); p.setFont(self._font_day)
        p.drawText(QRectF(clock_x, 50, 80, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._day_text)
        p.setPen(QColor(TEXT_MUTED)); p.setFont(self._font_date)
        p.drawText(QRectF(clock_x + 80, 50, 200, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._date_text)

    def _paint_active_station(self, p: QPainter) -> None:
        """Active Station card (220×60) at (1080, 8) — green-tinted with
        green-cyan vertical accent + KISS FM 91.5 + Jaipur, Rajasthan +
        green pulse dot."""
        card = QRectF(1080, 8, 220, 56)
        # Subtle green tint background
        bg = QLinearGradient(card.topLeft(), card.topRight())
        bg.setColorAt(0.15, _qcolor_a(GREEN, 0.12))
        bg.setColorAt(0.89, _qcolor_a(GREEN, 0.04))
        p.fillRect(card, QBrush(bg))
        # Border
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_qcolor_a(GREEN, 0.30)))
        p.drawRoundedRect(card.adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)
        # Left vertical accent (green→cyan, 4w)
        accent = QLinearGradient(card.topLeft(), card.bottomLeft())
        accent.setColorAt(0.0, QColor(GREEN))
        accent.setColorAt(1.0, QColor(CYAN))
        p.fillRect(QRectF(card.x(), card.y(), 4, card.height()),
                   QBrush(accent))
        # Header label
        p.setPen(QColor(GREEN_LIGHT)); p.setFont(self._font_station_h)
        p.drawText(QRectF(card.x() + 12, card.y() + 6, 200, 12),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "ACTIVE STATION")
        # Station name
        p.setPen(QColor(TEXT_PRI)); p.setFont(self._font_station)
        p.drawText(QRectF(card.x() + 12, card.y() + 20, 160, 18),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "KISS FM 91.5")
        # Location
        p.setPen(QColor(TEXT_SEC)); p.setFont(self._font_station_s)
        p.drawText(QRectF(card.x() + 12, card.y() + 38, 200, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "Jaipur, Rajasthan")
        # Green pulse dot (right side, vertically centered)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(_qcolor_a(GREEN, 0.4))
        p.drawEllipse(QPointF(card.right() - 18, card.center().y()), 8, 8)
        p.setBrush(QColor(GREEN))
        p.drawEllipse(QPointF(card.right() - 18, card.center().y()), 4, 4)

    def _paint_status_pills(self, p: QPainter) -> None:
        """3 pills SIGNAL / STREAM / AUTO at (1320, 18, 64×28 each, gap 8)."""
        pills = [
            ("SIGNAL", GREEN  if self._signal_ok else RED),
            ("STREAM", GREEN  if self._stream_ok else AMBER),
            ("AUTO",   PURPLE if self._auto_mode else TEXT_MUTED),
        ]
        for i, (label, color) in enumerate(pills):
            x = 1320 + i * 72
            r = QRectF(x, 18, 64, 32)
            p.fillRect(r, _qcolor_a(color, 0.12))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(_qcolor_a(color, 0.40)))
            p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
            # Color dot
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(color))
            p.drawEllipse(QPointF(x + 10, r.center().y()), 3, 3)
            # Label
            p.setPen(QColor(color)); p.setFont(self._font_pill)
            p.drawText(QRectF(x + 18, r.y(), r.width() - 18, r.height()),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       label)

    def _paint_control_panel_btn(self, p: QPainter) -> None:
        """Control Panel button — purple gradient with chevron arrow."""
        cp = QRectF(self._cp_btn_rect)
        grad = QLinearGradient(cp.topLeft(), cp.bottomLeft())
        grad.setColorAt(0.0, QColor(167, 139, 250))
        grad.setColorAt(1.0, QColor(124,  58, 237))
        p.fillRect(cp, QBrush(grad))
        # Inner highlight strip (top sheen)
        sheen = QLinearGradient(cp.topLeft(), QPointF(cp.x(), cp.y() + 16))
        sheen.setColorAt(0.0, QColor(255, 255, 255, 50))
        sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.fillRect(QRectF(cp.x() + 1, cp.y() + 1, cp.width() - 2, 16),
                   QBrush(sheen))
        # Border
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 30)))
        p.drawRoundedRect(cp.adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)
        # Glyph + label
        p.setPen(QColor(255, 255, 255)); p.setFont(self._font_cp)
        p.drawText(cp, Qt.AlignmentFlag.AlignCenter, "‹  Control Panel")

    def _paint_settings_cog(self, p: QPainter) -> None:
        cog = QRectF(self._cog_rect)
        p.setPen(QColor(TEXT_SEC)); p.setFont(self._font_cog)
        p.drawText(cog, Qt.AlignmentFlag.AlignCenter, "⚙")


# ════════════════════════════════════════════════════════════════════════
# NOW PLAYER — 836 × 88 (Figma 343:3, GREEN theme)
#
# Vinyl on left + NOW pill + ● ON AIR · LIVE indicator + track title
# (bold white) + artist · year (muted) + big elapsed time + small total
# + green-bar waveform with played/remaining split + REMAINING amber box
# ════════════════════════════════════════════════════════════════════════

class _NowPlayer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(836, 88)
        self._idle = True
        self._title = "—"
        self._artist_year = ""
        self._elapsed_ms = 0
        self._total_ms = 0
        self._progress = 0.0    # 0..1

        # Pre-cached fonts
        self._font_now      = inter(8, QFont.Weight.Black, letter_spacing=1.6)
        self._font_onair    = inter(9, QFont.Weight.Bold, letter_spacing=1.4)
        self._font_title    = inter(18, QFont.Weight.Black, letter_spacing=-0.3)
        self._font_artist   = inter(11, QFont.Weight.Medium)
        self._font_elapsed  = mono(20, bold=True, letter_spacing=-0.5)
        self._font_total    = mono(11, bold=True)
        self._font_rem_lbl  = inter(7, QFont.Weight.Bold, letter_spacing=1.4)
        self._font_rem_val  = mono(15, bold=True, letter_spacing=-0.3)

        # Pre-cached waveform bars (organic — sine + harmonic envelope)
        import math, random
        rng = random.Random(312)
        bars = []
        for i in range(200):
            t = i / 199
            envelope = 0.45 + 0.45 * math.sin(t * math.pi)
            harmonic = 0.18 * math.sin(t * 22.0)
            jitter = (rng.random() - 0.5) * 0.20
            bars.append(max(0.18, min(1.0, envelope + harmonic + jitter)))
        self._wf_bars = bars

    def set_track(self, title: str, artist_year: str,
                  total_ms: int) -> None:
        self._title = title or "—"
        self._artist_year = artist_year or ""
        self._total_ms = max(0, int(total_ms or 0))
        self._elapsed_ms = 0
        self._progress = 0.0
        self._idle = (title is None or title == "—")
        self.update(self.rect())

    def set_idle(self) -> None:
        self._idle = True
        self._title = "—"
        self._artist_year = ""
        self._total_ms = 0; self._elapsed_ms = 0; self._progress = 0.0
        self.update(self.rect())

    def set_progress(self, pos_ms: int, total_ms: int) -> None:
        self._elapsed_ms = max(0, int(pos_ms or 0))
        self._total_ms = max(0, int(total_ms or 0))
        if self._total_ms > 0:
            self._progress = max(0.0, min(1.0, self._elapsed_ms / self._total_ms))
        # Repaint just the elapsed-time and waveform regions
        self.update(QRect(530, 14, 280, 30))    # elapsed/total/rem block
        self.update(QRect(116, 56, 700, 26))    # waveform

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        # Card background — green-tinted
        bg = QLinearGradient(0, 0, 0, self.height())
        bg.setColorAt(0.0, _qcolor_a(GREEN, 0.10))
        bg.setColorAt(1.0, _qcolor_a(GREEN, 0.04))
        p.fillRect(r, QBrush(bg))
        # Border green
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_qcolor_a(GREEN, 0.30)))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)

        # Vinyl (left, ~80h - centered)
        cx, cy = 56, 44
        rad_outer = 30
        # Outer ring (green)
        for ring_r, alpha in [(rad_outer, 0.85), (rad_outer - 6, 0.55),
                               (rad_outer - 14, 0.30)]:
            grad = QRadialGradient(QPointF(cx, cy), ring_r)
            grad.setColorAt(0.0, _qcolor_a(GREEN_LIGHT, 0.5))
            grad.setColorAt(0.7, _qcolor_a(GREEN, alpha))
            grad.setColorAt(1.0, _qcolor_a(GREEN_LIGHT, 0.6))
            p.setBrush(QBrush(grad)); p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(cx, cy), ring_r, ring_r)
        # Center hole
        p.setBrush(QColor(BG_BASE)); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), 5, 5)
        p.setBrush(QColor(GREEN_LIGHT))
        p.drawEllipse(QPointF(cx, cy), 1.5, 1.5)

        # NOW pill (green) — top-left of text block
        pill = QRectF(108, 12, 48, 18)
        p.fillRect(pill, _qcolor_a(GREEN, 0.30))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_qcolor_a(GREEN, 0.55)))
        p.drawRoundedRect(pill.adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)
        p.setPen(QColor(GREEN_LIGHT)); p.setFont(self._font_now)
        p.drawText(pill, Qt.AlignmentFlag.AlignCenter, "NOW")
        # ● ON AIR · LIVE indicator
        # Green dot
        if not self._idle:
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(GREEN_LIGHT))
            p.drawEllipse(QPointF(166, 21), 4, 4)
            p.setPen(QColor(GREEN_LIGHT)); p.setFont(self._font_onair)
            p.drawText(QRectF(176, 12, 100, 18),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       "ON AIR · LIVE")

        # Track title (white bold, big)
        p.setPen(QColor(TEXT_PRI)); p.setFont(self._font_title)
        p.drawText(QRectF(108, 30, 410, 24),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._title)
        # Artist · year (muted)
        p.setPen(QColor(TEXT_SEC)); p.setFont(self._font_artist)
        p.drawText(QRectF(108, 52, 410, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._artist_year)

        # Elapsed time (mono, big white)
        p.setPen(QColor(TEXT_PRI)); p.setFont(self._font_elapsed)
        p.drawText(QRectF(534, 14, 80, 26),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   _fmt_duration(self._elapsed_ms))
        # / total (smaller muted)
        p.setPen(QColor(TEXT_DIM)); p.setFont(self._font_total)
        p.drawText(QRectF(620, 18, 80, 20),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "/  " + _fmt_duration(self._total_ms))

        # REMAINING box (right, green-tinted box)
        rem_box = QRectF(722, 8, 102, 40)
        p.fillRect(rem_box, _qcolor_a(GREEN, 0.18))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_qcolor_a(GREEN, 0.50)))
        p.drawRoundedRect(rem_box.adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
        p.setPen(QColor(TEXT_DIM)); p.setFont(self._font_rem_lbl)
        p.drawText(QRectF(rem_box.x(), rem_box.y() + 4, rem_box.width(), 12),
                   Qt.AlignmentFlag.AlignCenter, "REMAINING")
        rem_ms = max(0, self._total_ms - self._elapsed_ms)
        p.setPen(QColor(GREEN_LIGHT)); p.setFont(self._font_rem_val)
        p.drawText(QRectF(rem_box.x(), rem_box.y() + 16, rem_box.width(), 22),
                   Qt.AlignmentFlag.AlignCenter, _fmt_duration(rem_ms))

        # Waveform (200 bars, green played-portion + dimmed remaining)
        self._paint_waveform(p)
        p.end()

    def _paint_waveform(self, p: QPainter) -> None:
        wf_x, wf_y, wf_w, wf_h = 108, 64, 712, 18
        bar_count = len(self._wf_bars)
        step = wf_w / bar_count
        bar_w = max(1.4, step - 0.5)
        for i, h_frac in enumerate(self._wf_bars):
            x = wf_x + i * step
            h = wf_h * h_frac
            y = wf_y + (wf_h - h) / 2
            played = (i / bar_count) <= self._progress
            if played:
                # Played portion: bright green→cyan gradient depending on position
                t = i / bar_count
                if t < self._progress * 0.5:
                    color = _qcolor_a(GREEN, 0.9)
                else:
                    color = _qcolor_a(GREEN_LIGHT, 0.95)
            else:
                # Remaining: dim green
                color = _qcolor_a(GREEN, 0.20)
            p.fillRect(QRectF(x, y, bar_w, h), color)
        # Playhead — vertical white line with green glow
        if self._progress > 0:
            ph_x = wf_x + wf_w * self._progress
            playhead = QRectF(ph_x - 1, wf_y - 2, 2, wf_h + 4)
            grad = QLinearGradient(playhead.topLeft(), playhead.bottomLeft())
            grad.setColorAt(0.0, _qcolor_a(GREEN_LIGHT, 0.0))
            grad.setColorAt(0.5, QColor(255, 255, 255))
            grad.setColorAt(1.0, _qcolor_a(GREEN_LIGHT, 0.0))
            p.fillRect(playhead, QBrush(grad))


# ════════════════════════════════════════════════════════════════════════
# NEXT CHIP — 200 × 88 (Figma 344:2, ROSE theme)
# ════════════════════════════════════════════════════════════════════════

class _NextChip(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(200, 88)
        self._title = "—"
        self._artist = ""
        self._to_air_s = 0
        self._intro_s = 0

        self._font_pill   = inter(8, QFont.Weight.Black, letter_spacing=1.6)
        self._font_air_v  = mono(18, bold=True, letter_spacing=-0.5)
        self._font_air_l  = inter(7, QFont.Weight.Bold, letter_spacing=1.4)
        self._font_title  = inter(12, QFont.Weight.Bold, letter_spacing=-0.1)
        self._font_artist = inter(10, QFont.Weight.Medium)
        self._font_intro  = mono(8, bold=True, letter_spacing=0.4)

    def set_next(self, title: str, artist: str, to_air_s: int = 0,
                 intro_s: int = 0) -> None:
        self._title = title or "—"
        self._artist = artist or ""
        self._to_air_s = max(0, int(to_air_s))
        self._intro_s = max(0, int(intro_s))
        self.update(self.rect())

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        # Rose-tinted background
        bg = QLinearGradient(0, 0, 0, self.height())
        bg.setColorAt(0.0, _qcolor_a(RED, 0.10))
        bg.setColorAt(1.0, _qcolor_a(RED, 0.04))
        p.fillRect(r, QBrush(bg))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_qcolor_a(RED, 0.30)))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)
        # NEXT pill
        pill = QRectF(10, 10, 56, 18)
        p.fillRect(pill, _qcolor_a(RED, 0.30))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_qcolor_a(RED, 0.55)))
        p.drawRoundedRect(pill.adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)
        p.setPen(QColor(RED_LIGHT)); p.setFont(self._font_pill)
        p.drawText(pill, Qt.AlignmentFlag.AlignCenter, "NEXT")
        # TO AIR countdown (right side of top row)
        air_text = "—" if self._to_air_s == 0 else f"{self._to_air_s:02d}s"
        p.setPen(QColor(TEXT_PRI)); p.setFont(self._font_air_v)
        p.drawText(QRectF(self.width() - 80, 6, 70, 22),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   air_text)
        p.setPen(QColor(RED_LIGHT)); p.setFont(self._font_air_l)
        p.drawText(QRectF(self.width() - 80, 26, 70, 12),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   "TO AIR")
        # Divider
        p.fillRect(QRectF(10, 42, self.width() - 20, 1),
                   _qcolor_a(RED, 0.20))
        # Title
        p.setPen(QColor(TEXT_PRI)); p.setFont(self._font_title)
        p.drawText(QRectF(10, 46, self.width() - 20, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._title)
        # Artist
        p.setPen(QColor(RED_LIGHT)); p.setFont(self._font_artist)
        p.drawText(QRectF(10, 62, 100, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._artist)
        # INTRO badge bottom-right
        if self._intro_s > 0:
            badge = QRectF(self.width() - 76, 64, 66, 18)
            p.fillRect(badge, _qcolor_a(AMBER, 0.20))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(_qcolor_a(AMBER, 0.45)))
            p.drawRoundedRect(badge.adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)
            p.setPen(QColor(AMBER_LIGHT)); p.setFont(self._font_intro)
            p.drawText(badge, Qt.AlignmentFlag.AlignCenter,
                       f"INTRO {self._intro_s:.1f}s")
        p.end()


# ════════════════════════════════════════════════════════════════════════
# CONTROL CLUSTER — 296 × 80 (Figma 344:12, 4 buttons)
# Restart cyan / Loop purple / Pause amber (active) / StopNext rose
# ════════════════════════════════════════════════════════════════════════

class _ControlButton(QWidget):
    """One chunky button: icon + label below. Variants by accent color."""

    clicked = pyqtSignal()

    def __init__(self, label: str, glyph: str, accent: str, parent=None):
        super().__init__(parent)
        self.setFixedSize(70, 70)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._label = label; self._glyph = glyph
        self._accent = accent
        self._active = False
        self._enabled = True
        self._hover = False
        self._font_glyph = inter(22, QFont.Weight.Black)
        self._font_label = inter(9, QFont.Weight.Bold, letter_spacing=0.4)

    def set_active(self, on: bool) -> None:
        if on == self._active:
            return
        self._active = bool(on)
        self.update(self.rect())

    def set_enabled(self, on: bool) -> None:
        self._enabled = bool(on)
        self.setCursor(Qt.CursorShape.PointingHandCursor if on
                       else Qt.CursorShape.ForbiddenCursor)
        self.update(self.rect())

    def enterEvent(self, e):
        if self._enabled and not self._hover:
            self._hover = True; self.update(self.rect())
        super().enterEvent(e)

    def leaveEvent(self, e):
        if self._hover:
            self._hover = False; self.update(self.rect())
        super().leaveEvent(e)

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if self._enabled and e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        if self._active:
            grad = QLinearGradient(0, 0, 0, self.height())
            grad.setColorAt(0.0, _qcolor_a(self._accent, 0.95))
            grad.setColorAt(1.0, _qcolor_a(self._accent, 0.55))
            p.fillRect(r, QBrush(grad))
            text_color = QColor(255, 255, 255)
        else:
            alpha = 0.22 if (self._hover and self._enabled) else 0.10
            if not self._enabled:
                alpha = 0.05
            p.fillRect(r, _qcolor_a(self._accent, alpha))
            text_color = (_qcolor_a(self._accent, 0.95) if self._enabled
                          else _qcolor_a(self._accent, 0.30))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_qcolor_a(self._accent,
                                0.5 if self._enabled else 0.18)))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        # Glyph
        p.setPen(text_color); p.setFont(self._font_glyph)
        p.drawText(QRectF(0, 8, self.width(), 32),
                   Qt.AlignmentFlag.AlignCenter, self._glyph)
        # Label
        p.setFont(self._font_label)
        p.drawText(QRectF(0, 44, self.width(), 18),
                   Qt.AlignmentFlag.AlignCenter, self._label)
        p.end()


class _ControlCluster(QWidget):
    restart_clicked   = pyqtSignal()
    loop_toggled      = pyqtSignal(bool)
    pause_clicked     = pyqtSignal()
    stop_next_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(296, 80)
        self._loop_on = False
        self._paused = False

        self._b_restart = _ControlButton("Restart", "↺", CYAN, self)
        self._b_restart.move(2, 5)
        self._b_restart.clicked.connect(self.restart_clicked.emit)

        self._b_loop = _ControlButton("Loop", "↻", PURPLE_LIGHT, self)
        self._b_loop.move(76, 5)
        self._b_loop.clicked.connect(self._on_loop)

        self._b_pause = _ControlButton("Pause", "⏸", AMBER, self)
        self._b_pause.move(150, 5)
        self._b_pause.clicked.connect(self.pause_clicked.emit)

        self._b_stop = _ControlButton("StopNext", "⏭", RED, self)
        self._b_stop.move(224, 5)
        self._b_stop.clicked.connect(self.stop_next_clicked.emit)

    def _on_loop(self) -> None:
        self._loop_on = not self._loop_on
        self._b_loop.set_active(self._loop_on)
        self.loop_toggled.emit(self._loop_on)

    def set_paused(self, on: bool) -> None:
        self._paused = bool(on)
        self._b_pause.set_active(self._paused)

    def set_idle(self, idle: bool) -> None:
        for b in (self._b_restart, self._b_pause, self._b_stop):
            b.set_enabled(not idle)


# ════════════════════════════════════════════════════════════════════════
# LEVEL METERS — 80 × 80 (vertical L/R VU)
# ════════════════════════════════════════════════════════════════════════

class _LevelMeters(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(80, 80)
        self._left = 0.0
        self._right = 0.0
        self._peak_l = 0.0
        self._peak_r = 0.0
        self._font = inter(7, QFont.Weight.Bold, letter_spacing=1.2)
        self._anim = QTimer(self)
        self._anim.setInterval(33)    # ~30Hz
        self._anim.timeout.connect(self._tick)
        self._anim.start()

    def _tick(self) -> None:
        # Decorative idle decay (until engine RMS signal lands)
        self._left = max(0.0, self._left - 0.04)
        self._right = max(0.0, self._right - 0.04)
        self._peak_l = max(self._left, self._peak_l - 0.01)
        self._peak_r = max(self._right, self._peak_r - 0.01)
        self.update(self.rect())

    def set_levels(self, left: float, right: float) -> None:
        self._left = max(0.0, min(1.0, float(left)))
        self._right = max(0.0, min(1.0, float(right)))
        if self._left > self._peak_l: self._peak_l = self._left
        if self._right > self._peak_r: self._peak_r = self._right
        self.update(self.rect())

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        # Dark card
        p.fillRect(r, QColor(7, 9, 18, 200))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 18)))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        # Two columns
        col_w = 26; gap = 6
        col_x_l = 12
        col_x_r = col_x_l + col_w + gap
        col_y = 8
        col_h = self.height() - 24
        # Backgrounds
        p.fillRect(QRectF(col_x_l, col_y, col_w, col_h), QColor(0, 0, 0, 120))
        p.fillRect(QRectF(col_x_r, col_y, col_w, col_h), QColor(0, 0, 0, 120))
        # Fills (bottom-up)
        for cx, level, peak in (
                (col_x_l, self._left, self._peak_l),
                (col_x_r, self._right, self._peak_r)):
            fill_h = col_h * level
            grad = QLinearGradient(0, col_y, 0, col_y + col_h)
            grad.setColorAt(0.0, QColor(RED))
            grad.setColorAt(0.4, QColor(AMBER))
            grad.setColorAt(1.0, QColor(GREEN))
            p.fillRect(QRectF(cx, col_y + col_h - fill_h, col_w, fill_h),
                       QBrush(grad))
            # Peak hold tick (2h white)
            if peak > 0:
                py = col_y + col_h - col_h * peak
                p.fillRect(QRectF(cx, py - 1, col_w, 2),
                           QColor(255, 255, 255, 220))
        # L / R labels
        p.setPen(QColor(TEXT_DIM)); p.setFont(self._font)
        p.drawText(QRectF(col_x_l, col_y + col_h + 2, col_w, 14),
                   Qt.AlignmentFlag.AlignCenter, "L")
        p.drawText(QRectF(col_x_r, col_y + col_h + 2, col_w, 14),
                   Qt.AlignmentFlag.AlignCenter, "R")
        p.end()


# ════════════════════════════════════════════════════════════════════════
# CLOCK FACE — 80 × 80 (analog wall clock, 1Hz wall-clock tick)
# ════════════════════════════════════════════════════════════════════════

class _AnalogClock(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(80, 80)
        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(1000)
        self._tick_timer.timeout.connect(lambda: self.update(self.rect()))
        self._tick_timer.start()

    def paintEvent(self, e: QPaintEvent) -> None:
        import math
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        # Card background
        p.fillRect(r, QColor(7, 9, 18, 200))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 18)))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 40, 40)
        cx, cy = self.width() / 2, self.height() / 2
        rad = 32
        # 12 ticks (4 major + 8 minor)
        for i in range(12):
            angle = math.radians(90 - i * 30)
            r_in = rad - (8 if i % 3 == 0 else 5)
            r_out = rad - 1
            x1 = cx + r_in * math.cos(angle)
            y1 = cy - r_in * math.sin(angle)
            x2 = cx + r_out * math.cos(angle)
            y2 = cy - r_out * math.sin(angle)
            p.setPen(QPen(QColor(255, 255, 255, 100 if i % 3 == 0 else 50),
                          1.8 if i % 3 == 0 else 1.0))
            p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
        # Hands
        now = datetime.now()
        h = now.hour % 12; m = now.minute; s = now.second
        # Hour hand (cyan, shorter)
        h_angle = math.radians(90 - (h * 30 + m * 0.5))
        p.setPen(QPen(QColor(CYAN_LIGHT), 2.5))
        p.drawLine(QPointF(cx, cy),
                   QPointF(cx + 14 * math.cos(h_angle),
                           cy - 14 * math.sin(h_angle)))
        # Minute hand (cyan, longer)
        m_angle = math.radians(90 - m * 6 - s * 0.1)
        p.setPen(QPen(QColor(CYAN), 2.0))
        p.drawLine(QPointF(cx, cy),
                   QPointF(cx + 24 * math.cos(m_angle),
                           cy - 24 * math.sin(m_angle)))
        # Center cyan dot with glow
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(_qcolor_a(CYAN, 0.4))
        p.drawEllipse(QPointF(cx, cy), 5, 5)
        p.setBrush(QColor(CYAN_LIGHT))
        p.drawEllipse(QPointF(cx, cy), 2.5, 2.5)
        p.end()


# ════════════════════════════════════════════════════════════════════════
# WORDMARK — 320 × 80 (STUDIO PRO + cyan→purple→pink accent + MIC pill)
# ════════════════════════════════════════════════════════════════════════

class _Wordmark(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(320, 80)
        self._font_big   = inter(28, QFont.Weight.Black, letter_spacing=-0.8)
        self._font_sub   = inter(8, QFont.Weight.Bold, letter_spacing=2.8)
        self._font_pill  = inter(8, QFont.Weight.Bold, letter_spacing=1.6)

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        # Dark card
        bg = QLinearGradient(0, 0, 0, self.height())
        bg.setColorAt(0.0, QColor(14, 16, 32, 230))
        bg.setColorAt(1.0, QColor(7, 9, 18, 230))
        p.fillRect(r, QBrush(bg))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 18)))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)
        # cyan→purple→pink accent line (top, 2px)
        accent = QLinearGradient(0, 0, self.width(), 0)
        accent.setColorAt(0.0, QColor(CYAN))
        accent.setColorAt(0.5, QColor(PURPLE_LIGHT))
        accent.setColorAt(1.0, QColor(PINK))
        p.fillRect(QRectF(8, 4, self.width() - 16, 2), QBrush(accent))
        # STUDIO wordmark
        p.setPen(QColor(TEXT_PRI)); p.setFont(self._font_big)
        p.drawText(QRectF(16, 14, 220, 40),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "STUDIO")
        # PRO BROADCAST
        p.setPen(QColor(PURPLE_LIGHT)); p.setFont(self._font_sub)
        p.drawText(QRectF(16, 50, 220, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "PRO BROADCAST")
        # MIC OFF pill (right side, vertically centered)
        pill = QRectF(self.width() - 76, 30, 60, 22)
        p.fillRect(pill, _qcolor_a(TEXT_DIM, 0.30))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_qcolor_a(TEXT_DIM, 0.50)))
        p.drawRoundedRect(pill.adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
        p.setPen(QColor(TEXT_SEC)); p.setFont(self._font_pill)
        p.drawText(pill, Qt.AlignmentFlag.AlignCenter, "MIC OFF")
        p.end()


# ════════════════════════════════════════════════════════════════════════
# PLACEHOLDER widgets — solid frames with section labels.
# Replaced widget-by-widget in subsequent steps.
# ════════════════════════════════════════════════════════════════════════

class _PlaceholderFrame(QWidget):
    """Solid dark-tinted rectangle with a section label — temporary
    visual marker until the real widget lands in its scheduled step."""

    def __init__(self, label: str, step_n: str, w: int, h: int,
                 accent: str = TEXT_DIM, parent=None):
        super().__init__(parent)
        self.setFixedSize(w, h)
        self._label = label
        self._step = step_n
        self._accent = accent
        self._font_label = inter(13, QFont.Weight.Black, letter_spacing=0.5)
        self._font_step  = inter(9, QFont.Weight.Bold, letter_spacing=1.4)

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        # Background
        bg = QLinearGradient(0, 0, 0, self.height())
        bg.setColorAt(0.0, QColor(14, 16, 32, 230))
        bg.setColorAt(1.0, QColor(7, 9, 18, 230))
        p.fillRect(r, QBrush(bg))
        # Border
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_qcolor_a(self._accent, 0.30)))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)
        # Label
        p.setPen(_qcolor_a(self._accent, 0.85))
        p.setFont(self._font_label)
        p.drawText(QRectF(0, self.height() / 2 - 24, self.width(), 24),
                   Qt.AlignmentFlag.AlignCenter, self._label)
        # Step indicator
        p.setPen(_qcolor_a(self._accent, 0.55))
        p.setFont(self._font_step)
        p.drawText(QRectF(0, self.height() / 2 + 4, self.width(), 14),
                   Qt.AlignmentFlag.AlignCenter, self._step)
        p.end()


# ════════════════════════════════════════════════════════════════════════
# STUDIO — the screen shell
# ════════════════════════════════════════════════════════════════════════

class Studio(QWidget):
    """Premium broadcast Studio (Figma 312:2).

    Step 1 of the rebuild — Header is the only fully-built widget;
    every other body region is a placeholder until its scheduled step.
    Engine + scheduler wires + EOS path logic preserved verbatim from
    studio_legacy.py so all 9 existing Studio tests keep passing."""

    breadcrumb_clicked = pyqtSignal(str)
    screen_requested   = pyqtSignal(str)

    DEFAULT_VOLUME = 85
    FADE_OUT_MS = 3000

    def __init__(self, db, parent=None, engine=None, scheduler=None):
        super().__init__(parent)
        self._db = db
        self._engine = engine
        self._scheduler = scheduler
        self.setFixedSize(WINDOW_W, WINDOW_H)
        self.setStyleSheet(
            "background: qlineargradient("
            "x1:0,y1:0,x2:1,y2:1, stop:0 #0a0d1a, "
            "stop:0.5 #06080f, stop:1 #020308);"
        )

        # Phase D state (PRESERVED — names tested)
        self._playback_cid: Optional[int] = None
        self._current_track: Optional[dict] = None
        self._current_duration_ms: int = 0
        self._loop_enabled: bool = False
        self._stop_after_current: bool = False
        self._master_volume: int = self.DEFAULT_VOLUME
        self._fade_out_timer: Optional[QTimer] = None
        self._playback_kind: Optional[str] = None
        self._playback_campaign_id: Optional[int] = None
        self._pre_spot_song_id: Optional[int] = None
        self._queue_songs: list[dict] = self._load_queue_from_db()

        # Build widgets — Steps 1+2 done; rest are placeholders
        self._build_header()
        self._build_master_strip()
        self._build_body_placeholders()
        self._build_bottom_transport_placeholder()

        # Engine signal connections (PRESERVED)
        if self._engine is not None:
            self._engine.position_changed.connect(self._on_engine_position)
            self._engine.playback_ended.connect(self._on_engine_playback_ended)
            self._engine.error_occurred.connect(self._on_engine_error)

        # Scheduler signal connections (PRESERVED)
        if self._scheduler is not None:
            self._scheduler.spot_due.connect(self._on_scheduler_spot_due)
            self._scheduler.song_auto_advance.connect(
                self._on_scheduler_song_advance)
            self._scheduler.break_approaching.connect(
                self._on_scheduler_break_warn)
            self._scheduler.next_break_in.connect(
                self._on_scheduler_next_break_in)
            self._scheduler.started.connect(self._update_status_pills)
            self._scheduler.stopped.connect(self._update_status_pills)

        # 1Hz tick for header clock
        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(1000)
        self._tick_timer.timeout.connect(self._on_tick)
        self._tick_timer.start()
        self._on_tick()

        # Initial state
        self._apply_idle_state()
        self._update_status_pills()

        log.info("Studio ready (Figma 312:2 — Step 2: Master strip)")

    # ── Widget builders ──────────────────────────────────────────────────

    def _build_header(self) -> None:
        self._header = _Header(self)
        self._header.move(0, 0)
        self._header.control_panel_clicked.connect(self._on_control_panel)
        self._header.settings_clicked.connect(self._on_settings)

    def _build_master_strip(self) -> None:
        """Step 2 — six widgets in a horizontal row covering y=72..168.
        Layout per Figma 312:2:
          NowPlayer 836w @ x=16  · NextChip 200w @ x=864  ·
          ControlCluster 296w @ x=1080 · LevelMeters 80w @ x=1392 ·
          ClockFace 80w @ x=1488 · Wordmark 320w @ x=1584
        """
        self._now_player = _NowPlayer(self)
        self._now_player.move(16, MASTER_Y + 4)

        self._next_chip = _NextChip(self)
        self._next_chip.move(864, MASTER_Y + 4)

        self._control_cluster = _ControlCluster(self)
        self._control_cluster.move(1080, MASTER_Y + 8)
        self._control_cluster.restart_clicked.connect(self._on_restart_clicked)
        self._control_cluster.loop_toggled.connect(self._on_loop_toggled)
        self._control_cluster.pause_clicked.connect(self._on_pause_clicked)
        self._control_cluster.stop_next_clicked.connect(
            self._on_stop_next_clicked)

        self._level_meters = _LevelMeters(self)
        self._level_meters.move(1392, MASTER_Y + 8)

        self._clock_face = _AnalogClock(self)
        self._clock_face.move(1488, MASTER_Y + 8)

        self._wordmark = _Wordmark(self)
        self._wordmark.move(1584, MASTER_Y + 8)

    def _build_body_placeholders(self) -> None:
        self._upcoming_placeholder = _PlaceholderFrame(
            "UP COMING — track cards", "Step 3",
            380, BODY_H, accent=AMBER, parent=self)
        self._upcoming_placeholder.move(16, BODY_Y)

        self._libraries_placeholder = _PlaceholderFrame(
            "LIBRARIES — type icons + Action Stack + table + filter",
            "Step 4",
            720, BODY_H, accent=PURPLE_LIGHT, parent=self)
        self._libraries_placeholder.move(412, BODY_Y)

        self._instant_placeholder = _PlaceholderFrame(
            "INSTANT JINGLES — 6-pad + numeric pad + 1-5 hotkeys",
            "Step 5",
            420, 540, accent=AMBER, parent=self)
        self._instant_placeholder.move(1148, BODY_Y)

        self._history_placeholder = _PlaceholderFrame(
            "HISTORY — 12 alternating rows", "Step 6",
            320, 540, accent=ROSE_TEXT, parent=self)
        self._history_placeholder.move(1584, BODY_Y)

        self._next_break_placeholder = _PlaceholderFrame(
            "NEXT BREAK — countdown + Skip + Preview",
            "Step 7", 420, 264, accent=AMBER, parent=self)
        self._next_break_placeholder.move(1148, BODY_Y + 556)

        self._rds_placeholder = _PlaceholderFrame(
            "RDS — LIVE + clock + on-air + RT+",
            "Step 7", 320, 152, accent=GREEN, parent=self)
        self._rds_placeholder.move(1584, BODY_Y + 556)

        self._problems_placeholder = _PlaceholderFrame(
            "PROBLEMS — N badge + warnings",
            "Step 7", 320, 96, accent=AMBER, parent=self)
        self._problems_placeholder.move(1584, BODY_Y + 712)

    def _build_bottom_transport_placeholder(self) -> None:
        self._bottom_placeholder = _PlaceholderFrame(
            "BOTTOM TRANSPORT — Loaded total + ▶/■ + slider + "
            "AutoPlay + 6-button cluster",
            "Step 8", WINDOW_W - 32, BOTTOM_TRANS_H - 8,
            accent=CYAN, parent=self)
        self._bottom_placeholder.move(16, BOTTOM_TRANS_Y + 4)

    # ────────────────────────────────────────────────────────────────────
    # PRESERVED: queue loader — same as legacy
    # ────────────────────────────────────────────────────────────────────

    def _load_queue_from_db(self) -> list[dict]:
        out: list[dict] = []
        try:
            rows = self._db._conn().execute(
                "SELECT id, title, artist, file_path, duration_ms, "
                "category_id, energy "
                "FROM songs "
                "WHERE file_path IS NOT NULL AND file_path != '' "
                "AND duration_ms > 5000 "
                "ORDER BY id LIMIT 60"
            ).fetchall()
        except Exception as exc:
            log.warning(f"queue load failed: {exc}")
            return []
        for r in rows:
            path = r["file_path"]
            if path and os.path.exists(path):
                out.append({
                    "id":             r["id"],
                    "title":          r["title"] or "—",
                    "artist":         r["artist"] or "",
                    "file_path":      path,
                    "duration_ms":    int(r["duration_ms"] or 0),
                    "duration_str":   _fmt_duration(int(r["duration_ms"] or 0)),
                    "category":       "",
                    "_item_type":     "song",
                    "is_break":       False,
                    "is_current":     False,
                })
            if len(out) >= 12:
                break
        return out

    # ────────────────────────────────────────────────────────────────────
    # PRESERVED: helpers (tests touch these names)
    # ────────────────────────────────────────────────────────────────────

    @staticmethod
    def _derive_tags(song: dict) -> list[str]:
        if song.get("tags"):
            return list(song["tags"])
        tags: list[str] = []
        cat = song.get("category", "")
        if cat:
            tags.append(cat)
        energy = song.get("energy", "")
        if energy:
            tags.append(f"{energy} Energy")
        return tags

    @staticmethod
    def _tags_for_item_type(item_type: str) -> list[str]:
        return {
            "song":        [],
            "jingle":      ["Jingle", "Auto"],
            "sweeper":     ["Sweeper", "Auto"],
            "station_id":  ["Station ID", "Auto"],
            "voice_track": ["Voice Track", "Auto"],
            "spot":        ["Ad Break", "Auto"],
        }.get(item_type, [])

    # ────────────────────────────────────────────────────────────────────
    # PRESERVED: queue → deck (verbatim from legacy)
    # ────────────────────────────────────────────────────────────────────

    def _on_queue_song_play(self, song: dict) -> None:
        if self._engine is None:
            log.warning("[studio] no engine — playback unavailable")
            return
        path = song.get("file_path")
        if not path or not os.path.exists(path):
            log.warning(f"[studio] file missing: {path!r}")
            return

        if self._fade_out_timer is not None:
            self._fade_out_timer.stop()
            self._fade_out_timer = None

        if self._playback_cid is not None:
            try:
                self._engine.cleanup(self._playback_cid)
            except Exception:
                pass
            self._playback_cid = None

        try:
            cid = self._engine.load_file(path)
        except Exception as exc:
            log.warning(f"[studio] load_file failed: {exc}")
            return

        self._engine.set_volume(cid, self._master_volume)
        self._engine.play(cid)

        self._playback_cid = cid
        self._playback_kind = "deck"
        self._playback_campaign_id = None
        self._current_track = song
        self._current_duration_ms = self._engine.get_duration_ms(cid) or \
            int(song.get("duration_ms", 0))
        self._stop_after_current = False
        self._apply_playing_state(song)
        self._update_status_pills()

        # Phase F-Final: scheduler-driven plays write a broadcast_log row
        clock_id  = song.get("_clock_id")
        slot_idx  = song.get("_slot_idx")
        item_type = song.get("_item_type", "song")
        if clock_id is not None:
            try:
                self._db.log_play(
                    entry_type=item_type,
                    song_id=int(song.get("id"))
                            if (item_type == "song" and song.get("id")) else None,
                    duration_ms=int(self._current_duration_ms),
                    deck="A",
                    was_manual=0,
                    clock_id=int(clock_id),
                    slot_idx=int(slot_idx) if slot_idx is not None else None,
                )
            except Exception as exc:
                log.warning(f"[studio] {item_type} log_play failed: {exc}")

        log.info(
            f"[studio] deck play ch={cid} {item_type} id={song.get('id')} "
            f"{song.get('title')!r} dur_ms={self._current_duration_ms}"
            + (f" — scheduler clock_id={clock_id}" if clock_id else ""))

    # ────────────────────────────────────────────────────────────────────
    # PRESERVED: engine signal handlers (verbatim)
    # ────────────────────────────────────────────────────────────────────

    def _on_engine_position(self, channel_id: int, position_ms: int) -> None:
        if channel_id != self._playback_cid:
            return
        # Step 2: drive NowPlayer waveform + elapsed/total + REMAINING
        if hasattr(self, "_now_player") and self._now_player is not None:
            self._now_player.set_progress(position_ms,
                                           self._current_duration_ms)

    def _on_engine_playback_ended(self, channel_id: int) -> None:
        """PRESERVED verbatim from legacy — the four EOS paths."""
        if channel_id != self._playback_cid:
            return
        kind = self._playback_kind
        pre_track = self._current_track
        log.info(f"[studio] EOS on ch={channel_id} (kind={kind})")

        try:
            self._engine.cleanup(channel_id)
        except Exception as exc:
            log.debug(f"[studio] EOS cleanup: {exc}")
        self._playback_cid = None
        self._playback_kind = None
        self._playback_campaign_id = None

        # (a) spot resume
        if kind == "spot":
            anchor_id = self._pre_spot_song_id
            self._pre_spot_song_id = None
            next_song = self._compute_next_song(after_id=anchor_id)
            if next_song is not None:
                log.info(f"[studio] spot EOS → resume queue: "
                         f"{next_song.get('title')!r}")
                self._on_queue_song_play(next_song)
                return
            log.info("[studio] spot EOS → queue exhausted, idle")
            self._current_track = None
            self._apply_idle_state()
            self._update_status_pills()
            return

        # (b) stop-next consumed
        if kind == "deck" and self._stop_after_current:
            self._stop_after_current = False
            self._current_track = None
            log.info("[studio] stop-next consumed → idle")
            self._apply_idle_state()
            self._update_status_pills()
            return

        # (c) loop replays
        if (kind == "deck" and self._loop_enabled and pre_track is not None):
            log.info(f"[studio] loop replay → {pre_track.get('title')!r}")
            self._on_queue_song_play(pre_track)
            return

        # (d) auto-advance
        if kind == "deck":
            cur_id = (pre_track or {}).get("id")
            next_song = self._compute_next_song(after_id=cur_id)
            if next_song is not None:
                log.info(f"[studio] auto-advance → {next_song.get('title')!r}")
                self._on_queue_song_play(next_song)
                return
            log.info("[studio] queue exhausted — idle")
            self._current_track = None
            self._apply_idle_state()
            self._update_status_pills()
            return

        # Defensive
        self._current_track = None
        self._apply_idle_state()
        self._update_status_pills()

    def _compute_next_song(self, after_id: Optional[int]) -> Optional[dict]:
        """PRESERVED verbatim from legacy."""
        if self._scheduler is not None and self._scheduler.is_running():
            try:
                from datetime import datetime as _dt
                item = self._scheduler.pick_next_item(_dt.now())
            except Exception as exc:
                log.warning(f"[studio] scheduler.pick_next_item: {exc}")
                item = None
            if item is not None:
                item_type = item.get("item_type", "song") or "song"
                song = {
                    "id":          item.get("item_id"),
                    "title":       item.get("title"),
                    "artist":      item.get("artist"),
                    "file_path":   item.get("file_path"),
                    "duration_ms": int(item.get("duration_ms") or 0),
                    "tags":        self._tags_for_item_type(item_type),
                    "_clock_id":   item.get("clock_id"),
                    "_slot_idx":   item.get("slot_idx"),
                    "_item_type":  item_type,
                }
                log.info(f"[studio] scheduler picked {item_type} item_id="
                         f"{song['id']} clock_id={song['_clock_id']} "
                         f"slot_idx={song['_slot_idx']}")
                return song
        if not self._queue_songs:
            return None
        if after_id is None:
            return self._queue_songs[0]
        idx = next((i for i, s in enumerate(self._queue_songs)
                    if s.get("id") == after_id), -1)
        nxt = idx + 1
        if 0 <= nxt < len(self._queue_songs):
            return self._queue_songs[nxt]
        return None

    def _on_engine_error(self, channel_id: int, message: str) -> None:
        if channel_id != self._playback_cid:
            return
        log.warning(f"[studio] engine error: {message}")
        self._on_engine_playback_ended(channel_id)

    # ────────────────────────────────────────────────────────────────────
    # PRESERVED: scheduler signal handlers (verbatim shape)
    # ────────────────────────────────────────────────────────────────────

    def _on_scheduler_spot_due(self, campaign_id: int) -> None:
        try:
            self._do_scheduler_spot_due(campaign_id)
        except Exception as exc:
            import traceback
            log.error(f"[studio] spot_due handler crashed: "
                      f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}")

    def _do_scheduler_spot_due(self, campaign_id: int) -> None:
        if self._engine is None:
            log.warning(f"[studio] spot_due {campaign_id} — no engine")
            return
        try:
            spot_files = self._db.get_spot_files(campaign_id)
        except Exception as exc:
            log.warning(f"[studio] get_spot_files({campaign_id}): {exc}")
            return
        chosen = None
        for sf in spot_files:
            keys = sf.keys() if hasattr(sf, "keys") else []
            path = sf["file_path"] if "file_path" in keys else None
            is_active = (sf["is_active"] if "is_active" in keys else 1)
            if path and os.path.exists(path) and int(is_active or 0):
                chosen = sf; break
        if chosen is None:
            log.warning(
                f"[studio] campaign {campaign_id} has no playable spot file")
            return
        if self._playback_cid is not None:
            if (self._playback_kind == "deck" and self._current_track):
                self._pre_spot_song_id = self._current_track.get("id")
            try:
                self._engine.cleanup(self._playback_cid)
            except Exception as exc:
                log.debug(f"[studio] deck cleanup before spot: {exc}")
            self._playback_cid = None
            self._playback_kind = None
            self._current_track = None
        if self._fade_out_timer is not None:
            self._fade_out_timer.stop()
            self._fade_out_timer = None
        path = chosen["file_path"]
        try:
            cid = self._engine.load_file(path)
        except Exception as exc:
            log.warning(f"[studio] spot load_file failed: {exc}")
            return
        self._engine.set_volume(cid, self._master_volume)
        self._engine.play(cid)
        self._playback_cid = cid
        self._playback_kind = "spot"
        self._playback_campaign_id = int(campaign_id)
        chosen_keys = set(chosen.keys())
        chosen_duration_ms = int(chosen["duration_ms"] or 0) \
            if "duration_ms" in chosen_keys else 0
        self._current_duration_ms = (self._engine.get_duration_ms(cid)
                                     or chosen_duration_ms)
        chosen_filename = (chosen["filename"] if "filename" in chosen_keys
                           and chosen["filename"] else "—")
        campaign_name = chosen_filename
        try:
            full = self._db.get_campaign(int(campaign_id))
            if full and full.get("name"):
                campaign_name = full["name"]
        except Exception:
            pass
        self._current_track = {
            "id":          int(campaign_id),
            "title":       campaign_name,
            "artist":      "Spot · auto-aired",
            "duration_ms": int(self._current_duration_ms),
            "tags":        ["Ad Break", "Auto"],
        }
        try:
            self._db.log_play(
                entry_type="spot",
                campaign_id=int(campaign_id),
                duration_ms=int(self._current_duration_ms),
                deck="A",
                was_manual=0,
            )
        except Exception as exc:
            log.warning(f"[studio] broadcast_log write failed: {exc}")
        log.info(f"[studio] auto-spot ch={cid} campaign={campaign_id} "
                 f"file={os.path.basename(path)} "
                 f"dur={self._current_duration_ms}ms")
        self._update_status_pills()

    def _on_scheduler_song_advance(self) -> None:
        log.info("[studio] scheduler: song_auto_advance")

    def _on_scheduler_break_warn(self, seconds_until: int) -> None:
        log.info(f"[studio] scheduler: break_approaching in {seconds_until}s")

    def _on_scheduler_next_break_in(self, seconds: int) -> None:
        # Step 7 will wire NextBreak panel
        pass

    # ────────────────────────────────────────────────────────────────────
    # Idle / playing state coordinators (Step 2 — drive master-strip
    # widgets from track state)
    # ────────────────────────────────────────────────────────────────────

    def _apply_idle_state(self) -> None:
        if hasattr(self, "_now_player"):
            self._now_player.set_idle()
        if hasattr(self, "_control_cluster"):
            self._control_cluster.set_idle(True)
            self._control_cluster.set_paused(False)
        # NEXT chip: pre-populate from queue head so the panel isn't blank
        if hasattr(self, "_next_chip"):
            head = self._compute_next_song(after_id=None)
            if head is not None:
                self._next_chip.set_next(
                    str(head.get("title") or "—"),
                    str(head.get("artist") or ""),
                    to_air_s=0,
                    intro_s=0)
            else:
                self._next_chip.set_next("—", "")

    def _apply_playing_state(self, song: dict) -> None:
        if hasattr(self, "_now_player"):
            artist = str(song.get("artist") or "")
            year = song.get("year")
            artist_year = f"{artist} · {year}" if year else artist
            self._now_player.set_track(
                title=str(song.get("title") or "—"),
                artist_year=artist_year,
                total_ms=int(self._current_duration_ms or 0))
        if hasattr(self, "_control_cluster"):
            self._control_cluster.set_idle(False)
            self._control_cluster.set_paused(False)
        # NEXT chip = the song after this one in the queue
        if hasattr(self, "_next_chip"):
            nxt = self._compute_next_song(after_id=song.get("id"))
            if nxt is not None:
                self._next_chip.set_next(
                    str(nxt.get("title") or "—"),
                    str(nxt.get("artist") or ""))
            else:
                self._next_chip.set_next("—", "")

    # ────────────────────────────────────────────────────────────────────
    # Transport handlers (PRESERVED from legacy)
    # ────────────────────────────────────────────────────────────────────

    def _on_pause_clicked(self) -> None:
        if self._playback_cid is None or self._engine is None:
            return
        state = self._engine.get_state(self._playback_cid)
        if state == "playing":
            self._engine.pause(self._playback_cid)
            if hasattr(self, "_control_cluster"):
                self._control_cluster.set_paused(True)
            log.info("[studio] paused")
        elif state == "paused":
            self._engine.resume(self._playback_cid)
            if hasattr(self, "_control_cluster"):
                self._control_cluster.set_paused(False)
            log.info("[studio] resumed")

    def _on_restart_clicked(self) -> None:
        if self._playback_cid is None or self._engine is None:
            return
        self._engine.seek_to_ms(self._playback_cid, 0)
        if self._engine.get_state(self._playback_cid) != "playing":
            self._engine.play(self._playback_cid)
            if hasattr(self, "_control_cluster"):
                self._control_cluster.set_paused(False)
        log.info("[studio] restart → 0ms")

    def _on_stop_next_clicked(self) -> None:
        self._stop_after_current = True
        log.info("[studio] stop-after-current flag set (consumed on EOS)")

    def _on_loop_toggled(self, on: bool) -> None:
        self._loop_enabled = on
        log.info(f"[studio] loop = {on}")

    # ────────────────────────────────────────────────────────────────────
    # State sync
    # ────────────────────────────────────────────────────────────────────

    def _update_status_pills(self) -> None:
        if not hasattr(self, "_header") or self._header is None:
            return
        on_air = (self._playback_cid is not None
                  and self._playback_kind in ("deck", "spot"))
        auto_mode = (self._scheduler is not None
                     and self._scheduler.is_running())
        self._header.set_on_air(on_air)
        self._header.set_auto_mode(auto_mode)

    # ────────────────────────────────────────────────────────────────────
    # ROUTING
    # ────────────────────────────────────────────────────────────────────

    def _on_control_panel(self) -> None:
        # Premium pattern + legacy back-compat
        self.screen_requested.emit("scheduling_hub")
        self.breadcrumb_clicked.emit("control_panel")

    def _on_settings(self) -> None:
        QMessageBox.information(self, "Settings", "Settings — coming soon.")

    # ────────────────────────────────────────────────────────────────────
    # 1Hz tick — header clock
    # ────────────────────────────────────────────────────────────────────

    def _on_tick(self) -> None:
        now = datetime.now()
        self._header.set_clock(
            now.strftime("%H:%M:%S"),
            day=now.strftime("%A").upper(),
            date=now.strftime("%b %d, %Y").upper())

    # ────────────────────────────────────────────────────────────────────
    # Lifecycle
    # ────────────────────────────────────────────────────────────────────

    def hideEvent(self, event):
        super().hideEvent(event)


# Compat: legacy used the constant ROSE_TEXT — provide a fallback in case
# any token didn't import. Using ROSE direct.
ROSE_TEXT = RED
