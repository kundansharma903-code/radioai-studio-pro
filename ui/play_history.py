"""
RadioAI Studio Pro — Play History
Pixel-accurate match of Figma node 437:3 (file 7oN9K61g94wKx3nu44KKDF,
page "Play History").

Per-song analytics screen. Reached from Songs Library by selecting a
song row + clicking the "Play History" report action — MainWindow
captures the song_id + routes here.

Reads broadcast_log via three DB helpers:
  • get_song_play_history_summary(song_id) → totals + counters
  • get_song_monthly_plays(song_id, 12)   → 12-month bar data
  • get_song_recent_plays(song_id, 5)     → last 5 plays table

Layout (1440 × 900):
  Header        y=  0.. 72   Logo + breadcrumb + title + clock + Open Studio
  Hero card     y= 88..236   Album art + title/artist + category pill +
                              inline stats + TOTAL PLAYS right column
  Stats row     y=256..344   4 cards (this month / week / avg / last)
  Monthly chart y=360..616   12 bars + gridlines + peak callout
  Recent plays  y=632..852   Last 5 broadcast_log rows table
  Status bar    y=864..900   Pills + version

Public signals:
  breadcrumb_clicked(str) — header crumbs
  studio_clicked()        — Open Studio
"""

from __future__ import annotations

import logging
from datetime import datetime, date as ddate
from typing import Optional, List

from PyQt6.QtCore import Qt, QRectF, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QLinearGradient, QFont, QCursor,
)
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QHBoxLayout, QVBoxLayout,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
)

from core.settings import Settings
from ui.widgets._tokens import (
    inter, mono, rgba,
    BG_BASE, BG_DARK, BG_PANEL, BG_CARD, BG_CARD_DK,
    TEXT_PRI, TEXT_SEC, TEXT_MUTED, TEXT_DIM,
    CYAN, CYAN_LIGHT, PURPLE, PURPLE_LIGHT,
    GREEN, GREEN_LIGHT, AMBER, AMBER_LIGHT, RED, RED_LIGHT,
    PINK, PINK_LIGHT, TEAL,
)

log = logging.getLogger("PlayHistory")


WINDOW_W = 1440
WINDOW_H = 900
HEADER_H = 72
STATUS_H = 36

MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _category_color(name: str) -> str:
    """Lightweight category → tint mapping. Matches the Songs Library
    palette so a Bollywood song shows the same cyan in both places.
    Falls back to CYAN."""
    if not name:
        return CYAN
    nm = name.lower()
    if "bolly" in nm or "hindi" in nm:
        return CYAN
    if "pop" in nm or "english" in nm or "international" in nm:
        return PURPLE
    if "rock" in nm or "alt" in nm:
        return RED
    if "rom" in nm or "love" in nm:
        return PINK
    if "classic" in nm or "retro" in nm or "vintage" in nm:
        return AMBER
    if "punjab" in nm or "regional" in nm:
        return GREEN
    return CYAN


def _human_ago(played_at: str) -> str:
    """Return a 'just now / 2h ago / Today / Yesterday / DD MMM YYYY'
    label for a played_at ISO timestamp (matches Songs Library)."""
    if not played_at:
        return "Never played"
    try:
        dt = datetime.fromisoformat(played_at.replace("Z", "").strip())
    except Exception:
        try:
            dt = datetime.strptime(played_at[:19], "%Y-%m-%d %H:%M:%S")
        except Exception:
            return "—"
    now = datetime.now()
    delta = now - dt
    secs = int(delta.total_seconds())
    if secs < 60:
        return "Just now"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    if delta.days == 1:
        return "Yesterday"
    if delta.days < 7:
        return f"{delta.days}d ago"
    return dt.strftime("%d %b %Y")


def _format_added_at(ts: str) -> str:
    if not ts:
        return "Unknown"
    try:
        return datetime.strptime(ts[:10], "%Y-%m-%d").strftime("%d %b %Y")
    except Exception:
        return ts[:10]


def _format_played_date(ts: str) -> str:
    """Date part of a played_at ISO. 'Today', 'Yesterday' for the two
    most recent days, full date otherwise."""
    if not ts:
        return "—"
    try:
        d = datetime.strptime(ts[:10], "%Y-%m-%d").date()
    except Exception:
        return ts[:10]
    today = ddate.today()
    if d == today:
        return "Today"
    if (today - d).days == 1:
        return "Yesterday"
    return d.strftime("%d %b %Y")


def _format_played_time(ts: str) -> str:
    if not ts or len(ts) < 19:
        return "—"
    return ts[11:19]


# ════════════════════════════════════════════════════════════════════════════
# Header chrome
# ════════════════════════════════════════════════════════════════════════════


class _HeaderLogo(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(40, 40)

    def paintEvent(self, _e):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        g = QLinearGradient(0, 0, self.width(), self.height())
        g.setColorAt(0.0, QColor(CYAN))
        g.setColorAt(1.0, QColor(PURPLE))
        p.setBrush(QBrush(g)); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(2, 2, self.width() - 4, self.height() - 4)
        p.setPen(QPen(QColor(255, 255, 255, 230), 2))
        cx, cy = self.width() / 2, self.height() / 2
        for i, h in enumerate([6, 10, 14, 10, 6]):
            x = cx - 8 + i * 4
            p.drawLine(int(x), int(cy - h / 2), int(x), int(cy + h / 2))
        p.end()


class _HeaderOpenStudio(QPushButton):
    def __init__(self, parent=None):
        super().__init__("▶  Open Studio", parent)
        self.setFixedSize(110, 40)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFont(inter(11, QFont.Weight.Bold))
        self.setStyleSheet(
            f"QPushButton {{ background: qlineargradient("
            f"x1:0,y1:0,x2:0,y2:1, stop:0 {GREEN_LIGHT}, stop:1 {GREEN}); "
            f"color: white; border: none; border-radius: 8px; }}"
            f"QPushButton:hover {{ background: qlineargradient("
            f"x1:0,y1:0,x2:0,y2:1, stop:0 #34d399, stop:1 {GREEN}); }}"
        )


class _BreadcrumbLink(QPushButton):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFont(inter(11, QFont.Weight.Medium))
        self.setFlat(True)
        self.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {TEXT_MUTED}; "
            f"border: none; padding: 0 4px; text-align: left; }}"
            f"QPushButton:hover {{ color: {TEXT_PRI}; }}"
        )


class _BreadcrumbPill(QFrame):
    def __init__(self, label: str, accent: str = PURPLE, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"QFrame {{ background: {rgba(accent, 0.18)}; "
            f"border: 1px solid {rgba(accent, 0.40)}; border-radius: 16px; }}"
        )
        h = QHBoxLayout(self)
        h.setContentsMargins(14, 0, 14, 0); h.setSpacing(0)
        lbl = QLabel(label, self)
        lbl.setFont(inter(11, QFont.Weight.Bold))
        lbl.setStyleSheet(
            f"color: {PURPLE_LIGHT}; background: transparent; "
            f"border: none;")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h.addWidget(lbl)
        # Size from the label — the old fixed 124px clipped longer
        # crumbs ("Cat. Performance" lost its first letters; audit
        # 2026-07-03).
        self.setFixedSize(max(124, lbl.sizeHint().width() + 28), 32)


# ════════════════════════════════════════════════════════════════════════════
# Hero song card — album art + title/artist + category pill + TOTAL PLAYS
# ════════════════════════════════════════════════════════════════════════════


class _AlbumArt(QFrame):
    """108×108 purple→cyan gradient tile with a centered ♪ glyph.
    A placeholder until the songs.cover_art column is wired."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(108, 108)

    def paintEvent(self, _e):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        g = QLinearGradient(0, 0, self.width(), self.height())
        g.setColorAt(0.0, QColor(PURPLE))
        g.setColorAt(1.0, QColor(CYAN))
        p.setBrush(QBrush(g)); p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), 10, 10)
        # Music note glyph
        p.setPen(QColor(255, 255, 255, 235))
        p.setFont(inter(56, QFont.Weight.Bold))
        p.drawText(QRectF(0, 0, self.width(), self.height()),
                   Qt.AlignmentFlag.AlignCenter, "♪")


class _CategoryPill(QFrame):
    def __init__(self, label: str, accent: str = CYAN, parent=None):
        super().__init__(parent)
        self._accent = accent
        self.setFixedHeight(26)
        self.setMinimumWidth(100)
        self.setStyleSheet(
            f"QFrame {{ background: {rgba(accent, 0.18)}; "
            f"border: 1px solid {rgba(accent, 0.40)}; "
            f"border-radius: 13px; }}"
        )
        h = QHBoxLayout(self)
        h.setContentsMargins(12, 0, 12, 0); h.setSpacing(0)
        lbl = QLabel((label or "—").upper(), self)
        lbl.setFont(inter(9, QFont.Weight.Bold, letter_spacing=1.2))
        lbl.setStyleSheet(
            f"color: {accent}; background: transparent; border: none;")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h.addWidget(lbl)
        self.adjustSize()


class _HeroCard(QFrame):
    """Top song-info card — left accent stripe, album art, title block,
    inline stats, plus the right-aligned TOTAL PLAYS panel."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(1408, 148)
        self.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; "
            f"border-radius: 12px; }}"
        )
        # Children
        self._art = _AlbumArt(self)
        self._art.move(24, 20)

        self._title_lbl = QLabel("—", self)
        self._title_lbl.setGeometry(152, 18, 720, 36)
        self._title_lbl.setFont(inter(28, QFont.Weight.Black))
        self._title_lbl.setStyleSheet(
            f"color: {TEXT_PRI}; background: transparent; border: none;")

        self._meta_lbl = QLabel("", self)
        self._meta_lbl.setGeometry(152, 56, 720, 18)
        self._meta_lbl.setFont(inter(12, QFont.Weight.Medium))
        self._meta_lbl.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent; border: none;")

        # Category pill placeholder — replaced on load
        self._cat_pill: Optional[_CategoryPill] = None

        self._inline_stats = QLabel("", self)
        self._inline_stats.setGeometry(264, 90, 500, 26)
        self._inline_stats.setFont(inter(11, QFont.Weight.Medium))
        self._inline_stats.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; border: none;")

        # Right column — TOTAL PLAYS (paint background + content)
        self._right_lbl_caption = QLabel("TOTAL PLAYS", self)
        self._right_lbl_caption.setFont(
            inter(9, QFont.Weight.Bold, letter_spacing=1.6))
        self._right_lbl_caption.setStyleSheet(
            f"color: {PURPLE_LIGHT}; background: transparent; "
            f"border: none;")
        self._right_lbl_caption.setGeometry(1408 - 320, 22, 320, 14)
        self._right_lbl_caption.setAlignment(
            Qt.AlignmentFlag.AlignCenter)

        self._right_total = QLabel("0", self)
        self._right_total.setFont(mono(48, bold=True))
        self._right_total.setStyleSheet(
            f"color: {TEXT_PRI}; background: transparent; border: none;")
        self._right_total.setGeometry(1408 - 320, 42, 320, 60)
        self._right_total.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._right_added = QLabel("", self)
        self._right_added.setFont(inter(10))
        self._right_added.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; border: none;")
        self._right_added.setGeometry(1408 - 320, 108, 320, 14)
        self._right_added.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Left accent stripe
        p.fillRect(QRectF(0, 0, 4, self.height()), QColor(PURPLE))
        # Right column background tint
        p.fillRect(QRectF(self.width() - 320, 0, 320, self.height()),
                   QColor(rgba("#0c0e1c", 0.55)))
        p.end()

    def load_song(self, song: dict, summary: dict) -> None:
        title = song.get("title") or "—"
        artist = song.get("artist") or "—"
        album = song.get("album") or ""
        year = song.get("year") or ""
        cat = song.get("category") or song.get("cat_name") or ""
        dur_ms = int(song.get("duration_ms") or 0)
        bpm = song.get("bpm")
        energy = song.get("energy") or ""

        self._title_lbl.setText(title)
        # Build "Artist · Album · Year" with reasonable fallbacks
        parts = [artist]
        if album:
            parts.append(album)
        if year:
            parts.append(str(year))
        self._meta_lbl.setText("  ·  ".join(p for p in parts if p))

        # Replace category pill
        if self._cat_pill is not None:
            self._cat_pill.deleteLater()
            self._cat_pill = None
        if cat:
            self._cat_pill = _CategoryPill(
                cat, _category_color(cat), self)
            self._cat_pill.move(152, 90)

        # Inline stats: duration · BPM · energy
        bits = []
        if dur_ms > 0:
            total_s = dur_ms // 1000
            bits.append(f"{total_s // 60}:{total_s % 60:02d} duration")
        if bpm:
            bits.append(f"{bpm} BPM")
        if energy:
            bits.append(f"{energy} energy")
        self._inline_stats.setText("   ·   ".join(bits))

        total = int(summary.get("total_plays") or 0)
        self._right_total.setText(f"{total:,}")
        added = summary.get("added_at") or ""
        self._right_added.setText(f"Since {_format_added_at(added)}")


# ════════════════════════════════════════════════════════════════════════════
# Stats row — 4 mini cards
# ════════════════════════════════════════════════════════════════════════════


class _StatCard(QFrame):
    """One of the four mini stat cards — colored top accent, label,
    big value (mono), small subtitle."""

    def __init__(self, label: str, accent: str, accent_light: str,
                 parent=None):
        super().__init__(parent)
        self._accent = accent
        self.setFixedSize(340, 88)
        self.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; "
            f"border-radius: 10px; }}"
        )

        self._label_lbl = QLabel(label.upper(), self)
        self._label_lbl.setFont(
            inter(9, QFont.Weight.Bold, letter_spacing=1.4))
        self._label_lbl.setStyleSheet(
            f"color: {accent_light}; background: transparent; "
            f"border: none;")
        self._label_lbl.setGeometry(18, 12, self.width() - 36, 14)

        self._val_lbl = QLabel("0", self)
        self._val_lbl.setFont(mono(28, bold=True))
        self._val_lbl.setStyleSheet(
            f"color: {TEXT_PRI}; background: transparent; border: none;")
        self._val_lbl.setGeometry(18, 30, 260, 36)

        self._sub_lbl = QLabel("", self)
        self._sub_lbl.setFont(inter(10, QFont.Weight.Medium))
        self._sub_lbl.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; "
            f"border: none;")
        self._sub_lbl.setGeometry(18, 66, self.width() - 36, 14)

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(QRectF(0, 0, self.width(), 3), QColor(self._accent))
        p.end()

    def set_value(self, value: str, subtitle: str = "") -> None:
        self._val_lbl.setText(value)
        self._sub_lbl.setText(subtitle)


# ════════════════════════════════════════════════════════════════════════════
# Monthly bar chart
# ════════════════════════════════════════════════════════════════════════════


class _MonthlyChart(QFrame):
    """Custom-paint 12-bar chart. Bars are scaled to the chart's
    visible peak; current month rendered cyan, peak month purple-
    light, others a dimmer purple. Gridlines + Y-axis labels + month
    labels handled in paintEvent for crisp alignment."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(1408, 256)
        self.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; "
            f"border-radius: 12px; }}"
        )
        self._data: list = []   # list of dicts year/month/label/count
        self._max = 1

    def set_data(self, monthly: list) -> None:
        self._data = list(monthly or [])
        self._max = max(1, max((d.get("count") or 0) for d in self._data)
                          if self._data else 1)
        self.update()

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Heading
        p.setPen(QColor(PURPLE_LIGHT))
        p.setFont(inter(10, QFont.Weight.Bold, letter_spacing=1.4))
        p.drawText(QRectF(24, 14, 700, 20),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "MONTHLY PLAY DISTRIBUTION — LAST 12 MONTHS")
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(inter(10))
        p.drawText(QRectF(24, 34, 700, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "Bars show count per month. Current month in cyan; "
                   "peak in purple.")

        if not self._data:
            p.setPen(QColor(TEXT_MUTED))
            p.setFont(inter(11))
            p.drawText(QRectF(0, 100, self.width(), 40),
                       Qt.AlignmentFlag.AlignCenter,
                       "No plays logged yet for this song.")
            p.end()
            return

        # Peak callout (right)
        peak = self._max
        p.setPen(QColor(TEXT_SEC))
        p.setFont(inter(10, QFont.Weight.Medium))
        p.drawText(QRectF(self.width() - 24 - 200, 14, 200, 20),
                   Qt.AlignmentFlag.AlignRight
                   | Qt.AlignmentFlag.AlignVCenter,
                   f"Peak: {peak} plays")

        # Chart area
        bar_area_x = 60
        bar_area_y = 68
        bar_area_w = self.width() - 80
        bar_area_h = 140
        n = len(self._data)
        bar_w = 72 if n == 12 else max(24, int((bar_area_w * 0.8) / n))
        if n > 1:
            bar_spacing = (bar_area_w - n * bar_w) / (n - 1)
        else:
            bar_spacing = 0

        # Gridlines (5 horizontal lines incl top + bottom)
        p.setPen(QPen(QColor(rgba("#ffffff", 0.04)), 1))
        for i in range(5):
            gy = bar_area_y + (bar_area_h / 4) * i
            p.drawLine(int(bar_area_x), int(gy),
                       int(bar_area_x + bar_area_w), int(gy))
            # Y-axis value
            val = round(peak * (4 - i) / 4)
            p.setPen(QColor(TEXT_MUTED))
            p.setFont(inter(9, QFont.Weight.Medium))
            p.drawText(QRectF(16, gy - 8, 40, 16),
                       Qt.AlignmentFlag.AlignRight
                       | Qt.AlignmentFlag.AlignVCenter,
                       str(val))
            p.setPen(QPen(QColor(rgba("#ffffff", 0.04)), 1))

        # Bars
        today = ddate.today()
        for i, d in enumerate(self._data):
            count = int(d.get("count") or 0)
            label = d.get("label") or ""
            y_year = int(d.get("year") or 0)
            y_month = int(d.get("month") or 0)
            is_current = (y_year == today.year and y_month == today.month)
            is_peak = (count == peak and count > 0)

            ratio = (count / peak) if peak > 0 else 0.0
            bar_h = ratio * bar_area_h
            bx = bar_area_x + i * (bar_w + bar_spacing)
            by = bar_area_y + bar_area_h - bar_h

            # Gradient fill — current cyan, peak purple-light,
            # else dim purple
            grad = QLinearGradient(bx, by, bx, by + bar_h)
            if is_current:
                grad.setColorAt(0.0, QColor(CYAN_LIGHT))
                grad.setColorAt(1.0, QColor(CYAN))
            elif is_peak:
                grad.setColorAt(0.0, QColor(PURPLE_LIGHT))
                grad.setColorAt(1.0, QColor(PURPLE))
            else:
                c0 = QColor(PURPLE); c0.setAlphaF(0.45)
                c1 = QColor(PURPLE); c1.setAlphaF(0.20)
                grad.setColorAt(0.0, c0)
                grad.setColorAt(1.0, c1)
            p.setBrush(QBrush(grad))
            p.setPen(Qt.PenStyle.NoPen)
            if bar_h > 0:
                p.drawRoundedRect(QRectF(bx, by, bar_w, bar_h), 4, 4)

            # Count above bar (only when there's room)
            if count > 0:
                p.setPen(QColor(
                    CYAN_LIGHT if is_current else
                    (PURPLE_LIGHT if is_peak else TEXT_SEC)))
                p.setFont(inter(10, QFont.Weight.Bold))
                p.drawText(QRectF(bx, by - 18, bar_w, 14),
                           Qt.AlignmentFlag.AlignCenter,
                           str(count))
            # Month label
            p.setPen(QColor(
                CYAN_LIGHT if is_current else TEXT_MUTED))
            p.setFont(inter(10, QFont.Weight.Medium))
            p.drawText(QRectF(bx, bar_area_y + bar_area_h + 6,
                              bar_w, 14),
                       Qt.AlignmentFlag.AlignCenter, label)
        p.end()


# ════════════════════════════════════════════════════════════════════════════
# Recent plays table
# ════════════════════════════════════════════════════════════════════════════


class _RecentPlaysTable(QFrame):
    """Heading + 7-col table of broadcast_log rows."""

    COLUMNS = ["#", "DATE", "TIME", "CLOCK", "SLOT", "OPERATOR", "DECK"]
    COL_WIDTHS = [50, 130, 110, 360, 80, 540, 80]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(1408, 220)
        self.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; "
            f"border-radius: 12px; }}"
        )

        self._title_lbl = QLabel("RECENT PLAYS — LAST 5", self)
        self._title_lbl.setFont(
            inter(10, QFont.Weight.Bold, letter_spacing=1.4))
        self._title_lbl.setStyleSheet(
            f"color: {PURPLE_LIGHT}; background: transparent; "
            f"border: none;")
        self._title_lbl.setGeometry(24, 14, 400, 16)
        self._subtitle_lbl = QLabel(
            "Broadcast log entries for this song", self)
        self._subtitle_lbl.setFont(inter(10))
        self._subtitle_lbl.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; "
            f"border: none;")
        self._subtitle_lbl.setGeometry(24, 34, 600, 14)

        self._table = QTableWidget(0, len(self.COLUMNS), self)
        self._table.setGeometry(16, 56, 1376, 156)
        self._table.setHorizontalHeaderLabels(self.COLUMNS)
        self._table.setShowGrid(False)
        self._table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Fixed)
        for i, w in enumerate(self.COL_WIDTHS):
            self._table.setColumnWidth(i, w)
        # Stretch OPERATOR (col 5) to soak up remaining space
        self._table.horizontalHeader().setSectionResizeMode(
            5, QHeaderView.ResizeMode.Stretch)
        self._table.verticalHeader().setDefaultSectionSize(24)
        self._table.setStyleSheet(
            f"QTableWidget {{ background: transparent; "
            f"color: {TEXT_PRI}; gridline-color: transparent; "
            f"border: none; }}"
            f"QHeaderView::section {{ background: transparent; "
            f"color: {TEXT_MUTED}; border: none; "
            f"border-bottom: 1px solid {rgba('#ffffff', 0.06)}; "
            f"padding: 4px 6px; font-weight: bold; "
            f"font-size: 9px; letter-spacing: 1.2px; "
            f"text-align: left; }}"
            f"QTableWidget::item {{ padding: 3px 6px; border: none; }}"
        )

    def load_rows(self, rows: list) -> None:
        self._table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            played_at = r.get("played_at") or ""
            date_s = _format_played_date(played_at)
            time_s = _format_played_time(played_at)
            clock = r.get("clock_name") or "—"
            slot = r.get("slot_idx")
            slot_s = str(slot) if slot is not None else "—"
            operator = r.get("operator") or "—"
            deck = r.get("deck") or "—"

            num_item = QTableWidgetItem(str(i + 1))
            num_item.setForeground(QColor(TEXT_MUTED))
            num_item.setFont(mono(10, bold=False))
            self._table.setItem(i, 0, num_item)

            d_item = QTableWidgetItem(date_s)
            d_item.setForeground(QColor(TEXT_PRI))
            d_item.setFont(mono(11, bold=False))
            self._table.setItem(i, 1, d_item)

            t_item = QTableWidgetItem(time_s)
            t_item.setForeground(QColor(TEXT_PRI))
            t_item.setFont(mono(11, bold=True))
            self._table.setItem(i, 2, t_item)

            self._table.setItem(i, 3, self._txt(clock, TEXT_PRI,
                                                  inter(11, QFont.Weight.Medium)))
            self._table.setItem(i, 4, self._txt(slot_s, TEXT_SEC,
                                                  mono(10)))
            self._table.setItem(i, 5, self._txt(operator, TEXT_SEC,
                                                  inter(11)))
            self._table.setItem(i, 6, self._txt(deck, TEXT_SEC,
                                                  mono(10, bold=True)))

    @staticmethod
    def _txt(text: str, fg: str, font: QFont) -> QTableWidgetItem:
        it = QTableWidgetItem(text)
        it.setForeground(QColor(fg))
        it.setFont(font)
        return it


# ════════════════════════════════════════════════════════════════════════════
# Status bar
# ════════════════════════════════════════════════════════════════════════════


class _StatusPill(QFrame):
    def __init__(self, label: str, color: str, parent=None):
        super().__init__(parent)
        self.setFixedHeight(22)
        self.setStyleSheet(
            f"QFrame {{ background: {rgba(color, 0.18)}; "
            f"border: 1px solid {rgba(color, 0.40)}; border-radius: 11px; }}"
        )
        h = QHBoxLayout(self)
        h.setContentsMargins(10, 0, 12, 0); h.setSpacing(6)
        dot = QLabel("●", self)
        dot.setFont(inter(8))
        dot.setStyleSheet(
            f"color: {color}; background: transparent; border: none;")
        lbl = QLabel(label, self)
        lbl.setFont(inter(9, QFont.Weight.Bold))
        lbl.setStyleSheet(
            f"color: {color}; background: transparent; border: none;")
        h.addWidget(dot)
        h.addWidget(lbl)
        self.adjustSize()


# ════════════════════════════════════════════════════════════════════════════
# Public screen
# ════════════════════════════════════════════════════════════════════════════


class PlayHistory(QWidget):
    """Per-song play history screen (Figma 437:3)."""

    breadcrumb_clicked = pyqtSignal(str)
    studio_clicked     = pyqtSignal()

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self._db = db
        self._song_id: Optional[int] = None
        self._song: dict = {}
        self.setFixedSize(WINDOW_W, WINDOW_H)
        self.setStyleSheet(f"QWidget {{ background: {BG_BASE}; }}")

        self._build_header()
        self._build_body()
        self._build_status_bar()

        # Live clock
        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._tick_clock)
        self._clock_timer.start()
        self._tick_clock()

        log.info("PlayHistory ready (Figma 437:3)")

    # ── Header ────────────────────────────────────────────────────────

    def _build_header(self) -> None:
        h = QFrame(self)
        h.setGeometry(0, 0, WINDOW_W, HEADER_H)
        h.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border-bottom: 1px solid {rgba('#ffffff', 0.06)}; }} "
            f"QLabel {{ border: none; }}"
        )

        _HeaderLogo(h).move(14, 16)
        l = QLabel("RadioAI", h)
        l.setGeometry(64, 14, 120, 18)
        l.setFont(inter(15, QFont.Weight.Bold))
        l.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        sub = QLabel("STUDIO PRO", h)
        sub.setGeometry(64, 34, 120, 12)
        sub.setFont(inter(8, QFont.Weight.Bold, letter_spacing=1.2))
        sub.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

        # Breadcrumb: Control Panel | Songs Library | [Play History]
        cp = _BreadcrumbLink("Control Panel", h)
        cp.setGeometry(176, 22, 100, 22)
        cp.clicked.connect(
            lambda: self.breadcrumb_clicked.emit("control_panel"))
        sep1 = QLabel("|", h); sep1.setGeometry(272, 22, 8, 22)
        sep1.setFont(inter(11))
        sep1.setStyleSheet(
            f"color: {TEXT_DIM}; background: transparent;")
        sl = _BreadcrumbLink("Songs Library", h)
        sl.setGeometry(284, 22, 100, 22)
        sl.clicked.connect(
            lambda: self.breadcrumb_clicked.emit("songs"))
        sep2 = QLabel("|", h); sep2.setGeometry(384, 22, 8, 22)
        sep2.setFont(inter(11))
        sep2.setStyleSheet(
            f"color: {TEXT_DIM}; background: transparent;")
        pill = _BreadcrumbPill("Play History", PURPLE, h)
        pill.move(396, 20)

        # Title + subtitle
        title = QLabel("Play History", h)
        title.setGeometry(540, 12, 240, 24)
        title.setFont(inter(20, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        sub2 = QLabel(
            "Complete airplay analytics for the selected song", h)
        sub2.setGeometry(540, 38, 500, 14)
        sub2.setFont(inter(10))
        sub2.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

        # Clock + station
        self._clock_lbl = QLabel("", h)
        self._clock_lbl.setGeometry(1108, 14, 100, 24)
        self._clock_lbl.setFont(mono(20, bold=True))
        self._clock_lbl.setStyleSheet(
            f"color: {TEXT_PRI}; background: transparent;")
        try:
            station = Settings().station_display or "KISS FM 91.5"
        except Exception:
            station = "KISS FM 91.5"
        self._station_lbl = QLabel(station, h)
        self._station_lbl.setObjectName("hdr_station_lbl")
        self._station_lbl.setGeometry(1108, 40, 110, 14)
        self._station_lbl.setFont(inter(9, QFont.Weight.Medium))
        self._station_lbl.setStyleSheet(
            f"color: {GREEN}; background: transparent;")

        osb = _HeaderOpenStudio(h)
        osb.move(1222, 16)
        osb.clicked.connect(self.studio_clicked.emit)

    # ── Body ──────────────────────────────────────────────────────────

    def _build_body(self) -> None:
        # Hero
        self._hero = _HeroCard(self)
        self._hero.move(16, 88)

        # Stats row
        self._stat_month = _StatCard(
            "Plays This Month", GREEN, GREEN_LIGHT, self)
        self._stat_week  = _StatCard(
            "Plays This Week",  CYAN,  CYAN_LIGHT,  self)
        self._stat_avg   = _StatCard(
            "Avg / Week",       AMBER, AMBER_LIGHT, self)
        self._stat_last  = _StatCard(
            "Last Played",      PURPLE, PURPLE_LIGHT, self)
        SCARD_W = 340; SCARD_GAP = 12
        total_w = 4 * SCARD_W + 3 * SCARD_GAP
        start_x = (WINDOW_W - total_w) // 2
        ys = 256
        for i, c in enumerate(
                (self._stat_month, self._stat_week,
                 self._stat_avg, self._stat_last)):
            c.move(start_x + i * (SCARD_W + SCARD_GAP), ys)

        # Monthly chart
        self._chart = _MonthlyChart(self)
        self._chart.move(16, 360)

        # Recent plays table
        self._recent = _RecentPlaysTable(self)
        self._recent.move(16, 632)

    # ── Status bar ────────────────────────────────────────────────────

    def _build_status_bar(self) -> None:
        sb = QFrame(self)
        sb.setGeometry(0, WINDOW_H - STATUS_H, WINDOW_W, STATUS_H)
        sb.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border-top: 1px solid {rgba('#ffffff', 0.06)}; }} "
            f"QLabel {{ border: none; }}"
        )
        x = 12
        for txt, col in (("AUTO MODE", PURPLE),
                          ("Live Data", GREEN),
                          ("12-Month View", CYAN)):
            p = _StatusPill(txt, col, sb)
            p.move(x, (STATUS_H - p.height()) // 2)
            x += p.width() + 8

        ver = QLabel("Play History  ·  RadioAI Studio v1.0.0", sb)
        ver.setFont(inter(9))
        ver.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; "
            f"border: none;")
        ver.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        ver.setFixedSize(360, STATUS_H)
        ver.move(WINDOW_W - 24 - 360 - 130, 0)

        osb = QPushButton("▶  Open Studio", sb)
        osb.setFixedSize(120, 26)
        osb.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        osb.setFont(inter(10, QFont.Weight.Bold))
        osb.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {GREEN_LIGHT}; "
            f"border: none; padding: 0 8px; }}"
            f"QPushButton:hover {{ color: {GREEN}; }}"
        )
        osb.move(WINDOW_W - 12 - 120, (STATUS_H - 26) // 2)
        osb.clicked.connect(self.studio_clicked.emit)

    # ── Clock ─────────────────────────────────────────────────────────

    def _tick_clock(self) -> None:
        self._clock_lbl.setText(datetime.now().strftime("%H:%M:%S"))

    # ── Public API ────────────────────────────────────────────────────

    def load_song(self, song_id: int) -> None:
        """Fetch + render everything for `song_id`. Safe to re-call."""
        try:
            sid = int(song_id)
        except Exception:
            sid = 0
        if sid <= 0:
            return
        self._song_id = sid
        try:
            row = self._db.get_song(sid)
            song = ({k: row[k] for k in row.keys()} if row else {})
        except Exception as exc:
            log.warning(f"get_song({sid}) failed: {exc}")
            song = {}
        # Normalise cat_name → category for the hero
        if not song.get("category") and song.get("cat_name"):
            song["category"] = song["cat_name"]
        self._song = song

        try:
            summary = self._db.get_song_play_history_summary(sid)
        except Exception as exc:
            log.warning(f"play_history summary failed: {exc}")
            summary = {"total_plays": 0}

        try:
            monthly = self._db.get_song_monthly_plays(sid, 12)
        except Exception as exc:
            log.warning(f"monthly plays failed: {exc}")
            monthly = []

        try:
            recent = self._db.get_song_recent_plays(sid, 5)
        except Exception as exc:
            log.warning(f"recent plays failed: {exc}")
            recent = []

        # Push into the widgets
        self._hero.load_song(song, summary)
        self._update_stats(summary)
        self._chart.set_data(monthly)
        self._recent.load_rows(recent)
        log.info(
            f"PlayHistory loaded — song_id={sid} "
            f"total={summary.get('total_plays')} months={len(monthly)} "
            f"recent={len(recent)}")

    def _update_stats(self, summary: dict) -> None:
        # This month + delta
        cur_m = int(summary.get("plays_this_month") or 0)
        prev_m = int(summary.get("plays_last_month") or 0)
        diff_m = cur_m - prev_m
        diff_m_s = (f"+{diff_m} vs last month" if diff_m >= 0
                    else f"{diff_m} vs last month")
        self._stat_month.set_value(str(cur_m), diff_m_s)

        # This week + delta
        cur_w = int(summary.get("plays_this_week") or 0)
        prev_w = int(summary.get("plays_last_week") or 0)
        diff_w = cur_w - prev_w
        diff_w_s = (f"+{diff_w} vs last week" if diff_w >= 0
                    else f"{diff_w} vs last week")
        self._stat_week.set_value(str(cur_w), diff_w_s)

        # Avg / week
        avg = summary.get("avg_per_week") or 0.0
        try:
            avg_s = f"{float(avg):.1f}" if float(avg) != int(avg) \
                else str(int(avg))
        except (TypeError, ValueError):
            avg_s = "0"
        self._stat_avg.set_value(avg_s, "rolling 4 weeks")

        # Last played
        lp = summary.get("last_played_at")
        if lp:
            human = _human_ago(lp)
            try:
                d = datetime.strptime(lp[:19],
                                        "%Y-%m-%d %H:%M:%S")
                exact = d.strftime("%d %b %Y  ·  %H:%M")
            except Exception:
                exact = lp[:16]
        else:
            human = "Never played"
            exact = "—"
        self._stat_last.set_value(human, exact)
