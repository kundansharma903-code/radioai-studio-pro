"""
SOTG · Assign — the Save button actually saves (2026-10-13).

Operator: "Spot on the Go … when we assign the audio files and timing to
that show in Assign, the Save option does not work."

Evidence: the last row ever written to sotg_assignments was dated
2026-05-16; both shows created on 2026-07-25 had never had a single
assignment saved.

Root cause: _LinkRow re-evaluated Save only on _SharpTimeInput's
``invalid_changed`` signal, which fires when the "time is in the past"
flag FLIPS — not when the time text changes. So:

  • file → priority → typed a valid time  ⇒ Save stayed grey forever
  • cleared / half-typed the time         ⇒ Save stayed enabled and
    surfaced the DB's raw "sharp_time must be HH:MM 24h ('19:3')"

and a grey Save gave no hint of what was missing (priority is left
blank on purpose; today's auto-suggested times can already be past).

These tests drive the real row widgets in every input order and assert
the row lands in the database.
"""

from __future__ import annotations

import sys
import uuid
from datetime import date, datetime, timedelta

import pytest

from core.database import Database
from core import dialogs as _dialogs

_AUDIO = sys.executable          # any existing file — the DB never opens it


@pytest.fixture
def db():
    return Database()


@pytest.fixture
def seeded_show(db):
    sid = db.create_sotg_show(
        rj_name=f"RJ {uuid.uuid4().hex[:6]}",
        show_name=f"Show {uuid.uuid4().hex[:6]}",
        days="Daily",
        time_start="18:00", time_end="21:00",
        color="#06b6d4", description="",
        link_names=["L1", "L2", "L3"])
    yield sid
    try:
        db.delete_sotg_show(sid)
    except Exception:
        pass


@pytest.fixture
def dialogs_seen(monkeypatch):
    seen: list[tuple] = []
    for name in ("warning", "error", "info"):
        monkeypatch.setattr(
            _dialogs, name,
            lambda *a, _n=name, **k: seen.append((_n, a[1], a[2])))
    return seen


@pytest.fixture
def screen(qapp, db, seeded_show):
    from ui.sotg_assign import SOTGAssign
    s = SOTGAssign(db)
    s.show()
    qapp.processEvents()
    # Tomorrow keeps every test independent of the wall clock.
    s._on_date_changed((date.today() + timedelta(days=1)).isoformat())
    s._on_show_clicked(seeded_show)
    qapp.processEvents()
    yield s
    s.hide()
    s.deleteLater()


def _saved(db, link_id: int, d: str):
    return db.get_sotg_assignment(link_id, d)


def _apply(qapp, row, steps):
    for st in steps:
        if st == "file":
            row._on_file_chosen(_AUDIO)
        elif st == "prio":
            row._prio.set_value("High")
        elif st.startswith("time="):
            row._time_in.setText("")
            row._time_in.setText(st[5:])
        qapp.processEvents()


# ── The reported bug: every input order must end in a saved row ───────


@pytest.mark.parametrize("order", [
    ["file", "time=18:10", "prio"],
    ["time=18:10", "file", "prio"],
    ["file", "prio", "time=18:10"],      # the order that stayed grey
    ["prio", "file", "time=18:10"],
    ["prio", "time=18:10", "file"],
])
def test_save_works_in_every_input_order(qapp, db, screen, dialogs_seen,
                                         order):
    row = screen._row_widgets[0]
    # Start from an EMPTY time. Rows are pre-filled with an auto-
    # suggested time, which made priority alone enable Save and hid the
    # bug — the old code passed this test until the row began blank.
    row._time_in.setText("")
    qapp.processEvents()
    _apply(qapp, row, order)
    assert row._save_btn.isEnabled(), (
        f"Save stuck grey after {order}: {row.missing_reason()}")
    row._save_btn.click()
    qapp.processEvents()
    a = _saved(db, row.link_id(), screen._scheduled_date)
    assert a is not None, f"nothing written after {order}"
    assert a["sharp_time"] == "18:10"
    assert a["priority"] == "High"
    assert a["file_path"] == _AUDIO
    assert a["status"] in ("READY", "CONFLICT")
    assert not dialogs_seen


def test_saved_row_rerenders_as_update(qapp, db, screen):
    row = screen._row_widgets[0]
    _apply(qapp, row, ["file", "prio", "time=19:00"])
    row._save_btn.click()
    qapp.processEvents()
    fresh = screen._row_widgets[0]          # panel rebuilt after save
    assert fresh._save_btn.text() == "Update"
    assert fresh._status in ("READY", "CONFLICT")


def test_update_rewrites_the_same_row(qapp, db, screen):
    row = screen._row_widgets[0]
    _apply(qapp, row, ["file", "prio", "time=19:00"])
    row._save_btn.click(); qapp.processEvents()
    first = _saved(db, row.link_id(), screen._scheduled_date)
    row = screen._row_widgets[0]
    _apply(qapp, row, ["time=20:30"])
    row._save_btn.click(); qapp.processEvents()
    second = _saved(db, row.link_id(), screen._scheduled_date)
    assert second["id"] == first["id"]
    assert second["sharp_time"] == "20:30"


# ── Stale button, both directions ───────────────────────────────────────


def test_clearing_the_time_disables_save(qapp, screen):
    row = screen._row_widgets[0]
    _apply(qapp, row, ["file", "prio", "time=18:10"])
    assert row._save_btn.isEnabled()
    row._time_in.setText("")
    qapp.processEvents()
    assert not row._save_btn.isEnabled()


def test_half_typed_time_disables_save(qapp, screen):
    row = screen._row_widgets[0]
    _apply(qapp, row, ["file", "prio", "time=18:10"])
    row._time_in.setText("")
    row._time_in.setText("19:3")
    qapp.processEvents()
    assert not row._save_btn.isEnabled()
    assert "HH:MM" in row.missing_reason()


def test_host_guard_never_hands_a_half_time_to_the_db(qapp, db, screen,
                                                     dialogs_seen):
    """Even if the save signal fires on an incomplete row, the operator
    gets a plain message and nothing is written — never the DB's raw
    "sharp_time must be HH:MM 24h ('19:3')"."""
    row = screen._row_widgets[0]
    _apply(qapp, row, ["file", "prio"])
    row._time_in.setText("")
    row._time_in.setText("19:3")
    qapp.processEvents()
    screen._on_row_save(row.link_id())
    assert _saved(db, row.link_id(), screen._scheduled_date) is None
    assert dialogs_seen and dialogs_seen[-1][0] == "warning"
    assert "sharp_time must be" not in dialogs_seen[-1][2]


# ── A grey Save must say why ────────────────────────────────────────────


def test_missing_reason_walks_each_requirement(qapp, screen):
    row = screen._row_widgets[0]
    row._time_in.setText(""); qapp.processEvents()
    assert "audio file" in row.missing_reason()
    row._on_file_chosen(_AUDIO); qapp.processEvents()
    assert "HH:MM" in row.missing_reason()
    row._time_in.setText("18:45"); qapp.processEvents()
    assert "priority" in row.missing_reason().lower()
    row._prio.set_value("Low"); qapp.processEvents()
    assert row.missing_reason() is None
    assert row._save_btn.toolTip() == "Ready to save."


def test_tooltip_carries_the_reason_while_grey(qapp, screen):
    row = screen._row_widgets[0]
    _apply(qapp, row, ["file", "time=18:10"])
    assert not row._save_btn.isEnabled()
    assert "priority" in row._save_btn.toolTip().lower()


def test_missing_controls_are_outlined_once_a_file_is_chosen(qapp, screen):
    row = screen._row_widgets[0]
    row._time_in.setText(""); qapp.processEvents()
    # Untouched row stays calm
    assert row._prio._attention is False
    assert row._time_in._attention is False
    row._on_file_chosen(_AUDIO); qapp.processEvents()
    assert row._prio._attention is True
    assert row._time_in._attention is True
    row._time_in.setText("18:10"); row._prio.set_value("High")
    qapp.processEvents()
    assert row._prio._attention is False
    assert row._time_in._attention is False


# ── The operator's actual path ─────────────────────────────────────────


@pytest.fixture
def early_show(db):
    """A show whose window is at the very start of the day, so TODAY's
    auto-suggested times are already in the past — the 'College Canteen
    at 15:06' situation."""
    sid = db.create_sotg_show(
        rj_name=f"RJ {uuid.uuid4().hex[:6]}",
        show_name=f"Early {uuid.uuid4().hex[:6]}",
        days="Daily", time_start="00:00", time_end="00:30",
        color="#06b6d4", description="", link_names=["L1", "L2"])
    yield sid
    try:
        db.delete_sotg_show(sid)
    except Exception:
        pass


def test_past_suggestion_then_retyped_time_saves(qapp, db, early_show,
                                                 dialogs_seen):
    """Today, the row arrives with a suggested time that has already
    passed (red). Operator picks the file and priority, then types a
    later time. The old code left Save grey here: the past→not-past
    flip happened while the field was half-empty, so the final valid
    time never re-evaluated the button. Nothing could ever be saved."""
    now = datetime.now()
    if (now.hour, now.minute) <= (0, 30) or now.strftime("%H:%M") >= "23:59":
        pytest.skip("needs a wall clock between 00:31 and 23:58")
    from ui.sotg_assign import SOTGAssign
    s = SOTGAssign(db); s.show(); qapp.processEvents()
    s._on_date_changed(date.today().isoformat())
    s._on_show_clicked(early_show); qapp.processEvents()
    try:
        row = s._row_widgets[0]
        assert row._time_in.is_invalid_past(), "precondition: suggestion is past"
        _apply(qapp, row, ["file", "prio"])
        assert not row._save_btn.isEnabled()
        # Retype keystroke-by-keystroke like a person would.
        row._time_in.setText("")
        for partial in ("2", "23", "23:5", "23:59"):
            row._time_in.setText(partial)
            qapp.processEvents()
        assert row._save_btn.isEnabled(), row.missing_reason()
        row._save_btn.click(); qapp.processEvents()
        a = db.get_sotg_assignment(row.link_id(), date.today().isoformat())
        assert a is not None and a["sharp_time"] == "23:59"
        assert not dialogs_seen
    finally:
        s.hide(); s.deleteLater()


# ── Today: a past time blocks, a future time saves ──────────────────────


def test_past_time_today_blocks_with_a_clear_reason(qapp, db, seeded_show):
    if datetime.now().hour == 0 and datetime.now().minute == 0:
        pytest.skip("midnight — no past minute exists today")
    from ui.sotg_assign import SOTGAssign
    s = SOTGAssign(db); s.show(); qapp.processEvents()
    s._on_date_changed(date.today().isoformat())
    s._on_show_clicked(seeded_show); qapp.processEvents()
    try:
        row = s._row_widgets[0]
        _apply(qapp, row, ["file", "prio", "time=00:00"])
        assert not row._save_btn.isEnabled()
        assert "already passed" in row.missing_reason()
        _apply(qapp, row, ["time=23:59"])
        if datetime.now().strftime("%H:%M") < "23:59":
            assert row._save_btn.isEnabled()
    finally:
        s.hide(); s.deleteLater()
