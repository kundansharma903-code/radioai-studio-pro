"""
RadioAI Studio Pro — Main Auto Schedule (Figma 161:2).

Phase F1: 24-row × 7-col clock-assignment grid backed by auto_schedule.

Layout (1440 × 900)
-------------------
  HEADER     1440 ×  86  y=  0..86  — RadioAI/STUDIO PRO + nav + clock + CTA
  CONTENT    1440 × 778  y= 86..864
    SIDEBAR   240 × 778  x=  0..240   — AVAILABLE CLOCKS list + actions
    MAIN     1200 × 778  x=240..1440  — title + tabs + grid
  STATUSBAR  1440 ×  36  y=864..900   — pills + version + Settings

═════════════════════════════════════════════════════════════════════════════
PERFORMANCE NOTES — DO NOT VIOLATE
═════════════════════════════════════════════════════════════════════════════
  1. The grid has 24×7 = 168 cells. Render in ONE QPainter paintEvent;
     do NOT create 168 child widgets. event.rect() clipping limits work
     to the dirty rect — required for repaint speed when a single cell
     changes.
  2. Hit-testing is coordinate math (no per-cell QFrame).
  3. NO db calls in paintEvent — use self._grid_state cached dict.
  4. NO nested QScrollArea — grid is fixed-height fitting inside outer
     MainWindow scroll.
═════════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import logging
from typing import Optional

from PyQt6.QtCore import Qt, QRect, QRectF, QTimer, QPoint, pyqtSignal
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QFont, QCursor, QMouseEvent, QPalette,
)
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QDialog, QListWidget, QListWidgetItem, QSizePolicy, QMessageBox,
)

from ui.widgets._tokens import (
    inter, mono, rgba,
    BG_BASE, BG_DARK, BG_PANEL, BG_CARD, BG_CARD_DK, BG_ELEVATED,
    TEXT_PRI, TEXT_SEC, TEXT_MUTED, TEXT_DIM,
    CYAN, CYAN_LIGHT, PURPLE, PURPLE_LIGHT, PURPLE_DARK,
    GREEN, GREEN_LIGHT, AMBER, AMBER_LIGHT,
    RED, RED_LIGHT, PINK, PINK_LIGHT, TEAL, TEAL_LIGHT,
)

log = logging.getLogger("AutoSchedule")


# ── Layout ──────────────────────────────────────────────────────────────────

WINDOW_W   = 1440
WINDOW_H   = 900
HEADER_H   = 86
STATUS_H   = 36

LEFT_W = 240
LEFT_X = 0
MAIN_X = LEFT_X + LEFT_W
MAIN_W = WINDOW_W - LEFT_W

CONTENT_Y = HEADER_H
CONTENT_H = WINDOW_H - HEADER_H - STATUS_H

BORDER = "#1c1f38"

# Per-clock palette — deterministic by clock id so cells stay stable.
CLOCK_PALETTE = [AMBER, CYAN, PURPLE, PINK, TEAL, GREEN, AMBER_LIGHT, PURPLE_LIGHT]

DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
DAY_SHORT = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")


def _clock_color(clock_id: int) -> str:
    return CLOCK_PALETTE[(int(clock_id) - 1) % len(CLOCK_PALETTE)]


# ════════════════════════════════════════════════════════════════════════════
# HEADER
# ════════════════════════════════════════════════════════════════════════════

class _Header(QFrame):
    control_panel_clicked = pyqtSignal()
    clock_editor_clicked  = pyqtSignal()
    studio_clicked        = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(HEADER_H)
        self.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border-bottom: 1px solid {BORDER}; }}"
        )

        self._clock_text = "00:00:00"
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick_clock)
        self._timer.start()
        self._tick_clock()

        # Nav buttons
        cp_btn = QPushButton("Control Panel", self)
        cp_btn.setGeometry(220, 30, 110, 28)
        cp_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        cp_btn.setFont(inter(10, QFont.Weight.Medium))
        cp_btn.setStyleSheet(self._nav_qss(active=False))
        cp_btn.clicked.connect(self.control_panel_clicked.emit)

        sched_btn = QPushButton("Scheduling", self)
        sched_btn.setGeometry(336, 30, 92, 28)
        sched_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        sched_btn.setFont(inter(10, QFont.Weight.Medium))
        sched_btn.setStyleSheet(self._nav_qss(active=False))
        # Scheduling = Hub. Wired in F3.

        ce_btn = QPushButton("Clock Editor", self)
        ce_btn.setGeometry(434, 30, 108, 28)
        ce_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        ce_btn.setFont(inter(10, QFont.Weight.Medium))
        ce_btn.setStyleSheet(self._nav_qss(active=False))
        ce_btn.clicked.connect(self.clock_editor_clicked.emit)

        ms_btn = QPushButton("Main Auto Schedule", self)
        ms_btn.setGeometry(548, 30, 156, 28)
        ms_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        ms_btn.setFont(inter(10, QFont.Weight.DemiBold))
        ms_btn.setStyleSheet(self._nav_qss(active=True))

        # Open Studio CTA
        st_btn = QPushButton("▶  Open Studio", self)
        st_btn.setGeometry(WINDOW_W - 220, 26, 200, 36)
        st_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        st_btn.setFont(inter(11, QFont.Weight.Bold, letter_spacing=0.4))
        st_btn.setStyleSheet(
            f"QPushButton {{ background: qlineargradient("
            f"x1:0,y1:0,x2:1,y2:0, stop:0 {PURPLE_LIGHT}, "
            f"stop:1 {PURPLE_DARK}); "
            f"color: white; border: none; border-radius: 8px; }}"
            f"QPushButton:hover {{ background: qlineargradient("
            f"x1:0,y1:0,x2:1,y2:0, stop:0 #c4b5fd, stop:1 {PURPLE}); }}"
        )
        st_btn.clicked.connect(self.studio_clicked.emit)

    @staticmethod
    def _nav_qss(active: bool) -> str:
        if active:
            return (
                f"QPushButton {{ background: {rgba(CYAN, 0.18)}; "
                f"color: {CYAN_LIGHT}; "
                f"border: 1px solid {rgba(CYAN, 0.40)}; "
                f"border-radius: 6px; padding: 0 12px; }}"
            )
        return (
            f"QPushButton {{ background: transparent; "
            f"color: {TEXT_SEC}; "
            f"border: 1px solid transparent; "
            f"border-radius: 6px; padding: 0 12px; }}"
            f"QPushButton:hover {{ color: {TEXT_PRI}; "
            f"border: 1px solid {rgba('#ffffff', 0.10)}; }}"
        )

    def _tick_clock(self):
        from datetime import datetime
        self._clock_text = datetime.now().strftime("%H:%M:%S")
        self.update(QRect(680, 0, 220, HEADER_H))

    def paintEvent(self, _e):
        super().paintEvent(_e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Logo dot
        p.setBrush(QColor(PURPLE)); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(14, HEADER_H // 2 - 6, 12, 12)

        # RadioAI title block
        p.setPen(QColor(TEXT_PRI))
        p.setFont(inter(18, QFont.Weight.Black, letter_spacing=0.4))
        p.drawText(QRectF(75, 14, 200, 22),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "RadioAI")
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(inter(9, QFont.Weight.DemiBold, letter_spacing=1.6))
        p.drawText(QRectF(75, 36, 200, 18),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "STUDIO PRO")
        p.setPen(QColor(TEXT_DIM))
        p.setFont(inter(8, QFont.Weight.Bold, letter_spacing=1.2))
        p.drawText(QRectF(75, 54, 200, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "BROADCAST AUTOMATION")

        # Live clock + date
        p.setPen(QColor(TEXT_PRI))
        p.setFont(mono(20, bold=True))
        p.drawText(QRectF(WINDOW_W - 530, 18, 220, 28),
                   Qt.AlignmentFlag.AlignCenter, self._clock_text)
        from datetime import datetime
        date_text = datetime.now().strftime("%A, %d %B %Y")
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(inter(9))
        p.drawText(QRectF(WINDOW_W - 530, 46, 220, 14),
                   Qt.AlignmentFlag.AlignCenter, date_text)

        # ACTIVE STATION pill
        pill = QRectF(WINDOW_W - 290, 24, 175, 36)
        p.setBrush(QColor(BG_CARD_DK)); p.setPen(QPen(QColor(BORDER), 1))
        p.drawRoundedRect(pill, 8, 8)
        p.setPen(QColor(TEXT_DIM))
        p.setFont(inter(7, QFont.Weight.Bold, letter_spacing=1.0))
        p.drawText(pill.adjusted(12, 4, -10, -20),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   "ACTIVE STATION")
        p.setPen(QColor(CYAN_LIGHT))
        p.setFont(inter(11, QFont.Weight.Bold))
        p.drawText(pill.adjusted(12, 12, -10, 0),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   "KISS FM 91.5")


# ════════════════════════════════════════════════════════════════════════════
# CLOCKS SIDEBAR
# ════════════════════════════════════════════════════════════════════════════

class _ClockRow(QFrame):
    clicked = pyqtSignal(int)
    double_clicked = pyqtSignal(int)   # opens modal Clock Editor (ref 225:5)

    def __init__(self, clock: dict, is_active: bool, parent=None):
        super().__init__(parent)
        self._clock = dict(clock)
        self._active = bool(is_active)
        self.setFixedHeight(50)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(int(self._clock.get("id", 0)))

    def mouseDoubleClickEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit(int(self._clock.get("id", 0)))
        super().mouseDoubleClickEvent(e)

    def paintEvent(self, _e):
        super().paintEvent(_e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(8, 3, -8, -3)
        color = _clock_color(int(self._clock.get("id", 1)))
        bg = BG_ELEVATED if self._active else BG_CARD_DK
        p.setBrush(QColor(bg))
        p.setPen(QPen(QColor(color if self._active else BORDER), 1))
        p.drawRoundedRect(QRectF(rect), 5, 5)
        # Color dot
        p.setBrush(QColor(color)); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(rect.x() + 8, rect.y() + 12, 8, 8))
        # Name
        p.setPen(QColor(TEXT_PRI if self._active else TEXT_SEC))
        p.setFont(inter(11, QFont.Weight.DemiBold))
        p.drawText(QRectF(rect.x() + 24, rect.y() + 4, rect.width() - 50, 18),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   str(self._clock.get("name") or "—"))
        # Time range
        ts = self._clock.get("time_start") or ""; te = self._clock.get("time_end") or ""
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(mono(8, bold=False))
        p.drawText(QRectF(rect.x() + 24, rect.y() + 22, rect.width() - 50, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   f"{ts}–{te}" if (ts or te) else "00:00–24:00")
        # Slot count badge
        n = int(self._clock.get("slot_count") or 0)
        p.setPen(QColor(TEXT_DIM))
        p.setFont(inter(10, QFont.Weight.Bold))
        p.drawText(QRectF(rect.right() - 30, rect.y() + 4, 24, 36),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   str(n))


class _ClocksSidebar(QFrame):
    clock_selected      = pyqtSignal(int)
    clock_double_clicked = pyqtSignal(int)  # opens modal Clock Editor
    new_clock           = pyqtSignal()
    edit_clock          = pyqtSignal()      # SET >> — open editor on selected
    duplicate_clock     = pyqtSignal()
    auto_program        = pyqtSignal()      # stub
    delete_clock        = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(LEFT_W, CONTENT_H)
        self.setStyleSheet(
            f"QFrame {{ background: {BG_DARK}; "
            f"border-right: 1px solid {BORDER}; }}"
        )
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 14, 8, 12); v.setSpacing(6)

        header = QLabel("AVAILABLE CLOCKS")
        header.setFont(inter(8, QFont.Weight.Black, letter_spacing=1.6))
        header.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        v.addWidget(header)

        new_btn = QPushButton("+ New Clock")
        new_btn.setFixedHeight(28)
        new_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        new_btn.setFont(inter(10, QFont.Weight.DemiBold))
        new_btn.setStyleSheet(
            f"QPushButton {{ background: {rgba(CYAN, 0.16)}; "
            f"color: {CYAN_LIGHT}; "
            f"border: 1px solid {rgba(CYAN, 0.32)}; "
            f"border-radius: 5px; }}"
            f"QPushButton:hover {{ background: {rgba(CYAN, 0.26)}; }}"
        )
        new_btn.clicked.connect(self.new_clock.emit)
        v.addWidget(new_btn)

        # Rows
        self._rows_box = QFrame(); self._rows_box.setStyleSheet("background: transparent;")
        self._rows_layout = QVBoxLayout(self._rows_box)
        self._rows_layout.setContentsMargins(0, 4, 0, 4); self._rows_layout.setSpacing(3)
        v.addWidget(self._rows_box)
        v.addStretch()

        # Bottom action stack — SET in red per ref 225:4
        for label, color, signal in [
            ("SET ▶▶",                RED,       self.edit_clock),
            ("Duplicate Clock",       CYAN_LIGHT, self.duplicate_clock),
            ("Auto Program Settings", PURPLE_LIGHT, self.auto_program),
            ("✗  Delete Clock",       RED_LIGHT, self.delete_clock),
        ]:
            b = QPushButton(label)
            b.setFixedHeight(30)
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.setFont(inter(10, QFont.Weight.DemiBold))
            b.setStyleSheet(
                f"QPushButton {{ background: {rgba(color, 0.14)}; "
                f"color: {color}; "
                f"border: 1px solid {rgba(color, 0.32)}; "
                f"border-radius: 5px; padding: 0 8px; }}"
                f"QPushButton:hover {{ background: {rgba(color, 0.24)}; }}"
            )
            b.clicked.connect(signal.emit)
            v.addWidget(b)

        self._rows: list[_ClockRow] = []

    def populate(self, clocks: list[dict], active_id: Optional[int]) -> None:
        for r in self._rows:
            r.setParent(None); r.deleteLater()
        self._rows.clear()
        for clk in clocks:
            row = _ClockRow(clk, is_active=(int(clk.get("id") or 0) == int(active_id or 0)))
            row.clicked.connect(self.clock_selected.emit)
            row.double_clicked.connect(self.clock_double_clicked.emit)
            self._rows_layout.addWidget(row)
            self._rows.append(row)


# ════════════════════════════════════════════════════════════════════════════
# GRID — single QPainter surface for all 168 cells
# ════════════════════════════════════════════════════════════════════════════

class _Grid(QWidget):
    cell_clicked       = pyqtSignal(int, int)   # day, hour (left click)
    cell_right_clicked = pyqtSignal(int, int)   # right click → quick clear

    HOUR_COL_W = 64
    HEADER_ROW_H = 32
    ROW_H = 26

    def __init__(self, parent=None):
        super().__init__(parent)
        self._grid_state: dict[tuple[int, int], int] = {}     # (day, hour) → clock_id
        self._clocks: dict[int, dict] = {}                    # clock_id → row dict
        self._hover: Optional[tuple[int, int]] = None
        # Total 24 rows + 1 header → fixed height
        h = self.HEADER_ROW_H + 24 * self.ROW_H + 6
        self.setMinimumHeight(h)
        self.setMaximumHeight(h + 4)
        self.setMouseTracking(False)

    def set_data(self, grid: dict, clocks: list[dict]) -> None:
        self._grid_state = dict(grid or {})
        self._clocks = {int(c["id"]): dict(c) for c in (clocks or [])}
        self.update()

    def _cell_rect(self, day: int, hour: int) -> QRect:
        cell_w = (self.width() - self.HOUR_COL_W - 4) // 7
        x = self.HOUR_COL_W + 2 + day * cell_w
        y = self.HEADER_ROW_H + hour * self.ROW_H
        return QRect(x + 2, y + 2, cell_w - 4, self.ROW_H - 4)

    def _hit_test(self, pos: QPoint) -> Optional[tuple[int, int]]:
        if pos.x() < self.HOUR_COL_W or pos.y() < self.HEADER_ROW_H:
            return None
        cell_w = (self.width() - self.HOUR_COL_W - 4) // 7
        if cell_w <= 0:
            return None
        day = (pos.x() - self.HOUR_COL_W - 2) // cell_w
        hour = (pos.y() - self.HEADER_ROW_H) // self.ROW_H
        if 0 <= day <= 6 and 0 <= hour <= 23:
            return int(day), int(hour)
        return None

    def mousePressEvent(self, e: QMouseEvent) -> None:
        cell = self._hit_test(e.pos())
        if cell is None:
            return
        day, hour = cell
        if e.button() == Qt.MouseButton.LeftButton:
            self.cell_clicked.emit(day, hour)
        elif e.button() == Qt.MouseButton.RightButton:
            self.cell_right_clicked.emit(day, hour)

    def paintEvent(self, evt):
        super().paintEvent(evt)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)  # crisper grid lines
        dirty = evt.rect()

        w = self.width(); h = self.height()
        cell_w = (w - self.HOUR_COL_W - 4) // 7

        # Background
        if dirty.intersects(self.rect()):
            p.setBrush(QColor(BG_CARD_DK)); p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(QRectF(0, 0, w, h), 8, 8)

        # Header row (HOUR | days)
        hdr = QRect(0, 0, w, self.HEADER_ROW_H)
        if dirty.intersects(hdr):
            p.setBrush(QColor(BG_PANEL)); p.setPen(QPen(QColor(BORDER), 1))
            p.drawRect(hdr)
            p.setPen(QColor(TEXT_MUTED))
            p.setFont(inter(8, QFont.Weight.Black, letter_spacing=1.4))
            p.drawText(QRectF(0, 0, self.HOUR_COL_W, self.HEADER_ROW_H),
                       Qt.AlignmentFlag.AlignCenter, "HOUR")
            for d in range(7):
                x = self.HOUR_COL_W + 2 + d * cell_w
                weekend = d >= 5
                p.setPen(QColor(PINK if weekend else TEXT_SEC))
                p.setFont(inter(9, QFont.Weight.Black, letter_spacing=1.2))
                p.drawText(QRectF(x, 0, cell_w, self.HEADER_ROW_H),
                           Qt.AlignmentFlag.AlignCenter, DAYS[d].upper())

        # Body — 24 rows × (HOUR cell + 7 day cells)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        for hour in range(24):
            row_y = self.HEADER_ROW_H + hour * self.ROW_H
            row_rect = QRect(0, row_y, w, self.ROW_H)
            if not dirty.intersects(row_rect):
                continue

            # Hour label
            p.setPen(QColor(TEXT_MUTED))
            p.setFont(mono(9, bold=False))
            p.drawText(QRectF(0, row_y, self.HOUR_COL_W, self.ROW_H),
                       Qt.AlignmentFlag.AlignCenter, f"{hour:02d}:00")

            for day in range(7):
                cell = self._cell_rect(day, hour)
                if not dirty.intersects(cell):
                    continue
                clock_id = self._grid_state.get((day, hour))
                if clock_id is None:
                    # Empty cell — faint placeholder text
                    p.setBrush(QColor(BG_BASE)); p.setPen(QPen(QColor(BORDER), 1))
                    p.drawRoundedRect(QRectF(cell), 3, 3)
                    p.setPen(QColor(TEXT_DIM))
                    p.setFont(inter(8))
                    p.drawText(QRectF(cell),
                               Qt.AlignmentFlag.AlignCenter,
                               "—")
                else:
                    clock = self._clocks.get(clock_id, {})
                    color = _clock_color(clock_id)
                    body = QColor(color); body.setAlphaF(0.22)
                    p.setBrush(body)
                    p.setPen(QPen(QColor(color), 1))
                    p.drawRoundedRect(QRectF(cell), 3, 3)
                    p.setPen(QColor(TEXT_PRI))
                    p.setFont(inter(8, QFont.Weight.DemiBold))
                    name = str(clock.get("name") or f"#{clock_id}")
                    if len(name) > 12:
                        name = name[:11] + "…"
                    p.drawText(QRectF(cell.adjusted(4, 0, -4, 0)),
                               Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                               name)


# ════════════════════════════════════════════════════════════════════════════
# ASSIGNMENT DIALOG (cell-click modal)
# ════════════════════════════════════════════════════════════════════════════

class _AssignmentDialog(QDialog):
    """Modal shown on cell click. If the cell is empty, just shows a clock
    list. If filled, shows current + Change/Clear/Cancel."""

    def __init__(self, day: int, hour: int, current_clock: Optional[dict],
                 clocks: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Assign Clock — {DAY_SHORT[day]} {hour:02d}:00")
        self.setModal(True)
        self.setStyleSheet(f"QDialog {{ background: {BG_PANEL}; }}")
        self.setFixedSize(420, 480)
        self._chosen_clock_id: Optional[int] = None
        self._do_clear: bool = False

        v = QVBoxLayout(self)
        v.setContentsMargins(16, 16, 16, 16); v.setSpacing(10)

        title_text = f"{DAYS[day]}  ·  {hour:02d}:00 – {(hour+1)%24:02d}:00"
        if current_clock:
            title_text += f"\nCurrently: {current_clock.get('name', '—')}"
        title = QLabel(title_text)
        title.setFont(inter(11, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        title.setWordWrap(True)
        v.addWidget(title)

        # Clock list
        self._list = QListWidget()
        self._list.setStyleSheet(
            f"QListWidget {{ background: {BG_CARD_DK}; "
            f"color: {TEXT_PRI}; "
            f"border: 1px solid {BORDER}; "
            f"border-radius: 6px; padding: 4px; }}"
            f"QListWidget::item {{ padding: 6px; border-radius: 3px; }}"
            f"QListWidget::item:selected {{ background: {rgba(CYAN, 0.20)}; "
            f"color: {CYAN_LIGHT}; }}"
        )
        for c in clocks:
            item = QListWidgetItem(f"{c.get('name', '—')}   ·   "
                                   f"{c.get('slot_count') or 0} slots")
            item.setData(Qt.ItemDataRole.UserRole, int(c["id"]))
            self._list.addItem(item)
            if current_clock and int(c["id"]) == int(current_clock.get("id", -1)):
                self._list.setCurrentItem(item)
        self._list.itemDoubleClicked.connect(self._on_assign)
        v.addWidget(self._list, 1)

        # Buttons
        btn_row = QHBoxLayout(); btn_row.setSpacing(8)
        if current_clock:
            clear_btn = QPushButton("Clear Cell")
            clear_btn.setFixedHeight(32)
            clear_btn.setFont(inter(10, QFont.Weight.DemiBold))
            clear_btn.setStyleSheet(
                f"QPushButton {{ background: {rgba(RED, 0.18)}; "
                f"color: {RED}; border: 1px solid {rgba(RED, 0.40)}; "
                f"border-radius: 5px; padding: 0 12px; }}"
                f"QPushButton:hover {{ background: {rgba(RED, 0.28)}; }}"
            )
            clear_btn.clicked.connect(self._on_clear)
            btn_row.addWidget(clear_btn)
        btn_row.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedHeight(32)
        cancel_btn.setFont(inter(10))
        cancel_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; "
            f"color: {TEXT_SEC}; "
            f"border: 1px solid {BORDER}; "
            f"border-radius: 5px; padding: 0 12px; }}"
            f"QPushButton:hover {{ color: {TEXT_PRI}; "
            f"border-color: {TEXT_MUTED}; }}"
        )
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        ok_btn = QPushButton("Assign" if not current_clock else "Change")
        ok_btn.setFixedHeight(32)
        ok_btn.setDefault(True)
        ok_btn.setFont(inter(10, QFont.Weight.Bold))
        ok_btn.setStyleSheet(
            f"QPushButton {{ background: {rgba(GREEN, 0.20)}; "
            f"color: {GREEN_LIGHT}; "
            f"border: 1px solid {rgba(GREEN, 0.50)}; "
            f"border-radius: 5px; padding: 0 14px; }}"
            f"QPushButton:hover {{ background: {rgba(GREEN, 0.30)}; }}"
        )
        ok_btn.clicked.connect(self._on_assign)
        btn_row.addWidget(ok_btn)
        v.addLayout(btn_row)

    def _on_assign(self, *_):
        item = self._list.currentItem()
        if item is None:
            return
        self._chosen_clock_id = int(item.data(Qt.ItemDataRole.UserRole))
        self.accept()

    def _on_clear(self):
        self._do_clear = True
        self.accept()

    @property
    def chosen_clock_id(self) -> Optional[int]:
        return self._chosen_clock_id

    @property
    def do_clear(self) -> bool:
        return self._do_clear


# ════════════════════════════════════════════════════════════════════════════
# STATUS BAR
# ════════════════════════════════════════════════════════════════════════════

class _StatusBar(QFrame):
    settings_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(STATUS_H)
        self.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border-top: 1px solid {BORDER}; }}"
        )
        h = QHBoxLayout(self); h.setContentsMargins(14, 4, 14, 4); h.setSpacing(8)
        for label, color in [("AUTO MODE", GREEN),
                             ("AI Active", PURPLE_LIGHT),
                             ("Log Ready", CYAN_LIGHT)]:
            pill = QLabel(label); pill.setFixedHeight(22)
            pill.setFont(inter(8, QFont.Weight.Black, letter_spacing=1.4))
            pill.setStyleSheet(
                f"QLabel {{ background: {rgba(color, 0.16)}; "
                f"color: {color}; "
                f"border: 1px solid {rgba(color, 0.40)}; "
                f"border-radius: 11px; padding: 0 12px; }}"
            )
            h.addWidget(pill)
        self._clocks_pill = QLabel("0 Clocks"); self._clocks_pill.setFixedHeight(22)
        self._clocks_pill.setFont(inter(8, QFont.Weight.Black, letter_spacing=1.4))
        self._clocks_pill.setStyleSheet(
            f"QLabel {{ background: {rgba(AMBER, 0.16)}; "
            f"color: {AMBER}; "
            f"border: 1px solid {rgba(AMBER, 0.40)}; "
            f"border-radius: 11px; padding: 0 12px; }}"
        )
        h.addWidget(self._clocks_pill)
        h.addStretch()
        version = QLabel("RadioAI Studio v1.0.0  ·  Main Auto Schedule")
        version.setFont(inter(9))
        version.setStyleSheet(f"color: {TEXT_DIM}; background: transparent;")
        h.addWidget(version)
        s_btn = QPushButton("Settings")
        s_btn.setFixedHeight(24); s_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        s_btn.setFont(inter(9, QFont.Weight.Bold))
        s_btn.setStyleSheet(
            f"QPushButton {{ background: {rgba(PURPLE, 0.18)}; "
            f"color: {PURPLE_LIGHT}; "
            f"border: 1px solid {rgba(PURPLE, 0.40)}; "
            f"border-radius: 5px; padding: 0 14px; }}"
            f"QPushButton:hover {{ background: {rgba(PURPLE, 0.28)}; }}"
        )
        s_btn.clicked.connect(self.settings_clicked.emit)
        h.addWidget(s_btn)

    def set_clock_count(self, n: int) -> None:
        self._clocks_pill.setText(f"{n} Clocks")


# ════════════════════════════════════════════════════════════════════════════
# AUTO SCHEDULE — top-level
# ════════════════════════════════════════════════════════════════════════════

class AutoSchedule(QWidget):

    breadcrumb_clicked     = pyqtSignal(str)   # 'control_panel'  or 'clock_editor'
    studio_clicked         = pyqtSignal()

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self._db = db
        self.setFixedSize(WINDOW_W, WINDOW_H)
        self.setStyleSheet(f"QWidget {{ background: {BG_BASE}; }}")

        # First-mount housekeeping — collapse multi-hour ranges into per-hour.
        try:
            n = self._db.normalize_auto_schedule()
            if n:
                log.info(f"[auto-schedule] normalized {n} multi-hour ranges")
        except Exception as exc:
            log.warning(f"[auto-schedule] normalize skipped: {exc}")

        self._clocks: list[dict] = []
        self._selected_clock_id: Optional[int] = None

        # Header
        self._header = _Header(self)
        self._header.setGeometry(0, 0, WINDOW_W, HEADER_H)
        self._header.control_panel_clicked.connect(
            lambda: self.breadcrumb_clicked.emit("control_panel"))
        self._header.clock_editor_clicked.connect(
            lambda: self.breadcrumb_clicked.emit("clock_editor"))
        self._header.studio_clicked.connect(self.studio_clicked.emit)

        # Sidebar
        self._sidebar = _ClocksSidebar(self)
        self._sidebar.setGeometry(LEFT_X, CONTENT_Y, LEFT_W, CONTENT_H)
        self._sidebar.clock_selected.connect(self._on_clock_selected)
        self._sidebar.clock_double_clicked.connect(self._launch_clock_editor)
        self._sidebar.new_clock.connect(self._on_new_clock)
        self._sidebar.edit_clock.connect(self._on_edit_clock)
        self._sidebar.duplicate_clock.connect(self._on_duplicate_clock)
        self._sidebar.auto_program.connect(self._on_auto_program_stub)
        self._sidebar.delete_clock.connect(self._on_delete_clock)

        # Main content area — title block + tabs + clear-all + grid
        self._main = QWidget(self)
        self._main.setGeometry(MAIN_X, CONTENT_Y, MAIN_W, CONTENT_H)
        self._main.setStyleSheet(f"QWidget {{ background: {BG_BASE}; }}")
        v = QVBoxLayout(self._main); v.setContentsMargins(20, 16, 20, 16); v.setSpacing(10)

        title = QLabel("Clocks Schedule")
        title.setFont(inter(18, QFont.Weight.Black, letter_spacing=0.4))
        title.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        v.addWidget(title)
        sub = QLabel("Assign clocks to specific hours — each cell = 1 hour of broadcast")
        sub.setFont(inter(10))
        sub.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        v.addWidget(sub)

        # Tab bar + clear all — Specific Days first per ref 225:4
        bar_row = QHBoxLayout(); bar_row.setSpacing(6)
        specific_tab = QPushButton("Specific Days")
        specific_tab.setFixedHeight(32)
        specific_tab.setFont(inter(10, QFont.Weight.DemiBold))
        specific_tab.setEnabled(False)
        specific_tab.setToolTip("Phase F polish")
        specific_tab.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {TEXT_DIM}; "
            f"border: 1px solid {BORDER}; "
            f"border-radius: 5px; padding: 0 16px; }}"
        )
        bar_row.addWidget(specific_tab)
        weekdays_tab = QPushButton("Weekdays")
        weekdays_tab.setFixedHeight(32)
        weekdays_tab.setFont(inter(10, QFont.Weight.DemiBold))
        weekdays_tab.setStyleSheet(
            f"QPushButton {{ background: {rgba(CYAN, 0.20)}; "
            f"color: {CYAN_LIGHT}; "
            f"border: 1px solid {rgba(CYAN, 0.50)}; "
            f"border-radius: 5px; padding: 0 16px; }}"
        )
        bar_row.addWidget(weekdays_tab)
        bar_row.addStretch()
        clear_btn = QPushButton("Clear All")
        clear_btn.setFixedHeight(32)
        clear_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        clear_btn.setFont(inter(10, QFont.Weight.DemiBold))
        clear_btn.setStyleSheet(
            f"QPushButton {{ background: {rgba(RED, 0.16)}; "
            f"color: {RED}; "
            f"border: 1px solid {rgba(RED, 0.36)}; "
            f"border-radius: 5px; padding: 0 14px; }}"
            f"QPushButton:hover {{ background: {rgba(RED, 0.26)}; }}"
        )
        clear_btn.clicked.connect(self._on_clear_all)
        bar_row.addWidget(clear_btn)
        v.addLayout(bar_row)

        # Grid
        self._grid = _Grid()
        self._grid.cell_clicked.connect(self._on_cell_clicked)
        self._grid.cell_right_clicked.connect(self._on_cell_right_clicked)
        v.addWidget(self._grid)
        v.addStretch()

        # Status bar
        self._status = _StatusBar(self)
        self._status.setGeometry(0, WINDOW_H - STATUS_H, WINDOW_W, STATUS_H)
        self._status.settings_clicked.connect(self._on_settings_stub)

        # Initial data load
        self._refresh_all()
        log.info("AutoSchedule ready (Figma 161:2)")

    # ── data ──────────────────────────────────────────────────────────────

    def _refresh_all(self) -> None:
        try:
            self._clocks = [dict(r) for r in self._db.get_all_clocks()]
        except Exception as exc:
            log.warning(f"clocks list load failed: {exc}")
            self._clocks = []
        try:
            grid = self._db.get_auto_schedule_grid()
        except Exception as exc:
            log.warning(f"grid load failed: {exc}")
            grid = {}
        self._sidebar.populate(self._clocks, active_id=self._selected_clock_id)
        self._grid.set_data(grid, self._clocks)
        self._status.set_clock_count(len(self._clocks))

    # ── handlers ──────────────────────────────────────────────────────────

    def _on_clock_selected(self, clock_id: int) -> None:
        self._selected_clock_id = int(clock_id)
        self._sidebar.populate(self._clocks, active_id=self._selected_clock_id)

    def _launch_clock_editor(self, clock_id: int) -> None:
        """Single dispatch point for opening the Clock Editor on a clock id.

        Phase F-Final S5 follow-up (ref 225:5): C3 will replace this with
        a modal QDialog (`ClockEditorDialog`). For now the C2 commit
        keeps the existing full-screen route — the breadcrumb signal
        flips MainWindow's stack to the existing clock_editor screen
        and that screen's _load_clock pre-loads the requested id."""
        log.info(f"[auto-schedule] launch clock editor for id={clock_id}")
        # Ask MainWindow to open Clock Editor; it will load whichever
        # clock is the screen's _current_clock_id (carried from the
        # last visit). Pre-loading a specific id requires the modal
        # path arriving in C3.
        self._selected_clock_id = int(clock_id)
        self.breadcrumb_clicked.emit("clock_editor")

    def _on_edit_clock(self) -> None:
        """SET ▶▶ button — opens Clock Editor for the currently-selected
        clock. Falls back to first available clock if none selected."""
        cid = self._selected_clock_id
        if cid is None and self._clocks:
            cid = int(self._clocks[0]["id"])
        if cid is None:
            QMessageBox.information(self, "No clocks",
                                    "Create a clock first via + New Clock.")
            return
        self._launch_clock_editor(cid)

    def _on_new_clock(self) -> None:
        try:
            new_id = self._db.create_clock("New Clock")
        except Exception as exc:
            log.warning(f"create_clock failed: {exc}")
            return
        self._selected_clock_id = new_id
        self._refresh_all()
        # Per ref 225:4 — newly-created clock immediately opens in the
        # Clock Editor (modal in C3, full-screen route for now).
        self._launch_clock_editor(new_id)

    def _on_duplicate_clock(self) -> None:
        if self._selected_clock_id is None:
            return
        try:
            new_id = self._db.duplicate_clock(self._selected_clock_id)
        except Exception as exc:
            log.warning(f"duplicate_clock failed: {exc}")
            return
        self._selected_clock_id = new_id
        self._refresh_all()

    def _on_delete_clock(self) -> None:
        if self._selected_clock_id is None:
            return
        box = QMessageBox(self)
        box.setWindowTitle("Delete clock?")
        box.setText("Delete this clock and all its slots + grid assignments?")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if box.exec() != QMessageBox.StandardButton.Yes:
            return
        try:
            self._db.delete_clock(self._selected_clock_id)
        except ValueError as exc:
            QMessageBox.information(self, "Cannot delete", str(exc))
            return
        except Exception as exc:
            log.warning(f"delete_clock failed: {exc}")
            return
        self._selected_clock_id = None
        self._refresh_all()

    def _on_auto_program_stub(self) -> None:
        QMessageBox.information(
            self, "Auto Program Settings",
            "Auto Program Settings — Phase F polish.\n\n"
            "Will configure separation rules, fallback categories, and "
            "global rotation behavior across all clocks.")

    def _on_settings_stub(self) -> None:
        QMessageBox.information(
            self, "Settings",
            "Settings — Phase G.\n\nGlobal application preferences.")

    # ── grid handlers ─────────────────────────────────────────────────────

    def _on_cell_clicked(self, day: int, hour: int) -> None:
        grid = self._db.get_auto_schedule_grid()
        cur_id = grid.get((day, hour))
        cur_clock = None
        if cur_id is not None:
            cur_clock = next(
                (c for c in self._clocks if int(c["id"]) == int(cur_id)), None)
        if not self._clocks:
            QMessageBox.information(
                self, "No clocks",
                "Create a clock first (use the + New Clock button or "
                "the Clock Editor).")
            return
        dlg = _AssignmentDialog(day, hour, cur_clock, self._clocks, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            if dlg.do_clear:
                self._db.clear_auto_schedule_cell(day, hour)
                log.info(f"[auto-schedule] cleared ({day}, {hour})")
            elif dlg.chosen_clock_id is not None:
                self._db.set_auto_schedule_cell(day, hour, dlg.chosen_clock_id)
                log.info(f"[auto-schedule] set ({day}, {hour}) → "
                         f"clock_id={dlg.chosen_clock_id}")
        except Exception as exc:
            log.warning(f"cell write failed: {exc}")
            QMessageBox.warning(self, "Save failed", str(exc))
            return
        self._refresh_all()

    def _on_cell_right_clicked(self, day: int, hour: int) -> None:
        # Quick clear — no confirm.
        try:
            self._db.clear_auto_schedule_cell(day, hour)
            log.info(f"[auto-schedule] right-click cleared ({day}, {hour})")
        except Exception as exc:
            log.warning(f"quick-clear failed: {exc}")
            return
        self._refresh_all()

    def _on_clear_all(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("Clear all assignments?")
        box.setText("This wipes every cell in the 24×7 grid.\n\nProceed?")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if box.exec() != QMessageBox.StandardButton.Yes:
            return
        try:
            n = self._db.clear_all_auto_schedule()
            log.info(f"[auto-schedule] clear-all removed {n} rows")
        except Exception as exc:
            log.warning(f"clear-all failed: {exc}")
            return
        self._refresh_all()
