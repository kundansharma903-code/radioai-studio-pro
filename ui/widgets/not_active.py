"""
Shared "not active in this version" marker for Settings screens.

Some settings controls save a value that nothing in the app reads yet.
Rather than let the operator believe they work, each such control is
disabled, given a tooltip and its label gets a muted "coming soon"
suffix. Pure native PyQt6.
"""

from __future__ import annotations

from PyQt6.QtWidgets import QLabel, QWidget

from core.constants import TEXT_MUTED

NOT_ACTIVE_TIP = "Not active in this version"
COMING_SOON_SUFFIX = "  · coming soon"


def mark_not_active(widget: QWidget, label=None) -> None:
    """Disable `widget`, set the tooltip, and suffix its label with a
    muted "coming soon". `label`: a QLabel, None (auto-find the
    widget's ``_lbl`` / first QLabel child) or False (no label edit).
    Idempotent."""
    if widget is None:
        return
    widget.setEnabled(False)
    widget.setToolTip(NOT_ACTIVE_TIP)
    widget.setProperty("not_active", True)
    if label is False:
        return
    if label is None:
        label = getattr(widget, "_lbl", None)
    if label is None:
        label = widget.findChild(QLabel)
    if isinstance(label, QLabel):
        txt = label.text()
        if COMING_SOON_SUFFIX.strip() not in txt:
            label.setText(txt + COMING_SOON_SUFFIX)
        label.setToolTip(NOT_ACTIVE_TIP)
        label.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; border: none;")


def is_not_active(widget: QWidget) -> bool:
    return bool(widget is not None and widget.property("not_active"))
