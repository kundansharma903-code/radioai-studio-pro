"""
RadioAI Studio Pro — AI Magic · Daily Plan Review (Figma 512:2)

Approval gate for the Time-Slot Freshness rotation engine. AI's
proposed plan for today's clocks lands here side-by-side with what
WOULD have played (raw random + separation). Operator:
  • Approve & Apply Now — AI changes commit to today's rotation
  • Discard Plan — wipe and revert to random + separation
  • Walk away — AI auto-applies at 5 PM (safety net)

Phase B (mock UI): three clock cards are hardcoded sample data so the
operator can validate UX flow. First card auto-expanded showing
LEFT (without AI) vs RIGHT (with AI) song lists with RESTED /
FRESH badges + AI Reasoning strip. Two more cards collapsed (one
with sister-group activity, one with "no sister group" zero-change
state). Phase E replaces mocks with live ``ai_rotation_decisions``
DB reads.

Public signals:
  screen_requested(str) — "control_panel" / "ai_magic" /
                          "scheduling_automation" / "studio_open"
  studio_clicked()      — header Open Studio button
  approve_clicked()
  discard_clicked()
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from PyQt6.QtCore import Qt, QRectF, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QLinearGradient,
    QFont, QCursor,
)
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QHBoxLayout, QVBoxLayout,
    QScrollArea, QMessageBox,
)

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
from ui.scheduling_automation_hub import (
    _PurplePill, _HeroStatPill, BG_ELEV,
)

log = logging.getLogger("SchedulingDailyPlan")

WINDOW_W = 1440
WINDOW_H = 900
HEADER_H = 72
STATUS_H = 36

RED_LIGHT = "#fb7185"


# ════════════════════════════════════════════════════════════════════════════
# Small widgets — song row, status badge
# ════════════════════════════════════════════════════════════════════════════


class _SongRow(QFrame):
    """One song row inside a clock card column. Time + color dot +
    title + artist + category + optional status badge (RESTED / FRESH).
    Fixed height so card geometry stays predictable."""

    HEIGHT = 42

    def __init__(self, time: str, title: str, artist: str,
                 cat_name: str, cat_color: str,
                 badge_kind: str = "",
                 badge_label: str = "", parent=None):
        super().__init__(parent)
        self.setFixedHeight(self.HEIGHT)
        self.setStyleSheet(
            "QFrame { background: transparent; border: none; }")

        time_lbl = QLabel(time, self)
        time_lbl.setGeometry(0, 4, 50, 14)
        time_lbl.setFont(mono(11, bold=True))
        time_lbl.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; "
            f"border: none;")

        dot = QFrame(self)
        dot.setGeometry(54, 8, 10, 10)
        dot.setStyleSheet(
            f"background: {cat_color}; border-radius: 5px; "
            f"border: none;")

        name_lbl = QLabel(title, self)
        name_lbl.setGeometry(72, 0, 360, 18)
        name_lbl.setFont(inter(12, QFont.Weight.DemiBold))
        name_lbl.setStyleSheet(
            f"color: {TEXT_PRI}; background: transparent; "
            f"border: none;")

        sub_lbl = QLabel(f"{artist}  ·  {cat_name}", self)
        sub_lbl.setGeometry(72, 18, 360, 14)
        sub_lbl.setFont(inter(10, QFont.Weight.Medium))
        sub_lbl.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; "
            f"border: none;")

        if badge_kind:
            self._add_badge(badge_kind, badge_label)
        self._badge_kind = badge_kind

    def _add_badge(self, kind: str, label_text: str) -> None:
        # rested badge or fresh badge
        if kind == "rested":
            color = RED; light = RED_LIGHT
            text = label_text or "WILL BE RESTED"
            w = 130
        elif kind == "fresh":
            color = GREEN; light = GREEN_LIGHT
            text = label_text or "+ FRESH"
            w = 156
        elif kind == "agrees":
            color = CYAN; light = CYAN_LIGHT
            text = label_text or "AI AGREES"
            w = 110
        else:
            return
        # Right-aligned — caller positions row inside fixed-width column
        # so we compute position lazily in resizeEvent.
        self._badge_w = w
        self._badge_color = color
        self._badge_light = light
        self._badge_text = text

        self._badge = QFrame(self)
        self._badge.setGeometry(self.width() - w - 4, 6, w, 26)
        self._badge.setStyleSheet(
            f"QFrame {{ background: {rgba(color, 0.18)}; "
            f"border: 1px solid {rgba(color, 0.45)}; "
            f"border-radius: 6px; }}"
        )
        self._badge_lbl = QLabel(text, self._badge)
        self._badge_lbl.setGeometry(0, 0, w, 26)
        self._badge_lbl.setFont(
            inter(9, QFont.Weight.Bold, letter_spacing=0.4))
        self._badge_lbl.setStyleSheet(
            f"color: {light}; background: transparent; "
            f"border: none;")
        self._badge_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        # Re-position the badge on resize
        if getattr(self, "_badge_kind", "") and hasattr(self, "_badge"):
            w = self._badge_w
            self._badge.setGeometry(self.width() - w - 4, 6, w, 26)
            self._badge_lbl.setGeometry(0, 0, w, 26)


class _ClockCard(QFrame):
    """Expandable clock card — top bar always visible, body (left+right
    columns + reasoning) shown when expanded.

    Phase B: expansion state is hardcoded at construction (operator
    can toggle). Real engine in Phase E will manage expansion state
    + sync with the underlying ai_rotation_decisions data."""

    toggle_clicked = pyqtSignal(int)

    HEADER_H = 50
    BODY_GAP = 14
    COL_H    = 230
    REASONING_H = 26
    BODY_TOTAL_H = COL_H + REASONING_H + 24      # left/right cols + reasoning + padding

    def __init__(self, *, clock_idx: int,
                 time_range: str,
                 clock_name: str,
                 group_badge_text: str,
                 group_badge_color: str,
                 group_badge_light: str,
                 change_summary: str,
                 left_songs: list[dict],
                 right_songs: list[dict],
                 ai_reasoning: str = "",
                 expanded: bool = False,
                 accent: str = PURPLE,
                 parent=None):
        super().__init__(parent)
        self._idx = clock_idx
        self._expanded = bool(expanded)
        self._accent = accent
        self._left_songs = left_songs
        self._right_songs = right_songs
        self._ai_reasoning = ai_reasoning

        self.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border: 1px solid {rgba('#ffffff', 0.10)}; "
            f"border-radius: 12px; }}"
        )
        # Compute total height
        self._collapsed_h = self.HEADER_H + 6   # small footer pad
        self._expanded_h  = (self.HEADER_H + self.BODY_GAP
                              + self.COL_H + 18 + self.REASONING_H + 12)
        self.setFixedHeight(self._expanded_h if self._expanded
                              else self._collapsed_h)

        # ── HEADER row ────────────────────────────────────────────
        time_lbl = QLabel(time_range, self)
        time_lbl.setGeometry(20, 14, 140, 22)
        time_lbl.setFont(mono(16, bold=True))
        time_lbl.setStyleSheet(
            f"color: {TEXT_PRI}; background: transparent; border: none;")

        dot1 = QLabel("·", self)
        dot1.setGeometry(160, 14, 12, 22)
        dot1.setFont(inter(14))
        dot1.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; "
            f"border: none;")

        name_lbl = QLabel(f"Clock \"{clock_name}\"", self)
        name_lbl.setGeometry(178, 16, 220, 18)
        name_lbl.setFont(inter(13, QFont.Weight.Bold))
        name_lbl.setStyleSheet(
            f"color: {TEXT_PRI}; background: transparent; border: none;")

        # Group badge
        bw = 180
        badge = QFrame(self)
        badge.setGeometry(400, 14, bw, 22)
        badge.setStyleSheet(
            f"QFrame {{ background: {rgba(group_badge_color, 0.18)}; "
            f"border: 1px solid {rgba(group_badge_color, 0.45)}; "
            f"border-radius: 11px; }}"
        )
        blbl = QLabel(group_badge_text, badge)
        blbl.setGeometry(0, 0, bw, 22)
        blbl.setFont(inter(10, QFont.Weight.Bold, letter_spacing=0.8))
        blbl.setStyleSheet(
            f"color: {group_badge_light}; background: transparent; "
            f"border: none;")
        blbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Change summary (right side)
        self._summary_lbl = QLabel(change_summary, self)
        self._summary_lbl.setGeometry(800, 16, 320, 18)
        self._summary_lbl.setFont(inter(11, QFont.Weight.Medium))
        self._summary_lbl.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent; "
            f"border: none;")
        self._summary_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)

        # Chevron toggle
        self._chevron_lbl = QLabel("▾" if self._expanded else "▸", self)
        self._chevron_lbl.setGeometry(1140, 16, 16, 20)
        self._chevron_lbl.setFont(inter(14, QFont.Weight.Bold))
        self._chevron_lbl.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent; "
            f"border: none;")

        # Make whole header clickable
        click = QPushButton(self)
        click.setGeometry(0, 0, 1320, self.HEADER_H)
        click.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        click.setStyleSheet(
            "QPushButton { background: transparent; border: none; }")
        click.clicked.connect(
            lambda _=False, i=clock_idx: self._toggle_internal(i))

        # ── BODY (only when expanded) ────────────────────────────
        if self._expanded:
            self._build_body()

    def _toggle_internal(self, idx: int):
        # Phase B — local toggle. Real flow has host re-build with
        # different expansion states. For mock we just emit.
        self.toggle_clicked.emit(idx)

    def _build_body(self) -> None:
        # Divider line
        div = QFrame(self)
        div.setGeometry(20, self.HEADER_H, 1280, 1)
        div.setStyleSheet(
            f"background: {rgba('#ffffff', 0.10)}; border: none;")

        # LEFT column container (gray border)
        left_y = self.HEADER_H + self.BODY_GAP
        left_w = 624
        left_col = QFrame(self)
        left_col.setGeometry(20, left_y, left_w, self.COL_H)
        left_col.setStyleSheet(
            f"QFrame {{ background: {BG_ELEV()}; "
            f"border: 1px solid {rgba('#ffffff', 0.10)}; "
            f"border-radius: 8px; }}"
        )

        # RIGHT column container (purple border)
        right_x = 20 + left_w + 16
        right_w = 644
        right_col = QFrame(self)
        right_col.setGeometry(right_x, left_y, right_w, self.COL_H)
        right_col.setStyleSheet(
            f"QFrame {{ background: {BG_ELEV()}; "
            f"border: 1px solid {rgba(PURPLE, 0.40)}; "
            f"border-radius: 8px; }}"
        )

        # Render rows in each
        sy = 12
        for r in self._left_songs:
            row = _SongRow(
                r.get("time", ""), r.get("title", ""), r.get("artist", ""),
                r.get("cat_name", ""), r.get("cat_color", CYAN),
                badge_kind=r.get("badge_kind", ""),
                badge_label=r.get("badge_label", ""),
                parent=left_col)
            row.setGeometry(16, sy, left_w - 32, row.HEIGHT)
            sy += row.HEIGHT + 6
        sy = 12
        for r in self._right_songs:
            row = _SongRow(
                r.get("time", ""), r.get("title", ""), r.get("artist", ""),
                r.get("cat_name", ""), r.get("cat_color", CYAN),
                badge_kind=r.get("badge_kind", ""),
                badge_label=r.get("badge_label", ""),
                parent=right_col)
            row.setGeometry(16, sy, right_w - 32, row.HEIGHT)
            sy += row.HEIGHT + 6

        # AI Reasoning strip
        if self._ai_reasoning:
            reason_y = left_y + self.COL_H + 12
            reason_lbl = QLabel(
                f"AI Reasoning:  {self._ai_reasoning}", self)
            reason_lbl.setGeometry(20, reason_y, 1280, 18)
            reason_lbl.setFont(inter(10, italic=True))
            reason_lbl.setStyleSheet(
                f"color: {TEXT_MUTED}; background: transparent; "
                f"border: none;")

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(QRectF(0, 0, 4, self.height()), QColor(self._accent))
        p.end()


# ════════════════════════════════════════════════════════════════════════════
# Public screen
# ════════════════════════════════════════════════════════════════════════════


class SchedulingDailyPlanReview(QWidget):
    """AI Magic · Daily Plan Review (Figma 512:2)."""

    screen_requested = pyqtSignal(str)
    studio_clicked   = pyqtSignal()
    approve_clicked  = pyqtSignal()
    discard_clicked  = pyqtSignal()

    # ── Mock data (Phase B) ─────────────────────────────────────────

    # Three clock cards — first expanded, others collapsed.
    # Phase E replaces this with live ai_rotation_decisions DB reads.

    MOCK_PLAN_DATE = "Tue, 15 May 2026"
    MOCK_HERO_STATS = {
        "clocks":      8,
        "ai_changes": 32,
        "rested":     18,
    }

    MOCK_CLOCK_CARDS = [
        # ── CARD 1 — 10:00-11:00 Morning Mix (expanded) ──
        {
            "expanded": True,
            "time_range": "10:00 - 11:00",
            "clock_name": "Morning Mix",
            "group_badge_text":  "✦ Morning family group",
            "group_badge_color": AMBER,
            "group_badge_light": AMBER_LIGHT,
            "change_summary":    "5 changes · 18 rested · 14 fresh",
            "accent":            PURPLE,
            "left_songs": [
                {"time": "10:00", "title": "Tum Hi Ho",
                 "artist": "Arijit Singh", "cat_name": "Morning A",
                 "cat_color": AMBER},
                {"time": "10:12", "title": "Pyaar Hua Ikrar Hua",
                 "artist": "Manna Dey", "cat_name": "Morning A",
                 "cat_color": AMBER},
                {"time": "10:25", "title": "Tum Hi Ho",
                 "artist": "Arijit Singh", "cat_name": "Morning A",
                 "cat_color": AMBER,
                 "badge_kind": "rested",
                 "badge_label": "WILL BE RESTED"},
                {"time": "10:38", "title": "Sai Sai",
                 "artist": "Anup Jalota", "cat_name": "Morning B",
                 "cat_color": PURPLE},
                {"time": "10:50", "title": "Kabhi Kabhi Mere",
                 "artist": "Mukesh", "cat_name": "Morning A",
                 "cat_color": AMBER},
            ],
            "right_songs": [
                {"time": "10:00", "title": "Sai Sai",
                 "artist": "Anup Jalota", "cat_name": "Morning B",
                 "cat_color": PURPLE,
                 "badge_kind": "fresh",
                 "badge_label": "+ FRESH  ·  from sister B"},
                {"time": "10:12", "title": "Pyaar Hua Ikrar Hua",
                 "artist": "Manna Dey", "cat_name": "Morning A",
                 "cat_color": AMBER},
                {"time": "10:25", "title": "Aaj Kal Tere Mere",
                 "artist": "Mohd Rafi", "cat_name": "Morning A",
                 "cat_color": AMBER,
                 "badge_kind": "fresh",
                 "badge_label": "+ FRESH  ·  fresh in slot"},
                {"time": "10:38", "title": "Kabhi Kabhi Mere",
                 "artist": "Mukesh", "cat_name": "Morning A",
                 "cat_color": AMBER},
                {"time": "10:50", "title": "Naina Lade",
                 "artist": "Jubin Nautiyal", "cat_name": "Morning D",
                 "cat_color": GREEN,
                 "badge_kind": "fresh",
                 "badge_label": "+ FRESH  ·  from sister D"},
            ],
            "ai_reasoning": (
                "Tum Hi Ho rested (slot_age=0 — played yesterday in "
                "10 AM slot). 3 sister-category songs promoted to "
                "maintain Morning Mix variety."
            ),
        },
        # ── CARD 2 — 18:00-19:00 Evening Bhakti (collapsed) ──
        {
            "expanded": False,
            "time_range": "18:00 - 19:00",
            "clock_name": "Evening Bhakti",
            "group_badge_text":  "✦ Evening Bhakti family",
            "group_badge_color": PURPLE,
            "group_badge_light": PURPLE_LIGHT,
            "change_summary":    "4 changes · 9 rested · 7 fresh",
            "accent":            PURPLE,
            "left_songs":  [],
            "right_songs": [],
            "ai_reasoning": "",
        },
        # ── CARD 3 — 21:00-22:00 Late Night Romance (collapsed, no group) ──
        {
            "expanded": False,
            "time_range": "21:00 - 22:00",
            "clock_name": "Late Night Romance",
            "group_badge_text":  "No sister group",
            "group_badge_color": TEXT_MUTED,
            "group_badge_light": TEXT_MUTED,
            "change_summary":    "0 changes (no group)",
            "accent":            CYAN,
            "left_songs":  [],
            "right_songs": [],
            "ai_reasoning": "",
        },
    ]

    # ── Construction ────────────────────────────────────────────────

    def __init__(self, db=None, parent=None):
        super().__init__(parent)
        self._db = db
        self.setFixedSize(WINDOW_W, WINDOW_H)
        self.setStyleSheet(f"QWidget {{ background: {BG_BASE}; }}")

        self._backdrop = _PremiumBackdrop(self)
        self._backdrop.setGeometry(0, 0, WINDOW_W, WINDOW_H)

        # Live state — loaded from DB. Falls back to MOCK_* defaults
        # when no DB or no plan yet (operator hasn't seen a tick).
        self._live_plan_date: str = self.MOCK_PLAN_DATE
        self._live_hero_stats: dict = dict(self.MOCK_HERO_STATS)
        self._live_clock_cards: list = list(self.MOCK_CLOCK_CARDS)
        self._load_state()

        self._build_header()
        self._build_hero()
        self._build_diff_legend()
        self._build_clock_cards()
        self._build_action_bar()
        self._build_status_bar()

        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._tick_clock)
        self._clock_timer.start()
        self._tick_clock()

        log.info(
            "SchedulingDailyPlanReview ready (Figma 512:2, live mode)")

    # ── Live state loader ─────────────────────────────────────────────

    def _load_state(self) -> None:
        """Pull today's plan + decisions from DB and shape them into
        the clock-card structure the build pipeline expects."""
        if self._db is None:
            # No DB → keep MOCK_* defaults
            return
        from datetime import date as _date
        today = _date.today()
        try:
            today_iso = today.isoformat()
            plan = self._db.get_ai_rotation_plan(today_iso)
            decisions = self._db.get_rotation_decisions_for_date(
                today_iso)
        except Exception as exc:
            log.warning(f"_load_state DB fetch failed: {exc}")
            return

        self._live_plan_date = today.strftime("%a, %d %b %Y")

        # Hero stats from plan envelope
        if plan:
            rested = int(plan.get("rested_count") or 0)
            promoted = int(plan.get("promoted_count") or 0)
            clocks = int(plan.get("clocks_balanced") or 0)
            self._live_hero_stats = {
                "clocks":      clocks,
                "ai_changes":  rested + promoted,
                "rested":      rested,
            }
        else:
            # No plan yet — show empty hero
            self._live_hero_stats = {"clocks": 0, "ai_changes": 0,
                                       "rested": 0}

        # If no decisions in DB → empty state (no cards)
        if not decisions:
            self._live_clock_cards = []
            return

        # Group decisions by clock_id, then within each clock split
        # left (rest) vs right (pick/promote) song lists
        by_clock: dict[int, dict] = {}
        for d in decisions:
            cid = int(d["clock_id"])
            entry = by_clock.setdefault(cid, {
                "clock_id":   cid,
                "clock_name": d.get("clock_name") or "?",
                "hour":       int(d.get("hour") or 0),
                "rest_rows":     [],
                "promote_rows":  [],
                "pick_rows":     [],
            })
            action = (d.get("action") or "").lower()
            row = {
                "time":      f"{int(d.get('hour') or 0):02d}:"
                              f"{int(d.get('slot_idx') or 0) * 12 % 60:02d}",
                "title":     d.get("song_title") or "(song)",
                "artist":    d.get("song_artist") or "—",
                "cat_name":  (d.get("source_category_name")
                                or d.get("target_category_name")
                                or "—"),
                "cat_color": (d.get("source_category_color")
                                or d.get("target_category_color")
                                or CYAN),
                "reason":    d.get("reason") or "",
            }
            if action == "rest":
                entry["rest_rows"].append(row)
            elif action == "promote":
                entry["promote_rows"].append(row)
            else:    # 'pick'
                entry["pick_rows"].append(row)

        # Convert to the shape _build_clock_cards expects
        out: list = []
        sorted_clocks = sorted(by_clock.values(),
                                  key=lambda x: x["hour"])
        for i, e in enumerate(sorted_clocks):
            # group badge — find the sister group label for this clock's
            # primary category (which we infer from the first decision's
            # source/target category)
            group_label = "✦ Sister group"
            group_color = PURPLE
            group_light = PURPLE_LIGHT
            sample = (e["rest_rows"] + e["promote_rows"]
                       + e["pick_rows"])
            if sample and sample[0].get("cat_color"):
                group_color = sample[0]["cat_color"]
            # If no promote/rest decisions, group is "No sister group"
            if not e["promote_rows"] and not e["rest_rows"]:
                group_label = "No sister group"
                group_color = TEXT_MUTED
                group_light = TEXT_MUTED

            # LEFT column = rest_rows (songs that random would have
            # picked but AI vetoed) — mark each with WILL BE RESTED
            left_songs = []
            for r in e["rest_rows"]:
                left_songs.append({
                    "time": r["time"], "title": r["title"],
                    "artist": r["artist"], "cat_name": r["cat_name"],
                    "cat_color": r["cat_color"],
                    "badge_kind": "rested",
                    "badge_label": "WILL BE RESTED",
                })
            # RIGHT column = pick + promote rows. Promote marked FRESH.
            right_songs = []
            for r in e["promote_rows"]:
                right_songs.append({
                    "time": r["time"], "title": r["title"],
                    "artist": r["artist"], "cat_name": r["cat_name"],
                    "cat_color": r["cat_color"],
                    "badge_kind": "fresh",
                    "badge_label": "+ FRESH  ·  from sister",
                })
            for r in e["pick_rows"]:
                right_songs.append({
                    "time": r["time"], "title": r["title"],
                    "artist": r["artist"], "cat_name": r["cat_name"],
                    "cat_color": r["cat_color"],
                })

            n_rest = len(e["rest_rows"])
            n_promo = len(e["promote_rows"])
            n_pick = len(e["pick_rows"])
            n_changes = n_rest + n_promo
            change_summary = (f"{n_changes} changes · {n_rest} rested · "
                                f"{n_promo} fresh"
                                if n_changes else
                                f"0 changes")
            # Reasoning — concat first 1-2 reasons for surface area
            reasons = [r.get("reason", "")
                        for r in (e["rest_rows"] + e["promote_rows"])
                        if r.get("reason")][:2]
            reasoning = "  ".join(reasons) if reasons else ""

            out.append({
                "expanded":         (i == 0),    # first card auto-open
                "time_range":       f"{e['hour']:02d}:00 - "
                                      f"{(e['hour'] + 1) % 24:02d}:00",
                "clock_name":       e["clock_name"],
                "group_badge_text": group_label,
                "group_badge_color": group_color,
                "group_badge_light": group_light,
                "change_summary":   change_summary,
                "accent":           PURPLE if (n_changes > 0)
                                      else CYAN,
                "left_songs":       left_songs,
                "right_songs":      right_songs,
                "ai_reasoning":     reasoning,
            })
        self._live_clock_cards = out

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

        # 4-crumb breadcrumb
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

        sa = _BreadcrumbLink("Scheduling Automation", h)
        sa.setGeometry(376, 22, 160, 22)
        sa.clicked.connect(
            lambda: self.screen_requested.emit("scheduling_automation"))
        s3 = QLabel("|", h); s3.setGeometry(540, 22, 8, 22)
        s3.setFont(inter(11))
        s3.setStyleSheet(f"color: {TEXT_DIM}; background: transparent;")

        pill = _PurplePill("📅 Today's Plan", h)
        pill.move(552, 20)

        # Title
        title = QLabel("Today's Plan Review", h)
        title.setGeometry(782, 12, 280, 24)
        title.setFont(inter(20, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        sub = QLabel(
            "Approve AI's proposed rotation or let it auto-apply at 5 PM",
            h)
        sub.setGeometry(782, 38, 360, 14)
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
        sigil = QLabel("📅", self)
        sigil.setGeometry(60, 92, 40, 36)
        sigil.setFont(inter(28, QFont.Weight.Bold))
        sigil.setStyleSheet(
            f"color: {PURPLE_LIGHT}; background: transparent; "
            f"border: none;")
        title = QLabel("TODAY'S PLAN REVIEW", self)
        title.setGeometry(106, 88, 700, 44)
        title.setFont(inter(28, QFont.Weight.Black, letter_spacing=-0.4))
        title.setStyleSheet(
            f"color: {TEXT_PRI}; background: transparent; border: none;")

        sub1 = QLabel(
            f"{self._live_plan_date} — review AI's proposed song "
            "rotation. Approve to apply now, or let it auto-apply "
            "at 5 PM.", self)
        sub1.setGeometry(60, 132, 1100, 18)
        sub1.setFont(inter(13, QFont.Weight.Medium))
        sub1.setStyleSheet(
            f"color: {TEXT_SEC}; background: transparent; "
            f"border: none;")

        sub2 = QLabel(
            "Diff legend: 🟢 added from sister  ·  🔴 rested  ·  "
            "⚪ unchanged  ·  Click any clock card to expand.", self)
        sub2.setGeometry(60, 152, 1100, 16)
        sub2.setFont(inter(11, italic=True))
        sub2.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; "
            f"border: none;")

        # Hero stat pills (right)
        s = self._live_hero_stats
        self._pill_clocks = _HeroStatPill(
            "CLOCKS", str(s["clocks"]), PURPLE,
            value_color=TEXT_PRI, parent=self)
        self._pill_changes = _HeroStatPill(
            "AI CHANGES", str(s["ai_changes"]), GREEN, parent=self)
        self._pill_rested = _HeroStatPill(
            "RESTED", str(s["rested"]), RED, parent=self)
        gap = 10
        right_edge = WINDOW_W - 60
        pw = 132
        self._pill_rested.move(right_edge - pw, 92)
        self._pill_changes.move(right_edge - 2 * pw - gap, 92)
        self._pill_clocks.move(right_edge - 3 * pw - 2 * gap, 92)

    # ── Diff legend + column headers ────────────────────────────────

    def _build_diff_legend(self) -> None:
        cap = QLabel("DIFF VIEW · CLOCK BY CLOCK", self)
        cap.setGeometry(60, 200, 240, 14)
        cap.setFont(inter(10, QFont.Weight.Bold, letter_spacing=1.4))
        cap.setStyleSheet(
            f"color: {PURPLE_LIGHT}; background: transparent; "
            f"border: none;")

        l_hdr = QLabel("WITHOUT AI  (raw random + separation)", self)
        l_hdr.setGeometry(60, 222, 480, 14)
        l_hdr.setFont(inter(11, QFont.Weight.Bold, letter_spacing=1.2))
        l_hdr.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; "
            f"border: none;")

        r_hdr = QLabel(
            "WITH AI CHANGES  (Time-Slot Freshness)", self)
        r_hdr.setGeometry(720, 222, 540, 14)
        r_hdr.setFont(inter(11, QFont.Weight.Bold, letter_spacing=1.2))
        r_hdr.setStyleSheet(
            f"color: {PURPLE_LIGHT}; background: transparent; "
            f"border: none;")

    # ── Clock cards (scrollable list) ───────────────────────────────

    def _build_clock_cards(self) -> None:
        # Scroll area for cards (in case >3 clocks)
        scroll = QScrollArea(self)
        scroll.setGeometry(60, 248, 1320, 480)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            f"QScrollBar:vertical {{ background: {BG_PANEL}; "
            f"width: 10px; border-radius: 5px; }}"
            f"QScrollBar::handle:vertical {{ background: "
            f"{rgba('#ffffff', 0.12)}; border-radius: 5px; "
            f"min-height: 30px; }}"
            f"QScrollBar::handle:vertical:hover {{ background: "
            f"{rgba(PURPLE, 0.40)}; }}"
            f"QScrollBar::add-line:vertical, "
            f"QScrollBar::sub-line:vertical {{ height: 0; }}"
        )
        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        v = QVBoxLayout(inner)
        v.setContentsMargins(0, 0, 12, 0); v.setSpacing(12)

        self._cards: list[_ClockCard] = []
        cards_spec = self._live_clock_cards
        if not cards_spec:
            # Empty state — no plan computed yet
            empty = QFrame(inner)
            empty.setFixedSize(1320, 200)
            empty.setStyleSheet(
                f"QFrame {{ background: transparent; "
                f"border: 1px dashed {rgba('#ffffff', 0.10)}; "
                f"border-radius: 12px; }}")
            t = QLabel("No plan yet for today", empty)
            t.setGeometry(0, 70, 1320, 24)
            t.setFont(inter(14, QFont.Weight.Bold))
            t.setStyleSheet(
                f"color: {TEXT_SEC}; background: transparent; "
                f"border: none;")
            t.setAlignment(Qt.AlignmentFlag.AlignCenter)
            s2 = QLabel(
                "The engine ticks every hour. The first plan lands "
                "within an hour of boot. Hit Refresh on the Hub to "
                "force a tick now.", empty)
            s2.setGeometry(0, 100, 1320, 14)
            s2.setFont(inter(11, QFont.Weight.Medium))
            s2.setStyleSheet(
                f"color: {TEXT_MUTED}; background: transparent; "
                f"border: none;")
            s2.setAlignment(Qt.AlignmentFlag.AlignCenter)
            v.addWidget(empty)
        else:
            for idx, spec in enumerate(cards_spec):
                card = _ClockCard(
                    clock_idx=idx,
                    time_range=spec["time_range"],
                    clock_name=spec["clock_name"],
                    group_badge_text=spec["group_badge_text"],
                    group_badge_color=spec["group_badge_color"],
                    group_badge_light=spec["group_badge_light"],
                    change_summary=spec["change_summary"],
                    left_songs=spec["left_songs"],
                    right_songs=spec["right_songs"],
                    ai_reasoning=spec.get("ai_reasoning", ""),
                    expanded=spec.get("expanded", False),
                    accent=spec.get("accent", PURPLE),
                    parent=inner)
                card.setFixedWidth(1320)
                card.toggle_clicked.connect(self._on_card_toggled)
                v.addWidget(card)
                self._cards.append(card)

            # Footer hint — only show when there are more than 3 cards
            if len(cards_spec) > 3:
                hint = QLabel(
                    f"+ {len(cards_spec) - 3} more clocks below "
                    "— scroll to review all", inner)
                hint.setFont(inter(11, italic=True))
                hint.setStyleSheet(
                    f"color: {TEXT_MUTED}; background: transparent; "
                    f"border: none;")
                v.addWidget(hint)
        v.addStretch()

        scroll.setWidget(inner)
        self._scroll = scroll
        self._scroll_inner = inner

    def _on_card_toggled(self, idx: int) -> None:
        """Toggle expansion of the clicked card. Rebuilds the scroll
        section so heights re-flow cleanly."""
        if 0 <= idx < len(self._live_clock_cards):
            self._live_clock_cards[idx]["expanded"] = (
                not self._live_clock_cards[idx]["expanded"])
        # Rebuild the cards section so heights re-flow
        # Save scroll position
        scroll_pos = self._scroll.verticalScrollBar().value()
        # Clear inner layout
        for w in list(self._cards):
            w.setParent(None)
            w.deleteLater()
        self._cards.clear()
        # Drop the scroll area + rebuild it
        self._scroll.setParent(None)
        self._scroll.deleteLater()
        self._build_clock_cards()
        # Restore scroll position
        self._scroll.verticalScrollBar().setValue(scroll_pos)

    # ── Action bar ──────────────────────────────────────────────────

    def _build_action_bar(self) -> None:
        bar = QFrame(self)
        bar.setGeometry(60, 740, 1320, 60)
        bar.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border: 1px solid {rgba('#ffffff', 0.10)}; "
            f"border-radius: 12px; }}"
        )

        # Left: auto-apply notice
        icon = QLabel("⏰", self)
        icon.setGeometry(80, 756, 24, 22)
        icon.setFont(inter(14))
        icon.setStyleSheet(
            f"color: {AMBER_LIGHT}; background: transparent; "
            f"border: none;")

        notice = QLabel(
            "Auto-applies at 5 PM if no decision", self)
        notice.setGeometry(108, 756, 400, 18)
        notice.setFont(inter(12, QFont.Weight.Bold))
        notice.setStyleSheet(
            f"color: {AMBER_LIGHT}; background: transparent; "
            f"border: none;")

        hint = QLabel(
            "Approve now to apply immediately. Discard to revert "
            "to random + separation.", self)
        hint.setGeometry(108, 774, 800, 14)
        hint.setFont(inter(10, QFont.Weight.Medium))
        hint.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; "
            f"border: none;")

        # Discard
        discard = QPushButton("✕   Discard Plan", self)
        discard.setGeometry(932, 752, 144, 36)
        discard.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        discard.setFont(inter(11, QFont.Weight.Bold))
        discard.setStyleSheet(
            f"QPushButton {{ background: {BG_ELEV()}; "
            f"color: {RED_LIGHT}; "
            f"border: 1px solid {rgba(RED, 0.40)}; "
            f"border-radius: 10px; }}"
            f"QPushButton:hover {{ background: {rgba(RED, 0.12)}; }}"
        )
        discard.clicked.connect(self.discard_clicked.emit)

        # Approve
        approve = QPushButton("✓   Approve & Apply Now", self)
        approve.setGeometry(1092, 752, 270, 36)
        approve.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        approve.setFont(inter(12, QFont.Weight.Bold))
        approve.setStyleSheet(
            f"QPushButton {{ background: {rgba(GREEN, 0.28)}; "
            f"color: {GREEN_LIGHT}; "
            f"border: 1px solid {rgba(GREEN, 0.55)}; "
            f"border-radius: 10px; }}"
            f"QPushButton:hover {{ background: {rgba(GREEN, 0.38)}; }}"
        )
        approve.clicked.connect(self.approve_clicked.emit)

    # ── Status bar ──────────────────────────────────────────────────

    def _build_status_bar(self) -> None:
        sb = QFrame(self)
        sb.setGeometry(0, WINDOW_H - STATUS_H, WINDOW_W, STATUS_H)
        sb.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; "
            f"border-top: 1px solid {rgba('#ffffff', 0.06)}; }}"
        )
        x = 12
        for txt, col in (("AUTO MODE",                PURPLE),
                          ("📅 TODAY'S PLAN REVIEW",  PURPLE_LIGHT),
                          (self._live_plan_date,        GREEN)):
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

    # ── External hooks ──────────────────────────────────────────────

    def refresh(self) -> None:
        """Re-pull today's plan + decisions from DB and rebuild the
        clock-cards scroll section. Called by MainWindow on entry."""
        self._load_state()
        # Rebuild hero pills inline (cheap)
        if hasattr(self, "_pill_clocks"):
            try:
                self._pill_clocks._value_lbl.setText(
                    str(self._live_hero_stats.get("clocks", 0)))
                self._pill_changes._value_lbl.setText(
                    str(self._live_hero_stats.get("ai_changes", 0)))
                self._pill_rested._value_lbl.setText(
                    str(self._live_hero_stats.get("rested", 0)))
            except AttributeError:
                pass
        # Wipe + rebuild the scroll area
        if hasattr(self, "_scroll") and self._scroll is not None:
            try:
                self._scroll.setParent(None)
                self._scroll.deleteLater()
            except Exception:
                pass
        self._build_clock_cards()
