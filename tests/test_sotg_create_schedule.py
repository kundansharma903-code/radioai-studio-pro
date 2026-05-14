"""
SOTG · Create Schedule screen + DB helpers tests (Figma 469:3).

Pinned behaviour:

DB helpers (core/database.py):
  • create_sotg_show inserts header + N link rows atomically.
  • update_sotg_show replaces every field + rebuilds link rows.
  • delete_sotg_show cascades to links via ON DELETE CASCADE.
  • get_sotg_shows lists with link_count joined, sorted by time_start.
  • get_sotg_show returns the show + nested links, or None.
  • Validation: empty rj/show name, invalid days, invalid HH:MM, link
    count out of [1, 12] all raise.

Screen (ui/sotg_create_schedule.py):
  • SOTGCreateSchedule constructs at 1440×900.
  • _LinkRow auto-shrinks box width per count (1..9 = 132w,
    10..12 = ~98w with slim pill).
  • Time-envelope handles overnight wraparound (22:00 → 02:00 = 4h).
  • Breadcrumbs emit "control_panel", "ai_magic", "spot_on_the_go".
  • Edit flow: load show into form, button text flips to Update,
    Cancel button shows.
  • Station label has hdr_station_lbl.

MainWindow integration:
  • SOTGCreateSchedule mounts.
  • "create_schedule" route lands on it.
  • SOTG shell's Create Schedule card reaches it via
    screen_requested signal.
"""

from __future__ import annotations

import uuid

import pytest

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel

from core.database import Database


@pytest.fixture
def db():
    return Database()


# Clean up any rows we create with a marker prefix so the dev DB
# doesn't grow unbounded across test runs.
@pytest.fixture
def cleanup_sotg(db):
    created_ids: list[int] = []
    yield created_ids
    conn = db._conn()
    for sid in created_ids:
        try:
            conn.execute("DELETE FROM sotg_shows WHERE id = ?", [sid])
        except Exception:
            pass
    conn.commit()


# ── DB helpers ─────────────────────────────────────────────────────────


def test_create_show_inserts_show_plus_links(db, cleanup_sotg):
    mk = f"test_{uuid.uuid4().hex[:6]}"
    sid = db.create_sotg_show(
        rj_name=f"RJ {mk}", show_name=f"Show {mk}", days="Daily",
        time_start="04:00", time_end="07:00", color="#06b6d4",
        description="seed", link_names=["Open", "Quote", "Close"])
    cleanup_sotg.append(sid)
    fetched = db.get_sotg_show(sid)
    assert fetched is not None
    assert fetched["show_name"] == f"Show {mk}"
    assert fetched["rj_name"] == f"RJ {mk}"
    assert fetched["days"] == "Daily"
    assert fetched["time_start"] == "04:00"
    assert fetched["time_end"] == "07:00"
    assert fetched["color"] == "#06b6d4"
    assert len(fetched["links"]) == 3
    assert [l["link_name"] for l in fetched["links"]] == [
        "Open", "Quote", "Close"]


def test_update_show_replaces_fields_and_rebuilds_links(db, cleanup_sotg):
    sid = db.create_sotg_show(
        rj_name="A", show_name="A", days="Daily",
        time_start="04:00", time_end="05:00", color="#06b6d4",
        description="", link_names=["L1", "L2"])
    cleanup_sotg.append(sid)
    db.update_sotg_show(
        sid, rj_name="B", show_name="B Updated", days="Weekdays",
        time_start="09:00", time_end="11:00", color="#8b5cf6",
        description="new desc", link_names=["X", "Y", "Z", "W"])
    s2 = db.get_sotg_show(sid)
    assert s2["rj_name"] == "B"
    assert s2["show_name"] == "B Updated"
    assert s2["days"] == "Weekdays"
    assert s2["color"] == "#8b5cf6"
    assert len(s2["links"]) == 4
    assert [l["link_name"] for l in s2["links"]] == ["X", "Y", "Z", "W"]


def test_delete_show_cascades_to_links(db, cleanup_sotg):
    sid = db.create_sotg_show(
        rj_name="A", show_name="Doomed", days="Daily",
        time_start="04:00", time_end="05:00", color="#06b6d4",
        description="", link_names=["A", "B"])
    # Don't add to cleanup; we delete here.
    db.delete_sotg_show(sid)
    assert db.get_sotg_show(sid) is None
    # Links row also gone via ON DELETE CASCADE
    rows = db._conn().execute(
        "SELECT COUNT(*) FROM sotg_links WHERE show_id = ?",
        [sid]).fetchone()
    assert int(rows[0]) == 0


def test_get_sotg_shows_lists_with_link_count_ordered_by_time(
        db, cleanup_sotg):
    sid_a = db.create_sotg_show(
        rj_name="A", show_name="Show A", days="Daily",
        time_start="06:00", time_end="07:00", color="#06b6d4",
        description="", link_names=["1", "2", "3"])
    cleanup_sotg.append(sid_a)
    sid_b = db.create_sotg_show(
        rj_name="B", show_name="Show B", days="Daily",
        time_start="04:00", time_end="05:00", color="#8b5cf6",
        description="", link_names=["1", "2"])
    cleanup_sotg.append(sid_b)
    shows = db.get_sotg_shows()
    ids_in_order = [s["id"] for s in shows
                    if s["id"] in (sid_a, sid_b)]
    # B (04:00) should come before A (06:00) — ordered by time_start
    assert ids_in_order == [sid_b, sid_a]
    by_id = {s["id"]: s for s in shows}
    assert by_id[sid_a]["link_count"] == 3
    assert by_id[sid_b]["link_count"] == 2


def test_create_rejects_invalid_days(db):
    with pytest.raises(ValueError):
        db.create_sotg_show(
            rj_name="A", show_name="A", days="Holidays",
            time_start="04:00", time_end="05:00", color="#06b6d4",
            description="", link_names=["L"])


def test_create_rejects_invalid_time(db):
    with pytest.raises(ValueError):
        db.create_sotg_show(
            rj_name="A", show_name="A", days="Daily",
            time_start="4am", time_end="05:00", color="#06b6d4",
            description="", link_names=["L"])


def test_create_rejects_link_count_out_of_range(db):
    with pytest.raises(ValueError):
        db.create_sotg_show(
            rj_name="A", show_name="A", days="Daily",
            time_start="04:00", time_end="05:00", color="#06b6d4",
            description="", link_names=[])  # zero links
    with pytest.raises(ValueError):
        db.create_sotg_show(
            rj_name="A", show_name="A", days="Daily",
            time_start="04:00", time_end="05:00", color="#06b6d4",
            description="", link_names=[f"L{i}" for i in range(13)])


def test_create_rejects_blank_name(db):
    with pytest.raises(ValueError):
        db.create_sotg_show(
            rj_name="", show_name="X", days="Daily",
            time_start="04:00", time_end="05:00", color="#06b6d4",
            description="", link_names=["L"])
    with pytest.raises(ValueError):
        db.create_sotg_show(
            rj_name="X", show_name="  ", days="Daily",
            time_start="04:00", time_end="05:00", color="#06b6d4",
            description="", link_names=["L"])


# ── Screen smoke ───────────────────────────────────────────────────────


def test_construction_does_not_crash(qapp, db):
    from ui.sotg_create_schedule import SOTGCreateSchedule
    s = SOTGCreateSchedule(db)
    assert s.size().width() == 1440
    assert s.size().height() == 900
    s.deleteLater()


def test_link_row_count_clamps_and_widths_shrink(qapp, db):
    from ui.sotg_create_schedule import SOTGCreateSchedule, _LinkRow
    s = SOTGCreateSchedule(db)
    row: _LinkRow = s._link_row
    # 9 → 132w boxes
    row.set_count(9)
    assert row.count() == 9
    assert row._boxes[0].width() == 132
    # 12 → ~98w boxes
    row.set_count(12)
    assert row.count() == 12
    assert 90 <= row._boxes[0].width() <= 105
    # 13 clamps to 12
    row.set_count(13)
    assert row.count() == 12
    # 0 clamps to 1
    row.set_count(0)
    assert row.count() == 1
    s.deleteLater()


def test_envelope_minutes_handles_overnight_wraparound(qapp, db):
    from ui.sotg_create_schedule import SOTGCreateSchedule
    s = SOTGCreateSchedule(db)
    s._time_start.setText("22:00")
    s._time_end.setText("02:00")
    assert s._envelope_minutes() == 4 * 60
    s._time_start.setText("04:00")
    s._time_end.setText("07:00")
    assert s._envelope_minutes() == 3 * 60
    s.deleteLater()


def test_envelope_returns_none_for_invalid_time(qapp, db):
    from ui.sotg_create_schedule import SOTGCreateSchedule
    s = SOTGCreateSchedule(db)
    s._time_start.setText("4am")
    s._time_end.setText("--:--")
    assert s._envelope_minutes() is None
    s.deleteLater()


def test_breadcrumb_signals_emit_expected_keys(qapp, db, qtbot):
    from ui.sotg_create_schedule import SOTGCreateSchedule
    from ui.spot_on_the_go_shell import _BreadcrumbLink
    s = SOTGCreateSchedule(db)
    qtbot.addWidget(s)
    received: list[str] = []
    s.screen_requested.connect(received.append)
    crumbs = {c.text(): c for c in s.findChildren(_BreadcrumbLink)}
    assert "Control Panel" in crumbs
    assert "AI Magic" in crumbs
    assert "Spot on the Go" in crumbs
    crumbs["Control Panel"].clicked.emit()
    crumbs["AI Magic"].clicked.emit()
    crumbs["Spot on the Go"].clicked.emit()
    assert received == ["control_panel", "ai_magic", "spot_on_the_go"]


def test_refresh_updates_hero_pills_without_corruption(
        qapp, db, qtbot, cleanup_sotg):
    """Regression-guard: _refresh_saved_shows used to call
    findChild(QLabel).setParent(None) which detached a child from
    each hero pill on every refresh, eventually crashing the live
    app (exit-127 on 2026-05-14). New approach captures the label
    once + uses setText. Verify multiple refreshes work and the
    counters reflect actual DB state."""
    from ui.sotg_create_schedule import SOTGCreateSchedule
    s = SOTGCreateSchedule(db)
    qtbot.addWidget(s)
    # First refresh — pulls existing DB shows (may be > 0 from
    # other tests' leftovers if cleanup was skipped; use exact match
    # via newly-created seed).
    sid = db.create_sotg_show(
        rj_name="A", show_name="HeroPillTest", days="Daily",
        time_start="04:00", time_end="05:00", color="#06b6d4",
        description="", link_names=["X", "Y", "Z"])
    cleanup_sotg.append(sid)
    s._refresh_saved_shows()
    txt1 = s._pill_shows_label.text()
    assert " SHOWS SAVED" in txt1
    # Refresh again — labels must still be intact + updatable.
    s._refresh_saved_shows()
    txt2 = s._pill_shows_label.text()
    assert txt2 == txt1
    # Delete the seeded row + refresh — counter must drop by exactly 1.
    n_before = int(txt1.split()[0])
    db.delete_sotg_show(sid)
    cleanup_sotg.remove(sid)
    s._refresh_saved_shows()
    n_after = int(s._pill_shows_label.text().split()[0])
    assert n_after == n_before - 1
    # Inner label must still be a live child of the pill (no detach)
    assert s._pill_shows_label.parent() is s._pill_shows


def test_station_label_has_object_name(qapp, db):
    from ui.sotg_create_schedule import SOTGCreateSchedule
    s = SOTGCreateSchedule(db)
    lbl = s.findChild(QLabel, "hdr_station_lbl")
    assert lbl is not None
    s.deleteLater()


def test_edit_flow_loads_show_and_flips_ui(qapp, db, qtbot, cleanup_sotg):
    """Click-to-edit must populate the form, switch the submit button
    to 'Update', and reveal the Cancel button."""
    from ui.sotg_create_schedule import SOTGCreateSchedule
    sid = db.create_sotg_show(
        rj_name="RJ Edit", show_name="Editable Show", days="Weekends",
        time_start="14:00", time_end="16:00", color="#8b5cf6",
        description="for the edit-flow test",
        link_names=["A", "B", "C", "D"])
    cleanup_sotg.append(sid)
    s = SOTGCreateSchedule(db)
    qtbot.addWidget(s)
    s._refresh_saved_shows()
    s._on_edit(sid)
    assert s._editing_id == sid
    assert s._rj_name.text() == "RJ Edit"
    assert s._show_name.text() == "Editable Show"
    assert s._days.currentText() == "Weekends"
    assert s._time_start.text() == "14:00"
    assert s._time_end.text() == "16:00"
    assert s._color_picker.selected() == "#8b5cf6"
    assert s._link_count.value() == 4
    assert s._link_row.count() == 4
    assert "Update" in s._btn_create.text()
    # In headless tests the screen widget isn't shown, so isVisible()
    # returns False even after .show() — use isHidden() which only
    # tracks the explicit hide()/show() call.
    assert not s._btn_cancel.isHidden()
    # Cancel flips it back
    s._on_cancel_edit()
    assert s._editing_id is None
    assert "Create" in s._btn_create.text()
    assert s._btn_cancel.isHidden()


# ── MainWindow integration ────────────────────────────────────────────


def test_main_window_mounts_sotg_create_schedule(
        qapp, db, qtbot, monkeypatch):
    from ui import main_window as mw_mod
    monkeypatch.setattr(mw_mod.MainWindow, "_apply_startup_auto_mode",
                         lambda self: None)
    from ui.main_window import MainWindow
    w = MainWindow(db=db)
    qtbot.addWidget(w)
    assert hasattr(w, "sotg_create_schedule")
    w._on_hub_screen_requested("create_schedule")
    assert w._stack.currentWidget() is w.sotg_create_schedule
    w.close()
    w.deleteLater()


def test_sotg_shell_card_routes_to_create_schedule(
        qapp, db, qtbot, monkeypatch):
    """SOTG shell's 'Create Schedule' card emits
    screen_requested('create_schedule') — verify the host now routes
    it to the new screen instead of the previous toast."""
    from ui import main_window as mw_mod
    monkeypatch.setattr(mw_mod.MainWindow, "_apply_startup_auto_mode",
                         lambda self: None)
    from ui.main_window import MainWindow
    w = MainWindow(db=db)
    qtbot.addWidget(w)
    w.spot_on_the_go_shell.screen_requested.emit("create_schedule")
    assert w._stack.currentWidget() is w.sotg_create_schedule
    w.close()
    w.deleteLater()


def test_only_assign_api_key_card_still_toasts(
        qapp, db, qtbot, monkeypatch):
    """Updated 2026-05-14 evening — three of the four SOTG step cards
    are now real screens (Create Schedule, Assign, Generate Report).
    Only Assign API Key remains a placeholder toast until that
    screen ships in a follow-up session.

    Original assertion (3 toasts incl. Assign) was already stale at
    HEAD `859ba7b` — Assign shipped in that commit but this test
    file was not synced; corrected together with the Generate Report
    landing."""
    from ui import main_window as mw_mod
    monkeypatch.setattr(mw_mod.MainWindow, "_apply_startup_auto_mode",
                         lambda self: None)
    from ui.main_window import MainWindow
    w = MainWindow(db=db)
    qtbot.addWidget(w)
    toast_calls: list[tuple] = []
    from PyQt6.QtWidgets import QMessageBox
    monkeypatch.setattr(
        QMessageBox, "information",
        lambda parent, title, text: toast_calls.append((title, text)))
    w._on_hub_screen_requested("assign_api_key")
    titles = [t for t, _ in toast_calls]
    assert titles == ["Assign API Key"]
    w.close()
    w.deleteLater()
