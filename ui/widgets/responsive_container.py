"""
ResponsiveContainer — fit-to-window wrapper for fixed-canvas screens.

Wraps any QWidget authored at a fixed design size (e.g. 1920×1080)
inside a QGraphicsScene + QGraphicsView so it auto-fits the available
window space while preserving aspect ratio. Solves the "Studio cuts
off on a 1366×768 monitor" problem without requiring every screen
widget to support reflow / responsive layouts.

Designed for premium broadcast software where:
  - Operators expect Jazler-style fit-to-screen (NOT scrolling)
  - Native Qt widgets in the wrapped screen still receive mouse + key
    events transparently (QGraphicsProxyWidget handles event routing)
  - QSS, QPainter custom widgets, and QGraphicsDropShadowEffect all
    keep working — they're rasterised by Qt then composited by the view

Phase 2 pilot (responsive-pilot-studio branch): only Studio gets
this wrapper. Other screens stay direct-mounted under the existing
QScrollArea path. Part 2 will propagate the wrapper after the pilot
is verified on Kavish's 1366×768 hardware.

Usage::

    from ui.widgets.responsive_container import ResponsiveContainer

    studio = Studio(db=..., engine=..., scheduler=..., instant_jingle_engine=...)
    container = ResponsiveContainer(studio,
                                    design_width=1920,
                                    design_height=1080)
    self._stack.addWidget(container)

The wrapped widget is still accessible via container.inner_widget()
or by holding a reference (e.g. self._studio = studio) before wrapping
— signals / slots / direct method calls keep working unchanged.
"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QGraphicsView,
    QGraphicsScene,
    QGraphicsProxyWidget,
    QWidget,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPainter


class ResponsiveContainer(QGraphicsView):
    """Wrap a fixed-size QWidget so it auto-fits the available viewport
    while preserving aspect ratio.

    The inner widget is held at its native ``design_width × design_height``
    via ``setFixedSize`` so its internal geometry / layout / cached
    gradients stay correct. The QGraphicsView scales the rendered
    output to fill the window without distorting content.
    """

    def __init__(self, inner_widget: QWidget,
                 design_width: int = 1920, design_height: int = 1080,
                 parent=None):
        super().__init__(parent)
        self._design_width = int(design_width)
        self._design_height = int(design_height)
        self._inner = inner_widget

        # Force the inner widget to its native design size so all of
        # its internal coordinates / layouts / cached geometry stay
        # exactly as the screen author intended.
        self._inner.setFixedSize(self._design_width, self._design_height)

        # Build a scene exactly the size of the design canvas; embed
        # the widget via a proxy so click / key / mouse-move / IME
        # events all route to the embedded widget transparently.
        self._scene = QGraphicsScene(0, 0,
                                     self._design_width,
                                     self._design_height,
                                     self)
        self._proxy: QGraphicsProxyWidget = self._scene.addWidget(self._inner)
        self._proxy.setPos(0, 0)
        self.setScene(self._scene)

        # Render hints: keep custom QPainter widgets, fonts, and
        # antialiased shapes (drop shadows, vinyl rings, waveform bars)
        # crisp at non-1.0 scale factors.
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
            | QPainter.RenderHint.TextAntialiasing
        )

        # No scrollbars — this is fit-to-screen, never scroll.
        # Operators expect the Jazler-style "everything visible always"
        # contract; scrollbars on a broadcast cockpit would be a
        # workflow regression.
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # SmartViewportUpdate: Qt computes the minimal redraw region
        # per frame instead of repainting the whole viewport. Critical
        # for the LIVE-dot + AUTO-pulse animations which only dirty
        # small rects on each tick.
        self.setViewportUpdateMode(
            QGraphicsView.ViewportUpdateMode.SmartViewportUpdate)

        # Frame chrome off — the wrapper should be invisible to the
        # operator. Studio's own atmospheric bg fills the visible area
        # at any scale (its own paintEvent draws a 1920×1080 gradient
        # field, and the letterbox bands stay transparent).
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setBackgroundBrush(Qt.GlobalColor.transparent)

        # Initial fit — window resizeEvent will refit on every change.
        self._fit_view()

    # ── Public API ───────────────────────────────────────────────────────

    def inner_widget(self) -> QWidget:
        """Access the wrapped widget. Useful for callers that need to
        re-attach signals after construction or query state."""
        return self._inner

    def design_size(self) -> tuple[int, int]:
        """The native canvas size of the wrapped widget."""
        return self._design_width, self._design_height

    # ── Internals ────────────────────────────────────────────────────────

    def _fit_view(self) -> None:
        """Scale the scene to fit the current viewport, preserving aspect
        ratio. Called from __init__ and resizeEvent."""
        if self._scene is None:
            return
        rect = self._scene.sceneRect()
        if rect.width() <= 0 or rect.height() <= 0:
            return
        self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event):  # noqa: N802 — Qt naming
        """Re-fit on every viewport size change so the wrapped widget
        always exactly fills the new size, aspect-preserved."""
        super().resizeEvent(event)
        self._fit_view()
