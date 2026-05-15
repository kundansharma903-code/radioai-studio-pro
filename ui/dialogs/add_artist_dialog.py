"""
RadioAI Studio Pro — Add Artist Dialog
Figma node 218:2 (560×540).

Modal dialog for creating a new artist record. Built on BaseDialog
so it adapts to small screens with a scrollable middle zone.
"""

import logging
from typing import Optional

from PyQt6.QtCore import Qt, QRectF, pyqtSignal
from core import dialogs
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QPainterPath, QFont, QCursor,
)
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QLineEdit, QComboBox, QTextEdit,
    QHBoxLayout, QVBoxLayout, QMessageBox,
)

from ui.widgets._tokens import (
    inter, rgba,
    TEXT_PRI, TEXT_SEC, TEXT_MUTED,
    CYAN, PURPLE, PURPLE_LIGHT, GREEN, RED, RED_LIGHT,
)
from ui.dialogs.base_dialog import BaseDialog

log = logging.getLogger("AddArtistDialog")

INPUT_BG = "#0e1020"
INPUT_BORDER = "#1c1f38"

COUNTRIES = [
    "Select country...", "India", "USA", "UK", "Canada", "Australia",
    "France", "Germany", "Spain", "Italy", "Brazil", "Japan", "South Korea",
    "Pakistan", "Bangladesh", "Sri Lanka", "Netherlands", "Sweden",
    "Norway", "Mexico", "Russia", "China", "Other",
]
GENRES = [
    "Select genre...", "Pop", "Rock", "Hip-Hop", "R&B", "Electronic",
    "Jazz", "Classical", "Country", "Folk", "Indie", "Reggae",
    "Bollywood", "Devotional", "Ghazal", "Qawwali", "Bhajan",
    "Sufi", "Punjabi", "Other",
]
ERAS = [
    "Select era...", "60s", "70s", "80s", "90s", "2000s", "2010s", "2020s",
]


# ════════════════════════════════════════════════════════════════════════════
# Header logo — purple gradient with person silhouette
# ════════════════════════════════════════════════════════════════════════════

class _ArtistHeaderIcon(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(32, 32)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Rounded square
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, 32, 32), 7, 7)
        p.setClipPath(path)
        # Purple gradient
        from PyQt6.QtGui import QLinearGradient
        g = QLinearGradient(0, 0, 32, 32)
        g.setColorAt(0.0,   QColor("#a78bfa"))
        g.setColorAt(0.50,  QColor("#7c3aed"))
        g.setColorAt(1.0,   QColor("#5b21b6"))
        p.fillRect(QRectF(0, 0, 32, 32), g)
        # Person silhouette (head + shoulders)
        p.setBrush(QColor(255, 255, 255, 235))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(11, 7, 10, 10))    # head
        # Shoulders/torso (rounded trapezoid)
        torso = QPainterPath()
        torso.moveTo(7, 27)
        torso.cubicTo(7, 19, 11, 17, 16, 17)
        torso.cubicTo(21, 17, 25, 19, 25, 27)
        torso.lineTo(7, 27)
        torso.closeSubpath()
        p.fillPath(torso, QColor(255, 255, 255, 235))


# ════════════════════════════════════════════════════════════════════════════
# Helpers
# ════════════════════════════════════════════════════════════════════════════

def _label(text: str, required: bool = False) -> QLabel:
    if required:
        l = QLabel(f"{text} <span style='color:{RED};'>*</span>")
    else:
        l = QLabel(text)
    l.setFont(inter(11, QFont.Weight.Bold))
    l.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
    l.setFixedHeight(14)
    return l


def _make_input(placeholder: str, height: int = 36) -> QLineEdit:
    e = QLineEdit()
    e.setPlaceholderText(placeholder)
    e.setFixedHeight(height)
    e.setFont(inter(11))
    e.setStyleSheet(
        f"QLineEdit {{ background: {INPUT_BG}; color: {TEXT_PRI}; "
        f"border: 1px solid {INPUT_BORDER}; border-radius: 6px; "
        f"padding: 0 11px; selection-background-color: {rgba(CYAN, 0.25)}; }}"
        f"QLineEdit:focus {{ border-color: {CYAN}; background: #06080f; }}"
    )
    return e


def _make_combo(items: list, height: int = 32) -> QComboBox:
    c = QComboBox()
    c.addItems(items)
    c.setFixedHeight(height)
    c.setFont(inter(11))
    c.setStyleSheet(
        f"QComboBox {{ background: {INPUT_BG}; color: {TEXT_PRI}; "
        f"border: 1px solid {INPUT_BORDER}; border-radius: 6px; "
        f"padding: 0 24px 0 11px; }}"
        f"QComboBox:focus {{ border-color: {CYAN}; }}"
        f"QComboBox::drop-down {{ border: none; width: 20px; }}"
        f"QComboBox::down-arrow {{ image: none; width: 0; height: 0; "
        f"border-left: 4px solid transparent; border-right: 4px solid transparent; "
        f"border-top: 5px solid {TEXT_MUTED}; margin-right: 8px; }}"
        f"QComboBox QAbstractItemView {{ background: {INPUT_BG}; color: {TEXT_PRI}; "
        f"border: 1px solid {INPUT_BORDER}; border-radius: 5px; "
        f"selection-background-color: {rgba(CYAN, 0.20)}; selection-color: #22d3ee; "
        f"outline: none; padding: 4px; }}"
    )
    return c


# ════════════════════════════════════════════════════════════════════════════
# Dialog
# ════════════════════════════════════════════════════════════════════════════

class AddArtistDialog(BaseDialog):

    artist_saved = pyqtSignal(int, str)   # (artist_id, name)

    HEADER_H = 60
    FOOTER_H = 60

    def __init__(self, parent=None, db=None, prefill_name: str = ""):
        self._db = db
        self._prefill_name = prefill_name
        # Refs
        self._name_input: Optional[QLineEdit] = None
        self._display_input: Optional[QLineEdit] = None
        self._country_combo: Optional[QComboBox] = None
        self._genre_combo: Optional[QComboBox] = None
        self._era_combo: Optional[QComboBox] = None
        self._notes_box: Optional[QTextEdit] = None
        super().__init__(target_size=(560, 540), parent=parent)

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

        h.addWidget(_ArtistHeaderIcon())

        title_box = QWidget(); title_box.setStyleSheet("background: transparent;")
        tv = QVBoxLayout(title_box)
        tv.setContentsMargins(0, 0, 0, 0); tv.setSpacing(2)
        title = QLabel("NEW ARTIST")
        title.setFont(inter(18, QFont.Weight.Black, letter_spacing=0.5))
        title.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        sub = QLabel("Add a new artist to your library")
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

    # ── Content (scrollable) ──────────────────────────────────────────────

    def _build_content(self) -> QWidget:
        c = QFrame()
        c.setStyleSheet("background: transparent;")
        v = QVBoxLayout(c)
        v.setContentsMargins(23, 18, 23, 18)
        v.setSpacing(14)

        # Artist Name (required)
        v.addWidget(_label("Artist Name", required=True))
        self._name_input = _make_input("Enter artist full name...")
        if self._prefill_name:
            self._name_input.setText(self._prefill_name)
        v.addWidget(self._name_input)
        v.addSpacing(4)

        # Display Name + Country (2 cols)
        row = QHBoxLayout()
        row.setSpacing(16)
        # Display Name
        dn_col = QWidget(); dn_col.setStyleSheet("background: transparent;")
        dn_v = QVBoxLayout(dn_col); dn_v.setContentsMargins(0, 0, 0, 0); dn_v.setSpacing(4)
        dn_v.addWidget(_label("Display Name"))
        self._display_input = _make_input("Optional short name", height=32)
        dn_v.addWidget(self._display_input)
        row.addWidget(dn_col, stretch=1)
        # Country
        cn_col = QWidget(); cn_col.setStyleSheet("background: transparent;")
        cn_v = QVBoxLayout(cn_col); cn_v.setContentsMargins(0, 0, 0, 0); cn_v.setSpacing(4)
        cn_v.addWidget(_label("Country"))
        self._country_combo = _make_combo(COUNTRIES)
        cn_v.addWidget(self._country_combo)
        row.addWidget(cn_col, stretch=1)
        v.addLayout(row)

        # Primary Genre + Era (2 cols)
        row = QHBoxLayout()
        row.setSpacing(16)
        # Genre
        gn_col = QWidget(); gn_col.setStyleSheet("background: transparent;")
        gn_v = QVBoxLayout(gn_col); gn_v.setContentsMargins(0, 0, 0, 0); gn_v.setSpacing(4)
        gn_v.addWidget(_label("Primary Genre"))
        self._genre_combo = _make_combo(GENRES)
        gn_v.addWidget(self._genre_combo)
        row.addWidget(gn_col, stretch=1)
        # Era
        er_col = QWidget(); er_col.setStyleSheet("background: transparent;")
        er_v = QVBoxLayout(er_col); er_v.setContentsMargins(0, 0, 0, 0); er_v.setSpacing(4)
        er_v.addWidget(_label("Era"))
        self._era_combo = _make_combo(ERAS)
        er_v.addWidget(self._era_combo)
        row.addWidget(er_col, stretch=1)
        v.addLayout(row)

        # Notes
        v.addWidget(_label("Notes"))
        self._notes_box = QTextEdit()
        self._notes_box.setFixedHeight(64)
        self._notes_box.setFont(inter(11))
        self._notes_box.setPlaceholderText("Optional notes about the artist...")
        self._notes_box.setStyleSheet(
            f"QTextEdit {{ background: {INPUT_BG}; color: {TEXT_PRI}; "
            f"border: 1px solid {INPUT_BORDER}; border-radius: 6px; "
            f"padding: 6px 10px; }}"
            f"QTextEdit:focus {{ border-color: {CYAN}; }}"
        )
        v.addWidget(self._notes_box)

        # AI Auto-fill banner
        ai = QPushButton()
        ai.setFixedHeight(40)
        ai.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        ai.setStyleSheet(
            f"QPushButton {{ "
            f"  background: qlineargradient(x1:0,y1:0,x2:0,y2:1, "
            f"  stop:0 rgba(30,21,53,0.6), stop:1 rgba(30,21,53,0.3)); "
            f"  border: 1px solid {rgba(PURPLE_LIGHT, 0.30)}; "
            f"  border-left: 3px solid {PURPLE_LIGHT}; "
            f"  border-radius: 6px; text-align: left; padding: 0 13px; }}"
            f"QPushButton:hover {{ background: {rgba(PURPLE, 0.25)}; }}"
        )
        ai_lay = QHBoxLayout(ai)
        ai_lay.setContentsMargins(0, 4, 0, 4); ai_lay.setSpacing(8)
        sparkle = QLabel("✦")
        sparkle.setFont(inter(14, QFont.Weight.Bold))
        sparkle.setStyleSheet(f"color: {PURPLE_LIGHT}; background: transparent;")
        ai_lay.addWidget(sparkle)
        ai_text = QWidget(); ai_text.setStyleSheet("background: transparent;")
        ai_v = QVBoxLayout(ai_text); ai_v.setContentsMargins(0, 0, 0, 0); ai_v.setSpacing(0)
        line1 = QLabel("AI Auto-fill from artist name")
        line1.setFont(inter(12, QFont.Weight.Bold))
        line1.setStyleSheet(f"color: {PURPLE_LIGHT}; background: transparent;")
        line2 = QLabel("Auto-detect genre, country, era from web")
        line2.setFont(inter(9, QFont.Weight.Medium))
        line2.setStyleSheet(f"color: {TEXT_SEC}; background: transparent;")
        ai_v.addWidget(line1); ai_v.addWidget(line2)
        ai_lay.addWidget(ai_text)
        ai_lay.addStretch()
        ai.clicked.connect(self._on_ai_autofill)
        v.addWidget(ai)

        v.addStretch()
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

        l = QLabel("* Required fields")
        l.setFont(inter(10, QFont.Weight.Medium))
        l.setStyleSheet(f"color: {TEXT_SEC}; background: transparent;")
        h.addWidget(l)
        h.addStretch()

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

        save = QPushButton("✓  Save")
        save.setFixedSize(92, 32)
        save.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        save.setFont(inter(12, QFont.Weight.Bold))
        save.setStyleSheet(
            f"QPushButton {{ background: qlineargradient("
            f"x1:0,y1:0,x2:0,y2:1, stop:0 {PURPLE_LIGHT}, stop:0.5 {PURPLE}, stop:1 #7c3aed); "
            f"color: white; border: none; border-radius: 8px; }}"
            f"QPushButton:hover {{ background: qlineargradient("
            f"x1:0,y1:0,x2:0,y2:1, stop:0 #c4b5fd, stop:1 {PURPLE}); }}"
        )
        save.clicked.connect(self._on_save)
        h.addWidget(save)
        return f

    # ── Behavior ──────────────────────────────────────────────────────────

    def _on_ai_autofill(self):
        dialogs.info(
            self, "AI Auto-fill",
            "AI metadata auto-fill is not yet wired to Claude — coming in a future phase.\n\n"
            "When wired, this will analyze the artist name and auto-detect "
            "country, primary genre, and era from public web sources."
        )

    def _on_save(self):
        name = self._name_input.text().strip()
        if not name:
            dialogs.warning(self, "Required field", "Please enter the artist name.")
            self._name_input.setFocus()
            return

        country = self._country_combo.currentText()
        if country.startswith("Select"):
            country = None
        genre = self._genre_combo.currentText()
        if genre.startswith("Select"):
            genre = None
        era = self._era_combo.currentText()
        if era.startswith("Select"):
            era = None

        data = {
            "name": name,
            "display_name": self._display_input.text().strip() or None,
            "country": country,
            "primary_genre": genre,
            "era": era,
            "notes": self._notes_box.toPlainText().strip() or None,
        }

        try:
            artist_id = self._db.add_artist(data)
        except Exception as exc:
            # Likely UNIQUE constraint failure
            if "UNIQUE" in str(exc):
                dialogs.warning(
                    self, "Artist already exists",
                    f"An artist named '{name}' already exists in the library.",
                )
            else:
                dialogs.error(self, "Save failed", f"Could not save artist:\n\n{exc}")
            return

        log.info(f"Artist saved: id={artist_id} name='{name}'")
        self.artist_saved.emit(artist_id, name)
        self.accept()
