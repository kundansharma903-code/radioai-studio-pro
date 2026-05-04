"""
RadioAI Studio Pro — Songs Library
Pixel-accurate match of Figma node 212:2 (file 7oN9K61g94wKx3nu44KKDF).

Layout (1440×900 — extended from Figma's 1440×768 to fill the existing stack):
  Header           y=0..50           (compact: logo + breadcrumb + title + clock + Open Studio mini)
  Sidebar          y=50..868, x=0..160      (count + actions + search + filters + reports)
  Table header     y=50..82, x=160..860     (32px)
  Table body       y=82..868, x=160..860    (scrollable list of SongRow)
  Detail panel     y=50..868, x=860..1440   (tabs + song header + 8 form fields + waveform + AI insight)
  Status bar       y=868..900, 1440×32

Reuses premium widgets where possible: PictorialIcon, WaveformWidget,
PremiumBadge, LiveClock. Inline private widgets for sidebar buttons, detail
form fields, and table rows since those patterns are screen-specific.
"""

import logging
from datetime import datetime
from typing import Optional

from PyQt6.QtCore import (
    Qt, QRectF, QTimer, QPropertyAnimation, pyqtProperty, pyqtSignal, QSize,
)
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QLinearGradient, QPainterPath, QFont,
    QCursor, QFontMetrics,
)
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QLineEdit, QComboBox,
    QScrollArea, QVBoxLayout, QGraphicsDropShadowEffect, QMessageBox,
)

from ui.widgets._tokens import (
    inter, mono, rgba,
    BG_BASE, BG_PANEL, BG_CARD, BG_ELEVATED,
    TEXT_PRI, TEXT_SEC, TEXT_MUTED, TEXT_DIM,
    CYAN, CYAN_LIGHT, PURPLE, PURPLE_LIGHT, GREEN, GREEN_LIGHT,
    AMBER, AMBER_LIGHT, RED, RED_LIGHT, PINK, PINK_LIGHT,
)
from ui.widgets.pictorial_icon import PictorialIcon, IconType
from ui.widgets.waveform_widget import WaveformWidget

log = logging.getLogger("SongsLibrary")


# Common geometry tokens
WINDOW_W = 1440
WINDOW_H = 900
HEADER_H = 50
STATUS_H = 32
SIDEBAR_W = 160
TABLE_W = 700
DETAIL_W = 580
ROW_H = 28

# Dark panel bg (sidebar, tabs row)
BG_DARK_PANEL = "#0a0c16"


# Category color map (used by table category pills)
CATEGORY_COLORS = {
    "Hot Currents":  AMBER,
    "Air Currents":  CYAN,
    "Pop":           GREEN,
    "Classics":      PURPLE_LIGHT,
    "Rock":          RED,
    "Electronic":    PINK,
    "Jazz":          AMBER,
    "Devotional":    PURPLE,
    "Bhajan":        PURPLE,
    "Romantic":      PINK,
    "Dance":         CYAN,
    "Power Gold":    AMBER,
    "Recurrents":    PURPLE,
    "Currents":      CYAN,
    "Specialty":     CYAN,
    "Morning Vibes": PURPLE,
    "Gold":          AMBER,
    "News Break":    TEXT_MUTED,
}


def _category_color(name: str) -> str:
    return CATEGORY_COLORS.get(name, PURPLE_LIGHT)


def _human_ago(played_at: Optional[str]) -> str:
    """Convert an ISO datetime to '2h ago' / '3d ago' style string."""
    if not played_at:
        return "—"
    try:
        dt = datetime.strptime(str(played_at)[:19], "%Y-%m-%d %H:%M:%S")
        delta = datetime.now() - dt
        s = int(delta.total_seconds())
        if s < 60:           return f"{s}s ago"
        if s < 3600:         return f"{s // 60}m ago"
        if s < 86400:        return f"{s // 3600}h ago"
        return f"{s // 86400}d ago"
    except Exception:
        return "—"


def _fmt_duration(ms: int) -> str:
    s = int((ms or 0) // 1000)
    return f"{s // 60}:{s % 60:02d}"


# ════════════════════════════════════════════════════════════════════════════
# Inline private widgets — sidebar
# ════════════════════════════════════════════════════════════════════════════

class _SongCountBox(QFrame):
    """Sidebar count box: '395 / songs' with 3px cyan left accent."""

    def __init__(self, count: int, parent=None):
        super().__init__(parent)
        self._count = count
        self.setFixedSize(134, 36)

    def set_count(self, n: int):
        self._count = n
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0, 0, 134, 36)
        path = QPainterPath()
        path.addRoundedRect(rect, 6, 6)
        p.setClipPath(path)
        p.fillRect(rect, QColor(BG_ELEVATED))
        # 3px cyan left accent
        p.fillRect(0, 0, 3, 36, QColor(CYAN))
        # Count
        p.setClipping(False)
        p.setPen(QColor(TEXT_PRI))
        p.setFont(inter(16, QFont.Weight.Bold))
        p.drawText(14, 4, 100, 18,
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   f"{self._count:,}")
        # "songs" label
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(inter(9))
        p.drawText(14, 22, 100, 12,
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "songs")


class _SidebarActionButton(QPushButton):
    """Sidebar action button — 134×28 with left accent + icon + label."""

    def __init__(self, text: str, color: str, bg_tint: str, parent=None):
        super().__init__(text, parent)
        self._color = QColor(color)
        self._bg_tint = QColor(bg_tint)
        self._hover = False
        self.setFixedSize(134, 28)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFlat(True)
        self.setStyleSheet("background: transparent; border: none;")
        self.setFont(inter(10, QFont.Weight.Bold))

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0, 0, 134, 28)
        path = QPainterPath()
        path.addRoundedRect(rect, 5, 5)
        p.setClipPath(path)
        # Background tint
        bg = QColor(self._bg_tint)
        if self._hover:
            # boost alpha slightly on hover
            c = QColor(self._color); c.setAlphaF(0.12)
            p.fillRect(rect, bg)
            p.fillRect(rect, c)
        else:
            p.fillRect(rect, bg)
        # 2px left accent
        p.fillRect(0, 0, 2, 28, self._color)
        # Border (subtle)
        p.setClipping(False)
        bc = QColor(self._color); bc.setAlphaF(0.30)
        p.setPen(QPen(bc, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(0.5, 0.5, 133, 27), 5, 5)
        # Label
        p.setPen(self._color)
        p.setFont(self.font())
        p.drawText(10, 0, 124, 28,
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self.text())

    def enterEvent(self, e):
        self._hover = True; self.update(); super().enterEvent(e)
    def leaveEvent(self, e):
        self._hover = False; self.update(); super().leaveEvent(e)


class _SidebarReportButton(QPushButton):
    """Reports button — 134×24, smaller variant of action button."""

    def __init__(self, text: str, color: str, parent=None):
        super().__init__(text, parent)
        self._color = QColor(color)
        self._hover = False
        self.setFixedSize(134, 24)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFlat(True)
        self.setStyleSheet("background: transparent; border: none;")
        self.setFont(inter(9, QFont.Weight.Bold))

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0, 0, 134, 24)
        path = QPainterPath()
        path.addRoundedRect(rect, 4, 4)
        p.setClipPath(path)
        c = QColor(self._color); c.setAlphaF(0.10 if not self._hover else 0.18)
        p.fillRect(rect, c)
        # 2px left accent
        p.fillRect(0, 0, 2, 24, self._color)
        p.setClipping(False)
        p.setPen(self._color)
        p.setFont(self.font())
        p.drawText(8, 0, 124, 24,
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self.text())

    def enterEvent(self, e): self._hover = True; self.update(); super().enterEvent(e)
    def leaveEvent(self, e): self._hover = False; self.update(); super().leaveEvent(e)


class _SidebarSearchInput(QLineEdit):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(134, 28)
        self.setPlaceholderText("Search...")
        self.setFont(inter(10))
        self.setStyleSheet(
            f"QLineEdit {{ background: {BG_ELEVATED}; color: {TEXT_PRI}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; border-radius: 5px; "
            f"padding-left: 9px; padding-right: 22px; selection-background-color: {rgba(CYAN, 0.25)}; }}"
            f"QLineEdit:focus {{ border: 1px solid {CYAN}; }}"
        )


class _SidebarDropdown(QComboBox):

    def __init__(self, items: list, parent=None):
        super().__init__(parent)
        self.setFixedSize(134, 26)
        self.addItems(items)
        self.setFont(inter(10))
        self.setStyleSheet(
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


# ════════════════════════════════════════════════════════════════════════════
# Inline private widgets — header
# ════════════════════════════════════════════════════════════════════════════

class _HeaderLogo(QWidget):
    """Compact 36×36 logo box with 5 white waveform bars."""

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
        # 5 white bars (heights 4,9,15,9,4)
        p.setBrush(QColor(255, 255, 255, 235))
        p.setPen(Qt.PenStyle.NoPen)
        for x, h in [(6, 4), (12, 9), (18, 15), (24, 9), (30, 4)]:
            top = (36 - h) // 2
            p.drawRoundedRect(QRectF(x - 1.5, top, 3, h), 1.5, 1.5)


class _HeaderOpenStudio(QPushButton):
    """Mini Open Studio button (200×34) — green border + ▶ + 2-line label."""

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
        # Subtle green-tinted bg
        g = QLinearGradient(0, 0, 200, 34)
        c1 = QColor(GREEN); c1.setAlphaF(0.10)
        c2 = QColor(GREEN); c2.setAlphaF(0.04)
        g.setColorAt(0.0, c1); g.setColorAt(1.0, c2)
        p.fillRect(QRectF(0, 0, 200, 34), QBrush(g))
        p.setClipping(False)
        # Border
        bc = QColor(GREEN); bc.setAlphaF(0.30)
        p.setPen(QPen(bc, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 8, 8)
        # ▶ play icon
        p.setPen(QColor(GREEN))
        p.setFont(inter(11, QFont.Weight.Bold))
        p.drawText(12, 0, 16, 34, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "▶")
        # "Open Studio" label
        p.setFont(inter(11, QFont.Weight.Bold))
        p.drawText(28, 4, 170, 14, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "Open Studio")
        # Subtitle
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(inter(8))
        p.drawText(28, 18, 170, 12, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   "Billie Eilish — Bury A Friend")


class _ActiveBreadcrumbChip(QFrame):
    """● Songs chip — cyan with pulsing dot."""

    def __init__(self, text: str = "Songs", parent=None):
        super().__init__(parent)
        self._text = text
        self._dot_alpha = 1.0
        self.setFixedSize(92, 28)
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
        rect = QRectF(0.5, 0.5, 91, 27)
        path = QPainterPath()
        path.addRoundedRect(rect, 14, 14)
        p.setClipPath(path)
        # Cyan-tinted bg
        c1 = QColor(CYAN); c1.setAlphaF(0.18)
        c2 = QColor(CYAN); c2.setAlphaF(0.06)
        g = QLinearGradient(0, 0, 0, 28)
        g.setColorAt(0.0, c1); g.setColorAt(1.0, c2)
        p.fillRect(QRectF(0, 0, 92, 28), QBrush(g))
        p.setClipping(False)
        bc = QColor(CYAN); bc.setAlphaF(0.30)
        p.setPen(QPen(bc, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 14, 14)
        # Pulsing dot at left
        dot = QColor(CYAN); dot.setAlphaF(self._dot_alpha)
        p.setBrush(dot); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(10, 10, 8, 8)
        # Label
        p.setPen(QColor(CYAN))
        p.setFont(inter(11, QFont.Weight.Bold))
        p.drawText(24, 0, 60, 28,
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._text)


# ════════════════════════════════════════════════════════════════════════════
# Inline private widgets — table
# ════════════════════════════════════════════════════════════════════════════

class _CategoryPill(QLabel):
    """Inline category pill — used in table cells."""

    def __init__(self, text: str, color: str, parent=None):
        super().__init__(text.upper(), parent)
        self._color = QColor(color)
        self.setFixedHeight(18)
        self.setFont(inter(9, QFont.Weight.Bold, letter_spacing=0.3))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # auto-size based on text
        fm = QFontMetrics(self.font())
        self.setFixedWidth(min(86, fm.horizontalAdvance(text.upper()) + 16))

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        c1 = QColor(self._color); c1.setAlphaF(0.18)
        c2 = QColor(self._color); c2.setAlphaF(0.06)
        g = QLinearGradient(0, 0, 0, self.height())
        g.setColorAt(0.0, c1); g.setColorAt(1.0, c2)
        p.setBrush(QBrush(g))
        bc = QColor(self._color); bc.setAlphaF(0.30)
        p.setPen(QPen(bc, 1))
        p.drawRoundedRect(rect, 9, 9)
        p.setPen(self._color)
        p.setFont(self.font())
        # text matches Figma — title case not uppercase
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text().title())


class _PlayButton(QPushButton):
    """Small purple play button in table rows — 26×18."""

    def __init__(self, parent=None):
        super().__init__("", parent)
        self.setFixedSize(26, 18)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFlat(True)
        self.setStyleSheet("background: transparent; border: none;")

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0.5, 0.5, 25, 17)
        path = QPainterPath()
        path.addRoundedRect(rect, 4, 4)
        p.setClipPath(path)
        c = QColor(PURPLE); c.setAlphaF(0.18)
        p.fillRect(QRectF(0, 0, 26, 18), c)
        p.setClipping(False)
        bc = QColor(PURPLE); bc.setAlphaF(0.30)
        p.setPen(QPen(bc, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 4, 4)
        p.setPen(QColor(PURPLE_LIGHT))
        p.setFont(inter(9, QFont.Weight.Bold))
        p.drawText(QRectF(0, 0, 26, 18), Qt.AlignmentFlag.AlignCenter, "▶")


class _SongRow(QFrame):
    """One table row (700×28)."""

    clicked      = pyqtSignal(int)   # song_id
    play_clicked = pyqtSignal(int)   # song_id

    def __init__(self, song: dict, row_index: int, parent=None):
        super().__init__(parent)
        self._song = song
        self._row_index = row_index
        self._selected = False
        self._hover = False
        self.setFixedSize(700, 28)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        # Status dot (12×12 area, 8×8 dot centered at x=18)
        # painted in paintEvent

        # Title
        self._title_lbl = QLabel(song.get("title", ""), self)
        self._title_lbl.setGeometry(36, 0, 180, 28)
        self._title_lbl.setStyleSheet("background: transparent;")
        self._update_title_style()

        # Artist
        artist = QLabel(song.get("artist", ""), self)
        artist.setGeometry(220, 0, 130, 28)
        artist.setFont(inter(11))
        artist.setStyleSheet(f"color: {TEXT_SEC}; background: transparent;")

        # Category pill
        cat = song.get("category", "") or ""
        if cat:
            pill = _CategoryPill(cat, _category_color(cat), self)
            pill.move(354, 5)

        # Duration
        dur = QLabel(_fmt_duration(song.get("duration_ms", 0)), self)
        dur.setGeometry(450, 0, 60, 28)
        dur.setFont(inter(10))
        dur.setStyleSheet(f"color: {TEXT_SEC}; background: transparent;")

        # BPM
        bpm = QLabel(str(song.get("bpm", "—") or "—"), self)
        bpm.setGeometry(514, 0, 40, 28)
        bpm.setFont(inter(10, QFont.Weight.Bold))
        bpm.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")

        # Last played
        lp = QLabel(_human_ago(song.get("last_played")), self)
        lp.setGeometry(560, 0, 90, 28)
        lp.setFont(inter(10))
        lp.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

        # Play button
        pb = _PlayButton(self)
        pb.move(660, 5)
        pb.clicked.connect(lambda: self.play_clicked.emit(self._song.get("id", 0)))

    def _update_title_style(self):
        if self._selected:
            self._title_lbl.setFont(inter(11, QFont.Weight.Bold))
            self._title_lbl.setStyleSheet(f"color: {CYAN}; background: transparent;")
        else:
            self._title_lbl.setFont(inter(11, QFont.Weight.Medium))
            self._title_lbl.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")

    def set_selected(self, selected: bool):
        self._selected = selected
        self._update_title_style()
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0, 0, 700, 28)

        # Background
        if self._selected:
            bg = QColor(CYAN); bg.setAlphaF(0.10)
            p.fillRect(rect, bg)
            # 2px left accent
            p.fillRect(0, 0, 2, 28, QColor(CYAN))
        elif self._row_index % 2 == 1:
            c = QColor("#0d0f1e"); c.setAlphaF(0.4)
            p.fillRect(rect, c)
        if self._hover and not self._selected:
            c = QColor(255, 255, 255, 6)
            p.fillRect(rect, c)

        # Status dot (green) at (18, 14)
        p.setBrush(QColor(GREEN))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(14, 10, 8, 8)

        # Bottom hairline
        p.setPen(QPen(QColor(255, 255, 255, 8), 1))
        p.drawLine(0, 27, 700, 27)

    def enterEvent(self, e): self._hover = True; self.update(); super().enterEvent(e)
    def leaveEvent(self, e): self._hover = False; self.update(); super().leaveEvent(e)
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._song.get("id", 0))
        super().mousePressEvent(e)


# ════════════════════════════════════════════════════════════════════════════
# Inline private widgets — detail panel
# ════════════════════════════════════════════════════════════════════════════

class _DetailFormField(QFrame):
    """Label + input box (548×40 stacked: 14 label + 22 input + 4 gap)."""

    def __init__(self, label: str, value: str, parent=None):
        super().__init__(parent)
        self.setFixedSize(548, 36)

        self._label = QLabel(label.upper(), self)
        self._label.setGeometry(0, 0, 548, 12)
        self._label.setFont(inter(8, QFont.Weight.Bold, letter_spacing=1.2))
        self._label.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

        self._input = QLineEdit(value, self)
        self._input.setGeometry(0, 14, 548, 22)
        self._input.setFont(inter(10, QFont.Weight.Medium))
        self._input.setReadOnly(True)
        self._input.setStyleSheet(
            f"QLineEdit {{ background: {BG_BASE}; color: {TEXT_PRI}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; border-radius: 4px; "
            f"padding: 0 9px; }}"
            f"QLineEdit:focus {{ border-color: {CYAN}; }}"
        )

    def set_value(self, v: str):
        self._input.setText(v)


class _SongHeaderCard(QFrame):
    """Top of detail panel — song icon + name + meta + 2 status badges."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(552, 64)
        self._title = "—"
        self._meta = ""
        self._enabled = True
        self._category = ""

    def set_song(self, title: str, meta: str, enabled: bool, category: str):
        self._title = title
        self._meta = meta
        self._enabled = enabled
        self._category = category
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0, 0, 552, 64)
        path = QPainterPath()
        path.addRoundedRect(rect, 6, 6)
        p.setClipPath(path)
        # Bg
        p.fillRect(rect, QColor(BG_ELEVATED))
        # 3px cyan left accent
        p.fillRect(0, 0, 3, 64, QColor(CYAN))
        p.setClipping(False)
        # Border
        p.setPen(QPen(QColor(255, 255, 255, 16), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(0.5, 0.5, 551, 63), 6, 6)
        # Music note ellipse 36×36 at (14, 14)
        p.setBrush(QColor(8, 51, 68))  # cyan-dark
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(14, 14, 36, 36)
        p.setBrush(Qt.BrushStyle.NoBrush)
        bc = QColor(CYAN); bc.setAlphaF(0.6)
        p.setPen(QPen(bc, 1.5))
        p.drawEllipse(14, 14, 36, 36)
        # ♪ note glyph
        p.setPen(QColor(CYAN_LIGHT))
        p.setFont(inter(20, QFont.Weight.Bold))
        p.drawText(14, 14, 36, 36, Qt.AlignmentFlag.AlignCenter, "♪")
        # Title
        p.setPen(QColor(TEXT_PRI))
        p.setFont(inter(14, QFont.Weight.Bold))
        p.drawText(60, 8, 460, 22,
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._title)
        # Meta
        p.setPen(QColor(TEXT_SEC))
        p.setFont(inter(9))
        p.drawText(60, 26, 460, 14,
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._meta)
        # Status badges
        # Enabled
        en_color = QColor(GREEN) if self._enabled else QColor(RED)
        en_bg = QColor(en_color); en_bg.setAlphaF(0.12)
        en_text = "Enabled" if self._enabled else "Disabled"
        # Badge 60×14 at (60, 42)
        p.setBrush(en_bg)
        p.setPen(QPen(QColor(en_color.red(), en_color.green(), en_color.blue(), 80), 1))
        p.drawRoundedRect(QRectF(60, 42, 60, 14), 7, 7)
        p.setPen(en_color)
        p.setFont(inter(9, QFont.Weight.Bold))
        p.drawText(QRectF(60, 42, 60, 14), Qt.AlignmentFlag.AlignCenter, en_text)
        # Category
        if self._category:
            cat_color = QColor(_category_color(self._category))
            cat_bg = QColor(cat_color); cat_bg.setAlphaF(0.14)
            p.setBrush(cat_bg)
            p.setPen(QPen(QColor(cat_color.red(), cat_color.green(), cat_color.blue(), 80), 1))
            p.drawRoundedRect(QRectF(124, 42, 84, 14), 7, 7)
            p.setPen(cat_color)
            p.setFont(inter(9, QFont.Weight.Bold))
            p.drawText(QRectF(124, 42, 84, 14), Qt.AlignmentFlag.AlignCenter, self._category)


class _AIInsightBox(QFrame):
    """Purple AI insight box at the bottom of the detail panel."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(552, 36)
        self._line1 = "✦ AI: Plays every 18 min avg — healthy rotation"
        self._line2 = "Last 7 days: played 47 times"

    def set_insight(self, line1: str, line2: str):
        self._line1 = line1; self._line2 = line2; self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0, 0, 552, 36)
        path = QPainterPath()
        path.addRoundedRect(rect, 6, 6)
        p.setClipPath(path)
        p.fillRect(rect, QColor("#1e1535"))
        # 2px purple left accent
        p.fillRect(0, 0, 2, 36, QColor(PURPLE))
        p.setClipping(False)
        bc = QColor(PURPLE); bc.setAlphaF(0.30)
        p.setPen(QPen(bc, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(0.5, 0.5, 551, 35), 6, 6)
        # Line 1 — purple bold
        p.setPen(QColor(PURPLE_LIGHT))
        p.setFont(inter(9, QFont.Weight.Bold))
        p.drawText(12, 4, 540, 14,
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._line1)
        # Line 2 — muted regular
        p.setPen(QColor(TEXT_SEC))
        p.setFont(inter(9))
        p.drawText(12, 18, 540, 14,
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._line2)


# ════════════════════════════════════════════════════════════════════════════
# SongsLibrary — full screen
# ════════════════════════════════════════════════════════════════════════════

class SongsLibrary(QWidget):

    song_selected           = pyqtSignal(int)
    add_song_clicked        = pyqtSignal()
    mass_import_clicked     = pyqtSignal()
    edit_categories_clicked = pyqtSignal()
    delete_song_clicked     = pyqtSignal(int)
    breadcrumb_clicked      = pyqtSignal(str)
    studio_clicked          = pyqtSignal()
    report_clicked          = pyqtSignal(str)
    play_song_clicked       = pyqtSignal(int)

    def __init__(self, db, parent=None, engine=None):
        super().__init__(parent)
        self._db = db
        self._engine = engine     # shared AudioEngine (Phase B Option C)
        self.setFixedSize(WINDOW_W, WINDOW_H)
        self.setStyleSheet(
            f"background: qlineargradient("
            f"x1:0,y1:0,x2:1,y2:1, stop:0 #0a0d1a, stop:0.5 #06080f, stop:1 #020308);"
        )

        # State
        self._all_songs: list = []      # cache of fetched rows
        self._row_widgets: list = []    # _SongRow widgets for each song
        self._selected_id: Optional[int] = None
        self._table_body: Optional[QWidget] = None
        self._table_layout: Optional[QVBoxLayout] = None
        self._search_input: Optional[_SidebarSearchInput] = None
        self._dropdowns: dict = {}

        # Header clock
        self._clock_lbl: Optional[QLabel] = None

        # Detail refs
        self._song_header: Optional[_SongHeaderCard] = None
        self._fields: dict = {}
        self._waveform: Optional[WaveformWidget] = None
        self._wave_left_lbl: Optional[QLabel] = None
        self._wave_right_lbl: Optional[QLabel] = None
        self._ai_box: Optional[_AIInsightBox] = None
        self._count_box: Optional[_SongCountBox] = None

        self._build_header()
        self._build_sidebar()
        self._build_table_header()
        self._build_table_body()
        self._build_detail_panel()
        self._build_status_bar()

        # Initial data load
        self._load_songs()

        # Live clock
        self._tick()
        t = QTimer(self)
        t.setInterval(1000); t.timeout.connect(self._tick); t.start()

        log.info("SongsLibrary ready (Figma 212:2)")

    # ── HEADER (y=0..50) ──────────────────────────────────────────────────

    def _build_header(self):
        bg = QFrame(self)
        bg.setGeometry(0, 0, WINDOW_W, HEADER_H)
        bg.setStyleSheet(
            f"background: qlineargradient(x1:0,y1:0,x2:0,y2:1, "
            f"stop:0 rgba(16,19,31,0.95), stop:1 rgba(10,12,22,0.95)); "
            f"border-bottom: 1px solid {rgba('#ffffff', 0.06)};"
        )
        # Hairline
        hl = QFrame(self)
        hl.setGeometry(0, 49, WINDOW_W, 1)
        hl.setStyleSheet(
            f"background: qlineargradient(x1:0,y1:0,x2:1,y2:0, "
            f"stop:0 rgba(255,255,255,0), stop:0.5 rgba(255,255,255,0.10), "
            f"stop:1 rgba(255,255,255,0));"
        )

        # Logo at (14, 8)
        _HeaderLogo(self).move(14, 8)

        # Brand text
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

        sep = QLabel("|", self)
        sep.setGeometry(234, 14, 8, 22)
        sep.setFont(inter(11))
        sep.setStyleSheet(f"color: {TEXT_DIM}; background: transparent;")

        l = QLabel("Libraries", self)
        l.setGeometry(244, 14, 60, 22)
        l.setFont(inter(11, QFont.Weight.Medium))
        l.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

        sep2 = QLabel("|", self)
        sep2.setGeometry(300, 14, 8, 22)
        sep2.setFont(inter(11))
        sep2.setStyleSheet(f"color: {TEXT_DIM}; background: transparent;")

        chip = _ActiveBreadcrumbChip("Songs", self)
        chip.move(312, 11)

        # Title + subtitle
        l = QLabel("Songs Library", self)
        l.setGeometry(416, 4, 280, 22)
        l.setFont(inter(18, QFont.Weight.Bold))
        l.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        l = QLabel("Music collection — manage categories, cue points, AI rotation", self)
        l.setGeometry(416, 26, 460, 16)
        l.setFont(inter(10))
        l.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

        # Clock + station
        self._clock_lbl = QLabel("21:56:15", self)
        self._clock_lbl.setGeometry(990, 8, 90, 22)
        self._clock_lbl.setFont(mono(18, bold=True))
        self._clock_lbl.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        l = QLabel("KISS FM 91.5", self)
        l.setGeometry(990, 28, 100, 14)
        l.setFont(inter(9, QFont.Weight.Medium))
        l.setStyleSheet(f"color: {GREEN}; background: transparent;")

        # Open Studio mini
        osb = _HeaderOpenStudio(self)
        osb.move(1218, 8)
        osb.clicked.connect(self.studio_clicked.emit)

    # ── SIDEBAR (y=50..868, x=0..160) ─────────────────────────────────────

    def _build_sidebar(self):
        sb = QFrame(self)
        sb.setGeometry(0, HEADER_H, SIDEBAR_W, WINDOW_H - HEADER_H - STATUS_H)
        sb.setStyleSheet(
            f"background: {BG_DARK_PANEL}; border-right: 1px solid {rgba('#ffffff', 0.06)};"
        )

        # Songs count box at (12, 16) inside sidebar
        self._count_box = _SongCountBox(0, self)
        self._count_box.move(12, HEADER_H + 16)

        # Action buttons at y=64,96,128,160 (relative to sidebar) → abs y=114,146,178,210
        actions = [
            ("+ Add New Song",   GREEN,        "#052e16", self._open_add_song_dialog),
            ("⤓ Mass Import",   CYAN,         "#083344", self._open_mass_import_dialog),
            ("✎ Edit Categories", PURPLE_LIGHT, "#1e1535", self._open_edit_categories_dialog),
            ("✕ Delete",         RED,          "#1f0a12", self._on_delete_clicked),
        ]
        for i, (txt, color, bg_tint, slot) in enumerate(actions):
            btn = _SidebarActionButton(txt, color, bg_tint, self)
            btn.move(12, HEADER_H + 64 + i * 32)
            btn.clicked.connect(slot)

        # SEARCH label
        l = QLabel("SEARCH", self)
        l.setGeometry(12, HEADER_H + 208, 80, 14)
        l.setFont(inter(8, QFont.Weight.Bold, letter_spacing=1.2))
        l.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

        self._search_input = _SidebarSearchInput(self)
        self._search_input.move(12, HEADER_H + 224)
        self._search_input.textChanged.connect(self._on_search_changed)

        # FILTERS label
        l = QLabel("FILTERS", self)
        l.setGeometry(12, HEADER_H + 268, 80, 14)
        l.setFont(inter(8, QFont.Weight.Bold, letter_spacing=1.2))
        l.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

        # Filter dropdowns
        filter_specs = [
            ("category", ["Category (All)"]),
            ("energy",   ["Energy (All)", "Low", "Medium", "High"]),
            ("vocal",    ["Vocal (All)", "Male", "Female", "Instrumental"]),
            ("bpm",      ["BPM Range (All)", "60-90", "90-120", "120-150", "150+"]),
            ("enabled",  ["Only Enabled", "All", "Disabled"]),
        ]
        for i, (key, items) in enumerate(filter_specs):
            cb = _SidebarDropdown(items, self)
            cb.move(12, HEADER_H + 284 + i * 32)
            cb.currentIndexChanged.connect(lambda _i, k=key: self._on_filter_changed(k))
            self._dropdowns[key] = cb

        # Populate Category dropdown from real DB
        try:
            cats = self._db.get_categories()
            cat_combo = self._dropdowns["category"]
            cat_combo.clear()
            cat_combo.addItem("Category (All)")
            for c in cats:
                cat_combo.addItem(c["name"])
        except Exception as exc:
            log.error(f"category load failed: {exc}")

        # REPORTS label
        l = QLabel("REPORTS", self)
        l.setGeometry(12, HEADER_H + 460, 80, 14)
        l.setFont(inter(8, QFont.Weight.Bold, letter_spacing=1.2))
        l.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

        reports = [
            ("📊 Play History",    AMBER,  "play_history"),
            ("🎯 Rotation Health", GREEN,  "rotation_health"),
            ("⏱ Last Played",     CYAN,   "last_played"),
            ("📈 Top Songs",       PURPLE_LIGHT, "top_songs"),
        ]
        for i, (txt, color, key) in enumerate(reports):
            btn = _SidebarReportButton(txt, color, self)
            btn.move(12, HEADER_H + 476 + i * 28)
            btn.clicked.connect(lambda _checked=False, k=key: self.report_clicked.emit(k))

    # ── TABLE HEADER (y=50..82, x=160..860) ───────────────────────────────

    def _build_table_header(self):
        hdr = QFrame(self)
        hdr.setGeometry(SIDEBAR_W, HEADER_H, TABLE_W, 32)
        hdr.setStyleSheet(
            f"background: {BG_CARD}; "
            f"border-bottom: 1px solid {rgba('#ffffff', 0.06)};"
        )
        # Column headers at fixed x positions (relative to sidebar+0=160 abs)
        cols = [
            ("Song Title",  36),
            ("Artist",      220),
            ("Category",    354),
            ("Duration",    450),
            ("BPM",         514),
            ("Last Played", 560),
        ]
        for label, x in cols:
            l = QLabel(label, self)
            l.setGeometry(SIDEBAR_W + x, HEADER_H, 100, 32)
            l.setFont(inter(9, QFont.Weight.Bold, letter_spacing=0.8))
            l.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

    # ── TABLE BODY (y=82..868, x=160..860) ────────────────────────────────

    def _build_table_body(self):
        body_y = HEADER_H + 32
        body_h = WINDOW_H - body_y - STATUS_H

        scroll = QScrollArea(self)
        scroll.setGeometry(SIDEBAR_W, body_y, TABLE_W, body_h)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setStyleSheet(
            f"QScrollArea {{ background: transparent; border: none; }}"
            f"QScrollBar:vertical {{ background: transparent; width: 4px; margin: 0; }}"
            f"QScrollBar::handle:vertical {{ background: {rgba('#252840', 0.8)}; border-radius: 2px; }}"
            f"QScrollBar::handle:vertical:hover {{ background: {TEXT_SEC}; }}"
            f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}"
        )

        body = QWidget()
        body.setStyleSheet("background: transparent;")
        v = QVBoxLayout(body)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addStretch()
        scroll.setWidget(body)

        self._table_body = body
        self._table_layout = v

    # ── DETAIL PANEL (y=50..868, x=860..1440) ─────────────────────────────

    def _build_detail_panel(self):
        x0 = SIDEBAR_W + TABLE_W   # 860
        y0 = HEADER_H              # 50
        h  = WINDOW_H - y0 - STATUS_H

        bg = QFrame(self)
        bg.setGeometry(x0, y0, DETAIL_W, h)
        bg.setStyleSheet(
            f"background: {BG_CARD}; "
            f"border-left: 1px solid {rgba('#ffffff', 0.06)};"
        )

        # Tabs row (36px tall)
        tabs_bg = QFrame(self)
        tabs_bg.setGeometry(x0, y0, DETAIL_W, 36)
        tabs_bg.setStyleSheet(
            f"background: {BG_DARK_PANEL}; "
            f"border-bottom: 1px solid {rgba('#ffffff', 0.06)};"
        )
        for i, (txt, active) in enumerate([
            ("Song Details", True), ("Audio Cues", False), ("Play History", False),
        ]):
            btn = QPushButton(txt, self)
            btn.setGeometry(x0 + 14 + i * 105, y0, 100, 36)
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            color = CYAN if active else TEXT_MUTED
            weight = QFont.Weight.Bold if active else QFont.Weight.Medium
            btn.setFont(inter(11, weight))
            btn.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {color}; "
                f"border: none; padding: 0; text-align: left; }}"
                f"QPushButton:hover {{ color: {TEXT_PRI}; }}"
            )
        # Active tab underline
        ul = QFrame(self)
        ul.setGeometry(x0 + 14, y0 + 34, 90, 2)
        ul.setStyleSheet(f"background: {CYAN};")

        # Song header card at y=86 absolute (inside detail at 36..100)
        self._song_header = _SongHeaderCard(self)
        self._song_header.move(x0 + 14, y0 + 50)

        # 8 form fields starting at y=120 absolute (inside detail y=70)
        fields = [
            ("title", "Title"),
            ("artist", "Artist"),
            ("album", "Album"),
            ("year", "Year"),
            ("category", "Category"),
            ("energy", "Energy"),
            ("vocal", "Vocal"),
            ("bpm", "BPM"),
        ]
        for i, (key, label) in enumerate(fields):
            f = _DetailFormField(label, "", self)
            f.move(x0 + 16, y0 + 120 + i * 36)
            self._fields[key] = f

        # AUDIO PREVIEW header bar at y=460 inside detail = abs y=510
        ap_bg = QFrame(self)
        ap_bg.setGeometry(x0 + 14, y0 + 410, 552, 24)
        ap_bg.setStyleSheet(
            f"background: {rgba(AMBER, 0.08)}; "
            f"border-radius: 4px; border-left: 2px solid {AMBER};"
        )
        l = QLabel("AUDIO PREVIEW", self)
        l.setGeometry(x0 + 24, y0 + 410, 200, 24)
        l.setFont(inter(9, QFont.Weight.Bold, letter_spacing=1.2))
        l.setStyleSheet(f"color: {AMBER}; background: transparent;")

        # Waveform widget (full-width-28, height 30)
        self._waveform = WaveformWidget(
            n_bars=70, played_color=AMBER, light_color=AMBER_LIGHT, max_height=24,
            parent=self,
        )
        self._waveform.setGeometry(x0 + 14, y0 + 440, 552, 30)

        # Time labels
        self._wave_left_lbl = QLabel("0:42", self)
        self._wave_left_lbl.setGeometry(x0 + 14, y0 + 472, 60, 12)
        self._wave_left_lbl.setFont(inter(9, QFont.Weight.Bold))
        self._wave_left_lbl.setStyleSheet(f"color: {AMBER}; background: transparent;")

        self._wave_right_lbl = QLabel("2:18", self)
        self._wave_right_lbl.setGeometry(x0 + 514, y0 + 472, 52, 12)
        self._wave_right_lbl.setFont(inter(9, QFont.Weight.Bold))
        self._wave_right_lbl.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent;"
        )
        self._wave_right_lbl.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # AI insight box at y=506 inside detail = abs y=556
        self._ai_box = _AIInsightBox(self)
        self._ai_box.move(x0 + 14, y0 + 506)

        # ✎ Edit Cues button — Phase 5-A temporary placement.
        # Final placement (Phase 5-C) will integrate with the Audio Cues tab
        # once the tab system is wired. For now, button sits below the AI
        # insight box where it's discoverable but doesn't crowd existing UI.
        edit_cues = QPushButton("✎  Edit Cues", self)
        edit_cues.setGeometry(x0 + 14, y0 + 470, 130, 28)
        edit_cues.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        edit_cues.setFont(inter(10, QFont.Weight.DemiBold))
        edit_cues.setStyleSheet(
            f"QPushButton {{ background: {rgba(CYAN, 0.16)}; "
            f"color: {CYAN_LIGHT}; "
            f"border: 1px solid {rgba(CYAN, 0.40)}; "
            f"border-radius: 5px; padding: 0 12px; }}"
            f"QPushButton:hover {{ background: {rgba(CYAN, 0.26)}; }}"
            f"QPushButton:disabled {{ background: #181a30; "
            f"color: {TEXT_DIM}; border: 1px solid {rgba('#ffffff', 0.04)}; }}"
        )
        edit_cues.clicked.connect(self._open_cue_editor)
        self._edit_cues_btn = edit_cues

    def _open_cue_editor(self):
        if not self._selected_id:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(
                self, "No song selected",
                "Click a song in the table first, then ✎ Edit Cues.")
            return
        from ui.dialogs.audio_cue_editor_dialog import AudioCueEditorDialog
        dlg = AudioCueEditorDialog(
            db=self._db, song_id=self._selected_id,
            parent=self.window(), engine=self._engine)
        dlg.cues_saved.connect(self._on_cues_saved)
        dlg.exec()

    def _on_cues_saved(self, song_id: int):
        log.info(f"cues_saved received for song id={song_id}")
        # Refresh the detail panel — cue values may affect what the
        # waveform/labels show. For 5-A this is a no-op since the
        # detail panel doesn't yet display per-cue numbers.

    # ── STATUS BAR (y=868..900) ───────────────────────────────────────────

    def _build_status_bar(self):
        y0 = WINDOW_H - STATUS_H
        bg = QFrame(self)
        bg.setGeometry(0, y0, WINDOW_W, STATUS_H)
        bg.setStyleSheet(
            f"background: {BG_CARD}; "
            f"border-top: 1px solid {rgba('#ffffff', 0.06)};"
        )

        # Status pills left
        pills = [
            ("⬤ AUTO MODE", PURPLE),
            ("⬤ AI Active", GREEN),
            ("395 Songs",   CYAN),
        ]
        x = 12
        for txt, color in pills:
            fm = QFontMetrics(inter(9, QFont.Weight.Bold))
            tw = fm.horizontalAdvance(txt) + 16
            lbl = QLabel(txt, self)
            lbl.setGeometry(x, y0 + 6, tw, 20)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setFont(inter(9, QFont.Weight.Bold))
            lbl.setStyleSheet(
                f"background: {rgba(color, 0.15)}; color: {color}; "
                f"border-radius: 10px; border: 1px solid {rgba(color, 0.30)};"
            )
            x += tw + 8

        # Right: brand line
        brand = QLabel("Songs Library  •  RadioAI Studio v2.0", self)
        brand.setGeometry(WINDOW_W - 360, y0 + 6, 220, 20)
        brand.setFont(inter(9))
        brand.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        brand.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # Mini Open Studio button
        b = QPushButton("▶ Open Studio", self)
        b.setGeometry(WINDOW_W - 110, y0 + 4, 100, 24)
        b.setFont(inter(10, QFont.Weight.Bold))
        b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        b.setStyleSheet(
            f"QPushButton {{ background: {rgba(GREEN, 0.18)}; color: {GREEN}; "
            f"border: 1px solid {rgba(GREEN, 0.40)}; border-radius: 5px; }}"
            f"QPushButton:hover {{ background: {rgba(GREEN, 0.30)}; }}"
        )
        b.clicked.connect(self.studio_clicked.emit)

    # ── Data load / refresh ──────────────────────────────────────────────

    def _load_songs(self):
        try:
            rows = self._db.get_songs(limit=400)  # show all
            self._all_songs = [self._row_to_dict(r) for r in rows]
            # Count comes from dashboard stats so the sidebar always shows
            # the real total (in case the result set is filtered/limited later)
            try:
                stats = self._db.get_dashboard_stats()
                self._total_count = stats.get("songs_total", len(self._all_songs))
            except Exception:
                self._total_count = len(self._all_songs)
        except Exception as exc:
            log.error(f"get_songs failed: {exc}")
            self._all_songs = []
            self._total_count = 0
        self._populate_table()
        if self._all_songs:
            self._select_song(self._all_songs[0]["id"])

    def _row_to_dict(self, r) -> dict:
        return {
            "id":           r["id"],
            "title":        r["title"] or "",
            "artist":       r["artist"] or "",
            "category":     r["cat_name"] or "",
            "duration_ms":  r["duration_ms"] or 0,
            "bpm":          r["bpm"] or 0,
            "year":         r["year"] or "",
            "energy":       r["energy"] or "",
            "vocal":        r["vocal"] or "",
            "album":        r["album"] if "album" in r.keys() else "",
            "is_enabled":   r["is_enabled"] if "is_enabled" in r.keys() else 1,
            "last_played":  None,  # filled later if available
        }

    def _populate_table(self):
        # Clear existing rows
        for w in self._row_widgets:
            w.setParent(None)
            w.deleteLater()
        self._row_widgets.clear()

        # Refresh count — show TRUE total from stats (not the limited fetch)
        total = getattr(self, "_total_count", len(self._all_songs))
        if self._count_box:
            self._count_box.set_count(total)

        # Add rows
        # Insert at index 0 so the addStretch() at the end remains last
        for i, song in enumerate(self._all_songs):
            row = _SongRow(song, i)
            row.clicked.connect(self._select_song)
            row.play_clicked.connect(self.play_song_clicked.emit)
            self._table_layout.insertWidget(self._table_layout.count() - 1, row)
            self._row_widgets.append(row)

    def _select_song(self, song_id: int):
        self._selected_id = song_id
        # Update row selection state
        for row in self._row_widgets:
            row.set_selected(row._song.get("id") == song_id)
        # Update detail panel
        song = next((s for s in self._all_songs if s["id"] == song_id), None)
        if song:
            self._update_detail_panel(song)
        self.song_selected.emit(song_id)

    def _update_detail_panel(self, song: dict):
        if self._song_header:
            meta = f"{song.get('artist', '')}  •  {_fmt_duration(song.get('duration_ms', 0))}"
            if song.get("bpm"):
                meta += f"  •  {song['bpm']} BPM"
            self._song_header.set_song(
                title=song.get("title", "—"),
                meta=meta,
                enabled=bool(song.get("is_enabled", 1)),
                category=song.get("category", ""),
            )
        for key, lbl in [
            ("title",    song.get("title", "")),
            ("artist",   song.get("artist", "")),
            ("album",    song.get("album", "")),
            ("year",     str(song.get("year", "") or "")),
            ("category", song.get("category", "")),
            ("energy",   song.get("energy", "")),
            ("vocal",    song.get("vocal", "")),
            ("bpm",      str(song.get("bpm", "") or "")),
        ]:
            if key in self._fields:
                self._fields[key].set_value(lbl)
        if self._wave_right_lbl:
            self._wave_right_lbl.setText(_fmt_duration(song.get("duration_ms", 0)))

    def _on_search_changed(self, text: str):
        # Simple in-memory filter (no DB hit). For DB-driven, add a debounced QTimer.
        text = text.lower().strip()
        for row in self._row_widgets:
            s = row._song
            match = (text in (s.get("title", "") + " " + s.get("artist", "")).lower())
            row.setVisible(not text or match)

    def _open_add_song_dialog(self):
        """Open the Add New Song modal dialog. On save, reload table."""
        from ui.dialogs.add_new_song_dialog import AddNewSongDialog
        dlg = AddNewSongDialog(parent=self.window(), db=self._db)
        dlg.song_saved.connect(self._on_song_added)
        dlg.exec()

    def _open_mass_import_dialog(self):
        """Open the Mass Import modal dialog. On import done, reload table."""
        from ui.dialogs.mass_import_dialog import MassImportDialog
        dlg = MassImportDialog(parent=self.window(), db=self._db)
        dlg.songs_imported.connect(lambda _count: self._load_songs())
        dlg.exec()

    def _open_edit_categories_dialog(self):
        """Open the Edit Categories modal. On change, refresh filter dropdown + table."""
        from ui.dialogs.edit_categories_dialog import EditCategoriesDialog
        dlg = EditCategoriesDialog(parent=self.window(), db=self._db)
        dlg.categories_changed.connect(self._on_categories_changed)
        dlg.exec()

    def _on_delete_clicked(self):
        """Sidebar ✕ Delete handler — opens the Confirm Delete dialog for the
        currently-selected song. Emits delete_song_clicked upward as well so
        external listeners can react if they want to."""
        sid = self._selected_id or 0
        if not sid:
            QMessageBox.information(
                self,
                "No song selected",
                "Click a song in the list first, then press ✕ Delete.",
            )
            return

        # Pull the row from cache; fall back to DB if the cache is stale.
        cached = next((s for s in self._all_songs if s["id"] == sid), None)
        song_data = dict(cached) if cached else {}
        if not song_data:
            try:
                row = self._db.get_song(sid)
                if row:
                    song_data = {
                        "id":          row["id"],
                        "title":       row["title"],
                        "artist":      row["artist"],
                        "duration_ms": row["duration_ms"],
                        "category":    row["cat_name"] if "cat_name" in row.keys() else "",
                    }
            except Exception as exc:
                log.error(f"get_song failed for delete dialog: {exc}")

        if not song_data:
            QMessageBox.warning(
                self, "Song not found",
                "Could not load the selected song. Please refresh and try again.",
            )
            return

        # Augment with airtime stats so the dialog can show "Last played" + plays.
        try:
            stats = self._db.get_song_play_stats(sid)
            song_data["play_count"] = stats.get("play_count", 0)
            song_data["last_played_human"] = _human_ago(stats.get("last_played"))
        except Exception as exc:
            log.error(f"get_song_play_stats failed: {exc}")

        # Forward upward (preserve existing public signal contract)
        self.delete_song_clicked.emit(sid)

        from ui.dialogs.confirm_delete_dialog import ConfirmDeleteDialog
        dlg = ConfirmDeleteDialog(song_data=song_data, parent=self.window())
        dlg.delete_confirmed.connect(self._delete_song_confirmed)
        dlg.exec()

    def _delete_song_confirmed(self, song_id: int):
        try:
            self._db.delete_song(int(song_id))
        except Exception as exc:
            log.error(f"delete_song({song_id}) failed: {exc}", exc_info=True)
            QMessageBox.critical(
                self, "Delete failed",
                f"Could not delete song:\n\n{exc}",
            )
            return
        self._selected_id = None
        self._load_songs()

    def _on_categories_changed(self):
        """Reload the category dropdown options + re-fetch songs (cat names may have changed)."""
        try:
            cats = self._db.get_categories()
            cat_combo = self._dropdowns.get("category")
            if cat_combo is not None:
                cur_text = cat_combo.currentText()
                cat_combo.blockSignals(True)
                cat_combo.clear()
                cat_combo.addItem("Category (All)")
                for c in cats:
                    cat_combo.addItem(c["name"])
                # Try to restore previous selection
                idx = cat_combo.findText(cur_text)
                cat_combo.setCurrentIndex(idx if idx >= 0 else 0)
                cat_combo.blockSignals(False)
        except Exception as exc:
            log.error(f"category dropdown refresh failed: {exc}")
        self._load_songs()

    def _on_song_added(self, song: dict):
        log.info(f"Song added via dialog: {song.get('artist')} — {song.get('title')}")
        # Reload songs from DB and refresh the table
        self._load_songs()
        # Try to select the newly added song if it has an id
        if song.get("id"):
            self._select_song(song["id"])

    def _on_filter_changed(self, key: str):
        cb = self._dropdowns.get(key)
        if not cb:
            return
        sel = cb.currentText()
        for row in self._row_widgets:
            s = row._song
            visible = True
            if key == "category" and not sel.endswith("(All)") and sel != "":
                visible = (s.get("category", "") == sel)
            elif key == "energy" and not sel.endswith("(All)"):
                visible = (s.get("energy", "") == sel)
            elif key == "vocal" and not sel.endswith("(All)"):
                visible = (s.get("vocal", "") == sel)
            row.setVisible(visible)

    def _tick(self):
        if self._clock_lbl:
            self._clock_lbl.setText(datetime.now().strftime("%H:%M:%S"))


