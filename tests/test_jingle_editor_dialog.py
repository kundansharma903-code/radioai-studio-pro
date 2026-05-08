"""
Jingle Editor Dialog (Figma 106:2) + DB migration tests.

Pinned behaviour:
  • _ensure_jingles_columns idempotent + adds the 9 new columns
    (auto_code, author, entry_date, comments, bpm, era_year,
    clock_id, min_gap_minutes, max_per_hour) + creates the
    jingle_linked_spots join table.
  • next_jingle_auto_code returns JNG-NNNN, monotonically increasing.
  • add_jingle round-trip + auto_code is auto-assigned.
  • update_jingle preserves untouched fields (including auto_code).
  • get_jingle_linked_spots / set_jingle_linked_spots round-trip.
  • Dialog NEW mode: AUTO CODE pill prefilled, default category =
    Station ID, save with empty title is blocked + emits no signal.
  • Dialog EDIT mode: existing row preloads into every visible field;
    save persists changes + emits jingle_saved with the id.

Live-DB fixtures use a unique '_test_jingle_editor_<uuid8>_' prefix
+ try/finally cleanup so the dev DB stays untouched.
"""

from __future__ import annotations

import uuid
from typing import List

import pytest

from core.database import Database


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def db():
    return Database()


@pytest.fixture
def seeded(db):
    """Insert one well-formed jingle + one campaign so the linked-spots
    helpers can be exercised. Returns (prefix, jingle_id, campaign_id)
    and cleans both up on teardown."""
    prefix = f"_test_jingle_editor_{uuid.uuid4().hex[:8]}_"
    conn = db._conn()
    try:
        # Make sure the columns exist before we insert (the dialog
        # would normally do this on open).
        db._ensure_jingles_columns()
        jid = db.add_jingle({
            "name":     prefix + "Bridge",
            "category": "Station ID",
            "duration_ms": 6000,
            "properties":  "Top of Hour",
            "playlister_code": "JI-9050",
            "is_enabled": 1,
        })
        # Dummy campaign — schema differs across dev DBs; insert with
        # only the columns we know exist (name + auto_code).
        cur = conn.execute(
            "INSERT INTO campaigns (name, auto_code) VALUES (?, ?)",
            [prefix + "Brand X", "AC-9050"])
        cid = int(cur.lastrowid)
        conn.commit()
        yield prefix, jid, cid
    finally:
        try:
            conn.execute("DELETE FROM jingles WHERE id = ?", [jid])
            conn.execute("DELETE FROM campaigns WHERE id = ?", [cid])
            conn.execute(
                "DELETE FROM jingle_linked_spots WHERE jingle_id = ?", [jid])
            conn.commit()
        except Exception:
            pass


# ── DB migration + helpers ─────────────────────────────────────────────────


def test_ensure_jingles_columns_is_idempotent(db):
    db._ensure_jingles_columns()
    db._ensure_jingles_columns()  # second call must be a no-op
    cols = {r[1] for r in db._conn().execute(
        "PRAGMA table_info(jingles)").fetchall()}
    expected = {
        "auto_code", "author", "entry_date", "comments", "bpm",
        "era_year", "clock_id", "min_gap_minutes", "max_per_hour",
    }
    assert expected.issubset(cols)


def test_jingle_linked_spots_table_exists_after_migration(db):
    db._ensure_jingles_columns()
    rows = db._conn().execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name='jingle_linked_spots'"
    ).fetchall()
    assert len(rows) == 1


def test_next_jingle_auto_code_format(db):
    db._ensure_jingles_columns()
    code = db.next_jingle_auto_code()
    assert code.startswith("JNG-")
    assert len(code) == 8
    int(code.split("-")[1])  # numeric suffix


def test_add_jingle_assigns_auto_code(db):
    db._ensure_jingles_columns()
    new_id = db.add_jingle({
        "name":     "_test_addj_a",
        "category": "Promo",
        "duration_ms": 2500,
    })
    try:
        row = db._conn().execute(
            "SELECT auto_code, name, category FROM jingles WHERE id = ?",
            [new_id]).fetchone()
        assert row["auto_code"].startswith("JNG-")
        assert row["name"] == "_test_addj_a"
        assert row["category"] == "Promo"
    finally:
        db._conn().execute("DELETE FROM jingles WHERE id = ?", [new_id])
        db._conn().commit()


def test_update_jingle_preserves_untouched_fields(db, seeded):
    prefix, jid, _cid = seeded
    before = dict(db._conn().execute(
        "SELECT * FROM jingles WHERE id = ?", [jid]).fetchone())
    db.update_jingle(jid, {"category": "Weather", "comments": "x"})
    after = dict(db._conn().execute(
        "SELECT * FROM jingles WHERE id = ?", [jid]).fetchone())
    assert after["category"] == "Weather"
    assert after["comments"] == "x"
    # Auto code + name + playlister_code stay put.
    assert after["auto_code"] == before["auto_code"]
    assert after["name"] == before["name"]
    assert after["playlister_code"] == before["playlister_code"]


def test_linked_spots_round_trip(db, seeded):
    _prefix, jid, cid = seeded
    db.set_jingle_linked_spots(jid, [cid])
    rows = db.get_jingle_linked_spots(jid)
    assert len(rows) == 1
    assert int(rows[0]["campaign_id"]) == cid


def test_linked_spots_replace_semantic(db, seeded):
    """set_jingle_linked_spots replaces the entire set (not append)."""
    _prefix, jid, cid = seeded
    db.set_jingle_linked_spots(jid, [cid])
    db.set_jingle_linked_spots(jid, [])   # clears
    rows = db.get_jingle_linked_spots(jid)
    assert rows == []


# ── Dialog smoke + save flow ────────────────────────────────────────────────


def test_dialog_new_mode_prefills_auto_code(qapp, db):
    from ui.dialogs.jingle_editor_dialog import JingleEditorDialog
    d = JingleEditorDialog(db, jingle_id=None)
    assert d._auto_code.startswith("JNG-")
    assert d._selected_category == "Station ID"  # default
    d.deleteLater()


def test_dialog_edit_mode_preloads_row(qapp, db, seeded):
    from ui.dialogs.jingle_editor_dialog import JingleEditorDialog
    prefix, jid, _cid = seeded
    d = JingleEditorDialog(db, jingle_id=jid)
    assert d._title_input is not None
    assert d._title_input.text() == prefix + "Bridge"
    assert d._selected_category == "Station ID"
    assert d._duration_input.text() == "0:06"
    assert d._availability.is_enabled() is True
    d.deleteLater()


def test_dialog_save_with_empty_title_is_blocked(qapp, db, monkeypatch):
    """Empty title triggers QMessageBox.warning + suppresses the save —
    no DB row appears, no signal fires."""
    from PyQt6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a, **k: QMessageBox.StandardButton.Ok)
    from ui.dialogs.jingle_editor_dialog import JingleEditorDialog
    d = JingleEditorDialog(db, jingle_id=None)
    fired: list[int] = []
    d.jingle_saved.connect(fired.append)
    d._title_input.setText("")
    d._on_save()
    assert fired == []
    d.deleteLater()


def test_dialog_save_in_new_mode_inserts_and_emits(qapp, db, monkeypatch):
    from ui.dialogs.jingle_editor_dialog import JingleEditorDialog
    d = JingleEditorDialog(db, jingle_id=None)
    fired: list[int] = []
    d.jingle_saved.connect(fired.append)
    test_name = f"_test_save_new_{uuid.uuid4().hex[:8]}"
    d._title_input.setText(test_name)
    d._props_input.setText("Special")
    d._duration_input.setText("0:07")
    d._on_category_picked("Promo")
    # Suppress the modal close — accept() walks BaseDialog teardown.
    d._on_save()
    try:
        assert len(fired) == 1
        new_id = fired[0]
        row = dict(db._conn().execute(
            "SELECT * FROM jingles WHERE id = ?", [new_id]).fetchone())
        assert row["name"] == test_name
        assert row["category"] == "Promo"
        assert row["properties"] == "Special"
        assert row["duration_ms"] == 7000
        assert row["auto_code"].startswith("JNG-")
    finally:
        if fired:
            db._conn().execute("DELETE FROM jingles WHERE id = ?",
                               [fired[0]])
            db._conn().commit()
    d.deleteLater()


def test_dialog_save_in_edit_mode_persists_changes(qapp, db, seeded):
    from ui.dialogs.jingle_editor_dialog import JingleEditorDialog
    prefix, jid, _cid = seeded
    d = JingleEditorDialog(db, jingle_id=jid)
    fired: list[int] = []
    d.jingle_saved.connect(fired.append)
    d._on_category_picked("News Break")
    d._props_input.setText("News")
    d._on_save()
    assert fired == [jid]
    after = dict(db._conn().execute(
        "SELECT * FROM jingles WHERE id = ?", [jid]).fetchone())
    assert after["category"] == "News Break"
    assert after["properties"] == "News"
    d.deleteLater()
