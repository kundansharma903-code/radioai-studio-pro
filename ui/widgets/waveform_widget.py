"""
WaveformWidget — animated audio waveform.

80–110 bars with sine + noise heights.
Played: gradient bars (color → light)
Unplayed: solid #252840 at 60% opacity
1.5px gap, 1px bar corner radius.
Glowing playhead: 2px white line + 8px blur shadow.
QTimer @ 30fps animates progress.
"""

import math
import random

from PyQt6.QtCore import Qt, QTimer, QRectF
from PyQt6.QtGui import (
    QPainter, QColor, QBrush, QPen, QLinearGradient,
)
from PyQt6.QtWidgets import QWidget

from ._tokens import PURPLE, PURPLE_LIGHT, TEXT_DIM


class WaveformWidget(QWidget):

    def __init__(self, n_bars: int = 95, played_color: str = PURPLE,
                 light_color: str = PURPLE_LIGHT,
                 max_height: int = 36, parent=None):
        super().__init__(parent)
        self._n = n_bars
        self._played = QColor(played_color)
        self._light  = QColor(light_color)
        self._unplayed = QColor(TEXT_DIM)
        self._unplayed.setAlphaF(0.6)
        self._max_h  = max_height
        self._progress = 0.45  # 0..1
        self._heights = self._gen_heights()
        self._auto_animate = True

        # 30fps animation timer
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _gen_heights(self):
        random.seed(2026)
        out = []
        for i in range(self._n):
            phase = i / self._n * 2 * math.pi * 4.5
            base = self._max_h * 0.55 + (self._max_h * 0.40) * math.sin(phase)
            base += random.uniform(-self._max_h * 0.15, self._max_h * 0.15)
            out.append(max(3, min(self._max_h, base)))
        return out

    def _tick(self):
        if self._auto_animate:
            self._progress = (self._progress + 0.0012) % 1.0
            self.update()

    # ── Public API ────────────────────────────────────────────────────────

    def set_progress(self, percent: float):
        self._progress = max(0.0, min(1.0, percent))
        self.update()

    def set_colors(self, played_color: str, light_color: str):
        self._played = QColor(played_color)
        self._light  = QColor(light_color)
        self.update()

    def set_auto_animate(self, enabled: bool) -> None:
        """Toggle the decorative internal animation.

        - True  (default at construction): widget runs an internal 30fps
          progress animation for visual filler.
        - False: animation timer stops; external code drives progress via
          set_progress(fraction). Use this when wiring a real audio
          playhead (Phase B).

        Restarting auto-animation re-arms the QTimer; progress continues
        from its current value (caller can call set_progress(0) first to
        reset)."""
        if self._auto_animate == enabled:
            return
        self._auto_animate = enabled
        if enabled:
            self._timer.start()
        else:
            self._timer.stop()

    # ── Paint ─────────────────────────────────────────────────────────────

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        cy = h / 2

        # Compute bar geometry
        gap = 1.5
        bar_w = max(3.0, (w - gap * (self._n - 1)) / self._n)
        playhead_idx = int(self._progress * self._n)

        # Gradient brush for played bars
        grad = QLinearGradient(0, cy - self._max_h / 2, 0, cy + self._max_h / 2)
        grad.setColorAt(0.0, self._light)
        grad.setColorAt(1.0, self._played)

        for i in range(self._n):
            x = i * (bar_w + gap)
            if x + bar_w > w:
                break
            bh = self._heights[i]
            y = cy - bh / 2
            if i < playhead_idx:
                p.setBrush(QBrush(grad))
            else:
                p.setBrush(self._unplayed)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(QRectF(x, y, bar_w, bh), 1, 1)

        # Glowing playhead — 2px white line
        if 0 < playhead_idx < self._n:
            ph_x = playhead_idx * (bar_w + gap) - gap / 2
            # outer glow (semi-transparent thick line)
            p.setPen(QPen(QColor(255, 255, 255, 60), 6))
            p.drawLine(int(ph_x), int(cy - self._max_h / 2),
                       int(ph_x), int(cy + self._max_h / 2))
            # inner crisp line
            p.setPen(QPen(QColor(255, 255, 255, 220), 2))
            p.drawLine(int(ph_x), int(cy - self._max_h / 2),
                       int(ph_x), int(cy + self._max_h / 2))
