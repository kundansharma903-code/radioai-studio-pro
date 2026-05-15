"""
Sweeper Editor Dialog (Figma 108:2) — DB migration + dialog smoke tests.

Covers:
  • _ensure_sweepers_columns is idempotent (multiple calls = single column set)
  • next_sweeper_auto_code increments correctly
  • add_sweeper round-trips data + assigns auto_code
  • update_sweeper preserves untouched fields
  • Dialog opens in NEW mode with auto_code prefilled
  • Dialog opens in EDIT mode with existing row preloaded
  • Category tile selection is mutually exclusive
  • Position chip selection updates the field
  • _on_save with empty title shows warning + does not insert
  • _on_save round-trips and emits sweeper_saved(id)

Uses unique `_test_sweeper_editor_<uuid8>_` prefix per fixture so the
dev DB stays untouched. try/finally cleanup.
"""

from __future__ import annotations

import uuid
from typing import List

import pytest

from PyQt6.QtWidgets import QMessageBox

from core.database import Database
from ui.dialogs.sweeper_editor_dialog import SweeperEditorDialog
from core import dialogs as _dialogs


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def db():
    return Database()


@pytest.fixture
def cleanup(db):
    """Yield a callable to register sweeper rows for cleanup, plus a unique
    name prefix. Removes any matching rows on teardown."""
    prefix = f"_test_sweeper_editor_{uuid.uuid4().hex[:8]}_"
    ids: list[int] = []

    def register(sid: int):
        ids.append(int(sid))

    yield prefix, register
    conn = db._conn()
    if ids:
        qmarks = ",".join("?" for _ in ids)
        conn.execute(f"DELETE FROM sweepers WHERE id IN ({qmarks})", ids)
    # Belt + suspenders: also drop anything matching the prefix in case a
    # test inserted via a different code path.
    conn.execute("DELETE FROM sweepers WHERE name LIKE ? ESCAPE '\\'",
                 [prefix.replace("_", r"\_") + "%"])
    conn.commit()


# ── DB layer ────────────────────────────────────────────────────────────────

def test_ensure_sweepers_columns_is_idempotent(db):
    db._ensure_sweepers_columns()
    db._ensure_sweepers_columns()        # second call must not raise
    cols = {r[1] for r in db._conn().execute(
        "PRAGMA table_info(sweepers)").fetchall()}
    for expected in ("auto_code", "author", "entry_date", "comments",
                     "bpm", "era_year", "volume_song_pct",
                     "volume_sweeper_pct", "offset_seconds", "fade_seconds",
                     "clock_id", "min_gap_minutes", "max_per_hour"):
        assert expected in cols


def test_next_sweeper_auto_code_returns_swp_format(db):
    code = db.next_sweeper_auto_code()
    assert code.startswith("SWP-")
    suffix = code.split("-", 1)[1]
    assert suffix.isdigit() and len(suffix) == 4


def test_add_sweeper_round_trips(db, cleanup):
    prefix, register = cleanup
    sid = db.add_sweeper({
        "name": prefix + "RoundTrip",
        "category": "Music",
        "duration_ms": 12000,
        "position": "Before Intro",
        "properties": "Special",
        "playlister_code": "SS-9001",
        "is_enabled": True,
        "author": "RadioAI",
        "comments": "Test comment",
        "bpm": "128",
        "era_year": "2026",
        "volume_song_pct": 65,
        "volume_sweeper_pct": 95,
        "offset_seconds": 1.5,
        "fade_seconds": 0.7,
        "clock_id": None,
        "min_gap_minutes": 20,
        "max_per_hour": 6,
    })
    register(sid)
    row = dict(db._conn().execute(
        "SELECT * FROM sweepers WHERE id = ?", [sid]).fetchone())
    assert row["name"] == prefix + "RoundTrip"
    assert row["category"] == "Music"
    assert row["duration_ms"] == 12000
    assert row["position"] == "Before Intro"
    assert row["author"] == "RadioAI"
    assert row["volume_song_pct"] == 65
    assert row["max_per_hour"] == 6
    assert row["auto_code"].startswith("SWP-")


def test_update_sweeper_preserves_untouched_fields(db, cleanup):
    prefix, register = cleanup
    sid = db.add_sweeper({
        "name": prefix + "ToUpdate",
        "category": "Promo",
        "duration_ms": 8000,
        "position": "Bridge at End",
        "properties": "Regular",
        "is_enabled": True,
        "author": "Untouched",
    })
    register(sid)

    db.update_sweeper(sid, {"category": "Weather"})
    row = dict(db._conn().execute(
        "SELECT * FROM sweepers WHERE id = ?", [sid]).fetchone())
    assert row["category"] == "Weather"
    # Author was NOT in the update payload — should survive
    assert row["author"] == "Untouched"
    # Auto-code untouched
    assert row["auto_code"].startswith("SWP-")


# ── Dialog construction ─────────────────────────────────────────────────────

def test_dialog_new_mode_prefills_auto_code(qapp, db):
    expected_code = db.next_sweeper_auto_code()
    dlg = SweeperEditorDialog(db, sweeper_id=None)
    assert dlg._auto_code == expected_code
    assert not dlg._mode_edit
    assert dlg._title_input.text() == ""
    assert dlg._selected_category == "Station"   # default
    dlg.deleteLater()


def test_dialog_edit_mode_preloads_row(qapp, db, cleanup):
    prefix, register = cleanup
    sid = db.add_sweeper({
        "name": prefix + "EditMe",
        "category": "News",
        "duration_ms": 9000,
        "position": "Start of Song",
        "properties": "Special",
        "playlister_code": "SS-7777",
        "is_enabled": True,
        "author": "Test Author",
        "volume_song_pct": 70,
        "volume_sweeper_pct": 90,
    })
    register(sid)
    dlg = SweeperEditorDialog(db, sweeper_id=sid)
    assert dlg._mode_edit
    assert dlg._title_input.text() == prefix + "EditMe"
    assert dlg._selected_category == "News"
    assert dlg._selected_position == "Start of Song"
    assert dlg._author_input.text() == "Test Author"
    assert dlg._code_input.text() == "SS-7777"
    assert dlg._song_vol.value() == 70
    assert dlg._swp_vol.value() == 90
    assert dlg._availability.is_enabled() is True
    dlg.deleteLater()


# ── Selection logic ─────────────────────────────────────────────────────────

def test_category_selection_is_mutually_exclusive(qapp, db):
    dlg = SweeperEditorDialog(db, sweeper_id=None)
    # Default = Station
    assert dlg._cat_tiles["Station"]._active is True
    # Pick Music
    dlg._on_category_picked("Music")
    assert dlg._selected_category == "Music"
    assert dlg._cat_tiles["Music"]._active is True
    assert dlg._cat_tiles["Station"]._active is False
    # Only one active at a time
    actives = [n for n, t in dlg._cat_tiles.items() if t._active]
    assert actives == ["Music"]
    dlg.deleteLater()


def test_position_chip_selection_updates_state(qapp, db):
    dlg = SweeperEditorDialog(db, sweeper_id=None)
    # Default = Bridge at End
    assert dlg._selected_position == "Bridge at End"
    dlg._on_position_picked("Independent")
    assert dlg._selected_position == "Independent"
    assert dlg._pos_chips["Independent"]._active is True
    assert dlg._pos_chips["Bridge at End"]._active is False
    dlg.deleteLater()


# ── Save flow ───────────────────────────────────────────────────────────────

def test_save_with_empty_title_is_blocked(qapp, db, monkeypatch):
    """Empty title → QMessageBox.warning, no DB insert, dialog stays open."""
    warnings: list[str] = []
    monkeypatch.setattr(_dialogs, "warning",
        lambda *a, **k: warnings.append(a[2] if len(a) > 2 else ""))
    dlg = SweeperEditorDialog(db, sweeper_id=None)
    # Title is empty by default in NEW mode
    assert dlg._title_input.text() == ""
    captured: list[int] = []
    dlg.sweeper_saved.connect(captured.append)
    dlg._on_save()
    assert warnings, "expected QMessageBox.warning to be called"
    assert captured == [], "sweeper_saved must not fire on validation fail"
    dlg.deleteLater()


def test_save_inserts_row_and_emits_signal(qapp, db, cleanup):
    prefix, register = cleanup
    dlg = SweeperEditorDialog(db, sweeper_id=None)
    dlg._title_input.setText(prefix + "FromDialog")
    dlg._duration_input.setText("0:10")
    dlg._on_position_picked("Independent")
    dlg._on_category_picked("Custom")

    captured: list[int] = []
    dlg.sweeper_saved.connect(captured.append)
    dlg._on_save()

    assert captured, "sweeper_saved must fire on successful save"
    new_id = captured[0]
    register(new_id)
    row = dict(db._conn().execute(
        "SELECT * FROM sweepers WHERE id = ?", [new_id]).fetchone())
    assert row["name"] == prefix + "FromDialog"
    assert row["position"] == "Independent"
    assert row["category"] == "Custom"
    assert row["duration_ms"] == 10000
    assert row["auto_code"].startswith("SWP-")
    dlg.deleteLater()


def test_save_in_edit_mode_updates_existing(qapp, db, cleanup):
    prefix, register = cleanup
    sid = db.add_sweeper({
        "name": prefix + "Pre", "category": "Station",
        "duration_ms": 5000, "position": "Bridge at End",
        "is_enabled": True})
    register(sid)
    dlg = SweeperEditorDialog(db, sweeper_id=sid)
    dlg._title_input.setText(prefix + "Post")
    dlg._on_category_picked("Sports")

    captured: list[int] = []
    dlg.sweeper_saved.connect(captured.append)
    dlg._on_save()

    assert captured == [sid], "sweeper_saved must echo the existing id"
    row = dict(db._conn().execute(
        "SELECT * FROM sweepers WHERE id = ?", [sid]).fetchone())
    assert row["name"] == prefix + "Post"
    assert row["category"] == "Sports"
    dlg.deleteLater()
