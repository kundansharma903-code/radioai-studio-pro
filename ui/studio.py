"""
RadioAI Studio Pro — Studio Single Deck (Figma 182:2).

Phase D1: UI skeleton. Three-column 1440×900 layout matching Figma 182:2.
All custom-paint, hardcoded placeholder data. No audio wiring (Day D2),
no scheduler (Days D3–D5).

Layout
------
  HEADER  y=0..50    — logo, station pills, clock, AUTO pill, Open Studio CTA
  LEFT    x=0..300   — PLAYLIST QUEUE (scrollable rows + bottom action bar)
  CENTER  x=300..840 — NOW PLAYING card + waveform + countdown + transport
                        + master vol + NEXT UP + Instant Jingles 6-pad grid
  RIGHT   x=840..1440 — HISTORY + NEXT BREAK + UPCOMING SPOTS + AI INSIGHTS
                        + RDS card
  STATUS  y=868..900 — pills (AUTO MODE / AI Active / ON AIR / Log Ready / etc.)

═════════════════════════════════════════════════════════════════════════════
PERFORMANCE NOTES — DO NOT VIOLATE  (Spot Programming + cue editor lessons)
═════════════════════════════════════════════════════════════════════════════
  1. event.rect() CLIPPING — for the playlist queue (14+ rows tall) and
     history list, paintEvent must respect the dirty rect. Compute first
     and last visible rows from event.rect() rather than painting all
     rows unconditionally.
  2. NO bare self.update() in mouseMoveEvent — bounded update(rect) only.
  3. NO db calls in paintEvent — caller-side only.
  4. NO nested QScrollArea — Studio is rendered in MainWindow's outer
     scroll. Internal scrolls would create the layout-storm trap.
  5. NO setMouseTracking(True) unless specifically needed for hover.
  6. Any list >2000px tall: setFixedHeight only (not setFixedSize).
═════════════════════════════════════════════════════════════════════════════

Day D2 will:
  - Wire transport controls (Pause / Stop Next / Fade Out / Restart) to
    AudioEngine
  - Drive Now Playing waveform + countdown from engine.position_changed
  - Replace hardcoded placeholder data with real "idle" state when no
    song is playing
"""

from __future__ import annotations

import logging
from typing import Optional

from PyQt6.QtCore import Qt, QRect, QRectF, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QLinearGradient, QPainterPath, QFont,
    QCursor,
)
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QScrollArea, QSizePolicy,
)

from ui.widgets._tokens import (
    inter, mono, rgba,
    BG_BASE, BG_DARK, BG_PANEL, BG_CARD, BG_CARD_DK, BG_ELEVATED, BG_PURPLE_DK,
    TEXT_PRI, TEXT_SEC, TEXT_MUTED, TEXT_DIM,
    CYAN, CYAN_LIGHT,
    PURPLE, PURPLE_LIGHT, PURPLE_DARK,
    GREEN, GREEN_LIGHT,
    AMBER, AMBER_LIGHT,
    RED, RED_LIGHT,
    PINK, PINK_LIGHT,
)

log = logging.getLogger("Studio")


# ── Layout constants ───────────────────────────────────────────────────────

WINDOW_W = 1440
WINDOW_H = 900

HEADER_H = 50
STATUS_H = 32

LEFT_X  = 0
LEFT_W  = 300
CENTER_X = LEFT_X + LEFT_W          # 300
CENTER_W = 540
RIGHT_X = CENTER_X + CENTER_W       # 840
RIGHT_W = WINDOW_W - RIGHT_X        # 600


# ── Placeholder data (Day D1 — Figma example values) ───────────────────────

QUEUE_PLACEHOLDER = [
    # (idx, title, artist, time, duration, category, badge)
    (1,  "Amy Winehouse",  "You Know I'm No Good",      "21:56", "3:45", "Hot Currents", "AI Pick"),
    (2,  "Harry Styles",   "As It Was",                  "22:00", "2:37", "Hot Currents", ""),
    (3,  "Billie Eilish",  "Bury A Friend",              "22:03", "3:26", "Classic",      ""),
    (4,  "BREAK",          "FreshBurst + NovaTech",      "22:05", "2:50", "Ads",          "Overrun"),
    (5,  "Coldplay",       "Clocks",                     "22:09", "5:07", "Classic",      ""),
    (6,  "Drake",          "God's Plan",                 "22:14", "3:18", "Hot Currents", "Overplay"),
    (7,  "Eagle Eye Cherry","Save Tonight",              "22:17", "3:56", "Classic",      ""),
    (8,  "Kylie Minogue",  "Step Back In Time",          "22:21", "3:48", "Classic",      "AI Pick"),
    (9,  "Bangles",        "Walk Like An Egyptian",      "22:25", "3:24", "Classic",      ""),
    (10, "BREAK",          "City FM + Weather",          "22:29", "1:45", "Ads",          ""),
    (11, "Rick Astley",    "Never Gonna Give You Up",    "22:30", "3:33", "Classic",      ""),
    (12, "Britney Spears", "You Drive Me Crazy",         "22:34", "3:18", "Pop",          ""),
]

HISTORY_PLACEHOLDER = [
    ("21:43", "Billie Eilish",      "Bad Guy",              "3:14"),
    ("21:46", "Coldplay",           "Clocks",               "5:07"),
    ("21:51", "Drake",              "God's Plan",           "3:18"),
    ("21:55", "Kylie Minogue",      "Step Back In Time",    "3:48"),
    ("21:59", "Eagle Eye Cherry",   "Save Tonight",         "3:56"),
    ("22:02", "Rick Astley",        "Never Gonna Give Up",  "3:33"),
]

UPCOMING_SPOTS_PLACEHOLDER = [
    ("22:00", "FreshBurst Cola",  "30s"),
    ("22:00", "NovaTech Mobile",  "15s"),
    ("22:30", "City FM Promo",    "16s"),
]

AI_INSIGHTS_PLACEHOLDER = [
    ("warning",    "Drake — God's Plan overplayed (5×/wk)"),
    ("suggestion", "AI suggests Kylie after Eagle Eye Cherry"),
    ("info",       "FreshBurst Cola: 88% delivery on track"),
    ("info",       "Next break 22:00 — 2:50 spot load OK"),
]

JINGLES_PLACEHOLDER = [
    ("N30", "KISS Open",   "8.7s",  PURPLE),
    ("N29", "RR Bridge",   "11.8s", PURPLE),
    ("N28", "SW Fast Hit", "9.5s",  PURPLE),
    ("N27", "Party Beat",  "4.1s",  AMBER),
    ("N26", "SF Horn",     "1.3s",  PINK),
    ("N25", "SF Yes OK",   "4.2s",  PINK),
]

CURRENT_TRACK = {
    "title":   "Amy Winehouse",
    "artist":  "You Know I'm No Good",
    "tags":    ["Hot Currents", "88 BPM", "High Energy", "Female"],
    "elapsed": "01:23",
    "total":   "03:45",
    "remaining_text": "-01:22",
}

NEXT_UP = {
    "title":  "Harry Styles",
    "artist": "As It Was",
    "etr":    "2:37 / 22:00",
}


# ── Category color helper ──────────────────────────────────────────────────

def _category_color(cat: str) -> str:
    return {
        "Hot Currents": PINK,
        "Classic":      CYAN,
        "Pop":          AMBER,
        "Ads":          RED,
    }.get(cat, TEXT_MUTED)


def _ai_icon(kind: str) -> tuple[str, str]:
    """(glyph, color) for AI insight rows."""
    return {
        "warning":    ("⚠", AMBER_LIGHT),
        "suggestion": ("✦", PURPLE_LIGHT),
        "info":       ("●", GREEN),
    }.get(kind, ("·", TEXT_MUTED))


# ════════════════════════════════════════════════════════════════════════════
# HEADER
# ════════════════════════════════════════════════════════════════════════════

class _StudioHeader(QFrame):
    """Top bar — logo + station pills + clock + AUTO pill + CTAs."""

    control_panel_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(HEADER_H)
        self.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border-bottom: 1px solid {rgba('#ffffff', 0.06)}; }}"
        )
        # Live clock tick
        self._clock_text = "00:00:00"
        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._tick_clock)
        self._clock_timer.start()
        self._tick_clock()

        # Control Panel button (real, clickable)
        self._cp_btn = QPushButton("CONTROL PANEL", self)
        self._cp_btn.setGeometry(890, 12, 130, 28)
        self._cp_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._cp_btn.setFont(inter(9, QFont.Weight.Bold, letter_spacing=0.6))
        self._cp_btn.setStyleSheet(
            f"QPushButton {{ background: {rgba('#ffffff', 0.06)}; "
            f"color: {TEXT_SEC}; "
            f"border: 1px solid {rgba('#ffffff', 0.10)}; "
            f"border-radius: 6px; }}"
            f"QPushButton:hover {{ background: {rgba(CYAN, 0.18)}; "
            f"color: {CYAN_LIGHT}; }}"
        )
        self._cp_btn.clicked.connect(self.control_panel_clicked.emit)

    def _tick_clock(self):
        from datetime import datetime
        self._clock_text = datetime.now().strftime("%H:%M:%S")
        self.update(QRect(540, 0, 200, HEADER_H))

    def paintEvent(self, _e):
        super().paintEvent(_e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Logo dot + RadioAI brand
        p.setBrush(QColor(PURPLE)); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(14, HEADER_H // 2 - 6, 12, 12)
        p.setPen(QColor(TEXT_PRI))
        p.setFont(inter(14, QFont.Weight.Black, letter_spacing=0.5))
        p.drawText(QRectF(34, 0, 90, HEADER_H),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "RadioAI")
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(inter(7, QFont.Weight.Bold, letter_spacing=1.4))
        p.drawText(QRectF(34, 26, 90, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                   "STUDIO PRO")

        # Station pill (KISS FM 91.5 - Jaipur)
        pill = QRectF(140, 11, 230, 28)
        p.setBrush(QColor("#0c0e1c")); p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(pill, 14, 14)
        bc = QColor("#ffffff"); bc.setAlphaF(0.10)
        p.setPen(QPen(bc, 1)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(pill, 14, 14)
        p.setPen(QColor(CYAN_LIGHT))
        p.setFont(inter(10, QFont.Weight.DemiBold))
        p.drawText(pill.adjusted(14, 0, -10, 0),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   "KISS FM 91.5  ·  Jaipur, Rajasthan")

        # Live clock (mono, large)
        p.setPen(QColor(TEXT_PRI))
        p.setFont(mono(18, bold=True))
        p.drawText(QRectF(540, 0, 180, HEADER_H),
                   Qt.AlignmentFlag.AlignCenter,
                   self._clock_text)

        # AUTO mode pill (green)
        auto_pill = QRectF(740, 11, 100, 28)
        bg = QColor(GREEN); bg.setAlphaF(0.18)
        p.setBrush(bg); p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(auto_pill, 14, 14)
        p.setPen(QColor(GREEN))
        p.setFont(inter(10, QFont.Weight.Bold, letter_spacing=0.8))
        # Pulsing dot
        p.setBrush(QColor(GREEN)); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(752, HEADER_H // 2 - 4, 8, 8))
        p.setPen(QColor(GREEN))
        p.drawText(auto_pill.adjusted(28, 0, -8, 0),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   "AUTO")

        # FCP station pill (right of CP button — small)
        fcp = QRectF(1030, 11, 140, 28)
        p.setBrush(QColor("#0c0e1c")); p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(fcp, 14, 14)
        bc = QColor("#ffffff"); bc.setAlphaF(0.08)
        p.setPen(QPen(bc, 1)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(fcp, 14, 14)
        p.setPen(QColor(TEXT_SEC))
        p.setFont(inter(9, QFont.Weight.Medium))
        p.drawText(fcp.adjusted(12, 0, -10, 0),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   "FCP  ·  Sikar, Rajasthan")

        # ▶ Open Studio CTA (purple gradient, right edge)
        cta = QRectF(1180, 8, 245, 34)
        path = QPainterPath(); path.addRoundedRect(cta, 8, 8)
        p.setClipPath(path)
        grad = QLinearGradient(cta.topLeft(), cta.topRight())
        grad.setColorAt(0.0, QColor(PURPLE_LIGHT))
        grad.setColorAt(1.0, QColor(PURPLE_DARK))
        p.fillRect(cta, QBrush(grad))
        p.setClipping(False)
        p.setPen(QColor("#ffffff"))
        p.setFont(inter(11, QFont.Weight.Bold, letter_spacing=0.4))
        p.drawText(cta, Qt.AlignmentFlag.AlignCenter, "▶  Open Studio")


# ════════════════════════════════════════════════════════════════════════════
# LEFT — PLAYLIST QUEUE
# ════════════════════════════════════════════════════════════════════════════

class _QueueRow(QFrame):
    """One row in the playlist queue (300×46)."""

    ROW_H = 46

    def __init__(self, idx: int, title: str, artist: str, time_str: str,
                 duration: str, category: str, badge: str, parent=None):
        super().__init__(parent)
        self._idx       = idx
        self._title     = title
        self._artist    = artist
        self._time_str  = time_str
        self._duration  = duration
        self._category  = category
        self._badge     = badge
        self._is_break  = (title == "BREAK")
        self._is_current = (idx == 1)
        self.setFixedSize(LEFT_W - 8, self.ROW_H)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        rect = QRectF(0, 0, w, h)

        # Background — current playing has cyan tint, break has red tint
        if self._is_current:
            bg = QColor(GREEN); bg.setAlphaF(0.10)
            p.fillRect(rect, bg)
            p.fillRect(QRectF(0, 0, 3, h), QColor(GREEN))
        elif self._is_break:
            bg = QColor(RED); bg.setAlphaF(0.10)
            p.fillRect(rect, bg)
            p.fillRect(QRectF(0, 0, 3, h), QColor(RED))
        else:
            zebra = "#0d0f1c" if self._idx % 2 else "#0a0c18"
            p.fillRect(rect, QColor(zebra))

        # Index number (small, muted)
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(inter(9, QFont.Weight.Bold))
        p.drawText(QRectF(8, 4, 22, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   str(self._idx))

        # Title
        p.setPen(QColor(GREEN_LIGHT if self._is_current else
                        RED_LIGHT if self._is_break else TEXT_PRI))
        p.setFont(inter(10, QFont.Weight.Bold))
        fm = p.fontMetrics()
        title = fm.elidedText(self._title, Qt.TextElideMode.ElideRight, 130)
        p.drawText(QRectF(28, 4, 140, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   title)

        # Artist (subtitle line)
        if not self._is_break:
            p.setPen(QColor(TEXT_SEC))
            p.setFont(inter(9))
            artist = fm.elidedText(self._artist, Qt.TextElideMode.ElideRight, 130)
            p.drawText(QRectF(28, 18, 140, 12),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       artist)
        else:
            p.setPen(QColor(TEXT_MUTED))
            p.setFont(inter(8))
            sub = fm.elidedText(self._artist, Qt.TextElideMode.ElideRight, 130)
            p.drawText(QRectF(28, 18, 140, 12),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       sub)

        # Duration (bottom-left)
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(mono(8, bold=True))
        p.drawText(QRectF(28, 31, 60, 12),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._duration)

        # Time stamp (top-right, mono)
        p.setPen(QColor(TEXT_SEC))
        p.setFont(mono(9, bold=True))
        p.drawText(QRectF(w - 56, 4, 50, 14),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   self._time_str)

        # Category pill (right side, mid)
        if self._category:
            cat_color = _category_color(self._category)
            cat_w = 56
            cat_pill = QRectF(w - cat_w - 6, 22, cat_w, 14)
            cbg = QColor(cat_color); cbg.setAlphaF(0.18)
            p.setBrush(cbg); p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(cat_pill, 6, 6)
            p.setPen(QColor(cat_color))
            p.setFont(inter(7, QFont.Weight.Bold, letter_spacing=0.4))
            p.drawText(cat_pill, Qt.AlignmentFlag.AlignCenter, self._category)

        # Badge (AI Pick / Overrun / Overplay)
        if self._badge:
            badge_w = 48
            badge_pill = QRectF(w - badge_w - 6, 4, badge_w, 14)
            bcol = AMBER_LIGHT if "Overrun" in self._badge or "Overplay" in self._badge else CYAN_LIGHT
            bbg = QColor(bcol); bbg.setAlphaF(0.20)
            p.setBrush(bbg); p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(badge_pill, 6, 6)
            p.setPen(QColor(bcol))
            p.setFont(inter(7, QFont.Weight.Bold, letter_spacing=0.4))
            p.drawText(badge_pill, Qt.AlignmentFlag.AlignCenter, self._badge)


class _PlaylistQueue(QFrame):
    """Left panel — header + scrollable rows + bottom action bar."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(LEFT_W, WINDOW_H - HEADER_H - STATUS_H)
        self.setStyleSheet(
            f"QFrame {{ background: {BG_DARK}; "
            f"border-right: 1px solid {rgba('#ffffff', 0.06)}; }}"
        )

        v = QVBoxLayout(self)
        v.setContentsMargins(4, 6, 4, 6); v.setSpacing(4)

        # Sub-header
        hdr = QLabel("PLAYLIST QUEUE")
        hdr.setFont(inter(9, QFont.Weight.Black, letter_spacing=1.4))
        hdr.setStyleSheet(f"color: {TEXT_SEC}; background: transparent;")
        v.addWidget(hdr)

        sub = QLabel("Next 16 items   ↑↓   Skip")
        sub.setFont(inter(8))
        sub.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        v.addWidget(sub)

        # Scrollable rows
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            f"QScrollBar:vertical {{ background: transparent; width: 6px; }}"
            f"QScrollBar::handle:vertical {{ background: {rgba(PURPLE, 0.45)}; "
            f"border-radius: 3px; min-height: 24px; }}"
            "QScrollBar::add-line, QScrollBar::sub-line { height: 0; }"
        )
        body = QFrame(); body.setStyleSheet("background: transparent;")
        rows_v = QVBoxLayout(body)
        rows_v.setContentsMargins(0, 0, 0, 0); rows_v.setSpacing(2)
        for row_data in QUEUE_PLACEHOLDER:
            rows_v.addWidget(_QueueRow(*row_data))
        rows_v.addStretch()
        scroll.setWidget(body)
        v.addWidget(scroll, stretch=1)

        # Bottom action bar (placeholder — D5 wires queue manipulation)
        bar = QHBoxLayout(); bar.setSpacing(4); bar.setContentsMargins(0, 4, 0, 0)
        for label, color in [
            ("+ Add",  CYAN),
            ("↑ Up",   CYAN),
            ("↓ Down", CYAN),
            ("Skip",   RED),
            ("🔒 Lock", AMBER),
        ]:
            b = self._chip_button(label, color)
            bar.addWidget(b)
        v.addLayout(bar)

    def _chip_button(self, label: str, color: str) -> QPushButton:
        b = QPushButton(label)
        b.setFixedHeight(22)
        b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        b.setFont(inter(8, QFont.Weight.DemiBold))
        b.setStyleSheet(
            f"QPushButton {{ background: {rgba(color, 0.16)}; "
            f"color: {color}; "
            f"border: 1px solid {rgba(color, 0.30)}; "
            f"border-radius: 4px; padding: 0 6px; }}"
            f"QPushButton:hover {{ background: {rgba(color, 0.26)}; }}"
        )
        return b


# ════════════════════════════════════════════════════════════════════════════
# CENTER — NOW PLAYING + Controls
# ════════════════════════════════════════════════════════════════════════════

class _NowPlayingCard(QFrame):
    """Album art + title + artist + tag pills row."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(86)
        self.setStyleSheet("background: transparent;")

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Album art square (placeholder — music icon glyph)
        art = QRectF(0, 8, 70, 70)
        path = QPainterPath(); path.addRoundedRect(art, 8, 8)
        p.setClipPath(path)
        grad = QLinearGradient(art.topLeft(), art.bottomRight())
        grad.setColorAt(0.0, QColor(PURPLE_DARK))
        grad.setColorAt(1.0, QColor(BG_PURPLE_DK))
        p.fillRect(art, QBrush(grad))
        p.setClipping(False)
        p.setPen(QColor(PURPLE_LIGHT))
        p.setFont(inter(28, QFont.Weight.Black))
        p.drawText(art, Qt.AlignmentFlag.AlignCenter, "♪")

        # Title (huge)
        p.setPen(QColor(TEXT_PRI))
        p.setFont(inter(20, QFont.Weight.Black, letter_spacing=0.3))
        p.drawText(QRectF(82, 6, self.width() - 90, 30),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   CURRENT_TRACK["title"])

        # Artist
        p.setPen(QColor(TEXT_SEC))
        p.setFont(inter(11, QFont.Weight.Medium))
        p.drawText(QRectF(82, 32, self.width() - 90, 18),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   CURRENT_TRACK["artist"])

        # Tag pills row
        x = 82
        tag_colors = [PINK, CYAN, GREEN, AMBER]
        p.setFont(inter(8, QFont.Weight.Bold, letter_spacing=0.4))
        fm = p.fontMetrics()
        for i, tag in enumerate(CURRENT_TRACK["tags"]):
            tag_w = fm.horizontalAdvance(tag) + 14
            pill = QRectF(x, 56, tag_w, 18)
            cbg = QColor(tag_colors[i % len(tag_colors)]); cbg.setAlphaF(0.18)
            p.setBrush(cbg); p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(pill, 8, 8)
            p.setPen(QColor(tag_colors[i % len(tag_colors)]))
            p.drawText(pill, Qt.AlignmentFlag.AlignCenter, tag)
            x += tag_w + 6


class _StudioWaveform(QFrame):
    """Wide waveform with cue markers + time labels.

    Day D1: synthetic decoration — same generator pattern as cue editor.
    Day D2 will drive the playhead from engine.position_changed."""

    BAR_COUNT = 110

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(110)
        self.setStyleSheet(
            f"QFrame {{ background: #0a0c14; "
            f"border: 1px solid {rgba('#ffffff', 0.04)}; "
            f"border-radius: 6px; }}"
        )
        # Pre-compute bars (deterministic seed for stable layout)
        import math, random
        rng = random.Random(2026)
        self._bars: list[float] = []
        for i in range(self.BAR_COUNT):
            phase = i / self.BAR_COUNT * 2 * math.pi * 5.5
            base = 0.55 + 0.40 * math.sin(phase)
            base += rng.uniform(-0.20, 0.20)
            env = 0.4 + 0.6 * math.sin(math.pi * (i / self.BAR_COUNT))
            self._bars.append(max(0.10, min(1.0, base * env)))

    def paintEvent(self, _e):
        super().paintEvent(_e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        margin_x = 10
        plot_top = 8
        plot_bot = self.height() - 22
        plot_h = plot_bot - plot_top
        plot_left = margin_x
        plot_right = self.width() - margin_x
        plot_w = plot_right - plot_left

        # Played-fraction cutoff (matches Figma: ~01:23 / 03:45 ≈ 37%)
        played_frac = 1.43 / 3.75
        playhead_idx = int(played_frac * self.BAR_COUNT)

        # Cue markers
        markers = [
            (0.05,  "INTRO",    CYAN),
            (0.20,  "HOOK IN",  PINK),
            (0.70,  "OUTRO",    AMBER),
            (0.97,  "MIX",      RED),
        ]
        for frac, label, color in markers:
            mx = plot_left + int(plot_w * frac)
            p.setPen(QPen(QColor(color), 1))
            p.drawLine(mx, plot_top, mx, plot_bot)
            tag_w = 56
            tag = QRectF(mx - tag_w / 2, 0, tag_w, plot_top + 2)
            tint = QColor(color); tint.setAlphaF(0.85)
            p.setBrush(tint); p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(tag, 3, 3)
            p.setPen(QColor("#0a0c14"))
            p.setFont(inter(7, QFont.Weight.Bold, letter_spacing=0.4))
            p.drawText(tag, Qt.AlignmentFlag.AlignCenter, label)

        # Bars
        bar_total_w = plot_w / self.BAR_COUNT
        bar_w = max(2.0, bar_total_w * 0.65)
        cy = plot_top + plot_h / 2
        for i, amp in enumerate(self._bars):
            x = plot_left + int(i * bar_total_w + (bar_total_w - bar_w) / 2)
            color = QColor(GREEN) if i < playhead_idx else QColor(255, 255, 255, 90)
            bh = max(4, int(amp * plot_h * 0.85))
            y = int(cy - bh / 2)
            p.setBrush(color); p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(QRectF(x, y, bar_w, bh), 1, 1)

        # Playhead bright line
        ph_x = plot_left + int(played_frac * plot_w)
        p.setPen(QPen(QColor("#ffffff"), 2))
        p.drawLine(ph_x, plot_top, ph_x, plot_bot)

        # Time labels (mono)
        p.setPen(QColor(GREEN_LIGHT))
        p.setFont(mono(10, bold=True))
        p.drawText(QRectF(margin_x, plot_bot + 4, 80, 18),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   CURRENT_TRACK["elapsed"])
        p.setPen(QColor(TEXT_MUTED))
        p.drawText(QRectF(self.width() - 90, plot_bot + 4, 80, 18),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   CURRENT_TRACK["total"])


class _Countdown(QFrame):
    """Big red mono countdown — '-01:22 remaining'."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(70)
        self.setStyleSheet(
            f"QFrame {{ background: #0a0c14; "
            f"border: 1px solid {rgba(RED, 0.20)}; "
            f"border-radius: 6px; }}"
        )

    def paintEvent(self, _e):
        super().paintEvent(_e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Vertical accent stripe at left
        p.fillRect(0, 0, 4, self.height(), QColor(RED))
        # Big countdown
        p.setPen(QColor(RED_LIGHT))
        p.setFont(mono(40, bold=True))
        p.drawText(QRectF(0, 0, self.width(), self.height() - 14),
                   Qt.AlignmentFlag.AlignCenter,
                   CURRENT_TRACK["remaining_text"])
        # "remaining" subtitle
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(inter(8, QFont.Weight.Bold, letter_spacing=1.6))
        p.drawText(QRectF(0, self.height() - 18, self.width(), 16),
                   Qt.AlignmentFlag.AlignCenter,
                   "REMAINING")


class _TransportRow(QFrame):
    """Restart / Loop / Pause / Stop Next / Fade Out — visual stubs in D1."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(36)
        self.setStyleSheet("background: transparent;")
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0); h.setSpacing(6)

        for glyph, label, color in [
            ("⟳",  "Restart",   TEXT_SEC),
            ("↻",  "Loop",      CYAN),
            ("‖ ", "Pause",     AMBER),
            ("■",  "Stop Next", RED),
            ("▸",  "Fade Out",  GREEN),
        ]:
            btn = QPushButton(f"{glyph}  {label}")
            btn.setFixedHeight(34)
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn.setFont(inter(10, QFont.Weight.DemiBold))
            btn.setStyleSheet(
                f"QPushButton {{ background: {rgba(color, 0.14)}; "
                f"color: {color}; "
                f"border: 1px solid {rgba(color, 0.30)}; "
                f"border-radius: 6px; padding: 0 10px; }}"
                f"QPushButton:hover {{ background: {rgba(color, 0.24)}; }}"
            )
            h.addWidget(btn)


class _MasterVolumeStrip(QFrame):
    """MASTER VOL slider strip — green bar at 85%."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(28)
        self.setStyleSheet("background: transparent;")
        self._level = 0.85

    def paintEvent(self, _e):
        super().paintEvent(_e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Label
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(inter(8, QFont.Weight.Bold, letter_spacing=1.2))
        p.drawText(QRectF(0, 0, 90, self.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   "MASTER VOL")
        # Bar
        bar = QRectF(96, self.height() // 2 - 4, self.width() - 156, 8)
        path = QPainterPath(); path.addRoundedRect(bar, 4, 4)
        p.setClipPath(path)
        p.fillRect(bar, QColor("#0a0c18"))
        fill = QRectF(bar.x(), bar.y(), bar.width() * self._level, bar.height())
        grad = QLinearGradient(fill.topLeft(), fill.topRight())
        grad.setColorAt(0.0, QColor(GREEN)); grad.setColorAt(1.0, QColor(GREEN_LIGHT))
        p.fillRect(fill, QBrush(grad))
        p.setClipping(False)
        # Percent text
        p.setPen(QColor(GREEN_LIGHT))
        p.setFont(mono(11, bold=True))
        p.drawText(QRectF(self.width() - 50, 0, 46, self.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                   f"{int(self._level * 100)}%")


class _NextUpCard(QFrame):
    """Mini "NEXT UP" preview card."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(64)
        self.setStyleSheet(
            f"QFrame {{ background: {rgba('#ffffff', 0.02)}; "
            f"border: 1px solid {rgba('#ffffff', 0.06)}; "
            f"border-radius: 6px; }}"
        )

    def paintEvent(self, _e):
        super().paintEvent(_e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Header
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(inter(8, QFont.Weight.Black, letter_spacing=1.2))
        p.drawText(QRectF(12, 4, 100, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "NEXT UP")
        # Title
        p.setPen(QColor(TEXT_PRI))
        p.setFont(inter(12, QFont.Weight.Bold))
        p.drawText(QRectF(12, 20, 250, 18),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   NEXT_UP["title"])
        # Artist
        p.setPen(QColor(TEXT_SEC))
        p.setFont(inter(9))
        p.drawText(QRectF(12, 38, 250, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   NEXT_UP["artist"])
        # ETR (right side)
        p.setPen(QColor(CYAN_LIGHT))
        p.setFont(mono(10, bold=True))
        p.drawText(QRectF(self.width() - 110, 0, 100, self.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                   NEXT_UP["etr"])


class _StudioJinglesGrid(QFrame):
    """6-pad compact jingles grid (3×2)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(146)
        self.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(4)

        title = QLabel("INSTANT JINGLES")
        title.setFont(inter(8, QFont.Weight.Black, letter_spacing=1.2))
        title.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        layout.addWidget(title)

        grid = QFrame(); grid.setStyleSheet("background: transparent;")
        gv = QVBoxLayout(grid); gv.setContentsMargins(0, 0, 0, 0); gv.setSpacing(4)
        # 2 rows × 3 columns
        for row_start in (0, 3):
            row = QHBoxLayout(); row.setSpacing(4); row.setContentsMargins(0, 0, 0, 0)
            for j in range(3):
                row.addWidget(_JinglePadTile(*JINGLES_PLACEHOLDER[row_start + j]))
            gv.addLayout(row)
        layout.addWidget(grid)


class _JinglePadTile(QFrame):
    """One compact jingle pad (~158×52)."""

    def __init__(self, code: str, name: str, dur: str, color: str, parent=None):
        super().__init__(parent)
        self._code  = code
        self._name  = name
        self._dur   = dur
        self._color = color
        self.setFixedHeight(52)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0, 0, self.width(), self.height())
        path = QPainterPath(); path.addRoundedRect(rect, 6, 6)
        p.setClipPath(path)
        bg = QColor(self._color); bg.setAlphaF(0.16)
        p.fillRect(rect, bg)
        p.setClipping(False)
        bc = QColor(self._color); bc.setAlphaF(0.40)
        p.setPen(QPen(bc, 1)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 6, 6)
        # Code (top-left)
        p.setPen(QColor(self._color))
        p.setFont(inter(11, QFont.Weight.Black))
        p.drawText(QRectF(8, 4, 50, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._code)
        # Name
        p.setPen(QColor(TEXT_PRI))
        p.setFont(inter(9, QFont.Weight.Medium))
        fm = p.fontMetrics()
        name = fm.elidedText(self._name, Qt.TextElideMode.ElideRight, self.width() - 16)
        p.drawText(QRectF(8, 18, self.width() - 16, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   name)
        # Duration (bottom-left, mono)
        p.setPen(QColor(TEXT_SEC))
        p.setFont(mono(8, bold=True))
        p.drawText(QRectF(8, 33, 50, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._dur)
        # Play glyph (bottom-right)
        p.setPen(QColor(self._color))
        p.setFont(inter(10, QFont.Weight.Bold))
        p.drawText(QRectF(self.width() - 22, 30, 16, 18),
                   Qt.AlignmentFlag.AlignCenter,
                   "▶")


# ════════════════════════════════════════════════════════════════════════════
# RIGHT — HISTORY / NEXT BREAK / SPOTS / AI / RDS
# ════════════════════════════════════════════════════════════════════════════

class _HistoryRow(QFrame):
    def __init__(self, time_str: str, title: str, artist: str, dur: str, parent=None):
        super().__init__(parent)
        self._time  = time_str
        self._title = title
        self._artist= artist
        self._dur   = dur
        self.setFixedHeight(34)
        self.setStyleSheet("background: transparent;")

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Time stamp
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(mono(9, bold=True))
        p.drawText(QRectF(8, 0, 50, self.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   self._time)
        # Title
        p.setPen(QColor(TEXT_PRI))
        p.setFont(inter(10, QFont.Weight.Medium))
        p.drawText(QRectF(70, 2, 280, 16),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   self._title)
        # Artist
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(inter(9))
        p.drawText(QRectF(70, 18, 280, 14),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   self._artist)
        # Duration
        p.setPen(QColor(TEXT_SEC))
        p.setFont(mono(9))
        p.drawText(QRectF(self.width() - 60, 0, 50, self.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                   self._dur)


class _NextBreakCard(QFrame):
    """Big countdown card — '04:26 / in 4 min 26 sec'."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(118)
        self.setStyleSheet(
            f"QFrame {{ background: {rgba('#ffffff', 0.02)}; "
            f"border: 1px solid {rgba(AMBER, 0.30)}; "
            f"border-left: 3px solid {AMBER}; "
            f"border-radius: 6px; }}"
        )

    def paintEvent(self, _e):
        super().paintEvent(_e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Header
        p.setPen(QColor(AMBER_LIGHT))
        p.setFont(inter(8, QFont.Weight.Black, letter_spacing=1.4))
        p.drawText(QRectF(14, 6, 200, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "NEXT BREAK")
        # Big countdown
        p.setPen(QColor(AMBER_LIGHT))
        p.setFont(mono(38, bold=True))
        p.drawText(QRectF(0, 22, self.width(), 64),
                   Qt.AlignmentFlag.AlignCenter,
                   "04:26")
        # Subtitle
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(inter(9))
        p.drawText(QRectF(0, self.height() - 22, self.width(), 18),
                   Qt.AlignmentFlag.AlignCenter,
                   "in 4 min 26 sec")


class _UpcomingSpotsList(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0); v.setSpacing(4)
        title = QLabel("UPCOMING SPOTS — NEXT 30 MIN")
        title.setFont(inter(8, QFont.Weight.Black, letter_spacing=1.2))
        title.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        v.addWidget(title)
        for time_str, name, dur in UPCOMING_SPOTS_PLACEHOLDER:
            row = _SpotRow(time_str, name, dur)
            v.addWidget(row)


class _SpotRow(QFrame):
    def __init__(self, time_str: str, name: str, dur: str, parent=None):
        super().__init__(parent)
        self._time = time_str
        self._name = name
        self._dur  = dur
        self.setFixedHeight(26)
        self.setStyleSheet(
            f"QFrame {{ background: {rgba('#ffffff', 0.02)}; "
            f"border: 1px solid {rgba('#ffffff', 0.04)}; "
            f"border-radius: 4px; }}"
        )

    def paintEvent(self, _e):
        super().paintEvent(_e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(mono(9, bold=True))
        p.drawText(QRectF(8, 0, 50, self.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   self._time)
        p.setPen(QColor(TEXT_PRI))
        p.setFont(inter(9, QFont.Weight.Medium))
        p.drawText(QRectF(60, 0, self.width() - 110, self.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   self._name)
        # Duration pill
        pill_w = 36
        pill = QRectF(self.width() - pill_w - 6, 4, pill_w, 18)
        bg = QColor(AMBER); bg.setAlphaF(0.18)
        p.setBrush(bg); p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(pill, 8, 8)
        p.setPen(QColor(AMBER_LIGHT))
        p.setFont(inter(8, QFont.Weight.Bold))
        p.drawText(pill, Qt.AlignmentFlag.AlignCenter, self._dur)


class _AIInsightsList(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0); v.setSpacing(4)
        title = QLabel("✦  AI INSIGHTS — NEXT 2 HOURS")
        title.setFont(inter(8, QFont.Weight.Black, letter_spacing=1.2))
        title.setStyleSheet(f"color: {PURPLE_LIGHT}; background: transparent;")
        v.addWidget(title)
        for kind, text in AI_INSIGHTS_PLACEHOLDER:
            v.addWidget(_AIInsightRow(kind, text))


class _AIInsightRow(QFrame):
    def __init__(self, kind: str, text: str, parent=None):
        super().__init__(parent)
        self._kind  = kind
        self._text  = text
        self.setFixedHeight(22)
        self.setStyleSheet("background: transparent;")

    def paintEvent(self, _e):
        super().paintEvent(_e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        glyph, color = _ai_icon(self._kind)
        p.setPen(QColor(color))
        p.setFont(inter(11, QFont.Weight.Bold))
        p.drawText(QRectF(4, 0, 16, self.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignCenter,
                   glyph)
        p.setPen(QColor(TEXT_PRI))
        p.setFont(inter(9))
        p.drawText(QRectF(24, 0, self.width() - 28, self.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   self._text)


class _RDSCard(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(70)
        self.setStyleSheet(
            f"QFrame {{ background: #0c0e1c; "
            f"border: 1px solid {rgba(AMBER, 0.30)}; "
            f"border-radius: 6px; }}"
        )

    def paintEvent(self, _e):
        super().paintEvent(_e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Branding
        p.setPen(QColor(AMBER_LIGHT))
        p.setFont(inter(15, QFont.Weight.Black, letter_spacing=2.5))
        p.drawText(QRectF(0, 6, self.width(), 30),
                   Qt.AlignmentFlag.AlignCenter,
                   "★  KISS  ★")
        # Current track
        p.setPen(QColor(TEXT_SEC))
        p.setFont(inter(10, QFont.Weight.Medium))
        p.drawText(QRectF(0, 38, self.width(), 22),
                   Qt.AlignmentFlag.AlignCenter,
                   "Drake — God's Plan")


# ════════════════════════════════════════════════════════════════════════════
# Status bar
# ════════════════════════════════════════════════════════════════════════════

class _StudioStatusBar(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(STATUS_H)
        self.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border-top: 1px solid {rgba('#ffffff', 0.06)}; }}"
        )

    def paintEvent(self, _e):
        super().paintEvent(_e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Left-side pills
        x = 12
        for label, color in [
            ("AUTO MODE", PURPLE_LIGHT),
            ("AI Active", GREEN),
            ("● ON AIR", RED),
            ("Log Ready", AMBER),
            ("7 Clocks",  CYAN),
            ("● SOHO Auto", PURPLE),
        ]:
            fm_text = label
            tw = p.fontMetrics().horizontalAdvance(fm_text) if False else 0
            # Compute width manually
            p.setFont(inter(8, QFont.Weight.Bold, letter_spacing=0.6))
            tw = p.fontMetrics().horizontalAdvance(fm_text) + 16
            pill = QRectF(x, (STATUS_H - 18) / 2, tw, 18)
            bg = QColor(color); bg.setAlphaF(0.18)
            p.setBrush(bg); p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(pill, 8, 8)
            p.setPen(QColor(color))
            p.drawText(pill, Qt.AlignmentFlag.AlignCenter, fm_text)
            x += tw + 6

        # Center text
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(inter(9, QFont.Weight.Medium))
        p.drawText(QRectF(0, 0, self.width(), self.height()),
                   Qt.AlignmentFlag.AlignCenter,
                   "NOW ON AIR  —  KISS FM 91.5  ·  91.5 MHz")

        # Right "Settings"
        p.setPen(QColor(TEXT_SEC))
        p.setFont(inter(9, QFont.Weight.Medium))
        p.drawText(QRectF(self.width() - 86, 0, 70, self.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                   "Settings")


# ════════════════════════════════════════════════════════════════════════════
# Studio screen
# ════════════════════════════════════════════════════════════════════════════

class Studio(QWidget):
    """Studio Single Deck — broadcast operator workstation (Figma 182:2).

    Phase D1: skeleton with hardcoded Figma example data. No audio
    wiring (D2), no scheduler (D3+).
    """

    breadcrumb_clicked = pyqtSignal(str)    # 'control_panel' navigation

    def __init__(self, db, parent=None, engine=None, scheduler=None):
        super().__init__(parent)
        self._db = db
        self._engine = engine          # Day D2 wires this
        self._scheduler = scheduler    # Day D3+ wires this
        self.setFixedSize(WINDOW_W, WINDOW_H)
        self.setStyleSheet(
            f"background: qlineargradient("
            f"x1:0,y1:0,x2:1,y2:1, stop:0 #0a0d1a, stop:0.5 #06080f, stop:1 #020308);"
        )

        self._build_header()
        self._build_left()
        self._build_center()
        self._build_right()
        self._build_status_bar()

        log.info("Studio ready (Figma 182:2)")

    # ── Header ────────────────────────────────────────────────────────────

    def _build_header(self):
        self._header = _StudioHeader(self)
        self._header.setGeometry(0, 0, WINDOW_W, HEADER_H)
        self._header.control_panel_clicked.connect(
            lambda: self.breadcrumb_clicked.emit("control_panel"))

    # ── Left ──────────────────────────────────────────────────────────────

    def _build_left(self):
        body_y = HEADER_H
        body_h = WINDOW_H - HEADER_H - STATUS_H
        self._queue = _PlaylistQueue(self)
        self._queue.setGeometry(LEFT_X, body_y, LEFT_W, body_h)

    # ── Center ────────────────────────────────────────────────────────────

    def _build_center(self):
        body_y = HEADER_H
        # Inner padding from top of body
        center_pad = 10

        # Sub-header with NOW PLAYING + AUTO MODE ON
        sub = QLabel("●  NOW PLAYING                           AUTO MODE ON", self)
        sub.setGeometry(CENTER_X + 12, body_y + 4, CENTER_W - 24, 20)
        sub.setFont(inter(8, QFont.Weight.Black, letter_spacing=1.4))
        sub.setStyleSheet(f"color: {GREEN_LIGHT}; background: transparent;")

        y = body_y + 28

        # Now playing card
        self._now_playing = _NowPlayingCard(self)
        self._now_playing.setGeometry(CENTER_X + center_pad, y, CENTER_W - 2 * center_pad, 86)
        y += 92

        # Waveform
        self._waveform = _StudioWaveform(self)
        self._waveform.setGeometry(CENTER_X + center_pad, y, CENTER_W - 2 * center_pad, 110)
        y += 116

        # Countdown
        self._countdown = _Countdown(self)
        self._countdown.setGeometry(CENTER_X + center_pad, y, CENTER_W - 2 * center_pad, 70)
        y += 76

        # Transport row
        self._transport = _TransportRow(self)
        self._transport.setGeometry(CENTER_X + center_pad, y, CENTER_W - 2 * center_pad, 36)
        y += 42

        # Master vol
        self._master_vol = _MasterVolumeStrip(self)
        self._master_vol.setGeometry(CENTER_X + center_pad, y, CENTER_W - 2 * center_pad, 28)
        y += 36

        # Next up
        self._next_up = _NextUpCard(self)
        self._next_up.setGeometry(CENTER_X + center_pad, y, CENTER_W - 2 * center_pad, 64)
        y += 70

        # Jingles grid
        self._jingles = _StudioJinglesGrid(self)
        self._jingles.setGeometry(CENTER_X + center_pad, y, CENTER_W - 2 * center_pad, 146)

    # ── Right ─────────────────────────────────────────────────────────────

    def _build_right(self):
        body_y = HEADER_H
        right_pad = 12

        y = body_y + 4

        # History header
        history_hdr = QLabel("HISTORY  —  PREVIOUSLY PLAYED", self)
        history_hdr.setGeometry(RIGHT_X + right_pad, y, RIGHT_W - 2 * right_pad, 18)
        history_hdr.setFont(inter(8, QFont.Weight.Black, letter_spacing=1.4))
        history_hdr.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        y += 22

        # History list
        for time_str, title, artist, dur in HISTORY_PLACEHOLDER:
            row = _HistoryRow(time_str, title, artist, dur, self)
            row.setGeometry(RIGHT_X + right_pad, y, RIGHT_W - 2 * right_pad, 34)
            y += 36
        y += 8

        # Next Break card
        nb = _NextBreakCard(self)
        nb.setGeometry(RIGHT_X + right_pad, y, RIGHT_W - 2 * right_pad, 118)
        y += 124

        # Upcoming spots
        spots = _UpcomingSpotsList(self)
        spots.setGeometry(RIGHT_X + right_pad, y, RIGHT_W - 2 * right_pad, 110)
        y += 116

        # AI Insights
        ai = _AIInsightsList(self)
        ai.setGeometry(RIGHT_X + right_pad, y, RIGHT_W - 2 * right_pad, 130)
        y += 136

        # RDS card
        rds = _RDSCard(self)
        rds.setGeometry(RIGHT_X + right_pad, y, RIGHT_W - 2 * right_pad, 70)

    # ── Status bar ────────────────────────────────────────────────────────

    def _build_status_bar(self):
        self._status_bar = _StudioStatusBar(self)
        self._status_bar.setGeometry(0, WINDOW_H - STATUS_H, WINDOW_W, STATUS_H)
