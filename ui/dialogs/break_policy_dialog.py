"""
RadioAI — Break Policy dialog (Spots & Commercials → ⚙ Break Settings).

Operator-approved design 2026-07-04. One place to control the ad
discipline valve:

    Policy   ON  → due spots consolidate into fixed break windows,
                   the hourly ad budget is enforced (overflow defers
                   to the next hour), same-ad-category clients are
                   interleaved (competitive separation).
           OFF  → the ORIGINAL per-campaign firing, byte-identical.

    Windows      15,30,45 (comma minutes-of-hour, editable)
    Max ads/hour mm:ss budget (community-radio guideline, editable)

Settings persist via the Settings singleton; Studio reads them live —
no restart needed (the valve checks the toggle on every spot_due and
the meter re-reads the budget every second).
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCursor, QFont
from PyQt6.QtWidgets import (
    QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QSpinBox, QVBoxLayout, QWidget,
)

from core import dialogs
from core.break_policy import parse_windows
from core.settings import Settings
from ui.dialogs.base_dialog import BaseDialog
from ui.widgets._tokens import (
    inter, rgba,
    BG_CARD, BG_ELEVATED,
    TEXT_PRI, TEXT_SEC, TEXT_MUTED,
    CYAN, CYAN_LIGHT, GREEN, GREEN_LIGHT, AMBER_LIGHT, RED, RED_LIGHT,
)

log = logging.getLogger("BreakPolicyDialog")


def _lbl(text: str, size: int = 10, color: str = TEXT_SEC,
         bold: bool = False) -> QLabel:
    l = QLabel(text)
    l.setFont(inter(size, QFont.Weight.Bold if bold
                    else QFont.Weight.Medium))
    l.setStyleSheet(f"color: {color}; background: transparent;")
    l.setWordWrap(True)
    return l


class BreakPolicyDialog(BaseDialog):
    """Master toggle + window minutes + hourly budget (editable)."""

    def __init__(self, db, parent=None):
        self._db = db
        super().__init__(target_size=(560, 500), parent=parent)

    # ── Header ────────────────────────────────────────────────────────

    def _build_header(self) -> QWidget:
        f = QFrame()
        f.setStyleSheet(
            f"QFrame {{ background: #0d0f1e; "
            f"border-bottom: 1px solid {rgba('#ffffff', 0.06)}; }}")
        h = QHBoxLayout(f)
        h.setContentsMargins(20, 12, 12, 12)
        h.setSpacing(10)
        box = QWidget()
        box.setStyleSheet("background: transparent;")
        tv = QVBoxLayout(box)
        tv.setContentsMargins(0, 0, 0, 0)
        tv.setSpacing(2)
        title = QLabel("BREAK POLICY")
        title.setFont(inter(16, QFont.Weight.Black, letter_spacing=0.5))
        title.setStyleSheet(
            f"color: {TEXT_PRI}; background: transparent;")
        sub = QLabel("Ad discipline — windows · hourly budget · "
                     "competitive separation")
        sub.setFont(inter(10))
        sub.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent;")
        tv.addWidget(title)
        tv.addWidget(sub)
        h.addWidget(box)
        h.addStretch()
        x = QPushButton("✕")
        x.setFixedSize(28, 28)
        x.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        x.setFont(inter(13, QFont.Weight.Bold))
        x.setStyleSheet(
            f"QPushButton {{ background: #1c1f38; color: {TEXT_SEC}; "
            f"border: none; border-radius: 6px; }}"
            f"QPushButton:hover {{ background: {rgba(RED, 0.20)}; "
            f"color: {RED_LIGHT}; }}")
        x.clicked.connect(self.reject)
        h.addWidget(x)
        return f

    # ── Content ───────────────────────────────────────────────────────

    def _build_content(self) -> QWidget:
        s = Settings()
        body = QFrame()
        body.setStyleSheet("background: transparent;")
        v = QVBoxLayout(body)
        v.setContentsMargins(22, 14, 22, 10)
        v.setSpacing(10)

        self._chk = QCheckBox("  Break Policy ENABLED")
        self._chk.setFont(inter(12, QFont.Weight.Bold))
        self._chk.setChecked(s.get_bool("break_policy_enabled", False))
        self._chk.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._chk.setStyleSheet(
            f"QCheckBox {{ color: {TEXT_PRI}; background: transparent; "
            f"spacing: 8px; }}"
            f"QCheckBox::indicator {{ width: 20px; height: 20px; "
            f"border-radius: 5px; border: 1px solid {rgba(GREEN, 0.5)}; "
            f"background: {BG_CARD}; }}"
            f"QCheckBox::indicator:checked {{ background: {GREEN}; }}")
        v.addWidget(self._chk)
        v.addWidget(_lbl(
            "ON — due spots wait for the next break window, the hourly "
            "budget is enforced, and same-ad-category clients never "
            "air back-to-back.  OFF — the original per-campaign "
            "firing, unchanged.", 9, TEXT_MUTED))

        v.addSpacing(6)
        v.addWidget(_lbl("BREAK WINDOWS  ·  minutes of every hour", 9,
                         CYAN_LIGHT, bold=True))
        self._windows = QLineEdit(
            s.get("break_policy_windows", "15,30,45"))
        self._windows.setFont(inter(12))
        self._windows.setStyleSheet(
            f"QLineEdit {{ background: {BG_ELEVATED}; color: {TEXT_PRI}; "
            f"border: 1px solid #1c1f38; border-radius: 6px; "
            f"padding: 6px 10px; }}"
            f"QLineEdit:focus {{ border: 1px solid {rgba(CYAN, 0.5)}; }}")
        v.addWidget(self._windows)
        v.addWidget(_lbl("e.g. 15,30,45 = three breaks per hour. All "
                         "spots due since the last window air together "
                         "there, back-to-back.", 9, TEXT_MUTED))

        v.addSpacing(6)
        v.addWidget(_lbl("MAX ADS PER HOUR  ·  compliance budget", 9,
                         AMBER_LIGHT, bold=True))
        row = QHBoxLayout()
        row.setSpacing(6)
        max_s = max(60, int(s.get_int(
            "break_policy_max_ad_seconds_hour", 660)))
        self._min_spin = QSpinBox()
        self._min_spin.setRange(1, 59)
        self._min_spin.setValue(max_s // 60)
        self._sec_spin = QSpinBox()
        self._sec_spin.setRange(0, 59)
        self._sec_spin.setValue(max_s % 60)
        for sp in (self._min_spin, self._sec_spin):
            sp.setFont(inter(12, QFont.Weight.Bold))
            sp.setFixedWidth(72)
            sp.setStyleSheet(
                f"QSpinBox {{ background: {BG_ELEVATED}; "
                f"color: {TEXT_PRI}; border: 1px solid #1c1f38; "
                f"border-radius: 6px; padding: 4px 6px; }}")
        row.addWidget(self._min_spin)
        row.addWidget(_lbl("min", 11, TEXT_SEC))
        row.addWidget(self._sec_spin)
        row.addWidget(_lbl("sec", 11, TEXT_SEC))
        row.addStretch(1)
        v.addLayout(row)
        v.addWidget(_lbl("Spots that would cross this budget DEFER to "
                         "the next hour's first window — never "
                         "dropped. Studio's bottom-bar meter tracks "
                         "the number live.", 9, TEXT_MUTED))
        v.addStretch(1)
        return body

    # ── Footer ────────────────────────────────────────────────────────

    def _build_footer(self) -> QWidget:
        f = QFrame()
        f.setStyleSheet(
            f"QFrame {{ background: #0d0f1e; "
            f"border-top: 1px solid {rgba('#ffffff', 0.06)}; }}")
        h = QHBoxLayout(f)
        h.setContentsMargins(20, 10, 16, 10)
        h.setSpacing(8)
        h.addStretch()
        cancel = QPushButton("Cancel")
        cancel.setFixedHeight(34)
        cancel.setMinimumWidth(96)
        cancel.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        cancel.setFont(inter(11, QFont.Weight.Medium))
        cancel.setStyleSheet(
            f"QPushButton {{ background: #1c1f38; color: {TEXT_SEC}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; "
            f"border-radius: 7px; padding: 0 18px; }}"
            f"QPushButton:hover {{ background: #252848; "
            f"color: {TEXT_PRI}; }}")
        cancel.clicked.connect(self.reject)
        h.addWidget(cancel)
        save = QPushButton("✓  Save Policy")
        save.setFixedHeight(34)
        save.setMinimumWidth(140)
        save.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        save.setFont(inter(11, QFont.Weight.Bold))
        save.setStyleSheet(
            f"QPushButton {{ background: {GREEN}; color: #04141a; "
            f"border: none; border-radius: 7px; }}"
            f"QPushButton:hover {{ background: {GREEN_LIGHT}; }}")
        save.clicked.connect(self._on_save)
        h.addWidget(save)
        return f

    # ── Save ──────────────────────────────────────────────────────────

    def _on_save(self) -> None:
        windows = parse_windows(self._windows.text())
        total = self._min_spin.value() * 60 + self._sec_spin.value()
        s = Settings()
        s.set("break_policy_enabled",
              "1" if self._chk.isChecked() else "0")
        s.set("break_policy_windows",
              ",".join(str(w) for w in windows))
        s.set("break_policy_max_ad_seconds_hour", str(int(total)))
        log.info(f"[break-policy] saved: enabled="
                 f"{self._chk.isChecked()} windows={windows} "
                 f"max={total}s")
        dialogs.info(
            self, "Break Policy saved",
            f"Policy: {'ON' if self._chk.isChecked() else 'OFF'}\n"
            f"Windows: "
            f"{', '.join(':' + str(w).zfill(2) for w in windows)}\n"
            f"Budget: {total // 60}:{total % 60:02d} per hour\n\n"
            f"Applies live — no restart needed.")
        self.accept()
