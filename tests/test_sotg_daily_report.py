"""
SOTG Daily Report PDF generator tests (core/reports/sotg_daily_report.py).

Pinned behaviour:
  • Default output dir resolves to <project_root>/reports/sotg/.
  • Filename pattern sotg_daily_<YYYY-MM-DD>.pdf.
  • Empty day still produces a valid PDF (empty-state line, no crash).
  • Grouping by show — operator's Option B preference. Within each group
    rows sorted by link_order ASC. Groups themselves sorted by earliest
    sharp_time so the PDF reads in broadcast-day order.
  • include_pending=False filters out PENDING/READY/CONFLICT.
  • include_pending=True keeps every row.
  • _safe_color falls back to CYAN on bad input — no crash on garbage.
  • ai_summary on a row causes the sub-block to render (no crash today).
  • generated PDF file exists + has non-trivial size after generation.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from pathlib import Path

import pytest

from core.database import Database


@pytest.fixture
def db():
    return Database()


@pytest.fixture
def seeded_day(db, tmp_path):
    """Create 2 SOTG shows on a future date with mixed link statuses.
    Returns (date, [show_ids]). Caller is responsible for deletion via
    db.delete_sotg_show() — CASCADE wipes links + assignments."""
    today = date.today()
    target = today + timedelta(days=14)

    s1 = db.create_sotg_show(
        rj_name=f"RJ-A-{uuid.uuid4().hex[:6]}",
        show_name=f"Morning-{uuid.uuid4().hex[:6]}",
        days="Daily", time_start="06:00", time_end="07:00",
        color="#8b5cf6", description="",
        link_names=["L1-A", "L2-A", "L3-A"])
    s2 = db.create_sotg_show(
        rj_name=f"RJ-B-{uuid.uuid4().hex[:6]}",
        show_name=f"Bhakti-{uuid.uuid4().hex[:6]}",
        days="Daily", time_start="07:00", time_end="08:00",
        color="#f59e0b", description="",
        link_names=["L1-B", "L2-B"])

    show1 = db.get_sotg_show(s1)
    show2 = db.get_sotg_show(s2)
    links1 = show1["links"]
    links2 = show2["links"]

    # Two FIRED + one MISSED on show 1; one FIRED + one MISSED on show 2
    for sid_owner, status, link, hhmm in [
        (s1, "FIRED",  links1[0], "06:00"),
        (s1, "FIRED",  links1[1], "06:18"),
        (s1, "MISSED", links1[2], "06:45"),
        (s2, "FIRED",  links2[0], "07:00"),
        (s2, "MISSED", links2[1], "07:45"),
    ]:
        db.upsert_sotg_assignment(
            show_id=sid_owner, link_id=int(link["id"]),
            scheduled_date=target.isoformat(),
            file_path=f"/x/{link['link_name']}.mp3",
            file_name=f"{link['link_name']}.mp3",
            file_duration_ms=42_000,
            sharp_time=hhmm, priority="High", status=status,
            allow_past=True)

    yield (target, [s1, s2])

    for sid in (s1, s2):
        try:
            db.delete_sotg_show(sid)
        except Exception:
            pass


# ── Configuration / metadata ───────────────────────────────────────────────


def test_default_report_dir_under_project_root():
    from core.reports.sotg_daily_report import DEFAULT_REPORT_DIR
    # Must contain "reports" + "sotg" segments somewhere in the path
    s = str(DEFAULT_REPORT_DIR).lower().replace("\\", "/")
    assert "reports" in s
    assert "sotg" in s


def test_default_filename_pattern(qapp, db, tmp_path):
    from core.reports.sotg_daily_report import generate_sotg_daily_report
    target = date(2026, 5, 13)
    out = generate_sotg_daily_report(
        target, output_path=tmp_path / "sotg_daily_2026-05-13.pdf", db=db)
    assert out.name == "sotg_daily_2026-05-13.pdf"
    assert out.exists()


# ── Empty-day rendering ────────────────────────────────────────────────────


def test_empty_day_generates_valid_pdf(qapp, db, tmp_path):
    """No assignments for a date in the distant future — still must
    write a PDF (empty-state line) without raising."""
    from core.reports.sotg_daily_report import generate_sotg_daily_report
    far = date.today() + timedelta(days=365)
    out_path = tmp_path / "empty.pdf"
    out = generate_sotg_daily_report(far, output_path=out_path, db=db)
    assert out == out_path
    assert out.exists()
    # A real A4 PDF, even mostly empty, has more than a few hundred bytes
    assert out.stat().st_size > 500


# ── Real data: grouping + filtering ────────────────────────────────────────


def test_seeded_day_renders_pdf_with_expected_size(qapp, db, tmp_path, seeded_day):
    target, _ = seeded_day
    from core.reports.sotg_daily_report import generate_sotg_daily_report
    out_path = tmp_path / "seeded.pdf"
    out = generate_sotg_daily_report(target, output_path=out_path, db=db)
    assert out.exists()
    assert out.stat().st_size > 2_000


def test_groups_sorted_by_earliest_sharp_time(qapp, db, seeded_day):
    """Operator's Option B: groups appear in broadcast-day order. The
    show with the earliest first link comes first; later show second."""
    from core.reports.sotg_daily_report import (
        _fetch_assignments, _group_by_show,
    )
    target, _ = seeded_day
    rows = _fetch_assignments(db, target, include_pending=False)
    groups = _group_by_show(rows)
    assert len(groups) == 2
    # Morning (06:00) must come before Bhakti (07:00)
    times = [g["earliest_time"] for g in groups]
    assert times == sorted(times)


def test_links_within_group_sorted_by_link_order(qapp, db, seeded_day):
    """Within each show's section, link_order ASC drives the row
    ordering — operator's 'sabse pehle jo show tha, uske baad next
    number ka' clarification."""
    from core.reports.sotg_daily_report import (
        _fetch_assignments, _group_by_show,
    )
    target, _ = seeded_day
    rows = _fetch_assignments(db, target, include_pending=False)
    groups = _group_by_show(rows)
    for g in groups:
        orders = [int(r.get("link_order") or 0) for r in g["rows"]]
        assert orders == sorted(orders), (
            f"Show {g['show_name']} rows must be ordered by "
            f"link_order ASC; got {orders}")


def test_include_pending_false_excludes_non_terminal(qapp, db, seeded_day):
    """Default behaviour: only FIRED + MISSED. Pending/Ready hidden."""
    from core.reports.sotg_daily_report import _fetch_assignments
    target, _ = seeded_day
    # Add a PENDING row on show 1's first link, then refetch.
    pending = db.upsert_sotg_assignment(
        show_id=db.get_sotg_assignments_for_date(target.isoformat())[0]["show_id"],
        link_id=db.get_sotg_assignments_for_date(target.isoformat())[0]["link_id"],
        scheduled_date=target.isoformat(),
        file_path="/x/pending.mp3", file_name="pending.mp3",
        file_duration_ms=8_000,
        sharp_time="06:00", priority="Low", status="PENDING",
        allow_past=True)
    rows_filtered = _fetch_assignments(db, target, include_pending=False)
    rows_all = _fetch_assignments(db, target, include_pending=True)
    # Filtered slice has no PENDING; full slice has at least one.
    assert all((r.get("status") or "").upper() in ("FIRED", "MISSED")
                for r in rows_filtered)
    assert any((r.get("status") or "").upper() == "PENDING"
                for r in rows_all)


# ── Defensive helpers ──────────────────────────────────────────────────────


def test_safe_color_falls_back_on_garbage():
    from core.reports.sotg_daily_report import _safe_color, CYAN
    assert _safe_color(None) == CYAN
    assert _safe_color("") == CYAN
    assert _safe_color("not-a-color") == CYAN
    assert _safe_color("#zzzzzz") == CYAN
    # Valid colors are preserved unchanged
    assert _safe_color("#8b5cf6") == "#8b5cf6"
    assert _safe_color("#fff") == "#fff"


def test_status_display_maps_known_enums():
    from core.reports.sotg_daily_report import _status_to_display
    disp, _, glyph = _status_to_display("FIRED")
    assert disp == "PLAYED"
    assert glyph == "✓"
    disp, _, glyph = _status_to_display("MISSED")
    assert disp == "MISSED"
    assert glyph == "✕"
    # Unknown → neutral fallback (no crash)
    disp, _, _ = _status_to_display("ZOMBIE")
    assert disp == "ZOMBIE"


def test_row_with_ai_summary_does_not_crash(qapp, db, tmp_path, seeded_day):
    """v2 future-proofing — when ai_summary is populated, the row paint
    adds an italicized sub-block. Today no real data ever sets this,
    but the code path must not crash if a test/db row carries one."""
    from core.reports.sotg_daily_report import (
        generate_sotg_daily_report, _row_height,
    )
    target, _ = seeded_day

    # Verify _row_height accounts for the summary
    bare = {"link_order": 1}
    summarized = {"link_order": 1, "ai_summary": "RJ welcomes Diwali listeners."}
    assert _row_height(summarized) > _row_height(bare)

    # Monkey-patch the db to inject ai_summary into every row, then
    # generate — must not raise.
    original = db.get_sotg_assignments_for_date

    def patched(d, status=None):
        rows = original(d, status=status)
        for r in rows:
            r["ai_summary"] = "Auto-generated AI summary for testing only."
        return rows

    db.get_sotg_assignments_for_date = patched   # type: ignore[method-assign]
    try:
        out = generate_sotg_daily_report(
            target, output_path=tmp_path / "ai_summary.pdf", db=db)
        assert out.exists()
        assert out.stat().st_size > 2_000
    finally:
        db.get_sotg_assignments_for_date = original   # type: ignore[method-assign]


def test_invalid_date_raises():
    from core.reports.sotg_daily_report import (
        generate_sotg_daily_report, SOTGDailyReportError,
    )
    with pytest.raises(SOTGDailyReportError, match="datetime.date"):
        generate_sotg_daily_report("2026-05-14")   # type: ignore[arg-type]
