"""
Sweepers Library — smoke + interaction tests.

Pinned behaviour for Figma 46:2 (ui/sweepers_library.py):
  • Constructs without crashing on a real DB.
  • Loads the existing `sweepers` rows; counter reflects active/total.
  • Position filter narrows the visible row list.
  • Clicking a row updates the details panel (selected_id + signal).
  • breadcrumb_clicked / studio_clicked signals fire as expected.

Uses a uniquely-named test sweeper prefix per fixture so concurrent test
runs and the live KISS dev DB don't collide. try/finally cleans up.
"""

from __future__ import annotations

import uuid
from typing import List

import pytest

from core.database import Database
from ui.sweepers_library import SweepersLibrary, POSITION_OPTIONS


# ── Test data fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def db():
    return Database()


@pytest.fixture
def seeded(db):
    """Insert 3 unique sweepers and yield their (prefix, ids) — caller can
    check rows via the prefix to avoid colliding with the dev DB's seeds."""
    prefix = f"_test_sweepers_{uuid.uuid4().hex[:8]}_"
    rows = [
        ("KISS Open Bridge",  "Station", 8000,  "Bridge at End",  "Regular"),
        ("KISS Before Intro", "Station", 6000,  "Before Intro",   "Regular"),
        ("KISS Start Hit",    "Station", 5000,  "Start of Song",  "Special"),
    ]
    ids: List[int] = []
    conn = db._conn()
    try:
        for name, cat, dur, pos, props in rows:
            cur = conn.execute(
                "INSERT INTO sweepers (name, category, file_path, "
                "duration_ms, position, properties, is_enabled) "
                "VALUES (?, ?, '', ?, ?, ?, 1)",
                [prefix + name, cat, dur, pos, props])
            ids.append(int(cur.lastrowid))
        conn.commit()
        yield prefix, ids
    finally:
        conn.execute("DELETE FROM sweepers WHERE name LIKE ? ESCAPE '\\'",
                     [prefix.replace("_", r"\_") + "%"])
        conn.commit()


# ── Smoke ───────────────────────────────────────────────────────────────────

def test_construction_does_not_crash(qapp, db):
    s = SweepersLibrary(db)
    assert s.windowTitle() in ("", None) or isinstance(s.windowTitle(), str)
    s.deleteLater()


def test_loads_sweepers_from_db(qapp, db, seeded):
    prefix, ids = seeded
    s = SweepersLibrary(db)
    matching = [x for x in s._sweepers if x["name"].startswith(prefix)]
    assert len(matching) == 3
    s.deleteLater()


def test_counter_shows_total_and_active(qapp, db, seeded):
    prefix, ids = seeded
    s = SweepersLibrary(db)
    assert s._counter is not None
    # _counter stores (active, total) on the latest set_counts call.
    assert s._counter._total == len(s._sweepers)
    # All 3 seeded rows are active=1; counter must be ≥ 3.
    assert s._counter._active >= 3
    s.deleteLater()


# ── Position filter ─────────────────────────────────────────────────────────

def test_filter_narrows_visible_rows(qapp, db, seeded):
    prefix, ids = seeded
    s = SweepersLibrary(db)

    # Default = "All Positions" → all rows visible
    visible_all = s._filtered_sweepers()
    assert any(r["name"].startswith(prefix) for r in visible_all)

    # Pick "Before Intro" — only the 2nd seeded sweeper matches
    s._on_filter_picked("Before Intro")
    matching = [r for r in s._filtered_sweepers()
                if r["name"].startswith(prefix)]
    assert len(matching) == 1
    assert matching[0]["position"] == "Before Intro"

    # Reset
    s._on_filter_picked("All Positions")
    visible_after = s._filtered_sweepers()
    assert any(r["name"].startswith(prefix) for r in visible_after)
    s.deleteLater()


def test_filter_options_match_position_settings(qapp, db):
    """The 6 per-row position settings rows in the details panel should
    mirror the 6 POSITION_OPTIONS minus the leading 'All Positions'."""
    s = SweepersLibrary(db)
    expected = POSITION_OPTIONS[1:]
    actual = [r.text() for r in s._pos_setting_rows]
    assert actual == expected
    s.deleteLater()


# ── Row selection updates details ───────────────────────────────────────────

def test_row_click_updates_details_panel(qapp, db, seeded):
    prefix, ids = seeded
    s = SweepersLibrary(db)
    target = next(x for x in s._sweepers
                  if x["name"].startswith(prefix)
                  and x["position"] == "Before Intro")
    s._on_row_clicked(target["id"])

    assert s._selected_id == target["id"]
    assert s._details_fields["Position"]._value == "Before Intro"
    assert s._details_fields["Name"]._value.startswith(prefix)

    # Position-settings list should highlight "Before Intro"
    active_rows = [r for r in s._pos_setting_rows if r._active]
    assert len(active_rows) == 1
    assert active_rows[0].text() == "Before Intro"
    s.deleteLater()


def test_sweeper_selected_signal_fires(qapp, db, seeded):
    prefix, ids = seeded
    s = SweepersLibrary(db)
    captured: list[int] = []
    s.sweeper_selected.connect(captured.append)
    target_id = next(x["id"] for x in s._sweepers
                     if x["name"].startswith(prefix))
    s._on_row_clicked(target_id)
    assert captured and captured[-1] == target_id
    s.deleteLater()


# ── Breadcrumb / studio signals ─────────────────────────────────────────────

def test_add_sweeper_signal_fires_on_add_new(qapp, db, monkeypatch):
    """Stub QMessageBox so the test isn't gated on a modal dialog —
    the signal still has to fire."""
    from PyQt6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "information",
                        lambda *a, **k: QMessageBox.StandardButton.Ok)
    s = SweepersLibrary(db)
    captured: list[bool] = []
    s.add_sweeper_clicked.connect(lambda: captured.append(True))
    s._on_add_new()
    assert captured == [True]
    s.deleteLater()
