-- Migration: 004_cue_editor
-- Date: 2026-04-14
-- Description: Audio Cue Editor — REAL-seconds cue point columns +
--              clock_slots tweaks for the new Sweepers tab.
--
-- These ALTERs are wrapped by the Python migration runner so that
-- a "duplicate column name" error is treated as already-applied.

ALTER TABLE songs ADD COLUMN hook_in_time   REAL    DEFAULT 60.0;
ALTER TABLE songs ADD COLUMN hook_out_time  REAL    DEFAULT 68.0;
ALTER TABLE songs ADD COLUMN has_hook       INTEGER DEFAULT 1;
ALTER TABLE songs ADD COLUMN intro_time     REAL    DEFAULT 0.0;
ALTER TABLE songs ADD COLUMN outro_time     REAL    DEFAULT 0.0;
ALTER TABLE songs ADD COLUMN mix_point      REAL    DEFAULT 0.0;
ALTER TABLE songs ADD COLUMN intro_end_ms   INTEGER DEFAULT 0;

ALTER TABLE clock_slots ADD COLUMN sweeper_position TEXT    DEFAULT 'START_OF_SONG';
ALTER TABLE clock_slots ADD COLUMN item_id          INTEGER DEFAULT 0;

-- Backfill: songs with NULL/0 hook values get sensible defaults so
-- the Stitcher preview works on a fresh DB.
UPDATE songs SET
    hook_in_time  = COALESCE(NULLIF(hook_in_time, 0), 60.0),
    hook_out_time = COALESCE(NULLIF(hook_out_time, 0), 68.0),
    has_hook      = 1
WHERE has_hook IS NULL OR has_hook = 0;
