"""
RadioAI Studio Pro — Studio screen, premium broadcast design (Figma 312:2).

Replaces the Phase D `studio_legacy.py` with the new 1920×1080 broadcast-
grade layout. All Phase D wiring (audio engine signals, scheduler
integration, queue/EOS handlers, _on_queue_song_play, _compute_next_song,
_tags_for_item_type, _derive_tags) is preserved verbatim — the visual
layer changes; the broadcast logic does not.

Layout (1920 × 1080)
--------------------
  HEADER          1920 ×  60   y=0..60
                   Logo + STUDIO ON AIR + clock + Active Station +
                   3 status pills + Control Panel button + Settings cog

  MASTER TRANSPORT 1920 × 96   y=60..156
    NOW Player    836 × 88    @ x=16   — vinyl + LIVE pulse + title +
                                          elapsed/total + waveform
    NEXT Chip     200 × 88    @ x=864  — TO AIR countdown + intro badge
    Control Clust 296 × 80    @ x=1080 — Restart/Loop/Pause/StopNext
    Level Meters   80 × 80    @ x=1392 — vertical L/R VU
    Clock Face     80 × 80    @ x=1488 — analog 12-tick + hands
    Wordmark      320 × 80    @ x=1584 — STUDIO PRO + accent + MIC pill

  BODY            1920 × 820  y=172..992
    Up Coming     380 × 820   @ x=16   — 5 track cards stacked
    Libraries     720 × 820   @ x=412  — type icons + table + filter
    Instant Jing  420 × 540   @ x=1148 — 3×2 jingle tiles (visual-only)
    History       320 × 540   @ x=1584 — last 12 played
    Next Break    420 × 264   @ x=1148, y=728 — big amber countdown
    RDS           320 × 152   @ x=1584, y=728 — LIVE + RT+ button
    Problems      320 × 96    @ x=1584, y=896 — warning rows

  BOTTOM TRANSPORT 1920 × 80  y=1000..1080
    Loaded Pl     left
    Transport     center (▶ / ■ / progress / AutoPlay)
    6-btn cluster right (Up/Down/StopAll/Auto/MixFa../Loop)

Engine & scheduler wiring — preserved from Phase D
--------------------------------------------------
  engine.position_changed       → _on_engine_position
  engine.playback_ended         → _on_engine_playback_ended
  engine.error_occurred         → _on_engine_error
  scheduler.spot_due            → _on_scheduler_spot_due
  scheduler.song_auto_advance   → _on_scheduler_song_advance
  scheduler.break_approaching   → _on_scheduler_break_warn
  scheduler.next_break_in       → _on_scheduler_next_break_in
  scheduler.started/.stopped    → _update_status_pills

Internal API preserved (tests touch these names directly)
---------------------------------------------------------
  state attrs  : _queue_songs, _playback_cid, _current_track,
                 _loop_enabled, _stop_after_current, _pre_spot_song_id,
                 _playback_kind, _playback_campaign_id, _master_volume,
                 _fade_out_timer, _current_duration_ms
  methods      : _on_queue_song_play, _on_engine_playback_ended,
                 _compute_next_song
  staticmethods: _tags_for_item_type, _derive_tags

═══════════════════════════════════════════════════════════════════════════
PERFORMANCE INVARIANTS — broadcast app, perf is non-negotiable
═══════════════════════════════════════════════════════════════════════════
  1. event.rect() clipping in every paintEvent
  2. Waveform: cache static bar geometry; partial QRect updates for
     playhead position only; never full-widget repaint per frame
  3. Level meters: subscribe to RMS signal (when wired); throttle paint
     to 30Hz max
  4. Slider position from engine: throttle to 4Hz (250ms)
  5. Clock face hands: 1Hz wall-clock (NOT engine-driven), partial
     QRect updates
  6. NO setMouseTracking anywhere
  7. NO db calls in paintEvent
  8. NO self.update() inside paintEvent
  9. NO nested QScrollArea — Libraries / Up Coming / History each scroll
     in one
 10. Cache QGradient/QColor/QFont per custom widget in __init__
 11. Drop shadows via QGraphicsDropShadowEffect
═══════════════════════════════════════════════════════════════════════════

Decorative widgets (NOT engine-wired — flagged in NIGHT_LOG)
-----------------------------------------------------------
  - SIGNAL/STREAM/AUTO status pills (header) — visual placeholder
  - Instant Jingles 6-pad + 1-5 hotkeys — visual-only (legacy doesn't
    import core.instant_jingle_engine; dedicated wire-up in follow-up)
  - Up/Down navigation buttons — no queue-cursor in legacy
  - MixFade button — legacy has Fade Out only
  - Problems panel — empty state, no scheduler errors collection in legacy
"""

from __future__ import annotations

import logging
import math
import os
from datetime import datetime
from typing import Optional

from PyQt6.QtCore import (
    Qt, QRect, QRectF, QPoint, QPointF, QSize, QTimer, pyqtSignal,
)
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QLinearGradient, QRadialGradient,
    QPainterPath, QFont, QMouseEvent, QPaintEvent, QKeyEvent,
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

HEADER_H        = 60
MASTER_Y        = 60
MASTER_H        = 96
BODY_Y          = 172
BODY_H          = 820
BOTTOM_TRANS_Y  = 1000
BOTTOM_TRANS_H  = 80

# Common formatting helpers (preserved from legacy module)


def _fmt_duration(ms: int) -> str:
    """ms → 'M:SS' (or 'H:MM:SS' for very long)."""
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


def _qfill_card(p: QPainter, rect: QRectF) -> None:
    bg = QLinearGradient(0, 0, 0, rect.height())
    bg.setColorAt(0.0, QColor(14, 16, 32, 242))
    bg.setColorAt(1.0, QColor(7, 9, 18, 242))
    p.fillRect(rect, QBrush(bg))


def _qstroke_card(p: QPainter, rect: QRectF, radius: float = 12.0,
                  alpha: int = 18) -> None:
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(QColor(255, 255, 255, alpha)))
    p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)


def _drop_shadow(blur: int, color: QColor, dy: int = 0) -> QGraphicsDropShadowEffect:
    eff = QGraphicsDropShadowEffect()
    eff.setBlurRadius(blur)
    eff.setOffset(0, dy)
    eff.setColor(color)
    return eff


# ════════════════════════════════════════════════════════════════════════
# HEADER — 1920 × 60
# ════════════════════════════════════════════════════════════════════════

class _Header(QWidget):
    """Top bar: Logo + STUDIO ON AIR title + center clock + Active
    Station card + 3 status pills + Control Panel button + Settings cog."""

    control_panel_clicked = pyqtSignal()
    settings_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(WINDOW_W, HEADER_H)
        self._on_air = True
        self._clock_text = "00:00:00"
        self._date_text = ""
        self._signal_ok = True
        self._stream_ok = True
        self._auto_mode = False
        # Cached fonts
        self._font_brand = inter(15, QFont.Weight.Black, letter_spacing=-0.2)
        self._font_sub   = inter(8, QFont.Weight.Bold, letter_spacing=2.0)
        self._font_title = inter(14, QFont.Weight.Black, letter_spacing=-0.1)
        self._font_clock = mono(22, bold=True, letter_spacing=-0.5)
        self._font_pill  = inter(9, QFont.Weight.Bold, letter_spacing=1.0)
        self._font_cp    = inter(11, QFont.Weight.Bold, letter_spacing=0.3)

        # Control Panel button hit zone (right side)
        self._cp_btn_rect = QRect(WINDOW_W - 180, 14, 138, 32)
        # Settings cog hit zone
        self._cog_rect    = QRect(WINDOW_W - 36, 18, 24, 24)

    def set_clock(self, hms: str, date_text: str = "") -> None:
        if hms != self._clock_text:
            self._clock_text = hms
            self._date_text = date_text
            self.update(QRect(720, 8, 360, HEADER_H - 16))

    def set_on_air(self, on: bool) -> None:
        if on == self._on_air:
            return
        self._on_air = bool(on)
        self.update(QRect(0, 0, 720, HEADER_H))

    def set_auto_mode(self, on: bool) -> None:
        if on == self._auto_mode:
            return
        self._auto_mode = bool(on)
        self.update(QRect(1200, 0, 380, HEADER_H))

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            p = e.position().toPoint()
            if self._cp_btn_rect.contains(p):
                self.control_panel_clicked.emit()
            elif self._cog_rect.contains(p):
                self.settings_clicked.emit()
        super().mousePressEvent(e)

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Header background
        bg = QLinearGradient(0, 0, self.width(), 0)
        bg.setColorAt(0.0, QColor(16, 19, 31, 230))
        bg.setColorAt(1.0, QColor(10, 12, 22, 230))
        p.fillRect(self.rect(), QBrush(bg))
        # Hairline bottom
        p.fillRect(QRectF(0, self.height() - 1, self.width(), 1),
                   QColor(255, 255, 255, 18))

        # Logo block (purple square at x=16, 36×36)
        logo = QRectF(16, 12, 36, 36)
        lg = QLinearGradient(logo.topLeft(), logo.bottomRight())
        lg.setColorAt(0.0, QColor(PURPLE_LIGHT))
        lg.setColorAt(1.0, QColor(PURPLE_DARK))
        p.fillRect(logo, QBrush(lg))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 30)))
        p.drawRoundedRect(logo.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        # 5 vertical bars in logo
        bar_h = (5, 11, 17, 11, 5)
        for i, h in enumerate(bar_h):
            x = 22 + i * 5
            y = 30 - h // 2
            p.fillRect(QRectF(x, y, 3, h), QColor(255, 255, 255, 230))

        # RadioAI / STUDIO PRO wordmark
        p.setPen(QColor(TEXT_PRI)); p.setFont(self._font_brand)
        p.drawText(QRectF(64, 8, 200, 18),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "RadioAI")
        p.setPen(QColor(PURPLE_LIGHT)); p.setFont(self._font_sub)
        p.drawText(QRectF(64, 30, 200, 12),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "STUDIO PRO")

        # STUDIO ON AIR title
        p.setPen(QColor(TEXT_PRI)); p.setFont(self._font_title)
        p.drawText(QRectF(280, 18, 240, 24),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "STUDIO" if not self._on_air else "STUDIO ON AIR")
        # Rec dot
        if self._on_air:
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(RED))
            p.drawEllipse(QRectF(424, 25, 10, 10))

        # Center clock
        p.setPen(QColor(TEXT_PRI)); p.setFont(self._font_clock)
        p.drawText(QRectF(720, 0, 360, HEADER_H),
                   Qt.AlignmentFlag.AlignCenter, self._clock_text)

        # Active Station card (cyan accent, 200w near right)
        card = QRectF(1080, 12, 220, 36)
        p.fillRect(card, _qcolor_a(GREEN, 0.10))
        p.setPen(QPen(_qcolor_a(GREEN, 0.30)))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(card.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        p.setPen(QColor(GREEN_LIGHT)); p.setFont(self._font_pill)
        p.drawText(QRectF(card.x() + 10, card.y() + 4, 100, 12),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "KISS FM 91.5")
        p.setPen(QColor(TEXT_SEC)); p.setFont(inter(8, QFont.Weight.Medium))
        p.drawText(QRectF(card.x() + 10, card.y() + 18, 200, 12),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "Jaipur, Rajasthan")

        # 3 status pills (SIGNAL / STREAM / AUTO) — decorative
        pill_y = 14
        pills = [
            ("SIGNAL", GREEN if self._signal_ok else RED),
            ("STREAM", GREEN if self._stream_ok else AMBER),
            ("AUTO",   PURPLE if self._auto_mode else TEXT_DIM),
        ]
        for i, (label, color) in enumerate(pills):
            x = 1320 + i * 72
            r = QRectF(x, pill_y, 64, 28)
            p.fillRect(r, _qcolor_a(color, 0.10))
            p.setPen(QPen(_qcolor_a(color, 0.4)))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
            p.setPen(QColor(color)); p.setFont(self._font_pill)
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, label)

        # Control Panel button (top-right)
        cp = QRectF(self._cp_btn_rect)
        cp_grad = QLinearGradient(cp.topLeft(), cp.bottomLeft())
        cp_grad.setColorAt(0.0, QColor(PURPLE_LIGHT))
        cp_grad.setColorAt(1.0, QColor(PURPLE_DARK))
        p.fillRect(cp, QBrush(cp_grad))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 30)))
        p.drawRoundedRect(cp.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        p.setPen(QColor(255, 255, 255)); p.setFont(self._font_cp)
        p.drawText(cp, Qt.AlignmentFlag.AlignCenter, "← Control Panel")

        # Settings cog
        cog = QRectF(self._cog_rect)
        p.setPen(QColor(TEXT_SEC)); p.setFont(inter(14))
        p.drawText(cog, Qt.AlignmentFlag.AlignCenter, "⚙")
        p.end()


# ════════════════════════════════════════════════════════════════════════
# NOW PLAYER — 836 × 88
# ════════════════════════════════════════════════════════════════════════

class _NowPlayer(QWidget):
    """Now Playing card: vinyl album art + LIVE pulse + NOW pill +
    track title + artist + elapsed/total + REMAINING + waveform."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(836, 88)
        self._title = "—"
        self._artist = ""
        self._elapsed_ms = 0
        self._total_ms = 0
        self._progress = 0.0    # 0..1
        self._idle = True
        self._wf_bars: list[float] = self._gen_wf_bars()

        # Cached fonts
        self._font_now      = inter(8, QFont.Weight.Black, letter_spacing=1.6)
        self._font_title    = inter(15, QFont.Weight.Black, letter_spacing=-0.2)
        self._font_artist   = inter(10, QFont.Weight.Medium)
        self._font_time     = mono(11, bold=True, letter_spacing=-0.3)
        self._font_remain   = mono(13, bold=True, letter_spacing=-0.3)
        self._font_remlbl   = inter(7, QFont.Weight.Bold, letter_spacing=1.4)

    def set_track(self, track: Optional[dict]) -> None:
        if track is None:
            self._idle = True
            self._title = "—"; self._artist = ""
            self._elapsed_ms = 0; self._total_ms = 0
            self._progress = 0.0
        else:
            self._idle = False
            self._title = str(track.get("title") or "—")
            self._artist = str(track.get("artist") or "")
            self._total_ms = int(track.get("duration_ms") or 0)
            self._elapsed_ms = 0
            self._progress = 0.0
        self.update(self.rect())

    def set_progress(self, pos_ms: int, total_ms: int) -> None:
        self._elapsed_ms = max(0, int(pos_ms or 0))
        self._total_ms = max(0, int(total_ms or 0))
        if self._total_ms > 0:
            self._progress = max(0.0, min(1.0, self._elapsed_ms / self._total_ms))
        self.update(QRect(180, 60, self.width() - 200, 24))    # waveform area

    @staticmethod
    def _gen_wf_bars() -> list[float]:
        """Pseudo-random bar heights (0..1) for the waveform decoration.
        Cached per-widget so the silhouette is stable across frames."""
        import random
        rng = random.Random(42)
        return [0.30 + 0.65 * rng.random() for _ in range(160)]

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        _qfill_card(p, r)
        _qstroke_card(p, r, radius=10)

        # Vinyl album art (left circle)
        cx, cy, rad = 50, 44, 30
        for i, c_alpha in enumerate([(0.6, 30), (0.45, 22), (0.30, 14)]):
            grad = QRadialGradient(QPointF(cx, cy), rad - i * 6)
            grad.setColorAt(c_alpha[0], _qcolor_a(PURPLE_LIGHT, 0.7))
            grad.setColorAt(1.0, _qcolor_a(PURPLE_DARK, 0.3))
            p.setBrush(QBrush(grad))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(cx, cy), rad - i * 6, rad - i * 6)
        # Center hole
        p.setBrush(QColor(BG_BASE)); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), 4, 4)

        # LIVE pulse — small red dot top-right of vinyl
        if not self._idle:
            p.setBrush(QColor(RED)); p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(76, 18), 4, 4)

        # NOW pill (cyan)
        pill = QRectF(96, 12, 50, 16)
        p.fillRect(pill, _qcolor_a(CYAN, 0.20))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_qcolor_a(CYAN, 0.45)))
        p.drawRoundedRect(pill.adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)
        p.setPen(QColor(CYAN_LIGHT)); p.setFont(self._font_now)
        p.drawText(pill, Qt.AlignmentFlag.AlignCenter, "NOW")

        # Title + artist
        p.setPen(QColor(TEXT_PRI)); p.setFont(self._font_title)
        p.drawText(QRectF(96, 26, 540, 22),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._title)
        p.setPen(QColor(TEXT_SEC)); p.setFont(self._font_artist)
        p.drawText(QRectF(96, 46, 540, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._artist)

        # Elapsed / total time
        p.setPen(QColor(CYAN_LIGHT)); p.setFont(self._font_time)
        p.drawText(QRectF(640, 8, 80, 16),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   _fmt_duration(self._elapsed_ms))
        p.setPen(QColor(TEXT_DIM))
        p.drawText(QRectF(640, 24, 80, 16),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   _fmt_duration(self._total_ms))

        # REMAINING box
        rem = self._total_ms - self._elapsed_ms if not self._idle else 0
        rem_box = QRectF(730, 6, 96, 36)
        p.fillRect(rem_box, _qcolor_a(AMBER, 0.10))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_qcolor_a(AMBER, 0.4)))
        p.drawRoundedRect(rem_box.adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
        p.setPen(QColor(TEXT_DIM)); p.setFont(self._font_remlbl)
        p.drawText(QRectF(rem_box.x(), rem_box.y() + 2, rem_box.width(), 10),
                   Qt.AlignmentFlag.AlignCenter, "REMAINING")
        p.setPen(QColor(AMBER_LIGHT)); p.setFont(self._font_remain)
        p.drawText(QRectF(rem_box.x(), rem_box.y() + 13, rem_box.width(), 18),
                   Qt.AlignmentFlag.AlignCenter, _fmt_duration(rem))

        # Waveform — full-width bars below the meta line
        self._paint_waveform(p)
        p.end()

    def _paint_waveform(self, p: QPainter) -> None:
        wf_x, wf_y, wf_w, wf_h = 96, 64, 620, 18
        bar_count = len(self._wf_bars)
        bar_w = max(1.0, wf_w / bar_count - 0.5)
        for i, h_frac in enumerate(self._wf_bars):
            x = wf_x + i * (wf_w / bar_count)
            h = wf_h * h_frac
            y = wf_y + (wf_h - h) / 2
            played = (i / bar_count) <= self._progress
            if played:
                # Played portion gradient (cyan→purple→pink)
                t = i / bar_count
                if t < 0.5:
                    color = QColor(CYAN_LIGHT)
                else:
                    color = QColor(PINK_LIGHT)
            else:
                color = QColor(255, 255, 255, 32)
            p.fillRect(QRectF(x, y, bar_w, h), color)


# ════════════════════════════════════════════════════════════════════════
# NEXT CHIP — 200 × 88
# ════════════════════════════════════════════════════════════════════════

class _NextChip(QWidget):
    """NEXT pill + 01s TO AIR + divider + title + artist + INTRO Xs amber."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(200, 88)
        self._title = "—"
        self._artist = ""
        self._to_air_s = 0
        self._intro_s = 0
        self._font_pill   = inter(8, QFont.Weight.Black, letter_spacing=1.6)
        self._font_air    = mono(15, bold=True, letter_spacing=-0.3)
        self._font_title  = inter(11, QFont.Weight.Bold, letter_spacing=-0.1)
        self._font_artist = inter(9, QFont.Weight.Medium)
        self._font_intro  = mono(8, bold=True, letter_spacing=0.6)

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
        _qfill_card(p, r)
        _qstroke_card(p, r, radius=10)
        # NEXT pill
        pill = QRectF(10, 8, 56, 16)
        p.fillRect(pill, _qcolor_a(AMBER, 0.20))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_qcolor_a(AMBER, 0.45)))
        p.drawRoundedRect(pill.adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)
        p.setPen(QColor(AMBER_LIGHT)); p.setFont(self._font_pill)
        p.drawText(pill, Qt.AlignmentFlag.AlignCenter, "NEXT")
        # TO AIR countdown
        p.setPen(QColor(TEXT_PRI)); p.setFont(self._font_air)
        air_text = "—" if self._to_air_s == 0 else f"{self._to_air_s:02d}s"
        p.drawText(QRectF(72, 6, 120, 20),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   air_text)
        p.setPen(QColor(TEXT_DIM)); p.setFont(inter(7, QFont.Weight.Bold,
                                                    letter_spacing=1.0))
        p.drawText(QRectF(72, 22, 120, 12),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "TO AIR")
        # Divider
        p.fillRect(QRectF(10, 38, self.width() - 20, 1),
                   QColor(255, 255, 255, 18))
        # Title + artist
        p.setPen(QColor(TEXT_PRI)); p.setFont(self._font_title)
        p.drawText(QRectF(10, 42, self.width() - 70, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._title)
        p.setPen(QColor(TEXT_SEC)); p.setFont(self._font_artist)
        p.drawText(QRectF(10, 60, self.width() - 70, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._artist)
        # INTRO Xs amber badge (right)
        if self._intro_s > 0:
            badge = QRectF(self.width() - 56, 60, 46, 16)
            p.fillRect(badge, _qcolor_a(AMBER, 0.18))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(_qcolor_a(AMBER, 0.4)))
            p.drawRoundedRect(badge.adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)
            p.setPen(QColor(AMBER_LIGHT)); p.setFont(self._font_intro)
            p.drawText(badge, Qt.AlignmentFlag.AlignCenter,
                       f"INTRO {self._intro_s}s")
        p.end()


# ════════════════════════════════════════════════════════════════════════
# CONTROL CLUSTER — 296 × 80 (4 chunky transport buttons)
# ════════════════════════════════════════════════════════════════════════

class _ControlButton(QWidget):
    clicked = pyqtSignal()

    def __init__(self, label: str, icon: str, accent: str,
                 width: int = 70, parent=None):
        super().__init__(parent)
        self.setFixedSize(width, 64)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._label = label; self._icon = icon
        self._accent = accent
        self._active = False
        self._enabled = True
        self._hover = False
        self._font_icon  = inter(20, QFont.Weight.Black)
        self._font_label = inter(8, QFont.Weight.Bold, letter_spacing=0.5)

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
        if not self._hover:
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
        # Background
        if self._active:
            grad = QLinearGradient(0, 0, 0, self.height())
            grad.setColorAt(0.0, _qcolor_a(self._accent, 0.95))
            grad.setColorAt(1.0, _qcolor_a(self._accent, 0.65))
            p.fillRect(r, QBrush(grad))
            text_color = QColor(255, 255, 255)
        else:
            alpha = 0.20 if self._hover and self._enabled else 0.10
            if not self._enabled:
                alpha = 0.04
            p.fillRect(r, _qcolor_a(self._accent, alpha))
            text_color = (_qcolor_a(self._accent, 0.95) if self._enabled
                          else _qcolor_a(self._accent, 0.30))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_qcolor_a(self._accent,
                                0.5 if self._enabled else 0.15)))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        # Icon
        p.setPen(text_color); p.setFont(self._font_icon)
        p.drawText(QRectF(0, 6, self.width(), 28),
                   Qt.AlignmentFlag.AlignCenter, self._icon)
        # Label
        p.setFont(self._font_label)
        p.drawText(QRectF(0, 38, self.width(), 18),
                   Qt.AlignmentFlag.AlignCenter, self._label)
        p.end()


class _ControlCluster(QWidget):
    """4 chunky buttons: Restart / Loop / Pause / StopNext."""

    restart_clicked     = pyqtSignal()
    loop_toggled        = pyqtSignal(bool)
    pause_clicked       = pyqtSignal()
    stop_next_clicked   = pyqtSignal()
    fade_out_clicked    = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(296, 80)
        self._loop_on = False
        self._paused = False

        self._btn_restart = _ControlButton("RESTART", "↺", CYAN, 66, self)
        self._btn_restart.move(8, 8)
        self._btn_restart.clicked.connect(self.restart_clicked.emit)

        self._btn_loop = _ControlButton("LOOP", "↻", PURPLE, 66, self)
        self._btn_loop.move(80, 8)
        self._btn_loop.clicked.connect(self._on_loop)

        self._btn_pause = _ControlButton("PAUSE", "⏸", AMBER, 66, self)
        self._btn_pause.move(152, 8)
        self._btn_pause.clicked.connect(self.pause_clicked.emit)

        self._btn_stopnext = _ControlButton("STOP→", "⏭", RED, 66, self)
        self._btn_stopnext.move(224, 8)
        self._btn_stopnext.clicked.connect(self.stop_next_clicked.emit)

    def set_idle(self, idle: bool) -> None:
        for b in (self._btn_restart, self._btn_pause, self._btn_stopnext):
            b.set_enabled(not idle)

    def set_paused(self, on: bool) -> None:
        self._paused = bool(on)
        self._btn_pause.set_active(self._paused)

    def _on_loop(self) -> None:
        self._loop_on = not self._loop_on
        self._btn_loop.set_active(self._loop_on)
        self.loop_toggled.emit(self._loop_on)

    def paintEvent(self, e: QPaintEvent) -> None:
        # No background — buttons paint themselves
        pass


# ════════════════════════════════════════════════════════════════════════
# LEVEL METERS — 80 × 80 (vertical L/R VU)
# ════════════════════════════════════════════════════════════════════════

class _LevelMeters(QWidget):
    """L / R vertical meters with gradient fill (green→amber→rose) +
    peak hold ticks. RMS levels are decorative until engine RMS signal
    is wired (legacy doesn't expose one)."""

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
        self._anim.timeout.connect(self._tick_decay)
        self._anim.start()

    def _tick_decay(self) -> None:
        # Gradual decay so peaks fall over time (visual only)
        self._left = max(0.0, self._left - 0.04)
        self._right = max(0.0, self._right - 0.04)
        self._peak_l = max(self._left, self._peak_l - 0.01)
        self._peak_r = max(self._right, self._peak_r - 0.01)
        self.update(self.rect())

    def set_levels(self, left: float, right: float) -> None:
        self._left = max(0.0, min(1.0, float(left)))
        self._right = max(0.0, min(1.0, float(right)))
        if self._left > self._peak_l:
            self._peak_l = self._left
        if self._right > self._peak_r:
            self._peak_r = self._right
        self.update(self.rect())

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        _qfill_card(p, r, )
        _qstroke_card(p, r, radius=8)
        # Two columns
        col_w = 26
        gap = 6
        col_x_l = 12
        col_x_r = col_x_l + col_w + gap
        col_y = 10
        col_h = self.height() - 30
        # Backgrounds
        p.fillRect(QRectF(col_x_l, col_y, col_w, col_h), QColor(0, 0, 0, 100))
        p.fillRect(QRectF(col_x_r, col_y, col_w, col_h), QColor(0, 0, 0, 100))
        # Fills
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
            # Peak tick
            if peak > 0:
                py = col_y + col_h - col_h * peak
                p.fillRect(QRectF(cx, py - 1, col_w, 2),
                           QColor(255, 255, 255, 200))
        # L / R labels
        p.setPen(QColor(TEXT_DIM)); p.setFont(self._font)
        p.drawText(QRectF(col_x_l, col_y + col_h + 2, col_w, 14),
                   Qt.AlignmentFlag.AlignCenter, "L")
        p.drawText(QRectF(col_x_r, col_y + col_h + 2, col_w, 14),
                   Qt.AlignmentFlag.AlignCenter, "R")
        p.end()


# ════════════════════════════════════════════════════════════════════════
# CLOCK FACE — 80 × 80 (analog wall clock, hands + 12 ticks)
# ════════════════════════════════════════════════════════════════════════

class _AnalogClock(QWidget):
    """1Hz wall-clock face. Pure UI — NOT engine-driven (semantics are
    correct: this is the studio wall clock, not playback time)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(80, 80)
        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(lambda: self.update(self.rect()))
        self._tick.start()

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        _qfill_card(p, r)
        _qstroke_card(p, r, radius=40)
        cx, cy = self.width() / 2, self.height() / 2
        rad = 30
        # 12 tick marks
        p.setPen(QPen(QColor(255, 255, 255, 70), 1.5))
        for i in range(12):
            angle = math.radians(90 - i * 30)
            x1 = cx + (rad - 2) * math.cos(angle)
            y1 = cy - (rad - 2) * math.sin(angle)
            x2 = cx + (rad - 7) * math.cos(angle)
            y2 = cy - (rad - 7) * math.sin(angle)
            p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
        # Hands
        now = datetime.now()
        h = now.hour % 12
        m = now.minute
        s = now.second
        # Hour hand
        h_angle = math.radians(90 - (h * 30 + m * 0.5))
        p.setPen(QPen(QColor(CYAN_LIGHT), 2.5))
        p.drawLine(QPointF(cx, cy),
                   QPointF(cx + 13 * math.cos(h_angle),
                           cy - 13 * math.sin(h_angle)))
        # Minute hand
        m_angle = math.radians(90 - m * 6 - s * 0.1)
        p.setPen(QPen(QColor(PINK_LIGHT), 2.0))
        p.drawLine(QPointF(cx, cy),
                   QPointF(cx + 22 * math.cos(m_angle),
                           cy - 22 * math.sin(m_angle)))
        # Center dot
        p.setBrush(QColor(CYAN)); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), 3, 3)
        p.end()


# ════════════════════════════════════════════════════════════════════════
# WORDMARK — 320 × 80 (STUDIO PRO branding + accent + MIC pill)
# ════════════════════════════════════════════════════════════════════════

class _Wordmark(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(320, 80)
        self._font_big = inter(28, QFont.Weight.Black, letter_spacing=-0.8)
        self._font_sub = inter(8, QFont.Weight.Bold, letter_spacing=2.5)
        self._font_pill = inter(8, QFont.Weight.Bold, letter_spacing=1.4)

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        _qfill_card(p, r)
        _qstroke_card(p, r, radius=10)
        # cyan→purple→pink accent line (top)
        accent = QLinearGradient(0, 0, self.width(), 0)
        accent.setColorAt(0.0, QColor(CYAN))
        accent.setColorAt(0.5, QColor(PURPLE_LIGHT))
        accent.setColorAt(1.0, QColor(PINK))
        p.fillRect(QRectF(8, 8, self.width() - 16, 2), QBrush(accent))
        # STUDIO PRO wordmark
        p.setPen(QColor(TEXT_PRI)); p.setFont(self._font_big)
        p.drawText(QRectF(16, 16, 220, 40),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "STUDIO")
        p.setPen(QColor(PURPLE_LIGHT)); p.setFont(self._font_sub)
        p.drawText(QRectF(16, 50, 220, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "PRO BROADCAST")
        # MIC OFF pill (right side)
        pill = QRectF(self.width() - 70, 28, 56, 22)
        p.fillRect(pill, _qcolor_a(TEXT_DIM, 0.3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_qcolor_a(TEXT_DIM, 0.5)))
        p.drawRoundedRect(pill.adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
        p.setPen(QColor(TEXT_SEC)); p.setFont(self._font_pill)
        p.drawText(pill, Qt.AlignmentFlag.AlignCenter, "MIC OFF")
        p.end()


# ════════════════════════════════════════════════════════════════════════
# UP COMING QUEUE — 380 × 820 (5 track cards + footer)
# ════════════════════════════════════════════════════════════════════════

class _UpComingCard(QWidget):
    """One track card in the Up Coming list (110h)."""

    double_clicked = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(364, 110)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._song: Optional[dict] = None
        self._is_next = False
        self._at_text = "—"

        self._font_at    = mono(9, bold=True, letter_spacing=0.3)
        self._font_dur   = mono(10, bold=True)
        self._font_intro = mono(8, bold=True, letter_spacing=0.6)
        self._font_title = inter(13, QFont.Weight.Bold, letter_spacing=-0.1)
        self._font_artist = inter(10, QFont.Weight.Medium)
        self._font_type  = inter(8, QFont.Weight.Black, letter_spacing=1.2)

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
        if self._is_next:
            grad = QLinearGradient(0, 0, self.width(), 0)
            grad.setColorAt(0.0, _qcolor_a(RED, 0.20))
            grad.setColorAt(1.0, _qcolor_a(RED, 0.06))
            p.fillRect(r, QBrush(grad))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(_qcolor_a(RED, 0.45)))
        else:
            _qfill_card(p, r)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(255, 255, 255, 18)))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        # AT timestamp + DUR + INTRO badge (top row)
        p.setPen(QColor(TEXT_DIM)); p.setFont(self._font_at)
        p.drawText(QRectF(12, 8, 80, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   f"AT {self._at_text}")
        if self._song is not None:
            dur_ms = int(self._song.get("duration_ms") or 0)
            p.setPen(QColor(AMBER_LIGHT))
            p.drawText(QRectF(self.width() - 100, 8, 90, 14),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       f"DUR {_fmt_duration(dur_ms)}")
            # Album art tile (small)
            art = QRectF(12, 30, 56, 56)
            p.fillRect(art, _qcolor_a(PURPLE_DARK, 0.4))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_qcolor_a(PURPLE_LIGHT, 0.3))
            p.drawRoundedRect(art, 6, 6)
            # Title + artist
            p.setPen(QColor(TEXT_PRI)); p.setFont(self._font_title)
            p.drawText(QRectF(80, 32, self.width() - 100, 18),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       str(self._song.get("title") or "—"))
            p.setPen(QColor(TEXT_SEC)); p.setFont(self._font_artist)
            p.drawText(QRectF(80, 50, self.width() - 100, 14),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       str(self._song.get("artist") or ""))
            # Type badge
            t = self._song.get("_item_type") or "song"
            t_color = {"song": CYAN, "jingle": AMBER, "spot": GREEN,
                       "voice_track": PINK, "sweeper": PURPLE,
                       "station_id": PURPLE}.get(t, CYAN)
            badge_w = 76
            badge = QRectF(80, 76, badge_w, 18)
            p.fillRect(badge, _qcolor_a(t_color, 0.2))
            p.setPen(QPen(_qcolor_a(t_color, 0.4)))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(badge.adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)
            p.setPen(QColor(t_color)); p.setFont(self._font_type)
            p.drawText(badge, Qt.AlignmentFlag.AlignCenter, t.upper())
            # Intro hint (right)
            intro_ms = int(self._song.get("intro_point_ms") or 0)
            if intro_ms > 0:
                intro_s = max(1, intro_ms // 1000)
                ib = QRectF(self.width() - 70, 76, 60, 18)
                p.fillRect(ib, _qcolor_a(AMBER, 0.18))
                p.setPen(QPen(_qcolor_a(AMBER, 0.4)))
                p.drawRoundedRect(ib.adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)
                p.setPen(QColor(AMBER_LIGHT)); p.setFont(self._font_intro)
                p.drawText(ib, Qt.AlignmentFlag.AlignCenter, f"INTRO {intro_s}s")
        else:
            p.setPen(QColor(TEXT_DIM))
            p.setFont(inter(11, QFont.Weight.Medium))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, "—")
        p.end()


class _UpComingQueue(QWidget):
    """380 × 820 panel: 5 cards stacked + footer. Doubles as an
    enriched re-render of the legacy `_PlaylistQueue` row widget."""

    song_double_clicked = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(380, 820)
        self._cards: list[_UpComingCard] = []
        for i in range(5):
            c = _UpComingCard(self)
            c.move(8, 40 + i * 120)
            c.double_clicked.connect(self.song_double_clicked.emit)
            self._cards.append(c)
        self._loaded_total_str = "0:00:00"
        self._font_h = inter(11, QFont.Weight.Black, letter_spacing=1.4)
        self._font_footer = mono(11, bold=True)

    def set_queue(self, songs: list[dict], current_id: Optional[int] = None) -> None:
        # Compute "AT" timestamps cumulatively from "now"
        now = datetime.now()
        cum_s = 0
        # If a current track is playing, start counting from after that
        # finishes; else start from now. Pragmatic — exact alignment
        # with engine elapsed isn't required for this card view.
        for i, card in enumerate(self._cards):
            if i < len(songs):
                song = songs[i]
                hh = now.hour
                mm = now.minute
                add_total = (hh * 3600 + mm * 60 + cum_s)
                add_total %= 24 * 3600
                t_h = (add_total // 3600) % 24
                t_m = (add_total % 3600) // 60
                at_text = f"{t_h:02d}:{t_m:02d}"
                card.set_song(song, is_next=(i == 0), at_text=at_text)
                cum_s += int(song.get("duration_ms", 0) or 0) // 1000
            else:
                card.set_song(None)
        # Update footer total
        total_ms = sum(int(s.get("duration_ms") or 0) for s in songs)
        s = total_ms // 1000
        h, rem = divmod(s, 3600)
        m, ss = divmod(rem, 60)
        self._loaded_total_str = f"{h}:{m:02d}:{ss:02d}"
        self.update(QRect(0, self.height() - 60, self.width(), 60))

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        _qfill_card(p, r)
        _qstroke_card(p, r, radius=10)
        # Header
        p.setPen(QColor(CYAN_LIGHT)); p.setFont(self._font_h)
        p.drawText(QRectF(16, 12, 200, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "UP COMING")
        # Footer (Loaded Playlist + total)
        fy = self.height() - 50
        p.fillRect(QRectF(8, fy, self.width() - 16, 1),
                   QColor(255, 255, 255, 18))
        p.setPen(QColor(TEXT_DIM)); p.setFont(inter(8, QFont.Weight.Bold,
                                                    letter_spacing=1.2))
        p.drawText(QRectF(16, fy + 6, 200, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "LOADED PLAYLIST")
        p.setPen(QColor(AMBER_LIGHT)); p.setFont(self._font_footer)
        p.drawText(QRectF(16, fy + 22, 240, 18),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._loaded_total_str)
        p.end()


# ════════════════════════════════════════════════════════════════════════
# LIBRARIES — 720 × 820 (type icons + table + filter)
# ════════════════════════════════════════════════════════════════════════

class _LibrariesPanel(QWidget):
    """Visual-only in v1: type icons + sample table + filter strip.
    The full Library workflow lives in the Songs Library / Spots /
    Jingles screens; this is an in-Studio quick-access mirror."""

    song_double_clicked = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(720, 820)
        self._songs: list[dict] = []
        self._font_h = inter(13, QFont.Weight.Black, letter_spacing=-0.1)
        self._font_row_artist = inter(11, QFont.Weight.Bold, letter_spacing=-0.1)
        self._font_row_title  = inter(10, QFont.Weight.Medium)
        self._font_dur = mono(10, bold=True)

    def set_songs(self, songs: list[dict]) -> None:
        self._songs = list(songs or [])[:18]
        self.update(self.rect())

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        _qfill_card(p, r)
        # cyan→purple→pink accent
        accent = QLinearGradient(0, 0, self.width(), 0)
        accent.setColorAt(0.0, QColor(CYAN))
        accent.setColorAt(0.5, QColor(PURPLE_LIGHT))
        accent.setColorAt(1.0, QColor(PINK))
        p.fillRect(QRectF(0, 0, self.width(), 3), QBrush(accent))
        _qstroke_card(p, r, radius=10)
        # Title
        p.setPen(QColor(TEXT_PRI)); p.setFont(self._font_h)
        p.drawText(QRectF(20, 14, 300, 18),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "Libraries · Songs")
        # Type icons row (stub, visual)
        icon_y = 44
        icons = [("♪", AMBER, True), ("🔔", CYAN, False), ("$", GREEN, False),
                 ("🎤", PINK, False), ("★", PURPLE_LIGHT, False)]
        for i, (icon, color, active) in enumerate(icons):
            tile = QRectF(20 + i * 64, icon_y, 56, 36)
            if active:
                p.fillRect(tile, _qcolor_a(color, 0.25))
                p.setPen(QPen(_qcolor_a(color, 0.5)))
            else:
                p.fillRect(tile, QColor(7, 8, 16, 153))
                p.setPen(QPen(QColor(255, 255, 255, 18)))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(tile.adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
            p.setPen(QColor(color))
            p.setFont(inter(18, QFont.Weight.Black))
            p.drawText(tile, Qt.AlignmentFlag.AlignCenter, icon)
        # Table column headers
        hy = icon_y + 50
        p.setPen(QColor(TEXT_DIM))
        p.setFont(inter(9, QFont.Weight.Black, letter_spacing=1.0))
        p.drawText(QRectF(20, hy, 200, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "ARTIST")
        p.drawText(QRectF(260, hy, 300, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "TITLE")
        p.drawText(QRectF(self.width() - 90, hy, 70, 16),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   "DUR")
        # Hairline
        p.fillRect(QRectF(20, hy + 18, self.width() - 40, 1),
                   QColor(255, 255, 255, 18))
        # Rows
        for i, song in enumerate(self._songs[:14]):
            ry = hy + 24 + i * 28
            row_rect = QRectF(20, ry, self.width() - 40, 26)
            tint = 0.06 if i % 2 == 0 else 0.10
            p.fillRect(row_rect, _qcolor_a(AMBER, tint))
            # Artist
            p.setPen(QColor(TEXT_PRI)); p.setFont(self._font_row_artist)
            p.drawText(QRectF(28, ry, 200, 26),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       str(song.get("artist") or "—"))
            # Title
            p.setPen(QColor(TEXT_SEC)); p.setFont(self._font_row_title)
            p.drawText(QRectF(260, ry, self.width() - 380, 26),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       str(song.get("title") or "—"))
            # Duration
            p.setPen(QColor(AMBER_LIGHT)); p.setFont(self._font_dur)
            p.drawText(QRectF(self.width() - 90, ry, 70, 26),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       _fmt_duration(int(song.get("duration_ms") or 0)))
        p.end()


# ════════════════════════════════════════════════════════════════════════
# INSTANT JINGLES — 420 × 540 (3×2 tiles + numeric pad + 1-5 hotkeys)
# Visual-only per Q2 (legacy doesn't import core.instant_jingle_engine)
# ════════════════════════════════════════════════════════════════════════

class _InstantJingles(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(420, 540)
        self._font_h = inter(13, QFont.Weight.Black, letter_spacing=-0.1)
        self._font_demo = inter(11, QFont.Weight.Bold, letter_spacing=0.4)
        self._font_pad = mono(14, bold=True)
        self._font_label = inter(10, QFont.Weight.Bold)

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        _qfill_card(p, r)
        accent = QLinearGradient(0, 0, self.width(), 0)
        accent.setColorAt(0.0, QColor(AMBER))
        accent.setColorAt(1.0, QColor(AMBER + "55"))
        p.fillRect(QRectF(0, 0, self.width(), 3), QBrush(accent))
        _qstroke_card(p, r, radius=10)
        # Header
        p.setPen(QColor(AMBER_LIGHT)); p.setFont(self._font_h)
        p.drawText(QRectF(16, 14, 240, 18),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "INSTANT JINGLES")
        # DEMO Sweep PLAYING countdown (top-right area)
        demo_pill = QRectF(216, 14, 188, 24)
        p.fillRect(demo_pill, _qcolor_a(GREEN, 0.18))
        p.setPen(QPen(_qcolor_a(GREEN, 0.4)))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(demo_pill.adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
        p.setPen(QColor(GREEN_LIGHT)); p.setFont(self._font_demo)
        p.drawText(demo_pill, Qt.AlignmentFlag.AlignCenter,
                   "DEMO Sweep — PLAYING")
        # 3×2 jingle tiles
        tile_w, tile_h = 124, 90
        tile_gap = 8
        for row in range(2):
            for col in range(3):
                x = 16 + col * (tile_w + tile_gap)
                y = 56 + row * (tile_h + tile_gap)
                tr = QRectF(x, y, tile_w, tile_h)
                tile_grad = QLinearGradient(0, y, 0, y + tile_h)
                tile_grad.setColorAt(0.0, _qcolor_a(AMBER, 0.20))
                tile_grad.setColorAt(1.0, _qcolor_a(AMBER, 0.08))
                p.fillRect(tr, QBrush(tile_grad))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(_qcolor_a(AMBER, 0.4)))
                p.drawRoundedRect(tr.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
                p.setPen(QColor(AMBER_LIGHT)); p.setFont(inter(20, QFont.Weight.Black))
                p.drawText(QRectF(x, y + 6, tile_w, 32),
                           Qt.AlignmentFlag.AlignCenter, "♪")
                p.setPen(QColor(TEXT_PRI)); p.setFont(self._font_label)
                p.drawText(QRectF(x, y + tile_h - 30, tile_w, 14),
                           Qt.AlignmentFlag.AlignCenter,
                           f"Jingle {row * 3 + col + 1}")
                p.setPen(QColor(TEXT_DIM)); p.setFont(mono(8, bold=False))
                p.drawText(QRectF(x, y + tile_h - 18, tile_w, 14),
                           Qt.AlignmentFlag.AlignCenter, "0:08")
        # Numeric pad (bottom)
        pad_y = 256
        p.setPen(QColor(TEXT_DIM))
        p.setFont(inter(9, QFont.Weight.Bold, letter_spacing=1.0))
        p.drawText(QRectF(16, pad_y, 300, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "HOTKEYS · 1-5")
        for i in range(5):
            x = 16 + i * 78
            r2 = QRectF(x, pad_y + 22, 70, 60)
            p.fillRect(r2, _qcolor_a(CYAN, 0.10))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(_qcolor_a(CYAN, 0.4)))
            p.drawRoundedRect(r2.adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
            p.setPen(QColor(CYAN_LIGHT)); p.setFont(self._font_pad)
            p.drawText(r2, Qt.AlignmentFlag.AlignCenter, str(i + 1))
        # Numeric pad row
        np_y = pad_y + 100
        p.setPen(QColor(TEXT_DIM))
        p.setFont(inter(9, QFont.Weight.Bold, letter_spacing=1.0))
        p.drawText(QRectF(16, np_y, 300, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "NUMERIC PAD")
        nums = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"]
        for i, n in enumerate(nums):
            x = 16 + (i % 5) * 78
            y = np_y + 22 + (i // 5) * 50
            r3 = QRectF(x, y, 70, 40)
            p.fillRect(r3, QColor(7, 8, 16, 178))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(255, 255, 255, 22)))
            p.drawRoundedRect(r3.adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
            p.setPen(QColor(TEXT_PRI)); p.setFont(self._font_pad)
            p.drawText(r3, Qt.AlignmentFlag.AlignCenter, n)
        # Search + Edit Bank links
        p.setPen(QColor(CYAN_LIGHT)); p.setFont(inter(10, QFont.Weight.Bold))
        p.drawText(QRectF(16, self.height() - 28, 100, 20),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "🔍 Search")
        p.setPen(QColor(PURPLE_LIGHT))
        p.drawText(QRectF(self.width() - 110, self.height() - 28, 100, 20),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   "⚙ Edit Bank")
        p.end()


# ════════════════════════════════════════════════════════════════════════
# HISTORY PANEL — 320 × 540 (12 alternating rows)
# ════════════════════════════════════════════════════════════════════════

class _HistoryRow:
    """Plain data slot for one row."""
    def __init__(self):
        self.time_str = "—"
        self.title = "—"
        self.artist = ""
        self.dur = ""

    def set_data(self, time_str, title, artist, dur):
        self.time_str = time_str or "—"
        self.title = title or "—"
        self.artist = artist or ""
        self.dur = dur or ""


class _HistoryPanel(QWidget):
    """Last 12 played, alternating rose/yellow tinted."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(320, 540)
        self._rows: list[_HistoryRow] = [_HistoryRow() for _ in range(12)]
        self._font_h = inter(13, QFont.Weight.Black, letter_spacing=-0.1)
        self._font_time   = mono(9, bold=True)
        self._font_title  = inter(11, QFont.Weight.Bold, letter_spacing=-0.1)
        self._font_artist = inter(9, QFont.Weight.Medium)
        self._font_dur    = mono(9, bold=True)
        self._font_link   = inter(10, QFont.Weight.Bold)

    @property
    def rows(self) -> list[_HistoryRow]:
        return self._rows

    def refresh(self) -> None:
        self.update(self.rect())

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        _qfill_card(p, r)
        _qstroke_card(p, r, radius=10)
        # Header
        p.setPen(QColor(TEXT_PRI)); p.setFont(self._font_h)
        p.drawText(QRectF(16, 14, 200, 18),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "HISTORY · LAST 12")
        # Rows
        ry0 = 42
        row_h = 38
        for i, hr in enumerate(self._rows):
            y = ry0 + i * row_h
            row_rect = QRectF(8, y, self.width() - 16, row_h - 4)
            tint = AMBER if i % 2 == 0 else RED
            p.fillRect(row_rect, _qcolor_a(tint, 0.06))
            # Time
            p.setPen(QColor(TEXT_DIM)); p.setFont(self._font_time)
            p.drawText(QRectF(16, y, 50, row_h),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       hr.time_str)
            # Title
            p.setPen(QColor(TEXT_PRI)); p.setFont(self._font_title)
            p.drawText(QRectF(70, y + 4, self.width() - 130, 18),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       hr.title)
            # Artist
            p.setPen(QColor(TEXT_SEC)); p.setFont(self._font_artist)
            p.drawText(QRectF(70, y + 18, self.width() - 130, 14),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       hr.artist)
            # Duration (right)
            p.setPen(QColor(AMBER_LIGHT)); p.setFont(self._font_dur)
            p.drawText(QRectF(self.width() - 70, y, 60, row_h),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       hr.dur)
        # View Full History link (bottom)
        p.setPen(QColor(CYAN_LIGHT)); p.setFont(self._font_link)
        p.drawText(QRectF(16, self.height() - 28, self.width() - 32, 20),
                   Qt.AlignmentFlag.AlignCenter,
                   "View Full History →")
        p.end()


# ════════════════════════════════════════════════════════════════════════
# NEXT BREAK — 420 × 264 (big amber countdown + Skip/Preview buttons)
# ════════════════════════════════════════════════════════════════════════

class _NextBreakPanel(QWidget):
    skip_clicked = pyqtSignal()
    preview_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(420, 264)
        self._countdown_s = 0
        self._countdown_label = "—"
        self._break_type = "Ad Break"
        self._break_dur = "—"
        self._spots = 0
        self._font_h     = inter(13, QFont.Weight.Black, letter_spacing=-0.1)
        self._font_count = mono(60, bold=True, letter_spacing=-2.0)
        self._font_label = inter(9, QFont.Weight.Bold, letter_spacing=1.4)
        self._font_meta  = inter(11, QFont.Weight.Medium)
        self._font_btn   = inter(11, QFont.Weight.Bold)
        # Hit zones for buttons
        self._skip_rect    = QRect(20, 210, 180, 36)
        self._preview_rect = QRect(220, 210, 180, 36)

    def set_countdown(self, seconds: int) -> None:
        if seconds == self._countdown_s:
            return
        self._countdown_s = max(0, int(seconds or 0))
        if self._countdown_s == -1 or seconds < 0:
            self._countdown_label = "—"
        else:
            m = self._countdown_s // 60
            s = self._countdown_s % 60
            self._countdown_label = f"{m:02d}:{s:02d}"
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
        _qfill_card(p, r)
        accent = QLinearGradient(0, 0, self.width(), 0)
        accent.setColorAt(0.0, QColor(AMBER))
        accent.setColorAt(1.0, QColor(AMBER + "55"))
        p.fillRect(QRectF(0, 0, self.width(), 3), QBrush(accent))
        _qstroke_card(p, r, radius=10)
        # Header
        p.setPen(QColor(AMBER_LIGHT)); p.setFont(self._font_h)
        p.drawText(QRectF(16, 14, 240, 18),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "NEXT BREAK")
        # Big countdown
        p.setPen(QColor(AMBER_LIGHT)); p.setFont(self._font_count)
        p.drawText(QRectF(0, 50, self.width(), 80),
                   Qt.AlignmentFlag.AlignCenter, self._countdown_label)
        # Sub label
        p.setPen(QColor(TEXT_DIM)); p.setFont(self._font_label)
        p.drawText(QRectF(0, 130, self.width(), 14),
                   Qt.AlignmentFlag.AlignCenter, "TO NEXT BREAK")
        # Meta line
        p.setPen(QColor(TEXT_SEC)); p.setFont(self._font_meta)
        p.drawText(QRectF(20, 156, self.width() - 40, 18),
                   Qt.AlignmentFlag.AlignCenter,
                   f"{self._break_type} · {self._break_dur} · {self._spots} spots")
        # Skip + Preview buttons
        for rect, label, color in (
                (self._skip_rect, "⏭ Skip Break", RED),
                (self._preview_rect, "▶ Preview", GREEN)):
            r2 = QRectF(rect)
            p.fillRect(r2, _qcolor_a(color, 0.18))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(_qcolor_a(color, 0.5)))
            p.drawRoundedRect(r2.adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
            p.setPen(QColor(color)); p.setFont(self._font_btn)
            p.drawText(r2, Qt.AlignmentFlag.AlignCenter, label)
        p.end()


# ════════════════════════════════════════════════════════════════════════
# RDS PANEL — 320 × 152
# ════════════════════════════════════════════════════════════════════════

class _RDSPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(320, 152)
        self._on_air_track = "—"
        self._on_air_artist = ""
        self._font_h = inter(11, QFont.Weight.Black, letter_spacing=1.4)
        self._font_clock = mono(20, bold=True)
        self._font_track = inter(11, QFont.Weight.Bold)
        self._font_artist = inter(10, QFont.Weight.Medium)
        self._font_btn = inter(10, QFont.Weight.Bold, letter_spacing=0.4)

    def set_on_air(self, title: str, artist: str) -> None:
        self._on_air_track = title or "—"
        self._on_air_artist = artist or ""
        self.update(self.rect())

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        _qfill_card(p, r)
        _qstroke_card(p, r, radius=10)
        # Header + LIVE pill
        p.setPen(QColor(TEXT_PRI)); p.setFont(self._font_h)
        p.drawText(QRectF(16, 14, 80, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "RDS")
        live = QRectF(56, 14, 50, 16)
        p.fillRect(live, _qcolor_a(RED, 0.20))
        p.setPen(QPen(_qcolor_a(RED, 0.45)))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(live.adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)
        p.setPen(QColor(RED_LIGHT)); p.setFont(inter(8, QFont.Weight.Black,
                                                     letter_spacing=1.4))
        p.drawText(live, Qt.AlignmentFlag.AlignCenter, "LIVE")
        # Clock
        now = datetime.now()
        p.setPen(QColor(CYAN_LIGHT)); p.setFont(self._font_clock)
        p.drawText(QRectF(self.width() - 80, 10, 70, 24),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   now.strftime("%H:%M"))
        # On-air track
        p.setPen(QColor(TEXT_PRI)); p.setFont(self._font_track)
        p.drawText(QRectF(16, 50, self.width() - 32, 18),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._on_air_track)
        p.setPen(QColor(TEXT_SEC)); p.setFont(self._font_artist)
        p.drawText(QRectF(16, 70, self.width() - 32, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._on_air_artist)
        # RT+ button
        btn = QRectF(16, 100, 100, 32)
        p.fillRect(btn, _qcolor_a(PURPLE_LIGHT, 0.20))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_qcolor_a(PURPLE_LIGHT, 0.5)))
        p.drawRoundedRect(btn.adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
        p.setPen(QColor(PURPLE_LIGHT)); p.setFont(self._font_btn)
        p.drawText(btn, Qt.AlignmentFlag.AlignCenter, "RT+ Send")
        p.end()


# ════════════════════════════════════════════════════════════════════════
# PROBLEMS PANEL — 320 × 96
# ════════════════════════════════════════════════════════════════════════

class _ProblemsPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(320, 96)
        self._n = 0
        self._items: list[str] = []
        self._font_h = inter(11, QFont.Weight.Black, letter_spacing=1.4)
        self._font_badge = mono(13, bold=True)
        self._font_item = inter(10, QFont.Weight.Medium)

    def set_problems(self, items: list[str]) -> None:
        self._items = list(items or [])
        self._n = len(self._items)
        self.update(self.rect())

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        _qfill_card(p, r)
        _qstroke_card(p, r, radius=10)
        # Header + N badge
        p.setPen(QColor(TEXT_PRI)); p.setFont(self._font_h)
        p.drawText(QRectF(16, 12, 200, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "PROBLEMS")
        badge = QRectF(self.width() - 44, 10, 28, 18)
        color = RED if self._n > 0 else GREEN
        p.fillRect(badge, _qcolor_a(color, 0.20))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_qcolor_a(color, 0.45)))
        p.drawRoundedRect(badge.adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)
        p.setPen(QColor(color)); p.setFont(self._font_badge)
        p.drawText(badge, Qt.AlignmentFlag.AlignCenter, str(self._n))
        # Items or empty state
        if self._items:
            for i, item in enumerate(self._items[:3]):
                y = 38 + i * 18
                p.setPen(QColor(AMBER_LIGHT)); p.setFont(self._font_item)
                p.drawText(QRectF(16, y, self.width() - 32, 16),
                           Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                           f"⚠ {item}")
        else:
            p.setPen(QColor(TEXT_DIM)); p.setFont(self._font_item)
            p.drawText(QRectF(16, 0, self.width() - 32, self.height()),
                       Qt.AlignmentFlag.AlignCenter,
                       "All systems nominal")
        p.end()


# ════════════════════════════════════════════════════════════════════════
# BOTTOM TRANSPORT BAR — 1920 × 80 (Loaded + ▶/■/slider/AutoPlay + 6 btns)
# ════════════════════════════════════════════════════════════════════════

class _CircleBtn(QWidget):
    clicked = pyqtSignal()

    def __init__(self, glyph: str, color: str, size: int = 44, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._glyph = glyph; self._color = color
        self._enabled = True
        self._font = inter(15, QFont.Weight.Black)

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
            grad.setColorAt(0.0, _qcolor_a(self._color, 0.95))
            grad.setColorAt(1.0, _qcolor_a(self._color, 0.65))
            p.setBrush(QBrush(grad))
        else:
            p.setBrush(_qcolor_a(self._color, 0.10))
        p.setPen(QPen(_qcolor_a(self._color, 0.5 if self._enabled else 0.15)))
        cx, cy = self.width() / 2, self.height() / 2
        p.drawEllipse(QPointF(cx, cy), self.width() / 2 - 1, self.height() / 2 - 1)
        p.setPen(QColor(255, 255, 255) if self._enabled else QColor(TEXT_DIM))
        p.setFont(self._font)
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._glyph)
        p.end()


class _ProgressSlider(QWidget):
    seek_requested = pyqtSignal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(540, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._progress = 0.0
        self._enabled = False

    def set_enabled(self, on: bool) -> None:
        self._enabled = bool(on)
        self.setCursor(Qt.CursorShape.PointingHandCursor if on
                       else Qt.CursorShape.ArrowCursor)
        self.update(self.rect())

    def set_progress(self, frac: float) -> None:
        f = max(0.0, min(1.0, float(frac)))
        if abs(f - self._progress) < 0.005:
            return
        self._progress = f
        self.update(self.rect())

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if self._enabled and e.button() == Qt.MouseButton.LeftButton:
            x = e.position().toPoint().x()
            self.seek_requested.emit(max(0.0, min(1.0, x / self.width())))
        super().mousePressEvent(e)

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QRectF(0, 11, self.width(), 6)
        p.fillRect(track, QColor(255, 255, 255, 22))
        if self._progress > 0:
            fill = QRectF(0, 11, self.width() * self._progress, 6)
            grad = QLinearGradient(0, 0, fill.width(), 0)
            grad.setColorAt(0.0, QColor(CYAN))
            grad.setColorAt(1.0, QColor(PURPLE_LIGHT))
            p.fillRect(fill, QBrush(grad))
            cx = fill.right()
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(CYAN_LIGHT))
            p.drawEllipse(QPointF(cx, 13), 9, 9)
        p.end()


class _AutoPlayToggle(QWidget):
    toggled = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(110, 36)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._on = False
        self._font = inter(11, QFont.Weight.Bold, letter_spacing=0.6)

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
        r = QRectF(0, 0, self.width(), self.height())
        if self._on:
            grad = QLinearGradient(0, 0, self.width(), 0)
            grad.setColorAt(0.0, _qcolor_a(PURPLE_LIGHT, 0.95))
            grad.setColorAt(1.0, _qcolor_a(PURPLE_DARK, 0.95))
            p.fillRect(r, QBrush(grad))
        else:
            p.fillRect(r, _qcolor_a(PURPLE_LIGHT, 0.12))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_qcolor_a(PURPLE_LIGHT, 0.5)))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        p.setPen(QColor(255, 255, 255) if self._on else QColor(PURPLE_LIGHT))
        p.setFont(self._font)
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, "AutoPlay")
        p.end()


class _PillBtn(QWidget):
    clicked = pyqtSignal()

    def __init__(self, label: str, color: str, w: int = 70, parent=None):
        super().__init__(parent)
        self.setFixedSize(w, 36)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._label = label; self._color = color
        self._enabled = True
        self._active = False
        self._font = inter(10, QFont.Weight.Bold)

    def set_enabled(self, on: bool) -> None:
        self._enabled = bool(on)
        self.update(self.rect())

    def set_active(self, on: bool) -> None:
        if on == self._active:
            return
        self._active = bool(on)
        self.update(self.rect())

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if self._enabled and e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self); p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        bg = 0.30 if self._active else (0.18 if self._enabled else 0.06)
        p.fillRect(r, _qcolor_a(self._color, bg))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_qcolor_a(self._color, 0.5 if self._enabled else 0.15)))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
        col = (QColor(255, 255, 255) if self._active
               else _qcolor_a(self._color, 0.95 if self._enabled else 0.30))
        p.setPen(col); p.setFont(self._font)
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, self._label)
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
        self._font_load = inter(8, QFont.Weight.Bold, letter_spacing=1.4)
        self._font_load_val = mono(15, bold=True, letter_spacing=-0.3)

        # Transport (center)
        self._play = _CircleBtn("▶", GREEN, 44, self)
        self._play.move(380, 18); self._play.clicked.connect(self.play_clicked.emit)
        self._stop = _CircleBtn("■", RED, 44, self)
        self._stop.move(432, 18); self._stop.clicked.connect(self.stop_clicked.emit)
        self._slider = _ProgressSlider(self)
        self._slider.move(490, 27)
        self._slider.seek_requested.connect(self.seek_requested.emit)
        self._autoplay = _AutoPlayToggle(self)
        self._autoplay.move(1044, 22)
        self._autoplay.toggled.connect(self.autoplay_toggled.emit)

        # 6-button cluster (right)
        self._btns = []
        labels = [("UP", CYAN), ("DOWN", CYAN), ("STOP ALL", RED),
                  ("AUTO", PURPLE_LIGHT), ("MIXFADE", AMBER), ("LOOP", PURPLE_LIGHT)]
        slots = [self.up_clicked, self.down_clicked, self.stop_all_clicked,
                 self.auto_clicked, self.mixfade_clicked, self.loop_clicked]
        for i, (label, color) in enumerate(labels):
            b = _PillBtn(label, color, 80, self)
            b.move(1180 + i * 88, 22)
            b.clicked.connect(slots[i].emit)
            self._btns.append(b)

    def set_loaded_total(self, txt: str) -> None:
        if txt == self._loaded_total:
            return
        self._loaded_total = txt
        self.update(QRect(0, 0, 360, self.height()))

    def set_progress(self, frac: float) -> None:
        self._slider.set_progress(frac)

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
        _qfill_card(p, r)
        _qstroke_card(p, r, radius=10)
        # Loaded duration label
        p.setPen(QColor(TEXT_DIM)); p.setFont(self._font_load)
        p.drawText(QRectF(20, 14, 200, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "LOADED PLAYLIST")
        p.setPen(QColor(AMBER_LIGHT)); p.setFont(self._font_load_val)
        p.drawText(QRectF(20, 32, 200, 22),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._loaded_total)
        # $ indicator + ≡ menu
        p.setPen(QColor(GREEN_LIGHT)); p.setFont(inter(13, QFont.Weight.Bold))
        p.drawText(QRectF(220, 22, 24, 36),
                   Qt.AlignmentFlag.AlignCenter, "$")
        p.setPen(QColor(TEXT_SEC)); p.setFont(inter(13, QFont.Weight.Bold))
        p.drawText(QRectF(252, 22, 24, 36),
                   Qt.AlignmentFlag.AlignCenter, "≡")
        p.end()


# ════════════════════════════════════════════════════════════════════════
# STUDIO — the screen
# ════════════════════════════════════════════════════════════════════════

class Studio(QWidget):
    """Premium broadcast Studio (Figma 312:2 — 1920×1080).

    Constructor preserved verbatim from Phase D legacy; engine + scheduler
    wires preserved verbatim. Visual layer rebuilt to the new design.

    Public signals:
      breadcrumb_clicked(str)  — legacy back-compat (emits 'control_panel'
                                 and 'scheduling_hub' as appropriate)
      screen_requested(str)    — premium-pattern route emit (emits
                                 'scheduling_hub' from Control Panel button)
    """

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
        # Page background (matches the other premium screens)
        self.setStyleSheet(
            "background: qlineargradient("
            "x1:0,y1:0,x2:1,y2:1, stop:0 #0a0d1a, "
            "stop:0.5 #06080f, stop:1 #020308);"
        )

        # Phase D state — names PRESERVED for the 9 existing tests
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

        # Build widgets
        self._build_chrome()
        self._build_master_strip()
        self._build_body()
        self._build_bottom_transport()

        # Engine signal connections (filtered by cid in handlers)
        if self._engine is not None:
            self._engine.position_changed.connect(self._on_engine_position)
            self._engine.playback_ended.connect(self._on_engine_playback_ended)
            self._engine.error_occurred.connect(self._on_engine_error)

        # Scheduler signal connections (Phase D4 wires preserved)
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

        # 1Hz tick for header clock + RDS wall clock
        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(1000)
        self._tick_timer.timeout.connect(self._on_tick)
        self._tick_timer.start()
        self._on_tick()

        # Initial state
        self._refresh_history()
        self._apply_idle_state()
        self._update_status_pills()
        self._refresh_upcoming()
        self._refresh_libraries()

        log.info("Studio ready (Figma 312:2 — Premium Broadcast)")

    # ────────────────────────────────────────────────────────────────────
    # WIDGET BUILDERS
    # ────────────────────────────────────────────────────────────────────

    def _build_chrome(self) -> None:
        self._header = _Header(self)
        self._header.move(0, 0)
        self._header.control_panel_clicked.connect(self._on_control_panel)
        self._header.settings_clicked.connect(self._on_settings)

    def _build_master_strip(self) -> None:
        self._now_player = _NowPlayer(self)
        self._now_player.move(16, MASTER_Y + 4)

        self._next_chip = _NextChip(self)
        self._next_chip.move(864, MASTER_Y + 4)

        self._control_cluster = _ControlCluster(self)
        self._control_cluster.move(1080, MASTER_Y + 8)
        self._control_cluster.restart_clicked.connect(self._on_restart_clicked)
        self._control_cluster.loop_toggled.connect(self._on_loop_toggled)
        self._control_cluster.pause_clicked.connect(self._on_pause_clicked)
        self._control_cluster.stop_next_clicked.connect(self._on_stop_next_clicked)

        self._level_meters = _LevelMeters(self)
        self._level_meters.move(1392, MASTER_Y + 8)

        self._clock_face = _AnalogClock(self)
        self._clock_face.move(1488, MASTER_Y + 8)

        self._wordmark = _Wordmark(self)
        self._wordmark.move(1584, MASTER_Y + 8)

    def _build_body(self) -> None:
        self._upcoming = _UpComingQueue(self)
        self._upcoming.move(16, BODY_Y)
        self._upcoming.song_double_clicked.connect(self._on_queue_song_play)

        self._libraries = _LibrariesPanel(self)
        self._libraries.move(412, BODY_Y)

        self._instant_jingles = _InstantJingles(self)
        self._instant_jingles.move(1148, BODY_Y)

        self._history_panel = _HistoryPanel(self)
        self._history_panel.move(1584, BODY_Y)
        self._history_rows = self._history_panel.rows

        self._next_break = _NextBreakPanel(self)
        self._next_break.move(1148, BODY_Y + 556)

        self._rds = _RDSPanel(self)
        self._rds.move(1584, BODY_Y + 556)

        self._problems = _ProblemsPanel(self)
        self._problems.move(1584, BODY_Y + 712)

    def _build_bottom_transport(self) -> None:
        self._bottom = _BottomTransport(self)
        self._bottom.move(0, BOTTOM_TRANS_Y)
        self._bottom.play_clicked.connect(self._on_pause_clicked)
        self._bottom.stop_clicked.connect(self._on_fade_out_clicked)
        self._bottom.seek_requested.connect(self._on_bottom_seek)
        self._bottom.up_clicked.connect(self._on_up_clicked)
        self._bottom.down_clicked.connect(self._on_down_clicked)
        self._bottom.stop_all_clicked.connect(self._on_stop_all_clicked)

    # ────────────────────────────────────────────────────────────────────
    # QUEUE SOURCE — preserved from legacy (D5 will replace one day)
    # ────────────────────────────────────────────────────────────────────

    def _load_queue_from_db(self) -> list[dict]:
        out: list[dict] = []
        try:
            rows = self._db._conn().execute(
                "SELECT id, title, artist, file_path, duration_ms, "
                "category_id, energy, intro_point_ms "
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
                keys = r.keys() if hasattr(r, "keys") else []
                intro_ms = (int(r["intro_point_ms"] or 0)
                            if "intro_point_ms" in keys else 0)
                out.append({
                    "id":             r["id"],
                    "title":          r["title"] or "—",
                    "artist":         r["artist"] or "",
                    "file_path":      path,
                    "duration_ms":    int(r["duration_ms"] or 0),
                    "duration_str":   _fmt_duration(int(r["duration_ms"] or 0)),
                    "category":       "",
                    "intro_point_ms": intro_ms,
                    "_item_type":     "song",
                    "is_break":       False,
                    "is_current":     False,
                })
            if len(out) >= 12:
                break
        return out

    # ────────────────────────────────────────────────────────────────────
    # PRESERVED legacy helpers
    # ────────────────────────────────────────────────────────────────────

    def _apply_idle_state(self) -> None:
        self._now_player.set_track(None)
        self._control_cluster.set_idle(True)
        self._control_cluster.set_paused(False)
        self._bottom.set_progress(0.0)
        self._bottom.set_transport_enabled(False)
        # NEXT chip from queue head
        next_song = self._compute_next_up()
        if next_song:
            self._next_chip.set_next(
                next_song.get("title") or "—",
                next_song.get("artist") or "")
        else:
            self._next_chip.set_next("—", "")

    def _apply_playing_state(self, song: dict) -> None:
        track = {
            "title":  song.get("title", "—"),
            "artist": song.get("artist", ""),
            "duration_ms": self._current_duration_ms or
                           int(song.get("duration_ms", 0)),
            "tags":   self._derive_tags(song),
        }
        self._now_player.set_track(track)
        self._control_cluster.set_idle(False)
        self._control_cluster.set_paused(False)
        self._bottom.set_transport_enabled(True)
        # NEXT chip = next after this
        nxt = self._compute_next_up(after_song_id=song.get("id"))
        if nxt:
            self._next_chip.set_next(nxt.get("title") or "—",
                                     nxt.get("artist") or "")
        else:
            self._next_chip.set_next("—", "")
        # RDS reflects on-air
        self._rds.set_on_air(track["title"], track["artist"])

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

    def _compute_next_up(self, after_song_id: Optional[int] = None) -> Optional[dict]:
        if not self._queue_songs:
            return None
        if after_song_id is None:
            return self._queue_songs[0]
        idx = next((i for i, sg in enumerate(self._queue_songs)
                    if sg.get("id") == after_song_id), -1)
        nxt_idx = idx + 1
        if 0 <= nxt_idx < len(self._queue_songs):
            return self._queue_songs[nxt_idx]
        return None

    @staticmethod
    def _fmt_remaining(ms_remaining: int) -> str:
        if ms_remaining <= 0:
            return "0:00"
        total_s = int(ms_remaining // 1000)
        m = total_s // 60
        s = total_s % 60
        return f"-{m}:{s:02d}"

    # ────────────────────────────────────────────────────────────────────
    # QUEUE → DECK (PRESERVED verbatim from legacy)
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
    # TRANSPORT HANDLERS (PRESERVED)
    # ────────────────────────────────────────────────────────────────────

    def _on_pause_clicked(self) -> None:
        if self._playback_cid is None or self._engine is None:
            return
        state = self._engine.get_state(self._playback_cid)
        if state == "playing":
            self._engine.pause(self._playback_cid)
            self._control_cluster.set_paused(True)
            log.info("[studio] paused")
        elif state == "paused":
            self._engine.resume(self._playback_cid)
            self._control_cluster.set_paused(False)
            log.info("[studio] resumed")

    def _on_restart_clicked(self) -> None:
        if self._playback_cid is None or self._engine is None:
            return
        self._engine.seek_to_ms(self._playback_cid, 0)
        if self._engine.get_state(self._playback_cid) != "playing":
            self._engine.play(self._playback_cid)
            self._control_cluster.set_paused(False)
        log.info("[studio] restart → 0ms")

    def _on_stop_next_clicked(self) -> None:
        self._stop_after_current = True
        log.info("[studio] stop-after-current flag set (D5 will honor on EOS)")

    def _on_fade_out_clicked(self) -> None:
        if self._playback_cid is None or self._engine is None:
            return
        cid = self._playback_cid
        try:
            self._engine.fade_volume_to(cid, 0, self.FADE_OUT_MS)
        except Exception as exc:
            log.warning(f"[studio] fade_volume_to failed: {exc}")
            return
        log.info(f"[studio] fade out → 0 over {self.FADE_OUT_MS}ms")
        self._fade_out_timer = QTimer(self)
        self._fade_out_timer.setSingleShot(True)
        self._fade_out_timer.timeout.connect(self._on_fade_out_complete)
        self._fade_out_timer.start(self.FADE_OUT_MS + 100)

    def _on_fade_out_complete(self) -> None:
        if self._playback_cid is not None and self._engine is not None:
            try:
                self._engine.cleanup(self._playback_cid)
            except Exception:
                pass
            self._playback_cid = None
        self._playback_kind = None
        self._playback_campaign_id = None
        self._current_track = None
        self._apply_idle_state()
        self._update_status_pills()
        log.info("[studio] fade out complete — deck idle")

    def _on_loop_toggled(self, on: bool) -> None:
        self._loop_enabled = on
        log.info(f"[studio] loop = {on}")

    def _on_master_vol_changed(self, level: int) -> None:
        self._master_volume = level
        if self._playback_cid is not None and self._engine is not None:
            self._engine.set_volume(self._playback_cid, level)

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
        # Decorative — no queue-cursor in legacy
        pass

    def _on_down_clicked(self) -> None:
        pass

    def _on_stop_all_clicked(self) -> None:
        # Stop all engine channels
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
    # ENGINE SIGNAL HANDLERS (PRESERVED)
    # ────────────────────────────────────────────────────────────────────

    def _on_engine_position(self, channel_id: int, position_ms: int) -> None:
        if channel_id != self._playback_cid:
            return
        dur = self._current_duration_ms
        if dur > 0:
            self._now_player.set_progress(position_ms, dur)
            self._bottom.set_progress(position_ms / dur)

    def _on_engine_playback_ended(self, channel_id: int) -> None:
        """PRESERVED verbatim from legacy Phase D5."""
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

        # Path (a): spot ended → advance from pre-spot anchor
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

        # Path (b): stop-next flag wins
        if kind == "deck" and self._stop_after_current:
            self._stop_after_current = False
            self._current_track = None
            log.info("[studio] stop-next consumed → idle")
            self._apply_idle_state()
            self._update_status_pills()
            return

        # Path (c): loop replays the same song
        if (kind == "deck" and self._loop_enabled and pre_track is not None):
            log.info(f"[studio] loop replay → {pre_track.get('title')!r}")
            self._on_queue_song_play(pre_track)
            return

        # Path (d): auto-advance
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
        # Path 2: in-memory queue
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

    @staticmethod
    def _tags_for_item_type(item_type: str) -> list[str]:
        """PRESERVED — used by tests/test_studio_item_dispatch.py."""
        return {
            "song":        [],
            "jingle":      ["Jingle", "Auto"],
            "sweeper":     ["Sweeper", "Auto"],
            "station_id":  ["Station ID", "Auto"],
            "voice_track": ["Voice Track", "Auto"],
            "spot":        ["Ad Break", "Auto"],
        }.get(item_type, [])

    def _on_engine_error(self, channel_id: int, message: str) -> None:
        if channel_id != self._playback_cid:
            return
        log.warning(f"[studio] engine error: {message}")
        self._on_engine_playback_ended(channel_id)

    # ────────────────────────────────────────────────────────────────────
    # SCHEDULER SIGNAL HANDLERS (PRESERVED)
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
        chosen_filename = (chosen["filename"] if "filename" in chosen_keys
                           and chosen["filename"] else "—")
        self._current_duration_ms = (self._engine.get_duration_ms(cid)
                                     or chosen_duration_ms)
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
        log.info(f"[studio] auto-spot ch={cid} campaign={campaign_id} "
                 f"file={os.path.basename(path)} "
                 f"dur={self._current_duration_ms}ms")
        self._update_status_pills()
        self._refresh_history()

    def _on_scheduler_song_advance(self) -> None:
        log.info("[studio] scheduler: song_auto_advance (D5 wires internally)")

    def _on_scheduler_break_warn(self, seconds_until: int) -> None:
        log.info(f"[studio] scheduler: break_approaching in {seconds_until}s")

    def _on_scheduler_next_break_in(self, seconds: int) -> None:
        if hasattr(self, "_next_break") and self._next_break is not None:
            self._next_break.set_countdown(seconds)

    # ────────────────────────────────────────────────────────────────────
    # POLISH HELPERS (PRESERVED + adapted)
    # ────────────────────────────────────────────────────────────────────

    def _refresh_history(self) -> None:
        if not getattr(self, "_history_rows", None):
            return
        try:
            rows = self._db.get_history(limit=len(self._history_rows))
        except Exception as exc:
            log.debug(f"[studio] history refresh failed: {exc}")
            return
        for i, row_widget in enumerate(self._history_rows):
            if i < len(rows):
                r = rows[i]
                keys = r.keys() if hasattr(r, "keys") else []
                time_str = self._fmt_history_time(r["played_at"])
                entry_type = (r["entry_type"] if "entry_type" in keys
                              else "song")
                if entry_type == "spot":
                    title = (r["campaign_name"]
                             if "campaign_name" in keys
                             and r["campaign_name"] else "—")
                    artist = "(spot)"
                else:
                    title = (r["title"] if "title" in keys
                             and r["title"] else "—")
                    artist = (r["artist"] if "artist" in keys
                              and r["artist"] else "")
                dur_ms = (r["duration_ms"] if "duration_ms" in keys
                          and r["duration_ms"] else 0)
                row_widget.set_data(
                    time_str, title, artist, _fmt_duration(int(dur_ms or 0)))
            else:
                row_widget.set_data("—", "—", "", "")
        self._history_panel.refresh()

    @staticmethod
    def _fmt_history_time(played_at) -> str:
        if not played_at:
            return "—"
        s = str(played_at)
        if len(s) >= 16 and s[10] == " ":
            return s[11:16]
        return "—"

    def _update_status_pills(self) -> None:
        if not hasattr(self, "_header") or self._header is None:
            return
        on_air = (self._playback_cid is not None
                  and self._playback_kind in ("deck", "spot"))
        auto_mode = (self._scheduler is not None
                     and self._scheduler.is_running())
        self._header.set_on_air(on_air)
        self._header.set_auto_mode(auto_mode)

    def _refresh_upcoming(self) -> None:
        if hasattr(self, "_upcoming"):
            self._upcoming.set_queue(self._queue_songs[:5])

    def _refresh_libraries(self) -> None:
        if hasattr(self, "_libraries"):
            self._libraries.set_songs(self._queue_songs)
        # Also drive bottom-transport "loaded" total
        total_ms = sum(int(s.get("duration_ms") or 0)
                       for s in self._queue_songs)
        s = total_ms // 1000
        h, rem = divmod(s, 3600)
        m, ss = divmod(rem, 60)
        if hasattr(self, "_bottom"):
            self._bottom.set_loaded_total(f"{h}:{m:02d}:{ss:02d}")

    # ────────────────────────────────────────────────────────────────────
    # ROUTING
    # ────────────────────────────────────────────────────────────────────

    def _on_control_panel(self) -> None:
        # Per Q3 vote B: emit both signals — premium-pattern + back-compat
        self.screen_requested.emit("scheduling_hub")
        self.breadcrumb_clicked.emit("control_panel")

    def _on_settings(self) -> None:
        QMessageBox.information(
            self, "Settings", "Settings — coming soon.")

    # ────────────────────────────────────────────────────────────────────
    # 1Hz tick — header clock + RDS clock
    # ────────────────────────────────────────────────────────────────────

    def _on_tick(self) -> None:
        now = datetime.now()
        self._header.set_clock(now.strftime("%H:%M:%S"))

    # ────────────────────────────────────────────────────────────────────
    # Lifecycle: stop-on-hide is intentional NO-OP (broadcasting
    # continues). PRESERVED from legacy.
    # ────────────────────────────────────────────────────────────────────

    def hideEvent(self, event):
        super().hideEvent(event)
