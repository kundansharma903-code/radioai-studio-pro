"""
Stitcher screen (Figma 46:481) + DB helpers tests.

Pinned behaviour:
  • db.get_stitcher_config() returns a dict with all editable fields.
  • db.update_stitcher_config(partial) writes only present keys +
    bumps updated_at; bool-ish fields coerced to 0/1.
  • Stitcher screen constructs without crashing on a real DB.
  • _load_config populates widgets from the DB row (round-trip).
  • Tab switch swaps between Tab 1 panels and the placeholder card.
  • _on_save_config writes to DB; out-of-range min>max is blocked
    with a warning (no DB write).
  • _on_preview_full assembles a sequence and routes through the
    StitcherEngine.play_block fake.
  • Sample playlist preview pulls from scheduler.peek_next when
    a scheduler is wired; falls back to recent songs when not.

Live-DB fixtures use a unique '_test_stitcher_<uuid8>_' prefix +
try/finally cleanup. The single-row stitcher_config is snapshotted
+ restored after each round-trip test.
"""

from __future__ import annotations

import uuid

import pytest

from core.database import Database
from core import dialogs as _dialogs


# ── Test doubles ────────────────────────────────────────────────────────


class _RecordingSignal:
    def __init__(self):
        self._slots: list = []

    def connect(self, slot) -> None:
        self._slots.append(slot)

    def emit(self, *args) -> None:
        for slot in list(self._slots):
            slot(*args)


class _FakeStitcherEngine:
    """Records play_block calls so the preview-full test can assert
    the assembled sequence without actually firing BASS."""

    def __init__(self):
        self.calls: list[dict] = []
        self._running = False

    def play_block(self, sequence, target_vol=85, on_step=None,
                   on_done=None):
        self.calls.append({
            "sequence":   list(sequence),
            "target_vol": int(target_vol),
        })
        self._running = True

    def stop(self):
        self._running = False

    @property
    def is_running(self):
        return self._running


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def db():
    return Database()


@pytest.fixture
def cfg_snapshot(db):
    """Snapshot the stitcher_config row before the test, restore
    after — keeps the dev DB unchanged across runs."""
    before = db.get_stitcher_config()
    yield before
    # Restore everything except `id` / `updated_at`.
    restore = {k: v for k, v in before.items()
               if k in db.STITCHER_EDITABLE_FIELDS}
    if restore:
        db.update_stitcher_config(restore)


# ── DB helpers ─────────────────────────────────────────────────────────


def test_get_stitcher_config_returns_dict_with_keys(db):
    cfg = db.get_stitcher_config()
    expected = {
        "opening_audio", "separator_audio", "closing_audio",
        "fallback_audio", "hook_duration_seconds", "min_hooks_required",
        "max_hooks", "module_enabled", "trigger_mode",
    }
    assert expected.issubset(set(cfg.keys()))


def test_update_stitcher_config_round_trip(db, cfg_snapshot):
    test_dur = (int(cfg_snapshot.get("hook_duration_seconds") or 8) % 9) + 5
    db.update_stitcher_config({"hook_duration_seconds": test_dur})
    after = db.get_stitcher_config()
    assert int(after["hook_duration_seconds"]) == test_dur


def test_update_stitcher_config_coerces_bools(db, cfg_snapshot):
    db.update_stitcher_config({"module_enabled": False})
    after = db.get_stitcher_config()
    assert int(after["module_enabled"]) == 0
    db.update_stitcher_config({"module_enabled": True})
    after = db.get_stitcher_config()
    assert int(after["module_enabled"]) == 1


def test_update_stitcher_config_partial_preserves_other_keys(db, cfg_snapshot):
    sep_before = cfg_snapshot.get("separator_audio")
    db.update_stitcher_config({"min_hooks_required": 3})
    after = db.get_stitcher_config()
    # min_hooks_required updated, separator untouched
    assert int(after["min_hooks_required"]) == 3
    assert (after.get("separator_audio") or "") == (sep_before or "")


# ── Screen smoke ───────────────────────────────────────────────────────


def test_construction_does_not_crash(qapp, db):
    from ui.stitcher import Stitcher
    s = Stitcher(db)
    assert s.size().width() == 1440
    assert s.size().height() == 900
    s.deleteLater()


def test_load_config_populates_widgets(qapp, db, cfg_snapshot):
    from ui.stitcher import Stitcher
    db.update_stitcher_config({
        "min_hooks_required": 4,
        "max_hooks": 6,
        "hook_duration_seconds": 10,
        "module_enabled": True,
    })
    s = Stitcher(db)
    assert s._inp_min_hooks.text() == "4"
    assert s._inp_max_hooks.text() == "6"
    assert s._inp_hook_dur.text() == "10"
    assert s._enabled_card.is_enabled() is True
    s.deleteLater()


# ── Tab switching ──────────────────────────────────────────────────────


def test_tab_switch_hides_left_center_right_panels(qapp, db):
    from ui.stitcher import Stitcher
    s = Stitcher(db)
    s.show()
    qapp.processEvents()
    # Tab 1 (Next Songs Hooks) is active by default — body panels visible.
    assert s._left_panel.isVisible()
    assert s._center_panel.isVisible()
    assert s._right_panel.isVisible()
    assert not s._tab_placeholder.isVisible()
    # Switch to "Real Time Announcement" — placeholder takes over.
    s._on_tab_clicked("Real Time Announcement")
    qapp.processEvents()
    assert not s._left_panel.isVisible()
    assert s._tab_placeholder.isVisible()
    # Switch back — body panels return.
    s._on_tab_clicked("Next Songs Hooks")
    qapp.processEvents()
    assert s._left_panel.isVisible()
    assert not s._tab_placeholder.isVisible()
    s.deleteLater()


# ── Save flow ──────────────────────────────────────────────────────────


def test_save_config_writes_to_db(qapp, db, cfg_snapshot, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    monkeypatch.setattr(_dialogs, "info",
                        lambda *a, **k: None)
    from ui.stitcher import Stitcher
    s = Stitcher(db)
    s._inp_min_hooks.setText("3")
    s._inp_max_hooks.setText("5")
    s._inp_hook_dur.setText("9")
    s._dd_trigger.set_value("Top of hour")
    s._enabled_card.set_enabled(True)
    s._on_save_config()
    after = db.get_stitcher_config()
    assert int(after["min_hooks_required"]) == 3
    assert int(after["max_hooks"]) == 5
    assert int(after["hook_duration_seconds"]) == 9
    assert after["trigger_mode"] == "top_of_hour"
    assert int(after["trigger_top_of_hour"]) == 1
    assert int(after["trigger_before_every_break"]) == 0
    s.deleteLater()


def test_save_config_blocks_invalid_min_max(qapp, db, cfg_snapshot, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    seen: list[str] = []
    monkeypatch.setattr(_dialogs, "warning",
                        lambda *a, **k: seen.append("warn") or
                        QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(_dialogs, "info",
                        lambda *a, **k: None)
    from ui.stitcher import Stitcher
    s = Stitcher(db)
    before = db.get_stitcher_config()
    s._inp_min_hooks.setText("9")
    s._inp_max_hooks.setText("3")
    s._on_save_config()
    after = db.get_stitcher_config()
    assert seen == ["warn"]
    # min_hooks_required should NOT have been written.
    assert int(after.get("min_hooks_required", 0)) == \
           int(before.get("min_hooks_required", 0))
    s.deleteLater()


# ── Preview full → engine.play_block ───────────────────────────────────


def test_preview_full_routes_sequence_to_stitcher_engine(qapp, db, monkeypatch):
    """Module enabled + at least 2 hooks present + audio paths set ⇒
    play_block called with a sequence containing opening + hooks +
    separators + closing."""
    from PyQt6.QtWidgets import QMessageBox
    monkeypatch.setattr(_dialogs, "info",
                        lambda *a, **k: None)
    monkeypatch.setattr(_dialogs, "warning",
                        lambda *a, **k: None)
    monkeypatch.setattr(
        "os.path.exists", lambda _p: True)   # bypass file checks
    fake_engine = _FakeStitcherEngine()
    from ui.stitcher import Stitcher
    s = Stitcher(db, stitcher_engine=fake_engine)
    s._cfg = {
        "module_enabled":      1,
        "opening_audio":       "/fake/open.mp3",
        "separator_audio":     "/fake/sep.mp3",
        "closing_audio":       "/fake/close.mp3",
        "fallback_audio":      "",
        "min_hooks_required":  2,
        "max_hooks":           3,
        "hook_duration_seconds": 8,
    }
    # Inject sample songs with hooks set so the assembly path picks
    # them up. Real DB row IDs aren't needed here — the stub
    # SELECT will fail on file_path, so monkeypatch _conn().execute()
    # to return a path row.
    s._sample_songs = [
        {"id": 1, "title": "T1", "artist": "A1",
         "hook_in_ms": 1000, "hook_out_ms": 9000},
        {"id": 2, "title": "T2", "artist": "A2",
         "hook_in_ms": 2000, "hook_out_ms": 10000},
    ]
    class _StubConn:
        def execute(self, *a, **k):
            class _R:
                def fetchone(_): return ("/fake/song.mp3",)
            return _R()
    s._db._conn = lambda: _StubConn()
    s._on_preview_full()
    assert len(fake_engine.calls) == 1
    seq = fake_engine.calls[0]["sequence"]
    labels = [step.get("label") for step in seq]
    # Opening + 2 hooks + separator (between hooks) + closing
    assert "OPENING" in labels
    assert "CLOSING" in labels
    assert labels.count("SEP") == 1   # only between the two hooks
    s.deleteLater()


def test_preview_full_blocked_when_module_disabled(qapp, db, monkeypatch):
    """Disabled module → Stitcher won't fire even if everything else
    is configured. Saves the operator from accidentally previewing
    a module they've intentionally taken offline."""
    from PyQt6.QtWidgets import QMessageBox
    monkeypatch.setattr(_dialogs, "info",
                        lambda *a, **k: None)
    fake_engine = _FakeStitcherEngine()
    from ui.stitcher import Stitcher
    s = Stitcher(db, stitcher_engine=fake_engine)
    s._cfg = dict(s._cfg)
    s._cfg["module_enabled"] = 0
    s._on_preview_full()
    assert fake_engine.calls == []
    s.deleteLater()
