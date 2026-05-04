"""
RadioAI Studio Pro — Audio Cue Editor Dialog
Pixel-accurate match of Figma node 30:2 (920×680).

Custom waveform widget with 5 priority-coloured zones + 6 cue markers:
  START (green) → INTRO (cyan) → HOOK IN (pink) → HOOK OUT (pink) →
  OUTRO (orange) → MIX (red).

Phase 5 build status:
  [✓] 5-A — skeleton + waveform widget + 6 stationary markers
  [✓] 5-B — marker drag interaction + cue cards + fade sliders + validation
  [✓] 5-C — options bar + metadata + AI banner + DB save flow

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

from PyQt6.QtCore import Qt, QRect, QRectF, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QPainterPath, QFont, QCursor, QLinearGradient,
    QBrush,
)
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QLineEdit, QHBoxLayout, QVBoxLayout,
    QMessageBox, QSizePolicy, QSlider, QComboBox, QGraphicsOpacityEffect,
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
        self.setMinimumHeight(180)
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

        # Playhead overlay (Phase B1) — None = hidden, int = ms position
        self._playhead_ms: Optional[int] = None

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

    def set_playhead_ms(self, ms: int) -> None:
        """Show/move the playback position indicator (Phase B1).

        Repaints only the dirty rect spanning old + new positions, per
        the file-header performance invariants — at 100ms emit cadence
        this becomes ~5 px-wide repaints, not full-widget."""
        new_ms = max(0, min(self._duration_ms, int(ms)))
        old_ms = self._playhead_ms
        if old_ms == new_ms:
            return
        self._playhead_ms = new_ms
        # Compute dirty rect (with margin for the line stroke)
        old_x = self._ms_to_x(old_ms) if old_ms is not None else None
        new_x = self._ms_to_x(new_ms)
        if old_x is None:
            self.update(QRect(new_x - 4, 0, 8, self.height()))
        else:
            lo_x = min(old_x, new_x) - 4
            hi_x = max(old_x, new_x) + 4
            self.update(QRect(lo_x, 0, hi_x - lo_x, self.height()))

    def clear_playhead(self) -> None:
        """Hide the playback position indicator."""
        if self._playhead_ms is None:
            return
        old_x = self._ms_to_x(self._playhead_ms)
        self._playhead_ms = None
        self.update(QRect(old_x - 4, 0, 8, self.height()))

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

        # ── Playhead (Phase B1 — drawn on top so it's visible over markers)
        if self._playhead_ms is not None:
            ph_x = plot_left + int(plot_w * (self._playhead_ms / self._duration_ms))
            ph_color = QColor("#ffffff")
            p.setPen(QPen(ph_color, 2))
            p.drawLine(ph_x, plot_top, ph_x, plot_bot)
            # Small bright dot at top + bottom for emphasis
            p.setBrush(ph_color); p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QRectF(ph_x - 3, plot_top - 1, 6, 6))

        # ── Bottom labels — current time / total ─────────────────────────
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(mono(8, bold=False))
        # Show current playhead time on left if active, else first marker
        left_label_ms = self._playhead_ms if self._playhead_ms is not None \
            else self._positions.get('intro', 0)
        p.drawText(QRect(margin_x, plot_bot + 4, 120, 18),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   f"{_fmt_ms_decimal(left_label_ms)} / "
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
        self.setFixedSize(50, 180)
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
# Options bar — Variable Length / Reset / AutoCue / Volume / Normalize / 32-bit
# ════════════════════════════════════════════════════════════════════════════

def _toggle_button_qss(accent: str) -> str:
    """QSS for a checkable pill-style toggle. Off = muted, on = accent-tinted."""
    return (
        f"QPushButton {{ background: {rgba('#ffffff', 0.04)}; "
        f"color: {TEXT_SEC}; "
        f"border: 1px solid {rgba('#ffffff', 0.06)}; "
        f"border-radius: 5px; padding: 0 10px; }}"
        f"QPushButton:hover {{ background: {rgba(accent, 0.14)}; "
        f"color: {accent}; "
        f"border-color: {rgba(accent, 0.30)}; }}"
        f"QPushButton:checked {{ background: {rgba(accent, 0.22)}; "
        f"color: {accent}; "
        f"border: 1px solid {rgba(accent, 0.55)}; }}"
        f"QPushButton:checked:hover {{ background: {rgba(accent, 0.30)}; }}"
    )


class _OptionsBar(QFrame):
    """Variable Length / Reset / AutoCue / Volume slider / Normalize / 32-bit.

    Holds toggle state; emits `changed` whenever any control flips so the
    parent dialog can re-validate / mark dirty. `reset_clicked` is the
    sidebar Reset button (orange) — resets the option toggles + volume only,
    not the cue points.
    """

    changed       = pyqtSignal()
    reset_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(40)
        self.setStyleSheet(
            f"QFrame {{ background: {rgba('#ffffff', 0.02)}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; "
            f"border-radius: 6px; }}"
        )

        h = QHBoxLayout(self)
        h.setContentsMargins(10, 4, 10, 4); h.setSpacing(10)

        # Variable Length toggle
        self._var_btn = self._make_toggle("Variable Length", RED, "✕")
        h.addWidget(self._var_btn)

        # Reset button (orange)
        reset = QPushButton("↻  Reset")
        reset.setFixedHeight(30)
        reset.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        reset.setFont(inter(9, QFont.Weight.DemiBold, letter_spacing=0.4))
        reset.setStyleSheet(
            f"QPushButton {{ background: {rgba(AMBER, 0.16)}; "
            f"color: {AMBER_LIGHT}; "
            f"border: 1px solid {rgba(AMBER, 0.40)}; "
            f"border-radius: 5px; padding: 0 12px; }}"
            f"QPushButton:hover {{ background: {rgba(AMBER, 0.26)}; }}"
        )
        reset.clicked.connect(self.reset_clicked.emit)
        h.addWidget(reset)

        # AutoCue toggle (amber)
        self._autocue_btn = self._make_toggle("AutoCue", AMBER, "●")
        h.addWidget(self._autocue_btn)

        # Volume label + slider + percentage display
        vol_lbl = QLabel("Volume:")
        vol_lbl.setFont(inter(9, QFont.Weight.DemiBold, letter_spacing=0.4))
        vol_lbl.setStyleSheet(f"color: {TEXT_SEC}; background: transparent;")
        h.addWidget(vol_lbl)

        self._vol_slider = QSlider(Qt.Orientation.Horizontal)
        self._vol_slider.setRange(0, 100)
        self._vol_slider.setValue(100)
        self._vol_slider.setFixedWidth(140)
        self._vol_slider.setStyleSheet(self._vol_slider_qss())
        self._vol_slider.valueChanged.connect(self._on_vol_changed)
        h.addWidget(self._vol_slider)

        self._vol_lbl = QLabel("100%")
        self._vol_lbl.setFont(mono(10, bold=True))
        self._vol_lbl.setStyleSheet(
            f"color: {AMBER_LIGHT}; background: transparent;")
        self._vol_lbl.setFixedWidth(42)
        h.addWidget(self._vol_lbl)

        # Normalize toggle (cyan)
        self._norm_btn = self._make_toggle("Normalize", CYAN, "≈")
        h.addWidget(self._norm_btn)

        # 32-bit toggle (cyan)
        self._bit32_btn = self._make_toggle("32-bit", CYAN, "✓")
        h.addWidget(self._bit32_btn)

        h.addStretch()

    def _vol_slider_qss(self) -> str:
        return (
            f"QSlider::groove:horizontal {{ background: {rgba('#ffffff', 0.06)}; "
            f"height: 4px; border-radius: 2px; }}"
            f"QSlider::handle:horizontal {{ background: {AMBER}; "
            f"width: 12px; margin: -5px 0; border-radius: 4px; "
            f"border: 1px solid {rgba('#ffffff', 0.25)}; }}"
            f"QSlider::handle:horizontal:hover {{ border: 1px solid #ffffff; }}"
            f"QSlider::sub-page:horizontal {{ background: {rgba(AMBER, 0.55)}; "
            f"border-radius: 2px; }}"
            f"QSlider::add-page:horizontal {{ background: {rgba('#ffffff', 0.06)}; "
            f"border-radius: 2px; }}"
        )

    def _make_toggle(self, label: str, accent: str, glyph: str) -> QPushButton:
        b = QPushButton(f"{glyph}  {label}")
        b.setCheckable(True)
        b.setChecked(False)
        b.setFixedHeight(30)
        b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        b.setFont(inter(9, QFont.Weight.DemiBold, letter_spacing=0.4))
        b.setStyleSheet(_toggle_button_qss(accent))
        b.toggled.connect(lambda _on: self.changed.emit())
        return b

    def _on_vol_changed(self, v: int):
        self._vol_lbl.setText(f"{int(v)}%")
        self.changed.emit()

    # ── Public API ────────────────────────────────────────────────────────

    def set_state(self, *, variable_length: int, auto_cue: int,
                  normalize: int, bit_depth_32: int, volume: int):
        # Block signals so loading doesn't fire `changed` six times
        for w in (self._var_btn, self._autocue_btn,
                  self._norm_btn, self._bit32_btn, self._vol_slider):
            w.blockSignals(True)
        self._var_btn.setChecked(bool(variable_length))
        self._autocue_btn.setChecked(bool(auto_cue))
        self._norm_btn.setChecked(bool(normalize))
        self._bit32_btn.setChecked(bool(bit_depth_32))
        v = int(volume) if volume is not None else 100
        self._vol_slider.setValue(max(0, min(100, v)))
        self._vol_lbl.setText(f"{int(self._vol_slider.value())}%")
        for w in (self._var_btn, self._autocue_btn,
                  self._norm_btn, self._bit32_btn, self._vol_slider):
            w.blockSignals(False)

    def get_state(self) -> dict:
        return {
            "variable_length": int(self._var_btn.isChecked()),
            "auto_cue":        int(self._autocue_btn.isChecked()),
            "normalize":       int(self._norm_btn.isChecked()),
            "bit_depth_32":    int(self._bit32_btn.isChecked()),
            "volume_level":    int(self._vol_slider.value()),
        }

    def reset_to_defaults(self):
        """Reset toggles + volume — does NOT touch cue points."""
        self.set_state(
            variable_length=0, auto_cue=0,
            normalize=0, bit_depth_32=0, volume=100,
        )
        self.changed.emit()


# ════════════════════════════════════════════════════════════════════════════
# Public Announcement Metadata
# ════════════════════════════════════════════════════════════════════════════

class _MetadataSection(QFrame):
    """Cyan-accented section: header + Update on Play dropdown + 2 inputs.

    Stores its own state internally; the dialog reads via `get_state` on
    save, and writes via `set_state` on load.
    """

    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(74)
        self.setStyleSheet(
            f"QFrame {{ background: {rgba('#ffffff', 0.02)}; "
            f"border: 1px solid {rgba(CYAN, 0.20)}; "
            f"border-left: 3px solid {CYAN}; "
            f"border-radius: 6px; }}"
        )

        v = QVBoxLayout(self)
        v.setContentsMargins(12, 6, 12, 6); v.setSpacing(4)

        # ── Header row ───────────────────────────────────────────────────
        hdr_row = QHBoxLayout(); hdr_row.setSpacing(8); hdr_row.setContentsMargins(0, 0, 0, 0)

        title = QLabel("PUBLIC ANNOUNCEMENT METADATA")
        title.setFont(inter(9, QFont.Weight.Black, letter_spacing=1.2))
        title.setStyleSheet(
            f"color: {CYAN_LIGHT}; background: transparent; border: none;")
        hdr_row.addWidget(title)
        hdr_row.addStretch()

        upd_lbl = QLabel("Update on Play:")
        upd_lbl.setFont(inter(9, QFont.Weight.Medium))
        upd_lbl.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent; border: none;")
        hdr_row.addWidget(upd_lbl)

        self._upd_combo = QComboBox()
        self._upd_combo.addItems(["Yes", "No", "On Track Change"])
        self._upd_combo.setFixedSize(150, 24)
        self._upd_combo.setFont(inter(9, QFont.Weight.DemiBold))
        self._upd_combo.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._upd_combo.setStyleSheet(self._combo_qss())
        self._upd_combo.currentIndexChanged.connect(
            lambda _i: self.changed.emit())
        hdr_row.addWidget(self._upd_combo)
        v.addLayout(hdr_row)

        # ── Field row — Title + Artist inputs ────────────────────────────
        fields_row = QHBoxLayout(); fields_row.setSpacing(10)
        fields_row.setContentsMargins(0, 0, 0, 0)

        title_box = QVBoxLayout(); title_box.setSpacing(2); title_box.setContentsMargins(0, 0, 0, 0)
        tlbl = QLabel("Title Field")
        tlbl.setFont(inter(8, QFont.Weight.Bold, letter_spacing=0.6))
        tlbl.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; border: none;")
        title_box.addWidget(tlbl)
        self._title_input = QLineEdit("AUTO")
        self._title_input.setFixedHeight(26)
        self._title_input.setFont(inter(9))
        self._title_input.setStyleSheet(self._lineedit_qss())
        self._title_input.textChanged.connect(lambda _t: self.changed.emit())
        title_box.addWidget(self._title_input)
        fields_row.addLayout(title_box, stretch=1)

        artist_box = QVBoxLayout(); artist_box.setSpacing(2); artist_box.setContentsMargins(0, 0, 0, 0)
        albl = QLabel("Artist Field")
        albl.setFont(inter(8, QFont.Weight.Bold, letter_spacing=0.6))
        albl.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; border: none;")
        artist_box.addWidget(albl)
        self._artist_input = QLineEdit("AUTO")
        self._artist_input.setFixedHeight(26)
        self._artist_input.setFont(inter(9))
        self._artist_input.setStyleSheet(self._lineedit_qss())
        self._artist_input.textChanged.connect(lambda _t: self.changed.emit())
        artist_box.addWidget(self._artist_input)
        fields_row.addLayout(artist_box, stretch=1)

        v.addLayout(fields_row)

    def _lineedit_qss(self) -> str:
        return (
            f"QLineEdit {{ background: #0e1020; color: {TEXT_PRI}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; border-radius: 4px; "
            f"padding: 0 8px; "
            f"selection-background-color: {rgba(CYAN, 0.25)}; }}"
            f"QLineEdit:focus {{ border: 1px solid {rgba(CYAN, 0.50)}; }}"
        )

    def _combo_qss(self) -> str:
        return (
            f"QComboBox {{ background: #0e1020; color: {TEXT_PRI}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; border-radius: 4px; "
            f"padding: 0 8px; }}"
            f"QComboBox:hover {{ border: 1px solid {rgba(CYAN, 0.40)}; }}"
            f"QComboBox::drop-down {{ width: 18px; border: none; }}"
            f"QComboBox::down-arrow {{ image: none; width: 0; height: 0; "
            f"border-left: 4px solid transparent; "
            f"border-right: 4px solid transparent; "
            f"border-top: 5px solid {TEXT_SEC}; "
            f"margin-right: 6px; }}"
            f"QComboBox QAbstractItemView {{ background: #0e1020; "
            f"color: {TEXT_PRI}; selection-background-color: {rgba(CYAN, 0.25)}; "
            f"border: 1px solid {rgba('#ffffff', 0.10)}; }}"
        )

    # ── Public API ────────────────────────────────────────────────────────

    def set_state(self, *, title_field_mode: str, artist_field_mode: str,
                  update_on_play: str):
        for w in (self._title_input, self._artist_input, self._upd_combo):
            w.blockSignals(True)
        self._title_input.setText(title_field_mode or "AUTO")
        self._artist_input.setText(artist_field_mode or "AUTO")
        idx = self._upd_combo.findText(update_on_play or "Yes")
        self._upd_combo.setCurrentIndex(idx if idx >= 0 else 0)
        for w in (self._title_input, self._artist_input, self._upd_combo):
            w.blockSignals(False)

    def get_state(self) -> dict:
        return {
            "title_field_mode":  (self._title_input.text() or "AUTO").strip(),
            "artist_field_mode": (self._artist_input.text() or "AUTO").strip(),
            "update_on_play":    self._upd_combo.currentText(),
        }


# ════════════════════════════════════════════════════════════════════════════
# AI auto-fill banner — purely decorative
# ════════════════════════════════════════════════════════════════════════════

class _AIBanner(QFrame):
    """Purple gradient banner with sparkle icon + tagline.

    No interactive surface; paint event renders the gradient + glyph + text.
    Sized for a 40px row.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(38)

    def paintEvent(self, _e):
        super().paintEvent(_e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0, 0, self.width(), self.height())

        path = QPainterPath(); path.addRoundedRect(rect, 6, 6)
        p.setClipPath(path)

        grad = QLinearGradient(0, 0, self.width(), 0)
        grad.setColorAt(0.0, QColor(PURPLE_DARK))
        grad.setColorAt(0.6, QColor(PURPLE))
        grad.setColorAt(1.0, QColor(PURPLE_LIGHT))
        p.fillRect(rect, QBrush(grad))

        # Soft top highlight
        hl = QColor(255, 255, 255, 18)
        p.fillRect(QRectF(0, 0, self.width(), 1), hl)

        p.setClipping(False)
        # Subtle border
        bc = QColor(PURPLE_LIGHT); bc.setAlphaF(0.35)
        p.setPen(QPen(bc, 1)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)

        # Sparkle glyph
        glyph_x = 14
        p.setPen(QColor("#ffffff"))
        p.setFont(inter(15, QFont.Weight.Bold))
        p.drawText(QRectF(glyph_x, 0, 22, self.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   "✦")

        # Main text
        text_x = 40
        text_w = self.width() - text_x - 12
        p.setPen(QColor("#ffffff"))
        p.setFont(inter(10, QFont.Weight.DemiBold, letter_spacing=0.2))
        p.drawText(QRectF(text_x, 2, text_w, 17),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   "AI will auto-detect and fill metadata from audio file tags on import")

        # Subtitle (lighter)
        sub_color = QColor("#ffffff"); sub_color.setAlphaF(0.78)
        p.setPen(sub_color)
        p.setFont(inter(8))
        p.drawText(QRectF(text_x, 19, text_w, 17),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   "Artist, Title, Album, BPM, Energy, Genre — all detected automatically")


# ════════════════════════════════════════════════════════════════════════════
# Floating success toast
# ════════════════════════════════════════════════════════════════════════════

class _Toast(QLabel):
    """Brief overlay shown after a successful save. Auto-fades after `dwell_ms`.

    Created as a child of the dialog and positioned above the footer. Uses
    QGraphicsOpacityEffect for the fade so we don't fight Qt's window
    lifecycle.
    """

    def __init__(self, message: str, parent: QWidget):
        super().__init__(message, parent)
        self.setFont(inter(10, QFont.Weight.DemiBold, letter_spacing=0.4))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(
            f"QLabel {{ background: {rgba(GREEN, 0.92)}; "
            f"color: white; "
            f"border: 1px solid {rgba(GREEN_LIGHT, 0.6)}; "
            f"border-radius: 6px; "
            f"padding: 6px 16px; }}"
        )
        self.adjustSize()
        # Center horizontally near the bottom of the parent
        pw = parent.width()
        ph = parent.height()
        self.move((pw - self.width()) // 2, ph - 110)
        self.raise_()
        self.show()

    def schedule_close(self, on_done, dwell_ms: int = 700):
        """Hold visible for `dwell_ms`, then call `on_done`."""
        QTimer.singleShot(dwell_ms, on_done)


# ════════════════════════════════════════════════════════════════════════════
# Main dialog
# ════════════════════════════════════════════════════════════════════════════

class AudioCueEditorDialog(BaseDialog):

    cues_saved = pyqtSignal(int)   # song_id

    HEADER_H = 64
    FOOTER_H = 60

    def __init__(self, db, song_id: int, parent=None, engine=None):
        self._db = db
        self._song_id = int(song_id)
        self._engine = engine    # shared AudioEngine (Phase B Option C)

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
        self._options_bar: Optional[_OptionsBar] = None
        self._metadata: Optional[_MetadataSection] = None
        self._footer_msg_lbl: Optional[QLabel] = None
        self._footer_msg_default = (
            "Tip: Use << >> buttons to adjust by 0.1 second increments")

        # Phase B1 playback state — single channel per dialog. None = no
        # channel currently allocated. The engine survives the dialog;
        # cleanup() runs only on this channel id when the dialog closes.
        self._playback_cid: Optional[int] = None
        self._preview_stop_timer: Optional[QTimer] = None
        self._play_btn: Optional[QPushButton] = None
        self._stop_btn: Optional[QPushButton] = None

        super().__init__(target_size=(920, 740), parent=parent)
        self._populate_from_db()

        # Phase B1: connect AudioEngine signals after the UI exists
        if self._engine is not None:
            self._engine.position_changed.connect(self._on_engine_position)
            self._engine.playback_ended.connect(self._on_engine_playback_ended)
            self._engine.error_occurred.connect(self._on_engine_error)

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
        v.setContentsMargins(14, 8, 14, 8); v.setSpacing(6)

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

        # ── Options bar (Phase 5-C) ──────────────────────────────────────
        self._options_bar = _OptionsBar()
        self._options_bar.changed.connect(self._validate)
        self._options_bar.reset_clicked.connect(self._on_options_reset)
        v.addWidget(self._options_bar)

        # ── Public Announcement Metadata (Phase 5-C) ─────────────────────
        self._metadata = _MetadataSection()
        self._metadata.changed.connect(self._validate)
        v.addWidget(self._metadata)

        # ── AI banner (Phase 5-C — decorative) ───────────────────────────
        v.addWidget(_AIBanner())

        v.addStretch()
        return c

    def _build_controls_row(self) -> QHBoxLayout:
        """Phase 5-B: Play/Stop column + Fade In + 6 cue cards + Fade Out."""
        row = QHBoxLayout()
        row.setContentsMargins(0, 4, 0, 4); row.setSpacing(8)

        # Play / Stop column — Phase B1 wired to AudioEngine
        ps = QVBoxLayout(); ps.setSpacing(6); ps.setContentsMargins(0, 0, 0, 0)
        self._play_btn = self._make_transport_button("▶", GREEN, "Play")
        self._play_btn.clicked.connect(self._on_play_clicked)
        ps.addWidget(self._play_btn)
        self._stop_btn = self._make_transport_button("■", RED, "Stop")
        self._stop_btn.clicked.connect(self._on_stop_clicked)
        ps.addWidget(self._stop_btn)
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
        """Phase B1: load file (lazy), seek to marker, play, auto-stop in 5s."""
        if not self._waveform:
            return
        ms = self._waveform.get_positions().get(marker_id, 0)

        if not self._ensure_playback_channel():
            log.warning(
                f"[cue-editor] preview {marker_id} skipped — no playback channel")
            return

        self._engine.seek_to_ms(self._playback_cid, ms)
        self._engine.play(self._playback_cid)
        self._start_preview_auto_stop_timer(5_000)
        log.info(f"[cue-editor] preview {marker_id} at {ms}ms (5s auto-stop)")

    # ── Phase B1 playback wiring ─────────────────────────────────────────

    def _ensure_playback_channel(self) -> bool:
        """Allocate the dialog's BASS channel on first use. Returns False
        if the file is missing or unsupported (UI surface stays usable —
        preview / play just become no-ops with a warning)."""
        if self._playback_cid is not None:
            return True
        if self._engine is None:
            return False
        path = (self._cue_data or {}).get("file_path")
        if not path or not os.path.exists(path):
            log.warning(f"[cue-editor] audio file missing: {path!r}")
            return False
        try:
            self._playback_cid = self._engine.load_file(path)
            log.info(f"[cue-editor] playback channel ready: ch {self._playback_cid}")
            return True
        except Exception as exc:
            log.warning(f"[cue-editor] load_file failed: {exc}")
            self._playback_cid = None
            return False

    def _start_preview_auto_stop_timer(self, ms: int) -> None:
        """5-second preview cap. Restarts on each PREVIEW click so a fresh
        preview gets its full window."""
        if self._preview_stop_timer is None:
            self._preview_stop_timer = QTimer(self)
            self._preview_stop_timer.setSingleShot(True)
            self._preview_stop_timer.timeout.connect(self._on_preview_timeout)
        self._preview_stop_timer.stop()
        self._preview_stop_timer.start(ms)

    def _on_preview_timeout(self) -> None:
        if self._playback_cid is not None and self._engine is not None:
            try:
                self._engine.stop(self._playback_cid)
            except Exception:
                pass

    def _on_play_clicked(self) -> None:
        """Main Play transport: play full track from current position
        (or from start marker if at 0)."""
        if not self._ensure_playback_channel():
            return
        # Cancel any active preview auto-stop — main Play wants full track
        if self._preview_stop_timer is not None:
            self._preview_stop_timer.stop()
        self._engine.play(self._playback_cid)
        log.info(f"[cue-editor] main play → ch {self._playback_cid}")

    def _on_stop_clicked(self) -> None:
        """Main Stop transport: stop the dialog's channel (BASS resets
        position to 0 per Phase A2 contract)."""
        if self._playback_cid is None or self._engine is None:
            return
        if self._preview_stop_timer is not None:
            self._preview_stop_timer.stop()
        try:
            self._engine.stop(self._playback_cid)
        except Exception as exc:
            log.debug(f"[cue-editor] stop failed: {exc}")
        log.info(f"[cue-editor] main stop → ch {self._playback_cid}")

    # ── Engine signal handlers ───────────────────────────────────────────

    def _on_engine_position(self, channel_id: int, position_ms: int) -> None:
        """Drive the waveform playhead. Filtered to OUR channel — engine
        is shared, may have other channels active."""
        if channel_id != self._playback_cid or self._waveform is None:
            return
        self._waveform.set_playhead_ms(position_ms)

    def _on_engine_playback_ended(self, channel_id: int) -> None:
        """Reset playhead when our channel reaches natural EOS."""
        if channel_id != self._playback_cid:
            return
        if self._waveform is not None:
            self._waveform.clear_playhead()
        log.info(f"[cue-editor] playback ended on ch {channel_id}")

    def _on_engine_error(self, channel_id: int, message: str) -> None:
        """Surface engine errors as a footer warning. Doesn't block the
        dialog — UI must stay usable."""
        if channel_id != self._playback_cid:
            return
        log.warning(f"[cue-editor] engine error: {message}")
        if self._footer_msg_lbl:
            self._footer_msg_lbl.setText(f"⚠  Audio: {message}")
            self._footer_msg_lbl.setStyleSheet(
                f"color: {RED_LIGHT}; background: transparent;")

    def done(self, result: int) -> None:
        """QDialog teardown — fires for accept(), reject(), and the ✕
        button. Releases the dialog's BASS channel back to the engine
        (the engine itself survives — it's a MainWindow-level singleton)."""
        try:
            if self._preview_stop_timer is not None:
                self._preview_stop_timer.stop()
            if self._playback_cid is not None and self._engine is not None:
                self._engine.cleanup(self._playback_cid)
                self._playback_cid = None
        except Exception as exc:
            log.debug(f"[cue-editor] dialog cleanup error: {exc}")
        super().done(result)

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

        # Options bar — variable_length, auto_cue, normalize, bit_depth_32, volume_level
        if self._options_bar:
            vol = d.get("volume_level")
            self._options_bar.set_state(
                variable_length=int(d.get("variable_length") or 0),
                auto_cue=int(d.get("auto_cue") or 0),
                normalize=int(d.get("normalize") or 0),
                bit_depth_32=int(d.get("bit_depth_32") or 0),
                volume=100 if vol is None or vol == 0 else int(vol),
            )

        # Metadata section — title/artist field modes + update_on_play
        if self._metadata:
            self._metadata.set_state(
                title_field_mode=str(d.get("title_field_mode") or "AUTO"),
                artist_field_mode=str(d.get("artist_field_mode") or "AUTO"),
                update_on_play=str(d.get("update_on_play") or "Yes"),
            )

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

    def _on_options_reset(self):
        """↻ Reset on the options bar — restores option toggles + volume to
        defaults. Cue points and fade values are NOT touched here (they have
        their own per-card Reset)."""
        if self._options_bar:
            self._options_bar.reset_to_defaults()
        log.info("[cue-editor] options reset (toggles + volume → defaults)")

    def _collect_save_payload(self) -> dict:
        """Gather full state into a dict keyed by canonical column names —
        the same schema `Database.save_song_cue_points` expects."""
        payload: dict = {}

        # Cue point positions
        if self._waveform:
            for marker_id, ms in self._waveform.get_positions().items():
                payload[MARKER_DB_FIELD[marker_id]] = int(ms)

        # Fade values
        if self._fade_in_slider:
            payload["fade_in_ms"] = int(self._fade_in_slider.value())
        if self._fade_out_slider:
            payload["fade_out_ms"] = int(self._fade_out_slider.value())

        # Options
        if self._options_bar:
            payload.update(self._options_bar.get_state())

        # Metadata
        if self._metadata:
            payload.update(self._metadata.get_state())

        return payload

    def _on_save(self):
        """Validate, persist, toast, emit, close.

        Validation must pass before reaching here (Save button is gated by
        _validate), but we re-check defensively.
        """
        if not self._validate():
            log.warning("[cue-editor] save blocked — validation failed")
            return

        try:
            payload = self._collect_save_payload()
            self._db.save_song_cue_points(self._song_id, payload)
            log.info(
                f"[cue-editor] saved cue data for song id={self._song_id} "
                f"({len(payload)} fields)")
        except Exception as exc:
            log.error(f"[cue-editor] save failed: {exc}")
            QMessageBox.critical(
                self, "Save failed",
                f"Could not save cue data:\n\n{exc}")
            return

        # Brief success toast, then emit + close
        toast = _Toast("✓  Cue points saved", self)
        def _finish():
            try:
                toast.deleteLater()
            except Exception:
                pass
            self.cues_saved.emit(self._song_id)
            self.accept()
        toast.schedule_close(_finish, dwell_ms=700)
