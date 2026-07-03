"""
Category Move (Claude design) — screen + DB + wiring tests.

Pinned behaviour:
  • db.move_songs_to_category — exact WHERE id IN move, returns count,
    dest=None un-categorizes, empty list is a 0 no-op.
  • db.get_songs_for_category_move — plain dicts, Uncategorized pool
    via category_id=None.
  • CategoryMove mounts at 1440×900; source combo lists every category
    PLUS Uncategorized (always last); destination cards exclude the
    current source.
  • CTA gating: disabled until ≥1 song checked AND a destination picked.
  • set_context() pre-selects the source category and pre-checks ids
    (the right-click entry path).
  • Search filter hides non-matching rows; Select All only selects
    the visible (filtered) rows.
  • SongsLibrary._SongRow emits right_clicked on RMB press and
    SongsLibrary exposes change_category_requested.
  • MainWindow mounts category_move, routes "category_move", and
    _on_change_category_requested lands on the screen with context.

Tests run on the conftest live-DB shield copy — temp rows are still
cleaned up in try/finally as a courtesy.
"""

from __future__ import annotations

import pytest

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest

from core.database import Database


PFX = "catmove-test"


# ── helpers ──────────────────────────────────────────────────────────────

def _mk_category(db, name) -> int:
    return db.add_category({"name": f"{PFX}-{name}",
                            "color": "#8b5cf6"})


def _mk_song(db, title, cat_id) -> int:
    db.execute(
        "INSERT INTO songs (artist, title, category_id, duration_ms, "
        "is_enabled) VALUES (?, ?, ?, ?, 1)",
        (f"{PFX}-artist", f"{PFX}-{title}", cat_id, 180000))
    row = db.execute(
        "SELECT id FROM songs WHERE title = ? AND artist = ?",
        (f"{PFX}-{title}", f"{PFX}-artist"))
    return int(row[0]["id"])


def _cleanup(db, song_ids=(), cat_ids=()):
    if song_ids:
        ph = ", ".join(["?"] * len(song_ids))
        db.execute(f"DELETE FROM songs WHERE id IN ({ph})",
                   tuple(int(i) for i in song_ids))
    for cid in cat_ids:
        try:
            db.delete_category(int(cid))
        except Exception:
            pass


# ── DB layer ─────────────────────────────────────────────────────────────

def test_db_move_songs_roundtrip():
    db = Database()
    cat_a = cat_b = None
    ids = []
    try:
        cat_a = _mk_category(db, "A")
        cat_b = _mk_category(db, "B")
        ids = [_mk_song(db, "s1", cat_a), _mk_song(db, "s2", cat_a)]

        moved = db.move_songs_to_category(ids, cat_b)
        assert moved == 2
        rows = db.execute(
            "SELECT category_id FROM songs WHERE id IN (?, ?)",
            tuple(ids))
        assert all(int(r["category_id"]) == cat_b for r in rows)

        back = db.move_songs_to_category(ids, cat_a)
        assert back == 2
    finally:
        _cleanup(db, ids, [c for c in (cat_a, cat_b) if c])


def test_db_move_to_uncategorized_and_back():
    db = Database()
    cat = None
    ids = []
    try:
        cat = _mk_category(db, "U")
        ids = [_mk_song(db, "u1", cat)]
        assert db.move_songs_to_category(ids, None) == 1
        row = db.execute("SELECT category_id FROM songs WHERE id = ?",
                         (ids[0],))
        assert row[0]["category_id"] is None
        assert db.move_songs_to_category(ids, cat) == 1
    finally:
        _cleanup(db, ids, [cat] if cat else [])


def test_db_move_empty_list_is_noop():
    db = Database()
    assert db.move_songs_to_category([], 1) == 0


def test_db_get_songs_for_category_move_returns_dicts():
    db = Database()
    cat = None
    ids = []
    try:
        cat = _mk_category(db, "L")
        ids = [_mk_song(db, "l1", cat)]
        songs = db.get_songs_for_category_move(cat)
        assert len(songs) == 1
        assert isinstance(songs[0], dict)
        assert songs[0]["id"] == ids[0]
        assert "title" in songs[0] and "artist" in songs[0]
        # Uncategorized pool path must not raise
        assert isinstance(db.get_songs_for_category_move(None), list)
    finally:
        _cleanup(db, ids, [cat] if cat else [])


# ── Screen ───────────────────────────────────────────────────────────────

@pytest.fixture
def screen(qapp):
    from ui.category_move import CategoryMove
    scr = CategoryMove(Database())
    yield scr
    scr.deleteLater()


def test_screen_mounts_with_uncategorized_last(screen):
    db = Database()
    n_cats = len(db.get_categories())
    assert screen.width() == 1440 and screen.height() == 900
    assert screen._cmb_source.count() == n_cats + 1
    assert screen._cmb_source.itemText(
        screen._cmb_source.count() - 1).startswith("Uncategorized")


def test_dest_cards_exclude_source(screen):
    src = screen._source_id
    dest_ids = [c.cat_id for c in screen._dest_cards]
    assert src not in dest_ids
    assert len(dest_ids) == len(screen._cats_cache) - 1


def test_station_label_object_name(screen):
    assert screen._station_lbl.objectName() == "hdr_station_lbl"


def test_cta_gating_and_move(qapp):
    from ui.category_move import CategoryMove
    from core import dialogs as _dialogs
    db = Database()
    cat_a = cat_b = None
    ids = []
    scr = None
    try:
        cat_a = _mk_category(db, "G1")
        cat_b = _mk_category(db, "G2")
        ids = [_mk_song(db, "g1", cat_a), _mk_song(db, "g2", cat_a)]

        scr = CategoryMove(db)
        scr.set_context(ids, cat_a)
        assert set(scr.selected_ids()) == set(ids)
        assert scr._src_name().endswith("G1")
        # No destination picked yet → CTA disabled
        assert not scr._btn_move.isEnabled()

        card = next(c for c in scr._dest_cards if c.cat_id == cat_b)
        card.clicked.emit(card.cat_id)
        assert scr._btn_move.isEnabled()

        # Auto-accept the premium confirm + info dialogs
        orig_c, orig_i = _dialogs.confirm, _dialogs.info
        _dialogs.confirm = lambda *a, **k: True
        _dialogs.info = lambda *a, **k: None
        try:
            scr._on_move_clicked()
        finally:
            _dialogs.confirm, _dialogs.info = orig_c, orig_i

        rows = db.execute(
            "SELECT category_id FROM songs WHERE id IN (?, ?)",
            tuple(ids))
        assert all(int(r["category_id"]) == cat_b for r in rows)
    finally:
        if scr is not None:
            scr.deleteLater()
        _cleanup(db, ids, [c for c in (cat_a, cat_b) if c])


def test_search_filters_and_select_all_respects_filter(qapp):
    from ui.category_move import CategoryMove
    db = Database()
    cat = None
    ids = []
    scr = None
    try:
        cat = _mk_category(db, "S")
        ids = [_mk_song(db, "alpha-one", cat),
               _mk_song(db, "beta-two", cat)]
        scr = CategoryMove(db)
        scr.set_context(None, cat)
        assert len(scr._rows) == 2

        scr._search.setText("alpha")
        visible = [r for r in scr._rows if not r.isHidden()]
        assert len(visible) == 1

        scr._on_select_all()
        assert len(scr.selected_ids()) == 1   # only the visible row
    finally:
        if scr is not None:
            scr.deleteLater()
        _cleanup(db, ids, [cat] if cat else [])


# ── Songs Library wiring ─────────────────────────────────────────────────

def test_song_row_right_click_emits(qapp):
    from ui.songs_library import _SongRow
    row = _SongRow({"id": 42, "title": "t", "artist": "a",
                    "category": "", "duration_ms": 0, "bpm": 0,
                    "last_played": None}, 0)
    got = []
    row.right_clicked.connect(lambda sid, gp: got.append((sid, gp)))
    QTest.mouseClick(row, Qt.MouseButton.RightButton)
    assert got and got[0][0] == 42
    row.deleteLater()


def test_songs_library_has_change_category_signal(qapp):
    from ui.songs_library import SongsLibrary
    assert hasattr(SongsLibrary, "change_category_requested")


# ── MainWindow routing ───────────────────────────────────────────────────

def test_main_window_mounts_and_routes_category_move(qapp, qtbot,
                                                     monkeypatch):
    """Same harness pattern as test_ai_magic_hub's MainWindow tests:
    patch out the boot auto-play side effect, qtbot owns the widget,
    teardown via close() (runs _cleanup_engine internally)."""
    # Flush every deleteLater() queued by the earlier screen tests —
    # constructing the full MainWindow (all engines + BASS) on top of
    # a backlog of half-destroyed widgets is what trips the known
    # access-violation teardown flake in a combined run.
    qapp.processEvents()
    qapp.sendPostedEvents(None, 52)   # QEvent.DeferredDelete
    qapp.processEvents()

    from ui import main_window as mw_mod
    monkeypatch.setattr(mw_mod.MainWindow, "_apply_startup_auto_mode",
                        lambda self: None)
    from ui.main_window import MainWindow
    w = MainWindow(db=Database())
    qtbot.addWidget(w)

    assert hasattr(w, "category_move")
    w._on_hub_screen_requested("category_move")
    assert w._stack.currentWidget() is w.category_move

    w._on_hub_screen_requested("songs")
    assert w._stack.currentWidget() is w.songs_library

    w._on_change_category_requested([1], None)
    assert w._stack.currentWidget() is w.category_move

    w.close()
    w.deleteLater()
