"""
Diagnostic -- isolate the mixer stutter root cause.

Runs FOUR test variants in sequence with the same audio file:

  Variant 1: Direct play (no mixer) -- baseline (should be clean)
  Variant 2: Mixer route, default buffer config (current Step 5.3)
  Variant 3: Mixer route + BASS_MIXER_CHAN_BUFFER flag on source
  Variant 4: Mixer route + larger BASS device buffer (1000ms)

Operator listens to each variant for 8 seconds and reports which
ones stutter / pause properly. Output also logs BASS error codes
+ BASS_Mixer_ChannelFlags return values for diagnosis.

Usage: py scripts\\diag_mixer_stutter.py
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import time

# Make project root importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-7s] %(name)s: %(message)s",
)
log = logging.getLogger("diag")

from core.audio_engine import bass_init, bass_free
from core.audio.engine import AudioEngine
from core.audio.mixer_bus import MixerBus
from core.audio._bass import (
    BASS_ATTRIB_VOL, BASS_POS_BYTE, BASS_STREAM_PRESCAN,
    BASS_STREAM_DECODE, get_dll, error_code,
)
from core.audio._bassmix import (
    BASS_MIXER_NONSTOP, BASS_MIXER_POSEX,
    BASS_MIXER_CHAN_NORAMPIN, BASS_MIXER_CHAN_BUFFER, BASS_MIXER_CHAN_PAUSE,
    get_mixer_dll,
)
from pybass3 import BassStream, BassChannel


def _pick_song_path() -> str:
    """Find any real on-disk audio file from the songs DB."""
    from core.database import Database
    db = Database()
    rows = db._conn().execute(
        "SELECT file_path FROM songs "
        "WHERE file_path IS NOT NULL AND file_path != '' "
        "ORDER BY id LIMIT 20"
    ).fetchall()
    for r in rows:
        p = r["file_path"]
        if p and os.path.exists(p):
            return p
    raise SystemExit("no playable songs in DB")


def variant_1_direct(path: str) -> None:
    """Direct play -- no mixer at all. The baseline."""
    print("\n" + "=" * 72)
    print("VARIANT 1: DIRECT PLAY (no mixer) -- 8 seconds")
    print("Listen for: smooth playback, no stutter -- this is the baseline")
    print("=" * 72)
    handle = BassStream.CreateFile(
        False, path.encode("utf-8"), 0, 0, BASS_STREAM_PRESCAN)
    BassChannel.Play(int(handle), False)
    time.sleep(8)
    BassChannel.Stop(int(handle))
    BassStream.Free(int(handle))
    print("VARIANT 1 done")


def variant_2_mixer_default(path: str) -> None:
    """Mixer route, default buffer config (current Step 5.3 setup)."""
    print("\n" + "=" * 72)
    print("VARIANT 2: MIXER ROUTE, default buffer (current Step 5.3)")
    print("Listen for: stutter? Compare with Variant 1.")
    print("=" * 72)
    mb = MixerBus()
    mb.create()
    handle = BassStream.CreateFile(
        False, path.encode("utf-8"), 0, 0,
        BASS_STREAM_PRESCAN | BASS_STREAM_DECODE)
    mb.add_channel(int(handle))
    print(f"  channel attached, mixer playing")
    time.sleep(8)
    mb.remove_channel(int(handle))
    BassStream.Free(int(handle))
    mb.cleanup()
    print("VARIANT 2 done")


def variant_3_mixer_chan_buffer(path: str) -> None:
    """Mixer route WITH BASS_MIXER_CHAN_BUFFER flag -- per-source buffer."""
    print("\n" + "=" * 72)
    print("VARIANT 3: MIXER + BASS_MIXER_CHAN_BUFFER flag on source")
    print("Listen for: stutter? Should improve if buffer is the issue.")
    print("=" * 72)
    mixer_dll = get_mixer_dll()
    mb = MixerBus()
    mb.create()
    handle = BassStream.CreateFile(
        False, path.encode("utf-8"), 0, 0,
        BASS_STREAM_PRESCAN | BASS_STREAM_DECODE)

    # Add with CHAN_BUFFER + NORAMPIN
    flags = BASS_MIXER_CHAN_NORAMPIN | BASS_MIXER_CHAN_BUFFER
    ok = mixer_dll.BASS_Mixer_StreamAddChannel(
        ctypes.c_ulong(mb.handle()),
        ctypes.c_ulong(int(handle)),
        ctypes.c_ulong(flags),
    )
    print(f"  AddChannel(CHAN_BUFFER) result: {ok}, err: {error_code()}")
    time.sleep(8)
    mixer_dll.BASS_Mixer_ChannelRemove(ctypes.c_ulong(int(handle)))
    BassStream.Free(int(handle))
    mb.cleanup()
    print("VARIANT 3 done")


def variant_4_mixer_big_buffer(path: str) -> None:
    """Mixer route with BIGGER BASS device buffer (1000ms vs 500ms default)."""
    print("\n" + "=" * 72)
    print("VARIANT 4: MIXER + larger BASS device buffer (1000ms)")
    print("Listen for: stutter? Should fix if underrun is the cause.")
    print("=" * 72)

    bass_dll = get_dll()
    # BASS_CONFIG_BUFFER = 0
    BASS_CONFIG_BUFFER = 0
    # BASS_SetConfig
    if not hasattr(bass_dll, "BASS_SetConfig"):
        bass_dll.BASS_SetConfig.argtypes = [ctypes.c_ulong, ctypes.c_ulong]
        bass_dll.BASS_SetConfig.restype = ctypes.c_bool
    bass_dll.BASS_SetConfig(
        ctypes.c_ulong(BASS_CONFIG_BUFFER),
        ctypes.c_ulong(1000))
    print(f"  BASS_CONFIG_BUFFER set to 1000ms")

    mb = MixerBus()
    mb.create()
    handle = BassStream.CreateFile(
        False, path.encode("utf-8"), 0, 0,
        BASS_STREAM_PRESCAN | BASS_STREAM_DECODE)
    mb.add_channel(int(handle))
    time.sleep(8)
    mb.remove_channel(int(handle))
    BassStream.Free(int(handle))
    mb.cleanup()

    # Restore default
    bass_dll.BASS_SetConfig(
        ctypes.c_ulong(BASS_CONFIG_BUFFER),
        ctypes.c_ulong(500))
    print("VARIANT 4 done")


def variant_5_pause_test(path: str) -> None:
    """Mixer route -- test PAUSE specifically with BASS_Mixer_ChannelFlags."""
    print("\n" + "=" * 72)
    print("VARIANT 5: PAUSE TEST")
    print("Plays 3 sec -> PAUSE 3 sec (should be silent) -> RESUME 3 sec")
    print("=" * 72)
    mixer_dll = get_mixer_dll()
    mb = MixerBus()
    mb.create()
    handle = BassStream.CreateFile(
        False, path.encode("utf-8"), 0, 0,
        BASS_STREAM_PRESCAN | BASS_STREAM_DECODE)
    mb.add_channel(int(handle))
    print("  Playing 3 sec...")
    time.sleep(3)
    print("  PAUSING via BASS_Mixer_ChannelFlags(BASS_MIXER_CHAN_PAUSE)")
    result = mixer_dll.BASS_Mixer_ChannelFlags(
        ctypes.c_ulong(int(handle)),
        ctypes.c_ulong(BASS_MIXER_CHAN_PAUSE),
        ctypes.c_ulong(BASS_MIXER_CHAN_PAUSE),
    )
    print(f"  Flags returned: 0x{result:08x} (PAUSE bit = {bool(result & BASS_MIXER_CHAN_PAUSE)}), err: {error_code()}")
    print("  Listen -- should be SILENT for 3 seconds...")
    time.sleep(3)
    print("  RESUMING via BASS_Mixer_ChannelFlags(0, PAUSE)")
    result = mixer_dll.BASS_Mixer_ChannelFlags(
        ctypes.c_ulong(int(handle)),
        ctypes.c_ulong(0),
        ctypes.c_ulong(BASS_MIXER_CHAN_PAUSE),
    )
    print(f"  Flags returned: 0x{result:08x} (PAUSE bit = {bool(result & BASS_MIXER_CHAN_PAUSE)})")
    print("  Listen -- audio should resume for 3 seconds...")
    time.sleep(3)
    mixer_dll.BASS_Mixer_ChannelRemove(ctypes.c_ulong(int(handle)))
    BassStream.Free(int(handle))
    mb.cleanup()
    print("VARIANT 5 done")


def main():
    path = _pick_song_path()
    print(f"Test file: {path}")

    if not bass_init():
        print("BASS init failed")
        return

    try:
        variant_1_direct(path)
        time.sleep(1)
        variant_2_mixer_default(path)
        time.sleep(1)
        variant_3_mixer_chan_buffer(path)
        time.sleep(1)
        variant_4_mixer_big_buffer(path)
        time.sleep(1)
        variant_5_pause_test(path)
    finally:
        bass_free()

    print("\nAll variants done.")
    print("\nQuestions for operator:")
    print("  * Variant 1 (direct, baseline): clean / stutter?")
    print("  * Variant 2 (mixer default):    clean / stutter?")
    print("  * Variant 3 (mixer + CHAN_BUFFER): clean / stutter?")
    print("  * Variant 4 (mixer + bigger device buffer): clean / stutter?")
    print("  * Variant 5 (pause): silenced during pause / kept playing?")


if __name__ == "__main__":
    main()
