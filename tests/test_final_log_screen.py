"""
Final Log Creator (Figma 14:2) + DB helpers tests.

Pinned behaviour:
  • db.get_broadcast_log_for_hour(year, month, day, hour) returns
    only rows whose played_at falls in that hour on that date,
    oldest-first, with joined song/category/campaign/jingle metadata.
  • db.get_broadcast_hour_counts_for_date(year, month, day) returns
    a dict with all 24 hour keys (zero-filled), aggregated correctly.
  • FinalLog constructs on a real DB without crashing.
  • Initial date defaults to today.
  • Selecting a different hour reloads the table from the DB.
  • Stats strip aggregates totals from the rendered rows.
  • DOWNLOAD .TXT writes a formatted text file at the user-picked
    path; format includes header, per-row line, footer.
  • PRINT LOG shows the v1.1 placeholder dialog.

Live-DB tests insert broadcast_log rows with a unique 'test_final_log_<uuid8>'
operator marker and clean them up in a try/finally so the dev DB
stays consistent across runs.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime
from pathlib import Path

import pytest

from core.database import Database


# ── Helpers ────────────────────────────────────────────────────────────


@pytest.fixture
def db():
    return Database()


@pytest.fixture
def marked_log_rows(db):
    """Insert 3 rows on 2099-06-15 across hours 10 and 11, plus 1 row
    on a different date as a negative control. Cleans up via the
    unique operator marker on teardown."""
    marker = f"test_final_log_{uuid.uuid4().hex[:8]}"
    conn = db._conn()
    rows_to_insert = [
        # (played_at, entry_type, song_id, duration_ms)
        ("2099-06-15 10:05:30", "song",   None, 180_000),
        ("2099-06-15 10:08:15", "spot",   None,  30_000),
        ("2099-06-15 10:20:00", "song",   None, 200_000),
        ("2099-06-15 11:02:00", "jingle", None,   6_000),
        # Negative control — different date
        ("2099-06-16 10:00:00", "song",   None, 180_000),
    ]
    for played_at, etype, sid, dur in rows_to_insert:
        conn.execute(
            "INSERT INTO broadcast_log "
            "(played_at, entry_type, song_id, duration_ms, operator) "
            "VALUES (?, ?, ?, ?, ?)",
            [played_at, etype, sid, dur, marker])
    conn.commit()
    yield marker, rows_to_insert
    # Teardown
    try:
        conn.execute("DELETE FROM broadcast_log WHERE operator = ?",
                     [marker])
        conn.commit()
    except Exception:
        pass


# ── DB helper tests ────────────────────────────────────────────────────


def test_get_broadcast_log_for_hour_filters_by_date_and_hour(db, marked_log_rows):
    marker, _ = marked_log_rows
    rows = db.get_broadcast_log_for_hour(2099, 6, 15, 10)
    # Only the 3 rows seeded at hour 10 on 2099-06-15
    matching = [r for r in rows if r["operator"] == marker]
    assert len(matching) == 3
    # Oldest-first ordering preserved
    times = [r["played_at"] for r in matching]
    assert times == sorted(times)


def test_get_broadcast_log_for_hour_empty_when_no_match(db, marked_log_rows):
    rows = db.get_broadcast_log_for_hour(2099, 6, 15, 23)
    marker, _ = marked_log_rows
    matching = [r for r in rows if r["operator"] == marker]
    assert matching == []


def test_get_broadcast_log_for_hour_returns_neighbor_hour(db, marked_log_rows):
    marker, _ = marked_log_rows
    rows = db.get_broadcast_log_for_hour(2099, 6, 15, 11)
    matching = [r for r in rows if r["operator"] == marker]
    assert len(matching) == 1
    assert matching[0]["entry_type"] == "jingle"


def test_get_broadcast_hour_counts_for_date_has_all_24(db, marked_log_rows):
    counts = db.get_broadcast_hour_counts_for_date(2099, 6, 15)
    assert set(counts.keys()) == set(range(24))


def test_get_broadcast_hour_counts_for_date_aggregates(db, marked_log_rows):
    counts = db.get_broadcast_hour_counts_for_date(2099, 6, 15)
    # 3 rows at hour 10, 1 at hour 11, rest 0 (no other rows on this date
    # — marker is unique; pre-existing rows on 2099-06-15 are extremely
    # unlikely but we verify at minimum that hour-10 ≥ 3 and hour-11 ≥ 1)
    assert counts[10] >= 3
    assert counts[11] >= 1
    assert counts[23] == 0


def test_get_broadcast_hour_counts_for_date_empty_date(db):
    # A date with no broadcast rows — all zeros
    counts = db.get_broadcast_hour_counts_for_date(1990, 1, 1)
    assert all(counts[h] == 0 for h in range(24))


# ── Screen smoke ───────────────────────────────────────────────────────


def test_final_log_construction_does_not_crash(qapp, db):
    from ui.final_log import FinalLog
    s = FinalLog(db)
    assert s.size().width() == 1920
    assert s.size().height() == 1080
    s.deleteLater()


def test_initial_date_is_today(qapp, db):
    from ui.final_log import FinalLog
    from datetime import date as ddate
    s = FinalLog(db)
    today = ddate.today()
    assert s.selected_date_tuple() == (today.year, today.month, today.day)
    s.deleteLater()


def test_changing_month_repopulates_days(qapp, db):
    from ui.final_log import FinalLog
    s = FinalLog(db)
    s._month_cmb.setCurrentIndex(1)  # February
    s._month_cmb.currentIndexChanged.emit(1)
    # Feb has 28 or 29 days depending on year — never more than 29
    assert s._day_cmb.count() in (28, 29)
    s.deleteLater()


def test_selecting_hour_reloads_table(qapp, db, marked_log_rows):
    from ui.final_log import FinalLog
    s = FinalLog(db)
    # Reach into the in-memory date so the test rows are visible
    s._sel_year, s._sel_month, s._sel_day = 2099, 6, 15
    s._on_hour_selected(10)
    # 3 marker rows at hour 10 → table should reflect ≥ 3 rows
    assert s._table.rowCount() >= 3
    # Switch to a different hour — table changes
    s._on_hour_selected(23)
    assert s._table.rowCount() == 0
    s.deleteLater()


def test_stats_aggregate_from_rendered_rows(qapp, db):
    from ui.final_log import FinalLog
    s = FinalLog(db)
    fake_rows = [
        {"type": "song",    "title": "X", "artist": "Y",
         "category": "Pop", "time": "10:00:00",
         "duration": "3:00", "duration_ms": 180_000},
        {"type": "spot",    "title": "Ad", "artist": "—",
         "category": "Commercial", "time": "10:05:00",
         "duration": "0:30", "duration_ms": 30_000},
        {"type": "jingle",  "title": "Bell", "artist": "—",
         "category": "Station", "time": "10:08:00",
         "duration": "0:06", "duration_ms": 6_000},
    ]
    s._update_stats(fake_rows)
    # Total Items = 3
    assert s._stats._items[0]._val.text() == "3"
    # Songs = 1, Spots = 1, Jingles = 1, Sweepers = 0
    assert s._stats._items[1]._val.text() == "1"
    assert s._stats._items[2]._val.text() == "1"
    assert s._stats._items[3]._val.text() == "1"
    assert s._stats._items[4]._val.text() == "0"
    # Total Air Time = (180 + 30 + 6) sec = 216s = 3:36
    assert s._stats._items[5]._val.text() == "3:36"
    s.deleteLater()


def test_download_writes_formatted_text_file(qapp, db, monkeypatch, tmp_path):
    from ui.final_log import FinalLog
    from PyQt6.QtWidgets import QFileDialog
    s = FinalLog(db)
    s._sel_year, s._sel_month, s._sel_day = 2099, 6, 15
    s._hours.select_hour(10)

    target = tmp_path / "test_log.txt"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName",
        staticmethod(lambda *a, **kw: (str(target), "Log files (*.log *.txt)")))

    s._on_download_clicked()
    assert target.exists()
    content = target.read_text(encoding="utf-8")
    assert "BROADCAST LOG" in content
    assert "End of log" in content
    s.deleteLater()


def test_download_skipped_when_dialog_cancelled(
        qapp, db, monkeypatch, tmp_path):
    from ui.final_log import FinalLog
    from PyQt6.QtWidgets import QFileDialog
    s = FinalLog(db)

    monkeypatch.setattr(
        QFileDialog, "getSaveFileName",
        staticmethod(lambda *a, **kw: ("", "")))
    # Should not raise even when the user cancels
    s._on_download_clicked()
    s.deleteLater()


def test_print_shows_coming_soon_dialog(qapp, db, monkeypatch):
    from ui.final_log import FinalLog
    from PyQt6.QtWidgets import QMessageBox

    calls: list = []
    monkeypatch.setattr(
        QMessageBox, "information",
        staticmethod(
            lambda *args, **kwargs: calls.append((args, kwargs)) or 0))

    s = FinalLog(db)
    s._on_print_clicked()
    assert len(calls) == 1
    # Args: (parent, title, text)
    assert "Print Log" in calls[0][0][1]
    s.deleteLater()


def test_default_download_path_format(qapp, db):
    from ui.final_log import FinalLog
    s = FinalLog(db)
    s._sel_year, s._sel_month, s._sel_day = 2099, 6, 15
    p = s._default_download_path(hour=10)
    # Path looks like ...\\RadioAI\\logs\\2099\\June\\15\\10-11.log
    parts = p.parts
    assert "RadioAI" in parts
    assert "logs"    in parts
    assert "2099"    in parts
    assert "June"    in parts
    assert "15"      in parts
    assert p.name == "10-11.log"
    s.deleteLater()


def test_hour_label_format(qapp, db):
    from ui.final_log import _hour_label
    assert _hour_label(0)  == "00:00 – 01:00"
    assert _hour_label(9)  == "09:00 – 10:00"
    assert _hour_label(23) == "23:00 – 00:00"
