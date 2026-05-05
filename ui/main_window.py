"""
RadioAI Studio Pro — Main Window (chrome-less shell)

Each screen (ControlPanel, Studio, etc.) renders a fixed 1440×900 design.
The QMainWindow auto-sizes to that client area + OS chrome (title bar +
borders), so the FULL design is visible — no clipping.

Use --maximized to launch maximized for testing on larger displays.
"""

import logging
import sys

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QMainWindow, QStackedWidget, QApplication

from core.constants import APP_NAME, APP_VERSION, WINDOW_W, WINDOW_H

log = logging.getLogger("MainWindow")


class MainWindow(QMainWindow):
    """Frame around a 1440×900 screen widget. Sized to fit client + chrome."""

    def __init__(self, db_ok: bool = True, song_count: int = 0, db=None):
        super().__init__()
        self._db = db
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")

        # Shared AudioEngine instance (Phase B Option C: singleton + DI).
        # Created lazily — bass_init() is owned by main.py per the engine
        # lifecycle contract. closeEvent() AND QApplication.aboutToQuit
        # both invoke _cleanup_engine() (idempotent belt-and-suspenders)
        # before main.py runs bass_free().
        from core.audio import AudioEngine
        self._engine = AudioEngine(parent=self)

        # Shared SchedulerEngine instance (Phase D3 — Option C DI).
        # Lives on its own QThread; ticks at 1Hz. NOT auto-started in
        # D3 — explicit start() comes from D5+ once the live broadcast
        # loop is wired. Stopped before audio cleanup on shutdown.
        from core.scheduler import SchedulerEngine
        self._scheduler = SchedulerEngine(self._db, parent=self)

        # Phase B5: aboutToQuit safety net. Fires on app force-quit, OS
        # shutdown, or any path that bypasses closeEvent. cleanup_all is
        # idempotent so the dual-hook is cheap.
        from PyQt6.QtCore import QCoreApplication
        _app = QCoreApplication.instance()
        if _app is not None:
            _app.aboutToQuit.connect(self._on_about_to_quit)

        # Adaptive sizing: never exceed 95% × 92% of available screen.
        # On a 1920×1080 we get the full 1440×900 design. On a 1366×768
        # laptop we get ≈1300×700 and the central widget scrolls if needed.
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            max_w = int(avail.width()  * 0.98)
            max_h = int(avail.height() * 0.95)
        else:
            max_w, max_h = WINDOW_W, WINDOW_H

        target_w = min(WINDOW_W, max_w)
        target_h = min(WINDOW_H, max_h)

        # Wrap the QStackedWidget in a QScrollArea so screens larger than
        # the window can be scrolled. CRITICAL: the QScrollArea has TWO
        # background layers — the area widget itself AND its viewport
        # (a hidden child QWidget). We must dark-ify BOTH or the default
        # palette leaks through and we get a white background around the
        # screen.
        from PyQt6.QtWidgets import QScrollArea, QFrame
        from PyQt6.QtCore import Qt as _Qt
        from PyQt6.QtGui import QPalette, QColor as _QColor

        self._stack = QStackedWidget()
        self._stack.setFixedSize(WINDOW_W, WINDOW_H)  # design canvas

        scroll = QScrollArea()
        scroll.setObjectName("mwScroll")
        scroll.setWidgetResizable(False)             # keep stack at design size
        scroll.setHorizontalScrollBarPolicy(_Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(_Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        # Dark-ify the viewport via palette (QSS doesn't reach it reliably)
        viewport_bg = _QColor("#06080f")
        pal = scroll.viewport().palette()
        pal.setColor(QPalette.ColorRole.Base, viewport_bg)
        pal.setColor(QPalette.ColorRole.Window, viewport_bg)
        scroll.viewport().setPalette(pal)
        scroll.viewport().setAutoFillBackground(True)

        # Style the scrollbars (#mwScroll selector to scope precisely)
        scroll.setStyleSheet(
            "QScrollArea#mwScroll { background: #06080f; border: none; }"
            "QScrollArea#mwScroll > QWidget > QWidget { background: #06080f; }"
            "QScrollBar:vertical { background: rgba(255,255,255,0.02); width: 8px; }"
            "QScrollBar::handle:vertical { background: rgba(167,139,250,0.4); "
            "border-radius: 4px; min-height: 30px; margin: 2px; }"
            "QScrollBar::handle:vertical:hover { background: rgba(167,139,250,0.7); }"
            "QScrollBar:horizontal { background: rgba(255,255,255,0.02); height: 8px; }"
            "QScrollBar::handle:horizontal { background: rgba(167,139,250,0.4); "
            "border-radius: 4px; min-width: 30px; margin: 2px; }"
            "QScrollBar::handle:horizontal:hover { background: rgba(167,139,250,0.7); }"
            "QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }"
        )
        scroll.setWidget(self._stack)
        self.setCentralWidget(scroll)
        # Dark-ify the QMainWindow palette as well so any uncovered area
        # (e.g. menu bar zone, tiny stragglers) stays dark.
        mw_pal = self.palette()
        mw_pal.setColor(QPalette.ColorRole.Window, viewport_bg)
        self.setPalette(mw_pal)
        self.setAutoFillBackground(True)

        # Window can shrink below the design canvas (scrollbars will appear).
        self.setMinimumSize(800, 600)
        self.resize(target_w, target_h)

        self._mount_control_panel()
        self._center_on_screen()

        log.info(
            f"MainWindow ready — window={self.size().width()}x{self.size().height()}, "
            f"design canvas={WINDOW_W}x{WINDOW_H}"
        )

    # ── Sizing helpers ────────────────────────────────────────────────────

    def _center_on_screen(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        avail = screen.availableGeometry()
        x = avail.x() + (avail.width()  - self.width())  // 2
        y = avail.y() + (avail.height() - self.height()) // 2
        # Don't push above 0 if the window is taller than the screen
        self.move(max(avail.x(), x), max(avail.y(), y))

    # ── Mount ──────────────────────────────────────────────────────────────

    def _mount_control_panel(self) -> None:
        if self._db is None:
            return
        try:
            from ui.control_panel import ControlPanel
            self.control_panel = ControlPanel(self._db)
            self.control_panel.card_clicked.connect(self._on_card_clicked)
            self.control_panel.nav_clicked.connect(self._on_nav_clicked)
            self.control_panel.studio_clicked.connect(self._on_studio_clicked)
            self.control_panel.settings_clicked.connect(self._on_settings_clicked)
            self._stack.addWidget(self.control_panel)
            self._stack.setCurrentWidget(self.control_panel)

            # Mount Songs Library lazily — it's heavy because it loads all songs
            from ui.songs_library import SongsLibrary
            self.songs_library = SongsLibrary(self._db, engine=self._engine)
            self.songs_library.breadcrumb_clicked.connect(self._on_breadcrumb)
            self.songs_library.studio_clicked.connect(self._on_studio_clicked)
            self.songs_library.song_selected.connect(self._on_song_selected)
            self.songs_library.play_song_clicked.connect(self._on_play_song)
            self.songs_library.report_clicked.connect(self._on_report_clicked)
            self._stack.addWidget(self.songs_library)

            # Instant Jingles — live broadcast pads (Figma 44:688)
            from ui.instant_jingles import InstantJingles
            self.instant_jingles = InstantJingles(
                self._db, engine=self._engine)
            self.instant_jingles.breadcrumb_clicked.connect(self._on_breadcrumb)
            self.instant_jingles.studio_clicked.connect(self._on_studio_clicked)
            self._stack.addWidget(self.instant_jingles)

            # Spots & Commercials Library (Figma 35:2)
            from ui.spots_commercials import SpotsCommercials
            self.spots_commercials = SpotsCommercials(
                self._db, engine=self._engine)
            self.spots_commercials.breadcrumb_clicked.connect(self._on_breadcrumb)
            self.spots_commercials.studio_clicked.connect(self._on_studio_clicked)
            self._stack.addWidget(self.spots_commercials)

            # Studio Single Deck — broadcast operator workstation (Figma 182:2)
            # Phase D1: skeleton; D2 wires manual audio; D3 passes scheduler.
            from ui.studio import Studio
            self.studio = Studio(
                self._db, parent=None,
                engine=self._engine, scheduler=self._scheduler)
            self.studio.breadcrumb_clicked.connect(self._on_breadcrumb)
            self._stack.addWidget(self.studio)

            # Scheduling Hub — premium dark theme rebuild (Figma 231:3).
            # Pure navigation grid + Studio launcher; live status footer
            # reflects scheduler engine state.
            from ui.scheduling_hub import SchedulingHub
            self.scheduling_hub = SchedulingHub(
                self._db, scheduler=self._scheduler, parent=None)
            self.scheduling_hub.screen_requested.connect(
                self._on_hub_screen_requested)
            self._stack.addWidget(self.scheduling_hub)

            # Playlists — Figma 239:2 premium screen.
            from ui.playlists import Playlists
            self.playlists_screen = Playlists(
                self._db, scheduler=self._scheduler,
                studio=getattr(self, "studio", None),
                engine=self._engine, parent=None)
            self.playlists_screen.screen_requested.connect(
                self._on_hub_screen_requested)
            self._stack.addWidget(self.playlists_screen)

            # Create New Playlist — Figma 243:2 premium screen.
            from ui.playlist_new import PlaylistNew
            self.playlist_new_screen = PlaylistNew(
                self._db, scheduler=self._scheduler, parent=None,
                engine=self._engine)
            self.playlist_new_screen.screen_requested.connect(
                self._on_hub_screen_requested)
            self._stack.addWidget(self.playlist_new_screen)

            # Main Auto Schedule — Figma 278:2 premium screen.
            from ui.auto_schedule import AutoSchedule
            self.auto_schedule_screen = AutoSchedule(
                self._db, scheduler=self._scheduler, parent=None)
            self.auto_schedule_screen.screen_requested.connect(
                self._on_hub_screen_requested)
            self._stack.addWidget(self.auto_schedule_screen)

            # Clock Editor — Figma 285:2 premium screen.
            from ui.clock_editor import ClockEditor
            self.clock_editor_screen = ClockEditor(
                self._db, scheduler=self._scheduler, parent=None)
            self.clock_editor_screen.screen_requested.connect(
                self._on_hub_screen_requested)
            self._stack.addWidget(self.clock_editor_screen)

            # F9 shortcut → open Studio (broadcast convention; Jazler precedent)
            from PyQt6.QtGui import QShortcut, QKeySequence
            self._studio_shortcut = QShortcut(QKeySequence("F9"), self)
            self._studio_shortcut.activated.connect(self._on_studio_clicked)
        except Exception as exc:
            import traceback
            log.error(f"Mount failed: {exc}\n{traceback.format_exc()}")

    def _on_card_clicked(self, screen: str) -> None:
        log.info(f"Card → {screen}")
        # Route to matching screen
        if screen == "songs" and hasattr(self, "songs_library"):
            self._stack.setCurrentWidget(self.songs_library)
        elif screen == "instant_jingles" and hasattr(self, "instant_jingles"):
            self._stack.setCurrentWidget(self.instant_jingles)
        elif screen == "spots" and hasattr(self, "spots_commercials"):
            self._stack.setCurrentWidget(self.spots_commercials)
        elif screen == "scheduling" and hasattr(self, "scheduling_hub"):
            # Hub becomes the visible screen; it injects studio reference
            # lazily so the now-playing poll picks up Studio if mounted.
            if hasattr(self, "studio") and hasattr(self.scheduling_hub,
                                                    "set_studio"):
                self.scheduling_hub.set_studio(self.studio)
            self._stack.setCurrentWidget(self.scheduling_hub)

    def _on_breadcrumb(self, where: str) -> None:
        log.info(f"Breadcrumb → {where}")
        if where == "control_panel" and hasattr(self, "control_panel"):
            self._stack.setCurrentWidget(self.control_panel)

    def _on_hub_screen_requested(self, screen: str) -> None:
        """Routes from SchedulingHub / Playlists / sibling screens.
        Real screens that haven't been ported to the new theme yet
        show a "coming soon" toast — never crash."""
        log.info(f"Hub → {screen}")
        if screen == "studio_open":
            self._on_studio_clicked()
            return
        if screen == "libraries":
            # Libraries tab → Control Panel (hosts the library cards).
            if hasattr(self, "control_panel"):
                self._stack.setCurrentWidget(self.control_panel)
            return
        if screen == "scheduling_hub" and hasattr(self, "scheduling_hub"):
            self._stack.setCurrentWidget(self.scheduling_hub)
            return
        if screen == "playlists" and hasattr(self, "playlists_screen"):
            # Lazy-inject Studio so the on-air detection works
            if hasattr(self, "studio") and hasattr(
                    self.playlists_screen, "set_studio"):
                self.playlists_screen.set_studio(self.studio)
            self._stack.setCurrentWidget(self.playlists_screen)
            return
        # screen_requested("playlist_edit:42") — open editor for that id
        if screen.startswith("playlist_edit:"):
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(
                self, "Playlist Editor",
                f"Edit Playlist (id={screen.split(':', 1)[1]}) — "
                "coming soon (Figma 240:2).")
            return
        if screen == "playlist_new" and hasattr(self, "playlist_new_screen"):
            self._stack.setCurrentWidget(self.playlist_new_screen)
            return
        if (screen == "main_auto_schedule"
                and hasattr(self, "auto_schedule_screen")):
            self._stack.setCurrentWidget(self.auto_schedule_screen)
            return
        # Clock Editor (Figma 285:2) — three modes
        if screen == "clock_new" and hasattr(self, "clock_editor_screen"):
            self.clock_editor_screen.load_for_mode("new")
            self._stack.setCurrentWidget(self.clock_editor_screen)
            return
        if (screen.startswith("clock_edit:")
                and hasattr(self, "clock_editor_screen")):
            try:
                cid = int(screen.split(":", 1)[1])
            except (ValueError, IndexError):
                return
            self.clock_editor_screen.load_for_mode("edit", clock_id=cid)
            self._stack.setCurrentWidget(self.clock_editor_screen)
            return
        if (screen.startswith("clock_duplicate:")
                and hasattr(self, "clock_editor_screen")):
            try:
                cid = int(screen.split(":", 1)[1])
            except (ValueError, IndexError):
                return
            self.clock_editor_screen.load_for_mode("duplicate", clock_id=cid)
            self._stack.setCurrentWidget(self.clock_editor_screen)
            return
        if screen == "auto_program_settings":
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(
                self, "Auto Program Settings",
                "Auto Program Settings — coming soon.")
            return
        # Everything else is a future scheduling sub-screen.
        from PyQt6.QtWidgets import QMessageBox
        labels = {
            "force_clocks":       "Force Clocks Schedule",
            "rebroadcast":        "Rebroadcast Schedule",
            "rds":                "RDS",
            "final_log_creator":  "Final Log Creator",
            "log_viewer":         "Log Viewer",
            "settings":           "Settings",
            "ai_magic":           "AI Magic",
        }
        title = labels.get(screen, screen)
        QMessageBox.information(
            self, title,
            f"{title} — coming soon.\n\nThis screen will be ported to "
            "the premium theme in a follow-up commit.")

    def _on_song_selected(self, song_id: int) -> None:
        log.info(f"Song selected: id={song_id}")

    def _on_play_song(self, song_id: int) -> None:
        log.info(f"Play song: id={song_id}")

    def _on_report_clicked(self, name: str) -> None:
        log.info(f"Report → {name}")

    def _on_nav_clicked(self, tab: str) -> None:
        log.info(f"Nav → {tab}")

    def _on_studio_clicked(self) -> None:
        log.info("Open Studio →")
        if hasattr(self, "studio"):
            self._stack.setCurrentWidget(self.studio)

    def _on_settings_clicked(self) -> None:
        log.info("Settings →")

    def closeEvent(self, event):
        """Primary cleanup path — fires when the user closes the window
        via the title-bar X or via app.quit() during normal operation."""
        log.info("MainWindow closing")
        self._cleanup_engine()
        super().closeEvent(event)

    def _on_about_to_quit(self):
        """Safety net — fires AFTER all windows close but BEFORE the
        Qt event loop ends. Catches force-quit / OS-shutdown paths that
        bypass closeEvent. Idempotent with closeEvent's cleanup."""
        log.info("MainWindow aboutToQuit — defensive cleanup")
        self._cleanup_engine()

    def _cleanup_engine(self):
        """Idempotent shutdown. Both closeEvent and aboutToQuit call
        this; the second call is a no-op once the scheduler is stopped
        and the engine has no active channels.

        ORDER MATTERS: scheduler stops FIRST so it can't fire any more
        spot_due / song_auto_advance signals into a tearing-down audio
        engine. Then audio cleanup."""
        # 1. Stop scheduler (silence the event source)
        if hasattr(self, "_scheduler") and self._scheduler is not None:
            try:
                self._scheduler.stop()
                log.info("SchedulerEngine stopped")
            except Exception as exc:
                log.warning(f"scheduler stop failed: {exc}")

        # 2. Cleanup audio channels
        if not hasattr(self, "_engine") or self._engine is None:
            return
        try:
            self._engine.cleanup_all()
            log.info("AudioEngine cleanup_all done")
        except Exception as exc:
            log.warning(f"engine cleanup_all failed: {exc}")
