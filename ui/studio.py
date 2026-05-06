"""
RadioAI Studio Pro — Studio v3 (Figma 312:2 — Premium Jazler Style).

STEP-BY-STEP REBUILD per Plan A (Kavish, 2026-05-06):
  ✅ Step 1: 1920×1080 canvas + new Header           ← THIS COMMIT
  □  Step 2: Master strip (NowPlayer + NextChip + ControlCluster +
             LevelMeters + ClockFace + Wordmark)
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
    QPainter, QColor, QPen, QBrush, QLinearGradient, QFont,
    QMouseEvent, QPaintEvent,
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

        # Build widgets — Step 1 = Header only, rest are placeholders
        self._build_header()
        self._build_master_strip_placeholders()
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
        self._update_status_pills()

        log.info("Studio ready (Figma 312:2 — Step 1: Header)")

    # ── Widget builders ──────────────────────────────────────────────────

    def _build_header(self) -> None:
        self._header = _Header(self)
        self._header.move(0, 0)
        self._header.control_panel_clicked.connect(self._on_control_panel)
        self._header.settings_clicked.connect(self._on_settings)

    def _build_master_strip_placeholders(self) -> None:
        """Step 2 will replace these — for now a single labeled rect."""
        self._master_placeholder = _PlaceholderFrame(
            "MASTER STRIP — NowPlayer / NextChip / ControlCluster / "
            "LevelMeters / ClockFace / Wordmark",
            "Step 2",
            WINDOW_W - 32, MASTER_H - 8, accent=CYAN, parent=self)
        self._master_placeholder.move(16, MASTER_Y + 4)

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
        # Step 2 will wire NowPlayer + waveform + countdown
        # For now no-op — position drives nothing visible in Step 1

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
            self._update_status_pills()
            return

        # (b) stop-next consumed
        if kind == "deck" and self._stop_after_current:
            self._stop_after_current = False
            self._current_track = None
            log.info("[studio] stop-next consumed → idle")
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
            self._update_status_pills()
            return

        # Defensive
        self._current_track = None
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
