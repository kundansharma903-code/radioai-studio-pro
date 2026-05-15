"""
Sister Group Picker dialog — operator picks 2-5 categories from the
Songs Library to form (or edit) a sister group.

Used by the Scheduling Automation Hub's:
  • "+ Create New Sister Group" CTA
  • "✎ Edit" button on each existing group card

Per operator's locked decisions:
  Q-A  cap = 5 categories per group
  Q-B  no group naming required — groups identified by member set
  D3   symmetric — adding a category here means it pools with all
       other members of the group

Visual: modal dialog, dark-themed, list of categories with
checkboxes. Save button enabled when 2-5 selected. Categories already
in OTHER groups are listed but disabled (with a "(in Group N)" hint)
so the operator sees why they can't pick them.
"""

from __future__ import annotations

import logging
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QCursor, QFont
from core import dialogs
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QWidget, QMessageBox,
)

from ui.widgets._tokens import (
    inter, mono, rgba,
    BG_BASE, BG_PANEL,
    TEXT_PRI, TEXT_SEC, TEXT_MUTED, TEXT_DIM,
    PURPLE, PURPLE_LIGHT, CYAN, GREEN, RED,
)

log = logging.getLogger("SisterGroupPicker")

RED_LIGHT = "#fb7185"
GROUP_CAP = 5
GROUP_MIN = 2


# ────────────────────────────────────────────────────────────────────────────
# Category row checkbox widget
# ────────────────────────────────────────────────────────────────────────────


class _CategoryRow(QFrame):
    """One row in the picker list — checkbox + color dot + name +
    optional disabled-because hint. Emits toggled() with the category
    id when the operator clicks."""

    toggled = pyqtSignal(int, bool)    # category_id, is_checked

    HEIGHT = 44

    def __init__(self, *, category_id: int, name: str, color: str,
                 song_count: int, disabled_hint: str = "",
                 checked: bool = False, parent=None):
        super().__init__(parent)
        self._cid = int(category_id)
        self._checked = bool(checked)
        self._disabled = bool(disabled_hint)
        self._color = color or CYAN
        self.setFixedHeight(self.HEIGHT)
        self.setCursor(
            QCursor(Qt.CursorShape.PointingHandCursor
                     if not self._disabled
                     else Qt.CursorShape.ForbiddenCursor))
        self._render_frame()

        # Checkbox visual (paints in _render_frame)
        self._box = QFrame(self)
        self._box.setGeometry(16, 14, 16, 16)
        self._render_box()

        # Color dot
        dot = QFrame(self)
        dot.setGeometry(48, 18, 10, 10)
        dot.setStyleSheet(
            f"background: {self._color}; border-radius: 5px; "
            f"border: none;")

        # Name
        name_color = TEXT_MUTED if self._disabled else TEXT_PRI
        name_lbl = QLabel(name, self)
        name_lbl.setGeometry(68, 6, 360, 18)
        name_lbl.setFont(inter(13, QFont.Weight.Bold))
        name_lbl.setStyleSheet(
            f"color: {name_color}; background: transparent; "
            f"border: none;")

        # Sub-line: song count + disabled hint
        sub_color = TEXT_MUTED
        if self._disabled:
            sub_text = f"{song_count} songs  ·  {disabled_hint}"
        else:
            sub_text = f"{song_count} songs"
        sub_lbl = QLabel(sub_text, self)
        sub_lbl.setGeometry(68, 24, 360, 14)
        sub_lbl.setFont(inter(10, QFont.Weight.Medium,
                                italic=self._disabled))
        sub_lbl.setStyleSheet(
            f"color: {sub_color}; background: transparent; "
            f"border: none;")

    def _render_frame(self) -> None:
        if self._checked:
            self.setStyleSheet(
                f"QFrame {{ background: {rgba(PURPLE, 0.10)}; "
                f"border: 1px solid {rgba(PURPLE, 0.45)}; "
                f"border-radius: 8px; }}"
            )
        elif self._disabled:
            self.setStyleSheet(
                f"QFrame {{ background: transparent; "
                f"border: 1px solid {rgba('#ffffff', 0.05)}; "
                f"border-radius: 8px; }}"
            )
        else:
            self.setStyleSheet(
                f"QFrame {{ background: transparent; "
                f"border: 1px solid {rgba('#ffffff', 0.10)}; "
                f"border-radius: 8px; }}"
            )

    def _render_box(self) -> None:
        if self._checked:
            self._box.setStyleSheet(
                f"QFrame {{ background: {PURPLE}; "
                f"border: 1px solid {PURPLE}; border-radius: 4px; }}"
            )
        else:
            stroke = (rgba(TEXT_SEC, 0.30)
                       if self._disabled
                       else rgba(TEXT_SEC, 0.50))
            self._box.setStyleSheet(
                f"QFrame {{ background: transparent; "
                f"border: 1px solid {stroke}; border-radius: 4px; }}"
            )

    def is_checked(self) -> bool:
        return self._checked

    def set_checked(self, v: bool) -> None:
        if self._disabled:
            return
        new = bool(v)
        if new == self._checked:
            return
        self._checked = new
        self._render_frame()
        self._render_box()
        self.toggled.emit(self._cid, self._checked)

    def category_id(self) -> int:
        return self._cid

    def mousePressEvent(self, e):
        if (e.button() == Qt.MouseButton.LeftButton
                and not self._disabled):
            self.set_checked(not self._checked)
        super().mousePressEvent(e)


# ────────────────────────────────────────────────────────────────────────────
# Dialog
# ────────────────────────────────────────────────────────────────────────────


class SisterGroupPickerDialog(QDialog):
    """Modal picker. After Save:
      ``self.result_category_ids`` is the list of selected ids.
      ``self.exec()`` returns QDialog.Accepted on Save, Rejected on
      Cancel (per Qt convention)."""

    def __init__(self, db, *, edit_group_id: Optional[int] = None,
                 parent=None):
        super().__init__(parent)
        self._db = db
        self._edit_group_id = edit_group_id
        self.result_category_ids: list[int] = []
        self._selected: set[int] = set()
        # Track which categories are members of OTHER groups (so we
        # can disable + annotate them)
        self._other_group_owner: dict[int, int] = {}

        if edit_group_id is None:
            self.setWindowTitle("Create Sister Group")
        else:
            self.setWindowTitle(f"Edit Sister Group {edit_group_id}")
        self.setModal(True)
        self.setFixedSize(560, 640)
        self.setStyleSheet(f"QDialog {{ background: {BG_BASE}; }}")

        self._build_layout()
        self._populate_rows()
        self._refresh_save_state()

    def _build_layout(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 16, 20, 16); v.setSpacing(12)

        # Title
        title_text = ("Create Sister Group"
                       if self._edit_group_id is None
                       else f"Edit Sister Group {self._edit_group_id}")
        title = QLabel(title_text)
        title.setFont(inter(18, QFont.Weight.Bold, letter_spacing=-0.2))
        title.setStyleSheet(
            f"color: {TEXT_PRI}; background: transparent;")
        v.addWidget(title)

        sub = QLabel(
            f"Pick {GROUP_MIN}–{GROUP_CAP} categories whose songs "
            "should pool for rotation variety.")
        sub.setFont(inter(11, QFont.Weight.Medium))
        sub.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent;")
        sub.setWordWrap(True)
        v.addWidget(sub)

        # Scroll area for category rows
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(
            f"QScrollArea {{ background: {BG_PANEL}; "
            f"border: 1px solid {rgba('#ffffff', 0.10)}; "
            f"border-radius: 10px; }}"
            f"QScrollBar:vertical {{ background: {BG_PANEL}; "
            f"width: 8px; border-radius: 4px; }}"
            f"QScrollBar::handle:vertical {{ background: "
            f"{rgba('#ffffff', 0.20)}; border-radius: 4px; }}"
            f"QScrollBar::add-line:vertical, "
            f"QScrollBar::sub-line:vertical {{ height: 0; }}"
        )
        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        self._rows_layout = QVBoxLayout(inner)
        self._rows_layout.setContentsMargins(12, 12, 12, 12)
        self._rows_layout.setSpacing(6)
        self._rows_layout.addStretch()
        self._scroll.setWidget(inner)
        self._rows_inner = inner
        self._rows: list[_CategoryRow] = []
        v.addWidget(self._scroll, 1)

        # Counter + buttons row
        bottom = QHBoxLayout()
        bottom.setSpacing(12)
        self._counter_lbl = QLabel("0 / 5 selected")
        self._counter_lbl.setFont(inter(11, QFont.Weight.Bold))
        self._counter_lbl.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent;")
        bottom.addWidget(self._counter_lbl)
        bottom.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedSize(110, 36)
        cancel_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        cancel_btn.setFont(inter(11, QFont.Weight.Bold))
        cancel_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {TEXT_SEC}; "
            f"border: 1px solid {rgba('#ffffff', 0.10)}; "
            f"border-radius: 8px; }}"
            f"QPushButton:hover {{ color: {TEXT_PRI}; }}"
        )
        cancel_btn.clicked.connect(self.reject)
        bottom.addWidget(cancel_btn)

        self._save_btn = QPushButton("Save")
        self._save_btn.setFixedSize(130, 36)
        self._save_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._save_btn.setFont(inter(12, QFont.Weight.Bold))
        self._save_btn.clicked.connect(self._on_save)
        bottom.addWidget(self._save_btn)

        v.addLayout(bottom)

    def _populate_rows(self) -> None:
        """Pull every category from DB, mark each row as enabled /
        disabled-because-in-another-group / pre-selected (edit mode)."""
        try:
            cats = self._db._conn().execute(
                "SELECT c.id, c.name, c.color, "
                "       COUNT(s.id) AS song_count "
                "FROM categories c "
                "LEFT JOIN songs s ON s.category_id = c.id "
                "  AND s.is_enabled = 1 "
                "GROUP BY c.id "
                "ORDER BY c.display_order ASC, c.name ASC"
            ).fetchall()
        except Exception as exc:
            log.warning(f"populate_rows: category fetch failed: {exc}")
            cats = []

        # Find which categories are members of each group
        try:
            members = self._db._conn().execute(
                "SELECT group_id, category_id FROM sister_group_members"
            ).fetchall()
        except Exception:
            members = []
        # Map cid → owning group_id
        for m in members:
            self._other_group_owner[int(m["category_id"])] = int(
                m["group_id"])

        # Pre-select members of the edit group (if any)
        if self._edit_group_id is not None:
            current_members = [int(m["category_id"]) for m in members
                                if int(m["group_id"]) == int(
                                    self._edit_group_id)]
            self._selected = set(current_members)

        # Strip the trailing addStretch so rows insert before it
        if self._rows_layout.count():
            last_idx = self._rows_layout.count() - 1
            item = self._rows_layout.itemAt(last_idx)
            self._rows_layout.removeItem(item)

        for c in cats:
            cid = int(c["id"])
            owner = self._other_group_owner.get(cid)
            disabled_hint = ""
            if owner and owner != self._edit_group_id:
                disabled_hint = f"already in Group {owner}"
            row = _CategoryRow(
                category_id=cid,
                name=c["name"] or "(unnamed)",
                color=c["color"] or CYAN,
                song_count=int(c["song_count"] or 0),
                disabled_hint=disabled_hint,
                checked=(cid in self._selected),
                parent=self._rows_inner)
            row.toggled.connect(self._on_row_toggled)
            self._rows_layout.addWidget(row)
            self._rows.append(row)
        # Re-add stretch at end
        self._rows_layout.addStretch()

    def _on_row_toggled(self, cid: int, checked: bool) -> None:
        if checked:
            # Cap enforcement — silently undo if at GROUP_CAP
            if len(self._selected) >= GROUP_CAP:
                # Find the row that just toggled itself ON, un-check it
                for r in self._rows:
                    if r.category_id() == cid:
                        r.set_checked(False)
                        break
                dialogs.info(
                    self, "Maximum reached",
                    f"A sister group can hold at most {GROUP_CAP} "
                    "categories. Uncheck one before selecting another.")
                return
            self._selected.add(cid)
        else:
            self._selected.discard(cid)
        self._refresh_save_state()

    def _refresh_save_state(self) -> None:
        n = len(self._selected)
        self._counter_lbl.setText(f"{n} / {GROUP_CAP} selected")
        valid = GROUP_MIN <= n <= GROUP_CAP
        if valid:
            self._save_btn.setEnabled(True)
            self._save_btn.setStyleSheet(
                f"QPushButton {{ background: {rgba(PURPLE, 0.30)}; "
                f"color: {PURPLE_LIGHT}; "
                f"border: 1px solid {rgba(PURPLE, 0.55)}; "
                f"border-radius: 8px; }}"
                f"QPushButton:hover {{ background: {rgba(PURPLE, 0.45)}; }}"
            )
        else:
            self._save_btn.setEnabled(False)
            self._save_btn.setStyleSheet(
                f"QPushButton {{ background: transparent; "
                f"color: {TEXT_MUTED}; "
                f"border: 1px solid {rgba('#ffffff', 0.10)}; "
                f"border-radius: 8px; }}"
            )

    def _on_save(self) -> None:
        ids = sorted(self._selected)
        if not (GROUP_MIN <= len(ids) <= GROUP_CAP):
            return
        try:
            if self._edit_group_id is None:
                self._db.create_sister_group(ids)
            else:
                # Edit flow — diff old vs new
                existing_row = self._db._conn().execute(
                    "SELECT category_id FROM sister_group_members "
                    "WHERE group_id = ?", [int(self._edit_group_id)]
                ).fetchall()
                existing = {int(r["category_id"]) for r in existing_row}
                target = set(ids)
                to_add = target - existing
                to_remove = existing - target
                for cid in to_remove:
                    self._db.remove_category_from_sister_group(
                        self._edit_group_id, cid)
                for cid in to_add:
                    self._db.add_category_to_sister_group(
                        self._edit_group_id, cid)
        except ValueError as exc:
            dialogs.warning(
                self, "Save failed", str(exc))
            return
        except Exception as exc:
            log.exception("save failed")
            dialogs.warning(
                self, "Save failed",
                f"Unexpected error: {exc}")
            return
        self.result_category_ids = ids
        self.accept()
