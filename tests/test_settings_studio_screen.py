"""
Studio Settings screen (Figma 69:2) tests.

Pinned behaviour:
  • SettingsStudio constructs on a real DB without crashing.
  • _load_settings populates all sliders / dropdowns / toggles /
    radio group from existing Settings keys.
  • Three save paths write only their column's keys (independence).
  • Toggle bool persistence as '1'/'0'.
  • cue_split_mode round-trips through the radio group.
  • Header station label has objectName 'hdr_station_lbl'.
"""

from __future__ import annotations

import pytest

from core.database import Database
from core.settings import Settings
from core import dialogs as _dialogs


LEFT_KEYS = (
    "crossfade_duration", "fade_out_start", "fade_curve_type",
    "load_next_song", "preload_buffer", "automix_trigger",
    "fallback_action", "missing_file_alert",
)
CENTER_KEYS = (
    "autocue_threshold", "autocue_scan_mode",
    "master_volume", "cue_volume", "jingle_volume", "mic_volume",
    "vu_decay_speed", "peak_hold_duration", "clip_indicator",
)
RIGHT_KEYS = (
    "cue_split_mode", "show_crossfade_preview", "flash_mix_point",
)
TOUCHED_KEYS = LEFT_KEYS + CENTER_KEYS + RIGHT_KEYS


@pytest.fixture
def db():
    return Database()


@pytest.fixture
def studio_snapshot(db):
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
    from ui.settings_studio import SettingsStudio
    s = SettingsStudio(db)
    assert s.size().width() == 1440
    assert s.size().height() == 900
    s.deleteLater()


def test_load_settings_populates_widgets(qapp, db, studio_snapshot):
    from ui.settings_studio import SettingsStudio
    sett = Settings()
    sett.set("crossfade_duration", "7")
    sett.set("master_volume", "65")
    sett.set("fade_curve_type", "S-Curve")
    sett.set("cue_split_mode", "blend")
    sett.set("clip_indicator", "1")
    sett.reload(db)

    s = SettingsStudio(db)
    assert s._sl_crossfade.value() == 7
    assert s._sl_master.value() == 65
    assert s._curve.active() == "S-Curve"
    assert s._cue_split.selected() == "blend"
    assert s._tg_clip.is_on() is True
    s.deleteLater()


# ── Save flows ─────────────────────────────────────────────────────────


def test_save_left_writes_only_left_keys(
        qapp, db, studio_snapshot, monkeypatch):
    from ui.settings_studio import SettingsStudio
    from PyQt6.QtWidgets import QMessageBox
    monkeypatch.setattr(_dialogs, "info",
                         staticmethod(lambda *a, **k: 0))

    # Capture right-column key before
    sett = Settings()
    sett.set("cue_split_mode", "air_left")
    sett.set("master_volume", "55")
    sett.reload(db)

    s = SettingsStudio(db)
    s._sl_crossfade.set_value(8)
    s._curve.set_active("Exponential")
    # Mutate right + center via UI but only call save_left
    s._cue_split.set_selected("blend")
    s._sl_master.set_value(99)
    s._on_save_left()

    sett.reload(db)
    # Left keys updated
    assert sett.get_int("crossfade_duration") == 8
    assert sett.get("fade_curve_type") == "Exponential"
    # Right + center unchanged
    assert sett.get("cue_split_mode") == "air_left"
    assert sett.get_int("master_volume") == 55
    s.deleteLater()


def test_save_center_writes_only_center_keys(
        qapp, db, studio_snapshot, monkeypatch):
    from ui.settings_studio import SettingsStudio
    from PyQt6.QtWidgets import QMessageBox
    monkeypatch.setattr(_dialogs, "info",
                         staticmethod(lambda *a, **k: 0))

    sett = Settings()
    sett.set("crossfade_duration", "5")
    sett.reload(db)

    s = SettingsStudio(db)
    s._sl_crossfade.set_value(8)
    s._sl_master.set_value(77)
    s._tg_clip.set_on(True)
    s._on_save_center()

    sett.reload(db)
    assert sett.get_int("master_volume") == 77
    assert sett.get_bool("clip_indicator") is True
    # Left untouched
    assert sett.get_int("crossfade_duration") == 5
    s.deleteLater()


def test_save_right_writes_only_right_keys(
        qapp, db, studio_snapshot, monkeypatch):
    from ui.settings_studio import SettingsStudio
    from PyQt6.QtWidgets import QMessageBox
    monkeypatch.setattr(_dialogs, "info",
                         staticmethod(lambda *a, **k: 0))

    sett = Settings()
    sett.set("master_volume", "60")
    sett.set("show_crossfade_preview", "0")
    sett.reload(db)

    s = SettingsStudio(db)
    s._sl_master.set_value(40)  # left/center mutation NOT saved
    s._cue_split.set_selected("off")
    s._tg_show_preview.set_on(True)
    s._on_save_right()

    sett.reload(db)
    assert sett.get("cue_split_mode") == "off"
    assert sett.get_bool("show_crossfade_preview") is True
    # Center untouched
    assert sett.get_int("master_volume") == 60
    s.deleteLater()


def test_cue_split_unknown_value_falls_back(
        qapp, db, studio_snapshot):
    """Legacy rows may carry a long human-readable cue_split_mode
    string. The screen should fall back to 'cue_left' rather than
    crash."""
    from ui.settings_studio import SettingsStudio
    sett = Settings()
    sett.set("cue_split_mode", "Left: Cue + Right: On-Air (legacy)")
    sett.reload(db)
    s = SettingsStudio(db)
    assert s._cue_split.selected() == "cue_left"
    s.deleteLater()


def test_station_label_has_object_name(qapp, db):
    from PyQt6.QtWidgets import QLabel
    from ui.settings_studio import SettingsStudio
    s = SettingsStudio(db)
    lbl = s.findChild(QLabel, "hdr_station_lbl")
    assert lbl is not None
    s.deleteLater()
