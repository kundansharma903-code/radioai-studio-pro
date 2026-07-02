# RadioAI Studio Pro — Complete Blueprint
**Version:** 1.0.0  
**Station:** KISS FM 91.5 / EST FM / FCP  
**Location:** Jaipur / Sikar, Rajasthan, India  
**Developer:** Kavish  
**Built With:** PyQt6 + Python + SQLite + Claude AI + VLC

---

## Table of Contents
1. [Project Overview](#1-project-overview)
2. [Tech Stack](#2-tech-stack)
3. [Architecture](#3-architecture)
4. [Database Schema](#4-database-schema)
5. [Screen-by-Screen Features](#5-screen-by-screen-features)
6. [AI Engine](#6-ai-engine)
7. [Audio Engine](#7-audio-engine)
8. [API Endpoints](#8-api-endpoints)
9. [Figma Design Reference](#9-figma-design-reference)
10. [Packaging & Distribution](#10-packaging--distribution)
11. [Future Roadmap](#11-future-roadmap)

---

## 1. Project Overview

RadioAI Studio Pro is a **fully AI-native Windows desktop radio automation software** — a direct Jazler SOHO competitor built from scratch. It replaces manual radio scheduling with an intelligent AI engine that plans, rotates, and manages broadcasts automatically.

### Core Philosophy
```
Traditional Radio:
Human → Manual schedule → Radio plays → 
Same songs repeat → Listener bored

RadioAI:
AI midnight → Auto schedule → Fresh rotation → 
Professional sound → Zero manual work
```

### What Makes It Different
- AI schedules the entire next day at midnight automatically
- Smart song rotation — same song never repeats within 7 days
- Same time slot protection — song won't play at same hour for 3 days
- Real-time ad monitoring with 15-min/hour policy enforcement
- Jazler-style 24×7 clock grid scheduling
- Complete broadcast history tracking

---

## 2. Tech Stack

| Component | Technology |
|-----------|-----------|
| UI Framework | PyQt6 (Python) |
| Web UI | HTML + CSS + JavaScript |
| Audio Engine | python-vlc (VLC media player) |
| Database | SQLite |
| AI API | Claude API (claude-sonnet-4-20250514) |
| Audio Processing | pydub |
| Metadata Reading | mutagen |
| Web Server | Flask + Waitress |
| Packaging | PyInstaller + Inno Setup |
| Platform | Windows 10/11 only |
| Design | Figma |

---

## 3. Architecture

```
┌─────────────────────────────────────────────────────┐
│                  RadioAI Studio Pro                  │
├─────────────┬───────────────────────┬───────────────┤
│  PyQt6 UI   │    Python Backend     │  SQLite DB    │
│  (WebView)  │    (Flask Server)     │  (radioai.db) │
├─────────────┴───────────────────────┴───────────────┤
│                    Core Engines                      │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────┐ │
│  │   Audio     │  │  AutoSched   │  │  AI Daily  │ │
│  │   Engine    │  │   uler       │  │ Scheduler  │ │
│  │  (VLC)      │  │              │  │ (Midnight) │ │
│  └─────────────┘  └──────────────┘  └────────────┘ │
│  ┌─────────────┐  ┌──────────────┐                  │
│  │  Stitcher   │  │   Sweeper    │                  │
│  │   Engine    │  │   Engine     │                  │
│  └─────────────┘  └──────────────┘                  │
└─────────────────────────────────────────────────────┘
```

### File Structure
```
C:\RadioAI\
├── main.py                    # App entry point
├── radioai.spec               # PyInstaller spec
├── installer.iss              # Inno Setup script
├── core\
│   ├── auto_scheduler.py      # Clock→Queue engine
│   ├── ai_daily_scheduler.py  # Midnight AI engine
│   ├── stitcher_engine.py     # Hook/preview engine
│   └── sweeper_engine.py      # Sweeper overlay engine
├── ui\
│   ├── main_window.py         # PyQt6 main window
│   ├── bridge.py              # JS↔Python bridge
│   └── web\
│       ├── studio_screen.html
│       ├── songs_library.html
│       ├── spots_library.html
│       ├── jingles_library.html
│       ├── sweepers_library.html
│       ├── scheduling_screen.html
│       ├── main_auto_schedule.html
│       ├── clock_editor.html
│       └── ai_magic.html
└── assets\
    └── radioai.ico
```

---

## 4. Database Schema

### Core Tables

```sql
-- Songs library
songs (
  id, title, artist, album, year,
  duration_ms, bpm, energy, vocal,
  category_id, file_path, enabled,
  cue_start, intro_end, hook_in, 
  hook_out, outro_start, mix_point,
  fade_in_ms, fade_out_ms,
  last_played, play_count,
  created_at
)

-- Song categories
song_categories (
  id, name, color, description
)

-- Spots/Commercials
spots (
  id, name, file_path, duration_ms,
  campaign_id, category, enabled
)

-- Ad campaigns
campaigns (
  id, name, category, priority,
  start_date, end_date, 
  programming_mode, playback_order,
  created_at
)

-- Jingles
jingles (
  id, name, file_path, duration_ms,
  category, enabled
)

-- Sweepers
sweepers (
  id, name, file_path, duration_ms,
  category, enabled
)

-- Clocks (rotation templates)
clocks (
  id, name, color,
  time_start, time_end,
  comments, created_at
)

-- Clock slots (what plays in each clock)
clock_slots (
  id, clock_id, position,
  slot_type,     -- song/jingle/spot/sweeper
  category_id, energy, vocal,
  priority, separation,
  sweeper_position,  -- START_OF_SONG/BEFORE_INTRO/etc
  created_at
)

-- 24x7 schedule grid
clock_schedule (
  id, clock_id,
  day_of_week,  -- 0=Mon, 6=Sun
  hour          -- 0-23
)

-- Scheduling rules
scheduling_rules (
  id, rule_name, rule_value, updated_at
  -- same_song_days = 7
  -- same_slot_days = 3
  -- selection_randomness = 0
)
```

### AI Tables

```sql
-- AI generated daily schedule
ai_daily_log (
  id, schedule_date, hour, position,
  song_id, slot_type, generated_at,
  status  -- scheduled/played/skipped
)

-- AI schedule status per day
ai_schedule_status (
  id, schedule_date UNIQUE,
  status,           -- done/failed/pending
  generated_at,
  warnings_count,
  songs_scheduled,
  error_message
)

-- AI warnings
ai_schedule_warnings (
  id, schedule_date,
  warning_type, category_name,
  message, severity  -- info/warning/critical
)

-- AI step-by-step log
ai_scheduler_log (
  id, run_date, step_time,
  step_label, step_detail, status
)

-- AI decisions log
ai_decisions_log (
  id, run_date, decision_time,
  decision_type, song_id,
  message, color
)
```

### Broadcast History

```sql
-- Every play logged here
broadcast_log (
  id, entry_type,    -- song/spot/jingle/sweeper/stitcher
  song_id, campaign_id, jingle_id,
  duration_ms, played_at
)
```

---

## 5. Screen-by-Screen Features

### 5.1 Studio Screen
**File:** `studio_screen.html`  
**Purpose:** Main on-air broadcast control

#### Features
- **Dual Deck A/B** — Crossfade between songs
- **Waveform display** — Visual audio timeline
- **Now Playing** — Artist, title, category, BPM, energy
- **Playlist Queue** — Next 14 items with scheduled times
- **AUTO MODE** — AI-driven automatic playback
- **Jingle Pads** — N25-N30 instant jingle buttons
- **Stitcher Panel** — Hook preview sequences
- **History Panel** — Last 6 played songs
- **Next Break** — Upcoming ad break countdown
- **AI Insights** — Real-time recommendations

#### Key Behaviors
```
AUTO MODE ON:
1. Check ai_daily_log for current hour
2. If AI schedule exists → use it
3. If not → AutoScheduler real-time
4. Queue always has 3+ songs ahead
5. Hour change → reload from new clock
6. Status: "Morning Drive (09:00)" green
          "No clock — fallback" amber
```

---

### 5.2 Songs Library
**File:** `songs_library.html`

#### Features
- Song list with Artist, Title, Duration, Category
- **Filters:** Category, Energy, Vocal, BPM, Year, Search
- **Add New Song** dialog
- **Mass Import** — folder scan, auto metadata
- **Audio Cue Editor** — Set START, INTRO, HOOK IN/OUT, OUTRO, MIX POINT
- **Broadcast Analytics** — Play history chart
- **AI Insights** — Overplay alerts, similar songs, rotation health
- **Song Separation Settings** — Per-song rules
- **Categories Editor** — Create/edit categories with colors

#### Filters
```
Category dropdown → All categories from DB
Energy → High / Medium / Low / Any
Vocal → Male / Female / Any
BPM Min/Max → Range filter
Year Min/Max → Range filter
Search → Artist OR Title
```

---

### 5.3 Audio Cue Editor
**File:** Embedded in Songs Library

#### Markers
| Marker | Color | Purpose |
|--------|-------|---------|
| START | Green | Skip silence, true audio start |
| INTRO | Cyan | Intro end — sweeper BEFORE_INTRO fires here |
| HOOK IN | Cyan | Stitcher clip start |
| HOOK OUT | Cyan | Stitcher clip end |
| OUTRO | Amber | Song ending begins — sweeper BEFORE_END fires |
| MIX POINT | Red | Next song starts crossfading here |

#### Controls
- `<<` `>>` — 0.1 second fine adjustment
- **PREVIEW** — Play from that point
- **RESET** — Default position
- **AutoCue** — AI auto-detect all points
- **Fade In/Out sliders** — 0ms to 5000ms
- **Normalize** — Auto volume leveling
- **Variable Length** — Use exact file duration

---

### 5.4 Spots & Commercials
**File:** `spots_library.html`

#### Left Panel
- Campaign list (15 campaigns shown)
- Add/Edit/Delete campaign
- Break Settings
- Filters: Category, Priority, Day
- Reports: Actual Play Times, Spot Schedule, Daily Programming, Break Duration Check, Traffic Integration

#### Center Panel
- Campaign details table
- Spot files per campaign
- Weekly break schedule grid

#### Right Panel — AI Monitor (NEW)
```
THIS HOUR AD USAGE:
"8.5 min / 15 min ✅"
Green(<12) Amber(12-14) Red(15+)

HOURLY BROADCAST BREAKDOWN:
Donut pie chart:
- Songs: 45 min (75%)
- Ads: 8.5 min (13%)
- Jingles: 3 min (5%)
- Sweepers: 2 min (3%)

TODAY'S HOURLY TREND:
16-hour bar chart
Red dotted line at 15 min limit

CLIENT AD ROTATION:
Tabs: This Hour | Last 7 Days
Columns: Rank, Client, Rotations, 
         Min/Hour, 7-Day Total, Status
Sort: HIGH → MEDIUM → LOW

AI INSIGHT BAR:
"FreshBurst Cola 4.2 min/hr — 
 consider reducing"
```

#### Spot Playback Rules (Jazler Standard)
```
Spots play START to END (no cue points)
No fade out on spots
Pre-load next item 2 sec before end
Song→Spot: song fades out 1 sec
Spot→Song: song fades in 1 sec
Spot→Spot: 0ms gap (seamless)
```

---

### 5.5 Jingles Library
**File:** `jingles_library.html`

- Jingle list with duration
- Category organization
- Instant play from library
- Add/Edit/Delete

---

### 5.6 Sweepers Library
**File:** `sweepers_library.html`

- Sweeper list with duration
- Position type setting:
  - **BEFORE_INTRO** — Ends when song intro ends
  - **START_OF_SONG** — Plays before song starts (standalone)
  - **BEFORE_END** — Fires at outro point
  - **BRIDGE_AT_END** — Half at end, half at start of next
  - **INDEPENDENT** — Plays standalone
  - **CUSTOM** — User-defined milliseconds

---

### 5.7 Scheduling Screen
**File:** `scheduling_screen.html`

#### Top Badges
- `7 Clocks Built` (cyan)
- `Log Ready` (green)
- `⚡ SOHO Auto` (purple)

#### AI Daily Scheduler Card
```
STATE — Done:
✅ Today's scheduling is done
Generated: 12:03 AM • 247 songs
0 warnings
[View Schedule →]

STATE — Not Done:
⚠️ No scheduling done for today
Using real-time selection
Next: Tonight 12:00 AM
[Generate Now 🔄]

STATE — With Warnings:
⚠️ Done • 2 Warnings
• Morning Vibes: only 8 songs
• Evening: 1 repeat forced
[Fix Warnings] [View Schedule]

STATE — Failed:
🔴 Scheduling Failed
Error: [message]
Fallback: Real-time active
[Retry Now 🔄]
```

#### 6-Slot Weekly Grid
| Slot | Time | Color |
|------|------|-------|
| Night | 00:00-06:00 | Dark |
| Morning | 06:00-10:00 | Cyan |
| Daytime | 10:00-14:00 | Purple |
| Afternoon | 14:00-18:00 | Amber |
| Evening | 18:00-22:00 | Green |
| Late Night | 22:00-00:00 | Red |

#### Module Cards
1. **Clock Editor** — Build rotation clocks
2. **Final Log** — Generate broadcast log
3. **Force Clocks** — Override for specific dates
4. **Playlists** — Manual song sequences
5. **Log Viewer** — View/edit generated logs
6. **Rebroadcast** — Schedule reruns
7. **RDS Settings** — Radio Data System config

#### Song Separation Rules
```
Same Artist:        2 hours
Same Song:          7 days
Same Category:      30 mins
Artist Title Sep:   1 hour
Vocal Type:         Alternate
Selection Randomness: 0 (strict)
```

---

### 5.8 Main Auto Schedule
**File:** `main_auto_schedule.html`  
**Figma Node:** 161:2

#### Jazler-Style 24×7 Grid
- Left panel: Available clocks list
- **SET ▶▶** button (red) — assign clock to selected cells
- 24 rows (00:00-23:00) × 7 columns (Mon-Sun)
- Color-coded cells per clock type
- Today's column highlighted
- Click cell → select | Drag → multi-select
- Right-click → "Assign Clock" / "Clear Cell"
- Tabs: Weekdays | Specific Days

---

### 5.9 Clock Editor
**File:** `clock_editor.html`  
**Figma Node:** 165:2

#### Left Panel — Library Filter
- **Type Tabs:** Songs | Jingles | Spots | Sweepers | Events
- **Sub-tabs:** Category | Specific Song | Specific Artist
- **Sweepers Tab Special:**
  - "Sweeper will be placed" dropdown
  - Position: BEFORE INTRO / START OF SONG / BEFORE END / BRIDGE AT END / INDEPENDENT / CUSTOM
  - Radio: Random by category / Specific sweeper
- Filters: Category, Vocal, Energy, BPM, Year, Priority
- Songs Found count (live)

#### Center — Slot Editor
- Clock Name (editable) + Time range
- Comments field
- **Action Buttons:**
  Change | Delete | Add | Insert | Move Up | Move Down | AI Optimise | Preview | Validate | Save Clock
- **Slot List:**
  `#` | TYPE | EST. START→END | DESCRIPTION | CATEGORY | ENERGY | VOCAL
- Color coding:
  - 🔵 Song (cyan)
  - 🟡 Jingle (amber)
  - 🔴 Spot (red)
  - 🟣 Sweeper (purple)
  - 🟢 Event (green)

#### Right Panel — Slot Properties
- Editing: Slot X — Type
- Dropdowns: Type, Category, Energy, Vocal, Priority, Separation
- **Apply Changes** (amber)
- **Remove Slot** (red)
- Clock Overview stats: Songs, Breaks, Jingles, Total time
- Category Slots bar chart

---

### 5.10 AI Magic Tab
**File:** `ai_magic.html`  
**Figma Node:** 170:2

#### Top Status Bar
```
● ENGINE RUNNING (green)
✦ LAST RUN: 2026-04-13 00:03 AM
NEXT: 5h 4m 18s (live countdown)
```

#### Left — AI Engine 3D Visual
- Animated orbital brain (CSS 3D rings)
- 3 rotating rings (cyan, purple, green)
- Pulsing core with "AI" text
- 6 orbiting planets: Analyze, Schedule, Rotate, Warn, Learn, Report
- Connection lines from core to planets

#### Engine Components (6 cards)
| Component | Status | Color |
|-----------|--------|-------|
| History Scanner | ACTIVE | Green |
| Rule Engine | ACTIVE | Cyan |
| Song Picker | ACTIVE | Purple |
| Warning System | X WARNS | Amber |
| Log Writer | DONE | Green |
| Midnight Timer | WAITING | Gray |

#### Center — Last Run Timeline
- Step-by-step with timestamps
- Animated entry (300ms between steps)
- Example:
```
00:00:00 ● Midnight trigger fired ✓
00:00:01 ● Reading clock grid ✓
00:00:02 ● Loading broadcast history ✓
00:00:04 ⚠ Analyzing categories (warning)
00:00:06 ● Applying rotation rules ✓
00:00:08 ● Generating slots ✓
00:00:11 ⚠ 5 warnings generated
00:00:12 ● Writing to Final Log ✓
00:00:13 ● Schedule complete! ✓
```

#### Right — Stats + Category Health
```
Summary Cards:
♪ 176 Songs Scheduled
⚠ 7 Warnings
◈ 2/8 Categories Used
◷ 12:00 Next Run

Category Health Bars:
Morning Vibes  ████████  6/20  ✅
Hot Currents   ██        0/15  🔴
Classics       ░         0/25  🔴
Pop            ░         0/20  🔴
```

#### Bottom — AI Decision Log
```
Real decisions from ai_decisions_log:
"Skipped Kesariya — played 2 days ago at same time"
"Selected Raataan — 9 days fresh, score: 92%"
"Artist separation: Arijit at 10:04, next 12:04+"
"Warning: Hot Currents 0 songs — fallback used"
```

---

## 6. AI Engine

### 6.1 AI Daily Scheduler
**File:** `core/ai_daily_scheduler.py`

#### Midnight Trigger
```python
# Runs in background thread
# Checks every 10 seconds
# Triggers at 00:00 OR 01:00 (backup)
# If schedule already done → skip
# last_triggered_date prevents double trigger
```

#### Schedule Generation Algorithm
```
For each hour (0-23):
  1. Get clock from clock_schedule
  2. Get clock slots (ordered by position)
  3. For each song slot:
     a. Try FULL RULES:
        - Not played in 7 days
        - Not played at this hour in 3 days
        → ORDER BY last_played ASC
     b. FALLBACK 1: Relax hour rule
        - Not played in 7 days only
     c. FALLBACK 2: Relax day rule
        - Not played in 3 days
     d. FALLBACK 3: Any song (least recent)
     → Log warning if fallback used
  4. Save to ai_daily_log
  5. Log each decision to ai_decisions_log
```

#### Rotation Rules
| Rule | Value | Effect |
|------|-------|--------|
| Same Song Gap | 7 days | Song won't repeat for 7 days |
| Same Slot Gap | 3 days | Song won't play at same hour for 3 days |
| Artist Separation | OFF | Removed (Mass import compatibility) |
| Selection Randomness | 0 (strict) | Oldest played first |

#### Fallback Hierarchy
```
Level 1: AI pre-built schedule (ai_daily_log)
Level 2: AutoScheduler real-time (clock→category)
Level 3: Random songs from any category
Level 4: Emergency — any available song
Radio NEVER stops ✅
```

### 6.2 AutoScheduler
**File:** `core/auto_scheduler.py`

```
On AUTO MODE:
1. Check ai_daily_log for current hour
2. If found → use AI schedule
3. If not → real-time selection
4. Every 30 sec → check for hour change
5. Hour change → reload from new clock
```

### 6.3 Clock Change Detection
```javascript
// Studio JS polls every 30 seconds
// get_active_clock_info() slot
// Returns: {active, clock_name, clock_id, hour}
// Change detected → loadStudioQueue()
// Badge: "Morning Drive (06:00)" green
//        "No clock — fallback" amber
```

---

## 7. Audio Engine

### 7.1 Stitcher Engine
**File:** `core/stitcher_engine.py`

```
Pre-mix approach (pydub):
1. Get songs from queue (time window)
2. Extract hook clips: audio[hook_in:hook_out]
3. Concatenate: open + hook1 + hook2 + ... + close
4. Export as single WAV (tempfile)
5. VLC plays entire sequence (zero gaps)

Result: 44,752ms seamless WAV ✅
```

### 7.2 Sweeper Engine
**File:** `core/sweeper_engine.py`

#### Position Types
| Position | Behavior |
|----------|----------|
| START_OF_SONG | Sweeper plays BEFORE song (standalone) |
| BEFORE_INTRO | Sweeper ends when song intro ends |
| BEFORE_END | Fires at outro_start point |
| BRIDGE_AT_END | 4sec overlap at end + next song crossfade |
| INDEPENDENT | Standalone playback |
| CUSTOM | User-defined ms offset |

### 7.3 Spot Playback (Jazler Standard)
```
Spots: Play START to END (full file)
No cue points for spots
No fade out
Pre-load next item at spot_end - 2000ms
Spot→Song: fade in 1000ms
Song→Spot: fade out 1000ms
Spot→Spot: 0ms gap (seamless)
```

### 7.4 Sleep Prevention
```python
# Windows API — prevents system sleep
# Screen CAN turn off (lock mode OK)
# System CANNOT sleep
# AI midnight trigger always fires ✅
ctypes.windll.kernel32.SetThreadExecutionState(
    0x80000000 | 0x00000001
)
```

---

## 8. API Endpoints

### Songs
```
GET  /api/songs?category_id=&energy=&vocal=&search=
GET  /api/songs/categories
GET  /api/songs/overplay-stats
```

### Scheduling
```
GET  /api/schedule/grid
POST /api/schedule/grid/assign
DELETE /api/schedule/grid/clear
GET  /api/clocks
GET  /api/clocks/{id}/slots
POST /api/clocks
PUT  /api/clocks/{id}
POST /api/clocks/{id}/slots
```

### AI Scheduler
```
GET  /api/scheduler/status?date=
POST /api/scheduler/generate
```

### AI Magic
```
GET  /api/ai-magic/status
GET  /api/ai-magic/timeline
GET  /api/ai-magic/categories
GET  /api/ai-magic/decisions
```

### Spots Monitor
```
GET  /api/spots/hourly-usage
GET  /api/spots/hourly-trend
GET  /api/spots/client-rotation?period=hour|7days
GET  /api/spots/ai-insight
```

### Studio
```
GET  /api/studio/queue
GET  /api/active-clock-info
POST /api/scheduler/generate
```

---

## 9. Figma Design Reference

**File:** RadioAI — Control Panel PREMIUM  
**Key:** `7oN9K61g94wKx3nu44KKDF`  
**URL:** https://www.figma.com/design/7oN9K61g94wKx3nu44KKDF

| Screen | Node ID | Canvas X |
|--------|---------|----------|
| Control Panel — Libraries | 5:2 | 0 |
| Songs Library | 12:2 | 1500 |
| Add New Song Dialog | — | 3000, y=90 |
| Audio Cue Editor | — | 3000, y=830 |
| Song Categories Editor | — | 3000, y=1540 |
| Broadcast Statistics | — | 3700, y=90 |
| Spots & Commercials | 35:2 | 4900 |
| Jingles Library | — | 6340 |
| Instant Jingles | — | 7780 |
| Sweepers Library | — | 9220 |
| The Stitcher | — | 10660 |
| Control Panel — Scheduling | 50:2 | — |
| Main Auto Schedule | 161:2 | — |
| Clock Editor — Add Slots | 165:2 | 15100 |
| AI Magic Tab — Engine View | 170:2 | 16600 |
| Spots AI Monitor | 174:2 | 17800 |

### Design System
```
Background:    #070812 (deepest dark)
Panel BG:      #0a0b18
Card BG:       #0e1020
Border:        #1c1f38

Accent Colors:
Cyan:          #06b6d4 (Songs, Morning)
Purple:        #8b5cf6 (AI, Settings)
Green:         #10b981 (Active, Done)
Amber:         #f59e0b (Warning, Afternoon)
Red:           #f43f5e (Error, Late Night)
Pink:          #ec4899 (Weekend)

Text:
Primary:       #f1f5ff
Secondary:     #8891b8
Muted:         #454d6d

Fonts:
UI:            Inter (Regular/Medium/SemiBold/Bold)
Numbers:       Roboto Mono (Regular/Bold)
```

---

## 10. Packaging & Distribution

### Build Process
```bash
# Step 1: Build .exe
cd C:\RadioAI
pyinstaller radioai.spec --clean

# Step 2: Build installer
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss

# Output:
C:\RadioAI\installer_output\
RadioAI_Studio_Pro_Setup_v1.0.0.exe
```

### What's Packed Inside
```
✅ Python runtime (no install needed)
✅ PyQt6 (UI framework)
✅ VLC engine (libvlc.dll + plugins)
✅ SQLite (database)
✅ All Python packages
✅ All HTML/CSS/JS UI files
✅ RadioAI icon
✅ Blank database (fresh start)
```

### Install Experience
```
Screen 1: Welcome — RadioAI Studio Pro v1.0.0
Screen 2: License Agreement
Screen 3: Install Location (default: C:\Program Files\RadioAI)
Screen 4: Options (Desktop icon ✅, Startup ✅)
Screen 5: Installing with progress bar
Screen 6: Finish + Launch now
```

### First-Time Setup (New PC)
```
1. Install: setup.exe → Next → Next → Finish
2. Launch: Desktop icon
3. Settings → Station Name
4. Libraries → Songs → Mass Import
5. Assign categories to songs
6. Clock Editor → Create clocks
7. Main Auto Schedule → Assign grid
8. Studio → AUTO MODE ON
9. Radio is live! 🎙️
```

### Version History
```
v1.0.0 — Initial Release (Team Testing)
  ✅ Studio playback (Deck A/B)
  ✅ Songs Library + Mass Import
  ✅ Spots & Commercials + AI Monitor
  ✅ Scheduling + 24×7 Grid
  ✅ Clock Editor (Jazler-style)
  ✅ AI Daily Scheduler (midnight)
  ✅ AutoScheduler (clock→queue)
  ✅ Stitcher Engine
  ✅ Sweeper Engine
  ✅ AI Magic Engine tab
  ✅ Sleep prevention
  ✅ VLC packed inside
```

---

## 11. Future Roadmap

### v1.1 — Post Team Feedback
```
⬜ Songs Library AI overplay detection
   (Red flag: 15+ plays/month)
⬜ Category health warnings in library
⬜ Playlists screen
⬜ Force Clocks screen
⬜ Final Log viewer
⬜ AI Decision Log fully working
⬜ Song names visible in Studio decks
```

### v1.2 — Advanced Features
```
⬜ Settings screens
   - General (station info)
   - Soundcard selection
   - Studio settings
   - Users & Security
⬜ Rebroadcast screen
⬜ RDS Settings
⬜ Log Viewer screen
⬜ Weather integration
```

### v1.3 — AI Expansion
```
⬜ AI per-tab magic (Songs, Jingles, etc.)
⬜ AI hook detection (auto-set cue points)
⬜ AI energy detection from audio
⬜ AI similar songs recommendation
⬜ AI category health suggestions
⬜ Mass import auto-categorization
```

### v2.0 — Professional Release
```
⬜ Code signing certificate
⬜ Auto-update system
⬜ Multi-station support
⬜ Network/LAN sharing
⬜ Cloud backup for settings
⬜ Mobile app for remote control
⬜ Traffic/scheduling integration
```

---

## Known Issues (v1.0.0)

```
⚠️  Midnight trigger may occasionally miss
    (1AM backup trigger handles this)
    
⚠️  AI Decision Log not fully populating
    (ai_decisions_log save fix pending)
    
⚠️  Windows SmartScreen warning on install
    (unsigned build — click "Run Anyway")
    
⚠️  Some categories show "0 songs" in AI Magic
    until proper songs are assigned
```

---

## Support & Development

```
Project Path:  C:\RadioAI
Database:      %LOCALAPPDATA%\RadioAI\radioai.db
Figma File:    7oN9K61g94wKx3nu44KKDF
AI Model:      claude-sonnet-4-20250514
Built By:      Kavish (KISS FM 91.5, Jaipur)
```

---

*RadioAI Studio Pro — Professional Radio Automation, Powered by AI*  
*"AI raat bhar jaag ke tumhari radio ka schedule banata hai"* 🎙️📻
