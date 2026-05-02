"""RadioAI Studio Pro — Song & Category Models"""

import json


class Category:
    """Maps to the categories table."""

    __slots__ = ("id", "name", "color", "description", "auto_rotate",
                 "separation_min", "display_order")

    def __init__(self, **kw):
        for s in self.__slots__:
            setattr(self, s, kw.get(s))

    @classmethod
    def from_row(cls, row):
        return cls(**{k: row[k] for k in row.keys()})

    def to_dict(self):
        return {s: getattr(self, s) for s in self.__slots__}

    @classmethod
    def all(cls, db):
        rows = db.execute("SELECT * FROM categories ORDER BY display_order")
        return [cls.from_row(r) for r in rows]

    @classmethod
    def get(cls, db, cat_id):
        rows = db.execute("SELECT * FROM categories WHERE id = ?", (cat_id,))
        return cls.from_row(rows[0]) if rows else None


class Song:
    """Maps to the songs table."""

    FIELDS = (
        "id", "artist", "title", "album", "playlister_code", "auto_code",
        "label", "cd_key", "barcode", "songwriter", "composer", "comments",
        "category_id", "era", "vocal", "priority", "year", "bpm", "energy",
        "duration_ms", "file_path", "is_enabled", "is_frozen", "entry_date",
        "start_point_ms", "intro_point_ms", "hook_in_ms", "hook_out_ms",
        "outro_point_ms", "mix_point_ms", "fade_in_ms", "fade_out_ms",
        "fade_out_position", "volume_level", "variable_length",
        "separation_minutes", "artist_sep_minutes",
    )

    def __init__(self, **kw):
        for f in self.FIELDS:
            setattr(self, f, kw.get(f))
        # Joined fields (not in songs table)
        self.category_name = kw.get("category_name")
        self.category_color = kw.get("category_color")

    @classmethod
    def from_row(cls, row):
        return cls(**{k: row[k] for k in row.keys()})

    def to_dict(self):
        d = {f: getattr(self, f) for f in self.FIELDS}
        d["category_name"] = self.category_name
        d["category_color"] = self.category_color
        d["duration_display"] = self._format_duration()
        return d

    def _format_duration(self):
        ms = self.duration_ms or 0
        total_sec = ms // 1000
        m, s = divmod(total_sec, 60)
        return f"{m}:{s:02d}"

    @classmethod
    def all(cls, db, filters=None):
        """Fetch all songs joined with category info. Optional filters dict."""
        sql = """
            SELECT s.*, c.name AS category_name, c.color AS category_color
            FROM songs s
            LEFT JOIN categories c ON s.category_id = c.id
        """
        conditions = []
        params = []

        if filters:
            if filters.get("search"):
                conditions.append("(s.artist LIKE ? OR s.title LIKE ? OR s.album LIKE ?)")
                q = f"%{filters['search']}%"
                params.extend([q, q, q])
            if filters.get("category_id"):
                conditions.append("s.category_id = ?")
                params.append(int(filters["category_id"]))
            if filters.get("era") and filters["era"] != "All":
                conditions.append("s.era = ?")
                params.append(filters["era"])
            if filters.get("vocal") and filters["vocal"] != "All":
                conditions.append("s.vocal = ?")
                params.append(filters["vocal"])
            if filters.get("energy") and filters["energy"] != "All":
                conditions.append("s.energy = ?")
                params.append(filters["energy"])
            if filters.get("enabled_only"):
                conditions.append("s.is_enabled = 1")
            if filters.get("bpm_min"):
                conditions.append("s.bpm >= ?")
                params.append(int(filters["bpm_min"]))
            if filters.get("bpm_max"):
                conditions.append("s.bpm <= ?")
                params.append(int(filters["bpm_max"]))
            if filters.get("priority"):
                conditions.append("s.priority = ?")
                params.append(int(filters["priority"]))
            if filters.get("year"):
                conditions.append("s.year = ?")
                params.append(int(filters["year"]))

        if conditions:
            sql += " WHERE " + " AND ".join(conditions)

        sql += " ORDER BY s.artist, s.title"
        rows = db.execute(sql, tuple(params))
        return [cls.from_row(r) for r in rows]

    @classmethod
    def get(cls, db, song_id):
        rows = db.execute(
            """SELECT s.*, c.name AS category_name, c.color AS category_color
               FROM songs s
               LEFT JOIN categories c ON s.category_id = c.id
               WHERE s.id = ?""",
            (song_id,),
        )
        return cls.from_row(rows[0]) if rows else None

    @classmethod
    def get_play_stats(cls, db, song_id):
        """Return broadcast play statistics for a song."""
        total = db.execute(
            "SELECT COUNT(*) FROM broadcast_log WHERE song_id = ?", (song_id,)
        )[0][0]

        this_month = db.execute(
            "SELECT COUNT(*) FROM broadcast_log WHERE song_id = ? "
            "AND played_at > datetime('now', '-30 days')", (song_id,)
        )[0][0]

        last_played_rows = db.execute(
            "SELECT played_at FROM broadcast_log WHERE song_id = ? "
            "ORDER BY played_at DESC LIMIT 1", (song_id,)
        )
        last_played = last_played_rows[0][0] if last_played_rows else None

        days_recorded = db.execute(
            "SELECT COUNT(DISTINCT date(played_at)) FROM broadcast_log WHERE song_id = ?",
            (song_id,),
        )[0][0]

        avg_per_day = round(total / max(days_recorded, 1), 1)

        return {
            "total_plays": total,
            "this_month": this_month,
            "last_played": last_played,
            "avg_per_day": avg_per_day,
        }

    def save(self, db):
        """Insert or update this song."""
        if self.id:
            fields = [f for f in self.FIELDS if f != "id"]
            sets = ", ".join(f"{f} = ?" for f in fields)
            vals = [getattr(self, f) for f in fields] + [self.id]
            db.execute(f"UPDATE songs SET {sets} WHERE id = ?", tuple(vals))
            return self.id
        else:
            fields = [f for f in self.FIELDS if f != "id" and getattr(self, f) is not None]
            cols = ", ".join(fields)
            placeholders = ", ".join("?" for _ in fields)
            vals = [getattr(self, f) for f in fields]
            return db.execute_insert(
                f"INSERT INTO songs ({cols}) VALUES ({placeholders})", tuple(vals)
            )

    def delete(self, db):
        if self.id:
            db.execute("DELETE FROM songs WHERE id = ?", (self.id,))
