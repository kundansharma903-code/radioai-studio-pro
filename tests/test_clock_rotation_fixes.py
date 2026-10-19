"""
Clocks / rotation / schedule-grid / song-delete fixes (2026-10-17).

Runs against the session's disposable DB copy (conftest live-DB shield);
every row a test creates is removed by explicit id.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta

import pytest

from core.database import Database


@pytest.fixture
def db():
    return Database()


@pytest.fixture
def made(db):
    """Exact-id cleanup registry."""
    reg = {"songs": [], "clocks": [], "force": []}
    pre = f"_test_crf_{uuid.uuid4().hex[:8]}_"
    reg["prefix"] = pre
    yield reg
    for fid in reg["force"]:
        try:
            db.delete_force_clock(fid)
        except Exception:
            pass
    for cid in reg["clocks"]:
        try:
            db.delete_clock(cid)
        except Exception:
            pass
    for sid in reg["songs"]:
        try:
            db.delete_song(sid)
        except Exception:
            pass


def _make_song(db, made, category_id=None) -> int:
    conn = db._conn()
    cur = conn.execute(
        "INSERT INTO songs (artist, title, file_path, category_id, "
        "is_enabled) VALUES (?, ?, '', ?, 1)",
        [made["prefix"] + "artist", made["prefix"] + "title", category_id])
    conn.commit()
    sid = int(cur.lastrowid)
    made["songs"].append(sid)
    return sid


def _make_clock(db, made, name="clk") -> int:
    cid = int(db.create_clock(made["prefix"] + name))
    made["clocks"].append(cid)
    return cid


# ── 1. delete_song unpins clock_slots.specific_song_id ──────────────────

def test_delete_song_pinned_in_clock_succeeds(db, made):
    sid = _make_song(db, made)
    cid = _make_clock(db, made)
    db.save_clock_slots(cid, [{"slot_type": "song", "specific_song_id": sid,
                               "filter_json": "{}"}])
    db.delete_song(sid)                       # used to raise FK failure
    made["songs"].remove(sid)
    assert db._conn().execute(
        "SELECT COUNT(*) FROM songs WHERE id = ?", [sid]).fetchone()[0] == 0
    row = db._conn().execute(
        "SELECT specific_song_id FROM clock_slots WHERE clock_id = ?",
        [cid]).fetchone()
    assert row is not None and row[0] is None


# ── 2. plan picks gated by slot category + current song category ────────

def _engine(db, monkeypatch, tmp_path, picks):
    from core.scheduler.engine import SchedulerEngine
    eng = SchedulerEngine(db)
    for p in picks:
        f = tmp_path / f"{p['song_id']}.mp3"
        f.write_bytes(b"x")
        p["file_path"] = str(f)
    monkeypatch.setattr(eng, "_active_rotation_decisions",
                        lambda: {"active": True, "rest_ids": set(),
                                 "picks": picks})
    monkeypatch.setattr(eng, "_recent_artists", lambda _m: set())
    monkeypatch.setattr(eng, "_recent_song_ids", lambda _m: set())
    return eng


def _cat_ids(db, n=2):
    rows = db._conn().execute(
        "SELECT id FROM categories ORDER BY id LIMIT ?", [n]).fetchall()
    if len(rows) < n:
        pytest.skip("need categories")
    return [int(r[0]) for r in rows]


def test_plan_pick_only_airs_in_its_category_slot(db, monkeypatch, tmp_path):
    c1, c2 = _cat_ids(db)
    picks = [
        {"song_id": 90000001, "artist": "A", "title": "a", "action": "pick",
         "duration_ms": 1000, "target_category_id": c1, "category_id": c1},
        {"song_id": 90000002, "artist": "B", "title": "b", "action": "pick",
         "duration_ms": 1000, "target_category_id": c2, "category_id": c2},
    ]
    eng = _engine(db, monkeypatch, tmp_path, picks)
    for _ in range(15):
        item = eng._pick_song({"slot_type": "song", "category_id": c1})
        assert item is not None and item["item_id"] == 90000001


def test_moved_song_plan_pick_skipped(db, monkeypatch, tmp_path):
    c1, c2 = _cat_ids(db)
    picks = [{"song_id": 90000003, "artist": "C", "title": "c",
              "action": "pick", "duration_ms": 1000,
              "target_category_id": c1, "category_id": c2}]   # moved away
    eng = _engine(db, monkeypatch, tmp_path, picks)
    item = eng._pick_song({"slot_type": "song", "category_id": c1})
    assert item is None or item["item_id"] != 90000003


def test_invalidate_rotation_cache_and_generation(db):
    from core.scheduler.engine import SchedulerEngine
    eng = SchedulerEngine(db)
    eng._rot_dec_cache_key = ("x", 1, 1)
    eng._rot_dec_cache_at = 1e12
    eng._queue_dirty = False
    eng.invalidate_rotation_cache()
    assert eng._rot_dec_cache_key is None and eng._rot_dec_cache_at == 0.0
    assert eng._queue_dirty is True
    g = Database.data_generation
    db.move_songs_to_category([], None)     # no-op: no bump
    assert Database.data_generation == g


def test_queue_dirty_emitted_on_tick_not_during_peek(db, qtbot):
    from core.scheduler.engine import SchedulerEngine
    eng = SchedulerEngine(db)
    hits = []
    eng.queue_changed.connect(lambda: hits.append(1))
    eng._queue_dirty = True
    eng._suppress_queue_emit = True
    eng._on_tick()
    n_suppressed = len(hits)
    eng._suppress_queue_emit = False
    eng._on_tick()
    assert eng._queue_dirty is False
    assert len(hits) > n_suppressed


# ── 3. force clocks: shared resolver, HH:MM, exclusive end ──────────────

def test_normalize_hhmm():
    n = Database.normalize_hhmm
    assert n("9:5") == "09:05"
    assert n("09:00:00") == "09:00"
    assert n("24:00") == "24:00"
    assert n("25:00") is None and n("ab") is None and n("") is None


def test_force_clock_unpadded_and_exclusive_end(db, made):
    cid = _make_clock(db, made, "force")
    day = (datetime.now() + timedelta(days=400)).replace(
        hour=9, minute=30, second=0, microsecond=0)
    fid = db.add_force_clock(made["prefix"] + "fc", cid,
                             day.strftime("%Y-%m-%d"), "9:00", "10:00")
    made["force"].append(fid)
    hit = db.get_force_clock_for(day)
    assert hit is not None and int(hit["id"]) == fid
    assert db.get_force_clock_for(day.replace(hour=10, minute=0)) is None
    res = db.resolve_clock_for(day)
    assert res["id"] == cid and res["forced"] is True


def test_resolver_ignores_null_clock_and_delete_deactivates(db, made):
    cid = _make_clock(db, made, "force2")
    _make_clock(db, made, "keep")             # delete_clock needs >1
    day = (datetime.now() + timedelta(days=401)).replace(
        hour=12, minute=0, second=0, microsecond=0)
    fid = db.add_force_clock(made["prefix"] + "fc2", cid,
                             day.strftime("%Y-%m-%d"), "00:00", "23:59")
    made["force"].append(fid)
    assert db.get_force_clock_for(day.replace(hour=23, minute=59))
    db.delete_clock(cid)
    made["clocks"].remove(cid)
    row = db._conn().execute(
        "SELECT clock_id, is_active FROM force_clocks WHERE id = ?",
        [fid]).fetchone()
    assert row[0] is None and int(row[1]) == 0
    assert db.get_force_clock_for(day) is None


def test_engine_active_clock_uses_force(db, monkeypatch):
    from core.scheduler.engine import SchedulerEngine
    eng = SchedulerEngine(db)
    monkeypatch.setattr(db, "get_force_clock_for",
                        lambda _n: {"clock_id": 777001})
    monkeypatch.setattr(db, "get_clock",
                        lambda _i: {"name": "Forced"})
    seen = []
    eng.active_clock_changed.connect(lambda i, n: seen.append((i, n)))
    eng._check_active_clock_change()
    assert seen and seen[-1] == (777001, "Forced")


# ── 4. cursor resets when the resolved clock changes ───────────────────

def test_cursor_resets_on_clock_change(db, monkeypatch):
    from core.scheduler.engine import SchedulerEngine
    eng = SchedulerEngine(db)
    cur = {"id": 1}
    monkeypatch.setattr(
        "core.clock_resolver.resolve_clock",
        lambda _db, _now=None: {"id": cur["id"], "name": "", "forced": False})
    slots = [{"slot_type": "x"}] * 4
    monkeypatch.setattr(db, "get_clock_slots", lambda _c: slots)
    monkeypatch.setattr(eng, "_apply_category_air_time",
                        lambda s, c, n: s)
    now = datetime.now()
    eng.pick_next_item(now)
    eng._clock_slot_cursor = 3
    eng.pick_next_item(now)                   # same clock → kept
    assert eng._clock_slot_cursor == 3
    cur["id"] = 2
    eng.pick_next_item(now)                   # new clock → reset
    assert eng._clock_slot_cursor == 0


# ── 5. AUTO clock hand-edits survive build_grid ────────────────────────

def test_auto_clock_hand_edit_preserved(db, made):
    from core import auto_grid_builder as agb
    c1, _ = _cat_ids(db)
    cid = _make_clock(db, made, "auto")
    assert agb._is_builder_owned(db, cid, [c1])          # empty → owned
    db.save_clock_slots(cid, agb._template_slots(db, [c1]))
    assert agb._is_builder_owned(db, cid, [c1])          # template
    db.save_clock_slots(cid, [{"slot_type": "song", "category_id": c1},
                              {"slot_type": "song", "category_id": c1}])
    assert not agb._is_builder_owned(db, cid, [c1])      # hand-edited


# ── 6. clear-all also drops auto_grid_cells claims ──────────────────────

def test_clear_all_drops_grid_claims(db, monkeypatch):
    # Never wipe the session copy's real grid: run on a snapshot and
    # restore afterwards.
    conn = db._conn()
    db._ensure_auto_grid_tables()
    grid = [tuple(r) for r in conn.execute(
        "SELECT day_of_week, hour_start, hour_end, clock_id "
        "FROM auto_schedule").fetchall()]
    cells = [tuple(r) for r in conn.execute(
        "SELECT day_of_week, hour, clock_id FROM auto_grid_cells").fetchall()]
    try:
        clocks = list(db.get_all_clocks())
        if not clocks:
            pytest.skip("no clocks")
        db.record_auto_grid_cell(6, 3, int(clocks[0]["id"]))
        db.clear_all_auto_schedule()
        assert conn.execute(
            "SELECT COUNT(*) FROM auto_grid_cells").fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM auto_schedule").fetchone()[0] == 0
    finally:
        conn.execute("BEGIN")
        conn.execute("DELETE FROM auto_schedule")
        conn.execute("DELETE FROM auto_grid_cells")
        conn.executemany(
            "INSERT INTO auto_schedule (day_of_week, hour_start, hour_end, "
            "clock_id) VALUES (?, ?, ?, ?)", grid)
        conn.executemany(
            "INSERT INTO auto_grid_cells (day_of_week, hour, clock_id) "
            "VALUES (?, ?, ?)", cells)
        conn.commit()


def test_grid_delete_key_emits_request(qtbot):
    from PyQt6.QtCore import Qt
    from ui.auto_schedule import _ScheduleGrid
    g = _ScheduleGrid()
    qtbot.addWidget(g)
    g.select_cell(0, 5)
    with qtbot.waitSignal(g.delete_requested, timeout=500):
        qtbot.keyClick(g, Qt.Key.Key_Delete)


# ── 7. clock editor: new save switches to EDIT, keeps backup filter ────

def test_new_clock_save_twice_no_duplicate(db, made, qtbot):
    from ui.clock_editor import ClockEditor, MODE_EDIT
    ed = ClockEditor(db)
    qtbot.addWidget(ed)
    ed.load_for_mode("new")
    ed._meta.set_name(made["prefix"] + "ce")
    ed._elements = [{"element_type": "song", "duration_seconds": 240}]
    first = ed._save()
    made["clocks"].append(first)
    assert ed._mode == MODE_EDIT and ed._source_id == first
    db._conn().execute(
        "UPDATE clocks SET backup_song_filter = '{\"x\":1}' WHERE id = ?",
        [first])
    db._conn().commit()
    second = ed._save()
    assert second == first
    n = db._conn().execute("SELECT COUNT(*) FROM clocks WHERE name = ?",
                           [made["prefix"] + "ce"]).fetchone()[0]
    assert n == 1
    bf = db._conn().execute(
        "SELECT backup_song_filter FROM clocks WHERE id = ?",
        [first]).fetchone()[0]
    assert bf == '{"x":1}'
    assert not ed._editor._loop_cb.isEnabled()


# ── 10. move_songs_to_category chunks big id lists ──────────────────────

def test_move_songs_chunked(db, made):
    c1, _ = _cat_ids(db)
    sid = _make_song(db, made)
    ids = [sid] + list(range(95000000, 95002000))   # > 999 variables
    g = Database.data_generation
    assert db.move_songs_to_category(ids, c1) == 1
    assert Database.data_generation == g + 1
    assert int(db._conn().execute(
        "SELECT category_id FROM songs WHERE id = ?",
        [sid]).fetchone()[0]) == c1
