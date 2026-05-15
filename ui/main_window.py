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

        # SOTG Transcription Engine — QThread worker that listens for
        # fired SOTG drops, sends the audio to Gemini / OpenAI, and
        # persists a 4-line summary on the assignment row. Single
        # shared instance owned by MainWindow; the Studio dispatcher
        # emits sotg_drop_fired(aid) and the engine pulls audio + key
        # + adapter config from Settings on each job.
        from core.sotg_transcription_engine import SOTGTranscriptionEngine
        self._transcription_engine = SOTGTranscriptionEngine(
            db=self._db, parent=self)

        # AI Magic · Rotation AI Engine — QThread worker implementing
        # Time-Slot Freshness. Ticks every hour, pre-computes today's
        # song-rotation plan into ai_rotation_decisions. SchedulerEngine
        # consults its pick_song_for_clock() before falling back to
        # native random + separation (Phase E.5 wiring below). Engine
        # auto-starts but obeys Settings KEY_ENGINE_ENABLED — operator
        # can flip OFF from the Hub's Stop button anytime.
        from core.rotation_ai_engine import RotationAIEngine
        self._rotation_engine = RotationAIEngine(
            db=self._db, parent=self)

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

        # Auto-start broadcast on boot when the operator has toggled
        # 'Start in AUTO MODE automatically' (General Settings →
        # Startup & Behaviour, default ON). Single-shot timer fires
        # ~150ms after the GUI is fully painted so Studio's signal
        # plumbing is settled before the scheduler tries to dispatch.
        from PyQt6.QtCore import QTimer as _QTimer
        _QTimer.singleShot(150, self._apply_startup_auto_mode)

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
            # via Songs Library's detail-panel "Play History" tab; the
            # _on_report_clicked handler reads the currently-selected
            # song id off the songs_library + calls load_song().
            from ui.play_history import PlayHistory
            self.play_history = PlayHistory(self._db)
            self.play_history.breadcrumb_clicked.connect(
                self._on_hub_screen_requested)
            self.play_history.studio_clicked.connect(
                self._on_studio_clicked)
            self._stack.addWidget(self.play_history)

            # Category Performance (Figma 448:3) — per-category report.
            # Routed via Songs Library's "📊 Category Performance" tile
            # (was "📊 Play History" pre-this-session). Operator picks
            # a category in the filter dropdown, clicks the tile, and
            # _on_report_clicked reads songs_library.current_category_id()
            # before calling load_category().
            from ui.category_performance import CategoryPerformance
            self.category_performance = CategoryPerformance(self._db)
            self.category_performance.breadcrumb_clicked.connect(
                self._on_hub_screen_requested)
            self.category_performance.studio_clicked.connect(
                self._on_studio_clicked)
            self._stack.addWidget(self.category_performance)

            # Rotation Health (Figma 521:2) — Songs Library reports
            # tile "🎯 Rotation Health". Day-wise AI rotation audit
            # per category; rendered from ai_rotation_decisions joined
            # with categories + clocks + songs. Engine handle is
            # passed so the Refresh button can fire a synchronous tick.
            from ui.rotation_health import RotationHealthScreen
            self.rotation_health = RotationHealthScreen(
                db=self._db, engine=self._rotation_engine)
            self.rotation_health.breadcrumb_clicked.connect(
                self._on_hub_screen_requested)
            self.rotation_health.studio_clicked.connect(
                self._on_studio_clicked)
            self.rotation_health.back_clicked.connect(
                lambda: self._stack.setCurrentWidget(
                    self.songs_library))
            self._stack.addWidget(self.rotation_health)

            # AI Magic Hub (Figma 454:3) — landing page for the two AI
            # automation modules (Spot on the Go / Scheduling
            # Automation). Spot on the Go now routes to its own shell;
            # Scheduling Automation still toasts "coming soon".
            from ui.ai_magic_hub import AIMagicHub
            self.ai_magic_hub = AIMagicHub(self._db)
            self.ai_magic_hub.screen_requested.connect(
                self._on_hub_screen_requested)
            self.ai_magic_hub.studio_clicked.connect(
                self._on_studio_clicked)
            self._stack.addWidget(self.ai_magic_hub)

            # Spot on the Go shell (Figma 462:3) — 4-card landing for
            # the SOTG submodule (Create Schedule / Assign / Generate
            # Report / Assign API Key). Create Schedule now routes to
            # its own screen; remaining three still toast.
            from ui.spot_on_the_go_shell import SpotOnTheGoShell
            self.spot_on_the_go_shell = SpotOnTheGoShell(self._db)
            self.spot_on_the_go_shell.screen_requested.connect(
                self._on_hub_screen_requested)
            self.spot_on_the_go_shell.studio_clicked.connect(
                self._on_studio_clicked)
            self._stack.addWidget(self.spot_on_the_go_shell)

            # SOTG · Create Schedule (Figma 469:3) — first SOTG
            # sub-screen. Authors recurring show envelopes (RJ, show,
            # days, time slot, color, description, N link names).
            # The sharp-time/file/priority piece comes next in Assign.
            from ui.sotg_create_schedule import SOTGCreateSchedule
            self.sotg_create_schedule = SOTGCreateSchedule(self._db)
            self.sotg_create_schedule.screen_requested.connect(
                self._on_hub_screen_requested)
            self.sotg_create_schedule.studio_clicked.connect(
                self._on_studio_clicked)
            self._stack.addWidget(self.sotg_create_schedule)

            # SOTG · Assign (Figma 474:3) — Step 2. Per-day file +
            # sharp time + priority assignment for each link defined
            # in Create Schedule. Shares the AudioEngine for inline
            # preview (▶/■). Past-time guard enforced in both the
            # widget and db.upsert_sotg_assignment.
            from ui.sotg_assign import SOTGAssign
            self.sotg_assign = SOTGAssign(self._db, engine=self._engine)
            self.sotg_assign.screen_requested.connect(
                self._on_hub_screen_requested)
            self.sotg_assign.studio_clicked.connect(
                self._on_studio_clicked)
            self._stack.addWidget(self.sotg_assign)

            # SOTG · Generate Report (Figma 497:2) — Step 3. Daily play
            # log + PDF download. Background-saves the current day's
            # report at 23:59 via the minute tick wired below.
            from ui.sotg_generate_report import SOTGGenerateReport
            self.sotg_generate_report = SOTGGenerateReport(self._db)
            self.sotg_generate_report.screen_requested.connect(
                self._on_hub_screen_requested)
            self.sotg_generate_report.studio_clicked.connect(
                self._on_studio_clicked)
            self._stack.addWidget(self.sotg_generate_report)

            # SOTG · Assign API Key (Figma 503:3) — Step 4. Wires
            # Gemini / OpenAI keys to the SOTGTranscriptionEngine. The
            # engine then auto-summarises every FIRED drop into
            # ai_summary, which the report screen + PDF render as a
            # 4-line italic block under each link.
            from ui.sotg_assign_api_key import SOTGAssignAPIKey
            self.sotg_assign_api_key = SOTGAssignAPIKey(
                self._db, engine=self._transcription_engine)
            self.sotg_assign_api_key.screen_requested.connect(
                self._on_hub_screen_requested)
            self.sotg_assign_api_key.studio_clicked.connect(
                self._on_studio_clicked)
            self._stack.addWidget(self.sotg_assign_api_key)

            # AI Magic · Scheduling Automation Hub (Figma 511:3).
            # Phase E live wiring — passes the RotationAIEngine handle
            # so the hub renders live engine state + reacts to
            # tick_completed / engine_state_changed signals.
            from ui.scheduling_automation_hub import SchedulingAutomationHub
            self.scheduling_automation_hub = SchedulingAutomationHub(
                db=self._db, engine=self._rotation_engine)
            self.scheduling_automation_hub.screen_requested.connect(
                self._on_hub_screen_requested)
            self.scheduling_automation_hub.studio_clicked.connect(
                self._on_studio_clicked)
            self.scheduling_automation_hub.review_plan_clicked.connect(
                lambda: self._on_hub_screen_requested(
                    "review_daily_plan"))
            # Phase B mocks for button clicks (toast on action)
            self.scheduling_automation_hub.refresh_engine_clicked.connect(
                self._on_sched_ai_refresh)
            self.scheduling_automation_hub.stop_engine_clicked.connect(
                self._on_sched_ai_stop)
            self.scheduling_automation_hub.create_group_clicked.connect(
                self._on_sched_ai_create_group)
            self.scheduling_automation_hub.edit_group_clicked.connect(
                self._on_sched_ai_edit_group)
            self.scheduling_automation_hub.ungroup_clicked.connect(
                self._on_sched_ai_ungroup)
            self._stack.addWidget(self.scheduling_automation_hub)

            # AI Magic · Scheduling Daily Plan Review (Figma 512:2).
            # Approval gate for rotation AI's daily plan.
            from ui.scheduling_daily_plan_review import SchedulingDailyPlanReview
            self.scheduling_daily_plan_review = SchedulingDailyPlanReview(
                db=self._db)
            self.scheduling_daily_plan_review.screen_requested.connect(
                self._on_hub_screen_requested)
            self.scheduling_daily_plan_review.studio_clicked.connect(
                self._on_studio_clicked)
            self.scheduling_daily_plan_review.approve_clicked.connect(
                self._on_sched_ai_approve)
            self.scheduling_daily_plan_review.discard_clicked.connect(
                self._on_sched_ai_discard)
            self._stack.addWidget(self.scheduling_daily_plan_review)

            # Studio Single Deck — broadcast operator workstation (Figma 182:2)
            # Phase D1: skeleton; D2 wires manual audio; D3 passes scheduler.
            from ui.studio import Studio
            self.studio = Studio(
                self._db, parent=None,
                engine=self._engine, scheduler=self._scheduler,
                instant_jingle_engine=self._instant_jingle_engine,
                sweeper_engine=self._sweeper_engine)
            self.studio.breadcrumb_clicked.connect(self._on_breadcrumb)
            # SOTG drop FIRED → Transcription Engine enqueue. Real-time
            # post-FIRED summarisation (operator's Q1 = (a)).
            try:
                self.studio.sotg_drop_fired.connect(
                    self._transcription_engine.enqueue)
            except Exception as exc:
                log.warning(
                    f"sotg_drop_fired connect failed: {exc}")
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

            # SOTG daily-report midnight auto-save tick.
            # Ticks every 60s; fires _check_sotg_midnight_save() which is
            # idempotent (Settings sentinel "last_sotg_report_save_date").
            # Saves at HH:MM == 23:59 to capture the full day, with a
            # second chance at 00:00..00:05 the next morning if the
            # 23:59 tick was missed (app launched after midnight, etc.).
            from PyQt6.QtCore import QTimer
            self._sotg_save_timer = QTimer(self)
            self._sotg_save_timer.setInterval(60_000)
            self._sotg_save_timer.timeout.connect(
                self._check_sotg_midnight_save)
            self._sotg_save_timer.start()
            # One immediate check on boot — picks up a missed save if
            # the app starts at, say, 00:02 (yesterday's report still
            # needs to be written).
            QTimer.singleShot(2000, self._check_sotg_midnight_save)

            # Rotation AI · 5 PM auto-apply safety net (operator's Q7
            # Phase 2 contract). If the operator never approves or
            # discards today's rotation plan before 5 PM, the engine
            # auto-applies it so Studio's afternoon broadcast still
            # benefits from Time-Slot Freshness. Ticks every 60s,
            # idempotent via Settings sentinel "last_rotation_auto_apply_date".
            self._rotation_auto_apply_timer = QTimer(self)
            self._rotation_auto_apply_timer.setInterval(60_000)
            self._rotation_auto_apply_timer.timeout.connect(
                self._check_ai_rotation_auto_apply)
            self._rotation_auto_apply_timer.start()
            QTimer.singleShot(3000, self._check_ai_rotation_auto_apply)

            # Start the Rotation AI engine — hourly tick continuous
            # rotation balancing. Wire the SchedulerEngine to consult
            # rotation decisions before its native random+separation
            # pick (operator's Q4 = (b) safe fallback when AI off).
            try:
                self._scheduler.set_rotation_engine(self._rotation_engine)
            except (AttributeError, Exception) as exc:
                log.debug(
                    f"scheduler.set_rotation_engine wiring: {exc}")
            try:
                self._rotation_engine.start()
                log.info("RotationAIEngine started")
            except Exception as exc:
                log.warning(
                    f"RotationAIEngine start failed: {exc}")
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
        if (screen == "ai_magic"
                and hasattr(self, "ai_magic_hub")):
            self._stack.setCurrentWidget(self.ai_magic_hub)
            return
        if (screen == "spot_on_the_go"
                and hasattr(self, "spot_on_the_go_shell")):
            self._stack.setCurrentWidget(self.spot_on_the_go_shell)
            return
        if (screen == "scheduling_automation"
                and hasattr(self, "scheduling_automation_hub")):
            # AI Magic submodule 2 — rotation engine hub. Phase B mock
            # UI; engine wires in Phase D+E.
            try:
                self.scheduling_automation_hub.refresh()
            except Exception as exc:
                log.warning(
                    f"scheduling_automation_hub refresh failed: {exc}")
            self._stack.setCurrentWidget(self.scheduling_automation_hub)
            return
        if (screen == "review_daily_plan"
                and hasattr(self, "scheduling_daily_plan_review")):
            try:
                self.scheduling_daily_plan_review.refresh()
            except Exception as exc:
                log.warning(
                    f"scheduling_daily_plan_review refresh failed: {exc}")
            self._stack.setCurrentWidget(self.scheduling_daily_plan_review)
            return
        if (screen == "create_schedule"
                and hasattr(self, "sotg_create_schedule")):
            # SOTG Step 1 — refresh the table from DB on entry so any
            # external mutation (re-import, manual SQL) reflects.
            try:
                self.sotg_create_schedule._refresh_saved_shows()
            except Exception as exc:
                log.warning(
                    f"sotg_create_schedule refresh failed: {exc}")
            self._stack.setCurrentWidget(self.sotg_create_schedule)
            return
        if (screen == "assign"
                and hasattr(self, "sotg_assign")):
            # SOTG Step 2 — refresh shows + per-link assignments on
            # entry so creating a new show in Step 1 surfaces here
            # immediately.
            try:
                self.sotg_assign.refresh()
            except Exception as exc:
                log.warning(f"sotg_assign refresh failed: {exc}")
            self._stack.setCurrentWidget(self.sotg_assign)
            return
        if (screen == "generate_report"
                and hasattr(self, "sotg_generate_report")):
            # SOTG Step 3 — daily play log + PDF download.
            # Auto-refresh via showEvent inside the screen.
            try:
                self.sotg_generate_report.refresh()
            except Exception as exc:
                log.warning(
                    f"sotg_generate_report refresh failed: {exc}")
            self._stack.setCurrentWidget(self.sotg_generate_report)
            return
        if (screen == "assign_api_key"
                and hasattr(self, "sotg_assign_api_key")):
            # SOTG Step 4 — Gemini / OpenAI key + transcription engine.
            # Refresh activity log on entry so summaries fired while
            # elsewhere become visible.
            try:
                self.sotg_assign_api_key.refresh()
            except Exception as exc:
                log.warning(
                    f"sotg_assign_api_key refresh failed: {exc}")
            self._stack.setCurrentWidget(self.sotg_assign_api_key)
            return
        # Everything else is a future scheduling sub-screen.
        from PyQt6.QtWidgets import QMessageBox
        labels = {
            "force_clocks":       "Force Clocks Schedule",
            "rebroadcast":        "Rebroadcast Schedule",
            "rds":                "RDS",
            "log_viewer":         "Log Viewer",
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
        if name == "category_performance":
            # Category report — needs the Songs Library's currently-
            # selected category filter. "Category (All)" → no scope
            # → nudge the operator to pick one.
            cid = None
            if hasattr(self, "songs_library") and hasattr(
                    self.songs_library, "current_category_id"):
                try:
                    cid = self.songs_library.current_category_id()
                except Exception as exc:
                    log.warning(
                        f"current_category_id read failed: {exc}")
                    cid = None
            if not cid:
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.information(
                    self, "Category Performance",
                    "Pick a specific category from the Filters "
                    "dropdown first, then click "
                    "Category Performance.\n\n"
                    "(\"Category (All)\" doesn't scope the report.)")
                return
            if hasattr(self, "category_performance"):
                try:
                    self.category_performance.load_category(int(cid))
                except Exception as exc:
                    log.warning(
                        f"category_performance load failed: {exc}")
                self._stack.setCurrentWidget(self.category_performance)
            return
        if name == "rotation_health":
            # Songs Library reports tile → Rotation Health (Figma 521:2).
            # Refresh re-pulls the latest plan + decisions for the
            # currently-selected date (defaults to today).
            if hasattr(self, "rotation_health"):
                try:
                    self.rotation_health.refresh()
                except Exception as exc:
                    log.warning(
                        f"rotation_health refresh failed: {exc}")
                self._stack.setCurrentWidget(self.rotation_health)
            return
        # Other report actions still bubble up as logs only — they're
        # the "Last Played / Top Songs" tiles which haven't been
        # built yet.

    def _on_nav_clicked(self, tab: str) -> None:
        log.info(f"Nav → {tab}")
        # Top-nav routing — keep keys aligned with the labels rendered
        # in ControlPanel._build_top_nav (Libraries / Scheduling /
        # Settings / AI Magic ✦). Settings lands on the hub (Figma
        # 426:3); AI Magic lands on its own hub (Figma 454:3).
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
        elif tab == "AI Magic ✦" and hasattr(self, "ai_magic_hub"):
            # The ControlPanel emits the literal tab label including the
            # sparkle suffix — match it verbatim. Any other AI Magic
            # entry points (sibling screen header chips) route via
            # screen_requested("ai_magic") → _on_hub_screen_requested.
            self._stack.setCurrentWidget(self.ai_magic_hub)

    def _on_studio_clicked(self) -> None:
        log.info("Open Studio →")
        if hasattr(self, "studio"):
            self._stack.setCurrentWidget(self.studio)

    def _on_settings_clicked(self) -> None:
        log.info("Settings →")
        if hasattr(self, "settings_hub"):
            self._stack.setCurrentWidget(self.settings_hub)

    def _apply_startup_auto_mode(self) -> None:
        """Honour 'Start in AUTO MODE automatically' (General Settings
        → Startup & Behaviour). When the toggle is on, drive Studio
        through its canonical Play entry point — _on_play_clicked —
        which (a) starts the scheduler if idle, (b) picks the first
        deck-bound song for the current clock+hour, (c) flips
        _auto_advance_enabled so EOS keeps rolling. Result: songs
        start playing without the operator opening Studio or clicking
        Play.

        Skips silently when no clock is assigned to the current cell
        (the scheduler picker returns None) — the operator still has
        to assign a clock to the current hour via Main Auto Schedule
        for music to actually fire.

        Failures are non-fatal."""
        try:
            from core.settings import Settings
            on = Settings().get_bool("start_in_auto_mode", True)
        except Exception as exc:
            log.warning(f"startup auto-mode setting read failed: {exc}")
            return
        if not on:
            log.info("Startup auto-mode: setting is OFF — leaving "
                     "scheduler idle")
            return
        if not hasattr(self, "studio") or self.studio is None:
            log.warning("Startup auto-mode: Studio not mounted")
            return
        # Already playing? Don't disturb. Covers the edge case where
        # something else (e.g. a Stitcher block) is running at boot
        # finalisation time.
        if getattr(self.studio, "_playback_cid", None) is not None:
            log.info("Startup auto-mode: deck already busy — skipping")
            return
        try:
            self.studio._on_play_clicked()
            log.info("Startup auto-mode: Studio Play triggered")
        except Exception as exc:
            log.warning(f"Startup auto-mode dispatch failed: {exc}")

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

    # ── Scheduling Automation handlers (Phase E live wiring) ──────────

    def _on_sched_ai_refresh(self) -> None:
        """Manual re-tick — operator hit the Refresh button. Engine
        fires its compute_plan synchronously so the hub's stats +
        decisions repaint immediately via tick_completed signal."""
        if (hasattr(self, "_rotation_engine")
                and self._rotation_engine is not None):
            try:
                self._rotation_engine.tick()
            except Exception as exc:
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.warning(
                    self, "Refresh failed",
                    f"Rotation engine tick raised: {exc}")
                return
            # Hub's tick_completed handler already repaints

    def _on_sched_ai_stop(self) -> None:
        """Toggle the engine OFF — Settings sentinel flipped, engine
        thread keeps running (cheap heartbeat) but _on_tick exits
        early on is_enabled()=False."""
        from PyQt6.QtWidgets import QMessageBox
        ok = QMessageBox.question(
            self, "Stop AI Engine",
            "Stopping the engine reverts Studio to random + separation "
            "rotation for any song picks not yet decided. Re-enable "
            "anytime from Scheduling Automation.\n\nContinue?")
        if ok != QMessageBox.StandardButton.Yes:
            return
        from core.settings import Settings
        from core.rotation_ai_engine import KEY_ENGINE_ENABLED
        Settings().set(KEY_ENGINE_ENABLED, "0")
        if (hasattr(self, "_rotation_engine")
                and self._rotation_engine is not None):
            try:
                # Cycle state to OFF immediately so UI updates
                self._rotation_engine._set_state("OFF")
            except Exception:
                pass
        QMessageBox.information(
            self, "Engine stopped",
            "Rotation AI is OFF. Studio is back on manual rotation.")

    def _on_sched_ai_create_group(self) -> None:
        """Open the Sister Group Picker — fresh group, no preselection."""
        from ui.dialogs.sister_group_picker import SisterGroupPickerDialog
        dlg = SisterGroupPickerDialog(self._db, parent=self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            # Refresh hub's group section so the new group appears
            if hasattr(self, "scheduling_automation_hub"):
                try:
                    self.scheduling_automation_hub.reload_groups()
                except Exception as exc:
                    log.warning(
                        f"hub reload_groups failed: {exc}")

    def _on_sched_ai_edit_group(self, group_id: int) -> None:
        """Open the picker pre-loaded with this group's current members."""
        from ui.dialogs.sister_group_picker import SisterGroupPickerDialog
        dlg = SisterGroupPickerDialog(
            self._db, edit_group_id=int(group_id), parent=self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            if hasattr(self, "scheduling_automation_hub"):
                try:
                    self.scheduling_automation_hub.reload_groups()
                except Exception as exc:
                    log.warning(
                        f"hub reload_groups failed: {exc}")

    def _on_sched_ai_ungroup(self, group_id: int) -> None:
        """Delete a sister group. Confirmation gate — destructive op
        per CLAUDE.md."""
        from PyQt6.QtWidgets import QMessageBox
        ok = QMessageBox.question(
            self, "Delete Sister Group",
            f"Delete Sister Group {group_id}? Member categories "
            f"revert to standalone rotation (no sister pooling). "
            f"This does NOT delete the categories or their songs."
            f"\n\nContinue?")
        if ok != QMessageBox.StandardButton.Yes:
            return
        try:
            self._db.delete_sister_group(int(group_id))
        except Exception as exc:
            QMessageBox.warning(
                self, "Delete failed",
                f"Couldn't delete the group: {exc}")
            return
        if hasattr(self, "scheduling_automation_hub"):
            try:
                self.scheduling_automation_hub.reload_groups()
            except Exception as exc:
                log.warning(
                    f"hub reload_groups failed: {exc}")

    def _on_sched_ai_approve(self) -> None:
        """Approve today's plan — flip plan envelope to status=approved.
        Scheduler now treats today's decisions as authoritative (Phase
        E.5 hook reads this flag)."""
        from PyQt6.QtWidgets import QMessageBox
        from datetime import date as _date
        plan_date = _date.today().isoformat()
        try:
            plan = self._db.get_ai_rotation_plan(plan_date)
            if not plan:
                QMessageBox.information(
                    self, "Approve",
                    "No plan computed yet for today. Wait for the "
                    "engine's first tick (within an hour).")
                return
            self._db.mark_ai_rotation_plan_approved(plan_date)
        except Exception as exc:
            QMessageBox.warning(
                self, "Approve failed",
                f"DB write failed: {exc}")
            return
        QMessageBox.information(
            self, "Plan approved",
            "Today's AI rotation plan is now live. Studio's next song "
            "picks will use AI's decisions.")
        if hasattr(self, "scheduling_automation_hub"):
            self._stack.setCurrentWidget(self.scheduling_automation_hub)

    def _on_sched_ai_discard(self) -> None:
        """Discard today's plan — wipes decisions + flips status to
        'discarded'. Engine will compute again on next tick."""
        from PyQt6.QtWidgets import QMessageBox
        from datetime import date as _date
        ok = QMessageBox.question(
            self, "Discard Plan",
            "Discard today's AI plan? Decisions will be wiped. "
            "The engine will compute a fresh plan on its next "
            "hourly tick. Studio reverts to random + separation "
            "in the meantime.\n\nContinue?")
        if ok != QMessageBox.StandardButton.Yes:
            return
        plan_date = _date.today().isoformat()
        try:
            self._db.mark_ai_rotation_plan_discarded(plan_date)
        except Exception as exc:
            QMessageBox.warning(
                self, "Discard failed",
                f"DB write failed: {exc}")
            return
        if hasattr(self, "scheduling_automation_hub"):
            try:
                self.scheduling_automation_hub.refresh()
            except Exception:
                pass
            self._stack.setCurrentWidget(
                self.scheduling_automation_hub)

    def _check_ai_rotation_auto_apply(self) -> None:
        """60s tick — at or after 17:00 (5 PM), auto-apply today's
        rotation plan if the operator hasn't yet approved or discarded
        it. Operator's Q7 Phase 2 safety net: "walk away" path —
        Daily Plan Review's preview gate doesn't block the afternoon
        broadcast if the operator never opens the screen.

        Idempotent via the Settings sentinel "last_rotation_auto_apply_date".
        Only flips status from 'pending' → 'auto_applied' — never
        overrides an already-approved or already-discarded plan."""
        try:
            from datetime import datetime as _dt, date as _ddate
            from core.settings import Settings as _Settings
            now = _dt.now()
            if now.hour < 17:
                return    # too early
            today = _ddate.today().isoformat()
            sent_key = "last_rotation_auto_apply_date"
            stamped = _Settings().get(sent_key, "") or ""
            if stamped == today:
                return    # already auto-applied (or attempted) today
            plan = self._db.get_ai_rotation_plan(today)
            if not plan:
                return    # engine hasn't ticked today
            status = (plan.get("status") or "").lower()
            if status != "pending":
                # Operator already decided (approved/discarded) or
                # auto-applied — stamp the sentinel so we don't poll
                # forever today, then return.
                _Settings().set(sent_key, today)
                return
            self._db.mark_ai_rotation_plan_auto_applied(today)
            _Settings().set(sent_key, today)
            log.info(
                f"[rotation-ai] 5 PM auto-apply fired — plan {today} "
                f"flipped pending → auto_applied")
            # Refresh visible Rotation Health / Hub screens
            for attr in ("rotation_health",
                          "scheduling_automation_hub",
                          "scheduling_daily_plan_review"):
                screen = getattr(self, attr, None)
                if screen is not None and hasattr(screen, "refresh"):
                    try:
                        screen.refresh()
                    except Exception:
                        pass
        except Exception as exc:
            log.warning(f"rotation auto-apply check failed: {exc}")

    def _check_sotg_midnight_save(self) -> None:
        """60s tick — at 23:59 (or any time on the morning after if we
        missed it), persist the previous broadcast day's SOTG daily
        report to disk. Idempotent via a Settings sentinel keyed by
        the report date itself, so retries through the day are safe."""
        try:
            from datetime import datetime as _dt, date as _ddate, timedelta
            from core.settings import Settings as _Settings
            from core.reports.sotg_daily_report import (
                generate_sotg_daily_report,
            )
            now = _dt.now()
            today = _ddate.today()
            # Decide which date to save:
            #   • 23:59 → today (full day captured up to 23:59:00)
            #   • 00:00..00:05 → yesterday (catch-up if 23:59 was missed)
            target: _ddate
            if now.hour == 23 and now.minute >= 59:
                target = today
            elif now.hour == 0 and now.minute <= 5:
                target = today - timedelta(days=1)
            else:
                return    # not in the save window
            sent_key = "last_sotg_report_save_date"
            stamped = _Settings().get(sent_key, "") or ""
            if stamped == target.isoformat():
                return    # already saved for this target date
            path = generate_sotg_daily_report(target, db=self._db)
            _Settings().set(sent_key, target.isoformat())
            _Settings().set(
                "last_sotg_report_save_at",
                now.strftime("%d %b, %I:%M %p"))
            log.info(
                f"[sotg auto-save] target={target.isoformat()} → {path}")
            # Refresh the screen footer if it's mounted + visible
            if hasattr(self, "sotg_generate_report"):
                try:
                    self.sotg_generate_report._refresh_last_save_label()
                except Exception:
                    pass
        except Exception as exc:
            log.warning(f"sotg midnight save failed: {exc}")

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
            "play_history", "category_performance", "ai_magic_hub",
            "spot_on_the_go_shell", "sotg_create_schedule",
            "sotg_assign", "sotg_generate_report",
            "sotg_assign_api_key",
            "scheduling_automation_hub", "scheduling_daily_plan_review",
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
        # 0a. Stop the Rotation AI engine — QThread worker must not
        # outlive the QApplication.
        if (hasattr(self, "_rotation_engine")
                and self._rotation_engine is not None):
            try:
                self._rotation_engine.shutdown()
                log.info("RotationAIEngine shutdown done")
            except Exception as exc:
                log.warning(
                    f"rotation engine shutdown failed: {exc}")

        # 0b. Stop the transcription engine's QThread worker so it
        # doesn't outlive the QApplication. Idempotent; safe to call
        # even if it was never started.
        if (hasattr(self, "_transcription_engine")
                and self._transcription_engine is not None):
            try:
                self._transcription_engine.shutdown()
                log.info("SOTGTranscriptionEngine shutdown done")
            except Exception as exc:
                log.warning(
                    f"transcription engine shutdown failed: {exc}")

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
