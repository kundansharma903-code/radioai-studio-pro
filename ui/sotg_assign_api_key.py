"""
RadioAI Studio Pro — Spot on the Go · Assign API Key (Figma 503:3)

Step 4 of Spot on the Go. Operator wires a Gemini or OpenAI API key
to the Transcription Engine. Every fired SOTG drop then gets a 4-line
English summary persisted on the assignment row, which surfaces:
  • Live in the Activity Log on this screen (show-grouped, 24h)
  • In the Generate Report screen rows (italic sub-block under link)
  • In the daily PDF (italic 4-line block under each link)

Public signals:
  screen_requested(str) — "control_panel" / "ai_magic" / "spot_on_the_go"
  studio_clicked()      — header Open Studio button
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from PyQt6.QtCore import Qt, QRectF, QTimer, pyqtSignal
from core import dialogs
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QLinearGradient,
    QFont, QCursor,
)
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QHBoxLayout, QVBoxLayout,
    QLineEdit, QComboBox, QScrollArea, QMessageBox,
)

from core.settings import Settings
from core.database import Database
from core.sotg_transcription_engine import (
    SOTGTranscriptionEngine,
    KEY_ACTIVE_PROVIDER, KEY_ENGINE_ENABLED,
    KEY_GEMINI_API_KEY, KEY_GEMINI_MODEL,
    KEY_OPENAI_API_KEY, KEY_OPENAI_MODEL,
)
from core.transcription import build_adapter
from core.transcription.gemini_adapter import DEFAULT_MODELS as GEMINI_MODELS
from core.transcription.openai_adapter import DEFAULT_MODELS as OPENAI_MODELS
from ui.widgets._tokens import (
    inter, mono, rgba,
    BG_BASE, BG_PANEL,
    TEXT_PRI, TEXT_SEC, TEXT_MUTED, TEXT_DIM,
    CYAN, CYAN_LIGHT, PURPLE, PURPLE_LIGHT,
    GREEN, GREEN_LIGHT, AMBER, AMBER_LIGHT, RED,
)
from ui.spot_on_the_go_shell import (
    _HeaderLogo, _HeaderOpenStudio, _BreadcrumbLink, _BreadcrumbPill,
    _StatusPill, _PremiumBackdrop,
)

log = logging.getLogger("SOTGAssignAPIKey")

WINDOW_W = 1440
WINDOW_H = 900
HEADER_H = 72
STATUS_H = 36

RED_LIGHT = "#fb7185"


# ════════════════════════════════════════════════════════════════════════════
# Small widgets
# ════════════════════════════════════════════════════════════════════════════


class _HeroStatPill(QFrame):
    """Small hero-side stat block (DONE TODAY / QUEUE / ERRORS). Same
    visual family as Generate Report's stat pills but compact (132×64)."""

    def __init__(self, label: str, accent: str, parent=None):
        super().__init__(parent)
        self.setFixedSize(132, 64)
        self.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border: 1px solid {rgba(accent, 0.40)}; "
            f"border-radius: 10px; }}"
        )
        # Left accent bar
        bar = QFrame(self)
        bar.setGeometry(0, 0, 3, 64)
        bar.setStyleSheet(
            f"background: {accent}; border-top-left-radius: 2px; "
            f"border-bottom-left-radius: 2px; border: none;")

        lbl = QLabel(label, self)
        lbl.setGeometry(14, 10, 110, 14)
        lbl.setFont(inter(9, QFont.Weight.Bold, letter_spacing=1.2))
        lbl.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent; border: none;")

        self._value_lbl = QLabel("0", self)
        self._value_lbl.setGeometry(14, 26, 110, 32)
        self._value_lbl.setFont(mono(22, bold=True))
        self._value_lbl.setStyleSheet(
            f"color: {accent}; background: transparent; border: none;")

    def set_value(self, n: int) -> None:
        self._value_lbl.setText(str(int(n)))


class _ProviderCard(QFrame):
    """One provider row card (Gemini / OpenAI). Click → emits
    activate_clicked(provider_key). Visual state: active gets the
    amber border + filled CONFIGURE button; inactive gets a muted
    look + Switch to <Provider> button."""

    activate_clicked = pyqtSignal(str)
    configure_clicked = pyqtSignal(str)

    def __init__(self, provider_key: str, name: str, glyph: str,
                 tagline: str, hint: str,
                 accent: str, accent_light: str, parent=None):
        super().__init__(parent)
        self._provider_key = provider_key
        self._accent = accent
        self._accent_light = accent_light
        self._active = False
        self.setFixedSize(640, 116)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        # Glyph + name
        gx = 16
        self._glyph_lbl = QLabel(glyph, self)
        self._glyph_lbl.setGeometry(gx, 12, 24, 24)
        self._glyph_lbl.setFont(inter(18, QFont.Weight.Bold))
        self._glyph_lbl.setStyleSheet(
            f"color: {accent}; background: transparent; border: none;")

        name_lbl = QLabel(name, self)
        name_lbl.setGeometry(gx + 24, 10, 200, 24)
        name_lbl.setFont(inter(16, QFont.Weight.Bold, letter_spacing=0.4))
        name_lbl.setStyleSheet(
            f"color: {TEXT_PRI}; background: transparent; border: none;")

        tagline_lbl = QLabel(tagline, self)
        tagline_lbl.setGeometry(gx + 24, 32, 460, 16)
        tagline_lbl.setFont(inter(11, QFont.Weight.Medium))
        tagline_lbl.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent; border: none;")

        # Connection status (left bottom)
        self._status_dot_lbl = QLabel("●", self)
        self._status_dot_lbl.setGeometry(gx, 62, 14, 16)
        self._status_dot_lbl.setFont(inter(10))
        self._status_dot_lbl.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; border: none;")
        self._status_text_lbl = QLabel("DISCONNECTED", self)
        self._status_text_lbl.setGeometry(gx + 14, 62, 160, 16)
        self._status_text_lbl.setFont(
            inter(10, QFont.Weight.Bold, letter_spacing=1.2))
        self._status_text_lbl.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; border: none;")

        sep_lbl = QLabel("·", self)
        sep_lbl.setGeometry(gx + 174, 62, 8, 16)
        sep_lbl.setFont(inter(12))
        sep_lbl.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; border: none;")
        hint_lbl = QLabel(hint, self)
        hint_lbl.setGeometry(gx + 186, 62, 400, 16)
        hint_lbl.setFont(inter(10, QFont.Weight.Medium))
        hint_lbl.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; border: none;")

        # ACTIVE / NOT SET UP pill (top-right)
        self._badge = QFrame(self)
        self._badge.setGeometry(540, 12, 84, 22)
        self._badge_lbl = QLabel("", self._badge)
        self._badge_lbl.setGeometry(0, 0, 84, 22)
        self._badge_lbl.setFont(
            inter(9, QFont.Weight.Bold, letter_spacing=1.2))
        self._badge_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Activate / Configure button (bottom-right)
        self._action_btn = QPushButton("", self)
        self._action_btn.setGeometry(502, 80, 122, 28)
        self._action_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._action_btn.setFont(inter(11, QFont.Weight.Bold))
        self._action_btn.clicked.connect(self._on_action)

        self.set_active(False)

    def _on_action(self):
        if self._active:
            self.configure_clicked.emit(self._provider_key)
        else:
            self.activate_clicked.emit(self._provider_key)

    def set_active(self, active: bool) -> None:
        self._active = bool(active)
        if self._active:
            self.setStyleSheet(
                f"QFrame {{ background: {BG_PANEL}; "
                f"border: 1px solid {rgba(self._accent, 0.55)}; "
                f"border-radius: 12px; }}"
            )
            self._badge.setStyleSheet(
                f"QFrame {{ background: {rgba(self._accent, 0.22)}; "
                f"border: 1px solid {rgba(self._accent, 0.55)}; "
                f"border-radius: 11px; }}")
            self._badge_lbl.setText("● ACTIVE")
            self._badge_lbl.setStyleSheet(
                f"color: {self._accent_light}; background: transparent; "
                f"border: none;")
            self._action_btn.setText("Configure  →")
            self._action_btn.setStyleSheet(
                f"QPushButton {{ background: {rgba(self._accent, 0.22)}; "
                f"color: {self._accent_light}; "
                f"border: 1px solid {rgba(self._accent, 0.50)}; "
                f"border-radius: 8px; }}"
                f"QPushButton:hover {{ background: {rgba(self._accent, 0.32)}; }}"
            )
        else:
            self.setStyleSheet(
                f"QFrame {{ background: {BG_PANEL}; "
                f"border: 1px solid {rgba('#ffffff', 0.10)}; "
                f"border-radius: 12px; }}"
            )
            self._badge.setStyleSheet(
                f"QFrame {{ background: transparent; "
                f"border: 1px solid {rgba('#ffffff', 0.15)}; "
                f"border-radius: 11px; }}")
            self._badge_lbl.setText("○ INACTIVE")
            self._badge_lbl.setStyleSheet(
                f"color: {TEXT_MUTED}; background: transparent; "
                f"border: none;")
            self._action_btn.setText(f"Switch to {self._provider_key.title()}  →")
            self._action_btn.setStyleSheet(
                f"QPushButton {{ background: transparent; "
                f"color: {self._accent_light}; "
                f"border: 1px solid {rgba(self._accent, 0.40)}; "
                f"border-radius: 8px; }}"
                f"QPushButton:hover {{ background: {rgba(self._accent, 0.10)}; }}"
            )
        self.update()

    def set_connected(self, connected: bool, detail: str = "") -> None:
        if connected:
            self._status_dot_lbl.setStyleSheet(
                f"color: {GREEN}; background: transparent; border: none;")
            self._status_text_lbl.setText("CONNECTED")
            self._status_text_lbl.setStyleSheet(
                f"color: {GREEN}; background: transparent; "
                f"border: none;")
        else:
            self._status_dot_lbl.setStyleSheet(
                f"color: {TEXT_MUTED}; background: transparent; "
                f"border: none;")
            self._status_text_lbl.setText("DISCONNECTED")
            self._status_text_lbl.setStyleSheet(
                f"color: {TEXT_MUTED}; background: transparent; "
                f"border: none;")

    def paintEvent(self, e):
        super().paintEvent(e)
        # Left accent stripe always renders in the provider's color
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(QRectF(0, 0, 4, self.height()), QColor(self._accent))
        p.end()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and not self._active:
            self.activate_clicked.emit(self._provider_key)
        super().mousePressEvent(e)


# ════════════════════════════════════════════════════════════════════════════
# Activity log row widgets
# ════════════════════════════════════════════════════════════════════════════


def _safe_color(value: Optional[str], fallback: str = CYAN) -> str:
    if not value:
        return fallback
    v = str(value).strip()
    if v.startswith("#") and len(v) in (4, 7):
        try:
            int(v[1:], 16)
            return v
        except ValueError:
            return fallback
    return fallback


class _ShowGroupBanner(QFrame):
    """Coloured show banner inside the activity log scroll area.
    Same visual language as the Generate Report PDF's show banners."""

    HEIGHT = 40

    def __init__(self, show_name: str, rj_name: str,
                 link_count: int, summary_counts: dict,
                 color: str, parent=None):
        super().__init__(parent)
        self.setFixedHeight(self.HEIGHT)
        c = _safe_color(color)
        self._color = c
        self.setStyleSheet(
            f"QFrame {{ background: {rgba(c, 0.10)}; "
            f"border: 1px solid {rgba(c, 0.45)}; "
            f"border-radius: 8px; }}"
        )
        name_lbl = QLabel(show_name, self)
        name_lbl.setGeometry(16, 4, 320, 16)
        name_lbl.setFont(inter(12, QFont.Weight.Bold))
        name_lbl.setStyleSheet(
            f"color: {TEXT_PRI}; background: transparent; border: none;")

        sub_lbl = QLabel(
            f"RJ: {rj_name or '—'}  ·  {link_count} link"
            f"{'s' if link_count != 1 else ''}",
            self)
        sub_lbl.setGeometry(16, 20, 320, 16)
        sub_lbl.setFont(inter(10, QFont.Weight.Medium))
        sub_lbl.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent; border: none;")

        done = int(summary_counts.get("done", 0))
        proc = int(summary_counts.get("processing", 0))
        miss = int(summary_counts.get("missed", 0))
        fail = int(summary_counts.get("failed", 0))
        pending = int(summary_counts.get("pending", 0))
        right_lbl = QLabel(
            f"{done} done   ·   {miss} missed   ·   "
            f"{(proc + pending)} pending"
            + (f"   ·   {fail} failed" if fail else ""),
            self)
        right_lbl.setGeometry(self.width() - 360, 12, 344, 16)
        right_lbl.setFont(mono(10, bold=True))
        right_lbl.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent; border: none;")
        right_lbl.setAlignment(Qt.AlignmentFlag.AlignRight
                                | Qt.AlignmentFlag.AlignVCenter)
        # The QFrame is fixed-width by the parent layout; the right
        # label adjusts on resize via geometry. The fixed scroll area
        # width (1288) is known at build time, so we set geometry on
        # init.
        self.setFixedWidth(1288)
        right_lbl.setGeometry(900, 12, 372, 16)

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(QRectF(0, 0, 4, self.height()), QColor(self._color))
        p.end()


class _ActivityRow(QFrame):
    """One per-link row inside the activity log. Expands to 80h when
    ``ai_summary`` is populated (renders the 4-line italic sub-block);
    stays at 36h for PROCESSING / SKIPPED / FAILED states."""

    def __init__(self, row_data: dict, parent=None):
        super().__init__(parent)
        self._data = row_data
        ai_status = (row_data.get("ai_status") or "").upper()
        status = (row_data.get("status") or "").upper()
        summary = (row_data.get("ai_summary") or "").strip()
        has_summary = ai_status == "DONE" and bool(summary)
        h = 80 if has_summary else 36
        self.setFixedSize(1288, h)
        self.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border: 1px solid {rgba('#ffffff', 0.08)}; "
            f"border-radius: 8px; }}"
        )
        show_color = _safe_color(row_data.get("color"))
        self._show_color = show_color

        # # number
        num = int(row_data.get("link_order") or 0)
        num_lbl = QLabel(f"#{num:02d}", self)
        num_lbl.setGeometry(16, 8, 36, 18)
        num_lbl.setFont(mono(11, bold=True))
        num_lbl.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; border: none;")
        # Time
        time_lbl = QLabel(str(row_data.get("sharp_time") or "—:—"), self)
        time_lbl.setGeometry(48, 8, 60, 18)
        time_lbl.setFont(mono(12, bold=True))
        time_lbl.setStyleSheet(
            f"color: {TEXT_PRI}; background: transparent; border: none;")
        # Link name
        link_lbl = QLabel(str(row_data.get("link_name") or "—"), self)
        link_lbl.setGeometry(108, 8, 240, 18)
        link_lbl.setFont(inter(12, QFont.Weight.Bold))
        link_lbl.setStyleSheet(
            f"color: {TEXT_PRI}; background: transparent; border: none;")

        # Status pill — combines on-air status with ai_status
        # • status=FIRED + ai_status=DONE → ✓ DONE (green)
        # • status=FIRED + ai_status=PROCESSING → ◷ PROCESSING (amber)
        # • status=FIRED + ai_status=FAILED → ⚠ FAILED (red)
        # • status=FIRED + ai_status=SKIPPED → ✕ SKIPPED (muted)
        # • status=FIRED + ai_status=None → ◯ PENDING (cyan, queued/no-key)
        # • status=MISSED → ✕ MISSED (red)
        # • else status as-is
        pill_color = TEXT_MUTED
        pill_text = "—"
        pill_glyph = "·"
        pill_light = TEXT_MUTED
        if status == "MISSED":
            pill_color = RED; pill_light = RED_LIGHT
            pill_glyph = "✕"; pill_text = "MISSED"
        elif status == "FIRED":
            if ai_status == "DONE":
                pill_color = GREEN; pill_light = GREEN_LIGHT
                pill_glyph = "✓"; pill_text = "DONE"
            elif ai_status == "PROCESSING":
                pill_color = AMBER; pill_light = AMBER_LIGHT
                pill_glyph = "◷"; pill_text = "PROCESSING"
            elif ai_status == "FAILED":
                pill_color = RED; pill_light = RED_LIGHT
                pill_glyph = "⚠"; pill_text = "FAILED"
            elif ai_status == "SKIPPED":
                pill_color = TEXT_MUTED; pill_light = TEXT_MUTED
                pill_glyph = "✕"; pill_text = "SKIPPED"
            else:
                pill_color = CYAN; pill_light = CYAN_LIGHT
                pill_glyph = "◯"; pill_text = "PENDING"
        else:
            pill_color = TEXT_MUTED; pill_light = TEXT_MUTED
            pill_glyph = "·"
            pill_text = status or "—"

        pw = 110
        px = 360
        pill = QFrame(self)
        pill.setGeometry(px, 6, pw, 20)
        pill.setStyleSheet(
            f"QFrame {{ background: {rgba(pill_color, 0.20)}; "
            f"border: 1px solid {rgba(pill_color, 0.45)}; "
            f"border-radius: 10px; }}"
        )
        plbl = QLabel(f"{pill_glyph}  {pill_text}", pill)
        plbl.setGeometry(0, 0, pw, 20)
        plbl.setFont(inter(9, QFont.Weight.Bold, letter_spacing=0.8))
        plbl.setStyleSheet(
            f"color: {pill_light}; background: transparent; border: none;")
        plbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Right-side details (provider · timing or note)
        detail = ""
        if ai_status == "DONE":
            prov = (row_data.get("ai_provider") or "—").title()
            saved = (row_data.get("ai_summary_at") or "")[11:16]
            detail = f"{prov} · saved {saved}" if saved else prov
        elif ai_status == "PROCESSING":
            detail = "queued · processing…"
        elif ai_status == "FAILED":
            detail = "transcription failed · retry from Backfill"
        elif ai_status == "SKIPPED":
            detail = "no audio or no API key — see report"
        elif status == "MISSED":
            detail = "MISSED on air · no audio to transcribe"
        else:
            detail = "queued for next tick…"

        detail_lbl = QLabel(detail, self)
        detail_lbl.setGeometry(480, 9, 600, 16)
        detail_lbl.setFont(inter(10, italic=True))
        detail_lbl.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; border: none;")

        # 4-line AI summary sub-block (if present)
        if has_summary:
            lines = summary.splitlines()[:4]
            for i, line in enumerate(lines):
                slbl = QLabel(line, self)
                slbl.setGeometry(16, 32 + i * 12, 1264, 16)
                slbl.setFont(inter(10, italic=True))
                slbl.setStyleSheet(
                    f"color: {TEXT_SEC}; background: transparent; "
                    f"border: none;")

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(QRectF(0, 0, 3, self.height()), QColor(self._show_color))
        p.end()


# ════════════════════════════════════════════════════════════════════════════
# Public screen
# ════════════════════════════════════════════════════════════════════════════


class SOTGAssignAPIKey(QWidget):

    screen_requested = pyqtSignal(str)
    studio_clicked   = pyqtSignal()

    def __init__(self, db: Database, engine: SOTGTranscriptionEngine,
                 parent=None):
        super().__init__(parent)
        self._db = db
        self._engine = engine
        self.setFixedSize(WINDOW_W, WINDOW_H)
        self.setStyleSheet(f"QWidget {{ background: {BG_BASE}; }}")

        # State
        s = Settings()
        self._active_provider = (
            s.get(KEY_ACTIVE_PROVIDER, "gemini") or "gemini")
        # Track activity-log child widgets so refresh is leak-free
        # (incident #17 family)
        self._log_widgets: list[QWidget] = []

        self._backdrop = _PremiumBackdrop(self)
        self._backdrop.setGeometry(0, 0, WINDOW_W, WINDOW_H)

        self._build_header()
        self._build_hero()
        self._build_provider_row()
        self._build_key_card()
        self._build_activity_log()
        self._build_action_bar()
        self._build_status_bar()

        # Wire engine signals to refresh UI live
        try:
            self._engine.transcription_finished.connect(
                self._on_engine_finished)
            self._engine.queue_changed.connect(self._on_queue_changed)
        except Exception:
            pass

        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._tick_clock)
        self._clock_timer.start()
        self._tick_clock()

        self._refresh_provider_cards()
        self._refresh_key_card()
        self._refresh_activity_log()
        self._refresh_action_bar()
        log.info("SOTGAssignAPIKey ready (Figma 503:3)")

    # ── Header ────────────────────────────────────────────────────────

    def _build_header(self) -> None:
        h = QFrame(self)
        h.setGeometry(0, 0, WINDOW_W, HEADER_H)
        h.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border-bottom: 1px solid {rgba('#ffffff', 0.06)}; }}"
        )

        _HeaderLogo(h).move(14, 16)
        QLabel("RadioAI", h).setGeometry(64, 14, 120, 18)
        l = h.findChildren(QLabel)[-1]
        l.setFont(inter(15, QFont.Weight.Bold))
        l.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        l2 = QLabel("STUDIO PRO", h)
        l2.setGeometry(64, 34, 120, 12)
        l2.setFont(inter(8, QFont.Weight.Bold, letter_spacing=1.2))
        l2.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

        # Breadcrumb
        cp = _BreadcrumbLink("Control Panel", h)
        cp.setGeometry(176, 22, 100, 22)
        cp.clicked.connect(
            lambda: self.screen_requested.emit("control_panel"))
        s1 = QLabel("|", h); s1.setGeometry(272, 22, 8, 22)
        s1.setFont(inter(11))
        s1.setStyleSheet(f"color: {TEXT_DIM}; background: transparent;")

        am = _BreadcrumbLink("AI Magic", h)
        am.setGeometry(284, 22, 80, 22)
        am.clicked.connect(
            lambda: self.screen_requested.emit("ai_magic"))
        s2 = QLabel("|", h); s2.setGeometry(364, 22, 8, 22)
        s2.setFont(inter(11))
        s2.setStyleSheet(f"color: {TEXT_DIM}; background: transparent;")

        sog = _BreadcrumbLink("Spot on the Go", h)
        sog.setGeometry(376, 22, 110, 22)
        sog.clicked.connect(
            lambda: self.screen_requested.emit("spot_on_the_go"))
        s3 = QLabel("|", h); s3.setGeometry(490, 22, 8, 22)
        s3.setFont(inter(11))
        s3.setStyleSheet(f"color: {TEXT_DIM}; background: transparent;")

        pill = _BreadcrumbPill("⚿ Assign API Key", h)
        pill.move(502, 20)

        title = QLabel("Assign API Key", h)
        title.setGeometry(680, 12, 240, 24)
        title.setFont(inter(20, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        sub = QLabel(
            "Wire your Gemini / OpenAI key to auto-summarise fired drops", h)
        sub.setGeometry(680, 38, 420, 14)
        sub.setFont(inter(10))
        sub.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

        # Clock
        self._clock_lbl = QLabel("", h)
        self._clock_lbl.setGeometry(1108, 14, 100, 24)
        self._clock_lbl.setFont(mono(20, bold=True))
        self._clock_lbl.setStyleSheet(
            f"color: {TEXT_PRI}; background: transparent;")
        try:
            station = Settings().station_display or "KISS FM 91.5"
        except Exception:
            station = "KISS FM 91.5"
        self._station_lbl = QLabel(station, h)
        self._station_lbl.setObjectName("hdr_station_lbl")
        self._station_lbl.setGeometry(1108, 40, 110, 14)
        self._station_lbl.setFont(inter(9, QFont.Weight.Medium))
        self._station_lbl.setStyleSheet(
            f"color: {GREEN}; background: transparent;")

        osb = _HeaderOpenStudio(h)
        osb.move(1222, 16)
        osb.clicked.connect(self.studio_clicked.emit)

    def _tick_clock(self):
        self._clock_lbl.setText(datetime.now().strftime("%I:%M %p"))

    # ── Hero ──────────────────────────────────────────────────────────

    def _build_hero(self) -> None:
        sigil = QLabel("⚿", self)
        sigil.setGeometry(60, 92, 40, 36)
        sigil.setFont(inter(28, QFont.Weight.Bold))
        sigil.setStyleSheet(
            f"color: {AMBER_LIGHT}; background: transparent; border: none;")
        title = QLabel("ASSIGN API KEY", self)
        title.setGeometry(106, 88, 700, 44)
        title.setFont(inter(28, QFont.Weight.Black, letter_spacing=-0.4))
        title.setStyleSheet(
            f"color: {TEXT_PRI}; background: transparent; border: none;")

        sub1 = QLabel(
            "Connect Gemini or OpenAI to auto-transcribe every fired "
            "SOTG drop and surface a 4-line English summary under each "
            "link in the report.", self)
        sub1.setGeometry(60, 132, 1000, 18)
        sub1.setFont(inter(13, QFont.Weight.Medium))
        sub1.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent; border: none;")

        sub2 = QLabel(
            "Keys stored locally in radioai.db.settings — never logged "
            "or transmitted anywhere else. Audio files are sent only "
            "to the active provider.", self)
        sub2.setGeometry(60, 152, 1000, 16)
        sub2.setFont(inter(11, QFont.Weight.Medium))
        sub2.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; border: none;")

        # Hero stat pills (right)
        self._pill_done   = _HeroStatPill("DONE TODAY", GREEN, parent=self)
        self._pill_queue  = _HeroStatPill("QUEUE",      CYAN,  parent=self)
        self._pill_errors = _HeroStatPill("ERRORS",     RED,   parent=self)
        gap = 10
        right_edge = WINDOW_W - 60
        pw = 132
        self._pill_errors.move(right_edge - pw, 92)
        self._pill_queue.move(right_edge - 2 * pw - gap, 92)
        self._pill_done.move(right_edge - 3 * pw - 2 * gap, 92)

    # ── Provider row ──────────────────────────────────────────────────

    def _build_provider_row(self) -> None:
        self._card_gemini = _ProviderCard(
            "gemini", "GEMINI", "✦",
            "Google · 1-call audio → summary",
            "Best for Hindi-English mix · free tier 1500/day",
            AMBER, AMBER_LIGHT, parent=self)
        self._card_gemini.move(60, 188)
        self._card_gemini.activate_clicked.connect(self._on_activate_provider)
        self._card_gemini.configure_clicked.connect(self._on_configure_provider)

        self._card_openai = _ProviderCard(
            "openai", "OPENAI", "⌨",
            "Whisper STT + GPT-4o-mini · 2-call pipeline",
            "Higher accuracy, pay-per-use · ~$0.01 per drop",
            PURPLE, PURPLE_LIGHT, parent=self)
        self._card_openai.move(60 + 640 + 24, 188)
        self._card_openai.activate_clicked.connect(self._on_activate_provider)
        self._card_openai.configure_clicked.connect(self._on_configure_provider)

    def _refresh_provider_cards(self) -> None:
        self._card_gemini.set_active(self._active_provider == "gemini")
        self._card_openai.set_active(self._active_provider == "openai")
        s = Settings()
        self._card_gemini.set_connected(
            bool((s.get(KEY_GEMINI_API_KEY, "") or "").strip()))
        self._card_openai.set_connected(
            bool((s.get(KEY_OPENAI_API_KEY, "") or "").strip()))

    # ── Key card ──────────────────────────────────────────────────────

    def _build_key_card(self) -> None:
        card = QFrame(self)
        card.setGeometry(60, 320, 1320, 172)
        card.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border: 1px solid {rgba('#ffffff', 0.10)}; "
            f"border-radius: 12px; }}"
        )
        # Left accent bar painted in paintEvent of a child widget; for
        # simplicity, draw it as a thin QFrame:
        bar = QFrame(self)
        bar.setGeometry(60, 320, 4, 172)
        bar.setStyleSheet(
            f"QFrame {{ background: {AMBER}; "
            f"border-top-left-radius: 2px; "
            f"border-bottom-left-radius: 2px; "
            f"border: none; }}")

        # Provider title
        self._key_title_lbl = QLabel("", self)
        self._key_title_lbl.setGeometry(80, 332, 600, 16)
        self._key_title_lbl.setFont(
            inter(10, QFont.Weight.Bold, letter_spacing=1.4))
        self._key_title_lbl.setStyleSheet(
            f"color: {AMBER_LIGHT}; background: transparent; "
            f"border: none;")

        self._key_hint_lbl = QLabel("", self)
        self._key_hint_lbl.setGeometry(80, 352, 1000, 16)
        self._key_hint_lbl.setFont(inter(11, QFont.Weight.Medium))
        self._key_hint_lbl.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; "
            f"border: none;")

        # Labels row
        api_lbl = QLabel("API KEY", self)
        api_lbl.setGeometry(80, 384, 80, 14)
        api_lbl.setFont(inter(9, QFont.Weight.Bold, letter_spacing=1.4))
        api_lbl.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent; border: none;")
        self._reveal_btn = QPushButton("👁  Reveal", self)
        self._reveal_btn.setGeometry(168, 380, 90, 22)
        self._reveal_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._reveal_btn.setFont(inter(10, QFont.Weight.Medium))
        self._reveal_btn.setFlat(True)
        self._reveal_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {CYAN}; "
            f"border: none; }}"
            f"QPushButton:hover {{ color: {CYAN_LIGHT}; }}"
        )
        self._reveal_btn.clicked.connect(self._toggle_reveal)
        self._reveal_state = False

        model_lbl = QLabel("MODEL", self)
        model_lbl.setGeometry(776, 384, 80, 14)
        model_lbl.setFont(inter(9, QFont.Weight.Bold, letter_spacing=1.4))
        model_lbl.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent; border: none;")

        # API key input
        self._key_input = QLineEdit(self)
        self._key_input.setGeometry(80, 402, 680, 36)
        self._key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._key_input.setFont(mono(11))
        self._key_input.setStyleSheet(
            f"QLineEdit {{ background: {BG_BASE}; color: {TEXT_PRI}; "
            f"border: 1px solid {rgba('#ffffff', 0.10)}; "
            f"border-radius: 8px; padding: 0 14px; }}"
            f"QLineEdit:focus {{ border-color: {rgba(AMBER, 0.55)}; }}"
        )

        # Model dropdown
        self._model_combo = QComboBox(self)
        self._model_combo.setGeometry(776, 402, 280, 36)
        self._model_combo.setFont(mono(12, bold=True))
        self._model_combo.setStyleSheet(
            f"QComboBox {{ background: {BG_BASE}; color: {TEXT_PRI}; "
            f"border: 1px solid {rgba('#ffffff', 0.10)}; "
            f"border-radius: 8px; padding: 0 14px; }}"
            f"QComboBox::drop-down {{ width: 24px; border: none; }}"
            f"QComboBox QAbstractItemView {{ background: {BG_PANEL}; "
            f"color: {TEXT_PRI}; selection-background-color: "
            f"{rgba(AMBER, 0.30)}; }}"
        )

        # Test + Save buttons
        self._test_btn = QPushButton("↻   Test Connection", self)
        self._test_btn.setGeometry(1072, 402, 144, 36)
        self._test_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._test_btn.setFont(inter(11, QFont.Weight.Bold))
        self._test_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {CYAN}; "
            f"border: 1px solid {rgba(CYAN, 0.45)}; border-radius: 8px; }}"
            f"QPushButton:hover {{ background: {rgba(CYAN, 0.10)}; }}"
        )
        self._test_btn.clicked.connect(self._on_test_connection)

        self._save_btn = QPushButton("Save & Activate", self)
        self._save_btn.setGeometry(1232, 402, 132, 36)
        self._save_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._save_btn.setFont(inter(11, QFont.Weight.Bold))
        self._save_btn.setStyleSheet(
            f"QPushButton {{ background: {rgba(AMBER, 0.22)}; "
            f"color: {AMBER_LIGHT}; "
            f"border: 1px solid {rgba(AMBER, 0.55)}; border-radius: 8px; }}"
            f"QPushButton:hover {{ background: {rgba(AMBER, 0.32)}; }}"
        )
        self._save_btn.clicked.connect(self._on_save_clicked)

        # Privacy strip
        self._privacy_lbl = QLabel(
            "🔒  Audio files for fired drops are sent to the active "
            "provider. Keys never logged. Stored in radioai.db.settings "
            "— local only.",
            self)
        self._privacy_lbl.setGeometry(80, 458, 1240, 16)
        self._privacy_lbl.setFont(inter(10, italic=True))
        self._privacy_lbl.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; "
            f"border: none;")

    def _refresh_key_card(self) -> None:
        s = Settings()
        if self._active_provider == "openai":
            self._key_title_lbl.setText("OPENAI CONFIGURATION")
            self._key_hint_lbl.setText(
                "Get a key from platform.openai.com/api-keys "
                "(pay-as-you-go, ~$0.01 per 30s drop).")
            self._key_input.setText(s.get(KEY_OPENAI_API_KEY, "") or "")
            self._model_combo.clear()
            self._model_combo.addItems(list(OPENAI_MODELS))
            cur = s.get(KEY_OPENAI_MODEL, "gpt-4o-mini") or "gpt-4o-mini"
        else:
            self._key_title_lbl.setText("GEMINI CONFIGURATION")
            self._key_hint_lbl.setText(
                "Get a key from aistudio.google.com → Get API key (free).")
            self._key_input.setText(s.get(KEY_GEMINI_API_KEY, "") or "")
            self._model_combo.clear()
            self._model_combo.addItems(list(GEMINI_MODELS))
            cur = s.get(KEY_GEMINI_MODEL, "gemini-2.5-flash") or "gemini-2.5-flash"
        idx = self._model_combo.findText(cur)
        if idx >= 0:
            self._model_combo.setCurrentIndex(idx)
        elif cur:
            self._model_combo.addItem(cur)
            self._model_combo.setCurrentIndex(self._model_combo.count() - 1)

    def _toggle_reveal(self) -> None:
        self._reveal_state = not self._reveal_state
        if self._reveal_state:
            self._key_input.setEchoMode(QLineEdit.EchoMode.Normal)
            self._reveal_btn.setText("🙈  Hide")
        else:
            self._key_input.setEchoMode(QLineEdit.EchoMode.Password)
            self._reveal_btn.setText("👁  Reveal")

    # ── Activity log ──────────────────────────────────────────────────

    def _build_activity_log(self) -> None:
        # Section caption (left) + meta hint (right)
        cap = QLabel("LIVE PREVIEW · TODAY'S TRANSCRIPTIONS", self)
        cap.setGeometry(60, 504, 360, 14)
        cap.setFont(inter(10, QFont.Weight.Bold, letter_spacing=1.4))
        cap.setStyleSheet(
            f"color: {AMBER_LIGHT}; background: transparent; "
            f"border: none;")
        meta = QLabel("·  Show-grouped, same order as Generate Report PDF",
                       self)
        meta.setGeometry(420, 504, 540, 14)
        meta.setFont(inter(10, QFont.Weight.Medium))
        meta.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; "
            f"border: none;")

        self._missing_lbl = QLabel("", self)
        self._missing_lbl.setGeometry(1080, 504, 300, 14)
        self._missing_lbl.setFont(inter(10, QFont.Weight.Medium))
        self._missing_lbl.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent; "
            f"border: none;")
        self._missing_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)

        # Scroll area
        scroll = QScrollArea(self)
        scroll.setGeometry(60, 524, 1320, 252)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            f"QScrollArea {{ background: {BG_PANEL}; "
            f"border: 1px solid {rgba('#ffffff', 0.08)}; "
            f"border-radius: 12px; }}"
            f"QScrollBar:vertical {{ background: {BG_PANEL}; "
            f"width: 10px; border-radius: 5px; }}"
            f"QScrollBar::handle:vertical {{ background: "
            f"{rgba('#ffffff', 0.12)}; border-radius: 5px; "
            f"min-height: 30px; }}"
            f"QScrollBar::handle:vertical:hover {{ background: "
            f"{rgba(AMBER, 0.40)}; }}"
            f"QScrollBar::add-line:vertical, "
            f"QScrollBar::sub-line:vertical {{ height: 0; }}"
        )
        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        self._log_layout = QVBoxLayout(inner)
        self._log_layout.setContentsMargins(16, 16, 16, 16)
        self._log_layout.setSpacing(8)
        self._log_layout.addStretch()
        scroll.setWidget(inner)
        self._log_inner = inner

    def _refresh_activity_log(self) -> None:
        # Clear previous widgets
        for w in self._log_widgets:
            w.setParent(None)
            w.deleteLater()
        self._log_widgets.clear()
        while self._log_layout.count():
            item = self._log_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

        from datetime import date as _date
        today = _date.today().isoformat()
        rows: list[dict] = []
        try:
            rows = self._db.get_sotg_assignments_for_date(today)
        except Exception as exc:
            log.warning(f"get_sotg_assignments_for_date failed: {exc}")
            rows = []

        # Show-group + sort like the PDF generator
        groups: dict[int, dict] = {}
        for r in rows:
            sid = int(r.get("show_id") or 0)
            g = groups.setdefault(sid, {
                "show_id": sid,
                "show_name": r.get("show_name") or "(untitled)",
                "rj_name": r.get("rj_name") or "",
                "color": r.get("color") or CYAN,
                "rows": [],
                "earliest": "99:99",
                "counts": {"done": 0, "processing": 0, "missed": 0,
                            "failed": 0, "pending": 0},
            })
            g["rows"].append(r)
            t = str(r.get("sharp_time") or "")
            if t and t < g["earliest"]:
                g["earliest"] = t
            status = (r.get("status") or "").upper()
            ai_status = (r.get("ai_status") or "").upper()
            if status == "MISSED":
                g["counts"]["missed"] += 1
            elif status == "FIRED" and ai_status == "DONE":
                g["counts"]["done"] += 1
            elif status == "FIRED" and ai_status == "PROCESSING":
                g["counts"]["processing"] += 1
            elif status == "FIRED" and ai_status == "FAILED":
                g["counts"]["failed"] += 1
            else:
                g["counts"]["pending"] += 1

        # Sort within each group by link_order ASC
        for g in groups.values():
            g["rows"].sort(key=lambda x: (
                int(x.get("link_order") or 9999),
                str(x.get("sharp_time") or ""),
            ))
        group_list = sorted(groups.values(), key=lambda g: g["earliest"])

        if not group_list:
            empty = QFrame(self._log_inner)
            empty.setFixedSize(1288, 120)
            empty.setStyleSheet(
                f"QFrame {{ background: transparent; "
                f"border: 1px dashed {rgba('#ffffff', 0.10)}; "
                f"border-radius: 12px; }}")
            v = QVBoxLayout(empty)
            v.setContentsMargins(0, 32, 0, 32); v.setSpacing(6)
            t = QLabel("No SOTG drops yet today", empty)
            t.setFont(inter(14, QFont.Weight.Bold))
            t.setStyleSheet(
                f"color: {TEXT_SEC}; background: transparent; "
                f"border: none;")
            t.setAlignment(Qt.AlignmentFlag.AlignCenter)
            s_lbl = QLabel(
                "Drops appear here as Studio fires them on air. Yesterday's "
                "report stays available from the Generate Report screen.",
                empty)
            s_lbl.setFont(inter(11, QFont.Weight.Medium))
            s_lbl.setStyleSheet(
                f"color: {TEXT_MUTED}; background: transparent; "
                f"border: none;")
            s_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            v.addWidget(t); v.addWidget(s_lbl)
            self._log_layout.addWidget(empty)
            empty.show()
            self._log_widgets.append(empty)
        else:
            for g in group_list:
                banner = _ShowGroupBanner(
                    g["show_name"], g["rj_name"], len(g["rows"]),
                    g["counts"], g["color"], parent=self._log_inner)
                self._log_layout.addWidget(banner)
                banner.show()
                self._log_widgets.append(banner)
                for r in g["rows"]:
                    row = _ActivityRow(r, parent=self._log_inner)
                    self._log_layout.addWidget(row)
                    row.show()
                    self._log_widgets.append(row)
        self._log_layout.addStretch()

        # Missing-summary hint (right-side text above the scroll area)
        try:
            pending = self._db.get_pending_transcription_assignments(
                limit=200)
            n = len(pending)
            if n > 0:
                self._missing_lbl.setText(
                    f"{n} past drop{'s' if n != 1 else ''} missing summaries")
            else:
                self._missing_lbl.setText(
                    "Up to date — every fired drop has a summary")
        except Exception:
            self._missing_lbl.setText("")

        # Hero pill counts
        try:
            counts = self._db.get_sotg_summary_counts_today()
            self._pill_done.set_value(counts.get("done", 0))
            self._pill_errors.set_value(counts.get("failed", 0))
        except Exception:
            pass
        self._pill_queue.set_value(self._engine.queue_depth())

    # ── Action bar ────────────────────────────────────────────────────

    def _build_action_bar(self) -> None:
        bar = QFrame(self)
        bar.setGeometry(60, 796, 1320, 48)
        bar.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border: 1px solid {rgba('#ffffff', 0.08)}; "
            f"border-radius: 12px; }}"
        )
        # Engine dot + status
        dot = QLabel("●", bar)
        dot.setGeometry(20, 14, 14, 20)
        dot.setFont(inter(12))
        self._engine_dot_lbl = dot

        self._engine_status_lbl = QLabel("", self)
        self._engine_status_lbl.setGeometry(96, 808, 900, 24)
        self._engine_status_lbl.setFont(inter(11, QFont.Weight.Medium))
        self._engine_status_lbl.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent; "
            f"border: none;")

        # Backfill button (right)
        self._backfill_btn = QPushButton(
            "↺   Backfill Missing (50 max)", self)
        self._backfill_btn.setGeometry(1132, 802, 230, 32)
        self._backfill_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._backfill_btn.setFont(inter(11, QFont.Weight.Bold))
        self._backfill_btn.setStyleSheet(
            f"QPushButton {{ background: {rgba(PURPLE, 0.22)}; "
            f"color: {PURPLE_LIGHT}; "
            f"border: 1px solid {rgba(PURPLE, 0.55)}; "
            f"border-radius: 8px; }}"
            f"QPushButton:hover {{ background: {rgba(PURPLE, 0.32)}; }}"
        )
        self._backfill_btn.clicked.connect(self._on_backfill)

    def _refresh_action_bar(self) -> None:
        enabled = self._engine.is_enabled()
        if enabled:
            self._engine_dot_lbl.setStyleSheet(
                f"color: {GREEN}; background: transparent; border: none;")
        else:
            self._engine_dot_lbl.setStyleSheet(
                f"color: {TEXT_MUTED}; background: transparent; "
                f"border: none;")
        from datetime import date as _date
        today = _date.today().isoformat()
        try:
            counts = self._db.get_sotg_summary_counts_today()
        except Exception:
            counts = {"done": 0, "failed": 0, "pending": 0}
        prov = self._active_provider.title()
        on = "ON" if enabled else "OFF"
        self._engine_status_lbl.setText(
            f"  Engine: {on}  ·  Provider: {prov}  ·  "
            f"{self._engine.queue_depth()} in queue  ·  "
            f"{counts.get('done', 0)} done  ·  "
            f"{counts.get('failed', 0)} failed")

    # ── Status bar ────────────────────────────────────────────────────

    def _build_status_bar(self) -> None:
        sb = QFrame(self)
        sb.setGeometry(0, WINDOW_H - STATUS_H, WINDOW_W, STATUS_H)
        sb.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border-top: 1px solid {rgba('#ffffff', 0.06)}; }}"
        )
        x = 12
        for txt, col in (("AUTO MODE",        PURPLE),
                          ("⚿ ASSIGN API KEY", AMBER_LIGHT),
                          ("Engine ON",        GREEN)):
            p = _StatusPill(txt, col, sb)
            p.move(x, (STATUS_H - p.height()) // 2)
            x += p.width() + 8

        ver = QLabel("v2.0.0", sb)
        ver.setGeometry(WINDOW_W - 80, 8, 60, 20)
        ver.setFont(mono(10))
        ver.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; "
            f"border: none;")
        ver.setAlignment(Qt.AlignmentFlag.AlignRight
                          | Qt.AlignmentFlag.AlignVCenter)

    # ── Handlers ──────────────────────────────────────────────────────

    def _on_activate_provider(self, provider_key: str) -> None:
        """Switch active provider — saves the choice + reloads engine."""
        self._active_provider = provider_key
        Settings().set(KEY_ACTIVE_PROVIDER, provider_key)
        try:
            self._engine.reload_settings()
        except Exception as exc:
            log.warning(f"engine reload failed: {exc}")
        self._refresh_provider_cards()
        self._refresh_key_card()
        self._refresh_action_bar()

    def _on_configure_provider(self, provider_key: str) -> None:
        """Re-show the key card focused on the API key input."""
        self._on_activate_provider(provider_key)
        self._key_input.setFocus()

    def _on_test_connection(self) -> None:
        key = self._key_input.text().strip()
        if not key:
            dialogs.info(
                self, "Test Connection",
                "Paste an API key first, then click Test Connection.")
            return
        model = self._model_combo.currentText().strip()
        try:
            adapter = build_adapter(self._active_provider, key, model)
            res = adapter.test_connection()
        except Exception as exc:
            dialogs.warning(
                self, "Test Connection",
                f"Couldn't reach {self._active_provider.title()}: {exc}")
            return
        if res.ok:
            dialogs.info(
                self, "Test Connection",
                f"{self._active_provider.title()} reachable ✓\n\n"
                f"{res.detail}\n\n"
                "Hit Save & Activate to wire this key to the engine.")
        else:
            dialogs.warning(
                self, "Test Connection",
                f"{self._active_provider.title()} test failed:\n\n"
                f"{res.detail}\n\n"
                "Double-check the key, or try the other provider.")

    def _on_save_clicked(self) -> None:
        key = self._key_input.text().strip()
        model = self._model_combo.currentText().strip()
        if not key:
            dialogs.info(
                self, "Save & Activate",
                "API key cannot be empty.\n\n"
                "Get a key first:\n"
                "  • Gemini → aistudio.google.com\n"
                "  • OpenAI → platform.openai.com/api-keys")
            return
        s = Settings()
        if self._active_provider == "openai":
            s.set(KEY_OPENAI_API_KEY, key)
            s.set(KEY_OPENAI_MODEL, model or "gpt-4o-mini")
        else:
            s.set(KEY_GEMINI_API_KEY, key)
            s.set(KEY_GEMINI_MODEL, model or "gemini-2.5-flash")
        s.set(KEY_ACTIVE_PROVIDER, self._active_provider)
        s.set(KEY_ENGINE_ENABLED, "1")

        try:
            self._engine.reload_settings()
        except Exception as exc:
            log.warning(f"engine reload failed after save: {exc}")

        self._refresh_provider_cards()
        self._refresh_action_bar()
        dialogs.info(
            self, "Save & Activate",
            f"{self._active_provider.title()} key saved.\n\n"
            "Engine is live — the next fired SOTG drop will pick it up "
            "automatically. To process past drops, click Backfill "
            "Missing on the bottom-right.")

    def _on_backfill(self) -> None:
        if not self._engine.is_enabled():
            dialogs.info(
                self, "Backfill",
                "Engine is off or no API key is set. Save a key first, "
                "then click Backfill again.")
            return
        n = self._engine.enqueue_backfill(limit=50)
        if n == 0:
            dialogs.info(
                self, "Backfill",
                "Nothing to backfill — every FIRED drop already has a "
                "summary or is queued.")
        else:
            dialogs.info(
                self, "Backfill",
                f"Queued {n} drop{'s' if n != 1 else ''} for "
                "transcription. Progress shows in the activity log "
                "below as each finishes.")
        self._refresh_action_bar()

    # ── Engine signal hooks ───────────────────────────────────────────

    def _on_engine_finished(self, aid: int, status: str) -> None:
        # Refresh both the activity log + the hero pills on every
        # completion — cheap enough since the slice is small (≤24h)
        self._refresh_activity_log()
        self._refresh_action_bar()

    def _on_queue_changed(self, depth: int) -> None:
        self._pill_queue.set_value(depth)
        self._refresh_action_bar()

    # ── External hooks ────────────────────────────────────────────────

    def refresh(self) -> None:
        self._refresh_provider_cards()
        self._refresh_key_card()
        self._refresh_activity_log()
        self._refresh_action_bar()

    def showEvent(self, e):
        super().showEvent(e)
        self._refresh_activity_log()
        self._refresh_action_bar()
