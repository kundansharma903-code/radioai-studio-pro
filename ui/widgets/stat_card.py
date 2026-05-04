"""
StatCard — premium dashboard card with big stat + label + subtitle + icon.

Wraps PremiumCard. Inside:
  Top:    small uppercase label (Inter Black 9px, letter-spacing 1.5)
  Middle: big stat value (Inter Black 28px, letter-spacing -0.8)
  Bottom: subtitle (Inter Medium 10px)
  Top-right: PictorialIcon (36px box)
"""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QVBoxLayout, QHBoxLayout, QLabel, QSizePolicy

from ._tokens import (
    inter, TEXT_PRI, TEXT_SEC, TEXT_MUTED, PURPLE, PURPLE_LIGHT,
)
from .premium_card  import PremiumCard
from .pictorial_icon import PictorialIcon, IconType


class StatCard(PremiumCard):

    def __init__(self, label: str, value: str, subtitle: str,
                 icon_type: IconType, color: str = PURPLE,
                 light: str = PURPLE_LIGHT, parent=None):
        super().__init__(accent_color=color, light_color=light, parent=parent)
        self.setMinimumHeight(132)

        v = QVBoxLayout(self)
        v.setContentsMargins(20, 20, 20, 20)
        v.setSpacing(8)

        # Top row: label + icon
        top = QHBoxLayout()
        top.setSpacing(0)

        self._label = QLabel(label.upper())
        self._label.setFont(inter(9, QFont.Weight.Black, letter_spacing=1.5))
        self._label.setStyleSheet(f"color: {color}; background: transparent;")
        top.addWidget(self._label, alignment=Qt.AlignmentFlag.AlignTop)

        top.addStretch()

        self._icon = PictorialIcon(icon_type, color=color, light=light, size=36)
        top.addWidget(self._icon, alignment=Qt.AlignmentFlag.AlignTop)
        v.addLayout(top)

        # Big stat value
        self._value = QLabel(value)
        self._value.setFont(inter(28, QFont.Weight.Black, letter_spacing=-0.8))
        self._value.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        v.addWidget(self._value)

        # Subtitle
        self._sub = QLabel(subtitle)
        self._sub.setFont(inter(10, QFont.Weight.Medium))
        self._sub.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        self._sub.setWordWrap(True)
        v.addWidget(self._sub)

        v.addStretch()

    # ── Public setters for live updates ───────────────────────────────────
    def set_value(self, value: str):
        self._value.setText(value)
    def set_subtitle(self, sub: str):
        self._sub.setText(sub)
    def set_label(self, label: str):
        self._label.setText(label.upper())
