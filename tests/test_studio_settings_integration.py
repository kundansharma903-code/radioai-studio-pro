"""
Studio Settings → Studio live-apply integration tests.

Pinned behaviour:
  • Studio._apply_studio_settings reads all configured keys from the
    Settings singleton + snapshots them onto _cfg_* instance attrs.
  • Live master-volume push: changing master_volume in Settings +
    calling _apply_studio_settings drives engine.set_volume on the
    currently-playing channel.
  • _maybe_trigger_fade_out fires fade_volume_to once when position
    crosses (duration - fade_out_start*1000), and only once per cid.
  • _handle_missing_file routes by fallback_action — Skip / Stop /
    Re-queue / Play default — and toggles QMessageBox based on
    missing_file_alert.
"""

from __future__ import annotations

from typing import Optional

import pytest

from core.database import Database
from core.settings import Settings
from core import dialogs as _dialogs


# Keys this integration touches
TOUCHED_KEYS = (
    "master_volume", "crossfade_duration", "fade_out_start",
    "fade_curve_type", "missing_file_alert", "fallback_action",
    "load_next_song", "preload_buffer", "automix_trigger",
)


# ── Doubles ────────────────────────────────────────────────────────────


class _FakeEngine:
    """Minimal AudioEngine stub — records set_volume / fade_volume_to
    so the tests assert what was driven from the live-apply path."""

    def __init__(self):
        self.set_volume_calls: list = []
        self.fade_calls: list = []

    # Studio signals — both are pyqtSignals on real engine, fakes use
    # _RecordingSignal so the connect() in Studio's init doesn't crash.
    class _Sig:
        def __init__(self): self.slots = []
        def connect(self, slot): self.slots.append(slot)
        def emit(self, *a):
            for s in list(self.slots): s(*a)

    def __post_init__(self):  # not used; constructed via __init__
        pass

    def __getattr__(self, name):
        if name in ("position_changed", "playback_ended",
                    "error_occurred"):
            sig = _FakeEngine._Sig()
            self.__dict__[name] = sig
            return sig
        raise AttributeError(name)

    def set_volume(self, cid: int, v: int) -> None:
        self.set_volume_calls.append((cid, v))

    def fade_volume_to(self, cid: int, target: int,
                       duration_ms: int) -> None:
        self.fade_calls.append((cid, target, duration_ms))

    def load_file(self, path: str) -> int:
        # Hand out monotonically-increasing fake cids
        self.loaded_paths = getattr(self, "loaded_paths", [])
        self.loaded_paths.append(path)
        return 100 + len(self.loaded_paths)

    def play(self, cid: int) -> None:
        pass

    def get_duration_ms(self, cid: int) -> int:
        return 30_000

    def cleanup(self, cid: int) -> None:
        self.cleanup_calls = getattr(self, "cleanup_calls", [])
        self.cleanup_calls.append(cid)

    def get_levels(self, cid: int):
        return (0.0, 0.0)

    def get_active_channels(self):
        return []


class _FakeScheduler:
    """Studio init wires a few scheduler signals. Provide stubs."""

    class _Sig:
        def __init__(self): self.slots = []
        def connect(self, slot): self.slots.append(slot)
        def emit(self, *a):
            for s in list(self.slots): s(*a)

    def __init__(self):
        self.stop_calls = 0
        # Every signal Studio expects to connect()
        for nm in ("queue_song_play", "scheduler_state_changed",
                    "break_approaching", "spot_due", "song_auto_advance",
                    "next_break_in", "started", "stopped",
                    "sweeper_dispatch", "tick", "active_clock_changed",
                    "queue_updated"):
            setattr(self, nm, _FakeScheduler._Sig())

    def is_running(self):
        return False

    def stop(self):
        self.stop_calls += 1

    def start(self):
        pass

    def pick_next_item(self, **kw):
        return None

    def peek_next(self, **kw):
        return None


@pytest.fixture
def db():
    return Database()


@pytest.fixture
def settings_snapshot(db):
    s = Settings()
    s.reload(db)
    before = {k: s.get(k) for k in TOUCHED_KEYS}
    yield before
    for k, v in before.items():
        if v is None:
            continue
        s.set(k, v)
    s.reload(db)


@pytest.fixture
def studio(qapp, db):
    """Real Studio with fake engine + scheduler so we can run the live
    lifecycle without BASS. Skips heavyweight UI render."""
    from ui.studio import Studio
    eng = _FakeEngine()
    sch = _FakeScheduler()
    s = Studio(db, engine=eng, scheduler=sch)
    yield s, eng, sch
    s.deleteLater()


# ── _apply_studio_settings ─────────────────────────────────────────────


def test_apply_studio_settings_loads_all_cfg(
        studio, db, settings_snapshot):
    s, eng, sch = studio
    sett = Settings()
    sett.set("crossfade_duration", "7")
    sett.set("fade_out_start", "4")
    sett.set("fade_curve_type", "Exponential")
    sett.set("missing_file_alert", "1")
    sett.set("fallback_action", "Stop playback + alert operator")
    sett.set("load_next_song", "At fade-out start")
    s._apply_studio_settings()
    assert s._cfg_crossfade_dur_s == 7
    assert s._cfg_fade_out_start_s == 4
    assert s._cfg_fade_curve == "Exponential"
    assert s._cfg_missing_file_alert is True
    assert s._cfg_fallback_action.lower().startswith("stop")
    assert s._cfg_load_next == "At fade-out start"


def test_apply_pushes_master_volume_to_live_channel(
        studio, db, settings_snapshot):
    s, eng, sch = studio
    s._playback_cid = 42
    s._playback_kind = "deck"
    s._master_volume = 50
    Settings().set("master_volume", "77")
    s._apply_studio_settings()
    assert s._master_volume == 77
    assert (42, 77) in eng.set_volume_calls


def test_apply_skips_volume_push_when_idle(
        studio, db, settings_snapshot):
    s, eng, sch = studio
    s._playback_cid = None
    s._playback_kind = None
    Settings().set("master_volume", "99")
    s._apply_studio_settings()
    # No set_volume call should have been made for the live push
    # (init-time idle dispatch path also doesn't call set_volume).
    assert all(v != 99 for _cid, v in eng.set_volume_calls)


# ── _maybe_trigger_fade_out ────────────────────────────────────────────


def test_fade_out_fires_once_at_threshold(
        studio, db, settings_snapshot):
    s, eng, sch = studio
    s._playback_cid = 7
    s._playback_kind = "deck"
    s._current_duration_ms = 60_000
    s._cfg_fade_out_start_s = 5
    s._cfg_crossfade_dur_s = 3
    s._fade_triggered_for_cid = None
    # Before threshold — no fade
    s._maybe_trigger_fade_out(7, 50_000)
    assert eng.fade_calls == []
    # At threshold (60000 - 5000 = 55000)
    s._maybe_trigger_fade_out(7, 55_000)
    assert eng.fade_calls == [(7, 0, 3000)]
    # Past threshold — must not re-trigger
    s._maybe_trigger_fade_out(7, 58_000)
    assert eng.fade_calls == [(7, 0, 3000)]


def test_fade_out_zero_start_disables(
        studio, db, settings_snapshot):
    s, eng, sch = studio
    s._playback_cid = 7
    s._playback_kind = "deck"
    s._current_duration_ms = 60_000
    s._cfg_fade_out_start_s = 0
    s._fade_triggered_for_cid = None
    s._maybe_trigger_fade_out(7, 60_000)
    assert eng.fade_calls == []


def test_fade_out_ignored_for_non_deck_kind(
        studio, db, settings_snapshot):
    s, eng, sch = studio
    s._playback_cid = 7
    s._playback_kind = "spot"  # not 'deck'
    s._current_duration_ms = 60_000
    s._cfg_fade_out_start_s = 5
    s._cfg_crossfade_dur_s = 3
    s._maybe_trigger_fade_out(7, 56_000)
    assert eng.fade_calls == []


# ── _handle_missing_file ───────────────────────────────────────────────


def test_missing_file_skip_action(
        studio, db, settings_snapshot, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    s, eng, sch = studio
    s._cfg_fallback_action = "Skip and play next available song"
    s._cfg_missing_file_alert = False
    calls: list = []
    monkeypatch.setattr(_dialogs, "warning",
                         staticmethod(
                             lambda *a, **k: calls.append(a) or 0))
    s._handle_missing_file({"title": "T", "id": 1}, "/missing")
    # Alert off → no toast
    assert calls == []
    # Scheduler not stopped
    assert sch.stop_calls == 0


def test_missing_file_alert_toggle_shows_toast(
        studio, db, settings_snapshot, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    s, eng, sch = studio
    s._cfg_fallback_action = "Skip and play next available song"
    s._cfg_missing_file_alert = True
    calls: list = []
    monkeypatch.setattr(_dialogs, "warning",
                         staticmethod(
                             lambda *a, **k: calls.append(a) or 0))
    s._handle_missing_file({"title": "T", "id": 1}, "/missing")
    assert len(calls) == 1


def test_missing_file_stop_action_stops_scheduler(
        studio, db, settings_snapshot, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    s, eng, sch = studio
    s._cfg_fallback_action = "Stop playback + alert operator"
    s._cfg_missing_file_alert = False  # Stop force-alerts regardless
    monkeypatch.setattr(_dialogs, "warning",
                         staticmethod(lambda *a, **k: 0))
    s._handle_missing_file({"title": "T", "id": 1}, "/missing")
    assert sch.stop_calls == 1


def test_overlay_toggles_drive_now_player(
        studio, db, settings_snapshot):
    """Crossfade overlay + mix-point flash propagate from cfg flags
    into _NowPlayer.set_crossfade_overlay / set_mix_point_flash."""
    s, eng, sch = studio
    np = s._now_player
    s._playback_cid = 9
    s._playback_kind = "deck"
    s._current_duration_ms = 60_000
    s._cfg_fade_out_start_s = 10
    s._cfg_show_crossfade_preview = True
    s._cfg_flash_mix_point = True

    # Before the 10s flash window — flash is gated off, overlay on
    s._update_waveform_overlays(9, 30_000)
    assert np._show_overlay is True
    assert np._show_flash is True
    assert np._flash_active is False

    # Inside the flash window (mix point at 50s, window 40s..50s)
    s._update_waveform_overlays(9, 45_000)
    assert np._flash_active is True

    # Past mix point — flash off
    s._update_waveform_overlays(9, 55_000)
    assert np._flash_active is False


def test_mix_point_ms_overrides_fade_out_setting(
        studio, db, settings_snapshot, tmp_path):
    """When the current track carries songs.mix_point_ms, fade-out
    fires at that absolute position regardless of fade_out_start."""
    s, eng, sch = studio
    # Stub _compute_next_song so the crossfade overlap path doesn't
    # randomly fire (we're only asserting the fade trigger here).
    s._compute_next_song = lambda after_id=None: None
    s._playback_cid = 11
    s._playback_kind = "deck"
    s._current_duration_ms = 60_000
    s._cfg_fade_out_start_s = 6  # 60s - 6s = 54s normal trigger
    s._cfg_crossfade_dur_s = 3
    s._fade_triggered_for_cid = None
    # mix_point_ms = 40s — should fire earlier than fade_out_start
    s._current_track = {"id": 1, "mix_point_ms": 40_000}

    s._maybe_trigger_fade_out(11, 39_000)
    assert eng.fade_calls == []
    s._maybe_trigger_fade_out(11, 40_000)
    assert eng.fade_calls == [(11, 0, 3000)]


def test_crossfade_overlap_starts_next_song(
        studio, db, settings_snapshot, tmp_path):
    """When fade fires + a next song is available, a NEW channel is
    started so the two tracks overlap audibly."""
    s, eng, sch = studio
    # Real file on disk so os.path.exists passes
    fake = tmp_path / "next.mp3"; fake.write_bytes(b"x")
    next_song = {"id": 99, "title": "Next", "file_path": str(fake),
                 "duration_ms": 30_000, "item_type": "song"}
    s._compute_next_song = lambda after_id=None: next_song
    s._playback_cid = 11
    s._playback_kind = "deck"
    s._current_duration_ms = 60_000
    s._cfg_fade_out_start_s = 5
    s._cfg_crossfade_dur_s = 3
    s._fade_triggered_for_cid = None
    s._current_track = {"id": 1, "mix_point_ms": 0}

    s._maybe_trigger_fade_out(11, 55_000)
    # Fade started on the old channel
    assert eng.fade_calls == [(11, 0, 3000)]
    # New channel loaded + playing
    assert getattr(eng, "loaded_paths", []) == [str(fake)]
    assert s._fading_cid == 11
    assert s._playback_cid == 101  # 100 + first load
    assert s._current_track is next_song


def test_crossfade_tail_eos_cleans_up_old_channel(
        studio, db, settings_snapshot):
    """When the outgoing channel's EOS fires, it's cleaned up silently
    and _fading_cid is reset — without disturbing the new active deck."""
    s, eng, sch = studio
    s._fading_cid = 11
    s._playback_cid = 22  # new active deck
    s._playback_kind = "deck"
    s._on_engine_playback_ended(11)
    assert getattr(eng, "cleanup_calls", []) == [11]
    assert s._fading_cid is None
    # New active deck is unchanged
    assert s._playback_cid == 22


def test_crossfade_skipped_when_no_next_song(
        studio, db, settings_snapshot):
    """No scheduler / no next item → fade fires alone, no overlap."""
    s, eng, sch = studio
    s._compute_next_song = lambda after_id=None: None
    s._playback_cid = 11
    s._playback_kind = "deck"
    s._current_duration_ms = 60_000
    s._cfg_fade_out_start_s = 5
    s._cfg_crossfade_dur_s = 3
    s._fade_triggered_for_cid = None
    s._current_track = {"id": 1}

    s._maybe_trigger_fade_out(11, 55_000)
    assert eng.fade_calls == [(11, 0, 3000)]
    assert s._fading_cid is None
    assert s._playback_cid == 11  # still the original


def test_overlay_off_when_not_deck(
        studio, db, settings_snapshot):
    s, eng, sch = studio
    np = s._now_player
    s._playback_cid = 9
    s._playback_kind = "spot"
    s._current_duration_ms = 60_000
    s._cfg_fade_out_start_s = 10
    s._cfg_show_crossfade_preview = True
    s._cfg_flash_mix_point = True
    s._update_waveform_overlays(9, 45_000)
    assert np._show_overlay is False
    assert np._show_flash is False


def test_missing_file_requeue_pushes_to_queue_head(
        studio, db, settings_snapshot, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    s, eng, sch = studio
    s._cfg_fallback_action = "Re-queue the same song"
    s._cfg_missing_file_alert = False
    monkeypatch.setattr(_dialogs, "warning",
                         staticmethod(lambda *a, **k: 0))
    if not hasattr(s, "_queue_songs") or not isinstance(s._queue_songs,
                                                          list):
        s._queue_songs = []
    song = {"title": "T", "id": 42}
    s._handle_missing_file(song, "/missing")
    assert s._queue_songs[0] is song
