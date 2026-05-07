"""
Studio v3 — Up Coming queue strictly-upcoming filter tests.

Operator request: the Up Coming panel must show ONLY tracks that are
about to air, NOT the currently-playing song or anything that has
already aired in this session. Already-played items belong in the
History panel; the currently-playing item lives in NowPlayer.

State machine:
  - ``_played_song_ids`` is a per-session set of song ids whose
    play started via _on_queue_song_play.
  - _refresh_upcoming_panel's fallback path filters _queue_songs to
    exclude played ids, takes the first 5, and renders with
    next_index=0 (NEXT rose glow on the very first card).
  - Scheduler-driven path (via _upcoming_preview from peek_next) is
    NOT affected — peek_next naturally returns what's next-to-dispatch
    so it already excludes the currently-playing slot.
"""

from __future__ import annotations

import pytest

from core.database import Database
from ui.studio import Studio


@pytest.fixture
def studio(qtbot, engine):
    """Studio with shared engine + fresh Database, no scheduler so the
    fallback path drives the panel. _queue_songs loads 12 real songs
    from the live DB — we need at least 3 distinct ones to exercise
    the filter."""
    db = Database()
    s = Studio(db=db, engine=engine, scheduler=None,
               instant_jingle_engine=None)
    if len(s._queue_songs) < 3:
        pytest.skip("queue needs ≥3 distinct songs to test filter")
    yield s
    if s._playback_cid is not None:
        try:
            engine.cleanup(s._playback_cid)
        except Exception:
            pass


def _card_titles(studio: Studio) -> list[str]:
    """Read the rendered title text from each Up Coming card. Empty
    string means a placeholder slot (no song bound)."""
    return [
        (c._song.get("title") if c._song else "")
        for c in studio._upcoming._cards
    ]


# ── 1. Currently-playing song does NOT appear in Up Coming ────────────


def test_currently_playing_song_excluded_from_upcoming(qtbot, studio):
    """When song A starts playing, A should NOT be in Up Coming. The
    panel's slot 0 must be the NEXT song (B), not A."""
    song_a = studio._queue_songs[0]
    song_b = studio._queue_songs[1]

    studio._on_queue_song_play(song_a)
    qtbot.wait(50)

    titles = _card_titles(studio)
    # A is currently playing — should NOT be in Up Coming
    assert song_a["title"] not in titles, (
        f"currently-playing song {song_a['title']!r} must not appear "
        f"in Up Coming (titles: {titles})")
    # B is the next song after A in the queue — should be at slot 0
    assert titles[0] == song_b["title"], (
        f"slot 0 should show song B {song_b['title']!r}, got "
        f"{titles[0]!r}")


# ── 2. Already-played songs stay out of Up Coming ─────────────────────


def test_already_played_songs_stay_filtered_out(qtbot, studio):
    """Play A → B in sequence. After B is playing, NEITHER A nor B
    should appear in Up Coming. Slot 0 should be C."""
    song_a = studio._queue_songs[0]
    song_b = studio._queue_songs[1]
    song_c = studio._queue_songs[2]

    studio._on_queue_song_play(song_a)
    qtbot.wait(50)
    # Simulate A's EOS — _on_engine_playback_ended path (d) auto-
    # advances to B. We trigger this directly to keep the test
    # deterministic.
    studio._on_engine_playback_ended(studio._playback_cid)
    qtbot.wait(50)

    titles = _card_titles(studio)
    assert song_a["title"] not in titles, (
        "song A (already played) must not appear in Up Coming")
    assert song_b["title"] not in titles, (
        "song B (currently playing) must not appear in Up Coming")
    # First visible card should be the next unplayed → C
    assert titles[0] == song_c["title"], (
        f"slot 0 should be next unplayed song {song_c['title']!r}, "
        f"got {titles[0]!r}")


# ── 3. Played set persists across track ends ──────────────────────────


def test_played_set_grows_with_each_play(qtbot, studio):
    """_played_song_ids monotonically grows as plays happen — never
    shrinks. Operator's session history is preserved."""
    song_a = studio._queue_songs[0]
    song_b = studio._queue_songs[1]

    assert len(studio._played_song_ids) == 0

    studio._on_queue_song_play(song_a)
    qtbot.wait(50)
    assert int(song_a["id"]) in studio._played_song_ids

    studio._on_engine_playback_ended(studio._playback_cid)
    qtbot.wait(50)

    # After auto-advance to B, both A and B are in the played set
    assert int(song_a["id"]) in studio._played_song_ids
    assert int(song_b["id"]) in studio._played_song_ids


# ── 4. Up Coming exhausts gracefully when all songs played ────────────


def test_upcoming_renders_placeholders_when_queue_exhausted(qtbot, studio):
    """When every song in _queue_songs has been played, the panel
    falls back to placeholder rows — operator sees blank '—' cards
    rather than recycled played content."""
    # Mark every song in the queue as played
    for s in studio._queue_songs:
        try:
            studio._played_song_ids.add(int(s["id"]))
        except (KeyError, TypeError, ValueError):
            pass

    studio._refresh_upcoming_panel()

    titles = _card_titles(studio)
    # All 5 cards should be placeholders (empty title because _song is None)
    assert all(t == "" for t in titles), (
        f"exhausted queue should show placeholders, got {titles}")


# ── 5. Loop replay does NOT add the same song twice ──────────────────


def test_loop_replay_dedupe_in_played_set(qtbot, studio):
    """When _loop_enabled triggers a replay of the same song on EOS,
    the played set stays the same (set semantics — duplicate adds
    are no-ops). Up Coming filter behavior is unchanged."""
    song_a = studio._queue_songs[0]

    studio._on_queue_song_play(song_a)
    qtbot.wait(50)
    pre_size = len(studio._played_song_ids)
    assert int(song_a["id"]) in studio._played_song_ids

    studio._loop_enabled = True
    studio._on_engine_playback_ended(studio._playback_cid)
    qtbot.wait(50)

    # Loop replay invoked _on_queue_song_play(A) again — set doesn't grow
    assert len(studio._played_song_ids) == pre_size
    assert int(song_a["id"]) in studio._played_song_ids
