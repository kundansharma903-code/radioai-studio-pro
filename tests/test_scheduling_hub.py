"""
Scheduling Hub tests — premium-theme rebuild (Figma 231:3).

Covers:
  - Smoke render (instantiate without exception)
  - 7 tiles + Studio Launcher present
  - screen_requested signal emits the correct key per tile click
  - 1Hz tick updates header time + footer uptime
  - Scheduler started/stopped flips footer state and station-card pulse
  - Studio now-playing poll updates the launcher caption when a track
    is set on the Studio reference
"""

from __future__ import annotations

import pytest

from PyQt6.QtCore import QObject, pyqtSignal

from core.database import Database
from ui.scheduling_hub import (
    SchedulingHub, _TileCard, _StudioLauncher, _LiveTimePill,
    _StatusFooter, _ActiveStationCard,
    _TILE_SPECS_LEFT, _TILE_SPECS_RIGHT_TOP,
)


class _FakeScheduler(QObject):
    """Stand-in for SchedulerEngine that exposes the started / stopped
    signals + is_running()."""
    started = pyqtSignal()
    stopped = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._running = False

    def is_running(self) -> bool:
        return self._running

    def go(self) -> None:
        self._running = True
        self.started.emit()

    def halt(self) -> None:
        self._running = False
        self.stopped.emit()


class _FakeStudio:
    """Stand-in for Studio whose only relevant attribute is _current_track."""
    def __init__(self, track=None):
        self._current_track = track


@pytest.fixture
def hub(qtbot):
    db = Database()
    h = SchedulingHub(db=db)
    yield h


# ── Smoke ──────────────────────────────────────────────────────────────


def test_hub_mounts_without_exception(qtbot):
    """Hub instantiates with just a DB — no scheduler / studio required."""
    db = Database()
    h = SchedulingHub(db=db)
    assert h is not None
    assert h.width() == 1440
    assert h.height() == 900


def test_seven_tiles_plus_studio_launcher_visible(hub):
    """Per ref 231:3: 5 left-column + 2 right-column tiles + 1 launcher."""
    assert len(_TILE_SPECS_LEFT) == 5
    assert len(_TILE_SPECS_RIGHT_TOP) == 2
    assert len(hub._tiles) == 7
    assert isinstance(hub._launcher, _StudioLauncher)
    # Launcher sits in the bottom-right cell
    assert hub._launcher.x() == 732
    assert hub._launcher.y() == 600


def test_tile_keys_match_spec(hub):
    expected = {
        "playlists", "main_auto_schedule", "force_clocks", "rebroadcast",
        "rds", "final_log_creator", "log_viewer",
    }
    assert set(hub._tiles.keys()) == expected


# ── screen_requested signal ────────────────────────────────────────────


@pytest.mark.parametrize("tile_key", [
    "playlists", "main_auto_schedule", "force_clocks", "rebroadcast", "rds",
    "final_log_creator", "log_viewer",
])
def test_tile_click_emits_screen_requested(qtbot, hub, tile_key):
    """Each tile emits screen_requested with its key when clicked."""
    received: list[str] = []
    hub.screen_requested.connect(received.append)
    tile = hub._tiles[tile_key]
    # Direct emit on the tile's clicked signal (don't simulate mouse —
    # avoids GUI focus issues in headless test environments).
    tile.clicked.emit(tile_key)
    assert received == [tile_key]


def test_studio_launcher_click_routes_to_studio_open(qtbot, hub):
    received: list[str] = []
    hub.screen_requested.connect(received.append)
    hub._launcher.clicked.emit()
    assert "studio_open" in received


def test_go_live_button_routes_to_studio_open(qtbot, hub):
    received: list[str] = []
    hub.screen_requested.connect(received.append)
    hub._launcher.go_live_clicked.emit()
    assert "studio_open" in received


def test_header_open_studio_routes_to_studio_open(qtbot, hub):
    received: list[str] = []
    hub.screen_requested.connect(received.append)
    hub._header.studio_open_clicked.emit()
    assert "studio_open" in received


def test_header_libraries_routes_correctly(qtbot, hub):
    received: list[str] = []
    hub.screen_requested.connect(received.append)
    hub._header.libraries_clicked.emit()
    assert "libraries" in received


# ── 1Hz tick updates ───────────────────────────────────────────────────


def test_tick_updates_header_time(qtbot, hub):
    """Calling _on_tick refreshes the header's HH:MM display."""
    hub._on_tick()
    # Should be an HH:MM string (5 chars with a colon)
    assert ":" in hub._header._time_main
    assert len(hub._header._time_main) == 5


def test_tick_updates_live_pill(qtbot, hub):
    hub._on_tick()
    txt = hub._live_pill._clock_text
    # Expect HH:MM:SS (8 chars with two colons)
    assert txt.count(":") == 2
    assert len(txt) == 8


def test_tick_updates_footer_uptime(qtbot, hub):
    """Footer uptime starts as 'Program start up just now', then changes
    after a minute. We can't wait — just verify the format on first tick."""
    hub._on_tick()
    txt = hub._footer._uptime_text
    assert "Program" in txt


# ── Scheduler engine state ─────────────────────────────────────────────


def test_scheduler_running_flips_footer_to_healthy(qtbot):
    """When scheduler.started fires, footer reads 'SYSTEM HEALTHY'."""
    db = Database()
    sch = _FakeScheduler()
    h = SchedulingHub(db=db, scheduler=sch)
    # Default: not running → ENGINE STOPPED
    assert h._footer._heading == "ENGINE STOPPED"
    sch.go()
    assert h._footer._heading == "SYSTEM HEALTHY"
    assert h._header.station_card._pulse_on is True
    sch.halt()
    assert h._footer._heading == "ENGINE STOPPED"
    assert h._header.station_card._pulse_on is False


# ── Studio now-playing poll ────────────────────────────────────────────


def test_studio_now_playing_poll_updates_launcher(qtbot):
    """When a Studio reference is set with a current track, the
    launcher reads it on the next tick."""
    db = Database()
    studio = _FakeStudio({"title": "Chase The Sun", "artist": "Planet Funk"})
    h = SchedulingHub(db=db, studio=studio)
    h._on_tick()
    assert h._launcher._track_title == "Chase The Sun — Planet Funk"
    # Idle path
    h._studio = _FakeStudio(None)
    h._on_tick()
    assert h._launcher._track_title == "—"
    assert h._launcher._track_meta == "Studio idle"


def test_set_studio_after_construction_works(qtbot, hub):
    """Hub can have studio injected late (MainWindow may build the hub
    before Studio in some startup orders)."""
    studio = _FakeStudio({"title": "Get Lucky", "artist": "Daft Punk"})
    hub.set_studio(studio)
    hub._on_tick()
    assert "Get Lucky" in hub._launcher._track_title


# ── Component sanity ──────────────────────────────────────────────────


def test_live_pill_initial_state(qtbot, hub):
    pill = hub._live_pill
    assert isinstance(pill, _LiveTimePill)
    # Default text before first tick is "00:00:00"; after _on_tick in
    # __init__ it's a real time
    assert ":" in pill._clock_text


def test_active_station_card_present_in_header(qtbot, hub):
    card = hub._header.station_card
    assert isinstance(card, _ActiveStationCard)
    assert card.width() == 220
    assert card.height() == 60
