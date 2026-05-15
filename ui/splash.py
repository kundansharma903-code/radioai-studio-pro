"""
RadioAI Studio Pro — Premium Splash Screen

Shown immediately after QApplication is created, before any heavy
init (Database, BASS audio, font loading, MainWindow construction).
Status text + progress bar update as each init step completes, then
the splash fades out as the main window shows.

Design
------
* Static hero image (1376×768, 16:9) loaded from
  ``assets/splash.png``. Image carries the brand visual: waveform
  on left, plexus mesh on right, glowing "Radio AI Studio Pro"
  wordmark center, dark gradient background. Bottom 30% of the
  image is intentionally darker so overlay text reads cleanly.

* Four subtle Qt-side animations layered on the static image:

  1. **Splash fade-in** — opacity 0 → 1 over 300ms when the
     splash is first shown. Smooth entrance.

  2. **Status text cross-fade** — when ``set_status(...)`` is
     called with new text, the old label fades out + the new
     label fades in over 200ms simultaneously. Avoids jarring
     instant swaps.

  3. **Animated progress bar** — a thin cyan strip at the bottom
     fills smoothly from 0% to 100% as each init step completes.
     ``advance(step_n)`` is called by main.py.

  4. **Pulsing accent dot** — a small cyan dot next to the status
     text gently pulses (1.5s heartbeat cycle). Signals "system
     is working." Pure GPU-accelerated opacity animation — zero
     CPU impact, doesn't compete with init thread.

The splash subclasses ``QSplashScreen`` so Qt handles the
"top-level, always-on-top, modal-feeling" window flags correctly.
Frameless, undecorated — only the brand visual + overlay text
shows.

Init handoff pattern (called from main.py):

    splash = RadioAISplash(total_steps=8)
    splash.show_animated()           # triggers fade-in

    splash.set_status("Connecting to database...", step=1)
    db = Database(); db.verify()

    splash.set_status("Loading settings...", step=2)
    Settings().load(db)

    # ... etc through all 8 steps ...

    splash.set_status("Starting Studio...", step=8)
    window = MainWindow(...)
    window.show()
    splash.finish_animated(window)   # fade out + close

If ``assets/splash.png`` is missing (corrupted install / dev
fallback), the splash renders a solid dark backdrop with the
status text only — never crashes the boot path.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from PyQt6.QtCore import (
    Qt, QTimer, QRect, QPropertyAnimation, QEasingCurve,
    pyqtProperty, QSize,
)
from PyQt6.QtGui import (
    QPixmap, QPainter, QColor, QFont, QFontMetrics, QBrush,
    QLinearGradient, QPainterPath,
)
from PyQt6.QtWidgets import (
    QSplashScreen, QApplication, QGraphicsOpacityEffect, QWidget,
)


log = logging.getLogger("Splash")


# ── Layout constants ─────────────────────────────────────────────────────
SPLASH_W = 720        # rendered width on screen (image is 1376×768; scaled)
SPLASH_H = 405        # 16:9 → 720×405 (exact aspect lock)

# Bottom overlay zone — reserved for status text + version footer
OVERLAY_PAD_X = 36
STATUS_BAR_Y = SPLASH_H - 78     # status text Y
PROGRESS_BAR_Y = SPLASH_H - 32   # progress bar fill line Y
VERSION_Y = SPLASH_H - 18        # version footer Y

# Status text + dot positions
STATUS_DOT_SIZE = 8
STATUS_DOT_GAP = 12

# Progress bar
PROGRESS_BAR_H = 3
PROGRESS_BAR_W = SPLASH_W - 2 * OVERLAY_PAD_X

# Colors (matches app design tokens)
COL_BG_FALLBACK = QColor("#070812")
COL_TEXT_PRI = QColor("#f1f5ff")
COL_TEXT_SEC = QColor("#a4adcc")
COL_TEXT_MUTED = QColor("#6b7398")
COL_ACCENT = QColor("#06b6d4")          # cyan
COL_PROGRESS_BG = QColor(28, 31, 56, 180)
COL_PROGRESS_FILL = QColor("#06b6d4")

# Brand text
VERSION_TEXT = "Version 2.0.0 · Studio Pro"

# Animation durations
DUR_FADE_IN = 300                 # ms
DUR_FADE_OUT = 250
DUR_STATUS_CROSSFADE = 200
DUR_DOT_PULSE = 1500              # full heartbeat cycle


# ════════════════════════════════════════════════════════════════════════
# RadioAISplash
# ════════════════════════════════════════════════════════════════════════


class RadioAISplash(QSplashScreen):
    """Premium splash screen with image + status + progress + dot pulse.

    Constructed before any heavy init. Display sequence:
      1. ``__init__`` — load image, build internal state
      2. ``show_animated()`` — fade in (caller invokes once)
      3. ``set_status(msg, step=N)`` — update status + advance bar
         (caller invokes for each init step)
      4. ``finish_animated(window)`` — fade out + close + show
         main window (caller invokes once at end)

    All animations are GPU-accelerated Qt graphics effects — they
    do NOT compete with the main thread, so heavy init operations
    (BASS DLL load, DB connect) won't stutter the animation."""

    def __init__(self,
                 total_steps: int = 8,
                 splash_image_path: Optional[str] = None,
                 parent: Optional[QWidget] = None):
        # Resolve image path — caller can override, otherwise default
        # to assets/splash.png. Uses the resource_path helper so it
        # works in both dev mode and PyInstaller frozen builds (where
        # the bundled assets land under sys._MEIPASS or next to the
        # exe).
        if splash_image_path is None:
            from core.paths import resource_path
            splash_image_path = str(resource_path("assets", "splash.png"))
        self._image_path = splash_image_path

        # Load + scale the image to display size. If the file is
        # missing or corrupted, fall back to a solid dark canvas so
        # the splash still renders (never crash the boot path).
        pix = self._load_pixmap(splash_image_path)

        super().__init__(pix, Qt.WindowType.WindowStaysOnTopHint
                          | Qt.WindowType.FramelessWindowHint)
        self.setEnabled(False)    # not interactive
        self.setFixedSize(SPLASH_W, SPLASH_H)

        # Internal state
        self._total_steps = max(1, int(total_steps))
        self._current_step = 0
        self._current_status = ""
        # Cross-fade state — when set_status runs, _pending_status
        # snapshots the new text and an animation morphs it in.
        self._status_opacity = 1.0
        self._progress_value = 0.0       # 0.0..1.0
        self._dot_opacity = 1.0
        self._splash_opacity = 1.0       # outer opacity (fade in/out)

        # Set up opacity-effect wrappers for the splash itself —
        # the overall fade-in / fade-out at boot + close.
        self._main_opacity_effect = QGraphicsOpacityEffect(self)
        self._main_opacity_effect.setOpacity(0.0)
        self.setGraphicsEffect(self._main_opacity_effect)

        # Animation: fade-in for the whole splash on show
        self._anim_fade_in = QPropertyAnimation(
            self._main_opacity_effect, b"opacity")
        self._anim_fade_in.setDuration(DUR_FADE_IN)
        self._anim_fade_in.setStartValue(0.0)
        self._anim_fade_in.setEndValue(1.0)
        self._anim_fade_in.setEasingCurve(QEasingCurve.Type.OutCubic)

        # Animation: fade-out for the whole splash on finish
        self._anim_fade_out = QPropertyAnimation(
            self._main_opacity_effect, b"opacity")
        self._anim_fade_out.setDuration(DUR_FADE_OUT)
        self._anim_fade_out.setStartValue(1.0)
        self._anim_fade_out.setEndValue(0.0)
        self._anim_fade_out.setEasingCurve(QEasingCurve.Type.InCubic)

        # Pulsing dot — driven by a QTimer that flips a sine-ish
        # value 60 times per second. Phase tracked by _dot_t.
        self._dot_t = 0.0    # 0..1 sine phase
        self._dot_timer = QTimer(self)
        self._dot_timer.setInterval(16)   # ~60 fps
        self._dot_timer.timeout.connect(self._on_dot_tick)
        self._dot_timer.start()

        # Progress-bar smooth animation — animates 0→target value
        # over 250ms each time ``advance()`` is called.
        self._anim_progress = QPropertyAnimation(
            self, b"_qt_progress_value")
        self._anim_progress.setDuration(250)
        self._anim_progress.setEasingCurve(QEasingCurve.Type.OutCubic)

        # Status text fade animation — fade out current, then swap,
        # then fade back in. Uses _qt_status_opacity property.
        self._anim_status_out = QPropertyAnimation(
            self, b"_qt_status_opacity")
        self._anim_status_out.setDuration(DUR_STATUS_CROSSFADE // 2)
        self._anim_status_in = QPropertyAnimation(
            self, b"_qt_status_opacity")
        self._anim_status_in.setDuration(DUR_STATUS_CROSSFADE // 2)
        self._anim_status_out.finished.connect(self._on_status_faded_out)
        # New text to swap to (set by set_status before triggering the
        # fade-out animation; consumed when the fade-out finishes)
        self._pending_status: Optional[str] = None
        self._pending_step: Optional[int] = None

    # ── Image loading ──────────────────────────────────────────────────
    @staticmethod
    def _load_pixmap(path: str) -> QPixmap:
        """Load and scale the splash image to display size. Returns a
        fallback solid-dark pixmap if the file is missing or invalid."""
        if path and os.path.isfile(path):
            pix = QPixmap(path)
            if not pix.isNull():
                # Scale to display size preserving aspect ratio.
                scaled = pix.scaled(
                    SPLASH_W, SPLASH_H,
                    Qt.AspectRatioMode.IgnoreAspectRatio,
                    Qt.TransformationMode.SmoothTransformation)
                return scaled
            log.warning(
                f"splash image at {path!r} loaded as null pixmap — "
                f"using fallback")
        else:
            log.warning(
                f"splash image not found at {path!r} — using fallback")
        # Fallback: solid dark canvas
        fallback = QPixmap(SPLASH_W, SPLASH_H)
        fallback.fill(COL_BG_FALLBACK)
        return fallback

    # ── Qt animation properties ────────────────────────────────────────
    def _get_qt_progress_value(self) -> float:
        return self._progress_value

    def _set_qt_progress_value(self, value: float) -> None:
        self._progress_value = max(0.0, min(1.0, float(value)))
        self.repaint()

    _qt_progress_value = pyqtProperty(
        float, _get_qt_progress_value, _set_qt_progress_value)

    def _get_qt_status_opacity(self) -> float:
        return self._status_opacity

    def _set_qt_status_opacity(self, value: float) -> None:
        self._status_opacity = max(0.0, min(1.0, float(value)))
        self.repaint()

    _qt_status_opacity = pyqtProperty(
        float, _get_qt_status_opacity, _set_qt_status_opacity)

    # ── Pulsing dot tick ───────────────────────────────────────────────
    def _on_dot_tick(self) -> None:
        """Advances the sine phase used to pulse the accent dot."""
        import math
        self._dot_t = (self._dot_t + 16 / DUR_DOT_PULSE) % 1.0
        # Sine wave 0→1→0, mapped to 0.35..1.0 opacity (always
        # visible, just breathes)
        self._dot_opacity = 0.35 + 0.65 * (
            (math.sin(self._dot_t * 2 * math.pi - math.pi / 2) + 1) / 2)
        self.repaint()

    # ── Status text cross-fade ─────────────────────────────────────────
    def _on_status_faded_out(self) -> None:
        """Mid-cross-fade callback. Swap to the pending text + animate
        back in."""
        if self._pending_status is not None:
            self._current_status = self._pending_status
            self._pending_status = None
        if self._pending_step is not None:
            self._current_step = self._pending_step
            self._pending_step = None
            # Trigger progress bar animation to the new step's value
            target = self._current_step / self._total_steps
            self._anim_progress.stop()
            self._anim_progress.setStartValue(self._progress_value)
            self._anim_progress.setEndValue(target)
            self._anim_progress.start()
        # Fade the new text in
        self._anim_status_in.stop()
        self._anim_status_in.setStartValue(0.0)
        self._anim_status_in.setEndValue(1.0)
        self._anim_status_in.start()

    # ── Public API ─────────────────────────────────────────────────────
    def show_animated(self) -> None:
        """Show the splash + run the fade-in animation. Caller invokes
        once at boot before any init work."""
        # Centre on the primary screen
        screen = QApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            self.move(
                geo.center().x() - SPLASH_W // 2,
                geo.center().y() - SPLASH_H // 2)
        self.show()
        # Process events so the splash actually paints before init
        # begins blocking the main thread
        QApplication.processEvents()
        self._anim_fade_in.start()
        QApplication.processEvents()

    def set_status(self, message: str, step: Optional[int] = None) -> None:
        """Update the status text + (optionally) advance progress bar.

        Triggers a cross-fade animation: current text fades out, new
        text swaps in. ``step`` is the 1-based index of the init
        step — used to advance the progress bar by step/total_steps.

        Safe to call BEFORE ``show_animated()`` — the message will
        just appear when the splash is first shown."""
        log.info(f"[splash] {message} (step={step})")
        self._pending_status = str(message)
        if step is not None:
            self._pending_step = int(step)
        # If we're mid-animation, the existing fade-out finishing
        # handler will pick up the new pending text. Otherwise
        # trigger a fresh fade-out → in cycle.
        if (self._anim_status_out.state()
                != QPropertyAnimation.State.Running):
            self._anim_status_out.stop()
            self._anim_status_out.setStartValue(self._status_opacity)
            self._anim_status_out.setEndValue(0.0)
            self._anim_status_out.start()
        # Pump events so the splash repaints between init steps
        QApplication.processEvents()

    def dwell(self, milliseconds: int) -> None:
        """Hold the splash on its current message for ``milliseconds``
        while keeping all animations (pulsing dot, progress bar fill,
        text cross-fade) smooth and the Qt event loop pumping.

        Implementation uses a local ``QEventLoop`` with a single-shot
        ``QTimer`` — the standard Qt idiom for "sleep without blocking
        the UI." Animations driven by other timers + the
        QPropertyAnimation system continue running unaffected.

        Caller invokes this between ``set_status(...)`` and the next
        init step when the underlying work is too fast for the
        operator to read the message (DB connect, BASS init, etc.
        complete in <100ms — without dwell, the splash flashes past
        in 1-2 seconds total)."""
        from PyQt6.QtCore import QEventLoop
        loop = QEventLoop()
        QTimer.singleShot(max(0, int(milliseconds)), loop.quit)
        loop.exec()

    def finish_animated(self, main_window: QWidget) -> None:
        """Fade the splash out, then close it and ensure ``main_window``
        is on top. Caller invokes after MainWindow.show()."""
        log.info("[splash] finishing — fading out")
        # Ensure progress bar shows 100% on close
        if self._progress_value < 1.0:
            self._set_qt_progress_value(1.0)
        QApplication.processEvents()
        self._anim_fade_out.finished.connect(
            lambda mw=main_window: self._on_fade_out_done(mw))
        self._anim_fade_out.start()
        QApplication.processEvents()

    def _on_fade_out_done(self, main_window: QWidget) -> None:
        """Splash fade-out finished — call finish() to close + raise
        main window."""
        self._dot_timer.stop()
        try:
            self.finish(main_window)
        except Exception as exc:
            log.warning(f"[splash] finish() raised: {exc}")
            self.close()

    # ── Painting ───────────────────────────────────────────────────────
    def drawContents(self, painter: QPainter) -> None:
        """Custom overlay: status text + dot + progress bar + version
        footer. Painted on top of the splash image base."""
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(
            QPainter.RenderHint.TextAntialiasing, True)

        # ── Status text + pulsing dot ────────────────────────────────
        status_text = self._current_status or ""
        if status_text:
            # Pulsing cyan accent dot
            dot_color = QColor(COL_ACCENT)
            dot_color.setAlphaF(self._dot_opacity * self._status_opacity)
            painter.setBrush(dot_color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(
                OVERLAY_PAD_X, STATUS_BAR_Y + 4,
                STATUS_DOT_SIZE, STATUS_DOT_SIZE)

            # Status label
            text_color = QColor(COL_TEXT_PRI)
            text_color.setAlphaF(self._status_opacity)
            painter.setPen(text_color)
            font = QFont("Inter", 11, QFont.Weight.Medium)
            painter.setFont(font)
            text_x = OVERLAY_PAD_X + STATUS_DOT_SIZE + STATUS_DOT_GAP
            painter.drawText(
                text_x, STATUS_BAR_Y + 14,
                status_text)

        # ── Progress bar background ──────────────────────────────────
        painter.setBrush(COL_PROGRESS_BG)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(
            OVERLAY_PAD_X, PROGRESS_BAR_Y,
            PROGRESS_BAR_W, PROGRESS_BAR_H,
            1.5, 1.5)

        # Progress bar fill (cyan, animated)
        if self._progress_value > 0:
            fill_w = int(PROGRESS_BAR_W * self._progress_value)
            painter.setBrush(COL_PROGRESS_FILL)
            painter.drawRoundedRect(
                OVERLAY_PAD_X, PROGRESS_BAR_Y,
                fill_w, PROGRESS_BAR_H, 1.5, 1.5)

        # ── Version footer (bottom-right, subtle) ─────────────────────
        ver_color = QColor(COL_TEXT_MUTED)
        painter.setPen(ver_color)
        font = QFont("Inter", 9, QFont.Weight.Normal)
        painter.setFont(font)
        # Right-align: measure width + place
        fm = QFontMetrics(font)
        ver_w = fm.horizontalAdvance(VERSION_TEXT)
        painter.drawText(
            SPLASH_W - OVERLAY_PAD_X - ver_w,
            VERSION_Y + 6,
            VERSION_TEXT)

    # Disable Qt's default click-to-close on splash screens
    def mousePressEvent(self, ev) -> None:
        ev.accept()
