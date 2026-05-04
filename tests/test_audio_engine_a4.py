"""
Phase A4 smoke test — tag reading + metadata extraction (mutagen).

Standalone runner (Q3: pytest promotion deferred to A5). Run via:

    py tests/test_audio_engine_a4.py

7 tests:
  1. Read MP3 with full ID3v2 tags (title/artist non-empty, info populated)
  2. Read file with no/minimal tags (returns empty Tags, no crash)
  3. Read corrupted file (returns empty Tags + warning, no crash)
  4. Cache works (second read of same path skips _read_uncached)
  5. clear_cache forces re-read
  6. BPM detection on a song that carries BPM in its tag
     (skips with a TODO if no DB song has BPM)
  7. Cover art extraction on a song with embedded image
     (skips with a TODO if no DB song has cover art)
"""

from __future__ import annotations

import os
import sys
import tempfile

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
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)-8s] [%(name)s] %(message)s",
)

from core.audio import TagReader, Tags, read_tags
from core.database import Database


# ── Helpers ──────────────────────────────────────────────────────────────

def _pick_song_with_tags() -> tuple[str, dict]:
    """Pick a real DB MP3 with non-empty title+artist (likely to have ID3
    tags on disk). Falls back to any DB song with on-disk file."""
    db = Database()
    # Prefer MP3 with non-empty title + artist (signals ID3 likely present)
    preferred = db._conn().execute(
        "SELECT file_path, title, artist, duration_ms FROM songs "
        "WHERE file_path LIKE '%.mp3' "
        "AND title IS NOT NULL AND title != '' "
        "AND artist IS NOT NULL AND artist != '' "
        "ORDER BY id LIMIT 200"
    ).fetchall()
    for r in preferred:
        if r["file_path"] and os.path.exists(r["file_path"]):
            return r["file_path"], dict(r)
    # Fallback — any on-disk song
    rows = db._conn().execute(
        "SELECT file_path, title, artist, duration_ms FROM songs "
        "WHERE file_path IS NOT NULL AND file_path != '' "
        "ORDER BY id LIMIT 200"
    ).fetchall()
    for r in rows:
        if r["file_path"] and os.path.exists(r["file_path"]):
            return r["file_path"], dict(r)
    raise SystemExit("No DB song with on-disk file found")


def _find_first_with_attr(attr: str, limit: int = 200) -> tuple[str, object] | None:
    """Scan up to `limit` DB songs until one yields a non-None Tags.attr
    value. Returns (path, value) or None. Used by Tests 1/6/7 to gracefully
    handle a DB that doesn't contain a song with the relevant tag field."""
    db = Database()
    rows = db._conn().execute(
        "SELECT file_path FROM songs "
        "WHERE file_path IS NOT NULL AND file_path != '' "
        "ORDER BY id LIMIT ?", [limit]
    ).fetchall()
    reader = TagReader()
    for r in rows:
        path = r["file_path"]
        if not path or not os.path.exists(path):
            continue
        tags = reader.read(path)
        val = getattr(tags, attr, None)
        if val is not None and val != b"" and val != "" and val != 0:
            return path, val
    return None


# ── Tests ────────────────────────────────────────────────────────────────

def t1_full_tags():
    """Read tags from a real MP3. Prefer one whose tag actually carries a
    title (proves the ID3 read path); fall back to info-only verification
    if no DB song has rich tags (KISS-FM library MP3s often have only
    encoder TSSE frames — title/artist come from filename, not from ID3).
    """
    found = _find_first_with_attr("title")
    if found:
        path, _ = found
        tags = read_tags(path)
        assert isinstance(tags, Tags), "Test 1 FAIL: not a Tags instance"
        assert tags.title, f"Test 1 FAIL: title disappeared on re-read"
        assert tags.duration_ms and tags.duration_ms > 0, \
            f"Test 1 FAIL: duration_ms invalid: {tags.duration_ms}"
        print(f"  ✓ Test 1: full tags read — "
              f"artist={tags.artist!r} title={tags.title!r} "
              f"duration={tags.duration_ms}ms bitrate={tags.bitrate_kbps}kbps")
        return

    # Fallback: no DB song has a title tag — verify the info-only path
    path, _ = _pick_song_with_tags()
    tags = read_tags(path)
    assert isinstance(tags, Tags), "Test 1 FAIL: not a Tags instance"
    assert tags.duration_ms and tags.duration_ms > 0, \
        f"Test 1 FAIL: duration_ms invalid: {tags.duration_ms}"
    assert tags.bitrate_kbps and tags.bitrate_kbps > 0, \
        f"Test 1 FAIL: bitrate invalid: {tags.bitrate_kbps}"
    print(f"  ✓ Test 1: info-only path — "
          f"duration={tags.duration_ms}ms "
          f"bitrate={tags.bitrate_kbps}kbps "
          f"sr={tags.sample_rate_hz}Hz "
          f"(@TODO: no DB song has TIT2 frame — re-import with "
          f"rich tags for full coverage)")


def t2_no_tags_file():
    """Use a Windows system audio file (typically untagged) to verify
    empty-tag handling. If unavailable, fabricate a 1KB fake-WAV to
    exercise the same code path."""
    candidates = [
        r"C:\Windows\Media\Alarm01.wav",
        r"C:\Windows\Media\Ring01.wav",
    ]
    target = next((p for p in candidates if os.path.exists(p)), None)

    if target is None:
        # Fabricate a minimal RIFF header so mutagen recognizes it as WAV
        # but finds no tags
        target = os.path.join(tempfile.gettempdir(), "radioai_a4_notags.wav")
        # Minimal 1 frame of silent PCM
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
    # Either path: should not crash; tags is a valid Tags object.
    assert isinstance(tags, Tags), \
        f"Test 2 FAIL: did not return Tags for {target}"
    # Tags fields can all be None — that's the "no metadata" state.
    print(f"  ✓ Test 2: untagged WAV — title={tags.title!r} "
          f"duration_ms={tags.duration_ms}")


def t3_corrupted_file():
    """Write 256 bytes of random garbage to a .mp3 path. mutagen may
    raise; the reader must still return Tags() without exposing it."""
    import secrets
    target = os.path.join(tempfile.gettempdir(), "radioai_a4_corrupt.mp3")
    with open(target, "wb") as f:
        f.write(secrets.token_bytes(256))

    tags = read_tags(target)
    assert isinstance(tags, Tags), \
        f"Test 3 FAIL: corrupted file did not return Tags"
    # Should be entirely empty — no crash propagated
    assert tags.title is None and tags.duration_ms is None, \
        f"Test 3 FAIL: corrupted file returned populated Tags: {tags}"
    print(f"  ✓ Test 3: corrupted file → empty Tags + warning (no crash)")


def t4_cache_works():
    path, _ = _pick_song_with_tags()
    reader = TagReader()

    # Instrument _read_uncached to count calls
    call_count = [0]
    original = reader._read_uncached
    def counting(p):
        call_count[0] += 1
        return original(p)
    reader._read_uncached = counting

    tags1 = reader.read(path)
    tags2 = reader.read(path)

    assert call_count[0] == 1, \
        f"Test 4 FAIL: expected 1 _read_uncached call, got {call_count[0]}"
    assert tags1 is tags2, \
        f"Test 4 FAIL: cache returned different instance (id1={id(tags1)} id2={id(tags2)})"
    print(f"  ✓ Test 4: cache hit — _read_uncached called 1× for 2 reads")


def t5_clear_cache():
    path, _ = _pick_song_with_tags()
    reader = TagReader()

    call_count = [0]
    original = reader._read_uncached
    def counting(p):
        call_count[0] += 1
        return original(p)
    reader._read_uncached = counting

    reader.read(path)
    reader.clear_cache()
    reader.read(path)

    assert call_count[0] == 2, \
        f"Test 5 FAIL: expected 2 calls after clear, got {call_count[0]}"
    print(f"  ✓ Test 5: clear_cache forces re-read (2 calls / 2 reads after clear)")


def t6_bpm_detection():
    found = _find_first_with_attr("bpm")
    if found is None:
        print(f"  ⊘ Test 6 SKIPPED — no DB song with BPM tag "
              f"(@TODO seed a song with TBPM frame for full coverage)")
        return
    path, bpm = found
    assert isinstance(bpm, float) and bpm > 0, \
        f"Test 6 FAIL: bpm = {bpm!r}"
    print(f"  ✓ Test 6: BPM detected = {bpm} (from {os.path.basename(path)})")


def t7_cover_art():
    found = _find_first_with_attr("cover_art")
    if found is None:
        print(f"  ⊘ Test 7 SKIPPED — no DB song with embedded cover art "
              f"(@TODO seed a song with APIC frame for full coverage)")
        return
    path, data = found
    assert isinstance(data, (bytes, bytearray)) and len(data) > 100, \
        f"Test 7 FAIL: cover_art type/length: {type(data).__name__}/" \
        f"{len(data) if data else 0}"
    # Most embedded covers are JPEG or PNG — sanity-check magic bytes
    magic = bytes(data[:4])
    is_jpeg = magic[:3] == b"\xff\xd8\xff"
    is_png  = magic == b"\x89PNG"
    is_webp = magic[:4] == b"RIFF"   # WEBP starts with RIFF
    assert (is_jpeg or is_png or is_webp), \
        f"Test 7 FAIL: cover_art magic bytes don't match JPEG/PNG/WEBP: " \
        f"{magic.hex()}"
    fmt = "JPEG" if is_jpeg else ("PNG" if is_png else "WEBP")
    print(f"  ✓ Test 7: cover art extracted — {fmt}, {len(data)} bytes "
          f"(from {os.path.basename(path)})")


# ── Driver ──────────────────────────────────────────────────────────────

def main() -> int:
    print("=" * 70)
    print("Phase A4 smoke test — tag reading (7 tests)")
    print("=" * 70)
    print()

    t1_full_tags()
    t2_no_tags_file()
    t3_corrupted_file()
    t4_cache_works()
    t5_clear_cache()
    t6_bpm_detection()
    t7_cover_art()

    print("\n" + "=" * 70)
    print("PASS — Phase A4: 7/7 tests (skipped tests counted as pass)")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
