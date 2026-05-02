"""RadioAI Studio Pro — Break Scheduler (notification-only)

This scheduler does NOT touch audio. It watches `campaign_schedule`
and fires `on_break_due(spots)` when the current 10-minute slot has
scheduled spots. The Studio screen (in JS) is responsible for
actually playing the spots on the active deck and crossfading back
to music afterwards.

Callbacks:
    on_break_due(spots)   — fired when a break slot is due. `spots`
                            is a list of {file_path, filename,
                            duration_ms, campaign_name, priority}
                            dicts, filtered to only include spots
                            whose files actually exist on disk.

Public query methods kept for the bridge UI:
    get_next_break()      — next break time string today, or None
    get_todays_breaks()   — list of all breaks today with counts
"""

import os
import threading
import time
from datetime import datetime, timedelta


class BreakScheduler:
    def __init__(self, db):
        self.db = db
        self.is_running = False
        self.on_break_due = None
        self._thread = None
        self._last_slot = None
        # Kept for bridge compatibility (`get_current_break`)
        self.current_break = None
        self._last_break_spots = []

    # ── Lifecycle ───────────────────────────────────────────────────
    def start(self):
        if self.is_running:
            return
        self.is_running = True
        self._thread = threading.Thread(target=self._monitor, daemon=True)
        self._thread.start()

    def stop(self):
        self.is_running = False

    # ── Monitor loop (10-minute slot ticks) ─────────────────────────
    def _monitor(self):
        while self.is_running:
            try:
                now = datetime.now()
                rounded = (now.minute // 5) * 5
                slot = f"{now.hour:02d}:{rounded:02d}"

                if slot != self._last_slot:
                    self._last_slot = slot
                    spots = self._get_spots_for_slot(slot, now)
                    if spots and self.on_break_due:
                        try:
                            self._last_break_spots = spots
                            self.current_break = spots
                            self.on_break_due(spots)
                        except Exception as e:
                            print(f"[BreakScheduler] on_break_due error: {e}")

                time.sleep(10)
            except Exception as e:
                print(f"[BreakScheduler] monitor error: {e}")
                time.sleep(10)

    # ── Query the DB for spots at a specific slot ───────────────────
    def _get_spots_for_slot(self, time_slot, now):
        try:
            dow = now.weekday()  # 0=Mon .. 6=Sun
            rows = self.db.execute(
                "SELECT sf.file_path, sf.filename, sf.duration_ms, "
                "c.name, c.priority "
                "FROM campaign_schedule cs "
                "JOIN campaigns c ON c.id = cs.campaign_id "
                "JOIN spot_files sf ON sf.campaign_id = c.id "
                "WHERE c.is_active = 1 "
                "AND sf.is_active = 1 "
                "AND sf.file_path IS NOT NULL AND sf.file_path != '' "
                "AND cs.day_of_week = ? "
                "AND cs.break_time = ? "
                "ORDER BY c.priority DESC, sf.display_order, sf.id",
                (dow, time_slot)
            )
            spots = []
            for r in rows:
                path = r[0]
                if path and os.path.exists(path):
                    spots.append({
                        'file_path': path,
                        'filename': r[1] or '',
                        'duration_ms': r[2] or 0,
                        'campaign_name': r[3] or '',
                        'priority': r[4] or '',
                    })
            return spots
        except Exception as e:
            print(f"[BreakScheduler] get_spots error: {e}")
            return []

    # ── Public queries used by the bridge UI ───────────────────────
    def get_next_break(self):
        try:
            now = datetime.now()
            dow = now.weekday()
            hhmm = now.strftime('%H:%M')
            rows = self.db.execute(
                "SELECT cs.break_time "
                "FROM campaign_schedule cs "
                "JOIN campaigns c ON c.id = cs.campaign_id "
                "WHERE c.is_active = 1 "
                "AND cs.day_of_week = ? "
                "AND cs.break_time > ? "
                "ORDER BY cs.break_time LIMIT 1",
                (dow, hhmm)
            )
            return rows[0][0] if rows else None
        except Exception as e:
            print(f"[BreakScheduler] next_break error: {e}")
            return None

    def get_todays_breaks(self):
        try:
            dow = datetime.now().weekday()
            rows = self.db.execute(
                "SELECT cs.break_time, "
                "GROUP_CONCAT(DISTINCT c.name), "
                "COUNT(DISTINCT sf.id) "
                "FROM campaign_schedule cs "
                "JOIN campaigns c ON c.id = cs.campaign_id "
                "LEFT JOIN spot_files sf ON sf.campaign_id = c.id AND sf.is_active = 1 "
                "WHERE c.is_active = 1 AND cs.day_of_week = ? "
                "GROUP BY cs.break_time "
                "ORDER BY cs.break_time",
                (dow,)
            )
            return [{
                'time': r[0],
                'campaigns': r[1] or '',
                'spot_count': r[2] or 0,
            } for r in rows]
        except Exception as e:
            print(f"[BreakScheduler] todays_breaks error: {e}")
            return []
