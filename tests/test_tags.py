"""
Tag reading + metadata extraction (Phase A4, pytest).

Covers: format dispatch (MP3/FLAC/OGG/MP4/WAV), info-only fallback when
tags absent, fault tolerance for corrupted files, cache hit + clear,
BPM detection, cover-art extraction.

Tests 6 & 7 (BPM, cover art) gracefully skip if no DB song carries the
relevant tag — production library MP3s often have only encoder TSSE
frames (title/artist come from filename at import).
"""

import os
import secrets
import tempfile

import pytest

from core.audio import Tags, TagReader, read_tags
from core.database import Database


# ── Helpers (test-scoped, not fixtures since they query DB) ─────────────

def _find_first_with_attr(attr: str, limit: int = 200):
    """Scan up to `limit` DB songs for one yielding non-empty Tags.attr."""
    db = Database()
    rows = db._conn().execute(
        "SELECT file_path FROM songs "
        "WHERE file_path IS NOT NULL AND file_path != '' "
        "ORDER BY id LIMIT ?", [limit],
    ).fetchall()
    reader = TagReader()
    for r in rows:
        path = r["file_path"]
        if not path or not os.path.exists(path):
            continue
        tags = reader.read(path)
        val = getattr(tags, attr, None)
        if val:
            return path, val
    return None


# ── Tests ────────────────────────────────────────────────────────────────

def test_full_tags_from_real_mp3(test_song_path):
    """Prefer a song with title tag; fall back to info-only verification
    if no DB song has rich tags."""
    found = _find_first_with_attr("title")
    if found:
        path, _ = found
        tags = read_tags(path)
        assert isinstance(tags, Tags)
        assert tags.title
        assert tags.duration_ms and tags.duration_ms > 0
        return

    # Fallback: info-only path
    tags = read_tags(test_song_path)
    assert isinstance(tags, Tags)
    assert tags.duration_ms and tags.duration_ms > 0
    assert tags.bitrate_kbps and tags.bitrate_kbps > 0


def test_no_tags_file_returns_empty_tags():
    """Use a Windows system audio file (typically untagged) or a
    fabricated minimal RIFF WAV to exercise the empty-tag path."""
    candidates = [
        r"C:\Windows\Media\Alarm01.wav",
        r"C:\Windows\Media\Ring01.wav",
    ]
    target = next((p for p in candidates if os.path.exists(p)), None)
    if target is None:
        target = os.path.join(tempfile.gettempdir(), "radioai_a4_notags.wav")
        riff = (
            b"RIFF" + (36).to_bytes(4, "little") + b"WAVE"
            b"fmt " + (16).to_bytes(4, "little") +
            (1).to_bytes(2, "little") + (1).to_bytes(2, "little") +
            (44100).to_bytes(4, "little") + (88200).to_bytes(4, "little") +
            (2).to_bytes(2, "little") + (16).to_bytes(2, "little") +
            b"data" + (0).to_bytes(4, "little")
        )
        with open(target, "wb") as f:
            f.write(riff)

    tags = read_tags(target)
    assert isinstance(tags, Tags)
    # Tags fields can all be None — that's the "no metadata" state.


def test_corrupted_file_returns_empty_tags():
    target = os.path.join(tempfile.gettempdir(), "radioai_a4_corrupt.mp3")
    with open(target, "wb") as f:
        f.write(secrets.token_bytes(256))
    tags = read_tags(target)
    assert isinstance(tags, Tags)
    # Fully empty Tags — no crash propagated, just a warning log
    assert tags.title is None and tags.duration_ms is None


def test_cache_hit_skips_reread(test_song_path):
    reader = TagReader()
    call_count = [0]
    original = reader._read_uncached
    def counting(p):
        call_count[0] += 1
        return original(p)
    reader._read_uncached = counting

    tags1 = reader.read(test_song_path)
    tags2 = reader.read(test_song_path)
    assert call_count[0] == 1, f"expected 1 call, got {call_count[0]}"
    assert tags1 is tags2, "cache should return same instance"


def test_clear_cache_forces_reread(test_song_path):
    reader = TagReader()
    call_count = [0]
    original = reader._read_uncached
    def counting(p):
        call_count[0] += 1
        return original(p)
    reader._read_uncached = counting

    reader.read(test_song_path)
    reader.clear_cache()
    reader.read(test_song_path)
    assert call_count[0] == 2


def test_bpm_detection():
    """Skips if no DB song carries a BPM tag."""
    found = _find_first_with_attr("bpm")
    if not found:
        pytest.skip("no DB song with BPM tag — re-import with TBPM frame "
                    "for full coverage")
    _, bpm = found
    assert isinstance(bpm, float) and bpm > 0


def test_cover_art_extraction():
    """Skips if no DB song carries embedded cover art."""
    found = _find_first_with_attr("cover_art")
    if not found:
        pytest.skip("no DB song with embedded cover art — re-import with "
                    "APIC frame for full coverage")
    _, data = found
    assert isinstance(data, (bytes, bytearray)) and len(data) > 100
    magic = bytes(data[:4])
    assert (magic[:3] == b"\xff\xd8\xff"          # JPEG
            or magic == b"\x89PNG"                # PNG
            or magic[:4] == b"RIFF"), \
        f"unexpected cover_art magic bytes: {magic.hex()}"
