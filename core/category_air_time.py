"""
RadioAI Studio Pro — Category Air Time applied to ANY clock (2026-10-16).

Operator concept: a song category tagged with an air time ("A → 10 AM
and 10 PM") must air at that time whatever clock sits on the grid —
an AUTO clock, a hand-assigned one or a force clock.

Rule (operator-approved):
  • For each category tagged on the current hour that the clock does
    NOT already contain, ONE of the clock's other song categories is
    picked at random and — for this hour only — every free song slot
    of that category draws from the tagged category instead.
    Clock abc = B, C, D at 10 AM with A tagged → e.g. B, A, D.
  • The clock itself is never edited. The same clock on an untagged
    hour plays exactly as built, and the Clock Editor keeps working.
  • The pick is seeded by (date, hour, clock, tagged category): stable
    for the whole hour — so Up Coming matches what airs — and it moves
    to a different category on another day.
  • Slots the operator pinned (specific song / artist, filter, locked
    item) are never touched. A song slot with no category ("All
    Songs") counts as one replaceable choice.
  • A tagged category with no enabled songs is ignored, so a tag can
    never turn a slot into random filler.

Pure functions — no Qt, no DB. SchedulerEngine feeds them.
"""

from __future__ import annotations

import random
from typing import Iterable, Optional

#: slot key marking a slot rewritten by an air-time tag; value is the
#: category id it replaced (None = an "All Songs" slot).
AIR_TIME_FROM = "_air_time_from"

_LOCK_FIELDS = ("specific_song_id", "specific_artist_id", "item_id")


def _keys(slot) -> Iterable[str]:
    return slot.keys() if hasattr(slot, "keys") else ()


def _get(slot, field):
    return slot[field] if field in _keys(slot) else None


def _cat(slot) -> Optional[int]:
    v = _get(slot, "category_id")
    try:
        v = int(v) if v else None
    except (TypeError, ValueError):
        return None
    return v if v and v > 0 else None


def _is_song(slot) -> bool:
    t = str(_get(slot, "slot_type") or "").strip().lower()
    return t == "song"


def _is_free_song_slot(slot) -> bool:
    """A song slot the operator did not pin to something specific."""
    if not _is_song(slot):
        return False
    if any(_get(slot, f) for f in _LOCK_FIELDS):
        return False
    # A filter that only names the category (how the Clock Editor saves
    # a category pick) is not a pin — core.slot_filter.
    from core.slot_filter import effective_filter
    return effective_filter(slot) is None


def _hour_span(h1: int, h2: int) -> list[int]:
    """Same span rule as core.auto_grid_builder (overnight wrap)."""
    if h2 > h1:
        return list(range(h1, h2))
    return list(range(h1, 24)) + list(range(0, h2))


def tagged_categories_at(parts: Iterable[dict], day_of_week: int,
                         hour: int) -> list[int]:
    """Category ids whose air-time tags cover (day_of_week, hour).
    `parts` = rows from db.get_all_category_dayparts()."""
    out: set[int] = set()
    for p in parts or []:
        try:
            dow = p.get("day_of_week")
            if dow is not None and int(dow) != int(day_of_week):
                continue
            span = _hour_span(int(p["hour_start"]), int(p["hour_end"]))
            if int(hour) % 24 in [h % 24 for h in span]:
                out.add(int(p["category_id"]))
        except (TypeError, ValueError, KeyError):
            continue
    return sorted(out)


def apply_air_time(slots: list, tagged: Iterable[int], seed: str,
                   names: Optional[dict] = None) -> tuple[list, dict]:
    """Return (slots_for_this_hour, swaps).

    `swaps` maps each tagged category placed → the category it
    replaced (None = an "All Songs" slot). Slots that change come
    back as dict copies carrying AIR_TIME_FROM; everything else is
    returned as-is. A tag already present in the clock, or with no
    category left to replace, is simply not placed."""
    slots = list(slots or [])
    tagged = sorted({int(t) for t in (tagged or []) if t})
    if not tagged or not slots:
        return slots, {}

    present = {_cat(s) for s in slots if _is_song(s)}
    candidates = sorted(
        {_cat(s) for s in slots if _is_free_song_slot(s)}
        - set(tagged),
        key=lambda c: -1 if c is None else c)

    swaps: dict = {}
    for cat in tagged:
        if cat in present or not candidates:
            continue
        rng = random.Random(f"{seed}|{cat}")
        old = rng.choice(candidates)
        candidates.remove(old)
        swaps[cat] = old
    if not swaps:
        return slots, {}

    by_old = {old: new for new, old in swaps.items()}
    out = []
    for s in slots:
        if _is_free_song_slot(s) and _cat(s) in by_old:
            d = {k: s[k] for k in _keys(s)}
            d[AIR_TIME_FROM] = _cat(s)
            d["category_id"] = by_old[_cat(s)]
            # The filter named the OLD category by name — clear it or
            # the scheduler would keep drawing from the old category.
            d["filter_json"] = None
            d["cat_name"] = (names or {}).get(by_old[_cat(s)])
            # The old slot's energy / vocal preference was chosen for
            # the OLD category; kept here it could empty the tagged
            # pool and drop the slot to random filler.
            d["energy_pref"] = "Any"
            d["vocal_pref"] = "Any"
            out.append(d)
        else:
            out.append(s)
    return out, swaps
