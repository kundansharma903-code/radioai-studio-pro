"""
RadioAI Studio Pro — Final Log Creator
Pixel-accurate match of Figma node 14:2 (file 3pYLPe3k86I5hxJNubq9iR).

Reads broadcast_log (populated by Studio on every play) and presents
a per-hour breakdown of what ACTUALLY aired on a given date. The
operator picks Day / Month / Year, hits FETCH REPORT, then steps
through the 24 hour-slots in the sidebar to see the full air log
for any selected hour.

This is the post-broadcast truth — DIFFERENT from a schedule planner
(which projects a future day from auto_schedule). The old
ui/final_log.py was the planner concept (Figma 64:2) and was orphan
code; this file claims the same filename for the new history viewer.

Layout (1920 × 1080 design canvas):
  Header        y=  0.. 72     Logo + title + date/time + Jump To Screen
  Tab bar       y= 72..116     Libraries / Scheduling / Settings / Utilities + station
  Body          y=116..1024
    Left col   320w  SELECT DATE + FETCH REPORT + HOUR SLOTS list
    Center col 1600w BROADCAST LOG header + DOWNLOAD .TXT + table + stats
  Status bar    y=1024..1080   Status text + Auto-saved path + ON AIR strip

DB helpers used:
  db.get_broadcast_log_for_hour(year, month, day, hour) → list[Row]
  db.get_broadcast_hour_counts_for_date(year, month, day) → {hour: count}

Public signals:
  breadcrumb_clicked(str) — chrome tab navigation
  studio_clicked()        — chrome Open Studio button

v1 scope (per pre-build pushback):
  - DOWNLOAD .TXT: on-demand save via QFileDialog, default path
    %LOCALAPPDATA%\\RadioAI\\logs\\<Year>\\<Month>\\<DD>\\<HH>-<HH+1>.log
  - PRINT LOG: toast "Coming soon" (defer printer wiring to v1.1)
  - Auto-save background hourly task: deferred to v1.1
  - Jump To Screen dropdown: decorative-only (no jump wiring)
"""

from __future__ import annotations

import calendar
import logging
import os
from datetime import datetime, date as ddate
from pathlib import Path
from typing import Optional, List

from PyQt6.QtCore import Qt, QRectF, QTimer, pyqtSignal
from core import dialogs
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QLinearGradient, QFont, QCursor,
)
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QComboBox, QHBoxLayout,
    QVBoxLayout, QScrollArea, QMessageBox, QFileDialog,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
)

from core.settings import Settings
from ui.widgets._tokens import (
    inter, mono, rgba,
    BG_BASE, BG_DARK, BG_PANEL, BG_CARD, BG_CARD_DK, BG_ELEVATED,
    TEXT_PRI, TEXT_SEC, TEXT_MUTED, TEXT_DIM,
    CYAN, CYAN_LIGHT, PURPLE, PURPLE_LIGHT,
    GREEN, GREEN_LIGHT, AMBER, AMBER_LIGHT, RED, RED_LIGHT,
    PINK, PINK_LIGHT,
)

log = logging.getLogger("FinalLog")


# ════════════════════════════════════════════════════════════════════════════
# Geometry
# ════════════════════════════════════════════════════════════════════════════

WINDOW_W = 1920
WINDOW_H = 1080

HEADER_H  = 72
TAB_H     = 44
STATUS_H  = 56
LEFT_W    = 320

BODY_Y0   = HEADER_H + TAB_H            # 116
BODY_H    = WINDOW_H - BODY_Y0 - STATUS_H  # 908
CENTER_W  = WINDOW_W - LEFT_W              # 1600

# Type chip palette — TYPE column colors mirror category accents.
TYPE_COLORS = {
    "song":     (CYAN,   CYAN_LIGHT),
    "spot":     (AMBER,  AMBER_LIGHT),
    "jingle":   (GREEN,  GREEN_LIGHT),
    "sweeper":  (PURPLE, PURPLE_LIGHT),
    "stitcher": (PINK,   PINK_LIGHT),
}


def _hour_label(h: int) -> str:
    return f"{h:02d}:00 – {(h + 1) % 24:02d}:00"


def _month_names() -> List[str]:
    return [calendar.month_name[m] for m in range(1, 13)]


def _days_in_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


# ════════════════════════════════════════════════════════════════════════════
# Header chrome
# ════════════════════════════════════════════════════════════════════════════


class _HeaderLogo(QWidget):
    """Cyan-purple gradient circle with white sound-wave bars."""

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


class _JumpToScreenPill(QPushButton):
    """Decorative-only v1 — emits no jumps. Future: routes to other screens."""

    def __init__(self, parent=None):
        super().__init__("Jump To Screen  ▼", parent)
        self.setFixedSize(140, 32)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFont(inter(11, QFont.Weight.Medium))
        self.setStyleSheet(
            f"QPushButton {{ background: {BG_ELEVATED}; color: {TEXT_PRI}; "
            f"border: 1px solid {rgba('#ffffff', 0.10)}; "
            f"border-radius: 6px; padding: 0 12px; text-align: left; }}"
            f"QPushButton:hover {{ "
            f"border: 1px solid {rgba(CYAN, 0.50)}; }}"
        )


class _HeaderBar(QFrame):
    """Top header (1920×72). Logo + title left, live date/time + Jump pill
    right. Clock label updates once per second via the FinalLog's QTimer."""

    studio_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(WINDOW_W, HEADER_H)
        self.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border-bottom: 1px solid {rgba('#ffffff', 0.06)}; }} "
            f"QLabel {{ border: none; }}"
        )

        self._logo = _HeaderLogo(self)
        self._logo.move(24, 16)

        self._title = QLabel("Final Log Creator", self)
        self._title.setFont(inter(20, QFont.Weight.Bold))
        self._title.setStyleSheet(
            f"color: {TEXT_PRI}; background: transparent; border: none;")
        self._title.move(76, 22)
        # Explicit width — height-only sizing left the QLabel at its
        # 100px default width and the title clipped to "Final Log C"
        # (audit 2026-07-03).
        self._title.setFixedSize(240, 28)

        # Live date + time, right side
        self._date_lbl = QLabel("", self)
        self._date_lbl.setFont(inter(13, QFont.Weight.Medium))
        self._date_lbl.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent; border: none;")
        self._date_lbl.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self._sep_lbl = QLabel("|", self)
        self._sep_lbl.setFont(inter(13, QFont.Weight.Light))
        self._sep_lbl.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; border: none;")

        self._time_lbl = QLabel("", self)
        self._time_lbl.setFont(mono(14, bold=True))
        self._time_lbl.setStyleSheet(
            f"color: {TEXT_PRI}; background: transparent; border: none;")

        # Jump To Screen pill
        self._jump = _JumpToScreenPill(self)

        # Position right-anchored items
        self._reposition_right()

    def _reposition_right(self) -> None:
        # Jump pill anchored 24 from right
        self._jump.move(WINDOW_W - 24 - self._jump.width(), 20)
        # Time mono label
        self._time_lbl.setFixedWidth(80)
        self._time_lbl.move(self._jump.x() - 16 - self._time_lbl.width(), 22)
        # Separator
        self._sep_lbl.setFixedWidth(10)
        self._sep_lbl.move(self._time_lbl.x() - 10, 22)
        # Date label  (widest, anchored to left of separator)
        self._date_lbl.setFixedWidth(220)
        self._date_lbl.move(self._sep_lbl.x() - self._date_lbl.width() - 8, 22)
        self._date_lbl.setFixedHeight(28)
        self._time_lbl.setFixedHeight(28)
        self._sep_lbl.setFixedHeight(28)

    def set_now(self, dt: datetime) -> None:
        self._date_lbl.setText(dt.strftime("%A, %B %d, %Y"))
        self._time_lbl.setText(dt.strftime("%H:%M:%S"))


# ════════════════════════════════════════════════════════════════════════════
# Tab bar
# ════════════════════════════════════════════════════════════════════════════


class _TopTab(QPushButton):
    """Libraries / Scheduling / Settings / Utilities tab. Active has cyan
    underline; emits clicked when hit. Active state is set via set_active."""

    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self._name = name
        self._active = False
        self._hover = False
        self.setFixedHeight(TAB_H)
        self.setMinimumWidth(110)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFlat(True)
        self.setStyleSheet("QPushButton { background: transparent; "
                           "border: none; }")

    def set_active(self, on: bool) -> None:
        self._active = bool(on); self.update()

    def enterEvent(self, e):
        self._hover = True; self.update(); super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False; self.update(); super().leaveEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0, 0, self.width(), self.height())
        if self._active:
            p.fillRect(QRectF(0, self.height() - 2, self.width(), 2),
                       QColor(CYAN))
            text_color = TEXT_PRI
        else:
            if self._hover:
                p.fillRect(rect, QColor(rgba('#ffffff', 0.03)))
            text_color = TEXT_SEC if self._hover else TEXT_MUTED
        p.setPen(QColor(text_color))
        p.setFont(inter(13,
                        QFont.Weight.Bold if self._active
                        else QFont.Weight.Medium))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._name)


class _TabBar(QFrame):
    """4 chrome tabs left, AIRMIND FM (station) label right."""

    tab_clicked = pyqtSignal(str)

    def __init__(self, station_name: str, parent=None):
        super().__init__(parent)
        self.setFixedSize(WINDOW_W, TAB_H)
        self.setStyleSheet(
            f"QFrame {{ background: {BG_DARK}; "
            f"border-bottom: 1px solid {rgba('#ffffff', 0.06)}; }} "
            f"QLabel {{ border: none; }}"
        )

        self._tabs: dict[str, _TopTab] = {}
        x = 24
        for nm in ("Libraries", "Scheduling", "Settings", "Utilities"):
            t = _TopTab(nm, self)
            t.move(x, 0)
            t.clicked.connect(lambda _=False, n=nm: self.tab_clicked.emit(n))
            self._tabs[nm] = t
            x += t.minimumWidth() + 12
        # Scheduling = active for Final Log Creator
        self._tabs["Scheduling"].set_active(True)

        self._station = QLabel(station_name, self)
        self._station.setFont(inter(13, QFont.Weight.Bold, letter_spacing=1.4))
        self._station.setStyleSheet(
            f"color: {CYAN_LIGHT}; background: transparent; border: none;")
        self._station.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._station.setFixedSize(280, TAB_H)
        self._station.move(WINDOW_W - 24 - 280, 0)


# ════════════════════════════════════════════════════════════════════════════
# Left panel — SELECT DATE + FETCH + HOUR SLOTS
# ════════════════════════════════════════════════════════════════════════════


class _SmallSectionLabel(QLabel):
    def __init__(self, text: str, color: str = CYAN_LIGHT, parent=None):
        super().__init__(text.upper(), parent)
        self.setFont(inter(9, QFont.Weight.Bold, letter_spacing=1.4))
        self.setStyleSheet(
            f"color: {color}; background: transparent; border: none;")


class _StyledCombo(QComboBox):
    """Dark dropdown matching Figma — bordered, narrow chevron, no
    native focus halo. The combobox view is restyled so the popup list
    blends in instead of showing the OS combobox look."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFont(inter(13, QFont.Weight.Medium))
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setStyleSheet(
            f"QComboBox {{ background: {BG_ELEVATED}; color: {TEXT_PRI}; "
            f"border: 1px solid {rgba('#ffffff', 0.10)}; "
            f"border-radius: 6px; padding: 4px 8px; }}"
            f"QComboBox:hover {{ border: 1px solid {rgba(CYAN, 0.50)}; }}"
            f"QComboBox::drop-down {{ border: none; width: 20px; }}"
            f"QComboBox::down-arrow {{ image: none; }}"
            f"QComboBox QAbstractItemView {{ background: {BG_PANEL}; "
            f"color: {TEXT_PRI}; "
            f"selection-background-color: {rgba(CYAN, 0.25)}; "
            f"border: 1px solid {rgba('#ffffff', 0.10)}; outline: 0; }}"
        )


class _FetchReportButton(QPushButton):
    def __init__(self, parent=None):
        super().__init__("🔍  FETCH REPORT", parent)
        self.setFixedHeight(40)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFont(inter(12, QFont.Weight.Bold, letter_spacing=0.8))
        self.setStyleSheet(
            f"QPushButton {{ background: qlineargradient("
            f"x1:0,y1:0,x2:0,y2:1, stop:0 {CYAN_LIGHT}, stop:1 {CYAN}); "
            f"color: #04141a; border: none; border-radius: 7px; }}"
            f"QPushButton:hover {{ background: qlineargradient("
            f"x1:0,y1:0,x2:0,y2:1, stop:0 #67e8f9, stop:1 {CYAN_LIGHT}); }}"
            f"QPushButton:pressed {{ background: {CYAN}; }}"
        )


class _HourSlotRow(QFrame):
    """One row in the HOUR SLOTS list. Shows hour-range label + count
    badge. Selected state: blue background + ▶ arrow + bold time + larger
    badge. Click anywhere on the row emits clicked(hour)."""

    clicked = pyqtSignal(int)

    def __init__(self, hour: int, parent=None):
        super().__init__(parent)
        self._hour = hour
        self._count = 0
        self._selected = False
        self.setFixedHeight(38)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

    def set_count(self, n: int) -> None:
        self._count = max(0, int(n))
        self.update()

    def set_selected(self, on: bool) -> None:
        self._selected = bool(on); self.update()

    def hour(self) -> int:
        return self._hour

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._hour)
        super().mousePressEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        # Row background — alternating tone + selected highlight
        if self._selected:
            bg = QColor(rgba(CYAN, 0.16))
        else:
            bg = QColor(BG_CARD if (self._hour % 2 == 0) else BG_CARD_DK)
        p.fillRect(QRectF(0, 0, w, h), bg)

        if self._selected:
            # Left accent stripe
            p.fillRect(QRectF(0, 0, 3, h), QColor(CYAN))

        # Time label
        time_x = 16
        if self._selected:
            p.setPen(QColor(CYAN_LIGHT))
            p.setFont(inter(12, QFont.Weight.Bold))
        else:
            p.setPen(QColor(TEXT_SEC))
            p.setFont(inter(11, QFont.Weight.Medium))
        p.drawText(QRectF(time_x, 0, w - 70, h),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   _hour_label(self._hour))

        # ▶ arrow when selected
        if self._selected:
            p.setPen(QColor(CYAN))
            p.setFont(inter(10, QFont.Weight.Bold))
            p.drawText(QRectF(w - 80, 0, 16, h),
                       Qt.AlignmentFlag.AlignVCenter, "▶")

        # Count badge (right-anchored pill)
        badge_w = 36 if self._selected else 30
        badge_x = w - 12 - badge_w
        badge_rect = QRectF(badge_x, (h - 20) / 2, badge_w, 20)
        if self._selected:
            p.setBrush(QColor(rgba(CYAN, 0.32)))
        else:
            p.setBrush(QColor(rgba('#ffffff', 0.06)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(badge_rect, 10, 10)
        p.setPen(QColor(CYAN_LIGHT if self._selected else TEXT_SEC))
        p.setFont(inter(11 if self._selected else 10,
                        QFont.Weight.Bold))
        p.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, str(self._count))


class _HourSlotsList(QScrollArea):
    """Scroll area holding 24 _HourSlotRow widgets. Single-select; emits
    hour_selected(hour) when the user changes selection."""

    hour_selected = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setStyleSheet(
            f"QScrollArea {{ background: transparent; border: none; }}"
            f"QScrollBar:vertical {{ background: {BG_DARK}; width: 8px; }}"
            f"QScrollBar::handle:vertical {{ background: "
            f"{rgba('#ffffff', 0.08)}; border-radius: 4px; }}"
        )

        wrap = QFrame()
        wrap.setStyleSheet(f"QFrame {{ background: transparent; }}")
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0); v.setSpacing(2)

        self._rows: List[_HourSlotRow] = []
        for h in range(24):
            row = _HourSlotRow(h)
            row.clicked.connect(self._on_row_clicked)
            v.addWidget(row)
            self._rows.append(row)
        v.addStretch()
        self.setWidget(wrap)
        self._selected_hour = 0
        self._rows[0].set_selected(True)

    def set_counts(self, counts: dict) -> None:
        for h, row in enumerate(self._rows):
            row.set_count(int(counts.get(h, 0)))

    def select_hour(self, hour: int) -> None:
        hour = max(0, min(23, int(hour)))
        if hour == self._selected_hour:
            return
        self._rows[self._selected_hour].set_selected(False)
        self._selected_hour = hour
        self._rows[hour].set_selected(True)

    def selected_hour(self) -> int:
        return self._selected_hour

    def _on_row_clicked(self, hour: int) -> None:
        self.select_hour(hour)
        self.hour_selected.emit(hour)


# ════════════════════════════════════════════════════════════════════════════
# Center — BROADCAST LOG table + stats strip
# ════════════════════════════════════════════════════════════════════════════


class _ActionButton(QPushButton):
    def __init__(self, text: str, primary: bool = True, parent=None):
        super().__init__(text, parent)
        self.setFixedHeight(34)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFont(inter(11, QFont.Weight.Bold, letter_spacing=0.8))
        if primary:
            self.setStyleSheet(
                f"QPushButton {{ background: qlineargradient("
                f"x1:0,y1:0,x2:0,y2:1, stop:0 {CYAN_LIGHT}, stop:1 {CYAN}); "
                f"color: #04141a; border: none; border-radius: 6px; "
                f"padding: 0 14px; }}"
                f"QPushButton:hover {{ background: qlineargradient("
                f"x1:0,y1:0,x2:0,y2:1, stop:0 #67e8f9, stop:1 {CYAN_LIGHT}); }}"
            )
        else:
            self.setStyleSheet(
                f"QPushButton {{ background: {BG_ELEVATED}; color: {TEXT_PRI}; "
                f"border: 1px solid {rgba('#ffffff', 0.10)}; "
                f"border-radius: 6px; padding: 0 14px; }}"
                f"QPushButton:hover {{ "
                f"border: 1px solid {rgba(CYAN, 0.50)}; }}"
            )


class _BroadcastLogTable(QTableWidget):
    """8-column read-only table: # / TIME / TYPE / TITLE / ARTIST/DETAILS /
    CATEGORY / DURATION / STATUS. Type and Status columns render colored
    chips via custom delegate items."""

    COLUMNS = ["#", "TIME", "TYPE", "TITLE",
               "ARTIST / DETAILS", "CATEGORY", "DURATION", "STATUS"]
    COL_WIDTHS = [50, 110, 110, 280, 240, 200, 110, 110]

    def __init__(self, parent=None):
        super().__init__(0, len(self.COLUMNS), parent)
        self.setHorizontalHeaderLabels(self.COLUMNS)
        self.setShowGrid(False)
        self.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Fixed)
        for i, w in enumerate(self.COL_WIDTHS):
            self.setColumnWidth(i, w)
        # Stretch the TITLE column to take remaining space
        self.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch)
        self.verticalHeader().setDefaultSectionSize(36)
        self.setStyleSheet(
            f"QTableWidget {{ background: {BG_DARK}; "
            f"alternate-background-color: {BG_CARD_DK}; "
            f"color: {TEXT_PRI}; gridline-color: transparent; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; }}"
            f"QHeaderView::section {{ background: {BG_PANEL}; "
            f"color: {TEXT_MUTED}; border: none; "
            f"border-bottom: 1px solid {rgba('#ffffff', 0.08)}; "
            f"padding: 8px 12px; "
            f"font-weight: bold; font-size: 11px; letter-spacing: 1.2px; "
            f"text-align: left; }}"
            f"QTableWidget::item {{ padding: 6px 12px; border: none; }}"
        )

    def load_rows(self, rows: List[dict]) -> None:
        self.setRowCount(len(rows))
        for i, r in enumerate(rows):
            num_item = QTableWidgetItem(str(i + 1))
            num_item.setForeground(QColor(TEXT_MUTED))
            num_item.setFont(mono(11, bold=False))
            self.setItem(i, 0, num_item)

            t_item = QTableWidgetItem(r["time"])
            t_item.setForeground(QColor(TEXT_PRI))
            t_item.setFont(mono(11, bold=False))
            self.setItem(i, 1, t_item)

            # TYPE chip (colored)
            etype = (r.get("type") or "").lower()
            chip_fg, _ = TYPE_COLORS.get(etype, (TEXT_SEC, TEXT_SEC))
            type_item = QTableWidgetItem(etype.upper())
            type_item.setForeground(QColor(chip_fg))
            type_item.setFont(inter(10, QFont.Weight.Bold,
                                    letter_spacing=0.8))
            self.setItem(i, 2, type_item)

            self.setItem(i, 3, self._txt_item(
                r.get("title", "—"), TEXT_PRI, inter(12)))
            self.setItem(i, 4, self._txt_item(
                r.get("artist", "—"), TEXT_SEC, inter(11)))
            self.setItem(i, 5, self._txt_item(
                r.get("category", "—"), TEXT_MUTED, inter(11)))

            dur_item = QTableWidgetItem(r.get("duration", "—"))
            dur_item.setForeground(QColor(TEXT_SEC))
            dur_item.setFont(mono(11, bold=False))
            self.setItem(i, 6, dur_item)

            # STATUS chip (always PLAYED — broadcast_log only logs plays)
            st_item = QTableWidgetItem("PLAYED")
            st_item.setForeground(QColor(GREEN_LIGHT))
            st_item.setFont(inter(10, QFont.Weight.Bold,
                                  letter_spacing=0.8))
            self.setItem(i, 7, st_item)

    @staticmethod
    def _txt_item(text: str, fg: str, font: QFont) -> QTableWidgetItem:
        it = QTableWidgetItem(text)
        it.setForeground(QColor(fg))
        it.setFont(font)
        return it


class _StatsStrip(QFrame):
    """Bottom-of-center summary strip — 6 inline counters."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(52)
        self.setStyleSheet(
            f"QFrame {{ background: {BG_DARK}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; "
            f"border-radius: 6px; }}"
        )
        h = QHBoxLayout(self)
        h.setContentsMargins(20, 4, 20, 4); h.setSpacing(0)

        self._items = []
        specs = [
            ("Total Items",   TEXT_PRI),
            ("Songs",         CYAN_LIGHT),
            ("Spots",         AMBER_LIGHT),
            ("Jingles",       GREEN_LIGHT),
            ("Sweepers",      PURPLE_LIGHT),
            ("Total Air Time", TEXT_PRI),
        ]
        for label, color in specs:
            cell = self._build_cell(label, color)
            h.addWidget(cell, stretch=1)
            self._items.append(cell)

    def _build_cell(self, label: str, color: str) -> QWidget:
        c = QFrame()
        c.setStyleSheet("QFrame { background: transparent; }")
        v = QVBoxLayout(c)
        v.setContentsMargins(0, 0, 0, 0); v.setSpacing(0)
        v.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        val = QLabel("0")
        val.setFont(inter(20, QFont.Weight.Bold))
        val.setStyleSheet(
            f"color: {color}; background: transparent; border: none;")
        val.setAlignment(Qt.AlignmentFlag.AlignLeft
                         | Qt.AlignmentFlag.AlignBottom)

        lbl = QLabel(label)
        lbl.setFont(inter(10))
        lbl.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; border: none;")
        lbl.setAlignment(Qt.AlignmentFlag.AlignLeft
                         | Qt.AlignmentFlag.AlignTop)

        v.addWidget(val)
        v.addWidget(lbl)
        c._val = val  # noqa — informal handle
        return c

    def set_totals(self, total: int, songs: int, spots: int,
                   jingles: int, sweepers: int,
                   air_time_str: str) -> None:
        values = [total, songs, spots, jingles, sweepers]
        for i, v in enumerate(values):
            self._items[i]._val.setText(str(v))
        self._items[5]._val.setText(air_time_str)


# ════════════════════════════════════════════════════════════════════════════
# Status bar
# ════════════════════════════════════════════════════════════════════════════


class _StatusBar(QFrame):
    """Bottom strip — status text left, AirMind version right.
    The ON AIR strip (currently playing) is deferred to v1.1 — placeholder
    label rendered in the same space until the studio injection lands."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(WINDOW_W, STATUS_H)
        self.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border-top: 1px solid {rgba('#ffffff', 0.06)}; }} "
            f"QLabel {{ border: none; }}"
        )

        self._status_lbl = QLabel("Ready — pick a date and FETCH REPORT.", self)
        self._status_lbl.setFont(inter(11, QFont.Weight.Medium))
        self._status_lbl.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent; border: none;")
        self._status_lbl.move(24, 12)
        self._status_lbl.setFixedSize(WINDOW_W - 600, 18)

        self._path_lbl = QLabel("", self)
        self._path_lbl.setFont(inter(10))
        self._path_lbl.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; border: none;")
        self._path_lbl.move(24, 30)
        self._path_lbl.setFixedSize(WINDOW_W - 600, 16)

        # Right: version stamp
        self._ver = QLabel("AirMind v1.0.0  ·  Built for Community Radios",
                           self)
        self._ver.setFont(inter(10))
        self._ver.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; border: none;")
        self._ver.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._ver.setFixedSize(360, STATUS_H)
        self._ver.move(WINDOW_W - 24 - 360, 0)

    def set_status(self, text: str, color: str = TEXT_SEC) -> None:
        self._status_lbl.setText(text)
        self._status_lbl.setStyleSheet(
            f"color: {color}; background: transparent; border: none;")

    def set_path(self, text: str) -> None:
        self._path_lbl.setText(text)


# ════════════════════════════════════════════════════════════════════════════
# Public screen
# ════════════════════════════════════════════════════════════════════════════


class FinalLog(QWidget):
    """Final Log Creator — broadcast history viewer (Figma 14:2).

    Construction is non-fatal even with a partial db mock — used by
    tests that pass a thin _FakeDB shape. Live wiring expects the
    canonical Database singleton with the broadcast_log helpers
    (added in the same commit)."""

    breadcrumb_clicked = pyqtSignal(str)
    studio_clicked     = pyqtSignal()

    def __init__(self, db, parent=None, scheduler=None, studio=None):
        super().__init__(parent)
        self._db = db
        self._scheduler = scheduler
        self._studio = studio
        # Default to today
        today = ddate.today()
        self._sel_year = today.year
        self._sel_month = today.month
        self._sel_day = today.day

        self.setFixedSize(WINDOW_W, WINDOW_H)
        self.setStyleSheet(f"QWidget {{ background: {BG_BASE}; }}")

        # Settings — station name flows here; default to the operator's
        # branding from the settings table.
        try:
            station = Settings().get("station_display") or "AIRMIND FM"
        except Exception:
            station = "AIRMIND FM"

        # Chrome
        self._header = _HeaderBar(self)
        self._header.move(0, 0)

        self._tab_bar = _TabBar(station, self)
        self._tab_bar.move(0, HEADER_H)
        self._tab_bar.tab_clicked.connect(self._on_tab_clicked)

        # Live clock
        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(
            lambda: self._header.set_now(datetime.now()))
        self._clock_timer.start()
        self._header.set_now(datetime.now())

        # Left panel
        self._left = QFrame(self)
        self._left.setGeometry(0, BODY_Y0, LEFT_W, BODY_H)
        self._left.setStyleSheet(
            f"QFrame {{ background: {BG_DARK}; "
            f"border-right: 1px solid {rgba('#ffffff', 0.06)}; }}"
        )
        self._build_left_panel()

        # Center
        self._center = QFrame(self)
        self._center.setGeometry(LEFT_W, BODY_Y0, CENTER_W, BODY_H)
        self._center.setStyleSheet(
            f"QFrame {{ background: {BG_BASE}; }}"
        )
        self._build_center_panel()

        # Status bar
        self._status = _StatusBar(self)
        self._status.move(0, WINDOW_H - STATUS_H)

        # Initial population — counts for today, empty table
        self._reload_hour_counts()
        self._reload_for_hour(self._hours.selected_hour())

    # ── Layout builders ───────────────────────────────────────────────

    def _build_left_panel(self) -> None:
        # Manual layout — match Figma vertical rhythm.
        x = 24
        y = 16
        col_w = LEFT_W - 48

        # SELECT DATE label
        lbl = _SmallSectionLabel("SELECT DATE", parent=self._left)
        lbl.move(x, y); lbl.setFixedWidth(col_w); lbl.setFixedHeight(16)
        y += 22

        # 3 dropdowns
        sub_lbls = ["DAY", "MONTH", "YEAR"]
        sub_w = (col_w - 16) // 3
        for i, t in enumerate(sub_lbls):
            sl = QLabel(t, self._left)
            sl.setFont(inter(9, QFont.Weight.Bold, letter_spacing=1.2))
            sl.setStyleSheet(
                f"color: {TEXT_MUTED}; background: transparent; "
                f"border: none;")
            sl.move(x + i * (sub_w + 8), y)
            sl.setFixedSize(sub_w, 14)
        y += 16

        self._day_cmb = _StyledCombo(self._left)
        self._month_cmb = _StyledCombo(self._left)
        self._year_cmb = _StyledCombo(self._left)
        for cmb in (self._day_cmb, self._month_cmb, self._year_cmb):
            cmb.setFixedSize(sub_w, 34)
        self._day_cmb.move(x, y)
        self._month_cmb.move(x + sub_w + 8, y)
        self._year_cmb.move(x + 2 * (sub_w + 8), y)

        # Populate combos
        self._month_cmb.addItems(_month_names())
        self._month_cmb.setCurrentIndex(self._sel_month - 1)

        cur_year = self._sel_year
        for yr in range(cur_year - 5, cur_year + 2):
            self._year_cmb.addItem(str(yr), userData=yr)
        self._year_cmb.setCurrentText(str(cur_year))

        self._repopulate_days()

        # Signals — when month/year change, day list rebuilds; when any
        # changes, the in-memory selection updates but no fetch fires
        # until FETCH REPORT is clicked.
        self._day_cmb.currentIndexChanged.connect(self._on_day_changed)
        self._month_cmb.currentIndexChanged.connect(self._on_month_changed)
        self._year_cmb.currentIndexChanged.connect(self._on_year_changed)
        y += 50

        # FETCH REPORT
        self._fetch_btn = _FetchReportButton(self._left)
        self._fetch_btn.setFixedWidth(col_w)
        self._fetch_btn.move(x, y)
        self._fetch_btn.clicked.connect(self._on_fetch_clicked)
        y += 56

        # HOUR SLOTS — TODAY
        lbl2 = _SmallSectionLabel("HOUR SLOTS — TODAY", parent=self._left)
        lbl2.move(x, y); lbl2.setFixedWidth(col_w); lbl2.setFixedHeight(16)
        y += 22

        # Scroll area fills remainder
        self._hours = _HourSlotsList(self._left)
        self._hours.setGeometry(x, y, col_w, BODY_H - y - 16)
        self._hours.hour_selected.connect(self._on_hour_selected)

    def _build_center_panel(self) -> None:
        pad = 24
        inner_w = CENTER_W - 2 * pad

        # Title row — BROADCAST LOG (left) + buttons (right)
        self._title_lbl = QLabel("", self._center)
        self._title_lbl.setFont(inter(15, QFont.Weight.Bold,
                                       letter_spacing=0.6))
        self._title_lbl.setStyleSheet(
            f"color: {TEXT_PRI}; background: transparent; border: none;")
        self._title_lbl.move(pad, 16)
        self._title_lbl.setFixedSize(inner_w - 320, 24)

        # DOWNLOAD + PRINT buttons
        self._download_btn = _ActionButton("📥  DOWNLOAD .TXT",
                                            primary=True, parent=self._center)
        self._print_btn    = _ActionButton("🖨  PRINT LOG",
                                            primary=False, parent=self._center)
        self._download_btn.setFixedWidth(150)
        self._print_btn.setFixedWidth(120)
        self._print_btn.move(CENTER_W - pad - 120, 14)
        self._download_btn.move(self._print_btn.x() - 12 - 150, 14)
        self._download_btn.clicked.connect(self._on_download_clicked)
        self._print_btn.clicked.connect(self._on_print_clicked)

        # Table
        self._table = _BroadcastLogTable(self._center)
        self._table.setGeometry(
            pad, 52, inner_w, BODY_H - 52 - 16 - 60)
        # Stats strip (60h, gap 16 above)
        self._stats = _StatsStrip(self._center)
        self._stats.setGeometry(
            pad, BODY_H - 16 - 52, inner_w, 52)

    # ── Combo / fetch handlers ────────────────────────────────────────

    def _repopulate_days(self) -> None:
        prev = self._sel_day
        days = _days_in_month(self._sel_year, self._sel_month)
        # Block signals while we rebuild to avoid spurious _on_day_changed
        self._day_cmb.blockSignals(True)
        self._day_cmb.clear()
        for d in range(1, days + 1):
            self._day_cmb.addItem(str(d), userData=d)
        target = min(prev, days)
        self._sel_day = target
        self._day_cmb.setCurrentIndex(target - 1)
        self._day_cmb.blockSignals(False)

    def _on_day_changed(self, _idx: int) -> None:
        d = self._day_cmb.currentData()
        if d is not None:
            self._sel_day = int(d)

    def _on_month_changed(self, _idx: int) -> None:
        self._sel_month = self._month_cmb.currentIndex() + 1
        self._repopulate_days()

    def _on_year_changed(self, _idx: int) -> None:
        y = self._year_cmb.currentData()
        if y is not None:
            self._sel_year = int(y)
            self._repopulate_days()

    def _on_fetch_clicked(self) -> None:
        self._reload_hour_counts()
        self._reload_for_hour(self._hours.selected_hour())
        d = self._formatted_date()
        self._status.set_status(
            f"Log fetched — see HOUR SLOTS sidebar for per-hour counts.",
            color=GREEN_LIGHT)

    def _on_hour_selected(self, hour: int) -> None:
        self._reload_for_hour(hour)

    # ── Data plumbing ─────────────────────────────────────────────────

    def _reload_hour_counts(self) -> None:
        try:
            counts = self._db.get_broadcast_hour_counts_for_date(
                self._sel_year, self._sel_month, self._sel_day)
        except Exception as exc:
            log.warning(f"hour counts fetch failed: {exc}")
            counts = {h: 0 for h in range(24)}
        self._hours.set_counts(counts)

    def _reload_for_hour(self, hour: int) -> None:
        rows = []
        try:
            rows = self._db.get_broadcast_log_for_hour(
                self._sel_year, self._sel_month, self._sel_day, hour)
        except Exception as exc:
            log.warning(f"hour load failed: {exc}")
            rows = []

        rendered = [self._row_to_dict(r) for r in rows]
        self._table.load_rows(rendered)
        self._update_title_for_hour(hour)
        self._update_stats(rendered)

    def _row_to_dict(self, r) -> dict:
        """Coerce a broadcast_log row (with joined columns) into the
        flat dict shape the table expects."""
        etype = (r["entry_type"] or "").lower()
        # TITLE / ARTIST per entry type
        if etype == "song":
            title  = r["song_title"]  or "—"
            artist = r["song_artist"] or "—"
        elif etype == "spot":
            title  = r["campaign_name"] or "—"
            artist = "Commercial"
        elif etype == "jingle":
            title  = r["jingle_name"] or "—"
            artist = "Station ID"
        else:
            title  = etype.title() or "—"
            artist = "—"

        # TIME — HH:MM:SS from played_at ISO
        played_at = r["played_at"] or ""
        time_s = played_at[11:19] if len(played_at) >= 19 else "—"

        # CATEGORY
        cat = r["cat_name"] or ("Commercial" if etype == "spot"
                                else "Station" if etype == "jingle"
                                else "—")

        # DURATION (ms → m:ss)
        dur_ms = int(r["duration_ms"] or 0)
        if dur_ms > 0:
            total_s = dur_ms // 1000
            dur_str = f"{total_s // 60}:{total_s % 60:02d}"
        else:
            dur_str = "—"

        return {
            "type":     etype,
            "time":     time_s,
            "title":    title,
            "artist":   artist,
            "category": cat,
            "duration": dur_str,
            "duration_ms": dur_ms,
        }

    def _update_title_for_hour(self, hour: int) -> None:
        date_s = self._formatted_date()
        self._title_lbl.setText(
            f"BROADCAST LOG  —  {_hour_label(hour)}   |   {date_s}")

    def _update_stats(self, rows: List[dict]) -> None:
        total = len(rows)
        songs    = sum(1 for r in rows if r["type"] == "song")
        spots    = sum(1 for r in rows if r["type"] == "spot")
        jingles  = sum(1 for r in rows if r["type"] == "jingle")
        sweepers = sum(1 for r in rows if r["type"] == "sweeper")
        total_ms = sum(int(r.get("duration_ms") or 0) for r in rows)
        total_s = total_ms // 1000
        air = f"{total_s // 60}:{total_s % 60:02d}"
        self._stats.set_totals(total, songs, spots, jingles, sweepers, air)

    # ── DOWNLOAD .TXT / PRINT LOG ─────────────────────────────────────

    def _on_download_clicked(self) -> None:
        hour = self._hours.selected_hour()
        rows = []
        try:
            rows = self._db.get_broadcast_log_for_hour(
                self._sel_year, self._sel_month, self._sel_day, hour)
        except Exception as exc:
            log.warning(f"download fetch failed: {exc}")

        rendered = [self._row_to_dict(r) for r in rows]
        text = self._format_log_text(hour, rendered)

        # Default path: %LOCALAPPDATA%\RadioAI\logs\<Year>\<Month>\<DD>\<HH>-<HH+1>.log
        default_path = self._default_download_path(hour)
        default_path.parent.mkdir(parents=True, exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Broadcast Log", str(default_path),
            "Log files (*.log *.txt);;All files (*.*)")
        if not path:
            return
        try:
            Path(path).write_text(text, encoding="utf-8")
        except Exception as exc:
            dialogs.warning(self, "Save Failed",
                                f"Could not write log file:\n{exc}")
            return
        self._status.set_status(
            f"Saved {len(rendered)} entries — {_hour_label(hour)}",
            color=GREEN_LIGHT)
        self._status.set_path(f"Auto-saved to: {path}")

    def _default_download_path(self, hour: int) -> Path:
        appdata = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        base = Path(appdata) / "RadioAI" / "logs"
        month_nm = calendar.month_name[self._sel_month]
        nxt = (hour + 1) % 24
        return (base
                / f"{self._sel_year:04d}"
                / month_nm
                / f"{self._sel_day:02d}"
                / f"{hour:02d}-{nxt:02d}.log")

    def _format_log_text(self, hour: int, rows: List[dict]) -> str:
        date_s = self._formatted_date()
        lines = []
        lines.append("=" * 72)
        lines.append(f"BROADCAST LOG  —  {_hour_label(hour)}")
        lines.append(f"Date: {date_s}")
        lines.append(f"Total entries: {len(rows)}")
        lines.append("=" * 72)
        lines.append("")
        for i, r in enumerate(rows):
            lines.append(
                f"{i + 1:3d}. {r['time']}  "
                f"[{r['type'].upper():8s}]  "
                f"{r['title']}   "
                f"— {r['artist']}  ({r['duration']})")
        lines.append("")
        lines.append("=" * 72)
        lines.append("End of log")
        return "\n".join(lines)

    def _on_print_clicked(self) -> None:
        dialogs.info(
            self, "Print Log",
            "Print Log — coming in v1.1.\n\n"
            "For now use DOWNLOAD .TXT and print the saved file from "
            "your system's text editor.")

    # ── Header tab routing ────────────────────────────────────────────

    def _on_tab_clicked(self, tab_name: str) -> None:
        # Map design tab names → app screen keys.
        mapping = {
            "Libraries":  "libraries",
            "Scheduling": "scheduling_hub",
            "Settings":   "settings",
            "Utilities":  "utilities",
        }
        key = mapping.get(tab_name)
        if key:
            self.breadcrumb_clicked.emit(key)

    # ── Helpers ───────────────────────────────────────────────────────

    def _formatted_date(self) -> str:
        try:
            d = ddate(self._sel_year, self._sel_month, self._sel_day)
            return d.strftime("%A, %d %B %Y")
        except Exception:
            return f"{self._sel_year:04d}-{self._sel_month:02d}-{self._sel_day:02d}"

    # ── Public API ────────────────────────────────────────────────────

    def reload(self) -> None:
        """Re-fetch counts + currently-selected hour. Call this from
        MainWindow when the screen is shown so the data is fresh after
        any Studio playback."""
        self._reload_hour_counts()
        self._reload_for_hour(self._hours.selected_hour())

    def set_studio(self, studio) -> None:
        """ON AIR strip wiring lands in v1.1 — kwarg accepted today
        so MainWindow can inject without conditional checks."""
        self._studio = studio

    def selected_hour(self) -> int:
        return self._hours.selected_hour()

    def selected_date_tuple(self) -> tuple:
        return (self._sel_year, self._sel_month, self._sel_day)
