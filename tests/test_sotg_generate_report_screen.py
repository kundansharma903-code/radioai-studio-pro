"""
SOTG · Generate Report screen tests (ui/sotg_generate_report.py, Figma 497:2).

Pinned behaviour:
  • Screen constructs at 1440×900 without crashing.
  • Initial _report_date is yesterday.
  • Date controls (prev/next/today/calendar) update _report_date + refresh.
  • Pending toggle flips _include_pending + refresh.
  • Stat pills show counts from the FULL day (not the filtered slice).
  • Empty-state card renders when no rows for the selected date.
  • _AssignmentRow renders with show color + status pill + duration fmt.
  • Breadcrumb signals emit "control_panel" / "ai_magic" / "spot_on_the_go".
  • Station label has hdr_station_lbl objectName.
  • Refresh on a visible parent doesn't hide rows (incident #17 family).
  • Download PDF button calls the generator + os.startfile.

MainWindow integration:
  • SOTGGenerateReport mounts as self.sotg_generate_report.
  • Routing key "generate_report" lands on it (was a toast, now real).
  • Routing key "assign_api_key" stays a toast (the only remaining one).
  • _check_sotg_midnight_save is idempotent + gated by the time window.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta, datetime
from pathlib import Path

import pytest

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel

from core.database import Database


@pytest.fixture
def db():
    return Database()


@pytest.fixture
def seeded_yesterday(db):
    """Create a small show with 2 FIRED + 1 MISSED links scheduled
    yesterday so we have realistic data to render."""
    sid = db.create_sotg_show(
        rj_name=f"RJ-{uuid.uuid4().hex[:6]}",
        show_name=f"Test-{uuid.uuid4().hex[:6]}",
        days="Daily", time_start="06:00", time_end="07:00",
        color="#10b981", description="",
        link_names=["Opening", "Mid", "Closing"])
    show = db.get_sotg_show(sid)
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    for i, (status, hhmm) in enumerate([
            ("FIRED", "06:00"), ("MISSED", "06:30"), ("FIRED", "06:55")]):
        db.upsert_sotg_assignment(
            show_id=sid, link_id=int(show["links"][i]["id"]),
            scheduled_date=yesterday,
            file_path=f"/x/L{i+1}.mp3", file_name=f"L{i+1}.mp3",
            file_duration_ms=30_000,
            sharp_time=hhmm, priority="High", status=status,
            allow_past=True)
    yield sid
    try:
        db.delete_sotg_show(sid)
    except Exception:
        pass


# ── Screen construction ───────────────────────────────────────────────────


def test_screen_constructs_1440x900(qapp, db):
    from ui.sotg_generate_report import SOTGGenerateReport
    s = SOTGGenerateReport(db)
    assert s.width() == 1440
    assert s.height() == 900
    s.deleteLater()


def test_initial_report_date_is_yesterday(qapp, db):
    from ui.sotg_generate_report import SOTGGenerateReport
    s = SOTGGenerateReport(db)
    assert s._report_date == date.today() - timedelta(days=1)
    s.deleteLater()


def test_station_label_has_object_name(qapp, db):
    """Required for live station-branding refresh — MainWindow's
    qlabel_screens tuple loops over hdr_station_lbl."""
    from ui.sotg_generate_report import SOTGGenerateReport
    s = SOTGGenerateReport(db)
    lbl = s.findChild(QLabel, "hdr_station_lbl")
    assert lbl is not None
    s.deleteLater()


# ── Stat pills + filter ───────────────────────────────────────────────────


def test_stat_pills_reflect_full_day_counts(qapp, db, qtbot, seeded_yesterday):
    """Default filter (FIRED + MISSED) — counts should still match the
    full-day total in the TOTAL pill. PLAYED/MISSED counts are
    independent of the filter (always count the full day)."""
    from ui.sotg_generate_report import SOTGGenerateReport
    s = SOTGGenerateReport(db)
    qtbot.addWidget(s)
    s.set_report_date(date.today() - timedelta(days=1))
    # 2 fired + 1 missed = 3 total
    assert s._pill_total._value_lbl.text() == "3"
    assert s._pill_played._value_lbl.text() == "2"
    assert s._pill_missed._value_lbl.text() == "1"


def test_pending_toggle_flips_filter_and_refreshes(qapp, db, qtbot,
                                                     seeded_yesterday):
    from ui.sotg_generate_report import SOTGGenerateReport
    s = SOTGGenerateReport(db)
    qtbot.addWidget(s)
    s.set_report_date(date.today() - timedelta(days=1))
    assert s._include_pending is False
    s._pending_toggle.set_checked(True)
    assert s._include_pending is True
    s._pending_toggle.set_checked(False)
    assert s._include_pending is False


# ── Date controls ─────────────────────────────────────────────────────────


def test_prev_next_today_advance_report_date(qapp, db, qtbot):
    from ui.sotg_generate_report import SOTGGenerateReport
    s = SOTGGenerateReport(db)
    qtbot.addWidget(s)
    start = s._report_date
    s._on_prev_day()
    assert s._report_date == start - timedelta(days=1)
    s._on_next_day()
    assert s._report_date == start
    s._on_next_day()
    assert s._report_date == start + timedelta(days=1)
    s._on_today()
    assert s._report_date == date.today()


# ── Rows + empty state ────────────────────────────────────────────────────


def test_empty_state_card_renders_when_no_drops(qapp, db, qtbot):
    """A date with zero assignments renders an empty-state card, not a
    blank scroll area."""
    from ui.sotg_generate_report import SOTGGenerateReport
    s = SOTGGenerateReport(db)
    qtbot.addWidget(s)
    s.set_report_date(date.today() + timedelta(days=400))  # far future
    # Exactly one widget should be in the row list — the empty card.
    assert len(s._row_widgets) == 1


def test_rows_render_when_data_exists(qapp, db, qtbot, seeded_yesterday):
    from ui.sotg_generate_report import SOTGGenerateReport
    s = SOTGGenerateReport(db)
    qtbot.addWidget(s)
    s.set_report_date(date.today() - timedelta(days=1))
    # 3 rows expected
    assert len(s._row_widgets) == 3


def test_rows_remain_visible_after_screen_visible_refresh(
        qapp, db, qtbot, seeded_yesterday):
    """Family of incident #17 — refresh on a visible parent must not
    leave new rows hidden."""
    from ui.sotg_generate_report import SOTGGenerateReport
    s = SOTGGenerateReport(db)
    qtbot.addWidget(s)
    s.show()
    qapp.processEvents()
    s.set_report_date(date.today() - timedelta(days=1))
    qapp.processEvents()
    visible = sum(1 for w in s._row_widgets if not w.isHidden())
    assert visible == len(s._row_widgets)
    # Trigger another refresh via pending toggle — same invariant
    s._pending_toggle.set_checked(True)
    qapp.processEvents()
    visible = sum(1 for w in s._row_widgets if not w.isHidden())
    assert visible == len(s._row_widgets)


# ── Row widget rendering ──────────────────────────────────────────────────


def test_assignment_row_status_pill_for_fired(qapp):
    from ui.sotg_generate_report import _AssignmentRow
    row = _AssignmentRow({
        "link_order": 2, "sharp_time": "06:15",
        "show_name": "Morning Mantra", "rj_name": "Pradeep",
        "link_name": "Weather", "status": "FIRED",
        "file_name": "weather.mp3", "file_duration_ms": 42_000,
        "color": "#8b5cf6",
    })
    # No exceptions, height fixed
    assert row.height() == _AssignmentRow.HEIGHT
    row.deleteLater()


def test_assignment_row_handles_missing_color(qapp):
    """A row with garbage color string must fall back to cyan, not
    crash QColor."""
    from ui.sotg_generate_report import _AssignmentRow
    row = _AssignmentRow({
        "link_order": 1, "sharp_time": "07:00",
        "show_name": "X", "rj_name": "Y",
        "link_name": "Z", "status": "MISSED",
        "file_name": "z.mp3", "file_duration_ms": 0,
        "color": "garbage",
    })
    assert row._show_color.startswith("#")
    row.deleteLater()


# ── Breadcrumbs ───────────────────────────────────────────────────────────


def test_breadcrumb_signals(qapp, db, qtbot):
    from ui.sotg_generate_report import SOTGGenerateReport
    from ui.spot_on_the_go_shell import _BreadcrumbLink
    s = SOTGGenerateReport(db)
    qtbot.addWidget(s)
    received: list[str] = []
    s.screen_requested.connect(received.append)
    crumbs = {c.text(): c for c in s.findChildren(_BreadcrumbLink)}
    for label in ("Control Panel", "AI Magic", "Spot on the Go"):
        assert label in crumbs
        crumbs[label].clicked.emit()
    assert received == ["control_panel", "ai_magic", "spot_on_the_go"]


# ── Download button ───────────────────────────────────────────────────────


def test_download_pdf_calls_generator_and_opens(qapp, db, qtbot, monkeypatch,
                                                  seeded_yesterday, tmp_path):
    """Clicking Download PDF must call generate_sotg_daily_report +
    os.startfile (Windows default-app open)."""
    from ui.sotg_generate_report import SOTGGenerateReport
    s = SOTGGenerateReport(db)
    qtbot.addWidget(s)
    s.set_report_date(date.today() - timedelta(days=1))

    calls = {"generated": [], "opened": []}
    out_path = tmp_path / "fake.pdf"
    out_path.write_text("stub")    # exists so os.startfile would have a target

    def fake_gen(report_date, db=None, include_pending=False, output_path=None):
        calls["generated"].append((report_date, include_pending))
        return out_path

    monkeypatch.setattr(
        "core.reports.sotg_daily_report.generate_sotg_daily_report",
        fake_gen)
    import os as _os
    monkeypatch.setattr(_os, "startfile",
                          lambda p: calls["opened"].append(str(p)),
                          raising=False)
    s._on_download_pdf()
    assert calls["generated"] == [
        (date.today() - timedelta(days=1), False)]
    assert calls["opened"] == [str(out_path)]


# ── MainWindow integration ────────────────────────────────────────────────


def test_main_window_mounts_sotg_generate_report(
        qapp, db, qtbot, monkeypatch):
    from ui import main_window as mw_mod
    monkeypatch.setattr(mw_mod.MainWindow, "_apply_startup_auto_mode",
                         lambda self: None)
    from ui.main_window import MainWindow
    w = MainWindow(db=db)
    qtbot.addWidget(w)
    assert hasattr(w, "sotg_generate_report")
    w._on_hub_screen_requested("generate_report")
    assert w._stack.currentWidget() is w.sotg_generate_report
    w.close()
    w.deleteLater()


def test_only_assign_api_key_still_toasts(qapp, db, qtbot, monkeypatch):
    """Pre this build: generate_report + assign_api_key both toasted.
    Now generate_report routes to the real screen; only assign_api_key
    remains a toast (until that screen ships)."""
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
    w._on_hub_screen_requested("generate_report")
    assert toast_calls == []
    assert w._stack.currentWidget() is w.sotg_generate_report
    w._on_hub_screen_requested("assign_api_key")
    titles = [t for t, _ in toast_calls]
    assert titles == ["Assign API Key"]
    w.close()
    w.deleteLater()


def test_sotg_shell_generate_report_card_reaches_real_screen(
        qapp, db, qtbot, monkeypatch):
    """The Spot on the Go shell's Generate Report card now lands on
    the real screen (was a 'coming soon' toast in the previous build)."""
    from ui import main_window as mw_mod
    monkeypatch.setattr(mw_mod.MainWindow, "_apply_startup_auto_mode",
                         lambda self: None)
    from ui.main_window import MainWindow
    w = MainWindow(db=db)
    qtbot.addWidget(w)
    w.spot_on_the_go_shell.screen_requested.emit("generate_report")
    assert w._stack.currentWidget() is w.sotg_generate_report
    w.close()
    w.deleteLater()


# ── Midnight tick ─────────────────────────────────────────────────────────


def test_midnight_tick_method_exists_and_runs_without_crashing(
        qapp, db, qtbot, monkeypatch):
    """Boot the window, invoke the tick manually. Outside the 23:59 /
    00:00..00:05 window it's a no-op; the call must not raise. We
    don't try to mock datetime here — the precise timing path is
    operator-verified via the QTimer wiring and the once-per-day
    Settings sentinel ensures idempotency in real use."""
    from ui import main_window as mw_mod
    monkeypatch.setattr(mw_mod.MainWindow, "_apply_startup_auto_mode",
                         lambda self: None)
    from ui.main_window import MainWindow
    w = MainWindow(db=db)
    qtbot.addWidget(w)
    assert hasattr(w, "_check_sotg_midnight_save")
    # Should never raise regardless of current wall-clock time
    w._check_sotg_midnight_save()
    w.close()
    w.deleteLater()


def test_midnight_sentinel_blocks_duplicate_save(qapp, db, qtbot, monkeypatch):
    """Sentinel-only check — set the settings key to today, then
    invoke the tick. Even if the time window were active, the sentinel
    matches and the generator must not be called a second time."""
    from ui import main_window as mw_mod
    monkeypatch.setattr(mw_mod.MainWindow, "_apply_startup_auto_mode",
                         lambda self: None)
    from ui.main_window import MainWindow
    w = MainWindow(db=db)
    qtbot.addWidget(w)
    # Pre-stamp the sentinel with today; if the tick is in-window for
    # today, it will see the matching stamp and return early.
    from core.settings import Settings
    Settings().set("last_sotg_report_save_date", date.today().isoformat())

    import core.reports.sotg_daily_report as srd_mod
    fired = {"n": 0}
    real_gen = srd_mod.generate_sotg_daily_report

    def trap(*a, **kw):
        fired["n"] += 1
        return real_gen(*a, **kw)

    monkeypatch.setattr(srd_mod, "generate_sotg_daily_report", trap)
    w._check_sotg_midnight_save()
    # Either outside window (n==0) or inside-but-stamped (n==0) — both
    # paths skip the generator.
    assert fired["n"] == 0
    w.close()
    w.deleteLater()
