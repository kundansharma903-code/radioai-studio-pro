"""
Studio StopNext button — visual armed-state feedback.

Operator (Kavish) reported 2026-05-07: "stop next button is not working".
Tracing showed the button click WAS reaching the handler — flag was
being set, EOS branch was idling correctly. But there was no visual
confirmation that the click registered, so the operator concluded the
button was broken.

Fix: ControlCluster now exposes set_stop_armed(bool) which toggles the
StopNext button's existing accent-glow active state (same treatment
Loop and Pause use). Studio's _on_stop_next_clicked is now a TOGGLE:
  • First click  → arm (flag True, button glows red)
  • Second click → disarm (flag False, button reverts)
EOS handler that consumes the flag also clears the visual. New song
load (_on_queue_song_play) syncs the visual to the reset flag.
"""

from __future__ import annotations

import pytest

from core.database import Database
from ui.studio import Studio


def _make_studio(db) -> Studio:
    return Studio(db, parent=None, engine=None,
                  scheduler=None, instant_jingle_engine=None,
                  sweeper_engine=None)


@pytest.fixture
def db():
    return Database()


# ── Toggle behaviour ──────────────────────────────────────────────────────

def test_first_click_arms_visual_and_sets_flag(qapp, db):
    studio = _make_studio(db)
    assert studio._stop_after_current is False
    assert studio._control_cluster.is_stop_armed() is False

    studio._on_stop_next_clicked()

    assert studio._stop_after_current is True
    assert studio._control_cluster.is_stop_armed() is True
    studio.deleteLater()


def test_second_click_disarms_visual_and_clears_flag(qapp, db):
    """Toggle behaviour: clicking again cancels the pending stop."""
    studio = _make_studio(db)
    studio._on_stop_next_clicked()        # arm
    studio._on_stop_next_clicked()        # disarm

    assert studio._stop_after_current is False
    assert studio._control_cluster.is_stop_armed() is False
    studio.deleteLater()


def test_arm_visual_clears_when_eos_consumes_flag(qapp, db):
    """When the song ends and the EOS branch idles, the visual must
    revert so the operator sees the action was honoured."""
    studio = _make_studio(db)
    studio._on_stop_next_clicked()        # arm
    assert studio._control_cluster.is_stop_armed() is True

    # Simulate EOS: set up the deck state + run the handler
    studio._playback_cid = 7
    studio._playback_kind = "deck"
    studio._engine = type("FE", (), {"cleanup": lambda *_: None})()
    studio._on_engine_playback_ended(7)

    assert studio._stop_after_current is False
    assert studio._control_cluster.is_stop_armed() is False
    studio.deleteLater()


def test_arm_visual_resets_on_new_song_load(qapp, db, tmp_path):
    """If somehow the flag is cleared while the visual is still armed
    (e.g. defensive programming bug), loading a new song re-syncs the
    visual to the (cleared) flag."""
    studio = _make_studio(db)
    # Force a "stale armed" state to test the re-sync
    studio._control_cluster.set_stop_armed(True)

    # Load a new song via _on_queue_song_play — needs a real path
    fake_audio = tmp_path / "x.mp3"
    fake_audio.write_bytes(b"fake")
    studio._engine = type(
        "FE", (), {
            "cleanup": lambda *_: None,
            "load_file": lambda *_: 99,
            "set_volume": lambda *_: None,
            "play": lambda *_: None,
            "get_duration_ms": lambda *_: 180000,
        })()

    studio._on_queue_song_play({
        "id": 1, "title": "T", "artist": "A",
        "file_path": str(fake_audio), "duration_ms": 180000,
    })

    assert studio._control_cluster.is_stop_armed() is False
    studio.deleteLater()
