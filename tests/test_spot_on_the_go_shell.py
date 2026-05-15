"""
Spot on the Go shell (Figma 462:3) tests.

Pinned behaviour:
  • SpotOnTheGoShell constructs at 1440×900 without crashing.
  • Four step cards mount with screen_keys "create_schedule" /
    "assign" / "generate_report" / "assign_api_key" in that order.
  • Clicking a card (or its Open → CTA) emits screen_requested
    with the matching key.
  • Breadcrumbs: "Control Panel" → screen_requested("control_panel"),
    "AI Magic" → screen_requested("ai_magic").
  • Open Studio buttons emit studio_clicked.
  • Header hdr_station_lbl is set so the branding-refresh walk
    finds it.
  • MainWindow route "spot_on_the_go" lands on the shell (was a
    toast before this screen shipped).
  • MainWindow routes for the four sub-card keys toast "coming soon".
  • AI Magic Hub's "Spot on the Go" card click reaches the shell.
"""

from __future__ import annotations

import pytest

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QLabel

from core.database import Database
from ui.spot_on_the_go_shell import SpotOnTheGoShell, _StepCard


@pytest.fixture
def db():
    return Database()


# ── Construction smoke ─────────────────────────────────────────────────


def test_construction_does_not_crash(qapp, db):
    w = SpotOnTheGoShell(db)
    assert w.size().width() == 1440
    assert w.size().height() == 900
    w.deleteLater()


def test_construction_works_with_no_db(qapp):
    w = SpotOnTheGoShell(None)
    assert w.size().width() == 1440
    w.deleteLater()


# ── Cards ──────────────────────────────────────────────────────────────


def test_four_cards_mounted_in_order(qapp, db):
    """Card order pinned to the design's STEP 1 → 4 sequence so a
    future re-ordering is a deliberate change, not a silent slip."""
    w = SpotOnTheGoShell(db)
    assert len(w._cards) == 4
    keys = [c._screen_key for c in w._cards]
    assert keys == ["create_schedule", "assign",
                    "generate_report", "assign_api_key"]
    steps = [c._step_num for c in w._cards]
    assert steps == [1, 2, 3, 4]
    w.deleteLater()


def test_card_dimensions(qapp, db):
    w = SpotOnTheGoShell(db)
    for c in w._cards:
        assert c.width() == _StepCard.CARD_W == 312
        assert c.height() == _StepCard.CARD_H == 380
    w.deleteLater()


def test_card_glyphs(qapp, db):
    """STEP glyphs ✚ / ↗ / ▤ / ⚿ — surface in tests so a future
    copy-tweak that changes the icons is intentional."""
    w = SpotOnTheGoShell(db)
    by_key = {c._screen_key: c._glyph for c in w._cards}
    assert by_key == {
        "create_schedule":  "✚",
        "assign":           "↗",
        "generate_report":  "▤",
        "assign_api_key":   "⚿",
    }
    w.deleteLater()


# ── Signals ────────────────────────────────────────────────────────────


def test_card_click_emits_screen_requested(qapp, db, qtbot):
    w = SpotOnTheGoShell(db)
    qtbot.addWidget(w)
    received: list[str] = []
    w.screen_requested.connect(received.append)
    by_key = {c._screen_key: c for c in w._cards}
    for key in ("create_schedule", "assign",
                 "generate_report", "assign_api_key"):
        QTest.mouseClick(by_key[key], Qt.MouseButton.LeftButton)
    assert received == ["create_schedule", "assign",
                         "generate_report", "assign_api_key"]


def test_breadcrumb_control_panel_emits_signal(qapp, db, qtbot):
    from ui.spot_on_the_go_shell import _BreadcrumbLink
    w = SpotOnTheGoShell(db)
    qtbot.addWidget(w)
    received: list[str] = []
    w.screen_requested.connect(received.append)
    cps = [c for c in w.findChildren(_BreadcrumbLink)
            if c.text() == "Control Panel"]
    assert cps, "Header should contain a Control Panel breadcrumb link"
    cps[0].clicked.emit()
    assert "control_panel" in received


def test_breadcrumb_ai_magic_emits_signal(qapp, db, qtbot):
    """The 'AI Magic' crumb routes back to the parent hub — the path
    Control Panel | AI Magic | [Spot on the Go] requires both
    intermediate links to be navigable."""
    from ui.spot_on_the_go_shell import _BreadcrumbLink
    w = SpotOnTheGoShell(db)
    qtbot.addWidget(w)
    received: list[str] = []
    w.screen_requested.connect(received.append)
    crumbs = [c for c in w.findChildren(_BreadcrumbLink)
               if c.text() == "AI Magic"]
    assert crumbs, "Header should contain an AI Magic breadcrumb link"
    crumbs[0].clicked.emit()
    assert "ai_magic" in received


def test_open_studio_emits_studio_clicked(qapp, db, qtbot):
    from ui.spot_on_the_go_shell import _HeaderOpenStudio
    w = SpotOnTheGoShell(db)
    qtbot.addWidget(w)
    received: list[bool] = []
    w.studio_clicked.connect(lambda: received.append(True))
    btns = w.findChildren(_HeaderOpenStudio)
    assert btns, "Header should contain an Open Studio button"
    btns[0].clicked.emit()
    assert received == [True]


# ── Branding refresh hook ──────────────────────────────────────────────


def test_station_label_has_object_name(qapp, db):
    w = SpotOnTheGoShell(db)
    lbl = w.findChild(QLabel, "hdr_station_lbl")
    assert lbl is not None
    w.deleteLater()


# ── MainWindow integration ─────────────────────────────────────────────


def test_main_window_mounts_spot_on_the_go_shell(
        qapp, db, qtbot, monkeypatch):
    from ui import main_window as mw_mod
    monkeypatch.setattr(mw_mod.MainWindow, "_apply_startup_auto_mode",
                         lambda self: None)
    from ui.main_window import MainWindow
    w = MainWindow(db=db)
    qtbot.addWidget(w)
    assert hasattr(w, "spot_on_the_go_shell")
    w._on_hub_screen_requested("spot_on_the_go")
    assert w._stack.currentWidget() is w.spot_on_the_go_shell
    w.close()
    w.deleteLater()


def test_main_window_ai_magic_card_routes_to_shell(
        qapp, db, qtbot, monkeypatch):
    """AI Magic Hub's 'Spot on the Go' card emits
    screen_requested('spot_on_the_go') — verify the host routes it
    to the new shell (not the old toast)."""
    from ui import main_window as mw_mod
    monkeypatch.setattr(mw_mod.MainWindow, "_apply_startup_auto_mode",
                         lambda self: None)
    from ui.main_window import MainWindow
    w = MainWindow(db=db)
    qtbot.addWidget(w)
    # Direct emit on the AI Magic Hub's signal — simulates the card click
    w.ai_magic_hub.screen_requested.emit("spot_on_the_go")
    assert w._stack.currentWidget() is w.spot_on_the_go_shell
    w.close()
    w.deleteLater()


def test_all_four_step_cards_route_to_real_screens(
        qapp, db, qtbot, monkeypatch):
    """Updated 2026-05-15 — all four SOTG step cards now route to real
    screens (Create Schedule, Assign, Generate Report, Assign API Key).
    No card should produce a "coming soon" toast anymore.

    Renamed from test_only_assign_api_key_card_still_toasts after
    Phase F shipped the Assign API Key screen (Figma 503:3) +
    Transcription Engine, closing the last placeholder."""
    from ui import main_window as mw_mod
    monkeypatch.setattr(mw_mod.MainWindow, "_apply_startup_auto_mode",
                         lambda self: None)
    from ui.main_window import MainWindow
    w = MainWindow(db=db)
    qtbot.addWidget(w)
    toast_calls: list[tuple] = []
    from PyQt6.QtWidgets import QMessageBox
    monkeypatch.setattr(
        QMessageBox, "information",
        lambda parent, title, text: toast_calls.append((title, text)))
    for key in ("create_schedule", "assign",
                 "generate_report", "assign_api_key"):
        w._on_hub_screen_requested(key)
    titles = [t for t, _ in toast_calls]
    assert "Create Schedule" not in titles    # real screen
    assert "Assign" not in titles              # real screen
    assert "Generate Report" not in titles    # real screen
    assert "Assign API Key" not in titles      # real screen (Phase F)
    w.close()
    w.deleteLater()
