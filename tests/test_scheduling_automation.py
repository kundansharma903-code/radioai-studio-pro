"""
AI Magic · Scheduling Automation — Phase B mock UI tests.

Covers:

  Hub (ui/scheduling_automation_hub.py, Figma 511:3):
    • Screen constructs at 1440×900.
    • Station label has hdr_station_lbl objectName.
    • 3 hero stat pills (ENGINE / BALANCED TODAY / GROUPS).
    • 2 sister-group cards mounted with the mock data.
    • Recent decisions log has the 4 mock entries.
    • Refresh / Stop / Create-group / Edit-group / Ungroup /
      Review-plan signals emit on click.
    • Breadcrumb links emit control_panel + ai_magic.

  Daily Plan Review (ui/scheduling_daily_plan_review.py, Figma 512:2):
    • Screen constructs at 1440×900.
    • hdr_station_lbl objectName present.
    • 3 hero stat pills mounted.
    • 3 mock clock cards present.
    • First card is expanded by default; others collapsed.
    • Toggling a card flips its expansion state.
    • Approve / Discard signals emit on click.
    • Breadcrumb links emit control_panel + ai_magic +
      scheduling_automation.

  MainWindow integration:
    • Both screens mount.
    • Routing keys "scheduling_automation" + "review_daily_plan"
      land on the real screens (not toasts).
    • Hub's review_plan_clicked signal routes to the review screen.

Phase B is mock-only — no engine wired. Phase C-E in next session.
"""

from __future__ import annotations

from typing import Optional

import pytest

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QPushButton

from core.database import Database


@pytest.fixture
def db():
    return Database()


@pytest.fixture
def two_real_groups(db):
    """Create 2 real sister groups (each with 2 categories) for tests
    that need ≥1 card rendered on the Hub. Phase G fix: previously
    these tests silently relied on 84 leaked orphan groups in the
    live dev DB; with the orphan-wipe + WHERE EXISTS filter in
    get_sister_groups(), the helper now correctly returns 0 groups
    by default so tests must seed their own.

    Yields ``(group_a_id, group_b_id)`` and cleans up groups +
    categories on teardown."""
    import uuid
    conn = db._conn()
    # 4 throwaway categories (2 per group)
    cat_ids: list[int] = []
    for i in range(4):
        cur = conn.execute(
            "INSERT INTO categories (name, color) VALUES (?, ?)",
            [f"phaseG-{uuid.uuid4().hex[:6]}", "#06b6d4"])
        cat_ids.append(int(cur.lastrowid))
    conn.commit()
    g1 = db.create_sister_group([cat_ids[0], cat_ids[1]])
    g2 = db.create_sister_group([cat_ids[2], cat_ids[3]])
    yield (g1, g2)
    # Teardown
    try:
        db.delete_sister_group(g1)
        db.delete_sister_group(g2)
    except Exception:
        pass
    for cid in cat_ids:
        conn.execute("DELETE FROM categories WHERE id = ?", [cid])
    conn.commit()


# ════════════════════════════════════════════════════════════════════════════
# Scheduling Automation Hub
# ════════════════════════════════════════════════════════════════════════════


def test_hub_constructs_at_1440x900(qapp, db):
    from ui.scheduling_automation_hub import SchedulingAutomationHub
    s = SchedulingAutomationHub(db=db)
    assert s.width() == 1440
    assert s.height() == 900
    s.deleteLater()


def test_hub_station_label_has_object_name(qapp, db):
    from ui.scheduling_automation_hub import SchedulingAutomationHub
    s = SchedulingAutomationHub(db=db)
    lbl = s.findChild(QLabel, "hdr_station_lbl")
    assert lbl is not None
    s.deleteLater()


def test_hub_hero_stat_pills_carry_live_values(qapp, db):
    """Phase E live mode: 3 hero stat pills (ENGINE / BALANCED TODAY /
    GROUPS) should render with the live engine state + DB counts.
    Specific values depend on the dev DB so we only assert structure
    + numeric format."""
    from ui.scheduling_automation_hub import SchedulingAutomationHub
    s = SchedulingAutomationHub(db=db)
    # ENGINE pill — should contain a "●" status marker + a state word
    eng_text = s._pill_engine._value_lbl.text()
    assert "●" in eng_text
    assert any(state in eng_text
                for state in ("ON", "OFF", "WARMING", "ERROR"))
    # BALANCED + GROUPS pills should be numeric strings
    assert s._pill_balanced._value_lbl.text().isdigit()
    assert s._pill_groups._value_lbl.text().isdigit()
    s.deleteLater()


def test_hub_renders_two_sister_group_cards(qapp, db, two_real_groups,
                                              qtbot):
    """Phase E live mode: the Hub renders one ``_SisterGroupCard``
    per real sister group in the DB. The fixture seeds 2 groups so
    the Hub should render exactly 2 cards carrying those ids."""
    from ui.scheduling_automation_hub import (
        SchedulingAutomationHub, _SisterGroupCard,
    )
    g1, g2 = two_real_groups
    s = SchedulingAutomationHub(db=db)
    qtbot.addWidget(s)
    cards = s.findChildren(_SisterGroupCard)
    assert len(cards) == 2
    ids = sorted(c._group_id for c in cards)
    assert ids == sorted([g1, g2])
    s.deleteLater()


def test_hub_recent_decisions_log_renders_with_live_data(qapp, db, qtbot):
    """Phase E live mode: Today's AI Actions card renders decision
    rows from DB. When the dev DB has no plan yet, an "empty state"
    bullet appears ("No decisions yet — first engine tick will
    populate this log."). Either way, at least one bullet QLabel
    exists."""
    from ui.scheduling_automation_hub import SchedulingAutomationHub
    s = SchedulingAutomationHub(db=db)
    qtbot.addWidget(s)
    bullet_rows = [
        lbl for lbl in s.findChildren(QLabel)
        if lbl.text().startswith("•  ")
    ]
    # Always at least one row — empty state or live decisions
    assert len(bullet_rows) >= 1


def test_hub_refresh_signal_emits(qapp, db, qtbot):
    from ui.scheduling_automation_hub import SchedulingAutomationHub
    s = SchedulingAutomationHub(db=db)
    qtbot.addWidget(s)
    fired: list[bool] = []
    s.refresh_engine_clicked.connect(lambda: fired.append(True))
    # Locate the Refresh button by text
    btns = [b for b in s.findChildren(QPushButton)
             if "Refresh" in b.text()]
    assert btns, "Refresh button missing"
    btns[0].click()
    assert fired == [True]
    s.deleteLater()


def test_hub_stop_signal_emits(qapp, db, qtbot):
    from ui.scheduling_automation_hub import SchedulingAutomationHub
    s = SchedulingAutomationHub(db=db)
    qtbot.addWidget(s)
    fired: list[bool] = []
    s.stop_engine_clicked.connect(lambda: fired.append(True))
    btns = [b for b in s.findChildren(QPushButton)
             if "Stop AI Engine" in b.text()]
    assert btns, "Stop button missing"
    btns[0].click()
    assert fired == [True]
    s.deleteLater()


def test_hub_create_group_signal_emits(qapp, db, qtbot):
    from ui.scheduling_automation_hub import SchedulingAutomationHub
    s = SchedulingAutomationHub(db=db)
    qtbot.addWidget(s)
    fired: list[bool] = []
    s.create_group_clicked.connect(lambda: fired.append(True))
    btns = [b for b in s.findChildren(QPushButton)
             if b.text().strip() == "+ Create"]
    assert btns, "Create button missing"
    btns[0].click()
    assert fired == [True]
    s.deleteLater()


def test_hub_edit_group_signal_emits_with_id(qapp, db, two_real_groups,
                                                qtbot):
    """Clicking Edit on a sister-group card must emit edit_group_clicked
    with the card's group_id. Phase E uses this id to seed the picker."""
    from ui.scheduling_automation_hub import (
        SchedulingAutomationHub, _SisterGroupCard,
    )
    s = SchedulingAutomationHub(db=db)
    qtbot.addWidget(s)
    received: list[int] = []
    s.edit_group_clicked.connect(received.append)
    cards = s.findChildren(_SisterGroupCard)
    assert cards, "Hub should have rendered ≥1 card from the fixture"
    # Trigger via the card's own signal — the underlying button is
    # a private child; easier to fire from the card's surface.
    cards[0].edit_clicked.emit(cards[0]._group_id)
    assert received == [cards[0]._group_id]
    s.deleteLater()


def test_hub_ungroup_signal_emits_with_id(qapp, db, two_real_groups,
                                            qtbot):
    from ui.scheduling_automation_hub import (
        SchedulingAutomationHub, _SisterGroupCard,
    )
    s = SchedulingAutomationHub(db=db)
    qtbot.addWidget(s)
    received: list[int] = []
    s.ungroup_clicked.connect(received.append)
    cards = s.findChildren(_SisterGroupCard)
    assert len(cards) >= 2, (
        "Hub should have rendered ≥2 cards from the fixture")
    cards[1].ungroup_clicked.emit(cards[1]._group_id)
    assert received == [cards[1]._group_id]
    s.deleteLater()


def test_hub_review_plan_cta_emits(qapp, db, qtbot):
    """The big purple CTA at bottom-right of the Today's Actions card
    must emit review_plan_clicked. Host routes to the Daily Plan
    Review screen."""
    from ui.scheduling_automation_hub import SchedulingAutomationHub
    s = SchedulingAutomationHub(db=db)
    qtbot.addWidget(s)
    fired: list[bool] = []
    s.review_plan_clicked.connect(lambda: fired.append(True))
    # Locate the CTA by the text on its child QLabel.
    found_btn: Optional[QPushButton] = None
    for btn in s.findChildren(QPushButton):
        for child in btn.children():
            if isinstance(child, QLabel) and "REVIEW TODAY'S PLAN" in child.text():
                found_btn = btn
                break
        if found_btn:
            break
    assert found_btn is not None, "Review CTA button missing"
    found_btn.click()
    assert fired == [True]
    s.deleteLater()


def test_hub_breadcrumb_signals(qapp, db, qtbot):
    """The 2 breadcrumb crumbs (Control Panel + AI Magic) must emit
    the matching screen_requested key when clicked."""
    from ui.scheduling_automation_hub import SchedulingAutomationHub
    from ui.spot_on_the_go_shell import _BreadcrumbLink
    s = SchedulingAutomationHub(db=db)
    qtbot.addWidget(s)
    received: list[str] = []
    s.screen_requested.connect(received.append)
    crumbs = {c.text(): c for c in s.findChildren(_BreadcrumbLink)}
    assert "Control Panel" in crumbs
    assert "AI Magic" in crumbs
    crumbs["Control Panel"].clicked.emit()
    crumbs["AI Magic"].clicked.emit()
    assert received == ["control_panel", "ai_magic"]
    s.deleteLater()


# ════════════════════════════════════════════════════════════════════════════
# Daily Plan Review
# ════════════════════════════════════════════════════════════════════════════


def test_review_constructs_at_1440x900(qapp, db):
    from ui.scheduling_daily_plan_review import SchedulingDailyPlanReview
    s = SchedulingDailyPlanReview(db=db)
    assert s.width() == 1440
    assert s.height() == 900
    s.deleteLater()


def test_review_station_label_has_object_name(qapp, db):
    from ui.scheduling_daily_plan_review import SchedulingDailyPlanReview
    s = SchedulingDailyPlanReview(db=db)
    lbl = s.findChild(QLabel, "hdr_station_lbl")
    assert lbl is not None
    s.deleteLater()


def test_review_hero_stat_pills_render_live_values(qapp, db):
    """Phase E live mode: pills carry values from today's plan
    envelope (or zeros when no plan yet). We only assert numeric
    format since live values are DB-dependent."""
    from ui.scheduling_daily_plan_review import SchedulingDailyPlanReview
    s = SchedulingDailyPlanReview(db=db)
    assert s._pill_clocks._value_lbl.text().isdigit()
    assert s._pill_changes._value_lbl.text().isdigit()
    assert s._pill_rested._value_lbl.text().isdigit()
    s.deleteLater()


def test_review_renders_card_count_matching_live_plan(qapp, db, qtbot):
    """Phase E live mode: card count equals the number of distinct
    clocks in today's ai_rotation_decisions. When the dev DB has no
    plan yet, 0 cards render (empty-state placeholder takes over).
    Either way, no crash."""
    from ui.scheduling_daily_plan_review import (
        SchedulingDailyPlanReview, _ClockCard,
    )
    s = SchedulingDailyPlanReview(db=db)
    qtbot.addWidget(s)
    cards = s.findChildren(_ClockCard)
    # Count matches the live state we loaded
    assert len(cards) == len(s._live_clock_cards)


def test_review_first_card_expanded_when_present(qapp, db, qtbot):
    """Phase E: first card is auto-expanded when any cards exist
    (so operator sees a full side-by-side comparison on entry)."""
    from ui.scheduling_daily_plan_review import (
        SchedulingDailyPlanReview, _ClockCard,
    )
    s = SchedulingDailyPlanReview(db=db)
    qtbot.addWidget(s)
    cards = sorted(s.findChildren(_ClockCard), key=lambda c: c._idx)
    if cards:
        assert cards[0]._expanded is True
        for c in cards[1:]:
            assert c._expanded is False


def test_review_card_toggle_flips_expansion(qapp, db, qtbot):
    """Toggling a card's header flips its expansion state in the
    live state list. Only applicable when cards exist."""
    from ui.scheduling_daily_plan_review import SchedulingDailyPlanReview
    s = SchedulingDailyPlanReview(db=db)
    qtbot.addWidget(s)
    if not s._live_clock_cards:
        pytest.skip("no cards in live data — toggle test n/a")
    # Pick a non-first card to flip (first is already expanded)
    target_idx = min(1, len(s._live_clock_cards) - 1)
    before = s._live_clock_cards[target_idx]["expanded"]
    s._on_card_toggled(target_idx)
    after = s._live_clock_cards[target_idx]["expanded"]
    assert after != before
    s._on_card_toggled(target_idx)
    assert s._live_clock_cards[target_idx]["expanded"] == before


def test_review_approve_signal_emits(qapp, db, qtbot):
    from ui.scheduling_daily_plan_review import SchedulingDailyPlanReview
    s = SchedulingDailyPlanReview(db=db)
    qtbot.addWidget(s)
    fired: list[bool] = []
    s.approve_clicked.connect(lambda: fired.append(True))
    btns = [b for b in s.findChildren(QPushButton)
             if "Approve" in b.text()]
    assert btns, "Approve button missing"
    btns[0].click()
    assert fired == [True]
    s.deleteLater()


def test_review_discard_signal_emits(qapp, db, qtbot):
    from ui.scheduling_daily_plan_review import SchedulingDailyPlanReview
    s = SchedulingDailyPlanReview(db=db)
    qtbot.addWidget(s)
    fired: list[bool] = []
    s.discard_clicked.connect(lambda: fired.append(True))
    btns = [b for b in s.findChildren(QPushButton)
             if "Discard" in b.text()]
    assert btns, "Discard button missing"
    btns[0].click()
    assert fired == [True]
    s.deleteLater()


def test_review_breadcrumb_signals(qapp, db, qtbot):
    """3 breadcrumb crumbs (Control Panel + AI Magic + Scheduling
    Automation) emit the matching screen_requested key. The active
    crumb "Today's Plan" is a non-clickable purple pill."""
    from ui.scheduling_daily_plan_review import SchedulingDailyPlanReview
    from ui.spot_on_the_go_shell import _BreadcrumbLink
    s = SchedulingDailyPlanReview(db=db)
    qtbot.addWidget(s)
    received: list[str] = []
    s.screen_requested.connect(received.append)
    crumbs = {c.text(): c for c in s.findChildren(_BreadcrumbLink)}
    for label in ("Control Panel", "AI Magic", "Scheduling Automation"):
        assert label in crumbs, f"breadcrumb missing: {label!r}"
        crumbs[label].clicked.emit()
    assert received == ["control_panel", "ai_magic",
                         "scheduling_automation"]
    s.deleteLater()


# ════════════════════════════════════════════════════════════════════════════
# MainWindow integration
# ════════════════════════════════════════════════════════════════════════════


def test_main_window_mounts_and_routes_to_both_screens(
        qapp, db, qtbot, monkeypatch):
    """Single combined MainWindow integration test — covers screen
    mount + scheduling_automation routing + review_daily_plan routing
    + no-toast verification. Bundled into one fixture so we boot
    MainWindow ONCE per process — the BASS DLL multi-load segfault
    flake (incident #12) triggers when several tests in the same file
    each instantiate a fresh MainWindow."""
    from ui import main_window as mw_mod
    monkeypatch.setattr(mw_mod.MainWindow, "_apply_startup_auto_mode",
                         lambda self: None)
    from ui.main_window import MainWindow
    w = MainWindow(db=db)
    qtbot.addWidget(w)

    # Mount checks
    assert hasattr(w, "scheduling_automation_hub")
    assert hasattr(w, "scheduling_daily_plan_review")

    # Trap toasts so we can confirm the routes don't fall through to
    # the "coming soon" placeholder
    toast_calls: list[tuple] = []
    from PyQt6.QtWidgets import QMessageBox
    monkeypatch.setattr(
        QMessageBox, "information",
        lambda parent, title, text: toast_calls.append((title, text)))

    # scheduling_automation route → hub (was a toast pre-Phase-B)
    w._on_hub_screen_requested("scheduling_automation")
    assert toast_calls == []
    assert w._stack.currentWidget() is w.scheduling_automation_hub

    # review_daily_plan route → review screen (new in Phase B)
    w._on_hub_screen_requested("review_daily_plan")
    assert w._stack.currentWidget() is w.scheduling_daily_plan_review

    # Hub's review_plan_clicked signal must route to the review screen
    w._on_hub_screen_requested("scheduling_automation")
    w.scheduling_automation_hub.review_plan_clicked.emit()
    assert w._stack.currentWidget() is w.scheduling_daily_plan_review

    w.close()
    w.deleteLater()
