# RadioAI Studio Pro

**AI-native Windows desktop radio automation — a Jazler SOHO replacement.**

Built for KISS FM 91.5, Jaipur · Version 1.0.0

RadioAI replaces manual radio scheduling with an AI engine that plans,
rotates and manages broadcasts automatically. At midnight it builds the
next day's full playlist; during the day the AutoScheduler keeps the
queue ahead of the on-air deck and enforces ad-load policy in real time.

---

## Screenshots

> *Screenshots will be added once Session 1 (Foundation) lands.*
>
> Planned set: Studio (on-air deck), Songs Library, Spots & Commercials
> with the AI Monitor, Clock Editor, AI Magic engine view, and the
> 24×7 auto-schedule grid.

---

## Installation — End user (.exe)

1. Download `RadioAI_Studio_Pro_Setup_v1.0.0.exe` from
   `installer_output/` (or the release page).
2. Run the installer → Next → Next → Finish.
   - Windows SmartScreen may warn on the unsigned build; click
     **More info → Run anyway**.
3. Launch from the desktop shortcut.
4. First-run setup: Settings → Station Name → Songs Library → Mass
   Import → Clock Editor → Main Auto Schedule → Studio → AUTO MODE on.

The installer bundles Python, PyQt6, the VLC engine and a blank
SQLite database — nothing else needs to be installed.

---

## Installation — Developer

```bash
git clone <this-repo> C:\RadioAI
cd C:\RadioAI

py -3.11 -m venv .venv
.venv\Scripts\activate

pip install -r requirements.txt
python main.py
```

VLC must be installed and on `PATH` for `python-vlc` to find
`libvlc.dll` (the packaged `.exe` ships its own copy).

To bootstrap a fresh database from the canonical SQL files:

```bash
python -m database.db_manager
```

To build the installer:

```bash
pyinstaller radioai.spec --clean
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
```

---

## Tech stack

| Layer            | Technology                              |
|------------------|-----------------------------------------|
| Language         | Python 3.11+                            |
| UI framework     | PyQt6 + QtWebEngine (HTML/CSS/JS panes) |
| Audio engine     | python-vlc (VLC media player)           |
| Audio analysis   | librosa, mutagen, pydub                 |
| Database         | SQLite (WAL mode)                       |
| AI               | Anthropic Claude API (Sonnet 4)         |
| Packaging        | PyInstaller + Inno Setup                |
| Platform         | Windows 10 / 11 only                    |

---

## Features

- **Studio** — Dual-deck A/B with crossfade, waveform display, jingle
  pads, live queue and on-air status.
- **Songs Library** — Mass import with auto-metadata, audio cue editor
  (start, intro, hook in/out, outro, mix point), broadcast analytics,
  AI overplay alerts.
- **Spots & Commercials** — Campaign manager, weekly break grid, and
  the **AI Monitor** (per-hour ad usage, hourly trend, client rotation,
  AI insight bar — enforces the 15-min/hour policy).
- **Jingles, Sweepers, Stitcher** — Full instant-pad system, sweepers
  with six positioning modes, and a hook-clip preview engine that
  pre-mixes seamless promo sequences.
- **Scheduling** — Jazler-style 24×7 clock grid, drag-to-assign clocks
  per day/hour, force-clocks for one-off dates.
- **Clock Editor** — Slot-based rotation builder with category, energy,
  vocal, priority and separation controls.
- **AI Daily Scheduler** — Midnight trigger builds the next day's
  playlist using a 4-level fallback hierarchy (radio never stops).
- **AI Magic tab** — Live engine visualisation, run timeline, decision
  log and category-health bars.
- **Sleep prevention** — Windows stays awake so the midnight trigger
  never misses (display can still turn off).
- **AutoScheduler** — Keeps the on-air queue 3+ items ahead at all
  times; reloads when the clock changes on the hour.

See [`blueprint.md`](blueprint.md) for the full feature spec and
[`Design.md`](Design.md) for the design system.

---

## Project layout

```
C:\RadioAI\
├── main.py                     entry point
├── core/                       audio + scheduling + AI engines
├── ui/                         PyQt6 main window + bridge + web panes
│   └── web/                    HTML/CSS/JS for each screen
├── database/                   schema.sql · seeds.sql · migrations · DBManager
├── models/                     thin data classes
├── tests/                      QA harness
├── assets/                     icons + fonts
├── radioai.spec                PyInstaller build script
└── installer.iss               Inno Setup script
```

The live database lives at **`%LOCALAPPDATA%\RadioAI\radioai.db`**, not
in the project folder.

---

## License

Proprietary — © 2026 Kavish / KISS FM 91.5, Jaipur, Rajasthan. All
rights reserved. Internal use for the station; redistribution requires
written permission.

---

*RadioAI Studio Pro — Professional radio automation, powered by AI.*
*"AI raat bhar jaag ke tumhari radio ka schedule banata hai." 🎙️📻*
