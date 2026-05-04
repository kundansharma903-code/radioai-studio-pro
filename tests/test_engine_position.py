"""
Phase A2 smoke test — position tracking + volume + seek.

Standalone runner (Q3: pytest promotion deferred to A5). Run via:

    py tests/test_audio_engine_a2.py

10 tests:
  1. position_changed emits during playback
  2. position emission stops on pause
  3. seek_to_ms moves position
  4. seek triggers immediate position_changed (no waiting for tick)
  5. set_volume + boundary clamping (5 sub-asserts: -5, 0, 50, 100, 150)
  6. get_duration_ms ≈ DB-stored duration
  7. playback_ended fires at EOF (seek-near-end trick per Q2)
  8. State transitions: loaded → playing → paused → playing → stopped
  9. Two channels emit position_changed independently (sets up A3)
 10. stop() resets position to 0
"""

from __future__ import annotations

import os
import sys
import time

# Force UTF-8 on Windows terminals
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import logging
logging.basicConfig(
    level=logging.WARNING,    # quieter than A1 — we run more sub-tests
    format="%(asctime)s [%(levelname)-8s] [%(name)s] %(message)s",
)
log = logging.getLogger("test_a2")

from PyQt6.QtCore import QCoreApplication

from core.audio import AudioEngine
from core.audio_engine import bass_init, bass_free
from core.database import Database


def _pump(app: QCoreApplication, seconds: float) -> None:
    """Drain Qt event queue for `seconds`."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)


def _wait_for(app: QCoreApplication, predicate, timeout_s: float) -> bool:
    """Poll `predicate` until True or timeout. Pumps event loop while waiting."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    return False


def _pick_test_song() -> tuple[str, int]:
    """Return (file_path, db_duration_ms) for a real song. Falls back to
    a Windows system audio file if no DB song is playable."""
    db = Database()
    rows = db._conn().execute(
        "SELECT file_path, duration_ms FROM songs "
        "WHERE file_path IS NOT NULL AND file_path != '' "
        "AND duration_ms > 5000 "
        "ORDER BY id LIMIT 200"
    ).fetchall()
    for r in rows:
        path, dur = r[0], int(r[1] or 0)
        if path and os.path.exists(path):
            return path, dur

    # Fallback per Q2 spec — Windows system audio
    fallback = r"C:\Windows\Media\Alarm01.wav"
    if os.path.exists(fallback):
        log.warning(f"No DB song available; falling back to {fallback}")
        return fallback, 0   # 0 = unknown duration, will be measured
    raise SystemExit("No playable audio file (DB empty + no system fallback)")


# ── Individual tests ─────────────────────────────────────────────────────

def t1_position_emits(engine, app, path):
    cid = engine.load_file(path)
    pos_log: list[tuple[int, int]] = []
    engine.position_changed.connect(lambda c, p: pos_log.append((c, p)))
    engine.play(cid)
    _pump(app, 0.6)
    engine.cleanup(cid)
    assert len(pos_log) >= 3, \
        f"Test 1 FAIL: expected ≥3 position events, got {len(pos_log)}"
    print(f"  ✓ Test 1: position_changed fired {len(pos_log)}× during 0.6s playback")


def t2_position_stops_on_pause(engine, app, path):
    cid = engine.load_file(path)
    pos_log: list[int] = []
    engine.position_changed.connect(lambda c, p: pos_log.append(p))
    engine.play(cid)
    _pump(app, 0.4)
    engine.pause(cid)
    pos_log.clear()
    _pump(app, 0.5)
    engine.cleanup(cid)
    assert len(pos_log) == 0, \
        f"Test 2 FAIL: position emitted during pause: {len(pos_log)}"
    print(f"  ✓ Test 2: position_changed silent during pause (0 events / 500ms)")


def t3_seek_moves_position(engine, app, path):
    cid = engine.load_file(path)
    engine.play(cid)
    _pump(app, 0.2)
    engine.seek_to_ms(cid, 30_000)
    _pump(app, 0.15)
    pos = engine.get_position_ms(cid)
    engine.cleanup(cid)
    assert abs(pos - 30_000) < 600, \
        f"Test 3 FAIL: seek landed at {pos}ms, expected ~30000ms"
    print(f"  ✓ Test 3: seek_to_ms(30000) → position={pos}ms")


def t4_seek_immediate_emit(engine, app, path):
    cid = engine.load_file(path)
    engine.play(cid)
    _pump(app, 0.15)

    pos_log: list[tuple[int, int]] = []
    engine.position_changed.connect(lambda c, p: pos_log.append((c, p)))
    pos_log.clear()    # drain any tail-end tick
    engine.seek_to_ms(cid, 45_000)
    # No pump — seek's own emit must already be in the log (synchronous)
    immediate = next(((c, p) for c, p in pos_log if abs(p - 45_000) < 600), None)
    engine.cleanup(cid)
    assert immediate is not None, \
        f"Test 4 FAIL: no immediate position_changed near 45000ms; log={pos_log}"
    print(f"  ✓ Test 4: seek emits immediate position_changed (no tick wait)")


def t5_volume_clamp(engine, app, path):
    cid = engine.load_file(path)
    cases = [(-5, 0), (0, 0), (50, 50), (100, 100), (150, 100)]
    for input_vol, expected in cases:
        engine.set_volume(cid, input_vol)
        actual = engine.get_volume(cid)
        assert actual == expected, \
            f"Test 5 FAIL: set_volume({input_vol}) → {actual}, expected {expected}"
    engine.cleanup(cid)
    print(f"  ✓ Test 5: set_volume clamp {[c[0] for c in cases]} → "
          f"{[c[1] for c in cases]} (5/5)")


def t6_duration_matches_db(engine, app, path, db_duration: int):
    cid = engine.load_file(path)
    bass_dur = engine.get_duration_ms(cid)
    engine.cleanup(cid)
    assert bass_dur > 1000, f"Test 6 FAIL: bass duration too short: {bass_dur}ms"
    if db_duration > 0:
        # 2s tolerance — DB sometimes stores ID3-tag-rounded values
        assert abs(bass_dur - db_duration) < 2000, \
            f"Test 6 FAIL: duration mismatch DB={db_duration} BASS={bass_dur}"
        print(f"  ✓ Test 6: get_duration_ms={bass_dur} ≈ DB={db_duration} "
              f"(diff={abs(bass_dur - db_duration)}ms)")
    else:
        print(f"  ✓ Test 6: get_duration_ms={bass_dur} (no DB duration to compare)")


def t7_playback_ended_at_eof(engine, app, path):
    cid = engine.load_file(path)
    dur = engine.get_duration_ms(cid)
    assert dur > 2000, f"Test 7 FAIL: need song > 2s, got {dur}ms"

    ended_log: list[int] = []
    engine.playback_ended.connect(lambda c: ended_log.append(c))

    # Seek-near-end trick (Q2) — avoids needing a short-clip fixture
    engine.seek_to_ms(cid, dur - 1500)
    engine.play(cid)

    fired = _wait_for(app, lambda: cid in ended_log, timeout_s=4.0)
    final_pos = engine.get_position_ms(cid)
    final_state = engine.get_state(cid)
    engine.cleanup(cid)

    assert fired, f"Test 7 FAIL: playback_ended did not fire within 4s"
    assert final_state == "ended", \
        f"Test 7 FAIL: state={final_state!r}, expected 'ended'"
    # Position stays at duration on natural EOS (vs reset to 0 on stop())
    assert final_pos > dur - 500, \
        f"Test 7 FAIL: position {final_pos} not near end (duration={dur})"
    print(f"  ✓ Test 7: EOS detected — state=ended, pos={final_pos}/{dur} "
          f"(seek-near-end trick)")


def t8_state_transitions(engine, app, path):
    cid = engine.load_file(path)
    states: list[str] = []
    engine.channel_state_changed.connect(
        lambda c, s: states.append(s) if c == cid else None)

    engine.play(cid)
    _pump(app, 0.2)
    engine.pause(cid)
    _pump(app, 0.1)
    engine.resume(cid)
    _pump(app, 0.2)
    engine.stop(cid)
    engine.cleanup(cid)

    expected = ["playing", "paused", "playing", "stopped"]
    assert states == expected, \
        f"Test 8 FAIL: state log = {states}, expected {expected}"
    print(f"  ✓ Test 8: state transitions {' → '.join(states)} (4/4 in order)")


def t9_multi_channel_independent(engine, app, path):
    cid_a = engine.load_file(path)
    cid_b = engine.load_file(path)

    counts = {cid_a: 0, cid_b: 0}
    def _count(c, p):
        if c in counts:
            counts[c] += 1
    engine.position_changed.connect(_count)

    engine.play(cid_a)
    engine.play(cid_b)
    _pump(app, 0.6)
    engine.stop(cid_a)
    engine.stop(cid_b)
    engine.cleanup(cid_a)
    engine.cleanup(cid_b)

    assert counts[cid_a] >= 2, \
        f"Test 9 FAIL: ch A position events: {counts[cid_a]}"
    assert counts[cid_b] >= 2, \
        f"Test 9 FAIL: ch B position events: {counts[cid_b]}"
    print(f"  ✓ Test 9: 2 channels emitted independently — "
          f"A={counts[cid_a]}, B={counts[cid_b]}")


def t10_stop_resets_position(engine, app, path):
    cid = engine.load_file(path)
    engine.play(cid)
    _pump(app, 0.5)
    pos_during = engine.get_position_ms(cid)
    engine.stop(cid)
    pos_after = engine.get_position_ms(cid)
    engine.cleanup(cid)
    assert pos_during > 100, \
        f"Test 10 FAIL: pre-stop position too low: {pos_during}ms"
    assert pos_after < 200, \
        f"Test 10 FAIL: post-stop position {pos_after}ms not reset to 0 " \
        f"(was {pos_during}ms during playback)"
    print(f"  ✓ Test 10: stop resets position {pos_during}→{pos_after}ms")


def main() -> int:
    app = QCoreApplication(sys.argv)

    print("=" * 64)
    print("Phase A2 smoke test — position + volume + seek (10 tests)")
    print("=" * 64)

    if not bass_init():
        print("FAIL: bass_init() returned False")
        return 1

    try:
        path, db_duration = _pick_test_song()
        print(f"Test file: {os.path.basename(path)} (db_duration={db_duration}ms)\n")

        engine = AudioEngine()

        # Run all 10 tests. Each manages its own load/cleanup so failures
        # don't cascade.
        t1_position_emits(engine, app, path)
        t2_position_stops_on_pause(engine, app, path)
        t3_seek_moves_position(engine, app, path)
        t4_seek_immediate_emit(engine, app, path)
        t5_volume_clamp(engine, app, path)
        t6_duration_matches_db(engine, app, path, db_duration)
        t7_playback_ended_at_eof(engine, app, path)
        t8_state_transitions(engine, app, path)
        t9_multi_channel_independent(engine, app, path)
        t10_stop_resets_position(engine, app, path)

        # Final sanity: engine should be clean after all tests
        assert engine.active_channels() == [], \
            f"engine has leaked channels: {engine.active_channels()}"

        print("\n" + "=" * 64)
        print("PASS — Phase A2: 10/10 tests")
        print("=" * 64)
        return 0

    finally:
        try:
            bass_free()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
