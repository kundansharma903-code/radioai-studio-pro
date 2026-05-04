"""
RadioAI Studio Pro — Audio Cue Editor Dialog
Pixel-accurate match of Figma node 30:2 (920×680).

Custom waveform widget with 5 priority-coloured zones + 6 cue markers:
  START (green) → INTRO (cyan) → HOOK IN (pink) → HOOK OUT (pink) →
  OUTRO (orange) → MIX (red).

Phase 5 build status:
  [✓] 5-A — skeleton + waveform widget + 6 stationary markers
  [ ] 5-B — marker drag interaction + cue cards + fade sliders + validation
  [ ] 5-C — options bar + metadata + AI banner + integration + DB save

═════════════════════════════════════════════════════════════════════════════
PERFORMANCE NOTES — DO NOT VIOLATE  (Spot Programming grid lessons)
═════════════════════════════════════════════════════════════════════════════
  1. event.rect() CLIPPING — paintEvent should respect the dirty rect.
     Less critical here than for the 4064px-tall Spot grid (this widget is
     ~880×200), but the discipline keeps repaints cheap during drag.
  2. mouseMoveEvent BOUNDED UPDATES — when a marker drags, repaint only
     the rect spanning OLD_X..NEW_X (with margin for the flag), never
     bare self.update(). Prevents 60fps full-widget repaint during drag.
  3. NO setMouseTracking — only the marker hit-zones need mouse events.
  4. NO db calls in paintEvent — all reads from cached state.
  5. NO self.update() inside paintEvent — recursion / paint storm guard.
═════════════════════════════════════════════════════════════════════════════
"""

import logging
import math
import os
import random
from typing import Optional

from PyQt6.QtCore import Qt, QRect, QRectF, pyqtSignal
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QPainterPath, QFont, QCursor, QLinearGradient,
    QBrush,
)
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QLineEdit, QHBoxLayout, QVBoxLayout,
    QMessageBox, QSizePolicy,
)

from ui.widgets._tokens import (
    inter, mono, rgba,
    BG_BASE, BG_CARD, BG_ELEVATED,
    TEXT_PRI, TEXT_SEC, TEXT_MUTED, TEXT_DIM,
    PURPLE, PURPLE_LIGHT, PURPLE_DARK,
    CYAN, CYAN_LIGHT, GREEN, GREEN_LIGHT, AMBER, AMBER_LIGHT,
    RED, RED_LIGHT, PINK, PINK_LIGHT,
)
from ui.dialogs.base_dialog import BaseDialog

log = logging.getLogger("AudioCueEditorDialog")


# ════════════════════════════════════════════════════════════════════════════
# Constants
# ════════════════════════════════════════════════════════════════════════════

# Marker IDs in canonical order. Each maps to a DB column suffix.
MARKER_IDS = ("start", "intro", "hook_in", "hook_out", "outro", "mix")

# Display labels for the marker flags
MARKER_LABELS = {
    "start":    "START",
    "intro":    "INTRO",
    "hook_in":  "HOOK IN",
    "hook_out": "HOOK OUT",
    "outro":    "OUTRO",
    "mix":      "MIX",
}

# Colors per marker (flag colour + the right edge of its zone)
MARKER_COLORS = {
    "start":    GREEN,
    "intro":    CYAN,
    "hook_in":  PINK,
    "hook_out": PINK,
    "outro":    AMBER,
    "mix":      RED,
}

# DB column name for each marker_id (canonical _ms columns only)
MARKER_DB_FIELD = {
    "start":    "start_point_ms",
    "intro":    "intro_point_ms",
    "hook_in":  "hook_in_ms",
    "hook_out": "hook_out_ms",
    "outro":    "outro_point_ms",
    "mix":      "mix_point_ms",
}

# Default positions (as fraction of duration) when a song has no saved cues
DEFAULT_POSITIONS = {
    "start":    0.00,
    "intro":    0.05,
    "hook_in":  0.25,
    "hook_out": 0.50,
    "outro":    0.80,
    "mix":      1.00,
}


def _fmt_ms(ms: int) -> str:
    """Format ms as MM:SS or M:SS depending on length."""
    s = int((ms or 0) // 1000)
    return f"{s // 60}:{s % 60:02d}"


def _fmt_ms_decimal(ms: int) -> str:
    """Format ms as 'SS.s' (e.g. '09.4') for cue card displays under 1 min,
    or '01:20.0' for longer."""
    if ms is None:
        ms = 0
    total_s = ms / 1000.0
    if total_s < 60:
        return f"{total_s:04.1f}s"
    m = int(total_s // 60)
    s = total_s - m * 60
    return f"{m:02d}:{s:04.1f}"


# ════════════════════════════════════════════════════════════════════════════
# Header chrome
# ════════════════════════════════════════════════════════════════════════════

class _WaveformIcon(QWidget):
    """36×36 orange-tinted waveform-bars icon for the dialog header."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(36, 36)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0, 0, 36, 36)
        path = QPainterPath(); path.addRoundedRect(rect, 8, 8)
        p.setClipPath(path)
        bg = QColor(AMBER); bg.setAlphaF(0.20)
        p.fillRect(rect, bg)
        p.setClipping(False)
        bc = QColor(AMBER); bc.setAlphaF(0.50)
        p.setPen(QPen(bc, 1)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 8, 8)
        # Draw 5 small bars suggesting waveform
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(AMBER_LIGHT))
        heights = [4, 9, 14, 8, 5]
        for i, h in enumerate(heights):
            x = 7 + i * 5
            y = (36 - h) // 2
            p.drawRoundedRect(QRectF(x, y, 3, h), 1, 1)


class _SongInfoCard(QFrame):
    """Header-right card showing the song's name + run time."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._title = "—"
        self._artist = ""
        self._duration_ms = 0
        self.setFixedSize(220, 40)
        self.setStyleSheet(
            f"QFrame {{ background: {BG_ELEVATED}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; "
            f"border-radius: 6px; }}"
        )

    def set_song(self, title: str, artist: str, duration_ms: int):
        self._title = title or "—"
        self._artist = artist or ""
        self._duration_ms = int(duration_ms or 0)
        self.update()

    def paintEvent(self, _e):
        super().paintEvent(_e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Top line: artist — title (small)
        meta = f"{self._artist} — {self._title}" if self._artist else self._title
        p.setPen(QColor(TEXT_PRI))
        p.setFont(inter(10, QFont.Weight.DemiBold))
        fm = p.fontMetrics()
        elided = fm.elidedText(meta, Qt.TextElideMode.ElideRight,
                                self.width() - 20)
        p.drawText(QRectF(10, 4, self.width() - 20, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   elided)
        # Bottom line: Run Time + value
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(inter(8, QFont.Weight.Bold, letter_spacing=1.0))
        p.drawText(QRectF(10, 22, 60, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "Run Time:")
        p.setPen(QColor(AMBER_LIGHT))
        p.setFont(mono(11, bold=True))
        p.drawText(QRectF(70, 22, self.width() - 80, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   _fmt_ms(self._duration_ms))


# ════════════════════════════════════════════════════════════════════════════
# THE WAVEFORM — custom-painted widget with synthetic bars + 6 markers
# ════════════════════════════════════════════════════════════════════════════

class _CueWaveformWidget(QFrame):
    """Synthetic waveform with 5 priority-colored zones + 6 cue markers.

    Phase 5-A: stationary markers (no drag yet — comes in 5-B). Markers are
    rendered as vertical lines with a top label-flag. Bars are colored by
    which zone they fall into (between adjacent marker positions).

    State:
        self._duration_ms          — total audio duration in ms
        self._positions: dict      — marker_id → ms position
        self._bars: list[float]    — pre-computed synthetic amplitudes (0..1)
    """

    BAR_COUNT = 110
    HEADER_RULER_H = 22     # space at top for time labels
    FLAG_H = 24             # flag area height at top

    marker_changed = pyqtSignal(str, int)   # marker_id, new_ms (Phase 5-B)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(220)
        self.setStyleSheet(
            f"QFrame {{ background: #0a0c14; "
            f"border: 1px solid {rgba('#ffffff', 0.04)}; "
            f"border-radius: 6px; }}"
        )

        self._duration_ms: int = 180_000        # safe default — 3 min
        self._positions: dict[str, int] = {}
        self._set_default_positions()

        # Synthetic bars — same generator each open so the layout is stable
        self._bars = self._gen_bars(seed=2026)

        # Drag state (Phase 5-B)
        self._drag_marker: Optional[str] = None   # marker_id during drag
        self._hover_marker: Optional[str] = None  # marker_id under cursor

        # Mouse tracking is required so the cursor changes on hover. The
        # mouseMoveEvent stays cheap because we only repaint when the
        # hovered marker actually changes (or during an active drag).
        self.setMouseTracking(True)
        self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))

    # ── Public API ────────────────────────────────────────────────────────

    def set_duration_ms(self, ms: int):
        self._duration_ms = max(1000, int(ms or 0))
        # Clamp existing positions to new duration
        for k, v in self._positions.items():
            if v > self._duration_ms:
                self._positions[k] = self._duration_ms
        self.update()

    def set_positions(self, positions: dict[str, int]):
        """positions = {'start': ms, 'intro': ms, ...} — only updates the keys
        present in the dict; other markers keep their current values."""
        for k, v in positions.items():
            if k in MARKER_IDS:
                self._positions[k] = max(0, min(self._duration_ms, int(v or 0)))
        self.update()

    def get_positions(self) -> dict[str, int]:
        return dict(self._positions)

    def nudge_marker(self, marker_id: str, delta_ms: int) -> int:
        """Move a marker by delta_ms (signed, can be negative). Clamped to
        its bounds. Returns the resulting position. Used by cue card << >>."""
        if marker_id not in MARKER_IDS:
            return 0
        new_ms = self._clamp_marker(
            marker_id, self._positions[marker_id] + int(delta_ms))
        if new_ms != self._positions[marker_id]:
            self._positions[marker_id] = new_ms
            self.update()
            self.marker_changed.emit(marker_id, new_ms)
        return new_ms

    def reset_marker(self, marker_id: str) -> int:
        """Restore a single marker to its default position fraction."""
        if marker_id not in MARKER_IDS:
            return 0
        default_ms = int(self._duration_ms * DEFAULT_POSITIONS[marker_id])
        new_ms = self._clamp_marker(marker_id, default_ms)
        self._positions[marker_id] = new_ms
        self.update()
        self.marker_changed.emit(marker_id, new_ms)
        return new_ms

    # ── Internals ─────────────────────────────────────────────────────────

    def _set_default_positions(self):
        for m in MARKER_IDS:
            frac = DEFAULT_POSITIONS[m]
            self._positions[m] = int(self._duration_ms * frac)

    # ── Geometry helpers (used by hit-test + drag) ───────────────────────

    def _plot_left(self) -> int:
        return 12

    def _plot_right(self) -> int:
        return self.width() - 12

    def _plot_w(self) -> int:
        return max(1, self._plot_right() - self._plot_left())

    def _ms_to_x(self, ms: int) -> int:
        return self._plot_left() + int(self._plot_w() *
                                        (ms / max(1, self._duration_ms)))

    def _x_to_ms(self, x: int) -> int:
        ratio = (x - self._plot_left()) / self._plot_w()
        return max(0, min(self._duration_ms,
                          int(round(ratio * self._duration_ms))))

    # ── Hit-testing (find marker under cursor) ───────────────────────────

    HIT_RADIUS = 10   # pixels around marker line

    def _marker_at(self, pos) -> Optional[str]:
        """Return marker_id closest to `pos` within HIT_RADIUS, else None."""
        x = int(pos.x())
        y = int(pos.y())
        # Only allow grabs in the plot area + flag strip — not the bottom
        # labels area
        if y < 0 or y > self.height() - 22:
            return None
        best_id = None
        best_dx = self.HIT_RADIUS + 1
        for m in MARKER_IDS:
            mx = self._ms_to_x(self._positions[m])
            dx = abs(x - mx)
            if dx <= self.HIT_RADIUS and dx < best_dx:
                best_id = m
                best_dx = dx
        return best_id

    # ── Clamping (per-marker bounds based on neighbors) ──────────────────

    HOOK_MIN_MS = 100   # hook duration must be ≥ 100ms

    def _clamp_marker(self, marker_id: str, new_ms: int) -> int:
        """Bound new_ms to the marker's allowed range based on its
        neighbors. Caller is responsible for setting it back into
        self._positions.

        Order constraint:
          START ≤ INTRO ≤ HOOK IN < HOOK OUT ≤ OUTRO ≤ MIX ≤ duration
        Hook duration enforced strict-greater (HOOK_MIN_MS).
        """
        p = self._positions
        bounds = {
            "start":    (0,                 p["intro"]),
            "intro":    (p["start"],        p["hook_in"]),
            "hook_in":  (p["intro"],        p["hook_out"] - self.HOOK_MIN_MS),
            "hook_out": (p["hook_in"] + self.HOOK_MIN_MS, p["outro"]),
            "outro":    (p["hook_out"],     p["mix"]),
            "mix":      (p["outro"],        self._duration_ms),
        }[marker_id]
        lo, hi = bounds
        # Snap to 100ms grid (0.1s precision)
        snapped = int(round(new_ms / 100.0) * 100)
        return max(lo, min(hi, snapped))

    # ── Mouse handlers (drag + hover) ────────────────────────────────────

    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        marker = self._marker_at(e.position())
        if marker is not None:
            self._drag_marker = marker
            self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        x = int(e.position().x())

        if self._drag_marker is not None:
            # Active drag — clamp the new position and emit
            new_ms = self._clamp_marker(
                self._drag_marker, self._x_to_ms(x))
            old_ms = self._positions[self._drag_marker]
            if new_ms != old_ms:
                # Compute dirty rect: union of old + new marker neighborhoods,
                # so we don't repaint the whole 880×220 widget on every
                # pixel of mouse movement.
                old_x = self._ms_to_x(old_ms)
                new_x = self._ms_to_x(new_ms)
                lo_x = min(old_x, new_x) - 30
                hi_x = max(old_x, new_x) + 30
                dirty = QRect(lo_x, 0,
                              max(60, hi_x - lo_x),
                              self.height())
                self._positions[self._drag_marker] = new_ms
                self.update(dirty)
                self.marker_changed.emit(self._drag_marker, new_ms)
            return

        # No drag — update hover state for cursor
        hover_id = self._marker_at(e.position())
        if hover_id != self._hover_marker:
            self._hover_marker = hover_id
            if hover_id is not None:
                self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
            else:
                self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        if self._drag_marker is not None:
            self._drag_marker = None
            self.setCursor(QCursor(
                Qt.CursorShape.OpenHandCursor if self._hover_marker
                else Qt.CursorShape.ArrowCursor))
            # Final sanity-clamp after the drag (in case neighbors moved)
            self.update()

    def leaveEvent(self, _e):
        if self._drag_marker is None:
            self._hover_marker = None
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))

    def _gen_bars(self, seed: int = 2026) -> list[float]:
        rng = random.Random(seed)
        out = []
        for i in range(self.BAR_COUNT):
            # Sine fundamental + noise — looks like a typical track waveform
            phase = i / self.BAR_COUNT * 2 * math.pi * 5.5
            base  = 0.55 + 0.40 * math.sin(phase)
            base += rng.uniform(-0.20, 0.20)
            # Long-form envelope — quieter at start/end, louder middle
            env = 0.4 + 0.6 * math.sin(math.pi * (i / self.BAR_COUNT))
            out.append(max(0.10, min(1.0, base * env)))
        return out

    def _zone_for_x(self, x: int, plot_left: int, plot_w: int) -> str:
        """Return the zone-id for a given x-pixel — used for bar coloring.
        Zones are defined by adjacent marker pairs."""
        if plot_w <= 0:
            return "between"
        ms_at_x = ((x - plot_left) / plot_w) * self._duration_ms
        # Zone definitions (in order of containment check):
        if ms_at_x < self._positions.get("intro", 0):
            return "before_intro"        # GREEN
        if ms_at_x < self._positions.get("hook_in", 0):
            return "intro_to_hook"       # WHITE
        if ms_at_x < self._positions.get("hook_out", 0):
            return "hook"                # PINK
        if ms_at_x < self._positions.get("outro", 0):
            return "hook_to_outro"       # WHITE
        return "after_outro"             # RED

    def _zone_color(self, zone: str) -> QColor:
        return {
            "before_intro":   QColor(GREEN),
            "intro_to_hook":  QColor(255, 255, 255, 220),
            "hook":           QColor(PINK),
            "hook_to_outro":  QColor(255, 255, 255, 220),
            "after_outro":    QColor(RED),
        }.get(zone, QColor(TEXT_MUTED))

    # ── Painting ──────────────────────────────────────────────────────────

    def paintEvent(self, _e):
        super().paintEvent(_e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        # Layout — leave 22 at top for ruler labels, 24 below ruler for flags
        margin_x = 12
        ruler_y = 4
        flag_y = self.HEADER_RULER_H
        plot_top = self.HEADER_RULER_H + self.FLAG_H
        plot_bot = self.height() - 24    # leave room for bottom labels
        plot_h = plot_bot - plot_top
        plot_left = margin_x
        plot_right = self.width() - margin_x
        plot_w = plot_right - plot_left

        # ── Time ruler at top ────────────────────────────────────────────
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(mono(8, bold=False))
        # Tick interval — pick something readable based on duration
        if self._duration_ms <= 60_000:
            tick_ms = 5_000           # 0..1 min: 5-sec ticks
        elif self._duration_ms <= 300_000:
            tick_ms = 15_000          # 1..5 min: 15-sec ticks
        else:
            tick_ms = 30_000          # >5 min:  30-sec ticks
        n_ticks = int(self._duration_ms // tick_ms) + 1
        for i in range(n_ticks):
            t_ms = i * tick_ms
            if t_ms > self._duration_ms:
                break
            x = plot_left + int(plot_w * (t_ms / self._duration_ms))
            p.drawText(QRect(x - 30, ruler_y, 60, self.HEADER_RULER_H - 4),
                       Qt.AlignmentFlag.AlignCenter,
                       _fmt_ms(t_ms))
            # Vertical hairline tick
            tick = QColor(255, 255, 255, 8)
            p.setPen(QPen(tick, 1))
            p.drawLine(x, plot_top, x, plot_bot)
            p.setPen(QColor(TEXT_MUTED))

        # Far-right end label (total duration)
        p.drawText(QRect(plot_right - 60, ruler_y, 60, self.HEADER_RULER_H - 4),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   _fmt_ms(self._duration_ms))

        # ── Bars ─────────────────────────────────────────────────────────
        bar_total_w = plot_w / self.BAR_COUNT
        bar_w = max(2.0, bar_total_w * 0.65)
        gap   = bar_total_w - bar_w
        cy = plot_top + plot_h / 2
        for i, amp in enumerate(self._bars):
            x = plot_left + int(i * bar_total_w + gap / 2)
            zone = self._zone_for_x(x, plot_left, plot_w)
            color = self._zone_color(zone)
            bh = max(4, int(amp * plot_h * 0.85))
            y = int(cy - bh / 2)
            p.setBrush(color)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(QRectF(x, y, bar_w, bh), 1, 1)

        # ── Markers ──────────────────────────────────────────────────────
        for m in MARKER_IDS:
            ms = int(self._positions.get(m, 0))
            x = plot_left + int(plot_w * (ms / self._duration_ms))
            color = QColor(MARKER_COLORS[m])

            # Vertical line through plot area
            p.setPen(QPen(color, 2))
            p.drawLine(x, flag_y + 4, x, plot_bot)

            # Flag rectangle at top with label
            label = MARKER_LABELS[m]
            fm = p.fontMetrics()
            p.setFont(inter(8, QFont.Weight.Bold, letter_spacing=0.6))
            text_w = max(40, p.fontMetrics().horizontalAdvance(label) + 12)
            flag_rect = QRectF(x - text_w / 2, flag_y - 2,
                                text_w, self.FLAG_H - 6)
            # Flag fill — tinted
            tint = QColor(color); tint.setAlphaF(0.85)
            p.setBrush(tint); p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(flag_rect, 4, 4)
            # Label text
            p.setPen(QColor("#0a0c14"))
            p.drawText(flag_rect, Qt.AlignmentFlag.AlignCenter, label)

        # ── Bottom labels — current time / total ─────────────────────────
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(mono(8, bold=False))
        # Show first non-zero marker time on left ("09.4s") and end time
        # right-side. Placeholder for now — full play position comes in 5-B.
        first_label = _fmt_ms_decimal(self._positions.get("start", 0))
        p.drawText(QRect(margin_x, plot_bot + 4, 120, 18),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   f"{_fmt_ms_decimal(self._positions.get('intro', 0))} / "
                   f"{_fmt_ms_decimal(self._duration_ms)}")


# ════════════════════════════════════════════════════════════════════════════
# Cue card — one per marker (6 total)
# ════════════════════════════════════════════════════════════════════════════

class _CueCard(QFrame):
    """Single cue card: header / time / nudge buttons / preview / reset.

    Emits semantic signals; the parent dialog connects them to the waveform
    widget. The card is presentation-only — it does NOT mutate the marker
    state directly.
    """

    nudged          = pyqtSignal(str, int)   # marker_id, delta_ms
    reset_clicked   = pyqtSignal(str)        # marker_id
    preview_clicked = pyqtSignal(str)        # marker_id

    def __init__(self, marker_id: str, parent=None):
        super().__init__(parent)
        self._marker_id = marker_id
        self._color_hex = MARKER_COLORS[marker_id]
        self._time_ms = 0
        self.setFixedSize(102, 110)
        self.setStyleSheet(
            f"QFrame {{ background: #0e1020; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; "
            f"border-radius: 6px; }}"
        )

        v = QVBoxLayout(self)
        v.setContentsMargins(8, 6, 8, 6); v.setSpacing(3)

        # Header label (uppercase, color-tinted)
        self._header = QLabel(MARKER_LABELS[marker_id])
        self._header.setFont(inter(8, QFont.Weight.Bold, letter_spacing=0.8))
        self._header.setStyleSheet(
            f"color: {self._color_hex}; background: transparent; border: none;")
        v.addWidget(self._header)

        # Time display (mono, larger)
        self._time_lbl = QLabel("00.0s")
        self._time_lbl.setFont(mono(13, bold=True))
        self._time_lbl.setStyleSheet(
            f"color: {TEXT_PRI}; background: transparent; border: none;")
        v.addWidget(self._time_lbl)

        # Nudge buttons row
        nudge_row = QHBoxLayout(); nudge_row.setSpacing(4)
        nudge_row.setContentsMargins(0, 1, 0, 1)
        self._lt_btn = self._make_nudge_button("<<", -100)
        self._rt_btn = self._make_nudge_button(">>",  100)
        nudge_row.addWidget(self._lt_btn)
        nudge_row.addWidget(self._rt_btn)
        v.addLayout(nudge_row)

        # PREVIEW button (color-tinted, full width)
        self._preview_btn = QPushButton("▶ PREVIEW")
        self._preview_btn.setFixedHeight(22)
        self._preview_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._preview_btn.setFont(inter(8, QFont.Weight.Bold, letter_spacing=0.6))
        self._preview_btn.setStyleSheet(self._preview_qss())
        self._preview_btn.clicked.connect(
            lambda: self._on_preview())
        v.addWidget(self._preview_btn)

        # Reset button (subtle)
        self._reset_btn = QPushButton("↻ Reset")
        self._reset_btn.setFixedHeight(20)
        self._reset_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._reset_btn.setFont(inter(8, QFont.Weight.Medium))
        self._reset_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; "
            f"color: {TEXT_MUTED}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; "
            f"border-radius: 4px; }}"
            f"QPushButton:hover {{ color: {TEXT_PRI}; "
            f"border-color: {rgba('#ffffff', 0.15)}; }}"
        )
        self._reset_btn.clicked.connect(
            lambda: self.reset_clicked.emit(self._marker_id))
        v.addWidget(self._reset_btn)

    def _preview_qss(self) -> str:
        return (
            f"QPushButton {{ background: {rgba(self._color_hex, 0.18)}; "
            f"color: {self._color_hex}; "
            f"border: 1px solid {rgba(self._color_hex, 0.40)}; "
            f"border-radius: 4px; padding: 0 6px; }}"
            f"QPushButton:hover {{ background: {rgba(self._color_hex, 0.28)}; }}"
        )

    def _make_nudge_button(self, label: str, delta_ms: int) -> QPushButton:
        b = QPushButton(label)
        b.setFixedHeight(22)
        b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        b.setFont(inter(10, QFont.Weight.Bold))
        b.setStyleSheet(
            f"QPushButton {{ background: {rgba('#ffffff', 0.04)}; "
            f"color: {TEXT_SEC}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; "
            f"border-radius: 4px; }}"
            f"QPushButton:hover {{ background: {rgba(self._color_hex, 0.18)}; "
            f"color: {self._color_hex}; "
            f"border-color: {rgba(self._color_hex, 0.40)}; }}"
            f"QPushButton:pressed {{ background: {rgba(self._color_hex, 0.28)}; }}"
            f"QPushButton:disabled {{ color: {TEXT_DIM}; "
            f"background: rgba(255,255,255,0.02); }}"
        )
        # Hold-to-repeat — Qt fires click() at intervals while button held
        b.setAutoRepeat(True)
        b.setAutoRepeatDelay(500)
        b.setAutoRepeatInterval(100)
        b.clicked.connect(
            lambda _checked=False, d=delta_ms:
            self.nudged.emit(self._marker_id, d))
        return b

    # ── Public API ────────────────────────────────────────────────────────

    def set_time_ms(self, ms: int):
        self._time_ms = int(ms or 0)
        self._time_lbl.setText(_fmt_ms_decimal(self._time_ms))

    def flash_preview(self):
        """Briefly tint the PREVIEW button green to confirm the click —
        replaces real audio playback (per Q3 stub decision)."""
        from PyQt6.QtCore import QTimer
        self._preview_btn.setStyleSheet(
            f"QPushButton {{ background: {rgba(GREEN, 0.40)}; "
            f"color: {GREEN_LIGHT}; "
            f"border: 1px solid {rgba(GREEN, 0.60)}; "
            f"border-radius: 4px; padding: 0 6px; }}"
        )
        def _restore():
            try:
                self._preview_btn.setStyleSheet(self._preview_qss())
            except Exception:
                pass
        QTimer.singleShot(500, _restore)

    def _on_preview(self):
        self.flash_preview()
        self.preview_clicked.emit(self._marker_id)


# ════════════════════════════════════════════════════════════════════════════
# Vertical fade slider — Fade In (left) and Fade Out (right)
# ════════════════════════════════════════════════════════════════════════════

class _VerticalFadeSlider(QFrame):
    """Vertical 0..2000ms slider with header label + value display.

    Implementation note: uses native QSlider (vertical) with custom QSS so
    the thumb + track match the Figma marker style. Wheel scrolls in 50ms
    steps.
    """

    value_changed = pyqtSignal(int)   # ms

    def __init__(self, label: str, accent: str, parent=None):
        super().__init__(parent)
        self._label_text = label
        self._accent = accent
        self.setFixedSize(50, 220)
        self.setStyleSheet("background: transparent;")

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 4, 0, 4); v.setSpacing(4)

        # Header
        hdr = QLabel(label)
        hdr.setFont(inter(8, QFont.Weight.Bold, letter_spacing=0.8))
        hdr.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        hdr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(hdr)

        # Slider
        from PyQt6.QtWidgets import QSlider
        self._slider = QSlider(Qt.Orientation.Vertical)
        self._slider.setRange(0, 2000)
        self._slider.setValue(0)
        self._slider.setSingleStep(50)
        self._slider.setPageStep(200)
        self._slider.setInvertedAppearance(True)   # 0 at bottom, 2000 at top
        self._slider.setStyleSheet(self._slider_qss())
        self._slider.valueChanged.connect(self._on_changed)
        v.addWidget(self._slider, alignment=Qt.AlignmentFlag.AlignHCenter)

        # Value display
        self._value_lbl = QLabel("0ms")
        self._value_lbl.setFont(mono(9, bold=True))
        self._value_lbl.setStyleSheet(
            f"color: {self._accent}; background: transparent;")
        self._value_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(self._value_lbl)

    def _slider_qss(self) -> str:
        return (
            f"QSlider::groove:vertical {{ background: {rgba('#ffffff', 0.06)}; "
            f"width: 4px; border-radius: 2px; }}"
            f"QSlider::handle:vertical {{ background: {self._accent}; "
            f"height: 12px; margin: 0 -8px; border-radius: 4px; "
            f"border: 1px solid {rgba('#ffffff', 0.20)}; }}"
            f"QSlider::handle:vertical:hover {{ background: {self._accent}; "
            f"border: 1px solid #ffffff; }}"
            f"QSlider::sub-page:vertical {{ background: {rgba('#ffffff', 0.06)}; "
            f"border-radius: 2px; }}"
            f"QSlider::add-page:vertical {{ background: {rgba(self._accent, 0.40)}; "
            f"border-radius: 2px; }}"
        )

    def _on_changed(self, v: int):
        # Snap to 50ms
        snapped = int(round(v / 50.0) * 50)
        if snapped != v:
            self._slider.blockSignals(True)
            self._slider.setValue(snapped)
            self._slider.blockSignals(False)
        # Update display
        if snapped == 0 and "Out" in self._label_text:
            self._value_lbl.setText("OFF")
        else:
            self._value_lbl.setText(f"{snapped}ms")
        self.value_changed.emit(snapped)

    def value(self) -> int:
        return int(self._slider.value())

    def set_value(self, ms: int):
        self._slider.setValue(max(0, min(2000, int(ms or 0))))


# ════════════════════════════════════════════════════════════════════════════
# Main dialog
# ════════════════════════════════════════════════════════════════════════════

class AudioCueEditorDialog(BaseDialog):

    cues_saved = pyqtSignal(int)   # song_id

    HEADER_H = 64
    FOOTER_H = 60

    def __init__(self, db, song_id: int, parent=None):
        self._db = db
        self._song_id = int(song_id)
        # Load song + cue data
        try:
            self._db._ensure_song_cue_columns()
            self._cue_data = self._db.get_song_cue_data(self._song_id)
        except Exception as exc:
            log.error(f"get_song_cue_data({self._song_id}) failed: {exc}")
            self._cue_data = {}

        # Refs
        self._waveform: Optional[_CueWaveformWidget] = None
        self._song_card: Optional[_SongInfoCard] = None
        self._path_input: Optional[QLineEdit] = None
        self._save_btn: Optional[QPushButton] = None
        self._cue_cards: dict[str, _CueCard] = {}
        self._fade_in_slider: Optional[_VerticalFadeSlider] = None
        self._fade_out_slider: Optional[_VerticalFadeSlider] = None
        self._footer_msg_lbl: Optional[QLabel] = None
        self._footer_msg_default = (
            "Tip: Use << >> buttons to adjust by 0.1 second increments")

        super().__init__(target_size=(920, 680), parent=parent)
        self._populate_from_db()

    # ── Header ────────────────────────────────────────────────────────────

    def _build_header(self) -> QWidget:
        f = QFrame()
        f.setStyleSheet(
            f"QFrame {{ background: #0d0f1e; "
            f"border-bottom: 1px solid {rgba('#ffffff', 0.06)}; }}"
        )
        h = QHBoxLayout(f)
        h.setContentsMargins(16, 12, 12, 12); h.setSpacing(14)

        h.addWidget(_WaveformIcon())

        title_box = QWidget(); title_box.setStyleSheet("background: transparent;")
        tv = QVBoxLayout(title_box)
        tv.setContentsMargins(0, 0, 0, 0); tv.setSpacing(2)
        title = QLabel("AUDIO CUE EDITOR")
        title.setFont(inter(15, QFont.Weight.Black, letter_spacing=0.5))
        title.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        sub = QLabel("Set mix points, hooks, fade settings and audio levels")
        sub.setFont(inter(10))
        sub.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        tv.addWidget(title); tv.addWidget(sub)
        h.addWidget(title_box)
        h.addStretch()

        # Song info card on the right
        self._song_card = _SongInfoCard()
        h.addWidget(self._song_card)

        # Close
        x = QPushButton("✕")
        x.setFixedSize(28, 28)
        x.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        x.setFont(inter(13, QFont.Weight.Bold))
        x.setStyleSheet(
            f"QPushButton {{ background: #1c1f38; color: {TEXT_SEC}; "
            f"border: none; border-radius: 6px; }}"
            f"QPushButton:hover {{ background: {rgba(RED, 0.20)}; "
            f"color: {RED_LIGHT}; }}"
        )
        x.clicked.connect(self.reject)
        h.addWidget(x)
        return f

    # ── Content ───────────────────────────────────────────────────────────

    def _build_content(self) -> QWidget:
        c = QFrame(); c.setStyleSheet("background: transparent;")
        v = QVBoxLayout(c)
        v.setContentsMargins(14, 12, 14, 12); v.setSpacing(10)

        # ── File path bar ────────────────────────────────────────────────
        path_row = QHBoxLayout(); path_row.setContentsMargins(0, 0, 0, 0)
        path_row.setSpacing(8)
        self._path_input = QLineEdit()
        self._path_input.setPlaceholderText(
            "C:\\path\\to\\audio_file.wav")
        self._path_input.setFixedHeight(32)
        self._path_input.setFont(inter(10))
        self._path_input.setReadOnly(True)
        self._path_input.setStyleSheet(
            f"QLineEdit {{ background: #0e1020; color: {TEXT_PRI}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; border-radius: 5px; "
            f"padding: 0 10px; "
            f"selection-background-color: {rgba(CYAN, 0.25)}; }}"
        )
        path_row.addWidget(self._path_input, stretch=1)

        browse_btn = QPushButton("...")
        browse_btn.setFixedSize(36, 32)
        browse_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        browse_btn.setFont(inter(12, QFont.Weight.Bold))
        browse_btn.setStyleSheet(
            f"QPushButton {{ background: {rgba('#ffffff', 0.06)}; "
            f"color: {TEXT_SEC}; border: 1px solid {rgba('#ffffff', 0.06)}; "
            f"border-radius: 5px; }}"
            f"QPushButton:hover {{ background: {rgba(CYAN, 0.18)}; "
            f"color: {CYAN_LIGHT}; }}"
        )
        browse_btn.clicked.connect(self._on_browse_path)
        path_row.addWidget(browse_btn)

        edit_btn = QPushButton("Edit")
        edit_btn.setFixedSize(64, 32)
        edit_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        edit_btn.setFont(inter(11, QFont.Weight.DemiBold))
        edit_btn.setStyleSheet(
            f"QPushButton {{ background: #1c1f38; color: {TEXT_SEC}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; border-radius: 5px; }}"
            f"QPushButton:hover {{ background: #252848; color: {TEXT_PRI}; }}"
        )
        edit_btn.clicked.connect(self._on_edit_path)
        path_row.addWidget(edit_btn)
        v.addLayout(path_row)

        # ── Waveform ─────────────────────────────────────────────────────
        self._waveform = _CueWaveformWidget()
        self._waveform.marker_changed.connect(self._on_marker_changed)
        v.addWidget(self._waveform)

        # ── Controls row — Play/Stop / Fade In / 6 cue cards / Fade Out ─
        v.addLayout(self._build_controls_row())

        ph_options = self._make_placeholder(
            "▼  Options bar (Variable Length / AutoCue / Volume / Normalize / 32-bit) "
            "coming in Phase 5-C",
            color=TEXT_DIM, height=40)
        v.addWidget(ph_options)

        ph_meta = self._make_placeholder(
            "▼  PUBLIC ANNOUNCEMENT METADATA section coming in Phase 5-C",
            color=TEXT_DIM, height=60)
        v.addWidget(ph_meta)

        ph_ai = self._make_placeholder(
            "✦  AI auto-fill banner coming in Phase 5-C",
            color=TEXT_DIM, height=40)
        v.addWidget(ph_ai)

        v.addStretch()
        return c

    def _make_placeholder(self, text: str, color: str, height: int) -> QFrame:
        """Visual placeholder for sections to be filled in 5-C."""
        f = QFrame()
        f.setFixedHeight(height)
        f.setStyleSheet(
            f"QFrame {{ background: rgba(255,255,255,0.02); "
            f"border: 1px dashed {rgba('#ffffff', 0.10)}; "
            f"border-radius: 5px; }}"
        )
        l = QLabel(text, f)
        l.setGeometry(0, 0, 9999, height)
        l.setFont(inter(10))
        l.setStyleSheet(
            f"QLabel {{ color: {color}; background: transparent; "
            f"border: none; }}"
        )
        l.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return f

    def _build_controls_row(self) -> QHBoxLayout:
        """Phase 5-B: Play/Stop column + Fade In + 6 cue cards + Fade Out."""
        row = QHBoxLayout()
        row.setContentsMargins(0, 4, 0, 4); row.setSpacing(8)

        # Play / Stop column (visual stub per Q3 — no audio in Phase 5)
        ps = QVBoxLayout(); ps.setSpacing(6); ps.setContentsMargins(0, 0, 0, 0)
        play_btn = self._make_transport_button("▶", GREEN, "Play")
        play_btn.clicked.connect(
            lambda: log.info("[cue-editor] play (stub — wired in audio phase)"))
        ps.addWidget(play_btn)
        stop_btn = self._make_transport_button("■", RED, "Stop")
        stop_btn.clicked.connect(
            lambda: log.info("[cue-editor] stop (stub)"))
        ps.addWidget(stop_btn)
        ps_w = QWidget(); ps_w.setStyleSheet("background: transparent;")
        ps_w.setFixedWidth(56); ps_w.setLayout(ps)
        row.addWidget(ps_w)

        # Fade In (left)
        self._fade_in_slider = _VerticalFadeSlider("Fade In", PINK)
        self._fade_in_slider.value_changed.connect(self._validate)
        row.addWidget(self._fade_in_slider)

        # 6 cue cards
        for m in MARKER_IDS:
            card = _CueCard(m)
            card.nudged.connect(self._on_card_nudge)
            card.reset_clicked.connect(self._on_card_reset)
            card.preview_clicked.connect(self._on_card_preview)
            self._cue_cards[m] = card
            row.addWidget(card)

        # Fade Out (right)
        self._fade_out_slider = _VerticalFadeSlider("Fade Out", AMBER)
        self._fade_out_slider.value_changed.connect(self._validate)
        row.addWidget(self._fade_out_slider)

        row.addStretch()
        return row

    def _make_transport_button(self, glyph: str, color: str,
                                tooltip: str) -> QPushButton:
        b = QPushButton(glyph)
        b.setFixedSize(56, 50)
        b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        b.setFont(inter(18, QFont.Weight.Bold))
        b.setToolTip(tooltip)
        b.setStyleSheet(
            f"QPushButton {{ background: {rgba(color, 0.18)}; "
            f"color: {color}; "
            f"border: 1px solid {rgba(color, 0.40)}; "
            f"border-radius: 6px; }}"
            f"QPushButton:hover {{ background: {rgba(color, 0.30)}; }}"
        )
        return b

    # ── Cue card → waveform plumbing ─────────────────────────────────────

    def _on_marker_changed(self, marker_id: str, ms: int):
        """Waveform reports a marker moved — update the matching card display."""
        card = self._cue_cards.get(marker_id)
        if card:
            card.set_time_ms(ms)
        # When one marker moves, neighboring markers may have been shifted by
        # the clamping logic — refresh ALL cards so the UI stays consistent.
        if self._waveform:
            for m, p in self._waveform.get_positions().items():
                c = self._cue_cards.get(m)
                if c:
                    c.set_time_ms(p)
        self._validate()

    def _on_card_nudge(self, marker_id: str, delta_ms: int):
        if self._waveform:
            self._waveform.nudge_marker(marker_id, delta_ms)
        # _on_marker_changed will refresh + validate

    def _on_card_reset(self, marker_id: str):
        if self._waveform:
            self._waveform.reset_marker(marker_id)

    def _on_card_preview(self, marker_id: str):
        # Stub per Q3 — log + button already flashed green inside the card
        ms = self._waveform.get_positions().get(marker_id, 0) if self._waveform else 0
        log.info(f"[cue-editor] preview {marker_id} at {ms}ms "
                 f"(audio wiring deferred to follow-up phase)")

    # ── Validation ────────────────────────────────────────────────────────

    def _validate(self) -> bool:
        """Check the 6 ordering rules. Updates Save button + footer text.
        Returns True if state is valid.

        Rules (first failure wins):
          1. START ≤ INTRO
          2. INTRO ≤ HOOK IN
          3. HOOK OUT - HOOK IN ≥ 100ms (hook duration)
          4. HOOK OUT ≤ OUTRO
          5. OUTRO ≤ MIX
          6. MIX ≤ duration
        """
        if not self._waveform:
            return True
        p = self._waveform.get_positions()
        duration = self._waveform._duration_ms

        error: Optional[str] = None
        if p["start"] > p["intro"]:
            error = "START must be at or before INTRO"
        elif p["intro"] > p["hook_in"]:
            error = "INTRO must be at or before HOOK IN"
        elif (p["hook_out"] - p["hook_in"]) < 100:
            error = "Hook duration must be at least 0.1 seconds"
        elif p["hook_out"] > p["outro"]:
            error = "HOOK OUT must be at or before OUTRO"
        elif p["outro"] > p["mix"]:
            error = "OUTRO must be at or before MIX"
        elif p["mix"] > duration:
            error = "MIX must be at or before the end of the audio"

        if error:
            if self._footer_msg_lbl:
                self._footer_msg_lbl.setText("⚠  " + error)
                self._footer_msg_lbl.setStyleSheet(
                    f"color: {RED_LIGHT}; background: transparent;")
            if self._save_btn:
                self._save_btn.setEnabled(False)
            return False

        if self._footer_msg_lbl:
            self._footer_msg_lbl.setText(self._footer_msg_default)
            self._footer_msg_lbl.setStyleSheet(
                f"color: {TEXT_DIM}; background: transparent;")
        if self._save_btn:
            self._save_btn.setEnabled(True)
        return True

    # ── Footer ────────────────────────────────────────────────────────────

    def _build_footer(self) -> QWidget:
        f = QFrame()
        f.setStyleSheet(
            f"QFrame {{ background: #0d0f1e; "
            f"border-top: 1px solid {rgba('#ffffff', 0.06)}; }}"
        )
        h = QHBoxLayout(f)
        h.setContentsMargins(20, 12, 16, 12); h.setSpacing(8)

        # Footer message — defaults to tip text, swaps to red error when
        # validation fails (Phase 5-B).
        self._footer_msg_lbl = QLabel(self._footer_msg_default)
        self._footer_msg_lbl.setFont(inter(9))
        self._footer_msg_lbl.setStyleSheet(
            f"color: {TEXT_DIM}; background: transparent;")
        h.addWidget(self._footer_msg_lbl)
        h.addStretch()

        info_btn = QPushButton("← Song Info")
        info_btn.setFixedHeight(34); info_btn.setMinimumWidth(120)
        info_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        info_btn.setFont(inter(11, QFont.Weight.Medium))
        info_btn.setStyleSheet(
            f"QPushButton {{ background: #1c1f38; color: {TEXT_SEC}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; "
            f"border-radius: 7px; padding: 0 18px; }}"
            f"QPushButton:hover {{ background: #252848; color: {TEXT_PRI}; }}"
        )
        info_btn.clicked.connect(self.reject)
        h.addWidget(info_btn)

        cancel = QPushButton("Cancel")
        cancel.setFixedHeight(34); cancel.setMinimumWidth(96)
        cancel.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        cancel.setFont(inter(11, QFont.Weight.Medium))
        cancel.setStyleSheet(
            f"QPushButton {{ background: #1c1f38; color: {TEXT_SEC}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; "
            f"border-radius: 7px; padding: 0 18px; }}"
            f"QPushButton:hover {{ background: #252848; color: {TEXT_PRI}; }}"
        )
        cancel.clicked.connect(self.reject)
        h.addWidget(cancel)

        save = QPushButton("✓  Save")
        save.setFixedHeight(34); save.setMinimumWidth(108)
        save.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        save.setFont(inter(11, QFont.Weight.DemiBold))
        save.setStyleSheet(
            f"QPushButton {{ background: qlineargradient("
            f"x1:0,y1:0,x2:0,y2:1, stop:0 {PURPLE_LIGHT}, "
            f"stop:0.5 {PURPLE}, stop:1 #7c3aed); "
            f"color: white; border: none; border-radius: 7px; "
            f"padding: 0 22px; }}"
            f"QPushButton:hover {{ background: qlineargradient("
            f"x1:0,y1:0,x2:0,y2:1, stop:0 #c4b5fd, stop:1 {PURPLE}); }}"
            f"QPushButton:disabled {{ background: #252848; "
            f"color: {TEXT_MUTED}; }}"
        )
        save.clicked.connect(self._on_save)
        # Enabled when validation passes (Phase 5-B). Initial state is
        # confirmed valid by _validate() at end of __init__.
        save.setEnabled(True)
        h.addWidget(save)
        self._save_btn = save
        return f

    # ── Data hookup ───────────────────────────────────────────────────────

    def _populate_from_db(self):
        """Load the song's path, duration, marker positions into the widgets."""
        d = self._cue_data or {}

        # File path bar
        if self._path_input:
            self._path_input.setText(d.get("file_path") or "")

        # Header card
        if self._song_card:
            self._song_card.set_song(
                d.get("title") or "—",
                d.get("artist") or "",
                int(d.get("duration_ms") or 0),
            )

        # Waveform — duration + marker positions
        if self._waveform:
            duration = int(d.get("duration_ms") or 0)
            if duration <= 0:
                # Fallback per Phase 5-A guardrail D
                duration = 180_000
                log.warning(
                    f"[cue-editor] song id={self._song_id} has no duration_ms — "
                    f"falling back to 180000 (3 min)"
                )
            self._waveform.set_duration_ms(duration)

            # Initial positions: load from DB if any non-zero, else default
            saved = {m: int(d.get(MARKER_DB_FIELD[m]) or 0) for m in MARKER_IDS}
            any_saved = any(v > 0 for v in saved.values())
            if any_saved:
                # Mix point defaults to duration if unset
                if saved.get("mix", 0) == 0:
                    saved["mix"] = duration
                self._waveform.set_positions(saved)
            else:
                # Defaults derived from duration fractions are already set in
                # _CueWaveformWidget.__init__ — but they used the previous
                # duration value (180000). Re-apply now that real duration is
                # known.
                fresh = {
                    m: int(duration * DEFAULT_POSITIONS[m])
                    for m in MARKER_IDS
                }
                self._waveform.set_positions(fresh)

            # Populate cue cards with current positions
            for m, p in self._waveform.get_positions().items():
                card = self._cue_cards.get(m)
                if card:
                    card.set_time_ms(p)

        # Fade In/Out values from DB
        if self._fade_in_slider:
            self._fade_in_slider.set_value(int(d.get("fade_in_ms") or 0))
        if self._fade_out_slider:
            self._fade_out_slider.set_value(int(d.get("fade_out_ms") or 0))

        # Initial validation (defaults are valid; this primes the footer)
        self._validate()

    # ── Handlers ──────────────────────────────────────────────────────────

    def _on_browse_path(self):
        log.info("[cue-editor] browse — Phase 5-A: not yet wired")

    def _on_edit_path(self):
        # Toggle read-only on the path input — letting user retype
        if self._path_input:
            self._path_input.setReadOnly(not self._path_input.isReadOnly())
            log.info(
                f"[cue-editor] path edit "
                f"{'unlocked' if not self._path_input.isReadOnly() else 'locked'}")

    def _on_save(self):
        """Phase 5-A: Save is disabled. 5-B will collect waveform positions
        + slider values + option toggles and write via save_song_cue_points."""
        log.info("[cue-editor] save clicked (Phase 5-A — wiring in 5-B)")
        # Placeholder: emit signal so the integration code is exercised
        self.cues_saved.emit(self._song_id)
        self.accept()
