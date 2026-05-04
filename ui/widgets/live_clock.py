"""
LiveClock — big mono clock + day-of-week + date.

"21:56" Roboto Mono Bold 32px primary
":15"   Roboto Mono Bold 26px muted
"TUESDAY"          Inter Bold 9px purple-light uppercase letter-spacing 2
"JANUARY 31, 2023" Inter Medium 9px muted
QTimer ticks every 1 second.
"""

from datetime import datetime

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPainter, QColor, QFont
from PyQt6.QtWidgets import QWidget

from ._tokens import inter, mono, TEXT_PRI, TEXT_MUTED, PURPLE_LIGHT


class LiveClock(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._now = datetime.now()
        self.setFixedSize(180, 56)

        self._t = QTimer(self)
        self._t.setInterval(1000)
        self._t.timeout.connect(self._tick)
        self._t.start()

    def _tick(self):
        self._now = datetime.now()
        self.update()

    def get_current(self) -> datetime:
        return self._now

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        n = self._now
        hh_mm = n.strftime("%H:%M")
        ss = ":" + n.strftime("%S")

        # Big time: HH:MM
        p.setPen(QColor(TEXT_PRI))
        big = mono(32, bold=True, letter_spacing=-1.0)
        p.setFont(big)
        from PyQt6.QtGui import QFontMetrics
        fm = QFontMetrics(big)
        hh_w = fm.horizontalAdvance(hh_mm)
        p.drawText(0, 0, hh_w + 4, 36,
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   hh_mm)

        # Smaller seconds suffix
        small = mono(22, bold=True, letter_spacing=-1.0)
        p.setFont(small)
        p.setPen(QColor(TEXT_MUTED))
        p.drawText(hh_w + 2, 4, 80, 32,
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   ss)

        # Day of week label (purple, letter-spaced)
        p.setPen(QColor(PURPLE_LIGHT))
        p.setFont(inter(9, QFont.Weight.Bold, letter_spacing=2.0))
        dow = n.strftime("%A").upper()
        p.drawText(0, 38, 90, 12,
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   dow)

        # Date (muted, regular spacing)
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(inter(9, QFont.Weight.Medium))
        date_str = n.strftime("%B %d, %Y").upper()
        # Position after the day-of-week
        from PyQt6.QtGui import QFontMetrics
        dow_w = QFontMetrics(inter(9, QFont.Weight.Bold, 2.0)).horizontalAdvance(dow)
        p.drawText(dow_w + 12, 38, 200, 12,
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   date_str)
