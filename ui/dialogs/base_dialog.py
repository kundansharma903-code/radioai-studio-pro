"""
RadioAI Studio Pro — BaseDialog

Foundation class for all modal dialogs. Solves the overflow problem:
on smaller screens (e.g. 1366×768 laptops), Figma-sized dialogs (920×720)
would push their footer (Save / Cancel buttons) below the screen edge
because we used setFixedSize. Result: unreachable buttons.

This base class enforces a professional pattern:

1. ADAPTIVE SIZING
   The dialog never exceeds 95% × 92% of the available screen area.
   On a 1920×1080 it shows at the Figma target (e.g. 920×720). On a
   1366×768 laptop it shrinks to ≈920×680 and a scrollbar appears.

2. THREE-ZONE LAYOUT
   ┌─────────────────────────────┐
   │ HEADER  (fixed, no scroll)  │
   ├─────────────────────────────┤
   │ CONTENT (scrolls if needed) │
   ├─────────────────────────────┤
   │ FOOTER  (fixed, no scroll)  │
   └─────────────────────────────┘

   Save / Cancel are always reachable because the footer is pinned.

3. FRAMELESS WITH DRAG
   No OS title bar — the dialog renders its own header. Drag from
   anywhere on the header to move the dialog (matches Figma design).

Subclasses override:
    _build_header(self) -> QWidget       # pinned top
    _build_content(self) -> QWidget      # goes inside scroll area
    _build_footer(self) -> QWidget       # pinned bottom
"""

import logging

from PyQt6.QtCore import Qt, QPoint, QRectF
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QPainterPath
from PyQt6.QtWidgets import (
    QApplication, QDialog, QWidget, QFrame, QVBoxLayout, QScrollArea,
    QSizePolicy,
)

from ui.widgets._tokens import rgba, PURPLE

log = logging.getLogger("BaseDialog")


# Outer shadow padding around the dialog frame
SHADOW_PAD = 24


class BaseDialog(QDialog):
    """Base for premium frameless dialogs with adaptive sizing + scrollable
    middle zone."""

    HEADER_H_DEFAULT = 52
    FOOTER_H_DEFAULT = 52
    DLG_RADIUS = 12

    # Subclasses override these
    HEADER_H = HEADER_H_DEFAULT
    FOOTER_H = FOOTER_H_DEFAULT

    def __init__(self, target_size=(920, 720), parent=None):
        super().__init__(parent)
        self.setModal(True)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._drag_pos = None  # for header-drag-to-move support

        self._setup_size(target_size)
        self._setup_layout()

    # ── Adaptive sizing ───────────────────────────────────────────────────

    def _setup_size(self, target):
        """Cap the dialog at 95% × 92% of available screen, pad for outer
        shadow. Always centered on the available screen area."""
        target_w, target_h = target
        screen = QApplication.primaryScreen()
        if screen is None:
            avail = None
            max_w = target_w
            max_h = target_h
        else:
            avail = screen.availableGeometry()
            max_w = int(avail.width()  * 0.95)
            max_h = int(avail.height() * 0.92)

        # Final dialog frame size (excluding shadow padding)
        final_w = min(target_w, max_w)
        final_h = min(target_h, max_h)
        self._dlg_w = final_w
        self._dlg_h = final_h

        # Outer widget includes shadow padding
        self.resize(final_w + SHADOW_PAD * 2, final_h + SHADOW_PAD * 2)
        self.setMinimumSize(640 + SHADOW_PAD * 2, 480 + SHADOW_PAD * 2)
        self.setMaximumSize(max_w + SHADOW_PAD * 2, max_h + SHADOW_PAD * 2)

        # Center on screen
        if avail is not None:
            self.move(
                avail.x() + (avail.width()  - self.width())  // 2,
                avail.y() + (avail.height() - self.height()) // 2,
            )

    # ── Three-zone layout ─────────────────────────────────────────────────

    def _setup_layout(self):
        # Outer wrapper container — leaves SHADOW_PAD around the actual frame
        outer = QVBoxLayout(self)
        outer.setContentsMargins(SHADOW_PAD, SHADOW_PAD, SHADOW_PAD, SHADOW_PAD)
        outer.setSpacing(0)

        # Frame holds the actual dialog content. Painted via paintEvent.
        self._frame = QFrame()
        self._frame.setObjectName("dialogFrame")
        self._frame.setStyleSheet("background: transparent;")
        outer.addWidget(self._frame)

        zones = QVBoxLayout(self._frame)
        zones.setContentsMargins(0, 0, 0, 0)
        zones.setSpacing(0)

        # 1. HEADER (fixed)
        header = self._build_header()
        if header is not None:
            header.setFixedHeight(self.HEADER_H)
            header.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
            )
            self._header_widget = header
            zones.addWidget(header)
            # Enable drag-to-move from header
            header.installEventFilter(self)

        # 2. SCROLL AREA (flexible — takes all remaining vertical space)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            f"QScrollBar:vertical {{ background: {rgba('#ffffff', 0.02)}; "
            f"width: 8px; margin: 0; border: none; }}"
            f"QScrollBar::handle:vertical {{ background: {rgba(PURPLE, 0.45)}; "
            f"border-radius: 4px; min-height: 30px; margin: 2px; }}"
            f"QScrollBar::handle:vertical:hover {{ background: {rgba(PURPLE, 0.70)}; }}"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {"
            "  height: 0; background: transparent; border: none; }"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {"
            "  background: transparent; border: none; }"
        )

        content = self._build_content()
        self._scroll.setWidget(content)
        zones.addWidget(self._scroll, stretch=1)

        # 3. FOOTER (fixed)
        footer = self._build_footer()
        if footer is not None:
            footer.setFixedHeight(self.FOOTER_H)
            footer.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
            )
            self._footer_widget = footer
            zones.addWidget(footer)

    # ── Subclass hooks ────────────────────────────────────────────────────

    def _build_header(self) -> QWidget:
        """Override to provide the fixed-height header bar."""
        f = QFrame()
        f.setStyleSheet("background: #0d0f1e;")
        return f

    def _build_content(self) -> QWidget:
        """Override to provide the scrollable middle content."""
        f = QFrame()
        return f

    def _build_footer(self) -> QWidget:
        """Override to provide the fixed-height footer bar."""
        f = QFrame()
        f.setStyleSheet("background: #0d0f1e;")
        return f

    # ── Header drag-to-move ───────────────────────────────────────────────

    def eventFilter(self, obj, event):
        from PyQt6.QtCore import QEvent
        if obj is getattr(self, "_header_widget", None):
            if event.type() == QEvent.Type.MouseButtonPress and \
                    event.button() == Qt.MouseButton.LeftButton:
                self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                return False
            if event.type() == QEvent.Type.MouseMove and \
                    event.buttons() & Qt.MouseButton.LeftButton and \
                    self._drag_pos is not None:
                self.move(event.globalPosition().toPoint() - self._drag_pos)
                return False
            if event.type() == QEvent.Type.MouseButtonRelease:
                self._drag_pos = None
        return super().eventFilter(obj, event)

    # ── Backdrop + frame paint ────────────────────────────────────────────

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Dim backdrop fills the entire widget so the rest of the screen
        # behind us looks dimmed.
        p.fillRect(self.rect(), QColor(7, 8, 18, 180))

        # Soft shadow halo around the frame
        frame_rect = QRectF(
            SHADOW_PAD, SHADOW_PAD,
            self.width() - SHADOW_PAD * 2,
            self.height() - SHADOW_PAD * 2,
        )
        for i, alpha in enumerate([6, 14, 28]):
            pad = (3 - i) * 6
            halo = QRectF(
                frame_rect.x() - pad, frame_rect.y() - pad,
                frame_rect.width() + pad * 2, frame_rect.height() + pad * 2,
            )
            halo_path = QPainterPath()
            halo_path.addRoundedRect(halo, self.DLG_RADIUS + 4, self.DLG_RADIUS + 4)
            p.fillPath(halo_path, QColor(0, 0, 0, alpha))

        # Solid dialog background
        path = QPainterPath()
        path.addRoundedRect(frame_rect, self.DLG_RADIUS, self.DLG_RADIUS)
        p.setClipPath(path)
        p.fillRect(frame_rect, QColor("#0f1120"))
        # Top accent line 2px purple at 50%
        accent_rect = QRectF(frame_rect.x(), frame_rect.y(), frame_rect.width(), 2)
        accent = QColor(PURPLE); accent.setAlphaF(0.50)
        p.fillRect(accent_rect, accent)

        # Border
        p.setClipping(False)
        bc = QColor(PURPLE); bc.setAlphaF(0.35)
        p.setPen(QPen(bc, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(frame_rect, self.DLG_RADIUS, self.DLG_RADIUS)
