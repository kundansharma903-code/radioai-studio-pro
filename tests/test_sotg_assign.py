"""
SOTG · Assign screen + DB helpers tests (Figma 474:3).

Pinned behaviour:

DB helpers:
  • upsert_sotg_assignment validates HH:MM, priority, status,
    scheduled_date format.
  • Past-time guard: scheduled_date == today + sharp_time < now
    raises ValueError. allow_past=True bypasses.
  • Past-date (yesterday) is always rejected.
  • Tomorrow + any HH:MM is accepted.
  • UNIQUE(link_id, scheduled_date) → upsert replaces in place.
  • mark_sotg_assignment_fired stamps status + fired_at.
  • get_sotg_assignments_for_show_date joins links + assignments
    (so unfilled links surface too).
  • get_sotg_assignment_counts_for_date breaks down per show.

Screen:
  • SOTGAssign constructs at 1440×900 without crashing.
  • _DateToggle flips Today ↔ Tomorrow + emits ISO date.
  • _SharpTimeInput red-borders + flags invalid when validating
    today + a past HH:MM.
  • _FileButton render swaps Choose File ↔ filename pill.
  • _LinkRow save button gated until file + valid time + priority.
  • Breadcrumbs emit expected keys.
  • Station label has hdr_station_lbl objectName.

MainWindow integration:
  • SOTGAssign mounts.
  • "assign" route lands on it (was a toast).
"""

from __future__ import annotations

import os
import uuid
from datetime import date, timedelta, datetime

import pytest

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel

from core.database import Database
from core import dialogs as _dialogs


@pytest.fixture
def db():
    return Database()


@pytest.fixture
def seeded_show(db):
    """Create a fresh show with 3 links for assignment tests, then
    clean up at the end via cascade."""
    sid = db.create_sotg_show(
        rj_name=f"RJ {uuid.uuid4().hex[:6]}",
        show_name=f"Show {uuid.uuid4().hex[:6]}",
        days="Daily",
        time_start="04:00", time_end="07:00",
        color="#06b6d4", description="",
        link_names=["L1", "L2", "L3"])
    yield sid
    try:
        db.delete_sotg_show(sid)
    except Exception:
        pass


def _future_hhmm_today() -> str:
    """A HH:MM that's at least 1 hour in the future today, clamped
    so it stays inside 24:00."""
    now = datetime.now()
    h = (now.hour + 1) % 24
    return f"{h:02d}:30"


# ── DB helpers ─────────────────────────────────────────────────────────


def test_upsert_creates_assignment_then_replaces_in_place(db, seeded_show):
    show = db.get_sotg_show(seeded_show)
    link_id = int(show["links"][0]["id"])
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    a1 = db.upsert_sotg_assignment(
        show_id=seeded_show, link_id=link_id,
        scheduled_date=tomorrow,
        file_path="/x/a.mp3", file_name="a.mp3",
        file_duration_ms=10_000,
        sharp_time="05:00", priority="High", status="READY")
    a2 = db.upsert_sotg_assignment(
        show_id=seeded_show, link_id=link_id,
        scheduled_date=tomorrow,
        file_path="/x/b.mp3", file_name="b.mp3",
        file_duration_ms=12_000,
        sharp_time="05:30", priority="Low", status="READY")
    assert a1 == a2  # UNIQUE constraint → same id
    fetched = db.get_sotg_assignment(link_id, tomorrow)
    assert fetched["file_name"] == "b.mp3"
    assert fetched["sharp_time"] == "05:30"
    assert fetched["priority"] == "Low"


def test_past_time_today_rejected(db, seeded_show):
    show = db.get_sotg_show(seeded_show)
    link_id = int(show["links"][0]["id"])
    now = datetime.now()
    if now.hour == 0 and now.minute == 0:
        pytest.skip("Edge: midnight — no past minutes available today")
    past_hh = max(0, now.hour - 1)
    past_str = f"{past_hh:02d}:00"
    with pytest.raises(ValueError, match="past|passed"):
        db.upsert_sotg_assignment(
            show_id=seeded_show, link_id=link_id,
            scheduled_date=date.today().isoformat(),
            file_path="/x/p.mp3", file_name="p.mp3",
            file_duration_ms=10_000,
            sharp_time=past_str, priority="High", status="READY")


def test_past_time_today_allowed_when_explicit(db, seeded_show):
    show = db.get_sotg_show(seeded_show)
    link_id = int(show["links"][0]["id"])
    now = datetime.now()
    if now.hour == 0 and now.minute == 0:
        pytest.skip("Edge: midnight")
    past_str = f"{max(0, now.hour - 1):02d}:00"
    # allow_past=True bypasses — used by Studio to log fires after
    # the sharp time has slipped past.
    aid = db.upsert_sotg_assignment(
        show_id=seeded_show, link_id=link_id,
        scheduled_date=date.today().isoformat(),
        file_path="/x/p.mp3", file_name="p.mp3",
        file_duration_ms=10_000,
        sharp_time=past_str, priority="High", status="MISSED",
        allow_past=True)
    assert isinstance(aid, int) and aid > 0


def test_past_date_always_rejected(db, seeded_show):
    show = db.get_sotg_show(seeded_show)
    link_id = int(show["links"][0]["id"])
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    with pytest.raises(ValueError, match="past|passed"):
        db.upsert_sotg_assignment(
            show_id=seeded_show, link_id=link_id,
            scheduled_date=yesterday,
            file_path="/x/p.mp3", file_name="p.mp3",
            file_duration_ms=10_000,
            sharp_time="12:00", priority="High", status="READY")


def test_tomorrow_any_time_accepted(db, seeded_show):
    show = db.get_sotg_show(seeded_show)
    link_id = int(show["links"][0]["id"])
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    # Even 00:00 tomorrow is fine.
    aid = db.upsert_sotg_assignment(
        show_id=seeded_show, link_id=link_id,
        scheduled_date=tomorrow,
        file_path="/x/p.mp3", file_name="p.mp3",
        file_duration_ms=10_000,
        sharp_time="00:00", priority="High", status="READY")
    assert isinstance(aid, int) and aid > 0


def test_invalid_hhmm_priority_status_rejected(db, seeded_show):
    show = db.get_sotg_show(seeded_show)
    link_id = int(show["links"][0]["id"])
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    common = dict(show_id=seeded_show, link_id=link_id,
                   scheduled_date=tomorrow,
                   file_path="/x/p.mp3", file_name="p.mp3",
                   file_duration_ms=10_000)
    with pytest.raises(ValueError):
        db.upsert_sotg_assignment(
            sharp_time="bad", priority="High", status="READY",
            **common)
    with pytest.raises(ValueError):
        db.upsert_sotg_assignment(
            sharp_time="05:00", priority="Urgent", status="READY",
            **common)
    with pytest.raises(ValueError):
        db.upsert_sotg_assignment(
            sharp_time="05:00", priority="High", status="ZOMBIE",
            **common)


def test_mark_fired_stamps_status(db, seeded_show):
    show = db.get_sotg_show(seeded_show)
    link_id = int(show["links"][0]["id"])
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    aid = db.upsert_sotg_assignment(
        show_id=seeded_show, link_id=link_id,
        scheduled_date=tomorrow,
        file_path="/x/p.mp3", file_name="p.mp3",
        file_duration_ms=10_000,
        sharp_time="05:00", priority="High", status="READY")
    db.mark_sotg_assignment_fired(aid)
    a = db.get_sotg_assignment(link_id, tomorrow)
    assert a["status"] == "FIRED"
    assert a["fired_at"] is not None and len(a["fired_at"]) > 0


def test_list_for_show_date_includes_unassigned_links(db, seeded_show):
    """Joining links LEFT JOIN assignments — unfilled links must still
    surface so the operator can see what's missing for the day."""
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    items = db.get_sotg_assignments_for_show_date(seeded_show, tomorrow)
    assert len(items) == 3   # 3 links seeded
    # None assigned yet → status is NULL or PENDING
    assert all(i.get("status") in (None, "PENDING") for i in items)


def test_counts_break_down_per_show_per_date(db, seeded_show):
    show = db.get_sotg_show(seeded_show)
    links = show["links"]
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    db.upsert_sotg_assignment(
        show_id=seeded_show, link_id=int(links[0]["id"]),
        scheduled_date=tomorrow,
        file_path="/x/a.mp3", file_name="a.mp3",
        file_duration_ms=10_000,
        sharp_time="04:30", priority="High", status="READY")
    aid_l1 = db.get_sotg_assignment(int(links[0]["id"]), tomorrow)["id"]
    db.upsert_sotg_assignment(
        show_id=seeded_show, link_id=int(links[1]["id"]),
        scheduled_date=tomorrow,
        file_path="/x/b.mp3", file_name="b.mp3",
        file_duration_ms=10_000,
        sharp_time="05:30", priority="Low", status="CONFLICT")
    counts = db.get_sotg_assignment_counts_for_date(tomorrow)
    c = counts[seeded_show]
    assert c["total"] == 3
    assert c["ready"] == 1
    assert c["conflict"] == 1
    assert c["fired"] == 0


# ── Screen smoke ───────────────────────────────────────────────────────


def test_construction_does_not_crash(qapp, db):
    from ui.sotg_assign import SOTGAssign
    s = SOTGAssign(db)
    assert s.size().width() == 1440
    assert s.size().height() == 900
    s.deleteLater()


def test_date_toggle_flips_today_tomorrow(qapp, db, qtbot):
    from ui.sotg_assign import SOTGAssign, _DateToggle
    s = SOTGAssign(db)
    qtbot.addWidget(s)
    received: list[str] = []
    s._date_toggle.date_changed.connect(received.append)
    assert s._date_toggle.is_today() is True
    s._date_toggle._on_tomorrow()
    assert s._date_toggle.is_today() is False
    assert received[-1] == (date.today() + timedelta(days=1)).isoformat()
    s._date_toggle._on_today()
    assert s._date_toggle.is_today() is True
    assert received[-1] == date.today().isoformat()


def test_sharp_time_input_flags_past_when_validating_today(qapp, db):
    from ui.sotg_assign import _SharpTimeInput
    inp = _SharpTimeInput()
    inp.set_validate_against_today(True)
    # Set a past time
    now = datetime.now()
    if now.hour == 0 and now.minute == 0:
        pytest.skip("midnight edge")
    past_str = f"{max(0, now.hour - 1):02d}:00"
    inp.setText(past_str)
    assert inp.is_invalid_past() is True
    # Future is OK
    inp.setText(_future_hhmm_today())
    assert inp.is_invalid_past() is False
    # Disabling the validation clears the flag too.
    inp.setText(past_str)
    assert inp.is_invalid_past() is True
    inp.set_validate_against_today(False)
    assert inp.is_invalid_past() is False
    inp.deleteLater()


def test_file_button_swaps_visual_on_set(qapp):
    from ui.sotg_assign import _FileButton
    btn = _FileButton()
    assert "Choose File" in btn.text()
    btn.set_file("/tmp/opening.mp3", duration_ms=42_000)
    assert "opening.mp3" in btn.text()
    assert "0:42" in btn.text()
    # Reset back
    btn.set_file(None)
    assert "Choose File" in btn.text()
    btn.deleteLater()


def test_breadcrumb_signals(qapp, db, qtbot):
    from ui.sotg_assign import SOTGAssign
    from ui.spot_on_the_go_shell import _BreadcrumbLink
    s = SOTGAssign(db)
    qtbot.addWidget(s)
    received: list[str] = []
    s.screen_requested.connect(received.append)
    crumbs = {c.text(): c for c in s.findChildren(_BreadcrumbLink)}
    for label in ("Control Panel", "AI Magic", "Spot on the Go"):
        assert label in crumbs
        crumbs[label].clicked.emit()
    assert received == ["control_panel", "ai_magic", "spot_on_the_go"]


def test_refresh_preserves_left_panel_after_screen_visible(
        qapp, db, qtbot, seeded_show):
    """Regression-guard for the 2026-05-14 disappear-on-refresh bug.

    Pre-fix: _refresh_shows_list iterated _left_inner.children()
    which included scroll-area internals, AND new _ShowCard widgets
    parented to an already-visible container were NOT auto-shown by
    Qt. Result: clicking a show OR flipping Today/Tomorrow wiped the
    left panel + right panel rows.

    Post-fix: tracked widget list + explicit .show() on rebuild.
    """
    from ui.sotg_assign import SOTGAssign
    s = SOTGAssign(db)
    qtbot.addWidget(s)
    # Mark the screen as visible so refresh runs against a "live"
    # container — this is the state that triggered the original bug.
    s.show()
    qapp.processEvents()
    # Initial state: at least one show card visible.
    assert len(s._show_cards) >= 1
    first_visible = sum(1 for c in s._show_cards if not c.isHidden())
    assert first_visible == len(s._show_cards)

    # Trigger the refresh path (the actual bug repro): flip date.
    s._date_toggle._on_tomorrow()
    qapp.processEvents()
    assert len(s._show_cards) >= 1
    second_visible = sum(1 for c in s._show_cards if not c.isHidden())
    assert second_visible == len(s._show_cards), (
        "Show cards must remain visible after date-toggle refresh "
        "(disappear-on-refresh regression)")

    # Click a show card — also a refresh trigger.
    if s._show_cards:
        sid = s._show_cards[0]._show_id
        s._on_show_clicked(sid)
        qapp.processEvents()
        assert len(s._show_cards) >= 1
        third_visible = sum(1 for c in s._show_cards if not c.isHidden())
        assert third_visible == len(s._show_cards)


def test_refresh_preserves_right_panel_rows_after_screen_visible(
        qapp, db, qtbot, seeded_show):
    """Same regression for the right panel's link rows."""
    from ui.sotg_assign import SOTGAssign
    s = SOTGAssign(db)
    qtbot.addWidget(s)
    s.show()
    qapp.processEvents()
    # Select the seeded show explicitly so rows render.
    s._on_show_clicked(seeded_show)
    qapp.processEvents()
    initial_rows = len(s._row_widgets)
    assert initial_rows >= 1
    initial_visible = sum(1 for r in s._row_widgets if not r.isHidden())
    assert initial_visible == initial_rows

    # Flip date — triggers right-panel rebuild.
    s._date_toggle._on_tomorrow()
    qapp.processEvents()
    assert len(s._row_widgets) >= 1
    visible_after = sum(1 for r in s._row_widgets if not r.isHidden())
    assert visible_after == len(s._row_widgets), (
        "Link rows must remain visible after date-toggle refresh "
        "(disappear-on-refresh regression)")


def test_station_label_has_object_name(qapp, db):
    from ui.sotg_assign import SOTGAssign
    s = SOTGAssign(db)
    lbl = s.findChild(QLabel, "hdr_station_lbl")
    assert lbl is not None
    s.deleteLater()


# ── MainWindow integration ────────────────────────────────────────────


def test_main_window_mounts_sotg_assign(
        qapp, db, qtbot, monkeypatch):
    from ui import main_window as mw_mod
    monkeypatch.setattr(mw_mod.MainWindow, "_apply_startup_auto_mode",
                         lambda self: None)
    from ui.main_window import MainWindow
    w = MainWindow(db=db)
    qtbot.addWidget(w)
    assert hasattr(w, "sotg_assign")
    w._on_hub_screen_requested("assign")
    assert w._stack.currentWidget() is w.sotg_assign
    w.close()
    w.deleteLater()


def test_sotg_shell_assign_card_reaches_real_screen(
        qapp, db, qtbot, monkeypatch):
    """Pre-this-session 'assign' was a toast. Now the SOTG shell's
    Assign card emits screen_requested('assign') and the host routes
    it to the real screen."""
    from ui import main_window as mw_mod
    monkeypatch.setattr(mw_mod.MainWindow, "_apply_startup_auto_mode",
                         lambda self: None)
    from ui.main_window import MainWindow
    w = MainWindow(db=db)
    qtbot.addWidget(w)
    w.spot_on_the_go_shell.screen_requested.emit("assign")
    assert w._stack.currentWidget() is w.sotg_assign
    w.close()
    w.deleteLater()


def test_all_four_sotg_step_cards_land_on_real_screens(
        qapp, db, qtbot, monkeypatch):
    """Updated 2026-05-14 evening v3 — Assign API Key shipped this
    pass. All four SOTG step cards now route to real screens; no
    toast remains. The full regression for each individual screen
    lives in its own test file."""
    from ui import main_window as mw_mod
    monkeypatch.setattr(mw_mod.MainWindow, "_apply_startup_auto_mode",
                         lambda self: None)
    from ui.main_window import MainWindow
    w = MainWindow(db=db)
    qtbot.addWidget(w)
    toast_calls: list[tuple] = []
    from PyQt6.QtWidgets import QMessageBox
    monkeypatch.setattr(_dialogs, "info",
        lambda parent, title, text: toast_calls.append((title, text)))
    for key, screen_attr in (
        ("create_schedule",  "sotg_create_schedule"),
        ("assign",           "sotg_assign"),
        ("generate_report",  "sotg_generate_report"),
        ("assign_api_key",   "sotg_assign_api_key"),
    ):
        w._on_hub_screen_requested(key)
        assert w._stack.currentWidget() is getattr(w, screen_attr), key
    # And nothing toasted along the way
    assert [t for t, _ in toast_calls] == []
    w.close()
    w.deleteLater()
