"""
Jingles Library — smoke + interaction tests.

Pinned behaviour for Figma 44:2 (ui/jingles_library.py):
  • Constructs without crashing on a real DB.
  • Loads existing `jingles` rows; counter reflects active/total.
  • Category dropdown narrows the visible row list.
  • Properties / Duration / Only Enabled filters narrow the list.
  • Search input filters by name / category / playlister code.
  • Clicking a row updates the details panel + signal fires.
  • + Add New Jingle emits add_jingle_clicked (toast fallback when the
    editor dialog file isn't on disk yet — commit 2 lands it).

Uses a uniquely-named test prefix per fixture so concurrent test runs
and the live FCP dev DB don't collide. try/finally cleans up.
"""

from __future__ import annotations

import uuid
from typing import List

import pytest

from core.database import Database
from core import dialogs as _dialogs
from ui.jingles_library import (
    JinglesLibrary, CATEGORY_FILTER_OPTIONS, PROPERTIES_FILTER_OPTIONS,
    DURATION_FILTER_OPTIONS, DETAIL_TABS,
)


# ── Test data fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def db():
    return Database()


@pytest.fixture
def seeded(db):
    """Insert 4 unique jingles spanning categories + properties +
    durations so every filter axis can be exercised. Yield (prefix, ids)
    so callers can match against the prefix without colliding with the
    dev DB seeds."""
    prefix = f"_test_jingles_{uuid.uuid4().hex[:8]}_"
    rows = [
        # name, category, duration_ms, properties, playlister_code, enabled
        ("Open Bridge",   "Station ID", 5000,   "Top of Hour",  "JI-9001", 1),
        ("Shotgun A",     "Shotguns",   3000,   "Special",      "JI-9002", 1),
        ("News Cue",      "News Break", 8500,   "News",         "JI-9003", 1),
        ("Promo Tail",    "Promo",     12000,   "Promo",        "JI-9004", 0),
    ]
    ids: List[int] = []
    conn = db._conn()
    try:
        for name, cat, dur, props, code, en in rows:
            cur = conn.execute(
                "INSERT INTO jingles (name, category, file_path, "
                "duration_ms, properties, playlister_code, is_enabled) "
                "VALUES (?, ?, '', ?, ?, ?, ?)",
                [prefix + name, cat, dur, props, code, en])
            ids.append(int(cur.lastrowid))
        conn.commit()
        yield prefix, ids
    finally:
        conn.execute("DELETE FROM jingles WHERE name LIKE ? ESCAPE '\\'",
                     [prefix.replace("_", r"\_") + "%"])
        conn.commit()


# ── Smoke ───────────────────────────────────────────────────────────────────


def test_construction_does_not_crash(qapp, db):
    s = JinglesLibrary(db)
    assert s.size().width() == 1440
    assert s.size().height() == 900
    s.deleteLater()


def test_loads_jingles_from_db(qapp, db, seeded):
    prefix, ids = seeded
    s = JinglesLibrary(db)
    matching = [x for x in s._jingles if x["name"].startswith(prefix)]
    assert len(matching) == 4
    s.deleteLater()


def test_counter_shows_total_and_active(qapp, db, seeded):
    prefix, ids = seeded
    s = JinglesLibrary(db)
    assert s._counter is not None
    assert s._counter._total == len(s._jingles)
    # 3 of the 4 seeded rows are enabled.
    assert s._counter._active >= 3
    s.deleteLater()


# ── Filters ─────────────────────────────────────────────────────────────────


def test_category_filter_narrows_visible_rows(qapp, db, seeded):
    prefix, ids = seeded
    s = JinglesLibrary(db)

    # Default = "All Categories" → all rows visible.
    visible_all = s._filtered_jingles()
    assert any(r["name"].startswith(prefix) for r in visible_all)

    # Pick "News Break" — only the seeded "News Cue" matches.
    s._on_category_picked("News Break")
    matching = [r for r in s._filtered_jingles()
                if r["name"].startswith(prefix)]
    assert len(matching) == 1
    assert matching[0]["category"] == "News Break"

    # Reset
    s._on_category_picked("All Categories")
    visible_after = s._filtered_jingles()
    assert any(r["name"].startswith(prefix) for r in visible_after)
    s.deleteLater()


def test_properties_filter_narrows_visible_rows(qapp, db, seeded):
    prefix, ids = seeded
    s = JinglesLibrary(db)
    s._on_properties_picked("News")
    matching = [r for r in s._filtered_jingles()
                if r["name"].startswith(prefix)]
    assert len(matching) == 1
    assert matching[0]["properties"] == "News"
    s.deleteLater()


def test_duration_filter_buckets_correctly(qapp, db, seeded):
    """Under 5s / 5–10s / Over 10s buckets must classify the seeded
    durations 5s, 3s, 8.5s, 12s correctly."""
    prefix, ids = seeded
    s = JinglesLibrary(db)
    s._on_duration_picked("Under 5s")
    matching = [r for r in s._filtered_jingles()
                if r["name"].startswith(prefix)]
    assert len(matching) == 1
    assert matching[0]["duration_ms"] == 3000

    s._on_duration_picked("5–10s")
    matching = [r for r in s._filtered_jingles()
                if r["name"].startswith(prefix)]
    durations = sorted(int(r["duration_ms"]) for r in matching)
    assert durations == [5000, 8500]

    s._on_duration_picked("Over 10s")
    matching = [r for r in s._filtered_jingles()
                if r["name"].startswith(prefix)]
    assert len(matching) == 1
    assert matching[0]["duration_ms"] == 12000
    s.deleteLater()


def test_only_enabled_excludes_disabled_rows(qapp, db, seeded):
    prefix, ids = seeded
    s = JinglesLibrary(db)
    s._on_only_enabled_toggled(True)
    matching = [r for r in s._filtered_jingles()
                if r["name"].startswith(prefix)]
    assert len(matching) == 3
    assert all(r.get("is_enabled") for r in matching)
    s.deleteLater()


def test_search_filters_by_name(qapp, db, seeded):
    prefix, ids = seeded
    s = JinglesLibrary(db)
    s._on_search_changed("News Cue")
    matching = [r for r in s._filtered_jingles()
                if r["name"].startswith(prefix)]
    assert len(matching) == 1
    assert "News" in matching[0]["name"]
    s.deleteLater()


def test_filter_options_are_well_formed(qapp, db):
    """The dropdown option lists must lead with the 'All …' sentinel
    and contain at least one real value beneath."""
    s = JinglesLibrary(db)
    assert CATEGORY_FILTER_OPTIONS[0] == "All Categories"
    assert len(CATEGORY_FILTER_OPTIONS) >= 9      # All + 8 categories
    assert PROPERTIES_FILTER_OPTIONS[0] == "All Properties"
    assert DURATION_FILTER_OPTIONS[0] == "All Durations"
    assert DETAIL_TABS[0] == "Jingle Details"
    s.deleteLater()


# ── Row selection updates details ───────────────────────────────────────────


def test_row_click_updates_details_panel(qapp, db, seeded):
    prefix, ids = seeded
    s = JinglesLibrary(db)
    target = next(x for x in s._jingles
                  if x["name"].startswith(prefix)
                  and x["category"] == "News Break")
    s._on_row_clicked(target["id"])

    assert s._selected_id == target["id"]
    assert s._details_fields["Name"]._value.startswith(prefix)
    assert s._details_fields["Category"]._value == "News Break"
    assert s._details_fields["Properties"]._value == "News"
    s.deleteLater()


def test_jingle_selected_signal_fires(qapp, db, seeded):
    prefix, ids = seeded
    s = JinglesLibrary(db)
    captured: list[int] = []
    s.jingle_selected.connect(captured.append)
    target_id = next(x["id"] for x in s._jingles
                     if x["name"].startswith(prefix))
    s._on_row_clicked(target_id)
    assert captured and captured[-1] == target_id
    s.deleteLater()


# ── Delete (2026-07-09) ─────────────────────────────────────────────────────


def test_delete_removes_selected_jingle(qapp, db, seeded, monkeypatch):
    """✕ Delete → confirm accepted → row gone from DB + screen list."""
    prefix, ids = seeded
    monkeypatch.setattr(_dialogs, "confirm", lambda *a, **k: True)
    s = JinglesLibrary(db)
    target_id = next(x["id"] for x in s._jingles
                     if x["name"].startswith(prefix))
    s._on_row_clicked(target_id)

    s._on_delete()

    row = db._conn().execute(
        "SELECT 1 FROM jingles WHERE id = ?", [target_id]).fetchone()
    assert row is None
    assert all(x["id"] != target_id for x in s._jingles)
    s.deleteLater()


def test_delete_cancelled_keeps_jingle(qapp, db, seeded, monkeypatch):
    prefix, ids = seeded
    monkeypatch.setattr(_dialogs, "confirm", lambda *a, **k: False)
    s = JinglesLibrary(db)
    target_id = next(x["id"] for x in s._jingles
                     if x["name"].startswith(prefix))
    s._on_row_clicked(target_id)

    s._on_delete()

    row = db._conn().execute(
        "SELECT 1 FROM jingles WHERE id = ?", [target_id]).fetchone()
    assert row is not None
    assert s._selected_id == target_id
    s.deleteLater()


def test_delete_without_selection_shows_info_and_deletes_nothing(
        qapp, db, seeded, monkeypatch):
    prefix, ids = seeded
    infos: list = []
    monkeypatch.setattr(_dialogs, "info", lambda *a, **k: infos.append(a))
    monkeypatch.setattr(
        _dialogs, "confirm",
        lambda *a, **k: pytest.fail("confirm shown without a selection"))
    s = JinglesLibrary(db)
    s._selected_id = None

    s._on_delete()

    assert infos
    remaining = db._conn().execute(
        "SELECT COUNT(*) FROM jingles WHERE name LIKE ? ESCAPE '\\'",
        [prefix.replace("_", r"\_") + "%"]).fetchone()[0]
    assert int(remaining) == 4
    s.deleteLater()


def test_delete_confirm_mentions_pinned_clock_slots(
        qapp, db, seeded, monkeypatch):
    """The danger confirm must surface the on-air consequence (a pinned
    clock slot falling back to random) + the file-safety note."""
    prefix, ids = seeded
    bodies: list[str] = []

    def _capture(parent, title, text, **kw):
        bodies.append(text)
        return False        # cancel — this test only inspects the copy

    monkeypatch.setattr(_dialogs, "confirm", _capture)
    s = JinglesLibrary(db)
    target_id = next(x["id"] for x in s._jingles
                     if x["name"].startswith(prefix))
    s._on_row_clicked(target_id)

    cid = int(db.create_clock(f"{prefix}pinclock"))
    try:
        db.save_clock_slots(cid, [
            {"slot_type": "jingle", "duration_seconds": 8,
             "minute_position": 0, "filter_json": "{}",
             "selection_mode": "specific", "item_id": target_id},
        ])
        s._on_delete()
        assert bodies
        assert "1 clock slot" in bodies[0]
        assert "not deleted" in bodies[0].lower()
    finally:
        conn = db._conn()
        conn.execute("DELETE FROM clock_slots WHERE clock_id = ?", [cid])
        conn.commit()
        try:
            db.delete_clock(cid)
        except Exception:
            pass
    s.deleteLater()


def test_add_jingle_signal_fires_on_add_new(qapp, db, monkeypatch):
    """Stub the editor dialog so the test isn't gated on a modal —
    the signal still has to fire when the button is clicked.

    2026-07-09: previously only ``dialogs.info`` was stubbed while
    ``_on_add_new`` still ran ``JingleEditorDialog(...).exec()``, opening
    a REAL modal that blocked the suite until a human closed it. Patch
    the dialog opener itself."""
    monkeypatch.setattr(_dialogs, "info",
                        lambda *a, **k: None)
    monkeypatch.setattr(JinglesLibrary, "_open_editor_dialog",
                        lambda self, jingle_id=None: None)
    s = JinglesLibrary(db)
    captured: list[bool] = []
    s.add_jingle_clicked.connect(lambda: captured.append(True))
    s._on_add_new()
    assert captured == [True]
    s.deleteLater()
