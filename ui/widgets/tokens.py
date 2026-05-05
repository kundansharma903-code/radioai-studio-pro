"""
Premium-theme design tokens — color constants + font helpers.

Single source of truth for the new premium dark theme. The original
`_tokens.py` module is preserved for back-compat with older screens
(Studio, Songs Library, Spots, Instant Jingles, Control Panel). New
screens written under the premium theme should import from here.

This module re-exports the base palette / font helpers from `_tokens`
and adds the extended premium-theme constants (page gradient stops,
card surface gradients, border + text variants).
"""

from __future__ import annotations

from PyQt6.QtGui import QColor

# Re-export everything from the legacy tokens module so old + new
# screens can both import from `ui.widgets.tokens` going forward.
from ui.widgets._tokens import (    # noqa: F401  (re-export)
    inter, mono, rgba, qcolor,
    INTER_FAMILY, ROBOTO_MONO,
    BG_BASE, BG_DARK, BG_PANEL, BG_CARD, BG_CARD_DK, BG_ELEVATED, BG_PURPLE_DK,
    TEXT_PRI, TEXT_SEC, TEXT_MUTED, TEXT_DIM,
    BORDER_RGBA, BORDER_HOVER,
    CYAN, CYAN_LIGHT,
    PURPLE, PURPLE_LIGHT, PURPLE_DARK,
    GREEN, GREEN_LIGHT,
    AMBER, AMBER_LIGHT,
    RED, RED_LIGHT,
    PINK, PINK_LIGHT,
    TEAL, TEAL_LIGHT,
)


# ── Premium theme — page-level gradient stops ───────────────────────────

COL_BG_TOP = "#0a0d1a"
COL_BG_MID = "#06080f"
COL_BG_BOT = "#020308"


# ── Premium theme — card surface gradients ──────────────────────────────

# Use as rgba(...) strings for QSS, or via _qcolor() for QPainter.
COL_CARD_TOP = "rgba(14,16,32,0.95)"
COL_CARD_BOT = "rgba(7,9,18,0.95)"


# ── Borders + hairlines ─────────────────────────────────────────────────

# QColor variants for QPainter (rgba(255,255,255,0.06)-ish)
COL_BORDER_FAINT     = QColor(255, 255, 255, 15)
COL_BORDER_HAIRLINE  = QColor(255, 255, 255, 10)


# ── Premium accent palette (full per-tile set) ──────────────────────────

# Most are already exported from _tokens; aliases below cover the
# darker / mid variants that the premium theme introduced for tile
# accent gradients (top stripe + glow shadow chains).

COL_CYAN     = CYAN;        COL_CYAN_LT     = CYAN_LIGHT
COL_CYAN_DK  = "#0e7490";   COL_CYAN_MD     = "#0891b2"

COL_PURPLE     = PURPLE;        COL_PURPLE_LT   = PURPLE_LIGHT
COL_PURPLE_DEEP = "#7c3aed";    COL_PURPLE_MID  = "#8b5cf6"

COL_GREEN    = GREEN;       COL_GREEN_LT    = GREEN_LIGHT
COL_GREEN_DK = "#047857";   COL_GREEN_MD    = "#059669"

COL_AMBER    = AMBER;       COL_AMBER_LT    = AMBER_LIGHT
COL_AMBER_DK = "#b45309";   COL_AMBER_MD    = "#d97706"

COL_ROSE     = "#f43f5e";   COL_ROSE_LT     = "#fb7185"
COL_ROSE_DK  = "#be123c";   COL_ROSE_MD     = "#e11d48"

COL_PINK     = PINK;        COL_PINK_LT     = PINK_LIGHT
COL_PINK_DK  = "#be185d";   COL_PINK_MD     = "#db2777"

COL_TEAL     = TEAL;        COL_TEAL_LT     = "#5eead4"
COL_TEAL_DK  = "#0f766e";   COL_TEAL_MD     = "#0d9488"


# ── Text colors (premium-theme aliases for clarity) ─────────────────────

COL_TEXT_PRIMARY   = TEXT_PRI
COL_TEXT_SECONDARY = TEXT_SEC
COL_TEXT_MUTED     = TEXT_MUTED
COL_TEXT_DIM       = TEXT_DIM


def qcolor_a(hex_color: str, alpha: float = 1.0) -> QColor:
    """hex like '#06b6d4' + 0..1 alpha → QColor.

    Helper used inside paintEvents where rgba()-string strings can't be
    consumed (QPainter wants QColor / QBrush)."""
    c = QColor(hex_color)
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c
