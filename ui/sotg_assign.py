"""
RadioAI Studio Pro — Spot on the Go · Assign (Figma 474:3)

Step 2 of Spot on the Go. Operator picks a saved show on the left,
sees that show's link template on the right, and per-link:
  - uploads an audio file (mp3 / wav)
  - sets the sharp HH:MM time
  - picks priority High or Low
  - previews the file locally (▶/■)
  - saves the row

One-shot files: each assignment plays once on its scheduled day,
then leaves a FIRED record. Operator can prep TODAY or TOMORROW from
a toggle in the hero.

Priority order on-air (enforced by Studio when SOTG dispatch ships):
  Spots & Commercials  >  Spot on the Go  >  Songs (Library)

Past-time guard: when scheduled_date is today, sharp_time < current
HH:MM is rejected both client-side (input red + Save disabled) and
server-side (db.upsert_sotg_assignment raises ValueError).

Public signals:
  screen_requested(str) — "control_panel" / "ai_magic" /
                          "spot_on_the_go"
  studio_clicked()      — header Open Studio button
"""

from __future__ import annotations

import logging
import os
from datetime import date as ddate, datetime, timedelta
from typing import Optional

from PyQt6.QtCore import Qt, QRectF, QTimer, pyqtSignal
from core import dialogs
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QLinearGradient, QRadialGradient,
    QFont, QCursor,
)
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QHBoxLayout, QVBoxLayout,
    QLineEdit, QFileDialog, QScrollArea, QMessageBox,
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
from ui.spot_on_the_go_shell import (
    _HeaderLogo, _HeaderOpenStudio, _BreadcrumbLink, _BreadcrumbPill,
    _StatusPill, _PremiumBackdrop, _HeroStatusPill,
)

log = logging.getLogger("SOTGAssign")

WINDOW_W = 1440
WINDOW_H = 900
HEADER_H = 72
STATUS_H = 36


# Status palette: (bg color, text/icon light color, glyph)
STATUS_STYLE = {
    "PENDING":  ("#454d6d", "#8891b8", "●"),
    "READY":    (CYAN,      CYAN_LIGHT, "●"),
    "FIRED":    (GREEN,     GREEN_LIGHT, "✓"),
    "MISSED":   (RED,       "#fb7185",  "✕"),
    "CONFLICT": (AMBER,     AMBER_LIGHT, "⚠"),
}


def _hhmm_now() -> tuple[int, int]:
    now = datetime.now()
    return now.hour, now.minute


def _hhmm_to_minutes(s: str) -> Optional[int]:
    if not s or len(s) != 5 or s[2] != ":":
        return None
    try:
        h, m = int(s[:2]), int(s[3:])
    except ValueError:
        return None
    if not (0 <= h < 24 and 0 <= m < 60):
        return None
    return h * 60 + m


def _basename(path: Optional[str]) -> str:
    if not path:
        return ""
    return os.path.basename(path)


def _format_duration_ms(ms: int) -> str:
    if not ms or ms <= 0:
        return "—"
    s = int(ms) // 1000
    return f"{s // 60}:{s % 60:02d}"


def _spread_times(start_hhmm: str, end_hhmm: str,
                   n: int) -> list[str]:
    """Spread N sharp times evenly across the [start, end] envelope.
    Returns HH:MM strings. Handles overnight wraparound."""
    if n <= 0:
        return []
    sm = _hhmm_to_minutes(start_hhmm)
    em = _hhmm_to_minutes(end_hhmm)
    if sm is None or em is None:
        return [start_hhmm or "00:00"] * n
    if em <= sm:
        em += 24 * 60
    span = em - sm
    if n == 1:
        m = sm
    step = span / n if n > 0 else 0
    out = []
    for i in range(n):
        if n == 1:
            t = sm
        else:
            t = int(sm + i * step)
        t = t % (24 * 60)
        out.append(f"{(t // 60):02d}:{(t % 60):02d}")
    return out


# ════════════════════════════════════════════════════════════════════════════
# Today / Tomorrow date toggle
# ════════════════════════════════════════════════════════════════════════════


class _DateToggle(QFrame):
    """Two-pill date selector. Emits date_changed(iso_date) when the
    operator flips between Today and Tomorrow."""

    date_changed = pyqtSignal(str)   # 'YYYY-MM-DD'

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(240, 30)
        self._is_today = True
        self.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border: 1px solid {rgba('#ffffff', 0.10)}; "
            f"border-radius: 15px; }}"
        )
        self._today_btn = QPushButton("● TODAY", self)
        self._today_btn.setGeometry(4, 4, 116, 22)
        self._today_btn.setFont(
            inter(9, QFont.Weight.Bold, letter_spacing=1.0))
        self._today_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._today_btn.clicked.connect(self._on_today)
        self._tom_btn = QPushButton("TOMORROW", self)
        self._tom_btn.setGeometry(120, 4, 116, 22)
        self._tom_btn.setFont(
            inter(9, QFont.Weight.Bold, letter_spacing=1.0))
        self._tom_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._tom_btn.clicked.connect(self._on_tomorrow)
        self._render()

    def selected_date(self) -> str:
        d = ddate.today() if self._is_today \
            else ddate.today() + timedelta(days=1)
        return d.isoformat()

    def is_today(self) -> bool:
        return self._is_today

    def _on_today(self) -> None:
        if not self._is_today:
            self._is_today = True
            self._render()
            self.date_changed.emit(self.selected_date())

    def _on_tomorrow(self) -> None:
        if self._is_today:
            self._is_today = False
            self._render()
            self.date_changed.emit(self.selected_date())

    def _render(self) -> None:
        on = (f"QPushButton {{ background: {rgba(CYAN, 0.20)}; "
              f"color: {CYAN_LIGHT}; border: 1px solid "
              f"{rgba(CYAN, 0.5)}; border-radius: 11px; }}"
              f"QPushButton:hover {{ background: {rgba(CYAN, 0.30)}; }}")
        off = (f"QPushButton {{ background: transparent; "
               f"color: {TEXT_SEC}; border: none; }}"
               f"QPushButton:hover {{ color: {TEXT_PRI}; }}")
        if self._is_today:
            self._today_btn.setStyleSheet(on)
            self._today_btn.setText("● TODAY")
            self._tom_btn.setStyleSheet(off)
            self._tom_btn.setText("TOMORROW")
        else:
            self._today_btn.setStyleSheet(off)
            self._today_btn.setText("TODAY")
            self._tom_btn.setStyleSheet(on)
            self._tom_btn.setText("● TOMORROW")


# ════════════════════════════════════════════════════════════════════════════
# Status badge widget — used in link rows
# ════════════════════════════════════════════════════════════════════════════


class _StatusBadge(QFrame):
    """Compact pill (100×22) carrying icon + state name."""

    def __init__(self, status: str = "PENDING", parent=None):
        super().__init__(parent)
        self.setFixedSize(100, 22)
        self._status = status
        self._icon = QLabel("", self)
        self._icon.setGeometry(8, 3, 16, 16)
        self._icon.setFont(inter(11, QFont.Weight.Bold))
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._txt = QLabel("", self)
        self._txt.setGeometry(26, 3, 68, 16)
        self._txt.setFont(
            inter(9, QFont.Weight.Bold, letter_spacing=1.0))
        self.set_status(status)

    def set_status(self, status: str) -> None:
        self._status = status
        bg, fg, glyph = STATUS_STYLE.get(
            status, STATUS_STYLE["PENDING"])
        self.setStyleSheet(
            f"QFrame {{ background: {rgba(bg, 0.18)}; "
            f"border: 1px solid {rgba(bg, 0.5)}; "
            f"border-radius: 11px; }}"
        )
        self._icon.setText(glyph)
        self._icon.setStyleSheet(
            f"color: {fg}; background: transparent; border: none;")
        self._txt.setText(status)
        self._txt.setStyleSheet(
            f"color: {fg}; background: transparent; border: none;")


# ════════════════════════════════════════════════════════════════════════════
# Priority toggle — two-segment switch
# ════════════════════════════════════════════════════════════════════════════


class _PriorityToggle(QWidget):
    """⚡ HIGH | ⏱ LOW two-pill toggle. None state = both dimmed."""

    changed = pyqtSignal(str)   # 'High' / 'Low' / ''

    def __init__(self, initial: str = "", parent=None):
        super().__init__(parent)
        self.setFixedSize(128, 22)
        self._value = (initial or "").title()
        self._high_btn = QPushButton("⚡ HIGH", self)
        self._high_btn.setGeometry(0, 0, 60, 22)
        self._high_btn.setFont(
            inter(9, QFont.Weight.Bold, letter_spacing=0.5))
        self._high_btn.setCursor(
            QCursor(Qt.CursorShape.PointingHandCursor))
        self._high_btn.clicked.connect(lambda _=False: self.set_value("High"))
        self._low_btn = QPushButton("⏱ LOW", self)
        self._low_btn.setGeometry(64, 0, 60, 22)
        self._low_btn.setFont(
            inter(9, QFont.Weight.Bold, letter_spacing=0.5))
        self._low_btn.setCursor(
            QCursor(Qt.CursorShape.PointingHandCursor))
        self._low_btn.clicked.connect(lambda _=False: self.set_value("Low"))
        self._render()

    def value(self) -> str:
        return self._value

    def set_value(self, v: str) -> None:
        v = (v or "").title()
        if v not in ("High", "Low", ""):
            return
        if v != self._value:
            self._value = v
            self._render()
            self.changed.emit(v)

    def set_enabled(self, enabled: bool) -> None:
        self._high_btn.setEnabled(enabled)
        self._low_btn.setEnabled(enabled)
        self._render()

    def _render(self) -> None:
        def style(on: bool, accent: str, accent_light: str) -> str:
            if on:
                return (f"QPushButton {{ background: "
                        f"{rgba(accent, 0.30)}; "
                        f"color: {accent_light}; border: 1px solid "
                        f"{rgba(accent, 0.6)}; border-radius: 11px; }}"
                        f"QPushButton:hover {{ background: "
                        f"{rgba(accent, 0.40)}; }}"
                        f"QPushButton:disabled {{ color: "
                        f"{TEXT_MUTED}; }}")
            return (f"QPushButton {{ background: "
                    f"{rgba('#ffffff', 0.04)}; color: {TEXT_SEC}; "
                    f"border: 1px solid {rgba('#454d6d', 0.6)}; "
                    f"border-radius: 11px; }}"
                    f"QPushButton:hover {{ background: "
                    f"{rgba('#ffffff', 0.08)}; color: {TEXT_PRI}; }}"
                    f"QPushButton:disabled {{ color: "
                    f"{TEXT_MUTED}; }}")
        self._high_btn.setStyleSheet(
            style(self._value == "High", GREEN, GREEN_LIGHT))
        self._low_btn.setStyleSheet(
            style(self._value == "Low", CYAN, CYAN_LIGHT))


# ════════════════════════════════════════════════════════════════════════════
# Sharp time input — HH:MM with past-time validation
# ════════════════════════════════════════════════════════════════════════════


class _SharpTimeInput(QLineEdit):
    """24h HH:MM input. Tracks "is past" state externally and paints
    red when invalid. Past-time rejection is enforced when the host
    calls set_validate_against_today(True)."""

    invalid_changed = pyqtSignal(bool)   # True if currently past

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setInputMask("00:00;_")
        self.setFont(mono(12, bold=True))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._validate_today = False
        self._is_invalid = False
        self.textChanged.connect(lambda _t: self._revalidate())
        self._apply_style()

    def hhmm(self) -> str:
        return (self.text() or "").strip()

    def is_invalid_past(self) -> bool:
        return self._is_invalid

    def set_validate_against_today(self, on: bool) -> None:
        self._validate_today = bool(on)
        self._revalidate()

    def _revalidate(self) -> None:
        was_invalid = self._is_invalid
        self._is_invalid = False
        if self._validate_today:
            mins = _hhmm_to_minutes(self.hhmm())
            if mins is not None:
                h, m = _hhmm_now()
                now_m = h * 60 + m
                if mins < now_m:
                    self._is_invalid = True
        self._apply_style()
        if self._is_invalid != was_invalid:
            self.invalid_changed.emit(self._is_invalid)

    def _apply_style(self) -> None:
        border = (rgba(RED, 0.6) if self._is_invalid
                  else rgba('#ffffff', 0.12))
        focus_border = (rgba(RED, 0.8) if self._is_invalid
                         else rgba(CYAN, 0.5))
        self.setStyleSheet(
            f"QLineEdit {{ background: rgba(7,8,18,0.7); "
            f"color: {RED if self._is_invalid else TEXT_PRI}; "
            f"border: 1px solid {border}; border-radius: 8px; "
            f"padding: 0 6px; }}"
            f"QLineEdit:focus {{ border-color: {focus_border}; }}"
            f"QLineEdit:disabled {{ color: {TEXT_MUTED}; }}"
        )


# ════════════════════════════════════════════════════════════════════════════
# File button — uniform pill: '📎 Choose File…' or '📎 filename · dur'
# ════════════════════════════════════════════════════════════════════════════


class _FileButton(QPushButton):
    """Single button that toggles label/visual based on whether a file
    is currently bound. Click always opens the file picker — empty or
    not — so the operator can replace without a separate widget."""

    file_chosen = pyqtSignal(str)   # absolute path of new file

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(32)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFont(inter(11, QFont.Weight.Bold))
        self._file_path: Optional[str] = None
        self._duration_ms = 0
        self._render_empty()
        self.clicked.connect(self._on_click)

    def file_path(self) -> Optional[str]:
        return self._file_path

    def set_file(self, path: Optional[str],
                  duration_ms: int = 0) -> None:
        self._file_path = path or None
        self._duration_ms = int(duration_ms or 0)
        if self._file_path:
            self._render_filled()
        else:
            self._render_empty()

    def set_read_only(self, ro: bool) -> None:
        self.setEnabled(not ro)
        if ro and self._file_path:
            # Locked + has file → muted display
            self.setStyleSheet(
                f"QPushButton {{ background: {rgba('#ffffff', 0.04)}; "
                f"color: {TEXT_MUTED}; border: 1px solid "
                f"{rgba('#454d6d', 0.6)}; border-radius: 8px; "
                f"padding: 0 8px; text-align: left; }}"
            )

    def _render_empty(self) -> None:
        self.setText("📎  Choose File…")
        self.setStyleSheet(
            f"QPushButton {{ background: {rgba(CYAN, 0.12)}; "
            f"color: {CYAN_LIGHT}; border: 1px solid "
            f"{rgba(CYAN, 0.4)}; border-radius: 8px; "
            f"padding: 0 8px; }}"
            f"QPushButton:hover {{ background: {rgba(CYAN, 0.20)}; }}"
            f"QPushButton:disabled {{ color: {TEXT_MUTED}; }}"
        )

    def _render_filled(self) -> None:
        name = _basename(self._file_path)
        if len(name) > 26:
            name = name[:25] + "…"
        dur = _format_duration_ms(self._duration_ms)
        self.setText(f"📎  {name}  ·  {dur}")
        self.setStyleSheet(
            f"QPushButton {{ background: rgba(7,8,18,0.7); "
            f"color: {TEXT_PRI}; border: 1px solid "
            f"{rgba(CYAN, 0.30)}; border-radius: 8px; "
            f"padding: 0 8px; text-align: left; }}"
            f"QPushButton:hover {{ border-color: {rgba(CYAN, 0.6)}; "
            f"background: rgba(7,8,18,0.85); }}"
            f"QPushButton:disabled {{ color: {TEXT_MUTED}; "
            f"border-color: {rgba('#454d6d', 0.6)}; }}"
        )

    def _on_click(self) -> None:
        start_dir = (os.path.dirname(self._file_path)
                     if self._file_path else "")
        path, _ = QFileDialog.getOpenFileName(
            self, "Pick audio for this link",
            start_dir,
            "Audio (*.mp3 *.wav *.ogg *.flac *.m4a);;All files (*)")
        if path:
            self.file_chosen.emit(path)


# ════════════════════════════════════════════════════════════════════════════
# Preview button — ▶/■ for local audio playback
# ════════════════════════════════════════════════════════════════════════════


class _PreviewButton(QPushButton):
    """Local-only audio preview. Click ▶ to load + play via the shared
    AudioEngine, click ■ to stop. NOT on-air — operator can audition
    a link's file before saving without anything reaching the
    broadcast. Falls back to a disabled state when no engine is
    wired (tests) or no file is bound."""

    def __init__(self, engine=None, parent=None):
        super().__init__("▶", parent)
        self.setFixedSize(32, 32)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFont(inter(13, QFont.Weight.Bold))
        self._engine = engine
        self._file_path: Optional[str] = None
        self._channel_id: Optional[int] = None
        self._is_playing = False
        self._apply_idle()
        self.clicked.connect(self._on_click)

    def set_file(self, path: Optional[str]) -> None:
        self._file_path = path or None
        # If we were previewing a different file, stop the previous.
        if self._is_playing:
            self._stop()
        if self._file_path:
            self.setEnabled(True)
            self._apply_idle()
        else:
            self.setEnabled(False)
            self._apply_dim()

    def _apply_idle(self) -> None:
        self.setText("▶")
        self.setStyleSheet(
            f"QPushButton {{ background: {rgba(CYAN, 0.15)}; "
            f"color: {CYAN_LIGHT}; border: 1px solid "
            f"{rgba(CYAN, 0.5)}; border-radius: 8px; }}"
            f"QPushButton:hover {{ background: {rgba(CYAN, 0.25)}; }}"
            f"QPushButton:disabled {{ color: {TEXT_MUTED}; "
            f"background: {rgba('#ffffff', 0.04)}; "
            f"border-color: {rgba('#454d6d', 0.6)}; }}"
        )

    def _apply_dim(self) -> None:
        self.setText("▶")
        self.setStyleSheet(
            f"QPushButton {{ background: {rgba('#ffffff', 0.04)}; "
            f"color: {TEXT_MUTED}; border: 1px solid "
            f"{rgba('#454d6d', 0.6)}; border-radius: 8px; }}"
        )

    def _apply_playing(self) -> None:
        self.setText("■")
        self.setStyleSheet(
            f"QPushButton {{ background: {rgba(RED, 0.18)}; "
            f"color: #fb7185; border: 1px solid "
            f"{rgba(RED, 0.5)}; border-radius: 8px; }}"
            f"QPushButton:hover {{ background: {rgba(RED, 0.28)}; }}"
        )

    def _on_click(self) -> None:
        if not self._file_path or self._engine is None:
            return
        if self._is_playing:
            self._stop()
        else:
            self._play()

    def _play(self) -> None:
        try:
            cid = self._engine.load_file(self._file_path)
            self._engine.set_volume(cid, 80)
            self._engine.play(cid)
        except Exception as exc:
            log.warning(f"preview play failed: {exc}")
            return
        self._channel_id = cid
        self._is_playing = True
        self._apply_playing()
        # Connect once to stop self when the file ends naturally.
        try:
            self._engine.playback_ended.connect(self._on_engine_eos)
        except Exception:
            pass

    def _stop(self) -> None:
        cid = self._channel_id
        self._channel_id = None
        self._is_playing = False
        self._apply_idle()
        if cid is not None and self._engine is not None:
            try:
                self._engine.cleanup(cid)
            except Exception as exc:
                log.debug(f"preview stop cleanup: {exc}")

    def _on_engine_eos(self, channel_id: int) -> None:
        if (self._is_playing and self._channel_id is not None
                and int(channel_id) == int(self._channel_id)):
            self._channel_id = None
            self._is_playing = False
            self._apply_idle()


# ════════════════════════════════════════════════════════════════════════════
# Link row — full row composed of all the per-row widgets
# ════════════════════════════════════════════════════════════════════════════


class _LinkRow(QFrame):
    """One row inside the links table on the right panel. Self-contained
    state: knows its link_id, its assignment (or None), and the
    selected scheduled_date. Emits save_requested when the operator
    clicks the row's Save / Update button."""

    save_requested = pyqtSignal(int)   # link_id

    ROW_W = 928
    ROW_H = 48

    def __init__(self, link: dict, assignment: Optional[dict],
                  scheduled_date: str, engine=None, parent=None):
        super().__init__(parent)
        self._link = link
        self._link_id = int(link.get("link_id") or link.get("id") or 0)
        self._scheduled_date = scheduled_date
        self._assignment = assignment or {}
        self._engine = engine
        self.setFixedSize(self.ROW_W, self.ROW_H)
        self.setStyleSheet(
            f"QFrame {{ background: transparent; border: none; }}")

        # Status string drives the row's lock + accent
        self._status = (self._assignment.get("status")
                         or "PENDING")
        if not assignment or not assignment.get("sharp_time"):
            self._status = "PENDING"

        # Index
        idx_lbl = QLabel(str(link.get("link_order") or 0), self)
        idx_lbl.setGeometry(8, 14, 30, 18)
        idx_lbl.setFont(mono(12, bold=True))
        idx_lbl.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent;")
        # Link name
        name_lbl = QLabel(link.get("link_name") or f"Link {idx_lbl.text()}",
                          self)
        name_lbl.setGeometry(38, 12, 140, 18)
        name_lbl.setFont(inter(12, QFont.Weight.Bold))
        name_lbl.setStyleSheet(
            f"color: {TEXT_PRI}; background: transparent;")

        # File button
        self._file_btn = _FileButton(self)
        self._file_btn.setGeometry(184, 8, 220, 32)
        self._file_btn.set_file(self._assignment.get("file_path"),
                                  self._assignment.get("file_duration_ms") or 0)
        self._file_btn.file_chosen.connect(self._on_file_chosen)

        # Duration
        self._dur_lbl = QLabel(
            _format_duration_ms(self._assignment.get("file_duration_ms") or 0),
            self)
        self._dur_lbl.setGeometry(410, 14, 54, 18)
        self._dur_lbl.setFont(mono(11, bold=True))
        self._dur_lbl.setStyleSheet(
            f"color: {TEXT_SEC if self._assignment.get('file_path') else TEXT_MUTED}; "
            f"background: transparent;")

        # Sharp time
        self._time_in = _SharpTimeInput(self)
        self._time_in.setGeometry(470, 8, 74, 32)
        if self._assignment.get("sharp_time"):
            self._time_in.setText(self._assignment["sharp_time"])
        self._time_in.invalid_changed.connect(
            lambda _b: self._refresh_save_button())

        # Priority toggle
        self._prio = _PriorityToggle(
            self._assignment.get("priority") or "", self)
        self._prio.setGeometry(550, 13, 128, 22)
        self._prio.changed.connect(
            lambda _v: self._refresh_save_button())

        # Preview button
        self._preview = _PreviewButton(engine=engine, parent=self)
        self._preview.setGeometry(684, 8, 32, 32)
        self._preview.set_file(self._assignment.get("file_path"))

        # Status badge
        self._badge = _StatusBadge(self._status, self)
        self._badge.setGeometry(722, 13, 100, 22)

        # Save / Update button
        self._save_btn = QPushButton("Save", self)
        self._save_btn.setGeometry(832, 8, 84, 32)
        self._save_btn.setCursor(
            QCursor(Qt.CursorShape.PointingHandCursor))
        self._save_btn.setFont(
            inter(11, QFont.Weight.Bold, letter_spacing=0.4))
        self._save_btn.clicked.connect(
            lambda _=False: self.save_requested.emit(self._link_id))

        # Past-time validation enable depends on the date.
        self.set_scheduled_date(scheduled_date)

        # Lock fully if FIRED/MISSED — past history.
        self._apply_lock_state()
        self._refresh_save_button()

    def _on_file_chosen(self, path: str) -> None:
        # Probe the duration once via pybass3 if available; otherwise
        # leave 0 so the audio engine fills it on first play.
        dur_ms = 0
        try:
            from pybass3 import BassStream, BassChannel
            handle = BassStream.CreateFile(
                False, path.encode("utf-8"), 0, 0, 0x20000)
            if handle:
                dur_s = BassChannel.GetLengthSeconds(handle)
                dur_ms = int((dur_s or 0) * 1000)
                from pybass3 import bass_module as _bm
                try:
                    BassStream.Free(handle)
                except Exception:
                    pass
        except Exception:
            dur_ms = 0
        self._file_btn.set_file(path, dur_ms)
        self._preview.set_file(path)
        self._dur_lbl.setText(_format_duration_ms(dur_ms))
        self._dur_lbl.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent;")
        self._refresh_save_button()

    def set_scheduled_date(self, scheduled_date: str) -> None:
        self._scheduled_date = scheduled_date
        is_today = (scheduled_date == ddate.today().isoformat())
        self._time_in.set_validate_against_today(is_today)
        self._refresh_save_button()

    def _apply_lock_state(self) -> None:
        # FIRED / MISSED rows are full read-only.
        locked = self._status in ("FIRED", "MISSED")
        self._file_btn.set_read_only(locked)
        self._time_in.setEnabled(not locked)
        self._prio.set_enabled(not locked)
        if locked:
            self._save_btn.setText("—")
            self._save_btn.setEnabled(False)
            self._save_btn.setStyleSheet(
                f"QPushButton {{ background: "
                f"{rgba('#ffffff', 0.02)}; color: {TEXT_DIM}; "
                f"border: 1px solid {rgba('#252840', 0.6)}; "
                f"border-radius: 8px; }}"
            )

    def _refresh_save_button(self) -> None:
        if self._status in ("FIRED", "MISSED"):
            return  # locked — handled in _apply_lock_state
        # Eligible to save if all required fields are present + sharp
        # time isn't invalid past.
        has_file = bool(self._file_btn.file_path())
        has_time = (_hhmm_to_minutes(self._time_in.hhmm()) is not None
                    and not self._time_in.is_invalid_past())
        has_prio = self._prio.value() in ("High", "Low")
        eligible = has_file and has_time and has_prio
        # Label: Save when fresh, Update when an assignment id exists.
        already = bool(self._assignment.get("assignment_id"))
        self._save_btn.setText("Update" if already else "Save")
        if eligible:
            self._save_btn.setEnabled(True)
            self._save_btn.setStyleSheet(
                f"QPushButton {{ background: qlineargradient("
                f"x1:0,y1:0,x2:1,y2:0, stop:0 {CYAN_LIGHT}, "
                f"stop:1 {CYAN}); color: {BG_BASE}; "
                f"border: none; border-radius: 8px; }}"
                f"QPushButton:hover {{ background: {CYAN_LIGHT}; }}"
            )
        else:
            self._save_btn.setEnabled(False)
            self._save_btn.setStyleSheet(
                f"QPushButton {{ background: {rgba('#ffffff', 0.04)}; "
                f"color: {TEXT_MUTED}; border: 1px solid "
                f"{rgba('#454d6d', 0.6)}; border-radius: 8px; }}"
            )

    def paintEvent(self, e):
        super().paintEvent(e)
        # Status-color left accent stripe
        bg, _fg, _g = STATUS_STYLE.get(
            self._status, STATUS_STYLE["PENDING"])
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(QRectF(0, 8, 3, 32), QColor(bg))
        p.end()

    # ── Public — used by host on Save ──────────────────────────────────

    def current_form(self) -> dict:
        """Snapshot for the host to persist via DB."""
        return {
            "link_id":          self._link_id,
            "file_path":        self._file_btn.file_path(),
            "file_name":        _basename(self._file_btn.file_path()),
            "file_duration_ms": self._file_btn._duration_ms,
            "sharp_time":       self._time_in.hhmm(),
            "priority":         self._prio.value(),
        }

    def link_id(self) -> int:
        return self._link_id


# ════════════════════════════════════════════════════════════════════════════
# Show card — left panel
# ════════════════════════════════════════════════════════════════════════════


class _ShowCard(QFrame):
    """Saved-show card in the left panel. Clickable to select. Carries
    a per-date counts dict so it can paint X/Y ready badge + the
    mini fired/conflict/missed counters."""

    clicked = pyqtSignal(int)   # show_id

    def __init__(self, show: dict, counts: dict, selected: bool,
                  parent=None):
        super().__init__(parent)
        self._show_id = int(show.get("id") or 0)
        self._show = show
        self._counts = counts
        self._selected = selected
        self.setFixedSize(308, 100)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._build()

    def _build(self) -> None:
        color = self._show.get("color") or CYAN
        bg = (rgba(CYAN, 0.10) if self._selected
              else "rgba(7,8,18,0.7)")
        border = (rgba(CYAN, 0.6) if self._selected
                  else rgba('#ffffff', 0.10))
        sw = 2 if self._selected else 1
        self.setStyleSheet(
            f"QFrame {{ background: {bg}; "
            f"border: {sw}px solid {border}; border-radius: 10px; }}"
        )
        # Color chip — paint via paintEvent for a clean shape

        # Show name
        nm = QLabel(self._show.get("show_name") or "—", self)
        nm.setGeometry(28, 10, 200, 20)
        nm.setFont(inter(13, QFont.Weight.Bold))
        nm.setStyleSheet(
            f"color: {TEXT_PRI}; background: transparent; "
            f"border: none;")
        # RJ + days
        rj = QLabel(
            f"{self._show.get('rj_name') or '—'}  ·  "
            f"{self._show.get('days') or 'Daily'}", self)
        rj.setGeometry(28, 30, 240, 14)
        rj.setFont(inter(10, QFont.Weight.Medium))
        rj.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent; "
            f"border: none;")
        # Time slot (mono cyan)
        ts = (f"{self._show.get('time_start') or '—'} – "
              f"{self._show.get('time_end') or '—'}")
        time_lbl = QLabel(ts, self)
        time_lbl.setGeometry(8, 50, 200, 16)
        time_lbl.setFont(mono(11, bold=True))
        time_lbl.setStyleSheet(
            f"color: {CYAN}; background: transparent; "
            f"border: none;")
        # Ready badge (X/Y)
        total = int(self._counts.get("total") or 0)
        ready_n = (int(self._counts.get("ready") or 0)
                    + int(self._counts.get("fired") or 0))
        ready_t = f"{ready_n}/{total} ready"
        ready_w = 78
        rx = self.width() - 16 - ready_w
        ready_pill = QFrame(self)
        ready_pill.setGeometry(rx, 50, ready_w, 18)
        ready_pill.setStyleSheet(
            f"QFrame {{ background: "
            f"{rgba(CYAN if self._selected else '#8891b8', 0.18)}; "
            f"border: 1px solid "
            f"{rgba(CYAN if self._selected else '#8891b8', 0.4)}; "
            f"border-radius: 9px; }}"
        )
        rh = QHBoxLayout(ready_pill)
        rh.setContentsMargins(0, 0, 0, 0); rh.setSpacing(0)
        r_lbl = QLabel(ready_t, ready_pill)
        r_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        r_lbl.setFont(inter(9, QFont.Weight.Bold))
        r_lbl.setStyleSheet(
            f"color: {CYAN_LIGHT if self._selected else '#cbd5ff'}; "
            f"background: transparent; border: none;")
        rh.addWidget(r_lbl)

        # Mini status icons row
        offsets_x = 8
        fired = int(self._counts.get("fired") or 0)
        if fired > 0:
            self._mini_icon(offsets_x, 76, f"✓ {fired} fired",
                              GREEN_LIGHT)
            offsets_x += 88
        conf = int(self._counts.get("conflict") or 0)
        if conf > 0:
            self._mini_icon(offsets_x, 76, f"⚠ {conf} conflict",
                              AMBER_LIGHT)
            offsets_x += 92
        missed = int(self._counts.get("missed") or 0)
        if missed > 0:
            self._mini_icon(offsets_x, 76, f"✕ {missed} missed",
                              "#fb7185")

    def _mini_icon(self, x: int, y: int, txt: str,
                    color: str) -> None:
        lbl = QLabel(txt, self)
        lbl.setGeometry(x, y, 100, 14)
        lbl.setFont(inter(9, QFont.Weight.Bold))
        lbl.setStyleSheet(
            f"color: {color}; background: transparent; "
            f"border: none;")

    def paintEvent(self, e):
        super().paintEvent(e)
        # Color chip on the left
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor(self._show.get("color") or CYAN))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(8, 14, 14, 14), 4, 4)
        p.end()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._show_id)
        super().mousePressEvent(e)


# ════════════════════════════════════════════════════════════════════════════
# Public screen
# ════════════════════════════════════════════════════════════════════════════


class SOTGAssign(QWidget):
    """Assign screen (Figma 474:3) — Step 2 of Spot on the Go."""

    screen_requested = pyqtSignal(str)
    studio_clicked   = pyqtSignal()

    def __init__(self, db, engine=None, parent=None):
        super().__init__(parent)
        self._db = db
        self._engine = engine
        self._selected_show_id: Optional[int] = None
        self._scheduled_date: str = ddate.today().isoformat()
        # Tracked widget lists — refresh paths iterate ONLY these so
        # we never touch scroll-area internals or backdrop layers.
        self._show_cards: list[_ShowCard] = []
        self._row_widgets: list[_LinkRow] = []
        self.setFixedSize(WINDOW_W, WINDOW_H)
        self.setStyleSheet(f"QWidget {{ background: {BG_BASE}; }}")

        self._backdrop = _PremiumBackdrop(self)
        self._backdrop.setGeometry(0, 0, WINDOW_W, WINDOW_H)

        self._build_header()
        self._build_hero()
        self._build_left_panel()
        self._build_right_panel()
        self._build_status_bar()

        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._tick_clock)
        self._clock_timer.start()
        self._tick_clock()

        # Initial paint
        self._refresh_shows_list()
        self._refresh_right_panel()
        self._refresh_hero_counters()

        log.info("SOTGAssign ready (Figma 474:3)")

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
        l2 = QLabel("STUDIO PRO", h)
        l2.setGeometry(64, 34, 120, 12)
        l2.setFont(inter(8, QFont.Weight.Bold, letter_spacing=1.2))
        l2.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

        cp = _BreadcrumbLink("Control Panel", h)
        cp.setGeometry(176, 22, 100, 22)
        cp.clicked.connect(
            lambda: self.screen_requested.emit("control_panel"))
        sep1 = QLabel("|", h); sep1.setGeometry(272, 22, 8, 22)
        sep1.setFont(inter(11))
        sep1.setStyleSheet(f"color: {TEXT_DIM}; background: transparent;")
        am = _BreadcrumbLink("AI Magic", h)
        am.setGeometry(284, 22, 80, 22)
        am.clicked.connect(
            lambda: self.screen_requested.emit("ai_magic"))
        sep2 = QLabel("|", h); sep2.setGeometry(360, 22, 8, 22)
        sep2.setFont(inter(11))
        sep2.setStyleSheet(f"color: {TEXT_DIM}; background: transparent;")
        sotg = _BreadcrumbLink("Spot on the Go", h)
        sotg.setGeometry(372, 22, 110, 22)
        sotg.clicked.connect(
            lambda: self.screen_requested.emit("spot_on_the_go"))
        sep3 = QLabel("|", h); sep3.setGeometry(478, 22, 8, 22)
        sep3.setFont(inter(11))
        sep3.setStyleSheet(f"color: {TEXT_DIM}; background: transparent;")
        pill = _BreadcrumbPill("Assign", h)
        pill.move(490, 20)
        pill.setFixedSize(80, 32)

        title = QLabel("Assign", h)
        title.setGeometry(590, 12, 240, 24)
        title.setFont(inter(20, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        sub = QLabel(
            "Step 2 of Spot on the Go — upload files and set sharp times",
            h)
        sub.setGeometry(590, 38, 500, 14)
        sub.setFont(inter(10))
        sub.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

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

    # ── Hero ─────────────────────────────────────────────────────────

    def _build_hero(self) -> None:
        sigil = QLabel("✦", self)
        sigil.setGeometry(60, 88, 28, 36)
        sigil.setFont(inter(28, QFont.Weight.Bold))
        sigil.setStyleSheet(
            f"color: {CYAN_LIGHT}; background: transparent; "
            f"border: none;")
        title = QLabel("ASSIGN", self)
        title.setGeometry(96, 88, 600, 36)
        title.setFont(inter(28, QFont.Weight.Black, letter_spacing=-0.4))
        title.setStyleSheet(
            f"color: {TEXT_PRI}; background: transparent; border: none;")
        sub = QLabel(
            "Upload audio per link, pin sharp HH:MM, and pick "
            "priority. Files play once — refreshed daily.", self)
        sub.setGeometry(60, 128, 1000, 16)
        sub.setFont(inter(12, QFont.Weight.Medium))
        sub.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent; border: none;")

        # 4 counter pills — live, refreshed on every state change.
        self._pill_queued = _HeroStatusPill(
            "0 LINKS QUEUED", CYAN, CYAN_LIGHT, self)
        self._pill_queued.move(60, 156)
        self._pill_queued_label = self._capture_pill_label(self._pill_queued)
        self._pill_fired = _HeroStatusPill(
            "0 FIRED", GREEN, GREEN_LIGHT, self)
        self._pill_fired.move(60 + self._pill_queued.width() + 10, 156)
        self._pill_fired_label = self._capture_pill_label(self._pill_fired)
        self._pill_conflict = _HeroStatusPill(
            "0 CONFLICT", AMBER, AMBER_LIGHT, self)
        self._pill_conflict.move(
            self._pill_fired.x() + self._pill_fired.width() + 10, 156)
        self._pill_conflict_label = self._capture_pill_label(self._pill_conflict)
        self._pill_missed = _HeroStatusPill(
            "0 MISSED", RED, "#fb7185", self)
        self._pill_missed.move(
            self._pill_conflict.x() + self._pill_conflict.width() + 10, 156)
        self._pill_missed_label = self._capture_pill_label(self._pill_missed)

        # Today / Tomorrow toggle (right side)
        self._date_toggle = _DateToggle(self)
        self._date_toggle.move(1140, 154)
        self._date_toggle.date_changed.connect(self._on_date_changed)
        # Date label below
        self._date_label = QLabel(self)
        self._date_label.setGeometry(1140, 188, 240, 14)
        self._date_label.setFont(mono(10, bold=True))
        self._date_label.setStyleSheet(
            f"color: #cbd5ff; background: transparent; border: none;")
        self._date_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._refresh_date_label()

    @staticmethod
    def _capture_pill_label(pill) -> QLabel:
        for lbl in pill.findChildren(QLabel):
            if lbl.text() != "●":
                return lbl
        labels = pill.findChildren(QLabel)
        return labels[-1] if labels else QLabel(pill)

    def _refresh_date_label(self) -> None:
        try:
            d = datetime.strptime(
                self._scheduled_date, "%Y-%m-%d").date()
            self._date_label.setText(d.strftime("%a, %d %b %Y"))
        except Exception:
            self._date_label.setText(self._scheduled_date)

    # ── Left panel ────────────────────────────────────────────────────

    LX = 60; LY = 218; LW = 340; LH = 624

    def _build_left_panel(self) -> None:
        card = QFrame(self)
        card.setGeometry(self.LX, self.LY, self.LW, self.LH)
        card.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border: 1px solid {rgba('#ffffff', 0.08)}; "
            f"border-radius: 14px; }}"
        )
        self._left_card = card

        self._left_cap = QLabel("SAVED SHOWS  ·  0 TOTAL", card)
        self._left_cap.setGeometry(20, 16, 280, 14)
        self._left_cap.setFont(
            inter(10, QFont.Weight.Bold, letter_spacing=1.4))
        self._left_cap.setStyleSheet(
            f"color: {CYAN_LIGHT}; background: transparent; "
            f"border: none;")

        help_lbl = QLabel("Pick a show to assign files.", card)
        help_lbl.setGeometry(20, 34, 280, 12)
        help_lbl.setFont(inter(10))
        help_lbl.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; "
            f"border: none;")

        # Scroll area for the show cards (can grow beyond visible)
        self._left_scroll = QScrollArea(card)
        self._left_scroll.setGeometry(0, 96, self.LW, self.LH - 96)
        self._left_scroll.setWidgetResizable(True)
        self._left_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._left_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._left_scroll.setStyleSheet(
            f"QScrollArea {{ background: transparent; border: none; }}"
            f"QScrollBar:vertical {{ background: transparent; "
            f"width: 6px; margin: 4px 2px; }}"
            f"QScrollBar::handle:vertical {{ background: "
            f"{rgba('#252840', 0.8)}; border-radius: 3px; "
            f"min-height: 32px; }}"
            f"QScrollBar::add-line, QScrollBar::sub-line {{ "
            f"height: 0; width: 0; }}"
        )
        self._left_inner = QWidget()
        self._left_inner.setStyleSheet(
            "QWidget { background: transparent; }")
        self._left_scroll.setWidget(self._left_inner)

    def _refresh_shows_list(self) -> None:
        # Tear down ONLY tracked show cards. Iterating
        # _left_inner.children() instead would touch scroll-area
        # internals (viewport, scrollbars) and corrupt the panel.
        for c in list(self._show_cards):
            try:
                c.setParent(None)
                c.deleteLater()
            except Exception:
                pass
        self._show_cards = []

        try:
            shows = list(self._db.get_sotg_shows())
        except Exception as exc:
            log.warning(f"get_sotg_shows failed: {exc}")
            shows = []
        try:
            counts = self._db.get_sotg_assignment_counts_for_date(
                self._scheduled_date)
        except Exception as exc:
            log.warning(f"counts fetch failed: {exc}")
            counts = {}

        self._left_cap.setText(
            f"SAVED SHOWS  ·  {len(shows)} TOTAL")

        # If nothing selected yet but shows exist, pick the first.
        # Set state here (NOT via recursive _refresh_shows_list call)
        # so the layout step below runs once with the right selection.
        if self._selected_show_id is None and shows:
            self._selected_show_id = int(shows[0]["id"])

        # Lay out cards stacked vertically. Explicit .show() is
        # required because Qt does NOT auto-show widgets that get
        # parented to an already-visible container — this is what
        # caused the disappear-on-refresh bug.
        y = 0
        for s in shows:
            sid = int(s.get("id") or 0)
            c = _ShowCard(
                s,
                counts.get(sid) or {"total": int(s.get("link_count") or 0)},
                selected=(sid == self._selected_show_id),
                parent=self._left_inner,
            )
            c.move(16, y)
            c.clicked.connect(self._on_show_clicked)
            c.show()
            self._show_cards.append(c)
            y += 108

        self._left_inner.setFixedSize(self.LW, max(y, 1))

    def _on_show_clicked(self, show_id: int) -> None:
        if show_id == self._selected_show_id:
            return
        self._selected_show_id = int(show_id)
        self._refresh_shows_list()    # re-paint selection ring
        self._refresh_right_panel()

    def _on_date_changed(self, iso_date: str) -> None:
        self._scheduled_date = iso_date
        self._refresh_date_label()
        # Counters are date-scoped — refresh both panels.
        self._refresh_shows_list()
        self._refresh_right_panel()
        self._refresh_hero_counters()

    # ── Right panel ───────────────────────────────────────────────────

    RX = 420; RY = 218; RW = 960; RH = 624

    def _build_right_panel(self) -> None:
        card = QFrame(self)
        card.setGeometry(self.RX, self.RY, self.RW, self.RH)
        card.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border: 1px solid {rgba('#ffffff', 0.08)}; "
            f"border-radius: 14px; }}"
        )
        # Left accent stripe
        stripe = QFrame(card)
        stripe.setGeometry(0, 0, 4, self.RH)
        stripe.setStyleSheet(
            f"QFrame {{ background: {CYAN}; border: none; "
            f"border-top-left-radius: 14px; "
            f"border-bottom-left-radius: 14px; }}")

        # Header — show summary
        self._rh_chip = QLabel("", card)
        self._rh_chip.setGeometry(20, 18, 22, 22)
        self._rh_chip.setStyleSheet(
            f"QLabel {{ background: {CYAN}; border-radius: 6px; }}")

        self._rh_name = QLabel("—", card)
        self._rh_name.setGeometry(50, 14, 400, 24)
        self._rh_name.setFont(
            inter(18, QFont.Weight.Black, letter_spacing=-0.3))
        self._rh_name.setStyleSheet(
            f"color: {TEXT_PRI}; background: transparent; "
            f"border: none;")

        self._rh_meta = QLabel("", card)
        self._rh_meta.setGeometry(50, 38, 700, 14)
        self._rh_meta.setFont(inter(11, QFont.Weight.Medium))
        self._rh_meta.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent; "
            f"border: none;")

        # Auto-suggested times pill
        autosug = QFrame(card)
        autosug.setGeometry(self.RW - 20 - 220, 18, 220, 24)
        autosug.setStyleSheet(
            f"QFrame {{ background: {rgba(PURPLE, 0.15)}; "
            f"border: 1px solid {rgba(PURPLE, 0.4)}; "
            f"border-radius: 12px; }}"
        )
        ah = QHBoxLayout(autosug)
        ah.setContentsMargins(0, 0, 0, 0); ah.setSpacing(0)
        al = QLabel("✦ AUTO-SUGGESTED TIMES", autosug)
        al.setFont(
            inter(9, QFont.Weight.Bold, letter_spacing=1.0))
        al.setStyleSheet(
            f"color: {PURPLE_LIGHT}; background: transparent; "
            f"border: none;")
        al.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ah.addWidget(al)

        # Table header (col labels)
        header_y = 70
        cols = [
            (20,  30,  "#"),
            (54,  140, "LINK NAME"),
            (200, 220, "AUDIO FILE"),
            (426, 54,  "DUR"),
            (486, 74,  "SHARP"),
            (566, 128, "PRIORITY"),
            (700, 36,  "▶"),
            (742, 108, "STATUS"),
            (858, 84,  ""),
        ]
        for x, w, lbl in cols:
            l = QLabel(lbl, card)
            l.setGeometry(x, header_y, w, 14)
            l.setFont(
                inter(9, QFont.Weight.Bold, letter_spacing=1.0))
            l.setStyleSheet(
                f"color: {TEXT_MUTED}; background: transparent; "
                f"border: none;")
        hdr_line = QFrame(card)
        hdr_line.setGeometry(16, header_y + 22, self.RW - 32, 1)
        hdr_line.setStyleSheet(
            f"QFrame {{ background: {rgba('#ffffff', 0.06)}; "
            f"border: none; }}")

        # Rows container (scrollable)
        self._rows_scroll = QScrollArea(card)
        self._rows_scroll.setGeometry(16, header_y + 30,
                                        self.RW - 32, self.RH - header_y - 30 - 56)
        self._rows_scroll.setWidgetResizable(True)
        self._rows_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._rows_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._rows_scroll.setStyleSheet(
            f"QScrollArea {{ background: transparent; border: none; }}"
            f"QScrollBar:vertical {{ background: transparent; "
            f"width: 6px; margin: 4px 2px; }}"
            f"QScrollBar::handle:vertical {{ background: "
            f"{rgba('#252840', 0.8)}; border-radius: 3px; "
            f"min-height: 32px; }}"
            f"QScrollBar::add-line, QScrollBar::sub-line {{ "
            f"height: 0; width: 0; }}"
        )
        self._rows_inner = QWidget()
        self._rows_inner.setStyleSheet(
            "QWidget { background: transparent; }")
        self._rows_scroll.setWidget(self._rows_inner)
        self._row_widgets: list[_LinkRow] = []

        # Legend footer
        self._build_legend(card)

    def _build_legend(self, card: QFrame) -> None:
        ly = self.RH - 38
        line = QFrame(card)
        line.setGeometry(16, ly - 4, self.RW - 32, 1)
        line.setStyleSheet(
            f"QFrame {{ background: {rgba('#ffffff', 0.06)}; "
            f"border: none; }}")

        def pill(x: int, color: str, light: str,
                  icon: str, label: str) -> None:
            f = QFrame(card)
            f.setGeometry(x, ly + 4, 86, 22)
            f.setStyleSheet(
                f"QFrame {{ background: {rgba(color, 0.15)}; "
                f"border: 1px solid {rgba(color, 0.4)}; "
                f"border-radius: 11px; }}"
            )
            il = QLabel(icon, f)
            il.setGeometry(8, 3, 16, 16)
            il.setFont(inter(10, QFont.Weight.Bold))
            il.setAlignment(Qt.AlignmentFlag.AlignCenter)
            il.setStyleSheet(
                f"color: {light}; background: transparent; "
                f"border: none;")
            tl = QLabel(label, f)
            tl.setGeometry(24, 3, 58, 16)
            tl.setFont(
                inter(8, QFont.Weight.Bold, letter_spacing=1.0))
            tl.setStyleSheet(
                f"color: {light}; background: transparent; "
                f"border: none;")

        base_x = 20
        pill(base_x,        "#454d6d", "#8891b8", "●", "PENDING")
        pill(base_x + 96,   CYAN,      CYAN_LIGHT, "●", "READY")
        pill(base_x + 192,  GREEN,     GREEN_LIGHT, "✓", "FIRED")
        pill(base_x + 288,  RED,       "#fb7185",  "✕", "MISSED")
        pill(base_x + 384,  AMBER,     AMBER_LIGHT, "⚠", "CONFLICT")
        ex = QLabel(
            "✦ CONFLICT: a paid Spots & Commercials break occupies "
            "this minute — paid spot will win, this link slips.",
            card)
        ex.setGeometry(base_x + 480, ly + 6, 480, 18)
        ex.setFont(inter(10))
        ex.setStyleSheet(
            f"color: {AMBER_LIGHT}; background: transparent; "
            f"border: none;")

    def _refresh_right_panel(self) -> None:
        # Clear rows
        for r in list(self._row_widgets):
            try:
                r.setParent(None)
                r.deleteLater()
            except Exception:
                pass
        self._row_widgets = []

        if self._selected_show_id is None:
            # Empty state — no show selected yet
            self._rh_name.setText("No show selected")
            self._rh_meta.setText(
                "Pick a show from the left panel to begin.")
            self._rh_chip.setStyleSheet(
                f"QLabel {{ background: {rgba('#454d6d', 0.6)}; "
                f"border-radius: 6px; }}")
            self._rows_inner.setFixedHeight(1)
            return

        # Show metadata
        try:
            show = self._db.get_sotg_show(self._selected_show_id)
        except Exception as exc:
            log.warning(f"get_sotg_show({self._selected_show_id}): {exc}")
            show = None
        if show is None:
            self._selected_show_id = None
            self._refresh_right_panel()
            return

        self._rh_chip.setStyleSheet(
            f"QLabel {{ background: {show.get('color') or CYAN}; "
            f"border-radius: 6px; }}")
        self._rh_name.setText(show.get("show_name") or "—")
        envelope = (
            f"{show.get('time_start') or '—'} – "
            f"{show.get('time_end') or '—'}")
        link_count = len(show.get("links") or [])
        # Approx interval
        sm = _hhmm_to_minutes(show.get("time_start") or "")
        em = _hhmm_to_minutes(show.get("time_end") or "")
        interval_txt = ""
        if sm is not None and em is not None and link_count > 0:
            span = em - sm if em > sm else (em + 24 * 60 - sm)
            interval_txt = f"  ·  ~{max(1, span // link_count)} min interval"
        self._rh_meta.setText(
            f"{show.get('rj_name') or '—'}  ·  "
            f"{show.get('days') or 'Daily'}  ·  {envelope}  ·  "
            f"{link_count} links{interval_txt}"
        )

        # Fetch per-link assignments for this date
        try:
            items = self._db.get_sotg_assignments_for_show_date(
                self._selected_show_id, self._scheduled_date)
        except Exception as exc:
            log.warning(f"assignments fetch failed: {exc}")
            items = []

        # Auto-suggested times pre-fill for any link without a sharp
        # time set yet. Only on the date currently in view; never
        # overwrites operator-authored times.
        suggested = _spread_times(
            show.get("time_start") or "",
            show.get("time_end") or "",
            link_count)

        # Lay out rows. Explicit .show() required after parenting to
        # an already-visible container (same fix pattern as the left
        # panel's _ShowCard rebuild).
        y = 0
        for i, item in enumerate(items):
            # Fill in suggested time if no assignment yet
            if not item.get("sharp_time") and i < len(suggested):
                item = dict(item)
                item["sharp_time"] = suggested[i]
                # Default priority when auto-suggesting? Leave blank
                # so the operator must explicitly pick — but if you
                # want a default, set "High" here.
                if not item.get("priority"):
                    item["priority"] = ""
            row = _LinkRow(
                {"id": item["link_id"],
                 "link_id": item["link_id"],
                 "link_order": item["link_order"],
                 "link_name": item["link_name"]},
                item,
                self._scheduled_date,
                engine=self._engine,
                parent=self._rows_inner,
            )
            row.move(0, y)
            row.save_requested.connect(self._on_row_save)
            row.show()
            self._row_widgets.append(row)
            y += _LinkRow.ROW_H

        self._rows_inner.setFixedSize(self.RW - 32, max(y, 1))

    def _on_row_save(self, link_id: int) -> None:
        row = next(
            (r for r in self._row_widgets if r.link_id() == link_id),
            None)
        if row is None:
            return
        data = row.current_form()
        try:
            self._db.upsert_sotg_assignment(
                show_id=self._selected_show_id,
                link_id=link_id,
                scheduled_date=self._scheduled_date,
                file_path=data.get("file_path"),
                file_name=data.get("file_name"),
                file_duration_ms=data.get("file_duration_ms") or 0,
                sharp_time=data.get("sharp_time"),
                priority=data.get("priority"),
                status="READY",
            )
        except ValueError as exc:
            dialogs.warning(
                self, "Save blocked", str(exc))
            return
        except Exception as exc:
            dialogs.error(
                self, "Save failed", f"{exc}")
            return
        # Re-render — picks up the new assignment_id, ready status,
        # updated label, etc.
        self._refresh_right_panel()
        self._refresh_shows_list()
        self._refresh_hero_counters()

    # ── Hero counters ─────────────────────────────────────────────────

    def _refresh_hero_counters(self) -> None:
        try:
            counts = self._db.get_sotg_assignment_counts_for_date(
                self._scheduled_date)
        except Exception:
            counts = {}
        total_queued = 0
        total_fired = 0
        total_conflict = 0
        total_missed = 0
        for sid, c in counts.items():
            total_queued += int(c.get("ready") or 0)
            total_fired += int(c.get("fired") or 0)
            total_conflict += int(c.get("conflict") or 0)
            total_missed += int(c.get("missed") or 0)
        self._pill_queued_label.setText(f"{total_queued} LINKS QUEUED")
        self._pill_fired_label.setText(f"{total_fired} FIRED")
        self._pill_conflict_label.setText(f"{total_conflict} CONFLICT")
        self._pill_missed_label.setText(f"{total_missed} MISSED")

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
                          ("✦ ASSIGN", CYAN_LIGHT),
                          ("Live Data", GREEN)):
            p = _StatusPill(txt, col, sb)
            p.move(x, (STATUS_H - p.height()) // 2)
            x += p.width() + 8

        ver = QLabel(
            "Spot on the Go  ·  Step 2 / 4  ·  RadioAI Studio v1.0.0",
            sb)
        ver.setFont(inter(9))
        ver.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; "
            f"border: none;")
        ver.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        ver.setFixedSize(440, STATUS_H)
        ver.move(WINDOW_W - 24 - 440 - 130, 0)

        osb = QPushButton("▶  Open Studio", sb)
        osb.setFixedSize(120, 26)
        osb.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        osb.setFont(inter(10, QFont.Weight.Bold))
        osb.setStyleSheet(
            f"QPushButton {{ background: transparent; "
            f"color: {GREEN_LIGHT}; border: none; padding: 0 8px; }}"
            f"QPushButton:hover {{ color: {GREEN}; }}"
        )
        osb.move(WINDOW_W - 12 - 120, (STATUS_H - 26) // 2)
        osb.clicked.connect(self.studio_clicked.emit)

    # ── Clock tick ────────────────────────────────────────────────────

    def _tick_clock(self) -> None:
        self._clock_lbl.setText(datetime.now().strftime("%H:%M:%S"))
        # Re-trigger past-time validation every minute so a row that
        # was valid at 09:59 turns invalid at 10:00.
        if (datetime.now().second == 0
                and self._scheduled_date == ddate.today().isoformat()):
            for r in self._row_widgets:
                try:
                    r.set_scheduled_date(self._scheduled_date)
                except Exception:
                    pass

    # ── Public — refresh hooks for host routing ──────────────────────

    def refresh(self) -> None:
        """Called by MainWindow when the route lands on this screen."""
        self._refresh_shows_list()
        self._refresh_right_panel()
        self._refresh_hero_counters()
