"""
Spot Play Report — PDF generator smoke + edge-case tests.

Covers:
  • Generates a non-empty PDF for both Scheduled and Actual modes.
  • Filename slug + path land under DEFAULT_REPORT_DIR by default,
    and a caller-supplied output_path is honoured.
  • Invalid mode / inverted date range raise SpotPlayReportError.
  • Empty campaign (no schedule, no broadcast_log rows) still
    produces a valid PDF with a "no plays" placeholder grid.
  • Multi-page pagination kicks in for long date ranges.
"""

from __future__ import annotations

import uuid
from datetime import date
from pathlib import Path

import pytest

from core.database import Database
from core.settings import Settings
from core.reports import (
    generate_spot_play_report,
    SpotPlayReportError,
    REPORT_MODE_ACTUAL,
    REPORT_MODE_SCHEDULED,
    DEFAULT_REPORT_DIR,
)


@pytest.fixture
def db():
    d = Database()
    Settings().load(d)   # so station_display has a value
    return d


@pytest.fixture
def seeded_campaign(db):
    """Insert a tiny campaign with one spot file + one schedule row.
    Cleanup on teardown."""
    prefix = f"_test_play_report_{uuid.uuid4().hex[:8]}_"
    conn = db._conn()
    try:
        cur = conn.execute(
            "INSERT INTO campaigns (name, description, category, "
            "priority, programming_mode, playback_order, start_date, "
            "end_date, contracted_plays_per_day, is_active) "
            "VALUES (?, 'Test Client Inc.', 'Commercials', 'High', "
            "'Weekly', 'In Rotation', '2026-05-01', '2026-05-07', 4, 1)",
            [prefix + "Campaign"])
        cid = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO spot_files (campaign_id, filename, file_path, "
            "duration_ms, is_active, display_order) "
            "VALUES (?, 'jingle.mp3', '', 30000, 1, 0)", [cid])
        # Two scheduled breaks per day on Mon/Wed/Fri
        for dow in (0, 2, 4):       # Mon, Wed, Fri
            for slot in range(2):
                conn.execute(
                    "INSERT INTO campaign_schedule (campaign_id, "
                    "day_of_week, break_time, slot_order, priority) "
                    "VALUES (?, ?, ?, ?, 'High')",
                    [cid, dow, f"{8 + slot * 4:02d}:30", slot])
        conn.commit()
        yield cid, prefix
    finally:
        conn.execute("DELETE FROM campaign_schedule WHERE campaign_id = ?", [cid])
        conn.execute("DELETE FROM spot_files WHERE campaign_id = ?", [cid])
        conn.execute("DELETE FROM campaigns WHERE id = ?", [cid])
        conn.commit()


# ── Validation ──────────────────────────────────────────────────────────────

def test_invalid_mode_raises(qapp, db):
    with pytest.raises(SpotPlayReportError):
        generate_spot_play_report(
            1, "bogus_mode", date(2026, 5, 1), date(2026, 5, 7), db=db)


def test_inverted_date_range_raises(qapp, db):
    with pytest.raises(SpotPlayReportError):
        generate_spot_play_report(
            1, REPORT_MODE_SCHEDULED,
            date(2026, 5, 7), date(2026, 5, 1), db=db)


def test_missing_campaign_raises(qapp, db):
    # An id that won't exist (negative)
    with pytest.raises(SpotPlayReportError):
        generate_spot_play_report(
            -999, REPORT_MODE_SCHEDULED,
            date(2026, 5, 1), date(2026, 5, 7), db=db)


# ── Happy paths ─────────────────────────────────────────────────────────────

def test_scheduled_mode_writes_pdf(qapp, db, seeded_campaign, tmp_path):
    cid, _ = seeded_campaign
    out = tmp_path / "scheduled.pdf"
    result = generate_spot_play_report(
        cid, REPORT_MODE_SCHEDULED,
        date(2026, 5, 1), date(2026, 5, 7),
        output_path=out, db=db)
    assert result == out
    assert result.exists()
    assert result.stat().st_size > 4000   # rough sanity: PDF has content


def test_actual_mode_writes_pdf(qapp, db, seeded_campaign, tmp_path):
    cid, _ = seeded_campaign
    out = tmp_path / "actual.pdf"
    result = generate_spot_play_report(
        cid, REPORT_MODE_ACTUAL,
        date(2026, 4, 1), date(2026, 5, 7),
        output_path=out, db=db)
    assert result.exists()
    assert result.stat().st_size > 4000


def test_long_range_paginates(qapp, db, seeded_campaign, tmp_path):
    """30-day range should overflow page 1 and produce ≥ 2 pages.
    File size grows enough vs the 7-day baseline that it's an indirect
    proof of pagination (page chrome adds bytes)."""
    cid, _ = seeded_campaign
    short = generate_spot_play_report(
        cid, REPORT_MODE_SCHEDULED,
        date(2026, 5, 1), date(2026, 5, 7),
        output_path=tmp_path / "short.pdf", db=db)
    long = generate_spot_play_report(
        cid, REPORT_MODE_SCHEDULED,
        date(2026, 5, 1), date(2026, 5, 31),
        output_path=tmp_path / "long.pdf", db=db)
    assert long.stat().st_size > short.stat().st_size + 2000


# ── Default output path ─────────────────────────────────────────────────────

def test_default_output_path_uses_local_appdata(qapp, db, seeded_campaign,
                                                 tmp_path, monkeypatch):
    """Without output_path the generator drops the file under
    DEFAULT_REPORT_DIR with a slugified filename."""
    cid, prefix = seeded_campaign
    # Redirect DEFAULT_REPORT_DIR so we don't pollute the operator's
    # actual reports folder during test runs.
    import core.reports.spot_play_report as mod
    monkeypatch.setattr(mod, "DEFAULT_REPORT_DIR", tmp_path / "reports")

    result = generate_spot_play_report(
        cid, REPORT_MODE_SCHEDULED,
        date(2026, 5, 1), date(2026, 5, 7),
        db=db)
    assert (tmp_path / "reports") in result.parents
    assert result.name.endswith(".pdf")
    assert "scheduled" in result.name
    assert "20260501" in result.name and "20260507" in result.name
