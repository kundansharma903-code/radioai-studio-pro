"""
RadioAI Studio Pro — Modal Clock Editor (ref Figma 225:5).

Phase F-Final C3: replaces the previous full-screen clock editor with a
Jazler-style modal dialog. Filter-based slot definition, circular
60-minute clock face visualization, OK/Cancel exit semantics.

Layout (1280 × 800)
-------------------
  TOP FORM ROW   1240 ×  64   — Name | Comments | Color | Backup Filter
  BODY           1240 × 624
    LEFT (Available Clock Elements)   608 wide
      - 5 slot-type icon buttons (Song / Jingle / Spot / Voice Track / Sweeper)
      - 3 sub-tabs (Filters / Song Tracks / Artists)
      - tab content with filter inputs / song picker / artist picker
      - Filter Results: live "X Songs Available · Y.Ys avg duration"
      - Songs Found list
    RIGHT (Clock Editor)              608 wide
      - top-right: Colorize by dropdown
      - left-side: Add / Insert / Replace / Delete vertical action stack
      - validation status
      - circular 60-minute clock face (custom QPainter widget)
      - bottom: Loop/Cycle + Show-only-descriptions toggles
  ACTION ROW     1240 ×  48   — Cancel / OK at right

═════════════════════════════════════════════════════════════════════════════
PERFORMANCE NOTES
═════════════════════════════════════════════════════════════════════════════
  1. Clock face renders in one QPainter pass — slot count is bounded
     by 60 (one slot per minute max), so no event.rect() trickery needed.
  2. Filter live-count uses a bounded LIMIT 240 query; called on every
     dropdown / range change.
  3. NO db calls in paintEvent.
═════════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import json
import logging
import math
from typing import Optional

from PyQt6.QtCore import Qt, QRect, QRectF, QPoint, QPointF, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont, QCursor, QMouseEvent,
    QPainterPath,
)
from PyQt6.QtWidgets import (
    QDialog, QWidget, QFrame, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLineEdit, QComboBox, QCheckBox, QListWidget, QListWidgetItem,
    QTabWidget, QSpinBox, QSizePolicy, QMessageBox, QColorDialog,
)

from ui.widgets._tokens import (
    inter, mono, rgba,
    BG_BASE, BG_DARK, BG_PANEL, BG_CARD, BG_CARD_DK, BG_ELEVATED,
    TEXT_PRI, TEXT_SEC, TEXT_MUTED, TEXT_DIM,
    CYAN, CYAN_LIGHT, PURPLE, PURPLE_LIGHT, PURPLE_DARK,
    GREEN, GREEN_LIGHT, AMBER, AMBER_LIGHT,
    RED, RED_LIGHT, PINK, PINK_LIGHT, TEAL, TEAL_LIGHT,
)

log = logging.getLogger("ClockEditorDialog")


# ── Layout ──────────────────────────────────────────────────────────────

DIALOG_W = 1280
DIALOG_H = 800
BORDER = "#1c1f38"

SLOT_TYPES = ("Song", "Jingle", "Spot", "Voice Track", "Sweeper")

SLOT_TYPE_GLYPH = {
    "Song":        "♪",   # musical note
    "Jingle":      "🔔",  # bell
    "Spot":        "$",   # dollar sign
    "Voice Track": "🎤",  # microphone
    "Sweeper":     "★",   # star
}

SLOT_TYPE_COLOR = {
    "Song":        AMBER,
    "Jingle":      CYAN,
    "Spot":        GREEN,
    "Voice Track": TEAL,
    "Sweeper":     PURPLE,
}

# Default duration (minutes) for the circular face when slot's
# duration_seconds isn't set. 4-minute default = ~24° on the face.
DEFAULT_SLOT_MINUTES = 4


# ════════════════════════════════════════════════════════════════════════
# CIRCULAR CLOCK FACE — custom QPainter (60 minutes radial)
# ════════════════════════════════════════════════════════════════════════

class _CircularClockFace(QWidget):
    """Renders 60 minutes radially. Each slot is an arc segment from
    (minute_position * 6°) sweeping clockwise by (duration / 60 sec * 6°),
    rotated -90° so 12 o'clock = 0 minute.

    Click selects the slot under the mouse. Selected slot draws thicker.
    """

    slot_clicked = pyqtSignal(int)   # slot index in the parent's _slots list

    def __init__(self, parent=None):
        super().__init__(parent)
        self._slots: list[dict] = []
        self._selected_idx: Optional[int] = None
        self._colorize_by: str = "Slot Type"   # "Slot Type" | "Sound Code"
        self.setMinimumSize(360, 360)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

    def set_slots(self, slots: list[dict],
                  selected_idx: Optional[int]) -> None:
        self._slots = list(slots or [])
        self._selected_idx = selected_idx
        self.update()

    def set_colorize_by(self, mode: str) -> None:
        self._colorize_by = mode or "Slot Type"
        self.update()

    @staticmethod
    def _slot_minutes(slot: dict) -> float:
        """Slot duration in minutes for arc-sweep calc."""
        s = slot.get("duration_seconds")
        if s:
            return float(s) / 60.0
        # Type-specific defaults
        st = (slot.get("slot_type") or "Song").strip()
        return {"Song": 3.5, "Break": 1.0, "Jingle": 0.2, "Sweeper": 0.15,
                "Station ID": 0.13, "Voice Track": 0.5, "Spot": 1.0
                }.get(st, DEFAULT_SLOT_MINUTES)

    def _slot_color(self, slot: dict) -> str:
        if self._colorize_by == "Sound Code":
            cn = (slot.get("cat_color") or slot.get("color") or "").strip()
            if cn.startswith("#") and len(cn) == 7:
                return cn
        return SLOT_TYPE_COLOR.get(
            (slot.get("slot_type") or "Song").strip(), AMBER)

    def _hit_test(self, pos: QPoint) -> Optional[int]:
        """Convert (x,y) to (angle, radius); find slot at that angle."""
        cx, cy = self.width() // 2, self.height() // 2
        dx, dy = pos.x() - cx, pos.y() - cy
        r = math.hypot(dx, dy)
        outer_r = min(cx, cy) - 20
        inner_r = outer_r * 0.55
        if r < inner_r or r > outer_r:
            return None
        # angle: 0 = up (12 o'clock), clockwise
        ang = math.degrees(math.atan2(dx, -dy)) % 360
        minute_at_pos = ang / 6.0
        # Walk slots and find which arc contains minute_at_pos
        for idx, slot in enumerate(self._slots):
            start = float(slot.get("minute_position") or 0)
            sweep = self._slot_minutes(slot)
            end = (start + sweep) % 60.0
            if start <= end:
                if start <= minute_at_pos < end:
                    return idx
            else:
                # wraps past 60
                if minute_at_pos >= start or minute_at_pos < end:
                    return idx
        return None

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() != Qt.MouseButton.LeftButton:
            return
        idx = self._hit_test(e.pos())
        if idx is not None:
            self.slot_clicked.emit(int(idx))

    def paintEvent(self, _e):
        super().paintEvent(_e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy = self.width() // 2, self.height() // 2
        outer_r = min(cx, cy) - 20
        inner_r = int(outer_r * 0.55)

        # Background ring
        p.setBrush(QColor(BG_CARD_DK)); p.setPen(QPen(QColor(BORDER), 2))
        p.drawEllipse(QPointF(cx, cy), outer_r, outer_r)
        p.setBrush(QColor(BG_BASE)); p.setPen(QPen(QColor(BORDER), 1))
        p.drawEllipse(QPointF(cx, cy), inner_r, inner_r)

        # Minute tick marks every 5 minutes
        for m in range(0, 60, 5):
            ang = math.radians(m * 6 - 90)
            x1 = cx + (outer_r - 8) * math.cos(ang)
            y1 = cy + (outer_r - 8) * math.sin(ang)
            x2 = cx + (outer_r - 16) * math.cos(ang)
            y2 = cy + (outer_r - 16) * math.sin(ang)
            p.setPen(QPen(QColor(TEXT_DIM), 2 if m % 15 == 0 else 1))
            p.drawLine(int(x1), int(y1), int(x2), int(y2))

        # 12 / 3 / 6 / 9 minute labels
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(mono(9, bold=True))
        for m, label in ((0, "0"), (15, "15"), (30, "30"), (45, "45")):
            ang = math.radians(m * 6 - 90)
            tx = cx + (outer_r - 30) * math.cos(ang)
            ty = cy + (outer_r - 30) * math.sin(ang)
            p.drawText(QRectF(tx - 12, ty - 8, 24, 16),
                       Qt.AlignmentFlag.AlignCenter, label)

        # Slot arcs
        thickness = outer_r - inner_r - 4
        mid_r = (outer_r + inner_r) // 2
        for idx, slot in enumerate(self._slots):
            start_min = float(slot.get("minute_position") or 0) % 60
            sweep_min = max(0.5, self._slot_minutes(slot))
            # Qt arc angles are 1/16 degree, counter-clockwise from 3 o'clock
            # Our minute system: 0 minute = 12 o'clock, clockwise.
            # Convert to Qt: start_qt = 90° - start_min*6° (counter-clockwise),
            #               sweep_qt = -sweep_min * 6°
            start_qt = (90 - start_min * 6) * 16
            sweep_qt = int(-sweep_min * 6 * 16)
            color = QColor(self._slot_color(slot))
            is_sel = (idx == self._selected_idx)
            arc_color = QColor(color); arc_color.setAlphaF(0.85 if is_sel else 0.65)
            pen = QPen(arc_color, thickness if not is_sel else thickness + 4,
                       Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            arc_rect = QRectF(cx - mid_r, cy - mid_r, 2 * mid_r, 2 * mid_r)
            p.drawArc(arc_rect, int(start_qt), sweep_qt)

        # Center hub label
        p.setPen(QColor(TEXT_PRI))
        p.setFont(inter(11, QFont.Weight.Black, letter_spacing=1.4))
        p.drawText(QRectF(cx - 80, cy - 12, 160, 14),
                   Qt.AlignmentFlag.AlignCenter, f"{len(self._slots)} SLOTS")
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(inter(8))
        total_min = sum(self._slot_minutes(s) for s in self._slots)
        p.drawText(QRectF(cx - 80, cy + 4, 160, 14),
                   Qt.AlignmentFlag.AlignCenter,
                   f"{int(total_min)}:{int((total_min % 1) * 60):02d} total")


# ════════════════════════════════════════════════════════════════════════
# TOP FORM ROW — Name / Comments / Color / Backup
# ════════════════════════════════════════════════════════════════════════

class _TopFormRow(QFrame):
    """Single-line top form: Clock Name, Comments, Color picker,
    Backup Song Filter."""

    def __init__(self, categories: list[dict], parent=None):
        super().__init__(parent)
        self.setFixedHeight(64)
        self.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border: 1px solid {BORDER}; border-radius: 6px; }}"
        )
        h = QHBoxLayout(self); h.setContentsMargins(12, 8, 12, 8); h.setSpacing(10)

        # Name
        h.addLayout(self._labeled_input(
            "Clock Name", self._make_name_input()))
        # Comments
        h.addLayout(self._labeled_input(
            "Comments", self._make_comments_input()))
        # Color picker swatch
        col = QVBoxLayout(); col.setSpacing(2)
        col.addWidget(self._cap("Color"))
        self._color_btn = QPushButton()
        self._color_btn.setFixedSize(80, 28)
        self._color_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._color_btn.clicked.connect(self._on_color_clicked)
        self._color = "#06b6d4"
        self._refresh_color_btn()
        col.addWidget(self._color_btn)
        h.addLayout(col)
        # Backup Song Filter
        col = QVBoxLayout(); col.setSpacing(2)
        col.addWidget(self._cap("Backup Song Filter"))
        self._backup = QComboBox(); self._backup.setFixedHeight(28)
        self._backup.setFixedWidth(280)
        self._backup.setFont(inter(10))
        self._backup.setStyleSheet(self._combo_qss())
        self._backup.addItem("Random Song from the whole library (No Filter)",
                             userData=None)
        for c in categories:
            self._backup.addItem(f"Random from {c.get('name', '')}",
                                 userData=int(c["id"]))
        col.addWidget(self._backup)
        h.addLayout(col)

    def _make_name_input(self) -> QLineEdit:
        e = QLineEdit(); e.setFixedHeight(28); e.setFixedWidth(220)
        e.setPlaceholderText("New Clock"); e.setFont(inter(10))
        e.setStyleSheet(self._line_qss())
        self._name_input = e
        return e

    def _make_comments_input(self) -> QLineEdit:
        e = QLineEdit(); e.setFixedHeight(28); e.setMinimumWidth(280)
        e.setPlaceholderText("Notes about this clock…"); e.setFont(inter(10))
        e.setStyleSheet(self._line_qss())
        self._comments_input = e
        return e

    def _labeled_input(self, label: str, widget: QWidget) -> QVBoxLayout:
        v = QVBoxLayout(); v.setSpacing(2)
        v.addWidget(self._cap(label))
        v.addWidget(widget)
        return v

    def _cap(self, label: str) -> QLabel:
        l = QLabel(label)
        l.setFont(inter(8, QFont.Weight.Bold, letter_spacing=0.6))
        l.setStyleSheet(f"color: {TEXT_DIM}; background: transparent;")
        return l

    @staticmethod
    def _line_qss() -> str:
        return (
            f"QLineEdit {{ background: {BG_CARD_DK}; "
            f"color: {TEXT_PRI}; "
            f"border: 1px solid {BORDER}; "
            f"border-radius: 4px; padding: 0 8px; }}"
            f"QLineEdit:focus {{ border-color: {rgba(CYAN, 0.60)}; }}"
        )

    @staticmethod
    def _combo_qss() -> str:
        return (
            f"QComboBox {{ background: {BG_CARD_DK}; "
            f"color: {TEXT_PRI}; "
            f"border: 1px solid {BORDER}; "
            f"border-radius: 4px; padding: 0 8px; }}"
            f"QComboBox QAbstractItemView {{ background: {BG_CARD_DK}; "
            f"color: {TEXT_PRI}; selection-background-color: {rgba(CYAN, 0.20)}; }}"
        )

    def _refresh_color_btn(self):
        self._color_btn.setStyleSheet(
            f"QPushButton {{ background: {self._color}; "
            f"border: 1px solid {BORDER}; border-radius: 4px; }}"
            f"QPushButton:hover {{ border: 1px solid {rgba('#ffffff', 0.50)}; }}"
        )

    def _on_color_clicked(self):
        c = QColorDialog.getColor(QColor(self._color), self, "Pick a clock color")
        if c.isValid():
            self._color = c.name()
            self._refresh_color_btn()

    # ── Public ────────────────────────────────────────────────────────

    def get_data(self) -> dict:
        return {
            "name":               self._name_input.text().strip() or "New Clock",
            "comments":           self._comments_input.text().strip(),
            "color":              self._color,
            "backup_song_filter": json.dumps({"category_id": self._backup.currentData()})
                                  if self._backup.currentData() is not None else None,
        }

    def set_data(self, clock: dict) -> None:
        self._name_input.setText(clock.get("name") or "")
        self._comments_input.setText(clock.get("comments") or "")
        c = clock.get("color")
        if c:
            self._color = c
            self._refresh_color_btn()
        # Backup filter
        bf = clock.get("backup_song_filter")
        if bf:
            try:
                spec = json.loads(bf) if isinstance(bf, str) else bf
                cat_id = spec.get("category_id") if spec else None
                for i in range(self._backup.count()):
                    if self._backup.itemData(i) == cat_id:
                        self._backup.setCurrentIndex(i); break
            except (json.JSONDecodeError, AttributeError):
                pass


# ════════════════════════════════════════════════════════════════════════
# MAIN MODAL DIALOG
# ════════════════════════════════════════════════════════════════════════

class ClockEditorDialog(QDialog):
    """Modal Clock Editor matching Jazler ref 225:5."""

    def __init__(self, db, clock_id: Optional[int] = None,
                 scheduler=None, parent=None):
        super().__init__(parent)
        self._db = db
        self._scheduler = scheduler
        self._clock_id = clock_id      # None → new clock
        self._slots: list[dict] = []
        self._selected_slot_idx: Optional[int] = None
        self._selected_slot_type: str = "Song"

        self.setWindowTitle("Clock Editor")
        self.setModal(True)
        self.setFixedSize(DIALOG_W, DIALOG_H)
        self.setStyleSheet(f"QDialog {{ background: {BG_BASE}; }}")

        # Categories + songs + artists for dropdowns + pickers
        try:
            self._categories = [dict(r) for r in db.get_categories()]
        except Exception:
            self._categories = []

        v = QVBoxLayout(self); v.setContentsMargins(20, 16, 20, 16); v.setSpacing(12)

        # Top form row
        self._top_form = _TopFormRow(self._categories, self)
        v.addWidget(self._top_form)

        # Body — left half (Available Clock Elements) + right half (Editor)
        body = QHBoxLayout(); body.setSpacing(12)
        body.addWidget(self._build_left(), 1)
        body.addWidget(self._build_right(), 1)
        v.addLayout(body, 1)

        # Bottom action row — Cancel / OK
        btn_row = QHBoxLayout(); btn_row.addStretch(); btn_row.setSpacing(8)
        cancel = QPushButton("Cancel"); cancel.setFixedHeight(34)
        cancel.setFont(inter(11))
        cancel.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {TEXT_SEC}; "
            f"border: 1px solid {BORDER}; "
            f"border-radius: 5px; padding: 0 22px; }}"
            f"QPushButton:hover {{ color: {TEXT_PRI}; "
            f"border-color: {TEXT_MUTED}; }}"
        )
        cancel.clicked.connect(self.reject)
        btn_row.addWidget(cancel)
        ok = QPushButton("OK"); ok.setFixedHeight(34)
        ok.setDefault(True); ok.setFont(inter(11, QFont.Weight.Bold))
        ok.setStyleSheet(
            f"QPushButton {{ background: {rgba(GREEN, 0.24)}; "
            f"color: {GREEN_LIGHT}; "
            f"border: 1px solid {rgba(GREEN, 0.50)}; "
            f"border-radius: 5px; padding: 0 30px; }}"
            f"QPushButton:hover {{ background: {rgba(GREEN, 0.36)}; }}"
        )
        ok.clicked.connect(self._on_ok)
        btn_row.addWidget(ok)
        v.addLayout(btn_row)

        # Initial data load
        if clock_id is not None:
            self._load_clock(clock_id)
        else:
            self._refresh_filter_count()

        log.info(f"ClockEditorDialog open clock_id={clock_id}")

    # ── Left half: Available Clock Elements ─────────────────────────────

    def _build_left(self) -> QFrame:
        f = QFrame()
        f.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border: 1px solid {BORDER}; border-radius: 6px; }}"
        )
        v = QVBoxLayout(f); v.setContentsMargins(12, 10, 12, 10); v.setSpacing(8)

        title = QLabel("AVAILABLE CLOCK ELEMENTS")
        title.setFont(inter(8, QFont.Weight.Black, letter_spacing=1.6))
        title.setStyleSheet(f"color: {AMBER}; background: transparent;")
        v.addWidget(title)

        # 5 slot-type icon buttons
        types_row = QHBoxLayout(); types_row.setSpacing(6)
        self._type_buttons: dict[str, QPushButton] = {}
        for t in SLOT_TYPES:
            b = QPushButton(f"{SLOT_TYPE_GLYPH[t]}\n{t}")
            b.setFixedSize(96, 60)
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.setFont(inter(9, QFont.Weight.DemiBold))
            color = SLOT_TYPE_COLOR[t]
            b.setStyleSheet(self._type_btn_qss(color, active=(t == "Song")))
            b.clicked.connect(lambda _c=False, _t=t: self._on_type_button(_t))
            types_row.addWidget(b)
            self._type_buttons[t] = b
        types_row.addStretch()
        v.addLayout(types_row)

        # 3 sub-tabs (Filters / Song Tracks / Artists)
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(
            f"QTabWidget::pane {{ background: {BG_CARD_DK}; "
            f"border: 1px solid {BORDER}; border-radius: 4px; }}"
            f"QTabBar::tab {{ background: transparent; "
            f"color: {TEXT_SEC}; padding: 6px 14px; margin-right: 2px; }}"
            f"QTabBar::tab:selected {{ color: {AMBER}; "
            f"border-bottom: 2px solid {AMBER}; }}"
        )
        self._tabs.addTab(self._build_filters_tab(),     "Filters")
        self._tabs.addTab(self._build_song_tracks_tab(), "Song Tracks")
        self._tabs.addTab(self._build_artists_tab(),     "Artists")
        v.addWidget(self._tabs, 1)

        return f

    def _type_btn_qss(self, color: str, active: bool) -> str:
        if active:
            return (
                f"QPushButton {{ background: {rgba(color, 0.32)}; "
                f"color: {color}; "
                f"border: 2px solid {color}; "
                f"border-radius: 6px; }}"
            )
        return (
            f"QPushButton {{ background: {rgba(color, 0.10)}; "
            f"color: {color}; "
            f"border: 1px solid {rgba(color, 0.32)}; "
            f"border-radius: 6px; }}"
            f"QPushButton:hover {{ background: {rgba(color, 0.20)}; }}"
        )

    def _build_filters_tab(self) -> QWidget:
        w = QWidget(); w.setStyleSheet("background: transparent;")
        v = QVBoxLayout(w); v.setContentsMargins(8, 8, 8, 8); v.setSpacing(6)

        # Categories filters: 3 dropdowns side by side
        cat_row = QHBoxLayout(); cat_row.setSpacing(6)
        for label, attr in [("Sound Code", "sound_code"),
                            ("Era", "era"),
                            ("Vocal Presence", "vocal")]:
            cell = QVBoxLayout(); cell.setSpacing(2)
            cell.addWidget(self._cap(label))
            cb = QComboBox(); cb.setFixedHeight(26); cb.setFont(inter(10))
            cb.setStyleSheet(_TopFormRow._combo_qss())
            cb.addItem("All", userData="All")
            if attr == "sound_code":
                for c in self._categories:
                    cb.addItem(str(c.get("name") or ""),
                               userData=str(c.get("name") or ""))
            elif attr == "era":
                for e in ("80s", "90s", "2000s", "2010s", "2020s"):
                    cb.addItem(e, userData=e)
            elif attr == "vocal":
                for vv in ("vocal", "instrumental"):
                    cb.addItem(vv.title(), userData=vv)
            cb.currentIndexChanged.connect(self._refresh_filter_count)
            cell.addWidget(cb)
            cat_row.addLayout(cell, 1)
            setattr(self, f"_filter_{attr}", cb)
        v.addLayout(cat_row)

        # Range filters: Year / Priority / BPM (low → high pairs)
        for name, attr, lo, hi, step in [
            ("Year",      "year",     1980, 2030, 1),
            ("Priority",  "priority",    0,    9, 1),
            ("BPM",       "bpm",        60,  200, 5),
        ]:
            row = QHBoxLayout(); row.setSpacing(6)
            row.addWidget(self._cap(f"{name} (low → high)"))
            lo_sb = QSpinBox(); lo_sb.setRange(lo, hi); lo_sb.setValue(lo)
            lo_sb.setSingleStep(step); lo_sb.setFixedHeight(26)
            lo_sb.setStyleSheet(self._spin_qss())
            lo_sb.valueChanged.connect(self._refresh_filter_count)
            hi_sb = QSpinBox(); hi_sb.setRange(lo, hi); hi_sb.setValue(hi)
            hi_sb.setSingleStep(step); hi_sb.setFixedHeight(26)
            hi_sb.setStyleSheet(self._spin_qss())
            hi_sb.valueChanged.connect(self._refresh_filter_count)
            row.addWidget(lo_sb); row.addWidget(QLabel("→")); row.addWidget(hi_sb)
            row.addStretch()
            setattr(self, f"_filter_{attr}_lo", lo_sb)
            setattr(self, f"_filter_{attr}_hi", hi_sb)
            v.addLayout(row)

        # Filter Results live count
        self._filter_count_label = QLabel("0 Songs Available · 0.0s Estimated Avg Duration")
        self._filter_count_label.setFont(inter(11, QFont.Weight.Black))
        self._filter_count_label.setStyleSheet(
            f"QLabel {{ background: {rgba(AMBER, 0.16)}; "
            f"color: {AMBER}; "
            f"border: 1px solid {rgba(AMBER, 0.40)}; "
            f"border-radius: 5px; padding: 8px; }}"
        )
        self._filter_count_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(self._filter_count_label)

        # Reset all filters
        reset = QPushButton("↻ Reset All Filters")
        reset.setFixedHeight(26); reset.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        reset.setFont(inter(9, QFont.Weight.DemiBold))
        reset.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {TEXT_MUTED}; "
            f"border: none; }}"
            f"QPushButton:hover {{ color: {CYAN_LIGHT}; "
            f"text-decoration: underline; }}"
        )
        reset.clicked.connect(self._on_reset_filters)
        v.addWidget(reset, alignment=Qt.AlignmentFlag.AlignLeft)

        # Songs Found list
        v.addWidget(self._cap("Songs Found"))
        self._songs_found = QListWidget()
        self._songs_found.setStyleSheet(self._list_qss())
        v.addWidget(self._songs_found, 1)

        return w

    def _build_song_tracks_tab(self) -> QWidget:
        w = QWidget(); w.setStyleSheet("background: transparent;")
        v = QVBoxLayout(w); v.setContentsMargins(8, 8, 8, 8); v.setSpacing(6)
        v.addWidget(self._cap("Search song title or artist"))
        self._song_search = QLineEdit()
        self._song_search.setFixedHeight(28)
        self._song_search.setStyleSheet(_TopFormRow._line_qss())
        self._song_search.textChanged.connect(self._refresh_song_search)
        v.addWidget(self._song_search)
        self._song_list = QListWidget()
        self._song_list.setStyleSheet(self._list_qss())
        v.addWidget(self._song_list, 1)
        # Initial load — top 50 songs
        self._refresh_song_search("")
        return w

    def _build_artists_tab(self) -> QWidget:
        w = QWidget(); w.setStyleSheet("background: transparent;")
        v = QVBoxLayout(w); v.setContentsMargins(8, 8, 8, 8); v.setSpacing(6)
        v.addWidget(self._cap("Pick an artist (slot picks random songs)"))
        self._artist_list = QListWidget()
        self._artist_list.setStyleSheet(self._list_qss())
        try:
            rows = self._db._conn().execute(
                "SELECT DISTINCT artist FROM songs "
                "WHERE artist IS NOT NULL AND artist != '' "
                "ORDER BY artist LIMIT 200").fetchall()
        except Exception:
            rows = []
        for r in rows:
            item = QListWidgetItem(str(r[0]))
            item.setData(Qt.ItemDataRole.UserRole, str(r[0]))
            self._artist_list.addItem(item)
        v.addWidget(self._artist_list, 1)
        return w

    # ── Right half: Clock Editor (action stack + circular face) ─────────

    def _build_right(self) -> QFrame:
        f = QFrame()
        f.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border: 1px solid {BORDER}; border-radius: 6px; }}"
        )
        v = QVBoxLayout(f); v.setContentsMargins(12, 10, 12, 10); v.setSpacing(8)

        # Top row: title + colorize-by
        top = QHBoxLayout()
        title = QLabel("CLOCK EDITOR")
        title.setFont(inter(8, QFont.Weight.Black, letter_spacing=1.6))
        title.setStyleSheet(f"color: {GREEN_LIGHT}; background: transparent;")
        top.addWidget(title); top.addStretch()
        col_lbl = QLabel("Colorize by:")
        col_lbl.setFont(inter(8, QFont.Weight.Bold, letter_spacing=0.4))
        col_lbl.setStyleSheet(f"color: {TEXT_DIM}; background: transparent;")
        top.addWidget(col_lbl)
        self._colorize = QComboBox(); self._colorize.setFixedHeight(26)
        self._colorize.setFixedWidth(140); self._colorize.setFont(inter(10))
        self._colorize.setStyleSheet(_TopFormRow._combo_qss())
        for opt in ("Slot Type", "Sound Code"):
            self._colorize.addItem(opt, userData=opt)
        self._colorize.currentTextChanged.connect(
            lambda mode: self._face.set_colorize_by(mode))
        top.addWidget(self._colorize)
        v.addLayout(top)

        # Body: action stack on left + circular face on right
        body = QHBoxLayout(); body.setSpacing(8)
        actions = QVBoxLayout(); actions.setSpacing(6)
        self._add_btn    = self._action_btn("Add",     GREEN_LIGHT, on_click=self._on_add)
        self._insert_btn = self._action_btn("Insert",  GREEN,       on_click=self._on_insert)
        self._replace_btn= self._action_btn("Replace", CYAN_LIGHT,  on_click=self._on_replace)
        self._delete_btn = self._action_btn("Delete",  RED_LIGHT,   on_click=self._on_delete)
        for b in (self._add_btn, self._insert_btn, self._replace_btn, self._delete_btn):
            actions.addWidget(b)
        actions.addStretch()
        body.addLayout(actions)

        # Validation + face
        face_col = QVBoxLayout(); face_col.setSpacing(6)
        self._validation_label = QLabel("✓ No Errors Found")
        self._validation_label.setFont(inter(10, QFont.Weight.DemiBold))
        self._validation_label.setStyleSheet(
            f"color: {GREEN}; background: transparent;")
        self._validation_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        face_col.addWidget(self._validation_label)
        self._face = _CircularClockFace()
        self._face.slot_clicked.connect(self._on_face_slot_clicked)
        face_col.addWidget(self._face, 1)
        body.addLayout(face_col, 1)

        v.addLayout(body, 1)

        # Bottom toggles
        toggles = QHBoxLayout(); toggles.setSpacing(12)
        self._loop_chk = QCheckBox("Loop / Cycle clock elements")
        self._loop_chk.setFont(inter(9))
        self._loop_chk.setStyleSheet(self._chk_qss())
        self._loop_chk.setChecked(True)
        toggles.addWidget(self._loop_chk)
        self._show_only_chk = QCheckBox("Show only song descriptions")
        self._show_only_chk.setFont(inter(9))
        self._show_only_chk.setStyleSheet(self._chk_qss())
        toggles.addWidget(self._show_only_chk)
        toggles.addStretch()
        v.addLayout(toggles)

        return f

    def _action_btn(self, label: str, color: str, on_click) -> QPushButton:
        b = QPushButton(label)
        b.setFixedSize(96, 36)
        b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        b.setFont(inter(11, QFont.Weight.Bold))
        b.setStyleSheet(
            f"QPushButton {{ background: {rgba(color, 0.20)}; "
            f"color: {color}; "
            f"border: 1px solid {rgba(color, 0.50)}; "
            f"border-radius: 6px; }}"
            f"QPushButton:hover {{ background: {rgba(color, 0.32)}; }}"
            f"QPushButton:disabled {{ background: rgba(255,255,255,0.04); "
            f"color: {TEXT_DIM}; border-color: rgba(255,255,255,0.08); }}"
        )
        b.clicked.connect(on_click)
        return b

    @staticmethod
    def _spin_qss() -> str:
        return (
            f"QSpinBox {{ background: {BG_CARD_DK}; "
            f"color: {TEXT_PRI}; "
            f"border: 1px solid {BORDER}; "
            f"border-radius: 4px; padding: 0 6px; max-width: 70px; }}"
        )

    @staticmethod
    def _list_qss() -> str:
        return (
            f"QListWidget {{ background: {BG_CARD_DK}; "
            f"color: {TEXT_PRI}; "
            f"border: 1px solid {BORDER}; "
            f"border-radius: 4px; padding: 4px; }}"
            f"QListWidget::item {{ padding: 4px; border-radius: 2px; }}"
            f"QListWidget::item:selected {{ background: {rgba(AMBER, 0.20)}; "
            f"color: {AMBER}; }}"
        )

    @staticmethod
    def _chk_qss() -> str:
        return f"QCheckBox {{ color: {TEXT_SEC}; background: transparent; }}"

    def _cap(self, label: str) -> QLabel:
        l = QLabel(label)
        l.setFont(inter(8, QFont.Weight.Bold, letter_spacing=0.6))
        l.setStyleSheet(f"color: {TEXT_DIM}; background: transparent;")
        return l

    # ── Filter spec → JSON ──────────────────────────────────────────────

    def _current_filter_spec(self) -> dict:
        spec = {
            "sound_code": self._filter_sound_code.currentData(),
            "era":        self._filter_era.currentData(),
            "vocal":      self._filter_vocal.currentData(),
            "year_min":     self._filter_year_lo.value(),
            "year_max":     self._filter_year_hi.value(),
            "priority_min": self._filter_priority_lo.value(),
            "priority_max": self._filter_priority_hi.value(),
            "bpm_min":      self._filter_bpm_lo.value(),
            "bpm_max":      self._filter_bpm_hi.value(),
        }
        return spec

    def _refresh_filter_count(self, *_):
        from core.scheduler.engine import SchedulerEngine
        sch = self._scheduler or SchedulerEngine(db=self._db)
        spec = self._current_filter_spec()
        try:
            songs = sch._songs_matching_filter_json(json.dumps(spec))
        except Exception as exc:
            log.debug(f"filter count failed: {exc}")
            songs = []
        n = len(songs)
        avg_ms = sum(int(s.get("duration_ms") or 0) for s in songs) / max(1, n)
        avg_s = avg_ms / 1000.0
        self._filter_count_label.setText(
            f"{n} Songs Available · {avg_s:.1f}s Estimated Avg Duration")
        # Songs Found list
        self._songs_found.clear()
        for s in songs[:60]:
            label = f"{s.get('artist', '—')} — {s.get('title', '—')}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, int(s.get("id") or 0))
            self._songs_found.addItem(item)

    def _on_reset_filters(self):
        for cb_attr in ("_filter_sound_code", "_filter_era", "_filter_vocal"):
            cb = getattr(self, cb_attr)
            cb.setCurrentIndex(0)
        for lo_attr, hi_attr in [
            ("_filter_year_lo", "_filter_year_hi"),
            ("_filter_priority_lo", "_filter_priority_hi"),
            ("_filter_bpm_lo", "_filter_bpm_hi"),
        ]:
            lo = getattr(self, lo_attr); hi = getattr(self, hi_attr)
            lo.setValue(lo.minimum()); hi.setValue(hi.maximum())
        self._refresh_filter_count()

    def _refresh_song_search(self, text: str):
        text = text.strip()
        self._song_list.clear()
        try:
            sql = ("SELECT id, title, artist FROM songs "
                   "WHERE is_enabled = 1")
            params: list = []
            if text:
                sql += " AND (title LIKE ? OR artist LIKE ?)"
                params += [f"%{text}%", f"%{text}%"]
            sql += " ORDER BY artist, title LIMIT 80"
            rows = self._db._conn().execute(sql, params).fetchall()
        except Exception:
            rows = []
        for r in rows:
            label = f"{r['artist'] or '—'} — {r['title'] or '—'}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, int(r["id"]))
            self._song_list.addItem(item)

    # ── Action handlers ─────────────────────────────────────────────────

    def _on_type_button(self, slot_type: str):
        self._selected_slot_type = slot_type
        for t, b in self._type_buttons.items():
            b.setStyleSheet(self._type_btn_qss(
                SLOT_TYPE_COLOR[t], active=(t == slot_type)))

    def _make_slot_from_current_tab(self) -> Optional[dict]:
        """Construct a new slot dict reflecting the current tab + slot type."""
        slot_type = self._selected_slot_type
        # Find the next minute_position (cumulative)
        used_min = sum(_CircularClockFace._slot_minutes(s) for s in self._slots)
        next_min = int(used_min) % 60
        base = {
            "slot_type": slot_type,
            "category_id": None,
            "energy_pref": "Any", "vocal_pref": "Any",
            "priority_pref": "Normal",
            "is_break": 1 if slot_type == "Spot" else 0,
            "item_id": 0,
            "minute_position": next_min,
            "selection_mode": "random_from_category",
            "filter_json": None,
            "specific_song_id": None,
            "specific_artist_id": None,
            "duration_seconds": None,
            "ref_text": None,
        }
        # Map "Spot" → backend's "Break" slot_type for picker dispatch
        if slot_type == "Spot":
            base["slot_type"] = "Break"

        tab_idx = self._tabs.currentIndex()
        if tab_idx == 0:    # Filters
            spec = self._current_filter_spec()
            base["filter_json"] = json.dumps(spec)
            base["selection_mode"] = "random_from_category"
        elif tab_idx == 1:  # Song Tracks
            item = self._song_list.currentItem()
            if item is None:
                QMessageBox.information(
                    self, "No song selected",
                    "Pick a song from the list before clicking Add.")
                return None
            base["specific_song_id"] = int(item.data(Qt.ItemDataRole.UserRole))
            base["selection_mode"] = "specific"
        elif tab_idx == 2:  # Artists
            item = self._artist_list.currentItem()
            if item is None:
                QMessageBox.information(
                    self, "No artist selected",
                    "Pick an artist from the list before clicking Add.")
                return None
            # We store the artist NAME as specific_artist_id field — though
            # the column is INTEGER, picker code falls back to artist-name
            # lookup. (Schema-wise an `artists` table would be cleaner;
            # F-Final S1 didn't introduce that yet.)
            base["specific_artist_id"] = 0    # marker — name picker uses fallback
            base["ref_text"] = str(item.data(Qt.ItemDataRole.UserRole))
            base["selection_mode"] = "specific"
        return base

    def _on_add(self):
        slot = self._make_slot_from_current_tab()
        if slot is None:
            return
        self._slots.append(slot)
        self._selected_slot_idx = len(self._slots) - 1
        self._refresh_face()

    def _on_insert(self):
        slot = self._make_slot_from_current_tab()
        if slot is None:
            return
        idx = self._selected_slot_idx if self._selected_slot_idx is not None else len(self._slots)
        self._slots.insert(idx, slot)
        self._selected_slot_idx = idx
        self._refresh_face()

    def _on_replace(self):
        if self._selected_slot_idx is None:
            QMessageBox.information(
                self, "No slot selected", "Click a slot on the clock face first.")
            return
        slot = self._make_slot_from_current_tab()
        if slot is None:
            return
        # Preserve minute_position from the original
        slot["minute_position"] = self._slots[self._selected_slot_idx].get(
            "minute_position", 0)
        self._slots[self._selected_slot_idx] = slot
        self._refresh_face()

    def _on_delete(self):
        if self._selected_slot_idx is None:
            return
        del self._slots[self._selected_slot_idx]
        if not self._slots:
            self._selected_slot_idx = None
        else:
            self._selected_slot_idx = max(0, self._selected_slot_idx - 1)
        self._refresh_face()

    def _on_face_slot_clicked(self, idx: int):
        self._selected_slot_idx = idx
        self._refresh_face()

    def _refresh_face(self):
        self._face.set_slots(self._slots, self._selected_slot_idx)
        # Validation
        n = len(self._slots)
        if n == 0:
            self._validation_label.setText("⚠ No slots — add at least one")
            self._validation_label.setStyleSheet(
                f"color: {AMBER}; background: transparent;")
        else:
            self._validation_label.setText(f"✓ No Errors Found · {n} slots")
            self._validation_label.setStyleSheet(
                f"color: {GREEN}; background: transparent;")

    # ── Load / Save ─────────────────────────────────────────────────────

    def _load_clock(self, clock_id: int):
        try:
            row = self._db.get_clock(int(clock_id))
        except Exception as exc:
            log.warning(f"get_clock failed: {exc}"); return
        if row is None:
            return
        clock = dict(row)
        self._top_form.set_data(clock)
        self._loop_chk.setChecked(bool(clock.get("loop_cycle_enabled", 1)))
        self._show_only_chk.setChecked(bool(clock.get("show_only_descriptions", 0)))
        try:
            slot_rows = self._db.get_clock_slots(int(clock_id))
        except Exception:
            slot_rows = []
        self._slots = [dict(r) for r in slot_rows]
        self._selected_slot_idx = 0 if self._slots else None
        self._refresh_face()
        self._refresh_filter_count()

    def _on_ok(self):
        # Save clock fields
        data = self._top_form.get_data()
        data["loop_cycle_enabled"] = 1 if self._loop_chk.isChecked() else 0
        data["show_only_descriptions"] = 1 if self._show_only_chk.isChecked() else 0
        try:
            if self._clock_id is None:
                # Create new clock with the form name, then update its
                # other fields + persist slots.
                self._clock_id = self._db.create_clock(data["name"])
            self._db.save_clock(int(self._clock_id), data)
            self._db.save_clock_slots(int(self._clock_id), self._slots)
        except Exception as exc:
            log.warning(f"save failed: {exc}")
            QMessageBox.warning(self, "Save failed", str(exc))
            return
        log.info(
            f"[clock-editor-dialog] saved clock id={self._clock_id} "
            f"name={data['name']!r} slots={len(self._slots)}")
        self.accept()

    @property
    def clock_id(self) -> Optional[int]:
        return self._clock_id
