-- ════════════════════════════════════════════════════════════════════
-- RadioAI Studio Pro v2.0 — Master Database Schema
-- ════════════════════════════════════════════════════════════════════
-- Engine   : SQLite 3 (WAL journal, foreign_keys=ON)
-- Location : %LOCALAPPDATA%\RadioAI\radioai.db
-- Version  : 2.0.0
--
-- SAFE TO RUN ON EXISTING DB:
--   • Every table uses CREATE TABLE IF NOT EXISTS
--   • Existing data (395 songs, 15 campaigns, 26 clocks) is preserved
--   • Only NEW tables (spot_schedules, scheduling_rules) are added
--
-- Column names match the AUDITED production DB exactly.
-- ════════════════════════════════════════════════════════════════════

PRAGMA foreign_keys = ON;
PRAGMA journal_mode  = WAL;

-- ════════════════════════════════════════════════════════════════════
-- 1. SONG LIBRARIES
-- ════════════════════════════════════════════════════════════════════

-- Song categories — colour-code and group songs in clocks.
CREATE TABLE IF NOT EXISTS categories (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL UNIQUE,
    color           TEXT    DEFAULT '#06b6d4',
    description     TEXT,
    auto_rotate     TEXT    DEFAULT 'Rotate after 1 play',
    separation_min  INTEGER DEFAULT 120,
    display_order   INTEGER DEFAULT 0
);

-- Master songs library.
-- Cue points exist in two flavours:
--   *_ms  (integer milliseconds) — used by AudioEngine
--   *_time (REAL seconds)        — used by Cue Editor & Stitcher
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
    duration_ms         INTEGER DEFAULT 0,
    file_path           TEXT,
    is_enabled          INTEGER DEFAULT 1,
    is_frozen           INTEGER DEFAULT 0,
    entry_date          TEXT    DEFAULT (datetime('now')),
    -- Integer-millisecond cue points (AudioEngine)
    start_point_ms      INTEGER DEFAULT 0,
    intro_point_ms      INTEGER DEFAULT 0,
    intro_end_ms        INTEGER DEFAULT 0,
    hook_in_ms          INTEGER DEFAULT 0,
    hook_out_ms         INTEGER DEFAULT 0,
    outro_point_ms      INTEGER DEFAULT 0,
    mix_point_ms        INTEGER DEFAULT 0,
    fade_in_ms          INTEGER DEFAULT 1000,
    fade_out_ms         INTEGER DEFAULT 3000,
    fade_out_position   TEXT    DEFAULT 'OFF',
    volume_level        INTEGER DEFAULT 100,
    variable_length     INTEGER DEFAULT 0,
    separation_minutes  INTEGER DEFAULT 120,
    artist_sep_minutes  INTEGER DEFAULT 30,
    -- REAL-seconds cue points (Cue Editor / Stitcher)
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

-- Ad campaigns. One campaign owns one or more audio files (spot_files).
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

-- Audio files belonging to a campaign.
CREATE TABLE IF NOT EXISTS spot_files (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id   INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    filename      TEXT    NOT NULL,
    file_path     TEXT    NOT NULL,
    duration_ms   INTEGER DEFAULT 0,
    is_active     INTEGER DEFAULT 1,
    display_order INTEGER DEFAULT 0
);

-- Weekly break schedule — when ad breaks fire each day.
-- break_time: "HH:MM"  day_mask: bitmask 0=Mon … 6=Sun
CREATE TABLE IF NOT EXISTS break_schedule (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    break_time         TEXT    NOT NULL,
    day_mask           INTEGER DEFAULT 127,
    break_duration_sec INTEGER DEFAULT 120,
    start_immediately  INTEGER DEFAULT 0,
    is_active          INTEGER DEFAULT 1
);

-- Which campaigns play in which break slot, per day.
CREATE TABLE IF NOT EXISTS campaign_schedule (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER REFERENCES campaigns(id),
    day_of_week INTEGER,
    break_time  TEXT,
    slot_order  INTEGER DEFAULT 0
);

-- ★ NEW — Spot break timetable (plain hour:minute scheduling)
-- Used by Studio to display "NEXT BREAK" countdown.
CREATE TABLE IF NOT EXISTS spot_schedules (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    day_of_week         INTEGER,          -- NULL = every day
    hour                INTEGER NOT NULL,
    minute              INTEGER DEFAULT 0,
    max_duration_mins   INTEGER DEFAULT 5,
    is_active           INTEGER DEFAULT 1
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
    duration_ms     INTEGER DEFAULT 0,
    properties      TEXT,
    playlister_code TEXT,
    is_enabled      INTEGER DEFAULT 1,
    display_order   INTEGER DEFAULT 0
);

-- Instant-jingle pad pallets (a pallet = one screen of pad buttons).
CREATE TABLE IF NOT EXISTS jingle_pallets (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL,
    owner         TEXT,
    grid_cols     INTEGER DEFAULT 5,
    grid_rows     INTEGER DEFAULT 6,
    audio_output  INTEGER DEFAULT 4,
    display_order INTEGER DEFAULT 0
);

-- Individual instant-jingle pad buttons.
CREATE TABLE IF NOT EXISTS jingle_pads (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    pallet_id   INTEGER REFERENCES jingle_pallets(id) ON DELETE CASCADE,
    pad_index   INTEGER NOT NULL,
    label       TEXT,
    file_path   TEXT,
    duration_ms INTEGER DEFAULT 0,
    color       TEXT    DEFAULT '#F59E0B',
    volume      INTEGER DEFAULT 100,
    behaviour   TEXT    DEFAULT 'play_once'
);

-- Sweepers: short voice/effect overlays between songs.
-- position: BEFORE_INTRO | START_OF_SONG | BEFORE_END
--           BRIDGE_AT_END | INDEPENDENT | CUSTOM
CREATE TABLE IF NOT EXISTS sweepers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL,
    category        TEXT    DEFAULT 'Station',
    file_path       TEXT,
    duration_ms     INTEGER DEFAULT 0,
    position        TEXT    DEFAULT 'Bridge at End',
    properties      TEXT,
    playlister_code TEXT,
    is_enabled      INTEGER DEFAULT 1
);

-- ════════════════════════════════════════════════════════════════════
-- 4. CLOCKS, SLOTS, AUTO-SCHEDULE GRID
-- ════════════════════════════════════════════════════════════════════

-- Rotation templates. Each clock holds an ordered list of slots.
CREATE TABLE IF NOT EXISTS clocks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    time_start  TEXT,
    time_end    TEXT,
    day_mask    INTEGER DEFAULT 127,
    description TEXT,
    is_active   INTEGER DEFAULT 1
);

-- Ordered slots inside a clock (songs / jingles / spots / sweepers).
CREATE TABLE IF NOT EXISTS clock_slots (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    clock_id            INTEGER NOT NULL REFERENCES clocks(id) ON DELETE CASCADE,
    slot_type           TEXT    NOT NULL,   -- song|jingle|spot|sweeper|event
    category_id         INTEGER REFERENCES categories(id),
    energy_pref         TEXT    DEFAULT 'Any',
    vocal_pref          TEXT    DEFAULT 'Any',
    priority_pref       TEXT    DEFAULT 'Normal',
    separation_override INTEGER,
    position_minutes    REAL,
    slot_order          INTEGER NOT NULL,
    is_break            INTEGER DEFAULT 0,
    sweeper_position    TEXT    DEFAULT 'START_OF_SONG',
    item_id             INTEGER DEFAULT 0   -- specific song/jingle if locked
);

-- 24×7 grid: which clock plays which day+hour range.
-- AUDITED: uses hour_start / hour_end (ranges), NOT a single hour column.
-- Each row covers exactly 1 hour (hour_start = N, hour_end = N+1).
CREATE TABLE IF NOT EXISTS auto_schedule (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    clock_id    INTEGER REFERENCES clocks(id) ON DELETE CASCADE,
    day_of_week INTEGER NOT NULL,   -- 0=Mon … 6=Sun
    hour_start  INTEGER NOT NULL,   -- 0–23
    hour_end    INTEGER NOT NULL    -- 1–24
);

-- One-off date overrides (holidays, special programming).
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

-- ★ NEW — Scheduling rules (Jazler-style separation parameters).
CREATE TABLE IF NOT EXISTS scheduling_rules (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_name   TEXT    NOT NULL UNIQUE,
    rule_value  TEXT    NOT NULL,
    updated_at  TEXT    DEFAULT (datetime('now'))
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
-- 6. FINAL LOG (Jazler-style 24-hour broadcast plan)
-- ════════════════════════════════════════════════════════════════════

-- One row per day. is_locked = 1 → no further auto edits.
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
    duration_ms     INTEGER DEFAULT 0,
    is_locked       INTEGER DEFAULT 0,
    ai_flag         TEXT,
    position        INTEGER NOT NULL
);

-- ════════════════════════════════════════════════════════════════════
-- 7. BROADCAST HISTORY (what actually went on air)
-- ════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS broadcast_log (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    played_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    entry_type     TEXT    NOT NULL,    -- song|spot|jingle|sweeper|stitcher
    song_id        INTEGER REFERENCES songs(id),
    campaign_id    INTEGER REFERENCES campaigns(id),
    jingle_id      INTEGER REFERENCES jingles(id),
    scheduled_time TEXT,
    actual_time    TEXT,
    duration_ms    INTEGER DEFAULT 0,
    variance_ms    INTEGER DEFAULT 0,
    deck           TEXT    DEFAULT 'A',
    was_manual     INTEGER DEFAULT 0,
    operator       TEXT    DEFAULT 'AI AUTO'
);

-- ════════════════════════════════════════════════════════════════════
-- 8. AI ENGINE TABLES
-- ════════════════════════════════════════════════════════════════════

-- AI pre-generated daily schedule (one row per slot).
CREATE TABLE IF NOT EXISTS ai_daily_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    schedule_date TEXT    NOT NULL,
    hour          INTEGER NOT NULL,
    position      INTEGER NOT NULL,
    song_id       INTEGER REFERENCES songs(id),
    slot_type     TEXT    DEFAULT 'song',
    generated_at  TEXT    DEFAULT (datetime('now','localtime')),
    status        TEXT    DEFAULT 'scheduled'   -- scheduled|played|skipped
);

-- One row per day: did the midnight scheduler succeed?
CREATE TABLE IF NOT EXISTS ai_schedule_status (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    schedule_date    TEXT    UNIQUE NOT NULL,
    status           TEXT    DEFAULT 'pending',  -- done|failed|pending|building
    generated_at     TEXT    DEFAULT (datetime('now','localtime')),
    warnings_count   INTEGER DEFAULT 0,
    songs_scheduled  INTEGER DEFAULT 0,
    error_message    TEXT
);

-- Warnings raised during an AI generation run.
CREATE TABLE IF NOT EXISTS ai_schedule_warnings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    schedule_date TEXT    NOT NULL,
    warning_type  TEXT,
    category_name TEXT,
    message       TEXT,
    severity      TEXT    DEFAULT 'info'    -- info|warning|critical
);

-- AI Magic tab — step-by-step run timeline.
CREATE TABLE IF NOT EXISTS ai_run_steps (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date    TEXT    NOT NULL,
    step_time   TEXT,
    step_label  TEXT,
    step_detail TEXT,
    status      TEXT    DEFAULT 'done'
);

-- AI Magic tab — individual song decision log.
CREATE TABLE IF NOT EXISTS ai_decisions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date      TEXT    NOT NULL,
    decision_time TEXT,
    decision_type TEXT,
    song_id       INTEGER REFERENCES songs(id),
    message       TEXT
);

-- Generic AI insights surfaced in UI panels.
CREATE TABLE IF NOT EXISTS ai_insights (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    insight_type TEXT    NOT NULL,
    entity_type  TEXT,
    entity_id    INTEGER,
    severity     TEXT    DEFAULT 'info',
    message      TEXT    NOT NULL,
    detail       TEXT,
    created_at   TEXT    DEFAULT (datetime('now')),
    is_dismissed INTEGER DEFAULT 0
);

-- ════════════════════════════════════════════════════════════════════
-- 9. STITCHER ENGINE CONFIG
-- ════════════════════════════════════════════════════════════════════

-- Single-row config (id = 1 always).
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
    updated_at                  TEXT    DEFAULT (datetime('now'))
);

-- ════════════════════════════════════════════════════════════════════
-- 10. SETTINGS, USERS, AUDIT
-- ════════════════════════════════════════════════════════════════════

-- Generic key/value settings store.
-- Scheduling rules (same_song_days, etc.) also live here.
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL UNIQUE,
    display_name  TEXT    NOT NULL DEFAULT '',
    email         TEXT,
    role          TEXT    DEFAULT 'DJ',
    password_hash TEXT,
    is_active     INTEGER DEFAULT 1,
    created_at    TEXT    DEFAULT (datetime('now')),
    last_login    TEXT
);

CREATE TABLE IF NOT EXISTS access_log (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    username  TEXT,
    action    TEXT,
    timestamp TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS schema_migrations (
    name       TEXT PRIMARY KEY,
    applied_at TEXT DEFAULT (datetime('now'))
);

-- ════════════════════════════════════════════════════════════════════
-- 11. PERFORMANCE INDEXES
-- ════════════════════════════════════════════════════════════════════

-- Songs
CREATE INDEX IF NOT EXISTS idx_songs_category  ON songs(category_id);
CREATE INDEX IF NOT EXISTS idx_songs_enabled   ON songs(is_enabled);
CREATE INDEX IF NOT EXISTS idx_songs_artist    ON songs(artist);

-- Spot files
CREATE INDEX IF NOT EXISTS idx_spot_files_camp ON spot_files(campaign_id);

-- Clock slots
CREATE INDEX IF NOT EXISTS idx_clock_slots_clk ON clock_slots(clock_id, slot_order);

-- Auto-schedule grid
CREATE INDEX IF NOT EXISTS idx_auto_sched_day  ON auto_schedule(day_of_week, hour_start);

-- Broadcast log (most frequently queried)
CREATE INDEX IF NOT EXISTS idx_broadcast_song      ON broadcast_log(song_id, played_at);
CREATE INDEX IF NOT EXISTS idx_broadcast_when      ON broadcast_log(played_at);
CREATE INDEX IF NOT EXISTS idx_broadcast_campaign  ON broadcast_log(campaign_id);
CREATE INDEX IF NOT EXISTS idx_broadcast_type      ON broadcast_log(entry_type);

-- AI engine
CREATE INDEX IF NOT EXISTS idx_aidaily_date    ON ai_daily_log(schedule_date, hour);
CREATE INDEX IF NOT EXISTS idx_aistatus_date   ON ai_schedule_status(schedule_date);
CREATE INDEX IF NOT EXISTS idx_aiwarn_date     ON ai_schedule_warnings(schedule_date);
CREATE INDEX IF NOT EXISTS idx_aisteps_run     ON ai_run_steps(run_date);
CREATE INDEX IF NOT EXISTS idx_aidecide_run    ON ai_decisions(run_date);

-- Final log
CREATE INDEX IF NOT EXISTS idx_finallog_date   ON final_logs(log_date);
CREATE INDEX IF NOT EXISTS idx_finalentry_log  ON final_log_entries(log_id, position);

-- Spot schedules (new table)
CREATE INDEX IF NOT EXISTS idx_spot_sched_hour ON spot_schedules(hour, day_of_week);

-- Record this schema version
INSERT OR IGNORE INTO schema_migrations (name) VALUES ('v2.0.0_foundation');
