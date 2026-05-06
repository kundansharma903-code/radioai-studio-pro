"""
RadioAI Studio Pro — Global Constants
All magic numbers, colors, and config values live here.
Never hardcode these anywhere else.
"""

import os

# ── App ───────────────────────────────────────────────────────────────────────
APP_NAME    = "RadioAI Studio Pro"
APP_VERSION = "2.0.0"
STATION     = "KISS FM 91.5"

# ── Window ────────────────────────────────────────────────────────────────────
# Raised to 1920×1080 to host the premium broadcast Studio (Figma 312:2).
# Pre-existing 1440×900 screens (Hub, Playlists, AutoSchedule, ClockEditor,
# PlaylistEdit, etc.) hard-code their own setFixedSize(1440,900) and render
# top-left-anchored inside the bigger MainWindow stack — visually correct,
# just letterboxed at the right and bottom on full-HD displays. Future
# polish: re-anchor to center, or upgrade each screen to 1920×1080 native.
WINDOW_W = 1920
WINDOW_H = 1080

# ── Colors (from Design.md) ───────────────────────────────────────────────────
BG_DEEPEST  = "#04050f"
BG_DARK     = "#070812"
BG_PANEL    = "#0a0b18"
BG_CARD     = "#0e1020"
BG_ELEVATED = "#131626"
BG_INTERACTIVE = "#1c1f38"

BORDER        = "#1c1f38"
BORDER_MEDIUM = "#252840"
BORDER_STRONG = "#454d6d"

TEXT_PRI   = "#f1f5ff"
TEXT_SEC   = "#8891b8"
TEXT_MUTED = "#454d6d"
TEXT_DIS   = "#252840"

CYAN   = "#06b6d4"
PURPLE = "#8b5cf6"
GREEN  = "#10b981"
AMBER  = "#f59e0b"
RED    = "#f43f5e"
PINK   = "#ec4899"

# Semi-transparent backgrounds for accent elements
CYAN_BG   = "#083344"
PURPLE_BG = "#1e1535"
GREEN_BG  = "#052e16"
AMBER_BG  = "#2d1a00"
RED_BG    = "#1f0a12"

# ── Audio — Jazler SOHO values ────────────────────────────────────────────────
POSITION_POLL_MS      = 250    # How often to poll VLC for position
PRELOAD_BEFORE_END_MS = 3000   # Pre-load next item this many ms before end
FADE_IN_MS            = 1000   # Song → fade in duration
FADE_OUT_MS           = 1000   # Song → fade out duration
SPOT_FADE_MS          = 0      # Spots: no fade (Jazler standard)
SPOT_TO_SONG_FADE_MS  = 1000   # After spot block: song fades in
AUTO_QUEUE_HOURS      = 2      # Pre-load 2 hours like Jazler SOHO auto

# ── Scheduling (from Jazler lessons) ─────────────────────────────────────────
SELECTION_RANDOMNESS = 0   # 0 = strict (all songs play before any repeat)
SAME_SONG_DAYS       = 7   # Song won't repeat for 7 days
SAME_SLOT_DAYS       = 3   # Song won't play same hour for 3 days
AD_LIMIT_MINS        = 15  # Max ad minutes per hour

# ── Paths ─────────────────────────────────────────────────────────────────────
_appdata = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
DB_PATH  = os.path.join(_appdata, "RadioAI", "radioai.db")
LOG_PATH = os.path.join(_appdata, "RadioAI", "logs")

# ── UI Geometry ───────────────────────────────────────────────────────────────
HEADER_H    = 44
STATUSBAR_H = 36
NAV_W_LEFT  = 300   # Studio: playlist queue panel
NAV_W_CENTER = 540  # Studio: now playing panel
NAV_W_RIGHT  = 598  # Studio: history + next break panel
