"""
RadioAI Studio Pro — Spot Programming Dialog
Pixel-accurate match of Figma node 102:2 (860×620, BaseDialog floor → 860×620).

Custom-painted 144×7 = 1008-cell grid for scheduling per-day break times
across the week. Performance-critical — never instantiate one widget per
cell; the entire grid renders in a single paintEvent.

Two operating modes:
  • Persisted mode (campaign_id != None) — Apply Schedule writes directly to
    campaign_schedule via db.update_break_schedule(). Used from the Library
    "✎ Edit Breaks" sidebar button on a saved campaign.
  • Staged mode (campaign_id is None) — Apply emits schedule_staged(list)
    so the AddCampaignDialog can hold the schedule in memory and persist it
    after add_campaign() returns the new id.

Signals:
    schedule_saved(int, list)   — campaign_id, schedule rows  (persisted mode)
    schedule_staged(list)        — schedule rows               (staged mode)

Schedule row shape (both signals):
    {
        "day_of_week": int 0..6,    # 0=Mon … 6=Sun
        "break_time":  "HH:MM",     # 00:00 … 23:50, every 10 min
        "slot_order":  int,
        "priority":    "High" | "Medium" | "Low",
    }

═════════════════════════════════════════════════════════════════════════════
PERFORMANCE NOTES — DO NOT VIOLATE
═════════════════════════════════════════════════════════════════════════════

A 4064-px-tall fixed-size widget caused a layout-storm freeze during initial
construction (incident 2026-05-04). The fixes below are load-bearing — each
addresses a distinct performance cost. Don't change them without re-testing.

  1. SINGLE-SOURCE SCROLLING — Outer scrolling is BaseDialog's QScrollArea.
     Do NOT wrap the grid in a second nested QScrollArea. Nested
     QScrollAreas with setWidgetResizable=True on the outer + a fixed-size
     grandchild trigger Qt size-negotiation loops that look like a freeze.

  2. paintEvent CLIPS TO event.rect() — Always compute first_visible_slot
     and last_visible_slot from event.rect().y()/.bottom() before iterating
     cells. Painting all 1008 cells on every event is ~5000 primitives;
     painting only the ~30 visible cells is ~150 primitives.

  3. mouseMoveEvent USES BOUNDED self.update(rect) — Hover-cell changes
     repaint only the affected cell rects (old hover + new hover), never
     bare self.update(). Prevents 60fps full-widget repaint storm when
     mouse traverses the grid.

  4. NO setFixedSize ON HEIGHTS > 2000px — the height has to be fixed
     for scrolling to work, but width should follow the parent layout
     (setFixedHeight + setMinimumWidth, not setFixedSize). Lets the grid
     adapt to varying dialog widths without breaking horizontally.
═════════════════════════════════════════════════════════════════════════════
"""

import logging
from typing import Optional

from PyQt6.QtCore import Qt, QRect, QRectF, pyqtSignal, QPoint
from core import dialogs
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QPainterPath, QFont, QCursor, QLinearGradient,
    QBrush, QAction,
)
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QComboBox, QHBoxLayout, QVBoxLayout,
    QScrollArea, QMessageBox, QMenu, QCheckBox, QSizePolicy, QSpinBox,
)

from ui.widgets._tokens import (
    inter, mono, rgba,
    BG_BASE, BG_CARD, BG_ELEVATED,
    TEXT_PRI, TEXT_SEC, TEXT_MUTED, TEXT_DIM,
    PURPLE, PURPLE_LIGHT, PURPLE_DARK,
    CYAN, CYAN_LIGHT, GREEN, GREEN_LIGHT, AMBER, AMBER_LIGHT,
    RED, RED_LIGHT, PINK, PINK_LIGHT,
)
from ui.dialogs.base_dialog import BaseDialog

log = logging.getLogger("SpotProgrammingDialog")


# ════════════════════════════════════════════════════════════════════════════
# Constants
# ════════════════════════════════════════════════════════════════════════════

DAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
PRIORITY_OPTIONS = ["High", "Medium", "Low"]

PRIORITY_COLORS = {
    "High":   "#f43f5e",   # red
    "Medium": "#f59e0b",   # amber
    "Low":    "#06b6d4",   # cyan
}


# Hard-coded preset templates: name → list[(day_index, "HH:MM")]
# day_index: 0=Mon … 6=Sun. Use range(0,5) for Mon-Fri, range(0,7) for daily.
PRESETS: dict[str, list[tuple[int, str]]] = {
    "Morning Drive": [
        (d, t) for d in range(0, 5) for t in ("06:00", "07:30", "09:00")
    ],
    "Lunch Hour": [
        (d, t) for d in range(0, 7) for t in ("12:00", "12:20",
                                                "12:40", "13:00")
    ],
    "Drive Time": [
        (d, t) for d in range(0, 5) for t in ("17:00", "17:30",
                                                "18:00", "18:30")
    ],
    "Late Night": [
        (d, t) for d in range(0, 7) for t in ("22:00", "23:00")
    ],
}


# Grid geometry — 144 rows × 7 days
# NOTE: column WIDTH is dynamic (computed from current widget width by
# _day_col_w()) so the grid adapts to the dialog's actual width. Only the
# time column, header height and cell height are fixed.
TIME_COL_W = 60
HEADER_H   = 32
CELL_H     = 28
GRID_H     = HEADER_H + 144 * CELL_H         # 4064 — total scrollable height


def _slot_to_time(slot: int) -> str:
    """slot 0..143 → 'HH:MM' every 10 min."""
    h, m = divmod(slot, 6)
    return f"{h:02d}:{m * 10:02d}"


def _time_to_slot(text: str) -> Optional[int]:
    try:
        h, m = text.split(":")
        return int(h) * 6 + int(m) // 10
    except (ValueError, AttributeError):
        return None


# ════════════════════════════════════════════════════════════════════════════
# Header chrome
# ════════════════════════════════════════════════════════════════════════════

class _CalendarIcon(QWidget):
    """36×36 orange-tinted calendar icon for the dialog header."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(36, 36)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0, 0, 36, 36)
        path = QPainterPath(); path.addRoundedRect(rect, 8, 8)
        p.setClipPath(path)
        bg = QColor(AMBER); bg.setAlphaF(0.20)
        p.fillRect(rect, bg)
        p.setClipping(False)
        bc = QColor(AMBER); bc.setAlphaF(0.50)
        p.setPen(QPen(bc, 1)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 8, 8)
        # Calendar body — top bar + grid hint
        p.setPen(QColor(AMBER_LIGHT))
        p.setBrush(QColor(AMBER_LIGHT))
        # Top bar
        p.drawRect(QRectF(8, 12, 20, 3))
        # Grid dots (3×3)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(AMBER_LIGHT), 1))
        for r in range(3):
            for c in range(3):
                p.drawRect(QRectF(8 + c * 7, 18 + r * 5, 4, 3))


# ════════════════════════════════════════════════════════════════════════════
# Action bar buttons
# ════════════════════════════════════════════════════════════════════════════

class _ActionButton(QPushButton):
    """Action-bar button with rounded rect, tinted bg, colored border + label.
    `prominent=True` → solid filled (used for + Add and − Remove)."""

    def __init__(self, label: str, color: str, prominent: bool = False,
                 parent=None):
        super().__init__("", parent)
        self._label = label
        self._color = QColor(color)
        self._prominent = prominent
        self._hover = False
        self.setFixedHeight(34)
        self.setMinimumWidth(38)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFont(inter(11, QFont.Weight.DemiBold))
        self.setFlat(True)
        self.setStyleSheet("background: transparent; border: none;")
        # Width fits label
        from PyQt6.QtGui import QFontMetrics
        fm = QFontMetrics(self.font())
        self.setMinimumWidth(max(38, fm.horizontalAdvance(label) + 24))

    def enterEvent(self, e): self._hover = True; self.update(); super().enterEvent(e)
    def leaveEvent(self, e): self._hover = False; self.update(); super().leaveEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0, 0, self.width(), self.height())
        path = QPainterPath(); path.addRoundedRect(rect, 7, 7)
        p.setClipPath(path)

        if self._prominent:
            # Solid fill (e.g., +Add green / −Remove red)
            base = QColor(self._color)
            top = QColor(self._color); top.setHsl(
                self._color.hue(), self._color.saturation(),
                min(255, self._color.lightness() + 20), 255
            )
            g = QLinearGradient(0, 0, 0, self.height())
            g.setColorAt(0.0, top); g.setColorAt(1.0, base)
            p.fillRect(rect, QBrush(g))
        else:
            tint = QColor(self._color)
            tint.setAlphaF(0.20 if self._hover else 0.12)
            p.fillRect(rect, tint)
        p.setClipping(False)

        # Border
        bc = QColor(self._color); bc.setAlphaF(
            0.60 if self._prominent else 0.40)
        p.setPen(QPen(bc, 1)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 7, 7)

        # Label
        p.setPen(QColor("#ffffff" if self._prominent else self._color))
        p.setFont(self.font())
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._label)


# ════════════════════════════════════════════════════════════════════════════
# Left sidebar widgets
# ════════════════════════════════════════════════════════════════════════════

class _SpotsCountDisplay(QFrame):
    """'Total Spots Count' big-number display (orange)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._count = 0
        self.setFixedSize(170, 56)
        self.setStyleSheet(
            f"QFrame {{ background: {BG_CARD}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; "
            f"border-radius: 6px; }}"
        )

    def set_count(self, n: int):
        self._count = int(n)
        self.update()

    def paintEvent(self, _e):
        super().paintEvent(_e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QColor(AMBER_LIGHT))
        p.setFont(inter(28, QFont.Weight.Black))
        p.drawText(QRectF(0, 0, self.width(), self.height()),
                   Qt.AlignmentFlag.AlignCenter, str(self._count))


def _sidebar_label(text: str) -> QLabel:
    l = QLabel(text)
    l.setFont(inter(9, QFont.Weight.Medium))
    l.setStyleSheet(f"color: {TEXT_SEC}; background: transparent;")
    l.setFixedHeight(14)
    return l


def _sidebar_combo(items: list, default: str = "") -> QComboBox:
    c = QComboBox()
    c.addItems(items)
    if default and default in items:
        c.setCurrentText(default)
    c.setFixedHeight(30)
    c.setFont(inter(10))
    c.setStyleSheet(
        f"QComboBox {{ background: {BG_CARD}; color: {TEXT_PRI}; "
        f"border: 1px solid {rgba('#ffffff', 0.06)}; border-radius: 5px; "
        f"padding: 0 22px 0 10px; }}"
        f"QComboBox:focus {{ border-color: {CYAN}; }}"
        f"QComboBox::drop-down {{ border: none; width: 18px; }}"
        f"QComboBox::down-arrow {{ image: none; width: 0; height: 0; "
        f"border-left: 4px solid transparent; "
        f"border-right: 4px solid transparent; "
        f"border-top: 5px solid {TEXT_MUTED}; margin-right: 7px; }}"
        f"QComboBox QAbstractItemView {{ background: {BG_CARD}; "
        f"color: {TEXT_PRI}; "
        f"border: 1px solid {rgba('#ffffff', 0.06)}; border-radius: 5px; "
        f"selection-background-color: {rgba(CYAN, 0.20)}; "
        f"selection-color: {CYAN_LIGHT}; outline: none; padding: 4px; }}"
    )
    return c


# ════════════════════════════════════════════════════════════════════════════
# THE GRID — single-widget custom paint
# ════════════════════════════════════════════════════════════════════════════

class _BreakScheduleGrid(QWidget):
    """1008-cell scheduling grid. Single QWidget, single paintEvent.

    Storage:
        _breaks: dict[(day, slot)] → {"priority": str}    — scheduled cells
        _selected: set[(day, slot)]                       — drag-selected cells

    Painted layers (back to front):
        1. Header strip (TIME | MON | TUE | …)
        2. Time column labels (00:00 … 23:50)
        3. Vertical + horizontal hairlines
        4. Per-cell backgrounds — empty / hover / scheduled (priority color)
        5. Selected overlay — cyan tint + border on _selected cells
        6. Drag rectangle — translucent cyan rect during active drag
    """

    selection_changed = pyqtSignal(int)   # count

    def __init__(self, parent=None):
        super().__init__(parent)
        # Fix only the height (scrolling needs known total height); let
        # width follow the parent layout. setFixedSize on both axes
        # combined with a tall height was part of the layout-storm freeze.
        self.setFixedHeight(GRID_H)
        self.setMinimumWidth(TIME_COL_W + 7 * 60)   # absolute floor
        from PyQt6.QtWidgets import QSizePolicy as _SP
        self.setSizePolicy(_SP.Policy.Expanding, _SP.Policy.Fixed)
        self.setMouseTracking(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)
        # StrongFocus: required so keyPressEvent receives Esc for clear.
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._breaks: dict[tuple[int, int], dict] = {}
        self._selected: set[tuple[int, int]] = set()
        self._hover: Optional[tuple[int, int]] = None
        self._drag_start: Optional[tuple[int, int]] = None
        self._drag_end:   Optional[tuple[int, int]] = None
        self._dragging: bool = False
        self._press_cell: Optional[tuple[int, int]] = None
        self._priority = "Medium"   # default priority for new breaks

    def _day_col_w(self) -> int:
        """Column width adapts to current widget width — keeps the grid
        proportional regardless of dialog size."""
        return max(60, (self.width() - TIME_COL_W) // 7)

    def _grid_right_edge(self) -> int:
        """Right edge of the last day column (= TIME_COL_W + 7 × col_w)."""
        return TIME_COL_W + 7 * self._day_col_w()

    # ── Public API ────────────────────────────────────────────────────────

    def set_priority(self, p: str):
        if p in PRIORITY_COLORS:
            self._priority = p

    def get_breaks(self) -> dict[tuple[int, int], dict]:
        return dict(self._breaks)

    def set_breaks(self, breaks: dict[tuple[int, int], dict]):
        self._breaks = dict(breaks)
        self._selected.clear()
        self.update()
        self.selection_changed.emit(len(self._breaks))

    def add_break(self, day: int, slot: int, priority: Optional[str] = None):
        if 0 <= day < 7 and 0 <= slot < 144:
            self._breaks[(day, slot)] = {
                "priority": priority or self._priority,
            }

    def remove_break(self, day: int, slot: int):
        self._breaks.pop((day, slot), None)

    def clear_all(self):
        self._breaks.clear()
        self._selected.clear()
        self.update()
        self.selection_changed.emit(0)

    def selected_count(self) -> int:
        return len(self._selected)

    def selection(self) -> set[tuple[int, int]]:
        return set(self._selected)

    def schedule_at_selection(self):
        """Convert the current drag-selection into scheduled breaks."""
        if not self._selected:
            return
        for (d, s) in self._selected:
            self.add_break(d, s, self._priority)
        self._selected.clear()
        self.update()
        self.selection_changed.emit(len(self._breaks))

    def clear_at_selection(self):
        """Remove any scheduled break inside the current selection."""
        if not self._selected:
            return
        for cell in list(self._selected):
            self.remove_break(*cell)
        self._selected.clear()
        self.update()
        self.selection_changed.emit(len(self._breaks))

    def find_paste_source_day(self) -> Optional[int]:
        """Day index (0..6) with the most scheduled breaks, or first day with
        any breaks. None if no day has breaks yet."""
        counts: dict[int, int] = {}
        for (d, _s) in self._breaks:
            counts[d] = counts.get(d, 0) + 1
        if not counts:
            return None
        # Highest count, ties broken by earliest day
        return max(counts.items(), key=lambda kv: (kv[1], -kv[0]))[0]

    def paste_to_all_days(self):
        src = self.find_paste_source_day()
        if src is None:
            return False
        slots = [s for (d, s) in self._breaks if d == src]
        priorities = {s: self._breaks[(src, s)]["priority"] for s in slots}
        for day in range(7):
            for s in slots:
                self.add_break(day, s, priorities[s])
        self.update()
        self.selection_changed.emit(len(self._breaks))
        return True

    def paste_to_selected_day(self):
        """Copy the source-day pattern to the day(s) intersected by the
        current drag-selection."""
        if not self._selected:
            return False
        src = self.find_paste_source_day()
        if src is None:
            return False
        target_days = {d for (d, _s) in self._selected if d != src}
        if not target_days:
            return False
        slots = [s for (d, s) in self._breaks if d == src]
        priorities = {s: self._breaks[(src, s)]["priority"] for s in slots}
        for day in target_days:
            for s in slots:
                self.add_break(day, s, priorities[s])
        self._selected.clear()
        self.update()
        self.selection_changed.emit(len(self._breaks))
        return True

    # ── Hit testing ───────────────────────────────────────────────────────

    def _cell_at(self, pos) -> Optional[tuple[int, int]]:
        col_w = self._day_col_w()
        x = int(pos.x()) - TIME_COL_W
        y = int(pos.y()) - HEADER_H
        if x < 0 or y < 0:
            return None
        day  = x // col_w
        slot = y // CELL_H
        if not (0 <= day < 7) or not (0 <= slot < 144):
            return None
        return (int(day), int(slot))

    def _cell_rect(self, day: int, slot: int) -> QRect:
        """Geometry of cell (day, slot) inside this widget — used for both
        painting and bounded self.update(rect) calls."""
        col_w = self._day_col_w()
        x = TIME_COL_W + day * col_w
        y = HEADER_H + slot * CELL_H
        return QRect(x, y, col_w, CELL_H)

    # ── Mouse handling — toggle on click, additive drag rectangle ────────
    #
    # Selection model (changed 2026-05-07 per operator request):
    #   • Plain click    → TOGGLE that single cell (add if empty, remove if
    #                      already selected). Previous selection is preserved
    #                      so the operator can build up a multi-cell pick
    #                      cell-by-cell.
    #   • Drag rectangle → ADD all cells in the swept rectangle to the
    #                      existing selection (additive — no clear).
    #   • Esc            → clear the entire selection (handled in
    #                      keyPressEvent).
    #   • Right-click    → context menu; auto-targets the right-clicked cell
    #                      if it is not already selected.
    #
    # Press defers the toggle to release so a press-then-drag becomes a
    # rectangle add instead of a stray toggle on the press cell.

    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        cell = self._cell_at(e.position())
        if cell is None:
            return
        # Pull keyboard focus so subsequent Esc reaches keyPressEvent.
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        # Defer mutation until release/move classifies this as click vs drag.
        self._press_cell = cell
        self._drag_start = cell
        self._drag_end = cell
        self._dragging = False

    def mouseMoveEvent(self, e):
        cell = self._cell_at(e.position())
        prev_hover = self._hover
        self._hover = cell

        if self._drag_start is not None and \
                (e.buttons() & Qt.MouseButton.LeftButton):
            if cell is not None:
                # Promote to drag mode the moment we cross into a different
                # cell from the press anchor. Below that, treat as a click
                # (toggle on release).
                if not self._dragging and cell != self._drag_start:
                    self._dragging = True
                if self._dragging:
                    old_drag_rect = self._drag_bounds_rect()
                    self._drag_end = cell
                    # Additive: _refresh_drag_selection only adds cells,
                    # never removes — so existing selection survives.
                    self._refresh_drag_selection()
                    new_drag_rect = self._drag_bounds_rect()
                    self.update(old_drag_rect.united(new_drag_rect))
        elif prev_hover != cell:
            # Hover transition — repaint only the two affected cell rects.
            # Replaces a full-widget update() that would otherwise repaint
            # 4064px on every cell-boundary mouse move (= stutter storm).
            if prev_hover is not None:
                self.update(self._cell_rect(*prev_hover))
            if cell is not None:
                self.update(self._cell_rect(*cell))

    def _drag_bounds_rect(self) -> QRect:
        """Bounding rect of the active drag-select rectangle, or empty."""
        if self._drag_start is None or self._drag_end is None:
            return QRect()
        d1, s1 = self._drag_start
        d2, s2 = self._drag_end
        d_lo, d_hi = min(d1, d2), max(d1, d2)
        s_lo, s_hi = min(s1, s2), max(s1, s2)
        col_w = self._day_col_w()
        return QRect(
            TIME_COL_W + d_lo * col_w,
            HEADER_H + s_lo * CELL_H,
            (d_hi - d_lo + 1) * col_w,
            (s_hi - s_lo + 1) * CELL_H,
        )

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        if self._press_cell is not None and not self._dragging:
            # Plain click → toggle that cell. Other selected cells survive.
            cell = self._press_cell
            if cell in self._selected:
                self._selected.discard(cell)
            else:
                self._selected.add(cell)
            self.update(self._cell_rect(*cell))
        # else: drag already mutated _selected during mouseMoveEvent.
        self._press_cell = None
        self._drag_start = None
        self._drag_end = None
        self._dragging = False
        self.update()
        self.selection_changed.emit(len(self._selected))

    def keyPressEvent(self, e):
        # Esc clears the entire selection (the explicit "start over" hatch
        # now that plain click no longer auto-clears).
        if e.key() == Qt.Key.Key_Escape:
            if self._selected:
                self._selected.clear()
                self.update()
                self.selection_changed.emit(0)
            e.accept()
            return
        super().keyPressEvent(e)

    def leaveEvent(self, _e):
        self._hover = None
        self.update()

    def _refresh_drag_selection(self):
        if self._drag_start is None or self._drag_end is None:
            return
        d1, s1 = self._drag_start
        d2, s2 = self._drag_end
        d_lo, d_hi = min(d1, d2), max(d1, d2)
        s_lo, s_hi = min(s1, s2), max(s1, s2)
        for d in range(d_lo, d_hi + 1):
            for s in range(s_lo, s_hi + 1):
                self._selected.add((d, s))

    # ── Right-click context menu ─────────────────────────────────────────

    def _on_context_menu(self, pos):
        cell = self._cell_at(pos)
        if cell is None:
            return
        # If the cell isn't selected, treat the right-click as a single-cell
        # selection so the menu actions have a target.
        if cell not in self._selected:
            self._selected = {cell}
            self.update()

        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu {{ background: {BG_CARD}; color: {TEXT_PRI}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; padding: 4px; }}"
            f"QMenu::item {{ padding: 6px 18px; }}"
            f"QMenu::item:selected {{ background: {rgba(CYAN, 0.18)}; }}"
        )
        a_schedule = QAction("Schedule Break", self)
        a_schedule.triggered.connect(self.schedule_at_selection)
        menu.addAction(a_schedule)

        priorities = menu.addMenu("Set Priority")
        for p_name in PRIORITY_OPTIONS:
            act = QAction(p_name, self)
            act.triggered.connect(lambda _checked=False, n=p_name:
                                  self._set_priority_at_selection(n))
            priorities.addAction(act)

        a_clear = QAction("Clear", self)
        a_clear.triggered.connect(self.clear_at_selection)
        menu.addAction(a_clear)

        menu.exec(self.mapToGlobal(pos))

    def _set_priority_at_selection(self, p: str):
        if not self._selected:
            return
        for (d, s) in self._selected:
            if (d, s) in self._breaks:
                self._breaks[(d, s)]["priority"] = p
            else:
                self.add_break(d, s, p)
        self._selected.clear()
        self.update()
        self.selection_changed.emit(len(self._breaks))

    # ── Painting ──────────────────────────────────────────────────────────

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        # ── FIX A: clip painting to the dirty region ────────────────────
        # Without this, every paintEvent paints all 1008 cells + 144 time
        # labels + 144 minor lines on a 4064-px-tall widget. With it, only
        # the visible ~30 slot rows are painted per scroll step.
        dirty = _e.rect() if _e is not None else self.rect()

        col_w = self._day_col_w()
        right_edge = TIME_COL_W + 7 * col_w

        # Defensive: warn if dirty region covers >50% of widget — that's a
        # cue something is forcing full repaints.
        if dirty.height() > self.height() * 0.5 and self.height() > 1000:
            log.warning(
                f"[paint] big dirty rect {dirty.width()}×{dirty.height()} "
                f"on {self.width()}×{self.height()} widget — investigate"
            )

        # Compute first/last visible slot from dirty rect
        first_slot = max(0, (dirty.top() - HEADER_H) // CELL_H)
        last_slot  = min(143, (dirty.bottom() - HEADER_H) // CELL_H)

        # Background — only over the dirty area
        p.fillRect(dirty, QColor("#0a0c18"))

        # Header strip — only paint if the header is in the dirty region
        if dirty.top() < HEADER_H:
            p.fillRect(QRect(0, 0, right_edge, HEADER_H),
                       QColor("#0d0f1e"))
            p.setPen(QColor(TEXT_MUTED))
            p.setFont(inter(9, QFont.Weight.Bold, letter_spacing=1.0))
            p.drawText(QRect(0, 0, TIME_COL_W, HEADER_H),
                       Qt.AlignmentFlag.AlignCenter, "TIME")
            for c, day_name in enumerate(DAYS):
                x = TIME_COL_W + c * col_w
                p.drawText(QRect(x, 0, col_w, HEADER_H),
                           Qt.AlignmentFlag.AlignCenter, day_name)

        # Time column background — only behind the dirty slot range
        col_top = HEADER_H + first_slot * CELL_H
        col_bot = HEADER_H + (last_slot + 1) * CELL_H
        p.fillRect(QRect(0, col_top, TIME_COL_W, col_bot - col_top),
                   QColor("#0d0f1e"))

        # Time labels — only for visible slots
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(mono(9, bold=False))
        for slot in range(int(first_slot), int(last_slot) + 1):
            y = HEADER_H + slot * CELL_H
            p.drawText(QRect(0, y, TIME_COL_W, CELL_H),
                       Qt.AlignmentFlag.AlignCenter, _slot_to_time(slot))

        # Cell backgrounds — only for visible slots × all 7 days
        for slot in range(int(first_slot), int(last_slot) + 1):
            y = HEADER_H + slot * CELL_H
            for day in range(7):
                x = TIME_COL_W + day * col_w
                self._paint_cell(p, day, slot, x, y, col_w)

        # Hairlines — clipped to dirty region
        line = QColor(255, 255, 255, 12)
        p.setPen(QPen(line, 1))
        # Vertical lines (always span full visible height)
        v_top = max(0, dirty.top())
        v_bot = min(self.height(), dirty.bottom())
        for c in range(8):
            x = TIME_COL_W + c * col_w
            p.drawLine(x, v_top, x, v_bot)

        # Hour horizontals (every 6 slots) — only those in visible range
        hour_first = (int(first_slot) // 6) * 6
        hour_last  = ((int(last_slot) // 6) + 1) * 6
        for slot in range(hour_first, min(145, hour_last + 1), 6):
            y = HEADER_H + slot * CELL_H
            p.drawLine(0, y, right_edge, y)

        # Minor horizontals (every 10 min) — only visible slots
        minor = QColor(255, 255, 255, 5)
        p.setPen(QPen(minor, 1))
        for slot in range(int(first_slot), int(last_slot) + 2):
            if slot >= 145 or slot % 6 == 0:
                continue
            y = HEADER_H + slot * CELL_H
            p.drawLine(TIME_COL_W, y, right_edge, y)

        # Drag-rectangle overlay (live drag visualization)
        if self._drag_start is not None and self._drag_end is not None \
                and self._drag_start != self._drag_end:
            d1, s1 = self._drag_start
            d2, s2 = self._drag_end
            d_lo, d_hi = min(d1, d2), max(d1, d2)
            s_lo, s_hi = min(s1, s2), max(s1, s2)
            x = TIME_COL_W + d_lo * col_w
            y = HEADER_H + s_lo * CELL_H
            w = (d_hi - d_lo + 1) * col_w
            h = (s_hi - s_lo + 1) * CELL_H
            tint = QColor(CYAN); tint.setAlphaF(0.10)
            p.fillRect(QRect(x, y, w, h), tint)
            p.setPen(QPen(QColor(CYAN), 1.6))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(QRect(x, y, w - 1, h - 1))

    def _paint_cell(self, p: QPainter, day: int, slot: int,
                     x: int, y: int, col_w: int):
        cell_rect = QRect(x + 1, y + 1, col_w - 2, CELL_H - 2)

        # Default empty — slight zebra by hour
        if (slot // 6) % 2 == 0:
            p.fillRect(cell_rect, QColor(255, 255, 255, 4))
        else:
            p.fillRect(cell_rect, QColor("#0a0c18"))

        # Hover
        if self._hover == (day, slot):
            p.fillRect(cell_rect, QColor(255, 255, 255, 14))

        # Scheduled break
        if (day, slot) in self._breaks:
            data = self._breaks[(day, slot)]
            color = QColor(PRIORITY_COLORS.get(
                data.get("priority", "Medium"), AMBER))
            tint = QColor(color); tint.setAlphaF(0.50)
            p.fillRect(cell_rect, tint)
            # Left-edge accent bar
            accent = QRect(cell_rect.x(), cell_rect.y(), 3, cell_rect.height())
            p.fillRect(accent, color)

        # Selected overlay
        if (day, slot) in self._selected:
            sel_tint = QColor(CYAN); sel_tint.setAlphaF(0.20)
            p.fillRect(cell_rect, sel_tint)
            p.setPen(QPen(QColor(CYAN), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(cell_rect.adjusted(0, 0, -1, -1))


# ════════════════════════════════════════════════════════════════════════════
# Main dialog
# ════════════════════════════════════════════════════════════════════════════

class SpotProgrammingDialog(BaseDialog):

    schedule_saved  = pyqtSignal(int, list)   # campaign_id, rows
    schedule_staged = pyqtSignal(list)        # rows (for staged mode)

    HEADER_H = 64
    FOOTER_H = 56

    def __init__(self, db, campaign_id: Optional[int] = None,
                 campaign_name: str = "",
                 initial_schedule: Optional[list] = None,
                 parent=None):
        self._db = db
        self._campaign_id = int(campaign_id) if campaign_id else None
        self._campaign_name = campaign_name or "(unsaved campaign)"
        self._initial_schedule = initial_schedule or []

        # Refs
        self._grid: Optional[_BreakScheduleGrid] = None
        # NOTE: no self._scroll — Fix B removed the inner QScrollArea.
        # BaseDialog's outer scroll handles vertical scrolling now.
        self._count_display: Optional[_SpotsCountDisplay] = None
        self._priority_combo: Optional[QComboBox] = None
        self._preset_combo: Optional[QComboBox] = None
        self._programming_combo: Optional[QComboBox] = None
        self._file_alias_combo: Optional[QComboBox] = None
        self._paste_selected_btn: Optional[_ActionButton] = None
        self._paste_all_btn: Optional[_ActionButton] = None

        super().__init__(target_size=(860, 620), parent=parent)
        self._load_initial()

    # ── Header ────────────────────────────────────────────────────────────

    def _build_header(self) -> QWidget:
        f = QFrame()
        f.setStyleSheet(
            f"QFrame {{ background: #0d0f1e; "
            f"border-bottom: 1px solid {rgba('#ffffff', 0.06)}; }}"
        )
        h = QHBoxLayout(f)
        h.setContentsMargins(16, 12, 12, 12); h.setSpacing(14)

        h.addWidget(_CalendarIcon())

        title_box = QWidget(); title_box.setStyleSheet("background: transparent;")
        tv = QVBoxLayout(title_box)
        tv.setContentsMargins(0, 0, 0, 0); tv.setSpacing(2)
        title = QLabel("SPOT PROGRAMMING")
        title.setFont(inter(15, QFont.Weight.Black, letter_spacing=0.5))
        title.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        sub = QLabel(
            f"{self._campaign_name}  •  Set break times for each day"
        )
        sub.setFont(inter(10))
        sub.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        tv.addWidget(title); tv.addWidget(sub)
        h.addWidget(title_box)
        h.addStretch()

        # Presets dropdown
        preset_box = QWidget()
        preset_box.setStyleSheet("background: transparent;")
        pv = QVBoxLayout(preset_box)
        pv.setContentsMargins(0, 0, 0, 0); pv.setSpacing(2)
        pl = QLabel("Presets")
        pl.setFont(inter(8, QFont.Weight.Bold, letter_spacing=1.2))
        pl.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        pv.addWidget(pl, alignment=Qt.AlignmentFlag.AlignRight)

        self._preset_combo = _sidebar_combo(
            ["Select Preset"] + list(PRESETS.keys()))
        self._preset_combo.setFixedWidth(150)
        self._preset_combo.currentIndexChanged.connect(self._on_preset_picked)
        pv.addWidget(self._preset_combo)
        h.addWidget(preset_box)

        # Close
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
        outer = QVBoxLayout(c)
        outer.setContentsMargins(12, 10, 12, 10); outer.setSpacing(8)

        # Action bar
        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0); action_row.setSpacing(8)

        self._paste_selected_btn = _ActionButton(
            "Paste to Selected Day", GREEN)
        self._paste_selected_btn.clicked.connect(self._on_paste_selected)
        self._paste_all_btn = _ActionButton("Paste to All Days", CYAN)
        self._paste_all_btn.clicked.connect(self._on_paste_all)
        add_btn = _ActionButton("+", GREEN, prominent=True)
        add_btn.setFixedWidth(38)
        add_btn.clicked.connect(self._on_add)
        rm_btn = _ActionButton("−", RED, prominent=True)
        rm_btn.setFixedWidth(38)
        rm_btn.clicked.connect(self._on_remove)

        action_row.addWidget(self._paste_selected_btn)
        action_row.addWidget(self._paste_all_btn)
        action_row.addWidget(add_btn)
        action_row.addWidget(rm_btn)
        action_row.addStretch()
        outer.addLayout(action_row)

        # Body — sidebar + grid
        body = QHBoxLayout(); body.setContentsMargins(0, 0, 0, 0); body.setSpacing(12)
        body.addWidget(self._build_sidebar(), stretch=0)
        body.addWidget(self._build_grid_panel(), stretch=1)
        outer.addLayout(body)
        return c

    def _build_sidebar(self) -> QWidget:
        sb = QFrame(); sb.setStyleSheet("background: transparent;")
        sb.setFixedWidth(190)
        v = QVBoxLayout(sb)
        v.setContentsMargins(0, 0, 0, 0); v.setSpacing(6)

        v.addWidget(_sidebar_label("Total Spots Count"))
        self._count_display = _SpotsCountDisplay()
        v.addWidget(self._count_display)

        v.addSpacing(4)
        v.addWidget(_sidebar_label("Programming System"))
        self._programming_combo = _sidebar_combo(
            ["Specific Order", "Random", "Sequential"], "Specific Order")
        v.addWidget(self._programming_combo)

        v.addWidget(_sidebar_label("File Alias"))
        self._file_alias_combo = _sidebar_combo(["—"])
        v.addWidget(self._file_alias_combo)

        v.addWidget(_sidebar_label("Priority"))
        self._priority_combo = _sidebar_combo(PRIORITY_OPTIONS, "Medium")
        self._priority_combo.currentTextChanged.connect(
            lambda t: self._grid.set_priority(t) if self._grid else None)
        v.addWidget(self._priority_combo)

        v.addSpacing(8)
        mass = QPushButton("Mass Change Priorities")
        mass.setFixedHeight(28)
        mass.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        mass.setFont(inter(10, QFont.Weight.DemiBold))
        mass.setStyleSheet(
            f"QPushButton {{ background: {rgba(PURPLE, 0.16)}; "
            f"color: {PURPLE_LIGHT}; "
            f"border: 1px solid {rgba(PURPLE, 0.30)}; "
            f"border-radius: 5px; padding: 0 10px; }}"
            f"QPushButton:hover {{ background: {rgba(PURPLE, 0.24)}; }}"
        )
        mass.clicked.connect(self._on_mass_change_priorities)
        v.addWidget(mass)

        v.addSpacing(2)
        action_row = QHBoxLayout(); action_row.setSpacing(6)
        clear = QPushButton("Clear All")
        clear.setFixedHeight(28); clear.setCursor(
            QCursor(Qt.CursorShape.PointingHandCursor))
        clear.setFont(inter(10, QFont.Weight.DemiBold))
        clear.setStyleSheet(
            f"QPushButton {{ background: {RED}; color: white; "
            f"border: none; border-radius: 5px; padding: 0 10px; }}"
            f"QPushButton:hover {{ background: #f87171; }}"
        )
        clear.clicked.connect(self._on_clear_all)
        set_mode = QPushButton("Set Mode")
        set_mode.setFixedHeight(28); set_mode.setCursor(
            QCursor(Qt.CursorShape.PointingHandCursor))
        set_mode.setFont(inter(10, QFont.Weight.DemiBold))
        set_mode.setStyleSheet(
            f"QPushButton {{ background: {GREEN}; color: white; "
            f"border: none; border-radius: 5px; padding: 0 10px; }}"
            f"QPushButton:hover {{ background: {GREEN_LIGHT}; }}"
        )
        set_mode.clicked.connect(self._on_set_mode)
        action_row.addWidget(clear)
        action_row.addWidget(set_mode)
        v.addLayout(action_row)

        # ── AUTO-DISTRIBUTE (2026-07-04, operator-approved) ──
        # "20 rotations, 8 AM–9 PM" → one click picks evenly-spread
        # break-window times for EVERY day and fills the grid; the
        # generated list doubles as the client's time sheet.
        v.addSpacing(8)
        v.addWidget(_sidebar_label("Auto-Distribute"))
        ad_row1 = QHBoxLayout(); ad_row1.setSpacing(6)
        self._ad_rotations = QSpinBox()
        self._ad_rotations.setRange(1, 200)
        self._ad_rotations.setValue(20)
        self._ad_rotations.setFont(inter(10, QFont.Weight.DemiBold))
        self._ad_rotations.setStyleSheet(
            f"QSpinBox {{ background: {BG_CARD}; color: {TEXT_PRI}; "
            f"border: 1px solid {rgba('#ffffff', 0.08)}; "
            f"border-radius: 5px; padding: 3px 6px; }}")
        rot_lbl = QLabel("rotations/day")
        rot_lbl.setFont(inter(9))
        rot_lbl.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent;")
        ad_row1.addWidget(self._ad_rotations)
        ad_row1.addWidget(rot_lbl, stretch=1)
        v.addLayout(ad_row1)
        ad_row2 = QHBoxLayout(); ad_row2.setSpacing(6)
        hours = [f"{h:02d}:00" for h in range(24)]
        self._ad_from = _sidebar_combo(hours, "08:00")
        self._ad_to = _sidebar_combo(hours, "21:00")
        ad_row2.addWidget(self._ad_from)
        to_lbl = QLabel("to")
        to_lbl.setFont(inter(9))
        to_lbl.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent;")
        ad_row2.addWidget(to_lbl)
        ad_row2.addWidget(self._ad_to)
        v.addLayout(ad_row2)
        auto_btn = QPushButton("✦ Auto-Distribute")
        auto_btn.setFixedHeight(30)
        auto_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        auto_btn.setFont(inter(10, QFont.Weight.Bold))
        auto_btn.setStyleSheet(
            f"QPushButton {{ background: {rgba(CYAN, 0.18)}; "
            f"color: {CYAN_LIGHT}; "
            f"border: 1px solid {rgba(CYAN, 0.40)}; "
            f"border-radius: 5px; padding: 0 10px; }}"
            f"QPushButton:hover {{ background: {rgba(CYAN, 0.28)}; }}")
        auto_btn.clicked.connect(self._on_auto_distribute)
        v.addWidget(auto_btn)

        v.addSpacing(8)
        v.addWidget(_sidebar_label("Break Preview"))
        # Preview area placeholder
        preview = QFrame()
        preview.setMinimumHeight(60)
        preview.setStyleSheet(
            f"QFrame {{ background: {BG_CARD}; "
            f"border: 1px solid {rgba('#ffffff', 0.04)}; "
            f"border-radius: 5px; }}"
        )
        v.addWidget(preview, stretch=1)

        cb = QCheckBox("Preview Spot Breaks Load")
        cb.setFont(inter(9))
        cb.setStyleSheet(
            f"QCheckBox {{ color: {TEXT_SEC}; background: transparent; }}"
            f"QCheckBox::indicator {{ width: 14px; height: 14px; }}"
            f"QCheckBox::indicator:unchecked {{ background: {BG_CARD}; "
            f"border: 1px solid {rgba(PURPLE, 0.40)}; border-radius: 3px; }}"
            f"QCheckBox::indicator:checked {{ background: {PURPLE}; "
            f"border: 1px solid {PURPLE_LIGHT}; border-radius: 3px; }}"
        )
        v.addWidget(cb)
        return sb

    def _build_grid_panel(self) -> QWidget:
        """Grid container — Fix B: NO inner QScrollArea. The grid is added
        directly so BaseDialog's outer QScrollArea handles vertical scrolling.
        Nested scroll areas with setWidgetResizable=True caused a layout-storm
        freeze on dialog open (incident 2026-05-04)."""
        wrap = QFrame(); wrap.setStyleSheet("background: transparent;")
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0); v.setSpacing(4)

        self._grid = _BreakScheduleGrid()
        self._grid.selection_changed.connect(self._on_grid_changed)
        v.addWidget(self._grid, stretch=0)

        # Bottom hint
        hint = QLabel(
            "▼ Scroll — 144 slots (00:00 → 23:50, every 10 min)  •  "
            "Click cells to toggle, drag for a rectangle, Esc to clear")
        hint.setFont(inter(9))
        hint.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(hint)
        return wrap

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

        apply_btn = QPushButton("✓  Apply Schedule")
        apply_btn.setFixedHeight(34); apply_btn.setMinimumWidth(150)
        apply_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        apply_btn.setFont(inter(11, QFont.Weight.DemiBold))
        apply_btn.setStyleSheet(
            f"QPushButton {{ background: qlineargradient("
            f"x1:0,y1:0,x2:0,y2:1, stop:0 {PURPLE_LIGHT}, "
            f"stop:0.5 {PURPLE}, stop:1 #7c3aed); "
            f"color: white; border: none; border-radius: 7px; "
            f"padding: 0 22px; }}"
            f"QPushButton:hover {{ background: qlineargradient("
            f"x1:0,y1:0,x2:0,y2:1, stop:0 #c4b5fd, stop:1 {PURPLE}); }}"
        )
        apply_btn.clicked.connect(self._on_apply)
        h.addWidget(apply_btn)
        return f

    # ── Initial load ──────────────────────────────────────────────────────

    def _load_initial(self):
        # If a campaign_id was passed and DB has rows, load them
        rows = []
        if self._campaign_id is not None:
            try:
                self._db._ensure_campaign_schedule_columns()
                rows = [{k: r[k] for k in r.keys()} for r in
                        self._db.get_break_schedule(self._campaign_id)]
            except Exception as exc:
                log.error(f"get_break_schedule failed: {exc}")
                rows = []
        elif self._initial_schedule:
            rows = list(self._initial_schedule)

        breaks: dict[tuple[int, int], dict] = {}
        for r in rows:
            slot = _time_to_slot(r.get("break_time") or "")
            day = int(r.get("day_of_week") or 0)
            if slot is None:
                continue
            breaks[(day, slot)] = {
                "priority": r.get("priority") or "Medium",
            }
        if self._grid:
            self._grid.set_breaks(breaks)

    # ── Handlers ──────────────────────────────────────────────────────────

    def _on_grid_changed(self, _count: int):
        if self._count_display and self._grid:
            self._count_display.set_count(len(self._grid.get_breaks()))

    def _on_add(self):
        if not self._grid:
            return
        if self._grid.selected_count() == 0:
            dialogs.info(
                self, "No selection",
                "Click cells to select (or drag a rectangle), "
                "then click + Add. Esc clears selection.")
            return
        self._grid.schedule_at_selection()

    def _on_remove(self):
        if not self._grid:
            return
        if self._grid.selected_count() == 0:
            dialogs.info(
                self, "No selection",
                "Click cells to select (or drag a rectangle), "
                "then click − Remove. Esc clears selection.")
            return
        self._grid.clear_at_selection()

    def _on_paste_all(self):
        if not self._grid:
            return
        ok = self._grid.paste_to_all_days()
        if not ok:
            dialogs.info(
                self, "Nothing to paste",
                "No breaks scheduled yet — schedule some first, then paste.")
        else:
            src = self._grid.find_paste_source_day()
            log.info(f"[paste-all] source day index = {src}")

    def _on_paste_selected(self):
        if not self._grid:
            return
        ok = self._grid.paste_to_selected_day()
        if not ok:
            dialogs.info(
                self, "Nothing to paste",
                "Select target cells in another day first, "
                "then click Paste to Selected Day.\n\n"
                "Source day = the day with the most existing breaks.")

    def _on_clear_all(self):
        if not self._grid:
            return
        if not self._grid.get_breaks():
            return
        if dialogs.confirm(self, "Clear all breaks",
                   "Remove every scheduled break across all 7 days?",
                   danger=True, yes_label="Clear All"):
            self._grid.clear_all()

    def _on_auto_distribute(self):
        """One click: evenly spread N rotations/day across the break-
        window times in the chosen range, every day of the week. The
        resulting list = the client's TIME SHEET (also copied to the
        clipboard). Existing grid cells stay; duplicates merge."""
        from core.break_policy import (auto_distribute_slots,
                                       parse_windows)
        from core.settings import Settings
        rotations = int(self._ad_rotations.value())
        try:
            from_h = int(self._ad_from.currentText().split(":")[0])
            to_h = int(self._ad_to.currentText().split(":")[0])
        except (ValueError, IndexError):
            from_h, to_h = 8, 21
        if to_h <= from_h:
            dialogs.warning(self, "Auto-Distribute",
                            "'To' hour must be after 'From' hour.")
            return
        windows = parse_windows(
            Settings().get("break_policy_windows", "15,30,45"))
        times = auto_distribute_slots(rotations, from_h, to_h, windows)
        if not times:
            dialogs.warning(self, "Auto-Distribute",
                            "No break-window slots in that range.")
            return
        priority = self._priority_combo.currentText() or "Medium"
        added = 0
        for t in times:
            slot = _time_to_slot(t)
            if slot is None:
                continue
            for day in range(7):
                self._grid.add_break(day, slot, priority)
                added += 1
        self._count_display.set_count(len(self._grid.get_breaks()))
        sheet = "  ·  ".join(times)
        try:
            from PyQt6.QtWidgets import QApplication
            QApplication.clipboard().setText(
                f"Daily rotations ({len(times)}x): " + ", ".join(times))
        except Exception:
            pass
        log.info(f"[auto-distribute] {len(times)} rotations/day × 7 "
                 f"days placed ({from_h:02d}:00-{to_h:02d}:00, "
                 f"windows={windows})")
        dialogs.info(
            self, "Auto-Distribute — Client Time Sheet",
            f"{len(times)} rotations/day placed for all 7 days "
            f"(priority {priority}).\n\n{sheet}\n\n"
            f"Time sheet copied to clipboard — paste into the "
            f"client's WhatsApp/email. Click Apply Schedule to save.")

    def _on_set_mode(self):
        # TODO: open a sub-dialog for advanced bulk-mode editing.
        log.info("[Set Mode] — bulk-edit mode not yet implemented")

    def _on_mass_change_priorities(self):
        # TODO: pop a small modal asking for target priority + scope.
        log.info("[Mass Change Priorities] — not yet implemented")

    def _on_preset_picked(self, idx: int):
        if idx <= 0 or not self._grid:
            return
        name = self._preset_combo.currentText()
        template = PRESETS.get(name) or []
        # Replace current grid with the preset
        breaks: dict[tuple[int, int], dict] = {}
        for (day, time_str) in template:
            slot = _time_to_slot(time_str)
            if slot is not None:
                breaks[(day, slot)] = {"priority": self._grid._priority}
        self._grid.set_breaks(breaks)
        log.info(f"[preset] applied '{name}' ({len(template)} breaks)")
        # Reset combo so picking the same preset again still triggers
        self._preset_combo.blockSignals(True)
        self._preset_combo.setCurrentIndex(0)
        self._preset_combo.blockSignals(False)

    def _on_apply(self):
        rows = self._collect_rows()
        if self._campaign_id is not None:
            # Persisted mode — write directly to DB
            try:
                self._db.update_break_schedule(self._campaign_id, rows)
                log.info(f"[apply] saved {len(rows)} break rows to "
                         f"campaign {self._campaign_id}")
            except Exception as exc:
                log.error(f"update_break_schedule failed: {exc}",
                          exc_info=True)
                dialogs.error(
                    self, "Save failed",
                    f"Could not save schedule:\n\n{exc}")
                return
            self.schedule_saved.emit(int(self._campaign_id), rows)
        else:
            # Staged mode — hand back to caller (AddCampaignDialog)
            log.info(f"[apply] staged {len(rows)} break rows for "
                     f"unsaved campaign")
            self.schedule_staged.emit(rows)
        self.accept()

    def _collect_rows(self) -> list[dict]:
        """Convert grid state → list[dict] in DB row shape."""
        if not self._grid:
            return []
        breaks = self._grid.get_breaks()
        # Order rows by day, then time, then assign sequential slot_order
        items = sorted(breaks.items(), key=lambda kv: (kv[0][0], kv[0][1]))
        rows = []
        per_day_order: dict[int, int] = {}
        for ((day, slot), data) in items:
            order = per_day_order.get(day, 0)
            per_day_order[day] = order + 1
            rows.append({
                "day_of_week": day,
                "break_time":  _slot_to_time(slot),
                "slot_order":  order,
                "priority":    data.get("priority") or "Medium",
            })
        return rows
