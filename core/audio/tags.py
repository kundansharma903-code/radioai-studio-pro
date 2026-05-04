"""
Audio file tag reader (Phase A4).

Wraps mutagen with a uniform `Tags` dataclass and a small in-memory cache
(`TagReader`). Used by import flows that need to auto-populate Title /
Artist / Album / BPM / Genre from file metadata, plus cover-art extraction.

Tag reading is fault-tolerant: corrupted/missing files return an empty
Tags() with a warning log — never raise into the UI. This is paint-loop-
adjacent (Songs Library refresh), and one bad file shouldn't crash the
library view.

Cache trusts file content doesn't change in-place. Files in the library
get re-imported when tags need refreshing; mtime checks would add an I/O
hit on every read. Use `clear_cache()` if you have a specific reason to
force a re-read.

Format support: MP3 (ID3v2/v1), FLAC + OGG (Vorbis comments), MP4/M4A
(iTunes atoms), WAV (ID3 chunk if present), with a generic mutagen.File
fallback for anything else.

mutagen 1.47+ required. Top-level import — fail-fast on missing dep.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Optional

import mutagen
from mutagen.flac import FLAC
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4
from mutagen.oggvorbis import OggVorbis
from mutagen.wave import WAVE

log = logging.getLogger("TagReader")


# ── Public dataclass ────────────────────────────────────────────────────────

@dataclass
class Tags:
    """Uniform tag shape across all formats. Empty Tags() = "no metadata"
    (every field None except `raw` which is an empty dict)."""

    title: Optional[str]          = None
    artist: Optional[str]         = None
    album: Optional[str]          = None
    genre: Optional[str]          = None
    year: Optional[int]           = None     # parsed from "2003-04-15" → 2003
    track_number: Optional[int]   = None     # leading int from "5/12"
    duration_ms: Optional[int]    = None     # from mutagen.info — works on closed file
    bitrate_kbps: Optional[int]   = None
    sample_rate_hz: Optional[int] = None
    bpm: Optional[float]          = None
    cover_art: Optional[bytes]    = None     # raw bytes — UI decodes (PNG/JPG/WEBP)
    raw: dict                     = field(default_factory=dict)
    # `raw` carries the full mutagen tag dump for debugging and forward
    # compatibility. UI may inspect for obscure fields not promoted to
    # top-level attributes (composer, conductor, label, ISRC, ...).


# ── Internal parsing helpers ────────────────────────────────────────────────

def _safe_int_prefix(s: str) -> Optional[int]:
    """Parse leading integer from a string. '5/12' → 5, '2003-04' → 2003,
    'abc' → None."""
    if s is None:
        return None
    digits = ""
    for c in str(s).lstrip():
        if c.isdigit():
            digits += c
        else:
            break
    return int(digits) if digits else None


def _safe_float(s) -> Optional[float]:
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _largest_image_warning(data: Optional[bytes], path: str) -> None:
    if data and len(data) > 5_000_000:
        log.warning(
            f"Suspiciously large cover art ({len(data)/1e6:.1f}MB) in {path} "
            f"— file may be corrupt"
        )


# ── Format-specific extractors ──────────────────────────────────────────────

def _fill_id3(id3, tags: Tags) -> None:
    """Populate Tags from a mutagen.id3.ID3 instance (also used for WAV's
    embedded ID3 chunk)."""
    if id3 is None:
        return

    def _txt(key: str) -> Optional[str]:
        frame = id3.get(key)
        if frame is None or not getattr(frame, "text", None):
            return None
        return str(frame.text[0])

    tags.title  = _txt("TIT2") or tags.title
    tags.artist = _txt("TPE1") or tags.artist
    tags.album  = _txt("TALB") or tags.album
    tags.genre  = _txt("TCON") or tags.genre

    year_raw = _txt("TDRC") or _txt("TYER") or _txt("TDAT")
    if year_raw:
        tags.year = _safe_int_prefix(year_raw[:4])

    tags.track_number = _safe_int_prefix(_txt("TRCK")) or tags.track_number

    bpm_raw = _txt("TBPM")
    if bpm_raw:
        tags.bpm = _safe_float(bpm_raw)

    # Cover art — APIC frames. Prefer front cover (type=3).
    apics = [v for k, v in id3.items() if k.startswith("APIC")]
    if apics:
        front = next((a for a in apics if getattr(a, "type", 0) == 3), apics[0])
        tags.cover_art = bytes(getattr(front, "data", b"") or b"") or None


def _fill_vorbis(vorbis_obj, tags: Tags) -> None:
    """Populate Tags from FLAC or OGG Vorbis comments (vorbis_obj is the
    FLAC / OggVorbis instance, which exposes .tags as a dict-like)."""
    vc = getattr(vorbis_obj, "tags", None)
    if vc is None:
        return

    def _v(key: str) -> Optional[str]:
        vals = vc.get(key, [])
        return str(vals[0]) if vals else None

    tags.title  = _v("title")  or tags.title
    tags.artist = _v("artist") or tags.artist
    tags.album  = _v("album")  or tags.album
    tags.genre  = _v("genre")  or tags.genre

    date_raw = _v("date") or _v("year")
    if date_raw:
        tags.year = _safe_int_prefix(date_raw[:4])

    tags.track_number = _safe_int_prefix(_v("tracknumber")) or tags.track_number

    bpm_raw = _v("bpm") or _v("BPM")
    if bpm_raw:
        tags.bpm = _safe_float(bpm_raw)

    # FLAC stores cover art in .pictures (separate from VC); OGG Vorbis
    # uses METADATA_BLOCK_PICTURE (rare). Handle FLAC explicitly.
    pictures = getattr(vorbis_obj, "pictures", None) or []
    if pictures:
        front = next((p for p in pictures if getattr(p, "type", 0) == 3),
                     pictures[0])
        data = getattr(front, "data", None)
        if data:
            tags.cover_art = bytes(data)


def _fill_mp4(mp4_obj, tags: Tags) -> None:
    """Populate Tags from MP4/M4A iTunes atoms."""
    atoms = getattr(mp4_obj, "tags", None)
    if atoms is None:
        return

    def _a(key: str) -> Optional[str]:
        vals = atoms.get(key, [])
        if not vals:
            return None
        v = vals[0]
        if isinstance(v, bytes):
            try:
                return v.decode("utf-8", "replace")
            except Exception:
                return None
        return str(v)

    tags.title  = _a("\xa9nam") or tags.title
    tags.artist = _a("\xa9ART") or tags.artist
    tags.album  = _a("\xa9alb") or tags.album
    tags.genre  = _a("\xa9gen") or tags.genre

    date_raw = _a("\xa9day")
    if date_raw:
        tags.year = _safe_int_prefix(date_raw[:4])

    trkn = atoms.get("trkn", [])
    if trkn:
        try:
            tags.track_number = int(trkn[0][0])
        except (IndexError, TypeError, ValueError):
            pass

    tmpo = atoms.get("tmpo", [])
    if tmpo:
        try:
            tags.bpm = float(tmpo[0])
        except (IndexError, TypeError, ValueError):
            pass

    covr = atoms.get("covr", [])
    if covr:
        try:
            tags.cover_art = bytes(covr[0])
        except (IndexError, TypeError):
            pass


def _fill_info(info, tags: Tags) -> None:
    """Populate audio-info fields from any mutagen .info object."""
    if info is None:
        return
    length = getattr(info, "length", None)
    if length:
        tags.duration_ms = int(round(length * 1000))
    bitrate = getattr(info, "bitrate", None)
    if bitrate:
        tags.bitrate_kbps = int(bitrate / 1000)
    sample_rate = getattr(info, "sample_rate", None)
    if sample_rate:
        tags.sample_rate_hz = int(sample_rate)


def _stamp_raw(file_obj, tags: Tags) -> None:
    """Best-effort full tag dump for the `raw` field. Never raises."""
    try:
        tag_obj = getattr(file_obj, "tags", None)
        if tag_obj is None:
            return
        # ID3 / VComment / MP4Tags are dict-like but their values include
        # mutagen frame objects which aren't JSON-friendly. Stringify
        # values for debug-readability.
        out: dict = {}
        for k, v in tag_obj.items():
            try:
                out[str(k)] = str(v)
            except Exception:
                out[str(k)] = "<unrepresentable>"
        tags.raw = out
    except Exception:
        pass


# ── Public TagReader ────────────────────────────────────────────────────────

class TagReader:
    """Tag reader with simple in-memory cache.

    Cache trusts file content doesn't change in-place. Manual escape hatch
    via clear_cache(). Mass Import flow constructs a fresh TagReader per
    session, so cross-session staleness is a non-issue."""

    def __init__(self) -> None:
        self._cache: dict[str, Tags] = {}

    # ── Public API ────────────────────────────────────────────────────────

    def read(self, path: str) -> Tags:
        """Return Tags for `path`. Empty Tags() on missing file or read
        error (logs a warning — never raises)."""
        if path in self._cache:
            return self._cache[path]

        try:
            tags = self._read_uncached(path)
        except FileNotFoundError:
            log.warning(f"audio file not found: {path}")
            tags = Tags()
        except Exception as exc:
            log.warning(
                f"failed to read tags from {path}: "
                f"{type(exc).__name__}: {exc}"
            )
            tags = Tags()

        self._cache[path] = tags
        return tags

    def clear_cache(self) -> None:
        """Wipe the cache. Subsequent reads re-parse from disk."""
        self._cache.clear()

    # ── Internals ─────────────────────────────────────────────────────────

    def _read_uncached(self, path: str) -> Tags:
        """Format-dispatched read. Raises FileNotFoundError for a missing
        path; mutagen's own errors propagate."""
        if not os.path.exists(path):
            raise FileNotFoundError(path)

        ext = os.path.splitext(path)[1].lower()
        tags = Tags()
        file_obj = None

        if ext == ".mp3":
            file_obj = MP3(path)
            _fill_id3(file_obj.tags, tags)
        elif ext == ".flac":
            file_obj = FLAC(path)
            _fill_vorbis(file_obj, tags)
        elif ext in (".m4a", ".mp4", ".aac"):
            file_obj = MP4(path)
            _fill_mp4(file_obj, tags)
        elif ext == ".ogg":
            file_obj = OggVorbis(path)
            _fill_vorbis(file_obj, tags)
        elif ext == ".wav":
            file_obj = WAVE(path)
            # WAVE.tags is an ID3 instance when an ID3 chunk is present.
            _fill_id3(getattr(file_obj, "tags", None), tags)
        else:
            # Unknown extension — last-resort autodetection
            file_obj = mutagen.File(path)
            if file_obj is None:
                log.warning(f"mutagen.File could not parse: {path}")
                return Tags()

        _fill_info(getattr(file_obj, "info", None), tags)
        _stamp_raw(file_obj, tags)
        _largest_image_warning(tags.cover_art, path)
        return tags


# ── Module-level convenience ────────────────────────────────────────────────

_default_reader: Optional[TagReader] = None


def read_tags(path: str) -> Tags:
    """Convenience: use a process-global TagReader. Suitable for one-off
    reads; long-lived consumers should hold their own TagReader instance."""
    global _default_reader
    if _default_reader is None:
        _default_reader = TagReader()
    return _default_reader.read(path)
