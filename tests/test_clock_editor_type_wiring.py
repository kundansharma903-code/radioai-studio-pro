"""
Clock Editor — per-element-type wiring (2026-07-25).

Operator: "when we edit a clock in Main Auto Schedule we see these icons
on Song, Sweepers, Jingles and Spot — these are not wired correctly,
does not reflect correct data from relevant directory."

They were right. The Available Clock Elements card treated anything
that was not a sweeper or a jingle as "song-like", so:

  • SPOT ($) and VOICE (🎤) showed the full SONG filter panel, right
    down to "Pick Category → All Songs · 394 songs". _pick_break never
    reads the slot at all, and _pick_voice_track reads voice_tracks —
    neither looks at a song filter.
  • VOICE had no picker whatsoever, so a voice slot could never be
    pinned to a specific track from this screen.
  • the painted chrome ("Categories", "Pick Category", the "N AVAIL"
    badge = song-category count, and a song-category helper line) was
    drawn for EVERY type, captioning a Jingle slot with song data.
  • the Filter Results card always ran the song query, reporting a song
    count and song average duration no matter which type was selected.

These tests pin what each type must expose, matched to what the
scheduler genuinely reads from the slot. Display + selection only — no
scheduler or playback behaviour is involved.
"""

from __future__ import annotations

import uuid

import pytest

from core.database import Database
from ui.clock_editor import ClockEditor, MODE_NEW, _AvailableElementsCard


@pytest.fixture
def db():
    return Database()


@pytest.fixture
def card(qapp):
    c = _AvailableElementsCard()
    yield c
    c.deleteLater()


@pytest.fixture
def editor(qapp, db):
    s = ClockEditor(db=db, scheduler=None)
    s.load_for_mode(MODE_NEW)
    yield s
    s.deleteLater()


def _select(card_or_editor, t: str):
    lib = getattr(card_or_editor, "_lib", card_or_editor)
    lib._on_type_clicked(t)


# ── Which controls each type exposes ────────────────────────────────────


def test_song_shows_the_song_filter_panel(card):
    _select(card, "song")
    assert card._cat_dd.isVisibleTo(card) is True
    assert card._dd_era.isVisibleTo(card) is True
    assert card._dd_sweeper_pick.isVisibleTo(card) is False
    assert card._dd_jingle_pick.isVisibleTo(card) is False
    assert card._dd_voice_pick.isVisibleTo(card) is False


def test_spot_shows_no_song_filters(card):
    """The regression that started this: a Break slot was captioned
    'All Songs · 394 songs'. _pick_break ignores the slot entirely."""
    _select(card, "spot")
    assert card._cat_dd.isVisibleTo(card) is False
    for dd in (card._dd_era, card._dd_vocal, card._dd_year_min,
               card._dd_pri_min, card._dd_bpm_min, card._dd_sound_code):
        assert dd.isVisibleTo(card) is False
    # …and no picker either — there is nothing to pick per slot.
    assert card._dd_sweeper_pick.isVisibleTo(card) is False
    assert card._dd_jingle_pick.isVisibleTo(card) is False
    assert card._dd_voice_pick.isVisibleTo(card) is False


def test_voice_shows_its_own_picker_not_song_filters(card):
    _select(card, "voice")
    assert card._dd_voice_pick.isVisibleTo(card) is True
    assert card._cat_dd.isVisibleTo(card) is False
    assert card._dd_era.isVisibleTo(card) is False


def test_jingle_and_sweeper_keep_their_pickers(card):
    _select(card, "jingle")
    assert card._dd_jingle_pick.isVisibleTo(card) is True
    assert card._cat_dd.isVisibleTo(card) is False
    _select(card, "sweeper")
    assert card._dd_sweeper_pick.isVisibleTo(card) is True
    assert card._dd_sweeper_position.isVisibleTo(card) is True
    assert card._dd_jingle_pick.isVisibleTo(card) is False


def test_leaving_the_filters_subtab_hides_every_group(card):
    _select(card, "sweeper")
    card.set_subtab("tracks")
    assert card._dd_sweeper_pick.isVisibleTo(card) is False
    assert card._cat_dd.isVisibleTo(card) is False
    card.set_subtab("filters")
    assert card._dd_sweeper_pick.isVisibleTo(card) is True


# ── Voice-track picker ──────────────────────────────────────────────────


def test_set_voice_tracks_populates_picker_random_first(card):
    card.set_voice_tracks([
        {"id": 4, "label": "Morning VT"},
        {"id": 9, "name": "Evening VT"},      # falls back to `name`
    ])
    labels = card._dd_voice_pick._options
    assert labels[0] == "Random (any)"
    assert any("Morning VT" in l and "#4" in l for l in labels)
    assert any("Evening VT" in l and "#9" in l for l in labels)


def test_selected_voice_track_id(card):
    card.set_voice_tracks([{"id": 4, "label": "Morning VT"}])
    assert card.selected_voice_track_id() is None      # Random (any)
    target = next(l for l in card._dd_voice_pick._options if "#4" in l)
    card._dd_voice_pick._value = target
    assert card.selected_voice_track_id() == 4


def test_voice_element_is_pinned_when_a_track_is_picked(editor):
    _select(editor, "voice")
    editor._lib.set_voice_tracks([{"id": 41, "label": "VT One"}])
    target = next(l for l in editor._lib._dd_voice_pick._options
                  if "#41" in l)
    editor._lib._dd_voice_pick._value = target
    el = editor._build_element_from_filters()
    assert el["element_type"] == "voice"
    assert el["item_id"] == 41
    assert el["selection_mode"] == "specific"


def test_voice_element_stays_random_by_default(editor):
    _select(editor, "voice")
    el = editor._build_element_from_filters()
    assert el["item_id"] is None
    assert el["selection_mode"] == "random_from_category"


# ── Filter Results reflects the selected type ───────────────────────────


def test_results_use_each_type_own_library(editor, db):
    """Jingle/sweeper/voice report their own counts, not the song
    count. Compared against the same rows the scheduler would pick."""
    conn = db._conn()
    expected = {
        "jingle": conn.execute(
            "SELECT COUNT(*) FROM jingles WHERE is_enabled = 1 "
            "AND file_path IS NOT NULL AND file_path != ''").fetchone()[0],
        "sweeper": conn.execute(
            "SELECT COUNT(*) FROM sweepers WHERE is_enabled = 1 "
            "AND file_path IS NOT NULL AND file_path != ''").fetchone()[0],
        "voice": conn.execute(
            "SELECT COUNT(*) FROM voice_tracks "
            "WHERE is_active = 1").fetchone()[0],
    }
    for t, n in expected.items():
        _select(editor, t)
        editor._refresh_filter_results()
        assert editor._results._count == n, f"{t}: {editor._results._count} != {n}"


def test_spot_results_are_zero(editor):
    """No candidate set exists for a Break slot — reporting a song
    count there is what made the panel look wired to the wrong data."""
    _select(editor, "spot")
    editor._refresh_filter_results()
    assert editor._results._count == 0
    assert editor._results._avg_s == 0.0


def test_non_song_results_average_is_seconds(editor, db):
    """avg comes back in SECONDS (durations are stored in ms)."""
    row = db._conn().execute(
        "SELECT COUNT(*), AVG(duration_ms) FROM sweepers "
        "WHERE is_enabled = 1 AND file_path IS NOT NULL "
        "AND file_path != ''").fetchone()
    if not row or not row[0]:
        pytest.skip("no playable sweepers in the library")
    count, avg_s = editor._non_song_results("sweeper")
    assert count == row[0]
    assert avg_s == pytest.approx(float(row[1]) / 1000.0, abs=0.01)


def test_unknown_type_results_are_zero(editor):
    assert editor._non_song_results("nonsense") == (0, 0.0)


# ── Badge counts ────────────────────────────────────────────────────────


def test_library_counts_drive_the_badge(card):
    card.set_library_counts({"jingle": 7, "sweeper": 3, "voice": 2})
    assert card._lib_counts["jingle"] == 7
    assert card._lib_counts["sweeper"] == 3
    assert card._lib_counts["voice"] == 2


def test_editor_load_populates_library_counts(editor, db):
    """load_for_mode must seed the counts so the badge is right on the
    very first paint, not only after a type switch."""
    counts = editor._lib._lib_counts
    assert set(counts) >= {"jingle", "sweeper", "voice"}
    n_sweep = db._conn().execute(
        "SELECT COUNT(*) FROM sweepers WHERE is_enabled = 1").fetchone()[0]
    assert counts["sweeper"] == n_sweep


# ── Paint smoke — every type must render ────────────────────────────────


def test_every_type_paints(card, qapp):
    from PyQt6.QtGui import QPixmap
    for t in ("song", "jingle", "spot", "voice", "sweeper"):
        _select(card, t)
        pm = card.grab()
        assert isinstance(pm, QPixmap) and not pm.isNull()
