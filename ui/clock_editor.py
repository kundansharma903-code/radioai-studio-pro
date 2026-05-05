"""
RadioAI Studio Pro — Clock Editor (Figma 59:2).

Phase F2.3: full rewrite from the old 165:2 layout to 59:2.

Layout (1440 × 900)
-------------------
  HEADER     1440 ×  72   y=  0..72  — RadioAI/STUDIO PRO + screen title
                                       block + clock + station + Open Studio
  CONTENT    1440 × 778   y= 72..850
    LEFT      240 × 778   x=  0..240  — MY CLOCKS list + Duplicate/Rename/Delete
    CENTER    760 × 778   x=240..1000 — Action toolbar + 2-row timeline
                                       + SELECTED slot detail card
    RIGHT     440 × 778   x=1000..1440 — SLOT PROPERTIES + overview + categories
                                        + per-type form (6 types) + AI Optimiser
  STATUSBAR  1440 ×  50   y=850..900  — Pills + version + Open Studio CTA

═════════════════════════════════════════════════════════════════════════════
PERFORMANCE NOTES — DO NOT VIOLATE  (inherited from Studio + Spot Programming)
═════════════════════════════════════════════════════════════════════════════
  1. event.rect() CLIPPING — the timeline is the tallest custom-paint surface.
     paintEvent of _Timeline must respect the dirty rect when scrolled.
  2. NO bare self.update() in mouseMoveEvent — bounded update(rect) only.
  3. NO db calls in paintEvent — caller-side only.
  4. NO nested QScrollArea — Clock Editor is hosted in MainWindow's outer
     scroll. Internal scrolls would re-create the layout-storm trap.
  5. NO setMouseTracking(True) unless cursor change is needed.
═════════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import logging
from typing import Optional

from PyQt6.QtCore import Qt, QRect, QRectF, QPoint, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QLinearGradient, QFont, QCursor,
    QMouseEvent,
)
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QLineEdit, QComboBox, QStackedWidget, QInputDialog, QMessageBox,
    QSizePolicy,
)

from ui.widgets._tokens import (
    inter, mono, rgba,
    BG_BASE, BG_DARK, BG_PANEL, BG_CARD, BG_CARD_DK, BG_ELEVATED,
    TEXT_PRI, TEXT_SEC, TEXT_MUTED, TEXT_DIM,
    CYAN, CYAN_LIGHT, PURPLE, PURPLE_LIGHT, PURPLE_DARK,
    GREEN, GREEN_LIGHT, AMBER, AMBER_LIGHT,
    RED, RED_LIGHT, PINK, PINK_LIGHT, TEAL, TEAL_LIGHT,
)

log = logging.getLogger("ClockEditor")


# ── Layout constants ───────────────────────────────────────────────────────

WINDOW_W   = 1440
WINDOW_H   = 900
HEADER_H   = 72
STATUS_H   = 50

LEFT_X  = 0
LEFT_W  = 240
CENTER_X = LEFT_X + LEFT_W              # 240
CENTER_W = 760
RIGHT_X  = CENTER_X + CENTER_W          # 1000
RIGHT_W  = WINDOW_W - RIGHT_X           # 440

CONTENT_Y = HEADER_H
CONTENT_H = WINDOW_H - HEADER_H - STATUS_H   # 778

BORDER = "#1c1f38"


# ── Slot type metadata (per Figma 59:2 legend) ──────────────────────────────

SLOT_TYPES = ("Song", "Break", "Jingle", "Station ID", "Sweeper", "Voice Track")

# Color per Figma 59:2 spec; legacy 'Spot' kept as RED for any pre-migration row.
SLOT_TYPE_COLORS = {
    "Song":         AMBER,    "song":        AMBER,
    "Break":        GREEN,    "break":       GREEN,
    "Jingle":       CYAN,     "jingle":      CYAN,
    "Station ID":   PINK,     "station_id":  PINK,
    "Sweeper":      PURPLE,   "sweeper":     PURPLE,
    "Voice Track":  TEAL,     "voice_track": TEAL,
    "Spot":         RED,      "spot":        RED,    # legacy; migrate on save
}

# Two-letter badge prefixes (Figma legend pills).
SLOT_TYPE_BADGE = {
    "Song": "S", "Break": "B", "Jingle": "J",
    "Station ID": "ID", "Sweeper": "SW", "Voice Track": "VT",
}


def _slot_type_color(slot_type: str) -> str:
    return SLOT_TYPE_COLORS.get(slot_type or "", TEXT_MUTED)


def _normalize_slot_type(s: str) -> str:
    """Canonicalize stored slot_type to one of SLOT_TYPES (or pass through)."""
    if not s:
        return "Song"
    s = s.strip()
    # Special-case the multi-word ones (case-insensitive match).
    low = s.lower().replace("_", " ")
    for canonical in SLOT_TYPES:
        if canonical.lower() == low:
            return canonical
    # Legacy 'Spot' is recognised as such (caller may map to Break elsewhere).
    if low == "spot":
        return "Spot"
    # Fallback — title-case single word.
    return s[:1].upper() + s[1:].lower()


def _fmt_minutes(seconds: int) -> str:
    """seconds → 'M:SS'."""
    if seconds is None or seconds < 0:
        return "0:00"
    s = int(seconds)
    return f"{s // 60}:{s % 60:02d}"


# ════════════════════════════════════════════════════════════════════════════
# HEADER (1440×72) — RadioAI/STUDIO PRO + screen title + clock + station
# ════════════════════════════════════════════════════════════════════════════

class _Header(QFrame):
    """Top bar matching Figma 59:14/15 spec — fixed RadioAI overlap.

    RadioAI (18px Bold) at x=75 y=14, STUDIO PRO (9px Semi Bold) at x=75 y=36.
    Logo dot at x=14 y=24 (12×12).  Nav buttons inline with logo.
    """

    control_panel_clicked = pyqtSignal()
    scheduling_clicked    = pyqtSignal()
    studio_clicked        = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(HEADER_H)
        self.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border-bottom: 1px solid {BORDER}; }}"
        )

        # Live clock state
        self._clock_text = "00:00:00"
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick_clock)
        self._timer.start()
        self._tick_clock()

        # Nav buttons (Control Panel | Scheduling | Clock Editor active)
        cp_btn = QPushButton("Control Panel", self)
        cp_btn.setGeometry(220, 22, 110, 28)
        cp_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        cp_btn.setFont(inter(10, QFont.Weight.Medium))
        cp_btn.setStyleSheet(self._nav_qss(active=False))
        cp_btn.clicked.connect(self.control_panel_clicked.emit)

        sched_btn = QPushButton("Scheduling", self)
        sched_btn.setGeometry(336, 22, 92, 28)
        sched_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        sched_btn.setFont(inter(10, QFont.Weight.Medium))
        sched_btn.setStyleSheet(self._nav_qss(active=False))
        sched_btn.clicked.connect(self.scheduling_clicked.emit)

        ce_btn = QPushButton("Clock Editor", self)
        ce_btn.setGeometry(434, 22, 108, 28)
        ce_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        ce_btn.setFont(inter(10, QFont.Weight.DemiBold))
        ce_btn.setStyleSheet(self._nav_qss(active=True))

        # Open Studio CTA (top-right)
        st_btn = QPushButton("▶  Open Studio", self)
        st_btn.setGeometry(WINDOW_W - 220, 18, 200, 36)
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

        # RadioAI (18px Bold) at x=75 y=14 + STUDIO PRO (9px Semi) at x=75 y=36
        # — per Figma 59:14/15 spec; fixes the overlap from the old 50px header.
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

        # Screen title block (just right of nav)
        p.setPen(QColor(TEXT_PRI))
        p.setFont(inter(15, QFont.Weight.Bold, letter_spacing=0.2))
        p.drawText(QRectF(560, 14, 280, 22),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "Clock Editor")
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(inter(9))
        p.drawText(QRectF(560, 38, 360, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "Design hourly broadcast templates — define what plays each hour")

        # Live clock (mono, large)
        p.setPen(QColor(TEXT_PRI))
        p.setFont(mono(18, bold=True))
        p.drawText(QRectF(WINDOW_W - 410, 14, 180, 24),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   self._clock_text)
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(inter(9))
        p.drawText(QRectF(WINDOW_W - 410, 38, 180, 16),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   "KISS FM 91.5")


# ════════════════════════════════════════════════════════════════════════════
# CLOCKS LIST SIDEBAR (240×778) — replaces the old filter UI entirely
# ════════════════════════════════════════════════════════════════════════════

class _ClockRow(QFrame):
    """One row in the MY CLOCKS list. Click → emits selected(clock_id)."""

    clicked = pyqtSignal(int)

    def __init__(self, clock: dict, is_active: bool, parent=None):
        super().__init__(parent)
        self._clock = dict(clock)
        self._active = bool(is_active)
        self.setFixedHeight(54)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(int(self._clock.get("id", 0)))

    def paintEvent(self, _e):
        super().paintEvent(_e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(8, 4, -8, -4)

        # Background (active = elevated, hover handled by stylesheet via :hover
        # would be ideal but for custom QPainter we just draw active state).
        bg = BG_ELEVATED if self._active else BG_CARD_DK
        p.setBrush(QColor(bg))
        accent = _slot_type_color("Song") if self._active else BORDER
        p.setPen(QPen(QColor(accent), 1))
        p.drawRoundedRect(QRectF(rect), 6, 6)

        # Active indicator dot
        if self._active:
            p.setBrush(QColor(AMBER)); p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QRectF(rect.x() + 8, rect.y() + 14, 8, 8))
            text_x = rect.x() + 24
        else:
            text_x = rect.x() + 12

        # Clock name
        p.setPen(QColor(TEXT_PRI if self._active else TEXT_SEC))
        p.setFont(inter(11, QFont.Weight.DemiBold))
        p.drawText(QRectF(text_x, rect.y() + 6, rect.width() - 24, 18),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   str(self._clock.get("name") or "—"))

        # Time range subtitle
        ts = self._clock.get("time_start") or ""
        te = self._clock.get("time_end") or ""
        time_str = f"{ts} – {te}" if (ts or te) else "00:00 – 24:00"
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(mono(9, bold=False))
        p.drawText(QRectF(text_x, rect.y() + 24, rect.width() - 60, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   time_str)

        # Slot count badge (right side)
        n = int(self._clock.get("slot_count") or 0)
        p.setPen(QColor(TEXT_DIM))
        p.setFont(inter(10, QFont.Weight.Bold))
        p.drawText(QRectF(rect.right() - 32, rect.y() + 6, 26, 36),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   str(n))


class _ClocksListSidebar(QFrame):
    """MY CLOCKS list + +New + Duplicate/Rename/Delete actions."""

    clock_selected      = pyqtSignal(int)   # row clicked
    new_clock_requested = pyqtSignal()
    duplicate_requested = pyqtSignal()
    rename_requested    = pyqtSignal()
    delete_requested    = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(LEFT_W, CONTENT_H)
        self.setStyleSheet(
            f"QFrame {{ background: {BG_DARK}; "
            f"border-right: 1px solid {BORDER}; }}"
        )

        v = QVBoxLayout(self)
        v.setContentsMargins(8, 14, 8, 12); v.setSpacing(6)

        # Header row: "MY CLOCKS"  +  [+ New]
        header_row = QHBoxLayout(); header_row.setSpacing(6)
        header = QLabel("MY CLOCKS")
        header.setFont(inter(8, QFont.Weight.Black, letter_spacing=1.6))
        header.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        header_row.addWidget(header)
        header_row.addStretch()
        new_btn = QPushButton("+ New")
        new_btn.setFixedHeight(24)
        new_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        new_btn.setFont(inter(9, QFont.Weight.DemiBold))
        new_btn.setStyleSheet(
            f"QPushButton {{ background: {rgba(CYAN, 0.16)}; "
            f"color: {CYAN_LIGHT}; "
            f"border: 1px solid {rgba(CYAN, 0.32)}; "
            f"border-radius: 4px; padding: 0 8px; }}"
            f"QPushButton:hover {{ background: {rgba(CYAN, 0.26)}; }}"
        )
        new_btn.clicked.connect(self.new_clock_requested.emit)
        header_row.addWidget(new_btn)
        v.addLayout(header_row)

        # Rows holder
        self._rows_box = QFrame(); self._rows_box.setStyleSheet("background: transparent;")
        self._rows_layout = QVBoxLayout(self._rows_box)
        self._rows_layout.setContentsMargins(0, 6, 0, 6); self._rows_layout.setSpacing(4)
        v.addWidget(self._rows_box)

        v.addStretch()

        # Action row at the bottom — Duplicate / Rename / Delete
        for label, color, signal in [
            ("Duplicate", CYAN_LIGHT, self.duplicate_requested),
            ("Rename",    AMBER,      self.rename_requested),
            ("Delete",    RED,        self.delete_requested),
        ]:
            b = QPushButton(label)
            b.setFixedHeight(28)
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.setFont(inter(10, QFont.Weight.DemiBold))
            b.setStyleSheet(
                f"QPushButton {{ background: {rgba(color, 0.14)}; "
                f"color: {color}; "
                f"border: 1px solid {rgba(color, 0.32)}; "
                f"border-radius: 5px; padding: 0 8px; }}"
                f"QPushButton:hover {{ background: {rgba(color, 0.24)}; }}"
                f"QPushButton:disabled {{ background: rgba(255,255,255,0.02); "
                f"color: {TEXT_DIM}; border-color: rgba(255,255,255,0.04); }}"
            )
            b.clicked.connect(signal.emit)
            v.addWidget(b)

        self._rows: list[_ClockRow] = []

    def populate(self, clocks: list[dict], active_id: Optional[int]) -> None:
        # Clear existing
        for r in self._rows:
            r.setParent(None); r.deleteLater()
        self._rows.clear()
        for clk in clocks:
            row = _ClockRow(clk, is_active=(int(clk.get("id") or 0) == int(active_id or 0)))
            row.clicked.connect(self.clock_selected.emit)
            self._rows_layout.addWidget(row)
            self._rows.append(row)


# ════════════════════════════════════════════════════════════════════════════
# TIMELINE (760×778) — action toolbar + 2-row horizontal timeline + detail
# ════════════════════════════════════════════════════════════════════════════

class _TimelineGrid(QWidget):
    """Two-row horizontal slot grid.  Row 1 = 0-30 min, Row 2 = 30-60 min.

    Slot blocks have width proportional to their estimated duration.  Click
    inside a block selects it and emits slot_clicked(index).
    """

    SLOT_DEFAULT_SECONDS = {
        "Song": 210, "Break": 60, "Jingle": 12,
        "Station ID": 8, "Sweeper": 8, "Voice Track": 30, "Spot": 60,
    }

    slot_clicked = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._slots: list[dict] = []
        self._selected_idx: Optional[int] = None
        # (idx, QRect) for hit testing — recomputed on every paint.
        self._hit_rects: list[tuple[int, QRect]] = []
        self.setMinimumHeight(280)

    def set_slots(self, slots: list[dict], selected_idx: Optional[int]) -> None:
        self._slots = list(slots or [])
        self._selected_idx = selected_idx
        self.update()

    def _slot_seconds(self, slot: dict) -> int:
        explicit = slot.get("duration_seconds")
        if explicit:
            return int(explicit)
        return self.SLOT_DEFAULT_SECONDS.get(
            _normalize_slot_type(slot.get("slot_type", "")), 60)

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() != Qt.MouseButton.LeftButton:
            return
        for idx, r in self._hit_rects:
            if r.contains(e.pos()):
                self.slot_clicked.emit(idx)
                return

    def paintEvent(self, evt):
        super().paintEvent(evt)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        dirty = evt.rect()    # Performance: clip painting to the dirty rect.
        self._hit_rects = []

        w = self.width()
        h = self.height()
        row_h = 110
        gap_y = 18
        # Row band backgrounds
        for row in (0, 1):
            band = QRectF(8, 8 + row * (row_h + gap_y), w - 16, row_h)
            if not dirty.intersects(band.toRect()):
                continue
            p.setBrush(QColor(BG_CARD_DK)); p.setPen(QPen(QColor(BORDER), 1))
            p.drawRoundedRect(band, 6, 6)

            # Minute ticks (0/15/30 for row 0; 30/45/60 for row 1)
            for tick in range(0, 31, 5):
                x = band.x() + 8 + (band.width() - 16) * tick / 30.0
                p.setPen(QPen(QColor(TEXT_DIM), 1))
                p.drawLine(int(x), int(band.bottom()) - 2,
                           int(x), int(band.bottom()) + 2)
                if tick % 15 == 0:
                    label_min = tick + (30 if row == 1 else 0)
                    p.setPen(QColor(TEXT_MUTED))
                    p.setFont(mono(8, bold=False))
                    p.drawText(QRectF(x - 14, band.bottom() + 2, 28, 14),
                               Qt.AlignmentFlag.AlignCenter,
                               f"{label_min:02d}")

        # Slot blocks
        # Lay out cumulatively: each slot takes proportional width within its
        # row.  We compute total seconds for row 1 and row 2 separately based
        # on cumulative slot durations crossing the 30-min boundary.
        cumulative_s = 0
        seconds_per_pixel_row = (30 * 60) / max(1, w - 32)  # 30 min per row, 16px L+R padding
        for idx, slot in enumerate(self._slots):
            sec = self._slot_seconds(slot)
            # Decide which row this slot starts in.
            row_start = 0 if cumulative_s < 30 * 60 else 1
            offset_in_row = cumulative_s - (1800 if row_start == 1 else 0)
            row_y = 8 + row_start * (row_h + gap_y)
            block_x = 16 + offset_in_row / seconds_per_pixel_row
            block_w = max(28, sec / seconds_per_pixel_row)
            # Clip block_w so we don't run off the row.
            row_max_x = 8 + (w - 16) - 8
            if block_x + block_w > row_max_x:
                block_w = row_max_x - block_x
            block = QRect(int(block_x), int(row_y) + 14, int(block_w), row_h - 28)
            if dirty.intersects(block):
                self._draw_slot_block(p, idx, slot, block)
            self._hit_rects.append((idx, block))
            cumulative_s += sec
            # Stop drawing after row 2 fills (60 min = 3600s)
            if cumulative_s >= 3600:
                # Render a small overflow indicator if more slots remain
                if idx < len(self._slots) - 1:
                    p.setPen(QColor(AMBER))
                    p.setFont(inter(9, QFont.Weight.DemiBold))
                    p.drawText(QRectF(8, h - 22, w - 16, 16),
                               Qt.AlignmentFlag.AlignRight,
                               f"+{len(self._slots) - idx - 1} slots overflow")
                break

    def _draw_slot_block(self, p: QPainter, idx: int, slot: dict, block: QRect) -> None:
        """Paint a single slot block.  Selected slot gets a thicker border."""
        slot_type = _normalize_slot_type(slot.get("slot_type", ""))
        color = _slot_type_color(slot_type)
        rect = QRectF(block)
        is_selected = (idx == self._selected_idx)

        # Body — fill with the slot color at low alpha (selected = stronger).
        body_color = QColor(color)
        body_color.setAlphaF(0.32 if is_selected else 0.20)
        p.setBrush(body_color)
        border_color = QColor(color)
        p.setPen(QPen(border_color, 2 if is_selected else 1))
        p.drawRoundedRect(rect, 5, 5)

        # Top accent bar
        accent = QRectF(rect.x() + 1, rect.y() + 1, rect.width() - 2, 4)
        p.setBrush(QColor(color)); p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(accent, 2, 2)

        # Label (category name if Song; type label otherwise)
        cat_name = slot.get("cat_name") or slot.get("category_name") or ""
        if slot_type == "Song" and cat_name:
            label = cat_name
        elif slot_type == "Voice Track" and slot.get("ref_text"):
            label = str(slot["ref_text"])[:20]
        else:
            label = slot_type
        p.setPen(QColor(TEXT_PRI))
        p.setFont(inter(9, QFont.Weight.DemiBold))
        p.drawText(rect.adjusted(6, 8, -6, -6),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                   label)
        # Index footer
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(mono(8, bold=False))
        p.drawText(rect.adjusted(6, 0, -6, -4),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
                   f"#{idx + 1}")


class _Timeline(QFrame):
    """Center column: action toolbar (top), 2-row timeline (middle), and a
    SELECTED slot detail card (bottom amber band per Figma 59:2)."""

    add_slot          = pyqtSignal()
    ai_optimise       = pyqtSignal()
    preview           = pyqtSignal()
    validate          = pyqtSignal()
    save_clock        = pyqtSignal()
    slot_selected     = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(CENTER_W, CONTENT_H)
        self.setStyleSheet(
            f"QFrame {{ background: {BG_BASE}; "
            f"border-right: 1px solid {BORDER}; }}"
        )

        v = QVBoxLayout(self)
        v.setContentsMargins(14, 14, 14, 14); v.setSpacing(12)

        # Title block: clock name + subtitle + comments
        self._name_label = QLabel("CLOCK")
        self._name_label.setFont(inter(15, QFont.Weight.Black, letter_spacing=1.0))
        self._name_label.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        v.addWidget(self._name_label)
        self._subtitle_label = QLabel("00:00–00:00 · 0 min · 0 slots")
        self._subtitle_label.setFont(inter(10))
        self._subtitle_label.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        v.addWidget(self._subtitle_label)

        # Action toolbar
        bar = QHBoxLayout(); bar.setSpacing(8)
        for label, color, signal in [
            ("+ Add Slot",  AMBER,        self.add_slot),
            ("AI Optimise", PURPLE_LIGHT, self.ai_optimise),
            ("Preview",     CYAN_LIGHT,   self.preview),
            ("Validate",    GREEN,        self.validate),
            ("Save Clock",  GREEN_LIGHT,  self.save_clock),
        ]:
            b = QPushButton(label)
            b.setFixedHeight(30)
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.setFont(inter(10, QFont.Weight.DemiBold))
            b.setStyleSheet(
                f"QPushButton {{ background: {rgba(color, 0.16)}; "
                f"color: {color}; "
                f"border: 1px solid {rgba(color, 0.36)}; "
                f"border-radius: 5px; padding: 0 12px; }}"
                f"QPushButton:hover {{ background: {rgba(color, 0.26)}; }}"
            )
            b.clicked.connect(signal.emit)
            bar.addWidget(b)
        bar.addStretch()
        v.addLayout(bar)

        # Timeline grid (custom paint)
        self._grid = _TimelineGrid()
        self._grid.slot_clicked.connect(self.slot_selected.emit)
        v.addWidget(self._grid)

        # Selected slot detail card (amber band)
        self._detail = QFrame()
        self._detail.setFixedHeight(60)
        self._detail.setStyleSheet(
            f"QFrame {{ background: {rgba(AMBER, 0.10)}; "
            f"border: 1px solid {rgba(AMBER, 0.40)}; "
            f"border-left: 4px solid {AMBER}; "
            f"border-radius: 6px; }}"
        )
        d = QHBoxLayout(self._detail)
        d.setContentsMargins(14, 8, 14, 8); d.setSpacing(0)
        self._detail_title = QLabel("Click a slot to edit it")
        self._detail_title.setFont(inter(11, QFont.Weight.DemiBold))
        self._detail_title.setStyleSheet(f"color: {AMBER}; background: transparent;")
        d.addWidget(self._detail_title)
        v.addWidget(self._detail)

        # Slot type legend
        legend = QHBoxLayout(); legend.setSpacing(8)
        legend_lbl = QLabel("SLOT TYPES:")
        legend_lbl.setFont(inter(8, QFont.Weight.Black, letter_spacing=1.4))
        legend_lbl.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        legend.addWidget(legend_lbl)
        for t in SLOT_TYPES:
            pill = QLabel(f" {SLOT_TYPE_BADGE[t]}  {t} ")
            pill.setFixedHeight(22)
            pill.setFont(inter(9, QFont.Weight.DemiBold))
            color = _slot_type_color(t)
            pill.setStyleSheet(
                f"QLabel {{ background: {rgba(color, 0.20)}; "
                f"color: {color}; "
                f"border: 1px solid {rgba(color, 0.40)}; "
                f"border-radius: 4px; padding: 0 8px; }}"
            )
            legend.addWidget(pill)
        legend.addStretch()
        v.addLayout(legend)

        v.addStretch()

    def set_clock_meta(self, name: str, time_start: str, time_end: str,
                       slot_count: int) -> None:
        self._name_label.setText((name or "CLOCK").upper())
        ts = time_start or "00:00"; te = time_end or "00:00"
        self._subtitle_label.setText(f"{ts}–{te} · 60 min · {slot_count} slots")

    def set_slots(self, slots: list[dict], selected_idx: Optional[int]) -> None:
        self._grid.set_slots(slots, selected_idx)
        if selected_idx is None or selected_idx >= len(slots):
            self._detail_title.setText("Click a slot to edit it")
            return
        slot = slots[selected_idx]
        stype = _normalize_slot_type(slot.get("slot_type", ""))
        cat = slot.get("cat_name") or slot.get("category_name") or "—"
        energy = slot.get("energy_pref") or "Any"
        self._detail_title.setText(
            f"SELECTED: Slot {selected_idx + 1} — {stype} / {cat} / {energy} Energy"
        )


# ════════════════════════════════════════════════════════════════════════════
# SLOT EDITOR PANEL (440×778) — properties + overview + categories + AI
# ════════════════════════════════════════════════════════════════════════════

class _SlotEditor(QFrame):
    """Right column. Composed of stacked blocks; per-type form lives in a
    QStackedWidget that switches when the slot_type pill is clicked."""

    apply_clicked      = pyqtSignal(dict)   # emits {field: value} for the slot
    remove_clicked     = pyqtSignal()
    type_pill_clicked  = pyqtSignal(str)    # new slot_type
    auto_optimise      = pyqtSignal()       # stub toast (Phase E)

    def __init__(self, categories: list[dict], pallets: list[dict], parent=None):
        super().__init__(parent)
        self.setFixedSize(RIGHT_W, CONTENT_H)
        self.setStyleSheet(
            f"QFrame#se {{ background: {BG_PANEL}; "
            f"border-left: 1px solid {BORDER}; }}"
        )
        self.setObjectName("se")

        self._categories = list(categories or [])
        self._pallets    = list(pallets or [])
        self._cat_lookup = {int(c["id"]): dict(c) for c in self._categories}

        self._slot: Optional[dict] = None
        self._slot_idx: Optional[int] = None
        self._block_signals = False

        v = QVBoxLayout(self)
        v.setContentsMargins(14, 14, 14, 14); v.setSpacing(10)

        # Header
        h = QLabel("SLOT PROPERTIES")
        h.setFont(inter(10, QFont.Weight.Black, letter_spacing=1.6))
        h.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        v.addWidget(h)
        sub = QLabel("Click any slot to edit")
        sub.setFont(inter(9))
        sub.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        v.addWidget(sub)

        # Overview block
        self._overview = self._build_overview_block()
        v.addWidget(self._overview)

        # Category slots block
        self._cat_block, self._cat_rows_layout = self._build_category_block()
        v.addWidget(self._cat_block)

        # Editing block: heading + type pills + per-type stacked form
        v.addWidget(self._build_editing_heading())
        v.addWidget(self._build_type_pills_row())
        self._stack = QStackedWidget()
        self._stack.setStyleSheet("background: transparent;")
        self._page_song        = self._build_song_page()
        self._page_break       = self._build_break_page()
        self._page_jingle      = self._build_jingle_page()
        self._page_station_id  = self._build_station_id_page()
        self._page_sweeper     = self._build_sweeper_page()
        self._page_voice_track = self._build_voice_track_page()
        for w in (self._page_song, self._page_break, self._page_jingle,
                  self._page_station_id, self._page_sweeper,
                  self._page_voice_track):
            self._stack.addWidget(w)
        v.addWidget(self._stack)

        # Apply / Remove buttons
        btn_row = QHBoxLayout(); btn_row.setSpacing(8)
        self._apply_btn = QPushButton("Apply Changes")
        self._apply_btn.setFixedHeight(32)
        self._apply_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._apply_btn.setFont(inter(11, QFont.Weight.Bold))
        self._apply_btn.setStyleSheet(
            f"QPushButton {{ background: {rgba(AMBER, 0.20)}; "
            f"color: {AMBER}; "
            f"border: 1px solid {rgba(AMBER, 0.50)}; "
            f"border-radius: 6px; }}"
            f"QPushButton:hover {{ background: {rgba(AMBER, 0.30)}; }}"
        )
        self._apply_btn.clicked.connect(self._on_apply_clicked)
        btn_row.addWidget(self._apply_btn)

        self._remove_btn = QPushButton("Remove Slot")
        self._remove_btn.setFixedHeight(32)
        self._remove_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._remove_btn.setFont(inter(11, QFont.Weight.Bold))
        self._remove_btn.setStyleSheet(
            f"QPushButton {{ background: {rgba(RED, 0.18)}; "
            f"color: {RED}; "
            f"border: 1px solid {rgba(RED, 0.40)}; "
            f"border-radius: 6px; }}"
            f"QPushButton:hover {{ background: {rgba(RED, 0.28)}; }}"
        )
        self._remove_btn.clicked.connect(self.remove_clicked.emit)
        btn_row.addWidget(self._remove_btn)
        v.addLayout(btn_row)

        # AI Optimiser block (purple)
        v.addWidget(self._build_ai_optimiser_block())

        v.addStretch()

    # ── builders ──────────────────────────────────────────────────────────

    def _build_overview_block(self) -> QFrame:
        f = QFrame()
        f.setStyleSheet(
            f"QFrame {{ background: {BG_CARD}; "
            f"border: 1px solid {BORDER}; border-radius: 6px; }}"
        )
        v = QVBoxLayout(f); v.setContentsMargins(10, 8, 10, 8); v.setSpacing(6)
        title = QLabel("CLOCK OVERVIEW")
        title.setFont(inter(8, QFont.Weight.Black, letter_spacing=1.4))
        title.setStyleSheet(f"color: {CYAN_LIGHT}; background: transparent;")
        v.addWidget(title)

        row = QHBoxLayout(); row.setSpacing(0)
        self._overview_stats: dict[str, QLabel] = {}
        for label in ("Songs", "Breaks", "Jingles", "Total"):
            cell = QVBoxLayout(); cell.setSpacing(2)
            value = QLabel("0"); value.setFont(inter(15, QFont.Weight.Black))
            value.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
            value.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cap = QLabel(label); cap.setFont(inter(8, QFont.Weight.Medium, letter_spacing=0.6))
            cap.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
            cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cell.addWidget(value); cell.addWidget(cap)
            row.addLayout(cell, 1)
            self._overview_stats[label] = value
        v.addLayout(row)
        return f

    def _build_category_block(self) -> tuple[QFrame, QVBoxLayout]:
        f = QFrame()
        f.setStyleSheet(
            f"QFrame {{ background: {BG_CARD}; "
            f"border: 1px solid {BORDER}; border-radius: 6px; }}"
        )
        v = QVBoxLayout(f); v.setContentsMargins(10, 8, 10, 8); v.setSpacing(6)
        title = QLabel("CATEGORY SLOTS")
        title.setFont(inter(8, QFont.Weight.Black, letter_spacing=1.4))
        title.setStyleSheet(f"color: {AMBER}; background: transparent;")
        v.addWidget(title)
        rows = QVBoxLayout(); rows.setSpacing(4); rows.setContentsMargins(0, 0, 0, 0)
        v.addLayout(rows)
        return f, rows

    def _build_editing_heading(self) -> QLabel:
        self._editing_heading = QLabel("EDITING: (no slot selected)")
        self._editing_heading.setFont(inter(9, QFont.Weight.Black, letter_spacing=1.4))
        self._editing_heading.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent;")
        return self._editing_heading

    def _build_type_pills_row(self) -> QFrame:
        f = QFrame(); f.setStyleSheet("background: transparent;")
        h = QHBoxLayout(f); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(4)
        self._type_pills: dict[str, QPushButton] = {}
        for t in SLOT_TYPES:
            b = QPushButton(t)
            b.setFixedHeight(24)
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.setFont(inter(8, QFont.Weight.DemiBold))
            color = _slot_type_color(t)
            b.setStyleSheet(self._pill_qss(color, active=False))
            b.clicked.connect(lambda _c=False, _t=t: self._on_type_pill_clicked(_t))
            h.addWidget(b)
            self._type_pills[t] = b
        return f

    @staticmethod
    def _pill_qss(color: str, active: bool) -> str:
        if active:
            return (
                f"QPushButton {{ background: {rgba(color, 0.32)}; "
                f"color: {color}; "
                f"border: 1px solid {color}; "
                f"border-radius: 4px; padding: 0 4px; }}"
            )
        return (
            f"QPushButton {{ background: {rgba(color, 0.10)}; "
            f"color: {color}; "
            f"border: 1px solid {rgba(color, 0.30)}; "
            f"border-radius: 4px; padding: 0 4px; }}"
            f"QPushButton:hover {{ background: {rgba(color, 0.22)}; }}"
        )

    # ── per-type pages ───────────────────────────────────────────────────

    def _make_field(self, label: str) -> QVBoxLayout:
        lay = QVBoxLayout(); lay.setSpacing(2); lay.setContentsMargins(0, 4, 0, 0)
        cap = QLabel(label); cap.setFont(inter(8, QFont.Weight.Medium, letter_spacing=0.6))
        cap.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        lay.addWidget(cap)
        return lay

    def _styled_combo(self) -> QComboBox:
        c = QComboBox()
        c.setFixedHeight(28)
        c.setFont(inter(10))
        c.setStyleSheet(
            f"QComboBox {{ background: {BG_CARD_DK}; "
            f"color: {TEXT_PRI}; "
            f"border: 1px solid {BORDER}; "
            f"border-radius: 4px; padding: 0 8px; }}"
            f"QComboBox:hover {{ border-color: {rgba(CYAN, 0.40)}; }}"
            f"QComboBox::drop-down {{ border: none; width: 18px; }}"
            f"QComboBox QAbstractItemView {{ background: {BG_CARD_DK}; "
            f"color: {TEXT_PRI}; selection-background-color: {rgba(CYAN, 0.20)}; }}"
        )
        return c

    def _styled_line(self) -> QLineEdit:
        e = QLineEdit()
        e.setFixedHeight(28)
        e.setFont(inter(10))
        e.setStyleSheet(
            f"QLineEdit {{ background: {BG_CARD_DK}; "
            f"color: {TEXT_PRI}; "
            f"border: 1px solid {BORDER}; "
            f"border-radius: 4px; padding: 0 8px; }}"
            f"QLineEdit:focus {{ border-color: {rgba(CYAN, 0.60)}; }}"
        )
        return e

    def _pin_to_time_toggle(self) -> tuple[QFrame, QPushButton]:
        f = QFrame(); f.setStyleSheet(
            f"QFrame {{ background: {BG_CARD_DK}; "
            f"border: 1px solid {BORDER}; border-radius: 4px; }}"
        )
        h = QHBoxLayout(f); h.setContentsMargins(10, 4, 10, 4); h.setSpacing(0)
        lbl = QLabel("Pin to Exact Time")
        lbl.setFont(inter(9, QFont.Weight.DemiBold))
        lbl.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        h.addWidget(lbl); h.addStretch()
        btn = QPushButton("OFF"); btn.setCheckable(True); btn.setFixedSize(48, 22)
        btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn.setFont(inter(8, QFont.Weight.Bold))
        btn.setStyleSheet(
            f"QPushButton {{ background: {rgba('#ffffff', 0.06)}; "
            f"color: {TEXT_MUTED}; border: 1px solid {BORDER}; "
            f"border-radius: 11px; }}"
            f"QPushButton:checked {{ background: {rgba(GREEN, 0.30)}; "
            f"color: {GREEN_LIGHT}; border-color: {GREEN}; }}"
        )
        btn.toggled.connect(lambda on: btn.setText("ON" if on else "OFF"))
        h.addWidget(btn)
        return f, btn

    def _build_song_page(self) -> QWidget:
        page = QWidget(); page.setStyleSheet("background: transparent;")
        v = QVBoxLayout(page); v.setContentsMargins(0, 4, 0, 0); v.setSpacing(6)

        # Category
        l = self._make_field("Category"); self._sn_cat = self._styled_combo()
        self._sn_cat.addItem("(none)", userData=None)
        for c in self._categories:
            self._sn_cat.addItem(str(c.get("name") or ""), userData=int(c["id"]))
        l.addWidget(self._sn_cat); v.addLayout(l)
        # Energy
        l = self._make_field("Energy"); self._sn_energy = self._styled_combo()
        for e in ("Any", "Low", "Mid", "High"):
            self._sn_energy.addItem(e, userData=e)
        l.addWidget(self._sn_energy); v.addLayout(l)
        # Vocal
        l = self._make_field("Vocal"); self._sn_vocal = self._styled_combo()
        for e in ("Any", "Vocal", "Instrumental"):
            self._sn_vocal.addItem(e, userData=e)
        l.addWidget(self._sn_vocal); v.addLayout(l)
        # Priority
        l = self._make_field("Priority"); self._sn_prio = self._styled_combo()
        for e in ("Low", "Normal", "High"):
            self._sn_prio.addItem(e, userData=e)
        l.addWidget(self._sn_prio); v.addLayout(l)
        # Separation
        l = self._make_field("Separation"); self._sn_sep = self._styled_combo()
        for label, val in [("Use Default", None), ("15 min", 15), ("30 min", 30),
                           ("1 hour", 60), ("2 hours", 120)]:
            self._sn_sep.addItem(label, userData=val)
        l.addWidget(self._sn_sep); v.addLayout(l)
        # Fallback Category
        l = self._make_field("Fallback Category"); self._sn_fallback = self._styled_combo()
        self._sn_fallback.addItem("None (Skip slot)", userData=None)
        for c in self._categories:
            self._sn_fallback.addItem(str(c.get("name") or ""), userData=int(c["id"]))
        l.addWidget(self._sn_fallback); v.addLayout(l)
        # Pin to time
        pin_frame, self._sn_pin = self._pin_to_time_toggle()
        v.addWidget(pin_frame)
        return page

    def _build_break_page(self) -> QWidget:
        page = QWidget(); page.setStyleSheet("background: transparent;")
        v = QVBoxLayout(page); v.setContentsMargins(0, 4, 0, 0); v.setSpacing(6)
        l = self._make_field("Duration"); self._br_dur = self._styled_combo()
        for label, sec in [("15 sec", 15), ("30 sec", 30), ("60 sec", 60),
                           ("90 sec", 90), ("2 min", 120), ("3 min", 180)]:
            self._br_dur.addItem(label, userData=sec)
        l.addWidget(self._br_dur); v.addLayout(l)
        pin_frame, self._br_pin = self._pin_to_time_toggle()
        v.addWidget(pin_frame)
        v.addStretch()
        return page

    def _build_jingle_page(self) -> QWidget:
        page = QWidget(); page.setStyleSheet("background: transparent;")
        v = QVBoxLayout(page); v.setContentsMargins(0, 4, 0, 0); v.setSpacing(6)
        l = self._make_field("Pallet"); self._jn_pallet = self._styled_combo()
        self._jn_pallet.addItem("(any)", userData=None)
        for p in self._pallets:
            self._jn_pallet.addItem(str(p.get("name") or ""), userData=int(p["id"]))
        l.addWidget(self._jn_pallet); v.addLayout(l)
        pin_frame, self._jn_pin = self._pin_to_time_toggle()
        v.addWidget(pin_frame)
        v.addStretch()
        return page

    def _build_station_id_page(self) -> QWidget:
        page = QWidget(); page.setStyleSheet("background: transparent;")
        v = QVBoxLayout(page); v.setContentsMargins(0, 4, 0, 0); v.setSpacing(6)
        l = self._make_field("ID Reference"); self._st_ref = self._styled_line()
        self._st_ref.setPlaceholderText("e.g. KISS-FM-LIVE-15s")
        l.addWidget(self._st_ref); v.addLayout(l)
        v.addStretch()
        return page

    def _build_sweeper_page(self) -> QWidget:
        page = QWidget(); page.setStyleSheet("background: transparent;")
        v = QVBoxLayout(page); v.setContentsMargins(0, 4, 0, 0); v.setSpacing(6)
        l = self._make_field("Sweeper Category"); self._sw_cat = self._styled_combo()
        self._sw_cat.addItem("(any sweeper)", userData=None)
        for c in self._categories:
            self._sw_cat.addItem(str(c.get("name") or ""), userData=int(c["id"]))
        l.addWidget(self._sw_cat); v.addLayout(l)
        v.addStretch()
        return page

    def _build_voice_track_page(self) -> QWidget:
        page = QWidget(); page.setStyleSheet("background: transparent;")
        v = QVBoxLayout(page); v.setContentsMargins(0, 4, 0, 0); v.setSpacing(6)
        l = self._make_field("Label"); self._vt_label = self._styled_line()
        self._vt_label.setPlaceholderText("e.g. Show open / weather tag")
        l.addWidget(self._vt_label); v.addLayout(l)
        l = self._make_field("Duration"); self._vt_dur = self._styled_combo()
        for label, sec in [("10 sec", 10), ("20 sec", 20), ("30 sec", 30),
                           ("45 sec", 45), ("60 sec", 60)]:
            self._vt_dur.addItem(label, userData=sec)
        l.addWidget(self._vt_dur); v.addLayout(l)
        v.addStretch()
        return page

    def _build_ai_optimiser_block(self) -> QFrame:
        f = QFrame()
        f.setStyleSheet(
            f"QFrame {{ background: {rgba(PURPLE, 0.10)}; "
            f"border: 1px solid {rgba(PURPLE, 0.36)}; border-radius: 6px; }}"
        )
        v = QVBoxLayout(f); v.setContentsMargins(10, 8, 10, 8); v.setSpacing(6)
        title = QLabel("AI OPTIMISER")
        title.setFont(inter(8, QFont.Weight.Black, letter_spacing=1.4))
        title.setStyleSheet(f"color: {PURPLE_LIGHT}; background: transparent;")
        v.addWidget(title)

        self._ai_cards: dict[str, QFrame] = {}
        for label, default_color in [("Rotation", AMBER),
                                     ("Energy",   GREEN),
                                     ("Breaks",   CYAN_LIGHT)]:
            card = QFrame()
            card.setStyleSheet(
                f"QFrame {{ background: {rgba(default_color, 0.10)}; "
                f"border-left: 3px solid {default_color}; "
                f"border-radius: 3px; }}"
            )
            ch = QVBoxLayout(card); ch.setContentsMargins(8, 4, 8, 4); ch.setSpacing(0)
            head = QLabel(f"{label} —"); head.setFont(inter(9, QFont.Weight.Bold))
            head.setStyleSheet(f"color: {default_color}; background: transparent;")
            sub = QLabel("Computing…"); sub.setFont(inter(9))
            sub.setStyleSheet(f"color: {TEXT_SEC}; background: transparent;")
            ch.addWidget(head); ch.addWidget(sub)
            self._ai_cards[label] = card
            self._ai_cards[label + "_head"] = head
            self._ai_cards[label + "_sub"] = sub
            v.addWidget(card)

        opt_btn = QPushButton("Auto-Optimise This Clock")
        opt_btn.setFixedHeight(28)
        opt_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        opt_btn.setFont(inter(10, QFont.Weight.DemiBold))
        opt_btn.setStyleSheet(
            f"QPushButton {{ background: {rgba(PURPLE, 0.20)}; "
            f"color: {PURPLE_LIGHT}; "
            f"border: 1px solid {rgba(PURPLE, 0.50)}; "
            f"border-radius: 5px; }}"
            f"QPushButton:hover {{ background: {rgba(PURPLE, 0.30)}; }}"
        )
        opt_btn.clicked.connect(self.auto_optimise.emit)
        v.addWidget(opt_btn)
        return f

    # ── public API ──────────────────────────────────────────────────────

    def set_clock_meta(self, slots: list[dict]) -> None:
        """Populate the OVERVIEW + CATEGORY SLOTS blocks from the slot list."""
        n_song = sum(1 for s in slots if _normalize_slot_type(s.get("slot_type", "")) == "Song")
        n_break = sum(1 for s in slots if _normalize_slot_type(s.get("slot_type", "")) in ("Break", "Spot"))
        n_jingle = sum(1 for s in slots if _normalize_slot_type(s.get("slot_type", "")) == "Jingle")
        # Total seconds (rough estimate)
        defaults = _TimelineGrid.SLOT_DEFAULT_SECONDS
        total_s = 0
        for s in slots:
            if s.get("duration_seconds"):
                total_s += int(s["duration_seconds"])
            else:
                total_s += defaults.get(_normalize_slot_type(s.get("slot_type", "")), 60)
        self._overview_stats["Songs"].setText(str(n_song))
        self._overview_stats["Breaks"].setText(str(n_break))
        self._overview_stats["Jingles"].setText(str(n_jingle))
        self._overview_stats["Total"].setText(_fmt_minutes(total_s))

        # Category distribution — clear + rebuild
        for i in reversed(range(self._cat_rows_layout.count())):
            w = self._cat_rows_layout.itemAt(i).widget()
            if w:
                w.setParent(None); w.deleteLater()
        # Aggregate count by category_id (Song slots only)
        counts: dict[int, int] = {}
        for s in slots:
            if _normalize_slot_type(s.get("slot_type", "")) != "Song":
                continue
            cid = s.get("category_id")
            if not cid:
                continue
            counts[int(cid)] = counts.get(int(cid), 0) + 1
        if not counts:
            empty = QLabel("(no song slots assigned to a category)")
            empty.setFont(inter(9)); empty.setStyleSheet(
                f"color: {TEXT_MUTED}; background: transparent;")
            self._cat_rows_layout.addWidget(empty)
        else:
            max_n = max(counts.values()) or 1
            for cid, n in sorted(counts.items(), key=lambda kv: -kv[1]):
                cat = self._cat_lookup.get(cid, {})
                color = cat.get("color") or AMBER
                row = self._make_cat_row(str(cat.get("name") or "—"), n, max_n, color)
                self._cat_rows_layout.addWidget(row)

        # AI optimiser cards — simple deterministic copy from real numbers
        rot_status = "OK" if n_song >= 8 else "Low"
        rot_color = GREEN if rot_status == "OK" else AMBER
        self._ai_cards["Rotation_head"].setText(f"Rotation — {rot_status}")
        self._ai_cards["Rotation_head"].setStyleSheet(
            f"color: {rot_color}; background: transparent;")
        self._ai_cards["Rotation_sub"].setText(
            f"{n_song} song slots · {len(counts)} categories represented")

        n_high = sum(1 for s in slots
                     if _normalize_slot_type(s.get("slot_type", "")) == "Song"
                     and s.get("energy_pref") == "High")
        self._ai_cards["Energy_head"].setText("Energy — OK" if n_high >= 1 else "Energy — Flat")
        self._ai_cards["Energy_sub"].setText(
            f"{n_high} high-energy song slots in this clock")

        self._ai_cards["Breaks_head"].setText(
            "Breaks — Good" if n_break >= 2 else "Breaks — Sparse")
        self._ai_cards["Breaks_sub"].setText(
            f"{n_break} break/spot slots — target 3 per hour")

    def set_slot(self, slot: Optional[dict], slot_index: Optional[int] = None) -> None:
        """Bind the form to `slot` (None = no selection)."""
        self._slot = dict(slot) if slot else None
        self._slot_idx = slot_index
        self._block_signals = True
        try:
            if not slot:
                self._editing_heading.setText("EDITING: (no slot selected)")
                self._apply_btn.setEnabled(False)
                self._remove_btn.setEnabled(False)
                # Reset all type pills to inactive
                for t, b in self._type_pills.items():
                    b.setStyleSheet(self._pill_qss(_slot_type_color(t), active=False))
                return

            self._apply_btn.setEnabled(True)
            self._remove_btn.setEnabled(True)
            stype = _normalize_slot_type(slot.get("slot_type", ""))
            # Treat legacy 'Spot' as Break for editor-page selection
            page_type = "Break" if stype == "Spot" else stype
            self._editing_heading.setText(
                f"EDITING: Slot {(slot_index or 0) + 1} — {page_type}")
            self._editing_heading.setStyleSheet(
                f"color: {_slot_type_color(page_type)}; background: transparent;")

            # Type pill active state
            for t, b in self._type_pills.items():
                b.setStyleSheet(self._pill_qss(_slot_type_color(t), active=(t == page_type)))

            # Switch stacked page
            page_idx = {"Song": 0, "Break": 1, "Jingle": 2,
                        "Station ID": 3, "Sweeper": 4, "Voice Track": 5}.get(page_type, 0)
            self._stack.setCurrentIndex(page_idx)

            # Populate each page's fields with current slot data
            if page_type == "Song":
                self._select_combo_data(self._sn_cat, slot.get("category_id"))
                self._select_combo_data(self._sn_energy, slot.get("energy_pref") or "Any")
                self._select_combo_data(self._sn_vocal, slot.get("vocal_pref") or "Any")
                self._select_combo_data(self._sn_prio, slot.get("priority_pref") or "Normal")
                self._select_combo_data(self._sn_sep, slot.get("separation_override"))
                self._select_combo_data(self._sn_fallback, slot.get("fallback_category_id"))
                self._sn_pin.setChecked(bool(slot.get("pin_to_time")))
            elif page_type == "Break":
                dur = int(slot.get("duration_seconds") or 60)
                self._select_combo_data(self._br_dur, dur)
                self._br_pin.setChecked(bool(slot.get("pin_to_time")))
            elif page_type == "Jingle":
                self._select_combo_data(self._jn_pallet, slot.get("category_id"))
                self._jn_pin.setChecked(bool(slot.get("pin_to_time")))
            elif page_type == "Station ID":
                self._st_ref.setText(slot.get("ref_text") or "")
            elif page_type == "Sweeper":
                self._select_combo_data(self._sw_cat, slot.get("category_id"))
            elif page_type == "Voice Track":
                self._vt_label.setText(slot.get("ref_text") or "")
                dur = int(slot.get("duration_seconds") or 30)
                self._select_combo_data(self._vt_dur, dur)
        finally:
            self._block_signals = False

    @staticmethod
    def _select_combo_data(combo: QComboBox, value) -> None:
        for i in range(combo.count()):
            if combo.itemData(i) == value:
                combo.setCurrentIndex(i)
                return
        if combo.count() > 0:
            combo.setCurrentIndex(0)

    # ── handlers ────────────────────────────────────────────────────────

    def _on_type_pill_clicked(self, slot_type: str) -> None:
        if self._block_signals:
            return
        self.type_pill_clicked.emit(slot_type)

    def _on_apply_clicked(self) -> None:
        if self._slot is None or self._slot_idx is None:
            return
        stype = _normalize_slot_type(self._slot.get("slot_type", ""))
        page_type = "Break" if stype == "Spot" else stype
        out = dict(self._slot)
        out["slot_type"] = page_type
        if page_type == "Song":
            out["category_id"]         = self._sn_cat.currentData()
            out["energy_pref"]         = self._sn_energy.currentData() or "Any"
            out["vocal_pref"]          = self._sn_vocal.currentData() or "Any"
            out["priority_pref"]       = self._sn_prio.currentData() or "Normal"
            out["separation_override"] = self._sn_sep.currentData()
            out["fallback_category_id"] = self._sn_fallback.currentData()
            out["pin_to_time"]         = 1 if self._sn_pin.isChecked() else 0
        elif page_type == "Break":
            out["duration_seconds"] = int(self._br_dur.currentData() or 60)
            out["pin_to_time"]      = 1 if self._br_pin.isChecked() else 0
            out["is_break"]         = 1
        elif page_type == "Jingle":
            out["category_id"]  = self._jn_pallet.currentData()
            out["pin_to_time"]  = 1 if self._jn_pin.isChecked() else 0
        elif page_type == "Station ID":
            out["ref_text"]     = self._st_ref.text().strip()
        elif page_type == "Sweeper":
            out["category_id"]  = self._sw_cat.currentData()
        elif page_type == "Voice Track":
            out["ref_text"]         = self._vt_label.text().strip()
            out["duration_seconds"] = int(self._vt_dur.currentData() or 30)
        self.apply_clicked.emit(out)

    def _make_cat_row(self, name: str, n: int, max_n: int, color: str) -> QFrame:
        f = QFrame(); f.setStyleSheet("background: transparent;")
        f.setFixedHeight(20)
        h = QHBoxLayout(f); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(6)
        nm = QLabel(name); nm.setFont(inter(9, QFont.Weight.Medium))
        nm.setFixedWidth(110)
        nm.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        h.addWidget(nm)
        bar_box = QFrame(); bar_box.setFixedHeight(8)
        bar_box.setStyleSheet(
            f"QFrame {{ background: {rgba(color, 0.18)}; border-radius: 3px; }}"
        )
        bar_box.setMinimumWidth(120)
        # Inner fill
        from PyQt6.QtWidgets import QGraphicsOpacityEffect  # noqa  (kept for ref)
        # We use a child widget for fill; simpler than effects.
        inner = QFrame(bar_box)
        inner.setStyleSheet(
            f"QFrame {{ background: {color}; border-radius: 3px; }}"
        )
        # Set inner geometry deferred — use a one-shot QTimer so layout completes.
        def _resize_inner(b=bar_box, i=inner, n=n, m=max_n):
            ratio = max(0.05, n / max(1, m))
            i.setGeometry(0, 0, int(b.width() * ratio), b.height())
        QTimer.singleShot(0, _resize_inner)
        h.addWidget(bar_box, 1)
        cnt = QLabel(f"{n} slots"); cnt.setFont(mono(8, bold=False))
        cnt.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        cnt.setFixedWidth(50); cnt.setAlignment(Qt.AlignmentFlag.AlignRight)
        h.addWidget(cnt)
        return f


# ════════════════════════════════════════════════════════════════════════════
# STATUS BAR (1440×50)
# ════════════════════════════════════════════════════════════════════════════

class _StatusBar(QFrame):

    studio_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(STATUS_H)
        self.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border-top: 1px solid {BORDER}; }}"
        )
        h = QHBoxLayout(self); h.setContentsMargins(14, 8, 14, 8); h.setSpacing(8)
        for label, color in [("AUTO MODE", GREEN),
                             ("AI Active", PURPLE_LIGHT),
                             ("Log Ready", CYAN_LIGHT)]:
            pill = QLabel(label)
            pill.setFixedHeight(24)
            pill.setFont(inter(8, QFont.Weight.Black, letter_spacing=1.4))
            pill.setStyleSheet(
                f"QLabel {{ background: {rgba(color, 0.16)}; "
                f"color: {color}; "
                f"border: 1px solid {rgba(color, 0.40)}; "
                f"border-radius: 12px; padding: 0 12px; }}"
            )
            h.addWidget(pill)
        h.addStretch()
        self._clocks_label = QLabel("0 Clocks")
        self._clocks_label.setFont(inter(9, QFont.Weight.DemiBold))
        self._clocks_label.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        h.addWidget(self._clocks_label)
        version = QLabel("Clock Editor · RadioAI Studio v1.0.0")
        version.setFont(inter(9))
        version.setStyleSheet(f"color: {TEXT_DIM}; background: transparent;")
        h.addWidget(version)
        st_btn = QPushButton("Open Studio")
        st_btn.setFixedHeight(28); st_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        st_btn.setFont(inter(9, QFont.Weight.Bold))
        st_btn.setStyleSheet(
            f"QPushButton {{ background: {rgba(PURPLE, 0.18)}; "
            f"color: {PURPLE_LIGHT}; "
            f"border: 1px solid {rgba(PURPLE, 0.40)}; "
            f"border-radius: 5px; padding: 0 14px; }}"
            f"QPushButton:hover {{ background: {rgba(PURPLE, 0.28)}; }}"
        )
        st_btn.clicked.connect(self.studio_clicked.emit)
        h.addWidget(st_btn)

    def set_clock_count(self, n: int) -> None:
        self._clocks_label.setText(f"{n} Clock{'s' if n != 1 else ''}")


# ════════════════════════════════════════════════════════════════════════════
# CLOCK EDITOR — top-level (orchestrates header + sidebar + timeline + editor)
# ════════════════════════════════════════════════════════════════════════════

class ClockEditor(QWidget):

    breadcrumb_clicked = pyqtSignal(str)    # 'control_panel'
    studio_clicked     = pyqtSignal()

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self._db = db
        self.setFixedSize(WINDOW_W, WINDOW_H)
        self.setStyleSheet(f"QWidget {{ background: {BG_BASE}; }}")

        # Migrate any legacy 'Spot' rows on first mount.
        try:
            n = self._db.migrate_spot_to_break()
            if n:
                log.info(f"[clock-editor] migrated {n} 'Spot' rows → 'Break'")
        except Exception as exc:
            log.warning(f"[clock-editor] spot→break migration skipped: {exc}")

        # Categories + pallets (one read; passed to SlotEditor for dropdowns).
        try:
            categories = [dict(r) for r in self._db.get_categories()]
        except Exception:
            categories = []
        try:
            pallets = [dict(r) for r in self._db.get_pallets()]
        except Exception:
            pallets = []

        # Working state (preserved field names for F2.2 mutation tests)
        self._slots: list[dict] = []
        self._selected_slot_idx: Optional[int] = None
        self._is_dirty: bool = False
        self._current_clock_id: Optional[int] = None

        # Build widgets ────────────────────────────────────────────────────
        self._header = _Header(self)
        self._header.setGeometry(0, 0, WINDOW_W, HEADER_H)
        self._header.control_panel_clicked.connect(
            lambda: self.breadcrumb_clicked.emit("control_panel"))
        self._header.scheduling_clicked.connect(
            lambda: self.breadcrumb_clicked.emit("auto_schedule"))
        self._header.studio_clicked.connect(self.studio_clicked.emit)

        self._sidebar = _ClocksListSidebar(self)
        self._sidebar.setGeometry(LEFT_X, CONTENT_Y, LEFT_W, CONTENT_H)
        self._sidebar.clock_selected.connect(self._on_clock_selected)
        self._sidebar.new_clock_requested.connect(self._on_new_clock)
        self._sidebar.duplicate_requested.connect(self._on_duplicate_clock)
        self._sidebar.rename_requested.connect(self._on_rename_clock)
        self._sidebar.delete_requested.connect(self._on_delete_clock)

        self._timeline = _Timeline(self)
        self._timeline.setGeometry(CENTER_X, CONTENT_Y, CENTER_W, CONTENT_H)
        self._timeline.add_slot.connect(self._on_add_slot)
        self._timeline.ai_optimise.connect(self._on_auto_optimise_toast)
        self._timeline.preview.connect(self._on_preview_stub)
        self._timeline.validate.connect(self._on_validate_stub)
        self._timeline.save_clock.connect(self._on_save_clock)
        self._timeline.slot_selected.connect(self._on_slot_selected)

        self._editor = _SlotEditor(categories, pallets, self)
        self._editor.setGeometry(RIGHT_X, CONTENT_Y, RIGHT_W, CONTENT_H)
        self._editor.apply_clicked.connect(self._on_apply_slot_changes)
        self._editor.remove_clicked.connect(self._on_remove_selected_slot)
        self._editor.type_pill_clicked.connect(self._on_type_pill_clicked)
        self._editor.auto_optimise.connect(self._on_auto_optimise_toast)

        self._status = _StatusBar(self)
        self._status.setGeometry(0, WINDOW_H - STATUS_H, WINDOW_W, STATUS_H)
        self._status.studio_clicked.connect(self.studio_clicked.emit)

        # Initial population
        self._refresh_clocks_list(select_first=True)

        log.info("ClockEditor ready (Figma 59:2)")

    # ── slot factories ────────────────────────────────────────────────────

    @staticmethod
    def _new_song_slot() -> dict:
        """Default Song slot. F2.2 tests rely on this name + fields."""
        return {
            "slot_type":           "Song",
            "category_id":         None,
            "energy_pref":         "Any",
            "vocal_pref":          "Any",
            "priority_pref":       "Normal",
            "separation_override": None,
            "is_break":            0,
            "sweeper_position":    None,
            "item_id":             0,
            "fallback_category_id": None,
            "pin_to_time":         0,
            "duration_seconds":    None,
            "ref_text":            None,
        }

    @staticmethod
    def _new_slot_for_type(slot_type: str) -> dict:
        base = ClockEditor._new_song_slot()
        base["slot_type"] = slot_type
        if slot_type == "Break":
            base["is_break"] = 1
            base["duration_seconds"] = 60
        elif slot_type == "Voice Track":
            base["duration_seconds"] = 30
            base["ref_text"] = ""
        elif slot_type == "Station ID":
            base["ref_text"] = ""
        elif slot_type == "Sweeper":
            base["sweeper_position"] = "START_OF_SONG"
        return base

    # ── data load / save ──────────────────────────────────────────────────

    def _refresh_clocks_list(self, select_first: bool = False) -> None:
        try:
            clocks = [dict(r) for r in self._db.get_all_clocks()]
        except Exception as exc:
            log.warning(f"clocks list load failed: {exc}")
            clocks = []
        self._sidebar.populate(clocks, active_id=self._current_clock_id)
        self._status.set_clock_count(len(clocks))
        if select_first and clocks and self._current_clock_id is None:
            self._load_clock(int(clocks[0]["id"]))

    def _load_clock(self, clock_id: int) -> None:
        try:
            clock_row = self._db.get_clock(clock_id)
            if not clock_row:
                log.warning(f"clock id={clock_id} not found")
                return
            slot_rows = self._db.get_clock_slots(clock_id)
        except Exception as exc:
            log.warning(f"clock load {clock_id} failed: {exc}")
            return
        clock = dict(clock_row)
        self._current_clock_id = int(clock["id"])
        self._slots = [dict(r) for r in slot_rows]
        self._selected_slot_idx = None
        self._is_dirty = False

        self._timeline.set_clock_meta(
            clock.get("name") or "",
            clock.get("time_start") or "",
            clock.get("time_end") or "",
            len(self._slots),
        )
        self._timeline.set_slots(self._slots, self._selected_slot_idx)
        self._editor.set_clock_meta(self._slots)
        self._editor.set_slot(None)

        # Refresh sidebar to update active highlight + counts
        self._refresh_clocks_list(select_first=False)

        log.info(
            f"[clock-editor] loaded clock id={clock_id} "
            f"name={clock.get('name')!r} slots={len(self._slots)}")

    def _confirm_discard_if_dirty(self, action_label: str = "continue") -> bool:
        if not self._is_dirty:
            return True
        box = QMessageBox(self)
        box.setWindowTitle("Discard unsaved changes?")
        box.setText("This clock has unsaved changes.\n\n"
                    f"{action_label.capitalize()} will discard them.")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setStandardButtons(
            QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        return box.exec() == QMessageBox.StandardButton.Discard

    def _refresh_views(self) -> None:
        """Push current _slots state to timeline + editor blocks."""
        self._timeline.set_slots(self._slots, self._selected_slot_idx)
        self._editor.set_clock_meta(self._slots)
        if self._selected_slot_idx is None:
            self._editor.set_slot(None)
        else:
            slot = self._slots[self._selected_slot_idx]
            # Decorate with cat_name for the SELECTED detail card
            cid = slot.get("category_id")
            if cid:
                cat = next(
                    (dict(c) for c in self._db.get_categories()
                     if int(c["id"]) == int(cid)),
                    {})
                slot = dict(slot); slot["cat_name"] = cat.get("name") or ""
            self._editor.set_slot(slot, slot_index=self._selected_slot_idx)

    # ── event handlers ────────────────────────────────────────────────────

    def _on_clock_selected(self, clock_id: int) -> None:
        if clock_id == self._current_clock_id:
            return
        if not self._confirm_discard_if_dirty("loading another clock"):
            return
        self._load_clock(clock_id)

    def _on_new_clock(self) -> None:
        if not self._confirm_discard_if_dirty("creating a new clock"):
            return
        try:
            new_id = self._db.create_clock("New Clock")
        except Exception as exc:
            log.warning(f"create_clock failed: {exc}")
            return
        self._load_clock(new_id)

    def _on_duplicate_clock(self) -> None:
        if self._current_clock_id is None:
            return
        if not self._confirm_discard_if_dirty("duplicating this clock"):
            return
        try:
            new_id = self._db.duplicate_clock(self._current_clock_id)
        except Exception as exc:
            log.warning(f"duplicate_clock failed: {exc}")
            return
        self._load_clock(new_id)

    def _on_rename_clock(self) -> None:
        if self._current_clock_id is None:
            return
        current = self._db.get_clock(self._current_clock_id)
        old_name = (current["name"] if current else "") or ""
        new_name, ok = QInputDialog.getText(
            self, "Rename clock", "New name:", QLineEdit.EchoMode.Normal, old_name)
        if not ok or not new_name.strip():
            return
        try:
            self._db.save_clock(self._current_clock_id, {"name": new_name.strip()})
        except Exception as exc:
            log.warning(f"rename failed: {exc}")
            return
        self._load_clock(self._current_clock_id)

    def _on_delete_clock(self) -> None:
        if self._current_clock_id is None:
            return
        box = QMessageBox(self)
        box.setWindowTitle("Delete clock?")
        box.setText("Delete this clock and all its slots?\n\nThis cannot be undone.")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if box.exec() != QMessageBox.StandardButton.Yes:
            return
        try:
            self._db.delete_clock(self._current_clock_id)
        except ValueError as exc:
            QMessageBox.information(self, "Cannot delete", str(exc))
            return
        except Exception as exc:
            log.warning(f"delete_clock failed: {exc}")
            return
        self._current_clock_id = None
        self._slots = []
        self._is_dirty = False
        self._refresh_clocks_list(select_first=True)

    def _on_slot_selected(self, idx: int) -> None:
        if idx < 0 or idx >= len(self._slots):
            return
        self._selected_slot_idx = idx
        self._refresh_views()

    def _on_type_pill_clicked(self, slot_type: str) -> None:
        if self._selected_slot_idx is None:
            return
        # Replace the slot dict with a fresh one of the new type, preserving
        # any compatible fields (category_id, pin_to_time).
        old = self._slots[self._selected_slot_idx]
        new = self._new_slot_for_type(slot_type)
        for k in ("category_id", "pin_to_time"):
            if k in old and old[k] is not None:
                new[k] = old[k]
        self._slots[self._selected_slot_idx] = new
        self._is_dirty = True
        self._refresh_views()

    def _on_apply_slot_changes(self, data: dict) -> None:
        if self._selected_slot_idx is None:
            return
        self._slots[self._selected_slot_idx].update(data)
        self._is_dirty = True
        self._refresh_views()

    def _on_remove_selected_slot(self) -> None:
        self._on_delete_slot()

    # ── F2.2 mutation API (preserved names for tests) ─────────────────────

    def _on_add_slot(self) -> None:
        slot = self._new_song_slot()
        self._slots.append(slot)
        self._selected_slot_idx = len(self._slots) - 1
        self._is_dirty = True
        self._refresh_views()

    def _on_insert_slot(self) -> None:
        idx = self._selected_slot_idx if self._selected_slot_idx is not None else len(self._slots)
        slot = self._new_song_slot()
        self._slots.insert(idx, slot)
        self._selected_slot_idx = idx
        self._is_dirty = True
        self._refresh_views()

    def _on_delete_slot(self) -> None:
        if self._selected_slot_idx is None:
            return
        idx = self._selected_slot_idx
        del self._slots[idx]
        if not self._slots:
            self._selected_slot_idx = None
        else:
            self._selected_slot_idx = max(0, idx - 1)
        self._is_dirty = True
        self._refresh_views()

    def _on_move_up(self) -> None:
        if self._selected_slot_idx is None or self._selected_slot_idx == 0:
            return
        idx = self._selected_slot_idx
        self._slots[idx - 1], self._slots[idx] = self._slots[idx], self._slots[idx - 1]
        self._selected_slot_idx = idx - 1
        self._is_dirty = True
        self._refresh_views()

    def _on_move_down(self) -> None:
        if self._selected_slot_idx is None or self._selected_slot_idx >= len(self._slots) - 1:
            return
        idx = self._selected_slot_idx
        self._slots[idx + 1], self._slots[idx] = self._slots[idx], self._slots[idx + 1]
        self._selected_slot_idx = idx + 1
        self._is_dirty = True
        self._refresh_views()

    # ── save / stubs ─────────────────────────────────────────────────────

    def _on_save_clock(self) -> None:
        if self._current_clock_id is None:
            return
        try:
            self._db.save_clock_slots(self._current_clock_id, self._slots)
        except Exception as exc:
            log.warning(f"save_clock_slots failed: {exc}")
            QMessageBox.warning(self, "Save failed", str(exc))
            return
        self._is_dirty = False
        log.info(f"[clock-editor] saved clock id={self._current_clock_id} "
                 f"slots={len(self._slots)}")
        self._refresh_clocks_list(select_first=False)

    def _on_auto_optimise_toast(self) -> None:
        QMessageBox.information(
            self, "Auto-Optimise",
            "Auto-Optimise is wired to the Anthropic Claude API.\n\n"
            "Phase E AI integration — coming after Phase F polish.")

    def _on_preview_stub(self) -> None:
        QMessageBox.information(
            self, "Preview",
            "Clock Preview — Phase F polish.\n\nWill play through the clock "
            "in the Studio deck without committing it to the broadcast log.")

    def _on_validate_stub(self) -> None:
        # Cheap deterministic check: at least 6 song slots and 1 break.
        n_song = sum(1 for s in self._slots
                     if _normalize_slot_type(s.get("slot_type", "")) == "Song")
        n_break = sum(1 for s in self._slots
                      if _normalize_slot_type(s.get("slot_type", "")) in ("Break", "Spot"))
        problems = []
        if n_song < 6:
            problems.append(f"only {n_song} song slot(s) — target 8–14")
        if n_break < 1:
            problems.append("no breaks scheduled")
        if not problems:
            QMessageBox.information(
                self, "Validate",
                "Clock looks healthy.\n\n"
                f"{n_song} songs · {n_break} breaks · {len(self._slots)} total slots.")
        else:
            QMessageBox.warning(
                self, "Validate — issues found",
                "This clock may not air well:\n\n• " + "\n• ".join(problems))
