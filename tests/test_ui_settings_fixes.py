"""
Focused tests for the 2026-10-17 UI/settings fix batch:

  • Songs Library — no 400-row cap, disabled songs reachable + re-enable,
    filters combine with search and survive a reload.
  • Scheduled auto-backup (interval / folder / retention / due check),
    MainWindow background trigger, last-backup display.
  • Pre-restore safety copy includes WAL data; restore aborts when no
    safety copy can be made.
  • Final Log station label + branding refresh; rotation_health branding.
  • Dead settings visibly marked "not active"; honest save dialogs;
    Studio defaults match the runtime; default fallback track picker.

All DB access runs on the conftest live-DB shield copy; every row/key a
test changes is restored afterwards.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.database import Database
from core.settings import Settings
from core import dialogs as _dialogs


@pytest.fixture
def db():
    return Database()


@pytest.fixture
def keys_snapshot(db):
    """Restore any settings key a test writes."""
    s = Settings()
    s.reload(db)
    saved = {}

    def remember(*keys):
        for k in keys:
            saved.setdefault(k, s.get(k))
    yield remember
    for k, v in saved.items():
        s.set(k, "" if v is None else v)


@pytest.fixture
def one_song(db):
    """An enabled song id; its is_enabled is restored afterwards."""
    rows = db.get_songs()
    if not rows:
        pytest.skip("no songs in DB")
    sid = int(rows[0]["id"])
    yield sid
    db.set_songs_enabled([sid], True)


def _silence(monkeypatch):
    for fn in ("info", "warning", "error"):
        monkeypatch.setattr(_dialogs, fn, lambda *a, **k: None)


# ── Songs Library ───────────────────────────────────────────────────────

def test_get_songs_include_disabled(db, one_song):
    db.set_songs_enabled([one_song], False)
    assert one_song not in {r["id"] for r in db.get_songs()}
    assert one_song in {r["id"] for r in
                        db.get_songs(include_disabled=True)}


def test_library_loads_whole_library_no_cap(qapp, db):
    from ui.songs_library import SongsLibrary
    total = db._conn().execute("SELECT COUNT(*) FROM songs").fetchone()[0]
    s = SongsLibrary(db)
    try:
        assert len(s._all_songs) == total
    finally:
        s.deleteLater()


def test_disabled_filter_and_reenable(qapp, db, one_song):
    from ui.songs_library import SongsLibrary
    db.set_songs_enabled([one_song], False)
    s = SongsLibrary(db)
    try:
        def visible_ids():
            return {r._song["id"] for r in s._row_widgets
                    if not r.isHidden()}
        # Default "Only Enabled" hides it …
        assert one_song not in visible_ids()
        # … the Disabled filter finds it.
        s._dropdowns["enabled"].setCurrentText("Disabled")
        assert one_song in visible_ids()
        assert all(not r._song["is_enabled"] for r in s._row_widgets
                   if not r.isHidden())
        # Re-enable via the context-menu action path.
        s._set_enabled([one_song], True)
        assert one_song not in visible_ids()     # filter still Disabled
        s._dropdowns["enabled"].setCurrentText("Only Enabled")
        assert one_song in visible_ids()
    finally:
        s.deleteLater()


def test_filters_combine_and_survive_reload(qapp, db):
    from ui.songs_library import SongsLibrary
    s = SongsLibrary(db)
    try:
        songs = [x for x in s._all_songs if x.get("category")
                 and x.get("is_enabled") and (x["title"] or x["artist"])]
        if not songs:
            pytest.skip("no categorised songs")
        target = songs[0]
        cat = target["category"]
        word = (target["title"] or target["artist"]).split()[0].lower()
        s._dropdowns["category"].setCurrentText(cat)
        s._search_input.setText(word)
        # Changing ANOTHER filter must not drop the category filter.
        s._dropdowns["bpm"].setCurrentIndex(0)

        def check():
            vis = [r._song for r in s._row_widgets if not r.isHidden()]
            assert vis, "expected at least the target row"
            for x in vis:
                assert x["category"] == cat
                assert word in f"{x['title']} {x['artist']}".lower()
            return vis
        before = check()
        s._load_songs()                       # reload keeps filters
        after = check()
        assert [x["id"] for x in before] == [x["id"] for x in after]
    finally:
        s.deleteLater()


def test_reload_keeps_selection_and_cues_saved_refreshes(qapp, db,
                                                          monkeypatch):
    from ui.songs_library import SongsLibrary
    s = SongsLibrary(db)
    try:
        if len(s._all_songs) < 3:
            pytest.skip("need 3 songs")
        sid = s._all_songs[2]["id"]
        s._select_song(sid)
        calls = []
        orig = s._load_songs
        monkeypatch.setattr(s, "_load_songs",
                            lambda: (calls.append(1), orig()))
        s._on_cues_saved(sid)
        assert calls == [1]
        assert s._selected_id == sid
    finally:
        s.deleteLater()


# ── Scheduled auto-backup ───────────────────────────────────────────────

def _make_radioai_db(path: Path, marker: str = "x", wal: bool = False):
    con = sqlite3.connect(str(path))
    if wal:
        con.execute("PRAGMA journal_mode=WAL")
    con.executescript(
        "CREATE TABLE songs (id INTEGER PRIMARY KEY, title TEXT);"
        "CREATE TABLE categories (id INTEGER PRIMARY KEY, name TEXT);"
        "CREATE TABLE settings (key TEXT, value TEXT);"
        "CREATE TABLE campaigns (id INTEGER PRIMARY KEY, name TEXT);")
    con.execute("INSERT INTO songs (title) VALUES (?)", (marker,))
    con.commit()
    con.close()


@pytest.fixture
def br_paths(tmp_path, monkeypatch):
    import core.paths as _p
    db_dir = tmp_path / "Database"
    db_dir.mkdir()
    db_path = db_dir / "radioai.db"
    monkeypatch.setattr(_p, "DB_PATH", db_path, raising=False)
    monkeypatch.setattr(_p, "DB_DIR", db_dir, raising=False)
    monkeypatch.setattr(_p, "BACKUPS_DIR", tmp_path / "Backups",
                        raising=False)
    return tmp_path, db_path


def test_interval_and_folder_resolution(br_paths):
    from core import backup_restore as br
    assert br.interval_hours("Every 6 hours") == 6
    assert br.interval_hours("Every 7 days") == 168
    assert br.interval_hours("Manual only") is None
    auto = br.default_auto_backup_dir()
    assert br.resolve_auto_backup_dir("") == auto
    assert br.resolve_auto_backup_dir("C:\\RadioAI\\Backups\\") == auto
    assert br.resolve_auto_backup_dir("D:\\Station") == Path("D:\\Station")


def test_run_auto_backup_writes_prunes_and_reports(br_paths):
    from core import backup_restore as br
    tmp, db_path = br_paths
    _make_radioai_db(db_path)
    dest = tmp / "dest"
    dest.mkdir()
    # 8 stale auto files → prune to the newest 7 after the new one.
    for i in range(8):
        f = dest / f"radioai_auto_2020010{i}.db"
        shutil.copy2(db_path, f)
        old = time.time() - (10 - i) * 86400
        os.utime(f, (old, old))
    assert br.auto_backup_due(dest, 24) is True
    out = br.run_auto_backup(dest)
    assert out and br.is_valid_radioai_db(out)
    files = list(dest.glob("radioai_auto_*.db"))
    assert len(files) == br.AUTO_BACKUP_KEEP
    assert Path(out) in files
    assert not list(dest.glob("*.partial"))
    assert br.auto_backup_due(dest, 24) is False
    assert br.auto_backup_due(dest, None) is False
    assert br.auto_backup_due(
        dest, 24, now=datetime.now() + timedelta(hours=25)) is True
    assert br.latest_auto_backup_time(dest) == datetime.fromtimestamp(
        Path(out).stat().st_mtime).strftime("%Y-%m-%d %H:%M")


def test_main_window_check_runs_backup_off_thread(monkeypatch):
    from core import backup_restore as br
    from ui.main_window import MainWindow
    ran = []
    done = threading.Event()
    monkeypatch.setattr(br, "auto_backup_due", lambda d, h: True)
    monkeypatch.setattr(
        br, "run_auto_backup",
        lambda d: (ran.append(threading.current_thread().name),
                   done.set()))
    stub = SimpleNamespace(_shutting_down=False, _auto_backup_busy=False)
    assert MainWindow._check_auto_backup(stub) is True
    assert done.wait(5)
    assert ran and ran[0] == "auto-backup"
    for _ in range(50):
        if not stub._auto_backup_busy:
            break
        time.sleep(0.02)
    assert stub._auto_backup_busy is False
    # Not due → nothing started; shutting down → nothing started.
    monkeypatch.setattr(br, "auto_backup_due", lambda d, h: False)
    assert MainWindow._check_auto_backup(stub) is False
    stub._shutting_down = True
    assert MainWindow._check_auto_backup(stub) is False


# ── Restore safety copy ─────────────────────────────────────────────────

def test_pre_restore_copy_includes_wal_data(br_paths, tmp_path):
    from core import backup_restore as br
    _tmp, db_path = br_paths
    # Build a live DB whose newest row lives ONLY in the WAL.
    src = tmp_path / "src.db"
    _make_radioai_db(src, marker="old", wal=True)
    con = sqlite3.connect(str(src))
    con.execute("PRAGMA wal_autocheckpoint=0")
    con.execute("INSERT INTO songs (title) VALUES ('in-wal-only')")
    con.commit()
    shutil.copy2(src, db_path)
    shutil.copy2(str(src) + "-wal", str(db_path) + "-wal")
    con.close()
    backup = tmp_path / "backup.db"
    _make_radioai_db(backup, marker="restored")
    assert br.stage_restore(backup)
    assert br.apply_staged_restore() is True
    pre = list(db_path.parent.glob("radioai.db.pre_restore_*"))
    assert pre
    c = sqlite3.connect(str(pre[0]))
    titles = {r[0] for r in c.execute("SELECT title FROM songs")}
    c.close()
    assert "in-wal-only" in titles


def test_restore_aborts_when_safety_copy_fails(br_paths, tmp_path,
                                               monkeypatch):
    from core import backup_restore as br
    _tmp, db_path = br_paths
    _make_radioai_db(db_path, marker="current")
    backup = tmp_path / "backup.db"
    _make_radioai_db(backup, marker="restored")
    assert br.stage_restore(backup)

    real_connect = sqlite3.connect

    def bad_connect(target, *a, **k):
        if ".pre_restore_" in str(target):
            raise sqlite3.OperationalError("disk full")
        return real_connect(target, *a, **k)
    monkeypatch.setattr(br.sqlite3, "connect", bad_connect)
    monkeypatch.setattr(
        br.shutil, "copy2",
        lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    assert br.apply_staged_restore() is False
    monkeypatch.undo()
    c = sqlite3.connect(str(db_path))
    titles = {r[0] for r in c.execute("SELECT title FROM songs")}
    c.close()
    assert titles == {"current"}


# ── Final Log + branding ────────────────────────────────────────────────

def test_final_log_station_label_and_branding_refresh(qapp, db):
    from PyQt6.QtWidgets import QLabel, QWidget
    from ui.final_log import FinalLog
    from ui.main_window import MainWindow
    fl = FinalLog(db)
    rh = QWidget()
    lbl = QLabel("old", rh)
    lbl.setObjectName("hdr_station_lbl")
    try:
        expected = Settings().station_display
        if expected:
            assert fl._tab_bar._station.text() == expected
        fl._tab_bar._station.setText("stale")
        stub = SimpleNamespace(final_log=fl, rotation_health=rh)
        MainWindow._refresh_station_branding(stub)
        assert fl._tab_bar._station.text() == (expected or "")
        assert lbl.text() == (expected or "")
    finally:
        fl.deleteLater()
        rh.deleteLater()


# ── General Settings ────────────────────────────────────────────────────

def test_general_dead_controls_marked_and_caption(qapp, db):
    from ui.settings_general import SettingsGeneral
    from ui.widgets.not_active import NOT_ACTIVE_TIP
    s = SettingsGeneral(db)
    try:
        for w in s._inactive_controls():
            assert not w.isEnabled()
            assert w.toolTip() == NOT_ACTIVE_TIP
        for w in (s._fld_name, s._fld_freq, s._fld_slogan,
                  s._fld_path_recordings, s._tg_auto_mode,
                  s._cmb_backup_interval, s._fld_backup_path):
            assert w.isEnabled()
        assert "Used in RDS" not in s._fld_slogan._cap.text()
        assert s._lbl_last_backup.text().startswith("Last auto-backup:")
        from core import backup_restore as br
        stored = Settings().get("path_backup", "") or ""
        assert s._fld_backup_path.text() == str(
            br.resolve_auto_backup_dir(stored))
    finally:
        s.deleteLater()


def test_general_restore_button_label(qapp, db, monkeypatch, tmp_path):
    from ui import settings_general as sg
    seen = {}
    monkeypatch.setattr(
        sg.QFileDialog, "getOpenFileName",
        staticmethod(lambda *a, **k: (str(tmp_path / "x.db"), "")))

    def fake_confirm(*a, **k):
        seen.update(k)
        return False
    monkeypatch.setattr(_dialogs, "confirm", fake_confirm)
    s = sg.SettingsGeneral(db)
    try:
        s._on_restore_backup()
        assert seen.get("yes_label") == "Restore on Next Launch"
    finally:
        s.deleteLater()


# ── Studio Settings ─────────────────────────────────────────────────────

def test_studio_dead_controls_marked_live_ones_kept(qapp, db):
    from ui.settings_studio import SettingsStudio
    s = SettingsStudio(db)
    try:
        for w in s._inactive_controls():
            assert not w.isEnabled()
        for w in (s._sl_crossfade, s._sl_fade_out, s._cmb_automix,
                  s._cmb_fallback, s._tg_missing_alert, s._sl_master,
                  s._tg_show_preview, s._tg_flash_mix, s._fallback_path):
            assert w.isEnabled()
    finally:
        s.deleteLater()


def test_studio_defaults_match_runtime(qapp, db, monkeypatch):
    from ui.settings_studio import SettingsStudio
    s = SettingsStudio(db)
    try:
        monkeypatch.setattr(Settings, "get_int",
                            lambda self, k, d=0: d)
        s._load_settings()
        assert s._sl_crossfade.value() == 5
        assert s._sl_fade_out.value() == 5
    finally:
        s.deleteLater()


def test_studio_fallback_path_saved_and_honest_dialogs(
        qapp, db, monkeypatch, keys_snapshot):
    from ui.settings_studio import SettingsStudio
    keys_snapshot("default_fallback_path", "crossfade_duration",
                  "fade_out_start", "fade_curve_type", "load_next_song",
                  "preload_buffer", "automix_trigger", "fallback_action",
                  "missing_file_alert", "cue_split_mode",
                  "show_crossfade_preview", "flash_mix_point")
    msgs = []
    monkeypatch.setattr(_dialogs, "info",
                        lambda *a, **k: msgs.append(a[2]))
    s = SettingsStudio(db)
    try:
        s._fallback_path.set_path("C:\\Audio\\fallback.mp3")
        s._on_save_left()
        assert Settings().get("default_fallback_path") == \
            "C:\\Audio\\fallback.mp3"
        s._on_save_right()
        assert "audio engine preferences" not in msgs[-1].lower()
    finally:
        s.deleteLater()


# ── Soundcard ───────────────────────────────────────────────────────────

def test_soundcard_only_output1_device_active(qapp, db):
    from ui.settings_soundcard import SettingsSoundcard
    s = SettingsSoundcard(db)
    try:
        o1 = s._cards["output_1"]
        assert o1._cmb_device.isEnabled()
        assert not o1._sl_vol.isEnabled()
        assert not o1._cmb_channel.isEnabled()
        for k in ("output_2", "output_3", "output_4", "input_1"):
            assert not s._cards[k]._cmb_device.isEnabled()
        for c in s._cards.values():
            assert "Connected" not in c._status_lbl.text()
        assert not s._btn_test_all.isEnabled()
    finally:
        s.deleteLater()
