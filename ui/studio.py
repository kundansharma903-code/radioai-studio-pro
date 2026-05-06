"""
RadioAI Studio Pro — Studio v3 (Figma 312:2 — Premium Jazler Style).

STEP-BY-STEP REBUILD per Plan A (Kavish, 2026-05-06):
  ✅ Step 1: 1920×1080 canvas + new Header
  ✅ Step 2: Master strip (NowPlayer + NextChip + ControlCluster +
             LevelMeters + ClockFace + Wordmark)
  ✅ Step 3: Up Coming queue (rich track cards)
  ✅ Step 4: Libraries panel (type icons + Action Stack +
             Songs table + Filter + Category)
  ✅ Step 5: Instant Jingles (3×3 tiles + DEMO PLAYING +
             1-5 hotkeys + Edit Bank)
  ✅ Step 6: History panel (12 alternating rows +
             View Full History link)                         ← THIS COMMIT
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
# UP COMING — 380 × 820 (Figma 321:2)
#
# Header (UP COMING amber + FADE NEXT toggle + "+5 MORE" pill)
# 5 stacked track cards: AT timestamp + DUR + optional INTRO/NEXT badge
#   + colored album-art tile + title + artist + type badge
# Footer: LOADED PLAYLIST + total mono + Morning Drive Mix subtitle
#   + $ pill + ≡ menu
# ════════════════════════════════════════════════════════════════════════

# Map UI element type → (album-art tile color, type-badge color, label)
_TYPE_VISUAL = {
    "song":        (GREEN_LIGHT,  GREEN,        "SONG"),
    "jingle":      (AMBER_LIGHT,  AMBER,        "JINGLE"),
    "spot":        (RED_LIGHT,    RED,          "BREAK"),
    "break":       (RED_LIGHT,    RED,          "BREAK"),
    "voice_track": (PINK_LIGHT,   PINK,         "VOICE"),
    "voice":       (PINK_LIGHT,   PINK,         "VOICE"),
    "sweeper":     (PURPLE_LIGHT, PURPLE_LIGHT, "SWEEPER"),
    "station_id":  (CYAN_LIGHT,   CYAN,         "STATION"),
}


def _fmt_at_clock(seconds_into_hour: int) -> str:
    """Convert seconds-from-now to a wall-clock 'HH:MM:SS' string. The
    queue rolls forward from current time so each card shows when it
    will air."""
    now = datetime.now()
    base = now.hour * 3600 + now.minute * 60 + now.second + seconds_into_hour
    base %= 24 * 3600
    h = (base // 3600) % 24
    m = (base // 60) % 60
    s = base % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def _fmt_dur_short(ms: int) -> str:
    """Compact duration like '3.5s' or '4:23'."""
    s = max(0, int(ms or 0)) // 1000
    if s < 60:
        # Show one decimal if under a minute
        ms_rem = (int(ms or 0) % 1000) // 100
        return f"{s}.{ms_rem}s"
    m, ss = divmod(s, 60)
    return f"{m}:{ss:02d}"


class _UpComingCard(QWidget):
    """One track card in the Up Coming list (360 × 124)."""

    double_clicked = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(360, 124)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._song: Optional[dict] = None
        self._is_next = False
        self._at_text = "—"

        self._font_at        = mono(8, bold=True, letter_spacing=0.5)
        self._font_dur       = mono(9, bold=True, letter_spacing=0.3)
        self._font_intro     = mono(8, bold=True, letter_spacing=0.4)
        self._font_title     = inter(13, QFont.Weight.Bold, letter_spacing=-0.1)
        self._font_artist    = inter(10, QFont.Weight.Medium)
        self._font_badge     = inter(8, QFont.Weight.Black, letter_spacing=1.4)
        self._font_glyph     = inter(15, QFont.Weight.Black)
        self._font_next_pill = inter(8, QFont.Weight.Black, letter_spacing=1.4)

    def set_song(self, song: Optional[dict], is_next: bool = False,
                 at_text: str = "—") -> None:
        self._song = dict(song) if song else None
        self._is_next = bool(is_next)
        self._at_text = at_text or "—"
        self.update(self.rect())

    def mouseDoubleClickEvent(self, e: QMouseEvent) -> None:
        if self._song is not None:
            self.double_clicked.emit(self._song)
        super().mouseDoubleClickEvent(e)

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        # Card background — NEXT card gets rose tint + glow
        if self._is_next:
            grad = QLinearGradient(0, 0, self.width(), 0)
            grad.setColorAt(0.0, _qcolor_a(RED, 0.18))
            grad.setColorAt(1.0, _qcolor_a(RED, 0.04))
            p.fillRect(r, QBrush(grad))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(_qcolor_a(RED, 0.45)))
        else:
            bg = QLinearGradient(0, 0, 0, self.height())
            bg.setColorAt(0.0, QColor(14, 16, 32, 230))
            bg.setColorAt(1.0, QColor(7, 9, 18, 230))
            p.fillRect(r, QBrush(bg))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(255, 255, 255, 18)))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)

        if self._song is None:
            p.setPen(QColor(TEXT_DIM))
            p.setFont(inter(11, QFont.Weight.Medium))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, "—")
            p.end()
            return

        # Resolve type visuals
        item_type = self._song.get("_item_type") or "song"
        tile_color, badge_color, badge_label = _TYPE_VISUAL.get(
            item_type, _TYPE_VISUAL["song"])

        # AT timestamp (top-left)
        p.setPen(QColor(TEXT_DIM)); p.setFont(self._font_at)
        p.drawText(QRectF(12, 8, 100, 12),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   f"AT  {self._at_text}")

        # DUR (top, right-of-center)
        dur_ms = int(self._song.get("duration_ms") or 0)
        p.setPen(QColor(TEXT_DIM)); p.setFont(self._font_dur)
        p.drawText(QRectF(140, 8, 90, 12),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   f"DUR  {_fmt_dur_short(dur_ms)}")

        # INTRO badge or NEXT pill (top-right)
        if self._is_next:
            badge = QRectF(self.width() - 60, 6, 50, 18)
            p.fillRect(badge, _qcolor_a(RED, 0.4))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(_qcolor_a(RED, 0.7)))
            p.drawRoundedRect(badge.adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)
            p.setPen(QColor(TEXT_PRI)); p.setFont(self._font_next_pill)
            p.drawText(badge, Qt.AlignmentFlag.AlignCenter, "NEXT")
        else:
            intro_ms = int(self._song.get("intro_point_ms") or 0)
            if intro_ms > 0:
                intro_s = max(1, intro_ms // 1000)
                badge = QRectF(232, 6, 80, 14)
                p.setPen(QColor(AMBER_LIGHT)); p.setFont(self._font_intro)
                p.drawText(badge, Qt.AlignmentFlag.AlignLeft
                           | Qt.AlignmentFlag.AlignVCenter,
                           f"INTRO  {intro_s:02d}.0s")

        # Album art tile (44×44 colored square, left side, vertically centered)
        art_rect = QRectF(12, 36, 60, 60)
        # Background gradient (darker variant of tile color)
        art_grad = QLinearGradient(art_rect.topLeft(), art_rect.bottomRight())
        art_grad.setColorAt(0.0, _qcolor_a(tile_color, 0.95))
        art_grad.setColorAt(1.0, _qcolor_a(tile_color, 0.55))
        p.setBrush(QBrush(art_grad)); p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(art_rect, 8, 8)
        # Center glyph based on type
        p.setPen(QColor(BG_BASE)); p.setFont(self._font_glyph)
        glyph = {"song": "♪", "jingle": "🔔", "spot": "$",
                 "break": "$", "voice": "🎤", "voice_track": "🎤",
                 "sweeper": "★", "station_id": "ID"}.get(item_type, "♪")
        p.drawText(art_rect, Qt.AlignmentFlag.AlignCenter, glyph)

        # Title + artist (right of album art)
        title = str(self._song.get("title") or "—")
        artist = str(self._song.get("artist") or "")
        p.setPen(QColor(TEXT_PRI)); p.setFont(self._font_title)
        p.drawText(QRectF(82, 38, self.width() - 100, 18),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   title)
        p.setPen(QColor(TEXT_SEC)); p.setFont(self._font_artist)
        p.drawText(QRectF(82, 56, self.width() - 100, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   artist)

        # Type badge (bottom-right)
        badge_w = 76
        type_badge = QRectF(self.width() - badge_w - 12, 96, badge_w, 18)
        p.fillRect(type_badge, _qcolor_a(badge_color, 0.18))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_qcolor_a(badge_color, 0.45)))
        p.drawRoundedRect(type_badge.adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)
        p.setPen(QColor(badge_color)); p.setFont(self._font_badge)
        p.drawText(type_badge, Qt.AlignmentFlag.AlignCenter, badge_label)

        p.end()


class _FadeNextToggle(QWidget):
    """Small toggle pill at top-right of UP COMING header."""

    toggled = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(86, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._on = False
        self._font = inter(8, QFont.Weight.Bold, letter_spacing=1.2)

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._on = not self._on
            self.update(self.rect())
            self.toggled.emit(self._on)
        super().mousePressEvent(e)

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Label
        p.setPen(QColor(TEXT_DIM if not self._on else CYAN_LIGHT))
        p.setFont(self._font)
        p.drawText(QRectF(0, 0, 60, 22),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "FADE NEXT")
        # Toggle pill
        pill = QRectF(60, 4, 22, 14)
        p.fillRect(pill, _qcolor_a(CYAN if self._on else TEXT_DIM, 0.3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_qcolor_a(CYAN if self._on else TEXT_DIM, 0.5)))
        p.drawRoundedRect(pill.adjusted(0.5, 0.5, -0.5, -0.5), 7, 7)
        # Knob
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(CYAN_LIGHT) if self._on else QColor(TEXT_SEC))
        knob_x = 76 if self._on else 64
        p.drawEllipse(QPointF(knob_x, 11), 5, 5)
        p.end()


class _UpComingQueue(QWidget):
    """380 × 820 panel: header + 5 cards + footer."""

    song_double_clicked = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(380, 820)
        self._loaded_total = "0:00:00"
        self._loaded_label = "Morning Drive Mix"

        self._font_h        = inter(11, QFont.Weight.Black, letter_spacing=1.6)
        self._font_more     = inter(9, QFont.Weight.Bold, letter_spacing=0.8)
        self._font_footer_l = inter(8, QFont.Weight.Bold, letter_spacing=1.4)
        self._font_footer_v = mono(22, bold=True, letter_spacing=-0.5)
        self._font_footer_s = inter(10, QFont.Weight.Medium)

        self._fade_toggle = _FadeNextToggle(self)
        self._fade_toggle.move(12, 30)

        # 5 cards stacked vertically — y=64 + i*128
        self._cards: list[_UpComingCard] = []
        for i in range(5):
            c = _UpComingCard(self)
            c.move(10, 64 + i * 128)
            c.double_clicked.connect(self.song_double_clicked.emit)
            self._cards.append(c)

    def set_queue(self, songs: list[dict], current_id: Optional[int] = None) -> None:
        """Populate cards. AT timestamps cumulative from now. The first
        card is rendered as NEXT (rose glow + NEXT pill)."""
        cum_s = 0
        for i, card in enumerate(self._cards):
            if i < len(songs):
                song = songs[i]
                at_text = _fmt_at_clock(cum_s)
                card.set_song(song, is_next=(i == 1), at_text=at_text)
                # NOTE: index 1 = "NEXT" because index 0 is currently
                # playing (or just-played, in idle); the broadcast
                # operator's "what plays next" mental model points to
                # the row immediately below the active one.
                cum_s += int(song.get("duration_ms", 0) or 0) // 1000
            else:
                card.set_song(None)
        # Loaded total
        total_ms = sum(int(s.get("duration_ms") or 0) for s in songs)
        s_total = total_ms // 1000
        h, rem = divmod(s_total, 3600)
        m, ss = divmod(rem, 60)
        self._loaded_total = f"{h}:{m:02d}:{ss:02d}"
        self.update(QRect(0, self.height() - 100, self.width(), 100))

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        # Card background (panel)
        bg = QLinearGradient(0, 0, 0, self.height())
        bg.setColorAt(0.0, QColor(14, 16, 32, 235))
        bg.setColorAt(1.0, QColor(7, 9, 18, 235))
        p.fillRect(r, QBrush(bg))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 18)))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 12, 12)
        # 3px amber accent at top
        accent = QLinearGradient(0, 0, self.width(), 0)
        accent.setColorAt(0.0, QColor(AMBER))
        accent.setColorAt(1.0, _qcolor_a(AMBER, 0.4))
        p.fillRect(QRectF(0, 0, self.width(), 3), QBrush(accent))

        # "UP COMING" header
        p.setPen(QColor(AMBER_LIGHT)); p.setFont(self._font_h)
        p.drawText(QRectF(12, 10, 200, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "UP COMING")
        # "+5 MORE" pill (right of header)
        more_pill = QRectF(self.width() - 78, 10, 66, 16)
        p.fillRect(more_pill, _qcolor_a(AMBER, 0.18))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_qcolor_a(AMBER, 0.45)))
        p.drawRoundedRect(more_pill.adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)
        p.setPen(QColor(AMBER_LIGHT)); p.setFont(self._font_more)
        p.drawText(more_pill, Qt.AlignmentFlag.AlignCenter, "+5 MORE")

        # Footer separator hairline
        fy = self.height() - 88
        p.fillRect(QRectF(8, fy, self.width() - 16, 1),
                   QColor(255, 255, 255, 20))
        # LOADED PLAYLIST label
        p.setPen(QColor(TEXT_DIM)); p.setFont(self._font_footer_l)
        p.drawText(QRectF(12, fy + 8, 200, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "LOADED PLAYLIST")
        # Big total time
        p.setPen(QColor(AMBER_LIGHT)); p.setFont(self._font_footer_v)
        p.drawText(QRectF(12, fy + 22, 220, 30),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._loaded_total)
        # Subtitle
        p.setPen(QColor(TEXT_SEC)); p.setFont(self._font_footer_s)
        p.drawText(QRectF(12, fy + 56, 220, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._loaded_label)
        # $ pill (right)
        dollar = QRectF(self.width() - 80, fy + 28, 30, 28)
        p.fillRect(dollar, _qcolor_a(GREEN, 0.18))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_qcolor_a(GREEN, 0.45)))
        p.drawRoundedRect(dollar.adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
        p.setPen(QColor(GREEN_LIGHT))
        p.setFont(inter(13, QFont.Weight.Bold))
        p.drawText(dollar, Qt.AlignmentFlag.AlignCenter, "$")
        # ≡ menu (right)
        menu_box = QRectF(self.width() - 44, fy + 28, 30, 28)
        p.fillRect(menu_box, QColor(7, 8, 16, 178))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 30)))
        p.drawRoundedRect(menu_box.adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
        p.setPen(QColor(TEXT_SEC))
        p.setFont(inter(13, QFont.Weight.Bold))
        p.drawText(menu_box, Qt.AlignmentFlag.AlignCenter, "≡")
        p.end()


# ════════════════════════════════════════════════════════════════════════
# LIBRARIES — 720 × 820 (Figma 322:2)
#
# Header: LIBRARIES + "+5 IDEAS" pill
# 7 type icon tiles row: Songs / Tracks / Jingles / Spots / Voice /
#                         Folders / Favorites (Songs active green)
# Action Stack (left column): 5 buttons ADD / INSERT / REPLACE /
#                              prepAIR / DELETE
# Songs table: amber-tinted alternating rows, artist + title
# Filter sub-panel: SEARCH & FILTER + search input + Search/Reset
#                    buttons + 3 checkboxes
# Category dropdown: All Songs cyan + Manage Categories link
# ════════════════════════════════════════════════════════════════════════

# Type icon row entries (7) — name + glyph + accent color
_LIB_TYPE_ICONS = [
    ("Songs",     "♪",  GREEN_LIGHT,  True),    # active by default
    ("Tracks",    "≡",  CYAN_LIGHT,   False),
    ("Jingles",   "🔔", AMBER_LIGHT,  False),
    ("Spots",     "$",  GREEN,        False),
    ("Voice",     "🎤", PINK_LIGHT,   False),
    ("Folders",   "📁", PURPLE_LIGHT, False),
    ("Favorites", "♥",  RED,          False),
]


class _LibTypeTile(QWidget):
    """One 86 × 60 tile in the type icons row."""
    clicked = pyqtSignal(str)

    def __init__(self, name: str, glyph: str, accent: str, parent=None):
        super().__init__(parent)
        self.setFixedSize(86, 60)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._name = name; self._glyph = glyph
        self._accent = accent
        self._active = False
        self._font_glyph = inter(20, QFont.Weight.Black)
        self._font_label = inter(8, QFont.Weight.Bold, letter_spacing=1.4)

    def set_active(self, on: bool) -> None:
        if on == self._active:
            return
        self._active = bool(on)
        self.update(self.rect())

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._name)
        super().mousePressEvent(e)

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        # Tile background
        if self._active:
            grad = QLinearGradient(0, 0, 0, self.height())
            grad.setColorAt(0.0, _qcolor_a(self._accent, 0.30))
            grad.setColorAt(1.0, _qcolor_a(self._accent, 0.10))
            p.fillRect(r, QBrush(grad))
            border_alpha = 0.55
        else:
            p.fillRect(r, QColor(7, 8, 16, 178))
            border_alpha = 0.20
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_qcolor_a(self._accent, border_alpha)))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        # Glyph
        p.setPen(QColor(self._accent)); p.setFont(self._font_glyph)
        p.drawText(QRectF(0, 4, self.width(), 32),
                   Qt.AlignmentFlag.AlignCenter, self._glyph)
        # Label
        p.setPen(_qcolor_a(self._accent, 0.95))
        p.setFont(self._font_label)
        p.drawText(QRectF(0, 36, self.width(), 18),
                   Qt.AlignmentFlag.AlignCenter, self._name.upper())
        p.end()


class _LibActionButton(QWidget):
    """One 76 × 76 button in the action stack (vertical icon + label)."""
    clicked = pyqtSignal()

    def __init__(self, label: str, glyph: str, accent: str,
                 primary: bool = False, parent=None):
        super().__init__(parent)
        self.setFixedSize(76, 76)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._label = label; self._glyph = glyph
        self._accent = accent
        self._primary = primary
        self._enabled = True
        self._font_glyph = inter(22, QFont.Weight.Black)
        self._font_label = inter(8, QFont.Weight.Black, letter_spacing=0.6)
        if primary:
            self.setGraphicsEffect(_drop_shadow(14, _qcolor_a(accent, 0.4), 4))

    def set_enabled(self, on: bool) -> None:
        self._enabled = bool(on)
        self.setCursor(Qt.CursorShape.PointingHandCursor if on
                       else Qt.CursorShape.ForbiddenCursor)
        self.update(self.rect())

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if self._enabled and e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        if self._primary and self._enabled:
            grad = QLinearGradient(0, 0, 0, self.height())
            grad.setColorAt(0.0, _qcolor_a(self._accent, 0.95))
            grad.setColorAt(1.0, _qcolor_a(GREEN_DK if self._accent == GREEN
                                          else self._accent, 0.65))
            p.fillRect(r, QBrush(grad))
            text_color = QColor(255, 255, 255)
        else:
            alpha = 0.20 if self._enabled else 0.06
            p.fillRect(r, _qcolor_a(self._accent, alpha))
            text_color = (_qcolor_a(self._accent, 0.95) if self._enabled
                          else _qcolor_a(self._accent, 0.30))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_qcolor_a(self._accent,
                                0.5 if self._enabled else 0.18)))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        p.setPen(text_color); p.setFont(self._font_glyph)
        p.drawText(QRectF(0, 8, self.width(), 32),
                   Qt.AlignmentFlag.AlignCenter, self._glyph)
        p.setFont(self._font_label)
        p.drawText(QRectF(0, 46, self.width(), 18),
                   Qt.AlignmentFlag.AlignCenter, self._label)
        p.end()


# Need GREEN_DK fallback if not in tokens
GREEN_DK = "#047857"


class _LibSongRow:
    """Plain data slot for one row in the songs table."""
    def __init__(self, artist: str = "", title: str = ""):
        self.artist = artist
        self.title = title


class _LibSongsTable(QWidget):
    """Custom-paint songs table with amber-tinted alternating rows.
    Rows = list[_LibSongRow]. Selected row is highlighted lighter."""

    row_selected = pyqtSignal(int)
    row_double_clicked = pyqtSignal(int)

    ROW_H = 26

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(620, 380)
        self._rows: list[_LibSongRow] = []
        self._selected = -1
        self._font_artist = inter(11, QFont.Weight.Bold, letter_spacing=-0.1)
        self._font_title  = inter(10, QFont.Weight.Medium)

    def set_rows(self, rows: list[_LibSongRow]) -> None:
        self._rows = list(rows or [])
        self._selected = -1
        self.update(self.rect())

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(e); return
        y = e.position().toPoint().y()
        idx = y // self.ROW_H
        if 0 <= idx < len(self._rows):
            self._selected = idx
            self.update(self.rect())
            self.row_selected.emit(int(idx))
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e: QMouseEvent) -> None:
        y = e.position().toPoint().y()
        idx = y // self.ROW_H
        if 0 <= idx < len(self._rows):
            self.row_double_clicked.emit(int(idx))
        super().mouseDoubleClickEvent(e)

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        clip = e.rect()
        # Determine visible row range from clip
        first = max(0, clip.y() // self.ROW_H)
        last = min(len(self._rows) - 1,
                   (clip.y() + clip.height() - 1) // self.ROW_H)
        for i in range(first, last + 1):
            row = self._rows[i]
            ry = i * self.ROW_H
            row_rect = QRectF(0, ry, self.width(), self.ROW_H)
            # Background: amber tint, alternating; selected = lighter
            if i == self._selected:
                p.fillRect(row_rect, _qcolor_a(AMBER, 0.30))
            else:
                tint = 0.10 if (i % 2 == 0) else 0.06
                p.fillRect(row_rect, _qcolor_a(AMBER, tint))
            # Artist (bold white)
            p.setPen(QColor(TEXT_PRI)); p.setFont(self._font_artist)
            p.drawText(QRect(int(12), int(ry), int(190), int(self.ROW_H)),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       row.artist or "—")
            # Title (muted)
            p.setPen(QColor(TEXT_SEC)); p.setFont(self._font_title)
            p.drawText(QRect(int(212), int(ry),
                            int(self.width() - 224), int(self.ROW_H)),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       row.title or "—")
        p.end()


class _LibCheckbox(QWidget):
    """Small toggle checkbox for the filter strip."""
    toggled = pyqtSignal(bool)

    def __init__(self, label: str, accent: str = CYAN, checked: bool = False,
                 parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._label = label
        self._accent = accent
        self._checked = bool(checked)
        self._font = inter(10, QFont.Weight.Medium)
        self.setFixedSize(int(20 + len(label) * 7), 20)

    def is_checked(self) -> bool: return self._checked

    def set_checked(self, on: bool) -> None:
        if on == self._checked: return
        self._checked = bool(on); self.update(self.rect())

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._checked = not self._checked
            self.update(self.rect())
            self.toggled.emit(self._checked)
        super().mousePressEvent(e)

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        box = QRectF(0, 3, 14, 14)
        if self._checked:
            p.fillRect(box, _qcolor_a(self._accent, 0.30))
            p.setPen(QPen(_qcolor_a(self._accent, 0.95), 1.5))
        else:
            p.fillRect(box, QColor(7, 8, 16, 178))
            p.setPen(QPen(QColor(255, 255, 255, 50), 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(box.adjusted(0.5, 0.5, -0.5, -0.5), 3, 3)
        if self._checked:
            p.setPen(QColor(self._accent))
            p.setFont(inter(10, QFont.Weight.Bold))
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, "✓")
        # Label
        p.setPen(_qcolor_a(self._accent if self._checked else COL_TEXT_SECONDARY_FB, 0.95))
        p.setFont(self._font)
        p.drawText(QRectF(20, 0, self.width() - 22, self.height()),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._label)
        p.end()


# Token fallback for the checkbox (legacy _tokens.py exposes TEXT_SEC)
COL_TEXT_SECONDARY_FB = TEXT_SEC


class _LibPillBtn(QWidget):
    clicked = pyqtSignal()

    def __init__(self, label: str, color: str, w: int = 80, parent=None):
        super().__init__(parent)
        self.setFixedSize(w, 30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._label = label; self._color = color
        self._hover = False
        self._font = inter(10, QFont.Weight.Bold, letter_spacing=0.4)

    def enterEvent(self, e):
        if not self._hover:
            self._hover = True; self.update(self.rect())
        super().enterEvent(e)

    def leaveEvent(self, e):
        if self._hover:
            self._hover = False; self.update(self.rect())
        super().leaveEvent(e)

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        p.fillRect(r, _qcolor_a(self._color, 0.22 if self._hover else 0.12))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_qcolor_a(self._color, 0.45)))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
        p.setPen(_qcolor_a(self._color, 0.95)); p.setFont(self._font)
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, self._label)
        p.end()


class _LibCategoryDropdown(QWidget):
    """Big 540×42 cyan-glow dropdown showing 'All Songs' + chevron."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(540, 42)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._label = "All Songs"
        self._count = 0
        self._font_main = inter(13, QFont.Weight.Bold, letter_spacing=-0.2)
        self._font_count = mono(10)
        self._font_chev = inter(10, QFont.Weight.Bold)
        self.setGraphicsEffect(_drop_shadow(8, _qcolor_a(CYAN, 0.20), 3))

    def set_data(self, label: str, count: int) -> None:
        self._label = label
        self._count = int(count or 0)
        self.update(self.rect())

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        grad = QLinearGradient(0, 0, self.width(), 0)
        grad.setColorAt(0.0, _qcolor_a(CYAN, 0.10))
        grad.setColorAt(1.0, _qcolor_a(CYAN, 0.04))
        p.fillRect(r, QBrush(grad))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_qcolor_a(CYAN, 0.40)))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        # Color dot
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(_qcolor_a(CYAN_LIGHT, 0.95))
        p.drawEllipse(QPointF(14, self.height() / 2), 5, 5)
        # Label + count
        p.setPen(_qcolor_a(CYAN_LIGHT, 0.95)); p.setFont(self._font_main)
        p.drawText(QRectF(28, 4, 240, 22),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._label)
        p.setPen(QColor(TEXT_SEC)); p.setFont(self._font_count)
        p.drawText(QRectF(28, 22, 240, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   f"{self._count:,} songs")
        p.setPen(_qcolor_a(CYAN_LIGHT, 0.95)); p.setFont(self._font_chev)
        p.drawText(QRectF(self.width() - 24, 0, 18, self.height()),
                   Qt.AlignmentFlag.AlignCenter, "▾")
        p.end()


class _LibrariesPanel(QWidget):
    """720 × 820 — full Libraries panel."""

    song_double_clicked = pyqtSignal(int)    # row index in self._rows

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(720, 820)
        self._rows: list[_LibSongRow] = []
        self._total_song_count = 0

        self._font_h        = inter(13, QFont.Weight.Black, letter_spacing=-0.1)
        self._font_ideas    = inter(9, QFont.Weight.Bold, letter_spacing=0.6)
        self._font_section  = inter(11, QFont.Weight.Black, letter_spacing=1.4)
        self._font_results  = inter(10, QFont.Weight.Bold, letter_spacing=0.4)
        self._font_helper   = inter(10, QFont.Weight.Medium)
        self._font_manage   = inter(10, QFont.Weight.Bold, letter_spacing=0.4)

        # 7 type icons row
        self._type_tiles: dict[str, _LibTypeTile] = {}
        for i, (name, glyph, accent, active) in enumerate(_LIB_TYPE_ICONS):
            tile = _LibTypeTile(name, glyph, accent, self)
            tile.move(14 + i * 90, 38)
            tile.set_active(active)
            tile.clicked.connect(self._on_type_clicked)
            self._type_tiles[name] = tile

        # Action stack (left column)
        self._b_add = _LibActionButton("ADD", "+", GREEN, primary=True,
                                       parent=self)
        self._b_add.move(14, 110)
        self._b_ins = _LibActionButton("INSERT", "↳", GREEN, parent=self)
        self._b_ins.move(14, 192); self._b_ins.set_enabled(False)
        self._b_rep = _LibActionButton("REPLACE", "⇄", GREEN, parent=self)
        self._b_rep.move(14, 274); self._b_rep.set_enabled(False)
        self._b_prep = _LibActionButton("PREPAIR", "🎙", PURPLE_LIGHT,
                                        parent=self)
        self._b_prep.move(14, 356)
        self._b_del = _LibActionButton("DELETE", "🗑", RED, parent=self)
        self._b_del.move(14, 438); self._b_del.set_enabled(False)

        # Songs table
        self._table = _LibSongsTable(self)
        self._table.move(102, 110)
        self._table.row_selected.connect(self._on_row_selected)
        self._table.row_double_clicked.connect(self._on_row_double_clicked)

        # Filter sub-panel — search input + Search/Reset buttons
        from PyQt6.QtWidgets import QLineEdit
        self._search = QLineEdit(self)
        self._search.setGeometry(14, 540, 380, 32)
        self._search.setPlaceholderText("Search by artist or title…")
        self._search.setFont(inter(11, QFont.Weight.Medium))
        self._search.setStyleSheet(
            "QLineEdit { background: rgba(7,8,16,0.7); "
            "border: 1px solid rgba(255,255,255,0.10); border-radius: 6px; "
            f"color: {TEXT_PRI}; padding: 0 11px; }} "
            f"QLineEdit::placeholder {{ color: {TEXT_DIM}; }} "
            "QLineEdit:focus { border-color: rgba(6,182,212,0.5); }"
        )

        self._b_search = _LibPillBtn("Search", CYAN, 80, self)
        self._b_search.move(404, 541)
        self._b_reset = _LibPillBtn("Reset", RED, 80, self)
        self._b_reset.move(490, 541)

        # Checkboxes
        self._cb_super = _LibCheckbox("SuperSearch", CYAN, checked=True,
                                      parent=self)
        self._cb_super.move(14, 584)
        self._cb_new = _LibCheckbox("Show Only NEW Additions",
                                    PURPLE_LIGHT, parent=self)
        self._cb_new.move(140, 584)
        self._cb_surname = _LibCheckbox("Sort by Surname", AMBER_LIGHT,
                                        parent=self)
        self._cb_surname.move(360, 584)

        # Category dropdown
        self._cat_dropdown = _LibCategoryDropdown(self)
        self._cat_dropdown.move(14, 700)

    # ── Public API ───────────────────────────────────────────────────────

    def set_songs(self, songs: list[dict], total_song_count: int = 0) -> None:
        rows = []
        for s in songs:
            rows.append(_LibSongRow(
                artist=str(s.get("artist") or "—"),
                title=str(s.get("title") or "—")))
        self._rows = rows
        self._total_song_count = int(total_song_count or len(songs))
        self._table.set_rows(self._rows)
        self._cat_dropdown.set_data("All Songs", self._total_song_count)

    def _on_type_clicked(self, name: str) -> None:
        for k, tile in self._type_tiles.items():
            tile.set_active(k == name)

    def _on_row_selected(self, idx: int) -> None:
        # Enable INSERT/REPLACE/DELETE
        sel = idx >= 0
        self._b_ins.set_enabled(sel)
        self._b_rep.set_enabled(sel)
        self._b_del.set_enabled(sel)

    def _on_row_double_clicked(self, idx: int) -> None:
        self.song_double_clicked.emit(int(idx))

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        # Panel background
        bg = QLinearGradient(0, 0, 0, self.height())
        bg.setColorAt(0.0, QColor(14, 16, 32, 235))
        bg.setColorAt(1.0, QColor(7, 9, 18, 235))
        p.fillRect(r, QBrush(bg))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 18)))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 12, 12)
        # cyan→purple→pink accent at top (3px)
        accent = QLinearGradient(0, 0, self.width(), 0)
        accent.setColorAt(0.0, QColor(CYAN))
        accent.setColorAt(0.5, QColor(PURPLE_LIGHT))
        accent.setColorAt(1.0, QColor(PINK))
        p.fillRect(QRectF(0, 0, self.width(), 3), QBrush(accent))

        # Header "LIBRARIES"
        p.setPen(QColor(CYAN_LIGHT)); p.setFont(self._font_h)
        p.drawText(QRectF(14, 10, 200, 18),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "LIBRARIES")
        # "+5 IDEAS" pill (right of header)
        ideas = QRectF(self.width() - 88, 12, 74, 16)
        p.fillRect(ideas, QColor(7, 8, 16, 178))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 30)))
        p.drawRoundedRect(ideas.adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)
        p.setPen(QColor(TEXT_SEC)); p.setFont(self._font_ideas)
        p.drawText(ideas, Qt.AlignmentFlag.AlignCenter, "+5 IDEAS")

        # Filter sub-panel header
        p.setPen(QColor(CYAN_LIGHT)); p.setFont(self._font_section)
        p.drawText(QRectF(14, 510, 240, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "SEARCH & FILTER")
        # Results count (right side of filter header)
        p.setPen(QColor(AMBER_LIGHT)); p.setFont(self._font_results)
        p.drawText(QRectF(self.width() - 200, 510, 186, 14),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   f"{self._total_song_count} RESULTS")

        # Hairline above category section
        p.fillRect(QRectF(14, 670, self.width() - 28, 1),
                   QColor(255, 255, 255, 20))
        # CATEGORY label
        p.setPen(QColor(CYAN_LIGHT)); p.setFont(self._font_section)
        p.drawText(QRectF(14, 678, 200, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "CATEGORY")
        # Manage Categories link (right of dropdown)
        p.setPen(QColor(PURPLE_LIGHT)); p.setFont(self._font_manage)
        p.drawText(QRectF(self.width() - 170, 752, 160, 16),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   "⚙  Manage Categories")
        p.end()


# ════════════════════════════════════════════════════════════════════════
# INSTANT JINGLES — 420 × 540 (Figma 324:2)
#
# Header: INSTANT JINGLES + 12 SLOT pill + × close
# DEMO Sweep PLAYING display (full-width, green-tinted)
# 3×3 jingle tile grid with name + duration + play-arrow icon
# 5-button hotkey row (1 / 2 / 3 / 4 / 5)
# Helper text ("Tap any slot to play instantly · 1-5 hotkeys ...")
# Footer: "Edit Bank" purple link + Last played status (right)
#
# Decorative per Q2 vote A — visual fidelity only, no wiring to
# core.instant_jingle_engine in this commit.
# ════════════════════════════════════════════════════════════════════════

# Sample jingle tile data (visual placeholder per Q2 — wire later)
_JINGLE_TILES_DATA = [
    ("CLAPS",        "09.7", AMBER),
    ("SCREAM",       "09.5", AMBER),
    ("SF Aaa Lost",  "04.1", AMBER),
    ("SF Horn Funny","01.3", AMBER),
    ("SF Yea OK",    "04.2", RED),
    ("Drop O3",      "01.7", RED),
    ("O2",           "01.9", AMBER),
    ("O1",           "03.5", AMBER),
    ("SW Trave",     "00.9", AMBER),
]


class _JingleTile(QWidget):
    """One jingle tile — name + duration + play-arrow + colored accent."""

    clicked = pyqtSignal()

    def __init__(self, name: str, dur_str: str, accent: str, parent=None):
        super().__init__(parent)
        self.setFixedSize(124, 70)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._name = name
        self._dur_str = dur_str
        self._accent = accent
        self._font_name = inter(10, QFont.Weight.Black, letter_spacing=0.4)
        self._font_dur  = mono(11, bold=True, letter_spacing=-0.3)
        self._font_unit = inter(7, QFont.Weight.Bold, letter_spacing=1.2)
        self._font_play = inter(11, QFont.Weight.Black)

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        # Background — accent-tinted gradient
        bg = QLinearGradient(0, 0, 0, self.height())
        bg.setColorAt(0.0, _qcolor_a(self._accent, 0.30))
        bg.setColorAt(1.0, _qcolor_a(self._accent, 0.10))
        p.fillRect(r, QBrush(bg))
        # Border accent color
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_qcolor_a(self._accent, 0.55)))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        # Name (top-left)
        p.setPen(QColor(self._accent)); p.setFont(self._font_name)
        p.drawText(QRectF(10, 6, self.width() - 30, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._name.upper())
        # Play arrow (top-right)
        p.setPen(QColor(self._accent)); p.setFont(self._font_play)
        p.drawText(QRectF(self.width() - 22, 4, 18, 18),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   "▶")
        # Duration (big mono, center-bottom)
        p.setPen(QColor(self._accent)); p.setFont(self._font_dur)
        p.drawText(QRectF(10, 26, self.width() - 30, 24),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._dur_str)
        # SEC unit
        p.setPen(_qcolor_a(self._accent, 0.7)); p.setFont(self._font_unit)
        p.drawText(QRectF(10, 50, 30, 12),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "SEC")
        p.end()


class _JingleHotkey(QWidget):
    """Numbered hotkey button (1-5)."""

    clicked = pyqtSignal(int)

    def __init__(self, n: int, parent=None):
        super().__init__(parent)
        self.setFixedSize(60, 40)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._n = n
        self._font = mono(15, bold=True, letter_spacing=-0.5)

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._n)
        super().mousePressEvent(e)

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        p.fillRect(r, _qcolor_a(AMBER, 0.18))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_qcolor_a(AMBER, 0.45)))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
        p.setPen(QColor(AMBER_LIGHT)); p.setFont(self._font)
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, str(self._n))
        p.end()


class _InstantJinglesPanel(QWidget):
    """420 × 540 — full Instant Jingles panel."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(420, 540)
        self._demo_label = "DEMO Sweep"
        self._demo_remaining_s = 0.0       # seconds remaining (decorative)
        self._last_played_label = "SF Yes OK · 14s ago"

        self._font_h            = inter(11, QFont.Weight.Black, letter_spacing=1.6)
        self._font_slot_pill    = mono(8, bold=True, letter_spacing=0.5)
        self._font_close        = inter(13, QFont.Weight.Bold)
        self._font_playing_pill = inter(8, QFont.Weight.Black, letter_spacing=1.4)
        self._font_demo_label   = inter(13, QFont.Weight.Bold, letter_spacing=-0.1)
        self._font_demo_count   = mono(28, bold=True, letter_spacing=-0.8)
        self._font_demo_unit    = inter(8, QFont.Weight.Black, letter_spacing=1.4)
        self._font_helper       = inter(9, QFont.Weight.Medium)
        self._font_link         = inter(10, QFont.Weight.Bold, letter_spacing=0.4)

        # 3×3 = 9 jingle tiles
        self._tiles: list[_JingleTile] = []
        for i, (name, dur, accent) in enumerate(_JINGLE_TILES_DATA):
            tile = _JingleTile(name, dur, accent, self)
            row = i // 3
            col = i % 3
            x = 14 + col * 132
            y = 110 + row * 78
            tile.move(x, y)
            self._tiles.append(tile)

        # 5 numbered hotkeys (y=346)
        self._hotkeys: list[_JingleHotkey] = []
        for i in range(5):
            hk = _JingleHotkey(i + 1, self)
            hk.move(14 + i * 70, 360)
            self._hotkeys.append(hk)

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        # Panel background
        bg = QLinearGradient(0, 0, 0, self.height())
        bg.setColorAt(0.0, QColor(14, 16, 32, 235))
        bg.setColorAt(1.0, QColor(7, 9, 18, 235))
        p.fillRect(r, QBrush(bg))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 18)))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 12, 12)
        # 3px purple→pink→amber accent at top
        accent = QLinearGradient(0, 0, self.width(), 0)
        accent.setColorAt(0.0, QColor(PURPLE_LIGHT))
        accent.setColorAt(0.5, QColor(PINK))
        accent.setColorAt(1.0, QColor(AMBER))
        p.fillRect(QRectF(0, 0, self.width(), 3), QBrush(accent))

        # Header
        p.setPen(QColor(PURPLE_LIGHT)); p.setFont(self._font_h)
        p.drawText(QRectF(14, 12, 220, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "INSTANT JINGLES")
        # 12 SLOT pill (right of header)
        slot_pill = QRectF(180, 13, 56, 16)
        p.fillRect(slot_pill, _qcolor_a(CYAN, 0.18))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_qcolor_a(CYAN, 0.45)))
        p.drawRoundedRect(slot_pill.adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)
        p.setPen(QColor(CYAN_LIGHT)); p.setFont(self._font_slot_pill)
        p.drawText(slot_pill, Qt.AlignmentFlag.AlignCenter, "12 SLOT")
        # × close button (right)
        p.setPen(QColor(TEXT_DIM)); p.setFont(self._font_close)
        p.drawText(QRectF(self.width() - 22, 8, 14, 18),
                   Qt.AlignmentFlag.AlignCenter, "×")

        # DEMO Sweep PLAYING display
        demo = QRectF(14, 44, self.width() - 28, 56)
        demo_grad = QLinearGradient(demo.topLeft(), demo.bottomLeft())
        demo_grad.setColorAt(0.0, _qcolor_a(GREEN, 0.18))
        demo_grad.setColorAt(1.0, _qcolor_a(GREEN, 0.06))
        p.fillRect(demo, QBrush(demo_grad))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_qcolor_a(GREEN, 0.45)))
        p.drawRoundedRect(demo.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        # PLAYING pill (top-left of demo)
        playing_pill = QRectF(demo.x() + 10, demo.y() + 8, 64, 18)
        p.fillRect(playing_pill, _qcolor_a(GREEN, 0.4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_qcolor_a(GREEN, 0.7)))
        p.drawRoundedRect(playing_pill.adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)
        p.setPen(QColor(255, 255, 255)); p.setFont(self._font_playing_pill)
        p.drawText(playing_pill, Qt.AlignmentFlag.AlignCenter, "PLAYING")
        # Demo label (below pill)
        p.setPen(QColor(GREEN_LIGHT)); p.setFont(self._font_demo_label)
        p.drawText(QRectF(demo.x() + 10, demo.y() + 28, 200, 22),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._demo_label)
        # Big countdown (right side of demo)
        p.setPen(QColor(AMBER_LIGHT)); p.setFont(self._font_demo_count)
        p.drawText(QRectF(demo.right() - 130, demo.y() + 8, 100, 36),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   f"{self._demo_remaining_s:04.1f}")
        # SEC unit
        p.setPen(QColor(GREEN_LIGHT)); p.setFont(self._font_demo_unit)
        p.drawText(QRectF(demo.right() - 28, demo.y() + 22, 26, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "SEC")

        # Helper text below hotkey row
        p.setPen(QColor(TEXT_DIM)); p.setFont(self._font_helper)
        p.drawText(QRectF(14, 412, self.width() - 28, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "Tap any slot to play instantly")
        p.drawText(QRectF(14, 430, self.width() - 28, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "1-5 hotkeys for fast access")

        # Footer separator hairline
        p.fillRect(QRectF(14, 480, self.width() - 28, 1),
                   QColor(255, 255, 255, 20))
        # Edit Bank link (purple, left)
        p.setPen(QColor(PURPLE_LIGHT)); p.setFont(self._font_link)
        p.drawText(QRectF(14, 494, 80, 18),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "Edit Bank")
        p.fillRect(QRectF(14, 514, 64, 1), _qcolor_a(PURPLE_LIGHT, 0.4))
        # "Last played: ..." right
        p.setPen(QColor(TEXT_DIM)); p.setFont(self._font_helper)
        p.drawText(QRectF(100, 494, self.width() - 114, 18),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   f"Last played: {self._last_played_label}")
        p.end()


# ════════════════════════════════════════════════════════════════════════
# HISTORY — 320 × 540 (Figma 325:2)
#
# Header: HISTORY rose + LAST 12 dark pill (right) + 3px rose accent
# 12 rows: timestamp (top, mono muted) + artist - title (bold white)
#         alternating rose / amber-darker tinted backgrounds
# Footer: View Full History → rose link
# ════════════════════════════════════════════════════════════════════════

class _HistoryEntry:
    """Plain data slot for one history row."""
    def __init__(self, time_str: str = "—", artist: str = "",
                 title: str = "", dur: str = ""):
        self.time_str = time_str
        self.artist = artist
        self.title = title
        self.dur = dur


class _HistoryPanel(QWidget):
    """320 × 540 — Last 12 played panel."""

    view_full_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(320, 540)
        self._entries: list[_HistoryEntry] = [_HistoryEntry() for _ in range(12)]

        self._font_h        = inter(11, QFont.Weight.Black, letter_spacing=1.6)
        self._font_count    = mono(9, bold=True, letter_spacing=0.4)
        self._font_time     = mono(8, bold=True, letter_spacing=0.3)
        self._font_track    = inter(11, QFont.Weight.Bold, letter_spacing=-0.1)
        self._font_link     = inter(11, QFont.Weight.Bold, letter_spacing=0.4)

        # Footer link hit zone
        self._link_rect = QRect(14, 500, 200, 28)

    @property
    def entries(self) -> list[_HistoryEntry]:
        return self._entries

    def set_entry(self, idx: int, time_str: str, artist: str,
                  title: str, dur: str = "") -> None:
        if 0 <= idx < len(self._entries):
            self._entries[idx] = _HistoryEntry(time_str, artist, title, dur)
            row_h = 38
            row_y = 38 + idx * row_h
            self.update(QRect(0, row_y, self.width(), row_h))

    def refresh(self) -> None:
        self.update(self.rect())

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if (e.button() == Qt.MouseButton.LeftButton
                and self._link_rect.contains(e.position().toPoint())):
            self.view_full_clicked.emit()
        super().mousePressEvent(e)

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        # Panel background
        bg = QLinearGradient(0, 0, 0, self.height())
        bg.setColorAt(0.0, QColor(14, 16, 32, 235))
        bg.setColorAt(1.0, QColor(7, 9, 18, 235))
        p.fillRect(r, QBrush(bg))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 18)))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 12, 12)
        # 3px rose accent at top
        accent = QLinearGradient(0, 0, self.width(), 0)
        accent.setColorAt(0.0, QColor(RED))
        accent.setColorAt(1.0, _qcolor_a(RED, 0.4))
        p.fillRect(QRectF(0, 0, self.width(), 3), QBrush(accent))

        # Header "HISTORY"
        p.setPen(QColor(RED_LIGHT)); p.setFont(self._font_h)
        p.drawText(QRectF(14, 10, 200, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "HISTORY")
        # LAST 12 pill (right of header)
        last_pill = QRectF(self.width() - 64, 12, 50, 14)
        p.fillRect(last_pill, QColor(7, 8, 16, 178))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 30)))
        p.drawRoundedRect(last_pill.adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)
        p.setPen(QColor(TEXT_SEC)); p.setFont(self._font_count)
        p.drawText(last_pill, Qt.AlignmentFlag.AlignCenter, "LAST 12")

        # 12 rows (y=38, each 38h)
        row_h = 38
        for i, entry in enumerate(self._entries):
            y = 38 + i * row_h
            row_rect = QRectF(8, y, self.width() - 16, row_h - 2)
            # Alternating tint — rose / amber-dim
            if i % 2 == 0:
                p.fillRect(row_rect, _qcolor_a(RED, 0.10))
            else:
                p.fillRect(row_rect, _qcolor_a(AMBER, 0.06))
            # Timestamp (top, mono muted)
            p.setPen(QColor(TEXT_DIM)); p.setFont(self._font_time)
            p.drawText(QRectF(16, y + 4, 120, 14),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       entry.time_str)
            # Artist - Title combined (bold white)
            track_str = (f"{entry.artist} - {entry.title}"
                         if entry.artist and entry.title
                         else entry.title or entry.artist or "—")
            p.setPen(QColor(TEXT_PRI)); p.setFont(self._font_track)
            p.drawText(QRectF(16, y + 18, self.width() - 32, 16),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       track_str)

        # Footer separator hairline
        p.fillRect(QRectF(14, 494, self.width() - 28, 1),
                   QColor(255, 255, 255, 20))
        # View Full History → link
        p.setPen(QColor(RED_LIGHT)); p.setFont(self._font_link)
        p.drawText(QRectF(self._link_rect),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "View Full History →")
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
        if hasattr(self, "_libraries"):
            self._libraries.set_songs(self._queue_songs,
                                       len(self._queue_songs))
        self._refresh_history()
        self._update_status_pills()

        log.info("Studio ready (Figma 312:2 — Step 6: History)")

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
        self._upcoming = _UpComingQueue(self)
        self._upcoming.move(16, BODY_Y)
        self._upcoming.song_double_clicked.connect(self._on_queue_song_play)

        self._libraries = _LibrariesPanel(self)
        self._libraries.move(412, BODY_Y)
        self._libraries.song_double_clicked.connect(
            self._on_library_song_double_clicked)

        self._instant_jingles = _InstantJinglesPanel(self)
        self._instant_jingles.move(1148, BODY_Y)

        self._history_panel = _HistoryPanel(self)
        self._history_panel.move(1584, BODY_Y)

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
            self._refresh_history()
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
        # Up Coming queue: full 5-card refresh from in-memory queue
        if hasattr(self, "_upcoming"):
            self._upcoming.set_queue(self._queue_songs[:5])

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
        # Up Coming: roll the queue starting from the currently-playing
        # song so the playing song is visible at slot 0 and "next" is
        # at slot 1 (NEXT pill).
        if hasattr(self, "_upcoming"):
            cur_id = song.get("id")
            try:
                idx = next(i for i, s in enumerate(self._queue_songs)
                           if s.get("id") == cur_id)
            except StopIteration:
                idx = 0
            self._upcoming.set_queue(self._queue_songs[idx:idx + 5],
                                     current_id=cur_id)

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

    def _refresh_history(self) -> None:
        """Populate the History panel from db.get_history(). Called on
        init + after every spot/song state transition that could have
        written a broadcast_log row."""
        if not hasattr(self, "_history_panel"):
            return
        try:
            rows = self._db.get_history(limit=12)
        except Exception as exc:
            log.debug(f"[studio] history refresh failed: {exc}")
            return
        for i in range(12):
            if i < len(rows):
                r = rows[i]
                keys = r.keys() if hasattr(r, "keys") else []
                time_str = self._fmt_history_time(
                    r["played_at"] if "played_at" in keys else None)
                entry_type = (r["entry_type"] if "entry_type" in keys
                              else "song")
                if entry_type == "spot":
                    title = (r["campaign_name"] if "campaign_name" in keys
                             and r["campaign_name"] else "—")
                    artist = "(spot)"
                else:
                    title = (r["title"] if "title" in keys
                             and r["title"] else "—")
                    artist = (r["artist"] if "artist" in keys
                              and r["artist"] else "")
                dur_ms = (r["duration_ms"] if "duration_ms" in keys
                          and r["duration_ms"] else 0)
                self._history_panel.set_entry(
                    i, time_str, artist, title,
                    _fmt_duration(int(dur_ms or 0)))
            else:
                self._history_panel.set_entry(i, "—", "", "", "")
        self._history_panel.refresh()

    @staticmethod
    def _fmt_history_time(played_at) -> str:
        """Convert sqlite TEXT 'YYYY-MM-DD HH:MM:SS' → 'HH:MM:SS'."""
        if not played_at:
            return "—"
        s = str(played_at)
        if len(s) >= 19 and s[10] == " ":
            return s[11:19]
        return "—"

    # ────────────────────────────────────────────────────────────────────
    # ROUTING
    # ────────────────────────────────────────────────────────────────────

    def _on_control_panel(self) -> None:
        # Premium pattern + legacy back-compat
        self.screen_requested.emit("scheduling_hub")
        self.breadcrumb_clicked.emit("control_panel")

    def _on_settings(self) -> None:
        QMessageBox.information(self, "Settings", "Settings — coming soon.")

    def _on_library_song_double_clicked(self, idx: int) -> None:
        """Library row double-click → if the row maps to a real queue
        song (same index), play it."""
        if 0 <= idx < len(self._queue_songs):
            self._on_queue_song_play(self._queue_songs[idx])

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
