"""
Phase A3 smoke test — multi-channel scaling, eviction, fade_volume_to.

Standalone runner (Q3: pytest promotion deferred to A5). Run via:

    py tests/test_audio_engine_a3.py

10 tests:
  1. Load 8 simultaneous channels — all unique ids, all "loaded"
  2. Independent volumes per channel — set distinct values, read back
  3. Independent positions per channel — seek distinct, read back
  4. 9th load_file evicts oldest channel
  5. Eviction emits channel_state_changed(oldest_id, "stopped") BEFORE
     the new channel's "loaded" event (Q2 ordering)
  6. Accessing evicted channel id raises ChannelError
  7. fade_volume_to(target=20, duration=500ms) — BASS volume samples show
     monotonic decrease (verifies non-instant transition)
  8. fade_volume_to(duration=0) — instant set, get_volume == target
  9. Modest stress: 20 sequential load/play/stop/cleanup cycles
     (@TODO Phase A5: long-running soak test, memory-leak detection,
      handle-counting)
 10. Channel isolation — stop on one doesn't affect another's playback
"""

from __future__ import annotations

import ctypes
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
    level=logging.WARNING,    # quieter test output — failures still surface
    format="%(asctime)s [%(levelname)-8s] [%(name)s] %(message)s",
)

from PyQt6.QtCore import QCoreApplication

from core.audio import AudioEngine, ChannelError
from core.audio._bass import get_dll, BASS_ATTRIB_VOL
from core.audio_engine import bass_init, bass_free
from core.database import Database


# ── Helpers ──────────────────────────────────────────────────────────────

def _pump(app: QCoreApplication, seconds: float) -> None:
    """Drain Qt event queue for `seconds`."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)


def _read_bass_volume(handle: int) -> float:
    """Read current BASS volume attribute (0.0–1.0). Used by Test 7 to
    sample the in-flight slide value, which the engine's get_volume cache
    can't see (cache jumps to target immediately per Q4)."""
    out = ctypes.c_float(0.0)
    get_dll().BASS_ChannelGetAttribute(
        handle, BASS_ATTRIB_VOL, ctypes.byref(out)
    )
    return float(out.value)


def _pick_test_song() -> str:
    """Find a real audio file > 60s for position-isolation tests."""
    db = Database()
    rows = db._conn().execute(
        "SELECT file_path FROM songs "
        "WHERE file_path IS NOT NULL AND file_path != '' "
        "AND duration_ms > 60000 "
        "ORDER BY id LIMIT 200"
    ).fetchall()
    for r in rows:
        path = r[0]
        if path and os.path.exists(path):
            return path
    raise SystemExit(
        "No DB song > 60s with on-disk file found — A3 needs a multi-minute "
        "track for position-isolation testing."
    )


# ── Tests ────────────────────────────────────────────────────────────────

def t1_eight_concurrent_loads(engine, app, path):
    engine.cleanup_all()
    ids = [engine.load_file(path) for _ in range(8)]
    assert len(ids) == 8 and len(set(ids)) == 8, \
        f"Test 1 FAIL: duplicate ids {ids}"
    for cid in ids:
        assert engine.get_state(cid) == "loaded", \
            f"Test 1 FAIL: ch {cid} state={engine.get_state(cid)}"
    assert sorted(engine.active_channels()) == sorted(ids)
    engine.cleanup_all()
    print(f"  ✓ Test 1: 8 concurrent loads, all unique ids ({ids[0]}…{ids[-1]})")


def t2_independent_volumes(engine, app, path):
    engine.cleanup_all()
    ca = engine.load_file(path)
    cb = engine.load_file(path)
    cc = engine.load_file(path)

    engine.set_volume(ca, 50)
    engine.set_volume(cb, 75)
    engine.set_volume(cc, 100)
    assert engine.get_volume(ca) == 50
    assert engine.get_volume(cb) == 75
    assert engine.get_volume(cc) == 100

    # Mutate one — others should be untouched
    engine.set_volume(ca, 30)
    assert engine.get_volume(ca) == 30
    assert engine.get_volume(cb) == 75, \
        f"Test 2 FAIL: cb volume changed when ca was set"
    assert engine.get_volume(cc) == 100, \
        f"Test 2 FAIL: cc volume changed when ca was set"

    engine.cleanup_all()
    print(f"  ✓ Test 2: 3 channels with independent volumes (30/75/100)")


def t3_independent_positions(engine, app, path):
    engine.cleanup_all()
    ca = engine.load_file(path)
    cb = engine.load_file(path)
    cc = engine.load_file(path)

    dur = engine.get_duration_ms(ca)
    assert dur > 60_000, f"Test 3 FAIL: need >60s song, got {dur}ms"

    engine.seek_to_ms(ca, 10_000)
    engine.seek_to_ms(cb, 30_000)
    engine.seek_to_ms(cc, 60_000)

    pa = engine.get_position_ms(ca)
    pb = engine.get_position_ms(cb)
    pc = engine.get_position_ms(cc)

    assert abs(pa - 10_000) < 700, f"Test 3 FAIL: ca pos={pa}, expected ~10000"
    assert abs(pb - 30_000) < 700, f"Test 3 FAIL: cb pos={pb}, expected ~30000"
    assert abs(pc - 60_000) < 700, f"Test 3 FAIL: cc pos={pc}, expected ~60000"

    engine.cleanup_all()
    print(f"  ✓ Test 3: 3 channels seeked independently ({pa}/{pb}/{pc} ms)")


def t4_eviction_on_overflow(engine, app, path):
    engine.cleanup_all()
    ids = [engine.load_file(path) for _ in range(8)]
    oldest = ids[0]
    new_id = engine.load_file(path)   # 9th load → triggers eviction

    assert oldest not in engine.active_channels(), \
        f"Test 4 FAIL: oldest {oldest} not evicted; active={engine.active_channels()}"
    assert new_id in engine.active_channels()
    assert len(engine.active_channels()) == 8, \
        f"Test 4 FAIL: active count {len(engine.active_channels())} != 8"

    engine.cleanup_all()
    print(f"  ✓ Test 4: 9th load evicted oldest ({oldest}); active count back to 8")


def t5_eviction_signals(engine, app, path):
    engine.cleanup_all()

    state_log: list[tuple[int, str]] = []
    conn = engine.channel_state_changed.connect(
        lambda c, s: state_log.append((c, s)))

    ids = [engine.load_file(path) for _ in range(8)]
    oldest = ids[0]

    # Drop the noise from the initial 8 'loaded' emits — we only care
    # about events from the 9th load onwards.
    state_log.clear()
    new_id = engine.load_file(path)

    # Q2 contract: oldest gets ('stopped'), new gets ('loaded'),
    # and stopped MUST come before loaded.
    stopped_idx = next(
        (i for i, (c, s) in enumerate(state_log)
         if c == oldest and s == "stopped"),
        None,
    )
    loaded_idx = next(
        (i for i, (c, s) in enumerate(state_log)
         if c == new_id and s == "loaded"),
        None,
    )
    assert stopped_idx is not None, \
        f"Test 5 FAIL: no 'stopped' for evicted {oldest}; log={state_log}"
    assert loaded_idx is not None, \
        f"Test 5 FAIL: no 'loaded' for new {new_id}; log={state_log}"
    assert stopped_idx < loaded_idx, \
        f"Test 5 FAIL: 'stopped' must precede 'loaded'; log={state_log}"

    engine.channel_state_changed.disconnect(conn)
    engine.cleanup_all()
    print(f"  ✓ Test 5: eviction signal order — stopped({oldest}) → loaded({new_id})")


def t6_evicted_channel_invalid(engine, app, path):
    engine.cleanup_all()
    ids = [engine.load_file(path) for _ in range(8)]
    oldest = ids[0]
    engine.load_file(path)   # evicts oldest

    raised = False
    try:
        engine.play(oldest)
    except ChannelError:
        raised = True
    assert raised, \
        f"Test 6 FAIL: play(evicted_id={oldest}) did not raise ChannelError"

    engine.cleanup_all()
    print(f"  ✓ Test 6: ChannelError raised on access to evicted ch {oldest}")


def t7_fade_smooth(engine, app, path):
    engine.cleanup_all()
    cid = engine.load_file(path)
    engine.set_volume(cid, 100)
    engine.play(cid)
    _pump(app, 0.1)
    handle = engine._channels[cid].handle

    # Read BASS volume at start, then start a 100→20 over 500ms fade,
    # sample at early/mid/late points to verify non-instant transition.
    engine.fade_volume_to(cid, 20, 500)
    samples = []
    samples.append(("t=0",   _read_bass_volume(handle)))
    _pump(app, 0.10)
    samples.append(("t=100", _read_bass_volume(handle)))
    _pump(app, 0.20)
    samples.append(("t=300", _read_bass_volume(handle)))
    _pump(app, 0.20)
    samples.append(("t=500", _read_bass_volume(handle)))

    engine.cleanup_all()

    # Slide must be monotonically decreasing (start ≥ early ≥ mid ≥ late)
    # and end near target. Allow tiny non-monotonicity (rounding) via 0.01.
    v_start = samples[0][1]
    v_early = samples[1][1]
    v_mid   = samples[2][1]
    v_late  = samples[3][1]

    assert v_start >= v_early - 0.01, f"Test 7 FAIL: slide non-monotonic at start; samples={samples}"
    assert v_early >= v_mid   - 0.01, f"Test 7 FAIL: slide non-monotonic mid; samples={samples}"
    assert v_mid   >= v_late  - 0.01, f"Test 7 FAIL: slide non-monotonic late; samples={samples}"

    # Late should be near target (0.20)
    assert abs(v_late - 0.20) < 0.10, \
        f"Test 7 FAIL: late ({v_late:.3f}) not near target 0.20; samples={samples}"

    # Spread must show motion — pick the largest gap, must exceed 0.10
    spread = max(v_start, v_early, v_mid, v_late) - min(v_start, v_early, v_mid, v_late)
    assert spread > 0.30, \
        f"Test 7 FAIL: fade looks instant (spread={spread:.3f}); samples={samples}"

    print(f"  ✓ Test 7: fade smooth — start={v_start:.2f} → t100={v_early:.2f} "
          f"→ t300={v_mid:.2f} → t500={v_late:.2f}")


def t8_fade_instant(engine, app, path):
    engine.cleanup_all()
    cid = engine.load_file(path)
    engine.set_volume(cid, 100)
    engine.fade_volume_to(cid, 30, 0)   # duration=0 → instant
    assert engine.get_volume(cid) == 30, \
        f"Test 8 FAIL: cache volume {engine.get_volume(cid)} != 30"
    handle = engine._channels[cid].handle
    bass_v = _read_bass_volume(handle)
    assert abs(bass_v - 0.30) < 0.05, \
        f"Test 8 FAIL: BASS volume {bass_v:.3f} not at 0.30"
    engine.cleanup_all()
    print(f"  ✓ Test 8: fade(duration_ms=0) → instant set ({bass_v:.2f} ≈ 0.30)")


def t9_stress_cycles(engine, app, path):
    """Modest stress smoke test — 20 load/play/stop/cleanup cycles.

    @TODO Phase A5: long-running soak test (100+ cycles or 1-hour
    continuous), memory-leak detection, BASS resource handle counting.
    """
    engine.cleanup_all()
    starting_next_id = engine._next_id
    for _ in range(20):
        cid = engine.load_file(path)
        engine.play(cid)
        _pump(app, 0.04)
        engine.stop(cid)
        engine.cleanup(cid)

    assert engine.active_channels() == [], \
        f"Test 9 FAIL: leaked channels after stress: {engine.active_channels()}"
    new_ids_used = engine._next_id - starting_next_id
    assert new_ids_used == 20, \
        f"Test 9 FAIL: id counter advanced by {new_ids_used}, expected 20"
    print(f"  ✓ Test 9: 20-cycle stress complete, "
          f"next_id advanced {starting_next_id}→{engine._next_id}, no leaks")


def t10_stop_isolation(engine, app, path):
    engine.cleanup_all()
    ca = engine.load_file(path)
    cb = engine.load_file(path)
    engine.play(ca)
    engine.play(cb)
    _pump(app, 0.2)

    engine.stop(ca)

    assert not engine.is_playing(ca)
    assert engine.is_playing(cb), \
        f"Test 10 FAIL: stopping ca should not stop cb"
    assert engine.get_state(ca) == "stopped"
    assert engine.get_state(cb) == "playing"

    engine.cleanup_all()
    print(f"  ✓ Test 10: stop on ca={ca} did not affect cb={cb}")


# ── Driver ──────────────────────────────────────────────────────────────

def main() -> int:
    app = QCoreApplication(sys.argv)

    print("=" * 70)
    print("Phase A3 smoke test — multi-channel + eviction + fade (10 tests)")
    print("=" * 70)

    if not bass_init():
        print("FAIL: bass_init() returned False")
        return 1

    try:
        path = _pick_test_song()
        print(f"Test file: {os.path.basename(path)}\n")

        engine = AudioEngine()

        t1_eight_concurrent_loads(engine, app, path)
        t2_independent_volumes(engine, app, path)
        t3_independent_positions(engine, app, path)
        t4_eviction_on_overflow(engine, app, path)
        t5_eviction_signals(engine, app, path)
        t6_evicted_channel_invalid(engine, app, path)
        t7_fade_smooth(engine, app, path)
        t8_fade_instant(engine, app, path)
        t9_stress_cycles(engine, app, path)
        t10_stop_isolation(engine, app, path)

        # Final sanity: engine should be clean
        assert engine.active_channels() == [], \
            f"engine has leaked channels: {engine.active_channels()}"

        print("\n" + "=" * 70)
        print("PASS — Phase A3: 10/10 tests")
        print("=" * 70)
        return 0

    finally:
        try:
            bass_free()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
