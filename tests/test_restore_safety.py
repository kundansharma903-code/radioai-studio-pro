"""
Station Restore can never apply a stale or foreign staged file silently
(QA ⚠29, operator-approved 2026-10-19).

Incident: a July `_restore.marker` + `_restore_staged.db` left in a
virtualized %LOCALAPPDATA% overlay was applied on boot months later and
replaced the live DB. Now:
  • apply only when the marker is current-format, ≤ RESTORE_MAX_AGE_H old,
    and the staged file matches its recorded size + SHA256;
  • otherwise refuse: live DB untouched, staged files KEPT, LAST_RESTORE
    says why → the post-launch notice asks the operator;
  • an applied restore is announced, naming the safety copy that sits
    next to the live DB.

All paths are redirected to tmp (same pattern as test_backup_restore).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import core.backup_restore as br
from core import dialogs


def _make_db(path: Path, song="orig-song") -> None:
    con = sqlite3.connect(str(path))
    con.executescript(
        "CREATE TABLE songs (id INTEGER PRIMARY KEY, title TEXT);"
        "CREATE TABLE categories (id INTEGER PRIMARY KEY, name TEXT);"
        "CREATE TABLE settings (key TEXT, value TEXT);"
        "CREATE TABLE campaigns (id INTEGER PRIMARY KEY, name TEXT);")
    con.execute("INSERT INTO songs (title) VALUES (?)", (song,))
    con.commit()
    con.close()


def _song(path: Path) -> str:
    con = sqlite3.connect(str(path))
    try:
        return con.execute("SELECT title FROM songs").fetchone()[0]
    finally:
        con.close()


@pytest.fixture
def env(tmp_path, monkeypatch):
    db_dir = tmp_path / "Database"
    db_dir.mkdir()
    db_path = db_dir / "radioai.db"
    import core.paths as _p
    monkeypatch.setattr(_p, "DB_PATH", db_path, raising=False)
    monkeypatch.setattr(_p, "DB_DIR", db_dir, raising=False)
    monkeypatch.setattr(_p, "BACKUPS_DIR", tmp_path / "Backups",
                        raising=False)
    _make_db(db_path, "live-song")
    backup = tmp_path / "backup.db"
    _make_db(backup, "backup-song")
    return db_path, db_dir, backup


def _staged(db_dir):
    return db_dir / "_restore_staged.db", db_dir / "_restore.marker"


def test_fresh_matching_restore_applies_and_names_safety_copy(env):
    db, db_dir, backup = env
    assert br.stage_restore(backup)
    marker = json.loads(_staged(db_dir)[1].read_text(encoding="utf-8"))
    assert marker["v"] == 2 and len(marker["sha256"]) == 64
    assert br.apply_staged_restore() is True
    assert _song(db) == "backup-song"
    st = br.LAST_RESTORE
    assert st["status"] == "applied" and st["source"] == str(backup)
    safety = Path(st["safety_copy"])
    assert safety.parent == db_dir                     # next to the live DB
    assert safety.exists() and _song(safety) == "live-song"


def test_stale_restore_is_refused_and_kept(env):
    db, db_dir, backup = env
    assert br.stage_restore(backup)
    later = datetime.now() + timedelta(hours=br.RESTORE_MAX_AGE_H + 1)
    assert br.apply_staged_restore(now=later) is False
    assert _song(db) == "live-song"                    # untouched
    staged, marker = _staged(db_dir)
    assert staged.exists() and marker.exists()         # kept, not deleted
    assert br.LAST_RESTORE["status"] == "refused"
    assert "ago" in br.LAST_RESTORE["reason"]


def test_staged_file_changed_after_staging_is_refused(env):
    db, db_dir, backup = env
    assert br.stage_restore(backup)
    staged, _ = _staged(db_dir)
    con = sqlite3.connect(str(staged))
    con.execute("UPDATE songs SET title = 'tampered'")
    con.commit()
    con.close()
    assert br.apply_staged_restore() is False
    assert _song(db) == "live-song"
    assert "does not match" in br.LAST_RESTORE["reason"]


def test_legacy_plain_text_marker_is_refused(env):
    """Exactly the incident: an old-format marker + staged DB."""
    db, db_dir, backup = env
    staged, marker = _staged(db_dir)
    staged.write_bytes(backup.read_bytes())
    marker.write_text("2026-07-09 13:20:50\nD:\\old\\backup.db\n",
                      encoding="utf-8")
    assert br.apply_staged_restore() is False
    assert _song(db) == "live-song"
    st = br.LAST_RESTORE
    assert st["status"] == "refused"
    assert st["staged_at"] == "2026-07-09 13:20:50"   # shown to operator
    assert staged.exists()


def test_marker_without_staged_file_is_a_no_op(env):
    db, db_dir, _ = env
    _staged(db_dir)[1].write_text("{}", encoding="utf-8")
    assert br.apply_staged_restore() is False
    assert br.LAST_RESTORE["status"] == "none"
    assert _song(db) == "live-song"


def test_operator_approves_refused_restore_then_it_applies(env):
    db, db_dir, backup = env
    assert br.stage_restore(backup)
    later = datetime.now() + timedelta(hours=br.RESTORE_MAX_AGE_H + 1)
    assert br.apply_staged_restore(now=later) is False
    assert br.approve_pending_restore() is True        # re-stamped now
    assert br.apply_staged_restore() is True
    assert _song(db) == "backup-song"


def test_operator_declines_sets_files_aside_not_deleted(env):
    db, db_dir, backup = env
    assert br.stage_restore(backup)
    br.discard_pending_restore()
    staged, marker = _staged(db_dir)
    assert not staged.exists() and not marker.exists()
    kept = sorted(p.name for p in db_dir.iterdir() if ".discarded_" in p.name)
    assert len(kept) == 2                              # both kept, renamed
    assert br.apply_staged_restore() is False
    assert _song(db) == "live-song"


# ── the on-screen notice ───────────────────────────────────────────────

def test_notice_applied_names_source_and_safety_copy(qapp, monkeypatch):
    from ui.restore_notice import show_restore_notice
    shown = []
    monkeypatch.setattr(dialogs, "info",
                        lambda p, title, text, **k: shown.append(text))
    out = show_restore_notice(None, {
        "status": "applied", "source": "E:\\bk\\a.db",
        "staged_at": "2026-10-19 10:00:00",
        "safety_copy": "C:\\db\\radioai.db.pre_restore_x"})
    assert out == "applied-shown"
    assert "E:\\bk\\a.db" in shown[0] and "pre_restore_x" in shown[0]


@pytest.mark.parametrize("answer, expect", [(True, "approved"),
                                            (False, "declined")])
def test_notice_refused_asks_with_safe_default(env, qapp, monkeypatch,
                                               answer, expect):
    db, db_dir, backup = env
    assert br.stage_restore(backup)
    later = datetime.now() + timedelta(hours=br.RESTORE_MAX_AGE_H + 1)
    br.apply_staged_restore(now=later)
    asked = []

    def _confirm(p, title, text, **k):
        asked.append(k)
        return answer
    monkeypatch.setattr(dialogs, "confirm", _confirm)
    monkeypatch.setattr(dialogs, "info", lambda *a, **k: None)
    from ui.restore_notice import show_restore_notice
    assert show_restore_notice(None, dict(br.LAST_RESTORE)) == expect
    assert asked[0]["default_no"] is True              # Enter/Esc = safe
    assert _song(db) == "live-song"                    # never applied live
    if answer:
        assert br.apply_staged_restore() is True       # next boot applies
