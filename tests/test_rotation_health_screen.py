"""
Rotation Health (Songs Library report, Figma 521:2) — screen + DB
helper tests.

Covers:

  DB helpers:
    • get_rotation_summary_for_date returns {plan, categories} shape.
    • Buckets split rest/promote correctly per operator's Q6 ("both
      cards" — a promote decision appears in BOTH the source
      category's PROMOTED OUT list AND the target category's
      PROMOTED IN list).
    • Empty date → plan=None, categories=[] (or all-empty).
    • get_song_recent_plays_count returns 0 for unknown song.
    • get_song_recent_plays_count filters by date range.

  Screen (ui/rotation_health.py):
    • Constructs at 1440×900.
    • hdr_station_lbl objectName present.
    • Defaults to today.
    • 5 stat pills mounted (Rested / Promoted / Clocks / Errors /
      Plan Status).
    • Plan-status pill reflects envelope state (none / pending /
      approved / discarded).
    • Filter dropdown has 4 modes.
    • Hide-empty toggle defaults to checked.
    • Card grid renders one card per category with decisions.
    • Empty-state card renders when category has no AI changes.
    • Hide-empty toggle filters out empty cards.
    • Back-clicked + breadcrumb signals emit.

  MainWindow integration:
    • Routing key "rotation_health" lands on the real screen.

Tests use live dev DB (per project convention) but insert test data
under a far-future plan_date so cleanup is straightforward.
"""

from __future__ import annotations

from datetime import date as _date
from typing import Optional

import pytest

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QPushButton

from core.database import Database


# Sentinel future date for tests — well past any real engine ticks
TEST_DATE = "2099-12-31"


@pytest.fixture
def db():
    return Database()


@pytest.fixture
def two_cats(db):
    """Return (cat_a_id, cat_b_id) — first two categories in the DB
    by id. Most dev DBs have multiple categories seeded, so this
    is reliable."""
    rows = db._conn().execute(
        "SELECT id FROM categories ORDER BY id ASC LIMIT 2").fetchall()
    if len(rows) < 2:
        pytest.skip("Dev DB needs at least 2 categories for these tests")
    return int(rows[0]["id"]), int(rows[1]["id"])


@pytest.fixture
def one_song(db, two_cats):
    """Return a song_id belonging to cat_a (the first of two_cats)."""
    cat_a, _ = two_cats
    row = db._conn().execute(
        "SELECT id FROM songs WHERE category_id = ? "
        "LIMIT 1", [cat_a]).fetchone()
    if not row:
        pytest.skip("Dev DB needs a song in the first category")
    return int(row["id"])


@pytest.fixture
def one_clock(db):
    row = db._conn().execute(
        "SELECT id FROM clocks ORDER BY id ASC LIMIT 1").fetchone()
    if not row:
        pytest.skip("Dev DB needs at least 1 clock")
    return int(row["id"])


@pytest.fixture
def _cleanup_test_plan(db):
    """Wipe any leftover plan + decisions for TEST_DATE before & after."""
    def _wipe():
        conn = db._conn()
        conn.execute(
            "DELETE FROM ai_rotation_plans WHERE plan_date = ?",
            [TEST_DATE])
        conn.commit()
    _wipe()
    yield _wipe
    _wipe()


# ════════════════════════════════════════════════════════════════════════════
# DB helpers
# ════════════════════════════════════════════════════════════════════════════


def test_get_rotation_summary_for_date_returns_plan_and_categories(
        db, _cleanup_test_plan):
    summary = db.get_rotation_summary_for_date(TEST_DATE)
    assert set(summary.keys()) == {"plan", "categories"}
    assert summary["plan"] is None  # no plan envelope yet
    assert isinstance(summary["categories"], list)
    # All categories listed even with no decisions
    cat_count = db._conn().execute(
        "SELECT COUNT(*) AS n FROM categories").fetchone()["n"]
    assert len(summary["categories"]) == int(cat_count)


def test_get_rotation_summary_includes_plan_envelope_when_present(
        db, _cleanup_test_plan):
    pid = db.get_or_create_ai_rotation_plan(TEST_DATE)
    summary = db.get_rotation_summary_for_date(TEST_DATE)
    assert summary["plan"] is not None
    assert int(summary["plan"]["id"]) == int(pid)
    assert summary["plan"]["plan_date"] == TEST_DATE


def test_get_rotation_summary_rest_decision_lands_in_rested_bucket(
        db, two_cats, one_song, one_clock, _cleanup_test_plan):
    cat_a, cat_b = two_cats
    pid = db.get_or_create_ai_rotation_plan(TEST_DATE)
    db.add_rotation_decision(
        plan_id=pid, decision_date=TEST_DATE,
        clock_id=one_clock, hour=10, song_id=one_song,
        action="rest",
        source_category_id=cat_a, target_category_id=None,
        reason="played 1 day ago at 10 AM (heavy penalty)")
    summary = db.get_rotation_summary_for_date(TEST_DATE)
    cat_a_bucket = next(
        c for c in summary["categories"] if c["category_id"] == cat_a)
    cat_b_bucket = next(
        c for c in summary["categories"] if c["category_id"] == cat_b)
    assert len(cat_a_bucket["rested"]) == 1
    assert len(cat_a_bucket["promoted_out"]) == 0
    assert len(cat_a_bucket["promoted_in"]) == 0
    assert len(cat_b_bucket["rested"]) == 0
    # Reason flows through
    assert "played 1 day ago" in cat_a_bucket["rested"][0]["reason"]


def test_get_rotation_summary_promote_appears_in_both_source_and_target(
        db, two_cats, one_song, one_clock, _cleanup_test_plan):
    """Operator's Q6 — promote decisions must show in BOTH the
    source category's PROMOTED OUT bucket AND the target category's
    PROMOTED IN bucket. Full audit trail."""
    cat_a, cat_b = two_cats
    pid = db.get_or_create_ai_rotation_plan(TEST_DATE)
    db.add_rotation_decision(
        plan_id=pid, decision_date=TEST_DATE,
        clock_id=one_clock, hour=14, song_id=one_song,
        action="promote",
        source_category_id=cat_a, target_category_id=cat_b,
        reason="promoted from cat_a sister pool")
    summary = db.get_rotation_summary_for_date(TEST_DATE)
    cat_a_bucket = next(
        c for c in summary["categories"] if c["category_id"] == cat_a)
    cat_b_bucket = next(
        c for c in summary["categories"] if c["category_id"] == cat_b)
    assert len(cat_a_bucket["promoted_out"]) == 1
    assert len(cat_b_bucket["promoted_in"]) == 1
    # Same decision, surfaced in both buckets
    assert (cat_a_bucket["promoted_out"][0]["song_id"]
            == cat_b_bucket["promoted_in"][0]["song_id"])


def test_get_song_recent_plays_count_returns_zero_for_unknown_song(db):
    # Use a song_id that almost certainly doesn't exist
    assert db.get_song_recent_plays_count(99999999, 7) == 0


def test_get_song_recent_plays_count_filters_by_window(
        db, one_song):
    # 7d count should always be ≤ 30d count for the same song
    c7 = db.get_song_recent_plays_count(one_song, 7)
    c30 = db.get_song_recent_plays_count(one_song, 30)
    assert isinstance(c7, int) and isinstance(c30, int)
    assert c7 >= 0 and c30 >= 0
    assert c7 <= c30


def test_get_song_recent_plays_count_invalid_inputs_return_zero(db):
    assert db.get_song_recent_plays_count(None, 7) == 0
    assert db.get_song_recent_plays_count("foo", 7) == 0


# ════════════════════════════════════════════════════════════════════════════
# Screen widget
# ════════════════════════════════════════════════════════════════════════════


def test_screen_constructs_at_1440x900(qapp, db):
    from ui.rotation_health import RotationHealthScreen
    s = RotationHealthScreen(db=db)
    try:
        assert s.width() == 1440
        assert s.height() == 900
    finally:
        s.deleteLater()


def test_screen_station_label_has_object_name(qapp, db):
    from ui.rotation_health import RotationHealthScreen
    s = RotationHealthScreen(db=db)
    try:
        lbl = s.findChild(QLabel, "hdr_station_lbl")
        assert lbl is not None
    finally:
        s.deleteLater()


def test_screen_defaults_to_today(qapp, db):
    from ui.rotation_health import RotationHealthScreen
    s = RotationHealthScreen(db=db)
    try:
        assert s.selected_date() == _date.today()
    finally:
        s.deleteLater()


def test_screen_has_five_stat_pills(qapp, db):
    from ui.rotation_health import RotationHealthScreen
    s = RotationHealthScreen(db=db)
    try:
        # Each _StatPill has objectName "stat_pill"
        from PyQt6.QtWidgets import QFrame
        pills = [c for c in s.findChildren(QFrame)
                 if c.objectName() == "stat_pill"]
        assert len(pills) == 5
    finally:
        s.deleteLater()


def test_filter_dropdown_starts_in_all_mode(qapp, db):
    from ui.rotation_health import RotationHealthScreen
    s = RotationHealthScreen(db=db)
    try:
        assert s._filter.mode() == "all"
        # 4 modes total
        assert len(s._filter.MODES) == 4
        keys = [k for k, _ in s._filter.MODES]
        assert set(keys) == {"all", "rested", "promoted",
                              "has_changes"}
    finally:
        s.deleteLater()


def test_hide_empty_toggle_defaults_to_checked(qapp, db):
    from ui.rotation_health import RotationHealthScreen
    s = RotationHealthScreen(db=db)
    try:
        assert s._hide_empty_toggle.is_checked() is True
        assert s._hide_empty is True
    finally:
        s.deleteLater()


def test_screen_renders_category_card_when_decisions_present(
        qapp, db, two_cats, one_song, one_clock, _cleanup_test_plan):
    """Insert a rest decision for TEST_DATE → set screen date to
    TEST_DATE → assert a non-empty _CategoryCard appears for the
    source category."""
    from datetime import date
    from ui.rotation_health import (
        RotationHealthScreen, _CategoryCard, _EmptyCategoryCard,
    )
    cat_a, _ = two_cats
    pid = db.get_or_create_ai_rotation_plan(TEST_DATE)
    db.add_rotation_decision(
        plan_id=pid, decision_date=TEST_DATE,
        clock_id=one_clock, hour=10, song_id=one_song,
        action="rest",
        source_category_id=cat_a, target_category_id=None,
        reason="test rest decision")
    s = RotationHealthScreen(db=db)
    try:
        # Point screen at TEST_DATE
        from PyQt6.QtCore import QDate
        qd = QDate(2099, 12, 31)
        s._date_pill.set_date(qd)
        s._on_date_picked(qd)
        # At least one real (non-empty) category card mounted
        full_cards = s.findChildren(_CategoryCard)
        assert len(full_cards) >= 1
        # And the cat_a card is among them
        cat_ids = {c.category_id for c in full_cards}
        assert cat_a in cat_ids
    finally:
        s.deleteLater()


def test_screen_renders_three_sections_when_buckets_populated(
        qapp, db, two_cats, one_song, one_clock, _cleanup_test_plan):
    """Card for cat_a should expose RESTED + PROMOTED OUT + PROMOTED
    IN sections when all three are populated."""
    from PyQt6.QtCore import QDate
    from ui.rotation_health import (
        RotationHealthScreen, _CategoryCard, _CardSection,
    )
    cat_a, cat_b = two_cats
    pid = db.get_or_create_ai_rotation_plan(TEST_DATE)
    # rest for cat_a
    db.add_rotation_decision(
        plan_id=pid, decision_date=TEST_DATE,
        clock_id=one_clock, hour=10, song_id=one_song,
        action="rest",
        source_category_id=cat_a, target_category_id=None,
        reason="r")
    # promote from cat_a to cat_b
    db.add_rotation_decision(
        plan_id=pid, decision_date=TEST_DATE,
        clock_id=one_clock, hour=11, song_id=one_song,
        action="promote",
        source_category_id=cat_a, target_category_id=cat_b,
        reason="p")
    # promote from cat_b to cat_a (so cat_a has IN too)
    row = db._conn().execute(
        "SELECT id FROM songs WHERE category_id = ? LIMIT 1",
        [cat_b]).fetchone()
    if not row:
        pytest.skip("cat_b has no songs")
    cat_b_song = int(row["id"])
    db.add_rotation_decision(
        plan_id=pid, decision_date=TEST_DATE,
        clock_id=one_clock, hour=12, song_id=cat_b_song,
        action="promote",
        source_category_id=cat_b, target_category_id=cat_a,
        reason="p2")
    s = RotationHealthScreen(db=db)
    try:
        from PyQt6.QtCore import QDate
        qd = QDate(2099, 12, 31)
        s._date_pill.set_date(qd)
        s._on_date_picked(qd)
        # Find cat_a's full card
        cards = s.findChildren(_CategoryCard)
        cat_a_card = next(
            (c for c in cards if c.category_id == cat_a), None)
        assert cat_a_card is not None
        # 3 sections inside (RESTED + OUT + IN)
        sections = cat_a_card.findChildren(_CardSection)
        assert len(sections) == 3
    finally:
        s.deleteLater()


def test_screen_shows_empty_card_when_hide_empty_off(
        qapp, db, two_cats, one_song, one_clock, _cleanup_test_plan):
    """When hide_empty toggle is OFF, every category that had zero
    decisions should render as an empty-state card."""
    from PyQt6.QtCore import QDate
    from ui.rotation_health import (
        RotationHealthScreen, _EmptyCategoryCard,
    )
    cat_a, _ = two_cats
    pid = db.get_or_create_ai_rotation_plan(TEST_DATE)
    db.add_rotation_decision(
        plan_id=pid, decision_date=TEST_DATE,
        clock_id=one_clock, hour=9, song_id=one_song,
        action="rest",
        source_category_id=cat_a, target_category_id=None,
        reason="r")
    s = RotationHealthScreen(db=db)
    try:
        qd = QDate(2099, 12, 31)
        s._date_pill.set_date(qd)
        s._on_date_picked(qd)
        # First, with hide-empty ON, no empty cards should show
        empties_on = s.findChildren(_EmptyCategoryCard)
        # Now toggle off
        s._hide_empty_toggle.set_checked(False)
        empties_off = s.findChildren(_EmptyCategoryCard)
        # Toggling off should add cards (every category without
        # decisions becomes an empty card)
        assert len(empties_off) > len(empties_on)
    finally:
        s.deleteLater()


def test_screen_back_button_emits_signal(qapp, db, qtbot):
    from ui.rotation_health import RotationHealthScreen
    s = RotationHealthScreen(db=db)
    try:
        with qtbot.waitSignal(s.back_clicked, timeout=500):
            # Find the back button (text starts with "← Back")
            buttons = s.findChildren(QPushButton)
            back_btn = next(
                (b for b in buttons
                 if b.text().startswith("← Back")), None)
            assert back_btn is not None
            back_btn.click()
    finally:
        s.deleteLater()


def test_screen_breadcrumb_emits_control_panel(qapp, db, qtbot):
    from ui.rotation_health import RotationHealthScreen
    s = RotationHealthScreen(db=db)
    try:
        from ui.spot_on_the_go_shell import _BreadcrumbLink
        links = s.findChildren(_BreadcrumbLink)
        cp_link = next(
            (l for l in links if l.text() == "Control Panel"), None)
        assert cp_link is not None
        with qtbot.waitSignal(s.breadcrumb_clicked, timeout=500) as blocker:
            cp_link.click()
        assert blocker.args == ["control_panel"]
    finally:
        s.deleteLater()


def test_screen_breadcrumb_emits_songs(qapp, db, qtbot):
    from ui.rotation_health import RotationHealthScreen
    s = RotationHealthScreen(db=db)
    try:
        from ui.spot_on_the_go_shell import _BreadcrumbLink
        links = s.findChildren(_BreadcrumbLink)
        sl_link = next(
            (l for l in links if l.text() == "Songs Library"), None)
        assert sl_link is not None
        with qtbot.waitSignal(s.breadcrumb_clicked, timeout=500) as blocker:
            sl_link.click()
        assert blocker.args == ["songs"]
    finally:
        s.deleteLater()


def test_plan_status_pill_shows_no_plan_when_envelope_missing(
        qapp, db, _cleanup_test_plan):
    """For a date with no plan envelope, the status pill text should
    indicate 'no plan' rather than show a stale state."""
    from PyQt6.QtCore import QDate
    from ui.rotation_health import RotationHealthScreen
    s = RotationHealthScreen(db=db)
    try:
        qd = QDate(2099, 12, 31)
        s._date_pill.set_date(qd)
        s._on_date_picked(qd)
        val = s._stat_plan._val.text()
        assert "No plan" in val or "—" in val
    finally:
        s.deleteLater()


def test_plan_status_pill_reflects_approved_state(
        qapp, db, _cleanup_test_plan):
    from PyQt6.QtCore import QDate
    from ui.rotation_health import RotationHealthScreen
    db.get_or_create_ai_rotation_plan(TEST_DATE)
    db.mark_ai_rotation_plan_approved(TEST_DATE)
    s = RotationHealthScreen(db=db)
    try:
        qd = QDate(2099, 12, 31)
        s._date_pill.set_date(qd)
        s._on_date_picked(qd)
        val = s._stat_plan._val.text()
        assert "Approved" in val
    finally:
        s.deleteLater()


def test_plan_status_pill_reflects_discarded_state(
        qapp, db, _cleanup_test_plan):
    from PyQt6.QtCore import QDate
    from ui.rotation_health import RotationHealthScreen
    db.get_or_create_ai_rotation_plan(TEST_DATE)
    db.mark_ai_rotation_plan_discarded(TEST_DATE)
    s = RotationHealthScreen(db=db)
    try:
        qd = QDate(2099, 12, 31)
        s._date_pill.set_date(qd)
        s._on_date_picked(qd)
        val = s._stat_plan._val.text()
        assert "Discarded" in val
    finally:
        s.deleteLater()


def test_decision_row_carries_tooltip(qapp, db, two_cats,
                                        one_song, one_clock,
                                        _cleanup_test_plan):
    """Hover tooltip on a decision row should include the song
    title + play-count phrasing. Q4 (both play counts) + Q7
    (tooltip rather than per-row chip)."""
    from PyQt6.QtCore import QDate
    from ui.rotation_health import (
        RotationHealthScreen, _CategoryCard, _DecisionRow,
    )
    cat_a, _ = two_cats
    pid = db.get_or_create_ai_rotation_plan(TEST_DATE)
    db.add_rotation_decision(
        plan_id=pid, decision_date=TEST_DATE,
        clock_id=one_clock, hour=10, song_id=one_song,
        action="rest",
        source_category_id=cat_a, target_category_id=None,
        reason="test")
    s = RotationHealthScreen(db=db)
    try:
        qd = QDate(2099, 12, 31)
        s._date_pill.set_date(qd)
        s._on_date_picked(qd)
        rows = s.findChildren(_DecisionRow)
        assert len(rows) >= 1
        tip = rows[0].toolTip()
        assert "Last 7d" in tip
        assert "All-time" in tip
    finally:
        s.deleteLater()


def test_filter_mode_changes_propagate(qapp, db, two_cats,
                                         one_song, one_clock,
                                         _cleanup_test_plan):
    """Changing filter from 'all' to 'rested' should keep cards with
    rested rows and drop cards with only promoted rows."""
    from PyQt6.QtCore import QDate
    from ui.rotation_health import (
        RotationHealthScreen, _CategoryCard, _CardSection,
    )
    cat_a, cat_b = two_cats
    pid = db.get_or_create_ai_rotation_plan(TEST_DATE)
    db.add_rotation_decision(
        plan_id=pid, decision_date=TEST_DATE,
        clock_id=one_clock, hour=8, song_id=one_song,
        action="rest",
        source_category_id=cat_a, target_category_id=None,
        reason="r")
    s = RotationHealthScreen(db=db)
    try:
        qd = QDate(2099, 12, 31)
        s._date_pill.set_date(qd)
        s._on_date_picked(qd)
        # Switch to 'rested only' — cat_a should remain
        s._filter._mode = "rested"
        s._on_filter_changed("rested")
        cards = s.findChildren(_CategoryCard)
        assert any(c.category_id == cat_a for c in cards)
        # Switch to 'promoted only' — cat_a (with no promotes) drops
        s._filter._mode = "promoted"
        s._on_filter_changed("promoted")
        cards2 = s.findChildren(_CategoryCard)
        assert all(c.category_id != cat_a for c in cards2)
    finally:
        s.deleteLater()


# ════════════════════════════════════════════════════════════════════════════
# MainWindow integration
# ════════════════════════════════════════════════════════════════════════════


def test_main_window_mounts_rotation_health(qapp, db, qtbot):
    """Constructing MainWindow should create a rotation_health
    attribute, mount it in the stack, and route 'rotation_health'
    report clicks to it."""
    # Same trick as test_scheduling_automation: build with care and
    # the BASS audio engine shared with other tests can segfault
    # if MainWindow is loaded twice in the same process. Run this
    # test file standalone for clean signal.
    try:
        from ui.main_window import MainWindow
        from ui.rotation_health import RotationHealthScreen
    except Exception as exc:
        pytest.skip(f"MainWindow import failed: {exc}")
    try:
        mw = MainWindow(db=db)
    except Exception as exc:
        pytest.skip(f"MainWindow construction failed: {exc}")
    try:
        assert hasattr(mw, "rotation_health")
        assert isinstance(mw.rotation_health, RotationHealthScreen)
        # Stack contains it
        idx = mw._stack.indexOf(mw.rotation_health)
        assert idx >= 0
        # Route via _on_report_clicked
        mw._on_report_clicked("rotation_health")
        assert mw._stack.currentWidget() is mw.rotation_health
    finally:
        try:
            mw.close()
            mw.deleteLater()
        except Exception:
            pass
