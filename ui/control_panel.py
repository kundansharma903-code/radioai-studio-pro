"""
RadioAI Studio Pro — Control Panel
Pixel-accurate match of Figma node 192:2 (file 7oN9K61g94wKx3nu44KKDF).

Composes premium widgets from ui/widgets/ plus a few inline private
widgets (LogoBox, StationCard, OpenStudioButton, LivePill, LibraryRowCard)
that are specific to this screen and not reusable elsewhere.

Layout (absolute positioning, 1440×900):
  Header           y=0..88   (logo + brand + nav + clock + station card + Open Studio)
  Page title       y=128..192 ("Libraries" + subtitle + LIVE pill right)
  Cards grid       y=238..618 (2×3, 652×116, 24px col gap, 16px row gap)
  Footer           y=856..888 (hairline + brand line + Settings link)
"""

import logging
import time
from datetime import datetime

from PyQt6.QtCore import (
    Qt, QRectF, QTimer, QPropertyAnimation, pyqtProperty, pyqtSignal,
)
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QLinearGradient, QPainterPath,
    QFont, QCursor, QFontMetrics,
)
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QGraphicsDropShadowEffect,
)

from core.settings import Settings
from ui.widgets._tokens import (
    inter, mono, rgba,
    BG_BASE, TEXT_PRI, TEXT_SEC, TEXT_MUTED, TEXT_DIM,
    CYAN, CYAN_LIGHT, PURPLE, PURPLE_LIGHT, GREEN, GREEN_LIGHT,
    AMBER, AMBER_LIGHT, PINK, PINK_LIGHT, RED, RED_LIGHT,
)
from ui.widgets.pictorial_icon import PictorialIcon, IconType

log = logging.getLogger("ControlPanel")


# ════════════════════════════════════════════════════════════════════════════
# Card spec — each library row's full Figma data
# ════════════════════════════════════════════════════════════════════════════

CARD_SPECS = [
    dict(
        key="songs", x=56, y=238, icon=IconType.SONGS,
        title="Songs", stat="14,733 Songs Available",
        desc="5 Categories • Smart AI rotation with history analytics",
        badge="MAIN LIBRARY",
        main=CYAN, light=CYAN_LIGHT, mid="#0891b2", dark="#0e7490",
        stat_text=CYAN_LIGHT,  # #22d3ee per Figma
    ),
    dict(
        key="instant_jingles", x=732, y=238, icon=IconType.INSTANT,
        title="Instant Jingles", stat="266 Jingles • 9 Pallets",
        desc="Live broadcast pads with per-producer setup",
        badge="LIVE TOOLS",
        main=PURPLE_LIGHT, light=PURPLE_LIGHT, mid=PURPLE, dark="#7c3aed",
        stat_text="#c4b5fd",
    ),
    dict(
        key="spots", x=56, y=370, icon=IconType.SPOTS,
        title="Spots & Commercials", stat="29 Active Spots",
        desc="4 Active campaigns • Traffic synced • Next break 22:00",
        badge="REVENUE",
        main=GREEN, light=GREEN_LIGHT, mid="#059669", dark="#047857",
        stat_text=GREEN_LIGHT,
    ),
    dict(
        key="jingles", x=732, y=370, icon=IconType.JINGLES,
        title="Jingles", stat="293 Jingles Available",
        desc="4 Categories • Auto-Play • Schedule via clocks",
        badge="BRANDING",
        main=AMBER, light=AMBER_LIGHT, mid="#d97706", dark="#b45309",
        stat_text=AMBER_LIGHT,
    ),
    dict(
        key="sweepers", x=56, y=502, icon=IconType.SWEEPERS,
        title="Sweepers", stat="28 Sweepers Available",
        desc="Audio overlays at start, intro, end, bridge positions",
        badge="PRODUCTION",
        main=PINK, light=PINK_LIGHT, mid="#db2777", dark="#be185d",
        stat_text=PINK_LIGHT,
    ),
    dict(
        key="stitcher", x=732, y=502, icon=IconType.STITCHER,
        title="The Stitcher", stat="3 Active Modules",
        desc="AI auto-builds hooks, time announcements & news",
        badge="AI POWERED",
        main=RED, light=RED_LIGHT, mid="#e11d48", dark="#be123c",
        stat_text=RED_LIGHT,
    ),
    # Phase F2.1 — entry point to Clock Editor (F3 Hub will replace this
    # link with a routing card once built).
    dict(
        key="scheduling", x=56, y=634, icon=IconType.SONGS,
        title="Scheduling", stat="26 Clocks · 88 Hour Slots",
        desc="Build clocks · assign to days/hours · force overrides",
        badge="SCHEDULER",
        main=CYAN, light=CYAN_LIGHT, mid="#0891b2", dark="#0e7490",
        stat_text=CYAN_LIGHT,
    ),
]


# ════════════════════════════════════════════════════════════════════════════
# LibraryRowCard — one of the 6 cards (652×116)
# ════════════════════════════════════════════════════════════════════════════

class _LibraryRowCard(QFrame):

    clicked = pyqtSignal(str)

    def __init__(self, spec: dict, parent=None):
        super().__init__(parent)
        self._spec = spec
        self._main  = QColor(spec["main"])
        self._light = QColor(spec["light"])
        self._mid   = QColor(spec["mid"])
        self._dark  = QColor(spec["dark"])
        self._hover = False
        self.setFixedSize(652, 116)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        # Drop shadow — combine black depth + color glow into single shadow
        sh = QGraphicsDropShadowEffect(self)
        sh.setOffset(0, 12)
        sh.setBlurRadius(36)
        c = QColor(self._main); c.setAlpha(60)
        sh.setColor(c)
        self.setGraphicsEffect(sh)

        # ── Inner widgets (absolute positioning) ───────────────────────────

        # PictorialIcon inside the icon box
        icon = PictorialIcon(spec["icon"], color=spec["main"], light=spec["light"], size=34, parent=self)
        # icon box at (23, 21) 66×66 — center icon (34×34) at +16,+16
        icon.move(23 + (66 - 34) // 2, 21 + (66 - 34) // 2)
        # Don't double the glow — icon paints its own
        icon.setGraphicsEffect(None)

        # Title
        title = QLabel(spec["title"], self)
        title.setGeometry(109, 23, 420, 32)
        title.setFont(inter(24, QFont.Weight.Black, letter_spacing=-0.6))
        title.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")

        # Stat (with text-shadow simulated via glow effect on the label)
        stat = QLabel(spec["stat"], self)
        stat.setGeometry(109, 55, 420, 18)
        stat.setFont(inter(13, QFont.Weight.Bold, letter_spacing=-0.1))
        stat.setStyleSheet(f"color: {spec['stat_text']}; background: transparent;")
        stat_glow = QGraphicsDropShadowEffect(stat)
        stat_glow.setOffset(0, 1)
        stat_glow.setBlurRadius(6)
        gc = QColor(self._main); gc.setAlpha(102)
        stat_glow.setColor(gc)
        stat.setGraphicsEffect(stat_glow)

        # Description
        desc = QLabel(spec["desc"], self)
        desc.setGeometry(109, 77, 430, 16)
        desc.setFont(inter(11, QFont.Weight.Medium, letter_spacing=-0.05))
        desc.setStyleSheet(f"color: {TEXT_SEC}; background: transparent;")

        # Badge top-right (custom paint via private QFrame)
        badge_w = max(60, QFontMetrics(inter(8, QFont.Weight.Black, 1.2)).horizontalAdvance(spec["badge"]) + 16)
        self._badge_geom = (652 - 25 - badge_w, 21, badge_w, 22)
        badge = _ColoredPill(spec["badge"], spec["main"], spec["light"], parent=self)
        badge.setGeometry(*self._badge_geom)

        # Open → button bottom-right
        open_btn = _OpenButton(spec["main"], spec["light"], parent=self)
        open_btn.setGeometry(652 - 25 - 66, 79, 66, 26)
        open_btn.clicked.connect(lambda: self.clicked.emit(self._spec["key"]))

    # ── Paint base + accents ─────────────────────────────────────────────

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(0, 0, self.width(), self.height())
        path = QPainterPath()
        path.addRoundedRect(rect, 18, 18)
        p.setClipPath(path)

        # Body — vertical gradient rgba(14,16,32,0.95) → rgba(7,9,18,0.95)
        body = QLinearGradient(0, 0, 0, self.height())
        body.setColorAt(0.0, QColor(14, 16, 32, 242))
        body.setColorAt(1.0, QColor(7, 9, 18, 242))
        p.fillRect(self.rect(), QBrush(body))

        # Top accent overlay — color tint top 107px (95% → transparent at 70%)
        ov_h = 107
        ov = QLinearGradient(0, 0, 0, ov_h)
        c1 = QColor(self._main); c1.setAlphaF(0.05)
        c2 = QColor(self._main); c2.setAlphaF(0.0)
        ov.setColorAt(0.0, c1)
        ov.setColorAt(0.7, c2)
        p.fillRect(0, 0, self.width(), ov_h, QBrush(ov))

        # Top 3px gradient bar (light → mid → dark, horizontal)
        top = QLinearGradient(0, 0, self.width(), 0)
        top.setColorAt(0.0, self._light)
        top.setColorAt(0.5, self._mid)
        top.setColorAt(1.0, self._dark)
        p.fillRect(0, 0, self.width(), 3, QBrush(top))

        # 1px border (white@6%, hover: color@40%)
        p.setClipping(False)
        if self._hover:
            bc = QColor(self._main); bc.setAlpha(120)
            p.setPen(QPen(bc, 1.5))
        else:
            p.setPen(QPen(QColor(255, 255, 255, 16), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 18, 18)

        # ── Icon box (66×66 at 23,21) ──────────────────────────────────────
        ix, iy, isz = 23, 21, 66
        ipath = QPainterPath()
        ipath.addRoundedRect(QRectF(ix, iy, isz, isz), 16, 16)
        p.setClipPath(ipath)
        # Body — diagonal gradient
        ig = QLinearGradient(ix, iy, ix + isz, iy + isz)
        a1 = QColor(self._main); a1.setAlphaF(0.22)
        a2 = QColor(self._dark); a2.setAlphaF(0.10)
        ig.setColorAt(0.0, a1)
        ig.setColorAt(0.71, a2)
        p.fillRect(ix, iy, isz, isz, QBrush(ig))
        # Inner top highlight 64×32 white@15%
        ih = QLinearGradient(0, iy, 0, iy + 32)
        ih.setColorAt(0.0, QColor(255, 255, 255, 38))
        ih.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.fillRect(ix, iy, 64, 32, QBrush(ih))
        # Border
        p.setClipping(False)
        bc = QColor(self._main); bc.setAlphaF(0.35)
        p.setPen(QPen(bc, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(ix + 0.5, iy + 0.5, isz - 1, isz - 1), 16, 16)

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._spec["key"])
        super().mousePressEvent(e)


class _ColoredPill(QLabel):
    """Top-right uppercase badge with gradient + color border."""

    def __init__(self, text: str, main: str, light: str, parent=None):
        super().__init__(text.upper(), parent)
        self._main = QColor(main)
        self._light = QColor(light)
        self.setFont(inter(8, QFont.Weight.Black, letter_spacing=1.2))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        # Gradient 166deg ≈ vertical with slight tilt
        g = QLinearGradient(0, 0, 0, self.height())
        c1 = QColor(self._main); c1.setAlphaF(0.20)
        c2 = QColor(self._main); c2.setAlphaF(0.08)
        g.setColorAt(0.0, c1)
        g.setColorAt(1.0, c2)
        p.setBrush(QBrush(g))
        bc = QColor(self._main); bc.setAlphaF(0.30)
        p.setPen(QPen(bc, 1))
        p.drawRoundedRect(rect, 11, 11)
        p.setPen(self._light)
        p.setFont(self.font())
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text())


class _OpenButton(QPushButton):
    """Bottom-right Open → pill. Same color family as parent card."""

    def __init__(self, main: str, light: str, parent=None):
        super().__init__("Open  →", parent)
        self._main = QColor(main)
        self._light = QColor(light)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFlat(True)
        self.setStyleSheet("background: transparent; border: none;")
        self.setFont(inter(11, QFont.Weight.Bold, letter_spacing=0.3))

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        g = QLinearGradient(0, 0, self.width(), 0)
        c1 = QColor(self._main); c1.setAlphaF(0.18)
        c2 = QColor(self._main); c2.setAlphaF(0.06)
        g.setColorAt(0.0, c1)
        g.setColorAt(1.0, c2)
        p.setBrush(QBrush(g))
        bc = QColor(self._main); bc.setAlphaF(0.30)
        p.setPen(QPen(bc, 1))
        p.drawRoundedRect(rect, 8, 8)
        p.setPen(self._light)
        p.setFont(self.font())
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text())


# ════════════════════════════════════════════════════════════════════════════
# Header pieces
# ════════════════════════════════════════════════════════════════════════════

class _LogoBox(QWidget):
    """52×52 gradient logo box with 5 white waveform bars."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(52, 52)
        sh = QGraphicsDropShadowEffect(self)
        sh.setOffset(0, 8)
        sh.setBlurRadius(24)
        sh.setColor(QColor(124, 58, 237, 102))  # 40%
        self.setGraphicsEffect(sh)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0, 0, 52, 52)
        path = QPainterPath()
        path.addRoundedRect(rect, 14, 14)
        p.setClipPath(path)
        # Gradient 135deg
        g = QLinearGradient(0, 0, 52, 52)
        g.setColorAt(0.0,   QColor("#a78bfa"))
        g.setColorAt(0.355, QColor("#7c3aed"))
        g.setColorAt(0.711, QColor("#5b21b6"))
        p.fillRect(rect, QBrush(g))
        # Inner top white@20% highlight
        hi = QLinearGradient(0, 0, 0, 16)
        hi.setColorAt(0.0, QColor(255, 255, 255, 51))
        hi.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.fillRect(0, 0, 52, 16, QBrush(hi))
        # 5 white bars (heights 6,14,22,14,6)
        p.setBrush(QColor(255, 255, 255, 242))
        p.setPen(Qt.PenStyle.NoPen)
        for x, h in [(8, 6), (16, 14), (24, 22), (32, 14), (40, 6)]:
            top = (52 - h) // 2
            p.drawRoundedRect(QRectF(x, top, 4, h), 2, 2)
        # Border highlight
        p.setClipping(False)
        p.setPen(QPen(QColor(255, 255, 255, 51), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(0.5, 0.5, 51, 51), 14, 14)


class _StationCard(QWidget):
    """Header station card (220×60) with green left bar + pulsing dot."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(220, 60)
        self._dot_alpha = 1.0
        self._anim = QPropertyAnimation(self, b"dotAlpha", self)
        self._anim.setDuration(1600)
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.4)
        self._anim.setLoopCount(-1)
        self._anim.start()

    def get_dotAlpha(self): return self._dot_alpha
    def set_dotAlpha(self, v): self._dot_alpha = v; self.update()
    dotAlpha = pyqtProperty(float, get_dotAlpha, set_dotAlpha)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0.5, 0.5, 219, 59)
        path = QPainterPath()
        path.addRoundedRect(rect, 12, 12)
        p.setClipPath(path)
        # Background gradient
        g = QLinearGradient(0, 0, 220, 60)
        c1 = QColor(GREEN); c1.setAlphaF(0.12)
        c2 = QColor(GREEN); c2.setAlphaF(0.04)
        g.setColorAt(0.0, c1)
        g.setColorAt(0.71, c2)
        p.fillRect(QRectF(0, 0, 220, 60), QBrush(g))
        # Inner top green highlight
        ih = QLinearGradient(0, 0, 0, 24)
        ih.setColorAt(0.0, QColor(16, 185, 129, 38))
        ih.setColorAt(1.0, QColor(16, 185, 129, 0))
        p.fillRect(0, 0, 220, 24, QBrush(ih))
        # Left bar 4×60 vertical gradient green→cyan
        lb = QLinearGradient(0, 0, 0, 60)
        lb.setColorAt(0.0, QColor(GREEN))
        lb.setColorAt(1.0, QColor(CYAN))
        p.fillRect(0, 0, 4, 60, QBrush(lb))
        # Border
        p.setClipping(False)
        bc = QColor(GREEN); bc.setAlphaF(0.25)
        p.setPen(QPen(bc, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 12, 12)
        # Text labels
        p.setPen(QColor(GREEN))
        p.setFont(inter(8, QFont.Weight.Bold, letter_spacing=1.5))
        p.drawText(13, 16, 200, 12, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "ACTIVE STATION")
        p.setPen(QColor(TEXT_PRI))
        p.setFont(inter(14, QFont.Weight.Bold, letter_spacing=-0.2))
        p.drawText(13, 26, 200, 18, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   Settings().station_display)
        p.setPen(QColor(TEXT_SEC))
        p.setFont(inter(10, QFont.Weight.Medium))
        p.drawText(13, 41, 200, 14, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "Jaipur, Rajasthan")
        # Pulsing green dot at (197, 28) 4×4 with halo at (194, 25) 10×10
        halo = QColor(GREEN); halo.setAlphaF(self._dot_alpha * 0.4)
        p.setBrush(halo)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(194, 25, 10, 10)
        dot = QColor(GREEN); dot.setAlphaF(self._dot_alpha)
        p.setBrush(dot)
        p.drawEllipse(197, 28, 4, 4)


class _OpenStudioButton(QPushButton):
    """Header Open Studio CTA (200×52) — gradient + 2-line label + glow."""

    clicked_signal = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("", parent)
        self.setFixedSize(200, 52)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFlat(True)
        self.setStyleSheet("background: transparent; border: none;")
        # Multi-layer glow — single QGraphicsDropShadowEffect
        sh = QGraphicsDropShadowEffect(self)
        sh.setOffset(0, 8)
        sh.setBlurRadius(32)
        sh.setColor(QColor(124, 58, 237, 140))
        self.setGraphicsEffect(sh)
        self._hover = False

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0, 0, 200, 52)
        path = QPainterPath()
        path.addRoundedRect(rect, 14, 14)
        p.setClipPath(path)
        # Gradient 165deg
        g = QLinearGradient(0, 0, 200, 52)
        if self._hover:
            g.setColorAt(0.0, QColor("#c4b5fd"))
            g.setColorAt(0.5, QColor("#a78bfa"))
            g.setColorAt(1.0, QColor("#8b5cf6"))
        else:
            g.setColorAt(0.0,   QColor("#a78bfa"))
            g.setColorAt(0.355, QColor("#8b5cf6"))
            g.setColorAt(0.711, QColor("#7c3aed"))
        p.fillRect(rect, QBrush(g))
        # Inner top white@15% highlight
        hi = QLinearGradient(0, 0, 0, 24)
        hi.setColorAt(0.0, QColor(255, 255, 255, 38))
        hi.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.fillRect(0, 0, 200, 24, QBrush(hi))
        # Border
        p.setClipping(False)
        p.setPen(QPen(QColor(255, 255, 255, 64), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(0.5, 0.5, 199, 51), 14, 14)
        # Play icon — circle with ▶
        p.setBrush(QColor(255, 255, 255, 51))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(16, 14, 24, 24)
        p.setPen(QColor(255, 255, 255))
        p.setFont(inter(11, QFont.Weight.Bold))
        p.drawText(16, 14, 24, 24, Qt.AlignmentFlag.AlignCenter, "▶")
        # "Open Studio" 14px
        p.setPen(QColor(255, 255, 255))
        p.setFont(inter(14, QFont.Weight.Bold, letter_spacing=-0.2))
        p.drawText(50, 10, 140, 18, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "Open Studio")
        # "GO LIVE NOW" 8px
        p.setPen(QColor(255, 255, 255, 178))
        p.setFont(inter(8, QFont.Weight.DemiBold, letter_spacing=1.8))
        p.drawText(50, 30, 140, 14, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "GO LIVE NOW")

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)


class _LivePill(QWidget):
    """Top-right LIVE pill (144×44) — red gradient + pulsing dot + clock."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(144, 44)
        self._dot_alpha = 1.0
        self._time_str = datetime.now().strftime("%H:%M:%S")

        self._anim = QPropertyAnimation(self, b"dotAlpha", self)
        self._anim.setDuration(1400)
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.4)
        self._anim.setLoopCount(-1)
        self._anim.start()

        self._t = QTimer(self)
        self._t.setInterval(1000)
        self._t.timeout.connect(self._tick)
        self._t.start()

        sh = QGraphicsDropShadowEffect(self)
        sh.setOffset(0, 4)
        sh.setBlurRadius(16)
        sh.setColor(QColor(244, 63, 94, 80))
        self.setGraphicsEffect(sh)

    def _tick(self):
        self._time_str = datetime.now().strftime("%H:%M:%S")
        self.update()

    def get_dotAlpha(self): return self._dot_alpha
    def set_dotAlpha(self, v): self._dot_alpha = v; self.update()
    dotAlpha = pyqtProperty(float, get_dotAlpha, set_dotAlpha)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0.5, 0.5, 143, 43)
        path = QPainterPath()
        path.addRoundedRect(rect, 22, 22)
        p.setClipPath(path)
        # Background gradient 163deg dark red
        g = QLinearGradient(0, 0, 144, 44)
        g.setColorAt(0.0,   QColor(127, 29, 29, 102))
        g.setColorAt(0.71,  QColor(69, 10, 10, 102))
        p.fillRect(QRectF(0, 0, 144, 44), QBrush(g))
        # Border
        p.setClipping(False)
        bc = QColor(244, 63, 94, 76)  # 30%
        p.setPen(QPen(bc, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 22, 22)
        # Pulsing dot at (15, 17) 8×8
        halo = QColor(244, 63, 94)
        halo.setAlphaF(self._dot_alpha * 0.4)
        p.setBrush(halo); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(11, 13, 16, 16)
        dot = QColor(244, 63, 94)
        dot.setAlphaF(self._dot_alpha)
        p.setBrush(dot)
        p.drawEllipse(15, 17, 8, 8)
        # "LIVE"
        p.setPen(QColor(244, 63, 94))
        p.setFont(inter(11, QFont.Weight.Black, letter_spacing=1.5))
        p.drawText(31, 13, 40, 18, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "LIVE")
        # Clock
        p.setPen(QColor(TEXT_PRI))
        p.setFont(mono(13, bold=True))
        p.drawText(67, 12, 80, 20, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._time_str)


# ════════════════════════════════════════════════════════════════════════════
# ControlPanel — full 1440×900 screen
# ════════════════════════════════════════════════════════════════════════════

class ControlPanel(QWidget):

    card_clicked     = pyqtSignal(str)
    studio_clicked   = pyqtSignal()
    nav_clicked      = pyqtSignal(str)
    settings_clicked = pyqtSignal()

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self._db = db
        self.setFixedSize(1440, 900)

        # The window background is provided by premium.qss (gradient).
        # Apply same gradient locally as a guard.
        self.setStyleSheet(
            f"background: qlineargradient("
            f"x1:0,y1:0,x2:1,y2:1, stop:0 #0a0d1a, stop:0.5 #06080f, stop:1 #020308);"
        )

        # Holders for live updates
        self._clock_main_lbl = None
        self._clock_sec_lbl  = None
        self._dow_lbl        = None
        self._date_lbl       = None
        self._uptime_lbl     = None
        # Monotonic program-start reference for the footer uptime line.
        self._start_monotonic = time.monotonic()

        self._build_header()
        self._build_page_title()
        self._build_cards()
        self._build_footer()

        # Inject real DB stats over the placeholder card text
        self._refresh_card_data()

        # Header clock tick
        self._tick()
        t = QTimer(self)
        t.setInterval(1000)
        t.timeout.connect(self._tick)
        t.start()

        log.info("ControlPanel ready (Figma 192:2)")

    # ── HEADER ───────────────────────────────────────────────────────────

    def _build_header(self):
        # Background gradient (16,19,31,0.9) → (10,12,22,0.9)
        bg = QFrame(self)
        bg.setGeometry(0, 0, 1440, 88)
        bg.setStyleSheet(
            f"background: qlineargradient(x1:0,y1:0,x2:0,y2:1, "
            f"stop:0 rgba(16,19,31,0.9), stop:1 rgba(10,12,22,0.9));"
        )

        # Bottom hairline at y=87 — horizontal gradient transparent → white@10% → transparent
        hairline = QFrame(self)
        hairline.setGeometry(0, 87, 1440, 1)
        hairline.setStyleSheet(
            f"background: qlineargradient(x1:0,y1:0,x2:1,y2:0, "
            f"stop:0 rgba(255,255,255,0), stop:0.5 rgba(255,255,255,0.10), "
            f"stop:1 rgba(255,255,255,0));"
        )

        # Logo box (28, 18, 52×52)
        logo = _LogoBox(self)
        logo.move(28, 18)

        # Brand text
        l = QLabel("RadioAI", self)
        l.setGeometry(92, 16, 200, 26)
        l.setFont(inter(22, QFont.Weight.Black, letter_spacing=-0.5))
        l.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")

        l = QLabel("STUDIO PRO", self)
        l.setGeometry(92, 45, 200, 12)
        l.setFont(inter(9, QFont.Weight.Bold, letter_spacing=2.5))
        l.setStyleSheet(f"color: {PURPLE_LIGHT}; background: transparent;")

        l = QLabel("BROADCAST AUTOMATION", self)
        l.setGeometry(92, 60, 200, 12)
        l.setFont(inter(8, QFont.Weight.Medium, letter_spacing=1.5))
        l.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

        # Nav tabs
        nav = [
            ("Libraries",  240, True,  TEXT_PRI),
            ("Scheduling", 358, False, TEXT_SEC),
            ("Settings",   478, False, TEXT_SEC),
            ("AI Magic ✦", 590, False, TEXT_SEC),
        ]
        for text, x, active, color in nav:
            btn = QPushButton(text, self)
            weight = "900" if active else "500"
            btn.setGeometry(x, 30, 130, 24)
            btn.setFont(inter(14, QFont.Weight.Black if active else QFont.Weight.Medium,
                              letter_spacing=-0.2))
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {color}; "
                f"border: none; padding: 0; text-align: left; }}"
                f"QPushButton:hover {{ color: {TEXT_PRI}; }}"
            )
            btn.clicked.connect(lambda _=False, t=text: self.nav_clicked.emit(t))

        # Active tab gradient underline (240, 60, 82×3)
        underline = QFrame(self)
        underline.setGeometry(240, 60, 82, 3)
        underline.setStyleSheet(
            f"background: qlineargradient(x1:0,y1:0,x2:1,y2:0, "
            f"stop:0 #06b6d4, stop:0.5 #a78bfa, stop:1 #ec4899); border-radius: 2px;"
        )
        ushadow = QGraphicsDropShadowEffect(underline)
        ushadow.setOffset(0, 0); ushadow.setBlurRadius(10)
        ushadow.setColor(QColor(167, 139, 250, 153))
        underline.setGraphicsEffect(ushadow)

        # Clock (740, 16) "21:56" + (832, 22) ":15"
        self._clock_main_lbl = QLabel("21:56", self)
        self._clock_main_lbl.setGeometry(740, 14, 92, 36)
        self._clock_main_lbl.setFont(mono(32, bold=True, letter_spacing=-1.0))
        self._clock_main_lbl.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")

        self._clock_sec_lbl = QLabel(":15", self)
        self._clock_sec_lbl.setGeometry(832, 22, 60, 30)
        self._clock_sec_lbl.setFont(mono(26, bold=True, letter_spacing=-1.0))
        self._clock_sec_lbl.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

        self._dow_lbl = QLabel("TUESDAY", self)
        self._dow_lbl.setGeometry(740, 54, 80, 12)
        self._dow_lbl.setFont(inter(9, QFont.Weight.Bold, letter_spacing=2.0))
        self._dow_lbl.setStyleSheet(f"color: {PURPLE_LIGHT}; background: transparent;")

        self._date_lbl = QLabel("JANUARY 31, 2023", self)
        self._date_lbl.setGeometry(800, 54, 200, 12)
        self._date_lbl.setFont(inter(9, QFont.Weight.Medium, letter_spacing=1.0))
        self._date_lbl.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

        # Station card (968, 14)
        sc = _StationCard(self)
        sc.move(968, 14)

        # Open Studio button (1208, 18)
        osb = _OpenStudioButton(self)
        osb.move(1208, 18)
        osb.clicked.connect(self.studio_clicked.emit)

    # ── PAGE TITLE ───────────────────────────────────────────────────────

    def _build_page_title(self):
        l = QLabel("Libraries", self)
        l.setGeometry(56, 124, 400, 56)
        l.setFont(inter(44, QFont.Weight.Black, letter_spacing=-1.5))
        l.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")

        l = QLabel("Manage all your audio content with intelligent rotation", self)
        l.setGeometry(56, 184, 600, 18)
        l.setFont(inter(14, QFont.Weight.Medium, letter_spacing=-0.1))
        l.setStyleSheet(f"color: {TEXT_SEC}; background: transparent;")

        # Live pill at (1240, 136)
        lp = _LivePill(self)
        lp.move(1240, 136)

    # ── CARDS GRID ───────────────────────────────────────────────────────

    def _build_cards(self):
        self._cards = {}
        for spec in CARD_SPECS:
            card = _LibraryRowCard(spec, self)
            card.move(spec["x"], spec["y"])
            card.clicked.connect(self.card_clicked.emit)
            self._cards[spec["key"]] = card

    # ── FOOTER ───────────────────────────────────────────────────────────

    def _build_footer(self):
        # Hairline at (56, 856)
        hl = QFrame(self)
        hl.setGeometry(56, 856, 1328, 1)
        hl.setStyleSheet(
            f"background: qlineargradient(x1:0,y1:0,x2:1,y2:0, "
            f"stop:0 rgba(255,255,255,0), stop:0.5 rgba(255,255,255,0.06), "
            f"stop:1 rgba(255,255,255,0));"
        )

        # Brand line
        l = QLabel("RadioAI Studio Pro", self)
        l.setGeometry(56, 870, 200, 14)
        l.setFont(inter(10, QFont.Weight.Bold, letter_spacing=0.3))
        l.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

        for x, ch, color in [(162, "•", TEXT_DIM), (225, "•", TEXT_DIM)]:
            l = QLabel(ch, self)
            l.setGeometry(x, 870, 12, 14)
            l.setFont(inter(10, QFont.Weight.Bold))
            l.setStyleSheet(f"color: {color}; background: transparent;")

        l = QLabel("v2.0.0", self)
        l.setGeometry(177, 870, 60, 14)
        l.setFont(mono(10, bold=False, letter_spacing=0.3))
        l.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

        self._uptime_lbl = QLabel("Program running 0 minutes", self)
        self._uptime_lbl.setGeometry(240, 870, 250, 14)
        self._uptime_lbl.setFont(inter(10, QFont.Weight.Medium, letter_spacing=0.3))
        self._uptime_lbl.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        self._update_uptime()

        # Settings link bottom right
        gear = QLabel("⚙", self)
        gear.setGeometry(1319, 866, 18, 18)
        gear.setFont(inter(14, QFont.Weight.Bold))
        gear.setStyleSheet(f"color: {PURPLE_LIGHT}; background: transparent;")

        s = QPushButton("Settings", self)
        s.setGeometry(1339, 868, 70, 16)
        s.setFont(inter(11, QFont.Weight.Bold, letter_spacing=-0.1))
        s.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        s.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {PURPLE_LIGHT}; "
            f"border: none; padding: 0; text-align: left; }}"
            f"QPushButton:hover {{ color: {TEXT_PRI}; }}"
        )
        s.clicked.connect(self.settings_clicked.emit)

    # ── Live updates ─────────────────────────────────────────────────────

    def _tick(self):
        n = datetime.now()
        if self._clock_main_lbl:
            self._clock_main_lbl.setText(n.strftime("%H:%M"))
        if self._clock_sec_lbl:
            self._clock_sec_lbl.setText(":" + n.strftime("%S"))
        if self._dow_lbl:
            self._dow_lbl.setText(n.strftime("%A").upper())
        if self._date_lbl:
            self._date_lbl.setText(n.strftime("%B %d, %Y").upper())
        self._update_uptime()

    def _update_uptime(self):
        """Refresh the footer uptime line from the monotonic start time.
        Cheap — no DB, integer minutes only. Called on the existing 1s tick."""
        if not self._uptime_lbl:
            return
        minutes = int((time.monotonic() - self._start_monotonic) // 60)
        unit = "minute" if minutes == 1 else "minutes"
        self._uptime_lbl.setText(f"Program running {minutes} {unit}")

    def _refresh_card_data(self):
        """Inject real DB counts over the placeholder strings."""
        try:
            stats = self._db.get_dashboard_stats()
        except Exception as exc:
            log.error(f"stats error: {exc}")
            return

        # Stitcher line is module-state aware: counts non-empty audio
        # slots when enabled, says "Disabled" when not. Single source
        # of truth (stitcher_active + stitcher_enabled) lives on
        # get_dashboard_stats so any other surface stays in lockstep.
        if int(stats.get("stitcher_enabled", 0) or 0):
            stitcher_line = f"{stats.get('stitcher_active', 0)} Active Modules"
        else:
            stitcher_line = "Module Disabled"

        live_stats = {
            "songs":           f"{stats.get('songs_total', 0):,} Songs Available",
            # Instant Jingles surfaces the live PADS count — pads with
            # audio assigned can actually fire on the broadcast device.
            # The master library jingle count lives on the separate
            # 🔔 Jingles card; conflating them was the original bug.
            "instant_jingles": f"{stats.get('jingle_pads', 0)} Pads · "
                               f"{stats.get('jingle_pallets', 0)} Pallets",
            "spots":           f"{stats.get('campaigns_active', 0)} Active Spots",
            "jingles":         f"{stats.get('jingles_total', 0)} Jingles Available",
            "sweepers":        f"{stats.get('sweepers_total', 0)} Sweepers Available",
            "stitcher":        stitcher_line,
            "scheduling":      f"{stats.get('clocks_total', 0)} Clocks · "
                               f"{stats.get('auto_schedule_set', 0)} Hour Slots",
        }

        # Find each card's stat QLabel (second text label inside the frame,
        # geom 109,55). Skip cards whose key isn't in live_stats (defensive
        # for new card additions).
        for key, card in self._cards.items():
            if key not in live_stats:
                continue
            for child in card.findChildren(QLabel):
                g = child.geometry()
                if g.x() == 109 and g.y() == 55:
                    child.setText(live_stats[key])
                    break
