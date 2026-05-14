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

        # Studio's InstantJingleEngine (Phase A — Option 2 topology).
        # Independent from ui/instant_jingles.py's own IJE instance —
        # both share the underlying AudioEngine; the only divergence is
        # the per-instance 8-pad polyphony cap. Future cleanup will
        # consolidate to a single shared instance.
        from core.instant_jingle_engine import InstantJingleEngine
        self._instant_jingle_engine = InstantJingleEngine(
            engine=self._engine, parent=self)

        # SweeperEngine — overlay player on its own BASS channel. Shared
        # across MainWindow so manual sweeper plays from the Sweepers
        # Library tile in Studio's Libraries panel and scheduler-dispatched
        # sweeper slots both go through the same instance (latest cancels
        # any previous overlay — only one sweeper at a time, by design).
        from core.sweeper_engine import SweeperEngine
        self._sweeper_engine = SweeperEngine()

        # StitcherEngine — pre-mixes a "Coming Up Next" hook montage
        # (opening + N song hooks + closing) and plays the result as
        # one seamless WAV through BASS. Shared instance so The
        # Stitcher screen + Studio's pre-break trigger (when wired)
        # both drive the same engine.
        from core.stitcher_engine import StitcherEngine
        self._stitcher_engine = StitcherEngine()

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
        # Resize the stack to the active screen's footprint on every
        # widget change. Without this, the stack stays at the largest
        # screen's size (1920×1080 for Studio / Final Log) — so on
        # smaller screens (1440×900) the operator could scroll
        # horizontally into 480px of blank space past the content
        # edge. Hook fires for setCurrentWidget + setCurrentIndex.
        self._stack.currentChanged.connect(self._on_stack_currentChanged)

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

        # Style the scrollbars (#mwScroll selector to scope precisely).
        # Polished pattern matching modern broadcast apps:
        #   - Track barely visible (transparent), top/bottom inset so
        #     the handle never kisses the window edges.
        #   - Handle subtle gray idle, cyan on hover, brighter on
        #     press. 60px minimum so it's always easy to grab even
        #     when the content overflow is huge.
        #   - 10px outer width with 3px horizontal handle margin →
        #     effective 4px visible handle, which reads as "thin"
        #     while remaining easy to click.
        #   - No add-line / sub-line arrow buttons (modern convention).
        scroll.setStyleSheet(
            "QScrollArea#mwScroll { background: #06080f; border: none; }"
            "QScrollArea#mwScroll > QWidget > QWidget { background: #06080f; }"
            "QScrollBar:vertical { background: transparent; "
            "width: 10px; margin: 8px 0 8px 0; }"
            "QScrollBar::handle:vertical { background: "
            "rgba(255,255,255,0.10); border-radius: 3px; "
            "min-height: 60px; margin: 0 3px; }"
            "QScrollBar::handle:vertical:hover { "
            "background: rgba(34,211,238,0.55); }"
            "QScrollBar::handle:vertical:pressed { "
            "background: rgba(6,182,212,0.85); }"
            "QScrollBar:horizontal { background: transparent; "
            "height: 10px; margin: 0 8px 0 8px; }"
            "QScrollBar::handle:horizontal { background: "
            "rgba(255,255,255,0.10); border-radius: 3px; "
            "min-width: 60px; margin: 3px 0; }"
            "QScrollBar::handle:horizontal:hover { "
            "background: rgba(34,211,238,0.55); }"
            "QScrollBar::handle:horizontal:pressed { "
            "background: rgba(6,182,212,0.85); }"
            "QScrollBar::add-line, QScrollBar::sub-line { "
            "width: 0; height: 0; background: transparent; border: none; }"
            "QScrollBar::add-page, QScrollBar::sub-page { "
            "background: transparent; }"
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
                self._db, engine=self._engine,
                instant_jingle_engine=self._instant_jingle_engine)
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

            # Sweepers Library (Figma 46:2)
            from ui.sweepers_library import SweepersLibrary
            self.sweepers_library = SweepersLibrary(
                self._db, engine=self._engine)
            self.sweepers_library.breadcrumb_clicked.connect(self._on_breadcrumb)
            self.sweepers_library.studio_clicked.connect(self._on_studio_clicked)
            self._stack.addWidget(self.sweepers_library)

            # Jingles Library (Figma 44:2) — master catalog of station
            # identity audio. ControlPanel "Jingles" card routes here.
            from ui.jingles_library import JinglesLibrary
            self.jingles_library = JinglesLibrary(
                self._db, engine=self._engine)
            self.jingles_library.breadcrumb_clicked.connect(self._on_breadcrumb)
            self.jingles_library.studio_clicked.connect(self._on_studio_clicked)
            self._stack.addWidget(self.jingles_library)

            # The Stitcher (Figma 46:481) — pre-mix "Coming Up Next"
            # hook montage. ControlPanel "stitcher" card routes here.
            from ui.stitcher import Stitcher
            self.stitcher = Stitcher(
                self._db, engine=self._engine, scheduler=self._scheduler,
                stitcher_engine=self._stitcher_engine
                if hasattr(self, "_stitcher_engine") else None)
            self.stitcher.breadcrumb_clicked.connect(self._on_breadcrumb)
            self.stitcher.studio_clicked.connect(self._on_studio_clicked)
            self._stack.addWidget(self.stitcher)

            # Final Log Creator (Figma 14:2) — broadcast history viewer.
            # Reads broadcast_log per hour/date. SchedulingHub tile
            # "final_log_creator" routes here (removed from labels
            # coming-soon dict in the same commit).
            from ui.final_log import FinalLog
            self.final_log = FinalLog(self._db, scheduler=self._scheduler)
            # Final Log Creator's top tabs (Libraries / Scheduling /
            # Settings / Utilities) route through _on_hub_screen_requested
            # because those tab keys live in that handler's switch — not
            # in _on_breadcrumb which only handles a literal "control_panel"
            # crumb. Without this wiring "Libraries" tab swallowed silently.
            self.final_log.breadcrumb_clicked.connect(
                self._on_hub_screen_requested)
            self.final_log.studio_clicked.connect(self._on_studio_clicked)
            self._stack.addWidget(self.final_log)

            # General Settings (Figma 68:2) — Settings root page (only
            # sub-page so far). SchedulingHub footer "Settings" + Hub
            # tile "settings" both route here.
            from ui.settings_general import SettingsGeneral
            self.settings_general = SettingsGeneral(self._db)
            self.settings_general.breadcrumb_clicked.connect(
                self._on_hub_screen_requested)
            self.settings_general.studio_clicked.connect(
                self._on_studio_clicked)
            # Any successful save broadcasts a branding refresh so the
            # header station label on every other mounted screen catches
            # the new station_name / station_frequency immediately.
            self.settings_general.settings_saved.connect(
                self._refresh_station_branding)
            self._stack.addWidget(self.settings_general)

            # Settings Hub (Figma 426:3) — landing page for the three
            # Settings sub-sections. Routed via "settings"; General +
            # Soundcard cards route to real screens, Studio card still
            # toasts "coming v1.1".
            from ui.settings_hub import SettingsHub
            self.settings_hub = SettingsHub(self._db)
            self.settings_hub.screen_requested.connect(
                self._on_hub_screen_requested)
            self.settings_hub.studio_clicked.connect(
                self._on_studio_clicked)
            self._stack.addWidget(self.settings_hub)

            # Soundcard Settings (Figma 68:394) — 4 outputs + 1 input
            # channel cards, BASS device enumeration, save → settings DB.
            from ui.settings_soundcard import SettingsSoundcard
            self.settings_soundcard = SettingsSoundcard(self._db)
            self.settings_soundcard.breadcrumb_clicked.connect(
                self._on_hub_screen_requested)
            self.settings_soundcard.studio_clicked.connect(
                self._on_studio_clicked)
            self._stack.addWidget(self.settings_soundcard)

            # Studio Settings (Figma 69:2) — crossfade, fade curves,
            # AutoCue, levels, VU meters, cue split, audio engine info.
            # Third (and final) Settings sub-page.
            from ui.settings_studio import SettingsStudio
            self.settings_studio = SettingsStudio(self._db)
            self.settings_studio.breadcrumb_clicked.connect(
                self._on_hub_screen_requested)
            self.settings_studio.studio_clicked.connect(
                self._on_studio_clicked)
            # Live-broadcast: every successful Save inside Studio
            # Settings re-pushes the persisted values into the running
            # Studio screen so fade/volume/fallback changes feel
            # immediate (no restart required).
            self.settings_studio.settings_saved.connect(
                self._on_studio_settings_saved)
            self._stack.addWidget(self.settings_studio)

            # Play History (Figma 437:3) — per-song analytics. Routed
            # via Songs Library's "Play History" report action; the
            # _on_report_clicked handler reads the currently-selected
            # song id off the songs_library + calls load_song().
            from ui.play_history import PlayHistory
            self.play_history = PlayHistory(self._db)
            self.play_history.breadcrumb_clicked.connect(
                self._on_hub_screen_requested)
            self.play_history.studio_clicked.connect(
                self._on_studio_clicked)
            self._stack.addWidget(self.play_history)

            # Studio Single Deck — broadcast operator workstation (Figma 182:2)
            # Phase D1: skeleton; D2 wires manual audio; D3 passes scheduler.
            from ui.studio import Studio
            self.studio = Studio(
                self._db, parent=None,
                engine=self._engine, scheduler=self._scheduler,
                instant_jingle_engine=self._instant_jingle_engine,
                sweeper_engine=self._sweeper_engine)
            self.studio.breadcrumb_clicked.connect(self._on_breadcrumb)
            # Standalone IJ screen → Studio live refresh. When the
            # operator assigns audio / renames a pad / tweaks a pallet
            # in ui/instant_jingles.py, Studio's tile grid picks up the
            # change immediately (no app restart, no navigate-back
            # required). _force_studio_refresh on showEvent is the
            # belt; this signal is the suspenders.
            self.instant_jingles.pads_changed.connect(
                self.studio._reload_instant_jingles)
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

            # Edit Playlist — Figma 248:2 premium screen. Takes engine
            # (preview wiring) + lazy studio injection (on-air check).
            from ui.playlist_edit import PlaylistEdit
            self.playlist_edit_screen = PlaylistEdit(
                self._db, scheduler=self._scheduler,
                engine=self._engine, parent=None)
            self.playlist_edit_screen.screen_requested.connect(
                self._on_hub_screen_requested)
            self._stack.addWidget(self.playlist_edit_screen)

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
        elif screen == "sweepers" and hasattr(self, "sweepers_library"):
            self._stack.setCurrentWidget(self.sweepers_library)
        elif screen == "jingles" and hasattr(self, "jingles_library"):
            self._stack.setCurrentWidget(self.jingles_library)
        elif screen == "stitcher" and hasattr(self, "stitcher"):
            self._stack.setCurrentWidget(self.stitcher)
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
        if screen == "libraries" or screen == "control_panel":
            # Both keys land on the Control Panel — "libraries" is the
            # FinalLog top tab, "control_panel" is the SettingsGeneral
            # breadcrumb crumb.
            if hasattr(self, "control_panel"):
                self._stack.setCurrentWidget(self.control_panel)
            return
        if screen == "songs" and hasattr(self, "songs_library"):
            # Play History's "Songs Library" breadcrumb crumb lands
            # here. Mirrors the ControlPanel card route in
            # _on_card_clicked so the user never sees a no-op click.
            self._stack.setCurrentWidget(self.songs_library)
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
        # screen_requested("playlist_edit:42") — Edit Playlist (Figma 248:2)
        if (screen.startswith("playlist_edit:")
                and hasattr(self, "playlist_edit_screen")):
            try:
                pid = int(screen.split(":", 1)[1])
            except (ValueError, IndexError):
                return
            # Lazy studio injection so on-air detection has a real ref
            if hasattr(self, "studio") and hasattr(
                    self.playlist_edit_screen, "set_studio"):
                self.playlist_edit_screen.set_studio(self.studio)
            self.playlist_edit_screen.load_for_id(pid)
            self._stack.setCurrentWidget(self.playlist_edit_screen)
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
        if screen == "final_log_creator" and hasattr(self, "final_log"):
            # Refresh counts + selected hour every time the screen is
            # shown so Studio playback that happened while elsewhere is
            # visible immediately.
            try:
                self.final_log.reload()
            except Exception as exc:
                log.warning(f"final_log reload failed: {exc}")
            if hasattr(self, "studio") and hasattr(
                    self.final_log, "set_studio"):
                self.final_log.set_studio(self.studio)
            self._stack.setCurrentWidget(self.final_log)
            return
        if screen == "settings" and hasattr(self, "settings_hub"):
            # "Settings" entry-points (top nav, footer link, scheduling
            # hub, FinalLog Settings tab, etc.) land on the hub. From
            # there, each option card emits its own screen key.
            self._stack.setCurrentWidget(self.settings_hub)
            return
        if (screen == "settings_general"
                and hasattr(self, "settings_general")):
            try:
                self.settings_general.reload()
            except Exception as exc:
                log.warning(f"settings reload failed: {exc}")
            self._stack.setCurrentWidget(self.settings_general)
            return
        if (screen == "settings_soundcard"
                and hasattr(self, "settings_soundcard")):
            try:
                self.settings_soundcard.reload()
            except Exception as exc:
                log.warning(f"soundcard reload failed: {exc}")
            self._stack.setCurrentWidget(self.settings_soundcard)
            return
        if (screen == "settings_studio"
                and hasattr(self, "settings_studio")):
            try:
                self.settings_studio.reload()
            except Exception as exc:
                log.warning(f"studio settings reload failed: {exc}")
            self._stack.setCurrentWidget(self.settings_studio)
            return
        # Everything else is a future scheduling sub-screen.
        from PyQt6.QtWidgets import QMessageBox
        labels = {
            "force_clocks":       "Force Clocks Schedule",
            "rebroadcast":        "Rebroadcast Schedule",
            "rds":                "RDS",
            "log_viewer":         "Log Viewer",
            "ai_magic":           "AI Magic",
        }
        title = labels.get(screen, screen)
        QMessageBox.information(
            self, title,
            f"{title} — coming soon.\n\nThis screen will be ported to "
            "the premium theme in a follow-up commit.")

    def _on_song_selected(self, song_id: int) -> None:
        log.info(f"Song selected: id={song_id}")
        # Track for downstream report actions (e.g. Play History
        # needs the currently-focused song id at the moment the
        # operator clicks the report tile).
        self._selected_song_id = int(song_id) if song_id else None

    def _on_play_song(self, song_id: int) -> None:
        log.info(f"Play song: id={song_id}")

    def _on_report_clicked(self, name: str) -> None:
        log.info(f"Report → {name}")
        if name == "play_history":
            sid = getattr(self, "_selected_song_id", None)
            if not sid:
                # No song selected — toast a friendly nudge.
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.information(
                    self, "Play History",
                    "Select a song from the list first, "
                    "then click Play History.")
                return
            if hasattr(self, "play_history"):
                try:
                    self.play_history.load_song(int(sid))
                except Exception as exc:
                    log.warning(f"play_history load_song failed: {exc}")
                self._stack.setCurrentWidget(self.play_history)
            return
        # Other report actions still bubble up as logs only — they're
        # the "Rotation Health / Last Played / Top Songs" tiles which
        # haven't been built yet.

    def _on_nav_clicked(self, tab: str) -> None:
        log.info(f"Nav → {tab}")
        # Top-nav routing — keep keys aligned with the labels rendered
        # in ControlPanel._build_top_nav (Control Panel / Scheduling /
        # Settings / Studio). Settings lands on the hub (Figma 426:3),
        # which routes onward to General / Soundcard / Studio sub-pages.
        if tab == "Settings" and hasattr(self, "settings_hub"):
            self._stack.setCurrentWidget(self.settings_hub)
        elif tab == "Scheduling" and hasattr(self, "scheduling_hub"):
            if hasattr(self, "studio") and hasattr(self.scheduling_hub,
                                                    "set_studio"):
                self.scheduling_hub.set_studio(self.studio)
            self._stack.setCurrentWidget(self.scheduling_hub)
        elif tab == "Control Panel" and hasattr(self, "control_panel"):
            self._stack.setCurrentWidget(self.control_panel)
        elif tab == "Studio":
            self._on_studio_clicked()

    def _on_studio_clicked(self) -> None:
        log.info("Open Studio →")
        if hasattr(self, "studio"):
            self._stack.setCurrentWidget(self.studio)

    def _on_settings_clicked(self) -> None:
        log.info("Settings →")
        if hasattr(self, "settings_hub"):
            self._stack.setCurrentWidget(self.settings_hub)

    def _on_stack_currentChanged(self, idx: int) -> None:
        """Resize the stack to match the active screen's footprint so
        the outer QScrollArea never lets the operator scroll into
        blank space past the screen's right or bottom edge.

        Most RadioAI screens are 1440×900 but Studio + Final Log are
        1920×1080 — without this resize the stack stayed at the
        largest (1920×1080) and 1440-wide screens left 480px of
        scrollable emptiness on the right.

        Safety: minimum 800×600 (matches MainWindow's setMinimumSize)
        so the stack never collapses to 0×0 if a widget reports a
        bogus size before its setFixedSize has applied."""
        if idx < 0:
            return
        if not hasattr(self, "_stack") or self._stack is None:
            return
        w = self._stack.widget(idx)
        if w is None:
            return
        # Prefer the explicit setFixedSize (min == max == widget size).
        # Fall back to widget.size() (post-show), then sizeHint.
        size = w.size()
        if size.width() <= 0 or size.height() <= 0:
            mn = w.minimumSize(); mx = w.maximumSize()
            if mn.width() > 0 and mn == mx:
                size = mn
            else:
                size = w.sizeHint()
        target_w = max(800, int(size.width() or 0))
        target_h = max(600, int(size.height() or 0))
        try:
            self._stack.setFixedSize(target_w, target_h)
        except Exception as exc:
            log.debug(f"stack resize failed: {exc}")

    def _on_studio_settings_saved(self) -> None:
        """SettingsStudio.settings_saved broadcaster. Pushes the
        operator's freshly-saved values into the live Studio screen
        via Studio._apply_studio_settings, so fade-out / fallback /
        master-volume changes take effect without an app restart."""
        if hasattr(self, "studio") and hasattr(
                self.studio, "_apply_studio_settings"):
            try:
                self.studio._apply_studio_settings()
            except Exception as exc:
                log.warning(
                    f"studio settings live-apply failed: {exc}")

    def _refresh_station_branding(self) -> None:
        """Re-read Settings().station_display + push it to every header
        station label across every mounted screen. Two cohorts:
          • QLabel-based headers tagged with objectName "hdr_station_lbl"
            — found via findChild, .setText() rewrites the cached string.
          • paintEvent-based headers (control_panel, studio, app_chrome
            phase-stub footer) — call .update() so the next paint cycle
            re-reads Settings() and re-renders.
        Triggered by SettingsGeneral.settings_saved."""
        from PyQt6.QtWidgets import QLabel
        try:
            from core.settings import Settings
            new_text = Settings().station_display or ""
        except Exception as exc:
            log.warning(f"branding refresh — Settings read failed: {exc}")
            return

        qlabel_screens = (
            "songs_library", "instant_jingles", "spots_commercials",
            "sweepers_library", "jingles_library", "stitcher",
            "settings_hub", "settings_soundcard", "settings_studio",
            "play_history",
        )
        for attr in qlabel_screens:
            screen = getattr(self, attr, None)
            if screen is None:
                continue
            lbl = screen.findChild(QLabel, "hdr_station_lbl")
            if lbl is not None:
                lbl.setText(new_text)

        # paintEvent-based screens — force a repaint so their header
        # re-renders with the new station_display.
        for attr in ("control_panel", "studio"):
            screen = getattr(self, attr, None)
            if screen is not None:
                screen.update()

        # FinalLog stores its label as a self attribute (not findChild)
        if hasattr(self, "final_log") and hasattr(
                self.final_log, "_station_lbl"):
            try:
                self.final_log._station_lbl.setText(new_text)
            except Exception:
                pass
        log.info(f"Station branding refreshed → {new_text!r}")

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
