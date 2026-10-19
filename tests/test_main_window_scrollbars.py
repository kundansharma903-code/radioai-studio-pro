"""
MainWindow canvas scrollbars on small displays (QA ⚠13, 2026-10-18).

At 1366×768 (maximized window 1338×691) the 1920×1080 design canvas
does not fit, and the transport bar and right-hand panels are reached by
scrolling. The bars were 10 px with a 10 %-white handle on #06080f,
effectively invisible, so the operator saw the screen as "clipped".

This builds the same widget tree MainWindow uses (a QScrollArea named
mwScroll, not resizable, AsNeeded bars, holding a fixed 1920×1080
canvas, styled with MW_SCROLL_QSS) WITHOUT constructing MainWindow.
MainWindow's 150 ms startup auto-mode timer starts real playout.
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QScrollArea, QWidget

from core.constants import WINDOW_H, WINDOW_W
from ui.main_window import MW_SCROLL_QSS


@pytest.fixture
def canvas_scroll(qtbot):
    scroll = QScrollArea()
    scroll.setObjectName("mwScroll")
    scroll.setWidgetResizable(False)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setStyleSheet(MW_SCROLL_QSS)
    canvas = QWidget()
    canvas.setFixedSize(WINDOW_W, WINDOW_H)
    scroll.setWidget(canvas)
    qtbot.addWidget(scroll)
    scroll.show()
    return scroll


def _settle(qtbot, scroll, w, h):
    scroll.resize(w, h)
    qtbot.waitUntil(lambda: scroll.viewport().width() > 0, timeout=2000)
    qtbot.wait(50)


def test_design_canvas_is_1920x1080():
    assert (WINDOW_W, WINDOW_H) == (1920, 1080)


def test_small_display_shows_both_bars_with_room_to_scroll(qtbot,
                                                          canvas_scroll):
    _settle(qtbot, canvas_scroll, 1338, 691)
    v = canvas_scroll.verticalScrollBar()
    h = canvas_scroll.horizontalScrollBar()
    assert v.isVisible() and h.isVisible()
    assert v.maximum() > 0 and h.maximum() > 0
    # The bottom transport (y 1000-1080) and right panels can be reached.
    assert v.maximum() + canvas_scroll.viewport().height() >= WINDOW_H
    assert h.maximum() + canvas_scroll.viewport().width() >= WINDOW_W


def test_bars_are_14px(qtbot, canvas_scroll):
    _settle(qtbot, canvas_scroll, 1338, 691)
    assert canvas_scroll.verticalScrollBar().width() == 14
    assert canvas_scroll.horizontalScrollBar().height() == 14


def test_full_hd_needs_no_bars(qtbot, canvas_scroll):
    """On a display that holds the whole canvas (a full-HD window) the
    bars stay hidden, so 1920×1080 is visually unchanged. The window is
    grown slightly past the canvas so the platform's own frame and
    margins can't trigger a bar."""
    _settle(qtbot, canvas_scroll, WINDOW_W + 40, WINDOW_H + 40)
    assert canvas_scroll.viewport().width() >= WINDOW_W
    assert canvas_scroll.viewport().height() >= WINDOW_H
    assert not canvas_scroll.verticalScrollBar().isVisible()
    assert not canvas_scroll.horizontalScrollBar().isVisible()


def test_idle_handle_is_text_sec_not_near_invisible():
    """The idle handle must be solid TEXT_SEC (#8891b8, about 6.6:1 on
    #06080f), not the old rgba(255,255,255,0.10)."""
    assert "rgba(255,255,255,0.10)" not in MW_SCROLL_QSS
    for orient in ("vertical", "horizontal"):
        rule = MW_SCROLL_QSS.split(
            f"QScrollBar::handle:{orient} {{")[1].split("}")[0]
        assert "#8891b8" in rule, rule
