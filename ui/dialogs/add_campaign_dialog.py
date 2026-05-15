"""
RadioAI Studio Pro — Add Campaign Dialog
Pixel-accurate match of Figma node 100:2 (920×680).

Two-column form for creating an advertising campaign. Left column holds the
core campaign metadata + audio file list. Right column holds the four tinted
sections (Availability / Campaign Type / Contracted Plays / Break Priority)
plus the AI Auto-fill banner.

Date pickers ("..." buttons) and the Spot Programming button are stubbed
with toast messages for this session — wired in session 2 when the
CampaignDatePicker and SpotProgramming dialogs ship.

Emits campaign_saved(int) with the new campaign id when Save succeeds.
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Optional

from PyQt6.QtCore import Qt, QRectF, QTimer, pyqtSignal
from core import dialogs
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QPainterPath, QFont, QCursor, QLinearGradient,
    QBrush,
)
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QLineEdit, QComboBox, QTextEdit,
    QHBoxLayout, QVBoxLayout, QGridLayout, QFileDialog, QMessageBox,
    QSizePolicy,
)

from ui.widgets._tokens import (
    inter, mono, rgba,
    BG_BASE, BG_CARD, BG_ELEVATED,
    TEXT_PRI, TEXT_SEC, TEXT_MUTED, TEXT_DIM,
    CYAN, CYAN_LIGHT, GREEN, GREEN_LIGHT,
    AMBER, AMBER_LIGHT, RED, RED_LIGHT, PURPLE, PURPLE_LIGHT, PURPLE_DARK,
)
from ui.dialogs.base_dialog import BaseDialog

log = logging.getLogger("AddCampaignDialog")

INPUT_BG = "#0a0c18"
INPUT_BORDER = "rgba(255, 255, 255, 0.06)"


# ════════════════════════════════════════════════════════════════════════════
# Header — orange $ icon + AUTO CODE box
# ════════════════════════════════════════════════════════════════════════════

class _DollarIcon(QWidget):
    """36×36 orange-gradient $ icon for the dialog header."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(36, 36)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0, 0, 36, 36)
        path = QPainterPath(); path.addRoundedRect(rect, 8, 8)
        p.setClipPath(path)
        g = QLinearGradient(0, 0, 36, 36)
        g.setColorAt(0.0, QColor("#fbbf24"))
        g.setColorAt(1.0, QColor("#d97706"))
        p.fillRect(rect, QBrush(g))
        p.setClipping(False)
        p.setPen(QColor("#1f1102"))
        p.setFont(inter(20, QFont.Weight.Black, letter_spacing=-0.5))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, "$")


class _AutoCodeBox(QFrame):
    """Header-right AUTO CODE display — small label + monospace number."""

    def __init__(self, code: str = "—", parent=None):
        super().__init__(parent)
        self._code = code
        self.setFixedSize(132, 36)
        self.setStyleSheet(
            f"QFrame {{ background: {rgba(AMBER, 0.10)}; "
            f"border: 1px solid {rgba(AMBER, 0.30)}; "
            f"border-radius: 6px; }}"
        )

    def set_code(self, code: str):
        self._code = code or "—"
        self.update()

    def paintEvent(self, _e):
        super().paintEvent(_e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Label
        p.setPen(QColor(AMBER))
        p.setFont(inter(8, QFont.Weight.Bold, letter_spacing=1.4))
        p.drawText(QRectF(10, 4, 112, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "AUTO CODE")
        # Code
        p.setPen(QColor(AMBER_LIGHT))
        p.setFont(mono(15, bold=True))
        p.drawText(QRectF(10, 16, 112, 18),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._code)


# ════════════════════════════════════════════════════════════════════════════
# Generic form helpers
# ════════════════════════════════════════════════════════════════════════════

def _field_label(text: str, required: bool = False) -> QLabel:
    l = QLabel(text + (" *" if required else ""))
    l.setFont(inter(10, QFont.Weight.Medium))
    if required:
        l.setStyleSheet(
            f"QLabel {{ color: {TEXT_SEC}; background: transparent; }}"
            # Cyan asterisk via rich-text-ish prefix — we just colour the
            # whole label cyan to keep the QSS simple.
        )
    else:
        l.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent;")
    l.setFixedHeight(14)
    return l


def _input(placeholder: str = "") -> QLineEdit:
    e = QLineEdit()
    e.setPlaceholderText(placeholder)
    e.setFixedHeight(32)
    e.setFont(inter(11))
    e.setStyleSheet(
        f"QLineEdit {{ background: {INPUT_BG}; color: {TEXT_PRI}; "
        f"border: 1px solid {INPUT_BORDER}; border-radius: 5px; "
        f"padding: 0 10px; "
        f"selection-background-color: {rgba(CYAN, 0.25)}; }}"
        f"QLineEdit:focus {{ border-color: {CYAN}; }}"
        f"QLineEdit:disabled {{ color: {TEXT_DIM}; }}"
    )
    return e


class _DateInput(QLineEdit):
    """QLineEdit with a '...' button anchored to its right edge."""

    picker_clicked = pyqtSignal()

    def __init__(self, placeholder: str = "", parent=None):
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.setFixedHeight(32)
        self.setFont(inter(11))
        self.setStyleSheet(
            f"QLineEdit {{ background: {INPUT_BG}; color: {TEXT_PRI}; "
            f"border: 1px solid {INPUT_BORDER}; border-radius: 5px; "
            f"padding: 0 38px 0 10px; "
            f"selection-background-color: {rgba(CYAN, 0.25)}; }}"
            f"QLineEdit:focus {{ border-color: {CYAN}; }}"
        )
        self._btn = QPushButton("...", self)
        self._btn.setFixedSize(28, 24)
        self._btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._btn.setFont(inter(11, QFont.Weight.Bold))
        self._btn.setStyleSheet(
            f"QPushButton {{ background: {rgba('#ffffff', 0.06)}; "
            f"color: {TEXT_SEC}; border: 1px solid {INPUT_BORDER}; "
            f"border-radius: 4px; }}"
            f"QPushButton:hover {{ background: {rgba(CYAN, 0.18)}; "
            f"color: {CYAN_LIGHT}; }}"
        )
        self._btn.clicked.connect(self.picker_clicked.emit)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._btn.move(self.width() - self._btn.width() - 3,
                       (self.height() - self._btn.height()) // 2)


def _input_with_picker(placeholder: str = "") -> _DateInput:
    """Date-style input — text field + '...' button. Connect to
    `picker_clicked` for the picker-button press."""
    return _DateInput(placeholder)


def _combo(items: list, default: str = "") -> QComboBox:
    c = QComboBox()
    c.addItems(items)
    if default and default in items:
        c.setCurrentText(default)
    c.setFixedHeight(32)
    c.setFont(inter(11))
    c.setStyleSheet(
        f"QComboBox {{ background: {INPUT_BG}; color: {TEXT_PRI}; "
        f"border: 1px solid {INPUT_BORDER}; border-radius: 5px; "
        f"padding: 0 22px 0 10px; }}"
        f"QComboBox:focus {{ border-color: {CYAN}; }}"
        f"QComboBox::drop-down {{ border: none; width: 20px; }}"
        f"QComboBox::down-arrow {{ image: none; width: 0; height: 0; "
        f"border-left: 4px solid transparent; "
        f"border-right: 4px solid transparent; "
        f"border-top: 5px solid {TEXT_MUTED}; margin-right: 7px; }}"
        f"QComboBox QAbstractItemView {{ background: {BG_CARD}; "
        f"color: {TEXT_PRI}; "
        f"border: 1px solid {INPUT_BORDER}; border-radius: 5px; "
        f"selection-background-color: {rgba(CYAN, 0.20)}; "
        f"selection-color: {CYAN_LIGHT}; outline: none; padding: 4px; }}"
    )
    return c


def _section_header(text: str, color: str) -> QFrame:
    """Accent-bar + uppercase section header used on the right column."""
    f = QFrame()
    f.setFixedHeight(24)
    f.setStyleSheet("background: transparent;")

    class _Painter(QFrame):
        def __init__(self, t, c, parent=None):
            super().__init__(parent)
            self._t = t
            self._c = QColor(c)
            self.setFixedHeight(24)
            self.setStyleSheet("background: transparent;")

        def paintEvent(self, _e):
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            # 3px accent bar on the left
            p.fillRect(QRectF(0, 4, 3, 16), self._c)
            # Label
            p.setPen(self._c)
            p.setFont(inter(10, QFont.Weight.Bold, letter_spacing=1.4))
            p.drawText(QRectF(12, 0, self.width() - 12, 24),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       self._t)
    return _Painter(text, color)


# ════════════════════════════════════════════════════════════════════════════
# Right-column section widgets
# ════════════════════════════════════════════════════════════════════════════

class _AvailabilityCard(QFrame):
    """Active / Draft selector — two stacked rows, only one selected."""

    selection_changed = pyqtSignal(str)   # 'active' | 'draft'

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = "active"
        self.setStyleSheet("background: transparent;")
        self.setFixedHeight(96)

    def value(self) -> str:
        return self._value

    def set_value(self, v: str):
        v = (v or "active").lower()
        if v not in ("active", "draft"):
            v = "active"
        self._value = v
        self.update()

    def mousePressEvent(self, e):
        # Hit-test active vs draft regions
        if e.position().y() < 56:
            new_v = "active"
        else:
            new_v = "draft"
        if new_v != self._value:
            self._value = new_v
            self.update()
            self.selection_changed.emit(new_v)
        super().mousePressEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Active card (top row)
        active_rect = QRectF(0, 0, self.width(), 50)
        is_active = (self._value == "active")
        path = QPainterPath(); path.addRoundedRect(active_rect, 6, 6)
        p.setClipPath(path)
        if is_active:
            tint = QColor(GREEN); tint.setAlphaF(0.18)
            p.fillRect(active_rect, tint)
        else:
            p.fillRect(active_rect, QColor(INPUT_BG))
        p.setClipping(False)
        bc = QColor(GREEN); bc.setAlphaF(0.40 if is_active else 0.10)
        p.setPen(QPen(bc, 1)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(active_rect, 6, 6)

        # Active checkbox box
        cb = QRectF(10, 14, 22, 22)
        p.setBrush(QColor(GREEN if is_active else "transparent"))
        p.setPen(QPen(QColor(GREEN), 1.5))
        p.drawRoundedRect(cb, 4, 4)
        if is_active:
            p.setPen(QPen(QColor("#0a0c18"), 2))
            p.drawLine(int(cb.x() + 6), int(cb.y() + 11),
                       int(cb.x() + 9), int(cb.y() + 15))
            p.drawLine(int(cb.x() + 9), int(cb.y() + 15),
                       int(cb.x() + 17), int(cb.y() + 7))

        # Active label + sub
        p.setPen(QColor(GREEN_LIGHT if is_active else TEXT_SEC))
        p.setFont(inter(11, QFont.Weight.Bold))
        p.drawText(QRectF(40, 6, self.width() - 50, 18),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "Active")
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(inter(9))
        p.drawText(QRectF(40, 24, self.width() - 50, 18),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "Campaign will run on schedule")

        # Draft row (more compact, no card background)
        draft_y = 60
        is_draft = not is_active
        draft_cb = QRectF(10, draft_y + 5, 18, 18)
        p.setBrush(QColor("transparent"))
        p.setPen(QPen(QColor(TEXT_MUTED if not is_draft else AMBER), 1.4))
        p.drawRoundedRect(draft_cb, 3, 3)
        if is_draft:
            p.setBrush(QColor(AMBER)); p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(QRectF(draft_cb.x() + 3, draft_cb.y() + 3,
                                     12, 12), 2, 2)

        p.setPen(QColor(AMBER_LIGHT if is_draft else TEXT_SEC))
        p.setFont(inter(11, QFont.Weight.DemiBold))
        p.drawText(QRectF(36, draft_y, self.width() - 46, 18),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "Draft" if is_draft else "Draft")
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(inter(9))
        p.drawText(QRectF(36, draft_y + 16, self.width() - 46, 18),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "(Not scheduled yet)")


class _CampaignTypePill(QPushButton):
    """One pill in the Campaign Type grid — selected pill is filled orange."""

    pill_clicked = pyqtSignal(str)  # the pill's value

    def __init__(self, label: str, parent=None):
        super().__init__("", parent)
        self._label = label
        self._selected = False
        self._hover = False
        self.setFixedHeight(34)
        self.setMinimumWidth(80)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFlat(True)
        self.setStyleSheet("background: transparent; border: none;")

    def value(self) -> str:
        return self._label

    def set_selected(self, sel: bool):
        self._selected = sel
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.pill_clicked.emit(self._label)
        super().mousePressEvent(e)

    def enterEvent(self, e): self._hover = True;  self.update(); super().enterEvent(e)
    def leaveEvent(self, e): self._hover = False; self.update(); super().leaveEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0, 0, self.width(), self.height())
        path = QPainterPath(); path.addRoundedRect(rect, 6, 6)
        p.setClipPath(path)
        if self._selected:
            g = QLinearGradient(0, 0, 0, self.height())
            g.setColorAt(0.0, QColor("#fbbf24"))
            g.setColorAt(1.0, QColor("#d97706"))
            p.fillRect(rect, QBrush(g))
        else:
            p.fillRect(rect, QColor(INPUT_BG))
        p.setClipping(False)
        bc_color = QColor(AMBER) if self._selected else QColor(255, 255, 255, 14)
        if self._selected:
            bc_color.setAlphaF(0.50)
        p.setPen(QPen(bc_color, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 6, 6)
        # Label (only shown when not selected — Figma shows orange-only fill)
        if not self._selected:
            p.setPen(QColor(TEXT_PRI if self._hover else TEXT_SEC))
            p.setFont(inter(11, QFont.Weight.DemiBold))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._label)


class _AIBanner(QFrame):
    """Purple-gradient AI auto-fill banner. Click → log info (stub)."""

    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(50)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0, 0, self.width(), self.height())
        path = QPainterPath(); path.addRoundedRect(rect, 6, 6)
        p.setClipPath(path)
        c1 = QColor(PURPLE); c1.setAlphaF(0.22)
        c2 = QColor(PURPLE_DARK); c2.setAlphaF(0.10)
        g = QLinearGradient(0, 0, 0, self.height())
        g.setColorAt(0.0, c1); g.setColorAt(1.0, c2)
        p.fillRect(rect, QBrush(g))
        p.setClipping(False)
        bc = QColor(PURPLE); bc.setAlphaF(0.40)
        p.setPen(QPen(bc, 1)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 6, 6)
        # Title + subtitle
        p.setPen(QColor(PURPLE_LIGHT))
        p.setFont(inter(11, QFont.Weight.Bold))
        p.drawText(QRectF(12, 4, self.width() - 24, 18),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "✦ AI Auto-fill Campaign")
        p.setPen(QColor(TEXT_SEC))
        p.setFont(inter(9))
        p.drawText(QRectF(12, 22, self.width() - 24, 18),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "Let AI suggest optimal break times")


# ════════════════════════════════════════════════════════════════════════════
# Audio files mini-table (left column bottom)
# ════════════════════════════════════════════════════════════════════════════

class _AudioFilesPanel(QFrame):
    """Panel showing attached audio files with empty state.

    For Phase C we only support adding files in-memory; the parent dialog
    persists them on Save. Files added before Save aren't yet linked to a
    campaign id — we hold them in a list and INSERT them after the campaign
    row exists."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._files: list[dict] = []
        self.setStyleSheet(
            f"QFrame {{ background: {rgba('#ffffff', 0.02)}; "
            f"border: 1px solid {INPUT_BORDER}; border-radius: 6px; }}"
        )
        self.setFixedHeight(120)

    def files(self) -> list[dict]:
        return list(self._files)

    def add_file(self, file_path: str):
        if not file_path:
            return
        self._files.append({
            "filename":    os.path.basename(file_path),
            "file_path":   file_path,
            "duration_ms": 0,
            "is_active":   1,
        })
        self.update()

    def paintEvent(self, _e):
        super().paintEvent(_e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Column header
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(inter(8, QFont.Weight.Bold, letter_spacing=1.0))
        col_w = self.width() / 4
        for i, label in enumerate(["File Name", "Duration", "Status",
                                    "Actions"]):
            p.drawText(QRectF(12 + i * col_w, 6, col_w, 16),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       label)

        # Hairline separator
        p.setPen(QPen(QColor(255, 255, 255, 16), 1))
        p.drawLine(0, 24, self.width(), 24)

        if not self._files:
            p.setPen(QColor(TEXT_DIM))
            p.setFont(inter(10))
            p.drawText(QRectF(0, 24, self.width(), self.height() - 24),
                       Qt.AlignmentFlag.AlignCenter,
                       "No audio files added yet")
            return

        # File rows
        row_h = 24
        for i, f in enumerate(self._files):
            y = 30 + i * row_h
            if y + row_h > self.height():
                break
            p.setPen(QColor(TEXT_PRI))
            p.setFont(inter(10, QFont.Weight.Medium))
            fname = f.get("filename") or "—"
            p.drawText(QRectF(12, y, col_w - 12, row_h),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       fname)
            p.setPen(QColor(TEXT_MUTED))
            p.setFont(mono(9, bold=True))
            dur_ms = int(f.get("duration_ms") or 0)
            dur = f"{dur_ms//60000}:{(dur_ms//1000)%60:02d}" if dur_ms else "—"
            p.drawText(QRectF(12 + col_w, y, col_w, row_h),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       dur)
            # Status pill
            pill = QRectF(12 + 2 * col_w, y + 4, 56, 16)
            bg = QColor(GREEN); bg.setAlphaF(0.20)
            p.setBrush(bg); p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(pill, 7, 7)
            p.setPen(QColor(GREEN_LIGHT))
            p.setFont(inter(8, QFont.Weight.Bold, letter_spacing=0.5))
            p.drawText(pill, Qt.AlignmentFlag.AlignCenter, "Active")


# ════════════════════════════════════════════════════════════════════════════
# Main dialog
# ════════════════════════════════════════════════════════════════════════════

CAMPAIGN_TYPES = ["Commercial", "Station ID", "Sponsor", "News Break", "Promo"]
PRIORITIES     = ["Low", "Medium", "High", "Always"]
PLAYBACK_ORDERS = ["In Rotation", "Sequential", "Random", "Specific Order"]
CATEGORIES = ["Commercial", "Station ID", "News Break", "Sponsor", "Promo",
              "Commercials"]
PROGRAMMING_MODES = ["Weekly", "Daily", "Continuous", "Custom"]
STATUSES = ["Active", "Draft", "Paused"]


class AddCampaignDialog(BaseDialog):

    campaign_saved = pyqtSignal(int)   # new campaign id

    HEADER_H = 64
    FOOTER_H = 60

    def __init__(self, db, parent=None, edit_campaign_id: Optional[int] = None):
        """Opens in NEW or EDIT mode.

        edit_campaign_id is None  →  new-campaign flow (auto_code generated,
                                     fields blank/defaulted, Save inserts).
        edit_campaign_id is set   →  edit flow (auto_code from DB row,
                                     fields pre-populated, Save updates,
                                     header/button text changes).
        """
        self._db = db
        self._edit_id = int(edit_campaign_id) if edit_campaign_id else None
        # In edit mode, load the existing campaign so the form can pre-fill.
        # We hold the row dict so _populate_defaults can read it.
        self._edit_row: Optional[dict] = None
        if self._edit_id is not None:
            try:
                self._edit_row = db.get_campaign(self._edit_id)
            except Exception as exc:
                log.error(f"get_campaign({self._edit_id}) failed: {exc}")
                self._edit_row = None

        # auto_code: pre-existing in edit mode, freshly generated for new
        if self._edit_row and self._edit_row.get("auto_code"):
            self._auto_code = str(self._edit_row["auto_code"])
        else:
            try:
                self._auto_code = db.generate_auto_code()
            except Exception as exc:
                log.error(f"generate_auto_code failed: {exc}")
                self._auto_code = "—"
        # Form refs
        self._title_input: Optional[QLineEdit] = None
        self._status_combo: Optional[QComboBox] = None
        self._mode_combo:   Optional[QComboBox] = None
        self._ad_company_input: Optional[QLineEdit] = None
        self._start_date_input: Optional[QLineEdit] = None
        self._end_date_input:   Optional[QLineEdit] = None
        self._category_combo: Optional[QComboBox] = None
        self._client_input:   Optional[QLineEdit] = None
        self._media_shop_input: Optional[QLineEdit] = None
        self._cost_input:     Optional[QLineEdit] = None
        self._priority_combo: Optional[QComboBox] = None
        self._playback_combo: Optional[QComboBox] = None
        self._comments_input: Optional[QTextEdit] = None
        self._files_panel:    Optional[_AudioFilesPanel] = None
        self._auto_code_box:  Optional[_AutoCodeBox] = None
        self._availability:   Optional[_AvailabilityCard] = None
        self._type_pills:     list[_CampaignTypePill] = []
        self._selected_type = "Commercial"
        self._plays_per_day_input: Optional[QLineEdit] = None
        self._days_of_week_input:  Optional[QLineEdit] = None
        self._total_plays_input:   Optional[QLineEdit] = None
        self._min_gap_input:       Optional[QLineEdit] = None
        self._max_per_break_input: Optional[QLineEdit] = None
        self._save_btn: Optional[QPushButton] = None
        # Schedule staged from Spot Programming dialog (persisted on Save)
        self._staged_schedule: list = []

        super().__init__(target_size=(920, 680), parent=parent)
        self._populate_defaults()

    # ── Header ────────────────────────────────────────────────────────────

    def _build_header(self) -> QWidget:
        f = QFrame()
        f.setStyleSheet(
            f"QFrame {{ background: #0d0f1e; "
            f"border-bottom: 1px solid {rgba('#ffffff', 0.06)}; }}"
        )
        h = QHBoxLayout(f)
        h.setContentsMargins(16, 12, 12, 12); h.setSpacing(14)

        h.addWidget(_DollarIcon())

        title_box = QWidget(); title_box.setStyleSheet("background: transparent;")
        tv = QVBoxLayout(title_box)
        tv.setContentsMargins(0, 0, 0, 0); tv.setSpacing(2)
        is_edit = self._edit_id is not None
        title = QLabel("EDIT CAMPAIGN" if is_edit else "NEW CAMPAIGN")
        title.setFont(inter(16, QFont.Weight.Black, letter_spacing=0.5))
        title.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        sub = QLabel("Modify existing campaign" if is_edit
                     else "Add a new advertising campaign")
        sub.setFont(inter(10))
        sub.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        tv.addWidget(title); tv.addWidget(sub)
        h.addWidget(title_box)
        h.addStretch()

        # AUTO CODE box — visually muted when editing (the code never changes)
        self._auto_code_box = _AutoCodeBox(self._auto_code)
        if is_edit:
            self._auto_code_box.setEnabled(False)
            self._auto_code_box.setToolTip(
                "Auto-codes are immutable once a campaign is saved.")
        h.addWidget(self._auto_code_box)

        # Close
        x = QPushButton("✕")
        x.setFixedSize(28, 28)
        x.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        x.setFont(inter(13, QFont.Weight.Bold))
        x.setStyleSheet(
            f"QPushButton {{ background: #1c1f38; color: {TEXT_SEC}; "
            f"border: none; border-radius: 6px; }}"
            f"QPushButton:hover {{ background: {rgba(RED, 0.20)}; "
            f"color: {RED_LIGHT}; }}"
        )
        x.clicked.connect(self.reject)
        h.addWidget(x)
        return f

    # ── Content ───────────────────────────────────────────────────────────

    def _build_content(self) -> QWidget:
        c = QFrame(); c.setStyleSheet("background: transparent;")
        outer = QHBoxLayout(c)
        outer.setContentsMargins(16, 14, 16, 14); outer.setSpacing(14)
        outer.addWidget(self._build_left_column(), stretch=60)
        outer.addWidget(self._build_right_column(), stretch=40)
        return c

    # ── Left column ───────────────────────────────────────────────────────

    def _build_left_column(self) -> QWidget:
        wrap = QFrame(); wrap.setStyleSheet("background: transparent;")
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0); v.setSpacing(10)

        # Title (full width)
        v.addWidget(_field_label("Spot General Title", required=True))
        self._title_input = _input("Type campaign title...")
        self._title_input.textChanged.connect(self._on_title_changed)
        v.addWidget(self._title_input)

        # Row 2 — 3 cols
        row2 = QGridLayout(); row2.setContentsMargins(0, 0, 0, 0)
        row2.setHorizontalSpacing(10); row2.setVerticalSpacing(2)
        row2.addWidget(_field_label("Current Status"),   0, 0)
        row2.addWidget(_field_label("Programming Mode"), 0, 1)
        row2.addWidget(_field_label("Ad Company"),       0, 2)
        self._status_combo = _combo(STATUSES, "Active")
        self._mode_combo   = _combo(PROGRAMMING_MODES, "Weekly")
        self._ad_company_input = _input("e.g. Coca Cola...")
        row2.addWidget(self._status_combo,   1, 0)
        row2.addWidget(self._mode_combo,     1, 1)
        row2.addWidget(self._ad_company_input, 1, 2)
        v.addLayout(row2)

        # Row 3 — 4 cols (Start + Expire have date pickers)
        row3 = QGridLayout(); row3.setContentsMargins(0, 0, 0, 0)
        row3.setHorizontalSpacing(10); row3.setVerticalSpacing(2)
        row3.addWidget(_field_label("Start Date"),  0, 0)
        row3.addWidget(_field_label("Expire Date"), 0, 1)
        row3.addWidget(_field_label("Category"),    0, 2)
        row3.addWidget(_field_label("Client"),      0, 3)
        self._start_date_input = _input_with_picker("DD MMM YYYY")
        self._end_date_input   = _input_with_picker("DD MMM YYYY")
        self._start_date_input.picker_clicked.connect(
            lambda: self._stub_picker("Start Date"))
        self._end_date_input.picker_clicked.connect(
            lambda: self._stub_picker("Expire Date"))
        self._category_combo = _combo(CATEGORIES, "Commercials")
        self._client_input   = _input("Client name...")
        row3.addWidget(self._start_date_input, 1, 0)
        row3.addWidget(self._end_date_input,   1, 1)
        row3.addWidget(self._category_combo,   1, 2)
        row3.addWidget(self._client_input,     1, 3)
        v.addLayout(row3)

        # Row 4 — 4 cols
        row4 = QGridLayout(); row4.setContentsMargins(0, 0, 0, 0)
        row4.setHorizontalSpacing(10); row4.setVerticalSpacing(2)
        row4.addWidget(_field_label("Media Shop"),     0, 0)
        row4.addWidget(_field_label("Agreement Cost"), 0, 1)
        row4.addWidget(_field_label("Priority"),       0, 2)
        row4.addWidget(_field_label("Playback Order"), 0, 3)
        self._media_shop_input = _input("Media agency...")
        self._cost_input       = _input("0.0000")
        self._priority_combo   = _combo(PRIORITIES, "High")
        self._playback_combo   = _combo(PLAYBACK_ORDERS, "In Rotation")
        row4.addWidget(self._media_shop_input, 1, 0)
        row4.addWidget(self._cost_input,       1, 1)
        row4.addWidget(self._priority_combo,   1, 2)
        row4.addWidget(self._playback_combo,   1, 3)
        v.addLayout(row4)

        # Comments
        v.addWidget(_field_label("Comments"))
        self._comments_input = QTextEdit()
        self._comments_input.setFixedHeight(64)
        self._comments_input.setFont(inter(10))
        self._comments_input.setPlaceholderText("Notes about this campaign...")
        self._comments_input.setStyleSheet(
            f"QTextEdit {{ background: {INPUT_BG}; color: {TEXT_PRI}; "
            f"border: 1px solid {INPUT_BORDER}; border-radius: 5px; "
            f"padding: 8px 10px; "
            f"selection-background-color: {rgba(CYAN, 0.25)}; }}"
            f"QTextEdit:focus {{ border-color: {CYAN}; }}"
        )
        v.addWidget(self._comments_input)

        # AUDIO FILES section
        v.addWidget(_section_header("AUDIO FILES", CYAN))
        self._files_panel = _AudioFilesPanel()
        v.addWidget(self._files_panel)

        # Buttons row
        btn_row = QHBoxLayout(); btn_row.setSpacing(8); btn_row.setContentsMargins(0, 4, 0, 0)
        add_file = self._make_outlined("+ Add New File", GREEN)
        add_file.clicked.connect(self._on_add_file)
        stitcher = self._make_outlined("⚡ The Stitcher", CYAN)
        stitcher.clicked.connect(lambda: self._stub_toast(
            "The Stitcher", "Stitcher integration ships in a later phase"))
        btn_row.addWidget(add_file)
        btn_row.addWidget(stitcher)
        btn_row.addStretch()
        spot_prog = self._make_outlined("📅 Spot Programming", AMBER)
        spot_prog.clicked.connect(self._on_open_spot_programming)
        btn_row.addWidget(spot_prog)
        v.addLayout(btn_row)

        v.addStretch()
        return wrap

    def _make_outlined(self, text: str, color: str) -> QPushButton:
        b = QPushButton(text)
        b.setFixedHeight(32)
        b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        b.setFont(inter(10, QFont.Weight.DemiBold))
        b.setStyleSheet(
            f"QPushButton {{ background: {rgba(color, 0.14)}; color: {color}; "
            f"border: 1px solid {rgba(color, 0.40)}; border-radius: 6px; "
            f"padding: 0 14px; }}"
            f"QPushButton:hover {{ background: {rgba(color, 0.24)}; }}"
        )
        return b

    # ── Right column ──────────────────────────────────────────────────────

    def _build_right_column(self) -> QWidget:
        wrap = QFrame(); wrap.setStyleSheet("background: transparent;")
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0); v.setSpacing(10)

        # AVAILABILITY section
        v.addWidget(_section_header("AVAILABILITY", GREEN))
        self._availability = _AvailabilityCard()
        v.addWidget(self._availability)

        # CAMPAIGN TYPE section
        v.addWidget(_section_header("CAMPAIGN TYPE", AMBER))
        type_grid = QGridLayout()
        type_grid.setContentsMargins(0, 0, 0, 0)
        type_grid.setHorizontalSpacing(8); type_grid.setVerticalSpacing(8)
        for i, t in enumerate(CAMPAIGN_TYPES):
            pill = _CampaignTypePill(t)
            pill.set_selected(t == self._selected_type)
            pill.pill_clicked.connect(self._on_type_selected)
            self._type_pills.append(pill)
            type_grid.addWidget(pill, i // 3, i % 3)
        v.addLayout(type_grid)

        # CONTRACTED PLAYS section
        v.addWidget(_section_header("CONTRACTED PLAYS", CYAN))
        cp_grid = QGridLayout(); cp_grid.setContentsMargins(0, 0, 0, 0)
        cp_grid.setHorizontalSpacing(10); cp_grid.setVerticalSpacing(2)
        cp_grid.addWidget(_field_label("Plays per day"), 0, 0)
        cp_grid.addWidget(_field_label("Days of week"),  0, 1)
        self._plays_per_day_input = _input("3")
        self._plays_per_day_input.setText("3")
        self._plays_per_day_input.textChanged.connect(self._recalc_total_plays)
        self._days_of_week_input = _input("Mon-Fri")
        self._days_of_week_input.setText("Mon-Fri")
        self._days_of_week_input.textChanged.connect(self._recalc_total_plays)
        cp_grid.addWidget(self._plays_per_day_input, 1, 0)
        cp_grid.addWidget(self._days_of_week_input,  1, 1)
        v.addLayout(cp_grid)
        v.addWidget(_field_label("Total contracted plays"))
        self._total_plays_input = _input("90 plays (30 days)")
        self._total_plays_input.setReadOnly(True)
        self._total_plays_input.setText("90 plays (30 days)")
        v.addWidget(self._total_plays_input)

        # BREAK PRIORITY section
        v.addWidget(_section_header("BREAK PRIORITY", RED))
        bp_grid = QGridLayout(); bp_grid.setContentsMargins(0, 0, 0, 0)
        bp_grid.setHorizontalSpacing(10); bp_grid.setVerticalSpacing(2)
        bp_grid.addWidget(_field_label("Min gap between plays"), 0, 0)
        bp_grid.addWidget(_field_label("Max per break"),         0, 1)
        self._min_gap_input = _input("30 minutes")
        self._min_gap_input.setText("30 minutes")
        self._max_per_break_input = _input("1 spot")
        self._max_per_break_input.setText("1 spot")
        bp_grid.addWidget(self._min_gap_input,       1, 0)
        bp_grid.addWidget(self._max_per_break_input, 1, 1)
        v.addLayout(bp_grid)

        # AI banner
        ai = _AIBanner()
        ai.clicked.connect(lambda: log.info(
            "[AI Auto-fill] not yet wired to Claude API"))
        v.addWidget(ai)

        v.addStretch()
        return wrap

    # ── Footer ────────────────────────────────────────────────────────────

    def _build_footer(self) -> QWidget:
        f = QFrame()
        f.setStyleSheet(
            f"QFrame {{ background: #0d0f1e; "
            f"border-top: 1px solid {rgba('#ffffff', 0.06)}; }}"
        )
        h = QHBoxLayout(f)
        h.setContentsMargins(20, 12, 16, 12); h.setSpacing(8)

        req = QLabel("* Required fields")
        req.setFont(inter(9))
        req.setStyleSheet(f"color: {TEXT_DIM}; background: transparent;")
        h.addWidget(req)
        h.addStretch()

        cancel = QPushButton("Cancel")
        cancel.setFixedHeight(34); cancel.setMinimumWidth(96)
        cancel.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        cancel.setFont(inter(11, QFont.Weight.Medium))
        cancel.setStyleSheet(
            f"QPushButton {{ background: #1c1f38; color: {TEXT_SEC}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; "
            f"border-radius: 7px; padding: 0 18px; }}"
            f"QPushButton:hover {{ background: #252848; color: {TEXT_PRI}; }}"
        )
        cancel.clicked.connect(self.reject)
        h.addWidget(cancel)

        is_edit = self._edit_id is not None
        save = QPushButton("✓  Update Campaign" if is_edit else "✓  Save")
        save.setFixedHeight(34)
        save.setMinimumWidth(160 if is_edit else 108)
        save.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        save.setFont(inter(11, QFont.Weight.DemiBold))
        save.setStyleSheet(
            f"QPushButton {{ background: qlineargradient("
            f"x1:0,y1:0,x2:0,y2:1, stop:0 {PURPLE_LIGHT}, "
            f"stop:0.5 {PURPLE}, stop:1 #7c3aed); "
            f"color: white; border: none; border-radius: 7px; "
            f"padding: 0 22px; }}"
            f"QPushButton:hover {{ background: qlineargradient("
            f"x1:0,y1:0,x2:0,y2:1, stop:0 #c4b5fd, stop:1 {PURPLE}); }}"
            f"QPushButton:disabled {{ background: #252848; "
            f"color: {TEXT_MUTED}; }}"
        )
        save.clicked.connect(self._on_save)
        # In edit mode, title is already populated → enable immediately
        save.setEnabled(is_edit)
        h.addWidget(save)
        self._save_btn = save
        return f

    # ── Defaults / helpers ────────────────────────────────────────────────

    def _populate_defaults(self):
        """Fill the form with the spec'd defaults on open. In edit mode,
        pre-populate from the existing campaign + its spot files + schedule."""
        if self._edit_row is not None:
            self._populate_from_edit_row()
            return

        # NEW campaign defaults
        today = datetime.now().date()
        if self._start_date_input:
            self._start_date_input.setText(today.strftime("%d %b %Y"))
        if self._end_date_input:
            self._end_date_input.setText("Never")
        if self._comments_input:
            self._comments_input.setPlaceholderText(
                f"Created automatically — {today.strftime('%m/%d/%Y')}")
        self._recalc_total_plays()
        if self._save_btn:
            self._save_btn.setEnabled(False)

    def _populate_from_edit_row(self):
        """Copy fields from self._edit_row into the form widgets."""
        row = self._edit_row or {}

        def _iso_to_display(iso: str) -> str:
            if not iso:
                return ""
            if iso == "Never":
                return "Never"
            try:
                return datetime.strptime(iso, "%Y-%m-%d").strftime("%d %b %Y")
            except ValueError:
                return iso

        if self._title_input:
            self._title_input.setText(row.get("name") or "")
        if self._comments_input:
            self._comments_input.setPlainText(row.get("description") or "")
        if self._category_combo:
            cat = row.get("category") or ""
            idx = self._category_combo.findText(cat)
            if idx >= 0:
                self._category_combo.setCurrentIndex(idx)
        if self._priority_combo:
            pri = row.get("priority") or ""
            idx = self._priority_combo.findText(pri)
            if idx >= 0:
                self._priority_combo.setCurrentIndex(idx)
        if self._mode_combo:
            mode = row.get("programming_mode") or ""
            idx = self._mode_combo.findText(mode)
            if idx >= 0:
                self._mode_combo.setCurrentIndex(idx)
        if self._playback_combo:
            order = row.get("playback_order") or ""
            idx = self._playback_combo.findText(order)
            if idx >= 0:
                self._playback_combo.setCurrentIndex(idx)
        if self._start_date_input:
            self._start_date_input.setText(_iso_to_display(row.get("start_date") or ""))
        if self._end_date_input:
            self._end_date_input.setText(_iso_to_display(row.get("end_date") or "Never"))
        if self._plays_per_day_input:
            self._plays_per_day_input.setText(
                str(row.get("contracted_plays_per_day") or 3))
        if self._min_gap_input:
            self._min_gap_input.setText(
                f"{int(row.get('min_gap_minutes') or 30)} minutes")
        if self._max_per_break_input:
            self._max_per_break_input.setText(
                f"{int(row.get('max_per_break') or 1)} spot")
        # Availability — Active/Draft toggle
        if self._availability:
            avail = row.get("availability")
            if not avail:
                avail = "active" if row.get("is_active", 1) else "draft"
            self._availability.set_value(avail)

        # Pre-load existing spot files into the panel
        if self._files_panel:
            for sf in (row.get("spot_files") or []):
                self._files_panel.add_file(sf.get("file_path") or "")

        # Pre-load existing schedule so Spot Programming dialog opens with it
        sched_rows = row.get("schedule") or []
        if sched_rows:
            self._staged_schedule = list(sched_rows)

        self._recalc_total_plays()

    def _recalc_total_plays(self):
        """Update 'Total contracted plays' to plays/day × 30 calendar days.
        Matches Figma 100:2 reference (90 plays / 30 days for ppd=3).
        Days-of-week is metadata for scheduling, not a multiplier — a 30-day
        contract is 30 days regardless of which weekdays are scheduled."""
        try:
            ppd = int((self._plays_per_day_input.text() or "0").strip() or 0)
        except ValueError:
            ppd = 0
        contract_days = 30
        total = ppd * contract_days
        if self._total_plays_input:
            self._total_plays_input.setText(
                f"{total} plays ({contract_days} days)")

    def _on_title_changed(self, text: str):
        if self._save_btn:
            self._save_btn.setEnabled(bool(text.strip()))

    def _on_type_selected(self, value: str):
        self._selected_type = value
        for pill in self._type_pills:
            pill.set_selected(pill.value() == value)

    def _on_add_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Add audio file", "",
            "Audio files (*.mp3 *.wav *.ogg *.flac *.m4a);;All files (*.*)",
        )
        if path and self._files_panel:
            self._files_panel.add_file(path)
            log.info(f"file queued: {path}")

    def _stub_picker(self, label: str):
        """Open the CampaignDatePickerDialog for Start Date or Expire Date.
        Mode + min_date constraints depend on which button was clicked."""
        from PyQt6.QtCore import QDate
        from ui.dialogs.campaign_date_picker_dialog import CampaignDatePickerDialog

        is_start = (label == "Start Date")
        target_input = self._start_date_input if is_start else self._end_date_input
        mode = "start" if is_start else "expire"

        # Parse current text → QDate (for initial selection in the picker)
        initial = self._parse_input_to_qdate(target_input.text() if target_input else "")
        # Expire date can't precede the current Start Date value
        min_date = None
        if not is_start and self._start_date_input:
            min_date = self._parse_input_to_qdate(self._start_date_input.text())

        dlg = CampaignDatePickerDialog(
            mode=mode, min_date=min_date, initial=initial, parent=self)
        dlg.date_selected.connect(
            lambda qd, target=target_input: self._apply_picked_date(target, qd))
        dlg.never_selected.connect(
            lambda target=target_input: target.setText("Never") if target else None)
        dlg.exec()

    @staticmethod
    def _parse_input_to_qdate(text: str):
        """'10 Apr 2026' / 'Never' / '' → QDate or None."""
        from PyQt6.QtCore import QDate
        from datetime import datetime
        text = (text or "").strip()
        if not text or text.lower() == "never":
            return None
        for fmt in ("%d %b %Y", "%d %B %Y", "%Y-%m-%d", "%d/%m/%Y"):
            try:
                d = datetime.strptime(text, fmt)
                return QDate(d.year, d.month, d.day)
            except ValueError:
                pass
        return None

    @staticmethod
    def _apply_picked_date(target_input, qdate):
        """Format a QDate back into the 'DD MMM YYYY' display the field uses."""
        if target_input is None or qdate is None:
            return
        target_input.setText(qdate.toString("dd MMM yyyy"))

    def _on_open_spot_programming(self):
        """Open SpotProgrammingDialog in staged mode — campaign isn't saved
        yet, so the schedule is held in memory and persisted on Save."""
        from ui.dialogs.spot_programming_dialog import SpotProgrammingDialog
        title = (self._title_input.text() or "(unsaved campaign)").strip() \
                or "(unsaved campaign)"
        dlg = SpotProgrammingDialog(
            db=self._db,
            campaign_id=None,                       # → staged mode
            campaign_name=title,
            initial_schedule=self._staged_schedule,
            parent=self,
        )
        dlg.schedule_staged.connect(self._on_schedule_staged)
        dlg.exec()

    def _on_schedule_staged(self, rows: list):
        self._staged_schedule = list(rows or [])
        log.info(f"[stage] {len(self._staged_schedule)} break rows queued "
                 f"for save")

    def _stub_toast(self, title: str, msg: str):
        log.info(f"[STUB] {title}: {msg}")
        dialogs.info(self, title, msg)

    # ── Save ──────────────────────────────────────────────────────────────

    def _on_save(self):
        title = (self._title_input.text() or "").strip()
        if not title:
            dialogs.warning(self, "Required field",
                                "Spot General Title cannot be empty.")
            self._title_input.setFocus()
            return

        # Translate display dates to ISO
        start_iso = self._date_to_iso(self._start_date_input.text())
        end_text  = (self._end_date_input.text() or "").strip()
        end_iso   = "Never" if end_text.lower() == "never" else \
                    self._date_to_iso(end_text)

        try:
            ppd = int((self._plays_per_day_input.text() or "0").strip() or 3)
        except ValueError:
            ppd = 3

        # Translate Active/Draft → is_active
        avail = self._availability.value() if self._availability else "active"
        is_active = 1 if avail == "active" else 0

        data = {
            "name":             title,
            "description":      self._comments_input.toPlainText().strip(),
            "category":         self._category_combo.currentText(),
            "priority":         self._priority_combo.currentText(),
            "programming_mode": self._mode_combo.currentText(),
            "playback_order":   self._playback_combo.currentText(),
            "start_date":       start_iso,
            "end_date":         end_iso,
            "contracted_plays_per_day": ppd,
            "is_active":        is_active,
            "auto_code":        self._auto_code,
            "min_gap_minutes":  self._extract_int(
                                    self._min_gap_input.text(), 30),
            "max_per_break":    self._extract_int(
                                    self._max_per_break_input.text(), 1),
            "availability":     avail,
        }

        is_edit = self._edit_id is not None
        try:
            if is_edit:
                # Update path — preserve auto_code, never re-issue
                data.pop("auto_code", None)
                self._db.update_campaign(self._edit_id, data)
                target_id = self._edit_id
                log.info(f"campaign updated id={target_id} name={title!r}")
            else:
                target_id = self._db.add_campaign(data)
                log.info(f"campaign saved id={target_id} "
                         f"auto_code={self._auto_code} name={title!r}")

            # Persist any audio files queued in the panel.
            # In edit mode, files added during this session are appended;
            # the file panel currently has both pre-existing + newly-added
            # entries (session 1 does not yet support per-file delete from
            # an edit dialog — flagged as TODO).
            if self._files_panel and not is_edit:
                for f in self._files_panel.files():
                    self._db.add_spot_file(target_id, f)

            # Persist any schedule staged from Spot Programming dialog.
            # In both modes: if the user touched the schedule, write it.
            # The schedule replaces the existing one atomically (matches
            # the SpotProgrammingDialog's "Apply Schedule" semantic).
            if self._staged_schedule:
                self._db.update_break_schedule(target_id,
                                               self._staged_schedule)
                log.info(f"[stage] flushed {len(self._staged_schedule)} "
                         f"schedule rows to campaign {target_id}")
        except Exception as exc:
            log.error(
                f"{'update' if is_edit else 'add'}_campaign failed: {exc}",
                exc_info=True)
            dialogs.error(
                self,
                "Update failed" if is_edit else "Save failed",
                f"Could not save campaign:\n\n{exc}")
            return

        self.campaign_saved.emit(int(target_id))
        self.accept()

    @staticmethod
    def _date_to_iso(text: str) -> Optional[str]:
        """'10 Apr 2026' → '2026-04-10'. Returns None on parse failure."""
        text = (text or "").strip()
        if not text or text.lower() == "never":
            return text or None
        for fmt in ("%d %b %Y", "%d %B %Y", "%Y-%m-%d", "%d/%m/%Y"):
            try:
                return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
            except ValueError:
                pass
        return text  # leave it raw — DB column is TEXT

    @staticmethod
    def _extract_int(text: str, default: int) -> int:
        """'30 minutes' → 30, '1 spot' → 1, '' → default."""
        digits = "".join(ch for ch in (text or "") if ch.isdigit())
        try:
            return int(digits) if digits else default
        except ValueError:
            return default
