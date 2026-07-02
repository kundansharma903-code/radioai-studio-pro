"""
RadioAI — Force Clocks (Figma 63:521). Phase F6 + Phase F-Final S4.

Functional add/list/delete of force_clocks overrides. The scheduler's
pick_next_item resolution layer (added in S2) already consults
db.get_force_clock_for(now) — this UI is the operator-side surface for
managing those rows.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QCursor, QFont, QMouseEvent
from core import dialogs
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QDialog, QLineEdit, QComboBox, QMessageBox,
)

from ui.widgets._phase_stub import StubHeader, StubStatusBar, BORDER
from ui.widgets._tokens import (
    inter, mono, rgba,
    BG_BASE, BG_DARK, BG_PANEL, BG_CARD_DK,
    TEXT_PRI, TEXT_SEC, TEXT_MUTED, TEXT_DIM,
    CYAN, CYAN_LIGHT, PURPLE_LIGHT, GREEN, GREEN_LIGHT,
    AMBER, AMBER_LIGHT, RED, RED_LIGHT, PINK,
)

log = logging.getLogger("ForceClocks")

WINDOW_W = 1440; WINDOW_H = 900
HEADER_H = 72; STATUS_H = 36
LEFT_W = 240; RIGHT_W = 360
CENTER_W = WINDOW_W - LEFT_W - RIGHT_W
CONTENT_Y = HEADER_H
CONTENT_H = WINDOW_H - HEADER_H - STATUS_H


# ── Add-override dialog ────────────────────────────────────────────────

class _AddOverrideDialog(QDialog):
    """Minimal modal — name + clock + date + time range."""

    def __init__(self, clocks: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Force Clock Override")
        self.setModal(True)
        self.setFixedSize(420, 380)
        self.setStyleSheet(f"QDialog {{ background: {BG_PANEL}; }}")
        self._clocks = clocks
        self.result_payload: Optional[dict] = None

        v = QVBoxLayout(self); v.setContentsMargins(20, 18, 20, 18); v.setSpacing(10)

        v.addWidget(self._field_label("Override Name"))
        self._name = self._line(); self._name.setPlaceholderText("e.g. Eid Special")
        v.addWidget(self._name)

        v.addWidget(self._field_label("Target Clock"))
        self._clock = self._combo()
        for c in clocks:
            self._clock.addItem(str(c.get("name") or "—"), userData=int(c["id"]))
        v.addWidget(self._clock)

        v.addWidget(self._field_label("Date (YYYY-MM-DD)"))
        self._date = self._line()
        self._date.setText(datetime.now().strftime("%Y-%m-%d"))
        v.addWidget(self._date)

        v.addWidget(self._field_label("Time Start"))
        self._tstart = self._line(); self._tstart.setText("00:00")
        v.addWidget(self._tstart)

        v.addWidget(self._field_label("Time End"))
        self._tend = self._line(); self._tend.setText("23:59")
        v.addWidget(self._tend)

        v.addStretch()
        # Buttons
        h = QHBoxLayout(); h.setSpacing(8); h.addStretch()
        cancel = QPushButton("Cancel"); cancel.setFixedHeight(32)
        cancel.setFont(inter(10))
        cancel.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {TEXT_SEC}; "
            f"border: 1px solid {BORDER}; border-radius: 5px; padding: 0 14px; }}"
            f"QPushButton:hover {{ color: {TEXT_PRI}; }}"
        )
        cancel.clicked.connect(self.reject)
        h.addWidget(cancel)
        save = QPushButton("Save Override"); save.setFixedHeight(32)
        save.setDefault(True); save.setFont(inter(10, QFont.Weight.Bold))
        save.setStyleSheet(
            f"QPushButton {{ background: {rgba(AMBER, 0.24)}; "
            f"color: {AMBER}; "
            f"border: 1px solid {rgba(AMBER, 0.50)}; "
            f"border-radius: 5px; padding: 0 14px; }}"
            f"QPushButton:hover {{ background: {rgba(AMBER, 0.36)}; }}"
        )
        save.clicked.connect(self._on_save)
        h.addWidget(save)
        v.addLayout(h)

    def _field_label(self, text: str) -> QLabel:
        l = QLabel(text)
        l.setFont(inter(8, QFont.Weight.Bold, letter_spacing=0.6))
        l.setStyleSheet(f"color: {TEXT_DIM}; background: transparent;")
        return l

    def _line(self) -> QLineEdit:
        e = QLineEdit(); e.setFixedHeight(28); e.setFont(inter(10))
        e.setStyleSheet(
            f"QLineEdit {{ background: {BG_CARD_DK}; "
            f"color: {TEXT_PRI}; "
            f"border: 1px solid {BORDER}; "
            f"border-radius: 4px; padding: 0 8px; }}"
            f"QLineEdit:focus {{ border-color: {rgba(AMBER, 0.60)}; }}"
        )
        return e

    def _combo(self) -> QComboBox:
        c = QComboBox(); c.setFixedHeight(28); c.setFont(inter(10))
        c.setStyleSheet(
            f"QComboBox {{ background: {BG_CARD_DK}; "
            f"color: {TEXT_PRI}; "
            f"border: 1px solid {BORDER}; "
            f"border-radius: 4px; padding: 0 8px; }}"
            f"QComboBox QAbstractItemView {{ background: {BG_CARD_DK}; "
            f"color: {TEXT_PRI}; selection-background-color: {rgba(AMBER, 0.20)}; }}"
        )
        return c

    def _on_save(self):
        name = self._name.text().strip()
        clock_id = self._clock.currentData()
        date = self._date.text().strip()
        ts = self._tstart.text().strip() or "00:00"
        te = self._tend.text().strip() or "23:59"
        if not name or not clock_id or not date:
            dialogs.warning(self, "Missing fields",
                                "Name, target clock, and date are required.")
            return
        # Cheap date validation — must be YYYY-MM-DD
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            dialogs.warning(self, "Invalid date",
                                "Date must be YYYY-MM-DD (e.g. 2026-08-15).")
            return
        self.result_payload = {
            "name": name, "clock_id": int(clock_id),
            "override_date": date, "time_start": ts, "time_end": te,
        }
        self.accept()


# ── Override row (clickable) ───────────────────────────────────────────

class _OverrideRow(QFrame):
    clicked = pyqtSignal(int)

    def __init__(self, override: dict, is_selected: bool, parent=None):
        super().__init__(parent)
        self._override = dict(override)
        self._selected = bool(is_selected)
        self.setFixedHeight(56)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        bg = rgba(AMBER, 0.16) if self._selected else BG_CARD_DK
        border = rgba(AMBER, 0.40) if self._selected else BORDER
        self.setStyleSheet(
            f"QFrame {{ background: {bg}; "
            f"border: 1px solid {border}; border-radius: 5px; }}"
        )
        v = QVBoxLayout(self); v.setContentsMargins(8, 4, 8, 4); v.setSpacing(0)
        n = QLabel(str(override.get("name") or "—"))
        n.setFont(inter(10, QFont.Weight.DemiBold))
        n.setStyleSheet(
            f"color: {AMBER if is_selected else TEXT_SEC}; "
            f"background: transparent;")
        v.addWidget(n)
        d = QLabel(f"{override['override_date']}  ·  "
                   f"{override.get('time_start', '00:00')}–"
                   f"{override.get('time_end', '23:59')}")
        d.setFont(mono(8, bold=False))
        d.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        v.addWidget(d)

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(int(self._override.get("id", 0)))


# ── Top-level ──────────────────────────────────────────────────────────

class ForceClocks(QWidget):
    breadcrumb_clicked = pyqtSignal(str)
    studio_clicked     = pyqtSignal()

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self._db = db
        self.setFixedSize(WINDOW_W, WINDOW_H)
        self.setStyleSheet(f"QWidget {{ background: {BG_BASE}; }}")
        self._selected_id: Optional[int] = None
        self._rows: list[_OverrideRow] = []

        h = StubHeader("Force Clocks", "Force Clocks",
                       active_color=AMBER, parent=self)
        h.setGeometry(0, 0, WINDOW_W, HEADER_H)
        h.control_panel_clicked.connect(
            lambda: self.breadcrumb_clicked.emit("control_panel"))
        h.scheduling_clicked.connect(
            lambda: self.breadcrumb_clicked.emit("scheduling_hub"))
        h.studio_clicked.connect(self.studio_clicked.emit)

        # Left — overrides list
        left = QFrame(self)
        left.setGeometry(0, CONTENT_Y, LEFT_W, CONTENT_H)
        left.setStyleSheet(
            f"QFrame {{ background: {BG_DARK}; "
            f"border-right: 1px solid {BORDER}; }}"
        )
        lv = QVBoxLayout(left); lv.setContentsMargins(10, 14, 10, 14); lv.setSpacing(6)

        head_row = QHBoxLayout()
        self._count_label = QLabel("0 Overrides")
        self._count_label.setFont(inter(8, QFont.Weight.Black, letter_spacing=1.4))
        self._count_label.setStyleSheet(f"color: {AMBER}; background: transparent;")
        head_row.addWidget(self._count_label); head_row.addStretch()
        add_btn = QPushButton("+ Add New")
        add_btn.setFixedHeight(24)
        add_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        add_btn.setFont(inter(9, QFont.Weight.DemiBold))
        add_btn.setStyleSheet(
            f"QPushButton {{ background: {rgba(GREEN, 0.16)}; "
            f"color: {GREEN_LIGHT}; "
            f"border: 1px solid {rgba(GREEN, 0.40)}; "
            f"border-radius: 4px; padding: 0 8px; }}"
            f"QPushButton:hover {{ background: {rgba(GREEN, 0.26)}; }}"
        )
        add_btn.clicked.connect(self._on_add_override)
        head_row.addWidget(add_btn)
        lv.addLayout(head_row)

        self._rows_box = QFrame(); self._rows_box.setStyleSheet("background: transparent;")
        self._rows_layout = QVBoxLayout(self._rows_box)
        self._rows_layout.setContentsMargins(0, 4, 0, 4); self._rows_layout.setSpacing(4)
        lv.addWidget(self._rows_box, 1)
        lv.addStretch()
        delete_btn = QPushButton("✗ Delete Override")
        delete_btn.setFixedHeight(28)
        delete_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        delete_btn.setFont(inter(10, QFont.Weight.DemiBold))
        delete_btn.setStyleSheet(
            f"QPushButton {{ background: {rgba(RED, 0.18)}; "
            f"color: {RED_LIGHT}; "
            f"border: 1px solid {rgba(RED, 0.40)}; "
            f"border-radius: 5px; padding: 0 12px; text-align: left; }}"
            f"QPushButton:hover {{ background: {rgba(RED, 0.30)}; }}"
        )
        delete_btn.clicked.connect(self._on_delete_override)
        lv.addWidget(delete_btn)

        # Center — month label + helpful note
        center = QFrame(self)
        center.setGeometry(LEFT_W, CONTENT_Y, CENTER_W, CONTENT_H)
        center.setStyleSheet(f"QFrame {{ background: {BG_BASE}; "
                             f"border-right: 1px solid {BORDER}; }}")
        cv = QVBoxLayout(center); cv.setContentsMargins(20, 14, 20, 14); cv.setSpacing(8)
        title = QLabel(f"FORCE CLOCK OVERRIDES — "
                       f"{datetime.now().strftime('%B %Y').upper()}")
        title.setFont(inter(11, QFont.Weight.Black, letter_spacing=1.0))
        title.setStyleSheet(f"color: {AMBER}; background: transparent;")
        cv.addWidget(title)
        explain = QLabel(
            "Overrides win over the regular auto_schedule grid for the "
            "specific (date, hour) window. The scheduler's "
            "pick_next_item resolves through these first.\n\n"
            "+ Add New: define a new override (name, clock, date, "
            "time range).\n"
            "Click any override on the left to select it; the right "
            "panel shows its details. Delete Override removes the "
            "selected row."
        )
        explain.setFont(inter(10)); explain.setWordWrap(True)
        explain.setStyleSheet(
            f"QLabel {{ background: {BG_CARD_DK}; "
            f"color: {TEXT_SEC}; "
            f"border: 1px solid {BORDER}; "
            f"border-radius: 8px; padding: 18px; }}"
        )
        cv.addWidget(explain)
        cv.addStretch()

        # Right — selected override details
        right = QFrame(self)
        right.setGeometry(LEFT_W + CENTER_W, CONTENT_Y, RIGHT_W, CONTENT_H)
        right.setStyleSheet(f"QFrame {{ background: {BG_PANEL}; }}")
        rv = QVBoxLayout(right); rv.setContentsMargins(14, 14, 14, 14); rv.setSpacing(8)
        title2 = QLabel("OVERRIDE DETAIL")
        title2.setFont(inter(8, QFont.Weight.Black, letter_spacing=1.4))
        title2.setStyleSheet(f"color: {AMBER}; background: transparent;")
        rv.addWidget(title2)
        self._detail_kv: dict[str, QLabel] = {}
        for label in ("Override Name", "Target Clock", "Date",
                      "Time Start", "Time End"):
            f, val_lbl = self._kv(label, "—")
            rv.addWidget(f); self._detail_kv[label] = val_lbl
        rv.addStretch()

        sb = StubStatusBar("Force Clocks", parent=self)
        sb.setGeometry(0, WINDOW_H - STATUS_H, WINDOW_W, STATUS_H)

        self._refresh()
        log.info("ForceClocks ready (Figma 63:521)")

    # ── Builders ─────────────────────────────────────────────────────────

    def _kv(self, k: str, v: str) -> tuple[QFrame, QLabel]:
        f = QFrame(); f.setFixedHeight(34)
        f.setStyleSheet(f"QFrame {{ background: {BG_CARD_DK}; "
                        f"border: 1px solid {BORDER}; border-radius: 5px; }}")
        v_l = QVBoxLayout(f); v_l.setContentsMargins(10, 4, 10, 4); v_l.setSpacing(0)
        c = QLabel(k); c.setFont(inter(7, QFont.Weight.Medium, letter_spacing=0.6))
        c.setStyleSheet(f"color: {TEXT_DIM}; background: transparent;")
        d = QLabel(v); d.setFont(inter(10, QFont.Weight.Medium))
        d.setStyleSheet(f"color: {TEXT_SEC}; background: transparent;")
        v_l.addWidget(c); v_l.addWidget(d)
        return f, d

    # ── Data ─────────────────────────────────────────────────────────────

    def _refresh(self) -> None:
        try:
            overrides = [{k: r[k] for k in r.keys()} for r in self._db.list_force_clocks()]
        except Exception as exc:
            log.warning(f"list_force_clocks failed: {exc}")
            overrides = []
        # Clear existing rows
        for r in self._rows:
            r.setParent(None); r.deleteLater()
        self._rows.clear()
        self._count_label.setText(
            f"{len(overrides)} Override{'s' if len(overrides) != 1 else ''}")
        if overrides and self._selected_id is None:
            self._selected_id = int(overrides[0]["id"])
        # Build rows
        for ov in overrides:
            row = _OverrideRow(ov, is_selected=(int(ov["id"]) == self._selected_id))
            row.clicked.connect(self._on_select_override)
            self._rows_layout.addWidget(row)
            self._rows.append(row)
        # Right-panel detail
        cur = next((o for o in overrides if int(o["id"]) == (self._selected_id or 0)), None)
        if cur is None:
            for k, v in self._detail_kv.items():
                v.setText("—")
        else:
            try:
                target_clock = self._db.get_clock(int(cur.get("clock_id") or 0))
            except Exception:
                target_clock = None
            self._detail_kv["Override Name"].setText(str(cur.get("name") or "—"))
            self._detail_kv["Target Clock"].setText(
                target_clock["name"] if target_clock else f"#{cur.get('clock_id')}")
            self._detail_kv["Date"].setText(str(cur.get("override_date") or "—"))
            self._detail_kv["Time Start"].setText(str(cur.get("time_start") or "—"))
            self._detail_kv["Time End"].setText(str(cur.get("time_end") or "—"))

    # ── Handlers ─────────────────────────────────────────────────────────

    def _on_select_override(self, override_id: int) -> None:
        self._selected_id = int(override_id)
        self._refresh()

    def _on_add_override(self) -> None:
        clocks = [{k: c[k] for k in c.keys()} for c in self._db.get_all_clocks()]
        if not clocks:
            dialogs.info(self, "No clocks",
                                    "Create a clock first via Clock Editor.")
            return
        dlg = _AddOverrideDialog(clocks, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.result_payload:
            return
        p = dlg.result_payload
        try:
            new_id = self._db.add_force_clock(
                p["name"], p["clock_id"],
                override_date=p["override_date"],
                time_start=p["time_start"],
                time_end=p["time_end"])
            log.info(f"[force-clocks] added id={new_id} {p['name']!r} "
                     f"date={p['override_date']} clock_id={p['clock_id']}")
            self._selected_id = new_id
        except Exception as exc:
            log.warning(f"add_force_clock failed: {exc}")
            dialogs.warning(self, "Add failed", str(exc))
            return
        self._refresh()

    def _on_delete_override(self) -> None:
        if self._selected_id is None:
            return
        if not dialogs.confirm(
                self, "Delete override?",
                "Delete this force_clock override?",
                danger=True, yes_label="Delete"):
            return
        try:
            self._db.delete_force_clock(self._selected_id)
            log.info(f"[force-clocks] deleted id={self._selected_id}")
        except Exception as exc:
            log.warning(f"delete_force_clock failed: {exc}")
            return
        self._selected_id = None
        self._refresh()
