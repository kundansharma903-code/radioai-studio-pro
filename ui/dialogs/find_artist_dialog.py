"""
RadioAI Studio Pro — Find Artist Dialog
Figma node 218:46 (640×600).

Modal dialog for searching and selecting an existing artist. Built on
BaseDialog so it adapts to small screens with a scrollable artist list.

Features:
- Live search by name / country / genre
- Filter pills (All / Recently Added / Most Played / Favorites)
- Artist row: avatar + name + meta + ★ favorite + songs count badge
- Click row → select. Double-click → select + close.
- "+ Add New" → opens AddArtistDialog, refreshes list, auto-selects new
- "Select" button → emits artist_selected(id, name)
"""

import logging
from typing import Optional, List

from PyQt6.QtCore import Qt, QRectF, pyqtSignal
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QPainterPath, QFont, QCursor, QLinearGradient,
)
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QLineEdit,
    QHBoxLayout, QVBoxLayout, QScrollArea, QSizePolicy,
)

from ui.widgets._tokens import (
    inter, mono, rgba,
    TEXT_PRI, TEXT_SEC, TEXT_MUTED,
    CYAN, CYAN_LIGHT, GREEN, GREEN_LIGHT, AMBER,
    PURPLE, PURPLE_LIGHT, RED, RED_LIGHT,
)
from ui.dialogs.base_dialog import BaseDialog

log = logging.getLogger("FindArtistDialog")

INPUT_BG = "#0e1020"
INPUT_BORDER = "#1c1f38"
ROW_H = 40

# Avatar color palette — cycled by first letter to keep it visually varied
_AVATAR_COLORS = [
    ("#06b6d4", "#0891b2"),  # cyan
    ("#10b981", "#059669"),  # green
    ("#f59e0b", "#d97706"),  # amber
    ("#8b5cf6", "#7c3aed"),  # purple
    ("#ec4899", "#db2777"),  # pink
    ("#f43f5e", "#e11d48"),  # red
    ("#14b8a6", "#0d9488"),  # teal
]


def _avatar_colors_for(letter: str) -> tuple:
    if not letter:
        return _AVATAR_COLORS[0]
    return _AVATAR_COLORS[(ord(letter.upper()) - ord("A")) % len(_AVATAR_COLORS)]


# ════════════════════════════════════════════════════════════════════════════
# Header search-icon logo (32×32 cyan)
# ════════════════════════════════════════════════════════════════════════════

class _SearchHeaderIcon(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(32, 32)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Rounded square cyan gradient
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, 32, 32), 7, 7)
        p.setClipPath(path)
        g = QLinearGradient(0, 0, 32, 32)
        g.setColorAt(0.0, QColor(CYAN_LIGHT))
        g.setColorAt(0.7, QColor(CYAN))
        p.fillRect(QRectF(0, 0, 32, 32), g)
        # Magnifying glass — circle + handle
        p.setClipping(False)
        p.setPen(QPen(QColor(255, 255, 255, 235), 2.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(7, 7, 13, 13))
        p.drawLine(18, 18, 24, 24)


# ════════════════════════════════════════════════════════════════════════════
# Filter pill (toggleable)
# ════════════════════════════════════════════════════════════════════════════

class _FilterPill(QPushButton):

    toggled_active = pyqtSignal(str)

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self._active = False
        self.setFixedHeight(28)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFlat(True)
        self.setStyleSheet("background: transparent; border: none;")
        self.setFont(inter(10, QFont.Weight.Bold, letter_spacing=0.3))
        # Auto-size based on text
        from PyQt6.QtGui import QFontMetrics
        fm = QFontMetrics(self.font())
        self.setFixedWidth(fm.horizontalAdvance(text) + 22)

    def set_active(self, active: bool):
        self._active = active
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.toggled_active.emit(self.text())
        super().mousePressEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        path = QPainterPath()
        path.addRoundedRect(rect, 14, 14)
        p.setClipPath(path)

        if self._active:
            g = QLinearGradient(0, 0, 0, self.height())
            c1 = QColor(CYAN); c1.setAlphaF(0.20)
            c2 = QColor(CYAN); c2.setAlphaF(0.06)
            g.setColorAt(0.0, c1); g.setColorAt(1.0, c2)
            p.fillRect(self.rect(), g)
            p.setClipping(False)
            bc = QColor(CYAN); bc.setAlphaF(0.40)
            p.setPen(QPen(bc, 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(rect, 14, 14)
            p.setPen(QColor(CYAN_LIGHT))
        else:
            p.fillRect(self.rect(), QColor(INPUT_BORDER))
            p.setClipping(False)
            p.setPen(QColor(TEXT_SEC))

        p.setFont(self.font())
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text())


# ════════════════════════════════════════════════════════════════════════════
# Artist row
# ════════════════════════════════════════════════════════════════════════════

class _ArtistRow(QFrame):

    clicked         = pyqtSignal(int)   # artist_id (single-click)
    double_clicked  = pyqtSignal(int)   # artist_id (double-click → confirm)
    favorite_toggled = pyqtSignal(int)  # artist_id

    def __init__(self, artist: dict, row_index: int, parent=None):
        super().__init__(parent)
        self._artist = artist
        self._row_index = row_index
        self._selected = False
        self._hover = False
        self.setFixedSize(592, ROW_H)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setMouseTracking(True)

    def set_selected(self, sel: bool):
        self._selected = sel
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0, 0, 592, ROW_H)
        path = QPainterPath()
        path.addRoundedRect(rect, 6, 6)
        p.setClipPath(path)

        # Background
        if self._selected:
            bg = QColor(8, 51, 68); bg.setAlphaF(0.5)
            p.fillRect(rect, bg)
        elif self._row_index % 2 == 1:
            c = QColor("#0d0f1e"); c.setAlphaF(0.4)
            p.fillRect(rect, c)
        if self._hover and not self._selected:
            p.fillRect(rect, QColor(255, 255, 255, 8))

        # 3px cyan left bar when selected
        if self._selected:
            p.setClipping(False)
            p.fillRect(0, 0, 3, ROW_H, QColor(CYAN))
            p.setClipping(True)

        # Avatar circle (24×24 at x=12, y=8)
        first_letter = (self._artist.get("name") or "?")[0].upper()
        c1, c2 = _avatar_colors_for(first_letter)
        ag = QLinearGradient(12, 8, 36, 32)
        ag.setColorAt(0.0, QColor(c1))
        ag.setColorAt(1.0, QColor(c2))
        p.setBrush(ag); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(12, 8, 24, 24)
        # Initial letter
        p.setPen(QColor(255, 255, 255))
        p.setFont(inter(11, QFont.Weight.Black))
        p.drawText(QRectF(12, 8, 24, 24), Qt.AlignmentFlag.AlignCenter, first_letter)

        # Name
        name_color = QColor(CYAN_LIGHT) if self._selected else QColor(TEXT_PRI)
        p.setPen(name_color)
        p.setFont(inter(12, QFont.Weight.Bold))
        p.drawText(46, 4, 460, 18,
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   self._artist.get("name") or "—")

        # Meta line
        meta_parts = []
        if self._artist.get("country"):
            meta_parts.append(self._artist["country"])
        if self._artist.get("primary_genre"):
            meta_parts.append(self._artist["primary_genre"])
        # Active marker
        meta_parts.append("Active" if self._artist.get("songs_count", 0) > 0 else "New")
        meta = "  •  ".join(meta_parts)
        p.setPen(QColor(TEXT_SEC))
        p.setFont(inter(10))
        p.drawText(46, 22, 460, 14,
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   meta)

        # ★ favorite (right side, x=532)
        if self._artist.get("is_favorite"):
            p.setPen(QColor(AMBER))
            p.setFont(inter(11, QFont.Weight.Bold))
            p.drawText(532, 0, 14, ROW_H,
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignCenter,
                       "★")

        # Songs count badge (28×18 at x=555)
        p.setBrush(QColor(INPUT_BORDER))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(555, 11, 28, 18), 9, 9)
        p.setPen(QColor(CYAN))
        p.setFont(mono(9, bold=True))
        p.drawText(QRectF(555, 11, 28, 18),
                   Qt.AlignmentFlag.AlignCenter,
                   str(self._artist.get("songs_count", 0)))

    def enterEvent(self, e): self._hover = True; self.update(); super().enterEvent(e)
    def leaveEvent(self, e): self._hover = False; self.update(); super().leaveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            # Toggle favorite if click was inside the ★ area (x=528..548)
            if 528 <= e.position().x() <= 548 and self._artist.get("is_favorite"):
                self.favorite_toggled.emit(self._artist.get("id", 0))
            else:
                self.clicked.emit(self._artist.get("id", 0))
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit(self._artist.get("id", 0))
        super().mouseDoubleClickEvent(e)


# ════════════════════════════════════════════════════════════════════════════
# Find Artist Dialog
# ════════════════════════════════════════════════════════════════════════════

class FindArtistDialog(BaseDialog):

    artist_selected = pyqtSignal(int, str)

    HEADER_H = 60
    FOOTER_H = 60

    def __init__(self, parent=None, db=None):
        self._db = db
        self._artists: List[dict] = []
        self._row_widgets: List[_ArtistRow] = []
        self._selected_id: Optional[int] = None
        self._active_filter = "All Artists"
        self._search_text = ""

        # Refs
        self._search_input: Optional[QLineEdit] = None
        self._stats_label: Optional[QLabel] = None
        self._filter_pills: dict = {}
        self._list_layout: Optional[QVBoxLayout] = None
        self._select_btn: Optional[QPushButton] = None

        super().__init__(target_size=(640, 600), parent=parent)
        self._load_artists()

    # ── Header ────────────────────────────────────────────────────────────

    def _build_header(self) -> QWidget:
        f = QFrame()
        f.setStyleSheet(
            "QFrame { background: qlineargradient(x1:0,y1:0,x2:0,y2:1, "
            "stop:0 rgba(19,22,38,0.95), stop:1 rgba(14,16,32,0.95)); "
            f"border-bottom: 1px solid {rgba('#ffffff', 0.06)}; }}"
        )
        h = QHBoxLayout(f)
        h.setContentsMargins(16, 12, 14, 12)
        h.setSpacing(12)

        h.addWidget(_SearchHeaderIcon())

        title_box = QWidget(); title_box.setStyleSheet("background: transparent;")
        tv = QVBoxLayout(title_box); tv.setContentsMargins(0, 0, 0, 0); tv.setSpacing(2)
        title = QLabel("FIND ARTIST")
        title.setFont(inter(18, QFont.Weight.Black, letter_spacing=0.5))
        title.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        sub = QLabel("Search existing artists in library")
        sub.setFont(inter(11, QFont.Weight.Medium))
        sub.setStyleSheet(f"color: {TEXT_SEC}; background: transparent;")
        tv.addWidget(title); tv.addWidget(sub)
        h.addWidget(title_box)
        h.addStretch()

        x = QPushButton("✕")
        x.setFixedSize(24, 24)
        x.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        x.setFont(inter(12, QFont.Weight.Bold))
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
        v = QVBoxLayout(c)
        v.setContentsMargins(23, 19, 23, 12)
        v.setSpacing(12)

        # Search bar
        self._search_input = QLineEdit()
        self._search_input.setFixedHeight(44)
        self._search_input.setPlaceholderText("🔎    Search by name, country, genre...")
        self._search_input.setFont(inter(13, QFont.Weight.Medium))
        self._search_input.setStyleSheet(
            f"QLineEdit {{ background: {INPUT_BG}; color: {TEXT_PRI}; "
            f"border: 1.5px solid {rgba(CYAN, 0.40)}; border-radius: 8px; "
            f"padding-left: 16px; padding-right: 16px; "
            f"selection-background-color: {rgba(CYAN, 0.25)}; }}"
            f"QLineEdit:focus {{ border-color: {CYAN}; }}"
        )
        self._search_input.textChanged.connect(self._on_search_changed)
        v.addWidget(self._search_input)

        # Filter pills row
        pill_row = QHBoxLayout()
        pill_row.setSpacing(8)
        pill_row.setContentsMargins(0, 0, 0, 0)
        for name in ["All Artists", "Recently Added", "Most Played", "Favorites"]:
            pill = _FilterPill(name)
            pill.set_active(name == "All Artists")
            pill.toggled_active.connect(self._on_filter_pill)
            self._filter_pills[name] = pill
            pill_row.addWidget(pill)
        pill_row.addStretch()
        v.addLayout(pill_row)

        # Scrollable list
        list_scroll = QScrollArea()
        list_scroll.setWidgetResizable(True)
        list_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        list_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        list_scroll.setFrameShape(QFrame.Shape.NoFrame)
        list_scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            f"QScrollBar:vertical {{ background: {rgba('#ffffff', 0.02)}; width: 6px; }}"
            f"QScrollBar::handle:vertical {{ background: {rgba(CYAN, 0.45)}; "
            f"border-radius: 3px; min-height: 30px; }}"
            f"QScrollBar::handle:vertical:hover {{ background: {rgba(CYAN, 0.70)}; }}"
            "QScrollBar::add-line, QScrollBar::sub-line { height: 0; }"
        )
        list_widget = QWidget()
        list_widget.setStyleSheet("background: transparent;")
        self._list_layout = QVBoxLayout(list_widget)
        self._list_layout.setContentsMargins(0, 4, 0, 4)
        self._list_layout.setSpacing(4)
        self._list_layout.addStretch()
        list_scroll.setWidget(list_widget)
        v.addWidget(list_scroll, stretch=1)

        return c

    # ── Footer ────────────────────────────────────────────────────────────

    def _build_footer(self) -> QWidget:
        f = QFrame()
        f.setStyleSheet(
            "QFrame { background: qlineargradient(x1:0,y1:0,x2:0,y2:1, "
            "stop:0 rgba(19,22,38,0.95), stop:1 rgba(14,16,32,0.95)); "
            f"border-top: 1px solid {rgba('#ffffff', 0.06)}; }}"
        )
        h = QHBoxLayout(f)
        h.setContentsMargins(16, 14, 16, 14); h.setSpacing(12)

        self._stats_label = QLabel("0 of 0 artists")
        self._stats_label.setFont(inter(10, QFont.Weight.Medium))
        self._stats_label.setStyleSheet(f"color: {TEXT_SEC}; background: transparent;")
        h.addWidget(self._stats_label)
        h.addStretch()

        # + Add New (green outline)
        add_btn = QPushButton("+  Add New")
        add_btn.setFixedSize(130, 32)
        add_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        add_btn.setFont(inter(12, QFont.Weight.Bold))
        add_btn.setStyleSheet(
            f"QPushButton {{ background: qlineargradient("
            f"x1:0,y1:0,x2:1,y2:0, stop:0 {rgba(GREEN, 0.18)}, stop:1 {rgba(GREEN, 0.06)}); "
            f"color: {GREEN}; border: 1px solid {rgba(GREEN, 0.30)}; "
            f"border-radius: 8px; }}"
            f"QPushButton:hover {{ background: {rgba(GREEN, 0.30)}; }}"
        )
        add_btn.clicked.connect(self._on_add_new)
        h.addWidget(add_btn)

        cancel = QPushButton("Cancel")
        cancel.setFixedSize(80, 32)
        cancel.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        cancel.setFont(inter(12, QFont.Weight.Bold))
        cancel.setStyleSheet(
            f"QPushButton {{ background: #1c1f38; color: {TEXT_SEC}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; border-radius: 8px; }}"
            f"QPushButton:hover {{ background: #252848; color: {TEXT_PRI}; }}"
        )
        cancel.clicked.connect(self.reject)
        h.addWidget(cancel)

        self._select_btn = QPushButton("✓  Select")
        self._select_btn.setFixedSize(100, 32)
        self._select_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._select_btn.setFont(inter(12, QFont.Weight.Bold))
        self._select_btn.setStyleSheet(
            f"QPushButton {{ background: qlineargradient("
            f"x1:0,y1:0,x2:0,y2:1, stop:0 {CYAN}, stop:1 #0891b2); "
            f"color: white; border: none; border-radius: 8px; }}"
            f"QPushButton:hover {{ background: qlineargradient("
            f"x1:0,y1:0,x2:0,y2:1, stop:0 {CYAN_LIGHT}, stop:1 {CYAN}); }}"
            f"QPushButton:disabled {{ background: #252848; color: {TEXT_MUTED}; }}"
        )
        self._select_btn.clicked.connect(self._on_select)
        self._select_btn.setEnabled(False)
        h.addWidget(self._select_btn)
        return f

    # ── Data ──────────────────────────────────────────────────────────────

    def _load_artists(self):
        try:
            rows = self._db.get_all_artists()
            self._artists = [self._row_to_dict(r) for r in rows]
        except Exception as exc:
            log.error(f"get_all_artists failed: {exc}")
            self._artists = []
        self._populate_list()

    def _row_to_dict(self, r) -> dict:
        return {
            "id":            r["id"],
            "name":          r["name"] or "",
            "display_name":  r["display_name"] if "display_name" in r.keys() else None,
            "country":       r["country"] if "country" in r.keys() else None,
            "primary_genre": r["primary_genre"] if "primary_genre" in r.keys() else None,
            "era":           r["era"] if "era" in r.keys() else None,
            "is_favorite":   bool(r["is_favorite"]) if "is_favorite" in r.keys() else False,
            "songs_count":   int(r["songs_count"]) if "songs_count" in r.keys() else 0,
        }

    def _populate_list(self):
        # Clear existing rows
        for w in self._row_widgets:
            w.setParent(None); w.deleteLater()
        self._row_widgets.clear()

        visible = self._filtered_artists()
        for i, artist in enumerate(visible):
            row = _ArtistRow(artist, i)
            row.clicked.connect(self._on_row_click)
            row.double_clicked.connect(self._on_row_double_click)
            row.favorite_toggled.connect(self._on_favorite_toggled)
            self._list_layout.insertWidget(self._list_layout.count() - 1, row)
            self._row_widgets.append(row)

        # Update stats label
        if self._stats_label:
            total = len(self._artists)
            self._stats_label.setText(f"{len(visible)} of {total} artist{'s' if total != 1 else ''}")

        # If we had a selection, restore it
        if self._selected_id is not None:
            for r in self._row_widgets:
                if r._artist.get("id") == self._selected_id:
                    r.set_selected(True)
                    break

    def _filtered_artists(self) -> List[dict]:
        result = list(self._artists)
        # Search filter
        if self._search_text:
            q = self._search_text.lower()
            result = [
                a for a in result
                if q in (a.get("name") or "").lower()
                or q in (a.get("country") or "").lower()
                or q in (a.get("primary_genre") or "").lower()
            ]
        # Filter pill
        if self._active_filter == "Favorites":
            result = [a for a in result if a.get("is_favorite")]
        elif self._active_filter == "Most Played":
            result = sorted(result, key=lambda a: -a.get("songs_count", 0))
        elif self._active_filter == "Recently Added":
            result = sorted(result, key=lambda a: -a.get("id", 0))
        return result

    # ── Behavior ──────────────────────────────────────────────────────────

    def _on_search_changed(self, text: str):
        self._search_text = text.strip()
        self._populate_list()

    def _on_filter_pill(self, name: str):
        for n, p in self._filter_pills.items():
            p.set_active(n == name)
        self._active_filter = name
        self._populate_list()

    def _on_row_click(self, artist_id: int):
        self._selected_id = artist_id
        for row in self._row_widgets:
            row.set_selected(row._artist.get("id") == artist_id)
        if self._select_btn:
            self._select_btn.setEnabled(True)

    def _on_row_double_click(self, artist_id: int):
        self._on_row_click(artist_id)
        self._on_select()

    def _on_favorite_toggled(self, artist_id: int):
        try:
            new_val = self._db.toggle_artist_favorite(artist_id)
            for a in self._artists:
                if a.get("id") == artist_id:
                    a["is_favorite"] = new_val
                    break
            self._populate_list()
        except Exception as exc:
            log.error(f"toggle favorite failed: {exc}")

    def _on_add_new(self):
        from ui.dialogs.add_artist_dialog import AddArtistDialog
        prefill = self._search_text  # if user typed a name in search, prefill it
        dlg = AddArtistDialog(parent=self, db=self._db, prefill_name=prefill)
        dlg.artist_saved.connect(self._on_new_artist_added)
        dlg.exec()

    def _on_new_artist_added(self, artist_id: int, name: str):
        # Reload list and auto-select new artist
        self._load_artists()
        self._on_row_click(artist_id)

    def _on_select(self):
        if self._selected_id is None:
            return
        artist = next((a for a in self._artists if a.get("id") == self._selected_id), None)
        if artist:
            self.artist_selected.emit(artist["id"], artist["name"])
        self.accept()
