-- Migration: 003_spots_monitor
-- Date: 2026-04-14
-- Description: Stitcher (hook-clip preview engine) + indexes that
--              power the Spots AI Monitor (broadcast-history lookups
--              by hour/campaign).

-- Single-row config for the Stitcher engine.
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

INSERT OR IGNORE INTO stitcher_config (id) VALUES (1);

-- Indexes that the Spots AI Monitor relies on for the
-- "this hour ad usage" / "client rotation" queries.
CREATE INDEX IF NOT EXISTS idx_broadcast_song      ON broadcast_log(song_id, played_at);
CREATE INDEX IF NOT EXISTS idx_broadcast_when      ON broadcast_log(played_at);
CREATE INDEX IF NOT EXISTS idx_broadcast_campaign  ON broadcast_log(campaign_id, played_at);
CREATE INDEX IF NOT EXISTS idx_broadcast_type      ON broadcast_log(entry_type, played_at);
