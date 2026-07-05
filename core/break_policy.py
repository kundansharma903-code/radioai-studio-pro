"""
RadioAI — Break Policy (operator-approved design, 2026-07-04).

Commercial-FM style ad discipline as a PURE LOGIC module — no Qt, no
DB, no engine imports. Studio calls these helpers; everything here is
unit-testable in isolation and the whole feature sits BEHIND the
``break_policy_enabled`` master toggle (default OFF = the original
per-campaign firing stays byte-identical).

The three problems this solves (operator, peak season):
  1. Ads every 5-10 min chopped the music flow → ads now consolidate
     into fixed break windows (:15 / :30 / :45 by default).
  2. Community-radio compliance: max N ad-minutes per clock hour
     (default 11:00, operator-editable) — overflow DEFERS to the next
     hour's first window, never drops.
  3. Competitive separation: same ad-category clients (3 schools…)
     must not air back-to-back → round-robin interleave by category.

Settings keys (read by callers, seeded in database/seeds.sql):
  break_policy_enabled              "0"/"1"   master valve (default 0)
  break_policy_windows              "15,30,45" minutes-of-hour
  break_policy_max_ad_seconds_hour  "660"     11:00 budget
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional


DEFAULT_WINDOWS = (15, 30, 45)
DEFAULT_MAX_AD_SECONDS = 660          # 11:00 per clock hour


# ── Window math ──────────────────────────────────────────────────────────

def parse_windows(raw: str) -> tuple:
    """'15,30,45' → (15, 30, 45). Bad/empty input → defaults. Values
    clamped to 0-59, deduped, sorted."""
    try:
        vals = sorted({int(p) % 60 for p in str(raw or "").split(",")
                       if str(p).strip() != ""})
        return tuple(vals) if vals else DEFAULT_WINDOWS
    except (ValueError, TypeError):
        return DEFAULT_WINDOWS


def next_window_at(now: datetime, windows: tuple = DEFAULT_WINDOWS
                   ) -> datetime:
    """The first window time at/after `now`. An ad due 9:05 releases
    at 9:15; due 9:31 → 9:45; due 9:50 → 10:15 (next hour's first
    window). Exactly 9:15:00 → 9:15."""
    windows = tuple(sorted(int(w) % 60 for w in windows)) \
        or DEFAULT_WINDOWS
    for m in windows:
        cand = now.replace(minute=m, second=0, microsecond=0)
        if cand >= now:
            return cand
    return (now.replace(minute=windows[0], second=0, microsecond=0)
            + timedelta(hours=1))


def is_window_open(now: datetime, windows: tuple = DEFAULT_WINDOWS
                   ) -> bool:
    """True during the release minute itself (9:15:00–9:15:59)."""
    return int(now.minute) in set(int(w) for w in windows)


def first_window_next_hour(now: datetime,
                           windows: tuple = DEFAULT_WINDOWS) -> datetime:
    windows = tuple(sorted(windows)) or DEFAULT_WINDOWS
    return (now.replace(minute=0, second=0, microsecond=0)
            + timedelta(hours=1)).replace(minute=windows[0])


# ── Hourly ad budget ─────────────────────────────────────────────────────

def hour_start(now: datetime) -> datetime:
    return now.replace(minute=0, second=0, microsecond=0)


def budget_split(pool: list, aired_seconds: float,
                 max_seconds: int) -> tuple:
    """Split the release pool into (fits, deferred) against the hour's
    remaining ad budget. `pool` entries are dicts carrying at least
    ``duration_ms``; order is preserved (interleave AFTER splitting).
    Entries with unknown duration (0) count as 30s — the station
    average — so a missing tag can't smuggle unlimited ads through.
    """
    remaining = float(max_seconds) - float(aired_seconds or 0.0)
    fits: list = []
    deferred: list = []
    for entry in pool:
        dur_s = float(entry.get("duration_ms") or 0) / 1000.0
        if dur_s <= 0:
            dur_s = 30.0
        if dur_s <= remaining:
            fits.append(entry)
            remaining -= dur_s
        else:
            deferred.append(entry)
    return fits, deferred


# ── Competitive separation (category interleave) ─────────────────────────

def interleave_by_category(pool: list,
                           prev_category: Optional[str] = None) -> list:
    """Order the release batch so same-category ads are never adjacent
    when mathematically possible (round-robin, largest-remaining
    category first — the classic reorganize-with-distance approach).

    Entries are dicts with a ``category`` key (None/'' → 'others').
    ``prev_category`` — category of the LAST ad that aired before this
    batch, so the seam between two chains keeps the rule too.
    Returns a NEW list; input order inside one category is preserved
    (FIFO fairness between a client's own rotations)."""
    from collections import OrderedDict

    groups: "OrderedDict[str, list]" = OrderedDict()
    for e in pool:
        key = (str(e.get("category") or "").strip().lower()
               or "others")
        groups.setdefault(key, []).append(e)

    out: list = []
    last = (str(prev_category or "").strip().lower() or None)
    while any(groups.values()):
        # candidates: non-empty categories, largest first; skip `last`
        # unless it is the ONLY category left (unavoidable adjacency).
        nonempty = [(k, v) for k, v in groups.items() if v]
        nonempty.sort(key=lambda kv: -len(kv[1]))
        chosen = None
        for k, v in nonempty:
            if k != last:
                chosen = k
                break
        if chosen is None:
            chosen = nonempty[0][0]      # forced adjacency
        out.append(groups[chosen].pop(0))
        last = chosen
    return out


def has_adjacent_same_category(ordered: list) -> bool:
    """Audit helper: True when two neighbours share a category."""
    def _cat(e):
        return (str(e.get("category") or "").strip().lower()
                or "others")
    return any(_cat(a) == _cat(b)
               for a, b in zip(ordered, ordered[1:]))


# ── Meter math ───────────────────────────────────────────────────────────

def meter_state(aired_seconds: float, pending_seconds: float,
                max_seconds: int) -> dict:
    """Everything the bottom-bar widget needs, precomputed:
    {aired_s, pending_s, max_s, fraction, level} —
    level: 'ok' < 80% ≤ 'warn' < 100% ≤ 'over'."""
    max_s = max(1, int(max_seconds))
    aired = max(0.0, float(aired_seconds or 0))
    pending = max(0.0, float(pending_seconds or 0))
    frac = aired / max_s
    projected = (aired + pending) / max_s
    if frac >= 1.0:
        level = "over"
    elif projected >= 1.0 or frac >= 0.8:
        level = "warn"
    else:
        level = "ok"
    return {"aired_s": aired, "pending_s": pending, "max_s": max_s,
            "fraction": min(1.0, frac), "level": level}


def fmt_mmss(seconds: float) -> str:
    s = max(0, int(round(seconds)))
    return f"{s // 60}:{s % 60:02d}"


# ── Auto-Distribute (Spot Programming) ───────────────────────────────────

def auto_distribute_slots(rotations: int, start_hour: int,
                          end_hour: int,
                          windows: tuple = DEFAULT_WINDOWS) -> list:
    """Pick `rotations` break-window times, evenly spread across
    [start_hour, end_hour) — the one-click replacement for hand-
    assigning a client's "20 rotations between 8 AM and 9 PM".
    Returns 'HH:MM'
    strings sorted chronologically; capped at the number of available
    window slots in the range. Deterministic (no randomness) so the
    generated list doubles as the CLIENT TIME SHEET."""
    try:
        rotations = int(rotations)
        start_hour = max(0, min(23, int(start_hour)))
        end_hour = max(1, min(24, int(end_hour)))
    except (TypeError, ValueError):
        return []
    if rotations <= 0 or end_hour <= start_hour:
        return []
    windows = tuple(sorted(int(w) % 60 for w in windows)) \
        or DEFAULT_WINDOWS
    slots = [f"{h:02d}:{w:02d}"
             for h in range(start_hour, end_hour)
             for w in windows]
    n = len(slots)
    if rotations >= n:
        return slots
    # Even fractional stepping → unique indices → top-up if rounding
    # collapsed any.
    step = n / rotations
    idx = sorted({min(n - 1, int(i * step)) for i in range(rotations)})
    spare = (i for i in range(n) if i not in set(idx))
    while len(idx) < rotations:
        idx.append(next(spare))
    return [slots[i] for i in sorted(idx)]
