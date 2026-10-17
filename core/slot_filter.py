"""
RadioAI Studio Pro — what a clock slot's filter_json really asks for.

The Clock Editor stores a plain category choice as a filter:
category_id = 9 AND filter_json = '{"sound_code": "Test 500"}', and an
"All Songs" slot as filter_json = '{}'. The scheduler treated ANY
non-empty filter_json string as an operator pin, so for every slot
built in the Clock Editor (found 2026-10-16):
  • Rotation AI and the approved daily plan never applied, and
  • an "All Songs" slot drew from the first 240 songs by row id only
    (the filter query has a LIMIT and no ORDER BY).

effective_filter() returns only the constraints that are a real
filter. A filter that just names the slot's category — or nothing at
all — is no filter, so those slots behave exactly like an AUTO clock's
category slot. Era / vocal / year / priority / BPM stay real filters.
"""

from __future__ import annotations

import json
from typing import Optional

_EMPTY = (None, "", "All", "all", "(All)")


def _keys(slot):
    return slot.keys() if hasattr(slot, "keys") else ()


def _spec(slot) -> dict:
    raw = slot["filter_json"] if "filter_json" in _keys(slot) else None
    if not raw:
        return {}
    if isinstance(raw, dict):
        spec = raw
    else:
        try:
            spec = json.loads(raw)
        except (TypeError, ValueError):
            return {}
    if not isinstance(spec, dict):
        return {}
    return {k: v for k, v in spec.items()
            if k != "category_id" and v not in _EMPTY}


def effective_filter(slot) -> Optional[dict]:
    """The slot's real filter constraints, or None when it has none."""
    spec = _spec(slot)
    if set(spec) <= {"sound_code"}:
        return None
    return spec


def sound_code_only(slot) -> Optional[str]:
    """Category NAME when the filter is nothing but a sound_code (the
    caller resolves it when the slot has no category_id of its own)."""
    spec = _spec(slot)
    if set(spec) == {"sound_code"}:
        return str(spec["sound_code"])
    return None
