"""
RadioAI Studio Pro — Studio v3 (Figma 312:2 — Premium Jazler Style).

REBUILD COMPLETE — Plan A (Kavish, 2026-05-06):
  ✅ Step 1: 1920×1080 canvas + Header
  ✅ Step 2: Master strip (NowPlayer + NextChip + ControlCluster +
             LevelMeters + ClockFace + Wordmark)
  ✅ Step 3: Up Coming queue (rich track cards)
  ✅ Step 4: Libraries panel (type icons + Action Stack +
             Songs table + Filter + Category)
  ✅ Step 5: Instant Jingles (3×3 tiles + DEMO PLAYING +
             1-5 hotkeys + Edit Bank)
  ✅ Step 6: History panel (12 alternating rows +
             View Full History link)
  ✅ Step 7: Next Break + RDS + Problems trio
  ✅ Step 8: Bottom transport bar (▶/■ + slider + AutoPlay +
             6-button cluster)
  ✅ Step 9: Final integration + cleanup                     ← THIS COMMIT
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
    QPropertyAnimation, pyqtProperty,
)
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QLinearGradient, QRadialGradient,
    QFont, QMouseEvent, QPaintEvent, QShortcut, QKeySequence,
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


def _fmt_jingle_dur(seconds: float) -> str:
    """Jingle tile duration label format — matches the existing 'XX.X'
    style used by the placeholder data ('09.7', '04.2'…). Clamps to
    99.9 because the tile cell is sized for two-digit-dot-decimal."""
    s = max(0.0, float(seconds or 0.0))
    if s >= 99.95:
        return "99.9"
    return f"{s:04.1f}"


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
    auto_clicked          = pyqtSignal()   # Phase C — AUTO pill click

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
        # Active Station card third line — defaults to the station
        # location, replaced with the active clock name (prefixed "● ")
        # when the scheduler resolves a clock for the current cell.
        self._active_clock_name = ""

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

        # Hit zones (kept in sync with paint coordinates in
        # _paint_status_pills — pills at x=1320 + i*72, y=18, 64×32).
        self._cp_btn_rect    = QRect(WINDOW_W - 180, 16, 140, 40)
        self._cog_rect       = QRect(WINDOW_W - 32 - 4, 20, 32, 32)
        self._auto_pill_rect = QRect(1320 + 2 * 72, 18, 64, 32)
        # Visual polish 2/Area 7: AUTO pill pulse halo. Same pattern
        # as NowPlayer's LIVE dot — opacity loops 0.20→0.60→0.20 over
        # 1500ms when scheduler is running. set_auto_mode(True) starts
        # the animation; set_auto_mode(False) stops it. Partial repaint
        # is already scoped to the AUTO pill region only via set_auto_mode.
        self._auto_pulse_alpha: float = 0.0
        self._auto_pulse_anim = QPropertyAnimation(self, b"autoPulseAlpha")
        self._auto_pulse_anim.setDuration(1500)
        self._auto_pulse_anim.setStartValue(0.20)
        self._auto_pulse_anim.setKeyValueAt(0.5, 0.60)
        self._auto_pulse_anim.setEndValue(0.20)
        self._auto_pulse_anim.setLoopCount(-1)

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
        # Visual polish 2/Area 7: spin up / tear down the AUTO pulse
        # animation when the mode flips. Idle state = no animation
        # cost (timer not running).
        if self._auto_mode:
            if self._auto_pulse_anim.state() != QPropertyAnimation.State.Running:
                self._auto_pulse_anim.start()
        else:
            self._auto_pulse_anim.stop()
            self._auto_pulse_alpha = 0.0
        # Repaint the AUTO pill region
        self.update(QRect(1320, 12, 280, 32))

    # ── AUTO pulse property (visual polish 2/Area 7) ────────────────────

    def _get_auto_pulse_alpha(self) -> float:
        return self._auto_pulse_alpha

    def _set_auto_pulse_alpha(self, v: float) -> None:
        self._auto_pulse_alpha = max(0.0, min(1.0, float(v)))
        # Partial repaint scoped to just the AUTO pill region — the
        # whole 1920×72 header NEVER repaints on each pulse frame.
        self.update(self._auto_pill_rect.adjusted(-6, -6, 6, 6))

    autoPulseAlpha = pyqtProperty(float, _get_auto_pulse_alpha,
                                  _set_auto_pulse_alpha)

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

    def set_active_clock(self, name: str) -> None:
        """Update the Active Station card's third-line text to reflect
        the clock currently assigned to this hour. Empty string ('')
        means "no clock assigned" → the card falls back to its default
        location text in paint. Repaint scoped to just the card."""
        v = (name or "").strip()
        if v == self._active_clock_name:
            return
        self._active_clock_name = v
        # Active Station card lives at QRectF(1080, 8, 220, 56) per
        # _paint_active_station — just repaint that region.
        self.update(QRect(1080, 8, 220, 56))

    # ── Mouse ────────────────────────────────────────────────────────────

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            p = e.position().toPoint()
            if self._cp_btn_rect.contains(p):
                self.control_panel_clicked.emit()
            elif self._cog_rect.contains(p):
                self.settings_clicked.emit()
            elif self._auto_pill_rect.contains(p):
                self.auto_clicked.emit()
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
        # Third line — active clock name when assigned, station
        # location otherwise. Prefix '● ' on the active-clock variant
        # so the operator distinguishes a live clock-driven hour from
        # the idle fallback at a glance. Color stays TEXT_SEC for both
        # variants so the visual rhythm of the card is unchanged.
        if self._active_clock_name:
            third_line_text = f"● {self._active_clock_name}"
        else:
            third_line_text = "Jaipur, Rajasthan"
        p.setPen(QColor(TEXT_SEC)); p.setFont(self._font_station_s)
        p.drawText(QRectF(card.x() + 12, card.y() + 38, 200, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   third_line_text)
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
            # Visual polish 2/Area 7: AUTO pulse halo. Painted BEFORE
            # the pill body so it sits behind. Alpha driven by the
            # _auto_pulse_alpha property animation (active only when
            # _auto_mode is True; otherwise alpha stays 0 → no draw).
            if i == 2 and self._auto_pulse_alpha > 0.0:
                halo = QRadialGradient(r.center(), 28)
                halo.setColorAt(0.0,
                    _qcolor_a(PURPLE_LIGHT, self._auto_pulse_alpha))
                halo.setColorAt(0.6,
                    _qcolor_a(PURPLE, self._auto_pulse_alpha * 0.4))
                halo.setColorAt(1.0, _qcolor_a(PURPLE, 0.0))
                p.setBrush(QBrush(halo)); p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(r.center(), 28, 28)
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
    # LIVE-dot pulse rect — repaints clip to this region only so the
    # 25Hz animation never re-renders the full 836×88 panel.
    _LIVE_DOT_RECT = QRect(160, 12, 110, 18)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(836, 88)
        self._idle = True
        self._title = "—"
        self._artist_year = ""
        self._elapsed_ms = 0
        self._total_ms = 0
        self._progress = 0.0    # 0..1

        # Visual polish 4: LIVE dot pulse. Halo opacity animates over a
        # 1500ms loop via QPropertyAnimation on the custom property.
        # Setter stamps a partial-repaint of just the dot rect — the
        # 836×88 NowPlayer NEVER fully redraws on each frame.
        self._live_halo_alpha: float = 0.35
        self._live_pulse_anim = QPropertyAnimation(self, b"liveHaloAlpha")
        self._live_pulse_anim.setDuration(1500)
        self._live_pulse_anim.setStartValue(0.30)
        self._live_pulse_anim.setKeyValueAt(0.5, 0.70)
        self._live_pulse_anim.setEndValue(0.30)
        self._live_pulse_anim.setLoopCount(-1)
        self._live_pulse_anim.start()

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

    # ── LIVE dot pulse property ──────────────────────────────────────────

    def _get_live_halo_alpha(self) -> float:
        return self._live_halo_alpha

    def _set_live_halo_alpha(self, v: float) -> None:
        self._live_halo_alpha = max(0.0, min(1.0, float(v)))
        # Partial repaint — only the dot region. Skipping the full
        # panel keeps the pulse cheap even at 60fps.
        self.update(self._LIVE_DOT_RECT)

    liveHaloAlpha = pyqtProperty(float, _get_live_halo_alpha, _set_live_halo_alpha)

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
        # Repaint just the elapsed-time and waveform regions.
        # Waveform rect widened upward to include the playhead top
        # dot + halo (visual polish 2/Area 5) which sits at y≈53..65.
        self.update(QRect(530, 14, 280, 30))    # elapsed/total/rem block
        self.update(QRect(102, 50, 720, 38))    # waveform + playhead halo

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
        # Visual polish 2/Area 6: 3px solid-green top accent stripe so
        # NowPlayer matches the visual rhythm of the other panels
        # (every other panel has a 3px top accent; only NowPlayer +
        # NextChip didn't).
        p.fillRect(QRectF(0, 0, self.width(), 3), QColor(GREEN))

        # Vinyl (left, ~80h - centered)
        cx, cy = 56, 44
        rad_outer = 30
        # Visual polish 3: ambient halo BEHIND the vinyl rings. Soft
        # green falloff that gives the album-art region a glow without
        # changing the existing concentric-ring composition.
        halo_grad = QRadialGradient(QPointF(cx, cy), rad_outer + 12)
        halo_grad.setColorAt(0.0, _qcolor_a(GREEN_LIGHT, 0.30))
        halo_grad.setColorAt(0.6, _qcolor_a(GREEN, 0.12))
        halo_grad.setColorAt(1.0, _qcolor_a(GREEN, 0.0))
        p.setBrush(QBrush(halo_grad)); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), rad_outer + 12, rad_outer + 12)
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
        # ● ON AIR · LIVE indicator (visual polish 4: pulsing halo)
        if not self._idle:
            # Outer halo — radial green glow whose alpha is driven by
            # the QPropertyAnimation on liveHaloAlpha (1.5s loop). The
            # halo sits behind a solid 4px green dot, identical to
            # before for the dot itself.
            halo = QRadialGradient(QPointF(166, 21), 12)
            halo.setColorAt(0.0, _qcolor_a(GREEN_LIGHT, self._live_halo_alpha))
            halo.setColorAt(0.5, _qcolor_a(GREEN, self._live_halo_alpha * 0.5))
            halo.setColorAt(1.0, _qcolor_a(GREEN, 0.0))
            p.setBrush(QBrush(halo)); p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(166, 21), 12, 12)
            # Solid dot
            p.setBrush(QColor(GREEN_LIGHT))
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
        # Playhead — vertical white line with green glow + top dot.
        # Visual polish 2/Area 5: stronger glow (radial halo around the
        # line, not just the fade-out at top/bottom), plus a 4×4 white
        # head dot floating above the waveform with its own green halo.
        if self._progress > 0:
            ph_x = wf_x + wf_w * self._progress
            # Glow halo — soft green radial centered on the bar mid
            halo_r = 14
            halo = QRadialGradient(QPointF(ph_x, wf_y + wf_h / 2), halo_r)
            halo.setColorAt(0.0, _qcolor_a(GREEN_LIGHT, 0.55))
            halo.setColorAt(0.5, _qcolor_a(GREEN, 0.20))
            halo.setColorAt(1.0, _qcolor_a(GREEN, 0.0))
            p.setBrush(QBrush(halo)); p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(ph_x, wf_y + wf_h / 2),
                          halo_r, halo_r)
            # Vertical playhead line — 2px white core, full height of
            # the waveform region (no top/bot fade — the halo handles
            # that softly via the radial gradient above).
            playhead = QRectF(ph_x - 1, wf_y - 2, 2, wf_h + 4)
            p.fillRect(playhead, QColor(255, 255, 255))
            # Top dot — 4×4 white circle just above the playhead, with
            # its own green halo so the position read is unmistakable
            # at a glance from across the studio.
            dot_cy = wf_y - 5
            dot_halo = QRadialGradient(QPointF(ph_x, dot_cy), 6)
            dot_halo.setColorAt(0.0, _qcolor_a(GREEN_LIGHT, 0.7))
            dot_halo.setColorAt(1.0, _qcolor_a(GREEN, 0.0))
            p.setBrush(QBrush(dot_halo)); p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(ph_x, dot_cy), 6, 6)
            p.setBrush(QColor(255, 255, 255))
            p.drawEllipse(QPointF(ph_x, dot_cy), 2, 2)


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
        # Visual polish 2/Area 6: 3px solid-rose top accent stripe to
        # match the visual rhythm of the other panels.
        p.fillRect(QRectF(0, 0, self.width(), 3), QColor(RED))
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
        # Visual polish 2/Area 7: when a ControlButton enters its
        # active state (Pause when paused, Loop when looping), attach
        # an accent-tinted drop shadow halo so the button visibly
        # lights up. Toggled off → effect cleared. Single effect per
        # widget (Qt limitation), no conflict with other graphics
        # effects since the base button carries none.
        if self._active:
            halo = QGraphicsDropShadowEffect(self)
            c = QColor(self._accent)
            c.setAlpha(180)
            halo.setBlurRadius(20)
            halo.setColor(c)
            halo.setOffset(0, 0)
            self.setGraphicsEffect(halo)
        else:
            self.setGraphicsEffect(None)
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

    def set_stop_armed(self, on: bool) -> None:
        """Visual feedback for the StopNext button — when armed, the
        button shows the same accent-glow treatment as Loop/Pause's
        active state. Cleared when the EOS handler consumes the flag
        (current song ended → player idled) or the operator clicks
        StopNext again to disarm."""
        self._b_stop.set_active(bool(on))

    def is_stop_armed(self) -> bool:
        return self._b_stop._active

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

    def set_queue(self, songs: list[dict], current_id: Optional[int] = None,
                  next_index: int = 1) -> None:
        """Populate cards. AT timestamps cumulative from now. The card
        at ``next_index`` is rendered as NEXT (rose glow + NEXT pill).

        ``next_index`` defaults to 1 — legacy mode where index 0 is the
        currently-playing song and index 1 is what plays next.
        Phase B's scheduler-driven path uses ``next_index=0`` because
        ``peek_next`` returns items the scheduler WILL dispatch — the
        currently-playing item is not in the list, so index 0 IS the
        next-to-air."""
        cum_s = 0
        for i, card in enumerate(self._cards):
            if i < len(songs):
                song = songs[i]
                at_text = _fmt_at_clock(cum_s)
                card.set_song(song, is_next=(i == next_index),
                              at_text=at_text)
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
    # "Sweepers" replaces the placeholder "Folders" tile so the operator
    # can browse + manually fire sweeper overlays on the deck. Glyph
    # matches Clock Editor's sweeper symbol (★) for cross-screen recall.
    ("Sweepers",  "★",  PURPLE_LIGHT, False),
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
                # Visual polish 2/Area 7: 3px cyan left-edge accent
                # strip on the selected row — operator's eye locks
                # onto the highlighted song instantly.
                p.fillRect(QRectF(0, ry, 3, self.ROW_H), QColor(CYAN))
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
    # Phase 2 of sweeper-ecosystem wiring: the type-tile click now also
    # tells the Studio host to swap the table contents (songs ↔ sweepers
    # ↔ jingles ↔ etc.). Studio listens, fetches the right list from
    # DB, and calls set_songs / set_sweepers as appropriate.
    library_type_changed = pyqtSignal(str)   # tile name (e.g. "Sweepers")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(720, 820)
        self._rows: list[_LibSongRow] = []
        self._total_song_count = 0
        # Currently-active type tile. Used by the Studio host to know
        # how to interpret a row double-click. Default matches the
        # initial active=True entry in _LIB_TYPE_ICONS ("Songs").
        self._active_type: str = "Songs"

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
        if name == self._active_type:
            return
        for k, tile in self._type_tiles.items():
            tile.set_active(k == name)
        self._active_type = name
        self.library_type_changed.emit(name)

    def active_library_type(self) -> str:
        return self._active_type

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
# Phase A — wired to core.instant_jingle_engine via Studio. Tile labels
# + durations bind to real jingle_pads rows from db.get_jingle_pads_active()
# (capped at 9). Tile accent colors stay per-index from the table below
# (visual fidelity preserved). Click + 1-5 hotkeys + Esc-for-stop-all
# routed through Studio's _instant_jingle_engine.
# ════════════════════════════════════════════════════════════════════════

# Tile accent palette (per-index visual). Real label + duration come
# from DB at construction; if fewer than 9 pads exist, the trailing
# tiles render with label="Empty" and click is a no-op.
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

    def set_label(self, name: str, dur_str: str) -> None:
        """Phase A: refresh tile text from real DB pad data without
        rebuilding the widget. Layout/colors/sizes untouched."""
        if name == self._name and dur_str == self._dur_str:
            return
        self._name = name
        self._dur_str = dur_str
        self.update(self.rect())

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
    """420 × 540 — full Instant Jingles panel.

    Phase A: tile labels + DEMO display update via public methods
    driven by Studio. Click signals carry tile index / hotkey number /
    Edit Bank — Studio dispatches to the InstantJingleEngine."""

    tile_clicked      = pyqtSignal(int)   # tile index 0..N-1
    hotkey_clicked    = pyqtSignal(int)   # hotkey number 1..5
    edit_bank_clicked = pyqtSignal()

    # Geometry of the DEMO display box — used for partial repaint so the
    # 10Hz countdown doesn't re-paint the whole panel.
    _DEMO_RECT = QRect(14, 44, 420 - 28, 56)
    # Edit Bank hit-test rect (matches paintEvent coords).
    _EDIT_BANK_RECT = QRect(14, 494, 80, 18)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(420, 540)
        self._demo_label = ""
        self._demo_remaining_s = 0.0
        self._demo_active = False
        self._last_played_label = "—"

        self._font_h            = inter(11, QFont.Weight.Black, letter_spacing=1.6)
        self._font_slot_pill    = mono(8, bold=True, letter_spacing=0.5)
        self._font_close        = inter(13, QFont.Weight.Bold)
        self._font_playing_pill = inter(8, QFont.Weight.Black, letter_spacing=1.4)
        self._font_demo_label   = inter(13, QFont.Weight.Bold, letter_spacing=-0.1)
        self._font_demo_count   = mono(28, bold=True, letter_spacing=-0.8)
        self._font_demo_unit    = inter(8, QFont.Weight.Black, letter_spacing=1.4)
        self._font_helper       = inter(9, QFont.Weight.Medium)
        self._font_link         = inter(10, QFont.Weight.Bold, letter_spacing=0.4)

        # 3×3 = 9 jingle tiles. Default labels from the placeholder table;
        # Studio overwrites these via set_tiles() with real DB pad data.
        self._tiles: list[_JingleTile] = []
        for i, (name, dur, accent) in enumerate(_JINGLE_TILES_DATA):
            tile = _JingleTile(name, dur, accent, self)
            row = i // 3
            col = i % 3
            x = 14 + col * 132
            y = 110 + row * 78
            tile.move(x, y)
            tile.clicked.connect(lambda idx=i: self.tile_clicked.emit(idx))
            self._tiles.append(tile)

        # 5 numbered hotkeys (y=360)
        self._hotkeys: list[_JingleHotkey] = []
        for i in range(5):
            hk = _JingleHotkey(i + 1, self)
            hk.move(14 + i * 70, 360)
            hk.clicked.connect(self.hotkey_clicked.emit)
            self._hotkeys.append(hk)

    # ── Public API ───────────────────────────────────────────────────────

    def set_tiles(self, pads: list[dict]) -> None:
        """Bind tile labels + durations to real DB pad rows. `pads` is a
        list of dicts with keys 'label', 'duration_ms'. Trailing tiles
        beyond len(pads) render as 'Empty' (no-op on click)."""
        for i, tile in enumerate(self._tiles):
            if i < len(pads):
                lbl = (pads[i].get("label") or "—").strip() or "—"
                dur_s = (int(pads[i].get("duration_ms") or 0)) / 1000.0
                tile.set_label(lbl, _fmt_jingle_dur(dur_s))
            else:
                tile.set_label("Empty", "—")

    def set_demo_active(self, label: str, total_seconds: float) -> None:
        """A pad just started — show its label + remaining countdown."""
        self._demo_label = label or ""
        self._demo_remaining_s = max(0.0, float(total_seconds))
        self._demo_active = True
        self._last_played_label = label or self._last_played_label
        self.update(self._DEMO_RECT)

    def update_demo_remaining(self, remaining_seconds: float) -> None:
        """Driven by Studio's 10Hz countdown timer. Repaints DEMO rect only."""
        self._demo_remaining_s = max(0.0, float(remaining_seconds))
        self.update(self._DEMO_RECT)

    def set_demo_inactive(self) -> None:
        """A pad ended/stopped — clear the DEMO display."""
        self._demo_active = False
        self._demo_label = ""
        self._demo_remaining_s = 0.0
        self.update(self._DEMO_RECT)

    def mousePressEvent(self, e: QMouseEvent) -> None:
        # Edit Bank link is decorative drawn text; surface a click via
        # hit-test so it can route to the standalone Instant Jingles
        # screen without adding a separate widget.
        if (e.button() == Qt.MouseButton.LeftButton
                and self._EDIT_BANK_RECT.contains(e.pos())):
            self.edit_bank_clicked.emit()
            return
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

        # DEMO Sweep PLAYING display (frame always drawn; inner content
        # only when a pad is actively playing, so an idle Studio doesn't
        # falsely advertise PLAYING).
        demo = QRectF(14, 44, self.width() - 28, 56)
        demo_grad = QLinearGradient(demo.topLeft(), demo.bottomLeft())
        demo_grad.setColorAt(0.0, _qcolor_a(GREEN, 0.18))
        demo_grad.setColorAt(1.0, _qcolor_a(GREEN, 0.06))
        p.fillRect(demo, QBrush(demo_grad))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_qcolor_a(GREEN, 0.45)))
        p.drawRoundedRect(demo.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        if self._demo_active:
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
# NEXT BREAK — 420 × 264 (Figma 326:2)
#
# NEXT BREAK header amber + COUNTING DOWN muted right
# Big amber "04:43" countdown 60pt mono center
# 3 stat columns: BREAK TYPE / DURATION / SPOTS
# 2 buttons: × Skip Break rose + ▶ Preview cyan
# ════════════════════════════════════════════════════════════════════════

class _NextBreakPanel(QWidget):
    skip_clicked = pyqtSignal()
    preview_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(420, 264)
        self._countdown_s = 0
        self._countdown_label = "00:00"
        self._break_type = "Commercial"
        self._break_dur = "2:30"
        self._spots = 5

        self._font_h        = inter(13, QFont.Weight.Black, letter_spacing=1.4)
        self._font_status   = inter(9, QFont.Weight.Bold, letter_spacing=1.6)
        self._font_count    = mono(60, bold=True, letter_spacing=-2.0)
        self._font_stat_l   = inter(9, QFont.Weight.Bold, letter_spacing=1.4)
        self._font_stat_v   = inter(13, QFont.Weight.Bold, letter_spacing=-0.1)
        self._font_btn      = inter(11, QFont.Weight.Bold, letter_spacing=0.4)

        self._skip_rect    = QRect(14, 210, 192, 38)
        self._preview_rect = QRect(214, 210, 192, 38)

    def set_countdown(self, seconds: int) -> None:
        self._countdown_s = int(seconds or 0)
        if self._countdown_s < 0:
            self._countdown_label = "00:00"
        else:
            m = self._countdown_s // 60
            s = self._countdown_s % 60
            self._countdown_label = f"{m:02d}:{s:02d}"
        self.update(self.rect())

    def set_break_meta(self, break_type: str, dur: str, spots: int) -> None:
        self._break_type = break_type or "—"
        self._break_dur = dur or "—"
        self._spots = int(spots or 0)
        self.update(self.rect())

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            pt = e.position().toPoint()
            if self._skip_rect.contains(pt):
                self.skip_clicked.emit()
            elif self._preview_rect.contains(pt):
                self.preview_clicked.emit()
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
        p.setPen(QPen(_qcolor_a(AMBER, 0.30)))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 12, 12)
        # 3px amber accent at top
        accent = QLinearGradient(0, 0, self.width(), 0)
        accent.setColorAt(0.0, QColor(AMBER))
        accent.setColorAt(1.0, _qcolor_a(AMBER, 0.4))
        p.fillRect(QRectF(0, 0, self.width(), 3), QBrush(accent))

        # Header "NEXT BREAK"
        p.setPen(QColor(AMBER_LIGHT)); p.setFont(self._font_h)
        p.drawText(QRectF(14, 14, 200, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "NEXT BREAK")
        # COUNTING DOWN status (right)
        p.setPen(QColor(TEXT_DIM)); p.setFont(self._font_status)
        p.drawText(QRectF(self.width() - 140, 14, 126, 16),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   "COUNTING DOWN")

        # Big countdown
        p.setPen(QColor(AMBER_LIGHT)); p.setFont(self._font_count)
        p.drawText(QRectF(0, 50, self.width(), 80),
                   Qt.AlignmentFlag.AlignCenter, self._countdown_label)

        # 3-column stat block
        col_w = (self.width() - 28) / 3
        cols = [
            ("BREAK TYPE", self._break_type),
            ("DURATION",   self._break_dur),
            ("SPOTS",      str(self._spots)),
        ]
        for i, (label, value) in enumerate(cols):
            cx = 14 + i * col_w
            p.setPen(QColor(TEXT_DIM)); p.setFont(self._font_stat_l)
            p.drawText(QRectF(cx, 158, col_w, 14),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       label)
            p.setPen(QColor(TEXT_PRI)); p.setFont(self._font_stat_v)
            p.drawText(QRectF(cx, 174, col_w, 18),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       value)

        # × Skip Break button (rose outline)
        skip = QRectF(self._skip_rect)
        p.fillRect(skip, _qcolor_a(RED, 0.18))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_qcolor_a(RED, 0.50)))
        p.drawRoundedRect(skip.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        p.setPen(QColor(RED_LIGHT)); p.setFont(self._font_btn)
        p.drawText(skip, Qt.AlignmentFlag.AlignCenter, "×  Skip Break")

        # ▶ Preview button (cyan outline)
        prev = QRectF(self._preview_rect)
        p.fillRect(prev, _qcolor_a(CYAN, 0.18))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_qcolor_a(CYAN, 0.50)))
        p.drawRoundedRect(prev.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        p.setPen(QColor(CYAN_LIGHT)); p.setFont(self._font_btn)
        p.drawText(prev, Qt.AlignmentFlag.AlignCenter, "▶  Preview")
        p.end()


# ════════════════════════════════════════════════════════════════════════
# RDS — 320 × 152 (Figma 326:18)
#
# RDS LIVE green + Settings cyan link
# Big cyan "21:55" + ON-AIR TAG green tiny label
# Track box bottom: artist + title in green-bordered card
# ════════════════════════════════════════════════════════════════════════

class _RDSPanel(QWidget):
    settings_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(320, 152)
        self._artist = "—"
        self._title = ""

        self._font_h       = inter(11, QFont.Weight.Black, letter_spacing=1.6)
        self._font_settings = inter(10, QFont.Weight.Bold, letter_spacing=0.4)
        self._font_clock   = mono(28, bold=True, letter_spacing=-1.0)
        self._font_tag     = inter(8, QFont.Weight.Black, letter_spacing=2.0)
        self._font_artist  = inter(11, QFont.Weight.Bold, letter_spacing=-0.1)
        self._font_title   = inter(10, QFont.Weight.Medium)

        self._settings_rect = QRect(self.width() - 80, 10, 70, 16)

    def set_on_air(self, artist: str, title: str) -> None:
        self._artist = str(artist or "—")
        self._title = str(title or "")
        self.update(self.rect())

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if (e.button() == Qt.MouseButton.LeftButton
                and self._settings_rect.contains(e.position().toPoint())):
            self.settings_clicked.emit()
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
        p.setPen(QPen(_qcolor_a(GREEN, 0.30)))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 12, 12)
        # 3px green→cyan accent at top
        accent = QLinearGradient(0, 0, self.width(), 0)
        accent.setColorAt(0.0, QColor(GREEN))
        accent.setColorAt(1.0, QColor(CYAN))
        p.fillRect(QRectF(0, 0, self.width(), 3), QBrush(accent))

        # Header "RDS LIVE"
        p.setPen(QColor(GREEN_LIGHT)); p.setFont(self._font_h)
        p.drawText(QRectF(14, 10, 100, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "RDS LIVE")
        # Settings link (right)
        p.setPen(QColor(CYAN_LIGHT)); p.setFont(self._font_settings)
        p.drawText(QRectF(self._settings_rect),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   "Settings")
        p.fillRect(QRectF(self._settings_rect.x() + 14, 26, 56, 1),
                   _qcolor_a(CYAN_LIGHT, 0.4))

        # Big clock + ON-AIR TAG
        now = datetime.now()
        clock_text = now.strftime("%H:%M")
        p.setPen(QColor(CYAN_LIGHT)); p.setFont(self._font_clock)
        p.drawText(QRectF(14, 36, 110, 36),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   clock_text)
        # ON-AIR TAG label (right of clock)
        p.setPen(QColor(GREEN_LIGHT)); p.setFont(self._font_tag)
        p.drawText(QRectF(124, 50, 100, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "ON-AIR TAG")

        # Track box (bottom, green-bordered)
        track_box = QRectF(14, 88, self.width() - 28, 50)
        p.fillRect(track_box, QColor(7, 8, 16, 178))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_qcolor_a(GREEN, 0.40)))
        p.drawRoundedRect(track_box.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        # Artist
        p.setPen(QColor(TEXT_PRI)); p.setFont(self._font_artist)
        p.drawText(QRectF(track_box.x() + 12, track_box.y() + 6,
                          track_box.width() - 24, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._artist)
        # Title
        p.setPen(QColor(GREEN_LIGHT)); p.setFont(self._font_title)
        p.drawText(QRectF(track_box.x() + 12, track_box.y() + 24,
                          track_box.width() - 24, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._title)
        p.end()


# ════════════════════════════════════════════════════════════════════════
# PROBLEMS — 320 × 96 (Figma 326:31)
#
# PROBLEMS amber + N badge + Details cyan link
# Warning row: ⚠ Spot break collision at 22:15 (amber on dark)
# ════════════════════════════════════════════════════════════════════════

class _ProblemsPanel(QWidget):
    details_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(320, 96)
        self._items: list[str] = ["Spot break collision at 22:15"]

        self._font_h       = inter(11, QFont.Weight.Black, letter_spacing=1.6)
        self._font_badge   = mono(13, bold=True, letter_spacing=-0.3)
        self._font_details = inter(10, QFont.Weight.Bold, letter_spacing=0.4)
        self._font_item    = inter(10, QFont.Weight.Medium)

        self._details_rect = QRect(self.width() - 76, 10, 66, 16)

    def set_problems(self, items: list[str]) -> None:
        self._items = list(items or [])
        self.update(self.rect())

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if (e.button() == Qt.MouseButton.LeftButton
                and self._details_rect.contains(e.position().toPoint())):
            self.details_clicked.emit()
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
        p.setPen(QPen(_qcolor_a(AMBER, 0.30)))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 12, 12)
        # 3px amber accent at top
        p.fillRect(QRectF(0, 0, self.width(), 3),
                   _qcolor_a(AMBER, 0.85))

        # Header "PROBLEMS"
        p.setPen(QColor(AMBER_LIGHT)); p.setFont(self._font_h)
        p.drawText(QRectF(14, 10, 130, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "PROBLEMS")
        # N badge (right of header label)
        n = len(self._items)
        if n > 0:
            badge = QRectF(110, 12, 22, 14)
            color = AMBER if n > 0 else GREEN
            p.fillRect(badge, _qcolor_a(color, 0.30))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(_qcolor_a(color, 0.55)))
            p.drawRoundedRect(badge.adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)
            p.setPen(QColor(AMBER_LIGHT)); p.setFont(self._font_badge)
            p.drawText(badge, Qt.AlignmentFlag.AlignCenter, str(n))
        # Details → link (right)
        p.setPen(QColor(CYAN_LIGHT)); p.setFont(self._font_details)
        p.drawText(QRectF(self._details_rect),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   "Details →")

        # First item shown as a warning row (amber-tinted)
        if self._items:
            row = QRectF(14, 36, self.width() - 28, 44)
            p.fillRect(row, _qcolor_a(AMBER, 0.10))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(_qcolor_a(AMBER, 0.40)))
            p.drawRoundedRect(row.adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
            p.setPen(QColor(AMBER_LIGHT)); p.setFont(self._font_item)
            p.drawText(QRectF(row.x() + 14, row.y(),
                              row.width() - 28, row.height()),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       f"⚠  {self._items[0]}")
        else:
            p.setPen(QColor(TEXT_DIM)); p.setFont(self._font_item)
            p.drawText(QRectF(14, 36, self.width() - 28, 44),
                       Qt.AlignmentFlag.AlignCenter,
                       "All systems nominal")
        p.end()


# ════════════════════════════════════════════════════════════════════════
# BOTTOM TRANSPORT — 1920 × 80 (Figma 327:2)
#
# Left:    LOADED PLAYLIST + big amber time + $ pill + ≡ menu
# Center:  ▶ play (big green circle) + ■ stop (red) + slider with time
#          label + AutoPlay toggle
# Right:   6-button cluster Up / Down / Stop All / Auto / MixFa.. / Loop
# ════════════════════════════════════════════════════════════════════════

class _CircleBtn(QWidget):
    """Big circular transport button (▶ play green / ■ stop red)."""

    clicked = pyqtSignal()

    def __init__(self, glyph: str, accent: str, size: int = 52, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._glyph = glyph; self._accent = accent
        self._enabled = True
        self._font = inter(18, QFont.Weight.Black)
        if accent == GREEN:
            self.setGraphicsEffect(_drop_shadow(20, _qcolor_a(GREEN, 0.45), 6))

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
        if self._enabled:
            grad = QLinearGradient(0, 0, 0, self.height())
            grad.setColorAt(0.0, _qcolor_a(self._accent, 0.95))
            grad.setColorAt(1.0, _qcolor_a(self._accent, 0.55))
            p.setBrush(QBrush(grad))
        else:
            p.setBrush(_qcolor_a(self._accent, 0.10))
        p.setPen(QPen(_qcolor_a(self._accent, 0.5 if self._enabled else 0.15)))
        cx, cy = self.width() / 2, self.height() / 2
        p.drawEllipse(QPointF(cx, cy),
                      self.width() / 2 - 1, self.height() / 2 - 1)
        p.setPen(QColor(255, 255, 255) if self._enabled else QColor(TEXT_DIM))
        p.setFont(self._font)
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._glyph)
        p.end()


class _ProgressSlider(QWidget):
    """Progress slider with cyan→purple gradient + time label above."""

    seek_requested = pyqtSignal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(380, 50)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._progress = 0.0
        self._enabled = False
        self._elapsed_s = 0
        self._total_s = 0
        self._font = mono(9, bold=True)

    def set_enabled(self, on: bool) -> None:
        self._enabled = bool(on)
        self.setCursor(Qt.CursorShape.PointingHandCursor if on
                       else Qt.CursorShape.ArrowCursor)
        self.update(self.rect())

    def set_progress(self, frac: float, elapsed_s: int = 0,
                     total_s: int = 0) -> None:
        f = max(0.0, min(1.0, float(frac)))
        self._progress = f
        self._elapsed_s = int(elapsed_s)
        self._total_s = int(total_s)
        self.update(self.rect())

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if self._enabled and e.button() == Qt.MouseButton.LeftButton:
            x = e.position().toPoint().x()
            self.seek_requested.emit(max(0.0, min(1.0, x / self.width())))
        super().mousePressEvent(e)

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Time label "MM:SS / MM:SS" mono
        e_m = self._elapsed_s // 60; e_s = self._elapsed_s % 60
        t_m = self._total_s // 60;   t_s = self._total_s % 60
        p.setPen(QColor(TEXT_DIM)); p.setFont(self._font)
        p.drawText(QRectF(0, 8, 100, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   f"{e_m:02d}:{e_s:02d}  /  {t_m:02d}:{t_s:02d}")
        # Track
        track = QRectF(0, 32, self.width(), 6)
        p.fillRect(track, QColor(255, 255, 255, 22))
        # Fill
        if self._progress > 0:
            fill = QRectF(0, 32, self.width() * self._progress, 6)
            grad = QLinearGradient(0, 0, fill.width(), 0)
            grad.setColorAt(0.0, QColor(CYAN))
            grad.setColorAt(1.0, QColor(PURPLE_LIGHT))
            p.fillRect(fill, QBrush(grad))
            cx = fill.right()
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(CYAN_LIGHT))
            p.drawEllipse(QPointF(cx, 35), 7, 7)
        p.end()


class _AutoPlayToggle(QWidget):
    toggled = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(110, 36)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._on = False
        self._font = inter(11, QFont.Weight.Bold, letter_spacing=0.4)

    def is_on(self) -> bool: return self._on
    def set_on(self, on: bool) -> None:
        self._on = bool(on); self.update(self.rect())

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
        p.setPen(QColor(TEXT_PRI if self._on else TEXT_SEC))
        p.setFont(self._font)
        p.drawText(QRectF(0, 0, 70, self.height()),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "AutoPlay")
        # Toggle pill
        pill = QRectF(72, 10, 36, 16)
        color = GREEN if self._on else TEXT_DIM
        p.fillRect(pill, _qcolor_a(color, 0.30))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_qcolor_a(color, 0.50)))
        p.drawRoundedRect(pill.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        # Knob
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(GREEN_LIGHT) if self._on else QColor(TEXT_SEC))
        knob_x = 100 if self._on else 80
        p.drawEllipse(QPointF(knob_x, 18), 6, 6)
        p.end()


class _ClusterBtn(QWidget):
    """One of the 6 right-cluster buttons (Up/Down/StopAll/Auto/MixFa/Loop)."""

    clicked = pyqtSignal()

    def __init__(self, label: str, glyph: str, accent: str, parent=None):
        super().__init__(parent)
        self.setFixedSize(80, 56)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._label = label; self._glyph = glyph
        self._accent = accent
        self._enabled = True
        self._font_glyph = inter(15, QFont.Weight.Black)
        self._font_label = inter(9, QFont.Weight.Bold, letter_spacing=0.4)

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if self._enabled and e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        p.fillRect(r, _qcolor_a(self._accent, 0.20))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_qcolor_a(self._accent, 0.50)))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        p.setPen(QColor(self._accent)); p.setFont(self._font_glyph)
        p.drawText(QRectF(0, 4, self.width(), 24),
                   Qt.AlignmentFlag.AlignCenter, self._glyph)
        p.setFont(self._font_label)
        p.drawText(QRectF(0, 32, self.width(), 18),
                   Qt.AlignmentFlag.AlignCenter, self._label)
        p.end()


class _BottomTransport(QWidget):
    play_clicked      = pyqtSignal()
    stop_clicked      = pyqtSignal()
    seek_requested    = pyqtSignal(float)
    autoplay_toggled  = pyqtSignal(bool)
    up_clicked        = pyqtSignal()
    down_clicked      = pyqtSignal()
    stop_all_clicked  = pyqtSignal()
    auto_clicked      = pyqtSignal()
    mixfade_clicked   = pyqtSignal()
    loop_clicked      = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(WINDOW_W, BOTTOM_TRANS_H)
        self._loaded_total = "0:00:00"
        self._font_load_lbl = inter(8, QFont.Weight.Bold, letter_spacing=1.4)
        self._font_load_val = mono(20, bold=True, letter_spacing=-0.5)

        # Center transport
        self._play = _CircleBtn("▶", GREEN, 56, self)
        self._play.move(380, 12)
        self._play.clicked.connect(self.play_clicked.emit)

        self._stop = _CircleBtn("■", RED, 44, self)
        self._stop.move(450, 18)
        self._stop.clicked.connect(self.stop_clicked.emit)

        self._slider = _ProgressSlider(self)
        self._slider.move(510, 14)
        self._slider.seek_requested.connect(self.seek_requested.emit)

        self._autoplay = _AutoPlayToggle(self)
        self._autoplay.move(910, 22)
        self._autoplay.toggled.connect(self.autoplay_toggled.emit)

        # 6-button right cluster (each 80×56, gap 8)
        cluster_x0 = 1080
        clusters = [
            ("Up",       "▲", CYAN,         self.up_clicked),
            ("Down",     "▼", CYAN,         self.down_clicked),
            ("Stop All", "■", RED,          self.stop_all_clicked),
            ("Auto",     "◉", PURPLE_LIGHT, self.auto_clicked),
            ("MixFa..",  "⌒", AMBER,        self.mixfade_clicked),
            ("Loop",     "↻", PURPLE_LIGHT, self.loop_clicked),
        ]
        for i, (label, glyph, color, signal) in enumerate(clusters):
            b = _ClusterBtn(label, glyph, color, self)
            b.move(cluster_x0 + i * 88, 12)
            b.clicked.connect(signal.emit)

    def set_loaded_total(self, txt: str) -> None:
        if txt == self._loaded_total:
            return
        self._loaded_total = txt
        self.update(QRect(0, 0, 360, self.height()))

    def set_progress(self, frac: float, elapsed_s: int = 0,
                     total_s: int = 0) -> None:
        self._slider.set_progress(frac, elapsed_s, total_s)

    def set_transport_enabled(self, on: bool) -> None:
        self._play.set_enabled(on)
        self._stop.set_enabled(on)
        self._slider.set_enabled(on)

    def is_autoplay_on(self) -> bool:
        return self._autoplay.is_on()

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        # Background
        bg = QLinearGradient(0, 0, 0, self.height())
        bg.setColorAt(0.0, QColor(14, 16, 32, 235))
        bg.setColorAt(1.0, QColor(7, 9, 18, 235))
        p.fillRect(r, QBrush(bg))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 18)))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 12, 12)

        # Loaded Playlist label
        p.setPen(QColor(GREEN_LIGHT)); p.setFont(self._font_load_lbl)
        p.drawText(QRectF(20, 14, 200, 12),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "LOADED PLAYLIST")
        # Big total time
        p.setPen(QColor(AMBER_LIGHT)); p.setFont(self._font_load_val)
        p.drawText(QRectF(20, 30, 220, 28),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._loaded_total)
        # $ pill (green)
        dollar = QRectF(220, 22, 38, 36)
        dg = QLinearGradient(0, 22, 0, 58)
        dg.setColorAt(0.0, _qcolor_a(GREEN, 0.30))
        dg.setColorAt(1.0, _qcolor_a(GREEN, 0.10))
        p.fillRect(dollar, QBrush(dg))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_qcolor_a(GREEN, 0.45)))
        p.drawRoundedRect(dollar.adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
        p.setPen(QColor(GREEN_LIGHT))
        p.setFont(inter(15, QFont.Weight.Bold))
        p.drawText(dollar, Qt.AlignmentFlag.AlignCenter, "$")
        # ≡ menu
        menu = QRectF(266, 22, 38, 36)
        p.fillRect(menu, QColor(7, 8, 16, 178))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 30)))
        p.drawRoundedRect(menu.adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
        p.setPen(QColor(TEXT_SEC))
        p.setFont(inter(15, QFont.Weight.Bold))
        p.drawText(menu, Qt.AlignmentFlag.AlignCenter, "≡")
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

    def __init__(self, db, parent=None, engine=None, scheduler=None,
                 instant_jingle_engine=None, sweeper_engine=None):
        super().__init__(parent)
        self._db = db
        self._engine = engine
        self._scheduler = scheduler
        self._instant_jingle_engine = instant_jingle_engine
        # Sweeper overlay player — separate BASS channel that layers on
        # top of the deck. Optional kwarg keeps the existing tests' shorter
        # ctor signatures green; MainWindow injects the shared instance so
        # manual sweeper plays from the Libraries panel and scheduler-
        # dispatched sweeper slots both go through the same overlay path.
        self._sweeper_engine = sweeper_engine
        # Jingle pad cache: list of dicts {id, label, file_path,
        # duration_ms, volume, behaviour} — populated from
        # db.get_jingle_pads_active() at construction, capped at 9 to
        # match the 3×3 tile grid. Used by tile-click + hotkey dispatch
        # and by the DEMO display lookup on pad_started.
        self._jingle_pads: list[dict] = []
        # 10Hz countdown timer for the DEMO display. Lives for the full
        # session; started when a pad begins, stopped on pad_ended/stopped.
        self._jingle_demo_timer: Optional[QTimer] = None
        self._jingle_demo_remaining_s: float = 0.0
        # Phase B: scheduler-driven Up Coming preview. peek_next(5)
        # output translated to the card-friendly dict shape, refreshed
        # on scheduler signals + the 1Hz wall-clock tick. Empty when
        # no scheduler is wired or no clock is currently assigned —
        # in that case the legacy _queue_songs[:5] fallback path runs.
        self._upcoming_preview: list[dict] = []
        # Phase C: auto-advance master switch. Default True preserves
        # the legacy "always advance on EOS" behavior the existing
        # 9 Studio EOS-path tests assert. Turning it off (via the AUTO
        # header pill) puts Studio in Live-Assist mode — operator must
        # click Play after each track ends. AUTO pill click toggles
        # both this flag AND scheduler.start/stop together so the two
        # stay in lockstep.
        self._auto_advance_enabled: bool = True
        # Auto-start scheduler on Studio showEvent when a clock is
        # assigned to the current (weekday, hour) cell. Once the operator
        # explicitly stops via the AUTO pill, this flag latches True and
        # blocks subsequent showEvent auto-starts within the same app
        # session — respecting their Live-Assist intent. App restart
        # resets the flag (False) so the next session re-arms auto-start.
        self._operator_stopped_auto: bool = False
        # Visual polish 1: cached background gradients drawn from
        # paintEvent. Linear base (top→bottom) + 3 large radial glow
        # ellipses (purple TR, cyan BL, green mid) that give the
        # screen its premium-broadcast atmospheric depth without
        # adding any DOM widgets.
        self._bg_linear = QLinearGradient(0, 0, 0, WINDOW_H)
        self._bg_linear.setColorAt(0.0, QColor("#0a0d1a"))
        self._bg_linear.setColorAt(0.5, QColor("#06080f"))
        self._bg_linear.setColorAt(1.0, QColor("#020308"))
        # Purple radial — top-right
        self._bg_glow_purple = QRadialGradient(QPointF(1800, -200), 700)
        c_purple_in  = QColor("#8b5cf6"); c_purple_in.setAlphaF(0.16)
        c_purple_out = QColor("#8b5cf6"); c_purple_out.setAlphaF(0.0)
        self._bg_glow_purple.setColorAt(0.0, c_purple_in)
        self._bg_glow_purple.setColorAt(1.0, c_purple_out)
        # Cyan radial — bottom-left
        self._bg_glow_cyan = QRadialGradient(QPointF(100, 1100), 700)
        c_cyan_in  = QColor("#06b6d4"); c_cyan_in.setAlphaF(0.14)
        c_cyan_out = QColor("#06b6d4"); c_cyan_out.setAlphaF(0.0)
        self._bg_glow_cyan.setColorAt(0.0, c_cyan_in)
        self._bg_glow_cyan.setColorAt(1.0, c_cyan_out)
        # Green radial — mid-screen subtle glow
        self._bg_glow_green = QRadialGradient(QPointF(1100, 750), 600)
        c_green_in  = QColor("#10b981"); c_green_in.setAlphaF(0.06)
        c_green_out = QColor("#10b981"); c_green_out.setAlphaF(0.0)
        self._bg_glow_green.setColorAt(0.0, c_green_in)
        self._bg_glow_green.setColorAt(1.0, c_green_out)
        self.setFixedSize(WINDOW_W, WINDOW_H)
        # Visual polish 1: bg now painted in paintEvent so we can
        # composite the linear base + 3 radial glows. Stylesheet bg
        # removed — it would have layered over the radial pass.

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
        # Deferred spot dispatch — when scheduler fires spot_due during
        # an actively-playing deck song, we cache the campaign here
        # instead of interrupting. Song EOS path (d) consumes it and
        # plays the spot before auto-advancing to the next song.
        # None = no pending spot. Cleared on stop-next, loop, and
        # AUTO-off (operator-takes-control transitions).
        self._pending_spot_campaign_id: Optional[int] = None
        # Rapid-fire log_play guard — broadcast_log was getting duplicate
        # rows when an EOS-error loop (file fails to play → EOS fires
        # immediately → auto-advance picks the same song from a single-
        # slot clock → loops 9× in one second). 5-second same-song guard
        # prevents the duplicate clutter without affecting legitimate
        # spaced replays.
        self._last_song_log_id: Optional[int] = None
        self._last_song_log_time = None  # datetime, populated on first log
        # Active-clock indicator dedupe — Studio owns its own "what's
        # currently displayed" state so the indicator can refresh from
        # multiple paths (scheduler signal when AUTO is on, Studio's
        # 1Hz tick always, showEvent on navigate-back, AUTO toggle)
        # without flickering or double-rendering. -2 sentinel means
        # "never set" so the first resolved state always emits.
        self._displayed_active_clock_id: int = -2
        # Played-songs tracking — tracks song ids that have been
        # dispatched (play-started) since Studio launch. Used by the
        # Up Coming panel's fallback path to filter out songs that
        # have already aired so the panel only shows TRULY upcoming
        # tracks, not the currently-playing or already-played ones.
        # Scheduler-driven path is unaffected (peek_next already
        # advances past dispatched slots).
        self._played_song_ids: set = set()
        self._queue_songs: list[dict] = self._load_queue_from_db()

        # Build widgets — Steps 1+2 done; rest are placeholders
        self._build_header()
        self._build_master_strip()
        self._build_body_placeholders()
        self._build_bottom_transport_placeholder()
        # Visual polish 2: tinted drop shadows on every major panel so
        # they float above the atmospheric bg with depth.
        self._apply_panel_shadows()

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
            # Phase B: refresh Up Coming preview whenever the scheduler
            # state changes meaningfully. Belt + suspenders alongside
            # the 1Hz live AT tick — covers manual mutations the timer
            # might lag, plus avoids stale data after start/stop cycles.
            self._scheduler.song_auto_advance.connect(
                self._load_upcoming_queue)
            self._scheduler.started.connect(self._load_upcoming_queue)
            self._scheduler.stopped.connect(self._load_upcoming_queue)
            # Hour-boundary active-clock indicator. Signal fires only on
            # transitions; clock_id == -1 + name == "" means "no clock
            # assigned to this hour" — header falls back to the
            # station-location text in that case. Defensive
            # ``hasattr`` so older _FakeScheduler test doubles that
            # predate this signal don't crash on construct — additive
            # backward compat for the existing Phase B/C wiring tests.
            if hasattr(self._scheduler, "active_clock_changed"):
                self._scheduler.active_clock_changed.connect(
                    self._on_active_clock_changed)

        # Phase A — InstantJingleEngine signal connections + jingle pad
        # bindings + 1-5 hotkeys + Esc-for-stop-all.
        self._wire_instant_jingles()

        # 1Hz tick for header clock
        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(1000)
        self._tick_timer.timeout.connect(self._on_tick)
        self._tick_timer.start()
        self._on_tick()

        # Initial state
        self._load_upcoming_queue()        # Phase B — populate first
        self._apply_idle_state()
        if hasattr(self, "_libraries"):
            self._libraries.set_songs(self._queue_songs,
                                       len(self._queue_songs))
        self._refresh_history()
        self._update_status_pills()
        # Seed the Active Clock indicator from any value the scheduler
        # has already cached. Safe pre-tick (returns (None, "")) — the
        # header just shows the location fallback until the first
        # active_clock_changed signal arrives.
        self._seed_active_clock_indicator()

        log.info("Studio ready (Figma 312:2 — Premium Jazler Style)")

    # ── Widget builders ──────────────────────────────────────────────────

    def _build_header(self) -> None:
        self._header = _Header(self)
        self._header.move(0, 0)
        self._header.control_panel_clicked.connect(self._on_control_panel)
        self._header.settings_clicked.connect(self._on_settings)
        self._header.auto_clicked.connect(self._on_auto_pill_clicked)

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
        # Phase 2 sweeper wiring: type-tile click swaps the table source
        # between songs / sweepers / etc. Studio caches the resolved row
        # list so row-double-click can dispatch correctly.
        self._library_sweepers: list[dict] = []
        self._libraries.library_type_changed.connect(
            self._on_library_type_changed)

        self._instant_jingles = _InstantJinglesPanel(self)
        self._instant_jingles.move(1148, BODY_Y)

        self._history_panel = _HistoryPanel(self)
        self._history_panel.move(1584, BODY_Y)

        self._next_break = _NextBreakPanel(self)
        self._next_break.move(1148, BODY_Y + 556)

        self._rds = _RDSPanel(self)
        self._rds.move(1584, BODY_Y + 556)

        self._problems = _ProblemsPanel(self)
        self._problems.move(1584, BODY_Y + 712)

    def _apply_panel_shadows(self) -> None:
        """Attach a tinted drop shadow per major panel. The color is a
        dark variant of the panel's accent so the halo reinforces the
        panel's identity (NowPlayer green, Instant Jingles purple,
        etc.). Single QGraphicsDropShadowEffect per widget — Qt's
        graphics-effect pipeline only supports one effect per widget,
        so we pick one that conveys both depth (offset) and accent
        (color tint).

        Performance: drop shadows are GPU-rendered; setting them on
        nine 540h-820h panels is well within budget. Call once at
        construction; effects persist for the widget lifetime."""
        # (panel attribute, blur radius, RGBA color, dy offset)
        shadow_specs: list[tuple[str, int, QColor, int]] = [
            ("_now_player",       28, QColor(16, 185, 129, 110), 8),  # green
            ("_next_chip",        20, QColor(244,  63,  94, 100), 6),  # rose
            ("_upcoming",         28, QColor(245, 158,  11,  90), 8),  # amber
            ("_libraries",        28, QColor( 6, 182, 212,  90), 8),   # cyan
            ("_instant_jingles",  26, QColor(139,  92, 246, 110), 8),  # purple
            ("_history_panel",    24, QColor(244,  63,  94,  90), 8),  # rose
            ("_next_break",       24, QColor(245, 158,  11, 100), 8),  # amber
            ("_rds",              22, QColor( 16, 185, 129,  90), 6),  # green
            ("_problems",         20, QColor(245, 158,  11,  80), 6),  # amber
        ]
        for attr, blur, color, dy in shadow_specs:
            widget = getattr(self, attr, None)
            if widget is None:
                continue
            eff = QGraphicsDropShadowEffect(widget)
            eff.setBlurRadius(blur)
            eff.setColor(color)
            eff.setOffset(0, dy)
            widget.setGraphicsEffect(eff)

    def _build_bottom_transport_placeholder(self) -> None:
        self._bottom = _BottomTransport(self)
        self._bottom.move(0, BOTTOM_TRANS_Y)
        # Phase C: ▶ play_clicked routes to the new _on_play_clicked
        # (idle → start queue + auto-on scheduler; playing → pause/resume
        # toggle). ■ stop_clicked routes to the narrow deck-only stop
        # so jingle pads stay alive. The right-cluster Stop All button
        # (stop_all_clicked) keeps its broader cleanup_all semantic.
        self._bottom.play_clicked.connect(self._on_play_clicked)
        self._bottom.stop_clicked.connect(self._on_deck_stop)
        self._bottom.seek_requested.connect(self._on_bottom_seek)
        self._bottom.up_clicked.connect(self._on_up_clicked)
        self._bottom.down_clicked.connect(self._on_down_clicked)
        self._bottom.stop_all_clicked.connect(self._on_stop_all_clicked)
        # Compute total queue duration for "LOADED PLAYLIST" header
        total_ms = sum(int(s.get("duration_ms") or 0)
                       for s in self._queue_songs)
        s_total = total_ms // 1000
        h, rem = divmod(s_total, 3600)
        m, ss = divmod(rem, 60)
        self._bottom.set_loaded_total(f"{h}:{m:02d}:{ss:02d}")

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
            self._current_track = None
            self._apply_idle_state()
            self._update_status_pills()
            return
        path = song.get("file_path")
        if not path or not os.path.exists(path):
            # Defensive: _compute_next_song already filters bad files
            # but a stale path on a manually-loaded queue song could
            # still land here. Idle the UI rather than leaving the
            # operator with a phantom "now playing" tile.
            log.warning(f"[studio] file missing: {path!r}")
            self._current_track = None
            self._apply_idle_state()
            self._update_status_pills()
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
        # Sync the StopNext armed-state visual with the flag — a fresh
        # song load means the previous arm (if any) has already been
        # honoured or cancelled, so the button reverts to idle look.
        if hasattr(self, "_control_cluster") and self._control_cluster:
            self._control_cluster.set_stop_armed(False)
        # Track this song as "played" so the Up Coming panel's
        # fallback path filters it out — currently-playing should
        # not appear in the upcoming list (it's audibly the now,
        # not the next).
        if song.get("id") is not None:
            try:
                self._played_song_ids.add(int(song["id"]))
            except (TypeError, ValueError):
                pass
        self._apply_playing_state(song)
        self._update_status_pills()

        # Always write a broadcast_log row, regardless of whether the
        # play came from scheduler dispatch or a manual operator action.
        # Pre-fix: only scheduler-driven plays (with _clock_id) logged,
        # so Live-Assist sessions, library double-clicks, and ▶ Play
        # from idle never appeared in the History panel. log_play
        # accepts Optional clock_id / slot_idx so legacy/manual plays
        # land cleanly with NULL attribution columns.
        #
        # Rapid-fire guard: skip log_play if the same song id was just
        # logged within the last 5 seconds. Prevents the rapid-fire EOS
        # loop pattern (file errors out 0ms in → auto-advance picks
        # same song from single-slot clock → repeats) from polluting
        # broadcast_log with duplicate rows that swamp the History
        # panel. Spots are NOT guarded — back-to-back spots from
        # different campaigns are legitimate.
        from datetime import datetime as _dt, timedelta as _td
        clock_id  = song.get("_clock_id")
        slot_idx  = song.get("_slot_idx")
        item_type = song.get("_item_type", "song")
        was_manual = 0 if clock_id is not None else 1
        song_id = (int(song.get("id"))
                   if (item_type == "song" and song.get("id")) else None)
        now_dt = _dt.now()
        skip_log = False
        if (item_type == "song" and song_id is not None
                and self._last_song_log_id == song_id
                and self._last_song_log_time is not None
                and now_dt - self._last_song_log_time < _td(seconds=5)):
            skip_log = True
            log.warning(
                f"[studio] skipping duplicate log for song {song_id} "
                f"(< 5s since last log) — likely EOS-loop guard")
        if not skip_log:
            try:
                self._db.log_play(
                    entry_type=item_type,
                    song_id=song_id,
                    duration_ms=int(self._current_duration_ms),
                    deck="A",
                    was_manual=was_manual,
                    clock_id=int(clock_id) if clock_id is not None else None,
                    slot_idx=int(slot_idx) if slot_idx is not None else None,
                )
                if item_type == "song" and song_id is not None:
                    self._last_song_log_id = song_id
                    self._last_song_log_time = now_dt
            except Exception as exc:
                log.warning(f"[studio] {item_type} log_play failed: {exc}")
        # Refresh the History panel so the just-started track appears
        # at the top immediately, not on the next spot-EOS event.
        self._refresh_history()

        log.info(
            f"[studio] deck play ch={cid} {item_type} id={song.get('id')} "
            f"{song.get('title')!r} dur_ms={self._current_duration_ms}"
            + (f" — scheduler clock_id={clock_id}"
               if clock_id else " — manual"))

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
        # Step 8: drive bottom-transport progress slider
        if hasattr(self, "_bottom") and self._bottom is not None:
            dur = self._current_duration_ms
            frac = (position_ms / dur) if dur > 0 else 0.0
            self._bottom.set_progress(
                frac, position_ms // 1000, dur // 1000)

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
            # Drop any deferred spot — operator pressed stop-next, they
            # want silence after this song ends, not an auto-fired ad.
            if self._pending_spot_campaign_id is not None:
                log.info(
                    f"[studio] stop-next dropped pending spot "
                    f"{self._pending_spot_campaign_id}")
                self._pending_spot_campaign_id = None
            # Visual armed-state revert — the button stops glowing red
            # since the flag has been consumed.
            if hasattr(self, "_control_cluster") and self._control_cluster:
                self._control_cluster.set_stop_armed(False)
            log.info("[studio] stop-next consumed → idle")
            self._apply_idle_state()
            self._update_status_pills()
            return

        # (c) loop replays
        if (kind == "deck" and self._loop_enabled and pre_track is not None):
            log.info(f"[studio] loop replay → {pre_track.get('title')!r}")
            # Drop pending spot — loop is an "intentionally repeat this
            # song" instruction; pinning a spot inside a loop would be
            # a surprise interrupt the operator didn't ask for.
            if self._pending_spot_campaign_id is not None:
                log.info(
                    f"[studio] loop dropped pending spot "
                    f"{self._pending_spot_campaign_id}")
                self._pending_spot_campaign_id = None
            self._on_queue_song_play(pre_track)
            return

        # (d) auto-advance — gated on _auto_advance_enabled (Phase C).
        # Default True preserves the legacy "always advance" behavior
        # that the existing 9 Studio EOS-path tests depend on. The
        # AUTO header pill flips this off → Live-Assist mode where
        # operator must click Play after each track ends.
        if kind == "deck" and self._auto_advance_enabled:
            # Deferred spot fires here BEFORE auto-advancing to next
            # song. _pre_spot_song_id is set from the just-ended track
            # so the spot's own EOS path (a) resumes from the right
            # anchor in the queue. _do_scheduler_spot_due sees
            # _playback_cid is None (we just cleaned up above) so it
            # takes the "play immediately" path, not the defer path.
            if self._pending_spot_campaign_id is not None:
                pending = self._pending_spot_campaign_id
                self._pending_spot_campaign_id = None
                if pre_track is not None:
                    self._pre_spot_song_id = pre_track.get("id")
                log.info(
                    f"[studio] song EOS → playing deferred spot {pending}")
                self._do_scheduler_spot_due(pending)
                return
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
        if kind == "deck" and not self._auto_advance_enabled:
            log.info("[studio] EOS — Live-Assist mode, idle until next play click")
            self._current_track = None
            self._apply_idle_state()
            self._update_status_pills()
            return

        # Defensive
        self._current_track = None
        self._apply_idle_state()
        self._update_status_pills()

    def _compute_next_song(self, after_id: Optional[int]) -> Optional[dict]:
        """Pull the next deck-bound item from the scheduler, falling back
        to the static `_queue_songs` list when the scheduler is idle.

        Sweeper handling — position-aware with sequential fallback:
          • Overlay-style positions (Start of Song / Before Intro /
            Before End / Bridge at End / Custom) attempt to layer on
            the currently-playing deck song. If the deck has a song,
            fire the overlay and skip-past so the next picker cycle
            returns a true deck candidate. Bounded by
            ``_SWEEPER_SKIP_BUDGET`` so a malformed clock can't
            infinite-recurse.
          • If the deck is idle when the sweeper lands (the typical
            case at song-end EOS), the sweeper falls through to the
            deck-load path and plays sequentially in queue order —
            exactly as the operator scheduled it. This is the case
            that RR_SW was hitting before the fix.
          • Position == "Independent" always falls through to deck-
            load (it's an explicit "play standalone" marker).

        Future enhancement: a scheduler peek-ahead at song-START would
        let overlay-positioned sweepers fire DURING the previous song
        (the original Jazler semantic). That's deferred — sequential
        play is what matches the operator's mental model today and
        what the scheduler API supports without a refactor.
        """
        # Skip budget covers both overlay-sweeper consumption AND
        # broken-file skip-past. A clock with one or two misconfigured
        # rows (sweeper without file, song with missing file_path) must
        # not stall the broadcast — keep walking the cursor for up to
        # _SKIP_BUDGET extra items per dispatch. After that, fall back
        # to the static queue and log loudly so the operator can find
        # the broken row.
        _SKIP_BUDGET = 6
        if self._scheduler is not None and self._scheduler.is_running():
            from datetime import datetime as _dt
            for _ in range(_SKIP_BUDGET + 1):
                try:
                    item = self._scheduler.pick_next_item(_dt.now())
                except Exception as exc:
                    log.warning(f"[studio] scheduler.pick_next_item: {exc}")
                    item = None
                if item is None:
                    break
                item_type = (item.get("item_type") or "song").strip().lower()
                if item_type == "sweeper":
                    position = (item.get("position") or "").strip()
                    overlay_positions = ("Start of Song", "Before Intro",
                                          "Before End", "Bridge at End",
                                          "Custom Position", "Custom")
                    can_overlay = (
                        self._sweeper_engine is not None
                        and self._playback_cid is not None
                        and self._current_track
                        and position in overlay_positions
                    )
                    if can_overlay:
                        # Layer on currently-playing song. Loop continues
                        # so the next picker cycle returns a deck item.
                        self._dispatch_overlay_sweeper(item)
                        continue
                    # Sequential fallback — load this sweeper into the
                    # deck just like a song so it plays in its assigned
                    # slot order. Falls through to the song-dict build
                    # below (item_type stays 'sweeper' so log_play +
                    # tags route correctly).
                    log.info(
                        f"[studio] sweeper id={item.get('item_id')!r} "
                        f"position={position!r} → deck-load "
                        f"(deck idle / Independent / no engine)")
                # Validate file_path BEFORE returning — empty or missing
                # files will short-circuit _on_queue_song_play with no
                # next-item retry, stalling the broadcast (RR_SW
                # regression 2026-05-07: operator added a sweeper via
                # the Add dialog without picking an audio file; auto-
                # advance landed on it, _on_queue_song_play warned
                # "file missing" and the player stopped). Skip-past
                # within the same loop's budget so the cursor walks to
                # the next valid item.
                fp = item.get("file_path")
                if not fp or not os.path.exists(fp):
                    log.warning(
                        f"[studio] dispatch skipped {item_type} id="
                        f"{item.get('item_id')!r} — file_path missing "
                        f"or invalid: {fp!r}. Cursor advanced; "
                        f"check this row in the library editor.")
                    continue
                song = {
                    "id":          item.get("item_id"),
                    "title":       item.get("title"),
                    "artist":      item.get("artist"),
                    "file_path":   fp,
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
            # Either no item or exhausted skip budget: fall through to
            # static-queue fallback (matches the original idle-scheduler
            # behaviour).
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
    # Non-destructive preview (NEXT chip, RDS) — uses scheduler.peek_next
    # so the cursor does NOT advance on every UI refresh
    # ────────────────────────────────────────────────────────────────────
    #
    # Audit incident (2026-05-07): _compute_next_song calls
    # scheduler.pick_next_item which permanently advances
    # _clock_slot_cursor. Three display-only call sites (NEXT chip pre-
    # populate in _apply_idle_state, RDS panel in same, NEXT chip refresh
    # in _apply_playing_state) were each calling _compute_next_song for
    # preview purposes — every song-start triggered a cursor advance,
    # so slots were being consumed twice (once for the preview, once for
    # the real dispatch). Result: live broadcast skipped slots in pairs;
    # operator (Kavish) saw the NEXT chip show a stale title while the
    # Up Coming queue (peek_next-driven, already non-destructive) showed
    # the correct order.

    def _peek_next_for_display(self,
                               after_id: Optional[int]
                               ) -> Optional[dict]:
        """Display-only preview of the next deck-bound item. Uses
        scheduler.peek_next so the cursor does NOT mutate. Mirrors the
        sweeper-skip logic of _compute_next_song so the previewed item
        is what would actually land on the deck (overlay-style sweepers
        get skipped past since they wouldn't take the deck slot)."""
        # Scheduler-idle path: same static-queue lookup as
        # _compute_next_song's fallback branch.
        if not (self._scheduler is not None and self._scheduler.is_running()):
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

        # Live scheduler — use the non-destructive peek and skip-past
        # any overlay-style sweepers (they'd be eaten by the overlay
        # path during real dispatch, not loaded to the deck).
        try:
            items = self._scheduler.peek_next(5) or []
        except Exception as exc:
            log.debug(f"[studio] peek_next for NEXT-chip failed: {exc}")
            items = []

        overlay_positions = ("Start of Song", "Before Intro",
                              "Before End", "Bridge at End",
                              "Custom Position", "Custom")
        deck_has_song = (self._sweeper_engine is not None
                         and self._playback_cid is not None
                         and self._current_track)

        for item in items:
            item_type = (item.get("item_type") or "song").strip().lower()
            if item_type == "sweeper":
                position = (item.get("position") or "").strip()
                if deck_has_song and position in overlay_positions:
                    # Would overlay during real dispatch → skip in preview
                    continue
            return {
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
        # Peek empty (no clock assigned to current hour, or every
        # peeked slot was an overlay sweeper) → static fallback so the
        # chip still shows something meaningful.
        if not self._queue_songs:
            return None
        return self._queue_songs[0]

    # ────────────────────────────────────────────────────────────────────
    # Sweeper overlay dispatch (Phase 1 wiring — auto + manual share path)
    # ────────────────────────────────────────────────────────────────────

    def _dispatch_overlay_sweeper(self, item: dict) -> None:
        """Layer a sweeper on top of the currently-playing deck song.

        Called from two paths that share the same overlay semantics:
          • _compute_next_song when scheduler returns item_type='sweeper'
            (auto dispatch, slot-driven from a clock pattern)
          • _on_play_sweeper_overlay (manual click from the Libraries panel)

        No-ops gracefully when SweeperEngine is not wired (tests with the
        shorter Studio ctor signature) or when nothing is on the deck —
        a sweeper has nothing to overlay if the deck is silent. The slot
        cursor still advances either way (caller already moved past).
        """
        if self._sweeper_engine is None:
            log.warning("[studio] sweeper item arrived but no "
                        "SweeperEngine wired — skipping overlay")
            return
        if self._playback_cid is None or not self._current_track:
            log.info("[studio] sweeper skipped — deck idle "
                     "(no song to overlay)")
            return
        try:
            song_info = {
                "duration_ms":  int(self._current_duration_ms or 0),
                "intro_end_ms": int(
                    self._current_track.get("intro_end_ms")
                    or self._current_track.get("_intro_end_ms")
                    or 0),
            }
            sweeper_info = {
                "file_path":         item.get("file_path"),
                "duration_ms":       int(item.get("duration_ms") or 0),
                "position":          item.get("position")
                                      or item.get("_position")
                                      or "Bridge at End",
                "sweeper_volume":    int(item.get("volume_sweeper_pct")
                                          or item.get("sweeper_volume")
                                          or 100),
                "position_offset":   float(item.get("offset_seconds")
                                            or item.get("position_offset")
                                            or 0.0),
            }
            self._sweeper_engine.schedule_for_song(
                song_info, sweeper_info, self._playback_cid)
            log.info(
                f"[studio] sweeper overlay scheduled: "
                f"id={item.get('item_id')!r} "
                f"file={(sweeper_info['file_path'] or '')[-32:]!r} "
                f"position={sweeper_info['position']!r} "
                f"vol={sweeper_info['sweeper_volume']}%")
        except Exception as exc:
            log.warning(f"[studio] sweeper overlay failed: {exc}",
                        exc_info=True)
            return
        # Log to broadcast_log so History panel reflects the play.
        # Manual sweepers carry no clock metadata; auto-dispatched ones
        # have item['clock_id']/['slot_idx'] populated by the scheduler.
        try:
            self._db.log_play(
                entry_type="sweeper",
                song_id=None,                 # sweepers aren't songs
                duration_ms=int(item.get("duration_ms") or 0),
                deck="A",
                was_manual=0 if item.get("clock_id") else 1,
                clock_id=int(item["clock_id"]) if item.get("clock_id") else None,
                slot_idx=int(item["slot_idx"]) if item.get("slot_idx")
                                                   is not None else None,
            )
        except Exception as exc:
            log.warning(f"[studio] sweeper log_play failed: {exc}")

    def _on_play_sweeper_overlay(self, sweeper_id: int) -> None:
        """Manual sweeper play hook — fired from the Libraries panel
        when the operator clicks a sweeper while a song is on the deck.
        Pulls the row from DB and routes through the same overlay path
        the auto-dispatch uses."""
        try:
            row = self._db._conn().execute(
                "SELECT * FROM sweepers WHERE id = ? AND is_enabled = 1",
                [int(sweeper_id)]).fetchone()
        except Exception as exc:
            log.warning(f"[studio] manual sweeper lookup failed: {exc}")
            return
        if row is None:
            log.warning(f"[studio] manual sweeper id={sweeper_id} "
                        f"not found or disabled")
            return
        keys = row.keys()
        item = {
            "item_type":          "sweeper",
            "item_id":            int(row["id"]),
            "file_path":          row["file_path"]   if "file_path"   in keys else "",
            "duration_ms":        row["duration_ms"] if "duration_ms" in keys else 0,
            "position":           row["position"]    if "position"    in keys else None,
            "volume_sweeper_pct": row["volume_sweeper_pct"]
                                    if "volume_sweeper_pct" in keys else 100,
            "offset_seconds":     row["offset_seconds"]
                                    if "offset_seconds"     in keys else 0.0,
            "clock_id":           None,   # manual play — no slot context
            "slot_idx":           None,
        }
        self._dispatch_overlay_sweeper(item)

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
        # Deferred dispatch — when a song is currently playing on the
        # deck, do NOT interrupt. Cache the campaign id; song EOS path
        # (d) will consume it and play the spot before auto-advancing.
        # Operator's listener never hears a mid-song hard-cut.
        if (self._playback_kind == "deck"
                and self._playback_cid is not None
                and self._current_track is not None):
            if (self._pending_spot_campaign_id is not None
                    and self._pending_spot_campaign_id != int(campaign_id)):
                log.warning(
                    f"[studio] overwriting pending spot "
                    f"{self._pending_spot_campaign_id} with {campaign_id} "
                    f"(only the most-recent is queued)")
            self._pending_spot_campaign_id = int(campaign_id)
            log.info(
                f"[studio] spot {campaign_id} deferred — "
                f"current song will play out, then spot fires")
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
        # Push the spot's track info to NowPlayer / NextChip / RDS /
        # ControlCluster / BottomTransport. Without this call the visual
        # state stays on the previous song's name even though the spot
        # is audibly playing — operator + listener (via on-air display)
        # would see misleading metadata. Same call the deck path does
        # in _on_queue_song_play.
        self._apply_playing_state(self._current_track)
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
        # Refresh History panel so the spot row appears at the top
        # immediately on play-start, not just on the next spot-EOS.
        self._refresh_history()
        log.info(f"[studio] auto-spot ch={cid} campaign={campaign_id} "
                 f"file={os.path.basename(path)} "
                 f"dur={self._current_duration_ms}ms")
        self._update_status_pills()

    def _on_scheduler_song_advance(self) -> None:
        log.info("[studio] scheduler: song_auto_advance")

    def _on_scheduler_break_warn(self, seconds_until: int) -> None:
        log.info(f"[studio] scheduler: break_approaching in {seconds_until}s")

    def _on_scheduler_next_break_in(self, seconds: int) -> None:
        if hasattr(self, "_next_break") and self._next_break is not None:
            self._next_break.set_countdown(seconds)

    def _on_active_clock_changed(self, clock_id: int, name: str) -> None:
        """Scheduler resolved a different clock for the current cell —
        route through the same dedupe state Studio's own 1Hz tick
        uses. The scheduler's signal-driven path still works when AUTO
        is on; Studio's own tick covers the AUTO-off case."""
        self._set_displayed_active_clock(int(clock_id), name or "")

    def _seed_active_clock_indicator(self) -> None:
        """Pull whatever active clock the scheduler has already cached
        and push it to the header. Safe to call before any tick has
        run — getter returns (None, "") in that case and the header
        falls back to the location text."""
        if self._scheduler is None or not hasattr(self, "_header"):
            return
        try:
            cid, name = self._scheduler.current_active_clock()
        except Exception as exc:
            log.debug(f"[studio] seed active clock failed: {exc}")
            return
        if cid is not None and cid >= 0 and name:
            self._header.set_active_clock(name)

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
        if hasattr(self, "_bottom"):
            self._bottom.set_progress(0.0, 0, 0)
            self._bottom.set_transport_enabled(False)
        # NEXT chip: pre-populate from queue head so the panel isn't blank.
        # Uses peek (non-destructive) — historical bug was that the
        # display refresh advanced the scheduler cursor, eating slots
        # before they could be dispatched. See _peek_next_for_display.
        if hasattr(self, "_next_chip"):
            head = self._peek_next_for_display(after_id=None)
            if head is not None:
                self._next_chip.set_next(
                    str(head.get("title") or "—"),
                    str(head.get("artist") or ""),
                    to_air_s=0,
                    intro_s=0)
            else:
                self._next_chip.set_next("—", "")
        # Up Coming queue: full 5-card refresh.
        #   Phase B: prefer scheduler.peek_next preview when available;
        #   fall back to legacy in-memory queue when no scheduler is
        #   wired or no clock is currently assigned (peek returned []).
        if hasattr(self, "_upcoming"):
            self._refresh_upcoming_panel()
        # RDS panel: idle = queue head as next-up label. Uses peek
        # (non-destructive) — historical bug was the same cursor-eat
        # pattern as the NEXT chip.
        if hasattr(self, "_rds"):
            head = self._peek_next_for_display(after_id=None)
            if head is not None:
                self._rds.set_on_air(
                    str(head.get("artist") or "—"),
                    str(head.get("title") or ""))
            else:
                self._rds.set_on_air("—", "")

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
        if hasattr(self, "_bottom"):
            self._bottom.set_transport_enabled(True)
        # NEXT chip = the song after this one in the queue. Uses peek
        # (non-destructive) — calling _compute_next_song here was eating
        # a scheduler slot per song-start (audit 2026-05-07), so the
        # NEXT chip drifted out of sync with the Up Coming queue.
        if hasattr(self, "_next_chip"):
            nxt = self._peek_next_for_display(after_id=song.get("id"))
            if nxt is not None:
                self._next_chip.set_next(
                    str(nxt.get("title") or "—"),
                    str(nxt.get("artist") or ""))
            else:
                self._next_chip.set_next("—", "")
        # Up Coming: STRICTLY upcoming view — currently-playing song
        # is excluded (it lives in NowPlayer, not in the queue list).
        # _refresh_upcoming_panel filters _played_song_ids, which
        # includes this song's id (just added in _on_queue_song_play).
        # Scheduler-driven peek_next path naturally already shows
        # what's NEXT, not what's currently dispatched.
        if hasattr(self, "_upcoming"):
            self._load_upcoming_queue()
            self._refresh_upcoming_panel()
        # RDS: now-playing artist + title
        if hasattr(self, "_rds"):
            self._rds.set_on_air(
                str(song.get("artist") or "—"),
                str(song.get("title") or ""))

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

    def _on_play_clicked(self) -> None:
        """Phase C — bottom transport ▶ semantic.

        Idle (no _playback_cid): start the next track from the queue.
        Mirrors Jazler's "Play = go on air" — also auto-starts the
        scheduler if it's wired but not yet running, and flips
        auto-advance ON so EOS keeps the show rolling.

        Already loaded: forward to the existing pause/resume toggle.
        """
        if self._engine is None:
            return
        if self._playback_cid is not None:
            self._on_pause_clicked()
            return
        next_song = self._compute_next_song(after_id=None)
        if next_song is None:
            log.info("[studio] play clicked but queue is empty — no-op")
            return
        # Auto-start scheduler when going on air from idle. The is_running
        # check covers the "already running" case so we don't double-start.
        if self._scheduler is not None:
            try:
                if not self._scheduler.is_running():
                    self._scheduler.start()
                    log.info("[studio] play → scheduler.start()")
            except Exception as exc:
                log.warning(f"[studio] scheduler.start failed: {exc}")
        self._auto_advance_enabled = True
        self._on_queue_song_play(next_song)

    def _on_deck_stop(self) -> None:
        """Phase C — bottom transport ■ semantic. Narrow scope: stops
        and cleans up the deck channel only. Active jingle pads (which
        share the same AudioEngine via the InstantJingleEngine adapter)
        are NOT touched. The right-cluster Stop All button retains its
        broader cleanup_all semantic for the operator's emergency
        nuclear option.

        Latent broadcast-critical bug fix — prior wiring routed
        bottom-transport stop to cleanup_all, which would mid-show-cut
        any jingle pad active at that instant."""
        if self._playback_cid is None or self._engine is None:
            return
        try:
            self._engine.stop(self._playback_cid)
        except Exception as exc:
            log.debug(f"[studio] deck stop: engine.stop: {exc}")
        try:
            self._engine.cleanup(self._playback_cid)
        except Exception as exc:
            log.debug(f"[studio] deck stop: engine.cleanup: {exc}")
        self._playback_cid = None
        self._playback_kind = None
        self._playback_campaign_id = None
        self._current_track = None
        self._apply_idle_state()
        self._update_status_pills()
        log.info("[studio] deck stop (jingle pads untouched)")

    def _on_auto_pill_clicked(self) -> None:
        """Phase C — AUTO header pill toggles BOTH scheduler.start/stop
        AND ``_auto_advance_enabled``. Operator's mental model: AUTO
        ON = "tum chalao, mai dekhunga"; AUTO OFF = "main control hu,
        jab tak click na karu kuch nahi chalega" (Live-Assist mode).
        The two stay in lockstep so a stopped scheduler never auto-
        advances and a running scheduler always does.

        When ``_scheduler`` is None (tests, decorative), we still flip
        the local flag so the operator can toggle Live-Assist behavior
        even without an engine attached."""
        if self._scheduler is None:
            self._auto_advance_enabled = not self._auto_advance_enabled
            log.info(f"[studio] AUTO pill (no scheduler) → "
                     f"_auto_advance_enabled={self._auto_advance_enabled}")
            self._update_status_pills()
            return
        try:
            running = self._scheduler.is_running()
        except Exception:
            running = False
        try:
            if running:
                self._scheduler.stop()
                self._auto_advance_enabled = False
                # Latch the auto-start off so showEvent won't fight the
                # operator by re-arming on the next screen entry. Reset
                # only by an explicit AUTO-on click (or app restart).
                self._operator_stopped_auto = True
                # Drop any pending spot — operator clicked AUTO off,
                # they're taking control. A scheduled-but-deferred spot
                # firing during Live-Assist would surprise the operator.
                if self._pending_spot_campaign_id is not None:
                    log.info(
                        f"[studio] AUTO off — dropped pending spot "
                        f"{self._pending_spot_campaign_id}")
                    self._pending_spot_campaign_id = None
                log.info("[studio] AUTO pill → scheduler.stop() + Live-Assist")
            else:
                self._scheduler.start()
                self._auto_advance_enabled = True
                # Operator re-armed AUTO explicitly — clear the latch so
                # showEvent auto-start can engage again next session.
                self._operator_stopped_auto = False
                log.info("[studio] AUTO pill → scheduler.start() + auto-advance")
        except Exception as exc:
            log.warning(f"[studio] AUTO pill toggle failed: {exc}")
        self._update_status_pills()
        # Force immediate refresh so the operator sees the
        # newly-assigned clock + queue without waiting for the next
        # scheduler tick. Works in BOTH directions of the toggle —
        # the operator's "I just assigned a clock, toggle AUTO to
        # see it" workflow lands within one click.
        self._force_studio_refresh()

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
        # Toggle: first click ARMS (player will idle when current ends),
        # second click DISARMS (current behaviour cancelled, auto-advance
        # resumes). Visual armed-state on the button so the operator sees
        # the click registered immediately, even though the actual effect
        # only fires when the current song's EOS arrives.
        new_state = not self._stop_after_current
        self._stop_after_current = new_state
        if hasattr(self, "_control_cluster") and self._control_cluster:
            self._control_cluster.set_stop_armed(new_state)
        if new_state:
            log.info(
                "[studio] StopNext ARMED — player will idle after current "
                "track ends (click again to disarm)")
        else:
            log.info("[studio] StopNext DISARMED — auto-advance resumes")

    def _on_loop_toggled(self, on: bool) -> None:
        self._loop_enabled = on
        log.info(f"[studio] loop = {on}")

    # Bottom-transport-specific handlers (Step 8)

    def _on_bottom_seek(self, frac: float) -> None:
        if (self._playback_cid is None or self._engine is None
                or self._current_duration_ms <= 0):
            return
        target = int(self._current_duration_ms * frac)
        try:
            self._engine.seek_to_ms(self._playback_cid, target)
        except Exception as exc:
            log.warning(f"[studio] seek failed: {exc}")

    def _on_up_clicked(self) -> None:
        # Decorative — no queue cursor in legacy, flagged as carry-over
        pass

    def _on_down_clicked(self) -> None:
        pass

    def _on_stop_all_clicked(self) -> None:
        if self._engine is not None:
            try:
                self._engine.cleanup_all()
            except Exception:
                pass
        self._playback_cid = None
        self._playback_kind = None
        self._current_track = None
        self._apply_idle_state()
        self._update_status_pills()

    # ────────────────────────────────────────────────────────────────────
    # State sync
    # ────────────────────────────────────────────────────────────────────

    def _update_status_pills(self) -> None:
        if not hasattr(self, "_header") or self._header is None:
            return
        on_air = (self._playback_cid is not None
                  and self._playback_kind in ("deck", "spot"))
        # Phase C: AUTO pill reflects the unified Live-Assist state.
        # Source-of-truth = _auto_advance_enabled, which is flipped in
        # lockstep with scheduler start/stop. is_running() is still the
        # external check but the local flag is what gates EOS behavior.
        auto_mode = (self._auto_advance_enabled
                     and self._scheduler is not None
                     and self._scheduler.is_running())
        self._header.set_on_air(on_air)
        self._header.set_auto_mode(auto_mode)
        # Phase C: SIGNAL pill reflects whether AudioEngine has any
        # playing channel. Polled at 1Hz from _on_tick (no separate
        # timer). True = at least one channel in 'playing' state.
        self._header.set_signal(self._compute_signal_state())

    def _compute_signal_state(self) -> bool:
        """SIGNAL pill source-of-truth. True when the AudioEngine has
        at least one channel in 'playing' state (deck OR jingle pad).
        Defensive against engines that don't expose get_active_channels
        (older legacy stubs / tests with simpler fakes) — falls back to
        checking just the deck channel."""
        eng = self._engine
        if eng is None:
            return False
        # Preferred: get_active_channels returns playing+paused; we
        # then filter to playing only via get_state.
        try:
            ids = eng.get_active_channels()
        except Exception:
            ids = None
        if ids is not None:
            try:
                return any(eng.get_state(cid) == "playing" for cid in ids)
            except Exception:
                pass
        # Fallback: just the deck channel
        if self._playback_cid is None:
            return False
        try:
            return eng.get_state(self._playback_cid) == "playing"
        except Exception:
            return False

    def _refresh_history(self) -> None:
        """Populate the History panel from db.get_history(). Called on
        init + after every spot/song state transition that could have
        written a broadcast_log row.

        Render-side dedupe: collapses consecutive same-song rows into
        a single entry. Existing broadcast_log rows from rapid-fire
        EOS loops (pre-write-side-guard era) cluttered the 12-slot
        panel with the same song repeated 8× in a row; this collapse
        hides the redundancy without modifying the underlying audit
        log. Pull a larger window (24) and dedupe down to 12 visible
        slots so the panel never runs short. Spots are NOT collapsed
        — back-to-back spots are legitimate sequence."""
        if not hasattr(self, "_history_panel"):
            return
        try:
            rows = self._db.get_history(limit=24)
        except Exception as exc:
            log.debug(f"[studio] history refresh failed: {exc}")
            return
        # Build a deduped list of up to 12 rendered entries
        rendered: list = []
        prev_song_id = None
        for r in rows:
            keys = r.keys() if hasattr(r, "keys") else []
            entry_type = (r["entry_type"] if "entry_type" in keys
                          else "song")
            if entry_type == "song":
                row_song_id = (r["song_id"] if "song_id" in keys
                               else None)
                if row_song_id is not None and row_song_id == prev_song_id:
                    # Consecutive duplicate of the same song — skip;
                    # the older row is already rendered above it.
                    continue
                prev_song_id = row_song_id
            else:
                # Spot resets the consecutive-song-streak so the next
                # song after a spot is rendered even if it matches the
                # one before the spot (legitimate playlist pattern).
                prev_song_id = None
            rendered.append(r)
            if len(rendered) >= 12:
                break
        for i in range(12):
            if i < len(rendered):
                r = rendered[i]
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

    # ────────────────────────────────────────────────────────────────────
    # Phase A — InstantJingleEngine wiring
    # ────────────────────────────────────────────────────────────────────

    def _wire_instant_jingles(self) -> None:
        """Bind tile labels to real DB pads, wire panel click signals,
        install 1-5 + Esc shortcuts, and subscribe to IJE pad signals.
        Safe to call when ``_instant_jingle_engine`` is None — the panel
        still gets real labels; clicks just no-op."""
        # Load up to 9 active pads from DB. Failures are non-fatal —
        # the panel keeps its placeholder labels.
        self._jingle_pads = self._load_jingle_pads_from_db()
        if hasattr(self, "_instant_jingles") and self._instant_jingles is not None:
            self._instant_jingles.set_tiles(self._jingle_pads)
            self._instant_jingles.tile_clicked.connect(
                self._on_jingle_tile_clicked)
            self._instant_jingles.hotkey_clicked.connect(
                self._on_jingle_hotkey_clicked)
            self._instant_jingles.edit_bank_clicked.connect(
                self._on_jingle_edit_bank)

        # Subscribe to engine signals if available. None means tests /
        # legacy callers that constructed Studio without an IJE — the
        # panel + tiles still render, just no playback.
        if self._instant_jingle_engine is not None:
            self._instant_jingle_engine.pad_started.connect(
                self._on_ije_pad_started)
            self._instant_jingle_engine.pad_ended.connect(
                self._on_ije_pad_inactive)
            self._instant_jingle_engine.pad_stopped.connect(
                self._on_ije_pad_inactive)

        # 1-5 hotkeys + Esc-for-stop-all. WidgetWithChildrenShortcut so
        # the keys only fire while Studio is the visible widget (Jazler
        # convention; matches the standalone screen's pattern).
        self._jingle_shortcuts: list[QShortcut] = []
        for i in range(1, 6):
            sc = QShortcut(QKeySequence(str(i)), self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(
                lambda n=i: self._on_jingle_hotkey_clicked(n))
            self._jingle_shortcuts.append(sc)
        sc_esc = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        sc_esc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        sc_esc.activated.connect(self._on_jingle_stop_all)
        self._jingle_shortcuts.append(sc_esc)

    def _load_jingle_pads_from_db(self) -> list[dict]:
        """Pull up to 9 active jingle_pads rows from the DB. Each entry
        is the minimum field set the dispatcher + DEMO display needs.
        Pads whose file is missing on disk are excluded (broadcast tool
        — clicking a missing-file tile during a live show would just
        flash; better to surface an Empty tile in the first place)."""
        out: list[dict] = []
        try:
            rows = self._db.get_jingle_pads_active()
        except Exception as exc:
            log.debug(f"[studio] get_jingle_pads_active failed: {exc}")
            return out
        for r in rows:
            try:
                fp = r["file_path"]
            except (KeyError, IndexError, TypeError):
                fp = None
            if not fp or not os.path.exists(fp):
                continue
            try:
                pad = {
                    "id":          int(r["id"]),
                    "label":       (r["label"] or "—"),
                    "file_path":   fp,
                    "duration_ms": int(r["duration_ms"] or 0),
                    "volume":      int(r["volume"] or 100),
                    "behaviour":   (r["behaviour"] or "play_once"),
                }
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                log.debug(f"[studio] skipping malformed pad row: {exc}")
                continue
            out.append(pad)
            if len(out) >= 9:
                break
        return out

    def _on_jingle_tile_clicked(self, idx: int) -> None:
        self._play_jingle_at_index(idx)

    def _on_jingle_hotkey_clicked(self, n: int) -> None:
        # Hotkeys are 1-indexed (1..5); tiles are 0-indexed.
        self._play_jingle_at_index(n - 1)

    def _play_jingle_at_index(self, idx: int) -> None:
        """Common dispatcher — used by tile clicks and hotkeys. Guards
        on engine + index range. The proven volume/loop pattern is
        copied from ui/instant_jingles.py:_on_pad_left_clicked."""
        if self._instant_jingle_engine is None:
            return
        if not (0 <= idx < len(self._jingle_pads)):
            return
        pad = self._jingle_pads[idx]
        if not pad.get("file_path"):
            return
        loop = (pad.get("behaviour") == "loop")
        try:
            self._instant_jingle_engine.play_pad(
                int(pad["id"]),
                pad["file_path"],
                volume=int(pad.get("volume") or 100),
                loop=loop,
            )
        except Exception as exc:
            log.warning(f"[studio] play_pad failed: {exc}")

    def _on_jingle_stop_all(self) -> None:
        """Esc handler — emergency dump of every jingle pad. AudioEngine's
        cleanup_all is broader (kills deck + spots too); this is the
        narrow IJE-only stop the operator wants when a wrong jingle is
        on air."""
        if self._instant_jingle_engine is None:
            return
        try:
            self._instant_jingle_engine.stop_all()
        except Exception as exc:
            log.warning(f"[studio] ije.stop_all failed: {exc}")

    def _on_jingle_edit_bank(self) -> None:
        # Routes to the standalone Instant Jingles screen for editing.
        # Route name 'instant_jingles' is registered at
        # ui/main_window.py:261.
        self.breadcrumb_clicked.emit("instant_jingles")

    def _on_ije_pad_started(self, pad_id: int) -> None:
        """A pad just started — light up the DEMO display with that
        pad's label + total duration, and start the 10Hz countdown."""
        pad = next((p for p in self._jingle_pads
                    if int(p["id"]) == int(pad_id)), None)
        if pad is None or not hasattr(self, "_instant_jingles"):
            return
        total_s = (int(pad.get("duration_ms") or 0)) / 1000.0
        self._jingle_demo_remaining_s = total_s
        self._instant_jingles.set_demo_active(pad.get("label") or "—",
                                              total_s)
        # Start (or restart) the countdown timer
        if self._jingle_demo_timer is None:
            self._jingle_demo_timer = QTimer(self)
            self._jingle_demo_timer.setInterval(100)   # 10 Hz
            self._jingle_demo_timer.timeout.connect(self._on_jingle_demo_tick)
        if not self._jingle_demo_timer.isActive():
            self._jingle_demo_timer.start()

    def _on_ije_pad_inactive(self, _pad_id: int) -> None:
        """Single handler for pad_ended + pad_stopped. Stops the
        countdown timer and clears the DEMO display."""
        if self._jingle_demo_timer is not None and self._jingle_demo_timer.isActive():
            self._jingle_demo_timer.stop()
        self._jingle_demo_remaining_s = 0.0
        if hasattr(self, "_instant_jingles"):
            self._instant_jingles.set_demo_inactive()

    # ────────────────────────────────────────────────────────────────────
    # Phase B — Up Coming queue scheduler binding
    # ────────────────────────────────────────────────────────────────────

    def _load_upcoming_queue(self) -> None:
        """Pull the next 5 items from ``scheduler.peek_next(5)``,
        translate to the card-friendly dict shape, and re-render.

        peek_next is non-destructive (Commit 1 of Phase B) — calling
        it on every refresh leaves the dispatch cursor untouched.
        Errors are non-fatal: on any exception the preview is cleared
        and the legacy `_queue_songs` fallback path renders instead."""
        if self._scheduler is None:
            self._upcoming_preview = []
            self._refresh_upcoming_panel()
            return
        try:
            items = self._scheduler.peek_next(5)
        except Exception as exc:
            log.warning(f"[studio] peek_next failed: {exc}")
            self._upcoming_preview = []
            self._refresh_upcoming_panel()
            return
        # peek_next returns dicts shaped like pick_next_item:
        #   {item_type, item_id, file_path, title, artist, duration_ms,
        #    clock_id, slot_idx}
        # _UpComingCard expects:
        #   {_item_type, id, title, artist, file_path, duration_ms,
        #    intro_point_ms (optional)}
        translated: list[dict] = []
        for it in items[:5]:
            translated.append({
                "_item_type":  it.get("item_type") or "song",
                "id":          it.get("item_id"),
                "title":       it.get("title") or "—",
                "artist":      it.get("artist") or "",
                "file_path":   it.get("file_path"),
                "duration_ms": int(it.get("duration_ms") or 0),
                # intro_point_ms is not part of the peek_next shape —
                # the picker doesn't surface it. Leaving absent means
                # the card skips the INTRO badge, which is correct
                # default behaviour for non-song item types and for
                # songs whose intro hasn't been cued yet.
            })
        self._upcoming_preview = translated
        self._refresh_upcoming_panel()

    def _refresh_upcoming_panel(self) -> None:
        """Render the Up Coming panel from current state. Picks the
        scheduler-driven preview when available, else falls back to
        the legacy in-memory queue. Called from:
          - the 1Hz wall-clock tick (live AT timestamp refresh)
          - scheduler signals (song_auto_advance / started / stopped)
          - state-change paths (_apply_idle_state, _apply_playing_state)

        Both paths now show STRICTLY upcoming items — the currently-
        playing song and any already-played songs are excluded so the
        operator sees only "what's about to air next." Already-played
        items live in the History panel; the currently-playing item
        lives in NowPlayer.
        """
        if not hasattr(self, "_upcoming"):
            return
        if self._upcoming_preview:
            # Scheduler-driven path — peek_next already excludes
            # everything before the cursor, so the list is naturally
            # "next 5 to dispatch." Index 0 → NEXT rose glow.
            self._upcoming.set_queue(self._upcoming_preview, next_index=0)
        else:
            # Legacy fallback: filter _queue_songs to exclude already-
            # played songs (which includes the currently-playing one,
            # added to _played_song_ids when its play started). The
            # remaining list is the operator's "next up" — index 0
            # gets the NEXT rose glow.
            unplayed = [
                s for s in self._queue_songs
                if int(s.get("id") or 0) not in self._played_song_ids
            ]
            self._upcoming.set_queue(unplayed[:5], next_index=0)

    def _on_jingle_demo_tick(self) -> None:
        """10Hz countdown — decrement remaining; stop at 0 (we still
        wait for pad_ended/stopped to fully clear so the visual state
        stays in sync with the engine)."""
        self._jingle_demo_remaining_s = max(
            0.0, self._jingle_demo_remaining_s - 0.1)
        if hasattr(self, "_instant_jingles"):
            self._instant_jingles.update_demo_remaining(
                self._jingle_demo_remaining_s)
        if self._jingle_demo_remaining_s <= 0.0 and self._jingle_demo_timer is not None:
            self._jingle_demo_timer.stop()

    def _on_library_song_double_clicked(self, idx: int) -> None:
        """Library row double-click. Dispatch depends on the currently-
        active type tile:
          • "Songs" / "Tracks" / "Favorites" → load to deck (legacy path).
          • "Sweepers" → fire the row as an overlay on the current
                         deck song via the SweeperEngine.
          • Other types (Jingles / Spots / Voice) — reserved for future
                         wiring, no-op for now (table is empty so
                         double-click can't reach this branch anyway).
        """
        active = self._libraries.active_library_type() \
            if hasattr(self, "_libraries") else "Songs"
        if active == "Sweepers":
            if 0 <= idx < len(self._library_sweepers):
                sw = self._library_sweepers[idx]
                self._on_play_sweeper_overlay(int(sw.get("id") or 0))
            return
        # Songs (and the placeholder types) reuse the existing deck path.
        if 0 <= idx < len(self._queue_songs):
            self._on_queue_song_play(self._queue_songs[idx])

    def _on_library_type_changed(self, name: str) -> None:
        """A type tile in the Libraries panel was clicked. Swap the
        table source to match. Songs use _queue_songs (same as before);
        Sweepers query the live `sweepers` table; the remaining tiles
        are placeholders for now and clear the table.
        """
        if name == "Songs":
            self._library_sweepers = []
            self._libraries.set_songs(
                self._queue_songs, len(self._queue_songs))
            return
        if name == "Sweepers":
            try:
                rows = list(self._db.get_sweepers_active())
            except Exception as exc:
                log.warning(f"[studio] sweepers fetch failed: {exc}")
                rows = []
            cache: list[dict] = []
            display: list[dict] = []
            for r in rows:
                keys = r.keys()
                cache.append({
                    "id":          int(r["id"]),
                    "name":        r["name"]      if "name"      in keys else "",
                    "category":    r["category"]  if "category"  in keys else "",
                    "position":    r["position"]  if "position"  in keys else "",
                    "duration_ms": int(r["duration_ms"] or 0)
                                    if "duration_ms" in keys else 0,
                })
                # Render in the existing songs-table widget shape
                # (it expects "artist" + "title"). Showing position
                # as the artist-line keeps the table glanceable.
                display.append({
                    "title":  r["name"]     if "name"     in keys else "—",
                    "artist": (r["position"] if "position" in keys else "—")
                              or "—",
                })
            self._library_sweepers = cache
            self._libraries.set_songs(display, len(display))
            return
        # Placeholder tiles: clear the table so the operator sees the
        # empty list rather than stale song data.
        self._library_sweepers = []
        self._libraries.set_songs([], 0)

    # ────────────────────────────────────────────────────────────────────
    # 1Hz tick — header clock
    # ────────────────────────────────────────────────────────────────────

    def _on_tick(self) -> None:
        now = datetime.now()
        self._header.set_clock(
            now.strftime("%H:%M:%S"),
            day=now.strftime("%A").upper(),
            date=now.strftime("%b %d, %Y").upper())
        # Phase B: live AT timestamp tick. _refresh_upcoming_panel
        # re-renders the cards using current wall-clock so the
        # cumulative AT values stay fresh even when no song is
        # advancing (late-night automation, long song, etc.).
        self._refresh_upcoming_panel()
        # Phase C: SIGNAL pill 1Hz poll. _update_status_pills now also
        # calls header.set_signal(...) using _compute_signal_state.
        # set_signal/set_auto_mode/set_on_air are all change-gated so
        # repaint happens only when the state actually flips — cheap.
        self._update_status_pills()
        # Active-clock indicator (independent of scheduler running):
        # Studio's own 1Hz check ensures the header reflects
        # whichever clock is currently assigned to the (weekday, hour)
        # cell, even when AUTO is OFF. The scheduler-driven check
        # (which fires `active_clock_changed` when running) still
        # works in parallel — both paths converge through the same
        # dedupe state so no double-render.
        self._studio_check_active_clock()

    def _studio_check_active_clock(self) -> None:
        """Lightweight active-clock resolution from Studio's own tick.
        Direct DB query (no scheduler dependency), deduped against the
        last-displayed value so the header repaints only on transition.
        Wrapped in try/except — DB blip on this path must never freeze
        Studio's 1Hz tick (broadcast safety, same rule as the scheduler-
        side check in core/scheduler/engine.py)."""
        if self._db is None:
            return
        try:
            now = datetime.now()
            row = self._db.get_active_clock(int(now.weekday()),
                                            int(now.hour))
            if row is None:
                new_id = -1
                new_name = ""
            else:
                try:
                    new_id = int(row["id"])
                    new_name = str(row["name"] or "")
                except (KeyError, IndexError, TypeError, ValueError):
                    new_id = -1
                    new_name = ""
        except Exception as exc:
            log.debug(f"[studio] active-clock check failed: {exc}")
            return
        self._set_displayed_active_clock(new_id, new_name)

    def _set_displayed_active_clock(self, clock_id: int, name: str) -> None:
        """Single source of truth for the header's active-clock text.
        Called from both Studio's 1Hz tick and the scheduler's
        `active_clock_changed` signal — dedupe state ensures the header
        repaints only when the resolved clock actually changes."""
        if clock_id == self._displayed_active_clock_id:
            return
        self._displayed_active_clock_id = int(clock_id)
        if not hasattr(self, "_header") or self._header is None:
            return
        if clock_id < 0:
            self._header.set_active_clock("")
        else:
            self._header.set_active_clock(name or "")
        log.info(
            f"[studio] header active clock → "
            f"{'(none)' if clock_id < 0 else f'{name!r} (id={clock_id})'}")

    def _force_studio_refresh(self) -> None:
        """Heavy refresh used on navigate-back (showEvent) and AUTO
        toggle clicks. Bumps the active-clock dedupe so the next check
        re-emits, then re-runs the active-clock + Up Coming queue
        resolutions immediately. Lighter than a full re-construction
        — operator gets fresh data inside one tick of the click."""
        # Force the next active-clock check to fire even if the cell
        # didn't change — useful for "I just assigned a clock and
        # navigated back" workflow where the operator expects an
        # explicit refresh action.
        self._displayed_active_clock_id = -2
        self._studio_check_active_clock()
        try:
            self._load_upcoming_queue()
        except Exception as exc:
            log.debug(f"[studio] force refresh: upcoming reload failed: {exc}")
        self._refresh_history()

    # ────────────────────────────────────────────────────────────────────
    # Visual polish — root paintEvent (atmospheric background)
    # ────────────────────────────────────────────────────────────────────

    def paintEvent(self, e: QPaintEvent) -> None:
        """Compose the premium-broadcast background atmosphere:
        linear deep-navy base + 3 large radial glow ellipses (purple
        top-right, cyan bottom-left, green mid). All gradients are
        cached in __init__; this method does pure draw calls and
        clips to the dirty rect for partial repaints."""
        p = QPainter(self)
        p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Linear base
        p.fillRect(self.rect(), QBrush(self._bg_linear))
        # 3 radial glows on top — composition mode SourceOver is the
        # default but spelled out here for clarity that these are
        # additive-feeling colored halos, not opaque overlays.
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        p.fillRect(self.rect(), QBrush(self._bg_glow_purple))
        p.fillRect(self.rect(), QBrush(self._bg_glow_cyan))
        p.fillRect(self.rect(), QBrush(self._bg_glow_green))

    # ────────────────────────────────────────────────────────────────────
    # Lifecycle
    # ────────────────────────────────────────────────────────────────────

    def showEvent(self, event):
        """Triggered every time Studio becomes the active screen in the
        QStackedWidget (navigate-back from Auto Schedule, Hub, etc.).
        Forces a fresh resolution of the active clock + Up Coming queue
        so the operator sees up-to-date data without having to toggle
        AUTO. Skips the very first show during construction — the
        ctor already seeded everything.

        Also auto-starts the scheduler when a clock is assigned to the
        current (weekday, hour) cell so Studio shows live queue data
        without the operator having to click AUTO. Latched off if the
        operator explicitly stops via the AUTO pill in the same app
        session (Live-Assist intent)."""
        super().showEvent(event)
        # `_displayed_active_clock_id` defaults to -2 ("never set"),
        # so the first showEvent (during ctor) will run the seed
        # logic, and subsequent showEvents will diff against the last
        # displayed value and force-refresh if it changed.
        if hasattr(self, "_db"):
            self._force_studio_refresh()
            self._maybe_auto_start_scheduler()

    def _maybe_auto_start_scheduler(self) -> None:
        """If a clock is assigned to the current (weekday, hour) cell
        and the scheduler isn't already running and the operator hasn't
        latched the auto-start off via an explicit AUTO-pill stop,
        start the scheduler so Studio's queue + NEXT chip show real
        data immediately on screen entry."""
        if self._scheduler is None:
            return
        if self._operator_stopped_auto:
            log.debug("[studio] auto-start skipped — operator latched off")
            return
        try:
            if self._scheduler.is_running():
                return
        except Exception:
            return
        try:
            now = datetime.now()
            row = self._db.get_active_clock(int(now.weekday()),
                                             int(now.hour))
        except Exception as exc:
            log.debug(f"[studio] auto-start active-clock lookup failed: "
                      f"{exc}")
            return
        if row is None:
            log.info("[studio] auto-start skipped — no clock assigned to "
                     "the current hour")
            return
        try:
            self._scheduler.start()
        except Exception as exc:
            log.warning(f"[studio] auto-start failed: {exc}")
            return
        self._auto_advance_enabled = True
        try:
            cid = int(row["id"]) if "id" in row.keys() else "?"
            cname = row["name"] if "name" in row.keys() else ""
        except Exception:
            cid, cname = "?", ""
        log.info(
            f"[studio] auto-started scheduler on showEvent — "
            f"clock id={cid} name={cname!r} (weekday={now.weekday()}, "
            f"hour={now.hour})")
        # Force pill + queue refresh so the operator sees the AUTO
        # state flip immediately — same hooks the AUTO pill click
        # uses below.
        self._update_status_pills()
        self._load_upcoming_queue()
        self._refresh_upcoming_panel()

    def hideEvent(self, event):
        super().hideEvent(event)
