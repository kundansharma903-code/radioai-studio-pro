"""
Scheduling Hub unit tests (Phase F3).

Covers SchedulingHub mounts cleanly, the nav cards exist with the
expected keys, the status badges reflect real DB counts, and the
day-part matrix renders without exception.
"""

from __future__ import annotations

import pytest

from core.database import Database
from ui.scheduling_hub import SchedulingHub, DAY_PARTS, DAYS, _NavCard


@pytest.fixture
def hub(qtbot):
    db = Database()
    h = SchedulingHub(db=db)
    yield h


# ── 1. Renders without crashing ────────────────────────────────────────

def test_hub_mounts_clean(hub):
    """SchedulingHub builds, all blocks instantiated, no exceptions."""
    assert hub._header is not None
    assert hub._matrix is not None
    assert hub._status is not None


# ── 2. Status badges reflect DB counts ─────────────────────────────────

def test_status_badges_show_real_counts(hub):
    db = hub._db
    n_clocks = len(list(db.get_all_clocks()))
    # The Clocks Built badge should display this count.
    assert hub._badge_clocks._txt.text().startswith(f"{n_clocks}")


# ── 3. Seven nav cards present with expected keys ──────────────────────

def test_seven_nav_cards_with_correct_keys(hub):
    expected = {"clock_editor", "final_log", "force_clocks",
                "playlists", "log_viewer", "rebroadcast", "rds_settings"}
    assert set(hub._nav_cards.keys()) == expected
    assert all(isinstance(c, _NavCard) for c in hub._nav_cards.values())


# ── 4. Day-part matrix has 6 day-parts and renders without exception ───

def test_week_matrix_renders(hub):
    """Force a paint pass on the matrix to surface any geometry errors."""
    assert len(DAY_PARTS) == 6
    assert len(DAYS) == 7
    # Trigger paint
    hub._matrix.repaint()
    # And the matrix has populated grid state from the DB on init.
    # _grid is a dict — may be empty if no auto_schedule rows exist.
    assert isinstance(hub._matrix._grid, dict)


# ── 5. Phase E placeholder marker present ──────────────────────────────

def test_ai_insight_placeholder_present(hub):
    """The AI SCHEDULING INSIGHT block should render the Phase E marker
    so future Anthropic integration has an obvious mount point."""
    # Walk the children and look for the phase marker text.
    found = False
    for child in hub.findChildren(type(hub._matrix).__bases__[0]):
        # _matrix's base class is QWidget — too broad. Use a tighter probe:
        pass
    # Easier: inspect the labels for the literal "Phase E" text.
    from PyQt6.QtWidgets import QLabel
    for lbl in hub.findChildren(QLabel):
        if "Phase E" in (lbl.text() or ""):
            found = True
            break
    assert found, "AI SCHEDULING INSIGHT block missing Phase E marker"
