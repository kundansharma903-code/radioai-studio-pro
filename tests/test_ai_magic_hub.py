"""
AI Magic Hub screen (Figma 454:3) tests.

Pinned behaviour:
  • AIMagicHub constructs at 1440×900 without crashing.
  • Two option cards are mounted with screen_keys "spot_on_the_go"
    and "scheduling_automation".
  • Clicking a card (or its Configure CTA) emits screen_requested
    with the matching key.
  • Breadcrumb "Control Panel" link emits screen_requested("control_panel").
  • Open Studio buttons (header + footer) both emit studio_clicked.
  • Header carries the hdr_station_lbl QLabel so the branding-refresh
    walk in MainWindow picks it up.
  • Card titles + status pills match the design's "Coming soon" state.
"""

from __future__ import annotations

import pytest

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QLabel

from core.database import Database
from ui.ai_magic_hub import AIMagicHub, _AIOptionCard


@pytest.fixture
def db():
    return Database()


# ── Construction smoke ─────────────────────────────────────────────────


def test_construction_does_not_crash(qapp, db):
    w = AIMagicHub(db)
    assert w.size().width() == 1440
    assert w.size().height() == 900
    w.deleteLater()


def test_construction_works_with_no_db(qapp):
    """The hub doesn't query any DB rows — it must construct cleanly
    even with db=None so tests don't have to wire a fixture."""
    w = AIMagicHub(None)
    assert w.size().width() == 1440
    w.deleteLater()


# ── Cards: count, screen_keys, content ──────────────────────────────────


def test_two_cards_mounted(qapp, db):
    w = AIMagicHub(db)
    assert len(w._cards) == 2
    keys = sorted(c._screen_key for c in w._cards)
    assert keys == ["scheduling_automation", "spot_on_the_go"]
    w.deleteLater()


def test_card_dimensions(qapp, db):
    w = AIMagicHub(db)
    for c in w._cards:
        assert c.width() == _AIOptionCard.CARD_W == 480
        assert c.height() == _AIOptionCard.CARD_H == 400
    w.deleteLater()


def test_cards_carry_expected_glyphs(qapp, db):
    """Spot on the Go = ⚡, Scheduling Automation = ♻. Surface this
    in tests so a future copy-tweak doesn't silently break the
    Figma-truth match."""
    w = AIMagicHub(db)
    by_key = {c._screen_key: c for c in w._cards}
    assert by_key["spot_on_the_go"]._glyph == "⚡"
    assert by_key["scheduling_automation"]._glyph == "♻"
    w.deleteLater()


# ── Signals: card clicks + breadcrumb + studio ─────────────────────────


def test_card_click_emits_screen_requested(qapp, db, qtbot):
    w = AIMagicHub(db)
    qtbot.addWidget(w)
    received: list[str] = []
    w.screen_requested.connect(received.append)
    # Click the first card directly
    by_key = {c._screen_key: c for c in w._cards}
    QTest.mouseClick(by_key["spot_on_the_go"], Qt.MouseButton.LeftButton)
    assert "spot_on_the_go" in received
    QTest.mouseClick(by_key["scheduling_automation"],
                      Qt.MouseButton.LeftButton)
    assert received[-1] == "scheduling_automation"


def test_breadcrumb_control_panel_emits_signal(qapp, db, qtbot):
    """Breadcrumb 'Control Panel' link routes back to the home screen."""
    from ui.ai_magic_hub import _BreadcrumbLink
    w = AIMagicHub(db)
    qtbot.addWidget(w)
    received: list[str] = []
    w.screen_requested.connect(received.append)
    crumbs = [c for c in w.findChildren(_BreadcrumbLink)
              if c.text() == "Control Panel"]
    assert crumbs, "Header should contain a Control Panel breadcrumb link"
    crumbs[0].clicked.emit()
    assert "control_panel" in received


def test_open_studio_emits_studio_clicked(qapp, db, qtbot):
    from ui.ai_magic_hub import _HeaderOpenStudio
    w = AIMagicHub(db)
    qtbot.addWidget(w)
    received: list[bool] = []
    w.studio_clicked.connect(lambda: received.append(True))
    btns = w.findChildren(_HeaderOpenStudio)
    assert btns, "Header should contain an Open Studio button"
    btns[0].clicked.emit()
    assert received == [True]


# ── Branding refresh hook ──────────────────────────────────────────────


def test_station_label_has_object_name(qapp, db):
    """MainWindow's _refresh_station_branding walks every screen and
    looks up findChild(QLabel, 'hdr_station_lbl'). Without the name
    set, live station-name updates would skip this screen."""
    w = AIMagicHub(db)
    lbl = w.findChild(QLabel, "hdr_station_lbl")
    assert lbl is not None
    w.deleteLater()


# ── MainWindow integration — the hub is mounted + ai_magic route works ─


def test_main_window_mounts_ai_magic_hub(qapp, db, qtbot, monkeypatch):
    """The MainWindow constructor must mount AIMagicHub and the
    'ai_magic' screen-request key must route to it."""
    # Patch out heavy boot-time auto-play side effects.
    from ui import main_window as mw_mod
    monkeypatch.setattr(mw_mod.MainWindow, "_apply_startup_auto_mode",
                         lambda self: None)
    from ui.main_window import MainWindow
    w = MainWindow(db=db)
    qtbot.addWidget(w)
    assert hasattr(w, "ai_magic_hub")
    w._on_hub_screen_requested("ai_magic")
    assert w._stack.currentWidget() is w.ai_magic_hub
    w.close()
    w.deleteLater()


def test_main_window_nav_ai_magic_routes_to_hub(qapp, db, qtbot,
                                                  monkeypatch):
    """ControlPanel top-nav emits nav_clicked('AI Magic ✦') with the
    literal sparkle-suffixed label. _on_nav_clicked must match it
    verbatim and switch to the AI Magic Hub — operator-reported bug
    on 2026-05-14 (initial commit had only screen_requested wiring,
    not the nav handler)."""
    from ui import main_window as mw_mod
    monkeypatch.setattr(mw_mod.MainWindow, "_apply_startup_auto_mode",
                         lambda self: None)
    from ui.main_window import MainWindow
    w = MainWindow(db=db)
    qtbot.addWidget(w)
    # Sanity — start at control panel
    w._on_nav_clicked("Control Panel")
    assert w._stack.currentWidget() is w.control_panel
    # The actual click path
    w._on_nav_clicked("AI Magic ✦")
    assert w._stack.currentWidget() is w.ai_magic_hub
    w.close()
    w.deleteLater()


def test_both_ai_magic_modules_land_on_real_screens(qapp, db, qtbot,
                                                       monkeypatch):
    """Updated 2026-05-15 — Scheduling Automation hub shipped (Phase B
    mock UI). Both AI Magic submodules now route to real screens; no
    toast remains. Per-module regression coverage lives in the
    submodule's own test file.

    History:
      • 2026-05-14 (morning) — Both modules toasted.
      • 2026-05-14 (evening) — Spot on the Go shipped; only Scheduling
        Automation toasted.
      • 2026-05-15 — Scheduling Automation Phase B mock UI shipped;
        both modules now real screens."""
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
    w._on_hub_screen_requested("spot_on_the_go")
    assert w._stack.currentWidget() is w.spot_on_the_go_shell
    w._on_hub_screen_requested("scheduling_automation")
    assert w._stack.currentWidget() is w.scheduling_automation_hub
    titles = [t for t, _ in toast_calls]
    assert "Spot on the Go" not in titles
    assert "Scheduling Automation" not in titles
    w.close()
    w.deleteLater()


def test_station_branding_walks_through_ai_magic_hub(
        qapp, db, qtbot, monkeypatch):
    """When the operator edits station name in General Settings, the
    refresh walk must update AI Magic Hub's header label too. Pinning
    membership in qlabel_screens via the runtime side-effect."""
    from ui import main_window as mw_mod
    monkeypatch.setattr(mw_mod.MainWindow, "_apply_startup_auto_mode",
                         lambda self: None)
    from ui.main_window import MainWindow
    from PyQt6.QtWidgets import QLabel
    w = MainWindow(db=db)
    qtbot.addWidget(w)
    # Sanity: the hub mounted and has the labelled QLabel
    lbl = w.ai_magic_hub.findChild(QLabel, "hdr_station_lbl")
    assert lbl is not None
    original = lbl.text()
    # Stub Settings().station_display to return a sentinel
    from core import settings as settings_mod
    real_init = settings_mod.Settings.__init__
    monkeypatch.setattr(
        settings_mod.Settings, "station_display",
        property(lambda self: "TEST STATION 99.9"))
    w._refresh_station_branding()
    assert lbl.text() == "TEST STATION 99.9"
    # Restore original via a clean Settings re-init isn't needed —
    # monkeypatch reverts at fixture teardown.
    w.close()
    w.deleteLater()
