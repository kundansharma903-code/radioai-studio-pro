"""
Dead air on unplayable tracks (found 2026-10-16 in a sandbox run).

Two faults together silenced the station:

  1. Every BASS file open passed path.encode("utf-8"). BASS on Windows
     reads a char* name as the ANSI code page, so any path with a
     non-ASCII character — Devanagari titles, an en dash — failed with
     BASS_ERROR_FILEOPEN although the file exists (6 library songs).
     core.audio._bass.bass_file_arg now passes UTF-16 + BASS_UNICODE.
  2. When the deck could not open a track, _on_queue_song_play just
     returned, and the "Skip and play next available song" fallback
     went idle without playing anything. In AUTO the next item now airs
     at once (bounded by _MAX_SKIP_STREAK), alert after it has started.
"""

from __future__ import annotations

import os
import shutil

import pytest
from PyQt6.QtCore import QCoreApplication

from core.database import Database


def _pump(n: int = 4) -> None:
    for _ in range(n):
        QCoreApplication.processEvents()


# ── 1. non-ASCII paths open ─────────────────────────────────────────────


@pytest.mark.parametrize("name", ["तेरे बिन.mp3",
                                  "Sidharth – Kiara.mp3",
                                  "Café ñ test.mp3"])
def test_engine_opens_non_ascii_paths(engine, test_song_path, tmp_path,
                                      name):
    ext = os.path.splitext(test_song_path)[1]
    target = tmp_path / (os.path.splitext(name)[0] + ext)
    shutil.copyfile(test_song_path, target)
    cid = engine.load_file(str(target))
    assert cid is not None
    assert (engine.get_duration_ms(cid) or 0) > 0
    assert engine.probe_duration_ms(str(target)) > 0


def test_ascii_paths_still_open(engine, test_song_path):
    assert engine.load_file(test_song_path) is not None


def test_no_bass_call_site_passes_utf8_bytes():
    """Guard: a new BASS file-open must use bass_file_arg, not UTF-8."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    offenders = []
    for rel in ("core/audio/engine.py", "core/audio_engine.py",
                "core/sweeper_engine.py", "core/stitcher_engine.py",
                "ui/sotg_assign.py"):
        src = open(os.path.join(root, rel), encoding="utf-8").read()
        i = 0
        while True:
            i = src.find("CreateFile(", i)
            if i < 0:
                break
            if 'encode("utf-8")' in src[i:i + 200]:
                offenders.append(rel)
            i += 1
    assert offenders == []


# ── 2. a track the deck cannot open is skipped in AUTO ─────────────────


class _Sig:
    def __init__(self): self._s = []
    def connect(self, f): self._s.append(f)
    def disconnect(self, *_): self._s.clear()
    def emit(self, *a):
        for f in list(self._s): f(*a)


class _FlakyEngine:
    """load_file raises for paths in `bad`, succeeds otherwise."""

    def __init__(self, bad: set):
        self.bad = set(bad)
        self.loaded: list[str] = []
        self.position_changed = _Sig()
        self.playback_ended = _Sig()
        self.error_occurred = _Sig()
        self._n = 0

    def load_file(self, path, loop=False):
        if path in self.bad:
            raise RuntimeError("BASS_StreamCreateFile failed (err 2)")
        self._n += 1
        self.loaded.append(path)
        return self._n

    def set_volume(self, *_): pass
    def play(self, *_): pass
    def cleanup(self, *_): pass
    def cleanup_all(self): pass
    def get_duration_ms(self, *_): return 180_000
    def get_levels(self, *_): return (0.0, 0.0)
    def get_state(self, *_): return "playing"
    def get_position_ms(self, *_): return 0


def _real_songs(n):
    out = []
    for r in Database()._conn().execute(
            "SELECT id, title, artist, file_path, duration_ms FROM songs "
            "WHERE is_enabled = 1 ORDER BY id"):
        if r["file_path"] and os.path.exists(r["file_path"]):
            out.append({"id": r["id"], "title": r["title"],
                        "artist": r["artist"], "file_path": r["file_path"],
                        "duration_ms": r["duration_ms"],
                        "_item_type": "song"})
            if len(out) == n:
                return out
    pytest.skip(f"need {n} playable songs")


@pytest.fixture
def studio_with(qtbot, monkeypatch):
    import core.dialogs as _d
    alerts = []
    monkeypatch.setattr(_d, "warning", lambda *a, **k: alerts.append(a))
    from ui.studio import Studio

    def make(bad, queue):
        eng = _FlakyEngine(bad)
        s = Studio(db=Database(), engine=eng, scheduler=None)
        qtbot.addWidget(s)
        s._cfg_fallback_action = "Skip and play next available song"
        s._cfg_missing_file_alert = True
        s._manual_queue = [dict(q, _manual=True, _manual_uid=i)
                           for i, q in enumerate(queue)]
        return s, eng
    return make, alerts


def test_unopenable_track_skips_to_next(studio_with):
    make, alerts = studio_with
    a, b = _real_songs(2)
    s, eng = make({a["file_path"]}, [b])
    s._on_queue_song_play(a)
    _pump()
    assert eng.loaded == [b["file_path"]], "next item must air"
    assert s._current_track["id"] == b["id"]
    assert len(alerts) == 1, "operator still told, after the skip"
    assert s._skip_streak == 0, "a successful play resets the streak"


def test_live_assist_does_not_auto_skip(studio_with):
    make, _ = studio_with
    a, b = _real_songs(2)
    s, eng = make({a["file_path"]}, [b])
    s._auto_advance_enabled = False
    s._on_queue_song_play(a)
    _pump()
    assert eng.loaded == []
    assert s._current_track is None


def test_skip_streak_is_bounded(studio_with):
    make, _ = studio_with
    songs = _real_songs(8)
    bad = {x["file_path"] for x in songs}
    s, eng = make(bad, songs[1:])
    s._on_queue_song_play(songs[0])
    _pump(20)
    assert eng.loaded == []
    assert s._skip_streak == s._MAX_SKIP_STREAK + 1
    assert len(s._manual_queue) == len(songs) - 1 - s._MAX_SKIP_STREAK
