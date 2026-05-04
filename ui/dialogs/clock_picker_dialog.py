"""
RadioAI Studio Pro — Clock Picker Dialog (Phase F2.2).

Modal dialog for selecting which clock to edit in the Clock Editor.
Shows all clocks in the DB with name + slot count + time range +
day mask. Double-click or Open button to confirm selection.

Per F2.1 Q3 recommendation: modal dialog rather than inline dropdown
because clocks have rich metadata (slot count, time range, day mask)
that's hard to fit in a dropdown line.
"""

from __future__ import annotations

import logging
from typing import Optional

from PyQt6.QtCore import Qt, QRect, QRectF, pyqtSignal
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QFont, QCursor, QPainterPath,
)
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QLineEdit,
    QHBoxLayout, QVBoxLayout, QScrollArea, QSizePolicy,
)

from ui.widgets._tokens import (
    inter, mono, rgba,
    BG_BASE, BG_PANEL, BG_CARD, BG_DARK, BG_ELEVATED,
    TEXT_PRI, TEXT_SEC, TEXT_MUTED, TEXT_DIM,
    CYAN, CYAN_LIGHT, GREEN, GREEN_LIGHT, AMBER,
    PURPLE, PURPLE_LIGHT, RED, RED_LIGHT,
)
from ui.dialogs.base_dialog import BaseDialog

log = logging.getLogger("ClockPickerDialog")


# Day mask bits → labels (Mon=bit0..Sun=bit6 — matches CLAUDE.md convention)
_DAY_BITS = [(1 << i, name) for i, name in enumerate(
    ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])]


def _fmt_day_mask(mask: int) -> str:
    """127 → 'All days'; 31 → 'Mon-Fri'; else comma list of active days."""
    m = int(mask or 0)
    if m == 127:
        return "All days"
    if m == 31:
        return "Mon-Fri"
    if m == 96:
        return "Sat-Sun"
    days = [name for bit, name in _DAY_BITS if m & bit]
    return ", ".join(days) if days else "—"


class _ClockRow(QFrame):
    """One row in the picker list (shows name + slot count + time + days)."""

    ROW_H = 56

    clicked         = pyqtSignal(int)   # clock_id
    double_clicked  = pyqtSignal(int)   # clock_id

    def __init__(self, clock: dict, idx: int, parent=None):
        super().__init__(parent)
        self._clock = clock
        self._idx = idx
        self._selected = False
        self.setFixedHeight(self.ROW_H)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

    def set_selected(self, sel: bool) -> None:
        if self._selected == sel:
            return
        self._selected = sel
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(int(self._clock.get("id", 0)))
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit(int(self._clock.get("id", 0)))
        super().mouseDoubleClickEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        rect = QRectF(0, 0, w, h)

        # Background
        if self._selected:
            tint = QColor(CYAN); tint.setAlphaF(0.14)
            p.fillRect(rect, tint)
            p.fillRect(QRectF(0, 0, 3, h), QColor(CYAN))
        else:
            zebra = "#0d0f1c" if self._idx % 2 else "#0a0c18"
            p.fillRect(rect, QColor(zebra))

        # Name (large)
        name = self._clock.get("name") or "(unnamed)"
        p.setPen(QColor(TEXT_PRI if self._selected else TEXT_SEC))
        p.setFont(inter(12, QFont.Weight.Bold))
        fm = p.fontMetrics()
        elided = fm.elidedText(name, Qt.TextElideMode.ElideRight, w - 280)
        p.drawText(QRectF(14, 4, w - 280, 22),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   elided)

        # Sub-line: slot count + day mask
        slot_count = int(self._clock.get("slot_count") or 0)
        day_label = _fmt_day_mask(self._clock.get("day_mask", 127))
        sub = f"{slot_count} slot{'s' if slot_count != 1 else ''}  ·  {day_label}"
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(inter(9))
        p.drawText(QRectF(14, 28, w - 280, 18),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   sub)

        # Time range (right side, mono)
        t_start = self._clock.get("time_start") or ""
        t_end = self._clock.get("time_end") or ""
        if t_start and t_end:
            time_text = f"{t_start} → {t_end}"
        else:
            time_text = "(no time)"
        p.setPen(QColor(CYAN_LIGHT if (t_start and t_end) else TEXT_DIM))
        p.setFont(mono(11, bold=True))
        p.drawText(QRectF(w - 200, 0, 186, h),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   time_text)

        # Hairline separator
        p.setPen(QPen(QColor(255, 255, 255, 10), 1))
        p.drawLine(0, h - 1, w, h - 1)


class ClockPickerDialog(BaseDialog):
    """Pick an existing clock to edit. Emits clock_picked(int) on
    confirmation. Cancel closes without emit."""

    clock_picked = pyqtSignal(int)

    def __init__(self, db, current_clock_id: Optional[int] = None,
                 parent=None):
        self._db = db
        self._current_clock_id = current_clock_id
        self._clocks: list[dict] = []
        self._row_widgets: list[_ClockRow] = []
        self._selected_id: Optional[int] = current_clock_id
        self._search_text: str = ""
        # Refs assigned in _build_*
        self._list_layout: Optional[QVBoxLayout] = None
        self._open_btn: Optional[QPushButton] = None

        super().__init__(target_size=(640, 560), parent=parent)
        self._reload_clocks()

    # ── Header ────────────────────────────────────────────────────────────

    def _build_header(self) -> QWidget:
        f = QFrame()
        f.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border-bottom: 1px solid {rgba('#ffffff', 0.06)}; }}"
        )
        h = QHBoxLayout(f)
        h.setContentsMargins(20, 12, 12, 12); h.setSpacing(10)

        title_box = QWidget(); title_box.setStyleSheet("background: transparent;")
        tv = QVBoxLayout(title_box); tv.setContentsMargins(0, 0, 0, 0); tv.setSpacing(2)
        title = QLabel("OPEN CLOCK")
        title.setFont(inter(13, QFont.Weight.Black, letter_spacing=0.5))
        title.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        sub = QLabel("Select a broadcast clock template to edit")
        sub.setFont(inter(9))
        sub.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        tv.addWidget(title); tv.addWidget(sub)
        h.addWidget(title_box); h.addStretch()

        x = QPushButton("✕")
        x.setFixedSize(26, 26)
        x.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        x.setFont(inter(12, QFont.Weight.Bold))
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
        v.setContentsMargins(14, 12, 14, 12); v.setSpacing(8)

        # Search input
        search = QLineEdit()
        search.setPlaceholderText("🔍  Search clocks by name…")
        search.setFixedHeight(32)
        search.setFont(inter(10))
        search.setStyleSheet(
            f"QLineEdit {{ background: #0e1020; color: {TEXT_PRI}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; border-radius: 5px; "
            f"padding: 0 12px; "
            f"selection-background-color: {rgba(CYAN, 0.25)}; }}"
            f"QLineEdit:focus {{ border: 1px solid {rgba(CYAN, 0.50)}; }}"
        )
        search.textChanged.connect(self._on_search_changed)
        v.addWidget(search)

        # Scrollable list
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            f"QScrollBar:vertical {{ background: transparent; width: 6px; }}"
            f"QScrollBar::handle:vertical {{ background: {rgba(PURPLE, 0.45)}; "
            f"border-radius: 3px; min-height: 24px; }}"
            "QScrollBar::add-line, QScrollBar::sub-line { height: 0; }"
        )
        body = QFrame(); body.setStyleSheet(
            f"QFrame {{ background: {BG_DARK}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; "
            f"border-radius: 6px; }}"
        )
        self._list_layout = QVBoxLayout(body)
        self._list_layout.setContentsMargins(0, 0, 0, 0); self._list_layout.setSpacing(0)
        self._list_layout.addStretch()
        scroll.setWidget(body)
        v.addWidget(scroll, stretch=1)

        return c

    # ── Footer ────────────────────────────────────────────────────────────

    def _build_footer(self) -> QWidget:
        f = QFrame()
        f.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border-top: 1px solid {rgba('#ffffff', 0.06)}; }}"
        )
        h = QHBoxLayout(f)
        h.setContentsMargins(20, 12, 16, 12); h.setSpacing(8)

        self._summary_lbl = QLabel("(no clocks)")
        self._summary_lbl.setFont(inter(9))
        self._summary_lbl.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        h.addWidget(self._summary_lbl); h.addStretch()

        cancel = QPushButton("Cancel")
        cancel.setFixedHeight(30); cancel.setMinimumWidth(80)
        cancel.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        cancel.setFont(inter(10, QFont.Weight.Medium))
        cancel.setStyleSheet(
            f"QPushButton {{ background: #1c1f38; color: {TEXT_SEC}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; "
            f"border-radius: 6px; padding: 0 16px; }}"
            f"QPushButton:hover {{ background: #252848; color: {TEXT_PRI}; }}"
        )
        cancel.clicked.connect(self.reject)
        h.addWidget(cancel)

        self._open_btn = QPushButton("Open  →")
        self._open_btn.setFixedHeight(30); self._open_btn.setMinimumWidth(96)
        self._open_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._open_btn.setFont(inter(10, QFont.Weight.DemiBold))
        self._open_btn.setStyleSheet(
            f"QPushButton {{ background: qlineargradient("
            f"x1:0,y1:0,x2:0,y2:1, stop:0 {CYAN_LIGHT}, stop:1 {CYAN}); "
            f"color: white; border: none; border-radius: 6px; padding: 0 18px; }}"
            f"QPushButton:hover {{ background: {CYAN}; }}"
            f"QPushButton:disabled {{ background: #252848; color: {TEXT_MUTED}; }}"
        )
        self._open_btn.clicked.connect(self._on_open)
        self._open_btn.setEnabled(False)
        h.addWidget(self._open_btn)
        return f

    # ── Data + filtering ──────────────────────────────────────────────────

    def _reload_clocks(self) -> None:
        try:
            self._clocks = [dict(r) for r in self._db.get_all_clocks()]
        except Exception as exc:
            log.warning(f"clock list load failed: {exc}")
            self._clocks = []
        self._render_list()

    def _on_search_changed(self, text: str) -> None:
        self._search_text = (text or "").strip().lower()
        self._render_list()

    def _render_list(self) -> None:
        if self._list_layout is None:
            return
        # Clear existing rows
        for r in self._row_widgets:
            r.setParent(None); r.deleteLater()
        self._row_widgets.clear()
        # Filter
        if self._search_text:
            visible = [c for c in self._clocks
                       if self._search_text in (c.get("name") or "").lower()]
        else:
            visible = list(self._clocks)
        # Insert before the stretch
        stretch_idx = self._list_layout.count() - 1
        for i, clk in enumerate(visible):
            row = _ClockRow(clk, i)
            row.set_selected(int(clk.get("id") or 0) == self._selected_id)
            row.clicked.connect(self._on_row_clicked)
            row.double_clicked.connect(self._on_row_double_clicked)
            self._list_layout.insertWidget(stretch_idx + i, row)
            self._row_widgets.append(row)
        # Update footer summary + Open enabled state
        self._summary_lbl.setText(
            f"{len(visible)} of {len(self._clocks)} clocks shown")
        if self._open_btn is not None:
            self._open_btn.setEnabled(self._selected_id is not None)

    # ── Selection + confirm ──────────────────────────────────────────────

    def _on_row_clicked(self, clock_id: int) -> None:
        self._selected_id = int(clock_id)
        for row in self._row_widgets:
            row.set_selected(int(row._clock.get("id") or 0) == self._selected_id)
        if self._open_btn is not None:
            self._open_btn.setEnabled(True)

    def _on_row_double_clicked(self, clock_id: int) -> None:
        self._selected_id = int(clock_id)
        self._on_open()

    def _on_open(self) -> None:
        if self._selected_id is None:
            return
        self.clock_picked.emit(int(self._selected_id))
        self.accept()
