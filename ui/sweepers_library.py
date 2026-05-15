"""
RadioAI Studio Pro — Sweepers Library
Pixel-accurate match of Figma node 46:2 (file 7oN9K61g94wKx3nu44KKDF).

Layout (1440×900):
  Header           y=0..72         Logo, breadcrumb, title, clock, Open Studio
  Sidebar          y=72..850, x=0..220       Counter + actions + position filter +
                                              integration links
  Table area       y=72..850, x=220..980     Header strip + scrollable rows +
                                              "How Sweeper Positions Work" + scrubber
  Right details    y=72..850, x=982..1440    Sweeper details card + form + position
                                              settings list
  Status bar       y=850..900, 1440×50       Pills + version + Open Studio mini

Backend: existing `sweepers` schema (id, name, category, file_path, duration_ms,
position, properties, playlister_code, is_enabled). No migration needed for this
screen. `last_used` falls back to "—" until broadcast_log lookup is wired (TODO).

Phase status:
  [✓] header / sidebar / table / details panel / how-positions / status bar
  [ ] + Add New → opens 108:2 dialog (deferred — separate session)
  [ ] Mass Import / Edit Categories / Delete / Export to Playlister (toast stubs)
  [ ] Audio scrubber wires to AudioEngine for actual preview (toast stub for now)
  [ ] last_used pulls from broadcast_log
"""

from __future__ import annotations

import logging
from typing import Optional
from datetime import datetime
from core import dialogs

from PyQt6.QtCore import (
    Qt, QRectF, QTimer, QPropertyAnimation, pyqtProperty, pyqtSignal,
)
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QLinearGradient, QPainterPath, QFont,
    QCursor, QFontMetrics,
)
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QHBoxLayout, QVBoxLayout,
    QScrollArea, QMessageBox,
)

from core.settings import Settings
from ui.widgets._tokens import (
    inter, mono, rgba,
    BG_BASE, BG_PANEL, BG_CARD, BG_ELEVATED,
    TEXT_PRI, TEXT_SEC, TEXT_MUTED, TEXT_DIM,
    CYAN, CYAN_LIGHT, PURPLE, PURPLE_LIGHT, PURPLE_DARK, GREEN, GREEN_LIGHT,
    AMBER, AMBER_LIGHT, RED, RED_LIGHT, PINK, PINK_LIGHT, TEAL, TEAL_LIGHT,
)

log = logging.getLogger("SweepersLibrary")


# ════════════════════════════════════════════════════════════════════════════
# Geometry tokens
# ════════════════════════════════════════════════════════════════════════════

WINDOW_W = 1440
WINDOW_H = 900
HEADER_H = 72
STATUS_H = 50

SIDEBAR_W = 220

TABLE_X0 = 220
TABLE_W  = 760
TABLE_X1 = TABLE_X0 + TABLE_W              # 980

RIGHT_X = 982
RIGHT_W = WINDOW_W - RIGHT_X               # 458

ROW_H        = 38
TABLE_HDR_H  = 32

# Vertical layout inside the center column
# (relative to the table area: y0=HEADER_H)
TABLE_BODY_H        = 200      # 5 rows × 38 + headroom
HOW_POSITIONS_Y_REL = TABLE_HDR_H + TABLE_BODY_H + 8   # ~240
HOW_POSITIONS_H     = 200
SCRUBBER_H          = 50       # bottom of center column


POSITION_OPTIONS = [
    "All Positions",
    "Start of Song",
    "Before Intro",
    "Before End",
    "Bridge at End",
    "Independent",
    "Custom Position",
]


CATEGORY_COLORS = {
    "Station":   PURPLE_LIGHT,
    "Music":     CYAN,
    "News":      AMBER,
    "Promo":     PINK,
    "Weather":   TEAL_LIGHT,
    "Traffic":   AMBER_LIGHT,
    "Sports":    GREEN,
    "Custom":    TEXT_SEC,
}

POSITION_COLORS = {
    "Start of Song":   CYAN,
    "Before Intro":    AMBER,
    "Before End":      AMBER_LIGHT,
    "Bridge at End":   RED_LIGHT,
    "Independent":     PURPLE_LIGHT,
    "Custom Position": TEXT_SEC,
}


def _fmt_duration(ms: int) -> str:
    s = int((ms or 0) // 1000)
    return f"{s // 60}:{s % 60:02d}"


def _category_color(name: str) -> str:
    return CATEGORY_COLORS.get((name or "").strip(), TEXT_MUTED)


def _position_color(name: str) -> str:
    return POSITION_COLORS.get((name or "").strip(), TEXT_MUTED)


# ════════════════════════════════════════════════════════════════════════════
# Header chrome (replicated locally — see TODO in ui/spots_commercials.py for
# the planned ui/widgets/library_chrome.py extraction)
# ════════════════════════════════════════════════════════════════════════════

class _HeaderLogo(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(40, 40)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, 40, 40), 10, 10)
        p.setClipPath(path)
        g = QLinearGradient(0, 0, 40, 40)
        g.setColorAt(0.0,   QColor("#a78bfa"))
        g.setColorAt(0.355, QColor("#7c3aed"))
        g.setColorAt(0.711, QColor("#5b21b6"))
        p.fillRect(QRectF(0, 0, 40, 40), QBrush(g))
        p.setBrush(QColor(255, 255, 255, 235))
        p.setPen(Qt.PenStyle.NoPen)
        for x, h in [(7, 6), (14, 11), (20, 18), (26, 11), (33, 6)]:
            top = (40 - h) // 2
            p.drawRoundedRect(QRectF(x - 1.5, top, 3, h), 1.5, 1.5)


class _HeaderOpenStudio(QPushButton):
    def __init__(self, parent=None):
        super().__init__("", parent)
        self.setFixedSize(204, 38)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFlat(True)
        self.setStyleSheet("background: transparent; border: none;")

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0.5, 0.5, 203, 37)
        path = QPainterPath()
        path.addRoundedRect(rect, 8, 8)
        p.setClipPath(path)
        g = QLinearGradient(0, 0, 204, 38)
        c1 = QColor(GREEN); c1.setAlphaF(0.10)
        c2 = QColor(GREEN); c2.setAlphaF(0.04)
        g.setColorAt(0.0, c1); g.setColorAt(1.0, c2)
        p.fillRect(QRectF(0, 0, 204, 38), QBrush(g))
        p.setClipping(False)
        bc = QColor(GREEN); bc.setAlphaF(0.30)
        p.setPen(QPen(bc, 1)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 8, 8)
        p.setPen(QColor(GREEN))
        p.setFont(inter(12, QFont.Weight.Bold))
        p.drawText(12, 0, 16, 38,
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "▶")
        p.setFont(inter(11, QFont.Weight.Bold))
        p.drawText(28, 4, 170, 16,
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   "Open Studio")
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(inter(8))
        p.drawText(28, 22, 170, 12,
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   "Billie Eilish — Bury A Friend")


class _ActiveBreadcrumbChip(QFrame):
    """〜 Sweepers chip — pink-tinted with pulsing glyph (sweepers accent)."""

    def __init__(self, text: str = "Sweepers", parent=None):
        super().__init__(parent)
        self._text = text
        self._dot_alpha = 1.0
        self.setFixedSize(118, 32)
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
        rect = QRectF(0.5, 0.5, 117, 31)
        path = QPainterPath()
        path.addRoundedRect(rect, 16, 16)
        p.setClipPath(path)
        c1 = QColor(PINK); c1.setAlphaF(0.20)
        c2 = QColor(PINK); c2.setAlphaF(0.06)
        g = QLinearGradient(0, 0, 0, 32)
        g.setColorAt(0.0, c1); g.setColorAt(1.0, c2)
        p.fillRect(QRectF(0, 0, 118, 32), QBrush(g))
        p.setClipping(False)
        bc = QColor(PINK); bc.setAlphaF(0.35)
        p.setPen(QPen(bc, 1)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 16, 16)
        glow = QColor(PINK_LIGHT); glow.setAlphaF(self._dot_alpha)
        p.setPen(glow)
        p.setFont(inter(14, QFont.Weight.Black))
        p.drawText(QRectF(10, 0, 18, 32),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   "〜")
        p.setPen(QColor(PINK_LIGHT))
        p.setFont(inter(11, QFont.Weight.Bold))
        p.drawText(QRectF(30, 0, 84, 32),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   self._text)


# ════════════════════════════════════════════════════════════════════════════
# Sidebar widgets
# ════════════════════════════════════════════════════════════════════════════

class _SidebarCounter(QFrame):
    """'3/3 sweepers' green box."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._active = 0
        self._total = 0
        self.setFixedSize(SIDEBAR_W - 24, 38)

    def set_counts(self, active: int, total: int):
        self._active, self._total = int(active), int(total)
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        rect = QRectF(0.5, 0.5, w - 1, h - 1)
        path = QPainterPath(); path.addRoundedRect(rect, 6, 6)
        p.setClipPath(path)
        bg = QColor(GREEN); bg.setAlphaF(0.12)
        p.fillRect(rect, bg)
        p.setClipping(False)
        bc = QColor(GREEN); bc.setAlphaF(0.30)
        p.setPen(QPen(bc, 1)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 6, 6)
        p.fillRect(QRectF(0, 0, 3, h), QColor(GREEN))
        p.setPen(QColor(GREEN_LIGHT))
        p.setFont(mono(15, bold=True))
        p.drawText(QRectF(10, 4, w - 14, 18),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   f"{self._active}/{self._total}")
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(inter(8, QFont.Weight.Bold, letter_spacing=1.0))
        p.drawText(QRectF(10, 22, w - 14, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "SWEEPERS")


class _SidebarActionButton(QPushButton):
    """Sidebar action button — full-width with left accent + label."""

    def __init__(self, text: str, color: str, bg_tint: str, parent=None):
        super().__init__(text, parent)
        self._color = QColor(color)
        self._bg_tint = QColor(bg_tint)
        self._hover = False
        self.setFixedSize(SIDEBAR_W - 24, 30)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFlat(True)
        self.setStyleSheet("background: transparent; border: none;")
        self.setFont(inter(10, QFont.Weight.Bold))

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        rect = QRectF(0, 0, w, h)
        path = QPainterPath(); path.addRoundedRect(rect, 5, 5)
        p.setClipPath(path)
        if self._hover:
            c = QColor(self._color); c.setAlphaF(0.16)
            p.fillRect(rect, self._bg_tint); p.fillRect(rect, c)
        else:
            p.fillRect(rect, self._bg_tint)
        p.fillRect(0, 0, 2, h, self._color)
        p.setClipping(False)
        bc = QColor(self._color); bc.setAlphaF(0.30)
        p.setPen(QPen(bc, 1)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 5, 5)
        p.setPen(self._color)
        p.setFont(self.font())
        p.drawText(10, 0, w - 14, h,
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self.text())

    def enterEvent(self, e): self._hover = True;  self.update(); super().enterEvent(e)
    def leaveEvent(self, e): self._hover = False; self.update(); super().leaveEvent(e)


class _PositionFilterRow(QPushButton):
    """One filter row — full-width pill, click toggles selection."""

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self._text = text
        self._active = False
        self._hover = False
        self.setFixedSize(SIDEBAR_W - 24, 28)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFlat(True)
        self.setStyleSheet("background: transparent; border: none;")

    def set_active(self, active: bool):
        self._active = bool(active)
        self.update()

    def enterEvent(self, e): self._hover = True;  self.update(); super().enterEvent(e)
    def leaveEvent(self, e): self._hover = False; self.update(); super().leaveEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        rect = QRectF(0.5, 0.5, w - 1, h - 1)
        path = QPainterPath(); path.addRoundedRect(rect, 5, 5)
        p.setClipPath(path)
        if self._active:
            tint = QColor(CYAN); tint.setAlphaF(0.16)
            p.fillRect(rect, tint)
            p.setClipping(False)
            bc = QColor(CYAN); bc.setAlphaF(0.45)
            p.setPen(QPen(bc, 1)); p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(rect, 5, 5)
            p.setPen(QColor(CYAN_LIGHT))
        else:
            p.fillRect(rect, QColor("#0a0c18"))
            if self._hover:
                p.fillRect(rect, QColor(255, 255, 255, 8))
            p.setClipping(False)
            p.setPen(QPen(QColor(rgba("#ffffff", 0.06)), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(rect, 5, 5)
            p.setPen(QColor(TEXT_SEC if self._hover else TEXT_MUTED))
        p.setFont(inter(10, QFont.Weight.DemiBold if self._active
                                   else QFont.Weight.Medium))
        p.drawText(QRectF(10, 0, w - 28, h),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._text)
        # Right chevron
        p.setPen(QColor(TEXT_DIM))
        p.setFont(inter(9))
        p.drawText(QRectF(w - 18, 0, 12, h),
                   Qt.AlignmentFlag.AlignCenter, "⌄")


# ════════════════════════════════════════════════════════════════════════════
# Sweeper table widgets
# ════════════════════════════════════════════════════════════════════════════

class _Pill(QWidget):
    """Lightweight rounded badge — used for category, position, properties."""

    def __init__(self, text: str, color: str, parent=None):
        super().__init__(parent)
        self._text = text
        self._color = QColor(color)
        fm = QFontMetrics(inter(9, QFont.Weight.Bold, letter_spacing=0.5))
        w = max(64, fm.horizontalAdvance(text) + 18)
        self.setFixedSize(w, 20)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0, 0, self.width(), self.height())
        bg = QColor(self._color); bg.setAlphaF(0.18)
        p.setBrush(bg); p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(rect, 6, 6)
        p.setPen(self._color)
        p.setFont(inter(9, QFont.Weight.Bold, letter_spacing=0.5))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._text)


class _SweeperRow(QFrame):
    """One row in the sweepers table."""

    clicked = pyqtSignal(int)         # sweeper_id
    double_clicked = pyqtSignal(int)

    def __init__(self, sweeper: dict, row_index: int, parent=None):
        super().__init__(parent)
        self._sweeper = sweeper
        self._row_index = row_index
        self._selected = False
        self._hover = False
        self.setFixedHeight(ROW_H)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._build_pills()

    def _build_pills(self):
        pos = self._sweeper.get("position") or "—"
        cat = self._sweeper.get("category") or "—"
        props = self._sweeper.get("properties") or "Regular"
        self._pos_pill = _Pill(pos, _position_color(pos), self)
        self._cat_pill = _Pill(cat, _category_color(cat), self)
        self._props_pill = _Pill(props, TEXT_SEC, self)

    def set_selected(self, sel: bool):
        self._selected = sel
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(int(self._sweeper.get("id", 0)))
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit(int(self._sweeper.get("id", 0)))
        super().mouseDoubleClickEvent(e)

    def enterEvent(self, e): self._hover = True;  self.update(); super().enterEvent(e)
    def leaveEvent(self, e): self._hover = False; self.update(); super().leaveEvent(e)

    @staticmethod
    def _column_xs(total_w: int) -> list[int]:
        # Column starts: name | position | duration | category | properties | last_used
        return [
            36,                   # name (after status dot)
            int(total_w * 0.40),  # position
            int(total_w * 0.55),  # duration
            int(total_w * 0.66),  # category
            int(total_w * 0.78),  # properties
            int(total_w * 0.88),  # last used
        ]

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        rect = QRectF(0, 0, w, ROW_H)

        if self._selected:
            tint = QColor(CYAN); tint.setAlphaF(0.14)
            p.fillRect(rect, tint)
            p.fillRect(QRectF(0, 0, 3, ROW_H), QColor(CYAN))
        else:
            zebra = "#0d0f1c" if self._row_index % 2 else "#0a0c18"
            p.fillRect(rect, QColor(zebra))
            if self._hover:
                p.fillRect(rect, QColor(255, 255, 255, 8))

        # Status dot at x=14
        is_enabled = bool(self._sweeper.get("is_enabled", 1))
        dot_color = QColor(GREEN if is_enabled else RED)
        p.setBrush(dot_color); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(14, ROW_H // 2 - 4, 8, 8)

        col_x = self._column_xs(w)

        # Name
        p.setPen(QColor(TEXT_PRI if self._selected else TEXT_SEC))
        p.setFont(inter(11, QFont.Weight.DemiBold if self._selected
                                  else QFont.Weight.Medium))
        name = self._sweeper.get("name") or "—"
        fm = p.fontMetrics()
        elided = fm.elidedText(name, Qt.TextElideMode.ElideRight,
                               col_x[1] - col_x[0] - 10)
        p.drawText(QRectF(col_x[0], 0, col_x[1] - col_x[0] - 10, ROW_H),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   elided)

        # Duration (mono) — pills draw themselves at col_x[1], col_x[3], col_x[4]
        p.setPen(QColor(TEXT_MUTED if not self._selected else TEXT_SEC))
        p.setFont(mono(10, bold=True))
        p.drawText(QRectF(col_x[2], 0, col_x[3] - col_x[2] - 8, ROW_H),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   _fmt_duration(self._sweeper.get("duration_ms") or 0))

        # Last Used (text only — broadcast_log lookup deferred)
        p.setPen(QColor(TEXT_MUTED if not self._selected else TEXT_SEC))
        p.setFont(inter(10))
        last = self._sweeper.get("last_used_label") or "—"
        p.drawText(QRectF(col_x[5], 0, w - col_x[5] - 8, ROW_H),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   last)

        # Hairline separator
        p.setPen(QPen(QColor(255, 255, 255, 12), 1))
        p.drawLine(0, ROW_H - 1, int(w), ROW_H - 1)

    def resizeEvent(self, _e):
        self._reposition_pills()

    def showEvent(self, _e):
        self._reposition_pills()

    def _reposition_pills(self):
        col_x = self._column_xs(self.width())
        self._pos_pill.move(col_x[1], (ROW_H - self._pos_pill.height()) // 2)
        self._cat_pill.move(col_x[3], (ROW_H - self._cat_pill.height()) // 2)
        self._props_pill.move(col_x[4], (ROW_H - self._props_pill.height()) // 2)


class _TableHeader(QFrame):
    """Column header row above the sweepers table."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(TABLE_HDR_H)
        self.setStyleSheet(
            f"background: #0c0e1c; "
            f"border-bottom: 1px solid {rgba('#ffffff', 0.06)};"
        )

    def paintEvent(self, _e):
        super().paintEvent(_e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        col_x = _SweeperRow._column_xs(w)
        labels = ["Sweeper Name", "Position", "Duration", "Category",
                  "Properties", "Last Used"]
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(inter(9, QFont.Weight.Bold, letter_spacing=1.0))
        for x, label in zip(col_x, labels):
            p.drawText(QRectF(x, 0, w - x, TABLE_HDR_H),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       label)


# ════════════════════════════════════════════════════════════════════════════
# "How sweeper positions work" educational diagram
# ════════════════════════════════════════════════════════════════════════════

class _HowPositionsExplainer(QFrame):
    """Static painted educational diagram showing where sweepers play
    relative to song timeline."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(HOW_POSITIONS_H)
        self.setStyleSheet("background: transparent;")

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()

        # Outer rounded card
        card_rect = QRectF(8, 0, w - 16, HOW_POSITIONS_H - 4)
        path = QPainterPath(); path.addRoundedRect(card_rect, 8, 8)
        p.setClipPath(path)
        p.fillRect(card_rect, QColor("#0b0e1c"))
        p.setClipping(False)
        p.setPen(QPen(QColor(rgba(RED, 0.25)), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(card_rect, 8, 8)
        # Left red accent
        p.fillRect(QRectF(8, 0, 2, HOW_POSITIONS_H - 4), QColor(RED))

        # Title
        p.setPen(QColor(RED_LIGHT))
        p.setFont(inter(9, QFont.Weight.Bold, letter_spacing=1.4))
        p.drawText(QRectF(20, 10, 320, 14),
                   Qt.AlignmentFlag.AlignLeft, "HOW SWEEPER POSITIONS WORK")

        # Timeline strip (660 wide, in the middle)
        track_x = 32; track_y = 50; track_w = w - 64; track_h = 4
        p.setBrush(QColor("#1c1f38"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(track_x, track_y, track_w, track_h), 2, 2)

        # SONG AUDIO label above
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(inter(8, QFont.Weight.Bold, letter_spacing=1.1))
        p.drawText(QRectF(track_x, track_y - 14, 80, 10),
                   Qt.AlignmentFlag.AlignLeft, "SONG AUDIO")

        # Position markers along the track
        markers = [
            (0.04, "Start of Song",  CYAN),
            (0.22, "Before Intro",   AMBER),
            (0.66, "Before End",     AMBER_LIGHT),
            (0.86, "Bridge at End",  RED_LIGHT),
        ]
        for frac, label, col in markers:
            mx = int(track_x + track_w * frac)
            p.setBrush(QColor(col)); p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(mx - 6, track_y - 4, 12, 12)
            p.setPen(QColor(col))
            p.setFont(inter(8, QFont.Weight.DemiBold))
            fm = p.fontMetrics()
            tw = fm.horizontalAdvance(label)
            p.drawText(QRectF(mx - tw / 2, track_y + 14, tw + 4, 12),
                       Qt.AlignmentFlag.AlignLeft, label)

        # Callout: "Sweeper plays here" — red box with arrow up to bridge marker
        cx = int(track_x + track_w * 0.86) - 60
        cy = 110
        callout = QRectF(cx, cy, 120, 28)
        p.setBrush(QColor(rgba(RED, 0.20)))
        p.setPen(QPen(QColor(rgba(RED, 0.50)), 1))
        p.drawRoundedRect(callout, 6, 6)
        p.setPen(QColor(RED_LIGHT))
        p.setFont(inter(9, QFont.Weight.Bold))
        p.drawText(callout,
                   Qt.AlignmentFlag.AlignCenter, "Sweeper plays here")

        # Caption below
        p.setPen(QColor(AMBER_LIGHT))
        p.setFont(inter(9, QFont.Weight.Medium))
        p.drawText(QRectF(track_x, cy + 36, track_w, 12),
                   Qt.AlignmentFlag.AlignLeft,
                   "↕ plays simultaneously with song")
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(inter(9))
        p.drawText(QRectF(track_x, cy + 50, track_w, 12),
                   Qt.AlignmentFlag.AlignLeft,
                   "The song continues playing underneath — sweeper is layered on top")


# ════════════════════════════════════════════════════════════════════════════
# Audio scrubber footer (visual-only for now — preview wiring deferred)
# ════════════════════════════════════════════════════════════════════════════

class _AudioScrubber(QFrame):
    """Compact 'currently previewing' bar at the bottom of the center column.

    Visual only for now — clicking ▶ logs a TODO. Preview audio routing will
    land alongside the 108:2 dialog work."""

    play_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._title = "—"
        self._meta = ""
        self._pos = 0.5
        self.setFixedHeight(SCRUBBER_H)
        self.setStyleSheet(
            f"background: #0a0c18; "
            f"border-top: 1px solid {rgba('#ffffff', 0.06)};"
        )

    def set_track(self, title: str, meta: str = ""):
        self._title = title or "—"
        self._meta = meta or ""
        self.update()

    def mousePressEvent(self, e):
        # ▶ button hit zone
        if e.button() == Qt.MouseButton.LeftButton and 12 <= e.position().x() <= 44:
            self.play_clicked.emit()
        super().mousePressEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        # Play button
        p.setBrush(QColor(rgba(RED, 0.20)))
        p.setPen(QPen(QColor(rgba(RED, 0.40)), 1))
        p.drawEllipse(12, 12, 26, 26)
        p.setPen(QColor(RED_LIGHT))
        p.setFont(inter(11, QFont.Weight.Bold))
        p.drawText(QRectF(12, 12, 26, 26),
                   Qt.AlignmentFlag.AlignCenter, "▶")
        # Title + meta
        p.setPen(QColor(TEXT_PRI))
        p.setFont(inter(11, QFont.Weight.DemiBold))
        p.drawText(QRectF(50, 6, 320, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._title)
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(inter(9))
        p.drawText(QRectF(50, 22, 320, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._meta)
        # Slider track (right of meta, full remaining width minus right text)
        sx = 380; sw = w - sx - 90; sy = SCRUBBER_H // 2 - 1
        p.setBrush(QColor("#1c1f38")); p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(sx, sy, sw, 4), 2, 2)
        # Thumb
        thumb_x = sx + int(sw * self._pos)
        p.setBrush(QColor(RED_LIGHT))
        p.drawEllipse(thumb_x - 6, sy - 4, 12, 12)
        # Time text
        p.setPen(QColor(TEXT_SEC))
        p.setFont(mono(9, bold=True))
        p.drawText(QRectF(w - 80, 0, 70, SCRUBBER_H),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   "0:00 / 0:00")


# ════════════════════════════════════════════════════════════════════════════
# Right details panel
# ════════════════════════════════════════════════════════════════════════════

class _DetailsHeaderCard(QFrame):
    """Top card on the details panel — 〜 icon + name + meta line."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sweeper: dict = {}
        self.setFixedHeight(72)

    def set_sweeper(self, s: dict):
        self._sweeper = s or {}
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        # 〜 icon tile
        p.setBrush(QColor(rgba(PINK, 0.16)))
        p.setPen(QPen(QColor(rgba(PINK, 0.30)), 1))
        p.drawRoundedRect(QRectF(14, 12, 48, 48), 10, 10)
        p.setPen(QColor(PINK_LIGHT))
        p.setFont(inter(20, QFont.Weight.Black))
        p.drawText(QRectF(14, 12, 48, 48),
                   Qt.AlignmentFlag.AlignCenter, "〜")
        # Name
        name = self._sweeper.get("name") or "—"
        p.setPen(QColor(TEXT_PRI))
        p.setFont(inter(14, QFont.Weight.Bold))
        p.drawText(QRectF(76, 14, w - 90, 22),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   name)
        # Meta line — Category · Duration · Position
        cat = self._sweeper.get("category") or "—"
        dur = _fmt_duration(self._sweeper.get("duration_ms") or 0)
        pos = self._sweeper.get("position") or "—"
        meta = f"{cat}  ·  {dur}  ·  {pos}"
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(inter(10))
        p.drawText(QRectF(76, 38, w - 90, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   meta)


class _DetailsField(QFrame):
    """Read-only labeled value box."""

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self._label = label
        self._value = "—"
        self.setFixedHeight(48)

    def set_value(self, v: str):
        self._value = v if (v not in (None, "")) else "—"
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        # Label
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(inter(8, QFont.Weight.Bold, letter_spacing=1.0))
        p.drawText(QRectF(0, 0, w, 14),
                   Qt.AlignmentFlag.AlignLeft, self._label)
        # Value box
        box = QRectF(0, 16, w, 30)
        p.setBrush(QColor("#0a0c18"))
        p.setPen(QPen(QColor(rgba("#ffffff", 0.06)), 1))
        p.drawRoundedRect(box, 5, 5)
        p.setPen(QColor(TEXT_PRI))
        p.setFont(inter(11, QFont.Weight.Medium))
        p.drawText(QRectF(10, 16, w - 14, 30),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._value)


class _PositionSettingRow(QPushButton):
    """One position-settings row — clickable, click is read-only-ack
    until the 108:2 editor lands."""

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self._text = text
        self._active = False
        self._hover = False
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFlat(True)
        self.setFixedHeight(34)
        self.setStyleSheet("background: transparent; border: none;")

    def set_active(self, active: bool):
        self._active = bool(active)
        self.update()

    def enterEvent(self, e): self._hover = True;  self.update(); super().enterEvent(e)
    def leaveEvent(self, e): self._hover = False; self.update(); super().leaveEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        rect = QRectF(0.5, 0.5, w - 1, h - 1)
        path = QPainterPath(); path.addRoundedRect(rect, 5, 5)
        p.setClipPath(path)
        if self._active:
            p.fillRect(rect, QColor(rgba(RED, 0.16)))
            p.setClipping(False)
            p.setPen(QPen(QColor(rgba(RED, 0.45)), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(rect, 5, 5)
            p.setPen(QColor(RED_LIGHT))
        else:
            p.fillRect(rect, QColor("#0a0c18"))
            if self._hover:
                p.fillRect(rect, QColor(255, 255, 255, 8))
            p.setClipping(False)
            p.setPen(QPen(QColor(rgba("#ffffff", 0.06)), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(rect, 5, 5)
            p.setPen(QColor(TEXT_SEC if self._hover else TEXT_MUTED))
        p.setFont(inter(10, QFont.Weight.DemiBold if self._active
                                   else QFont.Weight.Medium))
        p.drawText(QRectF(12, 0, w - 24, h),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._text)


# ════════════════════════════════════════════════════════════════════════════
# Main screen
# ════════════════════════════════════════════════════════════════════════════

class SweepersLibrary(QWidget):

    breadcrumb_clicked = pyqtSignal(str)
    studio_clicked     = pyqtSignal()
    sweeper_selected   = pyqtSignal(int)
    add_sweeper_clicked = pyqtSignal()      # for future 108:2 dialog hook

    def __init__(self, db, parent=None, engine=None):
        super().__init__(parent)
        self._db = db
        self._engine = engine               # not wired yet — preview deferred

        # State
        self._sweepers: list[dict] = []
        self._row_widgets: list[_SweeperRow] = []
        self._selected_id: Optional[int] = None
        self._position_filter: str = "All Positions"

        # Refs
        self._table_layout: Optional[QVBoxLayout] = None
        self._counter: Optional[_SidebarCounter] = None
        self._clock_lbl: Optional[QLabel] = None
        self._filter_rows: list[_PositionFilterRow] = []
        self._details_card: Optional[_DetailsHeaderCard] = None
        self._details_fields: dict[str, _DetailsField] = {}
        self._pos_setting_rows: list[_PositionSettingRow] = []
        self._scrubber: Optional[_AudioScrubber] = None
        self._status_count: Optional[QLabel] = None

        self.setFixedSize(WINDOW_W, WINDOW_H)
        self.setStyleSheet(
            "background: qlineargradient("
            "x1:0, y1:0, x2:1, y2:1, "
            "stop:0 #0a0d1a, stop:0.5 #06080f, stop:1 #020308);"
        )

        self._build_header()
        self._build_sidebar()
        self._build_center()
        self._build_right_panel()
        self._build_status_bar()

        self._load_sweepers()

        # Live clock
        self._tick()
        t = QTimer(self)
        t.setInterval(1000); t.timeout.connect(self._tick); t.start()

        log.info("SweepersLibrary ready (Figma 46:2)")

    # ── HEADER ───────────────────────────────────────────────────────────

    def _build_header(self):
        bg = QFrame(self)
        bg.setGeometry(0, 0, WINDOW_W, HEADER_H)
        bg.setStyleSheet(
            f"background: qlineargradient(x1:0,y1:0,x2:0,y2:1, "
            f"stop:0 rgba(16,19,31,0.95), stop:1 rgba(10,12,22,0.95)); "
            f"border-bottom: 1px solid {rgba('#ffffff', 0.06)};"
        )
        hl = QFrame(self)
        hl.setGeometry(0, HEADER_H - 1, WINDOW_W, 1)
        hl.setStyleSheet(
            "background: qlineargradient(x1:0,y1:0,x2:1,y2:0, "
            "stop:0 rgba(255,255,255,0), stop:0.5 rgba(255,255,255,0.10), "
            "stop:1 rgba(255,255,255,0));"
        )

        _HeaderLogo(self).move(14, 16)
        l = QLabel("RadioAI", self)
        l.setGeometry(64, 14, 120, 18)
        l.setFont(inter(15, QFont.Weight.Bold))
        l.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        l = QLabel("STUDIO PRO", self)
        l.setGeometry(64, 34, 120, 12)
        l.setFont(inter(8, QFont.Weight.Bold, letter_spacing=1.2))
        l.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

        # Breadcrumb: Control Panel | Libraries | 〜 Sweepers
        cp_btn = QPushButton("Control Panel", self)
        cp_btn.setGeometry(170, 22, 100, 22)
        cp_btn.setFont(inter(11, QFont.Weight.Medium))
        cp_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        cp_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {TEXT_MUTED}; "
            f"border: none; padding: 0; text-align: left; }}"
            f"QPushButton:hover {{ color: {TEXT_PRI}; }}"
        )
        cp_btn.clicked.connect(
            lambda: self.breadcrumb_clicked.emit("control_panel"))

        sep = QLabel("|", self); sep.setGeometry(266, 22, 8, 22)
        sep.setFont(inter(11))
        sep.setStyleSheet(f"color: {TEXT_DIM}; background: transparent;")

        l = QLabel("Libraries", self)
        l.setGeometry(276, 22, 60, 22)
        l.setFont(inter(11, QFont.Weight.Medium))
        l.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

        sep2 = QLabel("|", self); sep2.setGeometry(336, 22, 8, 22)
        sep2.setFont(inter(11))
        sep2.setStyleSheet(f"color: {TEXT_DIM}; background: transparent;")

        chip = _ActiveBreadcrumbChip("Sweepers", self)
        chip.move(348, 20)

        # Title + subtitle (between breadcrumb and clock)
        l = QLabel("Sweepers Library", self)
        l.setGeometry(484, 12, 360, 24)
        l.setFont(inter(20, QFont.Weight.Bold))
        l.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        l = QLabel(
            "Audio overlays that play over songs — set position and timing",
            self)
        l.setGeometry(484, 38, 460, 14)
        l.setFont(inter(10))
        l.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

        # Clock + station
        self._clock_lbl = QLabel("21:56:15", self)
        self._clock_lbl.setGeometry(1108, 14, 100, 24)
        self._clock_lbl.setFont(mono(20, bold=True))
        self._clock_lbl.setStyleSheet(
            f"color: {TEXT_PRI}; background: transparent;")
        l = QLabel(Settings().station_display, self)
        l.setObjectName("hdr_station_lbl")
        l.setGeometry(1108, 40, 100, 14)
        l.setFont(inter(9, QFont.Weight.Medium))
        l.setStyleSheet(f"color: {GREEN}; background: transparent;")

        osb = _HeaderOpenStudio(self)
        osb.move(1222, 16)
        osb.clicked.connect(self.studio_clicked.emit)

    # ── SIDEBAR ──────────────────────────────────────────────────────────

    def _build_sidebar(self):
        sb = QFrame(self)
        sb.setGeometry(0, HEADER_H, SIDEBAR_W, WINDOW_H - HEADER_H - STATUS_H)
        sb.setStyleSheet(
            f"background: #0a0c16; "
            f"border-right: 1px solid {rgba('#ffffff', 0.06)};"
        )

        # Counter
        self._counter = _SidebarCounter(self)
        self._counter.move(12, HEADER_H + 14)

        # Action buttons
        actions = [
            ("+ Add New",          GREEN,        "#052e16", self._on_add_new),
            ("☴ Mass Import",      CYAN,         "#083344", self._on_mass_import),
            ("✎ Edit Categories",  PURPLE_LIGHT, "#1e1535", self._on_edit_categories),
            ("✕ Delete",           RED,          "#1f0a12", self._on_delete),
        ]
        y0 = HEADER_H + 64
        for i, (txt, color, bg_tint, slot) in enumerate(actions):
            btn = _SidebarActionButton(txt, color, bg_tint, self)
            btn.move(12, y0 + i * 34)
            btn.clicked.connect(slot)

        # Position filter section
        pf_y = y0 + 4 * 34 + 18
        l = QLabel("POSITION FILTER", self)
        l.setGeometry(12, pf_y, 160, 14)
        l.setFont(inter(8, QFont.Weight.Bold, letter_spacing=1.2))
        l.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        for i, opt in enumerate(POSITION_OPTIONS):
            row = _PositionFilterRow(opt, self)
            row.move(12, pf_y + 18 + i * 30)
            row.clicked.connect(
                lambda _checked=False, name=opt: self._on_filter_picked(name))
            if i == 0:
                row.set_active(True)
            self._filter_rows.append(row)

        # Integration section (links to Playlister)
        ig_y = pf_y + 18 + len(POSITION_OPTIONS) * 30 + 14
        l = QLabel("INTEGRATION", self)
        l.setGeometry(12, ig_y, 160, 14)
        l.setFont(inter(8, QFont.Weight.Bold, letter_spacing=1.2))
        l.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        integrations = [
            ("↗ Export to Playlister", GREEN,        "#052e16",
             self._on_export_playlister),
            ("⚙ Playlister Prefix",    CYAN_LIGHT,   "#083344",
             self._on_playlister_prefix),
        ]
        for i, (txt, color, bg_tint, slot) in enumerate(integrations):
            btn = _SidebarActionButton(txt, color, bg_tint, self)
            btn.move(12, ig_y + 18 + i * 32)
            btn.clicked.connect(slot)

    # ── CENTER (table + how-positions + scrubber) ────────────────────────

    def _build_center(self):
        # Table header strip
        hdr = _TableHeader(self)
        hdr.setGeometry(TABLE_X0, HEADER_H, TABLE_W, TABLE_HDR_H)

        # Scrollable table body
        scroll = QScrollArea(self)
        scroll.setGeometry(TABLE_X0, HEADER_H + TABLE_HDR_H,
                           TABLE_W, TABLE_BODY_H)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            f"QScrollBar:vertical {{ background: {rgba('#ffffff', 0.02)}; "
            f"width: 6px; }}"
            f"QScrollBar::handle:vertical {{ background: {rgba(CYAN, 0.45)}; "
            f"border-radius: 3px; min-height: 24px; }}"
            "QScrollBar::add-line, QScrollBar::sub-line { height: 0; }"
        )
        body = QFrame(); body.setStyleSheet("background: transparent;")
        self._table_layout = QVBoxLayout(body)
        self._table_layout.setContentsMargins(0, 0, 0, 0)
        self._table_layout.setSpacing(0)
        self._table_layout.addStretch()
        scroll.setWidget(body)

        # How sweeper positions work
        explainer = _HowPositionsExplainer(self)
        explainer.setGeometry(TABLE_X0,
                              HEADER_H + HOW_POSITIONS_Y_REL,
                              TABLE_W, HOW_POSITIONS_H)

        # Audio scrubber footer
        self._scrubber = _AudioScrubber(self)
        scrub_y = WINDOW_H - STATUS_H - SCRUBBER_H
        self._scrubber.setGeometry(TABLE_X0, scrub_y, TABLE_W, SCRUBBER_H)
        self._scrubber.play_clicked.connect(self._on_scrubber_play)

    # ── RIGHT DETAILS PANEL ──────────────────────────────────────────────

    def _build_right_panel(self):
        wrap = QFrame(self)
        wrap.setGeometry(RIGHT_X, HEADER_H + 4, RIGHT_W,
                         WINDOW_H - HEADER_H - STATUS_H - 12)
        wrap.setStyleSheet(
            f"QFrame {{ background: #0a0c18; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; "
            f"border-radius: 10px; }}"
        )

        # Title strip
        title = QLabel("SWEEPER DETAILS", wrap)
        title.setGeometry(14, 10, 200, 14)
        title.setFont(inter(10, QFont.Weight.Bold, letter_spacing=1.2))
        title.setStyleSheet(f"color: {RED_LIGHT}; background: transparent;")
        sub = QLabel("Select a sweeper to view details", wrap)
        sub.setObjectName("details_sub")
        sub.setGeometry(14, 26, 400, 12)
        sub.setFont(inter(9))
        sub.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        self._details_sub = sub

        # Header card
        self._details_card = _DetailsHeaderCard(wrap)
        self._details_card.setGeometry(14, 46, RIGHT_W - 28, 72)

        # Form fields (stacked)
        labels = ["Name", "Category", "Duration", "Position",
                  "Properties", "Playlister Code"]
        fy = 132
        for i, lab in enumerate(labels):
            f = _DetailsField(lab, wrap)
            f.setGeometry(14, fy + i * 56, RIGHT_W - 28, 48)
            self._details_fields[lab] = f

        # Position settings list
        ps_y = fy + len(labels) * 56 + 12
        ps_label = QLabel("POSITION SETTINGS", wrap)
        ps_label.setGeometry(14, ps_y, 220, 14)
        ps_label.setFont(inter(9, QFont.Weight.Bold, letter_spacing=1.2))
        ps_label.setStyleSheet(
            f"color: {RED_LIGHT}; background: transparent;")
        # 3px red bar to the left of the label
        bar = QFrame(wrap)
        bar.setGeometry(8, ps_y - 2, 2, 18)
        bar.setStyleSheet(f"background: {RED};")

        for i, opt in enumerate(POSITION_OPTIONS[1:]):  # skip "All Positions"
            row = _PositionSettingRow(opt, wrap)
            row.setGeometry(14, ps_y + 22 + i * 38, RIGHT_W - 28, 34)
            row.clicked.connect(
                lambda _checked=False, n=opt: self._on_position_setting_click(n))
            self._pos_setting_rows.append(row)

        # AI tip footer
        tip_y = ps_y + 22 + len(POSITION_OPTIONS[1:]) * 38 + 8
        tip = QLabel("✦ AI: Bridge position creates smooth transitions",
                     wrap)
        tip.setGeometry(14, tip_y, RIGHT_W - 28, 32)
        tip.setFont(inter(10, QFont.Weight.Medium))
        tip.setStyleSheet(
            f"QLabel {{ color: {PURPLE_LIGHT}; "
            f"background: {rgba(PURPLE, 0.10)}; "
            f"border: 1px solid {rgba(PURPLE, 0.30)}; "
            f"border-radius: 6px; padding-left: 10px; }}"
        )

    # ── STATUS BAR ───────────────────────────────────────────────────────

    def _build_status_bar(self):
        sb = QFrame(self)
        sb.setGeometry(0, WINDOW_H - STATUS_H, WINDOW_W, STATUS_H)
        sb.setStyleSheet(
            f"QFrame {{ background: rgba(13,15,30,0.95); "
            f"border-top: 1px solid {rgba('#ffffff', 0.06)}; }}"
        )

        def _pill(x, text, fg, bg, w=110):
            l = QLabel(text, sb)
            l.setGeometry(x, 14, w, 22)
            l.setFont(inter(9, QFont.Weight.Bold, letter_spacing=1.0))
            l.setStyleSheet(
                f"QLabel {{ background: {bg}; color: {fg}; "
                f"border-radius: 11px; padding-left: 10px; }}"
            )
            return l

        _pill(12,  "● AUTO MODE", PURPLE_LIGHT, rgba(PURPLE, 0.18))
        _pill(130, "● AI Active", GREEN_LIGHT,  rgba(GREEN,  0.18), w=96)
        self._status_count = _pill(234, "0 Sweepers",
                                   PINK_LIGHT, rgba(PINK, 0.18), w=110)

        version = QLabel(
            "Sweepers Library  ·  RadioAI Studio v2.0", sb)
        version.setGeometry(WINDOW_W - 380, 16, 280, 16)
        version.setFont(inter(9))
        version.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent;")
        version.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        os_btn = QPushButton("▶  Open Studio", sb)
        os_btn.setGeometry(WINDOW_W - 100, 12, 88, 26)
        os_btn.setFont(inter(10, QFont.Weight.Bold))
        os_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        os_btn.setStyleSheet(
            f"QPushButton {{ background: {rgba(GREEN, 0.18)}; color: {GREEN_LIGHT}; "
            f"border: 1px solid {rgba(GREEN, 0.4)}; border-radius: 5px; }}"
            f"QPushButton:hover {{ background: {rgba(GREEN, 0.30)}; }}"
        )
        os_btn.clicked.connect(self.studio_clicked.emit)

    # ── DATA ─────────────────────────────────────────────────────────────

    def _row_to_dict(self, row) -> dict:
        return {
            "id":              int(row["id"]),
            "name":            row["name"],
            "category":        row["category"] or "Station",
            "file_path":       row["file_path"] or "",
            "duration_ms":     int(row["duration_ms"] or 0),
            "position":        row["position"] or "Bridge at End",
            "properties":      row["properties"] or "Regular",
            "playlister_code": row["playlister_code"] or "",
            "is_enabled":      bool(row["is_enabled"]),
            "last_used_label": "—",   # broadcast_log lookup deferred
        }

    def _load_sweepers(self):
        try:
            rows = self._db._conn().execute(
                "SELECT * FROM sweepers ORDER BY id"
            ).fetchall()
            self._sweepers = [self._row_to_dict(r) for r in rows]
        except Exception as exc:
            log.error(f"load_sweepers failed: {exc}")
            self._sweepers = []

        if self._counter:
            total = len(self._sweepers)
            active = sum(1 for s in self._sweepers if s["is_enabled"])
            self._counter.set_counts(active, total)
        if self._status_count:
            self._status_count.setText(f"● {len(self._sweepers)} Sweepers")

        self._refresh_table()

        # Auto-select first row so the details panel isn't empty.
        if self._sweepers and self._selected_id is None:
            self._on_row_clicked(self._sweepers[0]["id"])

    def _filtered_sweepers(self) -> list[dict]:
        if self._position_filter == "All Positions":
            return list(self._sweepers)
        return [s for s in self._sweepers
                if (s.get("position") or "").strip() == self._position_filter]

    def _refresh_table(self):
        if not self._table_layout:
            return
        # Drop existing widgets
        for w in self._row_widgets:
            w.setParent(None)
            w.deleteLater()
        self._row_widgets = []

        # Insert at index 0 (the layout has a stretch trailing)
        for i, s in enumerate(self._filtered_sweepers()):
            row = _SweeperRow(s, i)
            row.clicked.connect(self._on_row_clicked)
            row.double_clicked.connect(self._on_row_double_clicked)
            self._table_layout.insertWidget(i, row)
            if s["id"] == self._selected_id:
                row.set_selected(True)
            self._row_widgets.append(row)

    def _on_row_clicked(self, sweeper_id: int):
        self._selected_id = int(sweeper_id)
        for r in self._row_widgets:
            r.set_selected(r._sweeper.get("id") == sweeper_id)
        self._refresh_details()
        self.sweeper_selected.emit(int(sweeper_id))

    def _on_row_double_clicked(self, sweeper_id: int):
        # Open the editor dialog in EDIT mode for this row.
        self._open_editor_dialog(sweeper_id=int(sweeper_id))

    def _refresh_details(self):
        cur = next((s for s in self._sweepers
                    if s["id"] == self._selected_id), None)
        if not cur:
            if self._details_card:
                self._details_card.set_sweeper({})
            for f in self._details_fields.values():
                f.set_value("—")
            for r in self._pos_setting_rows:
                r.set_active(False)
            if self._details_sub:
                self._details_sub.setText("Select a sweeper to view details")
            return
        if self._details_sub:
            self._details_sub.setText(cur.get("name") or "")
        if self._details_card:
            self._details_card.set_sweeper(cur)
        self._details_fields["Name"].set_value(cur.get("name") or "—")
        self._details_fields["Category"].set_value(cur.get("category") or "—")
        self._details_fields["Duration"].set_value(
            _fmt_duration(cur.get("duration_ms") or 0))
        self._details_fields["Position"].set_value(cur.get("position") or "—")
        self._details_fields["Properties"].set_value(
            cur.get("properties") or "—")
        self._details_fields["Playlister Code"].set_value(
            cur.get("playlister_code") or "—")
        # Position settings highlight
        for r in self._pos_setting_rows:
            r.set_active(r.text() == (cur.get("position") or ""))
        # Update scrubber meta
        if self._scrubber:
            self._scrubber.set_track(
                cur.get("name") or "—",
                f"{cur.get('position') or '—'}  ·  "
                f"{_fmt_duration(cur.get('duration_ms') or 0)}")

    # ── EVENT HANDLERS ───────────────────────────────────────────────────

    def _on_filter_picked(self, name: str):
        self._position_filter = name
        for r in self._filter_rows:
            r.set_active(r.text() == name)
        # Keep current selection if still in filtered set, else clear.
        filtered_ids = {s["id"] for s in self._filtered_sweepers()}
        if self._selected_id not in filtered_ids:
            self._selected_id = None
            self._refresh_details()
        self._refresh_table()

    def _on_add_new(self):
        log.info("[sweepers] + Add New (open editor dialog, Figma 108:2)")
        self.add_sweeper_clicked.emit()
        self._open_editor_dialog(sweeper_id=None)

    def _open_editor_dialog(self, sweeper_id: Optional[int] = None):
        """Open the SweeperEditorDialog. Lazy-imported so the screen
        constructs without dragging the dialog widgets into memory until
        the operator actually opens one."""
        from ui.dialogs.sweeper_editor_dialog import SweeperEditorDialog
        dlg = SweeperEditorDialog(self._db, sweeper_id=sweeper_id, parent=self)
        dlg.sweeper_saved.connect(self._on_sweeper_saved)
        dlg.exec()

    def _on_sweeper_saved(self, sweeper_id: int):
        """Refresh table + select the saved row."""
        self._selected_id = int(sweeper_id)
        self._load_sweepers()
        self._on_row_clicked(int(sweeper_id))

    def _on_mass_import(self):
        log.info("[sweepers] Mass Import — TODO")
        dialogs.info(
            self, "Coming soon",
            "Mass Import will let you bulk-add sweepers from a folder.")

    def _on_edit_categories(self):
        log.info("[sweepers] Edit Categories — TODO")
        dialogs.info(
            self, "Coming soon",
            "Edit Categories will let you manage sweeper category labels.")

    def _on_delete(self):
        log.info("[sweepers] Delete — TODO (waiting for confirm flow)")
        if self._selected_id is None:
            dialogs.info(
                self, "No selection", "Select a sweeper row first.")
            return
        dialogs.info(
            self, "Coming soon",
            "Sweeper delete will land alongside the editor dialog "
            "so the destructive confirmation matches the rest of the app.")

    def _on_export_playlister(self):
        log.info("[sweepers] Export to Playlister — TODO")
        dialogs.info(
            self, "Coming soon",
            "Export to Playlister will write the active sweepers list to "
            "the Playlister integration file.")

    def _on_playlister_prefix(self):
        log.info("[sweepers] Playlister Prefix — TODO")
        dialogs.info(
            self, "Coming soon",
            "Playlister Prefix lets you set the SS-### code template used "
            "when exporting.")

    def _on_position_setting_click(self, position: str):
        # Read-only ack until 108:2 lands. Logs the intent so we can verify
        # in NIGHT_LOG when wiring the editor.
        log.info(f"[sweepers] position-setting click: {position} "
                 f"(editor dialog not yet wired)")

    def _on_scrubber_play(self):
        log.info("[sweepers] scrubber ▶ — preview wiring deferred")

    # ── CLOCK ────────────────────────────────────────────────────────────

    def _tick(self):
        if self._clock_lbl:
            self._clock_lbl.setText(datetime.now().strftime("%H:%M:%S"))
