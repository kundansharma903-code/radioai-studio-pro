"""
Scheduling Hub unit tests — Jazler-style 7-tile nav grid (ref 225:3).

The previous version had week-matrix + status badges + AI Insight panels.
Per the reference rebuild, those are dropped; the Hub is now pure
navigation + a Studio launcher card.
"""

from __future__ import annotations

import pytest

from core.database import Database
from ui.scheduling_hub import (
    SchedulingHub, TILE_SPEC, _NavTile, _StudioLauncher,
)


@pytest.fixture
def hub(qtbot):
    db = Database()
    h = SchedulingHub(db=db)
    yield h


# ── 1. Renders the 7 tiles per ref ──────────────────────────────────────

def test_hub_renders_seven_tiles(hub):
    """The Jazler ref shows exactly 7 nav tiles. No 8th 'Clock Editor'
    card — that lives inside Auto Schedule now."""
    assert len(TILE_SPEC) == 7
    assert len(hub._tiles) == 7
    keys = set(hub._tiles.keys())
    assert keys == {"playlists", "final_log", "auto_schedule",
                    "force_clocks", "rebroadcast", "rds_settings",
                    "log_viewer"}
    assert all(isinstance(t, _NavTile) for t in hub._tiles.values())


# ── 2. Studio launcher in body, not header ──────────────────────────────

def test_hub_studio_launcher_in_body(hub):
    """Per ref 225:3, Studio launcher is a body-level card, not a
    header button. _launcher should be a child widget visible in the
    body area, not inside the header."""
    assert hasattr(hub, "_launcher")
    assert isinstance(hub._launcher, _StudioLauncher)
    # Geometry: bottom-right of body — y position should be below the
    # tile grid area (grid starts at y≈110, tile rows are 200 tall +
    # 24 gap, launcher sits in row-2 area i.e. y > 100).
    geom = hub._launcher.geometry()
    assert geom.y() > 100


# ── 3. Header has no AI Magic tab (only 4 tabs) ─────────────────────────

def test_header_has_four_tabs_no_ai_magic(hub):
    """Per ref the top nav is Libraries / Scheduling / Settings /
    Utilities — no AI Magic. AI Magic was a Phase E placeholder we
    used in the 50:2 build; rebuild drops it."""
    from PyQt6.QtWidgets import QPushButton
    nav_buttons = [b for b in hub._header.findChildren(QPushButton)]
    labels = [b.text() for b in nav_buttons]
    assert "Libraries"  in labels
    assert "Scheduling" in labels
    assert "Settings"   in labels
    assert "Utilities"  in labels
    assert "AI Magic"   not in labels
    assert "AI Magic ✦" not in labels


# ── 4. Dropped panels are gone ──────────────────────────────────────────

def test_dropped_panels_are_absent(hub):
    """Status badges / week matrix / AI Insight / song separation rules
    were removed — the corresponding attributes shouldn't exist."""
    for attr in ("_badge_clocks", "_badge_log", "_badge_auto",
                 "_matrix", "_ai_cards", "_nav_cards"):
        assert not hasattr(hub, attr), \
            f"dropped attribute {attr!r} still on Hub"


# ── 5. Tile click emits breadcrumb to MainWindow target ─────────────────

def test_tile_click_emits_breadcrumb(qtbot, hub):
    """Clicking the auto_schedule tile should emit
    breadcrumb_clicked('auto_schedule')."""
    received: list[str] = []
    hub.breadcrumb_clicked.connect(received.append)
    hub._on_tile_clicked("auto_schedule")
    assert received == ["auto_schedule"]


# ── 6. Studio launcher click emits studio_clicked ──────────────────────

def test_studio_launcher_click_emits_studio_clicked(qtbot, hub):
    received: list[None] = []
    hub.studio_clicked.connect(lambda: received.append(None))
    # Simulate the click signal directly
    hub._launcher.clicked.emit()
    assert len(received) == 1
