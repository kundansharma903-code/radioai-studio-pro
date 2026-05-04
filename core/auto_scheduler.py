"""RadioAI Studio Pro -- Auto Scheduler

Reads the clock schedule grid (auto_schedule) to determine which
clock is active for the current day + hour, then builds a playlist
queue from that clock's slots. Each slot type maps to a concrete
audio item from the library:

    Song    -> pick from songs matching the slot's category/energy/vocal
    Jingle  -> pick a specific or random jingle
    Sweeper -> attach to the previous song as an overlay
    Spot    -> insert a break marker

If no clock is assigned for the current hour, falls back to random
songs from the most popular category.
"""

import logging
from datetime import datetime

log = logging.getLogger("AutoScheduler")


class AutoScheduler:
    """Builds a concrete playlist queue from clock slot definitions."""

    MIN_QUEUE_SIZE = 6  # always keep at least N items ahead

    def __init__(self, db):
        self.db = db
        self._last_clock_id = None
        self._slot_cursor = 0  # position within the current clock's slots

    # ── Public API ───────────────────────────────────────────────────

    def get_current_clock(self):
        """Return the clock assigned to the current day + hour, or None."""
        now = datetime.now()
        dow = now.weekday()  # 0=Mon
        hour = now.hour
        rows = self.db.execute(
            "SELECT c.id, c.name, c.time_start, c.time_end "
            "FROM auto_schedule a "
            "JOIN clocks c ON c.id = a.clock_id "
            "WHERE a.day_of_week = ? AND a.hour_start = ? "
            "AND c.is_active = 1 "
            "LIMIT 1",
            (dow, hour),
        )
        if rows:
            return {
                "id": rows[0][0],
                "name": rows[0][1] or "",
                "time_start": rows[0][2] or "",
                "time_end": rows[0][3] or "",
            }
        return None

    def get_clock_slots(self, clock_id):
        """Return ordered slot definitions for a clock."""
        rows = self.db.execute(
            "SELECT cs.id, cs.slot_type, cs.category_id, cs.energy_pref, "
            "cs.vocal_pref, cs.priority_pref, cs.separation_override, "
            "cs.slot_order, cs.is_break, cs.sweeper_position, cs.item_id "
            "FROM clock_slots cs "
            "WHERE cs.clock_id = ? ORDER BY cs.slot_order",
            (int(clock_id),),
        )
        return [
            {
                "id": r[0],
                "slot_type": r[1] or "Song",
                "category_id": r[2],
                "energy": r[3] or "Any",
                "vocal": r[4] or "Any",
                "priority": r[5] or "Normal",
                "separation": r[6] or 0,
                "slot_order": r[7],
                "is_break": r[8] or 0,
                "sweeper_position": r[9] or "START_OF_SONG",
                "item_id": r[10] or 0,
            }
            for r in rows
        ]

    def build_queue(self, max_items=20):
        """Build a concrete playlist.

        Priority order:
        1. AI daily log (pre-generated schedule) for current hour
        2. Clock-driven real-time selection
        3. Random fallback
        """
        # ── Try AI pre-built schedule first ──────────────────────
        ai_queue = self._try_ai_schedule(max_items)
        if ai_queue:
            return ai_queue

        # ── Fall back to real-time clock selection ────────────────
        clock = self.get_current_clock()
        if clock:
            clock_id = clock["id"]
            if clock_id != self._last_clock_id:
                self._last_clock_id = clock_id
                self._slot_cursor = 0
            return self._build_from_clock(clock_id, max_items)
        else:
            return self._fallback_queue(max_items)

    def _try_ai_schedule(self, max_items):
        """Check ai_daily_log for today's pre-built hour schedule."""
        now = datetime.now()
        today = now.strftime('%Y-%m-%d')
        hour = now.hour

        # Is today's schedule done?
        status_rows = self.db.execute(
            "SELECT status FROM ai_schedule_status WHERE schedule_date=?",
            (today,))
        if not status_rows or status_rows[0][0] != 'done':
            return None

        # Get this hour's log entries
        from core.ai_daily_scheduler import AIDailyScheduler
        ai = AIDailyScheduler(self.db)
        rows = ai.get_hour_schedule(today, hour)
        if not rows:
            return None

        def ms_fmt(ms):
            if not ms:
                return "0:00"
            s = int(ms) // 1000
            return f"{s // 60}:{s % 60:02d}"

        queue = []
        for r in rows:
            song_id = r[0]
            slot_type = r[1] or "song"
            artist = r[3] or ""
            title = r[4] or ""
            file_path = r[5] or ""
            duration_ms = r[6] or 0
            bpm = r[7] or 0
            year = r[8] or 0
            cat_name = r[9] or ""
            cat_color = r[10] or "#8B5CF6"

            if slot_type == "spot":
                queue.append(self._make_break_marker())
                continue

            if not file_path:
                continue

            item = {
                "type": "song",
                "id": song_id,
                "artist": "SWEEPER" if slot_type == "sweeper" else ("JINGLE" if slot_type == "jingle" else artist),
                "title": title,
                "duration": ms_fmt(duration_ms),
                "duration_secs": int(duration_ms / 1000),
                "file_path": file_path,
                "bpm": bpm,
                "year": year,
                "category": cat_name,
                "cat_color": cat_color,
                "status": "Queued",
                "sched_time": "",
            }
            queue.append(item)

            if len(queue) >= max_items:
                break

        if queue:
            log.info(f"[AutoScheduler] using AI schedule for hour {hour}: {len(queue)} items")
        return queue if queue else None

    # ── Internal: clock-driven queue ─────────────────────────────────

    def _build_from_clock(self, clock_id, max_items):
        slots = self.get_clock_slots(clock_id)
        if not slots:
            return self._fallback_queue(max_items)

        queue = []
        slot_count = len(slots)
        items_added = 0

        while items_added < max_items:
            slot = slots[self._slot_cursor % slot_count]
            self._slot_cursor += 1

            stype = slot["slot_type"]

            if stype == "Song":
                song = self._pick_song(slot)
                if song:
                    queue.append(song)
                    items_added += 1

            elif stype == "Jingle":
                jingle = self._pick_jingle(slot)
                if jingle:
                    queue.append(jingle)
                    items_added += 1

            elif stype == "Spot":
                queue.append(self._make_break_marker())
                items_added += 1

            elif stype == "Sweeper":
                sw = self._pick_sweeper(slot)
                if sw:
                    queue.append(self._make_sweeper_item(sw, slot))
                    items_added += 1

            # Safety: if we've cycled through all slots once without
            # adding anything, break to avoid infinite loop.
            if self._slot_cursor >= slot_count * 3 and items_added == 0:
                break

        return queue

    def _pick_song(self, slot):
        q = (
            "SELECT s.id, s.artist, s.title, s.duration_ms, s.file_path, "
            "s.bpm, s.year, c.name AS cat_name, c.color "
            "FROM songs s LEFT JOIN categories c ON s.category_id = c.id "
            "WHERE s.is_enabled = 1 "
            "AND s.file_path IS NOT NULL AND s.file_path != ''"
        )
        params = []

        cat_id = slot.get("category_id")
        if cat_id:
            q += " AND s.category_id = ?"
            params.append(int(cat_id))

        energy = slot.get("energy", "Any")
        if energy and energy != "Any":
            q += " AND s.energy = ?"
            params.append(energy)

        vocal = slot.get("vocal", "Any")
        if vocal and vocal != "Any":
            q += " AND s.vocal = ?"
            params.append(vocal)

        q += " ORDER BY RANDOM() LIMIT 1"

        rows = self.db.execute(q, tuple(params))
        if not rows:
            rows = self.db.execute(
                "SELECT s.id, s.artist, s.title, s.duration_ms, s.file_path, "
                "s.bpm, s.year, c.name, c.color "
                "FROM songs s LEFT JOIN categories c ON s.category_id = c.id "
                "WHERE s.is_enabled = 1 AND s.file_path IS NOT NULL AND s.file_path != '' "
                "ORDER BY RANDOM() LIMIT 1"
            )
        if not rows:
            return None

        r = rows[0]
        ms = r[3] or 0

        def ms_fmt(ms):
            if not ms:
                return "0:00"
            s = int(ms) // 1000
            return f"{s // 60}:{s % 60:02d}"

        return {
            "type": "song",
            "id": r[0],
            "artist": r[1] or "",
            "title": r[2] or "",
            "duration": ms_fmt(ms),
            "duration_secs": int(ms / 1000),
            "file_path": r[4] or "",
            "bpm": r[5] or 0,
            "year": r[6] or 0,
            "category": r[7] or "",
            "cat_color": r[8] or "#8B5CF6",
            "status": "Queued",
            "sched_time": "",
        }

    def _pick_jingle(self, slot):
        item_id = slot.get("item_id", 0)
        if item_id:
            rows = self.db.execute(
                "SELECT id, name, duration_ms, file_path FROM jingles WHERE id = ?",
                (int(item_id),),
            )
        else:
            rows = self.db.execute(
                "SELECT id, name, duration_ms, file_path FROM jingles "
                "WHERE is_enabled = 1 ORDER BY RANDOM() LIMIT 1"
            )
        if not rows:
            return None
        r = rows[0]
        ms = r[2] or 0

        def ms_fmt(ms):
            if not ms:
                return "0:00"
            s = int(ms) // 1000
            return f"{s // 60}:{s % 60:02d}"

        return {
            "type": "song",
            "id": r[0],
            "artist": "JINGLE",
            "title": r[1] or "Jingle",
            "duration": ms_fmt(ms),
            "duration_secs": int(ms / 1000),
            "file_path": r[3] or "",
            "bpm": 0,
            "year": 0,
            "category": "Jingle",
            "cat_color": "#F59E0B",
            "status": "Queued",
            "sched_time": "",
        }

    def _pick_sweeper(self, slot):
        item_id = slot.get("item_id", 0)
        if item_id:
            rows = self.db.execute(
                "SELECT id, name, file_path, duration_ms FROM sweepers WHERE id = ?",
                (int(item_id),),
            )
        else:
            rows = self.db.execute(
                "SELECT id, name, file_path, duration_ms FROM sweepers "
                "WHERE is_enabled = 1 ORDER BY RANDOM() LIMIT 1"
            )
        if not rows:
            return None
        return {"id": rows[0][0], "name": rows[0][1] or "", "file_path": rows[0][2] or ""}

    def _make_sweeper_item(self, sw, slot):
        dur_ms = 0
        rows = self.db.execute(
            "SELECT duration_ms FROM sweepers WHERE id = ?", (int(sw.get("id", 0)),)
        )
        if rows and rows[0][0]:
            dur_ms = rows[0][0]

        def ms_fmt(ms):
            if not ms:
                return "0:00"
            s = int(ms) // 1000
            return f"{s // 60}:{s % 60:02d}"

        return {
            "type": "song",
            "id": sw.get("id", 0),
            "artist": "SWEEPER",
            "title": sw.get("name", "Sweeper"),
            "duration": ms_fmt(dur_ms),
            "duration_secs": int(dur_ms / 1000) if dur_ms else 8,
            "file_path": sw.get("file_path", ""),
            "bpm": 0,
            "year": 0,
            "category": "Sweeper",
            "cat_color": "#8B5CF6",
            "status": "Queued",
            "sched_time": "",
            "is_sweeper": True,
            "sweeper_position": slot.get("sweeper_position", "START_OF_SONG"),
        }

    def _make_break_marker(self):
        return {
            "type": "break",
            "id": 0,
            "artist": "",
            "title": "Spot Break",
            "duration": "---",
            "duration_secs": 0,
            "file_path": "",
            "bpm": 0,
            "year": 0,
            "category": "Ad Break",
            "cat_color": "#F43F5E",
            "status": "Break",
            "sched_time": "",
            "spot_count": 0,
        }

    def _fallback_queue(self, max_items):
        """No clock assigned — random songs from the library."""
        rows = self.db.execute(
            "SELECT s.id, s.artist, s.title, s.duration_ms, s.file_path, "
            "s.bpm, s.year, c.name, c.color "
            "FROM songs s LEFT JOIN categories c ON s.category_id = c.id "
            "WHERE s.is_enabled = 1 "
            "AND s.file_path IS NOT NULL AND s.file_path != '' "
            "ORDER BY RANDOM() LIMIT ?",
            (max_items,),
        )

        def ms_fmt(ms):
            if not ms:
                return "0:00"
            s = int(ms) // 1000
            return f"{s // 60}:{s % 60:02d}"

        return [
            {
                "type": "song",
                "id": r[0],
                "artist": r[1] or "",
                "title": r[2] or "",
                "duration": ms_fmt(r[3]),
                "duration_secs": int((r[3] or 0) / 1000),
                "file_path": r[4] or "",
                "bpm": r[5] or 0,
                "year": r[6] or 0,
                "category": r[7] or "",
                "cat_color": r[8] or "#8B5CF6",
                "status": "Queued",
                "sched_time": "",
            }
            for r in rows
        ]
