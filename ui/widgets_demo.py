"""
Widgets Demo — visualises every premium widget for QA review.

Run from project root:
    py -m ui.widgets_demo
"""

import os
import sys

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFontDatabase, QFont
from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QVBoxLayout, QHBoxLayout, QGridLayout,
    QFrame, QScrollArea, QSizePolicy,
)

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from ui.widgets import (
    PremiumCard, GlowingButton, StatCard, WaveformWidget,
    PremiumTable, PremiumBadge, PictorialIcon, IconType,
    LiveIndicator, CategoryPill, LiveClock,
)
from ui.widgets._tokens import (
    inter, BG_BASE, TEXT_PRI, TEXT_MUTED, BG_PANEL,
    CYAN, CYAN_LIGHT, PURPLE, PURPLE_LIGHT, GREEN, GREEN_LIGHT,
    AMBER, AMBER_LIGHT, RED, RED_LIGHT, PINK, PINK_LIGHT,
)


def _section_label(title: str) -> QLabel:
    lbl = QLabel(title)
    lbl.setFont(inter(10, QFont.Weight.Black, letter_spacing=1.5))
    lbl.setStyleSheet(f"color: {TEXT_MUTED}; padding-bottom: 4px;")
    return lbl


def _box(title: str, content: QWidget, min_h: int = 200) -> QFrame:
    """Labelled card. Each box is a generous container so widgets breathe."""
    f = QFrame()
    f.setStyleSheet(
        f"QFrame {{ background: {BG_PANEL}; "
        f"border: 1px dashed rgba(255,255,255,0.06); border-radius: 12px; }}"
    )
    f.setMinimumHeight(min_h)
    v = QVBoxLayout(f)
    v.setContentsMargins(20, 16, 20, 16)
    v.setSpacing(10)
    v.addWidget(_section_label(title))
    v.addWidget(content, stretch=1, alignment=Qt.AlignmentFlag.AlignCenter)
    return f


def _icon_with_label(icon_type: IconType, color: str, light: str) -> QWidget:
    w = QWidget()
    w.setStyleSheet("background: transparent;")
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(8)
    lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lay.addWidget(PictorialIcon(icon_type, color, light, size=44),
                  alignment=Qt.AlignmentFlag.AlignCenter)
    lbl = QLabel(icon_type.value.upper())
    lbl.setFont(inter(8, QFont.Weight.Bold, letter_spacing=1.0))
    lbl.setStyleSheet(f"color: {TEXT_MUTED};")
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lay.addWidget(lbl)
    return w


def _flow(items: list, spacing: int = 10) -> QWidget:
    """Vertical stack with consistent spacing."""
    w = QWidget()
    w.setStyleSheet("background: transparent;")
    v = QVBoxLayout(w)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(spacing)
    v.setAlignment(Qt.AlignmentFlag.AlignCenter)
    for it in items:
        v.addWidget(it, alignment=Qt.AlignmentFlag.AlignCenter)
    return w


class WidgetsDemo(QWidget):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("RadioAI v2 — Premium Widgets Demo")
        self.setObjectName("root")
        self.resize(1440, 900)

        # ScrollArea allows the demo to be taller than the window
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)
        outer_layout.addWidget(scroll)

        content = QWidget()
        content.setStyleSheet("background: transparent;")
        scroll.setWidget(content)

        v = QVBoxLayout(content)
        v.setContentsMargins(36, 28, 36, 28)
        v.setSpacing(18)

        # Header
        title = QLabel("Premium Widgets — visual quality check")
        title.setFont(inter(28, QFont.Weight.Black, letter_spacing=-0.8))
        title.setStyleSheet(f"color: {TEXT_PRI};")
        sub = QLabel("Inter Variable + Roboto Mono · multi-stop gradients · drop shadows · custom QPainter icons")
        sub.setFont(inter(12, QFont.Weight.Medium))
        sub.setStyleSheet(f"color: {TEXT_MUTED};")
        v.addWidget(title)
        v.addWidget(sub)
        v.addSpacing(8)

        # ── Row 1 — Stat cards ────────────────────────────────────────────
        r1 = QHBoxLayout()
        r1.setSpacing(16)
        r1.addWidget(_box(
            "01 · StatCard (cyan · SONGS)",
            StatCard("SONGS", "14,733", "Smart rotation enabled",
                     IconType.SONGS, CYAN, CYAN_LIGHT),
            min_h=200,
        ))
        r1.addWidget(_box(
            "02 · StatCard (green · CAMPAIGNS)",
            StatCard("CAMPAIGNS", "29", "Next break 22:00",
                     IconType.SPOTS, GREEN, GREEN_LIGHT),
            min_h=200,
        ))
        r1.addWidget(_box(
            "03 · StatCard (amber · JINGLES)",
            StatCard("JINGLES", "293", "4 categories · auto-play",
                     IconType.JINGLES, AMBER, AMBER_LIGHT),
            min_h=200,
        ))
        v.addLayout(r1)

        # ── Row 2 — Buttons / Waveform / PremiumCard ──────────────────────
        r2 = QHBoxLayout()
        r2.setSpacing(16)
        r2.addWidget(_box(
            "04 · GlowingButton (3 colors)",
            _flow([
                GlowingButton("Open Studio",  PURPLE, PURPLE_LIGHT),
                GlowingButton("Record Now",   RED,    RED_LIGHT),
                GlowingButton("Save Changes", CYAN,   CYAN_LIGHT),
            ]),
            min_h=240,
        ))
        wf = WaveformWidget(n_bars=80, played_color=PURPLE,
                            light_color=PURPLE_LIGHT, max_height=42)
        wf.setMinimumSize(380, 90)
        r2.addWidget(_box("05 · WaveformWidget (animated)", wf, min_h=240))

        # PremiumCard with content
        pc = PremiumCard(CYAN, CYAN_LIGHT)
        pc.setMinimumSize(280, 150)
        pcv = QVBoxLayout(pc)
        pcv.setContentsMargins(20, 20, 20, 20)
        pcv.setSpacing(8)
        l1 = QLabel("Premium Card")
        l1.setFont(inter(20, QFont.Weight.Black, letter_spacing=-0.4))
        l1.setStyleSheet(f"color: {TEXT_PRI};")
        l2 = QLabel("Multi-stop gradient · drop shadow · color accent · rgba border")
        l2.setFont(inter(11, QFont.Weight.Medium))
        l2.setStyleSheet(f"color: {TEXT_MUTED};")
        l2.setWordWrap(True)
        pcv.addWidget(l1)
        pcv.addWidget(l2)
        pcv.addStretch()
        r2.addWidget(_box("06 · PremiumCard", pc, min_h=240))
        v.addLayout(r2)

        # ── Row 3 — Badges, Icons, Pills ──────────────────────────────────
        r3 = QHBoxLayout()
        r3.setSpacing(16)
        r3.addWidget(_box(
            "07 · PremiumBadge (4 variants)",
            _flow([
                PremiumBadge("MAIN LIBRARY", CYAN,   with_dot=False),
                PremiumBadge("LIVE TOOLS",   PURPLE, with_dot=True),
                PremiumBadge("REVENUE",      GREEN,  with_dot=False),
                PremiumBadge("AI POWERED",   RED,    with_dot=True),
            ], spacing=12),
            min_h=240,
        ))

        # Icon gallery — 3×2 grid in its own QWidget
        icons_w = QWidget()
        icons_w.setStyleSheet("background: transparent;")
        ig = QGridLayout(icons_w)
        ig.setHorizontalSpacing(20)
        ig.setVerticalSpacing(14)
        ig.setContentsMargins(0, 0, 0, 0)
        gallery = [
            (IconType.SONGS,    CYAN,   CYAN_LIGHT),
            (IconType.JINGLES,  AMBER,  AMBER_LIGHT),
            (IconType.SPOTS,    GREEN,  GREEN_LIGHT),
            (IconType.SWEEPERS, PINK,   PINK_LIGHT),
            (IconType.INSTANT,  PURPLE, PURPLE_LIGHT),
            (IconType.STITCHER, RED,    RED_LIGHT),
        ]
        for i, (t, c, l) in enumerate(gallery):
            row, col = divmod(i, 3)
            ig.addWidget(_icon_with_label(t, c, l), row, col,
                         alignment=Qt.AlignmentFlag.AlignCenter)
        r3.addWidget(_box("08 · PictorialIcon (6 types)", icons_w, min_h=240))

        r3.addWidget(_box(
            "09 · CategoryPill (5 colors)",
            _flow([
                CategoryPill("Hot Currents", CYAN),
                CategoryPill("Power Gold",   AMBER),
                CategoryPill("Bhajan",       PURPLE),
                CategoryPill("Pop",          GREEN),
                CategoryPill("News Break",   RED),
            ], spacing=8),
            min_h=240,
        ))
        v.addLayout(r3)

        # ── Row 4 — LiveIndicator, LiveClock, PremiumTable ────────────────
        r4 = QHBoxLayout()
        r4.setSpacing(16)
        r4.addWidget(_box(
            "10 · LiveIndicator",
            _flow([
                LiveIndicator(show_clock=True),
                LiveIndicator(show_clock=False),
            ], spacing=14),
            min_h=200,
        ))
        r4.addWidget(_box("11 · LiveClock", LiveClock(), min_h=200))

        # Premium table
        table = PremiumTable()
        table.setColumnCount(3)
        table.setHorizontalHeaderLabels(["TITLE", "ARTIST", "DURATION"])
        for r in [
            ("As It Was",       "Harry Styles",  "2:47"),
            ("Bury A Friend",   "Billie Eilish", "3:13"),
            ("Blinding Lights", "The Weeknd",    "3:20"),
            ("Levitating",      "Dua Lipa",      "3:23"),
        ]:
            table.add_row(list(r))
        table.setColumnWidth(0, 160)
        table.setColumnWidth(1, 130)
        table.setMinimumHeight(220)
        r4.addWidget(_box("12 · PremiumTable", table, min_h=260))
        v.addLayout(r4)

        v.addStretch()


def main():
    app = QApplication(sys.argv)
    fonts_dir = os.path.join(_ROOT, "assets", "fonts")
    for fname in sorted(os.listdir(fonts_dir)):
        if fname.lower().endswith((".ttf", ".otf")):
            QFontDatabase.addApplicationFont(os.path.join(fonts_dir, fname))
    qss_path = os.path.join(_ROOT, "assets", "premium.qss")
    if os.path.exists(qss_path):
        with open(qss_path, encoding="utf-8") as f:
            app.setStyleSheet(f.read())
    w = WidgetsDemo()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
