"""
Soundcard Settings screen (Figma 68:394) tests.

Pinned behaviour:
  • SettingsSoundcard constructs on a real DB without crashing.
  • 5 channel cards are present with the canonical keys.
  • _load_settings reads existing audio_output_X / audio_vol_outputX /
    audio_channel_outputX keys into the cards.
  • _save_all writes every card's selection back to the DB; round-trip
    preserves device index, volume, and channel mode.
  • Test Tone / Monitor / Test ALL show v1.1 placeholder dialogs.
  • Header station label has objectName 'hdr_station_lbl' so the
    branding-refresh walk catches it.
  • Device enumeration helper returns a non-empty list even when
    BASS is unavailable (fallback).
"""

from __future__ import annotations

import pytest

from core.database import Database
from core.settings import Settings


TOUCHED_KEYS = (
    "audio_output_1", "audio_output_2", "audio_output_3", "audio_output_4",
    "audio_input_1",
    "audio_vol_output1", "audio_vol_output2", "audio_vol_output3",
    "audio_vol_output4", "audio_vol_input1",
    "audio_channel_output1", "audio_channel_output2",
    "audio_channel_output3", "audio_channel_output4",
    "audio_channel_input1",
)


@pytest.fixture
def db():
    return Database()


@pytest.fixture
def soundcard_snapshot(db):
    """Snapshot the audio routing keys before the test, restore after."""
    s = Settings()
    s.reload(db)
    before = {k: s.get(k) for k in TOUCHED_KEYS}
    yield before
    for k, v in before.items():
        if v is None:
            continue
        s.set(k, v)
    s.reload(db)


# ── Smoke ──────────────────────────────────────────────────────────────


def test_construction_does_not_crash(qapp, db):
    from ui.settings_soundcard import SettingsSoundcard
    s = SettingsSoundcard(db)
    assert s.size().width() == 1440
    assert s.size().height() == 900
    assert len(s._cards) == 5
    assert set(s._cards.keys()) == {
        "output_1", "output_2", "output_3", "output_4", "input_1"}
    s.deleteLater()


def test_device_enumeration_returns_non_empty(qapp):
    from ui.settings_soundcard import enumerate_audio_devices
    devs = enumerate_audio_devices()
    assert len(devs) >= 1
    # Each entry is (idx, name, enabled, is_input)
    idx, name, enabled, is_input = devs[0]
    assert isinstance(idx, int)
    assert isinstance(name, str) and len(name) > 0


# ── Load / save round-trip ─────────────────────────────────────────────


def test_load_settings_reads_existing_keys(
        qapp, db, soundcard_snapshot):
    from ui.settings_soundcard import SettingsSoundcard
    sett = Settings()
    sett.set("audio_vol_output1", "67")
    sett.set("audio_channel_output1", "Mono Left")
    sett.reload(db)

    s = SettingsSoundcard(db)
    assert s._cards["output_1"].volume() == 67
    assert s._cards["output_1"].channel_mode() == "Mono Left"
    s.deleteLater()


def test_save_all_writes_every_channel(
        qapp, db, soundcard_snapshot, monkeypatch):
    from ui.settings_soundcard import SettingsSoundcard
    from PyQt6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "information",
                         staticmethod(lambda *a, **k: 0))

    s = SettingsSoundcard(db)
    s._cards["output_1"].set_volume(72)
    s._cards["output_2"].set_volume(81)
    s._cards["output_1"].set_channel_mode("Mono Right")
    s._cards["input_1"].set_volume(55)
    s._cards["input_1"].set_channel_mode("Stereo Input")
    s._on_save_clicked()

    sett = Settings()
    sett.reload(db)
    assert sett.get_int("audio_vol_output1") == 72
    assert sett.get_int("audio_vol_output2") == 81
    assert sett.get("audio_channel_output1") == "Mono Right"
    assert sett.get_int("audio_vol_input1") == 55
    assert sett.get("audio_channel_input1") == "Stereo Input"
    s.deleteLater()


# ── Test-tone placeholders ─────────────────────────────────────────────


def test_test_tone_shows_coming_soon(qapp, db, monkeypatch):
    from ui.settings_soundcard import SettingsSoundcard
    from PyQt6.QtWidgets import QMessageBox
    calls: list = []
    monkeypatch.setattr(QMessageBox, "information",
                         staticmethod(
                             lambda *a, **k: calls.append(a) or 0))
    s = SettingsSoundcard(db)
    s._on_test_clicked("output_1")
    assert len(calls) == 1
    assert "Test Tone" in calls[0][1]
    # Input fires the Monitor variant
    s._on_test_clicked("input_1")
    assert len(calls) == 2
    assert "Monitor" in calls[1][1]
    s.deleteLater()


def test_test_all_shows_coming_soon(qapp, db, monkeypatch):
    from ui.settings_soundcard import SettingsSoundcard
    from PyQt6.QtWidgets import QMessageBox
    calls: list = []
    monkeypatch.setattr(QMessageBox, "information",
                         staticmethod(
                             lambda *a, **k: calls.append(a) or 0))
    s = SettingsSoundcard(db)
    s._on_test_all()
    assert len(calls) == 1
    assert "Test ALL" in calls[0][1]
    s.deleteLater()


# ── Branding ───────────────────────────────────────────────────────────


def test_station_label_has_object_name(qapp, db):
    from PyQt6.QtWidgets import QLabel
    from ui.settings_soundcard import SettingsSoundcard
    s = SettingsSoundcard(db)
    lbl = s.findChild(QLabel, "hdr_station_lbl")
    assert lbl is not None
    s.deleteLater()
