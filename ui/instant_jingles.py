"""
RadioAI Studio Pro — Instant Jingles Library
Pixel-accurate match of Figma node 44:688 (file 7oN9K61g94wKx3nu44KKDF).

Live broadcast tool — DJ presses colored pads to instantly play jingles
on air during shows. Multiple pads can play simultaneously through the
shared BASS output device.

Layout (1440×900):
  Header           y=0..50           Logo, breadcrumb chip, title, clock
  Sidebar          y=50..868, x=0..180        Pallets list + actions + output
  Tabs row         y=58..94, center-area      KISS MAIN | DJ VAS | …
  Pads grid        y=104..632                 5×6 = 30 pads (KISS MAIN)
  Control row      y=644..680                 Up/Down/StopAll/AutoGain/…
  Right panel      y=50..868, x=1144..1432    Pad editor (preview + form)
  Status bar       y=868..900, 1440×32

TODO: Refactor _HeaderLogo, _HeaderOpenStudio, _ActiveBreadcrumbChip,
      _SidebarActionButton into ui/widgets/library_chrome.py when 3+
      libraries share them (currently 2: Songs Library + Instant Jingles).

Step status (incremental build):
  [✓] header + sidebar + pads grid + tabs (CHECKPOINT scope)
  [ ] tabs row interactivity
  [ ] right-panel pad editor
  [ ] audio playback wiring
  [ ] control row (Stop All, Loop, Latch, …)
"""

import logging
from typing import Optional
from core import dialogs

from PyQt6.QtCore import (
    Qt, QRectF, QTimer, QPropertyAnimation, pyqtProperty, pyqtSignal,
)
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QLinearGradient, QPainterPath, QFont,
    QCursor, QFontMetrics, QShortcut, QKeySequence,
)
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QComboBox, QHBoxLayout, QVBoxLayout,
    QLineEdit, QFileDialog, QMessageBox,
)

from core.settings import Settings
from ui.widgets._tokens import (
    inter, mono, rgba,
    BG_BASE, BG_PANEL, BG_CARD, BG_ELEVATED,
    TEXT_PRI, TEXT_SEC, TEXT_MUTED, TEXT_DIM,
    CYAN, CYAN_LIGHT, PURPLE, PURPLE_LIGHT, PURPLE_DARK, GREEN, GREEN_LIGHT,
    AMBER, AMBER_LIGHT, RED, RED_LIGHT,
)

log = logging.getLogger("InstantJingles")


# ════════════════════════════════════════════════════════════════════════════
# Geometry tokens
# ════════════════════════════════════════════════════════════════════════════

WINDOW_W   = 1440
WINDOW_H   = 900
HEADER_H   = 50
STATUS_H   = 32
SIDEBAR_W  = 180
RIGHT_W    = 296

# Center pads area lives between sidebar and right panel
CENTER_X0  = SIDEBAR_W + 12             # 192
CENTER_X1  = WINDOW_W - RIGHT_W - 8     # 1136
CENTER_W   = CENTER_X1 - CENTER_X0      # 944

# Tabs row + grid
TABS_Y     = HEADER_H + 10              # 60
TABS_H     = 36
GRID_Y     = HEADER_H + 56              # 106 (after tabs + 10 padding)

# Pad cell + spacing
PAD_W      = 144
PAD_H      = 78
PAD_GAP    = 12

GRID_W_5   = 5 * PAD_W + 4 * PAD_GAP    # 768
GRID_PAD_X = CENTER_X0 + (CENTER_W - GRID_W_5) // 2   # ~280

# Right panel
RIGHT_X    = WINDOW_W - RIGHT_W - 4     # 1140

# Status bar
STATUS_Y   = WINDOW_H - STATUS_H        # 868

# Output routing display map (audio_output INT → label)
OUTPUT_LABELS = {
    1: "Output 1 — Soundcard A",
    2: "Output 2 — Soundcard A",
    3: "Output 3 — Soundcard B",
    4: "Output 4 — Soundcard B",
    5: "Output 5 — Soundcard C",
    6: "Output 6 — Soundcard C",
    7: "Output 7 — Headphone Cue",
    8: "Output 8 — Monitor",
}

BG_DARK_PANEL = "#0a0c16"


# ════════════════════════════════════════════════════════════════════════════
# Header chrome — replicated locally per screen (see TODO at top of file)
# ════════════════════════════════════════════════════════════════════════════

class _HeaderLogo(QWidget):
    """36×36 purple gradient logo box with 5 white waveform bars."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(36, 36)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, 36, 36), 9, 9)
        p.setClipPath(path)
        g = QLinearGradient(0, 0, 36, 36)
        g.setColorAt(0.0,   QColor("#a78bfa"))
        g.setColorAt(0.355, QColor("#7c3aed"))
        g.setColorAt(0.711, QColor("#5b21b6"))
        p.fillRect(QRectF(0, 0, 36, 36), QBrush(g))
        p.setBrush(QColor(255, 255, 255, 235))
        p.setPen(Qt.PenStyle.NoPen)
        for x, h in [(6, 4), (12, 9), (18, 15), (24, 9), (30, 4)]:
            top = (36 - h) // 2
            p.drawRoundedRect(QRectF(x - 1.5, top, 3, h), 1.5, 1.5)


class _HeaderOpenStudio(QPushButton):
    """200×34 subtle-green Open Studio button with 'now playing' subtitle."""

    def __init__(self, parent=None):
        super().__init__("", parent)
        self.setFixedSize(200, 34)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFlat(True)
        self.setStyleSheet("background: transparent; border: none;")

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0.5, 0.5, 199, 33)
        path = QPainterPath()
        path.addRoundedRect(rect, 8, 8)
        p.setClipPath(path)
        g = QLinearGradient(0, 0, 200, 34)
        c1 = QColor(GREEN); c1.setAlphaF(0.10)
        c2 = QColor(GREEN); c2.setAlphaF(0.04)
        g.setColorAt(0.0, c1); g.setColorAt(1.0, c2)
        p.fillRect(QRectF(0, 0, 200, 34), QBrush(g))
        p.setClipping(False)
        bc = QColor(GREEN); bc.setAlphaF(0.30)
        p.setPen(QPen(bc, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 8, 8)
        p.setPen(QColor(GREEN))
        p.setFont(inter(11, QFont.Weight.Bold))
        p.drawText(12, 0, 16, 34,
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "▶")
        p.setFont(inter(11, QFont.Weight.Bold))
        p.drawText(28, 4, 170, 14,
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "Open Studio")
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(inter(8))
        p.drawText(28, 18, 170, 12,
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   "Billie Eilish — Bury A Friend")


class _ActiveBreadcrumbChip(QFrame):
    """⚡ Instant Jingles chip — purple with pulsing dot."""

    def __init__(self, text: str = "Instant Jingles", parent=None):
        super().__init__(parent)
        self._text = text
        self._dot_alpha = 1.0
        self.setFixedSize(140, 28)
        self._anim = QPropertyAnimation(self, b"dotAlpha", self)
        self._anim.setDuration(1400)
        self._anim.setStartValue(1.0); self._anim.setEndValue(0.4)
        self._anim.setLoopCount(-1); self._anim.start()

    def get_dotAlpha(self): return self._dot_alpha
    def set_dotAlpha(self, v): self._dot_alpha = v; self.update()
    dotAlpha = pyqtProperty(float, get_dotAlpha, set_dotAlpha)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0.5, 0.5, 139, 27)
        path = QPainterPath()
        path.addRoundedRect(rect, 14, 14)
        p.setClipPath(path)
        c1 = QColor(PURPLE); c1.setAlphaF(0.22)
        c2 = QColor(PURPLE); c2.setAlphaF(0.06)
        g = QLinearGradient(0, 0, 0, 28)
        g.setColorAt(0.0, c1); g.setColorAt(1.0, c2)
        p.fillRect(QRectF(0, 0, 140, 28), QBrush(g))
        p.setClipping(False)
        bc = QColor(PURPLE); bc.setAlphaF(0.35)
        p.setPen(QPen(bc, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 14, 14)
        # Lightning bolt + pulsing accent dot
        p.setPen(Qt.PenStyle.NoPen)
        glow = QColor(PURPLE_LIGHT); glow.setAlphaF(self._dot_alpha)
        p.setBrush(glow)
        p.drawEllipse(QRectF(10, 11, 6, 6))
        # Label
        p.setPen(QColor(PURPLE_LIGHT))
        p.setFont(inter(11, QFont.Weight.Bold))
        p.drawText(22, 0, 110, 28,
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   "⚡ " + self._text)


# ════════════════════════════════════════════════════════════════════════════
# Sidebar widgets
# ════════════════════════════════════════════════════════════════════════════

class _PalletRow(QFrame):
    """One row in the Pallets sidebar — 60px tall."""

    clicked = pyqtSignal(int)

    def __init__(self, pallet: dict, parent=None):
        super().__init__(parent)
        self._pallet = pallet
        self._selected = False
        self._hover = False
        self.setFixedSize(SIDEBAR_W, 60)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

    def set_selected(self, sel: bool):
        self._selected = sel
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(int(self._pallet.get("id", 0)))
        super().mousePressEvent(e)

    def enterEvent(self, e): self._hover = True;  self.update(); super().enterEvent(e)
    def leaveEvent(self, e): self._hover = False; self.update(); super().leaveEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0, 0, SIDEBAR_W, 60)

        # Background
        if self._selected:
            tint = QColor(PURPLE); tint.setAlphaF(0.18)
            p.fillRect(rect, tint)
            # 3px purple accent on the left
            p.fillRect(QRectF(0, 0, 3, 60), QColor(PURPLE))
        elif self._hover:
            p.fillRect(rect, QColor(255, 255, 255, 8))

        # Bottom hairline
        p.setPen(QPen(QColor(255, 255, 255, 14), 1))
        p.drawLine(8, 59, SIDEBAR_W - 8, 59)

        name = self._pallet.get("name") or "—"
        owner = self._pallet.get("owner") or ""
        cols = int(self._pallet.get("grid_cols") or 0)
        rows = int(self._pallet.get("grid_rows") or 0)
        filled = int(self._pallet.get("filled_count") or 0)
        sub = f"{cols}×{rows} grid"
        if filled:
            sub += f"  ·  {filled} jingle{'s' if filled != 1 else ''}"
        elif owner:
            sub += f"  ·  {owner}"

        # Name (uppercase if selected for emphasis matches Figma feel)
        p.setPen(QColor(TEXT_PRI if self._selected else TEXT_SEC))
        p.setFont(inter(12, QFont.Weight.Bold if self._selected
                                  else QFont.Weight.DemiBold))
        p.drawText(14, 10, SIDEBAR_W - 28, 18,
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   name.upper())

        # Subtitle
        p.setPen(QColor(PURPLE_LIGHT if self._selected else TEXT_MUTED))
        p.setFont(inter(9))
        p.drawText(14, 32, SIDEBAR_W - 28, 14,
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   sub)


class _SidebarActionButton(QPushButton):
    """Sidebar action button — full-width with left accent + label."""

    def __init__(self, text: str, color: str, bg_tint: str, parent=None):
        super().__init__(text, parent)
        self._color   = QColor(color)
        self._bg_tint = QColor(bg_tint)
        self._hover = False
        self.setFixedSize(SIDEBAR_W - 16, 28)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFlat(True)
        self.setStyleSheet("background: transparent; border: none;")
        self.setFont(inter(10, QFont.Weight.Bold))

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        rect = QRectF(0, 0, w, h)
        path = QPainterPath()
        path.addRoundedRect(rect, 5, 5)
        p.setClipPath(path)
        if self._hover:
            c = QColor(self._color); c.setAlphaF(0.16)
            p.fillRect(rect, self._bg_tint)
            p.fillRect(rect, c)
        else:
            p.fillRect(rect, self._bg_tint)
        p.fillRect(0, 0, 2, h, self._color)
        p.setClipping(False)
        bc = QColor(self._color); bc.setAlphaF(0.30)
        p.setPen(QPen(bc, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 5, 5)
        p.setPen(self._color)
        p.setFont(self.font())
        p.drawText(10, 0, w - 14, h,
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self.text())

    def enterEvent(self, e): self._hover = True;  self.update(); super().enterEvent(e)
    def leaveEvent(self, e): self._hover = False; self.update(); super().leaveEvent(e)


# ════════════════════════════════════════════════════════════════════════════
# Pads grid widgets
# ════════════════════════════════════════════════════════════════════════════

class _Pad(QFrame):
    """One jingle pad — 144×78 colored tile.

    State:
      - filled (label != ''):  solid pad with label + duration
      - empty  (label == ''):  amber dashed border + 'NEW ENTRY / Empty slot'
      - selected: amber glowing outer border (overrides hover)
      - playing: brighter inner highlight (set externally via set_playing)
    """

    left_clicked  = pyqtSignal(int)   # pad_id
    right_clicked = pyqtSignal(int)   # pad_id

    def __init__(self, pad: dict, parent=None):
        super().__init__(parent)
        self._pad = pad
        self._selected = False
        self._hover = False
        self._playing = False
        self.setFixedSize(PAD_W, PAD_H)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

    @property
    def pad_id(self) -> int:
        return int(self._pad.get("id") or 0)

    @property
    def is_empty(self) -> bool:
        # Empty means: explicit empty slot (label cleared AND no audio)
        label = (self._pad.get("label") or "").strip()
        return not label

    def set_selected(self, sel: bool):
        self._selected = sel
        self.update()

    def set_playing(self, playing: bool):
        self._playing = playing
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.left_clicked.emit(self.pad_id)
        elif e.button() == Qt.MouseButton.RightButton:
            self.right_clicked.emit(self.pad_id)
        super().mousePressEvent(e)

    def enterEvent(self, e): self._hover = True;  self.update(); super().enterEvent(e)
    def leaveEvent(self, e): self._hover = False; self.update(); super().leaveEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect    = QRectF(2, 2, PAD_W - 4, PAD_H - 4)
        radius  = 8
        color   = QColor(self._pad.get("color") or "#06b6d4")

        if self.is_empty:
            self._paint_empty(p, rect, radius, color)
        else:
            self._paint_filled(p, rect, radius, color)

        # Outer selection glow
        if self._selected:
            self._paint_selection_glow(p)

    def _paint_filled(self, p: QPainter, rect: QRectF, radius: int, color: QColor):
        # Saturated pad fill — slight darkening at the bottom for depth
        bottom = QColor(color); bottom.setHsl(
            color.hue(), color.saturation(),
            max(0, color.lightness() - 35), 255
        )
        g = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        g.setColorAt(0.0, color)
        g.setColorAt(1.0, bottom)

        # Background
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        p.setClipPath(path)
        p.fillRect(rect, QBrush(g))

        # Inner highlight on hover/playing — top stripe
        if self._hover or self._playing:
            hi = QColor(255, 255, 255,
                        80 if self._playing else 30)
            p.fillRect(QRectF(rect.x(), rect.y(),
                              rect.width(), rect.height() * 0.4),
                       hi)

        # Border — brighter top-left, subtle elsewhere
        p.setClipping(False)
        bright = QColor(color); bright.setHsl(
            color.hue(), color.saturation(),
            min(255, color.lightness() + 30), 255
        )
        p.setPen(QPen(bright, 1.4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, radius, radius)

        # Label (top-left, big)
        label = self._pad.get("label") or "—"
        p.setPen(QColor(255, 255, 255, 240))
        p.setFont(inter(20, QFont.Weight.Black, letter_spacing=-0.5))
        p.drawText(QRectF(rect.x() + 14, rect.y() + 8,
                          rect.width() - 28, 32),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                   label)

        # Duration (bottom-left)
        dur_ms = int(self._pad.get("duration_ms") or 0)
        if dur_ms > 0:
            secs = dur_ms / 1000.0
            dur_text = f"{secs:04.1f}s".lstrip("0") or "0.0s"
        else:
            dur_text = "—"
        p.setPen(QColor(255, 255, 255, 180))
        p.setFont(mono(9, bold=True))
        p.drawText(QRectF(rect.x() + 14, rect.bottom() - 22,
                          rect.width() - 28, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   dur_text)

    def _paint_empty(self, p: QPainter, rect: QRectF, radius: int, color: QColor):
        # Dark pad with amber dashed border
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        p.setClipPath(path)
        p.fillRect(rect, QColor("#0e1020"))
        if self._hover:
            tint = QColor(AMBER); tint.setAlphaF(0.06)
            p.fillRect(rect, tint)
        p.setClipping(False)

        pen = QPen(QColor(AMBER), 1.4, Qt.PenStyle.DashLine)
        pen.setDashPattern([4, 3])
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, radius, radius)

        # NEW ENTRY headline
        p.setPen(QColor(AMBER))
        p.setFont(inter(11, QFont.Weight.Bold, letter_spacing=1.0))
        p.drawText(QRectF(rect.x(), rect.y() + 18, rect.width(), 16),
                   Qt.AlignmentFlag.AlignCenter, "NEW ENTRY")

        # Empty slot subtitle
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(inter(9))
        p.drawText(QRectF(rect.x(), rect.y() + 38, rect.width(), 14),
                   Qt.AlignmentFlag.AlignCenter, "Empty slot")

    def _paint_selection_glow(self, p: QPainter):
        """Amber glowing outline around the pad — drawn outside the inner rect."""
        # Outer glow (3 stacked passes for soft halo)
        for i, alpha in enumerate([40, 80, 140]):
            inset = 2 - i
            r = QRectF(inset, inset, PAD_W - inset * 2, PAD_H - inset * 2)
            c = QColor(AMBER); c.setAlpha(alpha)
            p.setPen(QPen(c, 1.5 + i * 0.4))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r, 9 + i, 9 + i)


# ════════════════════════════════════════════════════════════════════════════
# Tabs row
# ════════════════════════════════════════════════════════════════════════════

class _PalletTab(QPushButton):
    """One tab in the tab row — name only, cyan underline when active."""

    def __init__(self, pallet: dict, parent=None):
        super().__init__("", parent)
        self._pallet = pallet
        self._active = False
        self._hover = False
        text = pallet.get("name") or "—"
        # Width fits text + padding
        fm = QFontMetrics(inter(11, QFont.Weight.DemiBold))
        self.setFixedSize(max(80, fm.horizontalAdvance(text) + 28), TABS_H)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFlat(True)
        self.setStyleSheet("background: transparent; border: none;")

    @property
    def pallet_id(self) -> int:
        return int(self._pallet.get("id") or 0)

    def set_active(self, active: bool):
        self._active = active
        self.update()

    def enterEvent(self, e): self._hover = True;  self.update(); super().enterEvent(e)
    def leaveEvent(self, e): self._hover = False; self.update(); super().leaveEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        text = self._pallet.get("name") or "—"

        # Active gets a subtle bg + cyan underline
        if self._active:
            bg = QColor(CYAN); bg.setAlphaF(0.08)
            p.fillRect(QRectF(0, 0, w, h), bg)
            p.fillRect(QRectF(0, h - 2, w, 2), QColor(CYAN))
            p.setPen(QColor(CYAN_LIGHT))
        elif self._hover:
            p.setPen(QColor(TEXT_PRI))
        else:
            p.setPen(QColor(TEXT_MUTED))

        p.setFont(inter(11, QFont.Weight.DemiBold, letter_spacing=0.6))
        p.drawText(QRectF(0, 0, w, h),
                   Qt.AlignmentFlag.AlignCenter, text)


# ════════════════════════════════════════════════════════════════════════════
# Pad editor right panel
# ════════════════════════════════════════════════════════════════════════════

class _PadPreview(QFrame):
    """Compact preview card inside the pad editor — shows the pad's
    current colour, label and duration. ~104×80."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pad: dict = {}
        self.setFixedSize(104, 80)

    def set_pad(self, pad: dict):
        self._pad = pad or {}
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0, 0, 104, 80)
        color = QColor(self._pad.get("color") or "#06b6d4")
        bottom = QColor(color); bottom.setHsl(
            color.hue(), color.saturation(),
            max(0, color.lightness() - 35), 255
        )
        g = QLinearGradient(0, 0, 0, 80)
        g.setColorAt(0.0, color); g.setColorAt(1.0, bottom)
        path = QPainterPath()
        path.addRoundedRect(rect, 8, 8)
        p.setClipPath(path)
        p.fillRect(rect, QBrush(g))
        p.setClipping(False)

        bright = QColor(color); bright.setHsl(
            color.hue(), color.saturation(),
            min(255, color.lightness() + 30), 255
        )
        p.setPen(QPen(bright, 1.2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 8, 8)

        label = self._pad.get("label") or "—"
        p.setPen(QColor(255, 255, 255, 240))
        p.setFont(inter(18, QFont.Weight.Black, letter_spacing=-0.5))
        p.drawText(QRectF(10, 6, 90, 26),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                   label)

        dur_ms = int(self._pad.get("duration_ms") or 0)
        dur_text = (f"{dur_ms / 1000:.1f}s" if dur_ms > 0 else "—")
        p.setPen(QColor(255, 255, 255, 180))
        p.setFont(mono(9, bold=True))
        p.drawText(QRectF(10, 36, 90, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   dur_text)
        p.setPen(QColor(255, 255, 255, 130))
        p.setFont(inter(8))
        p.drawText(QRectF(10, 56, 90, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "Pad Label")


class _ColorSwatch(QPushButton):
    """Tiny circular color swatch — selected state has a white ring + halo."""

    swatch_clicked = pyqtSignal(str)

    SIZE = 22

    def __init__(self, color: str, parent=None):
        super().__init__("", parent)
        self._color_hex = color
        self._color = QColor(color)
        self._selected = False
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFlat(True)
        self.setStyleSheet("background: transparent; border: none;")

    def set_selected(self, sel: bool):
        self._selected = sel
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.swatch_clicked.emit(self._color_hex)
        super().mousePressEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._selected:
            halo = QColor(self._color); halo.setAlphaF(0.45)
            p.setPen(QPen(halo, 3))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(0, 0, self.SIZE, self.SIZE)
            p.setPen(QPen(QColor("#ffffff"), 1.6))
            p.drawEllipse(2, 2, self.SIZE - 4, self.SIZE - 4)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self._color)
            p.drawEllipse(5, 5, self.SIZE - 10, self.SIZE - 10)
        else:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self._color)
            p.drawEllipse(2, 2, self.SIZE - 4, self.SIZE - 4)


# Color palette offered in the pad editor (matches the seed palette)
EDITOR_SWATCHES = [
    "#f59e0b", "#10b981", "#3b82f6", "#be123c", "#8b5cf6",
    "#06b6d4", "#ec4899", "#ca8a04", "#0d9488", "#65a30d",
]


class _AIInsightBox(QFrame):
    """Purple-gradient AI insight panel at the bottom of the pad editor."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(76)
        self._line1 = "✦ AI: Select a pad to see usage analytics"
        self._line2 = "More analytics coming soon"

    def set_lines(self, line1: str, line2: str):
        self._line1 = line1
        self._line2 = line2
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0, 0, self.width(), self.height())
        # Background gradient
        c1 = QColor(PURPLE);       c1.setAlphaF(0.18)
        c2 = QColor(PURPLE_DARK);  c2.setAlphaF(0.10)
        g = QLinearGradient(0, 0, 0, self.height())
        g.setColorAt(0.0, c1); g.setColorAt(1.0, c2)
        path = QPainterPath(); path.addRoundedRect(rect, 8, 8)
        p.setClipPath(path)
        p.fillRect(rect, QBrush(g))
        p.setClipping(False)
        # Border
        bc = QColor(PURPLE); bc.setAlphaF(0.40)
        p.setPen(QPen(bc, 1)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 8, 8)
        # Line 1 (purple bold)
        p.setPen(QColor(PURPLE_LIGHT))
        p.setFont(inter(10, QFont.Weight.Bold))
        p.drawText(QRectF(12, 8, self.width() - 24, 20),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._line1)
        # Line 2 (dim)
        p.setPen(QColor(TEXT_SEC))
        p.setFont(inter(9))
        p.drawText(QRectF(12, 30, self.width() - 24, 36),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop |
                   Qt.TextFlag.TextWordWrap,
                   self._line2)


class _PadEditor(QFrame):
    """Right-panel pad editor.

    The screen owns DB writes — this widget emits semantic signals when the
    user changes something, and the screen responds by calling db.update_pad
    + reloading the pads grid. Clean separation."""

    label_committed     = pyqtSignal(int, str)        # pad_id, new label
    color_picked        = pyqtSignal(int, str)        # pad_id, hex
    output_picked       = pyqtSignal(int, int)        # pad_id, output 1..8
    volume_committed    = pyqtSignal(int, int)        # pad_id, vol 0..100
    behaviour_picked    = pyqtSignal(int, str)        # pad_id, behaviour
    assign_audio_clicked = pyqtSignal(int)            # pad_id
    clear_pad_clicked   = pyqtSignal(int)             # pad_id
    test_pad_clicked    = pyqtSignal(int)             # pad_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pad: dict = {}
        self._suppress_signals = False
        self.setStyleSheet(
            f"QFrame {{ background: {BG_DARK_PANEL}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; "
            f"border-radius: 8px; }}"
        )

        v = QVBoxLayout(self)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(10)

        # Header
        self._header_lbl = QLabel("PAD EDITOR")
        self._header_lbl.setFont(
            inter(10, QFont.Weight.Bold, letter_spacing=1.2))
        self._header_lbl.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; border: none;")
        v.addWidget(self._header_lbl)
        sub = QLabel("Right-click any pad to edit")
        sub.setFont(inter(10))
        sub.setStyleSheet(
            f"color: {TEXT_DIM}; background: transparent; border: none;")
        v.addWidget(sub)

        # Top row — preview + swatch grid
        top = QHBoxLayout(); top.setSpacing(10); top.setContentsMargins(0, 4, 0, 0)
        self._preview = _PadPreview()
        top.addWidget(self._preview, alignment=Qt.AlignmentFlag.AlignTop)

        sw_box = QWidget()
        sw_box.setStyleSheet("background: transparent;")
        sw_layout = QHBoxLayout(sw_box)
        sw_layout.setContentsMargins(0, 0, 0, 0); sw_layout.setSpacing(4)
        self._swatches: list[_ColorSwatch] = []
        for hex_c in EDITOR_SWATCHES:
            s = _ColorSwatch(hex_c)
            s.swatch_clicked.connect(self._on_swatch_clicked)
            sw_layout.addWidget(s)
            self._swatches.append(s)
        sw_layout.addStretch()
        # Wrap the swatch row at the top of the right column
        sw_col = QVBoxLayout(); sw_col.setSpacing(4)
        sw_col_label = QLabel("Pad Color")
        sw_col_label.setFont(inter(9, QFont.Weight.Medium))
        sw_col_label.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent; border: none;")
        sw_col.addWidget(sw_col_label)
        sw_col.addWidget(sw_box)
        sw_col.addStretch()
        sw_col_w = QWidget(); sw_col_w.setStyleSheet("background: transparent;")
        sw_col_w.setLayout(sw_col)
        top.addWidget(sw_col_w, stretch=1)
        v.addLayout(top)

        # Form fields
        self._pad_label_input = self._make_input("Pad label")
        self._pad_label_input.editingFinished.connect(self._on_label_committed)
        v.addLayout(self._labelled("Pad Label", self._pad_label_input))

        self._audio_file_lbl = self._make_readonly("(none — assign a file)")
        v.addLayout(self._labelled("Audio File", self._audio_file_lbl))

        self._duration_lbl = self._make_readonly("—")
        v.addLayout(self._labelled("Duration", self._duration_lbl))

        self._output_combo = QComboBox()
        self._output_combo.addItems([OUTPUT_LABELS[i] for i in range(1, 9)])
        self._output_combo.setFixedHeight(28)
        self._output_combo.setFont(inter(10))
        self._output_combo.setStyleSheet(self._combo_qss())
        self._output_combo.currentIndexChanged.connect(self._on_output_changed)
        v.addLayout(self._labelled("Output", self._output_combo))

        self._volume_input = self._make_input("100%")
        self._volume_input.editingFinished.connect(self._on_volume_committed)
        v.addLayout(self._labelled("Volume", self._volume_input))

        self._behaviour_combo = QComboBox()
        self._behaviour_combo.addItems([
            "Play once (default)", "Loop (until stop)", "Latch (toggle)",
        ])
        self._behaviour_combo.setFixedHeight(28)
        self._behaviour_combo.setFont(inter(10))
        self._behaviour_combo.setStyleSheet(self._combo_qss())
        self._behaviour_combo.currentIndexChanged.connect(self._on_behaviour_changed)
        v.addLayout(self._labelled("Behaviour", self._behaviour_combo))

        # Assign / Clear row
        btn_row = QHBoxLayout(); btn_row.setSpacing(8); btn_row.setContentsMargins(0, 4, 0, 0)
        self._assign_btn = QPushButton("📁  Assign Audio File")
        self._assign_btn.setFixedHeight(30)
        self._assign_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._assign_btn.setFont(inter(10, QFont.Weight.DemiBold))
        self._assign_btn.setStyleSheet(
            f"QPushButton {{ background: {rgba(GREEN, 0.18)}; color: {GREEN_LIGHT}; "
            f"border: 1px solid {rgba(GREEN, 0.40)}; border-radius: 6px; "
            f"padding: 0 10px; }}"
            f"QPushButton:hover {{ background: {rgba(GREEN, 0.28)}; }}"
            f"QPushButton:disabled {{ background: #181a30; color: {TEXT_DIM}; "
            f"border: 1px solid {rgba('#ffffff', 0.04)}; }}"
        )
        self._assign_btn.clicked.connect(self._on_assign_clicked)
        btn_row.addWidget(self._assign_btn, stretch=2)

        self._clear_btn = QPushButton("✕  Clear Pad")
        self._clear_btn.setFixedHeight(30)
        self._clear_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._clear_btn.setFont(inter(10, QFont.Weight.DemiBold))
        self._clear_btn.setStyleSheet(
            f"QPushButton {{ background: {rgba(RED, 0.12)}; color: {RED_LIGHT}; "
            f"border: 1px solid {rgba(RED, 0.35)}; border-radius: 6px; "
            f"padding: 0 10px; }}"
            f"QPushButton:hover {{ background: {rgba(RED, 0.20)}; }}"
            f"QPushButton:disabled {{ background: #181a30; color: {TEXT_DIM}; "
            f"border: 1px solid {rgba('#ffffff', 0.04)}; }}"
        )
        self._clear_btn.clicked.connect(self._on_clear_clicked)
        btn_row.addWidget(self._clear_btn, stretch=1)
        v.addLayout(btn_row)

        # Test / Preview button
        self._test_btn = QPushButton("▶  Test / Preview Pad")
        self._test_btn.setFixedHeight(32)
        self._test_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._test_btn.setFont(inter(11, QFont.Weight.DemiBold))
        self._test_btn.setStyleSheet(
            f"QPushButton {{ background: qlineargradient("
            f"x1:0,y1:0,x2:0,y2:1, stop:0 {CYAN_LIGHT}, stop:1 {CYAN}); "
            f"color: white; border: none; border-radius: 6px; }}"
            f"QPushButton:hover {{ background: qlineargradient("
            f"x1:0,y1:0,x2:0,y2:1, stop:0 #67e8f9, stop:1 {CYAN}); }}"
            f"QPushButton:disabled {{ background: #181a30; color: {TEXT_DIM}; }}"
        )
        self._test_btn.clicked.connect(self._on_test_clicked)
        v.addWidget(self._test_btn)

        # AI insight at the bottom
        self._insight = _AIInsightBox()
        v.addWidget(self._insight)
        v.addStretch()

        # Initial empty state
        self.set_pad(None, stats=None)

    # ── Helpers ──────────────────────────────────────────────────────────

    def _make_input(self, placeholder: str) -> QLineEdit:
        e = QLineEdit()
        e.setPlaceholderText(placeholder)
        e.setFixedHeight(28)
        e.setFont(inter(10))
        e.setStyleSheet(
            f"QLineEdit {{ background: {BG_CARD}; color: {TEXT_PRI}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; border-radius: 5px; "
            f"padding: 0 8px; selection-background-color: {rgba(CYAN, 0.25)}; }}"
            f"QLineEdit:focus {{ border-color: {CYAN}; }}"
            f"QLineEdit:disabled {{ color: {TEXT_DIM}; }}"
        )
        return e

    def _make_readonly(self, text: str) -> QLabel:
        l = QLabel(text)
        l.setFixedHeight(28)
        l.setFont(inter(10))
        l.setStyleSheet(
            f"QLabel {{ background: {BG_CARD}; color: {TEXT_SEC}; "
            f"border: 1px solid {rgba('#ffffff', 0.04)}; border-radius: 5px; "
            f"padding: 0 8px; }}"
        )
        return l

    def _labelled(self, text: str, widget) -> QVBoxLayout:
        v = QVBoxLayout(); v.setSpacing(2); v.setContentsMargins(0, 0, 0, 0)
        l = QLabel(text)
        l.setFont(inter(9, QFont.Weight.Medium))
        l.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent; border: none;")
        v.addWidget(l)
        if isinstance(widget, QWidget):
            v.addWidget(widget)
        else:
            v.addLayout(widget)
        return v

    def _combo_qss(self) -> str:
        return (
            f"QComboBox {{ background: {BG_CARD}; color: {TEXT_PRI}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; border-radius: 5px; "
            f"padding: 0 22px 0 8px; }}"
            f"QComboBox:focus {{ border-color: {CYAN}; }}"
            f"QComboBox::drop-down {{ border: none; width: 18px; }}"
            f"QComboBox::down-arrow {{ image: none; width: 0; height: 0; "
            f"border-left: 4px solid transparent; "
            f"border-right: 4px solid transparent; "
            f"border-top: 5px solid {TEXT_MUTED}; margin-right: 6px; }}"
            f"QComboBox QAbstractItemView {{ background: {BG_CARD}; "
            f"color: {TEXT_PRI}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; border-radius: 5px; "
            f"selection-background-color: {rgba(CYAN, 0.20)}; "
            f"selection-color: {CYAN_LIGHT}; outline: none; padding: 4px; }}"
        )

    # ── Population ───────────────────────────────────────────────────────

    def set_pad(self, pad: Optional[dict], stats: Optional[dict] = None,
                output: int = 3):
        """Populate fields from a pad row. None → empty placeholder state."""
        self._suppress_signals = True
        self._pad = pad or {}
        is_empty = pad is None

        if is_empty:
            self._header_lbl.setText("PAD EDITOR")
            self._preview.set_pad({})
            for s in self._swatches:
                s.set_selected(False)
            self._pad_label_input.setText("")
            self._pad_label_input.setEnabled(False)
            self._audio_file_lbl.setText("(none — select a pad)")
            self._duration_lbl.setText("—")
            self._output_combo.setCurrentIndex(max(0, output - 1))
            self._output_combo.setEnabled(False)
            self._volume_input.setText("")
            self._volume_input.setEnabled(False)
            self._behaviour_combo.setCurrentIndex(0)
            self._behaviour_combo.setEnabled(False)
            self._assign_btn.setEnabled(False)
            self._clear_btn.setEnabled(False)
            self._test_btn.setEnabled(False)
            self._insight.set_lines(
                "✦ AI: Select a pad to see usage analytics",
                "Right-click any pad to populate this editor",
            )
        else:
            label = pad.get("label") or "—"
            self._header_lbl.setText(f"PAD EDITOR — {label}")
            self._preview.set_pad(pad)
            cur_color = (pad.get("color") or "").lower()
            for s in self._swatches:
                s.set_selected(s._color_hex.lower() == cur_color)
            self._pad_label_input.setEnabled(True)
            self._pad_label_input.setText(pad.get("label") or "")
            file_path = pad.get("file_path") or ""
            import os as _os
            self._audio_file_lbl.setText(
                _os.path.basename(file_path) if file_path
                else "(none — assign a file)"
            )
            dur_ms = int(pad.get("duration_ms") or 0)
            if dur_ms > 0:
                self._duration_lbl.setText(f"{dur_ms / 1000:.1f}s (auto)")
            else:
                self._duration_lbl.setText("—")
            self._output_combo.setEnabled(True)
            self._output_combo.setCurrentIndex(max(0, output - 1))
            self._volume_input.setEnabled(True)
            self._volume_input.setText(f"{int(pad.get('volume') or 100)}%")
            self._behaviour_combo.setEnabled(True)
            beh = pad.get("behaviour") or "play_once"
            self._behaviour_combo.setCurrentIndex(
                {"play_once": 0, "loop": 1, "latch": 2}.get(beh, 0)
            )
            self._assign_btn.setEnabled(True)
            self._clear_btn.setEnabled(bool(file_path))
            self._test_btn.setEnabled(bool(file_path))
            # Insight
            plays = (stats or {}).get("plays_in_window", 0)
            total = (stats or {}).get("play_count", 0)
            if total > 0:
                self._insight.set_lines(
                    f"✦ AI: This pad used {plays}× in last 7 days",
                    "More analytics coming soon",
                )
            else:
                self._insight.set_lines(
                    "✦ AI: This pad has not been played yet",
                    "Press the pad to start tracking usage",
                )

        self._suppress_signals = False

    # ── Signal handlers (skipped while suppress_signals is on) ───────────

    def _pad_id(self) -> int:
        return int(self._pad.get("id") or 0)

    def _on_swatch_clicked(self, hex_color: str):
        if self._suppress_signals:
            return
        for s in self._swatches:
            s.set_selected(s._color_hex.lower() == hex_color.lower())
        # Live-preview the pad colour locally so the editor previews the
        # change without waiting for the round-trip refresh.
        self._pad["color"] = hex_color
        self._preview.set_pad(self._pad)
        self.color_picked.emit(self._pad_id(), hex_color)

    def _on_label_committed(self):
        if self._suppress_signals:
            return
        new_label = self._pad_label_input.text().strip()
        if new_label != (self._pad.get("label") or ""):
            self._pad["label"] = new_label
            self._preview.set_pad(self._pad)
            self.label_committed.emit(self._pad_id(), new_label)

    def _on_output_changed(self, idx: int):
        if self._suppress_signals:
            return
        self.output_picked.emit(self._pad_id(), idx + 1)

    def _on_volume_committed(self):
        if self._suppress_signals:
            return
        raw = self._volume_input.text().strip().rstrip("%")
        try:
            v = max(0, min(100, int(raw or 100)))
        except ValueError:
            v = 100
        self._volume_input.setText(f"{v}%")
        self.volume_committed.emit(self._pad_id(), v)

    def _on_behaviour_changed(self, idx: int):
        if self._suppress_signals:
            return
        beh = ["play_once", "loop", "latch"][idx]
        self.behaviour_picked.emit(self._pad_id(), beh)

    def _on_assign_clicked(self):
        if self._pad_id():
            self.assign_audio_clicked.emit(self._pad_id())

    def _on_clear_clicked(self):
        if self._pad_id():
            self.clear_pad_clicked.emit(self._pad_id())

    def _on_test_clicked(self):
        if self._pad_id():
            self.test_pad_clicked.emit(self._pad_id())


# ════════════════════════════════════════════════════════════════════════════
# Bottom control row (Up | Down | Stop All | AutoGain | MixFade | Loop | Latch)
# ════════════════════════════════════════════════════════════════════════════

class _ControlButton(QPushButton):
    """Compact bottom-row control button — tinted bg + colored text."""

    def __init__(self, text: str, color: str, parent=None,
                 prominent: bool = False):
        super().__init__(text, parent)
        self._color = QColor(color)
        self._prominent = prominent
        self._toggled_on = False
        self.setFixedHeight(30)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFont(inter(10, QFont.Weight.DemiBold))
        self.setFlat(True)
        self.setStyleSheet("background: transparent; border: none;")
        # Width fits text + padding
        fm = QFontMetrics(self.font())
        self.setMinimumWidth(fm.horizontalAdvance(text) + 24)

    def set_toggled(self, on: bool):
        self._toggled_on = on
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0, 0, self.width(), self.height())
        path = QPainterPath(); path.addRoundedRect(rect, 6, 6)
        p.setClipPath(path)

        # Background tint
        if self._prominent:
            # Stop All — solid red gradient, very visible
            g = QLinearGradient(0, 0, 0, self.height())
            g.setColorAt(0.0, QColor(self._color))
            top = QColor(self._color); top.setHsl(
                self._color.hue(), self._color.saturation(),
                min(255, self._color.lightness() + 30), 255
            )
            g.setColorAt(0.0, top); g.setColorAt(1.0, QColor(self._color))
            p.fillRect(rect, QBrush(g))
        else:
            tint = QColor(self._color)
            tint.setAlphaF(0.22 if self._toggled_on else 0.10)
            p.fillRect(rect, tint)
        p.setClipping(False)

        # Border
        bc = QColor(self._color); bc.setAlphaF(
            0.65 if (self._toggled_on or self._prominent) else 0.35)
        p.setPen(QPen(bc, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1),
                          6, 6)

        # Text
        if self._prominent:
            p.setPen(QColor("#ffffff"))
        else:
            p.setPen(QColor(self._color))
        p.setFont(self.font())
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.text())


# ════════════════════════════════════════════════════════════════════════════
# Main screen
# ════════════════════════════════════════════════════════════════════════════

class InstantJingles(QWidget):

    breadcrumb_clicked = pyqtSignal(str)
    studio_clicked     = pyqtSignal()
    pallet_changed     = pyqtSignal(int)
    pad_played         = pyqtSignal(int, str)   # pad_id, file_path
    pad_selected       = pyqtSignal(int)        # pad_id (right-click)
    pads_changed       = pyqtSignal()           # any DB mutation that affects what Studio renders

    def __init__(self, db, parent=None, engine=None,
                 instant_jingle_engine=None):
        super().__init__(parent)
        self._db = db
        self._audio_engine = engine    # shared AudioEngine (Option C DI)
        # Caller-provided shared InstantJingleEngine (set by MainWindow
        # so Studio + standalone screen drive the same polyphony state).
        # When None, fall through to creating an own instance below
        # (legacy/test path; backward-compat with prior ctor shape).
        self._shared_ije = instant_jingle_engine

        # State
        self._pallets: list[dict]   = []
        self._pads:    list[dict]   = []
        self._selected_pallet_id: Optional[int] = None
        self._selected_pad_id:    Optional[int] = None
        self._latched_pads: set[int] = set()       # pad_ids currently latched-on
        self._autogain_on = False                  # visual stub
        self._mixfade_on  = False                  # visual stub

        # Refs to dynamic widgets
        self._pallet_rows: list[_PalletRow] = []
        self._pads_widgets: list[_Pad] = []
        self._tabs: list[_PalletTab] = []
        self._pads_container: Optional[QWidget] = None
        self._tabs_container: Optional[QWidget] = None
        self._output_combo:   Optional[QComboBox] = None
        self._clock_lbl:      Optional[QLabel] = None
        self._status_count:   Optional[QLabel] = None
        self._editor:         Optional[_PadEditor] = None

        self.setFixedSize(WINDOW_W, WINDOW_H)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)   # for keyboard nav
        self.setStyleSheet(
            "background: qlineargradient("
            "x1:0, y1:0, x2:1, y2:1, "
            "stop:0 #0a0d1a, stop:0.5 #06080f, stop:1 #020308);"
        )

        # Migrate + seed first run
        try:
            self._db._ensure_jingle_pads_columns()
            from database.seeds_instant import seed_if_empty
            seed_if_empty(self._db)
        except Exception as exc:
            log.error(f"seed/migrate failed: {exc}")

        # Polyphonic playback engine — Phase B4 rebased on AudioEngine.
        # IJE is now a thin adapter; constructor takes the shared engine.
        # When MainWindow injected a shared instance via the
        # `instant_jingle_engine` kwarg, reuse it so both the standalone
        # screen and Studio's IJ panel see the same playing-state and
        # polyphony cap. Otherwise (legacy/test paths) build a new one.
        try:
            if self._shared_ije is not None:
                self._engine = self._shared_ije
            else:
                from core.instant_jingle_engine import InstantJingleEngine
                self._engine = InstantJingleEngine(
                    engine=self._audio_engine, parent=self)
            self._engine.pad_started.connect(self._on_engine_started)
            self._engine.pad_ended.connect(self._on_engine_ended)
            self._engine.pad_stopped.connect(self._on_engine_stopped)
        except Exception as exc:
            log.error(f"engine init failed: {exc}")
            self._engine = None

        self._build_header()
        self._build_sidebar()
        self._build_center_area()
        self._build_right_panel()
        self._build_status_bar()
        self._install_shortcuts()

        # Initial data load
        self._load_pallets()

        # Live clock
        self._tick()
        t = QTimer(self)
        t.setInterval(1000); t.timeout.connect(self._tick); t.start()

        log.info("InstantJingles ready (Figma 44:688)")

    def _install_shortcuts(self):
        """Up/Down/Esc keyboard shortcuts. Wired on the screen widget so they
        only fire while Instant Jingles is the active stack page."""
        for key, handler in [
            (QKeySequence(Qt.Key.Key_Up),    self._on_nav_up),
            (QKeySequence(Qt.Key.Key_Down),  self._on_nav_down),
            (QKeySequence(Qt.Key.Key_Left),  self._on_nav_left),
            (QKeySequence(Qt.Key.Key_Right), self._on_nav_right),
            (QKeySequence(Qt.Key.Key_Escape), self._on_stop_all),
        ]:
            sc = QShortcut(key, self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(handler)

    # ── HEADER ───────────────────────────────────────────────────────────

    def _build_header(self):
        bg = QFrame(self)
        bg.setGeometry(0, 0, WINDOW_W, HEADER_H)
        bg.setStyleSheet(
            f"background: qlineargradient(x1:0,y1:0,x2:0,y2:1, "
            f"stop:0 rgba(16,19,31,0.95), stop:1 rgba(10,12,22,0.95)); "
            f"border-bottom: 1px solid {rgba('#ffffff', 0.06)};"
        )
        # Hairline highlight
        hl = QFrame(self)
        hl.setGeometry(0, HEADER_H - 1, WINDOW_W, 1)
        hl.setStyleSheet(
            "background: qlineargradient(x1:0,y1:0,x2:1,y2:0, "
            "stop:0 rgba(255,255,255,0), stop:0.5 rgba(255,255,255,0.10), "
            "stop:1 rgba(255,255,255,0));"
        )

        # Logo + brand
        _HeaderLogo(self).move(14, 8)
        l = QLabel("RadioAI", self)
        l.setGeometry(60, 8, 120, 16)
        l.setFont(inter(14, QFont.Weight.Bold))
        l.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        l = QLabel("STUDIO PRO", self)
        l.setGeometry(60, 26, 120, 12)
        l.setFont(inter(8, QFont.Weight.Bold, letter_spacing=1.2))
        l.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

        # Breadcrumb
        cp_btn = QPushButton("Control Panel", self)
        cp_btn.setGeometry(156, 14, 100, 22)
        cp_btn.setFont(inter(11, QFont.Weight.Medium))
        cp_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        cp_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {TEXT_MUTED}; "
            f"border: none; padding: 0; text-align: left; }}"
            f"QPushButton:hover {{ color: {TEXT_PRI}; }}"
        )
        cp_btn.clicked.connect(lambda: self.breadcrumb_clicked.emit("control_panel"))

        sep = QLabel("|", self); sep.setGeometry(252, 14, 8, 22)
        sep.setFont(inter(11))
        sep.setStyleSheet(f"color: {TEXT_DIM}; background: transparent;")

        l = QLabel("Libraries", self)
        l.setGeometry(262, 14, 60, 22)
        l.setFont(inter(11, QFont.Weight.Medium))
        l.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

        sep2 = QLabel("|", self); sep2.setGeometry(322, 14, 8, 22)
        sep2.setFont(inter(11))
        sep2.setStyleSheet(f"color: {TEXT_DIM}; background: transparent;")

        chip = _ActiveBreadcrumbChip("Instant Jingles", self)
        chip.move(334, 11)

        # Title + subtitle
        l = QLabel("Instant Jingles", self)
        l.setGeometry(488, 4, 280, 22)
        l.setFont(inter(18, QFont.Weight.Bold))
        l.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        l = QLabel("Live broadcast pads — manage pallets and button assignments", self)
        l.setGeometry(488, 26, 480, 16)
        l.setFont(inter(10))
        l.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

        # Clock + station
        self._clock_lbl = QLabel("21:56:15", self)
        self._clock_lbl.setGeometry(990, 8, 100, 22)
        self._clock_lbl.setFont(mono(18, bold=True))
        self._clock_lbl.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        l = QLabel(Settings().station_display, self)
        l.setObjectName("hdr_station_lbl")
        l.setGeometry(990, 28, 100, 14)
        l.setFont(inter(9, QFont.Weight.Medium))
        l.setStyleSheet(f"color: {GREEN}; background: transparent;")

        # Open Studio
        osb = _HeaderOpenStudio(self)
        osb.move(1218, 8)
        osb.clicked.connect(self.studio_clicked.emit)

    # ── SIDEBAR ──────────────────────────────────────────────────────────

    def _build_sidebar(self):
        sb = QFrame(self)
        sb.setGeometry(0, HEADER_H, SIDEBAR_W, WINDOW_H - HEADER_H - STATUS_H)
        sb.setStyleSheet(
            f"background: {BG_DARK_PANEL}; "
            f"border-right: 1px solid {rgba('#ffffff', 0.06)};"
        )

        # ── PALLETS section header ────────────────────────────────────────
        y = HEADER_H + 8
        l = QLabel("PALLETS", self)
        l.setGeometry(12, y, 80, 14)
        l.setFont(inter(8, QFont.Weight.Bold, letter_spacing=1.2))
        l.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

        add_btn = QPushButton("+", self)
        add_btn.setGeometry(SIDEBAR_W - 28, y - 2, 18, 18)
        add_btn.setFont(inter(13, QFont.Weight.Bold))
        add_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        add_btn.setStyleSheet(
            f"QPushButton {{ background: {rgba(GREEN, 0.18)}; color: {GREEN_LIGHT}; "
            f"border: 1px solid {rgba(GREEN, 0.4)}; border-radius: 4px; }}"
            f"QPushButton:hover {{ background: {rgba(GREEN, 0.30)}; }}"
        )
        add_btn.clicked.connect(self._on_add_pallet)

        # Pallets container — rows added by _populate_pallets()
        self._pallets_container = QFrame(self)
        self._pallets_container.setGeometry(0, y + 22, SIDEBAR_W, 5 * 60)
        self._pallets_container.setStyleSheet("background: transparent;")

        # ── PALLET SETTINGS ───────────────────────────────────────────────
        ps_y = y + 22 + 5 * 60 + 12
        l = QLabel("PALLET SETTINGS", self)
        l.setGeometry(12, ps_y, 160, 14)
        l.setFont(inter(8, QFont.Weight.Bold, letter_spacing=1.2))
        l.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

        actions = [
            ("✎ Rename Pallet",  CYAN,         "#083344", self._on_rename_pallet),
            ("⊞ Edit Grid Size", PURPLE_LIGHT, "#1e1535", self._on_edit_grid),
            ("⊟ Audio Output",   GREEN,        "#052e16", self._on_audio_output),
            ("✕ Delete Pallet",  RED,          "#1f0a12", self._on_delete_pallet),
        ]
        for i, (txt, color, bg_tint, slot) in enumerate(actions):
            btn = _SidebarActionButton(txt, color, bg_tint, self)
            btn.move(8, ps_y + 22 + i * 32)
            btn.clicked.connect(slot)

        # ── OUTPUT ROUTING ────────────────────────────────────────────────
        out_y = ps_y + 22 + 4 * 32 + 14
        l = QLabel("OUTPUT ROUTING", self)
        l.setGeometry(12, out_y, 160, 14)
        l.setFont(inter(8, QFont.Weight.Bold, letter_spacing=1.2))
        l.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

        self._output_combo = QComboBox(self)
        self._output_combo.setGeometry(8, out_y + 20, SIDEBAR_W - 16, 28)
        self._output_combo.addItems([OUTPUT_LABELS[i] for i in range(1, 9)])
        self._output_combo.setCurrentIndex(2)  # Output 3 default
        self._output_combo.setFont(inter(10))
        self._output_combo.setStyleSheet(
            f"QComboBox {{ background: {BG_CARD}; color: {TEXT_SEC}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; border-radius: 5px; "
            f"padding-left: 9px; padding-right: 22px; }}"
            f"QComboBox::drop-down {{ border: none; width: 18px; }}"
            f"QComboBox::down-arrow {{ image: none; width: 0; height: 0; "
            f"border-left: 4px solid transparent; border-right: 4px solid transparent; "
            f"border-top: 5px solid {TEXT_MUTED}; margin-right: 6px; }}"
            f"QComboBox QAbstractItemView {{ background: {BG_CARD}; color: {TEXT_PRI}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; border-radius: 5px; "
            f"selection-background-color: {rgba(CYAN, 0.20)}; selection-color: {CYAN_LIGHT}; "
            f"outline: none; padding: 4px; }}"
        )
        self._output_combo.currentIndexChanged.connect(self._on_output_changed)

    # ── CENTER AREA (tabs + pads grid + control row placeholder) ────────

    def _build_center_area(self):
        # Tabs container — row of tab buttons centered horizontally above the grid
        self._tabs_container = QFrame(self)
        self._tabs_container.setGeometry(CENTER_X0, TABS_Y, CENTER_W, TABS_H)
        self._tabs_container.setStyleSheet(
            f"background: transparent; "
            f"border-bottom: 1px solid {rgba('#ffffff', 0.06)};"
        )
        self._tabs_layout = QHBoxLayout(self._tabs_container)
        self._tabs_layout.setContentsMargins(GRID_PAD_X - CENTER_X0, 0, 0, 0)
        self._tabs_layout.setSpacing(4)
        self._tabs_layout.addStretch()

        # Pads container — fixed-position children placed by _populate_pads()
        self._pads_container = QFrame(self)
        self._pads_container.setGeometry(
            GRID_PAD_X, GRID_Y,
            GRID_W_5, 6 * PAD_H + 5 * PAD_GAP,
        )
        self._pads_container.setStyleSheet("background: transparent;")

        # Bottom control row — Up | Down | Stop All | AutoGain | MixFade | Loop | Latch
        self._control_row = QFrame(self)
        self._control_row.setGeometry(
            GRID_PAD_X, GRID_Y + 6 * PAD_H + 5 * PAD_GAP + 12,
            GRID_W_5, 36,
        )
        self._control_row.setStyleSheet("background: transparent;")
        cr = QHBoxLayout(self._control_row)
        cr.setContentsMargins(0, 0, 0, 0)
        cr.setSpacing(8)

        self._up_btn = _ControlButton("▲ Up", TEXT_SEC)
        self._up_btn.clicked.connect(self._on_nav_up)
        cr.addWidget(self._up_btn)

        self._down_btn = _ControlButton("▼ Down", TEXT_SEC)
        self._down_btn.clicked.connect(self._on_nav_down)
        cr.addWidget(self._down_btn)

        self._stop_all_btn = _ControlButton("■ Stop All", RED, prominent=True)
        self._stop_all_btn.setMinimumWidth(108)
        self._stop_all_btn.clicked.connect(self._on_stop_all)
        cr.addWidget(self._stop_all_btn)

        self._autogain_btn = _ControlButton("⊕ AutoGain", AMBER)
        self._autogain_btn.clicked.connect(self._on_toggle_autogain)
        cr.addWidget(self._autogain_btn)

        self._mixfade_btn = _ControlButton("↔ MixFade", AMBER)
        self._mixfade_btn.clicked.connect(self._on_toggle_mixfade)
        cr.addWidget(self._mixfade_btn)

        self._loop_btn = _ControlButton("↺ Loop", PURPLE_LIGHT)
        self._loop_btn.clicked.connect(self._on_toggle_loop)
        cr.addWidget(self._loop_btn)

        self._latch_btn = _ControlButton("⤓ Latch", CYAN)
        self._latch_btn.clicked.connect(self._on_toggle_latch)
        cr.addWidget(self._latch_btn)

        cr.addStretch()

    # ── RIGHT PANEL — pad editor ──────────────────────────────────────────

    def _build_right_panel(self):
        self._editor = _PadEditor(self)
        self._editor.setGeometry(
            RIGHT_X, HEADER_H + 4,
            RIGHT_W, WINDOW_H - HEADER_H - STATUS_H - 8,
        )
        self._editor.label_committed.connect(self._on_editor_label)
        self._editor.color_picked.connect(self._on_editor_color)
        self._editor.output_picked.connect(self._on_editor_output)
        self._editor.volume_committed.connect(self._on_editor_volume)
        self._editor.behaviour_picked.connect(self._on_editor_behaviour)
        self._editor.assign_audio_clicked.connect(self._on_assign_audio)
        self._editor.clear_pad_clicked.connect(self._on_clear_pad)
        self._editor.test_pad_clicked.connect(self._on_test_pad)

    # ── STATUS BAR ───────────────────────────────────────────────────────

    def _build_status_bar(self):
        sb = QFrame(self)
        sb.setGeometry(0, STATUS_Y, WINDOW_W, STATUS_H)
        sb.setStyleSheet(
            f"QFrame {{ background: rgba(13,15,30,0.95); "
            f"border-top: 1px solid {rgba('#ffffff', 0.06)}; }}"
        )

        # Three pill badges, left-aligned. Children of `sb`, not `self`,
        # so y is relative to the status bar frame (sits at y=STATUS_Y).
        def _pill(x, text, fg, bg, w=110):
            p = QLabel(text, sb)
            p.setGeometry(x, 6, w, 20)
            p.setFont(inter(9, QFont.Weight.Bold, letter_spacing=1.0))
            p.setStyleSheet(
                f"QLabel {{ background: {bg}; color: {fg}; "
                f"border-radius: 10px; padding-left: 10px; }}"
            )
            return p

        _pill(12,  "● AUTO MODE",   PURPLE_LIGHT, rgba(PURPLE, 0.18))
        _pill(130, "● LIVE READY",  GREEN_LIGHT,  rgba(GREEN,  0.18))
        self._status_count = _pill(
            248, "0 Instant Jingles",
            AMBER_LIGHT, rgba(AMBER, 0.18), w=140,
        )

        # Right side — version + Open Studio mini (also children of sb)
        version = QLabel("Instant Jingles  ·  RadioAI Studio v2.0", sb)
        version.setGeometry(WINDOW_W - 380, 8, 270, 16)
        version.setFont(inter(9))
        version.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        version.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        os_btn = QPushButton("▶  Open Studio", sb)
        os_btn.setGeometry(WINDOW_W - 100, 4, 88, 24)
        os_btn.setFont(inter(10, QFont.Weight.Bold))
        os_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        os_btn.setStyleSheet(
            f"QPushButton {{ background: {rgba(GREEN, 0.18)}; color: {GREEN_LIGHT}; "
            f"border: 1px solid {rgba(GREEN, 0.4)}; border-radius: 5px; }}"
            f"QPushButton:hover {{ background: {rgba(GREEN, 0.30)}; }}"
        )
        os_btn.clicked.connect(self.studio_clicked.emit)

    # ── DATA ─────────────────────────────────────────────────────────────

    def _load_pallets(self):
        try:
            rows = self._db.get_pallets()
            self._pallets = [self._pallet_row_to_dict(r) for r in rows]
        except Exception as exc:
            log.error(f"get_pallets failed: {exc}")
            self._pallets = []
        self._populate_pallets()
        self._populate_tabs()
        if self._pallets:
            self._select_pallet(self._pallets[0]["id"])

    def _pallet_row_to_dict(self, r) -> dict:
        return {
            "id":           r["id"],
            "name":         r["name"] or "",
            "owner":        r["owner"] if "owner" in r.keys() else "",
            "grid_cols":    int(r["grid_cols"] or 5),
            "grid_rows":    int(r["grid_rows"] or 6),
            "audio_output": int(r["audio_output"] or 3),
            "pad_count":    int(r["pad_count"] or 0) if "pad_count" in r.keys() else 0,
            "filled_count": int(r["filled_count"] or 0) if "filled_count" in r.keys() else 0,
        }

    def _pad_row_to_dict(self, r) -> dict:
        keys = r.keys()
        return {
            "id":          r["id"],
            "pallet_id":   r["pallet_id"],
            "pad_index":   int(r["pad_index"] or 0),
            "label":       r["label"] or "",
            "file_path":   r["file_path"] if "file_path" in keys else None,
            "duration_ms": int(r["duration_ms"] or 0),
            "color":       r["color"] or "#06b6d4",
            "volume":      int(r["volume"] or 100),
            "behaviour":   r["behaviour"] or "play_once",
            "play_count":  int(r["play_count"] or 0) if "play_count" in keys else 0,
            "last_played": r["last_played"] if "last_played" in keys else None,
        }

    def _populate_pallets(self):
        # Remove old
        for w in self._pallet_rows:
            w.setParent(None); w.deleteLater()
        self._pallet_rows.clear()
        # Add new — stacked inside _pallets_container at y=i*60
        for i, pallet in enumerate(self._pallets):
            row = _PalletRow(pallet, self._pallets_container)
            row.move(0, i * 60)
            row.clicked.connect(self._select_pallet)
            row.show()
            self._pallet_rows.append(row)

    def _populate_tabs(self):
        # Clear old
        for t in self._tabs:
            t.setParent(None); t.deleteLater()
        self._tabs.clear()
        # Insert before the trailing addStretch
        for pallet in self._pallets:
            tab = _PalletTab(pallet, self._tabs_container)
            tab.clicked.connect(
                lambda _checked=False, pid=pallet["id"]: self._select_pallet(pid)
            )
            self._tabs_layout.insertWidget(self._tabs_layout.count() - 1, tab)
            self._tabs.append(tab)

    def _select_pallet(self, pallet_id: int):
        self._selected_pallet_id = int(pallet_id)
        self.pallet_changed.emit(int(pallet_id))
        # Update sidebar highlights
        for r in self._pallet_rows:
            r.set_selected(r._pallet.get("id") == pallet_id)
        # Update tab highlights
        for t in self._tabs:
            t.set_active(t.pallet_id == pallet_id)
        # Update output combo to this pallet's saved output
        pallet = next((p for p in self._pallets if p["id"] == pallet_id), None)
        if pallet and self._output_combo:
            self._output_combo.blockSignals(True)
            self._output_combo.setCurrentIndex(
                max(0, min(7, pallet.get("audio_output", 3) - 1))
            )
            self._output_combo.blockSignals(False)
        # Load this pallet's pads
        self._load_pads(pallet_id)

    def _load_pads(self, pallet_id: int):
        try:
            rows = self._db.get_pads(pallet_id)
            self._pads = [self._pad_row_to_dict(r) for r in rows]
        except Exception as exc:
            log.error(f"get_pads({pallet_id}) failed: {exc}")
            self._pads = []
        self._populate_pads()
        self._update_status_count()

    def _populate_pads(self):
        # Remove old
        for w in self._pads_widgets:
            w.setParent(None); w.deleteLater()
        self._pads_widgets.clear()

        pallet = next((p for p in self._pallets
                       if p["id"] == self._selected_pallet_id), None)
        if not pallet:
            return
        cols = pallet.get("grid_cols", 5)
        rows_n = pallet.get("grid_rows", 6)

        # Re-center the grid for non-default sizes
        grid_w = cols * PAD_W + (cols - 1) * PAD_GAP
        offset_x = (CENTER_W - grid_w) // 2 - (GRID_PAD_X - CENTER_X0)
        if offset_x < 0:
            offset_x = 0

        # Build grid by pad_index
        index_to_pad = {p["pad_index"]: p for p in self._pads}
        for r in range(rows_n):
            for c in range(cols):
                pad_index = r * cols + c + 1
                pad = index_to_pad.get(pad_index)
                if not pad:
                    continue
                w = _Pad(pad, self._pads_container)
                w.move(
                    offset_x + c * (PAD_W + PAD_GAP),
                    r * (PAD_H + PAD_GAP),
                )
                w.show()
                w.left_clicked.connect(self._on_pad_left_clicked)
                w.right_clicked.connect(self._on_pad_right_clicked)
                self._pads_widgets.append(w)

        # Auto-select the first non-empty pad in the new pallet
        first = next((p for p in self._pads_widgets if not p.is_empty), None)
        if first:
            self._select_pad(first.pad_id)

    def _select_pad(self, pad_id: int):
        self._selected_pad_id = int(pad_id)
        for w in self._pads_widgets:
            w.set_selected(w.pad_id == pad_id)
        self.pad_selected.emit(int(pad_id))

    def _update_status_count(self):
        """Show TOTAL filled pads across ALL pallets (broadcast-ready jingles).
        Filled = has a file_path. Labels alone don't count — a pad with no
        audio is just UI scaffolding, not a usable jingle."""
        if not self._status_count:
            return
        try:
            row = self._db._conn().execute(
                "SELECT COUNT(*) FROM jingle_pads "
                "WHERE file_path IS NOT NULL AND file_path != ''"
            ).fetchone()
            total = int(row[0]) if row else 0
        except Exception:
            total = 0
        self._status_count.setText(f"{total} Instant Jingles")

    # ── PAD CLICKS — left = play, right = edit ───────────────────────────

    def _on_pad_left_clicked(self, pad_id: int):
        """Left-click semantics:
          - latched pad: toggle stop
          - empty pad:  red-flash + log (no toast — non-disruptive)
          - normal pad: play through engine, record stats
        """
        pad = self._find_pad(pad_id)
        if not pad:
            return
        self._select_pad(pad_id)

        # Latch toggle — second click stops
        if pad_id in self._latched_pads:
            if self._engine:
                self._engine.stop_pad(pad_id)
            self._latched_pads.discard(pad_id)
            return

        file_path = pad.get("file_path")
        if not file_path:
            log.info(f"[pad {pad_id}] no audio assigned — flashing")
            self._flash_pad_red(pad_id)
            return

        if not self._engine:
            log.error("engine unavailable — cannot play")
            return

        beh = pad.get("behaviour") or "play_once"
        loop = (beh == "loop")
        ok = self._engine.play_pad(
            pad_id,
            file_path,
            volume=int(pad.get("volume") or 100),
            loop=loop,
        )
        if not ok:
            self._flash_pad_red(pad_id)
            return

        # Track latched pads — they only stop on second click or stop_all
        if beh == "latch":
            self._latched_pads.add(pad_id)

        # Record analytics
        try:
            self._db.record_pad_play(pad_id)
        except Exception as exc:
            log.error(f"record_pad_play failed: {exc}")

        self.pad_played.emit(int(pad_id), file_path)

    def _on_pad_right_clicked(self, pad_id: int):
        self._select_pad(pad_id)
        self._refresh_editor()

    def _flash_pad_red(self, pad_id: int):
        """Subtle non-modal feedback when DJ presses an empty/broken pad —
        the pad widget tints red briefly, then restores. Avoids QMessageBox
        which would be disruptive during a live broadcast."""
        widget = next((w for w in self._pads_widgets if w.pad_id == pad_id),
                      None)
        if not widget:
            return
        original_color = widget._pad.get("color")
        widget._pad["color"] = "#dc2626"
        widget.update()

        def _restore():
            widget._pad["color"] = original_color
            widget.update()
        QTimer.singleShot(500, _restore)

    # ── PALLET ACTIONS (sidebar) ─────────────────────────────────────────

    def _on_add_pallet(self):
        name = dialogs.text_input(
            self, "Add pallet", "Pallet name:",
            placeholder="My Pallet")
        if not name or not name.strip():
            return
        try:
            new_id = self._db.add_pallet({
                "name": name.strip(),
                "owner": "",
                "grid_cols": 5, "grid_rows": 6,
                "audio_output": 3,
                "display_order": len(self._pallets),
            })
            # Seed empty pads matching the default 5×6 grid
            for idx in range(1, 31):
                self._db.add_pad({
                    "pallet_id": new_id, "pad_index": idx,
                    "label": "", "color": "#f59e0b",
                })
            self._load_pallets()
            self._select_pallet(new_id)
            self._emit_pads_changed()
        except Exception as exc:
            log.error(f"add pallet failed: {exc}")
            dialogs.error(self, "Add failed", str(exc))

    def _on_rename_pallet(self):
        if not self._selected_pallet_id:
            return
        cur = next((p for p in self._pallets
                    if p["id"] == self._selected_pallet_id), None)
        if not cur:
            return
        new_name = dialogs.text_input(
            self, "Rename pallet", "New name:",
            default=cur["name"])
        if not new_name or not new_name.strip():
            return
        try:
            self._db.update_pallet(self._selected_pallet_id,
                                   {"name": new_name.strip()})
            self._load_pallets()
            self._select_pallet(self._selected_pallet_id)
            self._emit_pads_changed()
        except Exception as exc:
            log.error(f"rename pallet failed: {exc}")
            dialogs.error(self, "Rename failed", str(exc))

    def _on_edit_grid(self):
        # TODO: open a dialog to edit grid_cols × grid_rows. For now just log.
        log.info(f"edit grid for pallet {self._selected_pallet_id} — TBD")

    def _on_audio_output(self):
        # The output dropdown lives in the sidebar and updates live, so this
        # button is purely a focus shortcut. Future: open a routing matrix.
        if self._output_combo:
            self._output_combo.setFocus()
            self._output_combo.showPopup()

    def _on_delete_pallet(self):
        if not self._selected_pallet_id:
            return
        if len(self._pallets) <= 1:
            dialogs.info(
                self, "Cannot delete",
                "You must keep at least one pallet.")
            return
        cur = next((p for p in self._pallets
                    if p["id"] == self._selected_pallet_id), None)
        if not cur:
            return
        if not dialogs.confirm(
                self, "Delete pallet",
                f"Delete the '{cur['name']}' pallet?\n\n"
                f"All {cur.get('pad_count', 0)} pad slots will be "
                f"removed.",
                danger=True, yes_label="Delete"):
            return
        try:
            self._db.delete_pallet(self._selected_pallet_id)
            self._selected_pallet_id = None
            self._load_pallets()
            self._emit_pads_changed()
        except Exception as exc:
            log.error(f"delete pallet failed: {exc}")
            dialogs.error(self, "Delete failed", str(exc))

    def _on_output_changed(self, idx: int):
        if not self._selected_pallet_id:
            return
        try:
            self._db.update_pallet(self._selected_pallet_id,
                                   {"audio_output": idx + 1})
            log.info(
                f"pallet {self._selected_pallet_id} output → {idx + 1} "
                f"({OUTPUT_LABELS[idx + 1]})"
            )
            self._emit_pads_changed()
        except Exception as exc:
            log.error(f"update_pallet output failed: {exc}")

    # ── EDITOR change handlers (DB writes happen here) ───────────────────

    def _emit_pads_changed(self) -> None:
        """Notify external listeners (MainWindow → Studio) that something
        in jingle_pads / jingle_pallets just changed. Defensive try/except
        so a stale Studio listener can't take this screen down."""
        try:
            self.pads_changed.emit()
        except Exception as exc:
            log.debug(f"pads_changed emit failed: {exc}")

    def _refresh_editor(self):
        """Re-populate the editor with the currently-selected pad."""
        if not self._editor:
            return
        if not self._selected_pad_id:
            self._editor.set_pad(None)
            return
        pad = self._find_pad(self._selected_pad_id)
        if not pad:
            self._editor.set_pad(None)
            return
        try:
            stats = self._db.get_pad_play_stats(self._selected_pad_id, days=7)
        except Exception as exc:
            log.error(f"pad stats failed: {exc}")
            stats = None
        # Use the pallet's saved output as the default for this pad's editor
        pallet = next((p for p in self._pallets
                       if p["id"] == self._selected_pallet_id), None)
        out = pallet.get("audio_output", 3) if pallet else 3
        self._editor.set_pad(pad, stats=stats, output=out)

    def _on_editor_label(self, pad_id: int, new_label: str):
        try:
            self._db.update_pad(pad_id, {"label": new_label})
            log.info(f"[pad {pad_id}] label → '{new_label}'")
        except Exception as exc:
            log.error(f"update_pad label failed: {exc}")
            return
        # Refresh the cached row + repaint the grid widget
        pad = self._find_pad(pad_id)
        if pad:
            pad["label"] = new_label
        self._repaint_pad(pad_id)
        self._update_status_count()
        self._emit_pads_changed()

    def _on_editor_color(self, pad_id: int, hex_color: str):
        try:
            self._db.update_pad(pad_id, {"color": hex_color})
            log.info(f"[pad {pad_id}] color → {hex_color}")
        except Exception as exc:
            log.error(f"update_pad color failed: {exc}")
            return
        pad = self._find_pad(pad_id)
        if pad:
            pad["color"] = hex_color
        self._repaint_pad(pad_id)
        self._emit_pads_changed()

    def _on_editor_output(self, pad_id: int, output: int):
        # Per-pad output not stored in jingle_pads (column doesn't exist);
        # save it as the pallet output for now. TODO: per-pad routing column.
        if self._selected_pallet_id:
            self._on_output_changed(output - 1)

    def _on_editor_volume(self, pad_id: int, volume: int):
        try:
            self._db.update_pad(pad_id, {"volume": volume})
            log.info(f"[pad {pad_id}] volume → {volume}%")
        except Exception as exc:
            log.error(f"update_pad volume failed: {exc}")
            return
        pad = self._find_pad(pad_id)
        if pad:
            pad["volume"] = volume
        self._emit_pads_changed()

    def _on_editor_behaviour(self, pad_id: int, behaviour: str):
        try:
            self._db.update_pad(pad_id, {"behaviour": behaviour})
            log.info(f"[pad {pad_id}] behaviour → {behaviour}")
        except Exception as exc:
            log.error(f"update_pad behaviour failed: {exc}")
            return
        pad = self._find_pad(pad_id)
        if pad:
            pad["behaviour"] = behaviour
        self._emit_pads_changed()

    def _on_assign_audio(self, pad_id: int):
        """File picker → store path + auto-detected duration into the pad."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Assign audio file",
            "",
            "Audio files (*.mp3 *.wav *.ogg *.flac *.m4a *.aac);;All files (*.*)",
        )
        if not path:
            return
        # Probe duration via the engine (BASS prescan)
        duration_ms = 0
        if self._engine:
            try:
                duration_ms = self._engine.get_duration_ms(path) or 0
            except Exception as exc:
                log.warning(f"could not probe duration: {exc}")
        try:
            self._db.assign_audio_to_pad(pad_id, path, duration_ms)
            log.info(
                f"[pad {pad_id}] audio → {path} "
                f"({duration_ms}ms)"
            )
        except Exception as exc:
            log.error(f"assign_audio_to_pad failed: {exc}")
            dialogs.error(self, "Assign failed", str(exc))
            return
        # Refresh data + UI
        self._load_pads(self._selected_pallet_id)
        self._select_pad(pad_id)
        self._refresh_editor()
        self._emit_pads_changed()

    def _on_clear_pad(self, pad_id: int):
        if not dialogs.confirm(
                self, "Clear pad",
                "Remove the audio assignment from this pad?\n\n"
                "The slot itself stays — color and behaviour are "
                "preserved.",
                yes_label="Clear"):
            return
        try:
            self._db.clear_pad(pad_id)
            log.info(f"[pad {pad_id}] cleared")
        except Exception as exc:
            log.error(f"clear_pad failed: {exc}")
            return
        self._load_pads(self._selected_pallet_id)
        self._select_pad(pad_id)
        self._refresh_editor()
        self._emit_pads_changed()

    def _on_test_pad(self, pad_id: int):
        """Plays through the pad's configured output. TODO: route to monitor
        output (output 7) instead of main when BASS multi-device is wired."""
        pad = self._find_pad(pad_id)
        if not pad:
            return
        file_path = pad.get("file_path")
        if not file_path or not self._engine:
            self._flash_pad_red(pad_id)
            return
        log.info(f"[pad {pad_id}] TEST/PREVIEW (TODO: route to monitor)")
        self._engine.play_pad(
            pad_id, file_path,
            volume=int(pad.get("volume") or 100),
            loop=False,
        )

    # ── CONTROL ROW ──────────────────────────────────────────────────────

    def _on_stop_all(self):
        if self._engine:
            n = self._engine.stop_all()
            log.warning(f"[STOP ALL] killed {n} channel(s)")
        self._latched_pads.clear()
        for w in self._pads_widgets:
            w.set_playing(False)

    def _on_toggle_loop(self):
        """Set the selected pad's behaviour to 'loop' (or back to 'play_once')."""
        if not self._selected_pad_id:
            return
        pad = self._find_pad(self._selected_pad_id)
        if not pad:
            return
        new_beh = "play_once" if pad.get("behaviour") == "loop" else "loop"
        self._on_editor_behaviour(self._selected_pad_id, new_beh)
        self._loop_btn.set_toggled(new_beh == "loop")
        self._latch_btn.set_toggled(False)
        self._refresh_editor()

    def _on_toggle_latch(self):
        if not self._selected_pad_id:
            return
        pad = self._find_pad(self._selected_pad_id)
        if not pad:
            return
        new_beh = "play_once" if pad.get("behaviour") == "latch" else "latch"
        self._on_editor_behaviour(self._selected_pad_id, new_beh)
        self._latch_btn.set_toggled(new_beh == "latch")
        self._loop_btn.set_toggled(False)
        self._refresh_editor()

    def _on_toggle_autogain(self):
        # TODO: AutoGain — normalize all pad volumes to a common LUFS target.
        # Requires per-pad RMS analysis at assign time. Visual stub for now.
        self._autogain_on = not self._autogain_on
        self._autogain_btn.set_toggled(self._autogain_on)
        log.warning(f"[AutoGain] visual toggle = {self._autogain_on} "
                    f"(not yet implemented)")

    def _on_toggle_mixfade(self):
        # TODO: MixFade — crossfade between pads instead of hard-cutting.
        # Needs envelope automation in the engine. Visual stub for now.
        self._mixfade_on = not self._mixfade_on
        self._mixfade_btn.set_toggled(self._mixfade_on)
        log.warning(f"[MixFade] visual toggle = {self._mixfade_on} "
                    f"(not yet implemented)")

    # ── KEYBOARD NAV (Up/Down/Left/Right move selected pad) ──────────────

    def _on_nav_up(self):     self._move_selection(0, -1)
    def _on_nav_down(self):   self._move_selection(0,  1)
    def _on_nav_left(self):   self._move_selection(-1, 0)
    def _on_nav_right(self):  self._move_selection( 1, 0)

    def _move_selection(self, dx: int, dy: int):
        pallet = next((p for p in self._pallets
                       if p["id"] == self._selected_pallet_id), None)
        if not pallet or not self._selected_pad_id:
            return
        cols = pallet.get("grid_cols", 5)
        cur = self._find_pad(self._selected_pad_id)
        if not cur:
            return
        idx = int(cur.get("pad_index") or 1) - 1
        r, c = divmod(idx, cols)
        rows = pallet.get("grid_rows", 6)
        new_r = max(0, min(rows - 1, r + dy))
        new_c = max(0, min(cols - 1, c + dx))
        new_idx = new_r * cols + new_c + 1
        target = next((p for p in self._pads
                       if p.get("pad_index") == new_idx), None)
        if target:
            self._select_pad(target["id"])
            self._refresh_editor()

    # ── ENGINE callbacks (visual sync) ───────────────────────────────────

    def _on_engine_started(self, pad_id: int):
        for w in self._pads_widgets:
            if w.pad_id == pad_id:
                w.set_playing(True)
                break

    def _on_engine_ended(self, pad_id: int):
        for w in self._pads_widgets:
            if w.pad_id == pad_id:
                w.set_playing(False)
                break

    def _on_engine_stopped(self, pad_id: int):
        for w in self._pads_widgets:
            if w.pad_id == pad_id:
                w.set_playing(False)
                break
        self._latched_pads.discard(pad_id)

    # ── small helpers ────────────────────────────────────────────────────

    def _find_pad(self, pad_id: int) -> Optional[dict]:
        return next((p for p in self._pads if p["id"] == pad_id), None)

    def _repaint_pad(self, pad_id: int):
        for w in self._pads_widgets:
            if w.pad_id == pad_id:
                # Re-bind the dict so the widget paints fresh values
                pad = self._find_pad(pad_id)
                if pad:
                    w._pad = pad
                w.update()
                break

    def _tick(self):
        from datetime import datetime
        if self._clock_lbl:
            self._clock_lbl.setText(datetime.now().strftime("%H:%M:%S"))
