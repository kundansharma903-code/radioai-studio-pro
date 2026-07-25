"""
DB-level delete cascade for sweepers + jingles (2026-07-09).

Both libraries' ✕ Delete used to be a "Coming soon" stub because no
delete method existed. These tests pin the manual-cascade contract of
``db.delete_sweeper`` / ``db.delete_jingle``:

  • the row itself goes
  • clock_slots PINNED to it are UN-PINNED (item_id=0 +
    selection_mode='random_from_category') — a ghost item_id makes the
    scheduler's picker return None and silently skip that slot on air
  • airtime history survives (broadcast_log rows stay; only the FK link
    is cleared for jingles — sweepers have no id column there)
  • the audio FILE on disk is never touched (nothing here deletes files)

Live-DB discipline: every fixture row is prefixed
``_test_libdel_<uuid8>`` and removed in a finally block. Clocks are
dropped via the dedicated cascade-safe helper.
"""

from __future__ import annotations

import uuid

import pytest

from core.database import Database


@pytest.fixture
def db():
    return Database()


@pytest.fixture
def env(db):
    """Tracks ids created by a test so cleanup is exact (no LIKE on
    names for the destructive step — per the project's destructive-op
    protocol we delete by explicit id)."""
    created = {"sweepers": [], "jingles": [], "clocks": []}
    prefix = f"_test_libdel_{uuid.uuid4().hex[:8]}_"

    def make_sweeper(name: str = "sw", enabled: int = 1) -> int:
        conn = db._conn()
        cur = conn.execute(
            "INSERT INTO sweepers (name, category, file_path, duration_ms, "
            "position, properties, is_enabled) "
            "VALUES (?, 'Station', '', 8000, 'Bridge at End', 'Regular', ?)",
            [prefix + name, enabled])
        conn.commit()
        sid = int(cur.lastrowid)
        created["sweepers"].append(sid)
        return sid

    def make_jingle(name: str = "jg", enabled: int = 1) -> int:
        conn = db._conn()
        cur = conn.execute(
            "INSERT INTO jingles (name, category, file_path, duration_ms, "
            "properties, playlister_code, is_enabled) "
            "VALUES (?, 'Station ID', '', 5000, 'Top of Hour', '', ?)",
            [prefix + name, enabled])
        conn.commit()
        jid = int(cur.lastrowid)
        created["jingles"].append(jid)
        return jid

    def make_clock_with_pin(slot_type: str, item_id: int) -> int:
        cid = int(db.create_clock(f"{prefix}clock_{slot_type}"))
        created["clocks"].append(cid)
        db.save_clock_slots(cid, [
            {"slot_type": slot_type, "duration_seconds": 8,
             "minute_position": 0, "filter_json": "{}",
             "selection_mode": "specific", "item_id": int(item_id)},
        ])
        return cid

    env_obj = type("Env", (), {})()
    env_obj.db = db
    env_obj.prefix = prefix
    env_obj.created = created
    env_obj.make_sweeper = make_sweeper
    env_obj.make_jingle = make_jingle
    env_obj.make_clock_with_pin = make_clock_with_pin
    try:
        yield env_obj
    finally:
        conn = db._conn()
        for cid in created["clocks"]:
            try:
                conn.execute("DELETE FROM clock_slots WHERE clock_id = ?", [cid])
                conn.commit()
            except Exception:
                pass
            try:
                db.delete_clock(cid)
            except Exception:
                pass
        for sid in created["sweepers"]:
            try:
                conn.execute("DELETE FROM sweepers WHERE id = ?", [sid])
            except Exception:
                pass
        for jid in created["jingles"]:
            try:
                conn.execute("DELETE FROM jingle_linked_spots "
                             "WHERE jingle_id = ?", [jid])
            except Exception:
                pass
            try:
                conn.execute("DELETE FROM broadcast_log WHERE jingle_id = ?",
                             [jid])
                conn.execute("DELETE FROM jingles WHERE id = ?", [jid])
            except Exception:
                pass
        conn.commit()


def _row_exists(db, table: str, row_id: int) -> bool:
    row = db._conn().execute(
        f"SELECT 1 FROM {table} WHERE id = ?", [int(row_id)]).fetchone()
    return row is not None


# ── Sweepers ────────────────────────────────────────────────────────────


def test_delete_sweeper_removes_row(env):
    sid = env.make_sweeper()
    assert _row_exists(env.db, "sweepers", sid)
    env.db.delete_sweeper(sid)
    assert not _row_exists(env.db, "sweepers", sid)


def test_delete_sweeper_unpins_clock_slot(env):
    sid = env.make_sweeper()
    cid = env.make_clock_with_pin("sweeper", sid)
    assert env.db.count_sweeper_clock_slots(sid) == 1

    env.db.delete_sweeper(sid)

    slots = list(env.db.get_clock_slots(cid))
    assert len(slots) == 1                      # slot survives the delete
    assert int(slots[0]["item_id"] or 0) == 0   # …but is no longer pinned
    assert slots[0]["selection_mode"] == "random_from_category"
    assert env.db.count_sweeper_clock_slots(sid) == 0


def test_delete_sweeper_leaves_other_sweepers_alone(env):
    keep = env.make_sweeper("keep")
    drop = env.make_sweeper("drop")
    env.db.delete_sweeper(drop)
    assert _row_exists(env.db, "sweepers", keep)


def test_delete_sweeper_unknown_id_is_safe_noop(env):
    before = env.db._conn().execute(
        "SELECT COUNT(*) FROM sweepers").fetchone()[0]
    env.db.delete_sweeper(-99999)              # must not raise
    after = env.db._conn().execute(
        "SELECT COUNT(*) FROM sweepers").fetchone()[0]
    assert after == before


def test_count_sweeper_clock_slots_ignores_other_slot_types(env):
    sid = env.make_sweeper()
    # A SONG slot that happens to carry the same item_id must not count
    cid = env.make_clock_with_pin("song", sid)
    assert env.db.count_sweeper_clock_slots(sid) == 0
    env.db.delete_sweeper(sid)
    slots = list(env.db.get_clock_slots(cid))
    assert int(slots[0]["item_id"] or 0) == sid   # song slot untouched


# ── Jingles ─────────────────────────────────────────────────────────────


def test_delete_jingle_removes_row(env):
    jid = env.make_jingle()
    assert _row_exists(env.db, "jingles", jid)
    env.db.delete_jingle(jid)
    assert not _row_exists(env.db, "jingles", jid)


def test_delete_jingle_unpins_jingle_slot(env):
    jid = env.make_jingle()
    cid = env.make_clock_with_pin("jingle", jid)
    assert env.db.count_jingle_clock_slots(jid) == 1

    env.db.delete_jingle(jid)

    slots = list(env.db.get_clock_slots(cid))
    assert len(slots) == 1
    assert int(slots[0]["item_id"] or 0) == 0
    assert slots[0]["selection_mode"] == "random_from_category"


def test_delete_jingle_unpins_station_id_slot(env):
    """station_id slots pick from the jingles table too — they must be
    un-pinned as well, or the slot goes silent on air."""
    jid = env.make_jingle()
    cid = env.make_clock_with_pin("station_id", jid)
    assert env.db.count_jingle_clock_slots(jid) == 1

    env.db.delete_jingle(jid)

    slots = list(env.db.get_clock_slots(cid))
    assert int(slots[0]["item_id"] or 0) == 0


def test_delete_jingle_preserves_broadcast_log_history(env):
    """The airtime row survives; only its jingle_id link is cleared."""
    jid = env.make_jingle()
    conn = env.db._conn()
    cur = conn.execute(
        "INSERT INTO broadcast_log (entry_type, jingle_id, duration_ms) "
        "VALUES ('jingle', ?, 5000)", [jid])
    log_id = int(cur.lastrowid)
    conn.commit()
    try:
        env.db.delete_jingle(jid)
        row = conn.execute(
            "SELECT entry_type, jingle_id FROM broadcast_log WHERE id = ?",
            [log_id]).fetchone()
        assert row is not None                  # history preserved
        assert row["jingle_id"] is None         # link cleared
        assert row["entry_type"] == "jingle"
    finally:
        conn.execute("DELETE FROM broadcast_log WHERE id = ?", [log_id])
        conn.commit()


def test_delete_jingle_unknown_id_is_safe_noop(env):
    before = env.db._conn().execute(
        "SELECT COUNT(*) FROM jingles").fetchone()[0]
    env.db.delete_jingle(-99999)
    after = env.db._conn().execute(
        "SELECT COUNT(*) FROM jingles").fetchone()[0]
    assert after == before


def test_delete_jingle_leaves_other_jingles_alone(env):
    keep = env.make_jingle("keep")
    drop = env.make_jingle("drop")
    env.db.delete_jingle(drop)
    assert _row_exists(env.db, "jingles", keep)
