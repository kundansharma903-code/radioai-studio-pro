"""
Aircheck Recorder (hourly broadcast logger) tests.

Pinned behaviour:
  • resolve_record_device ladder: manual override → playback-name match
    → first loopback → (-1, reason).
  • hour_file_stem produces aircheck_YYYY-MM-DD_HH-00.
  • recordings_root: path_recordings setting wins; empty falls back to
    APP_DATA_ROOT/Recordings.
  • WAV lifecycle: open writes a valid 44.1k/16-bit/stereo header;
    close finalizes; an empty hour file (header only) is deleted.
  • Retention prune deletes date folders older than the window, keeps
    newer ones and ignores non-date folders.
  • start() with aircheck_enabled=0 no-ops and reports state_changed
    (False, reason) without touching BASS record.
  • SettingsSoundcard aircheck block: widgets exist, save→load
    round-trips the four settings keys.
  • Studio header REC pill: set_rec_state flips the painted state.

NO test starts a real BASS recording — that is hardware/session
dependent (loopback availability) and belongs to the operator's smoke
test, not CI.
"""

from __future__ import annotations

import wave
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from core.aircheck_recorder import (
    AircheckRecorder, hour_file_stem, resolve_record_device,
    RECORD_FREQ, RECORD_CHANS, SAMPLE_BYTES,
)
from core.settings import Settings


LOOPBACKS = [
    (4, "OUT 1-4 (BEHRINGER UMC 404HD)"),
    (7, "OUT 1-2 (BEHRINGER UMC 404HD)"),
    (6, "Speakers (Realtek High Definition Audio)"),
]


# ── resolve_record_device ladder ─────────────────────────────────────────────

def test_resolve_override_wins():
    dev, name = resolve_record_device(
        "OUT 1-2 (BEHRINGER UMC 404HD)", LOOPBACKS,
        override_name="Speakers (Realtek High Definition Audio)")
    assert (dev, name) == (6, "Speakers (Realtek High Definition Audio)")


def test_resolve_follows_playback_name():
    dev, name = resolve_record_device(
        "OUT 1-2 (BEHRINGER UMC 404HD)", LOOPBACKS)
    assert (dev, name) == (7, "OUT 1-2 (BEHRINGER UMC 404HD)")


def test_resolve_falls_back_to_first_loopback():
    dev, name = resolve_record_device("Nonexistent Device", LOOPBACKS)
    assert (dev, name) == (4, "OUT 1-4 (BEHRINGER UMC 404HD)")


def test_resolve_bad_override_still_follows_playback():
    dev, name = resolve_record_device(
        "Speakers (Realtek High Definition Audio)", LOOPBACKS,
        override_name="Unplugged USB Interface")
    assert dev == 6


def test_resolve_no_loopbacks_reports_failure():
    dev, reason = resolve_record_device("OUT 1-2", [])
    assert dev == -1
    assert "loopback" in reason


# ── File naming ──────────────────────────────────────────────────────────────

def test_hour_file_stem_format():
    assert hour_file_stem(datetime(2026, 7, 2, 18, 42, 31)) == "18-00"
    assert hour_file_stem(datetime(2026, 7, 2, 0, 5, 0)) == "00-00"
    assert hour_file_stem(datetime(2026, 7, 2, 10, 0, 0)) == "10-00"


def test_hour_file_dir_month_then_date(tmp_path):
    from core.aircheck_recorder import hour_file_dir
    d = hour_file_dir(tmp_path, datetime(2026, 7, 2, 16, 30, 0))
    assert d == tmp_path / "2026-07" / "2026-07-02"


# ── recordings_root ──────────────────────────────────────────────────────────

@pytest.fixture
def _restore_settings():
    s = Settings()
    keys = ("path_recordings", "aircheck_enabled",
            "aircheck_retention_days")
    before = {k: s.get(k) for k in keys}
    yield s
    for k, v in before.items():
        s.set(k, v if v is not None else "")


def test_recordings_root_uses_setting(qapp, _restore_settings, tmp_path):
    _restore_settings.set("path_recordings", str(tmp_path))
    rec = AircheckRecorder()
    assert rec.recordings_root() == tmp_path


def test_recordings_root_default_when_blank(qapp, _restore_settings):
    _restore_settings.set("path_recordings", "")
    from core.paths import APP_DATA_ROOT
    rec = AircheckRecorder()
    assert rec.recordings_root() == APP_DATA_ROOT / "Recordings"


# ── WAV lifecycle ────────────────────────────────────────────────────────────

def test_wav_open_write_close(qapp, _restore_settings, tmp_path):
    _restore_settings.set("path_recordings", str(tmp_path))
    rec = AircheckRecorder()
    now = datetime(2026, 7, 2, 18, 0, 5)
    assert rec._open_hour_file(now)
    expected = tmp_path / "2026-07" / "2026-07-02" / "18-00.wav"
    assert rec.current_file == str(expected)

    # Simulate the RECORDPROC delivering one second of silence
    one_sec = b"\x00" * (RECORD_FREQ * RECORD_CHANS * SAMPLE_BYTES)
    with rec._file_lock:
        rec._wav.writeframesraw(one_sec)

    done = rec._close_wav()
    assert done == expected and expected.exists()
    with wave.open(str(expected), "rb") as w:
        assert w.getframerate() == RECORD_FREQ
        assert w.getnchannels() == RECORD_CHANS
        assert w.getsampwidth() == SAMPLE_BYTES
        assert w.getnframes() == RECORD_FREQ


def test_empty_hour_file_deleted_on_close(qapp, _restore_settings,
                                          tmp_path):
    _restore_settings.set("path_recordings", str(tmp_path))
    rec = AircheckRecorder()
    assert rec._open_hour_file(datetime(2026, 7, 2, 19, 0, 0))
    path = Path(rec.current_file)
    done = rec._close_wav()          # no frames written → header only
    assert done is None
    assert not path.exists()


# ── Retention prune ──────────────────────────────────────────────────────────

def test_prune_deletes_only_expired_date_folders(qapp, _restore_settings,
                                                 tmp_path):
    """Month/date layout: expired date dirs go, fresh stay, an emptied
    month folder is removed, legacy flat date dirs are pruned too, and
    foreign folders are never touched."""
    _restore_settings.set("path_recordings", str(tmp_path))
    _restore_settings.set("aircheck_retention_days", "90")
    today = datetime.now().date()

    def month_date_dir(d):
        return tmp_path / d.strftime("%Y-%m") / d.strftime("%Y-%m-%d")

    old = month_date_dir(today - timedelta(days=120))
    fresh = month_date_dir(today - timedelta(days=5))
    legacy_old = tmp_path / (today - timedelta(days=120)
                              ).strftime("%Y-%m-%d")
    alien = tmp_path / "not-a-date"
    for d in (old, fresh, legacy_old, alien):
        d.mkdir(parents=True, exist_ok=True)
        (d / "x.mp3").write_bytes(b"x")

    rec = AircheckRecorder()
    rec._prune_old_recordings()

    assert not old.exists()
    assert not old.parent.exists()   # emptied month folder removed
    assert fresh.exists()
    assert not legacy_old.exists()   # pre-month flat layout pruned too
    assert alien.exists()            # foreign folders are never touched


def test_prune_disabled_when_retention_zero(qapp, _restore_settings,
                                            tmp_path):
    _restore_settings.set("path_recordings", str(tmp_path))
    _restore_settings.set("aircheck_retention_days", "0")
    old = tmp_path / "2020-01-01"
    old.mkdir(parents=True)
    rec = AircheckRecorder()
    rec._prune_old_recordings()
    assert old.exists()


# ── start() gating ───────────────────────────────────────────────────────────

def test_start_noop_when_disabled(qapp, _restore_settings):
    _restore_settings.set("aircheck_enabled", "0")
    rec = AircheckRecorder()
    states = []
    rec.state_changed.connect(lambda on, msg: states.append((on, msg)))
    assert rec.start() is False
    assert rec.is_recording is False
    assert states and states[0][0] is False


def test_stop_without_start_is_safe(qapp):
    rec = AircheckRecorder()
    rec.stop()                        # must not raise
    assert rec.is_recording is False


# ── SettingsSoundcard aircheck block ─────────────────────────────────────────

AIRCHECK_KEYS = ("aircheck_enabled", "aircheck_device_override",
                 "aircheck_bitrate", "aircheck_retention_days")


@pytest.fixture
def _aircheck_snapshot():
    s = Settings()
    before = {k: s.get(k) for k in AIRCHECK_KEYS}
    yield s
    for k, v in before.items():
        s.set(k, v if v is not None else "")


def test_soundcard_screen_has_aircheck_block(qapp, _aircheck_snapshot):
    from core.database import Database
    from ui.settings_soundcard import SettingsSoundcard, AIRCHECK_QUALITIES
    scr = SettingsSoundcard(Database())
    assert scr._chk_aircheck is not None
    assert scr._cmb_aircheck_dev.itemText(0).startswith("Auto")
    assert scr._cmb_aircheck_quality.count() == len(AIRCHECK_QUALITIES) == 7
    assert scr._cmb_aircheck_quality.itemText(0) == "32 kbps (Mono)"
    assert scr._cmb_aircheck_keep.count() == 4
    scr.deleteLater()


def test_soundcard_aircheck_save_load_roundtrip(qapp, _aircheck_snapshot):
    from core.database import Database
    from ui.settings_soundcard import SettingsSoundcard
    scr = SettingsSoundcard(Database())
    scr._chk_aircheck.setChecked(False)
    scr._cmb_aircheck_quality.setCurrentIndex(2)     # 64 kbps
    scr._cmb_aircheck_keep.setCurrentIndex(0)        # 30 days
    scr._save_all()

    s = _aircheck_snapshot
    assert s.get("aircheck_enabled") == "0"
    assert s.get("aircheck_device_override") == ""
    assert s.get("aircheck_bitrate") == "64"
    assert s.get("aircheck_retention_days") == "30"

    scr2 = SettingsSoundcard(Database())
    assert scr2._chk_aircheck.isChecked() is False
    assert scr2._cmb_aircheck_quality.currentText() == "64 kbps"
    assert scr2._cmb_aircheck_keep.currentText() == "30 days"
    scr.deleteLater(); scr2.deleteLater()


def test_soundcard_aircheck_default_quality_is_32_mono(qapp,
                                                       _aircheck_snapshot):
    """Fresh state (no aircheck_bitrate saved) must land on 32 kbps."""
    from core.database import Database
    from ui.settings_soundcard import SettingsSoundcard
    _aircheck_snapshot.set("aircheck_bitrate", "")
    scr = SettingsSoundcard(Database())
    assert scr._cmb_aircheck_quality.currentText() == "32 kbps (Mono)"
    scr.deleteLater()


# ── Studio header REC pill ───────────────────────────────────────────────────

def test_header_rec_pill_state(qapp):
    from ui.studio import _Header
    h = _Header()
    assert h._rec_on is False
    h.set_rec_state(True)
    assert h._rec_on is True
    h.set_rec_state(False)
    assert h._rec_on is False
    h.deleteLater()
