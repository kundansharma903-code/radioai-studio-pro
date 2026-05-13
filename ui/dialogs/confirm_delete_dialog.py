"""
RadioAI Studio Pro — Confirm Delete Dialog

Used by Songs Library when the user clicks ✕ Delete in the sidebar.
Built on BaseDialog so the layout adapts on small screens and the
Cancel / Delete buttons stay reachable.

  HEADER  — red trash icon + "DELETE SONG?" + cannot-be-undone subtitle
  CONTENT — song info card (title / artist / duration / last played / plays)
            + warning text about cascading removal
  FOOTER  — Cancel (secondary) + "Delete Permanently" (red gradient)

Emits delete_confirmed(song_id: int) when the user clicks Delete Permanently.
The caller is responsible for executing the actual DB delete + reload.
"""

import logging
from typing import Optional

from PyQt6.QtCore import Qt, QRectF, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QPen, QFont, QCursor, QPainterPath
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QHBoxLayout, QVBoxLayout,
)

from ui.widgets._tokens import (
    inter, mono, rgba,
    TEXT_PRI, TEXT_SEC, TEXT_MUTED, TEXT_DIM,
    RED, RED_LIGHT, AMBER,
)
from ui.dialogs.base_dialog import BaseDialog

log = logging.getLogger("ConfirmDeleteDialog")


# ════════════════════════════════════════════════════════════════════════════
# Header trash icon
# ════════════════════════════════════════════════════════════════════════════

class _TrashIcon(QWidget):
    """Custom-drawn red trash icon, 36×36, with subtle red halo."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(36, 36)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Halo
        halo = QColor(RED); halo.setAlphaF(0.18)
        p.setBrush(halo); p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(0, 0, 36, 36), 9, 9)

        # Trash body — square 14×16 centred
        p.setPen(QPen(QColor(RED_LIGHT), 1.6))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(11, 13, 14, 16), 2, 2)

        # Lid — line at y=11
        p.drawLine(8, 11, 28, 11)

        # Handle — small bump above the lid
        p.drawLine(15, 8, 21, 8)
        p.drawLine(15, 8, 15, 11)
        p.drawLine(21, 8, 21, 11)

        # Three vertical slits inside the body
        p.setPen(QPen(QColor(RED_LIGHT), 1.0))
        p.drawLine(15, 17, 15, 25)
        p.drawLine(18, 17, 18, 25)
        p.drawLine(21, 17, 21, 25)


# ════════════════════════════════════════════════════════════════════════════
# Song info card (centre of dialog)
# ════════════════════════════════════════════════════════════════════════════

class _SongInfoCard(QFrame):

    def __init__(self, song: dict, parent=None):
        super().__init__(parent)
        self._song = song or {}
        self.setFixedHeight(108)
        self.setStyleSheet(
            f"QFrame {{ background: #0c0e1c; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; "
            f"border-radius: 10px; }}"
        )

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Left red accent bar (3px × full height)
        p.setBrush(QColor(RED)); p.setPen(Qt.PenStyle.NoPen)
        p.drawRect(QRectF(0, 0, 3, self.height()))

        title = self._song.get("title") or "—"
        artist = self._song.get("artist") or "—"
        dur_ms = int(self._song.get("duration_ms") or 0)
        duration = self._fmt_duration(dur_ms)
        category = self._song.get("category") or self._song.get("cat_name") or ""
        last_played = self._song.get("last_played_human") or "Never played"
        play_count = int(self._song.get("play_count") or 0)
        plays = f"{play_count} play{'s' if play_count != 1 else ''} total"

        # Row 1 — Title (Inter Bold 16)
        p.setPen(QColor(TEXT_PRI))
        p.setFont(inter(16, QFont.Weight.Bold))
        p.drawText(20, 14, self.width() - 40, 22,
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._elide(p, title, self.width() - 40))

        # Row 2 — Artist • Duration • Category
        meta = f"{artist}  ·  {duration}"
        if category:
            meta += f"  ·  {category}"
        p.setPen(QColor(TEXT_SEC))
        p.setFont(inter(11))
        p.drawText(20, 38, self.width() - 40, 18,
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._elide(p, meta, self.width() - 40))

        # Row 3 — Last played
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(inter(10, QFont.Weight.Medium))
        p.drawText(20, 62, self.width() - 40, 16,
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   f"Last played: {last_played}")

        # Row 4 — plays badge
        p.setPen(QColor(AMBER))
        p.setFont(mono(10, bold=True))
        p.drawText(20, 82, self.width() - 40, 16,
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   plays)

    @staticmethod
    def _fmt_duration(ms: int) -> str:
        s = int((ms or 0) // 1000)
        return f"{s // 60}:{s % 60:02d}"

    @staticmethod
    def _elide(painter: QPainter, text: str, width: int) -> str:
        fm = painter.fontMetrics()
        return fm.elidedText(text, Qt.TextElideMode.ElideRight, width)


# ════════════════════════════════════════════════════════════════════════════
# Main dialog
# ════════════════════════════════════════════════════════════════════════════

class ConfirmDeleteDialog(BaseDialog):
    """Confirm-delete dialog. Single-song mode renders the rich
    _SongInfoCard with airtime stats; multi-song mode renders a
    compact scrollable list of titles + artist with a count badge.

    Construct with EITHER:
      - song_data=dict     → single-song mode (legacy entry point)
      - song_data_list=list → multi-song mode (N titles)
    Both feed the same _on_confirm path which emits
    delete_confirmed(list[int]). The signal payload is ALWAYS a list,
    even for single-song deletions — consumer iterates either way."""

    delete_confirmed = pyqtSignal(list)   # list[int] of song ids

    HEADER_H = 64
    FOOTER_H = 60

    def __init__(self, song_data: dict = None,
                 song_data_list: list = None,
                 parent=None):
        # Normalize: always work off a list internally. Single-song
        # callers still pass song_data=dict; the dialog detects and
        # renders the rich card for that case.
        if song_data_list:
            self._songs: list = list(song_data_list)
        elif song_data:
            self._songs = [song_data]
        else:
            self._songs = []
        # First entry is treated as the "focus" song for the legacy
        # single-song render.
        self._song = self._songs[0] if self._songs else {}
        # BaseDialog enforces a 640×480 minimum — use that as the target.
        super().__init__(target_size=(640, 480), parent=parent)

    # ── Header ────────────────────────────────────────────────────────────

    def _build_header(self) -> QWidget:
        f = QFrame()
        f.setStyleSheet(
            f"QFrame {{ background: #0d0f1e; "
            f"border-bottom: 1px solid {rgba(RED, 0.20)}; }}"
        )
        h = QHBoxLayout(f)
        h.setContentsMargins(18, 12, 12, 12)
        h.setSpacing(14)

        h.addWidget(_TrashIcon())

        title_box = QWidget(); title_box.setStyleSheet("background: transparent;")
        tv = QVBoxLayout(title_box)
        tv.setContentsMargins(0, 0, 0, 0); tv.setSpacing(2)
        n = len(self._songs)
        title_text = (
            "DELETE SONG?" if n <= 1 else f"DELETE {n} SONGS?")
        title = QLabel(title_text)
        title.setFont(inter(16, QFont.Weight.Black, letter_spacing=0.5))
        title.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        sub = QLabel("This action cannot be undone")
        sub.setFont(inter(10))
        sub.setStyleSheet(f"color: {RED_LIGHT}; background: transparent;")
        tv.addWidget(title); tv.addWidget(sub)
        h.addWidget(title_box)
        h.addStretch()

        x = QPushButton("✕")
        x.setFixedSize(26, 26)
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
        v.setContentsMargins(24, 24, 24, 16)
        v.setSpacing(18)

        n = len(self._songs)
        section_text = (
            "SELECTED SONG" if n <= 1 else f"SELECTED SONGS  ·  {n}")
        sl = QLabel(section_text)
        sl.setFont(inter(9, QFont.Weight.Bold, letter_spacing=1.4))
        sl.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        v.addWidget(sl)

        if n <= 1:
            # Single-song mode — rich info card
            v.addWidget(_SongInfoCard(self._song))
        else:
            # Multi-song mode — scrollable list of titles
            v.addWidget(self._build_multi_list())

        # Warning panel — copy adapts to count
        warn = QFrame()
        warn.setStyleSheet(
            f"QFrame {{ background: {rgba(RED, 0.06)}; "
            f"border: 1px solid {rgba(RED, 0.30)}; "
            f"border-radius: 8px; }}"
        )
        warn_l = QHBoxLayout(warn)
        warn_l.setContentsMargins(14, 10, 14, 10); warn_l.setSpacing(10)

        bullet = QLabel("⚠")
        bullet.setFont(inter(14, QFont.Weight.Bold))
        bullet.setStyleSheet(f"color: {RED_LIGHT}; background: transparent;")
        bullet.setFixedWidth(20)
        warn_l.addWidget(bullet, alignment=Qt.AlignmentFlag.AlignTop)

        subj = "song" if n <= 1 else f"{n} songs"
        warn_text = QLabel(
            f"This will permanently remove the {subj} from your library. "
            f"References in playlists and the daily log will also be removed. "
            f"Past airtime history will be kept (with the song links "
            f"cleared)."
        )
        warn_text.setWordWrap(True)
        warn_text.setFont(inter(11))
        warn_text.setStyleSheet(f"color: {TEXT_SEC}; background: transparent;")
        warn_l.addWidget(warn_text, stretch=1)
        v.addWidget(warn)

        v.addStretch()
        return c

    def _build_multi_list(self) -> QWidget:
        """Compact scrollable list — one row per song with title +
        artist. Caps at the dialog content's available height; long
        selections scroll. Each row 28h, list capped 180h."""
        from PyQt6.QtWidgets import QScrollArea
        wrap = QFrame()
        wrap.setFixedHeight(180)
        wrap.setStyleSheet(
            f"QFrame {{ background: #0c0e1c; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; "
            f"border-radius: 10px; }}"
        )
        wv = QVBoxLayout(wrap)
        wv.setContentsMargins(0, 0, 0, 0); wv.setSpacing(0)

        scroll = QScrollArea(wrap)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollBar:vertical { background: transparent; width: 6px; }"
            f"QScrollBar::handle:vertical {{ background: "
            f"{rgba('#ffffff', 0.18)}; border-radius: 3px; }}"
        )
        content = QFrame()
        content.setStyleSheet("background: transparent;")
        cv = QVBoxLayout(content)
        cv.setContentsMargins(12, 8, 12, 8); cv.setSpacing(2)

        for sng in self._songs:
            row = QFrame()
            row.setFixedHeight(28)
            row.setStyleSheet("background: transparent;")
            rh = QHBoxLayout(row)
            rh.setContentsMargins(8, 0, 8, 0); rh.setSpacing(8)
            # Red bullet
            b = QLabel("•")
            b.setFont(inter(12, QFont.Weight.Bold))
            b.setStyleSheet(
                f"color: {RED_LIGHT}; background: transparent;")
            b.setFixedWidth(14)
            rh.addWidget(b)
            # Title (white) + Artist (muted)
            title = QLabel(sng.get("title") or "—")
            title.setFont(inter(11, QFont.Weight.Bold))
            title.setStyleSheet(
                f"color: {TEXT_PRI}; background: transparent;")
            rh.addWidget(title)
            sep = QLabel(" · ")
            sep.setStyleSheet(
                f"color: {TEXT_MUTED}; background: transparent;")
            rh.addWidget(sep)
            artist = QLabel(sng.get("artist") or "—")
            artist.setFont(inter(11))
            artist.setStyleSheet(
                f"color: {TEXT_SEC}; background: transparent;")
            rh.addWidget(artist)
            rh.addStretch()
            cv.addWidget(row)
        cv.addStretch()
        scroll.setWidget(content)
        wv.addWidget(scroll)
        return wrap

    # ── Footer ────────────────────────────────────────────────────────────

    def _build_footer(self) -> QWidget:
        f = QFrame()
        f.setStyleSheet(
            f"QFrame {{ background: #0d0f1e; "
            f"border-top: 1px solid {rgba('#ffffff', 0.06)}; }}"
        )
        h = QHBoxLayout(f)
        h.setContentsMargins(20, 12, 20, 12); h.setSpacing(10)

        cancel = QPushButton("Cancel")
        cancel.setFixedHeight(36)
        cancel.setMinimumWidth(110)
        cancel.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        cancel.setFont(inter(12, QFont.Weight.Medium))
        cancel.setStyleSheet(
            f"QPushButton {{ background: #1c1f38; color: {TEXT_SEC}; "
            f"border: 1px solid {rgba('#ffffff', 0.08)}; "
            f"border-radius: 8px; padding: 0 18px; }}"
            f"QPushButton:hover {{ background: #252848; color: {TEXT_PRI}; }}"
        )
        cancel.clicked.connect(self.reject)
        h.addWidget(cancel)

        h.addStretch()

        n = len(self._songs)
        delete_label = (
            "✕  Delete Permanently" if n <= 1
            else f"✕  Delete {n} Permanently")
        delete = QPushButton(delete_label)
        delete.setFixedHeight(36)
        delete.setMinimumWidth(180)
        delete.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        delete.setFont(inter(12, QFont.Weight.DemiBold))
        delete.setStyleSheet(
            f"QPushButton {{ background: qlineargradient("
            f"x1:0,y1:0,x2:0,y2:1, stop:0 {RED_LIGHT}, stop:0.5 {RED}, stop:1 #be123c); "
            f"color: white; border: none; border-radius: 8px; padding: 0 22px; }}"
            f"QPushButton:hover {{ background: qlineargradient("
            f"x1:0,y1:0,x2:0,y2:1, stop:0 #fda4af, stop:1 {RED}); }}"
            f"QPushButton:pressed {{ background: #be123c; }}"
        )
        delete.clicked.connect(self._on_confirm)
        h.addWidget(delete)
        return f

    # ── Actions ───────────────────────────────────────────────────────────

    def _on_confirm(self):
        ids: list = []
        for s in self._songs:
            try:
                sid = int(s.get("id") or 0)
            except (TypeError, ValueError):
                sid = 0
            if sid:
                ids.append(sid)
        if not ids:
            log.warning("[DELETE] confirm clicked but no song ids")
            self.reject()
            return
        log.info(f"[DELETE] confirmed for {len(ids)} song id(s): {ids}")
        self.delete_confirmed.emit(ids)
        self.accept()
