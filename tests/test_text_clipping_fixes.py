"""
Text-clipping / overlap fixes (2026-07-25, operator-reported).

Two display bugs, both "the value is wider than the box QPainter was
given, so drawText clipped it mid-glyph":

  REPORT — core/reports/spot_play_report.py `_draw_metadata` boxed EVERY
    value at 200px. Single-column rows ("Spot Title", "Client",
    "Start & Expire") therefore lost their tails even though ~160px of
    page sat empty to the right, and the right-hand "Media Shop" value
    had only 100px for a station name that needs ~122-148px.

  GRID — ui/auto_schedule.py `_paint_cell` painted the clock name CENTRED
    across the whole cell and the "AUTO" watermark right-aligned in the
    SAME rect, so the two overlapped; and a name wider than the 120px
    cell was clipped on BOTH sides ("AUTO · Pool 07 + Testing 01" →
    "UTO · Pool 07 + Testing 0").

These tests pin the geometry contracts rather than pixels: the name rect
must exclude the tag, and long strings must come back ELIDED (ending in
an ellipsis) instead of silently truncated.
"""

from __future__ import annotations

from datetime import date

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QFontMetricsF

from core.reports import spot_play_report as spr
from ui.auto_schedule import _ScheduleGrid, _cell_rect


# ── Report metadata block ───────────────────────────────────────────────


def test_single_column_value_box_reaches_right_margin(qapp):
    """A one-column row must be allowed the full page width."""
    val_x = 156
    full_w = spr.PAGE_W - spr.MARGIN_X - val_x
    # The old hard-coded box was 200px; the fix must be materially wider.
    assert full_w > 200
    assert val_x + full_w == spr.PAGE_W - spr.MARGIN_X   # flush to margin


def test_start_expire_string_fits_the_full_width_box(qapp):
    """The exact value from the operator's report must not need eliding."""
    text = (f"{spr._fmt_long(date(2026, 7, 4))} > "
            f"{spr._fmt_long(date(2026, 8, 3))}")
    assert text == "Saturday, July 04, 2026 > Monday, August 03, 2026"
    fm = QFontMetricsF(
        spr._font(spr.INTER_FAMILY, 10, QFont.Weight.Medium, 0.0))
    needed = fm.horizontalAdvance(text)
    full_w = spr.PAGE_W - spr.MARGIN_X - 156
    assert needed > 200, "regression guard: this is why 200px clipped"
    assert needed <= full_w, (
        f"Start & Expire needs {needed:.0f}px but the box is {full_w}px")


def test_media_shop_box_fits_a_real_station_name(qapp):
    """'Radio Rajasthan 90.8' (and the longer KISS branding) must fit."""
    fm = QFontMetricsF(
        spr._font(spr.INTER_FAMILY, 10, QFont.Weight.Medium, 0.0))
    shop_w = 170        # keep in step with _draw_metadata's SHOP_VAL_W
    for name in ("Radio Rajasthan 90.8", "KISS FM 91.5 / FCP Radio"):
        assert fm.horizontalAdvance(name) <= shop_w, (
            f"{name!r} needs {fm.horizontalAdvance(name):.0f}px, "
            f"box is {shop_w}px")
    # The old box was 100px — this is the regression we are guarding.
    assert fm.horizontalAdvance("Radio Rajasthan 90.8") > 100


def test_painter_text_elides_instead_of_clipping(qapp, tmp_path):
    """_Painter.text(elide=True) shortens with an ellipsis; the default
    stays byte-identical (no elide) for every existing caller."""
    from PyQt6.QtGui import QPdfWriter, QPainter, QPageSize, QPageLayout
    from PyQt6.QtCore import QMarginsF

    writer = QPdfWriter(str(tmp_path / "probe.pdf"))
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    writer.setPageMargins(QMarginsF(0, 0, 0, 0),
                          QPageLayout.Unit.Point)
    p = QPainter(writer)
    try:
        pp = spr._Painter(p)
        drawn: list[str] = []
        orig = p.drawText

        def _capture(rect, flags, s):
            drawn.append(s)
            return orig(rect, flags, s)

        p.drawText = _capture
        long_s = "Saturday, July 04, 2026 > Monday, August 03, 2026"
        pp.text(0, 0, 60, 14, long_s, elide=True)
        assert drawn[-1] != long_s
        assert drawn[-1].endswith("…")
        pp.text(0, 0, 60, 14, long_s)          # default → untouched
        assert drawn[-1] == long_s
    finally:
        p.end()


# ── Spots List wrapping ─────────────────────────────────────────────────


def _fake_files(n: int, name: str = "D4_TEST.mp3") -> list[dict]:
    return [{"filename": name, "duration_ms": 10000} for _ in range(n)]


def test_spots_list_keeps_every_file(qapp):
    """The operator reads this block as the contract's file manifest —
    a campaign's files must ALL appear, however many there are."""
    for n in (1, 2, 3, 6, 20):
        lines = spr._spots_list_lines(_fake_files(n))
        joined = " ".join(lines)
        for i in range(1, n + 1):
            assert f"({i})" in joined, f"entry {i} of {n} vanished"


def test_spots_list_wraps_instead_of_clipping(qapp):
    """6 files need ~850px in a 399px column → must become >1 line, and
    no single line may exceed the printable width."""
    lines = spr._spots_list_lines(_fake_files(6))
    assert len(lines) > 1
    fm = QFontMetricsF(
        spr._font(spr.MONO_FAMILY, 10, QFont.Weight.Normal, 0.0))
    for ln in lines:
        assert fm.horizontalAdvance(ln) <= spr.SPOTS_LIST_W + 0.5, ln


def test_spots_list_single_file_stays_one_line(qapp):
    """No behaviour change for the common case."""
    assert len(spr._spots_list_lines(_fake_files(1))) == 1


def test_spots_list_empty_campaign_placeholder(qapp):
    lines = spr._spots_list_lines([])
    assert len(lines) == 1
    assert "no audio files" in lines[0]


def test_wrap_entries_never_drops_an_oversized_entry(qapp):
    """An entry wider than a whole line gets its own line rather than
    being silently discarded."""
    fm = QFontMetricsF(
        spr._font(spr.MONO_FAMILY, 10, QFont.Weight.Normal, 0.0))
    huge = "(1) " + "x" * 400 + " - 10sec"
    lines = spr._wrap_entries([huge, "(2) short.mp3 - 5sec"], fm, 200)
    assert any(huge in ln for ln in lines)
    assert any("short.mp3" in ln for ln in lines)


def test_page1_grid_start_accounts_for_wrapped_spots_list(qapp):
    """Pagination must use the SAME line count the renderer paints, or
    page 1 over-fills and its last day-row runs into the footer."""
    one = len(spr._spots_list_lines(_fake_files(1)))
    many = len(spr._spots_list_lines(_fake_files(6)))
    assert many > one
    start_one = 290 + max(0, one - 1) * spr.ROW_LINE_H
    start_many = 290 + max(0, many - 1) * spr.ROW_LINE_H
    assert start_many > start_one
    # …and the grid must still have usable room on page 1.
    assert start_many < spr.PAGE_LIMIT_Y - 110


# ── Auto Schedule grid cell ─────────────────────────────────────────────


@pytest.fixture
def grid(qapp):
    g = _ScheduleGrid()
    g.set_clocks([
        {"id": 1, "name": "AUTO · Pool 06"},
        {"id": 2, "name": "AUTO · Pool 07 + Testing 01"},
    ])
    yield g
    g.deleteLater()


def test_auto_tag_width_is_cached(grid):
    """Perf invariant: metrics computed once in __init__, not per cell
    (_paint_cell runs 168× per repaint)."""
    assert grid._auto_tag_w > 0
    fm = QFontMetricsF(grid._font_auto)
    assert grid._auto_tag_w == pytest.approx(
        fm.horizontalAdvance(_ScheduleGrid._AUTO_TAG))


def test_name_rect_excludes_the_auto_tag(grid):
    """The clock-name rect must stop before the right-aligned tag —
    this is what stops the two painting on top of each other."""
    rf = _cell_rect(0, 0)
    pad = _ScheduleGrid._CELL_TEXT_PAD
    plain_right = rf.right() - pad
    auto_right = plain_right - (grid._auto_tag_w
                                + _ScheduleGrid._AUTO_TAG_GAP)
    # The AUTO variant must give up real estate…
    assert auto_right < plain_right
    # …at least the tag's own width.
    assert plain_right - auto_right >= grid._auto_tag_w


def test_long_name_is_elided_not_clipped(grid):
    """A name wider than the cell comes back with an ellipsis, so it can
    never be sliced mid-glyph on both sides by the centred draw."""
    from ui.auto_schedule import CELL_W
    name = "AUTO · Pool 07 + Testing 01"
    fm = QFontMetricsF(grid._font_cell)
    avail = CELL_W - 2 * _ScheduleGrid._CELL_TEXT_PAD - (
        grid._auto_tag_w + _ScheduleGrid._AUTO_TAG_GAP)
    assert fm.horizontalAdvance(name) > avail, "regression guard"
    elided = fm.elidedText(name, Qt.TextElideMode.ElideRight, avail)
    assert elided.endswith("…")
    assert fm.horizontalAdvance(elided) <= avail


def test_short_name_is_not_elided(grid):
    """Names that fit must render verbatim — no stray ellipsis."""
    from ui.auto_schedule import CELL_W
    name = "P1"
    fm = QFontMetricsF(grid._font_cell)
    avail = CELL_W - 2 * _ScheduleGrid._CELL_TEXT_PAD
    assert fm.horizontalAdvance(name) <= avail
    assert fm.elidedText(name, Qt.TextElideMode.ElideRight, avail) == name


def test_grid_paints_without_error_for_long_and_auto_cells(grid, qapp):
    """End-to-end paint smoke — the real _paint_cell path with both a
    long AUTO name and a short plain one."""
    from PyQt6.QtGui import QPixmap, QPainter
    grid.set_grid({(0, 0): 2, (0, 1): 1}, auto_cells={(0, 0)})
    pm = QPixmap(grid.size())
    pm.fill()
    p = QPainter(pm)
    try:
        grid._paint_cell(p, 0, 0)      # long name + AUTO tag
        grid._paint_cell(p, 0, 1)      # plain
        grid._paint_cell(p, 3, 5)      # unassigned cell
    finally:
        p.end()
