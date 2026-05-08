"""
RadioAI Studio Pro — Jingles Library
Pixel-accurate match of Figma node 44:2 (file 7oN9K61g94wKx3nu44KKDF).

Layout (1440×900):
  Header           y=0..72         Logo, breadcrumb, title, clock, Open Studio
  Sidebar          y=72..850, x=0..220       Counter + actions + filters +
                                              integration links
  Table area       y=72..850, x=220..980     Header strip + scrollable rows +
                                              Audio Preview scrubber
  Right details    y=72..850, x=982..1440    Tabs + selected-jingle card +
                                              form + Audio Preview + Scheduling
                                              + AI insight + 7-day stat
  Status bar       y=850..900, 1440×50       Pills + version + Open Studio mini

Backend: existing `jingles` schema (id, name, category, file_path, duration_ms,
properties, playlister_code, is_enabled, display_order). No migration needed
for this screen — the editor dialog (Figma 106:2, separate commit) lands the
extra columns (auto_code, author, comments, bpm, etc.).

Phase status:
  [✓] header / sidebar / table / details panel / status bar / live clock
  [ ] + Add New Jingle → opens 106:2 dialog (separate commit)
  [ ] Mass Import / Edit Categories / Delete / Export to Playlister
      (toast stubs — same pattern as Sweepers Library)
  [ ] Schedule + Usage Stats tabs (placeholder content)
  [ ] Audio scrubber wires to AudioEngine for actual preview
  [ ] last_used pulls from broadcast_log
"""

from __future__ import annotations

import logging
from typing import Optional
from datetime import datetime

from PyQt6.QtCore import (
    Qt, QRectF, QTimer, pyqtSignal,
)
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QLinearGradient, QPainterPath, QFont,
    QCursor,
)
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QHBoxLayout, QVBoxLayout,
    QScrollArea, QMessageBox, QLineEdit,
)

from core.settings import Settings
from ui.widgets._tokens import (
    inter, mono, rgba,
    BG_BASE, BG_PANEL, BG_CARD, BG_ELEVATED,
    TEXT_PRI, TEXT_SEC, TEXT_MUTED, TEXT_DIM,
    CYAN, CYAN_LIGHT, PURPLE, PURPLE_LIGHT, PURPLE_DARK, GREEN, GREEN_LIGHT,
    AMBER, AMBER_LIGHT, RED, RED_LIGHT, PINK, PINK_LIGHT, TEAL, TEAL_LIGHT,
)

log = logging.getLogger("JinglesLibrary")


# ════════════════════════════════════════════════════════════════════════════
# Geometry tokens
# ════════════════════════════════════════════════════════════════════════════

WINDOW_W = 1440
WINDOW_H = 900
HEADER_H = 72
STATUS_H = 50

SIDEBAR_W = 220

TABLE_X0 = 220
TABLE_W  = 760
TABLE_X1 = TABLE_X0 + TABLE_W              # 980

RIGHT_X = 982
RIGHT_W = WINDOW_W - RIGHT_X               # 458

ROW_H        = 38
TABLE_HDR_H  = 32

# Center column slots (relative to table area top y0=HEADER_H)
TABLE_BODY_H        = WINDOW_H - HEADER_H - STATUS_H - TABLE_HDR_H - 60  # ~626
SCRUBBER_H          = 50    # bottom of center column

# Categories — 8 tiles in the editor dialog 4×2 grid (Figma 106:2).
# Mirrored here so the filter dropdown + table-cell colors stay in
# lockstep with the dialog the operator just used to add the jingle.
CATEGORIES = [
    "Station ID",
    "Shotguns",
    "Ad Break",
    "News Break",
    "Weather",
    "Traffic",
    "Promo",
    "Signature",
]

CATEGORY_FILTER_OPTIONS = ["All Categories"] + CATEGORIES

CATEGORY_COLORS = {
    "Station ID":  AMBER,
    "Shotguns":    PURPLE_LIGHT,
    "Ad Break":    RED,
    "News Break":  TEAL_LIGHT,
    "Weather":     CYAN,
    "Traffic":     PURPLE,
    "Promo":       PINK,
    "Signature":   GREEN,
}

# Properties column values from the Figma library frame. Free-form
# string in the DB, but these are the canonical values.
PROPERTIES_FILTER_OPTIONS = [
    "All Properties",
    "Top of Hour",
    "Regular",
    "Special",
    "Signature",
    "News",
    "Ads",
    "Info",
    "Promo",
]

DURATION_FILTER_OPTIONS = [
    "All Durations",
    "Under 5s",
    "5–10s",
    "Over 10s",
]

DETAIL_TABS = ("Jingle Details", "Schedule", "Usage Stats")


def _fmt_duration(ms: int) -> str:
    s = int((ms or 0) // 1000)
    return f"{s // 60}:{s % 60:02d}"


def _category_color(name: str) -> str:
    return CATEGORY_COLORS.get((name or "").strip(), TEXT_MUTED)


# ════════════════════════════════════════════════════════════════════════════
# Header chrome — reused with minor tweaks from sweepers_library.
# Self-contained so a future ui/widgets/library_chrome.py extraction
# can pick these up cleanly.
# ════════════════════════════════════════════════════════════════════════════


class _HeaderLogo(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(40, 40)

    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Soft purple-cyan gradient disc
        g = QLinearGradient(0, 0, self.width(), self.height())
        g.setColorAt(0.0, QColor(CYAN))
        g.setColorAt(1.0, QColor(PURPLE))
        p.setBrush(QBrush(g)); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(2, 2, self.width() - 4, self.height() - 4)
        # 5 vertical bars (the speaker / equalizer mark)
        p.setPen(QPen(QColor(255, 255, 255, 230), 2))
        cx, cy = self.width() / 2, self.height() / 2
        for i, h in enumerate([6, 10, 14, 10, 6]):
            x = cx - 8 + i * 4
            p.drawLine(int(x), int(cy - h / 2), int(x), int(cy + h / 2))
        p.end()


class _HeaderOpenStudio(QPushButton):
    def __init__(self, parent=None):
        super().__init__("▶  Open Studio", parent)
        self.setFixedSize(110, 40)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFont(inter(11, QFont.Weight.Bold))
        self.setStyleSheet(
            f"QPushButton {{ background: qlineargradient("
            f"x1:0,y1:0,x2:0,y2:1, stop:0 {GREEN_LIGHT}, stop:1 {GREEN}); "
            f"color: white; border: none; border-radius: 8px; }}"
            f"QPushButton:hover {{ background: qlineargradient("
            f"x1:0,y1:0,x2:0,y2:1, stop:0 #34d399, stop:1 {GREEN}); }}"
        )


class _ActiveBreadcrumbChip(QFrame):
    """🔔 Jingles — the active breadcrumb crumb."""

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self.setFixedSize(120, 32)
        self.setStyleSheet(
            f"QFrame {{ background: {rgba(AMBER, 0.18)}; "
            f"border: 1px solid {rgba(AMBER, 0.40)}; border-radius: 16px; }}"
        )
        h = QHBoxLayout(self)
        h.setContentsMargins(12, 0, 14, 0); h.setSpacing(6)
        ic = QLabel("🔔", self)
        ic.setFont(inter(11, QFont.Weight.Medium))
        ic.setStyleSheet(
            f"color: {AMBER_LIGHT}; background: transparent; border: none;")
        h.addWidget(ic)
        lbl = QLabel(label, self)
        lbl.setFont(inter(11, QFont.Weight.Bold))
        lbl.setStyleSheet(
            f"color: {AMBER_LIGHT}; background: transparent; border: none;")
        h.addWidget(lbl)
        h.addStretch()


# ════════════════════════════════════════════════════════════════════════════
# Sidebar widgets
# ════════════════════════════════════════════════════════════════════════════


class _SidebarCounter(QFrame):
    """Compact pill: '16 Jingles' + active-of-total beneath."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(SIDEBAR_W - 24, 44)
        self._active = 0
        self._total = 0
        self.setStyleSheet(
            f"QFrame {{ background: {rgba(AMBER, 0.10)}; "
            f"border: 1px solid {rgba(AMBER, 0.30)}; border-radius: 8px; }}"
        )
        self._big = QLabel("0", self)
        self._big.setGeometry(12, 6, 60, 20)
        self._big.setFont(mono(15, bold=True))
        self._big.setStyleSheet(
            f"color: {AMBER_LIGHT}; background: transparent; border: none;")
        self._sub = QLabel("Jingles", self)
        self._sub.setGeometry(50, 8, 100, 16)
        self._sub.setFont(inter(10, QFont.Weight.Medium))
        self._sub.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent; border: none;")
        self._meta = QLabel("0 enabled", self)
        self._meta.setGeometry(12, 24, 180, 14)
        self._meta.setFont(inter(9))
        self._meta.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; border: none;")

    def set_counts(self, active: int, total: int) -> None:
        self._active = int(active); self._total = int(total)
        self._big.setText(str(total))
        self._meta.setText(f"{active} enabled")


class _SidebarActionButton(QPushButton):
    """Tinted pill button. Used by Add / Mass Import / Edit / Delete /
    Export / Prefix slots."""

    def __init__(self, text: str, color: str, bg_tint: str, parent=None):
        super().__init__(text, parent)
        self.setFixedSize(SIDEBAR_W - 24, 30)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFont(inter(10, QFont.Weight.DemiBold))
        self.setStyleSheet(
            f"QPushButton {{ background: {bg_tint}; color: {color}; "
            f"border: 1px solid {rgba(color, 0.35)}; border-radius: 6px; "
            f"text-align: left; padding-left: 12px; }}"
            f"QPushButton:hover {{ background: {rgba(color, 0.18)}; "
            f"border: 1px solid {rgba(color, 0.55)}; }}"
        )


class _SidebarDropdown(QPushButton):
    """Filter dropdown — paints a chevron on the right. Behaviour stub:
    cycles through the option list on click. The Figma frame doesn't
    spec a real popup, just the closed pill."""

    picked = pyqtSignal(str)

    def __init__(self, label: str, options: list[str], parent=None):
        super().__init__(parent)
        self.setFixedSize(SIDEBAR_W - 24, 30)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._options = list(options)
        self._idx = 0
        self._label = label
        self.setFont(inter(10, QFont.Weight.Medium))
        self._refresh_label()
        self.setStyleSheet(
            f"QPushButton {{ background: {BG_CARD}; color: {TEXT_SEC}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; border-radius: 6px; "
            f"text-align: left; padding-left: 10px; padding-right: 22px; }}"
            f"QPushButton:hover {{ border: 1px solid {rgba(CYAN, 0.40)}; }}"
        )
        self.clicked.connect(self._cycle)

    def _refresh_label(self) -> None:
        self.setText(self._options[self._idx])

    def _cycle(self) -> None:
        self._idx = (self._idx + 1) % len(self._options)
        self._refresh_label()
        self.picked.emit(self._options[self._idx])

    def current(self) -> str:
        return self._options[self._idx]

    def paintEvent(self, e):
        super().paintEvent(e)
        # Right-side caret
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(TEXT_MUTED), 1.2))
        cx = self.width() - 14
        cy = self.height() / 2
        p.drawLine(int(cx - 4), int(cy - 2), int(cx), int(cy + 2))
        p.drawLine(int(cx + 4), int(cy - 2), int(cx), int(cy + 2))
        p.end()


class _OnlyEnabledCheckbox(QPushButton):
    """Custom checkable pill — operator toggles 'Only Enabled' filter."""

    toggled_picked = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(SIDEBAR_W - 24, 28)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setText("☐  Only Enabled")
        self.setFont(inter(10, QFont.Weight.Medium))
        self.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {TEXT_SEC}; "
            f"border: none; text-align: left; padding-left: 4px; }}"
            f"QPushButton:hover {{ color: {TEXT_PRI}; }}"
            f"QPushButton:checked {{ color: {GREEN_LIGHT}; }}"
        )
        self.toggled.connect(self._on_toggled)

    def _on_toggled(self, checked: bool) -> None:
        self.setText(("☑  " if checked else "☐  ") + "Only Enabled")
        self.toggled_picked.emit(bool(checked))


# ════════════════════════════════════════════════════════════════════════════
# Center column — table header, row, scrubber
# ════════════════════════════════════════════════════════════════════════════


class _Pill(QWidget):
    """Capsule label used for category + properties cells."""

    def __init__(self, text: str, color: str, parent=None):
        super().__init__(parent)
        self._text = text or "—"
        self._color = color
        self.setFixedSize(110, 22)

    def set_text(self, text: str, color: str) -> None:
        self._text = text or "—"; self._color = color; self.update()

    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0, 0, self.width(), self.height())
        col = QColor(self._color)
        p.setBrush(QColor(col.red(), col.green(), col.blue(), 50))
        p.setPen(QPen(QColor(col.red(), col.green(), col.blue(), 110), 1))
        p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 11, 11)
        p.setPen(QColor(self._color))
        p.setFont(inter(9, QFont.Weight.Bold, letter_spacing=0.4))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._text)
        p.end()


class _TableHeader(QFrame):
    """Column header strip — Name / Category / Duration / Properties /
    Last Used."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"QFrame {{ background: {rgba('#ffffff', 0.02)}; "
            f"border-bottom: 1px solid {rgba('#ffffff', 0.06)}; "
            f"border-top-left-radius: 8px; border-top-right-radius: 8px; }}"
        )
        # Name (220), Category (120), Duration (60), Properties (120),
        # Last Used (110), play (40 right gutter)
        positions = [
            ("Jingle Name", 16, 220),
            ("Category",   240, 120),
            ("Duration",   368,  60),
            ("Properties", 444, 120),
            ("Last Used",  580, 110),
        ]
        for txt, x, w in positions:
            l = QLabel(txt, self)
            l.setGeometry(x, 0, w, TABLE_HDR_H)
            l.setFont(inter(9, QFont.Weight.Bold, letter_spacing=1.0))
            l.setStyleSheet(
                f"QLabel {{ color: {TEXT_MUTED}; background: transparent; "
                f"border: none; }}")
            l.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)


class _JingleRow(QFrame):
    """Single jingle table row — bell icon + name + pills + last-used
    + play arrow. Click selects, double-click would open the editor
    (wired to the screen's signal handler)."""

    clicked        = pyqtSignal(int)   # jingle_id
    double_clicked = pyqtSignal(int)
    play_clicked   = pyqtSignal(int)

    ROW_H = ROW_H

    def __init__(self, jingle: dict, parent=None):
        super().__init__(parent)
        self._jingle = jingle
        self._selected = False
        self._hover = False
        self._playing = False     # flips when this row's preview is on
        self.setFixedSize(TABLE_W, self.ROW_H)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        # Inner widgets
        self._cat_pill = _Pill(
            jingle.get("category") or "—",
            _category_color(jingle.get("category") or ""),
            self)
        self._cat_pill.move(240, (self.ROW_H - 22) // 2)
        self._props_pill = _Pill(
            jingle.get("properties") or "—",
            CYAN,
            self)
        self._props_pill.move(444, (self.ROW_H - 22) // 2)

    @property
    def jingle_id(self) -> int:
        return int(self._jingle.get("id") or 0)

    def set_selected(self, sel: bool) -> None:
        self._selected = sel; self.update()

    def set_playing(self, playing: bool) -> None:
        """Flip the right-gutter glyph between ▶ (idle) and ■ (preview
        live). Only the row whose preview is currently airing has this
        on; the screen handles the swap when previews start/stop."""
        if self._playing == playing:
            return
        self._playing = bool(playing)
        self.update()

    def enterEvent(self, e):
        self._hover = True; self.update(); super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False; self.update(); super().leaveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            # Right gutter (last 40px) treated as a play hit zone.
            if e.position().x() >= TABLE_W - 40:
                self.play_clicked.emit(self.jingle_id)
                return
            self.clicked.emit(self.jingle_id)
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit(self.jingle_id)
        super().mouseDoubleClickEvent(e)

    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0, 0, self.width(), self.height())
        if self._selected:
            p.fillRect(rect, QColor(rgba(CYAN, 0.10)))
            p.setPen(QPen(QColor(rgba(CYAN, 0.40)), 1))
            p.drawLine(0, 0, 0, self.height())
        elif self._hover:
            p.fillRect(rect, QColor(rgba('#ffffff', 0.03)))

        # Bottom border
        p.setPen(QPen(QColor(rgba('#ffffff', 0.05)), 1))
        p.drawLine(0, self.height() - 1, self.width(), self.height() - 1)

        # Bell icon dot
        col = QColor(_category_color(self._jingle.get("category") or ""))
        p.setBrush(col); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(20, int(self.height() / 2 - 4), 8, 8)

        # Name
        p.setPen(QColor(TEXT_PRI if self._selected else TEXT_SEC))
        p.setFont(inter(11, QFont.Weight.DemiBold))
        p.drawText(QRectF(40, 0, 200, self.height()),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._jingle.get("name") or "—")

        # Duration (between cat and props pills)
        p.setPen(QColor(TEXT_SEC))
        p.setFont(mono(10, bold=True))
        p.drawText(QRectF(368, 0, 60, self.height()),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   _fmt_duration(self._jingle.get("duration_ms") or 0))

        # Last used (right-side text column)
        p.setPen(QColor(TEXT_MUTED)); p.setFont(inter(10))
        p.drawText(QRectF(580, 0, 110, self.height()),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._jingle.get("last_used_label") or "—")

        # Play / Stop glyph (right gutter) — flips when previewing.
        glyph_color = QColor(GREEN_LIGHT) if self._playing else QColor(AMBER_LIGHT)
        p.setPen(glyph_color)
        p.setFont(inter(11, QFont.Weight.Black))
        p.drawText(QRectF(self.width() - 32, 0, 24, self.height()),
                   Qt.AlignmentFlag.AlignCenter,
                   "■" if self._playing else "▶")
        p.end()


class _AudioScrubber(QFrame):
    """Audio preview footer — cosmetic only for now (preview wiring
    matches the sweepers_library deferred carry-over)."""

    play_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"QFrame {{ background: {BG_CARD}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; "
            f"border-radius: 8px; }}"
        )
        self._title = "—"
        self._meta = "Select a jingle"

        self._play = QPushButton("▶", self)
        self._play.setFixedSize(36, 36)
        self._play.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._play.setFont(inter(13, QFont.Weight.Black))
        self._play.setStyleSheet(
            f"QPushButton {{ background: {rgba(CYAN, 0.20)}; "
            f"color: {CYAN_LIGHT}; "
            f"border: 1px solid {rgba(CYAN, 0.45)}; border-radius: 18px; }}"
            f"QPushButton:hover {{ background: {rgba(CYAN, 0.30)}; }}"
        )
        self._play.clicked.connect(self.play_clicked.emit)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._play.move(8, (self.height() - 36) // 2)

    def set_track(self, title: str, meta: str) -> None:
        self._title = title or "—"; self._meta = meta or ""
        self.update()

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Title + meta block, right of play button
        p.setPen(QColor(TEXT_PRI))
        p.setFont(inter(10, QFont.Weight.Bold))
        p.drawText(QRectF(54, 8, self.width() - 70, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._title)
        p.setPen(QColor(TEXT_MUTED)); p.setFont(inter(9))
        p.drawText(QRectF(54, 24, self.width() - 70, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._meta)
        # Decorative waveform strip — bars from cyan→purple
        bar_x = 200
        bar_w = self.width() - bar_x - 14
        if bar_w > 60:
            for i in range(0, bar_w, 4):
                t = i / max(bar_w, 1)
                hue_color = QColor(CYAN) if t < 0.5 else QColor(PURPLE_LIGHT)
                hue_color.setAlpha(160 - int(abs(0.5 - t) * 200))
                # Sin-ish height variation (cheap deterministic curve)
                h = 6 + int(((i * 7) % 16))
                cx = bar_x + i
                cy = self.height() // 2
                p.fillRect(cx, cy - h // 2, 2, h, hue_color)
        p.end()


# ════════════════════════════════════════════════════════════════════════════
# Right details panel
# ════════════════════════════════════════════════════════════════════════════


class _DetailTabBar(QFrame):
    """Jingle Details / Schedule / Usage Stats tab strip."""

    tab_picked = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tabs: list[QPushButton] = []
        self._active = DETAIL_TABS[0]
        h = QHBoxLayout(self)
        h.setContentsMargins(12, 8, 12, 0); h.setSpacing(4)
        for name in DETAIL_TABS:
            btn = QPushButton(name, self)
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn.setFont(inter(10, QFont.Weight.DemiBold))
            btn.setFixedHeight(28)
            btn.clicked.connect(
                lambda _checked=False, n=name: self._on_pick(n))
            self._tabs.append(btn)
            h.addWidget(btn)
        h.addStretch()
        self._refresh_styles()

    def _on_pick(self, name: str):
        if name == self._active:
            return
        self._active = name
        self._refresh_styles()
        self.tab_picked.emit(name)

    def active(self) -> str:
        return self._active

    def _refresh_styles(self) -> None:
        for btn in self._tabs:
            if btn.text() == self._active:
                btn.setStyleSheet(
                    f"QPushButton {{ background: transparent; "
                    f"color: {AMBER_LIGHT}; border: none; "
                    f"border-bottom: 2px solid {AMBER}; "
                    f"padding-left: 8px; padding-right: 8px; }}")
            else:
                btn.setStyleSheet(
                    f"QPushButton {{ background: transparent; "
                    f"color: {TEXT_MUTED}; border: none; "
                    f"border-bottom: 2px solid transparent; "
                    f"padding-left: 8px; padding-right: 8px; }}"
                    f"QPushButton:hover {{ color: {TEXT_SEC}; }}")


class _DetailsHeaderCard(QFrame):
    """The card directly under the tab strip — bell + title + meta +
    Enabled/Disabled badge."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"QFrame {{ background: {BG_CARD}; "
            f"border: 1px solid {rgba(AMBER, 0.30)}; border-radius: 8px; }}"
        )
        self._title_lbl = QLabel("—", self)
        self._title_lbl.setGeometry(60, 12, RIGHT_W - 80, 18)
        self._title_lbl.setFont(inter(13, QFont.Weight.Bold))
        self._title_lbl.setStyleSheet(
            f"color: {TEXT_PRI}; background: transparent; border: none;")
        self._meta_lbl = QLabel("Select a jingle", self)
        self._meta_lbl.setGeometry(60, 32, RIGHT_W - 80, 14)
        self._meta_lbl.setFont(inter(10))
        self._meta_lbl.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; border: none;")
        self._badge = QLabel("Enabled", self)
        self._badge.setGeometry(60, 50, 80, 16)
        self._badge.setFont(inter(8, QFont.Weight.Bold, letter_spacing=1.0))
        self._badge.setStyleSheet(
            f"QLabel {{ color: {GREEN_LIGHT}; "
            f"background: {rgba(GREEN, 0.18)}; "
            f"border: 1px solid {rgba(GREEN, 0.40)}; "
            f"border-radius: 8px; padding-left: 8px; padding-right: 8px; }}")
        self._badge.setVisible(False)

    def set_jingle(self, j: dict) -> None:
        self._title_lbl.setText(j.get("name") or "—")
        cat  = j.get("category") or "—"
        dur  = _fmt_duration(j.get("duration_ms") or 0)
        prop = j.get("properties") or "—"
        self._meta_lbl.setText(f"{cat} · {dur} · {prop}")
        if not j:
            self._badge.setVisible(False)
            return
        self._badge.setVisible(True)
        if j.get("is_enabled", True):
            self._badge.setText("Enabled")
            self._badge.setStyleSheet(
                f"QLabel {{ color: {GREEN_LIGHT}; "
                f"background: {rgba(GREEN, 0.18)}; "
                f"border: 1px solid {rgba(GREEN, 0.40)}; "
                f"border-radius: 8px; padding-left: 8px; padding-right: 8px; }}")
        else:
            self._badge.setText("Disabled")
            self._badge.setStyleSheet(
                f"QLabel {{ color: {RED_LIGHT}; "
                f"background: {rgba(RED, 0.18)}; "
                f"border: 1px solid {rgba(RED, 0.40)}; "
                f"border-radius: 8px; padding-left: 8px; padding-right: 8px; }}")

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Bell icon disc on the left
        p.setBrush(QColor(rgba(AMBER, 0.20)))
        p.setPen(QPen(QColor(rgba(AMBER, 0.45)), 1))
        p.drawEllipse(14, 14, 36, 36)
        p.setPen(QColor(AMBER_LIGHT))
        p.setFont(inter(15, QFont.Weight.Bold))
        p.drawText(QRectF(14, 14, 36, 36),
                   Qt.AlignmentFlag.AlignCenter, "🔔")
        p.end()


class _DetailsField(QFrame):
    """Stacked label + readonly value used for each detail row."""

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self._value = "—"
        self._label_lbl = QLabel(label, self)
        self._label_lbl.setGeometry(0, 0, RIGHT_W - 28, 14)
        self._label_lbl.setFont(inter(9, QFont.Weight.Medium))
        self._label_lbl.setStyleSheet(
            f"QLabel {{ color: {TEXT_MUTED}; background: transparent; "
            f"border: none; }}")
        self._value_lbl = QLabel("—", self)
        self._value_lbl.setGeometry(0, 18, RIGHT_W - 28, 28)
        self._value_lbl.setFont(inter(11, QFont.Weight.DemiBold))
        self._value_lbl.setStyleSheet(
            f"QLabel {{ color: {TEXT_PRI}; "
            f"background: {BG_CARD}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; "
            f"border-radius: 6px; padding-left: 10px; }}")

    def set_value(self, v: str) -> None:
        self._value = v or "—"
        self._value_lbl.setText(self._value)


# ════════════════════════════════════════════════════════════════════════════
# Main screen
# ════════════════════════════════════════════════════════════════════════════


class JinglesLibrary(QWidget):

    breadcrumb_clicked = pyqtSignal(str)
    studio_clicked     = pyqtSignal()
    jingle_selected    = pyqtSignal(int)
    add_jingle_clicked = pyqtSignal()      # for future 106:2 dialog hook

    # 15s preview cap matches the Songs Library convention. Long
    # enough that the operator hears the hook of any reasonable jingle,
    # short enough that an accidental click doesn't spew audio.
    PREVIEW_DURATION_MS = 15000
    PREVIEW_VOLUME = 80          # monitor-loudness, not on-air

    def __init__(self, db, parent=None, engine=None):
        super().__init__(parent)
        self._db = db
        self._engine = engine          # AudioEngine — wired for preview play

        # State
        self._jingles: list[dict] = []
        self._row_widgets: list[_JingleRow] = []
        self._selected_id: Optional[int] = None
        self._category_filter: str = "All Categories"
        self._properties_filter: str = "All Properties"
        self._duration_filter: str = "All Durations"
        self._only_enabled: bool = False
        self._search_text: str = ""

        # Preview-channel state — shared by row ▶ icon + right-panel
        # scrubber ▶ button. Single channel; switching jingles cleans
        # up the previous one.
        self._preview_cid: Optional[int] = None
        self._preview_jingle_id: Optional[int] = None
        self._preview_timer: Optional[QTimer] = None

        # Refs
        self._table_layout: Optional[QVBoxLayout] = None
        self._counter: Optional[_SidebarCounter] = None
        self._clock_lbl: Optional[QLabel] = None
        self._search_edit: Optional[QLineEdit] = None
        self._cat_dropdown: Optional[_SidebarDropdown] = None
        self._props_dropdown: Optional[_SidebarDropdown] = None
        self._dur_dropdown: Optional[_SidebarDropdown] = None
        self._only_enabled_chk: Optional[_OnlyEnabledCheckbox] = None
        self._tab_bar: Optional[_DetailTabBar] = None
        self._details_card: Optional[_DetailsHeaderCard] = None
        self._details_fields: dict[str, _DetailsField] = {}
        self._scrubber: Optional[_AudioScrubber] = None
        self._status_count: Optional[QLabel] = None
        self._details_sub: Optional[QLabel] = None
        self._stats_card: Optional[QLabel] = None

        self.setFixedSize(WINDOW_W, WINDOW_H)
        self.setStyleSheet(
            "background: qlineargradient("
            "x1:0, y1:0, x2:1, y2:1, "
            "stop:0 #0a0d1a, stop:0.5 #06080f, stop:1 #020308);"
        )

        self._build_header()
        self._build_sidebar()
        self._build_center()
        self._build_right_panel()
        self._build_status_bar()

        self._load_jingles()

        # Engine EOS hookup so the row glyph + scrubber state reset
        # when the preview ends naturally (15s cap typically beats it).
        if self._engine is not None and hasattr(self._engine, "playback_ended"):
            try:
                self._engine.playback_ended.connect(
                    self._on_engine_playback_ended)
            except Exception as exc:
                log.debug(f"engine signal hookup failed: {exc}")

        # Live clock
        self._tick()
        t = QTimer(self)
        t.setInterval(1000); t.timeout.connect(self._tick); t.start()

        log.info("JinglesLibrary ready (Figma 44:2)")

    # ── HEADER ───────────────────────────────────────────────────────────

    def _build_header(self):
        bg = QFrame(self)
        bg.setGeometry(0, 0, WINDOW_W, HEADER_H)
        bg.setStyleSheet(
            f"background: qlineargradient(x1:0,y1:0,x2:0,y2:1, "
            f"stop:0 rgba(16,19,31,0.95), stop:1 rgba(10,12,22,0.95)); "
            f"border-bottom: 1px solid {rgba('#ffffff', 0.06)};"
        )
        hl = QFrame(self)
        hl.setGeometry(0, HEADER_H - 1, WINDOW_W, 1)
        hl.setStyleSheet(
            "background: qlineargradient(x1:0,y1:0,x2:1,y2:0, "
            "stop:0 rgba(255,255,255,0), stop:0.5 rgba(255,255,255,0.10), "
            "stop:1 rgba(255,255,255,0));"
        )
        _HeaderLogo(self).move(14, 16)
        l = QLabel("RadioAI", self)
        l.setGeometry(64, 14, 120, 18)
        l.setFont(inter(15, QFont.Weight.Bold))
        l.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        l = QLabel("STUDIO PRO", self)
        l.setGeometry(64, 34, 120, 12)
        l.setFont(inter(8, QFont.Weight.Bold, letter_spacing=1.2))
        l.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

        # Breadcrumb: Control Panel | Libraries | 🔔 Jingles
        cp_btn = QPushButton("Control Panel", self)
        cp_btn.setGeometry(170, 22, 100, 22)
        cp_btn.setFont(inter(11, QFont.Weight.Medium))
        cp_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        cp_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {TEXT_MUTED}; "
            f"border: none; padding: 0; text-align: left; }}"
            f"QPushButton:hover {{ color: {TEXT_PRI}; }}"
        )
        cp_btn.clicked.connect(
            lambda: self.breadcrumb_clicked.emit("control_panel"))

        sep = QLabel("|", self); sep.setGeometry(266, 22, 8, 22)
        sep.setFont(inter(11))
        sep.setStyleSheet(f"color: {TEXT_DIM}; background: transparent;")

        l = QLabel("Libraries", self)
        l.setGeometry(276, 22, 60, 22)
        l.setFont(inter(11, QFont.Weight.Medium))
        l.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

        sep2 = QLabel("|", self); sep2.setGeometry(336, 22, 8, 22)
        sep2.setFont(inter(11))
        sep2.setStyleSheet(f"color: {TEXT_DIM}; background: transparent;")

        chip = _ActiveBreadcrumbChip("Jingles", self)
        chip.move(348, 20)

        # Title + subtitle
        l = QLabel("Jingles Library", self)
        l.setGeometry(484, 12, 360, 24)
        l.setFont(inter(20, QFont.Weight.Bold))
        l.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        l = QLabel(
            "Station identity audio — manage categories and rotation",
            self)
        l.setGeometry(484, 38, 480, 14)
        l.setFont(inter(10))
        l.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

        # Clock + station
        self._clock_lbl = QLabel("21:56:15", self)
        self._clock_lbl.setGeometry(1108, 14, 100, 24)
        self._clock_lbl.setFont(mono(20, bold=True))
        self._clock_lbl.setStyleSheet(
            f"color: {TEXT_PRI}; background: transparent;")
        l = QLabel(Settings().station_display, self)
        l.setGeometry(1108, 40, 100, 14)
        l.setFont(inter(9, QFont.Weight.Medium))
        l.setStyleSheet(f"color: {GREEN}; background: transparent;")

        osb = _HeaderOpenStudio(self)
        osb.move(1222, 16)
        osb.clicked.connect(self.studio_clicked.emit)

    # ── SIDEBAR ──────────────────────────────────────────────────────────

    def _build_sidebar(self):
        sb = QFrame(self)
        sb.setGeometry(0, HEADER_H, SIDEBAR_W, WINDOW_H - HEADER_H - STATUS_H)
        sb.setStyleSheet(
            f"background: #0a0c16; "
            f"border-right: 1px solid {rgba('#ffffff', 0.06)};"
        )

        # Counter
        self._counter = _SidebarCounter(self)
        self._counter.move(12, HEADER_H + 14)

        # Action buttons
        actions = [
            ("+ Add New Jingle",   GREEN,        "#052e16", self._on_add_new),
            ("☴ Mass Import",      CYAN,         "#083344", self._on_mass_import),
            ("✎ Edit Categories",  PURPLE_LIGHT, "#1e1535", self._on_edit_categories),
            ("✕ Delete",           RED,          "#1f0a12", self._on_delete),
        ]
        y0 = HEADER_H + 64
        for i, (txt, color, bg_tint, slot) in enumerate(actions):
            btn = _SidebarActionButton(txt, color, bg_tint, self)
            btn.move(12, y0 + i * 34)
            btn.clicked.connect(slot)

        # SEARCH input
        s_y = y0 + 4 * 34 + 18
        l = QLabel("SEARCH", self)
        l.setGeometry(12, s_y, 160, 14)
        l.setFont(inter(8, QFont.Weight.Bold, letter_spacing=1.2))
        l.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        self._search_edit = QLineEdit(self)
        self._search_edit.setGeometry(12, s_y + 18, SIDEBAR_W - 24, 28)
        self._search_edit.setPlaceholderText("Search…")
        self._search_edit.setFont(inter(10))
        self._search_edit.setStyleSheet(
            f"QLineEdit {{ background: {BG_CARD}; color: {TEXT_PRI}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; border-radius: 6px; "
            f"padding-left: 8px; }}"
            f"QLineEdit:focus {{ border: 1px solid {rgba(CYAN, 0.50)}; }}"
        )
        self._search_edit.textChanged.connect(self._on_search_changed)

        # FILTERS section
        f_y = s_y + 18 + 28 + 14
        l = QLabel("FILTERS", self)
        l.setGeometry(12, f_y, 160, 14)
        l.setFont(inter(8, QFont.Weight.Bold, letter_spacing=1.2))
        l.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

        self._cat_dropdown = _SidebarDropdown(
            "Category", CATEGORY_FILTER_OPTIONS, self)
        self._cat_dropdown.move(12, f_y + 18)
        self._cat_dropdown.picked.connect(self._on_category_picked)

        self._props_dropdown = _SidebarDropdown(
            "Properties", PROPERTIES_FILTER_OPTIONS, self)
        self._props_dropdown.move(12, f_y + 18 + 34)
        self._props_dropdown.picked.connect(self._on_properties_picked)

        self._dur_dropdown = _SidebarDropdown(
            "Duration", DURATION_FILTER_OPTIONS, self)
        self._dur_dropdown.move(12, f_y + 18 + 68)
        self._dur_dropdown.picked.connect(self._on_duration_picked)

        self._only_enabled_chk = _OnlyEnabledCheckbox(self)
        self._only_enabled_chk.move(12, f_y + 18 + 102 + 4)
        self._only_enabled_chk.toggled_picked.connect(
            self._on_only_enabled_toggled)

        # INTEGRATION section
        ig_y = f_y + 18 + 102 + 4 + 28 + 14
        l = QLabel("INTEGRATION", self)
        l.setGeometry(12, ig_y, 160, 14)
        l.setFont(inter(8, QFont.Weight.Bold, letter_spacing=1.2))
        l.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        integrations = [
            ("↗ Export to Playlister", GREEN,        "#052e16",
             self._on_export_playlister),
            ("⚙ Playlister Code Prefix", CYAN_LIGHT, "#083344",
             self._on_playlister_prefix),
        ]
        for i, (txt, color, bg_tint, slot) in enumerate(integrations):
            btn = _SidebarActionButton(txt, color, bg_tint, self)
            btn.move(12, ig_y + 18 + i * 32)
            btn.clicked.connect(slot)

    # ── CENTER (table + scrubber) ────────────────────────────────────────

    def _build_center(self):
        # Table header strip
        hdr = _TableHeader(self)
        hdr.setGeometry(TABLE_X0, HEADER_H, TABLE_W, TABLE_HDR_H)

        # Scrollable table body
        scroll = QScrollArea(self)
        scroll.setGeometry(
            TABLE_X0, HEADER_H + TABLE_HDR_H,
            TABLE_W, TABLE_BODY_H,
        )
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            f"QScrollBar:vertical {{ background: {rgba('#ffffff', 0.02)}; "
            f"width: 6px; }}"
            f"QScrollBar::handle:vertical {{ background: {rgba(AMBER, 0.45)}; "
            f"border-radius: 3px; min-height: 24px; }}"
            "QScrollBar::add-line, QScrollBar::sub-line { height: 0; }"
        )
        body = QFrame(); body.setStyleSheet("background: transparent;")
        self._table_layout = QVBoxLayout(body)
        self._table_layout.setContentsMargins(0, 0, 0, 0)
        self._table_layout.setSpacing(0)
        self._table_layout.addStretch()
        scroll.setWidget(body)

        # Audio scrubber footer
        self._scrubber = _AudioScrubber(self)
        scrub_y = WINDOW_H - STATUS_H - SCRUBBER_H - 4
        self._scrubber.setGeometry(TABLE_X0, scrub_y, TABLE_W, SCRUBBER_H)
        self._scrubber.play_clicked.connect(self._on_scrubber_play)

    # ── RIGHT DETAILS PANEL ──────────────────────────────────────────────

    def _build_right_panel(self):
        wrap = QFrame(self)
        wrap.setGeometry(RIGHT_X, HEADER_H + 4, RIGHT_W,
                         WINDOW_H - HEADER_H - STATUS_H - 12)
        wrap.setStyleSheet(
            f"QFrame {{ background: #0a0c18; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; "
            f"border-radius: 10px; }}"
        )

        # Tab bar
        self._tab_bar = _DetailTabBar(wrap)
        self._tab_bar.setGeometry(0, 0, RIGHT_W, 38)
        self._tab_bar.tab_picked.connect(self._on_tab_picked)

        # Title hint
        sub = QLabel("Select a jingle to view details", wrap)
        sub.setObjectName("details_sub")
        sub.setGeometry(14, 44, 400, 12)
        sub.setFont(inter(9))
        sub.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        self._details_sub = sub

        # Header card
        self._details_card = _DetailsHeaderCard(wrap)
        self._details_card.setGeometry(14, 60, RIGHT_W - 28, 80)

        # Form fields
        labels = ["Name", "Category", "Duration", "Properties",
                  "Playlister Code", "Comments"]
        fy = 152
        for i, lab in enumerate(labels):
            f = _DetailsField(lab, wrap)
            f.setGeometry(14, fy + i * 50, RIGHT_W - 28, 44)
            self._details_fields[lab] = f

        # AUDIO PREVIEW header (decorative — full scrubber lives in center)
        ap_y = fy + len(labels) * 50 + 10
        ap_lbl = QLabel("AUDIO PREVIEW", wrap)
        ap_lbl.setGeometry(14, ap_y, 220, 14)
        ap_lbl.setFont(inter(9, QFont.Weight.Bold, letter_spacing=1.2))
        ap_lbl.setStyleSheet(
            f"color: {AMBER_LIGHT}; background: transparent;")
        bar = QFrame(wrap)
        bar.setGeometry(8, ap_y - 2, 2, 18)
        bar.setStyleSheet(f"background: {AMBER};")

        # SCHEDULING block
        sc_y = ap_y + 22
        sc_lbl = QLabel("SCHEDULING", wrap)
        sc_lbl.setGeometry(14, sc_y, 220, 14)
        sc_lbl.setFont(inter(9, QFont.Weight.Bold, letter_spacing=1.2))
        sc_lbl.setStyleSheet(
            f"color: {AMBER_LIGHT}; background: transparent;")
        bar = QFrame(wrap)
        bar.setGeometry(8, sc_y - 2, 2, 18)
        bar.setStyleSheet(f"background: {AMBER};")

        sc_row1 = QLabel(
            "Scheduled via Main Auto Clock — every 30 minutes", wrap)
        sc_row1.setGeometry(14, sc_y + 22, RIGHT_W - 28, 28)
        sc_row1.setFont(inter(10, QFont.Weight.Medium))
        sc_row1.setStyleSheet(
            f"QLabel {{ color: {TEXT_PRI}; "
            f"background: {BG_CARD}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; "
            f"border-radius: 6px; padding-left: 10px; }}")
        sc_row2 = QLabel(
            "Can also schedule via Playlists, Force Clocks, Final Log", wrap)
        sc_row2.setGeometry(14, sc_y + 54, RIGHT_W - 28, 28)
        sc_row2.setFont(inter(10))
        sc_row2.setStyleSheet(
            f"QLabel {{ color: {TEXT_MUTED}; "
            f"background: {BG_CARD}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; "
            f"border-radius: 6px; padding-left: 10px; }}")

        # AI rotation insight pill
        ai_y = sc_y + 90
        ai = QLabel("✦ AI: Playing every 28 min avg — healthy rotation",
                     wrap)
        ai.setGeometry(14, ai_y, RIGHT_W - 28, 26)
        ai.setFont(inter(10, QFont.Weight.Medium))
        ai.setStyleSheet(
            f"QLabel {{ color: {PURPLE_LIGHT}; "
            f"background: {rgba(PURPLE, 0.10)}; "
            f"border: 1px solid {rgba(PURPLE, 0.30)}; "
            f"border-radius: 6px; padding-left: 10px; }}")

        # 7-day stat card
        self._stats_card = QLabel(
            "Last 7 days: played 0 times", wrap)
        self._stats_card.setGeometry(14, ai_y + 32, RIGHT_W - 28, 30)
        self._stats_card.setFont(inter(10, QFont.Weight.Medium))
        self._stats_card.setStyleSheet(
            f"QLabel {{ color: {TEXT_SEC}; "
            f"background: {BG_CARD}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; "
            f"border-radius: 6px; padding-left: 10px; }}")

    # ── STATUS BAR ───────────────────────────────────────────────────────

    def _build_status_bar(self):
        sb = QFrame(self)
        sb.setGeometry(0, WINDOW_H - STATUS_H, WINDOW_W, STATUS_H)
        sb.setStyleSheet(
            f"QFrame {{ background: rgba(13,15,30,0.95); "
            f"border-top: 1px solid {rgba('#ffffff', 0.06)}; }}"
        )

        def _pill(x, text, fg, bg, w=110):
            l = QLabel(text, sb)
            l.setGeometry(x, 14, w, 22)
            l.setFont(inter(9, QFont.Weight.Bold, letter_spacing=1.0))
            l.setStyleSheet(
                f"QLabel {{ background: {bg}; color: {fg}; "
                f"border-radius: 11px; padding-left: 10px; }}"
            )
            return l

        _pill(12,  "● AUTO MODE", PURPLE_LIGHT, rgba(PURPLE, 0.18))
        _pill(130, "● AI Active", GREEN_LIGHT,  rgba(GREEN,  0.18), w=96)
        self._status_count = _pill(
            234, "0 Jingles", AMBER_LIGHT, rgba(AMBER, 0.18), w=110)

        version = QLabel(
            "Jingles Library  ·  RadioAI Studio v2.0", sb)
        version.setGeometry(WINDOW_W - 380, 16, 280, 16)
        version.setFont(inter(9))
        version.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent;")
        version.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        os_btn = QPushButton("▶  Open Studio", sb)
        os_btn.setGeometry(WINDOW_W - 100, 12, 88, 26)
        os_btn.setFont(inter(10, QFont.Weight.Bold))
        os_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        os_btn.setStyleSheet(
            f"QPushButton {{ background: {rgba(GREEN, 0.18)}; color: {GREEN_LIGHT}; "
            f"border: 1px solid {rgba(GREEN, 0.4)}; border-radius: 5px; }}"
            f"QPushButton:hover {{ background: {rgba(GREEN, 0.30)}; }}"
        )
        os_btn.clicked.connect(self.studio_clicked.emit)

    # ── DATA ─────────────────────────────────────────────────────────────

    def _row_to_dict(self, row) -> dict:
        return {
            "id":              int(row["id"]),
            "name":            row["name"],
            "category":        row["category"] or "Station ID",
            "file_path":       row["file_path"] or "",
            "duration_ms":     int(row["duration_ms"] or 0),
            "properties":      row["properties"] or "Regular",
            "playlister_code": row["playlister_code"] or "",
            "is_enabled":      bool(row["is_enabled"]),
            "last_used_label": "—",   # broadcast_log lookup deferred
        }

    def _load_jingles(self):
        try:
            rows = self._db._conn().execute(
                "SELECT * FROM jingles ORDER BY display_order, id"
            ).fetchall()
            self._jingles = [self._row_to_dict(r) for r in rows]
        except Exception as exc:
            log.error(f"load_jingles failed: {exc}")
            self._jingles = []

        if self._counter:
            total = len(self._jingles)
            active = sum(1 for s in self._jingles if s["is_enabled"])
            self._counter.set_counts(active, total)
        if self._status_count:
            self._status_count.setText(f"● {len(self._jingles)} Jingles")

        self._refresh_table()

        # Auto-select first row so the details panel isn't empty.
        if self._jingles and self._selected_id is None:
            self._on_row_clicked(self._jingles[0]["id"])

    def _filtered_jingles(self) -> list[dict]:
        out = list(self._jingles)
        if self._category_filter != "All Categories":
            out = [j for j in out
                   if (j.get("category") or "").strip() == self._category_filter]
        if self._properties_filter != "All Properties":
            out = [j for j in out
                   if (j.get("properties") or "").strip() == self._properties_filter]
        if self._duration_filter != "All Durations":
            def _within(ms: int) -> bool:
                s = (ms or 0) / 1000.0
                if self._duration_filter == "Under 5s":
                    return s < 5
                if self._duration_filter == "5–10s":
                    return 5 <= s <= 10
                if self._duration_filter == "Over 10s":
                    return s > 10
                return True
            out = [j for j in out if _within(j.get("duration_ms") or 0)]
        if self._only_enabled:
            out = [j for j in out if j.get("is_enabled")]
        if self._search_text:
            q = self._search_text.lower().strip()
            out = [j for j in out
                   if q in (j.get("name") or "").lower()
                   or q in (j.get("category") or "").lower()
                   or q in (j.get("playlister_code") or "").lower()]
        return out

    def _refresh_table(self):
        if not self._table_layout:
            return
        for w in self._row_widgets:
            w.setParent(None); w.deleteLater()
        self._row_widgets = []
        for i, j in enumerate(self._filtered_jingles()):
            row = _JingleRow(j)
            row.clicked.connect(self._on_row_clicked)
            row.double_clicked.connect(self._on_row_double_clicked)
            row.play_clicked.connect(self._on_row_play)
            self._table_layout.insertWidget(i, row)
            if j["id"] == self._selected_id:
                row.set_selected(True)
            self._row_widgets.append(row)

    def _on_row_clicked(self, jingle_id: int):
        self._selected_id = int(jingle_id)
        for r in self._row_widgets:
            r.set_selected(r.jingle_id == jingle_id)
        self._refresh_details()
        self.jingle_selected.emit(int(jingle_id))

    def _on_row_double_clicked(self, jingle_id: int):
        # Will open the editor dialog (Figma 106:2) in EDIT mode once
        # commit 2 lands. For now emits add_jingle_clicked + toasts.
        self._open_editor_dialog(jingle_id=int(jingle_id))

    def _on_row_play(self, jingle_id: int):
        """Toggle a 15-second on-screen preview for the row's jingle."""
        if (self._preview_cid is not None
                and self._preview_jingle_id == int(jingle_id)):
            self._stop_preview()
            return
        self._start_preview(int(jingle_id))

    def _refresh_details(self):
        cur = next((j for j in self._jingles
                    if j["id"] == self._selected_id), None)
        if not cur:
            if self._details_card:
                self._details_card.set_jingle({})
            for f in self._details_fields.values():
                f.set_value("—")
            if self._details_sub:
                self._details_sub.setText("Select a jingle to view details")
            if self._stats_card:
                self._stats_card.setText("Last 7 days: played 0 times")
            return
        if self._details_sub:
            self._details_sub.setText(cur.get("name") or "")
        if self._details_card:
            self._details_card.set_jingle(cur)
        self._details_fields["Name"].set_value(cur.get("name") or "—")
        self._details_fields["Category"].set_value(cur.get("category") or "—")
        self._details_fields["Duration"].set_value(
            _fmt_duration(cur.get("duration_ms") or 0))
        self._details_fields["Properties"].set_value(
            cur.get("properties") or "—")
        self._details_fields["Playlister Code"].set_value(
            cur.get("playlister_code") or "—")
        self._details_fields["Comments"].set_value(
            cur.get("comments") or "—")
        if self._scrubber:
            self._scrubber.set_track(
                cur.get("name") or "—",
                f"{cur.get('category') or '—'}  ·  "
                f"{_fmt_duration(cur.get('duration_ms') or 0)}")

    # ── EVENT HANDLERS ───────────────────────────────────────────────────

    def _on_search_changed(self, text: str):
        self._search_text = text or ""
        self._refresh_table()

    def _on_category_picked(self, name: str):
        self._category_filter = name
        self._reapply_filters()

    def _on_properties_picked(self, name: str):
        self._properties_filter = name
        self._reapply_filters()

    def _on_duration_picked(self, name: str):
        self._duration_filter = name
        self._reapply_filters()

    def _on_only_enabled_toggled(self, on: bool):
        self._only_enabled = bool(on)
        self._reapply_filters()

    def _reapply_filters(self):
        # Drop selection if it falls outside the new filtered set.
        filtered_ids = {j["id"] for j in self._filtered_jingles()}
        if self._selected_id not in filtered_ids:
            self._selected_id = None
            self._refresh_details()
        self._refresh_table()

    def _on_tab_picked(self, name: str):
        log.info(f"[jingles] tab → {name} (Schedule/Usage Stats deferred)")

    def _on_add_new(self):
        log.info("[jingles] + Add New Jingle (open editor dialog 106:2)")
        self.add_jingle_clicked.emit()
        self._open_editor_dialog(jingle_id=None)

    def _open_editor_dialog(self, jingle_id: Optional[int] = None):
        """Open the JingleEditorDialog. Lazy-imported so the screen
        constructs without dragging the dialog into memory until the
        operator actually opens one. Falls back to a 'coming soon'
        toast when the dialog file doesn't exist yet (commit 2)."""
        try:
            from ui.dialogs.jingle_editor_dialog import JingleEditorDialog
        except ImportError:
            QMessageBox.information(
                self, "Coming soon",
                "The Jingle editor dialog (Figma 106:2) lands in the "
                "next commit. For now you can browse + filter jingles.")
            return
        dlg = JingleEditorDialog(self._db, jingle_id=jingle_id, parent=self)
        if hasattr(dlg, "jingle_saved"):
            dlg.jingle_saved.connect(self._on_jingle_saved)
        dlg.exec()

    def _on_jingle_saved(self, jingle_id: int):
        """Refresh table + select the saved row."""
        self._selected_id = int(jingle_id)
        self._load_jingles()
        self._on_row_clicked(int(jingle_id))

    def _on_mass_import(self):
        log.info("[jingles] Mass Import — TODO")
        QMessageBox.information(
            self, "Coming soon",
            "Mass Import will let you bulk-add jingles from a folder.")

    def _on_edit_categories(self):
        log.info("[jingles] Edit Categories — TODO")
        QMessageBox.information(
            self, "Coming soon",
            "Edit Categories will let you manage jingle category labels.")

    def _on_delete(self):
        log.info("[jingles] Delete — TODO (waiting for confirm flow)")
        if self._selected_id is None:
            QMessageBox.information(
                self, "No selection", "Select a jingle row first.")
            return
        QMessageBox.information(
            self, "Coming soon",
            "Jingle delete will land alongside the editor dialog so "
            "the destructive confirmation matches the rest of the app.")

    def _on_export_playlister(self):
        log.info("[jingles] Export to Playlister — TODO")
        QMessageBox.information(
            self, "Coming soon",
            "Export to Playlister will write the active jingles list "
            "to the Playlister integration file.")

    def _on_playlister_prefix(self):
        log.info("[jingles] Playlister Code Prefix — TODO")
        QMessageBox.information(
            self, "Coming soon",
            "Playlister Code Prefix lets you set the JI-### code "
            "template used when exporting.")

    def _on_scrubber_play(self):
        """Right-panel scrubber ▶ button — same behaviour as the row
        ▶ icon, scoped to whichever jingle is currently selected."""
        if self._selected_id is None:
            return
        if (self._preview_cid is not None
                and self._preview_jingle_id == int(self._selected_id)):
            self._stop_preview()
            return
        self._start_preview(int(self._selected_id))

    # ── PREVIEW ──────────────────────────────────────────────────────────

    def _start_preview(self, jingle_id: int) -> None:
        """Spin up a single-channel preview for the given jingle. Any
        currently-playing preview is killed first so the operator never
        gets two voices through monitor."""
        if self._engine is None:
            log.warning("[jingles] preview skipped — no AudioEngine wired")
            return
        jingle = next((j for j in self._jingles
                       if int(j["id"]) == int(jingle_id)), None)
        if jingle is None:
            return
        path = jingle.get("file_path") or ""
        import os as _os
        if not path or not _os.path.exists(path):
            log.warning(
                f"[jingles] preview skipped — file missing: {path!r}")
            return

        # Kill any prior preview (different jingle, or stale).
        if self._preview_cid is not None:
            self._stop_preview()

        try:
            cid = self._engine.load_file(path)
        except Exception as exc:
            log.warning(f"[jingles] preview load_file failed: {exc}")
            return
        try:
            self._engine.set_volume(cid, self.PREVIEW_VOLUME)
        except Exception as exc:
            log.debug(f"[jingles] set_volume failed: {exc}")
        try:
            self._engine.play(cid)
        except Exception as exc:
            log.warning(f"[jingles] play failed: {exc}")
            try:
                self._engine.cleanup(cid)
            except Exception:
                pass
            return

        self._preview_cid = cid
        self._preview_jingle_id = int(jingle_id)

        # 15s auto-stop timer (matches Songs Library convention).
        if self._preview_timer is None:
            self._preview_timer = QTimer(self)
            self._preview_timer.setSingleShot(True)
            self._preview_timer.timeout.connect(self._stop_preview)
        self._preview_timer.stop()
        self._preview_timer.start(self.PREVIEW_DURATION_MS)

        # Visual cue: the row that's playing flips ▶ → ■.
        for r in self._row_widgets:
            r.set_playing(r.jingle_id == int(jingle_id))

        log.info(
            f"[jingles] preview started ch={cid} id={jingle_id} "
            f"({_fmt_duration(jingle.get('duration_ms') or 0)} cap "
            f"{self.PREVIEW_DURATION_MS}ms)")

    def _stop_preview(self) -> None:
        """Tear down the preview channel + reset visual state.
        Idempotent — safe when nothing is playing."""
        if self._preview_cid is None:
            return
        cid = self._preview_cid
        if self._preview_timer is not None:
            self._preview_timer.stop()
        try:
            self._engine.cleanup(cid)
        except Exception as exc:
            log.debug(f"[jingles] preview cleanup error: {exc}")
        self._preview_cid = None
        self._preview_jingle_id = None
        for r in self._row_widgets:
            r.set_playing(False)
        log.info(f"[jingles] preview stopped (ch={cid})")

    def _on_engine_playback_ended(self, channel_id: int) -> None:
        """Mirror the Songs Library teardown when the engine reports
        natural EOS for our preview channel. Other channels are not
        ours — defensive guard."""
        if channel_id == self._preview_cid:
            self._stop_preview()

    # ── CLOCK ────────────────────────────────────────────────────────────

    def _tick(self):
        if self._clock_lbl:
            self._clock_lbl.setText(datetime.now().strftime("%H:%M:%S"))
