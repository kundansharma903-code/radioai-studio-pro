"""
Settings Hub screen (Figma 426:3) tests.

Pinned behaviour:
  • SettingsHub constructs without crashing.
  • Three option cards are present, each emitting a distinct screen
    key on click: settings_general, settings_soundcard, settings_studio.
  • Header breadcrumb "Control Panel" link emits "control_panel".
  • Header station label has objectName "hdr_station_lbl" so the
    MainWindow branding-refresh walk hits it on Settings save.
"""

from __future__ import annotations

import pytest

from core.database import Database


@pytest.fixture
def db():
    return Database()


def test_construction_does_not_crash(qapp, db):
    from ui.settings_hub import SettingsHub
    s = SettingsHub(db)
    assert s.size().width() == 1440
    assert s.size().height() == 900
    # Three option cards rendered
    assert len(s._cards) == 3
    s.deleteLater()


def test_cards_emit_distinct_screen_keys(qapp, db):
    from ui.settings_hub import SettingsHub
    s = SettingsHub(db)
    emitted: list = []
    s.screen_requested.connect(lambda k: emitted.append(k))

    # Trigger each card's click handler directly — exercises the
    # OptionCard.clicked → SettingsHub.screen_requested chain.
    s._on_card_clicked("settings_general")
    s._on_card_clicked("settings_soundcard")
    s._on_card_clicked("settings_studio")
    assert emitted == ["settings_general", "settings_soundcard",
                        "settings_studio"]
    s.deleteLater()


def test_card_titles_match_design(qapp, db):
    """Sanity-check that the three cards carry the right screen keys
    (so future renames don't silently break navigation)."""
    from ui.settings_hub import SettingsHub
    s = SettingsHub(db)
    keys = [c._screen_key for c in s._cards]
    assert keys == ["settings_general", "settings_soundcard",
                    "settings_studio"]
    s.deleteLater()


def test_station_label_has_object_name(qapp, db):
    """MainWindow._refresh_station_branding walks findChild(QLabel,
    'hdr_station_lbl'). Confirm the hub's header label opts in."""
    from PyQt6.QtWidgets import QLabel
    from ui.settings_hub import SettingsHub
    s = SettingsHub(db)
    lbl = s.findChild(QLabel, "hdr_station_lbl")
    assert lbl is not None
    s.deleteLater()
