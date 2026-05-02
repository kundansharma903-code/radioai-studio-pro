# 🚀 RADIOAI STUDIO PRO — MASTER CODING HANDOFF DOCUMENT
### Version 1.0 — Design Phase Complete — Ready to Code

---

## 📌 QUICK REFERENCE (read this first)

**Project:** RadioAI Studio Pro — AI-native Windows desktop radio
automation. PyQt6 + QtWebEngine front end, SQLite back end, VLC for
playback, Anthropic Claude (Sonnet 4) for the scheduler. Replaces
Jazler SOHO at KISS FM 91.5, Jaipur.

**Run it:**
```bash
cd C:\RadioAI
pip install -r requirements.txt    # first time only
python main.py
```

**Bootstrap a fresh DB from the canonical SQL files:**
```bash
python -m database.db_manager
```

**Key files:**
| Path                              | Purpose                                |
|-----------------------------------|----------------------------------------|
| `main.py`                         | App entry point + Windows sleep guard  |
| `ui/main_window.py`               | QMainWindow + QWebEngineView host      |
| `ui/bridge.py`                    | JS ↔ Python bridge (all API endpoints) |
| `ui/web/*.html`                   | One HTML file per screen               |
| `ui/theme.py`                     | Colour / font / layout constants       |
| `core/database.py`                | Live SQLite singleton (legacy schema)  |
| `core/ai_daily_scheduler.py`      | Midnight scheduler (background thread) |
| `core/auto_scheduler.py`          | Real-time clock → queue selection      |
| `core/audio_engine.py`            | VLC-based dual-deck playback           |
| `core/stitcher_engine.py`         | Hook-clip pre-mix engine (pydub)       |
| `core/sweeper_engine.py`          | Sweeper overlay engine                 |
| `database/schema.sql`             | Canonical schema (single source of truth) |
| `database/seeds.sql`              | Default categories, settings, admin user |
| `database/migrations/*.sql`       | Numbered migrations (001 … 004)        |
| `database/db_manager.py`          | File-driven DBManager (initialize, migrate, backup) |
| `radioai.spec` / `installer.iss`  | PyInstaller + Inno Setup build scripts |

**Database location:** `%LOCALAPPDATA%\RadioAI\radioai.db` (WAL +
foreign keys on). Backups → `%LOCALAPPDATA%\RadioAI\backups\*.db`.
The `radioai.db` file in the project root is a legacy stub — leave it
alone. The migration runner records applied files in `schema_migrations`.

**Architecture summary:**
- PyQt6 host loads HTML screens into a `QWebEngineView`. JavaScript
  calls Python via a `QWebChannel` bridge (`ui/bridge.py`) — no Flask
  in production despite what the blueprint suggests.
- A SQLite singleton (`core.database.DatabaseManager`) is the only DB
  accessor for the running app; `database.DBManager` is the
  file-driven equivalent for tooling and tests.
- Three engines run in background threads: AutoScheduler (queue),
  AIDailyScheduler (midnight build), BreakScheduler (ad breaks).
- Studio is a persistent WebView — switching tabs never reloads it,
  so audio plays seamlessly across navigation.

**Figma file:** `7oN9K61g94wKx3nu44KKDF`
(<https://www.figma.com/design/7oN9K61g94wKx3nu44KKDF>) — 36 screens,
canonical reference for every colour, dimension and layout.

**Known issues (v1.0.0):**
- Midnight trigger occasionally misses → 1 AM backup trigger handles it.
- `ai_decisions` table not fully populated by all decision paths
  (`ai_decisions_log` save fix pending).
- Unsigned installer triggers Windows SmartScreen — click *Run anyway*.
- AI Magic shows "0 songs" for empty categories until songs are
  assigned.
- The legacy `core.database` and the new `database/schema.sql` define
  overlapping tables. Both target the same DB file and both use
  `IF NOT EXISTS`, so they coexist safely; the schema file is the
  source of truth going forward.

---

## ⚡ HOW TO USE THIS DOCUMENT

Paste this at the start of every new coding session. The new chat will read this and continue exactly from where the last session ended. No re-explaining needed.

**Start every coding session with:**
> "I am continuing the RadioAI Studio Pro project. Here is the full handoff document: [paste this]. We are on Session X. Please read everything and continue."

---

## 👤 CLIENT & PROJECT

- **Client:** Kavish (kundansharma903@gmail.com)
- **Station:** KISS FM 91.5, Jaipur, Rajasthan, India
- **Software Name:** RadioAI Studio Pro
- **Purpose:** Windows desktop radio automation software — replacement for Jazler SOHO
- **Status:** Design phase 100% complete. Coding phase starting.
- **Client technical level:** Non-technical. He reviews and approves. Does not need to explain features.

---

## 🎨 FIGMA DESIGN FILE — SOURCE OF TRUTH

- **File Key:** `7oN9K61g94wKx3nu44KKDF`
- **URL:** https://www.figma.com/design/7oN9K61g94wKx3nu44KKDF
- **Total screens designed:** 36 screens
- **Use Figma MCP** at the start of every session to read exact colors, dimensions and layouts

**All 36 frames and their x positions:**
```
x=0       RadioAI — Control Panel (Libraries tab)
x=1500    Songs Library
x=3000    Add New Song — Dialog (y=90)
x=3000    Audio Cue Editor — Dialog (y=830)
x=3000    Song Categories Editor (y=1540)
x=3700    Broadcast Statistics
x=4900    Spots & Commercials
x=6340    Jingles Library
x=7780    Instant Jingles
x=9220    Sweepers Library
x=10660   The Stitcher
x=12100   Control Panel — Scheduling
x=13540   Control Panel — Settings
x=14980   Control Panel — AI Magic
x=16420   Clock Editor
x=17860   Playlists
x=19300   Force Clocks
x=20740   Final Log Creator
x=22180   Log Viewer
x=23620   Rebroadcast Schedule
x=25060   RDS Settings
x=26500   General Settings
x=27940   Soundcards
x=29380   Studio Settings
x=30820   Users & Security
x=32260   Database Settings
x=33700   Weather & API
x=35140   Studio — On Air  ← THE BIG ONE
```

---

## 🛠 TECH STACK — FINAL, NON-NEGOTIABLE

```
Language:     Python 3.11+
UI Framework: PyQt6
Database:     SQLite (via Python sqlite3)
Audio:        python-vlc (VLC media player bindings)
AI:           Anthropic Claude API (claude-sonnet-4-20250514)
Metadata:     mutagen (ID3 tags), librosa (BPM detection)
Packaging:    PyInstaller + Inno Setup → Windows .exe
Platform:     Windows 10/11 only
```

**Install command for client's machine:**
```bash
pip install pyqt6 python-vlc anthropic mutagen librosa pyinstaller
```

---

## 📁 COMPLETE FILE STRUCTURE

```
C:\RadioAI\
│
├── main.py
├── requirements.txt
├── CLAUDE.md
├── RadioAI.spec
│
├── core\
│   ├── __init__.py
│   ├── database.py
│   ├── audio_engine.py
│   ├── scheduler.py
│   ├── ai_engine.py
│   ├── broadcast_logger.py
│   ├── file_scanner.py
│   └── rds_encoder.py
│
├── models\
│   ├── __init__.py
│   ├── song.py
│   ├── campaign.py
│   ├── jingle.py
│   ├── clock.py
│   ├── break_schedule.py
│   ├── broadcast_log.py
│   ├── playlist.py
│   └── user.py
│
├── ui\
│   ├── __init__.py
│   ├── theme.py
│   ├── main_window.py
│   │
│   ├── control_panel\
│   │   ├── __init__.py
│   │   ├── control_panel.py
│   │   ├── libraries_tab.py
│   │   ├── scheduling_tab.py
│   │   ├── settings_tab.py
│   │   └── ai_magic_tab.py
│   │
│   ├── songs\
│   │   ├── __init__.py
│   │   ├── songs_library.py
│   │   ├── add_song_dialog.py
│   │   ├── audio_cue_editor.py
│   │   ├── categories_editor.py
│   │   └── broadcast_stats.py
│   │
│   ├── spots\
│   │   ├── __init__.py
│   │   ├── spots_library.py
│   │   ├── campaign_dialog.py
│   │   ├── break_editor.py
│   │   └── break_settings.py
│   │
│   ├── jingles\
│   │   ├── __init__.py
│   │   ├── jingles_library.py
│   │   ├── instant_jingles.py
│   │   ├── sweepers_library.py
│   │   └── stitcher.py
│   │
│   ├── scheduling\
│   │   ├── __init__.py
│   │   ├── clock_editor.py
│   │   ├── playlists.py
│   │   ├── force_clocks.py
│   │   ├── final_log_creator.py
│   │   ├── log_viewer.py
│   │   ├── rebroadcast.py
│   │   └── rds_settings.py
│   │
│   ├── settings\
│   │   ├── __init__.py
│   │   ├── general_settings.py
│   │   ├── soundcards.py
│   │   ├── studio_settings.py
│   │   ├── users_security.py
│   │   ├── database_settings.py
│   │   └── weather_api.py
│   │
│   ├── studio\
│   │   ├── __init__.py
│   │   ├── studio_screen.py
│   │   ├── deck_widget.py
│   │   ├── playlist_queue.py
│   │   ├── jingle_pads.py
│   │   └── vu_meter.py
│   │
│   └── widgets\
│       ├── __init__.py
│       ├── waveform_widget.py
│       ├── styled_button.py
│       ├── filter_dropdown.py
│       ├── toggle_switch.py
│       └── ai_badge.py
│
└── assets\
    ├── fonts\
    │   ├── Inter-Regular.ttf
    │   ├── Inter-Medium.ttf
    │   ├── Inter-SemiBold.ttf
    │   ├── Inter-Bold.ttf
    │   └── RobotoMono-Regular.ttf
    └── icons\
        └── radioai_icon.ico
```

---

## 🎨 DESIGN SYSTEM — EXACT VALUES

```python
COLORS = {
    "bg":    "#070812",
    "surf":  "#0A0C18",
    "panel": "#0E1020",
    "card":  "#131626",
    "card2": "#181B2E",
    "b1":    "#1C1F38",
    "b2":    "#252848",
    "p1":    "#8B5CF6",
    "p2":    "#A78BFA",
    "p3":    "#6D28D9",
    "p4":    "#1E1535",
    "gn":    "#10B981",
    "gnD":   "#052E16",
    "am":    "#F59E0B",
    "amD":   "#2D1A00",
    "rs":    "#F43F5E",
    "rsD":   "#1F0A12",
    "cy":    "#06B6D4",
    "cyD":   "#083344",
    "tl":    "#14B8A6",
    "tlD":   "#042F2A",
    "pk":    "#EC4899",
    "pkD":   "#3B0020",
    "t1":    "#F1F5FF",
    "t2":    "#8891B8",
    "t3":    "#454D6D",
    "t4":    "#252840",
}

LIBRARY_COLORS = {
    "songs":    "#8B5CF6",
    "spots":    "#10B981",
    "jingles":  "#F59E0B",
    "instant":  "#06B6D4",
    "sweepers": "#F43F5E",
    "stitcher": "#14B8A6",
}

FONTS = {
    "regular":   ("Inter", 400),
    "medium":    ("Inter", 500),
    "semibold":  ("Inter", 600),
    "bold":      ("Inter", 700),
    "mono":      ("Roboto Mono", 400),
    "mono_bold": ("Roboto Mono", 700),
}

LAYOUT = {
    "header_h":        72,
    "status_bar_h":    50,
    "left_panel_w":    220,
    "left_panel_w_lg": 240,
    "row_h_sm":        24,
    "row_h_md":        30,
    "row_h_lg":        36,
    "border_radius":   6,
    "border_radius_lg":10,
}
```

---

## 🗄 DATABASE SCHEMA — COMPLETE

```sql
CREATE TABLE IF NOT EXISTS songs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    artist TEXT NOT NULL,
    title TEXT NOT NULL,
    album TEXT,
    playlister_code TEXT,
    auto_code INTEGER UNIQUE,
    label TEXT,
    cd_key TEXT,
    barcode TEXT,
    songwriter TEXT,
    composer TEXT,
    comments TEXT,
    category_id INTEGER REFERENCES categories(id),
    era TEXT,
    vocal TEXT,
    priority INTEGER DEFAULT 1,
    year INTEGER,
    bpm INTEGER,
    energy TEXT,
    duration_ms INTEGER,
    file_path TEXT,
    is_enabled INTEGER DEFAULT 1,
    is_frozen INTEGER DEFAULT 0,
    entry_date TEXT DEFAULT (datetime('now')),
    start_point_ms INTEGER DEFAULT 0,
    intro_point_ms INTEGER DEFAULT 0,
    hook_in_ms INTEGER DEFAULT 0,
    hook_out_ms INTEGER DEFAULT 0,
    outro_point_ms INTEGER DEFAULT 0,
    mix_point_ms INTEGER DEFAULT 0,
    fade_in_ms INTEGER DEFAULT 0,
    fade_out_ms INTEGER DEFAULT 0,
    fade_out_position TEXT DEFAULT 'OFF',
    volume_level INTEGER DEFAULT 100,
    variable_length INTEGER DEFAULT 0,
    separation_minutes INTEGER DEFAULT 120,
    artist_sep_minutes INTEGER DEFAULT 30
);

CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    color TEXT DEFAULT '#8B5CF6',
    description TEXT,
    auto_rotate TEXT DEFAULT 'Rotate after 1 play',
    separation_min INTEGER DEFAULT 120,
    display_order INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS campaigns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    category TEXT DEFAULT 'Commercials',
    priority TEXT DEFAULT 'Medium',
    programming_mode TEXT DEFAULT 'Weekly',
    playback_order TEXT DEFAULT 'Rotation',
    start_date TEXT,
    end_date TEXT,
    contracted_plays_per_day INTEGER DEFAULT 3,
    is_active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS spot_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    file_path TEXT NOT NULL,
    duration_ms INTEGER,
    is_active INTEGER DEFAULT 1,
    display_order INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS break_schedule (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    break_time TEXT NOT NULL,
    day_mask INTEGER DEFAULT 127,
    break_duration_sec INTEGER DEFAULT 120,
    start_immediately INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS campaign_schedule (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER REFERENCES campaigns(id),
    day_of_week INTEGER,
    break_time TEXT,
    slot_order INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS jingles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    category TEXT DEFAULT 'Station ID',
    file_path TEXT,
    duration_ms INTEGER,
    properties TEXT,
    playlister_code TEXT,
    is_enabled INTEGER DEFAULT 1,
    display_order INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS jingle_pallets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    owner TEXT,
    grid_cols INTEGER DEFAULT 5,
    grid_rows INTEGER DEFAULT 6,
    audio_output INTEGER DEFAULT 4,
    display_order INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS jingle_pads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pallet_id INTEGER REFERENCES jingle_pallets(id) ON DELETE CASCADE,
    pad_index INTEGER NOT NULL,
    label TEXT,
    file_path TEXT,
    duration_ms INTEGER,
    color TEXT DEFAULT '#F59E0B',
    volume INTEGER DEFAULT 100,
    behaviour TEXT DEFAULT 'play_once'
);

CREATE TABLE IF NOT EXISTS sweepers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    category TEXT DEFAULT 'Station',
    file_path TEXT,
    duration_ms INTEGER,
    position TEXT DEFAULT 'Bridge at End',
    properties TEXT,
    playlister_code TEXT,
    is_enabled INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS clocks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    time_start TEXT,
    time_end TEXT,
    day_mask INTEGER DEFAULT 127,
    description TEXT,
    is_active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS clock_slots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    clock_id INTEGER NOT NULL REFERENCES clocks(id) ON DELETE CASCADE,
    slot_type TEXT NOT NULL,
    category_id INTEGER REFERENCES categories(id),
    energy_pref TEXT DEFAULT 'Any',
    vocal_pref TEXT DEFAULT 'Any',
    priority_pref TEXT DEFAULT 'Normal',
    separation_override INTEGER,
    position_minutes REAL,
    slot_order INTEGER NOT NULL,
    is_break INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS auto_schedule (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    clock_id INTEGER REFERENCES clocks(id),
    day_of_week INTEGER NOT NULL,
    hour_start INTEGER NOT NULL,
    hour_end INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS force_clocks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    clock_id INTEGER REFERENCES clocks(id),
    override_date TEXT NOT NULL,
    time_start TEXT DEFAULT '00:00',
    time_end TEXT DEFAULT '23:59',
    is_recurring INTEGER DEFAULT 0,
    recur_month INTEGER,
    recur_day INTEGER,
    is_active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS playlists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    playback_mode TEXT DEFAULT 'Ordered',
    on_finish TEXT DEFAULT 'Return to Clock',
    crossfade_sec INTEGER DEFAULT 3,
    scheduled_day TEXT,
    scheduled_time TEXT,
    is_active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS playlist_songs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    playlist_id INTEGER REFERENCES playlists(id) ON DELETE CASCADE,
    song_id INTEGER REFERENCES songs(id),
    position INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS final_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    log_date TEXT NOT NULL UNIQUE,
    is_locked INTEGER DEFAULT 0,
    generated_by TEXT DEFAULT 'AI',
    generated_at TEXT DEFAULT (datetime('now')),
    warning_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS final_log_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    log_id INTEGER NOT NULL REFERENCES final_logs(id) ON DELETE CASCADE,
    scheduled_time TEXT NOT NULL,
    entry_type TEXT NOT NULL,
    song_id INTEGER REFERENCES songs(id),
    campaign_id INTEGER REFERENCES campaigns(id),
    jingle_id INTEGER REFERENCES jingles(id),
    title_override TEXT,
    artist_override TEXT,
    duration_ms INTEGER,
    is_locked INTEGER DEFAULT 0,
    ai_flag TEXT,
    position INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS broadcast_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    played_at TEXT NOT NULL DEFAULT (datetime('now')),
    entry_type TEXT NOT NULL,
    song_id INTEGER REFERENCES songs(id),
    campaign_id INTEGER REFERENCES campaigns(id),
    jingle_id INTEGER REFERENCES jingles(id),
    scheduled_time TEXT,
    actual_time TEXT,
    duration_ms INTEGER,
    variance_ms INTEGER DEFAULT 0,
    deck TEXT DEFAULT 'A',
    was_manual INTEGER DEFAULT 0,
    operator TEXT DEFAULT 'AI AUTO'
);

CREATE TABLE IF NOT EXISTS ai_insights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    insight_type TEXT NOT NULL,
    entity_type TEXT,
    entity_id INTEGER,
    severity TEXT DEFAULT 'info',
    message TEXT NOT NULL,
    detail TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    is_dismissed INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    email TEXT,
    role TEXT DEFAULT 'DJ',
    password_hash TEXT,
    is_active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now')),
    last_login TEXT
);
```

---

## 🤖 AI ENGINE — ALL 10 FUNCTIONS

```python
# FUNCTION 1: Auto-fill Metadata
# Read ID3 tags via mutagen
# BPM: tempo, _ = librosa.beat.beat_track(y, sr)
# Energy: rms = librosa.feature.rms(y=y)[0].mean()
#   High if rms > 0.1, Medium if > 0.05, else Low
# Call Claude API for genre if tags missing

# FUNCTION 2: Overplay Alert
# plays_this_week > (7/rotation_days * 1.5)
# rotation_days = 3 (default)
# threshold = 7/3 * 1.5 = 3.5 → alert if 4+ plays in 7 days
# Query: SELECT COUNT(*) FROM broadcast_log
#        WHERE song_id=? AND played_at > datetime('now','-7 days')

# FUNCTION 3: Energy Match
# 06-10: High, 10-14: Medium-High, 14-18: Medium
# 18-22: High, 22-06: Low
# Compare song.energy vs preferred for current hour

# FUNCTION 4: Rotation Health
# health = (unique_songs_30d / total_songs) * 100
# <50% = Poor, 50-70% = Fair, >70% = Good

# FUNCTION 5: Similar Songs
# SELECT * FROM songs WHERE ABS(bpm-?) <= 15
# AND energy=? AND category_id=? AND id!=?

# FUNCTION 6: Break Conflict Detection
# Sum spot durations for each break
# Alert if total > break_duration_sec * 1.1

# FUNCTION 7: Campaign Delivery Monitor
# delivery = actual_plays_today / contracted_plays_per_day * 100
# URGENT if <80% with <3 days remaining
# WARNING if <90% with <7 days remaining

# FUNCTION 8: Optimal Break Time Suggestion
# Analyze historical overruns + library depth per hour

# FUNCTION 9: Smart Clock Builder
# If category health <50%: reduce slots
# If >90%: add slots. Check energy curve alignment.

# FUNCTION 10: Autonomous Daily Log (AUTO MODE)
# Per hour → get clock → per slot → select song
# Filter: separation time + overplay + energy match
# Pick song with lowest recent play count
# Fill breaks with campaigns by priority
# Edge cases → Claude API

# CLAUDE API CALL:
# model = "claude-sonnet-4-20250514"
# max_tokens = 1000
# system = "You are RadioAI scheduling AI for KISS FM 91.5 Jaipur"
```

---

## 🎵 AUDIO ENGINE — VLC BASED

```python
# Two VLC instances: deck_a (playing) + deck_b (loaded/ready)
# Crossfade: every 50ms timer
#   vol_a = 100 * (1 - progress)
#   vol_b = 100 * progress
#   progress = elapsed_ms / crossfade_duration_ms
# When progress >= 1.0: A stops, B becomes active
# Extract waveform: librosa.load() → downsample to 500 points
# VU levels: from VLC audio output
```

---

## 📋 SESSION-BY-SESSION CODING PLAN

### SESSION 1 — Foundation
Files: main.py, requirements.txt, core/database.py,
ui/theme.py, ui/main_window.py,
ui/control_panel/control_panel.py,
ui/control_panel/libraries_tab.py

Test: python main.py → Control Panel visible

### SESSION 2 — Songs Library
Files: core/audio_engine.py (basic),
models/song.py, models/category.py,
ui/songs/songs_library.py,
ui/songs/add_song_dialog.py,
ui/songs/audio_cue_editor.py,
ui/songs/categories_editor.py,
ui/songs/broadcast_stats.py,
ui/widgets/waveform_widget.py

Test: Songs Library opens, Add Song works

### SESSION 3 — Spots + Jingles + Sweepers + Stitcher
Files: models/campaign.py, models/jingle.py,
ui/spots/spots_library.py, ui/spots/campaign_dialog.py,
ui/jingles/jingles_library.py,
ui/jingles/instant_jingles.py,
ui/jingles/sweepers_library.py,
ui/jingles/stitcher.py

Test: All 6 library cards open correctly

### SESSION 4 — Scheduling
Files: core/scheduler.py, models/clock.py,
ui/scheduling/ (all 7 files)

Test: Create clock, generate log, view it

### SESSION 5 — Settings + AI Engine
Files: core/ai_engine.py (all 10 functions),
core/broadcast_logger.py, core/file_scanner.py,
ui/settings/ (all 6 files),
ui/control_panel/ (remaining 3 tabs)

Test: AI runs, settings save, insights appear

### SESSION 6 — Studio + Packaging
Files: ui/studio/ (all 5 files),
core/audio_engine.py (complete with crossfade),
RadioAI.spec, setup.iss

Test: Full broadcast — songs play, crossfade works,
AUTO MODE runs, .exe builds

---

## 🎯 CODING RULES

1. Every button is wired — no placeholders
2. All data from SQLite — no mock data after Session 1
3. AI uses exact formulas from this document
4. QSS styling matches Figma hex values exactly
5. PyQt6 layouts only — QVBoxLayout, QHBoxLayout, QSplitter
6. All signals connected to proper slots
7. try/except on all file and DB operations
8. AI engine and scheduler in QThread (no UI freeze)

---

## 👤 ABOUT KAVISH

- Non-technical, reviews and approves only
- Real production software for KISS FM 91.5 Jaipur
- Windows PC for testing
- Detail-oriented — will notice branding/color mistakes
- Wants real AI, not decorative AI
- All 36 screens designed and approved in Figma

---

## 🔖 SESSION STATUS LOG
(Update this after each session)

- [x] Session 1 — Foundation: NOT STARTED
- [ ] Session 2 — Songs Library: PENDING
- [ ] Session 3 — Libraries: PENDING
- [ ] Session 4 — Scheduling: PENDING
- [ ] Session 5 — Settings + AI: PENDING
- [ ] Session 6 — Studio + Build: PENDING

---

*RadioAI Studio Pro v1.0 — Design Complete April 2026*
*36 screens | ~12,000 lines estimated | 6 coding sessions*
