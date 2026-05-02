"""RadioAI Studio Pro — Libraries Tab

The main landing screen of the Control Panel. Shows:
- Page title + badges
- Now On Air bar
- 6 library cards (Songs, Instant Jingles, Spots, Jingles, Sweepers, Stitcher)
- Studio bar at the bottom
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QGridLayout, QPushButton, QScrollArea, QSizePolicy,
)
from PyQt6.QtCore import Qt, QTimer, QTime, pyqtSignal

from ui.theme import COLORS, LIBRARY_COLORS, LAYOUT, font, badge_style, rgba, GlowBackground, apply_card_glow


class LibraryCard(QFrame):
    """A single library card matching the Figma design."""

    clicked = pyqtSignal(str)

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.key = config["key"]
        self.accent = config["accent"]
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._build_ui(config)
        self._apply_style()
        apply_card_glow(self, self.accent)

    def _build_ui(self, c):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(8)

        # Row 1: Icon + Title + Badge
        top_row = QHBoxLayout()
        top_row.setSpacing(10)

        icon_label = QLabel(c["icon"])
        icon_label.setFont(font("bold", 18))
        icon_label.setStyleSheet(f"color: {self.accent}; background: transparent;")
        icon_label.setFixedWidth(28)
        top_row.addWidget(icon_label)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title = QLabel(c["title"])
        title.setFont(font("semibold", 15))
        title.setStyleSheet(f"color: {COLORS['t1']}; background: transparent;")
        subtitle = QLabel(c["subtitle"])
        subtitle.setFont(font("regular", 11))
        subtitle.setStyleSheet(f"color: {COLORS['t2']}; background: transparent;")
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        top_row.addLayout(title_col)

        top_row.addStretch()

        badge = QLabel(c["badge_text"])
        badge.setFont(font("semibold", 9))
        badge.setStyleSheet(f"""
            color: {self.accent};
            background-color: {rgba(self.accent, 0.15)};
            border-radius: 8px;
            padding: 2px 10px;
        """)
        top_row.addWidget(badge, alignment=Qt.AlignmentFlag.AlignTop)

        layout.addLayout(top_row)

        # Row 2: Count badge
        count_label = QLabel(c["count_text"])
        count_label.setFont(font("semibold", 10))
        count_label.setStyleSheet(f"""
            color: {COLORS['t1']};
            background-color: {rgba(self.accent, 0.2)};
            border-radius: 8px;
            padding: 2px 10px;
        """)
        count_label.setFixedHeight(20)
        count_label.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        layout.addWidget(count_label)

        layout.addSpacing(4)

        # Row 3: Description
        desc = QLabel(c["description"])
        desc.setFont(font("regular", 11))
        desc.setStyleSheet(f"color: {COLORS['t3']}; background: transparent;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        layout.addStretch()

        # Row 4: Bottom row — info chips + Open button
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(8)

        for chip_text in c.get("chips", []):
            chip = QLabel(chip_text)
            chip.setFont(font("medium", 10))
            chip.setStyleSheet(f"""
                color: {self.accent};
                background-color: {rgba(self.accent, 0.12)};
                border-radius: 8px;
                padding: 3px 10px;
            """)
            bottom_row.addWidget(chip)

        bottom_row.addStretch()

        open_btn = QPushButton("Open →")
        open_btn.setFont(font("medium", 11))
        open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        open_btn.setStyleSheet(f"""
            QPushButton {{
                color: {COLORS['t2']};
                background: transparent;
                border: none;
                padding: 4px 8px;
            }}
            QPushButton:hover {{
                color: {COLORS['t1']};
            }}
        """)
        open_btn.clicked.connect(lambda: self.clicked.emit(self.key))
        bottom_row.addWidget(open_btn)

        layout.addLayout(bottom_row)

    def _apply_style(self):
        self.setStyleSheet(f"""
            LibraryCard {{
                background-color: {COLORS['card']};
                border: 1px solid {rgba(self.accent, 0.3)};
                border-radius: {LAYOUT['border_radius_lg']}px;
            }}
            LibraryCard:hover {{
                border-color: {self.accent};
                background-color: {COLORS['card2']};
            }}
        """)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.key)
        super().mousePressEvent(event)


class LibrariesTab(QWidget):
    """Libraries tab — the default landing page of the Control Panel."""

    library_opened = pyqtSignal(str)

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self._build_ui()

    def _build_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        container = GlowBackground()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(28, 20, 28, 20)
        layout.setSpacing(16)

        layout.addWidget(self._build_page_header())
        layout.addWidget(self._build_now_on_air())
        layout.addLayout(self._build_cards_grid())
        layout.addWidget(self._build_studio_bar())

        scroll.setWidget(container)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    # ── Page Header ─────────────────────────────────────────────────────

    def _build_page_header(self):
        header = QWidget()
        header.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        title = QLabel("Libraries")
        title.setFont(font("bold", 28))
        title.setStyleSheet(f"color: {COLORS['t1']}; background: transparent;")

        subtitle = QLabel("Manage all your audio content")
        subtitle.setFont(font("regular", 13))
        subtitle.setStyleSheet(f"color: {COLORS['t2']}; background: transparent;")

        layout.addWidget(title)
        layout.addWidget(subtitle)

        # Badges row
        badges = QHBoxLayout()
        badges.setSpacing(10)

        stats = self.db.get_stats()

        lib_badge = QLabel("6 Libraries")
        lib_badge.setFont(font("medium", 11))
        lib_badge.setStyleSheet(f"""
            color: {COLORS['t1']};
            background-color: {COLORS['card2']};
            border: 1px solid {COLORS['b1']};
            border-radius: 10px;
            padding: 3px 12px;
        """)

        status_badge = QLabel("● System OK")
        status_badge.setFont(font("medium", 11))
        status_badge.setStyleSheet(f"""
            color: {COLORS['gn']};
            background-color: {COLORS['gnD']};
            border-radius: 10px;
            padding: 3px 12px;
        """)

        badges.addWidget(lib_badge)
        badges.addWidget(status_badge)
        badges.addStretch()
        layout.addLayout(badges)

        return header

    # ── Now On Air Bar ──────────────────────────────────────────────────

    def _build_now_on_air(self):
        bar = QFrame()
        bar.setFixedHeight(80)
        bar.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS['card']};
                border: 1px solid {COLORS['b1']};
                border-radius: {LAYOUT['border_radius_lg']}px;
            }}
        """)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(20, 12, 20, 12)
        layout.setSpacing(16)

        # NOW ON AIR label
        now_label = QLabel("NOW ON AIR")
        now_label.setFont(font("semibold", 9))
        now_label.setStyleSheet(f"""
            color: {COLORS['rs']};
            background: transparent;
            letter-spacing: 1px;
        """)

        # Song info
        info_col = QVBoxLayout()
        info_col.setSpacing(2)

        self.now_playing_title = QLabel("No song playing")
        self.now_playing_title.setFont(font("semibold", 16))
        self.now_playing_title.setStyleSheet(f"color: {COLORS['t1']}; background: transparent;")

        self.now_playing_meta = QLabel("Start the Studio to begin broadcasting")
        self.now_playing_meta.setFont(font("regular", 11))
        self.now_playing_meta.setStyleSheet(f"color: {COLORS['t3']}; background: transparent;")

        info_col.addWidget(now_label)
        info_col.addWidget(self.now_playing_title)
        info_col.addWidget(self.now_playing_meta)

        layout.addLayout(info_col)
        layout.addStretch()

        # Waveform placeholder
        waveform = QLabel("▁▂▃▅▇▅▃▂▁▂▃▅▇▅▃▂▁▂▃▅▇▅▃▂▁▂▃▅▇▅▃▂▁")
        waveform.setFont(font("mono", 14))
        waveform.setStyleSheet(f"color: {COLORS['p1']}; background: transparent;")
        layout.addWidget(waveform)

        layout.addStretch()

        # Countdown
        countdown_col = QVBoxLayout()
        countdown_col.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.countdown_label = QLabel("--:--")
        self.countdown_label.setFont(font("mono_bold", 28))
        self.countdown_label.setStyleSheet(f"color: {COLORS['gn']}; background: transparent;")

        remaining_label = QLabel("Remaining")
        remaining_label.setFont(font("regular", 10))
        remaining_label.setStyleSheet(f"color: {COLORS['t3']}; background: transparent;")
        remaining_label.setAlignment(Qt.AlignmentFlag.AlignRight)

        countdown_col.addWidget(self.countdown_label, alignment=Qt.AlignmentFlag.AlignRight)
        countdown_col.addWidget(remaining_label)

        layout.addLayout(countdown_col)

        return bar

    # ── Library Cards Grid ──────────────────────────────────────────────

    def _build_cards_grid(self):
        stats = self.db.get_stats()

        cards_data = [
            {
                "key": "songs",
                "icon": "♫",
                "title": "Songs",
                "subtitle": "Categories & Smart Rotation",
                "badge_text": "MAIN LIBRARY",
                "count_text": f"{stats['songs']} Songs Available",
                "description": "Full music library with AI-powered rotation,\nplay history analytics and category rules.",
                "chips": [f"{stats['categories']} Categories", "87% Health"],
                "accent": LIBRARY_COLORS["songs"],
            },
            {
                "key": "instant",
                "icon": "⚡",
                "title": "Instant Jingles",
                "subtitle": "Live Broadcast Pads",
                "badge_text": "LIVE TOOLS",
                "count_text": "0 Jingles • 1 Pallet",
                "description": "Quick-fire jingle pallets for live broadcast.\nPer-producer pallets, separate audio output.",
                "chips": ["1 Pallet", "Live Ready"],
                "accent": LIBRARY_COLORS["instant"],
            },
            {
                "key": "spots",
                "icon": "$",
                "title": "Spots & Commercials",
                "subtitle": "Ad Breaks & Priority System",
                "badge_text": "REVENUE",
                "count_text": f"{stats['campaigns_active']} Active Campaigns",
                "description": "Campaign management with break times,\npriorities, optional play & traffic sync.",
                "chips": ["4 Active", "Next: 22:00"],
                "accent": LIBRARY_COLORS["spots"],
            },
            {
                "key": "jingles",
                "icon": "♪",
                "title": "Jingles",
                "subtitle": "Station Identity Audio",
                "badge_text": "BRANDING",
                "count_text": f"{stats['jingles']} Jingles Available",
                "description": "Branding jingles organized by category.\nSchedule via clocks or playlists.",
                "chips": ["4 Categories", "Auto-Play"],
                "accent": LIBRARY_COLORS["jingles"],
            },
            {
                "key": "sweepers",
                "icon": "◈",
                "title": "Sweepers",
                "subtitle": "Audio Overlays on Songs",
                "badge_text": "PRODUCTION",
                "count_text": f"{stats['sweepers']} Sweepers Available",
                "description": "Play over songs at defined positions:\nstart, before intro, before end, bridge.",
                "chips": ["3 Positions", "Synced"],
                "accent": LIBRARY_COLORS["sweepers"],
            },
            {
                "key": "stitcher",
                "icon": "◆",
                "title": "The Stitcher",
                "subtitle": "Automated Audio Assembly",
                "badge_text": "AI POWERED",
                "count_text": "3 Active Modules",
                "description": "Auto-builds hooks, time announcements\nand news from prerecorded audio parts.",
                "chips": ["Hooks+Time", "+ News"],
                "accent": LIBRARY_COLORS["stitcher"],
            },
        ]

        grid = QGridLayout()
        grid.setSpacing(16)

        for i, data in enumerate(cards_data):
            card = LibraryCard(data)
            card.clicked.connect(self._on_card_clicked)
            row = i // 3
            col = i % 3
            grid.addWidget(card, row, col)

        return grid

    # ── Studio Bar ──────────────────────────────────────────────────────

    def _build_studio_bar(self):
        bar = QFrame()
        bar.setFixedHeight(100)
        bar.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS['card']};
                border: 1px solid {COLORS['b1']};
                border-radius: {LAYOUT['border_radius_lg']}px;
            }}
        """)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(20, 12, 20, 12)
        layout.setSpacing(16)

        # Studio icon + label
        studio_col = QVBoxLayout()
        studio_col.setSpacing(4)

        studio_title = QLabel("Studio")
        studio_title.setFont(font("bold", 24))
        studio_title.setStyleSheet(f"color: {COLORS['t1']}; background: transparent;")

        live_badge = QLabel("● LIVE NOW")
        live_badge.setFont(font("semibold", 9))
        live_badge.setStyleSheet(f"color: {COLORS['gn']}; background: transparent;")

        studio_label = QLabel("STUDIO")
        studio_label.setFont(font("semibold", 8))
        studio_label.setStyleSheet(f"""
            color: {COLORS['p1']};
            background: {COLORS['p4']};
            border-radius: 4px;
            padding: 2px 8px;
            letter-spacing: 1px;
        """)
        studio_label.setFixedWidth(60)

        studio_col.addWidget(studio_title)
        studio_col.addWidget(live_badge)
        studio_col.addWidget(studio_label)
        layout.addLayout(studio_col)

        # Now Playing info (in studio bar)
        np_col = QVBoxLayout()
        np_col.setSpacing(2)

        np_header = QLabel("NOW PLAYING")
        np_header.setFont(font("regular", 9))
        np_header.setStyleSheet(f"color: {COLORS['t3']}; background: transparent; letter-spacing: 1px;")

        np_artist = QLabel("---")
        np_artist.setFont(font("semibold", 14))
        np_artist.setStyleSheet(f"color: {COLORS['t1']}; background: transparent;")

        np_song = QLabel("No song loaded")
        np_song.setFont(font("regular", 11))
        np_song.setStyleSheet(f"color: {COLORS['t2']}; background: transparent;")

        np_col.addWidget(np_header)
        np_col.addWidget(np_artist)
        np_col.addWidget(np_song)
        layout.addLayout(np_col)

        layout.addStretch()

        # Next Break
        break_col = QVBoxLayout()
        break_col.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        break_header = QLabel("NEXT BREAK")
        break_header.setFont(font("regular", 9))
        break_header.setStyleSheet(f"color: {COLORS['t3']}; background: transparent; letter-spacing: 1px;")
        break_header.setAlignment(Qt.AlignmentFlag.AlignRight)

        break_time = QLabel("--:--")
        break_time.setFont(font("mono_bold", 28))
        break_time.setStyleSheet(f"color: {COLORS['am']}; background: transparent;")
        break_time.setAlignment(Qt.AlignmentFlag.AlignRight)

        break_col.addWidget(break_header)
        break_col.addWidget(break_time)
        layout.addLayout(break_col)

        layout.addSpacing(16)

        # Open Studio button
        open_btn = QPushButton("▶  Open\n    Studio")
        open_btn.setFont(font("semibold", 13))
        open_btn.setFixedSize(110, 60)
        open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        open_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['p1']};
                color: white;
                border: none;
                border-radius: {LAYOUT['border_radius_lg']}px;
                padding: 8px;
            }}
            QPushButton:hover {{
                background-color: {COLORS['p2']};
            }}
            QPushButton:pressed {{
                background-color: {COLORS['p3']};
            }}
        """)
        open_btn.clicked.connect(self._on_open_studio)
        layout.addWidget(open_btn)

        return bar

    # ── Slots ───────────────────────────────────────────────────────────

    def _on_card_clicked(self, key):
        self.library_opened.emit(key)

    def _on_open_studio(self):
        self.library_opened.emit("studio")
