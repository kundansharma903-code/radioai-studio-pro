"""
Auto-Hook Scanner — pinned behaviour for core/hook_scanner.py.

detect_hook() finds the most-energetic sustained section (the chorus
heuristic). We synthesise WAVs where the "chorus" position is KNOWN
(quiet verse → loud chorus → quiet outro) and assert the detected
hook lands inside the loud zone. Pure-function tests — no DB, no Qt.
"""

from __future__ import annotations

import math
import os
import struct
import wave

import pytest

from core.hook_scanner import detect_hook


def _tone_wav(path: str, spans: list[tuple[float, float]],
              total_s: float, rate: int = 22050) -> str:
    """Mono WAV of `total_s` seconds of near-silence, with a loud
    440 Hz tone during each (start_s, end_s) span."""
    frames = bytearray()
    n = int(total_s * rate)
    for i in range(n):
        t = i / rate
        loud = any(a <= t < b for a, b in spans)
        amp = 12000 if loud else 120
        sample = int(amp * math.sin(2 * math.pi * 440 * t))
        frames += struct.pack("<h", sample)
    with wave.open(path, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))
    return path


def test_hook_lands_in_the_loud_chorus(tmp_path):
    """Quiet 0-40s, LOUD 40-60s (the 'chorus'), quiet 60-90s →
    the 8s hook must sit inside the loud span."""
    p = _tone_wav(str(tmp_path / "chorus.wav"), [(40.0, 60.0)], 90.0)
    got = detect_hook(p, hook_len_s=8.0)
    assert got is not None
    hin, hout = got
    assert 38_000 <= hin <= 55_000, f"hook_in {hin}ms outside chorus"
    assert hout - hin == pytest.approx(8_000, abs=600)
    assert hout <= 60_500, f"hook_out {hout}ms past the chorus"


def test_hook_prefers_the_louder_of_two_sections(tmp_path):
    """Two loud spans — detector picks the sustained one inside the
    15-75% search window over the intro blip."""
    # short blip at 5-8s (inside skip zone), real chorus 45-65s
    p = _tone_wav(str(tmp_path / "two.wav"),
                  [(5.0, 8.0), (45.0, 65.0)], 100.0)
    got = detect_hook(p, hook_len_s=8.0)
    assert got is not None
    assert 43_000 <= got[0] <= 60_000

def test_too_short_file_returns_none(tmp_path):
    p = _tone_wav(str(tmp_path / "short.wav"), [(1.0, 3.0)], 10.0)
    assert detect_hook(p, hook_len_s=8.0) is None


def test_missing_file_returns_none():
    assert detect_hook(r"Z:\nope\missing.mp3") is None
    assert detect_hook("") is None
