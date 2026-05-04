"""
RadioAI Studio Pro — Campaign Date Picker Dialog
Pixel-accurate match of Figma node 101:2 (480×520, BaseDialog floor → 640×520).

Custom QPushButton calendar — chosen over QCalendarWidget because Qt's built-in
calendar fights heavy QSS skinning and can't host the side quick-select panel
without wrapping. ~250 LOC of paint code gives an exact Figma match.

Used by AddCampaignDialog for both Start Date and Expire Date pickers (mode
parameter controls header text + whether the "Never" sentinel is offered).

Selection model: every interaction (calendar click + Today / In One Month /
Never quick-selects) only SETS the selection. User must click OK to confirm.
This matches Outlook / Google Calendar / Linear conventions and lets the
user review the time component (23:59 for expire, 00:00 for start) before
commit.

Signals:
    date_selected(object)   — QDate or None
    never_selected()        — emitted when 'Never' was the OK'd choice
"""

import logging
from typing import Optional

from PyQt6.QtCore import Qt, QRectF, QDate, pyqtSignal
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QPainterPath, QFont, QCursor, QLinearGradient,
    QBrush,
)
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QHBoxLayout, QVBoxLayout, QGridLayout,
)

from ui.widgets._tokens import (
    inter, mono, rgba,
    BG_BASE, BG_CARD, BG_ELEVATED,
    TEXT_PRI, TEXT_SEC, TEXT_MUTED, TEXT_DIM,
    PURPLE, PURPLE_LIGHT, PURPLE_DARK,
    CYAN, CYAN_LIGHT, GREEN, GREEN_LIGHT, AMBER, RED, RED_LIGHT,
)
from ui.dialogs.base_dialog import BaseDialog

log = logging.getLogger("CampaignDatePickerDialog")


# ════════════════════════════════════════════════════════════════════════════
# Sub-widgets
# ════════════════════════════════════════════════════════════════════════════

class _MonthNavBar(QFrame):
    """‹ April 2026 › month navigation row."""

    prev_month = pyqtSignal()
    next_month = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(40)
        self.setStyleSheet("background: transparent;")
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0); h.setSpacing(0)

        self._prev = self._make_arrow("‹")
        self._prev.clicked.connect(self.prev_month.emit)
        h.addWidget(self._prev)

        self._title = QLabel("—")
        self._title.setFont(inter(15, QFont.Weight.Bold))
        self._title.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h.addWidget(self._title, stretch=1)

        self._next = self._make_arrow("›")
        self._next.clicked.connect(self.next_month.emit)
        h.addWidget(self._next)

    def _make_arrow(self, glyph: str) -> QPushButton:
        b = QPushButton(glyph)
        b.setFixedSize(36, 36)
        b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        b.setFont(inter(16, QFont.Weight.Bold))
        b.setStyleSheet(
            f"QPushButton {{ background: {rgba('#ffffff', 0.04)}; "
            f"color: {TEXT_SEC}; border: 1px solid {rgba('#ffffff', 0.06)}; "
            f"border-radius: 6px; }}"
            f"QPushButton:hover {{ background: {rgba(PURPLE, 0.20)}; "
            f"color: {PURPLE_LIGHT}; border-color: {rgba(PURPLE, 0.35)}; }}"
        )
        return b

    def set_month(self, qdate: QDate):
        self._title.setText(qdate.toString("MMMM yyyy"))


class _DayButton(QPushButton):
    """Single day cell in the calendar.

    Visual states (handled in paintEvent):
      • out-of-month  → very dim, no fill
      • disabled (< min_date) → dim, no hover effect, no click signal
      • today         → subtle white border ring (overlay)
      • selected      → purple filled circle
      • default       → light gray text
      • hover         → light translucent fill
    """

    day_picked = pyqtSignal(QDate)

    SIZE = 36   # circle diameter inside the cell

    def __init__(self, parent=None):
        super().__init__("", parent)
        self._date: Optional[QDate] = None
        self._in_month = False
        self._enabled  = True
        self._is_today = False
        self._selected = False
        self._hover = False
        self.setFixedSize(48, 40)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFlat(True)
        self.setStyleSheet("background: transparent; border: none;")

    def configure(self, date: QDate, in_month: bool, enabled: bool,
                  is_today: bool, selected: bool):
        self._date = date
        self._in_month = in_month
        self._enabled = enabled
        self._is_today = is_today
        self._selected = selected
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor if enabled
                               else Qt.CursorShape.ArrowCursor))
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self._enabled \
                and self._date is not None:
            self.day_picked.emit(self._date)
        super().mousePressEvent(e)

    def enterEvent(self, e):
        if self._enabled:
            self._hover = True; self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False; self.update()
        super().leaveEvent(e)

    def paintEvent(self, _e):
        if self._date is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w // 2, h // 2

        # Selected pad: filled purple circle
        if self._selected and self._enabled:
            r = self.SIZE // 2
            g = QLinearGradient(cx - r, cy - r, cx + r, cy + r)
            g.setColorAt(0.0, QColor(PURPLE_LIGHT))
            g.setColorAt(1.0, QColor(PURPLE))
            p.setBrush(QBrush(g))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(cx - r, cy - r, self.SIZE, self.SIZE)
        elif self._hover and self._enabled:
            r = self.SIZE // 2
            tint = QColor(PURPLE); tint.setAlphaF(0.18)
            p.setBrush(tint); p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(cx - r, cy - r, self.SIZE, self.SIZE)

        # Today highlight (thin white ring), only if not selected
        if self._is_today and not self._selected and self._enabled:
            r = self.SIZE // 2
            p.setBrush(Qt.BrushStyle.NoBrush)
            ring = QColor("#ffffff"); ring.setAlphaF(0.30)
            p.setPen(QPen(ring, 1))
            p.drawEllipse(cx - r, cy - r, self.SIZE, self.SIZE)

        # Number
        if not self._enabled:
            text_color = QColor(TEXT_DIM)
        elif not self._in_month:
            text_color = QColor(TEXT_DIM)
        elif self._selected:
            text_color = QColor("#ffffff")
        else:
            text_color = QColor(TEXT_PRI)
        p.setPen(text_color)
        p.setFont(inter(12, QFont.Weight.Medium))
        p.drawText(QRectF(0, 0, w, h),
                   Qt.AlignmentFlag.AlignCenter,
                   str(self._date.day()))


class _CalendarGrid(QFrame):
    """7×7 grid (1 header row + 6 week rows). Holds _DayButton cells and
    repaints them every time the displayed month or selection changes."""

    day_picked = pyqtSignal(QDate)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0); v.setSpacing(2)

        # Day-of-week header
        hdr = QFrame(); hdr.setStyleSheet("background: transparent;")
        hdr_layout = QGridLayout(hdr)
        hdr_layout.setContentsMargins(0, 0, 0, 4); hdr_layout.setSpacing(0)
        for c, name in enumerate(["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]):
            l = QLabel(name)
            l.setFont(inter(9, QFont.Weight.Bold, letter_spacing=0.6))
            l.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
            l.setAlignment(Qt.AlignmentFlag.AlignCenter)
            l.setFixedHeight(20)
            hdr_layout.addWidget(l, 0, c)
        v.addWidget(hdr)

        # 6×7 grid of day buttons
        body = QFrame(); body.setStyleSheet("background: transparent;")
        self._grid_layout = QGridLayout(body)
        self._grid_layout.setContentsMargins(0, 0, 0, 0); self._grid_layout.setSpacing(2)
        self._buttons: list[_DayButton] = []
        for r in range(6):
            for c in range(7):
                btn = _DayButton()
                btn.day_picked.connect(self.day_picked.emit)
                self._grid_layout.addWidget(btn, r, c)
                self._buttons.append(btn)
        v.addWidget(body)

    def set_month(self, view_month: QDate, selected: Optional[QDate],
                  min_date: Optional[QDate]):
        """Repopulate the 42 cells based on the displayed month + selection."""
        # Find the first cell — Monday on/before the 1st of view_month
        first_of_month = QDate(view_month.year(), view_month.month(), 1)
        # Qt's dayOfWeek: Mon=1..Sun=7. We want Monday-start grids.
        offset = first_of_month.dayOfWeek() - 1
        start = first_of_month.addDays(-offset)

        today = QDate.currentDate()
        for i, btn in enumerate(self._buttons):
            d = start.addDays(i)
            in_month = (d.month() == view_month.month()
                        and d.year() == view_month.year())
            enabled = True
            if min_date is not None and d < min_date:
                enabled = False
            is_today = (d == today)
            is_selected = (selected is not None and d == selected)
            btn.configure(d, in_month, enabled, is_today, is_selected)


class _LeastDateBanner(QFrame):
    """Info strip showing the minimum allowed date (caller-supplied)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._text = ""
        self.setFixedHeight(34)
        self.setStyleSheet(
            f"QFrame {{ background: {BG_ELEVATED}; "
            f"border: 1px solid {rgba('#ffffff', 0.04)}; "
            f"border-radius: 6px; }}"
        )

    def set_date(self, qdate: Optional[QDate]):
        if qdate is None:
            self._text = ""
        else:
            self._text = f"Least Date: {qdate.toString('dddd, d MMMM yyyy')}  12:00 AM"
        self.update()

    def paintEvent(self, _e):
        super().paintEvent(_e)
        if not self._text:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QColor(TEXT_SEC))
        p.setFont(inter(10, QFont.Weight.Medium))
        p.drawText(QRectF(14, 0, self.width() - 28, self.height()),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._text)


class _QuickSelectButton(QPushButton):
    """Side-panel quick-select button (Today / In One Month / Never)."""

    def __init__(self, label: str, parent=None):
        super().__init__("", parent)
        self._label = label
        self._selected = False
        self._hover = False
        self._disabled = False
        self.setFixedSize(170, 44)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFlat(True)
        self.setStyleSheet("background: transparent; border: none;")

    def set_selected(self, sel: bool):
        self._selected = sel
        self.update()

    def setDisabled(self, disabled: bool):
        super().setDisabled(disabled)
        self._disabled = bool(disabled)
        self.setCursor(QCursor(
            Qt.CursorShape.ArrowCursor if disabled
            else Qt.CursorShape.PointingHandCursor))
        self.update()

    def enterEvent(self, e):
        if not self._disabled:
            self._hover = True; self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False; self.update()
        super().leaveEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0, 0, self.width(), self.height())
        path = QPainterPath(); path.addRoundedRect(rect, 6, 6)
        p.setClipPath(path)

        if self._disabled:
            # Visibly grayed-out — darker bg, dim text, no purple accents
            p.fillRect(rect, QColor(255, 255, 255, 4))
        elif self._selected:
            tint = QColor(PURPLE); tint.setAlphaF(0.22)
            p.fillRect(rect, tint)
        elif self._hover:
            p.fillRect(rect, QColor(255, 255, 255, 14))
        else:
            p.fillRect(rect, QColor(BG_CARD))
        p.setClipping(False)

        if self._disabled:
            bc = QColor(255, 255, 255, 12)
        elif self._selected:
            bc = QColor(PURPLE); bc.setAlphaF(0.45)
        else:
            bc = QColor(255, 255, 255, 14)
        p.setPen(QPen(bc, 1)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 6, 6)

        if self._disabled:
            text_color = QColor(TEXT_DIM)
        elif self._selected:
            text_color = QColor(PURPLE_LIGHT)
        else:
            text_color = QColor(TEXT_PRI)
        p.setPen(text_color)
        p.setFont(inter(12, QFont.Weight.DemiBold))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._label)


class _SelectedDateBar(QFrame):
    """Bottom strip — 'Selected Date: Monday, April 27, 2026  23:59'."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._text = "Selected Date: —"
        self.setFixedHeight(32)
        self.setStyleSheet(
            f"QFrame {{ background: {BG_ELEVATED}; "
            f"border: 1px solid {rgba('#ffffff', 0.04)}; "
            f"border-radius: 6px; }}"
        )

    def set_text(self, txt: str):
        self._text = txt or "Selected Date: —"
        self.update()

    def paintEvent(self, _e):
        super().paintEvent(_e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QColor(TEXT_PRI))
        p.setFont(inter(10, QFont.Weight.Medium))
        p.drawText(QRectF(14, 0, self.width() - 28, self.height()),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._text)


# ════════════════════════════════════════════════════════════════════════════
# Main dialog
# ════════════════════════════════════════════════════════════════════════════

class CampaignDatePickerDialog(BaseDialog):

    # Caller wires whichever signal makes sense for the input it's filling.
    # Both fire on OK; only one of them at a time.
    date_selected  = pyqtSignal(object)   # QDate
    never_selected = pyqtSignal()

    HEADER_H = 56
    FOOTER_H = 56

    def __init__(self, mode: str = "expire",
                 min_date: Optional[QDate] = None,
                 initial: Optional[QDate] = None,
                 parent=None):
        self._mode = mode if mode in ("start", "expire") else "expire"
        self._min_date = min_date
        # Default selection = initial → today → min_date (if today < min_date)
        today = QDate.currentDate()
        if initial is not None:
            self._selected: Optional[QDate] = QDate(initial)
        elif min_date is not None and today < min_date:
            self._selected = QDate(min_date)
        else:
            self._selected = QDate(today)
        self._is_never = False  # True when "Never" quick-select is chosen
        self._view_month = QDate(self._selected)

        # Refs
        self._nav: Optional[_MonthNavBar] = None
        self._grid: Optional[_CalendarGrid] = None
        self._least_banner: Optional[_LeastDateBanner] = None
        self._selected_bar: Optional[_SelectedDateBar] = None
        self._quick_today: Optional[_QuickSelectButton] = None
        self._quick_month: Optional[_QuickSelectButton] = None
        self._quick_never: Optional[_QuickSelectButton] = None

        # 580px tall — height calc: header 56 + footer 56 + body
        # (banner 34 + nav 40 + cal 240 + bar 32 + margins/spacing ~50)
        # = 508 ≈ 580 with breathing room.
        super().__init__(target_size=(640, 580), parent=parent)
        self._refresh()

    # ── Header ────────────────────────────────────────────────────────────

    def _build_header(self) -> QWidget:
        f = QFrame()
        f.setStyleSheet(
            f"QFrame {{ background: #0d0f1e; "
            f"border-bottom: 1px solid {rgba('#ffffff', 0.06)}; }}"
        )
        h = QHBoxLayout(f)
        h.setContentsMargins(18, 10, 12, 10); h.setSpacing(10)

        title_box = QWidget(); title_box.setStyleSheet("background: transparent;")
        tv = QVBoxLayout(title_box)
        tv.setContentsMargins(0, 0, 0, 0); tv.setSpacing(2)

        title = QLabel(
            "SELECT START DATE" if self._mode == "start"
            else "SELECT EXPIRE DATE"
        )
        title.setFont(inter(14, QFont.Weight.Black, letter_spacing=0.5))
        title.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        sub = QLabel(
            "Choose campaign start date" if self._mode == "start"
            else "Choose campaign end date"
        )
        sub.setFont(inter(9))
        sub.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        tv.addWidget(title); tv.addWidget(sub)
        h.addWidget(title_box)
        h.addStretch()

        x = QPushButton("✕")
        x.setFixedSize(28, 28)
        x.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        x.setFont(inter(13, QFont.Weight.Bold))
        x.setStyleSheet(
            f"QPushButton {{ background: #1c1f38; color: {TEXT_SEC}; "
            f"border: none; border-radius: 6px; }}"
            f"QPushButton:hover {{ background: {rgba(RED, 0.20)}; "
            f"color: {RED_LIGHT}; }}"
        )
        x.clicked.connect(self.reject)
        h.addWidget(x)
        return f

    # ── Content ───────────────────────────────────────────────────────────

    def _build_content(self) -> QWidget:
        c = QFrame(); c.setStyleSheet("background: transparent;")
        v = QVBoxLayout(c)
        v.setContentsMargins(16, 12, 16, 12); v.setSpacing(10)

        # Least Date banner
        self._least_banner = _LeastDateBanner()
        self._least_banner.set_date(self._min_date)
        v.addWidget(self._least_banner)

        # Main HBox: calendar + quick selects
        body = QHBoxLayout(); body.setContentsMargins(0, 4, 0, 0); body.setSpacing(16)

        # Left column — month nav + calendar
        cal_col = QFrame(); cal_col.setStyleSheet("background: transparent;")
        cv = QVBoxLayout(cal_col); cv.setContentsMargins(0, 0, 0, 0); cv.setSpacing(4)

        self._nav = _MonthNavBar()
        self._nav.prev_month.connect(self._prev_month)
        self._nav.next_month.connect(self._next_month)
        cv.addWidget(self._nav)

        self._grid = _CalendarGrid()
        self._grid.day_picked.connect(self._on_day_picked)
        cv.addWidget(self._grid)
        cv.addStretch()

        body.addWidget(cal_col, stretch=1)

        # Right column — quick selects
        qs_col = QFrame(); qs_col.setStyleSheet("background: transparent;")
        qsv = QVBoxLayout(qs_col)
        qsv.setContentsMargins(0, 8, 0, 0); qsv.setSpacing(8)

        self._quick_today = _QuickSelectButton("Today")
        self._quick_today.clicked.connect(self._pick_today)
        qsv.addWidget(self._quick_today)

        self._quick_month = _QuickSelectButton("In One Month")
        self._quick_month.clicked.connect(self._pick_in_one_month)
        qsv.addWidget(self._quick_month)

        self._quick_never = _QuickSelectButton("Never")
        self._quick_never.clicked.connect(self._pick_never)
        if self._mode == "start":
            # Start dates can't be "Never" — disable (paintEvent renders dim)
            self._quick_never.setDisabled(True)
        qsv.addWidget(self._quick_never)
        qsv.addStretch()

        body.addWidget(qs_col, stretch=0)
        v.addLayout(body)

        # Selected Date bar
        self._selected_bar = _SelectedDateBar()
        v.addWidget(self._selected_bar)

        v.addStretch()
        return c

    # ── Footer ────────────────────────────────────────────────────────────

    def _build_footer(self) -> QWidget:
        f = QFrame()
        f.setStyleSheet(
            f"QFrame {{ background: #0d0f1e; "
            f"border-top: 1px solid {rgba('#ffffff', 0.06)}; }}"
        )
        h = QHBoxLayout(f)
        h.setContentsMargins(20, 10, 16, 10); h.setSpacing(8)
        h.addStretch()

        cancel = QPushButton("Cancel")
        cancel.setFixedHeight(34); cancel.setMinimumWidth(96)
        cancel.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        cancel.setFont(inter(11, QFont.Weight.Medium))
        cancel.setStyleSheet(
            f"QPushButton {{ background: #1c1f38; color: {TEXT_SEC}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; "
            f"border-radius: 7px; padding: 0 18px; }}"
            f"QPushButton:hover {{ background: #252848; color: {TEXT_PRI}; }}"
        )
        cancel.clicked.connect(self.reject)
        h.addWidget(cancel)

        ok = QPushButton("✓  OK")
        ok.setFixedHeight(34); ok.setMinimumWidth(108)
        ok.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        ok.setFont(inter(11, QFont.Weight.DemiBold))
        ok.setStyleSheet(
            f"QPushButton {{ background: qlineargradient("
            f"x1:0,y1:0,x2:0,y2:1, stop:0 {PURPLE_LIGHT}, "
            f"stop:0.5 {PURPLE}, stop:1 #7c3aed); "
            f"color: white; border: none; border-radius: 7px; "
            f"padding: 0 22px; }}"
            f"QPushButton:hover {{ background: qlineargradient("
            f"x1:0,y1:0,x2:0,y2:1, stop:0 #c4b5fd, stop:1 {PURPLE}); }}"
        )
        ok.clicked.connect(self._on_ok)
        h.addWidget(ok)
        return f

    # ── Selection state ───────────────────────────────────────────────────

    def _refresh(self):
        """Repaint the calendar + selected-date bar from current state."""
        if self._grid:
            self._grid.set_month(
                self._view_month,
                None if self._is_never else self._selected,
                self._min_date,
            )
        if self._nav:
            self._nav.set_month(self._view_month)
        if self._selected_bar:
            self._selected_bar.set_text(self._format_selection())
        # Quick-select highlight reflects current state
        today = QDate.currentDate()
        in_one = today.addMonths(1)
        if self._quick_today:
            self._quick_today.set_selected(
                not self._is_never and self._selected == today)
        if self._quick_month:
            self._quick_month.set_selected(
                not self._is_never and self._selected == in_one)
        if self._quick_never:
            self._quick_never.set_selected(self._is_never)

    def _format_selection(self) -> str:
        if self._is_never:
            return "Selected Date: Never"
        if self._selected is None:
            return "Selected Date: —"
        time_part = "23:59" if self._mode == "expire" else "00:00"
        return (f"Selected Date: "
                f"{self._selected.toString('dddd, MMMM d, yyyy')}  "
                f"{time_part}")

    # ── Handlers ──────────────────────────────────────────────────────────

    def _prev_month(self):
        self._view_month = self._view_month.addMonths(-1)
        self._refresh()

    def _next_month(self):
        self._view_month = self._view_month.addMonths(1)
        self._refresh()

    def _on_day_picked(self, qdate: QDate):
        self._is_never = False
        self._selected = QDate(qdate)
        # If the picked day is in a different month, switch the view
        if (qdate.month() != self._view_month.month()
                or qdate.year() != self._view_month.year()):
            self._view_month = QDate(qdate.year(), qdate.month(), 1)
        self._refresh()

    def _pick_today(self):
        today = QDate.currentDate()
        self._is_never = False
        self._selected = today
        self._view_month = QDate(today.year(), today.month(), 1)
        self._refresh()

    def _pick_in_one_month(self):
        target = QDate.currentDate().addMonths(1)
        self._is_never = False
        self._selected = target
        self._view_month = QDate(target.year(), target.month(), 1)
        self._refresh()

    def _pick_never(self):
        if self._mode == "start":
            return
        self._is_never = True
        self._refresh()

    def _on_ok(self):
        if self._is_never:
            log.info("[date-picker] OK — Never")
            self.never_selected.emit()
        else:
            log.info(f"[date-picker] OK — {self._selected.toString('yyyy-MM-dd')}")
            self.date_selected.emit(QDate(self._selected))
        self.accept()
