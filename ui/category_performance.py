"""
RadioAI Studio Pro — Category Performance

Pixel-accurate match of Figma node 448:3 (file 7oN9K61g94wKx3nu44KKDF,
page "Category Performance"). The category-scoped sibling to per-song
Play History (Figma 437:3): the operator filters Songs Library by a
category, clicks the "Category Performance" report tile, and lands
here with that category loaded.

Reads three DB helpers (see core/database.py):
  - get_category_performance_summary(category_id) → totals + counters
  - get_category_monthly_plays(category_id, 12)    → 12-month bar data
  - get_category_songs_ranked(category_id)         → every song in cat

Layout (1440 × 900):
  Header        y=  0.. 72   Logo + breadcrumb + title + clock + Open Studio
  Hero card     y= 88..236   Category tile + name/summary + pill +
                              right-side TOTAL PLAYS readout
  Stats row     y=256..344   4 cards (this month / this week /
                              avg per song / most played)
  Monthly chart y=360..616   12 aggregate-plays bars + gridlines + peak
  Songs table   y=632..852   Every song in the category, ranked
  Status bar    y=864..900   Pills + version + Open Studio

Chrome widgets (_HeaderLogo / _BreadcrumbLink / _BreadcrumbPill /
_StatCard / _MonthlyChart / _StatusPill / _HeaderOpenStudio) are
imported from ui.play_history. The codebase has been duplicating these
across screens; importing keeps Category Performance + Play History
visually pinned to the same chrome. When `ui/widgets/library_chrome.py`
extraction lands, both files swap the same import.

Public signals:
  breadcrumb_clicked(str) — header crumbs
  studio_clicked()        — Open Studio
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from PyQt6.QtCore import Qt, QRectF, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QLinearGradient, QFont, QCursor,
)
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QHBoxLayout,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
)

from core.settings import Settings
from ui.widgets._tokens import (
    inter, mono, rgba,
    BG_BASE, BG_PANEL,
    TEXT_PRI, TEXT_SEC, TEXT_MUTED, TEXT_DIM,
    CYAN, CYAN_LIGHT, PURPLE, PURPLE_LIGHT,
    GREEN, GREEN_LIGHT, AMBER, AMBER_LIGHT,
    PINK, RED,
)
from ui.play_history import (
    _HeaderLogo, _HeaderOpenStudio,
    _BreadcrumbLink, _BreadcrumbPill,
    _StatCard, _MonthlyChart, _StatusPill,
    _human_ago,
)

log = logging.getLogger("CategoryPerformance")


WINDOW_W = 1440
WINDOW_H = 900
HEADER_H = 72
STATUS_H = 36


def _category_color(name: str) -> str:
    """Same palette mapping the Songs Library / Play History use, so
    Bollywood shows up cyan in both Play History and here."""
    if not name:
        return CYAN
    nm = name.lower()
    if "bolly" in nm or "hindi" in nm:
        return CYAN
    if "pop" in nm or "english" in nm or "international" in nm:
        return PURPLE
    if "rock" in nm or "alt" in nm:
        return RED
    if "rom" in nm or "love" in nm:
        return PINK
    if "classic" in nm or "retro" in nm or "vintage" in nm:
        return AMBER
    if "punjab" in nm or "regional" in nm:
        return GREEN
    if "bhajan" in nm or "devot" in nm:
        return AMBER
    return CYAN


# ════════════════════════════════════════════════════════════════════════════
# Category hero card — gradient tile + name + summary + TOTAL PLAYS readout
# ════════════════════════════════════════════════════════════════════════════


class _CategoryTile(QFrame):
    """108×108 gradient tile with a ♬ glyph. Same shape as the Play
    History album-art; gradient picks up the category's accent color
    so each category gets a slightly different visual signature."""

    def __init__(self, accent: str = PURPLE, parent=None):
        super().__init__(parent)
        self._accent = accent
        self.setFixedSize(108, 108)

    def set_accent(self, accent: str) -> None:
        self._accent = accent or PURPLE
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        g = QLinearGradient(0, 0, self.width(), self.height())
        g.setColorAt(0.0, QColor(PURPLE))
        g.setColorAt(1.0, QColor(self._accent if self._accent else CYAN))
        p.setBrush(QBrush(g)); p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), 10, 10)
        p.setPen(QColor(255, 255, 255, 235))
        p.setFont(inter(56, QFont.Weight.Bold))
        p.drawText(QRectF(0, 0, self.width(), self.height()),
                   Qt.AlignmentFlag.AlignCenter, "♬")


class _CategoryPill(QFrame):
    """Small uppercase pill carrying the category name in tinted accent.
    Auto-sizes width to label content within a 100..240px clamp so
    short ("POP") and long ("BHAJAN / DEVOTIONAL") names both fit."""

    def __init__(self, label: str, accent: str = CYAN, parent=None):
        super().__init__(parent)
        self._accent = accent
        self.setFixedHeight(26)
        self.setMinimumWidth(100)
        self.setMaximumWidth(240)
        self.setStyleSheet(
            f"QFrame {{ background: {rgba(accent, 0.18)}; "
            f"border: 1px solid {rgba(accent, 0.40)}; "
            f"border-radius: 13px; }}"
        )
        h = QHBoxLayout(self)
        h.setContentsMargins(12, 0, 12, 0); h.setSpacing(0)
        lbl = QLabel((label or "—").upper(), self)
        lbl.setFont(inter(9, QFont.Weight.Bold, letter_spacing=1.2))
        lbl.setStyleSheet(
            f"color: {accent}; background: transparent; border: none;")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h.addWidget(lbl)
        self.adjustSize()


class _HeroCard(QFrame):
    """Category info card — left accent stripe, gradient tile, name +
    summary + pill on the left; right-side TOTAL PLAYS panel mirroring
    Play History's layout."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(1408, 148)
        self.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; "
            f"border-radius: 12px; }}"
        )
        self._tile = _CategoryTile(PURPLE, self)
        self._tile.move(24, 20)

        self._name_lbl = QLabel("—", self)
        self._name_lbl.setGeometry(152, 18, 720, 36)
        self._name_lbl.setFont(inter(28, QFont.Weight.Black))
        self._name_lbl.setStyleSheet(
            f"color: {TEXT_PRI}; background: transparent; border: none;")

        self._summary_lbl = QLabel("", self)
        self._summary_lbl.setGeometry(152, 56, 720, 18)
        self._summary_lbl.setFont(inter(12, QFont.Weight.Medium))
        self._summary_lbl.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent; border: none;")

        self._cat_pill: Optional[_CategoryPill] = None

        self._meta_lbl = QLabel("", self)
        self._meta_lbl.setGeometry(264, 90, 600, 26)
        self._meta_lbl.setFont(inter(11, QFont.Weight.Medium))
        self._meta_lbl.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; border: none;")

        # Right column — TOTAL PLAYS
        self._right_cap = QLabel("TOTAL PLAYS", self)
        self._right_cap.setFont(
            inter(9, QFont.Weight.Bold, letter_spacing=1.6))
        self._right_cap.setStyleSheet(
            f"color: {PURPLE_LIGHT}; background: transparent; "
            f"border: none;")
        self._right_cap.setGeometry(1408 - 320, 22, 320, 14)
        self._right_cap.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._right_total = QLabel("0", self)
        self._right_total.setFont(mono(48, bold=True))
        self._right_total.setStyleSheet(
            f"color: {TEXT_PRI}; background: transparent; border: none;")
        self._right_total.setGeometry(1408 - 320, 42, 320, 60)
        self._right_total.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._right_sub = QLabel("", self)
        self._right_sub.setFont(inter(10))
        self._right_sub.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; border: none;")
        self._right_sub.setGeometry(1408 - 320, 108, 320, 14)
        self._right_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Left accent stripe (purple — same as Play History)
        p.fillRect(QRectF(0, 0, 4, self.height()), QColor(PURPLE))
        # Right-side tinted panel
        p.fillRect(QRectF(self.width() - 320, 0, 320, self.height()),
                   QColor(rgba("#0c0e1c", 0.55)))
        p.end()

    def load_category(self, summary: dict) -> None:
        name = (summary.get("category_name") or "—").strip() or "—"
        song_count = int(summary.get("song_count") or 0)
        total = int(summary.get("total_plays") or 0)
        accent = _category_color(name)

        self._tile.set_accent(accent)
        self._name_lbl.setText(name)
        self._summary_lbl.setText(
            f"{song_count} songs  ·  {total:,} total plays"
        )

        if self._cat_pill is not None:
            self._cat_pill.deleteLater()
            self._cat_pill = None
        self._cat_pill = _CategoryPill(name, accent, self)
        self._cat_pill.move(152, 90)
        self._cat_pill.show()

        # Meta line — most-played highlight, otherwise show recency hint
        mp = summary.get("most_played")
        if mp:
            self._meta_lbl.setText(
                f"Top: {mp.get('title')} — {mp.get('artist')}  ·  "
                f"{mp.get('count')} plays"
            )
        else:
            self._meta_lbl.setText(
                "No songs in this category have aired yet.")

        self._right_total.setText(f"{total:,}")
        self._right_sub.setText(f"{song_count} songs")


# ════════════════════════════════════════════════════════════════════════════
# Songs-ranked table (replaces Play History's Recent Plays section)
# ════════════════════════════════════════════════════════════════════════════


class _SongsRankedTable(QFrame):
    """Heading + 8-col table of every song in the category, ordered
    by TOTAL PLAYS desc. Zero-play rows render with dimmed colors so
    dead inventory is visible at a glance."""

    COLUMNS = ["#", "TITLE", "ARTIST", "TOTAL PLAYS", "WEEK",
                "MONTH", "LAST PLAYED", "ENERGY  ·  VOCAL"]
    COL_WIDTHS = [40, 320, 220, 110, 80, 80, 180, 240]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(1408, 220)
        self.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; "
            f"border-radius: 12px; }}"
        )

        self._title_lbl = QLabel(
            "SONGS IN CATEGORY — RANKED BY TOTAL PLAYS", self)
        self._title_lbl.setFont(
            inter(10, QFont.Weight.Bold, letter_spacing=1.4))
        self._title_lbl.setStyleSheet(
            f"color: {PURPLE_LIGHT}; background: transparent; "
            f"border: none;")
        self._title_lbl.setGeometry(24, 14, 600, 16)

        self._subtitle_lbl = QLabel("", self)
        self._subtitle_lbl.setFont(inter(10))
        self._subtitle_lbl.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; "
            f"border: none;")
        self._subtitle_lbl.setGeometry(24, 34, 900, 14)

        self._table = QTableWidget(0, len(self.COLUMNS), self)
        self._table.setGeometry(16, 56, 1376, 156)
        self._table.setHorizontalHeaderLabels(self.COLUMNS)
        self._table.setShowGrid(False)
        self._table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Fixed)
        for i, w in enumerate(self.COL_WIDTHS):
            self._table.setColumnWidth(i, w)
        # Stretch ARTIST (col 2) to soak up slack on wide displays
        self._table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch)
        self._table.verticalHeader().setDefaultSectionSize(22)
        self._table.setStyleSheet(
            f"QTableWidget {{ background: transparent; "
            f"color: {TEXT_PRI}; gridline-color: transparent; "
            f"border: none; }}"
            f"QHeaderView::section {{ background: transparent; "
            f"color: {TEXT_MUTED}; border: none; "
            f"border-bottom: 1px solid {rgba('#ffffff', 0.06)}; "
            f"padding: 4px 6px; font-weight: bold; "
            f"font-size: 9px; letter-spacing: 1.2px; "
            f"text-align: left; }}"
            f"QTableWidget::item {{ padding: 3px 6px; border: none; }}"
            f"QScrollBar:vertical {{ background: transparent; width: 8px; "
            f"margin: 0; }}"
            f"QScrollBar::handle:vertical {{ background: "
            f"{rgba('#252840', 0.8)}; border-radius: 4px; min-height: 32px; }}"
            f"QScrollBar::handle:vertical:hover {{ background: {TEXT_SEC}; }}"
            f"QScrollBar::add-line:vertical, "
            f"QScrollBar::sub-line:vertical {{ height: 0; }}"
        )

    def load_rows(self, rows: list, category_name: str = "") -> None:
        n = len(rows)
        active = sum(1 for r in rows if int(r.get("total_plays") or 0) > 0)
        dead = n - active
        if category_name:
            sub = (f"All {n} songs in {category_name.upper()}.  "
                   f"{active} aired  ·  {dead} dead inventory.  "
                   f"Click any row to open per-song Play History.")
        else:
            sub = (f"All {n} songs in this category.  "
                   f"{active} aired  ·  {dead} dead inventory.")
        self._subtitle_lbl.setText(sub)

        self._table.setRowCount(n)
        for i, r in enumerate(rows):
            total = int(r.get("total_plays") or 0)
            dim = total == 0
            num_col = TEXT_DIM if dim else TEXT_MUTED
            txt_col = TEXT_MUTED if dim else TEXT_PRI
            sub_col = TEXT_MUTED if dim else TEXT_SEC

            self._table.setItem(i, 0, self._txt(str(i + 1),
                                                  num_col,
                                                  inter(11, QFont.Weight.Medium)))
            self._table.setItem(i, 1, self._txt(
                r.get("title") or "—",
                txt_col, inter(11, QFont.Weight.Medium)))
            self._table.setItem(i, 2, self._txt(
                r.get("artist") or "—",
                sub_col, inter(11, QFont.Weight.Medium)))
            self._table.setItem(i, 3, self._txt(
                str(total), txt_col, mono(11, bold=True)))
            self._table.setItem(i, 4, self._txt(
                str(int(r.get("plays_week") or 0)),
                txt_col, mono(11, bold=True)))
            self._table.setItem(i, 5, self._txt(
                str(int(r.get("plays_month") or 0)),
                txt_col, mono(11, bold=True)))
            self._table.setItem(i, 6, self._txt(
                _human_ago(r.get("last_played_at")) if r.get("last_played_at")
                else "—",
                sub_col, inter(11, QFont.Weight.Medium)))
            ev_bits = []
            if r.get("energy"):
                ev_bits.append(str(r["energy"]))
            if r.get("vocal"):
                ev_bits.append(str(r["vocal"]))
            self._table.setItem(i, 7, self._txt(
                "  ·  ".join(ev_bits) or "—",
                sub_col, inter(11, QFont.Weight.Medium)))

    @staticmethod
    def _txt(text: str, fg: str, font: QFont) -> QTableWidgetItem:
        it = QTableWidgetItem(text)
        it.setForeground(QColor(fg))
        it.setFont(font)
        return it


# ════════════════════════════════════════════════════════════════════════════
# Public screen
# ════════════════════════════════════════════════════════════════════════════


class CategoryPerformance(QWidget):
    """Per-category report card (Figma 448:3). Reached from Songs
    Library's "Category Performance" report tile with the active
    category filter as context."""

    breadcrumb_clicked = pyqtSignal(str)
    studio_clicked     = pyqtSignal()

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self._db = db
        self._category_id: Optional[int] = None
        self.setFixedSize(WINDOW_W, WINDOW_H)
        self.setStyleSheet(f"QWidget {{ background: {BG_BASE}; }}")

        self._build_header()
        self._build_body()
        self._build_status_bar()

        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._tick_clock)
        self._clock_timer.start()
        self._tick_clock()

        log.info("CategoryPerformance ready (Figma 448:3)")

    # ── Header ────────────────────────────────────────────────────────

    def _build_header(self) -> None:
        h = QFrame(self)
        h.setGeometry(0, 0, WINDOW_W, HEADER_H)
        h.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border-bottom: 1px solid {rgba('#ffffff', 0.06)}; }}"
        )

        _HeaderLogo(h).move(14, 16)
        l = QLabel("RadioAI", h)
        l.setGeometry(64, 14, 120, 18)
        l.setFont(inter(15, QFont.Weight.Bold))
        l.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        sub = QLabel("STUDIO PRO", h)
        sub.setGeometry(64, 34, 120, 12)
        sub.setFont(inter(8, QFont.Weight.Bold, letter_spacing=1.2))
        sub.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

        cp = _BreadcrumbLink("Control Panel", h)
        cp.setGeometry(176, 22, 100, 22)
        cp.clicked.connect(
            lambda: self.breadcrumb_clicked.emit("control_panel"))
        sep1 = QLabel("|", h); sep1.setGeometry(272, 22, 8, 22)
        sep1.setFont(inter(11))
        sep1.setStyleSheet(
            f"color: {TEXT_DIM}; background: transparent;")

        sl = _BreadcrumbLink("Songs Library", h)
        sl.setGeometry(284, 22, 100, 22)
        sl.clicked.connect(
            lambda: self.breadcrumb_clicked.emit("songs"))
        sep2 = QLabel("|", h); sep2.setGeometry(384, 22, 8, 22)
        sep2.setFont(inter(11))
        sep2.setStyleSheet(
            f"color: {TEXT_DIM}; background: transparent;")
        pill = _BreadcrumbPill("Cat. Performance", PURPLE, h)
        pill.move(396, 20)

        title = QLabel("Category Performance", h)
        title.setGeometry(540, 12, 300, 24)
        title.setFont(inter(20, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        sub2 = QLabel(
            "Complete airplay analytics for the selected category", h)
        sub2.setGeometry(540, 38, 500, 14)
        sub2.setFont(inter(10))
        sub2.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

        self._clock_lbl = QLabel("", h)
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

        osb = _HeaderOpenStudio(h)
        osb.move(1222, 16)
        osb.clicked.connect(self.studio_clicked.emit)

    # ── Body ──────────────────────────────────────────────────────────

    def _build_body(self) -> None:
        self._hero = _HeroCard(self)
        self._hero.move(16, 88)

        self._stat_month = _StatCard(
            "Plays This Month", GREEN, GREEN_LIGHT, self)
        self._stat_week  = _StatCard(
            "Plays This Week",  CYAN,  CYAN_LIGHT,  self)
        self._stat_avg   = _StatCard(
            "Avg per Song",     AMBER, AMBER_LIGHT, self)
        self._stat_top   = _StatCard(
            "Most Played",      PURPLE, PURPLE_LIGHT, self)
        SCARD_W = 340; SCARD_GAP = 12
        total_w = 4 * SCARD_W + 3 * SCARD_GAP
        start_x = (WINDOW_W - total_w) // 2
        ys = 256
        for i, c in enumerate(
                (self._stat_month, self._stat_week,
                 self._stat_avg, self._stat_top)):
            c.move(start_x + i * (SCARD_W + SCARD_GAP), ys)

        self._chart = _MonthlyChart(self)
        self._chart.move(16, 360)

        self._songs = _SongsRankedTable(self)
        self._songs.move(16, 632)

    # ── Status bar ────────────────────────────────────────────────────

    def _build_status_bar(self) -> None:
        sb = QFrame(self)
        sb.setGeometry(0, WINDOW_H - STATUS_H, WINDOW_W, STATUS_H)
        sb.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border-top: 1px solid {rgba('#ffffff', 0.06)}; }}"
        )
        x = 12
        for txt, col in (("AUTO MODE", PURPLE),
                          ("Live Data", GREEN),
                          ("Category View", CYAN)):
            p = _StatusPill(txt, col, sb)
            p.move(x, (STATUS_H - p.height()) // 2)
            x += p.width() + 8

        ver = QLabel("Category Performance  ·  RadioAI Studio v1.0.0", sb)
        ver.setFont(inter(9))
        ver.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; "
            f"border: none;")
        ver.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        ver.setFixedSize(360, STATUS_H)
        ver.move(WINDOW_W - 24 - 360 - 130, 0)

        osb = QPushButton("▶  Open Studio", sb)
        osb.setFixedSize(120, 26)
        osb.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        osb.setFont(inter(10, QFont.Weight.Bold))
        osb.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {GREEN_LIGHT}; "
            f"border: none; padding: 0 8px; }}"
            f"QPushButton:hover {{ color: {GREEN}; }}"
        )
        osb.move(WINDOW_W - 12 - 120, (STATUS_H - 26) // 2)
        osb.clicked.connect(self.studio_clicked.emit)

    # ── Clock ─────────────────────────────────────────────────────────

    def _tick_clock(self) -> None:
        self._clock_lbl.setText(datetime.now().strftime("%H:%M:%S"))

    # ── Public API ────────────────────────────────────────────────────

    def load_category(self, category_id: int) -> None:
        """Fetch + render everything for `category_id`. Re-callable."""
        try:
            cid = int(category_id)
        except Exception:
            cid = 0
        if cid <= 0:
            log.warning(
                f"CategoryPerformance.load_category: invalid id={category_id!r}")
            return
        self._category_id = cid

        try:
            summary = self._db.get_category_performance_summary(cid)
        except Exception as exc:
            log.warning(f"category summary failed: {exc}")
            summary = {"category_id": cid, "category_name": "—",
                       "song_count": 0, "total_plays": 0,
                       "avg_per_song": 0.0, "most_played": None}

        try:
            monthly = self._db.get_category_monthly_plays(cid, 12)
        except Exception as exc:
            log.warning(f"category monthly plays failed: {exc}")
            monthly = []

        try:
            songs = self._db.get_category_songs_ranked(cid)
        except Exception as exc:
            log.warning(f"category songs ranked failed: {exc}")
            songs = []

        self._hero.load_category(summary)
        self._update_stats(summary)
        self._chart.set_data(monthly)
        self._songs.load_rows(songs, summary.get("category_name") or "")
        log.info(
            f"CategoryPerformance loaded — cat_id={cid} "
            f"name={summary.get('category_name')!r} "
            f"songs={summary.get('song_count')} "
            f"total={summary.get('total_plays')} "
            f"months={len(monthly)} rows={len(songs)}")

    def _update_stats(self, summary: dict) -> None:
        cur_m = int(summary.get("plays_this_month") or 0)
        prev_m = int(summary.get("plays_last_month") or 0)
        diff_m = cur_m - prev_m
        diff_m_s = (f"+{diff_m} vs last month" if diff_m >= 0
                    else f"{diff_m} vs last month")
        self._stat_month.set_value(str(cur_m), diff_m_s)

        cur_w = int(summary.get("plays_this_week") or 0)
        prev_w = int(summary.get("plays_last_week") or 0)
        diff_w = cur_w - prev_w
        diff_w_s = (f"+{diff_w} vs last week" if diff_w >= 0
                    else f"{diff_w} vs last week")
        self._stat_week.set_value(str(cur_w), diff_w_s)

        # Avg per song — lifetime average. total_plays ÷ song_count.
        # Surface a sub-line that explains the math so the operator
        # can sanity-check the number against the hero readout.
        song_count = int(summary.get("song_count") or 0)
        total = int(summary.get("total_plays") or 0)
        avg = summary.get("avg_per_song") or 0.0
        try:
            avg_s = (f"{float(avg):.1f}" if float(avg) != int(avg)
                     else str(int(avg)))
        except (TypeError, ValueError):
            avg_s = "0"
        avg_sub = (f"{total:,} plays ÷ {song_count} songs"
                   if song_count > 0 else "no songs")
        self._stat_avg.set_value(avg_s, avg_sub)

        # Most played — title as the big text, "artist · N plays" sub.
        mp = summary.get("most_played")
        if mp:
            title = mp.get("title") or "—"
            # Trim very long titles so they don't get clipped
            if len(title) > 18:
                title = title[:17] + "…"
            artist = mp.get("artist") or "—"
            count = int(mp.get("count") or 0)
            self._stat_top.set_value(
                title, f"{artist}  ·  {count} plays")
        else:
            self._stat_top.set_value("—", "no plays yet")
