-- Migration: 002_ai_tables
-- Date: 2026-04-14
-- Description: AI Daily Scheduler + AI Magic engine tables.
--              Adds the pre-built daily schedule, run status,
--              warnings, step-by-step timeline and decisions log.

CREATE TABLE IF NOT EXISTS ai_daily_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    schedule_date TEXT    NOT NULL,
    hour          INTEGER NOT NULL,
    position      INTEGER NOT NULL,
    song_id       INTEGER,
    slot_type     TEXT    DEFAULT 'song',
    generated_at  TEXT    DEFAULT (datetime('now','localtime')),
    status        TEXT    DEFAULT 'scheduled'
);

CREATE TABLE IF NOT EXISTS ai_schedule_status (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    schedule_date   TEXT    UNIQUE NOT NULL,
    status          TEXT    DEFAULT 'pending',
    generated_at    TEXT    DEFAULT (datetime('now','localtime')),
    warnings_count  INTEGER DEFAULT 0,
    songs_scheduled INTEGER DEFAULT 0,
    error_message   TEXT
);

CREATE TABLE IF NOT EXISTS ai_schedule_warnings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    schedule_date TEXT NOT NULL,
    warning_type  TEXT,
    category_name TEXT,
    message       TEXT,
    severity      TEXT DEFAULT 'info'
);

CREATE TABLE IF NOT EXISTS ai_run_steps (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date    TEXT NOT NULL,
    step_time   TEXT,
    step_label  TEXT,
    step_detail TEXT,
    status      TEXT DEFAULT 'done'
);

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

CREATE INDEX IF NOT EXISTS idx_aidaily_date ON ai_daily_log(schedule_date, hour);
CREATE INDEX IF NOT EXISTS idx_aiwarn_date  ON ai_schedule_warnings(schedule_date);
CREATE INDEX IF NOT EXISTS idx_aisteps_run  ON ai_run_steps(run_date);
CREATE INDEX IF NOT EXISTS idx_aidecide_run ON ai_decisions(run_date);
