"""
RadioAI Studio Pro — Spots & Commercials Library
Pixel-accurate match of Figma node 35:2 (file 7oN9K61g94wKx3nu44KKDF).

Layout (1440×900):
  Header           y=0..50           Logo, breadcrumb, title, clock
  Sidebar          y=50..868, x=0..160       Counter + actions + filters + reports
  Table header     y=50..82, x=160..860      28px header strip
  Table body       y=82..768, x=160..860     Scrollable campaign list
  Now Airing strip y=778..838, x=160..860    Compact "currently playing" panel
  Right panel      y=50..838, x=872..1432    Tabs + Campaign Details / Schedule / Reports
  Status bar       y=868..900, 1440×32       Pills + version + Open Studio mini

TODO: when 3+ libraries share the header chrome (Songs / Spots / Instant Jingles),
extract _HeaderLogo + _HeaderOpenStudio + _ActiveBreadcrumbChip into
ui/widgets/library_chrome.py.

Phase status (incremental build):
  [✓] header / sidebar / table / now-airing / right panel / status bar
  [ ] Add Campaign dialog (Phase C)
  [ ] Edit Breaks → Spot Programming dialog (session 2)
  [ ] Date picker integration (session 2)
"""

import logging
import os
from typing import Optional
from datetime import datetime

from PyQt6.QtCore import (
    Qt, QRectF, QTimer, QPropertyAnimation, pyqtProperty, pyqtSignal,
)
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QLinearGradient, QPainterPath, QFont,
    QCursor, QFontMetrics,
)
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QComboBox, QHBoxLayout, QVBoxLayout,
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

log = logging.getLogger("SpotsCommercials")


# ════════════════════════════════════════════════════════════════════════════
# Geometry tokens
# ════════════════════════════════════════════════════════════════════════════

WINDOW_W   = 1440
WINDOW_H   = 900
HEADER_H   = 50
STATUS_H   = 32

SIDEBAR_W  = 160
TABLE_X0   = SIDEBAR_W
TABLE_X1   = 860
TABLE_W    = TABLE_X1 - TABLE_X0      # 700
ROW_H      = 30

RIGHT_X    = 872
RIGHT_W    = WINDOW_W - RIGHT_X - 8   # 560

NOW_AIRING_H = 60
TABLE_HDR_H  = 32

CATEGORY_COLORS = {
    "Commercials":  AMBER,
    "Commercial":   AMBER,
    "Station ID":   PURPLE_LIGHT,
    "News Break":   CYAN,
    "Sponsor":      GREEN,
    "Sponsorship":  GREEN,
    "Promo":        PINK,
}

PRIORITY_COLORS = {
    "High":   RED_LIGHT,
    "Medium": AMBER,
    "Low":    TEXT_MUTED,
    "Always": PURPLE_LIGHT,
}


def _category_color(name: str) -> str:
    return CATEGORY_COLORS.get((name or "").strip(), TEXT_MUTED)


def _priority_color(name: str) -> str:
    return PRIORITY_COLORS.get((name or "").strip(), TEXT_MUTED)


def _fmt_date(s: Optional[str]) -> str:
    """ISO 'YYYY-MM-DD' or 'Never' → '01 Apr 2026' / 'Never'."""
    if not s:
        return "—"
    if s == "Never":
        return "Never"
    try:
        return datetime.strptime(s, "%Y-%m-%d").strftime("%d %b %Y")
    except Exception:
        return s


def _fmt_full_date(s: Optional[str]) -> str:
    """ISO 'YYYY-MM-DD' or 'Never' → '01 April 2026' / 'Never'."""
    if not s:
        return "—"
    if s == "Never":
        return "Never"
    try:
        return datetime.strptime(s, "%Y-%m-%d").strftime("%d %B %Y")
    except Exception:
        return s


def _fmt_duration_short(ms: int) -> str:
    s = int((ms or 0) // 1000)
    return f"{s // 60}:{s % 60:02d}"


# ════════════════════════════════════════════════════════════════════════════
# Header chrome — replicated locally per screen (see TODO at top of file)
# ════════════════════════════════════════════════════════════════════════════

class _HeaderLogo(QWidget):
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
        p.setPen(QPen(bc, 1)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 8, 8)
        p.setPen(QColor(GREEN))
        p.setFont(inter(11, QFont.Weight.Bold))
        p.drawText(12, 0, 16, 34,
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "▶")
        p.setFont(inter(11, QFont.Weight.Bold))
        p.drawText(28, 4, 170, 14,
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   "Open Studio")
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(inter(8))
        p.drawText(28, 18, 170, 12,
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   "Billie Eilish — Bury A Friend")


class _ActiveBreadcrumbChip(QFrame):
    """$ Spots & Commercials chip — green-tinted with pulsing dot."""

    def __init__(self, text: str = "Spots & Commercials", parent=None):
        super().__init__(parent)
        self._text = text
        self._dot_alpha = 1.0
        self.setFixedSize(160, 28)
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
        rect = QRectF(0.5, 0.5, 159, 27)
        path = QPainterPath()
        path.addRoundedRect(rect, 14, 14)
        p.setClipPath(path)
        c1 = QColor(GREEN); c1.setAlphaF(0.20)
        c2 = QColor(GREEN); c2.setAlphaF(0.06)
        g = QLinearGradient(0, 0, 0, 28)
        g.setColorAt(0.0, c1); g.setColorAt(1.0, c2)
        p.fillRect(QRectF(0, 0, 160, 28), QBrush(g))
        p.setClipping(False)
        bc = QColor(GREEN); bc.setAlphaF(0.35)
        p.setPen(QPen(bc, 1)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 14, 14)
        # Pulsing $ glyph
        glow = QColor(GREEN_LIGHT); glow.setAlphaF(self._dot_alpha)
        p.setPen(QColor(GREEN_LIGHT))
        p.setFont(inter(13, QFont.Weight.Black))
        p.drawText(QRectF(10, 0, 14, 28),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   "$")
        p.setPen(glow)
        p.setFont(inter(11, QFont.Weight.Bold))
        p.drawText(QRectF(26, 0, 130, 28),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   self._text)


# ════════════════════════════════════════════════════════════════════════════
# Sidebar widgets
# ════════════════════════════════════════════════════════════════════════════

class _SidebarCounter(QFrame):
    """'4/4 campaigns' green box — shows active/total."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._active = 0
        self._total  = 0
        self.setFixedSize(SIDEBAR_W - 24, 36)

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
        # 3px left accent
        p.fillRect(QRectF(0, 0, 3, h), QColor(GREEN))
        # Numbers
        p.setPen(QColor(GREEN_LIGHT))
        p.setFont(mono(15, bold=True))
        p.drawText(QRectF(10, 4, w - 14, 18),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   f"{self._active}/{self._total}")
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(inter(8, QFont.Weight.Bold, letter_spacing=1.0))
        p.drawText(QRectF(10, 20, w - 14, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "CAMPAIGNS")


class _SidebarActionButton(QPushButton):
    """Sidebar action button — full-width with left accent + label."""

    def __init__(self, text: str, color: str, bg_tint: str, parent=None):
        super().__init__(text, parent)
        self._color   = QColor(color)
        self._bg_tint = QColor(bg_tint)
        self._hover = False
        self.setFixedSize(SIDEBAR_W - 24, 28)
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
# Campaign table widgets
# ════════════════════════════════════════════════════════════════════════════

class _Pill(QWidget):
    """Lightweight rounded badge — used for category & priority columns."""

    def __init__(self, text: str, color: str, parent=None):
        super().__init__(parent)
        self._text = text
        self._color = QColor(color)
        fm = QFontMetrics(inter(9, QFont.Weight.Bold, letter_spacing=0.5))
        w = max(56, fm.horizontalAdvance(text) + 16)
        self.setFixedSize(w, 18)

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


class _CampaignRow(QFrame):
    """One row in the campaigns table — fixed-height, custom-painted."""

    clicked        = pyqtSignal(int)   # campaign_id (single-click → select)
    double_clicked = pyqtSignal(int)   # campaign_id (double-click → edit)

    def __init__(self, campaign: dict, row_index: int, parent=None):
        super().__init__(parent)
        self._campaign = campaign
        self._row_index = row_index
        self._selected = False
        self._hover = False
        self.setFixedHeight(ROW_H)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

    def set_selected(self, sel: bool):
        self._selected = sel
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(int(self._campaign.get("id", 0)))
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit(int(self._campaign.get("id", 0)))
        super().mouseDoubleClickEvent(e)

    def enterEvent(self, e): self._hover = True;  self.update(); super().enterEvent(e)
    def leaveEvent(self, e): self._hover = False; self.update(); super().leaveEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        rect = QRectF(0, 0, w, ROW_H)

        # Background
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
        is_active = bool(self._campaign.get("is_currently_active", 1))
        dot_color = QColor(GREEN if is_active else RED)
        p.setBrush(dot_color); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(14, ROW_H // 2 - 4, 8, 8)

        # Column positions (relative to row width)
        # name | spots | category | priority | start | end
        col_x = self._column_xs(w)

        # Name (bold, white if selected)
        p.setPen(QColor(TEXT_PRI if self._selected else TEXT_SEC))
        p.setFont(inter(11, QFont.Weight.DemiBold if self._selected
                                  else QFont.Weight.Medium))
        name = self._campaign.get("name") or "—"
        fm = p.fontMetrics()
        elided = fm.elidedText(name, Qt.TextElideMode.ElideRight,
                               col_x[1] - col_x[0] - 8)
        p.drawText(QRectF(col_x[0], 0, col_x[1] - col_x[0] - 8, ROW_H),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   elided)

        # Spots (file count)
        n = int(self._campaign.get("file_count") or 0)
        files_text = f"{n} file" + ("s" if n != 1 else "")
        p.setPen(QColor(TEXT_MUTED if not self._selected else TEXT_SEC))
        p.setFont(inter(10))
        p.drawText(QRectF(col_x[1], 0, col_x[2] - col_x[1] - 8, ROW_H),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   files_text)

        # End paint — pills draw themselves as child widgets

        # Start / End dates — text only
        p.setPen(QColor(TEXT_MUTED if not self._selected else TEXT_SEC))
        p.setFont(mono(9, bold=True))
        p.drawText(QRectF(col_x[4], 0, col_x[5] - col_x[4] - 8, ROW_H),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   _fmt_date(self._campaign.get("start_date")))
        p.drawText(QRectF(col_x[5], 0, w - col_x[5] - 8, ROW_H),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   _fmt_date(self._campaign.get("end_date")))

        # Hairline separator
        p.setPen(QPen(QColor(255, 255, 255, 12), 1))
        p.drawLine(0, ROW_H - 1, int(w), ROW_H - 1)

    def resizeEvent(self, _e):
        # Position pill children whenever the row resizes
        self._reposition_pills()

    def showEvent(self, _e):
        self._reposition_pills()

    def _reposition_pills(self):
        # Lazily create pill widgets (so they paint on top of paintEvent)
        if not hasattr(self, "_cat_pill"):
            cat = self._campaign.get("category") or ""
            pri = self._campaign.get("priority") or ""
            self._cat_pill = _Pill(cat, _category_color(cat), self)
            self._pri_pill = _Pill(pri, _priority_color(pri), self)
        col_x = self._column_xs(self.width())
        self._cat_pill.move(col_x[2], (ROW_H - self._cat_pill.height()) // 2)
        self._pri_pill.move(col_x[3], (ROW_H - self._pri_pill.height()) // 2)

    @staticmethod
    def _column_xs(total_w: int) -> list[int]:
        # Column starts: name | spots | category | priority | start | end
        # Tuned so End Date has ~80px room for "30 Jun 2026" without elision.
        return [
            32,                   # name (after status dot)
            int(total_w * 0.39),  # spots
            int(total_w * 0.51),  # category
            int(total_w * 0.64),  # priority
            int(total_w * 0.78),  # start date
            int(total_w * 0.89),  # end date
        ]


class _TableHeader(QFrame):
    """Column header row above the table body."""

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
        col_x = _CampaignRow._column_xs(w)
        labels = ["Campaign Name", "Spots", "Category", "Priority",
                  "Start Date", "End Date"]
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(inter(9, QFont.Weight.Bold, letter_spacing=1.0))
        for x, label in zip(col_x, labels):
            p.drawText(QRectF(x, 0, w - x, TABLE_HDR_H),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       label)


# ════════════════════════════════════════════════════════════════════════════
# Right detail panel — tabs + content
# ════════════════════════════════════════════════════════════════════════════

class _DetailTab(QPushButton):
    """One tab on the right detail panel."""

    def __init__(self, label: str, parent=None):
        super().__init__("", parent)
        self._label = label
        self._active = False
        self._hover = False
        fm = QFontMetrics(inter(11, QFont.Weight.DemiBold))
        self.setFixedSize(fm.horizontalAdvance(label) + 32, 36)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFlat(True)
        self.setStyleSheet("background: transparent; border: none;")

    def set_active(self, active: bool):
        self._active = active
        self.update()

    def enterEvent(self, e): self._hover = True;  self.update(); super().enterEvent(e)
    def leaveEvent(self, e): self._hover = False; self.update(); super().leaveEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        if self._active:
            tint = QColor(GREEN); tint.setAlphaF(0.10)
            p.fillRect(QRectF(0, 0, w, h), tint)
            p.fillRect(QRectF(0, h - 2, w, 2), QColor(GREEN))
            p.setPen(QColor(GREEN_LIGHT))
        elif self._hover:
            p.setPen(QColor(TEXT_PRI))
        else:
            p.setPen(QColor(TEXT_MUTED))
        p.setFont(inter(11, QFont.Weight.DemiBold, letter_spacing=0.4))
        p.drawText(QRectF(0, 0, w, h),
                   Qt.AlignmentFlag.AlignCenter, self._label)


class _CampaignHeaderCard(QFrame):
    """Top card in the Campaign Details tab — $ icon + name + meta + Active dot."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._campaign: dict = {}
        self.setFixedHeight(72)
        self.setStyleSheet(
            f"QFrame {{ background: #0d0f20; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; "
            f"border-radius: 8px; }}"
        )

    def set_campaign(self, c: dict):
        self._campaign = c or {}
        self.update()

    def paintEvent(self, _e):
        super().paintEvent(_e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Orange $ icon (rounded square w/ gradient)
        icon = QRectF(14, 14, 44, 44)
        path = QPainterPath(); path.addRoundedRect(icon, 10, 10)
        p.setClipPath(path)
        g = QLinearGradient(icon.topLeft(), icon.bottomRight())
        g.setColorAt(0.0, QColor("#fbbf24"))
        g.setColorAt(1.0, QColor("#d97706"))
        p.fillRect(icon, QBrush(g))
        p.setClipping(False)
        p.setPen(QColor("#1f1102"))
        p.setFont(inter(22, QFont.Weight.Black, letter_spacing=-0.5))
        p.drawText(icon, Qt.AlignmentFlag.AlignCenter, "$")

        # Name
        name = self._campaign.get("name") or "—"
        p.setPen(QColor(TEXT_PRI))
        p.setFont(inter(15, QFont.Weight.Bold))
        p.drawText(QRectF(70, 8, self.width() - 80, 22),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   name)

        # Meta line
        cat   = self._campaign.get("category") or "—"
        files = int(self._campaign.get("file_count") or 0)
        pri   = self._campaign.get("priority") or "—"
        meta = f"{cat}  ·  {files} spot file{'s' if files != 1 else ''}  ·  {pri} priority"
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(inter(10))
        p.drawText(QRectF(70, 30, self.width() - 80, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   meta)

        # Active pill + expires line
        is_active = bool(self._campaign.get("is_currently_active", 1))
        dot_x, dot_y = 70, 52
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(GREEN if is_active else RED))
        p.drawEllipse(dot_x, dot_y, 6, 6)
        p.setPen(QColor(GREEN_LIGHT if is_active else RED_LIGHT))
        p.setFont(inter(9, QFont.Weight.Bold, letter_spacing=0.6))
        p.drawText(QRectF(dot_x + 12, dot_y - 4, 80, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "Active" if is_active else "Expired")

        end = self._campaign.get("end_date")
        if end:
            p.setPen(QColor(TEXT_MUTED))
            p.setFont(inter(9))
            p.drawText(QRectF(150, 48, self.width() - 160, 14),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       f"Expires: {_fmt_date(end)}")


class _ReadonlyField(QFrame):
    """Label + read-only display value — used on the Details tab."""

    def __init__(self, label: str, value: str = "—", parent=None):
        super().__init__(parent)
        self._label = label
        self._value = value
        self.setFixedHeight(46)
        self.setStyleSheet("background: transparent;")

    def set_value(self, v: str):
        self._value = v or "—"
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Label
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(inter(9, QFont.Weight.Medium))
        p.drawText(QRectF(0, 0, self.width(), 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._label)
        # Value box
        rect = QRectF(0, 16, self.width(), 26)
        path = QPainterPath(); path.addRoundedRect(rect, 5, 5)
        p.setClipPath(path)
        p.fillRect(rect, QColor(BG_CARD))
        p.setClipping(False)
        bc = QColor(255, 255, 255, 14)
        p.setPen(QPen(bc, 1)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 5, 5)
        p.setPen(QColor(TEXT_PRI))
        p.setFont(inter(11))
        p.drawText(QRectF(rect.x() + 8, rect.y(), rect.width() - 16, rect.height()),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._value)


class _SpotFileRow(QFrame):
    """One spot-file entry inside the SPOT FILES section."""

    def __init__(self, spot: dict, parent=None):
        super().__init__(parent)
        self._spot = spot
        self.setFixedHeight(28)
        self.setStyleSheet(
            f"QFrame {{ background: #0c0e1c; "
            f"border: 1px solid {rgba('#ffffff', 0.04)}; "
            f"border-radius: 5px; }}"
        )

    def paintEvent(self, _e):
        super().paintEvent(_e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # ● green dot
        p.setBrush(QColor(GREEN)); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(10, 10, 6, 6)
        # Filename
        p.setPen(QColor(TEXT_PRI))
        p.setFont(inter(10, QFont.Weight.Medium))
        fname = self._spot.get("filename") or self._spot.get("file_path") or "—"
        import os as _os
        if "/" in fname or "\\" in fname:
            fname = _os.path.basename(fname)
        p.drawText(QRectF(22, 0, self.width() - 220, self.height()),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   fname)
        # Duration
        dur = _fmt_duration_short(self._spot.get("duration_ms") or 0)
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(mono(9, bold=True))
        p.drawText(QRectF(self.width() - 110, 0, 50, self.height()),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   dur)
        # Active pill
        is_active = bool(self._spot.get("is_active", 1))
        pill = QRectF(self.width() - 56, 6, 46, 16)
        bg = QColor(GREEN if is_active else TEXT_DIM); bg.setAlphaF(0.20)
        p.setBrush(bg); p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(pill, 8, 8)
        p.setPen(QColor(GREEN_LIGHT if is_active else TEXT_MUTED))
        p.setFont(inter(8, QFont.Weight.Bold, letter_spacing=0.5))
        p.drawText(pill, Qt.AlignmentFlag.AlignCenter,
                   "Active" if is_active else "Off")


class _WeeklyBreakGrid(QFrame):
    """Compact 7×6 visualization of the campaign's break schedule.

    Tab-2 read-only summary — actual editing happens in the Spot Programming
    dialog (session 2). Cells are 'lit' amber if any schedule entry falls in
    that day×hour cell, dim otherwise. Hours used: 06, 09, 12, 15, 18, 21."""

    HOURS = [6, 9, 12, 15, 18, 21]
    DAYS  = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._schedule: list[dict] = []
        self.setMinimumHeight(170)

    def set_schedule(self, schedule: list[dict]):
        self._schedule = schedule or []
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        # Geometry
        col_w = (w - 12) / 7
        hdr_h = 18
        row_h = (h - hdr_h - 4) / len(self.HOURS)

        # Build a set of (day, hour) keys that are scheduled
        lit = set()
        for item in self._schedule:
            day = int(item.get("day_of_week") or 0)
            t   = item.get("break_time") or ""
            try:
                hh = int(t.split(":")[0])
            except Exception:
                continue
            # Snap to nearest header hour
            best = min(self.HOURS, key=lambda x: abs(x - hh))
            lit.add((day, best))

        # Day-of-week header
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(inter(8, QFont.Weight.Bold, letter_spacing=0.6))
        for c, label in enumerate(self.DAYS):
            x0 = 6 + c * col_w
            p.drawText(QRectF(x0, 0, col_w, hdr_h),
                       Qt.AlignmentFlag.AlignCenter, label)

        # Cells
        for r, hh in enumerate(self.HOURS):
            for c in range(7):
                x0 = 6 + c * col_w + 2
                y0 = hdr_h + r * row_h + 2
                cell = QRectF(x0, y0, col_w - 4, row_h - 4)
                key = (c, hh)
                if key in lit:
                    bg = QColor(AMBER); bg.setAlphaF(0.30)
                    p.setBrush(bg); p.setPen(Qt.PenStyle.NoPen)
                    p.drawRoundedRect(cell, 3, 3)
                    p.setPen(QColor(AMBER_LIGHT))
                else:
                    bg = QColor(255, 255, 255, 6)
                    p.setBrush(bg); p.setPen(Qt.PenStyle.NoPen)
                    p.drawRoundedRect(cell, 3, 3)
                    p.setPen(QColor(TEXT_DIM))
                p.setFont(mono(8, bold=False))
                p.drawText(cell, Qt.AlignmentFlag.AlignCenter,
                           f"{hh:02d}:00")


class _AIInsightBar(QFrame):
    """Purple-gradient AI insights box at the bottom of Tab 1."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(98)
        self._on_track = "Campaign performing above target — 89% delivery"
        self._conflict = "Friday 09:00 has 5 overlapping high-priority spots"

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0, 0, self.width(), self.height())
        path = QPainterPath(); path.addRoundedRect(rect, 8, 8)
        p.setClipPath(path)
        c1 = QColor(PURPLE); c1.setAlphaF(0.18)
        c2 = QColor(PURPLE_DARK); c2.setAlphaF(0.10)
        g = QLinearGradient(0, 0, 0, self.height())
        g.setColorAt(0.0, c1); g.setColorAt(1.0, c2)
        p.fillRect(rect, QBrush(g))
        p.setClipping(False)
        bc = QColor(PURPLE); bc.setAlphaF(0.40)
        p.setPen(QPen(bc, 1)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 8, 8)
        # Header
        p.setPen(QColor(PURPLE_LIGHT))
        p.setFont(inter(10, QFont.Weight.Bold, letter_spacing=1.0))
        p.drawText(QRectF(12, 6, self.width() - 24, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "✦ AI CAMPAIGN INSIGHTS")
        # On Track row
        p.setPen(QColor(GREEN_LIGHT))
        p.setFont(inter(10, QFont.Weight.Bold))
        p.drawText(QRectF(12, 28, 80, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "✓ On Track")
        p.setPen(QColor(TEXT_SEC))
        p.setFont(inter(9))
        p.drawText(QRectF(12, 42, self.width() - 24, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._on_track)
        # Conflict row
        p.setPen(QColor(RED_LIGHT))
        p.setFont(inter(10, QFont.Weight.Bold))
        p.drawText(QRectF(12, 60, 80, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "⚠ Conflict")
        p.setPen(QColor(TEXT_SEC))
        p.setFont(inter(9))
        p.drawText(QRectF(12, 74, self.width() - 24, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._conflict)


# ════════════════════════════════════════════════════════════════════════════
# Now Airing strip
# ════════════════════════════════════════════════════════════════════════════

class _NowAiring(QFrame):
    """Compact 'currently playing' strip below the table.

    Phase B3: wired to AudioEngine. The left-edge play/stop button
    triggers manual playback of the selected campaign's first spot file.
    Progress bar + duration text are driven by engine.position_changed
    via set_progress / set_duration_text. AutoPlay pill is unchanged —
    Phase D scheduler will wire it.
    """

    play_clicked = pyqtSignal()    # emitted when the ▶/■ button is clicked

    PLAY_BTN_X = 10
    PLAY_BTN_W = 30
    PLAY_BTN_H = 30

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(NOW_AIRING_H)
        self.setStyleSheet(
            f"QFrame {{ background: #0c0e1c; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; "
            f"border-radius: 8px; }}"
        )
        self._campaign_name = "—"
        self._progress = 0.0
        self._duration_text = "0:00 / 0:00"
        self._playing = False
        self._hover_play = False
        self.setMouseTracking(True)

    # ── Public API (Phase B3) ─────────────────────────────────────────────

    def set_campaign(self, name: str) -> None:
        self._campaign_name = name or "—"
        self.update()

    def set_progress(self, fraction: float) -> None:
        f = max(0.0, min(1.0, float(fraction)))
        if abs(self._progress - f) < 0.001:
            return
        self._progress = f
        self.update()

    def set_duration_text(self, text: str) -> None:
        self._duration_text = text or "0:00 / 0:00"
        self.update()

    def set_playing(self, playing: bool) -> None:
        if self._playing == playing:
            return
        self._playing = playing
        if not playing:
            # Reset progress visual when not playing — looks cleaner than
            # leaving the bar half-full on stop.
            self._progress = 0.0
            self._duration_text = "0:00 / 0:00"
        self.update()

    # ── Hit-testing for the play button ──────────────────────────────────

    def _play_btn_rect(self) -> QRectF:
        return QRectF(
            self.PLAY_BTN_X,
            (NOW_AIRING_H - self.PLAY_BTN_H) / 2,
            self.PLAY_BTN_W,
            self.PLAY_BTN_H,
        )

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            if self._play_btn_rect().contains(e.position()):
                self.play_clicked.emit()
                return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        over = self._play_btn_rect().contains(e.position())
        if over != self._hover_play:
            self._hover_play = over
            self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor if over
                                   else Qt.CursorShape.ArrowCursor))
            self.update(self._play_btn_rect().toRect())
        super().mouseMoveEvent(e)

    def leaveEvent(self, e):
        if self._hover_play:
            self._hover_play = False
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
            self.update(self._play_btn_rect().toRect())
        super().leaveEvent(e)

    # ── Paint ─────────────────────────────────────────────────────────────

    def paintEvent(self, _e):
        super().paintEvent(_e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # ── Play / stop button (left edge, replaces the static dot) ─────
        btn = self._play_btn_rect()
        accent = QColor(RED if self._playing else GREEN)
        bg = QColor(accent); bg.setAlphaF(0.32 if self._hover_play else 0.20)
        path = QPainterPath(); path.addRoundedRect(btn, 6, 6)
        p.setClipPath(path)
        p.fillRect(btn, bg)
        p.setClipping(False)
        bc = QColor(accent); bc.setAlphaF(0.55)
        p.setPen(QPen(bc, 1)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(btn, 6, 6)
        p.setPen(QColor(accent))
        p.setFont(inter(13, QFont.Weight.Bold))
        p.drawText(btn, Qt.AlignmentFlag.AlignCenter,
                   "■" if self._playing else "▶")

        # NOW AIRING label (shifted right to make room for play button)
        label_x = self.PLAY_BTN_X + self.PLAY_BTN_W + 8
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(inter(8, QFont.Weight.Bold, letter_spacing=1.4))
        p.drawText(QRectF(label_x, 6, 100, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "NOW AIRING")
        # Campaign name
        p.setPen(QColor(GREEN_LIGHT))
        p.setFont(inter(11, QFont.Weight.DemiBold))
        p.drawText(QRectF(label_x, 22, 240, 18),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._campaign_name)

        # Progress bar (centre)
        bar = QRectF(290, NOW_AIRING_H // 2 - 3, self.width() - 470, 6)
        path = QPainterPath(); path.addRoundedRect(bar, 3, 3)
        p.setClipPath(path)
        p.fillRect(bar, QColor("#0a0c18"))
        fill = QRectF(bar.x(), bar.y(),
                      bar.width() * self._progress, bar.height())
        g = QLinearGradient(fill.topLeft(), fill.topRight())
        g.setColorAt(0.0, QColor(GREEN)); g.setColorAt(1.0, QColor(CYAN))
        p.fillRect(fill, QBrush(g))
        p.setClipping(False)

        # Duration text (right of bar)
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(mono(10, bold=True))
        p.drawText(QRectF(self.width() - 170, 0, 70, NOW_AIRING_H),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   self._duration_text)

        # AutoPlay ON pill (right edge — unchanged; Phase D will wire it)
        pill = QRectF(self.width() - 92, NOW_AIRING_H // 2 - 11, 80, 22)
        bg = QColor(AMBER); bg.setAlphaF(0.18)
        p.setBrush(bg); p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(pill, 10, 10)
        p.setPen(QColor(AMBER_LIGHT))
        p.setFont(inter(9, QFont.Weight.Bold, letter_spacing=0.6))
        p.drawText(pill, Qt.AlignmentFlag.AlignCenter, "AutoPlay ON")


# ════════════════════════════════════════════════════════════════════════════
# Main screen
# ════════════════════════════════════════════════════════════════════════════

class SpotsCommercials(QWidget):

    breadcrumb_clicked    = pyqtSignal(str)
    studio_clicked        = pyqtSignal()
    add_campaign_clicked  = pyqtSignal()
    edit_breaks_clicked   = pyqtSignal(int)   # campaign_id
    campaign_selected     = pyqtSignal(int)

    def __init__(self, db, parent=None, engine=None):
        super().__init__(parent)
        self._db = db
        self._engine = engine    # shared AudioEngine (Phase B Option C)

        # State
        self._campaigns: list[dict] = []
        self._row_widgets: list[_CampaignRow] = []
        self._selected_id: Optional[int] = None
        self._filter: str = "all"

        # Phase B3 Now-Airing playback state — channel separate from
        # SongsLibrary._preview_cid and AudioCueEditorDialog._playback_cid
        # so all three UIs can audition simultaneously (Q2 contract).
        self._airing_cid: Optional[int] = None
        self._airing_campaign_id: Optional[int] = None
        self._airing_spot_path: Optional[str] = None
        self._airing_duration_ms: int = 0

        # Refs
        self._table_layout: Optional[QVBoxLayout] = None
        self._counter:      Optional[_SidebarCounter] = None
        self._clock_lbl:    Optional[QLabel] = None
        self._header_card:  Optional[_CampaignHeaderCard] = None
        self._fields:       dict = {}
        self._spot_files_box: Optional[QFrame] = None
        self._spot_files_layout: Optional[QVBoxLayout] = None
        self._weekly_grid:  Optional[_WeeklyBreakGrid] = None
        self._now_airing:   Optional[_NowAiring] = None
        self._tab_buttons:  list[_DetailTab] = []
        self._status_count: Optional[QLabel] = None

        self.setFixedSize(WINDOW_W, WINDOW_H)
        self.setStyleSheet(
            "background: qlineargradient("
            "x1:0, y1:0, x2:1, y2:1, "
            "stop:0 #0a0d1a, stop:0.5 #06080f, stop:1 #020308);"
        )

        # Run migration so the new columns are visible
        try:
            self._db._ensure_campaigns_columns()
        except Exception as exc:
            log.error(f"campaigns migration failed: {exc}")

        self._build_header()
        self._build_sidebar()
        self._build_table()
        self._build_now_airing()
        self._build_right_panel()
        self._build_status_bar()

        # Initial data load
        self._load_campaigns()

        # Live clock
        self._tick()
        t = QTimer(self)
        t.setInterval(1000); t.timeout.connect(self._tick); t.start()

        log.info("SpotsCommercials ready (Figma 35:2)")

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

        _HeaderLogo(self).move(14, 8)
        l = QLabel("RadioAI", self)
        l.setGeometry(60, 8, 120, 16)
        l.setFont(inter(14, QFont.Weight.Bold))
        l.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        l = QLabel("STUDIO PRO", self)
        l.setGeometry(60, 26, 120, 12)
        l.setFont(inter(8, QFont.Weight.Bold, letter_spacing=1.2))
        l.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

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

        chip = _ActiveBreadcrumbChip("Spots & Commercials", self)
        chip.move(334, 11)

        # Title
        l = QLabel("Spots & Commercials Library", self)
        l.setGeometry(508, 4, 380, 22)
        l.setFont(inter(18, QFont.Weight.Bold))
        l.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        l = QLabel("Manage campaigns, break schedules & spot priorities", self)
        l.setGeometry(508, 26, 460, 16)
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

        osb = _HeaderOpenStudio(self)
        osb.move(1218, 8)
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

        # Action buttons — order matters for discoverability:
        #   Add → Edit Campaign → Schedule Breaks → Break Settings → Delete
        # "Edit Breaks" was renamed to "Schedule Breaks" to disambiguate
        # from the new "Edit Campaign" action (both could read as "edit").
        actions = [
            ("+ Add Campaign",    GREEN,        "#052e16", self._on_add_campaign),
            ("✎ Edit Campaign",   CYAN,         "#083344", self._on_edit_campaign),
            ("🗓 Schedule Breaks", AMBER,        "#2d1a00", self._on_edit_breaks),
            ("⚙ Break Settings",  PURPLE_LIGHT, "#1e1535", self._on_break_settings),
            ("✕ Delete",          RED,          "#1f0a12", self._on_delete_campaign),
        ]
        y0 = HEADER_H + 60
        for i, (txt, color, bg_tint, slot) in enumerate(actions):
            btn = _SidebarActionButton(txt, color, bg_tint, self)
            btn.move(12, y0 + i * 32)
            btn.clicked.connect(slot)

        # FILTERS section
        fl_y = y0 + 4 * 32 + 16
        l = QLabel("FILTERS", self)
        l.setGeometry(12, fl_y, 80, 14)
        l.setFont(inter(8, QFont.Weight.Bold, letter_spacing=1.2))
        l.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

        filter_specs = [
            ("all",      ["All Campaigns"]),
            ("status",   ["Active Only", "Expired Only", "All Status"]),
            ("category", ["Category (All)", "Commercials", "Station ID",
                          "News Break", "Sponsor", "Promo"]),
            ("priority", ["Priority (All)", "High", "Medium", "Low", "Always"]),
            ("day",      ["Day (All)", "Mon", "Tue", "Wed", "Thu", "Fri",
                          "Sat", "Sun"]),
        ]
        self._filter_combos: dict[str, QComboBox] = {}
        for i, (key, items) in enumerate(filter_specs):
            cb = self._make_filter_combo(items)
            cb.setParent(self)
            cb.setGeometry(12, fl_y + 18 + i * 30, SIDEBAR_W - 24, 26)
            self._filter_combos[key] = cb
        self._filter_combos["status"].currentIndexChanged.connect(
            self._on_status_filter_changed)

        # REPORTS section
        rp_y = fl_y + 18 + 5 * 30 + 14
        l = QLabel("REPORTS", self)
        l.setGeometry(12, rp_y, 80, 14)
        l.setFont(inter(8, QFont.Weight.Bold, letter_spacing=1.2))
        l.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        reports = [
            ("$ Actual Play Times",     GREEN),
            ("📅 Spot Schedule",         CYAN),
            ("📊 Daily Programming",     PURPLE_LIGHT),
            ("⏱ Break Duration Check",  AMBER),
            ("⇆ Traffic Integration",   TEAL_LIGHT),
        ]
        for i, (txt, color) in enumerate(reports):
            btn = _SidebarActionButton(txt, color, "#0a0c18", self)
            btn.move(12, rp_y + 18 + i * 26)

    def _make_filter_combo(self, items: list) -> QComboBox:
        c = QComboBox()
        c.addItems(items)
        c.setFont(inter(9))
        c.setStyleSheet(
            f"QComboBox {{ background: {BG_CARD}; color: {TEXT_SEC}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; border-radius: 5px; "
            f"padding-left: 9px; padding-right: 22px; }}"
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
        return c

    # ── TABLE ────────────────────────────────────────────────────────────

    def _build_table(self):
        # Header strip
        hdr = _TableHeader(self)
        hdr.setGeometry(TABLE_X0, HEADER_H, TABLE_W, TABLE_HDR_H)

        # Scrollable body
        scroll = QScrollArea(self)
        scroll.setGeometry(TABLE_X0, HEADER_H + TABLE_HDR_H,
                           TABLE_W, WINDOW_H - HEADER_H - TABLE_HDR_H
                           - NOW_AIRING_H - STATUS_H - 22)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
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

    # ── NOW AIRING ───────────────────────────────────────────────────────

    def _build_now_airing(self):
        self._now_airing = _NowAiring(self)
        na_y = WINDOW_H - STATUS_H - NOW_AIRING_H - 18
        self._now_airing.setGeometry(TABLE_X0, na_y, TABLE_W, NOW_AIRING_H)
        # Phase B3: wire the play/stop button + engine signals
        self._now_airing.play_clicked.connect(self._on_airing_play_clicked)
        if self._engine is not None:
            self._engine.position_changed.connect(self._on_airing_position)
            self._engine.playback_ended.connect(self._on_airing_playback_ended)
            self._engine.error_occurred.connect(self._on_airing_error)

    # ── RIGHT DETAIL PANEL ───────────────────────────────────────────────

    def _build_right_panel(self):
        wrap = QFrame(self)
        wrap.setGeometry(RIGHT_X, HEADER_H + 4, RIGHT_W,
                         WINDOW_H - HEADER_H - STATUS_H - 12)
        wrap.setStyleSheet(
            f"QFrame {{ background: #0a0c18; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; "
            f"border-radius: 10px; }}"
        )

        # Tabs row
        tabs_row = QFrame(wrap); tabs_row.setStyleSheet("background: transparent;")
        tabs_row.setGeometry(0, 0, RIGHT_W, 38)
        tabs_layout = QHBoxLayout(tabs_row)
        tabs_layout.setContentsMargins(8, 0, 8, 0); tabs_layout.setSpacing(2)
        for i, label in enumerate(["Campaign Details", "Break Schedule",
                                    "Play Reports"]):
            t = _DetailTab(label)
            t.set_active(i == 0)
            t.clicked.connect(lambda _checked=False, idx=i: self._switch_tab(idx))
            tabs_layout.addWidget(t)
            self._tab_buttons.append(t)
        tabs_layout.addStretch()

        # Content scroll area
        self._tab_content = QScrollArea(wrap)
        self._tab_content.setGeometry(0, 38, RIGHT_W, wrap.height() - 38)
        self._tab_content.setWidgetResizable(True)
        self._tab_content.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._tab_content.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._tab_content.setFrameShape(QFrame.Shape.NoFrame)
        self._tab_content.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            f"QScrollBar:vertical {{ background: {rgba('#ffffff', 0.02)}; "
            f"width: 6px; }}"
            f"QScrollBar::handle:vertical {{ background: {rgba(GREEN, 0.45)}; "
            f"border-radius: 3px; min-height: 24px; }}"
            "QScrollBar::add-line, QScrollBar::sub-line { height: 0; }"
        )

        # Tab 1 content (initial)
        self._build_tab_details()

    def _build_tab_details(self):
        c = QFrame(); c.setStyleSheet("background: transparent;")
        v = QVBoxLayout(c)
        v.setContentsMargins(12, 10, 12, 12); v.setSpacing(12)

        # Campaign header card
        self._header_card = _CampaignHeaderCard()
        v.addWidget(self._header_card)

        # Form fields
        fields_box = QFrame(); fields_box.setStyleSheet("background: transparent;")
        fv = QVBoxLayout(fields_box); fv.setContentsMargins(0, 0, 0, 0)
        fv.setSpacing(6)
        for key, label in [
            ("name",             "Campaign Name"),
            ("start_date",       "Start Date"),
            ("end_date",         "End Date"),
            ("programming_mode", "Programming Mode"),
            ("playback_order",   "Playback Order"),
            ("category",         "Category"),
            ("priority",         "Priority Level"),
        ]:
            f = _ReadonlyField(label)
            self._fields[key] = f
            fv.addWidget(f)
        v.addWidget(fields_box)

        # SPOT FILES
        sf_hdr = QFrame(); sf_hdr.setStyleSheet("background: transparent;")
        sf_hdr.setFixedHeight(20)
        sf_layout = QHBoxLayout(sf_hdr)
        sf_layout.setContentsMargins(0, 0, 0, 0); sf_layout.setSpacing(6)
        sf_label = QLabel("SPOT FILES")
        sf_label.setFont(inter(8, QFont.Weight.Bold, letter_spacing=1.2))
        sf_label.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        sf_layout.addWidget(sf_label)
        sf_layout.addStretch()
        add_file_btn = QPushButton("+ Add File")
        add_file_btn.setFixedHeight(20)
        add_file_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        add_file_btn.setFont(inter(9, QFont.Weight.Bold))
        add_file_btn.setStyleSheet(
            f"QPushButton {{ background: {rgba(GREEN, 0.18)}; color: {GREEN_LIGHT}; "
            f"border: 1px solid {rgba(GREEN, 0.40)}; border-radius: 4px; "
            f"padding: 0 8px; }}"
            f"QPushButton:hover {{ background: {rgba(GREEN, 0.28)}; }}"
        )
        add_file_btn.clicked.connect(self._on_add_file)
        sf_layout.addWidget(add_file_btn)
        v.addWidget(sf_hdr)

        self._spot_files_box = QFrame()
        self._spot_files_box.setStyleSheet("background: transparent;")
        self._spot_files_layout = QVBoxLayout(self._spot_files_box)
        self._spot_files_layout.setContentsMargins(0, 0, 0, 0)
        self._spot_files_layout.setSpacing(4)
        v.addWidget(self._spot_files_box)

        # WEEKLY BREAK SCHEDULE
        wk_label = QLabel("WEEKLY BREAK SCHEDULE")
        wk_label.setFont(inter(8, QFont.Weight.Bold, letter_spacing=1.2))
        wk_label.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        v.addWidget(wk_label)
        self._weekly_grid = _WeeklyBreakGrid()
        v.addWidget(self._weekly_grid)

        # AI insights
        v.addWidget(_AIInsightBar())
        v.addStretch()

        self._tab_content.setWidget(c)

    # ── Play Reports tab (Figma 412:2) ───────────────────────────────────

    def _build_tab_play_reports(self) -> None:
        """Replaces the stub Play Reports tab with the Figma 412:2 form:
        campaign info card + mode toggle + date range + Generate button.
        Lazy import on the report generator so the heavy QPdfWriter chain
        doesn't load until the operator actually opens this tab."""
        from PyQt6.QtWidgets import (
            QButtonGroup, QDateEdit, QRadioButton, QFormLayout, QFileDialog,
        )
        from PyQt6.QtCore import QDate
        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl
        from datetime import date as _dt_date, datetime as _dt
        from pathlib import Path as _Path
        from core.reports import (
            generate_spot_play_report, SpotPlayReportError,
            REPORT_MODE_ACTUAL, REPORT_MODE_SCHEDULED, DEFAULT_REPORT_DIR,
        )

        c = QFrame()
        c.setStyleSheet("background: transparent;")
        v = QVBoxLayout(c)
        v.setContentsMargins(16, 12, 16, 16)
        v.setSpacing(14)

        # Resolve current campaign + dates
        campaign = next(
            (cm for cm in self._campaigns if cm.get("id") == self._selected_id),
            None) if self._selected_id else None
        if not campaign:
            empty = QLabel(
                "Select a campaign in the list to generate a report.")
            empty.setFont(inter(11, QFont.Weight.Medium))
            empty.setStyleSheet(
                f"color: {TEXT_MUTED}; background: transparent;")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            v.addWidget(empty); v.addStretch()
            self._tab_content.setWidget(c)
            return

        # ── CAMPAIGN section ──
        sect_lbl = QLabel("CAMPAIGN")
        sect_lbl.setFont(inter(10, QFont.Weight.Bold, letter_spacing=1.4))
        sect_lbl.setStyleSheet(
            f"color: {PURPLE_LIGHT}; background: transparent; "
            f"padding: 4px 12px;")
        sect_lbl.setFixedHeight(24)
        v.addWidget(sect_lbl)

        info = QFrame()
        info.setStyleSheet(
            f"background: {BG_CARD}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; "
            f"border-radius: 8px;")
        info.setFixedHeight(76)
        ih = QHBoxLayout(info)
        ih.setContentsMargins(14, 10, 14, 10); ih.setSpacing(12)
        # $ icon
        icon = QLabel("$")
        icon.setFixedSize(48, 48)
        icon.setFont(inter(24, QFont.Weight.Bold))
        icon.setStyleSheet(
            f"QLabel {{ background: {rgba(AMBER, 0.18)}; color: {AMBER_LIGHT}; "
            f"border: 1px solid {rgba(AMBER, 0.30)}; "
            f"border-radius: 10px; }}")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ih.addWidget(icon)
        # Right column
        col = QVBoxLayout(); col.setContentsMargins(0, 0, 0, 0); col.setSpacing(2)
        name_row = QHBoxLayout(); name_row.setContentsMargins(0, 0, 0, 0)
        name_row.setSpacing(8)
        name_lbl = QLabel(str(campaign.get("name") or "Untitled"))
        name_lbl.setFont(inter(15, QFont.Weight.Bold))
        name_lbl.setStyleSheet(
            f"color: {TEXT_PRI}; background: transparent;")
        name_row.addWidget(name_lbl)
        # Auto code pill
        auto_code = (campaign.get("auto_code") or "").strip()
        if auto_code:
            pill = QLabel(f"#{auto_code}")
            pill.setFont(mono(10, bold=True))
            pill.setStyleSheet(
                f"QLabel {{ background: {rgba(GREEN, 0.16)}; "
                f"color: {GREEN_LIGHT}; "
                f"border: 1px solid {rgba(GREEN, 0.40)}; "
                f"border-radius: 4px; padding: 1px 8px; }}")
            name_row.addWidget(pill)
        name_row.addStretch()
        col.addLayout(name_row)
        # Status / dates
        active = bool(campaign.get("is_currently_active", 1))
        status = "● Active" if active else "○ Expired"
        sd = campaign.get("start_date") or "?"
        ed = campaign.get("end_date") or "?"
        meta_lbl = QLabel(f"{status}  ·  {_fmt_date(sd)} → {_fmt_date(ed)}")
        meta_lbl.setFont(inter(10, QFont.Weight.Medium))
        meta_lbl.setStyleSheet(
            f"color: {GREEN_LIGHT if active else TEXT_MUTED}; "
            f"background: transparent;")
        col.addWidget(meta_lbl)
        # Spot files line
        try:
            sfs = self._db.get_spot_files(int(campaign["id"]))
        except Exception:
            sfs = []
        total_dur_ms = sum(int(s["duration_ms"] or 0) for s in sfs)
        total_dur_s = total_dur_ms // 1000
        files_lbl = QLabel(
            f"{len(sfs)} spot file{'s' if len(sfs) != 1 else ''}  ·  "
            f"{total_dur_s} sec total")
        files_lbl.setFont(inter(9, QFont.Weight.Medium))
        files_lbl.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent;")
        col.addWidget(files_lbl)
        ih.addLayout(col, 1)
        v.addWidget(info)

        # ── REPORT MODE section ──
        sect2 = QLabel("REPORT MODE")
        sect2.setFont(inter(10, QFont.Weight.Bold, letter_spacing=1.4))
        sect2.setStyleSheet(
            f"color: {CYAN_LIGHT}; background: transparent; "
            f"padding: 4px 12px;")
        sect2.setFixedHeight(24)
        v.addWidget(sect2)

        mode_row = QHBoxLayout(); mode_row.setSpacing(8)
        self._report_mode_group = QButtonGroup(c)

        def _mode_radio(label: str, sub: str, mode_val: str,
                        accent_hex: str, default: bool):
            b = QRadioButton(label)
            b.setFont(inter(12, QFont.Weight.Bold))
            b.setStyleSheet(
                f"QRadioButton {{ color: {TEXT_PRI}; background: {BG_CARD}; "
                f"border: 1px solid {rgba(accent_hex, 0.30 if default else 0.15)}; "
                f"border-radius: 8px; padding: 12px 12px 28px 36px; }}"
                f"QRadioButton:checked {{ "
                f"  background: {rgba(accent_hex, 0.10)}; "
                f"  border: 1.5px solid {rgba(accent_hex, 0.55)}; }}"
                f"QRadioButton::indicator {{ width: 14px; height: 14px; "
                f"  border: 1.5px solid {rgba(accent_hex, 0.40)}; "
                f"  border-radius: 7px; "
                f"  background: {BG_BASE}; }}"
                f"QRadioButton::indicator:checked {{ "
                f"  background: {accent_hex}; "
                f"  border: 4px solid {BG_BASE}; }}"
            )
            b.setMinimumHeight(74)
            b.setProperty("mode", mode_val)
            b.setChecked(default)
            b.setToolTip(sub)
            self._report_mode_group.addButton(b)
            return b

        rb_actual = _mode_radio(
            "Actual Broadcast",
            "What actually played — pulled from broadcast_log",
            REPORT_MODE_ACTUAL, CYAN, default=False)
        rb_sched = _mode_radio(
            "Scheduled Broadcast",
            "What was planned — expanded from campaign_schedule",
            REPORT_MODE_SCHEDULED, AMBER, default=True)
        mode_row.addWidget(rb_actual)
        mode_row.addWidget(rb_sched)
        v.addLayout(mode_row)

        # ── DATE RANGE section ──
        sect3 = QLabel("DATE RANGE")
        sect3.setFont(inter(10, QFont.Weight.Bold, letter_spacing=1.4))
        sect3.setStyleSheet(
            f"color: {GREEN}; background: transparent; padding: 4px 12px;")
        sect3.setFixedHeight(24)
        v.addWidget(sect3)

        dt_row = QHBoxLayout(); dt_row.setSpacing(8)

        def _date_input(label: str, iso_str: str) -> tuple[QFrame, QDateEdit]:
            f = QFrame()
            f.setStyleSheet("background: transparent;")
            fl = QVBoxLayout(f)
            fl.setContentsMargins(0, 0, 0, 0); fl.setSpacing(6)
            l = QLabel(label.upper())
            l.setFont(inter(9, QFont.Weight.Bold, letter_spacing=1.0))
            l.setStyleSheet(
                f"color: {TEXT_MUTED}; background: transparent;")
            fl.addWidget(l)
            de = QDateEdit()
            de.setCalendarPopup(True)
            de.setDisplayFormat("dd / MM / yyyy")
            try:
                yr, mo, da = map(int, str(iso_str).split("-"))
                de.setDate(QDate(yr, mo, da))
            except (ValueError, AttributeError):
                de.setDate(QDate.currentDate())
            de.setStyleSheet(
                f"QDateEdit {{ background: {BG_CARD}; color: {TEXT_PRI}; "
                f"border: 1px solid {rgba('#ffffff', 0.06)}; "
                f"border-radius: 6px; padding: 6px 10px; }}"
                f"QDateEdit:focus {{ border-color: {rgba(CYAN, 0.45)}; }}"
                f"QDateEdit::drop-down {{ border: none; width: 22px; }}"
                f"QDateEdit::down-arrow {{ image: none; width: 0; "
                f"  border-left: 4px solid transparent; "
                f"  border-right: 4px solid transparent; "
                f"  border-top: 5px solid {TEXT_MUTED}; "
                f"  margin-right: 6px; }}"
            )
            de.setFixedHeight(36)
            de.setFont(inter(11, QFont.Weight.Bold))
            # Style the popup calendar (QDateEdit's setCalendarPopup
            # creates a QCalendarWidget under the global app stylesheet
            # which renders the date numbers near-black on near-black —
            # invisible on the operator's dark theme). Apply our own
            # palette directly so dates read clearly against a panel-
            # dark background.
            cw = de.calendarWidget()
            if cw is not None:
                cw.setStyleSheet(
                    f"QCalendarWidget QWidget {{ "
                    f"  background: {BG_PANEL}; color: {TEXT_PRI}; }}"
                    f"QCalendarWidget QToolButton {{ "
                    f"  background: {BG_CARD}; color: {TEXT_PRI}; "
                    f"  border: none; padding: 6px 10px; "
                    f"  border-radius: 4px; }}"
                    f"QCalendarWidget QToolButton:hover {{ "
                    f"  background: {rgba(CYAN, 0.18)}; "
                    f"  color: {CYAN_LIGHT}; }}"
                    f"QCalendarWidget QMenu {{ "
                    f"  background: {BG_CARD}; color: {TEXT_PRI}; "
                    f"  border: 1px solid {rgba('#ffffff', 0.10)}; }}"
                    f"QCalendarWidget QSpinBox {{ "
                    f"  background: {BG_CARD}; color: {TEXT_PRI}; "
                    f"  border: 1px solid {rgba('#ffffff', 0.10)}; "
                    f"  padding: 2px 6px; }}"
                    f"QCalendarWidget QAbstractItemView:enabled {{ "
                    f"  background: {BG_PANEL}; color: {TEXT_PRI}; "
                    f"  selection-background-color: {rgba(CYAN, 0.35)}; "
                    f"  selection-color: {TEXT_PRI}; "
                    f"  outline: none; }}"
                    f"QCalendarWidget QAbstractItemView:disabled {{ "
                    f"  color: {TEXT_DIM}; }}"
                )
            fl.addWidget(de)
            return f, de

        sd_box, self._report_start_de = _date_input(
            "Start Date", campaign.get("start_date") or "")
        ed_box, self._report_end_de = _date_input(
            "End Date", campaign.get("end_date") or "")
        dt_row.addWidget(sd_box, 1)
        dt_row.addWidget(ed_box, 1)
        v.addLayout(dt_row)

        # Reset link
        reset = QPushButton("↺  Reset to campaign window")
        reset.setFlat(True)
        reset.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        reset.setFont(inter(10, QFont.Weight.Medium))
        reset.setStyleSheet(
            f"QPushButton {{ color: {PURPLE_LIGHT}; "
            f"background: transparent; border: none; "
            f"text-align: left; padding: 0; }}"
            f"QPushButton:hover {{ color: {TEXT_PRI}; }}"
        )
        def _reset_dates():
            cur = next((cm for cm in self._campaigns
                        if cm.get("id") == self._selected_id), None)
            if not cur:
                return
            for iso, de in ((cur.get("start_date"), self._report_start_de),
                            (cur.get("end_date"),   self._report_end_de)):
                try:
                    yr, mo, da = map(int, str(iso).split("-"))
                    de.setDate(QDate(yr, mo, da))
                except (ValueError, AttributeError):
                    pass
        reset.clicked.connect(_reset_dates)
        v.addWidget(reset, 0, Qt.AlignmentFlag.AlignLeft)

        # ── GENERATE BUTTON ──
        gen = QPushButton("✦  GENERATE PDF REPORT")
        gen.setFixedHeight(48)
        gen.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        gen.setFont(inter(13, QFont.Weight.Bold, letter_spacing=1.4))
        gen.setStyleSheet(
            f"QPushButton {{ "
            f"  background: qlineargradient(x1:0,y1:0,x2:1,y2:0, "
            f"  stop:0 {CYAN}, stop:1 {PURPLE_LIGHT}); "
            f"  color: white; border: none; border-radius: 8px; }}"
            f"QPushButton:hover {{ "
            f"  background: qlineargradient(x1:0,y1:0,x2:1,y2:0, "
            f"  stop:0 {CYAN_LIGHT}, stop:1 {PURPLE}); }}"
        )
        # Footer status labels (declared up here so the closure can update them)
        last_lbl = QLabel("Last generated: (none)")
        last_lbl.setFont(inter(9, QFont.Weight.Medium))
        last_lbl.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent;")
        path_lbl = QLabel(f"Saved to: {DEFAULT_REPORT_DIR}")
        path_lbl.setFont(inter(9))
        path_lbl.setStyleSheet(
            f"color: {TEXT_DIM}; background: transparent;")

        def _on_generate():
            cur_id = self._selected_id
            if not cur_id:
                return
            checked = self._report_mode_group.checkedButton()
            mode_val = (checked.property("mode") if checked is not None
                        else REPORT_MODE_SCHEDULED)
            qd_s = self._report_start_de.date()
            qd_e = self._report_end_de.date()
            sd_py = _dt_date(qd_s.year(), qd_s.month(), qd_s.day())
            ed_py = _dt_date(qd_e.year(), qd_e.month(), qd_e.day())
            try:
                out = generate_spot_play_report(
                    int(cur_id), mode_val, sd_py, ed_py, db=self._db)
            except SpotPlayReportError as exc:
                QMessageBox.warning(
                    self, "Report failed", str(exc))
                return
            except Exception as exc:
                log.error(f"report generation failed: {exc}", exc_info=True)
                QMessageBox.critical(
                    self, "Report failed",
                    f"Could not generate report:\n\n{exc}")
                return
            last_lbl.setText(
                f"Last generated: {_dt.now().strftime('%d %b %Y %H:%M')}  "
                f"({mode_val})")
            path_lbl.setText(f"Saved to: {out}")
            # Verify the file is actually present + non-empty before
            # asking the OS to open it. Belt-and-suspenders against
            # any future writer-flush bug that lets us return early.
            import sys as _sys, os as _os
            try:
                size = out.stat().st_size
            except OSError:
                size = 0
            log.info(f"[reports] generated {out} ({size} bytes)")
            if size == 0:
                QMessageBox.warning(
                    self, "Report empty",
                    f"PDF was created but is 0 bytes:\n\n{out}\n\n"
                    f"Check the log for details.")
                return
            # Open with the OS default PDF handler. os.startfile is the
            # Windows-native shell-execute path — never races freshly-
            # written files. Falls back to QDesktopServices elsewhere.
            opened = False
            try:
                if _sys.platform == "win32" and hasattr(_os, "startfile"):
                    _os.startfile(str(out))   # type: ignore[attr-defined]
                    opened = True
                    log.info(f"[reports] opened via os.startfile")
            except Exception as exc:
                log.warning(f"[reports] os.startfile failed: {exc}")
            if not opened:
                ok = QDesktopServices.openUrl(QUrl.fromLocalFile(str(out)))
                log.info(
                    f"[reports] QDesktopServices.openUrl returned {ok}")
        gen.clicked.connect(_on_generate)
        v.addWidget(gen)

        # ── Footer ──
        v.addWidget(last_lbl)
        v.addWidget(path_lbl)
        v.addStretch()

        self._tab_content.setWidget(c)

    def _switch_tab(self, idx: int):
        for i, t in enumerate(self._tab_buttons):
            t.set_active(i == idx)
        if idx == 0:
            self._build_tab_details()
            self._refresh_detail_panel()
        elif idx == 2:
            self._build_tab_play_reports()
        else:
            # Tab 2 (Break Schedule editor) still stubbed
            stub = QFrame(); stub.setStyleSheet("background: transparent;")
            sv = QVBoxLayout(stub); sv.setContentsMargins(20, 60, 20, 20)
            l = QLabel("Break Schedule editor")
            l.setFont(inter(13, QFont.Weight.Bold))
            l.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
            l.setAlignment(Qt.AlignmentFlag.AlignCenter)
            sv.addWidget(l)
            l2 = QLabel(
                "Use ✎ Edit Breaks in the sidebar to open\n"
                "the full Spot Programming dialog (next session).")
            l2.setFont(inter(10))
            l2.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
            l2.setAlignment(Qt.AlignmentFlag.AlignCenter)
            sv.addWidget(l2)
            sv.addStretch()
            self._tab_content.setWidget(stub)

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
            l.setGeometry(x, 6, w, 20)
            l.setFont(inter(9, QFont.Weight.Bold, letter_spacing=1.0))
            l.setStyleSheet(
                f"QLabel {{ background: {bg}; color: {fg}; "
                f"border-radius: 10px; padding-left: 10px; }}"
            )
            return l

        _pill(12,  "● AUTO MODE",   PURPLE_LIGHT, rgba(PURPLE, 0.18))
        _pill(130, "● AI Active",   GREEN_LIGHT,  rgba(GREEN,  0.18), w=96)
        _pill(234, "● Sync OK",     CYAN_LIGHT,   rgba(CYAN,   0.18), w=88)
        self._status_count = _pill(330, "0 Campaigns Active",
                                   AMBER_LIGHT, rgba(AMBER, 0.18), w=160)

        version = QLabel("Spots & Commercials  ·  RadioAI Studio v2.0", sb)
        version.setGeometry(WINDOW_W - 380, 8, 280, 16)
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

    def _load_campaigns(self):
        try:
            rows = self._db.get_all_campaigns(self._filter)
            self._campaigns = [self._row_to_dict(r) for r in rows]
        except Exception as exc:
            log.error(f"get_all_campaigns failed: {exc}")
            self._campaigns = []

        # Refresh counter
        try:
            all_rows = self._db.get_all_campaigns("all")
            total = len(all_rows)
            active = sum(1 for r in all_rows if r["is_currently_active"])
        except Exception:
            total, active = len(self._campaigns), len(self._campaigns)
        if self._counter:
            self._counter.set_counts(active, total)
        if self._status_count:
            self._status_count.setText(
                f"{active} Campaign{'s' if active != 1 else ''} Active")

        self._populate_table()
        # Auto-select first row + populate detail
        if self._campaigns:
            self._select_campaign(self._campaigns[0]["id"])

    def _row_to_dict(self, r) -> dict:
        keys = r.keys()
        d = {k: r[k] for k in keys}
        return d

    def _populate_table(self):
        for w in self._row_widgets:
            w.setParent(None); w.deleteLater()
        self._row_widgets.clear()
        for i, c in enumerate(self._campaigns):
            row = _CampaignRow(c, i)
            row.clicked.connect(self._select_campaign)
            row.double_clicked.connect(self._on_edit_campaign)
            self._table_layout.insertWidget(self._table_layout.count() - 1, row)
            self._row_widgets.append(row)

    def _select_campaign(self, campaign_id: int):
        self._selected_id = int(campaign_id)
        for r in self._row_widgets:
            r.set_selected(r._campaign.get("id") == campaign_id)
        self._refresh_detail_panel()
        self.campaign_selected.emit(int(campaign_id))

    # ── Phase B3: Now Airing playback wiring ─────────────────────────────

    def _on_airing_play_clicked(self) -> None:
        """Now Airing strip ▶/■ button. Toggles per Q5 contract:
          - same campaign currently airing → stop
          - different selected campaign → stop current, start new
          - no current airing → start the selected campaign

        Manual play only — scheduled auto-play is Phase D scheduler's job.
        Preview is audition only, no broadcast_log entry (Q4)."""
        if self._engine is None:
            log.warning("[spots] no engine — Now Airing play unavailable")
            return

        target_id = self._selected_id
        if target_id is None:
            log.info("[spots] no campaign selected — Now Airing play ignored")
            return

        if self._airing_campaign_id == target_id:
            self._stop_airing()
            return

        self._stop_airing()
        self._start_airing(target_id)

    def _start_airing(self, campaign_id: int) -> None:
        spot_files = self._db.get_spot_files(campaign_id)
        # Pick first ACTIVE file with on-disk path. Round-robin selection
        # is Phase D scheduler's job.
        chosen = None
        for sf in spot_files:
            path = sf["file_path"] if "file_path" in sf.keys() else None
            if not path:
                continue
            if not os.path.exists(path):
                continue
            is_active = bool(sf["is_active"]) if "is_active" in sf.keys() else True
            if not is_active:
                continue
            chosen = sf
            break

        if chosen is None:
            log.warning(
                f"[spots] campaign {campaign_id} has no playable spot file")
            if self._now_airing:
                self._now_airing.set_campaign(
                    "No playable spot in campaign")
            return

        path = chosen["file_path"]
        try:
            cid = self._engine.load_file(path)
        except Exception as exc:
            log.warning(f"[spots] load_file failed: {exc}")
            return

        self._engine.play(cid)
        self._airing_cid = cid
        self._airing_campaign_id = campaign_id
        self._airing_spot_path = path
        self._airing_duration_ms = self._engine.get_duration_ms(cid) or 0

        # Strip UI
        if self._now_airing is not None:
            campaign = next(
                (c for c in self._campaigns if c["id"] == campaign_id), None)
            if campaign:
                self._now_airing.set_campaign(campaign.get("name") or "—")
            self._now_airing.set_playing(True)
            self._now_airing.set_progress(0.0)
            self._now_airing.set_duration_text(
                f"0:00 / {_fmt_duration_short(self._airing_duration_ms)}")

        log.info(
            f"[spots] now-airing started ch={cid} campaign={campaign_id} "
            f"path={os.path.basename(path)} dur={self._airing_duration_ms}ms")

    def _stop_airing(self) -> None:
        """End the current airing and reset strip. Idempotent."""
        if self._airing_cid is None:
            return
        cid = self._airing_cid
        try:
            self._engine.cleanup(cid)
        except Exception as exc:
            log.debug(f"[spots] airing cleanup error: {exc}")

        self._airing_cid = None
        self._airing_campaign_id = None
        self._airing_spot_path = None
        self._airing_duration_ms = 0

        if self._now_airing is not None:
            self._now_airing.set_playing(False)

        log.info(f"[spots] now-airing stopped (was ch={cid})")

    # ── Engine signal handlers (filtered to OUR channel) ─────────────────

    def _on_airing_position(self, channel_id: int, position_ms: int) -> None:
        if channel_id != self._airing_cid or self._now_airing is None:
            return
        if self._airing_duration_ms > 0:
            self._now_airing.set_progress(
                position_ms / self._airing_duration_ms)
            self._now_airing.set_duration_text(
                f"{_fmt_duration_short(position_ms)} / "
                f"{_fmt_duration_short(self._airing_duration_ms)}")

    def _on_airing_playback_ended(self, channel_id: int) -> None:
        if channel_id == self._airing_cid:
            self._stop_airing()

    def _on_airing_error(self, channel_id: int, message: str) -> None:
        if channel_id == self._airing_cid:
            log.warning(f"[spots] airing engine error: {message}")
            self._stop_airing()

    # ── Lifecycle: stop airing on hide / navigate-away ───────────────────

    def hideEvent(self, event):
        try:
            self._stop_airing()
        except Exception:
            pass
        super().hideEvent(event)

    def _refresh_detail_panel(self):
        if not self._selected_id or not self._header_card:
            return
        try:
            full = self._db.get_campaign(self._selected_id)
        except Exception as exc:
            log.error(f"get_campaign failed: {exc}")
            return
        if not full:
            return
        # Augment with file_count + active for the header card
        full["file_count"] = len(full.get("spot_files", []))
        cur = next((c for c in self._campaigns if c["id"] == self._selected_id),
                   None)
        if cur:
            full["is_currently_active"] = cur.get("is_currently_active", 1)
        self._header_card.set_campaign(full)

        # Update Now Airing strip with selected campaign name
        if self._now_airing:
            self._now_airing.set_campaign(full.get("name") or "—")

        # Form fields
        if "name" in self._fields:
            self._fields["name"].set_value(full.get("name") or "—")
            self._fields["start_date"].set_value(_fmt_full_date(full.get("start_date")))
            self._fields["end_date"].set_value(_fmt_full_date(full.get("end_date")))
            self._fields["programming_mode"].set_value(
                full.get("programming_mode") or "—")
            self._fields["playback_order"].set_value(
                full.get("playback_order") or "—")
            self._fields["category"].set_value(full.get("category") or "—")
            pri = full.get("priority") or "—"
            self._fields["priority"].set_value(
                f"{pri}" + (f"  (Priority {self._priority_rank(pri)})"
                            if pri in PRIORITY_COLORS else ""))

        # Spot files list
        if self._spot_files_layout:
            while self._spot_files_layout.count():
                item = self._spot_files_layout.takeAt(0)
                w = item.widget()
                if w:
                    w.setParent(None); w.deleteLater()
            files = full.get("spot_files") or []
            if not files:
                empty = QLabel("No spot files attached yet")
                empty.setFont(inter(9))
                empty.setStyleSheet(f"color: {TEXT_DIM}; "
                                    f"background: transparent; padding: 8px;")
                empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self._spot_files_layout.addWidget(empty)
            else:
                for sf in files:
                    self._spot_files_layout.addWidget(_SpotFileRow(sf))

        # Weekly grid
        if self._weekly_grid:
            self._weekly_grid.set_schedule(full.get("schedule") or [])

    @staticmethod
    def _priority_rank(p: str) -> int:
        return {"Low": 1, "Medium": 2, "High": 4, "Always": 5}.get(p, 3)

    # ── HANDLERS ─────────────────────────────────────────────────────────

    def _on_add_campaign(self):
        from ui.dialogs.add_campaign_dialog import AddCampaignDialog
        dlg = AddCampaignDialog(db=self._db, parent=self.window())
        dlg.campaign_saved.connect(self._on_campaign_saved)
        dlg.exec()
        # Forward signal upward for any external listeners (kept for parity)
        self.add_campaign_clicked.emit()

    def _on_campaign_saved(self, campaign_id: int):
        """Refresh the table + auto-select the newly created/updated row."""
        log.info(f"campaign_saved received: id={campaign_id}")
        self._load_campaigns()
        self._select_campaign(int(campaign_id))

    def _on_edit_campaign(self, campaign_id: Optional[int] = None):
        """Open AddCampaignDialog in edit mode for the selected campaign,
        or for `campaign_id` if passed (used by table double-click)."""
        target_id = int(campaign_id) if campaign_id else (self._selected_id or 0)
        if not target_id:
            QMessageBox.information(
                self, "No campaign",
                "Select a campaign first, then click ✎ Edit Campaign.")
            return
        from ui.dialogs.add_campaign_dialog import AddCampaignDialog
        dlg = AddCampaignDialog(
            db=self._db,
            parent=self.window(),
            edit_campaign_id=target_id,
        )
        dlg.campaign_saved.connect(self._on_campaign_saved)
        dlg.exec()

    def _on_edit_breaks(self):
        if not self._selected_id:
            QMessageBox.information(self, "No campaign",
                                    "Select a campaign first.")
            return
        from ui.dialogs.spot_programming_dialog import SpotProgrammingDialog
        cur = next((c for c in self._campaigns
                    if c["id"] == self._selected_id), None)
        name = (cur.get("name") if cur else "") or ""
        dlg = SpotProgrammingDialog(
            db=self._db,
            campaign_id=self._selected_id,
            campaign_name=name,
            parent=self.window(),
        )
        dlg.schedule_saved.connect(self._on_schedule_saved)
        dlg.exec()

    def _on_schedule_saved(self, campaign_id: int, _rows: list):
        """Refresh the detail panel so the WEEKLY BREAK SCHEDULE grid
        reflects the just-saved breaks."""
        log.info(f"schedule_saved for campaign {campaign_id}: "
                 f"{len(_rows)} rows")
        if self._selected_id == campaign_id:
            self._refresh_detail_panel()

    def _on_break_settings(self):
        log.info("Break Settings dialog — TBD")

    def _on_delete_campaign(self):
        if not self._selected_id:
            QMessageBox.information(self, "No campaign",
                                    "Select a campaign first.")
            return
        cur = next((c for c in self._campaigns
                    if c["id"] == self._selected_id), None)
        if not cur:
            return
        ans = QMessageBox.question(
            self, "Delete campaign",
            f"Delete '{cur['name']}'?\n\nAttached spot files and schedule "
            f"entries will be removed. Past airtime history is preserved.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        try:
            self._db.delete_campaign(self._selected_id)
            self._selected_id = None
            self._load_campaigns()
        except Exception as exc:
            log.error(f"delete_campaign failed: {exc}")
            QMessageBox.critical(self, "Delete failed", str(exc))

    def _on_add_file(self):
        if not self._selected_id:
            return
        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "Add spot file",
            "",
            "Audio files (*.mp3 *.wav *.ogg *.flac *.m4a);;All files (*.*)"
        )
        if not path:
            return
        import os as _os
        try:
            self._db.add_spot_file(self._selected_id, {
                "filename":  _os.path.basename(path),
                "file_path": path,
                "duration_ms": 0,
                "is_active": 1,
            })
            self._refresh_detail_panel()
            # Refresh file_count in the row + header card
            self._load_campaigns()
            self._select_campaign(self._selected_id)
        except Exception as exc:
            log.error(f"add_spot_file failed: {exc}")
            QMessageBox.critical(self, "Add file failed", str(exc))

    def _on_status_filter_changed(self, idx: int):
        self._filter = ["active", "expired", "all"][idx]
        self._load_campaigns()

    def _tick(self):
        if self._clock_lbl:
            self._clock_lbl.setText(datetime.now().strftime("%H:%M:%S"))
