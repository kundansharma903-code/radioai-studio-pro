"""
RadioAI Studio Pro — premium dialog helpers.

Centralised, on-brand replacements for Qt's stock `QMessageBox` and
`QInputDialog`. Every helper returns a Python-native result (bool /
Optional[str] / Optional[int]) so call-sites stay terse.

Why this module exists
----------------------
Qt's stock dialogs use Windows' native chrome — dark text on the
app's dark background was unreadable (see operator screenshot of a
"Delete show?" confirm where neither the body text nor the buttons
were legible). A global QSS sheet patches the surface colors but
can't reshape the chrome (icon area, native title bar) or deliver
the same accent/card polish as the rest of the app. These helpers
build a frameless `QDialog` with the project's design tokens —
matching the premium screen language verbatim.

Public helpers
--------------
* :func:`confirm`     — Yes / Cancel modal (returns ``bool``).
                         Pass ``danger=True`` for destructive actions
                         (the primary button switches to red).
* :func:`info`        — single OK acknowledgement, cyan accent.
* :func:`warning`     — single OK acknowledgement, amber accent.
* :func:`error`       — single OK acknowledgement, red accent.
* :func:`text_input`  — single-line text prompt (returns ``Optional[str]``;
                         None on cancel).
* :func:`int_input`   — bounded integer prompt (returns
                         ``Optional[int]``; None on cancel).

All helpers accept ``parent`` (typically ``self`` in a screen) so the
dialog inherits modality + centering off the calling widget.

Design notes
------------
* Frameless `QDialog` with translucent background + rounded card
  body. Title strip is the drag handle (mouse-press → drag → release
  pattern; no titlebar buttons).
* Accent stripe on top of the card (3px) carries the type's color —
  cyan/amber/red. Visually consistent with summary stat pills used
  on the Hub / Rotation Health / Daily Plan Review screens.
* Buttons are 36h × 88w minimum, Inter Semi Bold, with hover +
  default-button states. Default button (Yes / OK) carries the
  accent fill; secondary (Cancel / No) is muted.
* Tab + Esc + Enter keyboard behavior follows Qt conventions —
  Enter triggers default button, Esc triggers the cancel/secondary
  button. No accept-on-mouse-leave nonsense.
* Drop shadow added via `QGraphicsDropShadowEffect` so the dialog
  visually floats above the parent screen.
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, QPoint, QRect, QSize
from PyQt6.QtGui import (
    QFont, QColor, QKeyEvent, QMouseEvent, QPainter, QPen, QBrush,
)
from PyQt6.QtWidgets import (
    QDialog, QWidget, QFrame, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QLineEdit, QGraphicsDropShadowEffect,
    QSizePolicy,
)


# ════════════════════════════════════════════════════════════════════════════
# Design tokens — duplicated here (not imported) so this module can run
# in tests without pulling in heavyweight ui/widgets/_tokens loaders.
# Keep in sync with assets/style.qss + ui/widgets/_tokens.py.
# ════════════════════════════════════════════════════════════════════════════

BG_BASE     = "#070812"
BG_PANEL    = "#0f1120"
BG_CARD     = "#0e1020"
BG_ELEVATED = "#131626"
BORDER      = "#1c1f38"
TEXT_PRI    = "#f1f5ff"
TEXT_SEC    = "#8891b8"
TEXT_MUTED  = "#454d6d"
CYAN        = "#06b6d4"
PURPLE      = "#8b5cf6"
GREEN       = "#10b981"
AMBER       = "#f59e0b"
RED         = "#f43f5e"


def _rgba(hex_str: str, alpha: float) -> str:
    """rgb(...) → rgba(...) helper for use in style sheets."""
    h = hex_str.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r}, {g}, {b}, {alpha:.2f})"


# ════════════════════════════════════════════════════════════════════════════
# Internal dialog primitive
# ════════════════════════════════════════════════════════════════════════════


class _PremiumDialog(QDialog):
    """Frameless modal dialog with accent stripe, title, body, button row.

    Not instantiated directly outside this module — public helpers
    (``confirm`` / ``info`` / ``warning`` / ``error``) wrap it.

    Layout (all dimensions in px):

        ┌──────────────────────────────────────────────┐
        │ <accent stripe — 3h>                         │
        │                                              │
        │   <icon 28w>   <title — Inter Bold 16>      │  ← 24 top pad
        │                                              │
        │      <body — Inter Regular 12, multi-line>  │  ← 12 gap
        │      ...                                    │
        │                                              │
        │   ┌─── optional <input row>  ───────────┐    │  ← 16 gap
        │   └───────────────────────────────────────┘   │
        │                                              │
        │              <btn 1>   <btn 2>              │  ← 24 gap, 20 bottom
        └──────────────────────────────────────────────┘

    Width: 460 by default (caller can override). Height: hugs content.
    """

    CARD_W = 460
    PAD = 24
    GAP_TITLE = 14
    GAP_BTN = 24
    BTN_H = 36
    BTN_MIN_W = 88

    def __init__(self, parent: Optional[QWidget] = None, *,
                 title: str,
                 body: str,
                 icon: str = "ℹ",
                 accent: str = CYAN,
                 input_widget: Optional[QWidget] = None,
                 buttons=None,
                 default_btn_idx: int = 0,
                 cancel_btn_idx: int = -1):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Dialog
            | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)
        self.setMinimumWidth(self.CARD_W)
        self.setMaximumWidth(self.CARD_W + 80)

        self._accent = accent
        self._drag_origin: Optional[QPoint] = None
        self._result_value = None  # set by helpers that return a value
        self._input_widget = input_widget
        self._buttons = list(buttons or [])
        self._default_btn_idx = default_btn_idx
        self._cancel_btn_idx = (
            cancel_btn_idx if cancel_btn_idx >= 0
            else len(self._buttons) - 1)

        # ── Card frame (the visible rounded panel; translucent
        # outer widget hosts the drop shadow). ─────────────────────
        self._card = QFrame(self)
        self._card.setObjectName("premium_dialog_card")
        self._card.setStyleSheet(
            f"#premium_dialog_card {{ "
            f"background: {BG_PANEL}; "
            f"border: 1px solid {BORDER}; "
            f"border-radius: 12px; }}")
        shadow = QGraphicsDropShadowEffect(self._card)
        shadow.setBlurRadius(48)
        shadow.setOffset(0, 12)
        shadow.setColor(QColor(0, 0, 0, 180))
        self._card.setGraphicsEffect(shadow)

        # Outer layout — just to host the card with margin for shadow
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.addWidget(self._card)

        # ── Card contents ──────────────────────────────────────────
        card_lay = QVBoxLayout(self._card)
        card_lay.setContentsMargins(self.PAD, self.PAD,
                                       self.PAD, self.PAD)
        card_lay.setSpacing(self.GAP_TITLE)

        # Accent stripe — painted in paintEvent on the card, not a
        # separate widget, to keep top corners crisp.

        # Title row: icon + title text
        title_row = QHBoxLayout()
        title_row.setSpacing(12)
        title_row.setContentsMargins(0, 0, 0, 0)
        self._icon_lbl = QLabel(icon)
        self._icon_lbl.setFixedSize(QSize(32, 32))
        self._icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_lbl.setStyleSheet(
            f"background: {_rgba(accent, 0.18)}; "
            f"border-radius: 8px; "
            f"color: {accent}; "
            f"font-size: 18px;")
        title_row.addWidget(self._icon_lbl)
        self._title_lbl = QLabel(title)
        self._title_lbl.setFont(
            QFont("Inter", 14, QFont.Weight.Bold))
        self._title_lbl.setStyleSheet(
            f"color: {TEXT_PRI}; background: transparent;")
        self._title_lbl.setWordWrap(True)
        title_row.addWidget(self._title_lbl, 1)
        card_lay.addLayout(title_row)

        # Body
        self._body_lbl = QLabel(body)
        self._body_lbl.setFont(QFont("Inter", 11))
        self._body_lbl.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent;")
        self._body_lbl.setWordWrap(True)
        # Height must be resolved from the WRAPPED text at the card's
        # real inner width. Relying on the layout's height-for-width
        # left multi-paragraph bodies one line short whenever a
        # paragraph wrapped — the LAST paragraph was then clipped out of
        # view entirely (found 2026-07-09 on the Delete Sweeper confirm,
        # where the "file on disk is not deleted" note was invisible).
        # Measuring at CARD_W (the MINIMUM width) can only over-estimate
        # the line count, so short bodies keep the old 20px floor and
        # every existing dialog's geometry is unchanged.
        _inner_w = self.CARD_W - 2 * self.PAD
        _wrapped_h = self._body_lbl.fontMetrics().boundingRect(
            QRect(0, 0, _inner_w, 10000),
            int(Qt.TextFlag.TextWordWrap), body).height()
        self._body_lbl.setMinimumHeight(max(20, _wrapped_h))
        self._body_lbl.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.MinimumExpanding)
        card_lay.addWidget(self._body_lbl)

        # Input widget (text/int prompts)
        if input_widget is not None:
            card_lay.addSpacing(4)
            card_lay.addWidget(input_widget)

        # Spacer before buttons
        card_lay.addSpacing(self.GAP_BTN - self.GAP_TITLE)

        # Button row — right-aligned
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.addStretch(1)
        self._btn_widgets: list[QPushButton] = []
        for i, spec in enumerate(self._buttons):
            label, role = spec  # role: 'primary' | 'secondary' | 'danger'
            btn = QPushButton(label)
            btn.setFixedHeight(self.BTN_H)
            btn.setMinimumWidth(self.BTN_MIN_W)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFont(QFont("Inter", 11, QFont.Weight.DemiBold))
            self._style_button(btn, role, primary=(i == default_btn_idx))
            btn.clicked.connect(
                lambda _checked=False, idx=i: self._on_btn(idx))
            btn_row.addWidget(btn)
            self._btn_widgets.append(btn)
        card_lay.addLayout(btn_row)

        # Default focus = default button (so Enter triggers it)
        if 0 <= default_btn_idx < len(self._btn_widgets):
            self._btn_widgets[default_btn_idx].setDefault(True)
            self._btn_widgets[default_btn_idx].setFocus()
        # Input widget pulls focus if present
        if input_widget is not None:
            input_widget.setFocus()
            if isinstance(input_widget, QLineEdit):
                input_widget.selectAll()
                input_widget.returnPressed.connect(
                    lambda: self._on_btn(default_btn_idx))

        self._clicked_idx = -1
        # Center the dialog over the parent's TOP-LEVEL WINDOW
        # using screen coordinates. Earlier this used parent.geometry()
        # — which returns geometry in the parent's parent's coordinate
        # system, NOT screen coordinates — so when ``parent`` was a
        # nested widget (e.g. AutoSchedule mounted inside MainWindow's
        # stack), the dialog moved to garbage screen coordinates and
        # could land off-screen or behind the main window. exec()
        # would block silently waiting for an invisible dialog, which
        # the operator experienced as "Delete Selected Clock button
        # does nothing." (2026-05-16 fix.)
        try:
            top_window = None
            if parent is not None and hasattr(parent, "window"):
                top_window = parent.window()
            if top_window is not None:
                # frameGeometry returns the window's position + size
                # in SCREEN coordinates (including title bar / frame).
                tg = top_window.frameGeometry()
                cx = tg.x() + tg.width() // 2
                cy = tg.y() + tg.height() // 2
            else:
                screen = QApplication.primaryScreen()
                if screen is not None:
                    geo = screen.availableGeometry()
                    cx = geo.center().x()
                    cy = geo.center().y()
                else:
                    cx, cy = 480, 360
            # Card is 460 wide; outer adds 24px shadow margin
            self.move(cx - self.CARD_W // 2 - 24, cy - 140)
        except Exception:
            pass

    # ── Painting (accent stripe lives here so it doesn't break
    #    the card's rounded top corners) ───────────────────────────
    def paintEvent(self, ev) -> None:
        super().paintEvent(ev)
        # Stripe is drawn ON TOP of the card frame, clipped to
        # the card's top edge with 12px radius.
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(self._accent)))
        cg = self._card.geometry()
        # Draw a thin rounded rect 3px tall sitting on top edge
        p.drawRoundedRect(
            cg.x() + 1, cg.y() + 1, cg.width() - 2, 4, 12, 12)
        # Mask off the lower half of that stripe so only the top
        # 3-4px curves naturally with the card
        # (the underlying rounded rect handles it)

    # ── Frameless drag handle (entire title row) ──────────────────
    def mousePressEvent(self, ev: QMouseEvent) -> None:
        if ev.button() == Qt.MouseButton.LeftButton:
            # Drag only when mouse is in the upper part of the card
            cg = self._card.geometry()
            local = ev.position().toPoint()
            if local.y() < cg.y() + 80:
                self._drag_origin = (
                    ev.globalPosition().toPoint() - self.pos())
                ev.accept()
                return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev: QMouseEvent) -> None:
        if (self._drag_origin is not None
                and ev.buttons() & Qt.MouseButton.LeftButton):
            new_pos = ev.globalPosition().toPoint() - self._drag_origin
            self.move(new_pos)
            ev.accept()
            return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev: QMouseEvent) -> None:
        self._drag_origin = None
        super().mouseReleaseEvent(ev)

    # ── Esc → cancel button ───────────────────────────────────────
    def keyPressEvent(self, ev: QKeyEvent) -> None:
        if ev.key() == Qt.Key.Key_Escape:
            if 0 <= self._cancel_btn_idx < len(self._btn_widgets):
                self._on_btn(self._cancel_btn_idx)
                return
        super().keyPressEvent(ev)

    # ── Button click handler ───────────────────────────────────────
    def _on_btn(self, idx: int) -> None:
        self._clicked_idx = idx
        # Convention: index 0 = primary (accept) for confirms,
        # index 1 = cancel; for info/warning/error, single button @ idx 0 = OK
        if idx == 0 and len(self._buttons) <= 2:
            self.accept()
        elif (idx == 0 and len(self._buttons) > 2):
            self.accept()
        else:
            self.reject()

    @staticmethod
    def _style_button(btn: QPushButton, role: str, *,
                       primary: bool) -> None:
        """Wire a button's stylesheet based on role + primary flag.

        Roles:
          * ``primary``    — cyan accent (Yes / OK / Save)
          * ``danger``     — red accent (Delete / Discard)
          * ``secondary``  — muted dark (Cancel / No)
        """
        if role == "danger":
            base = RED
            hover_alpha = 0.30
            border_color = RED
            text_color = "#ffffff"
            base_fill = RED
        elif role == "primary":
            base = CYAN
            hover_alpha = 0.30
            border_color = CYAN
            text_color = "#031419"
            base_fill = CYAN
        else:    # secondary
            base = TEXT_SEC
            hover_alpha = 0.15
            border_color = BORDER
            text_color = TEXT_PRI
            base_fill = BG_ELEVATED
        btn.setStyleSheet(
            f"QPushButton {{ "
            f"  background-color: {base_fill}; "
            f"  color: {text_color}; "
            f"  border: 1px solid {border_color}; "
            f"  border-radius: 8px; "
            f"  padding: 0 16px; "
            f"  font-weight: 600; }}"
            f"QPushButton:hover {{ "
            f"  background-color: {_rgba(base, hover_alpha + 0.15)}; "
            f"  border-color: {base}; "
            f"  color: {TEXT_PRI}; }}"
            f"QPushButton:pressed {{ "
            f"  background-color: {_rgba(base, hover_alpha + 0.30)}; }}"
            f"QPushButton:focus {{ "
            f"  outline: none; "
            f"  border: 1px solid {base}; }}")


# ════════════════════════════════════════════════════════════════════════════
# Public helpers
# ════════════════════════════════════════════════════════════════════════════


def confirm(parent: Optional[QWidget],
            title: str,
            text: str,
            *,
            danger: bool = False,
            yes_label: str = "Yes",
            no_label: str = "Cancel") -> bool:
    """Modal Yes/No confirm. Returns True if user clicked the primary
    button, False on Cancel or Esc. Pass ``danger=True`` for
    destructive actions (Delete, Discard) — primary button switches
    to red.

    Replaces ``QMessageBox.question(...)``."""
    accent = RED if danger else CYAN
    icon = "🗑" if danger else "?"
    role = "danger" if danger else "primary"
    dlg = _PremiumDialog(
        parent,
        title=title,
        body=text,
        icon=icon,
        accent=accent,
        buttons=[
            (yes_label, role),
            (no_label, "secondary"),
        ],
        default_btn_idx=0,
        cancel_btn_idx=1)
    dlg.exec()
    return dlg._clicked_idx == 0


def info(parent: Optional[QWidget],
         title: str,
         text: str,
         *,
         ok_label: str = "OK") -> None:
    """Single-button acknowledgement, cyan accent. Replaces
    ``QMessageBox.information(...)``."""
    dlg = _PremiumDialog(
        parent,
        title=title,
        body=text,
        icon="i",
        accent=CYAN,
        buttons=[(ok_label, "primary")],
        default_btn_idx=0,
        cancel_btn_idx=0)
    dlg.exec()


def warning(parent: Optional[QWidget],
            title: str,
            text: str,
            *,
            ok_label: str = "OK") -> None:
    """Single-button acknowledgement, amber accent. Replaces
    ``QMessageBox.warning(...)``."""
    dlg = _PremiumDialog(
        parent,
        title=title,
        body=text,
        icon="!",
        accent=AMBER,
        buttons=[(ok_label, "primary")],
        default_btn_idx=0,
        cancel_btn_idx=0)
    dlg.exec()


def error(parent: Optional[QWidget],
          title: str,
          text: str,
          *,
          ok_label: str = "OK") -> None:
    """Single-button acknowledgement, red accent. Replaces
    ``QMessageBox.critical(...)``."""
    dlg = _PremiumDialog(
        parent,
        title=title,
        body=text,
        icon="X",
        accent=RED,
        buttons=[(ok_label, "danger")],
        default_btn_idx=0,
        cancel_btn_idx=0)
    dlg.exec()


def text_input(parent: Optional[QWidget],
                 title: str,
                 prompt: str,
                 *,
                 default: str = "",
                 placeholder: str = "",
                 ok_label: str = "OK",
                 cancel_label: str = "Cancel"
                 ) -> Optional[str]:
    """Modal text input prompt. Returns the entered string, or
    ``None`` if the user cancelled. Replaces
    ``QInputDialog.getText(...)``."""
    edit = QLineEdit()
    edit.setText(default)
    if placeholder:
        edit.setPlaceholderText(placeholder)
    edit.setStyleSheet(
        f"QLineEdit {{ "
        f"background: {BG_ELEVATED}; "
        f"border: 1px solid {BORDER}; "
        f"border-radius: 6px; "
        f"color: {TEXT_PRI}; "
        f"padding: 8px 12px; "
        f"font: 12px 'Inter'; }}"
        f"QLineEdit:focus {{ border-color: {CYAN}; }}")
    edit.setMinimumHeight(36)
    dlg = _PremiumDialog(
        parent,
        title=title,
        body=prompt,
        icon="?",
        accent=CYAN,
        input_widget=edit,
        buttons=[
            (ok_label, "primary"),
            (cancel_label, "secondary"),
        ],
        default_btn_idx=0,
        cancel_btn_idx=1)
    dlg.exec()
    if dlg._clicked_idx == 0:
        return edit.text()
    return None


def int_input(parent: Optional[QWidget],
                title: str,
                prompt: str,
                *,
                default: int = 0,
                min_value: int = 0,
                max_value: int = 99_999,
                ok_label: str = "OK",
                cancel_label: str = "Cancel"
                ) -> Optional[int]:
    """Modal integer input prompt. Returns the entered int, or
    ``None`` if the user cancelled or entered an invalid number.
    Replaces ``QInputDialog.getInt(...)``."""
    edit = QLineEdit()
    edit.setText(str(default))
    edit.setStyleSheet(
        f"QLineEdit {{ "
        f"background: {BG_ELEVATED}; "
        f"border: 1px solid {BORDER}; "
        f"border-radius: 6px; "
        f"color: {TEXT_PRI}; "
        f"padding: 8px 12px; "
        f"font: 12px 'Inter'; }}"
        f"QLineEdit:focus {{ border-color: {CYAN}; }}")
    edit.setMinimumHeight(36)
    # Permissive — accept any digit/-+; validate on accept
    dlg = _PremiumDialog(
        parent,
        title=title,
        body=f"{prompt}\n\nRange: {min_value} to {max_value}",
        icon="#",
        accent=CYAN,
        input_widget=edit,
        buttons=[
            (ok_label, "primary"),
            (cancel_label, "secondary"),
        ],
        default_btn_idx=0,
        cancel_btn_idx=1)
    dlg.exec()
    if dlg._clicked_idx != 0:
        return None
    try:
        val = int(edit.text().strip())
    except (TypeError, ValueError):
        return None
    if val < min_value or val > max_value:
        return None
    return val
