"""
RadioAI Studio Pro — Category Move (Claude design, approved 2026-07-02)

Full screen (1440×900) for moving songs between categories — bulk or
single. Entry points:
  1. Songs Library → right-click a song → "Change Category…" — opens
     with source = that song's category and the clicked/selected songs
     pre-checked (``set_context``).
  2. MainWindow route key "category_move" (breadcrumb navigation).

Layout:
  Header        y=0..72     logo + breadcrumb (Control Panel | Songs
                            Library | [Category Move]) + title + clock
                            + station + Open Studio
  Section strip y=72..116   "MOVE SONGS BETWEEN CATEGORIES" + subtitle
  Body          y=116..852
    LEFT  x=16..816         SOURCE: category combo (+counts, incl.
                            Uncategorized) · search · checkbox song
                            list · Select All / Clear · selected count
    RIGHT x=832..1424       DESTINATION: category cards (source hidden)
                            + summary (src → dst · N songs) + CTA
  Status bar    y=864..900  pills: categories / in source / selected

The move itself is ``db.move_songs_to_category`` — an exact
``WHERE id IN`` UPDATE (destructive-op protocol; never patterns).
Play history / reports are untouched — only future scheduling pools
(rotation AI, auto-grid, clock pickers) see the new pool depths.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from core import dialogs

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QCursor, QFont
from PyQt6.QtWidgets import (
    QComboBox, QFrame, QLabel, QLineEdit, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from core.settings import Settings
from ui.widgets._tokens import (
    inter, mono, rgba,
    BG_BASE, BG_PANEL, BG_CARD, BG_ELEVATED,
    TEXT_PRI, TEXT_SEC, TEXT_MUTED, TEXT_DIM,
    CYAN, CYAN_LIGHT, PURPLE, PURPLE_LIGHT, GREEN, GREEN_LIGHT,
)

log = logging.getLogger("CategoryMove")

WINDOW_W = 1440
WINDOW_H = 900
HEADER_H = 72
STRIP_H = 44
STATUS_H = 36
BODY_Y = HEADER_H + STRIP_H
BODY_H = WINDOW_H - BODY_Y - STATUS_H - 12
LEFT_X, LEFT_W = 16, 800
RIGHT_X = LEFT_X + LEFT_W + 16
RIGHT_W = WINDOW_W - RIGHT_X - 16
ROW_H = 44

UNCAT_LABEL = "Uncategorized"


def _fmt_duration(ms) -> str:
    s = int((ms or 0) // 1000)
    return f"{s // 60}:{s % 60:02d}"


# ════════════════════════════════════════════════════════════════════════
# Private widgets
# ════════════════════════════════════════════════════════════════════════

class _BreadcrumbLink(QPushButton):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFont(inter(11))
        self.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {TEXT_SEC}; "
            f"border: none; text-align: left; }}"
            f"QPushButton:hover {{ color: {CYAN_LIGHT}; }}"
        )


class _BreadcrumbPill(QFrame):
    def __init__(self, label: str, accent: str, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"QFrame {{ background: {rgba(accent, 0.14)}; "
            f"border: 1px solid {rgba(accent, 0.45)}; "
            f"border-radius: 12px; }}"
        )
        lbl = QLabel(label, self)
        lbl.setFont(inter(10, QFont.Weight.Medium))
        lbl.setStyleSheet(
            f"color: {accent}; background: transparent; border: none;")
        lbl.adjustSize()
        lbl.move(12, 4)
        self.setFixedSize(lbl.width() + 24, 24)


class _Combo(QComboBox):
    """Dark themed combo (same recipe as the soundcard screen)."""

    def __init__(self, accent: str = CYAN, parent=None):
        super().__init__(parent)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFont(inter(11))
        self.setStyleSheet(
            f"QComboBox {{ background: {BG_ELEVATED}; color: {TEXT_PRI}; "
            f"border: 1px solid #1c1f38; border-radius: 7px; "
            f"padding: 4px 10px; }}"
            f"QComboBox:hover {{ border: 1px solid {rgba(accent, 0.5)}; }}"
            f"QComboBox::drop-down {{ border: none; width: 22px; }}"
            f"QComboBox QAbstractItemView {{ background: {BG_ELEVATED}; "
            f"color: {TEXT_PRI}; border: 1px solid #1c1f38; "
            f"selection-background-color: {rgba(accent, 0.20)}; "
            f"selection-color: {CYAN_LIGHT}; outline: none; }}"
        )


class _SongRow(QFrame):
    """One selectable song row: checkbox + title/artist + duration.
    Whole row toggles on click."""

    toggled = pyqtSignal()

    def __init__(self, song: dict, parent=None):
        super().__init__(parent)
        self.song_id = int(song["id"])
        self._checked = False
        self._search_blob = (f"{song.get('title') or ''} "
                             f"{song.get('artist') or ''}").lower()
        self.setFixedHeight(ROW_H)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        self._box = QLabel("", self)
        self._box.setGeometry(12, (ROW_H - 16) // 2, 16, 16)

        title = QLabel(song.get("title") or "—", self)
        title.setFont(inter(11, QFont.Weight.Medium))
        title.setGeometry(40, 5, 640, 16)
        title.setStyleSheet(
            f"color: {TEXT_PRI}; background: transparent; border: none;")

        artist = QLabel(song.get("artist") or "—", self)
        artist.setFont(inter(9))
        artist.setGeometry(40, 23, 640, 14)
        artist.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent; border: none;")

        dur = QLabel(_fmt_duration(song.get("duration_ms")), self)
        dur.setFont(mono(10))
        dur.setGeometry(LEFT_W - 100, 0, 60, ROW_H)
        dur.setAlignment(Qt.AlignmentFlag.AlignRight |
                         Qt.AlignmentFlag.AlignVCenter)
        dur.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent; border: none;")

        self._apply_style()

    # ── state ────────────────────────────────────────────────────────
    def is_checked(self) -> bool:
        return self._checked

    def set_checked(self, checked: bool) -> None:
        if self._checked != bool(checked):
            self._checked = bool(checked)
            self._apply_style()

    def matches(self, needle: str) -> bool:
        return needle in self._search_blob

    def _apply_style(self) -> None:
        if self._checked:
            self.setStyleSheet(
                f"_SongRow {{ background: {rgba(CYAN, 0.06)}; "
                f"border: none; border-bottom: 1px solid "
                f"{rgba('#1c1f38', 0.6)}; }}")
            self._box.setStyleSheet(
                f"background: {CYAN}; border: 1px solid {CYAN}; "
                f"border-radius: 4px; color: #04141a; "
                f"font-size: 11px; font-weight: bold;")
            self._box.setText("✓")
            self._box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        else:
            self.setStyleSheet(
                f"_SongRow {{ background: transparent; border: none; "
                f"border-bottom: 1px solid {rgba('#1c1f38', 0.6)}; }}")
            self._box.setStyleSheet(
                f"background: transparent; border: 1px solid {TEXT_MUTED}; "
                f"border-radius: 4px;")
            self._box.setText("")

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.set_checked(not self._checked)
            self.toggled.emit()
        super().mousePressEvent(e)


class _DestCard(QFrame):
    """Destination category card — radio-select behaviour."""

    clicked = pyqtSignal(object)      # category id (int) or None

    def __init__(self, cat_id, name: str, color: str, count: int,
                 parent=None):
        super().__init__(parent)
        self.cat_id = cat_id
        self._selected = False
        self.setFixedHeight(38)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        self._dot = QLabel("", self)
        self._dot.setGeometry(12, 15, 8, 8)
        self._dot.setStyleSheet(
            f"background: {color or PURPLE}; border-radius: 4px;")

        self._name = QLabel(name, self)
        self._name.setFont(inter(11))
        self._name.setGeometry(30, 0, 360, 38)

        self._count = QLabel(str(count), self)
        self._count.setFont(inter(10))
        self._count.setGeometry(self.width() - 160, 0, 100, 38)
        self._count.setAlignment(Qt.AlignmentFlag.AlignRight |
                                 Qt.AlignmentFlag.AlignVCenter)

        self._tick = QLabel("✓", self)
        self._tick.setFont(inter(12, QFont.Weight.Bold))
        self._tick.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._tick.hide()

        self._apply_style()

    def resizeEvent(self, e):
        self._count.setGeometry(self.width() - 106, 0, 60, 38)
        self._tick.setGeometry(self.width() - 34, 0, 22, 38)
        super().resizeEvent(e)

    def set_selected(self, sel: bool) -> None:
        self._selected = bool(sel)
        self._apply_style()

    def _apply_style(self) -> None:
        if self._selected:
            self.setStyleSheet(
                f"_DestCard {{ background: {rgba(PURPLE, 0.10)}; "
                f"border: 1px solid {PURPLE}; border-radius: 7px; }}")
            self._name.setStyleSheet(
                f"color: {TEXT_PRI}; background: transparent; border: none;")
            self._count.setStyleSheet(
                f"color: {TEXT_SEC}; background: transparent; border: none;")
            self._tick.setStyleSheet(
                f"color: {PURPLE_LIGHT}; background: transparent; "
                f"border: none;")
            self._tick.show()
        else:
            self.setStyleSheet(
                f"_DestCard {{ background: {BG_CARD}; "
                f"border: 1px solid #1c1f38; border-radius: 7px; }}")
            self._name.setStyleSheet(
                f"color: {TEXT_SEC}; background: transparent; border: none;")
            self._count.setStyleSheet(
                f"color: {TEXT_MUTED}; background: transparent; "
                f"border: none;")
            self._tick.hide()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.cat_id)
        super().mousePressEvent(e)


class _StatusPill(QFrame):
    def __init__(self, color: str, parent=None):
        super().__init__(parent)
        self._color = color
        self._lbl = QLabel("", self)
        self._lbl.setFont(inter(9, QFont.Weight.Medium,
                                letter_spacing=0.8))
        self._lbl.setStyleSheet(
            f"color: {color}; background: transparent; border: none;")
        self.setStyleSheet(
            f"QFrame {{ background: transparent; "
            f"border: 1px solid {rgba(color, 0.4)}; "
            f"border-radius: 11px; }}")
        self.setFixedHeight(22)

    def set_text(self, text: str) -> None:
        self._lbl.setText(text)
        self._lbl.adjustSize()
        self._lbl.move(11, (22 - self._lbl.height()) // 2)
        self.setFixedWidth(self._lbl.width() + 22)


# ════════════════════════════════════════════════════════════════════════
# The screen
# ════════════════════════════════════════════════════════════════════════

class CategoryMove(QWidget):
    """Category Move screen — see module docstring."""

    breadcrumb_clicked = pyqtSignal(str)   # "control_panel" | "songs"
    studio_clicked     = pyqtSignal()
    songs_moved        = pyqtSignal(int)   # count — SongsLibrary refresh

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self._db = db
        self.setFixedSize(WINDOW_W, WINDOW_H)
        self.setStyleSheet(f"QWidget {{ background: {BG_BASE}; }}")

        self._rows: list[_SongRow] = []
        self._dest_cards: list[_DestCard] = []
        self._dest_selected = "__none__"     # sentinel: nothing picked
        self._source_id = "__none__"         # int | None (Uncategorized)
        self._pending_check_ids: set[int] = set()

        self._build_header()
        self._build_strip()
        self._build_left_panel()
        self._build_right_panel()
        self._build_status_bar()

        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(
            lambda: self._clock_lbl.setText(
                datetime.now().strftime("%H:%M:%S")))
        self._clock_timer.start()

        self.reload()
        log.info("CategoryMove ready (Claude design)")

    # ── Header ────────────────────────────────────────────────────────

    def _build_header(self) -> None:
        h = QFrame(self)
        h.setGeometry(0, 0, WINDOW_W, HEADER_H)
        h.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border-bottom: 1px solid {rgba('#ffffff', 0.06)}; }} "
            f"QLabel {{ border: none; }}")

        logo = QLabel("R", h)
        logo.setGeometry(14, 20, 32, 32)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setFont(inter(15, QFont.Weight.Bold))
        logo.setStyleSheet(
            f"background: {CYAN}; color: #04141a; border-radius: 9px;")

        l1 = QLabel("RadioAI", h)
        l1.setGeometry(56, 16, 120, 18)
        l1.setFont(inter(15, QFont.Weight.Bold))
        l1.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        l2 = QLabel("STUDIO PRO", h)
        l2.setGeometry(56, 36, 120, 12)
        l2.setFont(inter(8, QFont.Weight.Bold, letter_spacing=1.2))
        l2.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

        cp = _BreadcrumbLink("Control Panel", h)
        cp.setGeometry(176, 25, 100, 22)
        cp.clicked.connect(
            lambda: self.breadcrumb_clicked.emit("control_panel"))
        sep1 = QLabel("|", h)
        sep1.setGeometry(274, 25, 8, 22)
        sep1.setFont(inter(11))
        sep1.setStyleSheet(f"color: {TEXT_DIM}; background: transparent;")
        sl = _BreadcrumbLink("Songs Library", h)
        sl.setGeometry(286, 25, 95, 22)
        sl.clicked.connect(lambda: self.breadcrumb_clicked.emit("songs"))
        sep2 = QLabel("|", h)
        sep2.setGeometry(382, 25, 8, 22)
        sep2.setFont(inter(11))
        sep2.setStyleSheet(f"color: {TEXT_DIM}; background: transparent;")
        _BreadcrumbPill("Category Move", PURPLE_LIGHT, h).move(394, 24)

        title = QLabel("Category Move", h)
        title.setGeometry(540, 14, 260, 24)
        title.setFont(inter(20, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        sub = QLabel("Move songs between categories — bulk or single", h)
        sub.setGeometry(540, 40, 420, 14)
        sub.setFont(inter(10))
        sub.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

        self._clock_lbl = QLabel(datetime.now().strftime("%H:%M:%S"), h)
        self._clock_lbl.setGeometry(1108, 14, 100, 24)
        self._clock_lbl.setFont(mono(20, bold=True))
        self._clock_lbl.setStyleSheet(
            f"color: {TEXT_PRI}; background: transparent;")
        try:
            station = Settings().station_display or "KISS FM 91.5"
        except Exception:
            station = "KISS FM 91.5"
        self._station_lbl = QLabel(station, h)
        self._station_lbl.setObjectName("hdr_station_lbl")
        self._station_lbl.setGeometry(1108, 40, 110, 14)
        self._station_lbl.setFont(inter(9, QFont.Weight.Medium))
        self._station_lbl.setStyleSheet(
            f"color: {GREEN}; background: transparent;")

        osb = QPushButton("▶  Open Studio", h)
        osb.setGeometry(1252, 20, 140, 32)
        osb.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        osb.setFont(inter(10, QFont.Weight.Bold))
        osb.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {GREEN_LIGHT}; "
            f"border: 1px solid {rgba(GREEN, 0.4)}; border-radius: 7px; }}"
            f"QPushButton:hover {{ border: 1px solid {rgba(GREEN, 0.8)}; }}")
        osb.clicked.connect(self.studio_clicked.emit)

    # ── Section strip ─────────────────────────────────────────────────

    def _build_strip(self) -> None:
        t = QLabel("MOVE SONGS BETWEEN CATEGORIES", self)
        t.setGeometry(16, HEADER_H + 8, 600, 16)
        t.setFont(inter(11, QFont.Weight.Bold, letter_spacing=1.6))
        t.setStyleSheet(
            f"color: {PURPLE_LIGHT}; background: transparent;")
        s = QLabel(
            "Select songs from the source category, pick a destination, "
            "then click Change Category. Play history & reports are not "
            "affected.", self)
        s.setGeometry(16, HEADER_H + 26, 900, 14)
        s.setFont(inter(10))
        s.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

    # ── LEFT panel — source ───────────────────────────────────────────

    def _build_left_panel(self) -> None:
        p = QFrame(self)
        p.setGeometry(LEFT_X, BODY_Y, LEFT_W, BODY_H)
        p.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border: 1px solid #1c1f38; border-radius: 10px; }}")
        self._left_panel = p

        lbl = QLabel("SOURCE CATEGORY", p)
        lbl.setGeometry(14, 12, 200, 12)
        lbl.setFont(inter(8, QFont.Weight.Bold, letter_spacing=1.4))
        lbl.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; border: none;")

        self._cmb_source = _Combo(accent=GREEN, parent=p)
        self._cmb_source.setGeometry(14, 28, 300, 30)
        self._cmb_source.currentIndexChanged.connect(
            self._on_source_changed)

        self._src_count_lbl = QLabel("", p)
        self._src_count_lbl.setGeometry(324, 28, 120, 30)
        self._src_count_lbl.setFont(inter(10))
        self._src_count_lbl.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent; border: none;")

        self._search = QLineEdit(p)
        self._search.setGeometry(LEFT_W - 254, 28, 240, 30)
        self._search.setPlaceholderText("Search title / artist…")
        self._search.setFont(inter(10))
        self._search.setClearButtonEnabled(True)
        self._search.setStyleSheet(
            f"QLineEdit {{ background: {BG_CARD}; color: {TEXT_PRI}; "
            f"border: 1px solid #1c1f38; border-radius: 7px; "
            f"padding-left: 9px; }}"
            f"QLineEdit:focus {{ border: 1px solid {rgba(CYAN, 0.5)}; }}")
        self._search.textChanged.connect(self._apply_search)

        head = QFrame(p)
        head.setGeometry(14, 68, LEFT_W - 28, 24)
        head.setStyleSheet(
            f"QFrame {{ background: {BG_CARD}; border: 1px solid #1c1f38; "
            f"border-top-left-radius: 8px; border-top-right-radius: 8px; "
            f"border-bottom: none; }}")
        for text, x, w in (("TITLE / ARTIST", 40, 300),
                           ("TIME", LEFT_W - 128, 60)):
            c = QLabel(text, head)
            c.setGeometry(x, 4, w, 14)
            c.setFont(inter(8, QFont.Weight.Bold, letter_spacing=1.2))
            c.setStyleSheet(
                f"color: {TEXT_MUTED}; background: transparent; "
                f"border: none;")

        self._scroll = QScrollArea(p)
        self._scroll.setGeometry(14, 92, LEFT_W - 28, BODY_H - 92 - 52)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(
            f"QScrollArea {{ background: {BG_CARD}; "
            f"border: 1px solid #1c1f38; "
            f"border-bottom-left-radius: 8px; "
            f"border-bottom-right-radius: 8px; }}"
            f"QScrollBar:vertical {{ background: transparent; width: 8px; }}"
            f"QScrollBar::handle:vertical {{ background: #1c1f38; "
            f"border-radius: 4px; min-height: 30px; }}"
            f"QScrollBar::add-line, QScrollBar::sub-line "
            f"{{ height: 0; }}")
        self._list_host = QWidget()
        self._list_host.setStyleSheet("background: transparent;")
        self._list_lay = QVBoxLayout(self._list_host)
        self._list_lay.setContentsMargins(0, 0, 0, 0)
        self._list_lay.setSpacing(0)
        self._list_lay.addStretch(1)
        self._scroll.setWidget(self._list_host)

        y = BODY_H - 44
        self._btn_all = QPushButton("Select All", p)
        self._btn_all.setGeometry(14, y, 96, 30)
        self._btn_all.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._btn_all.setFont(inter(10, QFont.Weight.Medium))
        self._btn_all.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {CYAN_LIGHT}; "
            f"border: 1px solid {rgba(CYAN, 0.4)}; border-radius: 7px; }}"
            f"QPushButton:hover {{ border: 1px solid {rgba(CYAN, 0.8)}; }}")
        self._btn_all.clicked.connect(self._on_select_all)

        self._btn_clear = QPushButton("Clear", p)
        self._btn_clear.setGeometry(118, y, 76, 30)
        self._btn_clear.setCursor(
            QCursor(Qt.CursorShape.PointingHandCursor))
        self._btn_clear.setFont(inter(10, QFont.Weight.Medium))
        self._btn_clear.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {TEXT_SEC}; "
            f"border: 1px solid #1c1f38; border-radius: 7px; }}"
            f"QPushButton:hover {{ color: {TEXT_PRI}; }}")
        self._btn_clear.clicked.connect(self._on_clear)

        self._sel_lbl = QLabel("0 of 0 selected", p)
        self._sel_lbl.setGeometry(LEFT_W - 254, y, 240, 30)
        self._sel_lbl.setAlignment(Qt.AlignmentFlag.AlignRight |
                                   Qt.AlignmentFlag.AlignVCenter)
        self._sel_lbl.setFont(inter(11, QFont.Weight.Bold))
        self._sel_lbl.setStyleSheet(
            f"color: {CYAN_LIGHT}; background: transparent; border: none;")

    # ── RIGHT panel — destination + summary ───────────────────────────

    def _build_right_panel(self) -> None:
        dest_h = BODY_H - 168
        p = QFrame(self)
        p.setGeometry(RIGHT_X, BODY_Y, RIGHT_W, dest_h)
        p.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border: 1px solid #1c1f38; border-radius: 10px; }}")

        lbl = QLabel("DESTINATION CATEGORY", p)
        lbl.setGeometry(14, 12, 240, 12)
        lbl.setFont(inter(8, QFont.Weight.Bold, letter_spacing=1.4))
        lbl.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; border: none;")

        self._dest_scroll = QScrollArea(p)
        self._dest_scroll.setGeometry(14, 32, RIGHT_W - 28, dest_h - 46)
        self._dest_scroll.setWidgetResizable(True)
        self._dest_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._dest_scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            f"QScrollBar:vertical {{ background: transparent; width: 8px; }}"
            f"QScrollBar::handle:vertical {{ background: #1c1f38; "
            f"border-radius: 4px; min-height: 30px; }}"
            f"QScrollBar::add-line, QScrollBar::sub-line "
            f"{{ height: 0; }}")
        self._dest_host = QWidget()
        self._dest_host.setStyleSheet("background: transparent;")
        self._dest_lay = QVBoxLayout(self._dest_host)
        self._dest_lay.setContentsMargins(0, 0, 4, 0)
        self._dest_lay.setSpacing(6)
        self._dest_lay.addStretch(1)
        self._dest_scroll.setWidget(self._dest_host)

        card = QFrame(self)
        card.setGeometry(RIGHT_X, BODY_Y + dest_h + 12, RIGHT_W, 156)
        card.setStyleSheet(
            f"QFrame {{ background: {BG_CARD}; "
            f"border: 1px solid #1c1f38; border-radius: 10px; }}")

        self._summary_lbl = QLabel("Pick songs and a destination", card)
        self._summary_lbl.setGeometry(14, 12, RIGHT_W - 28, 20)
        self._summary_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._summary_lbl.setFont(inter(12, QFont.Weight.Bold))
        self._summary_lbl.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent; border: none;")

        self._summary_sub = QLabel("", card)
        self._summary_sub.setGeometry(14, 34, RIGHT_W - 28, 16)
        self._summary_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._summary_sub.setFont(inter(10))
        self._summary_sub.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent; border: none;")

        self._btn_move = QPushButton("⇄  Change Category", card)
        self._btn_move.setGeometry(14, 58, RIGHT_W - 28, 42)
        self._btn_move.setCursor(
            QCursor(Qt.CursorShape.PointingHandCursor))
        self._btn_move.setFont(inter(12, QFont.Weight.Bold))
        self._btn_move.clicked.connect(self._on_move_clicked)

        note = QLabel(
            "ⓘ  Play history & reports are not affected — only future "
            "scheduling pools change.", card)
        note.setGeometry(14, 110, RIGHT_W - 28, 30)
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        note.setWordWrap(True)
        note.setFont(inter(9))
        note.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; border: none;")

        self._refresh_cta()

    # ── Status bar ────────────────────────────────────────────────────

    def _build_status_bar(self) -> None:
        sb = QFrame(self)
        sb.setGeometry(0, WINDOW_H - STATUS_H, WINDOW_W, STATUS_H)
        sb.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border-top: 1px solid {rgba('#ffffff', 0.06)}; }} "
            f"QLabel {{ border: none; }}")

        self._pill_cats = _StatusPill(PURPLE_LIGHT, sb)
        self._pill_src = _StatusPill(CYAN_LIGHT, sb)
        self._pill_sel = _StatusPill(GREEN_LIGHT, sb)
        for i, pill in enumerate(
                (self._pill_cats, self._pill_src, self._pill_sel)):
            pill.move(12 + i * 150, (STATUS_H - 22) // 2)

        ver = QLabel("Category Move  ·  RadioAI Studio v1.0.0", sb)
        ver.setFont(inter(9))
        ver.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; border: none;")
        ver.setAlignment(Qt.AlignmentFlag.AlignRight |
                         Qt.AlignmentFlag.AlignVCenter)
        ver.setFixedSize(320, STATUS_H)
        ver.move(WINDOW_W - 16 - 320, 0)

    # ── Data loading ──────────────────────────────────────────────────

    def _category_rows(self) -> list[dict]:
        """[{id, name, color, count}] + Uncategorized appended."""
        out = []
        try:
            for c in self._db.get_categories():
                d = {k: c[k] for k in c.keys()}
                out.append({
                    "id": int(d["id"]),
                    "name": (d.get("name") or "").strip() or "—",
                    "color": d.get("color") or PURPLE,
                    "count": self._count_for(int(d["id"])),
                })
        except Exception as exc:
            log.error(f"[catmove] category load failed: {exc}")
        out.append({"id": None, "name": UNCAT_LABEL,
                    "color": TEXT_MUTED,
                    "count": self._count_for(None)})
        return out

    def _count_for(self, cat_id) -> int:
        try:
            if cat_id is None:
                row = self._db.execute(
                    "SELECT COUNT(*) AS n FROM songs "
                    "WHERE category_id IS NULL")
            else:
                row = self._db.execute(
                    "SELECT COUNT(*) AS n FROM songs "
                    "WHERE category_id = ?", (int(cat_id),))
            return int(row[0]["n"]) if row else 0
        except Exception:
            return 0

    def reload(self) -> None:
        """Refetch categories + song list. Keeps the current source
        selection when it still exists."""
        cats = self._category_rows()
        keep = self._source_id

        self._cmb_source.blockSignals(True)
        self._cmb_source.clear()
        restored_idx = 0
        for i, c in enumerate(cats):
            self._cmb_source.addItem(
                f"{c['name']}   ({c['count']})", c["id"])
            if keep != "__none__" and c["id"] == keep:
                restored_idx = i
        self._cmb_source.setCurrentIndex(restored_idx)
        self._cmb_source.blockSignals(False)

        self._cats_cache = cats
        self._source_id = cats[restored_idx]["id"] if cats else None
        self._load_source_songs()
        self._rebuild_dest_cards()
        self._refresh_status()

    def _load_source_songs(self) -> None:
        for r in self._rows:
            r.setParent(None)
            r.deleteLater()
        self._rows = []
        try:
            songs = self._db.get_songs_for_category_move(self._source_id)
        except Exception as exc:
            log.error(f"[catmove] songs load failed: {exc}")
            songs = []
        for s in songs:
            row = _SongRow(s)
            row.toggled.connect(self._on_row_toggled)
            if s["id"] in self._pending_check_ids:
                row.set_checked(True)
            self._list_lay.insertWidget(self._list_lay.count() - 1, row)
            self._rows.append(row)
        self._pending_check_ids = set()
        self._apply_search(self._search.text())
        self._refresh_selection_ui()

    def _rebuild_dest_cards(self) -> None:
        for c in self._dest_cards:
            c.setParent(None)
            c.deleteLater()
        self._dest_cards = []
        if (self._dest_selected != "__none__"
                and self._dest_selected == self._source_id):
            self._dest_selected = "__none__"
        for cat in self._cats_cache:
            if cat["id"] == self._source_id:
                continue
            card = _DestCard(cat["id"], cat["name"], cat["color"],
                             cat["count"])
            card.clicked.connect(self._on_dest_clicked)
            if (self._dest_selected != "__none__"
                    and cat["id"] == self._dest_selected):
                card.set_selected(True)
            self._dest_lay.insertWidget(self._dest_lay.count() - 1, card)
            self._dest_cards.append(card)
        self._refresh_summary()
        self._refresh_cta()

    # ── Selection / search ────────────────────────────────────────────

    def selected_ids(self) -> list[int]:
        return [r.song_id for r in self._rows if r.is_checked()]

    def _visible_rows(self) -> list[_SongRow]:
        return [r for r in self._rows if not r.isHidden()]

    def _apply_search(self, text: str) -> None:
        needle = (text or "").strip().lower()
        for r in self._rows:
            r.setVisible(not needle or r.matches(needle))

    def _on_row_toggled(self) -> None:
        self._refresh_selection_ui()

    def _on_select_all(self) -> None:
        for r in self._visible_rows():
            r.set_checked(True)
        self._refresh_selection_ui()

    def _on_clear(self) -> None:
        for r in self._rows:
            r.set_checked(False)
        self._refresh_selection_ui()

    def _refresh_selection_ui(self) -> None:
        n, total = len(self.selected_ids()), len(self._rows)
        self._sel_lbl.setText(f"{n} of {total} selected")
        self._src_count_lbl.setText(f"{total} songs")
        self._refresh_summary()
        self._refresh_cta()
        self._refresh_status()

    # ── Source / destination handlers ─────────────────────────────────

    def _on_source_changed(self, idx: int) -> None:
        if idx < 0 or idx >= len(self._cats_cache):
            return
        self._source_id = self._cats_cache[idx]["id"]
        self._load_source_songs()
        self._rebuild_dest_cards()
        self._refresh_status()

    def _on_dest_clicked(self, cat_id) -> None:
        self._dest_selected = cat_id
        for c in self._dest_cards:
            c.set_selected(c.cat_id == cat_id)
        self._refresh_summary()
        self._refresh_cta()

    # ── Summary / CTA ─────────────────────────────────────────────────

    def _src_name(self) -> str:
        for c in getattr(self, "_cats_cache", []):
            if c["id"] == self._source_id:
                return c["name"]
        return "—"

    def _dest_name(self) -> str:
        for c in getattr(self, "_cats_cache", []):
            if (self._dest_selected != "__none__"
                    and c["id"] == self._dest_selected):
                return c["name"]
        return "—"

    def _refresh_summary(self) -> None:
        n = len(self.selected_ids())
        if n and self._dest_selected != "__none__":
            self._summary_lbl.setText(
                f"{self._src_name()}  →  {self._dest_name()}")
            self._summary_sub.setText(
                f"{n} song{'s' if n != 1 else ''} will move")
        elif n:
            self._summary_lbl.setText("Pick a destination category")
            self._summary_sub.setText(f"{n} selected in "
                                      f"{self._src_name()}")
        else:
            self._summary_lbl.setText("Pick songs and a destination")
            self._summary_sub.setText("")

    def _refresh_cta(self) -> None:
        ready = bool(self.selected_ids()) and \
            self._dest_selected != "__none__"
        self._btn_move.setEnabled(ready)
        if ready:
            self._btn_move.setStyleSheet(
                f"QPushButton {{ background: qlineargradient("
                f"x1:0,y1:0,x2:0,y2:1, stop:0 {CYAN_LIGHT}, "
                f"stop:1 {CYAN}); color: #04141a; border: none; "
                f"border-radius: 8px; }}"
                f"QPushButton:hover {{ background: qlineargradient("
                f"x1:0,y1:0,x2:0,y2:1, stop:0 #67e8f9, "
                f"stop:1 {CYAN_LIGHT}); }}")
        else:
            self._btn_move.setStyleSheet(
                f"QPushButton {{ background: {BG_ELEVATED}; "
                f"color: {TEXT_MUTED}; border: 1px solid #1c1f38; "
                f"border-radius: 8px; }}")

    def _refresh_status(self) -> None:
        cats = len(getattr(self, "_cats_cache", [])) - 1   # minus Uncat
        self._pill_cats.set_text(f"{cats} CATEGORIES")
        self._pill_src.set_text(f"{len(self._rows)} IN SOURCE")
        self._pill_sel.set_text(f"{len(self.selected_ids())} SELECTED")

    # ── The move ──────────────────────────────────────────────────────

    def _on_move_clicked(self) -> None:
        ids = self.selected_ids()
        if not ids or self._dest_selected == "__none__":
            return
        src, dst = self._src_name(), self._dest_name()
        if not dialogs.confirm(
                self, "Change Category",
                f"Move {len(ids)} song{'s' if len(ids) != 1 else ''} "
                f"from '{src}' to '{dst}'?\n\n"
                f"Play history and reports are not affected.",
                yes_label="Change Category"):
            return
        try:
            dest_id = (None if self._dest_selected is None
                       else int(self._dest_selected))
            moved = self._db.move_songs_to_category(ids, dest_id)
        except Exception as exc:
            log.error(f"[catmove] move failed: {exc}", exc_info=True)
            dialogs.error(self, "Move failed",
                          f"Could not move songs:\n{exc}")
            return
        log.info(f"[catmove] moved {moved} songs '{src}' → '{dst}' "
                 f"(ids={ids[:20]}{'…' if len(ids) > 20 else ''})")
        self.songs_moved.emit(moved)
        dialogs.info(self, "Category changed",
                     f"{moved} song{'s' if moved != 1 else ''} moved "
                     f"from '{src}' to '{dst}'.")
        self.reload()

    # ── Public API (right-click entry) ────────────────────────────────

    def set_context(self, song_ids: Optional[list] = None,
                    source_category_id="__keep__") -> None:
        """Open-from-right-click: pre-select the source category and
        pre-check the given songs. ``source_category_id=None`` means
        Uncategorized; "__keep__" leaves the source as-is."""
        if source_category_id != "__keep__":
            self._source_id = source_category_id
        self._dest_selected = "__none__"
        self._pending_check_ids = set(int(i) for i in (song_ids or []))
        self._search.clear()
        self.reload()

    def reload_on_show(self) -> None:
        """MainWindow calls on navigate — refresh counts cheaply."""
        self.reload()
