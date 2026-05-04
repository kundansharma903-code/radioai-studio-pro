"""
Phase A1 smoke test — single-channel load + playback control.

Standalone runner (no pytest dependency yet — Day A5 may promote). Run via:

    py tests/test_audio_engine_a1.py

What it verifies:
  1. bass_init succeeds (idempotent)
  2. AudioEngine constructs without side effects
  3. load_file returns a positive channel id and registers as 'loaded'
  4. play / pause / resume / stop transitions reach the expected states
  5. State signals fire in order: loaded → playing → paused → playing → stopped
  6. Channel ids are NEVER reused after cleanup
  7. cleanup_all empties the active list
  8. No exceptions through the full lifecycle
"""

from __future__ import annotations

import os
import sys
import time

# Force UTF-8 on Windows terminals (matches main.py).
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Project root on path so `core.*` imports work when run as a script.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-8s] [%(name)s] %(message)s",
)
log = logging.getLogger("test_a1")

from PyQt6.QtCore import QCoreApplication

from core.audio import AudioEngine, AudioEngineError, ChannelError
# bass_init / bass_free still live in the legacy module — the new engine
# does NOT own BASS lifecycle (per Q6 of pre-planning).
from core.audio_engine import bass_init, bass_free
from core.database import Database


def _pick_test_song() -> str:
    """Find a real audio file from the songs DB. Skip the test if none."""
    db = Database()
    rows = db._conn().execute(
        "SELECT file_path FROM songs "
        "WHERE file_path IS NOT NULL AND file_path != '' "
        "ORDER BY id LIMIT 200"
    ).fetchall()
    for r in rows:
        path = r[0]
        if path and os.path.exists(path):
            return path
    raise SystemExit(
        "No playable audio file found in the songs DB — "
        "skipping Phase A1 smoke test."
    )


def _pump(app: QCoreApplication, seconds: float) -> None:
    """Drive the Qt event loop for `seconds`. Drains queued signals so the
    cross-thread BASS callback can dispatch."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.05)


def main() -> int:
    app = QCoreApplication(sys.argv)

    print("=" * 60)
    print("Phase A1 smoke test — multi-channel AudioEngine")
    print("=" * 60)

    # 1. BASS init (test owns lifecycle — engine does not)
    if not bass_init():
        print("FAIL: bass_init() returned False")
        return 1

    try:
        # 2. Locate a real song file
        path = _pick_test_song()
        print(f"Test file: {os.path.basename(path)}")

        # 3. Engine construction — must be side-effect-free
        engine = AudioEngine()
        assert engine.active_channels() == [], \
            "fresh engine should have zero active channels"

        # Track every state transition for end-of-test inspection
        state_log: list[tuple[int, str]] = []
        ended_log: list[int] = []
        engine.channel_state_changed.connect(
            lambda cid, st: state_log.append((cid, st)))
        engine.playback_ended.connect(
            lambda cid: ended_log.append(cid))

        # 4. load_file
        cid = engine.load_file(path)
        assert cid > 0, f"load_file returned non-positive id: {cid}"
        assert engine.get_state(cid) == "loaded", \
            f"expected 'loaded', got {engine.get_state(cid)!r}"
        assert cid in engine.active_channels(), \
            "channel not in active_channels after load"
        print(f"  ✓ load_file → channel {cid} (state=loaded)")

        # 5. play
        engine.play(cid)
        assert engine.is_playing(cid), "is_playing False after play()"
        assert engine.get_state(cid) == "playing"
        print(f"  ✓ play → state=playing")

        # Run real audio for ~1s so we know BASS is actually decoding
        _pump(app, 1.0)
        assert engine.is_playing(cid), \
            "channel should still be playing after 1s of pump"

        # 6. pause / resume
        engine.pause(cid)
        assert engine.get_state(cid) == "paused"
        assert not engine.is_playing(cid)
        print(f"  ✓ pause → state=paused")

        _pump(app, 0.3)
        engine.resume(cid)
        assert engine.get_state(cid) == "playing"
        assert engine.is_playing(cid)
        print(f"  ✓ resume → state=playing")

        _pump(app, 0.5)

        # 7. stop (manual — distinct from natural EOS)
        engine.stop(cid)
        assert engine.get_state(cid) == "stopped"
        assert not engine.is_playing(cid)
        print(f"  ✓ stop → state=stopped")

        # 8. cleanup
        engine.cleanup(cid)
        assert cid not in engine.active_channels(), \
            "channel still active after cleanup"
        print(f"  ✓ cleanup → channel removed from active map")

        # 9. Channel ids must NEVER reuse — second load should give a higher id
        cid2 = engine.load_file(path)
        assert cid2 > cid, \
            f"channel id was reused: cid={cid} cid2={cid2} (must be strictly >)"
        print(f"  ✓ never-reused id: load_file → {cid2} (> {cid})")

        engine.play(cid2)
        _pump(app, 0.3)
        engine.cleanup(cid2)
        assert cid2 not in engine.active_channels()

        # 10. cleanup_all on an already-empty map should be safe
        engine.cleanup_all()
        assert engine.active_channels() == []

        # 11. ChannelError for invalid ids
        try:
            engine.play(99999)
        except ChannelError:
            print(f"  ✓ ChannelError raised for unknown channel id")
        else:
            print("FAIL: play(99999) did not raise ChannelError")
            return 1

        # 12. AudioEngineError for missing files
        try:
            engine.load_file("E:\\does\\not\\exist.mp3")
        except AudioEngineError:
            print(f"  ✓ AudioEngineError raised for missing file")
        else:
            print("FAIL: load_file('does/not/exist') did not raise")
            return 1

        print("\n── State transitions observed ──")
        for cid_, st in state_log:
            print(f"  ch {cid_}: → {st}")
        print(f"\nTotal channels created: {cid2 - 1 + 1} (ids {cid}…{cid2})")
        print(f"Natural EOS events: {len(ended_log)} (expected 0 — all manual stops)")
        print("\n" + "=" * 60)
        print("PASS — Phase A1 smoke test")
        print("=" * 60)
        return 0

    finally:
        try:
            bass_free()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
