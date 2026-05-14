"""
RadioAI Studio Pro — Spot on the Go · Create Schedule (Figma 469:3)

The first sub-screen under Spot on the Go. Operator authors the day's
programming envelope here — RJ name, show name, days, time slot,
color, description, and the N editable link-name template. The sharp
per-link time + audio file + High/Low priority come next in the
Assign step (separate screen, not built yet).

Layout (1440 × 900):
  Header     y=  0..72    4-step breadcrumb
  Hero       y= 88..150   slim title + tagline
  Status row y=152..186   live N SHOWS SAVED · K TOTAL LINKS pills
  Form card  y=196..536   ADD A NEW SHOW (or EDIT: <show>) form
  Saved card y=556..846   table of every saved show with edit/delete
  Status bar y=864..900

DB:
  - sotg_shows  — header row per show (RJ, show, days, time, color, desc)
  - sotg_links  — N rows per show with link_order + link_name

# of Links is bounded [1, 12]. Link-name boxes auto-shrink width so
they fit one row regardless of count: 1..9 = 132w, 10..12 = ~98w
(formula in _LinkRow._compute_box_width).

Public signals:
  screen_requested(str) — "control_panel" / "ai_magic" /
                          "spot_on_the_go" (breadcrumb back-nav)
  studio_clicked()      — header Open Studio button
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from PyQt6.QtCore import Qt, QRectF, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QLinearGradient, QRadialGradient,
    QFont, QCursor,
)
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QHBoxLayout, QVBoxLayout,
    QLineEdit, QComboBox, QSpinBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QMessageBox, QScrollArea,
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
# Reuse chrome widgets — keeps the SOTG family visually pinned together.
from ui.spot_on_the_go_shell import (
    _HeaderLogo, _HeaderOpenStudio, _BreadcrumbLink, _BreadcrumbPill,
    _StatusPill, _PremiumBackdrop, _HeroStatusPill,
)

log = logging.getLogger("SOTGCreateSchedule")

WINDOW_W = 1440
WINDOW_H = 900
HEADER_H = 72
STATUS_H = 36


# ════════════════════════════════════════════════════════════════════════════
# Color picker — 6 swatches, click-to-select
# ════════════════════════════════════════════════════════════════════════════


COLOR_PALETTE = ["#06b6d4", "#8b5cf6", "#10b981", "#f59e0b",
                  "#ec4899", "#f43f5e"]


class _ColorPicker(QWidget):
    """Row of 6 round color swatches. Click selects one; the selected
    swatch gets a 2px ring in its own color. Emits color_changed(hex)."""

    color_changed = pyqtSignal(str)

    SWATCH = 32
    GAP = 12

    def __init__(self, initial: str = COLOR_PALETTE[0], parent=None):
        super().__init__(parent)
        self._colors = COLOR_PALETTE
        self._selected = (initial if initial in self._colors
                          else self._colors[0])
        n = len(self._colors)
        self.setFixedSize(n * self.SWATCH + (n - 1) * self.GAP, 36)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

    def selected(self) -> str:
        return self._selected

    def set_selected(self, color: str) -> None:
        if color in self._colors and color != self._selected:
            self._selected = color
            self.update()
            self.color_changed.emit(color)

    def _hit_index(self, x: int) -> int:
        # Pure linear hit-test. Snap to the nearest swatch box.
        slot = self.SWATCH + self.GAP
        idx = x // slot
        if 0 <= idx < len(self._colors):
            return int(idx)
        return -1

    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(e)
        idx = self._hit_index(int(e.position().x()))
        if idx >= 0:
            self.set_selected(self._colors[idx])

    def paintEvent(self, _e):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        for i, c in enumerate(self._colors):
            cx = i * (self.SWATCH + self.GAP)
            cy = 2
            # Ring if selected
            if c == self._selected:
                pen = QPen(QColor(c), 2)
                p.setPen(pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(QRectF(cx - 2, cy - 2,
                                       self.SWATCH + 4, self.SWATCH + 4))
            # Swatch fill (linear gradient for a hint of depth)
            grad = QLinearGradient(cx, cy, cx + self.SWATCH,
                                     cy + self.SWATCH)
            grad.setColorAt(0.0, QColor(c))
            grad.setColorAt(1.0, QColor(c).darker(110))
            p.setBrush(QBrush(grad))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QRectF(cx, cy, self.SWATCH, self.SWATCH))
        p.end()


# ════════════════════════════════════════════════════════════════════════════
# Link-name row — dynamic 1..12 input boxes with index pills
# ════════════════════════════════════════════════════════════════════════════


class _LinkBox(QFrame):
    """Single link-name input. Visual: rounded dark box + cyan index
    pill + QLineEdit for the label. Width is set externally so the
    parent row can auto-shrink the lot to fit one line at any count."""

    PILL_W_FULL = 22
    PILL_W_SLIM = 18

    def __init__(self, idx: int, default_name: str = "",
                  parent=None):
        super().__init__(parent)
        self._idx = idx
        self.setFixedHeight(36)
        self.setStyleSheet(
            f"QFrame {{ background: rgba(7,8,18,0.7); "
            f"border: 1px solid {rgba('#ffffff', 0.12)}; "
            f"border-radius: 6px; }}"
        )

        # Index pill — sized down for n>=10 by parent calling
        # set_slim_pill(True).
        self._pill = QFrame(self)
        self._pill.setStyleSheet(
            f"QFrame {{ background: {rgba(CYAN, 0.18)}; "
            f"border: 1px solid {rgba(CYAN, 0.40)}; "
            f"border-radius: 8px; }}"
        )
        self._pill_label = QLabel(str(idx), self._pill)
        self._pill_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._pill_label.setFont(inter(9, QFont.Weight.Bold))
        self._pill_label.setStyleSheet(
            f"color: {CYAN}; background: transparent; border: none;")
        self._pill.setGeometry(6, 10, self.PILL_W_FULL, 16)
        self._pill_label.setGeometry(0, 0, self.PILL_W_FULL, 16)

        self._edit = QLineEdit(default_name or f"Link {idx}", self)
        self._edit.setFont(inter(10, QFont.Weight.Medium))
        self._edit.setStyleSheet(
            f"QLineEdit {{ background: transparent; "
            f"color: {TEXT_PRI}; border: none; padding: 0; }}"
            f"QLineEdit::placeholder {{ color: {TEXT_DIM}; }}"
        )
        # Geometry set when parent calls set_box_width()
        self._set_layout(self.PILL_W_FULL, 132)

    def set_box_width(self, w: int, slim: bool = False) -> None:
        self.setFixedWidth(w)
        pw = self.PILL_W_SLIM if slim else self.PILL_W_FULL
        self._pill.setGeometry(6, 10, pw, 16)
        self._pill_label.setGeometry(0, 0, pw, 16)
        self._set_layout(pw, w)

    def _set_layout(self, pill_w: int, total_w: int) -> None:
        # Edit takes the remaining space after the pill + padding.
        edit_x = 6 + pill_w + 6
        edit_w = total_w - edit_x - 6
        self._edit.setGeometry(edit_x, 8, max(20, edit_w), 20)

    def link_name(self) -> str:
        return (self._edit.text() or "").strip()

    def set_link_name(self, name: str) -> None:
        self._edit.setText((name or "").strip() or f"Link {self._idx}")


class _LinkRow(QWidget):
    """Horizontal row of 1..12 link-name boxes that auto-shrinks per
    count so they always fit one line inside the form card.

    Public:
      set_count(n)       — rebuild for new count (clamps to 1..12)
      link_names()       — list[str] currently in the boxes
      set_link_names(xs) — populate boxes from a list (truncates >12)
    """

    MAX_LINKS = 12
    BOX_GAP = 8
    MAX_W = 132
    MIN_W = 90

    def __init__(self, available_w: int, initial_count: int = 9,
                  parent=None):
        super().__init__(parent)
        self._available_w = int(available_w)
        self.setFixedHeight(36)
        self._boxes: list[_LinkBox] = []
        self.set_count(initial_count)

    def set_count(self, n: int) -> None:
        n = max(1, min(self.MAX_LINKS, int(n)))
        # Preserve user-edited names where the index still exists.
        preserved = [b.link_name() for b in self._boxes][:n]
        for b in self._boxes:
            b.deleteLater()
        self._boxes = []
        box_w, slim = self._compute_box_width(n)
        x = 0
        for i in range(n):
            name = preserved[i] if i < len(preserved) else f"Link {i+1}"
            b = _LinkBox(i + 1, name, self)
            b.set_box_width(box_w, slim=slim)
            b.move(x, 0)
            b.show()
            self._boxes.append(b)
            x += box_w + self.BOX_GAP

    def _compute_box_width(self, n: int) -> tuple[int, bool]:
        """Same formula as the Figma footnote:
          box_w = min(132, max(90, (available_w − (n−1)·gap) / n))
        Returns (width, slim_pill). Slim pill kicks in at n ≥ 10."""
        if n <= 0:
            return self.MAX_W, False
        raw = (self._available_w - (n - 1) * self.BOX_GAP) // n
        w = max(self.MIN_W, min(self.MAX_W, raw))
        return int(w), (n >= 10)

    def link_names(self) -> list:
        return [b.link_name() or f"Link {i+1}"
                for i, b in enumerate(self._boxes)]

    def set_link_names(self, names: list) -> None:
        # Re-stash via rebuild so widths refresh too.
        self.set_count(len(names) if names else 1)
        for i, b in enumerate(self._boxes):
            if i < len(names):
                b.set_link_name(names[i])

    def count(self) -> int:
        return len(self._boxes)


# ════════════════════════════════════════════════════════════════════════════
# Public screen
# ════════════════════════════════════════════════════════════════════════════


class SOTGCreateSchedule(QWidget):
    """Create Schedule screen — Step 1 of Spot on the Go (Figma 469:3)."""

    screen_requested = pyqtSignal(str)
    studio_clicked   = pyqtSignal()

    # Saved-shows table columns (index → label, width)
    COLUMNS = [
        ("#",            36),
        ("",             32),   # color chip
        ("SHOW NAME",    230),
        ("RJ",           160),
        ("DAYS",         100),
        ("TIME SLOT",    130),
        ("LINKS",         60),
        ("INTERVAL",     110),
        ("DESCRIPTION",  220),
        ("",             54),   # edit btn
        ("",             36),   # delete btn
    ]

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self._db = db
        self._editing_id: Optional[int] = None   # show id mid-edit, else None
        self.setFixedSize(WINDOW_W, WINDOW_H)
        self.setStyleSheet(f"QWidget {{ background: {BG_BASE}; }}")

        self._backdrop = _PremiumBackdrop(self)
        self._backdrop.setGeometry(0, 0, WINDOW_W, WINDOW_H)

        self._build_header()
        self._build_hero()
        self._build_form()
        self._build_saved_shows()
        self._build_status_bar()

        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._tick_clock)
        self._clock_timer.start()
        self._tick_clock()

        # Initial pass — refresh status pills + table from DB.
        self._refresh_saved_shows()
        self._update_auto_calc()

        log.info("SOTGCreateSchedule ready (Figma 469:3)")

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

        # 4-step breadcrumb
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
        pill = _BreadcrumbPill("Create Schedule", h)
        pill.move(490, 20)

        title = QLabel("Create Schedule", h)
        title.setGeometry(660, 12, 240, 24)
        title.setFont(inter(20, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        sub = QLabel(
            "Step 1 of Spot on the Go — define your daily programming",
            h)
        sub.setGeometry(660, 38, 500, 14)
        sub.setFont(inter(10))
        sub.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

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

    # ── Hero ─────────────────────────────────────────────────────────

    def _build_hero(self) -> None:
        sigil = QLabel("✦", self)
        sigil.setGeometry(60, 88, 28, 36)
        sigil.setFont(inter(28, QFont.Weight.Bold))
        sigil.setStyleSheet(
            f"color: {CYAN_LIGHT}; background: transparent; "
            f"border: none;")
        title = QLabel("CREATE SCHEDULE", self)
        title.setGeometry(96, 88, 600, 36)
        title.setFont(inter(28, QFont.Weight.Black, letter_spacing=-0.4))
        title.setStyleSheet(
            f"color: {TEXT_PRI}; background: transparent; border: none;")
        sub = QLabel(
            "RJ name, show, day mask, time envelope, and link names. "
            "Sharp per-link times and priorities come next in Assign.",
            self)
        sub.setGeometry(60, 128, 1100, 16)
        sub.setFont(inter(12, QFont.Weight.Medium))
        sub.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent; border: none;")

        # Status pill row — populated live by _refresh_saved_shows.
        # Track the inner text label per pill so live updates don't
        # have to dig through findChildren on every refresh (which
        # was the source of an exit-127 crash on 2026-05-14 when a
        # stray setParent(None) corrupted the pill's child list).
        self._pill_shows = _HeroStatusPill(
            "0 SHOWS SAVED", CYAN, CYAN_LIGHT, self)
        self._pill_shows.move(60, 156)
        self._pill_shows_label = self._capture_pill_label(
            self._pill_shows)
        self._pill_links = _HeroStatusPill(
            "0 TOTAL LINKS", PURPLE, PURPLE_LIGHT, self)
        self._pill_links.move(60 + 178 + 10, 156)
        self._pill_links_label = self._capture_pill_label(
            self._pill_links)

    @staticmethod
    def _capture_pill_label(pill) -> QLabel:
        """Return the pill's text QLabel (the one that isn't the
        leading bullet). Used to live-update the pill on refresh
        without touching the widget tree."""
        for lbl in pill.findChildren(QLabel):
            if lbl.text() != "●":
                return lbl
        # Defensive fallback — shouldn't hit in practice.
        labels = pill.findChildren(QLabel)
        return labels[-1] if labels else QLabel(pill)

        self._hero_right = QLabel("Inline edit", self)
        self._hero_right.setGeometry(1240, 156, 180, 14)
        self._hero_right.setFont(inter(10, QFont.Weight.Medium))
        self._hero_right.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent; border: none;")
        self._hero_right.setAlignment(Qt.AlignmentFlag.AlignRight)
        h2 = QLabel("click any row to edit", self)
        h2.setGeometry(1240, 172, 180, 14)
        h2.setFont(inter(9))
        h2.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; border: none;")
        h2.setAlignment(Qt.AlignmentFlag.AlignRight)

    # ── Form card ─────────────────────────────────────────────────────

    FX = 60; FY = 196; FW = 1320; FH = 340

    def _build_form(self) -> None:
        card = QFrame(self)
        card.setGeometry(self.FX, self.FY, self.FW, self.FH)
        card.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border: 1px solid {rgba('#ffffff', 0.08)}; "
            f"border-radius: 14px; }}"
        )
        self._form_card = card

        # Left accent stripe (custom painted)
        stripe = QFrame(card)
        stripe.setGeometry(0, 0, 4, self.FH)
        stripe.setStyleSheet(f"QFrame {{ background: {CYAN_LIGHT}; "
                              f"border-top-left-radius: 14px; "
                              f"border-bottom-left-radius: 14px; "
                              f"border: none; }}")

        self._form_cap = QLabel("ADD A NEW SHOW", card)
        self._form_cap.setGeometry(24, 16, 360, 14)
        self._form_cap.setFont(
            inter(10, QFont.Weight.Bold, letter_spacing=1.4))
        self._form_cap.setStyleSheet(
            f"color: {CYAN_LIGHT}; background: transparent; "
            f"border: none;")

        help_lbl = QLabel(
            "Fill in the show details below. * required.", card)
        help_lbl.setGeometry(24, 34, 600, 12)
        help_lbl.setFont(inter(10))
        help_lbl.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; "
            f"border: none;")

        # Cancel button (only visible during edit)
        self._btn_cancel = QPushButton("✕  Cancel Edit", card)
        self._btn_cancel.setGeometry(self.FW - 24 - 140, 14, 140, 24)
        self._btn_cancel.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._btn_cancel.setFont(inter(10, QFont.Weight.Bold))
        self._btn_cancel.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {RED}; "
            f"border: 1px solid {rgba(RED, 0.4)}; border-radius: 12px; "
            f"padding: 0 8px; }}"
            f"QPushButton:hover {{ background: {rgba(RED, 0.10)}; }}"
        )
        self._btn_cancel.hide()
        self._btn_cancel.clicked.connect(self._on_cancel_edit)

        # Row 1 — RJ Name | Show Name | Days | Time Start | Time End | Color
        ROW1_Y = 64
        self._rj_name = self._build_text_field(
            card, 24,  ROW1_Y, 220, "RJ NAME *",
            placeholder="RJ Komal")
        self._show_name = self._build_text_field(
            card, 260, ROW1_Y, 260, "SHOW NAME *",
            placeholder="Bhakti Sagar")
        self._days = self._build_combo_field(
            card, 536, ROW1_Y, 160, "DAYS",
            items=["Daily", "Weekdays", "Weekends"])
        self._time_start = self._build_text_field(
            card, 712, ROW1_Y, 120, "TIME START",
            placeholder="HH:MM", mask="00:00;_")
        self._time_end = self._build_text_field(
            card, 848, ROW1_Y, 120, "TIME END",
            placeholder="HH:MM", mask="00:00;_")
        self._time_start.textChanged.connect(
            lambda _t: self._update_auto_calc())
        self._time_end.textChanged.connect(
            lambda _t: self._update_auto_calc())

        # Color picker
        color_lbl = QLabel("COLOR", card)
        color_lbl.setGeometry(984, ROW1_Y, 200, 12)
        color_lbl.setFont(
            inter(9, QFont.Weight.Bold, letter_spacing=1.0))
        color_lbl.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent; "
            f"border: none;")
        self._color_picker = _ColorPicker(parent=card)
        self._color_picker.move(984, ROW1_Y + 18)

        # Row 2 — # of Links | Description
        ROW2_Y = 144
        self._link_count = self._build_spin_field(
            card, 24, ROW2_Y, 120, "# OF LINKS",
            minimum=1, maximum=12, initial=9)
        self._link_count.valueChanged.connect(self._on_link_count_changed)
        self._description = self._build_text_field(
            card, 160, ROW2_Y, 1136, "SHOW DESCRIPTION",
            placeholder="Devotional songs + RJ Komal commentary, …")

        # Link names row
        ln_cap = QLabel("LINK NAMES  ·  9 LINKS", card)
        ln_cap.setGeometry(24, 220, 260, 12)
        ln_cap.setFont(
            inter(9, QFont.Weight.Bold, letter_spacing=1.0))
        ln_cap.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent; "
            f"border: none;")
        self._ln_cap = ln_cap
        ln_help = QLabel(
            "Auto-numbered Link 1–N by default. Click any to rename. "
            "Boxes auto-shrink for higher counts.", card)
        ln_help.setGeometry(280, 220, 900, 12)
        ln_help.setFont(inter(9))
        ln_help.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; "
            f"border: none;")

        # Available width inside the card for boxes:
        # FW - left padding 24 - right padding 24 = FW - 48 = 1272
        self._link_row = _LinkRow(
            available_w=self.FW - 48, initial_count=9, parent=card)
        self._link_row.move(24, 238)

        # Auto-calc strip (left) + Reset / Create buttons (right)
        ac = QFrame(card)
        ac.setGeometry(24, 280, 700, 36)
        ac.setStyleSheet(
            f"QFrame {{ background: {rgba(CYAN, 0.08)}; "
            f"border: 1px solid {rgba(CYAN, 0.30)}; "
            f"border-radius: 8px; }}"
        )
        sigil = QLabel("✦", ac)
        sigil.setGeometry(12, 8, 18, 20)
        sigil.setFont(inter(14, QFont.Weight.Bold))
        sigil.setStyleSheet(
            f"color: {CYAN_LIGHT}; background: transparent; "
            f"border: none;")
        self._auto_calc_lbl = QLabel(
            "Auto-calc:  —  ·  9 links", ac)
        self._auto_calc_lbl.setGeometry(36, 10, 660, 16)
        self._auto_calc_lbl.setFont(inter(11, QFont.Weight.Bold))
        self._auto_calc_lbl.setStyleSheet(
            f"color: {CYAN_LIGHT}; background: transparent; "
            f"border: none;")

        # Reset button
        self._btn_reset = QPushButton("Reset", card)
        self._btn_reset.setGeometry(self.FW - 24 - 100 - 12 - 160, 280,
                                      100, 36)
        self._btn_reset.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._btn_reset.setFont(inter(11, QFont.Weight.Bold))
        self._btn_reset.setStyleSheet(
            f"QPushButton {{ background: #1f2540; color: {TEXT_PRI}; "
            f"border: 1px solid {TEXT_MUTED}; border-radius: 8px; }}"
            f"QPushButton:hover {{ background: #2a304d; }}"
        )
        self._btn_reset.clicked.connect(self._reset_form)

        # Create / Update button
        self._btn_create = QPushButton("✚  Create Show", card)
        self._btn_create.setGeometry(self.FW - 24 - 160, 280, 160, 36)
        self._btn_create.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._btn_create.setFont(
            inter(12, QFont.Weight.Bold, letter_spacing=0.4))
        self._btn_create.setStyleSheet(
            f"QPushButton {{ background: qlineargradient("
            f"x1:0,y1:0,x2:1,y2:0, stop:0 {CYAN_LIGHT}, stop:1 {CYAN}); "
            f"color: {BG_BASE}; border: none; border-radius: 8px; }}"
            f"QPushButton:hover {{ background: {CYAN_LIGHT}; }}"
        )
        self._btn_create.clicked.connect(self._on_submit)

    def _build_text_field(self, parent, x: int, y: int, w: int,
                            label: str, placeholder: str = "",
                            mask: str = "") -> QLineEdit:
        lbl = QLabel(label, parent)
        lbl.setGeometry(x, y, w, 12)
        lbl.setFont(inter(9, QFont.Weight.Bold, letter_spacing=1.0))
        lbl.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent; "
            f"border: none;")
        edit = QLineEdit(parent)
        edit.setGeometry(x, y + 18, w, 38)
        edit.setFont(inter(12, QFont.Weight.Medium))
        if placeholder:
            edit.setPlaceholderText(placeholder)
        if mask:
            edit.setInputMask(mask)
        edit.setStyleSheet(
            f"QLineEdit {{ background: rgba(7,8,18,0.7); "
            f"color: {TEXT_PRI}; "
            f"border: 1px solid {rgba('#ffffff', 0.12)}; "
            f"border-radius: 8px; padding: 0 12px; }}"
            f"QLineEdit::placeholder {{ color: {TEXT_DIM}; }}"
            f"QLineEdit:focus {{ border-color: {rgba(CYAN, 0.5)}; }}"
        )
        return edit

    def _build_combo_field(self, parent, x: int, y: int, w: int,
                             label: str, items: list) -> QComboBox:
        lbl = QLabel(label, parent)
        lbl.setGeometry(x, y, w, 12)
        lbl.setFont(inter(9, QFont.Weight.Bold, letter_spacing=1.0))
        lbl.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent; "
            f"border: none;")
        cb = QComboBox(parent)
        cb.setGeometry(x, y + 18, w, 38)
        cb.setFont(inter(12, QFont.Weight.Medium))
        cb.addItems(items)
        cb.setStyleSheet(
            f"QComboBox {{ background: rgba(7,8,18,0.7); "
            f"color: {TEXT_PRI}; "
            f"border: 1px solid {rgba('#ffffff', 0.12)}; "
            f"border-radius: 8px; padding: 0 12px; }}"
            f"QComboBox:hover {{ border-color: {rgba(CYAN, 0.4)}; }}"
            f"QComboBox::drop-down {{ width: 24px; border: none; }}"
            f"QComboBox::down-arrow {{ image: none; }}"
            f"QComboBox QAbstractItemView {{ background: #0a0b18; "
            f"color: {TEXT_PRI}; selection-background-color: "
            f"{rgba(CYAN, 0.20)}; border: 1px solid "
            f"{rgba('#ffffff', 0.10)}; }}"
        )
        return cb

    def _build_spin_field(self, parent, x: int, y: int, w: int,
                            label: str, minimum: int, maximum: int,
                            initial: int) -> QSpinBox:
        lbl = QLabel(label, parent)
        lbl.setGeometry(x, y, w, 12)
        lbl.setFont(inter(9, QFont.Weight.Bold, letter_spacing=1.0))
        lbl.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent; "
            f"border: none;")
        sb = QSpinBox(parent)
        sb.setGeometry(x, y + 18, w, 38)
        sb.setFont(inter(12, QFont.Weight.Bold))
        sb.setRange(minimum, maximum)
        sb.setValue(initial)
        sb.setStyleSheet(
            f"QSpinBox {{ background: rgba(7,8,18,0.7); "
            f"color: {TEXT_PRI}; "
            f"border: 1px solid {rgba('#ffffff', 0.12)}; "
            f"border-radius: 8px; padding: 0 12px; }}"
            f"QSpinBox:focus {{ border-color: {rgba(CYAN, 0.5)}; }}"
        )
        return sb

    # ── Saved shows card ──────────────────────────────────────────────

    SX = 60; SY = 560; SW = 1320; SH = 290

    def _build_saved_shows(self) -> None:
        card = QFrame(self)
        card.setGeometry(self.SX, self.SY, self.SW, self.SH)
        card.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border: 1px solid {rgba('#ffffff', 0.08)}; "
            f"border-radius: 14px; }}"
        )

        self._saved_cap = QLabel("SAVED SHOWS  ·  0 TOTAL", card)
        self._saved_cap.setGeometry(24, 16, 320, 14)
        self._saved_cap.setFont(
            inter(10, QFont.Weight.Bold, letter_spacing=1.4))
        self._saved_cap.setStyleSheet(
            f"color: {PURPLE_LIGHT}; background: transparent; "
            f"border: none;")

        help_lbl = QLabel(
            "Click any row to edit inline. Confirm delete in popup.",
            card)
        help_lbl.setGeometry(24, 34, 600, 12)
        help_lbl.setFont(inter(10))
        help_lbl.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; "
            f"border: none;")

        # Table
        self._table = QTableWidget(0, len(self.COLUMNS), card)
        self._table.setGeometry(16, 56, self.SW - 32, self.SH - 64)
        self._table.setHorizontalHeaderLabels(
            [c[0] for c in self.COLUMNS])
        for i, (_, w) in enumerate(self.COLUMNS):
            self._table.setColumnWidth(i, w)
        # Stretch the DESCRIPTION column (idx 8) so the table breathes
        self._table.horizontalHeader().setSectionResizeMode(
            8, QHeaderView.ResizeMode.Stretch)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(False)
        self._table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setStyleSheet(
            f"QTableWidget {{ background: transparent; "
            f"color: {TEXT_PRI}; gridline-color: transparent; "
            f"border: none; }}"
            f"QHeaderView::section {{ background: transparent; "
            f"color: {TEXT_MUTED}; border: none; "
            f"border-bottom: 1px solid {rgba('#ffffff', 0.06)}; "
            f"padding: 6px 8px; font-weight: bold; font-size: 9px; "
            f"letter-spacing: 1.0px; text-align: left; }}"
            f"QTableWidget::item {{ padding: 4px 8px; border: none; }}"
            f"QTableWidget::item:selected {{ background: "
            f"{rgba(CYAN, 0.10)}; }}"
            f"QScrollBar:vertical {{ background: transparent; "
            f"width: 8px; }}"
            f"QScrollBar::handle:vertical {{ background: "
            f"{rgba('#252840', 0.8)}; border-radius: 4px; "
            f"min-height: 32px; }}"
            f"QScrollBar::add-line:vertical, "
            f"QScrollBar::sub-line:vertical {{ height: 0; }}"
        )
        self._table.verticalHeader().setDefaultSectionSize(36)
        # Row click → load that show into the form for inline edit
        self._table.cellClicked.connect(self._on_row_clicked)

    # ── Status bar ────────────────────────────────────────────────────

    def _build_status_bar(self) -> None:
        sb = QFrame(self)
        sb.setGeometry(0, WINDOW_H - STATUS_H, WINDOW_W, STATUS_H)
        sb.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border-top: 1px solid {rgba('#ffffff', 0.06)}; }}"
        )

        x = 12
        for txt, col in (("AUTO MODE",          PURPLE),
                          ("✦ CREATE SCHEDULE", CYAN_LIGHT),
                          ("Live Data",         GREEN)):
            p = _StatusPill(txt, col, sb)
            p.move(x, (STATUS_H - p.height()) // 2)
            x += p.width() + 8

        ver = QLabel(
            "Spot on the Go  ·  Step 1 / 4  ·  RadioAI Studio v1.0.0",
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

    # ── Form behaviour ────────────────────────────────────────────────

    def _on_link_count_changed(self, n: int) -> None:
        self._link_row.set_count(int(n))
        self._ln_cap.setText(f"LINK NAMES  ·  {int(n)} LINKS")
        self._update_auto_calc()

    def _update_auto_calc(self) -> None:
        """Refresh the auto-calc strip text from current envelope +
        link count. Defensive — invalid HH:MM just shows '—' for the
        envelope, never crashes."""
        n = int(self._link_count.value())
        env_mins = self._envelope_minutes()
        env_str = self._human_duration(env_mins) if env_mins is not None else "—"
        if env_mins is not None and n > 0:
            interval = max(1, env_mins // n)
            ints_str = f"~ {interval} min interval between links"
        else:
            ints_str = "set time slot to estimate interval"
        self._auto_calc_lbl.setText(
            f"Auto-calc:  {env_str} envelope  ·  {n} links"
            f"  ·  {ints_str}"
        )

    def _envelope_minutes(self) -> Optional[int]:
        """Convert (time_start, time_end) HH:MM strings into minutes.
        Handles overnight wraparound (e.g., 22:00 → 02:00 = 4h)."""
        ts = (self._time_start.text() or "").strip()
        te = (self._time_end.text() or "").strip()
        if len(ts) != 5 or ts[2] != ":" or len(te) != 5 or te[2] != ":":
            return None
        try:
            sh, sm = int(ts[:2]), int(ts[3:])
            eh, em = int(te[:2]), int(te[3:])
        except ValueError:
            return None
        if not (0 <= sh < 24 and 0 <= sm < 60
                and 0 <= eh < 24 and 0 <= em < 60):
            return None
        start_m = sh * 60 + sm
        end_m = eh * 60 + em
        if end_m <= start_m:
            end_m += 24 * 60  # wrap to next day
        return end_m - start_m

    @staticmethod
    def _human_duration(mins: int) -> str:
        h, m = divmod(int(mins), 60)
        if h and m:
            return f"{h}h {m:02d}m"
        if h:
            return f"{h}h 00m"
        return f"{m}m"

    def _on_submit(self) -> None:
        """Validate the form + create or update."""
        rj = (self._rj_name.text() or "").strip()
        sn = (self._show_name.text() or "").strip()
        days = self._days.currentText()
        ts = (self._time_start.text() or "").strip()
        te = (self._time_end.text() or "").strip()
        color = self._color_picker.selected()
        desc = (self._description.text() or "").strip()
        link_names = self._link_row.link_names()

        if not rj:
            QMessageBox.warning(self, "Missing RJ name",
                                  "RJ Name is required.")
            self._rj_name.setFocus()
            return
        if not sn:
            QMessageBox.warning(self, "Missing show name",
                                  "Show Name is required.")
            self._show_name.setFocus()
            return
        if self._envelope_minutes() is None:
            QMessageBox.warning(
                self, "Invalid time slot",
                "Time Start and Time End must both be HH:MM "
                "(24-hour). Example: 04:00 to 07:00.")
            return

        try:
            if self._editing_id is None:
                sid = self._db.create_sotg_show(
                    rj_name=rj, show_name=sn, days=days,
                    time_start=ts, time_end=te, color=color,
                    description=desc, link_names=link_names)
                log.info(f"SOTG show created — id={sid} '{sn}'")
            else:
                self._db.update_sotg_show(
                    self._editing_id,
                    rj_name=rj, show_name=sn, days=days,
                    time_start=ts, time_end=te, color=color,
                    description=desc, link_names=link_names)
                log.info(
                    f"SOTG show updated — id={self._editing_id} '{sn}'")
        except Exception as exc:
            QMessageBox.critical(
                self, "Save failed",
                f"Could not save show:\n\n{exc}")
            return

        self._editing_id = None
        self._reset_form()
        self._refresh_saved_shows()

    def _on_cancel_edit(self) -> None:
        self._editing_id = None
        self._reset_form()

    def _reset_form(self) -> None:
        """Clear all inputs back to placeholder defaults. Hides the
        Cancel button + flips the submit button back to 'Create'."""
        self._rj_name.clear()
        self._show_name.clear()
        self._days.setCurrentIndex(0)
        self._time_start.setText("")
        self._time_end.setText("")
        self._color_picker.set_selected(COLOR_PALETTE[0])
        self._description.clear()
        self._link_count.setValue(9)
        self._link_row.set_count(9)
        self._ln_cap.setText("LINK NAMES  ·  9 LINKS")
        self._update_auto_calc()
        # Edit mode UI
        self._editing_id = None
        self._form_cap.setText("ADD A NEW SHOW")
        self._btn_create.setText("✚  Create Show")
        self._btn_cancel.hide()

    # ── Saved shows table ─────────────────────────────────────────────

    def _refresh_saved_shows(self) -> None:
        try:
            shows = list(self._db.get_sotg_shows())
        except Exception as exc:
            log.warning(f"get_sotg_shows failed: {exc}")
            shows = []

        # Update hero pill counters via the captured inner labels.
        n = len(shows)
        total_links = sum(int(s.get("link_count") or 0) for s in shows)
        self._pill_shows_label.setText(f"{n} SHOWS SAVED")
        self._pill_links_label.setText(f"{total_links} TOTAL LINKS")
        self._saved_cap.setText(f"SAVED SHOWS  ·  {n} TOTAL")

        # Fill table
        self._table.setRowCount(n)
        for i, s in enumerate(shows):
            self._fill_row(i, s)

    def _fill_row(self, i: int, s: dict) -> None:
        def cell(text, fg=TEXT_PRI, font=None, mono_=False):
            it = QTableWidgetItem(str(text))
            it.setForeground(QColor(fg))
            it.setFont(font or (mono(11, bold=True) if mono_
                                  else inter(11, QFont.Weight.Medium)))
            return it

        # 0 — #
        self._table.setItem(i, 0, cell(i + 1, TEXT_SEC,
                                          mono(11, bold=True)))
        # 1 — color chip (drawn as a QLabel with bg)
        chip = QLabel("", self._table)
        chip.setFixedSize(22, 22)
        chip.setStyleSheet(
            f"QLabel {{ background: {s.get('color') or CYAN}; "
            f"border-radius: 6px; }}")
        self._table.setCellWidget(i, 1, self._wrap_centered(chip))
        # 2 — show name (bold)
        self._table.setItem(i, 2, cell(
            s.get("show_name") or "—", TEXT_PRI,
            inter(13, QFont.Weight.Bold)))
        # 3 — RJ
        self._table.setItem(i, 3, cell(
            s.get("rj_name") or "—", "#cbd5ff"))
        # 4 — days
        self._table.setItem(i, 4, cell(
            s.get("days") or "Daily", TEXT_SEC))
        # 5 — time slot (mono cyan)
        ts = s.get("time_start") or "—"
        te = s.get("time_end")   or "—"
        self._table.setItem(i, 5, cell(
            f"{ts} – {te}", CYAN, mono(11, bold=True)))
        # 6 — link count
        link_count = int(s.get("link_count") or 0)
        self._table.setItem(i, 6, cell(
            link_count, "#cbd5ff", mono(11, bold=True)))
        # 7 — interval
        env = self._envelope_minutes_from(
            s.get("time_start"), s.get("time_end"))
        if env is not None and link_count > 0:
            interval = max(1, env // link_count)
            self._table.setItem(i, 7, cell(
                f"~{interval} min", TEXT_SEC))
        else:
            self._table.setItem(i, 7, cell("—", TEXT_MUTED))
        # 8 — description
        self._table.setItem(i, 8, cell(
            s.get("description") or "", TEXT_SEC,
            inter(10)))
        # 9 — edit button
        edit_btn = self._build_action_button("EDIT", CYAN, CYAN_LIGHT)
        edit_btn.clicked.connect(
            lambda _=False, sid=int(s["id"]): self._on_edit(sid))
        self._table.setCellWidget(i, 9, self._wrap_centered(edit_btn))
        # 10 — delete button
        del_btn = self._build_action_button("✕", RED, "#fb7185", w=28)
        del_btn.clicked.connect(
            lambda _=False, sid=int(s["id"]),
                   name=s.get("show_name") or "": self._on_delete(sid, name))
        self._table.setCellWidget(i, 10, self._wrap_centered(del_btn))

    @staticmethod
    def _envelope_minutes_from(ts: Optional[str],
                                te: Optional[str]) -> Optional[int]:
        if not ts or not te or len(ts) < 5 or len(te) < 5:
            return None
        try:
            sh, sm = int(ts[:2]), int(ts[3:5])
            eh, em = int(te[:2]), int(te[3:5])
        except ValueError:
            return None
        if not (0 <= sh < 24 and 0 <= sm < 60
                and 0 <= eh < 24 and 0 <= em < 60):
            return None
        start_m, end_m = sh * 60 + sm, eh * 60 + em
        if end_m <= start_m:
            end_m += 24 * 60
        return end_m - start_m

    @staticmethod
    def _wrap_centered(widget: QWidget) -> QWidget:
        """Wrap a small widget in a parent so it lands centered inside
        a table cell (cellWidget alone aligns top-left)."""
        wrap = QWidget()
        wrap.setStyleSheet("QWidget { background: transparent; }")
        h = QHBoxLayout(wrap)
        h.setContentsMargins(0, 0, 0, 0); h.setSpacing(0)
        h.addStretch(1); h.addWidget(widget); h.addStretch(1)
        return wrap

    @staticmethod
    def _build_action_button(text: str, accent: str, accent_light: str,
                              w: int = 56) -> QPushButton:
        btn = QPushButton(text)
        btn.setFixedSize(w, 22)
        btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn.setFont(inter(9, QFont.Weight.Bold, letter_spacing=1.0))
        btn.setStyleSheet(
            f"QPushButton {{ background: {rgba(accent, 0.18)}; "
            f"color: {accent_light}; "
            f"border: 1px solid {rgba(accent, 0.4)}; "
            f"border-radius: 11px; padding: 0; }}"
            f"QPushButton:hover {{ background: {rgba(accent, 0.30)}; }}"
        )
        return btn

    def _on_row_clicked(self, row: int, _col: int) -> None:
        """Click anywhere in a row → load that show into the form. The
        Edit button uses the same path."""
        try:
            shows = list(self._db.get_sotg_shows())
            if 0 <= row < len(shows):
                self._on_edit(int(shows[row]["id"]))
        except Exception as exc:
            log.warning(f"row-click load failed: {exc}")

    def _on_edit(self, show_id: int) -> None:
        """Fill the form from a saved show + flip to Update mode."""
        try:
            show = self._db.get_sotg_show(int(show_id))
        except Exception as exc:
            log.warning(f"get_sotg_show failed: {exc}")
            return
        if show is None:
            return

        self._editing_id = int(show_id)
        self._rj_name.setText(show.get("rj_name") or "")
        self._show_name.setText(show.get("show_name") or "")
        # Days
        days = show.get("days") or "Daily"
        idx = self._days.findText(days)
        if idx >= 0:
            self._days.setCurrentIndex(idx)
        self._time_start.setText(show.get("time_start") or "")
        self._time_end.setText(show.get("time_end") or "")
        self._color_picker.set_selected(
            show.get("color") or COLOR_PALETTE[0])
        self._description.setText(show.get("description") or "")

        link_names = [l.get("link_name") or f"Link {i+1}"
                       for i, l in enumerate(show.get("links") or [])]
        link_names = link_names[:12] or [f"Link {i+1}" for i in range(1)]
        self._link_count.setValue(len(link_names))
        self._link_row.set_link_names(link_names)
        self._ln_cap.setText(
            f"LINK NAMES  ·  {len(link_names)} LINKS")
        self._update_auto_calc()

        # Flip UI to edit mode
        self._form_cap.setText(
            f"EDIT: {show.get('show_name') or 'Show'}")
        self._btn_create.setText("✚  Update Show")
        self._btn_cancel.show()
        self.scroll_into_view_form()

    def scroll_into_view_form(self) -> None:
        """Best-effort focus on the form when entering edit mode —
        useful when the table sits below the form on small screens."""
        try:
            self._rj_name.setFocus()
        except Exception:
            pass

    def _on_delete(self, show_id: int, name: str) -> None:
        ans = QMessageBox.question(
            self, "Delete show?",
            f"Delete the show '{name}'?\n\n"
            "This removes the show and all its link templates. "
            "Files uploaded in Assign for past plays are unaffected.",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if ans != QMessageBox.StandardButton.Yes:
            return
        try:
            self._db.delete_sotg_show(int(show_id))
        except Exception as exc:
            QMessageBox.critical(
                self, "Delete failed",
                f"Could not delete:\n\n{exc}")
            return
        # If we were editing this show, drop edit mode.
        if self._editing_id == int(show_id):
            self._editing_id = None
            self._reset_form()
        self._refresh_saved_shows()
