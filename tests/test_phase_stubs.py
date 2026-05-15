"""
Phase F4–F8 stub smoke tests.

Each stub screen is a Figma-faithful skeleton — heavy logic stubbed with
toasts. These tests just verify the screens mount cleanly and expose
their breadcrumb_clicked / studio_clicked signals.

Note: Playlists has been ported to the premium theme (Figma 239:2) and
no longer participates in this stub-style test. Its coverage lives in
tests/test_playlists_screen.py.
"""

from __future__ import annotations

import pytest

from core.database import Database
from ui.final_log    import FinalLog
from ui.log_viewer   import LogViewer
from ui.force_clocks import ForceClocks
from ui.rebroadcast  import Rebroadcast


@pytest.mark.parametrize("cls,name,expected_w,expected_h", [
    # FinalLog was upgraded to the 1920×1080 premium canvas during the
    # Final Log Creator build (Figma 14:2). The other three F4–F8 stubs
    # are still on the original 1440×900 design canvas — their toast
    # bodies haven't been ported yet.
    (FinalLog,    "FinalLog",    1920, 1080),
    (LogViewer,   "LogViewer",   1440,  900),
    (ForceClocks, "ForceClocks", 1440,  900),
    (Rebroadcast, "Rebroadcast", 1440,  900),
])
def test_stub_mounts_and_exposes_signals(qtbot, cls, name,
                                            expected_w, expected_h):
    """Each F4–F8 stub instantiates without error and exposes the
    contract that MainWindow wires (breadcrumb_clicked + studio_clicked)."""
    db = Database()
    screen = cls(db=db)
    assert screen is not None, f"{name} returned None"
    assert hasattr(screen, "breadcrumb_clicked"), \
        f"{name} missing breadcrumb_clicked"
    assert hasattr(screen, "studio_clicked"), \
        f"{name} missing studio_clicked"
    # Each is sized to its design canvas
    assert screen.width()  == expected_w, (
        f"{name} width {screen.width()} != expected {expected_w}")
    assert screen.height() == expected_h, (
        f"{name} height {screen.height()} != expected {expected_h}")
