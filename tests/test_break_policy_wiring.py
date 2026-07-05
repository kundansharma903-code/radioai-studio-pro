"""
Break Policy — Studio valve + DB layer wiring tests.

Pinned behaviour (operator-approved 2026-07-04):
  • Policy OFF (the default): spot_due takes the ORIGINAL path —
    the pool stays empty forever (byte-identical legacy flow).
  • Policy ON: spot_due HOLDS the campaign in _break_pool; the FIFO
    (_pending_spots) is untouched until a window minute opens.
  • Window release: pool → budget check → category interleave →
    SAME _pending_spots FIFO; one release per window minute.
  • Overflow defers (stays pooled), never drops.
  • _policy_exempt callers (EOS chain / manual fire) bypass the hold.
  • _drain_pending_dispatches clears the pool too.
  • DB: ad_categories CRUD + campaign assignment + aired-seconds sum.

Settings are snapshotted/restored so the (shielded) DB stays
deterministic for other files.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from core.database import Database
from core.settings import Settings


PFX = "bp-test"


@pytest.fixture
def policy_settings():
    s = Settings()
    keep = {k: s.get(k) for k in (
        "break_policy_enabled", "break_policy_windows",
        "break_policy_max_ad_seconds_hour")}
    s.set("break_policy_enabled", "1")
    s.set("break_policy_windows", "15,30,45")
    s.set("break_policy_max_ad_seconds_hour", "660")
    yield s
    for k, v in keep.items():
        s.set(k, v if v is not None else "0")


@pytest.fixture
def studio(qtbot, engine):
    from ui.studio import Studio
    db = Database()
    s = Studio(db=db, engine=engine, scheduler=None,
               instant_jingle_engine=None)
    yield s
    if s._playback_cid is not None:
        try:
            engine.cleanup(s._playback_cid)
        except Exception:
            pass


def _mk_campaign(db, name, cat_name=None) -> int:
    cid = db.add_campaign({"name": f"{PFX}-{name}",
                           "is_active": 1})
    if cat_name:
        acid = db.add_ad_category(cat_name)
        db.set_campaign_ad_category(cid, acid)
    return int(cid)


def _cleanup_campaigns(db, ids):
    for cid in ids:
        try:
            db.delete_campaign(int(cid))
        except Exception:
            pass


# ── DB layer ────────────────────────────────────────────────────────────

def test_ad_categories_defaults_and_add():
    db = Database()
    names = [c["name"] for c in db.get_ad_categories()]
    for want in ("Education", "Healthcare", "Automobile",
                 "Resto Hotel", "Gas Station", "Others"):
        assert want in names
    assert names[-1] == "Others"          # pinned last
    new_id = db.add_ad_category(f"{PFX}-Jewellery")
    assert new_id == db.add_ad_category(f"{PFX}-Jewellery")  # idempotent
    db.execute("DELETE FROM ad_categories WHERE id = ?", (new_id,))


def test_campaign_ad_category_roundtrip():
    db = Database()
    ids = []
    try:
        cid = _mk_campaign(db, "cat-rt", "Education")
        ids.append(cid)
        assert db.get_campaign_ad_category_name(cid) == "Education"
        db.set_campaign_ad_category(cid, None)
        assert db.get_campaign_ad_category_name(cid) == ""
    finally:
        _cleanup_campaigns(db, ids)


def test_spot_seconds_aired_since_sums_only_spots():
    db = Database()
    assert db.get_spot_seconds_aired_since(
        "2099-01-01 00:00:00") == 0.0
    total = db.get_spot_seconds_aired_since("2000-01-01 00:00:00")
    assert total > 0        # real broadcast_log has spot rows


# ── Studio valve ────────────────────────────────────────────────────────

def test_policy_off_is_passthrough(qtbot, studio, monkeypatch):
    Settings().set("break_policy_enabled", "0")
    fired = []
    monkeypatch.setattr(studio, "_pool_spot_entry",
                        lambda cid: fired.append(cid))
    # OFF → the classic dispatcher runs; the pool path never touches
    # the campaign. (Campaign 424242 has no files → classic path logs
    # 'no playable spot file' and returns — but the POOL stays empty.)
    studio._on_scheduler_spot_due(424242)
    assert studio._break_pool == []
    assert fired == []


def test_policy_on_holds_spot_in_pool(qtbot, studio, policy_settings):
    db = studio._db
    ids = []
    try:
        cid = _mk_campaign(db, "hold", "Education")
        ids.append(cid)
        studio._on_scheduler_spot_due(cid)
        assert [e["campaign_id"] for e in studio._break_pool] == [cid]
        assert studio._pending_spots == []       # FIFO untouched
    finally:
        _cleanup_campaigns(db, ids)


def test_window_release_interleaves_into_fifo(qtbot, studio,
                                              policy_settings,
                                              monkeypatch):
    db = studio._db
    ids = []
    try:
        e1 = _mk_campaign(db, "edu1", "Education")
        e2 = _mk_campaign(db, "edu2", "Education")
        h1 = _mk_campaign(db, "health1", "Healthcare")
        ids += [e1, e2, h1]
        for cid in (e1, e2, h1):
            studio._on_scheduler_spot_due(cid)
        assert len(studio._break_pool) == 3

        # No aired seconds → whole pool fits the budget. Deck must be
        # BUSY: an idle deck immediately (and correctly) fires the
        # first released spot instead of leaving it queued.
        monkeypatch.setattr(
            db, "get_spot_seconds_aired_since", lambda _s: 0.0)
        studio._playback_cid = 12345
        studio._playback_kind = "deck"
        studio._current_track = {"id": 1, "title": "busy"}
        at_window = datetime(2026, 7, 4, 12, 15, 3)
        studio._tick_break_policy(at_window)

        assert studio._break_pool == []
        assert set(studio._pending_spots) == {e1, e2, h1}
        # Education must not be adjacent: edu, health, edu
        cats = [db.get_campaign_ad_category_name(c)
                for c in studio._pending_spots]
        assert cats[0] != cats[1] and cats[1] != cats[2]

        # Same window minute must NOT double-release
        studio._pending_spots.clear()
        studio._on_scheduler_spot_due(e1)
        studio._tick_break_policy(at_window.replace(second=30))
        assert studio._pending_spots == []       # still held
        assert len(studio._break_pool) == 1
    finally:
        studio._break_pool.clear()
        studio._pending_spots.clear()
        studio._playback_cid = None
        studio._playback_kind = None
        studio._current_track = None
        _cleanup_campaigns(db, ids)


def test_budget_overflow_stays_pooled(qtbot, studio, policy_settings,
                                      monkeypatch):
    db = studio._db
    ids = []
    try:
        cid = _mk_campaign(db, "over", "Education")
        ids.append(cid)
        studio._on_scheduler_spot_due(cid)
        # Hour already at the 11-min cap → the spot must defer.
        monkeypatch.setattr(
            db, "get_spot_seconds_aired_since", lambda _s: 660.0)
        studio._tick_break_policy(datetime(2026, 7, 4, 13, 30, 2))
        assert studio._pending_spots == []
        assert len(studio._break_pool) == 1      # deferred, not dropped
    finally:
        studio._break_pool.clear()
        _cleanup_campaigns(db, ids)


def test_exempt_call_bypasses_pool(qtbot, studio, policy_settings):
    # EOS-chain style call: must NOT pool even with policy ON.
    studio._do_scheduler_spot_due(998877, _policy_exempt=True)
    assert studio._break_pool == []


def test_auto_distribute_fills_grid_all_days(qtbot, monkeypatch,
                                             policy_settings):
    """Spot Programming '✦ Auto-Distribute': N rotations/day × 7 days
    land on the grid at break-window times; the info dialog carries
    the client time sheet."""
    from core import dialogs as _dialogs
    from ui.dialogs.spot_programming_dialog import SpotProgrammingDialog
    shown: list[str] = []
    monkeypatch.setattr(_dialogs, "info",
                        lambda _p, _t, text: shown.append(text))
    dlg = SpotProgrammingDialog(Database(), campaign_id=None)
    qtbot.addWidget(dlg)
    dlg._grid.clear_all()
    dlg._ad_rotations.setValue(6)
    dlg._ad_from.setCurrentText("09:00")
    dlg._ad_to.setCurrentText("12:00")

    dlg._on_auto_distribute()

    breaks = dlg._grid.get_breaks()
    assert len(breaks) == 6 * 7            # 6/day × all 7 days
    days = {d for (d, _s) in breaks}
    assert days == set(range(7))
    assert shown and "rotations/day" in shown[0]
    dlg.deleteLater()


def test_drain_clears_pool(qtbot, studio, policy_settings):
    db = studio._db
    ids = []
    try:
        cid = _mk_campaign(db, "drain", None)
        ids.append(cid)
        studio._on_scheduler_spot_due(cid)
        assert studio._break_pool
        studio._drain_pending_dispatches(reason="test drain")
        assert studio._break_pool == []
    finally:
        _cleanup_campaigns(db, ids)
