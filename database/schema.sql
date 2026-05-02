-- ════════════════════════════════════════════════════════════════════
-- RadioAI Studio Pro — Complete Database Schema
-- ════════════════════════════════════════════════════════════════════
-- Engine:   SQLite 3 (WAL journal, foreign_keys=ON)
-- Location: %LOCALAPPDATA%\RadioAI\radioai.db
-- Version:  1.0.0
--
-- This file is the single source of truth for the RadioAI database.
-- Running it on a fresh install creates every table the app needs.
-- All tables use IF NOT EXISTS so the file is also safe to re-run.
-- ════════════════════════════════════════════════════════════════════

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- ════════════════════════════════════════════════════════════════════
-- 1. CORE LIBRARIES
-- ════════════════════════════════════════════════════════════════════

-- Song categories (aka song_categories) — used to colour-code and
-- group songs in clocks. Referenced by songs.category_id.
CREATE TABLE IF NOT EXISTS categories (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL UNIQUE,
    color           TEXT    DEFAULT '#8B5CF6',
    description     TEXT,
    auto_rotate     TEXT    DEFAULT 'Rotate after 1 play',
    separation_min  INTEGER DEFAULT 120,
    display_order   INTEGER DEFAULT 0
);

-- Master songs library. All cue points exist in two flavours:
--   *_ms columns (legacy integer milliseconds)
--   hook_in_time / hook_out_time / intro_time / outro_time / mix_point
--   (REAL seconds, used by the new Cue Editor + Stitcher).
-- has_hook = 1 means the Stitcher will pull a hook clip from this song.
CREATE TABLE IF NOT EXISTS songs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    artist              TEXT    NOT NULL,
    title               TEXT    NOT NULL,
    album               TEXT,
    playlister_code     TEXT,
    auto_code           INTEGER UNIQUE,
    label               TEXT,
    cd_key              TEXT,
    barcode             TEXT,
    songwriter          TEXT,
    composer            TEXT,
    comments            TEXT,
    category_id         INTEGER REFERENCES categories(id),
    era                 TEXT,
    vocal               TEXT,
    priority            INTEGER DEFAULT 1,
    year                INTEGER,
    bpm                 INTEGER,
    energy              TEXT,
    duration_ms         INTEGER,
    file_path           TEXT,
    is_enabled          INTEGER DEFAULT 1,
    is_frozen           INTEGER DEFAULT 0,
    entry_date          TEXT    DEFAULT (datetime('now')),
    -- Legacy integer-millisecond cue columns
    start_point_ms      INTEGER DEFAULT 0,
    intro_point_ms      INTEGER DEFAULT 0,
    intro_end_ms        INTEGER DEFAULT 0,
    hook_in_ms          INTEGER DEFAULT 0,
    hook_out_ms         INTEGER DEFAULT 0,
    outro_point_ms      INTEGER DEFAULT 0,
    mix_point_ms        INTEGER DEFAULT 0,
    fade_in_ms          INTEGER DEFAULT 0,
    fade_out_ms         INTEGER DEFAULT 0,
    fade_out_position   TEXT    DEFAULT 'OFF',
    volume_level        INTEGER DEFAULT 100,
    variable_length     INTEGER DEFAULT 0,
    separation_minutes  INTEGER DEFAULT 120,
    artist_sep_minutes  INTEGER DEFAULT 30,
    -- Cue Editor (REAL seconds)
    hook_in_time        REAL    DEFAULT 60.0,
    hook_out_time       REAL    DEFAULT 68.0,
    has_hook            INTEGER DEFAULT 1,
    intro_time          REAL    DEFAULT 0.0,
    outro_time          REAL    DEFAULT 0.0,
    mix_point           REAL    DEFAULT 0.0
);

-- ════════════════════════════════════════════════════════════════════
-- 2. SPOTS / COMMERCIALS
-- ════════════════════════════════════════════════════════════════════

-- Ad campaigns. A campaign owns one or more spot_files (audio files).
CREATE TABLE IF NOT EXISTS campaigns (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    name                     TEXT    NOT NULL,
    description              TEXT,
    category                 TEXT    DEFAULT 'Commercials',
    priority                 TEXT    DEFAULT 'Medium',
    programming_mode         TEXT    DEFAULT 'Weekly',
    playback_order           TEXT    DEFAULT 'Rotation',
    start_date               TEXT,
    end_date                 TEXT,
    contracted_plays_per_day INTEGER DEFAULT 3,
    is_active                INTEGER DEFAULT 1,
    created_at               TEXT    DEFAULT (datetime('now'))
);

-- Individual audio files belonging to a campaign (aka "spots").
CREATE TABLE IF NOT EXISTS spot_files (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id   INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    filename      TEXT    NOT NULL,
    file_path     TEXT    NOT NULL,
    duration_ms   INTEGER,
    is_active     INTEGER DEFAULT 1,
    display_order INTEGER DEFAULT 0
);

-- Weekly break grid: when ad breaks fire each day.
-- day_mask: bit-field 0..127 where bit 0 = Monday … bit 6 = Sunday.
CREATE TABLE IF NOT EXISTS break_schedule (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    break_time         TEXT    NOT NULL,
    day_mask           INTEGER DEFAULT 127,
    break_duration_sec INTEGER DEFAULT 120,
    start_immediately  INTEGER DEFAULT 0,
    is_active          INTEGER DEFAULT 1
);

-- Which campaigns play in which break, per day-of-week.
CREATE TABLE IF NOT EXISTS campaign_schedule (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER REFERENCES campaigns(id),
    day_of_week INTEGER,
    break_time  TEXT,
    slot_order  INTEGER DEFAULT 0
);

-- ════════════════════════════════════════════════════════════════════
-- 3. JINGLES & SWEEPERS
-- ════════════════════════════════════════════════════════════════════

-- Short audio elements: station IDs, news intros, transitions.
CREATE TABLE IF NOT EXISTS jingles (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL,
    category        TEXT    DEFAULT 'Station ID',
    file_path       TEXT,
    duration_ms     INTEGER,
    properties      TEXT,
    playlister_code TEXT,
    is_enabled      INTEGER DEFAULT 1,
    display_order   INTEGER DEFAULT 0
);

-- Instant-jingle pad pages (a "pallet" is one screen of pads).
CREATE TABLE IF NOT EXISTS jingle_pallets (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL,
    owner         TEXT,
    grid_cols     INTEGER DEFAULT 5,
    grid_rows     INTEGER DEFAULT 6,
    audio_output  INTEGER DEFAULT 4,
    display_order INTEGER DEFAULT 0
);

-- Individual instant-jingle buttons inside a pallet.
CREATE TABLE IF NOT EXISTS jingle_pads (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    pallet_id   INTEGER REFERENCES jingle_pallets(id) ON DELETE CASCADE,
    pad_index   INTEGER NOT NULL,
    label       TEXT,
    file_path   TEXT,
    duration_ms INTEGER,
    color       TEXT    DEFAULT '#F59E0B',
    volume      INTEGER DEFAULT 100,
    behaviour   TEXT    DEFAULT 'play_once'
);

-- Sweepers: short voice/effect overlays that sit between songs.
-- position values: BEFORE_INTRO | START_OF_SONG | BEFORE_END
--                  BRIDGE_AT_END | INDEPENDENT | CUSTOM
CREATE TABLE IF NOT EXISTS sweepers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL,
    category        TEXT    DEFAULT 'Station',
    file_path       TEXT,
    duration_ms     INTEGER,
    position        TEXT    DEFAULT 'Bridge at End',
    properties      TEXT,
    playlister_code TEXT,
    is_enabled      INTEGER DEFAULT 1
);

-- ════════════════════════════════════════════════════════════════════
-- 4. CLOCKS, SLOTS, AUTO-SCHEDULE GRID
-- ════════════════════════════════════════════════════════════════════

-- Rotation templates ("clocks"). Each clock holds an ordered list of
-- slots (songs / jingles / spots / sweepers / events).
CREATE TABLE IF NOT EXISTS clocks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    time_start  TEXT,
    time_end    TEXT,
    day_mask    INTEGER DEFAULT 127,
    description TEXT,
    is_active   INTEGER DEFAULT 1
);

-- Ordered slots inside a clock.
CREATE TABLE IF NOT EXISTS clock_slots (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    clock_id            INTEGER NOT NULL REFERENCES clocks(id) ON DELETE CASCADE,
    slot_type           TEXT    NOT NULL,
    category_id         INTEGER REFERENCES categories(id),
    energy_pref         TEXT    DEFAULT 'Any',
    vocal_pref          TEXT    DEFAULT 'Any',
    priority_pref       TEXT    DEFAULT 'Normal',
    separation_override INTEGER,
    position_minutes    REAL,
    slot_order          INTEGER NOT NULL,
    is_break            INTEGER DEFAULT 0,
    sweeper_position    TEXT    DEFAULT 'START_OF_SONG',
    item_id             INTEGER DEFAULT 0
);

-- 24×7 grid: which clock plays in which day/hour. (clock_schedule)
CREATE TABLE IF NOT EXISTS auto_schedule (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    clock_id    INTEGER REFERENCES clocks(id),
    day_of_week INTEGER NOT NULL,
    hour_start  INTEGER NOT NULL,
    hour_end    INTEGER NOT NULL
);

-- One-off date overrides (e.g. holidays, special programming).
CREATE TABLE IF NOT EXISTS force_clocks (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL,
    clock_id      INTEGER REFERENCES clocks(id),
    override_date TEXT    NOT NULL,
    time_start    TEXT    DEFAULT '00:00',
    time_end      TEXT    DEFAULT '23:59',
    is_recurring  INTEGER DEFAULT 0,
    recur_month   INTEGER,
    recur_day     INTEGER,
    is_active     INTEGER DEFAULT 1
);

-- ════════════════════════════════════════════════════════════════════
-- 5. PLAYLISTS (manual song sequences)
-- ════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS playlists (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL,
    description     TEXT,
    playback_mode   TEXT    DEFAULT 'Ordered',
    on_finish       TEXT    DEFAULT 'Return to Clock',
    crossfade_sec   INTEGER DEFAULT 3,
    scheduled_day   TEXT,
    scheduled_time  TEXT,
    is_active       INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS playlist_songs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    playlist_id INTEGER REFERENCES playlists(id) ON DELETE CASCADE,
    song_id     INTEGER REFERENCES songs(id),
    position    INTEGER NOT NULL
);

-- ════════════════════════════════════════════════════════════════════
-- 6. FINAL LOG (the day's broadcast plan)
-- ════════════════════════════════════════════════════════════════════

-- One row per scheduled day. is_locked = 1 means no further auto edits.
CREATE TABLE IF NOT EXISTS final_logs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    log_date      TEXT    NOT NULL UNIQUE,
    is_locked     INTEGER DEFAULT 0,
    generated_by  TEXT    DEFAULT 'AI',
    generated_at  TEXT    DEFAULT (datetime('now')),
    warning_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS final_log_entries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    log_id          INTEGER NOT NULL REFERENCES final_logs(id) ON DELETE CASCADE,
    scheduled_time  TEXT    NOT NULL,
    entry_type      TEXT    NOT NULL,
    song_id         INTEGER REFERENCES songs(id),
    campaign_id     INTEGER REFERENCES campaigns(id),
    jingle_id       INTEGER REFERENCES jingles(id),
    title_override  TEXT,
    artist_override TEXT,
    duration_ms     INTEGER,
    is_locked       INTEGER DEFAULT 0,
    ai_flag         TEXT,
    position        INTEGER NOT NULL
);

-- ════════════════════════════════════════════════════════════════════
-- 7. BROADCAST HISTORY (what actually went on air)
-- ════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS broadcast_log (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    played_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    entry_type     TEXT    NOT NULL,
    song_id        INTEGER REFERENCES songs(id),
    campaign_id    INTEGER REFERENCES campaigns(id),
    jingle_id      INTEGER REFERENCES jingles(id),
    scheduled_time TEXT,
    actual_time    TEXT,
    duration_ms    INTEGER,
    variance_ms    INTEGER DEFAULT 0,
    deck           TEXT    DEFAULT 'A',
    was_manual     INTEGER DEFAULT 0,
    operator       TEXT    DEFAULT 'AI AUTO'
);

-- ════════════════════════════════════════════════════════════════════
-- 8. AI ENGINE TABLES
-- ════════════════════════════════════════════════════════════════════

-- The AI's pre-generated daily schedule (one row per slot).
CREATE TABLE IF NOT EXISTS ai_daily_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    schedule_date TEXT    NOT NULL,
    hour          INTEGER NOT NULL,
    position      INTEGER NOT NULL,
    song_id       INTEGER,
    slot_type     TEXT    DEFAULT 'song',
    generated_at  TEXT    DEFAULT (datetime('now','localtime')),
    status        TEXT    DEFAULT 'scheduled'   -- scheduled|played|skipped
);

-- One row per day: did the midnight scheduler succeed?
CREATE TABLE IF NOT EXISTS ai_schedule_status (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    schedule_date    TEXT    UNIQUE NOT NULL,
    status           TEXT    DEFAULT 'pending', -- done|failed|pending|building
    generated_at     TEXT    DEFAULT (datetime('now','localtime')),
    warnings_count   INTEGER DEFAULT 0,
    songs_scheduled  INTEGER DEFAULT 0,
    error_message    TEXT
);

-- Warnings raised during a generation run.
CREATE TABLE IF NOT EXISTS ai_schedule_warnings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    schedule_date TEXT NOT NULL,
    warning_type  TEXT,
    category_name TEXT,
    message       TEXT,
    severity      TEXT DEFAULT 'info'           -- info|warning|critical
);

-- AI Magic tab — step-by-step run timeline (aka ai_scheduler_log).
CREATE TABLE IF NOT EXISTS ai_run_steps (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date    TEXT NOT NULL,
    step_time   TEXT,
    step_label  TEXT,
    step_detail TEXT,
    status      TEXT DEFAULT 'done'
);

-- AI Magic tab — individual decision log (aka ai_decisions_log).
CREATE TABLE IF NOT EXISTS ai_decisions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date      TEXT NOT NULL,
    decision_time TEXT,
    decision_type TEXT,
    song_id       INTEGER,
    message       TEXT
);

-- Generic AI insights surfaced anywhere in the UI.
CREATE TABLE IF NOT EXISTS ai_insights (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    insight_type TEXT NOT NULL,
    entity_type  TEXT,
    entity_id    INTEGER,
    severity     TEXT DEFAULT 'info',
    message      TEXT NOT NULL,
    detail       TEXT,
    created_at   TEXT DEFAULT (datetime('now')),
    is_dismissed INTEGER DEFAULT 0
);

-- ════════════════════════════════════════════════════════════════════
-- 9. STITCHER (hook-clip preview engine)
-- ════════════════════════════════════════════════════════════════════

-- Single-row config (id = 1) for the Stitcher engine.
CREATE TABLE IF NOT EXISTS stitcher_config (
    id                          INTEGER PRIMARY KEY DEFAULT 1,
    opening_audio               TEXT    DEFAULT '',
    separator_audio             TEXT    DEFAULT '',
    closing_audio               TEXT    DEFAULT '',
    fallback_audio              TEXT    DEFAULT '',
    hook_duration_seconds       INTEGER DEFAULT 8,
    min_hooks_required          INTEGER DEFAULT 2,
    max_hooks                   INTEGER DEFAULT 4,
    module_enabled              INTEGER DEFAULT 1,
    trigger_before_every_break  INTEGER DEFAULT 1,
    trigger_every_n_songs       INTEGER DEFAULT 0,
    trigger_every_n_songs_count INTEGER DEFAULT 4,
    trigger_top_of_hour         INTEGER DEFAULT 0,
    trigger_mode                TEXT    DEFAULT 'break_reference',
    time_window_minutes         INTEGER DEFAULT 25,
    strict_mode                 INTEGER DEFAULT 0,
    updated_at                  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ════════════════════════════════════════════════════════════════════
-- 10. SETTINGS, RULES, USERS
-- ════════════════════════════════════════════════════════════════════

-- Generic key/value settings store. Scheduling rules
-- (same_song_days, same_slot_days, …) also live here.
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL UNIQUE,
    display_name  TEXT    NOT NULL,
    email         TEXT,
    role          TEXT    DEFAULT 'DJ',
    password_hash TEXT,
    is_active     INTEGER DEFAULT 1,
    created_at    TEXT    DEFAULT (datetime('now')),
    last_login    TEXT
);

-- ════════════════════════════════════════════════════════════════════
-- 11. INDEXES (performance)
-- ════════════════════════════════════════════════════════════════════

CREATE INDEX IF NOT EXISTS idx_songs_category   ON songs(category_id);
CREATE INDEX IF NOT EXISTS idx_songs_enabled    ON songs(is_enabled);
CREATE INDEX IF NOT EXISTS idx_songs_artist     ON songs(artist);
CREATE INDEX IF NOT EXISTS idx_spot_files_camp  ON spot_files(campaign_id);
CREATE INDEX IF NOT EXISTS idx_clock_slots_clk  ON clock_slots(clock_id, slot_order);
CREATE INDEX IF NOT EXISTS idx_auto_sched_day   ON auto_schedule(day_of_week, hour_start);
CREATE INDEX IF NOT EXISTS idx_broadcast_song   ON broadcast_log(song_id, played_at);
CREATE INDEX IF NOT EXISTS idx_broadcast_when   ON broadcast_log(played_at);
CREATE INDEX IF NOT EXISTS idx_aidaily_date     ON ai_daily_log(schedule_date, hour);
CREATE INDEX IF NOT EXISTS idx_aiwarn_date      ON ai_schedule_warnings(schedule_date);
CREATE INDEX IF NOT EXISTS idx_aisteps_run      ON ai_run_steps(run_date);
CREATE INDEX IF NOT EXISTS idx_aidecide_run     ON ai_decisions(run_date);
CREATE INDEX IF NOT EXISTS idx_finallog_date    ON final_logs(log_date);
CREATE INDEX IF NOT EXISTS idx_finalentry_log   ON final_log_entries(log_id, position);
