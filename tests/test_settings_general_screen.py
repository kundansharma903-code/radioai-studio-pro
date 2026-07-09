"""
General Settings screen (Figma 68:2) tests.

Pinned behaviour:
  • SettingsGeneral constructs on a real DB without crashing.
  • _load_settings populates form widgets from current DB values.
  • _on_save_station writes the station-identity + path fields back
    to the DB via Settings().set(); right-column fields are NOT
    touched (round-trip + isolation).
  • _on_save_all writes both column groups; round-trip preserves
    every key.
  • Toggle on/off state is correctly persisted as '1'/'0' so the
    Settings.get_bool reader keeps working.
  • time_format shorthand round-trip — UI label "24-hour (HH:MM:SS)"
    maps to DB value "24h" and vice-versa.
  • Backup Now / Restore Backup show the v1.1 placeholder dialog.

Live-DB tests snapshot every key they touch before the test and
restore on teardown, so the dev DB stays consistent.
"""

from __future__ import annotations

import pytest

from core.database import Database
from core.settings import Settings
from core import dialogs as _dialogs


# Keys this screen touches — used by the snapshot/restore fixture.
TOUCHED_KEYS = (
    "station_name", "station_city", "station_region",
    "station_frequency", "station_slogan", "station_email",
    "path_music", "path_recordings", "path_logs", "path_exports",
    "path_backup",
    "start_on_windows_startup", "auto_load_last_session",
    "start_in_auto_mode", "show_splash_screen",
    "minimize_to_tray", "check_updates", "send_usage_stats",
    "date_format", "time_format", "timezone", "language",
    "backup_interval",
)


@pytest.fixture
def db():
    return Database()


@pytest.fixture
def settings_snapshot(db):
    """Snapshot the keys the screen touches; restore after the test so
    edits during a test don't leak across runs."""
    s = Settings()
    s.reload(db)
    before = {k: s.get(k) for k in TOUCHED_KEYS}
    yield before
    # Restore
    for k, v in before.items():
        if v is None:
            continue
        s.set(k, v)
    s.reload(db)


# ── Smoke ──────────────────────────────────────────────────────────────


def test_construction_does_not_crash(qapp, db):
    from ui.settings_general import SettingsGeneral
    s = SettingsGeneral(db)
    assert s.size().width() == 1440
    assert s.size().height() == 900
    s.deleteLater()


def test_load_settings_populates_fields(qapp, db, settings_snapshot):
    from ui.settings_general import SettingsGeneral
    # Seed known values
    sett = Settings()
    sett.set("station_name", "TEST FM 88.1")
    sett.set("station_city", "TestCity")
    sett.set("path_music", "C:\\Test\\Music\\")
    sett.set("start_on_windows_startup", "1")
    sett.set("date_format", "YYYY-MM-DD")
    sett.reload(db)

    s = SettingsGeneral(db)
    assert s._fld_name.text() == "TEST FM 88.1"
    assert s._fld_city.text() == "TestCity"
    assert s._fld_path_music.text() == "C:\\Test\\Music\\"
    assert s._tg_win_startup.is_on() is True
    assert s._cmb_date_fmt.current_text() == "YYYY-MM-DD"
    s.deleteLater()


# ── Save left column (station identity + file paths) ──────────────────


def test_save_station_writes_left_column_keys(
        qapp, db, settings_snapshot, monkeypatch):
    from ui.settings_general import SettingsGeneral
    from PyQt6.QtWidgets import QMessageBox
    monkeypatch.setattr(_dialogs, "info",
                         staticmethod(lambda *a, **k: 0))

    s = SettingsGeneral(db)
    s._fld_name.set_text("SAVED FM")
    s._fld_city.set_text("Saved City")
    s._fld_path_music.set_text("C:\\Saved\\Music\\")
    s._on_save_station()

    sett = Settings()
    sett.reload(db)
    assert sett.get("station_name") == "SAVED FM"
    assert sett.get("station_city") == "Saved City"
    assert sett.get("path_music") == "C:\\Saved\\Music\\"
    s.deleteLater()


def test_save_station_does_not_touch_right_column(
        qapp, db, settings_snapshot, monkeypatch):
    from ui.settings_general import SettingsGeneral
    from PyQt6.QtWidgets import QMessageBox
    monkeypatch.setattr(_dialogs, "info",
                         staticmethod(lambda *a, **k: 0))

    sett = Settings()
    sett.set("timezone", "UTC")
    sett.reload(db)

    s = SettingsGeneral(db)
    # Mutate timezone in the UI but call SAVE STATION only — DB value
    # should remain the pre-save UTC.
    s._cmb_tz.set_current_text("JST — Asia/Tokyo (UTC+9)")
    s._on_save_station()

    sett.reload(db)
    assert sett.get("timezone") == "UTC"
    s.deleteLater()


# ── Save all (both columns) ────────────────────────────────────────────


def test_save_all_writes_every_key(
        qapp, db, settings_snapshot, monkeypatch):
    from ui.settings_general import SettingsGeneral
    from PyQt6.QtWidgets import QMessageBox
    monkeypatch.setattr(_dialogs, "info",
                         staticmethod(lambda *a, **k: 0))

    s = SettingsGeneral(db)
    s._fld_name.set_text("ALL FM")
    s._tg_check_updates.set_on(False)
    s._cmb_lang.set_current_text("Hindi")
    s._cmb_backup_interval.set_current_text("Every 7 days")
    s._on_save_all()

    sett = Settings()
    sett.reload(db)
    assert sett.get("station_name") == "ALL FM"
    assert sett.get_bool("check_updates") is False
    assert sett.get("language") == "Hindi"
    assert sett.get("backup_interval") == "Every 7 days"
    s.deleteLater()


def test_toggle_persists_as_bool_string(
        qapp, db, settings_snapshot, monkeypatch):
    from ui.settings_general import SettingsGeneral
    from PyQt6.QtWidgets import QMessageBox
    monkeypatch.setattr(_dialogs, "info",
                         staticmethod(lambda *a, **k: 0))

    s = SettingsGeneral(db)
    s._tg_auto_mode.set_on(True)
    s._on_save_all()
    sett = Settings()
    sett.reload(db)
    assert sett.get_bool("start_in_auto_mode") is True
    # Off path
    s._tg_auto_mode.set_on(False)
    s._on_save_all()
    sett.reload(db)
    assert sett.get_bool("start_in_auto_mode") is False
    s.deleteLater()


def test_time_format_shorthand_round_trip(
        qapp, db, settings_snapshot, monkeypatch):
    from ui.settings_general import SettingsGeneral
    from PyQt6.QtWidgets import QMessageBox
    monkeypatch.setattr(_dialogs, "info",
                         staticmethod(lambda *a, **k: 0))

    sett = Settings()
    sett.set("time_format", "24h")
    sett.reload(db)
    s = SettingsGeneral(db)
    # UI displays the long-form label
    assert "24-hour" in s._cmb_time_fmt.current_text()
    # Switch to 12-hour and save — DB gets '12h'
    s._cmb_time_fmt.set_current_text("12-hour (HH:MM:SS AM/PM)")
    s._on_save_all()
    sett.reload(db)
    assert sett.get("time_format") == "12h"
    s.deleteLater()


# ── Backup / Restore (real wiring, 2026-07-09) ──────────────────────────


def test_backup_now_writes_file(qapp, db, monkeypatch, tmp_path):
    """Backup Now → folder picker → backup_now() writes a file and
    reports success (no more 'coming soon' stub)."""
    from ui.settings_general import SettingsGeneral
    from PyQt6.QtWidgets import QFileDialog
    import core.backup_restore as _br
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory",
        staticmethod(lambda *a, **k: str(tmp_path)))
    monkeypatch.setattr(_br, "backup_now",
                        lambda folder: str(tmp_path / "out.db"))
    info = []
    monkeypatch.setattr(_dialogs, "info",
                        staticmethod(lambda *a, **k: info.append(a)))
    s = SettingsGeneral(db)
    s._on_backup_now()
    assert info and "Backup complete" in info[0][1]
    s.deleteLater()


def test_restore_stages_and_prompts_restart(qapp, db, monkeypatch,
                                             tmp_path):
    """Restore → file picker → confirm → stage_restore() → 'restart to
    apply' info. The live DB is never mutated in-session."""
    from ui.settings_general import SettingsGeneral
    from PyQt6.QtWidgets import QFileDialog
    import core.backup_restore as _br
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName",
        staticmethod(lambda *a, **k: (str(tmp_path / "b.db"), "")))
    monkeypatch.setattr(_dialogs, "confirm",
                        staticmethod(lambda *a, **k: True))
    staged = []
    monkeypatch.setattr(_br, "stage_restore",
                        lambda f: staged.append(f) or True)
    info = []
    monkeypatch.setattr(_dialogs, "info",
                        staticmethod(lambda *a, **k: info.append(a)))
    s = SettingsGeneral(db)
    s._on_restore_backup()
    assert staged and info and "staged" in info[0][2].lower()
    s.deleteLater()


# ── Reload path ────────────────────────────────────────────────────────


def test_reload_repopulates_after_external_change(
        qapp, db, settings_snapshot, monkeypatch):
    from ui.settings_general import SettingsGeneral
    s = SettingsGeneral(db)
    # External change (simulating SQL edit / another panel)
    sett = Settings()
    sett.set("station_name", "EXTERNAL FM")
    s.reload()
    assert s._fld_name.text() == "EXTERNAL FM"
    s.deleteLater()
