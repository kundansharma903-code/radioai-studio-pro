"""
PremiumTable — styled QTableWidget subclass.

No grid lines. Alternating row backgrounds.
Selected row: cyan accent + 2px left bar via custom delegate.
Header: Inter Black 9px uppercase, letter-spacing 1.2.
Smooth 4px scrollbar.
"""

from PyQt6.QtCore import Qt, QRect
from PyQt6.QtGui import QColor, QPainter, QFont, QBrush, QPen
from PyQt6.QtWidgets import (
    QTableWidget, QTableWidgetItem, QHeaderView, QStyledItemDelegate,
    QStyle, QStyleOptionViewItem,
)

from ._tokens import (
    inter, BG_DARK, BG_PANEL, BG_ELEVATED, TEXT_PRI, TEXT_SEC, TEXT_MUTED,
    CYAN, rgba, BORDER_RGBA,
)


class _RowDelegate(QStyledItemDelegate):
    """Paint alternating rows + selected row's accent bar."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = option.rect
        row = index.row()

        # Background
        if option.state & QStyle.StateFlag.State_Selected:
            bg = QColor(CYAN); bg.setAlphaF(0.12)
            painter.fillRect(rect, bg)
            # 2px left accent bar (only on first column to avoid stripes)
            if index.column() == 0:
                painter.fillRect(QRect(rect.x(), rect.y(), 2, rect.height()),
                                 QColor(CYAN))
        elif row % 2 == 0:
            painter.fillRect(rect, QColor(BG_DARK))
        else:
            c = QColor("#0d0f1e"); c.setAlphaF(0.4)
            painter.fillRect(rect, c)

        # Text
        text = index.data(Qt.ItemDataRole.DisplayRole)
        if text is not None:
            color = QColor(TEXT_PRI)
            if option.state & QStyle.StateFlag.State_Selected:
                color = QColor(CYAN)
            painter.setPen(color)
            font = inter(12, QFont.Weight.Medium)
            painter.setFont(font)
            painter.drawText(rect.adjusted(14, 0, -14, 0),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                             str(text))
        painter.restore()


class PremiumTable(QTableWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setShowGrid(False)
        self.setAlternatingRowColors(False)  # we paint manually
        self.setSelectionBehavior(self.SelectionBehavior.SelectRows)
        self.setEditTriggers(self.EditTrigger.NoEditTriggers)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.verticalHeader().setVisible(False)
        self.setItemDelegate(_RowDelegate(self))

        # Header
        h = self.horizontalHeader()
        h.setHighlightSections(False)
        h.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        h.setStretchLastSection(True)
        h.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        h.setMinimumSectionSize(80)
        h.setFixedHeight(40)
        header_font = inter(9, QFont.Weight.Black, letter_spacing=1.2)
        h.setFont(header_font)

        self.verticalHeader().setDefaultSectionSize(40)

        scrollbar_handle = rgba("#252840", 0.8)
        self.setStyleSheet(
            f"QTableWidget {{ "
            f"  background: {BG_DARK}; "
            f"  border: 1px solid {BORDER_RGBA}; "
            f"  border-radius: 12px; "
            f"  outline: none; "
            f"  gridline-color: transparent; "
            f"}}"
            f"QHeaderView::section {{ "
            f"  background: {BG_ELEVATED}; "
            f"  color: {TEXT_MUTED}; "
            f"  border: none; "
            f"  border-bottom: 1px solid {BORDER_RGBA}; "
            f"  padding: 8px 14px; "
            f"  text-transform: uppercase; "
            f"}}"
            f"QScrollBar:vertical {{ "
            f"  background: transparent; width: 4px; margin: 0; "
            f"}}"
            f"QScrollBar::handle:vertical {{ "
            f"  background: {scrollbar_handle}; border-radius: 2px; "
            f"}}"
            f"QScrollBar::handle:vertical:hover {{ background: {TEXT_SEC}; }}"
            f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}"
        )

    # ── Convenience ───────────────────────────────────────────────────────
    def add_row(self, cells: list):
        r = self.rowCount()
        self.insertRow(r)
        for c, v in enumerate(cells):
            self.setItem(r, c, QTableWidgetItem(str(v)))
