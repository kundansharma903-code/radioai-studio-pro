"""
Playlists screen tests — premium-theme rebuild (Figma 239:2).

Covers:
  - Smoke render
  - DB load via showEvent populates stats + grid
  - Filter chips toggle + counts reflect data
  - Search debouncer filters the visible grid
  - Card selection updates detail panel
  - Open / + New emit screen_requested with the right keys
  - Add to Schedule routes through scheduler shim
  - Preview path returns gracefully when no engine wired
"""

from __future__ import annotations

import pytest

from PyQt6.QtCore import QObject, pyqtSignal

from core.database import Database
from core.scheduler.engine import SchedulerEngine
from ui.playlists import (
    Playlists, _kind_norm, _PlaylistCard, _StatCard, _FilterChip,
    _DetailPanel, _SearchInput,
)


# ── Fixture: a small in-DB playlist set we own ─────────────────────────


def _seed_test_playlists(db: Database) -> list[int]:
    """Insert 3 small playlists for testing. Returns the ids so the
    test can clean them up."""
    db._ensure_playlists_columns()
    conn = db._conn()
    ids: list[int] = []
    fixtures = [
        ("Playlists Test — Manual",   "manual",   None,        "00:00"),
        ("Playlists Test — Imported", "imported", "2026-05-05", "12:00"),
        ("Playlists Test — Smart",    "smart",    None,        "00:00"),
    ]
    for name, kind, sched_day, sched_time in fixtures:
        cur = conn.execute(
            "INSERT INTO playlists (name, description, kind, "
            "scheduled_day, scheduled_time, is_active, updated_at) "
            "VALUES (?, ?, ?, ?, ?, 1, datetime('now'))",
            [name, f"Test fixture — {kind}", kind, sched_day, sched_time],
        )
        ids.append(int(cur.lastrowid))
    conn.commit()
    return ids


def _delete_test_playlists(db: Database, ids: list[int]) -> None:
    conn = db._conn()
    for pid in ids:
        conn.execute("DELETE FROM playlist_songs WHERE playlist_id = ?", [pid])
        conn.execute("DELETE FROM playlists WHERE id = ?", [pid])
    conn.commit()


@pytest.fixture
def screen(qtbot):
    db = Database()
    ids = _seed_test_playlists(db)
    s = Playlists(db=db)
    s.show()        # triggers showEvent → reload
    qtbot.addWidget(s)
    yield s
    s.hide()
    _delete_test_playlists(db, ids)


# ── Smoke ───────────────────────────────────────────────────────────────


def test_screen_mounts_without_exception(qtbot):
    db = Database()
    s = Playlists(db=db)
    assert s is not None
    assert s.width() == 1440
    assert s.height() == 900


# ── Composition ─────────────────────────────────────────────────────────


def test_screen_composition(screen):
    """Header + LiveTimePill + 6 cards + 4 filter chips + 4 stat cards +
    detail panel + 2 toolbar buttons + 1 search input."""
    assert screen._header is not None
    assert screen._live_pill is not None
    assert len(screen._cards) == 6
    assert len(screen._chips) == 4
    assert isinstance(screen._stat_total, _StatCard)
    assert isinstance(screen._stat_tracks, _StatCard)
    assert isinstance(screen._stat_avg, _StatCard)
    assert isinstance(screen._stat_scheduled, _StatCard)
    assert isinstance(screen._detail, _DetailPanel)
    assert isinstance(screen._search, _SearchInput)


# ── DB load on showEvent ───────────────────────────────────────────────


def test_show_event_loads_playlists(screen):
    """After show(), _playlists is populated and stats reflect it."""
    # screen fixture seeded 3 test playlists; the DB may already have
    # other playlists too — assert at least our 3 are present.
    names = [p["name"] for p in screen._playlists]
    assert any("Playlists Test — Manual" in n for n in names)
    assert any("Playlists Test — Imported" in n for n in names)
    assert any("Playlists Test — Smart" in n for n in names)
    # Stat 1 reflects total count
    val = screen._stat_total._value
    assert int(val) >= 3


# ── Filter chips ───────────────────────────────────────────────────────


def test_filter_chip_counts_reflect_data(screen):
    """All chip count = total. Each kind chip count = # of that kind."""
    total = len(screen._playlists)
    n_manual = sum(1 for p in screen._playlists
                   if _kind_norm(p.get("kind")) == "manual")
    n_imported = sum(1 for p in screen._playlists
                     if _kind_norm(p.get("kind")) == "imported")
    n_smart = sum(1 for p in screen._playlists
                  if _kind_norm(p.get("kind")) == "smart")
    assert screen._chips["all"]._count      == total
    assert screen._chips["manual"]._count   == n_manual
    assert screen._chips["imported"]._count == n_imported
    assert screen._chips["smart"]._count    == n_smart


def test_filter_chip_click_filters_grid(screen):
    """Clicking 'Manual' chip filters _visible_playlists() to manual rows."""
    screen._on_chip_clicked("manual")
    visible = screen._visible_playlists()
    for p in visible:
        assert _kind_norm(p.get("kind")) == "manual"
    # Reset
    screen._on_chip_clicked("all")
    assert screen._filter_kind == "all"


# ── Search ─────────────────────────────────────────────────────────────


def test_search_filters_grid(screen):
    """Setting _search_text + calling _on_search filters visible list."""
    screen._on_search("imported")
    visible = screen._visible_playlists()
    assert all("imported" in (p.get("name") or "").lower()
               or "imported" in (p.get("description") or "").lower()
               for p in visible)
    # Reset
    screen._on_search("")


def test_search_input_has_debouncer(screen):
    """The search box uses a 200ms QTimer debouncer — sanity check it's
    attached and single-shot."""
    assert screen._search._debounce.isSingleShot()
    assert screen._search._debounce.interval() == 200


# ── Card selection → detail panel ──────────────────────────────────────


def test_card_selection_updates_detail_panel(screen):
    if not screen._playlists:
        pytest.skip("no playlists available")
    target_id = int(screen._playlists[0]["id"])
    screen._on_card_selected(target_id)
    assert screen._selected_id == target_id
    assert screen._detail.playlist_id == target_id


# ── screen_requested signal ────────────────────────────────────────────


def test_open_card_emits_playlist_edit(qtbot, screen):
    """Clicking 'Open →' on a card emits screen_requested('playlist_edit:<id>')."""
    received: list[str] = []
    screen.screen_requested.connect(received.append)
    if not screen._playlists:
        pytest.skip("no playlists")
    pid = int(screen._playlists[0]["id"])
    screen._on_open_card(pid)
    assert received == [f"playlist_edit:{pid}"]


def test_new_playlist_button_emits_playlist_new(qtbot, screen):
    received: list[str] = []
    screen.screen_requested.connect(received.append)
    screen._new_btn.clicked.emit()
    assert received == ["playlist_new"]


def test_header_studio_open_emits_studio_open(qtbot, screen):
    received: list[str] = []
    screen.screen_requested.connect(received.append)
    screen._header.studio_open_clicked.emit()
    assert "studio_open" in received


def test_header_libraries_emits_libraries(qtbot, screen):
    received: list[str] = []
    screen.screen_requested.connect(received.append)
    screen._header.libraries_clicked.emit()
    assert "libraries" in received


# ── Add to Schedule (real scheduler shim) ──────────────────────────────


def test_add_to_schedule_calls_scheduler(qtbot):
    """Add to Schedule routes through scheduler.add_playlist_to_schedule
    and stamps scheduled_day on the playlist row."""
    db = Database()
    sch = SchedulerEngine(db=db)
    ids = _seed_test_playlists(db)
    target = ids[0]   # 'Playlists Test — Manual', currently NOT scheduled
    try:
        ok = sch.add_playlist_to_schedule(target)
        assert ok is True
        # Verify DB toggled the schedule flag
        row = db._conn().execute(
            "SELECT scheduled_day FROM playlists WHERE id = ?", [target]
        ).fetchone()
        assert row["scheduled_day"]    # truthy date string
        # And remove_from_schedule clears it again
        ok2 = sch.remove_playlist_from_schedule(target)
        assert ok2 is True
        row = db._conn().execute(
            "SELECT scheduled_day FROM playlists WHERE id = ?", [target]
        ).fetchone()
        assert row["scheduled_day"] in (None, "")
    finally:
        _delete_test_playlists(db, ids)


# ── Preview no-engine fallthrough ─────────────────────────────────────


def test_preview_without_engine_does_not_crash(qtbot, screen):
    """When _engine is None, preview should pop a toast (or no-op) but
    never raise. Direct method invocation, no GUI click."""
    # screen fixture builds Playlists() without engine — preview should
    # be a graceful no-op (QMessageBox is non-blocking in this test env
    # because qtbot doesn't interact; either way, no raise).
    if not screen._playlists:
        pytest.skip("no playlists")
    pid = int(screen._playlists[0]["id"])
    # Studio is None too — preview confirms then returns.
    # We can't easily click through QMessageBox; verify the engine None
    # path returns without exception.
    screen._engine = None
    screen._on_preview_card(pid)


# ── _kind_norm ─────────────────────────────────────────────────────────


def test_kind_norm():
    assert _kind_norm(None)        == "manual"
    assert _kind_norm("")          == "manual"
    assert _kind_norm("Manual")    == "manual"
    assert _kind_norm("IMPORTED")  == "imported"
    assert _kind_norm("smart")     == "smart"
    assert _kind_norm("garbage")   == "manual"   # unknown falls back
