"""
core/backup_restore.py — Station Backup & Restore.

Pinned behaviour (operator-approved 2026-07-09):
  • backup_now copies the live DB to a timestamped file in the chosen
    folder; the copy is a valid RadioAI DB.
  • is_valid_radioai_db accepts a real DB, rejects junk / wrong files.
  • stage_restore validates first (bad file rejected, nothing staged),
    then stages a good file + writes the marker WITHOUT touching the
    live DB.
  • apply_staged_restore swaps the DB at boot, keeps a pre-restore
    safety copy, clears WAL/SHM + the staging slot, and round-trips the
    restored data. No-op when nothing is staged.

All paths are redirected to a tmp dir so the real %LOCALAPPDATA% DB is
never touched.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import core.backup_restore as br


def _make_db(path: Path, marker_song="orig-song") -> None:
    con = sqlite3.connect(str(path))
    con.executescript(
        "CREATE TABLE songs (id INTEGER PRIMARY KEY, title TEXT);"
        "CREATE TABLE categories (id INTEGER PRIMARY KEY, name TEXT);"
        "CREATE TABLE settings (key TEXT, value TEXT);"
        "CREATE TABLE campaigns (id INTEGER PRIMARY KEY, name TEXT);")
    con.execute("INSERT INTO songs (title) VALUES (?)", (marker_song,))
    con.commit()
    con.close()


@pytest.fixture
def paths(tmp_path, monkeypatch):
    """Redirect DB_PATH / DB_DIR / BACKUPS_DIR into tmp."""
    db_dir = tmp_path / "Database"
    db_dir.mkdir()
    db_path = db_dir / "radioai.db"
    backups = tmp_path / "Backups"
    import core.paths as _p
    monkeypatch.setattr(_p, "DB_PATH", db_path, raising=False)
    monkeypatch.setattr(_p, "DB_DIR", db_dir, raising=False)
    monkeypatch.setattr(_p, "BACKUPS_DIR", backups, raising=False)
    return tmp_path, db_path, db_dir


# ── Validation ──────────────────────────────────────────────────────────

def test_is_valid_accepts_real_and_rejects_junk(paths, tmp_path):
    _, db_path, _ = paths
    _make_db(db_path)
    assert br.is_valid_radioai_db(db_path)
    junk = tmp_path / "junk.db"
    junk.write_bytes(b"not a database at all" * 100)
    assert not br.is_valid_radioai_db(junk)
    assert not br.is_valid_radioai_db(tmp_path / "missing.db")


# ── Backup ──────────────────────────────────────────────────────────────

def test_backup_now_writes_valid_copy(paths, tmp_path):
    _, db_path, _ = paths
    _make_db(db_path)
    dest = tmp_path / "MyDrive"
    out = br.backup_now(str(dest))
    assert out is not None
    p = Path(out)
    assert p.exists() and p.name.startswith("RadioAI_backup_")
    assert br.is_valid_radioai_db(p)


def test_backup_now_no_db_returns_none(paths):
    assert br.backup_now(str(paths[0] / "x")) is None


# ── Stage + apply restore ───────────────────────────────────────────────

def test_stage_rejects_bad_file(paths, tmp_path):
    _, db_path, _ = paths
    _make_db(db_path)
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"garbage")
    assert br.stage_restore(bad) is False
    assert not br.has_pending_restore()


def test_stage_then_apply_roundtrip(paths, tmp_path):
    _, db_path, _ = paths
    _make_db(db_path, marker_song="CURRENT")
    # a different backup with distinct data
    backup = tmp_path / "backup.db"
    _make_db(backup, marker_song="RESTORED-DATA")

    assert br.stage_restore(backup) is True
    assert br.has_pending_restore()
    # live DB still untouched until apply
    con = sqlite3.connect(str(db_path))
    assert con.execute("SELECT title FROM songs").fetchone()[0] == \
        "CURRENT"
    con.close()

    assert br.apply_staged_restore() is True
    # restored data now live
    con = sqlite3.connect(str(db_path))
    assert con.execute("SELECT title FROM songs").fetchone()[0] == \
        "RESTORED-DATA"
    con.close()
    # staging cleared + a pre-restore safety copy kept
    assert not br.has_pending_restore()
    assert list(db_path.parent.glob("radioai.db.pre_restore_*"))


def test_apply_noop_when_nothing_staged(paths):
    assert br.apply_staged_restore() is False


def test_apply_clears_stale_wal(paths, tmp_path):
    _, db_path, _ = paths
    _make_db(db_path, marker_song="CURRENT")
    (Path(str(db_path) + "-wal")).write_bytes(b"stale-wal")
    (Path(str(db_path) + "-shm")).write_bytes(b"stale-shm")
    backup = tmp_path / "b.db"
    _make_db(backup, marker_song="NEW")
    br.stage_restore(backup)
    assert br.apply_staged_restore() is True
    assert not Path(str(db_path) + "-wal").exists()
    assert not Path(str(db_path) + "-shm").exists()
