"""
RadioAI Studio Pro — Edit Categories Dialog
Figma node 32:2 (640×560).

Two-pane category editor:
  Left pane  — list of categories with color dot + name + description + count badge
  Right pane — edit form: name + color swatches + description + auto-rotate +
               min-separation + songs preview

Built on BaseDialog so it adapts to small screens with a scrollable middle.
"""

import logging
from typing import List, Optional

from PyQt6.QtCore import Qt, QRectF, pyqtSignal
from core import dialogs
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QPainterPath, QFont, QCursor, QLinearGradient,
)
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QLineEdit, QComboBox,
    QHBoxLayout, QVBoxLayout, QGridLayout, QScrollArea, QMessageBox,
    QInputDialog,
)

from ui.widgets._tokens import (
    inter, mono, rgba,
    TEXT_PRI, TEXT_SEC, TEXT_MUTED, TEXT_DIM,
    CYAN, CYAN_LIGHT, GREEN, AMBER, AMBER_LIGHT, RED, RED_LIGHT,
    PURPLE, PURPLE_LIGHT,
)
from ui.dialogs.base_dialog import BaseDialog

log = logging.getLogger("EditCategoriesDialog")

INPUT_BG = "#0a0c18"
INPUT_BORDER = "#1c1f38"

# Air-time preset chips: (label, hour_start, hour_end) — daily (day_of_week=None)
DAYPART_PRESETS = [
    ("Morning Drive 06-10", 6, 10),
    ("Midday 10-14",        10, 14),
    ("Afternoon 14-18",     14, 18),
    ("Evening 18-23",       18, 23),
    ("Late Night 23-02",    23, 2),   # overnight wrap (h2 <= h1)
]
DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# 10 swatch colors (Figma)
SWATCH_COLORS = [
    "#f59e0b",   # 1 Orange
    "#06b6d4",   # 2 Cyan
    "#a78bfa",   # 3 Purple
    "#10b981",   # 4 Green
    "#ec4899",   # 5 Pink
    "#14b8a6",   # 6 Teal
    "#d946ef",   # 7 Magenta
    "#f43f5e",   # 8 Red
    "#3b82f6",   # 9 Blue
    "#84cc16",   # 10 Lime
]


# ════════════════════════════════════════════════════════════════════════════
# Header logo — small purple equalizer bars
# ════════════════════════════════════════════════════════════════════════════

class _HeaderLogo(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(28, 28)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, 28, 28), 6, 6)
        p.setClipPath(path)
        p.fillRect(QRectF(0, 0, 28, 28), QColor("#1e1535"))
        # 5 bars (heights 4, 8, 12, 8, 4) — purple
        p.setBrush(QColor(PURPLE_LIGHT))
        p.setPen(Qt.PenStyle.NoPen)
        for x_off, h in [(5, 4), (10, 8), (15, 12), (20, 8), (25, 4)]:
            top = (28 - h) // 2
            p.drawRoundedRect(QRectF(x_off - 1.5, top, 3, h), 1, 1)


# ════════════════════════════════════════════════════════════════════════════
# Category list row
# ════════════════════════════════════════════════════════════════════════════

class _CategoryRow(QFrame):

    clicked = pyqtSignal(int)

    def __init__(self, category: dict, row_index: int, parent=None):
        super().__init__(parent)
        self._cat = category
        self._row_index = row_index
        self._selected = False
        self._hover = False
        self.setFixedHeight(56)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

    def set_selected(self, sel: bool):
        self._selected = sel
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._cat.get("id", 0))
        super().mousePressEvent(e)

    def enterEvent(self, e): self._hover = True; self.update(); super().enterEvent(e)
    def leaveEvent(self, e): self._hover = False; self.update(); super().leaveEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0, 0, self.width(), 56)
        # Background
        if self._selected:
            p.fillRect(rect, QColor("#1e1b35"))
            p.fillRect(0, 0, 3, 56, QColor(PURPLE))
        else:
            bg = "#0d0f1c" if self._row_index % 2 else "#0b0d1a"
            p.fillRect(rect, QColor(bg))
            if self._hover:
                p.fillRect(rect, QColor(255, 255, 255, 6))

        # Color dot at (18, 18) 20×20
        dot_color = QColor(self._cat.get("color") or "#8b5cf6")
        p.setBrush(dot_color); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(18, 18, 20, 20)
        # Numeric badge inside dot
        p.setPen(QColor(0, 0, 0, 230))
        p.setFont(inter(8, QFont.Weight.Bold))
        p.drawText(QRectF(18, 18, 20, 20), Qt.AlignmentFlag.AlignCenter,
                   str(self._row_index + 1))

        # Name + description
        name_color = QColor(TEXT_PRI) if self._selected else QColor(TEXT_SEC)
        p.setPen(name_color)
        font_name = inter(13, QFont.Weight.DemiBold if self._selected else QFont.Weight.Normal)
        p.setFont(font_name)
        p.drawText(46, 8, 170, 18,
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   self._cat.get("name", "—"))
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(inter(9))
        p.drawText(46, 28, 170, 14,
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   self._cat.get("description") or "")

        # Songs count badge (right side, x=222)
        count = self._cat.get("songs_count", 0)
        badge_text = f"{count} song{'s' if count != 1 else ''}"
        if self._selected:
            badge_bg = QColor("#1e1535")
            badge_fg = QColor(PURPLE_LIGHT)
        else:
            badge_bg = QColor(INPUT_BORDER)
            badge_fg = QColor(TEXT_MUTED)
        p.setBrush(badge_bg); p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(222, 17, 50, 22), 6, 6)
        p.setPen(badge_fg)
        p.setFont(inter(8, QFont.Weight.Medium))
        p.drawText(QRectF(222, 17, 50, 22), Qt.AlignmentFlag.AlignCenter, badge_text)

        # Bottom hairline
        p.setPen(QPen(QColor(28, 31, 56, 128), 1))
        p.drawLine(0, 55, int(self.width()), 55)


# ════════════════════════════════════════════════════════════════════════════
# Color swatch
# ════════════════════════════════════════════════════════════════════════════

class _ColorSwatch(QPushButton):

    swatch_clicked = pyqtSignal(str)

    def __init__(self, color: str, parent=None):
        super().__init__("", parent)
        self._color = QColor(color)
        self._color_hex = color
        self._selected = False
        self.setFixedSize(26, 26)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFlat(True)
        self.setStyleSheet("background: transparent; border: none;")

    def set_selected(self, sel: bool):
        self._selected = sel
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.swatch_clicked.emit(self._color_hex)
        super().mousePressEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Outer ring (white when selected, transparent otherwise)
        if self._selected:
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor("#ffffff"), 2))
            p.drawEllipse(2, 2, 22, 22)
            # Glow halo
            halo = QColor(self._color); halo.setAlphaF(0.5)
            p.setPen(QPen(halo, 4))
            p.drawEllipse(0, 0, 26, 26)
        # Inner color circle
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self._color)
        if self._selected:
            p.drawEllipse(4, 4, 18, 18)
        else:
            p.drawEllipse(2, 2, 22, 22)


# ════════════════════════════════════════════════════════════════════════════
# Songs preview list inside the right panel
# ════════════════════════════════════════════════════════════════════════════

class _SongsPreview(QFrame):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(60)
        self.setStyleSheet(
            f"QFrame {{ background: #131626; border-radius: 6px; }}"
        )
        self._artists: List[str] = []
        self._extra_count: int = 0

    def set_data(self, artists: List[str], total: int):
        self._artists = artists
        self._extra_count = max(0, total - len(artists))
        self.update()

    def paintEvent(self, _e):
        super().paintEvent(_e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Bullet list
        for i, name in enumerate(self._artists[:5]):
            y = 8 + i * 9
            # Dot
            p.setBrush(QColor(TEXT_MUTED))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(8, y + 2, 4, 4)
            # Name
            p.setPen(QColor(TEXT_MUTED))
            p.setFont(inter(8))
            p.drawText(18, y - 2, 200, 12,
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       name)
        # "+ N more..." in purple at bottom-right
        if self._extra_count > 0:
            p.setPen(QColor(PURPLE_LIGHT))
            p.setFont(inter(8))
            p.drawText(self.width() - 80, 0, 70, int(self.height()),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                       f"+ {self._extra_count} more...")


# ════════════════════════════════════════════════════════════════════════════
# Main dialog
# ════════════════════════════════════════════════════════════════════════════

class EditCategoriesDialog(BaseDialog):

    categories_changed = pyqtSignal()

    HEADER_H = 50
    FOOTER_H = 26  # tiny info strip at bottom (per Figma)

    def __init__(self, parent=None, db=None):
        self._db = db
        self._categories: List[dict] = []
        self._row_widgets: List[_CategoryRow] = []
        self._selected_id: Optional[int] = None
        self._selected_color = "#f59e0b"

        # Refs
        self._list_layout: Optional[QVBoxLayout] = None
        self._count_label: Optional[QLabel] = None
        self._name_input: Optional[QLineEdit] = None
        self._desc_input: Optional[QLineEdit] = None
        self._rotate_combo: Optional[QComboBox] = None
        self._sep_combo: Optional[QComboBox] = None
        self._songs_preview: Optional[_SongsPreview] = None
        self._songs_count_badge: Optional[QLabel] = None
        self._swatches: List[_ColorSwatch] = []

        # Air-time (auto-grid) daypart tags for the selected category:
        # list of (day_of_week_or_None, hour_start, hour_end)
        self._dayparts: List[tuple] = []
        self._preset_chips: List[QPushButton] = []
        self._dp_start_combo: Optional[QComboBox] = None
        self._dp_end_combo: Optional[QComboBox] = None
        self._dp_day_combo: Optional[QComboBox] = None
        self._pills_grid = None          # QGridLayout of current tag pills
        self._pills_empty_hint: Optional[QLabel] = None

        super().__init__(target_size=(640, 560), parent=parent)
        self._load_categories()

    # ── Header ────────────────────────────────────────────────────────────

    def _build_header(self) -> QWidget:
        f = QFrame()
        f.setStyleSheet(
            f"QFrame {{ background: #0d0f1e; "
            f"border-bottom: 1px solid #1c1f38; }}"
        )
        h = QHBoxLayout(f)
        h.setContentsMargins(14, 10, 10, 10)
        h.setSpacing(10)

        h.addWidget(_HeaderLogo())

        title_box = QWidget(); title_box.setStyleSheet("background: transparent;")
        tv = QVBoxLayout(title_box); tv.setContentsMargins(0, 0, 0, 0); tv.setSpacing(2)
        title = QLabel("SONG CATEGORIES")
        title.setFont(inter(15, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        sub = QLabel("Create and manage song rotation categories")
        sub.setFont(inter(10))
        sub.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        tv.addWidget(title); tv.addWidget(sub)
        h.addWidget(title_box)
        h.addStretch()

        x = QPushButton("✕")
        x.setFixedSize(22, 28)
        x.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        x.setFont(inter(11, QFont.Weight.Bold))
        x.setStyleSheet(
            f"QPushButton {{ background: #1c1f38; color: {TEXT_SEC}; "
            f"border: none; border-radius: 6px; }}"
            f"QPushButton:hover {{ background: {rgba(RED, 0.20)}; color: {RED_LIGHT}; }}"
        )
        x.clicked.connect(self.reject)
        h.addWidget(x)
        return f

    # ── Content ───────────────────────────────────────────────────────────

    def _build_content(self) -> QWidget:
        c = QFrame()
        c.setStyleSheet("background: transparent;")
        outer = QHBoxLayout(c)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)
        outer.addWidget(self._build_left_pane(),  stretch=44)
        outer.addWidget(self._build_right_pane(), stretch=56)
        return c

    # ── Left pane — categories list ───────────────────────────────────────

    def _build_left_pane(self) -> QWidget:
        wrap = QFrame()
        wrap.setStyleSheet(
            f"QFrame {{ background: #0b0d1a; border-radius: 8px; }}"
        )
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # Header strip
        hdr = QFrame()
        hdr.setFixedHeight(32)
        hdr.setStyleSheet(f"QFrame {{ background: #131626; "
                          f"border-top-left-radius: 8px; border-top-right-radius: 8px; }}")
        hh = QHBoxLayout(hdr)
        hh.setContentsMargins(10, 0, 10, 0); hh.setSpacing(0)
        hl = QLabel("CATEGORIES")
        hl.setFont(inter(9, QFont.Weight.Bold, letter_spacing=0.8))
        hl.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        hh.addWidget(hl)
        hh.addStretch()
        self._count_label = QLabel("0 total")
        self._count_label.setFont(mono(9))
        self._count_label.setStyleSheet(f"color: {TEXT_DIM}; background: transparent;")
        hh.addWidget(self._count_label)
        v.addWidget(hdr)

        # Scrollable rows
        list_scroll = QScrollArea()
        list_scroll.setWidgetResizable(True)
        list_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        list_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        list_scroll.setFrameShape(QFrame.Shape.NoFrame)
        list_scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            f"QScrollBar:vertical {{ background: {rgba('#ffffff', 0.02)}; width: 6px; }}"
            f"QScrollBar::handle:vertical {{ background: {rgba(PURPLE_LIGHT, 0.5)}; "
            f"border-radius: 3px; min-height: 24px; }}"
            "QScrollBar::add-line, QScrollBar::sub-line { height: 0; }"
        )
        list_widget = QWidget(); list_widget.setStyleSheet("background: transparent;")
        self._list_layout = QVBoxLayout(list_widget)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(0)
        self._list_layout.addStretch()
        list_scroll.setWidget(list_widget)
        v.addWidget(list_scroll, stretch=1)

        # Action buttons row
        actions = QFrame()
        actions.setFixedHeight(40)
        actions.setStyleSheet("QFrame { background: transparent; }")
        ah = QHBoxLayout(actions)
        ah.setContentsMargins(0, 5, 0, 5); ah.setSpacing(6)

        add_btn = self._action_button("+ Add",   GREEN, "#052e16")
        add_btn.clicked.connect(self._on_add)
        ah.addWidget(add_btn)

        rename_btn = self._action_button("✎ Rename", AMBER, "#2d1a00")
        rename_btn.clicked.connect(self._on_rename)
        ah.addWidget(rename_btn)

        delete_btn = self._action_button("✕ Delete", RED, "#1f0a12")
        delete_btn.clicked.connect(self._on_delete)
        ah.addWidget(delete_btn)
        v.addWidget(actions)
        return wrap

    def _action_button(self, text: str, color: str, bg: str) -> QPushButton:
        b = QPushButton(text)
        b.setFixedSize(86, 30)
        b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        b.setFont(inter(11, QFont.Weight.DemiBold))
        b.setStyleSheet(
            f"QPushButton {{ background: {bg}; color: {color}; "
            f"border: none; border-left: 2px solid {color}; border-radius: 7px; }}"
            f"QPushButton:hover {{ background: {rgba(color, 0.30)}; }}"
        )
        return b

    # ── Right pane — edit form ────────────────────────────────────────────

    def _build_right_pane(self) -> QWidget:
        wrap = QFrame()
        wrap.setStyleSheet(
            f"QFrame {{ background: #0b0d1a; border-radius: 8px; }}"
        )
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # Header strip
        hdr = QFrame()
        hdr.setFixedHeight(32)
        hdr.setStyleSheet(f"QFrame {{ background: #131626; "
                          f"border-top-left-radius: 8px; border-top-right-radius: 8px; }}")
        hh = QHBoxLayout(hdr)
        hh.setContentsMargins(10, 0, 10, 0); hh.setSpacing(0)
        hl = QLabel("EDIT CATEGORY")
        hl.setFont(inter(9, QFont.Weight.Bold, letter_spacing=0.8))
        hl.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        hh.addWidget(hl)
        v.addWidget(hdr)

        # Scrollable form
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            f"QScrollBar:vertical {{ background: {rgba('#ffffff', 0.02)}; width: 6px; }}"
            f"QScrollBar::handle:vertical {{ background: {rgba(PURPLE_LIGHT, 0.5)}; "
            f"border-radius: 3px; min-height: 24px; }}"
            "QScrollBar::add-line, QScrollBar::sub-line { height: 0; }"
        )
        form = QWidget(); form.setStyleSheet("background: transparent;")
        fv = QVBoxLayout(form)
        fv.setContentsMargins(8, 8, 8, 8)
        fv.setSpacing(10)

        # Category Name *
        fv.addWidget(self._field_label("Category Name *", required=True))
        self._name_input = self._make_input("Category name")
        fv.addWidget(self._name_input)

        # Category Color
        fv.addWidget(self._field_label("Category Color"))
        sw_row = QHBoxLayout()
        sw_row.setContentsMargins(0, 0, 0, 0); sw_row.setSpacing(4)
        for col in SWATCH_COLORS:
            sw = _ColorSwatch(col)
            sw.swatch_clicked.connect(self._on_color_picked)
            self._swatches.append(sw)
            sw_row.addWidget(sw)
        sw_row.addStretch()
        fv.addLayout(sw_row)

        # Description
        fv.addWidget(self._field_label("Description"))
        self._desc_input = self._make_input("Optional description")
        fv.addWidget(self._desc_input)

        # Auto-Rotate Songs
        fv.addWidget(self._field_label("Auto-Rotate Songs"))
        self._rotate_combo = self._make_combo([
            "Rotate after 1 play (strict)",
            "Rotate after 2 plays",
            "Rotate after 3 plays",
            "No auto-rotation",
        ])
        fv.addWidget(self._rotate_combo)

        # Min Separation Time
        fv.addWidget(self._field_label("Min Separation Time"))
        self._sep_combo = self._make_combo([
            "30 minutes", "60 minutes", "90 minutes",
            "120 minutes", "180 minutes", "240 minutes",
        ])
        self._sep_combo.setCurrentText("120 minutes")
        fv.addWidget(self._sep_combo)

        # Songs in this category
        songs_row = QHBoxLayout()
        songs_row.setSpacing(6)
        sl = self._field_label("Songs in this category")
        songs_row.addWidget(sl)
        songs_row.addStretch()
        self._songs_count_badge = QLabel("0 songs")
        self._songs_count_badge.setFixedHeight(18)
        self._songs_count_badge.setFont(inter(8, QFont.Weight.DemiBold))
        self._songs_count_badge.setStyleSheet(
            f"QLabel {{ background: #2d1a00; color: {AMBER}; "
            f"border-radius: 6px; padding: 0 8px; }}"
        )
        songs_row.addWidget(self._songs_count_badge)
        fv.addLayout(songs_row)

        self._songs_preview = _SongsPreview()
        fv.addWidget(self._songs_preview)

        # ── AIR TIME (AUTO-GRID) ──────────────────────────────────────────
        fv.addSpacing(2)
        air_hdr = QLabel("AIR TIME (AUTO-GRID)")
        air_hdr.setFont(inter(9, QFont.Weight.Bold, letter_spacing=0.8))
        air_hdr.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        air_hdr.setFixedHeight(13)
        fv.addWidget(air_hdr)

        # Preset chips (toggle daily dayparts) — 3 + 2 across two rows
        self._preset_chips = []
        for chunk in (DAYPART_PRESETS[:3], DAYPART_PRESETS[3:]):
            chip_row = QHBoxLayout()
            chip_row.setContentsMargins(0, 0, 0, 0); chip_row.setSpacing(4)
            for label, h1, h2 in chunk:
                chip = self._make_preset_chip(label, h1, h2)
                self._preset_chips.append(chip)
                chip_row.addWidget(chip)
            chip_row.addStretch()
            fv.addLayout(chip_row)

        # Custom row: start hour · end hour · day · + Add
        custom_row = QHBoxLayout()
        custom_row.setContentsMargins(0, 0, 0, 0); custom_row.setSpacing(4)
        self._dp_start_combo = self._make_combo(
            [f"{h:02d}:00" for h in range(24)])
        self._dp_start_combo.setFixedWidth(66)
        self._dp_start_combo.setCurrentIndex(6)
        custom_row.addWidget(self._dp_start_combo)
        arrow = QLabel("→")
        arrow.setFont(inter(10))
        arrow.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        custom_row.addWidget(arrow)
        self._dp_end_combo = self._make_combo(
            [f"{h:02d}:00" for h in range(24)])
        self._dp_end_combo.setFixedWidth(66)
        self._dp_end_combo.setCurrentIndex(10)
        custom_row.addWidget(self._dp_end_combo)
        self._dp_day_combo = self._make_combo(
            ["Every day"] + list(DAY_NAMES))
        self._dp_day_combo.setFixedWidth(92)
        custom_row.addWidget(self._dp_day_combo)
        add_dp = QPushButton("+ Add")
        add_dp.setFixedSize(52, 30)
        add_dp.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        add_dp.setFont(inter(10, QFont.Weight.DemiBold))
        add_dp.setStyleSheet(
            f"QPushButton {{ background: #052e16; color: {GREEN}; "
            f"border: none; border-left: 2px solid {GREEN}; border-radius: 7px; }}"
            f"QPushButton:hover {{ background: {rgba(GREEN, 0.30)}; }}"
        )
        add_dp.clicked.connect(self._on_add_daypart)
        custom_row.addWidget(add_dp)
        custom_row.addStretch()
        fv.addLayout(custom_row)

        # Current tags — pill grid (2 columns), × on a pill removes it
        pills_wrap = QWidget(); pills_wrap.setStyleSheet("background: transparent;")
        self._pills_grid = QGridLayout(pills_wrap)
        self._pills_grid.setContentsMargins(0, 0, 0, 0)
        self._pills_grid.setHorizontalSpacing(4)
        self._pills_grid.setVerticalSpacing(4)
        fv.addWidget(pills_wrap)
        self._pills_empty_hint = QLabel(
            "No air-time tags — auto-grid leaves the schedule untouched")
        self._pills_empty_hint.setFont(inter(8))
        self._pills_empty_hint.setStyleSheet(
            f"color: {TEXT_DIM}; background: transparent;")
        fv.addWidget(self._pills_empty_hint)

        # Save Category button
        save = QPushButton("✓  Save Category")
        save.setFixedHeight(34)
        save.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        save.setFont(inter(12, QFont.Weight.DemiBold))
        save.setStyleSheet(
            f"QPushButton {{ background: qlineargradient("
            f"x1:0,y1:0,x2:0,y2:1, stop:0 {PURPLE_LIGHT}, stop:0.5 {PURPLE}, stop:1 #7c3aed); "
            f"color: white; border: none; border-radius: 8px; }}"
            f"QPushButton:hover {{ background: qlineargradient("
            f"x1:0,y1:0,x2:0,y2:1, stop:0 #c4b5fd, stop:1 {PURPLE}); }}"
            f"QPushButton:disabled {{ background: #252848; color: {TEXT_MUTED}; }}"
        )
        save.clicked.connect(self._on_save)
        self._save_btn_ref = save  # for _flash_save_success
        fv.addSpacing(4)
        fv.addWidget(save)
        fv.addStretch()

        scroll.setWidget(form)
        v.addWidget(scroll, stretch=1)
        return wrap

    def _field_label(self, text: str, required: bool = False) -> QLabel:
        l = QLabel(text)
        l.setFont(inter(10, QFont.Weight.Medium))
        l.setStyleSheet(f"color: {TEXT_SEC}; background: transparent;")
        l.setFixedHeight(13)
        return l

    def _make_input(self, placeholder: str) -> QLineEdit:
        e = QLineEdit()
        e.setPlaceholderText(placeholder)
        e.setFixedHeight(30)
        e.setFont(inter(11))
        e.setStyleSheet(
            f"QLineEdit {{ background: {INPUT_BG}; color: {TEXT_PRI}; "
            f"border: 1px solid {rgba(INPUT_BORDER, 0.7)}; border-radius: 6px; "
            f"padding: 0 8px; selection-background-color: {rgba(CYAN, 0.25)}; }}"
            f"QLineEdit:focus {{ border-color: {CYAN}; }}"
        )
        return e

    def _make_combo(self, items: list) -> QComboBox:
        c = QComboBox(); c.addItems(items); c.setFixedHeight(30); c.setFont(inter(10))
        c.setStyleSheet(
            f"QComboBox {{ background: {INPUT_BG}; color: {TEXT_SEC}; "
            f"border: 1px solid {rgba(INPUT_BORDER, 0.6)}; border-radius: 6px; "
            f"padding: 0 22px 0 8px; }}"
            f"QComboBox:focus {{ border-color: {CYAN}; }}"
            f"QComboBox::drop-down {{ border: none; width: 16px; }}"
            f"QComboBox::down-arrow {{ image: none; width: 0; height: 0; "
            f"border-left: 4px solid transparent; border-right: 4px solid transparent; "
            f"border-top: 5px solid {TEXT_MUTED}; margin-right: 6px; }}"
            f"QComboBox QAbstractItemView {{ background: {INPUT_BG}; color: {TEXT_PRI}; "
            f"border: 1px solid {INPUT_BORDER}; border-radius: 5px; "
            f"selection-background-color: {rgba(CYAN, 0.20)}; selection-color: {CYAN_LIGHT}; "
            f"outline: none; padding: 4px; }}"
        )
        return c

    # ── Air time (auto-grid) helpers ──────────────────────────────────────

    def _make_preset_chip(self, label: str, h1: int, h2: int) -> QPushButton:
        chip = QPushButton(label)
        chip.setCheckable(True)
        chip.setFixedHeight(22)
        chip.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        chip.setFont(inter(8, QFont.Weight.Medium))
        chip.setStyleSheet(
            f"QPushButton {{ background: {INPUT_BG}; color: {TEXT_SEC}; "
            f"border: 1px solid {rgba(INPUT_BORDER, 0.7)}; "
            f"border-radius: 11px; padding: 0 8px; }}"
            f"QPushButton:hover {{ border-color: {rgba(PURPLE, 0.7)}; }}"
            f"QPushButton:checked {{ background: {rgba(PURPLE, 0.25)}; "
            f"color: {PURPLE_LIGHT}; border: 1px solid {PURPLE}; }}"
        )
        chip.clicked.connect(lambda _c, a=h1, b=h2: self._toggle_preset(a, b))
        return chip

    def _toggle_preset(self, h1: int, h2: int):
        tag = (None, h1, h2)
        if tag in self._dayparts:
            self._dayparts.remove(tag)
        else:
            self._dayparts.append(tag)
        self._refresh_daypart_ui()

    def _on_add_daypart(self):
        h1 = self._dp_start_combo.currentIndex()
        h2 = self._dp_end_combo.currentIndex()
        day_ix = self._dp_day_combo.currentIndex()
        dow = None if day_ix == 0 else day_ix - 1   # Every day → None, Mon..Sun → 0..6
        if h1 == h2:
            dialogs.warning(self, "Invalid range",
                            "Start and end hour must be different.")
            return
        tag = (dow, h1, h2)   # h2 <= h1 = overnight wrap (backend supported)
        if tag in self._dayparts:
            return
        self._dayparts.append(tag)
        self._refresh_daypart_ui()

    def _remove_daypart(self, tag: tuple):
        if tag in self._dayparts:
            self._dayparts.remove(tag)
        self._refresh_daypart_ui()

    def _daypart_label(self, tag: tuple) -> str:
        dow, h1, h2 = tag
        day = "Daily" if dow is None else DAY_NAMES[int(dow) % 7]
        return f"{day} {h1:02d}:00-{h2:02d}:00"

    def _refresh_daypart_ui(self):
        """Sync preset chips + rebuild the tag pill grid from _dayparts."""
        # Preset chips reflect active state from the list
        for chip, (_lbl, h1, h2) in zip(self._preset_chips, DAYPART_PRESETS):
            chip.setChecked((None, h1, h2) in self._dayparts)
        # Rebuild pills
        if self._pills_grid is None:
            return
        while self._pills_grid.count():
            item = self._pills_grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        for i, tag in enumerate(self._dayparts):
            pill = QPushButton(f"{self._daypart_label(tag)}  ×")
            pill.setFixedHeight(20)
            pill.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            pill.setFont(mono(8))
            pill.setStyleSheet(
                f"QPushButton {{ background: #131626; color: {TEXT_SEC}; "
                f"border: 1px solid {rgba(INPUT_BORDER, 0.7)}; "
                f"border-radius: 10px; padding: 0 8px; text-align: center; }}"
                f"QPushButton:hover {{ background: {rgba(RED, 0.18)}; "
                f"color: {RED_LIGHT}; border-color: {rgba(RED, 0.5)}; }}"
            )
            pill.setToolTip("Click to remove this air-time tag")
            pill.clicked.connect(lambda _c, t=tag: self._remove_daypart(t))
            self._pills_grid.addWidget(
                pill, i // 2, i % 2, Qt.AlignmentFlag.AlignLeft)
        if self._pills_empty_hint:
            self._pills_empty_hint.setVisible(not self._dayparts)

    # ── Footer ────────────────────────────────────────────────────────────

    def _build_footer(self) -> QWidget:
        f = QFrame()
        f.setStyleSheet(
            f"QFrame {{ background: #0d0f1e; border-top: 1px solid #1c1f38; }}"
        )
        h = QHBoxLayout(f)
        h.setContentsMargins(12, 4, 8, 4); h.setSpacing(8)

        info = QLabel("Changes are saved immediately to the database")
        info.setFont(inter(9))
        info.setStyleSheet(f"color: {TEXT_DIM}; background: transparent;")
        h.addWidget(info)
        h.addStretch()

        close = QPushButton("✕  Close")
        close.setFixedSize(72, 22)
        close.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        close.setFont(inter(11, QFont.Weight.Medium))
        close.setStyleSheet(
            f"QPushButton {{ background: #1c1f38; color: {TEXT_SEC}; "
            f"border: none; border-radius: 6px; }}"
            f"QPushButton:hover {{ background: #252848; color: {TEXT_PRI}; }}"
        )
        close.clicked.connect(self.reject)
        h.addWidget(close)
        return f

    # ── Data ──────────────────────────────────────────────────────────────

    def _load_categories(self):
        try:
            rows = self._db.get_categories()
            self._categories = [self._row_to_dict(r) for r in rows]
        except Exception as exc:
            log.error(f"get_categories failed: {exc}")
            self._categories = []
        self._populate_list()
        # Preserve the user's selection across reloads. Only fall back to
        # the first row if the current selection is gone (e.g. just deleted)
        # or this is the first load.
        if not self._categories:
            return
        existing_ids = {c["id"] for c in self._categories}
        target_id = (
            self._selected_id
            if self._selected_id in existing_ids
            else self._categories[0]["id"]
        )
        self._select_category(target_id)

    def _row_to_dict(self, r) -> dict:
        return {
            "id":          r["id"],
            "name":        r["name"] or "",
            "color":       r["color"] if "color" in r.keys() else "#8b5cf6",
            "description": r["description"] if "description" in r.keys() else "",
            "songs_count": int(r["song_count"]) if "song_count" in r.keys() else 0,
        }

    def _populate_list(self):
        for w in self._row_widgets:
            w.setParent(None); w.deleteLater()
        self._row_widgets.clear()
        for i, cat in enumerate(self._categories):
            row = _CategoryRow(cat, i)
            row.clicked.connect(self._select_category)
            self._list_layout.insertWidget(self._list_layout.count() - 1, row)
            self._row_widgets.append(row)
        if self._count_label:
            self._count_label.setText(f"{len(self._categories)} total")

    def _select_category(self, cat_id: int):
        self._selected_id = cat_id
        for r in self._row_widgets:
            r.set_selected(r._cat.get("id") == cat_id)
        cat = next((c for c in self._categories if c["id"] == cat_id), None)
        if cat:
            self._update_form(cat)

    def _update_form(self, cat: dict):
        if self._name_input: self._name_input.setText(cat.get("name", ""))
        if self._desc_input: self._desc_input.setText(cat.get("description") or "")
        # Color swatch selection — pick the closest swatch (or none)
        self._selected_color = cat.get("color") or "#8b5cf6"
        for sw in self._swatches:
            sw.set_selected(sw._color_hex.lower() == (self._selected_color or "").lower())

        # Songs preview
        try:
            songs = self._db.get_songs_by_category(cat["id"], limit=5)
            artists = []
            for s in songs:
                a = s["artist"] if "artist" in s.keys() else None
                if a:
                    artists.append(a)
            total = cat.get("songs_count", 0)
            if self._songs_preview:
                self._songs_preview.set_data(artists, total)
            if self._songs_count_badge:
                self._songs_count_badge.setText(f"{total} song{'s' if total != 1 else ''}")
        except Exception as exc:
            log.error(f"songs preview failed: {exc}")

        # Air-time daypart tags for this category
        try:
            parts = self._db.get_category_dayparts(cat["id"])
            self._dayparts = [
                (None if p["day_of_week"] is None else int(p["day_of_week"]),
                 int(p["hour_start"]), int(p["hour_end"]))
                for p in parts
            ]
        except Exception as exc:
            log.error(f"dayparts load failed: {exc}")
            self._dayparts = []
        self._refresh_daypart_ui()

    def _on_color_picked(self, hex_color: str):
        self._selected_color = hex_color
        for sw in self._swatches:
            sw.set_selected(sw._color_hex.lower() == hex_color.lower())

    # ── Actions ───────────────────────────────────────────────────────────

    def _on_add(self):
        name = dialogs.text_input(self, "Add category", "Category name:",
                          placeholder="My Category")
        if not name or not name.strip():
            return
        try:
            new_id = self._db.add_category({
                "name": name.strip(),
                "color": "#8b5cf6",
                "description": "",
            })
            self._load_categories()
            self._select_category(new_id)
            self.categories_changed.emit()
        except Exception as exc:
            dialogs.error(self, "Add failed", f"Could not add category:\n\n{exc}")

    def _on_rename(self):
        if not self._selected_id:
            return
        cat = next((c for c in self._categories if c["id"] == self._selected_id), None)
        if not cat:
            return
        new_name = dialogs.text_input(
            self, "Rename category", "New name:",
            default=cat.get("name", ""))
        if not new_name or not new_name.strip():
            return
        try:
            self._db.update_category(self._selected_id, {"name": new_name.strip()})
            self._load_categories()
            self._select_category(self._selected_id)
            self.categories_changed.emit()
        except Exception as exc:
            dialogs.error(self, "Rename failed", f"Could not rename:\n\n{exc}")

    def _on_delete(self):
        if not self._selected_id:
            return
        cat = next((c for c in self._categories if c["id"] == self._selected_id), None)
        if not cat:
            return
        if len(self._categories) <= 1:
            dialogs.info(
                self, "Cannot delete",
                "You must keep at least one category. Add another one first.",
            )
            return
        count = cat.get("songs_count", 0)
        msg = f"Delete the '{cat['name']}' category?"
        if count > 0:
            msg += f"\n\n{count} song{'s' if count != 1 else ''} currently in this category will be unassigned."
        if not dialogs.confirm(self, "Delete category", msg,
                       danger=True, yes_label="Delete"):
            return
        try:
            self._db.delete_category(self._selected_id, reassign_to=None)
            self._load_categories()
            self.categories_changed.emit()
        except Exception as exc:
            dialogs.error(self, "Delete failed", f"Could not delete:\n\n{exc}")

    def _on_save(self):
        log.info("=" * 50)
        log.info("[SAVE] button clicked")
        log.info(f"[SAVE] selected_id={self._selected_id}")

        if not self._selected_id:
            log.warning("[SAVE] FAIL: no category selected")
            dialogs.info(self, "No category selected",
                                     "Click a category in the list first.")
            return

        name = self._name_input.text().strip()
        color = self._selected_color
        description = self._desc_input.text().strip() or None

        log.info(f"[SAVE] form: name='{name}'  color='{color}'  desc='{description}'")

        if not name:
            log.warning("[SAVE] FAIL: empty name")
            dialogs.warning(self, "Required field", "Category name cannot be empty.")
            self._name_input.setFocus()
            return

        # Uniqueness check (excluding self)
        for c in self._categories:
            if c["id"] != self._selected_id and c["name"].lower() == name.lower():
                log.warning(f"[SAVE] FAIL: duplicate name '{name}'")
                dialogs.warning(self, "Duplicate name",
                                    f"Another category called '{name}' already exists.")
                return

        try:
            log.info("[SAVE] calling db.update_category()...")
            self._db.update_category(self._selected_id, {
                "name": name,
                "color": color,
                "description": description,
            })
            log.info("[SAVE] db.update_category() returned OK")
        except Exception as exc:
            log.error(f"[SAVE] EXCEPTION: {exc}", exc_info=True)
            dialogs.error(self, "Save failed", f"Could not save:\n\n{exc}")
            return

        # Persist air-time tags + rebuild the auto grid. A grid-build
        # failure must never block the category save — warn in the log.
        grid_note = ""
        try:
            self._db.set_category_dayparts(
                self._selected_id, list(self._dayparts))
            log.info(f"[SAVE] dayparts saved: {self._dayparts}")
        except Exception as exc:
            log.error(f"[SAVE] set_category_dayparts failed: {exc}",
                      exc_info=True)
            dialogs.warning(
                self, "Air time not saved",
                f"Category saved, but the air-time tags could not "
                f"be stored:\n\n{exc}")
        else:
            try:
                from core.auto_grid_builder import build_grid
                summary = build_grid(self._db)
                log.info(f"[SAVE] auto-grid rebuilt: {summary}")
                if isinstance(summary, dict) and not summary.get("error"):
                    grid_note = (f" · grid: {summary.get('placed', 0)} placed, "
                                 f"{summary.get('cleared', 0)} cleared")
            except Exception as exc:
                log.warning(f"[SAVE] auto-grid rebuild failed "
                            f"(save kept): {exc}")

        # Reload — _load_categories now preserves current selection
        saved_id = self._selected_id
        self._load_categories()
        self.categories_changed.emit()
        log.info(f"[SAVE] DONE — category id={saved_id} saved as '{name}'")

        # Visible success feedback — flash the Save button green for 1 second
        self._flash_save_success(name, grid_note)

    def _flash_save_success(self, name: str, extra: str = ""):
        """Show a brief 'Saved' confirmation on the Save button."""
        if not hasattr(self, "_save_btn_ref") or self._save_btn_ref is None:
            return
        btn = self._save_btn_ref
        original_text = btn.text()
        original_style = btn.styleSheet()
        btn.setText(f"✓  Saved '{name}'{extra}")
        btn.setStyleSheet(
            f"QPushButton {{ background: qlineargradient("
            f"x1:0,y1:0,x2:0,y2:1, stop:0 #34d399, stop:1 #059669); "
            f"color: white; border: none; border-radius: 8px; }}"
        )

        from PyQt6.QtCore import QTimer
        def _restore():
            try:
                btn.setText(original_text)
                btn.setStyleSheet(original_style)
            except Exception:
                pass
        QTimer.singleShot(1200, _restore)
