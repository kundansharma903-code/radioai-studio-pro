"""
RadioAI Studio Pro — Category Auto-Grid Builder.

Operator concept (2026-07-02): tag a song category with air-time
dayparts ("Morning Vibes → 10-11 daily") and the system builds the
auto_schedule grid itself — the scheduler + Rotation AI then run the
day exactly as if the operator had hand-assigned clocks.

Rules (operator-approved design):
  • One PERMANENT auto-clock per unique category-set (never a new
    clock per day — Rotation AI plans reference clock ids).
  • Clock template = operator's pattern: Sweeper before EVERY song;
    a Jingle slot when any active jingle exists; otherwise the same
    pattern without it. Overlapping categories on one hour → ONE
    mixed clock with alternating song slots.
  • The builder fills ONLY empty cells (or cells it placed itself —
    tracked in auto_grid_cells). Manual assignments + force_clocks
    are sacred and always win.
  • Deterministic + idempotent: same tags → same grid, every run.
  • Removing a tag clears the builder's OWN cells for those hours
    (never a manually-overwritten one).

Triggering: boot + scheduler day-rollover + "Rebuild Now" (hub) +
after saving Air Time in Edit Categories. All call build_grid(db).
"""

from __future__ import annotations

import logging

log = logging.getLogger("AutoGrid")

AUTO_CLOCK_PREFIX = "AUTO · "


def _template_slots(db, cat_ids: list[int]) -> list[dict]:
    """Operator's pattern per hour-recipe. Slots cycle continuously in
    the scheduler, so one compact unit per category is enough:
    [Sweeper → Song(cat)] per category (alternating when mixed),
    plus one Jingle slot when the station has any enabled jingle."""
    has_jingle = False
    try:
        rows = db.get_jingles() or []
        for j in rows:
            keys = j.keys() if hasattr(j, "keys") else []
            if "is_enabled" not in keys or int(j["is_enabled"] or 0):
                has_jingle = True
                break
    except Exception:
        has_jingle = False
    slots: list[dict] = []
    for cid in cat_ids:
        slots.append({"slot_type": "sweeper",
                      "selection_mode": "random",
                      "category_id": None})
        slots.append({"slot_type": "song",
                      "selection_mode": "random_from_category",
                      "category_id": int(cid)})
    if has_jingle:
        slots.append({"slot_type": "jingle",
                      "selection_mode": "random",
                      "category_id": None})
    return slots


def _clock_label(db, cat_ids: list[int]) -> str:
    names = []
    for cid in cat_ids:
        try:
            row = db._conn().execute(
                "SELECT name FROM categories WHERE id = ?",
                [int(cid)]).fetchone()
            names.append(str(row[0]).strip() if row else f"#{cid}")
        except Exception:
            names.append(f"#{cid}")
    return AUTO_CLOCK_PREFIX + " + ".join(names)


def _get_or_make_auto_clock(db, cat_ids: list[int]) -> int:
    """Permanent clock per category-set. Slots are re-saved on every
    build (idempotent) so template/jingle changes propagate; the id
    never changes, keeping Rotation AI decisions valid."""
    key = "+".join(str(c) for c in sorted(int(c) for c in cat_ids))
    clock_id = db.get_auto_grid_clock_id(key)
    label = _clock_label(db, sorted(int(c) for c in cat_ids))
    if clock_id is not None:
        row = db._conn().execute(
            "SELECT id FROM clocks WHERE id = ?", [clock_id]).fetchone()
        if row is None:
            clock_id = None            # clock was deleted — recreate
    if clock_id is None:
        clock_id = db.create_clock(label)
        db.set_auto_grid_clock_id(key, clock_id)
        log.info(f"[auto-grid] created clock {clock_id} {label!r}")
    else:
        try:
            db._conn().execute(
                "UPDATE clocks SET name = ? WHERE id = ?",
                [label, int(clock_id)])
            db._conn().commit()
        except Exception:
            pass
    db.save_clock_slots(clock_id, _template_slots(
        db, sorted(int(c) for c in cat_ids)))
    return int(clock_id)


def build_grid(db) -> dict:
    """Reconcile the auto_schedule grid with the category daypart
    tags. Returns a summary dict for the hub status line / logs."""
    summary = {"placed": 0, "unchanged": 0, "skipped_manual": 0,
               "cleared": 0, "clocks": 0, "error": None}
    try:
        parts = db.get_all_category_dayparts()
        desired: dict[tuple[int, int], set] = {}
        for p in parts:
            dow = p.get("day_of_week")
            days = range(7) if dow is None else [int(dow)]
            h1, h2 = int(p["hour_start"]), int(p["hour_end"])
            span = range(h1, h2) if h2 > h1 else \
                list(range(h1, 24)) + list(range(0, h2))  # overnight wrap
            for d in days:
                for h in span:
                    desired.setdefault((int(d), int(h) % 24),
                                       set()).add(int(p["category_id"]))

        grid = db.get_auto_schedule_grid()          # (d,h) -> clock_id
        own = db.get_auto_grid_cell_records()       # (d,h) -> clock_id

        made_clocks: dict[str, int] = {}
        for (d, h), cats in sorted(desired.items()):
            key = "+".join(str(c) for c in sorted(cats))
            if key not in made_clocks:
                made_clocks[key] = _get_or_make_auto_clock(
                    db, sorted(cats))
            clock_id = made_clocks[key]
            cur = grid.get((d, h))
            rec = own.get((d, h))
            if cur is not None and rec is None:
                summary["skipped_manual"] += 1      # operator's cell
                continue
            if cur is not None and rec is not None and cur != rec:
                # Operator OVERWROTE one of our cells — it is manual
                # now; release our claim and never touch it again.
                db.remove_auto_grid_cell_record(d, h)
                summary["skipped_manual"] += 1
                continue
            if cur == clock_id:
                summary["unchanged"] += 1
                continue
            db.set_auto_schedule_cell(d, h, clock_id)
            db.record_auto_grid_cell(d, h, clock_id)
            summary["placed"] += 1

        # Tags removed → clear OUR stale cells (never overwritten ones)
        for (d, h), cid in list(own.items()):
            if (d, h) in desired:
                continue
            if grid.get((d, h)) == cid:
                db.clear_auto_schedule_cell(d, h)
                summary["cleared"] += 1
            db.remove_auto_grid_cell_record(d, h)

        summary["clocks"] = len(made_clocks)
        log.info(f"[auto-grid] build done: {summary}")
    except Exception as exc:
        summary["error"] = str(exc)
        log.error(f"[auto-grid] build FAILED: {exc}", exc_info=True)
    return summary
