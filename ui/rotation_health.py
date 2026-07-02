"""
RadioAI Studio Pro — Rotation Health (Songs Library report)

Day-wise audit of what the Time-Slot Freshness rotation engine did
to each music category. Reached via the Songs Library sidebar tile
"🎯 Rotation Health"; back button returns to Songs Library.

Per-category card grid (3-up). Every card has three stacked
sections:
  • RESTED         — songs from this category the AI vetoed at one
                     of their native clock slots
  • PROMOTED OUT   — songs from this category the AI inserted into
                     another (sister) category's clock
  • PROMOTED IN    — songs from OTHER categories that came INTO
                     this category's clock via the sister pool

A single 'promote' decision surfaces in BOTH the source card's
PROMOTED OUT list and the target card's PROMOTED IN list — operator's
Q6 "both cards" decision, full audit trail.

Per-row: Clock name · Song title · Parent category. Hover any row
to see a tooltip with `last 7d plays · all-time plays · reason`
(operator's Q7 = hover tooltip; Q4 = both play counts).

Date picker defaults to today (Q2). Last-7d play count is
rolling-from-today regardless of date pick (Q8).

Header matches the existing Songs Library report convention
(Category Performance, Play History) — full premium chrome with
breadcrumb: Control Panel | Songs Library | Rotation Health.

Figma reference: node 521:2 on the "AI · Scheduling Automation"
page (file 7oN9K61g94wKx3nu44KKDF).

Public signals:
  breadcrumb_clicked(str) — "control_panel" / "songs"
  studio_clicked()        — header Open Studio button
  back_clicked()          — Back-to-songs button on the body
"""

from __future__ import annotations

import logging
from datetime import date as _date, datetime
from typing import Optional

from PyQt6.QtCore import Qt, QDate, QPoint, pyqtSignal
from PyQt6.QtGui import QFont, QCursor, QPainter, QPen, QBrush, QColor
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QHBoxLayout, QVBoxLayout,
    QScrollArea, QGridLayout, QSizePolicy, QMenu, QCalendarWidget,
    QDialog,
)

from core.settings import Settings
from ui.widgets._tokens import (
    inter, mono, rgba,
    BG_BASE, BG_PANEL,
    TEXT_PRI, TEXT_SEC, TEXT_MUTED, TEXT_DIM,
    CYAN, CYAN_LIGHT, PURPLE, PURPLE_LIGHT,
    GREEN, GREEN_LIGHT, AMBER, AMBER_LIGHT, RED,
    PINK,
)
from ui.spot_on_the_go_shell import (
    _HeaderLogo, _HeaderOpenStudio, _BreadcrumbLink,
)

log = logging.getLogger("RotationHealth")

WINDOW_W = 1440
WINDOW_H = 900
HEADER_H = 72
STATUS_H = 36

BG_CARD     = "#0e1020"
BG_ELEVATED = "#131626"
BORDER      = "#1c1f38"


# ════════════════════════════════════════════════════════════════════════════
# Small reusable widgets
# ════════════════════════════════════════════════════════════════════════════


class _BreadcrumbPill(QFrame):
    """Small filled pill for the active breadcrumb leg. Mirrors the
    same widget used in Category Performance / Play History."""

    def __init__(self, label: str, accent: str = GREEN, parent=None):
        super().__init__(parent)
        self.setFixedSize(150, 24)
        self.setStyleSheet(
            f"QFrame {{ background: {rgba(accent, 0.18)}; "
            f"border-radius: 12px; "
            f"border: 1px solid {rgba(accent, 0.40)}; }}")
        t = QLabel(label, self)
        t.setGeometry(0, 0, self.width(), self.height())
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t.setFont(inter(10, QFont.Weight.Bold, letter_spacing=0.4))
        t.setStyleSheet(
            f"color: {accent}; background: transparent; border: none;")


class _StatPill(QFrame):
    """Summary strip stat card. 5 of these across the top: rested,
    promoted, clocks, errors, plan status. ~248 wide × 92 tall."""

    def __init__(self, label: str, value: str, accent: str,
                 value_color: str = TEXT_PRI,
                 sub: str = "", parent=None):
        super().__init__(parent)
        self.setFixedSize(248, 92)
        self.setStyleSheet(
            f"QFrame#stat_pill {{ background: {BG_CARD}; "
            f"border: 1px solid {BORDER}; border-radius: 12px; }}")
        self.setObjectName("stat_pill")
        self._accent = accent
        # Accent strip at top
        strip = QFrame(self)
        strip.setGeometry(0, 0, self.width(), 3)
        strip.setStyleSheet(
            f"background: {accent}; "
            f"border-top-left-radius: 12px; "
            f"border-top-right-radius: 12px;")
        # Dot
        dot = QFrame(self)
        dot.setGeometry(20, 22, 8, 8)
        dot.setStyleSheet(
            f"background: {accent}; border-radius: 4px;")
        # Label
        lbl = QLabel(label.upper(), self)
        lbl.setGeometry(36, 18, self.width() - 56, 16)
        lbl.setFont(inter(9, QFont.Weight.Bold, letter_spacing=1.2))
        lbl.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent; "
            f"border: none;")
        # Value
        self._val = QLabel(value, self)
        self._val.setGeometry(20, 40, self.width() - 40, 36)
        self._val.setFont(
            inter(26, QFont.Weight.Bold, letter_spacing=-0.4))
        self._val.setStyleSheet(
            f"color: {value_color}; background: transparent; "
            f"border: none;")
        # Sub
        self._sub = QLabel(sub, self)
        self._sub.setGeometry(20, 72, self.width() - 40, 14)
        self._sub.setFont(inter(9, QFont.Weight.Medium))
        self._sub.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; "
            f"border: none;")

    def set_value(self, value: str) -> None:
        self._val.setText(value)

    def set_sub(self, sub: str) -> None:
        self._sub.setText(sub)


class _DatePillButton(QPushButton):
    """Date picker pill: '📅 2026-05-15 (Today) ▾'. Opens a small
    QCalendarWidget popup on click. Emits ``date_picked(QDate)``."""

    date_picked = pyqtSignal(QDate)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._date = QDate.currentDate()
        self.setFixedSize(220, 40)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            f"QPushButton {{ background: {BG_ELEVATED}; "
            f"border: 1px solid {BORDER}; "
            f"border-radius: 8px; "
            f"color: {TEXT_PRI}; "
            f"font: 600 12px 'Inter'; "
            f"padding-left: 12px; text-align: left; }}"
            f"QPushButton:hover {{ "
            f"border-color: {rgba(GREEN, 0.55)}; }}")
        self.clicked.connect(self._open_calendar)
        self._refresh_text()

    def _refresh_text(self) -> None:
        suffix = (" (Today)"
                  if self._date == QDate.currentDate() else "")
        self.setText(
            f"📅  {self._date.toString('yyyy-MM-dd')}{suffix}    ▾")

    def date(self) -> QDate:
        return QDate(self._date)

    def set_date(self, qdate: QDate) -> None:
        if qdate.isValid():
            self._date = QDate(qdate)
            self._refresh_text()

    def _open_calendar(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowFlags(
            Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        dlg.setStyleSheet(
            f"QDialog {{ background: {BG_PANEL}; "
            f"border: 1px solid {BORDER}; border-radius: 8px; }}"
            f"QCalendarWidget QWidget {{ "
            f"background: {BG_PANEL}; color: {TEXT_PRI}; }}"
            f"QCalendarWidget QAbstractItemView:enabled {{ "
            f"background: {BG_CARD}; color: {TEXT_PRI}; "
            f"selection-background-color: {rgba(GREEN, 0.35)}; "
            f"selection-color: {TEXT_PRI}; }}"
            f"QCalendarWidget QToolButton {{ "
            f"background: transparent; color: {TEXT_PRI}; "
            f"font-weight: 600; }}"
            f"QCalendarWidget QSpinBox {{ background: {BG_CARD}; "
            f"color: {TEXT_PRI}; }}")
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(8, 8, 8, 8)
        cal = QCalendarWidget(dlg)
        cal.setSelectedDate(self._date)
        cal.setMaximumDate(QDate.currentDate())  # no future dates
        cal.setGridVisible(False)
        cal.setVerticalHeaderFormat(
            QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        cal.clicked.connect(
            lambda qd: (self._on_calendar_picked(qd), dlg.accept()))
        lay.addWidget(cal)
        # Anchor under the button
        pos = self.mapToGlobal(QPoint(0, self.height() + 4))
        dlg.move(pos)
        dlg.exec()

    def _on_calendar_picked(self, qdate: QDate) -> None:
        if qdate.isValid() and qdate != self._date:
            self._date = QDate(qdate)
            self._refresh_text()
            self.date_picked.emit(QDate(self._date))


class _RefreshButton(QPushButton):
    """Icon-only refresh button next to the date pill."""

    def __init__(self, parent=None):
        super().__init__("↻", parent)
        self.setFixedSize(44, 40)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            f"QPushButton {{ background: {BG_ELEVATED}; "
            f"border: 1px solid {BORDER}; border-radius: 8px; "
            f"color: {TEXT_PRI}; font: 700 18px 'Inter'; }}"
            f"QPushButton:hover {{ "
            f"border-color: {rgba(GREEN, 0.55)}; "
            f"background: {rgba(GREEN, 0.10)}; }}")


class _FilterDropdown(QPushButton):
    """Filter chooser. Modes: all / rested / promoted / has_changes."""

    mode_changed = pyqtSignal(str)
    MODES = [
        ("all",          "All decisions"),
        ("rested",       "Rested only"),
        ("promoted",     "Promoted only"),
        ("has_changes",  "Has changes only"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mode = "all"
        self.setFixedSize(180, 28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            f"QPushButton {{ background: {BG_ELEVATED}; "
            f"border: 1px solid {BORDER}; border-radius: 6px; "
            f"color: {TEXT_PRI}; font: 500 11px 'Inter'; "
            f"padding-left: 12px; text-align: left; }}"
            f"QPushButton:hover {{ "
            f"border-color: {rgba(GREEN, 0.55)}; }}")
        self.clicked.connect(self._open_menu)
        self._refresh_text()

    def _refresh_text(self) -> None:
        label = next(
            (l for k, l in self.MODES if k == self._mode), "All")
        self.setText(f"Filter: {label}    ▾")

    def mode(self) -> str:
        return self._mode

    def _open_menu(self) -> None:
        m = QMenu(self)
        m.setStyleSheet(
            f"QMenu {{ background: {BG_PANEL}; "
            f"border: 1px solid {BORDER}; color: {TEXT_PRI}; "
            f"padding: 4px; }}"
            f"QMenu::item {{ padding: 6px 16px; }}"
            f"QMenu::item:selected {{ "
            f"background: {rgba(GREEN, 0.18)}; }}")
        for key, label in self.MODES:
            act = m.addAction(label)
            act.setData(key)
        chosen = m.exec(self.mapToGlobal(QPoint(0, self.height())))
        if chosen:
            new_mode = chosen.data()
            if new_mode != self._mode:
                self._mode = new_mode
                self._refresh_text()
                self.mode_changed.emit(self._mode)


class _HideEmptyToggle(QFrame):
    """Square checkbox + 'Hide empty cards' label. Emits toggled(bool)."""

    toggled = pyqtSignal(bool)

    def __init__(self, checked: bool = True, parent=None):
        super().__init__(parent)
        self._checked = bool(checked)
        self.setFixedSize(170, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("QFrame { background: transparent; }")
        self._box = QFrame(self)
        self._box.setGeometry(0, 4, 14, 14)
        self._mark = QLabel("", self._box)
        self._mark.setGeometry(0, 0, 14, 14)
        self._mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._mark.setFont(inter(9, QFont.Weight.Bold))
        self._lbl = QLabel("Hide empty cards", self)
        self._lbl.setGeometry(22, 4, 150, 14)
        self._lbl.setFont(inter(11, QFont.Weight.Medium))
        self._lbl.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent;")
        self._repaint_box()

    def _repaint_box(self) -> None:
        if self._checked:
            self._box.setStyleSheet(
                f"background: {GREEN}; border-radius: 3px;")
            self._mark.setStyleSheet(
                f"color: {BG_BASE}; background: transparent;")
            self._mark.setText("✓")
        else:
            self._box.setStyleSheet(
                f"background: transparent; "
                f"border: 1.5px solid {TEXT_MUTED}; "
                f"border-radius: 3px;")
            self._mark.setText("")

    def is_checked(self) -> bool:
        return self._checked

    def set_checked(self, val: bool) -> None:
        val = bool(val)
        if val == self._checked:
            return
        self._checked = val
        self._repaint_box()
        self.toggled.emit(self._checked)

    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.MouseButton.LeftButton:
            self.set_checked(not self._checked)
        super().mousePressEvent(ev)


# ════════════════════════════════════════════════════════════════════════════
# Card body: section + row + card
# ════════════════════════════════════════════════════════════════════════════


class _DecisionRow(QFrame):
    """One row inside a section. Layout = Clock | Song | Parent cat.
    Hover shows a tooltip with rolling-7d + all-time play counts +
    the engine's `reason` string."""

    HEIGHT = 28

    def __init__(self, decision: dict, db=None, parent=None):
        super().__init__(parent)
        self.setFixedHeight(self.HEIGHT)
        self.setStyleSheet(
            f"QFrame {{ background: transparent; "
            f"border: none; border-radius: 4px; }}"
            f"QFrame:hover {{ background: {rgba('#ffffff', 0.04)}; }}")

        clock_name = (decision.get("clock_name")
                       or f"Clock {decision.get('clock_id') or '?'}")
        song_title = decision.get("song_title") or "(unknown song)"
        song_artist = decision.get("song_artist") or ""
        hour = decision.get("hour")
        # The "parent category" of the song is its native category —
        # source_category for rest + promoted_out, source_category for
        # promoted_in (the song's home, not where it's going).
        # ai_rotation_decisions always stores source_category_id as
        # the song's home category, so source_category_name is the
        # right field for all three sections.
        parent_cat = decision.get("source_category_name") or ""

        # Hour-aware clock label (e.g. "10 AM Clock — Morning Mix")
        try:
            h = int(hour) if hour is not None else None
        except (TypeError, ValueError):
            h = None
        if h is not None and 0 <= h <= 23:
            ampm = ("AM" if h < 12 else "PM")
            twelve = (h % 12) or 12
            clock_lbl = f"{twelve} {ampm} · {clock_name}"
        else:
            clock_lbl = clock_name

        # Tooltip — Qt rich-text HTML
        last7 = 0
        all_time = 0
        sid = decision.get("song_id")
        if db is not None and sid is not None:
            try:
                last7 = int(
                    db.get_song_recent_plays_count(int(sid), 7) or 0)
            except Exception as exc:
                log.debug(f"tooltip last7 failed sid={sid}: {exc}")
            try:
                stats = db.get_song_play_stats(int(sid))
                all_time = int(stats.get("play_count") or 0)
            except Exception as exc:
                log.debug(f"tooltip all_time failed sid={sid}: {exc}")
        reason = (decision.get("reason") or "").strip()
        artist_line = (
            f"<div style='color:#8891b8;font-size:10pt;'>{song_artist}"
            f"</div>" if song_artist else "")
        reason_line = (
            f"<div style='color:#f59e0b;font-size:9pt;margin-top:4px;'>"
            f"Reason: {reason}</div>" if reason else "")
        tip_html = (
            f"<div style='font-family:Inter,sans-serif;'>"
            f"<div style='color:#f1f5ff;font-size:11pt;"
            f"font-weight:700;'>{song_title}</div>"
            f"{artist_line}"
            f"<div style='color:#1c1f38;margin:6px 0;'>"
            f"<hr style='border:none;height:1px;background:#1c1f38;'/>"
            f"</div>"
            f"<div style='color:#f1f5ff;font-size:10pt;"
            f"font-weight:600;'>"
            f"⏱ Last 7d: {last7} plays  ·  All-time: "
            f"{all_time}</div>"
            f"{reason_line}"
            f"</div>")
        self.setToolTip(tip_html)

        # Three columns
        col_clock = QLabel(clock_lbl, self)
        col_clock.setGeometry(10, 5, 150, 18)
        col_clock.setFont(inter(10, QFont.Weight.Medium))
        col_clock.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent; "
            f"border: none;")

        col_song = QLabel(song_title, self)
        col_song.setGeometry(168, 5, 180, 18)
        col_song.setFont(inter(10, QFont.Weight.Bold))
        col_song.setStyleSheet(
            f"color: {TEXT_PRI}; background: transparent; "
            f"border: none;")

        col_cat = QLabel(parent_cat, self)
        col_cat.setGeometry(354, 5, 100, 18)
        col_cat.setFont(inter(10, QFont.Weight.Medium))
        col_cat.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; "
            f"border: none;")
        col_cat.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)


class _CardSection(QFrame):
    """Section header (color bar + name + optional target chip)
    followed by N decision rows. Auto-sizes vertically."""

    PAD_X = 16
    HEADER_H = 22
    ROW_H = _DecisionRow.HEIGHT
    GAP_AFTER = 8

    def __init__(self, title: str, accent: str, target_chip: str,
                 decisions: list, db=None, parent=None):
        super().__init__(parent)
        self.setStyleSheet("QFrame { background: transparent; }")

        bar = QFrame(self)
        bar.setGeometry(self.PAD_X, 4, 3, 14)
        bar.setStyleSheet(
            f"background: {accent}; border-radius: 1.5px;")

        name = QLabel(title.upper(), self)
        name.setGeometry(self.PAD_X + 10, 4, 160, 14)
        name.setFont(inter(9, QFont.Weight.Bold, letter_spacing=1.2))
        name.setStyleSheet(
            f"color: {TEXT_PRI}; background: transparent;")

        if target_chip:
            chip = QLabel(target_chip, self)
            chip.setFont(inter(9, QFont.Weight.Medium, letter_spacing=0.6))
            chip.setStyleSheet(
                f"color: {accent}; background: transparent;")
            chip.setAlignment(
                Qt.AlignmentFlag.AlignRight
                | Qt.AlignmentFlag.AlignVCenter)
            chip.setGeometry(0, 4, 0, 14)  # geometry set in resize hook

        # Rows
        self._rows: list[_DecisionRow] = []
        y = self.HEADER_H
        for d in decisions:
            r = _DecisionRow(d, db=db, parent=self)
            r.setGeometry(0, y, 100, self.ROW_H)  # width fixed in resize
            self._rows.append(r)
            y += self.ROW_H

        self._total_h = y + self.GAP_AFTER
        self._target_chip_widget = chip if target_chip else None

    def total_height(self) -> int:
        return self._total_h

    def resize_to_width(self, w: int) -> None:
        # Resize rows to card width
        for r in self._rows:
            r.setGeometry(self.PAD_X - 6, r.y(),
                          w - (self.PAD_X * 2 - 12), r.height())
            # Update internal column geometries
            children = r.findChildren(QLabel)
            if len(children) >= 3:
                clock_lbl, song_lbl, cat_lbl = children[0], children[1], children[2]
                clock_lbl.setGeometry(10, 5, 130, 18)
                song_lbl.setGeometry(150, 5,
                                       max(80, w - 150 - 110 - 24), 18)
                cat_lbl.setGeometry(w - 110 - 24, 5, 110, 18)
        # Target chip flush right
        if self._target_chip_widget is not None:
            cw = w - (self.PAD_X * 2)
            self._target_chip_widget.setGeometry(
                self.PAD_X + 130, 4, cw - 130 - 12, 14)


class _CategoryCard(QFrame):
    """One per-category card with up to 3 sections. Card height is
    variable; the screen's grid layout reads ``preferred_height()``
    to know how much vertical space to allocate."""

    PAD_X = 16
    HEADER_H = 56

    def __init__(self, *, category_id: int, name: str,
                 accent: str, rested: list, promoted_out: list,
                 promoted_in: list, db=None, parent=None):
        super().__init__(parent)
        self.category_id = int(category_id)
        self._accent = accent or "#8891b8"
        self.setStyleSheet(
            f"QFrame#cat_card {{ background: {BG_CARD}; "
            f"border: 1px solid {BORDER}; border-radius: 14px; }}")
        self.setObjectName("cat_card")

        # Left accent stripe — painted in paintEvent
        self._stripe_w = 3

        n_rest = len(rested)
        n_out = len(promoted_out)
        n_in = len(promoted_in)
        self._counts = {"rested": n_rest, "out": n_out, "in": n_in}

        dot = QFrame(self)
        dot.setGeometry(20, 24, 10, 10)
        dot.setStyleSheet(
            f"background: {self._accent}; border-radius: 5px;")
        name_lbl = QLabel(name.upper(), self)
        name_lbl.setGeometry(38, 20, 360, 18)
        name_lbl.setFont(
            inter(13, QFont.Weight.Bold, letter_spacing=0.4))
        name_lbl.setStyleSheet(
            f"color: {TEXT_PRI}; background: transparent;")
        counts_text = (
            f"{n_rest} rested  ·  {n_out} out  ·  {n_in} in")
        counts_lbl = QLabel(counts_text, self)
        counts_lbl.setGeometry(20, 40, 380, 14)
        counts_lbl.setFont(
            inter(10, QFont.Weight.Medium, letter_spacing=0.4))
        counts_lbl.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent;")

        # Divider beneath header
        div = QFrame(self)
        div.setGeometry(16, self.HEADER_H + 4, 100, 1)
        div.setStyleSheet(
            f"background: {rgba('#ffffff', 0.06)};")
        self._div = div

        # Build sections
        self._sections: list[_CardSection] = []
        cy = self.HEADER_H + 12
        if rested:
            s = _CardSection(
                "Rested", RED, "", rested, db=db, parent=self)
            s.move(0, cy)
            cy += s.total_height()
            self._sections.append(s)
        if promoted_out:
            s = _CardSection(
                "Promoted Out", AMBER,
                "→ to other clocks",
                promoted_out, db=db, parent=self)
            s.move(0, cy)
            cy += s.total_height()
            self._sections.append(s)
        if promoted_in:
            s = _CardSection(
                "Promoted In", GREEN,
                "← from sister categories",
                promoted_in, db=db, parent=self)
            s.move(0, cy)
            cy += s.total_height()
            self._sections.append(s)

        if not (rested or promoted_out or promoted_in):
            # Should not normally happen — empty cards use
            # _EmptyCategoryCard. Defensive fallback.
            stub = QLabel("no changes today", self)
            stub.setGeometry(20, cy, 240, 14)
            stub.setFont(inter(10, QFont.Weight.Medium))
            stub.setStyleSheet(
                f"color: {TEXT_MUTED}; background: transparent;")
            cy += 24

        self._preferred_h = max(cy + 12, 140)

    def preferred_height(self) -> int:
        return self._preferred_h

    def resize_to_width(self, w: int) -> None:
        self.setFixedSize(w, self._preferred_h)
        self._div.setGeometry(16, self.HEADER_H + 4, w - 32, 1)
        for s in self._sections:
            s.setFixedWidth(w)
            s.resize_to_width(w)

    def paintEvent(self, ev) -> None:
        super().paintEvent(ev)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(self._accent)))
        # 3-wide left stripe rounded to match card radius
        p.drawRoundedRect(
            0, 0, self._stripe_w + 8, self.height(), 4, 4)


class _EmptyCategoryCard(QFrame):
    """Dashed empty-state card shown when a category had no AI changes
    for the selected date. The 'Hide empty cards' toggle controls
    whether these are rendered."""

    HEIGHT = 160

    def __init__(self, *, category_id: int, name: str,
                 accent: str, parent=None):
        super().__init__(parent)
        self.category_id = int(category_id)
        self._accent = accent or "#8891b8"
        self.setStyleSheet(
            f"QFrame#cat_empty {{ background: {BG_CARD}; "
            f"border: 1px solid {BORDER}; border-radius: 14px; }}")
        self.setObjectName("cat_empty")
        self.setFixedHeight(self.HEIGHT)
        # Reduce visual weight
        try:
            self.setWindowOpacity(0.7)
        except Exception:
            pass

        dot = QFrame(self)
        dot.setGeometry(20, 26, 10, 10)
        dot.setStyleSheet(
            f"background: {rgba(self._accent, 0.7)}; "
            f"border-radius: 5px;")
        name_lbl = QLabel(name.upper(), self)
        name_lbl.setGeometry(38, 20, 360, 20)
        name_lbl.setFont(
            inter(13, QFont.Weight.Bold, letter_spacing=0.4))
        name_lbl.setStyleSheet(
            f"color: {TEXT_PRI}; background: transparent;")
        counts_lbl = QLabel("no changes today", self)
        counts_lbl.setGeometry(20, 42, 360, 14)
        counts_lbl.setFont(
            inter(10, QFont.Weight.Medium, letter_spacing=0.4))
        counts_lbl.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent;")

        body = QFrame(self)
        body.setGeometry(0, 0, 100, 60)
        body.setStyleSheet(
            f"QFrame {{ background: transparent; "
            f"border: 1px dashed {rgba('#ffffff', 0.10)}; "
            f"border-radius: 10px; }}")
        self._body = body
        msg = QLabel("AI did not touch this category", body)
        msg.setFont(inter(11, QFont.Weight.Medium))
        msg.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent; "
            f"border: none;")
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._msg = msg
        sub = QLabel(
            '(toggle "Hide empty cards" to remove)', body)
        sub.setFont(inter(9, QFont.Weight.Normal))
        sub.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; "
            f"border: none;")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._sub = sub

    def resize_to_width(self, w: int) -> None:
        self.setFixedSize(w, self.HEIGHT)
        self._body.setGeometry(24, 80, w - 48, 60)
        self._msg.setGeometry(0, 12, w - 48, 16)
        self._sub.setGeometry(0, 32, w - 48, 14)

    def paintEvent(self, ev) -> None:
        super().paintEvent(ev)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(rgba(self._accent, 0.5))))
        p.drawRoundedRect(0, 0, 3 + 8, self.height(), 4, 4)


# ════════════════════════════════════════════════════════════════════════════
# Main screen
# ════════════════════════════════════════════════════════════════════════════


class RotationHealthScreen(QWidget):
    """Rotation Health — Songs Library report (Figma 521:2)."""

    breadcrumb_clicked = pyqtSignal(str)
    studio_clicked     = pyqtSignal()
    back_clicked       = pyqtSignal()

    def __init__(self, db, engine=None, parent=None):
        super().__init__(parent)
        self._db = db
        self._engine = engine
        self._selected_date: _date = _date.today()
        self._hide_empty: bool = True
        self._filter_mode: str = "all"

        self.setFixedSize(WINDOW_W, WINDOW_H)
        self.setStyleSheet(
            f"QWidget {{ background: {BG_BASE}; }}"
            f"QToolTip {{ background: #1a1d33; "
            f"color: {TEXT_PRI}; "
            f"border: 1px solid {PURPLE}; "
            f"padding: 8px 10px; "
            f"border-radius: 6px; "
            f"font-family: 'Inter'; font-size: 11pt; }}")

        self._build_header()
        self._build_summary_strip()
        self._build_filter_row()
        self._build_card_grid()
        self._build_status_bar()

        # Live load
        self._load_state()

        from PyQt6.QtCore import QTimer
        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._tick_clock)
        self._clock_timer.start()
        self._tick_clock()

        log.info("RotationHealthScreen ready (Figma 521:2)")

    # ── Public API ─────────────────────────────────────────────────────

    def refresh(self) -> None:
        """Re-pull summary from DB and rebuild card grid. Called from
        MainWindow after the screen is shown, and after Refresh tick."""
        self._load_state()

    def selected_date(self) -> _date:
        return self._selected_date

    # ── Header ─────────────────────────────────────────────────────────

    def _build_header(self) -> None:
        h = QFrame(self)
        h.setGeometry(0, 0, WINDOW_W, HEADER_H)
        h.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border-bottom: 1px solid {rgba('#ffffff', 0.06)}; }}")

        _HeaderLogo(h).move(14, 16)
        l = QLabel("RadioAI", h)
        l.setGeometry(64, 14, 120, 18)
        l.setFont(inter(15, QFont.Weight.Bold))
        l.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        sub = QLabel("STUDIO PRO", h)
        sub.setGeometry(64, 34, 120, 12)
        sub.setFont(inter(8, QFont.Weight.Bold, letter_spacing=1.2))
        sub.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

        # Breadcrumb: Control Panel | Songs Library | (pill) Rotation Health
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
        pill = _BreadcrumbPill("🎯 Rotation Health", GREEN, h)
        pill.move(396, 20)

        title = QLabel("Rotation Health", h)
        title.setGeometry(556, 12, 300, 24)
        title.setFont(inter(20, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        sub2 = QLabel(
            "Day-wise AI rotation audit · per-category", h)
        sub2.setGeometry(556, 38, 500, 14)
        sub2.setFont(inter(10))
        sub2.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

        # Clock + station
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

    def _tick_clock(self) -> None:
        self._clock_lbl.setText(datetime.now().strftime("%I:%M %p"))

    # ── Summary strip (5 stat pills + date picker + refresh) ──────────

    def _build_summary_strip(self) -> None:
        # Back-to-songs as a tiny breadcrumb under the header
        back = QPushButton("← Back to Songs Library", self)
        back.setGeometry(60, 88, 200, 22)
        back.setCursor(Qt.CursorShape.PointingHandCursor)
        back.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; "
            f"color: {TEXT_SEC}; "
            f"font: 500 11px 'Inter'; text-align: left; }}"
            f"QPushButton:hover {{ color: {GREEN}; }}")
        back.clicked.connect(self.back_clicked.emit)

        # Date picker + refresh — top right of body
        self._date_pill = _DatePillButton(self)
        self._date_pill.move(WINDOW_W - 60 - 220 - 12 - 44, 88)
        self._date_pill.date_picked.connect(self._on_date_picked)

        self._refresh_btn = _RefreshButton(self)
        self._refresh_btn.move(WINDOW_W - 60 - 44, 88)
        self._refresh_btn.clicked.connect(self._on_refresh_clicked)

        # 5 stat pills
        self._stat_rested = _StatPill(
            "Rested",   "0", RED,    parent=self)
        self._stat_promoted = _StatPill(
            "Promoted", "0", GREEN,  parent=self)
        self._stat_clocks = _StatPill(
            "Clocks",   "0", PURPLE, parent=self)
        self._stat_errors = _StatPill(
            "Errors",   "0", AMBER,  parent=self)
        self._stat_plan = _StatPill(
            "Plan Status", "—", CYAN,
            value_color=TEXT_PRI, sub="", parent=self)

        SP_W = 248
        SP_GAP = 16
        total = 5 * SP_W + 4 * SP_GAP
        start_x = (WINDOW_W - total) // 2
        ys = 136
        for i, w in enumerate(
                (self._stat_rested, self._stat_promoted,
                 self._stat_clocks, self._stat_errors, self._stat_plan)):
            w.move(start_x + i * (SP_W + SP_GAP), ys)

    # ── Filter row ─────────────────────────────────────────────────────

    def _build_filter_row(self) -> None:
        cap = QLabel("PER-CATEGORY HEALTH", self)
        cap.setGeometry(60, 248, 280, 18)
        cap.setFont(inter(11, QFont.Weight.Bold, letter_spacing=1.4))
        cap.setStyleSheet(
            f"color: {TEXT_PRI}; background: transparent;")

        self._filter = _FilterDropdown(self)
        self._filter.move(WINDOW_W - 60 - 180 - 16 - 180, 248)
        self._filter.mode_changed.connect(self._on_filter_changed)

        self._hide_empty_toggle = _HideEmptyToggle(
            checked=True, parent=self)
        self._hide_empty_toggle.move(WINDOW_W - 60 - 170, 251)
        self._hide_empty_toggle.toggled.connect(self._on_hide_empty)

    # ── Card grid (scrollable) ─────────────────────────────────────────

    def _build_card_grid(self) -> None:
        self._scroll = QScrollArea(self)
        self._scroll.setGeometry(
            60, 280, WINDOW_W - 120, WINDOW_H - 280 - STATUS_H - 10)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(
            f"QScrollArea {{ background: transparent; "
            f"border: none; }}"
            f"QScrollBar:vertical {{ background: {BG_PANEL}; "
            f"width: 10px; border-radius: 5px; }}"
            f"QScrollBar::handle:vertical {{ background: "
            f"{rgba('#ffffff', 0.12)}; border-radius: 5px; "
            f"min-height: 30px; }}"
            f"QScrollBar::handle:vertical:hover {{ background: "
            f"{rgba(GREEN, 0.40)}; }}"
            f"QScrollBar::add-line:vertical, "
            f"QScrollBar::sub-line:vertical {{ height: 0; }}")

        self._grid_inner = QWidget()
        self._grid_inner.setStyleSheet(
            f"background: transparent;")
        self._scroll.setWidget(self._grid_inner)
        self._card_widgets: list[QWidget] = []

    # ── Status bar ─────────────────────────────────────────────────────

    def _build_status_bar(self) -> None:
        sb = QFrame(self)
        sb.setGeometry(0, WINDOW_H - STATUS_H, WINDOW_W, STATUS_H)
        sb.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border-top: 1px solid {rgba('#ffffff', 0.06)}; }}")
        hint = QLabel(
            "Empty cards hidden by default  ·  hover any row to see "
            "play counts  ·  refresh to re-pull after the next AI tick",
            sb)
        hint.setGeometry(0, 0, WINDOW_W, STATUS_H)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setFont(inter(10, QFont.Weight.Normal))
        hint.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; "
            f"border: none;")

    # ── Live state loader ─────────────────────────────────────────────

    def _load_state(self) -> None:
        date_iso = self._selected_date.isoformat()
        summary: dict = {"plan": None, "categories": []}
        if self._db is not None:
            try:
                summary = self._db.get_rotation_summary_for_date(
                    date_iso)
            except Exception as exc:
                log.warning(
                    f"get_rotation_summary_for_date({date_iso}) "
                    f"failed: {exc}")

        plan = summary.get("plan")
        categories: list = summary.get("categories") or []
        self._summary_data = summary

        # Update 5 stat pills from plan envelope + decision counts
        if plan:
            rested = int(plan.get("rested_count") or 0)
            promoted = int(plan.get("promoted_count") or 0)
            clocks = int(plan.get("clocks_balanced") or 0)
            errors = int(plan.get("error_count") or 0)
            status = str(plan.get("status") or "pending")
            approved_at = plan.get("approved_at") or ""
            discarded_at = plan.get("discarded_at") or ""
        else:
            rested = promoted = clocks = errors = 0
            status = ""
            approved_at = ""
            discarded_at = ""

        # Re-derive rested/promoted counts from buckets if the
        # envelope counters look stale (engine writes them at tick
        # time but admin operations may not refresh).
        cnt_rested = sum(len(c.get("rested") or [])
                          for c in categories)
        cnt_out = sum(len(c.get("promoted_out") or [])
                      for c in categories)
        # promote source equals promote target count in aggregate,
        # so promoted_total = cnt_out (each decision counted once)
        if rested == 0 and cnt_rested > 0:
            rested = cnt_rested
        if promoted == 0 and cnt_out > 0:
            promoted = cnt_out
        if clocks == 0:
            # Distinct clock_ids touched
            ids = set()
            for c in categories:
                for d in (c.get("rested") or []):
                    ids.add(d.get("clock_id"))
                for d in (c.get("promoted_out") or []):
                    ids.add(d.get("clock_id"))
                for d in (c.get("promoted_in") or []):
                    ids.add(d.get("clock_id"))
            clocks = len([x for x in ids if x is not None])

        self._stat_rested.set_value(str(rested))
        self._stat_promoted.set_value(str(promoted))
        self._stat_clocks.set_value(str(clocks))
        self._stat_errors.set_value(str(errors))

        # Plan status pill — value + sub
        if not plan:
            self._stat_plan.set_value("— No plan —")
            self._stat_plan.set_sub("Engine hasn't ticked today")
        else:
            disp = {
                "approved":      ("✓ Approved",      GREEN),
                "discarded":     ("✕ Discarded",     RED),
                "pending":       ("⏳ Pending",      AMBER),
                "auto_applied":  ("⚙ Auto-applied",  CYAN),
            }
            label, _color = disp.get(
                status, (f"? {status}", TEXT_MUTED))
            self._stat_plan.set_value(label)
            ts = (approved_at or discarded_at
                   or plan.get("created_at") or "")
            self._stat_plan.set_sub(
                f"At {ts}" if ts else "")

        # Rebuild card grid
        self._rebuild_card_grid(categories)

    def _rebuild_card_grid(self, categories: list) -> None:
        # Clear existing cards
        for w in self._card_widgets:
            try:
                w.setParent(None)
                w.deleteLater()
            except Exception:
                pass
        self._card_widgets = []

        # Apply filter
        kept: list = []
        for c in categories:
            n_rest = len(c.get("rested") or [])
            n_out = len(c.get("promoted_out") or [])
            n_in = len(c.get("promoted_in") or [])
            total = n_rest + n_out + n_in
            empty = (total == 0)
            mode = self._filter_mode

            if mode == "rested" and n_rest == 0:
                continue
            if mode == "promoted" and (n_out + n_in) == 0:
                continue
            if mode == "has_changes" and empty:
                continue
            if empty and self._hide_empty:
                continue
            kept.append(c)

        # Build grid (3-up, variable row heights)
        COLS = 3
        GAP = 20
        scroll_w = self._scroll.viewport().width() or (WINDOW_W - 120)
        # Compute card width so 3 fit with COLS-1 gaps
        card_w = (scroll_w - GAP * (COLS - 1)) // COLS

        # Manually place cards in a flowing layout
        inner = self._grid_inner
        inner.setMinimumWidth(scroll_w)
        layout = inner.layout()
        if layout is None:
            from PyQt6.QtWidgets import QVBoxLayout as _VBL
            layout = _VBL(inner)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
        # Clear existing rows from layout
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

        # Build rows of 3 with horizontal layouts
        row_idx = 0
        cur_row_widgets: list[QWidget] = []
        for c in kept:
            n_rest = len(c.get("rested") or [])
            n_out = len(c.get("promoted_out") or [])
            n_in = len(c.get("promoted_in") or [])
            empty = (n_rest + n_out + n_in == 0)
            if empty:
                w = _EmptyCategoryCard(
                    category_id=int(c["category_id"]),
                    name=c.get("category_name") or "",
                    accent=c.get("category_color") or "#8891b8",
                    parent=inner)
            else:
                w = _CategoryCard(
                    category_id=int(c["category_id"]),
                    name=c.get("category_name") or "",
                    accent=c.get("category_color") or "#8891b8",
                    rested=c.get("rested") or [],
                    promoted_out=c.get("promoted_out") or [],
                    promoted_in=c.get("promoted_in") or [],
                    db=self._db,
                    parent=inner)
            w.resize_to_width(card_w)
            self._card_widgets.append(w)
            cur_row_widgets.append(w)
            if len(cur_row_widgets) == COLS:
                self._flush_row(layout, cur_row_widgets, GAP, scroll_w)
                cur_row_widgets = []
                row_idx += 1

        if cur_row_widgets:
            self._flush_row(layout, cur_row_widgets, GAP, scroll_w)

        if not kept:
            empty = QFrame(inner)
            empty.setFixedHeight(220)
            empty.setStyleSheet(
                f"QFrame {{ background: transparent; "
                f"border: 1px dashed {rgba('#ffffff', 0.10)}; "
                f"border-radius: 12px; }}")
            inside_l = QVBoxLayout(empty)
            inside_l.setContentsMargins(0, 60, 0, 0)
            inside_l.setSpacing(8)
            t = QLabel("No matching cards", empty)
            t.setAlignment(Qt.AlignmentFlag.AlignCenter)
            t.setFont(inter(15, QFont.Weight.Bold))
            t.setStyleSheet(
                f"color: {TEXT_SEC}; background: transparent; "
                f"border: none;")
            inside_l.addWidget(t)
            d = QLabel(
                "Either the engine has not ticked today, the plan "
                "was discarded, or your filter has excluded "
                "everything.", empty)
            d.setAlignment(Qt.AlignmentFlag.AlignCenter)
            d.setFont(inter(11))
            d.setStyleSheet(
                f"color: {TEXT_MUTED}; background: transparent; "
                f"border: none;")
            inside_l.addWidget(d)
            layout.addWidget(empty)
            self._card_widgets.append(empty)

        # Bottom padding
        layout.addStretch(1)

    def _flush_row(self, layout, widgets: list,
                    gap: int, total_w: int) -> None:
        from PyQt6.QtWidgets import QHBoxLayout as _HBL
        row = QFrame()
        row.setStyleSheet("background: transparent;")
        # Row height = tallest widget
        row_h = max((w.height() for w in widgets), default=120)
        row.setMinimumHeight(row_h)
        h = _HBL(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(gap)
        for w in widgets:
            w.setParent(row)
            h.addWidget(w, alignment=Qt.AlignmentFlag.AlignTop)
        # Pad missing columns
        for _ in range(3 - len(widgets)):
            pad = QFrame(row)
            pad.setStyleSheet("background: transparent;")
            pad.setFixedSize(widgets[0].width(), 1)
            h.addWidget(pad)
        layout.addWidget(row)
        # Spacer between rows
        spacer = QFrame()
        spacer.setFixedHeight(gap)
        spacer.setStyleSheet("background: transparent;")
        layout.addWidget(spacer)

    # ── Event handlers ─────────────────────────────────────────────────

    def _on_date_picked(self, qdate: QDate) -> None:
        try:
            d = _date(qdate.year(), qdate.month(), qdate.day())
        except Exception:
            return
        if d == self._selected_date:
            return
        self._selected_date = d
        log.info(f"date changed → {d.isoformat()}")
        self._load_state()

    def _on_refresh_clicked(self) -> None:
        # If engine present + enabled, fire a synchronous tick first
        if self._engine is not None:
            try:
                if (hasattr(self._engine, "is_enabled")
                        and self._engine.is_enabled()
                        and hasattr(self._engine, "tick")):
                    self._engine.tick()
            except Exception as exc:
                log.warning(f"engine.tick() failed: {exc}")
        self._load_state()

    def _on_filter_changed(self, mode: str) -> None:
        self._filter_mode = mode
        # Re-render using last-loaded summary (no DB hit)
        cats = (self._summary_data or {}).get("categories") or []
        self._rebuild_card_grid(cats)

    def _on_hide_empty(self, checked: bool) -> None:
        self._hide_empty = bool(checked)
        cats = (self._summary_data or {}).get("categories") or []
        self._rebuild_card_grid(cats)
