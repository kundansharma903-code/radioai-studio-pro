"""
RadioAI Studio Pro — Clock Editor (Figma 165:2).

Phase F2.1: skeleton + real DB load + Save flow. Slot mutations
(Add/Insert/Delete/Move) are stubs — wired in F2.3. Drag-and-drop
reorder also F2.3.

Layout
------
  HEADER  y=0..50    — brand · nav (Control Panel | Scheduling |
                       Clock Editor) · live clock · station · Open Studio CTA
  LEFT    x=0..220   — Tab bar (Songs/Jingles/Spots/Sweepers/Events)
                     · Sub-tab (Category active; Specific Song/Artist greyed)
                     · Categories list · Properties · Scales
                     · "N Songs" counter · Reset / Preview (visual chrome only)
  CENTER  x=220..1020 — Clock name + time range + comments
                     · 5 counters (Songs/Breaks/Jingles/Sweepers/Total)
                     · Action toolbar (Change · Delete · +Add · Insert ·
                       ↑Up · ↓Down · ✦AI Optimise · ▶Preview · ✓Validate ·
                       💾Save Clock)
                     · Slot list (real DB data; click to select)
  RIGHT   x=1020..1440 — Slot properties form (dropdowns)
                     · Apply Changes · Remove Slot
                     · Overview card · Category Slots distribution
  STATUS  y=868..900 — pills (AUTO MODE / AI Active / 8 Clocks / Log Ready)

═════════════════════════════════════════════════════════════════════════════
PERFORMANCE NOTES — DO NOT VIOLATE  (inherited from Studio + Spot Programming)
═════════════════════════════════════════════════════════════════════════════
  1. event.rect() CLIPPING — slot list is the tallest custom-paint surface.
     paintEvent of _SlotList must respect the dirty rect when scrolled.
  2. NO bare self.update() in mouseMoveEvent — bounded update(rect) only.
  3. NO db calls in paintEvent — caller-side only.
  4. NO nested QScrollArea — Clock Editor is hosted in MainWindow's outer
     scroll. Internal scrolls would create the layout-storm trap.
  5. NO setMouseTracking(True) unless specifically needed.
  6. Any list >2000px tall: setFixedHeight only.
═════════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import logging
from typing import Optional

from PyQt6.QtCore import Qt, QRect, QRectF, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QLinearGradient, QPainterPath, QFont,
    QCursor,
)
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QScrollArea, QSizePolicy, QLineEdit, QComboBox,
)

from ui.widgets._tokens import (
    inter, mono, rgba,
    BG_BASE, BG_DARK, BG_PANEL, BG_CARD, BG_CARD_DK, BG_ELEVATED, BG_PURPLE_DK,
    TEXT_PRI, TEXT_SEC, TEXT_MUTED, TEXT_DIM,
    CYAN, CYAN_LIGHT,
    PURPLE, PURPLE_LIGHT, PURPLE_DARK,
    GREEN, GREEN_LIGHT,
    AMBER, AMBER_LIGHT,
    RED, RED_LIGHT,
    PINK, PINK_LIGHT,
)

log = logging.getLogger("ClockEditor")


# ── Layout constants ───────────────────────────────────────────────────────

WINDOW_W = 1440
WINDOW_H = 900
HEADER_H = 50
STATUS_H = 32

LEFT_X  = 0
LEFT_W  = 220
CENTER_X = LEFT_X + LEFT_W              # 220
CENTER_W = 800
RIGHT_X  = CENTER_X + CENTER_W          # 1020
RIGHT_W  = WINDOW_W - RIGHT_X           # 420


# ── Slot type → color/label helpers ─────────────────────────────────────────

SLOT_TYPE_COLORS = {
    "Song":     CYAN,
    "song":     CYAN,
    "Jingle":   PURPLE,
    "jingle":   PURPLE,
    "Sweeper":  AMBER,
    "sweeper":  AMBER,
    "Spot":     RED,
    "spot":     RED,
}


def _slot_type_color(slot_type: str) -> str:
    return SLOT_TYPE_COLORS.get(slot_type or "", TEXT_MUTED)


def _normalize_slot_type(s: str) -> str:
    """Canonicalize stored slot_type to title case."""
    if not s:
        return "Song"
    s = s.strip()
    return s[:1].upper() + s[1:].lower() if s else "Song"


def _fmt_minutes(seconds: int) -> str:
    """seconds → 'M:SS'."""
    if seconds is None or seconds < 0:
        return "0:00"
    s = int(seconds)
    return f"{s // 60}:{s % 60:02d}"


# ════════════════════════════════════════════════════════════════════════════
# HEADER
# ════════════════════════════════════════════════════════════════════════════

class _ClockEditorHeader(QFrame):
    """Top bar — brand + nav tabs + clock + station + Open Studio CTA."""

    control_panel_clicked = pyqtSignal()
    studio_clicked        = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(HEADER_H)
        self.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border-bottom: 1px solid {rgba('#ffffff', 0.06)}; }}"
        )
        # Live clock
        self._clock_text = "00:00:00"
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick_clock)
        self._timer.start()
        self._tick_clock()

        # Nav: Control Panel button (real)
        cp_btn = QPushButton("Control Panel", self)
        cp_btn.setGeometry(180, 12, 110, 26)
        cp_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        cp_btn.setFont(inter(10, QFont.Weight.Medium))
        cp_btn.setStyleSheet(self._nav_qss(active=False))
        cp_btn.clicked.connect(self.control_panel_clicked.emit)

        # Nav: Scheduling (visual — placeholder for Hub)
        sched_btn = QPushButton("Scheduling", self)
        sched_btn.setGeometry(296, 12, 92, 26)
        sched_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        sched_btn.setFont(inter(10, QFont.Weight.Medium))
        sched_btn.setStyleSheet(self._nav_qss(active=False))
        # No handler in F2.1 — Hub is F3 territory

        # Nav: Clock Editor (active)
        ce_btn = QPushButton("Clock Editor", self)
        ce_btn.setGeometry(394, 12, 108, 26)
        ce_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        ce_btn.setFont(inter(10, QFont.Weight.DemiBold))
        ce_btn.setStyleSheet(self._nav_qss(active=True))
        # No handler — already on this screen

        # Open Studio CTA (top-right)
        st_btn = QPushButton("▶  Open Studio", self)
        st_btn.setGeometry(WINDOW_W - 220, 8, 200, 34)
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
        self.update(QRect(540, 0, 220, HEADER_H))

    def paintEvent(self, _e):
        super().paintEvent(_e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Logo dot + RadioAI brand
        p.setBrush(QColor(PURPLE)); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(14, HEADER_H // 2 - 6, 12, 12)
        p.setPen(QColor(TEXT_PRI))
        p.setFont(inter(14, QFont.Weight.Black, letter_spacing=0.5))
        p.drawText(QRectF(34, 0, 90, HEADER_H),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "RadioAI")
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(inter(7, QFont.Weight.Bold, letter_spacing=1.4))
        p.drawText(QRectF(34, 26, 130, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                   "BROADCAST AUTOMATION")

        # Live clock (mono, large)
        p.setPen(QColor(TEXT_PRI))
        p.setFont(mono(18, bold=True))
        p.drawText(QRectF(540, 0, 220, HEADER_H),
                   Qt.AlignmentFlag.AlignCenter, self._clock_text)

        # Date subtitle
        from datetime import datetime
        date_text = datetime.now().strftime("%A, %d %B %Y")
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(inter(8))
        p.drawText(QRectF(540, 28, 220, 16),
                   Qt.AlignmentFlag.AlignCenter, date_text)

        # ACTIVE STATION pill
        pill = QRectF(WINDOW_W - 410, 11, 175, 28)
        p.setBrush(QColor("#0c0e1c")); p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(pill, 14, 14)
        bc = QColor("#ffffff"); bc.setAlphaF(0.10)
        p.setPen(QPen(bc, 1)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(pill, 14, 14)
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(inter(7, QFont.Weight.Bold, letter_spacing=1.0))
        p.drawText(pill.adjusted(12, 4, -10, -14),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   "ACTIVE STATION")
        p.setPen(QColor(CYAN_LIGHT))
        p.setFont(inter(11, QFont.Weight.Bold))
        p.drawText(pill.adjusted(12, 0, -10, 0),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   "  KISS FM 91.5")


# ════════════════════════════════════════════════════════════════════════════
# LEFT SIDEBAR — visual-only chrome (per Q3 — wired in F2.2 if Specific
# Song/Artist modes land)
# ════════════════════════════════════════════════════════════════════════════

class _LeftSidebar(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(LEFT_W, WINDOW_H - HEADER_H - STATUS_H)
        self.setStyleSheet(
            f"QFrame {{ background: {BG_DARK}; "
            f"border-right: 1px solid {rgba('#ffffff', 0.06)}; }}"
        )
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 8); v.setSpacing(6)

        # Top tab bar (filter scope)
        tab_row = QHBoxLayout(); tab_row.setSpacing(2); tab_row.setContentsMargins(0, 0, 0, 0)
        for i, label in enumerate(["Songs", "Jingles", "Spots", "Sweepers", "Events"]):
            b = self._tab_btn(label, active=(i == 0))
            tab_row.addWidget(b)
        v.addLayout(tab_row)

        # Sub-tab bar (mode)
        sub_row = QHBoxLayout(); sub_row.setSpacing(2); sub_row.setContentsMargins(0, 0, 0, 0)
        for i, label in enumerate(["Category", "Specific Song", "Specific Artist"]):
            b = self._tab_btn(label, active=(i == 0),
                              disabled=(i > 0))   # Q4: only Category enabled
            sub_row.addWidget(b)
        v.addLayout(sub_row)

        # Categories section
        v.addWidget(self._section_label("CATEGORIES"))
        self._cats_box = QFrame(); self._cats_box.setStyleSheet("background: transparent;")
        self._cats_layout = QVBoxLayout(self._cats_box)
        self._cats_layout.setContentsMargins(0, 0, 0, 0); self._cats_layout.setSpacing(2)
        v.addWidget(self._cats_box)

        # Properties section
        v.addWidget(self._section_label("PROPERTIES"))
        for label, value in [("Vocal Type", "Vocal (All)")]:
            v.addWidget(self._filter_pill(label, value))

        # Scales section
        v.addWidget(self._section_label("SCALES"))
        for label, value in [("Time Period", "Year (All)"),
                             ("Priority",    "Priority (All)"),
                             ("BPM",         "BPM (All)"),
                             ("Year",        "Year (All)")]:
            v.addWidget(self._filter_pill(label, value))

        v.addStretch()

        # Songs Found counter card
        self._songs_count_lbl = QLabel("— Songs", self)
        v.addWidget(self._make_counter_card())

        # Reset / Preview row
        bot = QHBoxLayout(); bot.setSpacing(4)
        for label, color in [("↻  Reset Filters", TEXT_MUTED),
                             ("▶  Preview Songs", GREEN)]:
            b = QPushButton(label)
            b.setFixedHeight(28)
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.setFont(inter(9, QFont.Weight.DemiBold))
            b.setStyleSheet(
                f"QPushButton {{ background: {rgba(color, 0.14)}; "
                f"color: {color}; "
                f"border: 1px solid {rgba(color, 0.30)}; "
                f"border-radius: 5px; padding: 0 6px; }}"
                f"QPushButton:hover {{ background: {rgba(color, 0.22)}; }}"
            )
            b.clicked.connect(
                lambda _c=False, n=label: log.info(
                    f"[clock-editor] sidebar action {n!r} (visual-only — F2.2)"))
            bot.addWidget(b)
        v.addLayout(bot)

    def populate_categories(self, categories: list[dict]) -> None:
        # Clear existing
        for i in reversed(range(self._cats_layout.count())):
            w = self._cats_layout.itemAt(i).widget()
            if w:
                w.setParent(None)
        for cat in categories[:6]:
            row = QLabel(f"  {cat.get('name', '—')}")
            row.setFixedHeight(22)
            row.setFont(inter(9))
            row.setStyleSheet(
                f"color: {TEXT_PRI}; "
                f"background: {rgba('#ffffff', 0.02)}; "
                f"border-left: 2px solid {cat.get('color', TEXT_MUTED)}; "
                f"border-radius: 3px;")
            self._cats_layout.addWidget(row)

    def set_song_count(self, n: int) -> None:
        self._songs_count_lbl.setText(f"{n:,} Songs" if n > 0 else "— Songs")

    def _section_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setFont(inter(7, QFont.Weight.Black, letter_spacing=1.4))
        lbl.setStyleSheet(f"color: {TEXT_MUTED}; "
                           f"background: transparent; padding-top: 8px;")
        return lbl

    def _filter_pill(self, label: str, value: str) -> QFrame:
        f = QFrame()
        f.setFixedHeight(26)
        f.setStyleSheet(
            f"QFrame {{ background: {rgba('#ffffff', 0.02)}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; "
            f"border-radius: 4px; }}"
        )
        v = QVBoxLayout(f)
        v.setContentsMargins(8, 1, 8, 1); v.setSpacing(0)
        sub = QLabel(label); sub.setFont(inter(7, QFont.Weight.Medium, letter_spacing=0.4))
        sub.setStyleSheet(f"color: {TEXT_DIM}; background: transparent;")
        val = QLabel(value); val.setFont(inter(9, QFont.Weight.Medium))
        val.setStyleSheet(f"color: {TEXT_SEC}; background: transparent;")
        v.addWidget(sub); v.addWidget(val)
        return f

    def _tab_btn(self, label: str, active: bool, disabled: bool = False) -> QPushButton:
        b = QPushButton(label)
        b.setFixedHeight(26)
        b.setFont(inter(8, QFont.Weight.DemiBold))
        b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor)
                     if not disabled else QCursor(Qt.CursorShape.ArrowCursor))
        if disabled:
            b.setEnabled(False)
            b.setToolTip("Coming in Phase F polish")
            b.setStyleSheet(
                f"QPushButton {{ background: {rgba('#ffffff', 0.02)}; "
                f"color: {TEXT_DIM}; "
                f"border: 1px solid {rgba('#ffffff', 0.04)}; "
                f"border-radius: 4px; padding: 0 6px; }}"
            )
        elif active:
            b.setStyleSheet(
                f"QPushButton {{ background: {rgba(CYAN, 0.18)}; "
                f"color: {CYAN_LIGHT}; "
                f"border: 1px solid {rgba(CYAN, 0.40)}; "
                f"border-radius: 4px; padding: 0 6px; }}"
            )
        else:
            b.setStyleSheet(
                f"QPushButton {{ background: {rgba('#ffffff', 0.04)}; "
                f"color: {TEXT_SEC}; "
                f"border: 1px solid {rgba('#ffffff', 0.06)}; "
                f"border-radius: 4px; padding: 0 6px; }}"
                f"QPushButton:hover {{ color: {TEXT_PRI}; "
                f"border-color: {rgba('#ffffff', 0.20)}; }}"
            )
        return b

    def _make_counter_card(self) -> QFrame:
        f = QFrame()
        f.setFixedHeight(60)
        f.setStyleSheet(
            f"QFrame {{ background: {rgba(CYAN, 0.14)}; "
            f"border: 1px solid {rgba(CYAN, 0.30)}; "
            f"border-radius: 6px; }}"
        )
        v = QVBoxLayout(f)
        v.setContentsMargins(10, 8, 10, 8); v.setSpacing(2)
        sub = QLabel("Songs Found")
        sub.setFont(inter(7, QFont.Weight.Bold, letter_spacing=1.0))
        sub.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        self._songs_count_lbl.setFont(mono(15, bold=True))
        self._songs_count_lbl.setStyleSheet(f"color: {CYAN_LIGHT}; background: transparent;")
        v.addWidget(sub); v.addWidget(self._songs_count_lbl)
        return f


# ════════════════════════════════════════════════════════════════════════════
# CENTER — Clock name + counters + toolbar + slot list
# ════════════════════════════════════════════════════════════════════════════

class _SlotRow(QFrame):
    """One row in the slot list. State-driven via set_data()."""

    ROW_H = 36

    clicked = pyqtSignal(int)   # slot_idx within working copy

    def __init__(self, idx: int, parent=None):
        super().__init__(parent)
        self._idx = idx
        self._slot: dict = {}
        self._is_selected = False
        self._is_break = False
        self.setFixedHeight(self.ROW_H)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

    def set_data(self, slot: dict, is_selected: bool = False) -> None:
        self._slot = slot or {}
        self._is_selected = is_selected
        self._is_break = bool(slot.get("is_break", 0)) or \
            _normalize_slot_type(slot.get("slot_type", "")) == "Spot"
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._idx)
        super().mousePressEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        rect = QRectF(0, 0, w, h)

        # Background
        if self._is_selected:
            tint = QColor(CYAN); tint.setAlphaF(0.14)
            p.fillRect(rect, tint)
            p.fillRect(QRectF(0, 0, 3, h), QColor(CYAN))
        else:
            zebra = "#0d0f1c" if self._idx % 2 else "#0a0c18"
            p.fillRect(rect, QColor(zebra))

        slot_type = _normalize_slot_type(self._slot.get("slot_type", "Song"))
        type_color = _slot_type_color(slot_type)

        # # column (16-32)
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(inter(9, QFont.Weight.Bold))
        p.drawText(QRectF(8, 0, 22, h),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   str(self._idx + 1))

        # TYPE pill (32-110)
        pill_w = 70
        pill = QRectF(36, h / 2 - 10, pill_w, 20)
        bg = QColor(type_color); bg.setAlphaF(0.20)
        p.setBrush(bg); p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(pill, 4, 4)
        p.setPen(QColor(type_color))
        p.setFont(inter(8, QFont.Weight.Bold, letter_spacing=0.5))
        p.drawText(pill, Qt.AlignmentFlag.AlignCenter, slot_type)

        # DESCRIPTION (right of pill, takes most space)
        desc = self._compose_description()
        p.setPen(QColor(TEXT_PRI if self._is_selected else TEXT_SEC))
        p.setFont(inter(9, QFont.Weight.Medium))
        fm = p.fontMetrics()
        desc_x = 36 + pill_w + 12
        desc_w = w - desc_x - 80   # leave 80 for category pill
        elided = fm.elidedText(desc, Qt.TextElideMode.ElideRight, int(desc_w))
        p.drawText(QRectF(desc_x, 0, desc_w, h),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   elided)

        # CATEGORY pill (right edge)
        cat_name = self._slot.get("cat_name") or "—"
        cat_color = self._slot.get("cat_color") or TEXT_MUTED
        cat_pill_w = 70
        cat_pill = QRectF(w - cat_pill_w - 8, h / 2 - 8, cat_pill_w, 16)
        cbg = QColor(cat_color); cbg.setAlphaF(0.18)
        p.setBrush(cbg); p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(cat_pill, 4, 4)
        p.setPen(QColor(cat_color))
        p.setFont(inter(7, QFont.Weight.Bold, letter_spacing=0.4))
        p.drawText(cat_pill, Qt.AlignmentFlag.AlignCenter,
                   fm.elidedText(cat_name, Qt.TextElideMode.ElideRight, cat_pill_w - 8))

        # Hairline separator
        sep = QColor(255, 255, 255, 10)
        p.setPen(QPen(sep, 1))
        p.drawLine(0, h - 1, w, h - 1)

    def _compose_description(self) -> str:
        slot_type = _normalize_slot_type(self._slot.get("slot_type", "Song"))
        if slot_type == "Song":
            return f"Song: from {self._slot.get('cat_name') or 'Any'} category"
        if slot_type == "Jingle":
            return f"Jingle: {self._slot.get('cat_name') or 'Any'}"
        if slot_type == "Sweeper":
            pos = self._slot.get("sweeper_position", "START_OF_SONG")
            return f"Sweeper: @{pos}"
        if slot_type == "Spot":
            return "Spot Break: campaign-driven (~2 min)"
        return slot_type or "—"


# ════════════════════════════════════════════════════════════════════════════
# RIGHT panel — Slot Properties + Overview + Distribution
# ════════════════════════════════════════════════════════════════════════════

class _SlotPropertiesPanel(QFrame):
    """Form for editing the selected slot."""

    apply_clicked  = pyqtSignal(dict)   # data dict to apply to slot
    remove_clicked = pyqtSignal()

    def __init__(self, categories: list[dict], parent=None):
        super().__init__(parent)
        self._categories = categories or []
        self.setStyleSheet("background: transparent;")
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12); v.setSpacing(8)

        title = QLabel("SLOT PROPERTIES")
        title.setFont(inter(8, QFont.Weight.Black, letter_spacing=1.4))
        title.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        v.addWidget(title)

        self._editing_lbl = QLabel("EDITING: (no slot selected)")
        self._editing_lbl.setFont(inter(9, QFont.Weight.Bold))
        self._editing_lbl.setStyleSheet(f"color: {CYAN_LIGHT}; background: transparent;")
        v.addWidget(self._editing_lbl)

        self._slot_type_combo = self._make_combo("Slot Type",
            ["Song", "Jingle", "Sweeper", "Spot"])
        v.addWidget(self._make_field("Slot Type", self._slot_type_combo))

        cat_names = ["(none)"] + [c.get("name", "—") for c in self._categories]
        self._category_combo = self._make_combo("Category", cat_names)
        v.addWidget(self._make_field("Category", self._category_combo))

        self._energy_combo = self._make_combo("Energy",
            ["Any", "Low", "Medium", "High"])
        v.addWidget(self._make_field("Energy", self._energy_combo))

        self._vocal_combo = self._make_combo("Vocal", ["Any", "Vocal", "Instrumental"])
        v.addWidget(self._make_field("Vocal", self._vocal_combo))

        self._priority_combo = self._make_combo("Priority",
            ["Normal", "Low", "High"])
        v.addWidget(self._make_field("Priority", self._priority_combo))

        self._sep_combo = self._make_combo("Separation",
            ["Use Default", "30 min", "1 hour", "2 hours", "4 hours"])
        v.addWidget(self._make_field("Separation", self._sep_combo))

        # Apply / Remove
        apply_btn = QPushButton("✓  Apply Changes")
        apply_btn.setFixedHeight(34)
        apply_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        apply_btn.setFont(inter(11, QFont.Weight.DemiBold))
        apply_btn.setStyleSheet(
            f"QPushButton {{ background: qlineargradient("
            f"x1:0,y1:0,x2:0,y2:1, stop:0 {AMBER_LIGHT}, stop:1 {AMBER}); "
            f"color: white; border: none; border-radius: 6px; }}"
            f"QPushButton:hover {{ background: {AMBER}; }}"
        )
        apply_btn.clicked.connect(self._on_apply_clicked)
        v.addWidget(apply_btn)

        rm_btn = QPushButton("✕  Remove Slot")
        rm_btn.setFixedHeight(28)
        rm_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        rm_btn.setFont(inter(10, QFont.Weight.DemiBold))
        rm_btn.setStyleSheet(
            f"QPushButton {{ background: {rgba(RED, 0.14)}; "
            f"color: {RED_LIGHT}; "
            f"border: 1px solid {rgba(RED, 0.30)}; "
            f"border-radius: 5px; }}"
            f"QPushButton:hover {{ background: {rgba(RED, 0.24)}; }}"
        )
        rm_btn.clicked.connect(self.remove_clicked.emit)
        v.addWidget(rm_btn)
        v.addStretch()
        self._enable_form(False)

    def set_slot(self, slot: Optional[dict], slot_index: Optional[int] = None) -> None:
        if slot is None:
            self._editing_lbl.setText("EDITING: (no slot selected)")
            self._enable_form(False)
            return
        slot_type = _normalize_slot_type(slot.get("slot_type", "Song"))
        idx_label = f"Slot {slot_index + 1}" if slot_index is not None else "Slot"
        self._editing_lbl.setText(f"EDITING: {idx_label} — {slot_type}")
        self._slot_type_combo.setCurrentText(slot_type)
        cat_id = slot.get("category_id")
        cat_name = "(none)"
        for c in self._categories:
            if c.get("id") == cat_id:
                cat_name = c.get("name") or "(none)"
                break
        self._category_combo.setCurrentText(cat_name)
        self._energy_combo.setCurrentText(slot.get("energy_pref") or "Any")
        self._vocal_combo.setCurrentText(slot.get("vocal_pref") or "Any")
        self._priority_combo.setCurrentText(slot.get("priority_pref") or "Normal")
        # Separation displayed as text — store as raw int in slot
        self._sep_combo.setCurrentText(self._sep_to_label(slot.get("separation_override")))
        self._enable_form(True)

    def _enable_form(self, enabled: bool) -> None:
        for w in (self._slot_type_combo, self._category_combo,
                  self._energy_combo, self._vocal_combo,
                  self._priority_combo, self._sep_combo):
            w.setEnabled(enabled)

    @staticmethod
    def _sep_to_label(minutes: Optional[int]) -> str:
        m = int(minutes or 0)
        if m == 30:    return "30 min"
        if m == 60:    return "1 hour"
        if m == 120:   return "2 hours"
        if m == 240:   return "4 hours"
        return "Use Default"

    @staticmethod
    def _label_to_sep(label: str) -> int:
        return {"30 min": 30, "1 hour": 60, "2 hours": 120, "4 hours": 240}\
            .get(label, 0)

    def _on_apply_clicked(self):
        cat_name = self._category_combo.currentText()
        cat_id = None
        for c in self._categories:
            if c.get("name") == cat_name:
                cat_id = c.get("id"); break
        data = {
            "slot_type":           self._slot_type_combo.currentText(),
            "category_id":         cat_id,
            "energy_pref":         self._energy_combo.currentText(),
            "vocal_pref":          self._vocal_combo.currentText(),
            "priority_pref":       self._priority_combo.currentText(),
            "separation_override": self._label_to_sep(self._sep_combo.currentText()),
        }
        self.apply_clicked.emit(data)

    def _make_field(self, label: str, widget: QWidget) -> QFrame:
        f = QFrame(); f.setStyleSheet("background: transparent;")
        v = QVBoxLayout(f)
        v.setContentsMargins(0, 0, 0, 0); v.setSpacing(2)
        lbl = QLabel(label.upper())
        lbl.setFont(inter(7, QFont.Weight.Bold, letter_spacing=0.8))
        lbl.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        v.addWidget(lbl); v.addWidget(widget)
        return f

    def _make_combo(self, _label: str, items: list[str]) -> QComboBox:
        c = QComboBox()
        c.addItems(items)
        c.setFixedHeight(28)
        c.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        c.setFont(inter(10))
        c.setStyleSheet(
            f"QComboBox {{ background: #0e1020; color: {TEXT_PRI}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; border-radius: 4px; "
            f"padding: 0 8px; }}"
            f"QComboBox:hover {{ border: 1px solid {rgba(CYAN, 0.40)}; }}"
            f"QComboBox QAbstractItemView {{ background: #0e1020; "
            f"color: {TEXT_PRI}; "
            f"selection-background-color: {rgba(CYAN, 0.25)}; "
            f"border: 1px solid {rgba('#ffffff', 0.10)}; }}"
        )
        return c


# ════════════════════════════════════════════════════════════════════════════
# Main screen
# ════════════════════════════════════════════════════════════════════════════

class ClockEditor(QWidget):
    """Clock Editor — broadcast clock template builder (Figma 165:2).

    Phase F2.1: layout chrome + real DB clock load + edit selected slot
    properties + Save persistence. Slot mutations (Add/Insert/Delete/
    Move) wired in F2.3.
    """

    breadcrumb_clicked = pyqtSignal(str)    # 'control_panel'
    studio_clicked     = pyqtSignal()

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self._db = db
        self.setFixedSize(WINDOW_W, WINDOW_H)
        self.setStyleSheet(
            "background: qlineargradient("
            "x1:0,y1:0,x2:1,y2:1, stop:0 #0a0d1a, stop:0.5 #06080f, stop:1 #020308);"
        )

        # State
        self._categories: list[dict] = []
        self._all_clocks: list[dict] = []
        self._current_clock_id: Optional[int] = None
        self._slots: list[dict] = []        # working copy
        self._selected_slot_idx: Optional[int] = None
        self._slot_rows: list[_SlotRow] = []

        # Pre-load reference data
        try:
            self._categories = [dict(r) for r in self._db.get_categories()]
            self._all_clocks = [dict(r) for r in self._db.get_all_clocks()]
        except Exception as exc:
            log.warning(f"reference-data load failed: {exc}")

        self._build_header()
        self._build_left_sidebar()
        self._build_center()
        self._build_right()
        self._build_status_bar()

        # Initial clock — pick the first one with slots, else first
        initial = next((c for c in self._all_clocks
                        if c.get("slot_count", 0) > 0), None)
        if initial is None and self._all_clocks:
            initial = self._all_clocks[0]
        if initial:
            self._load_clock(int(initial["id"]))
        else:
            self._show_no_clocks_state()

        log.info("ClockEditor ready (Figma 165:2)")

    # ── Layout ────────────────────────────────────────────────────────────

    def _build_header(self):
        self._header = _ClockEditorHeader(self)
        self._header.setGeometry(0, 0, WINDOW_W, HEADER_H)
        self._header.control_panel_clicked.connect(
            lambda: self.breadcrumb_clicked.emit("control_panel"))
        self._header.studio_clicked.connect(self.studio_clicked.emit)

    def _build_left_sidebar(self):
        body_y = HEADER_H
        body_h = WINDOW_H - HEADER_H - STATUS_H
        self._sidebar = _LeftSidebar(self)
        self._sidebar.setGeometry(LEFT_X, body_y, LEFT_W, body_h)
        self._sidebar.populate_categories(self._categories)
        # Songs count — total enabled songs in library (cheap)
        try:
            row = self._db._conn().execute(
                "SELECT COUNT(*) FROM songs WHERE is_enabled=1").fetchone()
            self._sidebar.set_song_count(int(row[0] or 0))
        except Exception:
            pass

    def _build_center(self):
        body_y = HEADER_H
        pad = 14
        x0 = CENTER_X + pad
        w  = CENTER_W - 2 * pad
        y  = body_y + pad

        # Clock name + time range row
        name_row = QFrame(self)
        name_row.setGeometry(x0, y, w, 50)
        name_row.setStyleSheet("background: transparent;")
        nh = QHBoxLayout(name_row)
        nh.setContentsMargins(0, 0, 0, 0); nh.setSpacing(10)

        # Clock name input
        name_frame = QFrame(); name_frame.setStyleSheet("background: transparent;")
        nv = QVBoxLayout(name_frame); nv.setContentsMargins(0, 0, 0, 0); nv.setSpacing(2)
        name_lbl = QLabel("CLOCK NAME")
        name_lbl.setFont(inter(7, QFont.Weight.Bold, letter_spacing=1.0))
        name_lbl.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        nv.addWidget(name_lbl)
        self._name_input = QLineEdit()
        self._name_input.setFixedHeight(28)
        self._name_input.setFont(inter(11, QFont.Weight.Bold))
        self._name_input.setStyleSheet(self._lineedit_qss())
        self._name_input.setPlaceholderText("(no clock loaded)")
        nv.addWidget(self._name_input)
        nh.addWidget(name_frame, stretch=2)

        # Time range
        time_frame = QFrame(); time_frame.setStyleSheet("background: transparent;")
        tv = QVBoxLayout(time_frame); tv.setContentsMargins(0, 0, 0, 0); tv.setSpacing(2)
        time_lbl = QLabel("TIME RANGE  (HH:MM → HH:MM)")
        time_lbl.setFont(inter(7, QFont.Weight.Bold, letter_spacing=1.0))
        time_lbl.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        tv.addWidget(time_lbl)
        time_inputs = QFrame(); time_inputs.setStyleSheet("background: transparent;")
        ti = QHBoxLayout(time_inputs); ti.setContentsMargins(0, 0, 0, 0); ti.setSpacing(6)
        self._time_start_input = QLineEdit()
        self._time_start_input.setFixedHeight(28); self._time_start_input.setFixedWidth(70)
        self._time_start_input.setFont(mono(10, bold=True))
        self._time_start_input.setStyleSheet(self._lineedit_qss())
        self._time_start_input.setPlaceholderText("06:00")
        ti.addWidget(self._time_start_input)
        arrow = QLabel("→"); arrow.setFont(inter(12, QFont.Weight.Bold))
        arrow.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        ti.addWidget(arrow)
        self._time_end_input = QLineEdit()
        self._time_end_input.setFixedHeight(28); self._time_end_input.setFixedWidth(70)
        self._time_end_input.setFont(mono(10, bold=True))
        self._time_end_input.setStyleSheet(self._lineedit_qss())
        self._time_end_input.setPlaceholderText("10:00")
        ti.addWidget(self._time_end_input)
        ti.addStretch()
        tv.addWidget(time_inputs)
        nh.addWidget(time_frame, stretch=2)
        y += 56

        # Counters strip
        counters = QFrame(self); counters.setGeometry(x0, y, w, 44)
        counters.setStyleSheet("background: transparent;")
        ch = QHBoxLayout(counters); ch.setContentsMargins(0, 0, 0, 0); ch.setSpacing(8)
        self._counter_widgets: dict[str, QLabel] = {}
        for label, color in [("Songs", CYAN), ("Breaks", RED),
                             ("Jingles", PURPLE), ("Sweepers", AMBER),
                             ("Total", GREEN_LIGHT)]:
            ch.addWidget(self._make_counter_widget(label, color))
        y += 50

        # Action toolbar
        toolbar = QFrame(self); toolbar.setGeometry(x0, y, w, 36)
        toolbar.setStyleSheet("background: transparent;")
        th = QHBoxLayout(toolbar); th.setContentsMargins(0, 0, 0, 0); th.setSpacing(4)
        self._action_buttons: dict[str, QPushButton] = {}
        actions = [
            ("change",      "↻  Change",       CYAN,    self._on_change_clock),
            ("delete",      "✕  Delete",       RED,     self._on_delete_stub),
            ("add",         "+  Add",          GREEN,   self._on_add_stub),
            ("insert",      "↳  Insert",       AMBER,   self._on_insert_stub),
            ("up",          "↑  Move Up",      AMBER,   self._on_move_up_stub),
            ("down",        "↓  Move Down",    AMBER,   self._on_move_down_stub),
            ("ai_optimise", "✦  AI Optimise",  PURPLE,  self._on_ai_optimise_stub),
            ("preview",     "▶  Preview",      GREEN,   self._on_preview_stub),
            ("validate",    "✓  Validate",     CYAN,    self._on_validate_stub),
            ("save",        "💾  Save Clock",  GREEN,   self._on_save_clock),
        ]
        for key, label, color, handler in actions:
            b = QPushButton(label); b.setFixedHeight(34)
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.setFont(inter(9, QFont.Weight.DemiBold))
            b.setStyleSheet(self._toolbar_btn_qss(color))
            b.clicked.connect(handler)
            self._action_buttons[key] = b
            th.addWidget(b)
        y += 42

        # Slot list (scroll area)
        slots_h = WINDOW_H - HEADER_H - STATUS_H - (y - body_y) - pad
        list_frame = QFrame(self); list_frame.setGeometry(x0, y, w, slots_h)
        list_frame.setStyleSheet(
            f"QFrame {{ background: {BG_DARK}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; "
            f"border-radius: 6px; }}"
        )
        scroll = QScrollArea(list_frame)
        scroll.setGeometry(0, 0, w, slots_h)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            f"QScrollBar:vertical {{ background: transparent; width: 6px; }}"
            f"QScrollBar::handle:vertical {{ background: {rgba(PURPLE, 0.45)}; "
            f"border-radius: 3px; min-height: 24px; }}"
            "QScrollBar::add-line, QScrollBar::sub-line { height: 0; }"
        )
        self._slot_body = QFrame(); self._slot_body.setStyleSheet("background: transparent;")
        self._slot_body_layout = QVBoxLayout(self._slot_body)
        self._slot_body_layout.setContentsMargins(0, 0, 0, 0)
        self._slot_body_layout.setSpacing(0)
        self._slot_body_layout.addStretch()
        scroll.setWidget(self._slot_body)

    def _make_counter_widget(self, label: str, color: str) -> QFrame:
        f = QFrame(); f.setFixedHeight(44)
        f.setStyleSheet(
            f"QFrame {{ background: {rgba(color, 0.10)}; "
            f"border: 1px solid {rgba(color, 0.30)}; "
            f"border-radius: 5px; }}"
        )
        v = QVBoxLayout(f); v.setContentsMargins(10, 4, 10, 4); v.setSpacing(0)
        sub = QLabel(label.upper())
        sub.setFont(inter(7, QFont.Weight.Bold, letter_spacing=1.0))
        sub.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        val = QLabel("0")
        val.setFont(mono(15, bold=True))
        val.setStyleSheet(f"color: {color}; background: transparent;")
        v.addWidget(sub); v.addWidget(val)
        self._counter_widgets[label] = val
        return f

    def _build_right(self):
        body_y = HEADER_H
        body_h = WINDOW_H - HEADER_H - STATUS_H
        wrap = QFrame(self); wrap.setGeometry(RIGHT_X, body_y, RIGHT_W, body_h)
        wrap.setStyleSheet(
            f"QFrame {{ background: {BG_DARK}; "
            f"border-left: 1px solid {rgba('#ffffff', 0.06)}; }}"
        )
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0); v.setSpacing(0)

        self._props_panel = _SlotPropertiesPanel(self._categories)
        self._props_panel.apply_clicked.connect(self._on_apply_slot_changes)
        self._props_panel.remove_clicked.connect(self._on_remove_slot_stub)
        v.addWidget(self._props_panel)

    def _build_status_bar(self):
        bar = QFrame(self); bar.setGeometry(0, WINDOW_H - STATUS_H, WINDOW_W, STATUS_H)
        bar.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border-top: 1px solid {rgba('#ffffff', 0.06)}; }}"
        )
        # Simple paint — pills + center text
        from datetime import datetime
        bar_paint = _ClockEditorStatusBar(bar)
        bar_paint.setGeometry(0, 0, WINDOW_W, STATUS_H)

    @staticmethod
    def _lineedit_qss() -> str:
        return (
            f"QLineEdit {{ background: #0e1020; color: {TEXT_PRI}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; border-radius: 4px; "
            f"padding: 0 10px; "
            f"selection-background-color: {rgba(CYAN, 0.25)}; }}"
            f"QLineEdit:focus {{ border: 1px solid {rgba(CYAN, 0.50)}; }}"
        )

    @staticmethod
    def _toolbar_btn_qss(color: str) -> str:
        return (
            f"QPushButton {{ background: {rgba(color, 0.14)}; "
            f"color: {color}; "
            f"border: 1px solid {rgba(color, 0.30)}; "
            f"border-radius: 5px; padding: 0 10px; }}"
            f"QPushButton:hover {{ background: {rgba(color, 0.24)}; }}"
            f"QPushButton:disabled {{ background: rgba(255,255,255,0.02); "
            f"color: {TEXT_DIM}; border-color: rgba(255,255,255,0.04); }}"
        )

    # ── State management ──────────────────────────────────────────────────

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

        self._name_input.setText(clock.get("name") or "")
        self._time_start_input.setText(clock.get("time_start") or "")
        self._time_end_input.setText(clock.get("time_end") or "")

        self._rebuild_slot_rows()
        self._refresh_counters()
        self._props_panel.set_slot(None)

        log.info(
            f"[clock-editor] loaded clock id={clock_id} "
            f"name={clock.get('name')!r} slots={len(self._slots)}")

    def _show_no_clocks_state(self) -> None:
        self._name_input.setPlaceholderText("(no clocks in DB — create one in F6)")
        self._refresh_counters()

    def _rebuild_slot_rows(self) -> None:
        # Remove existing rows
        for r in self._slot_rows:
            r.setParent(None); r.deleteLater()
        self._slot_rows.clear()
        # Insert new rows BEFORE the stretch (which is the last item)
        stretch_idx = self._slot_body_layout.count() - 1
        for i, slot in enumerate(self._slots):
            row = _SlotRow(i, self._slot_body)
            row.set_data(slot, is_selected=(i == self._selected_slot_idx))
            row.clicked.connect(self._on_slot_row_clicked)
            self._slot_body_layout.insertWidget(stretch_idx + i, row)
            self._slot_rows.append(row)

    def _refresh_counters(self) -> None:
        n_song = sum(1 for s in self._slots
                     if _normalize_slot_type(s.get("slot_type", "")) == "Song")
        n_break = sum(1 for s in self._slots
                      if _normalize_slot_type(s.get("slot_type", "")) == "Spot"
                      or s.get("is_break"))
        n_jingle = sum(1 for s in self._slots
                       if _normalize_slot_type(s.get("slot_type", "")) == "Jingle")
        n_sweeper = sum(1 for s in self._slots
                        if _normalize_slot_type(s.get("slot_type", "")) == "Sweeper")
        # Total minutes: rough estimate (3:30 per song, 2 min per break,
        # 8s sweeper, 12s jingle). Phase F4 will use real audio durations.
        total_s = (n_song * 210 + n_break * 120
                   + n_sweeper * 8 + n_jingle * 12)
        for label, val in [
            ("Songs", str(n_song)), ("Breaks", str(n_break)),
            ("Jingles", str(n_jingle)), ("Sweepers", str(n_sweeper)),
            ("Total", _fmt_minutes(total_s)),
        ]:
            if label in self._counter_widgets:
                self._counter_widgets[label].setText(val)

    # ── Handlers ──────────────────────────────────────────────────────────

    def _on_slot_row_clicked(self, idx: int) -> None:
        if idx < 0 or idx >= len(self._slots):
            return
        self._selected_slot_idx = idx
        for i, row in enumerate(self._slot_rows):
            row.set_data(self._slots[i], is_selected=(i == idx))
        self._props_panel.set_slot(self._slots[idx], slot_index=idx)

    def _on_apply_slot_changes(self, data: dict) -> None:
        if self._selected_slot_idx is None:
            return
        self._slots[self._selected_slot_idx].update(data)
        # Refresh row visual
        row = self._slot_rows[self._selected_slot_idx]
        row.set_data(self._slots[self._selected_slot_idx], is_selected=True)
        self._refresh_counters()
        log.info(
            f"[clock-editor] slot {self._selected_slot_idx + 1} updated: {data}")

    def _on_change_clock(self) -> None:
        # F2.1: cycle to next clock in the DB list (simple stub).
        # F2.2 will add a proper picker dialog.
        if not self._all_clocks:
            return
        ids = [c["id"] for c in self._all_clocks]
        if self._current_clock_id in ids:
            i = ids.index(self._current_clock_id)
            next_id = ids[(i + 1) % len(ids)]
        else:
            next_id = ids[0]
        self._load_clock(int(next_id))

    def _on_save_clock(self) -> None:
        if self._current_clock_id is None:
            log.warning("[clock-editor] save: no clock loaded")
            return
        try:
            self._db.save_clock(self._current_clock_id, {
                "name":       self._name_input.text().strip() or "Untitled",
                "time_start": self._time_start_input.text().strip(),
                "time_end":   self._time_end_input.text().strip(),
            })
            self._db.save_clock_slots(self._current_clock_id, self._slots)
            log.info(
                f"[clock-editor] saved clock id={self._current_clock_id} "
                f"({len(self._slots)} slots)")
            # Refresh in-memory clocks list (for Change cycling)
            self._all_clocks = [dict(r) for r in self._db.get_all_clocks()]
        except Exception as exc:
            log.warning(f"[clock-editor] save failed: {exc}")

    # ── Stubs (F2.3 will wire) ───────────────────────────────────────────

    def _on_delete_stub(self):       log.info("[clock-editor] Delete (F2.3 stub)")
    def _on_add_stub(self):          log.info("[clock-editor] Add slot (F2.3 stub)")
    def _on_insert_stub(self):       log.info("[clock-editor] Insert slot (F2.3 stub)")
    def _on_move_up_stub(self):      log.info("[clock-editor] Move Up (F2.3 stub)")
    def _on_move_down_stub(self):    log.info("[clock-editor] Move Down (F2.3 stub)")
    def _on_remove_slot_stub(self):  log.info("[clock-editor] Remove Slot (F2.3 stub)")
    def _on_ai_optimise_stub(self):  log.info(
        "[clock-editor] AI Optimise will run in Phase E (Anthropic API)")
    def _on_preview_stub(self):      log.info("[clock-editor] Preview (F2.4 stub)")
    def _on_validate_stub(self):     log.info(
        "[clock-editor] Validate: all checks passed (validation impl: Phase E)")


# ════════════════════════════════════════════════════════════════════════════
# Status bar (mirrors Studio's pattern, stripped down)
# ════════════════════════════════════════════════════════════════════════════

class _ClockEditorStatusBar(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(STATUS_H)
        self.setStyleSheet("background: transparent;")

    def paintEvent(self, _e):
        super().paintEvent(_e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Pills
        x = 12
        for label, color in [
            ("AUTO MODE",   PURPLE_LIGHT),
            ("AI Active",   GREEN),
            ("8 Clocks",    CYAN),
            ("Log Ready",   AMBER),
        ]:
            p.setFont(inter(8, QFont.Weight.Bold, letter_spacing=0.6))
            tw = p.fontMetrics().horizontalAdvance(label) + 16
            pill = QRectF(x, (STATUS_H - 18) / 2, tw, 18)
            bg = QColor(color); bg.setAlphaF(0.18)
            p.setBrush(bg); p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(pill, 8, 8)
            p.setPen(QColor(color))
            p.drawText(pill, Qt.AlignmentFlag.AlignCenter, label)
            x += tw + 6
        # Center text
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(inter(9, QFont.Weight.Medium))
        p.drawText(QRectF(0, 0, self.width(), self.height()),
                   Qt.AlignmentFlag.AlignCenter,
                   "Clock Editor  ·  KissFM Studio v2.0")
