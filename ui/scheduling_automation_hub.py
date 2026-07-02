"""
RadioAI Studio Pro — AI Magic · Scheduling Automation Hub (Figma 511:3)

Step 2 of AI Magic (companion to Spot on the Go). Operator's central
control panel for the Time-Slot Freshness song-rotation engine.

This screen does THREE things:
  1. Show the engine's live state — ON / WARMING / ERROR + last-tick
     timing — with Refresh + Stop buttons for manual control.
  2. Manage Sister Category Groups — Categories from Songs Library
     can be grouped (2-5 per group) so the rotation AI can pool their
     songs for variety. Categories not in a group rotate normally.
  3. Surface today's AI actions — songs rested, sister promotions,
     clocks balanced — plus a CTA into the Daily Plan Review screen
     for the approve/discard gate.

Phase B (mock UI): all data is hardcoded sample data so the operator
can validate UX flow before the engine is wired (Phase D). Button
clicks emit signals; host handler maps to toasts in Phase B and to
real DB writes in Phase E.

Public signals:
  screen_requested(str) — "control_panel" / "ai_magic" /
                          "scheduling_automation" / "review_daily_plan"
  studio_clicked()      — header Open Studio button
  refresh_engine_clicked() — emitted only when no engine handle was
                          passed (headless/test); with a live engine
                          the hub gates on is_enabled() and queues the
                          tick onto the engine's worker thread itself
  stop_engine_clicked()
  create_group_clicked()
  edit_group_clicked(int)
  ungroup_clicked(int)
  review_plan_clicked()
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from PyQt6.QtCore import Qt, QRectF, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QLinearGradient, QRadialGradient,
    QFont, QCursor,
)
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QHBoxLayout, QVBoxLayout,
    QMessageBox,
)

from core import dialogs
from core.settings import Settings
from ui.widgets._tokens import (
    inter, mono, rgba,
    BG_BASE, BG_PANEL,
    TEXT_PRI, TEXT_SEC, TEXT_MUTED, TEXT_DIM,
    CYAN, CYAN_LIGHT, PURPLE, PURPLE_LIGHT,
    GREEN, GREEN_LIGHT, AMBER, AMBER_LIGHT, RED,
    PINK,
)
from ui.spot_on_the_go_shell import (
    _HeaderLogo, _HeaderOpenStudio, _BreadcrumbLink,
    _StatusPill, _PremiumBackdrop,
)

log = logging.getLogger("SchedulingAutoHub")

WINDOW_W = 1440
WINDOW_H = 900
HEADER_H = 72
STATUS_H = 36

RED_LIGHT = "#fb7185"


# ════════════════════════════════════════════════════════════════════════════
# Local widgets — purple-accented breadcrumb pill matches AI Magic theme
# ════════════════════════════════════════════════════════════════════════════


class _PurplePill(QFrame):
    """Active breadcrumb crumb for the Scheduling Automation family.

    The shell's _BreadcrumbPill hardcodes cyan; this is the purple
    variant used by every Scheduling Automation sub-screen so the
    family stays visually distinct from Spot on the Go (cyan)."""

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self.setFixedSize(220, 32)
        self.setStyleSheet(
            f"QFrame {{ background: {rgba(PURPLE, 0.18)}; "
            f"border: 1px solid {rgba(PURPLE, 0.45)}; "
            f"border-radius: 16px; }}"
        )
        h = QHBoxLayout(self)
        h.setContentsMargins(14, 0, 14, 0); h.setSpacing(0)
        lbl = QLabel(label, self)
        lbl.setFont(inter(11, QFont.Weight.Bold))
        lbl.setStyleSheet(
            f"color: {PURPLE_LIGHT}; background: transparent; "
            f"border: none;")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h.addWidget(lbl)


class _HeroStatPill(QFrame):
    """Right-side hero stat block. Single-row variant (label + value)."""

    def __init__(self, label: str, value: str, accent: str,
                 value_color: Optional[str] = None, parent=None):
        super().__init__(parent)
        self._accent = accent
        self.setFixedSize(132, 64)
        self.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border: 1px solid {rgba(accent, 0.40)}; "
            f"border-radius: 10px; }}"
        )
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

        self._value_lbl = QLabel(value, self)
        self._value_lbl.setGeometry(14, 26, 110, 32)
        self._value_lbl.setFont(mono(22, bold=True))
        self._value_lbl.setStyleSheet(
            f"color: {value_color or accent}; background: transparent; "
            f"border: none;")

    def set_value(self, v: str) -> None:
        self._value_lbl.setText(v)


class _CategoryChip(QFrame):
    """Inline chip showing a category name + color dot inside a sister
    group card. Fixed width so layouts stay predictable."""

    def __init__(self, name: str, color: str, parent=None):
        super().__init__(parent)
        self.setFixedSize(108, 26)
        self.setStyleSheet(
            f"QFrame {{ background: {rgba(color, 0.16)}; "
            f"border: 1px solid {rgba(color, 0.45)}; "
            f"border-radius: 13px; }}"
        )
        dot = QFrame(self)
        dot.setGeometry(12, 9, 8, 8)
        dot.setStyleSheet(
            f"background: {color}; border-radius: 4px; border: none;")
        lbl = QLabel(name, self)
        lbl.setGeometry(26, 3, 80, 20)
        lbl.setFont(inter(11, QFont.Weight.Bold))
        lbl.setStyleSheet(
            f"color: {color}; background: transparent; border: none;")


class _AddSlotChip(QFrame):
    """Placeholder chip indicating "+ Add (N left)" in a sister group
    card that isn't full at 5 categories yet."""

    def __init__(self, slots_left: int, parent=None):
        super().__init__(parent)
        self.setFixedSize(108, 26)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setStyleSheet(
            f"QFrame {{ background: transparent; "
            f"border: 1px dashed {rgba('#ffffff', 0.20)}; "
            f"border-radius: 13px; }}"
        )
        lbl = QLabel(f"+ Add ({slots_left} left)", self)
        lbl.setGeometry(0, 3, 108, 20)
        lbl.setFont(inter(10, QFont.Weight.Bold))
        lbl.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; "
            f"border: none;")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)


class _SisterGroupCard(QFrame):
    """One card showing a sister category group: 2-5 category chips +
    metadata line + Edit / Ungroup buttons."""

    edit_clicked = pyqtSignal(int)
    ungroup_clicked = pyqtSignal(int)

    def __init__(self, group_id: int, group_label: str, accent: str,
                 categories: list[dict], total_songs: int,
                 last_balanced: str, stats_summary: str, parent=None):
        super().__init__(parent)
        self._group_id = group_id
        self._accent = accent
        self.setFixedHeight(108)
        self.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border: 1px solid {rgba('#ffffff', 0.10)}; "
            f"border-radius: 12px; }}"
        )

        # Top-left label
        title = QLabel(
            f"GROUP {group_id}  ·  {len(categories)} / 5 categories", self)
        title.setGeometry(16, 12, 300, 14)
        title.setFont(inter(9, QFont.Weight.Bold, letter_spacing=1.2))
        title.setStyleSheet(
            f"color: {self._lightened(accent)}; "
            f"background: transparent; border: none;")

        # Group label (operator-friendly name OR derived)
        name = QLabel(group_label, self)
        name.setGeometry(16, 30, 480, 22)
        name.setFont(inter(14, QFont.Weight.Bold))
        name.setStyleSheet(
            f"color: {TEXT_PRI}; background: transparent; border: none;")

        # Chips row
        cx = 16
        for cat in categories:
            chip = _CategoryChip(cat["name"], cat["color"], parent=self)
            chip.move(cx, 56)
            cx += chip.width() + 8
        # Add placeholder if group not full
        slots_left = 5 - len(categories)
        if slots_left > 0:
            holder = _AddSlotChip(slots_left, parent=self)
            holder.move(cx, 56)
            holder.mousePressEvent = (
                lambda e, gid=group_id: self.edit_clicked.emit(gid))

        # Metadata bottom line
        meta = QLabel(
            f"{total_songs} songs total  ·  Last balanced "
            f"{last_balanced}  ·  {stats_summary}", self)
        meta.setGeometry(16, 88, 480, 14)
        meta.setFont(inter(10, QFont.Weight.Medium))
        meta.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; "
            f"border: none;")

        # Buttons (top-right) — Edit + Ungroup
        edit_btn = QPushButton("✎ Edit", self)
        edit_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        edit_btn.setFont(inter(10, QFont.Weight.Bold))
        edit_btn.setStyleSheet(
            f"QPushButton {{ background: {BG_ELEV()}; color: {TEXT_SEC}; "
            f"border: 1px solid {rgba('#ffffff', 0.10)}; "
            f"border-radius: 6px; padding: 0 12px; }}"
            f"QPushButton:hover {{ border-color: "
            f"{rgba(PURPLE, 0.45)}; color: {TEXT_PRI}; }}"
        )
        edit_btn.clicked.connect(
            lambda _=False, gid=group_id: self.edit_clicked.emit(gid))

        ungroup_btn = QPushButton("✕ Ungroup", self)
        ungroup_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        ungroup_btn.setFont(inter(10, QFont.Weight.Bold))
        ungroup_btn.setStyleSheet(
            f"QPushButton {{ background: {BG_ELEV()}; color: {RED_LIGHT}; "
            f"border: 1px solid {rgba(RED, 0.35)}; "
            f"border-radius: 6px; padding: 0 12px; }}"
            f"QPushButton:hover {{ background: {rgba(RED, 0.12)}; }}"
        )
        ungroup_btn.clicked.connect(
            lambda _=False, gid=group_id: self.ungroup_clicked.emit(gid))

        # Layout right side - place at fixed offsets
        # Self width is set later via setFixedWidth — derive at runtime
        self._edit_btn = edit_btn
        self._ungroup_btn = ungroup_btn

    def resizeEvent(self, e):
        super().resizeEvent(e)
        # Position the right-side buttons after width is known
        w = self.width()
        self._edit_btn.setGeometry(w - 148, 12, 64, 24)
        self._ungroup_btn.setGeometry(w - 80, 12, 68, 24)

    @staticmethod
    def _lightened(accent: str) -> str:
        # Return a "_LIGHT" variant when possible, else accent itself
        return {
            CYAN:   CYAN_LIGHT,   PURPLE: PURPLE_LIGHT,
            GREEN:  GREEN_LIGHT,  AMBER:  AMBER_LIGHT,
            PINK:   "#f472b6",
        }.get(accent, accent)

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(QRectF(0, 0, 4, self.height()), QColor(self._accent))
        p.end()


def BG_ELEV() -> str:
    """Local helper — _tokens.py doesn't export BG_ELEVATED; mirror the
    value from core/constants.py for consistency."""
    return "#131626"


# ════════════════════════════════════════════════════════════════════════════
# Public screen
# ════════════════════════════════════════════════════════════════════════════


class SchedulingAutomationHub(QWidget):
    """AI Magic · Scheduling Automation Hub (Figma 511:3).

    Phase E: live-wired. Pulls engine state from a RotationAIEngine
    handle + sister groups / today's plan / recent decisions from
    Database. The constructor's ``engine`` arg is optional — when
    None, the screen falls back to safe defaults (engine OFF, empty
    groups, zero stats) so test fixtures and headless construction
    paths still work."""

    screen_requested      = pyqtSignal(str)
    studio_clicked        = pyqtSignal()
    refresh_engine_clicked = pyqtSignal()
    stop_engine_clicked   = pyqtSignal()
    # Private — queued onto the engine's worker thread so a manual
    # Refresh never runs plan-compute on the UI thread nor races the
    # engine's own hourly QTimer tick (both serialize on the engine's
    # event loop).
    _tick_requested       = pyqtSignal()
    create_group_clicked  = pyqtSignal()
    edit_group_clicked    = pyqtSignal(int)
    ungroup_clicked       = pyqtSignal(int)
    review_plan_clicked   = pyqtSignal()

    # ── Mock data (Phase B) ─────────────────────────────────────────
    # Replaced by live engine state + DB queries in Phase E.

    # Fallback values when no engine + db handles are passed (test
    # fixtures, headless construction). Live engine + DB overrides
    # these via the _load_* methods below.
    DEFAULT_ENGINE_STATE     = "OFF"
    DEFAULT_ALGORITHM_LABEL  = (
        "Time-Slot Freshness  ·  Sister pooling enabled  ·  "
        "Primary boost ×1.2"
    )
    # Kept for backward compatibility with the Phase B mock attribute
    # names used by tests. Phase B tests pre-Phase-E asserted these.
    MOCK_ENGINE_STATE = "OFF"
    MOCK_ALGORITHM    = DEFAULT_ALGORITHM_LABEL

    # Phase E: live-load defaults — used when no engine/db is passed
    # (test fixtures only). Kept under MOCK_* names for backward-compat
    # with Phase B test assertions.
    MOCK_GROUPS = []                    # populated via _load_groups()
    MOCK_TODAY_STATS = {
        "rested":     0,
        "promoted":   0,
        "balanced":    0,
        "errors":      0,
    }
    MOCK_RECENT_DECISIONS = []          # populated via _load_recent_decisions()

    # Show all decisions if more than 5 recent — keeps the panel
    # compact while still surfacing the latest activity
    RECENT_DECISIONS_CAP = 5

    # ── Construction ────────────────────────────────────────────────

    def __init__(self, db=None, engine=None, parent=None):
        """``engine`` — optional RotationAIEngine handle. When None,
        the screen renders safe defaults (engine OFF, empty groups,
        zero stats). MainWindow always passes the live engine; test
        fixtures pass None for headless construction."""
        super().__init__(parent)
        self._db = db
        self._engine = engine
        # Live data slots — populated by _load_state() below
        self._live_groups: list = []
        self._live_today_stats: dict = dict(self.MOCK_TODAY_STATS)
        self._live_recent_decisions: list = []
        # Color palette used to assign accent + chip colors for groups
        # that didn't come from the DB with one
        self._palette = [AMBER, PURPLE, CYAN, GREEN, PINK]
        self.setFixedSize(WINDOW_W, WINDOW_H)
        self.setStyleSheet(f"QWidget {{ background: {BG_BASE}; }}")

        # Initial state load (DB query + engine state) BEFORE building
        # the visual sections so they paint with live data on first
        # render.
        self._load_state()

        self._backdrop = _PremiumBackdrop(self)
        self._backdrop.setGeometry(0, 0, WINDOW_W, WINDOW_H)

        self._build_header()
        self._build_hero()
        self._build_engine_card()
        self._build_sister_groups()
        self._build_create_group_cta()
        self._build_today_summary()
        self._build_status_bar()

        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._tick_clock)
        self._clock_timer.start()
        self._tick_clock()

        # Engine signal wiring — keeps the screen reactive without
        # the operator having to navigate away + back.
        if self._engine is not None:
            try:
                self._engine.engine_state_changed.connect(
                    self._on_engine_state_changed)
                self._engine.tick_completed.connect(
                    self._on_tick_completed)
                # Manual Refresh dispatch — engine.tick is a bound
                # method on a QObject living on the worker thread, so
                # a QueuedConnection posts the call to the engine's
                # event loop instead of running it here on the UI
                # thread.
                self._tick_requested.connect(
                    self._engine.tick,
                    Qt.ConnectionType.QueuedConnection)
            except Exception as exc:
                log.debug(f"engine signal wiring: {exc}")

        log.info("SchedulingAutomationHub ready (Figma 511:3, live mode)")

    # ── Live state loaders ─────────────────────────────────────────

    def _load_state(self) -> None:
        """Pull engine state + DB rows into ``self._live_*`` slots.
        Cheap — runs on every refresh() + once at construction."""
        self._live_groups = self._load_groups()
        self._live_today_stats = self._load_today_stats()
        self._live_recent_decisions = self._load_recent_decisions()

    def _engine_state(self) -> str:
        if self._engine is not None:
            try:
                return self._engine.state()
            except Exception:
                return self.DEFAULT_ENGINE_STATE
        return self.DEFAULT_ENGINE_STATE

    def _last_tick_seconds(self) -> int:
        """Seconds since the last successful tick — read off the
        Settings sentinel."""
        try:
            from core.settings import Settings as _S
            stamp = _S().get("rotation_ai_last_tick_at", "") or ""
        except Exception:
            return -1
        if not stamp:
            return -1
        try:
            last = datetime.fromisoformat(stamp)
            return int((datetime.now() - last).total_seconds())
        except (ValueError, TypeError):
            return -1

    def _last_error(self) -> str:
        try:
            from core.settings import Settings as _S
            return _S().get("rotation_ai_last_error", "") or ""
        except Exception:
            return ""

    def _load_groups(self) -> list:
        """Fetch sister groups from DB + decorate with palette accents."""
        if self._db is None:
            return []
        try:
            raw = self._db.get_sister_groups()
        except Exception as exc:
            log.warning(f"get_sister_groups failed: {exc}")
            return []
        groups = []
        for idx, g in enumerate(raw):
            accent = self._palette[idx % len(self._palette)]
            # Each category dict already has color from DB; if missing,
            # cycle through the palette
            cats = []
            for j, c in enumerate(g.get("categories", [])):
                cats.append({
                    "name": c.get("name", "(unnamed)"),
                    "color": (c.get("color")
                              or self._palette[j % len(self._palette)]),
                })
            groups.append({
                "id":            int(g["id"]),
                "label":         f"Group {idx + 1}",   # operator-locked: no name
                "accent":        accent,
                "categories":    cats,
                "total_songs":   int(g.get("total_songs", 0)),
                "last_balanced": "—",
                "stats_summary": "Awaiting first tick",
            })
        return groups

    def _load_today_stats(self) -> dict:
        out = dict(self.MOCK_TODAY_STATS)
        if self._db is None:
            return out
        try:
            from datetime import date as _date
            plan = self._db.get_ai_rotation_plan(_date.today().isoformat())
            if plan:
                out["rested"]   = int(plan.get("rested_count")   or 0)
                out["promoted"] = int(plan.get("promoted_count") or 0)
                out["balanced"] = int(plan.get("clocks_balanced") or 0)
                out["errors"]   = int(plan.get("error_count")    or 0)
        except Exception as exc:
            log.warning(f"get_ai_rotation_plan failed: {exc}")
        return out

    def _load_recent_decisions(self) -> list:
        """Pull the most-recent ``RECENT_DECISIONS_CAP`` decisions
        and format them as human strings for the live audit log."""
        if self._db is None:
            return []
        from datetime import date as _date
        try:
            rows = self._db.get_rotation_decisions_for_date(
                _date.today().isoformat())
        except Exception as exc:
            log.warning(f"get_rotation_decisions failed: {exc}")
            return []
        # Take the most recent N — DB returns sorted by hour, but the
        # operator wants the LATEST-decided log first
        rows = list(reversed(rows))[:self.RECENT_DECISIONS_CAP]
        out: list = []
        for r in rows:
            time_str = ""
            if r.get("created_at"):
                try:
                    dt = datetime.fromisoformat(str(r["created_at"]))
                    time_str = dt.strftime("%H:%M")
                except (ValueError, TypeError):
                    time_str = str(r["created_at"])[11:16]
            action = (r.get("action") or "").lower()
            song = r.get("song_title") or "(song)"
            src = r.get("source_category_name") or "—"
            clock = r.get("clock_name") or "?"
            hour = int(r.get("hour") or 0)
            reason = r.get("reason") or ""
            if action == "rest":
                desc = (f"Rested {song!r} in {src} "
                        f"({clock}, {hour:02d}:00) — {reason}")
            elif action == "promote":
                tgt = r.get("target_category_name") or "—"
                desc = (f"Promoted {song!r} from {src} → {tgt} "
                        f"clock ({clock}, {hour:02d}:00) — {reason}")
            else:
                desc = (f"Pick {song!r} for {clock} "
                        f"({hour:02d}:00) — {reason}")
            out.append(f"{time_str}  ·  {desc}" if time_str else desc)
        return out

    # ── Header ──────────────────────────────────────────────────────

    def _build_header(self) -> None:
        h = QFrame(self)
        h.setGeometry(0, 0, WINDOW_W, HEADER_H)
        h.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border-bottom: 1px solid {rgba('#ffffff', 0.06)}; }}"
        )

        _HeaderLogo(h).move(14, 16)
        l = QLabel("RadioAI", h)
        l.setGeometry(64, 14, 120, 18)
        l.setFont(inter(15, QFont.Weight.Bold))
        l.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        l2 = QLabel("STUDIO PRO", h)
        l2.setGeometry(64, 34, 120, 12)
        l2.setFont(inter(8, QFont.Weight.Bold, letter_spacing=1.2))
        l2.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

        # 3-crumb breadcrumb: Control Panel | AI Magic | [Scheduling Automation]
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

        pill = _PurplePill("🤖 Scheduling Automation", h)
        pill.move(376, 20)

        # Title + subtitle
        title = QLabel("Scheduling Automation", h)
        title.setGeometry(620, 12, 280, 24)
        title.setFont(inter(20, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        sub = QLabel(
            "Continuous song-rotation engine — listener experience tuned",
            h)
        sub.setGeometry(620, 38, 480, 14)
        sub.setFont(inter(10))
        sub.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

        # Clock + station
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

    def _tick_clock(self) -> None:
        self._clock_lbl.setText(datetime.now().strftime("%I:%M %p"))

    # ── Hero ────────────────────────────────────────────────────────

    def _build_hero(self) -> None:
        sigil = QLabel("🤖", self)
        sigil.setGeometry(60, 92, 40, 36)
        sigil.setFont(inter(28, QFont.Weight.Bold))
        sigil.setStyleSheet(
            f"color: {PURPLE_LIGHT}; background: transparent; "
            f"border: none;")
        title = QLabel("SCHEDULING AUTOMATION", self)
        title.setGeometry(106, 88, 800, 44)
        title.setFont(inter(28, QFont.Weight.Black, letter_spacing=-0.4))
        title.setStyleSheet(
            f"color: {TEXT_PRI}; background: transparent; border: none;")

        sub1 = QLabel(
            "AI rotates songs across sister categories every hour. "
            "Listeners hear a fresh combination at every time slot — "
            "no song repeats the same hour on consecutive days.", self)
        sub1.setGeometry(60, 132, 1100, 18)
        sub1.setFont(inter(13, QFont.Weight.Medium))
        sub1.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent; border: none;")

        sub2 = QLabel(
            "Engine runs continuously. Approve today's plan or let "
            "it auto-apply at 5 PM. Stop the engine anytime if you "
            "need full manual control.", self)
        sub2.setGeometry(60, 152, 1100, 16)
        sub2.setFont(inter(11, QFont.Weight.Medium))
        sub2.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; "
            f"border: none;")

        # Hero stat pills (right) — live state from engine + DB
        engine_state = self._engine_state()
        engine_dot = ("● ON" if engine_state == "ON"
                       else "● " + engine_state)
        engine_color = ({"ON": GREEN, "WARMING": AMBER, "ERROR": RED,
                          "OFF": TEXT_MUTED}
                         .get(engine_state, TEXT_MUTED))
        self._pill_engine = _HeroStatPill(
            "ENGINE", engine_dot, engine_color,
            value_color=engine_color, parent=self)
        self._pill_balanced = _HeroStatPill(
            "BALANCED TODAY",
            str(self._live_today_stats.get("balanced", 0)),
            PURPLE, parent=self)
        self._pill_groups = _HeroStatPill(
            "GROUPS",
            str(len(self._live_groups)),
            CYAN, parent=self)
        gap = 10
        right_edge = WINDOW_W - 60
        pw = 132
        self._pill_groups.move(right_edge - pw, 92)
        self._pill_balanced.move(right_edge - 2 * pw - gap, 92)
        self._pill_engine.move(right_edge - 3 * pw - 2 * gap, 92)

    # ── Engine card ─────────────────────────────────────────────────

    def _build_engine_card(self) -> None:
        card = QFrame(self)
        card.setGeometry(60, 188, 1320, 140)
        card.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border: 1px solid {rgba('#ffffff', 0.10)}; "
            f"border-radius: 12px; }}"
        )
        # Left accent bar
        bar = QFrame(self)
        bar.setGeometry(60, 188, 4, 140, )
        bar.setStyleSheet(
            f"background: {PURPLE}; "
            f"border-top-left-radius: 2px; "
            f"border-bottom-left-radius: 2px; border: none;")

        # Big state dot — live engine state
        engine_state = self._engine_state()
        engine_color = ({"ON": GREEN, "WARMING": AMBER, "ERROR": RED,
                          "OFF": TEXT_MUTED}
                         .get(engine_state, TEXT_MUTED))
        # Halo (decorative ring)
        halo = QFrame(self)
        halo.setGeometry(86, 210, 48, 48)
        halo.setStyleSheet(
            f"background: {rgba(engine_color, 0.15)}; "
            f"border: 1px solid {rgba(engine_color, 0.30)}; "
            f"border-radius: 24px;")
        self._engine_halo = halo
        # Dot
        dot = QFrame(self)
        dot.setGeometry(96, 220, 28, 28)
        dot.setStyleSheet(
            f"background: {engine_color}; "
            f"border-radius: 14px; border: none;")
        self._engine_dot = dot

        # State label
        state_label = ({"ON":      "ENGINE: ON",
                         "WARMING": "ENGINE: WARMING UP",
                         "ERROR":   "ENGINE: ERROR",
                         "OFF":     "ENGINE: OFF"}
                        .get(engine_state, "ENGINE: —"))
        self._engine_state_lbl = QLabel(state_label, self)
        self._engine_state_lbl.setGeometry(150, 210, 400, 28)
        self._engine_state_lbl.setFont(
            inter(22, QFont.Weight.Bold, letter_spacing=0.5))
        self._engine_state_lbl.setStyleSheet(
            f"color: {engine_color}; background: transparent; "
            f"border: none;")

        # Tick info — live from Settings sentinel
        last_tick = self._last_tick_seconds()
        if last_tick < 0:
            tick_info = (
                "Last tick: pending  ·  "
                "Continuous hourly rebalancing active")
        else:
            tick_info = (
                f"Last tick: {last_tick}s ago  ·  "
                f"Next tick: in {max(0, 3600 - last_tick)}s  ·  "
                f"Continuous hourly rebalancing active")
        self._tick_info_lbl = QLabel(tick_info, self)
        self._tick_info_lbl.setGeometry(150, 244, 800, 16)
        self._tick_info_lbl.setFont(inter(12, QFont.Weight.Medium))
        self._tick_info_lbl.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent; border: none;")

        algo_lbl = QLabel(
            f"● Algorithm: {self.DEFAULT_ALGORITHM_LABEL}", self)
        algo_lbl.setGeometry(150, 264, 800, 16)
        algo_lbl.setFont(inter(11, QFont.Weight.Medium))
        algo_lbl.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; border: none;")

        # Last error line — live from Settings sentinel
        last_err = self._last_error()
        if last_err:
            err_lbl = QLabel(f"⚠  Last error: {last_err[:80]}", self)
            err_color = AMBER
        else:
            err_lbl = QLabel("Last error: none in last 24h.", self)
            err_color = GREEN
        err_lbl.setGeometry(150, 284, 800, 14)
        err_lbl.setFont(inter(10, italic=True))
        err_lbl.setStyleSheet(
            f"color: {err_color}; background: transparent; "
            f"border: none;")
        self._engine_err_lbl = err_lbl

        # Buttons — Refresh + Stop AI Engine
        refresh = QPushButton("🔄   Refresh", self)
        refresh.setGeometry(1116, 208, 112, 36)
        refresh.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        refresh.setFont(inter(11, QFont.Weight.Bold))
        refresh.setStyleSheet(
            f"QPushButton {{ background: {BG_ELEV()}; color: {CYAN}; "
            f"border: 1px solid {rgba(CYAN, 0.45)}; border-radius: 10px; }}"
            f"QPushButton:hover {{ background: {rgba(CYAN, 0.12)}; }}"
        )
        refresh.clicked.connect(self._on_refresh_clicked)

        stop = QPushButton("⏹   Stop AI Engine", self)
        stop.setGeometry(1240, 208, 124, 36)
        stop.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        stop.setFont(inter(11, QFont.Weight.Bold))
        stop.setStyleSheet(
            f"QPushButton {{ background: {rgba(RED, 0.22)}; "
            f"color: {RED_LIGHT}; "
            f"border: 1px solid {rgba(RED, 0.55)}; border-radius: 10px; }}"
            f"QPushButton:hover {{ background: {rgba(RED, 0.32)}; }}"
        )
        stop.clicked.connect(self.stop_engine_clicked.emit)

        # AUTO-APPLY controls (operator request 2026-07-02): fully
        # autonomous daily apply at a configurable time — replaces the
        # hardcoded 5 PM. Toggle OFF = pure manual (only Daily Plan
        # Review approval applies a plan).
        from core.settings import Settings as _Settings
        from PyQt6.QtWidgets import QLineEdit
        auto_on = str(_Settings().get(
            "rotation_ai_auto_apply_enabled", "1") or "1") not in (
            "0", "false", "False", "")
        self._auto_apply_btn = QPushButton(
            f"⚡ AUTO-APPLY: {'ON' if auto_on else 'OFF'}", self)
        self._auto_apply_btn.setGeometry(1116, 250, 136, 24)
        self._auto_apply_btn.setCursor(
            QCursor(Qt.CursorShape.PointingHandCursor))
        self._auto_apply_btn.setFont(inter(10, QFont.Weight.Bold))

        def _style_auto_btn(on: bool):
            col = GREEN if on else TEXT_MUTED
            self._auto_apply_btn.setStyleSheet(
                f"QPushButton {{ background: {rgba(col, 0.15)}; "
                f"color: {col}; border: 1px solid {rgba(col, 0.45)}; "
                f"border-radius: 8px; }}")
        _style_auto_btn(auto_on)

        def _toggle_auto_apply():
            cur = str(_Settings().get(
                "rotation_ai_auto_apply_enabled", "1") or "1") not in (
                "0", "false", "False", "")
            new_state = not cur
            _Settings().set("rotation_ai_auto_apply_enabled",
                            "1" if new_state else "0")
            self._auto_apply_btn.setText(
                f"⚡ AUTO-APPLY: {'ON' if new_state else 'OFF'}")
            _style_auto_btn(new_state)
        self._auto_apply_btn.clicked.connect(_toggle_auto_apply)

        self._auto_apply_time = QLineEdit(
            str(_Settings().get(
                "rotation_ai_auto_apply_time", "17:00") or "17:00"), self)
        self._auto_apply_time.setGeometry(1260, 250, 58, 24)
        self._auto_apply_time.setFont(inter(10, QFont.Weight.Bold))
        self._auto_apply_time.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._auto_apply_time.setStyleSheet(
            f"QLineEdit {{ background: {BG_ELEV()}; color: {CYAN}; "
            f"border: 1px solid {rgba(CYAN, 0.35)}; "
            f"border-radius: 8px; }}")

        def _save_auto_time():
            raw = (self._auto_apply_time.text() or "").strip()
            try:
                hh, mm = raw.split(":", 1)
                ok = 0 <= int(hh) <= 23 and 0 <= int(mm) <= 59
            except (ValueError, AttributeError):
                ok = False
            if ok:
                _Settings().set("rotation_ai_auto_apply_time",
                                f"{int(hh):02d}:{int(mm):02d}")
                self._auto_apply_time.setText(
                    f"{int(hh):02d}:{int(mm):02d}")
            else:
                self._auto_apply_time.setText(
                    str(_Settings().get(
                        "rotation_ai_auto_apply_time", "17:00")
                        or "17:00"))
        self._auto_apply_time.editingFinished.connect(_save_auto_time)

        hint = QLabel(
            "AUTO-APPLY ON = plan applies itself daily at the set time.",
            self)
        hint.setGeometry(1140, 280, 240, 14)
        hint.setFont(inter(10, italic=True))
        hint.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; "
            f"border: none;")
        hint.setAlignment(Qt.AlignmentFlag.AlignRight)

        # CATEGORY AUTO-GRID strip (2026-07-02) — status + Rebuild Now
        # for the daypart-driven grid builder (core/auto_grid_builder).
        self._autogrid_lbl = QLabel("", self)
        self._autogrid_lbl.setGeometry(150, 306, 900, 20)
        self._autogrid_lbl.setFont(inter(10, QFont.Weight.Bold))
        self._autogrid_lbl.setStyleSheet(
            f"color: {CYAN}; background: transparent; border: none;")

        def _refresh_autogrid_lbl(extra: str = ""):
            try:
                if self._db is None:
                    self._autogrid_lbl.setText(
                        "▦ CATEGORY AUTO-GRID: (no db)")
                    return
                parts = self._db.get_all_category_dayparts()
                cats = len({p["category_id"] for p in parts})
                cells = len(self._db.get_auto_grid_cell_records())
                txt = (f"▦ CATEGORY AUTO-GRID: {cats} categor"
                       f"{'y' if cats == 1 else 'ies'} tagged · "
                       f"{cells} auto cells on the grid")
                if extra:
                    txt += f"   —   {extra}"
                self._autogrid_lbl.setText(txt)
            except Exception as exc:
                self._autogrid_lbl.setText(
                    f"▦ CATEGORY AUTO-GRID: status failed ({exc})")
        self._refresh_autogrid_lbl = _refresh_autogrid_lbl
        _refresh_autogrid_lbl()

        rebuild = QPushButton("▦   Rebuild Grid", self)
        rebuild.setGeometry(1116, 304, 248, 26)
        rebuild.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        rebuild.setFont(inter(10, QFont.Weight.Bold))
        rebuild.setStyleSheet(
            f"QPushButton {{ background: {rgba(PURPLE, 0.18)}; "
            f"color: {PURPLE_LIGHT}; border: 1px solid "
            f"{rgba(PURPLE, 0.45)}; border-radius: 8px; }}"
            f"QPushButton:hover {{ background: {rgba(PURPLE, 0.30)}; }}")

        def _on_rebuild_grid():
            if self._db is None:
                return
            try:
                from core.auto_grid_builder import build_grid
                res = build_grid(self._db)
                if res.get("error"):
                    _refresh_autogrid_lbl(f"build FAILED: {res['error']}")
                else:
                    _refresh_autogrid_lbl(
                        f"built now: +{res['placed']} placed, "
                        f"{res['skipped_manual']} manual kept, "
                        f"{res['cleared']} cleared")
            except Exception as exc:
                _refresh_autogrid_lbl(f"build crashed: {exc}")
        rebuild.clicked.connect(_on_rebuild_grid)

    # ── Sister Groups section ───────────────────────────────────────

    def _build_sister_groups(self) -> None:
        # Section caption
        cap = QLabel("SISTER CATEGORY GROUPS", self)
        cap.setGeometry(60, 346, 240, 14)
        cap.setFont(inter(10, QFont.Weight.Bold, letter_spacing=1.4))
        cap.setStyleSheet(
            f"color: {PURPLE_LIGHT}; background: transparent; "
            f"border: none;")
        sep = QLabel("·", self)
        sep.setGeometry(260, 344, 8, 18)
        sep.setFont(inter(13))
        sep.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; border: none;")
        hint = QLabel(
            "Categories in the same group pool each other's songs for "
            "variety. Up to 5 per group.", self)
        hint.setGeometry(274, 346, 800, 14)
        hint.setFont(inter(10, QFont.Weight.Medium))
        hint.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; "
            f"border: none;")

        # Right counter — live group count
        total_grouped = sum(
            len(g["categories"]) for g in self._live_groups)
        # Count of ungrouped categories (live DB query)
        ungrouped = 0
        if self._db is not None:
            try:
                row = self._db._conn().execute(
                    "SELECT COUNT(*) FROM categories WHERE id NOT IN "
                    "(SELECT category_id FROM sister_group_members)"
                ).fetchone()
                ungrouped = int(row[0] or 0)
            except Exception:
                ungrouped = 0
        right_summary = QLabel(
            f"{len(self._live_groups)} groups · {total_grouped} "
            f"categories grouped · {ungrouped} ungrouped",
            self)
        right_summary.setGeometry(1080, 346, 300, 14)
        right_summary.setFont(inter(10, QFont.Weight.Medium))
        right_summary.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent; border: none;")
        right_summary.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._sister_summary_lbl = right_summary

        # Track group card widgets so refresh() can rebuild cleanly
        # without iterating .children() (incident #17 family)
        self._group_cards: list = []

        # Render up to 2 group cards side-by-side; remaining groups
        # surface as a "+ N more groups" hint below (operator can scroll
        # or future-extend the panel)
        gw = 644
        gap = 32
        if self._live_groups:
            # ALL groups render — 2 per row, wrapping downward (the old
            # code hard-capped at the first 2 and the promised "+N more"
            # hint was never built; audit finding 2026-07-02).
            specs = self._live_groups
            x_positions = [60, 60 + gw + gap]
            widths = [gw, 1380 - (60 + gw + gap)]
            row_h = 124
            for i, g in enumerate(specs):
                col = i % 2
                row = i // 2
                card = _SisterGroupCard(
                    g["id"], g["label"], g["accent"], g["categories"],
                    g["total_songs"], g["last_balanced"],
                    g["stats_summary"], parent=self)
                card.setFixedWidth(widths[col])
                card.move(x_positions[col], 364 + row * row_h)
                card.edit_clicked.connect(self.edit_group_clicked.emit)
                card.ungroup_clicked.connect(self.ungroup_clicked.emit)
                card.show()
                self._group_cards.append(card)
        else:
            # Empty state — clean panel encouraging operator to create
            # their first group
            empty = QFrame(self)
            empty.setGeometry(60, 364, 1320, 108)
            empty.setStyleSheet(
                f"QFrame {{ background: transparent; "
                f"border: 1px dashed {rgba('#ffffff', 0.10)}; "
                f"border-radius: 12px; }}")
            t = QLabel("No sister groups yet", empty)
            t.setGeometry(0, 30, 1320, 22)
            t.setFont(inter(14, QFont.Weight.Bold))
            t.setStyleSheet(
                f"color: {TEXT_SEC}; background: transparent; "
                f"border: none;")
            t.setAlignment(Qt.AlignmentFlag.AlignCenter)
            s = QLabel(
                "Click \"+ Create\" below to group 2–5 categories so "
                "their songs pool for rotation variety.", empty)
            s.setGeometry(0, 56, 1320, 14)
            s.setFont(inter(11, QFont.Weight.Medium))
            s.setStyleSheet(
                f"color: {TEXT_MUTED}; background: transparent; "
                f"border: none;")
            s.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.show()
            self._group_cards.append(empty)

    # ── Create New Group CTA ────────────────────────────────────────

    def _build_create_group_cta(self) -> None:
        card = QFrame(self)
        card.setGeometry(60, 488, 1320, 56)
        card.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border: 1px solid {rgba(PURPLE, 0.40)}; "
            f"border-radius: 12px; }}"
        )

        title = QLabel("+   CREATE NEW SISTER GROUP", self)
        title.setGeometry(80, 500, 320, 16)
        title.setFont(inter(13, QFont.Weight.Bold, letter_spacing=1.0))
        title.setStyleSheet(
            f"color: {PURPLE_LIGHT}; background: transparent; "
            f"border: none;")

        hint = QLabel(
            "Pick 2–5 categories from your Songs Library that should "
            "pool each other's songs for rotation variety.", self)
        hint.setGeometry(80, 520, 1100, 14)
        hint.setFont(inter(11, QFont.Weight.Medium))
        hint.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; "
            f"border: none;")

        create_btn = QPushButton("+ Create", self)
        create_btn.setGeometry(1252, 500, 112, 32)
        create_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        create_btn.setFont(inter(12, QFont.Weight.Bold))
        create_btn.setStyleSheet(
            f"QPushButton {{ background: {rgba(PURPLE, 0.22)}; "
            f"color: {PURPLE_LIGHT}; "
            f"border: 1px solid {rgba(PURPLE, 0.55)}; "
            f"border-radius: 8px; }}"
            f"QPushButton:hover {{ background: {rgba(PURPLE, 0.32)}; }}"
        )
        create_btn.clicked.connect(self.create_group_clicked.emit)

    # ── Today's Summary ─────────────────────────────────────────────

    def _build_today_summary(self) -> None:
        card = QFrame(self)
        card.setGeometry(60, 572, 1320, 200)
        card.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border: 1px solid {rgba('#ffffff', 0.10)}; "
            f"border-radius: 12px; }}"
        )
        bar = QFrame(self)
        bar.setGeometry(60, 572, 4, 200)
        bar.setStyleSheet(
            f"background: {GREEN}; "
            f"border-top-left-radius: 2px; "
            f"border-bottom-left-radius: 2px; border: none;")

        cap = QLabel("TODAY'S AI ACTIONS", self)
        cap.setGeometry(80, 584, 160, 14)
        cap.setFont(inter(10, QFont.Weight.Bold, letter_spacing=1.4))
        cap.setStyleSheet(
            f"color: {GREEN_LIGHT}; background: transparent; "
            f"border: none;")
        sep = QLabel("·", self)
        sep.setGeometry(232, 582, 8, 18)
        sep.setFont(inter(13))
        sep.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; border: none;")
        hint = QLabel("Live audit log — refreshes every hour", self)
        hint.setGeometry(246, 584, 400, 14)
        hint.setFont(inter(10, QFont.Weight.Medium))
        hint.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; "
            f"border: none;")

        # Big number stats row — live values from today's plan
        s = self._live_today_stats
        stats = [
            ("Songs rested",      str(s.get("rested", 0))),
            ("Sister promotions", str(s.get("promoted", 0))),
            ("Clocks balanced",   str(s.get("balanced", 0))),
            ("Errors",            str(s.get("errors", 0))),
        ]
        # Track stat labels for refresh()
        self._stat_value_lbls: list = []
        sx = 80
        for label, val in stats:
            v = QLabel(val, self)
            v.setGeometry(sx, 612, 200, 40)
            v.setFont(mono(32, bold=True))
            v.setStyleSheet(
                f"color: {TEXT_PRI}; background: transparent; "
                f"border: none;")
            self._stat_value_lbls.append(v)
            l = QLabel(label, self)
            l.setGeometry(sx, 654, 260, 14)
            l.setFont(inter(10, QFont.Weight.Bold, letter_spacing=1.2))
            l.setStyleSheet(
                f"color: {TEXT_SEC}; background: transparent; "
                f"border: none;")
            sx += 280

        # Decisions log — live from DB
        head = QLabel("Recent decisions:", self)
        head.setGeometry(80, 690, 300, 16)
        head.setFont(inter(11, QFont.Weight.Bold))
        head.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent; border: none;")

        # Track decision row labels so refresh() can rebuild them
        self._decision_row_lbls: list = []
        decisions = (self._live_recent_decisions
                     if self._live_recent_decisions
                     else ["No decisions yet — first engine tick "
                           "will populate this log."])
        ay = 710
        for entry in decisions:
            row = QLabel("•  " + entry, self)
            row.setGeometry(80, ay, 1280, 14)
            row.setFont(inter(10, QFont.Weight.Medium))
            row.setStyleSheet(
                f"color: {TEXT_MUTED}; background: transparent; "
                f"border: none;")
            self._decision_row_lbls.append(row)
            ay += 14

        # Big CTA — Review Today's Plan
        cta = QPushButton(self)
        cta.setGeometry(1160, 612, 200, 64)
        cta.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        cta.setStyleSheet(
            f"QPushButton {{ background: {rgba(PURPLE, 0.22)}; "
            f"border: 1px solid {rgba(PURPLE, 0.55)}; "
            f"border-radius: 12px; text-align: left; padding: 0; }}"
            f"QPushButton:hover {{ background: {rgba(PURPLE, 0.32)}; }}"
        )
        cta.clicked.connect(self.review_plan_clicked.emit)

        icon = QLabel("📅", cta)
        icon.setGeometry(14, 12, 24, 20)
        icon.setFont(inter(16))
        icon.setStyleSheet(
            "background: transparent; border: none;")

        ctitle = QLabel("REVIEW TODAY'S PLAN  →", cta)
        ctitle.setGeometry(40, 12, 156, 16)
        ctitle.setFont(inter(11, QFont.Weight.Bold, letter_spacing=0.8))
        ctitle.setStyleSheet(
            f"color: {PURPLE_LIGHT}; background: transparent; "
            f"border: none;")

        csub = QLabel("Side-by-side: AI changes vs raw random", cta)
        csub.setGeometry(40, 32, 156, 14)
        csub.setFont(inter(9, QFont.Weight.Medium))
        csub.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; "
            f"border: none;")

        cfooter = QLabel("Auto-applies at 5 PM if no decision", cta)
        cfooter.setGeometry(40, 46, 156, 14)
        cfooter.setFont(inter(9, italic=True))
        cfooter.setStyleSheet(
            f"color: {AMBER_LIGHT}; background: transparent; "
            f"border: none;")

    # ── Status bar ──────────────────────────────────────────────────

    def _build_status_bar(self) -> None:
        sb = QFrame(self)
        sb.setGeometry(0, WINDOW_H - STATUS_H, WINDOW_W, STATUS_H)
        sb.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border-top: 1px solid {rgba('#ffffff', 0.06)}; }}"
        )
        x = 12
        engine_state = ({"ON": "Engine ON  ·  Continuous",
                          "WARMING": "Engine warming…",
                          "ERROR": "Engine error",
                          "OFF": "Engine OFF"}
                         .get(self._engine_state(),
                              "Engine —"))
        for txt, col in (("AUTO MODE",                  PURPLE),
                          ("🤖 SCHEDULING AUTOMATION",   PURPLE_LIGHT),
                          (engine_state,                 GREEN)):
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

    # ── Engine signal handlers ──────────────────────────────────────

    def _on_refresh_clicked(self) -> None:
        """Manual Refresh. Gate on the operator's enable toggle, then
        queue ONE tick onto the engine's worker thread — never call
        ``self._engine.tick()`` directly here: that would run a full
        plan compute on the UI thread, racing the engine's own hourly
        QTimer tick (two threads interleaving reset + decision writes
        on the same plan). Repaint arrives via the existing
        tick_completed wiring."""
        if self._engine is None:
            # Headless/test construction — fall back to the public
            # host signal (legacy Phase B path).
            self.refresh_engine_clicked.emit()
            return
        try:
            enabled = self._engine.is_enabled()
        except Exception as exc:
            log.debug(f"is_enabled check failed: {exc}")
            enabled = False
        if not enabled:
            dialogs.info(
                self, "Engine is OFF",
                "Rotation AI is currently stopped, so there is no "
                "plan to refresh. Enable the engine first, then hit "
                "Refresh to recompute today's plan.")
            return
        self._tick_requested.emit()

    def _on_engine_state_changed(self, new_state: str) -> None:
        """Engine fired engine_state_changed — repaint the dot + state
        label + status bar pill. Cheap incremental update; full
        section rebuild only on tick_completed."""
        engine_color = ({"ON": GREEN, "WARMING": AMBER, "ERROR": RED,
                          "OFF": TEXT_MUTED}
                         .get(new_state, TEXT_MUTED))
        if hasattr(self, "_engine_dot"):
            self._engine_dot.setStyleSheet(
                f"background: {engine_color}; border-radius: 14px; "
                f"border: none;")
        if hasattr(self, "_engine_halo"):
            self._engine_halo.setStyleSheet(
                f"background: {rgba(engine_color, 0.15)}; "
                f"border: 1px solid {rgba(engine_color, 0.30)}; "
                f"border-radius: 24px;")
        if hasattr(self, "_engine_state_lbl"):
            state_label = ({"ON":      "ENGINE: ON",
                             "WARMING": "ENGINE: WARMING UP",
                             "ERROR":   "ENGINE: ERROR",
                             "OFF":     "ENGINE: OFF"}
                            .get(new_state, "ENGINE: —"))
            self._engine_state_lbl.setText(state_label)
            self._engine_state_lbl.setStyleSheet(
                f"color: {engine_color}; background: transparent; "
                f"border: none;")
        # Hero ENGINE pill
        if hasattr(self, "_pill_engine"):
            try:
                self._pill_engine._value_lbl.setText(
                    "● ON" if new_state == "ON" else "● " + new_state)
                self._pill_engine._value_lbl.setStyleSheet(
                    f"color: {engine_color}; background: transparent; "
                    f"border: none;")
            except AttributeError:
                pass

    def _on_tick_completed(self, plan_id: int, summary: dict) -> None:
        """Engine fired a tick — re-pull stats + recent decisions +
        repaint."""
        # Stat pills + hero pill counts
        self._live_today_stats = self._load_today_stats()
        if hasattr(self, "_stat_value_lbls"):
            labels = ["rested", "promoted", "balanced", "errors"]
            for i, key in enumerate(labels):
                if i < len(self._stat_value_lbls):
                    self._stat_value_lbls[i].setText(
                        str(self._live_today_stats.get(key, 0)))
        if hasattr(self, "_pill_balanced"):
            try:
                self._pill_balanced._value_lbl.setText(
                    str(self._live_today_stats.get("balanced", 0)))
            except AttributeError:
                pass
        # Refresh tick info string
        if hasattr(self, "_tick_info_lbl"):
            last_tick = self._last_tick_seconds()
            if last_tick >= 0:
                self._tick_info_lbl.setText(
                    f"Last tick: {last_tick}s ago  ·  "
                    f"Next tick: in {max(0, 3600 - last_tick)}s  ·  "
                    f"Continuous hourly rebalancing active")
        # Recent decisions log rebuild
        self._live_recent_decisions = self._load_recent_decisions()
        if hasattr(self, "_decision_row_lbls"):
            for lbl in self._decision_row_lbls:
                lbl.setParent(None)
                lbl.deleteLater()
            self._decision_row_lbls = []
        decisions = (self._live_recent_decisions
                     if self._live_recent_decisions
                     else ["No decisions yet — first engine tick "
                           "will populate this log."])
        ay = 710
        for entry in decisions:
            row = QLabel("•  " + entry, self)
            row.setGeometry(80, ay, 1280, 14)
            row.setFont(inter(10, QFont.Weight.Medium))
            row.setStyleSheet(
                f"color: {TEXT_MUTED}; background: transparent; "
                f"border: none;")
            row.show()
            self._decision_row_lbls.append(row)
            ay += 14

    # ── External hooks ──────────────────────────────────────────────

    def refresh(self) -> None:
        """Called by MainWindow on entry. Pulls fresh state from
        engine + DB; touches just the dynamic widgets (no full
        rebuild — that would flicker)."""
        self._load_state()
        self._on_engine_state_changed(self._engine_state())
        self._on_tick_completed(0, {})    # repaint pills + decisions

    def reload_groups(self) -> None:
        """Rebuild the sister-groups section after the operator
        creates / edits / deletes a group. Called by MainWindow's
        dialog handlers after a DB mutation."""
        # Wipe existing card widgets cleanly
        for w in getattr(self, "_group_cards", []):
            w.setParent(None)
            w.deleteLater()
        self._group_cards = []
        # Recompute live state + rebuild the section
        self._live_groups = self._load_groups()
        # Rebuild only the right_summary line + card grid (cheap)
        # by calling the builder again — it appends to self
        self._build_sister_groups()
