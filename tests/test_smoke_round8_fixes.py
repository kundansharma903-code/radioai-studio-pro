"""
Findings from the re-smoke of build 929f48f (2026-10-19).

⚠35 "[rotation] plan pick honored" was logged at INFO by every Up Coming
     preview (up to 10 a second). Previews log it at DEBUG; a real pick
     stays INFO.
⚠36 With Break Policy ON, a spot inside the T-60 preview flashed as a
     queued "Ad Break" card although the policy holds it for the next
     break window. It now shows only once the window releases it.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta

import pytest

from core.database import Database
from core.scheduler.engine import SchedulerEngine
from tests.test_smoke_round7_fixes import _cards, _song, song_clock, studio  # noqa: F401

_REAL = sys.executable
_HONORED = "plan pick honored"


# ── ⚠35: plan-pick log level ──────────────────────────────────────────

@pytest.fixture
def plan_engine(song_clock, monkeypatch):
    db, now, _ = song_clock
    sid = int(db._conn().execute(
        "SELECT id FROM songs WHERE is_enabled = 1 ORDER BY id LIMIT 1"
    ).fetchone()[0])
    eng = SchedulerEngine(db=db)
    monkeypatch.setattr(eng, "_active_rotation_decisions", lambda: {
        "active": True, "rest_ids": set(),
        "picks": [{"song_id": sid, "action": "pick", "category_id": None,
                   "target_category_id": None, "file_path": _REAL,
                   "title": "Plan", "artist": "", "duration_ms": 180_000}]})
    # An air-time tag on the copy DB's hour would swap the slot and skip
    # the plan picks — keep the clock's own slots.
    monkeypatch.setattr(eng, "_apply_category_air_time",
                        lambda slots, *a, **k: slots)
    monkeypatch.setattr(eng, "_recent_artists", lambda _m: set())
    monkeypatch.setattr(eng, "_recent_song_ids", lambda _m: set())
    return eng, now


def _honored(caplog, level):
    return [r for r in caplog.records
            if _HONORED in r.getMessage() and r.levelno == level]


def test_previews_log_the_plan_pick_at_debug(plan_engine, caplog):
    eng, now = plan_engine
    caplog.set_level(logging.DEBUG, logger="Scheduler")
    eng.peek_next(3, now=now)
    assert _honored(caplog, logging.DEBUG)          # the preview did honor it
    assert not _honored(caplog, logging.INFO)


def test_a_real_pick_still_logs_the_plan_pick_at_info(plan_engine, caplog):
    eng, now = plan_engine
    caplog.set_level(logging.DEBUG, logger="Scheduler")
    eng.pick_next_item(now=now)
    assert len(_honored(caplog, logging.INFO)) == 1


# ── ⚠36: a spot the policy will hold is not shown as queued ───────────

def _preview_spot():
    bt = (datetime.now() + timedelta(seconds=30)).strftime("%H:%M")
    return [{"campaign_id": 19, "break_time": bt, "name": "MG Mall",
             "priority": "", "delta_s": 30}]


def _spot_cards(s):
    return [c for c in _cards(s) if c.song().get("_item_type") == "spot"]


@pytest.mark.parametrize("policy_on, shown", [(True, False), (False, True)])
def test_preview_spot_card_follows_break_policy(studio, monkeypatch,
                                                policy_on, shown):
    from ui.studio import Studio
    monkeypatch.setattr(Studio, "_break_policy_enabled",
                        lambda self: policy_on)
    s, _ = studio([_song("After")])
    s._upcoming_preview_spots = _preview_spot()
    s._load_upcoming_queue()
    assert bool(_spot_cards(s)) is shown
    # The NEXT glow and chip stay on the song either way.
    assert s._next_chip._title == "After"


def test_released_spot_shows_as_queued_with_policy_on(studio, monkeypatch):
    """Once the window releases it into the FIFO, the card is real."""
    from ui.studio import Studio
    monkeypatch.setattr(Studio, "_break_policy_enabled", lambda self: True)
    s, _ = studio([_song("After")])
    s._pending_spots = [19]
    s._load_upcoming_queue()
    assert len(_spot_cards(s)) == 1


# ── ⚠37: a newly added spot file stores its real duration ─────────────

def _wav(path, seconds=1.5, rate=8000):
    import wave
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))
    return str(path)


@pytest.fixture
def campaign(qapp):
    import uuid
    db = Database()
    cid = int(db.add_campaign({"name": f"_test_r8_{uuid.uuid4().hex[:8]}",
                               "is_active": 1, "priority": 5}))
    yield db, cid
    db.delete_campaign(cid)


def _stored(db, fid):
    return int(db._conn().execute(
        "SELECT duration_ms FROM spot_files WHERE id = ?",
        [fid]).fetchone()[0])


def test_add_spot_file_reads_the_duration(campaign, tmp_path):
    db, cid = campaign
    path = _wav(tmp_path / "ad.wav")
    fid = db.add_spot_file(cid, {"filename": "ad.wav", "file_path": path,
                                 "duration_ms": 0, "is_active": 1})
    assert 1400 <= _stored(db, fid) <= 1600
    # …and the Up Coming card / budget see it.
    assert 1400 <= db.get_campaign_spot_duration_ms(cid) <= 1600


def test_add_spot_file_keeps_a_given_duration(campaign, tmp_path):
    db, cid = campaign
    path = _wav(tmp_path / "ad.wav")
    fid = db.add_spot_file(cid, {"file_path": path, "duration_ms": 22_975})
    assert _stored(db, fid) == 22_975


def test_unreadable_spot_file_still_saves_with_zero(campaign, tmp_path):
    db, cid = campaign
    fid = db.add_spot_file(cid, {"file_path": str(tmp_path / "gone.mp3")})
    assert _stored(db, fid) == 0


def test_add_campaign_dialog_file_list_shows_the_duration(qapp, tmp_path):
    from ui.dialogs.add_campaign_dialog import _AudioFilesPanel
    lst = _AudioFilesPanel()
    lst.add_file(_wav(tmp_path / "ad.wav"))
    assert 1400 <= lst.files()[0]["duration_ms"] <= 1600
    lst.deleteLater()
