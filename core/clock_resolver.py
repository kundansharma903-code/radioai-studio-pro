"""Single clock-resolution rule (2026-10-17).

Dispatch (SchedulerEngine.pick_next_item) honoured force_clocks first,
but the engine's active-clock indicator, Studio's header refresh and
Studio's auto-start only asked the weekly grid — so a forced hour aired
one clock while the UI showed (and auto-start keyed on) another. Every
caller now goes through ``resolve_clock``.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

log = logging.getLogger(__name__)


def resolve_clock(db, now: Optional[datetime] = None) -> Optional[dict]:
    """Force-clock override for ``now`` first, else the weekly grid cell.

    Returns ``{'id': int, 'name': str, 'forced': bool}`` or None when no
    clock is assigned. A failing force lookup is logged and ignored (the
    grid still resolves); a failing GRID lookup propagates so callers
    keep their existing error handling."""
    if now is None:
        now = datetime.now()
    fc = None
    try:
        getter = getattr(db, "get_force_clock_for", None)
        if getter is not None:
            fc = getter(now)
    except Exception as exc:
        log.debug(f"resolve_clock: force lookup failed: {exc}")
        fc = None
    if fc is not None:
        try:
            cid = fc["clock_id"]
        except (KeyError, IndexError, TypeError):
            cid = None
        if cid is not None:
            name = ""
            try:
                row = db.get_clock(int(cid))
                if row is not None:
                    name = str(row["name"] or "")
            except Exception:
                pass
            return {"id": int(cid), "name": name, "forced": True}
    row = db.get_active_clock(int(now.weekday()), int(now.hour))
    if not row:
        return None
    try:
        cid = int(row["id"])
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    try:
        name = str(row["name"] or "")
    except (KeyError, IndexError, TypeError):
        name = ""
    return {"id": cid, "name": name, "forced": False}
