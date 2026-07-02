"""
RadioAI Studio Pro — Jingle Editor Dialog (Add / Edit)
Pixel-accurate match of Figma node 106:2 (file 7oN9K61g94wKx3nu44KKDF).

Single dialog used for both "Add New Jingle" and "Edit Jingle":
  • Mode NEW  — jingle_id is None; AUTO CODE is generated server-side
                (db.next_jingle_auto_code) and shown in the header pill.
  • Mode EDIT — jingle_id is provided; existing row's data is preloaded
                into every field; auto_code is read-only display.

Layout (860×640, three-zone BaseDialog):
  HEADER (52h)   🔔 NEW JINGLE · subtitle · AUTO CODE pill · ✕
  CONTENT
    LEFT (560w):  Title* · Author / Code / Date · Comments ·
                  CATEGORY tile grid · TRACK PROPERTIES · AUDIO FILE picker
    RIGHT (260w): AVAILABILITY · SCHEDULING · SEPARATION ·
                  LINKED SPOTS · ✦ AI Auto-fill (stub)
  FOOTER (52h)   * Required fields · Cancel · ✓ Save

Key contrast vs the Sweeper Editor (Figma 108:2): jingles don't overlay
songs, so the entire POSITION SETTINGS / OVERLAY BEHAVIOR / POSITION
OFFSET zone is gone. In its place the right sidebar gains the LINKED
SPOTS card (a many-to-many between jingles and campaigns, persisted
through `jingle_linked_spots`).

Persistence:
  Save → calls db.add_jingle / update_jingle. Emits jingle_saved(id).
  Linked-spot picks save through db.set_jingle_linked_spots(...).

Phase status:
  [✓] Full layout, all jingle fields editable, save round-trips.
  [✓] LINKED SPOTS persistence end-to-end (UI shows existing links;
      add/remove pickers stub-toast for now — the picker dialog is
      a separate follow-up).
  [ ] AI Auto-fill Metadata — stub toast (no LLM hookup yet)
  [ ] Audio file probe (auto-fill duration_ms from BASS) — operator
      types duration manually for now
  [ ] Edit-Audio button → AudioCueEditorDialog hookup (future)
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Optional

from PyQt6.QtCore import Qt, QRectF, pyqtSignal
from core import dialogs
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QPainterPath, QFont, QCursor,
    QIntValidator,
)
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QLineEdit, QTextEdit, QComboBox,
    QHBoxLayout, QVBoxLayout, QFileDialog, QMessageBox,
)

from ui.dialogs.base_dialog import BaseDialog
# Reuse the generic input/section/category helpers from the Sweeper
# editor — they aren't sweeper-specific despite the underscore prefix
# (operator-driven decision: 3+ libraries share the chrome now, time
# to consolidate; full extraction to ui/widgets/library_chrome.py
# remains a flagged carry-over).
from ui.dialogs.sweeper_editor_dialog import (
    _SectionHeader, _LabeledField, _CategoryTile,
    _AvailabilityCard, _AICard,
    _styled_lineedit, _styled_textedit, _styled_combo,
    _fmt_duration as _fmt_duration_sweeper,
    _parse_duration as _parse_duration_sweeper,
)
from ui.widgets._tokens import (
    inter, mono, rgba,
    BG_BASE, BG_PANEL, BG_CARD, BG_ELEVATED,
    TEXT_PRI, TEXT_SEC, TEXT_MUTED, TEXT_DIM,
    CYAN, CYAN_LIGHT, PURPLE, PURPLE_LIGHT, GREEN, GREEN_LIGHT,
    AMBER, AMBER_LIGHT, RED, RED_LIGHT, PINK, PINK_LIGHT,
)

log = logging.getLogger("JingleEditorDialog")


# ════════════════════════════════════════════════════════════════════════════
# Geometry tokens
# ════════════════════════════════════════════════════════════════════════════

DLG_W = 860
DLG_H = 640

LEFT_W = 560
RIGHT_W = 260

# 8 jingle categories — match the ui/jingles_library.py grid + the
# Figma 106:2 4×2 tile arrangement.
CATEGORY_OPTIONS = [
    "Station ID",  "Shotguns",  "Ad Break",  "News Break",
    "Weather",     "Traffic",   "Promo",     "Signature",
]


def _fmt_duration(ms: int) -> str:
    return _fmt_duration_sweeper(ms)


def _parse_duration(text: str) -> int:
    return _parse_duration_sweeper(text)


# ════════════════════════════════════════════════════════════════════════════
# LINKED SPOTS card — jingle-specific
# ════════════════════════════════════════════════════════════════════════════


class _LinkedSpotsCard(QFrame):
    """Lists campaigns currently linked to the jingle. + adds a link
    (toast for now — the campaign-picker dialog is deferred), − removes
    the highlighted link.

    Persistence is owned by the dialog: it caches the current set of
    campaign_ids on this widget and writes them through
    db.set_jingle_linked_spots(...) on save."""

    add_requested    = pyqtSignal()
    remove_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[dict] = []     # cached spot dicts
        self._highlighted: Optional[int] = None
        self.setStyleSheet(
            f"QFrame {{ background: {BG_CARD}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; "
            f"border-radius: 6px; }}"
        )
        self.setFixedHeight(108)

        # + / − buttons — fixed, top-right
        self._add_btn = QPushButton("+", self)
        self._add_btn.setFixedSize(22, 22)
        self._add_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._add_btn.setFont(inter(13, QFont.Weight.Bold))
        self._add_btn.setStyleSheet(
            f"QPushButton {{ background: {rgba(GREEN, 0.18)}; "
            f"color: {GREEN_LIGHT}; "
            f"border: 1px solid {rgba(GREEN, 0.40)}; border-radius: 4px; }}"
            f"QPushButton:hover {{ background: {rgba(GREEN, 0.30)}; }}"
        )
        self._add_btn.clicked.connect(self.add_requested.emit)

        self._del_btn = QPushButton("−", self)
        self._del_btn.setFixedSize(22, 22)
        self._del_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._del_btn.setFont(inter(13, QFont.Weight.Bold))
        self._del_btn.setStyleSheet(
            f"QPushButton {{ background: {rgba(RED, 0.18)}; "
            f"color: {RED_LIGHT}; "
            f"border: 1px solid {rgba(RED, 0.40)}; border-radius: 4px; }}"
            f"QPushButton:hover {{ background: {rgba(RED, 0.30)}; }}"
        )
        self._del_btn.clicked.connect(self.remove_requested.emit)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        # Pin the +/− buttons to the right edge with a 8px margin.
        self._add_btn.move(self.width() - 36, 8)
        self._del_btn.move(self.width() - 36, 36)

    def set_rows(self, rows: list[dict]) -> None:
        """Bind the card to the current linked-spots set. `rows` is a
        list of dicts: [{'campaign_id', 'name', 'auto_code'}, ...]."""
        self._rows = list(rows or [])
        if self._rows:
            self._highlighted = int(self._rows[0]["campaign_id"])
        else:
            self._highlighted = None
        self.update()

    def linked_campaign_ids(self) -> list[int]:
        return [int(r["campaign_id"]) for r in self._rows]

    def remove_highlighted(self) -> None:
        """Drop the currently-highlighted row from the cached set."""
        if self._highlighted is None:
            return
        self._rows = [r for r in self._rows
                      if int(r["campaign_id"]) != int(self._highlighted)]
        self._highlighted = (int(self._rows[0]["campaign_id"])
                             if self._rows else None)
        self.update()

    def add_campaign(self, campaign_id: int, name: str,
                     auto_code: str) -> None:
        """Add a campaign to the cached set (de-duped). The dialog's
        add-handler stub will eventually call this when the picker
        lands."""
        if any(int(r["campaign_id"]) == int(campaign_id)
               for r in self._rows):
            return
        self._rows.append({
            "campaign_id": int(campaign_id),
            "name":        name or f"Campaign #{campaign_id}",
            "auto_code":   auto_code or "",
        })
        self._highlighted = int(campaign_id)
        self.update()

    def paintEvent(self, _e):
        super().paintEvent(_e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Section is the parent's background. We just paint the rows.
        if not self._rows:
            p.setPen(QColor(TEXT_MUTED))
            p.setFont(inter(10, QFont.Weight.Medium))
            p.drawText(QRectF(12, 0, self.width() - 50, self.height()),
                       Qt.AlignmentFlag.AlignLeft
                       | Qt.AlignmentFlag.AlignVCenter,
                       "No linked spots")
            return
        # Render up to 3 rows; truncate with "+ N more" if more exist.
        visible = self._rows[:3]
        row_h = 26
        y0 = 8
        for i, r in enumerate(visible):
            y = y0 + i * row_h
            is_hi = (self._highlighted is not None
                     and int(r["campaign_id"]) == int(self._highlighted))
            if is_hi:
                p.fillRect(QRectF(8, y, self.width() - 50, row_h - 4),
                           QColor(rgba(CYAN, 0.10)))
                p.setPen(QColor(CYAN_LIGHT))
            else:
                p.setPen(QColor(TEXT_SEC))
            p.setFont(inter(10, QFont.Weight.DemiBold))
            p.drawText(
                QRectF(14, y, self.width() - 60, row_h - 4),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                r.get("name") or "—")
            if r.get("auto_code"):
                p.setPen(QColor(TEXT_MUTED))
                p.setFont(mono(8, bold=True))
                p.drawText(
                    QRectF(self.width() - 110, y, 60, row_h - 4),
                    Qt.AlignmentFlag.AlignRight
                    | Qt.AlignmentFlag.AlignVCenter,
                    r["auto_code"])
        if len(self._rows) > 3:
            p.setPen(QColor(TEXT_MUTED))
            p.setFont(inter(9))
            p.drawText(
                QRectF(14, y0 + 3 * row_h, self.width() - 28, row_h - 4),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                f"+ {len(self._rows) - 3} more")

    def mousePressEvent(self, e):
        # Click anywhere on a row line to highlight it (so − knows
        # which one to drop).
        if e.button() == Qt.MouseButton.LeftButton and self._rows:
            row_h = 26
            y0 = 8
            idx = (int(e.position().y()) - y0) // row_h
            if 0 <= idx < min(3, len(self._rows)):
                self._highlighted = int(self._rows[idx]["campaign_id"])
                self.update()
        super().mousePressEvent(e)


# ════════════════════════════════════════════════════════════════════════════
# Main dialog
# ════════════════════════════════════════════════════════════════════════════

class JingleEditorDialog(BaseDialog):
    """Add or Edit a jingle. See module docstring for layout +
    persistence."""

    HEADER_H = 52
    FOOTER_H = 52

    jingle_saved = pyqtSignal(int)   # id of inserted/updated jingle

    def __init__(self, db, jingle_id: Optional[int] = None, parent=None):
        self._db = db
        self._jingle_id = jingle_id
        self._mode_edit = jingle_id is not None

        # Make sure the schema can accept the dialog's writes before
        # any widget queries the row.
        try:
            self._db._ensure_jingles_columns()
        except Exception as exc:
            log.error(f"_ensure_jingles_columns failed: {exc}")

        # Pre-fetch existing row + linked spots if editing
        self._existing: dict = {}
        self._initial_links: list[dict] = []
        if self._mode_edit:
            self._existing = self._fetch_existing(int(jingle_id))
            self._initial_links = self._fetch_links(int(jingle_id))

        # State driven by widgets
        self._auto_code: str = (self._existing.get("auto_code")
                                if self._mode_edit
                                else db.next_jingle_auto_code())
        self._selected_category: str = (self._existing.get("category")
                                        or "Station ID")

        # Widget refs
        self._title_input: Optional[QLineEdit] = None
        self._author_input: Optional[QLineEdit] = None
        self._code_input: Optional[QLineEdit] = None
        self._date_input: Optional[QLineEdit] = None
        self._comments_input: Optional[QTextEdit] = None
        self._props_input: Optional[QLineEdit] = None
        self._duration_input: Optional[QLineEdit] = None
        self._bpm_input: Optional[QLineEdit] = None
        self._era_input: Optional[QLineEdit] = None
        self._file_input: Optional[QLineEdit] = None
        self._cat_tiles: dict[str, _CategoryTile] = {}
        self._availability: Optional[_AvailabilityCard] = None
        self._clock_combo: Optional[QComboBox] = None
        self._clocks_index: list[int] = []
        self._min_gap_input: Optional[QLineEdit] = None
        self._max_per_hour_input: Optional[QLineEdit] = None
        self._linked_spots: Optional[_LinkedSpotsCard] = None

        super().__init__(target_size=(DLG_W, DLG_H), parent=parent)
        self.setWindowTitle(
            "Edit Jingle" if self._mode_edit else "New Jingle")

        self._populate_from_existing()

        log.info(
            f"JingleEditorDialog ready (mode="
            f"{'EDIT' if self._mode_edit else 'NEW'}, id={jingle_id}, "
            f"auto_code={self._auto_code})")

    # ── Data helpers ─────────────────────────────────────────────────────

    def _fetch_existing(self, jid: int) -> dict:
        try:
            row = self._db._conn().execute(
                "SELECT * FROM jingles WHERE id = ?", [jid]).fetchone()
            if row is None:
                return {}
            return {k: row[k] for k in row.keys()}
        except Exception as exc:
            log.error(f"fetch_existing(id={jid}) failed: {exc}")
            return {}

    def _fetch_links(self, jid: int) -> list[dict]:
        try:
            return [{k: r[k] for k in r.keys()} for r in
                    self._db.get_jingle_linked_spots(int(jid))]
        except Exception as exc:
            log.error(f"fetch_links(id={jid}) failed: {exc}")
            return []

    # ── Header ───────────────────────────────────────────────────────────

    def _build_header(self) -> QWidget:
        f = QFrame()
        f.setObjectName("jingleEditorHeader")
        f.setStyleSheet(
            "QFrame#jingleEditorHeader { "
            "background: qlineargradient(x1:0,y1:0,x2:0,y2:1, "
            "stop:0 rgba(20,22,40,0.95), stop:1 rgba(13,15,30,0.95)); "
            "border-top-left-radius: 12px; "
            "border-top-right-radius: 12px; "
            f"border-bottom: 1px solid {rgba('#ffffff', 0.06)};"
            "}"
        )
        # 🔔 icon tile
        icon = QLabel("🔔", f)
        icon.setGeometry(14, 12, 28, 28)
        icon.setFont(inter(13, QFont.Weight.Black))
        icon.setStyleSheet(
            f"QLabel {{ background: {rgba(AMBER, 0.18)}; "
            f"color: {AMBER_LIGHT}; "
            f"border: 1px solid {rgba(AMBER, 0.30)}; "
            f"border-radius: 6px; }}"
        )
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Title
        title = QLabel(
            "EDIT JINGLE" if self._mode_edit else "NEW JINGLE", f)
        title.setGeometry(50, 10, 240, 18)
        title.setFont(inter(13, QFont.Weight.Bold, letter_spacing=1.2))
        title.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        sub = QLabel(
            "Update an existing station jingle"
            if self._mode_edit
            else "Add a new station jingle to the library", f)
        sub.setGeometry(50, 30, 320, 14)
        sub.setFont(inter(9))
        sub.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

        # AUTO CODE pill (right-side)
        pill = QFrame(f)
        pill.setGeometry(DLG_W - 158, 12, 110, 28)
        pill.setStyleSheet(
            f"QFrame {{ background: {rgba(GREEN, 0.16)}; "
            f"border: 1px solid {rgba(GREEN, 0.40)}; "
            f"border-radius: 6px; }}"
        )
        cl = QLabel("AUTO CODE", pill)
        cl.setGeometry(8, 3, 60, 11)
        cl.setFont(inter(8, QFont.Weight.Bold, letter_spacing=1.0))
        cl.setStyleSheet(f"color: {GREEN}; background: transparent;")
        cv = QLabel(self._auto_code, pill)
        cv.setGeometry(8, 14, 100, 13)
        cv.setFont(mono(11, bold=True))
        cv.setStyleSheet(f"color: {GREEN_LIGHT}; background: transparent;")

        # Close
        x = QPushButton("✕", f)
        x.setGeometry(DLG_W - 42, 11, 30, 30)
        x.setFont(inter(13, QFont.Weight.Bold))
        x.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        x.setStyleSheet(
            f"QPushButton {{ background: #1c1f38; color: {TEXT_SEC}; "
            f"border: none; border-radius: 6px; }}"
            f"QPushButton:hover {{ background: {rgba(RED, 0.20)}; "
            f"color: {RED_LIGHT}; }}"
        )
        x.clicked.connect(self.reject)
        return f

    # ── Content ──────────────────────────────────────────────────────────

    def _build_content(self) -> QWidget:
        body = QFrame()
        body.setStyleSheet("background: transparent;")
        h = QHBoxLayout(body)
        h.setContentsMargins(16, 12, 16, 12)
        h.setSpacing(12)

        h.addWidget(self._build_left_form(), 0)

        # Vertical divider
        sep = QFrame()
        sep.setFixedWidth(1)
        sep.setStyleSheet(f"background: {rgba('#ffffff', 0.06)};")
        h.addWidget(sep)

        h.addWidget(self._build_right_sidebar(), 0)
        h.addStretch()
        return body

    # ── Left form ────────────────────────────────────────────────────────

    def _build_left_form(self) -> QWidget:
        wrap = QFrame()
        wrap.setFixedWidth(LEFT_W)
        wrap.setStyleSheet("background: transparent;")
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)

        # Jingle Title *
        self._title_input = _styled_lineedit("Enter jingle name…")
        v.addWidget(_LabeledField("Jingle Title *", self._title_input))

        # Author / Playlister Code / Entry Date — three-column row
        triple = QFrame(); triple.setStyleSheet("background: transparent;")
        th = QHBoxLayout(triple)
        th.setContentsMargins(0, 0, 0, 0); th.setSpacing(8)
        self._author_input = _styled_lineedit("e.g. RadioAI")
        author_box = _LabeledField("Author", self._author_input)
        author_box.setFixedWidth(180)
        # Default visible Playlister Code derived from auto_code so it
        # reads as the operator expects (JI-NNNN). Persist as-typed.
        ji_default = "JI-" + self._auto_code.split("-", 1)[-1]
        self._code_input = _styled_lineedit(ji_default, mono_font=True)
        code_box = _LabeledField("Playlister Code", self._code_input)
        code_box.setFixedWidth(160)
        self._date_input = _styled_lineedit("Now (Auto)")
        date_box = _LabeledField("Entry Date", self._date_input)
        date_box.setFixedWidth(184)
        th.addWidget(author_box); th.addWidget(code_box)
        th.addWidget(date_box); th.addStretch()
        v.addWidget(triple)

        # Comments
        self._comments_input = _styled_textedit(
            "Created automatically — auto-generated comment")
        v.addWidget(_LabeledField("Comments", self._comments_input))

        # CATEGORY section — 4×2 grid (8 jingle categories)
        v.addWidget(_SectionHeader("CATEGORY", PURPLE_LIGHT))
        cat_grid = QFrame(); cat_grid.setStyleSheet("background: transparent;")
        cv = QVBoxLayout(cat_grid)
        cv.setContentsMargins(0, 0, 0, 0); cv.setSpacing(8)
        for row_idx in range(2):
            row = QFrame(); row.setStyleSheet("background: transparent;")
            rh = QHBoxLayout(row)
            rh.setContentsMargins(0, 0, 0, 0); rh.setSpacing(8)
            for col in range(4):
                name = CATEGORY_OPTIONS[row_idx * 4 + col]
                tile = _CategoryTile(name)
                tile.setFixedWidth(128)
                tile.clicked.connect(
                    lambda _checked=False, n=name: self._on_category_picked(n))
                self._cat_tiles[name] = tile
                rh.addWidget(tile)
            rh.addStretch()
            cv.addWidget(row)
        v.addWidget(cat_grid)

        # TRACK PROPERTIES section
        v.addWidget(_SectionHeader("TRACK PROPERTIES", CYAN))
        props_row = QFrame()
        props_row.setStyleSheet("background: transparent;")
        ph = QHBoxLayout(props_row)
        ph.setContentsMargins(0, 0, 0, 0); ph.setSpacing(8)
        self._props_input = _styled_lineedit("Top of Hour")
        props_box = _LabeledField("Properties", self._props_input)
        props_box.setFixedWidth(130)
        self._duration_input = _styled_lineedit("0:05", mono_font=True)
        dur_box = _LabeledField("Duration", self._duration_input)
        dur_box.setFixedWidth(120)
        self._bpm_input = _styled_lineedit("Optional")
        bpm_box = _LabeledField("BPM", self._bpm_input)
        bpm_box.setFixedWidth(120)
        self._era_input = _styled_lineedit(str(datetime.now().year))
        era_box = _LabeledField("Era / Year", self._era_input)
        era_box.setFixedWidth(150)
        ph.addWidget(props_box); ph.addWidget(dur_box)
        ph.addWidget(bpm_box); ph.addWidget(era_box); ph.addStretch()
        v.addWidget(props_row)

        # AUDIO FILE section
        v.addWidget(_SectionHeader("AUDIO FILE", AMBER))
        af_row = QFrame(); af_row.setStyleSheet("background: transparent;")
        ah = QHBoxLayout(af_row)
        ah.setContentsMargins(0, 0, 0, 0); ah.setSpacing(8)
        self._file_input = _styled_lineedit("C:\\Audio\\Jingles\\select file…")
        ah.addWidget(self._file_input, 1)
        browse = QPushButton("…")
        browse.setFixedSize(34, 30)
        browse.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        browse.setFont(inter(11, QFont.Weight.Bold))
        browse.setStyleSheet(
            f"QPushButton {{ background: {BG_CARD}; color: {TEXT_SEC}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; border-radius: 6px; }}"
            f"QPushButton:hover {{ background: {rgba(CYAN, 0.16)}; "
            f"color: {CYAN_LIGHT}; }}"
        )
        browse.clicked.connect(self._on_browse_audio)
        ah.addWidget(browse)
        edit = QPushButton("Edit")
        edit.setFixedSize(44, 30)
        edit.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        edit.setFont(inter(10, QFont.Weight.Bold))
        edit.setStyleSheet(
            f"QPushButton {{ background: {BG_CARD}; color: {TEXT_MUTED}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; border-radius: 6px; }}"
            f"QPushButton:hover {{ background: {rgba(AMBER, 0.16)}; "
            f"color: {AMBER_LIGHT}; }}"
        )
        edit.clicked.connect(self._on_edit_audio_clicked)
        ah.addWidget(edit)
        v.addWidget(af_row)

        # Decorative ▶ Preview waveform footer (cosmetic per Figma 106:2;
        # real preview wiring lands with the standalone-screen preview).
        prev = QFrame()
        prev.setFixedHeight(30)
        prev.setStyleSheet(
            f"background: {BG_CARD}; "
            f"border: 1px solid {rgba(PURPLE, 0.30)}; "
            f"border-radius: 6px;")
        pl = QHBoxLayout(prev)
        pl.setContentsMargins(8, 0, 8, 0); pl.setSpacing(8)
        play_lbl = QLabel("▶  Preview")
        play_lbl.setFont(inter(10, QFont.Weight.Bold))
        play_lbl.setStyleSheet(
            f"color: {PURPLE_LIGHT}; background: transparent;")
        pl.addWidget(play_lbl)
        pl.addStretch()
        v.addWidget(prev)

        v.addStretch()
        return wrap

    # ── Right sidebar ────────────────────────────────────────────────────

    def _build_right_sidebar(self) -> QWidget:
        wrap = QFrame()
        wrap.setFixedWidth(RIGHT_W)
        wrap.setStyleSheet("background: transparent;")
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)

        # AVAILABILITY
        v.addWidget(_SectionHeader("AVAILABILITY", GREEN))
        self._availability = _AvailabilityCard()
        v.addWidget(self._availability)

        # SCHEDULING — clock dropdown
        v.addWidget(_SectionHeader("SCHEDULING", CYAN_LIGHT))
        clock_items, ids = self._fetch_clocks()
        self._clocks_index = ids
        self._clock_combo = _styled_combo(clock_items, default=clock_items[0])
        v.addWidget(_LabeledField("Clock Assignment", self._clock_combo))
        hint = QLabel("Can also use: Playlists, Force Clocks, Final Log")
        hint.setFont(inter(9))
        hint.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        v.addWidget(hint)

        # SEPARATION
        v.addWidget(_SectionHeader("SEPARATION SETTINGS", AMBER_LIGHT))
        sep_row = QFrame(); sep_row.setStyleSheet("background: transparent;")
        sh = QHBoxLayout(sep_row)
        sh.setContentsMargins(0, 0, 0, 0); sh.setSpacing(8)
        self._min_gap_input = _styled_lineedit("30 min")
        self._min_gap_input.setValidator(
            QIntValidator(0, 1440, self._min_gap_input))
        mg_box = _LabeledField("Min gap", self._min_gap_input)
        mg_box.setFixedWidth(118)
        self._max_per_hour_input = _styled_lineedit("2 plays")
        self._max_per_hour_input.setValidator(
            QIntValidator(0, 60, self._max_per_hour_input))
        mp_box = _LabeledField("Max per hour", self._max_per_hour_input)
        mp_box.setFixedWidth(124)
        sh.addWidget(mg_box); sh.addWidget(mp_box); sh.addStretch()
        v.addWidget(sep_row)

        # LINKED SPOTS
        v.addWidget(_SectionHeader("LINKED SPOTS", PINK_LIGHT))
        self._linked_spots = _LinkedSpotsCard()
        self._linked_spots.add_requested.connect(
            self._on_linked_spot_add)
        self._linked_spots.remove_requested.connect(
            self._on_linked_spot_remove)
        v.addWidget(self._linked_spots)

        # AI Auto-fill (stub)
        ai = _AICard()
        ai.clicked.connect(self._on_ai_autofill)
        v.addWidget(ai)

        v.addStretch()
        return wrap

    def _fetch_clocks(self) -> tuple[list[str], list[int]]:
        items = ["— No clock —"]
        ids: list[int] = [0]
        try:
            rows = self._db._conn().execute(
                "SELECT id, name FROM clocks ORDER BY id DESC"
            ).fetchall()
            for r in rows:
                items.append(str(r["name"] or f"Clock #{r['id']}"))
                ids.append(int(r["id"]))
        except Exception as exc:
            log.error(f"clocks fetch failed: {exc}")
        return items, ids

    # ── Footer ───────────────────────────────────────────────────────────

    def _build_footer(self) -> QWidget:
        f = QFrame()
        f.setStyleSheet(
            "QFrame { background: rgba(13,15,30,0.95); "
            f"border-top: 1px solid {rgba('#ffffff', 0.06)}; "
            "border-bottom-left-radius: 12px; "
            "border-bottom-right-radius: 12px; }"
        )
        rq = QLabel("* Required fields", f)
        rq.setGeometry(16, 18, 200, 14)
        rq.setFont(inter(9))
        rq.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

        cancel = QPushButton("Cancel", f)
        cancel.setGeometry(DLG_W - 192, 12, 82, 30)
        cancel.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        cancel.setFont(inter(11, QFont.Weight.DemiBold))
        cancel.setStyleSheet(
            f"QPushButton {{ background: #1c1f38; color: {TEXT_SEC}; "
            f"border: none; border-radius: 6px; }}"
            f"QPushButton:hover {{ background: #262947; color: {TEXT_PRI}; }}"
        )
        cancel.clicked.connect(self.reject)

        save = QPushButton("✓ Save", f)
        save.setGeometry(DLG_W - 102, 12, 84, 30)
        save.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        save.setFont(inter(11, QFont.Weight.Bold))
        save.setStyleSheet(
            f"QPushButton {{ background: {GREEN}; color: white; "
            f"border: none; border-radius: 6px; }}"
            f"QPushButton:hover {{ background: {GREEN_LIGHT}; }}"
        )
        save.clicked.connect(self._on_save)
        return f

    # ── Populate / commit ────────────────────────────────────────────────

    def _populate_from_existing(self):
        self._sync_category_visual()
        if self._linked_spots and self._initial_links:
            self._linked_spots.set_rows(self._initial_links)
        if not self._mode_edit:
            return
        e = self._existing
        if self._title_input:
            self._title_input.setText(e.get("name") or "")
        if self._author_input:
            self._author_input.setText(e.get("author") or "")
        if self._code_input:
            self._code_input.setText(e.get("playlister_code") or "")
        if self._date_input:
            self._date_input.setText(e.get("entry_date") or "")
        if self._comments_input:
            self._comments_input.setPlainText(e.get("comments") or "")
        if self._props_input:
            self._props_input.setText(e.get("properties") or "")
        if self._duration_input:
            self._duration_input.setText(
                _fmt_duration(e.get("duration_ms") or 0))
        if self._bpm_input:
            self._bpm_input.setText(e.get("bpm") or "")
        if self._era_input:
            self._era_input.setText(e.get("era_year") or "")
        if self._file_input:
            self._file_input.setText(e.get("file_path") or "")
        if self._availability:
            self._availability.set_enabled(bool(e.get("is_enabled", 1)))
        if self._clock_combo:
            cid = int(e.get("clock_id") or 0)
            if cid in self._clocks_index:
                self._clock_combo.setCurrentIndex(
                    self._clocks_index.index(cid))
        if self._min_gap_input:
            self._min_gap_input.setText(
                str(int(e.get("min_gap_minutes") or 30)))
        if self._max_per_hour_input:
            self._max_per_hour_input.setText(
                str(int(e.get("max_per_hour") or 2)))

    def _collect_values(self) -> dict:
        cur_clock_id = 0
        if self._clock_combo:
            idx = self._clock_combo.currentIndex()
            if 0 <= idx < len(self._clocks_index):
                cur_clock_id = self._clocks_index[idx]
        return {
            "name":            (self._title_input.text() if self._title_input
                                else "").strip(),
            "category":        self._selected_category,
            "file_path":       (self._file_input.text() if self._file_input
                                else "").strip(),
            "duration_ms":     _parse_duration(
                self._duration_input.text() if self._duration_input else ""),
            "properties":      (self._props_input.text() if self._props_input
                                else "").strip(),
            "playlister_code": (self._code_input.text() if self._code_input
                                else "").strip(),
            "is_enabled":      self._availability.is_enabled()
                                if self._availability else True,
            "author":          (self._author_input.text()
                                if self._author_input else "").strip(),
            "entry_date":      self._effective_entry_date(),
            "comments":        (self._comments_input.toPlainText()
                                if self._comments_input else "").strip(),
            "bpm":             (self._bpm_input.text() if self._bpm_input
                                else "").strip(),
            "era_year":        (self._era_input.text() if self._era_input
                                else "").strip(),
            "clock_id":        cur_clock_id or None,
            "min_gap_minutes": self._safe_int(
                self._min_gap_input.text()
                if self._min_gap_input else "", 30),
            "max_per_hour":    self._safe_int(
                self._max_per_hour_input.text()
                if self._max_per_hour_input else "", 2),
        }

    def _effective_entry_date(self) -> str:
        text = (self._date_input.text() if self._date_input else "").strip()
        if not text or text.lower().startswith("now"):
            return datetime.now().strftime("%Y-%m-%d")
        return text

    @staticmethod
    def _safe_int(text: str, default: int) -> int:
        try:
            return int((text or "").strip().split()[0])
        except Exception:
            return default

    # ── Event handlers ───────────────────────────────────────────────────

    def _on_category_picked(self, name: str):
        self._selected_category = name
        self._sync_category_visual()

    def _sync_category_visual(self):
        for n, tile in self._cat_tiles.items():
            tile.set_active(n == self._selected_category)

    def _on_browse_audio(self):
        start_dir = ""
        if self._file_input and self._file_input.text():
            start_dir = os.path.dirname(self._file_input.text())
        path, _ = QFileDialog.getOpenFileName(
            self, "Select jingle audio file", start_dir,
            "Audio files (*.mp3 *.wav *.ogg *.flac *.m4a);;All files (*.*)")
        if path and self._file_input:
            self._file_input.setText(path)

    def _on_edit_audio_clicked(self):
        dialogs.info(
            self, "Coming soon",
            "Audio cue editor for jingles is being wired in a follow-up "
            "session — for now, set the file path here and adjust cue "
            "points via the Songs Library audio editor on the source file.")

    def _on_ai_autofill(self):
        dialogs.info(
            self, "Coming soon",
            "AI Auto-fill Metadata will detect category + duration from "
            "the audio file. Hookup deferred — populate fields manually "
            "for now.")

    def _on_linked_spot_add(self):
        # The campaign-picker dialog is a separate follow-up. Toast for
        # now so the +/- buttons are obviously stubbed without crashing.
        dialogs.info(
            self, "Coming soon",
            "Linking spots opens a campaign picker — that dialog lands "
            "in a follow-up session. For now, linked-spot edits made "
            "elsewhere persist via jingle_linked_spots; this card just "
            "shows them.")

    def _on_linked_spot_remove(self):
        if not self._linked_spots:
            return
        before = list(self._linked_spots.linked_campaign_ids())
        self._linked_spots.remove_highlighted()
        after = self._linked_spots.linked_campaign_ids()
        if before == after:
            dialogs.info(
                self, "No selection",
                "Click a linked-spot row first, then press −.")

    def _on_save(self):
        data = self._collect_values()
        # Required: title
        if not data["name"]:
            dialogs.warning(
                self, "Missing required field",
                "Jingle Title is required.")
            if self._title_input:
                self._title_input.setFocus()
            return
        try:
            if self._mode_edit:
                self._db.update_jingle(int(self._jingle_id), data)
                new_id = int(self._jingle_id)
            else:
                new_id = self._db.add_jingle(data)
        except Exception as exc:
            log.error(f"save failed: {exc}", exc_info=True)
            dialogs.error(
                self, "Save failed",
                f"Could not save jingle:\n\n{exc}")
            return
        # Persist the linked-spots set (no-op if unchanged).
        try:
            if self._linked_spots is not None:
                self._db.set_jingle_linked_spots(
                    int(new_id),
                    self._linked_spots.linked_campaign_ids(),
                )
        except Exception as exc:
            log.error(f"linked-spots save failed: {exc}", exc_info=True)
        log.info(
            f"Jingle saved: id={new_id} "
            f"({'EDIT' if self._mode_edit else 'NEW'}) "
            f"name={data['name']!r} category={data['category']!r}")
        self.jingle_saved.emit(int(new_id))
        self.accept()
